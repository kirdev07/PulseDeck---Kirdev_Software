"""PulseDeck Panel WebSocket (/api/v1/display) over the real TLS server."""
import asyncio
import json
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp  # noqa: E402

from modules import display_api, local_api, mobile_access  # noqa: E402
from tests.test_api_v1 import ServerThread  # noqa: E402


class WireFormatTests(unittest.TestCase):
    def test_metrics_never_invent_values(self):
        snap = SimpleNamespace(cpu=12.345, gpu=None, gpu_name="", ram=50.0, ram_used=8, ram_total=16,
                               disks=[SimpleNamespace(mount="C:", used=60, total=100)])
        message = display_api.metrics_message(snap, {"C:": "Windows"})
        self.assertEqual(message["cpu"], {"load": 12.3, "temp": None})
        self.assertEqual(message["gpu"], {"load": None, "temp": None, "name": None})
        self.assertEqual(message["disks"], [{"name": "C:", "label": "Windows", "total": 100, "free": 40}])

    def test_hardware_names_vram_and_network(self):
        snap = SimpleNamespace(cpu=5.0, gpu=7.0, gpu_name="RTX", ram=1.0, ram_used=1, ram_total=2, disks=[],
                               cpu_name="i5-13420H", cpu_cores=12, gpu_memory_total=6 << 30, gpu_memory_used=1 << 30,
                               net_down=2048.4, net_up=None)
        message = display_api.metrics_message(snap)
        self.assertEqual((message["cpu"]["name"], message["cpu"]["cores"]), ("i5-13420H", 12))
        self.assertEqual((message["gpu"]["memory_total"], message["gpu"]["memory_used"]), (6 << 30, 1 << 30))
        self.assertEqual(message["net"], {"down": 2048.0, "up": None})

    def test_source_names(self):
        self.assertEqual(display_api.source_name("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"), "Медиаплеер")
        self.assertEqual(display_api.source_name("Spotify.exe"), "Spotify")
        self.assertEqual(display_api.source_name("msedge"), "Microsoft Edge")
        self.assertEqual(display_api.source_name("Some.Vendor_x!Player"), "Player")

    def test_media_session_or_none(self):
        self.assertIsNone(display_api.media_message(None)["session"])
        self.assertIsNone(display_api.media_message({"status": "stopped", "title": "x"})["session"])
        self.assertIsNone(display_api.media_message({"status": "playing", "title": "  "})["session"])
        session = display_api.media_message({"status": "paused", "title": "After Dark", "artist": "Mr.Kitty",
                                             "position": 42.04, "duration": 208, "cover": "k1"})["session"]
        self.assertEqual((session["status"], session["position"], session["cover"]), ("paused", 42.0, "k1"))

    def test_position_change_alone_is_not_a_new_track(self):
        a = display_api.media_message({"status": "playing", "title": "A", "position": 1})
        b = display_api.media_message({"status": "playing", "title": "A", "position": 9})
        c = display_api.media_message({"status": "paused", "title": "A", "position": 9})
        self.assertTrue(display_api._same_track(a, b))
        self.assertFalse(display_api._same_track(b, c))


class DisplaySocketTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "local_api.json").write_text(json.dumps({"port": 0, "tls_port": 0, "enabled": True,
                                                        "allow_pairing": False, "devices": []}), encoding="utf-8")
        self.locked = False
        self.commands = []
        self.patches = [mock.patch.object(mobile_access, "PATH", str(root / "local_api.json")),
                        mock.patch("modules.monitor.workstation_locked", side_effect=lambda: self.locked),
                        mock.patch.object(local_api.now_playing, "AVAILABLE", False),
                        mock.patch.object(local_api.player_bridge, "send",
                                          side_effect=lambda cmd, value=None: self.commands.append(cmd)),
                        mock.patch.object(local_api.player_bridge, "snapshot", return_value={
                            "active": True, "title": "After Dark", "artist": "Mr.Kitty", "album": "", "status": "playing",
                            "position": 42.0, "duration": 208.0, "volume": 0.5, "cover": None, "cover_key": ""}),
                        mock.patch.object(display_api, "AUTH_RECHECK_SECONDS", 0.3),
                        mock.patch.object(local_api.DiscoveryProtocol, "datagram_received", lambda *a: None)]
        for patch in self.patches:
            patch.start()
        self.server = ServerThread(root)
        self.port = self.server.server.runner_v1.addresses[0][1]
        self.token = mobile_access.add_device("Panel")

    def tearDown(self):
        self.server.close()
        for patch in self.patches:
            patch.stop()
        self.dir.cleanup()

    def run_client(self, scenario, token=None):
        async def main():
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            headers = {"Authorization": f"Bearer {self.token if token is None else token}"}
            async with aiohttp.ClientSession() as session:
                return await scenario(session, f"wss://127.0.0.1:{self.port}/api/v1/display", headers, context)
        return asyncio.run(main())

    @staticmethod
    async def receive_until(ws, kind, limit=20):
        for _ in range(limit):
            message = await asyncio.wait_for(ws.receive_json(), 10)
            if message.get("type") == kind:
                return message
        raise AssertionError(f"no {kind}")

    def test_hello_metrics_media_and_commands(self):
        async def scenario(session, url, headers, ctx):
            async with session.ws_connect(url, headers=headers, ssl=ctx) as ws:
                hello = await self.receive_until(ws, "hello")
                metrics = await self.receive_until(ws, "metrics")
                media = await self.receive_until(ws, "media")
                await ws.send_json({"type": "command", "action": "next"})
                await ws.send_json({"type": "command", "action": "shutdown"})
                error = await self.receive_until(ws, "error")
                await ws.send_json({"type": "ping"})
                pong = await self.receive_until(ws, "pong")
                return hello, metrics, media, error, pong
        hello, metrics, media, error, _ = self.run_client(scenario)
        self.assertEqual((hello["protocol"], hello["commands"]), (1, ["next", "prev", "toggle"]))
        self.assertIsNotNone(metrics["cpu"]["load"])
        self.assertTrue(metrics["disks"])
        self.assertEqual(media["session"]["title"], "After Dark")
        self.assertEqual(error["code"], "bad_command")
        self.assertEqual(self.commands, ["next"])          # the unknown command ran nothing

    def test_no_token_no_socket(self):
        async def scenario(session, url, headers, ctx):
            async with session.ws_connect(url, headers=headers, ssl=ctx):
                pass
        with self.assertRaises(aiohttp.WSServerHandshakeError) as caught:
            self.run_client(scenario, token="wrong")
        self.assertEqual(caught.exception.status, 401)

    def test_revocation_closes_an_open_socket(self):
        async def scenario(session, url, headers, ctx):
            async with session.ws_connect(url, headers=headers, ssl=ctx) as ws:
                await self.receive_until(ws, "hello")
                device = mobile_access.load()["devices"][0]["id"]
                mobile_access.remove_device(device)
                for _ in range(40):
                    message = await asyncio.wait_for(ws.receive(), 10)
                    if message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                        return ws.close_code
                return None
        self.assertEqual(self.run_client(scenario), display_api.CLOSE_REVOKED)

    def test_locked_pc_shows_data_but_refuses_commands(self):
        self.locked = True

        async def scenario(session, url, headers, ctx):
            async with session.ws_connect(url, headers=headers, ssl=ctx) as ws:
                await self.receive_until(ws, "metrics")
                await ws.send_json({"type": "command", "action": "toggle"})
                return await self.receive_until(ws, "error")
        self.assertEqual(self.run_client(scenario)["code"], "locked")
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
