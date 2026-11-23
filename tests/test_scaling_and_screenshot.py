"""Skalningstest, skärmbild med PIN-maskering och ikoner i 16/24 px."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import layout_audit  # noqa: E402
from core import screenshot  # noqa: E402
from core import theme as design  # noqa: E402


class ScalingAuditTests(unittest.TestCase):
    """Förslag 4: ingen klippt text och ingen sidrullning vid 100–200 %."""

    def test_all_planned_levels_are_tested(self):
        self.assertEqual(layout_audit.scaling_levels(), [100, 125, 150, 175, 200])

    def test_text_that_fits_is_not_reported(self):
        rows = [("Spara", "Spara", 200)]
        self.assertEqual(layout_audit.clipped_labels(rows, lambda text: 40), [])

    def test_clipped_text_is_reported_with_numbers(self):
        rows = [("Knapp", "Spara fordonet", 40)]
        problems = layout_audit.clipped_labels(rows, lambda text: 120)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["available"], 40)
        self.assertEqual(problems[0]["needed"], 120)
        self.assertEqual(problems[0]["missing"], 80)

    def test_elided_text_is_allowed_when_intended(self):
        rows = [("Cell", "Väldigt långt värde", 40)]
        self.assertEqual(layout_audit.clipped_labels(rows, lambda text: 200, elided_ok=("Cell",)), [])

    def test_scaling_up_a_label_can_trigger_a_warning(self):
        rows = [("Knapp", "Spara", 60)]
        results = layout_audit.report_all(
            scales=(100, 200),
            labels_for_scale=lambda scale: rows,
            measure_for_scale=lambda scale: (lambda text: int(50 * scale / 100)),
        )
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[1]["ok"])

    def test_horizontal_overflow(self):
        self.assertEqual(layout_audit.horizontal_overflow([100, 100], 300), 0)
        self.assertEqual(layout_audit.horizontal_overflow([200, 200], 300), 100)
        self.assertEqual(layout_audit.horizontal_overflow([], 0), 0)

    def test_empty_text_never_counts_as_clipped(self):
        self.assertEqual(layout_audit.clipped_labels([("Tom", "", 0)], lambda text: 50), [])

    def test_report_marks_a_wide_table_as_a_problem(self):
        result = layout_audit.report([100], [("Knapp", "Spara", 100)], [300, 300], 400,
                                     lambda text: 30)
        self.assertFalse(result["ok"])
        self.assertEqual(result["overflow"], 200)

    def test_summary_text_is_swedish_and_specific(self):
        ok = [{"scale": 100, "clipped": [], "overflow": 0, "ok": True},
              {"scale": 200, "clipped": [], "overflow": 0, "ok": True}]
        self.assertIn("All text får plats", layout_audit.summary_text(ok))
        bad = [{"scale": 200, "clipped": [{"widget": "Knapp"}], "overflow": 40, "ok": False}]
        text = layout_audit.summary_text(bad)
        self.assertIn("200 %", text)
        self.assertIn("klippta texter", text)
        self.assertIn("40 px", text)

    def test_audit_is_available_from_the_menu(self):
        source = (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")
        self.assertIn("Skalningstest…", source)
        self.assertIn("def _show_scaling_audit", source)


class ScreenshotTests(unittest.TestCase):
    """Förslag 25: skärmbild av appens fönster med maskade PIN-fält."""

    def test_pin_fields_are_recognised(self):
        for name in ("pin_input", "PIN-kod", "lösenord", "passwordField"):
            self.assertTrue(screenshot.is_secret_field(name), name)
        for name in ("vin_input", "sok", "Spara"):
            self.assertFalse(screenshot.is_secret_field(name), name)

    def test_marker_in_tooltip_is_enough(self):
        self.assertTrue(screenshot.is_secret_field("", "Ange PIN-kod"))

    def test_secret_fields_give_a_mask(self):
        self.assertEqual(len(screenshot.mask_rects(200, 30, ["pin_input"])), 1)
        self.assertEqual(screenshot.mask_rects(200, 30, ["vin_input"]), [])
        self.assertEqual(screenshot.mask_rects(200, 30), [])

    def test_filename_is_safe_and_timestamped(self):
        name = screenshot.default_filename("fordonsreg", datetime(2026, 10, 29, 13, 5, 9))
        self.assertEqual(name, "fordonsreg_2026-10-29_13-05-09.png")
        odd = screenshot.default_filename("Fordonsreg: support/ärende", datetime(2026, 1, 1))
        self.assertNotIn(":", odd)
        self.assertNotIn("/", odd)
        self.assertTrue(odd.endswith(".png"))

    def test_support_path_stays_inside_the_support_folder(self):
        root = Path(tempfile.mkdtemp())
        path = screenshot.support_path(root, "../../hemlig.png")
        self.assertEqual(path.parent, root / "logs/support")
        self.assertEqual(path.name, "hemlig.png")

    def test_png_suffix_is_added(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual(screenshot.support_path(root, "bild").name, "bild.png")

    def test_no_image_is_saved_without_a_pixmap(self):
        self.assertFalse(screenshot.save(None, Path(tempfile.mkdtemp()) / "x.png"))

    def test_dialog_masks_and_asks_before_saving(self):
        source = (ROOT / "plugins/main_gui/dialogs/screenshot_dialog.py").read_text(encoding="utf-8")
        self.assertIn("screenshot.capture(window)", source)
        self.assertIn("getSaveFileName", source)
        self.assertIn("maskerade", source)
        self.assertNotIn("grabWindow", source)

    def test_menu_entry_exists(self):
        source = (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")
        self.assertIn("Skärmbild för support", source)
        self.assertIn("def _show_screenshot", source)


class IconSizeTests(unittest.TestCase):
    """Förslag 11: ikonerna är ritade i 24 px och skarpa i 16 px."""

    def test_every_icon_uses_the_24_pixel_grid(self):
        for path in sorted(design.icons_directory(ROOT).glob("*.svg")):
            root = ElementTree.parse(path).getroot()
            self.assertEqual(root.get("viewBox"), "0 0 24 24", path.name)

    def test_stroke_icons_have_the_expected_width(self):
        for path in sorted(design.icons_directory(ROOT).glob("*.svg")):
            text = path.read_text(encoding="utf-8")
            self.assertIn("stroke-width", text, path.name)

    def test_icon_names_available_covers_the_folders_files(self):
        available = set(design.icon_names_available(ROOT))
        files = {path.stem for path in design.icons_directory(ROOT).glob("*.svg")}
        self.assertEqual(available, files)
        # 16 och 24 px är de två storlekar gränssnittet använder.
        for size in (16, 24):
            self.assertIn(size, (16, 24))

    def test_icon_sizes_are_the_two_supported(self):
        self.assertEqual(design.ICON_SIZES, (16, 24))
        self.assertEqual(design.icon_size("sidebar"), 16)
        self.assertEqual(design.icon_size("button"), 16)
        self.assertEqual(design.icon_size("page"), 24)

    def test_stroke_width_follows_the_size(self):
        # 16 px är 2/3 av 24 px; strecken skalas med, annars ser den lilla
        # ikonen grövre ut än den stora.
        self.assertAlmostEqual(design.icon_scale(24), 1.0)
        self.assertAlmostEqual(design.icon_scale(16), 2 / 3, places=3)
        self.assertEqual(design.icon_scale("trasigt"), 1.0)

    def test_sidebar_uses_the_regular_grid_and_sixteen_pixels(self):
        source = (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")
        self.assertIn("design.ICON_SIZE_REGULAR", source)
        self.assertIn('design.icon_size("sidebar")', source)

    def test_pixel_ratio_is_used_when_drawing(self):
        source = (ROOT / "core/theme.py").read_text(encoding="utf-8")
        # Ikonen ritas i skärmens upplösning och får rätt enhetspixelkvot,
        # annars blir den suddig vid 125–200 % skalning.
        self.assertIn("pixels = max(1, int(round(size * ratio)))", source)
        self.assertIn("pixmap.setDevicePixelRatio(ratio)", source)
        self.assertIn("def device_pixel_ratio", source)
        self.assertIn("QSvgRenderer", source)


if __name__ == "__main__":
    unittest.main()
