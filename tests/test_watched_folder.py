"""Bevakad mapp (7): upptäcker nya filer men importerar aldrig själv."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import watched_folder as wf  # noqa: E402


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.path = self.base / "watched.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_default_is_disabled(self):
        data = wf.load_settings(self.path)
        self.assertFalse(data["enabled"])
        self.assertEqual(data["folders"], [])

    def test_invalid_settings_disable_watching(self):
        for broken in ("{trasigt", json.dumps({"version": 99}), json.dumps({"version": 1, "enabled": "ja"})):
            self.path.write_text(broken, encoding="utf-8")
            self.assertFalse(wf.load_settings(self.path)["enabled"])
        self.path.write_text(json.dumps({"version": 1, "enabled": True, "folders": [], "seen": {}}), encoding="utf-8")
        self.assertTrue(wf.load_settings(self.path)["enabled"])

    def test_save_roundtrip_and_validation(self):
        data = {"version": 1, "enabled": True, "folders": [str(self.base)], "seen": {}}
        wf.save_settings(self.path, data)
        self.assertEqual(wf.load_settings(self.path)["folders"], [str(self.base)])
        with self.assertRaises(ValueError):
            wf.save_settings(self.path, {"version": 1, "enabled": True})

    def test_only_existing_absolute_folders_are_accepted(self):
        accepted = wf.normalize_folders([str(self.base), "relativ/mapp", str(self.base / "saknas")])
        self.assertEqual(len(accepted), 1)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.folder = self.base / "inkorg"
        self.folder.mkdir()
        self.settings = {"version": 1, "enabled": True, "folders": [str(self.folder)], "seen": {}}

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name: str, content: bytes = b"data", age: float = 60.0) -> Path:
        path = self.folder / name
        path.write_bytes(content)
        old = time.time() - age
        os.utime(path, (old, old))
        return path

    def test_disabled_watching_returns_nothing(self):
        self.write("ny.xlsx")
        disabled = dict(self.settings, enabled=False)
        self.assertEqual(wf.scan(disabled, now=time.time()), [])

    def test_only_import_formats_are_reported(self):
        self.write("ny.xlsx")
        self.write("ny.csv", b"a;b")
        self.write("ny.pdf", b"%PDF-1.4")
        self.write("bild.png", b"png")
        self.write("anteckning.txt", b"text")
        found = wf.scan(self.settings, now=time.time())
        self.assertEqual({item["name"] for item in found}, {"ny.xlsx", "ny.csv", "ny.pdf"})

    def test_temporary_hidden_and_empty_files_are_ignored(self):
        self.write("~$lock.xlsx")
        self.write(".dold.xlsx")
        self.write("halv.crdownload.xlsx")
        self.write("tom.xlsx", b"")
        self.assertEqual(wf.scan(self.settings, now=time.time()), [])

    def test_still_writing_files_are_delayed(self):
        self.write("färsk.xlsx", age=0.5)
        self.assertEqual(wf.scan(self.settings, now=time.time()), [])
        found = wf.scan(self.settings, now=time.time() + wf.SETTLE_SECONDS + 1)
        self.assertEqual(len(found), 1)

    def test_reported_files_are_not_reported_twice(self):
        self.write("ny.xlsx")
        found = wf.scan(self.settings, now=time.time())
        self.assertEqual(len(found), 1)
        updated = wf.mark_reported(self.settings, found)
        self.assertTrue(wf.valid_settings(updated))
        self.assertEqual(wf.scan(updated, now=time.time()), [])
        self.folder.joinpath("ny.xlsx").write_bytes("nytt innehåll".encode("utf-8"))
        os.utime(self.folder / "ny.xlsx", (time.time() - 60, time.time() - 60))
        self.assertEqual(len(wf.scan(updated, now=time.time())), 1)

    def test_seen_list_is_bounded(self):
        files = [{"path": f"/x/{index}.xlsx", "fingerprint": "1:1"} for index in range(600)]
        updated = wf.mark_reported(self.settings, files)
        self.assertLessEqual(len(updated["seen"]), 500)

    def test_clear_seen_allows_reporting_again(self):
        self.write("ny.xlsx")
        found = wf.scan(self.settings, now=time.time())
        updated = wf.mark_reported(self.settings, found)
        cleared = wf.clear_seen(updated)
        self.assertEqual(len(wf.scan(cleared, now=time.time())), 1)

    def test_scanning_never_modifies_or_moves_files(self):
        path = self.write("ny.xlsx")
        before = path.stat().st_mtime_ns
        wf.scan(self.settings, now=time.time())
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_unreadable_folder_is_skipped(self):
        settings = dict(self.settings, folders=[str(self.base / "finns-inte")])
        self.assertEqual(wf.scan(settings, now=time.time()), [])


if __name__ == "__main__":
    unittest.main()
