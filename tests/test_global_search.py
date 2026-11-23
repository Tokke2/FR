"""Global sökning (17): index, relevans och säker ombyggnad."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import global_search as gs  # noqa: E402


def payload(records):
    return {"_meta": {"count": len(records)}, "vehicles": records}


class IndexTests(unittest.TestCase):
    def test_index_skips_records_without_searchable_values(self):
        data = gs.build_index([(2025, payload([{"vin_kod": "1AK74S"}, {}, {"vin_kod": None}]), "2025.json")])
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["year"], 2025)
        self.assertEqual(data["entries"][0]["row"], 0)

    def test_invalid_year_and_payload_are_skipped(self):
        data = gs.build_index([("okänt", {"vehicles": []}, "x"), (2024, "trasigt", "2024.json")])
        self.assertEqual(data["entries"], [])

    def test_priority_field_ranks_exact_match_above_other_fields(self):
        records = [
            {"vin_kod": "AAA111", "handelsbeteckning": "STREET"},
            {"vin_kod": "BBB222", "handelsbeteckning": "AAA111 kopia"},
        ]
        index = gs.build_index([(2025, payload(records), "2025.json")])
        hits = gs.search(index, "AAA111")
        self.assertEqual(hits[0]["title"], "AAA111")
        self.assertEqual(hits[0]["field"], "VIN-kod")
        self.assertGreater(hits[0]["score"], hits[1]["score"])

    def test_search_is_case_insensitive_and_supports_tokens(self):
        records = [{"vin_kod": "1AK74S", "farg": "Svart metallic", "aterforsaljare": "Kista MC"}]
        index = gs.build_index([(2024, payload(records), "2024.json")])
        self.assertEqual(len(gs.search(index, "svart KISTA")), 1)
        self.assertEqual(gs.search(index, "svart göteborg"), [])
        self.assertEqual(gs.search(index, "   "), [])

    def test_limit_and_empty_query(self):
        records = [{"vin_kod": f"VIN{number:03d}"} for number in range(30)]
        index = gs.build_index([(2025, payload(records), "2025.json")])
        self.assertEqual(len(gs.search(index, "VIN", limit=5)), 5)
        self.assertEqual(len(gs.search(index, "VIN")), 30)
        self.assertEqual(gs.search(index, ""), [])

    def test_invalid_index_is_rejected(self):
        for bad in ({}, {"version": 99, "entries": []}, {"version": 1, "entries": [{"year": "x"}]}):
            with self.assertRaises(ValueError):
                gs.search(bad, "x")
        self.assertFalse(gs.valid_index({"version": 1, "entries": [{"year": 1, "row": 0,
                                                                    "haystack": "a", "fields": {}}]} ) is False)


class FileIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.vehicles = self.base / "vehicles"
        self.vehicles.mkdir()
        (self.base / "vehicles" / "2025.json").write_text(
            json.dumps(payload([{"vin_kod": "ABC123", "farg": "Röd"}])), encoding="utf-8")
        (self.vehicles / "arkiv").mkdir()
        (self.vehicles / "arkiv" / "2021.json").write_text(
            json.dumps(payload([{"vin_kod": "OLD999"}])), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_index_includes_archive_and_is_rebuilt_when_source_changes(self):
        index_path = self.base / "search_index.json"
        first = gs.ensure_index(index_path, self.vehicles)
        self.assertEqual(len(first["entries"]), 2)
        self.assertTrue(index_path.is_file())
        self.assertIn("2021.json", [entry for entry in index_path.read_text(encoding="utf-8").split('"') if entry.endswith(".json")])
        second = gs.ensure_index(index_path, self.vehicles)
        self.assertEqual(second["entries"], first["entries"])

        (self.vehicles / "2026.json").write_text(
            json.dumps(payload([{"vin_kod": "NEW777"}])), encoding="utf-8")
        third = gs.ensure_index(index_path, self.vehicles)
        self.assertEqual(len(third["entries"]), 3)
        self.assertEqual(len(gs.search(third, "NEW777")), 1)

    def test_corrupted_index_is_rebuilt_without_touching_sources(self):
        index_path = self.base / "search_index.json"
        index_path.write_text("{trasigt", encoding="utf-8")
        data = gs.ensure_index(index_path, self.vehicles)
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual(json.loads((self.vehicles / "2025.json").read_text(encoding="utf-8"))
                         ["vehicles"][0]["vin_kod"], "ABC123")

    def test_symlinked_index_is_not_written(self):
        target = self.base / "utanför.json"
        target.write_text("{}", encoding="utf-8")
        link = self.base / "search_index.json"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symboliska länkar stöds inte i miljön")
        data = gs.ensure_index(link, self.vehicles)
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")

    def test_broken_year_file_does_not_stop_index(self):
        (self.vehicles / "2027.json").write_text("{trasig", encoding="utf-8")
        data = gs.ensure_index(self.base / "index.json", self.vehicles)
        self.assertEqual(len(data["entries"]), 2)


if __name__ == "__main__":
    unittest.main()
