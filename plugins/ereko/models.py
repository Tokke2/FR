# -*- coding: utf-8 -*-
# Fil: plugins/ereko/models.py

"""
eReKo / IVI Generator — Datamodeller v1.0.1

Modeller för elektronisk registreringsbevis (eCoC / IVI) enligt
EU-standard.

IVI (International Vehicle Identification) är det elektroniska
formatet för Certificate of Conformity (CoC) som krävs för
fordonsregistrering inom EU/EES.

STANDARD:
    - EU 2018/858 (Type Approval)
    - EUCARIS IVI Data Exchange Format
    - Transportstyrelsen eReKo-krav

DATAFLÖDE:
    VehicleData (från registry/SAP/dispatch)
        ↓
    IVIDocument.from_vehicle_data()
        ↓
    IVIDocument.validate()
        ↓
    IVIDocument.to_xml()
        ↓
    XML-fil sparas / skickas till EUCARIS

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil: plugins/ereko/models.py" tillagd
    (saknades — stod utan "Fil:"-prefix).
  - FIX (låst regel, inga hårdkodade årtal): docstringens
    "Copyright © 2025" bort — dynamisk copyright via
    get_copyright_string() (konsistent med plugin.py v1.0.1).
  - FIX (låst regel, loggning): _setup_logger() med StreamHandler
    BORT (störde appens loggning — logger-setup sköts av
    core/logger_setup); logger → modul-nivå _log; f-string-
    logganrop → lazy %s.
  - FIX (dataförlust, låst regel): save_xml() → atomisk skrivning
    (mkstemp → fsync → os.replace — egen lokal _atomic_write_text,
    samma mönster som övriga moduler; models.py hålls fristående
    från plugin.py för att undvika cirkulära imports).
  - FIX (versionsharmonisering): VERSION 1.0.0 → 1.0.1 (matchar
    plugin.py v1.0.1 — spec-regeln om konsistenta versioner inom
    plugin).
  - FIX (korrekthet): validate_vin — förbjudna-tecken-kontrollen
    (I/O/Q) låg EFTER VIN_PATTERN som redan exkluderar tecknen →
    död kod med otydligt felmeddelande. Kontrollen flyttad FÖRE
    mönstret (tydligare "får inte innehålla 'X'" — fångat av test).
  - FIX (radbrytningsartefakt): dubblerade blankrader före
    def/class kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (enums + from_string-mappningar,
    validate_vin/date/type_approval, sanitize_xml_string,
    dataklasserna + deras validators, IVIDocument.validate/to_xml/
    to_dict/from_vehicle_data med svenska/engelska fallback-nycklar,
    kW↔hk-konvertering i TechnicalData.validate).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple
from xml.dom import minidom

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "1.0.1"
AUTHOR: Final[str] = "Rickard Längkvist"

# IVI XML Namespace
IVI_NAMESPACE: Final[str] = "urn:eu:eucaris:ivi:1.0"
IVI_SCHEMA_VERSION: Final[str] = "1.0"

# Encoding
IVI_ENCODING: Final[str] = "UTF-8"

# VIN-validering (konsistent med sap_import/validators).
VIN_LENGTH: Final[int] = 17
VIN_PATTERN: Final[re.Pattern] = re.compile(
    r"^[A-HJ-NPR-Z0-9]{17}$"
)
VIN_FORBIDDEN_CHARS: Final[str] = "IOQ"  # I, O, Q förbjudna i VIN

def get_copyright_year() -> int:
    """Hämta aktuellt år."""
    return datetime.now().year

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {get_copyright_year()} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log: logging.Logger = logging.getLogger("ereko.models")


# ══════════════════════════════════════════════════════════════════════════════
# ATOMISK SKRIVNING (låst regel: mkstemp → fsync → os.replace)
# ══════════════════════════════════════════════════════════════════════════════

def _atomic_write_text(path: Path, text: str) -> None:
    """Atomisk textskrivning. KRASCHSÄKER (kastar vid fel)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".ereko_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════════════════════

class FuelType(Enum):
    """Bränsletyper enligt EU-standard."""

    PETROL = "Petrol"
    DIESEL = "Diesel"
    ELECTRIC = "Electric"
    HYBRID_PETROL = "Hybrid Petrol"
    HYBRID_DIESEL = "Hybrid Diesel"
    PLUGIN_HYBRID_PETROL = "Plugin Hybrid Petrol"
    PLUGIN_HYBRID_DIESEL = "Plugin Hybrid Diesel"
    CNG = "CNG"  # Compressed Natural Gas
    LPG = "LPG"  # Liquefied Petroleum Gas
    HYDROGEN = "Hydrogen"
    E85 = "E85"
    OTHER = "Other"
    UNKNOWN = "Unknown"

    @classmethod
    def from_string(cls, value: str) -> FuelType:
        """Konvertera sträng till FuelType. KRASCHSÄKER."""
        if not value:
            return cls.UNKNOWN

        value_upper = value.upper().strip()

        # Direkt mapping
        mapping = {
            "BENSIN": cls.PETROL,
            "PETROL": cls.PETROL,
            "GASOLINE": cls.PETROL,
            "DIESEL": cls.DIESEL,
            "EL": cls.ELECTRIC,
            "ELECTRIC": cls.ELECTRIC,
            "BATTERY": cls.ELECTRIC,
            "HYBRID": cls.HYBRID_PETROL,
            "HYBRID BENSIN": cls.HYBRID_PETROL,
            "HYBRID DIESEL": cls.HYBRID_DIESEL,
            "LADDHYBRID": cls.PLUGIN_HYBRID_PETROL,
            "PLUGIN": cls.PLUGIN_HYBRID_PETROL,
            "GAS": cls.CNG,
            "CNG": cls.CNG,
            "LPG": cls.LPG,
            "GASOL": cls.LPG,
            "VÄTE": cls.HYDROGEN,
            "HYDROGEN": cls.HYDROGEN,
            "E85": cls.E85,
            "ETANOL": cls.E85,
        }

        return mapping.get(value_upper, cls.UNKNOWN)

class VehicleCategory(Enum):
    """Fordonskategorier enligt EU 2018/858."""

    M1 = "M1"  # Personbilar (max 8 passagerare)
    M2 = "M2"  # Bussar (>8 pass, vikt ≤5000 kg)
    M3 = "M3"  # Bussar (>8 pass, vikt >5000 kg)
    N1 = "N1"  # Lätta lastbilar (≤3500 kg)
    N2 = "N2"  # Medeltunga lastbilar (3500-12000 kg)
    N3 = "N3"  # Tunga lastbilar (>12000 kg)
    L1E = "L1e"  # Moped (≤50cc, ≤45 km/h)
    L3E = "L3e"  # Motorcykel (>50cc eller >45 km/h)
    L7E = "L7e"  # Fyrhjuling
    O1 = "O1"  # Lätt släpvagn (≤750 kg)
    O2 = "O2"  # Släpvagn (750-3500 kg)
    O3 = "O3"  # Tung släpvagn (3500-10000 kg)
    O4 = "O4"  # Tung släpvagn (>10000 kg)
    OTHER = "Other"

    @classmethod
    def from_string(cls, value: str) -> VehicleCategory:
        """Konvertera sträng till VehicleCategory. KRASCHSÄKER."""
        if not value:
            return cls.M1  # Default = personbil

        value_upper = value.upper().strip()

        # Exakt match
        for cat in cls:
            if cat.value.upper() == value_upper:
                return cat

        # Fuzzy match
        if "PERSONBIL" in value_upper or "CAR" in value_upper:
            return cls.M1
        if "BUSS" in value_upper or "BUS" in value_upper:
            return cls.M2
        if "LASTBIL" in value_upper or "TRUCK" in value_upper:
            if "LÄTT" in value_upper or "LIGHT" in value_upper:
                return cls.N1
            if "TUNG" in value_upper or "HEAVY" in value_upper:
                return cls.N3
            return cls.N2
        if "MOTORCYKEL" in value_upper or "MOTORCYCLE" in value_upper:
            return cls.L3E
        if "MOPED" in value_upper:
            return cls.L1E
        if "SLÄP" in value_upper or "TRAILER" in value_upper:
            return cls.O1

        return cls.M1  # Default

class IVIStatus(Enum):
    """IVI-dokumentstatus."""

    DRAFT = "draft"
    VALID = "valid"
    INVALID = "invalid"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def validate_vin(vin: str) -> Tuple[bool, Optional[str]]:
    """
    Validera VIN enligt ISO 3779.

    Args:
        vin: VIN-nummer (17 tecken)

    Returns:
        Tuple med (är_giltig, felmeddelande)
    """
    if not vin:
        return False, "VIN får inte vara tom"

    vin = vin.upper().strip()

    if len(vin) != VIN_LENGTH:
        return False, (
            "VIN måste vara %d tecken (är %d)"
            % (VIN_LENGTH, len(vin))
        )

    # Kontrollera förbjudna tecken FÖRE mönstret — VIN_PATTERN
    # exkluderar redan I/O/Q, men denna kontroll ger ett tydligare
    # felmeddelande (annars nås den aldrig).
    for char in VIN_FORBIDDEN_CHARS:
        if char in vin:
            return False, "VIN får inte innehålla '%s'" % char

    if not VIN_PATTERN.match(vin):
        return False, "VIN innehåller ogiltiga tecken"

    return True, None

def validate_date(date_str: str) -> Tuple[bool, Optional[str]]:
    """
    Validera datum (ISO 8601: YYYY-MM-DD).

    Args:
        date_str: Datumsträng

    Returns:
        Tuple med (är_giltig, felmeddelande)
    """
    if not date_str:
        return False, "Datum får inte vara tomt"

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True, None
    except ValueError:
        return False, "Datum måste vara i format YYYY-MM-DD"

def validate_type_approval(
    approval_number: str,
) -> Tuple[bool, Optional[str]]:
    """
    Validera typgodkännandenummer.

    Format: e1*2018/858*00001*00
    - e + landskod (1-2 siffror)
    - * + förordning
    - * + typnummer
    - * + variant/version

    Args:
        approval_number: Typgodkännandenummer

    Returns:
        Tuple med (är_giltig, felmeddelande)
    """
    if not approval_number:
        return False, "Typgodkännandenummer får inte vara tomt"

    # Grundläggande format-check
    pattern = r"^e\d{1,2}\*[\w/]+\*\d+\*\d+$"
    if not re.match(pattern, approval_number, re.IGNORECASE):
        return False, (
            "Ogiltigt format för typgodkännandenummer (förväntat: "
            "e1*2018/858*00001*00)"
        )

    return True, None

def sanitize_xml_string(value: str) -> str:
    """
    Rensa sträng för XML-säkerhet.

    Args:
        value: Sträng att rensa

    Returns:
        XML-säker sträng
    """
    if not value:
        return ""

    # Ta bort kontroll-tecken (utom tab, newline, carriage return)
    value = re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", value
    )

    # Trimma whitespace
    value = value.strip()

    return value


# ══════════════════════════════════════════════════════════════════════════════
# DATAKLASSER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Manufacturer:
    """Tillverkare-information."""

    name: str
    address: str = ""
    country: str = "SE"  # ISO 3166-1 alpha-2

    def validate(self) -> List[str]:
        """Validera tillverkare."""
        errors: List[str] = []

        if not self.name:
            errors.append("Tillverkarens namn måste anges")
        if len(self.country) != 2:
            errors.append(
                "Landskod måste vara 2 tecken (ISO 3166-1)"
            )

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "name": self.name,
            "address": self.address,
            "country": self.country,
        }


@dataclass
class VehicleIdentification:
    """Fordonsidentifikation."""

    vin: str
    make: str  # Märke (t.ex. "Volvo", "Toyota")
    model: str  # Modell (t.ex. "XC90", "Corolla")
    variant: str = ""  # Variant (t.ex. "2.0 D5 AWD")
    version: str = ""  # Version (t.ex. "Inscription")

    def validate(self) -> List[str]:
        """Validera identifikation."""
        errors: List[str] = []

        # VIN
        is_valid, error = validate_vin(self.vin)
        if not is_valid:
            errors.append("VIN: %s" % error)

        # Märke
        if not self.make:
            errors.append("Märke måste anges")

        # Modell
        if not self.model:
            errors.append("Modell måste anges")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "vin": self.vin,
            "make": self.make,
            "model": self.model,
            "variant": self.variant,
            "version": self.version,
        }


@dataclass
class TechnicalData:
    """Tekniska data."""

    category: VehicleCategory = VehicleCategory.M1
    fuel_type: FuelType = FuelType.UNKNOWN
    engine_capacity_cc: Optional[int] = None  # Motorvolym (cm³)
    power_kw: Optional[float] = None  # Effekt (kW)
    power_hp: Optional[float] = None  # Effekt (hk)
    max_speed_kmh: Optional[int] = None  # Topphastighet (km/h)
    co2_emission_gkm: Optional[float] = None  # CO2-utsläpp (g/km)
    fuel_consumption_l100km: Optional[float] = None  # l/100km
    electric_range_km: Optional[int] = None  # Elräckvidd (km)

    def validate(self) -> List[str]:
        """Validera tekniska data."""
        errors: List[str] = []

        # Bränsletyp
        if self.fuel_type == FuelType.UNKNOWN:
            errors.append("Bränsletyp måste anges")

        # Motorvolym (om förbränningsmotor)
        if (
            self.fuel_type != FuelType.ELECTRIC
            and not self.engine_capacity_cc
        ):
            errors.append(
                "Motorvolym måste anges för förbränningsmotor"
            )

        # Effekt
        if not self.power_kw and not self.power_hp:
            errors.append("Effekt (kW eller hk) måste anges")

        # Konvertera kW ↔ hk om bara en finns (sidoeffekt i
        # valideringen — ger to_xml alltid båda värdena)
        if self.power_kw and not self.power_hp:
            self.power_hp = round(self.power_kw * 1.35962, 1)
        elif self.power_hp and not self.power_kw:
            self.power_kw = round(self.power_hp / 1.35962, 1)

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "category": self.category.value,
            "fuel_type": self.fuel_type.value,
            "engine_capacity_cc": self.engine_capacity_cc,
            "power_kw": self.power_kw,
            "power_hp": self.power_hp,
            "max_speed_kmh": self.max_speed_kmh,
            "co2_emission_gkm": self.co2_emission_gkm,
            "fuel_consumption_l100km": self.fuel_consumption_l100km,
            "electric_range_km": self.electric_range_km,
        }


@dataclass
class Dimensions:
    """Mått och vikter."""

    length_mm: Optional[int] = None
    width_mm: Optional[int] = None
    height_mm: Optional[int] = None
    wheelbase_mm: Optional[int] = None
    mass_in_service_kg: Optional[int] = None  # Tjänstevikt
    max_mass_kg: Optional[int] = None  # Maxvikt
    max_towing_mass_kg: Optional[int] = None  # Max släpvagnsvikt

    def validate(self) -> List[str]:
        """Validera dimensioner."""
        errors: List[str] = []

        # Tjänstevikt är obligatorisk
        if not self.mass_in_service_kg:
            errors.append("Tjänstevikt måste anges")

        # Maxvikt är obligatorisk
        if not self.max_mass_kg:
            errors.append("Maxvikt måste anges")

        # Logisk validering
        if self.mass_in_service_kg and self.max_mass_kg:
            if self.mass_in_service_kg > self.max_mass_kg:
                errors.append(
                    "Tjänstevikt kan inte vara större än maxvikt"
                )

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "length_mm": self.length_mm,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "wheelbase_mm": self.wheelbase_mm,
            "mass_in_service_kg": self.mass_in_service_kg,
            "max_mass_kg": self.max_mass_kg,
            "max_towing_mass_kg": self.max_towing_mass_kg,
        }


@dataclass
class TypeApproval:
    """Typgodkännande."""

    approval_number: str
    approval_date: str  # ISO 8601: YYYY-MM-DD
    issuing_authority: str = "Transportstyrelsen"
    issuing_country: str = "SE"

    def validate(self) -> List[str]:
        """Validera typgodkännande."""
        errors: List[str] = []

        # Godkännandenummer
        is_valid, error = validate_type_approval(
            self.approval_number
        )
        if not is_valid:
            errors.append("Typgodkännande: %s" % error)

        # Datum
        is_valid, error = validate_date(self.approval_date)
        if not is_valid:
            errors.append("Godkännandedatum: %s" % error)

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "approval_number": self.approval_number,
            "approval_date": self.approval_date,
            "issuing_authority": self.issuing_authority,
            "issuing_country": self.issuing_country,
        }


@dataclass
class Color:
    """Färginformation."""

    exterior_color: str
    exterior_color_code: str = ""
    interior_color: str = ""

    def validate(self) -> List[str]:
        """Validera färg."""
        errors: List[str] = []

        if not self.exterior_color:
            errors.append("Utvändig färg måste anges")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "exterior_color": self.exterior_color,
            "exterior_color_code": self.exterior_color_code,
            "interior_color": self.interior_color,
        }


@dataclass
class IVIDocument:
    """
    Komplett IVI-dokument (elektronisk CoC).

    Huvudklassen som representerar ett komplett elektroniskt
    registreringsbevis enligt EU-standard.
    """

    # Identifikation
    identification: VehicleIdentification

    # Tillverkare
    manufacturer: Manufacturer

    # Tekniska data
    technical_data: TechnicalData

    # Dimensioner
    dimensions: Dimensions

    # Typgodkännande
    type_approval: TypeApproval

    # Färg
    color: Color

    # Metadata
    document_id: str = field(
        default_factory=lambda: datetime.now().strftime(
            "IVI_%Y%m%d_%H%M%S"
        )
    )
    issue_date: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d")
    )
    status: IVIStatus = IVIStatus.DRAFT

    # Validation
    validation_errors: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)

    def validate(self) -> bool:
        """
        Validera hela IVI-dokumentet.

        Returns:
            True om giltigt, False annars
        """
        self.validation_errors.clear()
        self.validation_warnings.clear()

        # Validera alla komponenter
        self.validation_errors.extend(
            self.identification.validate()
        )
        self.validation_errors.extend(self.manufacturer.validate())
        self.validation_errors.extend(self.technical_data.validate())
        self.validation_errors.extend(self.dimensions.validate())
        self.validation_errors.extend(self.type_approval.validate())
        self.validation_errors.extend(self.color.validate())

        # Kontrollera document_id
        if not self.document_id:
            self.validation_errors.append("Dokument-ID måste anges")

        # Kontrollera issue_date
        is_valid, error = validate_date(self.issue_date)
        if not is_valid:
            self.validation_errors.append(
                "Utfärdandedatum: %s" % error
            )

        # Varningar (inte blockerande)
        if not self.technical_data.co2_emission_gkm:
            self.validation_warnings.append("CO2-utsläpp saknas")
        if not self.dimensions.length_mm:
            self.validation_warnings.append("Längd saknas")

        # Sätt status
        if self.validation_errors:
            self.status = IVIStatus.INVALID
            return False
        self.status = IVIStatus.VALID
        return True

    def to_dict(self) -> Dict[str, Any]:
        """
        Exportera som dict.

        Returns:
            Dict med all IVI-data
        """
        return {
            "document_id": self.document_id,
            "issue_date": self.issue_date,
            "status": self.status.value,
            "identification": self.identification.to_dict(),
            "manufacturer": self.manufacturer.to_dict(),
            "technical_data": self.technical_data.to_dict(),
            "dimensions": self.dimensions.to_dict(),
            "type_approval": self.type_approval.to_dict(),
            "color": self.color.to_dict(),
            "validation": {
                "is_valid": len(self.validation_errors) == 0,
                "errors": self.validation_errors.copy(),
                "warnings": self.validation_warnings.copy(),
            },
        }

    def to_xml(self) -> str:
        """
        Generera XML enligt IVI-standard.

        Returns:
            XML-sträng (pretty-printed)

        Raises:
            ValueError: Om dokumentet inte är giltigt
        """
        if not self.validate():
            raise ValueError(
                "Kan inte generera XML för ogiltigt IVI-dokument. "
                "Fel: %s" % ", ".join(self.validation_errors)
            )

        # Root element
        root = ET.Element("IVI", attrib={
            "xmlns": IVI_NAMESPACE,
            "version": IVI_SCHEMA_VERSION,
        })

        # Document metadata
        metadata = ET.SubElement(root, "Metadata")
        ET.SubElement(metadata, "DocumentID").text = (
            sanitize_xml_string(self.document_id)
        )
        ET.SubElement(metadata, "IssueDate").text = self.issue_date
        ET.SubElement(metadata, "IssuingAuthority").text = (
            sanitize_xml_string(
                self.type_approval.issuing_authority
            )
        )
        ET.SubElement(metadata, "IssuingCountry").text = (
            self.type_approval.issuing_country
        )

        # Vehicle Identification
        vehicle = ET.SubElement(root, "VehicleIdentification")
        ET.SubElement(vehicle, "VIN").text = (
            self.identification.vin.upper()
        )
        ET.SubElement(vehicle, "Make").text = sanitize_xml_string(
            self.identification.make
        )
        ET.SubElement(vehicle, "Model").text = sanitize_xml_string(
            self.identification.model
        )
        if self.identification.variant:
            ET.SubElement(vehicle, "Variant").text = (
                sanitize_xml_string(self.identification.variant)
            )
        if self.identification.version:
            ET.SubElement(vehicle, "Version").text = (
                sanitize_xml_string(self.identification.version)
            )

        # Manufacturer
        mfr = ET.SubElement(root, "Manufacturer")
        ET.SubElement(mfr, "Name").text = sanitize_xml_string(
            self.manufacturer.name
        )
        if self.manufacturer.address:
            ET.SubElement(mfr, "Address").text = (
                sanitize_xml_string(self.manufacturer.address)
            )
        ET.SubElement(mfr, "Country").text = (
            self.manufacturer.country
        )

        # Type Approval
        ta = ET.SubElement(root, "TypeApproval")
        ET.SubElement(ta, "ApprovalNumber").text = (
            sanitize_xml_string(self.type_approval.approval_number)
        )
        ET.SubElement(ta, "ApprovalDate").text = (
            self.type_approval.approval_date
        )

        # Technical Data
        tech = ET.SubElement(root, "TechnicalData")
        ET.SubElement(tech, "Category").text = (
            self.technical_data.category.value
        )
        ET.SubElement(tech, "FuelType").text = (
            self.technical_data.fuel_type.value
        )

        if self.technical_data.engine_capacity_cc:
            ET.SubElement(tech, "EngineCapacityCC").text = str(
                self.technical_data.engine_capacity_cc
            )
        if self.technical_data.power_kw:
            ET.SubElement(tech, "PowerKW").text = str(
                self.technical_data.power_kw
            )
        if self.technical_data.max_speed_kmh:
            ET.SubElement(tech, "MaxSpeedKmH").text = str(
                self.technical_data.max_speed_kmh
            )
        if self.technical_data.co2_emission_gkm:
            ET.SubElement(tech, "CO2EmissionGKm").text = str(
                self.technical_data.co2_emission_gkm
            )
        if self.technical_data.fuel_consumption_l100km:
            ET.SubElement(tech, "FuelConsumptionL100Km").text = str(
                self.technical_data.fuel_consumption_l100km
            )
        if self.technical_data.electric_range_km:
            ET.SubElement(tech, "ElectricRangeKm").text = str(
                self.technical_data.electric_range_km
            )

        # Dimensions
        dim = ET.SubElement(root, "Dimensions")
        if self.dimensions.length_mm:
            ET.SubElement(dim, "LengthMM").text = str(
                self.dimensions.length_mm
            )
        if self.dimensions.width_mm:
            ET.SubElement(dim, "WidthMM").text = str(
                self.dimensions.width_mm
            )
        if self.dimensions.height_mm:
            ET.SubElement(dim, "HeightMM").text = str(
                self.dimensions.height_mm
            )
        if self.dimensions.wheelbase_mm:
            ET.SubElement(dim, "WheelbaseMM").text = str(
                self.dimensions.wheelbase_mm
            )

        ET.SubElement(dim, "MassInServiceKG").text = str(
            self.dimensions.mass_in_service_kg
        )
        ET.SubElement(dim, "MaxMassKG").text = str(
            self.dimensions.max_mass_kg
        )
        if self.dimensions.max_towing_mass_kg:
            ET.SubElement(dim, "MaxTowingMassKG").text = str(
                self.dimensions.max_towing_mass_kg
            )

        # Color
        color_elem = ET.SubElement(root, "Color")
        ET.SubElement(color_elem, "ExteriorColor").text = (
            sanitize_xml_string(self.color.exterior_color)
        )
        if self.color.exterior_color_code:
            ET.SubElement(color_elem, "ExteriorColorCode").text = (
                sanitize_xml_string(self.color.exterior_color_code)
            )
        if self.color.interior_color:
            ET.SubElement(color_elem, "InteriorColor").text = (
                sanitize_xml_string(self.color.interior_color)
            )

        # Pretty-print XML
        xml_string = ET.tostring(
            root, encoding=IVI_ENCODING, method="xml"
        )
        dom = minidom.parseString(xml_string)
        return dom.toprettyxml(
            indent="  ", encoding=IVI_ENCODING
        ).decode(IVI_ENCODING)

    def save_xml(self, filepath: Path) -> None:
        """
        Spara XML till fil (atomisk skrivning).

        Args:
            filepath: Sökväg där XML ska sparas

        Raises:
            ValueError: Om dokumentet inte är giltigt
        """
        xml_content = self.to_xml()
        _atomic_write_text(Path(filepath), xml_content)
        _log.info("IVI XML sparad: %s", filepath)

    @classmethod
    def from_vehicle_data(
        cls,
        vehicle_data: Dict[str, Any],
        manufacturer_data: Optional[Dict[str, Any]] = None,
        type_approval_data: Optional[Dict[str, Any]] = None,
    ) -> IVIDocument:
        """
        Skapa IVI-dokument från fordonsdata.

        Args:
            vehicle_data: Dict med fordonsdata (från
                vehicle_registry/SAP/dispatch)
            manufacturer_data: Dict med tillverkardata (optional)
            type_approval_data: Dict med typgodkännandedata
                (optional)

        Returns:
            IVIDocument

        Exempel:
            vehicle_data = {
                "vin": "YV1LSXXXXX1234567",
                "make": "Volvo",
                "model": "XC90",
                "variant": "2.0 D5 AWD",
                "fuel_type": "Diesel",
                "power_kw": 173,
                "mass_kg": 2100,
                "max_mass_kg": 2650,
                "exterior_color": "Svart",
                ...
            }
        """
        # Identification
        identification = VehicleIdentification(
            vin=vehicle_data.get("vin", ""),
            make=vehicle_data.get(
                "make", vehicle_data.get("marke", "")
            ),
            model=vehicle_data.get(
                "model", vehicle_data.get("modell", "")
            ),
            variant=vehicle_data.get(
                "variant", vehicle_data.get("variant_version", "")
            ),
            version=vehicle_data.get("version", ""),
        )

        # Manufacturer
        if manufacturer_data:
            manufacturer = Manufacturer(
                name=manufacturer_data.get("name", ""),
                address=manufacturer_data.get("address", ""),
                country=manufacturer_data.get("country", "SE"),
            )
        else:
            # Default från fordonsdata
            manufacturer = Manufacturer(
                name=vehicle_data.get(
                    "manufacturer_name", identification.make
                ),
                address="",
                country="SE",
            )

        # Technical Data
        fuel_str = vehicle_data.get(
            "fuel_type", vehicle_data.get("bransle", "")
        )
        technical_data = TechnicalData(
            category=VehicleCategory.from_string(
                vehicle_data.get("category", "M1")
            ),
            fuel_type=FuelType.from_string(fuel_str),
            engine_capacity_cc=vehicle_data.get(
                "engine_capacity_cc",
                vehicle_data.get("slagvolym"),
            ),
            power_kw=vehicle_data.get(
                "power_kw", vehicle_data.get("effekt_kw")
            ),
            power_hp=vehicle_data.get(
                "power_hp", vehicle_data.get("effekt_hk")
            ),
            max_speed_kmh=vehicle_data.get("max_speed_kmh"),
            co2_emission_gkm=vehicle_data.get("co2_emission"),
            fuel_consumption_l100km=vehicle_data.get(
                "fuel_consumption"
            ),
            electric_range_km=vehicle_data.get("electric_range"),
        )

        # Dimensions
        dimensions = Dimensions(
            length_mm=vehicle_data.get("length_mm"),
            width_mm=vehicle_data.get("width_mm"),
            height_mm=vehicle_data.get("height_mm"),
            wheelbase_mm=vehicle_data.get("wheelbase_mm"),
            mass_in_service_kg=vehicle_data.get(
                "mass_kg", vehicle_data.get("tjanstevikt")
            ),
            max_mass_kg=vehicle_data.get(
                "max_mass_kg", vehicle_data.get("totalvikt")
            ),
            max_towing_mass_kg=vehicle_data.get(
                "max_towing_mass_kg"
            ),
        )

        # Type Approval
        if type_approval_data:
            type_approval = TypeApproval(
                approval_number=type_approval_data.get(
                    "approval_number", ""
                ),
                approval_date=type_approval_data.get(
                    "approval_date", ""
                ),
                issuing_authority=type_approval_data.get(
                    "issuing_authority", "Transportstyrelsen"
                ),
                issuing_country=type_approval_data.get(
                    "issuing_country", "SE"
                ),
            )
        else:
            # Default/placeholder
            type_approval = TypeApproval(
                approval_number=vehicle_data.get(
                    "type_approval", "e1*2018/858*00000*00"
                ),
                approval_date=vehicle_data.get(
                    "approval_date",
                    datetime.now().strftime("%Y-%m-%d"),
                ),
            )

        # Color
        color = Color(
            exterior_color=vehicle_data.get(
                "exterior_color", vehicle_data.get("farg", "")
            ),
            exterior_color_code=vehicle_data.get("color_code", ""),
            interior_color=vehicle_data.get("interior_color", ""),
        )

        return cls(
            identification=identification,
            manufacturer=manufacturer,
            technical_data=technical_data,
            dimensions=dimensions,
            type_approval=type_approval,
            color=color,
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Constants
    "VERSION",
    "AUTHOR",
    "IVI_NAMESPACE",
    "IVI_SCHEMA_VERSION",
    "IVI_ENCODING",
    "VIN_LENGTH",
    # Copyright
    "get_copyright_year",
    "get_copyright_string",
    # Enums
    "FuelType",
    "VehicleCategory",
    "IVIStatus",
    # Validation
    "validate_vin",
    "validate_date",
    "validate_type_approval",
    "sanitize_xml_string",
    # Data classes
    "Manufacturer",
    "VehicleIdentification",
    "TechnicalData",
    "Dimensions",
    "TypeApproval",
    "Color",
    "IVIDocument",
]
