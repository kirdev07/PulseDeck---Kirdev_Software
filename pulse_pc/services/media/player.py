"""Built-in music player for the new interface.

`MusicPlayer` extends the proven PlayerController (also driven by the phone through
modules.player_bridge) with an explicit queue, shuffle and repeat. Library scanning and
Windows media sessions (other apps) run in background threads.
"""
import asyncio
import logging
import random
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QMediaPlayer

from modules import now_playing, player_bridge
from player_controller import PlayerController

logger = logging.getLogger(__name__)
REPEAT_MODES = ("all", "one", "off")


class MusicPlayer(PlayerController):
    queue_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.shuffle = False
        self.repeat = "all"         # PlayerController's original behaviour: wrap around
        self._history = []

    # ----- queue -----
    def open_track(self, path, queue=None):
        super().open_track(path, queue)
        self._history.clear()
        self.queue_changed.emit()

    def play_index(self, index):
        if 0 <= index < len(self.queue):
            self._history.append(self.index)
            self.index = index
            self.load_current()
            self.queue_changed.emit()

    def current(self):
        return self.queue[self.index] if 0 <= self.index < len(self.queue) else None

    # ----- modes -----
    def set_shuffle(self, on):
        self.shuffle = bool(on)
        self._history.clear()
        self.publish()

    def cycle_repeat(self):
        self.repeat = REPEAT_MODES[(REPEAT_MODES.index(self.repeat) + 1) % len(REPEAT_MODES)]
        self.publish()
        return self.repeat

    def step(self, offset):
        """next/prev from the window, the phone and the end of a track."""
        if not self.queue:
            return
        if offset < 0 and self.shuffle and self._history:
            self.index = self._history.pop()
        elif self.shuffle and len(self.queue) > 1:
            self._history.append(self.index)
            self.index = random.choice([i for i in range(len(self.queue)) if i != self.index])
        else:
            target = self.index + offset
            if not 0 <= target < len(self.queue):
                if self.repeat == "off":
                    self.player.stop()
                    self.publish()
                    return
                target %= len(self.queue)
            self.index = target
        self.load_current()
        self.queue_changed.emit()

    def media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self.repeat == "one":
            self.player.setPosition(0)
            self.player.play()
            self.publish()
            return
        super().media_status(status)

    def state(self):
        return player_bridge.snapshot()


def publish_to_store(player, store):
    """Mirror the player into StateStore.player (used by the dashboard mini-player)."""
    def push():
        data = player_bridge.snapshot()
        store.update("player", status=data["status"] if data["active"] else "stopped", title=data["title"],
                     artist=data["artist"], position=round(data["position"], 1), duration=data["duration"],
                     cover=data["cover"] or b"", source="Pulse-PC")
    player.changed.connect(push)
    push()


class LibraryScanner(QObject):
    """Scans the library folders off the UI thread (large folders take seconds)."""

    scanned = Signal(list)

    def scan(self):
        def target():
            try:
                tracks = player_bridge.scan_tracks()
            except OSError as exc:
                logger.warning("Не удалось прочитать библиотеку: %s", exc)
                tracks = []
            self.scanned.emit(tracks)
        threading.Thread(target=target, daemon=True, name="PulsePC-library").start()


class MediaSessions(QObject):
    """Media sessions of other apps (Spotify, browsers, …) via Windows; polled every few
    seconds while started. `available` is False without the optional winrt packages."""

    updated = Signal(list)
    failed = Signal(str)

    def __init__(self, interval=2.0, parent=None):
        super().__init__(parent)
        self.available = now_playing.AVAILABLE
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._loop = None

    def start(self):
        if not self.available or (self._thread and self._thread.is_alive() and not self._stop.is_set()):
            return
        if self._thread and self._thread.is_alive():
            self._thread.join(2)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="PulsePC-sessions")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def command(self, name, source):
        """Send play/pause/next/prev to another app's session (from the UI thread)."""
        loop = self._loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(now_playing.command(name, None, source), loop)

    def _run(self):
        loop = self._loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._poll())
        finally:
            self._loop = None
            loop.close()

    async def _poll(self):
        # One long-running coroutine keeps the loop alive, so command() is never dropped.
        while not self._stop.is_set():
            try:
                items = await now_playing.sessions()
                self.updated.emit([s for s in items if s.get("title")])
            except Exception as exc:  # noqa: BLE001 - Windows may drop sessions mid-read
                self.failed.emit(str(exc))
            for _ in range(int(self.interval * 10)):
                if self._stop.is_set():
                    return
                await asyncio.sleep(0.1)
