"""Design tokens of the AMOLED Black theme. Every colour, size and duration lives here.

The palette is strictly monochrome: states differ by brightness and shape, never by hue.
"""

# Surfaces, from the pure black window to raised controls.
BG = "#000000"
SURFACE = "#0A0A0A"
SURFACE_2 = "#111111"
SURFACE_3 = "#1A1A1A"
SURFACE_HOVER = "#202020"
SURFACE_PRESSED = "#262626"

BORDER = "#1C1C1C"
BORDER_STRONG = "#2C2C2C"
BORDER_FOCUS = "#8C8C8C"

TEXT = "#F2F2F2"
TEXT_2 = "#A6A6A6"
TEXT_3 = "#6E6E6E"
TEXT_DISABLED = "#4A4A4A"

ACCENT = "#FFFFFF"        # primary buttons, active navigation, live values
ON_ACCENT = "#000000"

# States: brightness only (see components.StatusDot for the matching shapes).
STATE_OK = "#F2F2F2"
STATE_BUSY = "#A6A6A6"
STATE_OFF = "#4A4A4A"
STATE_ERROR = "#F2F2F2"   # error = bright ring around a hollow dot

FONT_FAMILY = "Segoe UI Variable Text, Segoe UI"
FONT_MONO = "Cascadia Mono, Consolas"

# Font sizes in points so Windows scaling applies to them.
FS_CAPTION = 8
FS_SMALL = 9
FS_BODY = 10
FS_HEADING = 12
FS_TITLE = 20
FS_DISPLAY = 26

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32

RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 16

SIDEBAR_WIDTH = 216
TITLEBAR_HEIGHT = 52

# Animations stay short and cheap: opacity and geometry of single widgets only.
ANIM_FAST = 120
ANIM_NORMAL = 180
