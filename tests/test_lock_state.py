import ctypes
import unittest
from unittest import mock

from modules import monitor


class LockStateTest(unittest.TestCase):
    def test_uac_prompt_is_not_a_lock(self):
        # An installer's UAC prompt: secure desktop (old check says «locked»), session unlocked.
        with mock.patch.object(monitor, "_session_locked", return_value=False), \
                mock.patch.object(monitor, "_input_desktop_locked", return_value=True):
            self.assertFalse(monitor.workstation_locked())

    def test_lock_screen_is_a_lock(self):
        with mock.patch.object(monitor, "_session_locked", return_value=True), \
                mock.patch.object(monitor, "_input_desktop_locked", return_value=True):
            self.assertTrue(monitor.workstation_locked())

    def test_old_check_when_windows_does_not_say(self):
        for failure in ({"return_value": None}, {"side_effect": OSError}):
            with mock.patch.object(monitor, "_session_locked", **failure), \
                    mock.patch.object(monitor, "_input_desktop_locked", return_value=True):
                self.assertTrue(monitor.workstation_locked())

    def test_layout_matches_wtsapi32(self):
        # 64-bit Windows: Level, 4 bytes of padding, then the level-1 data (232 bytes in all).
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(monitor._WtsInfoEx), 232)
        self.assertEqual(monitor._WtsInfoEx.Data.offset, 8)
        self.assertEqual(monitor._WtsInfoLevel1.SessionFlags.offset, 8)

    def test_this_unlocked_session_reads_unlocked(self):
        # The tests run in an unlocked session: Windows must say so (not None, not «locked»).
        self.assertIs(monitor._session_locked(), False)


if __name__ == "__main__":
    unittest.main()
