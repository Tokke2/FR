from __future__ import annotations

import ast
import functools
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.dealer_storage import DealerStorage
from core.dealer_pin import DealerPin, PIN_FILENAME
from core.dealer_fields import FIELDS

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/dealers_manager/plugin.py'


def isolated(path, class_name, methods, env):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    source = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == class_name)
    nodes = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in methods]
    assert len(nodes) == len(methods), (methods, [n.name for n in nodes])
    cls = ast.ClassDef(name='Isolated', bases=[], keywords=[], body=nodes, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[
        ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[]))
    exec(compile(module, str(path), 'exec'), env)
    return env['Isolated']


METHODS = {'_storage', 'dealer_pin', 'load_from_json', 'save_to_json', 'get_all_dealers', '_dn',
           'get_by_dn', 'add_dealer', 'update_dealer', 'delete_dealer',
           'import_from_excel', '_merge_dealers', 'create_widget'}


class DealerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / '.js data' / 'aterforsaljare.json'
        self.env = {'DealerStorage': DealerStorage, 'DealerPin': DealerPin, 'PIN_FILENAME': PIN_FILENAME, 'FIELDS': FIELDS, '_NO_SNAPSHOT': object(),
                    '_log': logging.getLogger('dealer.test')}
        cls = isolated(PLUGIN, 'Plugin', METHODS, self.env)
        self.plugin = cls()
        self.plugin._json_path = self.path
        self.plugin._emit_safe = Mock()
        self.plugin.dealer_pin().create('123456')
        for method in ('save_to_json', 'add_dealer', 'update_dealer', 'delete_dealer'):
            setattr(self.plugin, method, functools.partial(getattr(self.plugin, method), pin='123456'))

    def write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def test_pin_blocks_all_plugin_writes(self):
        self.write([{'dealer_number': '001', 'namn': 'Existing'}])
        before = self.path.read_bytes()
        self.assertFalse(self.plugin.add_dealer({'dealer_number': '002', 'namn': 'New'}, pin='000000'))
        self.assertFalse(self.plugin.update_dealer('001', {'namn': 'Changed'}, pin='000000'))
        self.assertFalse(self.plugin.delete_dealer('001', pin='000000'))
        self.assertFalse(self.plugin.save_to_json([], pin='000000'))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.path.parent / 'backup_aterforsaljare').exists())

    def test_extended_fields_are_saved_and_untouched_fields_preserved(self):
        self.write([{'dealer_number': '001', 'namn': 'Name', 'adress': 'Old', 'land': 'SE', 'extra': 4}])
        self.assertTrue(self.plugin.update_dealer('001', {'namn': 'New', 'adress': 'Street', 'postnummer': '001 23'}))
        data = self.plugin.load_from_json()[0]
        self.assertEqual((data['adress'], data['postnummer'], data['land'], data['extra']), ('Street', '001 23', 'SE', 4))
        self.assertTrue(self.plugin.add_dealer({'dealer_number': '002', 'namn': 'Company', 'telefon_arbete': '0700', 'ort': 'Kista'}))
        self.assertEqual(self.plugin.get_by_dn('002')['telefon_arbete'], '0700')

    def test_dealer_number_change_requires_unique_number_and_pin(self):
        self.write([{'dealer_number': '001', 'namn': 'First', 'extra': 1},
                    {'dealer_number': '002', 'namn': 'Second'}])
        before = self.path.read_bytes()
        self.assertFalse(self.plugin.update_dealer('001', {'dealer_number': '002', 'namn': 'First'}))
        self.assertFalse(self.plugin.update_dealer('001', {'dealer_number': '003', 'namn': 'First'}, pin='999999'))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(self.plugin.update_dealer('001', {'dealer_number': '003', 'namn': 'First'}))
        self.assertEqual(self.plugin.get_by_dn('003')['extra'], 1)
        self.assertIsNone(self.plugin.get_by_dn('001'))

    def test_real_plugin_loader_lifecycle_with_qt_stubs(self):
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
               'PYTHONPATH': str(ROOT) + os.pathsep + os.environ.get('PYTHONPATH', '')}
        result = subprocess.run([sys.executable, str(ROOT / 'tests/dealer_lifecycle_stub.py')],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('dealer lifecycle OK', result.stdout)

    def test_create_widget_exposes_dealer_page_to_main_gui(self):
        widget = object()
        self.plugin.register_ui = Mock(return_value=widget)
        self.assertIs(self.plugin.create_widget('window'), widget)
        self.plugin.register_ui.assert_called_once_with('window')
        self.plugin._json_path = None
        with self.assertRaises(RuntimeError): self.plugin.create_widget('window')

    def test_main_gui_selects_dealer_widget(self):
        page = object()
        plugin = SimpleNamespace(create_widget=Mock(return_value=page))
        env = {'get_plugin_safe': lambda app, name: plugin if name == 'dealers_manager' else None,
               '_log': logging.getLogger('dealer.test')}
        cls = isolated(ROOT / 'plugins/main_gui/plugin.py', 'MainWindow', {'_init_other_pages'}, env)
        window = cls(); window.app = object(); window.pages = []; window.page_widgets = {}
        window._add_placeholder_page = Mock()
        window._init_other_pages()
        self.assertIs(window.page_widgets['🏢 Återförsäljare'], page)
        plugin.create_widget.assert_called_once_with(window)

    def test_add_edit_delete_backup_and_preserve_unknown_fields(self):
        original = [{'dealer_number': '001', 'namn': 'Älvsjö', 'orgnr': '1', 'extra': {'a': 3}},
                    {'dn': '002', 'namn': 'Malmö', 'other': True}]
        self.write(original)
        original_bytes = self.path.read_bytes()
        self.assertTrue(self.plugin.add_dealer({'dealer_number': '003', 'namn': 'Norr'}))
        copies = sorted(self.path.parent.joinpath('backup_aterforsaljare').iterdir())
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), original_bytes)
        self.assertTrue(self.plugin.update_dealer('001', {'namn': 'Älvsjö ny', 'orgnr': '2'}))
        data = self.plugin.load_from_json()
        self.assertEqual(data[0]['extra'], {'a': 3})
        self.assertEqual(data[1], original[1])
        self.assertTrue(self.plugin.delete_dealer('003'))
        self.assertEqual(len(self.plugin.load_from_json()), 2)
        self.assertEqual(len(list(copies[0].parent.iterdir())), 3)

    def test_first_version_is_backed_up(self):
        self.assertTrue(self.plugin.add_dealer({'dealer_number': 'a', 'namn': 'Test'}))
        backup = next((self.path.parent / 'backup_aterforsaljare').iterdir())
        self.assertEqual(backup.read_bytes(), self.path.read_bytes())

    def test_corrupt_and_partial_data_never_overwritten(self):
        for invalid in ('', '{bad', '[{"namn":"valid"}, null]', '123'):
            with self.subTest(invalid=invalid):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(invalid)
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    self.plugin.load_from_json()
                self.assertFalse(self.plugin.add_dealer({'dealer_number': '1', 'namn': 'T'}))
                self.assertFalse(self.plugin.save_to_json([]))
                self.assertEqual(self.path.read_text(), invalid)

    def test_duplicate_numbers_never_modified_or_deleted_as_group(self):
        data = [{'dealer_number': 'X', 'namn': 'A'}, {'dn': 'x', 'namn': 'B'}]
        self.write(data)
        self.assertIsNone(self.plugin.get_by_dn('x'))
        self.assertFalse(self.plugin.update_dealer('x', {'namn': 'C'}))
        self.assertFalse(self.plugin.delete_dealer('x'))
        self.assertFalse(self.plugin.add_dealer({'dealer_number': 'x', 'namn': 'C'}))
        self.assertEqual(json.loads(self.path.read_text()), data)

    def test_backup_failure_or_changed_file_aborts_write(self):
        self.write([{'dn': '1', 'namn': 'Old'}])
        records, expected = DealerStorage(self.path).snapshot()
        self.write([{'dn': '1', 'namn': 'External'}])
        with self.assertRaises(ValueError): DealerStorage(self.path).save(records, expected)
        self.assertEqual(json.loads(self.path.read_text())[0]['namn'], 'External')
        before = self.path.read_bytes()
        with patch('core.dealer_storage.tempfile.mkstemp', side_effect=OSError('disk')):
            self.assertFalse(self.plugin.add_dealer({'dn': '2', 'namn': 'New'}))
        self.assertEqual(self.path.read_bytes(), before)

    def test_dialog_snapshot_prevents_editing_or_deleting_changed_row(self):
        old = {'dealer_number': '1', 'namn': 'Old'}
        self.write([old])
        shown = self.plugin.get_by_dn('1')
        self.write([{'dealer_number': '1', 'namn': 'New'}])
        self.assertFalse(self.plugin.update_dealer('1', {'namn': 'Overwrite'}, expected_record=shown))
        self.assertFalse(self.plugin.delete_dealer('1', expected_record=shown))
        self.assertEqual(self.plugin.load_from_json()[0]['namn'], 'New')

    def test_excel_import_is_blocked_including_private_merge(self):
        self.write([{'dealer_number': '1', 'namn': 'Existing'}])
        before = self.path.read_bytes()
        self.assertFalse(self.plugin.import_from_excel('input.xlsx')['success'])
        with self.assertRaises(RuntimeError): self.plugin._merge_dealers([{'dealer_number': '1', 'namn': 'New'}])
        self.assertEqual(self.path.read_bytes(), before)

    def test_all_contact_fields_display_as_columns(self):
        qt = SimpleNamespace(ItemDataRole=SimpleNamespace(DisplayRole=0, TextAlignmentRole=1, ToolTipRole=2),
                             AlignmentFlag=SimpleNamespace(AlignCenter=1, AlignLeft=2, AlignVCenter=4))
        cls = isolated(PLUGIN, 'DealersTableModel', {'data', 'columnCount'}, {'Qt': qt, 'QModelIndex': lambda: None})
        cls.KEYS = list(FIELDS); cls.HEADERS = list(FIELDS.values()); cls.COL_DN = 0
        model = cls(); model._data = [{'dn': '007', 'namn': 'Firma', 'ansvarig': 'Anna',
                                       'adress': 'Gatan 1', 'postnummer': '01234', 'ort': 'Kista',
                                       'land': 'SE', 'telefon_bostad': '012', 'telefon_arbete': '034', 'adress': 'Gatan 1\nVåning 2'}]
        self.assertEqual(model.columnCount(), len(FIELDS))
        values = {}
        for column, field in enumerate(FIELDS):
            index = SimpleNamespace(isValid=lambda: True, row=lambda: 0, column=lambda: column)
            values[field] = model.data(index)
        self.assertEqual(values['dealer_number'], '007')
        self.assertEqual(values['postnummer'], '01234')
        self.assertEqual(values['telefon_arbete'], '034')
        self.assertEqual(values['ansvarig'], 'Anna')
        address = list(FIELDS).index('adress')
        index = SimpleNamespace(isValid=lambda: True, row=lambda: 0, column=lambda: address)
        self.assertEqual(model.data(index, 0), 'Gatan 1 ↵ Våning 2')
        self.assertEqual(model.data(index, 2), 'Gatan 1\nVåning 2')

    def test_search_and_refresh_are_bound_to_existing_rows(self):
        cls = isolated(PLUGIN, 'DealersWidget', {'refresh', '_on_search'}, {'_log': logging.getLogger('dealer.test')})
        widget = cls(); widget.plugin = self.plugin
        widget._model = SimpleNamespace(set_data=Mock(), rowCount=lambda: 2)
        widget._proxy = SimpleNamespace(setFilterFixedString=Mock(), rowCount=lambda: 1)
        widget._status_label = SimpleNamespace(setText=Mock())
        widget._count_label = SimpleNamespace(setText=Mock())
        widget._search_input = SimpleNamespace(text=lambda: ' malmö ')
        self.write([{'namn': 'Malmö'}, {'namn': 'Uppsala'}])
        widget.refresh()
        widget._model.set_data.assert_called_once()
        widget._proxy.setFilterFixedString.assert_called_once_with('malmö')
        widget._count_label.setText.assert_called_with('1 av 2 återförsäljare')
        self.path.write_text('{bad')
        widget.refresh()
        self.assertEqual(widget._model.set_data.call_count, 1)
        self.assertIn('Fel vid laddning', widget._status_label.setText.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
