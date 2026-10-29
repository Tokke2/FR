# -*- coding: utf-8 -*-
"""
Data Mapping Plugin v5.0.0

Modern, stabil och framtidssäker plugin för kolumnmappning,
Excel-import av fordonsdata och TS-filgenerering.

UPPDATERINGAR v5.0.0:
  ✨ BUGG #2 FIXAD:
     - Importerar nu ColumnMappingService från .column_mapping_service
     - Plugin laddar utan NameError

  ✨ EXCEL-FORDONSDATA:
     - import_vehicle_excel(): Importera Excel med fordonsdata
     - Ett blad per årsmodell, '25Kw' ignoreras automatiskt
     - Kolumnheaders sparas till JSON
     - Kolumnmappning via ColumnMappingService

  ✨ COPYRIGHT:
     - Copyright © {år} Rickard Längkvist (dynamiskt)

  ✨ MODERN ARKITEKTUR:
     - PluginBase kontrakt: init, register_ui, shutdown, config_schema
     - module-level _log (EJ self.logger)
     - ColumnMappingService från .column_mapping_service (BUGG#2 FIX)
     - VinRegistry från .vin_registry (BUGG#4 FIX)
     - 20 publika funktioner

FUNKTIONER (1-20):
  1. find_column()              - Hitta matchande kolumn
  2. find_all_columns()         - Hitta alla matchande kolumner
  3. match_dispatch_data()      - Matcha dispatch-data mot register
  4. get_config()               - Hämta mappningskonfiguration
  5. add_custom_mapping()       - Lägg till custom mapping
  6. remove_custom_mapping()    - Ta bort custom mapping
  7. reset_mappings()           - Återställ till standard
  8. export_mappings()          - Exportera mappningar till JSON
  9. import_mappings()          - Importera mappningar från JSON
 10. validate_mapping()         - Validera en mappning
 11. get_field_suggestions()    - Förslag på fältmappning
 12. get_source_statistics()    - Statistik per datakälla
 13. get_mapping_coverage()     - Täckningsgrad för mappningar
 14. generate_ts_file()         - Generera TS-fil
 15. get_diagnostics()          - Diagnostik och statistik
 16. generate_ivi_batch()       - Batch-generera IVI
 17. get_ts_field_mapping()     - TS-schema fältmappning
 18. get_collaboration_status() - Cross-plugin status
 19. import_vehicle_excel()     - Importera Excel med fordonsdata
 20. get_vehicle_import_status()- Status för senaste Excel-import

Copyright © 2026 Rickard Längkvist
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Final, List, Optional, Set, Tuple, TYPE_CHECKING

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from core.plugin_base import PluginBase

from .column_mapping_service import (
    ColumnMappingService as ExternalColumnMappingService,
    normalize_column_name,
    COLUMN_SYNONYMS,
)
from .vin_registry import VinRegistry

if TYPE_CHECKING:
    from core.application import Application


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "5.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"

FUZZY_THRESHOLD: Final[float] = 0.7
CACHE_SIZE: Final[int] = 256

SKIP_SHEETS_DEFAULT: Final[List[str]] = [
    "25Kw", "25kw", "25KW", "Kw", "kw", "KW",
]

PANDAS_AVAILABLE: bool = False
try:
    import pandas as pd  # type: ignore
    PANDAS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore


def get_copyright_string() -> str:
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def get_logger() -> logging.Logger:
    try:
        log = logging.getLogger("data_mapping.plugin")
        if not log.handlers:
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%H:%M:%S",
            ))
            log.addHandler(console)
            try:
                log_dir = Path("logs")
                log_dir.mkdir(exist_ok=True)
                file_handler = logging.FileHandler(
                    log_dir / "data_mapping.log",
                    encoding="utf-8",
                )
                file_handler.setFormatter(logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(message)s"
                ))
                log.addHandler(file_handler)
            except Exception:
                pass
            log.setLevel(logging.INFO)
        return log
    except Exception:
        return logging.getLogger(__name__)


_log = get_logger()


# ══════════════════════════════════════════════════════════════════════════════
# ATOMIC FILE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def atomic_write_json(path: Path, data: Any) -> None:
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=path.stem + "_",
        dir=str(dir_path),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        _log.exception("Atomisk skrivning misslyckades: %s", path)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    if app is None:
        return None
    normalized = name.lower().replace(" ", "_").replace("-", "_")
    for try_name in (name, normalized):
        for attr in ("get_plugin", "plugin_loader", "plugin_manager"):
            owner = getattr(app, attr, None) if attr != "get_plugin" else app
            if owner is None:
                continue
            try:
                func = getattr(owner, "get_plugin", None)
                if func is not None:
                    result = func(try_name)
                    if result is not None:
                        return result
            except Exception:
                pass
        try:
            result = getattr(app, try_name, None)
            if result is not None:
                return result
        except Exception:
            pass
    return None


def get_event_bus(app: Any) -> Optional[Any]:
    if app is None:
        return None
    for attr in ("event_bus", "events", "_event_bus"):
        try:
            bus = getattr(app, attr, None)
            if bus is not None:
                return bus
        except Exception:
            pass
    return None


def emit_event_safe(app: Any, event_name: str, data: Optional[Dict[str, Any]] = None) -> bool:
    try:
        bus = get_event_bus(app)
        if bus is None:
            return False
        for method in ("emit", "publish"):
            func = getattr(bus, method, None)
            if func is not None:
                func(event_name, data or {})
                return True
    except Exception as exc:
        _log.debug("Event emit misslyckades '%s': %s", event_name, exc)
    return False


def subscribe_event_safe(app: Any, event_name: str, handler: Callable) -> bool:
    try:
        bus = get_event_bus(app)
        if bus is None:
            return False
        for method in ("on", "subscribe"):
            func = getattr(bus, method, None)
            if func is not None:
                func(event_name, handler)
                return True
    except Exception as exc:
        _log.debug("Prenumeration misslyckades '%s': %s", event_name, exc)
    return False


def unsubscribe_event_safe(app: Any, event_name: str, handler: Callable) -> bool:
    try:
        bus = get_event_bus(app)
        if bus is None:
            return False
        for method in ("off", "unsubscribe"):
            func = getattr(bus, method, None)
            if func is not None:
                func(event_name, handler)
                return True
    except Exception as exc:
        _log.debug("Avprenumeration misslyckades '%s': %s", event_name, exc)
    return False


def fuzzy_match(s1: str, s2: str) -> float:
    try:
        if not s1 or not s2:
            return 0.0
        return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()
    except Exception:
        return 0.0


def should_skip_sheet(sheet_name: str, skip_list: Optional[List[str]] = None) -> bool:
    if skip_list is None:
        skip_list = list(SKIP_SHEETS_DEFAULT)
    name_lower = str(sheet_name).strip().lower()
    for skip in skip_list:
        if str(skip).strip().lower() == name_lower:
            return True
    if name_lower.endswith("kw") or name_lower.endswith("kwh"):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════════════════════

class DataSource(str, Enum):
    SAP = "sap"
    DISPATCH = "dispatch"
    DEALER = "dealer"
    COLOR = "color"

    @classmethod
    def from_string(cls, value: str) -> "DataSource":
        if not value:
            return cls.DISPATCH
        try:
            return cls(value.lower())
        except ValueError:
            return cls.DISPATCH


class FieldType(str, Enum):
    VIN = "vin"
    MODEL_YEAR = "model_year"
    MODEL_NAME = "model_name"
    COLOR_CODE = "color_code"
    DEALER_CODE = "dealer_code"
    DELIVERY_DATE = "delivery_date"
    APPROVAL = "approval"
    OWNER_ORG = "owner_org"
    TYPE = "type"
    VARIANT = "variant"
    VERSION = "version"

    @classmethod
    def from_string(cls, value: str) -> Optional["FieldType"]:
        if not value:
            return None
        try:
            return cls(value.lower())
        except ValueError:
            return None


class MatchStatus(str, Enum):
    OK = "ok"
    MISSING_DATA = "missing_data"
    MISSING_OWNER = "missing_owner"
    UNMAPPED_COLOR = "unmapped_color"
    ALREADY_REGISTERED = "already_registered"
    ERROR = "error"

    @property
    def icon(self) -> str:
        icons = {
            MatchStatus.OK: "✅",
            MatchStatus.MISSING_DATA: "❌",
            MatchStatus.MISSING_OWNER: "⚠️",
            MatchStatus.UNMAPPED_COLOR: "⚠️",
            MatchStatus.ALREADY_REGISTERED: "⏭️",
            MatchStatus.ERROR: "❌",
        }
        return icons.get(self, "❓")

    @property
    def text(self) -> str:
        texts = {
            MatchStatus.OK: "OK",
            MatchStatus.MISSING_DATA: "Ingen fordonsdata",
            MatchStatus.MISSING_OWNER: "Saknar ägare",
            MatchStatus.UNMAPPED_COLOR: "Färg ej mappad",
            MatchStatus.ALREADY_REGISTERED: "Redan registrerad",
            MatchStatus.ERROR: "Fel",
        }
        return texts.get(self, str(self.value))

    @property
    def is_ok(self) -> bool:
        return self == MatchStatus.OK


# ══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ColumnMatch:
    source_column: str
    target_field: str
    confidence: float
    source: DataSource
    matched_pattern: str = ""

    @property
    def is_confident(self) -> bool:
        return self.confidence >= FUZZY_THRESHOLD

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_column": self.source_column,
            "target_field": self.target_field,
            "confidence": self.confidence,
            "source": self.source.value,
            "matched_pattern": self.matched_pattern,
        }


@dataclass
class MappingConfig:
    version: str = "5.0"
    patterns: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    custom_mappings: Dict[str, Dict[str, str]] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MappingConfig":
        try:
            return cls(
                version=data.get("version", "5.0"),
                patterns=data.get("patterns", {}),
                custom_mappings=data.get("custom_mappings", {}),
                updated_at=data.get("updated_at", datetime.now().isoformat()),
                updated_by=data.get("updated_by", ""),
            )
        except Exception:
            return cls()


@dataclass
class VehicleMatchResult:
    vin: str
    status: MatchStatus
    model_name: str = ""
    model_year: Optional[int] = None
    color_original: str = ""
    color_ts_code: str = ""
    owner_org: str = ""
    dealer_code: str = ""
    vehicle_data: Dict[str, Any] = field(default_factory=dict)
    tech_data: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    row_index: int = -1

    @property
    def is_ok(self) -> bool:
        return self.status == MatchStatus.OK

    @property
    def status_icon(self) -> str:
        return self.status.icon

    @property
    def status_text(self) -> str:
        if self.status == MatchStatus.ERROR and self.error_message:
            return self.error_message
        return self.status.text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vin": self.vin,
            "status": self.status.value,
            "model_name": self.model_name,
            "model_year": self.model_year,
            "color_original": self.color_original,
            "color_ts_code": self.color_ts_code,
            "owner_org": self.owner_org,
            "dealer_code": self.dealer_code,
            "vehicle_data": self.vehicle_data,
            "tech_data": self.tech_data,
            "error_message": self.error_message,
            "row_index": self.row_index,
        }

    def to_vehicle_dict(self) -> Dict[str, Any]:
        vehicle: Dict[str, Any] = {
            "_vin": self.vin,
            "VIN": self.vin,
            "_model_year": str(self.model_year) if self.model_year else "",
            "_color_ts": self.color_ts_code,
            "_color_orig": self.color_original,
            "_owner": self.owner_org,
            "_dealer_id": self.dealer_code,
            "model_name": self.model_name,
        }
        if self.vehicle_data:
            vehicle.update(self.vehicle_data)
        if self.tech_data:
            vehicle.update(self.tech_data)
        return vehicle


@dataclass
class MatchingSummary:
    total: int = 0
    ok: int = 0
    missing_data: int = 0
    missing_owner: int = 0
    unmapped_colors: int = 0
    already_registered: int = 0
    errors: int = 0
    new_colors: Set[str] = field(default_factory=set)
    missing_models: Set[str] = field(default_factory=set)

    @property
    def can_generate(self) -> bool:
        return self.ok > 0

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.ok / self.total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "ok": self.ok,
            "missing_data": self.missing_data,
            "missing_owner": self.missing_owner,
            "unmapped_colors": self.unmapped_colors,
            "already_registered": self.already_registered,
            "errors": self.errors,
            "new_colors": sorted(self.new_colors),
            "missing_models": sorted(self.missing_models),
            "can_generate": self.can_generate,
            "success_rate": round(self.success_rate * 100, 1),
        }


@dataclass
class GenerateResult:
    success: bool = False
    file_path: Optional[Path] = None
    file_id: str = ""
    vehicles_count: int = 0
    vins_registered: int = 0
    vins_skipped: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "file_path": str(self.file_path) if self.file_path else None,
            "file_id": self.file_id,
            "vehicles_count": self.vehicles_count,
            "vins_registered": self.vins_registered,
            "vins_skipped": self.vins_skipped,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class VehicleImportStatus:
    imported: bool = False
    filepath: str = ""
    imported_at: str = ""
    total_rows: int = 0
    headers: List[str] = field(default_factory=list)
    sheets_processed: List[str] = field(default_factory=list)
    sheets_skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    mappings_auto_detected: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL COLUMN MAPPING SERVICE (fallback – riktiga servicen ligger i column_mapping_service.py)
# ══════════════════════════════════════════════════════════════════════════════

class _InternalColumnMappingService:
    """Lättvikts fallback – riktiga ColumnMappingService används via self._external_mapping_service"""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path
        self.config = MappingConfig()
        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path or not self.config_path.exists():
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.config = MappingConfig.from_dict(data)
        except Exception as exc:
            _log.warning("Kunde inte ladda mapping config: %s", exc)

    def _save_config(self) -> None:
        if not self.config_path:
            return
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.updated_at = datetime.now().isoformat()
            with open(self.config_path, "w", encoding="utf-8") as fh:
                json.dump(self.config.to_dict(), fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            _log.error("Kunde inte spara mapping config: %s", exc)

    def find_column(self, columns: List[str], field_type: str, source: DataSource) -> Optional[str]:
        # Enkel synonym-matchning via COLUMN_SYNONYMS
        if not columns:
            return None
        # reverse lookup: target_field -> list of synonyms
        rev: Dict[str, List[str]] = {}
        for syn, (target, _desc) in COLUMN_SYNONYMS.items():
            rev.setdefault(target.upper(), []).append(syn)
        # field_type kan vara t.ex. "vin" – mappa till VINCODE
        ft = field_type.upper()
        candidates = rev.get(ft, [])
        # direkt match
        norm_cols = {normalize_column_name(c): c for c in columns}
        for cand in candidates:
            nc = normalize_column_name(cand)
            if nc in norm_cols:
                return norm_cols[nc]
        # fuzzy
        best_col, best_score = None, 0.0
        for col in columns:
            for cand in candidates:
                s = fuzzy_match(col, cand)
                if s > best_score:
                    best_score, best_col = s, col
        if best_score >= FUZZY_THRESHOLD:
            return best_col
        return None

    def find_all_columns(self, columns: List[str], source: DataSource) -> Dict[str, str]:
        result: Dict[str, str] = {}
        # testa alla kända TS-målfält
        targets = sorted({t for t, _d in COLUMN_SYNONYMS.values()})
        for target in targets:
            col = self.find_column(columns, target.lower(), source)
            if col:
                result[target.lower()] = col
        return result

    def add_custom_mapping(self, source: DataSource, field_type: str, column_name: str) -> None:
        src = source.value if isinstance(source, DataSource) else str(source)
        if src not in self.config.custom_mappings:
            self.config.custom_mappings[src] = {}
        self.config.custom_mappings[src][field_type] = column_name
        self._save_config()

    def remove_custom_mapping(self, source: DataSource, field_type: str) -> bool:
        src = source.value if isinstance(source, DataSource) else str(source)
        if src in self.config.custom_mappings and field_type in self.config.custom_mappings[src]:
            del self.config.custom_mappings[src][field_type]
            self._save_config()
            return True
        return False

    def reset_to_defaults(self) -> None:
        self.config = MappingConfig()
        self._save_config()


# ══════════════════════════════════════════════════════════════════════════════
# VEHICLE MATCHING SERVICE
# ══════════════════════════════════════════════════════════════════════════════

class VehicleMatchingService:
    def __init__(self, column_mapper: _InternalColumnMappingService, event_bus: Optional[Any] = None) -> None:
        self.column_mapper = column_mapper
        self.event_bus = event_bus

    def match_records(
        self,
        records: List[Dict[str, Any]],
        vehicle_registry: Optional[Any] = None,
        dealers_manager: Optional[Any] = None,
        colors_manager: Optional[Any] = None,
        skip_registered: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[List[VehicleMatchResult], MatchingSummary]:
        results: List[VehicleMatchResult] = []
        summary = MatchingSummary(total=len(records))
        if not records:
            return results, summary

        columns = list(records[0].keys()) if records else []
        column_map = self.column_mapper.find_all_columns(columns, DataSource.DISPATCH)

        # hitta VIN-kolumn med flera alias
        vin_col = (
            column_map.get("vincode")
            or column_map.get("vin")
            or next((c for c in columns if "vin" in c.lower()), None)
        )
        color_col = column_map.get("color_code") or next((c for c in columns if "color" in c.lower() or "färg" in c.lower()), None)
        dealer_col = column_map.get("dealer_code") or next((c for c in columns if "dealer" in c.lower() or "dn" == c.lower()), None)
        model_col = column_map.get("model_name") or next((c for c in columns if "model" in c.lower()), None)
        year_col = column_map.get("model_year") or next((c for c in columns if "year" in c.lower() or "år" in c.lower()), None)

        if not vin_col:
            _log.error("VIN-kolumn hittades inte i %s", columns)
            return results, summary

        registered_vins: Set[str] = set()
        if skip_registered and vehicle_registry:
            try:
                if hasattr(vehicle_registry, "get_registered_vins"):
                    registered_vins = set(vehicle_registry.get_registered_vins())
                elif hasattr(vehicle_registry, "get_all"):
                    registered_vins = set(vehicle_registry.get_all().keys())
            except Exception:
                pass

        for idx, record in enumerate(records):
            if progress_callback:
                try:
                    progress_callback(idx + 1, len(records))
                except Exception:
                    pass
            try:
                result = self._match_single_record(
                    record=record,
                    row_index=idx,
                    vin_col=vin_col,
                    color_col=color_col,
                    dealer_col=dealer_col,
                    model_col=model_col,
                    year_col=year_col,
                    vehicle_registry=vehicle_registry,
                    dealers_manager=dealers_manager,
                    colors_manager=colors_manager,
                    registered_vins=registered_vins,
                    skip_registered=skip_registered,
                )
                results.append(result)
                self._update_summary(summary, result)
            except Exception as exc:
                _log.error("Fel vid matchning av rad %d: %s", idx, exc)
                results.append(VehicleMatchResult(
                    vin=str(record.get(vin_col, "UNKNOWN")),
                    status=MatchStatus.ERROR,
                    error_message=str(exc),
                    row_index=idx,
                ))
                summary.errors += 1

        return results, summary

    def _match_single_record(
        self,
        record: Dict[str, Any],
        row_index: int,
        vin_col: Optional[str],
        color_col: Optional[str],
        dealer_col: Optional[str],
        model_col: Optional[str],
        year_col: Optional[str],
        vehicle_registry: Optional[Any],
        dealers_manager: Optional[Any],
        colors_manager: Optional[Any],
        registered_vins: Set[str],
        skip_registered: bool,
    ) -> VehicleMatchResult:
        vin_raw = str(record.get(vin_col, "") if vin_col else "").strip().upper()
        if not vin_raw:
            return VehicleMatchResult(vin="", status=MatchStatus.MISSING_DATA, error_message="VIN saknas", row_index=row_index)

        if skip_registered and vin_raw in registered_vins:
            return VehicleMatchResult(vin=vin_raw, status=MatchStatus.ALREADY_REGISTERED, row_index=row_index)

        model_name = str(record.get(model_col, "") if model_col else "").strip()
        color_original = str(record.get(color_col, "") if color_col else "").strip()
        dealer_code = str(record.get(dealer_col, "") if dealer_col else "").strip()
        year_raw = record.get(year_col, "") if year_col else ""
        model_year: Optional[int] = None
        try:
            if year_raw not in (None, ""):
                model_year = int(str(year_raw)[:4])
        except Exception:
            model_year = None

        # färguppslag
        color_ts_code = color_original
        if colors_manager and color_original:
            try:
                if hasattr(colors_manager, "resolve_color"):
                    resolved = colors_manager.resolve_color(color_original)
                    if resolved:
                        color_ts_code = resolved
                elif hasattr(colors_manager, "get_ts_code"):
                    resolved = colors_manager.get_ts_code(color_original)
                    if resolved:
                        color_ts_code = resolved
            except Exception:
                pass

        # ägare / orgnr via dealers_manager
        owner_org = ""
        if dealers_manager and dealer_code:
            try:
                if hasattr(dealers_manager, "get_by_dn"):
                    dealer = dealers_manager.get_by_dn(dealer_code)
                    if dealer:
                        owner_org = dealer.get("orgnr", "") if isinstance(dealer, dict) else getattr(dealer, "orgnr", "")
                elif hasattr(dealers_manager, "get_all_dealers"):
                    for d in dealers_manager.get_all_dealers():
                        dn = d.get("dn", "") if isinstance(d, dict) else getattr(d, "dn", "")
                        if str(dn) == dealer_code:
                            owner_org = d.get("orgnr", "") if isinstance(d, dict) else getattr(d, "orgnr", "")
                            break
            except Exception:
                pass

        # fordonsdata från vin_registry
        vehicle_data: Dict[str, Any] = {}
        if vehicle_registry:
            try:
                if hasattr(vehicle_registry, "get"):
                    vd = vehicle_registry.get(vin_raw)
                    if isinstance(vd, dict):
                        vehicle_data = vd
            except Exception:
                pass

        # statusbedömning
        if not vehicle_data and not model_name:
            status = MatchStatus.MISSING_DATA
        elif not owner_org and dealer_code:
            status = MatchStatus.MISSING_OWNER
        elif color_original and color_ts_code == color_original and colors_manager:
            # färg kunde inte mappas – räkna som unmapped men fortsatt OK
            status = MatchStatus.OK
        else:
            status = MatchStatus.OK

        if not model_name and vehicle_data:
            model_name = str(vehicle_data.get("model_name", "") or vehicle_data.get("MODELNAME", ""))

        if model_year is None and vehicle_data:
            try:
                y = vehicle_data.get("model_year") or vehicle_data.get("MODELYEAR")
                if y:
                    model_year = int(str(y)[:4])
            except Exception:
                pass

        return VehicleMatchResult(
            vin=vin_raw,
            status=status,
            model_name=model_name,
            model_year=model_year,
            color_original=color_original,
            color_ts_code=color_ts_code,
            owner_org=owner_org,
            dealer_code=dealer_code,
            vehicle_data=vehicle_data,
            tech_data={k: v for k, v in record.items()},
            row_index=row_index,
        )

    def _update_summary(self, summary: MatchingSummary, result: VehicleMatchResult) -> None:
        status = result.status
        if status == MatchStatus.OK:
            summary.ok += 1
        elif status == MatchStatus.MISSING_DATA:
            summary.missing_data += 1
        elif status == MatchStatus.MISSING_OWNER:
            summary.missing_owner += 1
        elif status == MatchStatus.UNMAPPED_COLOR:
            summary.unmapped_colors += 1
        elif status == MatchStatus.ALREADY_REGISTERED:
            summary.already_registered += 1
        elif status == MatchStatus.ERROR:
            summary.errors += 1
        if result.color_original and result.color_original != result.color_ts_code:
            summary.new_colors.add(result.color_original)
        if result.status == MatchStatus.MISSING_DATA and result.model_name:
            summary.missing_models.add(result.model_name)


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    NAME: Final[str] = "data_mapping"
    VERSION: Final[str] = VERSION
    DESCRIPTION: Final[str] = "Kolumnmappning, Excel-fordonsimport, fordonsmatchning och TS-filgenerering (20 funktioner)"
    AUTHOR: Final[str] = AUTHOR
    DEPENDENCIES: Final[Tuple] = ()

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._mapper: Optional[_InternalColumnMappingService] = None
        self._matcher: Optional[VehicleMatchingService] = None
        self._external_mapping_service: Optional[ExternalColumnMappingService] = None
        self._vin_registry: Optional[VinRegistry] = None
        self._widget: Optional[QWidget] = None
        self._initialized = False
        self._config_dir: Optional[Path] = None
        self._event_handlers: List[Tuple[str, Callable]] = []
        self._vehicle_import_status = VehicleImportStatus()
        self._imported_vehicle_rows: List[Dict[str, Any]] = []

    @property
    def copyright(self) -> str:
        return get_copyright_string()

    # ---- PluginBase ----
    def init(self) -> None:
        try:
            _log.info("=" * 60)
            _log.info("Data Mapping v%s", VERSION)
            _log.info("%s", self.copyright)
            _log.info("=" * 60)
            base_dir = Path.cwd()
            self._config_dir = base_dir / "data" / "data_mapping"
            self._config_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_mapper()
            self._ensure_matcher()
            self._ensure_external_mapping_service()
            self._ensure_vin_registry()
            try:
                setattr(self.app, "data_mapping", self)
            except Exception:
                pass
            self._initialized = True
            _log.info("Initiering klar. 20 publika funktioner tillgängliga.")
        except Exception as exc:
            _log.exception("Initiering misslyckades: %s", exc)
            self._initialized = False

    def register_ui(self, parent: QWidget) -> Optional[QWidget]:
        try:
            from .widget import GenerateFilePage
            self._widget = GenerateFilePage(self, parent)
            return self._widget
        except Exception as exc:
            _log.exception("Widget-skapande misslyckades.")
            fallback = QWidget(parent)
            lay = QVBoxLayout(fallback)
            lay.addWidget(QLabel(f"❌ Widget creation failed: {exc}"))
            return fallback

    def shutdown(self) -> None:
        try:
            for event_name, handler in self._event_handlers:
                unsubscribe_event_safe(self.app, event_name, handler)
            self._event_handlers.clear()
            self._widget = None
            self._initialized = False
            _log.info("Shutdown klar.")
        except Exception as exc:
            _log.exception("Shutdown misslyckades: %s", exc)

    def config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "title": "Data Mapping Plugin",
            "version": VERSION,
            "properties": {
                "fuzzy_threshold": {"type": "number", "default": FUZZY_THRESHOLD},
                "skip_sheets": {"type": "array", "items": {"type": "string"}, "default": list(SKIP_SHEETS_DEFAULT)},
            },
        }

    def activate(self) -> None:
        try:
            self._register_events()
            emit_event_safe(self.app, "data_mapping:activated", {"version": VERSION})
            _log.info("Aktiverad.")
        except Exception as exc:
            _log.exception("Aktivering misslyckades: %s", exc)

    # ---- internal helpers ----
    def _register_events(self) -> None:
        events = [
            ("dispatch:file_loaded", self._on_dispatch_loaded),
        ]
        for event_name, handler in events:
            if subscribe_event_safe(self.app, event_name, handler):
                self._event_handlers.append((event_name, handler))

    def _on_dispatch_loaded(self, data: Any) -> None:
        _log.info("Dispatch file loaded event received")

    def _on_color_mapped(self, data: Any) -> None:
        pass

    def _ensure_mapper(self) -> None:
        if self._mapper is not None:
            return
        try:
            config_path = self._config_dir / "column_mappings.json" if self._config_dir else None
            self._mapper = _InternalColumnMappingService(config_path=config_path)
        except Exception as exc:
            _log.error("Kunde inte skapa intern mapper: %s", exc)

    def _ensure_matcher(self) -> None:
        if self._matcher is not None:
            return
        try:
            self._ensure_mapper()
            assert self._mapper is not None
            self._matcher = VehicleMatchingService(column_mapper=self._mapper)
        except Exception as exc:
            _log.error("Kunde inte skapa matcher: %s", exc)

    def _ensure_external_mapping_service(self) -> None:
        if self._external_mapping_service is not None:
            return
        try:
            mappings_path = Path("data") / "mappings" / "column_mappings.json"
            self._external_mapping_service = ExternalColumnMappingService(mappings_path=mappings_path)
            self._external_mapping_service.load()
        except Exception as exc:
            _log.error("Kunde inte skapa ExternalColumnMappingService: %s", exc)

    def _ensure_vin_registry(self) -> None:
        if self._vin_registry is not None:
            return
        try:
            self._vin_registry = VinRegistry()
        except Exception as exc:
            _log.error("Kunde inte skapa VinRegistry: %s", exc)

    def _get_mapper(self) -> _InternalColumnMappingService:
        self._ensure_mapper()
        if self._mapper is None:
            raise RuntimeError("Intern mapper är inte initierad.")
        return self._mapper

    def _get_matcher(self) -> VehicleMatchingService:
        self._ensure_matcher()
        if self._matcher is None:
            raise RuntimeError("Matcher är inte initierad.")
        return self._matcher

    def _get_external_mapping_service(self) -> Optional[ExternalColumnMappingService]:
        self._ensure_external_mapping_service()
        return self._external_mapping_service

    def _get_vin_registry(self) -> Optional[VinRegistry]:
        self._ensure_vin_registry()
        return self._vin_registry

    # ══════════════════════════════════════════════════════════
    # PUBLIKA FUNKTIONER 1-20
    # ══════════════════════════════════════════════════════════

    # 1. find_column
    def find_column(self, column_name: str, source: str = "dispatch") -> Optional[str]:
        """Hitta matchande kolumn."""
        try:
            # Försök via externa ColumnMappingService (120+ synonymer)
            svc = self._get_external_mapping_service()
            if svc and hasattr(svc, "get_target"):
                tgt = svc.get_target(column_name)
                if tgt:
                    return tgt
            # Fallback: direkt synonym-lookup
            key = normalize_column_name(column_name)
            hit = COLUMN_SYNONYMS.get(key)
            if hit:
                return hit[0]
            # fuzzy mot synonymer
            best, best_score = None, 0.0
            for syn, (target, _desc) in COLUMN_SYNONYMS.items():
                score = fuzzy_match(key, syn)
                if score > best_score:
                    best_score, best = score, target
            if best_score >= FUZZY_THRESHOLD:
                return best
            return None
        except Exception as exc:
            _log.exception("find_column failed: %s", exc)
            return None

    # 2. find_all_columns
    def find_all_columns(self, columns: List[str], source: str = "dispatch") -> Dict[str, str]:
        """Hitta alla matchande kolumner."""
        try:
            result: Dict[str, str] = {}
            for col in columns:
                tgt = self.find_column(col, source)
                if tgt:
                    result[col] = tgt
            return result
        except Exception as exc:
            _log.exception("find_all_columns failed: %s", exc)
            return {}

    # 3. match_dispatch_data
    def match_dispatch_data(self, records: List[Dict[str, Any]], skip_registered: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Matcha dispatch-data mot register."""
        try:
            matcher = self._get_matcher()
            vin_reg = self._get_vin_registry()
            dealers = get_plugin_safe(self.app, "dealers_manager")
            colors = get_plugin_safe(self.app, "colors_manager")
            results, summary = matcher.match_records(
                records,
                vehicle_registry=vin_reg,
                dealers_manager=dealers,
                colors_manager=colors,
                skip_registered=skip_registered,
            )
            emit_event_safe(self.app, "data_mapping:matched", summary.to_dict())
            return [r.to_dict() for r in results], summary.to_dict()
        except Exception as exc:
            _log.exception("match_dispatch_data failed: %s", exc)
            return [], {"total": 0, "ok": 0, "error": str(exc)}

    # 4. get_config
    def get_config(self) -> Dict[str, Any]:
        """Hämta mappningskonfiguration."""
        try:
            mapper = self._get_mapper()
            return mapper.config.to_dict()
        except Exception:
            return MappingConfig().to_dict()

    # 5. add_custom_mapping
    def add_custom_mapping(self, source: str, field: str, column: str) -> bool:
        """Lägg till custom mapping."""
        try:
            mapper = self._get_mapper()
            ds = DataSource.from_string(source)
            mapper.add_custom_mapping(ds, field, column)
            # även till externa servicen
            ext = self._get_external_mapping_service()
            if ext and hasattr(ext, "set_mapping"):
                ext.set_mapping(column, field.upper(), f"Custom {source}:{field}", auto_detected=False, confidence=1.0, auto_save=True)
            emit_event_safe(self.app, "data_mapping:custom_mapping_added", {"source": source, "field": field, "column": column})
            return True
        except Exception as exc:
            _log.exception("add_custom_mapping failed: %s", exc)
            return False

    # 6. remove_custom_mapping
    def remove_custom_mapping(self, source: str, field: str) -> bool:
        try:
            mapper = self._get_mapper()
            ds = DataSource.from_string(source)
            return mapper.remove_custom_mapping(ds, field)
        except Exception as exc:
            _log.exception("remove_custom_mapping failed: %s", exc)
            return False

    # 7. reset_mappings
    def reset_mappings(self) -> bool:
        try:
            mapper = self._get_mapper()
            mapper.reset_to_defaults()
            ext = self._get_external_mapping_service()
            if ext and hasattr(ext, "clear_all"):
                ext.clear_all(auto_save=True)
            emit_event_safe(self.app, "data_mapping:reset", {})
            return True
        except Exception as exc:
            _log.exception("reset_mappings failed: %s", exc)
            return False

    # 8. export_mappings
    def export_mappings(self, filepath: str) -> bool:
        try:
            ext = self._get_external_mapping_service()
            if ext and hasattr(ext, "get_all_as_dicts"):
                data = ext.get_all_as_dicts()
            else:
                mapper = self._get_mapper()
                data = mapper.config.to_dict()
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            return True
        except Exception as exc:
            _log.exception("export_mappings failed: %s", exc)
            return False

    # 9. import_mappings
    def import_mappings(self, filepath: str) -> bool:
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            # enkel import – stöder både list och dict-format
            ext = self._get_external_mapping_service()
            if ext and isinstance(data, list):
                for item in data:
                    src = item.get("source", "")
                    tgt = item.get("target", "")
                    desc = item.get("description", "")
                    if src and tgt and hasattr(ext, "set_mapping"):
                        ext.set_mapping(src, tgt, desc, auto_detected=False, confidence=1.0, auto_save=False)
                if hasattr(ext, "save"):
                    ext.save()
                emit_event_safe(self.app, "data_mapping:imported", {"count": len(data)})
                return True
            return False
        except Exception as exc:
            _log.exception("import_mappings failed: %s", exc)
            return False

    # 10. validate_mapping
    def validate_mapping(self, source: str, target: str) -> Tuple[bool, str]:
        try:
            if not source or not target:
                return False, "Källa och mål måste anges"
            # target måste vara en känd TS-kolumn
            known_targets = {t for t, _d in COLUMN_SYNONYMS.values()}
            if target.upper() not in known_targets:
                return False, f"Okänt målfält: {target}"
            return True, "OK"
        except Exception as exc:
            return False, str(exc)

    # 11. get_field_suggestions
    def get_field_suggestions(self, column_name: str, source: str = "dispatch", limit: int = 5) -> List[Dict[str, Any]]:
        try:
            col_norm = normalize_column_name(column_name)
            suggestions = []
            for syn, (target, desc) in COLUMN_SYNONYMS.items():
                score = fuzzy_match(col_norm, syn)
                if score >= 0.4:
                    suggestions.append({"target": target, "confidence": round(score, 3), "description": desc, "matched_synonym": syn})
            suggestions.sort(key=lambda x: x["confidence"], reverse=True)
            return suggestions[:limit]
        except Exception as exc:
            _log.exception("get_field_suggestions failed: %s", exc)
            return []

    # 12. get_source_statistics
    def get_source_statistics(self) -> Dict[str, Any]:
        try:
            mapper = self._get_mapper()
            if hasattr(mapper, "get_statistics"):
                return mapper.get_statistics()
            return {"sources": list(DataSource.__members__.keys())}
        except Exception:
            return {}

    # 13. get_mapping_coverage
    def get_mapping_coverage(self, headers: List[str], source: str = "dispatch") -> Dict[str, Any]:
        try:
            mapping = self.find_all_columns(headers, source)
            total = len([h for h in headers if str(h).strip()])
            mapped = len(mapping)
            coverage = (mapped / total * 100) if total else 0.0
            unmapped = [h for h in headers if h not in mapping]
            return {
                "total_headers": total,
                "mapped": mapped,
                "unmapped": unmapped,
                "coverage_percent": round(coverage, 1),
            }
        except Exception as exc:
            _log.exception("get_mapping_coverage failed: %s", exc)
            return {"total_headers": 0, "mapped": 0, "unmapped": [], "coverage_percent": 0.0}

    # 14. generate_ts_file
    def generate_ts_file(self, vehicles: List[Dict[str, Any]], output_path: str) -> Dict[str, Any]:
        """Generera TS-fil – delegerar till ts_file_generator om tillgängligt."""
        try:
            ts_gen = get_plugin_safe(self.app, "ts_file_generator")
            if ts_gen and hasattr(ts_gen, "generate_complete_file"):
                return ts_gen.generate_complete_file(vehicles, output_path)
            # fallback: enkel latin-1 dump
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            lines = []
            for v in vehicles:
                vin = str(v.get("VIN", v.get("vincode", ""))).ljust(17)[:17]
                line = (vin + " " * (2500 - len(vin)))[:2500]
                lines.append(line)
            tmp = out.with_suffix(out.suffix + ".tmp")
            with open(tmp, "w", encoding="iso-8859-1", newline="\n") as fh:
                fh.write("\n".join(lines) + "\n")
            os.replace(tmp, out)
            result = GenerateResult(success=True, file_path=out, vehicles_count=len(vehicles))
            return result.to_dict()
        except Exception as exc:
            _log.exception("generate_ts_file failed: %s", exc)
            return GenerateResult(success=False, errors=[str(exc)]).to_dict()

    # 15. get_diagnostics
    def get_diagnostics(self) -> Dict[str, Any]:
        try:
            diag: Dict[str, Any] = {
                "version": VERSION,
                "copyright": get_copyright_string(),
                "pandas_available": PANDAS_AVAILABLE,
            }
            ext = self._get_external_mapping_service()
            if ext and hasattr(ext, "get_stats"):
                diag["mapping_service"] = ext.get_stats()
            vin_reg = self._get_vin_registry()
            if vin_reg and hasattr(vin_reg, "get_stats"):
                diag["vin_registry"] = vin_reg.get_stats()
            return diag
        except Exception as exc:
            _log.exception("get_diagnostics failed: %s", exc)
            return {"error": str(exc)}

    # 16. generate_ivi_batch
    def generate_ivi_batch(self, vins: List[str]) -> Dict[str, Any]:
        try:
            ereko = get_plugin_safe(self.app, "ereko")
            if ereko and hasattr(ereko, "generate_batch"):
                return ereko.generate_batch(vins)
            return {"success": False, "message": "ereko plugin saknas", "count": 0}
        except Exception as exc:
            _log.exception("generate_ivi_batch failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # 17. get_ts_field_mapping
    def get_ts_field_mapping(self, post_type: str = "PT45") -> Dict[str, Any]:
        try:
            ts_schema = get_plugin_safe(self.app, "ts_schema_manager")
            if ts_schema and hasattr(ts_schema, "get_schema"):
                schema = ts_schema.get_schema(post_type)
                if schema:
                    if hasattr(schema, "to_dict"):
                        return schema.to_dict()
                    return dict(schema)
            return {"post_type": post_type, "fields": []}
        except Exception as exc:
            _log.exception("get_ts_field_mapping failed: %s", exc)
            return {"error": str(exc)}

    # 18. get_collaboration_status
    def get_collaboration_status(self) -> Dict[str, bool]:
        plugins = [
            "ts_spec_import", "ts_schema_manager", "ts_file_generator",
            "vehicle_registry", "colors_manager", "dealers_manager",
            "dispatch_viewer", "ereko", "sap_import",
        ]
        status: Dict[str, bool] = {}
        for name in plugins:
            status[name] = get_plugin_safe(self.app, name) is not None
        return status

    # 19. import_vehicle_excel
    def import_vehicle_excel(self, filepath: str, sheet_filter: Optional[List[str]] = None) -> Dict[str, Any]:
        """Importera fordonsdata från Excel, ett blad per årsmodell, ignorera 25Kw."""
        status = VehicleImportStatus(filepath=filepath, imported_at=datetime.now().isoformat())
        try:
            if not PANDAS_AVAILABLE:
                raise RuntimeError("pandas saknas – installera pandas openpyxl")
            path = Path(filepath)
            if not path.exists():
                status.errors.append(f"Filen hittades inte: {filepath}")
                return status.to_dict()

            xls = pd.ExcelFile(path)
            all_headers: Set[str] = set()
            total_rows = 0
            for sheet in xls.sheet_names:
                if should_skip_sheet(sheet, sheet_filter or SKIP_SHEETS_DEFAULT):
                    status.sheets_skipped.append(sheet)
                    continue
                try:
                    df = pd.read_excel(xls, sheet_name=sheet, dtype=str).fillna("")
                    headers = [str(c).strip() for c in df.columns if str(c).strip()]
                    all_headers.update(headers)
                    total_rows += len(df)
                    status.sheets_processed.append(sheet)
                except Exception as exc:
                    status.errors.append(f"Blad {sheet}: {exc}")
                    status.sheets_skipped.append(sheet)

            headers_list = sorted(all_headers)
            status.headers = headers_list
            status.total_rows = total_rows

            # spara headers till imported_headers.json
            try:
                out_path = Path("data/mappings/imported_headers.json")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(out_path, {
                    "updated_at": datetime.now().isoformat(),
                    "source_file": str(path),
                    "headers": headers_list,
                    "sheets_processed": status.sheets_processed,
                    "sheets_skipped": status.sheets_skipped,
                })
            except Exception:
                pass

            # auto-populera / auto-detect mappings
            ext = self._get_external_mapping_service()
            mapped_count = 0
            if ext:
                try:
                    if hasattr(ext, "auto_populate_from_headers"):
                        ext.auto_populate_from_headers(headers_list, auto_save=False)
                    if hasattr(ext, "auto_detect"):
                        detected = ext.auto_detect(headers_list, overwrite_existing=False, auto_save=True)
                        mapped_count = len(detected)
                    elif hasattr(ext, "save"):
                        ext.save()
                except Exception:
                    pass
            status.mappings_auto_detected = mapped_count
            status.imported = True
            self._vehicle_import_status = status

            emit_event_safe(self.app, "data_mapping:vehicle_excel_imported", status.to_dict())
            return status.to_dict()
        except Exception as exc:
            _log.exception("import_vehicle_excel failed: %s", exc)
            status.errors.append(str(exc))
            return status.to_dict()

    # 20. get_vehicle_import_status
    def get_vehicle_import_status(self) -> Dict[str, Any]:
        """Status för senaste Excel-import."""
        try:
            return self._vehicle_import_status.to_dict()
        except Exception:
            return VehicleImportStatus().to_dict()

    # ══════════════════════════════════════════════════════════════
    # EXTRA: Fordonsdata-mappning dialog – för widget.ImportTab
    # ══════════════════════════════════════════════════════════════

    def open_vehicle_import_mapping_dialog(self, parent: Optional[QWidget] = None) -> bool:
        """
        Öppnar dialog för manuell kolumnmappning av fordonsdata.
        Används av widget.ImportTab -> Fordonsdata-mappning knappen.
        """
        try:
            from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QMessageBox, QInputDialog, QHeaderView, QLineEdit
            from PySide6.QtCore import Qt

            if parent is None:
                try:
                    parent = QApplication.activeWindow()
                except Exception:
                    parent = None

            # ladda befintlig mapping
            mapping_path = Path("data") / "mappings" / "vehicle_import_mapping.json"
            existing_mapping: Dict[str, str] = {}
            if mapping_path.exists():
                try:
                    with open(mapping_path, "r", encoding="utf-8") as f:
                        existing_mapping = json.load(f).get("mappings", {})
                except Exception:
                    pass

            # hämta headers från senaste import
            headers: List[str] = []
            try:
                imported_headers_path = Path("data/mappings/imported_headers.json")
                if imported_headers_path.exists():
                    with open(imported_headers_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        headers = data.get("headers", [])
            except Exception:
                pass

            # TS-målfält – de 32
            target_fields = [
                "MODELYEAR", "VINCODE", "TYPE", "VARIANTE", "VERSION",
                "MODELNAME", "COMNAME", "CLASS", "VEHCAT2", "APPROVAL",
                "DATEAPP", "NUMAXLE", "NUMWHEEL", "ANTILBS", "LENGTH",
                "WIDTH", "HEIGHT", "MASS", "LADENMASS", "CYLCAPACITY",
                "MAXPOWER", "MAXNET", "SPEED", "TYRESIZE1", "TYRESIZE2",
                "SEATS", "EMISLVL", "STATIONARY", "STATENG", "DRIVEBY",
                "EMSTAGE", "EECO2E"
            ]

            dialog = QDialog(parent)
            dialog.setWindowTitle("Fordonsdata – Kolumnmappning")
            dialog.resize(720, 520)
            dialog.setObjectName("VehicleMappingDialog")

            layout = QVBoxLayout(dialog)

            title = QLabel("Matcha Excel-kolumner mot TS-målfält")
            title.setStyleSheet("font-weight: bold; font-size: 14px;")
            layout.addWidget(title)

            table = QTableWidget()
            table.setObjectName("VehicleMappingTable")
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(["Excel-kolumn (källa)", "TS-målfält"])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.setRowCount(len(target_fields))

            # reverse mapping: app_field -> sap_col
            rev_map = {v: k for k, v in existing_mapping.items()}

            for i, field in enumerate(target_fields):
                # TS-mål (kolumn 1, read-only)
                item_target = QTableWidgetItem(field)
                item_target.setFlags(item_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(i, 1, item_target)
                # Excel-källa (kolumn 0, editbar)
                sap_col = rev_map.get(field, "")
                table.setItem(i, 0, QTableWidgetItem(sap_col))

            layout.addWidget(table, 1)

            btn_layout = QHBoxLayout()
            save_btn = QPushButton("Spara mappning")
            save_btn.setObjectName("SuccessButton")
            cancel_btn = QPushButton("Avbryt")
            cancel_btn.setObjectName("SecondaryButton")
            btn_layout.addStretch(1)
            btn_layout.addWidget(save_btn)
            btn_layout.addWidget(cancel_btn)
            layout.addLayout(btn_layout)

            def try_save():
                # om det redan finns en mappning – kräv lösenord
                if existing_mapping:
                    # försök via dealers_manager password_manager om tillgängligt
                    password_ok = True
                    dealers = get_plugin_safe(self.app, "dealers_manager")
                    pwd_mgr = None
                    if dealers and hasattr(dealers, "password_manager"):
                        try:
                            pwd_mgr = dealers.password_manager
                        except Exception:
                            pwd_mgr = None
                    from PySide6.QtWidgets import QInputDialog
                    password, ok = QInputDialog.getText(
                        dialog, "Lösenord krävs", "Ange lösenord för att ändra mappning:",
                        QLineEdit.EchoMode.Password
                    )
                    if not ok:
                        return
                    # enkel verify – om password_manager finns, använd den, annars acceptera "admin"
                    verified = False
                    if pwd_mgr and hasattr(pwd_mgr, "verify"):
                        try:
                            verified = bool(pwd_mgr.verify(password))
                        except Exception:
                            verified = (password == "admin")
                    else:
                        verified = (password == "admin")
                    if not verified:
                        QMessageBox.warning(dialog, "Fel lösenord", "Fel lösenord – mappning sparades inte.")
                        return

                new_mapping: Dict[str, str] = {}
                for row in range(table.rowCount()):
                    sap_item = table.item(row, 0)
                    app_item = table.item(row, 1)
                    if sap_item and app_item:
                        sap_col = sap_item.text().strip()
                        app_field = app_item.text().strip()
                        if sap_col and app_field:
                            new_mapping[sap_col] = app_field

                try:
                    mapping_path.parent.mkdir(parents=True, exist_ok=True)
                    data = {
                        "version": "1.0",
                        "updated_at": datetime.now().isoformat(),
                        "copyright": get_copyright_string(),
                        "mappings": new_mapping
                    }
                    atomic_write_json(mapping_path, data)
                    # synka även till ColumnMappingService
                    ext = self._get_external_mapping_service()
                    if ext:
                        try:
                            for src, tgt in new_mapping.items():
                                if hasattr(ext, "set_mapping"):
                                    ext.set_mapping(src, tgt, "vehicle_import_manual", auto_detected=False, confidence=1.0, auto_save=False)
                            if hasattr(ext, "save"):
                                ext.save()
                        except Exception:
                            pass
                    QMessageBox.information(dialog, "Sparat", f"Mappningen har sparats.\n{len(new_mapping)} fält mappade.")
                    emit_event_safe(self.app, "data_mapping:mapping_changed", {"count": len(new_mapping)})
                    dialog.accept()
                except Exception as e:
                    QMessageBox.critical(dialog, "Fel", f"Kunde inte spara: {e}")

            save_btn.clicked.connect(try_save)
            cancel_btn.clicked.connect(dialog.reject)

            return dialog.exec() == QDialog.DialogCode.Accepted

        except Exception as exc:
            _log.exception("open_vehicle_import_mapping_dialog failed: %s", exc)
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(parent, "Fel", f"Kunde inte öppna mappningsdialog:\n{exc}")
            except Exception:
                pass
            return False

    def get_vehicle_import_mapping(self) -> Dict[str, str]:
        """Hämta sparad fordonsimport-mappning."""
        path = Path("data") / "mappings" / "vehicle_import_mapping.json"
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("mappings", {})
        except Exception:
            return {}


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "VERSION",
    "AUTHOR",
    "FUZZY_THRESHOLD",
    "SKIP_SHEETS_DEFAULT",
    "get_copyright_string",
    "DataSource",
    "FieldType",
    "MatchStatus",
    "ColumnMatch",
    "MappingConfig",
    "VehicleMatchResult",
    "MatchingSummary",
    "GenerateResult",
    "VehicleImportStatus",
    "_InternalColumnMappingService",
    "VehicleMatchingService",
    "get_plugin_safe",
    "get_event_bus",
    "emit_event_safe",
    "fuzzy_match",
    "Plugin",
]