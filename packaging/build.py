"""Build the Windows installer: PyInstaller folder build, then Inno Setup.

    .venv\\Scripts\\python packaging\\build.py            -> dist\\PulseDeck-<version>-Setup.exe
    .venv\\Scripts\\python packaging\\build.py --no-installer   (folder build only)

Needs (development only, not shipped to users): PyInstaller in the venv and Inno Setup 6.
"""
import os
import shutil
import subprocess
import sys
import time
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


def sync_version_info():
    """version_info.txt (the exe's file properties) follows pulse_pc.__version__."""
    import re
    path = ROOT / "packaging" / "version_info.txt"
    numbers = ", ".join((VERSION.split(".") + ["0"] * 4)[:4])
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(filevers|prodvers)=\([^)]*\)", rf"\1=({numbers})", text)
    text = re.sub(r"'(FileVersion|ProductVersion)', '[^']*'", rf"'\1', '{VERSION}'", text)
    path.write_text(text, encoding="utf-8")


def main(argv):
    sync_version_info()
    subprocess.run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "pulse_pc.spec"), "--noconfirm",
                    "--distpath", str(DIST), "--workpath", str(WORK)], check=True, cwd=ROOT)
    folder = DIST / "PulseDeck"
    print(f"\nПапка программы: {folder} — {size_mb(folder):.0f} МБ")
    if "--no-installer" in argv:
        return 0
    portable = DIST / f"PulseDeck-{VERSION}-Portable.zip"
    portable.unlink(missing_ok=True)
    shutil.make_archive(str(portable.with_suffix("")), "zip", DIST, "PulseDeck")
    print(f"Портативная версия: {portable} — {size_mb(portable):.1f} МБ")
    command = [find_iscc(), f"/DAppVersion={VERSION}", f"/DSourceDir={folder}", f"/DOutputDir={DIST}",
               str(ROOT / "packaging" / "installer.iss")]
    # Right after PyInstaller the antivirus may still hold freshly written files; ISCC then
    # fails with exit code 2. A pause and a retry is enough.
    for attempt in range(3):
        result = subprocess.run(command, cwd=ROOT / "packaging", capture_output=True, text=True, errors="replace")
        if result.returncode == 0:
            break
        print(f"Inno Setup: ошибка (попытка {attempt + 1}), повтор через 15 с…\n{result.stdout[-1500:]}")
        time.sleep(15)
    else:
        raise SystemExit("Inno Setup не смог собрать установщик, см. вывод выше.")
    setup = DIST / f"PulseDeck-{VERSION}-Setup.exe"
    print(f"Установщик: {setup} — {size_mb(setup):.1f} МБ")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
