"""Inkoppling av förslag 7, 9, 11, 17, 20, 21, 22 och 24 i appen."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MENU = (ROOT / "plugins" / "main_gui" / "plugin.py").read_text(encoding="utf-8")
DIALOGS = ROOT / "plugins" / "main_gui" / "dialogs"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class MenuAndShortcutTests(unittest.TestCase):
    def test_tools_menu_has_new_entries(self):
        for text in ("Sök i allt (Ctrl+K)", "Översikt", "Bevakad mapp", "Verifiera TS-underlag",
                     "Felkodsguide"):
            self.assertIn(text, MENU)
        for method in ("_show_global_search", "_show_dashboard", "_show_watched_folder",
                       "_show_ts_verification", "_show_error_guide"):
            self.assertIn(f"def {method}", MENU)

    def test_ctrl_k_is_application_wide(self):
        self.assertIn('QKeySequence("Ctrl+K")', MENU)
        self.assertIn("Qt.ShortcutContext.ApplicationShortcut", MENU)

    def test_search_opens_right_year_and_row(self):
        self.assertIn("def _open_vehicle_from_search", MENU)
        self.assertIn("open_year", MENU)
        self.assertIn("select_row", MENU)
        page = source(ROOT / "plugins" / "main_gui" / "vehicle_registry_page.py")
        self.assertIn("def open_year", page)
        self.assertIn("_create_tab(year, select=False)", page)
        self.assertIn("_show_year(year)", page)

    def test_tray_has_quick_actions(self):
        self.assertIn("🔎 Sök (Ctrl+K)", MENU)
        self.assertIn("📥 Ny import...", MENU)
        self.assertIn("📊 Översikt", MENU)
        self.assertIn("📋 Felsökningslogg", MENU)
        self.assertLess(MENU.index("🔎 Sök (Ctrl+K)"), MENU.index("menu.addSeparator()"))


class WatchedFolderWiringTests(unittest.TestCase):
    def test_watching_is_off_by_default_and_never_imports(self):
        from core.watched_folder import default_settings
        self.assertFalse(default_settings()["enabled"])
        self.assertIn("_check_watched_folder", MENU)
        self.assertIn("showMessage", MENU)
        self.assertIn("Inget importeras automatiskt", MENU)
        self.assertIn("def _watched_message_clicked", MENU)
        handler = MENU[MENU.index("def _watched_message_clicked"):]
        self.assertIn("self._import_file_dialog()", handler)
        dialog = source(DIALOGS / "watched_folder_dialog.py")
        self.assertIn("Ingenting importeras automatiskt", dialog)


class BackgroundImportTests(unittest.TestCase):
    def test_dialog_reads_files_through_cancellable_runner(self):
        dialog = source(DIALOGS / "import_dialog.py")
        self.assertIn("from plugins.main_gui.background import run_cancellable", dialog)
        self.assertIn("_read_in_background", dialog)
        self.assertIn("read_csv(path, delimiter)", dialog)
        self.assertIn("read_excel(path, sheet)", dialog)
        self.assertIn("read_pdf(path, delimiter)", dialog)
        self.assertGreaterEqual(dialog.count("_read_in_background(parent"), 4)

    def test_background_dialog_cancels_and_blocks_close(self):
        gui = source(ROOT / "plugins" / "main_gui" / "background.py")
        self.assertIn("CancellationToken", gui)
        self.assertIn("token.cancel()", gui)
        self.assertIn("event.ignore()", gui)
        self.assertIn("Avbryt", gui)


class StartupHealthWiringTests(unittest.TestCase):
    def test_start_checks_before_launch_and_gui_confirms(self):
        start = (ROOT / "start.pyw").read_text(encoding="utf-8")
        self.assertIn("from core.startup_health import check_and_recover", start)
        self.assertLess(start.index("_startup_health(log, ROOT)"), start.index("Startar appen"))
        self.assertIn("from core.startup_health import confirm_healthy", MENU)

    def test_updater_marks_pending_after_install(self):
        worker = source(ROOT / "plugins" / "auto_update" / "worker.py")
        self.assertIn("mark_pending(root, backup, list(files))", worker)
        self.assertLess(worker.index("install(root, files)"), worker.index("mark_pending"))

    def test_dashboard_warns_about_unconfirmed_start(self):
        from core.startup_health import mark_pending
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "core").mkdir()
            (root / "core" / "a.py").write_text("x", encoding="utf-8")
            (root / "backup").mkdir()
            mark_pending(root, root / "backup", ["core/a.py"])
            from core.dashboard import health_section
            self.assertTrue(health_section(root)["pending"])
            self.assertIn("bekräftades inte", health_section(root)["text"])


class DashboardAndGuideWiringTests(unittest.TestCase):
    def test_dashboard_is_delayed_until_window_opens(self):
        self.assertIn("_dashboard_pending", MENU)
        self.assertIn("def showEvent", MENU)
        self.assertIn("QTimer.singleShot(400, self._show_dashboard)", MENU)
        dialog = source(DIALOGS / "dashboard_dialog.py")
        self.assertIn("def reload", dialog)
        self.assertIn("TS-generering", dialog)

    def test_error_guide_reachable_from_log_and_menu(self):
        log_dialog = source(DIALOGS / "error_log_dialog.py")
        self.assertIn("Felkodsguide", log_dialog)
        self.assertIn("ErrorGuideDialog", log_dialog)
        guide = source(DIALOGS / "error_guide_dialog.py")
        self.assertIn("guide_lines", guide)
        self.assertIn("Felkodsguide", MENU)

    def test_ts_dialog_requires_confirmation_and_note(self):
        dialog = source(DIALOGS / "ts_verification_dialog.py")
        self.assertIn("confirmed=self._confirm.isChecked()", dialog)
        self.assertIn("len(self._note.text().strip()) >= 10", dialog)
        self.assertIn("ingenting skrivs, flyttas eller genereras", dialog)
        self.assertIn("PT28/PT99", dialog)


class SyntaxAndImportsTests(unittest.TestCase):
    def test_all_new_modules_compile(self):
        for path in [
            ROOT / "core" / "global_search.py", ROOT / "core" / "watched_folder.py",
            ROOT / "core" / "background_task.py", ROOT / "core" / "ts_verification.py",
            ROOT / "core" / "startup_health.py", ROOT / "core" / "error_codes.py",
            ROOT / "core" / "dashboard.py", ROOT / "plugins" / "main_gui" / "background.py",
            DIALOGS / "global_search_dialog.py", DIALOGS / "dashboard_dialog.py",
            DIALOGS / "ts_verification_dialog.py", DIALOGS / "watched_folder_dialog.py",
            DIALOGS / "error_guide_dialog.py",
        ]:
            with self.subTest(path=path.name):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_core_modules_have_no_qt_dependency(self):
        for name in ("global_search", "watched_folder", "background_task", "ts_verification",
                     "startup_health", "error_codes", "dashboard"):
            text = source(ROOT / "core" / f"{name}.py")
            self.assertNotIn("from PySide6", text, name)


if __name__ == "__main__":
    unittest.main()
