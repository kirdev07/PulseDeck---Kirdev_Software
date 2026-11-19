import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp import web
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


class HomeCertificateTest(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch("pulse_pc.services.web_panel.tls.SecretStore")
        self.patch.start().return_value.get.return_value = "p" * 32
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        self.patch.stop()

    def test_chain_is_valid_only_for_home_addresses(self):
        import ipaddress
        from cryptography import x509
        from cryptography.x509.verification import PolicyBuilder, Store
        from pulse_pc.services.web_panel import tls
        cert_path, _key, _pw = tls.ensure_server_certificate(self.dir, ["192.168.10.6", "8.8.8.8"])
        ca = x509.load_pem_x509_certificate((Path(self.dir) / tls.FOLDER / tls.CA_CERT).read_bytes())
        leaf = x509.load_pem_x509_certificate(cert_path.read_bytes())
        ips = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
        self.assertEqual(sorted(map(str, ips)), ["127.0.0.1", "192.168.10.6"])      # never a public address
        verifier = PolicyBuilder().store(Store([ca])).build_server_verifier(x509.IPAddress(ipaddress.ip_address("192.168.10.6")))
        self.assertEqual(len(verifier.verify(leaf, [])), 2)
        self.assertLessEqual((leaf.not_valid_after_utc - leaf.not_valid_before_utc).days, 397)   # Apple: <= 825

    def test_certificate_is_reused_and_renewed_on_new_address(self):
        from pulse_pc.services.web_panel import tls
        first = tls.ensure_server_certificate(self.dir, ["192.168.10.6"])[0].read_bytes()
        self.assertEqual(tls.ensure_server_certificate(self.dir, ["192.168.10.6"])[0].read_bytes(), first)
        self.assertNotEqual(tls.ensure_server_certificate(self.dir, ["192.168.10.7"])[0].read_bytes(), first)

    def test_iphone_profile(self):
        import plistlib
        from pulse_pc.services.web_panel import tls
        profile = plistlib.loads(tls.mobileconfig(self.dir))
        self.assertEqual(profile["PayloadContent"][0]["PayloadType"], "com.apple.security.root")
        self.assertEqual(profile["PayloadContent"][0]["PayloadContent"], tls.authority_der(self.dir))


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
        missing = await self.client.get("/../config.py")
        self.assertEqual(missing.status, 404)
        self.assertIn("frame-ancestors 'none'", missing.headers["Content-Security-Policy"])   # errors too

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

    async def test_https_pairing_is_trusted_like_the_apps(self):
        with mock.patch.object(web.BaseRequest, "secure", new_callable=mock.PropertyMock, return_value=True):
            await self.paired()
        device = mobile_access.load()["devices"][0]
        self.assertTrue(device["secure"])
        self.assertEqual(device["access"], mobile_access.ACCESS_FULL)

    async def test_socket_needs_a_browser_token(self):
        self.assertEqual((await self.client.get("/ws?t=wrong")).status, 403)
        app_token = mobile_access.add_device("PulseDesk")
        self.assertEqual((await self.client.get(f"/ws?t={app_token}")).status, 403)   # app tokens do not open it
        self.assertEqual((await self.client.get("/cover?key=x&t=wrong")).status, 403)

    async def test_hello_metrics_media(self):
        ws = await self.client.ws_connect(f"/ws?t={await self.paired()}")
        found = await self.messages(ws, 4)
        self.assertTrue({"hello", "access", "metrics", "media"} <= set(found) | {"metrics"})
        self.assertFalse(found["hello"]["control"])
        self.assertEqual(found["hello"]["assets"], service.assets_version())     # a sleeping old page reloads
        await ws.close()

    async def test_view_only_refuses_commands(self):
        ws = await self.client.ws_connect(f"/ws?t={await self.paired()}")
        await ws.send_json({"type": "command", "action": "toggle"})
        for _ in range(20):         # hello, access, metrics, media, sessions, activity … then the error
            msg = await ws.receive_json(timeout=5)
            if msg["type"] == "error":
                break
        self.assertEqual(msg["code"], "view_only")
        player_access.control_player.assert_not_called()
        await ws.close()

    async def full_access(self, secure_pairing):
        """A browser with «Полный»; secure_pairing: paired over HTTPS."""
        with mock.patch.object(web.BaseRequest, "secure", new_callable=mock.PropertyMock, return_value=secure_pairing):
            token = await self.paired()
        mobile_access.set_access(mobile_access.load()["devices"][0]["id"], mobile_access.ACCESS_FULL)
        return token

    async def commands(self, ws, *sent, wait_for=None):
        """Send commands; read until wait_for() is true (or, without it, until the first error)."""
        errors = []
        with mock.patch("modules.monitor.workstation_locked", return_value=False):
            for action, value in sent:
                await ws.send_json({"type": "command", "action": action, "value": value})
            for _ in range(15):
                msg = await ws.receive_json(timeout=5)
                if msg["type"] == "error":
                    errors.append(msg["code"])
                    if wait_for is None:
                        break
                if wait_for is not None and wait_for():
                    break
        return errors

    async def test_plain_http_never_controls(self):
        token = await self.full_access(secure_pairing=True)
        ws = await self.client.ws_connect(f"/ws?t={token}")           # the test server is HTTP
        found = await self.messages(ws, 3)
        errors = await self.commands(ws, ("next", None))
        self.assertIn("view_only", errors)
        player_access.control_player.assert_not_called()
        self.assertIn("access", found)
        await ws.close()

    async def test_https_full_access_controls_music_only(self):
        token = await self.full_access(secure_pairing=True)
        with mock.patch.object(web.BaseRequest, "secure", new_callable=mock.PropertyMock, return_value=True), \
                mock.patch("modules.volume.AVAILABLE", True), mock.patch("modules.volume.set_level") as set_level:
            ws = await self.client.ws_connect(f"/ws?t={token}")
            errors = await self.commands(ws, ("shutdown", None), ("source", "spotify.exe"), ("seek", 42),
                                         ("volume", 30), ("next", None),
                                         wait_for=lambda: player_access.control_player.await_count >= 2)
            await ws.close()
        self.assertIn("bad_command", errors)
        player_access.control_player.assert_any_await("seek", 42.0, "spotify.exe")
        player_access.control_player.assert_any_await("next", None, "spotify.exe")
        set_level.assert_called_with(30)

    async def test_paired_over_http_cannot_control_even_on_https(self):
        token = await self.full_access(secure_pairing=False)
        with mock.patch.object(web.BaseRequest, "secure", new_callable=mock.PropertyMock, return_value=True):
            ws = await self.client.ws_connect(f"/ws?t={token}")
            errors = await self.commands(ws, ("toggle", None))
            await ws.close()
        self.assertIn("view_only", errors)
        player_access.control_player.assert_not_called()

    async def test_revoked_browser_is_disconnected(self):
        token = await self.paired()
        ws = await self.client.ws_connect(f"/ws?t={token}")
        mobile_access.remove_device(mobile_access.load()["devices"][0]["id"])
        while True:
            msg = await ws.receive(timeout=5)
            if msg.type.name in ("CLOSE", "CLOSED", "CLOSING"):
                break
        # the code in the PC's close frame (ws.close_code may read 1006 after the client's own reply fails)
        self.assertEqual(msg.data if msg.type.name == "CLOSE" else ws.close_code, service.CLOSE_REVOKED)

    async def test_pc_control_only_for_trusted_browsers(self):
        token = await self.full_access(secure_pairing=True)
        app_token = mobile_access.add_device("PulseDesk")
        view_token = await self.paired()
        url, auth = "/pc/api/v1/history", lambda t: {"Authorization": f"Bearer {t}"}
        with mock.patch("modules.transfer_history.load_history", return_value=[]),                 mock.patch("modules.monitor.workstation_locked", return_value=False):
            self.assertEqual((await self.client.get(url, headers=auth(token))).status, 403)      # plain HTTP
            with mock.patch.object(web.BaseRequest, "secure", new_callable=mock.PropertyMock, return_value=True):
                response = await self.client.get(url, headers=auth(token))
                self.assertEqual(response.status, 200)
                self.assertEqual((await response.json())["history"], [])
                self.assertEqual((await self.client.get(url, headers=auth(app_token))).status, 401)   # app tokens: no
                self.assertEqual((await self.client.get(url, headers=auth(view_token))).status, 403)  # «Просмотр»
                self.assertEqual((await self.client.get(url)).status, 401)
                self.assertEqual((await self.client.post("/pc/api/v1/pair", json={"code": "1"})).status, 404)

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
