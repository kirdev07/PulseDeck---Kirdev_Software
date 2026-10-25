"""Stage C: «Приложения» — program storage, usage sampling and the screen."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_pc.app import create_application  # noqa: E402

APP = create_application([])

from pulse_pc.services.system import programs as svc  # noqa: E402
from pulse_pc.ui.screens.apps import AppsScreen  # noqa: E402

PYTHON_NAME = Path(sys.executable).name.lower()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "programs.json"
        self.store = svc.ProgramStore(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def test_add_update_move_remove_roundtrip(self):
        first = self.store.add("Python", sys.executable, "интерпретатор")
        second = self.store.add("Ещё", sys.executable)
        self.assertEqual(first["process"], Path(sys.executable).name)
        self.store.move(second["id"], -1)
        self.assertEqual([p["id"] for p in self.store.load()], [second["id"], first["id"]])
        self.store.update(first["id"], "Python 3", sys.executable, "")
        self.assertEqual(self.store.load()[1]["name"], "Python 3")
        self.store.remove(second["id"])
        self.assertEqual([p["name"] for p in json.loads(self.path.read_text(encoding="utf-8"))], ["Python 3"])

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.store.add("", sys.executable)
        with self.assertRaises(ValueError):
            self.store.add("Нет файла", r"C:\nope\missing.exe")
        for i in range(svc.MAX_PROGRAMS):
            self.store.add(f"P{i}", sys.executable)
        with self.assertRaises(ValueError):
            self.store.add("Лишняя", sys.executable)

    def test_legacy_entries_get_ids(self):
        self.path.write_text(json.dumps([{"name": "Old", "path": sys.executable}]), encoding="utf-8")
        programs = self.store.load()
        self.assertTrue(programs[0]["id"])
        self.assertEqual(self.store.load()[0]["id"], programs[0]["id"])

    def test_broken_file_is_never_overwritten(self):
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(svc.ProgramsFileError):
            self.store.load()
        with self.assertRaises(svc.ProgramsFileError):
            self.store.add("X", sys.executable)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{broken")


class UsageTests(unittest.TestCase):
    def test_current_python_process_is_found(self):
        program = {"id": "py", "name": "Python", "path": sys.executable, "process": PYTHON_NAME}
        stopped = {"id": "none", "name": "None", "path": sys.executable, "process": "definitely-not-running.exe"}
        usage = svc.UsageSampler().sample([program, stopped])
        self.assertTrue(usage["py"].running)
        self.assertGreater(usage["py"].memory, 0)
        self.assertFalse(usage["none"].running)

    def test_process_names_accept_names_without_exe(self):
        self.assertEqual(svc.process_names({"path": "x", "process": "OBS64"}), {"obs64", "obs64.exe"})
        self.assertEqual(svc.process_names({"path": "C:/a.bat", "process": "ignored.exe"}), set())

    def test_close_refuses_unknown_or_stopped(self):
        with self.assertRaises(ValueError):
            svc.close({"path": "C:/a.bat"})
        with self.assertRaises(ValueError):
            svc.close({"path": "x.exe", "process": "definitely-not-running.exe"})


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = svc.ProgramStore(Path(self.dir.name) / "programs.json")
        self.store.add("Python", sys.executable)
        self.store.add("Нет процесса", sys.executable)
        programs = self.store.load()
        programs[1]["process"] = "definitely-not-running.exe"
        self.store.save(programs)
        self.screen = AppsScreen(store=self.store)

    def tearDown(self):
        self.screen.monitor.stop()
        self.screen.deleteLater()
        self.dir.cleanup()

    def wait_usage(self):
        self.screen.monitor.start()
        deadline = time.monotonic() + 5
        while len(self.screen.usage) < 2 and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.02)
        self.assertEqual(len(self.screen.usage), 2)

    def visible_names(self):
        table = self.screen.table
        return [table.item(r, 0).text() for r in range(table.rowCount()) if not table.isRowHidden(r)]

    def test_lists_programs_and_live_status(self):
        self.assertEqual(self.screen.table.rowCount(), 2)
        self.assertEqual(self.screen.running_tile.value.text(), "…")
        self.wait_usage()
        self.assertEqual(self.screen.table.item(0, 1).text()[:8], "Запущена")
        self.assertEqual(self.screen.table.item(1, 1).text(), "Остановлена")
        self.assertEqual(self.screen.running_tile.value.text(), "1")

    def test_filters_and_search(self):
        self.wait_usage()
        self.screen.set_filter("running")
        self.assertEqual(self.visible_names(), ["Python"])
        self.screen.set_filter("stopped")
        self.assertEqual(self.visible_names(), ["Нет процесса"])
        self.screen.set_filter("all")
        self.screen.search.setText("проц")
        self.assertEqual(self.visible_names(), ["Нет процесса"])

    def test_details_follow_selection(self):
        self.screen.table.selectRow(1)
        self.assertEqual(self.screen.details_title.text(), "Нет процесса")
        self.assertFalse(self.screen.down_button.isEnabled())
        self.assertTrue(self.screen.up_button.isEnabled())

    def test_move_and_delete_persist(self):
        self.screen.table.selectRow(1)
        self.screen.move_selected(-1)
        self.assertEqual([p["name"] for p in self.store.load()], ["Нет процесса", "Python"])
        self.assertEqual(self.screen.details_title.text(), "Нет процесса")
        from PySide6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.screen.delete_selected()
        self.assertEqual([p["name"] for p in self.store.load()], ["Python"])

    def test_broken_file_disables_editing(self):
        self.store.path.write_text("{broken", encoding="utf-8")
        self.screen.reload()
        self.assertFalse(self.screen.add_button.isEnabled())
        self.assertIn("programs.json", self.screen.message.text())
        self.assertTrue(self.screen.empty.isVisibleTo(self.screen))


if __name__ == "__main__":
    unittest.main()
