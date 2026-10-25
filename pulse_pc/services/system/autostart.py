"""«Запускать вместе с Windows»: the HKCU Run entry.

Installed build: runs Pulse-PC.exe --minimized. Source checkout: uses the launcher's
command (PulsePC.pyw, which repairs the Python environment before starting)."""
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "PulsePC"
NAMES = (NAME, "PulsePC_Bot")   # PulsePC_Bot: entry of very old versions


def command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    import launcher
    return launcher.launcher_command("--minimized")[0]


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
        for name in (("PulsePC_Bot",) if enable else NAMES):   # never start twice
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
    return is_enabled()
