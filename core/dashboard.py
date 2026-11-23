"""Instrumentpanelens data (förslag 21), samlad utan att något ändras.

Varje avsnitt läses skilt och ett fel i en källa påverkar inte de andra. Inga
filer skrivs och inga nätverksanrop görs.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from core.error_codes import read_entries, summary as error_summary

_log = logging.getLogger(__name__)

MAX_YEARS = 40


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().isoformat(timespec="minutes")


def vehicles_section(vehicle_dir: Path) -> dict:
    """Antal fordon per år, samt senaste ändring."""
    rows = []
    base = Path(vehicle_dir)
    for path in sorted(base.glob("*.json")):
        if path.is_symlink() or not path.is_file() or not path.stem.isdigit():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            _log.warning("Årsfilen %s kunde inte läsas: %s", path.name, exc)
            rows.append({"year": int(path.stem), "count": 0, "updated": None,
                         "error": "Filen kunde inte läsas"})
            continue
        records = payload.get("vehicles") if isinstance(payload, dict) else None
        meta = payload.get("_meta") if isinstance(payload, dict) else None
        rows.append({
            "year": int(path.stem),
            "count": len(records) if isinstance(records, list) else 0,
            "updated": (meta or {}).get("updated_at") if isinstance(meta, dict) else _iso(path.stat().st_mtime),
            "error": None,
        })
        if len(rows) >= MAX_YEARS:
            break
    rows.sort(key=lambda row: row["year"], reverse=True)
    total = sum(row["count"] for row in rows)
    newest = None
    for row in rows:
        if row["updated"] and (newest is None or str(row["updated"]) > newest):
            newest = str(row["updated"])
    return {"rows": rows, "total": total, "years": len(rows), "latest_update": newest,
            "available": bool(rows)}


def colors_section(color_file: Path) -> dict:
    """Antal färger och hur många som väntar på koppling."""
    path = Path(color_file)
    if path.is_symlink() or not path.is_file():
        return {"available": False, "total": 0, "pending": 0, "mapped": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        _log.warning("Färgfilen kunde inte läsas: %s", exc)
        return {"available": False, "total": 0, "pending": 0, "mapped": 0}
    if isinstance(data, dict):
        data = data.get("colors") or data.get("farger") or []
    if not isinstance(data, list):
        return {"available": False, "total": 0, "pending": 0, "mapped": 0}
    pending = 0
    for row in data:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or row.get("kod") or "").strip()
        marker = str(row.get("dispatch_pending_id") or "")
        if not code or marker.startswith("@dispatch:"):
            pending += 1
    return {"available": True, "total": len(data), "pending": pending,
            "mapped": len(data) - pending}


def errors_section(logs_dir: Path) -> dict:
    entries = read_entries(Path(logs_dir) / "felkoder.json")
    active = [row for row in entries if row.get("status") == "aktiv"]
    return {"available": True, "active": len(active), "summary": error_summary(entries),
            "latest": active[:3]}


def ts_section(root: Path) -> dict:
    try:
        from core.ts_verification import status as ts_status, approval
        record = approval(root)
        return {"blocked": record is None, "status": ts_status(root),
                "approved_at": (record or {}).get("approved_at")}
    except Exception as exc:  # en trasig status får aldrig stoppa panelen
        _log.warning("TS-status kunde inte läsas: %s", exc)
        return {"blocked": True, "status": "TS-spärren kunde inte kontrolleras.",
                "approved_at": None}


def health_section(root: Path) -> dict:
    from core.startup_health import STATE_DIR, PENDING_NAME
    path = Path(root).resolve() / STATE_DIR / PENDING_NAME
    try:
        pending = path.is_file() and not path.is_symlink()
    except OSError:
        pending = False
    return {"pending": pending,
            "text": ("Föregående start efter en uppdatering bekräftades inte. "
                     "Kontrollera loggen." if pending else "Senaste starten bekräftades normalt.")}


def build(root: Path, *, vehicle_dir: Path | None = None, colors_file: Path | None = None,
          logs_dir: Path | None = None) -> dict:
    """Samla hela panelen. Saknade sökvägar hoppas över utan att kasta fel."""
    root = Path(root).resolve()
    sections = {
        "vehicles": vehicles_section(vehicle_dir or root / "data" / "vehicles"),
        "colors": colors_section(colors_file or root / "data" / "farger.json"),
        "errors": errors_section(logs_dir or _find_logs(root)),
        "ts": ts_section(root),
        "health": health_section(root),
    }
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sections": sections,
        "headline": headline(sections),
    }


def _find_logs(root: Path) -> Path:
    for candidate in (root / "logs", root / "data" / "logs"):
        if candidate.is_dir():
            return candidate
    return root / "logs"


def headline(sections: dict) -> str:
    """En enda mening som svarar på 'är allt i ordning?'."""
    vehicles = sections.get("vehicles", {})
    colors = sections.get("colors", {})
    errors = sections.get("errors", {})
    blocked = sections.get("ts", {}).get("blocked", True)
    parts = []
    if vehicles.get("available"):
        parts.append(f"{vehicles['total']} fordon i {vehicles['years']} år")
    else:
        parts.append("Ingen fordonsdata hittad")
    if colors.get("available") and colors.get("pending"):
        parts.append(f"{colors['pending']} färger väntar på koppling")
    if errors.get("active"):
        parts.append(f"{errors['active']} aktiva felkoder")
    parts.append("TS-genereringen är spärrad" if blocked else "TS-formatet är verifierat")
    return " · ".join(parts)
