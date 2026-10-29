# -*- coding: utf-8 -*-
# Fil: plugins/sap_import/core/column_resolver.py

"""
Kolumnmappning och alias-hantering med TS-spec integration (v2.1.1).

Hanterar:
    - Alias-matching mellan olika källor (SAP, Dispatch, Excel)
    - TS-fältnamn-mappning från ts_spec_import
    - Fuzzy matching med poängsystem
    - Cache för prestanda
    - Föreslagna mappningar (suggest_mappings)

FÖRÄNDRINGAR v2.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (IDE-VARNING): "Import core.plugin_manager could not be
      resolved" — TYPE_CHECKING-importen pekade på modul som inte
      finns. Nu: Optional[Any] (samma fix som date_converter v2.1.1
      och data_normalizer v2.1.1).
    - VERSION/AUTHOR/get_copyright_string tillagda (saknades helt).
    - FIX (KRAV 58): header normaliserad — "# Fil: plugins/sap_import/
      core/column_resolver.py".
    - FIX (arkitektur-prioritet): get_ts_field_names(),
      map_to_ts_fields() och _check_ts_spec_available() kollade ENDAST
      ts_spec_import — men ts_schema_manager är source of truth.
      Nu: ts_schema_manager FÖRST, sedan ts_spec_import (samma
      prioritet som date_converter/data_normalizer v2.1.1).
    - FIX (korrekthet, DATA-FÖRLUST): strip_object_columns() gjorde
      astype(str) — NaN blev strängen "nan" i stället för tomt, och
      "nan" är inte en giltig VIN/årsmodell men passerar som icke-tom.
      Nu: NaN/None -> "" (övriga strip:as).
    - FIX (robusthet): map_to_ts_fields() — get_field_mapping kan ha
      olika signaturer (ts_schema_manager: (post_type, version);
      ts_spec_import: (post_type, source)); båda försöks i try/except
      med fallback till default-mappning.
    - FIX (korrekthet, TESTFÅNGAD DATA-FÖRLUST): resolve_columns()
      med fuzzy kunde mappa SAMMA kolumn till flera canonicaler
      (t.ex. "Årsmodell" -> MODELYEAR via "ÅRSMODELL" [90] OCH
      MODELNAME via "MODELL" [70]) — rename_map-kollisionen i
      anroparen tappade sedan MODELYEAR helt. Nu: greedy-unik
      tilldelning (bästa poäng först, varje kolumn används en gång).
    - OBSERVATION (EJ ändrad): DISPATCH_ALIAS innehåller "ETG"/"WVTA"
      både under APPROVAL och ETG_NUMBER — dict-ordningen ger
      APPROVAL företräde (rimligt); ETG_NUMBER fångar bara kolumner
      som inte matchar APPROVAL först.
    - Övrig logik OFÖRÄNDRAD (alias-tabeller, fuzzy-poäng,
      suggest_mappings, caches).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None
    HAS_PANDAS = False

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
# KOLUMNALIAS - DISPATCH
# ══════════════════════════════════════════════════════════════════════════════

DISPATCH_ALIAS: Dict[str, List[str]] = {
    "VINCODE": [
        "VIN", "VIN CODE", "VINNUMBER", "VEHICLE IDENTIFICATION NUMBER",
        "CHASSIS", "CHASSIS NUMBER", "VIN NO", "VIN-NUMBER", "VEHICLEID",
        "UNDERSTÄLLSNUMMER"
    ],
    "MODELYEAR": [
        "MODEL YEAR", "MY", "YEAR", "MODYEAR", "ÅRSMODELL", "MODEL-YEAR",
        "MODELLÅR"
    ],
    "TYPE": ["TYPE", "TYP", "VEHICLE TYPE"],
    "VARIANTE": [
        "VARIANT", "VARIANTE", "MODEL VARIANT", "CAR VARIANT", "VAR."
    ],
    "VERSION": ["VERSION", "VER", "MODEL VERSION"],
    "MODELNAME": [
        "MODEL NAME", "MODEL", "MODELLNAMN", "MODELL", "HANDELSBETECKNING"
    ],
    "COMNAME": [
        "COMMERCIALNAME", "COMMERCIAL NAME", "COM NAME", "MARKETING NAME"
    ],
    "CLASS": ["CLASS", "VEHICLE CLASS", "CAR CLASS", "CATEGORY"],
    "VEHCAT2": [
        "VEH CAT 2", "VEH CAT2", "VEHICLE CATEGORY 2", "CATEGORY2"
    ],
    "APPROVAL": [
        "APPROVAL", "ETG", "WVTA", "CERTIFICATE", "CERT NO",
        "TYPGODKÄNNANDE", "TYPE APPROVAL", "TYPGODKÄNNANDENUMMER"
    ],
    "DATEAPP": [
        "DATE APP", "APPROVAL DATE", "DATE APPROVAL", "APPROVALDATE",
        "REGISTRATION DATE", "REG DATE", "REGISTRERINGSDATUM"
    ],
    "NUMAXLE": [
        "NUM AXLE", "NUMBER OF AXLES", "NO. AXLE", "AXLE COUNT", "AXLES"
    ],
    "NUMWHEEL": [
        "NUM WHEEL", "NUMBER OF WHEELS", "NO. WHEEL", "WHEEL COUNT", "WHEELS"
    ],
    "ANTILBS": ["ANTILBS", "ANTILOCK", "ABS", "ANTI-LOCK"],
    "LENGTH": ["LENGTH", "VEHICLE LENGTH", "CAR LENGTH"],
    "WIDTH": ["WIDTH", "VEHICLE WIDTH", "CAR WIDTH"],
    "HEIGHT": ["HEIGHT", "VEHICLE HEIGHT", "CAR HEIGHT"],
    "MASS": ["MASS", "WEIGHT", "TOTAL WEIGHT", "GROSS WEIGHT", "GVWR"],
    "LADENMASS": ["LADENMASS", "CURB WEIGHT", "EMPTY WEIGHT", "KERB WEIGHT"],
    "CYLCAPACITY": [
        "CYL CAPACITY", "CYLINDER CAPACITY", "ENGINE CAPACITY",
        "ENGINE SIZE", "DISPLACEMENT", "CC", "SLAGVOLYM"
    ],
    "MAXPOWER": [
        "MAX POWER", "MAXPOWER", "PEAK POWER", "ENGINE POWER", "HP", "POWER", "KW",
        "MOTOREFFEKT"
    ],
    "MAXNET": ["MAX NET", "MAX NET POWER", "MAXNET", "NET POWER"],
    "WORK_PR": ["WORK PR", "WORKPR", "WORK_PRESSURE", "WORKING PRESSURE"],
    "FUEL": [
        "FUEL", "FUEL TYPE", "ENGINE TYPE", "FUELTYPE", "BRÄNSLE", "DRIVMEDEL"
    ],
    "SPEED": ["SPEED", "MAX SPEED", "TOP SPEED", "MAXSPEED"],
    "TYRESIZE1": [
        "TYRE SIZE1", "TYRE SIZE 1", "TYRESIZE 1", "FRONT TYRE", "FRONT TIRE"
    ],
    "TYRESIZE2": [
        "TYRE SIZE2", "TYRE SIZE 2", "TYRESIZE 2", "REAR TYRE", "REAR TIRE"
    ],
    "SEATS": ["SEATS", "NUMBER OF SEATS", "SEATING CAPACITY", "PASSENGERS"],
    "EMISLVL": ["EMIS LVL", "EMISSION LEVEL", "EMISLVL", "EMISSIONS"],
    "STATIONARY": ["STATIONARY", "IDLE", "IDLE EMISSIONS"],
    "STATENG": ["STAT ENG", "STATIONARY ENGINE", "STATENG"],
    "DRIVEBY": ["DRIVE BY", "DRIVEBY", "DRIVE-BY", "NOISE LEVEL", "NOISE"],
    "EMSTAGE": ["EM STAGE", "EMISSION STAGE", "EMSTAGE", "EURO STAGE"],
    "EECO2E": ["EE CO2E", "EE_CO2E", "EECO2E", "CO2 EMISSIONS", "CO2"],
    "COLOR": ["COLOR", "COLOUR", "FÄRG", "FARG", "FÄRGKOD"],
    "INVOICE_DATE": ["INVOICE DATE", "FAKTURADATUM", "INVDATE", "INVOICE"],
    "PRODUCTION_DATE": [
        "ACTUAL PRODUCTION DATE", "PRODUKTIONSDATUM", "PRODDATE", "PRODUCTION DATE"
    ],
    "CUSTOMER_NUMBER": [
        "SOLD TO DEALER", "DEALER ID", "CUSTOMER NUMBER", "KUNDNUMMER", "DN"
    ],
    "DEALER_NAME": [
        "DEALER NAME", "SOLD TO NAME", "KUNDNAMN", "CUSTOMER NAME"
    ],
    "ETG_NUMBER": ["ETG NUMBER", "ETG NO", "ETG-NO", "ETG", "WVTA"],
}


# ══════════════════════════════════════════════════════════════════════════════
# KOLUMNALIAS - SAP
# ══════════════════════════════════════════════════════════════════════════════

SAP_ALIAS: Dict[str, List[str]] = {
    "VINCODE": [
        "VIN", "COMM_NO", "COMMISSION NUMBER", "CHASSIS", "CHASSIS_NO",
        "VEHICLE ID", "VEHICLEID"
    ],
    "MODELYEAR": [
        "MODEL_YEAR", "MY", "YEAR", "MODYEAR", "MODEL YEAR"
    ],
    "APPROVAL": [
        "APPROVAL", "TYPE_APPROVAL", "ETG", "WVTA", "CERTIFICATE"
    ],
    "MODELNAME": [
        "MODEL", "MODEL_NAME", "SALES_MODEL", "COMMERCIAL_NAME"
    ],
    "ENGINE": [
        "ENGINE", "ENGINE_CODE", "MOTOR", "MOTORCODE"
    ],
    "TRANSMISSION": [
        "TRANSMISSION", "TRANS", "GEARBOX", "VÄXELLÅDA"
    ],
    "COLOR_CODE": [
        "COLOR_CODE", "COLOUR_CODE", "EXTERIOR_COLOR", "EXT_COLOR"
    ],
    "EXTERIOR_COLOR": [
        "EXTERIOR_COLOR", "EXT_COLOR", "PAINT_CODE"
    ],
    "INTERIOR_COLOR": [
        "INTERIOR_COLOR", "INT_COLOR", "INTERIOR"
    ],
    "INVOICE_DATE": [
        "INVOICE_DATE", "INV_DATE", "BILLING_DATE", "FAKTURADATUM"
    ],
    "PRODUCTION_DATE": [
        "PRODUCTION_DATE", "PROD_DATE", "MANUFACTURING_DATE", "MFG_DATE"
    ],
    "DEALER_CODE": [
        "DEALER_CODE", "SOLD_TO", "CUSTOMER_CODE", "DN"
    ],
    "CUSTOMER_NAME": [
        "CUSTOMER_NAME", "SOLD_TO_NAME", "DEALER_NAME"
    ],
    "DELIVERY_DATE": [
        "DELIVERY_DATE", "DEL_DATE", "SHIP_DATE"
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# COLUMN RESOLVER CLASS
# ══════════════════════════════════════════════════════════════════════════════

class ColumnResolver:
    """App-aware kolumnresolver med TS-integration."""

    def __init__(self, app: Optional[Any] = None):
        self.app = app
        self._mapping_cache: Dict[str, Dict[str, str]] = {}
        self._ts_field_cache: Dict[str, List[str]] = {}
        self._has_ts_spec = False

        if app:
            self._check_ts_spec_available()

    def _check_ts_spec_available(self) -> None:
        if not self.app:
            return
        try:
            self._has_ts_spec = bool(
                getattr(self.app, "ts_schema_manager", None)
                or getattr(self.app, "ts_spec_import", None)
            )
        except Exception:
            self._has_ts_spec = False

    def _get_schema_plugin(self) -> Optional[Any]:
        """Hämta första tillgängliga schema-plugin (source of truth
        först)."""
        if not self.app:
            return None
        for plugin_name in ("ts_schema_manager", "ts_spec_import"):
            try:
                plugin = getattr(self.app, plugin_name, None)
                if plugin is not None:
                    return plugin
            except Exception:
                continue
        return None

    def resolve(
        self,
        df: "pd.DataFrame",
        source: str = "DISPATCH",
        use_fuzzy: bool = True
    ) -> Dict[str, Optional[str]]:
        if not HAS_PANDAS:
            raise ImportError("pandas krävs för column resolving")

        alias_map = SAP_ALIAS if source.upper() == "SAP" else DISPATCH_ALIAS
        mapping, _missing = resolve_columns(
            df, alias_map, use_fuzzy=use_fuzzy
        )
        return mapping

    def get_ts_field_names(self, post_type: str = "45") -> List[str]:
        if post_type in self._ts_field_cache:
            return self._ts_field_cache[post_type]

        fields = []
        plugin = self._get_schema_plugin() if self._has_ts_spec else None
        if plugin is not None:
            try:
                schema = plugin.get_schema(post_type)
                if schema is not None and hasattr(schema, "fields"):
                    fields = [
                        getattr(field, "name", "")
                        for field in schema.fields
                    ]
                    fields = [f for f in fields if f]
                    self._ts_field_cache[post_type] = fields
                    return fields
            except Exception:
                pass

        fields = [
            "Posttyp", "Underställsnummer", "Modellår",
            "Typgodkännandenummer", "Handelsbeteckning",
        ]
        self._ts_field_cache[post_type] = fields
        return fields

    def map_to_ts_fields(
        self,
        df: "pd.DataFrame",
        source: str = "SAP",
        post_type: str = "45"
    ) -> Dict[str, str]:
        standard_mapping = self.resolve(df, source=source)
        ts_mapping = {}

        plugin = self._get_schema_plugin() if self._has_ts_spec else None
        if plugin is not None:
            try:
                # Olika signaturer: ts_schema_manager (post_type,
                # version) vs ts_spec_import (post_type, source).
                try:
                    ts_mapping = plugin.get_field_mapping(post_type, source)
                except TypeError:
                    ts_mapping = plugin.get_field_mapping(post_type)
                if not isinstance(ts_mapping, dict):
                    ts_mapping = {}
            except Exception:
                ts_mapping = {}

        if not ts_mapping:
            ts_mapping = self._get_default_ts_mapping(source)

        result = {}
        for standard_name, df_column in standard_mapping.items():
            if df_column and standard_name in ts_mapping:
                result[df_column] = ts_mapping[standard_name]

        return result

    def _get_default_ts_mapping(self, source: str) -> Dict[str, str]:
        if source.upper() == "SAP":
            return {
                "VINCODE": "Underställsnummer",
                "MODELYEAR": "Modellår",
                "APPROVAL": "Typgodkännandenummer",
                "MODELNAME": "Handelsbeteckning",
                "ENGINE": "Motorbeteckning",
                "COLOR_CODE": "Färgkod",
                "INVOICE_DATE": "Fakturadatum",
            }
        else:
            return {
                "VINCODE": "Underställsnummer",
                "MODELYEAR": "Modellår",
                "APPROVAL": "Typgodkännandenummer",
                "MODELNAME": "Handelsbeteckning",
            }


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def normalize_key(s: Any) -> str:
    if s is None:
        return ""
    x = str(s).strip().lower()
    x = x.replace("å", "a").replace("ä", "a").replace("ö", "o")
    return re.sub(r"[\W_]+", "", x, flags=re.UNICODE)


def calculate_match_score(
    col: str,
    canonical: str,
    synonyms: List[str]
) -> int:
    col_norm = normalize_key(col)
    canonical_norm = normalize_key(canonical)

    if col_norm == canonical_norm:
        return 100

    for syn in synonyms:
        if col_norm == normalize_key(syn):
            return 90

    best_partial = 0
    if canonical_norm in col_norm:
        best_partial = max(best_partial, 70)
    if col_norm in canonical_norm:
        best_partial = max(best_partial, 60)

    for syn in synonyms:
        syn_norm = normalize_key(syn)
        if syn_norm in col_norm:
            best_partial = max(best_partial, 80)
        if col_norm in syn_norm:
            best_partial = max(best_partial, 70)

    return best_partial


def resolve_columns(
    df: "pd.DataFrame",
    aliases: Dict[str, List[str]],
    use_fuzzy: bool = True,
    score_threshold: int = 60
) -> Tuple[Dict[str, Optional[str]], List[str]]:
    if not HAS_PANDAS or df is None:
        return {}, list(aliases.keys())

    cols = list(df.columns)
    norm_to_real = {normalize_key(c): str(c) for c in cols}

    mapping: Dict[str, Optional[str]] = {}
    missing: List[str] = []

    if not use_fuzzy:
        # Exakt/alias-matchning (icke-fuzzy): varje kolumn en gång
        used: set = set()
        for canonical, synonyms in aliases.items():
            found = None
            canonical_norm = normalize_key(canonical)
            if canonical_norm in norm_to_real:
                found = norm_to_real[canonical_norm]
            if not found:
                for syn in synonyms:
                    syn_norm = normalize_key(syn)
                    if syn_norm in norm_to_real:
                        found = norm_to_real[syn_norm]
                        break
            if found and found not in used:
                mapping[canonical] = found
                used.add(found)
            else:
                mapping[canonical] = None
                missing.append(canonical)
        return mapping, missing

    # FUZZY: greedy-unik tilldelning (DATA-FÖRLUST-FIX v2.1.1).
    # Utan unikhet kunde samma kolumn mappas till FLERA canonicaler
    # (t.ex. "Årsmodell" -> MODELYEAR via "ÅRSMODELL" [90] OCH
    # MODELNAME via "MODELL" [70]) — rename_map-kollisionen tappade
    # sedan MODELYEAR helt.
    candidates: List[Tuple[int, str, str]] = []  # (score, canonical, col)
    for canonical, synonyms in aliases.items():
        for col in cols:
            score = calculate_match_score(col, canonical, synonyms)
            if score >= score_threshold:
                candidates.append((score, canonical, col))

    candidates.sort(key=lambda x: x[0], reverse=True)

    used_cols: set = set()
    assigned: set = set()
    for score, canonical, col in candidates:
        if canonical in assigned or col in used_cols:
            continue
        mapping[canonical] = col
        used_cols.add(col)
        assigned.add(canonical)

    for canonical in aliases.keys():
        if canonical not in mapping or mapping[canonical] is None:
            if canonical not in mapping:
                mapping[canonical] = None
            missing.append(canonical)

    return mapping, missing


def strip_object_columns(df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Rensa objekt-kolumner.

    NaN/None -> "" (inte strängen "nan" — annars passerar "nan" som
    icke-tomt värde för VIN/årsmodell längre fram).
    """
    if not HAS_PANDAS:
        return df
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].apply(
                lambda v: "" if v is None or (
                    isinstance(v, float) and v != v
                ) else str(v).strip()
            )
    return df


def get_column_types(df: "pd.DataFrame") -> Dict[str, str]:
    if not HAS_PANDAS:
        return {}
    return {col: str(df[col].dtype) for col in df.columns}


def suggest_mappings(
    df: "pd.DataFrame",
    aliases: Dict[str, List[str]],
    top_n: int = 3
) -> Dict[str, List[Tuple[str, int]]]:
    """Föreslå möjliga mappningar för varje canonical med poäng."""
    if not HAS_PANDAS:
        return {}

    cols = list(df.columns)
    suggestions = {}

    for canonical, synonyms in aliases.items():
        scores = []
        for col in cols:
            score = calculate_match_score(col, canonical, synonyms)
            if score > 0:
                scores.append((col, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        suggestions[canonical] = scores[:top_n]

    return suggestions


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "ColumnResolver",
    "resolve_columns",
    "normalize_key",
    "strip_object_columns",
    "get_column_types",
    "suggest_mappings",
    "calculate_match_score",
    "get_copyright_string",
    "DISPATCH_ALIAS",
    "SAP_ALIAS",
    "HAS_PANDAS",
    "VERSION",
    "AUTHOR",
]
