"""Skalningstest: hittar text som klipps och innehåll som kräver sidrullning.

När Windows eller Linux skalar gränssnittet till 125–200 % blir varje logisk
pixel större, och en text som precis fick plats vid 100 % kan plötsligt klippas
av. Det här testet mäter alla etiketter och knappar och rapporterar vilka som
inte får plats, samt om en tabell tvingar fram vågrät rullning.

Testet kan köras på två sätt:

* **I appen** (Verktyg → Skalningstest) – går igenom det riktiga fönstret,
  mäter med Qt:s tecktypsmått och visar en lista.
* **I testsviten** – med påhittade mått, så logiken är verifierad utan Qt.

Modulen importerar Qt först när det behövs.
"""
from __future__ import annotations

from typing import Any, Callable, Final, Iterable, Sequence

# Nivåer som testas. 100 % är standard, 200 % är det högsta Windows erbjuder
# utan att kräva omstart i de flesta miljöer.
SCALE_LEVELS: Final[tuple[int, ...]] = (100, 125, 150, 175, 200)

# Marginal innan texten anses klippt – tecktypsmått är aldrig exakta.
TEXT_SAFETY_MARGIN: Final[int] = 2
# Hur mycket en etikett får klippas innan det räknas som fel.
CLIP_TOLERANCE: Final[int] = 0


def scaling_levels() -> list[int]:
    return list(SCALE_LEVELS)


def text_fits(text: str, available: int, measure: Callable[[str], int] | None = None) -> bool:
    """Får texten plats inom ``available`` pixlar?"""
    if not text:
        return True
    needed = measure(text) if measure else len(text) * 7
    return needed <= max(0, int(available)) - TEXT_SAFETY_MARGIN


def clipped_labels(rows: Iterable[tuple[str, str, int]],
                   measure: Callable[[str], int] | None = None,
                   elided_ok: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Lista de etiketter som klipps.

    ``rows`` är (namn, text, tillgänglig bredd). Namn i ``elided_ok`` får
    förkortas med "…" och räknas därför inte som fel – det är ett medvetet
    val, till exempel i en tabellcell.
    """
    allowed = set(elided_ok)
    problems = []
    for name, text, width in rows:
        if name in allowed:
            continue
        if not text_fits(text, width, measure):
            needed = measure(text) if measure else len(text) * 7
            problems.append({
                "widget": name,
                "text": text,
                "available": int(width),
                "needed": int(needed),
                "missing": int(needed - max(0, int(width))),
            })
    return problems


def horizontal_overflow(column_widths: Sequence[int], available: int) -> int:
    """Antal pixlar som tabellen är bredare än vyn (0 = ingen sidrullning)."""
    try:
        total = sum(int(width) for width in column_widths)
        room = int(available)
    except (TypeError, ValueError):
        return 0
    return max(0, total - room)


def report(scales: Sequence[int] = (100,), labels: Iterable[tuple[str, str, int]] = (),
           columns: Sequence[int] = (), available: int = 0,
           measure: Callable[[str], int] | None = None,
           elided_ok: Iterable[str] = ()) -> dict[str, Any]:
    """Sammanställ ett skalningstest för en nivå."""
    rows = list(labels)
    clipped = clipped_labels(rows, measure, elided_ok)
    overflow = horizontal_overflow(columns, available) if columns else 0
    level = scales[0] if scales else 100
    return {
        "scale": level,
        "clipped": clipped,
        "overflow": overflow,
        "ok": not clipped and overflow <= 0,
        "checked": len(rows),
    }


def report_all(scales: Sequence[int] = SCALE_LEVELS,
               labels_for_scale: Callable[[int], Iterable[tuple[str, str, int]]] | None = None,
               columns_for_scale: Callable[[int], Sequence[int]] | None = None,
               available_for_scale: Callable[[int], int] | None = None,
               measure_for_scale: Callable[[int], Callable[[str], int]] | None = None,
               elided_ok: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Kör testet på alla nivåer och returnera en rad per nivå."""
    results = []
    for level in scales:
        labels = labels_for_scale(level) if labels_for_scale else ()
        columns = columns_for_scale(level) if columns_for_scale else ()
        available = available_for_scale(level) if available_for_scale else 0
        measure = measure_for_scale(level) if measure_for_scale else None
        results.append(report([level], labels, columns, available, measure, elided_ok))
    return results


def summary_text(results: Iterable[dict[str, Any]]) -> str:
    """Kort text till statusrutan, på svenska."""
    rows = list(results)
    failed = [row for row in rows if not row["ok"]]
    if not rows:
        return "Inget att mäta."
    if not failed:
        return (f"All text får plats på {rows[0]['scale']}–{rows[-1]['scale']} % "
                "och ingen tabell kräver sidrullning.")
    parts = []
    for row in failed:
        detail = []
        if row["clipped"]:
            detail.append(f"{len(row['clipped'])} klippta texter")
        if row["overflow"]:
            detail.append(f"{row['overflow']} px för bred tabell")
        parts.append(f"{row['scale']} %: " + ", ".join(detail))
    return "Problem: " + "; ".join(parts) + "."


# ── Mätning i det riktiga fönstret ──────────────────────────────────────────

def measure_labels(root: Any, elide_ok: tuple[str, ...] = ("Mono", "PageHeaderIcon")) -> list[tuple[str, str, int]]:
    """Samla (namn, text, bredd) från alla synliga etiketter och knappar.

    Kräver Qt och ett riktigt fönster; anropas bara från menyn.
    """
    rows: list[tuple[str, str, int]] = []
    try:
        from PySide6.QtWidgets import QLabel, QAbstractButton, QWidget
    except Exception:
        return rows
    stack = [root]
    seen = 0
    while stack and seen < 4000:
        widget = stack.pop()
        if not isinstance(widget, QWidget):
            continue
        seen += 1
        try:
            if widget.isVisible():
                stack.extend(widget.children())
                name = widget.objectName() or widget.__class__.__name__
                if name in elide_ok:
                    continue
                if isinstance(widget, QLabel):
                    text = widget.text()
                    if text and "<" not in text:  # hoppa över formaterad text
                        rows.append((name, text, widget.width()))
                elif isinstance(widget, QAbstractButton):
                    text = widget.text()
                    if text:
                        rows.append((name, text, widget.width()))
        except Exception:
            continue
    return rows


def measure_columns(root: Any) -> tuple[list[int], int]:
    """Bredden på alla kolumner och den plats som finns, för första tabellen."""
    try:
        from PySide6.QtWidgets import QTableView, QWidget
    except Exception:
        return [], 0
    stack = [root]
    while stack:
        widget = stack.pop()
        if not isinstance(widget, QWidget):
            continue
        if isinstance(widget, QTableView):
            header = widget.horizontalHeader()
            widths = [header.sectionSize(i) for i in range(header.count()) if not widget.isColumnHidden(i)]
            return widths, widget.viewport().width()
        stack.extend(widget.children())
    return [], 0


def audit_widget(root: Any, scale: int = 100) -> dict[str, Any]:
    """Kör testet på ett riktigt fönster och returnera resultatet."""
    labels = measure_labels(root)
    columns, available = measure_columns(root)
    try:
        metrics = root.fontMetrics()
        measure = lambda text: metrics.horizontalAdvance(text)  # noqa: E731
    except Exception:
        measure = None
    return report([scale], labels, columns, available, measure,
                  elided_ok=("Mono", "PageHeaderIcon", "Caption"))
