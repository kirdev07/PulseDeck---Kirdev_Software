"""Observable state of the background services, shared by all screens.

Services write it (stage D wires Telegram, the local API and the player); screens only
read it and react to `changed`. Until a service reports, its state is UNKNOWN and the
UI says so instead of inventing a status.
"""
from dataclasses import dataclass, field, replace

from PySide6.QtCore import QObject, Signal

UNKNOWN, STOPPED, STARTING, RUNNING, RECONNECTING, ERROR = (
    "unknown", "stopped", "starting", "running", "reconnecting", "error")


@dataclass(frozen=True)
class TelegramState:
    status: str = UNKNOWN
    bot_name: str = ""
    since: float = 0.0          # time.time() when RUNNING began
    error: str = ""


@dataclass(frozen=True)
class PhoneState:
    status: str = UNKNOWN       # local API server
    addresses: tuple = ()
    port: int = 0
    devices: tuple = ()         # ({"id", "name", "last_seen"}, ...)


@dataclass(frozen=True)
class PlayerState:
    status: str = "stopped"     # playing | paused | stopped
    title: str = ""
    artist: str = ""
    position: float = 0.0
    duration: float = 0.0
    cover: bytes = b""
    source: str = ""


@dataclass(frozen=True)
class AppState:
    telegram: TelegramState = field(default_factory=TelegramState)
    phone: PhoneState = field(default_factory=PhoneState)
    player: PlayerState = field(default_factory=PlayerState)


class StateStore(QObject):
    """Holds an immutable AppState; `update(part, **changes)` swaps in a new copy."""

    changed = Signal(str, object)   # (part, new value)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = AppState()

    def update(self, part, **changes):
        current = getattr(self.state, part)
        new = replace(current, **changes)
        if new != current:
            self.state = replace(self.state, **{part: new})
            self.changed.emit(part, new)
        return new
