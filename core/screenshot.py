"""Skärmbild av programmets eget fönster, för support (förslag 25).

Tre regler styr allt här:

1. **Bara appens fönster** fångas – aldrig skärmen, aldrig andra program. Det
   gör att en skärmbild kan skickas till support utan att något annat syns.
2. **PIN-fält maskas alltid.** Fält vars namn eller verktygstips innehåller
   *pin* eller *lösen* fylls med en heldragen ruta innan bilden sparas, och
   texten i dem kopieras aldrig med.
3. **Ingen bild utan användarens medgivande** – dialogen visar en
   förhandsgranskning och filen sparas först när användaren väljer att spara.

Modulen importerar Qt först när funktionerna anropas.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Final

SECRET_MARKERS: Final[tuple[str, ...]] = ("pin", "lösen", "losen", "password", "hemlig")
MASK_COLOR: Final[str] = "#4a4f57"
SUPPORT_DIR: Final[str] = "logs/support"


def is_secret_field(name: str, extra: str = "") -> bool:
    """Avgör om ett fält innehåller hemlig information som ska maskas."""
    haystack = f"{name or ''} {extra or ''}".casefold()
    return any(marker in haystack for marker in SECRET_MARKERS)


def mask_rects(width: int, height: int, names: list[str] | None = None) -> list[tuple[int, int, int, int]]:
    """Rutor som ska målas över.

    ``names`` är namnen på de fält som hittades; varje hemligt fält ger en
    ruta. Saknas mått returneras en tom lista i stället för en gissning.
    """
    if not names:
        return []
    rects = []
    for index, name in enumerate(names):
        if not is_secret_field(name):
            continue
        rects.append((0, 0, max(0, int(width)), max(0, int(height))))
    return rects


def default_filename(prefix: str = "fordonsreg", moment: datetime | None = None) -> str:
    """Filnamn med datum och tid, utan tecken som stökar till i Windows."""
    stamp = (moment or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    clean = "".join(ch for ch in prefix if ch.isalnum() or ch in "-_") or "fordonsreg"
    return f"{clean}_{stamp}.png"


def support_path(root: Path, filename: str = "") -> Path:
    """Sökväg i supportmappen, med skydd mot att hamna utanför den."""
    folder = Path(root) / SUPPORT_DIR
    name = Path(filename or default_filename()).name
    if not name.lower().endswith(".png"):
        name += ".png"
    return folder / name


def secret_field_names(widget: Any, limit: int = 500) -> list[str]:
    """Namn på alla PIN- och lösenordsfält i ett fönster."""
    names: list[str] = []
    try:
        from PySide6.QtWidgets import QWidget
    except Exception:
        return names
    stack = [widget]
    seen = 0
    while stack and seen < limit:
        current = stack.pop()
        if not isinstance(current, QWidget):
            continue
        seen += 1
        try:
            name = " ".join((current.objectName(), current.toolTip(), current.accessibleName()))
            if is_secret_field(name):
                names.append(current.objectName() or "fält")
            stack.extend(current.children())
        except Exception:
            continue
    return names


def capture(window: Any) -> Any:
    """Ta en bild av fönstret med PIN-fält övermålade.

    Returnerar en ``QPixmap``, eller ``None`` om Qt inte kan ta bilden.
    """
    try:
        from PySide6.QtGui import QColor, QPainter, QPixmap
    except Exception:
        return None
    try:
        pixmap = window.grab()
    except Exception:
        return None
    if pixmap is None or pixmap.isNull():
        return None
    names = secret_field_names(window)
    if not names:
        return pixmap
    painter = QPainter(pixmap)
    try:
        painter.setBrush(QColor(MASK_COLOR))
        painter.setPen(QColor(MASK_COLOR))
        from PySide6.QtWidgets import QWidget
        stack = [window]
        while stack:
            current = stack.pop()
            if not isinstance(current, QWidget):
                continue
            try:
                name = " ".join((current.objectName(), current.toolTip(), current.accessibleName()))
                if is_secret_field(name):
                    top_left = current.mapTo(window, current.rect().topLeft())
                    painter.drawRect(top_left.x(), top_left.y(), current.width(), current.height())
                stack.extend(current.children())
            except Exception:
                continue
    finally:
        painter.end()
    return pixmap


def save(pixmap: Any, path: Path) -> bool:
    """Spara bilden, med mappen skapad om den saknas."""
    if pixmap is None:
        return False
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return bool(pixmap.save(str(path), "PNG"))
    except Exception:
        return False
