# -*- coding: utf-8 -*-
# Fil: plugins/ts_schema_manager/constants.py
"""
Konstanter och hjälpfunktioner för TS-schemahantering v2.2.1

ANSVAR:
  - Grundkonstanter (TS_POST_LENGTH, TS_ENCODING m.fl.)
  - Kända posttyper med metadata (dynamisk registrering)
  - Typmappningar (TS_TYPE_MAPPING, FIELD_TYPE_CODES m.fl.)
  - Schema-defaults och fältregler
  - Kolumnmönster för Excel-import
  - Event-namn (SchemaEventNames)
  - 20 hjälpfunktioner för dynamisk hantering
  - Latin-1 sanering och validering

IMPORTER:
  re, datetime, typing (Any, Callable, Dict, Final, FrozenSet,
                         List, Optional, Set, Tuple)

EXPORTERAR:
  VERSION, AUTHOR, get_copyright_string()
  TS_POST_LENGTH, TS_ENCODING, TS_ENCODING_ALIASES
  SPEC_DIR_NAME, BACKUP_DIR_NAME, ACTIVE_VERSION_KEY, CACHE_TTL_SECONDS
  LATIN1_REPLACEMENTS
  KNOWN_POST_TYPES, get_known_post_types()
  TS_TYPE_MAPPING, FIELD_TYPE_CODES, FIELD_TYPE_FROM_CODE, FIELD_PADDING_RULES
  SCHEMA_DEFAULTS, TYPICALLY_REQUIRED_FIELDS, TYPICALLY_CONSTANT_FIELDS
  COLUMN_PATTERNS
  SchemaEventNames
  (20 hjälpfunktioner – se __all__)

ANVÄNDS AV:
  plugins/ts_schema_manager/plugin.py
  plugins/ts_schema_manager/models.py
  plugins/ts_schema_manager/version_manager.py
  plugins/ts_schema_manager/schema_store.py
  plugins/ts_schema_manager/widget.py (TS_POST_LENGTH, validate_latin1)
  plugins/ts_spec_import/ (indirekt via plugin.py)
  plugins/ts_file_generator/ (indirekt via plugin.py)

FÖRÄNDRINGAR v2.2.1 (granskad — spec v1.6 förbättringsregeln):
  - FIX (korrekthet, DATA-FÖRLUST): ensure_latin1() tog BORT ogiltiga
    tecken (replacement=""). I fasta TS-format förskjuter borttagning
    alla efterföljande positioner — korrupt post. Nu ersätts okända
    tecken med "?" — konsistent med models.py ensure_latin1()
    (encode/decode errors='replace').
  - get_known_post_types() returnerar nu riktiga kopior per posttyp
    (dict(info)) så att "read-only" löftet stämmer — mutering av
    returnerad kopia påverkar ej globala registret.
  - get_copyright_string() och felmeddelanden (% → f-string) för
    enhetlighet med övriga moduler.
  - Fil-huvud normaliserat: coding-rad före Fil-rad (spec v1.11,
    KRAV 58 — samma mönster som plugin.py/models.py).
  - OBSERVATION (EJ ändrad, inväntar beslut): KNOWN_POST_TYPES finns
    i TVÅ varianter — statisk Final-dict i models.py och dynamisk
    registreringsbar i constants.py. Medveten dubbeldefinition;
    synkroniseras manuellt. Konsolidering (models.py importerar från
    constants.py) kräver ny leverans av models.py.

FÖRÄNDRINGAR v2.2.0:
  - Copyright dynamiskt via _get_copyright_year()
  - validate_latin1() returnerar Tuple[bool, List[str]]
    (EJ List[int] + List[str] – matchar models.py)
  - LATIN1_REPLACEMENTS utökad med 40+ unicode-ersättningar
  - register_post_type() nu kraschsäker i listener-loop
  - get_encoding_errors() returnerar suggestion från LATIN1_REPLACEMENTS
  - add_post_type_listener() / remove_post_type_listener() kraschsäkra
  - get_constants_info() inkluderar nu alla nycklar
  - __all__ komplett och sorterad

FUNKTIONER 1–10 (CORE):
  1.  get_post_type_info(post_type)         -> Optional[Dict]
  2.  is_known_post_type(post_type)         -> bool
  3.  get_post_type_position(post_type)     -> str
  4.  normalize_field_type(type_str)        -> str
  5.  get_field_type_code(field_type)       -> str
  6.  register_post_type(...)               -> bool
  7.  unregister_post_type(post_type)       -> bool
  8.  get_all_post_types()                  -> List[Dict]
  9.  validate_post_length(length)          -> Tuple[bool, str]
  10. get_encoding_errors(text)             -> List[Dict]

FUNKTIONER 11–20 (ADVANCED):
  11. get_schema_defaults()                 -> Dict
  12. sanitize_for_encoding(text, repl)     -> str
  13. ensure_latin1(text)                   -> str
  14. validate_latin1(text)                 -> Tuple[bool, List[str]]
  15. get_post_types_by_position(position)  -> List[str]
  16. get_required_post_types()             -> List[str]
  17. get_padding_rule(field_type)          -> Dict
  18. is_typically_required(field_name)     -> bool
  19. is_typically_constant(field_name)     -> bool
  20. add_post_type_listener(callback)      -> bool
      remove_post_type_listener(callback)   -> bool  (bonus)

COLUMN DETECTION:
  detect_column_type(column_name)          -> Optional[str]
  get_column_patterns()                    -> Dict[str, List[str]]

DIAGNOSTIC:
  get_constants_info()                     -> Dict
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import (
    Any, Callable, Dict, Final, FrozenSet,
    List, Optional, Set, Tuple,
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
# CORE CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

TS_POST_LENGTH: Final[int] = 2500
TS_ENCODING: Final[str] = "iso-8859-1"

TS_ENCODING_ALIASES: Final[FrozenSet[str]] = frozenset({
    "iso-8859-1",
    "iso_8859_1",
    "latin-1",
    "latin1",
    "l1",
    "8859",
    "cp819",
    "ibm819",
})

SPEC_DIR_NAME: Final[str] = "ts_specs"
BACKUP_DIR_NAME: Final[str] = "backup"
ACTIVE_VERSION_KEY: Final[str] = "ts_schema_active_version"
CACHE_TTL_SECONDS: Final[int] = 300


# ──────────────────────────────────────────────────────────────────────────────
# LATIN-1 REPLACEMENTS
# ──────────────────────────────────────────────────────────────────────────────

LATIN1_REPLACEMENTS: Final[Dict[str, str]] = {
    # Typografiska citattecken
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": ",",
    "\u201b": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u2039": "<",
    "\u203a": ">",
    "\u00ab": '"',
    "\u00bb": '"',
    # Streck och bindestreck
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
    # Mellanslag och osynliga
    "\u00a0": " ",
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\u2060": "",
    "\ufeff": "",
    "\u00ad": "",
    # Punkter och ellips
    "\u2026": "...",
    "\u2022": "*",
    "\u2023": ">",
    "\u2043": "-",
    "\u25aa": "*",
    "\u25ab": "*",
    # Symboler
    "\u20ac": "EUR",
    "\u2122": "TM",
    "\u00ae": "(R)",
    "\u00a9": "(C)",
    "\u2117": "(P)",
    # Matematiska symboler
    "\u00b0": "o",
    "\u00b1": "+/-",
    "\u00d7": "x",
    "\u00f7": "/",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2260": "!=",
    "\u221e": "INF",
    # Pilar
    "\u2190": "<-",
    "\u2192": "->",
    "\u2194": "<->",
    "\u21d2": "=>",
    # Bråktal
    "\u00bc": "1/4",
    "\u00bd": "1/2",
    "\u00be": "3/4",
    # Ordningstal
    "\u00aa": "a",
    "\u00ba": "o",
    # Övriga
    "\u2020": "+",
    "\u2021": "++",
    "\u00a6": "|",
    "\u00a7": "S",
    "\u00b6": "P",
}


# ──────────────────────────────────────────────────────────────────────────────
# POST TYPES — DYNAMISK REGISTRERING
# ──────────────────────────────────────────────────────────────────────────────

# Mutable dict — register_post_type() kan lägga till nya posttyper
_KNOWN_POST_TYPES: Dict[str, Dict[str, Any]] = {
    "28": {
        "name": "Identitetspost",
        "description": "Filhuvud med organisationsnummer och filidentitet",
        "required": True,
        "position": "first",
        "count": "one",
        "min_count": 1,
        "max_count": 1,
        "order": 0,
        "source": "builtin",
    },
    "45": {
        "name": "Registreringspost",
        "description": "Fordonsdata för registrering",
        "required": True,
        "position": "middle",
        "count": "many",
        "min_count": 1,
        "max_count": None,
        "order": 50,
        "source": "builtin",
    },
    "99": {
        "name": "Slutpost",
        "description": "Filavslut med kontrollsumma och antal poster",
        "required": True,
        "position": "last",
        "count": "one",
        "min_count": 1,
        "max_count": 1,
        "order": 100,
        "source": "builtin",
    },
}

# Exponeras som KNOWN_POST_TYPES för bakåtkompatibilitet
KNOWN_POST_TYPES = _KNOWN_POST_TYPES

# Callbacks vid posttyp-ändringar
_POST_TYPE_LISTENERS: List[Callable[[str, str, Dict[str, Any]], None]] = []


def get_known_post_types() -> Dict[str, Dict[str, Any]]:
    """
    Hämta alla kända posttyper som read-only kopia.

    Returnerar kopior per posttyp — mutering av resultatet
    påverkar inte det globala registret.

    Returns:
        Dict med posttypskod -> metadata-dict (kopior)
    """
    return {pt: dict(info) for pt, info in _KNOWN_POST_TYPES.items()}


# ──────────────────────────────────────────────────────────────────────────────
# TYPE MAPPINGS
# ──────────────────────────────────────────────────────────────────────────────

TS_TYPE_MAPPING: Final[Dict[str, str]] = {
    # Numerisk
    "n": "numeric",
    "num": "numeric",
    "numeric": "numeric",
    "numerisk": "numeric",
    "siffror": "numeric",
    "tal": "numeric",
    "number": "numeric",
    "int": "numeric",
    "integer": "numeric",
    "heltal": "numeric",
    "9": "numeric",
    "9(n)": "numeric",
    "pic 9": "numeric",
    # Alfanumerisk
    "a": "alphanumeric",
    "an": "alphanumeric",
    "alpha": "alphanumeric",
    "alfabetisk": "alphanumeric",
    "alfanumerisk": "alphanumeric",
    "alphanumeric": "alphanumeric",
    "text": "alphanumeric",
    "string": "alphanumeric",
    "str": "alphanumeric",
    "sträng": "alphanumeric",
    "char": "alphanumeric",
    "character": "alphanumeric",
    "varchar": "alphanumeric",
    "x": "alphanumeric",
    "x(n)": "alphanumeric",
    "pic x": "alphanumeric",
    # Datum
    "d": "date",
    "date": "date",
    "datum": "date",
    "datetime": "date",
    "datumtid": "date",
    "yyyymmdd": "date",
    "åååå-mm-dd": "date",
    # Konstant
    "k": "constant",
    "konstant": "constant",
    "const": "constant",
    "fast": "constant",
    "fixed": "constant",
    "literal": "constant",
    "filler": "constant",
}

FIELD_TYPE_CODES: Final[Dict[str, str]] = {
    "numeric": "N",
    "alphanumeric": "AN",
    "date": "D",
    "constant": "K",
}

FIELD_TYPE_FROM_CODE: Final[Dict[str, str]] = {
    "N": "numeric",
    "AN": "alphanumeric",
    "A": "alphanumeric",
    "D": "date",
    "K": "constant",
}

FIELD_PADDING_RULES: Final[Dict[str, Dict[str, Any]]] = {
    "numeric": {
        "pad_char": "0",
        "justify": "right",
        "strip_non_digits": True,
    },
    "alphanumeric": {
        "pad_char": " ",
        "justify": "left",
        "strip_non_digits": False,
    },
    "date": {
        "pad_char": "0",
        "justify": "right",
        "strip_non_digits": True,
    },
    "constant": {
        "pad_char": " ",
        "justify": "left",
        "strip_non_digits": False,
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# SCHEMA DEFAULTS
# ──────────────────────────────────────────────────────────────────────────────

SCHEMA_DEFAULTS: Final[Dict[str, Any]] = {
    "total_length": TS_POST_LENGTH,
    "encoding": TS_ENCODING,
    "field_type": "alphanumeric",
    "required": True,
    "mandatory": True,
    "position": 1,
    "length": 1,
    "description": "",
    "valid_values": [],
    "default": "",
    "source_mapping": "",
    "constant_value": "",
}

TYPICALLY_REQUIRED_FIELDS: Final[FrozenSet[str]] = frozenset({
    "POSTTYP",
    "PT",
    "VIN",
    "CHASSINR",
    "CHASSI",
    "ORGANISATIONSNUMMER",
    "ORGNR",
    "FILID",
    "FILIDENTITET",
    "ANTALPOSTER",
    "ANTAL_POSTER",
})

TYPICALLY_CONSTANT_FIELDS: Final[FrozenSet[str]] = frozenset({
    "POSTTYP",
    "PT",
    "FILLER",
    "BLANK",
    "RESERV",
    "RESERVED",
})


# ──────────────────────────────────────────────────────────────────────────────
# COLUMN PATTERNS FOR EXCEL IMPORT
# ──────────────────────────────────────────────────────────────────────────────

COLUMN_PATTERNS: Final[Dict[str, List[str]]] = {
    "name": [
        r"^(fält)?namn",
        r"^field\s*name",
        r"^name$",
        r"^fält$",
        r"^field$",
        r"^benämning",
        r"^beskrivning.*namn",
    ],
    "position": [
        r"^(från\s*)?pos(ition)?",
        r"^start",
        r"^from",
        r"^fr\.?o\.?m",
        r"^kolumn",
        r"^column",
    ],
    "length": [
        r"^längd",
        r"^length",
        r"^len$",
        r"^antal\s*(tecken|tkn)?",
        r"^size",
        r"^storlek",
    ],
    "type": [
        r"^typ",
        r"^type",
        r"^format",
        r"^datatyp",
        r"^data\s*type",
    ],
    "mandatory": [
        r"^oblig",
        r"^mandatory",
        r"^required",
        r"^krävs",
        r"^måste",
        r"^must",
        r"^o/f",
    ],
    "description": [
        r"^beskrivning",
        r"^description",
        r"^desc$",
        r"^kommentar",
        r"^comment",
        r"^anmärkning",
        r"^info",
    ],
    "valid_values": [
        r"^(giltiga\s*)?värden",
        r"^valid\s*values",
        r"^allowed",
        r"^tillåtna",
        r"^enum",
        r"^options",
    ],
    "default": [
        r"^default",
        r"^standard",
        r"^(standard)?värde",
        r"^default\s*value",
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# EVENT NAMES
# ──────────────────────────────────────────────────────────────────────────────


class SchemaEventNames:
    """
    Konstanter för schema-relaterade event-namn.

    Används av emit_event_safe() i plugin.py för konsistenta event-namn.
    Legacy-format bibehålls för bakåtkompatibilitet.
    """

    LOADED: Final[str] = "ts:schema:loaded"
    VERSION_CHANGED: Final[str] = "ts:schema:version_changed"
    CREATED: Final[str] = "ts:schema:created"
    DELETED: Final[str] = "ts:schema:deleted"
    EXPORTED: Final[str] = "ts:schema:exported"
    IMPORTED: Final[str] = "ts:schema:imported"
    VALIDATED: Final[str] = "ts:schema:validated"
    MERGED: Final[str] = "ts:schema:merged"
    CLONED: Final[str] = "ts:schema:cloned"
    UPGRADED: Final[str] = "ts:schema:upgraded"
    BACKUP: Final[str] = "ts:schema:backup"
    RESTORED: Final[str] = "ts:schema:restored"
    SYNCED: Final[str] = "ts:schema:synced"
    POST_TYPE_REGISTERED: Final[str] = "ts:schema:post_type_registered"

    # Legacy (bakåtkompatibilitet)
    LEGACY_LOADED: Final[str] = "schema:loaded"
    LEGACY_VERSION_CHANGED: Final[str] = "schema:version_changed"


# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER 1–10: CORE
# ══════════════════════════════════════════════════════════════════════════════


def get_post_type_info(post_type: str) -> Optional[Dict[str, Any]]:
    """
    1. Hämta metadata för en posttyp.

    Args:
        post_type: Posttypskod (t.ex. "45", "28", "99")

    Returns:
        Dict med metadata eller None om okänd posttyp
    """
    return _KNOWN_POST_TYPES.get(post_type)


def is_known_post_type(post_type: str) -> bool:
    """
    2. Kontrollera om posttyp är känd.

    Args:
        post_type: Posttypskod

    Returns:
        True om posttypen finns i KNOWN_POST_TYPES
    """
    return post_type in _KNOWN_POST_TYPES


def get_post_type_position(post_type: str) -> str:
    """
    3. Hämta position för posttyp i fil.

    Args:
        post_type: Posttypskod

    Returns:
        "first", "middle", "last" eller "unknown"
    """
    info = get_post_type_info(post_type)
    if info:
        return str(info.get("position", "unknown"))
    return "unknown"


def normalize_field_type(type_str: str) -> str:
    """
    4. Normalisera fälttyp-sträng till intern representation.

    Hanterar alla varianter från TS_TYPE_MAPPING och FIELD_TYPE_FROM_CODE.
    Fallback: "alphanumeric".

    Args:
        type_str: Typsträng (t.ex. "N", "AN", "numerisk", "text")

    Returns:
        Normaliserad typ: "numeric", "alphanumeric", "date" eller "constant"
    """
    if not type_str:
        return "alphanumeric"

    normalized = type_str.lower().strip()

    if normalized in TS_TYPE_MAPPING:
        return TS_TYPE_MAPPING[normalized]

    upper = type_str.strip().upper()
    if upper in FIELD_TYPE_FROM_CODE:
        return FIELD_TYPE_FROM_CODE[upper]

    return "alphanumeric"


def get_field_type_code(field_type: str) -> str:
    """
    5. Hämta kort kod för fälttyp.

    Args:
        field_type: Intern fälttyp ("numeric", "alphanumeric", etc.)

    Returns:
        Kort kod: "N", "AN", "D" eller "K"
    """
    normalized = normalize_field_type(field_type)
    return FIELD_TYPE_CODES.get(normalized, "AN")


def register_post_type(
    post_type: str,
    name: str,
    description: str = "",
    position: str = "middle",
    required: bool = True,
    min_count: int = 0,
    max_count: Optional[int] = None,
    order: int = 50,
    source: str = "plugin",
    **extra: Any,
) -> bool:
    """
    6. Registrera ny posttyp dynamiskt.

    Gör systemet framtidssäkert för okända/nya posttyper.
    Andra plugins kan anropa detta för att registrera sina posttyper.
    Notifierar alla listeners via callback.

    Args:
        post_type:   Posttypskod (t.ex. "97")
        name:        Beskrivande namn
        description: Detaljerad beskrivning
        position:    "first", "middle" eller "last"
        required:    Om posttypen är obligatorisk
        min_count:   Minimum antal per fil
        max_count:   Maximum antal (None = obegränsat)
        order:       Sorteringsordning (0=först, 100=sist)
        source:      Källa ("builtin", "plugin", "import" etc.)
        **extra:     Ytterligare metadata

    Returns:
        True om registrering lyckades, False om post_type eller name saknas
    """
    if not post_type or not name:
        return False

    if position not in {"first", "middle", "last"}:
        position = "middle"

    metadata: Dict[str, Any] = {
        "name": name,
        "description": description,
        "required": required,
        "position": position,
        "min_count": min_count,
        "max_count": max_count,
        "count": "one" if max_count == 1 else "many",
        "order": order,
        "source": source,
        "registered_at": datetime.now().isoformat(),
        **extra,
    }

    was_existing = post_type in _KNOWN_POST_TYPES
    _KNOWN_POST_TYPES[post_type] = metadata

    action = "updated" if was_existing else "registered"
    for listener in list(_POST_TYPE_LISTENERS):
        try:
            listener(post_type, action, metadata)
        except Exception:
            pass

    return True


def unregister_post_type(post_type: str) -> bool:
    """
    7. Avregistrera en posttyp.

    Kan INTE avregistrera inbyggda posttyper (28, 45, 99).

    Args:
        post_type: Posttypskod

    Returns:
        True om avregistrering lyckades
    """
    if post_type in ("28", "45", "99"):
        return False

    if post_type not in _KNOWN_POST_TYPES:
        return False

    metadata = _KNOWN_POST_TYPES.pop(post_type)

    for listener in list(_POST_TYPE_LISTENERS):
        try:
            listener(post_type, "unregistered", metadata)
        except Exception:
            pass

    return True


def get_all_post_types() -> List[Dict[str, Any]]:
    """
    8. Lista alla kända posttyper med metadata, sorterade efter order.

    Returns:
        Lista med dicts ({"post_type": str, ...metadata})
    """
    result = [
        {"post_type": pt, **info}
        for pt, info in _KNOWN_POST_TYPES.items()
    ]
    return sorted(result, key=lambda x: x.get("order", 50))


def validate_post_length(length: int) -> Tuple[bool, str]:
    """
    9. Validera postlängd mot standard (TS_POST_LENGTH = 2500).

    Args:
        length: Längd att validera

    Returns:
        Tuple (is_valid: bool, error_message: str)
        error_message är tom sträng om is_valid=True
    """
    if length == TS_POST_LENGTH:
        return True, ""
    if length < 1:
        return False, f"Ogiltig längd: {length} (måste vara > 0)"
    if length > TS_POST_LENGTH:
        return (
            False,
            f"Längd {length} överskrider maximum {TS_POST_LENGTH}",
        )
    return False, f"Förväntad längd {TS_POST_LENGTH}, fick {length}"


def get_encoding_errors(text: str) -> List[Dict[str, Any]]:
    """
    10. Hitta tecken som inte är Latin-1-kompatibla.

    Args:
        text: Text att kontrollera

    Returns:
        Lista med dicts:
          position:   int   (0-baserad position i texten)
          char:       str   (det ogiltiga tecknet)
          unicode:    str   (t.ex. "U+20AC")
          suggestion: str   (föreslagen ersättning från LATIN1_REPLACEMENTS)
    """
    errors: List[Dict[str, Any]] = []
    if not text:
        return errors

    for i, char in enumerate(text):
        try:
            char.encode(TS_ENCODING)
        except UnicodeEncodeError:
            errors.append({
                "position": i,
                "char": char,
                "unicode": f"U+{ord(char):04X}",
                "suggestion": LATIN1_REPLACEMENTS.get(char, "?"),
            })

    return errors


# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER 11–20: ADVANCED
# ══════════════════════════════════════════════════════════════════════════════


def get_schema_defaults() -> Dict[str, Any]:
    """
    11. Hämta standardvärden för schema-skapande (kopia).

    Returns:
        Dict med default-värden för fält och schemas
    """
    return SCHEMA_DEFAULTS.copy()


def sanitize_for_encoding(
    text: str, replacement: str = "?"
) -> str:
    """
    12. Rensa text från ogiltiga Latin-1-tecken.

    Steg 1: Ersätt kända tecken via LATIN1_REPLACEMENTS.
    Steg 2: Ersätt övriga ogiltiga med replacement-tecken.

    Args:
        text:        Text att rensa
        replacement: Ersättningstecken för okända (default "?")

    Returns:
        Latin-1-kompatibel sträng
    """
    if not text:
        return ""

    result = text
    for uni_char, latin1_char in LATIN1_REPLACEMENTS.items():
        if uni_char in result:
            result = result.replace(uni_char, latin1_char)

    output: List[str] = []
    for char in result:
        try:
            char.encode(TS_ENCODING)
            output.append(char)
        except UnicodeEncodeError:
            output.append(replacement)

    return "".join(output)


def ensure_latin1(text: str) -> str:
    """
    13. Säkerställ Latin-1-kompatibilitet.

    Alias för sanitize_for_encoding() med "?" som ersättning —
    ogiltiga tecken ersätts (EJ tas bort, vilket skulle förskjuta
    positioner i fasta TS-format). Konsistent med models.py.

    Args:
        text: Text att konvertera

    Returns:
        Latin-1-kompatibel sträng (ogiltiga tecken ersatta med "?")
    """
    return sanitize_for_encoding(text, replacement="?")


def validate_latin1(text: str) -> Tuple[bool, List[str]]:
    """
    14. Validera Latin-1-kompatibilitet.

    Returnerar unika ogiltiga tecken (EJ positioner).
    Matchar signaturen i models.py.

    Args:
        text: Text att validera

    Returns:
        Tuple (is_valid: bool, invalid_chars: List[str])
        invalid_chars innehåller unika ogiltiga tecken.
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


def get_post_types_by_position(position: str) -> List[str]:
    """
    15. Hämta alla posttypskoder för en viss position.

    Args:
        position: "first", "middle" eller "last"

    Returns:
        Lista med posttypskoder, sorterade efter order-värde
    """
    types = [
        (pt, info.get("order", 50))
        for pt, info in _KNOWN_POST_TYPES.items()
        if info.get("position") == position
    ]
    return [pt for pt, _ in sorted(types, key=lambda x: x[1])]


def get_required_post_types() -> List[str]:
    """
    16. Hämta alla obligatoriska posttypskoder.

    Returns:
        Lista med posttypskoder där required=True
    """
    return [
        pt
        for pt, info in _KNOWN_POST_TYPES.items()
        if info.get("required", False)
    ]


def get_padding_rule(field_type: str) -> Dict[str, Any]:
    """
    17. Hämta padding-regel för fälttyp (kopia).

    Args:
        field_type: Fälttyp (normaliseras via normalize_field_type)

    Returns:
        Dict med: pad_char, justify, strip_non_digits
    """
    normalized = normalize_field_type(field_type)
    return FIELD_PADDING_RULES.get(
        normalized,
        FIELD_PADDING_RULES["alphanumeric"],
    ).copy()


def is_typically_required(field_name: str) -> bool:
    """
    18. Kontrollera om fältnamn typiskt är obligatoriskt.

    Användbart vid import för att föreslå mandatory-status.

    Args:
        field_name: Fältnamn

    Returns:
        True om fältnamnet finns i TYPICALLY_REQUIRED_FIELDS
    """
    return field_name.upper() in TYPICALLY_REQUIRED_FIELDS


def is_typically_constant(field_name: str) -> bool:
    """
    19. Kontrollera om fältnamn typiskt är ett konstantfält.

    Användbart vid import för att föreslå field_type="constant".

    Args:
        field_name: Fältnamn

    Returns:
        True om fältnamnet finns i TYPICALLY_CONSTANT_FIELDS
    """
    return field_name.upper() in TYPICALLY_CONSTANT_FIELDS


def add_post_type_listener(
    callback: Callable[[str, str, Dict[str, Any]], None],
) -> bool:
    """
    20. Lägg till lyssnare för posttyp-ändringar.

    Callback anropas med (post_type: str, action: str, metadata: Dict)
    där action är: "registered", "updated" eller "unregistered".

    Args:
        callback: Funktion att anropa vid ändringar

    Returns:
        True om lyssnare lades till, False om den redan finns
    """
    try:
        if callback not in _POST_TYPE_LISTENERS:
            _POST_TYPE_LISTENERS.append(callback)
            return True
        return False
    except Exception:
        return False


def remove_post_type_listener(
    callback: Callable[[str, str, Dict[str, Any]], None],
) -> bool:
    """
    Ta bort lyssnare för posttyp-ändringar. Kraschsäker.

    Args:
        callback: Funktion att ta bort

    Returns:
        True om lyssnare togs bort, False om den ej fanns
    """
    try:
        if callback in _POST_TYPE_LISTENERS:
            _POST_TYPE_LISTENERS.remove(callback)
            return True
        return False
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# COLUMN DETECTION FOR EXCEL IMPORT
# ══════════════════════════════════════════════════════════════════════════════


def detect_column_type(column_name: str) -> Optional[str]:
    """
    Detektera kolumntyp baserat på kolumnnamn (används vid Excel-import).

    Matchar mot regex-mönster i COLUMN_PATTERNS.

    Args:
        column_name: Kolumnnamn från Excel

    Returns:
        Matchad kolumntyp ("name", "position", "length" etc.)
        eller None om ingen matchning

    Exempel:
        detect_column_type("Fältnamn")  -> "name"
        detect_column_type("Position")  -> "position"
        detect_column_type("XYZ123")    -> None
    """
    if not column_name:
        return None

    col_lower = column_name.lower().strip()

    for col_type, patterns in COLUMN_PATTERNS.items():
        for pattern in patterns:
            try:
                if re.match(pattern, col_lower, re.IGNORECASE):
                    return col_type
            except re.error:
                continue

    return None


def get_column_patterns() -> Dict[str, List[str]]:
    """
    Hämta alla kolumnmönster som kopia.

    Returns:
        Dict med kolumntyp -> lista med regex-mönster
    """
    return {k: list(v) for k, v in COLUMN_PATTERNS.items()}


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC
# ══════════════════════════════════════════════════════════════════════════════


def get_constants_info() -> Dict[str, Any]:
    """
    Hämta diagnostikinformation om alla konstanter.

    Användbart för debug och systemrapporter.

    Returns:
        Dict med konstant-värden och metadata
    """
    return {
        "version": VERSION,
        "author": AUTHOR,
        "copyright": get_copyright_string(),
        "ts_post_length": TS_POST_LENGTH,
        "ts_encoding": TS_ENCODING,
        "ts_encoding_aliases": list(TS_ENCODING_ALIASES),
        "known_post_types": list(_KNOWN_POST_TYPES.keys()),
        "post_type_count": len(_KNOWN_POST_TYPES),
        "field_types": list(FIELD_TYPE_CODES.keys()),
        "field_type_codes": FIELD_TYPE_CODES,
        "latin1_replacements_count": len(LATIN1_REPLACEMENTS),
        "column_pattern_types": list(COLUMN_PATTERNS.keys()),
        "post_type_listeners": len(_POST_TYPE_LISTENERS),
        "typically_required_fields": sorted(TYPICALLY_REQUIRED_FIELDS),
        "typically_constant_fields": sorted(TYPICALLY_CONSTANT_FIELDS),
        "spec_dir_name": SPEC_DIR_NAME,
        "backup_dir_name": BACKUP_DIR_NAME,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
    }


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════


__all__ = [
    # Version & Copyright
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
    # Core Constants
    "TS_POST_LENGTH",
    "TS_ENCODING",
    "TS_ENCODING_ALIASES",
    "SPEC_DIR_NAME",
    "BACKUP_DIR_NAME",
    "ACTIVE_VERSION_KEY",
    "CACHE_TTL_SECONDS",
    # Latin-1
    "LATIN1_REPLACEMENTS",
    # Post Types
    "KNOWN_POST_TYPES",
    "get_known_post_types",
    # Type Mappings
    "TS_TYPE_MAPPING",
    "FIELD_TYPE_CODES",
    "FIELD_TYPE_FROM_CODE",
    "FIELD_PADDING_RULES",
    # Schema Defaults
    "SCHEMA_DEFAULTS",
    "TYPICALLY_REQUIRED_FIELDS",
    "TYPICALLY_CONSTANT_FIELDS",
    # Column Patterns
    "COLUMN_PATTERNS",
    # Event Names
    "SchemaEventNames",
    # Functions 1–10: Core
    "get_post_type_info",
    "is_known_post_type",
    "get_post_type_position",
    "normalize_field_type",
    "get_field_type_code",
    "register_post_type",
    "unregister_post_type",
    "get_all_post_types",
    "validate_post_length",
    "get_encoding_errors",
    # Functions 11–20: Advanced
    "get_schema_defaults",
    "sanitize_for_encoding",
    "ensure_latin1",
    "validate_latin1",
    "get_post_types_by_position",
    "get_required_post_types",
    "get_padding_rule",
    "is_typically_required",
    "is_typically_constant",
    "add_post_type_listener",
    "remove_post_type_listener",
    # Column Detection
    "detect_column_type",
    "get_column_patterns",
    # Diagnostic
    "get_constants_info",
]