"""Web panel server: the Panel screen (clock, CPU/RAM/GPU, network, disks, now playing) in
any phone browser on the home network, iPhone included. Files: web_panel/ next to the code.

Two ports, one app:
  * HTTP  (8780): the page for a new phone — pairing by code and the home certificate of
    this PC (/ca.mobileconfig for iPhone, /ca.crt for Android); view only;
  * HTTPS (8781): the same panel once the phone trusts that certificate (web_panel/tls.py).

Pairing works like the apps: «Телефон» → «Показать код» → «Браузер»; the browser sends the
6 digits to POST /pair and keeps its own token. Browsers are listed among the paired
devices: a browser paired over HTTPS gets «Полный» (music control), one paired over
plain HTTP «Просмотр»;
(play/pause, next/previous, seek, PC volume, which app is controlled). «Отозвать»
disconnects it within AUTH_RECHECK_SECONDS.

Security:
  * LAN addresses only, like the phone server;
  * browser tokens are a separate kind (mobile_access.KIND_WEB): they open the web panel and
    nothing else — never the TLS API of the apps; app tokens do not open the panel;
  * control needs an HTTPS connection AND a browser paired over HTTPS (its token never
    crossed the network unencrypted) AND «Полный»; nothing but music can be run from it.
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
SESSIONS_SECONDS = 3.0
AUTH_RECHECK_SECONDS = 5.0
MAX_CLIENTS = 8
CLOSE_REVOKED = 4001
COMMANDS = {"toggle", "next", "prev", "seek", "volume", "source"}
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # https: — the HTTP setup page checks whether the phone already trusts the HTTPS panel.
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                                "connect-src 'self' ws: wss: https:; frame-ancestors 'none'"),
}


def browser(token):
    """The paired browser for this token, or None (app tokens do not count)."""
    return mobile_access.authenticate(token, mobile_access.KIND_WEB)


def may_control(device, secure_connection):
    return bool(secure_connection and (device or {}).get("secure") and mobile_access.can_control(device))


def make_app(on_clients=lambda n: None, pairing=None, config_dir=None, https_port=0):
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

    async def info(request):
        return web.json_response({"ok": True, "secure": request.secure, "https_port": https_port,
                                  "name": socket.gethostname()})

    async def authority(request):
        """The home certificate for the phone: profile for iPhone/iPad, DER for Android."""
        if not config_dir:
            raise web.HTTPNotFound()
        from pulse_pc.services.web_panel import tls
        if request.path.endswith(".mobileconfig"):
            body = await asyncio.to_thread(tls.mobileconfig, config_dir)
            return web.Response(body=body, content_type="application/x-apple-aspen-config",
                                headers={"Content-Disposition": 'attachment; filename="PulseDeck.mobileconfig"'})
        body = await asyncio.to_thread(tls.authority_der, config_dir)
        return web.Response(body=body, content_type="application/x-x509-ca-cert",
                            headers={"Content-Disposition": 'attachment; filename="PulseDeck.crt"'})

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
        # Paired over HTTPS with the code the owner showed on the PC: trusted like the apps
        # («Полный»). Over plain HTTP the token crossed the network unencrypted: view only.
        access = mobile_access.ACCESS_FULL if request.secure else mobile_access.ACCESS_VIEW
        try:
            token = await asyncio.to_thread(mobile_access.add_device, name, mobile_access.KIND_WEB,
                                            access, request.secure)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        logger.info("Браузер «%s» подключён к веб-панели по коду (%s, %s)", name, request.remote,
                    "HTTPS" if request.secure else "HTTP, только просмотр")
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
        secure = request.secure
        view = {"control": may_control(device, secure), "source": "", "wake": asyncio.Event()}

        def access_message():
            if view["control"]:
                reason = ""
            elif not secure or not device.get("secure"):
                reason = "insecure"     # HTTP, or paired over HTTP: set up HTTPS and pair again
            else:
                reason = "view"         # «Доступ» → «Полный» on the PC
            return {"type": "access", "control": view["control"], "secure": secure, "reason": reason}

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
                    message = media_message(await player_access.current_player(view["source"]))
                    message["system_volume"] = await asyncio.to_thread(system_volume_state)
                    message["source_id"] = view["source"]
                    now = time.monotonic()
                    playing = (message["session"] or {}).get("status") == "playing"
                    if not _same_track(message, last) or (playing and now - sent_at >= MEDIA_RESYNC_SECONDS) \
                            or message.get("source_id") != (last or {}).get("source_id"):
                        await send(message)
                        last, sent_at = message, now
                except (ConnectionError, RuntimeError):
                    return
                except Exception:  # noqa: BLE001 - media sessions disappear mid-read
                    logger.debug("Веб-панель: плеер недоступен", exc_info=True)
                view["wake"].clear()
                try:        # a command wakes the loop at once, so the page sees the result quickly
                    await asyncio.wait_for(view["wake"].wait(), MEDIA_SECONDS)
                except asyncio.TimeoutError:
                    pass

        async def sessions_loop():
            last = None
            while not ws.closed:
                try:
                    items = [{"id": s.get("id", ""), "source": s.get("source", ""), "title": s.get("title", ""),
                              "status": s.get("status", "")} for s in await player_access.sessions()]
                    if items != last:
                        await send({"type": "sessions", "items": items})
                        last = items
                except (ConnectionError, RuntimeError):
                    return
                except Exception:  # noqa: BLE001
                    logger.debug("Веб-панель: список плееров недоступен", exc_info=True)
                await asyncio.sleep(SESSIONS_SECONDS)

        async def auth_loop():
            # «Отозвать» on the PC must cut an open page; «Доступ» changes apply live.
            while not ws.closed:
                await asyncio.sleep(AUTH_RECHECK_SECONDS)
                current = await asyncio.to_thread(browser, token)
                if not current:
                    logger.info("Доступ браузера к веб-панели отозван.")
                    async with lock:        # not in the middle of a send (see display_api)
                        await ws.close(code=CLOSE_REVOKED, message=b"revoked")
                    return
                control = may_control(current, secure)
                device.update(current)
                if control != view["control"]:
                    view["control"] = control
                    await send(access_message())

        async def run(action, value):
            if action == "source":
                view["source"] = value if isinstance(value, str) and len(value) <= 300 else ""
                return
            if action == "seek":
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    raise ValueError("Позиция — число секунд.")
                await player_access.control_player("seek", float(value), view["source"])
            elif action == "volume":
                from modules import volume
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
                    raise ValueError("Громкость — число от 0 до 100.")
                if not volume.AVAILABLE:
                    raise ValueError("Громкость ПК недоступна.")
                await asyncio.to_thread(volume.set_level, value)
            else:
                await player_access.control_player(action, None, view["source"])

        await send({"type": "hello", "app": "PulseDeck", "name": socket.gethostname(),
                    "device": device.get("name", ""), "control": view["control"], "secure": secure,
                    "metrics_interval": METRICS_SECONDS})
        await send(access_message())
        tasks = [asyncio.create_task(loop()) for loop in (metrics_loop, media_loop, sessions_loop, auth_loop)]
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
                    elif action == "source":        # what to watch: allowed for view-only browsers too
                        await run(action, data.get("value"))
                        view["wake"].set()
                    elif not view["control"]:
                        await send({"type": "error", "code": "view_only",
                                    "message": "Только просмотр." if secure and device.get("secure") else
                                    "Управление — только в защищённом режиме (HTTPS)."})
                    elif await asyncio.to_thread(workstation_locked):
                        await send({"type": "error", "code": "locked", "message": "ПК заблокирован."})
                    else:
                        try:
                            await run(action, data.get("value"))
                            view["wake"].set()
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
    app.router.add_get("/info", info)
    app.router.add_get("/ca.crt", authority)
    app.router.add_get("/ca.mobileconfig", authority)
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
            self._post(status=st.STOPPED, port=0, https_port=0, addresses=(), clients=0, error="")
            return
        if not (WEB_ROOT / "index.html").is_file():
            self._post(status=st.ERROR, port=0, https_port=0, error=f"Нет файлов веб-панели: {WEB_ROOT}")
            return
        self._post(status=st.STARTING, error="")
        from modules.local_api import lan_addresses
        addresses = tuple(await asyncio.to_thread(lan_addresses))
        https = web_settings.https_port(data["port"])
        app = make_app(lambda n: self._post(clients=n), config_dir=self.config_dir, https_port=https)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, "0.0.0.0", data["port"]).start()
        except OSError:
            await runner.cleanup()
            self._post(status=st.ERROR, port=0, https_port=0, addresses=(),
                       error=f"Порт {data['port']} занят другой программой. Выберите другой в настройках.")
            logger.error("Веб-панель: порт %s занят.", data["port"])
            return
        error = ""
        try:
            from pulse_pc.services.web_panel import tls
            context = await asyncio.to_thread(tls.server_context, self.config_dir, addresses)
            await web.TCPSite(runner, "0.0.0.0", https, ssl_context=context).start()
        except OSError:
            https = 0
            error = f"HTTPS-порт {web_settings.https_port(data['port'])} занят: работает только просмотр по HTTP."
            logger.error("Веб-панель: %s", error)
        except Exception as exc:  # noqa: BLE001 - certificate problems leave HTTP working
            https = 0
            error = "Не удалось создать сертификат HTTPS: работает только просмотр по HTTP."
            logger.exception("Веб-панель: сертификат HTTPS: %s", exc)
        self.runner = runner
        self._post(status=st.RUNNING, port=data["port"], https_port=https, addresses=addresses, clients=0, error=error)
        logger.info("Веб-панель: http://%s:%s, HTTPS %s", addresses[0] if addresses else "localhost", data["port"],
                    https or "нет")

    async def _stop(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            logger.info("Веб-панель остановлена.")
        self._post(status=st.STOPPED, port=0, https_port=0, addresses=(), clients=0)

    async def _restart(self):
        await self._stop()
        await self._start()
