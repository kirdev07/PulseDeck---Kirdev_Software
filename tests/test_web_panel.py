import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from modules import display_api, mobile_access, player_access
from pulse_pc.services.web_panel import service, settings as web_settings


class FakeReader:
    async def read(self):
        return {"type": "metrics", "cpu": {"load": 12.0}}

    def close(self):
        pass


class WebPanelSettingsTest(unittest.TestCase):
    def test_defaults_off(self):
        data = web_settings.load(tempfile.mkdtemp())
        self.assertEqual(data, {"enabled": False, "port": web_settings.DEFAULT_PORT})

    def test_bad_port_falls_back(self):
        folder = tempfile.mkdtemp()
        web_settings.save(folder, {"enabled": True, "port": 80})
        self.assertEqual(web_settings.load(folder)["port"], web_settings.DEFAULT_PORT)

    def test_code_only_in_fragment(self):
        self.assertEqual(web_settings.pairing_link("192.168.1.5", 8780, "123456"), "http://192.168.1.5:8780/#pair=123456")


class DeviceKindsTest(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(mobile_access, "PATH", str(Path(tempfile.mkdtemp()) / "local_api.json"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_tokens_work_only_for_their_kind(self):
        app = mobile_access.add_device("PulseDesk")
        web = mobile_access.add_device("Браузер (iPhone)", mobile_access.KIND_WEB, mobile_access.ACCESS_VIEW)
        self.assertIsNotNone(mobile_access.authenticate(app))
        self.assertIsNone(mobile_access.authenticate(web))                     # never the TLS API of the apps
        self.assertIsNotNone(mobile_access.authenticate(web, mobile_access.KIND_WEB))
        self.assertIsNone(mobile_access.authenticate(app, mobile_access.KIND_WEB))
        self.assertFalse(mobile_access.can_control(mobile_access.authenticate(web, mobile_access.KIND_WEB)))


class WebPanelServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [mock.patch.object(mobile_access, "PATH", str(Path(tempfile.mkdtemp()) / "local_api.json")),
                        mock.patch.object(display_api, "MetricsReader", FakeReader),
                        mock.patch.object(display_api, "system_volume_state", lambda: None),
                        mock.patch.object(player_access, "current_player", mock.AsyncMock(return_value=None)),
                        mock.patch.object(player_access, "control_player", mock.AsyncMock()),
                        mock.patch.object(service, "AUTH_RECHECK_SECONDS", 0.2)]
        for patch in self.patches:
            patch.start()
        self.pairing = mobile_access.PairingCodes()
        self.client = TestClient(TestServer(service.make_app(pairing=self.pairing)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for patch in self.patches:
            patch.stop()

    async def paired(self):
        code = self.pairing.start()
        response = await self.client.post("/pair", json={"code": code, "name": "Браузер (iPhone)"})
        self.assertEqual(response.status, 200)
        return (await response.json())["token"]

    async def messages(self, ws, count):
        found = {}
        for _ in range(count):
            msg = await ws.receive_json(timeout=5)
            found.setdefault(msg["type"], msg)
        return found

    async def test_page_is_served_with_strict_headers(self):
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn("PulseDeck", await response.text())
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual((await self.client.get("/../config.py")).status, 404)

    async def test_pairing_needs_the_code_shown_on_the_pc(self):
        response = await self.client.post("/pair", json={"code": "123456"})
        self.assertEqual(response.status, 403)          # no code started on the PC
        self.pairing.start()
        self.assertEqual((await self.client.post("/pair", json={"code": "000000"})).status, 403)

    async def test_paired_browser_is_listed_view_only(self):
        await self.paired()
        devices = mobile_access.load()["devices"]
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["name"], "Браузер (iPhone)")
        self.assertEqual(mobile_access.kind_of(devices[0]), mobile_access.KIND_WEB)
        self.assertEqual(devices[0]["access"], mobile_access.ACCESS_VIEW)

    async def test_socket_needs_a_browser_token(self):
        self.assertEqual((await self.client.get("/ws?t=wrong")).status, 403)
        app_token = mobile_access.add_device("PulseDesk")
        self.assertEqual((await self.client.get(f"/ws?t={app_token}")).status, 403)   # app tokens do not open it
        self.assertEqual((await self.client.get("/cover?key=x&t=wrong")).status, 403)

    async def test_hello_metrics_media(self):
        ws = await self.client.ws_connect(f"/ws?t={await self.paired()}")
        found = await self.messages(ws, 3)
        self.assertEqual(set(found), {"hello", "metrics", "media"})
        self.assertFalse(found["hello"]["control"])
        await ws.close()

    async def test_view_only_refuses_commands(self):
        ws = await self.client.ws_connect(f"/ws?t={await self.paired()}")
        await ws.send_json({"type": "command", "action": "toggle"})
        for _ in range(6):
            msg = await ws.receive_json(timeout=5)
            if msg["type"] == "error":
                break
        self.assertEqual(msg["code"], "view_only")
        player_access.control_player.assert_not_called()
        await ws.close()

    async def test_full_access_runs_only_playback(self):
        token = await self.paired()
        mobile_access.set_access(mobile_access.load()["devices"][0]["id"], mobile_access.ACCESS_FULL)
        ws = await self.client.ws_connect(f"/ws?t={token}")
        with mock.patch("modules.monitor.workstation_locked", return_value=False):
            await ws.send_json({"type": "command", "action": "shutdown"})
            await ws.send_json({"type": "command", "action": "next"})
            errors = []
            for _ in range(8):
                msg = await ws.receive_json(timeout=5)
                if msg["type"] == "error":
                    errors.append(msg["code"])
                if player_access.control_player.await_count:
                    break
        self.assertIn("bad_command", errors)
        player_access.control_player.assert_awaited_with("next")
        await ws.close()

    async def test_revoked_browser_is_disconnected(self):
        token = await self.paired()
        ws = await self.client.ws_connect(f"/ws?t={token}")
        mobile_access.remove_device(mobile_access.load()["devices"][0]["id"])
        while True:
            msg = await ws.receive(timeout=5)
            if msg.type.name in ("CLOSE", "CLOSED", "CLOSING"):
                break
        self.assertEqual(ws.close_code, service.CLOSE_REVOKED)

    async def test_internet_addresses_are_refused(self):
        with mock.patch("modules.local_api.is_private_ip", return_value=False):
            app = service.make_app(pairing=self.pairing)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            self.assertEqual((await client.get("/")).status, 403)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
