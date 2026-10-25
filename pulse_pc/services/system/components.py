"""Third-party components actually installed, with versions and declared licenses."""
from importlib import metadata

# Runtime dependencies from requirements*.txt (import name -> distribution name).
DISTRIBUTIONS = ("PySide6", "aiogram", "aiohttp", "python-dotenv", "psutil", "pywin32", "mss",
                 "pillow", "cryptography", "pycaw", "winrt-runtime", "winrt-Windows.Media.Control")


def license_of(meta):
    expression = meta.get("License-Expression")
    if expression:
        return expression
    value = (meta.get("License") or "").strip()
    if value and len(value) < 60 and "\n" not in value:
        return value
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return ", ".join(classifiers) or "см. страницу проекта"


def installed():
    items = []
    for name in DISTRIBUTIONS:
        try:
            meta = metadata.metadata(name)
        except metadata.PackageNotFoundError:
            continue
        items.append({"name": meta["Name"], "version": meta["Version"], "license": license_of(meta),
                      "url": meta.get("Home-page") or next((u.split(",", 1)[-1].strip() for u in
                                                             meta.get_all("Project-URL") or []), "")})
    return items
