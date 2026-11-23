# plugins/ts_spec_import/widget.py
# -*- coding: utf-8 -*-
"""
TS Spec Import Widget v4.0.1

Enkel GUI-widget för TS Spec Import-pluginet.
Visar status, aktiv version och tillgängliga posttyper.

Ändringar v4.0.1 (Session 11 — granskad, spec v1.6 förbättringsregeln):
    - BUGG #8: VERSION + AUTHOR + get_copyright_string tillagda
      (alla filer ska ha VERSION och AUTHOR överst).
    - HAS_PYSIDE6: Final-mönster (_PYSIDE6_AVAILABLE -> HAS_PYSIDE6:
      Final[bool]) — konsistent med övriga filer.
    - Dummy-QWidget behållen (kompatibilitet: plugin.py kan importera
      modulen även utan PySide6) men förtydligad — konstruktion av
      widgeten raise ImportError om PySide6 saknas.
    - refresh(): skyddad mot saknade plugin-metoder; get_post_info
      hanterar både dict och None.
    - Versionssynk med plugin.py v4.0.1 (spec W.7).

OBS (spec Sektion D beskriver "info/schema/system-flikar, DPI-skalat
scrollbart"): denna widget är den enkla status-varianten som följer med
plugin.py v4.0.1 (ts_spec_import är "EJ GÖRA OM"). Flik-varianten
introduceras endast på uttrycklig begäran.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Final, Optional

try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
    )
    _PYSIDE6_AVAILABLE = True
except ImportError:
    _PYSIDE6_AVAILABLE = False

HAS_PYSIDE6: Final[bool] = _PYSIDE6_AVAILABLE

if not HAS_PYSIDE6:

    class QWidget:  # type: ignore
        """Dummy-fallback så att modulen kan importeras utan PySide6."""

        pass

_log = logging.getLogger(__name__)

VERSION = "4.0.1"
AUTHOR = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return "Copyright © {} {}".format(datetime.now().year, AUTHOR)


class TSSpecImportWidget(QWidget):
    """Widget för att visa TS-spec-importstatus."""

    def __init__(self, parent: Optional[Any] = None, plugin: Optional[Any] = None):
        if not HAS_PYSIDE6:
            raise ImportError("PySide6 krävs för TS Spec Import-widget")
        super().__init__(parent)
        self.plugin = plugin
        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        """Bygg upp gränssnittet."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("TS Spec Import")
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        self.version_label = QLabel("Version: -")
        layout.addWidget(self.version_label)

        self.active_version_label = QLabel("Aktiv spec-version: -")
        layout.addWidget(self.active_version_label)

        self.post_type_table = QTableWidget()
        self.post_type_table.setColumnCount(2)
        self.post_type_table.setHorizontalHeaderLabels(["Posttyp", "Namn"])
        header = self.post_type_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.post_type_table.setAlternatingRowColors(True)
        layout.addWidget(self.post_type_table)

        btn_layout = QHBoxLayout()

        refresh_btn = QPushButton("Uppdatera")
        refresh_btn.clicked.connect(self.refresh)
        btn_layout.addWidget(refresh_btn)

        import_btn = QPushButton("Importera från Excel")
        import_btn.clicked.connect(self._on_import)
        btn_layout.addWidget(import_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.status_label = QLabel("Status: redo")
        layout.addWidget(self.status_label)

    def refresh(self) -> None:
        """Uppdatera information från plugin."""
        if self.plugin is None:
            self.status_label.setText("Status: inget plugin kopplat")
            return

        try:
            version = getattr(self.plugin, "VERSION", "-")
            self.version_label.setText("Version: %s" % version)

            active = None
            if hasattr(self.plugin, "get_active_version"):
                active = self.plugin.get_active_version()
            self.active_version_label.setText(
                "Aktiv spec-version: %s" % (active or "ingen")
            )

            post_types = []
            if hasattr(self.plugin, "get_post_types"):
                post_types = self.plugin.get_post_types() or []

            self.post_type_table.setRowCount(len(post_types))
            for row, pt in enumerate(post_types):
                info = {}
                if hasattr(self.plugin, "get_post_info"):
                    try:
                        info = self.plugin.get_post_info(pt) or {}
                    except Exception:
                        info = {}
                if not isinstance(info, dict):
                    info = {}
                self.post_type_table.setItem(row, 0, QTableWidgetItem("PT%s" % pt))
                self.post_type_table.setItem(
                    row, 1, QTableWidgetItem(info.get("name", "") or "")
                )

            self.status_label.setText("Status: uppdaterad")
        except Exception as exc:
            _log.error("Fel vid uppdatering av widget: %s", exc)
            self.status_label.setText("Status: fel vid uppdatering")

    def _on_import(self) -> None:
        """Öppna dialog för import från Excel."""
        QMessageBox.information(
            self,
            "Import från Excel",
            "Importfunktionen anropas via pluginets publika API."
        )


__all__ = [
    "TSSpecImportWidget",
    "VERSION",
    "AUTHOR",
    "HAS_PYSIDE6",
]
