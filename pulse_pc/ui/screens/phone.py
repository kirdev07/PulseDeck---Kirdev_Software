"""Телефон: the Pulse Mobile server (status, addresses, start/stop), how to connect,
paired phones with revocation, and recent file transfers."""
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from modules import mobile_access
from pulse_pc.core import state as st
from pulse_pc.ui.components import Card, EmptyState, PageHeader, StatusLine, Toggle, button, divider, label, page_container
from pulse_pc.ui.theme import icon, tokens

# QR pairing is off for now: weak phone cameras could not read the code from a monitor.
QR_ENABLED = False

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
        grid.addWidget(PageHeader("phone", "Телефон", "PulseDesk и PulseDeck Panel на телефоне — по Wi-Fi или USB-кабелю."), 0, 0, 1, 2)
        grid.addWidget(self._server_card(), 1, 0)
        grid.addWidget(self._connect_card(), 1, 1)
        grid.addWidget(self._code_card(), 2, 1)
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
                "Установите на Android PulseDesk (управление) или PulseDeck Panel (второй экран).",
                "Подключите телефон к той же Wi-Fi-сети или кабелем с «Отладкой по USB».",
                "В приложении нажмите «Автопоиск в сети» — компьютер появится сам. Если нет, введите адрес слева.",
                "Нажмите здесь «Показать код», сверьте отпечаток и введите 6 цифр на телефоне."), 1):
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

    def _code_card(self):
        card = Card("Подключить по коду")
        card.body.addWidget(label("Защищённое подключение (TLS): отсканируйте QR-код в PulseDeck Panel или введите "
                                  "код на телефоне и сверьте отпечаток.", "caption", wrap=True))
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.hide()
        self._qr_code = None
        card.body.addWidget(self.qr)
        self.code_label = label("", "display")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.body.addWidget(self.code_label)
        self.code_detail = label("", "caption", wrap=True)
        self.code_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body.addWidget(self.code_detail)
        self.code_button = button("Показать код", self.start_code, "primary", "shield")
        card.body.addWidget(self.code_button)
        self.code_timer = QTimer(self, interval=1000, timeout=self._tick_code)
        self._tick_code()
        return card

    def start_code(self):
        if mobile_access.PAIRING.active():
            mobile_access.PAIRING.cancel()
        else:
            mobile_access.PAIRING.start()
            self.code_timer.start()
        self._tick_code()

    def _tick_code(self):
        from pulse_pc.services.local_api import tls
        left = mobile_access.PAIRING.remaining()
        state = self.store.state.phone
        if not state.tls_port:
            self.code_label.setText("")
            self.code_detail.setText("Защищённый сервер не запущен." if state.status == st.RUNNING else "")
            self.code_button.setEnabled(False)
            self.code_timer.stop()
            return
        self.code_button.setEnabled(True)
        if left:
            code = mobile_access.PAIRING.current()
            self.code_label.setText(f"{code[:3]} {code[3:]}")
            config_dir = getattr(getattr(self.services, "local_api", None), "config_dir", None)
            full = tls.fingerprint(config_dir) if config_dir else ""
            print_ = tls.short_fingerprint(full) if full else ""
            if QR_ENABLED and full and code != self._qr_code:   # draw once per code, not every second
                from pulse_pc.services.local_api import pairing_qr
                import socket
                image = QPixmap()
                image.loadFromData(pairing_qr.png(pairing_qr.payload(
                    socket.gethostname(), list(state.addresses), state.tls_port, full, code)))
                self.qr.setPixmap(image)
                self._qr_code = code
            self.qr.setVisible(QR_ENABLED and bool(full))
            self.code_detail.setText(f"Действует ещё {left} с · порт {state.tls_port}"
                                     + (f"\nОтпечаток: {print_}" if print_ else ""))
            self.code_button.setText("Отменить")
        else:
            self.code_timer.stop()
            self.qr.hide()
            self._qr_code = None
            self.code_label.setText("")
            self.code_detail.setText(f"Порт TLS {state.tls_port}. Код действует 2 минуты и один раз.")
            self.code_button.setText("Показать код")

    def _devices_card(self):
        card = Card("Подключённые устройства")
        self.devices_count = card.add_action(label("", "caption"))
        self.devices = QTableWidget(0, 5)
        self.devices.setHorizontalHeaderLabels(("Устройство", "Последняя связь", "Добавлено", "Доступ", ""))
        self.devices.verticalHeader().hide()
        self.devices.setShowGrid(False)
        self.devices.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.devices.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.devices.verticalHeader().setDefaultSectionSize(44)
        self.devices.setStyleSheet("QTableWidget { border: none; }")
        head = self.devices.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in (1, 2, 3, 4):
            head.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        card.body.addWidget(self.devices)
        self.devices_empty = EmptyState("phone", "Телефоны не подключены",
                                        "Следуйте шагам справа. Каждый телефон получает собственный ключ доступа.")
        card.body.addWidget(self.devices_empty)
        card.body.addStretch(1)
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
            self._tick_code()

    def _show(self, value):
        text, dot = STATUS.get(value.status, STATUS[st.UNKNOWN])
        self.status.set(text, dot)
        running = value.status == st.RUNNING
        if running:
            self.detail.setText("Телефоны в этой сети могут найти ПК и подключиться.")
        else:
            self.detail.setText(value.error or ("Телефон не сможет подключиться, пока сервер остановлен."
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
            access = QComboBox()
            access.addItem("Полный", mobile_access.ACCESS_FULL)
            access.addItem("Только просмотр", mobile_access.ACCESS_VIEW)
            access.setToolTip("«Только просмотр»: показатели и что играет, без управления, файлов и скриншотов.")
            access.setCurrentIndex(0 if device.get("access", mobile_access.ACCESS_FULL) == mobile_access.ACCESS_FULL else 1)
            access.currentIndexChanged.connect(
                lambda _=0, d=device, box=access: self.services.local_api.set_access(d["id"], box.currentData()))
            self.devices.setCellWidget(row, 3, access)
            revoke = button("Отозвать", lambda _=False, d=device: self.revoke(d), "ghost")
            self.devices.setCellWidget(row, 4, revoke)
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
