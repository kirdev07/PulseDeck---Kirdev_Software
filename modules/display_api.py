"""WebSocket for PulseDeck Panel (the Android information display): /api/v1/display.

Runs only on the TLS server (API v1), behind the same guard as every other v1 route:
LAN peers only and a valid per-device token (pairing by code, revocable on the PC).
Protocol: docs/PANEL_PROTOCOL.md.

Server -> panel: hello, metrics (every METRICS_SECONDS), media (on change), sessions (players to
choose from), activity (the app in front on the PC), error.
Panel -> server: {"type": "command", "action": "toggle" | "next" | "prev" | "seek" | "volume" | "source"},
{"type": "ping"}, {"type": "subscribe", "metrics": false} (the panel runs in the background: send media only).
Panels that do not know a message type ignore it, so new messages need no new protocol version.
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
SESSIONS_SECONDS = 3.0         # the list of players is re-read this often
ACTIVITY_SECONDS = 3.0         # «Сейчас на ПК»
COMMANDS = {"toggle", "next", "prev", "seek", "volume", "source"}
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
                "cores": getattr(snap, "cpu_cores", None),
                "per_core": [_round(v) for v in getattr(snap, "cpu_per_core", None) or []]},
        # GPU load = busiest engine over all adapters (like Task Manager); name/memory = main card.
        "gpu": {"load": _round(snap.gpu), "temp": None, "name": snap.gpu_name or None,
                "memory_total": getattr(snap, "gpu_memory_total", None) or None,
                "memory_used": getattr(snap, "gpu_memory_used", None)},
        "ram": {"percent": _round(snap.ram), "used": snap.ram_used, "total": snap.ram_total},
        "net": {"down": _round(getattr(snap, "net_down", None), 0), "up": _round(getattr(snap, "net_up", None), 0)},
        "uptime": _round(getattr(snap, "uptime", None), 0),
        # Laptops only; a desktop PC has no battery: null.
        "battery": None if getattr(snap, "battery", None) is None else
        {"percent": _round(snap.battery, 0), "plugged": bool(getattr(snap, "plugged", False))},
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


def add_display_route(app, current_player, control_player, workstation_locked, list_players=None):
    """current_player(source) / control_player(cmd, value, source) / list_players(): modules.player_access."""
    async def run_command(action, value, source=""):
        """Playback and PC volume only; values are validated, nothing else can run."""
        if action == "seek":
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ValueError("Позиция — число секунд.")
            await control_player("seek", float(value), source)
        elif action == "volume":
            from modules import volume
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
                raise ValueError("Громкость — число от 0 до 100.")
            if not volume.AVAILABLE:
                raise ValueError("Громкость ПК недоступна: не установлен pycaw.")
            await asyncio.to_thread(volume.set_level, value)
        else:
            await control_player(action, None, source)

    async def display(request):
        token = request.headers.get("Authorization", "")[7:]     # already checked by the guard
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096)
        await ws.prepare(request)
        device = await asyncio.to_thread(mobile_access.authenticate, token)
        logger.info("Панель подключена: %s (%s)", (device or {}).get("name", "?"), request.remote)
        reader = MetricsReader()
        send_lock = asyncio.Lock()
        closing = asyncio.Event()
        wants = {"metrics": True, "interval": METRICS_SECONDS, "source": "", "wake": asyncio.Event()}

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
                    message = media_message(await current_player(wants["source"]))
                    message["system_volume"] = await asyncio.to_thread(system_volume_state)
                    message["source_id"] = wants["source"]
                    now = time.monotonic()
                    playing = (message["session"] or {}).get("status") == "playing"
                    if not _same_track(message, last) or (playing and now - sent_at >= MEDIA_RESYNC_SECONDS) \
                            or message["source_id"] != (last or {}).get("source_id"):
                        await send(message)
                        last, sent_at = message, now
                except (ConnectionError, RuntimeError):
                    return
                except Exception:  # noqa: BLE001 - media sessions disappear mid-read
                    logger.debug("Состояние плеера недоступно", exc_info=True)
                wants["wake"].clear()
                try:        # a command wakes the loop at once, so the panel sees the result quickly
                    await asyncio.wait_for(wants["wake"].wait(), MEDIA_SECONDS)
                except asyncio.TimeoutError:
                    pass

        async def sessions_loop():
            # Players the panel can choose from («Автоматически» is the panel's own first item).
            if list_players is None:
                return
            last = None
            while not ws.closed:
                try:
                    items = [{"id": s.get("id", ""), "source": source_name(s.get("source") or s.get("id") or ""),
                              "title": s.get("title", ""), "status": s.get("status", "")} for s in await list_players()]
                    if items != last:
                        await send({"type": "sessions", "items": items})
                        last = items
                except (ConnectionError, RuntimeError):
                    return
                except Exception:  # noqa: BLE001 - media sessions disappear mid-read
                    logger.debug("Список плееров недоступен", exc_info=True)
                await asyncio.sleep(SESSIONS_SECONDS)

        async def activity_loop():
            # «Сейчас на ПК»: the app in front and its window title (the link is TLS with a pinned key).
            last = object()
            while not ws.closed:
                if not wants["metrics"]:            # in the background nobody looks at it
                    await asyncio.sleep(ACTIVITY_SECONDS)
                    continue
                try:
                    from modules.winutil import foreground_activity
                    found = await asyncio.to_thread(foreground_activity)
                except Exception:  # noqa: BLE001 - a window closing mid-read, no pywin32
                    found = None
                message = {"type": "activity", "app": (found or {}).get("app") or None,
                           "title": (found or {}).get("title", ""), "fullscreen": bool((found or {}).get("fullscreen"))}
                if message != last:
                    try:
                        await send(message)
                    except (ConnectionError, RuntimeError):
                        return
                    last = message
                await asyncio.sleep(ACTIVITY_SECONDS)

        async def auth_loop():
            # Revocation on the PC must cut an open connection, not only new ones.
            while not ws.closed:
                await asyncio.sleep(AUTH_RECHECK_SECONDS)
                if not await asyncio.to_thread(mobile_access.authenticate, token):
                    logger.info("Доступ панели отозван, соединение закрыто.")
                    # Under the send lock: a close racing a send can abort the socket (1006),
                    # and the panel would never learn that it was revoked.
                    closing.set()
                    async with send_lock:
                        await asyncio.wait_for(ws.close(code=CLOSE_REVOKED, message=b"revoked"), 10)
                    return

        await send({"type": "hello", "protocol": PROTOCOL, "app": "PulseDeck", "name": socket.gethostname(),
                    "metrics_interval": METRICS_SECONDS, "commands": sorted(COMMANDS)})
        loops = (metrics_loop, media_loop, sessions_loop, activity_loop, auth_loop)
        AUTH = loops.index(auth_loop)
        tasks = [asyncio.create_task(loop()) for loop in loops]
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
                    elif action == "source":        # which player to show: view-only phones may choose too
                        value = data.get("value")
                        wants["source"] = value if isinstance(value, str) and len(value) <= 300 else ""
                        wants["wake"].set()
                    elif not mobile_access.can_control(await asyncio.to_thread(mobile_access.authenticate, token)):
                        await send({"type": "error", "code": "view_only", "message": "Телефон подключён только для просмотра."})
                    elif await asyncio.to_thread(workstation_locked):
                        await send({"type": "error", "code": "locked", "message": "ПК заблокирован."})
                    else:
                        try:
                            await run_command(action, data.get("value"), wants["source"])
                            wants["wake"].set()
                        except ValueError as exc:
                            await send({"type": "error", "code": "player", "message": str(exc)})
                else:
                    await send({"type": "error", "code": "bad_message", "message": "Неизвестный тип сообщения."})
        finally:
            # A revocation close in progress is let finish (cancelled half-way, the phone would
            # see a broken link, 1006, instead of «revoked», 4001); everything else stops now.
            for task in tasks:
                if not (task is tasks[AUTH] and closing.is_set()):
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            reader.close()
            logger.info("Панель отключена (%s)", request.remote)
        return ws

    app.router.add_get("/api/v1/display", display)
