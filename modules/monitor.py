import asyncio
import ctypes
from ctypes import wintypes
import logging
import config

logger = logging.getLogger(__name__)
pc_is_locked = False


class _WtsInfoLevel1(ctypes.Structure):
    """WTSINFOEX_LEVEL1_W (wtsapi32.h)."""
    _fields_ = [("SessionId", wintypes.ULONG), ("SessionState", ctypes.c_int), ("SessionFlags", ctypes.c_long),
                ("WinStationName", wintypes.WCHAR * 33), ("UserName", wintypes.WCHAR * 21),
                ("DomainName", wintypes.WCHAR * 18),
                ("LogonTime", ctypes.c_longlong), ("ConnectTime", ctypes.c_longlong),
                ("DisconnectTime", ctypes.c_longlong), ("LastInputTime", ctypes.c_longlong),
                ("CurrentTime", ctypes.c_longlong),
                ("IncomingBytes", wintypes.DWORD), ("OutgoingBytes", wintypes.DWORD),
                ("IncomingFrames", wintypes.DWORD), ("OutgoingFrames", wintypes.DWORD),
                ("IncomingCompressedBytes", wintypes.DWORD), ("OutgoingCompressedBytes", wintypes.DWORD)]


class _WtsInfoEx(ctypes.Structure):
    """WTSINFOEXW: the level, then the level-1 data aligned to 8 bytes (it holds LARGE_INTEGERs)."""
    _fields_ = [("Level", wintypes.DWORD), ("Data", _WtsInfoLevel1)]


WTS_SESSION_INFO_EX = 25
WTS_SESSIONSTATE_LOCK, WTS_SESSIONSTATE_UNLOCK = 0, 1
WTS_ACTIVE = 0


def _session_locked():
    """True/False from the session itself (Windows 10+), None when Windows does not say.

    This is the real lock state: the UAC prompt of an installer («Разрешить этому приложению
    вносить изменения?») runs on the secure desktop, like the lock screen, but the session
    stays unlocked — the desktop check alone took every installer for a locked PC.
    """
    wtsapi32 = ctypes.windll.wtsapi32
    wtsapi32.WTSQuerySessionInformationW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                                                     ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    session = wintypes.DWORD()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(ctypes.windll.kernel32.GetCurrentProcessId(), ctypes.byref(session)):
        return None
    buffer, size = ctypes.c_void_p(), wintypes.DWORD()
    if not wtsapi32.WTSQuerySessionInformationW(None, session.value, WTS_SESSION_INFO_EX, ctypes.byref(buffer), ctypes.byref(size)):
        return None
    try:
        if size.value < ctypes.sizeof(_WtsInfoEx):
            return None
        found = ctypes.cast(buffer, ctypes.POINTER(_WtsInfoEx)).contents
        if found.Level != 1:
            return None
        info = found.Data
        if info.SessionState != WTS_ACTIVE:        # another user switched in, remote session cut: not at this PC
            return True
        if info.SessionFlags == WTS_SESSIONSTATE_LOCK:
            return True
        if info.SessionFlags == WTS_SESSIONSTATE_UNLOCK:
            return False
        return None
    finally:
        wtsapi32.WTSFreeMemory(buffer)


def _input_desktop_locked():
    """The old check: the input desktop is not «Default» (lock screen, but also UAC prompts)."""
    user32 = ctypes.windll.user32
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    desktop = user32.OpenInputDesktop(0, False, 1)
    if not desktop:
        return True
    try:
        name = ctypes.create_unicode_buffer(256)
        length = wintypes.DWORD()
        ok = user32.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(length))
        return not (ok and name.value.lower() == "default")
    finally:
        user32.CloseDesktop(desktop)


def workstation_locked():
    """Is the PC locked (lock screen, another user)? A UAC prompt is not a lock."""
    try:
        locked = _session_locked()
    except (OSError, AttributeError):
        locked = None
    return _input_desktop_locked() if locked is None else locked


async def lock_monitor(bot):
    global pc_is_locked
    previous = None
    notification = None

    async def notify(locked):
        try:
            await bot.send_message(chat_id=config.ADMIN_ID,
                text="🔒 Компьютер был заблокирован." if locked else "🔓 Компьютер был разблокирован.",
                request_timeout=5)
        except Exception as exc:
            logger.warning("Не удалось отправить состояние блокировки: %s", exc)

    try:
        while True:
            try:
                locked = workstation_locked()
                pc_is_locked = locked
                if locked != previous and (previous is not None or locked):
                    from modules import notify_bus
                    notify_bus.push("PulseDeck", "Компьютер заблокирован." if locked else "Компьютер разблокирован.")
                if locked != previous and config.ADMIN_ID and (previous is not None or locked):
                    if notification:
                        notification.cancel()
                        await asyncio.gather(notification, return_exceptions=True)
                    notification = asyncio.create_task(notify(locked))
                previous = locked
            except Exception as exc:
                pc_is_locked = True
                logger.error("Ошибка в мониторе блокировки: %s", exc)
            await asyncio.sleep(2)
    finally:
        if notification:
            notification.cancel()
            await asyncio.gather(notification, return_exceptions=True)
