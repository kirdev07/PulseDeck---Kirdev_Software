"""Media keys and shortcuts without PyAutoGUI: the same Windows call (keybd_event) it used,
with the same key names, minus four extra dependencies."""
import ctypes
import time

KEYEVENTF_EXTENDEDKEY = 0x1
KEYEVENTF_KEYUP = 0x2
VK = {
    "prevtrack": 0xB1, "nexttrack": 0xB0, "playpause": 0xB3,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "alt": 0x12, "ctrl": 0x11, "shift": 0x10, "f4": 0x73,
}
EXTENDED = {0xB0, 0xB1, 0xB3, 0xAD, 0xAE, 0xAF}


def _user32():
    return ctypes.windll.user32


def _event(code, up=False):
    flags = (KEYEVENTF_EXTENDEDKEY if code in EXTENDED else 0) | (KEYEVENTF_KEYUP if up else 0)
    _user32().keybd_event(code, 0, flags, 0)


def _code(name):
    try:
        return VK[name.lower()]
    except KeyError:
        raise ValueError(f"Неизвестная клавиша: {name}") from None


def press(name, presses=1, interval=0.0):
    code = _code(name)
    for index in range(presses):
        _event(code)
        _event(code, up=True)
        if interval and index < presses - 1:
            time.sleep(interval)


def hotkey(*names):
    codes = [_code(name) for name in names]
    for code in codes:
        _event(code)
    for code in reversed(codes):
        _event(code, up=True)
