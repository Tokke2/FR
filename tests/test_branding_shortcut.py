from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from core.branding import APP_NAME, display_name
from core.desktop_shortcut import ShortcutError, create_desktop_shortcut
from plugins.auto_update import updater

ROOT = Path(__file__).resolve().parents[1]


def load_main():
    loader = importlib.machinery.SourceFileLoader('fordonsreg_test_main', str(ROOT / 'main.pyw'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def archive(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for name, content in entries.items():
            z.writestr('FR-release/' + name, content)
    return stream.getvalue()


class BrandingTests(unittest.TestCase):
    def test_default_and_legacy_names_and_custom_names(self):
        self.assertEqual(APP_NAME, 'Fordonsreg')
        self.assertEqual(json.loads((ROOT / 'config.json').read_text())['app_name'], APP_NAME)
        for previous in ('Filregistrering', 'Transportstyrelsen Fordonsregistreringssystem', 'TADEGA Fordonsregistrering', ''):
            self.assertEqual(display_name(previous), APP_NAME)
        self.assertEqual(display_name('Mitt eget namn'), 'Mitt eget namn')
        self.assertEqual(display_name(' Mitt eget namn '), ' Mitt eget namn ')

    def test_runtime_migration_preserves_config_and_custom_values(self):
        main = load_main()
        for original, expected in [('Filregistrering', 'Fordonsreg'), ('Mitt eget namn', 'Mitt eget namn')]:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'config.json'
                path.write_text(json.dumps({'app_name': original, 'theme': 'dark'}), encoding='utf-8')
                before = path.read_bytes()
                main.Application._instance = None
                app = main.Application(config_path=path, headless=True)
                asyncio.run(app._load_configuration())
                self.assertEqual(app.config.get_str('app_name'), expected)
                self.assertEqual(app.config.get_str('theme'), 'dark')
                self.assertEqual(path.read_bytes(), before)

    def test_windows_app_id_is_distinct(self):
        from core import branding
        captured = []
        fake = SimpleNamespace(windll=SimpleNamespace(shell32=SimpleNamespace(
            SetCurrentProcessExplicitAppUserModelID=lambda value: captured.append(value) or 0)))
        with patch.object(branding.sys, 'platform', 'win32'), patch.dict(sys.modules, {'ctypes': fake}):
            self.assertTrue(branding.set_windows_app_id())
        self.assertEqual(captured, ['se.langkvist.fordonsreg'])

    def test_qt_start_sets_name_and_icon_before_plugins(self):
        main = load_main()
        main.Application._instance = None
        app = main.Application(headless=False)
        app.config = main.Configuration.from_dict({'app_name': 'Fordonsreg', 'app_author': 'Tester'})
        fake = SimpleNamespace(aboutToQuit=SimpleNamespace(connect=lambda callback: None))
        fake.setApplicationName = lambda value: setattr(fake, 'name', value)
        fake.setApplicationVersion = lambda value: setattr(fake, 'version', value)
        fake.setOrganizationName = lambda value: setattr(fake, 'organization', value)
        qt = SimpleNamespace(QApplication=SimpleNamespace(instance=lambda: fake))
        with patch.dict(sys.modules, {'PySide6.QtWidgets': qt}), \
             patch('core.branding.set_windows_app_id') as set_id, \
             patch('plugins.app_icon.plugin.set_application_icon') as set_icon:
            app._init_qt()
        self.assertEqual(fake.name, 'Fordonsreg')
        set_id.assert_called_once()
        set_icon.assert_called_once_with(ROOT)

    def test_icon_assets_are_valid_sizes_and_ico_contains_multiple_sizes(self):
        for size in (16, 32, 64, 256):
            data = (ROOT / f'ikon_{size}.png').read_bytes()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II', data[16:24]), (size, size))
            updater._validate_icon(f'ikon_{size}.png', data)
        icon = (ROOT / 'ikon.ico').read_bytes()
        updater._validate_icon('ikon.ico', icon)
        count = int.from_bytes(icon[4:6], 'little')
        self.assertGreaterEqual(count, 4)
        sizes = {icon[6 + i * 16] or 256 for i in range(count)}
        self.assertTrue({16, 32, 64, 256}.issubset(sizes))

    def test_release_icon_backup_and_strict_whitelist(self):
        data = (ROOT / 'ikon_32.png').read_bytes()
        files = updater.release_files(archive({'ikon_32.png': data, 'config.json': b'{"danger":1}', 'data/secret.png': b'ignored'}))
        self.assertEqual(files, {'ikon_32.png': data})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'ikon_32.png').write_bytes(b'old custom icon')
            count, backup = updater.install(root, files)
            self.assertEqual(count, 1)
            self.assertEqual((backup / 'ikon_32.png').read_bytes(), b'old custom icon')
            self.assertEqual((root / 'ikon_32.png').read_bytes(), data)
        with self.assertRaises(updater.UpdateError):
            updater.release_files(archive({'ikon_32.png': b'not png'}))
        with self.assertRaises(updater.UpdateError):
            updater.release_files(archive({'ikon_64.png': data}))
        with self.assertRaises(updater.UpdateError):
            updater.release_files(archive({'ikon.ico': b'not ico'}))


class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'App $% with spaces'
        self.root.mkdir()
        self.desktop = self.base / 'Desktop'
        self.desktop.mkdir()
        for name in ('start.pyw', 'ikon.ico', 'ikon_256.png', 'python.exe', 'pythonw.exe'):
            (self.root / name).touch()

    def test_linux_shortcut_has_icon_escapes_and_no_overwrite(self):
        result = create_desktop_shortcut(self.root, desktop=self.desktop, platform='linux', executable=str(self.root / 'python.exe'))
        content = result.read_text()
        self.assertIn('Name=Fordonsreg\n', content)
        self.assertIn('Icon=' + str(self.root / 'ikon_256.png'), content)
        self.assertIn('Exec="', content)
        self.assertIn('\\$%%', content)
        self.assertIn('start.pyw"', content)
        self.assertTrue(result.stat().st_mode & 0o100)
        with self.assertRaises(ShortcutError):
            create_desktop_shortcut(self.root, desktop=self.desktop, platform='linux', executable=str(self.root / 'python.exe'))
        self.assertEqual(result.read_text(), content)

    def test_windows_uses_pythonw_icon_and_passes_paths_as_environment(self):
        def run(args, **kwargs):
            env = kwargs['env']
            self.assertEqual(env['FR_PYTHON'], str(self.root / 'pythonw.exe'))
            self.assertEqual(env['FR_ICON'], str(self.root / 'ikon.ico'))
            self.assertEqual(env['FR_SCRIPT'], str(self.root / 'start.pyw'))
            self.assertNotIn(str(self.root), args[-1])
            Path(env['FR_SHORTCUT']).write_bytes(b'link')
            return SimpleNamespace(returncode=0)
        with patch('core.desktop_shortcut.subprocess.run', side_effect=run):
            path = create_desktop_shortcut(self.root, desktop=self.desktop, platform='win32', executable=str(self.root / 'python.exe'))
        self.assertEqual(path.read_bytes(), b'link')
        with patch('core.desktop_shortcut.subprocess.run') as process, self.assertRaises(ShortcutError):
            create_desktop_shortcut(self.root, desktop=self.desktop, platform='win32', executable=str(self.root / 'python.exe'))
        process.assert_not_called()
        self.assertEqual(path.read_bytes(), b'link')

    def test_windows_failed_creation_cleans_temporary_files(self):
        with patch('core.desktop_shortcut.subprocess.run', side_effect=subprocess.TimeoutExpired('powershell', 30)), self.assertRaises(ShortcutError):
            create_desktop_shortcut(self.root, desktop=self.desktop, platform='win32', executable=str(self.root / 'python.exe'))
        self.assertEqual(list(self.desktop.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
