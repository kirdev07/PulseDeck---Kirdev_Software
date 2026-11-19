"""Настройки → Веб-панель: switch it on, view only or music control, port, the link and its
QR code for the phone, a new access key."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QVBoxLayout

from pulse_pc.core import state as st
from pulse_pc.services.web_panel import settings as web_settings
from pulse_pc.ui.components import Card, StatusLine, Toggle, button, divider, label

QR_SIZE = 220
STATUS = {st.RUNNING: ("Веб-панель работает", "ok"), st.STARTING: ("Запуск…", "busy"),
          st.STOPPED: ("Веб-панель выключена", "off"), st.ERROR: ("Ошибка", "error"), st.UNKNOWN: ("—", "off")}


class WebPanelSection:
    def __init__(self, screen, layout):
        self.screen = screen
        self.config_dir = screen.config_dir
        context = screen.context
        self.store = getattr(context, "store", None)
        self.service = getattr(getattr(context, "services", None), "web_panel", None)
        data = web_settings.load(self.config_dir)

        card = Card("Веб-панель")
        card.body.addWidget(label(
            "Экран PulseDeck Panel в браузере любого телефона — iPhone или Android, без установки приложения: "
            "часы, нагрузка CPU, RAM и GPU, сеть, диски и что сейчас играет. Работает только в домашней сети.",
            "muted", wrap=True))
        card.body.addWidget(divider())
        self.enabled = Toggle(data["enabled"])
        self.enabled.toggled.connect(lambda on: self._set(enabled=on))
        card.body.addLayout(_row("Включить веб-панель", "Открывается по ссылке или QR-коду ниже.", self.enabled))
        card.body.addWidget(divider())
        self.control = Toggle(data["control"])
        self.control.toggled.connect(lambda on: self._set(control=on))
        card.body.addLayout(_row("Управление музыкой из браузера",
                                 "Пауза, следующий и предыдущий трек. Выключено — только просмотр. "
                                 "Ничего другого на ПК из браузера сделать нельзя.", self.control))
        card.body.addWidget(divider())
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(data["port"])
        self.port.setFixedWidth(110)
        port_row = QHBoxLayout()
        port_row.addWidget(self.port)
        port_row.addWidget(button("Применить", self._apply_port, "ghost"))
        port_box = _row("Порт", f"По умолчанию {web_settings.DEFAULT_PORT}. Меняйте, если он занят другой программой.",
                        None)
        port_box.addLayout(port_row)
        card.body.addLayout(port_box)
        layout.addWidget(card)

        link_card = Card("Подключение телефона")
        self.status = StatusLine("", "off", "")
        link_card.body.addWidget(self.status)
        self.detail = label("", "caption", wrap=True)
        link_card.body.addWidget(self.detail)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.hide()
        link_card.body.addWidget(self.qr)
        self.link = label("", "mono", wrap=True)
        self.link.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        link_card.body.addWidget(self.link)
        actions = QHBoxLayout()
        self.copy_button = button("Копировать ссылку", self._copy, symbol="check")
        self.open_button = button("Открыть здесь", self._open, "ghost", "external")
        self.key_button = button("Новый ключ", self._new_key, "ghost", "refresh")
        for widget in (self.copy_button, self.open_button, self.key_button):
            actions.addWidget(widget)
        actions.addStretch(1)
        link_card.body.addLayout(actions)
        self.message = label("", "caption", wrap=True)
        link_card.body.addWidget(self.message)
        link_card.body.addWidget(label(
            "Наведите камеру телефона на QR-код — откроется браузер. На iPhone в Safari: «Поделиться» → "
            "«На экран Домой», и панель откроется как приложение. Ссылку храните как пароль: по ней видно, что "
            "происходит на ПК. «Новый ключ» сразу отключает все открытые панели и старые ссылки.",
            "caption", wrap=True))
        layout.addWidget(link_card)

        self._qr_link = None
        if self.store is not None:
            self.store.changed.connect(self._changed)
        self.refresh()

    # ----- state -----
    def _changed(self, part, _value):
        if part == "web_panel":
            self.refresh()

    def links(self):
        state = self.store.state.web_panel if self.store is not None else None
        if not state or state.status != st.RUNNING or not state.port:
            return []
        key = web_settings.load(self.config_dir)["key"]
        return [web_settings.link(address, state.port, key) for address in state.addresses]

    def refresh(self):
        state = self.store.state.web_panel if self.store is not None else None
        status = state.status if state else st.UNKNOWN
        text, dot = STATUS.get(status, STATUS[st.UNKNOWN])
        self.status.set(text, dot)
        links = self.links()
        if state and state.error:
            self.detail.setText(state.error)
        elif links:
            watching = f" Сейчас открыта на {state.clients} устр." if state.clients else ""
            self.detail.setText(f"Порт {state.port}. Телефон должен быть в той же сети Wi-Fi, что и ПК.{watching}")
        elif status == st.RUNNING:
            self.detail.setText("Сеть не найдена: подключите ПК к Wi-Fi или по кабелю к роутеру.")
        else:
            self.detail.setText("Включите веб-панель выше, чтобы получить ссылку.")
        main = links[0] if links else ""
        self.link.setText("\n".join(links))
        for widget in (self.copy_button, self.open_button):
            widget.setEnabled(bool(main))
        if main != self._qr_link:
            self._qr_link = main
            if main:
                from pulse_pc.services.local_api import pairing_qr
                image = QPixmap()
                image.loadFromData(pairing_qr.png(main))
                ratio = self.qr.devicePixelRatioF()
                side = round(QR_SIZE * ratio)
                image = image.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.FastTransformation)
                image.setDevicePixelRatio(ratio)
                self.qr.setPixmap(image)
        self.qr.setVisible(bool(main))

    # ----- actions -----
    def _set(self, **changes):
        try:
            web_settings.update(self.config_dir, **changes)
        except OSError as exc:
            self.message.setText(f"Не удалось сохранить: {exc}")
            return
        self.message.setText("Сохранено.")
        if self.service is not None:
            self.service.restart()

    def _apply_port(self):
        self._set(port=self.port.value())

    def _new_key(self):
        self._qr_link = None
        self._set(key=web_settings.new_key())
        self.message.setText("Создан новый ключ: старые ссылки и открытые панели отключены. Отсканируйте QR-код заново.")

    def _copy(self):
        links = self.links()
        if links:
            QGuiApplication.clipboard().setText(links[0])
            self.message.setText("Ссылка скопирована. Отправьте её себе на телефон.")

    def _open(self):
        links = self.links()
        if links:
            QDesktopServices.openUrl(QUrl(links[0]))


def _row(title, description, control):
    """Title and caption on the left, the control (if any) on the right — as setting_row in settings.py."""
    row = QHBoxLayout()
    column = QVBoxLayout()
    column.setSpacing(2)
    column.addWidget(label(title))
    if description:
        column.addWidget(label(description, "caption", wrap=True))
    row.addLayout(column, 1)
    if control is not None:
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return row
