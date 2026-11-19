import tempfile
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from modules import display_api, player_access
from pulse_pc.services.web_panel import service, settings as web_settings

KEY = "k" * 24


class FakeReader:
    async def read(self):
        return {"type": "metrics", "cpu": {"load": 12.0}}

    def close(self):
        pass


class WebPanelSettingsTest(unittest.TestCase):
    def test_defaults_off_with_a_key(self):
        folder = tempfile.mkdtemp()
        data = web_settings.load(folder)
        self.assertFalse(data["enabled"])
        self.assertFalse(data["control"])
        self.assertEqual(data["port"], web_settings.DEFAULT_PORT)
        self.assertGreaterEqual(len(data["key"]), 16)
        self.assertEqual(web_settings.load(folder)["key"], data["key"])     # kept, not regenerated

    def test_bad_values_fall_back(self):
        folder = tempfile.mkdtemp()
        web_settings.save(folder, {"enabled": True, "port": 80, "key": "short"})
        data = web_settings.load(folder)
        self.assertEqual(data["port"], web_settings.DEFAULT_PORT)
        self.assertNotEqual(data["key"], "short")

    def test_key_only_in_fragment(self):
        self.assertEqual(web_settings.link("192.168.1.5", 8780, KEY), f"http://192.168.1.5:8780/#k={KEY}")


class WebPanelServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = {"key": KEY, "control": False}
        self.patches = [mock.patch.object(display_api, "MetricsReader", FakeReader),
                        mock.patch.object(display_api, "system_volume_state", lambda: None),
                        mock.patch.object(player_access, "current_player", mock.AsyncMock(return_value=None)),
                        mock.patch.object(player_access, "control_player", mock.AsyncMock())]
        for patch in self.patches:
            patch.start()
        self.client = TestClient(TestServer(service.make_app(lambda: self.settings)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for patch in self.patches:
            patch.stop()

    async def test_page_is_served_with_strict_headers(self):
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn("PulseDeck", await response.text())
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual((await self.client.get("/../config.py")).status, 404)

    async def test_socket_needs_the_key(self):
        response = await self.client.get("/ws?k=wrong")
        self.assertEqual(response.status, 403)
        self.assertEqual((await self.client.get("/cover?key=x&k=wrong")).status, 403)

    async def test_hello_metrics_media(self):
        ws = await self.client.ws_connect(f"/ws?k={KEY}")
        kinds = {}
        for _ in range(3):
            msg = await ws.receive_json(timeout=5)
            kinds[msg["type"]] = msg
        self.assertEqual(set(kinds), {"hello", "metrics", "media"})
        self.assertFalse(kinds["hello"]["control"])
        self.assertIsNone(kinds["media"]["session"])
        await ws.close()

    async def test_view_only_refuses_commands(self):
        ws = await self.client.ws_connect(f"/ws?k={KEY}")
        await ws.send_json({"type": "command", "action": "toggle"})
        for _ in range(5):
            msg = await ws.receive_json(timeout=5)
            if msg["type"] == "error":
                break
        self.assertEqual(msg["code"], "view_only")
        player_access.control_player.assert_not_called()
        await ws.close()

    async def test_control_runs_only_playback(self):
        self.settings["control"] = True
        ws = await self.client.ws_connect(f"/ws?k={KEY}")
        with mock.patch("modules.monitor.workstation_locked", return_value=False):
            await ws.send_json({"type": "command", "action": "shutdown"})
            await ws.send_json({"type": "command", "action": "next"})
            errors = []
            for _ in range(6):
                msg = await ws.receive_json(timeout=5)
                if msg["type"] == "error":
                    errors.append(msg["code"])
                if player_access.control_player.await_count:
                    break
        self.assertIn("bad_command", errors)
        player_access.control_player.assert_awaited_with("next")
        await ws.close()

    async def test_internet_addresses_are_refused(self):
        with mock.patch("modules.local_api.is_private_ip", return_value=False):
            app = service.make_app(lambda: self.settings)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            self.assertEqual((await client.get("/")).status, 403)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
