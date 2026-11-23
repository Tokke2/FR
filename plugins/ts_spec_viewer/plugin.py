# plugins/ts_spec_viewer/plugin.py
# -*- coding: utf-8 -*-
"""
TS Spec Viewer Plugin v1.1.0

Visualisera, jämför och inspektera TS-specifikationer.
Integrerar med ts_schema_manager (source of truth).

Features:
    - Visa aktiv schema-version och dess posttyper
    - Detaljerad fältvisning per posttyp
    - Diff/jämförelse mellan versioner
    - Export till JSON
    - Schema-statistik

Ändringar v1.1.0 (Session 11 — granskad, spec v1.6 förbättringsregeln):
    - GRANSKAD: pluginet var dokumenterat i spec W.6 (plugin.py fanns,
      övriga filer saknades) — nu granskad.
    - AUTHOR: "System" -> "Rickard Längkvist" (spec L9 / BUGG #5-anda).
    - FIX (BUGG #15-mönster): activate() anropar super().activate() så
      att _activate_time sätts (uptime fungerar).
    - FIX: deactivate() anropar super().deactivate() (kraschsäkert) för
      korrekt cleanup (events/UI-komponenter/resurser).
    - FIX: get_schema_info() — "Schema PT%s hittades inte" formateras
      nu korrekt med post_type (var oformaterad %s).
    - HAS_PYSIDE6: Final-mönster (_PYSIDE6_AVAILABLE -> HAS_PYSIDE6:
      Final[bool]) — konsistent med övriga filer.
    - get_plugin_safe(): + plugin_manager-fallback + direktattribut
      (konsistent med vehicle_registry m.fl.).
    - OBSERVATION (EJ ändrad): widgeten använder QTableWidget; spec
      kräver QTableView/QAbstractTableModel för >100 rader. Om scheman
      med fler än ~100 fält/posttyper förekommer ska tabellerna
      konverteras vid nästa rotation (noterat i docstring).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, Final, List, Optional, TYPE_CHECKING

from core.plugin_base import PluginBase, PluginMetadata

# PySide6 (optional)
try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
        QComboBox, QTextEdit, QTabWidget, QMessageBox,
        QFileDialog, QFormLayout
    )

    _PYSIDE6_AVAILABLE = True
except ImportError:
    _PYSIDE6_AVAILABLE = False

HAS_PYSIDE6: Final[bool] = _PYSIDE6_AVAILABLE

if TYPE_CHECKING:
    from core.application import Application

_log = logging.getLogger(__name__)

VERSION = "1.1.0"
AUTHOR = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return "Copyright © {} {}".format(datetime.now().year, AUTHOR)


# ══════════════════════════════════════════════════════════════════════════════
# ROBUST HELPERS

# ══════════════════════════════════════════════════════════════════════════════


def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """Robust plugin-hämtning."""
    if app is None:
        return None

    normalized = name.replace("-", "_").lower()
    for candidate in (name, normalized):
        try:
            gp = getattr(app, "get_plugin", None)
            if callable(gp):
                p = gp(candidate)
                if p is not None:
                    return p
        except Exception:
            pass
        try:
            loader = getattr(app, "plugin_loader", None)
            if loader and hasattr(loader, "get_plugin"):
                p = loader.get_plugin(candidate)
                if p is not None:
                    return p
        except Exception:
            pass
        try:
            manager = getattr(app, "plugin_manager", None)
            if manager and hasattr(manager, "get_plugin"):
                p = manager.get_plugin(candidate)
                if p is not None:
                    return p
        except Exception:
            pass
        try:
            if hasattr(app, candidate):
                p = getattr(app, candidate)
                if p is not None:
                    return p
        except Exception:
            pass
    return None


def get_schema_manager(app: Any) -> Optional[Any]:
    """Hämta ts_schema_manager plugin."""
    return get_plugin_safe(app, "ts_schema_manager")


def get_active_version_safe(app: Any) -> Optional[str]:
    """Hämta aktiv schema-version säkert."""
    mgr = get_schema_manager(app)
    if mgr and hasattr(mgr, "get_active_version"):
        try:
            return mgr.get_active_version()
        except Exception:
            pass
    return None


def get_all_schemas_safe(app: Any) -> Dict[str, Any]:
    """Hämta alla scheman säkert."""
    mgr = get_schema_manager(app)
    if mgr and hasattr(mgr, "get_all_schemas"):
        try:
            result = mgr.get_all_schemas()
            return result if result else {}
        except Exception:
            pass
    return {}


def list_versions_safe(app: Any) -> List[str]:
    """Lista versioner säkert."""
    mgr = get_schema_manager(app)
    if mgr and hasattr(mgr, "list_versions"):
        try:
            versions = mgr.list_versions()
            if versions:
                if hasattr(versions[0], "version"):
                    return [v.version for v in versions]
                return list(versions)
        except Exception:
            pass
    return []


def _atomic_write_json(filepath: str, data: Dict[str, Any]) -> None:
    """Skriv JSON atomiskt med mkstemp + os.replace."""
    directory = os.path.dirname(filepath) or "."
    fd, tmp_path = tempfile.mkstemp(
        dir=directory,
        prefix=".tmp_",
        suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, filepath)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN

# ══════════════════════════════════════════════════════════════════════════════


class Plugin(PluginBase):
    """
    TS Spec Viewer - Visualisera och jämför TS-specifikationer.

    Tillhandahåller:
        - create_widget() för GUI i main_gui
        - compare_versions() för versionsjämförelse
        - get_schema_info() för schema-detaljer
    """

    METADATA = PluginMetadata(
        name="ts_spec_viewer",
        version=VERSION,
        description="Visualisera och jämför TS-specifikationer",
        author=AUTHOR,
        dependencies=(),
        optional_dependencies=("ts_schema_manager", "ts_excel_importer"),
        has_ui=True,
        screen_aware=False,
    )

    NAME = "TS Spec Viewer"
    VERSION = VERSION
    DESCRIPTION = "Visualisera och jämför TS-specifikationer"
    AUTHOR = AUTHOR

    DEPENDENCIES = []
    OPTIONAL_DEPENDENCIES = ["ts_schema_manager", "ts_excel_importer"]

    def __init__(self, app: "Application"):
        super().__init__(app)
        self._widget: Optional[Any] = None

    def initialize(self) -> None:
        """Initiera plugin."""
        _log.info("%s v%s initierad", self.NAME, self.VERSION)

    def activate(self) -> None:
        """Aktivera plugin."""
        super().activate()
        _log.info("%s aktiverad", self.NAME)

    def deactivate(self) -> None:
        """Deaktivera plugin."""
        self._widget = None
        try:
            super().deactivate()
        except Exception as exc:
            _log.warning("deactivate: %s", exc)
        self.is_active = False

    # ═══════════════════════════════════════════════════════════════════════
    # PUBLIC API

    # ═══════════════════════════════════════════════════════════════════════

    def create_widget(self, parent: Any = None) -> Optional[Any]:
        """
        Skapa viewer-widget för main_gui.

        Returns:
            QWidget eller None om PySide6 saknas
        """
        if not HAS_PYSIDE6:
            _log.warning("PySide6 saknas - GUI ej tillgängligt")
            return None
        try:
            self._widget = TSSpecViewerWidget(self.app, plugin=self, parent=parent)
            return self._widget
        except Exception as exc:
            _log.error("Kunde inte skapa viewer widget: %s", exc)
            return None

    def compare_versions(self, version1: str, version2: str) -> Dict[str, List[str]]:
        """
        Jämför två schema-versioner.

        Args:
            version1: Första version
            version2: Andra version

        Returns:
            Dict med "added", "removed", "modified" listor
        """
        mgr = get_schema_manager(self.app)

        if mgr and hasattr(mgr, "compare_versions"):
            try:
                return mgr.compare_versions(version1, version2)
            except Exception as exc:
                return {
                    "added": [],
                    "removed": [],
                    "modified": [],
                    "error": str(exc),
                }

        # Manuell jämförelse som fallback
        return self._manual_compare(version1, version2)

    def _manual_compare(self, version1: str, version2: str) -> Dict[str, List[str]]:
        """Manuell jämförelse av versioner."""
        mgr = get_schema_manager(self.app)
        if not mgr:
            return {
                "added": [],
                "removed": [],
                "modified": [],
                "error": "Schema manager ej tillgänglig",
            }
        try:
            schemas1: Dict[str, Any] = {}
            schemas2: Dict[str, Any] = {}

            if hasattr(mgr, "get_all_schemas"):
                schemas1 = mgr.get_all_schemas(version1) or {}
                schemas2 = mgr.get_all_schemas(version2) or {}

            types1 = set(schemas1.keys())
            types2 = set(schemas2.keys())
            added = list(types2 - types1)
            removed = list(types1 - types2)

            modified = []
            for pt in types1 & types2:
                spec1 = schemas1.get(pt)
                spec2 = schemas2.get(pt)

                if spec1 and spec2:
                    checksum1 = getattr(spec1, "checksum", None)
                    checksum2 = getattr(spec2, "checksum", None)

                    if checksum1 and checksum2 and checksum1 != checksum2:
                        modified.append(pt)
                    elif not checksum1 or not checksum2:
                        fields1 = len(getattr(spec1, "fields", []))
                        fields2 = len(getattr(spec2, "fields", []))
                        if fields1 != fields2:
                            modified.append(pt)

            return {
                "added": sorted(added),
                "removed": sorted(removed),
                "modified": sorted(modified),
            }
        except Exception as exc:
            return {
                "added": [],
                "removed": [],
                "modified": [],
                "error": str(exc),
            }

    def get_schema_info(self, post_type: str, version: Optional[str] = None) -> Dict[str, Any]:
        """
        Hämta detaljerad info om ett schema.

        Args:
            post_type: Posttyp (t.ex. "45")
            version: Version (eller aktiv)

        Returns:
            Dict med schema-information
        """
        mgr = get_schema_manager(self.app)
        if not mgr:
            return {"error": "Schema manager ej tillgänglig"}
        try:
            schema = None
            if hasattr(mgr, "get_schema"):
                schema = mgr.get_schema(post_type, version)
            if not schema:
                return {
                    "error": "Schema PT%s hittades inte" % post_type,
                    "post_type": post_type,
                }

            fields_info = []
            if hasattr(schema, "fields"):
                for field in schema.fields:
                    fields_info.append({
                        "name": getattr(field, "name", ""),
                        "position": getattr(field, "position", 0),
                        "length": getattr(field, "length", 0),
                        "type": getattr(field, "field_type", "alphanumeric"),
                        "required": getattr(field, "required", False),
                        "description": getattr(field, "description", ""),
                    })

            return {
                "post_type": post_type,
                "name": getattr(schema, "name", "Posttyp %s" % post_type),
                "total_length": getattr(schema, "total_length", 2500),
                "field_count": len(fields_info),
                "fields": fields_info,
                "version": version or get_active_version_safe(self.app),
                "checksum": getattr(schema, "checksum", None),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def get_active_version(self) -> Optional[str]:
        """Hämta aktiv version."""
        return get_active_version_safe(self.app)

    def list_versions(self) -> List[str]:
        """Lista alla versioner."""
        return list_versions_safe(self.app)

    def refresh(self) -> None:
        """Uppdatera widget."""
        if self._widget and hasattr(self._widget, "refresh"):
            self._widget.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# GUI WIDGET

# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class TSSpecViewerWidget(QWidget):
        """
        Huvudwidget för TS-schema visning.

        Tabs:
            1. Översikt - Aktiv version och posttyper
            2. Fältdetaljer - Detaljerad vy per posttyp
            3. Jämförelse - Diff mellan versioner

        OBS (v1.1.0): tabellerna använder QTableWidget. Spec kräver
        QTableView/QAbstractTableModel för >100 rader — konvertering
        sker vid nästa rotation om scheman överstiger ~100 fält.
        """

        def __init__(
            self,
            app: Any,
            plugin: Optional[Plugin] = None,
            parent: Any = None
        ):
            super().__init__(parent)
            self.app = app
            self._plugin = plugin
            self._setup_ui()

            # Initial laddning efter kort fördröjning
            QTimer.singleShot(100, self.refresh)

        def _setup_ui(self) -> None:
            """Konfigurera UI."""
            layout = QVBoxLayout(self)
            layout.setContentsMargins(20, 20, 20, 20)

            # Titel
            title = QLabel("TS Schema Viewer")
            title_font = title.font()
            title_font.setPointSize(16)
            title_font.setBold(True)
            title.setFont(title_font)
            layout.addWidget(title)

            # Tabs
            self.tabs = QTabWidget()
            layout.addWidget(self.tabs)

            # Tab 1: Översikt
            self.overview_tab = self._create_overview_tab()
            self.tabs.addTab(self.overview_tab, "Översikt")

            # Tab 2: Fältdetaljer
            self.details_tab = self._create_details_tab()
            self.tabs.addTab(self.details_tab, "Fältdetaljer")

            # Tab 3: Jämförelse
            self.compare_tab = self._create_compare_tab()
            self.tabs.addTab(self.compare_tab, "Jämför versioner")

            # Knappar längst ner
            btn_layout = QHBoxLayout()

            refresh_btn = QPushButton("Uppdatera")
            refresh_btn.clicked.connect(self.refresh)
            btn_layout.addWidget(refresh_btn)

            export_btn = QPushButton("Exportera JSON")
            export_btn.clicked.connect(self._export_json)
            btn_layout.addWidget(export_btn)

            btn_layout.addStretch()
            layout.addLayout(btn_layout)

        def _create_overview_tab(self) -> QWidget:
            """Skapa översikts-tab."""
            widget = QWidget()
            layout = QVBoxLayout(widget)

            # Version info
            self.version_group = QGroupBox("Aktiv version")
            version_layout = QFormLayout(self.version_group)

            self.version_label = QLabel("-")
            version_label_font = self.version_label.font()
            version_label_font.setBold(True)
            self.version_label.setFont(version_label_font)
            version_layout.addRow("Version:", self.version_label)

            self.post_count_label = QLabel("-")
            version_layout.addRow("Posttyper:", self.post_count_label)

            self.total_fields_label = QLabel("-")
            version_layout.addRow("Totalt antal fält:", self.total_fields_label)

            layout.addWidget(self.version_group)

            # Posttyper tabell
            post_group = QGroupBox("Posttyper")
            post_layout = QVBoxLayout(post_group)

            self.post_table = QTableWidget()
            self.post_table.setColumnCount(4)
            self.post_table.setHorizontalHeaderLabels(
                ["Posttyp", "Namn", "Fält", "Längd"]
            )
            self.post_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.post_table.setAlternatingRowColors(True)
            post_layout.addWidget(self.post_table)

            layout.addWidget(post_group)

            # Tillgängliga versioner
            versions_group = QGroupBox("Tillgängliga versioner")
            versions_layout = QVBoxLayout(versions_group)

            self.versions_list = QTextEdit()
            self.versions_list.setReadOnly(True)
            self.versions_list.setMaximumHeight(100)
            versions_layout.addWidget(self.versions_list)

            layout.addWidget(versions_group)

            return widget

        def _create_details_tab(self) -> QWidget:
            """Skapa fältdetaljer-tab."""
            widget = QWidget()
            layout = QVBoxLayout(widget)

            # Välj posttyp
            select_layout = QHBoxLayout()
            select_layout.addWidget(QLabel("Posttyp:"))

            self.post_type_combo = QComboBox()
            self.post_type_combo.setMinimumWidth(200)
            self.post_type_combo.currentTextChanged.connect(self._on_post_type_changed)
            select_layout.addWidget(self.post_type_combo)

            select_layout.addStretch()
            layout.addLayout(select_layout)

            # Fält-tabell
            self.fields_table = QTableWidget()
            self.fields_table.setColumnCount(6)
            self.fields_table.setHorizontalHeaderLabels([
                "Fältnamn", "Position", "Längd", "Typ", "Obligatorisk", "Beskrivning"
            ])
            header = self.fields_table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeToContents)
            header.setSectionResizeMode(5, QHeaderView.Stretch)
            self.fields_table.setAlternatingRowColors(True)
            layout.addWidget(self.fields_table)

            return widget

        def _create_compare_tab(self) -> QWidget:
            """Skapa jämförelse-tab."""
            widget = QWidget()
            layout = QVBoxLayout(widget)

            # Välj versioner
            select_group = QGroupBox("Välj versioner att jämföra")
            select_layout = QHBoxLayout(select_group)

            select_layout.addWidget(QLabel("Version 1:"))
            self.compare_v1_combo = QComboBox()
            self.compare_v1_combo.setMinimumWidth(150)
            select_layout.addWidget(self.compare_v1_combo)

            select_layout.addWidget(QLabel("Version 2:"))
            self.compare_v2_combo = QComboBox()
            self.compare_v2_combo.setMinimumWidth(150)
            select_layout.addWidget(self.compare_v2_combo)

            compare_btn = QPushButton("Jämför")
            compare_btn.clicked.connect(self._do_compare)
            select_layout.addWidget(compare_btn)

            select_layout.addStretch()
            layout.addWidget(select_group)

            # Resultat
            result_group = QGroupBox("Resultat")
            result_layout = QVBoxLayout(result_group)

            self.compare_result = QTextEdit()
            self.compare_result.setReadOnly(True)
            result_layout.addWidget(self.compare_result)

            layout.addWidget(result_group)

            return widget

        def refresh(self) -> None:
            """Uppdatera all data."""
            self._refresh_overview()
            self._refresh_post_types()
            self._refresh_versions()

        def _refresh_overview(self) -> None:
            """Uppdatera översikts-info."""
            version = get_active_version_safe(self.app)
            schemas = get_all_schemas_safe(self.app)
            self.version_label.setText(version or "Ingen version aktiv")

            self.post_count_label.setText(str(len(schemas)))

            total_fields = 0
            for schema in schemas.values():
                if hasattr(schema, "fields"):
                    total_fields += len(schema.fields)
            self.total_fields_label.setText(str(total_fields))

            # Posttyper tabell
            self.post_table.setRowCount(len(schemas))
            for row, (pt, schema) in enumerate(sorted(schemas.items())):
                name = getattr(schema, "name", "Posttyp %s" % pt)
                field_count = len(getattr(schema, "fields", []))
                total_length = getattr(schema, "total_length", 2500)

                self.post_table.setItem(row, 0, QTableWidgetItem("PT%s" % pt))
                self.post_table.setItem(row, 1, QTableWidgetItem(name))
                self.post_table.setItem(row, 2, QTableWidgetItem(str(field_count)))
                self.post_table.setItem(row, 3, QTableWidgetItem(str(total_length)))

        def _refresh_post_types(self) -> None:
            """Uppdatera posttyp-dropdown."""
            schemas = get_all_schemas_safe(self.app)

            self.post_type_combo.clear()
            for pt in sorted(schemas.keys()):
                schema = schemas[pt]
                name = getattr(schema, "name", "Posttyp %s" % pt)
                self.post_type_combo.addItem("PT%s - %s" % (pt, name), pt)

        def _refresh_versions(self) -> None:
            """Uppdatera versionslistor."""
            versions = list_versions_safe(self.app)
            active = get_active_version_safe(self.app)

            # Versions-lista i översikt
            if versions:
                version_text = "\n".join(
                    "%s %s" % ("->" if v == active else "  ", v)
                    for v in versions
                )
            else:
                version_text = "Inga versioner tillgängliga"
            self.versions_list.setText(version_text)

            # Compare dropdowns
            self.compare_v1_combo.clear()
            self.compare_v2_combo.clear()
            for v in versions:
                self.compare_v1_combo.addItem(v)
                self.compare_v2_combo.addItem(v)

            # Välj olika versioner om möjligt
            if len(versions) >= 2:
                self.compare_v1_combo.setCurrentIndex(0)
                self.compare_v2_combo.setCurrentIndex(1)

        def _on_post_type_changed(self, text: str) -> None:
            """Hantera val av posttyp."""
            if not text:
                return

            pt = self.post_type_combo.currentData()
            if not pt:
                return

            schemas = get_all_schemas_safe(self.app)
            schema = schemas.get(pt)

            if not schema:
                self.fields_table.setRowCount(0)
                return

            fields = getattr(schema, "fields", [])
            self.fields_table.setRowCount(len(fields))

            for row, field in enumerate(sorted(fields, key=lambda f: getattr(f, "position", 0))):
                name = getattr(field, "name", "")
                position = getattr(field, "position", 0)
                length = getattr(field, "length", 0)
                field_type = getattr(field, "field_type", "alphanumeric")
                required = "Ja" if getattr(field, "required", False) else "Nej"
                description = getattr(field, "description", "")

                self.fields_table.setItem(row, 0, QTableWidgetItem(name))
                self.fields_table.setItem(row, 1, QTableWidgetItem(str(position)))
                self.fields_table.setItem(row, 2, QTableWidgetItem(str(length)))
                self.fields_table.setItem(row, 3, QTableWidgetItem(field_type))
                self.fields_table.setItem(row, 4, QTableWidgetItem(required))
                self.fields_table.setItem(row, 5, QTableWidgetItem(description))

        def _do_compare(self) -> None:
            """Utför versionsjämförelse."""
            v1 = self.compare_v1_combo.currentText()
            v2 = self.compare_v2_combo.currentText()

            if not v1 or not v2:
                self.compare_result.setText("Välj två versioner att jämföra")
                return

            if v1 == v2:
                self.compare_result.setText("Samma version vald - välj olika versioner")
                return

            diff = None
            if self._plugin and hasattr(self._plugin, "compare_versions"):
                diff = self._plugin.compare_versions(v1, v2)
            else:
                viewer = get_plugin_safe(self.app, "ts_spec_viewer")
                if viewer and hasattr(viewer, "compare_versions"):
                    diff = viewer.compare_versions(v1, v2)
                else:
                    mgr = get_schema_manager(self.app)
                    if mgr and hasattr(mgr, "compare_versions"):
                        diff = mgr.compare_versions(v1, v2)

            if diff is None:
                diff = {"error": "Jämförelsefunktion ej tillgänglig"}

            # Formatera resultat
            result_lines = [
                "JÄMFÖRELSE: %s <-> %s" % (v1, v2),
                "=" * 50,
                ""
            ]

            if diff.get("error"):
                result_lines.append("Fel: %s" % diff["error"])
            else:
                added = diff.get("added", [])
                removed = diff.get("removed", [])
                modified = diff.get("modified", [])

                if added:
                    result_lines.append("TILLAGDA (%s):" % len(added))
                    for pt in added:
                        result_lines.append("  + PT%s" % pt)
                    result_lines.append("")

                if removed:
                    result_lines.append("BORTTAGNA (%s):" % len(removed))
                    for pt in removed:
                        result_lines.append("  - PT%s" % pt)
                    result_lines.append("")

                if modified:
                    result_lines.append("ÄNDRADE (%s):" % len(modified))
                    for pt in modified:
                        result_lines.append("  ~ PT%s" % pt)
                    result_lines.append("")

                if not any([added, removed, modified]):
                    result_lines.append("Inga skillnader hittades")

            self.compare_result.setText("\n".join(result_lines))

        def _export_json(self) -> None:
            """Exportera aktuella scheman till JSON."""
            default_name = "ts_schemas_%s.json" % datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Exportera scheman",
                default_name,
                "JSON-filer (*.json)"
            )

            if not filepath:
                return

            try:
                schemas = get_all_schemas_safe(self.app)
                version = get_active_version_safe(self.app)

                export_data = {
                    "version": version,
                    "exported_at": datetime.now().isoformat(),
                    "post_types": {}
                }

                for pt, schema in schemas.items():
                    fields_data = []
                    if hasattr(schema, "fields"):
                        for field in schema.fields:
                            fields_data.append({
                                "name": getattr(field, "name", ""),
                                "position": getattr(field, "position", 0),
                                "length": getattr(field, "length", 0),
                                "field_type": getattr(field, "field_type", "alphanumeric"),
                                "required": getattr(field, "required", False),
                                "description": getattr(field, "description", ""),
                            })

                    export_data["post_types"][pt] = {
                        "name": getattr(schema, "name", ""),
                        "total_length": getattr(schema, "total_length", 2500),
                        "fields": fields_data,
                    }

                _atomic_write_json(filepath, export_data)

                QMessageBox.information(
                    self,
                    "Export klar",
                    "Scheman exporterade till:\n%s" % filepath
                )

            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Export misslyckades",
                    "Kunde inte exportera:\n%s" % exc
                )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS

# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "Plugin",
    "VERSION",
    "HAS_PYSIDE6",
    "AUTHOR",
]

if HAS_PYSIDE6:
    __all__.append("TSSpecViewerWidget")
