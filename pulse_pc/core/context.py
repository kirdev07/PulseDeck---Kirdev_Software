"""Shared objects handed to every screen."""
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class AppContext:
    store: object = None              # core.state.StateStore
    metrics: object = None            # services.system.metrics.MetricsService
    navigate: Optional[Callable[[str], None]] = None   # set by the main window
