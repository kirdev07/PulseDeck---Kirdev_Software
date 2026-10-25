"""Entry point of the new interface: python -m pulse_pc [--minimized] [--gallery]

During migration the classic panel (gui.py) still exists; both share config/ and lock
the same files, so only one of them can run at a time.
"""
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

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


def _log_uncaught_exceptions():
    """The windowed build has no console: send crashes of any thread to the journal."""
    import logging
    import threading
    log = logging.getLogger("pulse_pc.crash")

    def main_hook(kind, value, trace):
        log.critical("Необработанная ошибка", exc_info=(kind, value, trace))

    def thread_hook(args):
        if args.exc_type is not SystemExit:
            log.critical("Необработанная ошибка в потоке %s", getattr(args.thread, "name", "?"),
                         exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    sys.excepthook = main_hook
    threading.excepthook = thread_hook


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = create_application(argv)
    app.setQuitOnLastWindowClosed(False)    # closing the window keeps the services in the tray

    import config
    from pulse_pc.core.context import AppContext
    from pulse_pc.core.logbook import Logbook
    from pulse_pc.core.settings import SettingsStore
    from pulse_pc.core.state import StateStore
    from pulse_pc.services.manager import InstanceLock, ServiceManager
    from pulse_pc.services.media.player import MusicPlayer, publish_to_store
    from pulse_pc.services.system.metrics import MetricsService
    from pulse_pc.ui.screens.registry import SCREENS
    from pulse_pc.ui.shell import MainWindow
    from pulse_pc.ui.tray import Tray

    config_dir = Path(config.CONFIG_DIR)
    lock = InstanceLock(config_dir)
    if not lock.acquire():
        QMessageBox.information(None, APP_NAME, "PulseDeck уже запущен. Откройте его через значок в системном трее.")
        return 0

    logbook = Logbook(config_dir / "logs")
    logbook.install()
    _log_uncaught_exceptions()
    from pulse_pc.core import secrets
    try:
        if secrets.migrate_token(config_dir):
            logbook.add("Токен бота перенесён из config/.env в зашифрованное хранилище Windows.")
    except Exception as exc:  # noqa: BLE001 - keep the old storage rather than lose the token
        logbook.add(f"Не удалось зашифровать токен бота, он остаётся в config/.env: {exc}", "WARN")
    token = secrets.load_token(config_dir)
    if token:
        logbook.secrets.extend((token, token.split(":", 1)[-1]))
    store = StateStore()
    services = ServiceManager(store, config_dir)
    context = AppContext(store=store, logbook=logbook, metrics=MetricsService(), player=MusicPlayer(app),
                         services=services)
    publish_to_store(context.player, store)

    screens = SCREENS
    if "--gallery" in argv:
        from pulse_pc.ui.gallery import SCREENS_WITH_GALLERY
        screens = SCREENS_WITH_GALLERY
    ui = SettingsStore(config_dir / "app_settings.json").load()
    window = MainWindow(screens, context=context, animate=ui.animations)
    tray = Tray(window, context)
    context.tray = tray if tray.available else None

    context.metrics.start()
    services.start(telegram=ui.telegram_autostart)

    def shutdown():
        context.metrics.stop()
        services.shutdown()
        tray.hide()
        logbook.close()
        lock.release()
    app.aboutToQuit.connect(shutdown)

    if not ({"--minimized", "-m"} & set(argv)) or not tray.available:
        window.show()
    return app.exec()
