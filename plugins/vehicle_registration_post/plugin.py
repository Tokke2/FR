# -*- coding: utf-8 -*-

# plugins/vehicle_registration_post/plugin.py

"""
Vehicle Registration Post Plugin v3.1.1

Genererar registreringsposter (PT45) för Transportstyrelsen.

TS-spec-driven, integrerad med ts_spec_import.

Ändringar v3.1.1 (Session 11 — granskad, spec v1.6 förbättringsregeln):
    - GRANSKAD: pluginet var dokumenterat i spec W.5 men EJ GRANSKAT.
    - HAS_PANDAS: Final-mönster ( _PANDAS_AVAILABLE -> HAS_PANDAS:
      Final[bool]) — konsistent med excel_importer v1.2.0.
    - initialize(): app-attribut (app.registration_post,
      app.vehicle_registration_post) sätts kraschsäkert i try/except.
    - DEPENDENCIES: Final[List[str]] (konsistent med övriga plugins).
    - OBSERVATION (EJ ändrad): fallback-strukturen i _generate_fallback
      innehåller dubblerade fält (MAXPOWER/MAXNET x2, SPEED x2,
      EECO2E x2). Lämnas oförändrad tills användaren beslutar (kan vara
      medvetet layout-val; TS-fältlayout kan inte verifieras här).
    - config.json (data/registration_post/config.json) ligger kvar
      enligt spec v1.4/Sektion Z (config.json-undantaget).

Ändringar v3.1.0:
    - Robusta helper-funktioner
    - Inga hårda dependencies
    - Förbättrad ts_spec_import integration
    - Lyssnar på ts_spec:imported event
    - Konsekvent Latin-1 encoding (iso-8859-1)
    - Bättre felhantering och logging
    - PostGenerator tar app istället för PluginManager
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Final, List, Optional, Tuple

try:
    import pandas as pd

    _PANDAS_AVAILABLE = True
except ImportError:
    pd = None
    _PANDAS_AVAILABLE = False

HAS_PANDAS: Final[bool] = _PANDAS_AVAILABLE

from core.plugin_base import PluginBase

_log = logging.getLogger(__name__)

POSTTYP_FORDON = "45"
RECORD_LENGTH = 2500
TS_ENCODING = "iso-8859-1"

VIN_LENGTH = 17
VIN_INVALID_CHARS = set("IOQ")
VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

MATCH_VIN_YEAR = "vin_year"
MATCH_VIN = "vin"
MATCH_ETG_YEAR = "etg_year"
MATCH_ETG = "etg"
MATCH_NONE = "none"

VERSION = "3.1.1"
AUTHOR = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return "Copyright © {} {}".format(datetime.now().year, AUTHOR)


# ══════════════════════════════════════════════════════════════════════════════
# ROBUST HELPER FUNCTIONS

# ══════════════════════════════════════════════════════════════════════════════


def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """Robust plugin-hämtning som fungerar oavsett app-konfiguration."""
    if app is None:
        return None

    candidates = [name, name.replace("-", "_").lower()]

    for candidate in candidates:
        try:
            if hasattr(app, "get_plugin") and callable(app.get_plugin):
                result = app.get_plugin(candidate)
                if result is not None:
                    return result
        except Exception:
            pass

        try:
            loader = getattr(app, "plugin_loader", None)
            if loader and hasattr(loader, "get_plugin"):
                result = loader.get_plugin(candidate)
                if result is not None:
                    return result
        except Exception:
            pass

        try:
            manager = getattr(app, "plugin_manager", None)
            if manager and hasattr(manager, "get_plugin"):
                result = manager.get_plugin(candidate)
                if result is not None:
                    return result
        except Exception:
            pass

        try:
            if hasattr(app, candidate):
                result = getattr(app, candidate)
                if result is not None:
                    return result
        except Exception:
            pass

    return None


def get_event_bus(app: Any) -> Optional[Any]:
    """Hämta event bus från app."""
    if app is None:
        return None

    if hasattr(app, "event_bus") and app.event_bus is not None:
        return app.event_bus

    if hasattr(app, "events") and app.events is not None:
        return app.events

    events_plugin = get_plugin_safe(app, "core_events")
    if events_plugin is not None:
        if hasattr(events_plugin, "bus"):
            return events_plugin.bus
        if hasattr(events_plugin, "emit"):
            return events_plugin

    return None


def emit_event_safe(
    app: Any,
    event_name: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Emit event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False

    payload = data or {}

    try:
        if hasattr(bus, "emit") and callable(bus.emit):
            bus.emit(event_name, payload)
            return True
        if hasattr(bus, "publish") and callable(bus.publish):
            bus.publish(event_name, payload)
            return True
    except Exception as exc:
        _log.debug("Could not emit event '%s': %s", event_name, exc)

    return False


def subscribe_event_safe(
    app: Any,
    event_name: str,
    handler: Callable,
) -> bool:
    """Prenumerera på event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False

    try:
        if hasattr(bus, "on") and callable(bus.on):
            bus.on(event_name, handler)
            return True
        if hasattr(bus, "subscribe") and callable(bus.subscribe):
            bus.subscribe(event_name, handler)
            return True
    except Exception as exc:
        _log.debug("Could not subscribe to '%s': %s", event_name, exc)

    return False


def unsubscribe_event_safe(
    app: Any,
    event_name: str,
    handler: Callable,
) -> bool:
    """Avprenumerera från event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False

    try:
        if hasattr(bus, "off") and callable(bus.off):
            bus.off(event_name, handler)
            return True
        if hasattr(bus, "unsubscribe") and callable(bus.unsubscribe):
            bus.unsubscribe(event_name, handler)
            return True
    except Exception as exc:
        _log.debug("Could not unsubscribe from '%s': %s", event_name, exc)

    return False


def get_app_config(app: Any, key: str, default: Any = None) -> Any:
    """Hämta config-värde robust."""
    if app is None:
        return default

    try:
        config = getattr(app, "config", None)
        if config and hasattr(config, "get"):
            result = config.get(key, default)
            if result is not None:
                return result
        elif isinstance(config, dict):
            result = config.get(key, default)
            if result is not None:
                return result
    except Exception:
        pass

    config_plugin = get_plugin_safe(app, "core_config")
    if config_plugin is not None:
        try:
            if hasattr(config_plugin, "get_config_value") and callable(
                config_plugin.get_config_value
            ):
                result = config_plugin.get_config_value(key, default)
                if result is not None:
                    return result
            if hasattr(config_plugin, "get") and callable(config_plugin.get):
                result = config_plugin.get(key, default)
                if result is not None:
                    return result
        except Exception:
            pass

    return default


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION

# ══════════════════════════════════════════════════════════════════════════════


@dataclass

class RegistrationConfig:
    """Konfiguration för registreringsposter."""

    dispatch_columns: Dict[str, str] = field(
        default_factory=lambda: {
            "vin": "VIN",
            "model_year": "Model Year",
            "etg": "ETG Number",
            "color": "Color",
            "customer_number": "Sold to Dealer",
            "dealer_name": "Sold to Name",
        }
    )

    sap_columns: Dict[str, str] = field(
        default_factory=lambda: {
            "vincode": "VINCODE",
            "modelyear": "MODELYEAR",
            "approval": "APPROVAL",
            "color_code": "COLORCODE",
            "type": "TYPE",
            "variant": "VARIANTE",
            "version": "VERSION",
        }
    )

    match_strategy: str = "best"
    allow_partial_matches: bool = True
    require_year_match: bool = False
    validate_vin_length: bool = True
    min_vin_length: int = 17

    validate_post_length: bool = True
    post_length: int = RECORD_LENGTH
    post_type: str = POSTTYP_FORDON
    use_ts_spec_schema: bool = True

    output_dir: str = "ut"
    output_encoding: str = TS_ENCODING

    @classmethod

    def from_dict(cls, data: Dict[str, Any]) -> "RegistrationConfig":
        valid_keys = set(cls.__dataclass_fields__.keys())
        filtered = {
            key: value for key, value in data.items() if key in valid_keys
        }
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dispatch_columns": self.dispatch_columns,
            "sap_columns": self.sap_columns,
            "match_strategy": self.match_strategy,
            "allow_partial_matches": self.allow_partial_matches,
            "require_year_match": self.require_year_match,
            "validate_vin_length": self.validate_vin_length,
            "min_vin_length": self.min_vin_length,
            "validate_post_length": self.validate_post_length,
            "post_length": self.post_length,
            "post_type": self.post_type,
            "use_ts_spec_schema": self.use_ts_spec_schema,
            "output_dir": self.output_dir,
            "output_encoding": self.output_encoding,
        }


@dataclass

class MatchStatistics:
    """Statistik för matchning."""

    total_dispatch: int = 0
    total_sap: int = 0

    vin_year_matches: int = 0
    vin_matches: int = 0
    etg_year_matches: int = 0
    etg_matches: int = 0
    no_match: int = 0

    invalid_vins: int = 0
    missing_years: int = 0

    def total_matched(self) -> int:
        return (
            self.vin_year_matches
            + self.vin_matches
            + self.etg_year_matches
            + self.etg_matches
        )

    def match_rate(self) -> float:
        if self.total_dispatch == 0:
            return 0.0
        return (self.total_matched() / self.total_dispatch) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_dispatch": self.total_dispatch,
            "total_sap": self.total_sap,
            "matched": self.total_matched(),
            "match_rate": "{:.1f}%".format(self.match_rate()),
            "breakdown": {
                "vin_year": self.vin_year_matches,
                "vin_only": self.vin_matches,
                "etg_year": self.etg_year_matches,
                "etg_only": self.etg_matches,
                "no_match": self.no_match,
            },
            "issues": {
                "invalid_vins": self.invalid_vins,
                "missing_years": self.missing_years,
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# FIELD FORMATTER

# ══════════════════════════════════════════════════════════════════════════════


class FieldFormatter:
    """Formaterar fält enligt TS-specifikation."""

    def __init__(self, app: Any = None):
        self.app = app
        self._date_converter = None
        self._setup_integrations()

    def _setup_integrations(self) -> None:
        """Konfigurera integrationer."""
        if self.app is None:
            return

        try:
            sap_import = get_plugin_safe(self.app, "sap_import")
            if sap_import and hasattr(sap_import, "DateConverter"):
                self._date_converter = sap_import.DateConverter(self.app)
        except Exception:
            pass

    def text(self, value: Any, length: int) -> str:
        """Vänsterjusterat textfält."""
        if value is None:
            value = ""

        text_value = str(value).strip()[:length]

        try:
            text_value.encode(TS_ENCODING)
        except UnicodeEncodeError:
            text_value = (
                text_value.encode(TS_ENCODING, errors="replace")
                .decode(TS_ENCODING)
            )

        return text_value.ljust(length, " ")

    def numeric(self, value: Any, length: int) -> str:
        """Högerjusterat numeriskt fält."""
        if value is None or value == "":
            return "0" * length

        numeric_value = re.sub(r"\D+", "", str(value))
        if not numeric_value:
            return "0" * length

        if len(numeric_value) > length:
            numeric_value = numeric_value[-length:]

        return numeric_value.rjust(length, "0")

    def date_yymmdd(self, value: Any) -> str:
        """Datum som YYMMDD."""
        if self._date_converter:
            try:
                return self._date_converter.to_ts_date(
                    value,
                    format="YYMMDD",
                    allow_unknown=True,
                )
            except Exception:
                pass

        return self._format_date_fallback(value, 6)

    def date_yyyymmdd(self, value: Any) -> str:
        """Datum som YYYYMMDD."""
        if self._date_converter:
            try:
                return self._date_converter.to_ts_date(
                    value,
                    format="YYYYMMDD",
                    allow_unknown=True,
                )
            except Exception:
                pass

        return self._format_date_fallback(value, 8)

    def _format_date_fallback(self, value: Any, length: int) -> str:
        """Fallback datumformattering."""
        if value is None or value == "":
            return "0" * length

        try:
            if HAS_PANDAS:
                converted = pd.to_datetime(
                    str(value), dayfirst=True, errors="coerce"
                )
                if pd.notna(converted):
                    return converted.strftime(
                        "%y%m%d" if length == 6 else "%Y%m%d"
                    )
        except Exception:
            pass

        digits = re.sub(r"\D+", "", str(value))
        return digits[-length:].zfill(length) if digits else "0" * length

    def boolean(
        self,
        value: Any,
        true_val: str = "1",
        false_val: str = "0",
    ) -> str:
        """Boolean-värde."""
        if value in (
            True, "True", "true", "1", "yes", "Yes", "YES",
            "ja", "Ja", "JA",
        ):
            return true_val
        return false_val

    def format_field_by_type(
        self,
        value: Any,
        data_type: str,
        length: int,
    ) -> str:
        """Formatera fält baserat på datatyp."""
        if data_type in {"A", "AN"}:
            return self.text(value, length)
        if data_type == "N":
            return self.numeric(value, length)
        if data_type == "D6":
            return self.date_yymmdd(value)
        if data_type == "D8":
            return self.date_yyyymmdd(value)
        return self.text(value, length)


# ══════════════════════════════════════════════════════════════════════════════
# VEHICLE DATA NORMALIZER

# ══════════════════════════════════════════════════════════════════════════════


class VehicleDataNormalizer:
    """Normaliserar fordonsdata för matchning."""

    def __init__(self, app: Any = None):
        self.app = app

    def sanitize_vin(self, value: Any) -> str:
        """Sanera VIN-nummer."""
        if value is None or value == "":
            return ""

        vin = str(value).strip().upper()
        vin = re.sub(r"[^A-Z0-9]", "", vin)

        for char in VIN_INVALID_CHARS:
            vin = vin.replace(char, "")

        return vin

    def normalize_etg(self, value: Any) -> str:
        """Normalisera ETG/typgodkännandenummer."""
        if value is None or value == "":
            return ""
        return str(value).strip().upper()

    def normalize_model_year(self, value: Any) -> str:
        """Normalisera årsmodell till YYYY."""
        if value is None or value == "":
            return ""

        year_text = str(value).strip().upper()

        if year_text in {"NAN", "NONE", "NULL", ""}:
            return ""

        if re.fullmatch(r"20\d{2}", year_text):
            return year_text

        my_match = re.search(
            r"MY\s*(\d{2,4})", year_text, re.IGNORECASE
        )
        if my_match:
            year_str = my_match.group(1)
            if len(year_str) == 2:
                return "20{}".format(year_str)
            if len(year_str) == 4 and year_str.startswith("20"):
                return year_str

        short_match = re.search(r"\b(\d{2})\b", year_text)
        if short_match:
            yy = int(short_match.group(1))
            return "20{:02d}".format(yy)

        try:
            numeric_year = int(float(year_text.replace(",", ".")))
            if 2000 <= numeric_year <= 2099:
                return str(numeric_year)
            if 0 <= numeric_year <= 99:
                return "20{:02d}".format(numeric_year)
        except (ValueError, OverflowError):
            pass

        full_match = re.search(r"\b(20\d{2})\b", year_text)
        if full_match:
            return full_match.group(1)

        return ""

    def normalize_color(self, value: Any) -> str:
        """Normalisera färgnamn."""
        if value is None:
            return ""
        return re.sub(r"\s+", " ", str(value).strip().lower())

    def normalize_dealer_code(self, value: Any) -> str:
        """Normalisera återförsäljarkod."""
        if value is None:
            return ""
        return str(value).strip().upper().replace(" ", "")

    def is_valid_vin(self, vin: str) -> bool:
        """Validera VIN-format."""
        if not isinstance(vin, str) or len(vin) != VIN_LENGTH:
            return False
        if any(char in VIN_INVALID_CHARS for char in vin):
            return False
        return VIN_PATTERN.match(vin) is not None


# ══════════════════════════════════════════════════════════════════════════════
# DATA MATCHER

# ══════════════════════════════════════════════════════════════════════════════


class DataMatcher:
    """Matchar dispatch-data mot SAP-data."""

    def __init__(self, config: RegistrationConfig, app: Any = None):
        self.config = config
        self.app = app
        self.normalizer = VehicleDataNormalizer(app)
        self.stats = MatchStatistics()

    def match_dispatch_to_sap(
        self,
        dispatch_df: Any,
        sap_df: Any,
    ) -> Tuple[List[Dict[str, Any]], MatchStatistics]:
        """Matcha dispatch mot SAP."""
        if not HAS_PANDAS:
            raise ImportError("pandas krävs för matchning")

        _log.info(
            "Matchning: %s dispatch ↔ %s SAP",
            len(dispatch_df),
            len(sap_df),
        )

        self.stats = MatchStatistics()
        self.stats.total_dispatch = len(dispatch_df)
        self.stats.total_sap = len(sap_df)

        dispatch_norm = self._normalize_dispatch(dispatch_df)
        sap_norm = self._normalize_sap(sap_df)

        sap_indices = self._build_sap_indices(sap_norm)

        matches: List[Dict[str, Any]] = []
        for idx, row in dispatch_norm.iterrows():
            match = self._find_best_match(row, sap_indices)
            if match:
                matches.append(
                    {
                        "dispatch": row.to_dict(),
                        "sap": match["data"],
                        "match_type": match["type"],
                        "match_score": match["score"],
                        "row_index": idx,
                    }
                )
            else:
                self.stats.no_match += 1

        self._log_statistics()
        return matches, self.stats

    def _normalize_dispatch(self, df: Any) -> Any:
        """Normalisera dispatch-data."""
        df = df.copy()

        vin_col = self.config.dispatch_columns.get("vin", "VIN")
        year_col = self.config.dispatch_columns.get(
            "model_year", "Model Year"
        )
        etg_col = self.config.dispatch_columns.get("etg", "ETG Number")

        df["_VIN_N"] = df.get(vin_col, pd.Series(dtype=str)).apply(
            self.normalizer.sanitize_vin
        )
        df["_YEAR_N"] = df.get(year_col, pd.Series(dtype=str)).apply(
            self.normalizer.normalize_model_year
        )
        df["_ETG_N"] = df.get(etg_col, pd.Series(dtype=str)).apply(
            self.normalizer.normalize_etg
        )

        self.stats.invalid_vins = int((df["_VIN_N"] == "").sum())
        self.stats.missing_years = int((df["_YEAR_N"] == "").sum())

        return df

    def _normalize_sap(self, df: Any) -> Any:
        """Normalisera SAP-data."""
        df = df.copy()

        vin_col = self.config.sap_columns.get("vincode", "VINCODE")
        year_col = self.config.sap_columns.get("modelyear", "MODELYEAR")
        etg_col = self.config.sap_columns.get("approval", "APPROVAL")

        df["_VIN_N"] = df.get(vin_col, pd.Series(dtype=str)).apply(
            self.normalizer.sanitize_vin
        )
        df["_YEAR_N"] = df.get(year_col, pd.Series(dtype=str)).apply(
            self.normalizer.normalize_model_year
        )
        df["_ETG_N"] = df.get(etg_col, pd.Series(dtype=str)).apply(
            self.normalizer.normalize_etg
        )

        return df

    def _build_sap_indices(self, sap_df: Any) -> Dict[str, Any]:
        """Bygg index för snabb matchning."""
        indices: Dict[str, Any] = {
            "vin": {},
            "vin_year": {},
            "etg": {},
            "etg_year": {},
        }

        for _, row in sap_df.iterrows():
            row_dict = row.to_dict()
            vin = row["_VIN_N"]
            year = row["_YEAR_N"]
            etg = row["_ETG_N"]

            if vin and len(vin) >= 11:
                indices["vin"][vin] = row_dict
                if year:
                    indices["vin_year"][(vin, year)] = row_dict

            if etg:
                indices["etg"].setdefault(etg, []).append(row_dict)
                if year:
                    indices["etg_year"].setdefault(
                        (etg, year), []
                    ).append(row_dict)

        _log.debug(
            "SAP index: %s VIN, %s ETG",
            len(indices["vin"]),
            len(indices["etg"]),
        )
        return indices

    def _find_best_match(
        self,
        dispatch_row: Any,
        sap_indices: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Hitta bästa matchning."""
        vin = dispatch_row.get("_VIN_N", "")
        year = dispatch_row.get("_YEAR_N", "")
        etg = dispatch_row.get("_ETG_N", "")

        if (
            self.config.validate_vin_length
            and vin
            and len(vin) < self.config.min_vin_length
        ):
            return None

        if vin and year and (vin, year) in sap_indices["vin_year"]:
            self.stats.vin_year_matches += 1
            return {
                "data": sap_indices["vin_year"][(vin, year)],
                "type": MATCH_VIN_YEAR,
                "score": 100.0,
            }

        if vin and vin in sap_indices["vin"]:
            self.stats.vin_matches += 1
            return {
                "data": sap_indices["vin"][vin],
                "type": MATCH_VIN,
                "score": 90.0,
            }

        if etg and year and (etg, year) in sap_indices["etg_year"]:
            matches = sap_indices["etg_year"][(etg, year)]
            if matches:
                self.stats.etg_year_matches += 1
                return {
                    "data": matches[0],
                    "type": MATCH_ETG_YEAR,
                    "score": 70.0,
                }

        if (
            self.config.allow_partial_matches
            and etg
            and etg in sap_indices["etg"]
        ):
            matches = sap_indices["etg"][etg]
            if matches:
                self.stats.etg_matches += 1
                return {
                    "data": matches[0],
                    "type": MATCH_ETG,
                    "score": 50.0,
                }

        return None

    def _log_statistics(self) -> None:
        _log.info(
            "Matchade: %s (%.1f%%) | VIN+År: %s, VIN: %s | "
            "ETG+År: %s, ETG: %s | Omatchade: %s",
            self.stats.total_matched(),
            self.stats.match_rate(),
            self.stats.vin_year_matches,
            self.stats.vin_matches,
            self.stats.etg_year_matches,
            self.stats.etg_matches,
            self.stats.no_match,
        )


# ══════════════════════════════════════════════════════════════════════════════
# POST GENERATOR

# ══════════════════════════════════════════════════════════════════════════════


class PostGenerator:
    """Genererar PT45-poster för Transportstyrelsen."""

    def __init__(self, config: RegistrationConfig, app: Any = None):
        self.config = config
        self.app = app
        self.formatter = FieldFormatter(app)
        self._schema = None
        self._schema_loaded = False

    @property

    def schema(self) -> Any:
        """Hämta PT45-schema (lazy loading)."""
        if not self._schema_loaded:
            self._load_schema()
        return self._schema

    def _load_schema(self) -> None:
        """Ladda PT45-schema från ts_spec_import."""
        self._schema_loaded = True
        self._schema = None

        if not self.config.use_ts_spec_schema or self.app is None:
            return

        ts_spec = get_plugin_safe(self.app, "ts_spec_import")
        if ts_spec is None:
            ts_spec = getattr(self.app, "ts_spec_import", None)

        if ts_spec and hasattr(ts_spec, "get_schema"):
            try:
                self._schema = ts_spec.get_schema("45")
                if self._schema:
                    version = getattr(self._schema, "version", "okänd")
                    _log.info("Loaded PT45 schema (version: %s)", version)
            except Exception as exc:
                _log.warning("Could not load PT45 schema: %s", exc)

    def invalidate_schema_cache(self) -> None:
        """Rensa cachad schema."""
        self._schema = None
        self._schema_loaded = False
        _log.debug("PT45 schema cache invalidated")

    def generate_posts(
        self,
        matches: List[Dict[str, Any]],
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Generera poster från matchningar."""
        posts: List[str] = []
        errors: List[Dict[str, Any]] = []

        _log.info("Genererar %s poster...", len(matches))

        has_schema = self.schema is not None

        for index, match in enumerate(matches, start=1):
            try:
                if has_schema:
                    post = self._generate_via_schema(
                        dispatch=match["dispatch"],
                        sap=match["sap"],
                        running_number=index,
                    )
                else:
                    post = self._generate_fallback(
                        dispatch=match["dispatch"],
                        sap=match["sap"],
                        running_number=index,
                    )

                if len(post) != self.config.post_length:
                    _log.warning(
                        "Post %s: %s chars, expected %s",
                        index,
                        len(post),
                        self.config.post_length,
                    )
                    post = post[: self.config.post_length].ljust(
                        self.config.post_length
                    )

                try:
                    post.encode(TS_ENCODING)
                except UnicodeEncodeError:
                    post = (
                        post.encode(TS_ENCODING, errors="replace")
                        .decode(TS_ENCODING)
                    )
                    _log.warning(
                        "Post %s: Replaced non-Latin-1 characters", index
                    )

                posts.append(post)

            except Exception as exc:
                error_info = {
                    "row": index,
                    "error": str(exc),
                    "vin": str(match["dispatch"].get("_VIN_N", "N/A"))[:10],
                }
                errors.append(error_info)
                _log.error("Post %s: %s", index, exc)

        _log.info("Genererade %s poster (%s fel)", len(posts), len(errors))
        return posts, errors

    def generate_posts_from_matched(
        self,
        vehicles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generera poster från redan matchade fordon."""
        posts: List[str] = []
        vins: List[str] = []
        errors: List[Dict[str, Any]] = []

        has_schema = self.schema is not None

        for index, vehicle in enumerate(vehicles, start=1):
            try:
                if has_schema:
                    post = self._generate_via_schema_from_vehicle(
                        vehicle, index
                    )
                else:
                    post = self._generate_fallback_from_vehicle(
                        vehicle, index
                    )

                if len(post) != self.config.post_length:
                    post = post[: self.config.post_length].ljust(
                        self.config.post_length
                    )

                try:
                    post.encode(TS_ENCODING)
                except UnicodeEncodeError:
                    post = (
                        post.encode(TS_ENCODING, errors="replace")
                        .decode(TS_ENCODING)
                    )

                posts.append(post)
                vins.append(vehicle.get("_vin", ""))

            except Exception as exc:
                _log.error("Post %s: %s", index, exc)
                errors.append({"row": index, "error": str(exc)})

        return {
            "success": len(posts) > 0,
            "posts": posts,
            "count": len(posts),
            "vins": vins,
            "errors": errors,
            "used_schema": has_schema,
        }

    def _generate_via_schema(
        self,
        dispatch: Dict[str, Any],
        sap: Dict[str, Any],
        running_number: int,
    ) -> str:
        """Generera post via ts_spec_import-schema."""
        data = self._map_to_ts_fields(dispatch, sap, running_number)
        return self._schema.format_record(data)

    def _generate_via_schema_from_vehicle(
        self,
        vehicle: Dict[str, Any],
        running_number: int,
    ) -> str:
        """Generera post via schema från matchat fordon."""
        data = {
            "POSTTYP": self.config.post_type,
            "LOPNUMMER": str(running_number).zfill(4),
            "LÖPNUMMER": str(running_number).zfill(4),
            "VIN": vehicle.get("_vin", ""),
            "UNDERSTÄLLSNUMMER": vehicle.get("_vin", ""),
            "MODELLÅR": vehicle.get("_model_year", ""),
            "MODEL_YEAR": vehicle.get("_model_year", ""),
            "TYPGODKÄNNANDENUMMER": vehicle.get(
                "APPROVAL", vehicle.get("_etg", "")
            ),
            "ETG": vehicle.get("APPROVAL", vehicle.get("_etg", "")),
            "APPROVAL": vehicle.get("APPROVAL", vehicle.get("_etg", "")),
            "HANDELSBETECKNING": vehicle.get(
                "MODELNAME", vehicle.get("MODEL", "")
            ),
            "FÄRGKOD": vehicle.get("_color_ts", ""),
            "COLOR": vehicle.get("_color_ts", ""),
            "KUNDNUMMER": vehicle.get("_owner", ""),
            "CUSTOMER": vehicle.get("_owner", ""),
            "TYPE": vehicle.get("TYPE", ""),
            "VARIANTE": vehicle.get("VARIANTE", ""),
            "VERSION": vehicle.get("VERSION", ""),
            "COMNAME": vehicle.get("COMNAME", ""),
            "CLASS": vehicle.get("CLASS", ""),
            "VEHCAT2": vehicle.get("VEHCAT2", ""),
            "NUMAXLE": vehicle.get("NUMAXLE", ""),
            "NUMWHEEL": vehicle.get("NUMWHEEL", ""),
            "LENGTH": vehicle.get("LENGTH", ""),
            "WIDTH": vehicle.get("WIDTH", ""),
            "HEIGHT": vehicle.get("HEIGHT", ""),
            "MASS": vehicle.get("MASS", ""),
            "LADENMASS": vehicle.get("LADENMASS", ""),
            "CYLCAPACITY": vehicle.get("CYLCAPACITY", ""),
            "MAXPOWER": vehicle.get("MAXPOWER", ""),
            "MAXNET": vehicle.get("MAXNET", ""),
            "FUEL": vehicle.get("FUEL", ""),
            "SPEED": vehicle.get("SPEED", ""),
            "TYRESIZE1": vehicle.get("TYRESIZE1", ""),
            "TYRESIZE2": vehicle.get("TYRESIZE2", ""),
            "SEATS": vehicle.get("SEATS", ""),
            "EMISLVL": vehicle.get("EMISLVL", ""),
            "EMSTAGE": vehicle.get("EMSTAGE", ""),
            "EECO2E": vehicle.get("EECO2E", ""),
            "DATEAPP": vehicle.get("DATEAPP", ""),
        }
        return self._schema.format_record(data)

    def _map_to_ts_fields(
        self,
        dispatch: Dict[str, Any],
        sap: Dict[str, Any],
        running_number: int,
    ) -> Dict[str, Any]:
        """Mappa dispatch + SAP till TS-fältnamn."""
        return {
            "POSTTYP": self.config.post_type,
            "LOPNUMMER": str(running_number).zfill(4),
            "LÖPNUMMER": str(running_number).zfill(4),
            "VIN": dispatch.get("_VIN_N", ""),
            "UNDERSTÄLLSNUMMER": dispatch.get("_VIN_N", ""),
            "MODELLÅR": dispatch.get("_YEAR_N", ""),
            "MODEL_YEAR": dispatch.get("_YEAR_N", ""),
            "TYPGODKÄNNANDENUMMER": sap.get(
                "APPROVAL", sap.get("_ETG_N", "")
            ),
            "ETG": sap.get("APPROVAL", sap.get("_ETG_N", "")),
            "APPROVAL": sap.get("APPROVAL", sap.get("_ETG_N", "")),
            "HANDELSBETECKNING": sap.get("MODELNAME", ""),
            "TYPE": sap.get("TYPE", ""),
            "VARIANTE": sap.get("VARIANTE", ""),
            "VERSION": sap.get("VERSION", ""),
            "COMNAME": sap.get("COMNAME", ""),
            "CLASS": sap.get("CLASS", ""),
            "VEHCAT2": sap.get("VEHCAT2", ""),
            "NUMAXLE": sap.get("NUMAXLE", ""),
            "NUMWHEEL": sap.get("NUMWHEEL", ""),
            "LENGTH": sap.get("LENGTH", ""),
            "WIDTH": sap.get("WIDTH", ""),
            "HEIGHT": sap.get("HEIGHT", ""),
            "MASS": sap.get("MASS", ""),
            "LADENMASS": sap.get("LADENMASS", ""),
            "CYLCAPACITY": sap.get("CYLCAPACITY", ""),
            "MAXPOWER": sap.get("MAXPOWER", ""),
            "MAXNET": sap.get("MAXNET", ""),
            "FUEL": sap.get("FUEL", ""),
            "SPEED": sap.get("SPEED", ""),
            "TYRESIZE1": sap.get("TYRESIZE1", ""),
            "TYRESIZE2": sap.get("TYRESIZE2", ""),
            "SEATS": sap.get("SEATS", ""),
            "EMISLVL": sap.get("EMISLVL", ""),
            "EMSTAGE": sap.get("EMSTAGE", ""),
            "EECO2E": sap.get("EECO2E", ""),
            "DATEAPP": sap.get("DATEAPP", ""),
            "KUNDNUMMER": dispatch.get(
                self.config.dispatch_columns.get(
                    "customer_number", "Sold to Dealer"
                ),
                "",
            ),
            "CUSTOMER": dispatch.get(
                self.config.dispatch_columns.get(
                    "customer_number", "Sold to Dealer"
                ),
                "",
            ),
            "FÄRGKOD": dispatch.get(
                self.config.dispatch_columns.get("color", "Color"),
                "",
            ),
        }

    def _generate_fallback(
        self,
        dispatch: Dict[str, Any],
        sap: Dict[str, Any],
        running_number: int,
    ) -> str:
        """Generera post med hårdkodad fallback-struktur."""
        _log.warning("Using hardcoded PT45 generation (no schema)")
        fmt = self.formatter

        customer_number = dispatch.get(
            self.config.dispatch_columns.get(
                "customer_number", "Sold to Dealer"
            ),
            "",
        )
        dateapp = sap.get("DATEAPP", "")

        fields = [
            fmt.numeric(running_number, 4),
            fmt.text(self.config.post_type, 2),
            fmt.numeric(customer_number, 10),
            fmt.text("", 6),
            fmt.numeric("", 4),
            fmt.text("", 80),
            fmt.text("", 8),
            fmt.numeric("", 4),
            fmt.numeric("", 4),
            fmt.text("", 24),
            fmt.text("", 3),
            fmt.text(sap.get("MODELNAME", "010000"), 6),
            fmt.text(sap.get("TYPE", ""), 24),
            fmt.text(sap.get("VARIANTE", ""), 40),
            fmt.text(sap.get("VERSION", ""), 40),
            fmt.text(sap.get("COMNAME", ""), 24),
            fmt.text(sap.get("CLASS", ""), 8),
            fmt.text("", 17),
            fmt.text(sap.get("VEHCAT2", ""), 25),
            fmt.numeric("", 8),
            fmt.date_yyyymmdd(dateapp),
            fmt.numeric(sap.get("NUMAXLE", ""), 2),
            fmt.numeric(sap.get("NUMWHEEL", ""), 3),
            fmt.text(sap.get("ANTILBS", ""), 7),
            fmt.numeric(sap.get("LENGTH", ""), 5),
            fmt.numeric(sap.get("WIDTH", ""), 5),
            fmt.numeric(sap.get("HEIGHT", ""), 4),
            fmt.numeric(sap.get("MASS", ""), 6),
            fmt.numeric("", 6),
            fmt.numeric(sap.get("LADENMASS", ""), 6),
            fmt.numeric("", 6),
            fmt.numeric("", 6),
            fmt.text("", 5),
            fmt.numeric(sap.get("CYLCAPACITY", ""), 5),
            fmt.text(sap.get("MAXPOWER", ""), 6),
            fmt.numeric(sap.get("MAXNET", ""), 5),
            fmt.text(sap.get("MAXPOWER", ""), 6),
            fmt.numeric(sap.get("MAXNET", ""), 5),
            fmt.text(sap.get("WORK_PR", ""), 6),
            fmt.text(sap.get("FUEL", ""), 6),
            fmt.text("", 10),
            fmt.text(sap.get("SPEED", ""), 5),
            fmt.text(sap.get("SPEED", ""), 5),
            fmt.text(sap.get("TYRESIZE1", ""), 20),
            fmt.text(sap.get("TYRESIZE2", ""), 20),
            fmt.numeric(sap.get("SEATS", ""), 1),
            fmt.text(sap.get("EMISLVL", ""), 6),
            fmt.numeric(sap.get("STATIONARY", ""), 3),
            fmt.numeric(sap.get("STATENG", ""), 5),
            fmt.numeric(sap.get("DRIVEBY", ""), 3),
            fmt.numeric("", 3),
            fmt.numeric("", 5),
            fmt.numeric("", 3),
            fmt.text("", 30),
            fmt.numeric(sap.get("EMSTAGE", ""), 2),
            fmt.numeric("", 6),
            fmt.numeric("", 1),
            fmt.text("", 1),
            fmt.text("", 1),
            fmt.text(sap.get("EECO2E", ""), 5),
            fmt.text("", 5),
            fmt.text(sap.get("EECO2E", ""), 5),
            fmt.text("", 6),
            fmt.text("", 6),
        ]

        post_content = "".join(fields)
        padding = self.config.post_length - len(post_content)

        if padding < 0:
            _log.error(
                "Post too long: %s (max %s)",
                len(post_content),
                self.config.post_length,
            )
            return post_content[: self.config.post_length]

        return post_content + (" " * padding)

    def _generate_fallback_from_vehicle(
        self,
        vehicle: Dict[str, Any],
        running_number: int,
    ) -> str:
        """Fallback för generate_posts_from_matched."""
        dispatch = {
            "_VIN_N": vehicle.get("_vin", ""),
            "_YEAR_N": vehicle.get("_model_year", ""),
            self.config.dispatch_columns.get(
                "customer_number", "Sold to Dealer"
            ): vehicle.get("_owner", ""),
        }

        sap = vehicle.copy()
        sap["APPROVAL"] = vehicle.get("APPROVAL", vehicle.get("_etg", ""))

        return self._generate_fallback(dispatch, sap, running_number)


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS

# ══════════════════════════════════════════════════════════════════════════════


class Plugin(PluginBase):
    """Vehicle Registration Post Plugin."""

    NAME = "Vehicle Registration Post"
    VERSION = "3.1.1"
    DESCRIPTION = "Genererar registreringsposter (PT45) för Transportstyrelsen"
    AUTHOR = AUTHOR
    COPYRIGHT = get_copyright_string()

    DEPENDENCIES: Final[List[str]] = []
    OPTIONAL_DEPENDENCIES = [
        "ts_spec_import",
        "sap_import",
        "core_config",
        "core_logger",
    ]

    def __init__(self, app: Any):
        super().__init__(app)

        self.is_active: bool = False
        self.config: Optional[RegistrationConfig] = None
        self.matcher: Optional[DataMatcher] = None
        self.generator: Optional[PostGenerator] = None
        self._paths: Dict[str, Path] = {}
        self._event_handlers: List[Tuple[str, Callable]] = []

    def initialize(self) -> bool:
        """Initiera plugin."""
        try:
            self._setup_paths()
            self._load_config()

            self.matcher = DataMatcher(self.config, self.app)
            self.generator = PostGenerator(self.config, self.app)

            # v3.1.1: kraschsäkra app-attribut
            try:
                self.app.registration_post = self
                self.app.vehicle_registration_post = self
            except Exception as exc:
                _log.warning(
                    "Kunde inte registrera app-attribut: %s", exc,
                )

            _log.info("%s v%s initialized", self.NAME, self.VERSION)
            return True

        except Exception:
            _log.exception("Failed to initialize %s", self.NAME)
            return False

    def activate(self) -> bool:
        """Aktivera plugin."""
        self.is_active = True

        events = [
            ("registration_post:generate", self._on_generate),
            ("ts_spec:version_changed", self._on_spec_changed),
            ("ts_spec:imported", self._on_spec_imported),
        ]

        for event_name, handler in events:
            if subscribe_event_safe(self.app, event_name, handler):
                self._event_handlers.append((event_name, handler))

        emit_event_safe(
            self.app,
            "vehicle_registration_post:activated",
            {"version": self.VERSION},
        )

        _log.info("%s activated", self.NAME)
        return True

    def deactivate(self) -> bool:
        """Deaktivera plugin."""
        for event_name, handler in self._event_handlers:
            unsubscribe_event_safe(self.app, event_name, handler)
        self._event_handlers.clear()

        self.is_active = False
        return True

    def init(self) -> bool:
        """Alias för initialize()."""
        return self.initialize()

    def register_ui(self, parent: Any) -> None:
        """Ingen egen standardwidget i denna version."""
        _ = parent
        return None

    def shutdown(self) -> bool:
        """Alias för deactivate()."""
        return self.deactivate()

    def config_schema(self) -> Dict[str, Any]:
        """Konfigurationsschema."""
        return {
            "enabled": {
                "type": "boolean",
                "default": True,
                "description": "Aktivera vehicle_registration_post-pluginet.",
            },
            "output_dir": {
                "type": "string",
                "default": "ut",
                "description": "Standardkatalog för genererade PT45-filer.",
            },
            "use_ts_spec_schema": {
                "type": "boolean",
                "default": True,
                "description": "Använd schema från ts_spec_import om tillgängligt.",
            },
        }

    def _setup_paths(self) -> None:
        """Konfigurera sökvägar."""
        base_dir = Path(
            get_app_config(self.app, "paths.base_dir", ".")
        )
        ut_dir = get_app_config(self.app, "paths.output_dir", "ut")

        self._paths = {
            "base": base_dir,
            "data": base_dir / "data" / "registration_post",
            "output": base_dir / ut_dir,
        }

        for path in self._paths.values():
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                _log.warning("Could not create directory %s: %s", path, exc)

    def _load_config(self) -> None:
        """Ladda konfiguration."""
        config_file = self._paths.get("data", Path(".")) / "config.json"

        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                    self.config = RegistrationConfig.from_dict(data)
                    return
            except Exception as exc:
                _log.warning("Config load failed: %s", exc)

        config_data = get_app_config(
            self.app, "vehicle_registration_post", {}
        )
        if isinstance(config_data, dict):
            self.config = RegistrationConfig.from_dict(config_data)
        else:
            self.config = RegistrationConfig()

        self._save_config()

    def _save_config(self) -> None:
        """Spara konfiguration atomiskt."""
        if self.config is None:
            return

        config_file = self._paths.get("data", Path(".")) / "config.json"
        data = self.config.to_dict()
        data["_meta"] = {
            "updated_at": datetime.now().isoformat(),
            "version": self.VERSION,
        }

        self._atomic_write_json(config_file, data)

    def _atomic_write_json(self, path: Path, data: Any) -> None:
        """Atomisk JSON-skrivning."""
        path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent),
            suffix=".tmp",
            prefix=".{}_".format(path.name),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _on_generate(self, data: Dict[str, Any]) -> None:
        """Hantera generate-event."""
        dispatch_file = data.get("dispatch_file")
        if dispatch_file:
            result = self.generate_posts(
                dispatch_file=Path(dispatch_file),
                output_file=Path(data["output_file"])
                if data.get("output_file")
                else None,
            )
        else:
            result = self._error_result("dispatch_file saknas i event data")

        callback = data.get("callback")
        if callable(callback):
            callback(result)

    def _on_spec_changed(self, event: Dict[str, Any]) -> None:
        """Hantera TS-spec version-byte."""
        _log.info("TS-spec changed to v%s", event.get("version"))
        if self.generator:
            self.generator.invalidate_schema_cache()

    def _on_spec_imported(self, event: Dict[str, Any]) -> None:
        """Hantera ny TS-spec import."""
        _log.info("TS-spec imported: %s", event.get("version"))
        if self.generator:
            self.generator.invalidate_schema_cache()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_posts(
        self,
        dispatch_file: Path,
        output_file: Optional[Path] = None,
        sap_df: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Generera registreringsposter."""
        if not HAS_PANDAS:
            return self._error_result("pandas krävs")

        try:
            _log.info("Genererar PT45 från %s", dispatch_file.name)

            dispatch_df = self._load_file(dispatch_file)
            if dispatch_df.empty:
                return self._error_result("Dispatch-filen är tom")

            if sap_df is None:
                sap_df = self._get_sap_data()

            if sap_df.empty:
                return self._error_result("SAP-data saknas")

            matches, stats = self.matcher.match_dispatch_to_sap(
                dispatch_df, sap_df
            )

            if not matches:
                return self._error_result("Inga matchningar hittades")

            posts, errors = self.generator.generate_posts(matches)

            if not posts:
                return self._error_result("Kunde inte generera poster")

            if output_file is None:
                output_file = self._get_default_output_path()

            checksum = self._save_posts(output_file, posts)

            emit_event_safe(
                self.app,
                "registration_post:generated",
                {
                    "posts_count": len(posts),
                    "output_file": str(output_file),
                    "match_rate": stats.match_rate(),
                    "checksum": checksum,
                },
            )

            result = {
                "success": True,
                "posts_count": len(posts),
                "output_file": output_file,
                "matched": stats.total_matched(),
                "total": stats.total_dispatch,
                "match_rate": stats.match_rate(),
                "statistics": stats.to_dict(),
                "errors": errors,
                "checksum": checksum,
                "used_schema": self.generator.schema is not None,
            }

            _log.info(
                "%s PT45 poster genererade -> %s",
                len(posts),
                output_file.name,
            )
            return result

        except Exception as exc:
            _log.exception("Fel vid PT45-generering")
            return self._error_result(str(exc))

    def generate_posts_from_matched(
        self, vehicles: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generera poster från redan matchade fordon."""
        return self.generator.generate_posts_from_matched(vehicles)

    def match_data(
        self,
        dispatch_df: Any,
        sap_df: Any,
    ) -> Tuple[List[Dict[str, Any]], MatchStatistics]:
        """Matcha dispatch mot SAP utan att generera poster."""
        return self.matcher.match_dispatch_to_sap(dispatch_df, sap_df)

    def get_config(self) -> Dict[str, Any]:
        """Hämta konfiguration."""
        return self.config.to_dict() if self.config else {}

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Uppdatera konfiguration."""
        try:
            current = self.config.to_dict() if self.config else {}
            current.update(updates)

            self.config = RegistrationConfig.from_dict(current)
            self._save_config()

            self.matcher = DataMatcher(self.config, self.app)
            self.generator = PostGenerator(self.config, self.app)

            return {"success": True, "config": self.config.to_dict()}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    def _load_file(self, filepath: Path) -> Any:
        """Ladda fil (Excel eller CSV)."""
        try:
            if not filepath.exists():
                _log.error("Fil finns inte: %s", filepath)
                return pd.DataFrame()

            if filepath.suffix.lower() in [".xlsx", ".xls"]:
                df = pd.read_excel(filepath, dtype=str)
            elif filepath.suffix.lower() == ".csv":
                df = pd.read_csv(filepath, dtype=str, encoding="utf-8")
            else:
                _log.error("Okänt format: %s", filepath.suffix)
                return pd.DataFrame()

            return df.fillna("")

        except Exception as exc:
            _log.error("Fel vid inläsning av %s: %s", filepath, exc)
            return pd.DataFrame()

    def _get_sap_data(self) -> Any:
        """Hämta SAP-data."""
        sap_import = get_plugin_safe(self.app, "sap_import")
        if sap_import and hasattr(sap_import, "get_all_vehicles"):
            try:
                vehicles = sap_import.get_all_vehicles()
                if vehicles:
                    return pd.DataFrame(vehicles).fillna("")
            except Exception as exc:
                _log.warning("Kunde inte hämta via sap_import: %s", exc)

        data_dir = self._paths.get("data")
        if data_dir:
            sap_file = data_dir / "sap_data.json"
            if sap_file.exists():
                try:
                    with open(sap_file, "r", encoding="utf-8") as handle:
                        data = json.load(handle)
                        return pd.DataFrame(data).fillna("")
                except Exception:
                    pass

        return pd.DataFrame()

    def _save_posts(self, filepath: Path, posts: List[str]) -> str:
        """Spara poster till fil med Latin-1 encoding."""
        filepath.parent.mkdir(parents=True, exist_ok=True)

        content = "\n".join(posts) + "\n"

        try:
            encoded_content = content.encode(TS_ENCODING)
        except UnicodeEncodeError:
            encoded_content = content.encode(TS_ENCODING, errors="replace")
            _log.warning("Replaced non-Latin-1 characters in output file")

        checksum = hashlib.sha256(encoded_content).hexdigest()

        fd, tmp_path = tempfile.mkstemp(
            dir=str(filepath.parent),
            suffix=".tmp",
            prefix=".{}_".format(filepath.name),
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded_content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, str(filepath))
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise

        _log.info("Sparade %s poster -> %s", len(posts), filepath.name)
        return checksum

    def _get_default_output_path(self) -> Path:
        """Generera standard output-sökväg."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = self._paths.get("output", Path("ut"))
        return output_dir / "PT45_{}.txt".format(timestamp)

    def _error_result(self, error_msg: str) -> Dict[str, Any]:
        """Skapa felresultat."""
        return {
            "success": False,
            "posts_count": 0,
            "output_file": None,
            "matched": 0,
            "total": 0,
            "match_rate": 0.0,
            "errors": [error_msg],
            "statistics": {},
        }


VehicleRegistrationPostPlugin = Plugin

__all__ = [
    "Plugin",
    "VehicleRegistrationPostPlugin",
    "RegistrationConfig",
    "MatchStatistics",
    "PostGenerator",
    "DataMatcher",
    "FieldFormatter",
    "VehicleDataNormalizer",
    "get_plugin_safe",
    "get_event_bus",
    "emit_event_safe",
    "subscribe_event_safe",
    "unsubscribe_event_safe",
    "get_app_config",
    "RECORD_LENGTH",
    "TS_ENCODING",
    "POSTTYP_FORDON",
]
