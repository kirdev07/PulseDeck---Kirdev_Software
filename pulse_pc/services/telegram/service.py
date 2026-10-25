"""Telegram bot as an independent service on the shared runtime loop.

Same handlers, commands and admin check as before (modules/*_handlers.py, AuthMiddleware);
the local API is NOT started here any more, so stopping the bot never affects the phone.

Connection policy (official Bot API via aiogram, no hard-coded addresses):
  * network errors / timeouts -> RECONNECTING with exponential backoff (2 s … 60 s);
  * RetryAfter -> wait as Telegram asks;
  * invalid token (401) or polling conflict (409, another instance / webhook) -> ERROR,
    polling stops; retrying would only repeat the error.
"""
import asyncio
import importlib
import logging
import time

import config
from pulse_pc.core import state as st

logger = logging.getLogger("pulse_pc.services.telegram")
HANDLER_MODULES = ("advanced_handlers", "remote_tools", "system_handlers", "media_handlers", "program_handlers",
                   "file_handlers")
POLLING_TIMEOUT = 25        # long polling, seconds
REQUEST_TIMEOUT = 35        # must exceed the polling timeout


def read_credentials():
    """(token, admin id) as saved in config/.env, re-read on every start."""
    importlib.reload(config)
    return config.BOT_TOKEN, config.ADMIN_ID


class FatalTelegramError(Exception):
    """Errors that retrying cannot fix (bad token, conflict, missing settings)."""


class TelegramService:
    def __init__(self, runtime, store, api_base=None, credentials=None):
        self.runtime = runtime
        self.credentials = credentials or read_credentials
        self.store = store
        self.api_base = api_base    # tests point aiogram at a local fake Bot API; None = api.telegram.org
        self.task = None
        self.bot = None
        self.counters = {"updates": 0, "denied": 0, "failures": 0}
        self._fatal = None          # reason when the service cancelled itself

    @property
    def running(self):
        return self.task is not None and not self.task.done()

    # ----- control (any thread) -----
    def start(self):
        return self.runtime.submit(self._start())

    def stop(self):
        return self.runtime.submit(self._stop())

    def restart(self):
        return self.runtime.submit(self._restart())

    async def _start(self):
        if self.running:
            return
        self.counters = dict.fromkeys(self.counters, 0)
        self._fatal = None
        self._post(status=st.STARTING, error="", updates=0, denied=0, failures=0)
        self.task = asyncio.create_task(self._run(), name="telegram")

    async def _stop(self):
        task = self.task
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.task = None

    async def _restart(self):
        await self._stop()
        await self._start()

    # ----- lifecycle (runtime loop) -----
    def _post(self, **changes):
        self.store.post("telegram", **changes)

    async def _run(self):
        try:
            await self._serve()
            self._post(status=st.STOPPED, since=0.0)
        except asyncio.CancelledError:
            if self._fatal:         # stopped by a fatal polling error, not by the user
                self._post(status=st.ERROR, error=self._fatal, since=0.0)
                return
            self._post(status=st.STOPPED, since=0.0)
            logger.info("Telegram-бот остановлен.")
            raise
        except FatalTelegramError as exc:
            self._post(status=st.ERROR, error=str(exc), since=0.0)
            logger.error("Telegram-бот остановлен: %s", exc)
        except Exception as exc:  # noqa: BLE001 - any crash becomes a visible error state
            from desktop_services import telegram_error
            self._post(status=st.ERROR, error=telegram_error(exc), since=0.0)
            logger.exception("Сбой Telegram-бота")

    async def _serve(self):
        from aiogram import Bot, Dispatcher
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.exceptions import TelegramUnauthorizedError
        from aiogram.utils.token import TokenValidationError

        token, admin = self.credentials()
        config.ADMIN_ID = admin     # AuthMiddleware reads it from the config module
        if not token or token == "your_telegram_bot_token_here":
            raise FatalTelegramError("Токен бота не настроен. Укажите его в Настройках.")
        if not admin:
            raise FatalTelegramError("Не указан ID администратора. Без него бот никого не пустит.")
        try:
            session = AiohttpSession(timeout=REQUEST_TIMEOUT)
            if self.api_base:
                from aiogram.client.telegram import TelegramAPIServer
                session = AiohttpSession(api=TelegramAPIServer.from_base(self.api_base), timeout=REQUEST_TIMEOUT)
            bot = Bot(token=token, session=session)
        except TokenValidationError as exc:
            raise FatalTelegramError("Токен имеет неверный формат. Скопируйте его из @BotFather целиком.") from exc
        self.bot = bot
        features = self.runtime.features
        monitor_task = None
        try:
            bot.session.middleware(self._request_status)
            dp = Dispatcher()
            dp["features"] = features
            middleware = importlib.reload(importlib.import_module("modules.middleware"))
            auth = middleware.AuthMiddleware()
            for observer in (dp.message, dp.edited_message, dp.callback_query):
                observer.outer_middleware(self._count)
                observer.middleware(auth)
            # A Router belongs to one Dispatcher: reload modules to get fresh routers each start.
            for name in HANDLER_MODULES:
                dp.include_router(importlib.reload(importlib.import_module(f"modules.{name}")).router)
            dp.errors.register(self._on_error)

            me = await self._connect(bot)
            self._post(bot_name=me.username or "", bot_title=me.full_name)
            await self._startup_messages(bot, admin)
            from modules.monitor import lock_monitor
            monitor_task = asyncio.create_task(lock_monitor(bot))
            self.runtime.notifier.bot = bot
            logger.info("Telegram-бот @%s запущен.", me.username)
            await dp.start_polling(bot, polling_timeout=POLLING_TIMEOUT, handle_signals=False, close_bot_session=False,
                                   backoff_config=_backoff())
        except TelegramUnauthorizedError as exc:
            raise FatalTelegramError(_UNAUTHORIZED) from exc
        finally:
            self.runtime.notifier.bot = None
            if monitor_task:
                monitor_task.cancel()
                await asyncio.gather(monitor_task, return_exceptions=True)
            await bot.session.close()
            self.bot = None

    async def _connect(self, bot):
        """getMe with retries; returns the bot user or raises a fatal error."""
        from aiogram.exceptions import (TelegramConflictError, TelegramNetworkError, TelegramRetryAfter,
                                        TelegramServerError, TelegramUnauthorizedError)
        delay = 2
        while True:
            try:
                return await bot.get_me(request_timeout=15)
            except TelegramUnauthorizedError as exc:
                raise FatalTelegramError(_UNAUTHORIZED) from exc
            except TelegramConflictError as exc:
                raise FatalTelegramError(_CONFLICT) from exc
            except TelegramRetryAfter as exc:
                self._post(status=st.RECONNECTING, error=f"Telegram просит подождать {exc.retry_after} с.")
                await asyncio.sleep(exc.retry_after)
            except (TelegramNetworkError, TelegramServerError, asyncio.TimeoutError, OSError) as exc:
                self._post(status=st.RECONNECTING, error="Нет связи с Telegram. Проверьте интернет, VPN или прокси.")
                logger.warning("Нет связи с Telegram (%s). Повтор через %s с.", type(exc).__name__, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def _startup_messages(self, bot, admin):
        from modules.keyboards import get_main_inline_keyboard, get_reply_keyboard
        from modules.utils import cleanup_old_files, should_send_startup_notification
        from modules.welcome import control_panel_text, welcome_text
        await asyncio.to_thread(cleanup_old_files, 3)
        if not should_send_startup_notification():
            return
        try:
            await bot.send_message(admin, welcome_text(startup=True), reply_markup=get_reply_keyboard(), parse_mode="HTML")
            await bot.send_message(admin, control_panel_text(), reply_markup=get_main_inline_keyboard(), parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001 - the bot works without the greeting
            from desktop_services import telegram_error
            logger.warning("Не удалось отправить приветствие администратору: %s", telegram_error(exc))

    async def _request_status(self, make_request, bot, method):
        """Session middleware: turns getUpdates outcomes into connection states."""
        from aiogram.exceptions import TelegramConflictError, TelegramUnauthorizedError
        from aiogram.methods import GetUpdates
        if not isinstance(method, GetUpdates):
            return await make_request(bot, method)
        try:
            result = await make_request(bot, method)
        except TelegramConflictError:
            logger.error(_CONFLICT)
            asyncio.get_running_loop().call_soon(self._cancel_self, _CONFLICT)
            raise
        except TelegramUnauthorizedError:
            asyncio.get_running_loop().call_soon(self._cancel_self, _UNAUTHORIZED)
            raise
        except Exception:
            self._post(status=st.RECONNECTING, error="Нет связи с Telegram. Переподключение…")
            raise
        if self.store.state.telegram.status != st.RUNNING:
            self._post(status=st.RUNNING, error="", since=time.time())
        return result

    def _cancel_self(self, reason):
        # Polling would retry a fatal error forever; stop it and keep the ERROR state.
        if self.task and not self.task.done():
            self._fatal = reason
            self.task.cancel()

    async def _count(self, handler, event, data):
        import config as current
        self.counters["updates"] += 1
        user = getattr(event, "from_user", None)
        if user and current.ADMIN_ID and user.id != current.ADMIN_ID:
            self.counters["denied"] += 1
        self._post(updates=self.counters["updates"], denied=self.counters["denied"])
        return await handler(event, data)

    async def _on_error(self, event):
        self.counters["failures"] += 1
        self._post(failures=self.counters["failures"])
        logger.error("Ошибка обработки команды Telegram: %s", event.exception)
        return True


_UNAUTHORIZED = "Telegram отклонил токен: он неверный или был отозван в @BotFather."
_CONFLICT = ("Этот бот уже получает обновления в другом месте: запущена вторая копия Pulse-PC "
             "или настроен webhook. Остановите другую копию и запустите бота снова.")


def _backoff():
    from aiogram.utils.backoff import BackoffConfig
    return BackoffConfig(min_delay=2.0, max_delay=60.0, factor=2.0, jitter=0.1)
