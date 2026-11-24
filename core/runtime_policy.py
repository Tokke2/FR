"""Regler för prestanda, minne och energiförbrukning.

Programmet har tre lägen som måste hanteras olika:

* **Synligt fönster** – allt ska vara uppdaterat och direkt.
* **Dolt eller minimerat** – inget syns; då ska programmet nästan inte göra
  någonting. En timer som tickar var 30:e sekund i bakgrunden kostar batteri
  utan att någon ser resultatet.
* **Inaktivt en längre stund** – fönstret står öppet men ingen rör det.

Här finns bara ren logik (intervall, gränser, minnesberäkning) så att den kan
testas utan Qt. Inkopplingen mot ``QTimer`` sker i huvudfönstret.

Modulen importerar aldrig Qt.
"""
from __future__ import annotations

from typing import Any, Final, Iterable

# ── Uppdateringsintervall ───────────────────────────────────────────────────

BASE_STATS_INTERVAL_MS: Final[int] = 30_000
BASE_WATCH_INTERVAL_MS: Final[int] = 30_000
BASE_TRAY_INTERVAL_MS: Final[int] = 10_000
BASE_INSTANCE_INTERVAL_MS: Final[int] = 5_000

# I bakgrunden räcker det med en bråkdel så många kontroller.
IDLE_FACTOR: Final[int] = 4
# Tak: även i bakgrunden ska en kontroll ske ibland, annars missas nya filer.
MAX_BACKGROUND_INTERVAL_MS: Final[int] = 10 * 60 * 1000
MIN_INTERVAL_MS: Final[int] = 250


def effective_interval(base_ms: int, hidden: bool = False, idle: bool = False,
                       factor: int = IDLE_FACTOR) -> int:
    """Räkna ut hur ofta en timer ska ticka i nuvarande läge.

    Dold eller minimerad ger ``factor`` gånger längre intervall (minst 4 gånger),
    ett inaktivt men synligt fönster ger halva ökningen. Intervallet kapas uppåt
    så att en kontroll alltid sker ibland.
    """
    try:
        base = max(MIN_INTERVAL_MS, int(base_ms))
    except (TypeError, ValueError):
        base = MIN_INTERVAL_MS
    steps = 0
    if hidden:
        steps = max(2, int(factor))
    elif idle:
        steps = 2
    interval = base * steps if steps else base
    return int(min(MAX_BACKGROUND_INTERVAL_MS, max(MIN_INTERVAL_MS, interval)))


def should_run(base_ms: int, hidden: bool = False, idle: bool = False,
               last_run: float | None = None, now: float | None = None) -> bool:
    """Ska en återkommande uppgift köras nu?

    Används av de uppgifter som räknar om statistik eller läser filer. I
    bakgrunden hoppas uppdateringen över tills intervallet verkligen har gått,
    så att en timer som vaknar ofta inte gör dyrbar nytta varje gång.
    """
    if not hidden and not idle:
        return True
    if last_run is None or now is None:
        return True
    interval = effective_interval(base_ms, hidden, idle) / 1000
    return (now - last_run) >= max(1.0, interval)


def idle_after_seconds(hidden: bool = False) -> int:
    """Hur länge fönstret ska vara orört innan det räknas som inaktivt."""
    return 20 if hidden else 120


def visible_timer_count(intervals: Iterable[int], hidden: bool = False) -> int:
    """Hur många timers som fortfarande arbetar i bakgrunden.

    Används av testerna och minnesöversikten: i bakgrunden ska antalet aktiva
    timers vara noll, allt annat är en läcka.
    """
    values = [value for value in intervals if isinstance(value, int) and value > 0]
    return 0 if hidden else len(values)


# ── Minne ──────────────────────────────────────────────────────────────────

MB: Final[int] = 1024 * 1024
# Rimligt tak innan programmet varnar. Sätts med marginal: en tom Fordonsreg
# med Qt ligger långt under, och en stor årsfil kan lägga till en del.
MEMORY_WARN_MB: Final[int] = 400
# Ett hopp mellan två mätningar som är större än så här kan tyda på en läcka.
MEMORY_GROWTH_WARN_MB: Final[int] = 80


def to_mb(value_bytes: Any) -> float:
    """Gör om byte till megabyte med en decimal."""
    try:
        value = float(value_bytes)
    except (TypeError, ValueError):
        return 0.0
    if value < 0:
        return 0.0
    return round(value / MB, 1)


def memory_status(rss_bytes: int = 0, previous_rss_bytes: int | None = None) -> dict[str, Any]:
    """Bedöm minnesanvändningen och föreslå en åtgärd.

    ``level`` är ``ok``, ``warning`` eller ``critical``. Nivån bygger enbart på
    uppmätta värden – ingenting gissas.
    """
    current_mb = to_mb(rss_bytes)
    growth_mb = 0.0
    if previous_rss_bytes:
        growth_mb = round(current_mb - to_mb(previous_rss_bytes), 1)
    level = "ok"
    if current_mb >= MEMORY_WARN_MB * 1.5:
        level = "critical"
    elif current_mb >= MEMORY_WARN_MB or growth_mb >= MEMORY_GROWTH_WARN_MB:
        level = "warning"
    return {
        "mb": current_mb,
        "growth_mb": growth_mb,
        "level": level,
        "limit_mb": MEMORY_WARN_MB,
        "advice": memory_advice(level),
    }


def memory_advice(level: str) -> str:
    """Kort råd på svenska, samma text i dialog och verktygstips."""
    return {
        "ok": "Minnesläget är normalt.",
        "warning": ("Minnesläget är högre än vanligt. Stäng årsflikar du inte "
                    "använder och kör Verktyg → Frigör minne."),
        "critical": ("Minnesläget är högt. Spara och starta om programmet när "
                     "det passar; inget data går förlorat."),
    }.get(level, "Minnesläget är normalt.")


def optimization_steps(stats: dict[str, int] | None = None) -> list[str]:
    """Vad "Frigör minne" faktiskt gör, i klartext.

    Stegen är desamma som modulen utför – listan är inte marknadsföring.
    """
    stats = stats or {}
    steps = [
        "Släpper cachade SVG-ikoner (de ritas om nästa gång de behövs).",
        "Tömmer tabellvyernas inaktuella rader och modellindex.",
        "Kör Pythons skräpsamlare och returnerar ledigt minne till systemet.",
    ]
    if stats.get("closed_tabs"):
        steps.append(f"Stängde {stats['closed_tabs']} årsflik(ar) som inte använts.")
    return steps


def memory_summary(status: dict[str, Any], objects: int = 0) -> str:
    """En rad till dialogen, med enbart uppmätta siffror."""
    parts = [f"{status.get('mb', 0):.1f} MB i bruk"]
    growth = status.get("growth_mb", 0)
    if growth:
        sign = "+" if growth > 0 else "−"
        parts.append(f"{sign}{abs(growth):.1f} MB sedan förra mätningen")
    if objects:
        parts.append(f"{objects} Python-objekt")
    return " · ".join(parts)


# ── Starttid ───────────────────────────────────────────────────────────────

# Tider över detta räknas som långsamma och loggas, så att en seg start syns.
SLOW_STEP_MS: Final[int] = 750
SLOW_START_TOTAL_MS: Final[int] = 4_000


def slow_steps(steps: Iterable[tuple[str, float]], limit_ms: int = SLOW_STEP_MS) -> list[tuple[str, float]]:
    """Plocka ut de startsteg som tog för lång tid."""
    result = []
    for name, duration in steps:
        try:
            value = float(duration)
        except (TypeError, ValueError):
            continue
        if value >= limit_ms:
            result.append((str(name), round(value, 1)))
    return result


def start_is_slow(steps: Iterable[tuple[str, float]], total_ms: float = 0,
                  limit_ms: int = SLOW_START_TOTAL_MS) -> bool:
    """Avgör om starten bör rapporteras som långsam."""
    try:
        total = float(total_ms)
    except (TypeError, ValueError):
        total = 0.0
    return total >= limit_ms or bool(slow_steps(steps))
