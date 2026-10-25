"""Shared objects handed to every screen."""
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class AppContext:
    store: object = None              # core.state.StateStore
    logbook: object = None            # core.logbook.Logbook
    player: object = None             # services.media.player.MusicPlayer
    metrics: object = None            # services.system.metrics.MetricsService
    window: object = None             # the main window, set by it
    navigate: Optional[Callable[[str], None]] = None   # set by the main window
