"""Snabbfilter och summefält för fordonslistan (förslag 9 och 10).

Filtren svarar på den vanligaste frågan i ett register: *vilka rader är det fel
på?* De bygger enbart på fält som redan finns i årsfilerna och hittar aldrig på
egna värden. Ett filter som kräver ett fält som inte finns ger noll träffar i
stället för en gissning.

Modulen är Qt-oberoende och kan därför testas direkt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Final, Iterable, Sequence

# Fältnamn som används i årsfilerna. Listan är uttrycklig: okända fält
# behandlas som tomma, aldrig som giltiga.
VIN_FIELDS: Final[tuple[str, ...]] = ("vin_kod", "vin", "VIN")
# Godkännandenummer sparas under något av dessa namn beroende på importväg.
APPROVAL_FIELDS: Final[tuple[str, ...]] = (
    "godkannandenummer", "approval_number", "approval", "avgaskrav_tillagg",
)
COLOR_FIELDS: Final[tuple[str, ...]] = ("farg_kod", "farg", "color_code", "kulor")
DEALER_FIELDS: Final[tuple[str, ...]] = ("aterforsaljare", "dealer", "handlare")
MODEL_FIELDS: Final[tuple[str, ...]] = ("modell", "model")


def _first(vehicle: dict[str, Any], fields: Sequence[str]) -> str:
    for field in fields:
        value = vehicle.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def vin(vehicle: dict[str, Any]) -> str:
    return _first(vehicle, VIN_FIELDS).upper()


def approval(vehicle: dict[str, Any]) -> str:
    return _first(vehicle, APPROVAL_FIELDS)


def color(vehicle: dict[str, Any]) -> str:
    return _first(vehicle, COLOR_FIELDS)


def dealer(vehicle: dict[str, Any]) -> str:
    return _first(vehicle, DEALER_FIELDS)


def model(vehicle: dict[str, Any]) -> str:
    return _first(vehicle, MODEL_FIELDS)


def missing_fields(vehicle: dict[str, Any]) -> list[str]:
    """Namnge de obligatoriska uppgifter som saknas, på svenska."""
    missing = []
    if not vin(vehicle):
        missing.append("VIN-kod")
    if not approval(vehicle):
        missing.append("Godkännandenummer")
    if not color(vehicle):
        missing.append("Färg")
    return missing


def is_incomplete(vehicle: dict[str, Any]) -> bool:
    return bool(missing_fields(vehicle))


def is_complete(vehicle: dict[str, Any]) -> bool:
    return not missing_fields(vehicle)


def missing_color(vehicle: dict[str, Any]) -> bool:
    return not color(vehicle)


def missing_approval(vehicle: dict[str, Any]) -> bool:
    return not approval(vehicle)


def missing_dealer(vehicle: dict[str, Any]) -> bool:
    return not dealer(vehicle)


def empty_row(vehicle: dict[str, Any]) -> bool:
    """En helt tom rad ska kunna filtreras bort utan att räknas som fel."""
    return not any(str(value).strip() for value in vehicle.values() if value is not None)


@dataclass(frozen=True)
class QuickFilter:
    """Ett filterchip ovanför tabellen."""

    key: str
    label: str
    predicate: Callable[[dict[str, Any]], bool]
    description: str = ""


QUICK_FILTERS: Final[tuple[QuickFilter, ...]] = (
    QuickFilter("incomplete", "Ofullständiga", is_incomplete,
                "Rader som saknar VIN-kod, godkännandenummer eller färg"),
    QuickFilter("no_color", "Saknar färg", missing_color,
                "Rader där färgkoden är tom"),
    QuickFilter("no_approval", "Saknar approval", missing_approval,
                "Rader där godkännandenumret är tomt"),
    QuickFilter("no_dealer", "Saknar återförsäljare", missing_dealer,
                "Rader där återförsäljaren är tom"),
    QuickFilter("complete", "Fullständiga", is_complete,
                "Rader där alla obligatoriska uppgifter finns"),
)

FILTERS_BY_KEY: Final[dict[str, QuickFilter]] = {item.key: item for item in QUICK_FILTERS}


def filter_keys() -> list[str]:
    return [item.key for item in QUICK_FILTERS]


def apply_filters(vehicles: Iterable[dict[str, Any]], keys: Iterable[str] = (),
                  text: str = "") -> list[dict[str, Any]]:
    """Filtrera rader på valda chip och en fritext.

    Flera chip kombineras med **och**, eftersom de beskriver olika fel. Okända
    nycklar ignoreras. Fritexten jämförs mot VIN, modell, färg, återförsäljare
    och godkännandenummer, utan att skilja på versaler.
    """
    chosen = [FILTERS_BY_KEY[key] for key in keys if key in FILTERS_BY_KEY]
    needle = str(text or "").strip().casefold()
    result = []
    for vehicle in vehicles:
        if not isinstance(vehicle, dict):
            continue
        if any(not chosen_filter.predicate(vehicle) for chosen_filter in chosen):
            continue
        if needle:
            haystack = " ".join((vin(vehicle), model(vehicle), color(vehicle),
                                 dealer(vehicle), approval(vehicle))).casefold()
            if needle not in haystack:
                continue
        result.append(vehicle)
    return result


def summary(vehicles: Iterable[dict[str, Any]], selected: int = 0) -> dict[str, int]:
    """Siffrorna under tabellen (förslag 10).

    Räknar rader, fullständiga, ofullständiga och antal med respektive fel.
    ``selected`` är antalet markerade rader, som vyn själv håller reda på.
    """
    rows = [vehicle for vehicle in vehicles if isinstance(vehicle, dict)]
    complete = sum(1 for vehicle in rows if is_complete(vehicle))
    return {
        "rows": len(rows),
        "complete": complete,
        "incomplete": len(rows) - complete,
        "no_color": sum(1 for vehicle in rows if missing_color(vehicle)),
        "no_approval": sum(1 for vehicle in rows if missing_approval(vehicle)),
        "no_dealer": sum(1 for vehicle in rows if missing_dealer(vehicle)),
        "selected": max(0, int(selected)),
    }


def summary_text(vehicles: Iterable[dict[str, Any]], selected: int = 0,
                 shown: int | None = None) -> str:
    """Färdig text till statusraden, med svenska siffror och ingen gissning."""
    numbers = summary(vehicles, selected)
    parts = [f"{numbers['rows']} fordon"]
    if shown is not None and shown != numbers["rows"]:
        parts.append(f"{shown} visas")
    parts.append(f"{numbers['complete']} fullständiga")
    if numbers["incomplete"]:
        parts.append(f"{numbers['incomplete']} ofullständiga")
    if numbers["no_color"]:
        parts.append(f"{numbers['no_color']} saknar färg")
    if numbers["no_approval"]:
        parts.append(f"{numbers['no_approval']} saknar approval")
    if selected:
        parts.append(f"{numbers['selected']} markerade")
    return " · ".join(parts)
