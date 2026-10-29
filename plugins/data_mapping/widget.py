# -*- coding: utf-8 -*-
"""
data_mapping.widget v5.0.0

GenerateFilePage – Import / Mappning / Generera
QTableView + QAbstractTableModel, QSortFilterProxyModel, DPI-aware

Copyright © 2026 Rickard Längkvist
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSizePolicy, QSplitter, QTabWidget,
    QTableView, QVBoxLayout, QWidget
)

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    PANDAS_AVAILABLE = False
    pd = None  # type: ignore

# local service
try:
    from .column_mapping_service import (
        ColumnMappingService, MappingEntry, get_column_mapping_service
    )
except Exception:
    ColumnMappingService = None  # type: ignore
    MappingEntry = None  # type: ignore
    def get_column_mapping_service():  # type: ignore
        return None


VERSION = "5.0.0"
AUTHOR = "Rickard Längkvist"


def _get_logger() -> logging.Logger:
    return logging.getLogger("data_mapping.widget")


_log = _get_logger()


def get_copyright_string() -> str:
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ── helpers ──

def _set_bold(w: QWidget) -> None:
    f = w.font()
    f.setBold(True)
    w.setFont(f)


def _mono_font() -> QFont:
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try: os.unlink(tmp)
        except Exception: pass
        raise


def _read_json_safe(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _pretty_json(data: Any) -> str:
    try:
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        return str(data)


SKIP_SHEETS_DEFAULT = ['25Kw', '25kw', '25KW', 'Kw', 'kw', 'KW']


def _should_skip_sheet(name: str) -> bool:
    n = str(name).strip()
    if n in SKIP_SHEETS_DEFAULT:
        return True
    low = n.lower()
    return low.endswith("kw") or low.endswith("kwh")


def _normalize_header(h: str) -> str:
    return str(h).strip()


def _get_excel_engine(path: Path) -> Optional[str]:
    s = path.suffix.lower()
    if s in (".xlsx", ".xlsm", ".xltx", ".xltm"):
        return "openpyxl"
    if s == ".xls":
        return "xlrd"
    return None


# ══════════════════════════════════════════════════════════════
# Table Models
# ══════════════════════════════════════════════════════════════

class MappingTableModel(QAbstractTableModel):
    HEADERS = ["Källkolumn", "TS-mål", "Beskrivning", "Auto", "Conf."]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[MappingEntry] = []

    def set_entries(self, entries: List[Any]) -> None:
        self.beginResetModel()
        self._rows = list(entries)
        self.endResetModel()

    def get_entry(self, row: int) -> Optional[Any]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self._rows[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                e.source,
                e.target,
                e.description,
                "Ja" if getattr(e, "auto_detected", False) else "Nej",
                f"{getattr(e, 'confidence', 1.0):.2f}",
            ][c]
        return None


class ImportPreviewModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._headers: List[str] = []
        self._rows: List[List[Any]] = []

    def set_data(self, headers: List[str], rows: List[List[Any]]):
        self.beginResetModel()
        self._headers = list(headers)
        self._rows = [list(r) for r in rows]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            r, c = index.row(), index.column()
            try:
                v = self._rows[r][c]
                return "" if v is None else str(v)
            except Exception:
                return ""
        return None


# ═══════════════════════════════════════════════════════════════════
# MappingDialog
# ═══════════════════════════════════════════════════════════════════

class MappingDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], svc: Any, headers: Optional[List[str]] = None, existing_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self._svc = svc
        self._headers = headers or []
        self.setWindowTitle("Fordonsdata-mappning")
        self.setModal(True)
        self.resize(560, 320)
        self.setObjectName("MappingDialog")

        form = QFormLayout()
        self.source_combo = QComboBox()
        self.source_combo.setObjectName("MappingSourceCombo")
        self.source_combo.setEditable(True)
        if self._headers:
            self.source_combo.addItems(self._headers)

        self.target_edit = QLineEdit()
        self.target_edit.setObjectName("MappingTargetEdit")
        self.target_edit.setPlaceholderText("Ex: COMNAME, VINCODE, MODELNAME ...")

        self.desc_edit = QLineEdit()
        self.desc_edit.setObjectName("MappingDescEdit")

        form.addRow("Källkolumn:", self.source_combo)
        form.addRow("TS-mål:", self.target_edit)
        form.addRow("Beskrivning:", self.desc_edit)

        if existing_data:
            self.source_combo.setCurrentText(str(existing_data.get("source", "")))
            self.target_edit.setText(str(existing_data.get("target", "")))
            self.desc_edit.setText(str(existing_data.get("description", "")))
            self.source_combo.setEnabled(False)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def _validate_accept(self):
        src = self.source_combo.currentText().strip()
        tgt = self.target_edit.text().strip()
        if not src or not tgt:
            QMessageBox.warning(self, "Validering", "Både källkolumn och TS-mål måste anges.")
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        return {
            "source": self.source_combo.currentText().strip(),
            "target": self.target_edit.text().strip(),
            "description": self.desc_edit.text().strip(),
        }


# ═══════════════════════════════════════════════════════════════════
# DependencyIndicator
# ═══════════════════════════════════════════════════════════════════

class DependencyIndicator(QGroupBox):
    def __init__(self, app: Any, parent=None):
        super().__init__("Beroenden", parent)
        self._app = app
        self.setObjectName("DependencyIndicator")
        lay = QHBoxLayout(self)
        self._label = QLabel("Kontrollerar plugins...")
        self._label.setWordWrap(True)
        self._label.setObjectName("DependencyLabel")
        lay.addWidget(self._label)
        self.refresh()

    def refresh(self):
        names = [
            "ts_schema_manager", "dealers_manager", "ts_file_generator",
            "response_viewer", "ts_spec_import", "dispatch_viewer", "colors_manager"
        ]
        ok, missing = 0, []
        get_plugin = getattr(self._app, "get_plugin_safe", None)
        for n in names:
            found = False
            try:
                if callable(get_plugin):
                    found = get_plugin(n) is not None
            except Exception:
                found = False
            if found:
                ok += 1
            else:
                missing.append(n)
        txt = f"{ok}/{len(names)} plugins aktiva"
        if missing:
            txt += " – saknas: " + ", ".join(missing)
        self._label.setText(txt)


# ═══════════════════════════════════════════════════════════════════
# ExcelImportEngine
# ═══════════════════════════════════════════════════════════════════

class ExcelImportEngine:
    def __init__(self, skip_sheets: Optional[List[str]] = None, log_callback: Optional[Callable[[str, str], None]] = None):
        self.skip_sheets = skip_sheets or SKIP_SHEETS_DEFAULT[:]
        self._log = log_callback or (lambda m, l: None)

    def import_file(self, path: Path, progress_cb: Optional[Callable[[int, int, str], None]] = None) -> Tuple[List[str], List[List[Any]], List[Dict[str, Any]]]:
        if not PANDAS_AVAILABLE:
            raise RuntimeError("pandas saknas – installera pandas openpyxl")
        xls = pd.ExcelFile(path, engine=_get_excel_engine(path))
        all_headers: List[str] = []
        all_rows: List[List[Any]] = []
        sheet_info: List[Dict[str, Any]] = []

        sheets = [s for s in xls.sheet_names if not _should_skip_sheet(s)]
        total = len(sheets)
        for idx, sheet in enumerate(sheets, 1):
            if progress_cb:
                progress_cb(idx, total, sheet)
                QApplication.processEvents()
            try:
                df = pd.read_excel(xls, sheet_name=sheet, dtype=str).fillna("")
                headers = [_normalize_header(str(c)) for c in df.columns]
                rows = df.values.tolist()
                if headers and headers not in [all_headers]:
                    if not all_headers:
                        all_headers = headers
                all_rows.extend(rows)
                sheet_info.append({"sheet": sheet, "rows": len(rows), "status": "ok"})
                self._log(f"Blad {sheet}: {len(rows)} rader", "info")
            except Exception as exc:
                sheet_info.append({"sheet": sheet, "rows": 0, "status": f"fel: {exc}"})
                self._log(f"Blad {sheet} hoppades över: {exc}", "warning")

        # spara headers
        try:
            out_path = Path("data/mappings/imported_headers.json")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(out_path, {
                "updated_at": datetime.now().isoformat(),
                "source_file": str(path),
                "headers": all_headers,
                "sheet_info": sheet_info
            })
        except Exception:
            pass

        return all_headers, all_rows, sheet_info


# ═══════════════════════════════════════════════════════════════════
# ColumnMappingManager
# ═══════════════════════════════════════════════════════════════════

class ColumnMappingManager:
    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self._log_cb = log_callback or (lambda m, l: None)
        self._svc = get_column_mapping_service() if callable(get_column_mapping_service) else None
        if self._svc and hasattr(self._svc, "load"):
            try: self._svc.load()
            except Exception: pass

    @property
    def service(self):
        return self._svc

    def auto_populate(self, headers: List[str]) -> int:
        if not self._svc:
            return 0
        n = 0
        if hasattr(self._svc, "auto_populate_from_headers"):
            n = self._svc.auto_populate_from_headers(headers, auto_save=False)
        if hasattr(self._svc, "auto_detect"):
            try: self._svc.auto_detect(headers, overwrite_existing=False, auto_save=False)
            except Exception: pass
        if hasattr(self._svc, "save"):
            try: self._svc.save()
            except Exception: pass
        return n

    def get_entries(self) -> List[Any]:
        if not self._svc or not hasattr(self._svc, "get_all_mappings"):
            return []
        return self._svc.get_all_mappings()

    def set_mapping(self, source: str, target: str, description: str = "") -> bool:
        if not self._svc or not hasattr(self._svc, "set_mapping"):
            return False
        return bool(self._svc.set_mapping(source, target, description, auto_detected=False, confidence=1.0, auto_save=True))

    def remove_mapping(self, source: str) -> bool:
        if not self._svc or not hasattr(self._svc, "remove_mapping"):
            return False
        return bool(self._svc.remove_mapping(source, auto_save=True))


# ═══════════════════════════════════════════════════════════════════
# ImportTab
# ═══════════════════════════════════════════════════════════════════

class ImportTab(QWidget):
    headers_imported = Signal(list)

    def __init__(self, parent: QWidget, app: Any, log_callback: Callable[[str, str], None], on_headers_imported: Callable[[List[str]], None]):
        super().__init__(parent)
        self._app = app
        self._log_cb = log_callback
        self._on_headers_imported = on_headers_imported
        self.setObjectName("ImportTab")

        self._import_engine = ExcelImportEngine(
            skip_sheets=list(SKIP_SHEETS_DEFAULT),
            log_callback=log_callback,
        )
        self._preview_model = ImportPreviewModel(self)
        self._preview_proxy = QSortFilterProxyModel(self)
        self._preview_proxy.setSourceModel(self._preview_model)
        self._preview_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._preview_proxy.setFilterKeyColumn(-1)

        self._imported_headers: List[str] = []
        self._imported_rows: List[List[Any]] = []
        self._sheet_info: List[Dict[str, Any]] = []

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Kontrollgrupp
        ctrl_group = QGroupBox("Excel-import")
        ctrl_group.setObjectName("ActionGroup")
        ctrl_layout = QGridLayout(ctrl_group)

        self.filepath_edit = QLineEdit()
        self.filepath_edit.setObjectName("ImportFilepathEdit")
        self.filepath_edit.setPlaceholderText("Välj Excel-fil med fordonsdata...")
        self.filepath_edit.setReadOnly(True)

        self.browse_button = QPushButton("Bläddra...")
        self.browse_button.setObjectName("SecondaryButton")
        _set_bold(self.browse_button)
        self.browse_button.clicked.connect(self._browse_file)

        self.import_button = QPushButton("Importera")
        self.import_button.setObjectName("PrimaryButton")
        _set_bold(self.import_button)
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._run_import)

        # Fordonsdata-mappning – från din patch
        self.mapping_button = QPushButton("Fordonsdata-mappning")
        self.mapping_button.setObjectName("SecondaryButton")
        _set_bold(self.mapping_button)
        self.mapping_button.setToolTip("Öppna dialog för manuell kolumnmappning av fordonsdata")
        self.mapping_button.clicked.connect(self._open_vehicle_mapping_dialog)

        self.clear_button = QPushButton("Rensa")
        self.clear_button.setObjectName("DangerButton")
        _set_bold(self.clear_button)
        self.clear_button.clicked.connect(self._clear_import)

        self.import_status_label = QLabel("Ingen fil importerad.")
        self.import_status_label.setObjectName("StatusLabel")
        self.import_status_label.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setObjectName("ImportProgress")
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)

        ctrl_layout.addWidget(QLabel("Fil:"), 0, 0)
        ctrl_layout.addWidget(self.filepath_edit, 0, 1)
        ctrl_layout.addWidget(self.browse_button, 0, 2)
        ctrl_layout.addWidget(self.import_button, 0, 3)
        ctrl_layout.addWidget(self.mapping_button, 0, 4)
        ctrl_layout.addWidget(self.clear_button, 0, 5)
        ctrl_layout.addWidget(self.import_status_label, 1, 0, 1, 4)
        ctrl_layout.addWidget(self.progress, 1, 4, 1, 2)
        ctrl_layout.setColumnStretch(1, 1)

        layout.addWidget(ctrl_group)

        # Sök + preview
        search_group = QGroupBox("Förhandsgranskning")
        search_group.setObjectName("SearchGroup")
        sg_lay = QVBoxLayout(search_group)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Sök:"))
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("ImportSearchEdit")
        self.search_edit.setPlaceholderText("Filtrera importerade rader...")
        self.search_edit.textChanged.connect(lambda t: self._preview_proxy.setFilterFixedString(t))
        search_row.addWidget(self.search_edit, 1)
        sg_lay.addLayout(search_row)

        self.preview_table = QTableView()
        self.preview_table.setObjectName("ImportPreviewTable")
        self.preview_table.setModel(self._preview_proxy)
        self.preview_table.setSortingEnabled(True)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.preview_table.setWordWrap(True)
        sg_lay.addWidget(self.preview_table, 1)

        self.count_label = QLabel("0 rader")
        self.count_label.setObjectName("CountLabel")
        sg_lay.addWidget(self.count_label)

        layout.addWidget(search_group, 1)

    # ── import ──
    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Välj fordonsdata Excel", "", "Excel (*.xlsx *.xls *.xlsm)")
        if path:
            self.filepath_edit.setText(path)
            self.import_button.setEnabled(True)
            self.import_status_label.setText(f"Vald: {Path(path).name}")

    def _run_import(self):
        p = Path(self.filepath_edit.text())
        if not p.exists():
            QMessageBox.warning(self, "Fil saknas", "Filen hittades inte.")
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        QApplication.processEvents()
        try:
            def prog_fn(i, total, sheet):
                self.progress.setRange(0, total)
                self.progress.setValue(i)
                self.import_status_label.setText(f"Importerar {sheet} ({i}/{total})...")
                QApplication.processEvents()

            headers, rows, sheet_info = self._import_engine.import_file(p, progress_cb=prog_fn)
            self._imported_headers = headers
            self._imported_rows = rows
            self._sheet_info = sheet_info

            self._preview_model.set_data(headers, rows[:500])
            self.count_label.setText(f"{len(rows)} rader importerade, visar max 500")
            self.import_status_label.setText(f"Import klar: {Path(p).name} – {len(rows)} rader, {len(headers)} kolumner")
            self._log_cb(f"Import klar: {len(rows)} rader", "success")

            try:
                self._on_headers_imported(headers)
                self.headers_imported.emit(headers)
            except Exception:
                pass
        except Exception as exc:
            _log.exception("Import misslyckades")
            QMessageBox.critical(self, "Importfel", str(exc))
            self.import_status_label.setText(f"Fel: {exc}")
        finally:
            self.progress.setVisible(False)

    def _clear_import(self):
        self.filepath_edit.clear()
        self.import_button.setEnabled(False)
        self._preview_model.set_data([], [])
        self.count_label.setText("0 rader")
        self.import_status_label.setText("Ingen fil importerad.")
        self._imported_headers = []
        self._imported_rows = []
        self._sheet_info = []

    # ── Fordonsdata-mappning ──
    def _open_vehicle_mapping_dialog(self) -> None:
        """Öppnar dialog för manuell kolumnmappning av fordonsdata."""
        # 1. Försök via plugin API (om du lagt till open_vehicle_import_mapping_dialog)
        plugin = None
        get_plugin = getattr(self._app, "get_plugin_safe", None)
        if callable(get_plugin):
            try:
                plugin = get_plugin("data_mapping")
            except Exception:
                plugin = None
        if plugin and hasattr(plugin, "open_vehicle_import_mapping_dialog"):
            try:
                success = plugin.open_vehicle_import_mapping_dialog(self)
                if success:
                    self._log_cb("Fordonsdata-mappning uppdaterad", "success")
                return
            except Exception as exc:
                _log.exception("plugin.open_vehicle_import_mapping_dialog failed")
        
        # 2. Fallback: öppna MappingDialog direkt mot ColumnMappingService
        try:
            from .column_mapping_service import get_column_mapping_service
            svc = get_column_mapping_service()
            if svc is None:
                raise RuntimeError("ColumnMappingService saknas")
            dlg = MappingDialog(self, svc, self._imported_headers)
            if dlg.exec():
                data = dlg.get_data()
                if svc.set_mapping(data["source"], data["target"], data.get("description", ""), auto_detected=False, confidence=1.0, auto_save=True):
                    self._log_cb(f"Mappning sparad: {data['source']} → {data['target']}", "success")
                    QMessageBox.information(self, "Sparat", f"Mappning sparad:\n{data['source']} → {data['target']}")
        except Exception as exc:
            _log.exception("MappingDialog failed")
            QMessageBox.warning(self, "Plugin saknas", f"Kunde inte öppna mappningsdialog:\n{exc}")


# ═══════════════════════════════════════════════════════════════════
# MappingTab
# ═══════════════════════════════════════════════════════════════════

class MappingTab(QWidget):
    def __init__(self, parent: QWidget, app: Any, log_callback: Callable[[str, str], None]):
        super().__init__(parent)
        self._app = app
        self._log_cb = log_callback
        self.setObjectName("MappingTab")

        self._mapping_mgr = ColumnMappingManager(log_callback=log_callback)
        self._model = MappingTableModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)

        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Sök + knappar
        top = QHBoxLayout()
        top.addWidget(QLabel("Sök:"))
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("MappingSearchEdit")
        self.search_edit.textChanged.connect(lambda t: self._proxy.setFilterFixedString(t))
        top.addWidget(self.search_edit, 1)

        btn_add = QPushButton("Lägg till")
        btn_add.setObjectName("SuccessButton")
        _set_bold(btn_add)
        btn_add.clicked.connect(self._add_mapping)
        top.addWidget(btn_add)

        btn_edit = QPushButton("Redigera")
        btn_edit.setObjectName("PrimaryButton")
        _set_bold(btn_edit)
        btn_edit.clicked.connect(self._edit_mapping)
        top.addWidget(btn_edit)

        btn_del = QPushButton("Ta bort")
        btn_del.setObjectName("DangerButton")
        _set_bold(btn_del)
        btn_del.clicked.connect(self._delete_mapping)
        top.addWidget(btn_del)

        btn_refresh = QPushButton("Uppdatera")
        btn_refresh.setObjectName("SecondaryButton")
        btn_refresh.clicked.connect(self.refresh)
        top.addWidget(btn_refresh)

        layout.addLayout(top)

        # Tabell
        self.table = QTableView()
        self.table.setObjectName("MappingTable")
        self.table.setModel(self._proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(lambda _: self._edit_mapping())
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.count_label = QLabel("0 mappningar")
        self.count_label.setObjectName("CountLabel")
        layout.addWidget(self.count_label)

    def refresh(self):
        entries = self._mapping_mgr.get_entries()
        self._model.set_entries(entries)
        self.count_label.setText(f"{len(entries)} mappningar")

    def _selected_entry(self):
        idx = self.table.currentIndex()
        if not idx.isValid():
            return None
        src_idx = self._proxy.mapToSource(idx)
        return self._model.get_entry(src_idx.row())

    def _add_mapping(self):
        svc = self._mapping_mgr.service
        dlg = MappingDialog(self, svc, [])
        if dlg.exec():
            d = dlg.get_data()
            if self._mapping_mgr.set_mapping(d["source"], d["target"], d["description"]):
                self.refresh()

    def _edit_mapping(self):
        e = self._selected_entry()
        if not e:
            QMessageBox.information(self, "Redigera", "Välj en mappning först.")
            return
        svc = self._mapping_mgr.service
        dlg = MappingDialog(self, svc, [], existing_data={
            "source": e.source, "target": e.target, "description": e.description
        })
        if dlg.exec():
            d = dlg.get_data()
            if self._mapping_mgr.set_mapping(d["source"], d["target"], d["description"]):
                self.refresh()

    def _delete_mapping(self):
        e = self._selected_entry()
        if not e:
            return
        if QMessageBox.question(self, "Ta bort", f"Ta bort mappning '{e.source}' ?") == QMessageBox.StandardButton.Yes:
            if self._mapping_mgr.remove_mapping(e.source):
                self.refresh()


# ═══════════════════════════════════════════════════════════════════
# GenerateFilePage – huvudwidget med 3 flikar
# ═══════════════════════════════════════════════════════════════════

class GenerateFilePage(QWidget):
    def __init__(self, plugin: Any, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._plugin = plugin
        self._app = getattr(plugin, "app", None)
        self.setObjectName("GenerateFilePage")

        def _log_cb(msg: str, level: str = "info"):
            try:
                _log.info("[%s] %s", level, msg)
            except Exception:
                pass

        self._log_cb = _log_cb

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Dependency indicator
        if self._app:
            dep = DependencyIndicator(self._app, self)
            dep.setObjectName("DependencyIndicator")
            layout.addWidget(dep)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setObjectName("DataMappingTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)

        # Import-tab
        def _on_headers_imported(headers: List[str]):
            try:
                mgr = ColumnMappingManager(log_callback=self._log_cb)
                mgr.auto_populate(headers)
                if hasattr(self, "_mapping_tab"):
                    self._mapping_tab.refresh()
            except Exception:
                pass

        self._import_tab = ImportTab(self, self._app, self._log_cb, _on_headers_imported)
        self.tabs.addTab(self._import_tab, "📂 Import")

        # Mapping-tab
        self._mapping_tab = MappingTab(self, self._app, self._log_cb)
        self.tabs.addTab(self._mapping_tab, "🔗 Mappning")

        # Generera-tab (enkel placeholder – koppla till ts_file_generator i prod)
        gen_page = QWidget()
        gen_page.setObjectName("GenerateTab")
        gen_layout = QVBoxLayout(gen_page)
        title = QLabel("Generera TS-fil")
        title.setObjectName("PageTitle")
        _set_bold(title)
        gen_layout.addWidget(title)
        info = QLabel("Matchning och TS-generering körs via data_mapping plugin API.\nAnvänd Import → Mappning, sedan Generera via TS File Generator plugin.")
        info.setWordWrap(True)
        info.setObjectName("StatusLabel")
        gen_layout.addWidget(info)
        gen_layout.addStretch(1)
        self.tabs.addTab(gen_page, "📤 Generera")

        layout.addWidget(self.tabs, 1)

        # Logg
        log_group = QGroupBox("Logg")
        log_group.setObjectName("LogGroup")
        log_lay = QVBoxLayout(log_group)
        self.log_box = QPlainTextEdit()
        self.log_box.setObjectName("LogBox")
        self.log_box.setReadOnly(True)
        self.log_box.setFont(_mono_font())
        self.log_box.setMaximumBlockCount(500)
        log_lay.addWidget(self.log_box)
        layout.addWidget(log_group)

    def refresh(self):
        if hasattr(self, "_mapping_tab"):
            self._mapping_tab.refresh()

    def cleanup(self):
        pass


# Aliases för plugin loader
DataMappingWidget = GenerateFilePage
Widget = GenerateFilePage