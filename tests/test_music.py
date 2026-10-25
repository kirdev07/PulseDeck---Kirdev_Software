"""Stage C: built-in player extensions and the «Музыка» screen."""
import math
import os
import struct
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_pc.app import create_application  # noqa: E402

APP = create_application([])

from modules import player_bridge  # noqa: E402
from pulse_pc.core.state import StateStore  # noqa: E402
from pulse_pc.services.media import player as media  # noqa: E402
from pulse_pc.ui.screens.music import MusicScreen  # noqa: E402


def tone(path, seconds=1):
    with wave.open(str(path), "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"".join(struct.pack("<h", int(2000 * math.sin(n / 5))) for n in range(8000 * seconds)))


class NoSessions(media.MediaSessions):
    def __init__(self):
        super().__init__()
        self.available = False


class PlayerTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # Windows Media may still hold a file
        root = Path(self.dir.name)
        (root / "lib").mkdir()
        for name in ("x", "y", "z"):
            tone(root / "lib" / f"{name}.wav")
        self.config = mock.patch.object(player_bridge, "CONFIG_PATH", str(root / "player.json"))
        self.config.start()
        player_bridge.save_folders([str(root / "lib")])
        self.player = media.MusicPlayer()
        self.player.audio.setMuted(True)
        self.tracks = player_bridge.scan_tracks()

    def tearDown(self):
        self.player.player.stop()
        self.player.player.setSource(media.QMediaPlayer().source())
        self.config.stop()
        player_bridge.CONTROLLER = None
        self.dir.cleanup()


class MusicPlayerTests(PlayerTestCase):
    def test_queue_next_wraps_with_repeat_all(self):
        self.player.open_track(self.tracks[2]["path"], self.tracks)
        self.assertEqual(self.player.index, 2)
        self.player.handle("next")
        self.assertEqual(self.player.index, 0)

    def test_repeat_off_stops_at_the_end(self):
        self.player.open_track(self.tracks[2]["path"], self.tracks)
        self.assertEqual(self.player.cycle_repeat(), "one")
        self.assertEqual(self.player.cycle_repeat(), "off")
        self.player.handle("next")
        self.assertEqual(self.player.index, 2)

    def test_shuffle_never_repeats_current_and_prev_goes_back(self):
        self.player.open_track(self.tracks[0]["path"], self.tracks)
        self.player.set_shuffle(True)
        self.player.step(1)
        self.assertNotEqual(self.player.index, 0)
        self.player.step(-1)
        self.assertEqual(self.player.index, 0)

    def test_phone_commands_reach_the_new_player(self):
        self.assertIs(player_bridge.CONTROLLER, self.player)
        self.player.open_track(self.tracks[0]["path"], self.tracks)
        player_bridge.send("next")
        APP.processEvents()
        self.assertEqual(self.player.index, 1)

    def test_state_is_mirrored_to_store(self):
        store = StateStore()
        media.publish_to_store(self.player, store)
        self.player.open_track(self.tracks[1]["path"], self.tracks)
        deadline = time.monotonic() + 5
        while store.state.player.status != "playing" and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.02)
        self.assertEqual(store.state.player.status, "playing")
        self.assertEqual(store.state.player.title, "y")


class MusicScreenTests(PlayerTestCase):
    def setUp(self):
        super().setUp()
        self.screen = MusicScreen(player=self.player, sessions=NoSessions())
        deadline = time.monotonic() + 5
        while not self.screen.tracks and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.02)

    def test_library_scan_search_and_play_filtered_queue(self):
        self.assertEqual(self.screen.library.count(), 3)
        self.assertEqual(self.screen.library_count.text(), "Треков: 3")
        self.screen.search.setText("y")
        hidden = [self.screen.library.item(r).isHidden() for r in range(3)]
        self.assertEqual(hidden, [True, False, True])
        self.screen.play_item(self.screen.library.item(1))
        self.assertEqual([t["title"] for t in self.player.queue], ["y"])
        self.assertEqual(self.screen.queue_list.count(), 1)

    def test_idle_state_and_missing_winrt(self):
        self.assertEqual(self.screen.title.text(), "Ничего не играет")
        self.assertFalse(self.screen.seek.isEnabled())
        self.assertIn("winrt", self.screen.sessions_note.text())

    def test_repeat_button_cycles(self):
        self.screen._cycle_repeat()
        self.assertEqual(self.player.repeat, "one")
        self.screen._cycle_repeat()
        self.assertFalse(self.screen.repeat_button.isChecked())

    def test_external_sessions_render(self):
        self.screen.sessions.available = True
        self.screen._sessions_ready([{"id": "Spotify.exe", "source": "Spotify", "kind": "stream",
                                      "title": "Song", "artist": "Band", "status": "playing"}])
        self.assertEqual(self.screen.sessions_box.count(), 1)
        self.assertFalse(self.screen.sessions_note.isVisibleTo(self.screen))


if __name__ == "__main__":
    unittest.main()
