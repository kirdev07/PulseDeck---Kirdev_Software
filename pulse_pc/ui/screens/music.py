"""Музыка: built-in player with queue, library folders, search, and control of other apps'
media sessions. The same player is controlled from Pulse Mobile."""
import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QSlider, QVBoxLayout, QWidget,
)

from modules import player_bridge
from pulse_pc.services.media.player import LibraryScanner, MediaSessions, MusicPlayer
from pulse_pc.ui.components import Card, EmptyState, PageHeader, button, icon_button, label
from pulse_pc.ui.theme import icon, tokens

REPEAT_TIPS = {"all": "Повтор очереди", "one": "Повтор трека", "off": "Без повтора"}
SOURCE_NAMES = {"stream": "Стриминг", "browser": "Браузер", "local": "Приложение"}


def clock(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


def track_text(track):
    return track.get("title") or Path(track["path"]).stem


class MusicScreen(QWidget):
    def __init__(self, context=None, player=None, sessions=None, parent=None):
        super().__init__(parent)
        self.player = player or getattr(context, "player", None) or MusicPlayer(self)
        self.sessions = sessions or MediaSessions(parent=self)
        self.tracks = []
        self._cover_key = "unset"   # forces the placeholder on first refresh

        column = QVBoxLayout(self)
        column.setContentsMargins(tokens.SPACE_5, tokens.SPACE_2, tokens.SPACE_5, tokens.SPACE_5)
        column.setSpacing(tokens.SPACE_4)
        column.addWidget(PageHeader("music", "Музыка", "Встроенный плеер. Им же можно управлять с телефона."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(tokens.SPACE_4)
        grid.setVerticalSpacing(tokens.SPACE_4)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.addWidget(self._now_card(), 0, 0)
        grid.addWidget(self._queue_card(), 0, 1, 2, 1)
        grid.addWidget(self._library_card(), 1, 0)
        grid.addWidget(self._sessions_card(), 2, 0, 1, 2)
        grid.setRowStretch(1, 1)
        column.addLayout(grid, 1)

        self.scanner = LibraryScanner(self)
        self.scanner.scanned.connect(self._library_ready)
        self.player.changed.connect(self.refresh)
        self.player.queue_changed.connect(self.refresh_queue)
        self.sessions.updated.connect(self._sessions_ready)
        self.refresh_folders()
        self.rescan()
        self.refresh()
        self.refresh_queue()

    # ----- layout -----
    def _now_card(self):
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_5)
        self.cover = QLabel()
        self.cover.setFixedSize(168, 168)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setStyleSheet(f"background: {tokens.SURFACE_3}; border-radius: {tokens.RADIUS_MD}px;")
        row.addWidget(self.cover)
        info = QVBoxLayout()
        info.setSpacing(tokens.SPACE_2)
        self.title = label("", "title", wrap=True)
        self.artist = label("", "muted", wrap=True)
        info.addWidget(self.title)
        info.addWidget(self.artist)
        info.addStretch(1)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setAccessibleName("Позиция трека")
        self.seek.sliderReleased.connect(self._seek)
        info.addWidget(self.seek)
        times = QHBoxLayout()
        self.position = label("0:00", "caption")
        self.duration = label("0:00", "caption")
        times.addWidget(self.position)
        times.addStretch(1)
        times.addWidget(self.duration)
        info.addLayout(times)

        controls = QHBoxLayout()
        controls.setSpacing(tokens.SPACE_2)
        self.shuffle_button = icon_button("shuffle", lambda: self.player.set_shuffle(self.shuffle_button.isChecked()),
                                          "Перемешать", 36)
        self.shuffle_button.setCheckable(True)
        prev = icon_button("prev", lambda: self.player.handle("prev"), "Предыдущий", 40)
        self.play_button = button("", lambda: self.player.handle("toggle"), "primary", "play", "Воспроизвести")
        self.play_button.setFixedSize(52, 52)
        self.play_button.setIconSize(QSize(20, 20))
        self.play_button.setStyleSheet("padding: 0; border-radius: 26px;")
        nxt = icon_button("next", lambda: self.player.handle("next"), "Следующий", 40)
        self.repeat_button = icon_button("repeat", self._cycle_repeat, REPEAT_TIPS["all"], 36)
        self.repeat_button.setCheckable(True)
        self.repeat_button.setChecked(True)
        controls.addStretch(1)
        for widget in (self.shuffle_button, prev, self.play_button, nxt, self.repeat_button):
            controls.addWidget(widget)
        controls.addStretch(1)
        glyph = QLabel()
        glyph.setPixmap(icon("volume", tokens.TEXT_3).pixmap(QSize(16, 16)))
        controls.addWidget(glyph)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(120)
        self.volume.setAccessibleName("Громкость плеера")
        self.volume.valueChanged.connect(lambda v: self.player.handle("volume", v / 100))
        controls.addWidget(self.volume)
        info.addLayout(controls)
        row.addLayout(info, 1)
        card.body.addLayout(row)
        return card

    def _queue_card(self):
        card = Card("Очередь")
        self.queue_count = card.add_action(label("", "caption"))
        self.queue_list = QListWidget()
        self.queue_list.setStyleSheet("border: none;")
        self.queue_list.itemActivated.connect(lambda item: self.player.play_index(self.queue_list.row(item)))
        card.body.addWidget(self.queue_list, 1)
        self.queue_empty = label("Очередь пуста. Выберите трек в библиотеке.", "caption", wrap=True)
        card.body.addWidget(self.queue_empty)
        return card

    def _library_card(self):
        card = Card("Библиотека")
        card.add_action(button("Папка…", self.add_folder, "ghost", "plus", "Добавить папку с музыкой"))
        card.add_action(icon_button("refresh", self.rescan, "Пересканировать"))
        self.folders = QListWidget()
        self.folders.setFlow(QListWidget.Flow.LeftToRight)
        self.folders.setWrapping(True)
        self.folders.setMaximumHeight(40)
        self.folders.setStyleSheet("border: none; background: transparent;")
        self.folders.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.folders.setToolTip("Правый клик по папке — убрать из библиотеки")
        from PySide6.QtGui import QAction
        remove = QAction("Убрать из библиотеки", self.folders)
        remove.triggered.connect(self.remove_folder)
        self.folders.addAction(remove)
        card.body.addWidget(self.folders)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Поиск по трекам и папкам…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search", tokens.TEXT_3), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.filter_library)
        card.body.addWidget(self.search)
        self.library = QListWidget()
        self.library.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.library.setStyleSheet("border: none;")
        self.library.itemActivated.connect(self.play_item)
        card.body.addWidget(self.library, 1)
        self.library_empty = EmptyState("music", "Треков не найдено",
                                        "Добавьте папку с музыкой (mp3, flac, wav, ogg, m4a, aac, opus, wma).")
        card.body.addWidget(self.library_empty, 1)
        self.library_count = label("", "caption")
        card.body.addWidget(self.library_count)
        return card

    def _sessions_card(self):
        card = Card("Другие приложения")
        self.sessions_box = QVBoxLayout()
        self.sessions_box.setSpacing(tokens.SPACE_2)
        card.body.addLayout(self.sessions_box)
        self.sessions_note = label("" if self.sessions.available else
                                   "Недоступно: не установлен компонент Windows Media (winrt).", "caption", wrap=True)
        card.body.addWidget(self.sessions_note)
        self.sessions_card = card
        return card

    # ----- player -----
    def refresh(self):
        state = player_bridge.snapshot()
        active = state["active"]
        self.title.setText(state["title"] if active else "Ничего не играет")
        self.artist.setText(" · ".join(x for x in (state["artist"], state["album"]) if x) if active
                            else "Выберите трек в библиотеке или запустите его с телефона.")
        playing = state["status"] == "playing"
        self.play_button.setIcon(icon("pause" if playing else "play", tokens.ON_ACCENT))
        self.play_button.setToolTip("Пауза" if playing else "Воспроизвести")
        duration = state["duration"] or 0
        if not self.seek.isSliderDown():
            self.seek.setValue(round(state["position"] / duration * 1000) if duration > 0 else 0)
        self.seek.setEnabled(active and duration > 0)
        self.position.setText(clock(state["position"] if active else 0))
        self.duration.setText(clock(duration if active else 0))
        volume = round(state["volume"] * 100)
        if not self.volume.isSliderDown() and self.volume.value() != volume:
            self.volume.blockSignals(True)
            self.volume.setValue(volume)
            self.volume.blockSignals(False)
        key = state["cover_key"] if active and state["cover"] else None
        if key != self._cover_key:
            self._cover_key = key
            image = QPixmap()
            if key and image.loadFromData(state["cover"]):
                self.cover.setPixmap(image.scaled(self.cover.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                  Qt.TransformationMode.SmoothTransformation))
            else:
                self.cover.setPixmap(icon("music", tokens.TEXT_3).pixmap(QSize(48, 48)))
        self._mark_current()

    def _seek(self):
        duration = player_bridge.snapshot()["duration"]
        if duration:
            self.player.handle("seek", self.seek.value() / 1000 * duration)

    def _cycle_repeat(self):
        mode = self.player.cycle_repeat()
        self.repeat_button.setChecked(mode != "off")
        self.repeat_button.setIcon(icon("repeat-one" if mode == "one" else "repeat", tokens.TEXT_2))
        self.repeat_button.setToolTip(REPEAT_TIPS[mode])

    def refresh_queue(self):
        self.queue_list.clear()
        for track in self.player.queue:
            self.queue_list.addItem(QListWidgetItem(track_text(track)))
        has = bool(self.player.queue)
        self.queue_list.setVisible(has)
        self.queue_empty.setVisible(not has)
        self.queue_count.setText(f"{len(self.player.queue)} треков" if has else "")
        self._mark_current()

    def _mark_current(self):
        for row in range(self.queue_list.count()):
            item = self.queue_list.item(row)
            font = item.font()
            font.setBold(row == self.player.index)
            item.setFont(font)
        if 0 <= self.player.index < self.queue_list.count():
            self.queue_list.setCurrentRow(self.player.index)

    # ----- library -----
    def refresh_folders(self):
        self.folders.clear()
        for folder in player_bridge.load_folders():
            item = QListWidgetItem(icon("folder", tokens.TEXT_3), Path(folder).name or folder)
            item.setToolTip(folder if Path(folder).is_dir() else f"{folder} — папка не найдена")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.folders.addItem(item)

    def rescan(self):
        self.library_count.setText("Сканирую папки…")
        self.scanner.scan()

    def _library_ready(self, tracks):
        self.tracks = tracks
        self.library.clear()
        for track in tracks:
            item = QListWidgetItem(f"{track_text(track)}    ·    {track['folder']}")
            item.setData(Qt.ItemDataRole.UserRole, track["path"])
            self.library.addItem(item)
        suffix = f" (показаны первые {player_bridge.MAX_TRACKS})" if len(tracks) >= player_bridge.MAX_TRACKS else ""
        self.library_count.setText(f"Треков: {len(tracks)}{suffix}")
        self.library.setVisible(bool(tracks))
        self.library_empty.setVisible(not tracks)
        self.filter_library(self.search.text())

    def filter_library(self, text):
        query = text.strip().casefold()
        for row in range(self.library.count()):
            item = self.library.item(row)
            item.setHidden(bool(query) and query not in item.text().casefold())

    def play_item(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        visible = [t for t in self.tracks if not self.library.item(self.tracks.index(t)).isHidden()] \
            if self.search.text().strip() else self.tracks
        self.player.open_track(path, list(visible))

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка с музыкой")
        if folder:
            player_bridge.save_folders(player_bridge.load_folders() + [os.path.normpath(folder)])
            self.refresh_folders()
            self.rescan()

    def remove_folder(self):
        item = self.folders.currentItem()
        if item:
            folders = [f for f in player_bridge.load_folders() if f != item.data(Qt.ItemDataRole.UserRole)]
            player_bridge.save_folders(folders)
            self.refresh_folders()
            self.rescan()

    # ----- other apps -----
    def _sessions_ready(self, items):
        while self.sessions_box.count():
            child = self.sessions_box.takeAt(0)
            if child.layout():
                while child.layout().count():
                    widget = child.layout().takeAt(0).widget()
                    if widget:
                        widget.deleteLater()
        for session in items:
            row = QHBoxLayout()
            name = label(f"{session['title']} — {session['artist']}" if session["artist"] else session["title"])
            row.addWidget(name, 1)
            row.addWidget(label(f"{SOURCE_NAMES.get(session['kind'], '')} · {session['source']}", "caption"))
            for symbol, cmd, tip in (("prev", "prev", "Предыдущий"),
                                     ("pause" if session["status"] == "playing" else "play", "toggle", "Пауза / play"),
                                     ("next", "next", "Следующий")):
                row.addWidget(icon_button(symbol, lambda _=False, c=cmd, s=session["id"]: self.sessions.command(c, s), tip))
            self.sessions_box.addLayout(row)
        if self.sessions.available:
            self.sessions_note.setText("" if items else "Сейчас другие приложения ничего не воспроизводят.")
        self.sessions_note.setVisible(bool(self.sessions_note.text()))

    def showEvent(self, event):
        self.sessions.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.sessions.stop()
        super().hideEvent(event)


def build(context):
    return MusicScreen(context)
