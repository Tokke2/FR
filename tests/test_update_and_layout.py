"""Tester för schemat, omstarten, profilfliken, tabellhjälparna och fönstret."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from core import startup_health, table_view, update_schedule
from core.vehicle_mapping_profiles import ProfileError, ProfileStore, profile_rows

ROOT = Path(__file__).resolve().parents[1]


class ScheduleTests(unittest.TestCase):
    """Daglig kontroll klockan 00:00, en gång per dygn."""

    def test_next_check_is_the_coming_midnight(self):
        now = datetime(2026, 10, 29, 14, 30)
        self.assertEqual(update_schedule.next_check(now), datetime(2026, 10, 30, 0, 0))

    def test_midnight_itself_points_at_the_next_day(self):
        now = datetime(2026, 10, 29, 0, 0)
        self.assertEqual(update_schedule.next_check(now), datetime(2026, 10, 30, 0, 0))

    def test_one_second_before_midnight_waits_one_second(self):
        now = datetime(2026, 10, 29, 23, 59, 59)
        self.assertEqual(update_schedule.next_check(now), datetime(2026, 10, 30, 0, 0))

    def test_milliseconds_are_capped_for_qt_timers(self):
        now = datetime(2026, 10, 29, 1, 0)
        delay = update_schedule.milliseconds_until(now)
        self.assertGreaterEqual(delay, 1_000)
        self.assertLessEqual(delay, update_schedule.MAX_TIMER_MS)

    def test_check_is_due_only_when_it_was_not_done_after_midnight(self):
        now = datetime(2026, 10, 29, 9, 0)
        self.assertTrue(update_schedule.is_due(None, now))
        self.assertTrue(update_schedule.is_due(datetime(2026, 10, 28, 23, 0), now))
        self.assertFalse(update_schedule.is_due(datetime(2026, 10, 29, 0, 0, 1), now))


class RestartTests(unittest.TestCase):
    """Omstart utan terminal och borttagen säkerhetskopia efter lyckad start."""

    def test_relaunch_uses_the_launcher_when_it_exists(self):
        from core.no_console import relaunch_arguments
        arguments = relaunch_arguments(str(ROOT / "main.pyw"), [])
        self.assertTrue(arguments[0])
        self.assertEqual(Path(arguments[1]).name, "start.pyw")
        self.assertEqual(len(arguments), 2)

    def test_relaunch_without_launcher_uses_the_entry_file(self):
        from core.no_console import relaunch_arguments
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / "main.pyw"
            entry.write_text("", encoding="utf-8")
            arguments = relaunch_arguments(str(entry), ["--validate-config"])
            self.assertEqual(arguments[1:], [str(entry.resolve()), "--validate-config"])

    def test_backup_outside_the_backup_folder_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "annat"
            outside.mkdir()
            self.assertFalse(startup_health.remove_backup(root, outside))
            self.assertTrue(outside.is_dir())

    def test_confirmed_start_removes_the_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "core").mkdir()
            (root / "core" / "modul.py").write_text("x = 1\n", encoding="utf-8")
            backup = root / ".update-backups" / "kopia"
            backup.mkdir(parents=True)
            startup_health.mark_pending(root, backup, ["core/modul.py"])
            self.assertTrue((root / ".health" / "pending.json").exists())
            self.assertTrue(startup_health.confirm_healthy(root))
            self.assertFalse(backup.exists())
            self.assertFalse((root / ".health" / "pending.json").exists())
            # Andra gången finns inget att bekräfta.
            self.assertFalse(startup_health.confirm_healthy(root))

    def test_update_plugin_restarts_only_when_an_update_is_prepared(self):
        source = (ROOT / "plugins/auto_update/plugin.py").read_text(encoding="utf-8")
        self.assertIn("def restart_after_update", source)
        self.assertIn("spawn_detached(arguments, self.root)", source)
        self.assertIn('state == "prepared"', source)
        self.assertIn("update_schedule.is_due", source)
        self.assertIn("def _schedule_daily_check", source)
        # En väntande omstart ska stoppa en ny nedladdning.
        self.assertIn("if self._restart_pending:", source)

    def test_main_window_asks_for_restart_before_quitting(self):
        source = (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")
        self.assertIn("def _restart_after_update", source)
        quit_index = source.index("def _quit_application")
        restart_index = source.index("self._restart_after_update()", quit_index)
        quit_index_end = source.index("application.quit()", quit_index)
        self.assertLess(restart_index, quit_index_end)


class ProfileTabTests(unittest.TestCase):
    def test_rows_are_sorted_and_count_the_mapped_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp) / "profiler.json")
            store.save("SAP", {"a": "vin", "b": "modell"})
            store.save("Dispatch", {"c": "färg"})
            self.assertEqual(profile_rows(store), [("Dispatch", 1), ("SAP", 2)])

    def test_missing_file_gives_an_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(profile_rows(ProfileStore(Path(tmp) / "saknas.json")), [])

    def test_profile_can_be_renamed_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp) / "profiler.json")
            store.save("Dispatch", {"a": "vin"})
            self.assertEqual(store.rename("dispatch", "Dispatch 2026"), "Dispatch 2026")
            self.assertEqual(store.list_profiles(), {"Dispatch 2026": {"a": "vin"}})
            store.delete("dispatch 2026")
            self.assertEqual(store.list_profiles(), {})
            with self.assertRaises(ProfileError):
                store.delete("finns-inte")

    def test_duplicate_name_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp) / "profiler.json")
            store.save("SAP", {"a": "vin"})
            store.save("Dispatch", {"b": "modell"})
            with self.assertRaises(FileExistsError):
                store.rename("Dispatch", "sap")

    def test_settings_menu_has_a_profile_entry(self):
        source = (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")
        self.assertIn("Profiler för import", source)
        self.assertIn("def _settings_profiles", source)


class TableHelperTests(unittest.TestCase):
    """Sortering och kolumnflytt ska fungera på alla tabeller."""

    def _view(self):
        header = Mock()
        view = Mock()
        view.horizontalHeader.return_value = header
        return view, header

    def test_sorting_and_moving_are_enabled(self):
        view, header = self._view()
        self.assertTrue(table_view.enable_sorting(view, movable=True))
        view.setSortingEnabled.assert_called_once_with(True)
        header.setSectionsMovable.assert_called_once_with(True)
        header.setSectionsClickable.assert_called_once_with(True)

    def test_moving_can_be_locked(self):
        view, header = self._view()
        table_view.enable_sorting(view, movable=False)
        header.setSectionsMovable.assert_called_once_with(False)

    def test_configure_enables_sorting_by_default(self):
        view, header = self._view()
        view.SelectionBehavior.SelectRows = 3
        table_view.configure(view, density="normal", word_wrap=False)
        view.setSortingEnabled.assert_called_with(True)

    def test_configure_can_skip_sorting_for_read_only_previews(self):
        view, _header = self._view()
        view.SelectionBehavior.SelectRows = 3
        table_view.configure(view, sortable=False)
        view.setSortingEnabled.assert_not_called()

    def test_sort_by_and_move_column_report_failure_instead_of_crashing(self):
        view, header = self._view()
        self.assertTrue(table_view.sort_by(view, 2))
        view.sortByColumn.assert_called_once_with(2, 0)
        self.assertTrue(table_view.move_column(view, 1, 0))
        header.moveSection.assert_called_once_with(1, 0)
        broken = object()
        self.assertFalse(table_view.sort_by(broken, 0))
        self.assertFalse(table_view.move_column(broken, 0, 1))

    def test_vehicle_table_keeps_sorting_off_while_filling(self):
        source = (ROOT / "plugins/main_gui/vehicle_registry_page.py").read_text(encoding="utf-8")
        self.assertIn("setSortingEnabled(False)", source)
        self.assertLess(source.index("setSortingEnabled(False)"),
                        source.index("self._table.setSortingEnabled(True)"))
        self.assertIn("sectionMoved.connect(self._on_column_moved)", source)


class WindowTests(unittest.TestCase):
    def test_window_uses_the_full_screen_height(self):
        from core import theme as design
        for height in (600, 768, 1080, 1440):
            self.assertEqual(design.window_size(1920, height)[1], height)

    def test_width_follows_the_screen_and_never_exceeds_ninety_percent(self):
        from core import theme as design
        self.assertEqual(design.window_size(1920, 1080)[0], design.PREFERRED_WIDTH)
        self.assertLessEqual(design.window_size(1200, 800)[0], int(1200 * 0.9))

    def test_window_is_placed_at_the_top_of_the_work_area(self):
        source = (ROOT / "plugins/main_gui/plugin.py").read_text(encoding="utf-8")
        self.assertIn("self.move(available.x(), available.y())", source)


class ScheduleAndSettingsTests(unittest.TestCase):
    def test_settings_have_daily_check_and_restart_defaults(self):
        from core.settings_manager import DEFAULT_SETTINGS
        self.assertIs(DEFAULT_SETTINGS["update_daily_check"], True)
        self.assertIs(DEFAULT_SETTINGS["update_restart"], True)

    def test_menu_can_turn_the_daily_check_off(self):
        source = (ROOT / "plugins/auto_update/plugin.py").read_text(encoding="utf-8")
        self.assertIn("Kontrollera uppdateringar varje dag klockan 00:00", source)
        self.assertIn("Starta om automatiskt efter uppdatering", source)
        self.assertIn('self.settings.set("update_daily_check"', source)
