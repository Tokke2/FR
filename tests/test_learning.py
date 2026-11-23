from __future__ import annotations

import ast
import copy
import json
import logging
from pathlib import Path
import sys
import tempfile
import types
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.learning import (LearningStore, LearningError, VEHICLE_IMPORT,
                           learn_vehicle_import, vehicle_mapping_suggestions)

ROOT = Path(__file__).resolve().parents[1]


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'learning.json'
        self.store = LearningStore(self.path)
        self.mapping = {'SPECIALMODEL': 'typ', 'VINCODE': 'vin_kod'}
        self.fields = {'typ', 'vin_kod', 'variant'}
        self.result = {'success': True, 'fingerprint': 'abc', 'mapping_used': dict(self.mapping),
                       'errors': [], 'row_errors': [], 'skipped': 0}

    def learn(self, **changes):
        opts = {'approved_save': True, 'protected': False}
        opts.update(changes)
        return learn_vehicle_import(self.store, self.mapping, self.fields, self.result, 'abc', **opts)

    def test_learns_only_after_repeated_confirmed_imports_and_uses_context(self):
        self.assertTrue(self.learn())
        self.assertEqual(self.store.suggestions(VEHICLE_IMPORT, self.mapping, self.fields), {})
        self.assertTrue(self.learn())
        self.assertEqual(self.store.suggestions(VEHICLE_IMPORT, self.mapping, self.fields), self.mapping)
        self.assertEqual(self.store.suggestions('another_feature.v1', self.mapping, self.fields), {})
        # Inget filnamn, fordonsvärde, PIN eller arbetsboksinnehåll lagras.
        stored = self.path.read_text()
        self.assertNotIn('abc', stored)
        self.assertNotIn('123456789', stored)

    def test_correction_makes_column_ambiguous_even_after_many_old_observations(self):
        for _ in range(3): self.learn()
        self.store.observe_mapping(VEHICLE_IMPORT, {'SPECIALMODEL': 'variant'}, self.fields)
        suggestions = self.store.suggestions(VEHICLE_IMPORT, self.mapping, self.fields)
        self.assertNotIn('SPECIALMODEL', suggestions)
        self.assertEqual(suggestions['VINCODE'], 'vin_kod')
        self.assertEqual(self.store.status()['conflicts'], 1)

    def test_preserves_explicit_mappings_and_prevents_duplicate_target_from_learning(self):
        self.learn(); self.learn()
        merged, used = vehicle_mapping_suggestions(self.store, ['SPECIALMODEL', 'VINCODE'], {}, self.fields)
        self.assertEqual(merged, self.mapping)
        self.assertEqual(used, ['SPECIALMODEL', 'VINCODE'])
        merged, used = vehicle_mapping_suggestions(self.store, ['SPECIALMODEL'], {'OTHER': 'typ'}, self.fields)
        self.assertNotIn('SPECIALMODEL', merged)
        self.assertEqual(used, [])
        self.assertEqual(self.store.suggestions(VEHICLE_IMPORT, self.mapping, {'variant'}), {})

    def test_never_learns_cancelled_protected_unapproved_or_partial_imports(self):
        self.assertFalse(self.learn(approved_save=False))
        self.assertFalse(self.learn(protected=True))
        for changes in ({'success': False}, {'errors': ['disk']}, {'row_errors': ['row']},
                        {'skipped': 1}, {'needs_resolution': True}, {'needs_year_resolution': True},
                        {'fingerprint': 'different'}, {'mapping_used': {'SPECIALMODEL': 'variant'}}):
            old = self.result.copy(); self.result.update(changes)
            self.assertFalse(self.learn(), changes)
            self.result = old
        self.assertFalse(self.path.exists())

    def test_disable_resume_and_clear_are_local_and_explicit(self):
        self.learn(); self.learn()
        self.store.set_enabled(False)
        old = self.path.read_bytes()
        self.assertFalse(self.learn())
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(self.store.suggestions(VEHICLE_IMPORT, self.mapping, self.fields), {})
        self.store.set_enabled(True)
        self.assertEqual(self.store.suggestions(VEHICLE_IMPORT, self.mapping, self.fields), self.mapping)
        self.store.clear()
        self.assertEqual(self.store.status()['rules'], 0)
        self.assertTrue(self.store.status()['enabled'])

    def test_invalid_files_are_not_overwritten_or_cleared(self):
        for content in (b'broken', b'{"version":2,"enabled":true,"contexts":{}}',
                        b'{"version":1,"enabled":true,"contexts":{"x":{"A":{"typ":-1}}}}'):
            self.path.write_bytes(content)
            for operation in (lambda: self.learn(), self.store.clear,
                              lambda: self.store.set_enabled(False), self.store.status):
                with self.assertRaises(LearningError): operation()
                self.assertEqual(self.path.read_bytes(), content)

    def test_failed_atomic_save_leaves_prior_learning_unchanged(self):
        self.learn(); prior = self.path.read_bytes()
        with patch('core.learning.os.replace', side_effect=OSError('disk')):
            with self.assertRaises(OSError): self.learn()
        self.assertEqual(self.path.read_bytes(), prior)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_unknown_target_and_invalid_mapping_are_rejected(self):
        with self.assertRaises(LearningError):
            self.store.observe_mapping(VEHICLE_IMPORT, {'X': 'unknown'}, self.fields)
        self.assertFalse(self.path.exists())

    def test_menu_pause_resume_and_confirmed_reset(self):
        source_path = ROOT / 'plugins/main_gui/plugin.py'
        tree = ast.parse(source_path.read_text(encoding='utf-8'))
        source = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'MainWindow')
        selected = {'_show_learning_info', '_toggle_learning', '_clear_learning'}
        methods = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in selected]
        cls = ast.ClassDef(name='Window', bases=[], keywords=[], body=methods, decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[]))
        msg = SimpleNamespace(information=Mock(), warning=Mock(), question=Mock(return_value=2),
                              StandardButton=SimpleNamespace(Yes=1, No=2))
        env = {'QMessageBox': msg, '_log': logging.getLogger('learning.test')}
        exec(compile(module, str(source_path), 'exec'), env)
        window = env['Window'](); window._learning_store = lambda: self.store
        self.learn(); self.learn()
        window._show_learning_info()
        self.assertIn('Återförsäljare', msg.information.call_args.args[2])
        window._toggle_learning(); self.assertFalse(self.store.status()['enabled'])
        window._toggle_learning(); self.assertTrue(self.store.status()['enabled'])
        window._clear_learning(); self.assertGreater(self.store.status()['rules'], 0)
        msg.question.return_value = 1
        window._clear_learning(); self.assertEqual(self.store.status()['rules'], 0)
        msg.warning.assert_not_called()

    def test_actual_excel_import_produces_evidence_without_storing_vehicle_values(self):
        try:
            import pandas as pd
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest('Excel-testberoenden saknas')
        from plugins.vehicle_registry.excel_importer import ExcelModelImporter
        from plugins.vehicle_registry.plugin import VehicleDataStorage
        root = Path(self.tmp.name)
        storage = VehicleDataStorage(root / 'vehicle-data')
        importer = ExcelModelImporter(vehicle_storage=storage, mapping_dir=root / 'mappings')
        mapping = {'VINCODE': 'vin_kod', 'YEAR': '_year', 'CUSTOMMODEL': 'typ'}
        allowed = {'vin_kod', '_year', 'typ'}
        for year in (2024, 2025):
            source = root / f'{year}.xlsx'
            pd.DataFrame({'VINCODE': ['ABC'], 'YEAR': [str(year)], 'CUSTOMMODEL': ['SensitiveModel']}).to_excel(source, index=False)
            headers = [h for info in importer.detect_headers(str(source)).values()
                       if not info.get('skipped') for h in info.get('headers', [])]
            fingerprint = importer.build_fingerprint(headers)
            result = importer.import_file(str(source), column_mapping=mapping, save_mapping=False)
            self.assertTrue(result['success'], result)
            self.assertTrue(learn_vehicle_import(self.store, mapping, allowed, result, fingerprint,
                                                 approved_save=True, protected=False))
        self.assertEqual(self.store.suggestions(VEHICLE_IMPORT, mapping, allowed), mapping)
        self.assertNotIn('SensitiveModel', self.path.read_text())
        self.assertNotIn('ABC', self.path.read_text())
        self.assertEqual(len(storage.load_year(2024)), 1)
        self.assertEqual(len(storage.load_year(2025)), 1)

    def test_mapping_ui_import_flow_records_success_and_prefills_later_variant(self):
        path = ROOT / 'plugins/main_gui/vehicle_registry_page.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        source = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'VehicleDataPage')
        method = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == '_import_from_excel')
        cls = ast.ClassDef(name='Page', bases=[], keywords=[], body=[method], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[]))
        mapping = dict(self.mapping)
        class Dialog:
            calls = []
            def __init__(self, **kwargs): self.calls.append(kwargs)
            def exec(self): return 1
            def get_mapping(self): return dict(mapping)
            def save_mapping_checked(self): return True
            def protect_checked(self): return False
            def get_pin(self): return ''
        class Progress:
            def __init__(self, *args): pass
            def __getattr__(self, key): return lambda *args: None
        plugin = SimpleNamespace(
            detect_excel_headers=lambda path: {'2025': {'headers': ['SPECIAL MODEL', 'VINCODE']}},
            build_mapping_fingerprint=lambda headers: '|'.join(headers),
            load_column_mapping_for_fingerprint=lambda fingerprint: None,
            suggest_column_mapping=lambda headers: {}, set_column_mapping=Mock(),
            preview_excel_import=lambda **kwargs: {'errors': [], 'year_issues': [], 'conflicts': []},
            import_from_excel=lambda **kwargs: {'success': True, 'fingerprint': 'SPECIAL MODEL|VINCODE',
                'mapping_used': dict(mapping), 'years': [], 'errors': [], 'row_errors': [], 'skipped': 0},
        )
        env = {'get_plugin_safe': lambda app, name: plugin, 'QFileDialog': SimpleNamespace(getOpenFileName=lambda *args: ('sample.xlsx', '')),
               'Path': Path, '__file__': str(path), 'QProgressDialog': Progress,
               'Qt': SimpleNamespace(WindowModality=SimpleNamespace(WindowModal=1)),
               'QDialog': SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
               '_log': logging.getLogger('learning.test'), '_normalize_header': lambda s: s.replace(' ', '').upper(),
               'ColumnMappingDialog': Dialog, 'TARGET_FIELD_LABELS': {f: f for f in self.fields},
               'QMessageBox': SimpleNamespace(warning=Mock(), critical=Mock())}
        exec(compile(module, str(path), 'exec'), env)
        page = env['Page'](); page._modified = set(); page._app = object(); page._tabs = {}; page._show_import_result = Mock()
        qtwidgets = types.ModuleType('PySide6.QtWidgets')
        qtwidgets.QApplication = SimpleNamespace(processEvents=lambda: None)
        package = types.ModuleType('PySide6'); package.__path__ = []
        with patch.dict(sys.modules, {'PySide6': package, 'PySide6.QtWidgets': qtwidgets}), \
             patch('core.learning.LearningStore', return_value=self.store), \
             patch('core.vehicle_mapping_profiles.ProfileStore'):
            page._import_from_excel(); page._import_from_excel(); page._import_from_excel()
        self.assertEqual(page._show_import_result.call_count, 3)
        self.assertEqual(Dialog.calls[0]['learned_headers'], [])
        self.assertEqual(Dialog.calls[2]['initial_mapping'], mapping)
        self.assertEqual(set(Dialog.calls[2]['learned_headers']), set(mapping))
        self.assertEqual(plugin.set_column_mapping.call_count, 3)
        env['QMessageBox'].critical.assert_not_called()
        # En gammal PIN-skyddad fingerprint förblir skyddad även när rutan
        # i den nya dialogen inte är markerad.
        before = self.store.path.read_bytes()
        plugin.load_column_mapping_for_fingerprint = lambda fingerprint: dict(mapping)
        plugin.is_mapping_protected = lambda fingerprint: True
        with patch.dict(sys.modules, {'PySide6': package, 'PySide6.QtWidgets': qtwidgets}), \
             patch('core.learning.LearningStore', return_value=self.store), \
             patch('core.vehicle_mapping_profiles.ProfileStore'):
            page._import_from_excel()
        self.assertFalse(Dialog.calls[-1]['allow_profile_save'])
        self.assertEqual(self.store.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
