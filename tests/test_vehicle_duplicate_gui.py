from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


def isolated(path, class_name, names, env):
    tree = ast.parse(Path(path).read_text())
    source = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    methods = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in names]
    cls = ast.ClassDef(name='Isolated', bases=[], keywords=[], body=methods, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[]))
    exec(compile(module, path, 'exec'), env)
    return env['Isolated']


class GuiDuplicateTests(unittest.TestCase):
    def test_dialog_does_not_accept_without_explicit_choice(self):
        warning = Mock()
        cls = isolated('plugins/main_gui/vehicle_registry_helpers.py', 'ConflictResolutionDialog',
                       {'_accept_if_resolved', 'get_resolutions'}, {'QMessageBox': SimpleNamespace(warning=warning)})
        dialog = cls(); dialog.accept = Mock()
        choice = [None]
        key = (2024, 'ABC', 0, 'signed')
        dialog._actions = {key: SimpleNamespace(currentData=lambda: choice[0])}
        dialog._accept_if_resolved(); dialog.accept.assert_not_called(); warning.assert_called_once()
        choice[0] = 'keep_both'
        dialog._accept_if_resolved(); dialog.accept.assert_called_once()
        self.assertEqual(dialog.get_resolutions(), {key: 'keep_both'})

    def test_search_offers_a_choice_between_duplicate_vehicles(self):
        class SearchResult:
            def __init__(self, found=False, year=None, index=None, vin3=None, snapshot=None, was_open=False):
                self.found, self.year, self.index, self.vin3 = found, year, index, vin3
                self.snapshot, self.was_open = snapshot, was_open
        prompt = Mock(return_value=('', False))
        import copy
        env = {'copy': copy, '_log': Mock(), 'validate_vin3': lambda v: len(v) == 3,
               'extract_vin3_from_full': lambda v: v[1:4], 'SearchResult': SearchResult,
               'QMessageBox': SimpleNamespace(warning=Mock()),
               'QInputDialog': SimpleNamespace(getItem=prompt)}
        cls = isolated('plugins/main_gui/vehicle_registry_page.py', 'VehicleDataPage', {'_search_vehicle'}, env)
        page = cls()
        records = [{'vin_kod': 'ABC', 'avgaskrav_tillagg': 'A'}, {'vin_kod': 'ABC', 'avgaskrav_tillagg': 'B'}]
        page._tabs = {2024: SimpleNamespace(_vehicles=records, _forms={})}
        page._storage = SimpleNamespace(list_years=lambda: [2024], load_year=Mock())
        self.assertIsNone(page._search_vehicle('ABC'))
        options = prompt.call_args.args[3]
        self.assertIn('Approval: A', options[0]); self.assertIn('Approval: B', options[1])
        prompt.return_value = (options[1], True)
        result = page._search_vehicle('ABC')
        self.assertTrue(result.found); self.assertEqual((result.year, result.index), (2024, 1))


if __name__ == '__main__':
    unittest.main()
