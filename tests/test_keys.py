"""Media keys without PyAutoGUI."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import keys  # noqa: E402


class KeysTests(unittest.TestCase):
    def events(self, action):
        user32 = mock.Mock()
        with mock.patch.object(keys, "_user32", return_value=user32), mock.patch.object(keys.time, "sleep"):
            action()
        return [call.args for call in user32.keybd_event.call_args_list]

    def test_media_key_is_extended_down_then_up(self):
        self.assertEqual(self.events(lambda: keys.press("playpause")), [(0xB3, 0, 0x1, 0), (0xB3, 0, 0x3, 0)])

    def test_repeated_presses(self):
        self.assertEqual(len(self.events(lambda: keys.press("volumeup", 3, 0.02))), 6)

    def test_hotkey_releases_in_reverse_order(self):
        self.assertEqual(self.events(lambda: keys.hotkey("alt", "f4")),
                         [(0x12, 0, 0, 0), (0x73, 0, 0, 0), (0x73, 0, 0x2, 0), (0x12, 0, 0x2, 0)])

    def test_unknown_key(self):
        with self.assertRaises(ValueError):
            keys.press("launchrockets")


if __name__ == "__main__":
    unittest.main()
