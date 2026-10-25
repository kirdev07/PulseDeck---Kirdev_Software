"""Stage B: design system and navigation shell of Pulse-PC Fusion 2.0."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSize  # noqa: E402

from pulse_pc.app import create_application  # noqa: E402

APP = create_application([])

from pulse_pc.ui.components import UNAVAILABLE, Sparkline, StatTile, StatusDot, Toggle  # noqa: E402
from pulse_pc.ui.screens.registry import SCREENS  # noqa: E402
from pulse_pc.ui.shell import MainWindow  # noqa: E402
from pulse_pc.ui.theme import icon, icons, stylesheet, tokens  # noqa: E402


class ThemeTests(unittest.TestCase):
    def test_palette_is_monochrome(self):
        for name in dir(tokens):
            value = getattr(tokens, name)
            if isinstance(value, str) and value.startswith("#") and len(value) == 7:
                r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
                self.assertTrue(r == g == b, f"{name}={value} is not grey")

    def test_stylesheet_builds_without_placeholders(self):
        css = stylesheet()
        self.assertIn(tokens.BG, css)
        self.assertNotIn("{t.", css)

    def test_every_icon_renders(self):
        for name in icons.names():
            image = icon(name, tokens.TEXT).pixmap(QSize(24, 24), 2.0)
            self.assertFalse(image.isNull(), name)
            self.assertEqual(image.width(), 48, name)  # rendered at the device pixel ratio


class ComponentTests(unittest.TestCase):
    def test_stat_tile_reports_unavailable_honestly(self):
        tile = StatTile("gpu", "GPU")
        self.assertEqual(tile.value.text(), UNAVAILABLE)
        tile.set_value(42.4, "1.2 ГГц")
        self.assertEqual(tile.value.text(), "42%")
        self.assertEqual(tile.bar.value(), 424)
        tile.set_value(None)
        self.assertEqual(tile.value.text(), UNAVAILABLE)
        self.assertTrue(tile.bar.isHidden())
        self.assertEqual(list(tile.chart.samples), [42.4, None])

    def test_sparkline_keeps_capacity_and_gaps(self):
        chart = Sparkline(capacity=3)
        for value in (1, None, -5, 7):
            chart.append(value)
        self.assertEqual(list(chart.samples), [None, 0.0, 7.0])
        chart.resize(100, 30)
        chart.grab()  # paints without error, including gaps

    def test_toggle_is_checkable(self):
        toggle = Toggle()
        seen = []
        toggle.toggled.connect(seen.append)
        toggle.click()
        self.assertTrue(toggle.isChecked())
        self.assertEqual(seen, [True])

    def test_status_dot_states(self):
        dot = StatusDot()
        for state in StatusDot.STATES:
            dot.set_state(state)
            dot.grab()
        with self.assertRaises(ValueError):
            dot.set_state("green")


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow(animate=False)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def test_all_seven_screens_are_navigable(self):
        self.assertEqual([s.key for s in SCREENS],
                         ["dashboard", "telegram", "phone", "apps", "console", "music", "settings"])
        self.assertEqual(self.window.current_key(), "dashboard")
        for screen in SCREENS:
            self.window.sidebar.items[screen.key].click()
            self.assertEqual(self.window.current_key(), screen.key)
            self.assertTrue(self.window.sidebar.items[screen.key].isChecked())

    def test_screens_are_built_lazily_once(self):
        self.assertEqual(list(self.window.pages), ["dashboard"])
        self.window.open("music")
        page = self.window.pages["music"]
        self.window.open("dashboard")
        self.window.open("music")
        self.assertIs(self.window.pages["music"], page)

    def test_quick_search_navigates(self):
        bar = self.window.titlebar
        bar.search.setText("журнал")
        bar.search.returnPressed.emit()
        self.assertEqual(self.window.current_key(), "console")
        self.assertEqual(bar.search.text(), "")
        bar.search.setText("тел")
        bar.search.returnPressed.emit()
        self.assertEqual(self.window.current_key(), "phone")  # partial match on «Телефон»

    def test_unknown_route_is_ignored(self):
        self.window.open("nope")
        self.assertEqual(self.window.current_key(), "dashboard")

    def test_sidebar_status_hidden_until_reported(self):
        self.assertTrue(self.window.sidebar.status.isHidden())
        self.window.sidebar.set_status("Система активна", "ok")
        self.assertFalse(self.window.sidebar.status.isHidden())


if __name__ == "__main__":
    unittest.main()
