"""«Запускать вместе с Windows»: the HKCU Run entry. Uses the launcher's command
(PulsePC.pyw, which repairs the environment before starting)."""
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAMES = ("PulsePC", "PulsePC_Bot")   # PulsePC_Bot: entry of very old versions


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
    import launcher
    launcher.set_autostart(enable)
    if enable:
        # Remove the legacy entry so the app does not start twice.
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "PulsePC_Bot")
        except OSError:
            pass
    return is_enabled()
