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
                  "last_seen": d.get("last_seen", "")} for d in data["devices"])


class LocalApiService:
    def __init__(self, runtime, store):
        self.runtime = runtime
        self.store = store
        self.server = None
        self._watch = None

    @property
    def running(self):
        return self.server is not None and self.server.runner is not None

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

    def refresh(self):
        self._publish()

    def _publish(self, status=None, error=None):
        data = mobile_access.load()
        running = self.running
        if status is None:
            status = st.RUNNING if running else st.STOPPED
        port = data["port"]
        if running and self.server.runner.addresses:
            port = self.server.runner.addresses[0][1]     # the port actually bound
        changes = dict(status=status, port=port, devices=public_devices(data),
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
        self.server = LocalApiServer(lambda text: logger.info("%s", text), lambda: self.runtime.features)
        await self.server.start()
        if self.server.runner is None:
            self.server = None
            await asyncio.to_thread(self._publish, st.ERROR,
                                    f"Порт {data['port']} занят другой программой или запрещён системой.")
            return
        self._watch = asyncio.create_task(self._refresh_loop())
        await asyncio.to_thread(self._publish)

    async def _stop(self):
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
