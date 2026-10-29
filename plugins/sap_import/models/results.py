# -*- coding: utf-8 -*-
# plugins/sap_import/models/results.py

"""
Datamodeller för SAP Import resultat (v2.1.0).

Detta modul innehåller alla dataklasser som används för att representera:
    - Fordonsdata (VehicleData)
    - Importresultat per blad (ProcessedSheet)
    - Importresultat per fil (ProcessedFile)
    - Sammanfattning av hela importen (ImportSummary)

Uppdaterad för fordonsdata-import med stöd för:
    - 32 target fields enligt specifikation
    - Import från data/vehicles/ och data/sap/
    - Bättre validering och normalisering
    - Kompatibilitet med vehicle_registry och ts_spec_import
    - Atomisk skrivning och checksum-stöd

Se även:
    - plugins/sap_import/plugin.py
    - plugins/vehicle_registry/plugin.py
    - plugins/ts_spec_import/plugin.py
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# FORDONSDATA
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class VehicleData:
    """
    Fordonsdata från SAP/Dispatch/Excel.

    Detta är kärnmodellen för importerad fordonsdata.
    Mappas mot de 32 gällande TS-fälten vid generering av PT45.

    Attributes:
        vin: VIN-nummer (17 tecken, normaliserat)
        model_year: Årsmodell (YYYY-format)
        type: Fordonstyp
        variante: Variant
        version: Version
        modelname: Modellnamn
        comname: Handelsbeteckning
        class_: Fordonsklass
        vehcat2: Fordonskategori 2
        approval: ETG-nummer / WVTA-godkännande
        dateapp: Godkännandedatum
        numaxle: Antal axlar
        numwheel: Antal hjul
        antilbs: ABS (ja/nej)
        length: Längd (mm)
        width: Bredd (mm)
        height: Höjd (mm)
        mass: Totalvikt (kg)
        ladenmass: Tjänstevikt (kg)
        cylcapacity: Slagvolym (cc)
        maxpower: Max effekt (kW)
        maxnet: Max nettoeffekt (kW)
        speed: Maxhastighet (km/h)
        tyresize1: Däckstorlek fram
        tyresize2: Däckstorlek bak
        seats: Antal sittplatser
        emislvl: Utsläppsnivå
        stationary: Ljudnivå stillastående (dB)
        stateng: Ljudnivå stationär motor (dB)
        driveby: Ljudnivå körning (dB)
        emstage: Euro-steg
        eeco2e: CO2-utsläpp (g/km)

        # Metadata
        source_file: Ursprungsfil
        source_sheet: Excel-blad
        import_timestamp: När data importerades
        extra: Dict med fält som inte matchas av standardmodellen
    """

    # === Huvudfält (32 target fields) ===
    vin: str
    model_year: str = ""
    type: str = ""
    variante: str = ""
    version: str = ""
    modelname: str = ""
    comname: str = ""
    class_: str = ""
    vehcat2: str = ""
    approval: str = ""
    dateapp: str = ""
    numaxle: str = ""
    numwheel: str = ""
    antilbs: str = ""
    length: str = ""
    width: str = ""
    height: str = ""
    mass: str = ""
    ladenmass: str = ""
    cylcapacity: str = ""
    maxpower: str = ""
    maxnet: str = ""
    speed: str = ""
    tyresize1: str = ""
    tyresize2: str = ""
    seats: str = ""
    emislvl: str = ""
    stationary: str = ""
    stateng: str = ""
    driveby: str = ""
    emstage: str = ""
    eeco2e: str = ""

    # === Metadata ===
    source_file: str = ""
    source_sheet: str = ""
    import_timestamp: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Post-init validering och initiering."""
        if not self.import_timestamp:
            self.import_timestamp = datetime.now().isoformat()

    @property
    def is_complete(self) -> bool:
        """Kontrollera om data är komplett för registrering."""
        return bool(self.vin and self.model_year)

    @property
    def year(self) -> Optional[int]:
        """Årsmodell som int."""
        try:
            return int(self.model_year) if self.model_year else None
        except (ValueError, TypeError):
            return None

    @property
    def vin3(self) -> str:
        """Returnerar de tre första tecknen i VIN (WMI + första siffran)."""
        return self.vin[:3] if len(self.vin) >= 3 else ""

    def to_dict(self) -> Dict[str, Any]:
        """
        Konvertera till dict.

        Används för:
            - JSON-serialisering
            - Mappning till TS-specifikationer
            - Event-payloads
            - vehicle_registry upsert
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VehicleData':
        """
        Skapa från dict.

        Hanterar extra fält som inte finns i dataclass-definitionen.
        Detta är viktigt när data kommer från äldre JSON-filer.
        """
        known_fields = set(cls.__dataclass_fields__.keys())
        known = {k: v for k, v in data.items() if k in known_fields}
        extra = {k: v for k, v in data.items() if k not in known_fields and k != 'extra'}

        if 'extra' in data and isinstance(data['extra'], dict):
            extra.update(data['extra'])

        known['extra'] = extra
        return cls(**known)

    def matches(
        self,
        vin: Optional[str] = None,
        year: Optional[str] = None,
        approval: Optional[str] = None
    ) -> bool:
        """
        Kontrollera om fordonet matchar sökkriterier.

        Används av vehicle_registry för matchning.

        Args:
            vin: VIN att matcha (case-insensitive)
            year: Årsmodell att matcha
            approval: ETG-nummer att matcha (case-insensitive)

        Returns:
            True om alla angivna kriterier matchar
        """
        if vin and self.vin.upper() != vin.upper():
            return False
        if year and self.model_year != year:
            return False
        if approval and self.approval.upper() != approval.upper():
            return False
        return True

    def to_ts_field_mapping(self) -> Dict[str, str]:
        """
        Konvertera till mappning för TS-fält.

        Används av vehicle_registration_post för att generera PT45.

        Returns:
            Dict med fältnamn från TS-spec -> värde
        """
        return {
            "VIN": self.vin,
            "ARSMODELL": self.model_year,
            "GODKANNANDENUMMER": self.approval,
            "FARGKOD": getattr(self, 'color_code', self.extra.get('color_code', '')),
            "MOTOR": getattr(self, 'engine', self.extra.get('engine', '')),
            "VARIANT": getattr(self, 'variant', self.extra.get('variant', '')),
            "TOTALVIKT": self.mass,
            "PRODUKTIONSDATUM": getattr(self, 'production_date', self.extra.get('production_date', '')),
            "FAKTURADATUM": getattr(self, 'invoice_date', self.extra.get('invoice_date', '')),
        }

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validera fordonsdata.

        Returns:
            (is_valid, errors)
        """
        errors = []

        if not self.vin:
            errors.append("VIN saknas")
        elif len(self.vin) != 17:
            errors.append(f"Felaktig VIN-längd: {len(self.vin)} (förväntat 17)")

        if self.model_year and not self.model_year.isdigit():
            errors.append(f"Ogiltigt modellår: {self.model_year}")

        return len(errors) == 0, errors

    def __repr__(self) -> str:
        """Kort representation."""
        return f"VehicleData(vin={self.vin}, year={self.model_year}, approval={self.approval[:20]}...)"

    def __hash__(self) -> int:
        """Hash baserat på VIN."""
        return hash(self.vin)

    def __eq__(self, other: Any) -> bool:
        """Likhet baserat på VIN."""
        if not isinstance(other, VehicleData):
            return False
        return self.vin == other.vin


# ══════════════════════════════════════════════════════════════════════════════
# IMPORT-RESULTAT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProcessedSheet:
    """
    Resultat från bearbetning av ett Excel-blad.

    Används för:
        - Progress-uppdateringar i GUI
        - Loggning
        - Felsökning
        - Statistik
    """
    name: str
    imported_rows: int = 0
    skipped_rows: int = 0
    skipped_vins: List[str] = field(default_factory=list)
    skipped_reason: str = ""
    columns_found: List[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def is_success(self) -> bool:
        """Kontrollera om bladet importerades framgångsrikt."""
        return self.imported_rows > 0 and not self.skipped_reason

    @property
    def skipped_count(self) -> int:
        """Antal skippade VIN."""
        return len(self.skipped_vins)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "name": self.name,
            "imported_rows": self.imported_rows,
            "skipped_rows": self.skipped_rows,
            "skipped_vins": len(self.skipped_vins),
            "skipped_reason": self.skipped_reason,
            "columns_found": self.columns_found,
            "duration_ms": self.duration_ms,
            "success": self.is_success,
        }

    def summary(self) -> str:
        """Enrads-sammanfattning."""
        if self.skipped_reason:
            return f"{self.name}: {self.skipped_reason}"
        return f"{self.name}: {self.imported_rows} importerade, {self.skipped_count} skippade"


@dataclass
class ProcessedFile:
    """
    Resultat från bearbetning av en Excel-fil.

    Aggregerar resultat från alla blad i filen.
    """
    filename: str
    full_path: str
    sheets: List[ProcessedSheet] = field(default_factory=list)
    imported_rows: int = 0
    error: str = ""
    duration_ms: float = 0.0
    checksum: str = ""
    processed_at: str = ""

    def __post_init__(self):
        """Post-init."""
        if not self.processed_at:
            self.processed_at = datetime.now().isoformat()

    @property
    def is_success(self) -> bool:
        """Kontrollera om filen importerades framgångsrikt."""
        return not self.error and self.imported_rows > 0

    @property
    def total_skipped_vins(self) -> int:
        """Totalt antal skippade VIN från alla blad."""
        return sum(len(s.skipped_vins) for s in self.sheets)

    @property
    def successful_sheets(self) -> List[ProcessedSheet]:
        """Lista med framgångsrikt importerade blad."""
        return [s for s in self.sheets if s.is_success]

    @property
    def failed_sheets(self) -> List[ProcessedSheet]:
        """Lista med misslyckade blad."""
        return [s for s in self.sheets if not s.is_success]

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "filename": self.filename,
            "full_path": self.full_path,
            "imported_rows": self.imported_rows,
            "total_skipped_vins": self.total_skipped_vins,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "checksum": self.checksum,
            "processed_at": self.processed_at,
            "success": self.is_success,
            "sheets": [s.to_dict() for s in self.sheets],
        }

    def summary(self) -> str:
        """Enrads-sammanfattning."""
        if self.error:
            return f"{self.filename}: ❌ {self.error}"
        success_count = len(self.successful_sheets)
        total_count = len(self.sheets)
        return (
            f"{self.filename}: ✅ {self.imported_rows} importerade, "
            f"{self.total_skipped_vins} skippade ({success_count}/{total_count} blad)"
        )


@dataclass
class ImportSummary:
    """
    Sammanfattning av en komplett import-körning.

    Aggregerar resultat från alla filer.

    Används för:
        - Slutrapport i GUI
        - JSON-export till ut/
        - Event-payload vid import_complete
        - Statistik och loggning
    """
    total_imported: int = 0
    total_skipped: int = 0
    processed_files: List[ProcessedFile] = field(default_factory=list)
    failed_files: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: str = ""
    plugin_version: str = ""
    config_snapshot: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Post-init."""
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def is_success(self) -> bool:
        """Kontrollera om importen lyckades övergripande."""
        return len(self.failed_files) == 0 and self.total_imported > 0

    @property
    def total_files_processed(self) -> int:
        """Totalt antal filer processade."""
        return len(self.processed_files)

    @property
    def successful_files(self) -> List[ProcessedFile]:
        """Lista med framgångsrikt importerade filer."""
        return [f for f in self.processed_files if f.is_success]

    @property
    def total_vins_imported(self) -> int:
        """Alias för total_imported (tydligare)."""
        return self.total_imported

    def get_all_skipped_vins(self) -> Set[str]:
        """Hämta alla skippade VIN från alla filer."""
        all_vins = set()
        for file in self.processed_files:
            for sheet in file.sheets:
                all_vins.update(sheet.skipped_vins)
        return all_vins

    def to_dict(self) -> Dict[str, Any]:
        """
        Konvertera till dict.

        Används för JSON-export och event-payloads.
        """
        return {
            "timestamp": self.timestamp,
            "plugin_version": self.plugin_version,
            "total_imported": self.total_imported,
            "total_skipped": self.total_skipped,
            "duration_ms": self.duration_ms,
            "duration_seconds": round(self.duration_ms / 1000, 2),
            "files_processed": self.total_files_processed,
            "files_successful": len(self.successful_files),
            "files_failed": len(self.failed_files),
            "success": self.is_success,
            "failed_files": self.failed_files,
            "config": self.config_snapshot,
            "files": [f.to_dict() for f in self.processed_files],
        }

    def to_json(self, indent: int = 2) -> str:
        """
        Konvertera till JSON-sträng.

        Används för att spara till fil.
        """
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def summary(self) -> str:
        """
        Flerlinje-sammanfattning för konsol/GUI.
        """
        icon = "✅" if self.is_success else "❌"
        lines = [
            "═" * 60,
            f"{icon} SAP IMPORT SAMMANFATTNING",
            "═" * 60,
            f"  Tidpunkt: {self.timestamp}",
            f"  Varaktighet: {self.duration_ms / 1000:.1f}s",
            "",
            f"  📊 Resultat:",
            f"     • Filer bearbetade: {self.total_files_processed}",
            f"     • Framgångsrika: {len(self.successful_files)}",
            f"     • Misslyckade: {len(self.failed_files)}",
            "",
            f"  🚗 Fordon:",
            f"     • Importerade: {self.total_imported}",
            f"     • Skippade (duplicat): {self.total_skipped}",
        ]
        if self.failed_files:
            lines.extend([
                "",
                f"  ❌ Misslyckade filer:",
            ])
            for failed in self.failed_files[:5]:
                lines.append(f"     • {failed}")
            if len(self.failed_files) > 5:
                lines.append(f"     • ... och {len(self.failed_files) - 5} till")
        lines.append("═" * 60)
        return "\n".join(lines)

    def short_summary(self) -> str:
        """
        Kort sammanfattning (en rad).

        Används för statusmeddelanden.
        """
        icon = "✅" if self.is_success else "❌"
        return (
            f"{icon} {self.total_imported} importerade, "
            f"{self.total_skipped} skippade, "
            f"{len(self.failed_files)} fel"
        )

    def add_file_result(self, file_result: ProcessedFile) -> None:
        """
        Lägg till filresultat och uppdatera totaler.

        Används internt under import-loopen.
        """
        self.processed_files.append(file_result)
        self.total_imported += file_result.imported_rows
        self.total_skipped += file_result.total_skipped_vins
        if file_result.error:
            self.failed_files.append(f"{file_result.filename}: {file_result.error}")

    def __repr__(self) -> str:
        """Kort representation."""
        return (
            f"ImportSummary(imported={self.total_imported}, "
            f"skipped={self.total_skipped}, "
            f"files={self.total_files_processed}, "
            f"success={self.is_success})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "VehicleData",
    "ProcessedSheet",
    "ProcessedFile",
    "ImportSummary",
]