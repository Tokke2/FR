# -*- coding: utf-8 -*-
# Fil: plugins/ts_excel_importer/widget.py
"""
Import-widget för TS Excel Importer v1.0.0.

Wizard-style interface:
    1. Välj fil
    2. Välj ark/posttyper
    3. Preview och mappning
    4. Import och resultat

FÖRÄNDRINGAR v1.0.0 (granskad — spec v1.6 förbättringsregeln):
    - VERSION/AUTHOR tillagda (module-level, saknades helt).
    - FIX (låst regel): ALLA hårdkodade stylesheet-färger BORTTAGNA
      (#1e3a5f, #888, #4caf50, #f44336, #1565c0, #ff9800, font-size)
      — styling sker via setObjectName + ThemeEngine (samma mönster
      som ts_file_generator/ts_schema_manager-widgetarna). Färger i
      QBrush för status (grön/röd) ersatta med emoji + text.
    - FIX (konvention): self.plugin.logger.error(f"...") ->
      module-level _log med lazy %s (aldrig f-string i logganrop).
    - FIX (robusthet): from .parser import ... utan try/except —
      modulen kunde inte importeras alls om parser.py saknas. Nu
      kraschsäker fallback med placeholder-klasser (samma mönster
      som ts_file_generator-widgetens latin1_utils-fallback).
    - setObjectName() på alla komponenter för fullständig
      ThemeEngine-styling (låst regel).
    - setWordWrap(True) på labels + tabeller i Python-kod; inga
      word-wrap i stylesheet (låst regel).
    - ScrollPerPixel på tabeller (DPI/skärm-anpassning).
    - Fil-huvud normaliserat: coding-rad före Fil-rad
      (spec v1.11, KRAV 58).
    - Importordning normaliserad (QtCore, QtWidgets, QtGui).
    - Övrig logik OFÖRÄNDRAD (wizard-flöde, versionshantering,
      preview, import, resultat).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox,
    QFileDialog, QComboBox, QGroupBox,
    QAbstractItemView, QCheckBox, QTextEdit, QFrame,
    QListWidget, QListWidgetItem, QTabWidget,
    QProgressDialog, QStackedWidget,
)

# Kraschsäker import av lokala modeller (fallback om parser.py
# inte levererats än — samma mönster som ts_file_generator)
try:
    from .parser import SheetInfo, ParsedSpec
except ImportError:
    class SheetInfo:  # type: ignore[no-redef]
        """Fallback när parser.py saknas."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.name: str = ""
            self.is_valid: bool = False
            self.row_count: int = 0
            self.detected_post_type: Optional[str] = None
            self.detected_post_name: str = ""
            self.validation_errors: List[str] = []

    class ParsedSpec:  # type: ignore[no-redef]
        """Fallback när parser.py saknas."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.post_type: Optional[str] = None
            self.post_name: str = ""
            self.fields: List[object] = []
            self.parse_warnings: List[str] = []
            self.total_length: int = 0
            self.column_mapping: Dict[str, str] = {}

if TYPE_CHECKING:
    from .plugin import Plugin

# ═══════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT
# ═══════════════════════════════════════════════════════════════════════

VERSION: str = "1.0.0"
AUTHOR: str = "Rickard Längkvist"


# ═══════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ═══════════════════════════════════════════════════════════════════════

def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback om logging ej konfigurerat.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("ts_excel_importer.widget")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log = _get_logger()


# ═══════════════════════════════════════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _set_bold(widget: QWidget) -> None:
    """Sätt fet stil på widget (kraschsäkert)."""
    try:
        font = widget.font()
        font.setBold(True)
        widget.setFont(font)
    except Exception:
        _log.exception("Kunde inte sätta fet stil.")


# ═══════════════════════════════════════════════════════════════════════
# KONSTANTER
# ═══════════════════════════════════════════════════════════════════════

KNOWN_POST_TYPES = {
    "28": {"name": "Identitetspost"},
    "45": {"name": "Registreringspost"},
    "99": {"name": "Slutpost"},
}


# ═══════════════════════════════════════════════════════════════════════
# WIDGET
# ═══════════════════════════════════════════════════════════════════════

class TSExcelImportWidget(QWidget):
    """Widget för Excel-import med wizard-style interface."""

    def __init__(self, parent: QWidget, plugin: "Plugin"):
        super().__init__(parent)
        self.plugin = plugin
        self.setObjectName("TSExcelImportWidget")

        self._current_file: Optional[Path] = None
        self._sheets: List[SheetInfo] = []
        self._parsed_specs: Dict[str, ParsedSpec] = {}

        self._setup_ui()
        self._load_versions()

    def _setup_ui(self) -> None:
        """Bygg UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = self._create_header()
        layout.addLayout(header)

        # Versions-info
        self.version_frame = self._create_version_frame()
        layout.addWidget(self.version_frame)

        # Main content (wizard pages)
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("WizardStack")

        self.sheet_page = self._create_sheet_page()
        self.content_stack.addWidget(self.sheet_page)

        self.preview_page = self._create_preview_page()
        self.content_stack.addWidget(self.preview_page)

        self.result_page = self._create_result_page()
        self.content_stack.addWidget(self.result_page)

        layout.addWidget(self.content_stack, 1)

    def _create_header(self) -> QHBoxLayout:
        """Skapa header."""
        layout = QHBoxLayout()

        title = QLabel("📥 Importera TS-specifikationer")
        title.setObjectName("PageTitle")
        _set_bold(title)
        layout.addWidget(title)

        layout.addStretch()

        self.btn_select = QPushButton("📂 Välj Excel-fil...")
        self.btn_select.setObjectName("PrimaryButton")
        self.btn_select.clicked.connect(self._on_select_file)
        layout.addWidget(self.btn_select)

        return layout

    def _create_version_frame(self) -> QFrame:
        """Skapa versions-info panel."""
        frame = QFrame()
        frame.setObjectName("VersionFrame")
        frame.setFrameStyle(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)

        version_caption = QLabel("📋 Aktiv version:")
        version_caption.setObjectName("StatusLabel")
        layout.addWidget(version_caption)

        self.version_combo = QComboBox()
        self.version_combo.setObjectName("VersionCombo")
        self.version_combo.setMinimumWidth(150)
        self.version_combo.currentTextChanged.connect(self._on_version_changed)
        layout.addWidget(self.version_combo)

        self.version_info = QLabel()
        self.version_info.setObjectName("StatusLabel")
        layout.addWidget(self.version_info)

        layout.addStretch()

        return frame

    def _create_sheet_page(self) -> QWidget:
        """Skapa sida för arkval."""
        page = QWidget()
        layout = QVBoxLayout(page)

        self.file_label = QLabel("Välj en Excel-fil med TS-specifikationer")
        self.file_label.setObjectName("StatusLabel")
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)

        sheet_caption = QLabel("📋 Hittade ark:")
        sheet_caption.setObjectName("SectionTitle")
        _set_bold(sheet_caption)
        layout.addWidget(sheet_caption)

        self.sheet_table = QTableWidget()
        self.sheet_table.setObjectName("SheetTable")
        self.sheet_table.setColumnCount(5)
        self.sheet_table.setHorizontalHeaderLabels([
            "✓", "Ark", "Posttyp", "Rader", "Status"
        ])
        self.sheet_table.setAlternatingRowColors(True)
        self.sheet_table.setWordWrap(True)
        self.sheet_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.sheet_table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.sheet_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.sheet_table.verticalHeader().setVisible(False)

        header = self.sheet_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.sheet_table)

        # Version input
        version_layout = QHBoxLayout()
        version_caption = QLabel("Version:")
        version_caption.setObjectName("StatusLabel")
        version_layout.addWidget(version_caption)

        self.version_input = QLineEdit()
        self.version_input.setObjectName("VersionInput")
        self.version_input.setPlaceholderText("T.ex. 13.2 eller 2024.03")
        self.version_input.setMaximumWidth(200)
        version_layout.addWidget(self.version_input)

        btn_auto_version = QPushButton("Auto")
        btn_auto_version.setObjectName("SecondaryButton")
        btn_auto_version.clicked.connect(self._on_auto_version)
        version_layout.addWidget(btn_auto_version)

        version_layout.addStretch()
        layout.addLayout(version_layout)

        # Buttons
        btn_layout = QHBoxLayout()

        btn_select_all = QPushButton("☑️ Alla")
        btn_select_all.setObjectName("SecondaryButton")
        btn_select_all.clicked.connect(self._on_select_all)
        btn_layout.addWidget(btn_select_all)

        btn_select_none = QPushButton("☐ Ingen")
        btn_select_none.setObjectName("SecondaryButton")
        btn_select_none.clicked.connect(self._on_select_none)
        btn_layout.addWidget(btn_select_none)

        btn_layout.addStretch()

        self.btn_preview = QPushButton("👁️ Förhandsgranska →")
        self.btn_preview.setObjectName("PrimaryButton")
        self.btn_preview.setEnabled(False)
        self.btn_preview.clicked.connect(self._on_preview)
        btn_layout.addWidget(self.btn_preview)

        layout.addLayout(btn_layout)

        return page

    def _create_preview_page(self) -> QWidget:
        """Skapa förhandsgranskningssida."""
        page = QWidget()
        layout = QVBoxLayout(page)

        self.preview_tabs = QTabWidget()
        self.preview_tabs.setObjectName("PreviewTabs")
        layout.addWidget(self.preview_tabs, 1)

        btn_layout = QHBoxLayout()

        btn_back = QPushButton("← Tillbaka")
        btn_back.setObjectName("SecondaryButton")
        btn_back.clicked.connect(lambda: self.content_stack.setCurrentIndex(0))
        btn_layout.addWidget(btn_back)

        btn_layout.addStretch()

        self.btn_import = QPushButton("📥 Importera")
        self.btn_import.setObjectName("SuccessButton")
        _set_bold(self.btn_import)
        self.btn_import.clicked.connect(self._on_import)
        btn_layout.addWidget(self.btn_import)

        layout.addLayout(btn_layout)

        return page

    def _create_result_page(self) -> QWidget:
        """Skapa resultatsida."""
        page = QWidget()
        layout = QVBoxLayout(page)

        self.result_label = QLabel()
        self.result_label.setObjectName("ResultLabel")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        self.result_list = QListWidget()
        self.result_list.setObjectName("ResultList")
        layout.addWidget(self.result_list)

        btn_layout = QHBoxLayout()

        btn_new = QPushButton("📂 Importera ny fil")
        btn_new.setObjectName("SecondaryButton")
        btn_new.clicked.connect(self._on_select_file)
        btn_layout.addWidget(btn_new)

        btn_layout.addStretch()

        btn_done = QPushButton("✓ Klar")
        btn_done.setObjectName("PrimaryButton")
        btn_done.clicked.connect(lambda: self.content_stack.setCurrentIndex(0))
        btn_layout.addWidget(btn_done)

        layout.addLayout(btn_layout)

        return page

    # ─────────────────────────────────────────────────────────────
    # VERSIONER
    # ─────────────────────────────────────────────────────────────

    def _load_versions(self) -> None:
        """Ladda versioner till combo."""
        self.version_combo.blockSignals(True)
        self.version_combo.clear()

        schema_mgr = self.plugin.get_plugin_safe("ts_schema_manager")
        if schema_mgr:
            versions = schema_mgr.list_versions()
            active = schema_mgr.get_active_version()

            for v in versions:
                self.version_combo.addItem(v.version)

            if active:
                idx = self.version_combo.findText(active)
                if idx >= 0:
                    self.version_combo.setCurrentIndex(idx)

        self._update_version_info()
        self.version_combo.blockSignals(False)

    def _update_version_info(self) -> None:
        """Uppdatera versionsinformation."""
        version = self.version_combo.currentText()
        if not version:
            self.version_info.setText("Ingen version laddad")
            return

        schema_mgr = self.plugin.get_plugin_safe("ts_schema_manager")
        if schema_mgr:
            schemas = schema_mgr.get_all_schemas(version)
            types = ", ".join(sorted(schemas.keys()))
            self.version_info.setText(
                f"Posttyper: {types}" if types else "Inga posttyper"
            )

    def _on_version_changed(self, version: str) -> None:
        """Hantera versionsbyte."""
        if version:
            schema_mgr = self.plugin.get_plugin_safe("ts_schema_manager")
            if schema_mgr:
                try:
                    schema_mgr.set_active_version(version)
                    self._update_version_info()
                except Exception as e:
                    QMessageBox.warning(self, "Fel", str(e))

    # ─────────────────────────────────────────────────────────────
    # FILVAL / ARK
    # ─────────────────────────────────────────────────────────────

    def _on_select_file(self) -> None:
        """Välj Excel-fil."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Välj TS-specifikation (Excel)", "",
            "Excel-filer (*.xlsx *.xls);;Alla filer (*.*)"
        )

        if not filepath:
            return

        self._current_file = Path(filepath)
        self.file_label.setText(f"📄 {self._current_file.name}")
        self.file_label.setObjectName("FileInfoLabel")

        try:
            self._sheets = self.plugin.analyze_file(self._current_file)
            self._populate_sheet_table()
            self.btn_preview.setEnabled(True)
            self.content_stack.setCurrentIndex(0)
            self._on_auto_version()
        except Exception as e:
            QMessageBox.critical(self, "Fel", f"Kunde inte läsa fil:\n{e}")

    def _populate_sheet_table(self) -> None:
        """Fyll sheet-tabellen."""
        self.sheet_table.setRowCount(0)

        for sheet in self._sheets:
            row = self.sheet_table.rowCount()
            self.sheet_table.insertRow(row)

            cb = QCheckBox()
            cb.setObjectName("SheetCheck")
            cb.setChecked(sheet.is_valid)
            cb.setEnabled(sheet.is_valid)
            self.sheet_table.setCellWidget(row, 0, cb)

            self.sheet_table.setItem(row, 1, QTableWidgetItem(sheet.name))

            pt = sheet.detected_post_type or "?"
            pt_item = QTableWidgetItem(pt)
            if pt in KNOWN_POST_TYPES:
                pt_item.setToolTip(KNOWN_POST_TYPES[pt]["name"])
            self.sheet_table.setItem(row, 2, pt_item)

            self.sheet_table.setItem(row, 3, QTableWidgetItem(str(sheet.row_count)))

            if sheet.is_valid:
                status = "✅ OK"
            else:
                err = (
                    sheet.validation_errors[0]
                    if sheet.validation_errors
                    else "Ogiltig"
                )
                status = f"❌ {err}"

            status_item = QTableWidgetItem(status)
            status_item.setToolTip(status)
            self.sheet_table.setItem(row, 4, status_item)

    def _on_select_all(self) -> None:
        for row in range(self.sheet_table.rowCount()):
            cb = self.sheet_table.cellWidget(row, 0)
            if cb and cb.isEnabled():
                cb.setChecked(True)

    def _on_select_none(self) -> None:
        for row in range(self.sheet_table.rowCount()):
            cb = self.sheet_table.cellWidget(row, 0)
            if cb:
                cb.setChecked(False)

    def _on_auto_version(self) -> None:
        try:
            version = self.plugin.generate_next_version()
            self.version_input.setText(version)
        except Exception as e:
            _log.error("Kunde inte generera versionsnamn: %s", e)

    def _get_selected_sheets(self) -> List[SheetInfo]:
        selected = []
        for row in range(self.sheet_table.rowCount()):
            cb = self.sheet_table.cellWidget(row, 0)
            if cb and cb.isChecked():
                selected.append(self._sheets[row])
        return selected

    # ─────────────────────────────────────────────────────────────
    # PREVIEW
    # ─────────────────────────────────────────────────────────────

    def _on_preview(self) -> None:
        selected = self._get_selected_sheets()

        if not selected:
            QMessageBox.information(self, "Info", "Välj minst ett ark")
            return

        version = self.version_input.text().strip()
        if not version:
            QMessageBox.warning(self, "Varning", "Ange versionsnamn")
            return

        self.preview_tabs.clear()
        self._parsed_specs.clear()

        for sheet in selected:
            try:
                parsed = self.plugin.parse_sheet(
                    self._current_file, sheet.name,
                    post_type=sheet.detected_post_type,
                    post_name=sheet.detected_post_name,
                )
                self._parsed_specs[sheet.name] = parsed

                tab = self._create_preview_tab(parsed)
                title = f"PT{parsed.post_type}" if parsed.post_type else sheet.name
                self.preview_tabs.addTab(tab, title)
            except Exception as e:
                QMessageBox.warning(self, "Varning", f"Fel: {sheet.name}:\n{e}")

        if self._parsed_specs:
            self.content_stack.setCurrentIndex(1)

    def _create_preview_tab(self, parsed: ParsedSpec) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Info
        info = QFrame()
        info.setObjectName("InfoFrame")
        info.setFrameStyle(QFrame.Shape.StyledPanel)
        info_layout = QGridLayout(info)

        info_layout.addWidget(QLabel("<b>Posttyp:</b>"), 0, 0)
        info_layout.addWidget(QLabel(parsed.post_type or "-"), 0, 1)
        info_layout.addWidget(QLabel("<b>Namn:</b>"), 0, 2)
        info_layout.addWidget(QLabel(parsed.post_name), 0, 3)
        info_layout.addWidget(QLabel("<b>Fält:</b>"), 1, 0)
        info_layout.addWidget(QLabel(str(len(parsed.fields))), 1, 1)

        layout.addWidget(info)

        # Fält-tabell
        table = QTableWidget()
        table.setObjectName("FieldsTable")
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(
            ["Pos", "Längd", "Namn", "Typ", "O/V", "Beskrivning"]
        )
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        table.verticalHeader().setVisible(False)

        for f in parsed.fields:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(f.position)))
            table.setItem(row, 1, QTableWidgetItem(str(f.length)))
            table.setItem(row, 2, QTableWidgetItem(f.name))
            table.setItem(row, 3, QTableWidgetItem(f.field_type[:3].upper()))
            table.setItem(row, 4, QTableWidgetItem("O" if f.required else "V"))
            table.setItem(row, 5, QTableWidgetItem(f.description[:50]))

        layout.addWidget(table, 1)

        # Varningar
        if parsed.parse_warnings:
            warn_text = QTextEdit()
            warn_text.setObjectName("WarningText")
            warn_text.setReadOnly(True)
            warn_text.setMaximumHeight(60)
            warn_text.setPlainText("\n".join(parsed.parse_warnings[:5]))
            layout.addWidget(warn_text)

        return widget

    # ─────────────────────────────────────────────────────────────
    # IMPORT / RESULTAT
    # ─────────────────────────────────────────────────────────────

    def _on_import(self) -> None:
        if not self._parsed_specs:
            return

        version = self.version_input.text().strip()
        if not version:
            QMessageBox.warning(self, "Varning", "Ange versionsnamn")
            return

        sheets_config = [
            {
                "sheet_name": name,
                "post_type": parsed.post_type,
                "post_name": parsed.post_name,
                "total_length": parsed.total_length,
                "column_mapping": parsed.column_mapping,
            }
            for name, parsed in self._parsed_specs.items()
        ]

        progress = QProgressDialog(
            "Importerar...", "Avbryt", 0, len(sheets_config), self
        )
        progress.setObjectName("ImportProgress")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        def on_progress(current: int, total: int, msg: str) -> None:
            progress.setValue(current)
            progress.setLabelText(msg)

        try:
            result = self.plugin.import_file(
                self._current_file, sheets_config, version, on_progress
            )
            progress.close()
            self._load_versions()
            self._show_result(result)
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Fel", f"Import misslyckades:\n{e}")

    def _show_result(self, result: object) -> None:
        from .plugin import SyncAction

        if result.is_success:
            icon, title = "✅", "Import lyckades!"
        elif result.specs_failed > 0 and result.specs_imported > 0:
            icon, title = "⚠️", "Import delvis lyckad"
        else:
            icon, title = "❌", "Import misslyckades"

        self.result_label.setText(
            f"{icon} <b>{title}</b>\n"
            f"Version: <b>{result.version}</b>\n"
            f"• Nya: {result.specs_imported}\n"
            f"• Uppdaterade: {result.specs_updated}\n"
            f"• Misslyckade: {result.specs_failed}\n"
            f"Tid: {result.duration_ms / 1000:.1f}s"
        )

        self.result_list.clear()

        icon_map = {
            SyncAction.CREATED: "✅",
            SyncAction.UPDATED: "🔄",
            SyncAction.UNCHANGED: "➖",
            SyncAction.ERROR: "❌",
        }

        for sr in result.sync_results:
            text = f"{icon_map.get(sr.action, '?')} PT{sr.post_type}: {sr.action.value}"
            if sr.error:
                text += f" - {sr.error}"

            item = QListWidgetItem(text)
            item.setToolTip(text)
            self.result_list.addItem(item)

        self.content_stack.setCurrentIndex(2)


__all__ = ["TSExcelImportWidget"]
