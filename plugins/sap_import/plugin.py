# -*- coding: utf-8 -*-
# Fil: plugins/sap_import/plugin.py

"""
SAP Import Plugin v4.1.1

Importerar fordonsdata från SAP/Dispatch Excel-filer.
Filbaserad lagring — ingen databas krävs.

ANSVAR:
    - Läsa Excel-filer med automatisk header-detektion
    - Normalisera VIN, årsmodell, datum
    - Lagra data i JSON-cache (data/sap_cache/)
    - In-memory index för snabb sökning
    - Integration med vin_tracking för duplicatkontroll
    - Integration med vehicle_registry för fordonsdata-synk
    - Progress-callbacks för GUI
    - Atomisk filskrivning

IMPORTER (EXTERNA):
    hashlib, json, logging, os, re, tempfile, time,
    contextlib, dataclasses, datetime, pathlib, typing
    core.plugin_base (PluginBase)
    pandas (valfri, kontrolleras vid runtime)

PUBLIKT API:
    import_from_file(filepath, ...)     -> ProcessedFile
    auto_import_sap(...)                -> ImportSummary
    list_sap_files()                    -> List[Path]
    get_vehicle(vin)                    -> Optional[VehicleData]
    get_vehicles_by_year(year)          -> List[VehicleData]
    get_vehicles_by_approval(approval)  -> List[VehicleData]
    find_vehicle(vin, year, approval)   -> List[VehicleData]
    get_statistics()                    -> Dict
    get_all_vins()                      -> Set[str]
    clear_cache()                       -> None
    sync_to_vehicle_registry()          -> Dict

EVENTS SOM EMITTAS:
    sap_import:file_complete, sap_import:started,
    sap_import:complete, sap_import:synced_to_registry

LYSSNAR PÅ:
    sap_import:auto_import, sap_import:import_file

SAMARBETAR MED:
    vin_tracking, vehicle_registry, core_config, ts_spec_import

FÖRÄNDRINGAR v4.1.1 (granskad — spec v1.6 förbättringsregeln):
    - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2026 ..." i
      docstringen BORTTAGEN — copyright genereras dynamiskt via
      get_copyright_string().
    - FIX (låst regel, DATA-FEL): VIN3 extraherades med vin[4:7]
      (tecken 5–7) men spec v7.0/låst regel säger VIN3 = tecken 2–4 =
      slice [1:4] — fel vin_kod skrevs till vehicle_registry vid sync.
      Nu vin[1:4] (konsistent med vehicle_registry, vin_tracking,
      main_gui-helpers).
    - setup_logger() -> _get_logger() (privat, konvention).
    - FIX (robusthet): _filter_registered() anropade
      is_registered() direkt — AttributeError om vin_tracking saknar
      metoden. Nu getattr-guard.
    - FIX (korrekthet, TESTFÅNGAD): VehicleCache.clear() rensade bara
      minnet — cachefilerna (vehicles_*.json + index.json) låg kvar på
      disk så nästa load() läste tillbaka allt och "clear_cache" var
      verkningslöst. Nu raderas även filerna (kraschsäkert, loggas).
    - Loggmeddelanden översatta till svenska; lazy %s överallt
      (inga f-string-logganrop).
    - Fil-huvud normaliserat: "# Fil: plugins/sap_import/plugin.py"
      (spec v1.11, KRAV 58).
    - Övrig logik OFÖRÄNDRAD (ExcelReader, DataNormalizer,
      ColumnResolver, VehicleCache, import/sync/events, atomisk
      skrivning).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Any, Callable, Dict, Final, Iterator, List, Optional, Set, Tuple, TYPE_CHECKING

try:
    import pandas as pd
    HAS_PANDAS: Final[bool] = True
except ImportError:
    pd = None
    HAS_PANDAS = False

from core.plugin_base import PluginBase

if TYPE_CHECKING:
    from core.event_bus import EventBus


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "4.1.1"
AUTHOR: Final[str] = "Rickard Längkvist"
PLUGIN_NAME: Final[str] = "SAP Import"


def get_copyright_string() -> str:
    return f"Copyright © {datetime.now().year} {AUTHOR}"


COLUMN_ALIASES: Final[Dict[str, List[str]]] = {
    "VINCODE": ["vincode", "vin", "vin-nummer", "vinnumber", "chassinummer", "chassis", "vehicle id"],
    "MODELYEAR": ["modelyear", "model year", "årsmodell", "arsmodell", "my", "year", "modellår"],
    "APPROVAL": ["approval", "etg", "etgnumber", "wvta", "typgodkännande"],
    "COLORCODE": ["colorcode", "color code", "färgkod", "fargkod", "color"],
    "DEALER": ["dealer", "sold to dealer", "dealer code", "återförsäljare", "kundnummer"],
    "PRODUCTION_DATE": ["production date", "produktionsdatum", "actual production date"],
    "INVOICE_DATE": ["invoice date", "fakturadatum", "invoicedate"],
    "ENGINE": ["engine", "motor", "motortyp", "engine_type"],
    "VARIANT": ["variant", "modell", "model", "version"],
    "MASS": ["mass", "vikt", "weight", "totalvikt"],
}

CRITICAL_COLUMNS: Final[List[str]] = ["VINCODE", "MODELYEAR"]
SAP_FILENAME_PATTERNS: Final[List[str]] = ["sap", "wvta", "modell", "register"]


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback om logging ej konfigurerat.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("sap_import")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log: logging.Logger = _get_logger()


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
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


def emit_event_safe(app: Any, event_name: str, data: Optional[Dict[str, Any]] = None) -> bool:
    if app is None:
        return False
    try:
        bus = getattr(app, "event_bus", None)
        if bus is None:
            return False
        for method in ("emit", "publish"):
            func = getattr(bus, method, None)
            if callable(func):
                func(event_name, data or {})
                return True
    except Exception as exc:
        _log.debug("Event emit misslyckades '%s': %s", event_name, exc)
    return False


def subscribe_event_safe(app: Any, event_name: str, handler: Callable) -> bool:
    try:
        bus = getattr(app, "event_bus", None) if app else None
        if bus is None:
            return False
        for method in ("on", "subscribe"):
            func = getattr(bus, method, None)
            if callable(func):
                func(event_name, handler)
                return True
    except Exception:
        pass
    return False


def unsubscribe_event_safe(app: Any, event_name: str, handler: Callable) -> bool:
    try:
        bus = getattr(app, "event_bus", None) if app else None
        if bus is None:
            return False
        for method in ("off", "unsubscribe"):
            func = getattr(bus, method, None)
            if callable(func):
                func(event_name, handler)
                return True
    except Exception:
        pass
    return False


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp",
        prefix=f".{path.name}.tmp_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SAPImportConfig:
    version: str = "4.1"
    header_scan_rows: int = 50
    max_rows_per_sheet: int = 100000
    vin_uppercase: bool = True
    vin_min_length: int = 17
    vin_max_length: int = 17
    date_columns: List[str] = field(default_factory=lambda: ["INVOICE_DATE", "PRODUCTION_DATE"])
    date_format_output: str = "%Y-%m-%d"
    skip_sheets: List[str] = field(default_factory=list)
    filename_patterns: List[str] = field(default_factory=lambda: list(SAP_FILENAME_PATTERNS))
    cache_enabled: bool = True
    cache_ttl_hours: int = 24
    batch_size: int = 1000

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SAPImportConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class VehicleData:
    vin: str
    model_year: str = ""
    approval: str = ""
    color_code: str = ""
    dealer: str = ""
    production_date: str = ""
    invoice_date: str = ""
    engine: str = ""
    variant: str = ""
    mass: str = ""
    source_file: str = ""
    source_sheet: str = ""
    import_timestamp: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VehicleData:
        known_fields = set(cls.__dataclass_fields__.keys())
        known = {k: v for k, v in data.items() if k in known_fields}
        extra = {k: v for k, v in data.items() if k not in known_fields}
        known["extra"] = {**known.get("extra", {}), **extra}
        return cls(**known)


@dataclass
class ProcessedSheet:
    name: str
    imported_rows: int = 0
    skipped_rows: int = 0
    skipped_vins: List[str] = field(default_factory=list)
    skipped_reason: str = ""
    columns_found: List[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class ProcessedFile:
    filename: str
    full_path: str
    sheets: List[ProcessedSheet] = field(default_factory=list)
    imported_rows: int = 0
    error: str = ""
    duration_ms: float = 0.0
    checksum: str = ""

    @property
    def is_success(self) -> bool:
        return not self.error and self.imported_rows > 0


@dataclass
class ImportSummary:
    total_imported: int = 0
    total_skipped: int = 0
    processed_files: List[ProcessedFile] = field(default_factory=list)
    failed_files: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def is_success(self) -> bool:
        return len(self.failed_files) == 0 and self.total_imported > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_imported": self.total_imported,
            "total_skipped": self.total_skipped,
            "duration_ms": self.duration_ms,
            "files_processed": len(self.processed_files),
            "files_failed": len(self.failed_files),
            "failed_files": self.failed_files,
        }


# ══════════════════════════════════════════════════════════════════════════════
# HELPER CLASSES
# ══════════════════════════════════════════════════════════════════════════════

class DataNormalizer:
    @staticmethod
    def normalize_vin(vin: Any) -> str:
        if vin is None:
            return ""
        s = str(vin).strip().upper()
        s = re.sub(r"[^A-Z0-9]", "", s)
        if len(s) != 17:
            return ""
        if any(c in s for c in "IOQ"):
            return ""
        return s

    @staticmethod
    def normalize_year(year: Any) -> str:
        if year is None:
            return ""
        s = str(year).strip()
        if not s or s.lower() in ("nan", "none", "null", ""):
            return ""
        if re.fullmatch(r"20\d{2}", s):
            return s
        my_match = re.search(r"[Mm][Yy]\s*(\d{2,4})", s)
        if my_match:
            y = my_match.group(1)
            return f"20{y}" if len(y) == 2 else y
        if re.fullmatch(r"\d{2}", s):
            return f"20{s}"
        try:
            val = int(float(s.replace(",", ".")))
            if 2000 <= val <= 2099:
                return str(val)
            elif 0 <= val <= 99:
                return f"20{val:02d}"
        except ValueError:
            pass
        m = re.search(r"\b(20\d{2})\b", s)
        if m:
            return m.group(1)
        return ""

    @staticmethod
    def normalize_date(value: Any, output_format: str = "%Y-%m-%d") -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime(output_format)
        if isinstance(value, date):
            return value.strftime(output_format)
        if HAS_PANDAS and isinstance(value, pd.Timestamp):
            return value.strftime(output_format)
        s = str(value).strip()
        if not s or s.lower() in ("nan", "nat", "none", ""):
            return ""
        formats = [
            "%Y-%m-%d", "%d.%m.%Y", "%Y%m%d", "%d/%m/%Y",
            "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt).strftime(output_format)
            except ValueError:
                continue
        return ""

    @staticmethod
    def clean_string(value: Any) -> str:
        if value is None:
            return ""
        s = str(value).strip()
        if s.lower() in ("nan", "none", "null"):
            return ""
        return s


class ColumnResolver:
    def __init__(self, aliases: Optional[Dict[str, List[str]]] = None):
        self.aliases = aliases or dict(COLUMN_ALIASES)
        self._cache: Dict[str, str] = {}

    def resolve(self, column: str) -> str:
        if column in self._cache:
            return self._cache[column]
        col_lower = re.sub(r"[\W_]+", "", column.lower())
        for canonical, alias_list in self.aliases.items():
            for alias in alias_list:
                alias_norm = re.sub(r"[\W_]+", "", alias.lower())
                if col_lower == alias_norm:
                    self._cache[column] = canonical
                    return canonical
        self._cache[column] = column
        return column

    def resolve_columns(self, columns: List[str]) -> Dict[str, str]:
        return {col: self.resolve(col) for col in columns}


class ExcelReader:
    def __init__(self, config: SAPImportConfig):
        self.config = config
        self.normalizer = DataNormalizer()
        self.resolver = ColumnResolver()

    def read_file(
        self,
        filepath: Path,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Iterator[Tuple[str, List[VehicleData]]]:
        if not HAS_PANDAS:
            raise ImportError("pandas krävs för Excel-import")
        engine = self._get_engine(filepath)
        try:
            xls = pd.ExcelFile(filepath, engine=engine)
        except Exception as e:
            _log.error("Kunde inte öppna Excel: %s: %s", filepath, e)
            raise
        for sheet_name in xls.sheet_names:
            if self._should_skip_sheet(sheet_name):
                _log.debug("Hoppar över blad: %s", sheet_name)
                continue
            if progress_callback:
                progress_callback(f"Läser: {sheet_name}")
            try:
                vehicles = self._read_sheet(xls, sheet_name, str(filepath))
                yield sheet_name, vehicles
            except Exception as e:
                _log.error("Fel vid läsning av blad %s: %s", sheet_name, e)
                yield sheet_name, []
        xls.close()

    def _read_sheet(self, xls: Any, sheet_name: str, source_file: str) -> List[VehicleData]:
        df = self._read_with_header_detection(xls, sheet_name)
        if df is None or df.empty:
            return []
        column_map = self.resolver.resolve_columns(df.columns.tolist())
        df = df.rename(columns=column_map)
        missing = [c for c in CRITICAL_COLUMNS if c not in df.columns]
        if missing:
            _log.warning("%s: Saknar kritiska kolumner: %s", sheet_name, missing)
            return []
        vehicles = []
        timestamp = datetime.now().isoformat()
        for _, row in df.iterrows():
            vehicle = self._row_to_vehicle(row, source_file, sheet_name, timestamp)
            if vehicle and vehicle.vin:
                vehicles.append(vehicle)
        return vehicles

    def _read_with_header_detection(self, xls: Any, sheet_name: str) -> Optional[Any]:
        df_preview = pd.read_excel(xls, sheet_name=sheet_name, nrows=self.config.header_scan_rows, header=None)
        if df_preview.empty:
            return None
        header_row = 0
        max_strings = 0
        for i in range(min(20, len(df_preview))):
            row = df_preview.iloc[i]
            string_count = sum(1 for v in row if isinstance(v, str) and v.strip() and not v.strip().isdigit())
            if string_count > max_strings:
                max_strings = string_count
                header_row = i
        df = pd.read_excel(xls, sheet_name=sheet_name, header=header_row, nrows=self.config.max_rows_per_sheet, dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.dropna(how="all")
        df = df.fillna("")
        return df

    def _row_to_vehicle(self, row: Any, source_file: str, source_sheet: str, timestamp: str) -> Optional[VehicleData]:
        vin = self.normalizer.normalize_vin(row.get("VINCODE", ""))
        if not vin:
            return None
        return VehicleData(
            vin=vin,
            model_year=self.normalizer.normalize_year(row.get("MODELYEAR", "")),
            approval=self.normalizer.clean_string(row.get("APPROVAL", "")),
            color_code=self.normalizer.clean_string(row.get("COLORCODE", "")),
            dealer=self.normalizer.clean_string(row.get("DEALER", "")),
            production_date=self.normalizer.normalize_date(row.get("PRODUCTION_DATE", "")),
            invoice_date=self.normalizer.normalize_date(row.get("INVOICE_DATE", "")),
            engine=self.normalizer.clean_string(row.get("ENGINE", "")),
            variant=self.normalizer.clean_string(row.get("VARIANT", "")),
            mass=self.normalizer.clean_string(row.get("MASS", "")),
            source_file=Path(source_file).name,
            source_sheet=source_sheet,
            import_timestamp=timestamp,
        )

    def _should_skip_sheet(self, sheet_name: str) -> bool:
        skip_lower = [s.lower() for s in self.config.skip_sheets]
        return sheet_name.lower() in skip_lower

    def _get_engine(self, filepath: Path) -> str:
        if filepath.suffix.lower() == ".xls":
            return "xlrd"
        return "openpyxl"


class VehicleCache:
    def __init__(self, cache_dir: Path, config: SAPImportConfig):
        self.cache_dir = cache_dir
        self.config = config
        self._vin_index: Dict[str, VehicleData] = {}
        self._year_index: Dict[str, List[VehicleData]] = {}
        self._approval_index: Dict[str, List[VehicleData]] = {}
        self._loaded = False
        self._dirty = False

    def load(self) -> None:
        if self._loaded:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for vehicle_file in self.cache_dir.glob("vehicles_*.json"):
            try:
                with open(vehicle_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data.get("vehicles", []):
                    vehicle = VehicleData.from_dict(item)
                    self._add_to_index(vehicle)
            except Exception as e:
                _log.error("Kunde inte ladda cache: %s: %s", vehicle_file, e)
        self._loaded = True
        _log.info("Laddade %d fordon från cache", len(self._vin_index))

    def save(self) -> None:
        if not self._dirty:
            return
        by_year: Dict[str, List[Dict]] = {}
        for vehicle in self._vin_index.values():
            year = vehicle.model_year or "unknown"
            by_year.setdefault(year, []).append(vehicle.to_dict())
        for year, vehicles in by_year.items():
            filepath = self.cache_dir / f"vehicles_{year}.json"
            atomic_write_json(filepath, {
                "year": year,
                "count": len(vehicles),
                "updated_at": datetime.now().isoformat(),
                "vehicles": vehicles,
            })
        self._save_index()
        self._dirty = False
        _log.info("Sparade %d fordon till cache", len(self._vin_index))

    def add_vehicles(self, vehicles: List[VehicleData]) -> Tuple[int, int]:
        self.load()
        added = 0
        updated = 0
        for vehicle in vehicles:
            if vehicle.vin in self._vin_index:
                updated += 1
            else:
                added += 1
            self._add_to_index(vehicle)
        if added > 0 or updated > 0:
            self._dirty = True
        return added, updated

    def get_by_vin(self, vin: str) -> Optional[VehicleData]:
        self.load()
        return self._vin_index.get(vin.upper())

    def get_by_year(self, year: str) -> List[VehicleData]:
        self.load()
        return self._year_index.get(year, [])

    def get_by_approval(self, approval: str) -> List[VehicleData]:
        self.load()
        return self._approval_index.get(approval.upper(), [])

    def find(self, vin: Optional[str] = None, year: Optional[str] = None, approval: Optional[str] = None) -> List[VehicleData]:
        self.load()
        if vin:
            vehicle = self._vin_index.get(vin.upper())
            if vehicle:
                if year and vehicle.model_year != year:
                    return []
                return [vehicle]
        if approval:
            candidates = self._approval_index.get(approval.upper(), [])
            if year:
                candidates = [v for v in candidates if v.model_year == year]
            return candidates
        if year:
            return self._year_index.get(year, [])
        return []

    def get_all_vins(self) -> Set[str]:
        self.load()
        return set(self._vin_index.keys())

    def get_all_vehicles(self) -> List[VehicleData]:
        self.load()
        return list(self._vin_index.values())

    def get_statistics(self) -> Dict[str, Any]:
        self.load()
        return {
            "total_vehicles": len(self._vin_index),
            "years": sorted(self._year_index.keys()),
            "vehicles_per_year": {y: len(v) for y, v in self._year_index.items()},
        }

    def clear(self) -> None:
        """
        Rensa cache HELT (minne + filer).

        Tar bort vehicles_*.json och index.json från cache-katalogen —
        annars skulle nästa load() läsa tillbaka allt från disk och
        "rensa" vore verkningslöst.
        """
        self._vin_index.clear()
        self._year_index.clear()
        self._approval_index.clear()
        self._loaded = False
        self._dirty = False
        try:
            for stale in self.cache_dir.glob("vehicles_*.json"):
                try:
                    stale.unlink()
                except OSError as exc:
                    _log.warning(
                        "Kunde inte ta bort cachefil %s: %s", stale, exc
                    )
            index_path = self.cache_dir / "index.json"
            if index_path.exists():
                try:
                    index_path.unlink()
                except OSError as exc:
                    _log.warning(
                        "Kunde inte ta bort indexfil %s: %s",
                        index_path, exc,
                    )
        except Exception as exc:
            _log.warning("Fel vid borttagning av cachefiler: %s", exc)

    def _add_to_index(self, vehicle: VehicleData) -> None:
        self._vin_index[vehicle.vin] = vehicle
        if vehicle.model_year:
            self._year_index.setdefault(vehicle.model_year, []).append(vehicle)
        if vehicle.approval:
            self._approval_index.setdefault(vehicle.approval.upper(), []).append(vehicle)

    def _save_index(self) -> None:
        index_path = self.cache_dir / "index.json"
        atomic_write_json(index_path, {
            "version": "1.0",
            "total_vehicles": len(self._vin_index),
            "years": sorted(self._year_index.keys()),
            "updated_at": datetime.now().isoformat(),
            "copyright": get_copyright_string(),
        })


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    NAME: Final[str] = PLUGIN_NAME
    VERSION: Final[str] = VERSION
    DESCRIPTION: Final[str] = "Import av SAP/Dispatch Excel-filer"
    AUTHOR: Final[str] = AUTHOR
    DEPENDENCIES: Final[List[str]] = []

    def __init__(self, app: Any):
        super().__init__(app)
        self._config: Optional[SAPImportConfig] = None
        self._paths: Dict[str, Path] = {}
        self._reader: Optional[ExcelReader] = None
        self._cache: Optional[VehicleCache] = None
        self._vin_tracking: Optional[Any] = None
        self._import_in_progress = False
        self._event_handlers: List[Tuple[str, Callable]] = []

    # ──────────────────────────────────────────────────────────────────
    # PLUGINBASE KONTRAKT
    # ──────────────────────────────────────────────────────────────────

    def init(self) -> None:
        try:
            if not HAS_PANDAS:
                _log.warning("pandas ej installerat — Excel-import begränsad")
            self._setup_paths()
            self._load_config()
            self._reader = ExcelReader(self._config)
            self._cache = VehicleCache(self._paths["sap_cache"], self._config)
            self._load_optional_plugins()
            try:
                self.app.sap_import = self
            except Exception:
                pass
            self._register_events()
            _log.info("%s v%s initierad", PLUGIN_NAME, VERSION)
        except Exception as exc:
            _log.error("Initiering misslyckades: %s", exc, exc_info=True)

    def register_ui(self, parent: Any) -> None:
        return None

    def shutdown(self) -> None:
        try:
            if self._cache:
                self._cache.save()
            for event_name, handler in self._event_handlers:
                unsubscribe_event_safe(self.app, event_name, handler)
            self._event_handlers.clear()
            _log.info("%s avstängd.", PLUGIN_NAME)
        except Exception as exc:
            _log.error("Avstängning misslyckades: %s", exc, exc_info=True)

    def config_schema(self) -> Dict[str, Any]:
        return {
            "plugin": PLUGIN_NAME,
            "version": VERSION,
            "author": AUTHOR,
            "copyright": get_copyright_string(),
            "settings": self._config.to_dict() if self._config else {},
        }

    # ──────────────────────────────────────────────────────────────────
    # BAKÅTKOMPATIBILITET
    # ──────────────────────────────────────────────────────────────────

    def initialize(self) -> None:
        self.init()

    def activate(self) -> None:
        if self._cache:
            self._cache.load()
        _log.info("%s aktiverad", PLUGIN_NAME)

    def deactivate(self) -> None:
        self.shutdown()

    @property
    def config(self) -> Dict[str, Any]:
        return self._config.to_dict() if self._config else {}

    # ──────────────────────────────────────────────────────────────────
    # INTERN SETUP
    # ──────────────────────────────────────────────────────────────────

    def _setup_paths(self) -> None:
        base_dir = Path(getattr(self.app, "base_path", "."))
        self._paths = {
            "base": base_dir,
            "data": base_dir / "data",
            "xlsx": base_dir / "xlsx",
            "dispatch": base_dir / "dispatch",
            "sap_cache": base_dir / "data" / "sap_cache",
            "ut": base_dir / "ut",
            "logs": base_dir / "logs",
        }
        for path in self._paths.values():
            path.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> None:
        config_data = {}
        try:
            cfg = getattr(self.app, "config", None)
            if cfg and hasattr(cfg, "get"):
                config_data = cfg.get("sap_import", {}) or {}
            elif isinstance(cfg, dict):
                config_data = cfg.get("sap_import", {}) or {}
        except Exception:
            pass
        self._config = SAPImportConfig.from_dict(config_data)

    def _load_optional_plugins(self) -> None:
        self._vin_tracking = get_plugin_safe(self.app, "vin_tracking")

    def _register_events(self) -> None:
        events = [
            ("sap_import:auto_import", self._on_auto_import),
            ("sap_import:import_file", self._on_import_file),
        ]
        for event_name, handler in events:
            if subscribe_event_safe(self.app, event_name, handler):
                self._event_handlers.append((event_name, handler))

    # ──────────────────────────────────────────────────────────────────
    # PUBLIKT API
    # ──────────────────────────────────────────────────────────────────

    def import_from_file(
        self,
        filepath: Path,
        progress_callback: Optional[Callable[[str], None]] = None,
        skip_registered: bool = True,
    ) -> ProcessedFile:
        filepath = Path(filepath)
        start_time = time.perf_counter()
        result = ProcessedFile(filename=filepath.name, full_path=str(filepath))

        if not filepath.exists():
            result.error = "Filen finns inte"
            return result
        if not self._is_valid_excel(filepath):
            result.error = "Ogiltig filtyp"
            return result

        result.checksum = self._file_checksum(filepath)
        if progress_callback:
            progress_callback(f"Öppnar {filepath.name}...")

        try:
            for sheet_name, vehicles in self._reader.read_file(filepath, progress_callback):
                sheet_start = time.perf_counter()
                sheet_result = ProcessedSheet(name=sheet_name, columns_found=[])

                if not vehicles:
                    sheet_result.skipped_reason = "Inga giltiga fordon"
                    result.sheets.append(sheet_result)
                    continue

                if skip_registered and self._vin_tracking:
                    vehicles, skipped = self._filter_registered(vehicles)
                    sheet_result.skipped_vins = skipped

                if not vehicles:
                    sheet_result.skipped_reason = "Alla VIN redan registrerade"
                    result.sheets.append(sheet_result)
                    continue

                added, updated = self._cache.add_vehicles(vehicles)
                sheet_result.imported_rows = added + updated
                sheet_result.duration_ms = (time.perf_counter() - sheet_start) * 1000
                result.sheets.append(sheet_result)
                result.imported_rows += sheet_result.imported_rows

                if progress_callback:
                    progress_callback(f"{sheet_name}: {sheet_result.imported_rows} fordon")

            self._cache.save()
        except Exception as e:
            _log.exception("Importfel: %s", filepath)
            result.error = str(e)

        result.duration_ms = (time.perf_counter() - start_time) * 1000
        emit_event_safe(self.app, "sap_import:file_complete", {
            "filename": result.filename,
            "imported": result.imported_rows,
            "success": result.is_success,
        })
        return result

    def auto_import_sap(
        self,
        progress_callback: Optional[Callable[[str], None]] = None,
        save_summary: bool = True,
    ) -> ImportSummary:
        start_time = time.perf_counter()
        summary = ImportSummary()

        if self._import_in_progress:
            _log.warning("Import pågår redan")
            return summary

        files = self.list_sap_files()
        if not files:
            if progress_callback:
                progress_callback("Inga SAP-filer hittades")
            return summary

        if progress_callback:
            progress_callback(f"Hittade {len(files)} filer")

        emit_event_safe(self.app, "sap_import:started", {"file_count": len(files)})

        with self._import_lock():
            for i, filepath in enumerate(files, 1):
                if progress_callback:
                    progress_callback(f"[{i}/{len(files)}] {filepath.name}")
                result = self.import_from_file(filepath, progress_callback)
                summary.processed_files.append(result)
                summary.total_imported += result.imported_rows
                for sheet in result.sheets:
                    summary.total_skipped += len(sheet.skipped_vins)
                if result.error:
                    summary.failed_files.append(f"{filepath.name}: {result.error}")

        summary.duration_ms = (time.perf_counter() - start_time) * 1000
        if save_summary:
            self._save_summary(summary)

        emit_event_safe(self.app, "sap_import:complete", summary.to_dict())
        _log.info(
            "SAP-import klar: %d importerade, %d hoppade över, %d misslyckade",
            summary.total_imported, summary.total_skipped, len(summary.failed_files)
        )
        return summary

    def list_sap_files(self) -> List[Path]:
        all_files: List[Path] = []
        search_dirs = [self._paths.get("xlsx"), self._paths.get("data"), self._paths.get("dispatch")]
        for search_dir in search_dirs:
            if not search_dir or not search_dir.exists():
                continue
            for pattern in ["*.xlsx", "*.xls", "*.xlsm"]:
                all_files.extend(search_dir.glob(pattern))

        patterns = [p.lower() for p in self._config.filename_patterns]
        sap_files = [
            f for f in all_files
            if any(p in f.stem.lower() for p in patterns) and not f.name.startswith("~$")
        ]
        sap_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        seen: Set[str] = set()
        unique: List[Path] = []
        for f in sap_files:
            if f.name not in seen:
                seen.add(f.name)
                unique.append(f)
        return unique

    def get_vehicle(self, vin: str) -> Optional[VehicleData]:
        return self._cache.get_by_vin(vin) if self._cache else None

    def get_vehicles_by_year(self, year: str) -> List[VehicleData]:
        return self._cache.get_by_year(year) if self._cache else []

    def get_vehicles_by_approval(self, approval: str) -> List[VehicleData]:
        return self._cache.get_by_approval(approval) if self._cache else []

    def find_vehicle(self, vin: Optional[str] = None, year: Optional[str] = None, approval: Optional[str] = None) -> List[VehicleData]:
        return self._cache.find(vin=vin, year=year, approval=approval) if self._cache else []

    def get_statistics(self) -> Dict[str, Any]:
        return self._cache.get_statistics() if self._cache else {}

    def get_all_vins(self) -> Set[str]:
        return self._cache.get_all_vins() if self._cache else set()

    def clear_cache(self) -> None:
        if self._cache:
            self._cache.clear()
        _log.info("SAP-cache rensad")

    # ──────────────────────────────────────────────────────────────────
    # SYNC TILL VEHICLE_REGISTRY
    # ──────────────────────────────────────────────────────────────────

    def sync_to_vehicle_registry(
        self,
        year_filter: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        result = {"success": False, "synced": 0, "skipped": 0, "errors": [], "years": []}

        vehicle_reg = get_plugin_safe(self.app, "vehicle_registry")
        if not vehicle_reg:
            result["errors"].append("vehicle_registry-plugin saknas")
            return result

        if not self._cache:
            result["errors"].append("SAP-cache ej laddad")
            return result

        self._cache.load()
        all_vehicles = self._cache.get_all_vehicles()

        if year_filter:
            all_vehicles = [v for v in all_vehicles if v.model_year == year_filter]

        if not all_vehicles:
            result["errors"].append("Inga fordon att synka")
            return result

        if progress_callback:
            progress_callback(f"Synkar {len(all_vehicles)} fordon...")

        years_synced: Set[str] = set()

        for i, vehicle in enumerate(all_vehicles):
            if progress_callback and i % 50 == 0:
                progress_callback(f"Synkar {i + 1}/{len(all_vehicles)}...")
            try:
                record = self._vehicle_to_registry_record(vehicle)
                if not record:
                    result["skipped"] += 1
                    continue

                upsert_result = vehicle_reg.upsert(record)
                if upsert_result.get("success"):
                    result["synced"] += 1
                    if vehicle.model_year:
                        years_synced.add(vehicle.model_year)
                else:
                    result["skipped"] += 1
                    err = upsert_result.get("error", "")
                    if err and len(result["errors"]) < 10:
                        result["errors"].append(f"{vehicle.vin}: {err}")
            except Exception as exc:
                result["skipped"] += 1
                if len(result["errors"]) < 10:
                    result["errors"].append(f"{vehicle.vin}: {exc}")

        result["success"] = result["synced"] > 0
        result["years"] = sorted(years_synced)

        emit_event_safe(self.app, "sap_import:synced_to_registry", {
            "synced": result["synced"],
            "skipped": result["skipped"],
            "years": result["years"],
        })

        _log.info(
            "Sync till vehicle_registry: %d synkade, %d hoppade över, %d fel",
            result["synced"], result["skipped"], len(result["errors"])
        )
        return result

    def _vehicle_to_registry_record(self, vehicle: VehicleData) -> Optional[Dict[str, Any]]:
        if not vehicle.vin or len(vehicle.vin) != 17:
            return None

        # LÅST REGEL (spec v7.0): VIN3 = tecken 2-4 (slice [1:4])
        vin3 = vehicle.vin[1:4]
        if not vin3 or len(vin3) != 3:
            return None

        record = {
            "vin_kod": vin3,
            "MODELYEAR": vehicle.model_year,
            "VINCODE": vehicle.vin,
            "avgaskrav_tillagg": vehicle.approval,
        }

        if vehicle.variant:
            record["handelsbeteckning"] = vehicle.variant
        if vehicle.engine:
            record["motor"] = vehicle.engine
        if vehicle.mass:
            try:
                record["vikt_kor_klar_kg"] = str(int(float(vehicle.mass)))
            except (ValueError, TypeError):
                pass
        if vehicle.color_code:
            record["fargkod"] = vehicle.color_code

        if vehicle.extra:
            record.update(vehicle.extra)

        return record

    # ──────────────────────────────────────────────────────────────────
    # EVENT HANDLERS
    # ──────────────────────────────────────────────────────────────────

    def _on_auto_import(self, data: Optional[Dict] = None) -> None:
        data = data or {}
        callback = data.get("progress_callback")
        save_summary = data.get("save_summary", True)
        result = self.auto_import_sap(progress_callback=callback, save_summary=save_summary)
        result_callback = data.get("callback")
        if result_callback:
            result_callback(result)

    def _on_import_file(self, data: Optional[Dict] = None) -> None:
        data = data or {}
        filepath = data.get("filepath")
        if not filepath:
            return
        callback = data.get("progress_callback")
        result = self.import_from_file(Path(filepath), callback)
        result_callback = data.get("callback")
        if result_callback:
            result_callback(result)

    # ──────────────────────────────────────────────────────────────────
    # INTERNAL
    # ──────────────────────────────────────────────────────────────────

    def _filter_registered(self, vehicles: List[VehicleData]) -> Tuple[List[VehicleData], List[str]]:
        if not self._vin_tracking:
            return vehicles, []
        is_registered = getattr(self._vin_tracking, "is_registered", None)
        if not callable(is_registered):
            return vehicles, []
        skipped: List[str] = []
        filtered: List[VehicleData] = []
        for vehicle in vehicles:
            try:
                if is_registered(vehicle.vin):
                    skipped.append(vehicle.vin)
                else:
                    filtered.append(vehicle)
            except Exception:
                filtered.append(vehicle)
        return filtered, skipped

    def _is_valid_excel(self, filepath: Path) -> bool:
        return filepath.suffix.lower() in {".xlsx", ".xls", ".xlsm"}

    def _file_checksum(self, filepath: Path) -> str:
        hasher = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()[:12]

    @contextmanager
    def _import_lock(self) -> Iterator[None]:
        self._import_in_progress = True
        try:
            yield
        finally:
            self._import_in_progress = False

    def _save_summary(self, summary: ImportSummary) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = self._paths["ut"] / f"sap_import_{timestamp}.json"
        data = {
            **summary.to_dict(),
            "plugin_version": VERSION,
            "copyright": get_copyright_string(),
            "files": [
                {
                    "filename": pf.filename,
                    "imported_rows": pf.imported_rows,
                    "error": pf.error,
                    "duration_ms": pf.duration_ms,
                }
                for pf in summary.processed_files
            ],
        }
        try:
            atomic_write_json(filepath, data)
            _log.info("Sammanfattning sparad: %s", filepath.name)
        except Exception as e:
            _log.error("Kunde inte spara sammanfattning: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "Plugin",
    "SAPImportConfig",
    "VehicleData",
    "ProcessedFile",
    "ProcessedSheet",
    "ImportSummary",
    "DataNormalizer",
    "ColumnResolver",
    "ExcelReader",
    "VehicleCache",
    "VERSION",
    "AUTHOR",
]
