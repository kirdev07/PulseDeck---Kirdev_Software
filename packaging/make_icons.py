"""Render image/icon.ico (exe, installer, shortcuts) and image/logo.png (README) from the
logo in pulse_pc/ui/theme/icons.py, so every place shows the same mark.

    .venv\\Scripts\\python packaging\\make_icons.py
"""
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from pulse_pc.ui.theme.icons import logo_pixmap  # noqa: E402

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(size):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    logo_pixmap(size).save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def main():
    _app = QGuiApplication.instance() or QGuiApplication([])
    images = [render(size) for size in ICO_SIZES]
    images[-1].save(ROOT / "image" / "icon.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    render(512).save(ROOT / "image" / "logo.png")
    print("image/icon.ico, image/logo.png")


if __name__ == "__main__":
    main()
