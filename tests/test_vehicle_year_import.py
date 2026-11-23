from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.vehicle_import_insights import profile_coverage, sheet_year, row_year
from plugins.vehicle_registry.excel_importer import ExcelModelImporter, _normalize_column_name
from plugins.vehicle_registry.plugin import VehicleDataStorage

try:
    import pandas as pd
    import openpyxl  # noqa: F401
except ImportError:
    pd = None


class InsightTests(unittest.TestCase):
    def test_profile_coverage_only_counts_existing_headers_and_known_target_fields(self):
        headers = ['VIN CODE', 'Type', 'Colour', 'Extra', '  type  ']
        mapping = {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'COLOUR': 'removed_field', 'OLD': 'typ'}
        self.assertEqual(profile_coverage(headers, mapping, ['vin_kod', 'typ'], _normalize_column_name), (2, 4))
        self.assertEqual(profile_coverage([], mapping, ['vin_kod'], _normalize_column_name), (0, 0))

    def test_profile_dropdown_displays_coverage(self):
        tree = ast.parse(Path('plugins/main_gui/vehicle_registry_helpers.py').read_text())
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'ColumnMappingDialog')
        method = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == '_refresh_profiles')
        isolated = ast.ClassDef(name='Dialog', bases=[], keywords=[], body=[method], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), isolated], type_ignores=[]))
        class Combo:
            def __init__(self): self.items = []
            def blockSignals(self, value): pass
            def clear(self): self.items.clear()
            def addItem(self, label, data): self.items.append((label, data))
            def findData(self, value): return next((i for i, item in enumerate(self.items) if item[1] == value), -1)
            def setCurrentIndex(self, value): self.index = value
        env = {'_normalize_header': _normalize_column_name}
        exec(compile(module, '<profiles-ui>', 'exec'), env)
        dialog = env['Dialog']()
        dialog._profile_store = SimpleNamespace(list_profiles=lambda: {'SAP': {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'OLD': 'typ'}})
        dialog._profile_combo = Combo()
        dialog._headers = ['VINCODE', 'TYPE', 'FUEL']
        dialog._target_labels = {'vin_kod': 'VIN', 'typ': 'Typ'}
        dialog._refresh_profiles('SAP')
        self.assertEqual(dialog._profile_combo.items[1], ('SAP — 2 av 3 kolumner', 'SAP'))
        self.assertEqual(dialog._profile_combo.index, 1)

    def test_years_are_extracted_only_when_unambiguous(self):
        self.assertEqual(sheet_year('2024'), 2024)
        self.assertEqual(sheet_year('Modeller 2023'), 2023)
        self.assertEqual(sheet_year('1999 MC'), 1999)
        self.assertIsNone(sheet_year('2023-2024'))
        self.assertIsNone(sheet_year('123456'))
        self.assertIsNone(sheet_year('MC'))
        self.assertEqual(row_year('24'), 2024)
        self.assertEqual(row_year('2024.0'), 2024)
        for value in ('2024.5', '2024/2025', '20500', '-1', ''):
            self.assertIsNone(row_year(value))

    def test_year_choice_dialog_demands_explicit_choice_and_supports_cancel(self):
        tree = ast.parse(Path('plugins/main_gui/vehicle_registry_page.py').read_text())
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'VehicleDataPage')
        method = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == '_choose_import_years')
        isolated = ast.ClassDef(name='Page', bases=[], keywords=[], body=[method], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), isolated], type_ignores=[]))
        class Message:
            Icon = SimpleNamespace(Warning=1)
            ButtonRole = SimpleNamespace(AcceptRole=1, RejectRole=2)
            choice = 0
            instances = []
            def __init__(self, parent): self.buttons = []; self.instances.append(self)
            def setWindowTitle(self, value): pass
            def setIcon(self, value): pass
            def setTextFormat(self, value): pass
            def setText(self, value): self.text = value
            def addButton(self, text, role):
                button = SimpleNamespace(text=text, role=role)
                self.buttons.append(button)
                return button
            def setDefaultButton(self, button): self.default = button
            def exec(self): pass
            def clickedButton(self): return self.buttons[self.choice]
        qt = SimpleNamespace(TextFormat=SimpleNamespace(PlainText=0))
        env = {'QMessageBox': Message, 'Qt': qt}
        exec(compile(module, '<choose-years>', 'exec'), env)
        page = env['Page']()
        issue = {'sheet': '2024', 'sheet_year': 2024, 'row_year': 2025, 'raw_year': '2025', 'count': 3}
        Message.choice = 0
        self.assertEqual(page._choose_import_years([issue]), {('2024', '2025'): 2024})
        self.assertEqual(Message.instances[-1].default.role, Message.ButtonRole.RejectRole)
        self.assertIn('3 rad', Message.instances[-1].text)
        Message.choice = 1
        self.assertEqual(page._choose_import_years([issue]), {('2024', '2025'): 2025})
        Message.choice = 2
        self.assertIsNone(page._choose_import_years([issue]))



@unittest.skipIf(pd is None, 'pandas och openpyxl saknas')
class MultiSheetImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'sap.xlsx'
        self.storage = VehicleDataStorage(self.root / 'registry')
        self.mapping_dir = self.root / 'json' / 'mappings'
        self.importer = ExcelModelImporter(self.storage, self.mapping_dir)

    def workbook(self, sheets):
        with pd.ExcelWriter(self.path) as writer:
            for name, rows in sheets:
                pd.DataFrame(rows).to_excel(writer, sheet_name=name, index=False)

    def test_examples_contain_actual_values_from_each_sheet(self):
        self.workbook([
            ('2025', {'VINCODE': ['ABC', 'DEF'], 'TYPE': ['Typ A', 'Typ B'], 'Extra': ['', 'hej']}),
            ('2023', {'VINCODE': ['XYZ'], 'TYPE': ['Typ C'], 'Other': ['Ja']}),
        ])
        before = self.path.read_bytes()
        info = self.importer.detect_headers(str(self.path))
        self.assertEqual(info['2025']['examples']['VINCODE'], ['2025: ABC', '2025: DEF'])
        self.assertEqual(info['2025']['examples']['EXTRA'], ['2025: hej'])
        self.assertEqual(info['2023']['examples']['TYPE'], ['2023: Typ C'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_all_year_sheets_import_to_right_year_and_do_not_modify_excel(self):
        self.workbook([
            ('2025', {'VINCODE': ['ABC'], 'TYPE': ['Model A'], 'FUEL': ['EL']}),
            ('År 2023', {'VINCODE': ['DEF'], 'TYPE': ['Model B'], 'FUEL': ['EL']}),
            ('2024', {'VINCODE': ['GHT'], 'TYPE': ['Model C'], 'FUEL': ['EL']}),
        ])
        original = self.path.read_bytes()
        mapping = {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'FUEL': 'bransle1'}
        preview = self.importer.preview_file(str(self.path), mapping)
        self.assertEqual(preview['years'], [2023, 2024, 2025])
        self.assertFalse(preview['year_issues'])
        self.assertEqual(self.storage.list_years(), [])
        result = self.importer.import_file(str(self.path), mapping, save_mapping=False)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['years'], [2023, 2024, 2025])
        self.assertEqual(self.storage.load_year(2023)[0]['vin_kod'], 'DEF')
        self.assertEqual(self.storage.load_year(2024)[0]['vin_kod'], 'GHT')
        self.assertEqual(self.storage.load_year(2025)[0]['vin_kod'], 'ABC')
        self.assertEqual(self.path.read_bytes(), original)

    def test_confirmed_sap_values_convert_and_keep_originals_without_changing_excel(self):
        self.workbook([
            ('2021', {'MODELYEAR': [2021, 2021], 'VINCODE': ['1YAJ4M', '1YBK4M'],
                      'TYPE': ['A', 'B'], 'FUEL': ['P;E5', 'D;B7'], 'EMISLVL': ['EURO 5', 'EURO 6']}),
            ('Pow 2', {'VINCODE': ['ABC'], 'TYPE': ['ignore'], 'MODELYEAR': [2022]}),
        ])
        original = self.path.read_bytes()
        mapping = {'MODELYEAR': '_year', 'VINCODE': 'vin_kod', 'TYPE': 'typ',
                   'FUEL': 'bransle1', 'EMISLVL': 'euroklass'}
        preview = self.importer.preview_file(str(self.path), mapping)
        self.assertIn('Pow 2', preview['sheets_skipped'])
        self.assertEqual(self.storage.list_years(), [])
        result = self.importer.import_file(str(self.path), mapping, save_mapping=False)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['years'], [2021])
        records = {v['vin_kod']: v for v in self.storage.load_year(2021)}
        self.assertEqual(records['YAJ']['bransle1'], 'BENSIN')
        self.assertEqual(records['YAJ']['euroklass'], '5')
        self.assertEqual(records['YAJ']['sap_originalvarden'], {'FUEL': 'P;E5', 'EMISLVL': 'EURO 5'})
        # Omvandling utan fastställd regel är inte tillåten.
        self.assertEqual(records['YBK']['bransle1'], 'D;B7')
        self.assertEqual(records['YBK']['euroklass'], 'EURO 6')
        self.assertEqual(self.path.read_bytes(), original)

    def test_reimport_updates_original_fuel_without_losing_existing_emission_original(self):
        self.storage.save_year(2021, [{'vin_kod': 'YAJ', 'bransle1': 'BENSIN', 'euroklass': '5',
                                      'sap_originalvarden': {'FUEL': 'P;E5', 'EMISLVL': 'EURO 5'}}])
        self.workbook([('2021', {'VINCODE': ['1YAJ4M'], 'FUEL': ['D;B7'], 'TYPE': ['model']})])
        mapping = {'VINCODE': 'vin_kod', 'FUEL': 'bransle1'}
        result = self.importer.import_file(str(self.path), mapping, on_conflict='merge', conflict_resolutions={(2021, 'YAJ'): 'merge'}, save_mapping=False)
        self.assertTrue(result['success'], result)
        vehicle = self.storage.load_year(2021)[0]
        self.assertEqual(vehicle['bransle1'], 'D;B7')
        self.assertEqual(vehicle['sap_originalvarden'], {'FUEL': 'D;B7', 'EMISLVL': 'EURO 5'})
        self.assertEqual(vehicle['euroklass'], '5')

    def test_sap_values_are_not_converted_if_user_maps_to_other_fields(self):
        self.workbook([('2021', {'VINCODE': ['1YAJ4M'], 'FUEL': ['P;E5'], 'EMISLVL': ['EURO 5']})])
        mapping = {'VINCODE': 'vin_kod', 'FUEL': 'typ', 'EMISLVL': 'variant'}
        result = self.importer.import_file(str(self.path), mapping, save_mapping=False)
        self.assertTrue(result['success'], result)
        vehicle = self.storage.load_year(2021)[0]
        self.assertEqual(vehicle['typ'], 'P;E5')
        self.assertEqual(vehicle['variant'], 'EURO 5')
        self.assertNotIn('sap_originalvarden', vehicle)

    def test_conflicting_years_block_all_writes_until_user_chooses(self):
        self.workbook([('2024', {'VINCODE': ['ABC', 'DEF'], 'TYPE': ['A', 'B'], 'MODELYEAR': ['2025', '2025']})])
        mapping = {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'MODELYEAR': '_year'}
        original = self.path.read_bytes()
        result = self.importer.import_file(str(self.path), mapping)
        self.assertTrue(result['needs_year_resolution'])
        issue = result['year_issues'][0]
        self.assertEqual((issue['sheet_year'], issue['row_year'], issue['count']), (2024, 2025, 2))
        self.assertEqual(self.storage.list_years(), [])
        self.assertFalse(self.mapping_dir.exists())
        invalid = self.importer.import_file(str(self.path), mapping, year_choices={('2024', '2025'): 2026})
        self.assertTrue(invalid['needs_year_resolution'])
        valid = self.importer.import_file(str(self.path), mapping, save_mapping=False, year_choices={('2024', '2025'): 2024})
        self.assertTrue(valid['success'], valid)
        self.assertEqual(valid['years'], [2024])
        self.assertEqual(len(self.storage.load_year(2024)), 2)
        self.assertEqual(self.storage.load_year(2025), [])
        self.assertEqual(self.path.read_bytes(), original)

    def test_other_conflict_choice_uses_row_year(self):
        self.workbook([('2024', {'VINCODE': ['ABC'], 'TYPE': ['A'], 'MODELYEAR': ['2025']})])
        mapping = {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'MODELYEAR': '_year'}
        result = self.importer.import_file(str(self.path), mapping, save_mapping=False, year_choices={('2024', '2025'): 2025})
        self.assertTrue(result['success'], result)
        self.assertEqual(result['years'], [2025])

    def test_unknown_year_is_not_silently_guessed(self):
        self.workbook([('2023-2024', {'VINCODE': ['ABC'], 'TYPE': ['A'], 'MODEL': ['bad']})])
        mapping = {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'MODEL': '_year'}
        result = self.importer.import_file(str(self.path), mapping, save_mapping=False)
        self.assertTrue(result['needs_year_resolution'])
        self.assertEqual(result['year_issues'][0]['raw_year'], 'bad')
        self.assertEqual(self.storage.list_years(), [])
        result = self.importer.import_file(str(self.path), mapping, save_mapping=False, year_choices={('2023-2024', 'bad'): 2023})
        self.assertTrue(result['success'], result)
        self.assertEqual(result['years'], [2023])

    def test_multiple_mapped_year_columns_block_import_without_guessing(self):
        self.workbook([('2024', {'VINCODE': ['ABC'], 'MODEL': ['2024'], 'MODELYEAR': ['2025']})])
        result = self.importer.import_file(str(self.path), {'VINCODE': 'vin_kod', 'MODEL': '_year', 'MODELYEAR': '_year'}, save_mapping=False)
        self.assertFalse(result['success'])
        self.assertIn('Flera kolumner', result['errors'][0])
        self.assertEqual(self.storage.list_years(), [])

    def test_duplicate_vin3_does_not_discard_imported_or_existing_records(self):
        self.workbook([
            ('2024', {'VINCODE': ['ABC'], 'TYPE': ['One'], 'FUEL': ['EL']}),
            ('År 2024', {'VINCODE': ['ABC'], 'TYPE': ['Two'], 'FUEL': ['EL']}),
        ])
        self.storage.save_year(2024, [{'vin_kod': 'OLD', 'typ': 'keep'}])
        before = self.storage._year_path(2024).read_bytes()
        mapping = {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'FUEL': 'bransle1'}
        result = self.importer.import_file(str(self.path), mapping)
        self.assertFalse(result['success'])
        self.assertTrue(result['needs_resolution'])
        self.assertEqual(result['conflicts'][0]['vin_kod'], 'ABC')
        self.assertEqual(self.storage._year_path(2024).read_bytes(), before)
        self.assertFalse(self.mapping_dir.exists())

    def test_existing_vin_conflict_requires_explicit_choice_even_with_replace_default(self):
        self.storage.save_year(2021, [{'vin_kod': 'YAJ', 'typ': 'old', 'avgaskrav_tillagg': 'e4*1'}])
        self.workbook([('2021', {'VINCODE': ['1YAJ4M'], 'TYPE': ['new'], 'APPROVAL': ['e4*1']})])
        mapping = {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'APPROVAL': 'avgaskrav_tillagg'}
        path = self.storage._year_path(2021); before = path.read_bytes()
        for choices in (None, {(2021, 'YAJ'): 'bad-action'}):
            result = self.importer.import_file(str(self.path), mapping, on_conflict='replace', conflict_resolutions=choices)
            self.assertTrue(result['needs_resolution'])
            self.assertEqual(result['conflicts'][0]['incoming']['avgaskrav_tillagg'], 'e4*1')
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(self.mapping_dir.exists())
        result = self.importer.import_file(str(self.path), mapping, save_mapping=False,
                                           conflict_resolutions={(2021, 'YAJ'): 'skip'})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result['skipped'], 1)

    def test_different_approval_same_vin_is_not_overwritten_until_full_support_exists(self):
        self.storage.save_year(2021, [{'vin_kod': 'YAJ', 'typ': 'old', 'avgaskrav_tillagg': 'e4*1'}])
        self.workbook([('2021', {'VINCODE': ['1YAJ4M'], 'TYPE': ['new'], 'APPROVAL': ['e4*2']})])
        mapping = {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'APPROVAL': 'avgaskrav_tillagg'}
        path = self.storage._year_path(2021); before = path.read_bytes()
        result = self.importer.import_file(str(self.path), mapping, on_conflict='replace',
                                           conflict_resolutions={(2021, 'YAJ'): 'replace'})
        self.assertFalse(result['success'])
        self.assertTrue(result['needs_resolution'])
        self.assertEqual(result['conflicts'][0]['allowed_actions'], ['keep_both'])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.mapping_dir.exists())

    def test_missing_vin_in_existing_year_is_not_overwritten(self):
        self.workbook([('2024', {'VINCODE': ['ABC'], 'TYPE': ['One'], 'FUEL': ['EL']})])
        mapping = {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'FUEL': 'bransle1'}
        self.storage._year_path(2024).write_text(json.dumps({'vehicles': [{'typ': 'no VIN'}]}), encoding='utf-8')
        before = self.storage._year_path(2024).read_bytes()
        result = self.importer.import_file(str(self.path), mapping, save_mapping=False)
        self.assertFalse(result['success'])
        self.assertTrue(result['errors'])
        self.assertEqual(self.storage._year_path(2024).read_bytes(), before)

    def test_corrupt_existing_year_file_is_not_overwritten(self):
        self.workbook([('2024', {'VINCODE': ['ABC'], 'TYPE': ['One'], 'FUEL': ['EL']})])
        path = self.storage._year_path(2024)
        path.write_bytes(b'{corrupt but valuable data')
        result = self.importer.import_file(str(self.path), {'VINCODE': 'vin_kod', 'TYPE': 'typ'}, save_mapping=False)
        self.assertFalse(result['success'])
        self.assertTrue(result['errors'])
        self.assertEqual(path.read_bytes(), b'{corrupt but valuable data')



if __name__ == '__main__':
    unittest.main()
