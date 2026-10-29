# -*- coding: utf-8 -*-
# Fil: plugins/ts_file_generator/latin1_utils.py
"""
Latin-1 Utils v2.0.1

Verktyg för Latin-1 (ISO-8859-1) validering och rensning
för TS-filer mot Transportstyrelsen.

ANSVAR:
    - validate_latin1(text)   → Tuple[bool, List[str]]
    - sanitize_for_ts(text)   → str
    - ensure_latin1(text)     → str
    - LATIN1_REPLACEMENTS     → Dict med kända ersättningar

KRAV:
    - TS-filer måste vara strikt ISO-8859-1 / Latin-1
    - Ogiltiga tecken ersätts med närmaste Latin-1-ekvivalent
    - Om ingen ekvivalent finns → ersätts med '?'

FÖRÄNDRINGAR v2.0.1 (granskad — spec v1.6 förbättringsregeln):
    - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2026 ..." i
      docstringen BORTTAGEN — copyright genereras dynamiskt via
      get_copyright_string().
    - Städning: LATIN1_REPLACEMENTS — no-op-entryn borttagna (tecken
      som redan ÄR Latin-1 mappade till sig själva: Å Ä Ö å ä ö Ü ü
      é è ê ë à â ç î ï ô ù û ÿ æ Æ á £ ¥ m.fl.). Dessa gjorde
      ingenting men lade till ~30 onödiga iterationer per anrop.
      Nu: endast faktiska ersättningar (~40 entryn).
    - get_logger() -> _get_logger() (privat, konvention).
    - Importordning normaliserad (logging, re, unicodedata).
    - Docstring: "være" -> "vara" (svenska).
    - __all__ kompletterad med get_copyright_string.
    - Övrig logik OFÖRÄNDRAD (validate/sanitize/ensure, NFD-steg,
      kontrolltecken-städning, BOM/whitespace-hjälpare,
      validate_ts_record).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from typing import Dict, Final, List, Tuple

# ══════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT
# ══════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "2.0.1"
AUTHOR: Final[str] = "Rickard Längkvist"
TS_ENCODING: Final[str] = "iso-8859-1"
FALLBACK_CHAR: Final[str] = "?"


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
        return logging.getLogger("ts_file_generator.latin1_utils")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log = _get_logger()


# ══════════════════════════════════════════════════════════════════════
# KÄNDA LATIN-1 ERSÄTTNINGAR (endast FAKTISKA ersättningar — no-op
# entryn borttagna i v2.0.1)
# ══════════════════════════════════════════════════════════════════════

LATIN1_REPLACEMENTS: Final[Dict[str, str]] = {
    # Tyska
    "ß": "ss",

    # Franska
    "œ": "oe",
    "Œ": "OE",

    # Spanska/portugisiska (icke-Latin-1 varianter)
    "ñ": "n",
    "Ñ": "N",
    "í": "i",
    "ó": "o",
    "ú": "u",
    "ã": "a",
    "õ": "o",

    # Quotation marks → standard
    "\u2018": "'",   # left single quote
    "\u2019": "'",   # right single quote
    "\u201c": '"',   # left double quote
    "\u201d": '"',   # right double quote
    "\u2032": "'",   # prime
    "\u2033": '"',   # double prime

    # Dashes → hyphen
    "\u2013": "-",   # en dash
    "\u2014": "-",   # em dash
    "\u2015": "-",   # horizontal bar

    # Ellipsis
    "\u2026": "...",

    # Bullets
    "\u2022": "*",
    "\u2023": "*",
    "\u2024": ".",

    # Mellanslag-varianter
    "\u00a0": " ",   # non-breaking space
    "\u2009": " ",   # thin space
    "\u200a": " ",   # hair space
    "\u200b": "",    # zero-width space
    "\u200c": "",    # zero-width non-joiner
    "\u200d": "",    # zero-width joiner
    "\ufeff": "",    # BOM

    # Pilar → ASCII
    "\u2190": "<",
    "\u2192": ">",
    "\u2191": "^",
    "\u2193": "v",

    # Matematiska
    "\u00d7": "x",   # multiplication sign
    "\u00f7": "/",   # division sign
    "\u00b1": "+/-",
    "\u00b2": "2",   # superscript 2
    "\u00b3": "3",   # superscript 3
    "\u00b9": "1",   # superscript 1
    "\u2212": "-",   # minus sign

    # Copyright / varumärken
    "\u00ae": "(R)",
    "\u2122": "(TM)",

    # Valutor
    "\u20ac": "EUR",  # euro (ej i Latin-1)

    # Kontrolltecken
    "\t": " ",         # tab → mellanslag
    "\r\n": "\n",      # Windows radslut
    "\r": "\n",        # CR-only radslut
}


# ══════════════════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════

def validate_latin1(text: str) -> Tuple[bool, List[str]]:
    """
    Validera att en sträng är Latin-1 (ISO-8859-1) kompatibel.

    Args:
        text: Strängen att validera

    Returns:
        Tuple (is_valid, list_of_invalid_chars)
        - is_valid:              True om alla tecken är Latin-1
        - list_of_invalid_chars: Lista av ogiltiga tecken (unika)
          på formen "U+XXXX ('c')"
    """
    if not isinstance(text, str):
        return False, [f"Ogiltigt typ: {type(text).__name__}"]

    invalid_chars: List[str] = []

    for char in text:
        try:
            char.encode(TS_ENCODING)
        except UnicodeEncodeError:
            char_repr = f"U+{ord(char):04X} ({char!r})"
            if char_repr not in invalid_chars:
                invalid_chars.append(char_repr)

    return len(invalid_chars) == 0, invalid_chars


def sanitize_for_ts(text: str) -> str:
    """
    Rensa text för TS-filer.

    Steg:
        1. Byt kända icke-Latin-1-tecken mot Latin-1-ekvivalent
        2. Försök NFD-normalisering för att extrahera bas-tecken
        3. Ersätt okända tecken med '?'
        4. Ta bort kontrolltecken (utom radbrytningar)

    Args:
        text: Text att rensa

    Returns:
        Latin-1 kompatibel sträng
    """
    if not isinstance(text, str):
        return str(text or "")

    if not text:
        return ""

    # Steg 1: Kända ersättningar
    result = text
    for old, new in LATIN1_REPLACEMENTS.items():
        result = result.replace(old, new)

    # Steg 2: NFD-normalisering
    normalized_chars: List[str] = []
    for char in result:
        try:
            char.encode(TS_ENCODING)
            normalized_chars.append(char)
            continue
        except UnicodeEncodeError:
            pass

        # Försök NFD — extrahera bas-tecken
        try:
            decomposed = unicodedata.normalize("NFD", char)
            base = decomposed[0] if decomposed else ""
            try:
                base.encode(TS_ENCODING)
                normalized_chars.append(base)
                continue
            except UnicodeEncodeError:
                pass
        except Exception:
            pass

        # Okänt tecken — ersätt med '?'
        _log.debug(
            "Ersätter U+%04X (%r) med '%s'.",
            ord(char), char, FALLBACK_CHAR,
        )
        normalized_chars.append(FALLBACK_CHAR)

    result = "".join(normalized_chars)

    # Steg 3: Ta bort kontrolltecken (utom normal radbrytning)
    result = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", result)

    return result


def ensure_latin1(text: str) -> str:
    """
    Säkerställ att text är Latin-1 kompatibel.

    Enklare än sanitize_for_ts — använder encode/decode med replace.
    Bör föregås av sanitize_for_ts för bästa resultat.

    Args:
        text: Text att säkerställa

    Returns:
        Latin-1 kompatibel sträng
    """
    if not isinstance(text, str):
        return str(text or "")

    try:
        text.encode(TS_ENCODING)
        return text
    except UnicodeEncodeError:
        return text.encode(TS_ENCODING, errors="replace").decode(TS_ENCODING)


def sanitize_and_ensure(text: str) -> str:
    """
    Kombinerad sanitering och Latin-1-säkring.

    Kör sanitize_for_ts() följt av ensure_latin1().
    Ger bästa möjliga resultat för teckenkonvertering.

    Args:
        text: Text att behandla

    Returns:
        Latin-1 kompatibel sträng
    """
    return ensure_latin1(sanitize_for_ts(text))


def is_latin1_safe(text: str) -> bool:
    """
    Snabb kontroll om text är Latin-1 kompatibel.

    Args:
        text: Text att kontrollera

    Returns:
        True om helt Latin-1 kompatibel
    """
    try:
        text.encode(TS_ENCODING)
        return True
    except UnicodeEncodeError:
        return False


def get_invalid_chars(text: str) -> List[Tuple[int, str, str]]:
    """
    Hitta alla ogiltiga Latin-1-tecken med position.

    Args:
        text: Text att kontrollera

    Returns:
        Lista av (position, char, unicode_repr)
    """
    invalid: List[Tuple[int, str, str]] = []
    for pos, char in enumerate(text):
        try:
            char.encode(TS_ENCODING)
        except UnicodeEncodeError:
            invalid.append((pos, char, f"U+{ord(char):04X}"))
    return invalid


def strip_bom(text: str) -> str:
    """
    Ta bort BOM (Byte Order Mark) från beginning av sträng.

    Args:
        text: Text att rensa

    Returns:
        Text utan BOM
    """
    return text.lstrip("\ufeff\u200b")


def normalize_whitespace(text: str, replacement: str = " ") -> str:
    """
    Normalisera whitespace (tab, non-breaking space etc.) till mellanslag.

    Args:
        text:        Text att normalisera
        replacement: Ersättningstecken (standard: mellanslag)

    Returns:
        Text med normaliserad whitespace
    """
    return re.sub(r"[\t\u00a0\u2009\u200a]+", replacement, text)


def validate_ts_record(record: str, expected_length: int = 2500) -> Tuple[bool, List[str]]:
    """
    Validera en komplett TS-post.

    Kontrollerar:
        1. Exakt rätt längd
        2. Latin-1 kompatibel
        3. Inga radbrytningar inuti posten

    Args:
        record:          TS-post att validera
        expected_length: Förväntad radlängd (standard: 2500)

    Returns:
        Tuple (is_valid, errors)
    """
    errors: List[str] = []

    if not isinstance(record, str):
        return False, [f"Ogiltigt typ: {type(record).__name__}"]

    if len(record) != expected_length:
        errors.append(
            f"Fel radlängd: {len(record)} tecken "
            f"(förväntade {expected_length})."
        )

    valid_latin1, invalid = validate_latin1(record)
    if not valid_latin1:
        errors.append(
            f"Ej Latin-1 kompatibel. "
            f"Ogiltiga tecken: {', '.join(invalid[:10])}"
        )

    if "\n" in record or "\r" in record:
        errors.append("Posten innehåller radbrytningar.")

    return len(errors) == 0, errors


# ══════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════

__all__ = [
    "validate_latin1",
    "sanitize_for_ts",
    "ensure_latin1",
    "sanitize_and_ensure",
    "is_latin1_safe",
    "get_invalid_chars",
    "strip_bom",
    "normalize_whitespace",
    "validate_ts_record",
    "get_copyright_string",
    "LATIN1_REPLACEMENTS",
    "TS_ENCODING",
    "FALLBACK_CHAR",
    "VERSION",
    "AUTHOR",
]
