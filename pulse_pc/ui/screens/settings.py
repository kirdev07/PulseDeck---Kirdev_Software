"""Настройки: general, Telegram, phone access, security summary, privacy, license and
third-party components, support and about. Every switch acts on a real setting."""
import asyncio
import threading
from pathlib import Path

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QScrollArea, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget, QAbstractItemView, QHeaderView,
)

import config
from modules import mobile_access
from pulse_pc import APP_NAME, __version__
from pulse_pc.core import secrets
from pulse_pc.core import settings as cfg
from pulse_pc.services.system import autostart, components
from pulse_pc.ui.components import Card, PageHeader, StatusLine, Toggle, button, divider, label
from pulse_pc.ui.theme import icon, tokens

ROOT = Path(config.RESOURCE_DIR)   # LICENSE, PRIVACY_POLICY.md … (bundled next to the code in builds)
REPOSITORY = "https://github.com/kirdev07/Pulse-PC"
SECTIONS = (
    ("general", "Основные", "settings"),
    ("telegram", "Telegram Бот", "telegram"),
    ("phone", "Телефон", "phone"),
    ("security", "Безопасность", "shield"),
    ("privacy", "Конфиденциальность", "info"),
    ("license", "Лицензия и компоненты", "info"),
    ("terms", "Условия использования", "info"),
    ("support", "Поддержка", "external"),
    ("about", "О PulseDeck", "pulse"),
)


class TokenProbe(QObject):
    finished = Signal(bool, str)

    def run(self, token):
        def target():
            try:
                from desktop_services import probe_bot, telegram_error
                try:
                    self.finished.emit(True, asyncio.run(probe_bot(token)))
                except Exception as exc:  # noqa: BLE001 - shown to the user
                    self.finished.emit(False, telegram_error(exc))
            except Exception as exc:  # noqa: BLE001
                self.finished.emit(False, str(exc))
        threading.Thread(target=target, daemon=True, name="PulsePC-probe").start()


def setting_row(title, description, control):
    row = QHBoxLayout()
    row.setSpacing(tokens.SPACE_4)
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(label(title))
    if description:
        text.addWidget(label(description, "caption", wrap=True))
    row.addLayout(text, 1)
    row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


def document(path, missing):
    view = QTextBrowser()
    view.setOpenExternalLinks(True)
    view.setStyleSheet("border: none; background: transparent;")
    try:
        view.setMarkdown(Path(path).read_text(encoding="utf-8"))
    except OSError:
        view.setPlainText(missing)
    view.setMinimumHeight(360)
    return view


class SettingsScreen(QWidget):
    def __init__(self, context=None, config_dir=None, parent=None):
        super().__init__(parent)
        self.context = context
        self.config_dir = Path(config_dir or config.CONFIG_DIR)
        self.env_path = self.config_dir / ".env"
        self.ui_store = cfg.SettingsStore(self.config_dir / "app_settings.json")
        self.ui = self.ui_store.load()

        column = QVBoxLayout(self)
        column.setContentsMargins(tokens.SPACE_5, tokens.SPACE_2, tokens.SPACE_5, tokens.SPACE_5)
        column.setSpacing(tokens.SPACE_4)
        column.addWidget(PageHeader("settings", "Настройки", "Параметры приложения, подключений и сведения о программе."))
        body = QHBoxLayout()
        body.setSpacing(tokens.SPACE_4)
        self.nav = QListWidget()
        self.nav.setFixedWidth(230)
        self.nav.setStyleSheet("QListWidget { border: none; background: transparent; } "
                               "QListWidget::item { padding: 9px 10px; }")
        self.pages = QStackedWidget()
        self.section_index = {}
        builders = {"general": self._general, "telegram": self._telegram, "phone": self._phone,
                    "security": self._security, "privacy": self._privacy, "license": self._license,
                    "terms": self._terms,
                    "support": self._support, "about": self._about}
        for key, title, symbol in SECTIONS:
            self.nav.addItem(QListWidgetItem(icon(symbol, tokens.TEXT_2), title))
            self.section_index[key] = self.pages.count()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            holder = QWidget()
            layout = QVBoxLayout(holder)
            layout.setContentsMargins(0, 0, tokens.SPACE_2, 0)
            layout.setSpacing(tokens.SPACE_4)
            builders[key](layout)
            layout.addStretch(1)
            scroll.setWidget(holder)
            self.pages.addWidget(scroll)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.currentRowChanged.connect(lambda _: self.refresh())
        self.nav.setCurrentRow(0)
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)
        column.addLayout(body, 1)

    def open_section(self, key):
        self.nav.setCurrentRow(self.section_index[key])

    # ----- sections -----
    def _general(self, layout):
        card = Card("Основные")
        self.autostart = Toggle(autostart.is_enabled())
        self.autostart.toggled.connect(self.set_autostart)
        card.body.addLayout(setting_row("Запускать вместе с Windows",
                                        "PulseDeck стартует свёрнутым в трей после входа в систему.", self.autostart))
        card.body.addWidget(divider())
        self.animations = Toggle(self.ui.animations)
        self.animations.toggled.connect(self.set_animations)
        card.body.addLayout(setting_row("Анимации интерфейса",
                                        "Плавная смена экранов и переключателей. Выключите на слабом ПК.", self.animations))
        self.general_message = label("", "caption", wrap=True)
        card.body.addWidget(self.general_message)
        layout.addWidget(card)
        look = Card("Оформление")
        look.body.addWidget(label("Тема AMOLED Black — единственная тема интерфейса. Язык — русский.", "muted", wrap=True))
        layout.addWidget(look)

    def _telegram(self, layout):
        card = Card("Подключение бота")
        card.body.addWidget(label("Токен выдаёт @BotFather. ID администратора — ваш числовой Telegram ID: "
                                  "отправьте боту /start, и он подскажет его.", "caption", wrap=True))
        card.body.addWidget(label("ТОКЕН БОТА", "overline"))
        token_row = QHBoxLayout()
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("123456789:AA…")
        self.token.setAccessibleName("Токен бота")
        self.show_token = button("Показать", self._toggle_token, "ghost")
        token_row.addWidget(self.token, 1)
        token_row.addWidget(self.show_token)
        card.body.addLayout(token_row)
        card.body.addWidget(label("ID АДМИНИСТРАТОРА", "overline"))
        self.admin = QLineEdit()
        self.admin.setPlaceholderText("Например, 123456789")
        self.admin.setMaxLength(20)
        card.body.addWidget(self.admin)
        actions = QHBoxLayout()
        actions.addWidget(button("Сохранить", self.save_telegram, "primary", "check"))
        self.probe_button = button("Проверить подключение", self.probe, symbol="refresh")
        actions.addWidget(self.probe_button)
        actions.addStretch(1)
        card.body.addLayout(actions)
        self.telegram_message = label("", "muted", wrap=True)
        card.body.addWidget(self.telegram_message)
        layout.addWidget(card)
        note = Card()
        note.body.addWidget(label("Токен шифруется средствами Windows (DPAPI) и хранится в config/secrets.bin. "
                                  "Расшифровать его может только ваша учётная запись на этом ПК.", "caption", wrap=True))
        layout.addWidget(note)
        self.prober = TokenProbe(self)
        self.prober.finished.connect(self._probe_done)
        self.load_telegram()

    def _phone(self, layout):
        card = Card("Доступ с телефона")
        data = mobile_access.load()
        self.server_enabled = Toggle(data["enabled"])
        self.server_enabled.toggled.connect(lambda on: self.set_phone_option("enabled", on))
        card.body.addLayout(setting_row("Сервер для Pulse Mobile",
                                        "Локальный сервер, через который телефон управляет ПК в домашней сети.",
                                        self.server_enabled))
        card.body.addWidget(divider())
        self.allow_pairing = Toggle(data["allow_pairing"])
        self.allow_pairing.toggled.connect(lambda on: self.set_phone_option("allow_pairing", on))
        card.body.addLayout(setting_row("Разрешить новые подключения",
                                        "Если выключено, подключиться смогут только уже сопряжённые телефоны.",
                                        self.allow_pairing))
        card.body.addWidget(divider())
        self.legacy_http = Toggle(data["legacy_http"])
        self.legacy_http.toggled.connect(lambda on: self.set_phone_option("legacy_http", on))
        card.body.addLayout(setting_row("Старый протокол без шифрования",
                                        "Нужен текущей версии Pulse Mobile. Выключите, когда все телефоны перейдут "
                                        "на подключение по коду (TLS).", self.legacy_http))
        card.body.addWidget(divider())
        card.body.addLayout(setting_row("Порты", "HTTP — старый протокол, TLS — защищённый, UDP — поиск ПК.",
                                        label(f"HTTP {data['port']} · TLS {data['tls_port']} · UDP "
                                              f"{mobile_access.DISCOVERY_PORT}", "mono")))
        self.phone_message = label("Изменения применяются при следующем запуске сервера.", "caption", wrap=True)
        card.body.addWidget(self.phone_message)
        card.body.addWidget(button("Сопряжённые устройства", lambda: self._navigate("phone"), "ghost", "chevron"))
        layout.addWidget(card)

    def _security(self, layout):
        card = Card("Текущее состояние защиты")
        self.security_lines = QVBoxLayout()
        self.security_lines.setSpacing(tokens.SPACE_3)
        card.body.addLayout(self.security_lines)
        layout.addWidget(card)

    def _privacy(self, layout):
        card = Card("Политика конфиденциальности")
        card.body.addWidget(document(ROOT / "PRIVACY_POLICY.md", "Файл PRIVACY_POLICY.md не найден."), 1)
        layout.addWidget(card)
        data = Card("Данные на этом ПК")
        data.body.addWidget(label(f"Настройки, журнал и полученные файлы хранятся в {self.config_dir} "
                                  f"и {config.FILES_DIR}. PulseDeck не отправляет их разработчику.",
                                  "muted", wrap=True))
        data.body.addWidget(button("Открыть папку настроек", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.config_dir))), symbol="folder"))
        layout.addWidget(data)

    def _license(self, layout):
        card = Card("Лицензия PulseDeck")
        card.body.addWidget(document(ROOT / "LICENSE", "Файл LICENSE не найден."), 1)
        layout.addWidget(card)
        third = Card("Сторонние компоненты")
        third.body.addWidget(label("Установленные библиотеки, их версии и лицензии по данным пакетов.",
                                   "caption", wrap=True))
        items = components.installed()
        table = QTableWidget(len(items), 3)
        table.setHorizontalHeaderLabels(("Компонент", "Версия", "Лицензия"))
        table.verticalHeader().hide()
        table.setShowGrid(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for row, item in enumerate(items):
            for col, key in enumerate(("name", "version", "license")):
                cell = QTableWidgetItem(item[key])
                cell.setToolTip(item["url"])
                table.setItem(row, col, cell)
        table.setMinimumHeight(40 + 32 * len(items))
        self.components_table = table
        third.body.addWidget(table)
        third.body.addWidget(label(f"Qt {PYSIDE_VERSION} распространяется по LGPLv3 (PySide6). Подробности и "
                                   "исходный код — в THIRD_PARTY_NOTICES.md.", "caption", wrap=True))
        layout.addWidget(third)

    def _terms(self, layout):
        card = Card("Условия использования")
        card.body.addWidget(document(ROOT / "TERMS_OF_USE.md", "Файл TERMS_OF_USE.md не найден."), 1)
        layout.addWidget(card)

    def _support(self, layout):
        card = Card("Связаться с разработчиком")
        card.body.addWidget(label("Отправка обращений прямо из приложения через Telegram появится, когда будет готов "
                                  "сервер поддержки. Сейчас сообщите о проблеме на GitHub.", "muted", wrap=True))
        card.body.addWidget(label("Перед отправкой уберите из журнала личные данные. PulseDeck ничего не отправляет "
                                  "автоматически.", "caption", wrap=True))
        card.body.addWidget(button("Открыть Issues на GitHub", lambda: QDesktopServices.openUrl(
            QUrl(REPOSITORY + "/issues")), symbol="external"))
        card.body.addWidget(button("Диагностика и журнал", lambda: self._navigate("console"), "ghost", "chevron"))
        layout.addWidget(card)

    def _about(self, layout):
        card = Card()
        row = QHBoxLayout()
        logo = label()
        logo.setPixmap(icon("pulse", tokens.TEXT).pixmap(48, 48))
        row.addWidget(logo)
        names = QVBoxLayout()
        names.addWidget(label(APP_NAME, "title"))
        names.addWidget(label(f"Версия {__version__} · Python {_python()} · Qt {PYSIDE_VERSION}", "caption"))
        row.addLayout(names, 1)
        card.body.addLayout(row)
        card.body.addWidget(label("Управление компьютером Windows с ПК, из Telegram и с телефона.", "muted", wrap=True))
        card.body.addWidget(button("Репозиторий на GitHub", lambda: QDesktopServices.openUrl(QUrl(REPOSITORY)),
                                   symbol="external"))
        layout.addWidget(card)

    # ----- behaviour -----
    def _navigate(self, key):
        navigate = getattr(self.context, "navigate", None)
        if navigate:
            navigate(key)

    def refresh(self):
        self._refresh_security()

    def set_autostart(self, enable):
        try:
            actual = autostart.set_enabled(enable)
            self.general_message.setText("Автозапуск " + ("включён." if actual else "выключен."))
        except Exception as exc:  # noqa: BLE001 - registry or launcher failure is shown
            actual = autostart.is_enabled()
            self.general_message.setText(f"Не удалось изменить автозапуск: {exc}")
        self.autostart.blockSignals(True)
        self.autostart.setChecked(actual)
        self.autostart.blockSignals(False)

    def set_animations(self, on):
        self.ui.animations = on
        self.ui_store.save(self.ui)
        window = getattr(self.context, "window", None)
        if window is not None:
            window.stack.animate = on
        self.general_message.setText("Анимации " + ("включены." if on else "выключены."))

    def load_telegram(self):
        self.token.setText(secrets.load_token(self.config_dir))
        self.admin.setText(cfg.read_env(self.env_path).get("ADMIN_ID", ""))

    def _toggle_token(self):
        hidden = self.token.echoMode() == QLineEdit.EchoMode.Password
        self.token.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.show_token.setText("Скрыть" if hidden else "Показать")

    def save_telegram(self):
        token, admin = self.token.text().strip(), self.admin.text().strip()
        problems = cfg.validate_telegram(token, admin)
        if problems:
            self.telegram_message.setText(" ".join(problems))
            return False
        try:
            secrets.save_token(self.config_dir, token)       # encrypted; .env keeps a placeholder
            cfg.write_env(self.env_path, {"ADMIN_ID": admin})
        except (OSError, secrets.SecretError) as exc:
            self.telegram_message.setText(f"Не удалось сохранить: {exc}")
            return False
        book = getattr(self.context, "logbook", None)
        if book is not None and token:
            book.secrets.extend((token, token.split(":", 1)[-1]))   # the secret part may appear alone
        self.telegram_message.setText("Сохранено. Перезапустите бота, чтобы применить новый токен.")
        self._refresh_security()
        return True

    def probe(self):
        token = self.token.text().strip()
        problems = cfg.validate_telegram(token, "")
        if not token or problems:
            self.telegram_message.setText(problems[0] if problems else "Введите токен бота.")
            return
        self.probe_button.setEnabled(False)
        self.telegram_message.setText("Проверяю…")
        self.prober.run(token)

    def _probe_done(self, ok, text):
        self.probe_button.setEnabled(True)
        self.telegram_message.setText(text)

    def set_phone_option(self, key, value):
        try:
            mobile_access.set_option(key, value)
            self.phone_message.setText("Сохранено. Изменения применяются при следующем запуске сервера.")
        except OSError as exc:
            self.phone_message.setText(f"Не удалось сохранить: {exc}")
        self._refresh_security()

    def _refresh_security(self):
        if not hasattr(self, "security_lines"):
            return
        while self.security_lines.count():
            widget = self.security_lines.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        token = secrets.load_token(self.config_dir)
        encrypted = bool(token) and token == _stored(self.config_dir)
        admin = cfg.read_env(self.env_path).get("ADMIN_ID", "")
        data = mobile_access.load()
        checks = [
            ("ok" if admin.isdigit() else "error",
             "Доступ к боту ограничен вашим Telegram ID" if admin.isdigit() else "ID администратора не задан"),
            ("ok" if encrypted or not token else "off",
             "Токен бота зашифрован средствами Windows для вашей учётной записи" if encrypted
             else "Токен бота хранится в config/.env без шифрования" if token
             else "Токен бота не сохранён на этом ПК"),
            ("ok" if not data["enabled"] or not data["legacy_http"] else "off",
             "Сервер для телефона выключен" if not data["enabled"]
             else "Телефоны подключаются только по защищённому протоколу (TLS)" if not data["legacy_http"]
             else "Включён старый протокол без шифрования (HTTP) для текущей версии Pulse Mobile"),
            ("ok", "Сервер отвечает только устройствам локальной сети"),
            ("off" if data["allow_pairing"] else "ok",
             "Новые телефоны могут запросить подключение (с подтверждением на ПК)" if data["allow_pairing"]
             else "Новые подключения запрещены"),
            ("ok", f"Сопряжённых телефонов: {len(data['devices'])}. Каждый со своим ключом, отзыв — на экране «Телефон»."),
        ]
        for state, text in checks:
            line = StatusLine(text, state)
            line.text.setWordWrap(True)
            self.security_lines.addWidget(line)
        legend = label("● в порядке   ○ требует внимания   ⊗ проблема", "caption")
        self.security_lines.addWidget(legend)


def _stored(config_dir):
    try:
        return secrets.SecretStore(config_dir).get("BOT_TOKEN")
    except secrets.SecretError:
        return ""


def _python():
    import platform
    return platform.python_version()


def build(context):
    return SettingsScreen(context)
