# -*- coding: utf-8 -*-
# Fil: plugins/dealers_manager/import_logic/excel_reader.py
# Copyright © 2025 Rickard Längkvist

"""
Excel-import för återförsäljare med headerdetektion.

ANSVAR:
  - Läsa Excel-filer med automatisk header-detektering
  - Normalisera kolumnnamn för synonym-matchning
  - Hitta rätt kolumner för DN, Namn och T6/orgnr
  - Stödja .xlsx, .xlsm, .xls med rätt engine
  - Hantera Excel-filer med header på valfri rad (0–20)
  - Kraschsäkra funktioner med tydliga fallbacks

IMPORTER:
  re, logging, pathlib (Path), typing (Any, Optional, Tuple)
  pandas (valfri – kontrolleras vid runtime)
  plugins.dealers_manager.import_logic.synonyms
    (DN_SYNONYMS, NAMN_SYNONYMS, T6_SYNONYMS)

EXPORTERAR (PUBLIKA FUNKTIONER):
  normalize_key(s)                          -> str
  strip_object_columns(df)                  -> pd.DataFrame
  resolve_columns(df)                       -> Tuple[Optional[str],
                                                     Optional[str],
                                                     Optional[str]]
  read_excel_with_header_detection(xls, sheet_name) -> pd.DataFrame
  get_excel_engine(path)                    -> Optional[str]

ANVÄNDS AV:
  plugins/dealers_manager/plugin.py
    → Plugin._process_excel_sheet()
    → Plugin.import_from_excel()

HEADER-DETEKTIONS STRATEGI:
  1. header=4  (vanligt i svenska system-exportfiler)
  2. header=0  (standard)
  3. Skanning rad 0–20 med poängsystem (dn=2, namn=2, t6=1, min=3)
  4. Fallback: header=0 utan validering

FÖRÄNDRINGAR v2.2.1:
  - Importväg fixad: synonyms ligger i samma mapp (import_logic/)
    FÖRE: from plugins.dealers_manager.synonyms import ...
    EFTER: from plugins.dealers_manager.import_logic.synonyms import ...
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple

# ── FIXAD IMPORTVÄG — synonyms.py ligger i samma mapp (import_logic/) ──
from plugins.dealers_manager.import_logic.synonyms import (
    DN_SYNONYMS,
    NAMN_SYNONYMS,
    T6_SYNONYMS,
)


# ──────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL LOGGER
# ──────────────────────────────────────────────────────────────────────────────

_log: logging.Logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

# Poänggräns för att en skannad header-rad ska accepteras
_HEADER_MIN_SCORE: Final[int] = 3

# Max antal rader att skanna vid header-detektering
_HEADER_SCAN_ROWS: Final[int] = 200

# Max antal rader att testa som möjlig header-rad
_HEADER_TEST_LIMIT: Final[int] = 20

# Pandas-status
try:
    import pandas as pd  # type: ignore
    _PANDAS_AVAILABLE: Final[bool] = True
except ImportError:
    pd = None  # type: ignore
    _PANDAS_AVAILABLE: Final[bool] = False

if not _PANDAS_AVAILABLE:
    _log.warning(
        "pandas ej installerat – excel_reader.py fungerar ej"
    )

# ──────────────────────────────────────────────────────────────────────────────
# Poängsättning per träff (används i header-skanningen)
# ──────────────────────────────────────────────────────────────────────────────

_SCORE_DN: Final[int] = 2
_SCORE_NAMN: Final[int] = 2
_SCORE_T6: Final[int] = 1


# ══════════════════════════════════════════════════════════════════════════════
# NORMALISERINGSVERKTYG
# ══════════════════════════════════════════════════════════════════════════════


def normalize_key(s: Any) -> str:
    """
    Normalisera nyckel för case-insensitive, accent-ignorerande jämförelse.

    Steg:
      1. Konvertera till str och strip
      2. Lowercase
      3. Ersätt svenska tecken (å→a, ä→a, ö→o)
      4. Ta bort alla icke-alfanumeriska tecken (inkl. understreck)

    Args:
        s: Värde att normalisera (str, int, None etc.)

    Returns:
        Normaliserad sträng, t.ex. "Dealer Number" → "dealernumber"

    Exempel:
        normalize_key("Dealer Number")  → "dealernumber"
        normalize_key("Återförsäljare") → "aterforsaljare"
        normalize_key(None)             → ""
        normalize_key(123)              → "123"
    """
    if s is None:
        return ""
    x = str(s).strip().lower()
    x = (
        x.replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace("é", "e")
        .replace("è", "e")
        .replace("ü", "u")
        .replace("ñ", "n")
    )
    return re.sub(r"[\W_]+", "", x, flags=re.UNICODE)


# ══════════════════════════════════════════════════════════════════════════════
# DATAFRAME-RENSNING
# ══════════════════════════════════════════════════════════════════════════════


def strip_object_columns(df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Trimma whitespace från alla objekt-kolumner i DataFrame.

    Konverterar object-dtype kolumner till str och kör .str.strip().
    Ersätter "nan"-strängar med tomma strängar.

    Args:
        df: pandas DataFrame att rensa

    Returns:
        Rensad DataFrame (in-place modifiering av kolumnvärden)

    Kraschsäker:
        Loggar och returnerar original vid fel.
    """
    try:
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = (
                    df[col]
                    .astype(str)
                    .str.strip()
                    .replace("nan", "")
                    .replace("None", "")
                )
        return df
    except Exception as exc:
        _log.warning("strip_object_columns misslyckades: %s", exc)
        return df


# ══════════════════════════════════════════════════════════════════════════════
# KOLUMNMATCHNING
# ══════════════════════════════════════════════════════════════════════════════


def resolve_columns(
    df: "pd.DataFrame",
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Hitta kolumner för DN, Namn och T6 i DataFrame via synonym-matchning.

    Matchning sker via normalize_key() – case-insensitive och
    accent-ignorerande.
    Synonym-listor importeras från import_logic/synonyms.py.
    Prioritetsordning: synonymlistan i ordning (specifika → generella).

    Args:
        df: DataFrame vars kolumner ska matchas

    Returns:
        Tuple med (dn_kolumn, namn_kolumn, t6_kolumn).
        Varje element är det faktiska kolumnnamnet i df, eller None
        om ej hittad.

    Loggar:
        DEBUG: varje matchad kolumn med synonym som matchade
        DEBUG: varje sökning utan träff
    """
    try:
        cols = list(df.columns)
        norm_to_real: Dict[str, str] = {
            normalize_key(c): str(c) for c in cols
        }

        _log.debug(
            "resolve_columns: %d kolumner tillgängliga: %s",
            len(cols),
            cols[:10],
        )

        def _find_first(
            synonyms: List[str], field_name: str
        ) -> Optional[str]:
            for syn in synonyms:
                nk = normalize_key(syn)
                if nk in norm_to_real:
                    matched = norm_to_real[nk]
                    _log.debug(
                        "Kolumn '%s' matchad som %s via synonym '%s'",
                        matched,
                        field_name,
                        syn,
                    )
                    return matched
            _log.debug(
                "Ingen matchning hittad för fält: %s", field_name
            )
            return None

        dn_col = _find_first(DN_SYNONYMS, "DN")
        namn_col = _find_first(NAMN_SYNONYMS, "Namn")
        t6_col = _find_first(T6_SYNONYMS, "T6/Orgnr")

        return dn_col, namn_col, t6_col

    except Exception as exc:
        _log.error(
            "Fel i resolve_columns: %s", exc, exc_info=True
        )
        return None, None, None


# ══════════════════════════════════════════════════════════════════════════════
# HEADER-DETEKTERING
# ══════════════════════════════════════════════════════════════════════════════


def read_excel_with_header_detection(
    xls: "pd.ExcelFile",
    sheet_name: str,
) -> "pd.DataFrame":
    """
    Läs Excel-blad med automatisk header-detektering.

    STRATEGI (i ordning):
      1. header=4  – vanligt i svenska system-exportfiler (SAP, Dispatch)
      2. header=0  – standard Excel-export
      3. Skanning rad 0–{_HEADER_TEST_LIMIT} med poängsystem:
           DN-träff:   +{_SCORE_DN} poäng
           Namn-träff: +{_SCORE_NAMN} poäng
           T6-träff:   +{_SCORE_T6} poäng
           Minst {_HEADER_MIN_SCORE} poäng krävs för accept
      4. Fallback: header=0 utan validering

    Args:
        xls:        Öppen pandas ExcelFile
        sheet_name: Bladets namn

    Returns:
        DataFrame med korrekt header och strippade strängar.
        Returnerar alltid ett DataFrame – aldrig None.

    Loggar:
        INFO:  vilken strategi som lyckades + bladets namn
        DEBUG: detaljer om poängsättning per rad vid skanning
        WARNING: om fallback används
    """
    if not _PANDAS_AVAILABLE:
        raise RuntimeError(
            "pandas ej installerat – kan inte läsa Excel"
        )

    # ── STRATEGI 1: header=4 ──────────────────────────────────────────
    try:
        df = pd.read_excel(
            xls, sheet_name=sheet_name, dtype=str, header=4
        )
        df = strip_object_columns(df)
        dn, nm, _ = resolve_columns(df)
        if dn and nm:
            _log.info(
                "Blad '%s': header detekterad på rad 4 "
                "(strategi 1, DN='%s', Namn='%s')",
                sheet_name, dn, nm,
            )
            return df
        _log.debug(
            "Blad '%s': strategi 1 (header=4) hittade ej DN+Namn",
            sheet_name,
        )
    except Exception as exc:
        _log.debug(
            "Blad '%s': strategi 1 misslyckades: %s",
            sheet_name, exc,
        )

    # ── STRATEGI 2: header=0 ──────────────────────────────────────────
    try:
        df = pd.read_excel(
            xls, sheet_name=sheet_name, dtype=str, header=0
        )
        df = strip_object_columns(df)
        dn, nm, _ = resolve_columns(df)
        if dn and nm:
            _log.info(
                "Blad '%s': header detekterad på rad 0 "
                "(strategi 2, DN='%s', Namn='%s')",
                sheet_name, dn, nm,
            )
            return df
        _log.debug(
            "Blad '%s': strategi 2 (header=0) hittade ej DN+Namn",
            sheet_name,
        )
    except Exception as exc:
        _log.debug(
            "Blad '%s': strategi 2 misslyckades: %s",
            sheet_name, exc,
        )

    # ── STRATEGI 3: SKANNING ──────────────────────────────────────────
    try:
        raw = pd.read_excel(
            xls,
            sheet_name=sheet_name,
            dtype=str,
            header=None,
            nrows=_HEADER_SCAN_ROWS,
        )
        raw = strip_object_columns(raw)

        best_idx: int = -1
        best_score: int = -1

        test_limit = min(_HEADER_TEST_LIMIT, len(raw))

        for i in range(test_limit):
            header_row: List[str] = [
                str(x).strip() for x in raw.iloc[i].tolist()
            ]

            # Hoppa över tomma rader
            if all(
                x == "" or x.lower() in ("nan", "none")
                for x in header_row
            ):
                _log.debug(
                    "Blad '%s': rad %d tom – hoppar över",
                    sheet_name, i,
                )
                continue

            tmp = raw.copy()
            tmp.columns = header_row  # type: ignore[assignment]
            tmp = tmp.iloc[i + 1:].reset_index(drop=True)

            if tmp.empty:
                continue

            dn, nm, t6 = resolve_columns(tmp)
            score = (
                (_SCORE_DN if dn else 0)
                + (_SCORE_NAMN if nm else 0)
                + (_SCORE_T6 if t6 else 0)
            )

            _log.debug(
                "Blad '%s': rad %d poäng=%d "
                "(dn=%s, namn=%s, t6=%s)",
                sheet_name, i, score,
                dn or "–", nm or "–", t6 or "–",
            )

            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx >= 0 and best_score >= _HEADER_MIN_SCORE:
            df = pd.read_excel(
                xls,
                sheet_name=sheet_name,
                dtype=str,
                header=best_idx,
            )
            df = strip_object_columns(df)
            _log.info(
                "Blad '%s': header detekterad på rad %d via skanning "
                "(strategi 3, poäng=%d)",
                sheet_name, best_idx, best_score,
            )
            return df

        _log.debug(
            "Blad '%s': skanning hittade ingen godkänd header "
            "(bästa poäng=%d, kräver >=%d)",
            sheet_name, best_score, _HEADER_MIN_SCORE,
        )

    except Exception as exc:
        _log.warning(
            "Blad '%s': skanning (strategi 3) misslyckades: %s",
            sheet_name, exc, exc_info=True,
        )

    # ── STRATEGI 4: FALLBACK ──────────────────────────────────────────
    _log.warning(
        "Blad '%s': använder fallback (header=0) utan validering",
        sheet_name,
    )
    try:
        df = pd.read_excel(
            xls, sheet_name=sheet_name, dtype=str, header=0
        )
        return strip_object_columns(df)
    except Exception as exc:
        _log.error(
            "Blad '%s': fallback misslyckades: %s",
            sheet_name, exc, exc_info=True,
        )
        # Returnera tom DataFrame med korrekta kolumnnamn
        return pd.DataFrame(
            columns=["dealer_number", "namn", "orgnr"]
        )


# ══════════════════════════════════════════════════════════════════════════════
# ENGINE-DETEKTERING
# ══════════════════════════════════════════════════════════════════════════════


def get_excel_engine(path: Path) -> Optional[str]:
    """
    Returnera rätt pandas Excel-engine baserat på filändelse.

    Stödda format:
      .xlsx, .xlsm, .xltx, .xltm → "openpyxl"
      .xls                        → "xlrd" (om installerat, annars None)
      Övriga                      → None

    Args:
        path: Sökväg till Excel-filen

    Returns:
        Engine-namn som str, eller None om okänt format / saknad
        dependency.

    Loggar:
        DEBUG: vald engine
        WARNING: xlrd saknas vid .xls-import
    """
    try:
        ext = path.suffix.lower()

        if ext in (".xlsx", ".xlsm", ".xltx", ".xltm"):
            _log.debug(
                "Excel-engine: openpyxl för %s", path.name
            )
            return "openpyxl"

        if ext == ".xls":
            try:
                import xlrd  # noqa: F401
                _log.debug(
                    "Excel-engine: xlrd för %s", path.name
                )
                return "xlrd"
            except ImportError:
                _log.warning(
                    "xlrd ej installerat – kan inte läsa .xls-filer. "
                    "Installera med: pip install xlrd==2.0.1"
                )
                return None

        _log.warning(
            "Okänd Excel-filändelse '%s' för %s – ingen engine vald",
            ext, path.name,
        )
        return None

    except Exception as exc:
        _log.error(
            "Fel i get_excel_engine(%s): %s",
            path, exc, exc_info=True,
        )
        return None
