# -*- coding: utf-8 -*-
# Fil: plugins/gui_helpers/components/validators.py

"""
Validators v1.0.1

Valideringsfunktioner för data (ren Python, inga GUI-beroenden) +
QValidator-fabriker (valfria, kräver PySide6).

Funktioner:
    - validate_vin: Validera VIN-nummer
    - validate_registration: Validera registreringsnummer
    - validate_orgnr: Validera organisationsnummer
    - validate_date: Validera datum
    - validate_email: Validera e-post
    - validate_phone: Validera telefonnummer
    - validate_required: Kontrollera obligatoriskt fält
    - validate_length: Kontrollera längd
    - validate_numeric: Kontrollera numeriskt
    - validate_latin1: Kontrollera Latin-1 kompatibilitet
    - create_vin_validator / create_numeric_validator /
      create_text_validator: QValidator-fabriker (plugin-kontraktet
      i gui_helpers/plugin.py v2.0.1 — returnerar None utan PySide6)

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil: plugins/gui_helpers/components/
    validators.py" tillagd (saknades — stod utan "Fil:"-prefix).
  - FIX (låst regel, inga hårdkodade årtal): COPYRIGHT_YEAR_START
    (2024) BORT — get_copyright_string() returnerar nu enbart
    innevarande år, konsistent med övriga moduler
    ("Copyright © <år> Rickard Längkvist"). Docstring-placeholdern
    "{current_year}" ersatt med dynamisk formulering.
  - FIX (integration, korrekthet): create_vin_validator()/
    create_numeric_validator()/create_text_validator() LAGT TILL —
    gui_helpers/plugin.py v2.0.1 anropar dessa via self.validators;
    utan dem AttributeError så fort komponenterna laddas. Lazy
    PySide6-import i funktionerna → returnerar None i headless
    (kraschsäkert, samma mönster som plugin.py:s HAS_PYSIDE6).
    create_vin_validator använder samma regel som sap_import
    (^[A-HJ-NPR-Z0-9]{17}$ — inga I/O/Q).
  - FIX (korrekthet): validate_orgnr — float-indata (vanligt från
    Excel) normaliseras nu (5566778899.0 → "5566778899") i stället
    för att avvisas som icke-siffror.
  - FIX (konsistens): VERSION/AUTHOR tillagda + i __all__.
  - FIX (radbrytningsartefakt): dubblerade blankrader före def/class
    kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (VIN-checksumma för NA-fordon,
    registreringsnummer, Luhn-orgnr, datum-intervall, e-post/telefon,
    sammansatta validatorer).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable, Optional, Tuple, Union

AUTHOR: str = "Rickard Längkvist"
VERSION: str = "1.0.1"

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# VIN VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

# VIN-tecken (I, O, Q är ej tillåtna — konsistent med sap_import
# VIN_PATTERN ^[A-HJ-NPR-Z0-9]{17}$).
VIN_CHARS: str = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"

# VIN-checksummavikter (standard, position 9 = kontrolltecken).
VIN_WEIGHTS: list = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]

# VIN-translitterering (A–H, J–N, P, R–Z; I/O/Q saknas medvetet).
VIN_VALUES: dict = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}

def validate_vin(vin: Any) -> Tuple[bool, str]:
    """
    Validera VIN-nummer (Vehicle Identification Number).

    Kontrollerar:
    - Längd (exakt 17 tecken)
    - Tillåtna tecken (ej I, O, Q)
    - Checksumma (position 9) för nordamerikanska fordon

    Args:
        vin: VIN att validera

    Returns:
        (is_valid, error_message)
    """
    if vin is None:
        return False, "VIN saknas"

    vin_str = str(vin).upper().strip()

    # Längd
    if len(vin_str) != 17:
        return False, f"VIN måste vara 17 tecken (har {len(vin_str)})"

    # Tillåtna tecken
    for i, char in enumerate(vin_str):
        if char not in VIN_CHARS:
            return False, f"Ogiltigt tecken '{char}' på position {i + 1}"

    # Checksumma (endast för nordamerikanska fordon, position 1
    # börjar med 1–5)
    if vin_str[0] in "12345":
        check_digit = vin_str[8]
        total = 0

        for i, char in enumerate(vin_str):
            if char.isdigit():
                value = int(char)
            else:
                value = VIN_VALUES.get(char, 0)
            total += value * VIN_WEIGHTS[i]

        remainder = total % 11
        expected = "X" if remainder == 10 else str(remainder)

        if check_digit != expected:
            return False, "Ogiltig checksumma (position 9)"

    return True, ""

def validate_vin_prefix(
    prefix: Any, expected_length: int = 3
) -> Tuple[bool, str]:
    """
    Validera VIN-prefix (WMI).

    Args:
        prefix: VIN-prefix (t.ex. "YV1" för Volvo)
        expected_length: Förväntad längd (3 för WMI)
    """
    if prefix is None:
        return False, "VIN-prefix saknas"

    prefix_str = str(prefix).upper().strip()

    if len(prefix_str) != expected_length:
        return False, f"VIN-prefix måste vara {expected_length} tecken"

    for char in prefix_str:
        if char not in VIN_CHARS:
            return False, f"Ogiltigt tecken '{char}'"

    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRATION NUMBER VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def validate_registration(reg: Any) -> Tuple[bool, str]:
    """
    Validera svenskt registreringsnummer.

    Format: ABC123 eller ABC12D (nytt format)
    """
    if reg is None:
        return False, "Registreringsnummer saknas"

    reg_str = str(reg).upper().strip().replace(" ", "")

    if len(reg_str) != 6:
        return False, "Registreringsnummer måste vara 6 tecken"

    # Gammalt format: ABC123
    old_pattern = r"^[A-Z]{3}[0-9]{3}$"

    # Nytt format: ABC12D
    new_pattern = r"^[A-Z]{3}[0-9]{2}[A-Z0-9]$"

    if not (
        re.match(old_pattern, reg_str) or re.match(new_pattern, reg_str)
    ):
        return False, "Ogiltigt format (förväntat ABC123 eller ABC12D)"

    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# ORGANIZATION NUMBER VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def validate_orgnr(orgnr: Any) -> Tuple[bool, str]:
    """
    Validera svenskt organisationsnummer (Luhn-kontrollsiffra).

    Format: NNNNNN-NNNN (10 siffror, optional bindestreck)
    """
    if orgnr is None:
        return False, "Organisationsnummer saknas"

    # Normalisera float-indata (vanligt från Excel: 5566778899.0).
    if isinstance(orgnr, float) and orgnr.is_integer():
        orgnr = int(orgnr)

    # Ta bort bindestreck och mellanslag
    orgnr_str = str(orgnr).replace("-", "").replace(" ", "")

    if not orgnr_str.isdigit():
        return False, "Organisationsnummer får endast innehålla siffror"

    if len(orgnr_str) != 10:
        return False, "Organisationsnummer måste vara 10 siffror"

    # Luhn-algoritm (kontrollsiffra)
    total = 0
    for i, digit in enumerate(orgnr_str[:-1]):
        d = int(digit)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d

    check_digit = (10 - (total % 10)) % 10

    if int(orgnr_str[-1]) != check_digit:
        return False, "Ogiltig kontrollsiffra"

    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# DATE VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def validate_date(
    value: Any,
    min_date: Optional[date] = None,
    max_date: Optional[date] = None,
    format_str: str = "%Y-%m-%d",
) -> Tuple[bool, str]:
    """
    Validera datum.

    Args:
        value: Datum att validera (str eller date)
        min_date: Minsta tillåtna datum
        max_date: Största tillåtna datum
        format_str: Datumformat för strängar
    """
    if value is None:
        return False, "Datum saknas"

    # Konvertera till date
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    elif isinstance(value, str):
        try:
            d = datetime.strptime(value.strip(), format_str).date()
        except ValueError:
            return False, f"Ogiltigt datumformat (förväntat {format_str})"
    else:
        return False, "Ogiltigt datumtyp"

    # Intervallkontroll
    if min_date and d < min_date:
        return False, f"Datum får inte vara före {min_date}"

    if max_date and d > max_date:
        return False, f"Datum får inte vara efter {max_date}"

    return True, ""

def validate_date_range(start: Any, end: Any) -> Tuple[bool, str]:
    """Validera att startdatum är före slutdatum."""
    start_valid, start_error = validate_date(start)
    if not start_valid:
        return False, f"Startdatum: {start_error}"

    end_valid, end_error = validate_date(end)
    if not end_valid:
        return False, f"Slutdatum: {end_error}"

    # Normalisera till date för jämförelse
    start_date = _as_date(start)
    end_date = _as_date(end)
    if start_date is None or end_date is None:
        return False, "Ogiltigt datum"

    if start_date > end_date:
        return False, "Startdatum måste vara före slutdatum"

    return True, ""

def _as_date(value: Any) -> Optional[date]:
    """Konvertera str/date/datetime till date. KRASCHSÄKER."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL / PHONE VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def validate_email(email: Any) -> Tuple[bool, str]:
    """Validera e-postadress."""
    if email is None:
        return False, "E-postadress saknas"

    email_str = str(email).strip()

    # Enkel regex för e-post
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    if not re.match(pattern, email_str):
        return False, "Ogiltig e-postadress"

    return True, ""

def validate_phone(phone: Any) -> Tuple[bool, str]:
    """Validera telefonnummer (svenskt format)."""
    if phone is None:
        return False, "Telefonnummer saknas"

    # Ta bort formattering
    phone_str = str(phone).replace(" ", "").replace("-", "").replace("+", "")

    if not phone_str.isdigit():
        return False, "Telefonnummer får endast innehålla siffror"

    if len(phone_str) < 8 or len(phone_str) > 15:
        return False, "Telefonnummer har ogiltig längd"

    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# GENERAL VALIDATORS
# ══════════════════════════════════════════════════════════════════════════════

def validate_required(
    value: Any, field_name: str = "Fält"
) -> Tuple[bool, str]:
    """Kontrollera att ett obligatoriskt fält har värde."""
    if value is None:
        return False, f"{field_name} är obligatoriskt"

    if isinstance(value, str) and not value.strip():
        return False, f"{field_name} får inte vara tomt"

    return True, ""

def validate_length(
    value: Any,
    min_length: int = 0,
    max_length: int = 0,
    exact_length: int = 0,
) -> Tuple[bool, str]:
    """
    Validera stränglängd.

    Args:
        value: Värde att validera
        min_length: Minsta längd (0 = ingen gräns)
        max_length: Största längd (0 = ingen gräns)
        exact_length: Exakt längd (0 = används ej)
    """
    if value is None:
        return False, "Värde saknas"

    length = len(str(value))

    if exact_length > 0:
        if length != exact_length:
            return False, (
                f"Måste vara exakt {exact_length} tecken (har {length})"
            )
        return True, ""

    if min_length > 0 and length < min_length:
        return False, f"Måste vara minst {min_length} tecken (har {length})"

    if max_length > 0 and length > max_length:
        return False, f"Får vara max {max_length} tecken (har {length})"

    return True, ""

def validate_numeric(
    value: Any,
    min_value: Optional[Union[int, float]] = None,
    max_value: Optional[Union[int, float]] = None,
    allow_decimal: bool = True,
) -> Tuple[bool, str]:
    """Validera numeriskt värde."""
    if value is None:
        return False, "Värde saknas"

    # Konvertera
    try:
        if allow_decimal:
            num = float(value)
        else:
            num = int(value)
    except (ValueError, TypeError):
        return False, "Måste vara ett tal"

    if min_value is not None and num < min_value:
        return False, f"Måste vara minst {min_value}"

    if max_value is not None and num > max_value:
        return False, f"Får vara max {max_value}"

    return True, ""

def validate_latin1(value: Any) -> Tuple[bool, str]:
    """
    Validera att värdet kan kodas som Latin-1 (ISO-8859-1).

    Viktigt för TS-filer.
    """
    if value is None:
        return True, ""

    try:
        str(value).encode("iso-8859-1")
        return True, ""
    except UnicodeEncodeError as exc:
        # Hitta ogiltigt tecken
        char = exc.object[exc.start:exc.end]
        return False, f"Ogiltigt tecken '{char}' (ej Latin-1 kompatibelt)"

def validate_pattern(
    value: Any, pattern: str, message: str = "Ogiltigt format"
) -> Tuple[bool, str]:
    """Validera mot regex-mönster."""
    if value is None:
        return False, "Värde saknas"

    if not re.match(pattern, str(value)):
        return False, message

    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# COMPOSITE VALIDATORS
# ══════════════════════════════════════════════════════════════════════════════

def create_validator(
    *validators: Callable[[Any], Tuple[bool, str]],
) -> Callable[[Any], Tuple[bool, str]]:
    """
    Skapa en kombinerad validator.

    Användning:
        validator = create_validator(
            validate_required,
            lambda v: validate_length(v, max_length=17),
            validate_vin,
        )
    """

    def combined(value: Any) -> Tuple[bool, str]:
        for validator in validators:
            is_valid, error = validator(value)
            if not is_valid:
                return False, error
        return True, ""

    return combined

def create_field_validator(
    required: bool = False,
    min_length: int = 0,
    max_length: int = 0,
    pattern: str = "",
    custom: Optional[Callable[[Any], Tuple[bool, str]]] = None,
) -> Callable[[Any], Tuple[bool, str]]:
    """
    Skapa fält-validator med standardkontroller.

    Användning:
        validator = create_field_validator(
            required=True,
            max_length=50,
            pattern=r'^[A-Z]+$',
        )
    """
    validators = []

    if required:
        validators.append(lambda v: validate_required(v))

    if min_length > 0 or max_length > 0:
        validators.append(
            lambda v: validate_length(v, min_length, max_length)
        )

    if pattern:
        validators.append(lambda v: validate_pattern(v, pattern))

    if custom:
        validators.append(custom)

    return create_validator(*validators)


# ══════════════════════════════════════════════════════════════════════════════
# QVALIDATOR-FABRIKER (plugin-kontraktet i gui_helpers/plugin.py)
# ══════════════════════════════════════════════════════════════════════════════
# Lazy PySide6-import i varje funktion — returnerar None i headless
# (kraschsäkert). create_vin_validator använder samma regel som
# sap_import: ^[A-HJ-NPR-Z0-9]{17}$ (inga I/O/Q).

def create_vin_validator() -> Optional[Any]:
    """
    Skapa QRegularExpressionValidator för VIN (17 tecken, ej I/O/Q).

    Returns:
        QValidator-instans eller None om PySide6 saknas
    """
    try:
        from PySide6.QtCore import QRegularExpression
        from PySide6.QtGui import QRegularExpressionValidator
    except ImportError:
        return None
    return QRegularExpressionValidator(
        QRegularExpression(r"^[A-HJ-NPR-Z0-9]{17}$")
    )

def create_numeric_validator(
    min_val: int = 0,
    max_val: int = 999999,
) -> Optional[Any]:
    """
    Skapa QIntValidator för numeriska fält.

    Returns:
        QIntValidator-instans eller None om PySide6 saknas
    """
    try:
        from PySide6.QtGui import QIntValidator
    except ImportError:
        return None
    return QIntValidator(min_val, max_val)

def create_text_validator(
    pattern: str = r".*",
    max_length: int = 100,
) -> Optional[Any]:
    """
    Skapa QRegularExpressionValidator för text med längdbegränsning.

    Returns:
        QValidator-instans eller None om PySide6 saknas
    """
    try:
        from PySide6.QtCore import QRegularExpression
        from PySide6.QtGui import QRegularExpressionValidator
    except ImportError:
        return None
    regex = QRegularExpression(
        "^(?:%s){0,%d}$" % (pattern, max_length)
    )
    return QRegularExpressionValidator(regex)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Metadata
    "VERSION",
    "AUTHOR",
    # VIN
    "validate_vin",
    "validate_vin_prefix",
    # Registration
    "validate_registration",
    "validate_orgnr",
    # Date
    "validate_date",
    "validate_date_range",
    # Contact
    "validate_email",
    "validate_phone",
    # General
    "validate_required",
    "validate_length",
    "validate_numeric",
    "validate_latin1",
    "validate_pattern",
    # Composite
    "create_validator",
    "create_field_validator",
    # QValidator-fabriker
    "create_vin_validator",
    "create_numeric_validator",
    "create_text_validator",
    # Utils
    "get_copyright_string",
]
