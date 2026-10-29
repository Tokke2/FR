# -*- coding: utf-8 -*-
# Fil: plugins/ts_file_generator/record_builder.py
"""
Record Builder v2.0.1

Bygger TS-poster (PT28/PT45/PT99) schema-drivet.
Hanterar positionering, padding, Latin-1 och fältvalidering.

ANSVAR:
    - Bygga PT28 (identitetspost)
    - Bygga PT45 (fordonspost, en per fordon)
    - Bygga PT99 (slutpost)
    - Schema-driven formatering via PostSpec.format_record()
    - Latin-1 säkring av varje fält
    - Exakt 2500 tecken per rad
    - Fallback-generering om schema saknas
    - Validering av obligatoriska fält

INTEGRATION:
    - Används av: plugin.py
    - Hämtar schema via: ts_schema_manager → ts_spec_import
    - Latin-1 hantering via: latin1_utils

FILFORMAT:
    - Exakt 2500 tecken per rad
    - ISO-8859-1 / Latin-1
    - Radslut: \n
    - Inga extra tecken

FÖRÄNDRINGAR v2.0.1 (granskad — spec v1.6 förbättringsregeln):
    - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2026 ..." i
      docstringen BORTTAGEN — copyright genereras dynamiskt via
      get_copyright_string().
    - FIX (robusthet): import av .latin1_utils var EJ kraschsäker —
      filen levereras senare och modulen kunde inte importeras alls.
      Nu try/except-fallback EXAKT som widget.py (inline-definitioner).
    - FIX (robusthet): validate_latin1() kan returnera antingen bool
      eller (bool, List[str]) beroende på latin1_utils-implementation
      — ny helper _latin1_check() normaliserar båda. Tidigare skulle
      en bool-källa krascha validate_record() med unpack-fel.
    - FIX (korrekthet): _find_value() sökte bara "default_value" men
      models.FieldSpec (ts_schema_manager) använder "default" och
      "constant_value" — konstantfält fick aldrig sitt värde. Nu
      söks default_value, default OCH constant_value.
    - FIX (korrekthet): _validate_required_fields() flaggade fält som
      saknade även när de har default/constant-värde (som används vid
      byggnad) — falska "obligatoriska fält saknas"-varningar. Nu
      räknas fält med default/constant_value som satta (samma
      semantik som models.FieldSpec.validate_value).
    - FIX (korrekthet): format_field_by_type() — "K" (FieldType.code
      för constant enligt models/constants) saknades i
      CONSTANT-grenen → K-fält formaterades som alfanumeriska.
    - get_logger() -> _get_logger() (privat, konvention; _log
      module-level).
    - __all__ kompletterad med get_copyright_string; oanvänd import
      Callable borttagen.
    - Övrig logik OFÖRÄNDRAD (formatörer, fallbacks, build_file,
      singleton/factory).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Final, List, Optional, Tuple

# Kraschsäker import av lokala verktyg (fallback om de inte skapats än)
try:
    from .latin1_utils import ensure_latin1, sanitize_for_ts, validate_latin1
except ImportError:
    def validate_latin1(text: str) -> bool:
        try:
            text.encode("latin-1")
            return True
        except UnicodeEncodeError:
            return False

    def sanitize_for_ts(text: str) -> str:
        return text.encode("latin-1", errors="replace").decode("latin-1")

    def ensure_latin1(text: str) -> str:
        return sanitize_for_ts(text)

# ══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "2.0.1"
AUTHOR: Final[str] = "Rickard Längkvist"

TS_RECORD_LENGTH: Final[int] = 2500
TS_ENCODING: Final[str] = "iso-8859-1"

POST_TYPE_IDENTITY: Final[str] = "28"
POST_TYPE_VEHICLE: Final[str] = "45"
POST_TYPE_END: Final[str] = "99"

NUMERIC_PAD_CHAR: Final[str] = "0"
ALPHA_PAD_CHAR: Final[str] = " "

LOPNUMMER_POSITION: Final[int] = 1
LOPNUMMER_LENGTH: Final[int] = 4
POSTTYPE_POSITION: Final[int] = 5
POSTTYPE_LENGTH: Final[int] = 2


def get_copyright_string() -> str:
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════

def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback om logging ej konfigurerat.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("ts_file_generator.record_builder")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log = _get_logger()


def _latin1_check(text: str) -> Tuple[bool, List[str]]:
    """
    Kraschsäker Latin-1-kontroll (normaliserad signatur).

    validate_latin1() kan returnera antingen bool eller
    (bool, List[str]) beroende på latin1_utils-implementation —
    denna helper normaliserar till (bool, List[str]).

    Args:
        text: Text att kontrollera

    Returns:
        Tuple (is_valid: bool, invalid_chars: List[str])
    """
    try:
        result = validate_latin1(text)
        if isinstance(result, tuple):
            ok = bool(result[0])
            chars = list(result[1]) if len(result) > 1 else []
            return ok, chars
        return bool(result), []
    except Exception:
        return False, []


# ══════════════════════════════════════════════════════════════════════
# FIELD FORMATTERS
# ══════════════════════════════════════════════════════════════════════

def format_numeric_field(value: Any, length: int) -> str:
    """
    Formatera numeriskt fält.

    Regler:
        - Endast siffror 0-9
        - Högerjusterat med nollor
        - Trunkeras till exakt längd om för långt

    Args:
        value:  Värde att formatera
        length: Fältlängd i tecken

    Returns:
        Sträng med exakt angiven längd
    """
    if value is None or str(value).strip() == "":
        return NUMERIC_PAD_CHAR * length

    text = re.sub(r"[^\d]", "", str(value).strip())
    if not text:
        return NUMERIC_PAD_CHAR * length

    if len(text) > length:
        text = text[-length:]

    return text.zfill(length)


def format_alpha_field(value: Any, length: int, left_justify: bool = True) -> str:
    """
    Formatera alfanumeriskt fält.

    Regler:
        - Latin-1 säkrat
        - Vänsterjusterat med mellanslag (standard) eller högerjusterat
        - Trunkeras till exakt längd om för långt

    Args:
        value:         Värde att formatera
        length:        Fältlängd i tecken
        left_justify:  True = vänsterjusterat, False = högerjusterat

    Returns:
        Sträng med exakt angiven längd
    """
    if value is None:
        return ALPHA_PAD_CHAR * length

    text = sanitize_for_ts(str(value))

    if len(text) > length:
        text = text[:length]

    if left_justify:
        return text.ljust(length, ALPHA_PAD_CHAR)
    return text.rjust(length, ALPHA_PAD_CHAR)


def format_date_field(value: Any, length: int = 6) -> str:
    """
    Formatera datumfält (YYMMDD eller YYYYMMDD).

    Args:
        value:  Datum som sträng, datetime eller None
        length: Fältlängd (6 = YYMMDD, 8 = YYYYMMDD)

    Returns:
        Sträng med exakt angiven längd
    """
    if value is None:
        return ALPHA_PAD_CHAR * length

    if isinstance(value, datetime):
        if length == 8:
            return value.strftime("%Y%m%d")
        return value.strftime("%y%m%d")

    text = re.sub(r"[^\d]", "", str(value).strip())

    if len(text) == 8 and length == 6:
        text = text[2:]
    elif len(text) == 6 and length == 8:
        text = "20" + text

    if len(text) == length:
        return text

    return ALPHA_PAD_CHAR * length


def format_constant_field(value: Any, length: int) -> str:
    """
    Formatera konstantfält (alltid exakt samma värde).

    Args:
        value:  Konstantvärde
        length: Fältlängd

    Returns:
        Sträng med exakt angiven längd
    """
    if value is None:
        return ALPHA_PAD_CHAR * length
    text = str(value)
    if len(text) > length:
        return text[:length]
    return text.ljust(length, ALPHA_PAD_CHAR)


def format_field_by_type(
    value: Any,
    length: int,
    field_type: str = "ALPHANUMERIC",
    left_justify: bool = True,
) -> str:
    """
    Formatera fält baserat på typ.

    Args:
        value:        Fältvärde
        length:       Fältlängd
        field_type:   NUMERIC / ALPHANUMERIC / DATE / CONSTANT
                      (koderna N/D/K accepteras — FieldType.code)
        left_justify: Gäller för ALPHANUMERIC

    Returns:
        Sträng med exakt angiven längd
    """
    ft = str(field_type).upper().strip()

    if ft in ("NUMERIC", "N", "NUM"):
        return format_numeric_field(value, length)
    if ft in ("DATE", "D", "DATUM"):
        return format_date_field(value, length)
    if ft in ("CONSTANT", "C", "KONST", "CONST", "K"):
        return format_constant_field(value, length)
    return format_alpha_field(value, length, left_justify)


# ══════════════════════════════════════════════════════════════════════
# BUILD RESULT
# ══════════════════════════════════════════════════════════════════════

@dataclass
class BuildResult:
    """
    Resultat från bygge av en TS-post.

    Attributes:
        success:          True om posten byggdes korrekt
        record:           Den byggda posten (exakt 2500 tecken)
        post_type:        Posttyp (28/45/99)
        sequence_no:      Löpnummer
        errors:           Felmeddelanden
        warnings:         Varningsmeddelanden
        fields_set:       Antal fält satta
        fields_total:     Totalt antal fält i schema
        missing_required: Obligatoriska fält som saknar värde
    """
    success: bool = False
    record: str = ""
    post_type: str = ""
    sequence_no: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    fields_set: int = 0
    fields_total: int = 0
    missing_required: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "record": self.record,
            "post_type": self.post_type,
            "sequence_no": self.sequence_no,
            "errors": self.errors,
            "warnings": self.warnings,
            "fields_set": self.fields_set,
            "fields_total": self.fields_total,
            "missing_required": self.missing_required,
            "record_length": len(self.record),
        }


# ══════════════════════════════════════════════════════════════════════
# RECORD BUILDER
# ══════════════════════════════════════════════════════════════════════

class RecordBuilder:
    """
    Bygger TS-poster (PT28/PT45/PT99) schema-drivet.

    Fallback-generering om schema saknas.
    """

    def __init__(
        self,
        app: Optional[Any] = None,
        record_length: int = TS_RECORD_LENGTH,
        encoding: str = TS_ENCODING,
    ) -> None:
        self.app = app
        self.record_length = record_length
        self.encoding = encoding
        self._schema_cache: Dict[str, Any] = {}

    # ─────────────────────────────────────────────────────────────────
    # SCHEMA ACCESS
    # ─────────────────────────────────────────────────────────────────

    def _get_schema(self, post_type: str) -> Optional[Any]:
        """
        Hämta schema för posttyp.

        Prioritet:
            1. Intern cache
            2. ts_schema_manager (source of truth)
            3. ts_spec_import (fallback)

        Args:
            post_type: Posttyp (28/45/99)

        Returns:
            PostSpec eller None
        """
        pt = str(post_type).strip()
        if pt in self._schema_cache:
            return self._schema_cache[pt]

        schema = None

        # ts_schema_manager
        try:
            mgr = self._get_plugin("ts_schema_manager")
            if mgr and hasattr(mgr, "get_schema"):
                schema = mgr.get_schema(pt)
        except Exception as exc:
            _log.debug("ts_schema_manager.get_schema(%s) failed: %s", pt, exc)

        # ts_spec_import fallback
        if schema is None:
            try:
                spec = self._get_plugin("ts_spec_import")
                if spec and hasattr(spec, "get_schema"):
                    schema = spec.get_schema(pt)
            except Exception as exc:
                _log.debug("ts_spec_import.get_schema(%s) failed: %s", pt, exc)

        if schema is not None:
            self._schema_cache[pt] = schema
            _log.debug("Schema PT%s laddad.", pt)

        return schema

    def _get_plugin(self, name: str) -> Optional[Any]:
        """
        Hämta plugin via app. KRASCHSÄKER.

        Args:
            name: Pluginnamn

        Returns:
            Plugin-instans eller None
        """
        if self.app is None:
            return None
        for attr in ("get_plugin", "plugin_loader"):
            try:
                owner = self.app if attr == "get_plugin" else getattr(self.app, attr, None)
                if owner is None:
                    continue
                func = getattr(owner, "get_plugin", None)
                if callable(func):
                    result = func(name)
                    if result is not None:
                        return result
            except Exception:
                pass
        try:
            return getattr(self.app, name, None)
        except Exception:
            return None

    def clear_schema_cache(self) -> None:
        """Rensa schema-cache (tvingar omladdning)."""
        self._schema_cache.clear()
        _log.debug("Schema-cache rensad.")

    # ─────────────────────────────────────────────────────────────────
    # CORE BUILD METHOD
    # ─────────────────────────────────────────────────────────────────

    def _build_from_schema(
        self,
        schema: Any,
        data: Dict[str, Any],
        sequence_no: int,
        post_type: str,
    ) -> BuildResult:
        """
        Bygg post från schema och data.

        Strategi:
            1. Försök schema.format_record(data) direkt
            2. Bygg manuellt fält-för-fält om format_record saknas
            3. Validera obligatoriska fält
            4. Säkerställ exakt radlängd

        Args:
            schema:      PostSpec
            data:        Fältdata
            sequence_no: Löpnummer
            post_type:   Posttyp

        Returns:
            BuildResult
        """
        result = BuildResult(post_type=post_type, sequence_no=sequence_no)

        fields = []
        try:
            fields = list(getattr(schema, "fields", []) or [])
        except Exception:
            pass
        result.fields_total = len(fields)

        # Steg 1: format_record()
        try:
            if hasattr(schema, "format_record") and callable(schema.format_record):
                record = schema.format_record(data)
                if isinstance(record, str) and len(record) == self.record_length:
                    record = self._ensure_latin1_safe(record, result)
                    result.record = record
                    result.success = True
                    result.fields_set = len(
                        [f for f in fields if str(getattr(f, "name", "")) in data]
                    )
                    self._validate_required_fields(schema, data, result)
                    return result
                if isinstance(record, str) and len(record) != self.record_length:
                    record = record[:self.record_length].ljust(self.record_length)
                    record = self._ensure_latin1_safe(record, result)
                    result.record = record
                    result.success = True
                    result.warnings.append(
                        f"format_record returnerade {len(record)} tecken "
                        f"(förväntade {self.record_length}) — justerat."
                    )
                    self._validate_required_fields(schema, data, result)
                    return result
        except Exception as exc:
            _log.debug("format_record() misslyckades: %s. Försöker manuell byggnad.", exc)
            result.warnings.append(f"format_record() misslyckades: {exc}")

        # Steg 2: Manuell fält-för-fält byggnad
        try:
            record = self._build_manually(schema, fields, data, result)
            result.record = record
            result.success = True
            self._validate_required_fields(schema, data, result)
            return result
        except Exception as exc:
            _log.exception("Manuell postbyggnad misslyckades.")
            result.errors.append(f"Manuell byggnad: {exc}")
            result.record = ALPHA_PAD_CHAR * self.record_length
            return result

    def _build_manually(
        self,
        schema: Any,
        fields: List[Any],
        data: Dict[str, Any],
        result: BuildResult,
    ) -> str:
        """
        Bygg post manuellt fält-för-fält från schema.

        Args:
            schema:  PostSpec
            fields:  Lista av FieldSpec
            data:    Fältdata
            result:  BuildResult att uppdatera

        Returns:
            Sträng med exakt record_length tecken
        """
        total_len = int(getattr(schema, "total_length", self.record_length) or self.record_length)
        buffer = [ALPHA_PAD_CHAR] * total_len

        fields_set = 0
        for fld in fields:
            try:
                name = str(getattr(fld, "name", "") or "")
                position = int(getattr(fld, "position", 0) or 0)
                length = int(getattr(fld, "length", 0) or 0)
                field_type = str(getattr(fld, "field_type", "ALPHANUMERIC") or "ALPHANUMERIC")

                if position <= 0 or length <= 0:
                    continue
                if position + length - 1 > total_len:
                    result.warnings.append(
                        f"Fält {name}: position {position}+{length} "
                        f"överstiger postlängd {total_len}."
                    )
                    continue

                # Hämta värde — prova variants av fältnamnet
                value = self._find_value(name, fld, data)

                # Formatera
                formatted = format_field_by_type(value, length, field_type)
                formatted = self._ensure_latin1_safe(formatted, result)

                # Skriv till buffer
                start = position - 1
                for i, ch in enumerate(formatted):
                    if start + i < total_len:
                        buffer[start + i] = ch

                if value is not None:
                    fields_set += 1

            except Exception as exc:
                _log.debug("Fält-byggnad misslyckades: %s", exc)
                result.warnings.append(f"Fält: {exc}")

        result.fields_set = fields_set

        record = "".join(buffer)
        if len(record) < self.record_length:
            record = record.ljust(self.record_length, ALPHA_PAD_CHAR)
        elif len(record) > self.record_length:
            record = record[:self.record_length]

        return record

    def _find_value(self, name: str, fld: Any, data: Dict[str, Any]) -> Any:
        """
        Hitta värde för ett fält i data.

        Sökordning:
            1. Exakt fältnamn
            2. Fältnamn i versaler
            3. Fältnamn i gemener
            4. Konstant-default från FieldSpec (default_value,
               default eller constant_value)

        Args:
            name: Fältnamn
            fld:  FieldSpec
            data: Fältdata

        Returns:
            Värde eller None
        """
        for key in (name, name.upper(), name.lower()):
            if key in data:
                return data[key]

        # Konstant-default
        try:
            ft = str(getattr(fld, "field_type", "") or "").upper()
            if ft in ("CONSTANT", "C", "KONST", "K"):
                for attr_name in ("default_value", "default", "constant_value"):
                    default = getattr(fld, attr_name, None)
                    if default is not None and default != "":
                        return default
        except Exception:
            pass

        return None

    def _validate_required_fields(
        self,
        schema: Any,
        data: Dict[str, Any],
        result: BuildResult,
    ) -> None:
        """
        Validera att obligatoriska fält har värden.

        Uppdaterar result.missing_required med saknade fält.

        Args:
            schema: PostSpec
            data:   Fältdata
            result: BuildResult att uppdatera
        """
        try:
            fields = list(getattr(schema, "fields", []) or [])
            for fld in fields:
                required = bool(
                    getattr(fld, "required", None)
                    or getattr(fld, "mandatory", None)
                )
                if not required:
                    continue

                name = str(getattr(fld, "name", "") or "")
                found = any(
                    key in data and data[key] not in (None, "")
                    for key in (name, name.upper(), name.lower())
                )
                # Fält med default/constant-värde räknas som satta även om
                # data saknar nyckeln (samma semantik som
                # models.FieldSpec.validate_value: mandatory + default -> OK)
                has_default = bool(
                    getattr(fld, "default_value", None)
                    or getattr(fld, "default", None)
                    or getattr(fld, "constant_value", None)
                )
                if not found and not has_default:
                    result.missing_required.append(name)

            if result.missing_required:
                result.warnings.append(
                    f"Obligatoriska fält saknar värde: "
                    f"{', '.join(result.missing_required)}"
                )
        except Exception as exc:
            _log.debug("Validering av obligatoriska fält misslyckades: %s", exc)

    def _ensure_latin1_safe(self, text: str, result: BuildResult) -> str:
        """
        Säkerställ att strängen är Latin-1 kompatibel.

        Loggar varning om tecken ersattes.

        Args:
            text:   Sträng att kontrollera
            result: BuildResult för varningsloggning

        Returns:
            Latin-1 säker sträng
        """
        safe = ensure_latin1(text)
        if safe != text:
            result.warnings.append("Ej Latin-1-kompatibla tecken ersattes med '?'.")
        return safe

    # ─────────────────────────────────────────────────────────────────
    # FALLBACK BUILDERS (om schema saknas)
    # ─────────────────────────────────────────────────────────────────

    def _build_identity_post_fallback(
        self,
        sequence_no: int,
        orgnummer: str,
        file_id: str,
        date_str: str,
    ) -> str:
        """
        Bygg minimal PT28 utan schema.

        Format:
            pos 1-4:   Löpnummer (numeriskt)
            pos 5-6:   Posttyp ("28")
            pos 7-16:  Organisationsnummer
            pos 17-22: FilID
            pos 23-28: Datum (YYMMDD)
            resten:    Mellanslag

        Args:
            sequence_no: Löpnummer
            orgnummer:   Organisationsnummer (10 siffror)
            file_id:     FilID (6 tecken)
            date_str:    Datum YYMMDD

        Returns:
            Sträng med exakt record_length tecken
        """
        org = re.sub(r"[^\d]", "", orgnummer).zfill(10)[:10]
        fid = str(file_id or "TS0001")[:6].ljust(6)
        dt = re.sub(r"[^\d]", "", date_str)[:6].ljust(6)
        seq = str(sequence_no).zfill(4)

        record = f"{seq}28{org}{fid}{dt}"
        return record.ljust(self.record_length, ALPHA_PAD_CHAR)[:self.record_length]

    def _build_vehicle_post_fallback(
        self,
        sequence_no: int,
        vin: str,
        model_year: str,
        color_code: str,
        owner_org: str,
    ) -> str:
        """
        Bygg minimal PT45 utan schema.

        Format:
            pos 1-4:   Löpnummer
            pos 5-6:   Posttyp ("45")
            pos 7-23:  VIN (17 tecken)
            pos 24-27: Modellår
            pos 28-33: Färgkod
            pos 34-43: Ägar-orgnr
            resten:    Mellanslag

        Args:
            sequence_no: Löpnummer
            vin:         VIN (17 tecken)
            model_year:  Modellår
            color_code:  Färgkod
            owner_org:   Ägarens organisationsnummer

        Returns:
            Sträng med exakt record_length tecken
        """
        seq = str(sequence_no).zfill(4)
        vin_clean = re.sub(r"[^A-Z0-9]", "", str(vin).upper())[:17].ljust(17)
        year = re.sub(r"[^\d]", "", str(model_year or ""))[:4].ljust(4)
        color = str(color_code or "")[:6].ljust(6)
        org = re.sub(r"[^\d]", "", str(owner_org or ""))[:10].ljust(10)

        record = f"{seq}45{vin_clean}{year}{color}{org}"
        return record.ljust(self.record_length, ALPHA_PAD_CHAR)[:self.record_length]

    def _build_end_post_fallback(
        self,
        sequence_no: int,
        total_posts: int,
    ) -> str:
        """
        Bygg minimal PT99 utan schema.

        Format:
            pos 1-4:   Löpnummer
            pos 5-6:   Posttyp ("99")
            pos 7-12:  Totalt antal poster
            resten:    Mellanslag

        Args:
            sequence_no: Löpnummer
            total_posts: Totalt antal poster i filen

        Returns:
            Sträng med exakt record_length tecken
        """
        seq = str(sequence_no).zfill(4)
        total = str(total_posts).zfill(6)
        record = f"{seq}99{total}"
        return record.ljust(self.record_length, ALPHA_PAD_CHAR)[:self.record_length]

    # ─────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────

    def build_identity_post(
        self,
        sequence_no: int = 1,
        orgnummer: str = "",
        file_id: str = "TS0001",
        date_str: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> BuildResult:
        """
        Bygg PT28 (identitetspost).

        Schema-driven om PT28-schema finns.
        Fallback till minimal PT28 annars.

        Args:
            sequence_no: Löpnummer (standard: 1)
            orgnummer:   Organisationsnummer
            file_id:     FilID (max 6 tecken)
            date_str:    Datum YYMMDD (None = dagens datum)
            extra_data:  Extra fältdata till schema

        Returns:
            BuildResult
        """
        result = BuildResult(post_type=POST_TYPE_IDENTITY, sequence_no=sequence_no)

        date_str = date_str or datetime.now().strftime("%y%m%d")
        org = re.sub(r"[^\d]", "", str(orgnummer or "")).zfill(10)
        fid = str(file_id or "TS0001")[:6]

        data: Dict[str, Any] = {
            "LOPNUMMER": sequence_no,
            "LÖPNUMMER": sequence_no,
            "POSTTYP": POST_TYPE_IDENTITY,
            "ORGNUMMER": org,
            "ORGNR": org,
            "ORGANISATIONSNUMMER": org,
            "FILIDENTITET": fid,
            "FIL_ID": fid,
            "FILE_ID": fid,
            "DATUM": date_str,
            "DATE": date_str,
        }
        if extra_data:
            data.update(extra_data)

        schema = self._get_schema(POST_TYPE_IDENTITY)
        if schema is not None:
            _log.debug("Bygger PT28 via schema.")
            return self._build_from_schema(schema, data, sequence_no, POST_TYPE_IDENTITY)

        _log.debug("Bygger PT28 via fallback (schema saknas).")
        result.record = self._build_identity_post_fallback(
            sequence_no, org, fid, date_str
        )
        result.success = True
        result.warnings.append("PT28 genererades via fallback — schema saknas.")
        return result

    def build_vehicle_post(
        self,
        sequence_no: int,
        vehicle_data: Dict[str, Any],
    ) -> BuildResult:
        """
        Bygg PT45 (fordonspost).

        Schema-driven om PT45-schema finns.
        Fallback till minimal PT45 annars.

        Nyckelnamn som söks (i prioritetsordning):
            VIN:         _vin, VIN, vin
            Modellår:     _model_year, MODELLYEAR, ÅRSMODELL
            Färgkod:     _color_ts, FARGKOD, COLOR_CODE
            Ägar-orgnr:  _owner, AGARE_ORG, OWNER_ORG

        Args:
            sequence_no:  Löpnummer
            vehicle_data: Dict med fordonsdata

        Returns:
            BuildResult
        """
        result = BuildResult(post_type=POST_TYPE_VEHICLE, sequence_no=sequence_no)

        vin = str(
            vehicle_data.get("_vin")
            or vehicle_data.get("VIN")
            or vehicle_data.get("vin")
            or ""
        ).upper().strip()

        model_year = str(
            vehicle_data.get("_model_year")
            or vehicle_data.get("MODELLYEAR")
            or vehicle_data.get("ÅRSMODELL")
            or vehicle_data.get("ARSMODELL")
            or vehicle_data.get("model_year")
            or ""
        ).strip()

        color_code = str(
            vehicle_data.get("_color_ts")
            or vehicle_data.get("FARGKOD")
            or vehicle_data.get("COLOR_CODE")
            or vehicle_data.get("color_code")
            or ""
        ).strip()

        owner_org = str(
            vehicle_data.get("_owner")
            or vehicle_data.get("AGARE_ORG")
            or vehicle_data.get("OWNER_ORG")
            or vehicle_data.get("owner_org")
            or ""
        ).strip()

        if not vin:
            result.errors.append("VIN saknas i fordonsdata.")
            result.record = ALPHA_PAD_CHAR * self.record_length
            return result

        data: Dict[str, Any] = {
            "LOPNUMMER": sequence_no,
            "LÖPNUMMER": sequence_no,
            "POSTTYP": POST_TYPE_VEHICLE,
            "VIN": vin,
            "UNDERSTÄLLSNUMMER": vin,
            "CHASSIS": vin,
            "MODELLÅR": model_year,
            "ARSMODELL": model_year,
            "MODEL_YEAR": model_year,
            "FARGKOD": color_code,
            "FÄRGKOD": color_code,
            "COLOR_CODE": color_code,
            "AGARE_ORG": owner_org,
            "OWNER_ORG": owner_org,
        }
        data.update(vehicle_data)

        schema = self._get_schema(POST_TYPE_VEHICLE)
        if schema is not None:
            _log.debug("Bygger PT45 via schema för VIN: %s", vin)
            return self._build_from_schema(schema, data, sequence_no, POST_TYPE_VEHICLE)

        _log.debug("Bygger PT45 via fallback för VIN: %s", vin)
        result.record = self._build_vehicle_post_fallback(
            sequence_no, vin, model_year, color_code, owner_org
        )
        result.success = True
        result.warnings.append("PT45 genererades via fallback — schema saknas.")
        return result

    def build_end_post(
        self,
        sequence_no: int,
        total_posts: int,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> BuildResult:
        """
        Bygg PT99 (slutpost).

        Schema-driven om PT99-schema finns.
        Fallback till minimal PT99 annars.

        Args:
            sequence_no: Löpnummer (= total antal poster)
            total_posts: Totalt antal poster i filen
            extra_data:  Extra fältdata till schema

        Returns:
            BuildResult
        """
        result = BuildResult(post_type=POST_TYPE_END, sequence_no=sequence_no)

        data: Dict[str, Any] = {
            "LOPNUMMER": sequence_no,
            "LÖPNUMMER": sequence_no,
            "POSTTYP": POST_TYPE_END,
            "ANTAL_POSTER": total_posts,
            "ANTAL": total_posts,
            "POST_COUNT": total_posts,
            "TOTAL": total_posts,
        }
        if extra_data:
            data.update(extra_data)

        schema = self._get_schema(POST_TYPE_END)
        if schema is not None:
            _log.debug("Bygger PT99 via schema.")
            return self._build_from_schema(schema, data, sequence_no, POST_TYPE_END)

        _log.debug("Bygger PT99 via fallback (schema saknas).")
        result.record = self._build_end_post_fallback(sequence_no, total_posts)
        result.success = True
        result.warnings.append("PT99 genererades via fallback — schema saknas.")
        return result

    def validate_record(self, record: str) -> Tuple[bool, List[str]]:
        """
        Validera en färdig TS-post.

        Kontrollerar:
            1. Exakt 2500 tecken
            2. Latin-1 kompatibel
            3. Inga radbrytningar inuti

        Args:
            record: TS-post to validera

        Returns:
            Tuple (is_valid, errors)
        """
        errors: List[str] = []

        if len(record) != self.record_length:
            errors.append(
                f"Fel radlängd: {len(record)} tecken "
                f"(förväntade {self.record_length})."
            )

        valid_latin1, invalid_chars = _latin1_check(record)
        if not valid_latin1:
            errors.append(
                f"Ej Latin-1 kompatibel. Ogiltiga tecken: "
                f"{', '.join(str(c) for c in invalid_chars[:10])}"
            )

        if "\n" in record or "\r" in record:
            errors.append("Posten innehåller radbrytningar.")

        return len(errors) == 0, errors

    def build_file(
        self,
        vehicles: List[Dict[str, Any]],
        orgnummer: str = "",
        file_id: str = "TS0001",
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Bygg komplett TS-fil (PT28 + PT45 × n + PT99).

        Args:
            vehicles:  Lista av fordonsdata-dicts
            orgnummer: Organisationsnummer för PT28
            file_id:   FilID för PT28

        Returns:
            Tuple (records, errors, warnings)
        """
        records: List[str] = []
        all_errors: List[str] = []
        all_warnings: List[str] = []

        # PT28
        pt28 = self.build_identity_post(
            sequence_no=1,
            orgnummer=orgnummer,
            file_id=file_id,
        )
        if not pt28.success:
            all_errors.extend(pt28.errors)
            return [], all_errors, all_warnings
        records.append(pt28.record)
        all_warnings.extend(pt28.warnings)

        # PT45 (ett per fordon)
        for idx, vehicle in enumerate(vehicles, start=2):
            pt45 = self.build_vehicle_post(
                sequence_no=idx,
                vehicle_data=vehicle,
            )
            if pt45.success:
                records.append(pt45.record)
                all_warnings.extend(pt45.warnings)
            else:
                vin = str(
                    vehicle.get("_vin") or vehicle.get("VIN") or f"rad {idx}"
                )
                all_errors.append(f"PT45 misslyckades för {vin}: {pt45.errors}")
                _log.warning("PT45 misslyckades för %s.", vin)

        # PT99
        total_posts = len(records) + 1
        pt99 = self.build_end_post(
            sequence_no=total_posts,
            total_posts=total_posts,
        )
        if not pt99.success:
            all_errors.extend(pt99.errors)
        else:
            records.append(pt99.record)
            all_warnings.extend(pt99.warnings)

        _log.info(
            "build_file: %d poster, %d fordon, %d fel, %d varningar.",
            len(records),
            len(vehicles),
            len(all_errors),
            len(all_warnings),
        )
        return records, all_errors, all_warnings

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        Hämta diagnostik.

        Returns:
            Dict med version, schema-status, copyright
        """
        return {
            "version": VERSION,
            "copyright": get_copyright_string(),
            "record_length": self.record_length,
            "encoding": self.encoding,
            "schema_cache": list(self._schema_cache.keys()),
            "pt28_schema": self._get_schema(POST_TYPE_IDENTITY) is not None,
            "pt45_schema": self._get_schema(POST_TYPE_VEHICLE) is not None,
            "pt99_schema": self._get_schema(POST_TYPE_END) is not None,
        }


# ══════════════════════════════════════════════════════════════════════
# SINGLETON / FACTORY
# ══════════════════════════════════════════════════════════════════════

default_builder: Optional[RecordBuilder] = None


def get_record_builder(app: Optional[Any] = None) -> RecordBuilder:
    """
    Hämta (eller skapa) standard RecordBuilder-instans.

    Args:
        app: Applikationsinstans (för plugin-access)

    Returns:
        RecordBuilder-instans
    """
    global default_builder
    if default_builder is None or app is not None:
        default_builder = RecordBuilder(app=app)
    return default_builder


def reset_default_builder() -> None:
    """Återställ standard-instansen (för testning)."""
    global default_builder
    default_builder = None


# ══════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════

__all__ = [
    "RecordBuilder",
    "BuildResult",
    "get_record_builder",
    "reset_default_builder",
    "get_copyright_string",
    "format_numeric_field",
    "format_alpha_field",
    "format_date_field",
    "format_constant_field",
    "format_field_by_type",
    "POST_TYPE_IDENTITY",
    "POST_TYPE_VEHICLE",
    "POST_TYPE_END",
    "TS_RECORD_LENGTH",
    "TS_ENCODING",
    "VERSION",
    "AUTHOR",
]
