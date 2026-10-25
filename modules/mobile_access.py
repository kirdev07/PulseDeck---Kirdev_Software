"""Paired phones and settings of the mobile access server (config/local_api.json).

Shared by the LAN API (bot thread) and the desktop window, so every change goes
through one lock. Phone tokens are stored only as SHA-256 hashes.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime

import config
from modules.bot_preferences import atomic_json

PATH = os.path.join(config.CONFIG_DIR, "local_api.json")
DEFAULT_PORT = 8765
DISCOVERY_PORT = 8766
DEFAULT_TLS_PORT = 8767     # API v1 over TLS
PAIR_CODE_SECONDS = 120
PAIR_CODE_ATTEMPTS = 5
MAX_DEVICES = 10
LOCK = threading.RLock()
# Filled in by the running server; read by the window.
STATE = {"running": False, "port": DEFAULT_PORT, "addresses": []}
_last_touch = {}


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def load():
    with LOCK:
        try:
            with open(PATH, encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        changed = data.pop("token", None) is not None  # old shared token is retired
        if not isinstance(data.get("port"), int):
            data["port"], changed = DEFAULT_PORT, True
        if not isinstance(data.get("tls_port"), int):
            data["tls_port"], changed = DEFAULT_TLS_PORT, True
        # legacy_http: API v0 without encryption, kept until every phone runs a v1 client.
        for key, default in (("enabled", True), ("allow_pairing", True), ("legacy_http", True)):
            if type(data.get(key)) is not bool:
                data[key], changed = default, True
        devices = data.get("devices")
        if not isinstance(devices, list):
            data["devices"], changed = [], True
        if changed:
            atomic_json(PATH, data)
        return data


def save(data):
    with LOCK:
        atomic_json(PATH, data)


def set_option(key, value):
    with LOCK:
        data = load()
        data[key] = value
        save(data)


def add_device(name):
    """Register a phone and return its token (shown only once)."""
    with LOCK:
        data = load()
        if len(data["devices"]) >= MAX_DEVICES:
            raise ValueError("Слишком много устройств. Отзовите ненужные в окне Pulse PC.")
        token = secrets.token_urlsafe(24)
        data["devices"].append({
            "id": secrets.token_hex(6), "name": name[:40] or "Телефон", "hash": _hash(token),
            "added": datetime.now().isoformat(timespec="seconds"), "last_seen": ""})
        save(data)
        return token


def remove_device(device_id):
    with LOCK:
        data = load()
        data["devices"] = [d for d in data["devices"] if d.get("id") != device_id]
        save(data)


class PairingCodes:
    """One-time 6-digit codes for API v1 pairing. The owner starts a code on the PC; the
    phone must send it within PAIR_CODE_SECONDS, with at most PAIR_CODE_ATTEMPTS tries."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._code = None
        self._expires = 0.0
        self._attempts = 0

    def start(self):
        with self._lock:
            self._code = f"{secrets.randbelow(1_000_000):06d}"
            self._expires = self.clock() + PAIR_CODE_SECONDS
            self._attempts = 0
            return self._code

    def cancel(self):
        with self._lock:
            self._code = None

    def remaining(self):
        with self._lock:
            if not self._code:
                return 0
            left = self._expires - self.clock()
            if left <= 0:
                self._code = None
                return 0
            return int(left + 0.999)

    def active(self):
        return self.remaining() > 0

    def current(self):
        """The code to show on the PC screen, '' when none is active."""
        return (self._code or "") if self.active() else ""

    def verify(self, code):
        """True once for the right code; wrong guesses burn attempts, then the code dies."""
        if not self.active():
            return False
        with self._lock:
            ok = hmac.compare_digest(str(code or "").strip().encode(), self._code.encode())
            if ok:
                self._code = None
                return True
            self._attempts += 1
            if self._attempts >= PAIR_CODE_ATTEMPTS:
                self._code = None
            return False


PAIRING = PairingCodes()


def authenticate(token):
    """Return the device record for a valid token, else None."""
    if not token:
        return None
    digest = _hash(token)
    with LOCK:
        devices = load()["devices"]
    found = None
    for device in devices:
        if hmac.compare_digest(str(device.get("hash", "")), digest):
            found = device
    if found:
        now = time.monotonic()
        if now - _last_touch.get(found["id"], -999) > 60:
            _last_touch[found["id"]] = now
            with LOCK:
                data = load()
                for device in data["devices"]:
                    if device.get("id") == found["id"]:
                        device["last_seen"] = datetime.now().isoformat(timespec="seconds")
                save(data)
    return found
