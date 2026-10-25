"""Application journal: every `logging` record plus explicit events, sorted by source.

Lines are written to config/logs/pulse.log in the same format the classic panel uses
(`[YYYY-mm-dd HH:MM:SS]  LEVEL  text`), so both panels share one history during the
migration. Tokens are masked before anything reaches memory or disk.
"""
import logging
import itertools
import re
import threading
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal

LEVELS = ("INFO", "WARN", "ERROR")
SOURCES = {"system": "Система", "telegram": "Telegram", "phone": "Телефон", "apps": "Приложения"}
_TOKEN = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{15,}\b")
_LINE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(?:(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s+)?(.*)$")
_TELEGRAM = ("aiogram", "modules.advanced_handlers", "modules.file_handlers", "modules.keyboards",
             "modules.media_handlers", "modules.middleware", "modules.program_handlers", "modules.remote_tools",
             "modules.system_handlers", "modules.bot_features", "modules.monitor", "pulse_pc.services.telegram")
_PHONE = ("aiohttp", "modules.local_api", "modules.mobile_access", "pulse_pc.services.local_api")
_APPS = ("modules.program_store", "pulse_pc.services.system.programs")


def redact(text, secrets=()):
    text = _TOKEN.sub("[TOKEN скрыт]", str(text))
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[скрыто]")
    return text


def level_of(name_or_number):
    if isinstance(name_or_number, int):
        return "ERROR" if name_or_number >= logging.ERROR else "WARN" if name_or_number >= logging.WARNING else "INFO"
    name = (name_or_number or "").upper()
    return "ERROR" if name in ("ERROR", "CRITICAL") else "WARN" if name in ("WARNING", "WARN") else "INFO"


def guess_level(text):
    upper = text.upper()
    if any(word in upper for word in ("ERROR", "ОШИБ", "КРИТИЧ", "TRACEBACK")):
        return "ERROR"
    if any(word in upper for word in ("WARNING", "ПРЕДУПРЕЖД", "НЕ УДАЛОСЬ", "НЕТ СВЯЗИ")):
        return "WARN"
    return "INFO"


def source_of(logger_name):
    name = logger_name or ""
    for prefixes, source in ((_TELEGRAM, "telegram"), (_PHONE, "phone"), (_APPS, "apps")):
        if name.startswith(prefixes):
            return source
    return "system"


def guess_source(text):
    lower = text.lower()
    if "telegram" in lower or "бот" in lower:
        return "telegram"
    if "телефон" in lower or "мобильн" in lower or "устройств" in lower or "api" in lower:
        return "phone"
    if "программ" in lower or "запущено:" in lower or "закрыто:" in lower:
        return "apps"
    return "system"


@dataclass(frozen=True)
class Entry:
    time: datetime
    level: str
    source: str
    text: str
    seq: int = 0        # order of arrival in this Logbook, stable when old entries rotate out

    def line(self):
        return f"[{self.time:%Y-%m-%d %H:%M:%S}]  {self.level:<5}  {self.text}"


def parse_line(line):
    """A line of pulse.log (either panel) -> Entry, or None for blank lines."""
    line = line.rstrip()
    if not line:
        return None
    match = _LINE.match(line)
    if not match:
        return Entry(datetime.min, guess_level(line), guess_source(line), line)
    stamp, level, text = match.groups()
    # The classic panel writes some levels inside the text: "WARNING  Нет связи…".
    inner = re.match(r"^(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s+(.*)$", text)
    if not level and inner:
        level, text = inner.groups()
    return Entry(datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S"),
                 level_of(level) if level else guess_level(text), guess_source(text), text)


class Logbook(QObject):
    """Ring buffer of entries; `added` is emitted from whatever thread logged
    (Qt queues it to the UI thread)."""

    added = Signal(object)

    def __init__(self, directory=None, capacity=5000, parent=None):
        super().__init__(parent)
        self.entries = deque(maxlen=capacity)
        self._seq = itertools.count(1)
        self.secrets = []
        self.counts = {level: 0 for level in LEVELS}   # since this start
        self._lock = threading.Lock()
        self.path = None
        self._file = None
        if directory:
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True)
            self.path = directory / "pulse.log"
            self._load_history()
            self._file = RotatingFileHandler(self.path, maxBytes=2_000_000, backupCount=3, encoding="utf-8", delay=True)
            self._file.setFormatter(logging.Formatter("%(message)s"))
        self.handler = _Handler(self)

    def _load_history(self, limit=2000):
        lines = deque(maxlen=limit)
        for path in [self.path.with_name(f"pulse.log.{n}") for n in (3, 2, 1)] + [self.path]:
            if path.exists():
                with path.open(encoding="utf-8", errors="replace") as stream:
                    lines.extend(stream)
        for line in lines:
            entry = parse_line(redact(line))
            if entry:
                self.entries.append(replace(entry, seq=next(self._seq)))

    def add(self, text, level="INFO", source="system", when=None):
        entry = Entry(when or datetime.now().replace(microsecond=0), level_of(level),
                      source if source in SOURCES else "system", redact(str(text).rstrip(), self.secrets))
        with self._lock:
            entry = replace(entry, seq=next(self._seq))
            self.entries.append(entry)
            self.counts[entry.level] += 1
            if self._file:
                try:
                    self._file.emit(logging.LogRecord("pulse.journal", logging.INFO, "", 0, entry.line(), (), None))
                except Exception:  # noqa: BLE001 - a full disk must not break logging
                    pass
        self.added.emit(entry)
        return entry

    def snapshot(self):
        with self._lock:
            return list(self.entries)

    def install(self, logger=None, level=logging.INFO):
        logger = logger or logging.getLogger()
        if self.handler not in logger.handlers:
            logger.addHandler(self.handler)
        if logger.level == logging.NOTSET or logger.level > level:
            logger.setLevel(level)

    def uninstall(self, logger=None):
        (logger or logging.getLogger()).removeHandler(self.handler)

    def close(self):
        self.uninstall()
        if self._file:
            self._file.close()


class _Handler(logging.Handler):
    def __init__(self, book):
        super().__init__(logging.INFO)
        self.book = book

    def emit(self, record):
        try:
            text = record.getMessage()
            if record.exc_info:
                text += "\n" + logging.Formatter().formatException(record.exc_info)
            self.book.add(text, level_of(record.levelno), source_of(record.name),
                          datetime.fromtimestamp(record.created).replace(microsecond=0))
        except Exception:  # noqa: BLE001
            self.handleError(record)
