"""Start PulseDeck from the source code (double-click, no console).

For users the installer (PulseDeck-<version>-Setup.exe) is the normal way. This file stays
for running from a checkout and for shortcuts and autostart entries created by 1.x: when
the interpreter that opened it lacks the packages, it restarts itself with the project's
.venv.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def has_packages():
    try:
        import PySide6, aiogram  # noqa: F401,E401
        return True
    except ImportError:
        return False


def main():
    if not has_packages():
        venv = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        if venv.exists() and Path(sys.executable).resolve() != venv.resolve():
            subprocess.Popen([str(venv), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return 0
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "Не найдены библиотеки PulseDeck.\n\nУстановите программу с помощью PulseDeck-Setup.exe "
               "или выполните в папке проекта:\npython -m venv .venv\n.venv\\Scripts\\pip install -r requirements.txt",
            "PulseDeck", 0x10)
        return 1
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    from pulse_pc.app import main as run
    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
