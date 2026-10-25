"""Custom-painted controls: status dot, toggle switch, sparkline and metric tile."""
from collections import deque

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget

from pulse_pc.ui.components.basic import UNAVAILABLE, Card, label, set_kind

LOADING = "…"
from pulse_pc.ui.theme import icon, tokens


class StatusDot(QWidget):
    """Monochrome state marker. The state is told by shape, so it works without colour:
    ok = filled, busy = filled + slow pulse, off = hollow grey, error = hollow with a cross."""

    STATES = ("ok", "busy", "off", "error")

    def __init__(self, state="off", size=10, parent=None):
        super().__init__(parent)
        self._state = state
        self._pulse = 1.0
        self._size = size
        self.setFixedSize(size + 4, size + 4)
        self._anim = QVariantAnimation(self, startValue=1.0, endValue=0.35, duration=900, loopCount=-1,
                                       easingCurve=QEasingCurve.Type.InOutSine)
        self._anim.valueChanged.connect(self._on_pulse)
        self.set_state(state)

    def state(self):
        return self._state

    def set_state(self, state):
        if state not in self.STATES:
            raise ValueError(f"Unknown state: {state}")
        self._state = state
        if state == "busy":
            self._anim.start()
        else:
            self._anim.stop()
            self._pulse = 1.0
        self.setAccessibleName({"ok": "Работает", "busy": "Подключение", "off": "Выключено", "error": "Ошибка"}[state])
        self.update()

    def _on_pulse(self, value):
        self._pulse = value
        self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(2, 2, self._size, self._size)
        if self._state in ("ok", "busy"):
            color = QColor(tokens.STATE_OK if self._state == "ok" else tokens.STATE_BUSY)
            color.setAlphaF(self._pulse)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(r)
        elif self._state == "off":
            painter.setPen(QPen(QColor(tokens.STATE_OFF), 1.5))
            painter.drawEllipse(r.adjusted(0.75, 0.75, -0.75, -0.75))
        else:
            painter.setPen(QPen(QColor(tokens.STATE_ERROR), 1.5))
            painter.drawEllipse(r.adjusted(0.75, 0.75, -0.75, -0.75))
            inset = self._size * 0.32
            painter.drawLine(QPointF(r.left() + inset, r.top() + inset), QPointF(r.right() - inset, r.bottom() - inset))
            painter.drawLine(QPointF(r.right() - inset, r.top() + inset), QPointF(r.left() + inset, r.bottom() - inset))


class StatusLine(QWidget):
    """Dot + text, e.g. «● Бот активен»."""

    def __init__(self, text="", state="off", kind="", parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_2)
        self.dot = StatusDot(state)
        self.text = label(text, kind)
        row.addWidget(self.dot)
        row.addWidget(self.text, 1)

    def set(self, text, state):
        self.text.setText(text)
        self.dot.set_state(state)


class Toggle(QAbstractButton):
    """Animated on/off switch; a drop-in for QCheckBox (checkable, toggled signal)."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._offset = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"offset", self, duration=tokens.ANIM_FAST,
                                        easingCurve=QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(36, 20)

    def _animate(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def get_offset(self):
        return self._offset

    def set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = track.height() / 2
        on = QColor(tokens.ACCENT)
        off = QColor(tokens.SURFACE_3)
        if not self.isEnabled():
            on = off = QColor(tokens.SURFACE_2)
        fill = QColor.fromRgbF(*(a + (b - a) * self._offset for a, b in zip(off.getRgbF()[:3], on.getRgbF()[:3])))
        painter.setPen(QPen(QColor(tokens.BORDER_FOCUS if self.hasFocus() else tokens.BORDER_STRONG), 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(track, radius, radius)
        knob = track.height() - 6
        x = track.left() + 3 + (track.width() - knob - 6) * self._offset
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens.ON_ACCENT if self._offset > 0.5 else tokens.TEXT_2)
                         if self.isEnabled() else QColor(tokens.TEXT_DISABLED))
        painter.drawEllipse(QRectF(x, track.top() + 3, knob, knob))


class Sparkline(QWidget):
    """Line chart of the latest samples. Draws nothing fake: with fewer than two
    real samples it stays empty. `None` samples break the line (gaps)."""

    def __init__(self, capacity=60, maximum=100.0, parent=None):
        super().__init__(parent)
        self.samples = deque(maxlen=capacity)
        self.maximum = maximum
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def append(self, value):
        self.samples.append(None if value is None else max(0.0, float(value)))
        self.update()

    def clear(self):
        self.samples.clear()
        self.update()

    def paintEvent(self, _):
        values = list(self.samples)
        if sum(v is not None for v in values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height() - 2
        top = max(self.maximum, max(v for v in values if v is not None)) or 1.0
        step = w / max(self.samples.maxlen - 1, 1)
        start = w - step * (len(values) - 1)
        segments, current = [], []
        for i, v in enumerate(values):
            if v is None:
                if current:
                    segments.append(current)
                current = []
            else:
                current.append(QPointF(start + i * step, 1 + h - h * v / top))
        if current:
            segments.append(current)
        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0, QColor(255, 255, 255, 22))
        gradient.setColorAt(1, QColor(255, 255, 255, 0))
        for points in segments:
            if len(points) < 2:
                continue
            line = QPainterPath(points[0])
            for p in points[1:]:
                line.lineTo(p)
            area = QPainterPath(line)
            area.lineTo(points[-1].x(), h + 1)
            area.lineTo(points[0].x(), h + 1)
            painter.fillPath(area, gradient)
            painter.setPen(QPen(QColor(tokens.TEXT), 1.4))
            painter.drawPath(line)


class StatTile(Card):
    """Metric card: icon + name, big value, detail line, thin bar and sparkline.
    `set_value(None)` shows «Недоступно» instead of a number."""

    def __init__(self, symbol, name, *, unit="%", history=True, parent=None):
        super().__init__(padding=tokens.SPACE_4, spacing=tokens.SPACE_2, parent=parent)
        self.unit = unit
        head = QHBoxLayout()
        head.setSpacing(tokens.SPACE_2)
        glyph = QLabel()
        glyph.setPixmap(icon(symbol, tokens.TEXT_2).pixmap(QSize(18, 18), self.devicePixelRatioF()))
        head.addWidget(glyph)
        self.name = label(name, "overline")
        head.addWidget(self.name)
        head.addStretch(1)
        self.body.addLayout(head)
        self.value = label(LOADING, "unavailable")   # until the first real reading arrives
        self.body.addWidget(self.value)
        self.detail = label("", "caption")
        self.detail.setMinimumHeight(self.detail.fontMetrics().height())  # keep tiles aligned when empty
        self.body.addWidget(self.detail)
        self.body.addStretch(1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.body.addWidget(self.bar)
        self.chart = Sparkline() if history else None
        if self.chart:
            self.chart.setFixedHeight(32)
            self.body.addWidget(self.chart)
        self.setAccessibleName(name)

    def set_name(self, name):
        self.name.setText(name)
        self.setAccessibleName(name)

    def set_value(self, value, detail="", fraction=None):
        """value: number or None; fraction: 0..1 for the bar (defaults to value/100 for %)."""
        if value is None:
            self.value.setText(UNAVAILABLE)
            set_kind(self.value, "unavailable")
            self.bar.hide()
            if self.chart:
                self.chart.append(None)
        else:
            self.value.setText(f"{value:.0f}{self.unit}" if isinstance(value, (int, float)) else str(value))
            set_kind(self.value, "value")
            numeric = isinstance(value, (int, float))
            if fraction is None and self.unit == "%" and numeric:
                fraction = value / 100
            if fraction is not None:
                self.bar.setValue(round(max(0.0, min(1.0, fraction)) * 1000))
                self.bar.show()
            else:
                self.bar.hide()
            if self.chart and isinstance(value, (int, float)):
                self.chart.append(value)
        self.detail.setText(detail)
