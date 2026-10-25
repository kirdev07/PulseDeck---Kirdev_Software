"""The screens of the app in navigation order. Each screen is built lazily on first visit."""
from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtWidgets import QVBoxLayout, QWidget

from pulse_pc.ui.components import EmptyState, PageHeader
from pulse_pc.ui.theme import tokens


@dataclass(frozen=True)
class Screen:
    key: str
    title: str
    symbol: str
    subtitle: str
    keywords: tuple = ()
    factory: Optional[Callable[[object], QWidget]] = field(default=None, compare=False)  # receives the AppContext


def pending_screen(screen):
    """Shown until a screen is ported (stage C). States plainly that nothing is here yet."""
    page = QWidget()
    column = QVBoxLayout(page)
    column.setContentsMargins(tokens.SPACE_5, tokens.SPACE_2, tokens.SPACE_5, tokens.SPACE_5)
    column.setSpacing(tokens.SPACE_5)
    column.addWidget(PageHeader(screen.symbol, screen.title, screen.subtitle))
    column.addWidget(EmptyState(screen.symbol, "Экран ещё переносится",
                                "Эта часть новой версии пока не готова. Все функции доступны в текущей панели Pulse-PC."), 1)
    return page


def _lazy(module):
    """Import a screen module only when the screen is first opened."""
    def factory(context):
        from importlib import import_module
        return import_module(f"pulse_pc.ui.screens.{module}").build(context)
    return factory


SCREENS = (
    Screen("dashboard", "Главная", "home", "Ваш компьютер под контролем.", ("dashboard", "система", "cpu", "ram"),
           factory=_lazy("dashboard")),
    Screen("telegram", "Telegram Бот", "telegram", "Управление, мониторинг и настройки бота.", ("бот", "telegram"),
           factory=_lazy("telegram")),
    Screen("phone", "Телефон", "phone", "Подключение и управление мобильными устройствами.", ("android", "pulse mobile"),
           factory=_lazy("phone")),
    Screen("apps", "Приложения", "apps", "Запуск и завершение настроенных программ.", ("программы",),
           factory=_lazy("apps")),
    Screen("console", "Консоль", "console", "Журнал событий и диагностика.", ("журнал", "логи"),
           factory=_lazy("console")),
    Screen("music", "Музыка", "music", "Плеер, библиотека и очередь.", ("плеер",), factory=_lazy("music")),
    Screen("settings", "Настройки", "settings", "Параметры приложения.", ("параметры", "поддержка", "лицензия"),
           factory=_lazy("settings")),
)
