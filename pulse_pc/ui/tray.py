"""System tray icon: the services keep running while the window is closed."""
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from pulse_pc import APP_NAME
from pulse_pc.core import state as st
from pulse_pc.ui.theme import icon, tokens

TELEGRAM_TEXT = {st.RUNNING: "работает", st.STARTING: "запуск…", st.RECONNECTING: "переподключение…",
                 st.ERROR: "ошибка", st.STOPPED: "остановлен", st.UNKNOWN: "—"}


class Tray:
    def __init__(self, window, context):
        self.window = window
        self.context = context
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self.icon = QSystemTrayIcon(icon("pulse", tokens.TEXT), window)
        self.icon.setToolTip(APP_NAME)
        menu = QMenu()
        self.status_action = QAction("", menu, enabled=False)
        menu.addAction(self.status_action)
        menu.addSeparator()
        menu.addAction(QAction("Открыть PulseDeck", menu, triggered=self.show_window))
        self.telegram_action = QAction("", menu, triggered=self.toggle_telegram)
        menu.addAction(self.telegram_action)
        menu.addSeparator()
        menu.addAction(QAction("Выход", menu, triggered=QApplication.instance().quit))
        self.menu = menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)
        if context.store is not None:
            context.store.changed.connect(lambda part, _value: self._update() if part in ("telegram", "phone") else None)
        self._update()
        if self.available:
            self.icon.show()

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def toggle_telegram(self):
        services = self.context.services
        if services is None:
            return
        running = self.context.store.state.telegram.status in (st.RUNNING, st.STARTING, st.RECONNECTING)
        (services.telegram.stop if running else services.telegram.start)()

    def _update(self):
        state = self.context.store.state if self.context.store is not None else None
        if state is None:
            return
        phone = "работает" if state.phone.status == st.RUNNING else "выключен"
        text = f"Telegram: {TELEGRAM_TEXT.get(state.telegram.status, '—')} · Телефон: {phone}"
        self.status_action.setText(text)
        self.icon.setToolTip(f"{APP_NAME}\n{text}")
        running = state.telegram.status in (st.RUNNING, st.STARTING, st.RECONNECTING)
        self.telegram_action.setText("Остановить Telegram-бота" if running else "Запустить Telegram-бота")

    def notify(self, title, text):
        if self.available:
            self.icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 4000)

    def hide(self):
        self.icon.hide()
