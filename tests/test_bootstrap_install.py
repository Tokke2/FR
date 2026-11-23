from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import io
import json
import logging
from pathlib import Path
from datetime import date
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import dependencies

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("filregistrering_start_test", str(ROOT / "start.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
start = importlib.util.module_from_spec(spec)
loader.exec_module(start)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        outdated = patch.object(start, "outdated_packages", return_value=[])
        outdated.start()
        self.addCleanup(outdated.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        for logger_name in ("filregistrering.start", "filregistrering.process_output"):
            logger = logging.getLogger(logger_name)
            for h in list(logger.handlers):
                logger.removeHandler(h)
                h.close()
        def cleanup():
            for logger_name in ("filregistrering.start", "filregistrering.process_output"):
                logger = logging.getLogger(logger_name)
                for h in list(logger.handlers):
                    logger.removeHandler(h)
                    h.close()
        self.addCleanup(cleanup)

    def test_due_check_runs_only_once_for_two_starts(self):
        with patch.object(start, '_claim_weekly', side_effect=[True, False]), patch.object(start, 'probe', return_value={'missing': [], 'broken': {}}) as probe, patch.object(start.subprocess, 'Popen', return_value=SimpleNamespace(stdout=io.BufferedReader(io.BytesIO(b'')), wait=lambda: 0)), patch.object(start, 'ROOT', self.root):
            self.assertEqual(start.main(), 0)
            self.assertEqual(start.main(), 0)
            self.assertEqual(probe.call_count, 1)

    def test_declining_missing_packages_does_not_invoke_pip(self):
        with patch.object(start, "ROOT", self.root), patch.object(start, "probe", return_value={"missing": ["PySide6"], "broken": {}}), patch.object(start, "_message", return_value=False), patch.object(start.subprocess, "run") as run, patch.object(start.subprocess, "Popen") as popen:
            self.assertEqual(start.main(), 1)
            run.assert_not_called()
            popen.assert_not_called()
        self.assertIn("avböjdes", (self.root / "logs/bootstrap.log").read_text())
        self.assertIn("avböjdes", (self.root / "logs/felsokning.log").read_text())

    def test_approved_pip_then_app_output_and_exit_are_logged(self):
        child = SimpleNamespace(stdout=io.BufferedReader(io.BytesIO(b"startup error\n")), wait=lambda: 7)
        probes = [{"missing": ["pandas"], "broken": {}}, {"missing": [], "broken": {}}]
        with patch.object(start, "ROOT", self.root), patch.object(start, "probe", side_effect=probes), patch.object(start, "_message", return_value=True), patch.object(start.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run, patch.object(start.subprocess, "Popen", return_value=child) as popen, patch.object(sys, "argv", ["start.pyw"]):
            self.assertEqual(start.main(), 7)
            self.assertEqual(run.call_args.args[0], [sys.executable, "-m", "pip", "install", "--no-input", "pandas"])
            self.assertEqual(popen.call_args.kwargs["env"]["FR_PREFLIGHT_DONE"], "1")
        self.assertIn("startup error", (self.root / "logs/console.log").read_text())
        self.assertIn("status 7", (self.root / "logs/bootstrap.log").read_text())
        summary = (self.root / "logs/felsokning.log").read_text()
        self.assertIn("[startkontroll]", summary)
        self.assertIn("status 7", summary)
        self.assertIn("console.log", summary)
        daily = (self.root / 'logs' / 'dagliga' / f'{date.today().isoformat()}.log').read_text(encoding='utf-8')
        self.assertIn('startup error', daily)
        self.assertIn('status 7', daily)

    def test_broken_module_does_not_trigger_install(self):
        with patch.object(start, "ROOT", self.root), patch.object(start, "probe", return_value={"missing": [], "broken": {"PySide6": "missing libGL"}}), patch.object(start, "_message"), patch.object(start.subprocess, "run") as run:
            self.assertEqual(start.main(), 1)
            run.assert_not_called()
        summary = (self.root / "logs/felsokning.log").read_text()
        self.assertIn("Beroenden kan inte användas", summary)
        self.assertIn("missing libGL", summary)

    def test_whitelist_rejects_arbitrary_pip_arguments(self):
        with self.assertRaises(ValueError):
            dependencies.pip_command(["--index-url", "https://example.invalid"])
        with self.assertRaises(ValueError):
            dependencies.pip_command([])


class MainEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "main.pyw").write_bytes((ROOT / "main.pyw").read_bytes())
        (self.root / "start.pyw").write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "def main():\n"
            "    Path(__file__).with_name('called.txt').write_text(' '.join(sys.argv[1:]))\n"
            "    return 42\n")
        self.env = {**__import__('os').environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("FR_PREFLIGHT_DONE", None)

    def run_main(self, *args):
        return subprocess.run([sys.executable, str(self.root / "main.pyw"), *args],
                              cwd=self.root, env=self.env, capture_output=True, text=True)

    def test_normal_start_routes_to_bootstrap_and_keeps_arguments(self):
        result = self.run_main("--debug")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual((self.root / "called.txt").read_text(), "--debug")

    def test_diagnostics_skip_bootstrap_without_gui_packages(self):
        (self.root / "plugins").mkdir()
        result = self.run_main("--plugins-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "called.txt").exists())

    def test_validate_config_still_reports_on_stderr_with_summary_handler(self):
        (self.root / "config.json").write_text('{"app_name":"Fordonsreg","plugins":{"enabled":[]}}')
        result = self.run_main("--validate-config")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Configuration is valid", result.stderr)
        self.assertTrue((self.root / "logs/felsokning.log").is_file())

    def test_child_process_does_not_reenter_bootstrap(self):
        self.env["FR_PREFLIGHT_DONE"] = "1"
        result = self.run_main("--unknown-test-option")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / "called.txt").exists())



if __name__ == "__main__":
    unittest.main()
