# -*- coding: utf-8 -*-
# plugins/vehicle_registry/plugin.py
"""
Vehicle Registry Plugin v4.6.0
Fordonsregister med VIN-validering, historik, JSON-lagring
och Excel-modellimport.
ANSVAR:
  - Fordonsdata CRUD (per årsmodell, JSON-lagring)
  - VIN-validering (ISO 3779, VIN3-extraktion tecken 2-4)
  - Registreringshistorik (per år/månad)
  - VIN3-index för snabb sökning
  - Schema-awareness (ts_schema_manager integration)
  - Export till JSON/Excel
  - GUI via VehicleDataPage (skapas via create_page)
  - Excel-modellimport via excel_importer.py
IMPORTER (EXTERNA):
  json, logging, os, re, tempfile, collections, dataclasses,
  datetime, pathlib, typing
  core.plugin_base (PluginBase)
  PySide6 (valfri, kontrolleras vid runtime)
  pandas (valfri, för Excel-export)
  .excel_importer (ExcelModelImporter, DEFAULT_COLUMN_MAPPING, ConflictAction)
PUBLIKT API:
  ─── MODELLIMPORT ───
  import_from_excel(filepath, ...)                    -> Dict[str, Any]
  preview_excel_import(filepath, ...)                 -> Dict[str, Any]
  detect_excel_headers(filepath, sheet_name)          -> Dict[str, Dict]
  suggest_column_mapping(headers, target_fields)      -> Dict[str, str]
  build_mapping_fingerprint(headers)                  -> str
  load_column_mapping_for_fingerprint(fingerprint)    -> Optional[Dict]
  verify_mapping_pin(fingerprint, pin)                -> bool
  get_column_mapping()                                -> Dict[str, str]
  set_column_mapping(mapping, fingerprint, pin, ...)  -> None
  ─── VIN LOOKUP ───
  find_vehicle_by_vin3(vin3)          -> Tuple[Optional[int], Optional[Dict]]
  find_vehicle_by_full_vin(vin)       -> Optional[Dict]
  find_vehicle_by_vin(vin)            -> Optional[Dict]  (alias)
  find_vehicle_by_vin_and_year(...)   -> Optional[Dict]
  get_vehicle(vin)                    -> Optional[Dict]  (VIN3/prefix/full VIN)
  get_vehicle_years()                 -> List[int]
  load_vehicles_for_year(year)        -> List[Dict]
  save_vehicles_for_year(year, ...)   -> None
  ─── VIN VALIDATION ───
  validate_vin(vin)                   -> Dict[str, Any]
  sanitize_vin(vin)                   -> str
  extract_vin_code(vin)               -> str
  is_valid_vin(vin)                   -> bool
  ─── REGISTRATION HISTORY ───
  is_registered(vin)                  -> bool
  register_vins(vin_list)             -> Dict
  register_multiple(vin_list)         -> Tuple[int, int]
  unregister_vin(vin)                 -> bool
  get_registration_statistics()       -> Dict
  get_recent_registrations(limit)     -> List[Dict]
  get_registered_vins()               -> List[str]
  ─── CRUD ───
  upsert(record)                      -> Dict
  delete(vin3, year)                  -> Dict
  get_by_vin3(vin3)                   -> Optional[Dict]
  get_by_modelyear(year)              -> List[Dict]
  get_all(limit)                      -> List[Dict]
  search(term, limit)                 -> List[Dict]
  get_count()                         -> int
  get_statistics()                    -> Dict
  ─── EXPORT ───
  export_to_json(filepath, year)      -> bool
  export_to_excel(filepath, year)     -> bool
  ─── SCHEMA ───
  get_schema(post_type)               -> Optional[Any]
  get_active_schema_version()         -> Optional[str]
  invalidate_schema_cache()           -> None
  ─── INDEX ───
  rebuild_index()                     -> int
  ─── GUI ───
  create_page(pin_getter)             -> Optional[QWidget]
  get_page()                          -> Optional[QWidget]
DATALAGRING (spec v1.4 / Sektion Z):
  data/vehicles/{YYYY}.json                  (fordonsdata per år)
  data/vehicle_registry/registered_vins.json (VIN-historik)
  data/vehicle_registry/index.json           (VIN3-index)
  json/mappings/column_mapping.json          (excel_importer fältmappning
                                             v1.2.0 — primär sökväg)
  json/mappings/vehicle_import_mapping.json  (dialogmappning, Sektion Q —
                                             ägs av main_gui-flödet)
  (data/vehicle_registry/column_mapping.json och
   data/mappings/vehicle_import_mapping.json läses som FALLBACK tills
   migrerade — se Sektion Z i spec v1.4.)
EVENTS SOM EMITTAS:
  vehicle_registry:vins_registered
  vehicle_registry:updated
  vehicle_registry:excel_imported
LYSSNAR PÅ:
  vehicle_registry:refresh
  ts:schema:loaded, ts:schema:version_changed
  schema:loaded, schema:version_changed
  ts_spec:imported, ts_spec:version_changed
FÖRÄNDRINGAR v4.6.0 (Session 10 — spec v1.4):
  - VERSION 4.5.0 -> 4.6.0. Hela filen omskriven ren (markdown-artefakter
    borttagna: [url]-länkar, **-markeringar, &gt;/&lt;/&amp; osv.).
  - excel_importer v1.2.0-INTEGRATION:
      * mapping_dir -> json/mappings (tidigare data/vehicle_registry).
      * NYA publika metoder: detect_excel_headers, suggest_column_mapping,
        build_mapping_fingerprint, load_column_mapping_for_fingerprint,
        verify_mapping_pin, preview_excel_import.
      * import_from_excel() stöder on_conflict, conflict_resolutions,
        dry_run, save_mapping, pin och protected (KRAV 34-39, 41-42).
      * set_column_mapping() tar fingerprint, pin och protected.
  - VehicleCache: invalidate_year(), get_loaded_years(), get_vin3_count()
    PUBLIKA — privat åtkomst borta (samma princip som get_all_vins i
    VinRegistry). get_statistics() och save_vehicles_for_year() använder
    de publika metoderna.
  - Förutsätter excel_importer.py v1.2.0 (levereras separat) med:
    detect_headers(), suggest_mapping(), build_fingerprint(),
    load_mapping_for_fingerprint(), verify_mapping_pin(), preview_file(),
    import_file(..., on_conflict, conflict_resolutions, dry_run,
    save_mapping, pin, protected) och ConflictAction.
FÖRÄNDRINGAR v4.5.0:
  - SPEC v7.0: VIN3/VINCODE-matchning använder nu TECKEN 2-4 ur VIN
    (tidigare position 5-7). Ändrat i VinValidator.validate,
    VinValidator.extract_vin3 och extract_vin3_from_full.
  - activate() respekterar nu autoload_current_year från config
  - Oanvända PySide6 widget-importer borttagna -> minimal
    availability-check (GUI ligger i main_gui)
  - NY: VinRegistry.get_all_vins() publik metod
  - get_vehicle(): VIN-prefix 4-8 tecken -> tecken 2-4 extraheras,
    exakt 3 tecken = direkt VIN3-uppslag
  - Final-omtilldelning för HAS_PYSIDE6 fixad
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""
from __future__ import annotations
import json
import logging
import os
import re
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Final, List,
    Optional, Set, Tuple,
)
from core.plugin_base import PluginBase
# Excel-modellimport
from .excel_importer import (
    ExcelModelImporter,
    DEFAULT_COLUMN_MAPPING,
    ConflictAction,
)
# PySide6 (optional) — endast availability-check.
# GUI ligger i plugins/main_gui/vehicle_registry_page.py.
try:
    from PySide6.QtWidgets import QWidget as _QWidgetCheck  # noqa: F401
    _PYSIDE6_AVAILABLE = True
except Exception:
    _PYSIDE6_AVAILABLE = False
HAS_PYSIDE6: Final[bool] = _PYSIDE6_AVAILABLE
if TYPE_CHECKING:
    from core.application import Application
# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
VERSION: Final[str] = "4.6.0"
AUTHOR: Final[str] = "Rickard Längkvist"
PLUGIN_NAME: Final[str] = "Vehicle Registry"

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def _setup_logger() -> logging.Logger:
    """Konfigurera och returnera logger. KRASCHSÄKER."""
    try:
        return logging.getLogger("vehicle_registry")
    except Exception:
        return logging.getLogger(__name__)

_log: logging.Logger = _setup_logger()
# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA EVENT NAMES
# ══════════════════════════════════════════════════════════════════════════════

class SchemaEventNames:
    """Event-namn för schema-relaterade händelser."""
    TS_SCHEMA_LOADED: Final[str] = "ts:schema:loaded"
    TS_VERSION_CHANGED: Final[str] = "ts:schema:version_changed"
    SCHEMA_LOADED: Final[str] = "schema:loaded"
    SCHEMA_VERSION_CHANGED: Final[str] = "schema:version_changed"
    TS_SPEC_IMPORTED: Final[str] = "ts_spec:imported"
    TS_SPEC_VERSION_CHANGED: Final[str] = "ts_spec:version_changed"

# ══════════════════════════════════════════════════════════════════════════════
# ROBUST HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Skriv JSON atomiskt. mkstemp→fsync→os.replace. KRASCHSÄKER."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp",
        prefix=f".{path.name}.tmp_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                data, handle, indent=2,
                ensure_ascii=False, sort_keys=True,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

def read_json_safe(path: Path, default: Any) -> Any:
    """Läs JSON kraschsäkert."""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except Exception:
        pass
    return default

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """Robust plugin-hämtning. KRASCHSÄKER."""
    if app is None:
        return None
    normalized = name.replace("-", "_").lower()
    for candidate in (name, normalized):
        try:
            gp = getattr(app, "get_plugin", None)
            if callable(gp):
                plugin = gp(candidate)
                if plugin is not None:
                    return plugin
        except Exception:
            pass
        try:
            loader = getattr(app, "plugin_loader", None)
            if loader and hasattr(loader, "get_plugin"):
                plugin = loader.get_plugin(candidate)
                if plugin is not None:
                    return plugin
        except Exception:
            pass
        try:
            manager = getattr(app, "plugin_manager", None)
            if manager and hasattr(manager, "get_plugin"):
                plugin = manager.get_plugin(candidate)
                if plugin is not None:
                    return plugin
        except Exception:
            pass
        try:
            if hasattr(app, candidate):
                plugin = getattr(app, candidate)
                if plugin is not None:
                    return plugin
        except Exception:
            pass
    return None

def get_event_bus(app: Any) -> Optional[Any]:
    """Hämta event bus. KRASCHSÄKER."""
    if app is None:
        return None
    for attr in ("event_bus", "events"):
        try:
            bus = getattr(app, attr, None)
            if bus is not None:
                return bus
        except Exception:
            pass
    return None

def subscribe_event_safe(
    app: Any, event_name: str, handler: Callable
) -> bool:
    """Prenumerera event. KRASCHSÄKER."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        for method in ("on", "subscribe"):
            func = getattr(bus, method, None)
            if callable(func):
                func(event_name, handler)
                return True
    except Exception:
        pass
    return False

def unsubscribe_event_safe(
    app: Any, event_name: str, handler: Callable
) -> bool:
    """Avprenumerera event. KRASCHSÄKER."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        for method in ("off", "unsubscribe"):
            func = getattr(bus, method, None)
            if callable(func):
                func(event_name, handler)
                return True
    except Exception:
        pass
    return False

def emit_event_safe(
    app: Any, event_name: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Emit event. KRASCHSÄKER."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        for method in ("emit", "publish"):
            func = getattr(bus, method, None)
            if callable(func):
                func(event_name, data or {})
                return True
    except Exception:
        pass
    return False

def get_config_value(
    app: Any, key: str, default: Any = None
) -> Any:
    """Hämta config-värde. KRASCHSÄKER."""
    cfg = getattr(app, "config", None)
    if cfg is not None:
        try:
            if hasattr(cfg, "get") and callable(cfg.get):
                value = cfg.get(key, default)
                return default if value is None else value
            if isinstance(cfg, dict):
                value = cfg.get(key, default)
                return default if value is None else value
        except Exception:
            pass
    core_cfg = get_plugin_safe(app, "core_config")
    if core_cfg is not None:
        for method in ("get_config_value", "get"):
            try:
                getter = getattr(core_cfg, method, None)
                if callable(getter):
                    value = getter(key, default)
                    return default if value is None else value
            except Exception:
                pass
    return default

def get_ts_schema_safe(app: Any, post_type: str) -> Optional[Any]:
    """Hämta schema. Prioriterar ts_schema_manager. KRASCHSÄKER."""
    for plugin_name in ("ts_schema_manager", "ts_spec_import"):
        plugin = get_plugin_safe(app, plugin_name)
        if plugin is not None:
            try:
                getter = getattr(plugin, "get_schema", None)
                if callable(getter):
                    schema = getter(str(post_type))
                    if schema is not None:
                        return schema
            except Exception:
                pass
    return None

def get_active_schema_version_safe(app: Any) -> Optional[str]:
    """Hämta aktiv schema-version. KRASCHSÄKER."""
    for plugin_name in ("ts_schema_manager", "ts_spec_import"):
        plugin = get_plugin_safe(app, plugin_name)
        if plugin is not None:
            try:
                getter = getattr(plugin, "get_active_version", None)
                if callable(getter):
                    version = getter()
                    if version is not None:
                        return str(version)
            except Exception:
                pass
            try:
                av = getattr(plugin, "active_version", None)
                if av is not None:
                    return str(av)
            except Exception:
                pass
    return None

# ══════════════════════════════════════════════════════════════════════════════
# VIN KONSTANTER
# ══════════════════════════════════════════════════════════════════════════════
AUTOLOCK_MS: Final[int] = 10 * 60 * 1000
VIN_LENGTH: Final[int] = 17
VIN_INVALID_CHARS: Final[Set[str]] = {"I", "O", "Q"}
VIN_PATTERN: Final[re.Pattern] = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
VIN3_PATTERN: Final[re.Pattern] = re.compile(r"^[A-Z0-9]{3}$")
DEFAULT_ENCODING: Final[str] = "utf-8"
# SPEC v7.0: VINCODE-matchning använder tecken 2-4 ur VIN
# (1-indexerade positioner 2, 3 och 4 = Python-slice [1:4]).
VIN3_SLICE_START: Final[int] = 1
VIN3_SLICE_END: Final[int] = 4
MODEL_COLUMNS: Final[List[str]] = [
    "MODELYEAR", "TYPE", "VARIANTE", "VERSION", "MODELNAME",
    "COMNAME", "CLASS", "VEHCAT2", "APPROVAL", "DATEAPP",
    "NUMAXLE", "NUMWHEEL", "ANTILBS", "LENGTH", "WIDTH",
    "HEIGHT", "MASS", "LADENMASS", "CYLCAPACITY", "MAXPOWER",
    "MAXNET", "WORK_PR", "FUEL", "SPEED", "TYRESIZE1",
    "TYRESIZE2", "SEATS", "EMISLVL", "STATIONARY", "STATENG",
    "DRIVEBY", "EMSTAGE", "EECO2E",
]
SEARCHABLE_COLUMNS: Final[List[str]] = [
    "VINCODE", "MODELNAME", "COMNAME", "TYPE", "APPROVAL",
]
DROPDOWNS: Final[Dict[str, List[str]]] = {
    "bransle1": [
        "BENSIN", "DIESEL", "EL", "ETANOL",
        "HYBRID", "GAS", "VÄTGAS",
    ],
    "bransle2": [
        "-", "BENSIN", "DIESEL", "EL",
        "ETANOL", "HYBRID", "GAS",
    ],
    "bromsar": [
        "ABS", "EBS", "CBS", "ABS+CBS",
        "Hydraulisk", "Mekanisk",
    ],
    "euroklass": [
        "1", "2", "3", "4", "5", "5+", "6", "6+", "7",
    ],
    "fordonskategori": [
        "L1E-A", "L1E-B", "L2E", "L3E-A1", "L3E-A2",
        "L3E-A3", "L4E", "L5E", "L6E", "L7E", "M1", "N1",
    ],
    "skyltformat_bak": [
        "Enradig 520x110", "Tvåradig 170x150", "Liten 300x110",
    ],
    "bestallning_regbevis": ["Nej", "Ja"],
    "kommissionssparr": ["N", "J"],
}
FIELD_GROUPS: Final = OrderedDict([
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
VALIDATION: Final[Dict[str, Dict[str, Any]]] = {
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
    "effekt_kw": {"type": "float", "min": 0.1, "max": 2000},
    "varvtal_effekt_1": {"type": "int", "min": 500, "max": 20000},
    "max_hastighet_kmh": {"type": "int", "min": 25, "max": 500},
    "euroklass": {"type": "dropdown", "required": True},
    "bransle1": {"type": "dropdown", "required": True},
}
# ══════════════════════════════════════════════════════════════════════════════
# VIN VALIDATOR
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class VinValidationResult:
    """Resultat av VIN-validering."""
    valid: bool
    vin: str
    error: Optional[str] = None
    vin_code: Optional[str] = None
    vin3: Optional[str] = None
    manufacturer: Optional[str] = None
    year_code: Optional[str] = None
    country: Optional[str] = None
    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid, "vin": self.vin,
            "error": self.error, "vin_code": self.vin_code,
            "vin3": self.vin3, "manufacturer": self.manufacturer,
            "year_code": self.year_code, "country": self.country,
        }

class VinValidator:
    """VIN-validator enligt ISO 3779."""
    MANUFACTURERS: Final[Dict[str, str]] = {
        "WVW": "Volkswagen", "WV2": "Volkswagen Commercial",
        "WAU": "Audi", "WUA": "Audi Quattro",
        "WBA": "BMW", "WBS": "BMW M",
        "WDB": "Mercedes-Benz", "WDD": "Mercedes-Benz",
        "WDC": "Mercedes-Benz", "WF0": "Ford Germany",
        "WP0": "Porsche", "WP1": "Porsche SUV",
        "YV1": "Volvo", "YV4": "Volvo", "YS3": "Saab",
        "SAJ": "Jaguar", "SAL": "Land Rover",
        "SCC": "Lotus", "SCF": "Aston Martin",
        "ZFA": "Fiat", "ZFF": "Ferrari",
        "ZAM": "Maserati", "ZLA": "Lancia",
        "ZAR": "Alfa Romeo",
        "VF1": "Renault", "VF3": "Peugeot", "VF7": "Citroën",
        "JTD": "Toyota", "JTE": "Toyota", "JTM": "Toyota",
        "JHM": "Honda", "JN1": "Nissan", "JN8": "Nissan",
        "JMZ": "Mazda", "JS3": "Suzuki",
        "1G1": "Chevrolet", "1FA": "Ford", "1FM": "Ford",
        "2HG": "Honda USA", "5YJ": "Tesla",
        "KMH": "Hyundai", "KNA": "Kia", "KND": "Kia",
        "TRU": "Audi Hungary", "TMB": "Škoda",
        "VSS": "SEAT", "VS6": "Ford Spain",
        "JYA": "Yamaha", "JKA": "Kawasaki",
        "JH2": "Honda MC", "JS1": "Suzuki MC",
        "SMT": "Triumph", "ZDM": "Ducati",
        "1HD": "Harley-Davidson", "5HD": "Harley-Davidson",
        "WB1": "BMW Motorrad", "VG5": "MBK",
        "ZES": "Harley-Davidson EU",
    }
    COUNTRY_CODES: Final[Dict[str, str]] = {
        "A": "Sydafrika", "J": "Japan", "K": "Korea",
        "L": "Kina", "S": "Storbritannien",
        "V": "Frankrike/Spanien", "W": "Tyskland",
        "X": "Ryssland", "Y": "Sverige/Finland",
        "Z": "Italien", "1": "USA", "2": "Kanada",
        "3": "Mexiko", "4": "USA", "5": "USA",
        "6": "Australien", "9": "Brasilien",
    }
    YEAR_CODES: Final[Dict[str, int]] = {
        "A": 2010, "B": 2011, "C": 2012, "D": 2013,
        "E": 2014, "F": 2015, "G": 2016, "H": 2017,
        "J": 2018, "K": 2019, "L": 2020, "M": 2021,
        "N": 2022, "P": 2023, "R": 2024, "S": 2025,
        "T": 2026, "V": 2027, "W": 2028, "X": 2029,
        "Y": 2030,
        "1": 2001, "2": 2002, "3": 2003, "4": 2004,
        "5": 2005, "6": 2006, "7": 2007, "8": 2008,
        "9": 2009,
    }
    @classmethod
    def validate(cls, vin: str) -> VinValidationResult:
        """Validera ett VIN-nummer."""
        if not vin:
            return VinValidationResult(False, "", "VIN saknas")
        clean_vin = re.sub(r"[^A-Z0-9]", "", vin.strip().upper())
        if len(clean_vin) != VIN_LENGTH:
            return VinValidationResult(
                False, clean_vin,
                f"Fel längd: {len(clean_vin)} (ska vara {VIN_LENGTH})",
            )
        invalid = set(clean_vin) & VIN_INVALID_CHARS
        if invalid:
            return VinValidationResult(
                False, clean_vin,
                f"Ogiltiga tecken: {', '.join(sorted(invalid))} "
                f"(I, O, Q ej tillåtna)",
            )
        if not VIN_PATTERN.match(clean_vin):
            return VinValidationResult(
                False, clean_vin,
                "VIN matchar ej ISO 3779-format",
            )
        wmi = clean_vin[:3]
        vin_code = clean_vin[3:11]
        # SPEC v7.0: VIN3 = tecken 2-4 (slice [1:4])
        vin3 = clean_vin[VIN3_SLICE_START:VIN3_SLICE_END]
        year_char = clean_vin[9]
        manufacturer = cls.MANUFACTURERS.get(
            wmi, cls.MANUFACTURERS.get(wmi[:2], "Okänd")
        )
        country = cls.COUNTRY_CODES.get(clean_vin[0], "Okänt")
        model_year = cls.YEAR_CODES.get(year_char)
        return VinValidationResult(
            valid=True, vin=clean_vin,
            vin_code=vin_code, vin3=vin3,
            manufacturer=manufacturer,
            year_code=str(model_year) if model_year else None,
            country=country,
        )
    @classmethod
    def is_valid(cls, vin: str) -> bool:
        """Snabbkontroll om VIN är giltigt."""
        return cls.validate(vin).valid
    @classmethod
    def sanitize(cls, vin: str) -> str:
        """Rensa och normalisera VIN."""
        if not vin:
            return ""
        return re.sub(r"[^A-Z0-9]", "", vin.strip().upper())
    @classmethod
    def extract_vin_code(cls, vin: str) -> str:
        """Extrahera VIN-kod (position 4-11)."""
        return cls.validate(vin).vin_code or ""
    @classmethod
    def extract_vin3(cls, vin: str) -> str:
        """Extrahera VIN3-kod (tecken 2-4 enligt spec v7.0)."""
        return cls.validate(vin).vin3 or ""
    @classmethod
    def get_model_year(cls, vin: str) -> Optional[int]:
        """Extrahera årsmodell från VIN."""
        clean = cls.sanitize(vin)
        if len(clean) >= 10:
            return cls.YEAR_CODES.get(clean[9].upper())
        return None

def normalize_model_year(value: Any) -> str:
    """Normalisera årsmodell till YYYY-format."""
    if value is None:
        return ""
    s = str(value).strip().upper()
    if not s or s in ("NAN", "NONE", "NULL", ""):
        return ""
    if re.fullmatch(r"20\d{2}", s):
        return s
    my_match = re.search(r"MY\s*(\d{2,4})", s, re.IGNORECASE)
    if my_match:
        year_str = my_match.group(1)
        if len(year_str) == 2:
            return f"20{year_str}"
        return year_str
    m2 = re.search(r"\b(\d{2})\b", s)
    if m2:
        yy = int(m2.group(1))
        return f"20{yy:02d}"
    try:
        val = int(float(s.replace(",", ".")))
        if 2000 <= val <= 2099:
            return str(val)
        if 0 <= val <= 99:
            return f"20{val:02d}"
    except Exception:
        pass
    m4 = re.search(r"\b(20\d{2})\b", s)
    if m4:
        return m4.group(1)
    return ""

def validate_vin3(vin3: str) -> bool:
    """Validera en VIN3-kod."""
    return bool(vin3 and VIN3_PATTERN.match(vin3.strip().upper()))

def extract_vin3_from_full(vin: str) -> Optional[str]:
    """
    Extrahera VIN3 från ett fullständigt VIN eller VIN-prefix.
    SPEC v7.0: VINCODE-matchning använder tecken 2-4 ur VIN
    (1-indexerade positioner 2, 3, 4 = slice [1:4]).
    Kräver minst 4 tecken i indata.
    """
    if not vin:
        return None
    clean = VinValidator.sanitize(vin)
    if len(clean) >= VIN3_SLICE_END:
        code = clean[VIN3_SLICE_START:VIN3_SLICE_END]
        if validate_vin3(code):
            return code
    return None

# ══════════════════════════════════════════════════════════════════════════════
# VIN REGISTRY (File-based)
# ══════════════════════════════════════════════════════════════════════════════

class VinRegistry:
    """Filbaserad historik över registrerade VIN."""
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._cache: Optional[Dict[str, Dict[str, List[str]]]] = None
        self._flat_cache: Optional[Set[str]] = None
    def invalidate_cache(self) -> None:
        self._cache = None
        self._flat_cache = None
    def is_registered(self, vin: str) -> bool:
        self._load()
        return VinValidator.sanitize(vin) in (self._flat_cache or set())
    def register_multiple(self, vin_list: List[str]) -> Tuple[int, int]:
        self._load()
        now = datetime.now()
        year, month = str(now.year), f"{now.month:02d}"
        if self._cache is None:
            self._cache = {}
        self._cache.setdefault(year, {}).setdefault(month, [])
        registered = skipped = 0
        for vin in vin_list:
            clean = VinValidator.sanitize(vin)
            if not VinValidator.is_valid(clean) or clean in (self._flat_cache or set()):
                skipped += 1
                continue
            self._cache[year][month].append(clean)
            if self._flat_cache is not None:
                self._flat_cache.add(clean)
            registered += 1
        if registered > 0:
            self._save()
        return registered, skipped
    def unregister(self, vin: str) -> bool:
        self._load()
        clean = VinValidator.sanitize(vin)
        if clean not in (self._flat_cache or set()):
            return False
        for yd in (self._cache or {}).values():
            for ml in (yd or {}).values():
                if isinstance(ml, list) and clean in ml:
                    ml.remove(clean)
                    if self._flat_cache:
                        self._flat_cache.discard(clean)
                    self._save()
                    return True
        return False
    def get_all_vins(self) -> List[str]:
        """
        Publik metod som returnerar alla registrerade VIN
        sorterade. Ersätter extern åtkomst till privata _load()/
        _flat_cache.
        """
        self._load()
        return sorted(self._flat_cache or set())
    def get_statistics(self) -> Dict[str, Any]:
        self._load()
        now = datetime.now()
        total = len(self._flat_cache or set())
        yd = (self._cache or {}).get(str(now.year), {})
        this_year = sum(len(v) for v in yd.values() if isinstance(v, list))
        this_month = len(yd.get(f"{now.month:02d}", []))
        per_year: Dict[str, int] = {}
        for y, months in (self._cache or {}).items():
            if str(y).startswith("_"):
                continue
            if isinstance(months, dict):
                per_year[str(y)] = sum(
                    len(v) for v in months.values() if isinstance(v, list)
                )
        return {
            "total": total,
            "this_year": this_year,
            "this_month": this_month,
            "per_year": per_year,
        }
    def get_recent(self, limit: int = 50) -> List[Dict[str, str]]:
        self._load()
        recent: List[Dict[str, str]] = []
        for year in sorted((self._cache or {}).keys(), reverse=True):
            if str(year).startswith("_"):
                continue
            months = (self._cache or {}).get(year, {})
            if not isinstance(months, dict):
                continue
            for month in sorted(months.keys(), reverse=True):
                for vin in reversed(months.get(month, [])):
                    v = VinValidator.validate(vin)
                    recent.append({
                        "date": f"{year}-{month}",
                        "vin": vin,
                        "manufacturer": v.manufacturer or "Okänd",
                    })
                    if len(recent) >= limit:
                        return recent
        return recent
    def _load(self) -> None:
        if self._cache is not None:
            return
        data = read_json_safe(self.file_path, {})
        self._cache = data.get("registered_vins", data) if isinstance(data, dict) else {}
        self._flat_cache = set()
        for yd in (self._cache or {}).values():
            if isinstance(yd, dict):
                for ml in yd.values():
                    if isinstance(ml, list):
                        self._flat_cache.update(v.upper() for v in ml)
    def _save(self) -> None:
        atomic_write_json(self.file_path, {
            "registered_vins": self._cache or {},
            "_meta": {
                "updated_at": datetime.now().isoformat(),
                "total_count": len(self._flat_cache or set()),
            },
        })

# ══════════════════════════════════════════════════════════════════════════════
# VEHICLE DATA STORAGE
# ══════════════════════════════════════════════════════════════════════════════

class VehicleDataStorage:
    """Hanterar fordonsdata i JSON-filer per år."""
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir / "vehicles"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._index: Optional[Dict[str, int]] = None
        self._index_path = base_dir / "vehicle_registry" / "index.json"
    def _year_path(self, year: int) -> Path:
        return self.base_dir / f"{year}.json"
    def load_year(self, year: int) -> List[Dict[str, Any]]:
        path = self._year_path(year)
        if not path.exists():
            return []
        data = read_json_safe(path, [])
        if isinstance(data, dict) and "vehicles" in data:
            v = data.get("vehicles", [])
            return v if isinstance(v, list) else []
        return data if isinstance(data, list) else []
    def save_year(
        self, year: int, vehicles: List[Dict[str, Any]],
        version: str = "1.0",
    ) -> None:
        valid = [
            {k: v for k, v in veh.items() if not str(k).startswith("_")}
            for veh in vehicles
            if isinstance(veh, dict) and veh.get("vin_kod")
        ]
        atomic_write_json(self._year_path(year), {
            "vehicles": valid,
            "_meta": {
                "year": year,
                "count": len(valid),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "version": version,
            },
        })
        self._update_index(year, valid)
    def list_years(self) -> List[int]:
        years: List[int] = []
        for fp in self.base_dir.glob("*.json"):
            try:
                y = int(fp.stem)
                if 1900 <= y <= 2200:
                    years.append(y)
            except ValueError:
                pass
        return sorted(set(years))
    def find_by_vin3(
        self, vin3: str
    ) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        cv = vin3.strip().upper()
        self._load_index()
        if self._index and cv in self._index:
            year = self._index[cv]
            for v in self.load_year(year):
                if str(v.get("vin_kod", "")).strip().upper() == cv:
                    return year, v.copy()
        for year in reversed(self.list_years()):
            for v in self.load_year(year):
                if str(v.get("vin_kod", "")).strip().upper() == cv:
                    return year, v.copy()
        return None, None
    def find_years_by_vin3(self, vin3: str) -> List[int]:
        cv = vin3.strip().upper()
        return [
            y for y in self.list_years()
            if any(
                str(v.get("vin_kod", "")).strip().upper() == cv
                for v in self.load_year(y)
            )
        ]
    def find_by_full_vin(self, vin: str) -> Optional[Dict[str, Any]]:
        vin3 = extract_vin3_from_full(vin)
        if not vin3:
            return None
        _, v = self.find_by_vin3(vin3)
        return v
    def _load_index(self) -> None:
        if self._index is not None:
            return
        data = read_json_safe(self._index_path, {})
        self._index = data.get("vin3_to_year", {}) if isinstance(data, dict) else {}
    def _update_index(
        self, year: int, vehicles: List[Dict[str, Any]]
    ) -> None:
        self._load_index()
        if self._index is None:
            self._index = {}
        for v in vehicles:
            vin3 = str(v.get("vin_kod", "")).strip().upper()
            if vin3:
                self._index[vin3] = year
        atomic_write_json(self._index_path, {
            "vin3_to_year": self._index,
            "_meta": {
                "updated_at": datetime.now().isoformat(),
                "count": len(self._index),
            },
        })
    def rebuild_index(self) -> int:
        self._index = {}
        count = 0
        for year in self.list_years():
            for v in self.load_year(year):
                vin3 = str(v.get("vin_kod", "")).strip().upper()
                if vin3:
                    self._index[vin3] = year
                    count += 1
        atomic_write_json(self._index_path, {
            "vin3_to_year": self._index,
            "_meta": {
                "updated_at": datetime.now().isoformat(),
                "count": count,
                "rebuilt": True,
            },
        })
        return count

class VehicleCache:
    """In-memory cache för snabb uppslag."""
    def __init__(self, storage: VehicleDataStorage) -> None:
        self._storage = storage
        self._by_vin3: Dict[str, Tuple[int, Dict[str, Any]]] = {}
        self._by_approval: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
        self._loaded_years: Set[int] = set()
    def load_year(self, year: int) -> None:
        if year in self._loaded_years:
            return
        for v in self._storage.load_year(year):
            vin3 = str(v.get("vin_kod", "")).strip().upper()
            if vin3:
                self._by_vin3[vin3] = (year, v)
            appr = str(v.get("avgaskrav_tillagg", "") or "").strip().upper()
            if appr:
                self._by_approval.setdefault(appr, []).append((year, v))
        self._loaded_years.add(year)
    def load_all(self) -> None:
        for y in self._storage.list_years():
            self.load_year(y)
    def find_by_vin3(
        self, vin3: str
    ) -> Optional[Tuple[int, Dict[str, Any]]]:
        return self._by_vin3.get(vin3.strip().upper())
    def find_by_approval(
        self, approval: str
    ) -> List[Tuple[int, Dict[str, Any]]]:
        return self._by_approval.get(approval.strip().upper(), [])
    def invalidate(self) -> None:
        self._by_vin3.clear()
        self._by_approval.clear()
        self._loaded_years.clear()
    def invalidate_year(self, year: int) -> None:
        """
        Invalidera enbart ett års poster ur cachen (publik v4.6.0).
        Behåller övriga år — snabbare än full invalidate vid sparning.
        """
        self._loaded_years.discard(year)
        stale_vin3 = [
            key for key, (y, _v) in self._by_vin3.items() if y == year
        ]
        for key in stale_vin3:
            del self._by_vin3[key]
        stale_approval = [
            key for key, entries in self._by_approval.items()
            if any(y == year for y, _v in entries)
        ]
        for key in stale_approval:
            remaining = [e for e in self._by_approval[key] if e[0] != year]
            if remaining:
                self._by_approval[key] = remaining
            else:
                del self._by_approval[key]
    def get_loaded_years(self) -> List[int]:
        """Returnera cachade år (sorterade). Publik v4.6.0."""
        return sorted(self._loaded_years)
    def get_vin3_count(self) -> int:
        """Antal VIN3-poster i cache. Publik v4.6.0."""
        return len(self._by_vin3)

# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    Vehicle Registry Plugin v4.6.0
    KONTRAKT (PluginBase):
      init()              - initiera plugin
      register_ui(parent) - returnerar None (GUI via create_page)
      shutdown()          - städa upp
      config_schema()     - returnera schema
    """
    NAME: Final[str] = PLUGIN_NAME
    VERSION: Final[str] = VERSION
    DESCRIPTION: Final[str] = (
        "Fordonsregister med VIN-validering, JSON-lagring och Excel-import"
    )
    AUTHOR: Final[str] = AUTHOR
    COPYRIGHT: Final[str] = get_copyright_string()
    DEPENDENCIES: Final[List[str]] = []
    def __init__(self, app: "Application") -> None:
        super().__init__(app)
        self.vin_registry: Optional[VinRegistry] = None
        self.vehicle_storage: Optional[VehicleDataStorage] = None
        self.vehicle_cache: Optional[VehicleCache] = None
        self._paths: Dict[str, Path] = {}
        self._page: Optional[Any] = None
        self._event_handlers: List[Tuple[str, Callable]] = []
        self._cached_schema_version: Optional[str] = None
        self._excel_importer: Optional[ExcelModelImporter] = None
        self.normalize_model_year = normalize_model_year
        self.validate_vin3 = validate_vin3
        self.extract_vin3_from_full = extract_vin3_from_full
    # ──────────────────────────────────────────────────────────────────
    # PLUGINBASE KONTRAKT
    # ──────────────────────────────────────────────────────────────────
    def init(self) -> bool:
        """Initiera plugin. KRASCHSÄKER."""
        try:
            self._setup_paths()
            self.vin_registry = VinRegistry(
                self._paths["data"] / "registered_vins.json"
            )
            self.vehicle_storage = VehicleDataStorage(
                self._paths["base"]
            )
            self.vehicle_cache = VehicleCache(
                self.vehicle_storage
            )
            # spec v1.4 / Sektion Z: mappnings-JSON under json/mappings/
            self._excel_importer = ExcelModelImporter(
                vehicle_storage=self.vehicle_storage,
                mapping_dir=self._paths["json_mappings"],
            )
            try:
                self.app.vehicle_registry = self
            except Exception:
                pass
            _log.info(
                "✅ %s v%s initierad", PLUGIN_NAME, VERSION,
            )
            return True
        except Exception as exc:
            _log.error(
                "Kunde inte initiera %s: %s",
                PLUGIN_NAME, exc, exc_info=True,
            )
            return False
    def register_ui(self, parent: Any) -> None:
        """Ingen standardflik — GUI via create_page()."""
        return None
    def shutdown(self) -> bool:
        """Städa upp resurser. KRASCHSÄKER."""
        try:
            for event_name, handler in self._event_handlers:
                unsubscribe_event_safe(
                    self.app, event_name, handler
                )
            self._event_handlers.clear()
            _log.info(
                "✓ %s deaktiverad", PLUGIN_NAME,
            )
            return True
        except Exception as exc:
            _log.error(
                "Shutdown misslyckades: %s",
                exc, exc_info=True,
            )
            return False
    def config_schema(self) -> Dict[str, Any]:
        """Returnera plugin-konfiguration."""
        return {
            "plugin": PLUGIN_NAME,
            "version": VERSION,
            "author": AUTHOR,
            "copyright": get_copyright_string(),
            "settings": {
                "autoload_current_year": {
                    "type": "boolean",
                    "default": True,
                    "description": "Ladda aktuellt år vid aktivering.",
                },
            },
        }
    # ──────────────────────────────────────────────────────────────────
    # BAKÅTKOMPATIBILITET
    # ──────────────────────────────────────────────────────────────────
    def initialize(self) -> bool:
        return self.init()
    def activate(self) -> bool:
        events = [
            ("vehicle_registry:refresh", self._on_refresh),
            (SchemaEventNames.TS_SCHEMA_LOADED, self._on_schema_changed),
            (SchemaEventNames.TS_VERSION_CHANGED, self._on_schema_changed),
            (SchemaEventNames.SCHEMA_LOADED, self._on_schema_changed),
            (SchemaEventNames.SCHEMA_VERSION_CHANGED, self._on_schema_changed),
            (SchemaEventNames.TS_SPEC_IMPORTED, self._on_schema_changed),
            (SchemaEventNames.TS_SPEC_VERSION_CHANGED, self._on_schema_changed),
        ]
        for en, h in events:
            if subscribe_event_safe(self.app, en, h):
                self._event_handlers.append((en, h))
        autoload = bool(get_config_value(
            self.app, "autoload_current_year", True,
        ))
        if autoload:
            try:
                if self.vehicle_cache:
                    self.vehicle_cache.load_year(datetime.now().year)
            except Exception:
                pass
        self._cached_schema_version = get_active_schema_version_safe(self.app)
        _log.info(
            "✓ %s aktiverad (schema: %s, autoload: %s)",
            PLUGIN_NAME,
            self._cached_schema_version or "none",
            autoload,
        )
        return True
    def deactivate(self) -> bool:
        return self.shutdown()
    # ──────────────────────────────────────────────────────────────────
    # INTERN SETUP
    # ──────────────────────────────────────────────────────────────────
    def _setup_paths(self) -> None:
        project_root = Path(get_config_value(self.app, "base_dir", ".") or ".")
        data_dir = project_root / "data"
        json_dir = project_root / "json"
        self._paths = {
            "root": project_root,
            "base": data_dir,
            "data": data_dir / "vehicle_registry",
            "vehicles": data_dir / "vehicles",
            "json": json_dir,
            "json_mappings": json_dir / "mappings",
        }
        for p in self._paths.values():
            p.mkdir(parents=True, exist_ok=True)
    def _on_refresh(self, data: Optional[Dict[str, Any]] = None) -> None:
        if self.vin_registry:
            self.vin_registry.invalidate_cache()
        if self.vehicle_cache:
            self.vehicle_cache.invalidate()
    def _on_schema_changed(
        self, event: Optional[Dict[str, Any]] = None
    ) -> None:
        event = event or {}
        version = (
            event.get("version") or event.get("new_version")
            or event.get("active_version")
            or get_active_schema_version_safe(self.app)
        )
        old = self._cached_schema_version
        self._cached_schema_version = version
        if old != version:
            _log.info("Schema uppdaterat: %s -> %s", old, version)
        self.invalidate_schema_cache()
    # ──────────────────────────────────────────────────────────────────
    # EXCEL MODELLIMPORT
    # ──────────────────────────────────────────────────────────────────
    def detect_excel_headers(
        self,
        filepath: str,
        sheet_name: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Detektera rad 1-rubriker per blad."""
        if not self._excel_importer:
            return {}
        return self._excel_importer.detect_headers(filepath, sheet_name)
    def suggest_column_mapping(
        self,
        headers: List[str],
        target_fields: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Föreslå mappning för en lista med Excel-rubriker."""
        if not self._excel_importer:
            return {}
        return self._excel_importer.suggest_mapping(headers, target_fields)
    def build_mapping_fingerprint(self, headers: List[str]) -> str:
        """Bygg fingerprint för en rubrikuppsättning."""
        if not self._excel_importer:
            return ""
        return self._excel_importer.build_fingerprint(headers)
    def load_column_mapping_for_fingerprint(
        self, fingerprint: str
    ) -> Optional[Dict[str, str]]:
        """Ladda sparad mappning för ett fingerprint."""
        if not self._excel_importer:
            return None
        return self._excel_importer.load_mapping_for_fingerprint(fingerprint)
    def verify_mapping_pin(self, fingerprint: str, pin: str) -> bool:
        """Verifiera PIN för en sparad mappning."""
        if not self._excel_importer:
            return False
        return self._excel_importer.verify_mapping_pin(fingerprint, pin)
    def preview_excel_import(
        self,
        filepath: str,
        column_mapping: Optional[Dict[str, str]] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Torrkörning av Excel-import. Returnerar förhandsgranskning,
        konflikter och fingerprint utan att spara.
        """
        if not self._excel_importer:
            return {"success": False, "errors": ["Excel-importer ej initierad"]}
        return self._excel_importer.preview_file(
            filepath,
            column_mapping=column_mapping,
            progress_callback=progress_callback,
        )
    def import_from_excel(
        self,
        filepath: str,
        column_mapping: Optional[Dict[str, str]] = None,
        on_conflict: str = ConflictAction.REPLACE,
        conflict_resolutions: Optional[Dict[str, str]] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        dry_run: bool = False,
        save_mapping: bool = True,
        pin: Optional[str] = None,
        protected: bool = False,
    ) -> Dict[str, Any]:
        """
        Importera modelldata från Excel till vehicle_registry.
        Delegerar till ExcelModelImporter (excel_importer.py v1.2.0).
        Stöder VINCODE som VIN-prefix (3-8 tecken).
        OBS SPEC v7.0: VINCODE-matchning ska använda tecken 2-4 —
        excel_importer.py MÅSTE använda samma extraktion som
        extract_vin3_from_full() i denna modul.
        Args:
            filepath:             Sökväg till .xlsx/.xls/.xlsm
            column_mapping:       Custom mappning (None = sparad/default)
            on_conflict:          "replace" | "skip" | "merge" | "ask"
            conflict_resolutions: Dict {vin_kod: action} för specifika val.
            progress_callback:    Callback(msg) för progress
            dry_run:              Om True sparas inget.
            save_mapping:         Spara mappning under fingerprint.
            pin:                  PIN om mappningen ska/är skyddad.
            protected:            Skydda mappningen med PIN.
        Returns:
            Dict med success, imported, updated, skipped, errors, years,
            conflicts, needs_resolution, fingerprint, mapping_used.
        """
        if not self._excel_importer:
            return {"success": False, "errors": ["Excel-importer ej initierad"]}
        if column_mapping:
            self._excel_importer.set_column_mapping(column_mapping)
        result = self._excel_importer.import_file(
            filepath=filepath,
            column_mapping=column_mapping,
            on_conflict=on_conflict,
            conflict_resolutions=conflict_resolutions,
            progress_callback=progress_callback,
            dry_run=dry_run,
            save_mapping=save_mapping,
            pin=pin,
            protected=protected,
        )
        if self.vehicle_cache and (result.get("success") or result.get("needs_resolution")):
            self.vehicle_cache.invalidate()
        if result.get("success"):
            emit_event_safe(self.app, "vehicle_registry:excel_imported", {
                "imported": result.get("imported", 0),
                "updated": result.get("updated", 0),
                "years": result.get("years", []),
                "filepath": str(filepath),
            })
        return result
    def get_column_mapping(self) -> Dict[str, str]:
        """Hämta aktuell kolumnmappning (Excel -> internt fält)."""
        if self._excel_importer:
            return self._excel_importer.get_column_mapping()
        return dict(DEFAULT_COLUMN_MAPPING)
    def set_column_mapping(
        self,
        mapping: Dict[str, str],
        fingerprint: Optional[str] = None,
        pin: Optional[str] = None,
        protected: bool = False,
    ) -> None:
        """Sätt kolumnmappning och spara persistent."""
        if self._excel_importer:
            self._excel_importer.set_column_mapping(
                mapping,
                fingerprint=fingerprint,
                pin=pin,
                protected=protected,
            )
    # ──────────────────────────────────────────────────────────────────
    # GUI
    # ──────────────────────────────────────────────────────────────────
    def create_page(
        self, pin_getter: Callable[[], str]
    ) -> Optional[Any]:
        if not HAS_PYSIDE6:
            _log.warning("PySide6 saknas")
            return None
        try:
            from plugins.main_gui.vehicle_registry_page import VehicleDataPage
        except ImportError as exc:
            _log.error("Kunde inte importera VehicleDataPage: %s", exc)
            return None
        try:
            self._page = VehicleDataPage(
                storage=self.vehicle_storage,
                pin_getter=pin_getter,
                initial_years=[datetime.now().year],
                app=self.app,
            )
            return self._page
        except Exception as exc:
            _log.error("Kunde inte skapa VehicleDataPage: %s", exc)
            return None
    def get_page(self) -> Optional[Any]:
        return self._page
    def invalidate_schema_cache(self) -> None:
        if self._page is None:
            return
        for m in ("on_ts_spec_changed", "on_schema_changed", "refresh"):
            if hasattr(self._page, m):
                try:
                    getattr(self._page, m)()
                    return
                except Exception:
                    pass
    # ──────────────────────────────────────────────────────────────────
    # SCHEMA ACCESS
    # ──────────────────────────────────────────────────────────────────
    def get_schema(self, post_type: str) -> Optional[Any]:
        return get_ts_schema_safe(self.app, post_type)
    def get_active_schema_version(self) -> Optional[str]:
        return self._cached_schema_version or get_active_schema_version_safe(self.app)
    # ──────────────────────────────────────────────────────────────────
    # VIN / VEHICLE LOOKUP
    # ──────────────────────────────────────────────────────────────────
    def find_vehicle_by_vin3(
        self, vin3: str
    ) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        if not self.vehicle_cache or not self.vehicle_storage:
            return None, None
        cached = self.vehicle_cache.find_by_vin3(vin3)
        if cached:
            return cached
        return self.vehicle_storage.find_by_vin3(vin3)
    def find_vehicle_by_full_vin(self, vin: str) -> Optional[Dict[str, Any]]:
        vin3 = extract_vin3_from_full(vin)
        if not vin3:
            return None
        _, v = self.find_vehicle_by_vin3(vin3)
        return v
    def find_vehicle_by_vin(self, vin: str) -> Optional[Dict[str, Any]]:
        """Alias för find_vehicle_by_full_vin."""
        return self.find_vehicle_by_full_vin(vin)
    def find_vehicle_by_vin_and_year(
        self, vin: str, year: Any
    ) -> Optional[Dict[str, Any]]:
        if not self.vehicle_cache or not self.vehicle_storage:
            return None
        ny = normalize_model_year(year)
        if not ny:
            return self.find_vehicle_by_full_vin(vin)
        yi = int(ny)
        self.vehicle_cache.load_year(yi)
        vin3 = extract_vin3_from_full(vin)
        if not vin3:
            return None
        cached = self.vehicle_cache.find_by_vin3(vin3)
        if cached and cached[0] == yi:
            return cached[1]
        for v in self.vehicle_storage.load_year(yi):
            if str(v.get("vin_kod", "")).strip().upper() == vin3:
                return v
        return None
    def get_vehicle(self, vin: str) -> Optional[Dict[str, Any]]:
        """
        Hämta fordon — stöder VIN3, VIN-prefix och full VIN.
        FIXAT v4.5.0 (spec v7.0):
          - Exakt 3 tecken  -> tolkas som direkt VIN3-uppslag
          - 4-8 tecken      -> tolkas som VIN-prefix, tecken 2-4
                               extraheras (slice [1:4])
          - 9+ tecken       -> full VIN, tecken 2-4 extraheras
        """
        cleaned = vin.strip().upper()
        if not cleaned:
            return None
        if len(cleaned) == 3:
            _, v = self.find_vehicle_by_vin3(cleaned)
            return v
        return self.find_vehicle_by_full_vin(cleaned)
    def get_vehicle_years(self) -> List[int]:
        return self.vehicle_storage.list_years() if self.vehicle_storage else []
    def load_vehicles_for_year(self, year: int) -> List[Dict[str, Any]]:
        return self.vehicle_storage.load_year(year) if self.vehicle_storage else []
    def save_vehicles_for_year(
        self, year: int, vehicles: List[Dict[str, Any]]
    ) -> None:
        if not self.vehicle_storage or not self.vehicle_cache:
            return
        self.vehicle_storage.save_year(year, vehicles, self.VERSION)
        # v4.6.0: publik metod — ingen privat åtkomst
        self.vehicle_cache.invalidate_year(year)
        self.vehicle_cache.load_year(year)
    # ──────────────────────────────────────────────────────────────────
    # VIN VALIDATION
    # ──────────────────────────────────────────────────────────────────
    def validate_vin(self, vin: str) -> Dict[str, Any]:
        return VinValidator.validate(vin).to_dict()
    def sanitize_vin(self, vin: str) -> str:
        return VinValidator.sanitize(vin)
    def extract_vin_code(self, vin: str) -> str:
        return VinValidator.extract_vin_code(vin)
    def is_valid_vin(self, vin: str) -> bool:
        return VinValidator.is_valid(vin)
    # ──────────────────────────────────────────────────────────────────
    # REGISTERED VIN HISTORY
    # ──────────────────────────────────────────────────────────────────
    def is_registered(self, vin: str) -> bool:
        return self.vin_registry.is_registered(vin) if self.vin_registry else False
    def register_vins(self, vin_list: List[str]) -> Dict[str, Any]:
        if not self.vin_registry:
            return {"registered": 0, "skipped": 0}
        registered, skipped = self.vin_registry.register_multiple(vin_list)
        if registered > 0:
            emit_event_safe(
                self.app, "vehicle_registry:vins_registered",
                {"registered": registered, "skipped": skipped},
            )
        return {"registered": registered, "skipped": skipped}
    def register_multiple(self, vin_list: List[str]) -> Tuple[int, int]:
        """Registrera flera VIN (tuple-retur, för ts_file_generator)."""
        if not self.vin_registry:
            return 0, 0
        return self.vin_registry.register_multiple(vin_list)
    def unregister_vin(self, vin: str) -> bool:
        return self.vin_registry.unregister(vin) if self.vin_registry else False
    def get_registration_statistics(self) -> Dict[str, Any]:
        return self.vin_registry.get_statistics() if self.vin_registry else {}
    def get_recent_registrations(self, limit: int = 50) -> List[Dict[str, str]]:
        return self.vin_registry.get_recent(limit) if self.vin_registry else []
    def get_registered_vins(self) -> List[str]:
        if not self.vin_registry:
            return []
        return self.vin_registry.get_all_vins()
    # ──────────────────────────────────────────────────────────────────
    # CRUD
    # ──────────────────────────────────────────────────────────────────
    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        if not self.vehicle_storage or not self.vehicle_cache:
            return {"success": False, "error": "Storage ej initierad"}
        vin3 = str(record.get("vin_kod", "") or "").strip().upper()
        if not vin3:
            full_vin = record.get("VINCODE", record.get("vin", ""))
            vin3 = extract_vin3_from_full(str(full_vin or "")) or ""
        if not vin3:
            return {"success": False, "error": "VIN-kod krävs"}
        record["vin_kod"] = vin3
        year_str = record.get("MODELYEAR", record.get("modelyear", ""))
        year = normalize_model_year(year_str)
        if not year:
            year = str(datetime.now().year)
        yi = int(year)
        vehicles = self.vehicle_storage.load_year(yi)
        found = False
        for i, v in enumerate(vehicles):
            if str(v.get("vin_kod", "")).strip().upper() == vin3:
                vehicles[i] = record
                found = True
                break
        if not found:
            vehicles.append(record)
        self.vehicle_storage.save_year(yi, vehicles, self.VERSION)
        self.vehicle_cache.invalidate()
        self.vehicle_cache.load_year(yi)
        emit_event_safe(self.app, "vehicle_registry:updated", {
            "vin3": vin3, "year": yi,
            "action": "update" if found else "insert",
        })
        return {"success": True, "vin3": vin3, "year": yi}
    def delete(
        self, vin3: str, year: Optional[int] = None
    ) -> Dict[str, Any]:
        if not self.vehicle_storage or not self.vehicle_cache:
            return {"success": False, "error": "Storage ej initierad"}
        cv = vin3.strip().upper()
        if not validate_vin3(cv):
            return {"success": False, "error": "Ogiltig VIN3"}
        if year is None:
            fy, _ = self.vehicle_storage.find_by_vin3(cv)
            if not fy:
                return {"success": False, "error": "VIN3 hittades inte"}
            year = fy
        vehicles = self.vehicle_storage.load_year(year)
        orig = len(vehicles)
        vehicles = [
            v for v in vehicles
            if str(v.get("vin_kod", "")).strip().upper() != cv
        ]
        if len(vehicles) == orig:
            return {"success": False, "error": "VIN3 hittades inte i angivet år"}
        self.vehicle_storage.save_year(year, vehicles, self.VERSION)
        self.vehicle_cache.invalidate()
        emit_event_safe(self.app, "vehicle_registry:updated", {
            "vin3": cv, "year": year, "action": "delete",
        })
        return {"success": True, "vin3": cv, "year": year}
    def get_by_vin3(self, vin3: str) -> Optional[Dict[str, Any]]:
        _, v = self.find_vehicle_by_vin3(vin3)
        return v
    def get_by_modelyear(self, year: str) -> List[Dict[str, Any]]:
        ny = normalize_model_year(year)
        if not ny or not self.vehicle_storage:
            return []
        return self.vehicle_storage.load_year(int(ny))
    def get_all(self, limit: int = 1000) -> List[Dict[str, Any]]:
        if not self.vehicle_storage:
            return []
        all_v: List[Dict[str, Any]] = []
        for year in reversed(self.vehicle_storage.list_years()):
            for v in self.vehicle_storage.load_year(year):
                item = dict(v)
                item["_year"] = year
                all_v.append(item)
                if len(all_v) >= limit:
                    return all_v
        return all_v
    def search(
        self, search_term: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        if not self.vehicle_storage:
            return []
        term = search_term.strip().upper()
        if not term:
            return []
        results: List[Dict[str, Any]] = []
        fields = [
            "vin_kod", "fabrikat", "handelsbeteckning",
            "typ", "avgaskrav_tillagg",
        ]
        for year in reversed(self.vehicle_storage.list_years()):
            for v in self.vehicle_storage.load_year(year):
                if any(term in str(v.get(f, "")).upper() for f in fields):
                    item = dict(v)
                    item["_year"] = year
                    results.append(item)
                    if len(results) >= limit:
                        return results
        return results
    def get_count(self) -> int:
        if not self.vehicle_storage:
            return 0
        return sum(
            len(self.vehicle_storage.load_year(y))
            for y in self.vehicle_storage.list_years()
        )
    def get_statistics(self) -> Dict[str, Any]:
        if not self.vehicle_storage or not self.vehicle_cache or not self.vin_registry:
            return {
                "vehicles": {"total": 0},
                "registered": {},
                "schema": {"version": None},
                "generated_at": datetime.now().isoformat(),
            }
        years = self.vehicle_storage.list_years()
        counts = {y: len(self.vehicle_storage.load_year(y)) for y in years}
        return {
            "vehicles": {
                "total": sum(counts.values()),
                "years": years,
                "per_year": counts,
            },
            "registered": self.vin_registry.get_statistics(),
            "cache": {
                # v4.6.0: publika metoder — ingen privat åtkomst
                "loaded_years": self.vehicle_cache.get_loaded_years(),
                "vin3_count": self.vehicle_cache.get_vin3_count(),
            },
            "schema": {"version": self._cached_schema_version},
            "generated_at": datetime.now().isoformat(),
        }
    def rebuild_index(self) -> int:
        return self.vehicle_storage.rebuild_index() if self.vehicle_storage else 0
    # ──────────────────────────────────────────────────────────────────
    # EXPORT
    # ──────────────────────────────────────────────────────────────────
    def export_to_json(
        self, filepath: Path, year: Optional[int] = None
    ) -> bool:
        try:
            vehicles = (
                self.vehicle_storage.load_year(year)
                if year and self.vehicle_storage
                else self.get_all(100000)
            )
            atomic_write_json(filepath, {
                "vehicles": vehicles,
                "_meta": {
                    "exported_at": datetime.now().isoformat(),
                    "count": len(vehicles),
                    "version": VERSION,
                    "copyright": get_copyright_string(),
                },
            })
            return True
        except Exception as exc:
            _log.error("Export misslyckades: %s", exc, exc_info=True)
            return False
    def export_to_excel(
        self, filepath: Path, year: Optional[int] = None
    ) -> bool:
        try:
            import pandas as pd
            vehicles = (
                self.vehicle_storage.load_year(year)
                if year and self.vehicle_storage
                else self.get_all(100000)
            )
            if not vehicles:
                return False
            df = pd.DataFrame(vehicles)
            df.to_excel(filepath, index=False, sheet_name="Fordon")
            return True
        except ImportError:
            _log.error("pandas krävs för Excel-export")
            return False
        except Exception as exc:
            _log.error("Excel-export misslyckades: %s", exc, exc_info=True)
            return False

# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════
__all__ = [
    "Plugin",
    "VinValidator",
    "VinValidationResult",
    "VinRegistry",
    "VehicleDataStorage",
    "VehicleCache",
    "SchemaEventNames",
    "VERSION",
    "AUTHOR",
    "DEFAULT_COLUMN_MAPPING",
    "normalize_model_year",
    "validate_vin3",
    "extract_vin3_from_full",
    "get_plugin_safe",
    "get_ts_schema_safe",
    "get_active_schema_version_safe",
    "VIN_LENGTH",
    "VIN_INVALID_CHARS",
    "VIN_PATTERN",
    "VIN3_SLICE_START",
    "VIN3_SLICE_END",
    "MODEL_COLUMNS",
    "FIELD_GROUPS",
    "DROPDOWNS",
    "VALIDATION",
    "SEARCHABLE_COLUMNS",
    "HAS_PYSIDE6",
    "ConflictAction",
]
