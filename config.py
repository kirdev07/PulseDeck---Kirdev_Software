import os
import sys
from dotenv import load_dotenv

# Где лежит программа и где её данные.
#   Запуск из исходников: данные рядом с кодом (config/, files/), как раньше.
#   Установленная сборка (PyInstaller): программа в папке установки, а данные в
#   %APPDATA%\Pulse-PC — они переживают обновление и удаление программы.
#   PULSE_PC_DATA_DIR переопределяет папку данных (переносная установка, тесты).
FROZEN = getattr(sys, 'frozen', False)
if FROZEN:
    APP_DIR = os.path.dirname(sys.executable)
    RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = APP_DIR

DATA_DIR = os.environ.get("PULSE_PC_DATA_DIR") or (
    os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Pulse-PC") if FROZEN else APP_DIR)
CONFIG_DIR = os.path.join(DATA_DIR, "config")
FILES_DIR = os.path.join(DATA_DIR, "files")      # received files
os.makedirs(CONFIG_DIR, exist_ok=True)

# Для обратной совместимости, BASE_DIR теперь указывает на config
BASE_DIR = CONFIG_DIR

# Загружаем переменные из файла .env в директории config
env_path = os.path.join(CONFIG_DIR, ".env")
if not os.path.exists(env_path):
    with open(env_path, "w") as f:
        f.write("BOT_TOKEN=your_telegram_bot_token_here\nADMIN_ID=\n")

load_dotenv(dotenv_path=env_path, override=True)

# Токен бота. Новая панель хранит его зашифрованным (config/secrets.bin, DPAPI);
# в .env тогда остаётся заглушка.
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_telegram_bot_token_here")
if not BOT_TOKEN.strip() or BOT_TOKEN == "your_telegram_bot_token_here":
    try:
        from pulse_pc.core.secrets import SecretStore
        BOT_TOKEN = SecretStore(CONFIG_DIR).get("BOT_TOKEN") or "your_telegram_bot_token_here"
    except Exception:  # noqa: BLE001 - no store or cannot decrypt: behave as «not set»
        BOT_TOKEN = "your_telegram_bot_token_here"

# ID администратора (один человек)
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "")
ADMIN_ID = None

if ADMIN_ID_RAW.strip() and ADMIN_ID_RAW.strip().isdigit():
    ADMIN_ID = int(ADMIN_ID_RAW.strip())

# Путь к файлу конфигурации программ
PROGRAMS_FILE_PATH = os.path.join(CONFIG_DIR, "programs.json")
