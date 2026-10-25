"""Background runtime: one asyncio loop in a daemon thread shared by the services.

Telegram and the local API are independent services on this loop; neither owns the
other. Shared PC features (power timer, scenarios, load alerts) live here as well, so
the phone keeps working while the bot is stopped or misconfigured.
"""
import asyncio
import concurrent.futures
import logging
import threading

from modules.background_io import FileIOExecutor

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Stands in for `aiogram.Bot` inside BotFeatures: forwards messages to the running
    bot, silently drops them while Telegram is off (they still reach the log and phone)."""

    def __init__(self):
        self.bot = None

    async def send_message(self, chat_id, text, **kwargs):
        bot = self.bot
        if bot is None or not chat_id:
            logger.info("Уведомление (Telegram выключен): %s", text)
            return None
        return await bot.send_message(chat_id, text, **kwargs)


class Runtime:
    def __init__(self):
        self.loop = None
        self.thread = None
        self.features = None
        self.notifier = TelegramNotifier()
        self._ready = threading.Event()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self._ready.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="PulsePC-runtime")
        self.thread.start()
        self._ready.wait(10)

    def _run(self):
        loop = self.loop = asyncio.new_event_loop()
        loop.set_default_executor(FileIOExecutor())
        asyncio.set_event_loop(loop)

        async def boot():
            from modules.bot_features import BotFeatures
            self.features = BotFeatures(self.notifier)
            self.features.start()
        loop.run_until_complete(boot())
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(self.features.close())
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()

    def submit(self, coroutine) -> concurrent.futures.Future:
        """Run a coroutine on the runtime loop from any thread."""
        if not self.loop or not self.loop.is_running():
            coroutine.close()
            raise RuntimeError("Фоновая служба Pulse-PC не запущена.")
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def stop(self, timeout=8.0):
        loop = self.loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self.thread:
            self.thread.join(timeout)
