"""Settings of the new interface (config/app_settings.json) and the Telegram values in
config/.env, which the bot and the classic panel also read.

The token stays in .env during the migration; encrypted storage is stage E.
"""
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path

PLACEHOLDER_TOKEN = "your_telegram_bot_token_here"
TOKEN_PATTERN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class UiSettings:
    animations: bool = True
    telegram_autostart: bool = True     # start the bot with Pulse-PC when it is configured
    start_page: str = "dashboard"


class SettingsStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        known = {f.name: f for f in fields(UiSettings)}
        values = {}
        for key, value in (data.items() if isinstance(data, dict) else ()):
            if key in known and isinstance(value, type(getattr(UiSettings(), key))):
                values[key] = value
        return UiSettings(**values)

    def save(self, settings):
        atomic_write_text(self.path, json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n")


_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].replace("\'", "'").replace('\\"', '"').replace("\\\\", "\\")
    return value


def read_env(path):
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        match = _LINE.match(line)
        if match and not line.lstrip().startswith("#"):
            values[match[1]] = _unquote(match[2])
    return values


def write_env(path, updates):
    """Replace the given keys, keep every other line and comment (same as the classic panel)."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output = [line for line in lines if not ((m := _LINE.match(line)) and m[1] in updates)]
    for key, value in updates.items():
        escaped = str(value).replace("\\", "\\\\").replace("'", "\'")
        output.append(f"{key}='{escaped}'")
    atomic_write_text(path, "\n".join(output) + "\n")


def validate_telegram(token, admin_id):
    """Returns a list of problems (empty = fine). Empty values are allowed (bot not set up)."""
    problems = []
    if token and not TOKEN_PATTERN.match(token):
        problems.append("Токен должен выглядеть как 123456789:AA… — скопируйте его из @BotFather целиком.")
    if admin_id and (not admin_id.isascii() or not admin_id.isdigit() or int(admin_id) <= 0):
        problems.append("ID администратора — положительное целое число.")
    return problems


def mask(token):
    return "" if not token or token == PLACEHOLDER_TOKEN else token.split(":")[0] + ":" + "•" * 8 + token[-4:]
