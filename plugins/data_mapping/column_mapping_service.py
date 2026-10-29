# -*- coding: utf-8 -*-
"""
Column Mapping Service v2.0.0

Central tjänst för kolumnmappning mellan källdata och TS-fältnamn.
Hanterar persistent lagring, auto-detektering, synonymer och validering.

Löser BUGG #2:
    NameError: ColumnMappingService is not defined

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
from typing import Any, Callable, Dict, Final, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "2.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"

MAPPINGS_DIR_NAME: Final[str] = "mappings"
MAPPINGS_FILENAME: Final[str] = "column_mappings.json"
DATA_DIR: Final[str] = "data"

MAX_HISTORY_ENTRIES: Final[int] = 500


def get_copyright_string() -> str:
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def get_logger() -> logging.Logger:
    try:
        return logging.getLogger("data_mapping.column_mapping_service")
    except Exception:
        return logging.getLogger(__name__)


_log = get_logger()


# ══════════════════════════════════════════════════════════════════════════════
# KNOWN COLUMN SYNONYMS (MAPPED TO THE 32 EXACT FORDONSDATA-TARGETS)
# ══════════════════════════════════════════════════════════════════════════════

COLUMN_SYNONYMS: Final[Dict[str, Tuple[str, str]]] = {
    # 1. MODELYEAR
    "modelyear": ("MODELYEAR", "Model year / Modellår"),
    "modellar": ("MODELYEAR", "Modellår"),
    "arsmodell": ("MODELYEAR", "Årsmodell"),
    "year": ("MODELYEAR", "År"),
    "ar": ("MODELYEAR", "År"),
    "tillverkningsar": ("MODELYEAR", "Tillverkningsår"),
    "productionyear": ("MODELYEAR", "Production year"),
    "my": ("MODELYEAR", "Model Year (MY)"),

    # 2. VINCODE
    "vincode": ("VINCODE", "Vehicle Identification Number / VIN-kod"),
    "vin": ("VINCODE", "VIN-nummer"),
    "vinnumber": ("VINCODE", "VIN-nummer"),
    "vinnr": ("VINCODE", "VIN-nummer"),
    "chassinummer": ("VINCODE", "Chassinummer"),
    "chassinr": ("VINCODE", "Chassinummer"),
    "chassi": ("VINCODE", "Chassi"),
    "frameno": ("VINCODE", "Frame number"),
    "frame": ("VINCODE", "Frame number"),

    # 3. TYPE
    "type": ("TYPE", "Vehicle type / Typ"),
    "typ": ("TYPE", "Typ"),
    "fordonstyp": ("TYPE", "Fordonstyp"),
    "vehicletype": ("TYPE", "Vehicle type"),

    # 4. VARIANTE
    "variante": ("VARIANTE", "Variant / Variante"),
    "variant": ("VARIANTE", "Variant"),

    # 5. VERSION
    "version": ("VERSION", "Version"),

    # 6. MODELNAME
    "modelname": ("MODELNAME", "Model name / Modellnamn"),
    "modell": ("MODELNAME", "Modellnamn"),
    "modellnamn": ("MODELNAME", "Modellnamn"),
    "model": ("MODELNAME", "Model name"),
    "vehiclemodel": ("MODELNAME", "Vehicle model"),
    "fordonsmodell": ("MODELNAME", "Fordonsmodell"),

    # 7. COMNAME
    "comname": ("COMNAME", "Commercial name / Handelsbeteckning"),
    "commercialname": ("COMNAME", "Commercial name"),
    "handelsbeteckning": ("COMNAME", "Handelsbeteckning"),
    "modellbeskrivning": ("COMNAME", "Modellbeskrivning"),
    "modelldescription": ("COMNAME", "Modellbeskrivning"),

    # 8. CLASS
    "class": ("CLASS", "Vehicle class / Klass"),
    "klass": ("CLASS", "Klass"),
    "vehicleclass": ("CLASS", "Vehicle class"),

    # 9. VEHCAT2
    "vehcat2": ("VEHCAT2", "Vehicle category EU / Fordonskategori"),
    "vehcat": ("VEHCAT2", "Vehicle category"),
    "category": ("VEHCAT2", "Category"),
    "kategori": ("VEHCAT2", "Kategori"),
    "fordonskategori": ("VEHCAT2", "Fordonskategori"),

    # 10. APPROVAL
    "approval": ("APPROVAL", "Type approval / Typgodkännandenummer"),
    "typgodkannande": ("APPROVAL", "Typgodkännandenummer"),
    "typgodkannandenummer": ("APPROVAL", "Typgodkännandenummer"),
    "typeapproval": ("APPROVAL", "Type approval"),
    "typeapprovalnum": ("APPROVAL", "Type approval number"),
    "wvta": ("APPROVAL", "WVTA approval number"),
    "coc": ("APPROVAL", "CoC approval"),

    # 11. DATEAPP
    "dateapp": ("DATEAPP", "Approval date / Godkännandedatum"),
    "godkannandedatum": ("DATEAPP", "Godkännandedatum"),
    "approvaldate": ("DATEAPP", "Approval date"),
    "dateofapproval": ("DATEAPP", "Date of approval"),

    # 12. NUMAXLE
    "numaxle": ("NUMAXLE", "Number of axles / Antal axlar"),
    "axlar": ("NUMAXLE", "Antal axlar"),
    "antalaxlar": ("NUMAXLE", "Antal axlar"),
    "numberofaxles": ("NUMAXLE", "Number of axles"),

    # 13. NUMWHEEL
    "numwheel": ("NUMWHEEL", "Number of wheels / Antal hjul"),
    "hjul": ("NUMWHEEL", "Antal hjul"),
    "antalhjul": ("NUMWHEEL", "Antal hjul"),
    "numberofwheels": ("NUMWHEEL", "Number of wheels"),

    # 14. ANTILBS
    "antilbs": ("ANTILBS", "Anti-lock braking system / ABS"),
    "abs": ("ANTILBS", "ABS"),
    "bromsar": ("ANTILBS", "Bromssystem"),
    "antilockbrakes": ("ANTILBS", "Anti-lock brakes"),

    # 15. LENGTH
    "length": ("LENGTH", "Length in mm / Längd"),
    "langd": ("LENGTH", "Längd"),

    # 16. WIDTH
    "width": ("WIDTH", "Width in mm / Bredd"),
    "bredd": ("WIDTH", "Bredd"),

    # 17. HEIGHT
    "height": ("HEIGHT", "Height in mm / Höjd"),
    "hojd": ("HEIGHT", "Höjd"),

    # 18. MASS
    "mass": ("MASS", "Unladen mass / Tjänstevikt (kg)"),
    "tjanstevikt": ("MASS", "Tjänstevikt"),
    "kerbweight": ("MASS", "Kerb weight"),
    "unladenmass": ("MASS", "Unladen mass"),
    "vikt": ("MASS", "Vikt"),

    # 19. LADENMASS
    "ladenmass": ("LADENMASS", "Gross vehicle mass / Totalvikt (kg)"),
    "totalvikt": ("LADENMASS", "Totalvikt"),
    "maxweight": ("LADENMASS", "Max weight"),
    "gvw": ("LADENMASS", "Gross Vehicle Weight"),
    "grossweight": ("LADENMASS", "Gross weight"),

    # 20. CYLCAPACITY
    "cylcapacity": ("CYLCAPACITY", "Cylinder capacity / Cylindervolym (cm3)"),
    "cylindervolym": ("CYLCAPACITY", "Cylindervolym"),
    "cc": ("CYLCAPACITY", "Cylinder capacity"),
    "capacity": ("CYLCAPACITY", "Capacity"),
    "volym": ("CYLCAPACITY", "Volym"),

    # 21. MAXPOWER
    "maxpower": ("MAXPOWER", "Maximum net power (kW) / Effekt"),
    "power": ("MAXPOWER", "Power"),
    "powerkw": ("MAXPOWER", "Power (kW)"),
    "effekt": ("MAXPOWER", "Effekt"),
    "effektkw": ("MAXPOWER", "Effekt (kW)"),
    "kw": ("MAXPOWER", "kW"),
    "maxpowerkw": ("MAXPOWER", "Max power (kW)"),

    # 22. MAXNET
    "maxnet": ("MAXNET", "Maximum net torque (Nm) / Vridmoment"),
    "torque": ("MAXNET", "Torque"),
    "vridmoment": ("MAXNET", "Vridmoment"),
    "maxnettorque": ("MAXNET", "Max net torque"),

    # 23. SPEED
    "speed": ("SPEED", "Maximum speed (km/h) / Toppfart"),
    "toppfart": ("SPEED", "Toppfart"),
    "hastighet": ("SPEED", "Maxhastighet"),
    "maxspeed": ("SPEED", "Maximum speed"),

    # 24. TYRESIZE1
    "tyresize1": ("TYRESIZE1", "Tyre size axle 1 / Däckdimension 1"),
    "dackdimension1": ("TYRESIZE1", "Däckdimension axel 1"),
    "tyres1": ("TYRESIZE1", "Tyres axle 1"),
    "dack1": ("TYRESIZE1", "Däck axel 1"),

    # 25. TYRESIZE2
    "tyresize2": ("TYRESIZE2", "Tyre size axle 2 / Däckdimension 2"),
    "dackdimension2": ("TYRESIZE2", "Däckdimension axel 2"),
    "tyres2": ("TYRESIZE2", "Tyres axle 2"),
    "dack2": ("TYRESIZE2", "Däck axel 2"),

    # 26. SEATS
    "seats": ("SEATS", "Number of seats / Antal platser"),
    "platser": ("SEATS", "Antal sittplatser"),
    "sittplatser": ("SEATS", "Antal sittplatser"),
    "numberofseats": ("SEATS", "Number of seats"),

    # 27. EMISLVL
    "emislvl": ("EMISLVL", "Emission level / Miljöklass"),
    "miljoklass": ("EMISLVL", "Miljöklass"),
    "emissionlevel": ("EMISLVL", "Emission level"),

    # 28. STATIONARY
    "stationary": ("STATIONARY", "Stationary noise level (dB) / Buller stillastående"),
    "bullerstillastaende": ("STATIONARY", "Buller stillastående"),
    "stationarynoise": ("STATIONARY", "Stationary noise"),

    # 29. STATENG
    "stateng": ("STATENG", "Engine speed for stationary noise / Varvtal buller"),
    "bullervarvtal": ("STATENG", "Varvtal för bullermätning"),
    "stationaryenginespeed": ("STATENG", "Stationary engine speed"),

    # 30. DRIVEBY
    "driveby": ("DRIVEBY", "Drive-by noise level (dB) / Buller vid körning"),
    "bullerkorning": ("DRIVEBY", "Buller vid körning"),
    "drivebynoise": ("DRIVEBY", "Drive-by noise"),

    # 31. EMSTAGE
    "emstage": ("EMSTAGE", "Emission stage / Utsläppsklass"),
    "utslappsklass": ("EMSTAGE", "Utsläppsklass"),
    "emissionstage": ("EMSTAGE", "Emission stage"),

    # 32. EECO2E
    "eeco2e": ("EECO2E", "CO2 emissions / CO2-utsläpp (g/km)"),
    "co2": ("EECO2E", "CO2"),
    "co2utslapp": ("EECO2E", "CO2-utsläpp"),
    "co2gkm": ("EECO2E", "CO2 g/km"),
    "co2emissions": ("EECO2E", "CO2 emissions"),
}


# ══════════════════════════════════════════════════════════════════════════════
# NORMALIZATION
# ══════════════════════════════════════════════════════════════════════════════

def normalize_column_name(name: str) -> str:
    text = str(name).strip().lower()

    replacements = {
        "å": "a", "ä": "a", "ö": "o",
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "ü": "u", "ú": "u", "ù": "u", "û": "u",
        "ñ": "n", "ï": "i", "î": "i", "ì": "i",
        "à": "a", "â": "a", "ã": "a",
        "ô": "o", "ò": "o", "õ": "o",
        "ç": "c", "ß": "ss",
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)

    text = re.sub(r"[^a-z0-9]", "", text)
    text = text.strip("_")
    return text


# ══════════════════════════════════════════════════════════════════════════════
# ATOMIC FILE OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_mappings_dir() -> Path:
    return Path(DATA_DIR) / MAPPINGS_DIR_NAME


def get_mappings_path() -> Path:
    return get_mappings_dir() / MAPPINGS_FILENAME


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
# MAPPING ENTRY
# ══════════════════════════════════════════════════════════════════════════════

class MappingEntry:
    __slots__ = (
        "source", "target", "description",
        "auto_detected", "confidence",
        "created_at", "updated_at",
    )

    def __init__(
        self,
        source: str,
        target: str = "",
        description: str = "",
        auto_detected: bool = False,
        confidence: float = 1.0,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ) -> None:
        self.source = str(source).strip()
        self.target = str(target).strip()
        self.description = str(description).strip()
        self.auto_detected = bool(auto_detected)
        self.confidence = max(0.0, min(1.0, float(confidence)))
        now = datetime.now().isoformat()
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def update(self, target: str, description: str = "", confidence: float = 1.0) -> None:
        self.target = str(target).strip()
        if description:
            self.description = str(description).strip()
        self.confidence = max(0.0, min(1.0, float(confidence)))
        self.updated_at = datetime.now().isoformat()
        self.auto_detected = False

    @property
    def is_mapped(self) -> bool:
        return bool(self.target)

    @property
    def is_manual(self) -> bool:
        return not self.auto_detected

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "description": self.description,
            "auto_detected": self.auto_detected,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MappingEntry":
        return cls(
            source=data.get("source", ""),
            target=data.get("target", ""),
            description=data.get("description", ""),
            auto_detected=bool(data.get("auto_detected", False)),
            confidence=float(data.get("confidence", 1.0)),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def __repr__(self) -> str:
        mapped = f" → {self.target}" if self.target else " (ej mappad)"
        auto = " [auto]" if self.auto_detected else ""
        return f"MappingEntry({self.source!r}{mapped}{auto})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MappingEntry):
            return NotImplemented
        return self.source == other.source

    def __hash__(self) -> int:
        return hash(self.source)


# ══════════════════════════════════════════════════════════════════════════════
# COLUMN MAPPING SERVICE
# ══════════════════════════════════════════════════════════════════════════════

class ColumnMappingService:
    def __init__(
        self,
        mappings_path: Optional[Path] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._path = mappings_path or get_mappings_path()
        self._log_cb = log_callback or (lambda msg, lvl: None)
        self._entries: Dict[str, MappingEntry] = {}
        self._history: List[Dict[str, Any]] = []
        self._loaded = False
        self._dirty = False

    # ── LOAD / SAVE ──

    def load(self) -> bool:
        try:
            data = read_json_safe(self._path)
            if data and isinstance(data, dict):
                raw_mappings = data.get("mappings", [])
                self._entries = {}
                for item in raw_mappings:
                    if isinstance(item, dict) and item.get("source"):
                        entry = MappingEntry.from_dict(item)
                        self._entries[entry.source] = entry

                self._history = list(data.get("history", []))
                if len(self._history) > MAX_HISTORY_ENTRIES:
                    self._history = self._history[-MAX_HISTORY_ENTRIES:]

                self._loaded = True
                self._dirty = False
                self._log_cb(f"Laddade {len(self._entries)} mappningar från {self._path.name}", "info")
                return True
            else:
                self._entries = {}
                self._history = []
                self._loaded = True
                self._dirty = False
                return True
        except Exception as exc:
            _log.exception("Kunde inte ladda mappningar från %s.", self._path)
            self._log_cb(f"Kunde inte ladda mappningar: {exc}", "warning")
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
                "mappings": [
                    entry.to_dict()
                    for entry in sorted(self._entries.values(), key=lambda e: e.source)
                ],
                "history": self._history,
            }
            atomic_write_json(self._path, data)
            self._dirty = False
            self._log_cb(f"Sparade {len(self._entries)} mappningar till {self._path.name}", "success")
            return True
        except Exception as exc:
            _log.exception("Kunde inte spara mappningar till %s.", self._path)
            self._log_cb(f"Kunde inte spara mappningar: {exc}", "error")
            return False

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def _add_history(self, action: str, source: str, target: str = "", details: str = "") -> None:
        self._history.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "source": source,
            "target": target,
            "details": details,
        })

    # ── CRUD ──

    def set_mapping(
        self,
        source: str,
        target: str,
        description: str = "",
        auto_detected: bool = False,
        confidence: float = 1.0,
        auto_save: bool = True,
    ) -> bool:
        self._ensure_loaded()
        source = str(source).strip()
        target = str(target).strip()

        if not source:
            _log.warning("Tomt källnamn — avbryter set_mapping.")
            return False

        existing = self._entries.get(source)
        if existing:
            existing.update(target, description, confidence)
            self._add_history("update", source, target)
            self._log_cb(f"Mappning uppdaterad: {source} → {target}", "info")
        else:
            entry = MappingEntry(
                source=source,
                target=target,
                description=description,
                auto_detected=auto_detected,
                confidence=confidence,
            )
            self._entries[source] = entry
            self._add_history("add", source, target)
            self._log_cb(f"Ny mappning: {source} → {target}", "info")

        self._dirty = True
        if auto_save:
            return self.save()
        return True

    def remove_mapping(self, source: str, auto_save: bool = True) -> bool:
        self._ensure_loaded()
        source = str(source).strip()

        if source not in self._entries:
            return False

        old_target = self._entries[source].target
        del self._entries[source]
        self._add_history("delete", source, old_target)
        self._log_cb(f"Mappning borttagen: {source}", "info")

        self._dirty = True
        if auto_save:
            return self.save()
        return True

    def get_target(self, source: str) -> Optional[str]:
        self._ensure_loaded()
        entry = self._entries.get(str(source).strip())
        if entry and entry.is_mapped:
            return entry.target
        return None

    def get_entry(self, source: str) -> Optional[MappingEntry]:
        self._ensure_loaded()
        return self._entries.get(str(source).strip())

    def has_mapping(self, source: str) -> bool:
        self._ensure_loaded()
        return str(source).strip() in self._entries

    def is_mapped(self, source: str) -> bool:
        self._ensure_loaded()
        entry = self._entries.get(str(source).strip())
        return entry is not None and entry.is_mapped

    # ── BATCH ──

    def get_all_mappings(self) -> List[MappingEntry]:
        self._ensure_loaded()
        return sorted(self._entries.values(), key=lambda e: e.source)

    def get_mapping_dict(self) -> Dict[str, str]:
        self._ensure_loaded()
        return {
            entry.source: entry.target
            for entry in self._entries.values()
            if entry.is_mapped
        }

    def get_all_as_dicts(self) -> List[Dict[str, str]]:
        self._ensure_loaded()
        return [
            {
                "source": entry.source,
                "target": entry.target,
                "description": entry.description,
            }
            for entry in sorted(self._entries.values(), key=lambda e: e.source)
        ]

    def auto_populate_from_headers(self, headers: List[str], auto_save: bool = True) -> int:
        self._ensure_loaded()
        added = 0
        for header in headers:
            header = str(header).strip()
            if header and header not in self._entries:
                self._entries[header] = MappingEntry(source=header, target="", description="")
                added += 1

        if added > 0:
            self._add_history("auto_populate", f"{added} headers", details="from import")
            self._log_cb(f"{added} nya kolumner tillagda", "info")
            self._dirty = True
            if auto_save:
                self.save()

        return added

    def clear_all(self, auto_save: bool = True) -> bool:
        count = len(self._entries)
        self._entries.clear()
        self._add_history("clear_all", f"{count} mappningar")
        self._log_cb(f"Alla {count} mappningar rensade", "info")
        self._dirty = True
        if auto_save:
            return self.save()
        return True

    # ── AUTO-DETECTION ──

    def auto_detect(
        self,
        headers: List[str],
        overwrite_existing: bool = False,
        auto_save: bool = True,
    ) -> Dict[str, Tuple[str, float, str]]:
        self._ensure_loaded()
        detected: Dict[str, Tuple[str, float, str]] = {}
        updated = 0

        for header in headers:
            header = str(header).strip()
            if not header:
                continue
            if not overwrite_existing and self.is_mapped(header):
                continue

            result = self._detect_single(header)
            if result is None:
                continue

            target, confidence, description = result
            detected[header] = (target, confidence, description)

            existing = self._entries.get(header)
            if existing:
                if overwrite_existing or not existing.is_mapped:
                    existing.update(target, description, confidence)
                    existing.auto_detected = True
                    updated += 1
            else:
                self._entries[header] = MappingEntry(
                    source=header,
                    target=target,
                    description=description,
                    auto_detected=True,
                    confidence=confidence,
                )
                updated += 1

        if updated > 0:
            self._add_history("auto_detect", f"{updated} mappningar", details="synonym-match")
            self._log_cb(f"Auto-detekterade {updated} mappningar av {len(headers)} headers", "info")
            self._dirty = True
            if auto_save:
                self.save()

        return detected

    def _detect_single(self, header: str) -> Optional[Tuple[str, float, str]]:
        header_lower = header.strip().lower()
        header_normalized = normalize_column_name(header)

        if not header_normalized:
            return None

        if header_lower in COLUMN_SYNONYMS:
            target, desc = COLUMN_SYNONYMS[header_lower]
            return (target, 1.0, f"Exakt match: {desc}")

        if header_normalized in COLUMN_SYNONYMS:
            target, desc = COLUMN_SYNONYMS[header_normalized]
            return (target, 0.9, f"Normaliserad match: {desc}")

        best_match = None
        best_length = 0

        for synonym_key, (target, desc) in COLUMN_SYNONYMS.items():
            if len(synonym_key) < 3:
                continue
            if synonym_key in header_normalized or header_normalized in synonym_key:
                match_length = min(len(synonym_key), len(header_normalized))
                if match_length > best_length:
                    best_length = match_length
                    ratio = match_length / max(len(synonym_key), len(header_normalized))
                    confidence = max(0.4, min(0.8, ratio))
                    best_match = (target, confidence, f"Delvis match ({synonym_key}): {desc}")

        return best_match

    # ── APPLY ──

    def apply_to_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_loaded()
        mapped_record: Dict[str, Any] = {}
        mapping_dict = self.get_mapping_dict()

        for source, value in record.items():
            target = mapping_dict.get(source)
            if target:
                mapped_record[target] = value
            else:
                mapped_record[source] = value

        return mapped_record

    # ── STATS ──

    def get_stats(self) -> Dict[str, Any]:
        self._ensure_loaded()
        all_entries = list(self._entries.values())
        mapped = [e for e in all_entries if e.is_mapped]
        return {
            "version": VERSION,
            "total": len(all_entries),
            "mapped": len(mapped),
            "unmapped": len(all_entries) - len(mapped),
            "file_path": str(self._path),
        }


# ══════════════════════════════════════════════════════════════════════════════
# FACTORY
# ══════════════════════════════════════════════════════════════════════════════

default_service: Optional[ColumnMappingService] = None


def get_column_mapping_service(
    log_callback: Optional[Callable[[str, str], None]] = None,
) -> ColumnMappingService:
    global default_service
    if default_service is None:
        default_service = ColumnMappingService(log_callback=log_callback)
    return default_service


def reset_default_service() -> None:
    global default_service
    default_service = None


__all__ = [
    "ColumnMappingService",
    "MappingEntry",
    "COLUMN_SYNONYMS",
    "normalize_column_name",
    "get_column_mapping_service",
    "reset_default_service",
    "VERSION",
    "AUTHOR",
]