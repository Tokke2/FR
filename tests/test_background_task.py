"""Bakgrundsarbete (9): avbrott, förlopp och att inget skrivs vid avbrott."""
from __future__ import annotations

from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import background_task as bt  # noqa: E402


class RunnerTests(unittest.TestCase):
    def test_successful_work_returns_value_and_time(self):
        outcome = bt.run(lambda progress: 42)
        self.assertTrue(outcome["ok"])
        self.assertFalse(outcome["cancelled"])
        self.assertEqual(outcome["value"], 42)
        self.assertGreaterEqual(outcome["seconds"], 0)

    def test_exception_is_captured_not_raised(self):
        def boom(progress):
            raise RuntimeError("trasig fil")

        outcome = bt.run(boom)
        self.assertFalse(outcome["ok"])
        self.assertIsInstance(outcome["error"], RuntimeError)
        self.assertFalse(outcome["cancelled"])

    def test_cancellation_stops_work_without_result(self):
        token = bt.CancellationToken()
        started = []

        def work(progress):
            started.append(True)
            for index in range(100):
                progress.emit(index, 100, f"steg {index}", force=True)
                if index == 3:
                    token.cancel()
            return "borde-inte-nås"

        outcome = bt.run(work, token=token)
        self.assertTrue(outcome["cancelled"])
        self.assertFalse(outcome["ok"])
        self.assertIsNone(outcome["value"])
        self.assertEqual(len(started), 1)

    def test_cancelled_before_start_does_not_run_work(self):
        token = bt.CancellationToken()
        token.cancel()
        called = []
        outcome = bt.run(lambda progress: called.append(True), token=token)
        self.assertTrue(outcome["cancelled"])
        self.assertEqual(called, [])

    def test_progress_is_throttled_but_forced_updates_pass(self):
        clock = iter([0.0, 0.01, 0.02, 0.3, 0.31])
        seen = []
        reporter = bt.ProgressReporter(lambda *args: seen.append(args), min_interval=0.1, clock=lambda: next(clock))
        reporter.emit(1, 10, "a")
        reporter.emit(2, 10, "b")          # för tätt inpå → hoppas över
        reporter.emit(3, 10, "c")          # för tätt inpå → hoppas över
        reporter.emit(4, 10, "d")          # tillräckligt lång tid
        self.assertEqual(seen, [(1, 10, "a"), (4, 10, "d")])

    def test_identical_progress_payload_is_not_repeated(self):
        seen = []
        clock = iter([0.0, 1.0, 2.0])
        reporter = bt.ProgressReporter(lambda *args: seen.append(args), min_interval=0, clock=lambda: next(clock))
        reporter.emit(1, 1, "klar")
        reporter.emit(1, 1, "klar")
        reporter.emit(1, 1, "klar", force=True)
        self.assertEqual(seen, [(1, 1, "klar"), (1, 1, "klar")])

    def test_token_raises_when_cancelled(self):
        token = bt.CancellationToken()
        self.assertFalse(token.cancelled)
        token.cancel()
        with self.assertRaises(bt.TaskCancelled):
            token.raise_if_cancelled()

    def test_chunked_rejects_bad_size_and_splits(self):
        with self.assertRaises(ValueError):
            list(bt.chunked([1, 2], 0))
        self.assertEqual(list(bt.chunked(range(5), 2)), [[0, 1], [2, 3], [4]])

    def test_cancelled_reading_never_leaves_partial_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "resultat.json"

            def work(progress):
                token = progress.token
                assert token is not None
                token.cancel()
                progress.emit(1, 2, "halvvägs")
                target.write_text("ofullständig")   # ska aldrig ske: avbrott före skrivning
                return "klar"

            outcome = bt.run(work)
            self.assertTrue(outcome["cancelled"])
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
