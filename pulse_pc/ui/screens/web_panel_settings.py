"""Настройки → Веб-панель: switch it on, port, the address. Browsers are paired like the
apps — «Телефон» → «Подключить по коду» → «Браузер» — and listed among the devices there."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QSpinBox, QVBoxLayout

from pulse_pc.core import state as st
from pulse_pc.services.web_panel import settings as web_settings
from pulse_pc.ui.components import Card, StatusLine, Toggle, button, divider, label

STATUS = {st.RUNNING: ("Веб-панель работает", "ok"), st.STARTING: ("Запуск…", "busy"),
          st.STOPPED: ("Веб-панель выключена", "off"), st.ERROR: ("Ошибка", "error"), st.UNKNOWN: ("—", "off")}


class WebPanelSection:
    def __init__(self, screen, layout):
        self.screen = screen
        self.config_dir = screen.config_dir
        context = screen.context
        self.context = context
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
        card.body.addLayout(_row("Включить веб-панель",
                                 "Обычный HTTP без шифрования (браузеры телефонов не доверяют домашним сертификатам), "
                                 "поэтому по умолчанию выключена.", self.enabled))
        card.body.addWidget(divider())
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(data["port"])
        self.port.setFixedWidth(110)
        port_row = _row("Порт", f"По умолчанию {web_settings.DEFAULT_PORT}. Меняйте, если он занят другой программой.",
                        None)
        port_row.addWidget(self.port)
        port_row.addWidget(button("Применить", lambda: self._set(port=self.port.value()), "ghost"))
        card.body.addLayout(port_row)
        layout.addWidget(card)

        connect = Card("Подключение телефона")
        self.status = StatusLine("", "off", "")
        connect.body.addWidget(self.status)
        self.detail = label("", "caption", wrap=True)
        connect.body.addWidget(self.detail)
        self.address = label("", "mono", wrap=True)
        self.address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        connect.body.addWidget(self.address)
        actions = QHBoxLayout()
        self.pair_button = button("Подключить телефон…", self._pair, "primary", "phone")
        self.open_button = button("Открыть здесь", self._open, "ghost", "external")
        actions.addWidget(self.pair_button)
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        connect.body.addLayout(actions)
        self.message = label("", "caption", wrap=True)
        connect.body.addWidget(self.message)
        connect.body.addWidget(label(
            "Подключение как у приложений: «Телефон» → «Показать код» → «Браузер», затем QR-код камерой телефона. "
            "Телефон запоминается и появляется в «Подключённых устройствах»: «Доступ» — только просмотр или "
            "управление музыкой, «Отозвать» сразу закрывает панель. На iPhone в Safari: «Поделиться» → "
            "«На экран Домой» — панель откроется как приложение.", "caption", wrap=True))
        layout.addWidget(connect)

        if self.store is not None:
            self.store.changed.connect(self._changed)
        self.refresh()

    def _changed(self, part, _value):
        if part == "web_panel":
            self.refresh()

    def _addresses(self):
        state = self.store.state.web_panel if self.store is not None else None
        if not state or state.status != st.RUNNING or not state.port:
            return []
        return [web_settings.address(host, state.port) for host in state.addresses]

    def refresh(self):
        state = self.store.state.web_panel if self.store is not None else None
        status = state.status if state else st.UNKNOWN
        text, dot = STATUS.get(status, STATUS[st.UNKNOWN])
        self.status.set(text, dot)
        addresses = self._addresses()
        if state and state.error:
            self.detail.setText(state.error)
        elif addresses:
            watching = f" Сейчас открыта на {state.clients} устр." if state.clients else ""
            self.detail.setText(f"Телефон должен быть в той же сети Wi-Fi, что и ПК.{watching}")
        elif status == st.RUNNING:
            self.detail.setText("Сеть не найдена: подключите ПК к Wi-Fi или кабелем к роутеру.")
        else:
            self.detail.setText("Включите веб-панель выше.")
        self.address.setText("\n".join(addresses))
        self.address.setVisible(bool(addresses))
        self.pair_button.setEnabled(bool(addresses))
        self.open_button.setEnabled(bool(addresses))

    def _set(self, **changes):
        try:
            web_settings.update(self.config_dir, **changes)
        except OSError as exc:
            self.message.setText(f"Не удалось сохранить: {exc}")
            return
        self.message.setText("Сохранено.")
        if self.service is not None:
            self.service.restart()

    def _pair(self):
        """Open «Телефон» with «Браузер» chosen and a fresh code on screen."""
        navigate = getattr(self.context, "navigate", None)
        window = getattr(self.context, "window", None)
        if navigate:
            navigate("phone")
        page = window.pages.get("phone") if window is not None else None
        if page is not None and hasattr(page, "pair_browser"):
            page.pair_browser()

    def _open(self):
        addresses = self._addresses()
        if addresses:
            QDesktopServices.openUrl(QUrl(addresses[0]))


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
