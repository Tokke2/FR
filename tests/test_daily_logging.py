from __future__ import annotations

from datetime import date, timedelta
import json
import logging
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from core.daily_logging import DailyLogHandler, append_daily, archive_old_days, record_error_code, resolve_config_parse_error
from core.exceptions import ConfigParseError, CoreError
from core.config import Configuration

ROOT = Path(__file__).resolve().parents[1]


class DailyArchiveTests(unittest.TestCase):
    def test_day_boundary_moves_old_logs_without_losing_today_or_existing_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); today = date(2026, 11, 4); yesterday = today - timedelta(days=1)
            append_daily(root, yesterday, 'gårdag: åäö', today=yesterday)
            append_daily(root, today, 'idag', today=yesterday)
            archive_old_days(root, today)
            self.assertEqual((root / 'arkiv/2026-11-03.log').read_text(), 'gårdag: åäö\n')
            self.assertEqual((root / 'dagliga/2026-11-04.log').read_text(), 'idag\n')
            self.assertFalse((root / 'dagliga/2026-11-03.log').exists())
            # Försenade poster sparas i ett nytt arkiv, aldrig över en befintlig fil.
            append_daily(root, yesterday, 'sen post', today=today)
            self.assertEqual((root / 'arkiv/2026-11-03.log').read_text(), 'gårdag: åäö\n')
            self.assertEqual((root / 'arkiv/2026-11-03-1.log').read_text(), 'sen post\n')
            archive_old_days(root, today)
            self.assertEqual(len(list((root / 'arkiv').iterdir())), 2)

    def test_archive_copy_failure_preserves_original_and_removes_incomplete_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); yesterday = date(2026, 11, 3)
            append_daily(root, yesterday, 'viktigt', today=yesterday)
            with patch('core.daily_logging.shutil.copyfileobj', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): archive_old_days(root, date(2026, 11, 4))
            self.assertEqual((root / 'dagliga/2026-11-03.log').read_text(), 'viktigt\n')
            self.assertEqual(list((root / 'arkiv').iterdir()), [])
            archive_old_days(root, date(2026, 11, 4))
            self.assertEqual((root / 'arkiv/2026-11-03.log').read_text(), 'viktigt\n')

    def test_archive_handles_missed_days_future_dates_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); daily = root / 'dagliga'; daily.mkdir()
            for name in ('2026-01-01.log', '2026-11-03.log', '2027-01-01.log', 'unknown.log'):
                (daily / name).write_text(name)
            archive_old_days(root, date(2026, 11, 4))
            self.assertEqual({p.name for p in (root / 'arkiv').iterdir()}, {'2026-01-01.log', '2026-11-03.log'})
            self.assertEqual({p.name for p in daily.iterdir()}, {'2027-01-01.log', 'unknown.log'})

    def test_monitor_archives_without_new_log_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            yesterday = date.today() - timedelta(days=1)
            append_daily(root, yesterday, 'gammal', today=yesterday)
            handler = DailyLogHandler(root, 'test', monitor=False)
            self.assertTrue((root / 'arkiv' / f'{yesterday.isoformat()}.log').exists())
            older = yesterday - timedelta(days=1)
            append_daily(root, older, 'äldre', today=older)
            handler._stop = Mock()
            handler._stop.wait.side_effect = [False, True]
            handler._monitor()
            self.assertTrue((root / 'arkiv' / f'{older.isoformat()}.log').exists())
            handler.close()

    def test_symlinked_daily_file_is_never_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'dagliga').mkdir()
            victim = root / 'private'; victim.write_text('bevara')
            try:
                (root / 'dagliga/2026-01-01.log').symlink_to(victim)
            except OSError:
                self.skipTest('Symboliska länkar stöds inte')
            with self.assertRaises(OSError): archive_old_days(root, date(2026, 1, 2))
            self.assertEqual(victim.read_text(), 'bevara')

    @unittest.skipIf(os.name == 'nt', 'Parallelltest körs på POSIX')
    def test_parallel_processes_preserve_every_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = '''
import sys
from pathlib import Path
from datetime import date
from core.daily_logging import append_daily
for i in range(40): append_daily(Path(sys.argv[1]), date(2026,1,1), f'{sys.argv[2]}-{i:03}', today=date(2026,1,1))
'''
            env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}
            ps = [subprocess.Popen([sys.executable, '-c', script, tmp, str(i)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(4)]
            for p in ps:
                _, err = p.communicate(timeout=30); self.assertEqual(p.returncode, 0, err.decode())
            archive_old_days(Path(tmp), date(2026, 1, 2))
            lines = (Path(tmp) / 'arkiv/2026-01-01.log').read_text().splitlines()
            self.assertEqual(len(lines), 160); self.assertEqual(len(set(lines)), 160)


class ActiveCodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = logging.getLogger(f'code-test-{id(self)}'); self.log.handlers.clear(); self.log.propagate = False
        self.log.setLevel(logging.DEBUG)
        self.handler = DailyLogHandler(self.root, 'test'); self.log.addHandler(self.handler)
        def cleanup():
            self.log.removeHandler(self.handler); self.handler.close(); self.log.propagate = True
        self.addCleanup(cleanup)

    def entries(self):
        return list(json.loads((self.root / 'felkoder.json').read_text(encoding='utf-8'))['entries'].values())

    def test_only_explicit_codes_are_stored_without_guessing_from_message(self):
        self.log.error('Ordinary error or [IMPORT_ERROR] in text')
        self.assertFalse((self.root / 'felkoder.json').exists())
        self.log.error('Structured code', extra={'error_code': 'IMPORT_ERROR'})
        self.log.error('bad code', extra={'error_code': '../bad'})
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]['code'], entries[0]['status']), ('IMPORT_ERROR', 'aktiv'))
        self.assertIn('Ordinary error', next((self.root / 'dagliga').glob('*.log')).read_text())

    def test_actual_exception_as_argument_and_traceback_are_detected(self):
        error = CoreError('failure', error_code='IMPORT_ERROR')
        self.log.error('An error: %s', error)
        try:
            raise CoreError('other failure', error_code='EXPORT_ERROR')
        except CoreError:
            self.log.exception('Exception')
        self.assertEqual({e['code'] for e in self.entries()}, {'IMPORT_ERROR', 'EXPORT_ERROR'})
        self.assertTrue(all(e['status'] == 'aktiv' for e in self.entries()))

    def test_config_parse_verified_only_for_same_file_and_after_failure(self):
        first = self.root / 'config.json'; second = self.root / 'other.json'
        first.write_text('{bad'); second.write_text('{}')
        try:
            Configuration._load_json_file(first, 'utf-8')
        except ConfigParseError as exc:
            self.log.error('Config: %s', exc)
        self.assertEqual(self.entries()[0]['status'], 'aktiv')
        with patch('core.log_paths.app_log_dir', return_value=self.root):
            Configuration._load_json_file(second, 'utf-8')
            self.assertEqual(self.entries()[0]['status'], 'aktiv')
            first.write_text('{"name": "test"}')
            Configuration._load_json_file(first, 'utf-8')
        entry = self.entries()[0]
        self.assertEqual(entry['status'], 'åtgärdad')
        self.assertIn('parsats', entry['verification'])
        # Samma fel kan uppstå igen och blir då aktivt på nytt.
        self.log.error('Again: %s', ConfigParseError('invalid', config_path=first))
        self.assertEqual(self.entries()[0]['status'], 'aktiv')
        self.assertEqual(self.entries()[0]['count'], 2)

    def test_failure_after_verification_started_cannot_be_cleared(self):
        path = self.root / 'config.json'
        started = time.time()
        self.log.error('Config: %s', ConfigParseError('bad', config_path=path))
        self.assertFalse(resolve_config_parse_error(self.root, path, started_at=started))
        self.assertEqual(self.entries()[0]['status'], 'aktiv')

    @unittest.skipIf(os.name == 'nt', 'Parallelltest körs på POSIX')
    def test_parallel_code_updates_do_not_lose_occurrences(self):
        script = """
import logging, sys
from pathlib import Path
from core.daily_logging import record_error_code
for i in range(30):
 r = logging.LogRecord('same', logging.ERROR, 'same.py', 4, 'same error', (), None)
 r.error_code = 'IMPORT_ERROR'
 record_error_code(Path(sys.argv[1]), r)
"""
        env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}
        processes = [subprocess.Popen([sys.executable, '-c', script, str(self.root)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
        for p in processes:
            _, err = p.communicate(timeout=30)
            self.assertEqual(p.returncode, 0, err.decode())
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.entries()[0]['count'], 120)

    def test_corrupt_register_is_preserved_not_silently_overwritten(self):
        path = self.root / 'felkoder.json'; path.write_text('{ valuable invalid json')
        record = logging.LogRecord('test', logging.ERROR, __file__, 1, 'bad', (), None)
        record.error_code = 'IMPORT_ERROR'
        with self.assertRaises(ValueError): record_error_code(self.root, record)
        self.assertEqual(path.read_text(), '{ valuable invalid json')

class ActualStartupCodeTests(unittest.TestCase):
    def test_broken_then_fixed_config_resolves_the_exact_program_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'app'; root.mkdir()
            shutil.copytree(ROOT / 'core', root / 'core', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copyfile(ROOT / 'main.pyw', root / 'main.pyw')
            config = root / 'config.json'; config.write_text('{invalid', encoding='utf-8')
            env = {**os.environ, 'PYTHONPATH': str(root), 'FR_PREFLIGHT_DONE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
            command = [sys.executable, str(root / 'main.pyw'), '--validate-config']
            failed = subprocess.run(command, cwd=tmp, env=env, capture_output=True, timeout=30)
            self.assertNotEqual(failed.returncode, 0)
            codes_path = root / 'logs/felkoder.json'
            entries = list(json.loads(codes_path.read_text(encoding='utf-8'))['entries'].values())
            self.assertEqual([(e['code'], e['status']) for e in entries], [('CONFIG_PARSE_ERROR', 'aktiv')])
            config.write_text(json.dumps({'app_name': 'Fordonsreg', 'plugins': {'enabled': []}}), encoding='utf-8')
            success = subprocess.run(command, cwd=tmp, env=env, capture_output=True, timeout=30)
            self.assertEqual(success.returncode, 0, success.stderr.decode())
            entries = list(json.loads(codes_path.read_text(encoding='utf-8'))['entries'].values())
            self.assertEqual(entries[0]['status'], 'åtgärdad')
            daily = list((root / 'logs/dagliga').glob('*.log'))
            self.assertEqual(len(daily), 1)
            self.assertIn('Error:', daily[0].read_text(encoding='utf-8'))



if __name__ == '__main__':
    unittest.main()
