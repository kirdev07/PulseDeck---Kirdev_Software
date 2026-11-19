"""Settings of the web panel: config/web_panel.json.

enabled   off by default — the panel is plain HTTP (phone browsers do not trust a home
          certificate), so the owner turns it on deliberately;
port      8780 unless changed;
key       random access key; it travels in the link's #fragment (never sent to the
          server in the URL, not written to logs) and then in the WebSocket request;
          a new key makes every old link stop working;
control   off = view only; on = play/pause/next/previous from the browser.
"""
import json
import secrets
from pathlib import Path

DEFAULT_PORT = 8780
FILE = "web_panel.json"


def new_key():
    return secrets.token_urlsafe(18)


def load(config_dir):
    path = Path(config_dir) / FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    port = data.get("port")
    result = {
        "enabled": bool(data.get("enabled", False)),
        "port": port if isinstance(port, int) and 1024 <= port <= 65535 else DEFAULT_PORT,
        "key": data.get("key") if isinstance(data.get("key"), str) and len(data["key"]) >= 16 else "",
        "control": bool(data.get("control", False)),
    }
    if not result["key"]:
        result["key"] = new_key()
        save(config_dir, result)
    return result


def save(config_dir, data):
    path = Path(config_dir) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def update(config_dir, **changes):
    data = load(config_dir)
    data.update(changes)
    save(config_dir, data)
    return data


def link(address, port, key):
    return f"http://{address}:{port}/#k={key}"
