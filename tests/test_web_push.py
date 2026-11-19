import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from modules import mobile_access
from pulse_pc.services.web_panel import push, service

SUB = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "B" * 87, "auth": "a" * 22}}


def metrics(cpu=10.0, free=50, battery=None):
    return {"cpu": {"load": cpu}, "gpu": {"load": 1.0, "memory_total": None, "memory_used": None},
            "ram": {"percent": 40.0}, "disks": [{"name": "C:", "total": 100, "free": free}], "battery": battery}


class PushLogicTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.patches = [mock.patch.object(mobile_access, "PATH", str(Path(self.dir) / "local_api.json")),
                        mock.patch("pulse_pc.services.web_panel.push.SecretStore")]
        for patch in self.patches:
            patch.start()
        secrets = {}
        store = push.SecretStore.return_value
        store.get.side_effect = secrets.get
        store.set.side_effect = secrets.__setitem__

    def tearDown(self):
        for patch in self.patches:
            patch.stop()

    def test_public_key_is_an_uncompressed_p256_point(self):
        raw = base64.urlsafe_b64decode(push.public_key(self.dir) + "==")
        self.assertEqual((len(raw), raw[0]), (65, 4))
        self.assertEqual(push.public_key(self.dir), push.public_key(self.dir))     # kept, not regenerated

    def test_limits_and_subscriptions_are_checked(self):
        self.assertEqual(push.clean_limits({"cpu": 70, "ram": "x", "disk": 0})["cpu"], 70)
        self.assertEqual(push.clean_limits({"ram": "x"})["ram"], 90)
        self.assertTrue(push.valid_subscription(SUB))
        self.assertFalse(push.valid_subscription({"endpoint": "http://evil", "keys": SUB["keys"]}))

    def test_revoked_browser_loses_its_subscription(self):
        mobile_access.add_device("Браузер (iPhone)", mobile_access.KIND_WEB, mobile_access.ACCESS_FULL, True)
        device = mobile_access.load()["devices"][0]["id"]
        push.subscribe(self.dir, device, SUB, {"cpu": 80})
        self.assertIn(device, push.subscribers(self.dir))
        mobile_access.remove_device(device)
        self.assertEqual(push.subscribers(self.dir), {})

    def test_monitor_once_per_crossing(self):
        monitor = push.Monitor(self.dir, "PC")
        subs = {"d1": {"subscription": SUB, "limits": push.clean_limits({"cpu": 80}), "alerts": True}}
        self.assertEqual(monitor.check(metrics(cpu=95), subs), [])            # first sample: not yet
        sent = monitor.check(metrics(cpu=95), subs)
        self.assertEqual([(d, tag) for d, _s, tag, _t in sent], [("d1", "cpu")])
        self.assertEqual(monitor.check(metrics(cpu=95), subs), [])            # still over: no repeat
        monitor.check(metrics(cpu=70), subs)                                  # back under the limit − 5
        monitor.check(metrics(cpu=95), subs)
        self.assertEqual(len(monitor.check(metrics(cpu=95), subs)), 1)        # armed again

    def test_disk_and_battery_under_their_limits(self):
        monitor = push.Monitor(self.dir, "PC")
        subs = {"d1": {"subscription": SUB, "limits": push.clean_limits({}), "alerts": True}}
        low = metrics(free=5, battery={"percent": 12, "plugged": False})
        monitor.check(low, subs)
        tags = {tag for _d, _s, tag, _t in monitor.check(low, subs)}
        self.assertEqual(tags, {"disk", "battery"})
        plugged = push.Monitor(self.dir, "PC")
        on_power = metrics(battery={"percent": 12, "plugged": True})
        plugged.check(on_power, subs)
        self.assertEqual(plugged.check(on_power, subs), [])                   # charging: no battery notice

    def test_gone_subscription_is_dropped(self):
        from pywebpush import WebPushException
        mobile_access.add_device("Браузер (iPhone)", mobile_access.KIND_WEB, mobile_access.ACCESS_FULL, True)
        device = mobile_access.load()["devices"][0]["id"]
        push.subscribe(self.dir, device, SUB, {})
        gone = WebPushException("gone", response=mock.Mock(status_code=410))
        with mock.patch("pywebpush.webpush", side_effect=gone):
            self.assertFalse(push.send(self.dir, device, SUB, "t", "b", "cpu"))
        self.assertEqual(push.subscribers(self.dir), {})


class PushRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.patches = [mock.patch.object(mobile_access, "PATH", str(Path(self.dir) / "local_api.json")),
                        mock.patch("pulse_pc.services.web_panel.push.SecretStore")]
        for patch in self.patches:
            patch.start()
        push.SecretStore.return_value.get.return_value = None
        self.token = mobile_access.add_device("Браузер (iPhone)", mobile_access.KIND_WEB, mobile_access.ACCESS_FULL, True)
        self.client = TestClient(TestServer(service.make_app(config_dir=self.dir)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for patch in self.patches:
            patch.stop()

    async def test_subscribe_needs_https_and_a_browser_token(self):
        body = {"t": self.token, "subscription": SUB, "limits": {"cpu": 80}}
        self.assertEqual((await self.client.post("/push/subscribe", json=body)).status, 403)       # plain HTTP
        with mock.patch.object(web.BaseRequest, "secure", new_callable=mock.PropertyMock, return_value=True):
            self.assertEqual((await self.client.post("/push/subscribe", json={**body, "t": "wrong"})).status, 403)
            self.assertEqual((await self.client.post("/push/subscribe", json={**body, "subscription": {}})).status, 400)
            self.assertEqual((await self.client.post("/push/subscribe", json=body)).status, 200)
        device = mobile_access.load()["devices"][0]["id"]
        self.assertEqual(push.subscribers(self.dir)[device]["limits"]["cpu"], 80)


if __name__ == "__main__":
    unittest.main()
