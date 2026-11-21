"""Web Push for the web panel: notifications on the phone even when the panel is closed.

How it works:
  * the PC has a VAPID key pair (P-256); the private key lives in the DPAPI secret store,
    like the bot token; the public key goes to the browser (GET /push/key);
  * a paired browser on HTTPS subscribes (pushManager) and sends its subscription and its
    limits to POST /push/subscribe; they are kept in config/web_push.json per device;
  * the PC watches its own metrics (Monitor) while somebody is subscribed and, when a value
    stays over that phone's limit, sends a push through the phone's push service (Apple or
    Google, over the internet) with pywebpush;
  * a revoked browser loses its subscription; an expired one (404/410) is dropped.

The PC needs internet access for this; without it the notices simply do not leave.
"""
import base64
import json
import logging
import threading
from pathlib import Path

from modules import mobile_access
from pulse_pc.core.secrets import SecretStore

logger = logging.getLogger("pulse_pc.services.web_panel.push")
FILE = "web_push.json"
KEY_SECRET = "WEB_PUSH_VAPID_PEM"
SUBJECT = "https://github.com/kirdev07/PulseDeck---Kirdev_Software"
CHECK_SECONDS = 5
OVER_SAMPLES = 2                 # ~10 s over the limit, as on the page
REARM_MARGIN = 5
LIMIT_KEYS = {"cpu": True, "gpu": True, "ram": True, "vram": True, "disk": False, "battery": False}   # True = over
DEFAULT_LIMITS = {"cpu": 90, "gpu": 90, "ram": 90, "vram": 95, "disk": 10, "battery": 20}
TITLES = {"cpu": "Процессор", "gpu": "Видеокарта", "ram": "Память", "vram": "Видеопамять"}
_lock = threading.Lock()


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def vapid(config_dir):
    """The PC's VAPID key (created once, kept encrypted)."""
    from py_vapid import Vapid02
    store = SecretStore(config_dir)
    pem = store.get(KEY_SECRET)
    if pem:
        try:
            return Vapid02.from_pem(pem.encode())
        except Exception:  # noqa: BLE001 - unreadable: make a new pair (old subscriptions stop working)
            logger.warning("Ключ Web Push не читается, создаю новый.")
    key = Vapid02()
    key.generate_keys()
    from cryptography.hazmat.primitives import serialization
    pem = key.private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()).decode()
    store.set(KEY_SECRET, pem)
    _save(config_dir, {})           # subscriptions made for the old key are worthless
    return key


def public_key(config_dir):
    """applicationServerKey for pushManager.subscribe: the uncompressed point, base64url."""
    from cryptography.hazmat.primitives import serialization
    raw = vapid(config_dir).public_key.public_bytes(serialization.Encoding.X962,
                                                    serialization.PublicFormat.UncompressedPoint)
    return _b64(raw)


def _path(config_dir):
    return Path(config_dir) / FILE


def _load(config_dir):
    try:
        data = json.loads(_path(config_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(config_dir, data):
    path = _path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def clean_limits(raw):
    limits = dict(DEFAULT_LIMITS)
    for key in DEFAULT_LIMITS:
        value = (raw or {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 1 <= value <= 100:
            limits[key] = int(value)
    return limits


# The push services of browsers (Safari/iOS, Chrome/Android, Firefox, Edge). The PC posts
# notices only there, never to an address a page made up (a LAN device, for example).
PUSH_SERVICES = ("web.push.apple.com", "fcm.googleapis.com", "android.googleapis.com",
                 "push.services.mozilla.com", "notify.windows.com")


def valid_subscription(sub):
    from urllib.parse import urlsplit
    keys = (sub or {}).get("keys") or {}
    endpoint = str((sub or {}).get("endpoint", ""))
    try:
        parts = urlsplit(endpoint)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    known = any(host == s or host.endswith("." + s) for s in PUSH_SERVICES)
    return parts.scheme == "https" and known and len(endpoint) < 1000 and \
        all(isinstance(keys.get(k), str) and 10 < len(keys[k]) < 200 for k in ("p256dh", "auth"))


def clean_disk(name):
    """«D:» chosen for the tile on the phone ('' = the first disk)."""
    return name if isinstance(name, str) and len(name) <= 10 else ""


def subscribe(config_dir, device_id, subscription, limits, alerts=True, disk=""):
    with _lock:
        data = _load(config_dir)
        data[device_id] = {"subscription": {"endpoint": subscription["endpoint"], "keys": {
            "p256dh": subscription["keys"]["p256dh"], "auth": subscription["keys"]["auth"]}},
            "limits": clean_limits(limits), "alerts": bool(alerts), "disk": clean_disk(disk)}
        _save(config_dir, data)


def update(config_dir, device_id, limits, alerts, disk=""):
    with _lock:
        data = _load(config_dir)
        if device_id in data:
            data[device_id]["limits"] = clean_limits(limits)
            data[device_id]["alerts"] = bool(alerts)
            data[device_id]["disk"] = clean_disk(disk)
            _save(config_dir, data)


def unsubscribe(config_dir, device_id):
    with _lock:
        data = _load(config_dir)
        if data.pop(device_id, None) is not None:
            _save(config_dir, data)


def subscribers(config_dir):
    """{device_id: record} of browsers that are still paired (revoked ones are dropped)."""
    with _lock:
        data = _load(config_dir)
        paired = {d.get("id"): d for d in mobile_access.load()["devices"] if mobile_access.kind_of(d) == mobile_access.KIND_WEB}
        alive = {k: v for k, v in data.items() if k in paired}
        if len(alive) != len(data):
            _save(config_dir, alive)
        for key, record in alive.items():
            record["name"] = paired[key].get("name", "")
        return alive


def send(config_dir, device_id, subscription, title, body, tag):
    """One push; False when the subscription is gone (it is removed)."""
    from pywebpush import WebPushException, webpush
    try:
        webpush(subscription, json.dumps({"title": title, "body": body, "tag": tag}, ensure_ascii=False),
                vapid_private_key=vapid(config_dir), vapid_claims={"sub": SUBJECT}, ttl=600, timeout=15)
        return True
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            logger.info("Подписка на уведомления устарела, удалена.")
            unsubscribe(config_dir, device_id)
            return False
        logger.warning("Web Push не отправлен: %s", exc)
    except Exception as exc:  # noqa: BLE001 - no internet, DNS, TLS: try next time
        logger.warning("Web Push не отправлен: %s", exc)
    return False


def values(m, disk_name=""):
    """The watched values from a display_api metrics message (the disk chosen on the phone, else the first)."""
    disks = m.get("disks") or []
    disk = next((d for d in disks if d.get("name") == disk_name), disks[0] if disks else None)
    gpu, battery = m.get("gpu") or {}, m.get("battery")
    total, used = gpu.get("memory_total"), gpu.get("memory_used")
    return {
        "cpu": (m.get("cpu") or {}).get("load"), "gpu": gpu.get("load"), "ram": (m.get("ram") or {}).get("percent"),
        "vram": 100 * used / total if total and used is not None else None,
        "disk": 100 * disk["free"] / disk["total"] if disk and disk.get("total") else None,
        "battery": battery["percent"] if battery and not battery.get("plugged") else None,
        "disk_name": disk["name"] if disk else "",
    }


class Monitor:
    """Watches the PC for subscribed phones and pushes a notice once per crossing."""

    def __init__(self, config_dir, pc_name):
        self.config_dir = config_dir
        self.pc_name = pc_name
        self.state = {}                 # (device_id, key) -> {"count", "active"}

    def check(self, metrics, subs):
        sent = []
        for key in [k for k in self.state if k[0] not in subs]:     # revoked / unsubscribed phones
            del self.state[key]
        for device_id, record in subs.items():
            if not record.get("alerts", True):
                continue
            found = values(metrics, record.get("disk", ""))
            for key, over in LIMIT_KEYS.items():
                value, limit = found.get(key), record["limits"].get(key, DEFAULT_LIMITS[key])
                st = self.state.setdefault((device_id, key), {"count": 0, "active": False})
                bad = value is not None and (value >= limit if over else value <= limit)
                fine = value is None or (value < limit - REARM_MARGIN if over else value > limit + REARM_MARGIN)
                st["count"] = st["count"] + 1 if bad else 0
                if not st["active"] and st["count"] >= OVER_SAMPLES:
                    st["active"] = True
                    sent.append((device_id, record["subscription"], key, self.text(key, value, limit, found)))
                elif st["active"] and fine:
                    st["active"] = False
        return sent

    @staticmethod
    def text(key, value, limit, found):
        if key in TITLES:
            return f"{TITLES[key]}: {round(value)}% (порог {limit}%)"
        if key == "disk":
            return f"Мало места: свободно {round(value)}% на {found.get('disk_name') or 'диске'}"
        return f"Батарея ПК: {round(value)}%, подключите зарядку"

    def title(self):
        return f"PulseDeck · {self.pc_name}"

