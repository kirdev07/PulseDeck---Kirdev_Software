"""Observable state of the background services, shared by all screens.

Services write it (stage D wires Telegram, the local API and the player); screens only
read it and react to `changed`. Until a service reports, its state is UNKNOWN and the
UI says so instead of inventing a status.
"""
from dataclasses import dataclass, field, replace

from PySide6.QtCore import QObject, Qt, Signal

UNKNOWN, STOPPED, STARTING, RUNNING, RECONNECTING, ERROR = (
    "unknown", "stopped", "starting", "running", "reconnecting", "error")


@dataclass(frozen=True)
class TelegramState:
    status: str = UNKNOWN
    bot_name: str = ""          # @username
    bot_title: str = ""         # display name
    since: float = 0.0          # time.time() when RUNNING began
    error: str = ""
    updates: int = 0            # Telegram updates handled since start
    denied: int = 0             # updates from users other than the administrator
    failures: int = 0           # handler errors since start


@dataclass(frozen=True)
class PhoneState:
    status: str = UNKNOWN       # local API server
    addresses: tuple = ()
    port: int = 0               # API v0 over HTTP; 0 = not running
    tls_port: int = 0           # API v1 over TLS; 0 = not running
    devices: tuple = ()         # ({"id", "name", "added", "last_seen"}, ...)
    error: str = ""


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
    """Holds an immutable AppState; `update(part, **changes)` swaps in a new copy.

    `update` must run in the UI thread; services in other threads call `post`, which
    queues the change to the UI thread."""

    changed = Signal(str, object)   # (part, new value)
    _posted = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = AppState()
        self._posted.connect(lambda part, changes: self.update(part, **changes), Qt.ConnectionType.QueuedConnection)

    def post(self, part, **changes):
        self._posted.emit(part, changes)

    def update(self, part, **changes):
        current = getattr(self.state, part)
        new = replace(current, **changes)
        if new != current:
            self.state = replace(self.state, **{part: new})
            self.changed.emit(part, new)
        return new
