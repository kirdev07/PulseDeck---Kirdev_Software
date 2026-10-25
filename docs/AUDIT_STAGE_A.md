# Pulse-PC Fusion 2.0 — Этап A: аудит

Дата: 2026-10-25. Код не изменялся; этот файл — единственное добавление.

## 0. Блокер перед этапом B

`C:\My Project\PulseDesk` **не является git-репозиторием** (нет `.git`). Правило «работать в отдельной ветке, main не трогать» выполнить нельзя.
Варианты: (1) клонировать `kirdev07/Pulse-PC` и создать ветку `fusion-2.0`, сверив локальные файлы с `main`; (2) `git init` здесь, первый коммит = текущее состояние, затем ветка. Рекомендую (1).

## 1. Карта проекта (≈7 100 строк Python)

| Слой | Файлы | Назначение |
|---|---|---|
| Запуск/установка | `PulsePC.pyw`, `launcher.py`, `install.bat`, `build_release.py` | Создание `.venv` + pip install при первом запуске (Tk-окно прогресса), ярлык, автозапуск, ZIP исходников |
| Конфиг | `config.py`, `config/.env`, `config/*.json` | Токен/ADMIN_ID в `.env`; programs, preferences, local_api, player, history в JSON |
| GUI (монолит) | `gui.py` (1454 стр.), `bot_options_ui.py`, `player_controller.py` | Окно PySide6: главная, программы, телефон, плеер, консоль, настройки; трей; QSS-строка STYLE |
| Telegram | `bot_runtime.py`, `modules/*_handlers.py`, `keyboards.py`, `middleware.py`, `welcome.py`, `bot_features.py`, `bot_preferences.py`, `monitor.py` | aiogram 3 polling в отдельном потоке/цикле |
| Локальный API | `modules/local_api.py`, `mobile_access.py`, `notify_bus.py` | aiohttp на `0.0.0.0:8765`, UDP-поиск `8766`, токены устройств (SHA-256) |
| Медиа | `player_bridge.py`, `now_playing.py` (WinRT SMTC), `volume.py` (pycaw), `media_handlers.py` | Встроенный плеер + внешние сессии + громкость |
| Сервисы | `desktop_services.py`, `background_io.py`, `transfer_history.py`, `program_store.py`, `winutil.py`, `utils.py`, `remote_tools.py` | Журнал, ошибки Telegram, загрузка файлов с прогрессом, утилиты Windows |
| Тесты | `tests/` (6 файлов, unittest) | CI запускает только `test_local_api_security.py` |
| Документы | README, BOT_GUIDE, PRIVACY_POLICY, SECURITY_REVIEW_1_0, LICENSE, УСТАНОВКА | Сохранить; обновить под 2.0 |

## 2. Функции, которые нужно сохранить

**Telegram-команды:** `/start`, `/help`, `/cancel`, `/status`, `/getfile`, `/shutdown`, `/restart`, `/files`, `/history`, `/scenarios`, `/windows`, `/search` (`/s`, `? `), открытие ссылок из сообщений, приём файлов/фото/видео/аудио на ПК, очистка `files/`.
**Inline-меню:** система (сон, блокировка, закрыть активное окно, скриншот по мониторам, инфо), медиа (prev/play/next/громкость/mute), запуск/закрытие программ (по процессу и hwnd), файловый браузер, история передач, таймер питания с подтверждением, сценарии, окна, помощь.
**Фоновое:** уведомление о старте (кулдаун 5 мин), уведомления о блокировке ПК, оповещения по порогам (AlertEvaluator), запрет управления при заблокированном ПК, троттлинг 0.5 с.
**API Pulse Mobile (v0, не ломать):** `/api/ping, pair, status, programs[/run|/kill], volume, media/{a}, system/{a}, screenshot, open_url, windows[/{hwnd}/{a}], files/roots|list|download|upload, history, scenarios[/run], search, monitors, player/state|sessions|focus|cover|tracks|tracks/open|{cmd}, events`; UDP `PULSEPC?` → JSON.
**GUI:** редактор программ (.exe/.lnk, имя процесса, порядок, тест), сопряжённые устройства и отзыв, библиотека плеера, журнал с экспортом, отправка файлов в Telegram с прогрессом/отменой, проверка токена, автозапуск, трей, single-instance lock.

## 3. Ошибки и риски (по приоритету)

### Критические / архитектурные
1. **Локальный API живёт внутри цикла бота** (`bot_runtime._main_async` создаёт `LocalApiServer`). Остановка бота, неверный токен, отсутствие ADMIN_ID или нет интернета → Android не работает. Прямо противоречит требованию.
2. **Shutdown/restart и сценарии по API зависят от `BotFeatures`** («Бот ещё не готов»).
3. **HTTP без шифрования**: bearer-токен телефона и файлы идут открытым текстом по LAN.
4. **Сервер слушает `0.0.0.0` без проверки адреса для авторизованных запросов** — приватность IP проверяется только в `/api/pair`. При пробросе портов/UPnP/публичном IP API доступен из интернета.
5. **Файловый API без ограничений**: `files/list` и `files/download` читают любой путь на любом диске; `/getfile` в Telegram тоже. Это осознанная функция, но нужна настройка разрешённых папок.
6. **Токен бота — открытым текстом в `config/.env` рядом с программой**. При установке в Program Files папка будет недоступна для записи, а обновление может её затереть.

### Средние
7. Сопряжение подтверждается только `MessageBox` с именем от телефона — нет кода подтверждения (возможна подмена в LAN), окно может появиться поверх игры/полноэкранного приложения.
8. Две разные реализации автозапуска: `launcher.set_autostart` (PulsePC.pyw) и `gui.change_autostart` (сразу `gui.py`, минуя проверку окружения).
9. Два обработчика ссылок: `system_handlers.handle_url_message` и `file_handlers.handle_url` (второй почти недостижим).
10. `F.text.startswith("/s")` перехватывает любую неизвестную команду на `/s…` (например `/stop`, `/settings`) и делает поиск Google.
11. `GetUpdates` Conflict/Unauthorized вызывает `self.stop()` изнутри middleware — работает, но без понятного состояния «конфликт» в UI.
12. `notify_bus` / `mobile_access.STATE` / `player_bridge.STATE` — глобальные модули-синглтоны, общие для потоков; трудно тестировать и переносить.
13. `gui.py` — монолит: UI, сохранение `.env`, реестр, программы, передачи файлов в одном классе.
14. `config.py` создаёт `.env` и папку при импорте (побочный эффект).
15. Python 3.14 в системе, PySide6 не установлен → тесты сейчас локально не запускались. CI на 3.11.
16. Установка требует системного Python + pip из интернета; Tk-установщик — отдельный UI.
17. `pyautogui` используется только для медиа-клавиш (тяжёлая зависимость, тянет pymsgbox/pyscreeze и т.п.) — заменить на `keybd_event` через ctypes/pywin32.

### Не нарушения, но учесть
- Telegram: используется стандартный `api.telegram.org` через aiogram, жёстко прописанных IP нет ✔.
- Проверка администратора есть (`AuthMiddleware`), токен маскируется в логах (`redact`) ✔.
- Токены телефонов хранятся как хэши, сравнение `hmac.compare_digest` ✔, лимит 10 устройств, лимит запросов сопряжения ✔.

## 4. Зависимости

| Пакет | Где | Решение |
|---|---|---|
| PySide6 | GUI, QtMultimedia | Оставить; при сборке исключить WebEngine, 3D, QML, Charts и т.п. (основной резерв по размеру) |
| aiogram 3, aiohttp | бот, API | Оставить |
| python-dotenv | config, gui | Заменить на JSON-настройки + DPAPI для токена (оставить чтение старого `.env` для миграции) |
| psutil, pywin32, mss, pillow | метрики, Windows, скриншоты | Оставить |
| PyAutoGUI | только медиа-клавиши | Заменить на ctypes, удалить |
| winrt-* (опц.) | now_playing | Оставить опционально, включить в сборку |
| pycaw (опц.) | громкость | Оставить, включить в сборку |
| tkinter | только PulsePC.pyw | Уйдёт вместе с self-install после появления установщика |
| GPU-метрики | — | Новое: через Windows PDH/`nvidia-ml` недоступно везде → честное «Недоступно» |

## 5. Предлагаемая структура

```
pulse_pc/
  app.py                 # точка входа, single-instance, DI
  core/                  # paths (%APPDATA%\Pulse-PC), settings, secrets (DPAPI), logging, events (шина)
  services/
    telegram/            # runtime.py (жизненный цикл), handlers/, keyboards.py, middleware.py
    local_api/           # server.py, routes_v0.py (как сейчас), routes_v1.py, pairing.py, devices.py, discovery.py, tls.py
    system/              # metrics.py, power.py, windows.py, programs.py, files.py, screenshot.py
    media/               # player.py (Qt), sessions.py (WinRT), volume.py
    support/             # клиент сервиса обращений
  ui/
    theme/               # tokens.py, qss, иконки
    components/          # Card, Sidebar, TitleBar, StatTile, Sparkline, Toggle, LogView...
    screens/             # dashboard, telegram, phone, apps, console, music, settings
    viewmodels/          # состояние экранов, связь с сервисами через сигналы
  resources/
installer/               # spec сборщика + Inno Setup
tests/
docs/
```
Ключевое: **ServiceManager** запускает Telegram и Local API как независимые сервисы со своими asyncio-циклами/задачами; общие действия (питание, сценарии) переезжают из `BotFeatures` в `services/system`.

## 6. Оставить / переработать / удалить

| Компонент | Решение |
|---|---|
| Все обработчики Telegram, keyboards, middleware, welcome | Перенести, исправить п.9–10 |
| `local_api.py` | Разделить; маршруты v0 сохранить без изменений, добавить `/api/v1` |
| `mobile_access.py`, `program_store`, `transfer_history`, `bot_preferences`, `background_io`, `now_playing`, `volume`, `winutil`, `monitor` | Оставить логику, перенести в новые пакеты |
| `desktop_services.py` | Разделить: journal → core/logging, телеграм-функции → services/telegram |
| `gui.py`, `bot_options_ui.py` | Переписать как экраны (логику вынести в сервисы) |
| `player_controller.py` | Перенести в services/media, расширить очередь |
| `config.py` | Заменить на core/settings + миграция старого `config/` |
| `launcher.py`, `PulsePC.pyw`, `install.bat` | Оставить до готовности установщика (этап F), затем удалить — по согласованию |
| `build_release.py`, `release.yml` | Заменить сборкой установщика |
| `modules/utils.py::safe_edit_text` и др. | Проверить использование при переносе |
| README, LICENSE, PRIVACY_POLICY, SECURITY_REVIEW, BOT_GUIDE, УСТАНОВКА | Сохранить, обновить тексты |
| `image/*` | Сохранить (иконка); проверить использование emblem/logo |
| Удалить сейчас | **Ничего** |

## 7. Решения, которые нужны от вас

1. Git: клонировать репозиторий или `git init` здесь?
2. Шифрование API v1: самоподписанный TLS-сертификат с закреплением отпечатка при сопряжении (рекомендую) или шифрование на уровне приложения?
3. Сопряжение: 6-значный код на экране ПК, вводимый на телефоне (рекомендую), вместо простого «Да/Нет».
4. Файловый доступ телефона/Telegram: оставить весь диск или ввести список разрешённых папок (по умолчанию — весь диск, как сейчас, с переключателем)?
5. Сервер поддержки: где он будет размещён (нужен ваш хостинг для бота-приёмника обращений)?
6. Сборщик: Nuitka (меньше размер, дольше сборка) или PyInstaller onedir + Inno Setup (проще, предсказуемее). Предлагаю измерить оба на этапе F.
7. Пользовательские данные переезжают в `%APPDATA%\Pulse-PC` с автоматической миграцией из `config/` — согласны?
