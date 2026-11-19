"""Web panel server: the Panel screen (clock, CPU/RAM/GPU, network, disks, now playing) in
any phone browser on the home network, iPhone included. Files: web_panel/ next to the code.

Pairing works like the apps: the owner presses «Показать код» on «Телефон» (choice
«Браузер»), the browser sends the 6 digits to POST /pair and gets its own token, which it
keeps. The browser then appears among the paired devices: view only by default, «Полный»
allows play/pause/next/previous, «Отозвать» disconnects it.

Security (it is plain HTTP, see settings.py):
  * answers LAN addresses only, like the phone server;
  * browser tokens are a separate kind (mobile_access.KIND_WEB): they open the web panel
    and nothing else — never the TLS API of the apps; app tokens do not open the panel;
  * the page holds no data without a token; nothing but playback can be run from it;
  * a revoked browser is disconnected within AUTH_RECHECK_SECONDS.
"""
import asyncio
import logging
import socket
import time
from pathlib import Path

from aiohttp import WSMsgType, web

import config
from modules import mobile_access
from pulse_pc.core import state as st
from pulse_pc.services.web_panel import settings as web_settings

logger = logging.getLogger("pulse_pc.services.web_panel")
WEB_ROOT = Path(config.RESOURCE_DIR) / "web_panel"
FILES = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/app.css": "app.css",
         "/logo.svg": "logo.svg", "/icon.png": "icon.png", "/manifest.webmanifest": "manifest.webmanifest"}
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
         ".png": "image/png", ".webmanifest": "application/manifest+json"}
METRICS_SECONDS = 2.0
MEDIA_SECONDS = 1.0
MEDIA_RESYNC_SECONDS = 5.0
AUTH_RECHECK_SECONDS = 5.0
MAX_CLIENTS = 8
CLOSE_REVOKED = 4001
COMMANDS = {"toggle", "next", "prev"}
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                                "connect-src 'self' ws: wss:; frame-ancestors 'none'"),
}


def browser(token):
    """The paired browser for this token, or None (app tokens do not count)."""
    return mobile_access.authenticate(token, mobile_access.KIND_WEB)


def make_app(on_clients=lambda n: None, pairing=None):
    from modules.display_api import MetricsReader, _same_track, media_message, system_volume_state
    from modules.local_api import is_private_ip
    from modules.monitor import workstation_locked
    from modules import player_access

    pairing = pairing or mobile_access.PAIRING
    clients = set()

    @web.middleware
    async def guard(request, handler):
        if not is_private_ip(request.remote):
            return web.Response(status=403, text="PulseDeck: только для домашней сети.")
        response = await handler(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    async def static(request):
        name = FILES.get(request.path)
        path = WEB_ROOT / name if name else None
        if not path or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Content-Type": TYPES.get(path.suffix, "application/octet-stream")})

    async def pair(request):
        """6-digit code from «Телефон» → a token of this browser, kept by the page."""
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        name = " ".join(str(body.get("name", "")).split())[:40] or "Браузер"
        if not (await asyncio.to_thread(mobile_access.load))["allow_pairing"]:
            return web.json_response({"ok": False, "error": "Новые подключения выключены на ПК: «Телефон» → "
                                                            "«Разрешить новые подключения»."}, status=403)
        if not pairing.active():
            return web.json_response({"ok": False, "error": "На ПК откройте «Телефон» → «Показать код» "
                                                            "(выберите «Браузер»)."}, status=403)
        if not pairing.verify(body.get("code")):
            logger.warning("Веб-панель: неверный код подключения от %s", request.remote)
            text = "Неверный код." if pairing.active() else "Код больше не действует. Покажите новый на ПК."
            return web.json_response({"ok": False, "error": text}, status=403)
        try:
            token = await asyncio.to_thread(mobile_access.add_device, name, mobile_access.KIND_WEB,
                                            mobile_access.ACCESS_VIEW)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        logger.info("Браузер «%s» подключён к веб-панели по коду (%s)", name, request.remote)
        return web.json_response({"ok": True, "token": token, "name": socket.gethostname()})

    async def cover(request):
        if not await asyncio.to_thread(browser, request.query.get("t", "")):
            raise web.HTTPForbidden()
        found = await asyncio.to_thread(player_access.cover, request.query.get("key", ""))
        if not found:
            raise web.HTTPNotFound()
        return web.Response(body=found[0], content_type=found[1])

    async def socket_handler(request):
        token = request.query.get("t", "")
        device = await asyncio.to_thread(browser, token)
        if not device:
            return web.json_response({"ok": False, "error": "not_paired"}, status=403)
        if len(clients) >= MAX_CLIENTS:
            return web.json_response({"ok": False, "error": "busy"}, status=503)
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=2048)
        await ws.prepare(request)
        clients.add(ws)
        on_clients(len(clients))
        logger.info("Веб-панель открыта: %s (%s)", device.get("name", "?"), request.remote)
        reader = MetricsReader()
        lock = asyncio.Lock()
        access = {"control": mobile_access.can_control(device)}

        async def send(message):
            async with lock:
                if not ws.closed:
                    await ws.send_json(message)

        async def metrics_loop():
            while not ws.closed:
                try:
                    await send(await reader.read())
                except (ConnectionError, RuntimeError):
                    return
                except Exception:  # noqa: BLE001 - one bad sample must not end the page
                    logger.exception("Веб-панель: не удалось собрать показатели")
                await asyncio.sleep(METRICS_SECONDS)

        async def media_loop():
            last, sent_at = None, 0.0
            while not ws.closed:
                try:
                    message = media_message(await player_access.current_player())
                    message["system_volume"] = await asyncio.to_thread(system_volume_state)
                    now = time.monotonic()
                    playing = (message["session"] or {}).get("status") == "playing"
                    if not _same_track(message, last) or (playing and now - sent_at >= MEDIA_RESYNC_SECONDS):
                        await send(message)
                        last, sent_at = message, now
                except (ConnectionError, RuntimeError):
                    return
                except Exception:  # noqa: BLE001 - media sessions disappear mid-read
                    logger.debug("Веб-панель: плеер недоступен", exc_info=True)
                await asyncio.sleep(MEDIA_SECONDS)

        async def auth_loop():
            # «Отозвать» on the PC must cut an open page; «Доступ» changes apply live.
            while not ws.closed:
                await asyncio.sleep(AUTH_RECHECK_SECONDS)
                current = await asyncio.to_thread(browser, token)
                if not current:
                    logger.info("Доступ браузера к веб-панели отозван.")
                    await ws.close(code=CLOSE_REVOKED, message=b"revoked")
                    return
                control = mobile_access.can_control(current)
                if control != access["control"]:
                    access["control"] = control
                    await send({"type": "access", "control": control})

        await send({"type": "hello", "app": "PulseDeck", "name": socket.gethostname(),
                    "device": device.get("name", ""), "control": access["control"],
                    "metrics_interval": METRICS_SECONDS})
        tasks = [asyncio.create_task(loop()) for loop in (metrics_loop, media_loop, auth_loop)]
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = msg.json()
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                if data.get("type") == "ping":
                    await send({"type": "pong"})
                elif data.get("type") == "command":
                    action = data.get("action")
                    if action not in COMMANDS:
                        await send({"type": "error", "code": "bad_command", "message": "Команда не поддерживается."})
                    elif not access["control"]:
                        await send({"type": "error", "code": "view_only",
                                    "message": "Только просмотр. Управление музыкой включается на ПК: "
                                               "«Телефон» → «Доступ» → «Полный»."})
                    elif await asyncio.to_thread(workstation_locked):
                        await send({"type": "error", "code": "locked", "message": "ПК заблокирован."})
                    else:
                        try:
                            await player_access.control_player(action)
                        except ValueError as exc:
                            await send({"type": "error", "code": "player", "message": str(exc)})
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            reader.close()
            clients.discard(ws)
            on_clients(len(clients))
            logger.info("Веб-панель закрыта (%s)", request.remote)
        return ws

    async def close_clients(_app):
        for ws in list(clients):
            await ws.close(code=1001, message=b"server stopped")

    app = web.Application(middlewares=[guard], client_max_size=4096)
    app.on_shutdown.append(close_clients)
    app.router.add_get("/ws", socket_handler)
    app.router.add_get("/cover", cover)
    app.router.add_post("/pair", pair)
    for path in FILES:
        app.router.add_get(path, static)
    return app


class WebPanelService:
    def __init__(self, runtime, store, config_dir):
        self.runtime = runtime
        self.store = store
        self.config_dir = Path(config_dir)
        self.runner = None

    @property
    def running(self):
        return self.runner is not None

    def start(self):
        return self.runtime.submit(self._start())

    def stop(self):
        return self.runtime.submit(self._stop())

    def restart(self):
        return self.runtime.submit(self._restart())

    def _post(self, **changes):
        self.store.post("web_panel", **changes)

    async def _start(self):
        if self.running:
            return
        data = await asyncio.to_thread(web_settings.load, self.config_dir)
        if not data["enabled"]:
            self._post(status=st.STOPPED, port=0, addresses=(), clients=0, error="")
            return
        if not (WEB_ROOT / "index.html").is_file():
            self._post(status=st.ERROR, port=0, error=f"Нет файлов веб-панели: {WEB_ROOT}")
            return
        self._post(status=st.STARTING, error="")
        runner = web.AppRunner(make_app(lambda n: self._post(clients=n)), access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, "0.0.0.0", data["port"]).start()
        except OSError:
            await runner.cleanup()
            self._post(status=st.ERROR, port=0, addresses=(),
                       error=f"Порт {data['port']} занят другой программой. Выберите другой в настройках.")
            logger.error("Веб-панель: порт %s занят.", data["port"])
            return
        self.runner = runner
        from modules.local_api import lan_addresses
        addresses = tuple(await asyncio.to_thread(lan_addresses))
        self._post(status=st.RUNNING, port=data["port"], addresses=addresses, clients=0, error="")
        logger.info("Веб-панель: http://%s:%s", addresses[0] if addresses else "localhost", data["port"])

    async def _stop(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            logger.info("Веб-панель остановлена.")
        self._post(status=st.STOPPED, port=0, addresses=(), clients=0)

    async def _restart(self):
        await self._stop()
        await self._start()
