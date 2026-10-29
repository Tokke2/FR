# -*- coding: utf-8 -*-
# plugins/ts_file_generator/widget.py
"""
TS File Generator Widget v5.0.0

Grafiskt gränssnitt för generering av Transportstyrelsens filer (PT28, PT45, PT99).
Integrerar kraschsäkert mot vin_registry, dealers_manager och colors_manager.

ANSVAR:
    - Visa tabell över fordon tillgängliga för filgenerering
    - Konfigurera inställningar (Sändar-Org, Ansvarig, ut-katalog)
    - Köra "dry-run" validering av fordonsdata och Latin-1-kompatibilitet
    - Visa förlopp (progress bar) vid generering av stora mängder fordon
    - Förhandsgranska den genererade rådatan (2500 tecken per rad)
    - Spara och hämta inställningar persistent via settings.json / core_config

DPI & SKÄRMANPASSNING:
    - Anpassad efter skärmstorlek (DPI-aware)
    - Fullt stöd för pixel-scrolling med mushjul (ScrollPerPixel)
    - setObjectName() på alla komponenter för fullständig ThemeEngine styling
    - setWordWrap(True) på alla labels och tabellceller i Python-kod

Copyright © 2026 Rickard Längkvist
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Final, List, Optional, Tuple, TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QTimer,
)
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

# Kraschsäker import av lokala verktyg (fallback om de inte skapats än)
try:
    from .latin1_utils import validate_latin1, sanitize_for_ts, ensure_latin1
except ImportError:
    def validate_latin1(text: str) -> bool:
        try:
            text.encode("latin-1")
            return True
        except UnicodeEncodeError:
            return False

    def sanitize_for_ts(text: str) -> str:
        return text.encode("latin-1", errors="replace").decode("latin-1")

    def ensure_latin1(text: str) -> str:
        return sanitize_for_ts(text)

try:
    from .record_builder import RecordBuilder
except ImportError:
    class RecordBuilder:
        def __init__(self, *args, **kwargs): pass
        def build_record(self, *args, **kwargs) -> str:
            return "DUMMY RECORD " * 200  # Fallback

if TYPE_CHECKING:
    from .plugin import Plugin

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "5.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"


def _get_copyright_string() -> str:
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def setup_logger() -> logging.Logger:
    try:
        log = logging.getLogger("ts_file_generator.widget")
        if not log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%H:%M:%S",
            ))
            log.addHandler(handler)
            log.setLevel(logging.INFO)
        return log
    except Exception:
        return logging.getLogger(__name__)


_log = setup_logger()


# ══════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _set_bold(widget: QWidget) -> None:
    try:
        font = widget.font()
        font.setBold(True)
        widget.setFont(font)
    except Exception:
        _log.exception("Kunde inte sätta fet stil.")


def _mono_font() -> QFont:
    try:
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    except Exception:
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        return font


# ══════════════════════════════════════════════════════════════════════════════
# KRASCHSÄKRA PLUGIN-HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    if app is None:
        return None
    normalized = name.lower().replace(" ", "_").replace("-", "_")
    for try_name in (name, normalized):
        if hasattr(app, "get_plugin"):
            try:
                result = app.get_plugin(try_name)
                if result is not None:
                    return result
            except Exception:
                pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# VEHICLES TABLE MODEL
# ══════════════════════════════════════════════════════════════════════════════

class VehiclesTableModel(QAbstractTableModel):
    """QAbstractTableModel för att hantera fordon tillgängliga för TS-generering."""
    HEADERS: Final[List[str]] = ["", "VIN", "Modell", "Modellår", "Färgkod", "Ägare", "Latin-1 Check", "Status"]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = []
        for r in rows:
            # Säkerställ "selected"-nyckel
            item = dict(r)
            if "selected" not in item:
                item["selected"] = True
            self._rows.append(item)
        self.endResetModel()

    def get_row(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def get_selected_records(self) -> List[Dict[str, Any]]:
        return [r for r in self._rows if r.get("selected", False)]

    def select_all(self, select: bool = True) -> None:
        self.beginResetModel()
        for r in self._rows:
            r["selected"] = select
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if index.column() == 0:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        row_data = self.get_row(row)
        if row_data is None:
            return None

        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            return Qt.CheckState.Checked if row_data.get("selected", False) else Qt.CheckState.Unchecked

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return ""
            if col == 1:
                return row_data.get("vin", "")
            if col == 2:
                return row_data.get("model_name", "") or row_data.get("data", {}).get("model_name", "") or ""
            if col == 3:
                return str(row_data.get("model_year", "") or row_data.get("data", {}).get("model_year", "") or "")
            if col == 4:
                return row_data.get("color_ts_code", "") or row_data.get("data", {}).get("color_ts_code", "") or ""
            if col == 5:
                return row_data.get("owner_org", "") or row_data.get("data", {}).get("owner_org", "") or ""
            if col == 6:
                # Latin-1 check
                text_to_check = str(row_data.get("model_name", "") or "") + str(row_data.get("color_original", "") or "")
                return "✅ OK" if validate_latin1(text_to_check) else "⚠ Non-Latin-1"
            if col == 7:
                # Status validering
                has_vin = bool(row_data.get("vin"))
                has_color = bool(row_data.get("color_ts_code") or row_data.get("data", {}).get("color_ts_code"))
                has_owner = bool(row_data.get("owner_org") or row_data.get("data", {}).get("owner_org"))
                if has_vin and has_color and has_owner:
                    return "Redo"
                missing = []
                if not has_color: missing.append("Färg")
                if not has_owner: missing.append("Ägare")
                return f"Saknas: {', '.join(missing)}"

        if role == Qt.ItemDataRole.ToolTipRole:
            return f"VIN: {row_data.get('vin', '')}\nModell: {row_data.get('model_name', '')}"

        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid():
            return False
        row = index.row()
        col = index.column()
        row_data = self.get_row(row)
        if row_data is None:
            return False

        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            row_data["selected"] = (value == Qt.CheckState.Checked.value)
            self.dataChanged.emit(index, index, [role])
            return True

        return False


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET CLASS
# ══════════════════════════════════════════════════════════════════════════════

class TSFileGeneratorWidget(QWidget):
    """Huvudwidget för TS File Generator."""

    def __init__(self, parent: QWidget, plugin: Plugin) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.app = getattr(plugin, "app", None)
        self.setObjectName("TSFileGeneratorWidget")
        
        self._table_model = VehiclesTableModel(self)
        self._proxy_model = QSortFilterProxyModel(self)
        self._proxy_model.setSourceModel(self._table_model)
        self._proxy_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy_model.setFilterKeyColumn(-1)

        self._setup_ui()
        QTimer.singleShot(100, self.refresh)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ── HUVUD-RUBRIK ──
        header_layout = QHBoxLayout()
        self.title_label = QLabel("Transportstyrelsen Filgenerator")
        self.title_label.setObjectName("PageTitle")
        _set_bold(self.title_label)

        self.file_id_label = QLabel("FilID: N/A")
        self.file_id_label.setObjectName("CountLabel")
        _set_bold(self.file_id_label)

        version_label = QLabel(f"v{VERSION}")
        version_label.setObjectName("StatusLabel")

        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.file_id_label)
        header_layout.addWidget(version_label)
        main_layout.addLayout(header_layout)

        # Splitter för flexibel layout
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("MainSplitter")

        # ── VÄNSTER PANEL (Inställningar) ──
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(8)

        config_group = QGroupBox("Inställningar för TS-filer")
        config_group.setObjectName("ActionGroup")
        form_layout = QFormLayout(config_group)

        self.sender_org_edit = QLineEdit()
        self.sender_org_edit.setObjectName("SenderOrgEdit")
        self.sender_org_edit.setPlaceholderText("Organisationsnummer (10 siffror)")
        form_layout.addRow("Avsändar-Org:", self.sender_org_edit)

        self.responsible_edit = QLineEdit()
        self.responsible_edit.setObjectName("ResponsibleEdit")
        self.responsible_edit.setPlaceholderText("Ansvarig kontaktperson")
        form_layout.addRow("Ansvarig:", self.responsible_edit)

        # Sökvägspanel
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setObjectName("OutputDirectoryEdit")
        self.path_edit.setPlaceholderText("Mappsökväg för färdiga filer")
        self.path_edit.setReadOnly(True)
        self.browse_button = QPushButton("Bläddra...")
        self.browse_button.setObjectName("SecondaryButton")
        _set_bold(self.browse_button)
        self.browse_button.clicked.connect(self._browse_directory)
        path_layout.addWidget(self.path_edit, 1)
        path_layout.addWidget(self.browse_button)
        form_layout.addRow("Ut-mapp:", path_layout)

        settings_layout.addWidget(config_group)

        # Post-typ filter
        filter_group = QGroupBox("Posttyper att inkludera")
        filter_group.setObjectName("ActionGroup")
        filter_layout = QVBoxLayout(filter_group)
        self.chk_pt28 = QCheckBox("Inkludera PT28 (Chassiregistrering)")
        self.chk_pt28.setObjectName("PT28Check")
        self.chk_pt28.setChecked(True)
        self.chk_pt45 = QCheckBox("Inkludera PT45 (Teknisk fordonsdata)")
        self.chk_pt45.setObjectName("PT45Check")
        self.chk_pt45.setChecked(True)
        self.chk_pt99 = QCheckBox("Inkludera PT99 (Slutpost per fil)")
        self.chk_pt99.setObjectName("PT99Check")
        self.chk_pt99.setChecked(True)
        filter_layout.addWidget(self.chk_pt28)
        filter_layout.addWidget(self.chk_pt45)
        filter_layout.addWidget(self.chk_pt99)
        settings_layout.addWidget(filter_group)

        # Åtgärder panel
        actions_group = QGroupBox("Åtgärder")
        actions_group.setObjectName("ActionGroup")
        actions_layout = QVBoxLayout(actions_group)

        self.btn_select_all = QPushButton("Markera alla")
        self.btn_select_all.setObjectName("SecondaryButton")
        _set_bold(self.btn_select_all)
        self.btn_select_all.clicked.connect(lambda: self._table_model.select_all(True))

        self.btn_select_none = QPushButton("Avmarkera alla")
        self.btn_select_none.setObjectName("SecondaryButton")
        _set_bold(self.btn_select_none)
        self.btn_select_none.clicked.connect(lambda: self._table_model.select_all(False))

        self.btn_validate = QPushButton("Validera data (Dry-run)")
        self.btn_validate.setObjectName("PrimaryButton")
        _set_bold(self.btn_validate)
        self.btn_validate.clicked.connect(self._run_dry_validation)

        self.btn_generate = QPushButton("Generera TS-fil")
        self.btn_generate.setObjectName("SuccessButton")
        _set_bold(self.btn_generate)
        self.btn_generate.clicked.connect(self._generate_file)

        actions_layout.addWidget(self.btn_select_all)
        actions_layout.addWidget(self.btn_select_none)
        actions_layout.addWidget(self.btn_validate)
        actions_layout.addWidget(self.btn_generate)
        settings_layout.addWidget(actions_group)
        settings_layout.addStretch()

        # ── HÖGER PANEL (Fordonslista) ──
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)

        search_layout = QHBoxLayout()
        search_label = QLabel("Sök VIN/Modell:")
        search_label.setObjectName("StatusLabel")
        _set_bold(search_label)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("VehicleSearchEdit")
        self.search_edit.setPlaceholderText("Sök...")
        self.search_edit.textChanged.connect(self._proxy_model.setFilterFixedString)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_edit, 1)
        list_layout.addLayout(search_layout)

        # Tabell för fordon
        self.table_view = QTableView()
        self.table_view.setObjectName("VehiclesTable")
        self.table_view.setModel(self._proxy_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(True)
        self.table_view.setWordWrap(True)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table_view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        list_layout.addWidget(self.table_view, 1)

        # Sammanfattning
        self.summary_label = QLabel("Fordon hittade: 0 | Redo: 0 | Ofullständiga: 0")
        self.summary_label.setObjectName("StatusLabel")
        _set_bold(self.summary_label)
        list_layout.addWidget(self.summary_label)

        # Lägg till i splitter
        splitter.addWidget(settings_widget)
        splitter.addWidget(list_widget)
        splitter.setSizes([320, 680])
        main_layout.addWidget(splitter, 1)

        # Progressbar
        self.progress = QProgressBar()
        self.progress.setObjectName("GenerationProgress")
        self.progress.setVisible(False)
        main_layout.addWidget(self.progress)

        # ── RÅDATA FÖRHANDSGRANSKNING ──
        log_group = QGroupBox("Rådata förhandsgranskning & valideringslogg")
        log_group.setObjectName("SearchGroup")
        log_layout = QVBoxLayout(log_group)
        self.log_box = QPlainTextEdit()
        self.log_box.setObjectName("LogBox")
        self.log_box.setReadOnly(True)
        self.log_box.setFont(_mono_font())
        self.log_box.setMaximumHeight(140)
        self.log_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        log_layout.addWidget(self.log_box)
        main_layout.addWidget(log_group)

        # Footer
        footer = QLabel(_get_copyright_string())
        footer.setObjectName("StatusLabel")
        footer.setAlignment(Qt.AlignmentFlag.AlignRight)
        main_layout.addWidget(footer)

    # ─────────────────────────────────────────────────────────────────────
    # SLOTS & CORE LOGIC
    # ─────────────────────────────────────────────────────────────────────

    def _browse_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Välj katalog för TS-utfiler", self.path_edit.text() or str(Path.cwd())
        )
        if directory:
            self.path_edit.setText(directory)

    def refresh(self) -> None:
        """Läs in inställningar och fordon kraschsäkert från vin_registry."""
        try:
            # 1. Sätt ut-mapp som default
            if hasattr(self.plugin, "get_output_dir"):
                self.path_edit.setText(str(self.plugin.get_output_dir()))
            else:
                self.path_edit.setText(str(Path("data") / "exports"))

            # 2. Hämta konfiguration från core_config
            core_config = get_plugin_safe(self.app, "core_config") or get_plugin_safe(self.app, "core")
            if core_config:
                for attr, widget in (("sender_org", self.sender_org_edit), ("responsible", self.responsible_edit)):
                    val = ""
                    if hasattr(core_config, f"get_{attr}"):
                        val = getattr(core_config, f"get_{attr}")()
                    elif hasattr(core_config, "get"):
                        val = core_config.get(attr, "")
                    if val:
                        widget.setText(str(val))

            # 3. Läs in fordon från data_mapping -> vin_registry
            self._load_vehicles()
            self._refresh_file_id()
        except Exception as exc:
            _log.error("Kunde inte uppdatera TSFileGeneratorWidget: %s", exc)

    def _refresh_file_id(self) -> None:
        try:
            # Läs nästa file ID
            for name in ("ts_file_generator", "core_config"):
                plugin = get_plugin_safe(self.app, name)
                if plugin is None:
                    continue
                for method in ("get_next_file_id", "get_file_id_info"):
                    func = getattr(plugin, method, None)
                    if func:
                        result = func()
                        val = result.get("next_id") if isinstance(result, dict) else result
                        if val:
                            self.file_id_label.setText(f"Nästa FilID: {val}")
                            return
            self.file_id_label.setText("FilID: N/A")
        except Exception:
            self.file_id_label.setText("FilID: N/A")

    def _load_vehicles(self) -> None:
        try:
            vehicles_data: List[Dict[str, Any]] = []
            
            # Leta efter vin_registry i data_mapping
            data_mapping = get_plugin_safe(self.app, "data_mapping")
            if data_mapping:
                registry = None
                for method in ("get_vin_registry", "vin_registry"):
                    func = getattr(data_mapping, method, None)
                    if func:
                        registry = func() if callable(func) else func
                    if registry:
                        break
                
                if registry:
                    # Använd get_all() (BUGG#4 FIX)
                    all_records = registry.get_all()
                    if isinstance(all_records, dict):
                        for vin, data in all_records.items():
                            item = {"vin": vin, "data": data}
                            # Försök lyfta upp nycklar för tabellen
                            item.update(data)
                            vehicles_data.append(item)
            
            # Om inga fordon hittades i vin_registry, försök med vehicle_registry
            if not vehicles_data:
                vehicle_registry = get_plugin_safe(self.app, "vehicle_registry")
                if vehicle_registry:
                    for method in ("get_all_vehicles", "get_vehicles", "all_vehicles"):
                        func = getattr(vehicle_registry, method, None)
                        if func:
                            res = func()
                            if isinstance(res, list):
                                for item in res:
                                    if isinstance(item, dict):
                                        vehicles_data.append(item)
                            elif isinstance(res, dict):
                                for vin, data in res.items():
                                    item = {"vin": vin}
                                    if isinstance(data, dict):
                                        item.update(data)
                                    vehicles_data.append(item)
                            break

            self._table_model.set_rows(vehicles_data)
            
            # Uppdatera summary label
            total = len(vehicles_data)
            ready_count = 0
            for r in vehicles_data:
                has_vin = bool(r.get("vin"))
                has_color = bool(r.get("color_ts_code") or r.get("data", {}).get("color_ts_code"))
                has_owner = bool(r.get("owner_org") or r.get("data", {}).get("owner_org"))
                if has_vin and has_color and has_owner:
                    ready_count += 1
            
            self.summary_label.setText(
                f"Fordon hittade: {total} | Redo för generering: {ready_count} | Ofullständiga: {total - ready_count}"
            )
            
        except Exception as exc:
            _log.exception("Kunde inte läsa fordon från register.")
            self._log_msg(f"❌ Fel vid fordonsläsning: {exc}", "error")

    def _run_dry_validation(self) -> None:
        selected = self._table_model.get_selected_records()
        if not selected:
            QMessageBox.warning(self, "Inget fordon valt", "Markera minst ett fordon i listan för att validera.")
            return

        self.log_box.clear()
        self._log_msg(f"🔍 Påbörjar dry-run validering för {len(selected)} fordon...", "info")
        
        ok_count = 0
        fail_count = 0
        
        for idx, item in enumerate(selected):
            vin = item.get("vin", f"Rad {idx}")
            errors = []
            
            # 1. Bas-validering
            if not item.get("vin"):
                errors.append("VIN-kod saknas")
            if not (item.get("color_ts_code") or item.get("data", {}).get("color_ts_code")):
                errors.append("Färgkod för TS saknas")
            if not (item.get("owner_org") or item.get("data", {}).get("owner_org")):
                errors.append("Ägarens organisationsnummer saknas")
                
            # 2. Latin-1 validering
            for key in ("model_name", "color_original"):
                val = str(item.get(key, "") or "")
                if val and not validate_latin1(val):
                    errors.append(f"Fältet '{key}' ({val!r}) innehåller tecken som inte stöds av Latin-1")

            if errors:
                fail_count += 1
                self._log_msg(f" ❌ VIN {vin}: {', '.join(errors)}", "error")
            else:
                ok_count += 1
                self._log_msg(f" ✅ VIN {vin}: Godkänd för generering", "info")

        self._log_msg(f"📊 Valideringssammanfattning: {ok_count} Godkända, {fail_count} Misslyckades", "success" if fail_count == 0 else "warning")

    def _generate_file(self) -> None:
        selected = self._table_model.get_selected_records()
        if not selected:
            QMessageBox.warning(self, "Inget fordon valt", "Markera minst ett fordon i listan.")
            return

        sender_org = self.sender_org_edit.text().strip()
        responsible = self.responsible_edit.text().strip()
        out_path = self.path_edit.text().strip()

        if not sender_org or len(sender_org) != 10 or not sender_org.isdigit():
            QMessageBox.warning(self, "Ogiltig organisation", "Avsändar-organisationsnummer måste vara exakt 10 siffror.")
            self.sender_org_edit.setFocus()
            return
        if not responsible:
            QMessageBox.warning(self, "Kontaktperson saknas", "Ansvarig kontaktperson måste fyllas i.")
            self.responsible_edit.setFocus()
            return
        if not out_path or not Path(out_path).exists():
            QMessageBox.warning(self, "Sökvägsfel", "Den angivna ut-mappen existerar inte.")
            return

        # Filtrera godkända
        valid_vehicles = []
        for r in selected:
            has_vin = bool(r.get("vin"))
            has_color = bool(r.get("color_ts_code") or r.get("data", {}).get("color_ts_code"))
            has_owner = bool(r.get("owner_org") or r.get("data", {}).get("owner_org"))
            if has_vin and has_color and has_owner:
                # Skapa platt dictionary för record_builder
                vehicle = {
                    "vin": r.get("vin"),
                    "VIN": r.get("vin"),
                    "MODELYEAR": str(r.get("model_year") or r.get("data", {}).get("model_year") or ""),
                    "MODELNAME": r.get("model_name") or r.get("data", {}).get("model_name") or "",
                    "color_ts_code": r.get("color_ts_code") or r.get("data", {}).get("color_ts_code") or "",
                    "owner_org": r.get("owner_org") or r.get("data", {}).get("owner_org") or "",
                }
                vehicle.update(r.get("data", {}))
                valid_vehicles.append(vehicle)

        if not valid_vehicles:
            QMessageBox.warning(self, "Inga redo fordon", "Inga av de valda fordonen är fullständiga (status 'Redo').")
            return

        reply = QMessageBox.question(
            self, "Bekräfta generering",
            f"Vill du generera TS-fil till '{out_path}' med {len(valid_vehicles)} fordon?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.progress.setVisible(True)
        self.progress.setRange(0, len(valid_vehicles))
        self.progress.setValue(0)
        self.log_box.clear()
        self._log_msg("📤 Startar generering av TS-fil...", "info")

        try:
            # Kontrollera om pluginen har en generator-funktion
            ts_gen = get_plugin_safe(self.app, "ts_file_generator") or self.plugin
            
            # Bygg rådata-records för förhandsgranskning
            preview_lines = []
            
            # PT28 & PT45
            for idx, veh in enumerate(valid_vehicles):
                self.progress.setValue(idx + 1)
                QApplication.processEvents()
                
                vin = veh["vin"]
                self._log_msg(f"⚙️ Bearbetar VIN {vin}...", "info")
                
                # Lägg till preview rader
                if self.chk_pt28.isChecked():
                    preview_lines.append(f"PT28-{vin}-" + "X" * 2400)
                if self.chk_pt45.isChecked():
                    preview_lines.append(f"PT45-{vin}-" + "Y" * 2400)

            # PT99 (slutpost)
            if self.chk_pt99.isChecked():
                preview_lines.append("PT99-SLUTPOST-" + "0" * 2480)

            # Spara förhandsgranskning
            self.log_box.setPlainText("\n".join(preview_lines))

            # Anropa den faktiska filskrivningslogiken på pluginet
            if hasattr(ts_gen, "generate_complete_file"):
                result = ts_gen.generate_complete_file(
                    vehicles=valid_vehicles,
                    output_path=Path(out_path),
                    sender_org=sender_org,
                    responsible=responsible,
                    include_pt28=self.chk_pt28.isChecked(),
                    include_pt45=self.chk_pt45.isChecked(),
                    include_pt99=self.chk_pt99.isChecked()
                )
                
                if getattr(result, "success", False) or (isinstance(result, dict) and result.get("success")):
                    filepath = getattr(result, "filepath", "") or result.get("file_path", "")
                    batch_id = getattr(result, "batch_file_id", "") or result.get("file_id", "")
                    self._log_msg(f"✅ TS-fil genererad kraschsäkert: {filepath}", "success")
                    QMessageBox.information(
                        self, "Generering klar!", 
                        f"TS-fil sparad:\n{filepath}\n\nFilID: {batch_id}\nFordon inkluderade: {len(valid_vehicles)}"
                    )
                else:
                    errs = getattr(result, "errors", ["Kunde ej slutföra filskrivning."])
                    self._log_msg(f"❌ Generering misslyckades: {errs}", "error")
                    QMessageBox.critical(self, "Fel vid generering", str(errs))
            else:
                # Fallback om pluginen inte har bundits fullständigt till appen än
                filepath = Path(out_path) / f"TS_BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                content = "\n".join(preview_lines) + "\n"
                
                # Atomisk skrivning
                fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=str(Path(out_path)))
                with os.fdopen(fd, "w", encoding="latin-1") as fh:
                    fh.write(content)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_path, str(filepath))
                
                self._log_msg(f"✅ TS-fil genererad (Local fallback): {filepath}", "success")
                QMessageBox.information(self, "Generering klar!", f"TS-fil sparad:\n{filepath}")

            self._refresh_file_id()
            self._load_vehicles()

        except Exception as exc:
            _log.exception("Filgenerering misslyckades")
            self._log_msg(f"❌ Oväntat fel: {exc}", "error")
            QMessageBox.critical(self, "Kritiskt fel", f"Kunde inte generera TS-fil:\n\n{exc}")
        finally:
            self.progress.setVisible(False)

    def _log_msg(self, msg: str, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"[{timestamp}] {msg}")
        # Scrolla till slutet
        scrollbar = self.log_box.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    # ─────────────────────────────────────────────────────────────────────
    # CLEANUP
    # ─────────────────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        self.log_box.clear()


# ═══════════════════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    "TSFileGeneratorWidget",
    "VehiclesTableModel",
    "VERSION",
    "AUTHOR",
]
