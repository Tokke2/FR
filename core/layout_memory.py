"""Minnesvärda inställningar per skärm, tabell och fönster.

Här samlas de filer som gör att programmet beter sig likadant nästa gång:

* ``data/screen_profiles.json`` – fönstrets storlek och placering per skärm
  (förslag 3).
* ``data/table_profiles.json`` – kolumnordning, dolda kolumner, bredder,
  radhöjd och textbrytning per tabell och år (förslag 7 och 8).
* ``data/year_layout.json`` – fästa årsflikar (förslag 17, ej byggt här).

Allt skrivs atomiskt (tempfil + ``os.replace``) och läses defensivt: en trasig
fil får aldrig hindra programmet från att starta. Filer som inte finns ger
tomma värden, inte fel.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Final

_log = logging.getLogger(__name__)

SCREEN_PROFILES_FILE: Final[str] = "screen_profiles.json"
TABLE_PROFILES_FILE: Final[str] = "table_profiles.json"
MAX_PROFILES: Final[int] = 200


def _data_dir(root: Path) -> Path:
    return Path(root) / "data"


def _read(path: Path) -> dict[str, Any]:
    """Läs en JSON-fil. Saknad eller trasig fil ger en tom struktur."""
    try:
        if not path.is_file() or path.is_symlink():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError) as exc:
        _log.warning("Kunde inte läsa %s: %s", path.name, exc)
        return {}


def _write(path: Path, data: dict[str, Any]) -> bool:
    """Skriv atomiskt. Returnerar ``False`` om filen inte kunde sparas."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(data, out, ensure_ascii=False, indent=2, sort_keys=True)
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise
        return True
    except OSError as exc:
        _log.warning("Kunde inte spara %s: %s", path.name, exc)
        return False


def _prune(data: dict[str, Any]) -> dict[str, Any]:
    """Behåll högst ``MAX_PROFILES`` poster, de senast använda först."""
    if len(data) <= MAX_PROFILES:
        return data
    items = sorted(data.items(), key=lambda item: str(item[1].get("used") if isinstance(item[1], dict) else ""),
                   reverse=True)
    return dict(items[:MAX_PROFILES])


# ── Skärmprofiler (förslag 3) ───────────────────────────────────────────────

def screen_key(name: str, width: int, height: int) -> str:
    """Nyckel som skiljer skärmar med olika upplösning åt."""
    clean = "".join(ch for ch in str(name or "skarm") if ch.isalnum() or ch in "-_").strip("-_")
    return f"{clean or 'skarm'}@{int(width)}x{int(height)}"


def load_screen_profiles(root: Path) -> dict[str, Any]:
    return _read(_data_dir(root) / SCREEN_PROFILES_FILE)


def _valid_geometry(values: dict[str, Any], available_width: int, available_height: int) -> bool:
    """Fönstret måste rymmas på skärmen och ha rimlig storlek."""
    try:
        width, height = int(values["width"]), int(values["height"])
        x, y = int(values["x"]), int(values["y"])
    except (KeyError, TypeError, ValueError):
        return False
    if width < 600 or height < 400:
        return False
    if width > available_width or height > available_height:
        return False
    # Minst en fjärdedel av fönstret måste ligga innanför skärmen.
    if x + width < available_width * 0.25 or x > available_width * 0.75:
        return False
    if y + height < available_height * 0.25 or y > available_height * 0.75:
        return False
    return True


def screen_geometry(root: Path, name: str, available_width: int, available_height: int) -> dict[str, int] | None:
    """Hämta sparad geometri om den fortfarande passar på skärmen."""
    profiles = load_screen_profiles(root)
    for key, value in profiles.items():
        if not isinstance(value, dict):
            continue
        if value.get("name") != name:
            continue
        if not _valid_geometry(value, available_width, available_height):
            _log.info("Sparad fönstergeometri passar inte längre på %s och används inte", name)
            return None
        return {field: int(value[field]) for field in ("width", "height", "x", "y")}
    return None


def save_screen_geometry(root: Path, name: str, *, width: int, height: int, x: int, y: int,
                         maximized: bool = False, used: str = "") -> bool:
    """Spara fönstrets storlek och placering för en skärm."""
    profiles = load_screen_profiles(root)
    key = screen_key(name, width, height)
    profiles[key] = {
        "name": name,
        "width": int(width),
        "height": int(height),
        "x": int(x),
        "y": int(y),
        "maximized": bool(maximized),
        "used": used,
    }
    return _write(_data_dir(root) / SCREEN_PROFILES_FILE, _prune(profiles))


# ── Tabellprofiler (förslag 7 och 8) ────────────────────────────────────────

def table_key(table: str, year: int | str | None = None) -> str:
    suffix = f"/{year}" if year is not None else ""
    return f"{str(table).strip()}{suffix}"


def load_table_profiles(root: Path) -> dict[str, Any]:
    return _read(_data_dir(root) / TABLE_PROFILES_FILE)


def table_profile(root: Path, table: str, year: int | str | None = None) -> dict[str, Any]:
    """Profil för en tabell, eller en tom profil om ingen sparats."""
    value = load_table_profiles(root).get(table_key(table, year))
    return value if isinstance(value, dict) else {}


def normalize_profile(profile: dict[str, Any], known_columns: list[str]) -> dict[str, Any]:
    """Rensa en profil mot tabellens faktiska kolumner.

    Kolumner som inte längre finns tas bort, okända bredder ignoreras och
    ordningen blir alltid en delmängd av de kända kolumnerna. Det gör att en
    gammal profil aldrig kan dölja en ny kolumn.
    """
    if not known_columns:
        return {}
    known = list(dict.fromkeys(known_columns))
    order = []
    for name in profile.get("order", []) or []:
        # En kolumn får bara förekomma en gång, annars flyttas fel kolumn.
        if name in known and name not in order:
            order.append(name)
    order += [name for name in known if name not in order]
    hidden = [name for name in profile.get("hidden", []) if name in known]
    widths_raw = profile.get("widths") if isinstance(profile.get("widths"), dict) else {}
    widths = {}
    for name in known:
        try:
            width = int(widths_raw.get(name, 0))
        except (TypeError, ValueError):
            continue
        if 20 <= width <= 2000:
            widths[name] = width
    result: dict[str, Any] = {"order": order, "hidden": hidden, "widths": widths}
    density = str(profile.get("density") or "").strip().lower()
    if density in ("comfortable", "compact"):
        result["density"] = density
    if isinstance(profile.get("word_wrap"), bool):
        result["word_wrap"] = profile["word_wrap"]
    return result


def save_table_profile(root: Path, table: str, profile: dict[str, Any],
                       year: int | str | None = None, *, known_columns: list[str] | None = None,
                       used: str = "") -> bool:
    """Spara en tabellprofil, rensad mot kända kolumner om de anges."""
    clean = normalize_profile(profile, known_columns) if known_columns is not None else dict(profile)
    clean["used"] = used
    profiles = load_table_profiles(root)
    key = table_key(table, year)
    profiles[key] = clean
    return _write(_data_dir(root) / TABLE_PROFILES_FILE, _prune(profiles))


def clear_table_profile(root: Path, table: str, year: int | str | None = None) -> bool:
    """Återställ en tabell till standardkolumnerna."""
    profiles = load_table_profiles(root)
    profiles.pop(table_key(table, year), None)
    return _write(_data_dir(root) / TABLE_PROFILES_FILE, profiles)
