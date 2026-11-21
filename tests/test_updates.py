import unittest

from pulse_pc.services import updates


class UpdatesTest(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(updates.is_newer("1.0.1", "1.0.0"))
        self.assertTrue(updates.is_newer("1.0.10", "1.0.9"))
        self.assertTrue(updates.is_newer("2.0", "1.9.9"))
        self.assertFalse(updates.is_newer("1.0", "1.0.0"))
        self.assertFalse(updates.is_newer("0.9", "1.0.0"))

    def test_parses_release_with_installer(self):
        release = updates.parse({
            "tag_name": "v1.0.1", "body": "## Что нового\n- **Автообновление** с [GitHub](https://github.com)",
            "assets": [{"name": "notes.txt"}, {"name": "PulseDeck-1.0.1-Setup.exe",
                                               "browser_download_url": "https://x/s.exe", "size": 7}]})
        self.assertEqual(release.version, "1.0.1")
        self.assertEqual(release.name, "PulseDeck-1.0.1-Setup.exe")
        self.assertEqual(release.size, 7)
        self.assertEqual(release.notes, "Что нового\n• Автообновление с GitHub")
        self.assertIn("**Автообновление**", release.markdown)       # kept as written, shown formatted

    def test_changelog_section_of_the_version(self):
        import tempfile
        from pathlib import Path
        path = Path(tempfile.mkdtemp()) / "CHANGELOG.md"
        path.write_text("# Журнал\n\n## [Не выпущено]\n- новое\n\n## [1.0.2] — 2026-10-28\n### Изменено\n- QR 240 px\n\n"
                        "## [1.0.1]\n- QR\n\n[1.0.2]: https://example.com\n", encoding="utf-8")
        self.assertEqual(updates.changelog_section(path, "1.0.2"), "### Изменено\n- QR 240 px")
        self.assertEqual(updates.changelog_section(path, "9.9.9"), "- новое")       # unknown: the newest section
        self.assertEqual(updates.changelog_section(path.with_name("none.md"), "1.0.2"), "")

    def test_last_check_time(self):
        import json
        import tempfile
        from pathlib import Path
        folder = Path(tempfile.mkdtemp())
        self.assertIsNone(updates.last_check(folder))
        (folder / "update_check.json").write_text(json.dumps({"time": 1700000000}), encoding="utf-8")
        self.assertEqual(updates.last_check(folder), 1700000000.0)

    def test_skips_prerelease_draft_and_missing_installer(self):
        asset = [{"name": "PulseDeck-2.0.0-Setup.exe"}]
        self.assertIsNone(updates.parse({"tag_name": "v2", "prerelease": True, "assets": asset}))
        self.assertIsNone(updates.parse({"tag_name": "v2", "draft": True, "assets": asset}))
        self.assertIsNone(updates.parse({"tag_name": "v2", "assets": [{"name": "src.zip"}]}))


if __name__ == "__main__":
    unittest.main()
