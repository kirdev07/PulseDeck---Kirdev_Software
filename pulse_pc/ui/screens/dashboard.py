"""Главная: live CPU/RAM/GPU/disk, load history, system, network and service summaries."""
import time
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from pulse_pc.core import state as st
from pulse_pc.services.system.metrics import format_bytes, format_uptime, host_info
from pulse_pc.ui.components import UNAVAILABLE, Card, StatTile, StatusLine, button, divider, label, page_container
from pulse_pc.ui.components.charts import LegendMark, LoadChart
from pulse_pc.ui.theme import icon, tokens

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря")
WEEKDAYS = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
RANGES = (("1 мин", 60), ("5 мин", 300), ("15 мин", 900))


def info_row(symbol, name):
    """Icon + name on the left, value on the right; returns (layout, value label)."""
    row = QHBoxLayout()
    row.setSpacing(tokens.SPACE_2)
    glyph = QLabel()
    glyph.setPixmap(icon(symbol, tokens.TEXT_3).pixmap(QSize(16, 16)))
    row.addWidget(glyph)
    row.addWidget(label(name, "muted"), 1)
    value = label("—")
    value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(value)
    return row, value


class DashboardScreen(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.navigate = getattr(context, "navigate", None)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(tokens.SPACE_4)
        grid.setVerticalSpacing(tokens.SPACE_4)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 1)

        grid.addLayout(self._greeting(), 0, 0)
        grid.addWidget(self._system_card(), 0, 1, 2, 1)
        tiles = QHBoxLayout()
        tiles.setSpacing(tokens.SPACE_3)
        self.cpu = StatTile("cpu", "CPU")
        self.ram = StatTile("ram", "RAM")
        self.gpu = StatTile("gpu", "GPU")
        self.disk = StatTile("disk", "Диск C:", history=False)
        for tile in (self.cpu, self.ram, self.gpu, self.disk):
            tiles.addWidget(tile, 1)
        grid.addLayout(tiles, 1, 0)
        grid.addWidget(self._load_card(), 2, 0)
        grid.addWidget(self._network_card(), 2, 1)
        grid.addLayout(self._services_row(), 3, 0)
        grid.addWidget(self._player_card(), 3, 1)
        grid.setRowStretch(4, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page_container(content))

        self.clock_timer = QTimer(self, interval=1000, timeout=self._tick_clock)
        self.clock_timer.start()
        self._tick_clock()
        self.host = host_info()
        self.host_name.setText(self.host["name"])
        self.host_os.setText(self.host["os"])
        self.addresses.setText(", ".join(self.host["addresses"]) or "Нет подключения")

        metrics = getattr(context, "metrics", None)
        if metrics is not None:
            metrics.updated.connect(self.apply)
            if metrics.latest:
                self.apply(metrics.latest)
        store = getattr(context, "store", None)
        if store is not None:
            store.changed.connect(self._state_changed)
            for part in ("telegram", "phone", "player"):
                self._state_changed(part, getattr(store.state, part))
        else:
            self._state_changed("telegram", st.TelegramState())
            self._state_changed("phone", st.PhoneState())
            self._state_changed("player", st.PlayerState())

    # ----- layout pieces -----
    def _greeting(self):
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label("Добро пожаловать.", "display"))
        text.addWidget(label("Ваш компьютер под контролем.", "muted"))
        row.addLayout(text, 1)
        clock = QVBoxLayout()
        clock.setSpacing(0)
        self.date_label = label("", "caption")
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.time_label = label("", "title")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        clock.addWidget(self.date_label)
        clock.addWidget(self.time_label)
        row.addLayout(clock)
        return row

    def _system_card(self):
        card = Card("Состояние системы")
        self.system_rows = {}
        for key, symbol, name in (("uptime", "power", "Время работы"), ("processes", "apps", "Процессы"),
                                  ("cores", "cpu", "Логических ядер"), ("gpu_name", "gpu", "Видеокарта"),
                                  ("battery", "power", "Батарея")):
            row, value = info_row(symbol, name)
            self.system_rows[key] = value
            card.body.addLayout(row)
        card.body.addWidget(divider())
        card.body.addWidget(label("УСТРОЙСТВО", "overline"))
        self.host_name = label("", "heading")
        self.host_os = label("", "caption")
        card.body.addWidget(self.host_name)
        card.body.addWidget(self.host_os)
        card.body.addStretch(1)
        return card

    def _load_card(self):
        card = Card("Загрузка системы")
        self.chart = LoadChart(("CPU", "RAM", "GPU"))
        for index, name in enumerate(self.chart.names):
            card.add_action(LegendMark(index))
            card.add_action(label(name, "caption"))
        spacer = QWidget()
        spacer.setFixedWidth(tokens.SPACE_3)
        card.add_action(spacer)
        self.range_group = QButtonGroup(self)
        for text, seconds in RANGES:
            choice = button(text, kind="ghost")
            choice.setCheckable(True)
            choice.setChecked(seconds == self.chart.window)
            choice.setStyleSheet("padding: 4px 10px;")
            choice.clicked.connect(lambda _=False, s=seconds: self.chart.set_window(s))
            self.range_group.addButton(choice)
            card.add_action(choice)
        card.body.addWidget(self.chart, 1)
        card.setMinimumHeight(260)
        return card

    def _network_card(self):
        card = Card("Сеть")
        row, self.addresses = info_row("network", "IP")
        card.body.addLayout(row)
        rates = QHBoxLayout()
        self.down = label("—", "heading")
        self.up = label("—", "heading")
        for name, value in (("Загрузка", self.down), ("Отдача", self.up)):
            column = QVBoxLayout()
            column.setSpacing(0)
            column.addWidget(value)
            column.addWidget(label(name, "caption"))
            rates.addLayout(column, 1)
        card.body.addLayout(rates)
        card.body.addStretch(1)
        return card

    def _services_row(self):
        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_3)
        telegram = Card("Telegram Бот")
        self.telegram_status = StatusLine()
        self.telegram_detail = label("", "caption", wrap=True)
        telegram.body.addWidget(self.telegram_status)
        telegram.body.addWidget(self.telegram_detail)
        telegram.body.addStretch(1)
        telegram.body.addWidget(button("Открыть", lambda: self._go("telegram"), symbol="chevron"))
        phone = Card("Телефон")
        self.phone_status = StatusLine()
        self.phone_detail = label("", "caption", wrap=True)
        phone.body.addWidget(self.phone_status)
        phone.body.addWidget(self.phone_detail)
        phone.body.addStretch(1)
        phone.body.addWidget(button("Открыть", lambda: self._go("phone"), symbol="chevron"))
        quick = Card("Быстрый доступ")
        for key, symbol, text in (("apps", "apps", "Приложения"), ("console", "console", "Консоль"),
                                  ("music", "music", "Музыка"), ("settings", "settings", "Настройки")):
            shortcut = button(text, lambda _=False, k=key: self._go(k), kind="ghost", symbol=symbol)
            shortcut.setStyleSheet("text-align: left;")
            quick.body.addWidget(shortcut)
        for card in (telegram, phone, quick):
            row.addWidget(card, 1)
        return row

    def _player_card(self):
        card = Card("Сейчас играет")
        top = QHBoxLayout()
        self.cover = QLabel()
        self.cover.setFixedSize(56, 56)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setStyleSheet(f"background: {tokens.SURFACE_3}; border-radius: {tokens.RADIUS_SM}px;")
        top.addWidget(self.cover)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.track_title = label("", "heading")
        self.track_artist = label("", "caption")
        text.addWidget(self.track_title)
        text.addWidget(self.track_artist)
        top.addLayout(text, 1)
        card.body.addLayout(top)
        self.track_progress = QProgressBar()
        self.track_progress.setRange(0, 1000)
        self.track_progress.setTextVisible(False)
        card.body.addWidget(self.track_progress)
        card.body.addStretch(1)
        return card

    def _go(self, key):
        if self.navigate:
            self.navigate(key)

    # ----- updates -----
    def _tick_clock(self):
        now = datetime.now()
        self.date_label.setText(f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]}")
        self.time_label.setText(now.strftime("%H:%M"))

    def apply(self, snap):
        freq = f"{snap.cpu_freq_mhz / 1000:.2f} ГГц" if snap.cpu_freq_mhz else ""
        self.cpu.set_value(snap.cpu, freq)
        ram = f"{format_bytes(snap.ram_used)} из {format_bytes(snap.ram_total)}" if snap.ram is not None else ""
        self.ram.set_value(snap.ram, ram)
        gpu_detail = f"Видеопамять {format_bytes(snap.gpu_memory_used)}" if snap.gpu_memory_used else ""
        self.gpu.set_value(snap.gpu, gpu_detail if snap.gpu is not None else "Счётчики GPU недоступны")
        disk = snap.system_disk
        if disk:
            self.disk.set_name(f"Диск {disk.mount}")
            self.disk.set_value(disk.percent, f"{format_bytes(disk.total - disk.used)} свободно")
        else:
            self.disk.set_value(None)
        self.chart.append({"CPU": snap.cpu, "RAM": snap.ram, "GPU": snap.gpu})
        rows = self.system_rows
        rows["uptime"].setText(format_uptime(snap.uptime))
        rows["processes"].setText(str(snap.processes) if snap.processes is not None else UNAVAILABLE)
        rows["cores"].setText(str(snap.cpu_cores) if snap.cpu_cores else UNAVAILABLE)
        rows["gpu_name"].setText(snap.gpu_name or UNAVAILABLE)
        rows["gpu_name"].setToolTip(snap.gpu_name)
        rows["battery"].setText("Нет" if snap.battery is None else
                                f"{snap.battery:.0f}% · {'сеть' if snap.plugged else 'батарея'}")
        self.down.setText(format_bytes(snap.net_down, True) if snap.net_down is not None else "—")
        self.up.setText(format_bytes(snap.net_up, True) if snap.net_up is not None else "—")

    def _state_changed(self, part, value):
        if part == "telegram":
            self._show_telegram(value)
        elif part == "phone":
            self._show_phone(value)
        elif part == "player":
            self._show_player(value)

    def _show_telegram(self, value):
        texts = {st.UNKNOWN: ("Нет данных", "off"), st.STOPPED: ("Остановлен", "off"), st.STARTING: ("Запуск…", "busy"),
                 st.RUNNING: ("Активен", "ok"), st.RECONNECTING: ("Переподключение…", "busy"), st.ERROR: ("Ошибка", "error")}
        text, dot = texts.get(value.status, texts[st.UNKNOWN])
        self.telegram_status.set(text, dot)
        if value.status == st.UNKNOWN:
            detail = "Служба бота ещё не подключена к новому интерфейсу."
        elif value.status == st.RUNNING and value.since:
            detail = (f"@{value.bot_name} · " if value.bot_name else "") + "в сети " + format_uptime(time.time() - value.since)
        else:
            detail = value.error
        self.telegram_detail.setText(detail)

    def _show_phone(self, value):
        if value.status == st.UNKNOWN:
            self.phone_status.set("Нет данных", "off")
            self.phone_detail.setText("Локальный сервер ещё не подключён к новому интерфейсу.")
            return
        running = value.status == st.RUNNING
        self.phone_status.set("Сервер активен" if running else "Сервер остановлен", "ok" if running else "off")
        count = len(value.devices)
        devices = f"Сопряжено устройств: {count}" if count else "Нет сопряжённых устройств"
        address = f"{value.addresses[0]}:{value.port}" if running and value.addresses else ""
        self.phone_detail.setText(devices + (f"\n{address}" if address else ""))

    def _show_player(self, value):
        playing = value.status in ("playing", "paused") and value.title
        self.track_title.setText(value.title if playing else "Ничего не играет")
        self.track_artist.setText((value.artist or value.source) if playing else "")
        self.track_progress.setVisible(bool(playing and value.duration))
        if playing and value.duration:
            self.track_progress.setValue(round(1000 * value.position / value.duration))
        cover = QPixmap()
        if playing and value.cover and cover.loadFromData(value.cover):
            self.cover.setPixmap(cover.scaled(self.cover.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                              Qt.TransformationMode.SmoothTransformation))
        else:
            self.cover.setPixmap(icon("music", tokens.TEXT_3).pixmap(QSize(24, 24)))


def build(context):
    return DashboardScreen(context)
