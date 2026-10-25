"""Entry point of the new interface: python -m pulse_pc [--gallery]

During migration this runs only the new shell; the working app is still gui.py.
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication

from pulse_pc import APP_NAME
from pulse_pc.ui.theme import stylesheet


def create_application(argv=None):
    app = QApplication.instance()
    if app:
        return app
    # Honour fractional Windows scaling (125 %, 150 %) instead of rounding it.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    font = QFont("Segoe UI Variable Text")
    font.setPointSize(10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    app.setStyleSheet(stylesheet())
    return app


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = create_application(argv)
    from pulse_pc.core.context import AppContext
    from pulse_pc.core.state import StateStore
    from pulse_pc.services.system.metrics import MetricsService
    from pulse_pc.ui.screens.registry import SCREENS
    from pulse_pc.ui.shell import MainWindow
    import config
    from pathlib import Path
    from pulse_pc.core.logbook import Logbook
    logbook = Logbook(Path(config.CONFIG_DIR) / "logs")
    logbook.install()
    from pulse_pc.services.media.player import MusicPlayer, publish_to_store
    context = AppContext(store=StateStore(), logbook=logbook, metrics=MetricsService(), player=MusicPlayer(app))
    publish_to_store(context.player, context.store)
    screens = SCREENS
    if "--gallery" in argv:
        from pulse_pc.ui.gallery import SCREENS_WITH_GALLERY
        screens = SCREENS_WITH_GALLERY
    from pulse_pc.core.settings import SettingsStore
    ui = SettingsStore(Path(config.CONFIG_DIR) / "app_settings.json").load()
    window = MainWindow(screens, context=context, animate=ui.animations)
    context.metrics.start()
    app.aboutToQuit.connect(context.metrics.stop)
    app.aboutToQuit.connect(logbook.close)
    window.show()
    return app.exec()
