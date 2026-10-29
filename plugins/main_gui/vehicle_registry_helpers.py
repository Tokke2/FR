# -*- coding: utf-8 -*-
# plugins/main_gui/vehicle_registry_helpers.py

"""
Vehicle Registry GUI — Hjälpmodul v1.0.0
Hjälpfil till vehicle_registry_page.py (spec v1.4, Sektion A:
"Om fil >1800 rader → föreslå hjälpfil (max 1200 rader)").
Innehåller (flyttat från vehicle_registry_page.py v5.5.0):
  - Konstanter: TIMER_CONFIG, VIN3_PATTERN, VIN_INVALID_CHARS,
    TARGET_FIELD_LABELS, INTERNAL_TO_TS_FIELD_CANDIDATES,
    DROPDOWNS, FIELD_GROUPS, VALIDATION, DEFAULT_VEHICLE_DATA
  - Styles/STYLES (tema-styling för fordonssidans widgets)
  - Hjälpfunktioner: _normalize_header, get_plugin_safe,
    get_ts_schema_safe, validate_vin3, extract_vin3_from_full,
    _build_ts_field_lookup, get_copyright_string
  - Dataclasses/enums/protocols: TimerConfig, FieldInfo, SearchResult,
    FieldType, LockState, VehicleDict, ValidationRule, FieldDefinition,
    PluginProtocol, AppProtocol, FieldSpecProtocol
  - Dialoger: ColumnMappingDialog ("COMNAME = ?"-flödet, KRAV 40/31),
    ConflictResolutionDialog (KRAV 37),
    GenerateTextFileDialog (+ _write_vehicle_text_file)
ANVÄNDS AV:
  plugins/main_gui/vehicle_registry_page.py
    → from .vehicle_registry_helpers import (...)
    → VehicleForm, YearTab, VehicleDataPage (konstanter, Styles,
      hjälpfunktioner och dialoger)
IMPORTER:
  logging, os, re, tempfile, collections (OrderedDict),
  dataclasses, datetime, enum, pathlib, typing
  PySide6.QtCore (Qt), PySide6.QtWidgets (dialogwidgets)
  TYPE_CHECKING: plugins.vehicle_registry.plugin (VehicleDataStorage)
FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (radbrytningsdubbling): 930 dubblerade blankrader (transport-
    artefakt) kollapsade till max 1 tomrad — normaliserat enligt
    arbetsregeln. Ingen logikändring.
  - VERSION/AUTHOR module-level tillagda (saknades — endast
    get_copyright_string fanns) + i __all__.
  - Övrig logik OFÖRÄNDRAD (dialoger, helpers, styles, konstanter,
    _write_vehicle_text_file atomisk).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (Session 10): uppdelning av vehicle_registry_page.py v5.5.0
    (2307 rader → hjälpfil + page). Ingen logikändring — ren flytt.
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""
from __future__ import annotations
import logging
import os
import re
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Final, List,
    Optional, Protocol, Tuple, TypedDict,
)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from plugins.vehicle_registry.plugin import VehicleDataStorage

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER

# ══════════════════════════════════════════════════════════════════════════════
_log: logging.Logger = logging.getLogger("vehicle_registry_helpers")

# ══════════════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT (v1.0.1 — tillagda vid granskning)
# ══════════════════════════════════════════════════════════════════════════════
VERSION: str = "1.0.1"
AUTHOR: str = "Rickard Längkvist"

def get_copyright_string() -> str:

    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} Rickard Längkvist"

# ══════════════════════════════════════════════════════════════════════════════
# PROTOCOLS

# ══════════════════════════════════════════════════════════════════════════════

class PluginProtocol(Protocol):

    def get_schema(self, post_type: str) -> Optional[Any]: ...

class AppProtocol(Protocol):

    def get_plugin(self, name: str) -> Optional[Any]: ...

class FieldSpecProtocol(Protocol):
    name: str
    length: int
    required: bool
    field_type: str

# ══════════════════════════════════════════════════════════════════════════════
# ENUMS

# ══════════════════════════════════════════════════════════════════════════════

class FieldType(str, Enum):
    TEXT = "text"
    INT = "int"
    FLOAT = "float"
    DROPDOWN = "dropdown"
    VIN3 = "vin3"

class LockState(Enum):
    LOCKED = auto()
    UNLOCKED = auto()

# ══════════════════════════════════════════════════════════════════════════════
# TYPE DEFINITIONS

# ══════════════════════════════════════════════════════════════════════════════

class VehicleDict(TypedDict, total=False):
    vin_kod: str
    fabrikat: str
    fabrikatskod: str
    typ: str
    variant: str
    version: str
    handelsbeteckning: str
    fordonskategori: str
    langd_mm: str
    bredd_mm: str
    hojd_mm: str
    vikt_kor_klar_kg: str
    totalvikt_kg: str
    slagvolym_cm3: str
    effekt_kw: str
    varvtal_effekt_1: str
    max_hastighet_kmh: str
    bransle1: str
    bransle2: str
    antal_axlar: str
    antal_hjul: str
    bromsar: str
    dack_fram: str
    dack_bak: str
    euroklass: str
    ljud_stillas_db: str
    avgaskrav_grund: str
    avgaskrav_tillagg: str
    tillverkningsmanad: str
    skyltformat_bak: str
    kommissionssparr: str
    bestallning_regbevis: str

class ValidationRule(TypedDict, total=False):
    type: str
    required: bool
    min: int
    max: int

class FieldDefinition(TypedDict):
    key: str
    label: str
    placeholder: str

# ══════════════════════════════════════════════════════════════════════════════
# DATACLASSES

# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)

class TimerConfig:
    autolock_ms: int = 10 * 60 * 1000
    autosave_ms: int = 700

@dataclass

class FieldInfo:
    key: str
    label: str
    placeholder: str = ""

    def to_tuple(self) -> Tuple[str, str, str]:
        return (self.key, self.label, self.placeholder)

@dataclass

class SearchResult:
    found: bool
    year: Optional[int] = None
    index: Optional[int] = None
    vin3: Optional[str] = None

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS

# ══════════════════════════════════════════════════════════════════════════════
TIMER_CONFIG: Final[TimerConfig] = TimerConfig()
VIN3_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-HJ-NPR-Z0-9]{3}$")
VIN_INVALID_CHARS: Final[str] = "IOQ"
# Målfält för Excel-mappningsdialogen (internt fält -> svensk etikett)
TARGET_FIELD_LABELS: Final[Dict[str, str]] = {
    "_year": "Årsmodell (ej sparas i record)",
    "vin_kod": "VIN-kod (3 tecken)",
    "typ": "Typ",
    "variant": "Variant",
    "version": "Version",
    "modellkod": "Modellkod",
    "handelsbeteckning": "Handelsbeteckning / Modell",
    "fordonsklass": "Fordonsklass",
    "fordonskategori": "Fordonskategori",
    "avgaskrav_tillagg": "Typgodkännande / Approval",
    "godkannandedatum": "Godkännandedatum",
    "antal_axlar": "Antal axlar",
    "antal_hjul": "Antal hjul",
    "bromsar": "Bromssystem",
    "langd_mm": "Längd (mm)",
    "bredd_mm": "Bredd (mm)",
    "hojd_mm": "Höjd (mm)",
    "vikt_kor_klar_kg": "Vikt körklar (kg)",
    "totalvikt_kg": "Totalvikt (kg)",
    "slagvolym_cm3": "Slagvolym (cm³)",
    "effekt_kw": "Effekt (kW)",
    "max_vridmoment": "Max vridmoment",
    "max_hastighet_kmh": "Maxhastighet (km/h)",
    "bransle1": "Drivmedel",
    "dack_fram": "Däck fram",
    "dack_bak": "Däck bak",
    "antal_platser": "Antal platser",
    "euroklass": "Euroklass",
    "ljud_stillas_db": "Ljudnivå stillastående (dB)",
    "ljud_varvtal": "Ljud varvtal",
    "ljud_korning_db": "Ljud körning (dB)",
    "utslappsklass": "Utsläppsklass",
    "co2_utslapp": "CO2-utsläpp",
}
INTERNAL_TO_TS_FIELD_CANDIDATES: Final[Dict[str, List[str]]] = {
    "fabrikat": ["FABRIKAT", "MAKE"],
    "fabrikatskod": ["FABRIKATSKOD", "MAKE_CODE"],
    "typ": ["TYP", "TYPE"],
    "variant": ["VARIANT", "VARIANTE"],
    "version": ["VERSION"],
    "handelsbeteckning": ["HANDELSBETECKNING", "MODEL", "MODELNAME"],
    "fordonskategori": ["FORDONSKATEGORI", "VEHICLE_CATEGORY", "VEHCAT2", "CLASS"],
    "langd_mm": ["LÄNGD", "LENGTH"],
    "bredd_mm": ["BREDD", "WIDTH"],
    "hojd_mm": ["HÖJD", "HEIGHT"],
    "vikt_kor_klar_kg": ["VIKT_KÖRKLAR", "MASS", "KERB_MASS"],
    "totalvikt_kg": ["TOTALVIKT", "LADENMASS", "TOTAL_MASS"],
    "slagvolym_cm3": ["SLAGVOLYM", "CYLCAPACITY", "CYL_CAPACITY"],
    "effekt_kw": ["EFFEKT", "MAXPOWER", "POWER"],
    "max_hastighet_kmh": ["MAX_HASTIGHET", "SPEED", "MAXSPEED"],
    "bransle1": ["BRÄNSLE", "FUEL"],
    "bransle2": ["BRÄNSLE2", "FUEL2"],
    "antal_axlar": ["ANTAL_AXLAR", "NUMAXLE"],
    "antal_hjul": ["ANTAL_HJUL", "NUMWHEEL"],
    "euroklass": ["EUROKLASS", "EMISLVL", "EMISSION_LEVEL"],
    "dack_fram": ["DÄCK_FRAM", "TYRESIZE1"],
    "dack_bak": ["DÄCK_BAK", "TYRESIZE2"],
}
DROPDOWNS: Final[Dict[str, List[str]]] = {
    "bransle1": ["BENSIN", "DIESEL", "EL", "ETANOL", "HYBRID", "GAS", "VÄTGAS"],
    "bransle2": ["-", "BENSIN", "DIESEL", "EL", "ETANOL", "HYBRID", "GAS"],
    "bromsar": ["ABS", "EBS", "CBS", "ABS+CBS", "Hydraulisk", "Mekanisk"],
    "euroklass": ["1", "2", "3", "4", "5", "5+", "6", "6+", "7"],
    "fordonskategori": [
        "L1E-A", "L1E-B", "L2E", "L3E-A1", "L3E-A2", "L3E-A3",
        "L4E", "L5E", "L6E", "L7E", "M1", "N1",
    ],
    "skyltformat_bak": ["Enradig 520x110", "Tvåradig 170x150", "Liten 300x110"],
    "bestallning_regbevis": ["Nej", "Ja"],
    "kommissionssparr": ["N", "J"],
}
FIELD_GROUPS: Final[OrderedDict[str, List[Tuple[str, str, str]]]] = OrderedDict([
    ("Identitet", [
        ("fabrikat", "Fabrikat", "Ex: Harley-Davidson"),
        ("fabrikatskod", "Fabrikatskod", "Ex: HAR"),
        ("typ", "Typ", "Ex: FXBRS"),
        ("variant", "Variant", ""),
        ("version", "Version", ""),
        ("handelsbeteckning", "Modell", "Ex: Breakout"),
        ("fordonskategori", "Kategori", ""),
        ("vin_kod", "VIN-kod (3 tecken)", "Ex: ZES"),
    ]),
    ("Dimensioner & Vikt", [
        ("langd_mm", "Längd (mm)", ""),
        ("bredd_mm", "Bredd (mm)", ""),
        ("hojd_mm", "Höjd (mm)", ""),
        ("vikt_kor_klar_kg", "Vikt körklart (kg)", ""),
        ("totalvikt_kg", "Totalvikt (kg)", ""),
    ]),
    ("Motor", [
        ("slagvolym_cm3", "Slagvolym (cm³)", ""),
        ("effekt_kw", "Effekt (kW)", ""),
        ("varvtal_effekt_1", "Varvtal maxeffekt", ""),
        ("max_hastighet_kmh", "Maxhastighet (km/h)", ""),
        ("bransle1", "Drivmedel", ""),
        ("bransle2", "Sekundärt drivmedel", ""),
    ]),
    ("Chassi", [
        ("antal_axlar", "Antal axlar", ""),
        ("antal_hjul", "Antal hjul", ""),
        ("bromsar", "Bromssystem", ""),
        ("dack_fram", "Däck fram", ""),
        ("dack_bak", "Däck bak", ""),
    ]),
    ("Miljö", [
        ("euroklass", "Euroklass", ""),
        ("ljud_stillas_db", "Ljudnivå (dB)", ""),
        ("avgaskrav_grund", "Grunddirektiv", ""),
        ("avgaskrav_tillagg", "Typgodkännande", ""),
    ]),
    ("Administration", [
        ("tillverkningsmanad", "Tillverkningsmånad", "YYYY-MM"),
        ("skyltformat_bak", "Skyltformat", ""),
        ("kommissionssparr", "Kommissionärsspärr", ""),
        ("bestallning_regbevis", "Beställ regbevis", ""),
    ]),
])
VALIDATION: Final[Dict[str, ValidationRule]] = {
    "vin_kod": {"type": "vin3", "required": True},
    "fabrikat": {"type": "text", "required": True, "max": 24},
    "typ": {"type": "text", "required": True, "max": 24},
    "fordonskategori": {"type": "dropdown", "required": True},
    "langd_mm": {"type": "int", "min": 500, "max": 99999},
    "bredd_mm": {"type": "int", "min": 200, "max": 99999},
    "hojd_mm": {"type": "int", "min": 200, "max": 99999},
    "vikt_kor_klar_kg": {"type": "int", "min": 50, "max": 99999},
    "totalvikt_kg": {"type": "int", "min": 50, "max": 99999},
    "slagvolym_cm3": {"type": "int", "min": 1, "max": 20000},
    "effekt_kw": {"type": "float", "min": 0, "max": 2000},
    "varvtal_effekt_1": {"type": "int", "min": 500, "max": 20000},
    "max_hastighet_kmh": {"type": "int", "min": 25, "max": 500},
    "euroklass": {"type": "dropdown", "required": True},
    "bransle1": {"type": "dropdown", "required": True},
}
DEFAULT_VEHICLE_DATA: Final[VehicleDict] = {
    "skyltformat_bak": "Tvåradig 170x150",
    "bestallning_regbevis": "Ja",
    "kommissionssparr": "N",
    "euroklass": "5",
    "bransle1": "BENSIN",
}

# ══════════════════════════════════════════════════════════════════════════════
# STYLES

# ══════════════════════════════════════════════════════════════════════════════

class Styles:
    PAGE_TITLE: Final[str] = (
        "font-size: 24px; font-weight: bold; "
        "padding: 10px; color: #ffffff;"
    )
    GROUP_BOX: Final[str] = """
        QGroupBox {
            font-weight: bold; padding-top: 15px;
            border: 1px solid #444; border-radius: 5px;
            margin-top: 10px; background: #2b2b2b;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 10px;
            padding: 0 5px; color: #ffffff;
        }

    """
    LIST_WIDGET: Final[str] = """
        QListWidget {
            background: #2b2b2b; color: #fff;
            border: 1px solid #444; border-radius: 4px;
        }
        QListWidget::item {
            padding: 8px; border-bottom: 1px solid #404040;
        }
        QListWidget::item:selected { background: #007bff; }
        QListWidget::item:hover { background: #3a3a3a; }

    """
    TAB_WIDGET: Final[str] = """
        QTabWidget::pane {
            border: 1px solid #444; border-radius: 4px;
            background: #2b2b2b;
        }
        QTabBar::tab {
            background: #343a40; color: #fff;
            padding: 8px 16px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            margin-right: 2px;
        }
        QTabBar::tab:selected { background: #007bff; }
        QTabBar::tab:hover:!selected { background: #495057; }

    """
    BTN_PRIMARY: Final[str] = """
        QPushButton {
            background: #007bff; color: white; border: none;
            padding: 6px 12px; border-radius: 4px; font-weight: bold;
        }
        QPushButton:hover { background: #0056b3; }
        QPushButton:disabled { background: #6c757d; }

    """
    BTN_SUCCESS: Final[str] = """
        QPushButton, QToolButton {
            background: #28a745; color: white; border: none;
            padding: 6px 12px; border-radius: 4px; font-weight: bold;
        }
        QPushButton:hover, QToolButton:hover { background: #218838; }

    """
    BTN_WARNING: Final[str] = """
        QPushButton {
            background: #ffc107; color: #212529; border: none;
            padding: 6px 12px; border-radius: 4px; font-weight: bold;
        }
        QPushButton:hover { background: #e0a800; }

    """
    BTN_DANGER: Final[str] = """
        QPushButton {
            background: #dc3545; color: white; border: none;
            padding: 6px 12px; border-radius: 4px;
        }
        QPushButton:hover { background: #c82333; }

    """
    BTN_INFO: Final[str] = """
        QPushButton {
            background: #17a2b8; color: white; border: none;
            padding: 6px 12px; border-radius: 4px; font-weight: bold;
        }
        QPushButton:hover { background: #138496; }

    """
    LOCK_LOCKED: Final[str] = (
        "color: #dc3545; font-weight: bold; padding: 4px 8px; "
        "background: rgba(220,53,69,0.1); border-radius: 4px;"
    )
    LOCK_UNLOCKED: Final[str] = (
        "color: #28a745; font-weight: bold; padding: 4px 8px; "
        "background: rgba(40,167,69,0.1); border-radius: 4px;"
    )
    HEADER_LABEL: Final[str] = (
        "background: #343a40; padding: 8px; border-radius: 4px; "
        "color: #ffffff; font-weight: bold;"
    )
    EMPTY_LABEL: Final[str] = (
        "color: #888; font-size: 16px; padding: 50px;"
    )
    SEARCH_INPUT: Final[str] = """
        QLineEdit {
            padding: 6px; border: 1px solid #444;
            border-radius: 4px; background: #2b2b2b;
            color: #ffffff;
        }
        QLineEdit:focus { border-color: #007bff; }

    """
STYLES: Final[Dict[str, str]] = {
    "page_title": Styles.PAGE_TITLE,
    "group_box": Styles.GROUP_BOX,
    "list_widget": Styles.LIST_WIDGET,
    "tab_widget": Styles.TAB_WIDGET,
    "btn_primary": Styles.BTN_PRIMARY,
    "btn_success": Styles.BTN_SUCCESS,
    "btn_warning": Styles.BTN_WARNING,
    "btn_danger": Styles.BTN_DANGER,
    "lock_label_locked": Styles.LOCK_LOCKED,
    "lock_label_unlocked": Styles.LOCK_UNLOCKED,
    "header_label": Styles.HEADER_LABEL,
    "empty_label": Styles.EMPTY_LABEL,
    "search_input": Styles.SEARCH_INPUT,
}

# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS

# ══════════════════════════════════════════════════════════════════════════════

def _normalize_header(name: str) -> str:

    """Normalisera Excel-rubrik för mappning."""
    if not name:
        return ""
    x = str(name).strip().upper()
    x = (
        x.replace("Å", "A").replace("Ä", "A").replace("Ö", "O")
        .replace("É", "E").replace("È", "E").replace("Ü", "U")
        .replace("Ñ", "N")
    )
    return re.sub(r"[\W_]+", "", x)

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
            if hasattr(app, candidate):
                return getattr(app, candidate)
        except Exception:
            pass
    return None

def get_ts_schema_safe(app: Any, post_type: str) -> Optional[Any]:

    """Hämta schema. Söker ts_schema_manager först."""
    for plugin_name in ("ts_schema_manager", "ts_spec_import"):
        plugin = get_plugin_safe(app, plugin_name)
        if plugin and hasattr(plugin, "get_schema"):
            try:
                schema = plugin.get_schema(str(post_type))
                if schema is not None:
                    return schema
            except Exception:
                pass
    return None

def validate_vin3(vin3: str) -> bool:

    """Validera 3-teckens VIN-kod."""
    if not vin3:
        return False
    return bool(VIN3_PATTERN.match(vin3.strip().upper()))

def extract_vin3_from_full(vin: str) -> Optional[str]:

    """
    Extrahera VIN3 (tecken 2-4) från fullständigt VIN eller VIN-prefix.
    SPEC v7.0: VINCODE-matchning använder tecken 2-4 (slice [1:4]).

    """
    if not vin:
        return None
    cleaned = re.sub(r"[^A-Z0-9]", "", vin.strip().upper())
    if len(cleaned) < 4:
        return None
    code = cleaned[1:4]
    if validate_vin3(code):
        return code
    return None

def _build_ts_field_lookup(schema: Any) -> Dict[str, Any]:

    """Bygg lookup från schema-fält."""
    lookup: Dict[str, Any] = {}
    try:
        if not hasattr(schema, "fields"):
            return lookup
        for field_spec in schema.fields:
            if hasattr(field_spec, "name"):
                lookup[str(field_spec.name).upper()] = field_spec
    except Exception:
        pass
    return lookup

# ══════════════════════════════════════════════════════════════════════════════
# COLUMN MAPPING DIALOG

# ══════════════════════════════════════════════════════════════════════════════

class ColumnMappingDialog(QDialog):

    """
    Dialog för att koppla Excel-rubriker till interna fält.
    Används i modellimportflödet FÖRE matchning mot befintlig data.
    KRAV 40/31: rubrikerna kommer från rad 1 i ALLA blad (unika, i ordning).

    """

    def __init__(
        self,
        headers: List[str],
        initial_mapping: Dict[str, str],
        target_labels: Dict[str, str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._headers = headers
        self._initial_mapping = initial_mapping
        self._target_labels = target_labels
        self._combos: List[QComboBox] = []
        self.setWindowTitle("Kolumnmappning")
        self.setMinimumSize(700, 500)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        info = QLabel(
            "Koppla varje Excel-rubrik till ett internt fält. "
            "Välj '-- inte mappad --' för kolumner som ska ignoreras.\n\n"
            "Rubrikerna kommer från rad 1 i alla blad i filen."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self._table = QTableWidget(len(self._headers), 2)
        self._table.setHorizontalHeaderLabels(["Excel-rubrik", "Målfält"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        sorted_targets = sorted(
            self._target_labels.items(),
            key=lambda item: item[1].lower(),
        )
        for row, header in enumerate(self._headers):
            header_item = QTableWidgetItem(header)
            header_item.setFlags(header_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, header_item)
            combo = QComboBox()
            combo.addItem("-- inte mappad --", "")
            for field, label in sorted_targets:
                combo.addItem(label, field)
            norm = _normalize_header(header)
            initial = self._initial_mapping.get(norm, "")
            if initial:
                idx = combo.findData(initial)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self._table.setCellWidget(row, 1, combo)
            self._combos.append(combo)
        layout.addWidget(self._table)
        # Sparalternativ
        options = QGroupBox("Sparalternativ")
        opt_layout = QFormLayout(options)
        self._save_checkbox = QCheckBox("Spara mappning för framtida import")
        self._save_checkbox.setChecked(True)
        opt_layout.addRow(self._save_checkbox)
        self._protect_checkbox = QCheckBox("Skydda mappningen med PIN")
        opt_layout.addRow(self._protect_checkbox)
        self._pin_input = QLineEdit()
        self._pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pin_input.setEnabled(False)
        self._protect_checkbox.toggled.connect(self._pin_input.setEnabled)
        opt_layout.addRow("PIN:", self._pin_input)
        layout.addWidget(options)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_mapping(self) -> Dict[str, str]:

        """Returnera {normaliserad_rubrik: internt_fält}."""
        mapping: Dict[str, str] = {}
        for header, combo in zip(self._headers, self._combos):
            field = combo.currentData()
            if field:
                mapping[_normalize_header(header)] = field
        return mapping

    def save_mapping_checked(self) -> bool:
        return self._save_checkbox.isChecked()

    def protect_checked(self) -> bool:
        return self._protect_checkbox.isChecked()

    def get_pin(self) -> str:
        return self._pin_input.text().strip()

# ══════════════════════════════════════════════════════════════════════════════
# CONFLICT RESOLUTION DIALOG

# ══════════════════════════════════════════════════════════════════════════════

class ConflictResolutionDialog(QDialog):

    """
    Dialog för att välja åtgärd per dublett-VIN3 vid import.
    Åtgärder:
      - replace: Skriv över befintlig post med den nya
      - skip:    Behåll befintlig post, hoppa över den nya
      - merge:   Slå ihop fält (nytt värde vinner om det inte är tomt)

    """

    def __init__(
        self,
        conflicts: List[Dict[str, Any]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._conflicts = conflicts
        self._actions: Dict[str, QComboBox] = {}
        self.setWindowTitle("Konflikter vid import")
        self.setMinimumSize(800, 450)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        info = QLabel(
            "Följande VIN3 finns redan i fordonsregistret. "
            "Välj åtgärd för varje rad innan importen slutförs."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self._table = QTableWidget(len(self._conflicts), 5)
        self._table.setHorizontalHeaderLabels(
            ["VIN3", "År", "Befintlig post", "Inkommande post", "Åtgärd"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for row, conflict in enumerate(self._conflicts):
            vin = conflict.get("vin_kod", "")
            year = str(conflict.get("year", ""))
            existing = conflict.get("existing", {})
            incoming = conflict.get("incoming", {})
            self._table.setItem(row, 0, QTableWidgetItem(vin))
            self._table.setItem(row, 1, QTableWidgetItem(year))
            self._table.setItem(row, 2, QTableWidgetItem(self._summary(existing)))
            self._table.setItem(row, 3, QTableWidgetItem(self._summary(incoming)))
            for col in (0, 1, 2, 3):
                item = self._table.item(row, col)
                if item:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            combo = QComboBox()
            combo.addItem("📝 Skriv över", "replace")
            combo.addItem("⏭️ Hoppa över", "skip")
            combo.addItem("🔀 Slå ihop", "merge")
            self._table.setCellWidget(row, 4, combo)
            self._actions[vin] = combo
        layout.addWidget(self._table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod

    def _summary(data: Dict[str, Any]) -> str:
        parts = [
            data.get("fabrikat", ""),
            data.get("handelsbeteckning", ""),
            data.get("typ", ""),
        ]
        text = " ".join(str(p) for p in parts if p).strip()
        return text or "-"

    def get_resolutions(self) -> Dict[str, str]:

        """Returnera {vin_kod: action}."""
        return {
            vin: combo.currentData()
            for vin, combo in self._actions.items()
        }

# ══════════════════════════════════════════════════════════════════════════════
# TEXT FILE GENERATION

# ══════════════════════════════════════════════════════════════════════════════

class GenerateTextFileDialog(QDialog):

    """
    Dialog för manuellt urval av fordonsrader som ska exporteras till textfil.
    Användaren markerar vilka rader som ska ingå. Filen skrivs atomiskt
    med semikolonseparerade värden.

    """

    def __init__(
        self,
        storage: "VehicleDataStorage",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._storage = storage
        self._rows: List[Tuple[int, Dict[str, Any], QCheckBox]] = []
        self.setWindowTitle("Generera textfil")
        self.setMinimumSize(750, 500)
        self._setup_ui()
        self._load_rows()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        info = QLabel(
            "Markera de fordon som ska ingå i textfilen. "
            "Endast markerade rader exporteras."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["", "År", "VIN", "Fabrikat", "Modell", "Typ"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)
        btn_layout = QHBoxLayout()
        self._btn_select_all = QPushButton("Markera alla")
        self._btn_select_all.clicked.connect(self._select_all)
        self._btn_deselect_all = QPushButton("Avmarkera alla")
        self._btn_deselect_all.clicked.connect(self._deselect_all)
        btn_layout.addWidget(self._btn_select_all)
        btn_layout.addWidget(self._btn_deselect_all)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setText("Generera")
        buttons.accepted.connect(self._generate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_rows(self) -> None:
        for year in sorted(self._storage.list_years()):
            for vehicle in self._storage.load_year(year):
                vin = str(vehicle.get("vin_kod", "")).strip().upper()
                if not vin:
                    continue
                row = self._table.rowCount()
                self._table.insertRow(row)
                checkbox = QCheckBox()
                checkbox.setChecked(True)
                cell = QWidget()
                hbox = QHBoxLayout(cell)
                hbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
                hbox.setContentsMargins(0, 0, 0, 0)
                hbox.addWidget(checkbox)
                self._table.setCellWidget(row, 0, cell)
                self._table.setItem(row, 1, QTableWidgetItem(str(year)))
                self._table.setItem(row, 2, QTableWidgetItem(vin))
                self._table.setItem(row, 3, QTableWidgetItem(
                    str(vehicle.get("fabrikat", ""))
                ))
                self._table.setItem(row, 4, QTableWidgetItem(
                    str(vehicle.get("handelsbeteckning", ""))
                ))
                self._table.setItem(row, 5, QTableWidgetItem(
                    str(vehicle.get("typ", ""))
                ))
                self._rows.append((year, vehicle, checkbox))
        self._table.resizeColumnsToContents()

    def _select_all(self) -> None:
        for _, _, checkbox in self._rows:
            checkbox.setChecked(True)

    def _deselect_all(self) -> None:
        for _, _, checkbox in self._rows:
            checkbox.setChecked(False)

    def _generate(self) -> None:
        selected = [
            (year, vehicle)
            for year, vehicle, checkbox in self._rows
            if checkbox.isChecked()
        ]
        if not selected:
            QMessageBox.information(
                self, "Inga rader",
                "Inga rader är markerade för export.",
            )
            return
        default_name = "fordonsdata_{}.txt".format(
            datetime.now().strftime("%Y%m%d")
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Spara textfil",
            str(Path.cwd() / default_name),
            "Textfiler (*.txt);;Alla filer (*.*)",
        )
        if not path:
            return
        try:
            _write_vehicle_text_file(Path(path), selected)
            QMessageBox.information(
                self,
                "Textfil genererad",
                "Sparade %d rader till:\n%s" % (len(selected), path),
            )
            _log.info(
                "Genererade textfil %s med %d rader",
                path, len(selected),
            )
            self.accept()
        except Exception as exc:
            _log.exception("Kunde inte spara textfil: %s", exc)
            QMessageBox.critical(
                self,
                "Fel",
                "Kunde inte spara textfil:\n%s" % exc,
            )

def _write_vehicle_text_file(
    path: Path,
    selected: List[Tuple[int, Dict[str, Any]]],
) -> None:

    """Skriv valda fordon till en semikolonseparerad textfil, atomiskt."""
    field_keys: List[str] = []
    for group_fields in FIELD_GROUPS.values():
        for key, _, _ in group_fields:
            field_keys.append(key)
    lines: List[str] = []
    lines.append("Fordonsexport;%s" % datetime.now().isoformat())
    header = ["year"] + field_keys
    lines.append(";".join(header))
    for year, vehicle in selected:
        row = [str(year)]
        for key in field_keys:
            value = str(vehicle.get(key, ""))
            value = value.replace(";", ",").replace("\n", " ").replace("\r", "")
            row.append(value)
        lines.append(";".join(row))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=".%s.tmp_" % path.name,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS

# ══════════════════════════════════════════════════════════════════════════════
__all__ = [
    # Dialoger
    "ColumnMappingDialog",
    "ConflictResolutionDialog",
    "GenerateTextFileDialog",
    # Dataclasses
    "TimerConfig",
    "FieldInfo",
    "SearchResult",
    # Enums
    "FieldType",
    "LockState",
    # Konstanter
    "TIMER_CONFIG",
    "VIN3_PATTERN",
    "VIN_INVALID_CHARS",
    "TARGET_FIELD_LABELS",
    "INTERNAL_TO_TS_FIELD_CANDIDATES",
    "DROPDOWNS",
    "FIELD_GROUPS",
    "VALIDATION",
    "DEFAULT_VEHICLE_DATA",
    "STYLES",
    "Styles",
    # Funktioner
    "validate_vin3",
    "extract_vin3_from_full",
    "get_plugin_safe",
    "get_ts_schema_safe",
    "get_copyright_string",
    "_normalize_header",
    # Metadata (v1.0.1)
    "VERSION",
    "AUTHOR",
    "_build_ts_field_lookup",
]