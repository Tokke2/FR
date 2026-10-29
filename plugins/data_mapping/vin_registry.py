# -*- coding: utf-8 -*-
"""
VIN Registry v2.0.0

Central lagring och hantering av VIN-nummer (Vehicle Identification Numbers).

Löser BUGG #4:
    AttributeError: 'VinRegistry' object has no attribute 'get_all'
    Metoden get_all() finns nu och returnerar Dict[str, dict].

ANSVAR:
    - Registrera VIN-nummer med tillhörande fordonsdata
    - Slå upp fordonsdata via VIN
    - Returnera alla registrerade VIN (get_all)
    - Kontrollera om VIN är registrerat
    - Persistent lagring till JSON (data/mappings/vin_registry.json)
    - Historik över registreringar
    - Statistik och diagnostik
    - Import/export av VIN-data
    - Validering av VIN-format (ISO 3779)

Copyright © 2026 Rickard Längkvist
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Final, List, Optional, Set, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "2.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"

REGISTRY_DIR_NAME: Final[str] = "mappings"
REGISTRY_FILENAME: Final[str] = "vin_registry.json"
DATA_DIR: Final[str] = "data"

MAX_HISTORY_ENTRIES: Final[int] = 1000

VIN_LENGTH: Final[int] = 17
VIN_INVALID_CHARS: Final[Set[str]] = {"I", "O", "Q"}
VIN_PATTERN: Final[re.Pattern] = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

VIN_TRANSLITERATION: Final[Dict[str, int]] = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5,
    "6": 6, "7": 7, "8": 8, "9": 9,
}

VIN_WEIGHTS: Final[List[int]] = [
    8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2
]


def get_copyright_string() -> str:
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def get_logger() -> logging.Logger:
    try:
        return logging.getLogger("data_mapping.vin_registry")
    except Exception:
        return logging.getLogger(__name__)


_log = get_logger()


# ══════════════════════════════════════════════════════════════════════════════
# ATOMIC FILE OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_registry_dir() -> Path:
    return Path(DATA_DIR) / REGISTRY_DIR_NAME


def get_registry_path() -> Path:
    return get_registry_dir() / REGISTRY_FILENAME


def atomic_write_json(path: Path, data: Any) -> None:
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=path.stem + "_",
        dir=str(dir_path),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, str(path))
        _log.info("Atomisk skrivning OK: %s", path)
    except Exception:
        _log.exception("Atomisk skrivning misslyckades: %s", path)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_json_safe(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8-sig")
        return json.loads(text)
    except Exception:
        _log.exception("Kunde inte läsa JSON: %s", path)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# VIN VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def validate_vin_format(vin: str) -> Tuple[bool, str]:
    if not vin:
        return False, "VIN är tomt."

    vin_upper = vin.strip().upper()

    if len(vin_upper) != VIN_LENGTH:
        return False, f"VIN måste vara exakt {VIN_LENGTH} tecken (fick {len(vin_upper)})."

    invalid = [c for c in vin_upper if c in VIN_INVALID_CHARS]
    if invalid:
        return False, f"VIN innehåller ogiltiga tecken: {', '.join(invalid)}."

    if not VIN_PATTERN.match(vin_upper):
        return False, "VIN innehåller ogiltiga tecken (tillåtet: A-H, J-N, P-Z, 0-9)."

    return True, ""


def validate_vin_checksum(vin: str) -> Tuple[bool, str]:
    is_valid_format, err = validate_vin_format(vin)
    if not is_valid_format:
        return False, err

    vin_upper = vin.strip().upper()

    try:
        total = 0
        for i, char in enumerate(vin_upper):
            value = VIN_TRANSLITERATION.get(char, 0)
            weight = VIN_WEIGHTS[i]
            total += value * weight

        remainder = total % 11
        check_char = vin_upper[8]

        if remainder == 10:
            expected = "X"
        else:
            expected = str(remainder)

        if check_char == expected:
            return True, ""
        return False, f"Kontrollsiffra fel: fick '{check_char}', förväntade '{expected}'."
    except Exception as exc:
        return False, f"Kontrollsiffra-validering misslyckades: {exc}"


def normalize_vin(vin: str) -> str:
    return str(vin).strip().upper()


def extract_wmi(vin: str) -> str:
    vin_upper = normalize_vin(vin)
    if len(vin_upper) >= 3:
        return vin_upper[:3]
    return ""


def extract_model_year_from_vin(vin: str) -> Optional[int]:
    vin_upper = normalize_vin(vin)
    if len(vin_upper) < 10:
        return None

    year_char = vin_upper[9]

    year_map: Dict[str, int] = {
        "A": 1980, "B": 1981, "C": 1982, "D": 1983, "E": 1984,
        "F": 1985, "G": 1986, "H": 1987, "J": 1988, "K": 1989,
        "L": 1990, "M": 1991, "N": 1992, "P": 1993, "R": 1994,
        "S": 1995, "T": 1996, "V": 1997, "W": 1998, "X": 1999,
        "Y": 2000, "1": 2001, "2": 2002, "3": 2003, "4": 2004,
        "5": 2005, "6": 2006, "7": 2007, "8": 2008, "9": 2009,
    }

    year_map_2010: Dict[str, int] = {
        "A": 2010, "B": 2011, "C": 2012, "D": 2013, "E": 2014,
        "F": 2015, "G": 2016, "H": 2017, "J": 2018, "K": 2019,
        "L": 2020, "M": 2021, "N": 2022, "P": 2023, "R": 2024,
        "S": 2025, "T": 2026, "V": 2027, "W": 2028, "X": 2029,
        "Y": 2030,
    }

    current_year = datetime.now().year

    if year_char in year_map_2010:
        year_2010 = year_map_2010[year_char]
        if year_2010 <= current_year + 1:
            return year_2010

    if year_char in year_map:
        return year_map[year_char]

    return None


# ══════════════════════════════════════════════════════════════════════════════
# VIN ENTRY
# ══════════════════════════════════════════════════════════════════════════════

class VinEntry:
    __slots__ = (
        "vin", "registered_at", "updated_at",
        "data", "source", "tags",
    )

    def __init__(
        self,
        vin: str,
        data: Optional[Dict[str, Any]] = None,
        source: str = "unknown",
        registered_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        self.vin = normalize_vin(vin)
        self.data = dict(data or {})
        self.source = str(source).strip() or "unknown"
        now = datetime.now().isoformat()
        self.registered_at = registered_at or now
        self.updated_at = updated_at or now
        self.tags = list(tags or [])

    def update(
        self,
        data: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
        tags: Optional[List[str]] = None,
        merge_data: bool = True,
    ) -> None:
        if data is not None:
            if merge_data:
                self.data.update(data)
            else:
                self.data = dict(data)
        if source is not None:
            self.source = str(source).strip() or self.source
        if tags is not None:
            self.tags = list(tags)
        self.updated_at = datetime.now().isoformat()

    def add_tag(self, tag: str) -> None:
        tag = str(tag).strip()
        if tag and tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.now().isoformat()

    def remove_tag(self, tag: str) -> bool:
        tag = str(tag).strip()
        if tag in self.tags:
            self.tags.remove(tag)
            self.updated_at = datetime.now().isoformat()
            return True
        return False

    @property
    def wmi(self) -> str:
        return extract_wmi(self.vin)

    @property
    def model_year_from_vin(self) -> Optional[int]:
        return extract_model_year_from_vin(self.vin)

    @property
    def model_year(self) -> Optional[int]:
        try:
            year = self.data.get("model_year")
            if year:
                return int(year)
        except (ValueError, TypeError):
            pass
        return self.model_year_from_vin

    @property
    def model_name(self) -> str:
        return str(self.data.get("model_name", "") or "")

    @property
    def color(self) -> str:
        return str(self.data.get("color_ts_code", "") or self.data.get("color_original", "") or "")

    @property
    def owner_org(self) -> str:
        return str(self.data.get("owner_org", "") or "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vin": self.vin,
            "registered_at": self.registered_at,
            "updated_at": self.updated_at,
            "data": self.data,
            "source": self.source,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VinEntry":
        return cls(
            vin=data.get("vin", ""),
            data=data.get("data", {}),
            source=data.get("source", "unknown"),
            registered_at=data.get("registered_at"),
            updated_at=data.get("updated_at"),
            tags=data.get("tags", []),
        )

    def __repr__(self) -> str:
        return (
            f"VinEntry({self.vin!r}, "
            f"model={self.model_name!r}, "
            f"year={self.model_year}, "
            f"source={self.source!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VinEntry):
            return NotImplemented
        return self.vin == other.vin

    def __hash__(self) -> int:
        return hash(self.vin)


# ══════════════════════════════════════════════════════════════════════════════
# VIN REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

class VinRegistry:
    def __init__(
        self,
        registry_path: Optional[Path] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
        auto_load: bool = True,
        auto_save: bool = True,
    ) -> None:
        self._path = registry_path or get_registry_path()
        self._log_cb = log_callback or (lambda msg, lvl: None)
        self._auto_save = auto_save
        self._entries: Dict[str, VinEntry] = {}
        self._history: List[Dict[str, Any]] = []
        self._loaded = False
        self._dirty = False
        self._callbacks: Dict[str, List[Callable[..., Any]]] = {}

        if auto_load:
            self.load()

    def load(self) -> bool:
        try:
            data = read_json_safe(self._path)
            if data and isinstance(data, dict):
                raw_entries = data.get("entries", {})
                self._entries = {}

                for vin, entry_data in raw_entries.items():
                    if isinstance(entry_data, dict):
                        vin_normalized = normalize_vin(vin)
                        if vin_normalized:
                            try:
                                self._entries[vin_normalized] = VinEntry.from_dict(entry_data)
                            except Exception as exc:
                                _log.warning("Kunde inte läsa VIN-entry %s: %s", vin, exc)

                self._history = list(data.get("history", []))
                if len(self._history) > MAX_HISTORY_ENTRIES:
                    self._history = self._history[-MAX_HISTORY_ENTRIES:]

                self._loaded = True
                self._dirty = False
                self._log_cb(
                    f"Laddade {len(self._entries)} VIN från {self._path.name}",
                    "info",
                )
                return True
            else:
                self._entries = {}
                self._history = []
                self._loaded = True
                self._dirty = False
                return True
        except Exception as exc:
            _log.exception("Kunde inte ladda VIN registry från %s.", self._path)
            self._log_cb(f"Kunde inte ladda VIN registry: {exc}", "warning")
            self._entries = {}
            self._history = []
            self._loaded = True
            self._dirty = False
            return False

    def save(self) -> bool:
        try:
            if len(self._history) > MAX_HISTORY_ENTRIES:
                self._history = self._history[-MAX_HISTORY_ENTRIES:]

            data = {
                "version": VERSION,
                "updated_at": datetime.now().isoformat(),
                "copyright": get_copyright_string(),
                "count": len(self._entries),
                "entries": {
                    vin: entry.to_dict()
                    for vin, entry in sorted(self._entries.items())
                },
                "history": self._history,
            }
            atomic_write_json(self._path, data)
            self._dirty = False
            self._log_cb(
                f"Sparade {len(self._entries)} VIN till {self._path.name}",
                "success",
            )
            return True
        except Exception as exc:
            _log.exception("Kunde inte spara VIN registry till %s.", self._path)
            self._log_cb(f"Kunde inte spara VIN registry: {exc}", "error")
            return False

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def _maybe_save(self) -> None:
        if self._auto_save and self._dirty:
            self.save()

    def _add_history(self, action: str, vin: str, source: str = "", details: str = "") -> None:
        self._history.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "vin": vin,
            "source": source,
            "details": details,
        })
        if len(self._history) > MAX_HISTORY_ENTRIES:
            self._history = self._history[-MAX_HISTORY_ENTRIES:]

    def _notify(self, event: str, **kwargs: Any) -> None:
        for callback in list(self._callbacks.get(event, [])):
            try:
                callback(**kwargs)
            except Exception as exc:
                _log.warning("Callback misslyckades för event '%s': %s", event, exc)

    # ─────────────────────────────────────────────────────────────────────
    # CORE CRUD
    # ─────────────────────────────────────────────────────────────────────

    def register(
        self,
        vin: str,
        data: Optional[Dict[str, Any]] = None,
        source: str = "unknown",
        tags: Optional[List[str]] = None,
        merge_data: bool = True,
        validate: bool = False,
    ) -> bool:
        self._ensure_loaded()

        vin_normalized = normalize_vin(vin)
        if not vin_normalized:
            _log.warning("Tomt VIN — avbryter register().")
            return False

        if validate:
            is_valid, error = validate_vin_format(vin_normalized)
            if not is_valid:
                _log.warning("Ogiltigt VIN-format: %s — %s", vin_normalized, error)
                self._log_cb(f"Ogiltigt VIN: {vin_normalized} — {error}", "warning")
                return False

        existing = self._entries.get(vin_normalized)
        if existing:
            existing.update(data=data, source=source, tags=tags, merge_data=merge_data)
            self._add_history("update", vin_normalized, source)
            self._log_cb(f"VIN uppdaterat: {vin_normalized}", "info")
        else:
            self._entries[vin_normalized] = VinEntry(
                vin=vin_normalized,
                data=data or {},
                source=source,
                tags=tags or [],
            )
            self._add_history("register", vin_normalized, source)
            self._log_cb(f"VIN registrerat: {vin_normalized}", "info")

        self._dirty = True
        self._maybe_save()
        self._notify("register", vin=vin_normalized, source=source, data=data or {})
        return True

    def get(self, vin: str) -> Optional[Dict[str, Any]]:
        self._ensure_loaded()
        vin_normalized = normalize_vin(vin)
        entry = self._entries.get(vin_normalized)
        if entry is not None:
            return dict(entry.data)
        return None

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """BUGG #4 FIX: Returnera alla registrerade VIN."""
        self._ensure_loaded()
        return {
            vin: dict(entry.data)
            for vin, entry in self._entries.items()
        }

    def clear(self) -> None:
        self._ensure_loaded()
        count = len(self._entries)
        self._entries.clear()
        self._add_history("clear", f"{count} VIN rensade")
        self._log_cb(f"Alla {count} VIN rensade.", "info")
        self._dirty = True
        self._maybe_save()
        self._notify("clear", count=count)

    def count(self) -> int:
        self._ensure_loaded()
        return len(self._entries)

    def is_registered(self, vin: str) -> bool:
        self._ensure_loaded()
        return normalize_vin(vin) in self._entries

    def get_entry(self, vin: str) -> Optional[VinEntry]:
        self._ensure_loaded()
        return self._entries.get(normalize_vin(vin))

    def get_all_entries(self) -> List[VinEntry]:
        self._ensure_loaded()
        return sorted(self._entries.values(), key=lambda e: e.vin)

    def get_all_vins(self) -> List[str]:
        self._ensure_loaded()
        return sorted(self._entries.keys())

    def get_registered_vins(self) -> List[str]:
        return self.get_all_vins()

    def unregister(self, vin: str) -> bool:
        self._ensure_loaded()
        vin_normalized = normalize_vin(vin)
        if vin_normalized not in self._entries:
            _log.debug("VIN hittades inte för avregistrering: %s", vin_normalized)
            return False

        del self._entries[vin_normalized]
        self._add_history("unregister", vin_normalized)
        self._log_cb(f"VIN avregistrerat: {vin_normalized}", "info")
        self._dirty = True
        self._maybe_save()
        self._notify("unregister", vin=vin_normalized)
        return True

    # ─────────────────────────────────────────────────────────────────────
    # SEARCH METHODS
    # ─────────────────────────────────────────────────────────────────────

    def find_by_model(self, model_name: str) -> List[VinEntry]:
        self._ensure_loaded()
        model_lower = str(model_name).strip().lower()
        return [
            entry for entry in self._entries.values()
            if model_lower in entry.model_name.lower()
        ]

    def find_by_year(self, year: int) -> List[VinEntry]:
        self._ensure_loaded()
        return [
            entry for entry in self._entries.values()
            if entry.model_year == year
        ]

    def find_by_owner(self, owner_org: str) -> List[VinEntry]:
        self._ensure_loaded()
        org = str(owner_org).strip()
        return [
            entry for entry in self._entries.values()
            if entry.owner_org == org
        ]

    def find_by_source(self, source: str) -> List[VinEntry]:
        self._ensure_loaded()
        source_lower = str(source).strip().lower()
        return [
            entry for entry in self._entries.values()
            if entry.source.lower() == source_lower
        ]

    def find_by_tag(self, tag: str) -> List[VinEntry]:
        self._ensure_loaded()
        tag = str(tag).strip()
        return [
            entry for entry in self._entries.values()
            if tag in entry.tags
        ]

    def find_by_wmi(self, wmi: str) -> List[VinEntry]:
        self._ensure_loaded()
        wmi_upper = str(wmi).strip().upper()
        return [
            entry for entry in self._entries.values()
            if entry.wmi == wmi_upper
        ]

    def search(self, query: str) -> List[VinEntry]:
        self._ensure_loaded()
        query_lower = str(query).strip().lower()
        if not query_lower:
            return self.get_all_entries()

        return [
            entry for entry in self._entries.values()
            if (
                query_lower in entry.vin.lower()
                or query_lower in entry.model_name.lower()
                or query_lower in entry.source.lower()
                or query_lower in entry.owner_org.lower()
                or any(query_lower in tag.lower() for tag in entry.tags)
            )
        ]

    # ─────────────────────────────────────────────────────────────────────
    # TAG MANAGEMENT
    # ─────────────────────────────────────────────────────────────────────

    def add_tag(self, vin: str, tag: str) -> bool:
        self._ensure_loaded()
        entry = self._entries.get(normalize_vin(vin))
        if entry is None:
            return False
        entry.add_tag(tag)
        self._dirty = True
        self._maybe_save()
        return True

    def remove_tag(self, vin: str, tag: str) -> bool:
        self._ensure_loaded()
        entry = self._entries.get(normalize_vin(vin))
        if entry is None:
            return False
        removed = entry.remove_tag(tag)
        if removed:
            self._dirty = True
            self._maybe_save()
        return removed

    def get_all_tags(self) -> List[str]:
        self._ensure_loaded()
        all_tags: Set[str] = set()
        for entry in self._entries.values():
            all_tags.update(entry.tags)
        return sorted(all_tags)

    # ─────────────────────────────────────────────────────────────────────
    # BULK OPERATIONS
    # ─────────────────────────────────────────────────────────────────────

    def bulk_register(
        self,
        records: List[Dict[str, Any]],
        vin_key: str = "vin",
        source: str = "bulk",
        validate: bool = False,
        merge_data: bool = True,
    ) -> Dict[str, Any]:
        self._ensure_loaded()
        result: Dict[str, Any] = {
            "success": False,
            "total": len(records),
            "registered": 0,
            "updated": 0,
            "failed": 0,
            "errors": [],
        }

        if not records:
            return result

        was_auto_save = self._auto_save
        self._auto_save = False

        try:
            for idx, record in enumerate(records):
                try:
                    vin = str(record.get(vin_key, "") or "").strip()
                    if not vin:
                        result["failed"] += 1
                        result["errors"].append(f"Rad {idx}: VIN saknas.")
                        continue

                    vin_normalized = normalize_vin(vin)
                    existed = vin_normalized in self._entries

                    ok = self.register(
                        vin=vin,
                        data={k: v for k, v in record.items() if k != vin_key},
                        source=source,
                        merge_data=merge_data,
                        validate=validate,
                    )
                    if ok:
                        if existed:
                            result["updated"] += 1
                        else:
                            result["registered"] += 1
                    else:
                        result["failed"] += 1
                        result["errors"].append(f"Rad {idx}: VIN {vin} registrering misslyckades.")
                except Exception as exc:
                    result["failed"] += 1
                    result["errors"].append(f"Rad {idx}: {exc}")

            self._add_history(
                "bulk_register",
                f"{result['registered']} nya, {result['updated']} uppdaterade",
                source,
            )

            result["success"] = result["registered"] > 0 or result["updated"] > 0

        finally:
            self._auto_save = was_auto_save
            if self._dirty:
                self.save()

        self._notify(
            "bulk_register",
            registered=result["registered"],
            updated=result["updated"],
            source=source,
        )

        self._log_cb(
            f"Bulk: {result['registered']} nya, {result['updated']} uppdaterade, "
            f"{result['failed']} misslyckade av {result['total']} totalt",
            "info",
        )

        return result

    def merge_from(self, other: "VinRegistry") -> Dict[str, int]:
        self._ensure_loaded()
        result: Dict[str, int] = {"merged": 0, "updated": 0, "skipped": 0}

        for vin, entry in other._entries.items():
            if vin in self._entries:
                self._entries[vin].update(
                    data=entry.data,
                    source=entry.source,
                    merge_data=True,
                )
                result["updated"] += 1
            else:
                self._entries[vin] = VinEntry(
                    vin=entry.vin,
                    data=dict(entry.data),
                    source=entry.source,
                    tags=list(entry.tags),
                )
                result["merged"] += 1

        self._dirty = True
        self._maybe_save()
        return result

    # ─────────────────────────────────────────────────────────────────────
    # EXPORT / IMPORT
    # ─────────────────────────────────────────────────────────────────────

    def export_to_file(self, path: Path) -> bool:
        try:
            self._ensure_loaded()
            path = Path(path)

            data = {
                "version": VERSION,
                "exported_at": datetime.now().isoformat(),
                "copyright": get_copyright_string(),
                "source_file": str(self._path),
                "count": len(self._entries),
                "entries": {
                    vin: entry.to_dict()
                    for vin, entry in sorted(self._entries.items())
                },
            }
            atomic_write_json(path, data)
            self._log_cb(f"Registry exporterad: {path} ({len(self._entries)} VIN)", "success")
            return True
        except Exception as exc:
            _log.exception("export_to_file misslyckades.")
            self._log_cb(f"Export misslyckades: {exc}", "error")
            return False

    def import_from_file(
        self,
        path: Path,
        merge: bool = True,
        validate: bool = False,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "success": False,
            "imported": 0,
            "merged": 0,
            "failed": 0,
            "errors": [],
        }

        try:
            path = Path(path)
            data = read_json_safe(path)
            if not data or not isinstance(data, dict):
                result["errors"].append(f"Ogiltig JSON-fil: {path}")
                return result

            raw_entries = data.get("entries", {})

            if not merge:
                self._entries.clear()

            for vin, entry_data in raw_entries.items():
                try:
                    vin_normalized = normalize_vin(vin)
                    if not vin_normalized:
                        result["failed"] += 1
                        continue

                    if validate:
                        is_valid, error = validate_vin_format(vin_normalized)
                        if not is_valid:
                            result["failed"] += 1
                            result["errors"].append(f"{vin}: {error}")
                            continue

                    if vin_normalized in self._entries:
                        self._entries[vin_normalized].update(
                            data=entry_data.get("data", {}),
                            source=entry_data.get("source", "import"),
                            merge_data=True,
                        )
                        result["merged"] += 1
                    else:
                        self._entries[vin_normalized] = VinEntry.from_dict(entry_data)
                        result["imported"] += 1
                except Exception as exc:
                    result["failed"] += 1
                    result["errors"].append(f"{vin}: {exc}")

            self._add_history(
                "import_from_file",
                str(path),
                details=f"{result['imported']} nya, {result['merged']} mergade",
            )
            self._dirty = True
            self._maybe_save()
            result["success"] = True
            self._log_cb(
                f"Registry importerad: {result['imported']} nya, "
                f"{result['merged']} mergade, {result['failed']} misslyckade",
                "info",
            )
        except Exception as exc:
            _log.exception("import_from_file misslyckades.")
            result["errors"].append(str(exc))

        return result

    # ─────────────────────────────────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────────────────────────────────

    def validate(self, vin: str) -> Tuple[bool, str]:
        return validate_vin_format(vin)

    def validate_checksum(self, vin: str) -> Tuple[bool, str]:
        return validate_vin_checksum(vin)

    def validate_all(self, strict: bool = False) -> Dict[str, List[str]]:
        self._ensure_loaded()
        result: Dict[str, List[str]] = {
            "valid": [],
            "invalid": [],
            "checksum_fail": [],
        }

        for vin in self._entries.keys():
            is_valid, _ = validate_vin_format(vin)
            if not is_valid:
                result["invalid"].append(vin)
                continue

            result["valid"].append(vin)

            if strict:
                checksum_ok, _ = validate_vin_checksum(vin)
                if not checksum_ok:
                    result["checksum_fail"].append(vin)

        return result

    # ─────────────────────────────────────────────────────────────────────
    # HISTORY
    # ─────────────────────────────────────────────────────────────────────

    def get_history(
        self,
        limit: Optional[int] = None,
        action_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_loaded()
        history = list(reversed(self._history))

        if action_filter:
            action_lower = action_filter.lower()
            history = [
                h for h in history
                if h.get("action", "").lower() == action_lower
            ]

        if limit is not None:
            history = history[:limit]

        return history

    def clear_history(self) -> bool:
        self._history.clear()
        self._dirty = True
        self._maybe_save()
        return True

    # ─────────────────────────────────────────────────────────────────────
    # CALLBACKS / EVENTS
    # ─────────────────────────────────────────────────────────────────────

    def subscribe(self, event: str, callback: Callable[..., Any]) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        if callback not in self._callbacks[event]:
            self._callbacks[event].append(callback)

    def unsubscribe(self, event: str, callback: Callable[..., Any]) -> bool:
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)
            return True
        return False

    # ─────────────────────────────────────────────────────────────────────
    # STATISTICS & DIAGNOSTICS
    # ─────────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        self._ensure_loaded()
        entries = list(self._entries.values())

        sources: Dict[str, int] = {}
        for entry in entries:
            sources[entry.source] = sources.get(entry.source, 0) + 1

        wmis: Dict[str, int] = {}
        for entry in entries:
            wmi = entry.wmi
            if wmi:
                wmis[wmi] = wmis.get(wmi, 0) + 1

        years: Dict[int, int] = {}
        for entry in entries:
            year = entry.model_year
            if year:
                years[year] = years.get(year, 0) + 1

        tagged = sum(1 for e in entries if e.tags)

        return {
            "version": VERSION,
            "copyright": get_copyright_string(),
            "total": len(entries),
            "with_data": sum(1 for e in entries if e.data),
            "without_data": sum(1 for e in entries if not e.data),
            "tagged": tagged,
            "sources": dict(sorted(sources.items(), key=lambda x: x[1], reverse=True)),
            "top_wmis": dict(sorted(wmis.items(), key=lambda x: x[1], reverse=True)[:10]),
            "year_distribution": dict(sorted(years.items())),
            "history_entries": len(self._history),
            "file_path": str(self._path),
            "is_dirty": self._dirty,
            "auto_save": self._auto_save,
        }

    def get_diagnostics(self) -> Dict[str, Any]:
        diag = self.get_stats()
        diag["sample_vins"] = self.get_all_vins()[:20]
        diag["all_tags"] = self.get_all_tags()
        diag["validation"] = self.validate_all(strict=False)
        return diag

    # ─────────────────────────────────────────────────────────────────────
    # PROPERTIES
    # ─────────────────────────────────────────────────────────────────────

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def registry_path(self) -> Path:
        return self._path

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._entries)

    def __contains__(self, vin: str) -> bool:
        self._ensure_loaded()
        return normalize_vin(vin) in self._entries

    def __repr__(self) -> str:
        return (
            f"VinRegistry("
            f"count={len(self._entries)}, "
            f"path={self._path.name!r}, "
            f"loaded={self._loaded})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# FACTORY / CONVENIENCE
# ══════════════════════════════════════════════════════════════════════════════

default_registry: Optional[VinRegistry] = None


def get_vin_registry(
    log_callback: Optional[Callable[[str, str], None]] = None,
    auto_load: bool = True,
    auto_save: bool = True,
) -> VinRegistry:
    global default_registry
    if default_registry is None:
        default_registry = VinRegistry(
            log_callback=log_callback,
            auto_load=auto_load,
            auto_save=auto_save,
        )
    return default_registry


def reset_default_registry() -> None:
    global default_registry
    default_registry = None


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "VinRegistry",
    "VinEntry",
    "validate_vin_format",
    "validate_vin_checksum",
    "normalize_vin",
    "extract_wmi",
    "extract_model_year_from_vin",
    "get_vin_registry",
    "reset_default_registry",
    "VIN_LENGTH",
    "VIN_PATTERN",
    "VERSION",
    "AUTHOR",
]