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
        # legacy_http: API v0 without encryption (only the old Pulse Mobile app needs it). Off by
        # default; settings saved before 1.0.3 had it on and are switched off once (it can be
        # turned on again in Настройки → Телефон).
        for key, default in (("enabled", True), ("allow_pairing", True), ("legacy_http", False)):
            if type(data.get(key)) is not bool:
                data[key], changed = default, True
        if not data.get("legacy_off_once"):
            data["legacy_http"], data["legacy_off_once"], changed = False, True, True
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


# Kinds of paired devices. A token works only for its own kind: a browser token travels over
# plain HTTP (web panel), so it must never open the TLS API of the apps.
KIND_APP = "app"          # PulseDesk / PulseDeck Panel (API v1 over TLS); devices without "kind"
KIND_WEB = "web"          # a phone browser with the web panel


def add_device(name, kind=KIND_APP, access=None, secure=None, legacy=False):
    """Register a phone and return its token (shown only once). secure: a browser paired
    over HTTPS (its token never crossed the network unencrypted) — only those may control.
    legacy: an app paired over the old HTTP protocol (v0) — its token crossed the network
    unencrypted, so the TLS API (v1) does not accept it."""
    with LOCK:
        data = load()
        if len(data["devices"]) >= MAX_DEVICES:
            raise ValueError("Слишком много устройств. Отзовите ненужные в окне PulseDeck.")
        token = secrets.token_urlsafe(24)
        device = {"id": secrets.token_hex(6), "name": name[:40] or "Телефон", "hash": _hash(token),
                  "added": datetime.now().isoformat(timespec="seconds"), "last_seen": ""}
        if kind != KIND_APP:
            device["kind"] = kind
        if access is not None:
            device["access"] = access
        if secure is not None:
            device["secure"] = bool(secure)
        if legacy:
            device["legacy"] = True
        data["devices"].append(device)
        save(data)
        return token


def kind_of(device):
    return (device or {}).get("kind", KIND_APP)


ACCESS_FULL = "full"      # everything the API offers (default; devices paired before this setting)
ACCESS_VIEW = "view"      # monitoring and now playing only: no commands, no files, no screenshots


def can_control(device):
    return (device or {}).get("access", ACCESS_FULL) == ACCESS_FULL


def set_access(device_id, access):
    if access not in (ACCESS_FULL, ACCESS_VIEW):
        raise ValueError("Неизвестный уровень доступа.")
    with LOCK:
        data = load()
        for device in data["devices"]:
            if device.get("id") == device_id:
                device["access"] = access
        save(data)


def remove_device(device_id):
    with LOCK:
        data = load()
        data["devices"] = [d for d in data["devices"] if d.get("id") != device_id]
        save(data)


class PairingCodes:
    """One-time 6-digit codes for API v1 pairing. The owner starts a code on the PC; the
    phone must send it within PAIR_CODE_SECONDS, with at most PAIR_CODE_ATTEMPTS tries.

    Two codes are shown together: the main one (apps over TLS, browsers over HTTPS — full
    trust) and a «view only» one for a browser on plain HTTP. Each is good only on its own
    channel, so a code seen on the unencrypted page can never be redeemed for full access.
    The main code typed on the plain page is burnt (it was exposed). Either code, used once,
    ends both."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._code = None
        self._view = None
        self._expires = 0.0
        self._attempts = 0

    def start(self):
        with self._lock:
            self._code = f"{secrets.randbelow(1_000_000):06d}"
            self._view = self._code
            while self._view == self._code:
                self._view = f"{secrets.randbelow(1_000_000):06d}"
            self._expires = self.clock() + PAIR_CODE_SECONDS
            self._attempts = 0
            return self._code

    def cancel(self):
        with self._lock:
            self._code = self._view = None

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

    def current_view(self):
        """The «view only» code for a browser on plain HTTP, '' when none is active."""
        return (self._view or "") if self.active() else ""

    def verify(self, code, plain=False):
        """True once for the right code of this channel (plain: the unencrypted HTTP page);
        wrong guesses burn attempts, then the codes die."""
        return self.check(code, plain) == "ok"

    def check(self, code, plain=False):
        """'ok', 'wrong', or 'exposed' (the main code sent over plain HTTP: now dead)."""
        if not self.active():
            return "wrong"
        given = str(code or "").replace(" ", "").strip().encode()
        with self._lock:
            if hmac.compare_digest(given, (self._view if plain else self._code).encode()):
                self._code = self._view = None
                return "ok"
            if plain and hmac.compare_digest(given, self._code.encode()):
                self._code = self._view = None
                return "exposed"
            self._attempts += 1
            if self._attempts >= PAIR_CODE_ATTEMPTS:
                self._code = self._view = None
            return "wrong"


PAIRING = PairingCodes()


def authenticate(token, kind=KIND_APP):
    """Return the device record for a valid token of this kind, else None."""
    if not token:
        return None
    digest = _hash(token)
    with LOCK:
        devices = load()["devices"]
    found = None
    for device in devices:
        if hmac.compare_digest(str(device.get("hash", "")), digest) and kind_of(device) == kind:
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
