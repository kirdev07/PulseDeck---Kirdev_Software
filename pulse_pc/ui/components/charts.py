"""Multi-series load chart. Series are told apart by brightness and dash pattern, so the
chart stays readable in a strictly monochrome theme."""
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from pulse_pc.ui.theme import tokens

STYLES = (
    (tokens.TEXT, Qt.PenStyle.SolidLine, 1.6),
    ("#8C8C8C", Qt.PenStyle.SolidLine, 1.4),
    ("#8C8C8C", Qt.PenStyle.DashLine, 1.3),
    ("#5A5A5A", Qt.PenStyle.DotLine, 1.3),
)


class LoadChart(QWidget):
    """Percent values per second; shows the last `window` seconds of at most `capacity`."""

    def __init__(self, series, capacity=900, window=60, parent=None):
        super().__init__(parent)
        self.names = list(series)
        self.data = {name: deque(maxlen=capacity) for name in self.names}
        self.window = window
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    @staticmethod
    def style(index):
        return STYLES[index % len(STYLES)]

    def set_window(self, seconds):
        self.window = seconds
        self.update()

    def append(self, values):
        """values: {name: percent or None}; missing names count as None (gap)."""
        for name in self.names:
            value = values.get(name)
            self.data[name].append(None if value is None else max(0.0, min(100.0, float(value))))
        self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPointSizeF(tokens.FS_CAPTION)
        painter.setFont(font)
        axis = 40
        plot = QRectF(0, 6, self.width() - axis, self.height() - 12)
        for level in (0, 50, 100):
            y = plot.bottom() - plot.height() * level / 100
            painter.setPen(QPen(QColor(tokens.BORDER), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(tokens.TEXT_3))
            painter.drawText(QRectF(plot.right() + 6, y - 8, axis - 6, 16),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{level}%")
        step = plot.width() / max(self.window - 1, 1)
        for index, name in enumerate(self.names):
            values = list(self.data[name])[-self.window:]
            color, dash, width = self.style(index)
            pen = QPen(QColor(color), width, dash)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            start = plot.right() - step * (len(values) - 1)
            path, drawing = QPainterPath(), False
            for i, value in enumerate(values):
                if value is None:
                    drawing = False
                    continue
                point = QPointF(start + i * step, plot.bottom() - plot.height() * value / 100)
                if drawing:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
                    drawing = True
            painter.drawPath(path)


class LegendMark(QWidget):
    """Short line sample matching a LoadChart series."""

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self.setFixedSize(18, 10)

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color, dash, width = LoadChart.style(self.index)
        painter.setPen(QPen(QColor(color), width + 0.4, dash))
        painter.drawLine(QPointF(1, 5), QPointF(17, 5))
