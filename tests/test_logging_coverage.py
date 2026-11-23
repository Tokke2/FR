from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class LoggingCoverageTests(unittest.TestCase):
    def test_events_unraisable_threads_and_shutdown_are_logged(self):
        script = '''
import logging, sys, threading, types, warnings
from core.logger_setup import setup_all_loggers, shutdown_logging
from core.event_bus import EventBus
setup_all_loggers()
bus = EventBus()
bus.emit('test:important', {'password': 'DO_NOT_LOG_PAYLOAD'})
try:
    raise ValueError('unraisable-test')
except Exception as e:
    t, v, tb = sys.exc_info()
    sys.unraisablehook(types.SimpleNamespace(err_msg='cleanup-test', exc_type=t, exc_value=v, exc_traceback=tb))
def crash():
    raise RuntimeError('thread-test')
t = threading.Thread(target=crash, name='test-thread')
t.start(); t.join()
warnings.warn('warning-test')
shutdown_logging()
'''
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / 'app'
            shutil.copytree(ROOT / 'core', app / 'core', ignore=shutil.ignore_patterns('__pycache__'))
            work = Path(tmp) / 'other-working-dir'; work.mkdir()
            env = {**os.environ, "PYTHONPATH": str(app), "PYTHONDONTWRITEBYTECODE": "1"}
            subprocess.run([sys.executable, "-c", script], cwd=work, env=env, check=True, capture_output=True)
            self.assertFalse((work / 'logs').exists())
            debug = (app / "logs/debug.log").read_text(encoding="utf-8")
            errors = (app / "logs/errors.log").read_text(encoding="utf-8")
            summary = (app / "logs/felsokning.log").read_text(encoding="utf-8")
            self.assertIn("SYSTEM STARTUP", debug)
            self.assertIn("Event: test:important", debug)
            self.assertNotIn("DO_NOT_LOG_PAYLOAD", debug)
            self.assertIn("SYSTEM SHUTDOWN", debug)
            for message in ("unraisable-test", "thread-test", "warning-test"):
                self.assertIn(message, errors)
                self.assertIn(message, summary)
            self.assertNotIn("DO_NOT_LOG_PAYLOAD", summary)

    def test_qt_critical_is_sent_to_logging(self):
        from plugins.app_logging import plugin
        package = types.ModuleType("PySide6")
        package.__path__ = []
        core = types.ModuleType("PySide6.QtCore")
        core.QtMsgType = types.SimpleNamespace(QtDebugMsg=0, QtInfoMsg=1, QtWarningMsg=2, QtCriticalMsg=3, QtFatalMsg=4)
        handlers = []
        core.qInstallMessageHandler = handlers.append
        old_handler = plugin._handler
        plugin._handler = None
        try:
            with patch.dict(sys.modules, {"PySide6": package, "PySide6.QtCore": core}):
                plugin.install_qt_logging()
                with self.assertLogs("qt", level="ERROR") as captured:
                    handlers[0](3, None, "Qt-fel")
                self.assertIn("Qt-fel", captured.output[0])
            from core.error_summary import ErrorSummaryHandler
            with tempfile.TemporaryDirectory() as tmp:
                root = logging.getLogger()
                qt_logger = logging.getLogger("qt")
                old_level, old_propagate, old_disabled = qt_logger.level, qt_logger.propagate, qt_logger.disabled
                qt_logger.setLevel(logging.DEBUG)
                qt_logger.propagate = True
                qt_logger.disabled = False
                handler = ErrorSummaryHandler(Path(tmp), "app")
                root.addHandler(handler)
                try:
                    handlers[0](3, None, "Qt-fel till sammanställningen")
                    self.assertIn("Qt-fel till sammanställningen", (Path(tmp) / "felsokning.log").read_text())
                finally:
                    root.removeHandler(handler)
                    handler.close()
                    qt_logger.setLevel(old_level)
                    qt_logger.propagate, qt_logger.disabled = old_propagate, old_disabled
        finally:
            plugin._handler = old_handler


if __name__ == "__main__":
    unittest.main()
