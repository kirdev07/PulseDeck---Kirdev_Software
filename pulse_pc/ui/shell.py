"""Main window: frameless Material 3 shell with the navigation rail, title bar and lazily built screens."""
from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from pulse_pc import APP_NAME
from pulse_pc.ui.components import FadeStack, Sidebar, TitleBar
from pulse_pc.ui.screens.registry import SCREENS, pending_screen
from pulse_pc.ui.theme import tokens
from pulse_pc.ui.theme.icons import app_icon

EDGE = 6  # px of the window border that resizes it


def round_corners(window):
    """Windows 11 rounds the corners of a frameless window too when asked (DWM, the same
    radius as every other window). Windows 10 has no rounded windows: nothing happens."""
    import ctypes
    DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
    try:
        preference = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(window.winId())), DWMWA_WINDOW_CORNER_PREFERENCE,
                                                   ctypes.byref(preference), ctypes.sizeof(preference))
    except (AttributeError, OSError):
        pass


class Backdrop(QWidget):
    """The window background of «Оформление → Фон»: the surface colour plus a soft light of
    the accent from two corners («glow»), a fine dot grid («dots») or nothing («flat»).
    Pages are transparent, cards opaque, so the light shows between the cards."""

    def paintEvent(self, _):
        from PySide6.QtGui import QRadialGradient
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tokens.BG))
        w, h = self.width(), self.height()
        if tokens.BACKGROUND == "glow":
            strength = 0.16 if tokens.DARK else 0.11
            for cx, cy, radius, alpha in ((w, 0, max(w, h) * 0.62, strength), (0, h, max(w, h) * 0.5, strength * 0.6)):
                gradient = QRadialGradient(cx, cy, radius)
                light, clear = QColor(tokens.ACCENT), QColor(tokens.ACCENT)
                light.setAlphaF(alpha)
                clear.setAlphaF(0.0)
                gradient.setColorAt(0, light)
                gradient.setColorAt(1, clear)
                painter.fillRect(self.rect(), gradient)
        elif tokens.BACKGROUND == "dots":
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            dot = QColor(tokens.TEXT_2)
            dot.setAlphaF(0.16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot)
            step = 24
            for x in range(step // 2, w, step):
                for y in range(step // 2, h, step):
                    painter.drawEllipse(QPoint(x, y), 1, 1)


class MainWindow(QMainWindow):
    def __init__(self, screens=SCREENS, *, context=None, animate=True):
        super().__init__()
        if context is None:     # previews and tests: no services, every screen shows «Нет данных»
            from pulse_pc.core.context import AppContext
            from pulse_pc.core.state import StateStore
            context = AppContext(store=StateStore())
        self.context = context
        context.navigate = self.open
        context.window = self
        self.screens = {screen.key: screen for screen in screens}
        self.pages = {}
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(1040, 660)
        self.resize(1320, 820)

        root = Backdrop()
        root.setObjectName("root")
        root.setMouseTracking(True)
        root.installEventFilter(self)
        self.root = root
        outer = QHBoxLayout(root)
        outer.setContentsMargins(EDGE, EDGE, EDGE, EDGE)
        outer.setSpacing(0)
        self.sidebar = Sidebar(screens)
        self.sidebar.navigate.connect(self.open)
        outer.addWidget(self.sidebar)
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        self.titlebar = TitleBar(self, screens)
        self.titlebar.navigate.connect(self.open)
        main.addWidget(self.titlebar)
        self.stack = FadeStack(animate=animate)
        main.addWidget(self.stack, 1)
        outer.addLayout(main, 1)
        self.setCentralWidget(root)
        self.open(screens[0].key)

    def current_key(self):
        return next((key for key, page in self.pages.items() if page is self.stack.currentWidget()), None)

    def open(self, key):
        screen = self.screens.get(key)
        if not screen:
            return
        page = self.pages.get(key)
        if page is None:
            page = screen.factory(self.context) if screen.factory else pending_screen(screen)
            self.pages[key] = page
            self.stack.addWidget(page)
        self.stack.show_page(page)
        self.sidebar.select(key)

    def closeEvent(self, event):
        # With a tray icon the window only hides: Telegram and the phone server keep working.
        tray = getattr(self.context, "tray", None)
        if tray is not None:
            event.ignore()
            self.hide()
            if not getattr(self, "_tray_hint_shown", False):
                self._tray_hint_shown = True
                tray.notify("PulseDeck работает в фоне", "Откройте окно или выйдите через значок в трее.")
            return
        super().closeEvent(event)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    # ----- frameless window: rounded corners, border, resize edges -----
    def showEvent(self, event):
        super().showEvent(event)
        round_corners(self)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isMaximized():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(tokens.BORDER), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            self.titlebar.sync_state()
            margin = 0 if self.isMaximized() else EDGE
            self.root.layout().setContentsMargins(margin, margin, margin, margin)
        super().changeEvent(event)

    def _edges(self, pos: QPoint):
        if self.isMaximized():
            return Qt.Edge(0)
        edges = Qt.Edge(0)
        if pos.x() <= EDGE:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - EDGE:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= EDGE:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= self.height() - EDGE:
            edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, watched, event):
        if watched is self.root:
            if event.type() == QEvent.Type.MouseMove and not event.buttons():
                edges = self._edges(event.position().toPoint())
                horizontal = edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge)
                vertical = edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge)
                if horizontal and vertical:
                    diagonal = edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
                    shape = Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor
                elif horizontal:
                    shape = Qt.CursorShape.SizeHorCursor
                elif vertical:
                    shape = Qt.CursorShape.SizeVerCursor
                else:
                    shape = None
                if shape is None:
                    self.root.unsetCursor()
                else:
                    self.root.setCursor(shape)
            elif event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                edges = self._edges(event.position().toPoint())
                if edges and self.windowHandle():
                    self.windowHandle().startSystemResize(edges)
                    return True
            elif event.type() == QEvent.Type.Leave:
                self.root.unsetCursor()
        return super().eventFilter(watched, event)
