"""Tabellhjälp: frysta kolumner, radhöjd, textbrytning och ihågkommen profil.

Används av tabeller som vill ha samma beteende som resten av programmet:

* första kolumnen (VIN-koden) är fryst så att den alltid syns (förslag 6),
* rubrikraden ligger fast överst,
* radhöjd och textbrytning följer vald densitet (förslag 8),
* kolumnordning, dolda kolumner och bredder sparas per tabell och år
  (förslag 7) via :mod:`core.layout_memory`.

Modulen importerar Qt först när funktionerna anropas, så den kan importeras av
test och av kod utan Qt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core import layout_memory


def apply_density(view: Any, density: str = "normal",
                  word_wrap: bool | None = None) -> int:
    """Sätt radhöjd och textbrytning på en tabellvy.

    ``word_wrap`` är användarens val. Utan val bryter luftiga rader lång text
    och kompakta rader gör det inte – då ryms fler rader samtidigt.
    """
    from core import theme as design

    height = design.row_height(density)
    if word_wrap is None:
        word_wrap = design.resolve_row_mode(density) != "compact"
    try:
        vertical = view.verticalHeader()
        vertical.setDefaultSectionSize(height)
        vertical.setMinimumSectionSize(height)
        vertical.setSectionResizeMode(vertical.ResizeMode.Fixed)
        view.setWordWrap(bool(word_wrap))
    except Exception:
        return height
    return height


def freeze_first_column(view: Any) -> bool:
    """Frys första kolumnen så att VIN-koden syns vid rullning i sidled."""
    try:
        if hasattr(view, "setFrozenColumnCount"):
            view.setFrozenColumnCount(1)
            return True
    except Exception:
        pass
    return False


def configure(view: Any, *, density: str = "normal", word_wrap: bool | None = None,
              freeze_first: bool = False) -> Any:
    """Grundinställningar som ska gälla alla tabeller i programmet."""
    try:
        view.setAlternatingRowColors(True)
        view.setSelectionBehavior(view.SelectionBehavior.SelectRows)
        view.horizontalHeader().setHighlightSections(False)
        view.horizontalHeader().setStretchLastSection(False)
    except Exception:
        pass
    apply_density(view, density, word_wrap)
    if freeze_first:
        freeze_first_column(view)
    return view


# ── Kolumnprofiler (förslag 7) ──────────────────────────────────────────────

def capture(view: Any, known_columns: list[str]) -> dict[str, Any]:
    """Läs av tabellens nuvarande kolumnläge till en profil."""
    profile: dict[str, Any] = {"order": [], "hidden": [], "widths": {}}
    header = None
    try:
        header = view.horizontalHeader()
    except Exception:
        return profile
    try:
        for index in range(header.count()):
            if hasattr(header, "logicalIndex"):
                logical = header.logicalIndex(index)
            else:  # pragma: no cover - äldre Qt
                logical = index
            if not 0 <= logical < len(known_columns):
                continue
            name = known_columns[logical]
            profile["order"].append(name)
            if hasattr(view, "isColumnHidden") and view.isColumnHidden(logical):
                profile["hidden"].append(name)
            width = header.sectionSize(logical)
            if isinstance(width, int) and width > 0:
                profile["widths"][name] = width
    except Exception:
        return profile
    return profile


def apply(view: Any, profile: dict[str, Any], known_columns: list[str]) -> list[str]:
    """Lägg en sparad profil på en tabell och returnera den ordning som används.

    Profilen rensas först mot ``known_columns``, så en gammal fil kan aldrig
    dölja en ny kolumn eller referera till en som tagits bort.
    """
    clean = layout_memory.normalize_profile(profile or {}, known_columns)
    if not clean:
        return list(known_columns)
    order = clean["order"]
    hidden = set(clean["hidden"])
    widths = clean["widths"]
    try:
        header = view.horizontalHeader()
        for target, name in enumerate(order):
            source = known_columns.index(name)
            if target != source and hasattr(header, "moveSection"):
                header.moveSection(header.logicalIndex(source), target)
        for name in known_columns:
            column = header.logicalIndex(order.index(name)) if name in order else known_columns.index(name)
            if name in hidden:
                view.setColumnHidden(column, True)
            elif hasattr(view, "setColumnHidden"):
                view.setColumnHidden(column, False)
            if name in widths:
                header.resizeSection(column, widths[name])
    except Exception:
        return known_columns
    return order


def load(root: Path, view: Any, table: str, known_columns: list[str],
         year: int | str | None = None) -> dict[str, Any]:
    """Läs och lägg på sparad profil för en tabell."""
    profile = layout_memory.table_profile(root, table, year)
    if profile:
        apply(view, profile, known_columns)
    return profile


def save(root: Path, view: Any, table: str, known_columns: list[str],
         year: int | str | None = None, *, density: str | None = None,
         word_wrap: bool | None = None, used: str = "") -> bool:
    """Spara tabellens kolumnläge."""
    profile = capture(view, known_columns)
    if density:
        profile["density"] = density
    if word_wrap is not None:
        profile["word_wrap"] = word_wrap
    return layout_memory.save_table_profile(root, table, profile, year,
                                            known_columns=known_columns, used=used)


def reset(root: Path, table: str, year: int | str | None = None) -> bool:
    """Glöm en tabells kolumnläge."""
    return layout_memory.clear_table_profile(root, table, year)
