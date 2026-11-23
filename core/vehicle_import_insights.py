"""Biverkningsfria hjälpfunktioner för Fordonsdatas Excel-import."""
from __future__ import annotations

import re
from typing import Callable, Iterable


def profile_coverage(headers: Iterable[str], mapping: dict[str, str],
                     allowed_fields: Iterable[str], normalize: Callable[[str], str]) -> tuple[int, int]:
    """Räkna filens unika rubriker med användbart målfält, inte profilens extra fält."""
    fields = set(allowed_fields)
    normalized = {normalize(header) for header in headers}
    normalized.discard("")
    return sum(1 for header in normalized if mapping.get(header) in fields), len(normalized)


def example_text(value: object, *, limit: int = 80) -> str:
    """Begränsa visningsvärde utan att påverka det som importeras."""
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def sheet_year(name: str) -> int | None:
    """Ett entydigt fyrsiffrigt år i bladnamnet, annars inget gissat år."""
    years = {int(value) for value in re.findall(r"(?<!\d)(?:19\d{2}|20\d{2}|2100)(?!\d)", name)}
    return next(iter(years)) if len(years) == 1 else None


def row_year(value: str) -> int | None:
    """Acceptera årtal, inklusive Excels heltalsskrivning och befintliga tvåsiffriga år."""
    text = value.strip()
    if not re.fullmatch(r"\d{1,4}(?:\.0+)?", text):
        return None
    year = int(text.split('.')[0])
    if year < 100:
        year += 2000
    return year if 1900 <= year <= 2100 else None
