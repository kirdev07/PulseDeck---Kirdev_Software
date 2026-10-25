"""Telegram Бот: start/stop/restart, live connection state, counters, settings and the
bot's part of the journal."""
import time

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget,
)

from pulse_pc.core import settings as cfg
from pulse_pc.core import state as st
from pulse_pc.services.system.metrics import format_uptime
from pulse_pc.ui.components import Card, PageHeader, StatTile, StatusLine, Toggle, button, divider, label
from pulse_pc.ui.theme import icon, tokens

STATUS = {st.UNKNOWN: ("Нет данных", "off"), st.STOPPED: ("Бот остановлен", "off"),
          st.STARTING: ("Запуск…", "busy"), st.RUNNING: ("Бот активен", "ok"),
          st.RECONNECTING: ("Переподключение…", "busy"), st.ERROR: ("Ошибка", "error")}
ACTIVE = (st.STARTING, st.RUNNING, st.RECONNECTING)
LOG_LINES = 300


class TelegramScreen(QWidget):
    def __init__(self, context, config_dir=None, parent=None):
        super().__init__(parent)
        import config
        self.context = context
        self.store = context.store
        self.services = getattr(context, "services", None)
        self.config_dir = config_dir or config.CONFIG_DIR
        self.ui_store = cfg.SettingsStore(f"{self.config_dir}/app_settings.json")

        column = QVBoxLayout(self)
        column.setContentsMargins(tokens.SPACE_5, tokens.SPACE_2, tokens.SPACE_5, tokens.SPACE_5)
        column.setSpacing(tokens.SPACE_4)
        column.addWidget(PageHeader("telegram", "Telegram Бот", "Управление, мониторинг и настройки бота."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(tokens.SPACE_4)
        grid.setVerticalSpacing(tokens.SPACE_4)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.addWidget(self._hero(), 0, 0)
        grid.addWidget(self._info_card(), 0, 1)
        tiles = QHBoxLayout()
        tiles.setSpacing(tokens.SPACE_3)
        self.updates_tile = StatTile("telegram", "ОБНОВЛЕНИЙ", unit="", history=False)
        self.denied_tile = StatTile("shield", "ОТКЛОНЕНО", unit="", history=False)
        self.failures_tile = StatTile("info", "ОШИБОК", unit="", history=False)
        self.uptime_tile = StatTile("power", "В СЕТИ", unit="", history=False)
        for tile in (self.updates_tile, self.denied_tile, self.failures_tile, self.uptime_tile):
            tiles.addWidget(tile, 1)
        grid.addLayout(tiles, 1, 0)
        side = QVBoxLayout()
        side.setSpacing(tokens.SPACE_4)
        side.addWidget(self._control_card())
        side.addWidget(self._send_card())
        side.addStretch(1)
        grid.addLayout(side, 1, 1, 2, 1)
        grid.addWidget(self._log_card(), 2, 0)
        grid.setRowStretch(2, 1)
        column.addLayout(grid, 1)

        self.store.changed.connect(self._changed)
        book = getattr(context, "logbook", None)
        if book is not None:
            for entry in book.snapshot()[-LOG_LINES:]:
                self._log(entry)
            book.added.connect(self._log)
        self.timer = QTimer(self, interval=1000, timeout=self._tick)
        self.timer.start()
        self._show(self.store.state.telegram)

    # ----- layout -----
    def _hero(self):
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_5)
        badge = QLabel()
        badge.setFixedSize(84, 84)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icon("telegram", tokens.TEXT).pixmap(QSize(38, 38)))
        badge.setStyleSheet(f"border: 1px solid {tokens.BORDER_STRONG}; border-radius: 42px; background: {tokens.SURFACE_2};")
        row.addWidget(badge)
        text = QVBoxLayout()
        text.setSpacing(tokens.SPACE_1)
        self.status = StatusLine("", "off", "heading")
        self.detail = label("", "muted", wrap=True)
        text.addWidget(self.status)
        text.addWidget(self.detail)
        actions = QHBoxLayout()
        self.toggle_button = button("Запустить", self.toggle, "primary", "play")
        self.restart_button = button("Перезапустить", self.restart, symbol="refresh")
        actions.addWidget(self.toggle_button)
        actions.addWidget(self.restart_button)
        actions.addStretch(1)
        text.addLayout(actions)
        row.addLayout(text, 1)
        card.body.addLayout(row)
        return card

    def _info_card(self):
        card = Card("Информация")
        self.info = {}
        for key, name in (("bot", "Бот"), ("title", "Имя"), ("admin", "Администратор"), ("token", "Токен")):
            row = QHBoxLayout()
            row.addWidget(label(name, "muted"), 1)
            value = label("—", "mono")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(value)
            self.info[key] = value
            card.body.addLayout(row)
        card.body.addWidget(divider())
        links = QHBoxLayout()
        self.chat_button = button("Открыть чат", self.open_chat, "ghost", "external")
        links.addWidget(self.chat_button)
        links.addWidget(button("@BotFather", lambda: QDesktopServices.openUrl(QUrl("https://t.me/BotFather")),
                               "ghost", "external"))
        links.addStretch(1)
        card.body.addLayout(links)
        return card

    def _control_card(self):
        card = Card("Управление")
        self.autostart = Toggle(self.ui_store.load().telegram_autostart)
        self.autostart.toggled.connect(self.set_autostart)
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.addWidget(label("Запускать вместе с Pulse-PC"))
        text.addWidget(label("Если бот настроен, он стартует при запуске программы.", "caption", wrap=True))
        row.addLayout(text, 1)
        row.addWidget(self.autostart)
        card.body.addLayout(row)
        card.body.addWidget(divider())
        card.body.addWidget(button("Меню, сценарии и уведомления…", self.open_options, symbol="settings"))
        card.body.addWidget(label("Кнопки главного меню бота, сценарии запуска программ и оповещения о нагрузке. "
                                  "Применяются сразу, без перезапуска.", "caption", wrap=True))
        card.body.addWidget(button("Токен и ID администратора", self.open_settings, "ghost", "chevron"))
        card.body.addStretch(1)
        return card

    def _send_card(self):
        card = Card("Отправить файлы в Telegram")
        card.body.addWidget(label("Файлы до 50 МБ уходят в ваш чат с ботом. Работает, даже когда бот остановлен.",
                                  "caption", wrap=True))
        row = QHBoxLayout()
        self.send_button = button("Выбрать файлы…", self.choose_files, symbol="folder")
        self.cancel_send = button("Отменить", self.cancel_sending, "ghost")
        self.cancel_send.hide()
        row.addWidget(self.send_button)
        row.addWidget(self.cancel_send)
        row.addStretch(1)
        card.body.addLayout(row)
        self.send_bar = QProgressBar()
        self.send_bar.setRange(0, 1000)
        self.send_bar.setTextVisible(False)
        self.send_bar.hide()
        card.body.addWidget(self.send_bar)
        self.send_status = label("", "caption", wrap=True)
        self.send_status.hide()
        card.body.addWidget(self.send_status)
        self.sender = None
        runtime = getattr(self.services, "runtime", None)
        if runtime is not None:
            from pulse_pc.services.telegram.file_sender import FileSender
            self.sender = FileSender(runtime, self)
            self.sender.progress.connect(self._send_progress)
            self.sender.finished.connect(self._send_finished)
        else:
            self.send_button.setEnabled(False)
        return card

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Отправить файлы в Telegram")
        if paths:
            self.send_files(paths)

    def send_files(self, paths):
        from pulse_pc.core.secrets import load_token
        admin = cfg.read_env(f"{self.config_dir}/.env").get("ADMIN_ID", "")
        try:
            self.sender.send(load_token(self.config_dir), admin, paths)
        except (ValueError, RuntimeError) as exc:
            self._show_send(str(exc))
            return
        self.send_button.setEnabled(False)
        self.cancel_send.show()
        self.cancel_send.setEnabled(True)
        self.send_bar.setValue(0)
        self.send_bar.show()
        self._show_send(f"Файлов: {len(paths)}. Подготовка…")

    def cancel_sending(self):
        if self.sender:
            self.cancel_send.setEnabled(False)
            self._show_send("Отмена отправки…")
            self.sender.cancel()

    def _send_progress(self, state):
        from pulse_pc.services.system.metrics import format_bytes
        from pulse_pc.services.telegram.file_sender import PHASES
        total = state.get("total_size") or 0
        self.send_bar.setValue(round(1000 * state.get("total_transferred", 0) / total) if total else 0)
        lines = [f"Отправлено {state.get('completed', 0)} из {state.get('total', 0)} · "
                 f"{format_bytes(state.get('total_transferred', 0))} из {format_bytes(total)}"]
        if state.get("speed"):
            lines[0] += f" · {format_bytes(state['speed'], True)}"
        for item in state.get("active", []):
            lines.append(f"{item['name']}: {format_bytes(item['transferred'])} / {format_bytes(item['size'])}")
        lines.append(PHASES.get(state.get("phase"), ""))
        self._show_send("\n".join(line for line in lines if line))

    def _send_finished(self, ok, text):
        self.send_button.setEnabled(True)
        self.cancel_send.hide()
        if ok:
            self.send_bar.setValue(1000)
        self._show_send(text)

    def _show_send(self, text):
        self.send_status.setText(text)
        self.send_status.setVisible(bool(text))

    def _log_card(self):
        card = Card("Журнал бота")
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(LOG_LINES)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setStyleSheet("border: none;")
        self.log_view.setMinimumHeight(180)
        card.body.addWidget(self.log_view, 1)
        card.add_action(button("Вся консоль", lambda: self._navigate("console"), "ghost", "chevron"))
        return card

    # ----- state -----
    def _changed(self, part, value):
        if part == "telegram":
            self._show(value)

    def _show(self, value):
        text, dot = STATUS.get(value.status, STATUS[st.UNKNOWN])
        self.status.set(text, dot)
        if value.status == st.RUNNING:
            detail = f"@{value.bot_name} принимает команды администратора." if value.bot_name else "Принимает команды."
        elif value.error:
            detail = value.error
        elif value.status == st.STOPPED:
            detail = "Команды из Telegram не выполняются. Телефон и остальные функции работают."
        else:
            detail = ""
        self.detail.setText(detail)
        active = value.status in ACTIVE
        self.toggle_button.setText("Остановить" if active else "Запустить")
        self.toggle_button.setIcon(icon("stop" if active else "play", tokens.ON_ACCENT))
        self.toggle_button.setEnabled(self.services is not None)
        self.restart_button.setEnabled(self.services is not None and active)
        self.updates_tile.set_value(value.updates, "с момента запуска")
        self.denied_tile.set_value(value.denied, "сообщения посторонних")
        self.failures_tile.set_value(value.failures, "при обработке команд")
        self.info["bot"].setText(f"@{value.bot_name}" if value.bot_name else "—")
        self.info["title"].setText(value.bot_title or "—")
        self.chat_button.setEnabled(bool(value.bot_name))
        values = cfg.read_env(f"{self.config_dir}/.env")
        self.info["admin"].setText(values.get("ADMIN_ID") or "не задан")
        from pulse_pc.core.secrets import load_token
        self.info["token"].setText(cfg.mask(load_token(self.config_dir)) or "не задан")
        self._tick()

    def _tick(self):
        value = self.store.state.telegram
        if value.status == st.RUNNING and value.since:
            self.uptime_tile.set_value(format_uptime(time.time() - value.since))
        else:
            self.uptime_tile.set_value("—")

    def _log(self, entry):
        if entry.source != "telegram":
            return
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(tokens.TEXT if entry.level != "INFO" else tokens.TEXT_2))
        if not self.log_view.document().isEmpty():
            cursor.insertText("\n")
        stamp = entry.time.strftime("%H:%M:%S") if entry.time.year > 1 else "—"
        cursor.insertText(f"{stamp}  {entry.level:<5}  {entry.text}", fmt)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    # ----- actions -----
    def toggle(self):
        if self.services is None:
            return
        if self.store.state.telegram.status in ACTIVE:
            self.services.telegram.stop()
        else:
            self.services.telegram.start()

    def restart(self):
        if self.services is not None:
            self.services.telegram.restart()

    def set_autostart(self, on):
        ui = self.ui_store.load()
        ui.telegram_autostart = on
        self.ui_store.save(ui)

    def open_chat(self):
        name = self.store.state.telegram.bot_name
        if name:
            QDesktopServices.openUrl(QUrl(f"https://t.me/{name}"))

    def open_options(self):
        from bot_options_ui import BotOptionsDialog
        from modules.keyboards import load_programs
        BotOptionsDialog(load_programs(), self).exec()

    def open_settings(self):
        self._navigate("settings")
        window = getattr(self.context, "window", None)
        page = window.pages.get("settings") if window is not None else None
        if page is not None:
            page.open_section("telegram")

    def _navigate(self, key):
        navigate = getattr(self.context, "navigate", None)
        if navigate:
            navigate(key)


def build(context):
    return TelegramScreen(context)
