"""Tabellhjälp, snabbfilter och summefält för fordonslistan."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import layout_memory  # noqa: E402
from core import theme as design  # noqa: E402
from core import table_view  # noqa: E402
from core import vehicle_filters as filters  # noqa: E402


class TableProfileTests(unittest.TestCase):
    """Förslag 7: kolumnprofil per tabell och år."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.columns = ["VIN", "Modell", "Färg", "Återförsäljare"]

    def test_unknown_profile_is_empty(self):
        self.assertEqual(layout_memory.table_profile(self.root, "fordon", 2026), {})

    def test_profile_is_stored_per_year(self):
        layout_memory.save_table_profile(self.root, "fordon", {"order": ["Modell", "VIN"]},
                                         year=2026, known_columns=self.columns)
        self.assertEqual(layout_memory.table_profile(self.root, "fordon", 2026)["order"][:2],
                         ["Modell", "VIN"])
        self.assertEqual(layout_memory.table_profile(self.root, "fordon", 2025), {})

    def test_new_column_can_never_be_hidden_by_an_old_profile(self):
        saved = layout_memory.save_table_profile(
            self.root, "fordon",
            {"order": ["Modell", "Okänd"], "hidden": ["Okänd", "Färg"]},
            year=2026, known_columns=self.columns)
        self.assertTrue(saved)
        profile = layout_memory.table_profile(self.root, "fordon", 2026)
        self.assertNotIn("Okänd", profile["order"])
        self.assertIn("VIN", profile["order"])
        self.assertEqual(profile["hidden"], ["Färg"])

    def test_order_keeps_every_known_column_once(self):
        profile = layout_memory.normalize_profile(
            {"order": ["Färg", "Färg", "VIN"]}, self.columns)
        self.assertEqual(sorted(profile["order"]), sorted(self.columns))
        self.assertEqual(len(profile["order"]), len(self.columns))
        self.assertEqual(profile["order"][0], "Färg")

    def test_impossible_widths_are_dropped(self):
        profile = layout_memory.normalize_profile(
            {"widths": {"VIN": 10, "Modell": 5000, "Färg": "bred"}}, self.columns)
        self.assertEqual(profile["widths"], {})

    def test_reset_forgets_the_profile(self):
        layout_memory.save_table_profile(self.root, "fordon", {"order": self.columns}, year=2026)
        self.assertTrue(layout_memory.clear_table_profile(self.root, "fordon", 2026))
        self.assertEqual(layout_memory.table_profile(self.root, "fordon", 2026), {})

    def test_unknown_density_is_not_saved(self):
        profile = layout_memory.normalize_profile({"density": "pytteliten"}, self.columns)
        self.assertNotIn("density", profile)
        profile = layout_memory.normalize_profile({"density": "compact"}, self.columns)
        self.assertEqual(profile["density"], "compact")

    def test_profile_file_is_named_as_planned(self):
        self.assertEqual(layout_memory.TABLE_PROFILES_FILE, "table_profiles.json")


class FreezeAndRowHeightTests(unittest.TestCase):
    """Förslag 6 och 8: fryst VIN-kolumn, radhöjd och textbrytning."""

    class FakeHeader:
        def __init__(self):
            self.highlight = None
            self.stretch = None

        def setHighlightSections(self, value):
            self.highlight = value

        def setStretchLastSection(self, value):
            self.stretch = value

    class FakeVertical:
        ResizeMode = type("ResizeMode", (), {"Fixed": 2})

        def __init__(self):
            self.size = None
            self.minimum = None
            self.mode = None

        def setDefaultSectionSize(self, value):
            self.size = value

        def setMinimumSectionSize(self, value):
            self.minimum = value

        def setSectionResizeMode(self, value):
            self.mode = value

    class FakeView:
        SelectionBehavior = type("SelectionBehavior", (), {"SelectRows": 1})

        def __init__(self):
            self._vertical = FreezeAndRowHeightTests.FakeVertical()
            self._header = FreezeAndRowHeightTests.FakeHeader()
            self.frozen = None
            self.wrap = None
            self.alternating = None
            self.behavior = None

        def verticalHeader(self):
            return self._vertical

        def horizontalHeader(self):
            return self._header

        def setFrozenColumnCount(self, value):
            self.frozen = value

        def setWordWrap(self, value):
            self.wrap = value

        def setAlternatingRowColors(self, value):
            self.alternating = value

        def setSelectionBehavior(self, value):
            self.behavior = value

    def test_freeze_first_column(self):
        view = self.FakeView()
        self.assertTrue(table_view.freeze_first_column(view))
        self.assertEqual(view.frozen, 1)

    def test_freeze_is_optional(self):
        view = self.FakeView()
        table_view.configure(view, freeze_first=False)
        self.assertIsNone(view.frozen)

    def test_compact_mode_lowers_the_row_height(self):
        compact = self.FakeView()
        comfortable = self.FakeView()
        table_view.apply_density(compact, "compact")
        table_view.apply_density(comfortable, "comfortable")
        self.assertLess(compact.verticalHeader().size, comfortable.verticalHeader().size)
        self.assertFalse(compact.wrap)
        self.assertTrue(comfortable.wrap)

    def test_configure_sets_the_common_basics(self):
        view = self.FakeView()
        table_view.configure(view, freeze_first=True)
        self.assertTrue(view.alternating)
        self.assertFalse(view.horizontalHeader().highlight)
        self.assertFalse(view.horizontalHeader().stretch)

    def test_missing_freeze_support_does_not_crash(self):
        class Old:
            pass

        self.assertFalse(table_view.freeze_first_column(Old()))


class QuickFilterTests(unittest.TestCase):
    """Förslag 9: snabbfilterchip."""

    def setUp(self):
        self.rows = [
            {"vin_kod": "YAJ4M123", "godkannandenummer": "e5", "farg_kod": "Vit",
             "aterforsaljare": "AB Hjul"},
            {"vin_kod": "YAJ7N654", "farg_kod": "", "aterforsaljare": ""},
            {"vin_kod": "", "godkannandenummer": "", "farg_kod": ""},
        ]

    def test_the_four_planned_chips_exist(self):
        labels = [item.label for item in filters.QUICK_FILTERS]
        self.assertIn("Ofullständiga", labels)
        self.assertIn("Saknar färg", labels)
        self.assertIn("Saknar approval", labels)
        self.assertIn("Saknar återförsäljare", labels)

    def test_filters_use_the_fields_that_exist(self):
        self.assertEqual(len(filters.apply_filters(self.rows, ["no_color"])), 2)
        self.assertEqual(len(filters.apply_filters(self.rows, ["no_approval"])), 2)
        self.assertEqual(len(filters.apply_filters(self.rows, ["complete"])), 1)

    def test_several_chips_are_combined_with_and(self):
        both = filters.apply_filters(self.rows, ["no_color", "no_dealer"])
        self.assertEqual(len(both), 2)
        self.assertTrue(all(filters.missing_color(row) for row in both))
        only_color = filters.apply_filters(self.rows, ["no_color"])
        self.assertGreaterEqual(len(only_color), len(both))

    def test_unknown_chip_is_ignored(self):
        self.assertEqual(len(filters.apply_filters(self.rows, ["hittepa"])), 3)

    def test_free_text_matches_vin_and_ignores_case(self):
        found = filters.apply_filters(self.rows, text="yaj7")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["vin_kod"], "YAJ7N654")

    def test_free_text_matches_dealer(self):
        self.assertEqual(len(filters.apply_filters(self.rows, text="hjul")), 1)

    def test_missing_fields_are_named_in_swedish(self):
        self.assertEqual(filters.missing_fields(self.rows[1]), ["Godkännandenummer", "Färg"])

    def test_never_invents_values(self):
        self.assertFalse(filters.is_complete({}))
        self.assertEqual(filters.vin({"vin_kod": None}), "")
        self.assertEqual(filters.color({"farg_kod": "  "}), "")
        self.assertTrue(filters.empty_row({"vin_kod": "", "farg_kod": None}))

    def test_summary_counts(self):
        numbers = filters.summary(self.rows, selected=1)
        self.assertEqual(numbers["rows"], 3)
        self.assertEqual(numbers["complete"], 1)
        self.assertEqual(numbers["incomplete"], 2)
        self.assertEqual(numbers["no_color"], 2)
        self.assertEqual(numbers["selected"], 1)

    def test_summary_text_mentions_all_figures(self):
        text = filters.summary_text(self.rows, selected=2, shown=1)
        self.assertIn("3 fordon", text)
        self.assertIn("1 visas", text)
        self.assertIn("2 ofullständiga", text)
        self.assertIn("2 markerade", text)

    def test_summary_text_skips_zero_counts(self):
        text = filters.summary_text([self.rows[0]])
        self.assertNotIn("ofullständiga", text)
        self.assertIn("1 fullständiga", text)


class RowModeTests(unittest.TestCase):
    """Förslag 8: tre radhöjder och textbrytning som användaren styr."""

    def test_three_row_modes(self):
        self.assertEqual(design.TABLE_ROW_MODES, ("compact", "normal", "airy"))
        heights = [design.row_height(mode) for mode in design.TABLE_ROW_MODES]
        self.assertEqual(heights, sorted(heights))
        self.assertEqual(len(set(heights)), 3)

    def test_labels_are_swedish(self):
        self.assertEqual(design.TABLE_ROW_LABELS["airy"], "Luftig")

    def test_old_value_still_works(self):
        self.assertEqual(design.row_height("comfortable"), design.row_height("normal"))
        self.assertEqual(design.resolve_row_mode("trasigt"), "normal")

    def test_word_wrap_can_be_forced(self):
        class View(FreezeAndRowHeightTests.FakeView):
            def __init__(self):
                super().__init__()
                self.wrap = "orörd"

        view = View()
        table_view.apply_density(view, "compact", word_wrap=True)
        self.assertTrue(view.wrap)
        view = View()
        table_view.apply_density(view, "airy", word_wrap=False)
        self.assertFalse(view.wrap)

    def test_word_wrap_default_follows_the_row_mode(self):
        class View(FreezeAndRowHeightTests.FakeView):
            pass

        compact = View()
        table_view.apply_density(compact, "compact")
        self.assertFalse(compact.wrap)
        airy = View()
        table_view.apply_density(airy, "airy")
        self.assertTrue(airy.wrap)

    def test_menu_and_setting_exist(self):
        source = (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")
        self.assertIn("Radhöjd i tabeller", source)
        self.assertIn("ui.row_height", source)
        self.assertIn("ui.word_wrap", source)
        self.assertIn("def _set_row_mode", source)
        self.assertIn("def _set_word_wrap", source)


class RegistryTableTests(unittest.TestCase):
    """Förslag 6–10 kopplade in i fordonsregistret."""

    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "plugins/main_gui/vehicle_registry_page.py").read_text(encoding="utf-8")

    def test_vin_column_is_frozen_and_the_header_stays(self):
        self.assertIn("freeze_first=True", self.source)
        self.assertIn("QHeaderView.ResizeMode.Interactive", self.source)
        self.assertIn("VEHICLE_COLUMNS", self.source)

    def test_table_shows_the_important_columns(self):
        import ast
        tree = ast.parse(self.source)
        columns = next(node for node in tree.body
                       if isinstance(node, ast.AnnAssign)
                       and getattr(node.target, "id", "") == "VEHICLE_COLUMNS")
        names = [element.value for element in columns.value.elts]
        for expected in ("VIN-kod", "Modell", "Godkännandenummer",
                         "Färg", "Återförsäljare", "Status"):
            self.assertIn(expected, names)

    def test_empty_values_are_shown_as_dash_not_invented(self):
        self.assertIn('or "—"', self.source)
        self.assertNotIn('or "Okänd"', self.source)

    def test_filters_and_summary_are_wired(self):
        self.assertIn("vehicle_filters.apply_filters", self.source)
        self.assertIn("vehicle_filters.summary_text", self.source)
        self.assertIn("def _toggle_filter", self.source)
        self.assertIn("def _clear_filters", self.source)
        self.assertIn("FilterChip", self.source)

    def test_profile_is_saved_per_year(self):
        self.assertIn("table_view.load(", self.source)
        self.assertIn("table_view.save(", self.source)
        self.assertIn("self.year", self.source)
        self.assertIn("_reset_table_profile", self.source)

    def test_row_height_comes_from_the_design(self):
        self.assertIn("design.row_height(self._row_mode())", self.source)

    def test_visible_rows_keep_the_file_order(self):
        # Filtret får aldrig sortera om årsfilen.
        self.assertIn("for row in self._vehicles if id(row) in allowed", self.source)


if __name__ == "__main__":
    unittest.main()
