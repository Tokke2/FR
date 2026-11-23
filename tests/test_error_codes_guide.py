"""Åtgärdsguider för felkoder (24) och instrumentpanelens data (21)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import dashboard, error_codes  # noqa: E402


class GuideTests(unittest.TestCase):
    def test_known_code_has_cause_and_steps(self):
        entry = error_codes.guide_for("CONFIG_PARSE_ERROR")
        self.assertEqual(entry["code"], "CONFIG_PARSE_ERROR")
        self.assertTrue(entry["title"])
        self.assertTrue(entry["cause"])
        self.assertGreaterEqual(len(entry["steps"]), 2)
        self.assertTrue(entry["automatic_resolution"])

    def test_code_is_case_insensitive_and_only_verified_codes_resolve(self):
        self.assertIsNotNone(error_codes.guide_for("config_parse_error"))
        self.assertFalse(error_codes.guide_for("PLUGIN_LOAD_ERROR")["automatic_resolution"])

    def test_unknown_code_gets_honest_help(self):
        self.assertIsNone(error_codes.guide_for("SOMETHING_ELSE"))
        lines = error_codes.guide_lines("SOMETHING_ELSE")
        self.assertIn("Ingen åtgärdsguide", lines[0])
        self.assertIn("upprepas", " ".join(lines))

    def test_guide_lines_are_readable(self):
        lines = error_codes.guide_lines("DEPENDENCY_ERROR")
        self.assertIn("Gör så här:", lines)
        self.assertTrue(any(line.startswith("1.") for line in lines))
        self.assertTrue(any("verifieras" in line or "verifierat" in line for line in lines))

    def test_registry_is_read_without_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "felkoder.json"
            payload = {"version": 1, "entries": {
                "a": {"code": "CONFIG_PARSE_ERROR", "status": "aktiv", "message": "trasig", "count": 2,
                      "last_seen": "2026-10-01T10:00:00"},
                "b": {"code": "OKAND_KOD", "status": "åtgärdad", "message": "gammal", "count": 1,
                      "last_seen": "2026-09-01T10:00:00"},
                "c": "trasig post",
            }}
            path.write_text(json.dumps(payload), encoding="utf-8")
            before = path.read_bytes()
            rows = error_codes.read_entries(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual([row["code"] for row in rows], ["CONFIG_PARSE_ERROR", "OKAND_KOD"])
            self.assertTrue(rows[0]["known"])
            self.assertFalse(rows[1]["known"])
            self.assertIn("1 aktiva felkoder", error_codes.summary(rows))

    def test_broken_registry_gives_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "felkoder.json"
            path.write_text("{trasigt", encoding="utf-8")
            self.assertEqual(error_codes.read_entries(path), [])
            self.assertEqual(error_codes.summary([]), "Inga aktiva felkoder.")


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        vehicles = self.root / "data" / "vehicles"
        vehicles.mkdir(parents=True)
        (vehicles / "2025.json").write_text(json.dumps({
            "_meta": {"updated_at": "2026-10-01T10:00:00+00:00", "year": 2025},
            "vehicles": [{"vin_kod": "AAA111"}, {"vin_kod": "BBB222"}],
        }), encoding="utf-8")
        (vehicles / "2024.json").write_text("{trasigt", encoding="utf-8")
        (self.root / "data" / "farger.json").write_text(json.dumps([
            {"code": "SV", "name": "Svart"},
            {"code": "", "name": "Ny färg", "dispatch_pending_id": "@dispatch:" + "a" * 33},
        ]), encoding="utf-8")
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "felkoder.json").write_text(json.dumps({"version": 1, "entries": {
            "k": {"code": "DEPENDENCY_ERROR", "status": "aktiv", "message": "saknas", "count": 1,
                  "last_seen": "2026-10-02T10:00:00"}}}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_sections_report_real_numbers(self):
        data = dashboard.build(self.root)
        vehicles = data["sections"]["vehicles"]
        self.assertEqual(vehicles["total"], 2)
        self.assertEqual(vehicles["years"], 2)
        self.assertTrue(any(row["error"] for row in vehicles["rows"]))
        colors = data["sections"]["colors"]
        self.assertEqual((colors["total"], colors["pending"], colors["mapped"]), (2, 1, 1))
        self.assertEqual(data["sections"]["errors"]["active"], 1)
        self.assertTrue(data["sections"]["ts"]["blocked"])
        self.assertFalse(data["sections"]["health"]["pending"])

    def test_headline_mentions_pending_colors_and_blocked_ts(self):
        headline = dashboard.build(self.root)["headline"]
        self.assertIn("2 fordon", headline)
        self.assertIn("väntar på koppling", headline)
        self.assertIn("spärrad", headline)

    def test_missing_files_do_not_raise(self):
        with tempfile.TemporaryDirectory() as empty:
            data = dashboard.build(Path(empty))
            self.assertEqual(data["sections"]["vehicles"]["total"], 0)
            self.assertFalse(data["sections"]["colors"]["available"])
            self.assertIn("Ingen fordonsdata", data["headline"])

    def test_dashboard_never_writes(self):
        before = sorted(p.as_posix() for p in self.root.rglob("*"))
        dashboard.build(self.root)
        self.assertEqual(sorted(p.as_posix() for p in self.root.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
