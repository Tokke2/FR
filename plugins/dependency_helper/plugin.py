"""Erbjud installation även när main.pyw startats direkt och Qt finns."""
from __future__ import annotations
import logging
import os
from pathlib import Path

from core.dependencies import missing_packages, pip_command
from core.plugin_base import PluginBase

_log = logging.getLogger(__name__)


class Plugin(PluginBase):
    NAME = "dependency_helper"
    DESCRIPTION = "Erbjud installation av saknade Pythonpaket"
    DEPENDENCIES = []

    def __init__(self, app):
        super().__init__(app)
        self._process = None

    def activate(self):
        self.is_active = True
        if os.environ.get("FR_PREFLIGHT_DONE") == "1":
            return
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            if QApplication.instance():
                QTimer.singleShot(0, self._offer)
        except ImportError:
            _log.warning("Qt saknas; använd start.pyw för att installera tillägg")

    def _offer(self):
        from PySide6.QtCore import QProcess
        from PySide6.QtWidgets import QMessageBox
        packages = missing_packages()
        if not packages:
            return
        answer = QMessageBox.question(None, "Saknade Python-tillägg",
            "Följande tillägg saknas: " + ", ".join(packages)
            + "\n\nInstallera i den aktuella Pythonmiljön? En omstart behövs efteråt.")
        if answer != QMessageBox.StandardButton.Yes:
            _log.info("Installation av saknade tillägg avböjdes")
            return
        command = pip_command(packages)
        self._process = QProcess()
        self._process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        self._process.finished.connect(self._finished)
        self._process.errorOccurred.connect(self._error)
        self._process.start(command[0], command[1:])
        _log.info("Användaren godkände installation av %s", packages)

    def _finished(self, code, status):
        from PySide6.QtWidgets import QMessageBox
        if code == 0:
            _log.info("Paketinstalleraren avslutades; omstart krävs")
            QMessageBox.information(None, "Python-tillägg", "Installationen är klar. Starta om appen för att använda tilläggen.")
        else:
            _log.error("Paketinstallationen misslyckades, status %s", code)
            QMessageBox.warning(None, "Python-tillägg", "Installationen misslyckades. Kontrollera pip, internet och behörigheter.")
        self._process = None

    def _error(self, error):
        from PySide6.QtWidgets import QMessageBox
        _log.error("Kunde inte starta paketinstalleraren: %s", error)
        QMessageBox.warning(None, "Python-tillägg", "Paketinstalleraren kunde inte startas.")

    def deactivate(self):
        self.is_active = False
