# PyInstaller spec for PulseDeck (one folder: PulseDeck.exe + _internal/).
# Build: python packaging/build.py   (wraps PyInstaller and Inno Setup)
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
import sys
sys.path.insert(0, str(ROOT))      # collect_submodules imports the packages to list them
LEAN = os.environ.get("PULSE_PC_LEAN", "1") == "1"   # 0 = baseline build for size comparison

# Loaded with importlib at run time, so the analysis cannot see them.
hidden = collect_submodules("modules") + collect_submodules("pulse_pc") + [
    "desktop_services", "player_controller", "bot_options_ui", "config",
    "winrt.windows.media.control", "winrt.windows.storage.streams", "winrt.windows.foundation",
    "winrt.windows.foundation.collections", "pycaw.pycaw", "comtypes.stream",
]

# Parts of Qt and Python that PulseDeck never uses. Each one was checked with grep and by
# running the built app; see docs/BUILD.md for sizes.
EXCLUDES = [
    # unittest stays: aiogram imports unittest.mock at start-up.
    "tkinter", "_tkinter", "pydoc", "test", "lib2to3", "idlelib", "turtledemo",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtWebSockets", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
    "PySide6.QtSpatialAudio", "PySide6.QtHttpServer", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtAxContainer", "PySide6.QtCanvasPainter",
] if LEAN else []

datas = [(str(ROOT / name), ".") for name in
         ("LICENSE", "PRIVACY_POLICY.md", "TERMS_OF_USE.md", "THIRD_PARTY_NOTICES.md")]
datas.append((str(ROOT / "image" / "icon.ico"), "image"))

a = Analysis(
    [str(ROOT / "pulse_pc" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hidden,
    excludes=EXCLUDES,
    noarchive=False,
)

if LEAN:
    # Qt translations other than Russian/English and Qt plugins nobody loads.
    def keep(entry):
        name = entry[0].replace("\\", "/").lower()
        if "/translations/" in name and not any(f"_{lang}." in name for lang in ("ru", "en")):
            return False
        for unused in ("/plugins/qmltooling/", "/plugins/sqldrivers/", "/plugins/designer/", "/plugins/sensors/",
                       "/plugins/position/", "/plugins/geoservices/", "/plugins/texttospeech/", "/plugins/canbus/",
                       "/qml/", "qt6webengine", "qt6quick", "qt6qml", "qt6pdf", "qt6designer", "qt63d",
                       "qt6charts", "qt6datavisualization", "qt6graphs", "opengl32sw.dll", "qt6virtualkeyboard"):
            if unused in name:
                return False
        return True
    a.binaries = [entry for entry in a.binaries if keep(entry)]
    a.datas = [entry for entry in a.datas if keep(entry)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PulseDeck",
    icon=str(ROOT / "image" / "icon.ico"),
    console=False,
    version=str(ROOT / "packaging" / "version_info.txt"),
    upx=False,          # UPX-packed DLLs often trigger antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, name="PulseDeck", upx=False)
