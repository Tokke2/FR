# -*- coding: utf-8 -*-
# plugins/main_gui/vehicle_registry_page.py
"""
Vehicle Registry GUI - PySide6 komponenter för fordonshantering.
VERSION 5.5.1 - Manuell inmatning per år, kopiering mellan år,
textfilsgenerering och Excel-import med mappningsdialog.
UPPDELNING (Session 10, spec v1.4 Sektion A):
  Konstanter, Styles/STYLES, hjälpfunktioner, dataclasses, enums,
  protokoll och dialogerna (ColumnMappingDialog, ConflictResolutionDialog,
  GenerateTextFileDialog + _write_vehicle_text_file) ligger i:
    plugins/main_gui/vehicle_registry_helpers.py  (v1.0.0, 1849 rader —
    avvikelse från 1200-radersgränsen, beslutad av användaren)
  Denna fil innehåller: VehicleForm, YearTab, VehicleDataPage.
  __all__ re-exporterar alla publika namn (inkl. från hjälpfilen) så att
  befintliga importer (t.ex. main_gui/plugin.py) fungerar oförändrade.
Komponenter:
    - VehicleForm: Formulär för enskilt fordon
    - YearTab: Flik för fordon per år
    - VehicleDataPage: Huvudsida med sök, tabs, låsning, textfilsgenerering
      och Excel-import med mappningsdialog
    - (Dialoger finns i vehicle_registry_helpers.py)
FÖRÄNDRINGAR v5.5.0 (Session 10 — spec v1.4):
  - Uppdelning: flyttat till vehicle_registry_helpers.py v1.0.0
    (konstanter, Styles, hjälpare, dataclasses, enums, protokoll,
    ColumnMappingDialog, ConflictResolutionDialog,
    GenerateTextFileDialog + _write_vehicle_text_file).
    Ingen logikändring i kvarvarande klasser.
  - Excel-importknappen ÅTERAKTIVERAD (v5.4.0 dolde den): "📥 Importera Excel"
    i verktygsraden (spec v1.4, Sektion Q — FORDONSIMPORT UI).
  - KRAV 40/31: rubrikerna samlas från RAD 1 i ALLA blad (unika, i ordning)
    och visas i mappningsdialogen — tidigare endast första användbara bladet.
    Rubrikerna från varje blad sparas tillsammans med ett fingerprint så att
    samma filtyp kan återanvända mappningen.
  - KRAV 41/P14: fingerprint byggs över ALLA blads rubriker (ordning, md5 —
    konsistent med excel_importer v1.2.0 build_fingerprint). Mappningen
    sparas via vehicle_registry v4.6.0 → json/mappings/ (Sektion Z).
  - Filfilter fixat: "*.xlsx *.xls *.xlsm" (var "*.xls*" — felaktigt glob).
  - Hela filen omskriven ren (markdown-artefakter borttagna:
    [url]-länkar, **-markeringar, &gt;/&lt;/&amp; osv.).
FÖRÄNDRINGAR v5.4.0:
  - Excel-importknappen är dold tills vidare (funktionen kan återaktiveras
    i framtiden — ÅTERAKTIVERAD i v5.5.0).
  - NY: Kopiera fordon till ett annat år via YearTab.
  - NY: Generera textfil där användaren manuellt väljer vilka rader som ska ingå.
  - All fordonsdata matas in manuellt per årsflik.
FÖRÄNDRINGAR v5.3.0:
  - NY: ColumnMappingDialog vid Excel-import ("COMNAME = ?"-flödet)
  - NY: Fingerprint-baserad återanvändning av sparad mappning
  - NY: PIN-skydd vid ändring av sparad mappning
  - NY: ConflictResolutionDialog för dublett-VIN3
  - FIX: extract_vin3_from_full() använder nu tecken 2-4 (slice [1:4])
  - import_from_excel() använder preview -> konflikter -> import
FÖRÄNDRINGAR v5.2.0:
  - import_from_excel() anropar vehicle_registry.import_from_excel()
    DIREKT (ej via sap_import)
  - Stöder VINCODE som VIN-prefix (3-8 tecken)
  - Visar detaljerat resultat (nya/uppdaterade/blad/fel)
FÖRÄNDRINGAR v5.1.0:
  - logger -> _log (spec-konvention)
  - NY: "📥 Importera Excel" knapp i VehicleDataPage toolbar
  - Dynamisk copyright
FÖRÄNDRINGAR v5.5.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2026 ..." i
    docstringen BORTTAGEN — copyright genereras dynamiskt via
    module-level get_copyright_string() (samma mönster som
    vehicle_registry_helpers.py och övriga granskade moduler).
  - Övrig logik OFÖRÄNDRAD (VehicleForm, YearTab, VehicleDataPage,
    Excel-import med mappningsdialog, kopiering mellan år,
    textfilsgenerering, sök, låsning).
"""
from __future__ import annotations
import copy
import logging
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Final, List,
    Optional, Set, Tuple,
)
from PySide6.QtCore import QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import (
    QDoubleValidator, QIntValidator, QKeySequence,
    QRegularExpressionValidator, QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QProgressDialog,
    QPushButton, QScrollArea, QSplitter, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)
# Hjälpmodul (spec v1.4 — uppdelning av denna fil)
from .vehicle_registry_helpers import (
    ColumnMappingDialog,
    ConflictResolutionDialog,
    DEFAULT_VEHICLE_DATA,
    DROPDOWNS,
    FIELD_GROUPS,
    FieldInfo,
    FieldType,
    GenerateTextFileDialog,
    INTERNAL_TO_TS_FIELD_CANDIDATES,
    LockState,
    SearchResult,
    Styles,
    STYLES,
    TARGET_FIELD_LABELS,
    TIMER_CONFIG,
    TimerConfig,
    VALIDATION,
    VehicleDict,
    ValidationRule,
    _build_ts_field_lookup,
    _normalize_header,
    extract_vin3_from_full,
    get_plugin_safe,
    get_ts_schema_safe,
    validate_vin3,
)
if TYPE_CHECKING:
    from plugins.vehicle_registry.plugin import VehicleDataStorage

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER

# ══════════════════════════════════════════════════════════════════════════════
_log: logging.Logger = logging.getLogger("vehicle_registry_page")


# ══════════════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT (dynamisk — BUGG #5-fix v5.5.1)
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "5.5.1"
AUTHOR: str = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"

# ══════════════════════════════════════════════════════════════════════════════
# VEHICLE FORM

# ══════════════════════════════════════════════════════════════════════════════

class VehicleForm(QWidget):
    """Formulär för enskilt fordon."""
    data_modified = Signal()

    def __init__(
        self,
        data: Optional[Dict[str, Any]] = None,
        parent: Optional[QWidget] = None,
        app: Any = None,
    ) -> None:
        super().__init__(parent)
        self._loading = False
        self._inputs: Dict[str, QWidget] = {}
        self._app = app
        self._schema_45: Optional[Any] = None
        self._schema_loaded = False
        self._setup_ui()
        self.load_data(data or {})
        self._apply_ts_constraints_if_available()

    # ── Schema handling ──

    def _get_schema_45(self) -> Optional[Any]:
        if self._schema_loaded:
            return self._schema_45
        self._schema_loaded = True
        self._schema_45 = get_ts_schema_safe(self._app, "45")
        return self._schema_45

    def invalidate_schema_cache(self) -> None:
        self._schema_loaded = False
        self._schema_45 = None
        self._apply_ts_constraints_if_available()

    def _apply_ts_constraints_if_available(self) -> None:
        schema = self._get_schema_45()
        if not schema:
            return
        lookup = _build_ts_field_lookup(schema)
        if not lookup:
            return
        for internal_key, candidates in INTERNAL_TO_TS_FIELD_CANDIDATES.items():
            widget = self._inputs.get(internal_key)
            if not isinstance(widget, QLineEdit):
                continue
            field_spec = self._find_field_spec(candidates, lookup)
            if field_spec is None:
                continue
            self._apply_field_constraints(widget, field_spec)

    def _find_field_spec(
        self, candidates: List[str], lookup: Dict[str, Any]
    ) -> Optional[Any]:
        for c in candidates:
            spec = lookup.get(c.upper())
            if spec is not None:
                return spec
        return None

    def _apply_field_constraints(
        self, widget: QLineEdit, field_spec: Any
    ) -> None:
        try:
            length = int(getattr(field_spec, "length", 0) or 0)
            required = bool(getattr(field_spec, "required", False))
            ftype = str(getattr(field_spec, "field_type", "") or "")
            name = str(getattr(field_spec, "name", ""))
            if length > 0:
                widget.setMaxLength(length)
            parts = [f"TS/PT45: {name}"]
            if length:
                parts.append(f"Längd: {length}")
            if ftype:
                parts.append(f"Typ: {ftype}")
            parts.append("Obligatorisk" if required else "Valfri")
            widget.setToolTip(" | ".join(parts))
        except Exception as e:
            _log.debug("Failed to apply constraints: %s", e)

    # ── UI Setup ──

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        scroll.setWidget(container)
        form_layout = QVBoxLayout(container)
        form_layout.setSpacing(15)
        for group_name, fields in FIELD_GROUPS.items():
            group = self._create_group(group_name, fields)
            form_layout.addWidget(group)
        form_layout.addStretch()
        layout.addWidget(scroll)

    def _create_group(
        self, title: str, fields: List[Tuple[str, str, str]]
    ) -> QGroupBox:
        group = QGroupBox(title)
        group.setStyleSheet(Styles.GROUP_BOX)
        form = QFormLayout(group)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        form.setSpacing(8)
        for key, label, placeholder in fields:
            widget = self._create_field(key, placeholder)
            form.addRow(f"{label}:", widget)
            self._inputs[key] = widget
        return group

    def _create_field(self, key: str, placeholder: str) -> QWidget:
        rule = VALIDATION.get(key, {"type": "text"})
        if key == "vin_kod":
            return self._create_vin_field(placeholder)
        if rule.get("type") == "dropdown" or key in DROPDOWNS:
            return self._create_dropdown_field(key)
        return self._create_input_field(key, placeholder, rule)

    def _create_vin_field(self, placeholder: str) -> QWidget:
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(5)
        inp = QLineEdit()
        inp.setPlaceholderText(placeholder)
        inp.setMaxLength(3)
        inp.setFixedWidth(60)
        inp.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"^[A-Za-z0-9]{0,3}$")
            )
        )
        inp.textEdited.connect(lambda t: inp.setText(t.upper()))
        inp.textChanged.connect(self._on_modified)
        btn = QPushButton("← Från VIN")
        btn.setFixedWidth(90)
        btn.setStyleSheet(Styles.BTN_PRIMARY)
        btn.clicked.connect(lambda: self._extract_vin3(inp))
        h.addWidget(inp)
        h.addWidget(btn)
        h.addStretch()
        self._inputs["vin_kod"] = inp
        return container

    def _create_dropdown_field(self, key: str) -> QComboBox:
        combo = QComboBox()
        combo.addItems(DROPDOWNS.get(key, []))
        combo.currentIndexChanged.connect(self._on_modified)
        return combo

    def _create_input_field(
        self, key: str, placeholder: str, rule: ValidationRule
    ) -> QLineEdit:
        inp = QLineEdit()
        inp.setPlaceholderText(placeholder)
        ft = rule.get("type", "text")
        if ft == "int":
            inp.setValidator(
                QIntValidator(rule.get("min", 0), rule.get("max", 999999))
            )
            inp.setAlignment(Qt.AlignmentFlag.AlignRight)
        elif ft == "float":
            v = QDoubleValidator(
                float(rule.get("min", 0)),
                float(rule.get("max", 999999)), 1,
            )
            v.setNotation(QDoubleValidator.Notation.StandardNotation)
            inp.setValidator(v)
            inp.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            ml = rule.get("max", 0)
            if ml and ml > 0:
                inp.setMaxLength(ml)
        inp.textEdited.connect(self._on_modified)
        return inp

    # ── Actions ──

    def _extract_vin3(self, target: QLineEdit) -> None:
        vin, ok = QInputDialog.getText(
            self, "Extrahera VIN-kod",
            "Ange fullständigt VIN (17 tecken):",
        )
        if not ok or not vin:
            return
        vin3 = extract_vin3_from_full(vin)
        if vin3:
            target.setText(vin3)
            self._on_modified()
        else:
            QMessageBox.critical(
                self, "Ogiltigt VIN",
                f"Kunde inte extrahera VIN-kod från: '{vin}'\n\n"
                f"VIN måste vara minst 4 tecken (A-Z, 0-9, ej I/O/Q).",
            )

    def _on_modified(self) -> None:
        if not self._loading:
            self.data_modified.emit()

    # ── Public API ──

    def get_data(self) -> Dict[str, str]:
        data: Dict[str, str] = {}
        for key, widget in self._inputs.items():
            if isinstance(widget, QLineEdit):
                data[key] = widget.text().strip()
            elif isinstance(widget, QComboBox):
                data[key] = widget.currentText().strip()
        return data

    def load_data(self, data: Dict[str, Any]) -> None:
        self._loading = True
        try:
            for key, value in data.items():
                if key.startswith("_"):
                    continue
                widget = self._inputs.get(key)
                if widget is None:
                    continue
                val = str(value) if value is not None else ""
                if isinstance(widget, QLineEdit):
                    widget.setText(val)
                elif isinstance(widget, QComboBox):
                    idx = widget.findText(val)
                    widget.setCurrentIndex(max(0, idx))
        finally:
            self._loading = False

    def validate(self) -> List[str]:
        errors: List[str] = []
        errors.extend(self._validate_standard())
        errors.extend(self._validate_ts_schema())
        return errors

    def _validate_standard(self) -> List[str]:
        errors: List[str] = []
        for key, rule in VALIDATION.items():
            widget = self._inputs.get(key)
            if not widget:
                continue
            value = self._get_widget_value(widget)
            if rule.get("required") and not value:
                errors.append(f"{key} är obligatoriskt")
                continue
            if not value:
                continue
            if rule.get("type") == "vin3" and not validate_vin3(value):
                errors.append(
                    f"{key} måste vara 3 tecken (A-Z, 0-9, ej I/O/Q)"
                )
            if rule.get("type") == "text":
                ml = rule.get("max")
                if ml and len(value) > ml:
                    errors.append(f"{key} är för långt ({len(value)}>{ml})")
        return errors

    def _validate_ts_schema(self) -> List[str]:
        errors: List[str] = []
        schema = self._get_schema_45()
        if not schema:
            return errors
        lookup = _build_ts_field_lookup(schema)
        if not lookup:
            return errors
        for internal_key, candidates in INTERNAL_TO_TS_FIELD_CANDIDATES.items():
            widget = self._inputs.get(internal_key)
            if not isinstance(widget, QLineEdit):
                continue
            value = widget.text().strip()
            field_spec = self._find_field_spec(candidates, lookup)
            if field_spec is None:
                continue
            if not value:
                if bool(getattr(field_spec, "required", False)):
                    errors.append(
                        f"{internal_key} saknas (obligatoriskt enligt TS-spec)"
                    )
                continue
            try:
                ml = int(getattr(field_spec, "length", 0) or 0)
                if ml and len(value) > ml:
                    errors.append(
                        f"{internal_key} för långt för TS ({len(value)}>{ml})"
                    )
            except (ValueError, TypeError):
                pass
        return errors

    def _get_widget_value(self, widget: QWidget) -> str:
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        elif isinstance(widget, QComboBox):
            return widget.currentText().strip()
        return ""

    def enable_editing(self, enabled: bool) -> None:
        for widget in self._inputs.values():
            widget.setEnabled(enabled)

    def clear(self) -> None:
        self._loading = True
        try:
            for widget in self._inputs.values():
                if isinstance(widget, QLineEdit):
                    widget.clear()
                elif isinstance(widget, QComboBox):
                    widget.setCurrentIndex(0)
        finally:
            self._loading = False

# ══════════════════════════════════════════════════════════════════════════════
# YEAR TAB

# ══════════════════════════════════════════════════════════════════════════════

class YearTab(QWidget):
    """Flik för fordon i ett specifikt år."""
    year_modified = Signal(int)
    copy_vehicle_requested = Signal(int, dict)

    def __init__(
        self,
        year: int,
        storage: "VehicleDataStorage",
        on_modified: Callable[[int], None],
        parent: Optional[QWidget] = None,
        app: Any = None,
    ) -> None:
        super().__init__(parent)
        self.year = year
        self._storage = storage
        self._on_modified_callback = on_modified
        self._app = app
        self._loading = False
        self._editing = True
        self._vehicles: List[Dict[str, Any]] = []
        self._forms: Dict[str, VehicleForm] = {}
        self._setup_ui()
        self._load_from_disk()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.addLayout(self._create_toolbar())
        layout.addWidget(self._create_splitter())

    def _create_toolbar(self) -> QHBoxLayout:
        toolbar = QHBoxLayout()
        self._btn_add = QToolButton()
        self._btn_add.setText("+ Lägg till fordon")
        self._btn_add.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        self._btn_add.setStyleSheet(Styles.BTN_SUCCESS)
        menu = QMenu()
        menu.addAction("🆕 Skapa tomt fordon", self._add_empty)
        menu.addAction("📋 Kopiera markerat", self._duplicate_selected)
        menu.addAction(
            "📅 Kopiera till annat år...", self._copy_to_other_year
        )
        self._btn_add.setMenu(menu)
        self._btn_add.clicked.connect(self._add_empty)
        self._lbl_count = QLabel()
        self._lbl_count.setStyleSheet("color: #888;")
        toolbar.addWidget(self._btn_add)
        toolbar.addSpacing(10)
        toolbar.addWidget(self._lbl_count)
        toolbar.addStretch()
        return toolbar

    def _create_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._create_list_widget())
        splitter.addWidget(self._create_form_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        return splitter

    def _create_list_widget(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QLabel(f"<b>Fordon {self.year}</b>")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(Styles.HEADER_LABEL)
        layout.addWidget(header)
        self._list = QListWidget()
        self._list.setMinimumWidth(250)
        self._list.setMaximumWidth(350)
        self._list.setStyleSheet(Styles.LIST_WIDGET)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._list.customContextMenuRequested.connect(
            self._show_context_menu
        )
        layout.addWidget(self._list)
        return container

    def _create_form_panel(self) -> QWidget:
        self._form_panel = QWidget()
        self._form_layout = QVBoxLayout(self._form_panel)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        self._empty_label = QLabel(
            "Inga fordon. Använd '+ Lägg till fordon' för att skapa."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(Styles.EMPTY_LABEL)
        self._form_layout.addWidget(self._empty_label)
        return self._form_panel

    def _load_from_disk(self) -> None:
        self._vehicles = self._storage.load_year(self.year)
        self._populate_list()

    def _populate_list(self) -> None:
        self._loading = True
        self._list.clear()
        self._forms.clear()
        self._clear_form_panel()
        for i, vehicle in enumerate(self._vehicles):
            self._add_list_item(i, vehicle)
        self._lbl_count.setText(f"{len(self._vehicles)} fordon")
        if self._vehicles:
            self._list.setCurrentRow(0)
            self._empty_label.hide()
        else:
            self._form_layout.addWidget(self._empty_label)
            self._empty_label.show()
        self._loading = False

    def _add_list_item(
        self, index: int, vehicle: Dict[str, Any]
    ) -> None:
        vin = vehicle.get("vin_kod", "???").upper()
        brand = vehicle.get("fabrikat", "Okänd")
        model = vehicle.get(
            "handelsbeteckning", vehicle.get("typ", "")
        )
        item = QListWidgetItem(f"[{vin}] {brand} – {model}")
        item.setData(Qt.ItemDataRole.UserRole, index)
        self._list.addItem(item)
        form = VehicleForm(vehicle, app=self._app)
        form.data_modified.connect(
            lambda: self._on_modified_callback(self.year)
        )
        form.enable_editing(self._editing)
        self._forms[str(index)] = form

    def _clear_form_panel(self) -> None:
        while self._form_layout.count():
            child = self._form_layout.takeAt(0)
            if child.widget():
                child.widget().setParent(None)

    def _on_selection_changed(
        self,
        current: Optional[QListWidgetItem],
        previous: Optional[QListWidgetItem],
    ) -> None:
        if self._loading or not current:
            return
        idx = current.data(Qt.ItemDataRole.UserRole)
        form = self._forms.get(str(idx))
        if not form:
            return
        self._clear_form_panel()
        self._form_layout.addWidget(form)

    def _show_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        menu = QMenu(self)
        if item:
            idx = item.data(Qt.ItemDataRole.UserRole)
            if self._editing:
                menu.addAction("📋 Kopiera", self._duplicate_selected)
                menu.addAction(
                    "📅 Kopiera till annat år...", self._copy_to_other_year
                )
                menu.addSeparator()
                menu.addAction("🗑️ Ta bort", lambda: self._delete_at(idx))
            else:
                menu.addAction("🔒 Låst — lås upp för att redigera")
        else:
            if self._editing:
                menu.addAction("🆕 Skapa nytt fordon", self._add_empty)
            else:
                menu.addAction("🔒 Låst — lås upp för att redigera")
        menu.exec(self._list.mapToGlobal(pos))

    def _add_empty(self) -> None:
        self._add_vehicle(dict(DEFAULT_VEHICLE_DATA))

    def _add_vehicle(self, data: Dict[str, Any]) -> None:
        self._vehicles.append(data)
        self._populate_list()
        self._list.setCurrentRow(len(self._vehicles) - 1)
        self._on_modified_callback(self.year)

    def _duplicate_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Inget valt",
                "Välj ett fordon att kopiera först.",
            )
            return
        data = copy.deepcopy(self._vehicles[row])
        data["vin_kod"] = ""
        self._add_vehicle(data)

    def _copy_to_other_year(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Inget valt",
                "Välj ett fordon att kopiera först.",
            )
            return
        data = copy.deepcopy(self._vehicles[row])
        data["vin_kod"] = ""
        self.copy_vehicle_requested.emit(self.year, data)

    def _delete_at(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._vehicles):
            return
        vin = self._vehicles[idx].get("vin_kod", "???")
        reply = QMessageBox.question(
            self,
            "Bekräfta borttagning",
            f"Ta bort fordon [{vin}]?\n\n"
            f"Denna åtgärd kan inte ångras.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self._vehicles[idx]
            self._populate_list()
            self._on_modified_callback(self.year)

    def add_vehicle_copy(self, data: Dict[str, Any]) -> None:
        """Lägg till en kopia av ett fordon i denna flik."""
        self._add_vehicle(copy.deepcopy(data))

    def select_row(self, index: int) -> None:
        """Markera rad i listan (publik — används av sökning)."""
        if 0 <= index < self._list.count():
            self._list.setCurrentRow(index)

    def enable_editing(self, enabled: bool) -> None:
        self._editing = enabled
        self._btn_add.setEnabled(enabled)
        for form in self._forms.values():
            form.enable_editing(enabled)

    def get_all_data(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for i in range(len(self._vehicles)):
            form = self._forms.get(str(i))
            if form:
                data = form.get_data()
                if data.get("vin_kod"):
                    result.append(data)
        return result

    def validate_all(self) -> List[str]:
        errors: List[str] = []
        for i in range(len(self._vehicles)):
            form = self._forms.get(str(i))
            if form:
                fe = form.validate()
                if fe:
                    vin = form.get_data().get("vin_kod", f"#{i + 1}")
                    errors.append(
                        f"Fordon [{vin}]: {', '.join(fe)}"
                    )
        return errors

    def find_by_vin3(self, vin3: str) -> Optional[int]:
        v = vin3.strip().upper()
        for i, vehicle in enumerate(self._vehicles):
            if vehicle.get("vin_kod", "").strip().upper() == v:
                return i
        return None

    def refresh(self) -> None:
        self._load_from_disk()

    def on_ts_spec_changed(self) -> None:
        for form in self._forms.values():
            form.invalidate_schema_cache()

# ══════════════════════════════════════════════════════════════════════════════
# VEHICLE DATA PAGE

# ══════════════════════════════════════════════════════════════════════════════

class VehicleDataPage(QWidget):
    """
    Huvudsida för fordonsdata.
    v5.5.0: Manuell inmatning per årsflik, kopiering mellan år,
    generering av textfil via manuellt radurval OCH Excel-import
    med mappningsdialog (rad 1 = titlar i alla blad, KRAV 40-42).
    """

    def __init__(
        self,
        storage: "VehicleDataStorage",
        pin_getter: Callable[[], str],
        initial_years: Optional[List[int]] = None,
        parent: Optional[QWidget] = None,
        app: Any = None,
    ) -> None:
        super().__init__(parent)
        self._storage = storage
        self._pin_getter = pin_getter
        self._app = app
        self._lock_state = LockState.LOCKED
        self._tabs: Dict[int, YearTab] = {}
        self._modified: Set[int] = set()
        self._autosave_timer = self._create_timer(
            TIMER_CONFIG.autosave_ms, self._do_autosave,
        )
        self._autolock_timer = self._create_timer(
            TIMER_CONFIG.autolock_ms, self._lock,
        )
        self._setup_ui()
        self._setup_shortcuts()
        for year in initial_years or [datetime.now().year]:
            self._create_tab(year)
        self._update_lock_state()

    def _create_timer(
        self, interval_ms: int, callback: Callable[[], None],
    ) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(interval_ms)
        timer.timeout.connect(callback)
        return timer

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        title = QLabel("🚗 Fordonsdata")
        title.setObjectName("PageTitle")
        title.setStyleSheet(Styles.PAGE_TITLE)
        layout.addWidget(title)
        layout.addLayout(self._create_toolbar())
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(Styles.TAB_WIDGET)
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.tabCloseRequested.connect(self._close_tab)
        layout.addWidget(self._tab_widget)

    def _create_toolbar(self) -> QHBoxLayout:
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self._lock_label = QLabel("🔒 Låst")
        self._lock_label.setStyleSheet(Styles.LOCK_LOCKED)
        toolbar.addWidget(self._lock_label)
        toolbar.addSpacing(20)
        toolbar.addWidget(QLabel("Sök:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "VIN (17 tecken) eller VIN3 (3 tecken)"
        )
        self._search.setFixedWidth(300)
        self._search.setStyleSheet(Styles.SEARCH_INPUT)
        self._search.returnPressed.connect(self._do_search)
        toolbar.addWidget(self._search)
        btn_search = QPushButton("🔍 Sök")
        btn_search.setStyleSheet(Styles.BTN_PRIMARY)
        btn_search.clicked.connect(self._do_search)
        toolbar.addWidget(btn_search)
        toolbar.addStretch()
        # ── Excel-import (v5.5.0: återaktiverad, spec v1.4 Sektion Q) ──
        self._btn_import_excel = QPushButton("📥 Importera Excel")
        self._btn_import_excel.setStyleSheet(Styles.BTN_INFO)
        self._btn_import_excel.setToolTip(
            "Importera modelldata från Excel.\n"
            "Rad 1 i alla blad = titlar → mappningsdialog → json/mappings/"
        )
        self._btn_import_excel.clicked.connect(self._import_from_excel)
        toolbar.addWidget(self._btn_import_excel)
        # ── Textfilsgenerering ──
        self._btn_generate = QPushButton("📄 Generera textfil")
        self._btn_generate.setStyleSheet(Styles.BTN_INFO)
        self._btn_generate.setToolTip(
            "Generera textfil från valda fordonsrader.\n"
            "Användaren väljer manuellt vilka rader som ska ingå."
        )
        self._btn_generate.clicked.connect(self._generate_text_file)
        toolbar.addWidget(self._btn_generate)
        self._btn_unlock = QPushButton("🔓 Lås upp")
        self._btn_unlock.setStyleSheet(Styles.BTN_SUCCESS)
        self._btn_unlock.clicked.connect(self._unlock)
        toolbar.addWidget(self._btn_unlock)
        self._btn_lock = QPushButton("🔒 Lås")
        self._btn_lock.setStyleSheet(Styles.BTN_DANGER)
        self._btn_lock.clicked.connect(self._lock)
        toolbar.addWidget(self._btn_lock)
        self._btn_add_year = QPushButton("📅 + År")
        self._btn_add_year.setStyleSheet(Styles.BTN_PRIMARY)
        self._btn_add_year.clicked.connect(self._add_year_dialog)
        toolbar.addWidget(self._btn_add_year)
        self._btn_save = QPushButton("💾 Spara")
        self._btn_save.setStyleSheet(Styles.BTN_WARNING)
        self._btn_save.clicked.connect(self._save_all)
        toolbar.addWidget(self._btn_save)
        return toolbar

    def _setup_shortcuts(self) -> None:
        shortcuts = [
            ("Ctrl+S", self._save_all),
            ("Ctrl+F", lambda: self._search.setFocus()),
            ("Ctrl+N", self._add_year_dialog),
            ("Ctrl+G", self._generate_text_file),
        ]
        for key_seq, callback in shortcuts:
            QShortcut(QKeySequence(key_seq), self).activated.connect(callback)

    # ──────────────────────────────────────────────────────────────────
    # EXCEL-IMPORT (v5.5.0 — KRAV 40-42, spec v1.4)

    # ──────────────────────────────────────────────────────────────────

    def _import_from_excel(self) -> None:
        """
        Importera modelldata från Excel via vehicle_registry.
        Flöde (spec v1.4, Sektion Q — 5-stegsflödet):
          1. Välj fil
          2. Detektera rubriker från RAD 1 i ALLA blad (KRAV 40/31)
          3. Ladda sparad mappning (fingerprint, KRAV 35/41)
          4. Visa mappningsdialog (användaren kan ändra/spara/PIN-skydda)
          5. Preview-import → konfliktdetektering (KRAV 37)
          6. Vid konflikter: visa konfliktdialog
          7. Kör riktig import med valda åtgärder
          8. Refresha tabs och visa resultat (KRAV 39)
        """
        vr_plugin = get_plugin_safe(self._app, "vehicle_registry")
        if not vr_plugin or not hasattr(vr_plugin, "import_from_excel"):
            QMessageBox.warning(
                self,
                "Plugin saknas",
                "Vehicle Registry plugin saknar import_from_excel().\n\n"
                "Kontrollera att vehicle_registry v4.6.0+ är installerad.",
            )
            return
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Välj Excel-fil med modelldata",
            str(Path.cwd()),
            "Excel-filer (*.xlsx *.xls *.xlsm);;Alla filer (*.*)",
        )
        if not filepath:
            return
        _log.info("Startar Excel-import från: %s", filepath)
        progress = QProgressDialog(
            "Läser Excel-fil...", "Avbryt", 0, 0, self,
        )
        progress.setWindowTitle("Excel-import")
        progress.setMinimumDuration(500)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        def progress_cb(msg: str) -> None:
            progress.setLabelText(msg)
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
        try:
            # 1. Detektera rubriker (rad 1 i ALLA blad — KRAV 40/31)
            header_info = vr_plugin.detect_excel_headers(filepath)
            usable = [
                info for info in header_info.values()
                if not info.get("skipped") and info.get("headers")
            ]
            if not usable:
                raise ValueError(
                    "Kunde inte hitta några rubriker i filen."
                )
            headers: List[str] = []
            seen: Set[str] = set()
            for info in usable:
                for header in info.get("headers", []):
                    norm = _normalize_header(header)
                    if norm and norm not in seen:
                        seen.add(norm)
                        headers.append(header)
            if not headers:
                raise ValueError(
                    "Kunde inte hitta några användbara rubriker i filen."
                )
            # 2. Fingerprint över ALLA blads rubriker (P14) + sparad mappning
            fingerprint = vr_plugin.build_mapping_fingerprint(headers)
            saved_mapping = (
                vr_plugin.load_column_mapping_for_fingerprint(fingerprint)
                or {}
            )
            suggestion = vr_plugin.suggest_column_mapping(headers) or {}
            initial_mapping = saved_mapping if saved_mapping else suggestion
            progress.close()
            # 3. Mappningsdialog
            mapping_dialog = ColumnMappingDialog(
                headers=headers,
                initial_mapping=initial_mapping,
                target_labels=dict(TARGET_FIELD_LABELS),
                parent=self,
            )
            if mapping_dialog.exec() != QDialog.DialogCode.Accepted:
                _log.info("Användaren avbröt mappningsdialogen")
                return
            column_mapping = mapping_dialog.get_mapping()
            if not column_mapping:
                QMessageBox.warning(
                    self, "Ingen mappning",
                    "Inga kolumner är mappade. Importen avbryts.",
                )
                return
            # Spara mappning om användaren valt det (KRAV 34/41/36)
            if mapping_dialog.save_mapping_checked():
                pin = mapping_dialog.get_pin()
                protected = mapping_dialog.protect_checked()
                try:
                    vr_plugin.set_column_mapping(
                        column_mapping,
                        fingerprint=fingerprint,
                        pin=pin,
                        protected=protected,
                    )
                except PermissionError:
                    existing_pin, ok = QInputDialog.getText(
                        self,
                        "Lösenord krävs",
                        "Ange befintlig PIN för att ändra mappningen:",
                        QLineEdit.EchoMode.Password,
                    )
                    if (
                        ok
                        and existing_pin
                        and vr_plugin.verify_mapping_pin(fingerprint, existing_pin)
                    ):
                        vr_plugin.set_column_mapping(
                            column_mapping,
                            fingerprint=fingerprint,
                            pin=existing_pin,
                            protected=protected,
                        )
                    else:
                        QMessageBox.warning(
                            self,
                            "Sparat avbrutet",
                            "Felaktig PIN. Mappningen sparades inte, "
                            "men importen fortsätter.",
                        )
                except Exception as exc:
                    QMessageBox.warning(
                        self,
                        "Kunde inte spara mappning",
                        f"{exc}\n\nImporten fortsätter ändå.",
                    )
            progress.setLabelText("Analyserar importen...")
            progress.show()
            # 4. Preview för konflikter
            preview = vr_plugin.preview_excel_import(
                filepath=filepath,
                column_mapping=column_mapping,
                progress_callback=progress_cb,
            )
            errors = preview.get("errors", [])
            if errors and not preview.get("fingerprint"):
                raise ValueError("; ".join(errors))
            conflicts = preview.get("conflicts", [])
            conflict_resolutions: Dict[str, str] = {}
            if conflicts:
                progress.close()
                conflict_dialog = ConflictResolutionDialog(
                    conflicts=conflicts,
                    parent=self,
                )
                if conflict_dialog.exec() != QDialog.DialogCode.Accepted:
                    _log.info("Användaren avbröt konfliktdialogen")
                    return
                conflict_resolutions = conflict_dialog.get_resolutions()
                progress.setLabelText("Importerar...")
                progress.show()
            # 5. Riktig import
            result = vr_plugin.import_from_excel(
                filepath=filepath,
                column_mapping=column_mapping,
                on_conflict="replace",
                conflict_resolutions=conflict_resolutions,
                progress_callback=progress_cb,
                save_mapping=False,
            )
            progress.close()
            # 6. Refresha tabs
            for year in result.get("years", []):
                try:
                    year_int = int(year)
                    if year_int in self._tabs:
                        self._tabs[year_int].refresh()
                    else:
                        self._create_tab(year_int)
                except (ValueError, TypeError):
                    pass
            for tab in self._tabs.values():
                tab.refresh()
            # 7. Visa resultat
            self._show_import_result(result)
        except Exception as exc:
            progress.close()
            _log.exception("Excel-import misslyckades: %s", exc)
            QMessageBox.critical(
                self, "Importfel",
                f"Ett oväntat fel uppstod:\n\n{exc}",
            )

    def _show_import_result(self, result: Dict[str, Any]) -> None:
        """Visa sammanfattningsdialog efter import."""
        imported = result.get("imported", 0)
        updated = result.get("updated", 0)
        skipped = result.get("skipped", 0)
        errors = result.get("errors", [])
        years = result.get("years", [])
        sheets_processed = result.get("sheets_processed", [])
        sheets_skipped = result.get("sheets_skipped", [])
        row_errors = result.get("row_errors", [])
        msg_lines: List[str] = []
        if result.get("success"):
            msg_lines.append("✅ Import klar!\n")
        else:
            msg_lines.append("⚠️ Import delvis misslyckad\n")
        if imported > 0:
            msg_lines.append(f"Nya fordon: {imported}")
        if updated > 0:
            msg_lines.append(f"Uppdaterade: {updated}")
        if skipped > 0:
            msg_lines.append(f"Överhoppade: {skipped}")
        if years:
            msg_lines.append(
                f"År: {', '.join(str(y) for y in sorted(years))}"
            )
        if sheets_processed:
            msg_lines.append("\nBearbetade blad:")
            for s in sheets_processed[:10]:
                msg_lines.append(f"  ✅ {s}")
        if sheets_skipped:
            msg_lines.append("\nHoppade blad:")
            for s in sheets_skipped[:5]:
                msg_lines.append(f"  ⏭️ {s}")
        if row_errors:
            msg_lines.append(f"\nRadfel ({len(row_errors)} st):")
            for err in row_errors[:5]:
                msg_lines.append(
                    f"  • Blad {err.get('sheet')} rad {err.get('row')}: "
                    f"{err.get('reason')}"
                )
            if len(row_errors) > 5:
                msg_lines.append(f"  ... och {len(row_errors) - 5} fler")
        if errors:
            msg_lines.append(f"\n⚠️ {len(errors)} fel:")
            for err in errors[:5]:
                msg_lines.append(f"  • {err}")
            if len(errors) > 5:
                msg_lines.append(f"  ... och {len(errors) - 5} fler")
        if result.get("success"):
            QMessageBox.information(
                self, "Import klar", "\n".join(msg_lines),
            )
        else:
            QMessageBox.warning(
                self, "Import delvis misslyckad",
                "\n".join(msg_lines),
            )
        _log.info(
            "Modellimport klar: %d nya, %d uppdaterade, "
            "%d överhoppade",
            imported, updated, skipped,
        )

    # ──────────────────────────────────────────────────────────────────
    # TAB MANAGEMENT

    # ──────────────────────────────────────────────────────────────────

    def _create_tab(self, year: int) -> None:
        if year in self._tabs:
            self._tab_widget.setCurrentWidget(self._tabs[year])
            return
        tab = YearTab(
            year, self._storage, self._on_year_modified,
            app=self._app,
        )
        tab.enable_editing(self._is_unlocked)
        tab.copy_vehicle_requested.connect(self._on_copy_vehicle_requested)
        self._tabs[year] = tab
        idx = self._tab_widget.addTab(tab, str(year))
        self._tab_widget.setCurrentIndex(idx)

    def _close_tab(self, index: int) -> None:
        widget = self._tab_widget.widget(index)
        for year, tab in list(self._tabs.items()):
            if tab == widget:
                if not self._handle_unsaved_changes(year, tab):
                    return
                del self._tabs[year]
                break
        self._tab_widget.removeTab(index)

    def _handle_unsaved_changes(
        self, year: int, tab: YearTab
    ) -> bool:
        if year not in self._modified:
            return True
        reply = QMessageBox.question(
            self,
            "Osparade ändringar",
            f"År {year} har osparade ändringar.\n\n"
            f"Vill du spara innan du stänger?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.Save:
            self._storage.save_year(year, tab.get_all_data())
            self._modified.discard(year)
        return True

    def _on_copy_vehicle_requested(
        self, source_year: int, vehicle_data: Dict[str, Any]
    ) -> None:
        """Hantera begäran om att kopiera ett fordon till ett annat år."""
        target_year, ok = QInputDialog.getInt(
            self,
            "Kopiera till annat år",
            "Välj målår för kopian:",
            source_year,
            1900,
            2200,
        )
        if not ok:
            return
        if target_year == source_year:
            tab = self._tabs.get(source_year)
            if tab:
                tab.add_vehicle_copy(copy.deepcopy(vehicle_data))
            return
        if target_year not in self._tabs:
            self._create_tab(target_year)
        target_tab = self._tabs.get(target_year)
        if target_tab:
            target_tab.add_vehicle_copy(copy.deepcopy(vehicle_data))
            self._tab_widget.setCurrentWidget(target_tab)

    def _generate_text_file(self) -> None:
        """Öppna dialog för att generera textfil från valda rader."""
        dialog = GenerateTextFileDialog(self._storage, parent=self)
        dialog.exec()

    def _add_year_dialog(self) -> None:
        year, ok = QInputDialog.getInt(
            self, "Lägg till år", "År:",
            datetime.now().year, 1980, 2100,
        )
        if ok:
            self._create_tab(year)
            self._reset_autolock()

    # ──────────────────────────────────────────────────────────────────
    # LOCK/UNLOCK

    # ──────────────────────────────────────────────────────────────────
    @property

    def _is_unlocked(self) -> bool:
        return self._lock_state == LockState.UNLOCKED

    def _unlock(self) -> None:
        pin = self._pin_getter().strip()
        if not pin:
            QMessageBox.warning(
                self, "PIN saknas",
                "Ingen PIN har konfigurerats.\n\n"
                "Kontakta administratör.",
            )
            return
        entered, ok = QInputDialog.getText(
            self, "Lås upp", "Ange PIN:",
            QLineEdit.EchoMode.Password,
        )
        if ok and entered.strip() == pin:
            self._lock_state = LockState.UNLOCKED
            self._update_lock_state()
            self._autolock_timer.start()
        elif ok:
            QMessageBox.critical(
                self, "Fel PIN",
                "Felaktig PIN. Försök igen.",
            )

    def _lock(self) -> None:
        if self._modified:
            self._do_autosave()
        self._lock_state = LockState.LOCKED
        self._update_lock_state()
        self._autolock_timer.stop()

    def _update_lock_state(self) -> None:
        unlocked = self._is_unlocked
        for tab in self._tabs.values():
            tab.enable_editing(unlocked)
        self._btn_save.setEnabled(unlocked)
        self._btn_unlock.setEnabled(not unlocked)
        self._btn_unlock.setVisible(not unlocked)
        self._btn_lock.setEnabled(unlocked)
        self._btn_lock.setVisible(unlocked)
        self._btn_add_year.setEnabled(unlocked)
        if unlocked:
            self._lock_label.setText("🔓 Upplåst")
            self._lock_label.setStyleSheet(Styles.LOCK_UNLOCKED)
        else:
            self._lock_label.setText("🔒 Låst")
            self._lock_label.setStyleSheet(Styles.LOCK_LOCKED)

    def _reset_autolock(self) -> None:
        if self._is_unlocked:
            self._autolock_timer.start()

    # ──────────────────────────────────────────────────────────────────
    # SAVE/LOAD

    # ──────────────────────────────────────────────────────────────────

    def _on_year_modified(self, year: int) -> None:
        if not self._is_unlocked:
            return
        self._modified.add(year)
        self._autosave_timer.start()
        self._reset_autolock()
        self._update_tab_title(year, modified=True)

    def _update_tab_title(
        self, year: int, modified: bool = False
    ) -> None:
        tab = self._tabs.get(year)
        if not tab:
            return
        for i in range(self._tab_widget.count()):
            if self._tab_widget.widget(i) == tab:
                title = f"{year} *" if modified else str(year)
                self._tab_widget.setTabText(i, title)
                break

    def _do_autosave(self) -> None:
        for year in list(self._modified):
            tab = self._tabs.get(year)
            if tab:
                try:
                    self._storage.save_year(
                        year, tab.get_all_data()
                    )
                    self._update_tab_title(year, modified=False)
                except Exception as e:
                    _log.error(
                        "Autosave failed for %d: %s", year, e
                    )
        self._modified.clear()

    def _save_all(self) -> None:
        if not self._is_unlocked:
            return
        # Validera först
        for year, tab in self._tabs.items():
            errors = tab.validate_all()
            if errors:
                QMessageBox.critical(
                    self,
                    f"Valideringsfel år {year}",
                    "Följande fel hittades:\n\n"
                    + "\n".join(errors[:10]),
                )
                return
        # Spara
        saved: List[int] = []
        for year, tab in self._tabs.items():
            self._storage.save_year(year, tab.get_all_data())
            saved.append(year)
            self._update_tab_title(year, modified=False)
        QMessageBox.information(
            self,
            "Sparat",
            f"Data sparad för år: "
            f"{', '.join(map(str, sorted(saved)))}",
        )
        self._modified.clear()
        self._reset_autolock()

    # ──────────────────────────────────────────────────────────────────
    # SEARCH

    # ──────────────────────────────────────────────────────────────────

    def _do_search(self) -> None:
        text = self._search.text().strip()
        if not text:
            return
        result = self._search_vehicle(text)
        if result.found:
            self._navigate_to_result(result)
        else:
            QMessageBox.information(
                self,
                "Ej hittat",
                f"VIN3 '{result.vin3}' hittades inte i något år.\n\n"
                f"Skapa ett nytt fordon eller kontrollera söktermen.",
            )

    def _search_vehicle(self, text: str) -> SearchResult:
        if len(text) == 3 and validate_vin3(text):
            vin3 = text.upper()
        else:
            vin3 = extract_vin3_from_full(text)
        if not vin3:
            QMessageBox.warning(
                self,
                "Ogiltigt sökord",
                "Ange giltigt VIN (17 tecken) eller VIN3 (3 tecken).\n\n"
                "VIN får inte innehålla I, O eller Q.",
            )
            return SearchResult(found=False)
        # Sök i öppna tabs
        for year, tab in self._tabs.items():
            idx = tab.find_by_vin3(vin3)
            if idx is not None:
                return SearchResult(
                    found=True, year=year, index=idx, vin3=vin3
                )
        # Sök på disk
        years = self._storage.find_years_by_vin3(vin3)
        if years:
            for y in years:
                if y not in self._tabs:
                    self._create_tab(y)
            tab = self._tabs[years[0]]
            idx = tab.find_by_vin3(vin3)
            if idx is not None:
                return SearchResult(
                    found=True, year=years[0], index=idx, vin3=vin3
                )
        return SearchResult(found=False, vin3=vin3)

    def _navigate_to_result(self, result: SearchResult) -> None:
        if not result.found or result.year is None:
            return
        tab = self._tabs.get(result.year)
        if tab and result.index is not None:
            self._tab_widget.setCurrentWidget(tab)
            tab.select_row(result.index)
            self._search.clear()

    # ──────────────────────────────────────────────────────────────────
    # PUBLIC API

    # ──────────────────────────────────────────────────────────────────

    def refresh_all(self) -> None:
        """Ladda om alla tabs från disk."""
        for tab in self._tabs.values():
            tab.refresh()

    def refresh(self) -> None:
        """Alias för refresh_all()."""
        self.refresh_all()

    def get_modified_years(self) -> List[int]:
        """Hämta lista med modifierade år."""
        return list(self._modified)

    def on_ts_spec_changed(self) -> None:
        """Uppdatera formulär när TS-spec ändrats."""
        for tab in self._tabs.values():
            tab.on_ts_spec_changed()

    def on_schema_changed(self) -> None:
        """Alias för on_ts_spec_changed()."""
        self.on_ts_spec_changed()

# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS

# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Klasser (egna)
    "VehicleForm",
    "YearTab",
    "VehicleDataPage",
    # Klasser (re-export från vehicle_registry_helpers)
    "ColumnMappingDialog",
    "ConflictResolutionDialog",
    "GenerateTextFileDialog",
    # Dataclasses (re-export)
    "TimerConfig",
    "FieldInfo",
    "SearchResult",
    # Enums (re-export)
    "FieldType",
    "LockState",
    # Konstanter (re-export)
    "FIELD_GROUPS",
    "DROPDOWNS",
    "VALIDATION",
    "STYLES",
    "DEFAULT_VEHICLE_DATA",
    "TARGET_FIELD_LABELS",
    # Funktioner (re-export)
    "validate_vin3",
    "extract_vin3_from_full",
    "get_plugin_safe",
    "get_ts_schema_safe",
    # Metadata (v5.5.1)
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]
