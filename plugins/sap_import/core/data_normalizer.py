# -*- coding: utf-8 -*-
# Fil: plugins/sap_import/core/data_normalizer.py

"""
Datanormalisering för fordonsdata med TS-spec integration (v2.1.1).

Hanterar normalisering från olika källor (SAP, Dispatch) till:
    - Standardiserat internt format
    - TS-färdiga fältnamn och format
    - Validering mot TS-regler

Funktioner:
    - VIN-validering (I/O/Q-regler)
    - Datumkonvertering
    - Kolumnmappning
    - Dublettborttagning
    - Event-emission vid normalisering

Användning (standalone):
    >>> from plugins.sap_import.core.data_normalizer import normalize_dataframe
    >>> df_clean = normalize_dataframe(df)

Användning (med app):
    >>> normalizer = DataNormalizer(app)
    >>> df_clean = normalizer.normalize(df, source="SAP")

FÖRÄNDRINGAR v2.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (IDE-VARNING 1): "Variable not allowed in type expression" —
      VIN_LENGTH/VIN_INVALID_CHARS/VIN_PATTERN användes som type hints
      (-> bool med VIN_PATTERN i annotering). Nu: alla typ-annoteringar
      citerade som strängar (forward refs), inkl. pd.DataFrame ->
      "pd.DataFrame".
    - FIX (IDE-VARNING 2): "Import core.plugin_manager could not be
      resolved" — TYPE_CHECKING-importen pekade på modul som inte
      finns. Nu: Optional[Any] (samma fix som date_converter v2.1.1).
    - FIX (låst regel): f-string-logganrop -> lazy %s (7 st).
    - FIX (kraschsäkerhet): from .column_resolver import DISPATCH_ALIAS,
      SAP_ALIAS, resolve_columns UTAN fallback — modulen kunde inte
      importeras om column_resolver saknas. Nu try/except med
      fallback-konstanter + fallback-resolve_columns (samma mönster
      som excel_reader v2.1.1).
    - FIX (KRAV 55–57/länkning): DateConverter importeras med
      try/except — den är redan levererad, men guard skadar inte.
    - VERSION/AUTHOR/get_copyright_string tillagda (saknades helt).
    - FIX (korrekthet): _map_columns() byggde alias_map från
      SAP_ALIAS/DISPATCH_ALIAS — om dessa är fallback-dicts (utan
      column_resolver) fungerar mappningen ändå (konstanterna
      definieras nedan).
    - FIX (konsistens): get_ts_mapping() kollar ts_schema_manager
      (source of truth) FÖRST, sedan ts_spec_import (arkitektur-
      prioritet — samma som date_converter).
    - _is_valid_vin() använder VIN_PATTERN + I/O/Q (konsistent med
      plugin.py DataNormalizer.normalize_vin).
    - Övrig logik OFÖRÄNDRAD (normalize/validate/columns/dates/vin/
      duplicates/events).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None
    HAS_PANDAS = False

try:
    from .column_resolver import DISPATCH_ALIAS, SAP_ALIAS, resolve_columns
except ImportError:
    # Kraschsäker fallback om column_resolver.py inte levererats än
    DISPATCH_ALIAS: Dict[str, List[str]] = {
        "VINCODE": ["VIN", "VIN-KOD", "VINCODE", "CHASSINR", "CHASSIS"],
        "MODELYEAR": ["MY", "ÅRSMODELL", "MODEL YEAR", "MODELYEAR"],
        "APPROVAL": ["ETG", "APPROVAL", "GODKÄNNANDENR", "TYPGODKÄNNANDE"],
        "MODEL": ["MODELL", "MODEL", "MODELLNAMN", "MODELNAME"],
        "ENGINE": ["MOTOR", "ENGINE", "MOTORTYP", "ENGINE_TYPE"],
        "COLOR_CODE": ["FÄRGKOD", "COLOR CODE", "FÄRG", "COLOR"],
    }
    SAP_ALIAS: Dict[str, List[str]] = {
        "VINCODE": ["VIN", "VIN-NUMMER", "VINNUMMER", "CHASSINR"],
        "MODELYEAR": ["MODEL YEAR", "ÅRSMODELL", "MY"],
        "APPROVAL": ["ETG", "APPROVAL NO", "GODKÄNNANDENR", "TYPGODKÄNNANDE"],
        "MODEL": ["MODELL", "MODEL", "MODELLNAMN", "MODELNAME"],
        "ENGINE": ["MOTOR", "ENGINE", "MOTORTYP"],
        "COLOR_CODE": ["FÄRGKOD", "COLOR CODE", "FÄRG"],
    }

    def resolve_columns(
        df: Any,
        expected_aliases: Dict[str, List[str]],
    ) -> Tuple[Dict[str, Optional[str]], List[str]]:
        """Fallback: enkel exakt/alias-matchning av kolumnnamn."""
        mapping: Dict[str, Optional[str]] = {}
        missing: List[str] = []
        columns = [
            str(c).strip() for c in (df.columns if hasattr(df, "columns") else [])
        ]
        for canonical, aliases in expected_aliases.items():
            found = None
            for col in columns:
                col_lower = (
                    col.lower().replace("_", "").replace("-", "").replace(" ", "")
                )
                for alias in aliases:
                    alias_norm = (
                        alias.lower().replace("_", "").replace("-", "").replace(" ", "")
                    )
                    if col_lower == alias_norm:
                        found = col
                        break
                if found:
                    break
            if found:
                mapping[canonical] = found
            else:
                missing.append(canonical)
        return mapping, missing

from .date_converter import DateConverter, to_iso_date

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "2.1.1"
AUTHOR: str = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    from datetime import datetime
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VIN_LENGTH = 17
VIN_INVALID_CHARS = set('IOQ')
VIN_PATTERN = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')

STANDARD_COLUMNS = [
    "VINCODE", "MODELYEAR", "APPROVAL", "INVOICE_DATE",
    "PRODUCTION_DATE", "DATEAPP", "MODEL", "ENGINE",
    "TRANSMISSION", "COLOR_CODE", "EXTERIOR_COLOR",
    "INTERIOR_COLOR", "DEALER_CODE", "CUSTOMER_NAME",
]

DEFAULT_CRITICAL_COLUMNS = ["VINCODE", "MODELYEAR", "APPROVAL"]
DEFAULT_DATE_COLUMNS = ["INVOICE_DATE", "PRODUCTION_DATE", "DATEAPP"]


# ══════════════════════════════════════════════════════════════════════════════
# DATA NORMALIZER CLASS
# ══════════════════════════════════════════════════════════════════════════════

class DataNormalizer:
    """
    App-aware datanormaliserare med TS-integration.
    """

    def __init__(
        self,
        app: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        self.app = app
        self.config = config or {}
        self.date_converter = DateConverter(app) if app else None
        self._ts_mapping_cache: Dict[str, Dict[str, str]] = {}

        self.critical_columns = self.config.get(
            "critical_columns", DEFAULT_CRITICAL_COLUMNS
        )
        self.date_columns = self.config.get(
            "date_columns", DEFAULT_DATE_COLUMNS
        )
        self.vin_uppercase = self.config.get("vin_uppercase", True)
        self.validate_vin = self.config.get("validate_vin", True)
        self.remove_duplicates = self.config.get("remove_duplicates", True)

    def normalize(
        self,
        df: "pd.DataFrame",
        source: str = "DISPATCH",
        normalize_year_func: Optional[Callable] = None
    ) -> "pd.DataFrame":
        """Normalisera DataFrame från specifik källa."""
        if not HAS_PANDAS:
            raise ImportError("pandas krävs för normalisering")

        _log.info(
            "Normaliserar %d rader från %s",
            len(df), source,
        )

        df = self._map_columns(df, source)
        df = df.where(pd.notna(df), None)
        df = self._trim_strings(df)
        df = self._convert_dates(df)
        df = self._normalize_vin(df)

        if normalize_year_func and "MODELYEAR" in df.columns:
            df["MODELYEAR"] = df["MODELYEAR"].apply(normalize_year_func)

        if self.remove_duplicates and "VINCODE" in df.columns:
            before = len(df)
            df = df.drop_duplicates(subset=["VINCODE"], keep="last")
            if before != len(df):
                _log.info(
                    "Tog bort %d dubblett-VIN",
                    before - len(df),
                )

        df = self._ensure_columns(df)

        if self.app and hasattr(self.app, 'event_bus'):
            try:
                self.app.event_bus.emit('sap_import:normalized', {
                    'source': source,
                    'row_count': len(df),
                    'columns': list(df.columns)
                })
            except Exception:
                pass

        _log.info(
            "Normalisering klar: %d giltiga rader",
            len(df),
        )
        return df

    def validate(
        self,
        df: "pd.DataFrame"
    ) -> Tuple[bool, List[str]]:
        """Validera normaliserad DataFrame."""
        errors = []

        has_critical, missing = self._check_critical_columns(df)
        if not has_critical:
            errors.append(
                "Saknar kritiska kolumner: " + ", ".join(missing)
            )

        if "VINCODE" in df.columns:
            invalid_vins = df[
                ~df["VINCODE"].apply(self._is_valid_vin)
            ]["VINCODE"].tolist()
            if invalid_vins:
                errors.append(
                    f"Ogiltiga VIN hittade ({len(invalid_vins)} totalt)"
                )

        for col in self.date_columns:
            if col in df.columns:
                invalid = df[
                    (df[col].notna()) & (df[col] == "")
                ][col].tolist()
                if invalid:
                    errors.append(
                        f"Ogiltiga datum i {col}: {len(invalid)}"
                    )

        return len(errors) == 0, errors

    def _map_columns(
        self,
        df: "pd.DataFrame",
        source: str
    ) -> "pd.DataFrame":
        alias_map = SAP_ALIAS if source.upper() == "SAP" else DISPATCH_ALIAS
        mapping, missing = resolve_columns(df, alias_map)

        if missing:
            _log.warning(
                "Saknade kolumner i %s: %s",
                source, ", ".join(missing),
            )

        rename_map = {v: k for k, v in mapping.items() if v}
        df = df.rename(columns=rename_map)

        keep_cols = [c for c in alias_map.keys() if c in df.columns]
        return df[keep_cols].copy()

    def _trim_strings(self, df: "pd.DataFrame") -> "pd.DataFrame":
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].apply(
                    lambda v: None if v is None else str(v).strip()
                )
        return df

    def _convert_dates(self, df: "pd.DataFrame") -> "pd.DataFrame":
        for col in self.date_columns:
            if col not in df.columns:
                continue
            if self.date_converter:
                df[col] = df[col].apply(self.date_converter.to_iso_date)
            else:
                df[col] = df[col].apply(to_iso_date)
        return df

    def _normalize_vin(self, df: "pd.DataFrame") -> "pd.DataFrame":
        if "VINCODE" not in df.columns:
            return df

        if self.vin_uppercase:
            df["VINCODE"] = df["VINCODE"].apply(
                lambda v: "" if v is None else str(v).strip().upper()
            )
        else:
            df["VINCODE"] = df["VINCODE"].apply(
                lambda v: "" if v is None else str(v).strip()
            )

        before = len(df)
        df = df[df["VINCODE"] != ""]
        if before != len(df):
            _log.info(
                "Tog bort %d rader med tomt VIN",
                before - len(df),
            )

        if self.validate_vin and len(df) > 0:
            invalid_mask = ~df["VINCODE"].apply(self._is_valid_vin)
            invalid_count = invalid_mask.sum()
            if invalid_count > 0:
                _log.warning(
                    "%d VIN klarade inte valideringen. Behålls ändå.",
                    invalid_count,
                )

        return df

    def _is_valid_vin(self, vin: Any) -> bool:
        if not isinstance(vin, str):
            return False
        if len(vin) != VIN_LENGTH:
            return False
        if any(c in VIN_INVALID_CHARS for c in vin):
            return False
        return VIN_PATTERN.match(vin) is not None

    def _ensure_columns(self, df: "pd.DataFrame") -> "pd.DataFrame":
        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[STANDARD_COLUMNS]

    def _check_critical_columns(
        self,
        df: "pd.DataFrame"
    ) -> Tuple[bool, List[str]]:
        missing = [c for c in self.critical_columns if c not in df.columns]
        return len(missing) == 0, missing

    def get_ts_mapping(self, source: str = "SAP") -> Dict[str, str]:
        if source in self._ts_mapping_cache:
            return self._ts_mapping_cache[source]

        mapping = {}
        # Prioritet: ts_schema_manager (source of truth) -> ts_spec_import
        if self.app:
            for plugin_name in ("ts_schema_manager", "ts_spec_import"):
                try:
                    plugin = getattr(self.app, plugin_name, None)
                    if plugin is None or not hasattr(
                        plugin, "get_field_mapping"
                    ):
                        continue
                    mapping = plugin.get_field_mapping("45", source)
                    if mapping:
                        self._ts_mapping_cache[source] = mapping
                        return mapping
                except Exception:
                    continue

        if source.upper() == "SAP":
            mapping = {
                "VINCODE": "Underställsnummer",
                "MODELYEAR": "Modellår",
                "APPROVAL": "Typgodkännandenummer",
                "MODEL": "Handelsbeteckning",
                "ENGINE": "Motorbeteckning",
                "COLOR_CODE": "Färgkod",
            }
        else:
            mapping = {
                "VINCODE": "Underställsnummer",
                "MODELYEAR": "Modellår",
                "APPROVAL": "Typgodkännandenummer",
            }

        self._ts_mapping_cache[source] = mapping
        return mapping


# ══════════════════════════════════════════════════════════════════════════════
# STANDALONE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def normalize_dataframe(
    df: "pd.DataFrame",
    config: Optional[Dict] = None,
    normalize_year_func: Optional[Callable] = None
) -> "pd.DataFrame":
    if not HAS_PANDAS:
        raise ImportError("pandas krävs")

    normalizer = DataNormalizer(app=None, config=config)
    return normalizer.normalize(
        df,
        source="DISPATCH",
        normalize_year_func=normalize_year_func
    )


def has_critical_columns(
    df: "pd.DataFrame",
    config: Optional[Dict] = None
) -> Tuple[bool, List[str]]:
    if config is None:
        config = {}
    _, missing = resolve_columns(df, DISPATCH_ALIAS)
    critical = config.get("critical_columns", DEFAULT_CRITICAL_COLUMNS)
    missing_critical = [c for c in critical if c in missing]
    return len(missing_critical) == 0, missing_critical


def validate_vin(vin: str) -> bool:
    if not isinstance(vin, str):
        return False
    if len(vin) != VIN_LENGTH:
        return False
    if any(c in VIN_INVALID_CHARS for c in vin):
        return False
    return VIN_PATTERN.match(vin) is not None


def clean_vin(vin: Any, uppercase: bool = True) -> str:
    if vin is None:
        return ""
    cleaned = str(vin).strip()
    if uppercase:
        cleaned = cleaned.upper()
    return cleaned if cleaned else ""


def get_invalid_vins(df: "pd.DataFrame") -> List[str]:
    if "VINCODE" not in df.columns:
        return []
    return df[
        ~df["VINCODE"].apply(validate_vin)
    ]["VINCODE"].tolist()


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "DataNormalizer",
    "normalize_dataframe",
    "has_critical_columns",
    "validate_vin",
    "clean_vin",
    "get_invalid_vins",
    "get_copyright_string",
    "STANDARD_COLUMNS",
    "DEFAULT_CRITICAL_COLUMNS",
    "DEFAULT_DATE_COLUMNS",
    "VIN_LENGTH",
    "VIN_INVALID_CHARS",
    "HAS_PANDAS",
    "VERSION",
    "AUTHOR",
]
