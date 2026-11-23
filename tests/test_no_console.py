"""Inga terminalfönster och alltid minimerad start.

Testerna granskar både hjälpmodulen och att varje plats i programmet som
startar en hjälpprocess använder de dolda flaggorna. Detta är det som hindrar
ett svart konsolfönster från att blinka till vid start, paketskanning,
tilläggsinstallation eller uppdateringsförberedelse.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import no_console  # noqa: E402


def _own_files() -> list[Path]:
    files = []
    for pattern in ('*.py', '*.pyw'):
        for path in ROOT.rglob(pattern):
            parts = set(path.parts)
            if '.git' in parts or '__pycache__' in parts:
                continue
            if path.relative_to(ROOT).parts[0] == 'tests':
                continue
            if path == ROOT / 'core' / 'no_console.py':
                continue
            files.append(path)
    return files


def _subprocess_calls(path: Path):
    """Alla anrop till subprocess.run/Popen i filen."""
    tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != 'subprocess':
            continue
        if node.func.attr in ('run', 'Popen', 'call', 'check_output'):
            yield node


class HiddenProcessTests(unittest.TestCase):
    def test_hidden_kwargs_hide_the_window_on_windows(self):
        # CREATE_NO_WINDOW hindrar Windows från att skapa en konsol alls.
        self.assertEqual(no_console.CREATE_NO_WINDOW, 0x08000000)
        kwargs = no_console.hidden_kwargs()
        if sys.platform == 'win32':
            self.assertEqual(kwargs['creationflags'], no_console.CREATE_NO_WINDOW)
            self.assertIsNotNone(kwargs['startupinfo'])
        else:
            # På Linux och macOS finns ingen konsol att skapa.
            self.assertEqual(kwargs, {})

    def test_merged_never_overrides_the_callers_choice(self):
        merged = no_console.merged({'creationflags': 1234, 'timeout': 5})
        self.assertEqual(merged['creationflags'], 1234)
        self.assertEqual(merged['timeout'], 5)
        self.assertIn('text', no_console.merged({'text': True}))

    def test_gui_executable_has_no_console(self):
        exe = no_console.gui_executable()
        self.assertTrue(exe)
        if sys.platform == 'win32':
            self.assertTrue(exe.lower().endswith('pythonw.exe') or exe.lower().endswith('python.exe'))
        else:
            self.assertEqual(exe, sys.executable)
        self.assertFalse(no_console.hide_console_window() if sys.platform != 'win32' else False)

    def test_every_helper_process_runs_without_a_console(self):
        missing = []
        for path in _own_files():
            for node in _subprocess_calls(path):
                names = {kw.arg for kw in node.keywords if kw.arg}
                unpacked = {kw.value.func.id for kw in node.keywords
                            if kw.arg is None and isinstance(kw.value, ast.Call)
                            and isinstance(kw.value.func, ast.Name)}
                if unpacked & {'hidden_kwargs', 'merged'} or 'creationflags' in names:
                    continue
                missing.append(f'{path.relative_to(ROOT)}:{node.lineno}')
        self.assertEqual(missing, [], 'Hjälpprocesser utan dolda flaggor')

    def test_no_shell_command_window_is_opened(self):
        for path in _own_files():
            text = path.read_text(encoding='utf-8', errors='replace')
            self.assertNotIn('"cmd", "/c", "start"', text, path)
            self.assertNotIn("'cmd', '/c', 'start'", text, path)

    def test_launcher_starts_the_app_with_pythonw(self):
        start = (ROOT / 'start.pyw').read_text(encoding='utf-8')
        self.assertIn('hide_console_window()', start)
        self.assertIn('gui_executable()', start)
        child = start.split('subprocess.Popen([gui_executable()', 1)[1].split(')\n', 1)[0]
        self.assertIn('hidden_kwargs()', child)
        # Ingen ny konsol får skapas av den startade appprocessen.
        self.assertNotIn('subprocess.Popen([sys.executable, str(ROOT / "main.pyw")', start)

    def test_main_hides_an_existing_console_before_qt(self):
        main = (ROOT / 'main.pyw').read_text(encoding='utf-8')
        self.assertIn('from core.no_console import hide_console_window', main)
        self.assertIn('hide_console_window()', main)
        self.assertLess(main.index('hide_console_window()'), main.index('from core.event_bus import EventBus'))

    def test_weekend_scan_and_install_paths_pass_the_flags(self):
        dependencies = (ROOT / 'core' / 'dependencies.py').read_text(encoding='utf-8')
        self.assertEqual(dependencies.count('hidden_kwargs()'), 2)
        import_dialog = (ROOT / 'plugins' / 'main_gui' / 'dialogs' / 'import_dialog.py').read_text(encoding='utf-8')
        self.assertEqual(import_dialog.count('hidden_kwargs()'), 2)
        updater = (ROOT / 'plugins' / 'auto_update' / 'plugin.py').read_text(encoding='utf-8')
        self.assertIn('gui_executable()', updater)
        self.assertIn('hidden_kwargs()', updater)

    def test_windows_start_files_hide_their_console(self):
        script = (ROOT / 'start_fordonsreg.ps1').read_text(encoding='utf-8')
        self.assertIn('GetConsoleWindow', script)
        self.assertIn('ShowWindow', script)
        self.assertIn("$startArgs['WindowStyle'] = 'Hidden'", script)
        # .cmd ska starta PowerShell dolt och avsluta sig själv direkt.
        cmd = (ROOT / 'start_fordonsreg.cmd').read_text(encoding='utf-8')
        self.assertIn('-WindowStyle Hidden', cmd)
        self.assertIn('start "" /min', cmd)
        self.assertIn('exit /b 0', cmd)


class AlwaysMinimizedTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'plugins' / 'main_gui' / 'plugin.py').read_text(encoding='utf-8')

    def test_activation_always_minimizes(self):
        tree = ast.parse(self.source)
        plugin = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Plugin')
        activate = next(n for n in plugin.body
                        if isinstance(n, ast.FunctionDef) and n.name == 'activate')
        methods = [n.attr for n in ast.walk(activate) if isinstance(n, ast.Attribute)]
        self.assertIn('showMinimized', methods)
        self.assertNotIn('showMaximized', methods)

    def test_window_minimizes_again_if_shown_during_startup(self):
        self.assertIn('self._startup_phase = True', self.source)
        window = self.source.split('class MainWindow', 1)[1]
        show = window.split('def showEvent', 1)[1].split('def closeEvent', 1)[0]
        self.assertIn('if self._startup_phase:', show)
        self.assertIn('self.showMinimized()', show)
        self.assertIn('self.hide()', show)
        # Användarens egen öppning från systemfältet avslutar startfasen.
        tray = window.split('def _show_from_tray', 1)[1].split('def add_update_tray_action', 1)[0]
        self.assertIn('self._startup_phase = False', tray)

    def test_start_minimized_setting_cannot_disable_it(self):
        config = (ROOT / 'config.json').read_text(encoding='utf-8')
        self.assertIn('"start_minimized": true', config)
        # Ingen kod läser inställningen för att kunna visa fönstret vid start.
        for path in _own_files():
            text = path.read_text(encoding='utf-8', errors='replace')
            self.assertNotIn("get_config_value_safe(self.app, \"start_minimized\"", text, path)


if __name__ == '__main__':
    unittest.main()
