"""Stage D: independent Telegram and phone services on the shared runtime.

The Telegram tests run the real aiogram stack against a local fake Bot API, so polling,
admin checks, conflicts and bad tokens are exercised without network access."""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_pc.app import create_application  # noqa: E402

APP = create_application([])

from aiohttp import web  # noqa: E402

from modules import mobile_access  # noqa: E402
from pulse_pc.core import state as st  # noqa: E402
from pulse_pc.core.state import StateStore  # noqa: E402
from pulse_pc.services.local_api.service import LocalApiService  # noqa: E402
from pulse_pc.services.runtime import Runtime  # noqa: E402
from pulse_pc.services.telegram.service import TelegramService  # noqa: E402

TOKEN = "123456789:AAH" + "x" * 32
ADMIN = 1001
STRANGER = 2002


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    APP.processEvents()
    return predicate()


class FakeBotApi:
    """Minimal Bot API: getMe, getUpdates, sendMessage (+ failure modes)."""

    def __init__(self):
        self.updates = []
        self.sent = []
        self.documents = []
        self.mode = "ok"            # ok | conflict | unauthorized
        self.polls = 0
        self._next_id = 1
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(5)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        app = web.Application()
        app.router.add_post("/bot{token}/{method}", self.handle)
        self.runner = web.AppRunner(app)
        self.loop.run_until_complete(self.runner.setup())
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        self.loop.run_until_complete(site.start())
        self.port = self.runner.addresses[0][1]
        self.ready.set()
        self.loop.run_forever()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def message(self, user_id, text):
        self.updates.append({"update_id": self._next_id, "message": {
            "message_id": self._next_id, "date": int(time.time()), "text": text,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "User"},
            **({"entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]}
               if text.startswith("/") else {})}})
        self._next_id += 1

    async def handle(self, request):
        method = request.match_info["method"].lower()
        if request.content_type.startswith("multipart"):
            data = {}
            async for part in await request.multipart():
                raw = await part.read()
                data[part.name] = raw.decode("utf-8", "replace") if not part.filename else raw
                if part.filename:
                    data["filename"] = part.filename
        else:
            data = dict(await request.post())
        if self.mode == "unauthorized":
            return web.json_response({"ok": False, "error_code": 401, "description": "Unauthorized"}, status=401)
        if method == "getme":
            return web.json_response({"ok": True, "result": {"id": 1, "is_bot": True, "first_name": "Pulse Test",
                                                             "username": "pulse_test_bot"}})
        if method == "getupdates":
            self.polls += 1
            if self.mode == "conflict":
                return web.json_response({"ok": False, "error_code": 409,
                                          "description": "Conflict: terminated by other getUpdates request"}, status=409)
            offset = int(data.get("offset") or 0)
            pending = [u for u in self.updates if u["update_id"] >= offset]
            if not pending:
                await asyncio.sleep(0.2)
            return web.json_response({"ok": True, "result": pending})
        if method == "senddocument":
            self.documents.append(data)
            return web.json_response({"ok": True, "result": {
                "message_id": 900 + len(self.documents), "date": int(time.time()),
                "chat": {"id": int(data["chat_id"]), "type": "private"},
                "document": {"file_id": "f", "file_unique_id": "u", "file_name": data.get("filename", "")}}})
        if method == "sendmessage":
            self.sent.append(data)
            return web.json_response({"ok": True, "result": {
                "message_id": 500 + len(self.sent), "date": int(time.time()), "text": data.get("text", ""),
                "chat": {"id": int(data["chat_id"]), "type": "private"}}})
        return web.json_response({"ok": True, "result": True})

    def close(self):
        asyncio.run_coroutine_threadsafe(self.runner.cleanup(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "local_api.json").write_text(json.dumps({"port": 0, "tls_port": 0, "enabled": True, "allow_pairing": False,
                                                        "devices": []}), encoding="utf-8")
        self.patches = [
            mock.patch.object(mobile_access, "PATH", str(root / "local_api.json")),
            mock.patch("modules.utils.cleanup_old_files", lambda *_: None),
            mock.patch("modules.utils.should_send_startup_notification", lambda: False),
            mock.patch("modules.monitor.workstation_locked", lambda: False),
        ]
        for patch in self.patches:
            patch.start()
        self.store = StateStore()
        self.runtime = Runtime()
        self.runtime.start()
        self.api = FakeBotApi()

    def tearDown(self):
        for service in getattr(self, "services", ()):
            try:
                service.stop().result(10)
            except Exception:  # noqa: BLE001
                pass
        self.runtime.stop()
        self.api.close()
        for patch in self.patches:
            patch.stop()
        self.dir.cleanup()

    def telegram(self, token=TOKEN, admin=ADMIN):
        service = TelegramService(self.runtime, self.store, api_base=self.api.base, credentials=lambda: (token, admin))
        self.services = getattr(self, "services", []) + [service]
        return service

    def local_api(self):
        service = LocalApiService(self.runtime, self.store, self.dir.name)
        self.services = getattr(self, "services", []) + [service]
        return service

    def telegram_status(self):
        return self.store.state.telegram.status


class TelegramServiceTests(ServiceTestCase):
    def test_start_handles_admin_command_and_stops(self):
        bot = self.telegram()
        bot.start().result(5)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.RUNNING))
        self.assertEqual(self.store.state.telegram.bot_name, "pulse_test_bot")
        self.api.message(ADMIN, "/status")
        self.assertTrue(wait_for(lambda: any(str(ADMIN) == m["chat_id"] for m in self.api.sent)))
        self.assertIn("Процессор", self.api.sent[-1]["text"])
        self.assertTrue(wait_for(lambda: self.store.state.telegram.updates >= 1))
        bot.stop().result(10)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.STOPPED))
        self.assertIsNone(self.runtime.notifier.bot)

    def test_startup_greeting_sends_the_shared_panel(self):
        with mock.patch("modules.utils.should_send_startup_notification", lambda: True),                 mock.patch("modules.welcome.control_panel_text", return_value="<b>Same panel</b>"):
            self.telegram().start().result(5)
            self.assertTrue(wait_for(lambda: len(self.api.sent) >= 2))
        self.assertIn("Pulse PC на связи", self.api.sent[0]["text"])
        self.assertEqual((self.api.sent[1]["chat_id"], self.api.sent[1]["text"]), (str(ADMIN), "<b>Same panel</b>"))

    def test_search_commands_and_links(self):
        opened = []
        with mock.patch("webbrowser.open", side_effect=opened.append):
            self.telegram().start().result(5)
            self.assertTrue(wait_for(lambda: self.telegram_status() == st.RUNNING))
            # AuthMiddleware drops commands sent less than 0.5 s apart, so pace them.
            for text in ("/stop", "/settings", "/s погода", "/s@pulse_test_bot кот", "? новости"):
                self.api.message(ADMIN, text)
                wait_for(lambda: False, 0.7)
            self.api.message(ADMIN, "смотри https://example.org/a.")
            self.api.updates[-1]["message"]["entities"] = [{"type": "url", "offset": 7, "length": 21}]
            self.assertTrue(wait_for(lambda: len(opened) >= 4, 15))
            time.sleep(1)   # make sure nothing else opens late
        searches = [u for u in opened if "google.com/search" in u]
        self.assertEqual(len(searches), 3, opened)                 # /stop and /settings are not searches
        self.assertTrue(any("%D0%BF%D0%BE%D0%B3%D0%BE%D0%B4%D0%B0" in u for u in searches))
        self.assertEqual([u for u in opened if "example.org" in u], ["https://example.org/a"])   # once, no dot

    def test_stranger_is_refused_and_counted(self):
        bot = self.telegram()
        bot.start().result(5)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.RUNNING))
        self.api.message(STRANGER, "/status")
        self.assertTrue(wait_for(lambda: self.store.state.telegram.denied == 1))
        self.assertTrue(wait_for(lambda: any(m["chat_id"] == str(STRANGER) for m in self.api.sent)))
        reply = next(m for m in self.api.sent if m["chat_id"] == str(STRANGER))
        self.assertIn("Доступ ограничен", reply["text"])
        self.assertNotIn("Процессор", reply["text"])

    def test_polling_conflict_stops_with_error(self):
        self.api.mode = "conflict"
        self.telegram().start().result(5)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.ERROR, 15))
        self.assertIn("другом месте", self.store.state.telegram.error)
        polls = self.api.polls
        time.sleep(1)
        self.assertEqual(self.api.polls, polls)   # no endless retry

    def test_rejected_token_is_an_error(self):
        self.api.mode = "unauthorized"
        self.telegram().start().result(5)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.ERROR))
        self.assertIn("токен", self.store.state.telegram.error)

    def test_missing_settings_are_reported(self):
        self.telegram(token="your_telegram_bot_token_here").start().result(5)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.ERROR))
        self.assertIn("Токен", self.store.state.telegram.error)

    def test_setup_mode_tells_the_id_and_runs_nothing(self):
        self.telegram(admin=None).start().result(5)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.RUNNING))
        self.assertIn("Режим настройки", self.store.state.telegram.error)
        self.api.message(STRANGER, "/status")
        self.assertTrue(wait_for(lambda: any(m["chat_id"] == str(STRANGER) for m in self.api.sent)))
        reply = next(m for m in self.api.sent if m["chat_id"] == str(STRANGER))
        self.assertIn(str(STRANGER), reply["text"])            # the sender learns their ID
        self.assertNotIn("Процессор", reply["text"])          # and nothing is executed

    def test_unreachable_server_means_reconnecting(self):
        service = TelegramService(self.runtime, self.store, api_base="http://127.0.0.1:9",
                                  credentials=lambda: (TOKEN, ADMIN))
        self.services = [service]
        service.start().result(5)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.RECONNECTING))
        self.assertIn("Нет связи", self.store.state.telegram.error)
        service.stop().result(10)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.STOPPED))


class IndependenceTests(ServiceTestCase):
    def ping(self, service):
        port = service.server.runner.addresses[0][1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=5) as response:
            return json.loads(response.read())

    def test_phone_server_survives_telegram_stop_and_failure(self):
        phone = self.local_api()
        phone.start().result(10)
        self.assertTrue(wait_for(lambda: self.store.state.phone.status == st.RUNNING))
        bot = self.telegram()
        bot.start().result(5)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.RUNNING))
        bot.stop().result(10)
        self.assertTrue(self.ping(phone)["ok"])
        self.api.mode = "unauthorized"
        bot.start().result(5)
        self.assertTrue(wait_for(lambda: self.telegram_status() == st.ERROR))
        self.assertTrue(self.ping(phone)["ok"])
        self.assertEqual(self.store.state.phone.status, st.RUNNING)

    def test_phone_requests_still_need_a_device_token(self):
        phone = self.local_api()
        phone.start().result(10)
        port = phone.server.runner.addresses[0][1]
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5)
        self.assertEqual(caught.exception.code, 401)

    def test_power_timer_works_without_telegram(self):
        features = self.runtime.features
        with mock.patch("modules.bot_features.subprocess.Popen") as popen:
            seconds = self.runtime.submit(asyncio.to_thread(lambda: None)).result(5) or \
                self.runtime.loop.call_soon_threadsafe(features.schedule_power, "shutdown", 5)
            self.assertTrue(wait_for(lambda: features.power_task is not None))
            self.assertTrue(self.runtime.submit(features.cancel_power()).result(5))
            popen.assert_not_called()
        del seconds

    def test_revoke_removes_device(self):
        phone = self.local_api()
        mobile_access.add_device("Pixel")
        phone.refresh()
        self.assertTrue(wait_for(lambda: len(self.store.state.phone.devices) == 1))
        self.assertNotIn("hash", self.store.state.phone.devices[0])
        phone.revoke(self.store.state.phone.devices[0]["id"])
        self.assertTrue(wait_for(lambda: self.store.state.phone.devices == ()))

    def test_disabled_server_is_not_started(self):
        mobile_access.set_option("enabled", False)
        phone = self.local_api()
        phone.start().result(10)
        self.assertTrue(wait_for(lambda: self.store.state.phone.status == st.STOPPED))
        self.assertFalse(phone.running)
        self.assertIn("выключен", self.store.state.phone.error)


class FileSenderTests(ServiceTestCase):
    def bot_factory(self):
        """aiogram.Bot that talks to the fake API (send_files_with_token builds its own Bot)."""
        import aiogram
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.client.telegram import TelegramAPIServer
        real = aiogram.Bot
        base = self.api.base
        return lambda token, **kw: real(token, session=AiohttpSession(api=TelegramAPIServer.from_base(base)))

    def test_files_reach_the_admin_chat_with_progress(self):
        from pulse_pc.services.telegram.file_sender import FileSender
        root = Path(self.dir.name)
        files = []
        for name, size in (("a.txt", 300_000), ("b.bin", 70_000)):
            (root / name).write_bytes(os.urandom(size))
            files.append(str(root / name))
        sender = FileSender(self.runtime)
        progress, done = [], []
        sender.progress.connect(progress.append)
        sender.finished.connect(lambda ok, text: done.append((ok, text)))
        with mock.patch("aiogram.Bot", self.bot_factory()),                 mock.patch("modules.transfer_history.record_transfer"):
            sender.send(TOKEN, ADMIN, files)
            self.assertTrue(wait_for(lambda: bool(done), 20))
        self.assertEqual(done[0], (True, "Отправлено файлов: 2 из 2."))
        self.assertEqual(sorted(d["filename"] for d in self.api.documents), ["a.txt", "b.bin"])
        self.assertTrue(all(d["chat_id"] == str(ADMIN) for d in self.api.documents))
        self.assertEqual(progress[-1]["phase"], "completed")
        self.assertEqual(progress[-1]["total_transferred"], 370_000)

    def test_validation_errors_are_reported(self):
        from pulse_pc.services.telegram.file_sender import FileSender
        sender = FileSender(self.runtime)
        with self.assertRaises(ValueError):
            sender.send("", ADMIN, ["x"])
        with self.assertRaises(ValueError):
            sender.send(TOKEN, "", ["x"])
        done = []
        sender.finished.connect(lambda ok, text: done.append((ok, text)))
        with mock.patch("modules.transfer_history.record_transfer"):
            sender.send(TOKEN, ADMIN, [str(Path(self.dir.name) / "missing.txt")])
            self.assertTrue(wait_for(lambda: bool(done)))
        self.assertFalse(done[0][0])
        self.assertIn("не найден", done[0][1])


if __name__ == "__main__":
    unittest.main()
