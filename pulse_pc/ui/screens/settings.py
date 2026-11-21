"""Настройки: general, Telegram, phone access, security summary, privacy, license and
third-party components, support and about. Every switch acts on a real setting."""
import asyncio
import threading
from pathlib import Path

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
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
from pulse_pc.ui.theme.icons import logo_pixmap

ROOT = Path(config.RESOURCE_DIR)   # LICENSE, PRIVACY_POLICY.md … (bundled next to the code in builds)
REPOSITORY = "https://github.com/kirdev07/PulseDeck---Kirdev_Software"
SECTIONS = (
    ("general", "Основные", "settings"),
    ("look", "Оформление", "palette"),
    ("telegram", "Telegram Бот", "telegram"),
    ("phone", "Телефон", "phone"),
    ("web", "Веб-панель", "network"),
    ("security", "Безопасность", "shield"),
    ("privacy", "Конфиденциальность", "info"),
    ("license", "Лицензия и компоненты", "info"),
    ("terms", "Условия использования", "info"),
    ("updates", "Обновления", "refresh"),
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
        threading.Thread(target=target, daemon=True, name="PulseDeck-probe").start()


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


class Segmented(QWidget):
    """Material 3 segmented button: one outlined pill split into options; the chosen one is
    filled with the secondary container and carries a check."""

    def __init__(self, options, current, on_change, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QButtonGroup
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        last = len(options) - 1
        for index, (value, text) in enumerate(options):
            choice = button(text)
            choice.setCheckable(True)
            left = f"{tokens.RADIUS_PILL}px" if index == 0 else "0"
            right = f"{tokens.RADIUS_PILL}px" if index == last else "0"
            choice.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {tokens.TEXT}; border: 1px solid {tokens.BORDER_STRONG};"
                f" border-left-width: {1 if index == 0 else 0}px; border-top-left-radius: {left};"
                f" border-bottom-left-radius: {left}; border-top-right-radius: {right};"
                f" border-bottom-right-radius: {right}; padding: 8px 16px; }}"
                f" QPushButton:hover {{ background: {tokens.SURFACE_HOVER}; }}"
                f" QPushButton:checked {{ background: {tokens.SECONDARY_CONTAINER}; color: {tokens.ON_SECONDARY_CONTAINER}; }}")
            choice.toggled.connect(lambda on, b=choice: b.setIcon(icon("check", tokens.ON_SECONDARY_CONTAINER) if on
                                                                  else QIcon()))
            choice.setChecked(value == current)
            choice.clicked.connect(lambda _=False, v=value: on_change(v))
            self.group.addButton(choice)
            self.buttons[value] = choice
            row.addWidget(choice)


def choice_row(options, current, on_change):
    return Segmented(options, current, on_change)


class Swatch(QWidget):
    """A round colour choice (40 px); the chosen one has a ring and a check."""

    clicked = Signal()

    def __init__(self, color, name, parent=None):
        super().__init__(parent)
        self.color = color
        self.checked = False
        self.setFixedSize(48, 48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)
        self.setAccessibleName(name)

    def setChecked(self, on):
        self.checked = on
        self.update()

    def mouseReleaseEvent(self, event):
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter, QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor(self.color)
        if not self.isEnabled():
            fill.setAlphaF(0.35)
        if self.checked:
            painter.setPen(QPen(QColor(tokens.TEXT), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(1, 1, 46, 46))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(5, 5, 38, 38))
        if self.checked:
            painter.drawPixmap(12, 12, icon("check", "#FFFFFF").pixmap(24, 24))


class Document(QTextBrowser):
    """A document shown in full: as tall as its text at the current width, so the section
    scrolls as one page instead of a small box with a scrollbar of its own."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QSizePolicy
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(lambda _size: self._fit())

    def _fit(self):
        self.document().setTextWidth(self.viewport().width())
        height = int(self.document().size().height()) + 2 * self.frameWidth() + 4
        if height != self.height():
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def wheelEvent(self, event):
        event.ignore()              # the page scrolls, not the document


def document(path, missing):
    view = Document()
    view.setOpenExternalLinks(True)
    view.setStyleSheet("border: none; background: transparent;")
    try:
        view.setMarkdown(Path(path).read_text(encoding="utf-8"))
    except OSError:
        view.setPlainText(missing)
    return view


def compact(widget):
    """A button as wide as its text inside a card (Material 3), not stretched across it."""
    from PySide6.QtWidgets import QSizePolicy
    widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return widget


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
                               "QListWidget::item { padding: 11px 16px; border-radius: 18px; margin: 1px 0; }")
        self.pages = QStackedWidget()
        self.section_index = {}
        builders = {"general": self._general, "look": self._look, "telegram": self._telegram, "phone": self._phone,
                    "web": self._web,
                    "security": self._security, "privacy": self._privacy, "license": self._license,
                    "terms": self._terms, "updates": self._updates,
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

    def _look(self, layout):
        """Material 3 palette: style, theme, accent, background. Colours are built into every
        widget when it is created, so «Применить» restarts the window (services keep their
        settings; the restart takes a few seconds)."""
        self.look = {key: getattr(self.ui, key) for key in ("style", "accent", "mode", "amoled", "background")}
        theme = Card("Тема")
        self.style_choice = choice_row((("color", "Цветной"), ("mono", "Чёрно-белый")), self.look["style"],
                                       lambda v: self.pick_look("style", v))
        theme.body.addLayout(setting_row("Стиль", "Чёрно-белый — прежний строгий вид PulseDeck, без цвета акцента.",
                                         self.style_choice))
        theme.body.addWidget(divider())
        self.mode_choice = choice_row((("dark", "Тёмная"), ("light", "Светлая"), ("system", "Как в Windows")),
                                      self.look["mode"], lambda v: self.pick_look("mode", v))
        theme.body.addLayout(setting_row("Режим", "«Как в Windows» следует настройке «Режим приложений».", self.mode_choice))
        theme.body.addWidget(divider())
        self.amoled = Toggle(self.look["amoled"])
        self.amoled.toggled.connect(lambda on: self.pick_look("amoled", on))
        theme.body.addLayout(setting_row("Чёрный фон (AMOLED)", "В тёмном режиме окно чисто чёрное — экономит заряд "
                                         "OLED-экранов.", self.amoled))
        layout.addWidget(theme)

        accent = Card("Цвет акцента")
        accent.body.addWidget(label("Из него строятся все оттенки программы: кнопки, переключатели, графики, "
                                    "подсветка. В чёрно-белом стиле не используется.", "caption", wrap=True))
        swatches = QHBoxLayout()
        swatches.setSpacing(tokens.SPACE_3)
        self.swatches = {}
        names = {"purple": "Фиолетовый", "blue": "Голубой", "green": "Зелёный", "orange": "Оранжевый", "pink": "Розовый"}
        for key in tokens.ACCENTS:
            swatch = Swatch(tokens.SEEDS[key], names[key])
            swatch.clicked.connect(lambda _=False, k=key: self.pick_look("accent", k))
            swatches.addWidget(swatch)
            self.swatches[key] = swatch
        swatches.addStretch(1)
        accent.body.addLayout(swatches)
        layout.addWidget(accent)

        background = Card("Фон окна")
        self.background_choice = choice_row((("glow", "Свечение"), ("dots", "Точки"), ("flat", "Ровный")),
                                            self.look["background"], lambda v: self.pick_look("background", v))
        background.body.addLayout(setting_row("Фон", "Свечение — мягкий свет цвета акцента из углов окна.",
                                              self.background_choice))
        layout.addWidget(background)

        apply_row = QHBoxLayout()
        self.look_message = label("", "caption", wrap=True)
        apply_row.addWidget(self.look_message, 1)
        self.look_apply = button("Применить", self.apply_look, "primary", "check")
        self.look_apply.setEnabled(False)
        apply_row.addWidget(self.look_apply)
        layout.addLayout(apply_row)
        self._show_look()

    def pick_look(self, key, value):
        self.look[key] = value
        self._show_look()

    def _show_look(self):
        for key, swatch in self.swatches.items():
            swatch.setChecked(key == self.look["accent"])
            swatch.setEnabled(self.look["style"] == "color")
        self.amoled.setEnabled(self.look["mode"] != "light")
        changed = any(self.look[key] != getattr(self.ui, key) for key in self.look)
        self.look_apply.setEnabled(changed)
        self.look_message.setText("Окно PulseDeck перезапустится на пару секунд — бот и сервер для телефонов "
                                  "запустятся снова сами." if changed else "")

    def apply_look(self):
        for key, value in self.look.items():
            setattr(self.ui, key, value)
        self.ui_store.save(self.ui)
        from pulse_pc.app import restart_application
        if not restart_application(open_page="settings"):
            self.look_message.setText("Сохранено. Новое оформление появится при следующем запуске PulseDeck.")
            self.look_apply.setEnabled(False)

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
        card.body.addLayout(setting_row("Сервер для телефона",
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
                                        "Нужен только старому приложению Pulse Mobile; по умолчанию выключен. В той же Wi-Fi "
                                        "его ключи можно перехватить. PulseDesk и PulseDeck Panel подключаются по коду (TLS).",
                                        self.legacy_http))
        card.body.addWidget(divider())
        card.body.addLayout(setting_row("Порты", "HTTP — старый протокол, TLS — защищённый, UDP — поиск ПК.",
                                        label(f"HTTP {data['port']} · TLS {data['tls_port']} · UDP "
                                              f"{mobile_access.DISCOVERY_PORT}", "mono")))
        self.phone_message = label("Изменения применяются при следующем запуске сервера.", "caption", wrap=True)
        card.body.addWidget(self.phone_message)
        card.body.addWidget(button("Сопряжённые устройства", lambda: self._navigate("phone"), "ghost", "chevron"))
        layout.addWidget(card)

    def _web(self, layout):
        from pulse_pc.ui.screens.web_panel_settings import WebPanelSection
        self.web_section = WebPanelSection(self, layout)

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
        data.body.addWidget(compact(button("Открыть папку настроек", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.config_dir))), symbol="folder")))
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
        head = table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.verticalHeader().setDefaultSectionSize(34)
        for row, item in enumerate(items):
            for col, key in enumerate(("name", "version", "license")):
                cell = QTableWidgetItem(item[key])
                cell.setToolTip(item["url"])
                table.setItem(row, col, cell)
        # Every row visible: the section scrolls, not a box inside it.
        table.setFixedHeight(head.sizeHint().height() + 34 * len(items) + 4)
        self.components_table = table
        third.body.addWidget(table)
        third.body.addWidget(label(f"Qt {PYSIDE_VERSION} распространяется по LGPLv3 (PySide6). Подробности и "
                                   "исходный код — в THIRD_PARTY_NOTICES.md.", "caption", wrap=True))
        layout.addWidget(third)

    def _terms(self, layout):
        card = Card("Условия использования")
        card.body.addWidget(document(ROOT / "TERMS_OF_USE.md", "Файл TERMS_OF_USE.md не найден."), 1)
        layout.addWidget(card)

    def _updates(self, layout):
        from pulse_pc.services import updates
        card = Card("Обновления")
        self.update_status = label("", "", wrap=True)
        self.update_notes = label("", "caption", wrap=True)
        self.update_notes.hide()
        card.body.addWidget(self.update_status)
        card.body.addWidget(self.update_notes)
        row = QHBoxLayout()
        self.update_button = button("Проверить", self._update_action, "primary", "refresh")
        row.addWidget(self.update_button)
        row.addWidget(button("Все версии на GitHub", lambda: QDesktopServices.openUrl(QUrl(updates.RELEASES)),
                             "ghost", "external"))
        row.addStretch(1)
        card.body.addLayout(row)
        card.body.addWidget(label(f"PulseDeck проверяет GitHub при запуске и каждые {updates.AUTO_HOURS} ч, новую версию скачивает сам и предлагает установить. "
                                  "Новая версия ставится поверх: настройки, токен и телефоны сохраняются, "
                                  "программа перезапустится сама.", "caption", wrap=True))
        layout.addWidget(card)
        self.updater = getattr(self.context, "updater", None)
        if self.updater is not None:
            self.updater.changed.connect(self._show_update)
        self._show_update()

    def _update_action(self):
        from pulse_pc.services import updates
        if self.updater is None:
            return
        if self.updater.state == updates.AVAILABLE:
            self.updater.download()
        elif self.updater.state == updates.READY:
            self.updater.install()
        else:
            self.updater.check()

    def _show_update(self, *_):
        from pulse_pc.services import updates
        updater = self.updater
        notes = ""
        if updates.portable_build():
            text, action = (f"Портативная версия {__version__}. Чтобы обновиться, скачайте новый ZIP со страницы "
                            "«Все версии на GitHub» и распакуйте поверх этой папки."), None
        elif updater is None or not updates.installed_build():
            text, action = (f"Установлена версия {__version__}. Запуск из исходников обновляется через git pull; "
                            "автообновление работает в установленной программе."), None
        else:
            state, release = updater.state, updater.release
            text, action = {
                updates.IDLE: (f"Установлена версия {__version__}.", "Проверить"),
                updates.CHECKING: ("Проверяю обновления…", None),
                updates.UP_TO_DATE: (f"Установлена последняя версия {__version__}.", "Проверить"),
                updates.AVAILABLE: (f"Доступна версия {release.version if release else ''} (у вас {__version__}).",
                                    "Скачать и установить"),
                updates.DOWNLOADING: (f"Скачиваю {release.version if release else ''}: {round(updater.progress * 100)}%",
                                      None),
                updates.READY: ("Обновление скачано. PulseDeck закроется, установит новую версию и запустится снова.",
                                "Установить и перезапустить"),
                updates.FAILED: (updater.message, "Проверить"),
            }[state]
            if state == updates.AVAILABLE and release:
                notes = release.notes[:600]
        self.update_status.setText(text)
        self.update_notes.setText(notes)
        self.update_notes.setVisible(bool(notes))
        self.update_button.setVisible(action is not None)
        if action:
            self.update_button.setText(action)

    def _support(self, layout):
        card = Card("Связаться с разработчиком")
        card.body.addWidget(label("Отправка обращений прямо из приложения через Telegram появится, когда будет готов "
                                  "сервер поддержки. Сейчас сообщите о проблеме на GitHub.", "muted", wrap=True))
        card.body.addWidget(label("Перед отправкой уберите из журнала личные данные. PulseDeck ничего не отправляет "
                                  "автоматически.", "caption", wrap=True))
        card.body.addWidget(compact(button("Открыть Issues на GitHub", lambda: QDesktopServices.openUrl(
            QUrl(REPOSITORY + "/issues")), symbol="external")))
        card.body.addWidget(compact(button("Диагностика и журнал", lambda: self._navigate("console"), "ghost",
                                           "chevron")))
        layout.addWidget(card)

    def _about(self, layout):
        card = Card()
        row = QHBoxLayout()
        logo = label()
        logo.setPixmap(logo_pixmap(56, logo.devicePixelRatioF(), themed=True))
        row.addWidget(logo)
        names = QVBoxLayout()
        names.addWidget(label(APP_NAME, "title"))
        names.addWidget(label(f"Версия {__version__} · Python {_python()} · Qt {PYSIDE_VERSION}", "caption"))
        row.addLayout(names, 1)
        card.body.addLayout(row)
        card.body.addWidget(label("Управление компьютером Windows с ПК, из Telegram и с телефона.", "muted", wrap=True))
        card.body.addWidget(compact(button("Репозиторий на GitHub", lambda: QDesktopServices.openUrl(QUrl(REPOSITORY)),
                                           symbol="external")))
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
             else "Включён старый протокол без шифрования (HTTP) для старого приложения Pulse Mobile"),
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
        # The legend with the same dots as the lines above (text glyphs came out tiny).
        legend = QWidget()
        row = QHBoxLayout(legend)
        row.setContentsMargins(0, tokens.SPACE_2, 0, 0)
        row.setSpacing(tokens.SPACE_4)
        for state, text in (("ok", "в порядке"), ("off", "требует внимания"), ("error", "проблема")):
            row.addWidget(StatusLine(text, state, "caption"))
        row.addStretch(1)
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
