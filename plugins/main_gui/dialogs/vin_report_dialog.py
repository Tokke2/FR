# -*- coding: utf-8 -*-
# Fil: plugins/main_gui/dialogs/vin_report_dialog.py

"""
VIN-rapport dialog v1.0.1

Dialog för att generera årsrapport över VIN-registreringar via
vin_tracking-pluginet (load_registry + generate_yearly_report).

ANVÄNDNING (från main_gui/plugin.py, framtida inkoppling):
    from .dialogs.vin_report_dialog import VinReportDialog
    dialog = VinReportDialog(self._main_window, self.app)
    dialog.exec()

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (korrekthet, KRITISK): tkinter → PySide6-port. main_gui är
      ett PySide6-plugin (QApplication i plugin.py) — en
      tkinter.Toplevel med QMainWindow som parent fungerar inte
      (föräldratyp mismatch + två GUI-eventloopar som krockar).
      Nu: QDialog enligt kodbasens mönster (ColumnMappingDialog,
      GenerateTextFileDialog i vehicle_registry_helpers).
    - FIX (låst regel, inga hårdkodade årtal): default "2025" bort →
      str(datetime.now().year). Innevarande år läggs ALLTID till i
      årlistan (rapport för aktuellt år möjlig även utan poster).
    - FIX (säkerhet): os.startfile/os.system → QDesktopServices.
      openUrl(QUrl.fromLocalFile()) — plattformsoberoende, ingen
      shell-expansion, inga os.system-anrop.
    - FIX (stabilitet/loggning): except Exception: pass bort →
      _log.exception/_log.warning (lazy %s). _open_folder loggar om
      mappen saknas; genereringsfel → kritisk-dialog + logg.
    - FIX (plugin-åtkomst): app.plugin_manager.get_plugin (legacy,
      Method 3) → _get_plugin_safe(app, "vin_tracking") med alla 4
      hämtningsmetoder (samma fallback-kedja som plugin.py).
    - FIX (konventioner): modul-nivå _log, VERSION/AUTHOR + dynamisk
      copyright, setObjectName med design-tokens (PageTitle,
      StatusLabel, PrimaryButton, buttonBox), full-form PySide6-enums
      (QDialogButtonBox.StandardButton.Cancel), "# Fil:"-kommentar
      behållen (KRAV 58).
    - FIX (UI/UX): Avbryt-knapp (Esc stänger), generera-knappen
      inaktiveras under generering (dubbelklick-skydd), "Ingen data"-
      fallet stänger INTE längre dialogen (användaren kan välja ett
      annat år), framgång stänger via accept().
FÖRÄNDRINGAR v1.0.0:
    - NY FIL (inklistrad original): tkinter-dialog (ersatt av v1.0.1).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_log: logging.Logger = logging.getLogger("vin_report_dialog")

VERSION: str = "1.0.1"
AUTHOR: str = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


def _get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Robust plugin-hämtning — samma fallback-kedja som main_gui/plugin.py.

    Metod 1: app.get_plugin() · 2: app.plugin_loader.get_plugin() ·
    3: app.plugin_manager.get_plugin() (legacy) · 4: direktattribut.
    """
    if app is None:
        return None
    try:
        getter = getattr(app, "get_plugin", None)
        if callable(getter):
            plugin = getter(name)
            if plugin is not None:
                return plugin
    except Exception as exc:
        _log.debug("app.get_plugin misslyckades för %s: %s", name, exc)
    try:
        loader = getattr(app, "plugin_loader", None)
        if loader is not None and hasattr(loader, "get_plugin"):
            plugin = loader.get_plugin(name)
            if plugin is not None:
                return plugin
    except Exception as exc:
        _log.debug(
            "plugin_loader.get_plugin misslyckades för %s: %s",
            name,
            exc,
        )
    try:
        manager = getattr(app, "plugin_manager", None)
        if manager is not None and hasattr(manager, "get_plugin"):
            plugin = manager.get_plugin(name)
            if plugin is not None:
                return plugin
    except Exception as exc:
        _log.debug(
            "plugin_manager.get_plugin misslyckades för %s: %s",
            name,
            exc,
        )
    try:
        attr_name = name.replace("-", "_").lower()
        if hasattr(app, attr_name):
            return getattr(app, attr_name)
    except Exception as exc:
        _log.debug("getattr misslyckades för %s: %s", name, exc)
    return None


class VinReportDialog(QDialog):
    """Dialog för att generera VIN-rapport (år per VIN-register)."""

    def __init__(self, parent: Optional[QWidget], app: Any) -> None:
        super().__init__(parent)
        self._app = app
        self.setObjectName("vinReportDialog")
        self.setWindowTitle("📊 Generera VIN-rapport")
        self.setModal(True)
        self.setFixedSize(380, 200)
        self._create_widgets()

    def _create_widgets(self) -> None:
        """Bygg dialogens widgets (design-tokens, inga hårdkodade färger)."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        heading = QLabel("📊 Generera VIN-rapport")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        info = QLabel("Välj år för rapport:")
        info.setObjectName("StatusLabel")
        layout.addWidget(info)

        self._year_combo = QComboBox()
        self._year_combo.setObjectName("yearCombo")
        self._year_combo.setEditable(False)
        self._year_combo.addItems(self._get_available_years())
        layout.addWidget(self._year_combo)

        self._generate_button = QPushButton("📊 Generera rapport")
        self._generate_button.setObjectName("PrimaryButton")
        self._generate_button.clicked.connect(self._generate)
        layout.addWidget(self._generate_button)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.setObjectName("buttonBox")
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _get_available_years(self) -> List[str]:
        """
        Hämta tillgängliga år från VIN-tracking-pluginet.

        Innevarande år läggs alltid till (rapport för aktuellt år ska
        vara möjlig även innan första registreringen).
        """
        years: List[str] = []
        plugin = _get_plugin_safe(self._app, "vin_tracking")
        if plugin is not None and hasattr(plugin, "load_registry"):
            try:
                registry = plugin.load_registry()
                if isinstance(registry, dict):
                    years = [
                        str(year)
                        for year in registry.keys()
                        if str(year).isdigit()
                    ]
            except Exception:
                _log.exception("Kunde inte läsa VIN-registret.")
        current = str(datetime.now().year)
        if current not in years:
            years.append(current)
        return sorted(years, reverse=True)

    def _generate(self) -> None:
        """Generera årsrapport och öppna mappen med rapporten."""
        year = self._year_combo.currentText().strip()
        if not year:
            return
        self._generate_button.setEnabled(False)
        try:
            plugin = _get_plugin_safe(self._app, "vin_tracking")
            if plugin is None:
                QMessageBox.critical(
                    self,
                    "Fel",
                    "VIN Tracking-pluginet saknas.",
                )
                return
            generator = getattr(plugin, "generate_yearly_report", None)
            if not callable(generator):
                QMessageBox.critical(
                    self,
                    "Fel",
                    "VIN Tracking-pluginet saknar "
                    "generate_yearly_report().",
                )
                return
            report_path = generator(year)
            if report_path:
                path = Path(report_path)
                QMessageBox.information(
                    self,
                    "Rapport genererad",
                    "VIN-rapport för {} sparad:\n{}".format(
                        year, path.name
                    ),
                )
                self._open_folder(path.parent)
                self.accept()
            else:
                QMessageBox.information(
                    self,
                    "Ingen data",
                    "Inga VIN registrerade för {}.".format(year),
                )
        except Exception:
            _log.exception("Fel vid generering av VIN-rapport för %s", year)
            QMessageBox.critical(
                self,
                "Fel",
                "Kunde inte generera VIN-rapporten.",
            )
        finally:
            self._generate_button.setEnabled(True)

    def _open_folder(self, path: Path) -> None:
        """Öppna mappen i utforskaren (plattformsoberoende)."""
        try:
            if not path.is_dir():
                _log.warning("Mapp finns inte: %s", path)
                return
            opened = QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(path))
            )
            if not opened:
                _log.warning("Kunde inte öppna mappen: %s", path)
        except Exception:
            _log.exception("Fel vid öppning av mapp: %s", path)


__all__: List[str] = [
    "VinReportDialog",
    "_get_plugin_safe",
    "get_copyright_string",
    "VERSION",
    "AUTHOR",
]
