"""Server features for the PulseDesk phone app: access levels, processes, file operations, metrics fields."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase
from modules import mobile_access
from modules.local_api import make_app

AUTH = {"Authorization": "Bearer test"}


class AccessLevelTests(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    def as_device(self, access):
        device = {"id": "phone"} if access is None else {"id": "phone", "access": access}
        return patch("modules.local_api.mobile_access.authenticate", return_value=device)

    async def test_view_only_phone_reads_monitoring_but_cannot_control(self):
        with self.as_device(mobile_access.ACCESS_VIEW), \
             patch("modules.monitor.workstation_locked", return_value=False), \
             patch("modules.local_api.load_programs", return_value={}):
            self.assertEqual((await self.client.get("/api/events", headers=AUTH)).status, 200)
            for method, path in (("POST", "/api/system/lock"), ("GET", "/api/files/roots"),
                                 ("GET", "/api/screenshot"), ("GET", "/api/programs"), ("GET", "/api/processes")):
                response = await self.client.request(method, path, headers=AUTH)
                self.assertEqual(response.status, 403, path)
                self.assertIn("только для просмотра", (await response.json())["error"])

    async def test_phones_paired_before_access_levels_keep_full_control(self):
        with self.as_device(None), patch("modules.monitor.workstation_locked", return_value=False), \
             patch("modules.local_api.load_programs", return_value={}):
            self.assertEqual((await self.client.get("/api/programs", headers=AUTH)).status, 200)

    def test_set_access_rejects_unknown_level(self):
        with self.assertRaises(ValueError):
            mobile_access.set_access("x", "admin")


class FileOperationTests(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch("modules.local_api.mobile_access.authenticate", return_value={"id": "phone"}),
                        patch("modules.monitor.workstation_locked", return_value=False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()
        super().tearDown()

    async def post(self, path, body):
        return await self.client.post(path, json=body, headers=AUTH)

    async def test_mkdir_and_rename(self):
        response = await self.post("/api/files/mkdir", {"path": str(self.root), "name": "Новая"})
        self.assertEqual(response.status, 200)
        self.assertTrue((self.root / "Новая").is_dir())
        response = await self.post("/api/files/rename", {"path": str(self.root / "Новая"), "name": "Готово"})
        self.assertEqual(response.status, 200)
        self.assertTrue((self.root / "Готово").is_dir())

    async def test_bad_names_and_existing_targets_are_refused(self):
        (self.root / "a").mkdir()
        for name in ("", "..", "x/y", "a:b", "a"):
            response = await self.post("/api/files/mkdir", {"path": str(self.root), "name": name})
            self.assertEqual(response.status, 400, name)

    async def test_drive_root_and_relative_paths_are_refused(self):
        drive = Path(os.environ.get("SystemDrive", "C:") + "\\")
        for path in (str(drive), "relative\\path"):
            response = await self.post("/api/files/delete", {"path": path})
            self.assertEqual(response.status, 400, path)

    async def test_delete_goes_to_recycle_bin(self):
        target = self.root / "old.txt"
        target.write_text("x")
        with patch("modules.local_api.to_recycle_bin") as recycle:
            response = await self.post("/api/files/delete", {"path": str(target)})
        self.assertEqual(response.status, 200)
        recycle.assert_called_once_with(target.resolve())


class ProcessTests(unittest.TestCase):
    def test_list_has_real_fields(self):
        from modules.local_api import list_processes
        processes = list_processes(limit=5)
        self.assertTrue(processes)
        self.assertEqual(set(processes[0]), {"pid", "name", "cpu", "memory", "protected"})
        self.assertNotIn(0, [p["pid"] for p in list_processes()])

    def test_system_and_own_processes_are_protected(self):
        from modules.local_api import end_process
        for pid in (0, 4, os.getpid()):
            with self.assertRaises(ValueError):
                end_process(pid)

    def test_protected_names_are_refused(self):
        from modules.local_api import end_process
        fake = SimpleNamespace(name=lambda: "lsass.exe")
        with patch("psutil.Process", return_value=fake), self.assertRaises(ValueError):
            end_process(1234)


class MetricsFieldTests(unittest.TestCase):
    def test_uptime_and_per_core_are_sent(self):
        from modules.display_api import metrics_message
        snap = SimpleNamespace(cpu=10, gpu=None, gpu_name="", ram=50, ram_used=1, ram_total=2, disks=[],
                               cpu_per_core=[5.04, 15.0], uptime=3600.4)
        message = metrics_message(snap)
        self.assertEqual(message["cpu"]["per_core"], [5.0, 15.0])
        self.assertEqual(message["uptime"], 3600)


if __name__ == "__main__":
    unittest.main()
