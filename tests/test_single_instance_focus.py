from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import single_instance as si

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('instance_start_test', str(ROOT / 'start.pyw'))
spec = importlib.util.spec_from_loader(loader.name, loader)
start = importlib.util.module_from_spec(spec)
loader.exec_module(start)


def extract_class(name, methods, env):
    path = ROOT / 'plugins/main_gui/plugin.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    original = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == name)
    body = [n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in methods]
    assert len(body) == len(methods)
    cls = ast.ClassDef(name=name, bases=[], keywords=[], body=body, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[]))
    exec(compile(module, str(path), 'exec'), env)
    return env[name]


class SingleInstanceTests(unittest.TestCase):
    def test_process_lock_focus_and_crash_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(ROOT)}
            script = ('import sys; from pathlib import Path; from core.single_instance import SingleInstance; '
                      'x=SingleInstance(lock_dir=Path(sys.argv[1]), on_show_request=lambda: print("focus", flush=True)); '
                      'print("ready" if x.acquire() else "failed", flush=True); '
                      'sys.stdin.readline(); print(x.check_show_request(), flush=True); sys.stdin.read()')
            owner = subprocess.Popen([sys.executable, '-c', script, directory], env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(owner.stdout.readline().strip(), 'ready')
                other = si.SingleInstance(lock_dir=Path(directory))
                self.assertFalse(other.acquire())
                self.assertIsNone(other.error)
                self.assertTrue(other.focus_existing())
                owner.stdin.write('check\n'); owner.stdin.flush()
                self.assertEqual(owner.stdout.readline().strip(), 'focus')
                self.assertEqual(owner.stdout.readline().strip(), 'True')
                self.assertFalse(other.check_show_request())
                owner.kill()
                owner.wait(timeout=5)
                self.assertTrue(other.acquire())
                other.release()
            finally:
                if owner.poll() is None:
                    owner.kill(); owner.wait(timeout=5)
                owner.stdin.close(); owner.stdout.close()

    def test_request_survives_lock_handover(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = si.SingleInstance(lock_dir=Path(directory))
            sender = si.SingleInstance(lock_dir=Path(directory))
            self.assertTrue(lock.acquire())
            self.assertTrue(sender.focus_existing())
            lock.release()
            callback = Mock()
            successor = si.SingleInstance(lock_dir=Path(directory), on_show_request=callback)
            self.assertTrue(successor.acquire())
            try:
                self.assertTrue(successor.check_show_request())
                callback.assert_called_once()
            finally:
                successor.release()

    def test_no_unsafe_pid_fallback_and_fail_closed_on_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(si, 'IS_WINDOWS', False), patch.object(si, '_HAS_FCNTL', False):
            lock = si.SingleInstance(lock_dir=Path(directory))
            self.assertFalse(lock.acquire())
            self.assertIsNotNone(lock.error)
            self.assertFalse(lock.is_acquired)
        with tempfile.TemporaryDirectory() as directory, patch.object(si, '_HAS_FCNTL', True), patch.object(si.SingleInstance, '_acquire_flock', side_effect=OSError('broken')):
            lock = si.SingleInstance(lock_dir=Path(directory))
            self.assertFalse(lock.acquire())
            self.assertIsNotNone(lock.error)

    @unittest.skipIf(not hasattr(os, 'O_NOFOLLOW'), 'requires O_NOFOLLOW')
    def test_lock_does_not_follow_symlink_or_truncate_user_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            victim = root / 'user-data'
            victim.write_text('untouched')
            lock = si.SingleInstance(lock_dir=root)
            lock._lock_path.symlink_to(victim)
            self.assertFalse(lock.acquire())
            self.assertIsNotNone(lock.error)
            self.assertEqual(victim.read_text(), 'untouched')

    def test_windows_mutex_uses_pointer_sized_handle_and_session_scope(self):
        import ctypes
        class Function:
            def __init__(self, result): self.result = result; self.calls = []
            def __call__(self, *args): self.calls.append(args); return self.result
        handle = 0x123456789ABC
        kernel = SimpleNamespace(CreateMutexW=Function(handle), CloseHandle=Function(1), GetLastError=Function(0))
        with tempfile.TemporaryDirectory() as directory, patch.object(si, 'IS_WINDOWS', True), patch.object(si, '_HAS_CTYPES', True), patch.object(ctypes, 'windll', SimpleNamespace(kernel32=kernel), create=True):
            lock = si.SingleInstance(lock_dir=Path(directory))
            self.assertTrue(lock.acquire())
            self.assertEqual(kernel.CreateMutexW.restype, ctypes.c_void_p)
            self.assertTrue(kernel.CreateMutexW.calls[0][2].startswith('Local\\'))
            lock.release()
            self.assertEqual(kernel.CloseHandle.calls, [(handle,)])

    def test_focus_write_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(si, '_atomic_write_text', side_effect=OSError('unwritable')):
            self.assertFalse(si.SingleInstance(lock_dir=Path(directory)).focus_existing())

    def test_duplicate_during_preflight_sends_request_without_running_checks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(si.tempfile, 'gettempdir', return_value=directory):
            lock = si.SingleInstance(si.LAUNCHER_LOCK_NAME)
            self.assertTrue(lock.acquire())
            try:
                with patch.object(start, 'setup_log', return_value=logging.getLogger('test-launch')), patch.object(start, '_claim_weekly') as claim, patch.object(start.subprocess, 'Popen') as popen:
                    self.assertEqual(start.main(), 0)
                    claim.assert_not_called(); popen.assert_not_called()
                self.assertTrue(si.SingleInstance().check_show_request())
            finally:
                lock.release()

    def test_existing_direct_app_skips_preflight(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(si.tempfile, 'gettempdir', return_value=directory):
            existing = si.SingleInstance()
            self.assertTrue(existing.acquire())
            try:
                with patch.object(start, 'setup_log', return_value=logging.getLogger('test-launch')), patch.object(start, '_claim_weekly') as claim:
                    self.assertEqual(start.main(), 0)
                    claim.assert_not_called()
                self.assertTrue(existing.check_show_request())
            finally:
                existing.release()

    def test_focus_timer_registered_on_main_window(self):
        class Timer:
            singles = []
            def __init__(self, parent):
                self.parent = parent
                self.timeout = SimpleNamespace(connect=Mock())
                self.start = Mock()
            @staticmethod
            def singleShot(delay, callback): Timer.singles.append((delay, callback))
        window_cls = extract_class('MainWindow', {'_setup_instance_focus'}, {'QTimer': Timer})
        window = window_cls(); window._show_from_tray = Mock()
        instance = SimpleNamespace(set_show_callback=Mock(), check_show_request=Mock())
        window.app = SimpleNamespace(single_instance=instance)
        window._setup_instance_focus()
        instance.set_show_callback.assert_called_once_with(window._show_from_tray)
        window._instance_focus_timer.timeout.connect.assert_called_once_with(instance.check_show_request)
        window._instance_focus_timer.start.assert_called_once_with(500)
        Timer.singles[0][1]()
        instance.check_show_request.assert_called_once()

    def test_plugin_does_not_start_nested_event_loop_and_exposes_window(self):
        source = (ROOT / 'plugins/main_gui/plugin.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Plugin')
        activate = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'activate')
        self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr == 'exec' for n in ast.walk(activate)))
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'main_window' for n in cls.body))

    def test_plugin_activation_starts_minimized_without_running_qt_loop(self):
        fake_window = SimpleNamespace(show=Mock(), showMinimized=Mock())
        cls = extract_class('Plugin', {'activate', 'main_window'},
                            {'MainWindow': lambda app: fake_window, '_log': Mock()})
        plugin = cls()
        plugin.app = object()
        plugin._qapp = SimpleNamespace(exec=Mock())
        plugin.activate()
        fake_window.showMinimized.assert_called_once()
        fake_window.show.assert_not_called()
        plugin._qapp.exec.assert_not_called()
        self.assertIs(plugin.main_window, fake_window)

    def test_app_start_runs_one_loop_and_shutdown_after_plugins(self):
        import asyncio
        from unittest.mock import AsyncMock
        main_loader = importlib.machinery.SourceFileLoader('instance_main_test', str(ROOT / 'main.pyw'))
        main_spec = importlib.util.spec_from_loader(main_loader.name, main_loader)
        main = importlib.util.module_from_spec(main_spec)
        sys.modules[main_loader.name] = main
        main_loader.exec_module(main)
        main.Application._instance = None
        app = main.Application(headless=False)
        app.config = SimpleNamespace(get_str=lambda *args: 'INFO')
        app._qapp = SimpleNamespace(exec=Mock(return_value=0))
        app.event_bus = SimpleNamespace(emit=Mock())
        for name in ('_load_configuration', '_create_event_bus', '_load_plugins', '_initialize_plugins', '_activate_plugins', 'shutdown'):
            setattr(app, name, AsyncMock())
        for name in ('_print_banner', '_setup_cache_manager', '_ensure_directories', '_init_qt', '_print_section', '_print_load_result', '_print_ready'):
            setattr(app, name, Mock())
        app._find_main_window = Mock(return_value=True)
        with patch.object(main, 'setup_all_loggers'):
            self.assertEqual(asyncio.run(app.start()), 0)
        app._activate_plugins.assert_awaited_once()
        app._qapp.exec.assert_called_once_with()
        app.event_bus.emit.assert_called_once()
        app.shutdown.assert_awaited_once()
        main.Application._instance = None

    def test_worker_waits_for_launcher_before_install(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'core').mkdir()
            (root / 'core/a.py').write_text('old = True\n')
            archive = root / 'release.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('FR-release/core/a.py', 'new = True\n')
            launcher = si.SingleInstance(si.LAUNCHER_LOCK_NAME, lock_dir=root)
            self.assertTrue(launcher.acquire())
            env = {**os.environ, 'TMPDIR': directory, 'TEMP': directory, 'TMP': directory, 'PYTHONDONTWRITEBYTECODE': '1'}
            worker = ROOT / 'plugins/auto_update/worker.py'
            process = subprocess.Popen([sys.executable, str(worker), str(root), str(archive)], stdin=subprocess.PIPE, env=env)
            try:
                process.stdin.close()
                time.sleep(.6)
                self.assertIsNone(process.poll())
                self.assertEqual((root / 'core/a.py').read_text(), 'old = True\n')
                launcher.release()
                self.assertEqual(process.wait(timeout=10), 0)
                self.assertEqual((root / 'core/a.py').read_text(), 'new = True\n')
            finally:
                launcher.release()
                if process.poll() is None:
                    process.kill(); process.wait()


if __name__ == '__main__':
    unittest.main()
