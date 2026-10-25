"""Stage E: the bot token is stored encrypted with DPAPI and migrated from .env."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_pc.core import secrets  # noqa: E402
from pulse_pc.core.settings import read_env, write_env  # noqa: E402

TOKEN = "123456789:AAH" + "s" * 32
ROOT = Path(__file__).resolve().parents[1]


class SecretStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_roundtrip_and_file_has_no_plaintext(self):
        store = secrets.SecretStore(self.root)
        store.set("BOT_TOKEN", TOKEN)
        self.assertEqual(store.get("BOT_TOKEN"), TOKEN)
        raw = (self.root / secrets.FILE_NAME).read_bytes()
        self.assertNotIn(TOKEN.encode(), raw)
        self.assertNotIn(TOKEN.split(":")[1].encode(), raw)
        store.set("BOT_TOKEN", "")
        self.assertEqual(store.get("BOT_TOKEN"), "")

    def test_damaged_blob_raises_clear_error(self):
        (self.root / secrets.FILE_NAME).write_text('{"BOT_TOKEN": "AAAA"}', encoding="utf-8")
        with self.assertRaises(secrets.SecretError):
            secrets.SecretStore(self.root).get("BOT_TOKEN")
        self.assertEqual(secrets.load_token(self.root), "")   # treated as «not set», never crashes

    def test_migration_moves_token_out_of_env(self):
        write_env(self.root / ".env", {"BOT_TOKEN": TOKEN, "ADMIN_ID": "42"})
        self.assertTrue(secrets.migrate_token(self.root))
        env = read_env(self.root / ".env")
        self.assertEqual(env["BOT_TOKEN"], secrets.PLACEHOLDER_TOKEN)
        self.assertEqual(env["ADMIN_ID"], "42")
        self.assertNotIn(TOKEN, (self.root / ".env").read_text(encoding="utf-8"))
        self.assertEqual(secrets.load_token(self.root), TOKEN)
        self.assertFalse(secrets.migrate_token(self.root))    # second run does nothing

    def test_load_prefers_store_and_falls_back_to_env(self):
        write_env(self.root / ".env", {"BOT_TOKEN": TOKEN})
        self.assertEqual(secrets.load_token(self.root), TOKEN)
        secrets.SecretStore(self.root).set("BOT_TOKEN", "999:" + "z" * 35)
        self.assertEqual(secrets.load_token(self.root), "999:" + "z" * 35)

    def test_classic_config_module_reads_the_encrypted_token(self):
        """config.py (used by the bot of the classic panel) must see the migrated token."""
        app_dir = self.root / "app"
        (app_dir / "config").mkdir(parents=True)
        (app_dir / "config.py").write_text((ROOT / "config.py").read_text(encoding="utf-8"), encoding="utf-8")
        write_env(app_dir / "config" / ".env", {"BOT_TOKEN": TOKEN, "ADMIN_ID": "42"})
        secrets.migrate_token(app_dir / "config")
        env = {k: v for k, v in os.environ.items() if k not in ("BOT_TOKEN", "ADMIN_ID")}
        env["PYTHONPATH"] = os.pathsep.join((str(app_dir), str(ROOT)))
        out = subprocess.run([sys.executable, "-c", "import config; print(config.BOT_TOKEN == %r, config.ADMIN_ID)" % TOKEN],
                             capture_output=True, text=True, env=env, cwd=app_dir, timeout=60)
        self.assertEqual(out.stdout.split(), ["True", "42"], out.stderr)


if __name__ == "__main__":
    unittest.main()
