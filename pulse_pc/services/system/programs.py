"""Configured programs: storage (config/programs.json, shared with Telegram and the phone
API), launching, closing and live resource usage of their processes."""
import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import psutil

from modules.program_store import effective_process, executable_process, validate_programs

MAX_PROGRAMS = 15   # Telegram menu limit; the bot and the phone show the same list
LAUNCHABLE = (".exe", ".lnk", ".bat", ".cmd")


class ProgramsFileError(Exception):
    """programs.json exists but cannot be read; never overwrite it silently."""


def atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ProgramStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return []
        try:
            programs = validate_programs(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise ProgramsFileError(f"Не удалось прочитать {self.path.name}: {exc}") from exc
        changed = False
        for program in programs:
            if not program.get("id"):
                program["id"] = uuid.uuid4().hex
                changed = True
        if changed:
            self.save(programs)
        return programs

    def save(self, programs):
        validate_programs(programs)
        if len(programs) > MAX_PROGRAMS:
            raise ValueError(f"Не больше {MAX_PROGRAMS} программ.")
        atomic_write_json(self.path, programs)

    @staticmethod
    def make(name, path, description=""):
        name, path = name.strip(), path.strip().strip('"')
        if not name or not path:
            raise ValueError("Укажите название и путь к программе.")
        if len(name) > 40:
            raise ValueError("Название — не длиннее 40 символов.")
        if not Path(os.path.expandvars(path)).is_file():
            raise ValueError("Файл не найден. Проверьте путь к программе.")
        return {"name": name, "path": path, "process": executable_process(path),
                "description": description.strip()[:130]}

    def add(self, name, path, description=""):
        programs = self.load()
        if len(programs) >= MAX_PROGRAMS:
            raise ValueError(f"Не больше {MAX_PROGRAMS} программ: Telegram показывает их одним меню.")
        program = {**self.make(name, path, description), "id": uuid.uuid4().hex}
        programs.append(program)
        self.save(programs)
        return program

    def update(self, program_id, name, path, description=""):
        programs = self.load()
        program = self._find(programs, program_id)
        program.update(self.make(name, path, description))
        self.save(programs)
        return program

    def remove(self, program_id):
        programs = self.load()
        self._find(programs, program_id)
        self.save([p for p in programs if p["id"] != program_id])

    def move(self, program_id, offset):
        programs = self.load()
        index = programs.index(self._find(programs, program_id))
        target = index + offset
        if 0 <= target < len(programs):
            programs[index], programs[target] = programs[target], programs[index]
            self.save(programs)
        return programs

    @staticmethod
    def _find(programs, program_id):
        for program in programs:
            if program.get("id") == program_id:
                return program
        raise ValueError("Программа не найдена. Обновите список.")


def launch(program):
    path = Path(os.path.expandvars(program["path"]))
    if not path.is_file():
        raise ValueError("Файл не найден. Измените путь к программе.")
    try:
        os.startfile(str(path))
    except AttributeError:      # not Windows (tests on other systems)
        subprocess.Popen([str(path)])


def process_names(program):
    """Lower-case names that identify the program's processes, e.g. {'obs64.exe'}."""
    name = (effective_process(program) or "").strip().lower()
    if not name:
        return set()
    return {name, name if name.endswith(".exe") else name + ".exe"}


def close(program):
    """Terminate every process of the program. Returns how many were stopped."""
    names = process_names(program)
    if not names:
        raise ValueError("Имя процесса не определено: программа запускается через ярлык или скрипт без .exe.")
    victims = [p for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() in names]
    if not victims:
        raise ValueError("Программа не запущена.")
    for proc in victims:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(victims, timeout=3)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, still = psutil.wait_procs(alive, timeout=2)
    if still:
        raise PermissionError("Нет прав завершить процесс. Запустите PulseDeck от имени администратора.")
    return len(victims)


@dataclass
class Usage:
    running: bool = False
    count: int = 0
    cpu: float = 0.0        # percent of the whole machine
    memory: int = 0         # resident bytes


class UsageSampler:
    """CPU and RAM of the configured programs. CPU percent needs two readings of the
    same process object, so processes are kept between samples."""

    def __init__(self):
        self._procs = {}
        self.cores = psutil.cpu_count(logical=True) or 1

    def sample(self, programs):
        wanted = {}
        for program in programs:
            for name in process_names(program):
                wanted.setdefault(name, []).append(program["id"])
        result = {program["id"]: Usage() for program in programs}
        seen = set()
        for proc in psutil.process_iter(["name"]):
            name = (proc.info["name"] or "").lower()
            if name not in wanted:
                continue
            proc = self._procs.setdefault(proc.pid, proc)
            seen.add(proc.pid)
            try:
                cpu = proc.cpu_percent(None) / self.cores
                memory = proc.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            for program_id in set(wanted[name]):
                usage = result[program_id]
                usage.running = True
                usage.count += 1
                usage.cpu += cpu
                usage.memory += memory
        self._procs = {pid: proc for pid, proc in self._procs.items() if pid in seen}
        return result
