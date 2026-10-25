"""Window chrome: sidebar navigation, title bar with quick search, animated page stack."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QCompleter, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from pulse_pc import APP_NAME, EDITION, __version__
from pulse_pc.ui.components.basic import button, label
from pulse_pc.ui.components.indicators import StatusLine
from pulse_pc.ui.theme import icon, tokens


class NavItem(QPushButton):
    def __init__(self, key, symbol, text):
        super().__init__(text)
        self.key = key
        self.symbol = symbol
        self.setProperty("kind", "nav")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setIconSize(QSize(18, 18))
        self.setAccessibleName(text)
        self._paint_icon(False)
        self.toggled.connect(self._paint_icon)

    def _paint_icon(self, checked):
        self.setIcon(icon(self.symbol, tokens.TEXT if checked else tokens.TEXT_2))


class Sidebar(QFrame):
    """Brand, one button per screen and a live status line at the bottom."""

    navigate = Signal(str)

    def __init__(self, screens, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(tokens.SIDEBAR_WIDTH)
        column = QVBoxLayout(self)
        column.setContentsMargins(tokens.SPACE_3, tokens.SPACE_4, tokens.SPACE_3, tokens.SPACE_4)
        column.setSpacing(2)

        brand = QHBoxLayout()
        brand.setContentsMargins(tokens.SPACE_2, 0, 0, tokens.SPACE_5)
        brand.setSpacing(tokens.SPACE_2)
        logo = QLabel()
        logo.setPixmap(icon("pulse", tokens.TEXT).pixmap(QSize(26, 26), self.devicePixelRatioF()))
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label(APP_NAME.upper(), "brand"))
        names.addWidget(label(EDITION, "edition"))
        brand.addLayout(names, 1)
        column.addLayout(brand)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.items = {}
        for screen in screens:
            item = NavItem(screen.key, screen.symbol, screen.title)
            item.clicked.connect(lambda _=False, key=screen.key: self.navigate.emit(key))
            self.group.addButton(item)
            self.items[screen.key] = item
            column.addWidget(item)
        column.addStretch(1)

        self.status = StatusLine("", "off", "caption")
        self.status.setContentsMargins(tokens.SPACE_2, 0, 0, 0)
        self.status.hide()  # shown once the service manager reports a real state (stage D)
        column.addWidget(self.status)
        version = label(f"{APP_NAME} v{__version__}", "caption")
        version.setContentsMargins(tokens.SPACE_2, 0, 0, 0)
        column.addWidget(version)

    def set_status(self, text, state):
        self.status.set(text, state)
        self.status.setVisible(bool(text))

    def select(self, key):
        item = self.items.get(key)
        if item and not item.isChecked():
            item.setChecked(True)


class TitleBar(QFrame):
    """Drag area with quick navigation search (Ctrl+K) and window buttons."""

    navigate = Signal(str)

    def __init__(self, window, screens):
        super().__init__(window)
        self.window = window
        self.setObjectName("titlebar")
        self.setFixedHeight(tokens.TITLEBAR_HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(tokens.SPACE_5, 0, tokens.SPACE_2, 0)
        row.setSpacing(tokens.SPACE_2)

        self.targets = {screen.title.casefold(): screen.key for screen in screens}
        for screen in screens:
            for word in screen.keywords:
                self.targets.setdefault(word.casefold(), screen.key)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Перейти к разделу…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search", tokens.TEXT_3), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setMaximumWidth(380)
        self.search.setAccessibleName("Быстрый переход")
        completer = QCompleter([screen.title for screen in screens], self.search)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(self._go)
        self.search.setCompleter(completer)
        self.search.returnPressed.connect(lambda: self._go(self.search.text()))
        row.addWidget(self.search, 1)
        hint = label("Ctrl K", "caption")
        row.addWidget(hint)
        row.addStretch(2)
        QShortcut(QKeySequence("Ctrl+K"), window, activated=self.focus_search)

        self.minimize = self._window_button("minimize", "Свернуть", window.showMinimized)
        self.maximize = self._window_button("maximize", "Развернуть", self.toggle_maximized)
        self.close_button = self._window_button("close", "Закрыть", window.close)
        self.close_button.setObjectName("closeWindow")
        for widget in (self.minimize, self.maximize, self.close_button):
            row.addWidget(widget)

    def _window_button(self, symbol, tip, callback):
        widget = button("", callback, "window", tooltip=tip)
        widget.setIcon(icon(symbol, tokens.TEXT_2))
        widget.setIconSize(QSize(16, 16))
        widget.setFixedSize(40, 32)
        widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return widget

    def focus_search(self):
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def _go(self, text):
        query = text.strip().casefold()
        if not query:
            return
        key = self.targets.get(query) or next((k for name, k in self.targets.items() if query in name), None)
        if key:
            self.navigate.emit(key)
            self.search.clear()
            self.search.clearFocus()

    def toggle_maximized(self):
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def sync_state(self):
        maximized = self.window.isMaximized()
        self.maximize.setIcon(icon("restore" if maximized else "maximize", tokens.TEXT_2))
        self.maximize.setToolTip("Восстановить" if maximized else "Развернуть")

    # Dragging the empty title area moves the window with native Windows snapping.
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window.windowHandle():
            self.window.windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class FadeStack(QStackedWidget):
    """Stacked pages with a short fade-in. Only the incoming page is animated, and the
    effect is removed afterwards so idle pages cost nothing."""

    def __init__(self, parent=None, animate=True):
        super().__init__(parent)
        self.animate = animate
        self._anim = None

    def show_page(self, widget):
        if widget is self.currentWidget():
            return
        self.setCurrentWidget(widget)
        if not self.animate:
            return
        if self._anim:
            self._anim.stop()
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        self._anim = QPropertyAnimation(effect, b"opacity", self, duration=tokens.ANIM_NORMAL,
                                        startValue=0.0, endValue=1.0, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        self._anim.start()


def page_container(content):
    """Scrollable page body with the standard margins."""
    from PySide6.QtWidgets import QScrollArea
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(tokens.SPACE_5, tokens.SPACE_2, tokens.SPACE_5, tokens.SPACE_5)
    layout.addWidget(content)
    scroll.setWidget(holder)
    return scroll
