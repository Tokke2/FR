"""Bevakad mapp (förslag 7): upptäcker nya importfiler, importerar aldrig själv.

Bevakningen är avstängd som standard och sparar bara fingeravtryck för filer som
redan rapporterats. All import kräver att användaren väljer filen och godkänner
den i den vanliga importdialogen.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile

_log = logging.getLogger(__name__)

SETTINGS_VERSION = 1
ALLOWED_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".csv", ".pdf")
MAX_FILE_BYTES = 80 * 1024 * 1024
MAX_REPORTED = 20
TEMP_MARKERS = ("~$", ".tmp", ".part", ".crdownload", ".partial", ".download")
SETTLE_SECONDS = 5.0


def default_settings() -> dict:
    return {"version": SETTINGS_VERSION, "enabled": False, "folders": [], "seen": {}}


def _reject_link(path: Path) -> None:
    if path.is_symlink():
        raise OSError("Filen får inte vara en symbolisk länk")


def valid_settings(data) -> bool:
    if not isinstance(data, dict) or data.get("version") != SETTINGS_VERSION:
        return False
    if not isinstance(data.get("enabled"), bool):
        return False
    folders = data.get("folders")
    if not isinstance(folders, list) or not all(isinstance(item, str) for item in folders):
        return False
    seen = data.get("seen")
    if not isinstance(seen, dict):
        return False
    return all(isinstance(key, str) and isinstance(value, str) for key, value in seen.items())


def load_settings(path: Path) -> dict:
    """Läs inställningen. Ett skadat eller manipulerat svar stänger av bevakningen."""
    path = Path(path)
    _reject_link(path)
    if not path.exists():
        return default_settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        _log.warning("Bevakningsinställningen kunde inte läsas: %s", exc)
        return default_settings()
    if not valid_settings(data):
        _log.warning("Bevakningsinställningen har ogiltigt format och ignoreras")
        return default_settings()
    return data


def save_settings(path: Path, data: dict) -> None:
    if not valid_settings(data):
        raise ValueError("Ogiltiga bevakningsinställningar")
    path = Path(path)
    _reject_link(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".watch-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def normalize_folders(folders) -> list[str]:
    """Endast befintliga, absoluta mappar utan länkar godtas."""
    accepted: list[str] = []
    for raw in folders or []:
        try:
            path = Path(raw).expanduser()
        except TypeError:
            continue
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            _log.warning("Bevakad mapp ignoreras: %s", raw)
            continue
        resolved = str(path.resolve())
        if resolved not in accepted:
            accepted.append(resolved)
    return accepted[:5]


def _is_temporary(name: str) -> bool:
    lowered = name.casefold()
    return name.startswith(".") or any(marker in lowered for marker in TEMP_MARKERS)


def _fingerprint(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def scan(settings: dict, *, now: float | None = None) -> list[dict]:
    """Lista nya, färdigskrivna importfiler. Ingenting öppnas eller ändras."""
    if not isinstance(settings, dict) or not settings.get("enabled"):
        return []
    seen = settings.get("seen") if isinstance(settings.get("seen"), dict) else {}
    found: list[dict] = []
    for folder in normalize_folders(settings.get("folders")):
        base = Path(folder)
        try:
            entries = sorted(base.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            _log.warning("Bevakad mapp kunde inte läsas: %s (%s)", folder, exc)
            continue
        for path in entries:
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                if _is_temporary(path.name) or path.suffix.casefold() not in ALLOWED_SUFFIXES:
                    continue
                st = path.stat()
                if st.st_size <= 0 or st.st_size > MAX_FILE_BYTES:
                    continue
                if now is not None and now - st.st_mtime < SETTLE_SECONDS:
                    # Filen skrivs fortfarande; rapporteras vid nästa kontroll.
                    continue
                key = str(path.resolve())
                mark = _fingerprint(path)
                if seen.get(key) == mark:
                    continue
                found.append({"path": key, "name": path.name, "size": st.st_size,
                              "fingerprint": mark})
                if len(found) >= MAX_REPORTED:
                    return found
            except OSError as exc:
                _log.warning("Filen kunde inte kontrolleras: %s (%s)", path, exc)
    return found


def mark_reported(settings: dict, files: list[dict]) -> dict:
    """Spara att filerna rapporterats, så samma fil inte visas varje gång."""
    if not valid_settings(settings):
        raise ValueError("Ogiltiga bevakningsinställningar")
    seen = dict(settings.get("seen") or {})
    for item in files or []:
        path = item.get("path")
        mark = item.get("fingerprint")
        if isinstance(path, str) and isinstance(mark, str):
            seen[path] = mark
    # Behåll bara de senaste posterna så filen inte växer obegränsat.
    if len(seen) > 500:
        ordered = list(seen.items())[-500:]
        seen = dict(ordered)
    updated = dict(settings)
    updated["seen"] = seen
    return updated


def clear_seen(settings: dict) -> dict:
    updated = dict(settings)
    updated["seen"] = {}
    return updated
