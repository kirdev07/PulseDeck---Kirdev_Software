"""Settings of the web panel: config/web_panel.json.

enabled   off by default — the panel is plain HTTP (phone browsers do not trust a home
          certificate), so the owner turns it on deliberately;
port      8780 unless changed: plain HTTP — the setup page, the home certificate, view only;
https     port + 1 (8781): the same panel over HTTPS once the phone trusts this PC's
          home certificate (web_panel/tls.py); only there music can be controlled.

Who may open it is decided per browser, like the apps: each browser pairs with the
6-digit code from «Телефон» and is listed there (view only or music control, revocable).
"""
import json
from pathlib import Path

DEFAULT_PORT = 8780
FILE = "web_panel.json"


def load(config_dir):
    path = Path(config_dir) / FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    port = data.get("port")
    port = port if isinstance(port, int) and 1024 <= port < 65535 else DEFAULT_PORT
    return {"enabled": bool(data.get("enabled", False)), "port": port}


def https_port(port):
    return port + 1


def save(config_dir, data):
    path = Path(config_dir) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def update(config_dir, **changes):
    data = load(config_dir)
    data.update(changes)
    save(data=data, config_dir=config_dir)
    return data


def address(host, port):
    """The panel's address for a browser that is already paired (HTTPS once trusted)."""
    return f"https://{host}:{https_port(port)}/"


def setup_address(host, port):
    """Plain HTTP page: pairing and the home certificate for a new phone."""
    return f"http://{host}:{port}/"


def pairing_link(host, port, code, view=""):
    """QR code for a new browser: the codes travel in the #fragment, not in the request. The
    page uses `pair` over HTTPS and `view` (view only) if it stays on plain HTTP."""
    return f"http://{host}:{port}/#pair={code}" + (f"&view={view}" if view else "")
