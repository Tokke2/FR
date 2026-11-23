from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import logger_setup

ROOT = Path(__file__).resolve().parents[1]


class AppLogPathsTests(unittest.TestCase):
    def make_application(self, tmp: Path) -> Path:
        app = tmp / 'fordonsreg'
        shutil.copytree(ROOT / 'core', app / 'core', ignore=shutil.ignore_patterns('__pycache__'))
        for plugin in ('core_logger', 'data_mapping'):
            shutil.copytree(ROOT / 'plugins' / plugin, app / 'plugins' / plugin,
                            ignore=shutil.ignore_patterns('__pycache__'))
        return app

    def test_direct_launch_from_another_directory_uses_app_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); app = self.make_application(root)
            other = root / 'another-place'; other.mkdir()
            # Äldre filer och användarens önskade externa sökväg lämnas orörda.
            (other / 'logs').mkdir()
            legacy = other / 'logs' / 'data_mapping.log'; legacy.write_text('BEVARA', encoding='utf-8')
            outside = root / 'outside.log'; outside.write_text('BEVARA', encoding='utf-8')
            script = '''
import logging, sys
from pathlib import Path
from types import SimpleNamespace
from core.logger_setup import setup_all_loggers, shutdown_logging, setup_logger
import types
pyside = types.ModuleType('PySide6'); widgets = types.ModuleType('PySide6.QtWidgets')
widgets.QWidget = widgets.QVBoxLayout = widgets.QLabel = type('FakeWidget', (), {})
sys.modules['PySide6'] = pyside; sys.modules['PySide6.QtWidgets'] = widgets
from plugins.data_mapping import plugin as mapping
from plugins.core_logger.plugin import Plugin, LoggerConfig
setup_all_loggers()
logging.warning('samlad varning')
mapping._log.warning('mappning här')
setup_logger('custom.outside', sys.argv[1]).warning('egen logg här')
p = Plugin(SimpleNamespace(base_path=sys.argv[2], config={}))
p._setup_paths()
p.create_logger(LoggerConfig(name='unique.external.test', log_file=Path(sys.argv[1]))).warning('pluginlogg här')
assert p.log_dir == Path(sys.argv[3]) / 'logs'
shutdown_logging()
'''
            env = {**os.environ, 'PYTHONPATH': str(app), 'PYTHONDONTWRITEBYTECODE': '1'}
            result = subprocess.run([sys.executable, '-c', script, str(outside), str(other), str(app)],
                                    cwd=other, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(outside.read_text(encoding='utf-8'), 'BEVARA')
            self.assertEqual(legacy.read_text(encoding='utf-8'), 'BEVARA')
            logs = app / 'logs'
            self.assertIn('samlad varning', (logs / 'felsokning.log').read_text(encoding='utf-8'))
            self.assertIn('mappning här', (logs / 'data_mapping.log').read_text(encoding='utf-8'))
            self.assertIn('pluginlogg här', (logs / 'outside.log').read_text(encoding='utf-8'))
            self.assertEqual(sorted(p.name for p in (other / 'logs').iterdir()), ['data_mapping.log'])

    def test_unusable_app_log_directory_fails_without_temp_fallback_or_deleting_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'logs'
            directory.write_text('behåll filen', encoding='utf-8')
            with patch.object(logger_setup, 'LOGS_DIR', directory):
                with self.assertRaises(OSError):
                    logger_setup._resolve_logs_dir()
            self.assertEqual(directory.read_text(encoding='utf-8'), 'behåll filen')
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ['logs'])


if __name__ == '__main__':
    unittest.main()
