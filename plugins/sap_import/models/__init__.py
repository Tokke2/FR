# -*- coding: utf-8 -*-
# plugins/sap_import/models/__init__.py

"""
Datamodeller för SAP Import Plugin (v2.1.0).

Detta package innehåller alla dataklasser som används för att representera
resultat från import av fordonsdata från SAP/Dispatch-excel-filer.

Huvudklasser:
    - VehicleData          : Representerar ett enskilt fordon
    - ProcessedSheet       : Resultat från ett specifikt Excel-blad
    - ProcessedFile        : Resultat från en hel Excel-fil
    - ImportSummary        : Sammanfattning av en komplett importkörning

Detta modul tillhandahåller även ett antal convenience-funktioner för att
arbeta med listor av VehicleData-objekt, skapa instanser, slå samman
sammanfattningar, filtrera, gruppera och beräkna statistik.

Användningsexempel:

    >>> from plugins.sap_import.models import (
    ...     VehicleData, ImportSummary, create_vehicle,
    ...     create_summary, get_statistics
    ... )
    >>>
    >>> # Skapa ett fordon
    >>> vehicle = create_vehicle(
    ...     vin="WVWZZZ1KZ12345678",
    ...     model_year="2024",
    ...     approval="e1*2001/116*1234"
    ... )
    >>>
    >>> # Skapa en sammanfattning
    >>> summary = create_summary(total_imported=150, total_skipped=12)
    >>> print(summary.short_summary())
    '✅ 150 importerade, 12 skippade, 0 fel'
    >>>
    >>> # Beräkna statistik
    >>> stats = get_statistics([vehicle])
    >>> print(stats['total_vehicles'])
    1

Se även:
    - plugins/sap_import/plugin.py
    - plugins/sap_import/core/data_normalizer.py
    - plugins/vehicle_registry/plugin.py
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional

# Resultatmodeller
from .results import (
    VehicleData,
    ProcessedSheet,
    ProcessedFile,
    ImportSummary,
)

# Re-export för bakåtkompatibilitet
__all__ = [
    # Huvudklasser
    "VehicleData",
    "ProcessedSheet",
    "ProcessedFile",
    "ImportSummary",
    
    # Convenience-funktioner
    "create_vehicle",
    "create_summary",
    "merge_summaries",
    "vehicles_to_dict_list",
    "dict_list_to_vehicles",
    "filter_by_year",
    "filter_by_approval",
    "group_by_year",
    "get_unique_vins",
    "get_statistics",
]

__version__ = "2.1.0"


# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def create_vehicle(
    vin: str,
    model_year: str = "",
    approval: str = "",
    **kwargs
) -> VehicleData:
    """
    Factory-funktion för att skapa VehicleData.

    Detta är ett bekvämt sätt att skapa VehicleData-instanser utan att
    behöva ange alla parametrar explicit.

    Args:
        vin: VIN-nummer (17 tecken)
        model_year: Årsmodell (t.ex. "2024")
        approval: ETG-nummer / WVTA-godkännande
        **kwargs: Övriga fält (color_code, engine, variant, etc.)

    Returns:
        VehicleData-instans

    Example:
        >>> vehicle = create_vehicle(
        ...     vin="WVWZZZ1KZ12345678",
        ...     model_year="2024",
        ...     approval="e1*2001/116*1234",
        ...     color_code="L041",
        ...     engine="B48"
        ... )
    """
    return VehicleData(
        vin=vin,
        model_year=model_year,
        approval=approval,
        **kwargs
    )


def create_summary(
    processed_files: list = None,
    total_imported: int = 0,
    total_skipped: int = 0,
    **kwargs
) -> ImportSummary:
    """
    Factory-funktion för att skapa ImportSummary.

    Args:
        processed_files: Lista med ProcessedFile-objekt
        total_imported: Totalt antal importerade fordon
        total_skipped: Totalt antal skippade fordon (duplicat etc.)
        **kwargs: Övriga fält (plugin_version, config_snapshot, etc.)

    Returns:
        ImportSummary-instans

    Example:
        >>> summary = create_summary(
        ...     total_imported=150,
        ...     total_skipped=25,
        ...     plugin_version="4.1.0"
        ... )
    """
    return ImportSummary(
        processed_files=processed_files or [],
        total_imported=total_imported,
        total_skipped=total_skipped,
        **kwargs
    )


def merge_summaries(summaries: List[ImportSummary]) -> ImportSummary:
    """
    Slå samman flera ImportSummary till en enda.

    Användbart vid batch-import, parallel processing eller när man vill
    kombinera resultat från flera körningar.

    Args:
        summaries: Lista med ImportSummary-objekt

    Returns:
        Sammanslagen ImportSummary
    """
    if not summaries:
        return ImportSummary()

    merged = ImportSummary()

    for s in summaries:
        merged.total_imported += s.total_imported
        merged.total_skipped += s.total_skipped
        merged.processed_files.extend(s.processed_files)
        merged.failed_files.extend(s.failed_files)
        merged.duration_ms += s.duration_ms

    # Använd tidigaste timestamp
    timestamps = [s.timestamp for s in summaries if s.timestamp]
    if timestamps:
        merged.timestamp = min(timestamps)

    return merged


def vehicles_to_dict_list(vehicles: List[VehicleData]) -> List[Dict[str, Any]]:
    """
    Konvertera lista med VehicleData till lista med dict.

    Användbart för JSON-serialisering eller konvertering till pandas DataFrame.

    Args:
        vehicles: Lista med VehicleData

    Returns:
        Lista med dict-representationer
    """
    return [v.to_dict() for v in vehicles]


def dict_list_to_vehicles(dict_list: List[Dict[str, Any]]) -> List[VehicleData]:
    """
    Konvertera lista med dict till lista med VehicleData.

    Användbart när data laddas från JSON-filer.

    Args:
        dict_list: Lista med dict-representationer

    Returns:
        Lista med VehicleData-instanser
    """
    return [VehicleData.from_dict(d) for d in dict_list]


def filter_by_year(vehicles: List[VehicleData], year: str) -> List[VehicleData]:
    """
    Filtrera fordon på årsmodell.

    Args:
        vehicles: Lista med VehicleData
        year: Årsmodell att filtrera på (t.ex. "2024")

    Returns:
        Filtrerad lista
    """
    return [v for v in vehicles if v.model_year == year]


def filter_by_approval(vehicles: List[VehicleData], approval: str) -> List[VehicleData]:
    """
    Filtrera fordon på ETG-nummer.

    Args:
        vehicles: Lista med VehicleData
        approval: ETG-nummer att filtrera på (case-insensitive)

    Returns:
        Filtrerad lista
    """
    approval_upper = approval.upper()
    return [v for v in vehicles if v.approval.upper() == approval_upper]


def group_by_year(vehicles: List[VehicleData]) -> Dict[str, List[VehicleData]]:
    """
    Gruppera fordon per årsmodell.

    Args:
        vehicles: Lista med VehicleData

    Returns:
        Dict med year -> lista med VehicleData
    """
    grouped: Dict[str, List[VehicleData]] = {}
    for v in vehicles:
        year = v.model_year or "unknown"
        grouped.setdefault(year, []).append(v)
    return grouped


def get_unique_vins(vehicles: List[VehicleData]) -> set:
    """
    Hämta unika VIN-nummer från fordonslista.

    Args:
        vehicles: Lista med VehicleData

    Returns:
        Set med unika VIN-nummer
    """
    return {v.vin for v in vehicles if v.vin}


def get_statistics(vehicles: List[VehicleData]) -> Dict[str, Any]:
    """
    Beräkna statistik för en lista med fordon.

    Args:
        vehicles: Lista med VehicleData

    Returns:
        Dict med statistik (total_vehicles, unique_vins, years, etc.)
    """
    if not vehicles:
        return {
            "total_vehicles": 0,
            "unique_vins": 0,
            "years": [],
            "vehicles_per_year": {},
            "complete_records": 0,
            "completion_rate": 0.0,
        }

    grouped = group_by_year(vehicles)
    unique_vins = get_unique_vins(vehicles)
    complete = sum(1 for v in vehicles if v.is_complete)

    return {
        "total_vehicles": len(vehicles),
        "unique_vins": len(unique_vins),
        "years": sorted(grouped.keys()),
        "vehicles_per_year": {y: len(vs) for y, vs in grouped.items()},
        "complete_records": complete,
        "completion_rate": round(complete / len(vehicles) * 100, 1) if vehicles else 0.0,
    }