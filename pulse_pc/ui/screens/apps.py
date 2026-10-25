"""Приложения: the configured programs with live status, search, filters and actions."""
import os
import threading
from pathlib import Path

from PySide6.QtCore import QFileInfo, QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDialog, QDialogButtonBox, QFileDialog, QFileIconProvider, QFormLayout,
    QHBoxLayout, QHeaderView, QLineEdit, QMenu, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import config
from pulse_pc.services.system import programs as svc
from pulse_pc.services.system.metrics import format_bytes
from pulse_pc.ui.components import Card, EmptyState, PageHeader, StatusDot, StatTile, button, divider, label
from pulse_pc.ui.theme import icon, tokens

FILTERS = (("all", "Все"), ("running", "Запущенные"), ("stopped", "Остановленные"))
COLUMNS = ("Название", "Статус", "CPU", "RAM")


def file_exists(program):
    return Path(os.path.expandvars(program["path"])).is_file()


class UsageMonitor(QObject):
    """Samples program usage every `interval` s in a daemon thread."""

    updated = Signal(dict)

    def __init__(self, interval=2.0, parent=None):
        super().__init__(parent)
        self.interval = interval
        self.programs = []
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            if not self._stop.is_set():
                return
            self._thread.join(2)    # a stopped worker exits within one sample
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._run, name="PulsePC-apps", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def refresh_now(self):
        self._wake.set()

    def _run(self):
        sampler = svc.UsageSampler()
        while not self._stop.is_set():
            try:
                self.updated.emit(sampler.sample(list(self.programs)))
            except Exception:  # noqa: BLE001 - next tick retries
                pass
            self._wake.wait(self.interval)
            self._wake.clear()


class Worker(QObject):
    """Runs one blocking action off the UI thread and reports (ok, message)."""

    done = Signal(bool, str)

    def run(self, function, success):
        def target():
            try:
                function()
                self.done.emit(True, success)
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self.done.emit(False, str(exc))
        threading.Thread(target=target, daemon=True, name="PulsePC-action").start()


class ProgramDialog(QDialog):
    def __init__(self, parent=None, program=None):
        super().__init__(parent)
        self.setWindowTitle("Изменить программу" if program else "Новая программа")
        self.setMinimumWidth(520)
        column = QVBoxLayout(self)
        column.setContentsMargins(tokens.SPACE_5, tokens.SPACE_5, tokens.SPACE_5, tokens.SPACE_5)
        column.setSpacing(tokens.SPACE_4)
        column.addWidget(label(self.windowTitle(), "title"))
        form = QFormLayout()
        form.setSpacing(tokens.SPACE_3)
        self.name = QLineEdit(program["name"] if program else "")
        self.name.setMaxLength(40)
        self.name.setPlaceholderText("Например, OBS Studio")
        self.path = QLineEdit(program["path"] if program else "")
        self.path.setPlaceholderText(r"C:\Program Files\…\program.exe")
        browse = button("Обзор…", self.browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)
        self.description = QLineEdit(str(program.get("description", "")) if program else "")
        self.description.setMaxLength(130)
        self.description.setPlaceholderText("Необязательно")
        form.addRow("Название", self.name)
        form.addRow("Путь", path_row)
        form.addRow("Описание", self.description)
        column.addLayout(form)
        self.error = label("", "muted", wrap=True)
        self.error.hide()
        column.addWidget(self.error)
        buttons = QDialogButtonBox()
        save = buttons.addButton("Сохранить", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("kind", "primary")
        buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите программу", "",
                                              "Программы (*.exe *.lnk *.bat *.cmd);;Все файлы (*)")
        if path:
            self.path.setText(os.path.normpath(path))
            if not self.name.text().strip():
                self.name.setText(Path(path).stem[:40])

    def values(self):
        return self.name.text(), self.path.text(), self.description.text()

    def show_error(self, text):
        self.error.setText(text)
        self.error.show()


class AppsScreen(QWidget):
    def __init__(self, context=None, store=None, parent=None):
        super().__init__(parent)
        self.store = store or svc.ProgramStore(config.PROGRAMS_FILE_PATH)
        self.programs = []
        self.usage = {}
        self.file_error = ""
        self.filter = "all"
        self.icons = QFileIconProvider()

        column = QVBoxLayout(self)
        column.setContentsMargins(tokens.SPACE_5, tokens.SPACE_2, tokens.SPACE_5, tokens.SPACE_5)
        column.setSpacing(tokens.SPACE_4)
        header = PageHeader("apps", "Приложения", "Программы для быстрого запуска с ПК, из Telegram и с телефона.")
        self.add_button = button("Добавить программу", self.add_program, "primary", "plus")
        header.actions.addWidget(self.add_button)
        column.addWidget(header)

        stats = QHBoxLayout()
        stats.setSpacing(tokens.SPACE_3)
        self.total_tile = StatTile("apps", "ПРОГРАММ", unit="", history=False)
        self.running_tile = StatTile("play", "ЗАПУЩЕНО", unit="", history=False)
        self.cpu_tile = StatTile("cpu", "НАГРУЗКА CPU", history=False)
        self.ram_tile = StatTile("ram", "ПАМЯТЬ", unit="", history=False)
        for tile in (self.total_tile, self.running_tile, self.cpu_tile, self.ram_tile):
            stats.addWidget(tile, 1)
        column.addLayout(stats)

        body = QHBoxLayout()
        body.setSpacing(tokens.SPACE_4)
        body.addWidget(self._list_card(), 3)
        body.addWidget(self._details_card(), 2)
        column.addLayout(body, 1)
        self.message = label("", "muted", wrap=True)
        column.addWidget(self.message)

        self.worker = Worker(self)
        self.worker.done.connect(self._action_done)
        self.monitor = UsageMonitor(parent=self)
        self.monitor.updated.connect(self._apply_usage)
        self.reload()

    # Sampling processes costs CPU; do it only while the screen is visible.
    def showEvent(self, event):
        self.monitor.start()
        self.monitor.refresh_now()
        super().showEvent(event)

    def hideEvent(self, event):
        self.monitor.stop()
        super().hideEvent(event)

    # ----- layout -----
    def _list_card(self):
        card = Card(padding=tokens.SPACE_3)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(tokens.SPACE_1)
        self.filter_group = QButtonGroup(self)
        for key, text in FILTERS:
            choice = button(text, kind="ghost")
            choice.setCheckable(True)
            choice.setChecked(key == self.filter)
            choice.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            self.filter_group.addButton(choice)
            toolbar.addWidget(choice)
        toolbar.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Поиск программ…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search", tokens.TEXT_3), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.apply_filter)
        toolbar.addWidget(self.search)
        card.body.addLayout(toolbar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setIconSize(QSize(20, 20))
        self.table.setStyleSheet("QTableWidget { border: none; } QTableWidget::item { padding: 6px; }")
        self.table.verticalHeader().setDefaultSectionSize(40)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in (1, 2, 3):
            head.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.table.itemDoubleClicked.connect(lambda _: self.launch_selected())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        card.body.addWidget(self.table, 1)
        self.empty = EmptyState("apps", "Пока нет программ",
                                "Добавьте программу — она появится здесь, в меню Telegram и в Pulse Mobile.")
        card.body.addWidget(self.empty, 1)
        return card

    def _details_card(self):
        card = Card()
        self.details_title = label("", "heading", wrap=True)
        self.details_status = StatusDot("off")
        top = QHBoxLayout()
        top.addWidget(self.details_status)
        top.addWidget(self.details_title, 1)
        card.body.addLayout(top)
        self.details_description = label("", "muted", wrap=True)
        card.body.addWidget(self.details_description)
        self.details_rows = {}
        for key, name in (("path", "Путь"), ("process", "Процесс"), ("usage", "Ресурсы")):
            card.body.addWidget(label(name.upper(), "overline"))
            value = label("", "mono", wrap=True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.details_rows[key] = value
            card.body.addWidget(value)
        card.body.addWidget(divider())
        actions = QHBoxLayout()
        self.launch_button = button("Запустить", self.launch_selected, "primary", "play")
        self.close_button = button("Завершить", self.close_selected, symbol="stop")
        actions.addWidget(self.launch_button)
        actions.addWidget(self.close_button)
        card.body.addLayout(actions)
        more = QHBoxLayout()
        self.edit_button = button("Изменить", self.edit_selected, "ghost")
        self.folder_button = button("Папка", self.open_folder, "ghost", "folder")
        self.up_button = button("", lambda: self.move_selected(-1), "ghost", tooltip="Выше в списке")
        self.up_button.setText("↑")
        self.down_button = button("", lambda: self.move_selected(1), "ghost", tooltip="Ниже в списке")
        self.down_button.setText("↓")
        self.delete_button = button("Удалить", self.delete_selected, "ghost")
        for widget in (self.edit_button, self.folder_button, self.up_button, self.down_button):
            more.addWidget(widget)
        more.addStretch(1)
        more.addWidget(self.delete_button)
        card.body.addLayout(more)
        card.body.addStretch(1)
        self.details_card = card
        return card

    # ----- data -----
    def reload(self, select_id=None):
        try:
            self.programs = self.store.load()
            self.file_error = ""
        except svc.ProgramsFileError as exc:
            self.programs, self.file_error = [], str(exc)
        self.monitor.programs = list(self.programs)
        self.monitor.refresh_now()
        selected = select_id or self.selected_id()
        self.table.setRowCount(0)
        for program in self.programs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = QTableWidgetItem(program["name"])
            name.setData(Qt.ItemDataRole.UserRole, program["id"])
            name.setToolTip(program.get("description") or program["path"])
            target = Path(os.path.expandvars(program["path"]))
            name.setIcon(self.icons.icon(QFileInfo(str(target))) if target.exists() else icon("apps", tokens.TEXT_3))
            self.table.setItem(row, 0, name)
            for col in (1, 2, 3):
                self.table.setItem(row, col, QTableWidgetItem(""))
            self._paint_usage(row, program)
        has = bool(self.programs)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        self.add_button.setEnabled(not self.file_error and len(self.programs) < svc.MAX_PROGRAMS)
        self.add_button.setToolTip("" if len(self.programs) < svc.MAX_PROGRAMS else
                                   f"Достигнут предел: {svc.MAX_PROGRAMS} программ")
        if self.file_error:
            self.show_message(self.file_error + " Исправьте файл или удалите его, затем откройте экран снова.")
        self._update_stats()
        self.apply_filter()
        if selected:
            self.select(selected)
        if not self.selected_id() and has:
            self.table.selectRow(next((r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)), 0))
        self.show_details()

    def program(self, program_id):
        return next((p for p in self.programs if p["id"] == program_id), None)

    def selected_id(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None

    def select(self, program_id):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == program_id:
                self.table.selectRow(row)
                return

    def _apply_usage(self, usage):
        self.usage = usage
        for row in range(self.table.rowCount()):
            program = self.program(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            if program:
                self._paint_usage(row, program)
        self._update_stats()
        self.apply_filter()
        self.show_details()

    def _paint_usage(self, row, program):
        usage = self.usage.get(program["id"])
        if usage is None:
            texts = ("…", "", "")
        elif not usage.running and not file_exists(program):
            texts = ("Файл не найден", "—", "—")
        elif usage.running:
            texts = ("Запущена" + (f" · {usage.count}" if usage.count > 1 else ""), f"{usage.cpu:.1f}%",
                     format_bytes(usage.memory))
        elif not svc.process_names(program):
            texts = ("Неизвестно", "—", "—")
        else:
            texts = ("Остановлена", "—", "—")
        for col, text in zip((1, 2, 3), texts):
            item = self.table.item(row, col)
            item.setText(text)
            item.setForeground(Qt.GlobalColor.white if usage and usage.running else Qt.GlobalColor.gray)

    def _update_stats(self):
        self.total_tile.set_value(f"{len(self.programs)} / {svc.MAX_PROGRAMS}", "в списке")
        known = [self.usage[p["id"]] for p in self.programs if p["id"] in self.usage]
        if len(known) < len(self.programs):     # first sample has not arrived yet
            for tile in (self.running_tile, self.cpu_tile, self.ram_tile):
                tile.set_value("…")
            return
        running = [u for u in known if u.running]
        self.running_tile.set_value(len(running), "из списка")
        self.cpu_tile.set_value(sum(u.cpu for u in running), "запущенных программ")
        self.ram_tile.set_value(format_bytes(sum(u.memory for u in running)), "запущенных программ")

    def set_filter(self, key):
        self.filter = key
        self.apply_filter()

    def apply_filter(self):
        query = self.search.text().strip().casefold()
        for row in range(self.table.rowCount()):
            program = self.program(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            usage = self.usage.get(program["id"])
            running = bool(usage and usage.running)
            visible = (self.filter == "all" or (self.filter == "running") == running) and (
                not query or query in program["name"].casefold() or query in program["path"].casefold())
            self.table.setRowHidden(row, not visible)

    def show_details(self):
        program = self.program(self.selected_id())
        self.details_card.setVisible(program is not None)
        if not program:
            return
        usage = self.usage.get(program["id"])
        running = bool(usage and usage.running)
        names = svc.process_names(program)
        self.details_title.setText(program["name"])
        self.details_status.set_state("ok" if running else "off")
        self.details_description.setText(program.get("description", ""))
        self.details_description.setVisible(bool(program.get("description")))
        self.details_rows["path"].setText(program["path"])
        self.details_rows["process"].setText(min(names, key=len) if names else
                                             "Не определён (ярлык или скрипт без .exe)")
        if usage is None:
            self.details_rows["usage"].setText("Проверяю…")
        elif running:
            self.details_rows["usage"].setText(f"CPU {usage.cpu:.1f}% · RAM {format_bytes(usage.memory)}"
                                               f" · процессов: {usage.count}")
        else:
            self.details_rows["usage"].setText("Не запущена" if names else "Недоступно")
        self.close_button.setEnabled(running)
        self.launch_button.setEnabled(file_exists(program))
        self.launch_button.setToolTip("" if file_exists(program) else "Файл не найден. Измените путь.")
        index = self.programs.index(program)
        self.up_button.setEnabled(index > 0)
        self.down_button.setEnabled(index < len(self.programs) - 1)

    # ----- actions -----
    def show_message(self, text):
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _action_done(self, ok, text):
        self.show_message(text)
        self.monitor.refresh_now()

    def launch_selected(self):
        program = self.program(self.selected_id())
        if program:
            self.worker.run(lambda: svc.launch(program), f"Запущено: {program['name']}")

    def close_selected(self):
        program = self.program(self.selected_id())
        if not program:
            return
        answer = QMessageBox.question(self, "Завершить программу",
                                      f"Завершить «{program['name']}»? Несохранённые данные в ней могут потеряться.")
        if answer == QMessageBox.StandardButton.Yes:
            self.worker.run(lambda: svc.close(program), f"Завершено: {program['name']}")

    def add_program(self):
        self._edit(None)

    def edit_selected(self):
        program = self.program(self.selected_id())
        if program:
            self._edit(program)

    def _edit(self, program):
        dialog = ProgramDialog(self, program)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                saved = (self.store.update(program["id"], *dialog.values()) if program
                         else self.store.add(*dialog.values()))
            except (ValueError, OSError, svc.ProgramsFileError) as exc:
                dialog.show_error(str(exc))
                continue
            self.reload(saved["id"])
            self.show_message(f"Сохранено: {saved['name']}. Список уже доступен в Telegram и Pulse Mobile.")
            return

    def delete_selected(self):
        program = self.program(self.selected_id())
        if not program:
            return
        answer = QMessageBox.question(self, "Удалить программу",
                                      f"Убрать «{program['name']}» из списка? Сама программа на ПК не удаляется.")
        if answer == QMessageBox.StandardButton.Yes:
            self._mutate(lambda: self.store.remove(program["id"]), f"Удалено из списка: {program['name']}")

    def move_selected(self, offset):
        program_id = self.selected_id()
        if program_id:
            self._mutate(lambda: self.store.move(program_id, offset), "", program_id)

    def _mutate(self, change, text, select_id=None):
        try:
            change()
        except (ValueError, OSError, svc.ProgramsFileError) as exc:
            self.show_message(str(exc))
            return
        self.reload(select_id)
        self.show_message(text)

    def open_folder(self):
        program = self.program(self.selected_id())
        if program:
            folder = Path(os.path.expandvars(program["path"])).parent
            if folder.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
            else:
                self.show_message("Папка не найдена.")

    def _context_menu(self, position):
        if not self.selected_id():
            return
        menu = QMenu(self)
        for text, handler in (("Запустить", self.launch_selected), ("Завершить", self.close_selected),
                              ("Изменить", self.edit_selected), ("Открыть папку", self.open_folder),
                              ("Удалить из списка", self.delete_selected)):
            action = QAction(text, menu)
            action.triggered.connect(handler)
            menu.addAction(action)
        menu.exec(self.table.viewport().mapToGlobal(position))


def build(context):
    return AppsScreen(context)
