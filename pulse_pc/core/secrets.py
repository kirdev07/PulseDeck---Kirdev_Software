"""Secrets encrypted with Windows DPAPI for the current Windows user (config/secrets.bin).

A copied file cannot be decrypted on another PC or by another Windows account. The bot
token moves here from config/.env; .env keeps a placeholder so older readers see «not
set» instead of a stale value. config.py falls back to this store when .env has none.
"""
import base64
import json
import os
import threading
import uuid
from pathlib import Path

FILE_NAME = "secrets.bin"
PLACEHOLDER_TOKEN = "your_telegram_bot_token_here"
_ENTROPY = b"Pulse-PC/secrets/v1"
_FLAGS = 0x1            # CRYPTPROTECT_UI_FORBIDDEN
_LOCK = threading.Lock()


class SecretError(Exception):
    pass


def _protect(data: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptProtectData(data, "PulseDeck", _ENTROPY, None, None, _FLAGS)


def _unprotect(blob: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptUnprotectData(blob, _ENTROPY, None, None, _FLAGS)[1]


class SecretStore:
    def __init__(self, config_dir):
        self.path = Path(config_dir) / FILE_NAME

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, name):
        with _LOCK:
            blob = self._read().get(name)
        if not blob:
            return ""
        try:
            return _unprotect(base64.b64decode(blob)).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 - wrong user/PC or damaged file
            raise SecretError("Не удалось расшифровать сохранённый токен (другой пользователь Windows или "
                              "повреждённый файл). Введите токен заново.") from exc

    def set(self, name, value):
        with _LOCK:
            data = self._read()
            if value:
                data[name] = base64.b64encode(_protect(value.encode("utf-8"))).decode("ascii")
            else:
                data.pop(name, None)
            self._write(data)


def load_token(config_dir):
    """Token from the encrypted store, else from .env (not yet migrated); '' if none."""
    from pulse_pc.core.settings import read_env
    try:
        token = SecretStore(config_dir).get("BOT_TOKEN")
    except SecretError:
        token = ""
    if token:
        return token
    token = read_env(Path(config_dir) / ".env").get("BOT_TOKEN", "")
    return "" if token == PLACEHOLDER_TOKEN else token


def save_token(config_dir, token):
    """Encrypt the token and leave only the placeholder in .env."""
    from pulse_pc.core.settings import write_env
    SecretStore(config_dir).set("BOT_TOKEN", token)
    write_env(Path(config_dir) / ".env", {"BOT_TOKEN": PLACEHOLDER_TOKEN})


def migrate_token(config_dir):
    """Move a plain-text token from .env into the encrypted store. Returns True if moved."""
    from pulse_pc.core.settings import read_env
    token = read_env(Path(config_dir) / ".env").get("BOT_TOKEN", "")
    if not token or token == PLACEHOLDER_TOKEN:
        return False
    save_token(config_dir, token)
    return SecretStore(config_dir).get("BOT_TOKEN") == token
