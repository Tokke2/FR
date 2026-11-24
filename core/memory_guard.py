"""Minnesöversikt och "Frigör minne".

Programmet ska vara snällt mot en vanlig kontorsdator: det ska inte växa i
minnet under en arbetsdag och inte arbeta i bakgrunden när ingen tittar.

Modulen mäter den egna processens minne (Windows och Linux, utan nya
beroenden), kan köra skräpsamlaren och rapportera vad som faktiskt hände. Alla
siffror som visas kommer härifrån – inget gissas.
"""
from __future__ import annotations

import gc
import logging
import os
from pathlib import Path
import sys
from typing import Any

from core import runtime_policy

_log = logging.getLogger(__name__)

# Startvärdet sparas så att tillväxten kan mätas under körningen.
_last_rss: int | None = None


def _read_linux_rss() -> int:
    """Läs processens minnesbruk ur /proc, i byte."""
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as handle:
            parts = handle.read().split()
        pages = int(parts[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return 0


def _read_windows_rss() -> int:
    """Läs processens arbetsminne med ctypes (ingen psutil behövs)."""
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
            handle, ctypes.byref(counters), counters.cb)
        return int(counters.WorkingSetSize) if ok else 0
    except Exception:
        return 0


def current_rss() -> int:
    """Processens arbetsminne i byte, eller 0 om det inte kan mätas."""
    if sys.platform.startswith("win"):
        return _read_windows_rss()
    if sys.platform.startswith("linux"):
        return _read_linux_rss()
    # macOS och övriga: rusage finns i standardbiblioteket.
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        return int(usage.ru_maxrss)
    except Exception:
        return 0


def measure(store_previous: bool = True) -> dict[str, Any]:
    """Mät minnet och jämför med förra mätningen."""
    global _last_rss
    rss = current_rss()
    status = runtime_policy.memory_status(rss, _last_rss)
    if store_previous:
        _last_rss = rss
    status["rss"] = rss
    status["objects"] = len(gc.get_objects()) if rss else 0
    return status


def reset_baseline() -> None:
    """Glöm förra mätningen (används av test)."""
    global _last_rss
    _last_rss = None


def clear_pixmap_cache() -> int:
    """Töm Qt:s egen bildcache om den finns.

    Returnerar 1 när cachen rensades, annars 0. Qt har inget mått på hur mycket
    som låg i cachen, så inget antal rapporteras.
    """
    freed = 0
    try:
        from PySide6.QtGui import QPixmapCache

        QPixmapCache.clear()
        freed = 1
    except Exception:
        pass
    return freed


def trim_view_caches(widgets: Any = None) -> int:
    """Be tabellvyer att släppa inaktuella rader och index.

    Returnerar antalet vyer som rensades. Felen sväljs med flit: en vy som inte
    längre finns får inte hindra frigöringen.
    """
    cleared = 0
    for view in list(widgets or []):
        try:
            model = view.model()
            if model is not None and hasattr(model, "layoutChanged"):
                # Tvingar vyn att släppa sina cachade storlekar.
                view.reset()
            cleared += 1
        except Exception:
            continue
    return cleared


def clear_icon_cache() -> int:
    """Töm designsystemets ikoncache, så att Qt-bilderna släpps."""
    try:
        from core import theme as design

        return design.clear_icon_cache()
    except Exception:
        return 0


def release(stats: dict[str, int] | None = None) -> dict[str, Any]:
    """Frigör minne och rapportera resultatet med uppmätta siffror."""
    before = current_rss()
    clear_pixmap_cache()
    icons = clear_icon_cache()
    objects_before = len(gc.get_objects())
    # Tre omgångar: den första frigör objekt, den andra deras referenser.
    for _ in range(3):
        gc.collect()
    objects_after = len(gc.get_objects())
    after = current_rss()
    result = {
        "before": before,
        "after": after,
        "before_mb": runtime_policy.to_mb(before),
        "after_mb": runtime_policy.to_mb(after),
        "freed_bytes": max(0, before - after),
        "freed_mb": runtime_policy.to_mb(max(0, before - after)),
        "objects_freed": max(0, objects_before - objects_after),
        "icons_freed": icons,
        "steps": runtime_policy.optimization_steps(stats),
        "summary": "",
    }
    if result["freed_mb"] <= 0:
        result["summary"] = ("Inget minne kunde lämnas tillbaka den här gången – "
                             "det betyder inte att något är fel.")
    else:
        result["summary"] = (f"{result['freed_mb']:.1f} MB lämnades tillbaka, "
                             f"{result['objects_freed']} objekt släpptes.")
    return result


def diagnose(root: Path | None = None) -> dict[str, Any]:
    """Samla en översikt för dialogen: minne, objekt och loggplacering."""
    status = measure()
    status["python"] = f"{sys.version_info.major}.{sys.version_info.minor}"
    status["platform"] = sys.platform
    status["root"] = str(root) if root else ""
    return status
