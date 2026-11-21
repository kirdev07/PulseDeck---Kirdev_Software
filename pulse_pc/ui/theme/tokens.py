"""Design tokens: every colour, size and duration lives here.

The palette is Material 3 (Material You): one accent seed gives tonal roles — primary,
containers, surfaces of five steps, outlines. The owner picks in «Настройки → Оформление»
(config/app_settings.json, read once at start, so every widget built afterwards uses it):

  * style: «color» (an accent) or «mono» — the strict black-and-white look of PulseDeck 1.0;
  * accent: purple (default), blue, green, orange, pink;
  * mode: dark, light or «system» (follows Windows);
  * amoled: pure black window in the dark mode;
  * background: «glow» (soft accent light from the corners), «dots» or «flat».

The old names (BG, SURFACE, TEXT_2, ACCENT …) keep their meaning, so every screen follows.
"""
import json
import os

# Material 3 baseline schemes, in this order:
# primary, on primary, primary container, on primary container, secondary container,
# on secondary container, surface, container low, container, container high, container
# highest, on surface, on surface variant, outline, outline variant, error.
_SCHEMES = {
    "purple": {
        "dark": ("#D0BCFF", "#381E72", "#4F378B", "#EADDFF", "#4A4458", "#E8DEF8", "#141218", "#1D1B20", "#211F26",
                 "#2B2930", "#36343B", "#E6E0E9", "#CAC4D0", "#938F99", "#49454F", "#F2B8B5"),
        "light": ("#6750A4", "#FFFFFF", "#EADDFF", "#21005D", "#E8DEF8", "#1D192B", "#FEF7FF", "#F7F2FA", "#F3EDF7",
                  "#ECE6F0", "#E6E0E9", "#1D1B20", "#49454F", "#79747E", "#CAC4D0", "#B3261E"),
    },
    "blue": {
        "dark": ("#9ECAFF", "#003258", "#00497D", "#D1E4FF", "#3B4858", "#D7E3F7", "#111418", "#191C20", "#1D2024",
                 "#272A2F", "#32353A", "#E1E2E8", "#C3C7CF", "#8D9199", "#43474E", "#FFB4AB"),
        "light": ("#0061A4", "#FFFFFF", "#D1E4FF", "#001D36", "#D7E3F7", "#101C2B", "#F8F9FF", "#F2F3FA", "#ECEEF4",
                  "#E6E8EE", "#E1E2E8", "#191C20", "#43474E", "#73777F", "#C3C7CF", "#BA1A1A"),
    },
    "green": {
        "dark": ("#9DD67F", "#0E3900", "#215107", "#B8F397", "#3B4B32", "#D7E8CB", "#11140F", "#191D17", "#1D211B",
                 "#282B25", "#33362F", "#E1E4DA", "#C3C8BB", "#8D9286", "#43483E", "#FFB4AB"),
        "light": ("#386A20", "#FFFFFF", "#B8F397", "#042100", "#D7E8CB", "#121F0C", "#F8FBF1", "#F2F5EB", "#ECEFE5",
                  "#E7E9E0", "#E1E4DA", "#191D17", "#43483E", "#74796D", "#C3C8BB", "#BA1A1A"),
    },
    "orange": {
        "dark": ("#FFB870", "#4A2800", "#693C00", "#FFDCBE", "#59422C", "#FFDCBE", "#19120C", "#221A14", "#261E18",
                 "#312822", "#3C332C", "#EFE0D6", "#D5C3B5", "#9E8E81", "#51443A", "#FFB4AB"),
        "light": ("#8B5000", "#FFFFFF", "#FFDCBE", "#2C1600", "#FCDEC5", "#2B1709", "#FFF8F5", "#FFF1E9", "#FCEBE2",
                  "#F6E5DC", "#F0DFD7", "#211A14", "#51443A", "#837468", "#D5C3B5", "#BA1A1A"),
    },
    "pink": {
        "dark": ("#FFB0C8", "#5E1133", "#7B2949", "#FFD9E2", "#5A3F48", "#FFD9E2", "#191113", "#22191C", "#261D20",
                 "#31282A", "#3C3235", "#EFDFE1", "#D5C2C6", "#9E8C90", "#514347", "#FFB4AB"),
        "light": ("#984061", "#FFFFFF", "#FFD9E2", "#3E001D", "#FFD9E2", "#2B151C", "#FFF8F8", "#FFF0F2", "#FAEAED",
                  "#F4E4E7", "#EEDEE1", "#22191C", "#514347", "#837377", "#D5C2C6", "#BA1A1A"),
    },
    # The black-and-white look: brightness only, as PulseDeck 1.0.
    "mono": {
        "dark": ("#FFFFFF", "#000000", "#3A3A3A", "#F2F2F2", "#2A2A2A", "#F2F2F2", "#000000", "#070707", "#0E0E0E",
                 "#171717", "#202020", "#F2F2F2", "#A6A6A6", "#6E6E6E", "#2C2C2C", "#F2F2F2"),
        "light": ("#1A1A1A", "#FFFFFF", "#E0E0E0", "#111111", "#EBEBEB", "#111111", "#FFFFFF", "#F6F6F6", "#F0F0F0",
                  "#E8E8E8", "#E0E0E0", "#111111", "#555555", "#888888", "#D6D6D6", "#111111"),
    },
}
ACCENTS = ("purple", "blue", "green", "orange", "pink")
# The seed colour of each accent, for the swatches in «Оформление».
SEEDS = {"purple": "#6750A4", "blue": "#0061A4", "green": "#386A20", "orange": "#8B5000", "pink": "#984061",
         "mono": "#5E5E5E"}
STYLES = ("color", "mono")
MODES = ("dark", "light", "system")
BACKGROUNDS = ("glow", "dots", "flat")
DEFAULTS = {"style": "color", "accent": "purple", "mode": "dark", "amoled": False, "background": "glow"}


def _mix(a, b, amount):
    """b over a at `amount` (0..1): the state layers of Material 3 (hover 8 %, pressed 12 %)."""
    a, b = a.lstrip("#"), b.lstrip("#")
    channels = (round(int(a[i:i + 2], 16) * (1 - amount) + int(b[i:i + 2], 16) * amount) for i in (0, 2, 4))
    return "#" + "".join(f"{c:02X}" for c in channels)


def windows_dark():
    """Windows «Режим приложений: тёмный»? (True when it cannot be read.)"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return True


def read_appearance(path=None):
    """The owner's choice from app_settings.json, checked; defaults for anything missing."""
    found = dict(DEFAULTS)
    if path is None:
        try:
            import config
            path = os.path.join(config.CONFIG_DIR, "app_settings.json")
        except Exception:  # noqa: BLE001 - no config (a bare test): defaults
            return found
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    for key, options in (("style", STYLES), ("accent", ACCENTS), ("mode", MODES), ("background", BACKGROUNDS)):
        if data.get(key) in options:
            found[key] = data[key]
    if isinstance(data.get("amoled"), bool):
        found["amoled"] = data["amoled"]
    return found


def apply(appearance):
    """Fill the module's colours from an appearance dict (read_appearance())."""
    g = globals()
    dark = appearance["mode"] == "dark" or (appearance["mode"] == "system" and windows_dark())
    scheme = "mono" if appearance["style"] == "mono" else appearance["accent"]
    (primary, on_primary, pc, on_pc, sc, on_sc, surface, low, cont, high, highest,
     on, on_variant, outline, outline_variant, error) = _SCHEMES[scheme]["dark" if dark else "light"]
    if dark and appearance["amoled"]:
        surface, low = "#000000", "#000000"
    g.update(
        APPEARANCE=dict(appearance), DARK=dark, MONO=scheme == "mono",
        BACKGROUND=appearance["background"],
        BG=surface, SURFACE_LOW=low, SURFACE=cont, SURFACE_2=high, SURFACE_3=highest,
        SURFACE_HOVER=_mix(high, on, 0.08), SURFACE_PRESSED=_mix(high, on, 0.12),
        BORDER=outline_variant, BORDER_STRONG=outline, BORDER_FOCUS=primary,
        TEXT=on, TEXT_2=on_variant, TEXT_3=outline, TEXT_DISABLED=_mix(surface, on, 0.38),
        ACCENT=primary, ON_ACCENT=on_primary, ACCENT_HOVER=_mix(primary, on_primary, 0.08),
        ACCENT_PRESSED=_mix(primary, on_primary, 0.12),
        PRIMARY_CONTAINER=pc, ON_PRIMARY_CONTAINER=on_pc,
        SECONDARY_CONTAINER=sc, ON_SECONDARY_CONTAINER=on_sc,
        SECONDARY_HOVER=_mix(sc, on_sc, 0.08), SECONDARY_PRESSED=_mix(sc, on_sc, 0.12),
        ERROR=error,
        STATE_OK=primary, STATE_BUSY=on_variant, STATE_OFF=outline, STATE_ERROR=error,
        SELECTION=_mix(surface, primary, 0.35),
    )


apply(read_appearance())

FONT_FAMILY = "Segoe UI Variable Text, Segoe UI"
FONT_MONO = "Cascadia Mono, Consolas"

# Font sizes in points so Windows scaling applies to them (Material 3 type scale).
FS_CAPTION = 8
FS_SMALL = 9
FS_BODY = 10
FS_HEADING = 12
FS_TITLE = 22
FS_DISPLAY = 28

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32

RADIUS_SM = 12      # fields, list rows, small tiles
RADIUS_MD = 16      # inner panels, covers
RADIUS_LG = 24      # cards
RADIUS_PILL = 16    # buttons and chips; Qt drops a radius above half the height, so a bit under it

SIDEBAR_WIDTH = 96  # the navigation rail
TITLEBAR_HEIGHT = 56

# Animations stay short and cheap: opacity and geometry of single widgets only.
ANIM_FAST = 150
ANIM_NORMAL = 220
