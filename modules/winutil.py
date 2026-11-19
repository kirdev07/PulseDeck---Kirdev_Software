"""Small Windows helpers shared by the bot and the phone API."""


def bring_to_front(hwnd):
    """Show a window on top and give it focus.

    Windows lets only the foreground process take focus, so a background PulseDeck
    first "taps" Alt and attaches to the foreground thread. Raises ValueError with a
    readable message instead of a raw pywin32 error.
    """
    import pywintypes
    import win32api
    import win32con
    import win32gui
    import win32process

    try:
        if not win32gui.IsWindow(hwnd):
            raise ValueError("Окно уже закрыто. Обновите список.")
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        foreground = win32gui.GetForegroundWindow()
        current = win32api.GetCurrentThreadId()
        other = win32process.GetWindowThreadProcessId(foreground)[0] if foreground else 0
        attached = bool(other and other != current)
        if attached:
            win32process.AttachThreadInput(current, other, True)
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                win32process.AttachThreadInput(current, other, False)
    except pywintypes.error as exc:
        raise ValueError("Windows не разрешила показать окно (ПК заблокирован или окно закрыто).") from exc


_names = {}


def _app_name(path):
    """«Google Chrome» from the exe's version info (as Task Manager shows it), else the file name."""
    if path in _names:
        return _names[path]
    import os
    name = os.path.splitext(os.path.basename(path))[0]
    try:
        import win32api
        lang, page = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")[0]
        described = win32api.GetFileVersionInfo(path, f"\\StringFileInfo\\{lang:04x}{page:04x}\\FileDescription")
        if described and described.strip():
            name = described.strip()
    except Exception:  # noqa: BLE001 - no version info (many games): the file name
        pass
    _names[path] = name
    return name


def foreground_activity():
    """What is in front on the PC: {'app', 'title', 'fullscreen'} or None (desktop / nothing / locked)."""
    import win32api
    import win32con
    import win32gui
    import win32process

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd or win32gui.GetClassName(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        import psutil
        path = psutil.Process(pid).exe()
    except Exception:  # noqa: BLE001 - a protected process
        path = ""
    if path.lower().endswith(("lockapp.exe", "logonui.exe")):
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    monitor = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST))["Monitor"]
    fullscreen = (left, top, right, bottom) == tuple(monitor) and not win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & win32con.WS_CAPTION
    return {"app": _app_name(path) if path else "", "title": win32gui.GetWindowText(hwnd)[:120], "fullscreen": bool(fullscreen)}


def close_foreground_window():
    """Close the active window like Alt+F4, but without key injection (and never the desktop/taskbar,
    where Alt+F4 would open the Windows shutdown dialog). Returns the title of the closed window."""
    import win32con
    import win32gui

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        raise ValueError("Нет активного окна.")
    if win32gui.GetClassName(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        raise ValueError("Сейчас активен рабочий стол Windows: закрывать нечего.")
    title = win32gui.GetWindowText(hwnd)
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    return title
