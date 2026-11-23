"""Design, typsnitt, ikoner, skärmbredd och tema.

Testerna granskar de rena beräkningarna (paletter, kontrast, typsnittsval,
fönsterstorlek, stilark) utan att Qt behövs, samt att huvudfönstret faktiskt
använder designsystemet i stället för egna färgkoder.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import unittest
import xml.etree.ElementTree as ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import theme as design  # noqa: E402


class PaletteTests(unittest.TestCase):
    def test_both_themes_have_the_same_tokens(self):
        self.assertEqual(set(design.PALETTES), {"dark", "light"})
        keys = set(design.PALETTES["dark"])
        self.assertEqual(set(design.PALETTES["light"]), keys)
        for name, colors in design.PALETTES.items():
            for key, value in colors.items():
                self.assertRegex(value, r"^#[0-9a-f]{6}$", f"{name}.{key}")

    def test_text_has_readable_contrast(self):
        for name, colors in design.PALETTES.items():
            for background in ("window", "surface", "surface_alt", "sidebar"):
                ratio = design.contrast_ratio(colors["text"], colors[background])
                self.assertGreaterEqual(ratio, 4.5, f"{name}: text mot {background}")
            muted = design.contrast_ratio(colors["text_muted"], colors["surface"])
            self.assertGreaterEqual(muted, 4.5, f"{name}: dämpad text")
            accent = design.contrast_ratio(colors["accent_text"], colors["accent"])
            self.assertGreaterEqual(accent, 4.5, f"{name}: text på accentfärg")

    def test_palette_cannot_be_modified_from_outside(self):
        colors = design.palette("dark")
        colors["window"] = "#000000"
        self.assertNotEqual(design.PALETTES["dark"]["window"], "#000000")

    def test_unknown_theme_falls_back_to_dark(self):
        self.assertEqual(design.palette("okänd")["window"], design.PALETTES["dark"]["window"])


class ThemeModeTests(unittest.TestCase):
    def test_auto_follows_the_desktop(self):
        self.assertEqual(design.resolve_mode("auto", True), "dark")
        self.assertEqual(design.resolve_mode("auto", False), "light")

    def test_explicit_mode_wins(self):
        self.assertEqual(design.resolve_mode("light", True), "light")
        self.assertEqual(design.resolve_mode("dark", False), "dark")

    def test_broken_value_becomes_auto(self):
        for value in (None, "", "blått", "123"):
            self.assertEqual(design.resolve_mode(value, True), "dark")

    def test_every_mode_has_a_swedish_label_and_icon(self):
        for mode in design.THEME_MODES:
            self.assertIn(mode, design.THEME_LABELS)
            self.assertIsNotNone(design.icon_path(ROOT, f"theme-{mode}"))


class FontTests(unittest.TestCase):
    def test_each_platform_prefers_its_own_ui_font(self):
        self.assertEqual(design.font_family("win32"), "Segoe UI Variable Text")
        self.assertEqual(design.font_family("darwin"), "SF Pro Text")
        self.assertEqual(design.font_family("linux"), "Inter")

    def test_first_installed_candidate_is_chosen(self):
        available = ["DejaVu Sans", "Noto Sans"]
        self.assertEqual(design.font_family("linux", available), "Noto Sans")
        self.assertEqual(design.font_family("win32", ["Arial"]), "Arial")

    def test_unknown_installed_fonts_fall_back_to_a_candidate(self):
        self.assertEqual(design.font_family("linux", ["Ingen"]), "Liberation Sans")
        self.assertEqual(design.font_family("win32", []), "Arial")

    def test_font_chain_lists_fallbacks(self):
        chain = design.font_chain("linux")
        self.assertIn("Noto Sans", chain)
        self.assertTrue(chain.endswith("sans-serif"))
        self.assertIn("monospace", design.mono_chain("win32"))

    def test_font_size_is_clamped(self):
        self.assertEqual(design.clamp_font_size(0), design.MIN_FONT_SIZE)
        self.assertEqual(design.clamp_font_size(99), design.MAX_FONT_SIZE)
        self.assertEqual(design.clamp_font_size("trasigt"), design.DEFAULT_FONT_SIZE)
        self.assertEqual(design.clamp_font_size(None), design.DEFAULT_FONT_SIZE)
        self.assertEqual(design.clamp_font_size("12"), 12)

    def test_high_dpi_does_not_blow_up_the_text(self):
        self.assertEqual(design.scaled_font_size(10, 1.0), 10)
        self.assertEqual(design.scaled_font_size(10, 2.0), 15)
        # Skalningen stannar vid 1,5 gånger, oavsett skärmens täthet.
        self.assertEqual(design.scaled_font_size(10, 4.0), 15)


class ScreenWidthTests(unittest.TestCase):
    def test_small_screen_gets_a_window_that_fits(self):
        width, height = design.window_size(1366, 768)
        self.assertLessEqual(width, int(1366 * 0.9))
        self.assertLessEqual(height, int(768 * 0.9))
        self.assertGreaterEqual(width, design.MIN_WINDOW_WIDTH)
        self.assertGreaterEqual(height, design.MIN_WINDOW_HEIGHT)

    def test_large_screen_does_not_get_an_endless_window(self):
        self.assertEqual(design.window_size(3840, 2160), (design.PREFERRED_WIDTH, design.PREFERRED_HEIGHT))

    def test_tiny_screen_still_gets_a_usable_window(self):
        width, height = design.window_size(800, 600)
        self.assertLessEqual(width, 720)
        self.assertLessEqual(height, 540)

    def test_broken_screen_size_gives_the_preferred_size(self):
        self.assertEqual(design.window_size(0, 0), (design.PREFERRED_WIDTH, design.PREFERRED_HEIGHT))
        self.assertEqual(design.window_size(None, None), (design.PREFERRED_WIDTH, design.PREFERRED_HEIGHT))

    def test_sidebar_shrinks_on_narrow_screens(self):
        self.assertEqual(design.sidebar_width(1000), 180)
        self.assertEqual(design.sidebar_width(1280), 210)
        self.assertEqual(design.sidebar_width(1920), 240)
        self.assertLess(design.sidebar_width(1000), design.sidebar_width(1920))

    def test_content_margins_grow_with_the_window(self):
        self.assertLess(design.content_margins(1000)[0], design.content_margins(1920)[0])


class StylesheetTests(unittest.TestCase):
    def setUp(self):
        self.dark = design.stylesheet("dark", font_size=10)
        self.light = design.stylesheet("light", font_size=10)

    def test_both_themes_are_rendered_with_their_own_colors(self):
        self.assertIn(design.PALETTES["dark"]["window"], self.dark)
        self.assertIn(design.PALETTES["light"]["window"], self.light)
        self.assertNotEqual(self.dark, self.light)

    def test_widgets_used_by_the_app_are_styled(self):
        for selector in ("QPushButton", "QLineEdit", "QComboBox", "QTableWidget",
                         "QHeaderView::section", "QTabBar::tab", "QMenuBar", "QMenu",
                         "QScrollBar::handle:vertical", "QToolTip", "QProgressBar",
                         "QPushButton#NavButton", "QLabel#PageTitle", "QPushButton#PrimaryButton"):
            self.assertIn(selector, self.dark, selector)

    def test_focus_is_visible_for_keyboard_users(self):
        self.assertIn("QPushButton:focus", self.dark)
        self.assertIn(":focus {", self.dark)
        self.assertIn(design.PALETTES["dark"]["accent"], self.dark)

    def test_font_and_size_are_applied(self):
        custom = design.stylesheet("dark", "Noto Sans", 13)
        self.assertIn("font-family: Noto Sans", custom)
        self.assertIn("font-size: 13pt", custom)
        big = design.stylesheet("dark", font_size=18)
        self.assertIn("font-size: 18pt", big)

    def test_broken_font_size_does_not_break_the_theme(self):
        text = design.stylesheet("dark", font_size="stor")
        self.assertIn("font-size", text)
        self.assertIn(design.DEFAULT_FONT_SIZE.__str__() + "pt", text)

    def test_no_qt_import_is_needed_for_the_stylesheet(self):
        source = (ROOT / 'core' / 'theme.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names]
                self.assertFalse([n for n in names if n.startswith('PySide6')],
                                 'Qt får bara importeras i funktionerna')


class IconTests(unittest.TestCase):
    def test_all_icons_exist_and_are_valid_svg(self):
        available = design.icon_names_available(ROOT)
        self.assertEqual(sorted(available), sorted(design.ICON_NAMES))
        for name in available:
            path = design.icon_path(ROOT, name)
            root = ElementTree.parse(path).getroot()
            self.assertTrue(root.tag.endswith('svg'), name)
            self.assertEqual(root.get('viewBox'), '0 0 24 24', name)

    def test_unknown_icon_is_not_invented(self):
        self.assertIsNone(design.icon_path(ROOT, 'finns-inte'))
        self.assertIsNone(design.icon_path(ROOT, '../ikon'))

    def test_pages_get_a_matching_icon(self):
        self.assertEqual(design.page_icon('🚗 Fordonsdata'), 'vehicle')
        self.assertEqual(design.page_icon('📋 TS Schema'), 'schema')
        self.assertEqual(design.page_icon('🏢 Återförsäljare'), 'dealers')
        self.assertEqual(design.page_icon('🎨 Färger'), 'colors')
        self.assertEqual(design.page_icon('📥 Dispatch Import'), 'dispatch')
        self.assertEqual(design.page_icon('📊 Rapporter/Historik'), 'reports')
        self.assertEqual(design.page_icon('Något nytt'), 'folder')

    def test_emoji_prefix_can_be_replaced_by_an_icon(self):
        self.assertEqual(design.strip_emoji_prefix('🚗 Fordonsdata'), 'Fordonsdata')
        self.assertEqual(design.strip_emoji_prefix('📋 TS Schema'), 'TS Schema')
        self.assertEqual(design.strip_emoji_prefix('Generera TS-fil'), 'Generera TS-fil')
        self.assertEqual(design.strip_emoji_prefix(''), '')
        self.assertEqual(design.strip_emoji_prefix('⚙️ Generera'), 'Generera')


class UpdaterIconTests(unittest.TestCase):
    def test_theme_icons_are_allowed_in_releases(self):
        from plugins.auto_update import updater

        self.assertTrue(updater._is_theme_icon('assets/icons/vehicle.svg'))
        for forbidden in ('assets/icons/ikon.png', 'assets/icons/../../secret.py',
                          'assets/icons/sub/vehicle.svg', 'core/theme.py'):
            self.assertFalse(updater._is_theme_icon(forbidden), forbidden)
        self.assertLessEqual(updater.MAX_ICON_FILE, updater.MAX_FILE)
        # Sökvägen måste fortfarande godkännas av den gemensamma kontrollen.
        self.assertEqual(updater._validate_relative('assets/icons/search.svg'),
                         ('assets', 'icons', 'search.svg'))


class SharpnessTests(unittest.TestCase):
    def test_high_dpi_is_enabled_before_qt_is_created(self):
        source = (ROOT / 'plugins' / 'main_gui' / 'plugin.py').read_text(encoding='utf-8')
        self.assertIn('design.enable_high_dpi()', source)
        self.assertLess(source.index('design.enable_high_dpi()'),
                        source.index('QApplication(sys.argv)'))

    def test_high_dpi_helper_prefers_pass_through_rounding(self):
        source = (ROOT / 'core' / 'theme.py').read_text(encoding='utf-8')
        self.assertIn('setHighDpiScaleFactorRoundingPolicy', source)
        self.assertIn('PassThrough', source)

    def test_font_uses_full_hinting(self):
        source = (ROOT / 'core' / 'theme.py').read_text(encoding='utf-8')
        self.assertIn('PreferFullHinting', source)
        self.assertIn('PreferAntialias', source)

    def test_icons_are_rendered_in_screen_resolution(self):
        source = (ROOT / 'core' / 'theme.py').read_text(encoding='utf-8')
        icon_body = source.split('def icon(', 1)[1].split('def enable_high_dpi', 1)[0]
        self.assertIn('device_pixel_ratio', icon_body)
        self.assertIn('setDevicePixelRatio', icon_body)
        # Ingen kantutjämning på QR-koden – modulerna ska vara knivskarpa.
        qr_body = source.split('def qr_image(', 1)[1].split('def apply_font', 1)[0]
        self.assertIn('Antialiasing, False', qr_body)

    def test_donation_qr_uses_the_sharp_renderer(self):
        dialog = (ROOT / 'plugins' / 'main_gui' / 'dialogs' / 'swish_qr_dialog.py').read_text(encoding='utf-8')
        self.assertIn('design.qr_image(', dialog)
        self.assertNotIn('QImage(', dialog)

    def test_device_pixel_ratio_is_never_below_one(self):
        ratio = design.device_pixel_ratio(None)
        self.assertGreaterEqual(ratio, 1.0)
        self.assertLessEqual(ratio, 4.0)

    def test_sidebar_follows_the_window_width(self):
        source = (ROOT / 'plugins' / 'main_gui' / 'plugin.py').read_text(encoding='utf-8')
        self.assertIn('def resizeEvent', source)
        resize = source.split('def resizeEvent', 1)[1].split('def showEvent', 1)[0]
        self.assertIn('_fit_sidebar_to_window', resize)
        fit = source.split('def _fit_sidebar_to_window', 1)[1].split('def showEvent', 1)[0]
        self.assertIn('design.sidebar_width(self.width())', fit)
        # Bredden sätts nu på delaren (förslag 2), med gränser på sidomenyn –
        # en fast bredd skulle göra kanten odragbar.
        self.assertIn('main_splitter', fit)
        self.assertIn('setMinimumWidth', fit)
        self.assertIn('setMaximumWidth', fit)
        self.assertNotIn('setFixedWidth', fit)


class MainWindowTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'plugins' / 'main_gui' / 'plugin.py').read_text(encoding='utf-8')

    def test_window_uses_the_design_system(self):
        self.assertIn('design.window_size(', self.source)
        self.assertIn('design.sidebar_width(', self.source)
        self.assertIn('design.apply_font(', self.source)
        self.assertIn('design.stylesheet(', self.source)
        self.assertIn('design.strip_emoji_prefix(', self.source)
        self.assertIn('design.icon(', self.source)

    def test_theme_menu_exists_with_all_modes(self):
        self.assertIn('def _create_view_menu', self.source)
        for mode in design.THEME_MODES:
            self.assertIn(f'design.THEME_LABELS[mode]', self.source)
        self.assertIn('def _set_theme_mode', self.source)
        self.assertIn('set_config_value_safe(self.app, "ui.theme", mode)', self.source)
        self.assertIn('def _set_font_size', self.source)
        self.assertIn('def _fit_window_to_screen', self.source)

    def test_no_hardcoded_colors_in_the_sidebar(self):
        sidebar = self.source.split('def _create_sidebar', 1)[1].split('def _add_stats_labels', 1)[0]
        self.assertNotIn('#14161a', sidebar)
        self.assertNotIn('#20c8df', sidebar)
        stats = self.source.split('def _add_stats_labels', 1)[1].split('def _init_menu', 1)[0]
        self.assertNotIn('#888', stats)
        self.assertNotIn('#aaa', stats)

    def test_old_styles_are_generated_not_duplicated(self):
        match = re.search(r'MAIN_STYLESHEET: Final\[str\] = (.+)', self.source)
        self.assertIsNotNone(match)
        self.assertIn('design.stylesheet(', match.group(1))
        self.assertNotIn('background: #191b1f', self.source)


if __name__ == '__main__':
    unittest.main()
