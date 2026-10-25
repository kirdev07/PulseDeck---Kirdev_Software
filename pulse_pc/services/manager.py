"""Starts and stops the background services in a fixed order and reports overall state."""
import logging
import msvcrt
from pathlib import Path

from pulse_pc.core import settings as cfg
from pulse_pc.services.local_api.service import LocalApiService
from pulse_pc.services.runtime import Runtime
from pulse_pc.services.telegram.service import TelegramService

logger = logging.getLogger(__name__)
LOCK_FILES = ("gui.lock", "bot.lock")   # the same files the classic panel locks


class InstanceLock:
    """Only one Pulse-PC panel (classic or new) may run: both would poll the same bot
    and bind the same ports."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.handles = []

    def acquire(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            for name in LOCK_FILES:
                stream = open(self.directory / name, "a+b")
                self.handles.append(stream)
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.release()
            return False
        return True

    def release(self):
        for stream in self.handles:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            stream.close()
        self.handles = []


class ServiceManager:
    def __init__(self, store, config_dir):
        self.store = store
        self.config_dir = Path(config_dir)
        self.runtime = Runtime()
        self.telegram = TelegramService(self.runtime, store)
        self.local_api = LocalApiService(self.runtime, store, self.config_dir)

    def telegram_configured(self):
        from pulse_pc.core.secrets import load_token
        return bool(load_token(self.config_dir)) and cfg.read_env(self.config_dir / ".env").get("ADMIN_ID", "").isdigit()

    def start(self, telegram=True):
        """Phone server always (if enabled in settings); Telegram when configured and wanted."""
        from pulse_pc.core import state as st
        self.runtime.start()
        if not self.runtime.loop:
            reason = self.runtime.error or "Фоновая служба Pulse-PC не запустилась."
            self.store.post("telegram", status=st.ERROR, error=reason)
            self.store.post("phone", status=st.ERROR, error=reason)
            return
        self.local_api.start()
        if telegram and self.telegram_configured():
            self.telegram.start()
        else:
            from pulse_pc.core import state as st
            self.store.post("telegram", status=st.STOPPED,
                            error="" if self.telegram_configured() else "Бот не настроен: укажите токен и ID в Настройках.")

    def shutdown(self, timeout=8.0):
        """Telegram first (it may be sending), then the phone server, then the loop."""
        for service in (self.telegram, self.local_api):
            try:
                service.stop().result(timeout / 2)
            except Exception as exc:  # noqa: BLE001 - shutdown continues regardless
                logger.warning("Служба остановлена с ошибкой: %s", exc)
        self.runtime.stop(timeout)
