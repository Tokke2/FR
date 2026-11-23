from __future__ import annotations

from datetime import datetime
import importlib.machinery
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import dependencies, weekly_maintenance as weekly

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('weekly_start_test', str(ROOT / 'start.pyw'))
spec = importlib.util.spec_from_loader(loader.name, loader)
start = importlib.util.module_from_spec(spec)
loader.exec_module(start)
LOG = logging.getLogger('test.weekly')


class ScheduleTests(unittest.TestCase):
    def test_monday_eight_boundary_and_catchup(self):
        self.assertEqual(weekly.scheduled_slot(datetime(2026, 11, 9, 7, 59)), datetime(2026, 11, 2, 8))
        self.assertEqual(weekly.scheduled_slot(datetime(2026, 11, 9, 8)), datetime(2026, 11, 9, 8))
        self.assertEqual(weekly.scheduled_slot(datetime(2026, 11, 15, 23)), datetime(2026, 11, 9, 8))
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(weekly.claim_due(Path(folder), datetime(2026, 11, 9, 7, 59)))
            self.assertFalse(weekly.claim_due(Path(folder), datetime(2026, 11, 9, 7, 59, 59)))
            self.assertTrue(weekly.claim_due(Path(folder), datetime(2026, 11, 9, 8)))
            self.assertFalse(weekly.claim_due(Path(folder), datetime(2026, 11, 15, 23)))
            self.assertTrue(weekly.claim_due(Path(folder), datetime(2026, 11, 20, 10)))
            self.assertFalse(weekly.claim_due(Path(folder), datetime(2026, 11, 9, 8)))  # clock set back

    def test_corrupt_state_or_link_never_runs_a_duplicate_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / weekly.STATE_NAME
            state.write_text('{bad')
            with self.assertRaises(ValueError):
                weekly.claim_due(root, datetime(2026, 11, 9, 8))
            self.assertEqual(state.read_text(), '{bad')
            state.unlink()
            try:
                state.symlink_to(root / 'target')
            except OSError:
                self.skipTest('symboliska länkar saknas')
            with self.assertRaises(OSError):
                weekly.claim_due(root, datetime(2026, 11, 9, 8))

    def test_simultaneous_processes_only_claim_once(self):
        with tempfile.TemporaryDirectory() as folder:
            code = ('from core.weekly_maintenance import claim_due; from pathlib import Path; '
                    'from datetime import datetime; import sys; '
                    'print(int(claim_due(Path(sys.argv[1]), datetime(2026,11,9,8))))')
            env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
            jobs = [subprocess.Popen([sys.executable, '-c', code, folder], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(5)]
            results = [job.communicate(timeout=20) for job in jobs]
            self.assertEqual([job.returncode for job in jobs], [0] * 5, results)
            self.assertEqual(sorted(out.strip() for out, _ in results), ['0', '0', '0', '0', '1'])


class PackageTests(unittest.TestCase):
    def test_outdated_is_limited_to_known_app_packages(self):
        versions = {'PySide6': ('6.9', '6.10'), 'pandas': ('2.0', '3.0'), 'openpyxl': ('3.1', '3.1'), 'xlrd': ('2.0', '2.0')}
        def answer(command, **kwargs):
            current, latest = versions[command[5]]
            return SimpleNamespace(returncode=0, stdout=f'  INSTALLED: {current}\n  LATEST: {latest}\n')
        with patch.object(dependencies.subprocess, 'run', side_effect=answer) as run:
            result = dependencies.outdated_packages()
            self.assertEqual([item['name'] for item in result], ['PySide6', 'pandas'])
            self.assertEqual(run.call_count, 4)
            self.assertEqual(run.call_args.args[0][:5], [sys.executable, '-m', 'pip', 'index', 'versions'])
        self.assertEqual(dependencies.pip_command(['pandas'], upgrade=True),
                         [sys.executable, '-m', 'pip', 'install', '--no-input', '--upgrade', 'pandas'])
        with self.assertRaises(ValueError):
            dependencies.pip_command(['malicious-package'], upgrade=True)
        with self.assertRaises(ValueError):
            dependencies.outdated_packages(skip=('malicious-package',))

    def test_failed_or_invalid_pip_query_does_not_update(self):
        for result in (SimpleNamespace(returncode=1, stdout=''), SimpleNamespace(returncode=0, stdout='not json')):
            with self.subTest(result=result), patch.object(dependencies.subprocess, 'run', return_value=result):
                with self.assertRaises(RuntimeError):
                    dependencies.outdated_packages()

    def test_upgrades_require_explicit_permission(self):
        updates = [{'name': 'pandas', 'version': '2.0', 'latest_version': '3.0'}]
        for approved in (False, True):
            with self.subTest(approved=approved), patch.object(start, 'probe', return_value={'missing': [], 'broken': {}}), patch.object(start, 'outdated_packages', return_value=updates), patch.object(start, '_message', return_value=approved), patch.object(start, '_run_pip', return_value=True) as run:
                self.assertTrue(start.check_dependencies(LOG))
                if approved:
                    run.assert_called_once_with(LOG, ['pandas'], upgrade=True)
                else:
                    run.assert_not_called()

    def test_updates_during_open_app_are_only_queued(self):
        packages = []
        updates = [{'name': 'pandas', 'version': '2.0', 'latest_version': '3.0'}]
        with patch.object(start, 'probe', return_value={'missing': [], 'broken': {}}), patch.object(start, 'outdated_packages', return_value=updates), patch.object(start, '_message', return_value=True), patch.object(start, '_run_pip') as run:
            self.assertTrue(start.check_dependencies(LOG, deferred=packages))
            self.assertEqual(packages, [(True, ['pandas'])])
            run.assert_not_called()

    def test_network_failure_is_reported_not_reported_as_up_to_date(self):
        with patch.object(start, 'probe', return_value={'missing': [], 'broken': {}}), patch.object(start, 'outdated_packages', side_effect=RuntimeError('offline')), patch.object(start, '_message') as message, patch.object(start, '_run_pip') as run:
            self.assertTrue(start.check_dependencies(LOG))
            self.assertIn('Kunde inte kontrollera', message.call_args.args[1])
            run.assert_not_called()

    def test_deferred_packages_run_after_normal_exit_and_stop_on_failure(self):
        queue = [(True, ['pandas'])]
        with patch.object(start, '_run_pip', return_value=True) as run, patch.object(start, 'probe', return_value={'missing': [], 'broken': {}}), patch.object(start, '_message'):
            start._apply_deferred(LOG, queue)
            run.assert_called_once_with(LOG, ['pandas'], upgrade=True)
        with patch.object(start, '_run_pip', return_value=False) as run, patch.object(start, 'probe') as probe:
            start._apply_deferred(LOG, queue)
            run.assert_called_once()
            probe.assert_not_called()

    def test_timer_checks_packages_while_open_but_does_not_install(self):
        stop = SimpleNamespace(wait=unittest.mock.Mock(side_effect=[False, True]))
        packages = []
        with patch.object(start, '_claim_weekly', return_value=True), patch.object(start, 'check_dependencies') as check_packages, patch.object(start, '_run_pip') as run:
            start._weekly_monitor(LOG, stop, packages)
            check_packages.assert_called_once_with(LOG, deferred=packages)
            run.assert_not_called()

    def test_bad_schedule_state_stops_monitor_without_repeated_dialogs(self):
        stop = SimpleNamespace(wait=unittest.mock.Mock(return_value=False))
        with patch.object(start, '_claim_weekly', return_value=None) as claim, patch.object(start, 'check_dependencies') as check:
            start._weekly_monitor(LOG, stop, [])
            claim.assert_called_once()
            check.assert_not_called()

    def test_main_applies_queued_packages_only_after_child_exits(self):
        import io
        exited = []
        child = SimpleNamespace(stdout=io.BufferedReader(io.BytesIO(b'')))
        child.wait = lambda: (exited.append(True) or 0)
        class FakeThread:
            def __init__(self, *, target, args, **kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)
            def join(self):
                pass
        def fake_monitor(log, stop, packages):
            packages.append((True, ['pandas']))
        def apply_pip(log, names, *, upgrade=False):
            self.assertTrue(exited, 'pip får inte köra före appens avslut')
            return True
        with tempfile.TemporaryDirectory() as folder, patch.object(start, 'ROOT', Path(folder)), patch.object(start, '_claim_weekly', return_value=False), patch.object(start, '_weekly_monitor', side_effect=fake_monitor), patch.object(start.threading, 'Thread', FakeThread), patch.object(start.subprocess, 'Popen', return_value=child), patch.object(start, '_run_pip', side_effect=apply_pip) as run, patch.object(start, 'probe', return_value={'missing': [], 'broken': {}}), patch.object(start, '_message'):
            self.assertEqual(start.main(), 0)
            run.assert_called_once_with(unittest.mock.ANY, ['pandas'], upgrade=True)
        logger = logging.getLogger('filregistrering.start')
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()



if __name__ == '__main__':
    unittest.main()
