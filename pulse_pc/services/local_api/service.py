"""The Pulse Mobile server (modules/local_api.py, protocol unchanged) as an independent
service on the shared runtime loop. Telegram can be stopped without affecting it."""
import asyncio
import logging

from modules import mobile_access
from pulse_pc.core import state as st

logger = logging.getLogger("pulse_pc.services.local_api")
REFRESH_SECONDS = 5


def public_devices(data):
    """Device records without token hashes, for the UI."""
    return tuple({"id": d.get("id", ""), "name": d.get("name", ""), "added": d.get("added", ""),
                  "last_seen": d.get("last_seen", ""),
                  "access": d.get("access", mobile_access.ACCESS_FULL)} for d in data["devices"])


class LocalApiService:
    def __init__(self, runtime, store, config_dir=None):
        import config
        self.config_dir = config_dir or config.CONFIG_DIR
        self.runtime = runtime
        self.store = store
        self.server = None
        self._watch = None

    @property
    def running(self):
        return self.server is not None and self.server.running

    def start(self):
        return self.runtime.submit(self._start())

    def stop(self):
        return self.runtime.submit(self._stop())

    def restart(self):
        return self.runtime.submit(self._restart())

    def revoke(self, device_id):
        """Remove a phone's access; its token stops working on the next request."""
        mobile_access.remove_device(device_id)
        logger.info("Доступ телефона отозван.")
        self._publish()

    def set_access(self, device_id, access):
        """Full control or view only; applies to the phone's next request (the panel within 5 s)."""
        mobile_access.set_access(device_id, access)
        self._publish()

    def refresh(self):
        self._publish()

    def _publish(self, status=None, error=None):
        data = mobile_access.load()
        running = self.running
        if status is None:
            status = st.RUNNING if running else st.STOPPED
        port = data["port"]
        tls_port = 0
        if running:     # the ports actually bound
            if self.server.runner and self.server.runner.addresses:
                port = self.server.runner.addresses[0][1]
            else:
                port = 0
            if self.server.runner_v1 and self.server.runner_v1.addresses:
                tls_port = self.server.runner_v1.addresses[0][1]
        changes = dict(status=status, port=port, tls_port=tls_port, devices=public_devices(data),
                       addresses=tuple(a.rsplit(":", 1)[0] for a in mobile_access.STATE["addresses"]) if running else ())
        if error is not None or status != st.ERROR:
            changes["error"] = error or ""
        self.store.post("phone", **changes)

    async def _start(self):
        if self.running:
            return
        from modules.local_api import LocalApiServer
        data = await asyncio.to_thread(mobile_access.load)
        if not data["enabled"]:
            await asyncio.to_thread(self._publish, st.STOPPED, "Сервер выключен в настройках.")
            logger.info("Сервер для телефона выключен в настройках.")
            return
        self.store.post("phone", status=st.STARTING)
        from pulse_pc.services.local_api import tls
        self.server = LocalApiServer(lambda text: logger.info("%s", text), lambda: self.runtime.features,
                                     tls_context=lambda: tls.server_context(self.config_dir))
        await self.server.start()
        if not self.server.running:
            self.server = None
            await asyncio.to_thread(self._publish, st.ERROR,
                                    f"Порт {data['port']} занят другой программой или запрещён системой.")
            return
        self._watch = asyncio.create_task(self._refresh_loop())
        if self.server.runner_v1 and self.server.runner_v1.addresses:
            from pulse_pc.services.local_api.usb import UsbBridge
            self._usb = UsbBridge(self.server.runner_v1.addresses[0][1])
            self._usb.start()
        await asyncio.to_thread(self._publish)

    async def _stop(self):
        if getattr(self, "_usb", None):
            await self._usb.stop()
            self._usb = None
        if self._watch:
            self._watch.cancel()
            await asyncio.gather(self._watch, return_exceptions=True)
            self._watch = None
        if self.server:
            await self.server.close()
            self.server = None
            logger.info("Сервер для телефона остановлен.")
        await asyncio.to_thread(self._publish)

    async def _restart(self):
        await self._stop()
        await self._start()

    async def _refresh_loop(self):
        # New pairings and «last seen» times change inside the server; mirror them.
        while True:
            await asyncio.sleep(REFRESH_SECONDS)
            try:
                await asyncio.to_thread(self._publish)
            except OSError as exc:
                logger.warning("Не удалось прочитать список телефонов: %s", exc)
