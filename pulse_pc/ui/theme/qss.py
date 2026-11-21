"""Application stylesheet generated from tokens (Material 3). Widgets choose a variant with
the dynamic property `kind` (buttons, labels, frames).

Buttons: default = tonal (secondary container), «primary» = filled, «outlined», «ghost» =
text/icon button. Cards have no border: they stand out by tone, as in Material 3."""
from pulse_pc.ui.theme import tokens as t


def _rgba(color, alpha):
    """Qt reads #AARRGGBB, not #RRGGBBAA: transparency goes through rgba()."""
    c = color.lstrip("#")
    return f"rgba({int(c[0:2], 16)}, {int(c[2:4], 16)}, {int(c[4:6], 16)}, {round(alpha * 255)})"


def stylesheet():
    return f"""
* {{ font-family: {t.FONT_FAMILY}; font-size: {t.FS_BODY}pt; color: {t.TEXT}; }}
QWidget {{ background: transparent; }}
QMainWindow, QWidget#root {{ background: {t.BG}; }}
QDialog {{ background: {t.SURFACE_2}; }}
QMessageBox {{ background: {t.SURFACE_2}; }}
QToolTip {{ background: {t.SURFACE_3}; color: {t.TEXT}; border: none; border-radius: 8px; padding: 6px 10px; }}

QLabel {{ border: none; }}
QLabel[kind='display'] {{ font-size: {t.FS_DISPLAY}pt; font-weight: 400; }}
QLabel[kind='title'] {{ font-size: {t.FS_TITLE}pt; font-weight: 400; }}
QLabel[kind='heading'] {{ font-size: {t.FS_HEADING}pt; font-weight: 600; }}
QLabel[kind='muted'] {{ color: {t.TEXT_2}; }}
QLabel[kind='caption'] {{ color: {t.TEXT_2}; font-size: {t.FS_SMALL}pt; }}
QLabel[kind='overline'] {{ color: {t.TEXT_2}; font-size: {t.FS_CAPTION}pt; font-weight: 600; letter-spacing: 1px; }}
QLabel[kind='value'] {{ font-size: {t.FS_TITLE}pt; font-weight: 400; }}
QLabel[kind='unavailable'] {{ color: {t.TEXT_3}; font-size: {t.FS_HEADING}pt; }}
QLabel[kind='brand'] {{ font-size: {t.FS_HEADING}pt; font-weight: 700; letter-spacing: 1px; }}
QLabel[kind='edition'] {{ color: {t.TEXT_3}; font-size: 7pt; letter-spacing: 1px; }}
QLabel[kind='mono'] {{ font-family: {t.FONT_MONO}; color: {t.TEXT_2}; }}
QLabel[kind='rail'] {{ color: {t.TEXT_3}; font-size: 7pt; }}

QFrame#sidebar {{ background: transparent; border: none; }}
QFrame#titlebar {{ background: transparent; }}
QFrame[kind='card'] {{ background: {t.SURFACE}; border: none; border-radius: {t.RADIUS_LG}px; }}
QFrame[kind='cardhi'] {{ background: {t.PRIMARY_CONTAINER}; border: none; border-radius: {t.RADIUS_LG}px; }}
QFrame[kind='cardhi'] QLabel {{ color: {t.ON_PRIMARY_CONTAINER}; }}
QFrame[kind='cardhi'] QProgressBar {{ background: {_rgba(t.ON_PRIMARY_CONTAINER, 0.25)}; }}
QFrame[kind='cardhi'] QProgressBar::chunk {{ background: {t.ON_PRIMARY_CONTAINER}; }}
QFrame[kind='inset'] {{ background: {t.SURFACE_2}; border: none; border-radius: {t.RADIUS_MD}px; }}
QFrame[kind='divider'] {{ background: {t.BORDER}; border: none; max-height: 1px; min-height: 1px; }}

QPushButton {{ background: {t.SECONDARY_CONTAINER}; color: {t.ON_SECONDARY_CONTAINER}; border: none;
              border-radius: {t.RADIUS_PILL}px; padding: 9px 20px; font-weight: 600; }}
QPushButton:hover {{ background: {t.SECONDARY_HOVER}; }}
QPushButton:pressed {{ background: {t.SECONDARY_PRESSED}; }}
QPushButton:focus {{ outline: none; }}
QPushButton:disabled {{ color: {t.TEXT_DISABLED}; background: {t.SURFACE_2}; }}
QPushButton[kind='primary'] {{ background: {t.ACCENT}; color: {t.ON_ACCENT}; }}
QPushButton[kind='primary']:hover {{ background: {t.ACCENT_HOVER}; }}
QPushButton[kind='primary']:pressed {{ background: {t.ACCENT_PRESSED}; }}
QPushButton[kind='primary']:disabled {{ background: {t.SURFACE_3}; color: {t.TEXT_DISABLED}; }}
QPushButton[kind='outlined'] {{ background: transparent; color: {t.ACCENT}; border: 1px solid {t.BORDER_STRONG}; }}
QPushButton[kind='outlined']:hover {{ background: {t.SURFACE_HOVER}; }}
QPushButton[kind='ghost'] {{ background: transparent; color: {t.TEXT_2}; }}
QPushButton[kind='ghost']:hover {{ background: {t.SURFACE_HOVER}; color: {t.TEXT}; }}
QPushButton[kind='ghost']:pressed {{ background: {t.SURFACE_PRESSED}; }}
QPushButton[kind='ghost']:checked {{ background: {t.SECONDARY_CONTAINER}; color: {t.ON_SECONDARY_CONTAINER}; }}
QPushButton[kind='ghost']:disabled {{ background: transparent; }}
QPushButton[kind='nav'] {{ background: transparent; border: none; border-radius: 16px; color: {t.TEXT_2};
                          text-align: left; padding: 0 16px; font-weight: 600; }}
QPushButton[kind='nav']:hover {{ background: {t.SURFACE_HOVER}; color: {t.TEXT}; }}
QPushButton[kind='nav']:checked {{ background: {t.SECONDARY_CONTAINER}; color: {t.ON_SECONDARY_CONTAINER}; }}
QPushButton[kind='window'] {{ background: transparent; border: none; border-radius: 8px; padding: 0; }}
QPushButton[kind='window']:hover {{ background: {t.SURFACE_HOVER}; }}
QPushButton#closeWindow:hover {{ background: {t.ERROR}; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {t.SURFACE_2}; border: 1px solid transparent; border-radius: {t.RADIUS_SM}px; padding: 8px 12px;
    selection-background-color: {t.SELECTION}; selection-color: {t.TEXT}; }}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ background: {t.SURFACE_3}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 2px solid {t.ACCENT}; padding: 7px 11px; }}
QLineEdit:disabled {{ color: {t.TEXT_DISABLED}; }}
QLineEdit#search {{ background: {t.SURFACE_2}; border: none; border-radius: 18px; padding: 8px 16px; min-height: 22px; }}
QLineEdit#search:hover {{ background: {t.SURFACE_3}; }}
QLineEdit#search:focus {{ border: 2px solid {t.ACCENT}; padding: 6px 14px; }}
QPlainTextEdit#log {{ font-family: {t.FONT_MONO}; font-size: {t.FS_SMALL}pt; color: {t.TEXT_2}; background: {t.SURFACE_LOW};
                      border-radius: {t.RADIUS_MD}px; padding: 8px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {t.SURFACE_2}; border: none; border-radius: 8px; padding: 4px;
                               selection-background-color: {t.SECONDARY_CONTAINER}; selection-color: {t.ON_SECONDARY_CONTAINER}; }}

QListView, QTreeView, QTableView, QListWidget {{ background: transparent; border: none; border-radius: {t.RADIUS_MD}px;
    outline: none; alternate-background-color: {t.SURFACE_2}; }}
QListView::item, QListWidget::item {{ padding: 8px 10px; border-radius: {t.RADIUS_SM}px; }}
QListView::item:hover, QListWidget::item:hover {{ background: {t.SURFACE_HOVER}; }}
QListView::item:selected, QListWidget::item:selected {{ background: {t.SECONDARY_CONTAINER}; color: {t.ON_SECONDARY_CONTAINER}; }}
QTableView::item {{ padding: 6px; border: none; }}
QTableView::item:selected {{ background: {t.SECONDARY_CONTAINER}; color: {t.ON_SECONDARY_CONTAINER}; }}
QHeaderView::section {{ background: transparent; color: {t.TEXT_2}; border: none; border-bottom: 1px solid {t.BORDER}; padding: 8px; font-weight: 600; }}

QSlider::groove:horizontal {{ height: 6px; background: {t.SURFACE_3}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {t.ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {t.ACCENT}; width: 4px; height: 20px; margin: -7px 2px; border-radius: 2px; }}
QProgressBar {{ background: {t.SURFACE_3}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ background: {t.ACCENT}; border-radius: 3px; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 6px 2px; }}
QScrollBar::handle:vertical {{ background: {t.BORDER}; border-radius: 3px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {t.BORDER_STRONG}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 6px; }}
QScrollBar::handle:horizontal {{ background: {t.BORDER}; border-radius: 3px; min-width: 32px; }}
QScrollBar::handle:horizontal:hover {{ background: {t.BORDER_STRONG}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QMenu {{ background: {t.SURFACE_2}; border: none; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 8px 20px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t.SURFACE_HOVER}; }}
QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid {t.TEXT_2}; border-radius: 3px; background: transparent; }}
QCheckBox::indicator:checked {{ background: {t.ACCENT}; border-color: {t.ACCENT}; }}
QTabBar::tab {{ background: transparent; color: {t.TEXT_2}; padding: 9px 16px; border: none; border-radius: 16px; font-weight: 600; }}
QTabBar::tab:selected {{ background: {t.SECONDARY_CONTAINER}; color: {t.ON_SECONDARY_CONTAINER}; }}
QTabBar::tab:hover:!selected {{ background: {t.SURFACE_HOVER}; color: {t.TEXT}; }}
"""
