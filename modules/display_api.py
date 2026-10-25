"""WebSocket for PulseDeck Panel (the Android information display): /api/v1/display.

Runs only on the TLS server (API v1), behind the same guard as every other v1 route:
LAN peers only and a valid per-device token (pairing by code, revocable on the PC).
Protocol: docs/PANEL_PROTOCOL.md.

Server -> panel: hello, metrics (every METRICS_SECONDS), media (on change), error.
Panel -> server: {"type": "command", "action": "toggle" | "next" | "prev"}, {"type": "ping"},
{"type": "subscribe", "metrics": false} (the panel runs in the background: send media only).
"""
import asyncio
import concurrent.futures
import logging
import socket
import time

from aiohttp import WSMsgType, web

from modules import mobile_access

logger = logging.getLogger(__name__)
PROTOCOL = 1
METRICS_SECONDS = 1.5
MEDIA_SECONDS = 1.0
MEDIA_RESYNC_SECONDS = 5.0      # position is re-sent this often; the panel interpolates in between
AUTH_RECHECK_SECONDS = 5.0      # a revoked phone is disconnected within this time
COMMANDS = {"toggle", "next", "prev", "seek", "volume"}
MIN_INTERVAL, MAX_INTERVAL = 1.0, 10.0      # metrics period the panel may ask for, seconds
CLOSE_REVOKED = 4001


def _volume_labels():
    labels = {}
    try:
        import psutil
        import win32api
        for part in psutil.disk_partitions(all=False):
            try:
                labels[part.mountpoint.rstrip("\\")] = win32api.GetVolumeInformation(part.mountpoint)[0]
            except Exception:  # noqa: BLE001 - removable drive without media, access denied
                continue
    except ImportError:
        pass
    return labels


class MetricsReader:
    """MetricsSampler in its own thread: Windows performance counters belong to the thread
    that opened them, so every sample for this panel runs on the same worker."""

    def __init__(self):
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="PulseDeck-panel")
        self.sampler = None
        self.labels = {}

    def _sample(self):
        if self.sampler is None:
            from pulse_pc.services.system.metrics import MetricsSampler
            self.sampler = MetricsSampler()
            self.labels = _volume_labels()
        return metrics_message(self.sampler.sample(), self.labels)

    async def read(self):
        return await asyncio.get_running_loop().run_in_executor(self.pool, self._sample)

    def close(self):
        def stop():
            if self.sampler:
                self.sampler.close()
        self.pool.submit(stop)
        self.pool.shutdown(wait=False)


def _round(value, digits=1):
    return None if value is None else round(float(value), digits)


def metrics_message(snap, labels=None):
    """Snapshot -> wire format. Unknown values are null, never invented."""
    labels = labels or {}
    return {
        "type": "metrics",
        "cpu": {"load": _round(snap.cpu), "temp": None, "name": getattr(snap, "cpu_name", "") or None,
                "cores": getattr(snap, "cpu_cores", None)},
        # GPU load = busiest engine over all adapters (like Task Manager); name/memory = main card.
        "gpu": {"load": _round(snap.gpu), "temp": None, "name": snap.gpu_name or None,
                "memory_total": getattr(snap, "gpu_memory_total", None) or None,
                "memory_used": getattr(snap, "gpu_memory_used", None)},
        "ram": {"percent": _round(snap.ram), "used": snap.ram_used, "total": snap.ram_total},
        "net": {"down": _round(getattr(snap, "net_down", None), 0), "up": _round(getattr(snap, "net_up", None), 0)},
        "disks": [{"name": disk.mount, "label": labels.get(disk.mount, ""), "total": disk.total,
                   "free": max(0, disk.total - disk.used)} for disk in snap.disks],
    }


_SOURCES = (
    ("spotify", "Spotify"), ("yandex", "Яндекс Музыка"), ("zunemusic", "Медиаплеер"), ("zune", "Медиаплеер"),
    ("wmplayer", "Проигрыватель Windows"), ("vlc", "VLC"), ("aimp", "AIMP"), ("foobar", "foobar2000"),
    ("chrome", "Google Chrome"), ("msedge", "Microsoft Edge"), ("firefox", "Firefox"), ("opera", "Opera"),
    ("brave", "Brave"), ("vivaldi", "Vivaldi"), ("telegram", "Telegram"), ("applemusic", "Apple Music"),
    ("itunes", "iTunes"), ("deezer", "Deezer"), ("soundcloud", "SoundCloud"), ("pulsedeck", "PulseDeck"),
)


def source_name(source):
    """«Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic» -> «Медиаплеер»."""
    low = (source or "").lower()
    for needle, name in _SOURCES:
        if needle in low:
            return name
    tail = (source or "").split("!")[-1].split("\\")[-1]
    return tail.rsplit(".", 1)[-1] if "." in tail and not tail.lower().endswith(".exe") else tail.removesuffix(".exe")


def media_message(player):
    """Player state from the local API -> wire format; None when nothing can be shown."""
    if not player or player.get("status") not in ("playing", "paused") or not (player.get("title") or "").strip():
        return {"type": "media", "session": None}
    return {"type": "media", "session": {
        "title": player.get("title") or "",
        "artist": player.get("artist") or "",
        "album": player.get("album") or "",
        "status": player["status"],
        "position": _round(player.get("position") or 0.0),
        "duration": _round(player.get("duration") or 0.0),
        "source": source_name(player.get("source") or player.get("id") or ""),
        "cover": player.get("cover") or "",
        "can_prev": bool(player.get("can_prev", True)),
        "can_next": bool(player.get("can_next", True)),
    }}


def _same_track(a, b):
    """Equal apart from the playback position (which moves every second)."""
    if (a or {}).get("system_volume") != (b or {}).get("system_volume"):
        return False
    if (a or {}).get("session") is None or (b or {}).get("session") is None:
        return a == b
    strip = lambda m: {k: v for k, v in m["session"].items() if k != "position"}   # noqa: E731
    return strip(a) == strip(b)


def system_volume_state():
    """{level 0..100, muted} of the PC speakers, or None without pycaw."""
    from modules import volume
    return volume.get() if volume.AVAILABLE else None


def add_display_route(app, current_player, control_player, workstation_locked):
    async def run_command(action, value):
        """Playback and PC volume only; values are validated, nothing else can run."""
        if action == "seek":
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ValueError("Позиция — число секунд.")
            await control_player("seek", float(value))
        elif action == "volume":
            from modules import volume
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
                raise ValueError("Громкость — число от 0 до 100.")
            if not volume.AVAILABLE:
                raise ValueError("Громкость ПК недоступна: не установлен pycaw.")
            await asyncio.to_thread(volume.set_level, value)
        else:
            await control_player(action)

    async def display(request):
        token = request.headers.get("Authorization", "")[7:]     # already checked by the guard
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096)
        await ws.prepare(request)
        device = await asyncio.to_thread(mobile_access.authenticate, token)
        logger.info("Панель подключена: %s (%s)", (device or {}).get("name", "?"), request.remote)
        reader = MetricsReader()
        send_lock = asyncio.Lock()
        wants = {"metrics": True, "interval": METRICS_SECONDS}

        async def send(message):
            async with send_lock:
                if not ws.closed:
                    await ws.send_json(message)

        async def metrics_loop():
            while not ws.closed:
                if not wants["metrics"]:            # panel in the background: no sampling at all
                    await asyncio.sleep(METRICS_SECONDS)
                    continue
                try:
                    await send(await reader.read())
                except (ConnectionError, RuntimeError):
                    return
                except Exception:  # noqa: BLE001 - keep the panel alive after a bad sample
                    logger.exception("Не удалось собрать показатели для панели")
                await asyncio.sleep(wants["interval"])

        async def media_loop():
            last, sent_at = None, 0.0
            while not ws.closed:
                try:
                    message = media_message(await current_player())
                    message["system_volume"] = await asyncio.to_thread(system_volume_state)
                    now = time.monotonic()
                    playing = (message["session"] or {}).get("status") == "playing"
                    if not _same_track(message, last) or (playing and now - sent_at >= MEDIA_RESYNC_SECONDS):
                        await send(message)
                        last, sent_at = message, now
                except (ConnectionError, RuntimeError):
                    return
                except Exception:  # noqa: BLE001 - media sessions disappear mid-read
                    logger.debug("Состояние плеера недоступно", exc_info=True)
                await asyncio.sleep(MEDIA_SECONDS)

        async def auth_loop():
            # Revocation on the PC must cut an open connection, not only new ones.
            while not ws.closed:
                await asyncio.sleep(AUTH_RECHECK_SECONDS)
                if not await asyncio.to_thread(mobile_access.authenticate, token):
                    logger.info("Доступ панели отозван, соединение закрыто.")
                    await ws.close(code=CLOSE_REVOKED, message=b"revoked")
                    return

        await send({"type": "hello", "protocol": PROTOCOL, "app": "PulseDeck", "name": socket.gethostname(),
                    "metrics_interval": METRICS_SECONDS, "commands": sorted(COMMANDS)})
        tasks = [asyncio.create_task(loop()) for loop in (metrics_loop, media_loop, auth_loop)]
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = msg.json()
                except ValueError:
                    await send({"type": "error", "code": "bad_message", "message": "Ожидается JSON."})
                    continue
                kind = data.get("type") if isinstance(data, dict) else None
                if kind == "ping":
                    await send({"type": "pong"})
                elif kind == "subscribe":
                    wants["metrics"] = bool(data.get("metrics", True))
                    interval = data.get("interval")
                    if isinstance(interval, (int, float)) and not isinstance(interval, bool):
                        wants["interval"] = min(MAX_INTERVAL, max(MIN_INTERVAL, float(interval)))
                elif kind == "command":
                    action = data.get("action")
                    if action not in COMMANDS:      # only playback; nothing else can be run from the panel
                        await send({"type": "error", "code": "bad_command", "message": "Команда не поддерживается."})
                    elif await asyncio.to_thread(workstation_locked):
                        await send({"type": "error", "code": "locked", "message": "ПК заблокирован."})
                    else:
                        try:
                            await run_command(action, data.get("value"))
                        except ValueError as exc:
                            await send({"type": "error", "code": "player", "message": str(exc)})
                else:
                    await send({"type": "error", "code": "bad_message", "message": "Неизвестный тип сообщения."})
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            reader.close()
            logger.info("Панель отключена (%s)", request.remote)
        return ws

    app.router.add_get("/api/v1/display", display)
