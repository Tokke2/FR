# -*- coding: utf-8 -*-
# Fil: plugins/sap_import/core/date_converter.py

"""
Datumkonvertering för SAP/Dispatch-data med TS-spec integration (v2.1.1).

Hanterar konvertering till:
    - ISO-format (YYYY-MM-DD)
    - TS-format (YYMMDD / YYYYMMDD) med schema-support

Funktioner:
    - App-aware med TS-spec integration
    - Caching av TS-datumformat
    - Event-lyssning på schema-uppdateringar
    - Validering mot TS-regler
    - Stöd för "unknown date" markers

Användning (standalone):
    >>> from plugins.sap_import.core.date_converter import to_iso_date
    >>> to_iso_date(43831)
    '2020-01-01'

Användning (med app):
    >>> converter = DateConverter(app)
    >>> converter.to_ts_date("2023-01-15", format="YYMMDD")
    '230115'

FÖRÄNDRINGAR v2.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (KRAV 55–57, IDE-VARNING): "Import core.plugin_manager could
      not be resolved" — TYPE_CHECKING-importen pekade på
      core.plugin_manager som INTE finns (trädet: core har
      application/config/event_bus/exceptions/plugin_base/
      plugin_loader/__init__). Nu: Optional[Any] — varningen
      försvinner.
    - FIX (låst regel): f-string-logganrop -> lazy %s (3 st:
      _on_schema_changed, to_iso_date strict, to_ts_date standalone).
    - VERSION/AUTHOR/get_copyright_string tillagda (saknades helt).
    - FIX (korrekthet): get_ts_format() läste field.data_type — men
      ts_schema_manager-modellen (FieldSpec) har field_type/type_code,
      INTE data_type → TS-formatet hämtades ALDRIG (tyst fallback).
      Nu: data_type ("D6"/"D8") ELLER field_type "date" (length 6/8),
      och koll mot ts_schema_manager (source of truth) FÖRST, sedan
      ts_spec_import (spec-arkitektur-prioritet).
    - FIX (stabilitet): DateConverter prenumererade på events utan
      avregistrering ("unsubscribe KRÄVS vid cleanup" — master).
      Nu: _unregister_events() + close() (off/unsubscribe + cache-
      rensning); handler-referens sparas.
    - _check_ts_spec_available(): kollar nu BÅDE ts_schema_manager
      och ts_spec_import (tidigare bara ts_spec_import).
    - _on_schema_changed(event) -> _on_schema_changed(data)
      (parameternamn, konvention).
    - Docstring-exempel korrigerat (44927 -> 43831 = 2020-01-01,
      verifierat i test).
    - Övrig logik OFÖRÄNDRAD (Excel-serial, parsning, TS-format,
      unknown-markers, validate/range/future/normalize).
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Literal, Optional, Tuple, Union

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
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

EXCEL_EPOCH_1900 = date(1899, 12, 30)
EXCEL_EPOCH_1904 = date(1904, 1, 1)

EXCEL_MIN_SERIAL = 1
EXCEL_MAX_SERIAL = 2958465

DEFAULT_TS_FORMATS = {
    "YYMMDD": "%y%m%d",
    "YYYYMMDD": "%Y%m%d",
    "D6": "%y%m%d",
    "D8": "%Y%m%d",
}

COMMON_DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y",
    "%m/%d/%Y", "%m-%d-%Y",
    "%Y%m%d",
]

TS_MIN_YEAR = 1900
TS_MAX_YEAR = 2099

TS_UNKNOWN_DATES = {
    6: "000000",
    8: "00000000",
}


# ══════════════════════════════════════════════════════════════════════════════
# DATE CONVERTER CLASS
# ══════════════════════════════════════════════════════════════════════════════

class DateConverter:
    """
    App-aware datumkonverterare med TS-spec integration.
    """

    def __init__(self, app: Optional[Any] = None):
        self.app = app
        self._format_cache: Dict[Tuple[str, str], str] = {}
        self._has_ts_spec = False
        self._event_handler: Optional[Tuple[str, Any]] = None

        if app:
            self._check_ts_spec_available()
            self._register_events()

    def _check_ts_spec_available(self) -> None:
        """Kontrollera om någon schema-källa finns (source of truth
        eller fallback)."""
        if not self.app:
            return
        try:
            self._has_ts_spec = bool(
                getattr(self.app, "ts_schema_manager", None)
                or getattr(self.app, "ts_spec_import", None)
            )
        except Exception:
            self._has_ts_spec = False

    def _register_events(self) -> None:
        if not self.app or not hasattr(self.app, "event_bus"):
            return
        try:
            bus = self.app.event_bus
            method = getattr(bus, "on", None) or getattr(bus, "subscribe", None)
            if callable(method):
                method("ts_spec:version_changed", self._on_schema_changed)
                self._event_handler = (
                    "ts_spec:version_changed",
                    self._on_schema_changed,
                )
        except Exception:
            pass

    def _unregister_events(self) -> None:
        """Avregistrera event-handler (cleanup-kontrakt)."""
        if not self.app or not hasattr(self.app, "event_bus"):
            return
        try:
            handler = self._event_handler
            if handler is None:
                return
            bus = self.app.event_bus
            method = getattr(bus, "off", None) or getattr(bus, "unsubscribe", None)
            if callable(method):
                method(handler[0], handler[1])
            self._event_handler = None
        except Exception:
            pass

    def close(self) -> None:
        """Avregistrera events och rensa cache (cleanup-kontrakt)."""
        self._unregister_events()
        self._format_cache.clear()

    def _on_schema_changed(self, data: Optional[Dict[str, Any]] = None) -> None:
        _log.info("TS-spec ändrad — rensar datumformat-cache")
        self._format_cache.clear()

    def get_ts_format(
        self,
        post_type: str,
        field_name: str,
        default: str = "YYMMDD"
    ) -> str:
        cache_key = (post_type, field_name)
        if cache_key in self._format_cache:
            return self._format_cache[cache_key]

        fmt = self._lookup_schema_format(post_type, field_name)
        if fmt is None:
            fmt = default

        self._format_cache[cache_key] = fmt
        return fmt

    def _lookup_schema_format(
        self, post_type: str, field_name: str
    ) -> Optional[str]:
        """
        Slå upp TS-datumformat i schema.

        Prioritet: ts_schema_manager (source of truth) ->
        ts_spec_import (fallback). Stödjer data_type ("D6"/"D8")
        OCH field_type "date" med length 6/8 (ts_schema_manager-
        modellen har field_type/type_code, inte data_type).

        Returns:
            "YYMMDD" eller "YYYYMMDD", eller None om ej hittat
        """
        if not self._has_ts_spec or not self.app:
            return None

        for plugin_name in ("ts_schema_manager", "ts_spec_import"):
            try:
                plugin = getattr(self.app, plugin_name, None)
                if plugin is None or not hasattr(plugin, "get_schema"):
                    continue
                schema = plugin.get_schema(post_type)
                if schema is None or not hasattr(schema, "get_field"):
                    continue
                field = schema.get_field(field_name)
                if field is None:
                    continue

                data_type = str(getattr(field, "data_type", "") or "").upper()
                field_type = str(getattr(field, "field_type", "") or "").lower()
                length = int(getattr(field, "length", 0) or 0)

                if data_type in ("D6", "D8"):
                    return "YYMMDD" if data_type == "D6" else "YYYYMMDD"
                if field_type == "date":
                    return "YYYYMMDD" if length >= 8 else "YYMMDD"
            except Exception:
                continue

        return None

    def to_iso_date(
        self,
        val: Any,
        default: str = "",
        strict: bool = False
    ) -> str:
        return to_iso_date(val, default=default, strict=strict)

    def to_ts_date(
        self,
        val: Any,
        post_type: Optional[str] = None,
        field_name: Optional[str] = None,
        format: Optional[Literal["YYMMDD", "YYYYMMDD"]] = None,
        default: str = "",
        allow_unknown: bool = True
    ) -> str:
        if format:
            ts_format = format
        elif post_type and field_name:
            ts_format = self.get_ts_format(post_type, field_name)
        else:
            ts_format = "YYMMDD"

        length = 6 if ts_format in ("YYMMDD", "D6") else 8

        if val is None or (isinstance(val, str) and not val.strip()):
            if allow_unknown:
                return TS_UNKNOWN_DATES.get(length, default)
            return default

        iso_date = self.to_iso_date(val, default="")
        if not iso_date:
            if allow_unknown:
                return TS_UNKNOWN_DATES.get(length, default)
            return default

        try:
            dt = datetime.fromisoformat(iso_date)
            if ts_format in ("YYMMDD", "D6") and dt.year > TS_MAX_YEAR:
                ts_format = "YYYYMMDD"
            fmt_str = DEFAULT_TS_FORMATS.get(ts_format, "%y%m%d")
            return dt.strftime(fmt_str)
        except Exception:
            if allow_unknown:
                return TS_UNKNOWN_DATES.get(length, default)
            return default

    def validate_for_ts(
        self,
        val: Any,
        post_type: Optional[str] = None,
        field_name: Optional[str] = None
    ) -> Tuple[bool, str]:
        iso_date = self.to_iso_date(val)
        if not iso_date:
            return False, "Kunde inte parsa datum"

        try:
            dt = datetime.fromisoformat(iso_date).date()
            if dt.year < TS_MIN_YEAR:
                return (
                    False,
                    f"År {dt.year} före TS-minimum ({TS_MIN_YEAR})",
                )
            if post_type and field_name:
                fmt = self.get_ts_format(post_type, field_name)
            else:
                fmt = "YYMMDD"
            if fmt in ("YYMMDD", "D6") and dt.year > TS_MAX_YEAR:
                return (
                    False,
                    f"År {dt.year} överstiger YYMMDD-gränsen "
                    f"({TS_MAX_YEAR})",
                )
            return True, ""
        except Exception as e:
            return False, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# STANDALONE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def to_iso_date(
    val: Any,
    default: str = "",
    strict: bool = False
) -> str:
    if val is None:
        return default

    if HAS_PANDAS:
        if isinstance(val, float) and pd.isna(val):
            return default
        if isinstance(val, pd.Timestamp):
            try:
                if pd.isna(val):
                    return default
                return val.date().isoformat()
            except Exception:
                return default

    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()

    if isinstance(val, (int, float)) and not isinstance(val, bool):
        result = _from_excel_serial(val)
        if result:
            return result
        return default

    s = str(val).strip()
    if not s or s.lower() in ('nan', 'nat', 'none', 'null', ''):
        return default

    if s.replace('.', '', 1).replace('-', '', 1).isdigit():
        try:
            result = _from_excel_serial(float(s))
            if result:
                return result
        except (ValueError, OverflowError):
            pass

    result = _parse_date_string(s)
    if result:
        return result

    result = _parse_with_formats(s)
    if result:
        return result

    if strict:
        _log.warning("Kunde inte parsa datum: '%s'", val)
    return default


def to_ts_date(
    val: Any,
    format: Literal["YYMMDD", "YYYYMMDD"] = "YYMMDD",
    default: str = "",
    allow_unknown: bool = False
) -> str:
    length = 6 if format == "YYMMDD" else 8

    if val is None or (isinstance(val, str) and not val.strip()):
        if allow_unknown:
            return TS_UNKNOWN_DATES.get(length, default)
        return default

    iso_date = to_iso_date(val, default="")
    if not iso_date:
        if allow_unknown:
            return TS_UNKNOWN_DATES.get(length, default)
        return default

    try:
        dt = datetime.fromisoformat(iso_date)
        if format == "YYMMDD" and dt.year > TS_MAX_YEAR:
            _log.warning(
                "År %d överstiger YYMMDD-gränsen (2099)",
                dt.year,
            )
        fmt_str = DEFAULT_TS_FORMATS.get(format, "%y%m%d")
        return dt.strftime(fmt_str)
    except Exception:
        if allow_unknown:
            return TS_UNKNOWN_DATES.get(length, default)
        return default


def validate_date(
    val: Any,
    min_year: int = TS_MIN_YEAR,
    max_year: int = TS_MAX_YEAR
) -> Tuple[bool, str]:
    iso_date = to_iso_date(val)
    if not iso_date:
        return False, "Kunde inte parsa datum"
    try:
        dt = datetime.fromisoformat(iso_date).date()
        if dt.year < min_year or dt.year > max_year:
            return (
                False,
                f"År {dt.year} utanför spannet "
                f"({min_year}-{max_year})",
            )
        return True, ""
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _from_excel_serial(serial: Union[int, float]) -> Optional[str]:
    if not isinstance(serial, (int, float)):
        return None
    if serial < EXCEL_MIN_SERIAL or serial > EXCEL_MAX_SERIAL:
        return None
    try:
        # Excel 1900-bugg: serial 60 = 1900-02-29 (fiktivt datum)
        if serial == 60:
            return None
        result_date = EXCEL_EPOCH_1900 + timedelta(days=int(serial))
        # 1904-systemet (äldre Mac Excel) för tidiga datum
        if result_date.year < 1920 and serial > 1000:
            result_date = EXCEL_EPOCH_1904 + timedelta(days=int(serial))
        return result_date.isoformat()
    except (ValueError, OverflowError):
        return None


def _parse_date_string(s: str) -> Optional[str]:
    m = re.fullmatch(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', s)
    if m:
        try:
            y, mo, d = map(int, m.groups())
            return date(y, mo, d).isoformat()
        except ValueError:
            return None

    m = re.fullmatch(r'(\d{1,2})[./-](\d{1,2})[./-](\d{4})', s)
    if m:
        try:
            d, mo, y = map(int, m.groups())
            return date(y, mo, d).isoformat()
        except ValueError:
            return None

    if re.fullmatch(r'\d{8}', s):
        try:
            y, mo, d = int(s[:4]), int(s[4:6]), int(s[6:8])
            if 1900 <= y <= 9999:
                return date(y, mo, d).isoformat()
        except ValueError:
            pass
        try:
            d, mo, y = int(s[:2]), int(s[2:4]), int(s[4:8])
            if 1900 <= y <= 9999:
                return date(y, mo, d).isoformat()
        except ValueError:
            pass
    return None


def _parse_with_formats(s: str) -> Optional[str]:
    for fmt in COMMON_DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.date().isoformat()
        except (ValueError, TypeError):
            continue
    return None


def parse_partial_date(s: str, default_day: int = 1) -> Optional[str]:
    s = s.strip()
    m = re.fullmatch(r'(\d{4})-(\d{1,2})', s)
    if m:
        try:
            y, mo = map(int, m.groups())
            return date(y, mo, default_day).isoformat()
        except ValueError:
            return None
    if re.fullmatch(r'\d{4}', s):
        try:
            y = int(s)
            if 1900 <= y <= 9999:
                return date(y, 1, default_day).isoformat()
        except ValueError:
            return None
    return None


def get_date_range(start: Any, end: Any) -> Optional[int]:
    start_iso = to_iso_date(start)
    end_iso = to_iso_date(end)
    if not start_iso or not end_iso:
        return None
    try:
        d1 = datetime.fromisoformat(start_iso).date()
        d2 = datetime.fromisoformat(end_iso).date()
        return (d2 - d1).days
    except Exception:
        return None


def is_future_date(val: Any, reference: Optional[date] = None) -> bool:
    iso_date = to_iso_date(val)
    if not iso_date:
        return False
    try:
        dt = datetime.fromisoformat(iso_date).date()
        ref = reference or date.today()
        return dt > ref
    except Exception:
        return False


def normalize_date_format(val: Any, output_format: str = "%Y-%m-%d") -> str:
    iso_date = to_iso_date(val)
    if not iso_date:
        return ""
    try:
        dt = datetime.fromisoformat(iso_date)
        return dt.strftime(output_format)
    except Exception:
        return ""


def is_valid_ts_unknown_marker(val: str) -> bool:
    return val in TS_UNKNOWN_DATES.values()


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "DateConverter",
    "to_iso_date",
    "to_ts_date",
    "validate_date",
    "parse_partial_date",
    "get_date_range",
    "is_future_date",
    "normalize_date_format",
    "is_valid_ts_unknown_marker",
    "get_copyright_string",
    "DEFAULT_TS_FORMATS",
    "TS_MIN_YEAR",
    "TS_MAX_YEAR",
    "TS_UNKNOWN_DATES",
    "HAS_PANDAS",
    "VERSION",
    "AUTHOR",
]
