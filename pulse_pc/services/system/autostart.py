"""«Запускать вместе с Windows»: the HKCU Run entry.

Installed build: runs PulseDeck.exe --minimized. Source checkout: pythonw + PulsePC.pyw,
which finds the project's .venv by itself."""
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "PulseDeck"
LEGACY = ("PulsePC", "PulsePC_Bot")   # entries of the previous name (Pulse-PC / Pulse PC 1.x)
NAMES = (NAME,) + LEGACY
ROOT = Path(__file__).resolve().parents[3]


def command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{interpreter}" "{ROOT / "PulsePC.pyw"}" --minimized'


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            for name in NAMES:
                try:
                    winreg.QueryValueEx(key, name)
                    return True
                except FileNotFoundError:
                    continue
    except OSError:
        pass
    return False


def set_enabled(enable):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enable:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
        for name in (LEGACY if enable else NAMES):   # never start twice
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
    return is_enabled()
