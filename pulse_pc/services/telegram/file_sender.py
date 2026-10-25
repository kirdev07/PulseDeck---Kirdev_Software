"""Send files from this PC to the administrator's Telegram chat (moved from the classic
panel). Uses desktop_services.send_files_with_token on the shared runtime loop: up to two
files in parallel, 50 MB each, live progress, cancellation. Independent of the bot's
polling, so it works while the bot is stopped as long as the token is valid."""
from PySide6.QtCore import QObject, Signal

PHASES = {
    "preparing": "Проверка размеров и доступности файлов…",
    "uploading": "Отправка…",
    "waiting": "Telegram просит подождать. Отправка продолжится автоматически…",
    "confirming": "Данные переданы. Ожидание подтверждения Telegram…",
    "sent": "Файл доставлен.",
    "completed": "Все файлы отправлены.",
    "cancelled": "Отправка отменена. Уже отправленные файлы остаются в Telegram.",
    "error": "Отправка остановлена из-за ошибки.",
}


class FileSender(QObject):
    progress = Signal(dict)
    finished = Signal(bool, str)      # (ok, message)

    def __init__(self, runtime, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self.future = None

    @property
    def busy(self):
        return self.future is not None and not self.future.done()

    def send(self, token, admin_id, paths):
        from desktop_services import send_files_with_token
        if self.busy:
            raise ValueError("Дождитесь окончания текущей отправки.")
        if not token:
            raise ValueError("Сначала укажите токен бота в Настройках.")
        if not str(admin_id or "").isdigit():
            raise ValueError("Сначала укажите ID администратора в Настройках.")
        self.future = self.runtime.submit(
            send_files_with_token(token, int(admin_id), list(paths), self.progress.emit))
        self.future.add_done_callback(self._done)

    def cancel(self):
        if self.busy:
            self.future.cancel()

    def _done(self, future):
        import concurrent.futures
        try:
            self.finished.emit(True, future.result())
        except (concurrent.futures.CancelledError, KeyboardInterrupt):
            self.finished.emit(False, PHASES["cancelled"])
        except Exception as exc:  # noqa: BLE001 - shown to the user
            from desktop_services import telegram_error
            self.finished.emit(False, telegram_error(exc))
