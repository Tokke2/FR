"""Prestanda, minne och energiförbrukning.

Testerna granskar de rena beräkningarna (intervall, minnesbedömning, starttider)
och att huvudfönstret verkligen går ner i sparläge när fönstret är dolt – det är
där energin annars går åt utan att någon ser resultatet.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import memory_guard  # noqa: E402
from core import runtime_policy  # noqa: E402
from core import theme as design  # noqa: E402


def _source() -> str:
    return (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")


class IntervalTests(unittest.TestCase):
    def test_visible_window_keeps_the_normal_interval(self):
        self.assertEqual(runtime_policy.effective_interval(30_000), 30_000)

    def test_hidden_window_works_far_less_often(self):
        hidden = runtime_policy.effective_interval(30_000, hidden=True)
        self.assertGreaterEqual(hidden, 30_000 * 4)

    def test_idle_window_works_less_often_but_not_as_much(self):
        idle = runtime_policy.effective_interval(30_000, idle=True)
        self.assertGreater(idle, 30_000)
        self.assertLess(idle, runtime_policy.effective_interval(30_000, hidden=True))

    def test_interval_is_capped(self):
        self.assertLessEqual(runtime_policy.effective_interval(3_600_000, hidden=True),
                             runtime_policy.MAX_BACKGROUND_INTERVAL_MS)

    def test_broken_values_do_not_crash(self):
        self.assertEqual(runtime_policy.effective_interval("trasigt"),
                         runtime_policy.MIN_INTERVAL_MS)
        self.assertEqual(runtime_policy.effective_interval(-5),
                         runtime_policy.MIN_INTERVAL_MS)

    def test_skipped_runs_when_too_soon(self):
        self.assertTrue(runtime_policy.should_run(30_000, hidden=True,
                                                  last_run=100.0, now=101.0) is False)
        self.assertTrue(runtime_policy.should_run(30_000, hidden=True,
                                                  last_run=100.0, now=100.0 + 200.0))
        self.assertTrue(runtime_policy.should_run(30_000))

    def test_no_timers_are_left_working_in_the_background(self):
        self.assertEqual(runtime_policy.visible_timer_count([1000, 2000], hidden=True), 0)
        self.assertEqual(runtime_policy.visible_timer_count([1000, 2000]), 2)

    def test_idle_thresholds(self):
        self.assertLess(runtime_policy.idle_after_seconds(True),
                        runtime_policy.idle_after_seconds(False))


class MemoryTests(unittest.TestCase):
    def test_bytes_to_megabytes(self):
        self.assertEqual(runtime_policy.to_mb(0), 0.0)
        self.assertEqual(runtime_policy.to_mb("trasigt"), 0.0)
        self.assertEqual(runtime_policy.to_mb(-1), 0.0)
        self.assertAlmostEqual(runtime_policy.to_mb(400 * 1024 * 1024), 400.0, places=1)

    def test_levels(self):
        self.assertEqual(runtime_policy.memory_status(100 * 1024 * 1024)["level"], "ok")
        warning = 420 * 1024 * 1024
        self.assertEqual(runtime_policy.memory_status(warning)["level"], "warning")
        critical = 700 * 1024 * 1024
        self.assertEqual(runtime_policy.memory_status(critical)["level"], "critical")

    def test_growth_triggers_a_warning(self):
        status = runtime_policy.memory_status(250 * 1024 * 1024,
                                              previous_rss_bytes=100 * 1024 * 1024)
        self.assertEqual(status["level"], "warning")
        self.assertGreater(status["growth_mb"], 0)

    def test_advice_is_swedish_and_present_for_every_level(self):
        for level in ("ok", "warning", "critical", "okänd"):
            text = runtime_policy.memory_advice(level)
            self.assertTrue(text)
            self.assertTrue(text[0].isupper())

    def test_summary_uses_measured_numbers_only(self):
        status = runtime_policy.memory_status(200 * 1024 * 1024)
        text = runtime_policy.memory_summary(status, objects=1234)
        self.assertIn("200.0 MB", text)
        self.assertIn("1234 Python-objekt", text)

    def test_release_reports_what_it_did(self):
        result = memory_guard.release()
        self.assertIn("summary", result)
        self.assertIn("steps", result)
        self.assertGreaterEqual(result["freed_mb"], 0)
        self.assertIsInstance(result["icons_freed"], int)

    def test_real_measurement_works_without_qt(self):
        status = memory_guard.measure()
        self.assertIn("mb", status)
        self.assertGreaterEqual(status["mb"], 0)
        self.assertIn(status["level"], ("ok", "warning", "critical"))

    def test_reset_of_baseline(self):
        memory_guard.reset_baseline()
        self.assertIsNone(memory_guard._last_rss)

    def test_optimization_steps_are_specific(self):
        steps = runtime_policy.optimization_steps({"closed_tabs": 2})
        self.assertTrue(any("ikon" in step for step in steps))
        self.assertTrue(any("skräpsamlare" in step for step in steps))
        self.assertTrue(any("2 årsflik" in step for step in steps))


class StartTests(unittest.TestCase):
    def test_slow_steps_are_detected(self):
        steps = [("Läs konfiguration", 12), ("Ladda sidor", 1200)]
        self.assertEqual(runtime_policy.slow_steps(steps), [("Ladda sidor", 1200.0)])

    def test_broken_durations_are_ignored(self):
        self.assertEqual(runtime_policy.slow_steps([("x", "trasigt")]), [])

    def test_start_is_slow_when_total_is_slow(self):
        self.assertTrue(runtime_policy.start_is_slow([], total_ms=5000))
        self.assertFalse(runtime_policy.start_is_slow([("a", 10)], total_ms=100))


class WiringTests(unittest.TestCase):
    """Att koden faktiskt använder sparläget."""

    def setUp(self):
        self.source = _source()

    def test_menu_has_memory_entry(self):
        self.assertIn("Minne och prestanda", self.source)
        self.assertIn("def _show_memory_status", self.source)
        self.assertIn("MemoryDialog", self.source)

    def test_timers_follow_the_window_state(self):
        self.assertIn("def _apply_timer_policy", self.source)
        self.assertIn("def _timer_interval", self.source)
        self.assertIn("def _background_allowed", self.source)
        self.assertIn("runtime_policy.effective_interval", self.source)

    def test_hiding_the_window_lowers_the_work(self):
        tree = ast.parse(self.source)
        window = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
        names = {node.name for node in window.body if isinstance(node, ast.FunctionDef)}
        for expected in ("hideEvent", "showEvent", "changeEvent", "event"):
            self.assertIn(expected, names)
        hide = next(node for node in window.body
                    if isinstance(node, ast.FunctionDef) and node.name == "hideEvent")
        # Anropet sker via QTimer.singleShot(0, self._apply_timer_policy).
        referenced = {node.attr for node in ast.walk(hide)
                      if isinstance(node, ast.Attribute)}
        self.assertIn("_apply_timer_policy", referenced)

    def test_background_tasks_are_guarded(self):
        self.assertIn('_background_allowed(\n                "watched"', self.source)

    def test_statistics_are_rescheduled_with_the_policy(self):
        self.assertIn("self._next_interval(STATS_UPDATE_INTERVAL_MS)", self.source)

    def test_pages_are_built_after_the_window_is_shown(self):
        self.assertIn("def _init_remaining_pages", self.source)
        self.assertIn("def _attach_pages_to_stack", self.source)
        # Fordonsdata byggs direkt, resten när fönstret visas.
        init = self.source.split("def _init_pages", 1)[1].split("def _init_remaining_pages")[0]
        self.assertIn("_init_vehicle_data_page", init)
        self.assertNotIn("_init_other_pages()", init)


class IconCacheTests(unittest.TestCase):
    def test_cache_is_empty_without_qt(self):
        design.clear_icon_cache()
        self.assertEqual(design.icon_cache_size(), 0)

    def test_icon_without_qt_returns_none_and_is_not_cached(self):
        design.clear_icon_cache()
        self.assertIsNone(design.icon(ROOT, "vehicle"))
        self.assertEqual(design.icon_cache_size(), 0)

    def test_unknown_icon_is_still_none(self):
        self.assertIsNone(design.icon(ROOT, "finns-inte"))

    def test_cache_has_a_limit(self):
        self.assertGreater(design.ICON_CACHE_LIMIT, 20)


if __name__ == "__main__":
    unittest.main()
