from __future__ import annotations

import ast
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from plugins.vehicle_registry.plugin import VehicleDataStorage


class VehicleBackupTests(unittest.TestCase):
    def test_previous_year_is_backed_up_exactly_before_each_change(self):
        with tempfile.TemporaryDirectory() as folder:
            storage = VehicleDataStorage(Path(folder))
            path = storage.base_dir / '2024.json'
            storage.save_year(2024, [{'vin_kod': 'YAJ', 'typ': 'original'}])
            original = path.read_bytes()
            backups = list((storage.backup_dir / '2024').glob('*.json'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            storage.save_year(2024, [{'vin_kod': 'YAJ', 'typ': 'second'}])
            backups = list((storage.backup_dir / '2024').glob('*.json'))
            self.assertEqual(len(backups), 2)
            self.assertTrue(all(item.read_bytes() == original for item in backups))
            second = path.read_bytes()
            storage.save_year(2024, [{'vin_kod': 'YAJ', 'typ': 'third'}])
            backups = list((storage.backup_dir / '2024').glob('*.json'))
            self.assertEqual(len(backups), 3)
            self.assertEqual({x.read_bytes() for x in backups}, {original, second})

    def test_failure_of_first_backup_does_not_create_year_file(self):
        with tempfile.TemporaryDirectory() as folder:
            storage = VehicleDataStorage(Path(folder))
            with patch('core.vehicle_backup.backup_new_year', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(ValueError, 'säkerhetskopia'):
                    storage.save_year(2024, [{'vin_kod': 'ABC'}])
            self.assertFalse((storage.base_dir / '2024.json').exists())

    def test_backup_failure_aborts_save_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            storage = VehicleDataStorage(Path(folder))
            storage.save_year(2024, [{'vin_kod': 'ABC', 'typ': 'keep'}])
            before = (storage.base_dir / '2024.json').read_bytes()
            with patch('core.vehicle_backup.backup_year', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(ValueError, 'säkerhetskopia'):
                    storage.save_year(2024, [{'vin_kod': 'ABC', 'typ': 'new'}])
            self.assertEqual((storage.base_dir / '2024.json').read_bytes(), before)

    def test_invalid_save_creates_no_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            storage = VehicleDataStorage(Path(folder))
            storage.save_year(2024, [{'vin_kod': 'ABC'}])
            before = list((storage.backup_dir / '2024').glob('*.json'))
            with self.assertRaises(ValueError):
                storage.save_year(2024, [{'vin_kod': ''}])
            self.assertEqual(list((storage.backup_dir / '2024').glob('*.json')), before)

    def test_symlink_backup_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            storage = VehicleDataStorage(root)
            storage.save_year(2024, [{'vin_kod': 'ABC'}])
            import shutil
            shutil.rmtree(storage.backup_dir)
            try:
                storage.backup_dir.symlink_to(root, target_is_directory=True)
            except OSError:
                self.skipTest('symboliska länkar saknas')
            before = (storage.base_dir / '2024.json').read_bytes()
            with self.assertRaises(ValueError):
                storage.save_year(2024, [{'vin_kod': 'DEF'}])
            self.assertEqual((storage.base_dir / '2024.json').read_bytes(), before)


class SearchResult:
    def __init__(self, found=False, year=None, index=None, vin3=None, snapshot=None, was_open=False):
        self.found, self.year, self.index, self.vin3 = found, year, index, vin3
        self.snapshot, self.was_open = snapshot, was_open


def search_page_class(dialog):
    path = Path('plugins/main_gui/vehicle_registry_page.py')
    tree = ast.parse(path.read_text())
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'VehicleDataPage')
    methods = [x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name in {'_search_vehicle', '_navigate_to_result'}]
    module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), ast.ClassDef(name='Isolated', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[]))
    env = {'copy': copy, '_log': Mock(), 'SearchResult': SearchResult, 'QInputDialog': dialog,
           'QMessageBox': SimpleNamespace(warning=Mock()),
           'validate_vin3': lambda value: len(value) == 3 and value.isalnum(),
           'extract_vin3_from_full': lambda value: value[1:4]}
    exec(compile(module, str(path), 'exec'), env)
    return env['Isolated'], env


class AllYearSearchTests(unittest.TestCase):
    def test_approval_search_reads_unopened_archived_year_and_opens_only_choice(self):
        prompt = Mock(return_value=('', False))
        cls, _ = search_page_class(SimpleNamespace(getItem=prompt))
        page = cls()
        page._storage = SimpleNamespace(list_years=lambda: [2020, 2024], load_year=lambda y: {2020: [{'vin_kod': 'ABC', 'avgaskrav_tillagg': 'E4*AB'}], 2024: []}[y])
        page._tabs = {2024: SimpleNamespace(_vehicles=[], _forms={})}
        page._create_tab = Mock()
        result = page._search_vehicle('e4*ab')
        self.assertTrue(result.found)
        self.assertEqual((result.year, result.index, result.was_open), (2020, 0, False))
        page._create_tab.assert_not_called()
        page._create_tab.side_effect = lambda year, select: page._tabs.update({year: SimpleNamespace(_vehicles=[result.snapshot], _forms={}, select_row=Mock())})
        page._show_year = Mock(); page._search = SimpleNamespace(clear=Mock())
        page._navigate_to_result(result)
        page._create_tab.assert_called_once_with(2020, select=False)
        page._show_year.assert_called_once_with(2020)
        page._tabs[2020].select_row.assert_called_once_with(0)

    def test_unsaved_form_values_override_saved_rows_and_show_multiple_years(self):
        prompt = Mock(return_value=('', False))
        cls, _ = search_page_class(SimpleNamespace(getItem=prompt))
        page = cls()
        page._storage = SimpleNamespace(list_years=lambda: [2021, 2024], load_year=lambda y: [{'vin_kod': 'YAJ', 'avgaskrav_tillagg': 'E4*NEW'}])
        form = SimpleNamespace(get_data=lambda: {'vin_kod': 'YAJ', 'avgaskrav_tillagg': 'E4*NEW'})
        page._tabs = {2024: SimpleNamespace(_vehicles=[{'vin_kod': 'YAJ', 'avgaskrav_tillagg': 'OLD'}], _forms={'0': form})}
        self.assertIsNone(page._search_vehicle('e4*new'))
        options = prompt.call_args.args[3]
        self.assertEqual(len(options), 2)
        self.assertIn('2021', options[1]); self.assertIn('2024', options[0])
        prompt.return_value = (options[0], True)
        result = page._search_vehicle('YAJ')
        self.assertEqual((result.year, result.index, result.was_open), (2024, 0, True))

    def test_changed_result_does_not_select_wrong_row(self):
        cls, env = search_page_class(SimpleNamespace(getItem=Mock()))
        page = cls(); tab = SimpleNamespace(_vehicles=[{'vin_kod': 'OTHER'}], _forms={}, select_row=Mock())
        page._tabs = {2020: tab}; page._show_year = Mock(); page._search = SimpleNamespace(clear=Mock())
        page._navigate_to_result(SearchResult(True, 2020, 0, snapshot={'vin_kod': 'ABC'}))
        tab.select_row.assert_not_called()
        env['QMessageBox'].warning.assert_called_once()

    def test_unreadable_year_reports_incomplete_search(self):
        cls, env = search_page_class(SimpleNamespace(getItem=Mock()))
        page = cls(); page._tabs = {}
        page._storage = SimpleNamespace(list_years=lambda: [2021], load_year=Mock(side_effect=ValueError('bad data')))
        self.assertIsNone(page._search_vehicle('E4'))
        env['QMessageBox'].warning.assert_called_once()


if __name__ == '__main__':
    unittest.main()
