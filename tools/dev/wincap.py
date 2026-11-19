"""Capture the running PulseDeck window (README screenshots, UI checks).

    .venv\\Scripts\\python tools\\dev\\wincap.py out.png [click_x click_y]

Coordinates are relative to the window's top-left; the click happens before the capture.
Sidebar at 1440×900: Главная y=101, Telegram 141, Телефон 181, Приложения 221, Консоль 261,
Музыка 301, Настройки 341 (x=90).
"""
import ctypes
import sys
import time

import win32con
import win32gui
import win32ui
from PIL import Image

ctypes.windll.user32.SetProcessDPIAware()


def find():
    found = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == "PulseDeck":
            found.append(hwnd)
    win32gui.EnumWindows(cb, None)
    return found[0]


hwnd = find()
if win32gui.IsIconic(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
left, top, right, bottom = win32gui.GetWindowRect(hwnd)
if len(sys.argv) > 3:
    import win32api
    x, y = left + int(sys.argv[2]), top + int(sys.argv[3])
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    win32api.SetCursorPos((x, y))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    win32api.SetCursorPos((left + 5, bottom + 40))
    time.sleep(1.5)
w, h = right - left, bottom - top
dc = win32gui.GetWindowDC(hwnd)
src = win32ui.CreateDCFromHandle(dc)
mem = src.CreateCompatibleDC()
bmp = win32ui.CreateBitmap()
bmp.CreateCompatibleBitmap(src, w, h)
mem.SelectObject(bmp)
ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2)
info = bmp.GetInfo()
img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
img.save(sys.argv[1])
print(w, h)
win32gui.DeleteObject(bmp.GetHandle())
for release in (mem.DeleteDC, src.DeleteDC):
    try:
        release()
    except win32ui.error:
        pass
win32gui.ReleaseDC(hwnd, dc)
