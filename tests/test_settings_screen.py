"""Stage C: settings storage and the «Настройки» screen."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_pc.app import create_application  # noqa: E402

APP = create_application([])

from modules import mobile_access  # noqa: E402
from pulse_pc.core import settings as cfg  # noqa: E402
from pulse_pc.core.context import AppContext  # noqa: E402
from pulse_pc.core.logbook import Logbook  # noqa: E402
from pulse_pc.services.system import components  # noqa: E402
from pulse_pc.ui.screens import settings as screen_module  # noqa: E402

TOKEN = "123456789:AAH" + "x" * 32


class EnvTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / ".env"

    def tearDown(self):
        self.dir.cleanup()

    def test_write_keeps_other_lines_and_roundtrips_quotes(self):
        self.path.write_text("# comment\nOTHER=1\nBOT_TOKEN=old\n", encoding="utf-8")
        cfg.write_env(self.path, {"BOT_TOKEN": TOKEN, "ADMIN_ID": "42"})
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# comment", text)
        self.assertIn("OTHER=1", text)
        self.assertNotIn("old", text)
        self.assertEqual(cfg.read_env(self.path), {"OTHER": "1", "BOT_TOKEN": TOKEN, "ADMIN_ID": "42"})
        cfg.write_env(self.path, {"X": r"it's \ ok"})
        self.assertEqual(cfg.read_env(self.path)["X"], r"it's \ ok")

    def test_classic_panel_and_dotenv_read_the_same_values(self):
        from dotenv import dotenv_values
        cfg.write_env(self.path, {"BOT_TOKEN": TOKEN, "ADMIN_ID": "42"})
        self.assertEqual(dotenv_values(self.path)["BOT_TOKEN"], TOKEN)

    def test_validation_and_mask(self):
        self.assertEqual(cfg.validate_telegram("", ""), [])
        self.assertEqual(cfg.validate_telegram(TOKEN, "42"), [])
        self.assertEqual(len(cfg.validate_telegram("abc", "-1")), 2)
        self.assertEqual(cfg.mask(TOKEN), "123456789:••••••••xxxx")
        self.assertEqual(cfg.mask(cfg.PLACEHOLDER_TOKEN), "")

    def test_ui_settings_ignore_bad_values(self):
        store = cfg.SettingsStore(Path(self.dir.name) / "app.json")
        self.assertTrue(store.load().animations)
        (Path(self.dir.name) / "app.json").write_text('{"animations": "no", "unknown": 1}', encoding="utf-8")
        self.assertTrue(store.load().animations)
        store.save(cfg.UiSettings(animations=False))
        self.assertFalse(store.load().animations)


class ComponentsTests(unittest.TestCase):
    def test_installed_components_have_versions_and_licenses(self):
        items = {item["name"].lower(): item for item in components.installed()}
        self.assertIn("pyside6", items)
        self.assertIn("aiogram", items)
        self.assertTrue(all(item["version"] and item["license"] for item in items.values()))


class SettingsScreenTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.patches = [mock.patch.object(mobile_access, "PATH", str(self.root / "local_api.json")),
                        mock.patch.object(screen_module.autostart, "is_enabled", return_value=False),
                        mock.patch.object(screen_module.autostart, "set_enabled", side_effect=lambda on: on)]
        for patch in self.patches:
            patch.start()
        self.book = Logbook()
        self.context = AppContext(logbook=self.book, navigate=lambda key: self.opened.append(key))
        self.opened = []
        self.screen = screen_module.SettingsScreen(self.context, self.root)

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.dir.cleanup()

    def test_saving_telegram_settings(self):
        self.screen.token.setText("bad")
        self.assertFalse(self.screen.save_telegram())
        self.assertFalse((self.root / ".env").exists())
        self.screen.token.setText(TOKEN)
        self.screen.admin.setText("42")
        self.assertTrue(self.screen.save_telegram())
        self.assertEqual(cfg.read_env(self.root / ".env")["ADMIN_ID"], "42")
        self.book.add(f"token {TOKEN.split(':')[1]} in a message")
        self.assertNotIn(TOKEN.split(":")[1], self.book.entries[-1].text)   # secret now masked in the journal

    def test_token_hidden_by_default(self):
        from PySide6.QtWidgets import QLineEdit
        self.assertEqual(self.screen.token.echoMode(), QLineEdit.EchoMode.Password)
        self.screen._toggle_token()
        self.assertEqual(self.screen.token.echoMode(), QLineEdit.EchoMode.Normal)

    def test_phone_switches_write_mobile_access(self):
        self.screen.allow_pairing.click()
        self.assertFalse(mobile_access.load()["allow_pairing"])
        self.screen.server_enabled.click()
        self.assertFalse(mobile_access.load()["enabled"])

    def test_security_summary_reflects_real_state(self):
        def texts():
            lines = self.screen.security_lines
            return " ".join(lines.itemAt(i).widget().text.text() for i in range(lines.count() - 1))
        self.screen.refresh()
        self.assertIn("ID администратора не задан", texts())
        self.assertIn("не шифруется", texts())
        cfg.write_env(self.root / ".env", {"BOT_TOKEN": TOKEN, "ADMIN_ID": "7"})
        mobile_access.set_option("enabled", False)
        self.screen.refresh()
        self.assertIn("ограничен вашим Telegram ID", texts())
        self.assertIn("без шифрования", texts())
        self.assertIn("Сервер для телефона выключен", texts())

    def test_animations_apply_and_persist(self):
        self.screen.animations.click()
        self.assertFalse(cfg.SettingsStore(self.root / "app_settings.json").load().animations)

    def test_autostart_toggle_uses_service(self):
        self.screen.autostart.click()
        self.assertTrue(self.screen.autostart.isChecked())
        screen_module.autostart.set_enabled.assert_called_with(True)

    def test_documents_and_navigation(self):
        self.assertGreater(self.screen.components_table.rowCount(), 3)
        self.screen.open_section("support")
        self.assertEqual(self.screen.pages.currentIndex(), self.screen.section_index["support"])
        self.screen._navigate("console")
        self.assertEqual(self.opened, ["console"])


if __name__ == "__main__":
    unittest.main()
