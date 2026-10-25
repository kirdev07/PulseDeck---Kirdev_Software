"""Stage C: metrics service and the «Главная» screen."""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_pc.app import create_application  # noqa: E402

APP = create_application([])

from pulse_pc.core import state as st  # noqa: E402
from pulse_pc.core.context import AppContext  # noqa: E402
from pulse_pc.core.state import StateStore  # noqa: E402
from pulse_pc.services.system import metrics  # noqa: E402
from pulse_pc.services.system.metrics import Disk, MetricsSampler, Snapshot  # noqa: E402
from pulse_pc.ui.components import UNAVAILABLE  # noqa: E402
from pulse_pc.ui.screens.dashboard import DashboardScreen  # noqa: E402


class NoGpu:
    available = False

    def read(self):
        return None, None

    def close(self):
        pass


class MetricsTests(unittest.TestCase):
    def test_gpu_load_is_busiest_engine_summed_over_processes(self):
        values = {
            "pid_1_luid_0x0_0xA_phys_0_eng_0_engtype_3D": 30.0,
            "pid_2_luid_0x0_0xA_phys_0_eng_0_engtype_3D": 25.0,
            "pid_2_luid_0x0_0xA_phys_0_eng_4_engtype_VideoDecode": 40.0,
            "pid_3_luid_0x0_0xB_phys_0_eng_0_engtype_3D": 10.0,
        }
        self.assertEqual(metrics.aggregate_engines(values), 55.0)
        self.assertIsNone(metrics.aggregate_engines({}))
        self.assertEqual(metrics.aggregate_engines({"pid_1_luid_x_phys_0_eng_0_engtype_3D": 180.0}), 100.0)

    def test_sample_without_gpu_reports_none(self):
        sampler = MetricsSampler(gpu=NoGpu())
        snap = sampler.sample()
        self.assertIsNone(snap.gpu)
        # The card name comes from the registry and stays known even without load counters.
        self.assertIsNotNone(snap.cpu)
        self.assertGreater(snap.ram_total, 0)
        self.assertIsNone(snap.net_down)  # rate needs two samples
        clock = [100.0]
        sampler.clock = lambda: clock[0]
        sampler.sample()
        clock[0] = 102.0
        self.assertIsNotNone(sampler.sample().net_down)

    def test_network_rate_uses_elapsed_time(self):
        counters = [mock.Mock(bytes_recv=1000, bytes_sent=500), mock.Mock(bytes_recv=5000, bytes_sent=900)]
        clock = iter([10.0, 12.0])
        sampler = MetricsSampler(gpu=NoGpu(), clock=lambda: next(clock))
        with mock.patch.object(metrics.psutil, "net_io_counters", side_effect=counters):
            sampler.sample()
            snap = sampler.sample()
        self.assertEqual(snap.net_down, 2000.0)
        self.assertEqual(snap.net_up, 200.0)

    def test_formatting(self):
        self.assertEqual(metrics.format_bytes(None), "—")
        self.assertEqual(metrics.format_bytes(512), "512 Б")
        self.assertEqual(metrics.format_bytes(1536, True), "1.5 КБ/с")
        self.assertEqual(metrics.format_uptime(59 * 60), "59 мин")
        self.assertEqual(metrics.format_uptime(3 * 86400 + 3600 * 2), "3 д 2 ч")

    def test_service_emits_and_stops(self):
        service = metrics.MetricsService(interval=0.05, sampler_factory=lambda: MetricsSampler(gpu=NoGpu()))
        received = []
        service.updated.connect(received.append)
        service.start()
        deadline = time.monotonic() + 3
        while not received and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.02)
        service.stop()
        self.assertTrue(received)
        self.assertIsInstance(received[0], Snapshot)
        self.assertFalse(service._thread.is_alive())


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.store = StateStore()
        self.opened = []
        self.screen = DashboardScreen(AppContext(store=self.store, navigate=self.opened.append))

    def snapshot(self, **changes):
        values = dict(time=0, cpu=12.0, cpu_freq_mhz=2100, cpu_cores=8, ram_used=4 << 30, ram_total=16 << 30,
                      gpu=None, disks=[Disk("C:", 50, 100)], net_down=2048.0, net_up=0.0, uptime=3700,
                      processes=120, battery=None)
        values.update(changes)
        return Snapshot(**values)

    def test_real_values_and_honest_unavailable(self):
        self.screen.apply(self.snapshot())
        self.assertEqual(self.screen.cpu.value.text(), "12%")
        self.assertEqual(self.screen.ram.value.text(), "25%")
        self.assertEqual(self.screen.gpu.value.text(), UNAVAILABLE)
        self.assertEqual(self.screen.disk.value.text(), "50%")
        self.assertEqual(self.screen.system_rows["gpu_name"].text(), UNAVAILABLE)
        self.assertEqual(self.screen.system_rows["battery"].text(), "Нет")
        self.assertEqual(self.screen.down.text(), "2.0 КБ/с")
        self.assertEqual(self.screen.system_rows["uptime"].text(), "1 ч 1 мин")

    def test_disk_tile_names_the_real_system_drive(self):
        self.screen.apply(self.snapshot(disks=[Disk("D:", 1, 2)]))
        self.assertEqual(self.screen.disk.name.text(), "Диск D:")
        self.screen.apply(self.snapshot(disks=[]))
        self.assertEqual(self.screen.disk.value.text(), UNAVAILABLE)

    def test_chart_gets_gaps_for_missing_gpu(self):
        self.screen.apply(self.snapshot())
        self.assertIsNone(self.screen.chart.data["GPU"][-1])
        self.assertEqual(self.screen.chart.data["CPU"][-1], 12.0)

    def test_services_show_unknown_until_reported(self):
        self.assertEqual(self.screen.telegram_status.text.text(), "Нет данных")
        self.assertEqual(self.screen.telegram_status.dot.state(), "off")
        self.store.update("telegram", status=st.RUNNING, bot_name="pulse_bot", since=time.time() - 120)
        self.assertEqual(self.screen.telegram_status.text.text(), "Активен")
        self.assertIn("@pulse_bot", self.screen.telegram_detail.text())
        self.store.update("phone", status=st.RUNNING, addresses=("192.168.1.5",), port=8765,
                          devices=({"id": "a", "name": "Pixel"},))
        self.assertIn("192.168.1.5:8765", self.screen.phone_detail.text())
        self.assertIn("1", self.screen.phone_detail.text())

    def test_player_card(self):
        self.assertEqual(self.screen.track_title.text(), "Ничего не играет")
        self.store.update("player", status="playing", title="Night Drive", artist="LXST", position=30, duration=120)
        self.assertEqual(self.screen.track_title.text(), "Night Drive")
        self.assertEqual(self.screen.track_progress.value(), 250)

    def test_quick_access_navigates(self):
        self.screen._go("console")
        self.assertEqual(self.opened, ["console"])


if __name__ == "__main__":
    unittest.main()
