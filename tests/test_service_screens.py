"""Stage D: «Telegram Бот» and «Телефон» screens driven by the shared state."""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_pc.app import create_application  # noqa: E402

APP = create_application([])

from modules import mobile_access  # noqa: E402
from pulse_pc.core import state as st  # noqa: E402
from pulse_pc.core.context import AppContext  # noqa: E402
from pulse_pc.core.logbook import Logbook  # noqa: E402
from pulse_pc.core.state import StateStore  # noqa: E402
from pulse_pc.ui.screens import phone as phone_screen  # noqa: E402
from pulse_pc.ui.screens.telegram import TelegramScreen  # noqa: E402


class FakeService:
    def __init__(self):
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def restart(self):
        self.calls.append("restart")

    def revoke(self, device_id):
        self.calls.append(("revoke", device_id))


class FakeServices:
    def __init__(self):
        self.telegram = FakeService()
        self.local_api = FakeService()


class ScreenTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        (self.root / "local_api.json").write_text(json.dumps({"port": 8765, "enabled": True, "allow_pairing": True,
                                                             "devices": []}), encoding="utf-8")
        self.patch = mock.patch.object(mobile_access, "PATH", str(self.root / "local_api.json"))
        self.patch.start()
        self.store = StateStore()
        self.book = Logbook()
        self.services = FakeServices()
        self.context = AppContext(store=self.store, logbook=self.book, services=self.services)

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()


class TelegramScreenTests(ScreenTestCase):
    def setUp(self):
        super().setUp()
        self.screen = TelegramScreen(self.context, config_dir=str(self.root))

    def test_states_and_buttons(self):
        self.assertEqual(self.screen.status.text.text(), "Нет данных")
        self.store.update("telegram", status=st.RUNNING, bot_name="pulse_bot", since=time.time() - 3600,
                          updates=5, denied=2)
        self.assertEqual(self.screen.status.text.text(), "Бот активен")
        self.assertEqual(self.screen.toggle_button.text(), "Остановить")
        self.assertEqual(self.screen.updates_tile.value.text(), "5")
        self.assertEqual(self.screen.denied_tile.value.text(), "2")
        self.assertEqual(self.screen.uptime_tile.value.text(), "1 ч 0 мин")
        self.screen.toggle()
        self.assertEqual(self.services.telegram.calls, ["stop"])
        self.store.update("telegram", status=st.ERROR, error="Telegram отклонил токен", since=0.0)
        self.assertEqual(self.screen.detail.text(), "Telegram отклонил токен")
        self.assertFalse(self.screen.restart_button.isEnabled())
        self.screen.toggle()
        self.assertEqual(self.services.telegram.calls, ["stop", "start"])

    def test_send_card_needs_the_runtime(self):
        self.assertFalse(self.screen.send_button.isEnabled())      # FakeServices has no runtime
        self.assertTrue(self.screen.send_bar.isHidden())

    def test_send_progress_text(self):
        self.screen.send_bar.show()
        self.screen._send_progress({"phase": "uploading", "total": 2, "completed": 1, "total_size": 2048,
                                    "total_transferred": 1024, "speed": 512.0,
                                    "active": [{"name": "b.bin", "transferred": 0, "size": 1024}]})
        self.assertEqual(self.screen.send_bar.value(), 500)
        self.assertIn("Отправлено 1 из 2", self.screen.send_status.text())
        self.assertIn("b.bin", self.screen.send_status.text())

    def test_only_telegram_entries_in_its_log(self):
        self.book.add("Бот запущен", source="telegram")
        self.book.add("Порт занят", "ERROR", "phone")
        text = self.screen.log_view.toPlainText()
        self.assertIn("Бот запущен", text)
        self.assertNotIn("Порт занят", text)

    def test_autostart_setting_persists(self):
        from pulse_pc.core.settings import SettingsStore
        self.screen.autostart.click()
        self.assertFalse(SettingsStore(self.root / "app_settings.json").load().telegram_autostart)


class PhoneScreenTests(ScreenTestCase):
    def setUp(self):
        super().setUp()
        self.screen = phone_screen.PhoneScreen(self.context)

    def addresses(self):
        rows = self.screen.address_rows
        return [rows.itemAt(i).widget().text() for i in range(rows.count())]

    def test_server_state_and_addresses(self):
        self.store.update("phone", status=st.RUNNING, addresses=("192.168.1.5",), port=8765)
        self.assertEqual(self.screen.status.text.text(), "Сервер активен")
        self.assertIn("192.168.1.5:8765", self.addresses())
        self.screen.toggle()
        self.assertEqual(self.services.local_api.calls, ["stop"])
        self.store.update("phone", status=st.ERROR, error="Порт 8765 занят", addresses=())
        self.assertEqual(self.screen.detail.text(), "Порт 8765 занят")

    def test_starting_by_hand_reenables_the_setting(self):
        mobile_access.set_option("enabled", False)
        self.store.update("phone", status=st.STOPPED)
        self.screen.toggle()
        self.assertTrue(mobile_access.load()["enabled"])
        self.assertEqual(self.services.local_api.calls, ["start"])

    def test_devices_online_and_revoke(self):
        now = datetime.now().isoformat(timespec="seconds")
        old = (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds")
        self.store.update("phone", devices=({"id": "a", "name": "Pixel", "added": old, "last_seen": now},
                                            {"id": "b", "name": "Galaxy", "added": old, "last_seen": ""}))
        self.assertEqual(self.screen.devices.rowCount(), 2)
        self.assertTrue(self.screen.devices.item(0, 0).text().startswith("●"))
        self.assertTrue(self.screen.devices.item(1, 0).text().startswith("○"))
        self.assertEqual(self.screen.devices.item(1, 1).text(), "ещё не подключался")
        from PySide6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.screen.devices.cellWidget(1, 3).click()
        self.assertEqual(self.services.local_api.calls, [("revoke", "b")])

    def test_pairing_switch(self):
        self.screen.pairing.click()
        self.assertFalse(mobile_access.load()["allow_pairing"])

    def test_relative_times(self):
        now = datetime(2026, 10, 25, 16, 0, 0)
        self.assertEqual(phone_screen.ago("2026-10-25T15:59:30", now), "только что")
        self.assertEqual(phone_screen.ago("2026-10-25T15:30:00", now), "30 мин назад")
        self.assertEqual(phone_screen.ago("2026-10-25T09:05:00", now), "сегодня в 09:05")
        self.assertEqual(phone_screen.ago("2026-10-20T09:05:00", now), "20.10.2026 09:05")
        self.assertTrue(phone_screen.is_online("2026-10-25T15:59:00", now))
        self.assertFalse(phone_screen.is_online("", now))


if __name__ == "__main__":
    unittest.main()
