import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase
from modules.local_api import make_app


class LocalApiSecurityTests(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    async def test_public_ping_does_not_reveal_computer_name(self):
        response = await self.client.request("GET", "/api/ping")
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["app"], "PulsePC")
        self.assertNotIn("name", data)

    async def test_protected_endpoint_requires_device_token(self):
        response = await self.client.request("GET", "/api/status")
        self.assertEqual(response.status, 401)
        data = await response.json()
        self.assertFalse(data["ok"])

    async def test_invalid_bearer_token_is_rejected(self):
        response = await self.client.request("GET", "/api/status", headers={"Authorization": "Bearer invalid-token"})
        self.assertEqual(response.status, 401)

    async def test_pairing_attempts_are_rate_limited(self):
        with patch("modules.local_api.mobile_access.load", return_value={"allow_pairing": True}), \
             patch("modules.local_api.is_private_ip", return_value=True), \
             patch("modules.local_api.ask_owner", return_value=False):
            statuses = []
            for _ in range(4):
                response = await self.client.request("POST", "/api/pair", json={"device": "Test"})
                statuses.append(response.status)
            self.assertEqual(statuses, [403, 403, 403, 429])

    async def test_unexpected_exception_does_not_leak_details(self):
        with patch("modules.local_api.mobile_access.authenticate", return_value={"id": "test"}), \
             patch("modules.monitor.workstation_locked", return_value=False), \
             patch("modules.local_api.load_programs", side_effect=RuntimeError("secret-path-C:/private")):
            response = await self.client.request("GET", "/api/programs", headers={"Authorization": "Bearer test"})
            self.assertEqual(response.status, 500)
            data = await response.json()
            self.assertNotIn("secret-path", data["error"])
            self.assertIn("Внутренняя ошибка", data["error"])


class LanOnlyTests(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    async def request_from(self, remote, path="/api/status", **kwargs):
        from aiohttp.test_utils import make_mocked_request  # noqa: F401 - documents intent
        with patch("aiohttp.web_request.BaseRequest.remote", new=remote):
            return await self.client.request("GET", path, **kwargs)

    async def test_public_address_is_refused_even_with_a_valid_token(self):
        with patch("modules.local_api.mobile_access.authenticate", return_value={"id": "test"}), \
             patch("modules.monitor.workstation_locked", return_value=False):
            response = await self.request_from("93.184.216.34", headers={"Authorization": "Bearer test"})
            self.assertEqual(response.status, 403)
            ping = await self.request_from("8.8.8.8", "/api/ping")
            self.assertEqual(ping.status, 403)

    async def test_lan_addresses_pass_the_network_check(self):
        for address in ("192.168.1.20", "10.0.0.5", "127.0.0.1", "::1", "::ffff:192.168.1.20", "fe80::1%12"):
            response = await self.request_from(address, "/api/ping")
            self.assertEqual(response.status, 200, address)


class PrivateAddressTests(unittest.TestCase):
    def test_classification(self):
        from modules.local_api import is_private_ip
        for address in ("192.168.0.1", "172.16.5.4", "10.1.2.3", "127.0.0.1", "169.254.1.1", "::1", "fd00::1",
                        "::ffff:10.0.0.1"):
            self.assertTrue(is_private_ip(address), address)
        for address in ("8.8.8.8", "93.184.216.34", "::ffff:8.8.8.8", "2001:4860::8888", "", None, "nonsense"):
            self.assertFalse(is_private_ip(address), address)


if __name__ == "__main__":
    unittest.main()
