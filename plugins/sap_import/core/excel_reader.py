# -*- coding: utf-8 -*-
# Fil: plugins/sap_import/core/excel_reader.py

"""
Excel-läsning med automatisk header-detektion för SAP/Dispatch-filer (v2.1.1).

Detekterar header-rad automatiskt (vanligt problem med SAP-exporter).

Strategier:
    1. Header på rad 5 (vanligt för SAP)
    2. Skanna första 20–200 raderna och poängsätt
    3. Fallback till rad 1

Användning:
    >>> xls = pd.ExcelFile("sap_export.xlsx")
    >>> df, mapping = read_excel_with_header_detection(
    ...     xls, "Sheet1", COLUMN_ALIASES
    ... )

FÖRÄNDRINGAR v2.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (låst regel): alla f-string-logganrop -> lazy %s.
    - VERSION/AUTHOR/get_copyright_string tillagda (saknades helt).
    - FIX (KRAV 58): header normaliserad — "# Fil: plugins/sap_import/
      core/excel_reader.py".
    - FIX (kraschsäkerhet): import från .column_resolver utan fallback
      → modulen gick inte att importera om column_resolver saknas.
      Nu try/except med funktions-fallbackar (resolve_columns via
      COLUMN_ALIASES-hjälp; strip_object_columns inline) — samma
      mönster som övriga moduler.
    - FIX (korrekthet): _scan_for_header() returnerade best_df (en
      KOPIA av raw med manuellt satta kolumnnamn) — om anroparen
      använde df:n direkt kunde kolumn-index/namn bli inkonsekventa
      mot mapping. Nu: OMLÄSNING med header=best_idx (konsistent med
      resten).
    - Oanvända importer borttagna (Path används, TYPE_CHECKING/pd
      TYPE_CHECKING-block onödigt — pd importeras ändå; Optional
      behålls).
    - Övrig logik OFÖRÄNDRAD (strategier 1–3, poängsättning,
      engine-detection, validate/preview).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None
    HAS_PANDAS = False

try:
    from .column_resolver import resolve_columns, strip_object_columns
except ImportError:
    # Kraschsäker fallback om column_resolver.py inte levererats än
    def resolve_columns(df: Any, expected_aliases: Dict[str, List[str]]) -> Tuple[Dict[str, Optional[str]], List[str]]:
        """Fallback: enkel exakt/alias-matchning av kolumnnamn."""
        mapping: Dict[str, Optional[str]] = {}
        missing: List[str] = []
        columns = [str(c).strip() for c in (df.columns if hasattr(df, "columns") else [])]
        for canonical, aliases in expected_aliases.items():
            found = None
            for col in columns:
                col_lower = col.lower().replace("_", "").replace("-", "").replace(" ", "")
                for alias in aliases:
                    if col_lower == alias.lower().replace("_", "").replace("-", "").replace(" ", ""):
                        found = col
                        break
                if found:
                    break
            if found:
                mapping[canonical] = found
            else:
                missing.append(canonical)
        return mapping, missing

    def strip_object_columns(df: Any) -> Any:
        """Fallback: konvertera objekt-kolumner till str."""
        try:
            for col in df.columns:
                if hasattr(df[col], "dtype") and str(df[col].dtype) == "object":
                    df[col] = df[col].astype(str)
        except Exception:
            pass
        return df

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

DEFAULT_SCAN_ROWS = 200
DEFAULT_MAX_HEADER_SEARCH = 20
DEFAULT_MIN_SCORE = 2
DEFAULT_CRITICAL_COLUMNS = ["VINCODE", "MODELYEAR", "APPROVAL"]


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def read_excel_with_header_detection(
    xls: Any,
    sheet_name: str,
    expected_aliases: Dict[str, List[str]],
    config: Optional[Dict[str, Any]] = None,
    prefer_row_5: bool = True
) -> Tuple[Any, Dict[str, Optional[str]]]:
    """
    Läs Excel-blad med automatisk header-detektion.
    """
    if not HAS_PANDAS:
        raise ImportError(
            "pandas krävs för Excel-läsning. "
            "Installera med: pip install pandas openpyxl"
        )

    if config is None:
        config = {}

    scan_rows = config.get("excel_header_scan_nrows", DEFAULT_SCAN_ROWS)
    require_all = config.get("require_all_columns", False)
    critical_columns = config.get("critical_columns", DEFAULT_CRITICAL_COLUMNS)

    _log.debug("Läser blad '%s' med header-detektion", sheet_name)

    # STRATEGI 1: Header på rad 5
    if prefer_row_5:
        try:
            df = pd.read_excel(xls, sheet_name=sheet_name, header=4, dtype=str)
            df = strip_object_columns(df)
            mapping, missing = resolve_columns(df, expected_aliases)

            if _is_acceptable_mapping(
                mapping, missing, require_all, len(expected_aliases)
            ):
                _log.info("Header hittad på rad 5 för '%s'", sheet_name)
                return df, mapping
        except Exception as e:
            _log.debug("Rad 5-strategin misslyckades: %s", e)

    # STRATEGI 2: Skanna rader
    try:
        result = _scan_for_header(
            xls, sheet_name, expected_aliases,
            scan_rows=scan_rows,
            max_search=DEFAULT_MAX_HEADER_SEARCH,
            critical_columns=critical_columns
        )
        if result is not None:
            df, mapping, header_idx = result
            _log.info(
                "Header hittad på rad %d för '%s'",
                header_idx + 1, sheet_name,
            )
            return df, mapping
    except Exception as e:
        _log.warning("Header-skanning misslyckades: %s", e)

    # STRATEGI 3: Fallback
    _log.warning("Använder default-header (rad 1) för '%s'", sheet_name)
    df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str)
    df = strip_object_columns(df)
    mapping, missing = resolve_columns(df, expected_aliases)

    if missing:
        _log.warning("Default-header saknar kolumner: %s", missing)

    return df, mapping


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _is_acceptable_mapping(
    mapping: Dict[str, Optional[str]],
    missing: List[str],
    require_all: bool,
    total_expected: int
) -> bool:
    if require_all:
        return len(missing) == 0
    found = len(mapping) - len(missing)
    return found >= (total_expected / 2)


def _scan_for_header(
    xls: Any,
    sheet_name: str,
    expected_aliases: Dict[str, List[str]],
    scan_rows: int,
    max_search: int,
    critical_columns: List[str]
) -> Optional[Tuple[Any, Dict[str, Optional[str]], int]]:
    raw = pd.read_excel(
        xls, sheet_name=sheet_name, header=None,
        nrows=scan_rows, dtype=str
    )
    raw = strip_object_columns(raw)

    if raw.empty:
        return None

    best_idx = -1
    best_score = -1
    best_mapping: Dict[str, Optional[str]] = {}

    for i in range(min(max_search, len(raw))):
        header_row = [str(x).strip() for x in raw.iloc[i].tolist()]
        if _is_empty_row(header_row):
            continue

        tmp_df = raw.copy()
        tmp_df.columns = header_row
        tmp_df = tmp_df.iloc[i + 1:]

        if tmp_df.empty:
            continue

        mapping, missing = resolve_columns(
            tmp_df, expected_aliases
        )
        score = _calculate_header_score(
            mapping, missing, expected_aliases, critical_columns
        )

        if score > best_score:
            best_score = score
            best_idx = i
            best_mapping = mapping

    if best_idx >= 0 and best_score >= DEFAULT_MIN_SCORE:
        # OMLÄSNING med header=best_idx — konsistent df (fix v2.1.1:
        # tidigare returnerades en kopia av raw med manuellt satta
        # kolumnnamn, vilket kunde ge inkonsekventa index/namn).
        df = pd.read_excel(
            xls, sheet_name=sheet_name, header=best_idx, dtype=str
        )
        df = strip_object_columns(df)
        mapping, _ = resolve_columns(df, expected_aliases)
        return df, mapping, best_idx

    return None


def _is_empty_row(row: List[str]) -> bool:
    return all(
        x == "" or x.lower() in ("nan", "none", "null") for x in row
    )


def _calculate_header_score(
    mapping: Dict[str, Optional[str]],
    missing: List[str],
    expected_aliases: Dict[str, List[str]],
    critical_columns: List[str]
) -> int:
    score = len(expected_aliases) - len(missing)
    for col in critical_columns:
        if col in expected_aliases and mapping.get(col):
            score += 2
    return score


# ══════════════════════════════════════════════════════════════════════════════
# ENGINE DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def get_excel_engine(filepath: Path) -> Optional[str]:
    if isinstance(filepath, str):
        filepath = Path(filepath)

    ext = filepath.suffix.lower()

    if ext in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        try:
            import openpyxl
            return "openpyxl"
        except ImportError:
            _log.warning("openpyxl ej installerat")
            return None

    if ext == ".xls":
        try:
            import xlrd
            return "xlrd"
        except ImportError:
            _log.warning("xlrd ej installerat")
            return None

    _log.warning("Okänt Excel-format: %s", ext)
    return None


def validate_excel_file(filepath: Path) -> Tuple[bool, str]:
    if not filepath.exists():
        return False, f"Filen finns inte: {filepath}"
    if not filepath.is_file():
        return False, f"Inte en fil: {filepath}"

    ext = filepath.suffix.lower()
    valid_extensions = {".xls", ".xlsx", ".xlsm", ".xltx", ".xltm"}

    if ext not in valid_extensions:
        return False, f"Ogiltig filtyp: {ext}"

    engine = get_excel_engine(filepath)
    if engine is None:
        return False, f"Ingen Excel-engine tillgänglig för {ext}"

    return True, ""


def get_sheet_names(filepath: Path) -> List[str]:
    if not HAS_PANDAS:
        raise ImportError("pandas krävs")

    is_valid, error = validate_excel_file(filepath)
    if not is_valid:
        raise ValueError(error)

    engine = get_excel_engine(filepath)
    try:
        xls = pd.ExcelFile(filepath, engine=engine)
        sheets = xls.sheet_names
        xls.close()
        return sheets
    except Exception as e:
        raise ValueError(f"Kunde inte läsa Excel-fil: {e}")


def preview_sheet(
    filepath: Path,
    sheet_name: str,
    nrows: int = 10
) -> Optional[Any]:
    if not HAS_PANDAS:
        return None

    engine = get_excel_engine(filepath)
    try:
        df = pd.read_excel(
            filepath, sheet_name=sheet_name, nrows=nrows,
            engine=engine, dtype=str
        )
        return strip_object_columns(df)
    except Exception as e:
        _log.error("Förhandsvisning misslyckades: %s", e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "read_excel_with_header_detection",
    "get_excel_engine",
    "validate_excel_file",
    "get_sheet_names",
    "preview_sheet",
    "HAS_PANDAS",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]
