"""Small building blocks shared by every screen."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from pulse_pc.ui.theme import icon, tokens

UNAVAILABLE = "Недоступно"


def label(text="", kind="", wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if kind:
        widget.setProperty("kind", kind)
    widget.setWordWrap(wrap)
    if wrap:
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return widget


def set_kind(widget, kind):
    """Change a styling variant at runtime (Qt only re-reads properties on repolish)."""
    if widget.property("kind") != kind:
        widget.setProperty("kind", kind)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def button(text, callback=None, kind="", symbol=None, tooltip=""):
    widget = QPushButton(text)
    if kind:
        widget.setProperty("kind", kind)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if symbol:
        widget.setIcon(icon(symbol, tokens.ON_ACCENT if kind == "primary" else tokens.TEXT_2))
        widget.setIconSize(QSize(16, 16))
    if tooltip:
        widget.setToolTip(tooltip)
        widget.setAccessibleName(tooltip)
    if callback:
        widget.clicked.connect(callback)
    return widget


def icon_button(symbol, callback=None, tooltip="", size=32):
    widget = button("", callback, "ghost", symbol, tooltip)
    widget.setFixedSize(size, size)
    widget.setStyleSheet("padding: 0;")
    return widget


def divider():
    line = QFrame()
    line.setProperty("kind", "divider")
    return line


class Card(QFrame):
    """Rounded panel with an optional header row (title + trailing widgets)."""

    def __init__(self, title="", *, kind="card", padding=tokens.SPACE_4, spacing=tokens.SPACE_3, parent=None):
        super().__init__(parent)
        self.setProperty("kind", kind)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(padding, padding, padding, padding)
        outer.setSpacing(spacing)
        self.header = None
        if title:
            self.header = QHBoxLayout()
            self.header.setSpacing(tokens.SPACE_2)
            self.title = label(title, "heading")
            self.header.addWidget(self.title)
            self.header.addStretch(1)
            outer.addLayout(self.header)
        self.body = outer

    def add_action(self, widget):
        if self.header is not None:
            self.header.addWidget(widget)
        return widget


class PageHeader(QWidget):
    """Icon, title and one-line description at the top of every screen."""

    def __init__(self, symbol, title, subtitle="", parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_3)
        glyph = QLabel()
        glyph.setPixmap(icon(symbol, tokens.TEXT).pixmap(QSize(28, 28), self.devicePixelRatioF()))
        glyph.setFixedSize(32, 32)
        row.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = label(title, "title")
        self.subtitle = label(subtitle, "muted")
        text.addWidget(self.title)
        if subtitle:
            text.addWidget(self.subtitle)
        row.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(tokens.SPACE_2)
        row.addLayout(self.actions)


class EmptyState(QWidget):
    """Honest placeholder for content that is not available yet."""

    def __init__(self, symbol, title, text="", parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.setSpacing(tokens.SPACE_2)
        glyph = QLabel()
        glyph.setPixmap(icon(symbol, tokens.TEXT_3).pixmap(QSize(40, 40), self.devicePixelRatioF()))
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(glyph)
        heading = label(title, "heading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(heading)
        if text:
            body = label(text, "muted", wrap=True)
            body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            body.setFixedWidth(420)
            column.addWidget(body, 0, Qt.AlignmentFlag.AlignHCenter)
