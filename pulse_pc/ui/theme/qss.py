"""Application stylesheet generated from tokens. Widgets choose a variant with the
dynamic property `kind` (buttons, labels, frames)."""
from pulse_pc.ui.theme import tokens as t


def stylesheet():
    return f"""
* {{ font-family: {t.FONT_FAMILY}; font-size: {t.FS_BODY}pt; color: {t.TEXT}; }}
QWidget {{ background: transparent; }}
QMainWindow, QWidget#root {{ background: {t.BG}; }}
QDialog {{ background: {t.SURFACE}; }}
QToolTip {{ background: {t.SURFACE_3}; color: {t.TEXT}; border: 1px solid {t.BORDER_STRONG}; padding: 6px 8px; }}

QLabel {{ border: none; }}
QLabel[kind='display'] {{ font-size: {t.FS_DISPLAY}pt; font-weight: 600; }}
QLabel[kind='title'] {{ font-size: {t.FS_TITLE}pt; font-weight: 600; }}
QLabel[kind='heading'] {{ font-size: {t.FS_HEADING}pt; font-weight: 600; }}
QLabel[kind='muted'] {{ color: {t.TEXT_2}; }}
QLabel[kind='caption'] {{ color: {t.TEXT_3}; font-size: {t.FS_SMALL}pt; }}
QLabel[kind='overline'] {{ color: {t.TEXT_3}; font-size: {t.FS_CAPTION}pt; font-weight: 600; letter-spacing: 1px; }}
QLabel[kind='value'] {{ font-size: {t.FS_TITLE}pt; font-weight: 600; }}
QLabel[kind='unavailable'] {{ color: {t.TEXT_3}; font-size: {t.FS_HEADING}pt; }}
QLabel[kind='brand'] {{ font-size: {t.FS_HEADING}pt; font-weight: 700; letter-spacing: 1px; }}
QLabel[kind='edition'] {{ color: {t.TEXT_3}; font-size: 7pt; letter-spacing: 1px; }}
QLabel[kind='mono'] {{ font-family: {t.FONT_MONO}; color: {t.TEXT_2}; }}

QFrame#sidebar {{ background: {t.BG}; border-right: 1px solid {t.BORDER}; }}
QFrame#titlebar {{ background: {t.BG}; }}
QFrame[kind='card'] {{ background: {t.SURFACE}; border: 1px solid {t.BORDER}; border-radius: {t.RADIUS_LG}px; }}
QFrame[kind='inset'] {{ background: {t.SURFACE_2}; border: 1px solid {t.BORDER}; border-radius: {t.RADIUS_MD}px; }}
QFrame[kind='divider'] {{ background: {t.BORDER}; border: none; max-height: 1px; min-height: 1px; }}

QPushButton {{ background: {t.SURFACE_2}; border: 1px solid {t.BORDER_STRONG}; border-radius: {t.RADIUS_SM}px;
              padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {t.SURFACE_HOVER}; }}
QPushButton:pressed {{ background: {t.SURFACE_PRESSED}; }}
QPushButton:focus {{ border-color: {t.BORDER_FOCUS}; }}
QPushButton:disabled {{ color: {t.TEXT_DISABLED}; border-color: {t.BORDER}; background: {t.SURFACE}; }}
QPushButton[kind='primary'] {{ background: {t.ACCENT}; color: {t.ON_ACCENT}; border-color: {t.ACCENT}; }}
QPushButton[kind='primary']:hover {{ background: #E0E0E0; }}
QPushButton[kind='primary']:pressed {{ background: #C8C8C8; }}
QPushButton[kind='primary']:disabled {{ background: {t.SURFACE_3}; color: {t.TEXT_DISABLED}; border-color: {t.SURFACE_3}; }}
QPushButton[kind='ghost'] {{ background: transparent; border-color: transparent; color: {t.TEXT_2}; }}
QPushButton[kind='ghost']:hover {{ background: {t.SURFACE_2}; color: {t.TEXT}; }}
QPushButton[kind='ghost']:checked {{ background: {t.SURFACE_3}; color: {t.TEXT}; }}
QPushButton[kind='nav'] {{ background: transparent; border: none; border-radius: {t.RADIUS_SM}px; color: {t.TEXT_2};
                          text-align: left; padding: 0 12px; font-weight: 500; }}
QPushButton[kind='nav']:hover {{ background: {t.SURFACE_2}; color: {t.TEXT}; }}
QPushButton[kind='nav']:checked {{ background: {t.SURFACE_3}; color: {t.TEXT}; font-weight: 600; }}
QPushButton[kind='window'] {{ background: transparent; border: none; border-radius: 6px; padding: 0; }}
QPushButton[kind='window']:hover {{ background: {t.SURFACE_3}; }}
QPushButton#closeWindow:hover {{ background: #3A3A3A; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {t.SURFACE_2}; border: 1px solid {t.BORDER_STRONG}; border-radius: {t.RADIUS_SM}px; padding: 7px 10px;
    selection-background-color: #3A3A3A; selection-color: {t.TEXT}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {t.BORDER_FOCUS}; }}
QLineEdit:disabled {{ color: {t.TEXT_DISABLED}; }}
QLineEdit#search {{ background: {t.SURFACE}; border-color: {t.BORDER}; border-radius: {t.RADIUS_MD}px; padding: 6px 10px; }}
QLineEdit#search:focus {{ border-color: {t.BORDER_STRONG}; }}
QPlainTextEdit#log {{ font-family: {t.FONT_MONO}; font-size: {t.FS_SMALL}pt; color: {t.TEXT_2}; background: {t.SURFACE}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {t.SURFACE_2}; border: 1px solid {t.BORDER_STRONG}; selection-background-color: {t.SURFACE_3}; }}

QListView, QTreeView, QTableView, QListWidget {{ background: {t.SURFACE}; border: 1px solid {t.BORDER}; border-radius: {t.RADIUS_MD}px;
    outline: none; alternate-background-color: {t.SURFACE_2}; }}
QListView::item, QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListView::item:hover, QListWidget::item:hover {{ background: {t.SURFACE_2}; }}
QListView::item:selected, QListWidget::item:selected {{ background: {t.SURFACE_3}; color: {t.TEXT}; }}
QHeaderView::section {{ background: transparent; color: {t.TEXT_3}; border: none; border-bottom: 1px solid {t.BORDER}; padding: 6px 8px; }}

QSlider::groove:horizontal {{ height: 3px; background: {t.BORDER_STRONG}; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {t.TEXT}; border-radius: 1px; }}
QSlider::handle:horizontal {{ background: {t.ACCENT}; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; }}
QProgressBar {{ background: {t.SURFACE_3}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }}
QProgressBar::chunk {{ background: {t.TEXT}; border-radius: 2px; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: {t.BORDER_STRONG}; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #3C3C3C; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0 4px; }}
QScrollBar::handle:horizontal {{ background: {t.BORDER_STRONG}; border-radius: 4px; min-width: 32px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QMenu {{ background: {t.SURFACE_2}; border: 1px solid {t.BORDER_STRONG}; padding: 4px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t.SURFACE_3}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {t.BORDER_STRONG}; border-radius: 4px; background: {t.SURFACE_2}; }}
QCheckBox::indicator:checked {{ background: {t.ACCENT}; border-color: {t.ACCENT}; }}
QTabBar::tab {{ background: transparent; color: {t.TEXT_2}; padding: 7px 14px; border: none; border-radius: {t.RADIUS_SM}px; }}
QTabBar::tab:selected {{ background: {t.SURFACE_3}; color: {t.TEXT}; }}
QTabBar::tab:hover:!selected {{ color: {t.TEXT}; }}
"""
