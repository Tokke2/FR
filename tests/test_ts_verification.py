"""TS-verifiering (11): analys, hinder och ett godkännande som inte kan kringgås."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import ts_safety, ts_verification as tv  # noqa: E402


def record(text: str = " " * 2500) -> bytes:
    return text.encode("utf-8")


class AnalyzeTests(unittest.TestCase):
    def test_valid_fixed_width_file_has_no_problems(self):
        data = (record("A" * 2500) + b"\r\n" + record("B" * 2500) + b"\r\n")
        structure = tv.analyze(data)
        self.assertEqual(structure["records"], 2)
        self.assertEqual(structure["record_lengths"], [2500])
        self.assertEqual(structure["line_endings"], "crlf")
        self.assertEqual(tv.compare(structure), [])

    def test_wrong_length_is_reported(self):
        structure = tv.analyze(record("A" * 100) + b"\n")
        problems = tv.compare(structure)
        self.assertTrue(any("2500" in problem for problem in problems))

    def test_semicolon_tab_and_empty_lines_are_reported(self):
        data = record("A" * 2498 + ";x") + b"\n\n"
        problems = tv.compare(tv.analyze(data))
        self.assertTrue(any("semikolon" in problem for problem in problems))
        self.assertTrue(any("tomma rader" in problem for problem in problems))
        tabbed = tv.compare(tv.analyze(record("A" * 2499 + "\t") + b"\n"))
        self.assertTrue(any("tabulator" in problem for problem in tabbed))

    def test_mixed_line_endings_are_reported(self):
        data = record("A" * 2500) + b"\r\n" + record("B" * 2500) + b"\n"
        problems = tv.compare(tv.analyze(data))
        self.assertTrue(any("radslut" in problem for problem in problems))

    def test_encoding_is_detected_without_guessing(self):
        self.assertEqual(tv.decode("åäö".encode("utf-8"))[1], "utf-8")
        self.assertEqual(tv.decode(b"\xef\xbb\xbfabc")[1:], ("utf-8-sig", True))
        self.assertEqual(tv.decode("åäö".encode("cp1252"))[1], "cp1252")

    def test_empty_binary_and_oversized_input_are_rejected(self):
        with self.assertRaises(tv.VerificationError):
            tv.analyze(b"")
        with self.assertRaises(tv.VerificationError):
            tv.analyze(record("A" * 2500) + b"\x00")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stor.ts"
            path.write_bytes(b"A" * (tv.MAX_BYTES + 1))
            with self.assertRaises(tv.VerificationError):
                tv.report(path)

    def test_report_does_not_write_or_unlock(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "riktig.ts"
            path.write_bytes((record("A" * 2500) + b"\r\n"))
            before = sorted(p.name for p in base.iterdir())
            data = tv.report(path)
            self.assertTrue(data["can_lock_open"])
            self.assertEqual(sorted(p.name for p in base.iterdir()), before)
            self.assertIsNone(tv.approval(base))
            self.assertIn("spärrad", ts_safety.generation_block_reason(base))

    def test_symlinked_and_missing_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "mål.ts"
            target.write_bytes(record())
            link = base / "länk.ts"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symboliska länkar stöds inte")
            with self.assertRaises(tv.VerificationError):
                tv.report(link)
            with self.assertRaises(tv.VerificationError):
                tv.report(base / "saknas.ts")


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / "riktig.ts"
        self.file.write_bytes(record("A" * 2500) + b"\r\n")
        self.report = tv.report(self.file)

    def tearDown(self):
        self.temp.cleanup()

    def test_approval_requires_confirmation_and_note(self):
        with self.assertRaises(tv.VerificationError):
            tv.approve(self.root, self.report, confirmed=False, note="Jag har granskat allt noggrant.")
        with self.assertRaises(tv.VerificationError):
            tv.approve(self.root, self.report, confirmed=True, note="kort")
        self.assertIsNone(tv.approval(self.root))

    def test_approval_is_refused_when_report_has_problems(self):
        bad = self.root / "fel.ts"
        bad.write_bytes(record("A" * 10) + b"\n")
        with self.assertRaises(tv.VerificationError):
            tv.approve(self.root, tv.report(bad), confirmed=True,
                       note="Jag har granskat rapporten och godkänner formatet.")

    def test_approved_format_unlocks_only_with_matching_source(self):
        tv.approve(self.root, self.report, confirmed=True,
                   note="Jämfört mot Transportstyrelsens exempel och hela filen.")
        self.assertEqual(ts_safety.generation_block_reason(self.root), "")
        self.assertIsNotNone(tv.approval(self.root, source=self.file))
        self.file.write_bytes(record("B" * 2500) + b"\r\n")
        self.assertIsNone(tv.approval(self.root, source=self.file))
        tampered = json.loads((self.root / tv.VERIFICATION_NAME).read_text(encoding="utf-8"))
        tampered["sha256"] = "0" * 64
        (self.root / tv.VERIFICATION_NAME).write_text(json.dumps(tampered), encoding="utf-8")
        self.assertEqual(ts_safety.generation_block_reason(self.root), "")
        self.assertIsNone(tv.approval(self.root, source=self.file))

    def test_missing_or_broken_approval_keeps_block(self):
        self.assertIn("spärrad", ts_safety.generation_block_reason(self.root))
        (self.root / tv.VERIFICATION_NAME).write_text("{trasigt", encoding="utf-8")
        self.assertIn("spärrad", ts_safety.generation_block_reason(self.root))
        self.assertIsNone(tv.approval(self.root))
        self.assertIn("kan inte användas", tv.status(self.root))

    def test_generation_stays_blocked_without_root(self):
        tv.approve(self.root, self.report, confirmed=True,
                   note="Jämfört mot Transportstyrelsens exempel och hela filen.")
        self.assertIn("spärrad", ts_safety.generation_block_reason())

    def test_status_text_mentions_path_forward(self):
        self.assertIn("Verifiera TS-underlag", tv.status(self.root))
        tv.approve(self.root, self.report, confirmed=True,
                   note="Jämfört mot Transportstyrelsens exempel och hela filen.")
        self.assertIn("verifierat", tv.status(self.root).casefold())


if __name__ == "__main__":
    unittest.main()
