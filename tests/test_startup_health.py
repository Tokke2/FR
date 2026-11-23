"""Starthälsokontroll (22): markör, återfall och fail-closed-beteende."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import startup_health as sh  # noqa: E402


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "core").mkdir()
        self.file = self.root / "core" / "modul.py"
        self.file.write_text("ny version\n", encoding="utf-8")
        self.backup = self.root / ".update-backups" / "kopia"
        (self.backup / "core").mkdir(parents=True)
        (self.backup / "core" / "modul.py").write_text("gammal version\n", encoding="utf-8")
        (self.backup / "manifest.json").write_text(json.dumps({"files": ["core/modul.py"]}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_without_marker_nothing_happens(self):
        result = sh.check_and_recover(self.root)
        self.assertFalse(result["pending"])
        self.assertEqual(result["recovered"], [])
        self.assertEqual(self.file.read_text(encoding="utf-8"), "ny version\n")

    def test_marker_written_with_hashes_and_confirmed_after_start(self):
        marker = sh.mark_pending(self.root, self.backup, ["core/modul.py"])
        self.assertTrue(marker.is_file())
        data = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(len(data["files"][0]["sha256"]), 64)
        self.assertTrue(sh.confirm_healthy(self.root))
        self.assertFalse(sh.confirm_healthy(self.root))
        self.assertFalse(sh.check_and_recover(self.root)["pending"])

    def test_unconfirmed_start_restores_backup(self):
        sh.mark_pending(self.root, self.backup, ["core/modul.py"])
        result = sh.check_and_recover(self.root)
        self.assertTrue(result["pending"])
        self.assertEqual(result["recovered"], ["core/modul.py"])
        self.assertEqual(self.file.read_text(encoding="utf-8"), "gammal version\n")
        self.assertFalse((self.root / sh.STATE_DIR / sh.PENDING_NAME).exists())
        history = (self.root / sh.STATE_DIR / sh.HISTORY_NAME).read_text(encoding="utf-8")
        self.assertIn("automatic_rollback", history)

    def test_missing_backup_keeps_files_and_reports_error(self):
        sh.mark_pending(self.root, self.backup, ["core/modul.py"])
        (self.backup / "core" / "modul.py").unlink()
        result = sh.check_and_recover(self.root)
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["recovered"], [])
        self.assertEqual(self.file.read_text(encoding="utf-8"), "ny version\n")
        self.assertTrue((self.root / sh.STATE_DIR / sh.PENDING_NAME).exists())

    def test_missing_manifest_blocks_rollback(self):
        sh.mark_pending(self.root, self.backup, ["core/modul.py"])
        (self.backup / "manifest.json").unlink()
        result = sh.check_and_recover(self.root)
        self.assertIn("manifest", result["error"])
        self.assertEqual(self.file.read_text(encoding="utf-8"), "ny version\n")

    def test_broken_marker_is_reported_and_never_deletes_data(self):
        state = self.root / sh.STATE_DIR
        state.mkdir()
        (state / sh.PENDING_NAME).write_text("{trasigt", encoding="utf-8")
        result = sh.check_and_recover(self.root)
        self.assertIn("skadad", result["error"])
        self.assertEqual(self.file.read_text(encoding="utf-8"), "ny version\n")

    def test_unsafe_paths_are_rejected(self):
        for name in ("../utanför.py", "/absolut.py", "core/../../x.py", "core/.dold.py"):
            with self.assertRaises(sh.HealthError):
                sh.mark_pending(self.root, self.backup, [name])
        self.assertFalse((self.root / sh.STATE_DIR / sh.PENDING_NAME).exists())

    def test_mark_pending_requires_existing_updated_files(self):
        with self.assertRaises(sh.HealthError):
            sh.mark_pending(self.root, self.backup, ["core/saknas.py"])
        self.assertIsNone(sh.mark_pending(self.root, self.backup, []))

    def test_symlinked_state_dir_is_not_used(self):
        target = self.root / "annanstans"
        target.mkdir()
        (self.root / sh.STATE_DIR).symlink_to(target, target_is_directory=True)
        with self.assertRaises((sh.HealthError, OSError)):
            sh.mark_pending(self.root, self.backup, ["core/modul.py"])

    def test_health_section_shows_pending_state(self):
        from core.dashboard import health_section
        self.assertFalse(health_section(self.root)["pending"])
        sh.mark_pending(self.root, self.backup, ["core/modul.py"])
        self.assertTrue(health_section(self.root)["pending"])


if __name__ == "__main__":
    unittest.main()
