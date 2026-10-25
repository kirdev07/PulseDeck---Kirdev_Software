"""Design-system gallery for review: every shared component in its states.
Run: python -m pulse_pc --gallery"""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from pulse_pc.ui.components import (
    Card, PageHeader, StatTile, StatusLine, Toggle, button, divider, icon_button, label, page_container,
)
from pulse_pc.ui.screens.registry import SCREENS, Screen
from pulse_pc.ui.theme import icon, icons, tokens


def build():
    content = QWidget()
    column = QVBoxLayout(content)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(tokens.SPACE_4)
    column.addWidget(PageHeader("pulse", "Дизайн-система", "Компоненты AMOLED-темы. Значения ниже — демонстрационные."))

    type_card = Card("Типографика")
    for kind, text in (("display", "Добро пожаловать."), ("title", "Заголовок экрана"), ("heading", "Заголовок карточки"),
                       ("", "Основной текст интерфейса"), ("muted", "Вторичный текст"), ("caption", "Подпись"),
                       ("overline", "НАДЗАГОЛОВОК"), ("mono", "16:24:11 [INFO] Моноширинный журнал")):
        type_card.body.addWidget(label(text, kind))
    column.addWidget(type_card)

    controls = Card("Кнопки и поля")
    row = QHBoxLayout()
    row.addWidget(button("Основная", kind="primary", symbol="play"))
    row.addWidget(button("Обычная", symbol="refresh"))
    row.addWidget(button("Тихая", kind="ghost"))
    disabled = button("Недоступна")
    disabled.setEnabled(False)
    row.addWidget(disabled)
    row.addWidget(icon_button("settings", tooltip="Настройки"))
    row.addStretch(1)
    controls.body.addLayout(row)
    field = QLineEdit()
    field.setPlaceholderText("Поле ввода")
    controls.body.addWidget(field)
    controls.body.addWidget(divider())
    toggles = QHBoxLayout()
    for checked, enabled in ((True, True), (False, True), (True, False)):
        toggle = Toggle(checked)
        toggle.setEnabled(enabled)
        toggles.addWidget(toggle)
    toggles.addStretch(1)
    controls.body.addLayout(toggles)
    column.addWidget(controls)

    states = Card("Состояния")
    for text, state in (("Работает", "ok"), ("Подключение…", "busy"), ("Остановлен", "off"), ("Ошибка", "error")):
        states.body.addWidget(StatusLine(text, state))
    column.addWidget(states)

    tiles = QGridLayout()
    tiles.setSpacing(tokens.SPACE_3)
    cpu = StatTile("cpu", "CPU")
    ram = StatTile("ram", "RAM")
    gpu = StatTile("gpu", "GPU")
    gpu.set_value(None, "Датчик не найден")
    for i, tile in enumerate((cpu, ram, gpu)):
        tiles.addWidget(tile, 0, i)
    column.addLayout(tiles)
    demo = {"i": 0}

    def tick():
        import math
        demo["i"] += 1
        cpu.set_value(35 + 25 * math.sin(demo["i"] / 4), "Демо-данные")
        ram.set_value(55 + 10 * math.cos(demo["i"] / 7), "Демо-данные")
    timer = QTimer(content, interval=500, timeout=tick)
    timer.start()
    tick()

    glyphs = Card("Иконки")
    grid = QGridLayout()
    for i, name in enumerate(icons.names()):
        cell = QVBoxLayout()
        image = QLabel()
        image.setPixmap(icon(name, tokens.TEXT).pixmap(24, 24))
        cell.addWidget(image)
        cell.addWidget(label(name, "caption"))
        grid.addLayout(cell, i // 8, i % 8)
    glyphs.body.addLayout(grid)
    column.addWidget(glyphs)
    column.addStretch(1)
    return page_container(content)


GALLERY = Screen("gallery", "Дизайн-система", "pulse", "", ("gallery",), factory=build)
SCREENS_WITH_GALLERY = (GALLERY,) + SCREENS
