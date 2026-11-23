from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import types
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.dealer_pin import DealerPin

ROOT = Path(__file__).resolve().parents[1]


def load_color_module():
    package = types.ModuleType('PySide6'); package.__path__ = []
    qtcore = types.ModuleType('PySide6.QtCore'); qtcore.Qt = SimpleNamespace()
    qtgui = types.ModuleType('PySide6.QtGui')
    for name in ('QColor', 'QBrush', 'QFont'): setattr(qtgui, name, type(name, (), {}))
    widgets = types.ModuleType('PySide6.QtWidgets')
    for name in ('QAbstractItemView', 'QComboBox', 'QDialog', 'QDialogButtonBox', 'QFrame',
                 'QGridLayout', 'QGroupBox', 'QHBoxLayout', 'QLabel', 'QLineEdit', 'QMessageBox',
                 'QPushButton', 'QSplitter', 'QTableWidget', 'QTableWidgetItem', 'QVBoxLayout', 'QWidget', 'QHeaderView'):
        setattr(widgets, name, type(name, (), {}))
    name = 'colors_manager_test_module'
    spec = importlib.util.spec_from_file_location(name, ROOT / 'plugins/colors_manager/plugin.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'PySide6': package, 'PySide6.QtCore': qtcore,
                                  'PySide6.QtGui': qtgui, 'PySide6.QtWidgets': widgets, name: module}):
        spec.loader.exec_module(module)
    return module


class ColorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.module = load_color_module()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.colors = self.root / 'farger.json'; self.mappings = self.root / 'color_mappings.json'
        self.pin = DealerPin(self.root / '.js data/aterforsaljare_pin.json'); self.pin.create('123456')
        self.bus = SimpleNamespace(emit=Mock())
        self.service = self.module.ColorService(self.colors, self.mappings, self.bus, pin_provider=lambda: self.pin)

    def write(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def test_dispatch_pending_rows_are_blank_deduplicated_and_editable(self):
        self.write(self.colors, {'colors': [{'kod': 'x', 'namn': 'Vit', 'ts_kod': 'WIT', 'extra': 3}], 'metadata': 4})
        before = self.colors.read_bytes()
        self.service.load()
        result = self.service.add_dispatch_names([' Vit ', 'Red metallic', 'red metallic', ' Blue '])
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.affected_count, 2)
        rows = json.loads(self.colors.read_text())
        self.assertEqual(rows['metadata'], 4)
        self.assertEqual(rows['colors'][0]['extra'], 3)
        self.assertEqual([r['kod'] for r in rows['colors'][1:]], ['', ''])
        self.assertTrue(all(not r['ts_kod'] for r in rows['colors'][1:]))
        self.assertIn(before, [p.read_bytes() for p in (self.root / 'backup_farger').iterdir()])
        self.service.load()
        red = self.service.get_by_name('red metallic')
        self.assertFalse(self.service.lookup_ts_code(red.name))
        self.assertFalse(self.service.update(red.storage_key, ts_code='ROT').success)
        self.assertTrue(self.service.update(red.storage_key, ts_code='ROT', pin='123456').success)
        self.service.load()
        red = self.service.get_by_name('red metallic')
        self.assertEqual(red.code, '')
        self.assertEqual(red.ts_code, 'ROT')
        self.assertTrue(self.service.update(red.storage_key, new_code='300', pin='123456').success)
        self.service.load()
        self.assertEqual(self.service.get_by_code('300').name, 'Red metallic')
        self.assertEqual(self.service.add_dispatch_names(['RED METALLIC']).affected_count, 0)

    def test_dispatch_snapshot_and_corrupt_data_fail_closed(self):
        self.service.load()
        self.mappings.write_text('{invalid')
        self.assertFalse(self.service.add_dispatch_names(['Blue']).success)
        self.assertFalse(self.colors.exists())
        self.assertEqual(self.mappings.read_text(), '{invalid')

    def test_real_plugin_lifecycle_with_qt_stubs(self):
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
               'PYTHONPATH': str(ROOT) + os.pathsep + os.environ.get('PYTHONPATH', '')}
        result = subprocess.run([sys.executable, str(ROOT / 'tests/color_lifecycle_stub.py')],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('color lifecycle OK', result.stdout)

    def test_shared_pin_required_and_no_default_bypass(self):
        self.assertEqual(self.service.load(), 0)
        self.assertFalse(self.service.add('1', 'Vit').success)
        self.assertFalse(self.service.add('1', 'Vit', pin='999999').success)
        self.assertFalse(self.service.add_mapping('vit', 'WIT', pin='999999'))
        self.assertFalse(self.colors.exists()); self.assertFalse(self.mappings.exists())
        self.assertTrue(self.service.add('1', 'Vit', 'WIT', pin='123456').success)
        self.assertFalse(self.service.update('1', name='Ändrad').success)
        self.assertFalse(self.service.delete('1').success)
        self.assertFalse(self.service.save())
        self.assertEqual(self.service.get_by_code('1').name, 'Vit')
        no_provider = self.module.ColorService(self.colors, self.mappings)
        self.assertFalse(no_provider.delete('1', pin='123456').success)

    def test_unknown_fields_wrapper_and_independent_mappings_are_preserved(self):
        source = {'colors': [{'kod': '01', 'namn': 'White', 'ts_kod': 'WIT', 'extra': {'a': 2}}], 'metadata': {'id': 9}}
        mapping = {'mappings': {'White': 'WIT', 'Custom': 'ROT'}, 'unknown': {'keep': 7}}
        self.write(self.colors, source); self.write(self.mappings, mapping)
        original = self.colors.read_bytes(); mapping_bytes = self.mappings.read_bytes()
        self.service.load()
        self.assertTrue(self.service.update('01', name='Changed', pin='123456').success)
        after = json.loads(self.colors.read_text())
        self.assertEqual(after['metadata'], source['metadata'])
        self.assertEqual(after['colors'][0]['extra'], {'a': 2})
        self.assertEqual(self.mappings.read_bytes(), mapping_bytes)
        self.assertIn(original, [p.read_bytes() for p in (self.root / 'backup_farger').iterdir()])
        self.assertTrue(self.service.add_mapping('Other', 'BLA', pin='123456'))
        after_mapping = json.loads(self.mappings.read_text())
        self.assertEqual(after_mapping['unknown'], {'keep': 7})
        self.assertEqual(after_mapping['mappings']['White'], 'WIT')
        self.assertTrue(self.service.delete('01', pin='123456').success)
        self.assertIn('White', json.loads(self.mappings.read_text())['mappings'])

    def test_bad_duplicate_and_conflicting_data_never_overwritten(self):
        candidates = [b'{invalid', b'', b'[{"kod":"x","kod":"y","namn":"A"}]', json.dumps([{'kod':'x','namn':'A'}, None]).encode(),
                      json.dumps([{'kod':'x','namn':'A'}, {'kod':'X','namn':'B'}]).encode(),
                      json.dumps([{'kod':'x','code':'other','namn':'A'}]).encode()]
        for content in candidates:
            with self.subTest(content=content):
                self.colors.write_bytes(content)
                with self.assertRaises(Exception): self.service.load()
                self.assertFalse(self.service.add('B', 'Blå', pin='123456').success)
                self.assertEqual(self.colors.read_bytes(), content)
        self.colors.unlink(); self.mappings.write_text('{broken')
        with self.assertRaises(Exception): self.service.load()
        self.assertFalse(self.service.add('1', 'A', pin='123456').success)
        self.assertFalse(self.colors.exists())
        self.mappings.write_text('{"red": "ROT"}')  # okänt format får inte misstolkas som tomt
        before = self.mappings.read_bytes()
        with self.assertRaises(ValueError): self.service.load()
        self.assertFalse(self.service.add_mapping('blue', 'BLA', pin='123456'))
        self.assertEqual(self.mappings.read_bytes(), before)

    def test_concurrent_change_and_backup_failure_leave_memory_and_file_unchanged(self):
        self.write(self.colors, [{'kod': '1', 'namn': 'Old', 'extra': 5}]); self.service.load()
        self.write(self.colors, [{'kod': '1', 'namn': 'External'}]); before = self.colors.read_bytes()
        result = self.service.update('1', name='Changed', pin='123456')
        self.assertFalse(result.success); self.assertEqual(self.colors.read_bytes(), before)
        self.assertEqual(self.service.get_by_code('1').name, 'Old')
        self.service.load(); before = self.colors.read_bytes()
        with patch('core.color_storage.tempfile.mkstemp', side_effect=OSError('disk')):
            result = self.service.delete('1', pin='123456')
        self.assertFalse(result.success); self.assertEqual(self.colors.read_bytes(), before)
        self.assertEqual(self.service.get_by_code('1').name, 'External')

    def test_unchanged_rows_retain_exact_fields_across_multiple_saves(self):
        rows = [{'kod': '1', 'namn': 'One'}, {'code': ' 02 ', 'name': ' Two ', 'ts_code': 'bla', 'unrecognized': ['x']}]
        self.colors.write_text('// Keep this comment\n' + json.dumps(rows))
        self.service.load()
        self.assertTrue(self.service.update('1', name='Updated', pin='123456').success)
        self.assertTrue(self.service.add('3', 'Three', pin='123456').success)
        self.assertTrue(self.colors.read_text().startswith('// Keep this comment'))
        from core.color_storage import decode_snapshot
        result = decode_snapshot(self.colors.read_bytes(), [])
        self.assertEqual(result[1], rows[1])
        self.assertEqual(result[0]['namn'], 'Updated')

    def test_edit_color_code_checks_pin_and_duplicates(self):
        self.service.load()
        self.assertTrue(self.service.add('1', 'One', pin='123456').success)
        self.assertTrue(self.service.add('2', 'Two', pin='123456').success)
        before = self.colors.read_bytes()
        self.assertFalse(self.service.update('1', new_code='2', pin='123456').success)
        self.assertFalse(self.service.update('1', new_code='3', pin='999999').success)
        self.assertEqual(self.colors.read_bytes(), before)
        self.assertTrue(self.service.update('1', new_code='3', pin='123456').success)
        self.assertIsNone(self.service.get_by_code('1'))
        self.assertEqual(self.service.get_by_code('3').name, 'One')
        self.assertEqual(len(self.service.get_all()), 2)

    def test_mapping_removal_is_pin_gated_and_preserves_other_fields(self):
        self.write(self.mappings, {'mappings': {'Mixed Name': 'ROT', 'Other': 'BLA'}, 'extra': 'keep'})
        self.service.load()
        before = self.mappings.read_bytes()
        self.assertFalse(self.service.delete_mapping('mixed name', pin='000000'))
        self.assertEqual(self.mappings.read_bytes(), before)
        self.assertTrue(self.service.delete_mapping('MIXED NAME', pin='123456'))
        result = json.loads(self.mappings.read_text())
        self.assertEqual(result, {'mappings': {'Other': 'BLA'}, 'extra': 'keep'})

    def test_lookup_never_returns_guesses_and_conflicts_are_blocked(self):
        self.service.load()
        guess = self.service.lookup_ts_code_detailed('red metallic')
        self.assertTrue(guess.ts_code)
        self.assertNotEqual(guess.match_type, 'exact')
        self.assertEqual(self.service.lookup_ts_code('red metallic'), '')
        self.assertEqual(len(self.service.get_unmapped_sample(['red metallic'])), 1)
        self.assertTrue(self.service.add_mapping('red metallic', 'ROT', pin='123456'))
        self.assertEqual(self.service.lookup_ts_code('red metallic'), 'ROT')
        self.assertFalse(self.service.add_mapping('red metallic', 'BLA', pin='123456'))
        self.assertEqual(self.service.lookup_ts_code('red metallic'), 'ROT')
        self.assertTrue(self.service.add('1', 'red metallic', 'BLA', pin='123456').success)
        self.assertEqual(self.service.lookup_ts_code('red metallic'), '')
        self.assertEqual(self.service.lookup_ts_code_detailed('red metallic').match_type, 'conflict')
        self.assertEqual(self.service.get_statistics()['conflicts'], 1)

    def test_search_and_external_mutation_cannot_write_behind_service(self):
        self.service.load()
        self.assertTrue(self.service.add('1', 'Colour', manufacturer='BMW', hex_value='#ffffee', pin='123456').success)
        self.assertEqual(len(self.service.search('ffffee')), 1)
        self.assertEqual(len(self.service.search('bmw')), 1)
        self.assertTrue(self.service.update('1', ts_code='BLA', pin='123456').success)
        self.assertEqual(len(self.service.search('blå')), 1)
        returned = self.service.get_by_code('1'); returned.name = 'Bad'
        self.assertEqual(self.service.get_by_code('1').name, 'Colour')
        shown = self.service.get_by_code('1')
        self.assertTrue(self.service.update('1', name='New', pin='123456').success)
        self.assertFalse(self.service.delete('1', pin='123456', expected_color=shown).success)
        self.assertEqual(self.service.get_by_code('1').name, 'New')

    def test_plugin_resolves_existing_dealer_pin(self):
        plugin = object.__new__(self.module.Plugin)
        plugin.app = SimpleNamespace(dealers=SimpleNamespace(dealer_pin=lambda: self.pin))
        self.assertIs(plugin._shared_dealer_pin(), self.pin)
        plugin.app = SimpleNamespace()
        with self.assertRaises(Exception): plugin._shared_dealer_pin()


class ColorWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.mod = load_color_module()

    def test_table_populates_without_row_mixing_and_read_only(self):
        class Item:
            def __init__(self, text): self.text = text; self.role_data = {}; self.flag = 7
            def setData(self, role, value): self.role_data[role] = value
            def setToolTip(self, text): self.tooltip = text
            def flags(self): return self.flag
            def setFlags(self, flag): self.flag = flag
        class Table:
            def __init__(self): self.enabled = True; self.rows = []; self.transitions = []
            def isSortingEnabled(self): return self.enabled
            def setSortingEnabled(self, value): self.enabled = value; self.transitions.append(value)
            def setRowCount(self, count): self.rows = []
            def rowCount(self): return len(self.rows)
            def insertRow(self, index): self.rows.append([None]*6)
            def setItem(self, row, col, item):
                assert not self.enabled
                self.rows[row][col] = item
        one = self.mod.Color('1', 'First', 'WIT', 'BMW', '#123456')
        two = self.mod.Color('2', 'Second', 'BLA', 'Volvo', '#000000')
        table = Table()
        view = SimpleNamespace(search_input=SimpleNamespace(text=lambda: ''), table=table,
                               service=SimpleNamespace(search=lambda q: [one, two], get_all_mappings=lambda: {'first': 'ROT'}),
                               _auto_color_columns=False, count_label=SimpleNamespace(setText=Mock()))
        qt = SimpleNamespace(ItemDataRole=SimpleNamespace(UserRole=100), ItemFlag=SimpleNamespace(ItemIsEditable=2))
        with patch.object(self.mod, 'QTableWidgetItem', Item), patch.object(self.mod, 'Qt', qt):
            self.mod.ColorsWidget._populate_table(view)
        self.assertEqual(table.transitions, [False, True])
        self.assertEqual([item.text for item in table.rows[0]][:3], ['1', 'First', 'WIT'])
        self.assertIn('Motstridig', table.rows[0][3].text)
        self.assertEqual(table.rows[1][0].role_data[100], '2')
        self.assertEqual(table.rows[0][4].tooltip, 'BMW')
        self.assertEqual(table.rows[0][0].flag & 2, 0)

    def test_mapping_table_lists_saved_and_suggestions_without_auto_selection(self):
        class Item:
            def __init__(self, text): self.text = text
            def setToolTip(self, text): self.tooltip = text
        class Combo:
            def __init__(self): self.items = []; self.currentIndexChanged = SimpleNamespace(connect=Mock()); self.index = 0
            def addItem(self, label, value): self.items.append((label, value))
            def findData(self, value): return next((i for i, item in enumerate(self.items) if item[1] == value), -1)
            def setCurrentIndex(self, index): self.index = index
            def currentData(self): return self.items[self.index][1]
        class Table:
            def __init__(self): self.rows = []
            def setRowCount(self, count): self.rows = []
            def rowCount(self): return len(self.rows)
            def insertRow(self, index): self.rows.append([None]*5)
            def setItem(self, row, col, item): self.rows[row][col] = item
            def setCellWidget(self, row, col, combo): self.rows[row][col] = combo
        exact = self.mod.ColorLookupResult('ROT', 1, 'exact', 'saved')
        guess = self.mod.ColorLookupResult('BLA', .85, 'keyword', 'new')
        service = SimpleNamespace(get_mapping_display=lambda: {'Saved': 'ROT'}, lookup_ts_code_detailed=lambda name: exact)
        table = Table()
        view = SimpleNamespace(service=service, _unmapped=[('New', guess)], unmapped_table=table, search_input=SimpleNamespace(text=lambda: ''), _mapping_drafts={'saved': 'BLA'})
        with patch.object(self.mod, 'QTableWidgetItem', Item), patch.object(self.mod, 'QComboBox', Combo):
            self.mod.ColorsWidget._populate_unmapped_table(view)
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(table.rows[0][0].text, 'Saved')
        self.assertEqual(table.rows[0][1].text, 'ROT')
        self.assertEqual(table.rows[1][2].text, 'BLA')
        self.assertEqual(table.rows[1][4].items[0][1], '')  # användaren måste välja själv
        self.assertEqual(table.rows[1][4].index, 0)
        self.assertEqual(table.rows[0][4].currentData(), 'BLA')  # ett tidigare aktivt val behålls

    def test_canceled_pin_never_saves_color(self):
        result = self.mod.Color('1', 'Old', 'WIT')
        dialog = SimpleNamespace(exec=lambda: 1, get_data=lambda: {'code': '1', 'name': 'New'})
        view = SimpleNamespace(table=SimpleNamespace(currentRow=lambda: 0, item=lambda r,c: SimpleNamespace(data=lambda role: '1')),
                               service=SimpleNamespace(get_by_code=lambda code: result, update=Mock()), refresh=Mock())
        pin = types.ModuleType('plugins.main_gui.dialogs.dealer_pin'); pin.request_pin = lambda *args, **kwargs: None
        qt = SimpleNamespace(ItemDataRole=SimpleNamespace(UserRole=100))
        with patch.object(self.mod, 'ColorDialog', return_value=dialog), patch.object(self.mod, 'QDialog', SimpleNamespace(Accepted=1)), \
             patch.object(self.mod, 'Qt', qt), patch.dict(sys.modules, {'plugins.main_gui.dialogs.dealer_pin': pin}):
            self.mod.ColorsWidget._on_edit(view)
        view.service.update.assert_not_called(); view.refresh.assert_not_called()


class LegacyColorImportSafetyTests(unittest.TestCase):
    def test_old_import_store_is_blocked(self):
        source = ast.parse((ROOT / 'plugins/color_import/plugin.py').read_text())
        plugin = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'Plugin')
        method = next(n for n in plugin.body if isinstance(n, ast.FunctionDef) and n.name == '_store_color')
        cls = ast.ClassDef(name='P', bases=[], keywords=[], body=[method], decorator_list=[])
        tree = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[]))
        env = {}; exec(compile(tree, '<old-import>', 'exec'), env)
        result = env['P']()._store_color('1', 'Old', 'BLA')
        self.assertFalse(result[0]); self.assertIn('spärrad', result[1])


if __name__ == '__main__': unittest.main()
