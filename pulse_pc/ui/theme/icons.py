"""Monochrome line icons drawn from inline SVG (no icon fonts, no network).

Icons are rendered at the device pixel ratio of the request, so they stay sharp at
any Windows scaling level.
"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from pulse_pc.ui.theme import tokens

# 24x24 viewBox, stroke-based paths.
_PATHS = {
    "pulse": '<path d="M2 12h4l3-8 4 16 3-8h6"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5.5 9v11.5h13V9"/><path d="M10 20.5v-6h4v6"/>',
    "system": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "apps": '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/>'
            '<rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    "phone": '<rect x="6.5" y="2.5" width="11" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    "telegram": '<path d="M21.5 3.5 2.5 11l6.5 2.5 2.5 7 3.5-4.5 5 3.5z"/><path d="m9 13.5 12.5-10"/>',
    "console": '<path d="m4 6 6 6-6 6"/><path d="M12.5 18H20"/>',
    "music": '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    "folder": '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1'
                'M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"/>'
           '<path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>',
    "ram": '<rect x="2.5" y="7" width="19" height="10" rx="1.5"/><path d="M6.5 10.5v3M10.5 10.5v3M14.5 10.5v3M18 10.5v3M5 17v2.5M19 17v2.5"/>',
    "gpu": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="9" cy="12" r="3"/><path d="M15 10h3M15 14h3"/>',
    "disk": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 14h18"/><circle cx="17" cy="17" r=".6"/>',
    "network": '<path d="M2.5 9a14 14 0 0 1 19 0"/><path d="M5.5 12.5a9.5 9.5 0 0 1 13 0"/><path d="M8.7 16a5 5 0 0 1 6.6 0"/><circle cx="12" cy="19.5" r=".8"/>',
    "power": '<path d="M12 3v8"/><path d="M6.4 6.6a8 8 0 1 0 11.2 0"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 3.5V8h4.5"/><path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/><path d="M20 20.5V16h-4.5"/>',
    "play": '<path d="M7 4.5v15l12-7.5z" fill="currentColor"/>',
    "pause": '<rect x="6" y="4.5" width="4" height="15" rx="1" fill="currentColor"/><rect x="14" y="4.5" width="4" height="15" rx="1" fill="currentColor"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor"/>',
    "prev": '<path d="M19 5v14l-10-7z" fill="currentColor"/><path d="M6 5v14"/>',
    "next": '<path d="M5 5v14l10-7z" fill="currentColor"/><path d="M18 5v14"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "chevron": '<path d="m9.5 6 6 6-6 6"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "shield": '<path d="M12 2.5 4 5.5v6c0 5 3.4 8.6 8 10 4.6-1.4 8-5 8-10v-6z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.1"/>',
    "minimize": '<path d="M6 12h12"/>',
    "maximize": '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    "restore": '<rect x="5" y="9" width="10" height="10" rx="1"/><path d="M9 9V6a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-3"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
}


def names():
    return sorted(_PATHS)


@lru_cache(maxsize=256)
def _renderer(name, color):
    body = _PATHS.get(name, _PATHS["pulse"]).replace("currentColor", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    return QSvgRenderer(QByteArray(svg.encode()))


class _SvgEngine(QIconEngine):
    """Paints the SVG at whatever size and pixel ratio Qt asks for."""

    def __init__(self, name, color, disabled):
        super().__init__()
        self.name, self.color, self.disabled = name, color, disabled

    def paint(self, painter, rect, mode, state):
        color = self.disabled if mode == QIcon.Mode.Disabled else self.color
        _renderer(self.name, color).render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        image = QPixmap(size)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint(painter, image.rect(), mode, state)
        painter.end()
        return image

    def scaledPixmap(self, size, mode, state, scale):
        image = self.pixmap(QSize(round(size.width() * scale), round(size.height() * scale)), mode, state)
        image.setDevicePixelRatio(scale)
        return image

    def clone(self):
        return _SvgEngine(self.name, self.color, self.disabled)


def icon(name, color=tokens.TEXT_2):
    return QIcon(_SvgEngine(name, color, tokens.TEXT_DISABLED))


def pixmap(name, size, color=tokens.TEXT_2, ratio=1.0):
    return icon(name, color).pixmap(QSize(size, size), ratio)
