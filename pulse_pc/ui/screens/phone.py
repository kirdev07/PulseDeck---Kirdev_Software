"""Телефон: the Pulse Mobile server (status, addresses, start/stop), how to connect,
paired phones with revocation, and recent file transfers."""
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QMessageBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from modules import mobile_access
from pulse_pc.core import state as st
from pulse_pc.ui.components import Card, EmptyState, PageHeader, StatusLine, Toggle, button, divider, label, page_container
from pulse_pc.ui.theme import icon, tokens

ONLINE_SECONDS = 120        # the app polls the PC every few seconds while open
STATUS = {st.UNKNOWN: ("Нет данных", "off"), st.STOPPED: ("Сервер остановлен", "off"),
          st.STARTING: ("Запуск…", "busy"), st.RUNNING: ("Сервер активен", "ok"), st.ERROR: ("Сервер не запущен", "error")}
DIRECTIONS = {"incoming": "С телефона", "outgoing": "На телефон / в Telegram"}
RESULTS = {"sent": "Отправлен", "received": "Получен", "error": "Ошибка", "cancelled": "Отменён"}


def ago(iso, now=None):
    """'2026-10-25T16:24:01' -> 'сейчас' / '5 мин назад' / '25.10 16:24'; '' -> 'ещё не подключался'."""
    if not iso:
        return "ещё не подключался"
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    seconds = ((now or datetime.now()) - moment).total_seconds()
    if seconds < 90:
        return "только что"
    if seconds < 3600:
        return f"{int(seconds // 60)} мин назад"
    if seconds < 86400 and moment.date() == (now or datetime.now()).date():
        return f"сегодня в {moment:%H:%M}"
    return f"{moment:%d.%m.%Y %H:%M}"


def is_online(iso, now=None):
    try:
        return ((now or datetime.now()) - datetime.fromisoformat(iso)).total_seconds() < ONLINE_SECONDS
    except (TypeError, ValueError):
        return False


class PhoneScreen(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.store = context.store
        self.services = getattr(context, "services", None)

        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(tokens.SPACE_4)
        grid.setVerticalSpacing(tokens.SPACE_4)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.addWidget(PageHeader("phone", "Телефон", "Pulse Mobile управляет этим ПК по домашней сети."), 0, 0, 1, 2)
        grid.addWidget(self._server_card(), 1, 0)
        grid.addWidget(self._connect_card(), 1, 1, 2, 1)
        grid.addWidget(self._devices_card(), 2, 0)
        grid.addWidget(self._history_card(), 3, 0, 1, 2)
        grid.setRowStretch(4, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page_container(content))

        self.store.changed.connect(self._changed)
        self.timer = QTimer(self, interval=30_000, timeout=self._refresh_times)   # «N мин назад» stays current
        self.timer.start()
        self._show(self.store.state.phone)
        self.load_history()

    # ----- layout -----
    def _server_card(self):
        card = Card("Локальный сервер")
        self.status = StatusLine("", "off", "heading")
        card.body.addWidget(self.status)
        self.detail = label("", "muted", wrap=True)
        card.body.addWidget(self.detail)
        self.address_rows = QVBoxLayout()
        self.address_rows.setSpacing(tokens.SPACE_1)
        card.body.addLayout(self.address_rows)
        actions = QHBoxLayout()
        self.toggle_button = button("Запустить", self.toggle, "primary", "play")
        self.restart_button = button("Перезапустить", self.restart, symbol="refresh")
        actions.addWidget(self.toggle_button)
        actions.addWidget(self.restart_button)
        actions.addStretch(1)
        card.body.addLayout(actions)
        card.body.addWidget(label("Сервер доступен только устройствам вашей локальной сети. Не пробрасывайте этот "
                                  "порт на роутере.", "caption", wrap=True))
        return card

    def _connect_card(self):
        card = Card("Как подключить телефон")
        for number, text in enumerate((
                "Установите Pulse Mobile на Android.",
                "Подключите телефон к той же Wi-Fi-сети, что и этот ПК.",
                "В приложении нажмите «Найти ПК» — компьютер появится сам. Если нет, введите адрес слева вручную.",
                "Подтвердите запрос в окне, которое появится на этом ПК."), 1):
            row = QHBoxLayout()
            row.setSpacing(tokens.SPACE_3)
            badge = label(str(number), "caption")
            badge.setFixedSize(22, 22)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(f"border: 1px solid {tokens.BORDER_STRONG}; border-radius: 11px;")
            row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label(text, "", wrap=True), 1)
            card.body.addLayout(row)
        card.body.addWidget(divider())
        self.pairing = Toggle(mobile_access.load()["allow_pairing"])
        self.pairing.toggled.connect(self.set_pairing)
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.addWidget(label("Разрешить новые подключения"))
        text.addWidget(label("Выключите, когда все ваши телефоны подключены.", "caption", wrap=True))
        row.addLayout(text, 1)
        row.addWidget(self.pairing)
        card.body.addLayout(row)
        card.body.addStretch(1)
        return card

    def _devices_card(self):
        card = Card("Подключённые устройства")
        self.devices_count = card.add_action(label("", "caption"))
        self.devices = QTableWidget(0, 4)
        self.devices.setHorizontalHeaderLabels(("Устройство", "Последняя связь", "Добавлено", ""))
        self.devices.verticalHeader().hide()
        self.devices.setShowGrid(False)
        self.devices.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.devices.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.devices.verticalHeader().setDefaultSectionSize(44)
        self.devices.setStyleSheet("QTableWidget { border: none; }")
        head = self.devices.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in (1, 2, 3):
            head.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        card.body.addWidget(self.devices)
        self.devices_empty = EmptyState("phone", "Телефоны не подключены",
                                        "Следуйте шагам справа. Каждый телефон получает собственный ключ доступа.")
        card.body.addWidget(self.devices_empty)
        return card

    def _history_card(self):
        card = Card("Передача файлов")
        card.add_action(button("Обновить", self.load_history, "ghost", "refresh"))
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(("Файл", "Направление", "Результат", "Время"))
        self.history.verticalHeader().hide()
        self.history.setShowGrid(False)
        self.history.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.history.setStyleSheet("QTableWidget { border: none; }")
        head = self.history.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in (1, 2, 3):
            head.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.history.setMinimumHeight(200)
        card.body.addWidget(self.history)
        self.history_note = label("", "caption", wrap=True)
        card.body.addWidget(self.history_note)
        return card

    # ----- state -----
    def _changed(self, part, value):
        if part == "phone":
            self._show(value)

    def _show(self, value):
        text, dot = STATUS.get(value.status, STATUS[st.UNKNOWN])
        self.status.set(text, dot)
        running = value.status == st.RUNNING
        if running:
            self.detail.setText("Телефоны в этой сети могут найти ПК и подключиться.")
        else:
            self.detail.setText(value.error or ("Pulse Mobile не сможет подключиться, пока сервер остановлен."
                                                if value.status == st.STOPPED else ""))
        while self.address_rows.count():
            widget = self.address_rows.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        for address in value.addresses if running else ():
            line = label(f"{address}:{value.port}", "mono")
            line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.address_rows.addWidget(line)
        if running:
            self.address_rows.addWidget(label(f"Поиск ПК: UDP {mobile_access.DISCOVERY_PORT}", "caption"))
        active = value.status in (st.RUNNING, st.STARTING)
        self.toggle_button.setText("Остановить" if active else "Запустить")
        self.toggle_button.setIcon(icon("stop" if active else "play", tokens.ON_ACCENT))
        self.toggle_button.setEnabled(self.services is not None)
        self.restart_button.setEnabled(self.services is not None and running)
        self._show_devices(value.devices)

    def _show_devices(self, devices):
        self.devices.setRowCount(0)
        for device in devices:
            row = self.devices.rowCount()
            self.devices.insertRow(row)
            online = is_online(device.get("last_seen"))
            name = QTableWidgetItem(("● " if online else "○ ") + (device.get("name") or "Телефон"))
            name.setToolTip("На связи" if online else "Не на связи")
            self.devices.setItem(row, 0, name)
            seen = QTableWidgetItem(ago(device.get("last_seen")))
            seen.setData(Qt.ItemDataRole.UserRole, device.get("last_seen"))
            self.devices.setItem(row, 1, seen)
            added = device.get("added", "")
            self.devices.setItem(row, 2, QTableWidgetItem(added.replace("T", " ")[:16] if added else "—"))
            revoke = button("Отозвать", lambda _=False, d=device: self.revoke(d), "ghost")
            self.devices.setCellWidget(row, 3, revoke)
        has = bool(devices)
        self.devices.setVisible(has)
        self.devices_empty.setVisible(not has)
        self.devices.setFixedHeight(36 + 44 * len(devices))
        self.devices_count.setText(f"{len(devices)} из {mobile_access.MAX_DEVICES}" if has else "")

    def _refresh_times(self):
        self._show_devices(self.store.state.phone.devices)

    def load_history(self):
        from modules.transfer_history import load_history
        try:
            items = list(reversed(load_history()))[:30]
            self.history_note.setText("" if items else "Передач ещё не было.")
        except (OSError, ValueError) as exc:
            items = []
            self.history_note.setText(f"История недоступна: {exc}")
        self.history_note.setVisible(bool(self.history_note.text()))
        self.history.setRowCount(0)
        for item in items:
            row = self.history.rowCount()
            self.history.insertRow(row)
            name = QTableWidgetItem(item["name"])
            name.setToolTip(item["path"] + (f"\n{item['error']}" if item.get("error") else ""))
            self.history.setItem(row, 0, name)
            self.history.setItem(row, 1, QTableWidgetItem(DIRECTIONS.get(item["direction"], item["direction"])))
            self.history.setItem(row, 2, QTableWidgetItem(RESULTS.get(item["status"], item["status"])))
            self.history.setItem(row, 3, QTableWidgetItem(ago(item["time"])))
        self.history.setVisible(bool(items))

    # ----- actions -----
    def toggle(self):
        if self.services is None:
            return
        if self.store.state.phone.status in (st.RUNNING, st.STARTING):
            self.services.local_api.stop()
        else:
            if not mobile_access.load()["enabled"]:
                mobile_access.set_option("enabled", True)   # starting by hand turns the setting back on
            self.services.local_api.start()

    def restart(self):
        if self.services is not None:
            self.services.local_api.restart()

    def set_pairing(self, on):
        mobile_access.set_option("allow_pairing", on)

    def revoke(self, device):
        name = device.get("name") or "Телефон"
        answer = QMessageBox.question(self, "Отозвать доступ",
                                      f"Отключить «{name}»? Чтобы снова управлять ПК, телефону придётся подключиться "
                                      "заново с подтверждением на этом компьютере.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.services is not None:
            self.services.local_api.revoke(device["id"])
        else:
            mobile_access.remove_device(device["id"])


def build(context):
    return PhoneScreen(context)
