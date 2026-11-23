"""Konsekvent svenska och versaler i gränssnittet (förslag 23).

Testet letar efter engelska ord som tidigare smygit sig in i menyer, knappar
och rubriker, samt efter knapptexter som inte börjar med versal. Det läser
källkoden, så en ny text granskas automatiskt.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ord som inte ska stå som synlig text i gränssnittet. Facktermer som VIN, TS,
# Dispatch, Excel och PIN är undantagna eftersom de används av myndigheten.
# "Export" är undantaget därför att det är den etablerade svenska termen i
# Fordonsreg (exporterade filer heter just export).
ENGLISH_WORDS = (
    "Save", "Cancel", "Close", "Delete", "Edit", "Search", "Settings",
    "Refresh", "Open", "Exit", "Help", "About", "Loading", "Error",
    "Warning", "Success", "Failed",
)
FILES = (
    "plugins/main_gui/plugin.py",
    "plugins/main_gui/vehicle_registry_page.py",
    "plugins/main_gui/dialogs/screenshot_dialog.py",
    "plugins/main_gui/dialogs/error_log_dialog.py",
    "plugins/data_viewer/plugin.py",
    "plugins/reports/plugin.py",
    "plugins/dealers_manager/plugin.py",
    "plugins/dispatch_viewer/plugin.py",
    "plugins/ts_excel_importer/widget.py",
)


# Strängar som är loggmeddelanden, nycklar eller kod – inte text till användaren.
_NOT_UI = re.compile(r"^[a-z0-9_.:/\\-]+$|^%[sdrf]|^\{[^}]*\}$")


def _visible_strings(source: str) -> list[tuple[int, str]]:
    """Alla textsträngar som kan hamna i gränssnittet.

    Strängar som är loggmeddelanden (innehåller ``%s``), konstanter i
    versaler och tekniska nycklar hoppas över.
    """
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if not text.strip() or "\n" in text and len(text) > 120:
                continue
            if "%s" in text or "%d" in text or _NOT_UI.match(text.strip()):
                continue
            if re.search(r"[\wÅÄÖåäö]", text) and " " in text or text[:1].isupper():
                found.append((getattr(node, "lineno", 0), text))
    return found


class SwedishTextTests(unittest.TestCase):
    def test_no_english_ui_words(self):
        problems = []
        for path in FILES:
            source = (ROOT / path).read_text(encoding="utf-8")
            for line_number, text in _visible_strings(source):
                for word in ENGLISH_WORDS:
                    if re.search(rf"\b{re.escape(word)}\b", text):
                        problems.append(f"{path}:{line_number}: {word} i {text!r}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_menu_entries_have_capital_letters(self):
        source = (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")
        entries = re.findall(r'addAction\("([^"]+)"', source)
        self.assertTrue(entries)
        # En inledande symbol (ℹ️, 📸) räknas inte – bokstaven efter ska vara versal.
        bad = []
        for entry in entries:
            text = re.sub(r"^[^0-9A-Za-zÅÄÖåäö]+", "", entry)
            if text and text[0].isalpha() and not text[0].isupper():
                bad.append(entry)
        self.assertEqual(bad, [])

    def test_menus_are_named_in_swedish(self):
        source = (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")
        menus = set(re.findall(r'addMenu\("([^"]+)"', source))
        expected = {"Arkiv", "Visa", "Verktyg", "Hjälp", "Inställningar", "Schema",
                    "Tema", "Densitet", "Textstorlek", "Skala gränssnittet"}
        self.assertTrue(expected.issubset(menus), expected - menus)

    def test_dialog_titles_use_swedish_sentence_case(self):
        for path in ("plugins/main_gui/dialogs/screenshot_dialog.py",):
            source = (ROOT / path).read_text(encoding="utf-8")
            for title in re.findall(r'setWindowTitle\("([^"]+)"', source):
                self.assertTrue(title[0].isupper(), f"{path}: {title}")
                self.assertFalse(title.isupper(), f"{path}: {title}")

    def test_density_and_scale_labels_are_swedish(self):
        from core import theme as design
        self.assertEqual(design.DENSITY_LABELS["compact"], "Kompakt")
        self.assertEqual(design.DENSITY_LABELS["comfortable"], "Luftig")
        self.assertEqual(design.DENSITY_LABELS["auto"], "Automatisk")
        for label in design.THEME_LABELS.values():
            self.assertTrue(label[0].isupper(), label)

    def test_new_support_text_is_swedish(self):
        source = (ROOT / "plugins/main_gui/dialogs/screenshot_dialog.py").read_text(encoding="utf-8")
        self.assertIn("Skärmbild", source)
        self.assertIn("maskerade", source)
        self.assertNotIn("Screenshot of", source)


if __name__ == "__main__":
    unittest.main()
