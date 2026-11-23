from __future__ import annotations

import logging
import os
from pathlib import Path
from datetime import date
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from core.error_summary import ErrorSummaryHandler, _append

ROOT = Path(__file__).resolve().parents[1]


class ErrorSummaryTests(unittest.TestCase):
    def test_summary_file_is_available_before_first_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = ErrorSummaryHandler(Path(tmp), 'app')
            try:
                path = Path(tmp) / 'felsokning.log'
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_text(), '')
            finally:
                handler.close()

    def test_warnings_errors_tracebacks_and_duplicate_propagation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = logging.getLogger('summary_test')
            child = logging.getLogger('summary_test.vehicle')
            for log in (root, child):
                log.handlers.clear()
                log.setLevel(logging.DEBUG)
            root.propagate = False
            child.propagate = True
            root.addHandler(ErrorSummaryHandler(Path(tmp), 'app'))
            child.addHandler(ErrorSummaryHandler(Path(tmp), 'lokal'))
            try:
                child.info('normal info ska inte med')
                child.warning('warning-exempel')
                try:
                    raise ValueError('test-orsak')
                except ValueError:
                    child.exception('importfel-test')
                contents = (Path(tmp) / 'felsokning.log').read_text(encoding='utf-8')
                self.assertNotIn('normal info', contents)
                self.assertEqual(contents.count('warning-exempel'), 1)
                self.assertEqual(contents.count('importfel-test'), 1)
                self.assertIn('[lokal]', contents)
                self.assertIn('[summary_test.vehicle]', contents)
                self.assertIn('ValueError: test-orsak', contents)
            finally:
                for log in (root, child):
                    for handler in list(log.handlers):
                        log.removeHandler(handler)
                        handler.close()
                root.propagate = True

    def test_duplicate_guard_is_per_destination(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            logger = logging.getLogger('summary-destinations')
            logger.handlers.clear(); logger.setLevel(logging.DEBUG); logger.propagate = False
            handlers = [ErrorSummaryHandler(Path(one), 'one'), ErrorSummaryHandler(Path(two), 'two')]
            for handler in handlers: logger.addHandler(handler)
            try:
                logger.error('both-targets')
                self.assertIn('both-targets', (Path(one) / 'felsokning.log').read_text())
                self.assertIn('both-targets', (Path(two) / 'felsokning.log').read_text())
            finally:
                for handler in handlers:
                    logger.removeHandler(handler); handler.close()
                logger.propagate = True

    def test_rotation_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(4):
                _append(root, f'{index}: ' + 'x' * 75, max_bytes=180, backups=3)
            files = [root / 'felsokning.log', root / 'felsokning.log.1']
            text = ''.join(f.read_text() for f in files)
            for index in range(4):
                self.assertIn(f'{index}: ', text)
            if not hasattr(os, 'symlink'):
                return
            target = root / 'untouched.txt'
            target.write_text('keep')
            (root / 'felsokning.log').unlink()
            try:
                (root / 'felsokning.log').symlink_to(target)
            except OSError:
                self.skipTest('Symboliska länkar kan inte skapas')
            with self.assertRaises(OSError):
                _append(root, 'not allowed', max_bytes=180, backups=3)
            self.assertEqual(target.read_text(), 'keep')

    @unittest.skipIf(os.name == 'nt', 'Parallelltestet körs på POSIX; Windows-låset simuleras separat')
    def test_parallel_processes_write_and_rotate_without_interleaving(self):
        script = '''
import logging, sys
from pathlib import Path
from core.error_summary import ErrorSummaryHandler
log = logging.getLogger('multi')
log.setLevel(logging.DEBUG)
log.addHandler(ErrorSummaryHandler(Path(sys.argv[1]), 'app', max_bytes=2400, backups=30))
log.propagate = False
for i in range(50):
    log.error('unique=%s-%03d', sys.argv[2], i)
'''
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}
            processes = [subprocess.Popen([sys.executable, '-c', script, tmp, str(i)], env=env,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(4)]
            for process in processes:
                _, err = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, err.decode())
            lines = []
            for path in Path(tmp).glob('felsokning.log*'):
                lines.extend(path.read_text(encoding='utf-8').splitlines())
            self.assertEqual(len(lines), 200)
            for i in range(4):
                for j in range(50):
                    self.assertEqual(sum(f'unique={i}-{j:03d}' in line for line in lines), 1)
            self.assertTrue((Path(tmp) / 'felsokning.log.1').exists())

    def test_windows_lock_api_is_used_for_the_same_lock_byte(self):
        import core.error_summary as summary
        calls = []
        fake = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2,
                                     locking=lambda fd, operation, count: calls.append((operation, count)))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'lock'
            with patch.dict(sys.modules, {'msvcrt': fake}), patch.object(summary.os, 'name', 'nt'):
                with summary._process_lock(path):
                    self.assertEqual(calls, [(1, 1)])
            self.assertEqual(calls, [(1, 1), (2, 1)])
            self.assertEqual(path.read_bytes(), b'0')

    def test_update_worker_exception_is_written_to_both_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'bad.zip'; archive.write_bytes(b'not a zip')
            worker = ROOT / 'plugins/auto_update/worker.py'
            process = subprocess.run([sys.executable, str(worker), str(root), str(archive)],
                                     input=b'', capture_output=True, timeout=20)
            self.assertEqual(process.returncode, 1, process.stderr.decode())
            summary = (root / 'logs/felsokning.log').read_text(encoding='utf-8')
            self.assertIn('[uppdatering]', summary)
            self.assertIn('Automatisk uppdatering misslyckades', summary)
            self.assertIn('BadZipFile', summary)
            self.assertIn('Automatisk uppdatering misslyckades', (root / 'logs/auto_update.log').read_text())
            daily = (root / 'logs/dagliga' / f'{date.today().isoformat()}.log').read_text(encoding='utf-8')
            self.assertIn('Automatisk uppdatering misslyckades', daily)
            self.assertFalse(archive.exists())

    def test_broken_bootstrap_import_is_reported_before_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'core').mkdir()
            (root / 'start.pyw').write_bytes((ROOT / 'start.pyw').read_bytes())
            (root / 'core/error_summary.py').write_bytes((ROOT / 'core/error_summary.py').read_bytes())
            (root / 'core/dependencies.py').write_text("raise RuntimeError('BROKEN_DEPENDENCIES')\n")
            env = {**os.environ, 'PYTHONPATH': str(root), 'PYTHONDONTWRITEBYTECODE': '1'}
            process = subprocess.run([sys.executable, str(root / 'start.pyw')], cwd=root,
                                     env=env, capture_output=True, timeout=20)
            self.assertNotEqual(process.returncode, 0)
            contents = (root / 'logs/felsokning.log').read_text(encoding='utf-8')
            self.assertIn('[startkontroll]', contents)
            self.assertIn('RuntimeError: BROKEN_DEPENDENCIES', contents)

    def test_unhandled_early_app_import_error_includes_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'core').mkdir()
            (root / 'main.pyw').write_bytes((ROOT / 'main.pyw').read_bytes())
            (root / 'core/error_summary.py').write_bytes((ROOT / 'core/error_summary.py').read_bytes())
            (root / 'core/event_bus.py').write_text("raise RuntimeError('EARLY_TEST_FAILURE')\n")
            env = {**os.environ, 'FR_PREFLIGHT_DONE': '1', 'PYTHONPATH': str(root), 'PYTHONDONTWRITEBYTECODE': '1'}
            process = subprocess.run([sys.executable, str(root / 'main.pyw'), '--headless'],
                                     cwd=root, env=env, capture_output=True, timeout=20)
            self.assertNotEqual(process.returncode, 0)
            summary = (root / 'logs/felsokning.log').read_text(encoding='utf-8')
            self.assertIn('[app-start]', summary)
            self.assertIn('RuntimeError: EARLY_TEST_FAILURE', summary)


if __name__ == '__main__':
    unittest.main()
