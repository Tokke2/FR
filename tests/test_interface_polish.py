"""Kompakt läge, justerbar sidomeny, skärmprofiler, skalning och sidhuvud.

Testerna granskar de rena beräkningarna och att huvudfönstret faktiskt kopplar
in dem – aldrig påhittade värden, utan samma funktioner som appen använder.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import layout_memory  # noqa: E402
from core import theme as design  # noqa: E402


def _main_window_source() -> str:
    return (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class DensityTests(unittest.TestCase):
    """Förslag 1: kompakt läge under 1100 px."""

    def test_auto_becomes_compact_on_small_windows(self):
        self.assertEqual(design.resolve_density("auto", 1000, 900), "compact")
        self.assertEqual(design.resolve_density("auto", 1600, 900), "comfortable")

    def test_low_screen_becomes_compact_too(self):
        self.assertEqual(design.resolve_density("auto", 1600, 700), "compact")

    def test_user_choice_always_wins(self):
        self.assertEqual(design.resolve_density("comfortable", 900, 600), "comfortable")
        self.assertEqual(design.resolve_density("compact", 2560, 1440), "compact")

    def test_broken_value_falls_back_to_auto(self):
        for value in (None, "", "pytteliten"):
            self.assertEqual(design.resolve_density(value, 1000, 900), "compact")

    def test_compact_mode_has_lower_rows_and_less_padding(self):
        self.assertLess(design.row_height("compact"), design.row_height("comfortable"))
        self.assertLess(design.spacing("compact"), design.spacing("comfortable"))
        self.assertEqual(design.row_height("okänd"), design.row_height("comfortable"))

    def test_compact_stylesheet_is_shorter(self):
        comfortable = design.stylesheet("dark", density="comfortable")
        compact = design.stylesheet("dark", density="compact")
        self.assertNotEqual(comfortable, compact)
        self.assertIn("min-height", compact)

    def test_every_density_has_a_swedish_label(self):
        for mode in design.DENSITY_MODES:
            self.assertIn(mode, design.DENSITY_LABELS)

    def test_icon_only_sidebar_on_narrow_windows(self):
        self.assertTrue(design.icon_only_sidebar(1000))
        self.assertFalse(design.icon_only_sidebar(1600))


class SidebarWidthTests(unittest.TestCase):
    """Förslag 2: justerbar sidomeny med ihågkommen bredd."""

    def test_saved_width_wins_over_the_default(self):
        self.assertEqual(design.sidebar_initial_width(300, 1600), 300)

    def test_saved_width_is_clamped_to_the_window(self):
        self.assertEqual(design.sidebar_initial_width(9999, 1600),
                         design.sidebar_max_width(1600))
        self.assertEqual(design.sidebar_initial_width(10, 1600), design.SIDEBAR_MIN_WIDTH)

    def test_no_saved_width_gives_the_screen_default(self):
        self.assertEqual(design.sidebar_initial_width(0, 1600), design.sidebar_width(1600))
        self.assertEqual(design.sidebar_initial_width("trasigt", 1600), design.sidebar_width(1600))

    def test_compact_start_is_icon_width(self):
        self.assertEqual(design.sidebar_initial_width(None, 900, "compact"),
                         design.design_icon_width())

    def test_sidebar_never_takes_more_than_a_third(self):
        for width in (900, 1200, 1920, 3840):
            self.assertLess(design.sidebar_max_width(width), width * 0.5)

    def test_window_uses_a_splitter_and_remembers_the_width(self):
        source = _main_window_source()
        self.assertIn("QSplitter", source)
        self.assertIn("splitterMoved.connect(self._on_sidebar_resized)", source)
        self.assertIn("ui.sidebar_width", source)
        self.assertIn("def _on_sidebar_resized", source)
        self.assertIn("def _save_sidebar_width", source)


class ScreenProfileTests(unittest.TestCase):
    """Förslag 3: fönstret kommer tillbaka där det var, per skärm."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_nothing_is_remembered_at_first_start(self):
        self.assertIsNone(layout_memory.screen_geometry(self.root, "Skärm 1", 1920, 1080))

    def test_geometry_round_trip(self):
        self.assertTrue(layout_memory.save_screen_geometry(
            self.root, "Skärm 1", width=1400, height=900, x=20, y=30, used="2026-10-29"))
        saved = layout_memory.screen_geometry(self.root, "Skärm 1", 1920, 1080)
        self.assertEqual(saved, {"width": 1400, "height": 900, "x": 20, "y": 30})

    def test_geometry_that_no_longer_fits_is_ignored(self):
        layout_memory.save_screen_geometry(self.root, "Skärm 1",
                                           width=1400, height=900, x=0, y=0)
        self.assertIsNone(layout_memory.screen_geometry(self.root, "Skärm 1", 1024, 700))

    def test_window_mostly_off_screen_is_ignored(self):
        layout_memory.save_screen_geometry(self.root, "Skärm 1",
                                           width=800, height=600, x=5000, y=0)
        self.assertIsNone(layout_memory.screen_geometry(self.root, "Skärm 1", 1920, 1080))

    def test_tiny_window_is_ignored(self):
        layout_memory.save_screen_geometry(self.root, "Skärm 1",
                                           width=200, height=100, x=0, y=0)
        self.assertIsNone(layout_memory.screen_geometry(self.root, "Skärm 1", 1920, 1080))

    def test_broken_file_does_not_crash(self):
        folder = self.root / "data"
        folder.mkdir()
        (folder / layout_memory.SCREEN_PROFILES_FILE).write_text("{trasigt", encoding="utf-8")
        self.assertIsNone(layout_memory.screen_geometry(self.root, "Skärm 1", 1920, 1080))
        self.assertTrue(layout_memory.save_screen_geometry(
            self.root, "Skärm 1", width=1200, height=800, x=5, y=5))

    def test_screen_key_separates_resolutions(self):
        self.assertNotEqual(layout_memory.screen_key("Skärm 1", 1920, 1080),
                            layout_memory.screen_key("Skärm 1", 1280, 720))
        self.assertIn("1920x1080", layout_memory.screen_key("Skärm 1", 1920, 1080))

    def test_window_saves_and_restores_geometry(self):
        source = _main_window_source()
        self.assertIn("layout_memory.screen_geometry", source)
        self.assertIn("layout_memory.save_screen_geometry", source)
        self.assertIn("def moveEvent", source)
        self.assertIn("def _save_geometry", source)


class ScalingTests(unittest.TestCase):
    """Förslag 13: skalning av hela gränssnittet utan omstart."""

    def test_scale_is_clamped(self):
        self.assertEqual(design.clamp_scale(0.1), design.SCALE_MIN)
        self.assertEqual(design.clamp_scale(9), design.SCALE_MAX)
        self.assertEqual(design.clamp_scale("trasigt"), 1.0)
        self.assertEqual(design.clamp_scale(1.25), 1.25)

    def test_steps_cover_the_whole_range(self):
        steps = design.scale_steps()
        self.assertEqual(steps[0], design.SCALE_MIN)
        self.assertEqual(steps[-1], design.SCALE_MAX)
        self.assertIn(1.0, steps)
        self.assertTrue(all(0.9 <= step <= 1.5 for step in steps))

    def test_scaled_measure_never_becomes_zero(self):
        self.assertGreaterEqual(design.scaled(0, 0.9), 1)
        self.assertEqual(design.scaled(32, 1.5), 48)

    def test_stylesheet_follows_the_scale(self):
        small = design.stylesheet("dark", scale=0.9)
        large = design.stylesheet("dark", scale=1.5)
        self.assertNotEqual(small, large)
        self.assertIn("min-height", large)

    def test_scale_has_menu_and_is_saved(self):
        source = _main_window_source()
        self.assertIn("Skala gränssnittet", source)
        self.assertIn("ui.scale", source)
        self.assertIn("def _set_ui_scale", source)

    def test_scale_is_applied_without_restart(self):
        source = _main_window_source()
        tree = ast.parse(source)
        window = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
        names = {node.name for node in window.body if isinstance(node, ast.FunctionDef)}
        self.assertIn("_set_ui_scale", names)
        method = next(node for node in window.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_set_ui_scale")
        calls = {getattr(node.func, "attr", "") for node in ast.walk(method)
                 if isinstance(node, ast.Call)}
        self.assertIn("_appearance_changed", calls)


class PageHeaderTests(unittest.TestCase):
    """Förslag 5: ett gemensamt sidhuvud på alla sidor."""

    def test_header_module_is_qt_free_at_import(self):
        source = _read("plugins/gui_helpers/page_header.py")
        tree = ast.parse(source)
        top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = {alias.name for node in top_level if isinstance(node, ast.ImportFrom)
                 for alias in node.names}
        self.assertNotIn("QtWidgets", names)
        self.assertNotIn("PySide6", names)

    def test_pages_use_the_shared_header(self):
        # Exporterade sidor har bytts ut. ts_excel_importer importerar Qt på
        # modulnivå och kan därför inte läsas i testsviten utan PySide6, men
        # källkoden granskas ändå här.
        for path in (
            "plugins/main_gui/vehicle_registry_page.py",
            "plugins/data_viewer/plugin.py",
            "plugins/reports/plugin.py",
            "plugins/dealers_manager/plugin.py",
            "plugins/dispatch_viewer/plugin.py",
        ):
            source = _read(path)
            self.assertIn("PageHeader.build(", source, path)
            self.assertIn("page_header", source, path)
        importer = _read("plugins/ts_excel_importer/widget.py")
        self.assertIn("PageHeader.build(", importer)
        self.assertIn("page_header", importer)

    def test_old_hardcoded_titles_are_gone(self):
        for path in ("plugins/data_viewer/plugin.py", "plugins/reports/plugin.py"):
            source = _read(path)
            self.assertNotIn('setStyleSheet("font-size: 22px', source, path)
            self.assertNotIn('setStyleSheet(\n            "font-size: 22px', source, path)

    def test_header_builds_a_fixed_height_row(self):
        source = _read("plugins/gui_helpers/page_header.py")
        self.assertIn("TITLE_HEIGHT", source)
        self.assertIn("PageTitle", source)


class ContrastTests(unittest.TestCase):
    """Förslag 22: kontrastverktyg i appen."""

    def test_every_pair_passes_its_requirement(self):
        problems = design.contrast_problems()
        self.assertEqual(problems, [], problems)

    def test_report_covers_text_and_borders_in_both_themes(self):
        rows = design.contrast_report("dark") + design.contrast_report("light")
        self.assertEqual(len(rows), 2 * len(design._CONTRAST_PAIRS))
        labels = {row["label"] for row in rows}
        self.assertIn("Ram runt fält och tabell", labels)
        self.assertIn("Brödtext på bakgrund", labels)

    def test_text_requirement_is_stricter_than_borders(self):
        for _fg, _bg, _label, required in design._CONTRAST_PAIRS:
            self.assertIn(required, (3.0, 4.5))
        requirements = {row["required"] for row in design.contrast_report("light")}
        self.assertEqual(requirements, {3.0, 4.5})

    def test_tool_is_in_the_view_menu(self):
        source = _main_window_source()
        self.assertIn("Kontrastkontroll…", source)
        self.assertIn("def _show_contrast_check", source)


class AccessibilityTests(unittest.TestCase):
    """Förslag 15: skärmläsare får alltid en beskrivning."""

    def test_accessible_text_skips_empty_parts(self):
        self.assertEqual(design.accessible_text("VIN", "", "Färg"), "VIN, Färg")

    def test_icon_button_never_has_an_empty_label(self):
        self.assertEqual(design.label_for_icon_button(""), "Knapp")
        self.assertEqual(design.label_for_icon_button("Fordonsdata"), "Fordonsdata")

    def test_navigation_sets_accessible_names(self):
        source = _main_window_source()
        self.assertIn("design.set_accessible(btn", source)
        self.assertIn("def _apply_nav_icon_mode", source)


if __name__ == "__main__":
    unittest.main()
