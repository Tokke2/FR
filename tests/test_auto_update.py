from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from core import autostart
from core.settings_manager import SettingsManager
from plugins.auto_update import updater


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for path, value in entries.items():
            z.writestr("FR-release/" + path, value)
    return out.getvalue()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_compare_contents_and_protect_data(self):
        (self.root / "core").mkdir()
        (self.root / "core/a.py").write_bytes(b"x = 1\n")
        (self.root / "main.pyw").write_bytes(b"untouched\n")
        (self.root / "data").mkdir()
        (self.root / "data/vehicles.json").write_bytes(b"user data")
        files = updater.release_files(archive({"core/a.py": "x = 1\n", "core/b.py": "y = 2\n", "data/vehicles.json": "bad", "config.json": "bad", "core/__pycache__/x.pyc": "bad"}))
        self.assertEqual(set(files), {"core/a.py", "core/b.py"})
        self.assertEqual(set(updater.changed_files(self.root, files)), {"core/b.py"})
        count, backup = updater.install(self.root, files)
        self.assertEqual(count, 1)
        self.assertEqual(json.loads((backup / "manifest.json").read_text())["new_files"], ["core/b.py"])
        self.assertEqual((self.root / "data/vehicles.json").read_bytes(), b"user data")
        self.assertEqual((self.root / "main.pyw").read_bytes(), b"untouched\n")
        self.assertEqual(updater.install(self.root, files), (0, None))

    def test_launcher_and_main_are_updated_with_backup(self):
        (self.root / "main.pyw").write_text("protected\n")
        files = updater.release_files(archive({"start.pyw": "x = 1\n", "tools/install_latest_python.py": "y = 2\n", "Installera senaste Python.bat": "danger", "main.pyw": "z = 3\n"}))
        self.assertEqual(set(files), {"start.pyw", "main.pyw"})
        for legacy in ("tools/install_latest_python.py", "tools/Install_Latest_Python.py"):
            with self.assertRaises(updater.UpdateError):
                updater.changed_files(self.root, {legacy: b"x=2"})
        _, backup = updater.install(self.root, files)
        self.assertEqual((backup / "main.pyw").read_text(), "protected\n")
        self.assertEqual((self.root / "main.pyw").read_text(), "z = 3\n")
        self.assertEqual((self.root / "start.pyw").read_text(), "x = 1\n")

    def test_license_is_updated_but_never_executed(self):
        (self.root / "LICENSE").write_text("gammal\n")
        text = "Fordonsreg – licens för användning\n\nCopyright © Rickard Längkvist\n"
        files = updater.release_files(archive({"LICENSE": text, "config.json": "bad", "data/LICENSE": "bad"}))
        self.assertEqual(set(files), {"LICENSE"})
        _, backup = updater.install(self.root, files)
        self.assertEqual((backup / "LICENSE").read_text(), "gammal\n")
        self.assertEqual((self.root / "LICENSE").read_text(), text)
        with self.assertRaises(updater.UpdateError):
            updater.release_files(archive({"LICENSE": b"bad\x00data"}))
        with self.assertRaises(updater.UpdateError):
            updater.release_files(archive({"LICENSE": "x" * 70000}))

    def test_native_launchers_are_updated_with_backup_and_validation(self):
        (self.root / 'start_fordonsreg.cmd').write_text('old')
        files = updater.release_files(archive({'start_fordonsreg.cmd': '@echo off\n', 'start_fordonsreg.ps1': 'Write-Output ok\n', 'start_fordonsreg.sh': '#!/bin/sh\n', 'evil.cmd': 'no'}))
        self.assertEqual(set(files), updater.START_SCRIPTS)
        _, backup = updater.install(self.root, files)
        self.assertEqual((backup / 'start_fordonsreg.cmd').read_text(), 'old')
        with self.assertRaises(updater.UpdateError):
            updater.release_files(archive({'start_fordonsreg.cmd': b'bad\x00data'}))

    def test_backup_and_rollback_on_error(self):
        (self.root / "core").mkdir()
        (self.root / "core/a.py").write_text("original = 1\n")
        (self.root / "core/b.py").write_text("original = 2\n")
        actual_write = updater._atomic_write
        def fail_once(path, content):
            if path == self.root / "core/b.py":
                raise OSError("disk error")
            actual_write(path, content)
        with patch.object(updater, "_atomic_write", side_effect=fail_once):
            with self.assertRaises(OSError):
                updater.install(self.root, {"core/a.py": b"new = 1\n", "core/b.py": b"new = 2\n"})
        self.assertEqual((self.root / "core/a.py").read_text(), "original = 1\n")
        self.assertEqual((self.root / "core/b.py").read_text(), "original = 2\n")
        backups = list((self.root / ".update-backups").iterdir())
        self.assertEqual((backups[0] / "core/a.py").read_text(), "original = 1\n")

    def test_rejects_unsafe_archives_and_target_symlink(self):
        for name in ("../core/evil.py", "core/../../escape.py", "core/evil\\x.py"):
            with self.subTest(name=name), self.assertRaises(updater.UpdateError):
                updater.release_files(archive({name: "x=1"}))
        with self.assertRaises(updater.UpdateError):
            updater.release_files(archive({"core/bad.py": "this is not python !"}))
        with self.assertRaises(updater.UpdateError):
            updater.release_files(archive({"core/a.py": "x=1", "core/A.py": "x=2"}))
        with self.assertRaises(updater.UpdateError):
            updater.release_files(archive({"data/config.json": "{}"}))
        if hasattr(os, "symlink"):
            try:
                (self.root / "core").symlink_to(Path(self.temp.name).parent, target_is_directory=True)
            except OSError:
                self.skipTest("Symboliska länkar kan inte skapas")
            with self.assertRaises(updater.UpdateError):
                updater.changed_files(self.root, {"core/test.py": b"x=1"})

    def test_no_release_and_valid_url_restriction(self):
        error = urllib.error.HTTPError(updater.API_URL, 404, "not found", {}, None)
        with patch.object(updater, "_get", side_effect=error):
            self.assertIsNone(updater.latest_archive())
        for url in ("http://github.com/a", "https://evil.example/", "https://github.com.evil.example/", "https://user@github.com/a"):
            with self.assertRaises(updater.UpdateError):
                updater._validate_url(url)

    def test_github_request_revalidates_cached_tag_and_release_metadata(self):
        from unittest.mock import Mock
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{}'
        opener = Mock(); opener.open.return_value = response
        with patch.object(updater.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual(updater._get(updater.API_URL, 1024), b'{}')
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Cache-control'), 'no-cache')
        self.assertEqual(request.get_header('Pragma'), 'no-cache')

    def test_same_release_version_new_commit_updates_changed_files_and_preserves_data(self):
        tag = 'v1.0'
        commit = ['a' * 40]
        url = 'https://api.github.com/repos/Tokke2/FR/git/ref/tags/v1.0'
        (self.root / 'data').mkdir()
        (self.root / 'data' / 'vehicles.json').write_text('user data')
        (self.root / 'settings.json').write_text('user settings')
        def get(endpoint, maximum):
            if endpoint == updater.API_URL:
                return json.dumps({'tag_name': tag, 'name': 'Version 1.0', 'draft': False, 'prerelease': False}).encode()
            if endpoint == url:
                return json.dumps({'object': {'type': 'commit', 'sha': commit[0]}}).encode()
            if endpoint.endswith('/zipball/' + commit[0]):
                value = 1 if commit[0] == 'a' * 40 else 2
                return archive({'core/version.py': 'VERSION = "1.0"\n',
                                'core/feature.py': f'VALUE = {value}\n',
                                'settings.json': 'danger', 'data/vehicles.json': 'danger'})
            raise AssertionError(endpoint)
        with patch.object(updater, '_get', side_effect=get):
            first = updater.release_files(updater.latest_archive())
            count, _ = updater.install(self.root, first)
            self.assertEqual(count, 2)
            commit[0] = 'b' * 40
            second = updater.release_files(updater.latest_archive())
            self.assertEqual(set(updater.changed_files(self.root, second)), {'core/feature.py'})
            count, backup = updater.install(self.root, second)
            self.assertEqual(count, 1)
            self.assertEqual((backup / 'core/feature.py').read_text(), 'VALUE = 1\n')
            self.assertEqual((self.root / 'core/feature.py').read_text(), 'VALUE = 2\n')
            self.assertEqual(updater.install(self.root, second), (0, None))
        self.assertEqual((self.root / 'data/vehicles.json').read_text(), 'user data')
        self.assertEqual((self.root / 'settings.json').read_text(), 'user settings')

    def test_release_resolves_annotated_tag_to_immutable_commit(self):
        tag_sha, commit_sha = 'c' * 40, 'd' * 40
        def get(endpoint, maximum):
            if endpoint == updater.API_URL:
                return json.dumps({'tag_name': 'release/1', 'draft': False, 'prerelease': False}).encode()
            if endpoint.endswith('/git/ref/tags/release/1'):
                return json.dumps({'object': {'type': 'tag', 'sha': tag_sha}}).encode()
            if endpoint.endswith('/git/tags/' + tag_sha):
                return json.dumps({'object': {'type': 'commit', 'sha': commit_sha}}).encode()
            if endpoint.endswith('/zipball/' + commit_sha):
                return b'archive'
            raise AssertionError(endpoint)
        with patch.object(updater, '_get', side_effect=get):
            self.assertEqual(updater.latest_archive(), b'archive')

    def test_release_rejects_invalid_tag_and_non_commit_refs(self):
        for tag in ('../test', 'x?x', 'x y', 'a\\b'):
            with self.assertRaises(updater.UpdateError):
                updater._release_commit(tag)
        with patch.object(updater, '_get', return_value=json.dumps({'object': {'type': 'tree', 'sha': 'f' * 40}}).encode()):
            with self.assertRaises(updater.UpdateError):
                updater._release_commit('v1')

    def test_helper_waits_for_parent_pipe_and_installs(self):
        (self.root / "core").mkdir()
        (self.root / "core/a.py").write_text("old = True\n")
        staged = self.root / "release.zip"
        staged.write_bytes(archive({"core/a.py": "new = True\n"}))
        worker = Path(__file__).resolve().parents[1] / "plugins/auto_update/worker.py"
        process = subprocess.Popen([sys.executable, str(worker), str(self.root), str(staged)], stdin=subprocess.PIPE, env={**os.environ, "TMPDIR": str(self.root), "TEMP": str(self.root), "TMP": str(self.root)})
        self.assertEqual((self.root / "core/a.py").read_text(), "old = True\n")
        process.stdin.close()
        self.assertEqual(process.wait(timeout=10), 0)
        self.assertEqual((self.root / "core/a.py").read_text(), "new = True\n")
        self.assertEqual(len(list((self.root / ".update-backups").iterdir())), 1)
        self.assertFalse(staged.exists())

    def test_worker_does_not_install_while_another_instance_holds_lock(self):
        from core.single_instance import SingleInstance
        (self.root / "core").mkdir()
        (self.root / "core/a.py").write_text("old = True\n")
        staged = self.root / "release.zip"
        staged.write_bytes(archive({"core/a.py": "new = True\n"}))
        lock = SingleInstance(lock_dir=self.root)
        self.assertTrue(lock.acquire())
        self.assertTrue(lock.is_acquired)
        self.addCleanup(lock.release)
        worker = Path(__file__).resolve().parents[1] / "plugins/auto_update/worker.py"
        process = subprocess.Popen([sys.executable, str(worker), str(self.root), str(staged)], stdin=subprocess.PIPE, env={**os.environ, "TMPDIR": str(self.root), "TEMP": str(self.root), "TMP": str(self.root)})
        process.stdin.close()
        self.assertEqual(process.wait(timeout=10), 1)
        self.assertEqual((self.root / "core/a.py").read_text(), "old = True\n")

    def test_application_plugin_lifecycle_starts_update_check(self):
        import asyncio
        from types import SimpleNamespace
        from core.plugin_loader import PluginLoader
        from plugins.auto_update import plugin as update_plugin
        loader = PluginLoader(Path(__file__).resolve().parents[1] / 'plugins', app=SimpleNamespace(), auto_discover=True)
        instance = asyncio.run(loader.load('auto_update', retry=False))
        instance.root = self.root
        loader._load_order = ['auto_update']
        process = SimpleNamespace()
        payload = archive({'core/a.py': 'VALUE = 1\n'})
        with patch.object(update_plugin.AutostartManager, 'sync'), \
             patch.object(update_plugin.threading, 'Thread') as thread, \
             patch.object(update_plugin, 'latest_archive', return_value=payload), \
             patch.object(update_plugin.subprocess, 'Popen', return_value=process) as popen:
            initialized = asyncio.run(loader.initialize_all())
            activated = asyncio.run(loader.activate_all())
            self.assertIn('auto_update', initialized.success)
            self.assertIn('auto_update', activated.success)
            target = thread.call_args.kwargs['target']
            self.assertEqual(target, instance._check_for_updates)
            thread.return_value.start.assert_called_once()
            target()
            args = popen.call_args.args[0]
            staged = Path(args[-1])
            self.assertEqual(staged.read_bytes(), payload)
            self.assertEqual(Path(args[-2]), self.root)
            self.assertEqual(args[1], str(Path(update_plugin.__file__).with_name('worker.py')))
            self.assertIn(process, update_plugin._helpers)
            update_plugin._helpers.remove(process)

    def test_manual_update_reports_status_and_avoids_competing_helpers(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from plugins.auto_update import plugin as update_plugin
        instance = update_plugin.Plugin(SimpleNamespace())
        instance.root = self.root
        instance._update_bridge = SimpleNamespace(completed=SimpleNamespace(emit=Mock()))
        payload = archive({'core/a.py': 'x=1\n'})
        process = SimpleNamespace(poll=lambda: None)
        with patch.object(update_plugin, 'latest_archive', return_value=payload), \
             patch.object(update_plugin.subprocess, 'Popen', return_value=process) as popen:
            self.assertEqual(instance._check_for_updates(interactive=True)[0], 'prepared')
            self.assertEqual(instance._check_for_updates(interactive=True)[0], 'pending')
            self.assertEqual(popen.call_count, 1)
            self.assertEqual([c.args[0] for c in instance._update_bridge.completed.emit.call_args_list], ['prepared', 'pending'])
            update_plugin._helpers.remove(process)

    def test_manual_update_reports_no_release_current_error_and_busy(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from plugins.auto_update import plugin as update_plugin
        instance = update_plugin.Plugin(SimpleNamespace())
        instance.root = self.root
        instance._update_bridge = SimpleNamespace(completed=SimpleNamespace(emit=Mock()))
        with patch.object(update_plugin, 'latest_archive', return_value=None):
            self.assertEqual(instance._check_for_updates(interactive=True)[0], 'no_release')
        (self.root / 'core').mkdir()
        (self.root / 'core/a.py').write_text('x=1\n')
        with patch.object(update_plugin, 'latest_archive', return_value=archive({'core/a.py': 'x=1\n'})):
            self.assertEqual(instance._check_for_updates(interactive=True)[0], 'current')
        with patch.object(update_plugin, 'latest_archive', side_effect=OSError('network')):
            self.assertEqual(instance._check_for_updates(interactive=True)[0], 'error')
        with instance._check_lock:
            self.assertEqual(instance._check_for_updates(interactive=True)[0], 'busy')
        self.assertEqual([c.args[0] for c in instance._update_bridge.completed.emit.call_args_list], ['no_release', 'current', 'error', 'busy'])

    def test_manual_check_uses_worker_thread(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from plugins.auto_update import plugin as update_plugin
        instance = update_plugin.Plugin(SimpleNamespace())
        instance._update_action = Mock()
        with patch.object(update_plugin.threading, 'Thread') as thread:
            instance._start_manual_check()
            instance._update_action.setEnabled.assert_called_once_with(False)
            self.assertEqual(thread.call_args.kwargs['target'], instance._check_for_updates)
            self.assertEqual(thread.call_args.kwargs['kwargs'], {'interactive': True})
            thread.return_value.start.assert_called_once()

    def test_plugin_loader_discovers_and_loads_plugin(self):
        import asyncio
        from types import SimpleNamespace
        from core.plugin_loader import PluginLoader
        root = Path(__file__).resolve().parents[1]
        loader = PluginLoader(root / "plugins", app=SimpleNamespace(), auto_discover=True)
        self.assertIn("auto_update", loader.get_discovered())
        plugin = asyncio.run(loader.load("auto_update", retry=False))
        self.assertEqual(plugin.NAME, "auto_update")


class AutostartTests(unittest.TestCase):
    def test_macos_plist_escapes_paths_and_verifies(self):
        import plistlib
        with tempfile.TemporaryDirectory(prefix="app & ") as tmp, patch.object(Path, "home", return_value=Path(tmp)), patch.multiple(autostart, IS_WINDOWS=False, IS_MACOS=True, IS_LINUX=False):
            root = Path(tmp) / "app & files"
            root.mkdir()
            (root / "main.pyw").write_text("pass\n")
            settings = SettingsManager(root / "settings.json")
            manager = autostart.AutostartManager(settings=settings, base_dir=root)
            manager.set_enabled(True)
            self.assertTrue(manager.is_enabled())
            self.assertTrue(manager.verify())
            plist = plistlib.loads(manager._mac_plist_path().read_bytes())
            self.assertEqual(plist["WorkingDirectory"], str(root))
            self.assertEqual(plist["ProgramArguments"][-1], str(root / "main.pyw"))
            manager.set_enabled(False)
            self.assertFalse(manager.is_enabled())

    @staticmethod
    def _fake_windows_shell(args, **kwargs):
        """Simulera WScript.Shell och egenskaperna i en .lnk utan Windows."""
        env = kwargs["env"]
        path = Path(env["FR_SHORTCUT"])
        if "ConvertTo-Json" in args[-1]:
            return subprocess.CompletedProcess(args, 0, stdout=path.read_text(), stderr="")
        info = {"target": env["FR_PYTHON"],
                "arguments": f'"{env["FR_SCRIPT"]}"' if env["FR_SCRIPT"] else "",
                "icon": env["FR_ICON"] + ",0", "directory": env["FR_ROOT"],
                "description": env["FR_DESCRIPTION"]}
        path.write_text(json.dumps(info))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def test_windows_migrates_to_icon_shortcut_and_disables(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"APPDATA": tmp}), patch.multiple(autostart, IS_WINDOWS=True, IS_MACOS=False, IS_LINUX=False):
            root = Path(tmp) / "app"
            root.mkdir()
            (root / "start.pyw").write_text("pass\n")
            (root / "ikon.ico").touch()
            settings = SettingsManager(root / "settings.json")
            settings.set("startup", True)
            manager = autostart.AutostartManager(settings=settings, base_dir=root)
            registry = {"value": manager.build_command()}
            bat = manager._win_bat_path()
            bat.parent.mkdir(parents=True)
            bat.write_text("old")
            def delete():
                registry.clear()
                return True
            with patch('core.desktop_shortcut.subprocess.run', side_effect=self._fake_windows_shell), \
                 patch.object(manager, "_win_registry_get", side_effect=lambda: registry.get("value")), \
                 patch.object(manager, "_win_registry_delete", side_effect=delete):
                manager.sync()
                self.assertFalse(registry)
                self.assertFalse(bat.exists())
                self.assertTrue(settings.get("startup"))
                self.assertTrue(manager.is_enabled())
                self.assertTrue(manager.verify())
                link = manager._win_shortcut_path()
                props = json.loads(link.read_text())
                self.assertEqual(props['icon'], str(root / 'ikon.ico') + ',0')
                self.assertEqual(props['arguments'], f'"{root / "start.pyw"}"')
                self.assertEqual(props['description'], 'Fordonsreg autostart')
                before = link.read_bytes()
                manager.sync()
                self.assertEqual(link.read_bytes(), before)
                self.assertTrue(manager.set_enabled(False))
                self.assertFalse(link.exists())
                self.assertFalse(settings.get("startup"))

    def test_windows_failed_migration_keeps_existing_autostart_and_setting(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"APPDATA": tmp}), patch.multiple(autostart, IS_WINDOWS=True, IS_MACOS=False, IS_LINUX=False):
            root = Path(tmp) / "app"
            root.mkdir()
            (root / "start.pyw").touch()
            (root / "ikon.ico").touch()
            settings = SettingsManager(root / "settings.json")
            settings.set("startup", True)
            manager = autostart.AutostartManager(settings=settings, base_dir=root)
            registry = {"value": manager.build_command()}
            bat = manager._win_bat_path()
            bat.parent.mkdir(parents=True)
            bat.write_text("keep me")
            with patch('core.desktop_shortcut.subprocess.run', side_effect=OSError('blocked')), \
                 patch.object(manager, "_win_registry_get", side_effect=lambda: registry.get("value")), \
                 patch.object(manager, "_win_registry_delete") as delete:
                manager.sync()
                self.assertFalse(manager.set_enabled(True))
                delete.assert_not_called()
                self.assertIn("value", registry)
                self.assertEqual(bat.read_text(), "keep me")
                self.assertTrue(settings.get("startup"))
                self.assertFalse(manager._win_shortcut_path().exists())

    def test_windows_unknown_shortcut_is_not_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"APPDATA": tmp}), patch.multiple(autostart, IS_WINDOWS=True, IS_MACOS=False, IS_LINUX=False):
            root = Path(tmp) / "app"
            root.mkdir()
            (root / "start.pyw").touch()
            (root / "ikon.ico").touch()
            settings = SettingsManager(root / "settings.json")
            manager = autostart.AutostartManager(settings=settings, base_dir=root)
            link = manager._win_shortcut_path()
            link.parent.mkdir(parents=True)
            link.write_text(json.dumps({"description": "Eget program"}))
            original = link.read_bytes()
            with patch('core.desktop_shortcut.subprocess.run', side_effect=self._fake_windows_shell):
                self.assertFalse(manager.set_enabled(True))
                self.assertEqual(link.read_bytes(), original)
                self.assertTrue(manager.set_enabled(False))
                self.assertEqual(link.read_bytes(), original)

    def test_windows_failed_repair_preserves_existing_shortcut(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"APPDATA": tmp}), patch.multiple(autostart, IS_WINDOWS=True, IS_MACOS=False, IS_LINUX=False):
            root = Path(tmp) / "app"
            root.mkdir()
            (root / "start.pyw").touch()
            (root / "ikon.ico").touch()
            manager = autostart.AutostartManager(base_dir=root)
            link = manager._win_shortcut_path()
            link.parent.mkdir(parents=True)
            link.write_text(json.dumps({"description": "Fordonsreg autostart", "icon": "old"}))
            original = link.read_bytes()
            def invalid_shell(args, **kwargs):
                result = self._fake_windows_shell(args, **kwargs)
                if 'ConvertTo-Json' in args[-1] and '.fordonsreg-' in kwargs['env']['FR_SHORTCUT']:
                    props = json.loads(result.stdout)
                    props['icon'] = 'wrong'
                    result.stdout = json.dumps(props)
                return result
            with patch('core.desktop_shortcut.subprocess.run', side_effect=invalid_shell):
                self.assertFalse(manager.set_enabled(True))
                self.assertEqual(link.read_bytes(), original)

    def test_windows_repair_does_not_overwrite_concurrent_shortcut_change(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"APPDATA": tmp}), patch.multiple(autostart, IS_WINDOWS=True, IS_MACOS=False, IS_LINUX=False):
            root = Path(tmp) / "app"
            root.mkdir()
            (root / "start.pyw").touch()
            (root / "ikon.ico").touch()
            manager = autostart.AutostartManager(base_dir=root)
            link = manager._win_shortcut_path()
            link.parent.mkdir(parents=True)
            link.write_text(json.dumps({"description": "Fordonsreg autostart", "icon": "old"}))
            changed = b'user changed the shortcut'
            def race_shell(args, **kwargs):
                result = self._fake_windows_shell(args, **kwargs)
                if 'ConvertTo-Json' in args[-1] and '.fordonsreg-' in kwargs['env']['FR_SHORTCUT']:
                    link.write_bytes(changed)
                return result
            with patch('core.desktop_shortcut.subprocess.run', side_effect=race_shell):
                self.assertFalse(manager.set_enabled(True))
                self.assertEqual(link.read_bytes(), changed)

    def test_autostart_prefers_launcher_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.pyw").touch()
            (root / "start.pyw").touch()
            manager = autostart.AutostartManager(base_dir=root)
            self.assertEqual(manager._find_entry_script(), root / "start.pyw")

    def test_linux_missing_icon_does_not_replace_existing_autostart(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}), patch.multiple(autostart, IS_WINDOWS=False, IS_MACOS=False, IS_LINUX=True):
            root = Path(tmp) / "app"
            root.mkdir()
            (root / "start.pyw").touch()
            settings = SettingsManager(root / "settings.json")
            settings.set("startup", True)
            manager = autostart.AutostartManager(settings=settings, base_dir=root)
            desktop = manager._linux_desktop_path()
            desktop.parent.mkdir(parents=True)
            desktop.write_text('old autostart')
            manager.sync()
            self.assertEqual(desktop.read_text(), 'old autostart')
            self.assertTrue(settings.get("startup"))
            self.assertFalse(manager.set_enabled(True))
            self.assertEqual(desktop.read_text(), 'old autostart')

    def test_linux_enable_sync_and_disable(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}), patch.multiple(autostart, IS_WINDOWS=False, IS_MACOS=False, IS_LINUX=True):
            root = Path(tmp) / "app"
            root.mkdir()
            (root / "main.pyw").write_text("pass\n")
            (root / "ikon_256.png").touch()
            settings = SettingsManager(root / "settings.json")
            manager = autostart.AutostartManager(settings=settings, base_dir=root)
            manager.set_enabled(True)
            self.assertTrue(manager.is_enabled())
            self.assertTrue(manager.verify())
            self.assertTrue(settings.get("startup"))
            desktop = manager._linux_desktop_path()
            self.assertIn(f"Icon={root / 'ikon_256.png'}", desktop.read_text())
            self.assertIn("Name=Fordonsreg\n", desktop.read_text())
            desktop.write_text(desktop.read_text().replace("Name=Fordonsreg\n", "Name=Filregistrering\n"))
            self.assertFalse(manager.verify())
            manager.sync()
            self.assertIn("Name=Fordonsreg\n", desktop.read_text())
            desktop.write_text(desktop.read_text().replace(f"Path={root}\n", ""))
            self.assertFalse(manager.verify())
            manager.sync()
            self.assertTrue(manager.verify())
            manager.set_enabled(False)
            self.assertFalse(manager.is_enabled())
            self.assertFalse(settings.get("startup"))


if __name__ == "__main__":
    unittest.main()
