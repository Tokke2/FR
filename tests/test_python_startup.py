from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('no_python_update_start_test', str(ROOT / 'start.pyw'))
spec = importlib.util.spec_from_loader(loader.name, loader)
start = importlib.util.module_from_spec(spec)
loader.exec_module(start)


class PythonPolicyTests(unittest.TestCase):
    def test_existing_python_never_prompts_or_schedules_system_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'logs').mkdir()
            child = SimpleNamespace(stdout=io.BufferedReader(io.BytesIO(b'')), wait=lambda: 0)
            with patch.object(start, 'ROOT', root), patch.object(start, '_claim_weekly', return_value=True), \
                 patch.object(start, 'check_dependencies', return_value=True), \
                 patch.object(start, '_message') as message, \
                 patch.object(start.subprocess, 'Popen', return_value=child) as spawn:
                self.assertEqual(start._run_with_launcher_lock(logging.getLogger('test.policy')), 0)
                message.assert_not_called()
                self.assertEqual(spawn.call_count, 1)
                self.assertEqual(spawn.call_args.args[0][0], sys.executable)
        self.assertFalse((ROOT / 'tools/install_latest_python.py').exists())
        self.assertFalse((ROOT / 'Installera senaste Python.bat').exists())

    def test_windows_launcher_guards_installation_with_presence_and_consent(self):
        code = (ROOT / 'start_fordonsreg.ps1').read_text(encoding='utf-8')
        self.assertLess(code.index('$python = Find-Python'), code.index('if (!$python)'))
        self.assertLess(code.index('if (!$python)'), code.index('winget.Source install'))
        self.assertLess(code.index('[System.Windows.Forms.DialogResult]::Yes'), code.index('winget.Source install'))
        self.assertIn('WindowsApps', code)
        self.assertIn('PythonCore', code)
        self.assertIn('ingen ny installation', code.lower())
        self.assertNotIn('winget.Source upgrade', code)


class NativeLauncherTests(unittest.TestCase):
    def launch(self, system='Linux', answer='', python=None, installed=False, opener=True):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); tools = root / 'bin'; tools.mkdir()
            source = (ROOT / 'start_fordonsreg.sh').read_text()
            # macOS search paths are redirected to this sandbox; the logic is unchanged.
            if system == 'Darwin':
                source = source.replace('/usr/local/bin/python3', str(root / 'absent/local/python3'))
                source = source.replace('/opt/homebrew/bin/python3', str(root / 'absent/homebrew/python3'))
                source = source.replace('/Library/Frameworks/Python.framework/Versions/', str(root / 'absent/Versions/'))
            script = root / 'start.sh'; script.write_text(source)
            for name in ('dirname', 'grep'):
                (tools / name).symlink_to(shutil.which(name))
            commands = {'uname': 'echo ' + system,
                        'dpkg-query': 'echo installed' if installed else 'exit 1',
                        'pkgutil': 'echo org.python.Python.PythonFramework-3.13' if installed else 'exit 0',
                        'rpm': 'exit 1', 'pacman': 'exit 1'}
            if opener:
                commands['xdg-open'] = 'printf "%s" "$1" > "$OPENED"'
                commands['open'] = 'printf "%s" "$1" > "$OPENED"'
            if python:
                name, body = python
                commands[name] = body
            for name, body in commands.items():
                command = tools / name
                command.write_text('#!/bin/sh\n' + body + '\n')
                command.chmod(0o755)
            opened, invoked = root / 'opened', root / 'invoked'
            env = dict(os.environ, PATH=str(tools), OPENED=str(opened), INVOKED=str(invoked))
            result = subprocess.run(['/bin/sh', str(script)], input=answer, text=True,
                                    capture_output=True, env=env, timeout=10)
            return result, opened.read_text() if opened.exists() else None, invoked.exists()

    def test_existing_python_starts_without_install_question_on_linux_and_mac(self):
        for system in ('Linux', 'Darwin'):
            with self.subTest(system=system):
                result, opened, invoked = self.launch(system, python=('python3', 'echo used > "$INVOKED"; exit 0'))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(invoked); self.assertIsNone(opened)
                self.assertNotIn('[j/N]', result.stdout)

    def test_versioned_python_is_used_without_question(self):
        result, opened, invoked = self.launch(python=('python3.13', 'echo used > "$INVOKED"; exit 0'))
        self.assertEqual(result.returncode, 0)
        self.assertTrue(invoked); self.assertIsNone(opened)

    def test_broken_or_registered_python_never_offers_install(self):
        for system in ('Linux', 'Darwin'):
            for kwargs in ({'installed': True}, {'python': ('python3', 'exit 1')}):
                with self.subTest(system=system, kwargs=kwargs):
                    result, opened, _ = self.launch(system, answer='j\n', **kwargs)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIsNone(opened)
                    self.assertNotIn('[j/N]', result.stdout)

    def test_missing_python_offers_official_site_only_with_consent(self):
        for system in ('Linux', 'Darwin'):
            with self.subTest(system=system):
                result, opened, _ = self.launch(system, answer='n\n')
                self.assertEqual(result.returncode, 0); self.assertIsNone(opened)
                self.assertIn('[j/N]', result.stdout)
                result, opened, _ = self.launch(system, answer='j\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(opened, 'https://www.python.org/downloads/')
                self.assertIn('manuellt', result.stdout)

    def test_missing_browser_shows_official_link(self):
        result, opened, _ = self.launch(answer='j\n', opener=False)
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(opened)
        self.assertIn('https://www.python.org/downloads/', result.stdout)


if __name__ == '__main__':
    unittest.main()
