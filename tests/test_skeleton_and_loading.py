"""Skeleton-rader som inte flyttar layouten (förslag 24)."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import skeleton  # noqa: E402


class FakeTable:
    """Minimal tabell som räknar anropen."""

    class SelectionMode:
        NoSelection = 0
        ExtendedSelection = 3

    def __init__(self, columns):
        self.columns = columns
        self.rows = 0
        self.heights = {}
        self.mode = None
        self.cells = {}

    def setRowCount(self, value):
        self.rows = value

    def setRowHeight(self, row, height):
        self.heights[row] = height

    def setSelectionMode(self, value):
        self.mode = value

    def item(self, row, column):
        return self.cells.get((row, column))


class SkeletonTests(unittest.TestCase):
    def test_default_number_of_rows(self):
        self.assertEqual(skeleton.row_count(), skeleton.DEFAULT_ROWS)

    def test_negative_or_broken_values_are_clamped(self):
        self.assertEqual(skeleton.row_count(-5), 0)
        self.assertEqual(skeleton.row_count("trasigt"), skeleton.DEFAULT_ROWS)
        self.assertLessEqual(skeleton.row_count(999), 20)

    def test_placeholders_are_never_invented_data(self):
        for column in ("VIN-kod", "Modell", "Färg"):
            self.assertEqual(skeleton.placeholder_text(column), "")
        self.assertEqual(skeleton.placeholder_values(["a", "b"]), ["", ""])

    def test_placeholder_rows_use_the_real_row_height(self):
        table = FakeTable(["VIN-kod", "Modell"])
        count = skeleton.show(table, ["VIN-kod", "Modell"], rows=4, row_height=42)
        self.assertEqual(count, 4)
        self.assertEqual(table.rows, 4)
        self.assertEqual(set(table.heights.values()), {42})

    def test_placeholders_cannot_be_selected(self):
        table = FakeTable(["VIN-kod"])
        skeleton.show(table, ["VIN-kod"])
        self.assertEqual(table.mode, table.SelectionMode.NoSelection)
        skeleton.clear(table)
        self.assertEqual(table.rows, 0)
        self.assertEqual(table.mode, table.SelectionMode.ExtendedSelection)

    def test_layout_does_not_move(self):
        """Samma antal rader och samma höjd före och efter inläsning."""
        table = FakeTable(["VIN-kod", "Modell"])
        skeleton.show(table, ["VIN-kod", "Modell"], rows=3, row_height=32)
        before = table.rows * table.heights[0]
        skeleton.clear(table)
        for row in range(3):
            table.setRowHeight(row, 32)
        after = 3 * table.heights[1]
        self.assertEqual(before, after)

    def test_bar_width_follows_the_column(self):
        self.assertGreater(skeleton.bar_width(200, "VIN-kod"),
                           skeleton.bar_width(200, "Modell"))
        self.assertEqual(skeleton.bar_width("trasigt"), 0)

    def test_broken_table_does_not_crash(self):
        self.assertEqual(skeleton.show(object(), ["a"]), 0)
        skeleton.clear(object())


if __name__ == "__main__":
    unittest.main()
