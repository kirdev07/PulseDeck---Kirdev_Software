"""LAN HTTP API for the PulseDeck mobile app (same actions as the Telegram bot).

Every request except /api/ping and /api/pair needs `Authorization: Bearer <token>`.
Each phone gets its own token when the PC owner approves it (see mobile_access.py).
The PC also answers UDP discovery broadcasts so phones can find it automatically.
"""
import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import subprocess
import time
import webbrowser
from io import BytesIO

from aiohttp import web

import config
from desktop_services import computer_info
from modules import mobile_access, notify_bus, now_playing, player_access, player_bridge, volume as system_volume
from modules.keyboards import load_programs
from modules.program_store import effective_process
from modules.utils import kill_process

logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 200 * 1024 * 1024
# Read-only endpoints that still work while the PC is locked (phone notifications).
# The panel (/api/display) keeps showing data while the PC is locked; it refuses commands itself.
READ_WHEN_LOCKED = {"/api/status", "/api/events", "/api/player/state", "/api/player/cover", "/api/display"}
# A «view only» phone gets exactly what is readable on a locked PC: monitoring and now playing.
VIEW_ONLY_PATHS = READ_WHEN_LOCKED
MEDIA_KEYS = {"prev": "prevtrack", "play": "playpause", "next": "nexttrack",
              "voldown": "volumedown", "volup": "volumeup", "mute": "volumemute"}


def lan_addresses():
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                found.add(ip)
    except OSError:
        pass
    return sorted(found)


def json_error(status, text):
    return web.json_response({"ok": False, "error": text}, status=status)


def is_private_ip(ip):
    """LAN, loopback or link-local address; IPv4 written as IPv6 (::ffff:a.b.c.d) counts as IPv4."""
    try:
        address = ipaddress.ip_address((ip or "").split("%", 1)[0])
    except ValueError:
        return False
    if getattr(address, "ipv4_mapped", None):
        address = address.ipv4_mapped
    return address.is_private or address.is_loopback or address.is_link_local


def host_allowed(request):
    """DNS rebinding guard: a web page that points its own domain at this PC's address must
    not reach the API from the owner's browser. Phones and the panel use the IP (or
    localhost over USB), so only an IP literal, localhost or this PC's own name is accepted."""
    try:
        name = (request.url.host or "").strip("[]").rstrip(".").lower()
    except (ValueError, TypeError):
        return False
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    pc = socket.gethostname().lower()
    return name in ("localhost", pc, pc + ".local") or name.endswith(".localhost")


def clean_device_name(raw, default="Телефон"):
    """A phone's name as shown on the PC and in the log: one line, at most 40 characters."""
    return " ".join(str(raw or "").split())[:40] or default


def ask_owner(text):
    """Yes/No dialog on the PC desktop (blocking; run it in a thread)."""
    import ctypes
    MB_YESNO, MB_ICONQUESTION, MB_SETFOREGROUND, MB_TOPMOST = 0x4, 0x20, 0x10000, 0x40000
    IDYES = 6
    return ctypes.windll.user32.MessageBoxW(
        0, text, "PulseDeck — новое устройство", MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST) == IDYES


def to_recycle_bin(path):
    """Move a file or folder to the Windows Recycle Bin (SHFileOperation with FOF_ALLOWUNDO)."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=str(path) + "\0",
                         fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI)
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0 or op.fAnyOperationsAborted:
        raise ValueError("Не удалось переместить в корзину.")


# Ending these breaks Windows or PulseDeck itself, so the phone may not.
PROTECTED_PROCESSES = {"system", "idle", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
                       "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe", "memory compression"}


def list_processes(limit=300):
    """Processes with CPU (sampled over 0.3 s, % of the whole CPU) and memory, biggest first."""
    import psutil
    import time as _time
    procs = []
    for proc in psutil.process_iter(["pid", "name"]):
        if proc.pid == 0:        # «System Idle Process»: idle time, not load
            continue
        try:
            proc.cpu_percent(None)
            procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _time.sleep(0.3)
    cores = psutil.cpu_count() or 1
    result = []
    for proc in procs:
        try:
            with proc.oneshot():
                name = proc.info["name"] or ""
                result.append({"pid": proc.pid, "name": name,
                               "cpu": round(proc.cpu_percent(None) / cores, 1),
                               "memory": proc.memory_info().rss,
                               "protected": is_protected(proc.pid, name)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    result.sort(key=lambda p: (p["cpu"], p["memory"]), reverse=True)
    return result[:limit]


def is_protected(pid, name):
    return pid <= 4 or pid == os.getpid() or (name or "").lower() in PROTECTED_PROCESSES


def end_process(pid):
    import psutil
    if pid <= 4 or pid == os.getpid():
        raise ValueError("Этот процесс завершать нельзя.")
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        if name.lower() in PROTECTED_PROCESSES:
            raise ValueError("Это системный процесс, его завершать нельзя.")
        proc.terminate()
        proc.wait(5)
    except psutil.NoSuchProcess:
        raise ValueError("Процесс уже завершён.")
    except psutil.AccessDenied:
        raise ValueError("Нет прав на завершение этого процесса.")
    except psutil.TimeoutExpired:
        raise ValueError("Процесс не завершился за 5 секунд.")
    return name


def make_app(features_getter=lambda: None, version=0, pairing=None, browser=False, prefix=""):
    """version 0: the original HTTP API (/api/...). version 1: the same handlers under
    /api/v1/... for the TLS server, with code-based pairing and /api/v1/info.

    browser=True: the same v1 handlers for «Управление ПК» of the web panel, mounted under
    `prefix` (e.g. /pc). Only browser tokens (KIND_WEB) open it, and only over HTTPS from a
    browser paired over HTTPS with «Полный» (web_panel.service.may_control); no pairing route
    and no panel socket there."""
    from modules.monitor import workstation_locked
    pairing = pairing or mobile_access.PAIRING
    pairing_lock = asyncio.Lock()
    pairing_attempts = {}
    PAIR_WINDOW_SECONDS = 60
    PAIR_MAX_ATTEMPTS = 3

    @web.middleware
    async def guard(request, handler):
        # The server is for the home network only: refuse every request from outside it,
        # even with a valid token (e.g. after a port was forwarded on the router).
        if not is_private_ip(request.remote or ""):
            logger.warning("Отклонён запрос не из локальной сети: %s %s", request.remote, request.path)
            return json_error(403, "PulseDeck принимает запросы только из локальной сети.")
        if not host_allowed(request):
            logger.warning("Отклонён запрос с чужим адресом сайта (Host: %s) от %s", request.host[:60], request.remote)
            return json_error(421, "Откройте PulseDeck по IP-адресу ПК.")
        path = request.path
        if prefix and path.startswith(prefix + "/"):
            path = path[len(prefix):]
        if version == 1 and path.startswith("/api/v1/"):
            path = "/api/" + path[len("/api/v1/"):]       # same rules for both versions
        if path not in ("/api/ping", "/api/pair", "/api/info"):
            given = request.headers.get("Authorization", "")
            token = given[7:] if given.startswith("Bearer ") else ""
            device = await asyncio.to_thread(mobile_access.authenticate, token,
                                             mobile_access.KIND_WEB if browser else mobile_access.KIND_APP)
            if not device:
                return json_error(401, "Устройство не подключено или отозвано.")
            if version == 1 and not browser and device.get("legacy"):
                # Paired over the old HTTP protocol: the token may have been seen on the network.
                return json_error(401, "Этот телефон подключён по старому протоколу без шифрования. "
                                       "Подключите его заново по коду (TLS).")
            if browser and not (request.secure and device.get("secure") and mobile_access.can_control(device)):
                return json_error(403, "Управление ПК — только в защищённом режиме (HTTPS) и с доступом «Полный».")
            if not mobile_access.can_control(device) and (path not in VIEW_ONLY_PATHS or request.method != "GET"):
                return json_error(403, "Этот телефон подключён только для просмотра. Доступ меняется в PulseDeck на ПК.")
            # Same rule as the Telegram bot: no control while the PC is locked.
            if path not in READ_WHEN_LOCKED and await asyncio.to_thread(workstation_locked):
                return json_error(423, "ПК заблокирован. Управление недоступно.")
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except ValueError as exc:
            return json_error(400, str(exc))
        except Exception:
            logger.exception("Local API error")
            return json_error(500, "Внутренняя ошибка сервера. Подробности сохранены в журнале PulseDeck.")

    routes = web.RouteTableDef()

    @routes.get("/api/ping")
    async def ping(_):
        return web.json_response({"ok": True, "app": "PulsePC"})

    @routes.get("/api/status")
    async def status(_):
        text = await asyncio.to_thread(computer_info)
        locked = await asyncio.to_thread(workstation_locked)
        features = features_getter()
        power = None
        if features and features.power_task and not features.power_task.done() and features.power_deadline:
            import time
            power = {"action": features.power_action, "seconds": max(0, int(features.power_deadline - time.monotonic()))}
        return web.json_response({"ok": True, "name": socket.gethostname(), "locked": locked, "info": text, "power": power})

    @routes.get("/api/programs")
    async def programs(_):
        items = load_programs()
        return web.json_response({"ok": True, "programs": [
            {"id": p.get("id") or str(i), "name": p["name"]} for i, p in enumerate(items)]})

    def find_program(key):
        for i, program in enumerate(load_programs()):
            if (program.get("id") or str(i)) == key:
                return program
        raise ValueError("Программа не найдена.")

    @routes.post("/api/programs/{key}/run")
    async def run_program(request):
        program = find_program(request.match_info["key"])
        path = os.path.expandvars(program["path"])
        try:
            os.startfile(path)
        except AttributeError:
            subprocess.Popen([path])
        return web.json_response({"ok": True, "message": f"Запущено: {program['name']}"})

    @routes.post("/api/programs/{key}/kill")
    async def kill_program(request):
        program = find_program(request.match_info["key"])
        process = await asyncio.to_thread(effective_process, program)
        if not process:
            raise ValueError("Имя процесса не настроено.")
        ok, error = await kill_process(process)
        if not ok:
            raise ValueError(error or "Не удалось закрыть программу.")
        return web.json_response({"ok": True, "message": f"Закрыто: {program['name']}"})

    @routes.get("/api/volume")
    async def get_volume(_):
        level = await asyncio.to_thread(system_volume.get)
        if level is None:
            raise ValueError("Точная громкость недоступна: установите pycaw (pip install pycaw).")
        return web.json_response({"ok": True, **level})

    @routes.post("/api/volume")
    async def set_volume(request):
        """{level: 0..100} | {delta: -100..100} | {muted: bool}"""
        if not system_volume.AVAILABLE:
            raise ValueError("Точная громкость недоступна: установите pycaw (pip install pycaw).")
        body = await request.json() if request.can_read_body else {}
        if "level" in body:
            if type(body["level"]) is not int:
                raise ValueError("Уровень должен быть числом 0–100.")
            await asyncio.to_thread(system_volume.set_level, body["level"])
        elif "delta" in body:
            if type(body["delta"]) is not int or not -100 <= body["delta"] <= 100:
                raise ValueError("Изменение должно быть числом от -100 до 100.")
            await asyncio.to_thread(system_volume.adjust, body["delta"])
        elif "muted" in body:
            if type(body["muted"]) is not bool:
                raise ValueError("muted: true или false.")
            await asyncio.to_thread(system_volume.set_muted, body["muted"])
        else:
            raise ValueError("Укажите level, delta или muted.")
        return web.json_response({"ok": True, **(await asyncio.to_thread(system_volume.get) or {})})

    @routes.post("/api/media/{action}")
    async def media(request):
        key = MEDIA_KEYS.get(request.match_info["action"])
        if not key:
            raise ValueError("Неизвестное действие.")
        body = await request.json() if request.can_read_body else {}
        count = body.get("count", 1)
        if type(count) is not int or not 1 <= count <= 25:
            raise ValueError("Повторов должно быть от 1 до 25.")
        from modules import keys
        await asyncio.to_thread(keys.press, key, count, 0.02)
        return web.json_response({"ok": True})

    @routes.post("/api/system/{action}")
    async def system(request):
        action = request.match_info["action"]
        if action == "lock":
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif action == "sleep":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
        elif action == "close_active":
            from modules.winutil import close_foreground_window
            title = await asyncio.to_thread(close_foreground_window)
            return web.json_response({"ok": True, "message": f"Закрыто: {title}"})
        elif action in ("shutdown", "restart"):
            features = features_getter()
            if not features:
                raise ValueError("Бот ещё не готов.")
            body = await request.json() if request.can_read_body else {}
            minutes = body.get("minutes", 1)
            if type(minutes) is not int:
                raise ValueError("Укажите минуты числом.")
            features.schedule_power(action, minutes)
        elif action == "cancel":
            features = features_getter()
            cancelled = bool(features and await features.cancel_power())
            return web.json_response({"ok": True, "message": "Таймер отменён." if cancelled else "Нет активного таймера."})
        else:
            raise ValueError("Неизвестное действие.")
        return web.json_response({"ok": True})

    @routes.get("/api/screenshot")
    async def screenshot(request):
        monitor = int(request.query.get("monitor", "0"))
        width = min(max(int(request.query.get("width", "1280")), 320), 3840)

        def grab():
            import mss
            from PIL import Image
            with mss.mss() as sct:
                if not 0 <= monitor < len(sct.monitors):
                    raise ValueError("Монитор не найден.")
                shot = sct.grab(sct.monitors[monitor])
                image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            if image.width > width:
                image = image.resize((width, round(image.height * width / image.width)))
            out = BytesIO()
            image.save(out, format="JPEG", quality=70)
            return out.getvalue()
        return web.Response(body=await asyncio.to_thread(grab), content_type="image/jpeg")

    @routes.post("/api/open_url")
    async def open_url(request):
        url = str((await request.json()).get("url", "")).strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("Нужна ссылка http:// или https://")
        webbrowser.open(url)
        return web.json_response({"ok": True})

    @routes.get("/api/windows")
    async def windows(_):
        from modules.bot_features import list_windows
        items = await asyncio.to_thread(list_windows)
        return web.json_response({"ok": True, "windows": items[:40]})

    @routes.post("/api/windows/{hwnd}/{action}")
    async def window_action(request):
        from modules.bot_features import list_windows, change_window
        hwnd = int(request.match_info["hwnd"])
        window = next((w for w in await asyncio.to_thread(list_windows) if w["hwnd"] == hwnd), None)
        if not window:
            raise ValueError("Это окно уже закрыто. Обновите список.")
        if request.match_info["action"] == "close":
            import win32gui
            import win32con
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        else:
            await asyncio.to_thread(change_window, window, request.match_info["action"])
        return web.json_response({"ok": True})

    # ---- Files ----
    @routes.get("/api/files/roots")
    async def files_roots(_):
        from modules.bot_features import file_roots
        roots = await asyncio.to_thread(file_roots)
        return web.json_response({"ok": True, "roots": [{"name": t, "path": str(p)} for t, p in roots]})

    def scan_directory(path):
        from pathlib import Path
        target = Path(path).resolve(strict=True)
        if not target.is_dir():
            raise ValueError("Это не папка.")
        items = []
        with os.scandir(target) as scan:
            for entry in scan:
                if len(items) >= 2000:
                    break
                try:
                    is_dir = entry.is_dir()
                    size = 0 if is_dir else entry.stat().st_size
                except OSError:
                    continue
                items.append({"name": entry.name, "dir": is_dir, "size": size})
        items.sort(key=lambda i: (not i["dir"], i["name"].casefold()))
        parent = str(target.parent) if target.parent != target else ""
        return {"ok": True, "path": str(target), "parent": parent, "items": items}

    @routes.get("/api/files/list")
    async def files_list(request):
        path = request.query.get("path", "")
        if not path:
            raise ValueError("Не указана папка.")
        try:
            return web.json_response(await asyncio.to_thread(scan_directory, path))
        except OSError as exc:
            raise ValueError(f"Папка недоступна: {exc.strerror or exc}")

    @routes.get("/api/files/download")
    async def files_download(request):
        from modules.transfer_history import record_transfer
        from pathlib import Path
        path = Path(request.query.get("path", "")).resolve()
        if not path.is_file():
            raise ValueError("Файл не найден.")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Файл больше 200 МБ.")
        record_transfer(path, "outgoing", "sent")
        return web.FileResponse(path, headers={"Content-Disposition": "attachment"})

    @routes.post("/api/files/upload")
    async def files_upload(request):
        from pathlib import Path
        from modules.transfer_history import record_transfer
        name = Path(request.query.get("name", "file").replace("\\", "/")).name
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")[:160] or "file"
        target_dir = Path(config.FILES_DIR)
        target_dir.mkdir(exist_ok=True)
        target = target_dir / name
        counter = 1
        while target.exists():
            target = target_dir / f"{Path(name).stem}_{counter}{Path(name).suffix}"
            counter += 1
        part = target.with_name(target.name + ".part")
        size = 0
        try:
            with open(part, "wb") as stream:
                async for chunk in request.content.iter_chunked(1 << 16):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise ValueError("Файл больше 200 МБ.")
                    await asyncio.to_thread(stream.write, chunk)
            if size == 0:
                raise ValueError("Пустой файл.")
            os.replace(part, target)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        record_transfer(target, "incoming", "received")
        return web.json_response({"ok": True, "message": f"Сохранено на ПК: {target.name}"})

    def target_path(raw, must_exist=True):
        from pathlib import Path
        if not raw:
            raise ValueError("Не указан путь.")
        path = Path(raw)
        if not path.is_absolute():
            raise ValueError("Нужен полный путь.")
        try:
            path = path.resolve(strict=must_exist)
        except FileNotFoundError:
            raise ValueError("Файл или папка не найдены. Обновите список.")
        if path.parent == path:
            raise ValueError("С корнем диска так нельзя.")
        return path

    def clean_name(name):
        name = (name or "").strip()
        if not name or name in (".", "..") or any(c in name for c in '<>:"/\\|?*') or len(name) > 200:
            raise ValueError("Недопустимое имя.")
        return name

    @routes.post("/api/files/mkdir")
    async def files_mkdir(request):
        data = await request.json()
        parent = target_path(data.get("path"))
        if not parent.is_dir():
            raise ValueError("Это не папка.")
        folder = parent / clean_name(data.get("name"))
        if folder.exists():
            raise ValueError("Такое имя уже есть.")
        await asyncio.to_thread(folder.mkdir)
        return web.json_response({"ok": True, "path": str(folder)})

    @routes.post("/api/files/rename")
    async def files_rename(request):
        data = await request.json()
        source = target_path(data.get("path"))
        target = source.with_name(clean_name(data.get("name")))
        if target.exists():
            raise ValueError("Такое имя уже есть.")
        await asyncio.to_thread(source.rename, target)
        return web.json_response({"ok": True, "path": str(target)})

    @routes.post("/api/files/delete")
    async def files_delete(request):
        data = await request.json()
        path = target_path(data.get("path"))
        await asyncio.to_thread(to_recycle_bin, path)      # never a permanent delete from the phone
        return web.json_response({"ok": True, "message": f"В корзине: {path.name}"})

    def file_info(path):
        from datetime import datetime
        stat = path.stat()
        when = lambda t: datetime.fromtimestamp(t).strftime("%d.%m.%Y %H:%M")
        info = {"ok": True, "name": path.name, "path": str(path), "dir": path.is_dir(),
                "size": 0 if path.is_dir() else stat.st_size,
                "modified": when(stat.st_mtime), "created": when(getattr(stat, "st_birthtime", stat.st_ctime))}
        if path.is_dir():
            count = 0
            try:
                with os.scandir(path) as scan:
                    for _ in scan:
                        count += 1
                        if count >= 10000:
                            break
            except OSError:
                count = -1
            info["items"] = count
        return info

    @routes.get("/api/files/info")
    async def files_info(request):
        path = target_path(request.query.get("path", ""))
        return web.json_response(await asyncio.to_thread(file_info, path))

    @routes.post("/api/files/open")
    async def files_open(request):
        # Opens with the program Windows has for it, on the PC's screen (the phone asks first for programs).
        data = await request.json()
        path = target_path(data.get("path"))
        await asyncio.to_thread(os.startfile, str(path))
        return web.json_response({"ok": True, "message": f"Открыто на ПК: {path.name}"})

    @routes.post("/api/files/reveal")
    async def files_reveal(request):
        data = await request.json()
        path = target_path(data.get("path"))
        subprocess.Popen(["explorer", f"/select,{path}"])
        return web.json_response({"ok": True, "message": f"Показано в папке: {path.name}"})

    # ---- Processes ----
    @routes.get("/api/processes")
    async def processes(_):
        return web.json_response({"ok": True, "processes": await asyncio.to_thread(list_processes)})

    @routes.post("/api/processes/{pid}/kill")
    async def process_kill(request):
        try:
            pid = int(request.match_info["pid"])
        except ValueError:
            raise ValueError("Неверный PID.")
        name = await asyncio.to_thread(end_process, pid)
        return web.json_response({"ok": True, "message": f"Завершён: {name}"})

    @routes.get("/api/history")
    async def history(_):
        from modules.transfer_history import load_history
        items = await asyncio.to_thread(load_history)
        return web.json_response({"ok": True, "history": list(reversed(items))})

    # ---- Scenarios, search, monitors ----
    @routes.get("/api/scenarios")
    async def scenarios(_):
        from modules.bot_preferences import load_preferences
        prefs = await asyncio.to_thread(load_preferences)
        return web.json_response({"ok": True, "scenarios": [
            {"id": s["id"], "name": s["name"], "count": len(s["program_ids"])} for s in prefs["scenarios"]]})

    @routes.post("/api/scenarios/{key}/run")
    async def run_scenario(request):
        features = features_getter()
        if not features:
            raise ValueError("Бот ещё не готов.")
        launched = await features.run_scenario(request.match_info["key"])
        return web.json_response({"ok": True, "message": "Запущено: " + ", ".join(launched)})

    @routes.post("/api/search")
    async def search(request):
        import urllib.parse
        query = str((await request.json()).get("query", "")).strip()
        if not query:
            raise ValueError("Введите запрос.")
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
        return web.json_response({"ok": True})

    @routes.get("/api/monitors")
    async def monitors(_):
        def count():
            import mss
            with mss.mss() as sct:
                return len(sct.monitors) - 1
        return web.json_response({"ok": True, "count": await asyncio.to_thread(count)})

    # ---- Player (shared with the web panel: modules/player_access.py) ----
    external_player = player_access.external_player
    current_player = player_access.current_player
    control_player = player_access.control_player

    @routes.get("/api/player/state")
    async def player_state(request):
        data = await current_player(request.query.get("source", ""))
        level = await asyncio.to_thread(system_volume.get)        # exact PC volume when pycaw is installed
        return web.json_response({"ok": True, "player": data or {"status": "none"}, "system_volume": level})

    @routes.get("/api/player/sessions")
    async def player_sessions(_):
        """Everything that can be controlled: the built-in player and media sessions of other apps."""
        return web.json_response({"ok": True, "sessions": await player_access.sessions()})

    @routes.post("/api/player/focus")
    async def player_focus(request):
        """Show the window of the app that is playing (streaming service or browser) on the PC."""
        body = await request.json() if request.can_read_body else {}
        source = str(body.get("source") or "")
        data = await external_player(source or None)
        if not data:
            raise ValueError("Сейчас нечего открывать.")
        title = await asyncio.to_thread(now_playing.focus_source_window, data["id"], data["title"])
        return web.json_response({"ok": True, "message": f"Открыто на ПК: {title}"})

    @routes.get("/api/player/cover")
    async def player_cover(request):
        found = player_access.cover(request.query.get("key", ""))
        if not found:
            return json_error(404, "Обложки нет.")
        return web.Response(body=found[0], content_type=found[1])

    @routes.post("/api/player/tracks/open")
    async def player_open(request):
        path = str((await request.json()).get("path", ""))
        if not await asyncio.to_thread(player_bridge.is_library_track, path):
            raise ValueError("Этого трека нет в библиотеке плеера PulseDeck.")
        player_bridge.send("open", path)
        return web.json_response({"ok": True})

    @routes.get("/api/player/tracks")
    async def player_tracks(_):
        tracks = await asyncio.to_thread(player_bridge.scan_tracks)
        return web.json_response({"ok": True, "tracks": tracks})

    @routes.post("/api/player/{cmd}")
    async def player_command(request):
        body = await request.json() if request.can_read_body else {}
        await control_player(request.match_info["cmd"], body.get("value"), str(body.get("source") or ""))
        return web.json_response({"ok": True})

    # ---- Notifications for the phone ----
    @routes.get("/api/events")
    async def events(request):
        items, last = notify_bus.since(int(request.query.get("after", "-1")))
        return web.json_response({"ok": True, "events": items, "last": last})

    # ---- Pairing ----
    @routes.post("/api/pair")
    async def pair(request):
        # The phone asks to be added; the PC owner must approve it in a dialog.
        if not mobile_access.load()["allow_pairing"]:
            return json_error(403, "Новые устройства отключены в настройках PulseDeck (вкладка «Телефон»).")
        if not is_private_ip(request.remote or ""):
            return json_error(403, "Сопряжение доступно только из локальной сети.")
        if pairing_lock.locked():
            return json_error(409, "На ПК уже открыт запрос. Ответьте на него.")
        # Bound owner-confirmation prompts per remote address to reduce dialog spam.
        now = time.monotonic()
        for address, timestamps in list(pairing_attempts.items()):
            fresh = [stamp for stamp in timestamps if now - stamp < PAIR_WINDOW_SECONDS]
            if fresh:
                pairing_attempts[address] = fresh
            else:
                del pairing_attempts[address]
        remote = request.remote or ""
        recent = pairing_attempts.setdefault(remote, [])
        if len(recent) >= PAIR_MAX_ATTEMPTS:
            return json_error(429, "Слишком много запросов подключения. Попробуйте через минуту.")
        recent.append(now)
        try:
            device = clean_device_name((await request.json()).get("device"))
        except ValueError:
            device = "Телефон"
        async with pairing_lock:
            try:
                allowed = await asyncio.wait_for(asyncio.to_thread(
                    ask_owner, f"Телефон «{device}» ({request.remote}) хочет управлять этим ПК.\n\nРазрешить?"), timeout=60)
            except asyncio.TimeoutError:
                return json_error(408, "На ПК не ответили на запрос.")
            if not allowed:
                return json_error(403, "Владелец ПК отклонил подключение.")
            token = await asyncio.to_thread(mobile_access.add_device, device, legacy=True)
        logger.info("Phone paired: %s (%s)", device, request.remote)
        return web.json_response({"ok": True, "token": token, "name": socket.gethostname()})

    async def info(_):
        return web.json_response({"ok": True, "app": "PulsePC", "api": 1, "pairing": pairing.active()})

    async def pair_with_code(request):
        # The owner pressed «Подключить по коду» on the PC; the phone proves it saw the code.
        try:
            body = await request.json()
        except ValueError:
            body = {}
        device = clean_device_name(body.get("device") if isinstance(body, dict) else None)
        if not pairing.active():
            return json_error(403, "Сначала нажмите «Подключить по коду» на ПК.")
        if not pairing.verify(body.get("code")):
            logger.warning("Неверный код сопряжения от %s", request.remote)
            return json_error(403, "Неверный код." if pairing.active() else "Код больше не действует. Запросите новый на ПК.")
        token = await asyncio.to_thread(mobile_access.add_device, device)
        logger.info("Телефон «%s» подключён по коду (%s)", device, request.remote)
        return web.json_response({"ok": True, "token": token, "name": socket.gethostname(), "api": 1})

    app = web.Application(middlewares=[guard], client_max_size=MAX_FILE_BYTES + (1 << 20))
    if version == 1:
        if not browser:
            from modules.display_api import add_display_route
            add_display_route(app, current_player, control_player, workstation_locked, player_access.sessions)
            app.router.add_post("/api/v1/pair", pair_with_code)
        app.router.add_get("/api/v1/info", info)
        for route in routes:
            if route.path in ("/api/ping", "/api/pair"):
                continue    # replaced by /api/v1/info and code pairing
            app.router.add_route(route.method, "/api/v1/" + route.path[len("/api/"):], route.handler, **route.kwargs)
    else:
        app.add_routes(routes)
    return app


class DiscoveryProtocol(asyncio.DatagramProtocol):
    # "PULSEPC?" / "app": "PulsePC" are protocol identifiers the phone apps look for; keep them.
    """Answers the phone's UDP broadcast "PULSEPC?" with this PC's name and port.
    With API v1 running the reply also has "tls_port" and "api" (extra keys; v0 clients ignore them)."""
    def __init__(self, port, tls_port=None):
        self.port = port
        self.tls_port = tls_port

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if data.strip() == b"PULSEPC?" and is_private_ip(addr[0]):
            data = {"app": "PulsePC", "name": socket.gethostname(), "port": self.port}
            if self.tls_port:
                data.update(tls_port=self.tls_port, api=[0, 1] if self.port else [1])
            reply = json.dumps(data)
            self.transport.sendto(reply.encode(), addr)


class LocalApiServer:
    """v0 over HTTP (settings «legacy_http») and, when `tls_context` is given, v1 over TLS."""

    def __init__(self, log_callback, features_getter=lambda: None, tls_context=None):
        self.log = log_callback
        self.features_getter = features_getter
        self.tls_context = tls_context      # callable returning an ssl.SSLContext, or None
        self.runner = None                  # v0 (HTTP)
        self.runner_v1 = None               # v1 (TLS)
        self.discovery = None

    @property
    def running(self):
        return self.runner is not None or self.runner_v1 is not None

    async def _serve(self, app, port, ssl_context=None):
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, "0.0.0.0", port, ssl_context=ssl_context).start()
        except OSError as exc:
            self.log(f"Локальный API не запущен (порт {port}): {exc}")
            await runner.cleanup()
            return None
        return runner

    async def start(self):
        settings = mobile_access.load()
        if not settings["enabled"]:
            return
        if settings.get("legacy_http", True) or self.tls_context is None:
            self.runner = await self._serve(make_app(self.features_getter), settings["port"])
        if self.tls_context is not None:
            try:
                context = await asyncio.to_thread(self.tls_context)
            except Exception as exc:  # noqa: BLE001 - v0 keeps working without TLS
                self.log(f"Защищённое подключение (TLS) недоступно: {exc}")
            else:
                self.runner_v1 = await self._serve(make_app(self.features_getter, version=1),
                                                   settings["tls_port"], context)
        if not self.running:
            return
        port = settings["port"] if self.runner else 0
        tls_port = settings["tls_port"] if self.runner_v1 else None
        try:
            loop = asyncio.get_running_loop()
            self.discovery, _ = await loop.create_datagram_endpoint(
                lambda: DiscoveryProtocol(port, tls_port), local_addr=("0.0.0.0", mobile_access.DISCOVERY_PORT))
        except OSError as exc:
            self.log(f"Автопоиск телефоном недоступен (UDP {mobile_access.DISCOVERY_PORT}): {exc}")
        shown = settings["port"] if self.runner else settings["tls_port"]
        addresses = [f"{ip}:{shown}" for ip in lan_addresses()]
        mobile_access.STATE.update(running=True, port=shown, addresses=addresses)
        modes = ", ".join(m for m, on in (("HTTP v0", self.runner), ("TLS v1", self.runner_v1)) if on)
        self.log(f"Мобильный доступ ({modes}): {', '.join(addresses) or shown}. Телефоны: {len(settings['devices'])}")

    async def close(self):
        mobile_access.STATE.update(running=False, addresses=[])
        if self.discovery:
            self.discovery.close()
            self.discovery = None
        for name in ("runner", "runner_v1"):
            runner = getattr(self, name)
            if runner:
                await runner.cleanup()
                setattr(self, name, None)
