from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.vehicle_duplicate_resolution import plan_year
from plugins.vehicle_registry.plugin import VehicleDataStorage, VehicleCache, Plugin
from plugins.vehicle_registry.excel_importer import ExcelModelImporter

try:
    import pandas as pd
    import openpyxl  # noqa
except ImportError:
    pd = None


def row(vin='ABC', approval='', typ=''):
    return {'vin_kod': vin, 'avgaskrav_tillagg': approval, 'typ': typ}


class DuplicatePlannerTests(unittest.TestCase):
    def test_different_approval_needs_explicit_keep_both_and_is_not_destroyed_by_replace(self):
        old = row(approval='A', typ='old'); new = row(approval='B', typ='new')
        original = [old]
        p = plan_year(2024, original, [new], {})
        c = p['conflict']; self.assertEqual(c['allowed_actions'], ['keep_both'])
        for choices in ({(2024, 'ABC'): 'replace'}, {c['key']: 'replace'}, {c['key']: 'skip'}):
            self.assertIn('conflict', plan_year(2024, original, [new], choices))
        done = plan_year(2024, original, [new], {c['key']: 'keep_both'})
        self.assertEqual(done['rows'], [old, new]); self.assertEqual(original, [old])
        self.assertEqual(done['imported'], 1)

    def test_multiple_incoming_rows_require_separate_choices(self):
        incoming = [row(approval='A'), row(approval='B'), row(approval='C')]
        p = plan_year(2024, [], incoming, {})
        self.assertEqual(p['conflict']['incoming']['avgaskrav_tillagg'], 'B')
        choices = {p['conflict']['key']: 'keep_both'}
        p2 = plan_year(2024, [], incoming, choices)
        self.assertEqual(p2['conflict']['incoming']['avgaskrav_tillagg'], 'C')
        choices[p2['conflict']['key']] = 'keep_both'
        self.assertEqual(plan_year(2024, [], incoming, choices)['rows'], incoming)

    def test_exact_approval_selects_one_record_without_destroying_other_variants(self):
        old = [row(approval='A', typ='a'), row(approval='B', typ='b')]
        incoming = [row(approval='B', typ='updated')]
        c = plan_year(2024, old, incoming, {})['conflict']
        self.assertEqual(c['existing']['avgaskrav_tillagg'], 'B')
        done = plan_year(2024, old, incoming, {c['key']: 'replace'})
        self.assertEqual(done['rows'], [old[0], incoming[0]])

    def test_ambiguous_matching_approval_does_not_allow_arbitrary_overwrite(self):
        old = [row(approval='A', typ='1'), row(approval='A', typ='2')]
        c = plan_year(2024, old, [row(approval='A')], {})['conflict']
        self.assertEqual(c['allowed_actions'], ['keep_both', 'skip'])
        self.assertIn('conflict', plan_year(2024, old, [row(approval='A')], {c['key']: 'replace'}))

    def test_choices_are_bound_to_year_and_content(self):
        old = [row(approval='A')]; incoming = [row(approval='B')]
        c = plan_year(2024, old, incoming, {})['conflict']
        choices = {c['key']: 'keep_both'}
        self.assertIn('conflict', plan_year(2025, old, incoming, choices))
        self.assertIn('conflict', plan_year(2024, [row(approval='C')], incoming, choices))
        self.assertIn('conflict', plan_year(2024, old, [row(approval='D')], choices))

    def test_single_unknown_approval_offers_options_instead_of_guessing(self):
        c = plan_year(2024, [row(approval='')], [row(approval='B')], {})['conflict']
        self.assertIn('replace', c['allowed_actions'])
        self.assertIn('keep_both', c['allowed_actions'])


class DuplicateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.storage = VehicleDataStorage(Path(self.tmp.name))
        self.cache = VehicleCache(self.storage)
        self.storage.save_year(2024, [row(approval='A'), row(approval='B')])
        self.cache.load_year(2024)

    def test_single_record_lookups_refuse_ambiguous_vin(self):
        self.assertEqual(self.storage.find_by_vin3('ABC'), (None, None))
        self.assertIsNone(self.cache.find_by_vin3('ABC'))
        obj = SimpleNamespace(vehicle_storage=self.storage, vehicle_cache=self.cache)
        self.assertIsNone(Plugin.find_vehicle_by_vin_and_year(obj, 'ABC', 2024))
        self.assertEqual(len(self.storage.load_year(2024)), 2)

    def test_upsert_and_delete_cannot_mutate_ambiguous_records(self):
        obj = SimpleNamespace(vehicle_storage=self.storage, vehicle_cache=self.cache, VERSION='test', app=None)
        before = self.storage._year_path(2024).read_bytes()
        result = Plugin.upsert(obj, {'vin_kod': 'ABC', 'MODELYEAR': '2024', 'typ': 'bad'})
        self.assertFalse(result['success'])
        result = Plugin.delete(obj, 'ABC', 2024)
        self.assertFalse(result['success'])
        self.assertEqual(self.storage._year_path(2024).read_bytes(), before)

    def test_manual_duplicate_save_asks_and_cancel_preserves_file(self):
        tree = ast.parse(Path('plugins/main_gui/vehicle_registry_page.py').read_text())
        c = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VehicleDataPage')
        method = next(n for n in c.body if isinstance(n, ast.FunctionDef) and n.name == '_save_year_with_duplicate_confirmation')
        mod = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), ast.ClassDef(name='Page', bases=[], keywords=[], body=[method], decorator_list=[])], type_ignores=[]))
        buttons = SimpleNamespace(Yes=1, No=2)
        message = SimpleNamespace(StandardButton=buttons, question=Mock(return_value=buttons.No))
        env = {'QMessageBox': message}; exec(compile(mod, '<manual-confirm>', 'exec'), env)
        page = env['Page'](); page._storage = self.storage; page._autosave_timer = SimpleNamespace(stop=Mock())
        before = self.storage._year_path(2024).read_bytes()
        new_rows = self.storage.load_year(2024) + [row(approval='C')]
        self.assertFalse(page._save_year_with_duplicate_confirmation(2024, new_rows))
        self.assertEqual(self.storage._year_path(2024).read_bytes(), before)
        self.assertIn('Approval: C', message.question.call_args.args[2])
        message.question.return_value = buttons.Yes
        self.assertTrue(page._save_year_with_duplicate_confirmation(2024, new_rows))
        self.assertEqual(self.storage.load_year(2024), new_rows)


@unittest.skipIf(pd is None, 'pandas och openpyxl saknas')
class DuplicateExcelTests(unittest.TestCase):
    def test_excel_repeated_vin_asks_then_keeps_each_approval_and_no_writes_before_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / 'input.xlsx'
            with pd.ExcelWriter(path) as writer:
                pd.DataFrame({'VINCODE': ['ABC', 'ABC', 'ABC'], 'TYPE': ['A', 'B', 'C'], 'APPROVAL': ['a', 'b', 'c']}).to_excel(writer, sheet_name='2024', index=False)
            original = path.read_bytes()
            storage = VehicleDataStorage(root / 'registry')
            importer = ExcelModelImporter(storage, root / 'mappings')
            mapping = {'VINCODE': 'vin_kod', 'TYPE': 'typ', 'APPROVAL': 'avgaskrav_tillagg'}
            choices = {}
            for expected in ('b', 'c'):
                preview = importer.import_file(str(path), mapping, dry_run=True, conflict_resolutions=choices, save_mapping=False)
                self.assertTrue(preview['needs_resolution'])
                conflict = preview['conflicts'][0]
                self.assertEqual(conflict['incoming']['avgaskrav_tillagg'], expected)
                self.assertEqual(storage.list_years(), [])
                choices[conflict['key']] = 'keep_both'
            final = importer.import_file(str(path), mapping, conflict_resolutions=choices, save_mapping=False)
            self.assertTrue(final['success'], final)
            self.assertEqual([r['avgaskrav_tillagg'] for r in storage.load_year(2024)], ['a', 'b', 'c'])
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
