"""Skeleton-rader: visa att data är på väg utan att layouten flyttar sig.

När en årsfil läses in kan tabellen vara tom en kort stund. Tidigare visades en
"Laddar..."-text, och när raderna kom hoppade hela vyn. Här skapas i stället
lika många platshållarrader som tabellen brukar ha, med **samma radhöjd** som de
riktiga raderna. Då står rubriken, rullningslisten och formuläret stilla.

Modulen importerar Qt först när funktionerna anropas.
"""
from __future__ import annotations

from typing import Any, Final

# Antal platshållarrader innan data finns. Fyra räcker för att visa att
# tabellen är på väg och ryms i de flesta fönster utan att skapa rullning.
DEFAULT_ROWS: Final[int] = 4
# Andel av kolumnbredden som platshållaren fyller, så att den ser ut som text.
FILL_RATIO: Final[float] = 0.6


def placeholder_text(column: str, width: int = 120) -> str:
    """En neutral platshållare – aldrig en påhittad VIN eller ett påhittat namn."""
    return ""


def placeholder_values(columns: list[str]) -> list[str]:
    """Tomma platshållarvärden i samma antal som kolumnerna."""
    return [placeholder_text(name) for name in columns]


def row_count(rows: int = DEFAULT_ROWS) -> int:
    """Antal platshållarrader, aldrig negativt eller orimligt stort."""
    try:
        value = int(rows)
    except (TypeError, ValueError):
        return DEFAULT_ROWS
    return max(0, min(20, value))


def bar_width(section_width: int, column: str = "") -> int:
    """Bredden på den lilla stapel som antyder text i en cell."""
    try:
        width = int(section_width)
    except (TypeError, ValueError):
        return 0
    # VIN-koden är alltid 17 tecken och följer en fast andel, övriga 60 %.
    ratio = 0.85 if column == "VIN-kod" else FILL_RATIO
    return max(0, int(width * ratio))


def show(table: Any, columns: list[str], rows: int = DEFAULT_ROWS,
         row_height: int = 32) -> int:
    """Fyll en tabell med platshållarrader. Returnerar antalet rader.

    Radhöjden sätts uttryckligen, så att tabellen har exakt samma höjd före
    och efter inläsningen – det är det som gör att inget hoppar.
    """
    count = row_count(rows)
    try:
        table.setRowCount(0)
        table.setRowCount(count)
        for row in range(count):
            table.setRowHeight(row, int(row_height))
            for column in range(len(columns)):
                item = table.item(row, column)
                if item is not None:
                    item.setText("")
        # Platshållarna ska inte kunna markeras eller redigeras.
        try:
            table.setSelectionMode(table.SelectionMode.NoSelection)
        except Exception:
            pass
    except Exception:
        return 0
    return count


def clear(table: Any) -> None:
    """Ta bort platshållarna och ge tillbaka normal markering."""
    try:
        table.setRowCount(0)
        table.setSelectionMode(table.SelectionMode.ExtendedSelection)
    except Exception:
        pass
