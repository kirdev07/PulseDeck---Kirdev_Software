"""Window chrome: sidebar navigation, title bar with quick search, animated page stack."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QCompleter, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit,
    QStackedWidget, QVBoxLayout, QWidget,
)

from pulse_pc import APP_NAME, __version__
from pulse_pc.ui.components.basic import button, label
from pulse_pc.ui.components.indicators import StatusLine
from pulse_pc.ui.theme import icon, tokens
from pulse_pc.ui.theme.icons import logo_pixmap


RAIL_NAMES = {"telegram": "Бот"}     # short labels under the rail icons


class NavItem(QAbstractButton):
    """Navigation rail destination (Material 3): the icon in a 56 × 32 «pill» that lights up
    with the secondary container when selected, the label below."""

    def __init__(self, key, symbol, text):
        super().__init__()
        self.key = key
        self.symbol = symbol
        self.setText(RAIL_NAMES.get(key, text))
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(tokens.SIDEBAR_WIDTH - 8, 60)
        self._hover = False

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pill = QRectF((self.width() - 56) / 2, 4, 56, 32)
        checked = self.isChecked()
        if checked or self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.SECONDARY_CONTAINER if checked else tokens.SURFACE_HOVER))
            painter.drawRoundedRect(pill, 16, 16)
        ink = tokens.ON_SECONDARY_CONTAINER if checked else tokens.TEXT_2
        side = 24
        glyph = icon(self.symbol, ink).pixmap(QSize(side, side), self.devicePixelRatioF())
        painter.drawPixmap(round(pill.center().x() - side / 2), round(pill.center().y() - side / 2), glyph)
        font = QFont(self.font())
        font.setPointSizeF(tokens.FS_CAPTION + 0.5)
        font.setWeight(QFont.Weight.DemiBold if checked else QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QColor(tokens.TEXT if checked else tokens.TEXT_2))
        painter.drawText(QRectF(0, pill.bottom() + 3, self.width(), 18),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.text())


class Fab(QAbstractButton):
    """Floating action button of the rail: 56 × 56, primary container, a plus."""

    def __init__(self, tooltip):
        super().__init__()
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(56, 56)
        self._hover = False

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor(tokens.PRIMARY_CONTAINER)
        if self._hover or self.isDown():
            over = QColor(tokens.ON_PRIMARY_CONTAINER)
            amount = 0.12 if self.isDown() else 0.08
            fill = QColor.fromRgbF(*(a + (b - a) * amount for a, b in zip(fill.getRgbF()[:3], over.getRgbF()[:3])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(self.rect()), 16, 16)
        glyph = icon("plus", tokens.ON_PRIMARY_CONTAINER).pixmap(QSize(24, 24), self.devicePixelRatioF())
        painter.drawPixmap(16, 16, glyph)


class Sidebar(QFrame):
    """Navigation rail (Material 3): logo, the main action, one destination per screen,
    a live status dot and the version at the bottom."""

    navigate = Signal(str)

    def __init__(self, screens, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(tokens.SIDEBAR_WIDTH)
        column = QVBoxLayout(self)
        column.setContentsMargins(4, tokens.SPACE_4, 4, tokens.SPACE_4)
        column.setSpacing(4)
        center = Qt.AlignmentFlag.AlignHCenter

        logo = QLabel()
        logo.setPixmap(logo_pixmap(44, self.devicePixelRatioF(), themed=True))
        logo.setToolTip(f"{APP_NAME} {__version__}")
        column.addWidget(logo, 0, center)
        column.addSpacing(tokens.SPACE_3)
        self.fab = Fab("Подключить телефон")
        self.fab.clicked.connect(lambda: self.navigate.emit("phone"))
        column.addWidget(self.fab, 0, center)
        column.addSpacing(tokens.SPACE_4)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.items = {}
        for screen in screens:
            item = NavItem(screen.key, screen.symbol, screen.title)
            item.clicked.connect(lambda _=False, key=screen.key: self.navigate.emit(key))
            self.group.addButton(item)
            self.items[screen.key] = item
            column.addWidget(item, 0, center)
        column.addStretch(1)

        self.status = StatusLine("", "off", "rail")
        self.status.text.hide()         # the rail is narrow: the text is the dot's tooltip
        self.status.hide()  # shown once the service manager reports a real state (stage D)
        column.addWidget(self.status, 0, center)
        version = label(f"v{__version__}", "rail")
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(version, 0, center)

    def set_status(self, text, state):
        self.status.set(text, state)
        self.status.setToolTip(text)
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
