"""Stage C: journal, diagnostics and the «Консоль» screen."""
import logging
import os
import socket
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_pc.app import create_application  # noqa: E402

APP = create_application([])

from pulse_pc.core import logbook as lb  # noqa: E402
from pulse_pc.services.system import diagnostics as dg  # noqa: E402
from pulse_pc.ui.screens.console import ConsoleScreen  # noqa: E402

TOKEN = "123456789:AAH" + "x" * 30


class LogbookTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.book = lb.Logbook(self.dir.name)

    def tearDown(self):
        self.book.close()
        self.dir.cleanup()

    def test_parses_classic_panel_lines(self):
        entry = lb.parse_line("[2026-10-25 16:24:11]  WARNING  Нет связи с Telegram. Переподключение…")
        self.assertEqual((entry.level, entry.source), ("WARN", "telegram"))
        self.assertEqual(entry.time, datetime(2026, 10, 25, 16, 24, 11))
        entry = lb.parse_line("[2026-10-25 16:24:12]  INFO  Телефон «Pixel» подключён")
        self.assertEqual((entry.level, entry.source), ("INFO", "phone"))
        self.assertEqual(lb.parse_line("[2026-10-25 16:24:13]  Ошибка в работе бота").level, "ERROR")
        self.assertIsNone(lb.parse_line("   "))

    def test_tokens_never_reach_memory_or_disk(self):
        self.book.add(f"token {TOKEN} leaked")
        self.book.close()
        self.assertNotIn(TOKEN, self.book.entries[-1].text)
        self.assertNotIn(TOKEN, (Path(self.dir.name) / "pulse.log").read_text(encoding="utf-8"))

    def test_history_is_reloaded_in_the_shared_format(self):
        self.book.add("Первая", "WARN", "apps")
        self.book.close()
        again = lb.Logbook(self.dir.name)
        self.assertEqual(again.entries[-1].text, "Первая")
        self.assertEqual(again.entries[-1].level, "WARN")
        again.close()

    def test_logging_records_are_routed_by_logger(self):
        logger = logging.getLogger("modules.local_api.test")
        logger.propagate = False
        self.book.install(logger)
        logger.error("Порт занят")
        self.book.uninstall(logger)
        entry = self.book.entries[-1]
        self.assertEqual((entry.level, entry.source, entry.text), ("ERROR", "phone", "Порт занят"))
        self.assertEqual(self.book.counts["ERROR"], 1)
        self.assertEqual(lb.source_of("aiogram.dispatcher"), "telegram")
        self.assertEqual(lb.source_of("pulse_pc.services.system.programs"), "apps")
        self.assertEqual(lb.source_of("PySide6"), "system")

    def test_sequence_survives_rotation(self):
        small = lb.Logbook(capacity=3)
        for i in range(5):
            small.add(str(i))
        self.assertEqual([e.seq for e in small.entries], [3, 4, 5])


class DiagnosticsTests(unittest.TestCase):
    def test_telegram_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text("BOT_TOKEN=your_telegram_bot_token_here\nADMIN_ID=\n", encoding="utf-8")
            level, _, detail = dg.check_telegram_settings(env)
            self.assertEqual(level, dg.WARN)
            self.assertIn("ID администратора", detail)
            env.write_text(f"BOT_TOKEN='{TOKEN}'\nADMIN_ID='42'\n", encoding="utf-8")
            level, _, detail = dg.check_telegram_settings(env)
            self.assertEqual(level, dg.OK)
            self.assertNotIn(TOKEN, detail)

    def test_programs_file_states(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "programs.json"
            self.assertEqual(dg.check_programs(path)[0], dg.OK)
            path.write_text("{bad", encoding="utf-8")
            self.assertEqual(dg.check_programs(path)[0], dg.ERROR)
            path.write_text('[{"name": "X", "path": "C:/nope/x.exe"}]', encoding="utf-8")
            level, _, detail = dg.check_programs(path)
            self.assertEqual(level, dg.WARN)
            self.assertIn("X", detail)

    def test_busy_port_is_reported(self):
        with socket.socket() as server:
            server.bind(("0.0.0.0", 0))
            server.listen()
            self.assertEqual(dg.check_port(server.getsockname()[1])[0], dg.WARN)

    def test_offline_telegram_is_an_error_not_a_crash(self):
        with mock.patch.object(dg.socket, "getaddrinfo", side_effect=OSError("no dns")):
            level, _, detail = dg.check_telegram_reachable()
        self.assertEqual(level, dg.ERROR)
        self.assertIn("DNS", detail)

    def test_run_all_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            results = dg.run_all(folder, Path(folder) / "p.json", Path(folder) / ".env", 0, 0, network=False)
        self.assertTrue(all(len(r) == 3 for r in results))
        self.assertNotIn("Связь с Telegram", [title for _, title, _ in results])


class ConsoleScreenTests(unittest.TestCase):
    def setUp(self):
        self.book = lb.Logbook()
        self.book.add("Система готова", "INFO", "system")
        self.book.add("Бот остановлен", "WARN", "telegram")
        self.book.add("Порт занят", "ERROR", "phone")
        self.screen = ConsoleScreen(logbook=self.book)

    def lines(self):
        text = self.screen.view.toPlainText()
        return [line for line in text.splitlines() if line]

    def test_filters_by_source_level_and_text(self):
        self.assertEqual(len(self.lines()), 3)
        self.screen.set_source("telegram")
        self.assertEqual(len(self.lines()), 1)
        self.screen.set_source("all")
        self.screen.level_buttons["INFO"].setChecked(False)
        self.assertEqual(len(self.lines()), 2)
        self.screen.search.setText("порт")
        self.assertEqual(len(self.lines()), 1)
        self.assertIn("Порт занят", self.lines()[0])

    def test_live_entries_respect_filters(self):
        self.screen.set_source("phone")
        self.book.add("Телефон подключён", "INFO", "phone")
        self.book.add("Бот запущен", "INFO", "telegram")
        self.assertEqual(len(self.lines()), 2)
        self.assertEqual(self.screen.stat_labels["total"].text(), "5")

    def test_clear_view_keeps_history(self):
        self.screen.clear_view()
        self.assertEqual(self.lines(), [])
        self.book.add("После очистки")
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(len(self.book.entries), 4)

    def test_diagnostics_results_are_logged(self):
        self.screen._diagnostics_done([("INFO", "Окружение", "ok"), ("ERROR", "Связь с Telegram", "нет сети")])
        self.assertIn("замечаний — 1", self.book.entries[-1].text)
        self.assertTrue(self.screen.diagnose_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
