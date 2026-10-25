"""Stage E: API v1 — TLS with a pinned self-signed certificate and code pairing.
API v0 (HTTP) keeps working unchanged next to it."""
import asyncio
import hashlib
import json
import os
import socket
import ssl
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import local_api, mobile_access  # noqa: E402
from pulse_pc.services.local_api import tls  # noqa: E402


class PairingCodeTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.codes = mobile_access.PairingCodes(clock=lambda: self.now[0])

    def test_code_is_single_use(self):
        code = self.codes.start()
        self.assertRegex(code, r"^\d{6}$")
        self.assertTrue(self.codes.verify(code))
        self.assertFalse(self.codes.verify(code))

    def test_code_expires(self):
        code = self.codes.start()
        self.now[0] += mobile_access.PAIR_CODE_SECONDS + 1
        self.assertFalse(self.codes.active())
        self.assertFalse(self.codes.verify(code))

    def test_wrong_guesses_burn_the_code(self):
        code = self.codes.start()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(mobile_access.PAIR_CODE_ATTEMPTS):
            self.assertFalse(self.codes.verify(wrong))
        self.assertFalse(self.codes.verify(code))   # even the right code is dead now

    def test_no_code_no_pairing(self):
        self.assertFalse(self.codes.verify(""))
        self.assertFalse(self.codes.verify(None))


class CertificateTests(unittest.TestCase):
    def test_certificate_is_created_once_and_key_is_encrypted(self):
        with tempfile.TemporaryDirectory() as folder:
            first = tls.ensure_certificate(folder)
            fingerprint = tls.fingerprint(folder)
            self.assertEqual(tls.ensure_certificate(folder)[0], first[0])
            self.assertEqual(tls.fingerprint(folder), fingerprint)
            self.assertIn(b"ENCRYPTED", first[1].read_bytes())
            self.assertEqual(len(fingerprint.split(":")), 32)
            self.assertEqual(len(tls.short_fingerprint(fingerprint).split()), 4)
            tls.server_context(folder)   # loads with the DPAPI-stored password


class ServerThread:
    """Runs LocalApiServer (v0 + v1) on its own loop with free ports."""

    def __init__(self, config_dir):
        self.loop = asyncio.new_event_loop()
        self.server = local_api.LocalApiServer(lambda _: None, tls_context=lambda: tls.server_context(config_dir))
        ready = threading.Event()

        def run():
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.server.start())
            ready.set()
            self.loop.run_forever()
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        ready.wait(15)

    def close(self):
        asyncio.run_coroutine_threadsafe(self.server.close(), self.loop).result(10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


class ApiV1Tests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        (self.root / "local_api.json").write_text(json.dumps({"port": 0, "tls_port": 0, "enabled": True,
                                                             "allow_pairing": False, "devices": []}), encoding="utf-8")
        self.patches = [mock.patch.object(mobile_access, "PATH", str(self.root / "local_api.json")),
                        mock.patch.object(mobile_access, "PAIRING", mobile_access.PairingCodes()),
                        mock.patch("modules.monitor.workstation_locked", return_value=False),
                        mock.patch.object(local_api.DiscoveryProtocol, "datagram_received", lambda *a: None)]
        for patch in self.patches:
            patch.start()
        self.server = ServerThread(self.root)
        self.http_port = self.server.server.runner.addresses[0][1]
        self.tls_port = self.server.server.runner_v1.addresses[0][1]
        self.pinned = tls.fingerprint(self.root)

    def tearDown(self):
        self.server.close()
        for patch in self.patches:
            patch.stop()
        self.dir.cleanup()

    def call(self, path, body=None, token="", method=None):
        """HTTPS request that trusts exactly the pinned certificate, as the phone will."""
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE     # self-signed: verified by fingerprint below
        request = urllib.request.Request(f"https://127.0.0.1:{self.tls_port}{path}", method=method,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type": "application/json",
                                                  **({"Authorization": f"Bearer {token}"} if token else {})})
        with socket.create_connection(("127.0.0.1", self.tls_port), timeout=5) as raw:
            with context.wrap_socket(raw) as wrapped:
                seen = hashlib.sha256(wrapped.getpeercert(binary_form=True)).hexdigest().upper()
        self.assertEqual(":".join(seen[i:i + 2] for i in range(0, 64, 2)), self.pinned)
        try:
            with urllib.request.urlopen(request, context=context, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                return error.code, json.loads(body)
            except ValueError:      # aiohttp's own 404/405 pages are plain text
                return error.code, body.decode("utf-8", "replace")

    def test_info_and_code_pairing_then_authorized_requests(self):
        status, info = self.call("/api/v1/info")
        self.assertEqual((status, info["api"], info["pairing"]), (200, 1, False))
        self.assertEqual(self.call("/api/v1/pair", {"device": "Pixel", "code": "123456"})[0], 403)
        code = mobile_access.PAIRING.start()
        self.assertTrue(self.call("/api/v1/info")[1]["pairing"])
        status, paired = self.call("/api/v1/pair", {"device": "Pixel", "code": code})
        self.assertEqual(status, 200)
        token = paired["token"]
        self.assertEqual(self.call("/api/v1/programs")[0], 401)
        status, programs = self.call("/api/v1/programs", token=token)
        self.assertEqual(status, 200)
        self.assertIn("programs", programs)
        device_id = mobile_access.load()["devices"][0]["id"]
        mobile_access.remove_device(device_id)          # revocation applies to v1 as well
        self.assertEqual(self.call("/api/v1/programs", token=token)[0], 401)

    def test_v1_has_no_dialog_pairing_and_no_plain_http(self):
        self.assertEqual(self.call("/api/v1/ping")[0], 404)
        with self.assertRaises(Exception):   # HTTP on the TLS port is not accepted
            urllib.request.urlopen(f"http://127.0.0.1:{self.tls_port}/api/v1/info", timeout=5)

    def test_v0_is_unchanged(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.http_port}/api/ping", timeout=5) as response:
            self.assertEqual(json.loads(response.read()), {"ok": True, "app": "PulsePC"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"http://127.0.0.1:{self.http_port}/api/status", timeout=5)
        self.assertEqual(caught.exception.code, 401)

    def test_token_from_v0_pairing_works_on_v1(self):
        token = mobile_access.add_device("Old phone")
        self.assertEqual(self.call("/api/v1/programs", token=token)[0], 200)


class DiscoveryTests(unittest.TestCase):
    def test_reply_keeps_v0_fields_and_adds_tls(self):
        sent = []
        protocol = local_api.DiscoveryProtocol(8765, 8767)
        protocol.connection_made(mock.Mock(sendto=lambda data, addr: sent.append(json.loads(data))))
        protocol.datagram_received(b"PULSEPC?", ("192.168.1.9", 5000))
        self.assertEqual(sent[0]["port"], 8765)
        self.assertEqual((sent[0]["tls_port"], sent[0]["api"]), (8767, [0, 1]))
        legacy = local_api.DiscoveryProtocol(8765)
        legacy.connection_made(mock.Mock(sendto=lambda data, addr: sent.append(json.loads(data))))
        legacy.datagram_received(b"PULSEPC?", ("192.168.1.9", 5000))
        self.assertNotIn("tls_port", sent[1])


if __name__ == "__main__":
    unittest.main()
