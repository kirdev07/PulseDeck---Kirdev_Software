"""Консоль: the application journal with source tabs, level filters, search, export and
an on-demand self-check."""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QGridLayout, QHBoxLayout, QScrollArea, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget,
)

import config
from pulse_pc.core.logbook import LEVELS, SOURCES, Entry, Logbook
from pulse_pc.services.system import diagnostics
from pulse_pc.ui.components import Card, PageHeader, StatusLine, Toggle, button, divider, label
from pulse_pc.ui.theme import icon, tokens

MAX_VIEW_LINES = 3000
LEVEL_COLORS = {"INFO": tokens.TEXT_2, "WARN": tokens.TEXT, "ERROR": tokens.ACCENT}
LEVEL_NAMES = {"INFO": "Инфо", "WARN": "Предупреждения", "ERROR": "Ошибки"}


class DiagnosticsRunner(QObject):
    finished = Signal(list)

    def run(self):
        def target():
            self.finished.emit(diagnostics.run_all(
                config.CONFIG_DIR, config.PROGRAMS_FILE_PATH, Path(config.CONFIG_DIR) / ".env"))
        threading.Thread(target=target, daemon=True, name="PulsePC-diagnostics").start()


class ConsoleScreen(QWidget):
    def __init__(self, context=None, logbook=None, parent=None):
        super().__init__(parent)
        self.book = logbook or getattr(context, "logbook", None) or Logbook()
        self.source = "all"
        self.levels = set(LEVELS)
        self.query = ""
        self.cleared_after = 0      # «Очистить окно» hides entries with seq <= this
        self.visible_count = 0

        column = QVBoxLayout(self)
        column.setContentsMargins(tokens.SPACE_5, tokens.SPACE_2, tokens.SPACE_5, tokens.SPACE_5)
        column.setSpacing(tokens.SPACE_4)
        column.addWidget(PageHeader("console", "Консоль", "Журнал событий PulseDeck, фильтры и диагностика."))
        body = QHBoxLayout()
        body.setSpacing(tokens.SPACE_4)
        body.addWidget(self._log_card(), 3)
        panel = QWidget()
        side = QVBoxLayout(panel)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(tokens.SPACE_4)
        side.addWidget(self._status_card())
        side.addWidget(self._diagnostics_card())
        side.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setFixedWidth(320)
        body.addWidget(scroll)
        column.addLayout(body, 1)

        self.diagnostics = DiagnosticsRunner(self)
        self.diagnostics.finished.connect(self._diagnostics_done)
        self.book.added.connect(self._on_entry)
        self.render()

    # ----- layout -----
    def _log_card(self):
        card = Card(padding=tokens.SPACE_3)
        tabs = QHBoxLayout()
        tabs.setSpacing(tokens.SPACE_1)
        self.source_group = QButtonGroup(self)
        for key, text in (("all", "Все"),) + tuple(SOURCES.items()):
            tab = button(text, kind="ghost")
            tab.setCheckable(True)
            tab.setChecked(key == self.source)
            tab.clicked.connect(lambda _=False, k=key: self.set_source(k))
            self.source_group.addButton(tab)
            tabs.addWidget(tab)
        tabs.addStretch(1)
        card.body.addLayout(tabs)

        tools = QHBoxLayout()
        tools.setSpacing(tokens.SPACE_1)
        self.level_buttons = {}
        for level in LEVELS:
            chip = button(LEVEL_NAMES[level], kind="ghost")
            chip.setCheckable(True)
            chip.setChecked(True)
            chip.toggled.connect(lambda on, lv=level: self.set_level(lv, on))
            self.level_buttons[level] = chip
            tools.addWidget(chip)
        tools.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Поиск по журналу…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search", tokens.TEXT_3), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self.set_query)
        tools.addWidget(self.search)
        card.body.addLayout(tools)

        self.view = QPlainTextEdit()
        self.view.setObjectName("log")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setMaximumBlockCount(MAX_VIEW_LINES)
        self.view.setAccessibleName("Журнал событий")
        self.view.setStyleSheet("border: none;")
        card.body.addWidget(self.view, 1)

        footer = QHBoxLayout()
        self.shown = label("", "caption")
        footer.addWidget(self.shown, 1)
        footer.addWidget(label("Автопрокрутка", "caption"))
        self.autoscroll = Toggle(True)
        self.autoscroll.setFixedSize(32, 18)
        footer.addWidget(self.autoscroll)
        card.body.addLayout(footer)
        return card

    def _status_card(self):
        card = Card("Журнал")
        self.stat_labels = {}
        for key, name in (("ERROR", "Ошибок за сеанс"), ("WARN", "Предупреждений"), ("total", "Записей в памяти")):
            row = QHBoxLayout()
            row.addWidget(label(name, "muted"), 1)
            value = label("0")
            row.addWidget(value)
            self.stat_labels[key] = value
            card.body.addLayout(row)
        card.body.addWidget(divider())
        grid = QGridLayout()
        grid.setSpacing(tokens.SPACE_2)
        for index, (text, handler) in enumerate((("Экспорт…", self.export), ("Копировать", self.copy),
                                                 ("Очистить окно", self.clear_view), ("Папка", self.open_folder))):
            grid.addWidget(button(text, handler), index // 2, index % 2)
        card.body.addLayout(grid)
        card.body.addWidget(label("Очистка окна не удаляет историю на диске.", "caption", wrap=True))
        return card

    def _diagnostics_card(self):
        card = Card("Диагностика")
        card.body.addWidget(label("Проверка настроек, связи с Telegram, портов для телефона и компонентов.",
                                  "caption", wrap=True))
        self.diagnose_button = button("Запустить проверку", self.run_diagnostics, "primary", "refresh")
        card.body.addWidget(self.diagnose_button)
        self.results = QVBoxLayout()
        self.results.setSpacing(tokens.SPACE_2)
        card.body.addLayout(self.results)
        card.body.addStretch(1)
        return card

    # ----- filtering and rendering -----
    def matches(self, entry: Entry):
        return ((self.source == "all" or entry.source == self.source) and entry.level in self.levels
                and (not self.query or self.query in entry.text.casefold()))

    def set_source(self, key):
        self.source = key
        self.render()

    def set_level(self, level, on):
        (self.levels.add if on else self.levels.discard)(level)
        self.render()

    def set_query(self, text):
        self.query = text.strip().casefold()
        self.render()

    def render(self):
        visible = [e for e in self.book.snapshot() if e.seq > self.cleared_after and self.matches(e)][-MAX_VIEW_LINES:]
        self.view.clear()
        cursor = self.view.textCursor()
        cursor.beginEditBlock()
        for entry in visible:
            self._write(cursor, entry)
        cursor.endEditBlock()
        self.visible_count = len(visible)
        self._scroll()
        self._update_stats()

    def _write(self, cursor, entry):
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(LEVEL_COLORS[entry.level]))
        if entry.level == "ERROR":
            fmt.setFontWeight(600)
        if not self.view.document().isEmpty():
            cursor.insertText("\n")
        stamp = entry.time.strftime("%d.%m %H:%M:%S") if entry.time.year > 1 else "—"
        cursor.insertText(f"{stamp}  {entry.level:<5}  {entry.text}", fmt)

    def _on_entry(self, entry):
        if self.matches(entry):
            self._write(self.view.textCursor(), entry)
            self.visible_count = min(self.visible_count + 1, MAX_VIEW_LINES)
            self._scroll()
        self._update_stats()

    def _scroll(self):
        if self.autoscroll.isChecked():
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _update_stats(self):
        self.stat_labels["ERROR"].setText(str(self.book.counts["ERROR"]))
        self.stat_labels["WARN"].setText(str(self.book.counts["WARN"]))
        self.stat_labels["total"].setText(str(len(self.book.entries)))
        self.shown.setText(f"Показано: {self.visible_count}")

    # ----- actions -----
    def visible_text(self):
        return self.view.toPlainText()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт журнала", "pulse-pc-log.txt", "Текст (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(self.visible_text() + "\n", encoding="utf-8")
            self.book.add(f"Журнал экспортирован: {path}")
        except OSError as exc:
            self.book.add(f"Не удалось экспортировать журнал: {exc}", "ERROR")

    def copy(self):
        QGuiApplication.clipboard().setText(self.visible_text())

    def clear_view(self):
        entries = self.book.snapshot()
        self.cleared_after = entries[-1].seq if entries else 0
        self.render()

    def open_folder(self):
        folder = self.book.path.parent if self.book.path else Path(config.CONFIG_DIR) / "logs"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def run_diagnostics(self):
        self.diagnose_button.setEnabled(False)
        self.diagnose_button.setText("Проверяю…")
        self.book.add("Диагностика запущена.")
        self.diagnostics.run()

    def _diagnostics_done(self, results):
        while self.results.count():
            item = self.results.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for level, title, detail in results:
            line = StatusLine(title, {"INFO": "ok", "WARN": "off", "ERROR": "error"}[level])
            line.setToolTip(detail)
            self.results.addWidget(line)
            if level != "INFO":
                hint = label(detail, "caption", wrap=True)
                self.results.addWidget(hint)
            self.book.add(f"Диагностика · {title}: {detail}", level)
        problems = sum(level != "INFO" for level, _, _ in results)
        self.book.add("Диагностика завершена: " + (f"замечаний — {problems}." if problems else "проблем не найдено."),
                      "WARN" if problems else "INFO")
        self.diagnose_button.setEnabled(True)
        self.diagnose_button.setText("Запустить снова")


def build(context):
    return ConsoleScreen(context)
