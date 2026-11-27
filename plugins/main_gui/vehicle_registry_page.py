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
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QProgressDialog,
    QPushButton, QScrollArea, QSplitter, QTabBar, QTableWidget,
    QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)
from core import layout_memory, responsive_layout, skeleton, table_view
from core import theme as design
from core import vehicle_filters
from plugins.gui_helpers.page_header import PageHeader
from core.vehicle_year_layout import FIRST_YEAR, initial_years as vehicle_initial_years, is_archived_year
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
        self._original_data: Dict[str, Any] = {}
        self._edited_fields: Set[str] = set()
        self._vin_button: Optional[QPushButton] = None
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
            # VIN-kontrollen är en container; _create_vin_field har redan
            # registrerat själva QLineEdit. Ersätt inte den med containern.
            self._inputs.setdefault(key, widget)
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
        inp.textEdited.connect(lambda t: (inp.setText(t.upper()), self._on_modified("vin_kod")))
        btn = QPushButton("← Från VIN")
        btn.setFixedWidth(90)
        btn.setStyleSheet(Styles.BTN_PRIMARY)
        btn.clicked.connect(lambda: self._extract_vin3(inp))
        self._vin_button = btn
        h.addWidget(inp)
        h.addWidget(btn)
        h.addStretch()
        self._inputs["vin_kod"] = inp
        return container

    def _create_dropdown_field(self, key: str) -> QComboBox:
        combo = QComboBox()
        combo.addItems(DROPDOWNS.get(key, []))
        combo.currentIndexChanged.connect(lambda *_: self._on_modified(key))
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
        inp.textEdited.connect(lambda *_: self._on_modified(key))
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
            self._on_modified("vin_kod")
        else:
            QMessageBox.critical(
                self, "Ogiltigt VIN",
                f"Kunde inte extrahera VIN-kod från: '{vin}'\n\n"
                f"VIN måste vara minst 4 tecken (A-Z, 0-9, ej I/O/Q).",
            )

    def _on_modified(self, key: str) -> None:
        if not self._loading:
            self._edited_fields.add(key)
            self.data_modified.emit()

    # ── Public API ──

    def get_data(self) -> Dict[str, Any]:
        # Bevara även okända, dolda och oförändrade värden. En widget kan
        # förkorta ett äldre värde vid visning; den får inte skriva över det
        # förrän användaren faktiskt ändrat fältet.
        data: Dict[str, Any] = copy.deepcopy(self._original_data)
        for key, widget in self._inputs.items():
            if key not in self._edited_fields:
                continue
            if isinstance(widget, QLineEdit):
                data[key] = widget.text().strip()
            elif isinstance(widget, QComboBox):
                data[key] = widget.currentText().strip()
        return data

    def load_data(self, data: Dict[str, Any]) -> None:
        self._loading = True
        try:
            self._original_data = copy.deepcopy(data)
            self._edited_fields.clear()
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
                    # Visa ett befintligt värde även om det inte längre finns
                    # bland standardalternativen; det får inte gå förlorat.
                    if idx < 0 and val:
                        widget.addItem(val)
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
        if self._vin_button is not None:
            self._vin_button.setEnabled(enabled)

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

# Kolumnerna i en fordonsrad. Ordningen är den som visas första gången; den
# som drar i rubrikerna får sin egen ordning sparad per år (förslag 7).
VEHICLE_COLUMNS: tuple[str, ...] = (
    "VIN-kod", "Fabrikat", "Modell", "Godkännandenummer", "Färg",
    "Återförsäljare", "Status",
)


def _column_values(vehicle: Dict[str, Any]) -> Dict[str, str]:
    """Värdena som visas i tabellraden – aldrig påhittade."""
    missing = vehicle_filters.missing_fields(vehicle)
    return {
        "VIN-kod": vehicle_filters.vin(vehicle) or "—",
        "Fabrikat": str(vehicle.get("fabrikat") or "—"),
        "Modell": vehicle_filters.model(vehicle) or "—",
        "Godkännandenummer": vehicle_filters.approval(vehicle) or "—",
        "Färg": vehicle_filters.color(vehicle) or "—",
        "Återförsäljare": vehicle_filters.dealer(vehicle) or "—",
        "Status": "Klar" if not missing else "Saknar " + ", ".join(missing).lower(),
    }


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
        # Snabbfilter (förslag 9). Tom lista = alla rader visas.
        self._active_filters: List[str] = []
        self._table_ready = False
        self._setup_ui()
        # Platshållarrader innan första inläsningen: tabellen har samma höjd
        # hela vägen, så inget hoppar när årsfilen är klar (förslag 24).
        self._show_skeleton()
        self._load_from_disk()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.addLayout(self._create_toolbar())
        layout.addLayout(self._create_filter_bar())
        layout.addWidget(self._create_splitter(), 1)
        layout.addWidget(self._create_summary_bar())

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
        self._lbl_count.setObjectName("Caption")
        toolbar.addWidget(self._btn_add)
        toolbar.addSpacing(10)
        toolbar.addWidget(self._lbl_count)
        toolbar.addStretch()
        return toolbar

    def _create_filter_bar(self) -> QHBoxLayout:
        """Snabbfilterchip ovanför listan (förslag 9).

        Chipsen beskriver fel som redan går att se i data – de hittar aldrig på
        egna värden. Flera val kombineras med *och*.
        """
        bar = QHBoxLayout()
        bar.setSpacing(6)
        caption = QLabel("Visa:")
        caption.setObjectName("Muted")
        bar.addWidget(caption)
        self._filter_buttons: Dict[str, QToolButton] = {}
        for chip in vehicle_filters.QUICK_FILTERS:
            button = QToolButton()
            button.setText(chip.label)
            button.setCheckable(True)
            button.setToolTip(chip.description)
            button.setObjectName("FilterChip")
            design.set_accessible(button, chip.label, chip.description)
            button.toggled.connect(
                lambda checked, key=chip.key: self._toggle_filter(key, checked))
            self._filter_buttons[chip.key] = button
            bar.addWidget(button)
        self._btn_clear_filters = QToolButton()
        self._btn_clear_filters.setText("Visa alla")
        self._btn_clear_filters.setObjectName("FilterChip")
        design.set_accessible(self._btn_clear_filters, "Visa alla",
                              "Tar bort alla snabbfilter")
        self._btn_clear_filters.clicked.connect(self._clear_filters)
        bar.addWidget(self._btn_clear_filters)
        bar.addStretch()
        return bar

    def _create_summary_bar(self) -> QWidget:
        """Statusrad under listan med antal och vad som saknas (förslag 10)."""
        self._summary_label = QLabel("")
        self._summary_label.setObjectName("Caption")
        self._summary_label.setWordWrap(True)
        return self._summary_label

    def _toggle_filter(self, key: str, checked: bool) -> None:
        if checked and key not in self._active_filters:
            self._active_filters.append(key)
        elif not checked and key in self._active_filters:
            self._active_filters.remove(key)
        self._populate_list()

    def _clear_filters(self) -> None:
        self._active_filters.clear()
        for button in getattr(self, "_filter_buttons", {}).values():
            button.setChecked(False)
        self._populate_list()

    def _visible_vehicles(self) -> List[Dict[str, Any]]:
        """Rader som filtren släpper igenom, i årsfilens ordning."""
        if not self._active_filters:
            return list(self._vehicles)
        allowed = {id(row) for row in
                   vehicle_filters.apply_filters(self._vehicles, self._active_filters)}
        return [row for row in self._vehicles if id(row) in allowed]

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
        # Tabell i stället för en lista: VIN-koden är fryst så att den syns
        # även när formuläret tar plats (förslag 6). Radhöjden följer vald
        # densitet (förslag 8) och kolumnläget sparas per år (förslag 7).
        self._table = QTableWidget(0, len(VEHICLE_COLUMNS))
        self._table.setObjectName("VehicleTable")
        self._table.setHorizontalHeaderLabels(list(VEHICLE_COLUMNS))
        self._table.setMinimumWidth(320)
        self._table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        table_view.configure(self._table, density=self._row_mode(),
                             word_wrap=self._word_wrap(), freeze_first=True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        # Sorteringen slås på först när tabellen är fylld, annars sorteras
        # raderna om mitt under påfyllningen. Kolumnerna kan flyttas.
        self._table.setSortingEnabled(False)
        header.setSectionsMovable(True)
        header.sectionMoved.connect(self._on_column_moved)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().sectionResized.connect(
            self._on_column_resized)
        # Kolumnbredderna anpassas till innehållet när vyn ändrar storlek, så
        # att inget klipps och ingen vågrät rullning behövs (för skärmar i alla
        # storlekar). Användarens egen bredd vinner alltid över automaten.
        self._auto_columns = True
        self._table.installEventFilter(self)
        layout.addWidget(self._table, 1)
        self._table_ready = True
        return container

    # ── Tabell och profil (förslag 6–8) ─────────────────────────────────

    def _main_window(self) -> Any:
        """Huvudfönstret, om det går att nå – annars ``None``."""
        try:
            if self._app is not None and hasattr(self._app, "get_plugin"):
                return self._app.get_plugin("main_gui")
        except Exception:
            pass
        return None

    def _density(self) -> str:
        """Densitet från inställningarna, annars luftig."""
        main = self._main_window()
        value = getattr(main, "_density", None)
        return value if isinstance(value, str) else "comfortable"

    def _row_mode(self) -> str:
        """Radhöjd: kompakt, normal eller luftig (förslag 8)."""
        main = self._main_window()
        reader = getattr(main, "_row_mode", None)
        if callable(reader):
            try:
                return design.resolve_row_mode(reader())
            except Exception:
                pass
        return "compact" if self._density() == "compact" else "normal"

    def _word_wrap(self) -> bool:
        """Textbrytning i celler, så att långa värden syns hela."""
        main = self._main_window()
        reader = getattr(main, "_wrap_enabled", None)
        if callable(reader):
            try:
                return bool(reader())
            except Exception:
                pass
        return self._density() != "compact"

    def _profile_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _load_table_profile(self) -> None:
        """Lägg på sparad kolumnordning och bredd för året.

        Finns ingen sparad profil anpassas bredden automatiskt till fönstret.
        """
        try:
            profile = table_view.load(self._profile_root(), self._table, "fordon",
                                      list(VEHICLE_COLUMNS), self.year)
        except Exception:
            profile = {}
            _log.debug("Tabellprofilen kunde inte användas", exc_info=True)
        if profile.get("widths"):
            # Användaren har valt bredder – automaten ska inte röra dem.
            self._auto_columns = False
        else:
            self._auto_columns = True
            self._fit_columns_soon()

    def _save_table_profile(self) -> None:
        """Spara kolumnläget när användaren har ändrat det."""
        try:
            table_view.save(self._profile_root(), self._table, "fordon",
                            list(VEHICLE_COLUMNS), self.year,
                            density=self._density())
        except Exception:
            _log.debug("Tabellprofilen kunde inte sparas", exc_info=True)

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """Anpassa kolumnerna när tabellen byter storlek."""
        try:
            if watched is self._table and event.type() == event.Type.Resize:
                self._fit_columns_soon()
        except Exception:
            pass
        return super().eventFilter(watched, event)

    def _fit_columns_soon(self) -> None:
        """Vänta tills storleksändringen är klar innan kolumnerna räknas om."""
        timer = getattr(self, "_fit_timer", None)
        if timer is None:
            self._fit_timer = QTimer(self)
            self._fit_timer.setSingleShot(True)
            self._fit_timer.setInterval(120)
            self._fit_timer.timeout.connect(self._fit_columns)
            timer = self._fit_timer
        timer.start()

    def _fit_columns(self) -> None:
        """Fördela kolumnbredden så att rubriken och värdena syns."""
        if not getattr(self, "_auto_columns", True):
            return
        try:
            room = self._table.viewport().width()
            if room < 120:
                return
            longest: List[Any] = [None] * len(VEHICLE_COLUMNS)
            for row in range(self._table.rowCount()):
                for column in range(len(VEHICLE_COLUMNS)):
                    cell = self._table.item(row, column)
                    if cell is None:
                        continue
                    text = cell.text()
                    if longest[column] is None or len(text) > len(longest[column]):
                        longest[column] = text
            widths = responsive_layout.column_widths(list(VEHICLE_COLUMNS), longest, room)
            # Automatiken får inte sparas som användarens eget val.
            self._fitting = True
            try:
                for column, width in enumerate(widths[:len(VEHICLE_COLUMNS)]):
                    self._table.setColumnWidth(column, width)
            finally:
                self._fitting = False
        except Exception:
            _log.debug("Kolumnbredderna kunde inte anpassas", exc_info=True)

    def _on_column_resized(self, *_args) -> None:
        """Spara bredden en kort stund efter att användaren släppt kanten.

        Så snart användaren själv ändrar en bredd stängs automaten av för den
        fliken – annars skulle nästa storleksändring skriva över valet.
        """
        if getattr(self, "_auto_columns", False) and getattr(self, "_fitting", False):
            return
        self._auto_columns = False
        timer = getattr(self, "_profile_timer", None)
        if timer is None:
            self._profile_timer = QTimer(self)
            self._profile_timer.setSingleShot(True)
            self._profile_timer.setInterval(900)
            self._profile_timer.timeout.connect(self._save_table_profile)
            timer = self._profile_timer
        timer.start()

    def _on_column_moved(self, *_args) -> None:
        """Spara kolumnordningen när användaren flyttar en kolumn."""
        if getattr(self, "_loading", False):
            return
        # En flytt är användarens val: automaten får inte röra bredderna.
        self._auto_columns = False
        timer = getattr(self, "_profile_timer", None)
        if timer is None:
            # Skapa timern på samma sätt som vid breddändring och starta den.
            self._on_column_resized()
            timer = getattr(self, "_profile_timer", None)
        if timer is not None:
            timer.start()

    def _selected_row(self) -> int:
        """Index i årsfilen för markerad rad, eller -1."""
        rows = self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        if not rows:
            return -1
        try:
            return int(self._table.model().data(self._table.model().index(rows[0].row(), 0),
                                                Qt.ItemDataRole.UserRole))
        except Exception:
            return -1

    def _on_table_selection_changed(self) -> None:
        idx = self._selected_row()
        if idx < 0:
            return
        form = self._forms.get(str(idx))
        if not form:
            return
        self._clear_form_panel()
        self._form_layout.addWidget(form)
        self._update_summary()

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
        """Visa platshållarrader medan årsfilen läses, så att inget hoppar."""
        self._show_skeleton()
        self._vehicles = self._storage.load_year(self.year)
        self._populate_list()

    def _show_skeleton(self, rows: int = skeleton.DEFAULT_ROWS) -> None:
        """Fyll tabellen med platshållare i stället för tom yta (förslag 24).

        Radhöjden är den samma som de riktiga raderna får, så att rubriken,
        rullningslisten och formuläret står stilla när data kommer.
        """
        if not getattr(self, "_table_ready", False):
            return
        try:
            skeleton.show(self._table, list(VEHICLE_COLUMNS), rows=rows,
                          row_height=design.row_height(self._row_mode()))
        except Exception:
            _log.debug("Platshållarrader kunde inte visas", exc_info=True)

    def _populate_list(self) -> None:
        """Bygg om tabellen från årsfilen och de aktiva filtren."""
        self._capture_edited_forms()
        self._loading = True
        self._table.setRowCount(0)
        self._forms.clear()
        self._clear_form_panel()
        visible = self._visible_vehicles()
        for index, vehicle in enumerate(self._vehicles):
            form = VehicleForm(vehicle, app=self._app)
            form.data_modified.connect(
                lambda idx=index: self._on_form_modified(idx))
            form.enable_editing(self._editing)
            self._forms[str(index)] = form
        for vehicle in visible:
            self._add_table_row(vehicle)
        self._lbl_count.setText(f"{len(visible)} av {len(self._vehicles)} fordon"
                                if len(visible) != len(self._vehicles)
                                else f"{len(self._vehicles)} fordon")
        if visible:
            self._table.selectRow(0)
            self._empty_label.hide()
        else:
            self._form_layout.addWidget(self._empty_label)
            self._empty_label.show()
        self._loading = False
        self._load_table_profile()
        self._table.setSortingEnabled(True)
        self._update_summary()
        if visible:
            self._on_table_selection_changed()

    def _add_table_row(self, vehicle: Dict[str, Any]) -> None:
        """Lägg till en rad; index sparas på första cellen så att raden kan hittas."""
        row = self._table.rowCount()
        self._table.insertRow(row)
        index = next((i for i, item in enumerate(self._vehicles) if item is vehicle), -1)
        values = _column_values(vehicle)
        for column, name in enumerate(VEHICLE_COLUMNS):
            cell = QTableWidgetItem(values.get(name, ""))
            if column == 0:
                # VIN-koden är radens identitet och alltid fryst.
                cell.setData(Qt.ItemDataRole.UserRole, index)
                font = cell.font()
                font.setBold(True)
                cell.setFont(font)
            if name == "Status":
                missing = vehicle_filters.missing_fields(vehicle)
                cell.setToolTip("Saknar: " + ", ".join(missing) if missing
                                else "Alla obligatoriska uppgifter finns")
            self._table.setItem(row, column, cell)
        self._table.setRowHeight(row, design.row_height(self._row_mode()))

    def _update_summary(self) -> None:
        """Uppdatera statusraden under tabellen (förslag 10)."""
        try:
            visible = self._visible_vehicles()
            selection = self._table.selectionModel()
            selected = len(selection.selectedRows()) if selection else 0
            self._summary_label.setText(
                vehicle_filters.summary_text(self._vehicles,
                                             selected=selected,
                                             shown=len(visible)))
        except Exception:
            _log.debug("Summeringen kunde inte uppdateras", exc_info=True)

    def _on_form_modified(self, index: int) -> None:
        """Uppdatera radens celler direkt när formuläret ändras."""
        form = self._forms.get(str(index))
        if form is not None:
            values = _column_values(form.get_data())
            for row in range(self._table.rowCount()):
                cell = self._table.item(row, 0)
                if cell is not None and cell.data(Qt.ItemDataRole.UserRole) == index:
                    for column, name in enumerate(VEHICLE_COLUMNS):
                        target = self._table.item(row, column)
                        if target is not None:
                            target.setText(values.get(name, ""))
                    break
        self._on_modified_callback(self.year)
        self._update_summary()

    def _clear_form_panel(self) -> None:
        while self._form_layout.count():
            child = self._form_layout.takeAt(0)
            if child.widget():
                child.widget().setParent(None)

    def _show_context_menu(self, pos) -> None:
        item = self._table.itemAt(pos)
        if item is not None:
            self._table.selectRow(item.row())
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
        if item is not None:
            menu.addSeparator()
            menu.addAction("↔️ Återställ kolumnbredder", self._reset_table_profile)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _reset_table_profile(self) -> None:
        """Glöm årets kolumnläge och visa standardkolumnerna igen."""
        try:
            table_view.reset(self._profile_root(), "fordon", self.year)
            self._table.setColumnHidden(0, False)
            self._table.resizeColumnsToContents()
        except Exception:
            _log.debug("Kolumnläget kunde inte återställas", exc_info=True)

    def _capture_edited_forms(self) -> None:
        """Behåll redigeringar när listan byggs om före autosparning."""
        for index in range(len(self._vehicles)):
            form = self._forms.get(str(index))
            if form:
                self._vehicles[index] = form.get_data()

    def _add_empty(self) -> None:
        self._add_vehicle(dict(DEFAULT_VEHICLE_DATA))

    def _add_vehicle(self, data: Dict[str, Any]) -> None:
        self._capture_edited_forms()
        self._vehicles.append(data)
        self._populate_list()
        self.select_row(len(self._vehicles) - 1)
        self._on_modified_callback(self.year)

    def _duplicate_selected(self) -> None:
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(
                self, "Inget valt",
                "Välj ett fordon att kopiera först.",
            )
            return
        self._capture_edited_forms()
        data = copy.deepcopy(self._vehicles[row])
        data["vin_kod"] = ""
        self._add_vehicle(data)

    def _copy_to_other_year(self) -> None:
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(
                self, "Inget valt",
                "Välj ett fordon att kopiera först.",
            )
            return
        self._capture_edited_forms()
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
            self._capture_edited_forms()
            del self._vehicles[idx]
            self._populate_list()
            self._on_modified_callback(self.year)

    def add_vehicle_copy(self, data: Dict[str, Any]) -> None:
        """Lägg till en kopia av ett fordon i denna flik."""
        self._add_vehicle(copy.deepcopy(data))

    def open_year(self, year: int):
        """Öppna ett år (skapa fliken vid behov) och returnera dess YearTab."""
        try:
            year = int(year)
        except (TypeError, ValueError):
            return None
        if year not in self._tabs:
            self._create_tab(year, select=False)
        self._show_year(year)
        return self._tabs.get(year)

    def select_row(self, index: int) -> None:
        """Markera rad i tabellen (publik — används av sökning och kopiering)."""
        for row in range(self._table.rowCount()):
            cell = self._table.item(row, 0)
            if cell is not None and cell.data(Qt.ItemDataRole.UserRole) == index:
                self._table.selectRow(row)
                self._table.scrollToItem(cell)
                return

    def enable_editing(self, enabled: bool) -> None:
        self._editing = enabled
        self._btn_add.setEnabled(enabled)
        for form in self._forms.values():
            form.enable_editing(enabled)

    def get_all_data(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for i in range(len(self._vehicles)):
            form = self._forms.get(str(i))
            if form is None:
                raise ValueError(f"Fordon {i + 1} saknar formulär; sparandet avbröts.")
            data = form.get_data()
            if not str(data.get("vin_kod") or "").strip():
                raise ValueError(f"Fordon {i + 1} saknar VIN-kod; sparandet avbröts.")
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
        self._layout_year = datetime.now().year
        years = vehicle_initial_years(self._layout_year, self._storage.list_years(), initial_years or ())
        for year in years:
            self._create_tab(year, select=False)
        self._show_year(self._layout_year)
        # En app som är öppen över nyår ska också få rätt årsflikar.
        self._year_timer = QTimer(self)
        self._year_timer.setInterval(60 * 60 * 1000)
        self._year_timer.timeout.connect(self._refresh_year_placement)
        self._year_timer.start()
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
        # Gemensamt sidhuvud (förslag 5) i stället för en egen rubrikstil.
        layout.addWidget(PageHeader.build(
            "Fordonsdata", "vehicle",
            "Ett fordon per rad och år – VIN, färg, återförsäljare", self))
        layout.addLayout(self._create_toolbar())
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(Styles.TAB_WIDGET)
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.tabCloseRequested.connect(self._close_tab)
        self._archive_tabs = QTabWidget()
        self._archive_tabs.setStyleSheet(Styles.TAB_WIDGET)
        self._archive_tabs.setTabsClosable(True)
        self._archive_tabs.tabCloseRequested.connect(self._close_archive_tab)
        archive_index = self._tab_widget.addTab(self._archive_tabs, "Arkiv")
        # Arkivet är en permanent behållare, inte en årsflik som kan stängas.
        bar = self._tab_widget.tabBar()
        bar.setTabButton(archive_index, QTabBar.ButtonPosition.LeftSide, None)
        bar.setTabButton(archive_index, QTabBar.ButtonPosition.RightSide, None)
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
            "VIN, VIN3 eller approval-nummer"
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

    def _import_from_excel(self, filepath: Optional[str] = None) -> None:
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
        if self._modified:
            QMessageBox.warning(
                self, "Osparade ändringar",
                "Spara eller stäng osparade årsflikar innan du importerar Excel. "
                "Annars skulle importen kunna ersätta ändringar i formulären.",
            )
            return
        vr_plugin = get_plugin_safe(self._app, "vehicle_registry")
        if not vr_plugin or not hasattr(vr_plugin, "import_from_excel"):
            QMessageBox.warning(
                self,
                "Plugin saknas",
                "Vehicle Registry plugin saknar import_from_excel().\n\n"
                "Kontrollera att vehicle_registry v4.6.0+ är installerad.",
            )
            return
        if not isinstance(filepath, str) or not filepath:
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
            "Läser Excel-fil...", "", 0, 0, self,
        )
        progress.setWindowTitle("Excel-import")
        # Importen ändrar lagring och saknar säker avbrytning.
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        def progress_cb(msg: str) -> None:
            progress.setLabelText(msg)
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
        try:
            progress.show()
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
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
            # Exempelvärden kommer från respektive blads förhandsläsning.
            examples: Dict[str, List[str]] = {}
            for info in usable:
                for key, values in info.get("examples", {}).items():
                    collected = examples.setdefault(key, [])
                    for value in values:
                        if value not in collected and len(collected) < 3:
                            collected.append(value)
            # 2. Fingerprint över ALLA blads rubriker (P14) + sparad mappning
            fingerprint = vr_plugin.build_mapping_fingerprint(headers)
            saved_mapping = (
                vr_plugin.load_column_mapping_for_fingerprint(fingerprint)
                or {}
            )
            prior_protected = bool(saved_mapping) and (
                not hasattr(vr_plugin, "is_mapping_protected")
                or vr_plugin.is_mapping_protected(fingerprint)
            )
            suggestion = vr_plugin.suggest_column_mapping(headers) or {}
            initial_mapping = saved_mapping if saved_mapping else suggestion
            learned_headers = []
            learning_store = None
            expected_import_fingerprint = vr_plugin.build_mapping_fingerprint(
                [header for info in usable for header in info.get("headers", [])]
            )
            if not saved_mapping:
                try:
                    from core.learning import LearningStore, vehicle_mapping_suggestions
                    learning_store = LearningStore(Path(__file__).resolve().parents[2] / "json" / "mappings" / "learning.json")
                    initial_mapping, learned_headers = vehicle_mapping_suggestions(
                        learning_store, [_normalize_header(h) for h in headers],
                        initial_mapping, TARGET_FIELD_LABELS,
                    )
                except Exception as exc:
                    _log.warning("Inlärda förslag kunde inte läsas: %s", exc)
            progress.close()
            # 3. Mappningsdialog
            from core.vehicle_mapping_profiles import ProfileStore
            mapping_dialog = ColumnMappingDialog(
                profile_store=ProfileStore(Path(__file__).resolve().parents[2] / "json" / "mappings" / "vehicle_mapping_profiles.json"),
                headers=headers,
                examples=examples,
                learned_headers=learned_headers,
                allow_profile_save=not prior_protected,
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
            # Inlärning kräver även att sparande faktiskt lyckats och inte är PIN-skyddat.
            mapping_saved_for_learning = False
            protected = mapping_dialog.protect_checked()
            if mapping_dialog.save_mapping_checked():
                protected = mapping_dialog.protect_checked()
                try:
                    pin = None
                    if protected or prior_protected:
                        from plugins.main_gui.dialogs.dealer_pin import request_pin, request_migrated_pin
                        dealer = get_plugin_safe(self._app, "dealers_manager") or getattr(self._app, "dealers", None)
                        if dealer is None:
                            raise ValueError("Den gemensamma PIN-hanteraren saknas")
                        if prior_protected and vr_plugin.mapping_legacy_identity(fingerprint) != "shared":
                            pin = request_migrated_pin(self, dealer, "mapping:" + fingerprint,
                                lambda: vr_plugin.mapping_legacy_identity(fingerprint),
                                lambda old: vr_plugin.verify_legacy_mapping_pin(fingerprint, old),
                                "den skyddade importmappningen")
                        else:
                            pin = request_pin(self, dealer, resource="importmappningen")
                        if pin is None:
                            raise PermissionError("PIN-kontrollen avbröts")
                    vr_plugin.set_column_mapping(column_mapping, fingerprint=fingerprint,
                                                 pin=pin, protected=protected)
                    mapping_saved_for_learning = True
                except Exception as exc:
                    QMessageBox.warning(self, "Kunde inte spara mappning",
                                        f"{exc}\n\nImporten fortsätter utan att spara mappningen.")
            progress.setLabelText("Analyserar importen...")
            progress.show()
            # Årskonflikter måste lösas före VIN-konflikter och före skrivning.
            year_choices: Dict[Tuple[str, str], int] = {}
            while True:
                preview = vr_plugin.preview_excel_import(
                    filepath=filepath,
                    column_mapping=column_mapping,
                    progress_callback=progress_cb,
                    year_choices=year_choices,
                )
                errors = preview.get("errors", [])
                if errors:
                    raise ValueError("; ".join(errors))
                issues = preview.get("year_issues", [])
                if not issues:
                    break
                progress.close()
                choices = self._choose_import_years(issues)
                if choices is None:
                    _log.info("Användaren avbröt valet av årsmodell")
                    return
                year_choices.update(choices)
                progress.setLabelText("Kontrollerar valda år...")
                progress.show()
            conflicts = preview.get("conflicts", [])
            conflict_resolutions: Dict[Tuple, str] = {}
            # En senare rad kan skapa en ny konflikt beroende på tidigare val.
            # Kör om torrt tills varje konflikt har ett uttryckligt val.
            while conflicts:
                progress.close()
                conflict_dialog = ConflictResolutionDialog(conflicts=conflicts, parent=self)
                if conflict_dialog.exec() != QDialog.DialogCode.Accepted:
                    _log.info("Användaren avbröt konfliktdialogen")
                    return
                conflict_resolutions.update(conflict_dialog.get_resolutions())
                progress.setLabelText("Kontrollerar dubbletter...")
                progress.show()
                preview = vr_plugin.import_from_excel(
                    filepath=filepath, column_mapping=column_mapping,
                    conflict_resolutions=conflict_resolutions, dry_run=True,
                    progress_callback=progress_cb, save_mapping=False, year_choices=year_choices,
                )
                if preview.get("errors"):
                    raise ValueError("; ".join(preview["errors"]))
                if preview.get("needs_year_resolution"):
                    raise ValueError("Årsuppgifterna ändrades. Starta importen igen.")
                conflicts = preview.get("conflicts", [])
            # 5. Riktig import
            result = vr_plugin.import_from_excel(
                filepath=filepath,
                column_mapping=column_mapping,
                on_conflict="replace",
                conflict_resolutions=conflict_resolutions,
                progress_callback=progress_cb,
                save_mapping=False,
                year_choices=year_choices,
            )
            if result.get("needs_year_resolution"):
                raise ValueError("Årsuppgifterna har ändrats sedan kontrollen. Starta importen igen.")
            if result.get("needs_resolution"):
                raise ValueError("Konflikterna har ändrats sedan kontrollen. Starta importen igen.")
            # Lägg aldrig till belägg efter avbruten, partiell eller misslyckad import.
            try:
                from core.learning import LearningStore, learn_vehicle_import
                if learning_store is None:
                    learning_store = LearningStore(Path(__file__).resolve().parents[2] / "json" / "mappings" / "learning.json")
                learn_vehicle_import(
                    learning_store, column_mapping, TARGET_FIELD_LABELS, result,
                    expected_import_fingerprint, approved_save=mapping_saved_for_learning,
                    protected=protected or prior_protected,
                )
            except Exception as exc:
                _log.warning("Kunde inte spara inlärda förslag: %s", exc)
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

    def _choose_import_years(self, issues: List[Dict[str, Any]]) -> Optional[Dict[Tuple[str, str], int]]:
        """Fråga per blad och avvikande år innan några fordonsdata skrivs."""
        choices: Dict[Tuple[str, str], int] = {}
        for issue in issues:
            sheet = issue["sheet"]
            raw = issue.get("raw_year", "")
            sheet_year = issue.get("sheet_year")
            row_year = issue.get("row_year")
            count = issue.get("count", 0)
            if sheet_year is not None and row_year is not None:
                message = QMessageBox(self)
                message.setWindowTitle("Årsmodell skiljer sig")
                message.setIcon(QMessageBox.Icon.Warning)
                message.setTextFormat(Qt.TextFormat.PlainText)
                message.setText(
                    f"Bladet '{sheet}' anger {sheet_year}, men {count} rad(er) anger {row_year}.\n"
                    "Vilket år ska dessa rader importeras till?"
                )
                sheet_button = message.addButton(f"Bladets år: {sheet_year}", QMessageBox.ButtonRole.AcceptRole)
                row_button = message.addButton(f"Radens år: {row_year}", QMessageBox.ButtonRole.AcceptRole)
                cancel_button = message.addButton("Avbryt import", QMessageBox.ButtonRole.RejectRole)
                message.setDefaultButton(cancel_button)
                message.exec()
                if message.clickedButton() is sheet_button:
                    selected = sheet_year
                elif message.clickedButton() is row_button:
                    selected = row_year
                else:
                    return None
            else:
                from core.vehicle_import_insights import example_text
                explanation = (f"Ogiltigt årsvärde: {example_text(raw)}" if raw else "Årsmodell saknas")
                selected, ok = QInputDialog.getInt(
                    self, "Ange årsmodell",
                    f"Blad '{sheet}': {explanation}.\n"
                    f"Ange år för {count} rad(er), eller avbryt importen:",
                    sheet_year or datetime.now().year, 1900, 2100,
                )
                if not ok:
                    return None
            choices[(sheet, raw)] = selected
        return choices

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

    def _year_container(self, year: int, current_year: Optional[int] = None) -> QTabWidget:
        current = datetime.now().year if current_year is None else current_year
        return self._archive_tabs if is_archived_year(year, current) else self._tab_widget

    def _insert_year_tab(self, year: int, tab: YearTab, current_year: Optional[int] = None) -> None:
        container = self._year_container(year, current_year)
        index = sum(1 for other_year, other_tab in self._tabs.items()
                    if other_year < year and container.indexOf(other_tab) >= 0)
        title = f"{year} *" if year in self._modified else str(year)
        container.insertTab(index, tab, title)

    def _show_year(self, year: int) -> None:
        tab = self._tabs.get(year)
        if tab is None:
            return
        if self._archive_tabs.indexOf(tab) >= 0:
            self._tab_widget.setCurrentWidget(self._archive_tabs)
            self._archive_tabs.setCurrentWidget(tab)
        elif self._tab_widget.indexOf(tab) >= 0:
            self._tab_widget.setCurrentWidget(tab)

    def _create_tab(self, year: int, select: bool = True) -> None:
        if year in self._tabs:
            if select:
                self._show_year(year)
            return
        try:
            tab = YearTab(year, self._storage, self._on_year_modified, app=self._app)
        except ValueError as exc:
            _log.exception("Kunde inte öppna år %s", year)
            QMessageBox.warning(self, "Årsdata kunde inte öppnas", f"År {year}: {exc}\n\nFilen har inte ändrats.")
            return
        tab.enable_editing(self._is_unlocked)
        tab.copy_vehicle_requested.connect(self._on_copy_vehicle_requested)
        self._tabs[year] = tab
        self._insert_year_tab(year, tab)
        if select:
            self._show_year(year)

    def _refresh_year_placement(self) -> None:
        """Flytta widgets, inte filer, vid ett årsskifte. Behåll osparade formulär."""
        current = datetime.now().year
        if current == self._layout_year:
            return
        selected = self._tab_widget.currentWidget()
        if selected is self._archive_tabs:
            selected = self._archive_tabs.currentWidget()
        for year, tab in sorted(self._tabs.items()):
            target = self._year_container(year, current)
            source = self._archive_tabs if self._archive_tabs.indexOf(tab) >= 0 else self._tab_widget
            if source is not target:
                index = source.indexOf(tab)
                if index < 0:
                    raise RuntimeError(f"Årsfliken {year} saknar behållare")
                source.removeTab(index)
                self._insert_year_tab(year, tab, current)
        for year in range(FIRST_YEAR, current + 1):
            if year not in self._tabs:
                self._create_tab(year, select=False)
        self._layout_year = current
        self._update_archive_title()
        for year, tab in self._tabs.items():
            if tab is selected:
                self._show_year(year)
                break

    def _close_tab(self, index: int) -> None:
        self._close_year_tab(self._tab_widget, index)

    def _close_archive_tab(self, index: int) -> None:
        self._close_year_tab(self._archive_tabs, index)

    def _close_year_tab(self, container: QTabWidget, index: int) -> None:
        widget = container.widget(index)
        for year, tab in list(self._tabs.items()):
            if tab is widget:
                if not self._handle_unsaved_changes(year, tab):
                    return
                del self._tabs[year]
                container.removeTab(index)
                tab.deleteLater()
                self._update_archive_title()
                return
        # Arkivfliken eller en ogiltig index får aldrig tas bort här.

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
            try:
                if not self._save_year_with_duplicate_confirmation(year, tab.get_all_data()):
                    return False
            except Exception as exc:
                _log.exception("Kunde inte spara år %s", year)
                QMessageBox.warning(self, "Kunde inte spara", str(exc))
                return False
        else:
            try:
                tab.refresh()
            except Exception as exc:
                _log.exception("Kunde inte återläsa år %s", year)
                QMessageBox.warning(self, "Kunde inte återläsa data", str(exc))
                return False
        self._modified.discard(year)
        self._update_tab_title(year, modified=False)
        return True

    def confirm_close(self) -> bool:
        """Fråga om osparade år innan huvudfönstret får stängas."""
        for year in sorted(self._modified):
            tab = self._tabs.get(year)
            if tab is None or not self._handle_unsaved_changes(year, tab):
                return False
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
            self._show_year(target_year)

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
        # Callbacken verifierar gemensam PIN samt eventuell äldre PIN vid övergång.
        if self._pin_getter(self) is None:
            return
        self._lock_state = LockState.UNLOCKED
        self._update_lock_state()
        self._autolock_timer.start()

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

    def _update_archive_title(self) -> None:
        index = self._tab_widget.indexOf(self._archive_tabs)
        if index < 0:
            return
        dirty = any(self._archive_tabs.indexOf(self._tabs[year]) >= 0
                    for year in self._modified if year in self._tabs)
        self._tab_widget.setTabText(index, "Arkiv *" if dirty else "Arkiv")

    def _update_tab_title(self, year: int, modified: bool = False) -> None:
        tab = self._tabs.get(year)
        if tab is None:
            return
        for container in (self._tab_widget, self._archive_tabs):
            index = container.indexOf(tab)
            if index >= 0:
                container.setTabText(index, f"{year} *" if modified else str(year))
                break
        self._update_archive_title()

    def _save_year_with_duplicate_confirmation(self, year: int, vehicles: List[Dict[str, Any]]) -> bool:
        """Fråga innan manuell redigering introducerar nya VIN3-dubbletter."""
        previous = self._storage.load_year(year)
        def grouped(rows):
            groups = {}
            for row in rows:
                vin = str(row.get("vin_kod") or "").strip().upper()
                if vin:
                    groups.setdefault(vin, []).append(row)
            return groups
        old_groups, new_groups = grouped(previous), grouped(vehicles)
        # Stoppa eventuella timeranrop medan en modal fråga är öppen.
        self._autosave_timer.stop()
        for vin, records in new_groups.items():
            if len(records) <= 1 or len(records) <= len(old_groups.get(vin, [])):
                continue
            approvals = "\n".join(
                f"• Approval: {row.get('avgaskrav_tillagg') or 'saknas'} — "
                f"{row.get('handelsbeteckning') or row.get('typ') or 'utan modellnamn'}"
                for row in records
            )
            reply = QMessageBox.question(
                self, "Dubblett i Fordonsdata",
                f"År {year} innehåller {len(records)} poster med VIN3 {vin}:\n\n{approvals}\n\n"
                "Vill du behålla alla dessa poster? Nej avbryter sparandet.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
        if self._storage.load_year(year) != previous:
            raise ValueError("Årets data ändrades under sparandet. Återläs innan du försöker igen.")
        self._storage.save_year(year, vehicles)
        return True

    def _do_autosave(self) -> None:
        for year in list(self._modified):
            tab = self._tabs.get(year)
            if tab:
                try:
                    if not self._save_year_with_duplicate_confirmation(year, tab.get_all_data()):
                        continue
                    self._modified.discard(year)
                    self._update_tab_title(year, modified=False)
                except Exception as e:
                    _log.error(
                        "Autosave failed for %d: %s", year, e
                    )
        # Misslyckade år ligger kvar som osparade och kan försöka igen.

    def _save_all(self) -> None:
        if not self._is_unlocked:
            return
        if not self._modified:
            QMessageBox.information(self, "Sparat", "Det finns inga osparade ändringar.")
            return
        # Validera först, men låt inte oförändrade år hindra sparande.
        for year, tab in self._tabs.items():
            if year not in self._modified:
                continue
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
            if year not in self._modified:
                continue
            try:
                if not self._save_year_with_duplicate_confirmation(year, tab.get_all_data()):
                    return
            except Exception as exc:
                _log.exception("Kunde inte spara år %s", year)
                QMessageBox.warning(self, "Kunde inte spara", f"År {year}: {exc}")
                return
            saved.append(year)
            self._modified.discard(year)
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
        if result is None:  # Avbrutet val eller en årgång kunde inte läsas.
            return
        if result.found:
            self._navigate_to_result(result)
        else:
            QMessageBox.information(self, "Ej hittat", f"Ingen träff för '{text}' i något år eller i arkivet.")

    def _search_vehicle(self, text: str) -> Optional[SearchResult]:
        query = text.strip().upper()
        if not query:
            return None
        # Sök VIN3 för fullständigt VIN och sexställigt VINCODE, men även
        # approval som delsträng. Andra sökord tolkas enbart som approval.
        vin3 = None
        if len(query) == 3 and validate_vin3(query):
            vin3 = query
        elif len(query) in (6, 17) and query.isalnum():
            vin3 = extract_vin3_from_full(query)
        try:
            years = sorted(set(self._storage.list_years()) | set(self._tabs), reverse=True)
            matches = []
            for year in years:
                tab = self._tabs.get(year)
                if tab is not None:
                    rows = [(form.get_data() if form else vehicle)
                            for idx, vehicle in enumerate(tab._vehicles)
                            for form in [tab._forms.get(str(idx))]]
                else:
                    rows = self._storage.load_year(year)
                for idx, row in enumerate(rows):
                    code = str(row.get("vin_kod") or "").strip().upper()
                    approval = str(row.get("avgaskrav_tillagg") or "").strip().upper()
                    if (vin3 and code == vin3) or query in approval:
                        matches.append((year, idx, copy.deepcopy(row), tab is not None))
        except Exception as exc:
            _log.exception("Sökning i årsdata misslyckades")
            QMessageBox.warning(self, "Sökningen kunde inte slutföras", f"En årgång kunde inte läsas: {exc}\n\nIngen data ändrades.")
            return None
        if not matches:
            return SearchResult(found=False, vin3=vin3)
        if len(matches) > 1:
            options = [
                f"{n + 1}. År {year} — VIN3: {row.get('vin_kod') or 'saknas'} — "
                f"Approval: {row.get('avgaskrav_tillagg') or 'saknas'} — "
                f"{row.get('handelsbeteckning') or row.get('typ') or 'utan modellnamn'}"
                for n, (year, _idx, row, _opened) in enumerate(matches)
            ]
            selected, ok = QInputDialog.getItem(self, "Flera fordon hittades", "Välj post:", options, 0, False)
            if not ok or selected not in options:
                return None
            year, idx, row, was_open = matches[options.index(selected)]
        else:
            year, idx, row, was_open = matches[0]
        return SearchResult(found=True, year=year, index=idx, vin3=vin3, snapshot=row, was_open=was_open)

    def _navigate_to_result(self, result: SearchResult) -> None:
        if not result.found or result.year is None or result.index is None:
            return
        if result.year not in self._tabs:
            self._create_tab(result.year, select=False)
        tab = self._tabs.get(result.year)
        if tab is None:
            return
        snapshot = getattr(result, "snapshot", None)
        if snapshot is not None:
            # En stängd årsfil kan ha ändrats av en annan process medan
            # valdialogen var öppen. Välj inte fel post efter en sådan ändring.
            idx = result.index
            if idx >= len(tab._vehicles):
                QMessageBox.warning(self, "Sökresultatet har ändrats", "Årsdata har ändrats. Gör om sökningen.")
                return
            form = tab._forms.get(str(idx)) if getattr(result, "was_open", False) else None
            current = form.get_data() if form else tab._vehicles[idx]
            if current != snapshot:
                QMessageBox.warning(self, "Sökresultatet har ändrats", "Årsdata har ändrats. Gör om sökningen.")
                return
        self._show_year(result.year)
        tab.select_row(result.index)
        self._search.clear()

    # ──────────────────────────────────────────────────────────────────
    # PUBLIC API

    # ──────────────────────────────────────────────────────────────────

    def refresh_all(self) -> None:
        """Ladda om alla tabs från disk."""
        for year, tab in self._tabs.items():
            # Navigation och globala uppdateringar får inte kasta osparade
            # formulärändringar, exempelvis medan VIN ännu saknas.
            if year not in self._modified:
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
