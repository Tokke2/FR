from __future__ import annotations

import ast
import copy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from plugins.vehicle_registry.plugin import VehicleDataStorage

PAGE = Path('plugins/main_gui/vehicle_registry_page.py')


def isolated(class_name, methods, extra=None):
    tree = ast.parse(PAGE.read_text(encoding='utf-8'))
    original = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    selected = [node for node in original.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    assert len(selected) == len(methods)
    cls = ast.ClassDef(name='Isolated', bases=[], keywords=[], body=selected, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[
        ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls,
    ], type_ignores=[]))
    env = {'copy': copy, 'QLineEdit': LineEdit, 'QComboBox': Combo}
    env.update(extra or {})
    exec(compile(module, str(PAGE), 'exec'), env)
    return env['Isolated']


class LineEdit:
    def __init__(self, value=''): self.value = value
    def text(self): return self.value
    def setText(self, value): self.value = value


class Combo:
    def __init__(self, items=()): self.items = list(items); self.index = 0
    def currentText(self): return self.items[self.index]
    def findText(self, text): return self.items.index(text) if text in self.items else -1
    def addItem(self, text): self.items.append(text)
    def setCurrentIndex(self, index): self.index = index


class RegistrySafetyTests(unittest.TestCase):
    def test_vin_container_does_not_replace_vin_input(self):
        class Group:
            def __init__(self, title): pass
            def setStyleSheet(self, style): pass
        class Layout:
            def __init__(self, group): pass
            def setLabelAlignment(self, align): pass
            def setSpacing(self, spacing): pass
            def addRow(self, label, widget): pass
        cls = isolated('VehicleForm', ['_create_group'], {
            'QGroupBox': Group, 'QFormLayout': Layout,
            'Styles': SimpleNamespace(GROUP_BOX=''),
            'Qt': SimpleNamespace(AlignmentFlag=SimpleNamespace(AlignLeft=1, AlignVCenter=2)),
        })
        form = cls(); form._inputs = {}
        vin, container = LineEdit(), object()
        def create_field(key, hint):
            form._inputs[key] = vin
            return container
        form._create_field = create_field
        form._create_group('VIN', [('vin_kod', 'VIN', '')])
        self.assertIs(form._inputs['vin_kod'], vin)

    def test_unedited_and_unknown_data_are_preserved_even_if_display_was_truncated(self):
        cls = isolated('VehicleForm', ['get_data', 'load_data', '_on_modified'])
        form = cls()
        form._inputs = {'vin_kod': LineEdit(), 'typ': LineEdit(), 'bransle1': Combo(['', 'BENSIN'])}
        form._edited_fields = set(); form._loading = False
        form.data_modified = SimpleNamespace(emit=Mock())
        original = {'vin_kod': 'ABC', 'typ': 'mycket långt originalvärde', 'bransle1': 'GAS', 'unmapped': {'a': 3}}
        form.load_data(original)
        self.assertEqual(form._inputs['bransle1'].currentText(), 'GAS')
        form._inputs['typ'].value = 'truncated'  # e.g. by a widget length constraint
        self.assertEqual(form.get_data(), original)
        form._inputs['vin_kod'].value = 'XYZ'
        form._on_modified('vin_kod')
        self.assertEqual(form.get_data(), {**original, 'vin_kod': 'XYZ'})
        self.assertEqual(original['vin_kod'], 'ABC')
        form.data_modified.emit.assert_called_once()

    def test_no_vehicle_silently_omitted_when_vin_missing(self):
        cls = isolated('YearTab', ['get_all_data'])
        tab = cls(); tab._vehicles = [{}, {}]
        tab._forms = {'0': SimpleNamespace(get_data=lambda: {'vin_kod': 'ABC'}),
                      '1': SimpleNamespace(get_data=lambda: {'typ': 'x'})}
        with self.assertRaisesRegex(ValueError, 'VIN'):
            tab.get_all_data()
        del tab._forms['1']
        with self.assertRaisesRegex(ValueError, 'formulär'):
            tab.get_all_data()

    def test_rebuilding_list_captures_unsaved_edits(self):
        cls = isolated('YearTab', ['_capture_edited_forms', '_add_vehicle'])
        tab = cls(); tab._vehicles = [{'vin_kod': 'ABC', 'typ': 'old'}]
        tab._forms = {'0': SimpleNamespace(get_data=lambda: {'vin_kod': 'ABC', 'typ': 'new'})}
        tab._populate_list = Mock(); tab.select_row = Mock()
        tab._on_modified_callback = Mock(); tab.year = 2024
        tab._add_vehicle({'vin_kod': 'DEF'})
        self.assertEqual(tab._vehicles, [{'vin_kod': 'ABC', 'typ': 'new'}, {'vin_kod': 'DEF'}])
        # Den nya raden markeras via tabellen, inte via en lista.
        tab.select_row.assert_called_once_with(1)

    def test_first_vehicle_is_selected_after_loading_finishes(self):
        class Form:
            """Platshållare – formuläret byggs av VehicleForm i den riktiga vyn."""

            def __init__(self, vehicle, app=None):
                self.data_modified = SimpleNamespace(connect=lambda callback: None)

            def enable_editing(self, value):
                pass

        cls = isolated('YearTab', ['_populate_list'], {'VehicleForm': Form})
        tab = cls(); tab._vehicles = [{'vin_kod': 'ABC'}]; tab._forms = {}
        tab._table = SimpleNamespace(setRowCount=Mock(), selectRow=Mock())
        tab._clear_form_panel = Mock(); tab._add_table_row = Mock()
        tab._lbl_count = SimpleNamespace(setText=Mock()); tab._empty_label = SimpleNamespace(hide=Mock())
        tab._active_filters = []
        tab._capture_edited_forms = Mock()
        tab._load_table_profile = Mock(); tab._update_summary = Mock()
        tab._visible_vehicles = lambda: list(tab._vehicles)

        tab._app = None
        tab._editing = True
        def show():
            self.assertFalse(tab._loading)
        tab._on_table_selection_changed = Mock(side_effect=show)
        tab._populate_list()
        tab._on_table_selection_changed.assert_called_once()
        tab._table.selectRow.assert_called_once_with(0)

    def test_import_is_blocked_while_forms_have_unsaved_edits(self):
        dialog = SimpleNamespace(warning=Mock())
        cls = isolated('VehicleDataPage', ['_import_from_excel'], {'QMessageBox': dialog})
        page = cls(); page._modified = {2024}
        page._import_from_excel()
        dialog.warning.assert_called_once()

    def test_refresh_never_reloads_unsaved_year(self):
        cls = isolated('VehicleDataPage', ['refresh_all'])
        dirty, clean = SimpleNamespace(refresh=Mock()), SimpleNamespace(refresh=Mock())
        page = cls(); page._tabs = {2023: dirty, 2024: clean}; page._modified = {2023}
        page.refresh_all()
        dirty.refresh.assert_not_called()
        clean.refresh.assert_called_once()

    def test_close_requires_confirmation_for_each_unsaved_year(self):
        cls = isolated('VehicleDataPage', ['confirm_close'])
        page = cls(); page._modified = {2023, 2024}; page._tabs = {2023: object(), 2024: object()}
        page._handle_unsaved_changes = Mock(side_effect=[True, False])
        self.assertFalse(page.confirm_close())
        self.assertEqual(page._handle_unsaved_changes.call_count, 2)
        page._handle_unsaved_changes = Mock(return_value=True)
        self.assertTrue(page.confirm_close())

    def test_discard_then_cancel_leaves_discarded_year_reloaded(self):
        buttons = SimpleNamespace(Save=1, Discard=2, Cancel=4)
        dialog = SimpleNamespace(question=Mock(return_value=buttons.Discard), StandardButton=buttons, warning=Mock())
        cls = isolated('VehicleDataPage', ['_handle_unsaved_changes'], {'QMessageBox': dialog, '_log': Mock()})
        page = cls(); page._modified = {2024}; page._storage = SimpleNamespace(save_year=Mock())
        page._update_tab_title = Mock()
        tab = SimpleNamespace(refresh=Mock())
        self.assertTrue(page._handle_unsaved_changes(2024, tab))
        tab.refresh.assert_called_once()
        page._storage.save_year.assert_not_called()
        self.assertEqual(page._modified, set())

    def test_autosave_preserves_vin_and_unknown_fields(self):
        form_cls = isolated('VehicleForm', ['get_data'])
        year_cls = isolated('YearTab', ['get_all_data'])
        page_cls = isolated('VehicleDataPage', ['_do_autosave'], {'_log': Mock()})
        with tempfile.TemporaryDirectory() as directory:
            storage = VehicleDataStorage(Path(directory))
            original = [{'vin_kod': 'ABC', 'typ': 'old', 'extra': 'keep'}, {'vin_kod': 'DEF', 'typ': 'unchanged'}]
            storage.save_year(2024, original)
            first = form_cls(); first._original_data = original[0]; first._edited_fields = {'typ'}
            first._inputs = {'vin_kod': LineEdit('ABC'), 'typ': LineEdit('new')}
            second = form_cls(); second._original_data = original[1]; second._edited_fields = set()
            second._inputs = {'vin_kod': LineEdit('DEF'), 'typ': LineEdit('unchanged')}
            tab = year_cls(); tab._vehicles = original; tab._forms = {'0': first, '1': second}
            page = page_cls(); page._storage = storage; page._tabs = {2024: tab}; page._modified = {2024}
            page._update_tab_title = Mock()
            page._save_year_with_duplicate_confirmation = lambda year, rows: (storage.save_year(year, rows) or True)
            page._do_autosave()
            self.assertEqual(storage.load_year(2024), [dict(original[0], typ='new'), original[1]])
            self.assertEqual(page._modified, set())

    def test_failed_autosave_remains_modified_and_does_not_write(self):
        year_cls = isolated('YearTab', ['get_all_data'])
        page_cls = isolated('VehicleDataPage', ['_do_autosave'], {'_log': Mock()})
        tab = year_cls(); tab._vehicles = [{}]; tab._forms = {'0': SimpleNamespace(get_data=lambda: {})}
        page = page_cls(); page._storage = SimpleNamespace(save_year=Mock()); page._tabs = {2024: tab}; page._modified = {2024}
        page._update_tab_title = Mock()
        page._save_year_with_duplicate_confirmation = Mock()
        page._do_autosave()
        page._storage.save_year.assert_not_called()
        self.assertEqual(page._modified, {2024})

    def test_corrupt_files_and_missing_vins_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = VehicleDataStorage(Path(directory))
            path = storage._year_path(2024)
            path.write_text('{broken', encoding='utf-8')
            with self.assertRaises(ValueError): storage.load_year(2024)
            with self.assertRaises(ValueError): storage.save_year(2024, [{'vin_kod': 'ABC'}])
            self.assertEqual(path.read_text(encoding='utf-8'), '{broken')
            path.write_text(json.dumps({'vehicles': [{'vin_kod': 'ABC'}]}), encoding='utf-8')
            before = path.read_bytes()
            with self.assertRaises(ValueError): storage.save_year(2024, [{'typ': 'x'}])
            self.assertEqual(path.read_bytes(), before)

    def test_symlinked_year_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = VehicleDataStorage(root / 'registry')
            target = root / 'important.json'; target.write_text('original', encoding='utf-8')
            storage._year_path(2024).symlink_to(target)
            with self.assertRaises(ValueError): storage.load_year(2024)
            with self.assertRaises(ValueError): storage.save_year(2024, [{'vin_kod': 'ABC'}])
            self.assertEqual(target.read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
