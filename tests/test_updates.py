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

    def test_skips_prerelease_draft_and_missing_installer(self):
        asset = [{"name": "PulseDeck-2.0.0-Setup.exe"}]
        self.assertIsNone(updates.parse({"tag_name": "v2", "prerelease": True, "assets": asset}))
        self.assertIsNone(updates.parse({"tag_name": "v2", "draft": True, "assets": asset}))
        self.assertIsNone(updates.parse({"tag_name": "v2", "assets": [{"name": "src.zip"}]}))


if __name__ == "__main__":
    unittest.main()
