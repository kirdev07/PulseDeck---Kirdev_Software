"""Self-check run on demand from the console. Each check returns (level, title, detail);
nothing is sent anywhere except the Telegram reachability probe (DNS + TLS port)."""
import importlib.util
import json
import os
import platform
import socket
import sys
from pathlib import Path

from pulse_pc import __version__

OK, WARN, ERROR = "INFO", "WARN", "ERROR"
TELEGRAM_HOST = "api.telegram.org"


def _dotenv(path):
    values = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return values


def check_environment():
    bits = "64" if sys.maxsize > 2**32 else "32"
    return OK, "Окружение", (f"Pulse-PC {__version__} · Python {platform.python_version()} ({bits} бит) · "
                             f"{platform.system()} {platform.release()} ({platform.version()})")


def check_config_dir(config_dir):
    path = Path(config_dir)
    probe = path / ".write-test"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return OK, "Папка настроек", f"Доступна для записи: {path}"
    except OSError as exc:
        return ERROR, "Папка настроек", f"Нет доступа на запись ({path}): {exc.strerror or exc}"


def check_programs(path):
    path = Path(path)
    if not path.exists():
        return OK, "Список программ", "Ещё не создан."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        from modules.program_store import validate_programs
        validate_programs(data)
        missing = [p["name"] for p in data if not Path(os.path.expandvars(p["path"])).is_file()]
        if missing:
            return WARN, "Список программ", f"Программ: {len(data)}. Файлы не найдены: {', '.join(missing)}"
        return OK, "Список программ", f"Программ: {len(data)}, все файлы на месте."
    except (OSError, ValueError) as exc:
        return ERROR, "Список программ", f"{path.name} повреждён: {exc}"


def check_telegram_settings(env_path):
    from pulse_pc.core.secrets import load_token
    values = _dotenv(env_path)
    token = load_token(Path(env_path).parent)
    admin = values.get("ADMIN_ID", "")
    problems = []
    if not token or token == "your_telegram_bot_token_here":
        problems.append("токен бота не указан")
    elif ":" not in token:
        problems.append("токен выглядит неверно")
    if not admin.isdigit():
        problems.append("ID администратора не указан")
    if problems:
        text = "; ".join(problems)
        return WARN, "Настройки Telegram", text[0].upper() + text[1:] + "."
    return OK, "Настройки Telegram", "Токен и ID администратора заданы."


def check_telegram_reachable(timeout=5):
    try:
        address = socket.getaddrinfo(TELEGRAM_HOST, 443, type=socket.SOCK_STREAM)[0][4]
    except OSError as exc:
        return ERROR, "Связь с Telegram", f"Не удаётся найти {TELEGRAM_HOST} (DNS): {exc}. Проверьте интернет."
    try:
        with socket.create_connection(address[:2], timeout=timeout):
            pass
    except OSError as exc:
        return ERROR, "Связь с Telegram", (f"{TELEGRAM_HOST} не отвечает на порту 443: {exc}. "
                                           "Возможно, доступ ограничен сетью или провайдером — проверьте VPN или прокси.")
    return OK, "Связь с Telegram", f"{TELEGRAM_HOST} доступен."


def check_port(port, kind=socket.SOCK_STREAM, title="Порт"):
    """Free port -> OK; busy port -> WARN (may be Pulse-PC itself)."""
    sock = socket.socket(socket.AF_INET, kind)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError:
        return WARN, title, f"Порт {port} занят (это нормально, если сервер Pulse-PC уже запущен)."
    finally:
        sock.close()
    return OK, title, f"Порт {port} свободен."


def check_optional():
    found = {name: importlib.util.find_spec(module) is not None for name, module in (
        ("«Что играет» в других приложениях", "winrt.windows.media.control"),
        ("Точная громкость", "pycaw"),
        ("Скриншоты", "mss"),
    )}
    missing = [name for name, ok in found.items() if not ok]
    if missing:
        return WARN, "Дополнительные компоненты", "Не установлены: " + ", ".join(missing)
    return OK, "Дополнительные компоненты", "Все установлены."


def run_all(config_dir, programs_path, env_path, api_port=8765, discovery_port=8766, network=True):
    checks = [
        check_environment,
        lambda: check_config_dir(config_dir),
        lambda: check_programs(programs_path),
        lambda: check_telegram_settings(env_path),
        lambda: check_port(api_port, title="Порт сервера для телефона"),
        lambda: check_port(discovery_port, socket.SOCK_DGRAM, "Порт поиска ПК (UDP)"),
        check_optional,
    ]
    if network:
        checks.insert(4, check_telegram_reachable)
    results = []
    for check in checks:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 - a broken check is itself a finding
            results.append((ERROR, "Проверка", f"Не выполнена: {exc}"))
    return results
