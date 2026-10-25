"""Build the Windows installer: PyInstaller folder build, then Inno Setup.

    .venv\\Scripts\\python packaging\\build.py            -> dist\\Pulse-PC-<version>-Setup.exe
    .venv\\Scripts\\python packaging\\build.py --no-installer   (folder build only)

Needs (development only, not shipped to users): PyInstaller in the venv and Inno Setup 6.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
WORK = ROOT / "build"
sys.path.insert(0, str(ROOT))
from pulse_pc import __version__  # noqa: E402

VERSION = __version__.split("-")[0]     # Inno/Windows need a plain x.y.z


def find_iscc():
    for candidate in (shutil.which("ISCC"),
                      Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
                      Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
                      Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe"):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise SystemExit("Inno Setup 6 не найден (ISCC.exe). Установите: winget install JRSoftware.InnoSetup")


def size_mb(path):
    path = Path(path)
    total = path.stat().st_size if path.is_file() else sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return total / 1024 / 1024


def main(argv):
    subprocess.run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "pulse_pc.spec"), "--noconfirm",
                    "--distpath", str(DIST), "--workpath", str(WORK)], check=True, cwd=ROOT)
    folder = DIST / "Pulse-PC"
    print(f"\nПапка программы: {folder} — {size_mb(folder):.0f} МБ")
    if "--no-installer" in argv:
        return 0
    subprocess.run([find_iscc(), f"/DAppVersion={VERSION}", f"/DSourceDir={folder}", f"/DOutputDir={DIST}",
                    str(ROOT / "packaging" / "installer.iss")], check=True, cwd=ROOT / "packaging")
    setup = DIST / f"Pulse-PC-{VERSION}-Setup.exe"
    print(f"Установщик: {setup} — {size_mb(setup):.1f} МБ")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
