from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.vehicle_mapping_profiles import ProfileError, ProfileStore, unmapped_headers
from plugins.vehicle_registry.excel_importer import ExcelModelImporter, _normalize_column_name


class ProfileTests(unittest.TestCase):
    def test_named_profiles_persist_select_and_do_not_overwrite_without_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mappings' / 'profiles.json'
            store = ProfileStore(path)
            a = {'VINCODE': 'vin_kod', 'TYPE': 'typ'}
            b = {'VIN': 'vin_kod', 'MODEL': 'handelsbeteckning'}
            store.save('Leverantör A', a)
            store.save('Leverantör B', b)
            loaded = ProfileStore(path).list_profiles()
            self.assertEqual(loaded, {'Leverantör A': a, 'Leverantör B': b})
            loaded['Leverantör A']['TYPE'] = 'wrong'
            with self.assertRaises(FileExistsError):
                store.save('leverantör a', b)
            self.assertEqual(store.list_profiles()['Leverantör A'], a)
            store.save('leverantör a', b, overwrite=True)
            self.assertEqual(store.list_profiles()['Leverantör A'], b)
            self.assertEqual(store.list_profiles()['Leverantör B'], b)

    def test_corrupt_profile_file_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profiles.json'
            for raw in (b'not json', b'{"version":99,"profiles":{}}', b'{"version":1,"profiles":[]}'):
                path.write_bytes(raw)
                with self.assertRaises(ProfileError):
                    ProfileStore(path).save('Test', {'VIN': 'vin_kod'})
                self.assertEqual(path.read_bytes(), raw)

    def test_failed_atomic_save_keeps_existing_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profiles.json'
            store = ProfileStore(path)
            store.save('A', {'VIN': 'vin_kod'})
            old = path.read_bytes()
            with patch('core.vehicle_mapping_profiles.os.replace', side_effect=OSError('disk')), self.assertRaises(OSError):
                store.save('B', {'TYPE': 'typ'})
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_all_unmapped_headers_are_identified_using_import_normalization(self):
        headers = ['VIN CODE', 'Färg', 'Extra', 'Weight']
        mapping = {'VINCODE': 'vin_kod', 'FARG': 'farg'}
        self.assertEqual(unmapped_headers(headers, mapping, _normalize_column_name), ['Extra', 'Weight'])
        self.assertEqual(unmapped_headers(headers, {**mapping, 'EXTRA': 'typ', 'WEIGHT': 'vikt'}, _normalize_column_name), [])

    def test_profile_selection_maps_known_headers_and_leaves_new_ones_unmapped(self):
        tree = ast.parse(Path('plugins/main_gui/vehicle_registry_helpers.py').read_text())
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'ColumnMappingDialog')
        method = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == '_select_profile')
        isolated = ast.ClassDef(name='Dialog', bases=[], keywords=[], body=[method], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), isolated], type_ignores=[]))
        env = {'_normalize_header': _normalize_column_name}
        exec(compile(module, '<dialog>', 'exec'), env)
        class Combo:
            def __init__(self): self.value = None
            def findData(self, value): return {'': 0, 'vin_kod': 1, 'typ': 2}.get(value, -1)
            def setCurrentIndex(self, value): self.value = value
        dialog = env['Dialog']()
        dialog._profiles = {'Leverantör': {'VINCODE': 'vin_kod', 'TYPE': 'typ'}}
        dialog._profile_combo = SimpleNamespace(currentData=lambda: 'Leverantör')
        dialog._headers = ['VIN CODE', 'Type', 'Nytt fält']
        dialog._combos = [Combo(), Combo(), Combo()]
        dialog._initial_mapping = {}
        updates = []
        dialog._update_unmapped_status = lambda: updates.append(True)
        dialog._select_profile()
        self.assertEqual([c.value for c in dialog._combos], [1, 2, 0])
        self.assertTrue(updates)

    def test_protected_mapping_cannot_be_saved_as_unprotected_profile(self):
        tree = ast.parse(Path('plugins/main_gui/vehicle_registry_helpers.py').read_text())
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'ColumnMappingDialog')
        method = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == '_save_profile')
        isolated = ast.ClassDef(name='Dialog', bases=[], keywords=[], body=[method], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[]))
        message = SimpleNamespace(warning=Mock())
        env = {'QMessageBox': message}
        exec(compile(module, '<dialog>', 'exec'), env)
        dialog = env['Dialog'](); dialog._allow_profile_save = False
        dialog.protect_checked = lambda: False
        dialog.get_mapping = Mock()
        dialog._save_profile()
        dialog.get_mapping.assert_not_called()
        dialog._allow_profile_save = True
        dialog.protect_checked = lambda: True
        dialog._save_profile()
        dialog.get_mapping.assert_not_called()
        self.assertEqual(message.warning.call_count, 2)

    def test_warning_requires_explicit_yes_and_lists_every_unmapped_column(self):
        tree = ast.parse(Path('plugins/main_gui/vehicle_registry_helpers.py').read_text())
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'ColumnMappingDialog')
        accept = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == 'accept')
        isolated = ast.ClassDef(name='Dialog', bases=[ast.Name(id='QDialog', ctx=ast.Load())], keywords=[], body=[accept], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[]))
        class Base:
            def accept(self): self.accepted = True
        class Message:
            StandardButton = SimpleNamespace(Yes=1, No=2)
            Icon = SimpleNamespace(Warning=4)
            answer = 2
            instances = []
            def __init__(self, parent):
                self.details = None
                self.instances.append(self)
            def setWindowTitle(self, x): pass
            def setIcon(self, x): pass
            def setText(self, x): pass
            def setDetailedText(self, x): self.details = x
            def setInformativeText(self, x): pass
            def setStandardButtons(self, x): pass
            def setDefaultButton(self, x): self.default = x
            def exec(self): return self.answer
            @staticmethod
            def warning(*args): pass
        env = {'QDialog': Base, 'QMessageBox': Message}
        exec(compile(module, '<dialog>', 'exec'), env)
        dialog = env['Dialog']()
        dialog.get_mapping = lambda: {'VIN': 'vin_kod'}
        dialog.protect_checked = lambda: False
        dialog._unmapped_headers = lambda: ['Extra1', 'Extra2', 'Extra3']
        dialog.accept()
        self.assertFalse(getattr(dialog, 'accepted', False))
        self.assertEqual(Message.instances[-1].details, 'Extra1\nExtra2\nExtra3')
        self.assertEqual(Message.instances[-1].default, Message.StandardButton.No)
        Message.answer = 1
        dialog.accept()
        self.assertTrue(dialog.accepted)


class ExistingMappingSafetyTests(unittest.TestCase):
    def test_bad_pin_does_not_modify_fingerprint_or_active_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'json' / 'mappings'
            importer = ExcelModelImporter(vehicle_storage=Mock(), mapping_dir=directory)
            importer.set_column_mapping({'VINCODE': 'vin_kod'}, fingerprint='abc', pin='1234', protected=True)
            paths = [directory / 'column_mapping.json', directory / 'vehicle_import_mapping.json']
            before = [p.read_bytes() for p in paths]
            with self.assertRaises(PermissionError):
                importer.set_column_mapping({'VINCODE': 'typ'}, fingerprint='abc', pin='wrong')
            self.assertEqual([p.read_bytes() for p in paths], before)
            self.assertEqual(importer.get_column_mapping(), {'VINCODE': 'vin_kod'})

    def test_existing_pin_protection_survives_unchecked_dialog(self):
        with tempfile.TemporaryDirectory() as tmp:
            importer = ExcelModelImporter(vehicle_storage=Mock(), mapping_dir=Path(tmp))
            importer.set_column_mapping({'VIN': 'vin_kod'}, fingerprint='abc', pin='1234', protected=True)
            self.assertTrue(importer.is_mapping_protected('abc'))
            importer.set_column_mapping({'VIN': 'vin_kod'}, fingerprint='abc', pin='1234', protected=False)
            self.assertTrue(importer.is_mapping_protected('abc'))
            self.assertFalse(importer.is_mapping_protected('different'))

    def test_legacy_fingerprints_are_preserved_during_first_new_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / 'data' / 'mappings' / 'vehicle_import_mapping.json'
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({'mappings': {'old': {'mapping': {'A': 'typ'}}}}))
            importer = ExcelModelImporter(vehicle_storage=Mock(), mapping_dir=root / 'json' / 'mappings')
            importer.set_column_mapping({'VIN': 'vin_kod'}, fingerprint='new')
            saved = json.loads((root / 'json' / 'mappings' / 'vehicle_import_mapping.json').read_text())
            self.assertEqual(set(saved['mappings']), {'old', 'new'})
            self.assertTrue(legacy.exists())

    def test_invalid_fingerprint_file_is_not_destroyed(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = directory / 'vehicle_import_mapping.json'
            path.write_text('invalid json')
            importer = ExcelModelImporter(vehicle_storage=Mock(), mapping_dir=directory)
            before = importer.get_column_mapping()
            with self.assertRaises(ValueError):
                importer.set_column_mapping({'VIN': 'vin_kod'}, fingerprint='x')
            self.assertEqual(path.read_text(), 'invalid json')
            self.assertEqual(importer.get_column_mapping(), before)
            self.assertFalse((directory / 'column_mapping.json').exists())

    def test_real_excel_preview_does_not_save_mapping(self):
        try:
            import pandas as pd
            import openpyxl  # noqa
        except ImportError:
            self.skipTest('Excel-testberoenden saknas')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.xlsx'
            pd.DataFrame({'VINCODE': ['ABC'], 'TYPE': ['Example'], 'COMNAME': ['Example'], 'YEAR': ['2025'], 'FUEL': ['EL']}).to_excel(path, index=False)
            directory = Path(tmp) / 'mappings'
            importer = ExcelModelImporter(vehicle_storage=None, mapping_dir=directory)
            with patch.object(importer, '_save_fingerprint_mapping') as save:
                result = importer.preview_file(str(path), column_mapping={'VINCODE': 'vin_kod', 'TYPE': 'typ'})
            self.assertTrue(result['fingerprint'])
            self.assertEqual(result['mapping_used']['VINCODE'], 'vin_kod')
            save.assert_not_called()
            self.assertFalse(directory.exists())

    def test_plugin_import_does_not_write_active_mapping_when_not_requested(self):
        from plugins.vehicle_registry.plugin import Plugin
        plugin = Plugin(None)
        plugin._excel_importer = Mock()
        plugin._excel_importer.import_file.return_value = {'success': False}
        plugin.import_from_excel('anything.xlsx', column_mapping={'VIN': 'vin_kod'}, save_mapping=False, dry_run=True)
        plugin._excel_importer.set_column_mapping.assert_not_called()
        self.assertFalse(plugin._excel_importer.import_file.call_args.kwargs['save_mapping'])


if __name__ == '__main__':
    unittest.main()
