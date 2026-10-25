"""Phone over a USB cable: `adb reverse` maps the phone's 127.0.0.1:8767 to this PC's TLS port.

Works when the phone has USB debugging enabled and adb (Android SDK platform-tools) is on
this PC. The connection is the same TLS API v1 with the same per-device token and pinned
certificate; the server sees the phone as a loopback peer. Without adb nothing happens.
The other cable option, USB tethering, needs nothing here: the phone and the PC simply share
a private network over the cable and the normal discovery finds the PC.
"""
import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("pulse_pc.services.local_api")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CHECK_SECONDS = 5


def find_adb():
    candidates = [shutil.which("adb")]
    for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if os.environ.get(variable):
            candidates.append(str(Path(os.environ[variable]) / "platform-tools" / "adb.exe"))
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(str(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk" / "platform-tools" / "adb.exe"))
    return next((c for c in candidates if c and Path(c).is_file()), None)


def _run(adb, *args, timeout=10):
    done = subprocess.run([adb, *args], capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    return done.returncode, done.stdout


def connected_devices(adb):
    code, out = _run(adb, "devices")
    if code != 0:
        return []
    return [line.split()[0] for line in out.splitlines()[1:] if line.strip().endswith("\tdevice")]


class UsbBridge:
    def __init__(self, port):
        self.port = port
        self.adb = find_adb()
        self.forwarded = set()
        self.task = None

    @property
    def available(self):
        return self.adb is not None

    def start(self):
        if self.available and self.task is None:
            self.task = asyncio.create_task(self._loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        if self.adb:
            for serial in list(self.forwarded):
                await asyncio.to_thread(_run, self.adb, "-s", serial, "reverse", "--remove", f"tcp:{self.port}")
        self.forwarded.clear()

    async def _loop(self):
        while True:
            try:
                devices = set(await asyncio.to_thread(connected_devices, self.adb))
                for serial in devices - self.forwarded:
                    code, _ = await asyncio.to_thread(_run, self.adb, "-s", serial, "reverse",
                                                      f"tcp:{self.port}", f"tcp:{self.port}")
                    if code == 0:
                        self.forwarded.add(serial)
                        logger.info("Телефон подключён по USB (adb), порт %s проброшен.", self.port)
                self.forwarded &= devices
            except (OSError, subprocess.SubprocessError) as exc:
                logger.debug("adb недоступен: %s", exc)
            await asyncio.sleep(CHECK_SECONDS)
