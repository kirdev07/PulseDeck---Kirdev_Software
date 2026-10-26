"""Updates from GitHub Releases, like the PulseDesk and PulseDeck Panel apps.

The newest release whose tag (v1.0.1) is above the running version and which has a
PulseDeck-<version>-Setup.exe asset. The installer is downloaded to %TEMP% and started in
silent mode; it closes this program (CloseApplications=force), installs over it keeping
%APPDATA%\\PulseDeck, and starts the new version (see installer.iss). Nothing is installed
without the user pressing the button.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from pulse_pc import __version__

REPO = "kirdev07/PulseDeck---Kirdev_Software"
# PULSEDECK_UPDATE_URL points the check at a test server (end-to-end test of the update).
LATEST = os.environ.get("PULSEDECK_UPDATE_URL") or f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases/latest"
AUTO_HOURS = 6
TIMEOUT = 20

IDLE, CHECKING, UP_TO_DATE, AVAILABLE, DOWNLOADING, READY, FAILED = (
    "idle", "checking", "up_to_date", "available", "downloading", "ready", "failed")


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    url: str
    size: int
    name: str


def parse(data):
    """Release from the GitHub API answer, or None (draft, pre-release, no installer)."""
    if data.get("draft") or data.get("prerelease"):
        return None
    for asset in data.get("assets") or ():
        name = asset.get("name", "")
        if name.lower().endswith("-setup.exe"):
            return Release(str(data.get("tag_name", "")).lstrip("vV"), plain(data.get("body") or ""),
                           asset.get("browser_download_url", ""), int(asset.get("size") or 0), name)
    return None


def is_newer(candidate, installed):
    """«1.0.10» > «1.0.9»; missing parts count as 0 («1.0» == «1.0.0»)."""
    def parts(text):
        return [int("".join(ch for ch in part if ch.isdigit()) or 0) for part in text.split("-")[0].split(".")]
    a, b = parts(candidate), parts(installed)
    width = max(len(a), len(b))
    return a + [0] * (width - len(a)) > b + [0] * (width - len(b))


def plain(markdown):
    """Release notes without GitHub markdown marks."""
    import re
    lines = []
    for line in markdown.splitlines():
        line = re.sub(r"^#{1,6}\s*", "", line.rstrip())
        line = re.sub(r"^\s*[-*+]\s+", "• ", line)
        line = re.sub(r"\[([^\]]*)]\([^)]*\)", r"\1", line)
        lines.append(re.sub(r"\*\*|__|`", "", line))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def installed_build():
    """Updates replace the installed program; a source checkout updates with git and the
    portable ZIP (no uninstaller next to the exe) by downloading a new ZIP."""
    return bool(getattr(sys, "frozen", False)) and (Path(sys.executable).parent / "unins000.exe").is_file()


def portable_build():
    return bool(getattr(sys, "frozen", False)) and not installed_build()


class Updater(QObject):
    changed = Signal(str)       # state; details in .release / .progress / .message

    def __init__(self, config_dir, parent=None):
        super().__init__(parent)
        self.stamp = Path(config_dir) / "update_check.json"
        self.state = IDLE
        self.release = None
        self.progress = 0.0
        self.message = ""
        self.file = None
        self._busy = False

    # ----- checking -----
    def check_automatically(self):
        """At most once per AUTO_HOURS, in the background, on program start."""
        try:
            last = json.loads(self.stamp.read_text(encoding="utf-8")).get("time", 0)
        except (OSError, ValueError):
            last = 0
        if time.time() - last >= AUTO_HOURS * 3600:
            self.check()

    def check(self):
        if self._busy:
            return
        self._busy = True
        self._set(CHECKING)
        threading.Thread(target=self._check, daemon=True, name="PulseDeck-updates").start()

    def _check(self):
        try:
            request = urllib.request.Request(LATEST, headers={"Accept": "application/vnd.github+json",
                                                              "User-Agent": f"PulseDeck/{__version__}"})
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    release = parse(json.load(response))
            except urllib.error.HTTPError as exc:
                if exc.code != 404:         # 404: no releases yet
                    raise
                release = None
            try:
                self.stamp.write_text(json.dumps({"time": time.time()}), encoding="utf-8")
            except OSError:
                pass
            self.release = release if release and is_newer(release.version, __version__) else None
            self._done(AVAILABLE if self.release else UP_TO_DATE)
        except Exception:  # noqa: BLE001 - offline, GitHub down, bad answer
            self.message = "Не удалось проверить обновления: нет интернета или GitHub недоступен."
            self._done(FAILED)

    # ----- downloading and installing -----
    def download(self):
        if self._busy or self.release is None:
            return
        self._busy = True
        self.progress = 0.0
        self._set(DOWNLOADING)
        threading.Thread(target=self._download, daemon=True, name="PulseDeck-update-download").start()

    def _download(self):
        release = self.release
        folder = Path(tempfile.gettempdir()) / "PulseDeck-update"
        try:
            folder.mkdir(exist_ok=True)
            for old in folder.glob("*.exe"):
                old.unlink(missing_ok=True)
            target = folder / Path(release.name).name
            request = urllib.request.Request(release.url, headers={"User-Agent": f"PulseDeck/{__version__}"})
            with urllib.request.urlopen(request, timeout=60) as response, open(target, "wb") as out:
                total = int(response.headers.get("Content-Length") or release.size or 0)
                done = 0
                while chunk := response.read(256 * 1024):
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        self.progress = min(done / total, 1.0)
                        self.changed.emit(DOWNLOADING)
            if release.size and target.stat().st_size != release.size:
                raise OSError("size mismatch")
            self.file = target
            self._done(READY)
        except Exception:  # noqa: BLE001
            self.message = "Не удалось скачать обновление. Попробуйте ещё раз."
            self._done(FAILED)

    def install(self):
        """Start the installer silently and quit: it replaces the files and starts the new version."""
        if self.file is None or not self.file.is_file():
            return False
        os.startfile(str(self.file), arguments="/SILENT /SP- /NOCANCEL /NORESTART")  # noqa: S606
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()
        return True

    def _done(self, state):
        self._busy = False
        self._set(state)

    def _set(self, state):
        self.state = state
        self.changed.emit(state)
