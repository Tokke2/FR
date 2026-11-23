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

from plugins.app_icon.plugin import set_application_icon


class FakeIcon:
    def __init__(self):
        self.files = []

    def addFile(self, *args):
        self.files.append(args)

    def isNull(self):
        return not self.files


class FakeApplication:
    current = None

    @classmethod
    def instance(cls):
        return cls.current

    def setWindowIcon(self, icon):
        self.icon = icon


def qt_modules():
    package = types.ModuleType("PySide6")
    package.__path__ = []
    core = types.ModuleType("PySide6.QtCore")
    core.QSize = lambda w, h: (w, h)
    gui = types.ModuleType("PySide6.QtGui")
    gui.QIcon = FakeIcon
    widgets = types.ModuleType("PySide6.QtWidgets")
    widgets.QApplication = FakeApplication
    return {"PySide6": package, "PySide6.QtCore": core,
            "PySide6.QtGui": gui, "PySide6.QtWidgets": widgets}


class IconTests(unittest.TestCase):
    def tearDown(self):
        FakeApplication.current = None

    def test_uses_all_available_sizes_for_application(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, qt_modules()):
            root = Path(tmp)
            for name in ("ikon_16.png", "ikon_32.png", "ikon_64.png", "ikon_256.png", "ikon.ico"):
                (root / name).touch()
            app = FakeApplication()
            FakeApplication.current = app
            self.assertTrue(set_application_icon(root))
            self.assertEqual(len(app.icon.files), 5)
            self.assertEqual(app.icon.files[0][1], (16, 16))
            self.assertEqual(app.icon.files[3][1], (256, 256))
            self.assertEqual(app.icon.files[4][0], str(root / "ikon.ico"))

    def test_missing_icon_or_application_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, qt_modules()):
            self.assertFalse(set_application_icon(Path(tmp)))
            FakeApplication.current = FakeApplication()
            self.assertFalse(set_application_icon(Path(tmp)))

    def test_plugin_is_discovered_before_main_gui(self):
        from core.plugin_loader import PluginLoader
        root = Path(__file__).resolve().parents[1]
        loader = PluginLoader(root / "plugins")
        self.assertIn("app_icon", loader.get_discovered())
        self.assertLess(loader._resolve_load_order().index("app_icon"),
                        loader._resolve_load_order().index("main_gui"))

    def test_logging_starts_with_empty_directory(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / 'app'
            shutil.copytree(root / 'core', app / 'core', ignore=shutil.ignore_patterns('__pycache__'))
            env = {**os.environ, "PYTHONPATH": str(app), "PYTHONDONTWRITEBYTECODE": "1"}
            script = ("import logging; from core.logger_setup import setup_all_loggers, shutdown_logging; "
                      "setup_all_loggers(); logging.warning('test new log'); shutdown_logging()")
            subprocess.run([sys.executable, "-c", script], cwd=tmp, env=env,
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertFalse((Path(tmp) / 'logs').exists())
            self.assertIn("test new log", (app / "logs/errors.log").read_text(encoding="utf-8"))
            self.assertIn("test new log", (app / "logs/debug.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
