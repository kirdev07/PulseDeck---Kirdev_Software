"""Main window: frameless AMOLED shell with sidebar, title bar and lazily built screens."""
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from pulse_pc import APP_NAME
from pulse_pc.ui.components import FadeStack, Sidebar, TitleBar
from pulse_pc.ui.screens.registry import SCREENS, pending_screen
from pulse_pc.ui.theme import icon, tokens

EDGE = 6  # px of the window border that resizes it


class MainWindow(QMainWindow):
    def __init__(self, screens=SCREENS, *, context=None, animate=True):
        super().__init__()
        self.context = context
        if context is not None:
            context.navigate = self.open
            context.window = self
        self.screens = {screen.key: screen for screen in screens}
        self.pages = {}
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon("pulse", tokens.TEXT))
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(1040, 660)
        self.resize(1320, 820)

        root = QWidget()
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

    # ----- frameless window: border, resize edges -----
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isMaximized():
            return
        painter = QPainter(self)
        painter.setPen(QPen(QColor(tokens.BORDER_STRONG), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

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
