from __future__ import annotations

import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.vehicle_year_layout import FIRST_YEAR, initial_years, is_archived_year
from plugins.vehicle_registry.plugin import VehicleDataStorage


class Tabs:
    def __init__(self):
        self.tabs = []
        self.selected = None

    def insertTab(self, index, widget, title):
        self.tabs.insert(index, [widget, title])
        if self.selected is None:
            self.selected = widget
        return index

    def indexOf(self, widget):
        return next((i for i, (w, _) in enumerate(self.tabs) if w is widget), -1)

    def removeTab(self, index):
        widget, _ = self.tabs.pop(index)
        if self.selected is widget:
            self.selected = self.tabs[0][0] if self.tabs else None

    def setCurrentWidget(self, widget):
        if self.indexOf(widget) >= 0:
            self.selected = widget

    def currentWidget(self):
        return self.selected

    def widget(self, index):
        return self.tabs[index][0] if 0 <= index < len(self.tabs) else None

    def setTabText(self, index, text):
        self.tabs[index][1] = text

    def titles(self):
        return [title for _, title in self.tabs]


class Clock:
    year = 2026

    @classmethod
    def now(cls):
        return SimpleNamespace(year=cls.year)


class FakeYearTab:
    def __init__(self, year, storage, on_modified, app=None):
        self.year = year
        self.editing_enabled = None
        self.copy_vehicle_requested = SimpleNamespace(connect=Mock())
        self.select_row = Mock()
        self.deleteLater = Mock()
        self.unsaved_contents = {}

    def enable_editing(self, enabled):
        self.editing_enabled = enabled


def make_page(year_factory=FakeYearTab):
    tree = ast.parse(Path('plugins/main_gui/vehicle_registry_page.py').read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'VehicleDataPage')
    names = {'_year_container', '_insert_year_tab', '_show_year', '_create_tab',
             '_refresh_year_placement', '_update_archive_title', '_update_tab_title',
             '_close_tab', '_close_archive_tab', '_close_year_tab', '_navigate_to_result'}
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(methods) == len(names)
    isolated = ast.ClassDef(name='Page', bases=[], keywords=[], body=methods, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[
        ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), isolated,
    ], type_ignores=[]))
    env = {'datetime': Clock, 'FIRST_YEAR': FIRST_YEAR, 'is_archived_year': is_archived_year,
           'YearTab': year_factory, '_log': Mock(), 'QMessageBox': SimpleNamespace(warning=Mock())}
    exec(compile(module, '<archive-ui>', 'exec'), env)
    page = env['Page']()
    page._message_box = env['QMessageBox']
    page._tabs = {}; page._modified = set(); page._storage = object(); page._app = None
    page._is_unlocked = True; page._layout_year = Clock.year
    page._on_year_modified = Mock(); page._on_copy_vehicle_requested = Mock()
    page._archive_tabs = Tabs(); page._tab_widget = Tabs()
    page._tab_widget.insertTab(0, page._archive_tabs, 'Arkiv')
    page._search = SimpleNamespace(clear=Mock())
    return page


class VehicleYearArchiveTests(unittest.TestCase):
    def setUp(self):
        Clock.year = 2026

    def test_cutoff_and_year_list(self):
        self.assertFalse(is_archived_year(2021, 2026))
        self.assertTrue(is_archived_year(2021, 2027))
        self.assertFalse(is_archived_year(2022, 2027))
        self.assertFalse(is_archived_year(2028, 2027))
        self.assertEqual(initial_years(2026), list(range(2021, 2027)))
        self.assertEqual(initial_years(2026, [2020, 2028], [2024]), [2020, 2021, 2022, 2023, 2024, 2025, 2026, 2028])

    def test_years_are_sorted_and_old_years_in_archive_without_recreation(self):
        page = make_page()
        for year in (2025, 2020, 2023, 2024, 2021, 2022, 2026, 2028, 2019):
            page._create_tab(year, select=False)
        self.assertEqual(page._tab_widget.titles(), ['2021', '2022', '2023', '2024', '2025', '2026', '2028', 'Arkiv'])
        self.assertEqual(page._archive_tabs.titles(), ['2019', '2020'])
        old = page._tabs[2020]
        page._create_tab(2020)
        self.assertIs(page._tabs[2020], old)
        self.assertIs(page._tab_widget.currentWidget(), page._archive_tabs)
        self.assertIs(page._archive_tabs.currentWidget(), old)
        self.assertTrue(old.editing_enabled)

    def test_new_year_moves_same_unsaved_widget_and_updates_archive_indicator(self):
        page = make_page()
        for year in range(2021, 2027): page._create_tab(year, select=False)
        page._show_year(2021)
        old = page._tabs[2021]
        old.unsaved_contents = {'vin_kod': 'ABC', 'typ': 'ändring'}
        page._modified.add(2021)
        page._update_tab_title(2021, True)
        Clock.year = 2027
        page._refresh_year_placement()
        self.assertEqual(page._tab_widget.titles(), ['2022', '2023', '2024', '2025', '2026', '2027', 'Arkiv *'])
        self.assertEqual(page._archive_tabs.titles(), ['2021 *'])
        self.assertIs(page._tabs[2021], old)
        self.assertEqual(old.unsaved_contents, {'vin_kod': 'ABC', 'typ': 'ändring'})
        self.assertIs(page._tab_widget.currentWidget(), page._archive_tabs)
        self.assertIs(page._archive_tabs.currentWidget(), old)
        page._modified.remove(2021)
        page._update_tab_title(2021, False)
        self.assertEqual(page._tab_widget.titles()[-1], 'Arkiv')
        self.assertEqual(page._archive_tabs.titles(), ['2021'])

    def test_navigate_to_archived_search_result(self):
        page = make_page()
        page._create_tab(2020, select=False)
        page._navigate_to_result(SimpleNamespace(found=True, year=2020, index=3))
        self.assertIs(page._tab_widget.currentWidget(), page._archive_tabs)
        page._tabs[2020].select_row.assert_called_once_with(3)
        page._search.clear.assert_called_once()

    def test_closing_archive_container_is_ignored_and_year_respects_unsaved_guard(self):
        page = make_page()
        page._create_tab(2020, select=False)
        page._handle_unsaved_changes = Mock(return_value=False)
        page._close_tab(page._tab_widget.indexOf(page._archive_tabs))
        self.assertGreaterEqual(page._tab_widget.indexOf(page._archive_tabs), 0)
        page._close_archive_tab(0)
        self.assertIn(2020, page._tabs)
        page._handle_unsaved_changes.return_value = True
        tab = page._tabs[2020]
        page._close_archive_tab(0)
        self.assertNotIn(2020, page._tabs)
        tab.deleteLater.assert_called_once()

    def test_unreadable_year_is_not_overwritten_and_other_years_remain_available(self):
        class LoadingTab(FakeYearTab):
            def __init__(self, year, storage, on_modified, app=None):
                storage.load_year(year)
                super().__init__(year, storage, on_modified, app)
        with tempfile.TemporaryDirectory() as directory:
            storage = VehicleDataStorage(Path(directory))
            path = storage._year_path(2021)
            path.write_bytes(b'{broken')
            page = make_page(LoadingTab)
            page._storage = storage
            page._create_tab(2021, select=False)
            page._create_tab(2022, select=False)
            self.assertNotIn(2021, page._tabs)
            self.assertIn(2022, page._tabs)
            self.assertEqual(path.read_bytes(), b'{broken')
            page._message_box.warning.assert_called_once()

    def test_year_rollover_does_not_change_year_data_files(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = VehicleDataStorage(Path(directory))
            storage.save_year(2021, [{'vin_kod': 'ABC', 'typ': 'original'}])
            path = storage._year_path(2021)
            before = path.read_bytes()
            page = make_page()
            page._storage = storage
            page._create_tab(2021, select=False)
            Clock.year = 2027
            page._refresh_year_placement()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(storage.load_year(2021), [{'vin_kod': 'ABC', 'typ': 'original'}])

    def test_clock_moving_back_moves_same_widget_out_of_archive(self):
        page = make_page()
        page._create_tab(2020, select=False)
        old = page._tabs[2020]
        Clock.year = 2025
        page._refresh_year_placement()
        self.assertIs(page._tabs[2020], old)
        self.assertGreaterEqual(page._tab_widget.indexOf(old), 0)
        self.assertEqual(page._archive_tabs.indexOf(old), -1)


if __name__ == '__main__':
    unittest.main()
