# -*- coding: utf-8 -*-
# Fil: plugins/ts_schema_manager/models.py
"""
Datamodeller för TS-scheman v2.2.1

ANSVAR:
  - FieldSpec:  ett fält i en TS-post (position, längd, typ, validering)
  - PostSpec:   en hel posttyp (PT28, PT45, PT99 m.fl.)
  - SpecVersion: metadata om en specifikationsversion
  - FieldType:  enum för fälttyper (N, AN, D, K)
  - Latin-1 utilities (ensure_latin1, validate_latin1, sanitize_for_ts)
  - Factory-funktioner (create_empty_post_spec, create_field_for_gap)

IMPORTER:
  hashlib, json, logging, re, dataclasses, datetime, enum, typing

EXPORTERAR:
  VERSION, AUTHOR, get_copyright_string()
  TS_POST_LENGTH, TS_ENCODING, KNOWN_POST_TYPES, LATIN1_REPLACEMENTS
  ensure_latin1(), validate_latin1(), sanitize_for_ts()
  FieldType (Enum)
  FieldSpec (dataclass)
  PostSpec (dataclass)
  SpecVersion (dataclass)
  create_empty_post_spec(), create_field_for_gap(), create_minimal_spec()

ANVÄNDS AV:
  plugins/ts_schema_manager/version_manager.py (lazy)
  plugins/ts_schema_manager/schema_store.py (lazy)
  plugins/ts_schema_manager/schema_diff.py (lazy)
  plugins/ts_schema_manager/widget.py (direkt)
  plugins/ts_file_generator/ (indirekt via plugin.py)

FÖRÄNDRINGAR v2.2.1 (granskad — spec v1.6 förbättringsregeln):
  - FIX (BUGG #5-mönster): hårdkodad copyright-rad
    "# Copyright © 2025 ..." BORTTAGEN från header — copyright
    genereras dynamiskt via get_copyright_string().
  - logger -> _log (spec-konvention: module-level _log, ej logger).
  - FIX (korrekthet, DATA-FÖRLUST): create_empty_post_spec() skapade
    POSTTYP-fältet som "numeric" med constant_value. format_value()
    använde constant_value ENDAST när field_type == "constant" →
    POSTTYP formaterades till "00" när data saknades (fel posttyp i
    filen). Nu: (a) format_value() låter constant_value alltid vinna
    när satt (dess enda syfte), (b) POSTTYP skapas som field_type
    "constant" (semantiskt korrekt).
  - FIX (korrekthet): FieldSpec.validate_value() numerisk kontroll
    skärpt från "minst en siffra" till "endast siffror"
    (cleaned != sv). Tidigare passerade t.ex. "12a34" valideringen
    men formaterades tyst till "1234" — risk för tyst dataförändring.
    Nu konsistent med plugin.py FieldSpec.validate_value().
  - SpecVersion.from_dict(): kraschsäker via .get() med defaultar —
    klarar None och partiell data (inte bara extra nycklar).
  - Övrig logik OFÖRÄNDRAD (FieldType, kloner, gaps/overlaps,
    format_record, serialisering, factory-funktioner).

FÖRÄNDRINGAR v2.2.0:
  - Copyright dynamiskt via _get_copyright_year()
  - logger = _get_logger() (module-level, EJ self.logger)
  - FieldSpec: mandatory som primär, required som property-alias
  - FieldSpec.from_dict() hanterar 'required' och 'mandatory' (bakåtkomp.)
  - PostSpec.from_dict() robustare (None-säkra str/int/bool-konverteringar)
  - SpecVersion.from_dict() kraschsäker vid extra nycklar
  - find_gaps() / find_overlaps() returnerar detaljerade dicts
  - get_gaps() / get_overlaps() bakåtkompatibla wrappers
  - validate_latin1() returnerar Tuple[bool, List[str]] (EJ positions)
  - LATIN1_REPLACEMENTS utökad med fler unicode-ersättningar
  - __all__ komplett och uppdaterad

PUBLIKA FUNKTIONER (FieldSpec):
  clone(**overrides)            -> FieldSpec
  shift_position(delta)         -> FieldSpec
  overlaps_with(other)          -> bool
  contains_position(position)   -> bool
  format_value(value)           -> str  (exakt length tecken)
  validate_value(value)         -> Tuple[bool, str]
  to_dict()                     -> Dict
  from_dict(data) [classmethod] -> FieldSpec

PUBLIKA FUNKTIONER (PostSpec):
  clone(**overrides)            -> PostSpec
  add_field(field, validate)    -> PostSpec
  remove_field(name)            -> PostSpec
  update_field(name, **upd)     -> PostSpec
  get_field(name)               -> Optional[FieldSpec]
  get_field_at(position)        -> Optional[FieldSpec]
  get_fields_in_range(s, e)     -> List[FieldSpec]
  get_fields_by_type(type)      -> List[FieldSpec]
  get_required_fields()         -> List[FieldSpec]
  get_optional_fields()         -> List[FieldSpec]
  has_field(name)               -> bool
  find_fields(pattern)          -> List[FieldSpec]
  get_position_map()            -> Dict[int, str]
  find_gaps()                   -> List[Dict]        (detaljerad)
  find_overlaps()               -> List[Dict]        (detaljerad)
  get_gaps()                    -> List[Tuple]       (bakåtkompatibel)
  get_overlaps()                -> List[Tuple]       (bakåtkompatibel)
  format_record(data)           -> str  (exakt total_length tecken) ⭐
  validate_record(data)         -> Tuple[bool, List[str]]
  validate_structure()          -> List[str]
  merge_fields(other)           -> PostSpec
  to_dict()                     -> Dict
  from_dict(data) [classmethod] -> PostSpec
  to_json(indent)               -> str
  from_json(s) [classmethod]    -> PostSpec
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import (
    Any, Dict, Final, Iterator, List,
    Optional, Set, Tuple, Union,
)

# ──────────────────────────────────────────────────────────────────────────────
# COPYRIGHT & VERSION
# ──────────────────────────────────────────────────────────────────────────────

VERSION: Final[str] = "2.2.1"
AUTHOR: Final[str] = "Rickard Längkvist"


def _get_copyright_year() -> int:
    """Hämta aktuellt år för copyright (dynamiskt)."""
    return datetime.now().year


def get_copyright_string() -> str:
    """
    Generera copyright-sträng med dynamiskt år.

    Returns:
        Sträng på formen "Copyright © YYYY Rickard Längkvist"
    """
    return f"Copyright © {_get_copyright_year()} {AUTHOR}"


# ──────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL LOGGER
# ──────────────────────────────────────────────────────────────────────────────

def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("ts_schema_manager.models")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log: logging.Logger = _get_logger()

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

TS_POST_LENGTH: Final[int] = 2500
TS_ENCODING: Final[str] = "iso-8859-1"

KNOWN_POST_TYPES: Final[Dict[str, Dict[str, Any]]] = {
    "28": {
        "name": "Identitetspost",
        "description": "Filhuvud med organisationsnummer och filidentitet",
        "position": "first",
        "required": True,
    },
    "45": {
        "name": "Registreringspost",
        "description": "Fordonsdata för registrering",
        "position": "middle",
        "required": True,
    },
    "99": {
        "name": "Slutpost",
        "description": "Filavslut med kontrollsumma och antal poster",
        "position": "last",
        "required": True,
    },
}

LATIN1_REPLACEMENTS: Final[Dict[str, str]] = {
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a0": " ",
    "\u200b": "",
    "\u20ac": "EUR",
    "\u2122": "TM",
    "\u00ae": "(R)",
    "\u00b0": "o",
    "\u00b1": "+/-",
    "\u00d7": "x",
    "\u00f7": "/",
    "\u00e9": "\xe9",
    "\u00e8": "\xe8",
    "\u00fc": "\xfc",
    "\u00f1": "\xf1",
}

# ──────────────────────────────────────────────────────────────────────────────
# LATIN-1 UTILITIES
# ──────────────────────────────────────────────────────────────────────────────


def ensure_latin1(text: str, log_warnings: bool = False) -> str:
    """
    Säkerställ Latin-1-kompatibilitet.

    Ersätter kända unicode-tecken via LATIN1_REPLACEMENTS,
    sedan fallback med encode/decode errors='replace'.

    Args:
        text:         Text att konvertera
        log_warnings: Logga debug-meddelande vid ersättning

    Returns:
        Latin-1-kompatibel sträng
    """
    if not text:
        return ""

    result = text
    for uni_char, replacement in LATIN1_REPLACEMENTS.items():
        if uni_char in result:
            result = result.replace(uni_char, replacement)

    try:
        result.encode(TS_ENCODING)
        return result
    except UnicodeEncodeError:
        cleaned = (
            result.encode(TS_ENCODING, errors="replace").decode(TS_ENCODING)
        )
        if log_warnings and cleaned != result:
            _log.debug("Ersatte icke-Latin-1-tecken i text")
        return cleaned


def validate_latin1(text: str) -> Tuple[bool, List[str]]:
    """
    Validera Latin-1-kompatibilitet.

    Args:
        text: Text att validera

    Returns:
        Tuple (is_valid: bool, invalid_chars: List[str])
        Varje char i invalid_chars är unik.
    """
    if not text:
        return True, []

    invalid_chars: List[str] = []
    seen: Set[str] = set()

    for char in text:
        try:
            char.encode(TS_ENCODING)
        except UnicodeEncodeError:
            if char not in seen:
                invalid_chars.append(char)
                seen.add(char)

    return len(invalid_chars) == 0, invalid_chars


def sanitize_for_ts(text: str) -> str:
    """
    Rensa text för TS-kompatibilitet (alias för ensure_latin1).

    Args:
        text: Text att rensa

    Returns:
        Latin-1-kompatibel sträng
    """
    return ensure_latin1(text, log_warnings=False)


# ══════════════════════════════════════════════════════════════════════════════
# ENUM: FIELDTYPE
# ══════════════════════════════════════════════════════════════════════════════


class FieldType(str, Enum):
    """
    Fälttyper enligt TS-specifikation.

    Bestämmer formatering i format_value():
      NUMERIC:      högerställda, noll-paddade, endast siffror
      ALPHANUMERIC: vänsterställda, space-paddade
      DATE:         som NUMERIC (YYYYMMDD)
      CONSTANT:     fast värde via constant_value

    PROPERTIES:
      padding_char -> str  ("0" för N/D, " " för AN/K)
      alignment    -> str  ("right" för N/D, "left" för AN/K)
      code         -> str  ("N", "AN", "D", "K")

    KLASSMETOD:
      from_string(value) -> FieldType  (flexibel parsning)
    """

    NUMERIC = "numeric"
    ALPHANUMERIC = "alphanumeric"
    DATE = "date"
    CONSTANT = "constant"

    @property
    def padding_char(self) -> str:
        """Paddingtecken: '0' för numeriska, ' ' för övriga."""
        return "0" if self in (FieldType.NUMERIC, FieldType.DATE) else " "

    @property
    def alignment(self) -> str:
        """Justering: 'right' för numeriska, 'left' för övriga."""
        return (
            "right" if self in (FieldType.NUMERIC, FieldType.DATE) else "left"
        )

    @property
    def code(self) -> str:
        """Kort typkod för visning."""
        return {
            FieldType.NUMERIC: "N",
            FieldType.ALPHANUMERIC: "AN",
            FieldType.DATE: "D",
            FieldType.CONSTANT: "K",
        }.get(self, "AN")

    @classmethod
    def from_string(cls, value: str) -> "FieldType":
        """
        Parsa FieldType från sträng (flexibel, case-insensitive).

        Hanterar svenska och engelska varianter:
          N, num, numeric, numerisk, 9, tal, int, integer, heltal
          A, AN, alpha, text, string, str, sträng, char, x
          D, date, datum, datetime
          K, const, constant, konstant, fixed, literal, filler

        Args:
            value: Sträng att parsa

        Returns:
            FieldType (fallback: ALPHANUMERIC)
        """
        if not value:
            return cls.ALPHANUMERIC

        v = value.lower().strip()

        quick: Dict[str, "FieldType"] = {
            "numeric": cls.NUMERIC,
            "alphanumeric": cls.ALPHANUMERIC,
            "date": cls.DATE,
            "constant": cls.CONSTANT,
        }
        if v in quick:
            return quick[v]

        extended: Dict[str, "FieldType"] = {
            # Numerisk
            "n": cls.NUMERIC,
            "num": cls.NUMERIC,
            "numerisk": cls.NUMERIC,
            "number": cls.NUMERIC,
            "tal": cls.NUMERIC,
            "int": cls.NUMERIC,
            "integer": cls.NUMERIC,
            "heltal": cls.NUMERIC,
            "9": cls.NUMERIC,
            # Alfanumerisk
            "a": cls.ALPHANUMERIC,
            "an": cls.ALPHANUMERIC,
            "alpha": cls.ALPHANUMERIC,
            "alfabetisk": cls.ALPHANUMERIC,
            "alfanumerisk": cls.ALPHANUMERIC,
            "text": cls.ALPHANUMERIC,
            "string": cls.ALPHANUMERIC,
            "str": cls.ALPHANUMERIC,
            "sträng": cls.ALPHANUMERIC,
            "char": cls.ALPHANUMERIC,
            "varchar": cls.ALPHANUMERIC,
            "x": cls.ALPHANUMERIC,
            # Datum
            "d": cls.DATE,
            "datum": cls.DATE,
            "datetime": cls.DATE,
            # Konstant
            "k": cls.CONSTANT,
            "const": cls.CONSTANT,
            "konstant": cls.CONSTANT,
            "fixed": cls.CONSTANT,
            "literal": cls.CONSTANT,
            "filler": cls.CONSTANT,
        }
        return extended.get(v, cls.ALPHANUMERIC)


# ══════════════════════════════════════════════════════════════════════════════
# DATACLASS: FIELDSPEC
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class FieldSpec:
    """
    Specifikation för ett fält i en TS-post.

    Attributes:
        name:           Fältnamn (unikt inom posten)
        position:       Startposition (1-baserad, 1..2500)
        length:         Antal tecken
        field_type:     Typ som str (normaliseras via FieldType.from_string)
        mandatory:      Om fältet är obligatoriskt
        description:    Beskrivning
        valid_values:   Giltiga värden (tom = alla OK)
        default:        Standardvärde om data saknas
        source_mapping: Alternativt fältnamn i källdata
        constant_value: Fast värde för CONSTANT-fält

    PROPERTIES:
        end_position    -> int    (position + length - 1)
        required        -> bool   (alias för mandatory, bakåtkompatibilitet)
        field_type_enum -> FieldType
        type_code       -> str    ("N", "AN", "D", "K")
        position_range  -> Tuple[int, int]
    """

    name: str
    position: int
    length: int
    field_type: str = "alphanumeric"
    mandatory: bool = True
    description: str = ""
    valid_values: List[str] = field(default_factory=list)
    default: str = ""
    source_mapping: str = ""
    constant_value: str = ""

    def __post_init__(self) -> None:
        """Validera och normalisera efter initiering."""
        if self.position < 1:
            raise ValueError(
                f"Position måste vara >= 1, fick {self.position}"
            )
        if self.length < 1:
            raise ValueError(
                f"Längd måste vara >= 1, fick {self.length}"
            )
        # Normalisera field_type via FieldType
        if self.field_type:
            self.field_type = FieldType.from_string(self.field_type).value

    # ── PROPERTIES ──────────────────────────────────────────────────────────

    @property
    def end_position(self) -> int:
        """Slutposition (1-baserad, inklusive)."""
        return self.position + self.length - 1

    @property
    def required(self) -> bool:
        """Alias för mandatory (bakåtkompatibilitet med ts_spec_import)."""
        return self.mandatory

    @property
    def field_type_enum(self) -> FieldType:
        """Fälttyp som FieldType enum."""
        return FieldType.from_string(self.field_type)

    @property
    def type_code(self) -> str:
        """Kort typkod: N, AN, D eller K."""
        return self.field_type_enum.code

    @property
    def position_range(self) -> Tuple[int, int]:
        """Position som (start, end) tuple."""
        return (self.position, self.end_position)

    # ── FUNKTIONER 1–2 ──────────────────────────────────────────────────────

    def clone(self, **overrides: Any) -> "FieldSpec":
        """
        1. Skapa kopia med valfria modifieringar.

        Args:
            **overrides: Attribut att överskriva

        Returns:
            Ny FieldSpec-instans

        Exempel:
            ny = gammal.clone(position=100, length=20)
        """
        data = self.to_dict()
        data.update(overrides)
        return FieldSpec.from_dict(data)

    def shift_position(self, delta: int) -> "FieldSpec":
        """
        2. Flytta fält relativt (returnerar ny kopia).

        Args:
            delta: Antal positioner att flytta (+/-)

        Returns:
            Ny FieldSpec med uppdaterad position

        Raises:
            ValueError: Om ny position < 1
        """
        new_pos = self.position + delta
        if new_pos < 1:
            raise ValueError(
                f"Kan inte flytta till position {new_pos} (< 1)"
            )
        return self.clone(position=new_pos)

    # ── HJÄLPMETODER ────────────────────────────────────────────────────────

    def overlaps_with(self, other: "FieldSpec") -> bool:
        """
        Kontrollera om detta fält överlappar med annat fält.

        Args:
            other: Fält att kontrollera mot

        Returns:
            True om fälten delar minst en position
        """
        return not (
            self.end_position < other.position
            or other.end_position < self.position
        )

    def contains_position(self, position: int) -> bool:
        """
        Kontrollera om fältet täcker given position.

        Args:
            position: Position (1-baserad)

        Returns:
            True om position är inom fältets range
        """
        return self.position <= position <= self.end_position

    # ── FORMAT ──────────────────────────────────────────────────────────────

    def format_value(self, value: Any) -> str:
        """
        Formatera värde till exakt self.length Latin-1-tecken.

        Regler:
          NUMERIC/DATE: högerställt, noll-paddat, bara siffror
          ALPHANUMERIC/CONSTANT: vänsterställt, space-paddat
          CONSTANT: constant_value används om satt
          Alltid exakt self.length tecken, alltid Latin-1

        Args:
            value: Värde att formatera (None ger default/blank)

        Returns:
            Sträng med exakt self.length tecken
        """
        if value is None:
            value = self.default or ""

        if self.constant_value:
            value = self.constant_value

        str_value = ensure_latin1(str(value).strip())
        ft = self.field_type_enum

        if ft in (FieldType.NUMERIC, FieldType.DATE):
            str_value = re.sub(r"[^\d]", "", str_value)
            if len(str_value) > self.length:
                str_value = str_value[-self.length :]
            return str_value.rjust(self.length, "0")
        else:
            if len(str_value) > self.length:
                str_value = str_value[: self.length]
            return str_value.ljust(self.length, " ")

    # ── VALIDERING ──────────────────────────────────────────────────────────

    def validate_value(self, value: Any) -> Tuple[bool, str]:
        """
        Validera värde mot fältspecifikation.

        Kontrollerar:
          1. Obligatorisk (mandatory + saknar värde)
          2. Längd
          3. Numerisk typ (om field_type = numeric/date)
          4. Giltiga värden (valid_values)
          5. Latin-1-kompatibilitet

        Args:
            value: Värde att validera

        Returns:
            Tuple (is_valid: bool, error_message: str)
            error_message är tom sträng vid is_valid=True
        """
        if value is None or str(value).strip() == "":
            if self.mandatory and not self.default and not self.constant_value:
                return (
                    False,
                    f"Obligatoriskt fält '{self.name}' saknar värde",
                )
            return True, ""

        sv = str(value).strip()

        if len(sv) > self.length:
            return (
                False,
                f"'{self.name}' överskrider maxlängd {self.length} "
                f"(har {len(sv)})",
            )

        if self.field_type in ("numeric", "date"):
            cleaned = re.sub(r"[^\d]", "", sv)
            if cleaned != sv:
                return (
                    False,
                    f"'{self.name}' kräver numeriskt värde, fick '{sv}'",
                )

        if self.valid_values and sv not in self.valid_values:
            preview = ", ".join(self.valid_values[:3])
            if len(self.valid_values) > 3:
                preview += f" ... (+{len(self.valid_values) - 3})"
            return (
                False,
                f"Ogiltigt värde '{sv}' för '{self.name}'. "
                f"Giltiga: {preview}",
            )

        is_ok, invalid = validate_latin1(sv)
        if not is_ok:
            chars_preview = ", ".join(f"'{c}'" for c in invalid[:3])
            return (
                False,
                f"'{self.name}' innehåller ogiltiga tecken: {chars_preview}",
            )

        return True, ""

    # ── SERIALISERING ───────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary (använder 'mandatory' som nyckel)."""
        return {
            "name": self.name,
            "position": self.position,
            "length": self.length,
            "field_type": self.field_type,
            "mandatory": self.mandatory,
            "description": self.description,
            "valid_values": self.valid_values,
            "default": self.default,
            "source_mapping": self.source_mapping,
            "constant_value": self.constant_value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FieldSpec":
        """
        Skapa FieldSpec från dictionary. Kraschsäker.

        Hanterar 'required' som alias för 'mandatory'.
        Ignorerar okända nycklar.

        Args:
            data: Dictionary med fältdata

        Returns:
            FieldSpec instans
        """
        d = dict(data)

        # Hantera 'required' som alias
        if "required" in d and "mandatory" not in d:
            d["mandatory"] = d.pop("required")
        elif "required" in d:
            d.pop("required")

        valid: Final[Set[str]] = {
            "name", "position", "length", "field_type", "mandatory",
            "description", "valid_values", "default",
            "source_mapping", "constant_value",
        }
        filtered = {k: v for k, v in d.items() if k in valid}

        # Typkonverteringar
        for int_key in ("position", "length"):
            if int_key in filtered:
                filtered[int_key] = int(filtered[int_key])
        if "mandatory" in filtered:
            filtered["mandatory"] = bool(filtered["mandatory"])
        if "valid_values" in filtered and not isinstance(
            filtered["valid_values"], list
        ):
            filtered["valid_values"] = []

        return cls(**filtered)

    # ── DUNDER ──────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<FieldSpec {self.name} "
            f"pos={self.position}-{self.end_position} "
            f"len={self.length} type={self.type_code}>"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FieldSpec):
            return False
        return (
            self.name == other.name
            and self.position == other.position
            and self.length == other.length
            and self.field_type == other.field_type
        )

    def __hash__(self) -> int:
        return hash(
            (self.name, self.position, self.length, self.field_type)
        )


# ══════════════════════════════════════════════════════════════════════════════
# DATACLASS: POSTSPEC
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class PostSpec:
    """
    Specifikation för en hel posttyp (PT28, PT45, PT99 m.fl.).

    ⭐ format_record() är HUVUDMETODEN för postgenerering! ⭐

    Attributes:
        post_type:    Posttypsidentifierare ("28", "45", "99" m.fl.)
        name:         Beskrivande namn
        total_length: Total längd (normalt 2500)
        fields:       Lista med FieldSpec (sorteras på position)
        description:  Beskrivning
        version:      Versionsidentifierare
        source_file:  Källfil för specifikationen
        created_at:   ISO-timestamp
        checksum:     MD5-checksumma för fältdefinitionerna

    PROPERTIES:
        is_valid             -> bool
        calculated_length    -> int
        coverage             -> float  (0.0–1.0)
        field_count          -> int
        required_field_count -> int
        optional_field_count -> int
    """

    post_type: str
    name: str
    total_length: int
    fields: List[FieldSpec]
    description: str = ""
    version: str = ""
    source_file: str = ""
    created_at: str = ""
    checksum: str = ""

    def __post_init__(self) -> None:
        """Sortera fält och beräkna checksumma."""
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.fields = sorted(self.fields, key=lambda f: f.position)
        if not self.checksum:
            self.checksum = self._calculate_checksum()

    def _calculate_checksum(self) -> str:
        """Beräkna MD5-checksumma för fältdefinitionerna."""
        try:
            content = json.dumps(
                [f.to_dict() for f in self.fields], sort_keys=True
            )
            return hashlib.md5(content.encode()).hexdigest()[:12]
        except Exception:
            return ""

    # ── PROPERTIES ──────────────────────────────────────────────────────────

    @property
    def is_valid(self) -> bool:
        """Sant om post_type, fields och total_length är satta."""
        return bool(self.post_type and self.fields and self.total_length > 0)

    @property
    def calculated_length(self) -> int:
        """Sista fältets slutposition (faktisk beräknad längd)."""
        if not self.fields:
            return 0
        return max(f.end_position for f in self.fields)

    @property
    def coverage(self) -> float:
        """
        Andel av total_length som täcks av fält (0.0–1.0).

        Returns:
            Täckningsgrad som float
        """
        if self.total_length == 0:
            return 0.0
        covered: Set[int] = set()
        for f in self.fields:
            covered.update(range(f.position, f.end_position + 1))
        return len(covered) / self.total_length

    @property
    def field_count(self) -> int:
        """Totalt antal fält."""
        return len(self.fields)

    @property
    def required_field_count(self) -> int:
        """Antal obligatoriska fält."""
        return sum(1 for f in self.fields if f.mandatory)

    @property
    def optional_field_count(self) -> int:
        """Antal valfria fält."""
        return self.field_count - self.required_field_count

    # ── FÄLTÅTKOMST ─────────────────────────────────────────────────────────

    def get_field(self, name: str) -> Optional[FieldSpec]:
        """Hämta fält via namn (case-insensitive)."""
        name_upper = name.upper()
        for f in self.fields:
            if f.name.upper() == name_upper:
                return f
        return None

    def get_field_at(self, position: int) -> Optional[FieldSpec]:
        """Hämta fält vid given position (1-baserad)."""
        for f in self.fields:
            if f.contains_position(position):
                return f
        return None

    def get_fields_in_range(self, start: int, end: int) -> List[FieldSpec]:
        """Hämta fält som överlappar med intervall [start, end]."""
        return [
            f for f in self.fields
            if not (f.end_position < start or f.position > end)
        ]

    def get_fields_by_type(self, field_type: str) -> List[FieldSpec]:
        """Hämta fält av viss typ (normaliseras via FieldType.from_string)."""
        normalized = FieldType.from_string(field_type).value
        return [f for f in self.fields if f.field_type == normalized]

    def get_required_fields(self) -> List[FieldSpec]:
        """Lista obligatoriska fält."""
        return [f for f in self.fields if f.mandatory]

    def get_optional_fields(self) -> List[FieldSpec]:
        """Lista valfria fält."""
        return [f for f in self.fields if not f.mandatory]

    def has_field(self, name: str) -> bool:
        """Sant om fält med given namn finns."""
        return self.get_field(name) is not None

    def find_fields(self, pattern: str) -> List[FieldSpec]:
        """
        Sök fält med regex-mönster (case-insensitive).

        Faller tillbaka på enkel substring-sökning vid ogiltig regex.
        """
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            return [f for f in self.fields if regex.search(f.name)]
        except re.error:
            pl = pattern.lower()
            return [f for f in self.fields if pl in f.name.lower()]

    # ── FUNKTIONER 3–9 ──────────────────────────────────────────────────────

    def clone(self, **overrides: Any) -> "PostSpec":
        """
        3. Skapa kopia med valfria modifieringar.

        Args:
            **overrides: Attribut att överskriva

        Returns:
            Ny PostSpec-instans
        """
        data = self.to_dict()
        if "fields" not in overrides:
            data["fields"] = [f.clone() for f in self.fields]
        data.update(overrides)
        if "fields" in data and data["fields"]:
            if isinstance(data["fields"][0], dict):
                data["fields"] = [
                    FieldSpec.from_dict(fd) for fd in data["fields"]
                ]
        return PostSpec.from_dict(data)

    def add_field(
        self,
        field_spec: FieldSpec,
        validate: bool = True,
    ) -> "PostSpec":
        """
        4. Lägg till fält (returnerar ny PostSpec).

        Args:
            field_spec: Fält att lägga till
            validate:   Validera överlapp, bounds och duplikat

        Returns:
            Ny PostSpec med fältet tillagt

        Raises:
            ValueError: Om validering misslyckas
        """
        if validate:
            for existing in self.fields:
                if field_spec.overlaps_with(existing):
                    raise ValueError(
                        f"Fält '{field_spec.name}' överlappar "
                        f"'{existing.name}' vid position "
                        f"{max(field_spec.position, existing.position)}"
                    )
            if field_spec.end_position > self.total_length:
                raise ValueError(
                    f"Fält '{field_spec.name}' överskrider total längd "
                    f"({field_spec.end_position} > {self.total_length})"
                )
            if self.has_field(field_spec.name):
                raise ValueError(
                    f"Fält '{field_spec.name}' finns redan"
                )

        return self.clone(fields=self.fields + [field_spec])

    def remove_field(self, name: str) -> "PostSpec":
        """
        5. Ta bort fält (returnerar ny PostSpec).

        Args:
            name: Fältnamn

        Returns:
            Ny PostSpec utan fältet

        Raises:
            ValueError: Om fältet inte finns
        """
        new_fields = [
            f for f in self.fields if f.name.upper() != name.upper()
        ]
        if len(new_fields) == len(self.fields):
            raise ValueError(f"Fält '{name}' hittades inte")
        return self.clone(fields=new_fields)

    def update_field(self, name: str, **updates: Any) -> "PostSpec":
        """
        6. Uppdatera fält (returnerar ny PostSpec).

        Args:
            name:     Fältnamn att uppdatera
            **updates: Attribut att ändra

        Returns:
            Ny PostSpec med uppdaterat fält

        Raises:
            ValueError: Om fältet inte finns
        """
        new_fields: List[FieldSpec] = []
        found = False
        for f in self.fields:
            if f.name.upper() == name.upper():
                new_fields.append(f.clone(**updates))
                found = True
            else:
                new_fields.append(f.clone())
        if not found:
            raise ValueError(f"Fält '{name}' hittades inte")
        return self.clone(fields=new_fields)

    def get_position_map(self) -> Dict[int, str]:
        """
        7. Skapa karta position → fältnamn.

        Returns:
            Dict med position (int) → fältnamn (str)
            för alla täckta positioner.
        """
        pos_map: Dict[int, str] = {}
        for f in self.fields:
            for pos in range(f.position, f.end_position + 1):
                pos_map[pos] = f.name
        return pos_map

    def find_gaps(self) -> List[Dict[str, Any]]:
        """
        8. Hitta luckor i fältdefinitioner (detaljerad).

        Returns:
            Lista med dicts:
              start:        int
              end:          int
              length:       int
              before_field: Optional[str]  (fältnamn precis före)
              after_field:  Optional[str]  (fältnamn precis efter)
        """
        pos_map = self.get_position_map()
        covered = set(pos_map.keys())
        uncovered = sorted(
            set(range(1, self.total_length + 1)) - covered
        )

        if not uncovered:
            return []

        gaps: List[Dict[str, Any]] = []
        start = end = uncovered[0]

        def _add_gap(s: int, e: int) -> None:
            bf = self.get_field_at(s - 1)
            af = self.get_field_at(e + 1)
            gaps.append({
                "start": s,
                "end": e,
                "length": e - s + 1,
                "before_field": bf.name if bf else None,
                "after_field": af.name if af else None,
            })

        for pos in uncovered[1:]:
            if pos == end + 1:
                end = pos
            else:
                _add_gap(start, end)
                start = end = pos
        _add_gap(start, end)
        return gaps

    def find_overlaps(self) -> List[Dict[str, Any]]:
        """
        9. Hitta överlappande fält (detaljerad).

        Returns:
            Lista med dicts:
              field1:          str
              field2:          str
              overlap_start:   int
              overlap_end:     int
              overlap_length:  int
        """
        overlaps: List[Dict[str, Any]] = []
        for i, f1 in enumerate(self.fields):
            for f2 in self.fields[i + 1:]:
                if f1.overlaps_with(f2):
                    os = max(f1.position, f2.position)
                    oe = min(f1.end_position, f2.end_position)
                    overlaps.append({
                        "field1": f1.name,
                        "field2": f2.name,
                        "overlap_start": os,
                        "overlap_end": oe,
                        "overlap_length": oe - os + 1,
                    })
        return overlaps

    # ── BAKÅTKOMPATIBLA WRAPPERS ─────────────────────────────────────────────

    def get_gaps(self) -> List[Tuple[int, int]]:
        """
        Hitta luckor – bakåtkompatibel wrapper.

        Returns:
            Lista med (start, end) tupler
        """
        return [(g["start"], g["end"]) for g in self.find_gaps()]

    def get_overlaps(
        self,
    ) -> List[Tuple["FieldSpec", "FieldSpec", int]]:
        """
        Hitta överlapp – bakåtkompatibel wrapper.

        Returns:
            Lista med (field1, field2, overlap_start) tupler
        """
        result: List[Tuple[FieldSpec, FieldSpec, int]] = []
        for ov in self.find_overlaps():
            f1 = self.get_field(ov["field1"])
            f2 = self.get_field(ov["field2"])
            if f1 and f2:
                result.append((f1, f2, ov["overlap_start"]))
        return result

    # ── FORMAT ──────────────────────────────────────────────────────────────

    def format_record(self, data: Dict[str, Any]) -> str:
        """
        ⭐ Formatera en hel post till exakt total_length tecken. ⭐

        Regler:
          - Output är EXAKT total_length tecken (normalt 2500)
          - Varje fält formateras via FieldSpec.format_value()
          - Odefinierade positioner fylls med space
          - Output är Latin-1-kompatibel
          - source_mapping används som fallback för fältnamn

        Args:
            data: Dict med fältnamn → värde

        Returns:
            Sträng med EXAKT total_length tecken
        """
        buffer = [" "] * self.total_length

        for fs in self.fields:
            value = data.get(fs.name)
            if value is None and fs.source_mapping:
                value = data.get(fs.source_mapping)

            formatted = fs.format_value(value)

            if len(formatted) != fs.length:
                formatted = formatted[: fs.length].ljust(fs.length)

            start_idx = fs.position - 1
            for i, char in enumerate(formatted):
                if 0 <= start_idx + i < self.total_length:
                    buffer[start_idx + i] = char

        result = "".join(buffer)
        if len(result) != self.total_length:
            result = result[: self.total_length].ljust(self.total_length)

        return ensure_latin1(result, log_warnings=False)

    # ── VALIDERING ──────────────────────────────────────────────────────────

    def validate_record(
        self, data: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        Validera data mot schemat.

        Args:
            data: Dict med fältnamn → värde

        Returns:
            Tuple (is_valid: bool, errors: List[str])
        """
        errors: List[str] = []
        for fs in self.fields:
            value = data.get(fs.name)
            if value is None and fs.source_mapping:
                value = data.get(fs.source_mapping)
            is_valid, error = fs.validate_value(value)
            if not is_valid:
                errors.append(error)
        return len(errors) == 0, errors

    def validate_structure(self) -> List[str]:
        """
        Validera specifikationens struktur.

        Kontrollerar: post_type, fields, överlapp, bounds.
        Returnerar varningar om luckor (ej fel).

        Returns:
            Lista med felmeddelanden (tom = OK)
        """
        errors: List[str] = []

        if not self.post_type:
            errors.append("Posttyp saknas")
        if not self.fields:
            errors.append("Inga fält definierade")
            return errors

        for ov in self.find_overlaps():
            errors.append(
                f"Överlapp vid {ov['overlap_start']}-{ov['overlap_end']}: "
                f"'{ov['field1']}' och '{ov['field2']}'"
            )

        for f in self.fields:
            if f.position < 1:
                errors.append(
                    f"Fält '{f.name}' har ogiltig position {f.position} (< 1)"
                )
            if f.end_position > self.total_length:
                errors.append(
                    f"Fält '{f.name}' överskrider total längd "
                    f"({f.end_position} > {self.total_length})"
                )

        gaps = self.find_gaps()
        if gaps:
            total_gap = sum(g["length"] for g in gaps)
            cov_pct = (1 - total_gap / self.total_length) * 100
            if cov_pct < 50:
                errors.append(f"[VARNING] Låg täckning: {cov_pct:.1f}%")
            gap_strs = [f"{g['start']}-{g['end']}" for g in gaps[:5]]
            suffix = (
                f" ... (+{len(gaps) - 5} fler)" if len(gaps) > 5 else ""
            )
            errors.append(
                f"[INFO] Odefinierade positioner: "
                f"{', '.join(gap_strs)}{suffix}"
            )

        return errors

    def merge_fields(self, other: "PostSpec") -> "PostSpec":
        """
        Slå ihop fält från annat schema.

        Fält från 'other' överskriver vid namnkollision.

        Args:
            other: Schema att merga in

        Returns:
            Ny PostSpec med sammanslagna fält
        """
        field_map = {f.name: f for f in self.fields}
        for f in other.fields:
            field_map[f.name] = f
        merged = sorted(field_map.values(), key=lambda x: x.position)
        return self.clone(
            fields=merged,
            version=other.version or self.version,
            source_file=other.source_file or self.source_file,
        )

    # ── SERIALISERING ───────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "post_type": self.post_type,
            "name": self.name,
            "total_length": self.total_length,
            "fields": [f.to_dict() for f in self.fields],
            "description": self.description,
            "version": self.version,
            "source_file": self.source_file,
            "created_at": self.created_at,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostSpec":
        """
        Skapa PostSpec från dictionary. Kraschsäker.

        Args:
            data: Dictionary med spec-data

        Returns:
            PostSpec instans
        """
        raw_fields = data.get("fields", [])
        fields: List[FieldSpec] = []
        for fd in raw_fields:
            try:
                if isinstance(fd, dict):
                    fields.append(FieldSpec.from_dict(fd))
                elif isinstance(fd, FieldSpec):
                    fields.append(fd)
            except Exception as exc:
                _log.warning("Kunde inte ladda fält: %s", exc)

        return cls(
            post_type=str(data.get("post_type", "")),
            name=str(data.get("name", "")),
            total_length=int(data.get("total_length", TS_POST_LENGTH)),
            fields=fields,
            description=str(data.get("description", "")),
            version=str(data.get("version", "")),
            source_file=str(data.get("source_file", "")),
            created_at=str(data.get("created_at", "")),
            checksum=str(data.get("checksum", "")),
        )

    def to_json(self, indent: int = 2) -> str:
        """Serialisera till JSON-sträng."""
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=indent
        )

    @classmethod
    def from_json(cls, json_str: str) -> "PostSpec":
        """Skapa PostSpec från JSON-sträng."""
        return cls.from_dict(json.loads(json_str))

    # ── DUNDER ──────────────────────────────────────────────────────────────

    def __iter__(self) -> Iterator[FieldSpec]:
        """Iterera över fält."""
        return iter(self.fields)

    def __len__(self) -> int:
        """Antal fält."""
        return len(self.fields)

    def __getitem__(
        self, key: Union[str, int]
    ) -> Optional[FieldSpec]:
        """Hämta fält via namn (str) eller index (int)."""
        if isinstance(key, int):
            return self.fields[key] if 0 <= key < len(self.fields) else None
        return self.get_field(key)

    def __contains__(self, name: object) -> bool:
        """Sant om fält med given namn finns."""
        if not isinstance(name, str):
            return False
        return self.has_field(name)

    def __repr__(self) -> str:
        return (
            f"<PostSpec PT{self.post_type} '{self.name}' "
            f"fields={len(self.fields)} "
            f"coverage={self.coverage:.1%} "
            f"v={self.version}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# DATACLASS: SPECVERSION
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class SpecVersion:
    """
    Metadata om en specifikationsversion.

    Attributes:
        version:     Versionsidentifierare
        created_at:  ISO-timestamp
        source_file: Källfil
        post_types:  Lista med posttyper
        description: Beskrivning
        is_active:   Om detta är aktiv version

    PROPERTIES:
        age_days        -> int
        post_type_count -> int
    """

    version: str
    created_at: str
    source_file: str
    post_types: List[str]
    description: str = ""
    is_active: bool = False

    @property
    def age_days(self) -> int:
        """Dagar sedan skapande. -1 om datum ej kan parsas."""
        try:
            return (datetime.now() - datetime.fromisoformat(self.created_at)).days
        except Exception:
            return -1

    @property
    def post_type_count(self) -> int:
        """Antal posttyper."""
        return len(self.post_types)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpecVersion":
        """
        Skapa SpecVersion från dictionary. Kraschsäker.

        Hanterar None/partiell data via .get() med defaultar och
        ignorerar extra nycklar.

        Args:
            data: Dictionary med versionsdata

        Returns:
            SpecVersion instans
        """
        data = data or {}
        return cls(
            version=str(data.get("version", "")),
            created_at=str(data.get("created_at", "")),
            source_file=str(data.get("source_file", "")),
            post_types=list(data.get("post_types", [])),
            description=str(data.get("description", "")),
            is_active=bool(data.get("is_active", False)),
        )

    def __repr__(self) -> str:
        active = " [AKTIV]" if self.is_active else ""
        return (
            f"<SpecVersion {self.version} "
            f"({len(self.post_types)} typer){active}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# FACTORY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════


def create_empty_post_spec(
    post_type: str,
    name: Optional[str] = None,
    total_length: int = TS_POST_LENGTH,
    version: str = "",
) -> PostSpec:
    """
    10. Skapa minimalt schema för en posttyp.

    Skapar ett schema med bara POSTTYP-fältet (position 1-2).
    Information om kända posttyper (28, 45, 99) hämtas från
    KNOWN_POST_TYPES.

    Args:
        post_type:    Posttyp (t.ex. "45", "28", "99")
        name:         Namn (auto från KNOWN_POST_TYPES om None)
        total_length: Total längd (default 2500)
        version:      Versionsidentifierare

    Returns:
        PostSpec med bara POSTTYP-fält
    """
    info = KNOWN_POST_TYPES.get(post_type, {})
    return PostSpec(
        post_type=post_type,
        name=name or info.get("name", f"Posttyp {post_type}"),
        total_length=total_length,
        fields=[
            FieldSpec(
                name="POSTTYP",
                position=1,
                length=2,
                field_type="constant",
                mandatory=True,
                constant_value=post_type,
                description="Posttypsidentifierare",
            )
        ],
        description=info.get("description", ""),
        version=version,
    )


def create_field_for_gap(
    gap: Dict[str, Any],
    name: Optional[str] = None,
    field_type: str = "alphanumeric",
    mandatory: bool = False,
) -> FieldSpec:
    """
    Skapa FieldSpec som fyller en lucka (från find_gaps()).

    Args:
        gap:        Gap-dict från PostSpec.find_gaps()
        name:       Fältnamn (auto om None)
        field_type: Fälttyp
        mandatory:  Om fältet är obligatoriskt

    Returns:
        FieldSpec som täcker luckan exakt
    """
    auto_name = name or f"FILLER_{gap['start']}_{gap['end']}"
    return FieldSpec(
        name=auto_name,
        position=gap["start"],
        length=gap["length"],
        field_type=field_type,
        mandatory=mandatory,
        description=(
            f"Auto-genererat filler för lucka "
            f"{gap['start']}-{gap['end']}"
        ),
    )


def create_minimal_spec(post_type: str) -> PostSpec:
    """
    Skapa minimalt schema (alias för create_empty_post_spec).

    Args:
        post_type: Posttyp

    Returns:
        Minimalt PostSpec
    """
    return create_empty_post_spec(post_type)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
    "TS_POST_LENGTH",
    "TS_ENCODING",
    "KNOWN_POST_TYPES",
    "LATIN1_REPLACEMENTS",
    "ensure_latin1",
    "validate_latin1",
    "sanitize_for_ts",
    "FieldType",
    "FieldSpec",
    "PostSpec",
    "SpecVersion",
    "create_empty_post_spec",
    "create_field_for_gap",
    "create_minimal_spec",
]