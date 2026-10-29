# -*- coding: utf-8 -*-
# plugins/vehicle_registry/excel_importer.py
"""
Excel Modellimport för Vehicle Registry v1.2.0
Importerar modelldata från Excel-filer till vehicle_registry.
Stöder VINCODE som VIN-prefix (3-8 tecken, EJ 17-teckens VIN).
Konfigurerbar fältmappning (Excel-kolumn → internt fält).
ANSVAR:
  - Läsa Excel-filer med header-detektion
  - Upptäcka rubriker (rad 1 = titlar direkt, KRAV 40)
  - Föreslå och tillämpa kolumnmappning mot vehicle_registry-fält
  - SPEC v7.0: VINCODE-matchning via tecken 2-4
  - Gruppera per årsmodell → spara till {year}.json
  - Merge med befintlig data (upsert per vin_kod)
  - Konfliktdetektering och upplösning (replace/skip/merge/ask)
  - Persistent lagring av fältmappning med fingerprint
  - Lösenordsskydd vid ändring av sparad mappning (KRAV 36)
IMPORTER:
  json, logging, os, re, tempfile, hashlib, datetime, pathlib, typing
  pandas (valfri, kontrolleras vid runtime)
EXPORTERAR:
  DEFAULT_COLUMN_MAPPING     — standardmappning (33 fält)
  import_excel_to_registry() — huvudfunktion
  ExcelModelImporter         — klass med full funktionalitet
ANVÄNDS AV:
  plugins/vehicle_registry/plugin.py
    → Plugin.import_from_excel()
    → Plugin.get_column_mapping()
    → Plugin.set_column_mapping()
DATALAGRING (spec v1.4 / Sektion Z):
  json/mappings/column_mapping.json            (aktiv fältmappning)
  json/mappings/vehicle_import_mapping.json    (fingerprint-mappningar,
                                               PIN-skyddade, KRAV 34-36/41)
  data/vehicles/{YYYY}.json                    (via vehicle_storage)
  (data/vehicle_registry/column_mapping.json och
   data/mappings/vehicle_import_mapping.json läses som FALLBACK tills
   migrerade — se Sektion Z.)
FÖRÄNDRINGAR v1.2.0 (spec v1.4-anpassning av levererad v1.2.0-draft):
  - KRAV 40: RAD 1 (index 0) läses DIREKT som rubriker i varje blad.
    Rad 1 tom/oläsbar → fallback-skanning rad 1-9 (loggas INFO). Hittas
    ingen användbar rubrikrad → bladet skippas MED RAPPORT (aldrig tyst).
  - Sektion Z: mappning-JSON under json/mappings/ (mapping_dir) —
    column_mapping.json + vehicle_import_mapping.json. Gamla sökvägar
    (data/vehicle_registry/column_mapping.json,
     data/mappings/vehicle_import_mapping.json) läses som fallback om
    de nya saknas (loggas INFO).
  - P14: fingerprint = md5 över normaliserade rubriker i ORDNING
    (alla blad, i följd; dubbletter tas bort, första förekomst behålls).
    Tidigare: sha256 av sorterade rubriker från första bladet.
FÖRÄNDRINGAR v1.2.0:
  - NY: detect_headers() för att läsa rad 1-titlar per blad.
  - NY: Fingerprint-baserad mappning med suggest_mapping().
        Sparas i json/mappings/vehicle_import_mapping.json.
  - NY: Konfliktdetektering och upplösning (replace/skip/merge/ask).
  - NY: preview_import() för torrkörning/förhandsgranskning.
  - NY: Lösenordsskydd (PIN-hash) för ändring av sparad mappning.
  - Förbättrad felrapportering per rad (source_sheet, source_row).
  - VERSION bump → 1.2.0
FÖRÄNDRINGAR v1.1.0:
  - SPEC v7.0: VINCODE-värden konverteras till VIN3 via tecken 2-4.
  - Ogiltiga VINCODE-värden räknas som skipped.
  - Final-omtilldelning för HAS_PANDAS fixad.
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    Any, Callable, Dict, Final, List,
    Optional, Set, Tuple,
)
try:
    import pandas as pd
    _PANDAS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore[assignment]
    _PANDAS_AVAILABLE = False
HAS_PANDAS: Final[bool] = _PANDAS_AVAILABLE

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER

# ══════════════════════════════════════════════════════════════════════════════
_log: logging.Logger = logging.getLogger("vehicle_registry.excel_importer")

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS

# ══════════════════════════════════════════════════════════════════════════════
VERSION: Final[str] = "1.2.0"
AUTHOR: Final[str] = "Rickard Längkvist"
# SPEC v7.0: VINCODE-matchning använder tecken 2-4 ur VIN/VIN-prefix
# (1-indexerade positioner 2, 3 och 4 = Python-slice [1:4]).
VIN3_SLICE_START: Final[int] = 1
VIN3_SLICE_END: Final[int] = 4
VIN3_PATTERN: Final[re.Pattern] = re.compile(r"^[A-Z0-9]{3}$")
# Filnamn för persistenta mappningar
ACTIVE_MAPPING_FILENAME: Final[str] = "column_mapping.json"
VEHICLE_IMPORT_MAPPING_FILENAME: Final[str] = "vehicle_import_mapping.json"

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"

class ConflictAction(str, Enum):
    """Åtgärder vid dublett-VIN3 vid import."""
    REPLACE = "replace"
    SKIP = "skip"
    MERGE = "merge"
    ASK = "ask"

# ── KONFIGURERBAR FÄLTMAPPNING ──
# Mappar normaliserade Excel-kolumnnamn → vehicle_registry internt fältnamn.
# "_year" är speciellt: anger årsmodell (används för filnamn/bladnamn).
DEFAULT_COLUMN_MAPPING: Final[Dict[str, str]] = {
    # Identitet
    "MODEL": "_year",
    "VINCODE": "vin_kod",
    "TYPE": "typ",
    "VARIANTE": "variant",
    "VERSION": "version",
    "MODELNAME": "modellkod",
    "COMNAME": "handelsbeteckning",
    "CLASS": "fordonsklass",
    "VEHCA": "fordonskategori",
    "VEHCAT2": "fordonskategori",
    # Godkännande
    "APPROVAL": "avgaskrav_tillagg",
    "DATEAPP": "godkannandedatum",
    # Dimensioner
    "NUMAXLE": "antal_axlar",
    "NUMWHEEL": "antal_hjul",
    "ANTILBS": "bromsar",
    "LENGTH": "langd_mm",
    "WIDTH": "bredd_mm",
    "HEIGHT": "hojd_mm",
    # Vikt
    "MASS": "vikt_kor_klar_kg",
    "LADENMASS": "totalvikt_kg",
    # Motor
    "CYLCAPACITY": "slagvolym_cm3",
    "MAXPOWER": "effekt_kw",
    "MAXNET": "max_vridmoment",
    "SPEED": "max_hastighet_kmh",
    "FUEL": "bransle1",
    # Däck
    "TYRESIZE1": "dack_fram",
    "TYRESIZE2": "dack_bak",
    # Övrigt
    "SEATS": "antal_platser",
    "EMISLVL": "euroklass",
    "STATIONARY": "ljud_stillas_db",
    "STATENG": "ljud_varvtal",
    "DRIVEBY": "ljud_korning_db",
    "EMSTAGE": "utslappsklass",
    "EECO2E": "co2_utslapp",
}
# Blad att hoppa över
SKIP_SHEETS: Final[List[str]] = [
    "25kw", "25kwh", "kw", "kwh", "info", "mall",
    "template", "instruktioner",
]

# ══════════════════════════════════════════════════════════════════════════════
# DATAKLASSER

# ══════════════════════════════════════════════════════════════════════════════

@dataclass

class ConflictInfo:
    """Information om en VIN3-konflikt mellan befintlig och inkommande post."""
    vin_kod: str
    year: int
    existing: Dict[str, Any] = field(default_factory=dict)
    incoming: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vin_kod": self.vin_kod,
            "year": self.year,
            "existing": dict(self.existing),
            "incoming": dict(self.incoming),
        }

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS

# ══════════════════════════════════════════════════════════════════════════════

def _normalize_column_name(name: str) -> str:
    """Normalisera kolumnnamn: UPPER, strip accenter, strip icke-alfanum."""
    if not name:
        return ""
    x = str(name).strip().upper()
    x = (
        x.replace("Å", "A").replace("Ä", "A").replace("Ö", "O")
        .replace("É", "E").replace("È", "E").replace("Ü", "U")
        .replace("Ñ", "N")
    )
    x = re.sub(r"[\W_]+", "", x)
    return x

def _extract_vin3_from_value(value: str) -> Optional[str]:
    """
    Extrahera VIN3 från ett VINCODE-värde (SPEC v7.0).
    Regel (konsistent med extract_vin3_from_full i plugin.py):
      - Exakt 3 tecken  -> tolkas som färdig VIN3-kod
      - 4+ tecken       -> tecken 2-4 extraheras (slice [1:4])
      - <3 tecken       -> ogiltigt -> None
    Returnerar validerad VIN3 (A-Z0-9, 3 tecken) eller None.
    """
    if not value:
        return None
    clean = re.sub(r"[^A-Z0-9]", "", str(value).strip().upper())
    if len(clean) == 3:
        code = clean
    elif len(clean) >= VIN3_SLICE_END:
        code = clean[VIN3_SLICE_START:VIN3_SLICE_END]
    else:
        return None
    if VIN3_PATTERN.match(code):
        return code
    return None

def _should_skip_sheet(name: str) -> bool:
    """Kontrollera om blad ska hoppas över."""
    n = str(name).strip().lower()
    if n in SKIP_SHEETS:
        return True
    if n.endswith("kw") or n.endswith("kwh"):
        return True
    return False

def _atomic_write_json(path: Path, data: Any) -> None:
    """Atomisk JSON-skrivning: mkstemp → fdopen → fsync → os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=f".{path.name}.tmp_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

def _read_json_safe(path: Path, default: Any = None) -> Any:
    """Läs JSON kraschsäkert."""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except Exception:
        pass
    return default

def _hash_pin(pin: str, fingerprint: str) -> str:
    """Skapa enkel SHA-256-hash av PIN med fingerprint som salt."""
    if not pin:
        return ""
    data = f"{pin}:{fingerprint}".encode("utf-8")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"

def _verify_pin(pin: str, fingerprint: str, stored_hash: str) -> bool:
    """Verifiera PIN mot lagrad hash."""
    if not stored_hash:
        return True
    return _hash_pin(pin, fingerprint) == stored_hash

def _get_engine_for_path(path: Path) -> Optional[str]:
    """Bestäm pandas Excel-engine utifrån filändelse."""
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return "openpyxl"
    if ext == ".xls":
        return "xlrd"
    return None

def _build_norm_mapping(mapping: Dict[str, str]) -> Dict[str, str]:
    """Bygg normaliserad kolumn → internt fält."""
    norm: Dict[str, str] = {}
    for excel_col, internal_field in mapping.items():
        norm[_normalize_column_name(excel_col)] = internal_field
    return norm

def _extract_header_values(df_raw: Any, row_idx: int) -> List[str]:
    """Extrahera rubrikvärden från en rad (NaN/None → '')."""
    headers: List[str] = []
    for val in df_raw.iloc[row_idx]:
        s = str(val).strip()
        if s.lower() in ("nan", "none", "nat"):
            s = ""
        headers.append(s)
    return headers

def _detect_header_row(df_raw: Any, sheet_name: str = "") -> Tuple[int, List[str]]:
    """
    Detektera rubrikrad (0-indexerad).
    KRAV 40 (spec v1.4): RAD 1 (index 0) är ALLTID kolumnrubrikerna.
      - Rad 1 läses DIREKT om den innehåller minst en användbar
        (icke-tom, icke-ren-numerisk) cell.
      - Är rad 1 tom/oläsbar → fallback-skanning rad 1-9 (loggas INFO).
      - Hittas ingen användbar rubrikrad → returneras (0, []) — anroparen
        skippar bladet med rapport (aldrig tyst).
    """
    max_scan = min(10, len(df_raw))

    def _row_has_strings(row_idx: int) -> bool:
        for val in df_raw.iloc[row_idx]:
            s = str(val).strip()
            if s.lower() in ("nan", "none", "nat", ""):
                continue
            if re.fullmatch(r"[\d\s,.\-]+", s):
                continue
            return True
        return False
    # Strategi 1 (KRAV 40): rad 1 direkt
    if max_scan >= 1 and _row_has_strings(0):
        return 0, _extract_header_values(df_raw, 0)
    _log.info(
        "Rad 1 i blad '%s' tom/oläsbar — skannar rad 1-9 (fallback)",
        sheet_name or "?",
    )
    # Strategi 2: skanning rad 1-9, välj rad med flest strängceller
    best_row = -1
    best_score = -1.0
    for row_idx in range(1, max_scan):
        string_count = 0
        numeric_count = 0
        empty_count = 0
        for val in df_raw.iloc[row_idx]:
            s = str(val).strip()
            if s.lower() in ("nan", "none", "nat", ""):
                empty_count += 1
                continue
            if re.fullmatch(r"[\d\s,.\-]+", s):
                numeric_count += 1
            else:
                string_count += 1
        total = string_count + numeric_count + empty_count
        if total == 0:
            continue
        # Favorisera rader med många strängar och få numeriska värden
        score = string_count - (0.5 * numeric_count) - (0.2 * empty_count)
        if score > best_score:
            best_score = score
            best_row = row_idx
    if best_row >= 0:
        return best_row, _extract_header_values(df_raw, best_row)
    _log.warning(
        "Ingen användbar rubrikrad i blad '%s' — bladet skippas",
        sheet_name or "?",
    )
    return 0, []

# ══════════════════════════════════════════════════════════════════════════════
# EXCEL MODEL IMPORTER

# ══════════════════════════════════════════════════════════════════════════════

class ExcelModelImporter:
    """
    Importerar modelldata från Excel till vehicle_registry.
    Stöder:
      - VINCODE som VIN-prefix (3-8 tecken, EJ 17-teckens VIN)
      - SPEC v7.0: VIN3 extraheras via tecken 2-4 (exakt 3 = as-is)
      - KRAV 40: rad 1 i varje blad = rubriker direkt
      - Konfigurerbar fältmappning med fingerprint-baserad återanvändning
      - Konfliktdetektering och upplösning (replace/skip/merge/ask)
      - Gruppering per årsmodell → {year}.json
      - Merge med befintlig data (upsert per vin_kod)
      - Header-detektion (rad 1 direkt, fallback rad 1-9)
      - Bladfiltrering (hoppa över 25Kw etc.)
      - Persistent lagring av fältmappning (json/mappings/, Sektion Z)
    Användning:
        importer = ExcelModelImporter(storage, mapping_dir)
        preview = importer.preview_file("modelldata.xlsx")
        result = importer.import_file("modelldata.xlsx", on_conflict="ask")
    """

    def __init__(
        self,
        vehicle_storage: Any,
        mapping_dir: Optional[Path] = None,
        column_mapping: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Args:
            vehicle_storage: VehicleDataStorage-instans
            mapping_dir:     Katalog för persistent mappning-JSON
                             (spec v1.4: json/mappings/)
            column_mapping:  Custom mappning (None = default)
        """
        self._storage = vehicle_storage
        self._mapping_dir = mapping_dir
        self._column_mapping: Dict[str, str] = dict(
            column_mapping or DEFAULT_COLUMN_MAPPING
        )
        self._vehicle_import_mapping_path: Optional[Path] = (
            self._get_vehicle_import_mapping_path()
        )
        if mapping_dir:
            self._load_saved_mapping()

    # ──────────────────────────────────────────────────────────────────
    # SÖKVÄGSHANTERING

    # ──────────────────────────────────────────────────────────────────

    def _get_active_mapping_path(self) -> Optional[Path]:
        """Hämta sökväg till aktiv mappnings-JSON (json/mappings/)."""
        if self._mapping_dir:
            return self._mapping_dir / ACTIVE_MAPPING_FILENAME
        return None

    def _get_legacy_active_mapping_path(self) -> Optional[Path]:
        """
        Fallback-sökväg (Sektion Z): data/vehicle_registry/column_mapping.json.
        mapping_dir förväntas vara <projektrot>/json/mappings,
        så projektrot blir mapping_dir.parent.parent.
        """
        if not self._mapping_dir:
            return None
        try:
            root = self._mapping_dir.parent.parent
            return root / "data" / "vehicle_registry" / ACTIVE_MAPPING_FILENAME
        except Exception:
            return None

    def _get_vehicle_import_mapping_path(self) -> Optional[Path]:
        """Hämta sökväg till fingerprint-mappningsfil (json/mappings/)."""
        if not self._mapping_dir:
            return None
        return self._mapping_dir / VEHICLE_IMPORT_MAPPING_FILENAME

    def _get_legacy_vehicle_import_mapping_path(self) -> Optional[Path]:
        """
        Fallback-sökväg (Sektion Z):
        data/mappings/vehicle_import_mapping.json.
        """
        if not self._mapping_dir:
            return None
        try:
            root = self._mapping_dir.parent.parent
            return root / "data" / "mappings" / VEHICLE_IMPORT_MAPPING_FILENAME
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────────
    # MAPPING HANTERING

    # ──────────────────────────────────────────────────────────────────

    def get_column_mapping(self) -> Dict[str, str]:
        """Hämta aktuell kolumnmappning."""
        return dict(self._column_mapping)

    def set_column_mapping(
        self,
        mapping: Dict[str, str],
        fingerprint: Optional[str] = None,
        pin: Optional[str] = None,
        protected: bool = False,
    ) -> None:
        """
        Sätt kolumnmappning och spara persistent.
        Args:
            mapping:     Kolumnmappning (normaliserad header → internt fält).
            fingerprint: Om angiven sparas mappningen även under detta
                         fingerprint i vehicle_import_mapping.json.
            pin:         PIN för att få ändra en skyddad mappning.
            protected:   Om True skyddas mappningen med angiven PIN.
        """
        self._column_mapping = dict(mapping)
        self._save_mapping()
        if fingerprint:
            self._save_fingerprint_mapping(
                fingerprint=fingerprint,
                headers=list(mapping.keys()),
                mapping=mapping,
                pin=pin,
                protected=protected,
            )
        _log.info(
            "Kolumnmappning uppdaterad: %d fält",
            len(mapping),
        )

    def suggest_mapping(
        self,
        headers: List[str],
        target_fields: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Föreslå mappning för en lista med Excel-rubriker.
        Returnerar dict {normaliserad_header: internt_fält}.
        """
        suggestions: Dict[str, str] = {}
        targets = set(target_fields or list(DEFAULT_COLUMN_MAPPING.values()))
        for header in headers:
            norm = _normalize_column_name(header)
            if not norm:
                continue
            if norm in DEFAULT_COLUMN_MAPPING:
                suggestions[norm] = DEFAULT_COLUMN_MAPPING[norm]
            elif norm in targets:
                suggestions[norm] = norm
        return suggestions

    def build_fingerprint(self, headers: List[str]) -> str:
        """
        Bygg unik fingerprint för en rubrikuppsättning.
        Spec v1.4 / P14: md5 över normaliserade rubriker i ORDNING
        (alla blad, i följd; dubbletter tas bort, första förekomst behålls).
        """
        normalized: List[str] = []
        for header in headers:
            norm = _normalize_column_name(header)
            if norm and norm not in normalized:
                normalized.append(norm)
        joined = "|".join(normalized)
        return hashlib.md5(joined.encode("utf-8")).hexdigest()

    def verify_mapping_pin(self, fingerprint: str, pin: str) -> bool:
        """Verifiera PIN för en fingerprint-baserad mappning."""
        entry = self._load_fingerprint_entry(fingerprint)
        if not entry:
            return False
        if not entry.get("protected"):
            return True
        stored = entry.get("pin_hash", "")
        return _verify_pin(pin, fingerprint, stored)

    def _load_saved_mapping(self) -> None:
        """Ladda sparad aktiv mappning om den finns (json/ + fallback)."""
        path = self._get_active_mapping_path()
        data = None
        if path and path.exists():
            data = _read_json_safe(path)
        else:
            legacy = self._get_legacy_active_mapping_path()
            if legacy and legacy.exists():
                _log.info(
                    "Hittade gammal mappning — läser fallback: %s",
                    legacy.name,
                )
                data = _read_json_safe(legacy)
        if data and isinstance(data, dict) and "mapping" in data:
            self._column_mapping = data["mapping"]
            _log.info(
                "Laddade %d kolumnmappningar från %s",
                len(self._column_mapping), path.name if path else "?",
            )

    def _save_mapping(self) -> None:
        """Spara aktiv mappning persistent (json/mappings/column_mapping.json)."""
        path = self._get_active_mapping_path()
        if not path:
            return
        try:
            _atomic_write_json(path, {
                "version": VERSION,
                "updated_at": datetime.now().isoformat(),
                "copyright": get_copyright_string(),
                "mapping": self._column_mapping,
            })
        except Exception as exc:
            _log.error("Kunde inte spara aktiv mappning: %s", exc)

    def _load_fingerprint_entry(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        """Ladda en enskild fingerprint-post från global mappningsfil."""
        path = self._get_vehicle_import_mapping_path()
        data = None
        if path and path.exists():
            data = _read_json_safe(path, {})
        else:
            legacy = self._get_legacy_vehicle_import_mapping_path()
            if legacy and legacy.exists():
                _log.info(
                    "Läser legacy fingerprint-mappningar: %s",
                    legacy.name,
                )
                data = _read_json_safe(legacy, {})
        if not isinstance(data, dict):
            return None
        mappings = data.get("mappings", {})
        entry = mappings.get(fingerprint)
        return entry if isinstance(entry, dict) else None

    def load_mapping_for_fingerprint(self, fingerprint: str) -> Optional[Dict[str, str]]:
        """Publik: ladda mappning för ett fingerprint."""
        entry = self._load_fingerprint_entry(fingerprint)
        if not entry:
            return None
        mapping = entry.get("mapping")
        if isinstance(mapping, dict):
            return dict(mapping)
        return None

    def _save_fingerprint_mapping(
        self,
        fingerprint: str,
        headers: List[str],
        mapping: Dict[str, str],
        pin: Optional[str] = None,
        protected: bool = False,
    ) -> None:
        """
        Spara mappning under fingerprint i
        json/mappings/vehicle_import_mapping.json.
        """
        path = self._get_vehicle_import_mapping_path()
        if not path:
            return
        data = _read_json_safe(path, {})
        if not isinstance(data, dict):
            data = {}
        mappings = data.setdefault("mappings", {})
        existing = mappings.get(fingerprint, {})
        existing_protected = existing.get("protected", False)
        existing_hash = existing.get("pin_hash", "")
        if existing_protected and existing_hash:
            if not _verify_pin(pin or "", fingerprint, existing_hash):
                raise PermissionError(
                    "Lösenord krävs för att ändra den sparade mappningen."
                )
        # Bevara befintligt lösenord om nytt PIN inte anges
        if pin:
            pin_hash = _hash_pin(pin, fingerprint)
        elif existing_hash:
            pin_hash = existing_hash
        else:
            pin_hash = ""
        final_protected = bool(protected or existing_protected)
        if final_protected and not pin_hash:
            # Om mappningen ska vara skyddad men vi inte har någon hash,
            # kan vi inte spara som skyddad.
            final_protected = False
        mappings[fingerprint] = {
            "headers": list(headers),
            "normalized_headers": sorted({
                _normalize_column_name(h) for h in headers
            }),
            "mapping": dict(mapping),
            "updated_at": datetime.now().isoformat(),
            "created_at": existing.get("created_at") or datetime.now().isoformat(),
            "protected": final_protected,
            "pin_hash": pin_hash,
            "source": "vehicle_import",
            "version": VERSION,
        }
        data["version"] = VERSION
        data["updated_at"] = datetime.now().isoformat()
        try:
            _atomic_write_json(path, data)
        except Exception as exc:
            _log.error("Kunde inte spara fingerprint-mappning: %s", exc)
            raise

    # ──────────────────────────────────────────────────────────────────
    # HEADER-DETEKTION / PREVIEW

    # ──────────────────────────────────────────────────────────────────

    def detect_headers(
        self,
        filepath: str,
        sheet_name: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Detektera rubriker för ett eller alla blad i en Excel-fil.
        KRAV 40: rad 1 (index 0) läses direkt som rubriker; fallback
        rad 1-9 endast om rad 1 är tom/oläsbar.
        Returnerar dict:
            {
              "Blad1": {
                  "headers": ["COL1", "COL2", ...],
                  "header_row": 0,
                  "skipped": False,
              },
              ...
            }
        """
        result: Dict[str, Dict[str, Any]] = {}
        if not HAS_PANDAS:
            return result
        path = Path(filepath)
        engine = _get_engine_for_path(path)
        if not engine:
            return result
        try:
            xls = pd.ExcelFile(filepath, engine=engine)
        except Exception as exc:
            _log.warning("Kunde inte öppna fil för header-detektion: %s", exc)
            return result
        sheets = [sheet_name] if sheet_name else xls.sheet_names
        for name in sheets:
            if name not in xls.sheet_names:
                continue
            if _should_skip_sheet(name):
                result[name] = {"headers": [], "header_row": 0, "skipped": True}
                continue
            try:
                df_raw = pd.read_excel(
                    xls, sheet_name=name,
                    header=None, nrows=15, dtype=str,
                )
                if df_raw.empty:
                    result[name] = {"headers": [], "header_row": 0, "skipped": True}
                    continue
                header_row, headers = _detect_header_row(df_raw, sheet_name=name)
                if not headers:
                    result[name] = {"headers": [], "header_row": 0, "skipped": True}
                    continue
                result[name] = {
                    "headers": headers,
                    "header_row": header_row,
                    "skipped": False,
                }
            except Exception as exc:
                _log.warning("Kunde inte detektera headers i '%s': %s", name, exc)
                result[name] = {"headers": [], "header_row": 0, "skipped": True}
        return result

    def preview_file(
        self,
        filepath: str,
        column_mapping: Optional[Dict[str, str]] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Torrkörning: läs fil, applicera mappning, returnera förhandsgranskning
        utan att spara något.
        Returnerar dict med fingerprint, headers, preview-rader, konflikter,
        förslag på mappning och eventuella fel.
        """
        return self.import_file(
            filepath=filepath,
            column_mapping=column_mapping,
            on_conflict=ConflictAction.ASK,
            dry_run=True,
            progress_callback=progress_callback,
        )

    # ──────────────────────────────────────────────────────────────────
    # IMPORT

    # ──────────────────────────────────────────────────────────────────

    def import_file(
        self,
        filepath: str,
        column_mapping: Optional[Dict[str, str]] = None,
        on_conflict: str = ConflictAction.REPLACE,
        conflict_resolutions: Optional[Dict[str, str]] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        dry_run: bool = False,
        save_mapping: bool = True,
        pin: Optional[str] = None,
        protected: bool = False,
    ) -> Dict[str, Any]:
        """
        Importera modelldata från Excel-fil.
        Args:
            filepath:             Sökväg till .xlsx/.xls/.xlsm
            column_mapping:       Custom mappning. Om None används sparad
                                  mappning (fingerprint först, sedan aktiv).
            on_conflict:          "replace" | "skip" | "merge" | "ask"
            conflict_resolutions: Dict {vin_kod: action} för specifika val.
            progress_callback:    Callback(msg) för progress
            dry_run:              Om True sparas inget, endast preview.
            save_mapping:         Spara column_mapping under fingerprint.
            pin:                  PIN om mappningen ska/är skyddad.
            protected:            Skydda mappningen med PIN.
        Returns:
            Dict med success, imported, updated, skipped, errors, years,
            sheets_processed, sheets_skipped, conflicts, needs_resolution,
            fingerprint, mapping_used.
        """
        result: Dict[str, Any] = {
            "success": False,
            "imported": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "years": [],
            "sheets_processed": [],
            "sheets_skipped": [],
            "conflicts": [],
            "needs_resolution": False,
            "fingerprint": None,
            "mapping_used": {},
            "row_errors": [],
        }
        conflict_resolutions = conflict_resolutions or {}
        if not HAS_PANDAS:
            result["errors"].append(
                "pandas krävs — pip install pandas openpyxl"
            )
            return result
        path = Path(filepath)
        if not path.exists():
            result["errors"].append(f"Filen finns inte: {filepath}")
            return result
        log_cb = progress_callback or (lambda msg: None)
        engine = _get_engine_for_path(path)
        if not engine:
            result["errors"].append(f"Okänt filformat: {path.suffix}")
            return result
        _log.info("Importerar modelldata från: %s", path.name)
        log_cb(f"Öppnar {path.name}...")
        try:
            xls = pd.ExcelFile(filepath, engine=engine)
        except Exception as exc:
            result["errors"].append(f"Kunde inte öppna fil: {exc}")
            return result
        # Detektera headers per blad (KRAV 40: rad 1 direkt)
        header_info = self.detect_headers(filepath)
        all_headers: List[str] = []
        for name, info in header_info.items():
            if not info.get("skipped") and info.get("headers"):
                all_headers.extend(info["headers"])
        fingerprint = self.build_fingerprint(all_headers) if all_headers else ""
        result["fingerprint"] = fingerprint
        # Välj mappning
        current_mapping: Dict[str, str]
        if column_mapping is not None:
            current_mapping = dict(column_mapping)
            if save_mapping and fingerprint:
                try:
                    self._save_fingerprint_mapping(
                        fingerprint=fingerprint,
                        headers=all_headers,
                        mapping=current_mapping,
                        pin=pin,
                        protected=protected,
                    )
                except PermissionError as exc:
                    result["errors"].append(str(exc))
                    return result
        else:
            fp_mapping = self.load_mapping_for_fingerprint(fingerprint) if fingerprint else None
            if fp_mapping:
                current_mapping = fp_mapping
                _log.info("Återanvände fingerprint-mappning %s", fingerprint[:12])
            else:
                current_mapping = dict(self._column_mapping)
        result["mapping_used"] = dict(current_mapping)
        norm_mapping = _build_norm_mapping(current_mapping)
        # Bearbeta alla blad
        vehicles_by_year: Dict[int, List[Dict[str, Any]]] = {}
        years_seen: Set[int] = set()
        skipped_invalid_vin = 0
        row_errors: List[Dict[str, Any]] = []
        for sheet_name in xls.sheet_names:
            if _should_skip_sheet(sheet_name):
                result["sheets_skipped"].append(sheet_name)
                log_cb(f"⏭️ Hoppar blad: {sheet_name}")
                continue
            log_cb(f"Läser blad: {sheet_name}...")
            try:
                df = self._read_sheet(xls, sheet_name)
                if df is None:
                    result["sheets_skipped"].append(
                        f"{sheet_name} (ingen användbar rubrikrad)"
                    )
                    continue
                if df.empty:
                    result["sheets_skipped"].append(f"{sheet_name} (tomt)")
                    continue
                sheet_vehicles, sheet_skipped, sheet_errors = self._process_sheet(
                    df=df,
                    sheet_name=sheet_name,
                    norm_mapping=norm_mapping,
                    log_cb=log_cb,
                )
                skipped_invalid_vin += sheet_skipped
                row_errors.extend(sheet_errors)
                for year, vehicle in sheet_vehicles:
                    vehicles_by_year.setdefault(year, []).append(vehicle)
                    years_seen.add(year)
                result["sheets_processed"].append(
                    f"{sheet_name} ({len(sheet_vehicles)} rader)"
                )
                log_cb(f"✅ {sheet_name}: {len(sheet_vehicles)} fordon")
            except Exception as exc:
                _log.warning("Fel i blad '%s': %s", sheet_name, exc)
                result["errors"].append(f"Blad '{sheet_name}': {exc}")
        result["row_errors"] = row_errors
        # Konflikthantering
        conflicts: List[ConflictInfo] = []
        if vehicles_by_year and self._storage:
            conflicts = self._detect_conflicts(vehicles_by_year)
        if on_conflict == ConflictAction.ASK and conflicts:
            result["conflicts"] = [c.to_dict() for c in conflicts]
            result["needs_resolution"] = True
            result["years"] = sorted(years_seen)
            result["skipped"] += skipped_invalid_vin
            _log.info("Import kräver konfliktlösning: %d konflikter", len(conflicts))
            return result
        # Spara per år (om inte torrkörning)
        if vehicles_by_year and self._storage and not dry_run:
            for year in sorted(vehicles_by_year.keys()):
                vehicles = vehicles_by_year[year]
                log_cb(f"Sparar {len(vehicles)} fordon för {year}...")
                try:
                    actions = self._build_year_actions(
                        year, vehicles, on_conflict, conflict_resolutions
                    )
                    imp, upd, skip = self._merge_and_save(
                        year=year,
                        new_vehicles=vehicles,
                        actions=actions,
                    )
                    result["imported"] += imp
                    result["updated"] += upd
                    result["skipped"] += skip
                    _log.info(
                        "År %d: %d nya, %d uppdaterade, %d överhoppade",
                        year, imp, upd, skip,
                    )
                except Exception as exc:
                    _log.error("Kunde inte spara år %d: %s", year, exc)
                    result["errors"].append(f"År {year}: {exc}")
        elif dry_run:
            # Räkna torrt resultat
            for year in sorted(vehicles_by_year.keys()):
                vehicles = vehicles_by_year[year]
                actions = self._build_year_actions(
                    year, vehicles, on_conflict, conflict_resolutions
                )
                existing = self._storage.load_year(year) if self._storage else []
                existing_by_vin = {
                    str(v.get("vin_kod", "")).strip().upper(): v
                    for v in existing if v.get("vin_kod")
                }
                for v in vehicles:
                    vin = str(v.get("vin_kod", "")).strip().upper()
                    action = actions.get(vin, on_conflict)
                    if not vin:
                        result["skipped"] += 1
                        continue
                    if vin in existing_by_vin:
                        if action == ConflictAction.SKIP:
                            result["skipped"] += 1
                        else:
                            result["updated"] += 1
                    else:
                        result["imported"] += 1
        result["skipped"] += skipped_invalid_vin
        result["years"] = sorted(years_seen)
        result["success"] = (
            result["imported"] + result["updated"]
        ) > 0 and not result["needs_resolution"]
        if conflicts and on_conflict != ConflictAction.ASK:
            result["conflicts"] = [c.to_dict() for c in conflicts]
        _log.info(
            "Import klar: %d nya, %d uppdaterade, "
            "%d överhoppade, %d fel",
            result["imported"],
            result["updated"],
            result["skipped"],
            len(result["errors"]),
        )
        return result

    # ──────────────────────────────────────────────────────────────────
    # KONFLIKTHANTERING

    # ──────────────────────────────────────────────────────────────────

    def _detect_conflicts(
        self,
        vehicles_by_year: Dict[int, List[Dict[str, Any]]],
    ) -> List[ConflictInfo]:
        """Hitta VIN3 som redan finns i lagringen."""
        conflicts: List[ConflictInfo] = []
        if not self._storage:
            return conflicts
        for year, vehicles in vehicles_by_year.items():
            existing_by_vin: Dict[str, Dict[str, Any]] = {}
            for v in self._storage.load_year(year):
                vin = str(v.get("vin_kod", "")).strip().upper()
                if vin:
                    existing_by_vin[vin] = v
            seen: Set[str] = set()
            for v in vehicles:
                vin = str(v.get("vin_kod", "")).strip().upper()
                if not vin or vin in seen:
                    continue
                seen.add(vin)
                if vin in existing_by_vin:
                    conflicts.append(ConflictInfo(
                        vin_kod=vin,
                        year=year,
                        existing=dict(existing_by_vin[vin]),
                        incoming={k: v for k, v in v.items() if not str(k).startswith("_")},
                    ))
        return conflicts

    def _build_year_actions(
        self,
        year: int,
        new_vehicles: List[Dict[str, Any]],
        on_conflict: str,
        conflict_resolutions: Dict[str, str],
    ) -> Dict[str, str]:
        """Bygg dict {vin_kod: action} för ett år."""
        actions: Dict[str, str] = {}
        for v in new_vehicles:
            vin = str(v.get("vin_kod", "")).strip().upper()
            if not vin:
                continue
            actions[vin] = conflict_resolutions.get(vin, on_conflict)
        return actions

    # ──────────────────────────────────────────────────────────────────
    # EXCEL-LÄSNING

    # ──────────────────────────────────────────────────────────────────

    def _read_sheet(self, xls: Any, sheet_name: str) -> Optional[Any]:
        """
        Läs Excel-blad. KRASCHSÄKER.
        KRAV 40 (spec v1.4): RAD 1 (header=0) läses DIREKT som rubriker.
          - Rad 1 användbar (≥3 kolumner, <50 % unnamed) → returneras.
          - Rad 1 tom/oläsbar → fallback-skanning rad 1-9 (loggas INFO).
          - Ingen användbar rubrikrad → None — anroparen skippar bladet
            med rapport (aldrig tyst).
        """
        def _usable(df: Any) -> bool:
            if df is None or df.empty or len(df.columns) < 3:
                return False
            unnamed = sum(
                1 for c in df.columns
                if "unnamed" in str(c).lower()
            )
            return unnamed < len(df.columns) * 0.5
        # Strategi 1 (KRAV 40): header=0 — rad 1 direkt
        try:
            df = pd.read_excel(
                xls, sheet_name=sheet_name, dtype=str, header=0,
            )
            if _usable(df):
                return self._clean_df(df)
        except Exception:
            pass
        _log.info(
            "Rad 1 i blad '%s' tom/oläsbar — skannar rad 1-9 (fallback)",
            sheet_name,
        )
        # Strategi 2: skanning rad 1-9
        for header_row in range(1, 10):
            try:
                df = pd.read_excel(
                    xls, sheet_name=sheet_name,
                    dtype=str, header=header_row,
                )
                if _usable(df):
                    _log.debug(
                        "Header hittad på rad %d i '%s'",
                        header_row, sheet_name,
                    )
                    return self._clean_df(df)
            except Exception:
                continue
        # Ingen användbar rubrikrad — anroparen skippar bladet med rapport
        _log.warning(
            "Ingen användbar rubrikrad i blad '%s' — bladet skippas",
            sheet_name,
        )
        return None

    def _clean_df(self, df: Any) -> Any:
        """Rensa DataFrame från nan/None."""
        for col in df.select_dtypes(include=["object"]).columns:
            try:
                df[col] = (
                    df[col]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .replace({"nan": "", "None": "", "NaT": ""})
                )
            except Exception:
                pass
        df = df.dropna(how="all")
        return df

    # ──────────────────────────────────────────────────────────────────
    # BEARBETNING

    # ──────────────────────────────────────────────────────────────────

    def _process_sheet(
        self,
        df: Any,
        sheet_name: str,
        norm_mapping: Dict[str, str],
        log_cb: Callable[[str], None],
    ) -> Tuple[List[Tuple[int, Dict[str, Any]]], int, List[Dict[str, Any]]]:
        """
        Bearbeta ett blad → (lista av (year, vehicle_dict), skippade, radfel).
        SPEC v7.0: VINCODE-värden konverteras till VIN3 via tecken 2-4.
        Rader med ogiltigt VINCODE räknas som skippade.
        Årsmodell extraheras från:
          1. MODEL/MODELYEAR-kolumn i raden
          2. Bladnamnet (om 4-siffrigt)
          3. Aktuellt år (fallback)
        """
        results: List[Tuple[int, Dict[str, Any]]] = []
        skipped = 0
        row_errors: List[Dict[str, Any]] = []
        # Mappa Excel-kolumner → interna fält
        col_to_internal: Dict[str, str] = {}
        for df_col in df.columns:
            norm = _normalize_column_name(df_col)
            if norm in norm_mapping:
                col_to_internal[str(df_col)] = norm_mapping[norm]
        if not col_to_internal:
            log_cb(f"⚠️ Inga matchande kolumner i '{sheet_name}'")
            return results, skipped, row_errors
        matched = [
            f"{dc} → {internal}"
            for dc, internal in col_to_internal.items()
        ]
        _log.info(
            "Blad '%s': matchade %d kolumner: %s",
            sheet_name, len(matched),
            ", ".join(matched[:10]),
        )
        # Försök extrahera år från bladnamnet
        sheet_year: Optional[int] = None
        try:
            cleaned_name = sheet_name.strip()
            if re.fullmatch(r"20\d{2}", cleaned_name):
                sheet_year = int(cleaned_name)
        except Exception:
            pass
        pandas_row_offset = 2  # header=0 -> data börjar på Excel-rad 2
        for row_index, row in df.iterrows():
            vehicle: Dict[str, Any] = {}
            year: Optional[int] = None
            raw_vincode = ""
            source_row = int(row_index) + pandas_row_offset
            for df_col, internal_field in col_to_internal.items():
                value = str(row.get(df_col, "")).strip()
                if value.lower() in ("nan", "none", "nat", ""):
                    continue
                if internal_field == "_year":
                    try:
                        year = int(float(value))
                        if year < 100:
                            year = 2000 + year
                    except (ValueError, TypeError):
                        pass
                elif internal_field == "vin_kod":
                    raw_vincode = value
                else:
                    vehicle[internal_field] = value
            # Bestäm år
            if year is None:
                year = sheet_year or datetime.now().year
            # SPEC v7.0: extrahera VIN3 via tecken 2-4
            if not raw_vincode:
                skipped += 1
                row_errors.append({
                    "sheet": sheet_name,
                    "row": source_row,
                    "reason": "Saknar VINCODE",
                })
                continue
            vin_kod = _extract_vin3_from_value(raw_vincode)
            if not vin_kod:
                skipped += 1
                _log.debug(
                    "Ogiltigt VINCODE-värde '%s' i blad '%s' rad %d — skippas",
                    raw_vincode, sheet_name, source_row,
                )
                row_errors.append({
                    "sheet": sheet_name,
                    "row": source_row,
                    "reason": f"Ogiltigt VINCODE: {raw_vincode}",
                })
                continue
            vehicle["vin_kod"] = vin_kod
            vehicle["_source_sheet"] = sheet_name
            vehicle["_source_row"] = source_row
            results.append((year, vehicle))
        return results, skipped, row_errors

    # ──────────────────────────────────────────────────────────────────
    # MERGE & SAVE

    # ──────────────────────────────────────────────────────────────────

    def _merge_and_save(
        self,
        year: int,
        new_vehicles: List[Dict[str, Any]],
        actions: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, int, int]:
        """
        Merge nya fordon med befintliga och spara.
        Args:
            actions: Dict {vin_kod: "replace"|"skip"|"merge"}.
                     Om None behandlas allt som replace.
        Returns:
            (imported, updated, skipped)
        """
        actions = actions or {}
        existing = self._storage.load_year(year)
        existing_by_vin: Dict[str, Dict[str, Any]] = {
            str(v.get("vin_kod", "")).strip().upper(): v
            for v in existing
            if v.get("vin_kod")
        }
        imported = 0
        updated = 0
        skipped = 0
        for vehicle in new_vehicles:
            vin_kod = str(vehicle.get("vin_kod", "")).strip().upper()
            if not vin_kod:
                skipped += 1
                continue
            action = actions.get(vin_kod, ConflictAction.REPLACE)
            if vin_kod in existing_by_vin:
                if action == ConflictAction.SKIP:
                    skipped += 1
                    continue
                if action == ConflictAction.MERGE:
                    for key, val in vehicle.items():
                        if str(key).startswith("_"):
                            continue
                        if val not in (None, ""):
                            existing_by_vin[vin_kod][key] = val
                else:
                    # replace: behåll befintligt skal, skriv över med nytt
                    existing_by_vin[vin_kod].update(vehicle)
                updated += 1
            else:
                existing_by_vin[vin_kod] = vehicle
                imported += 1
        merged_list = sorted(
            existing_by_vin.values(),
            key=lambda v: str(v.get("vin_kod", "")),
        )
        self._storage.save_year(year, merged_list, VERSION)
        return imported, updated, skipped

# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTION

# ══════════════════════════════════════════════════════════════════════════════

def import_excel_to_registry(
    filepath: str,
    vehicle_storage: Any,
    column_mapping: Optional[Dict[str, str]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Convenience-funktion för att importera utan att skapa
    ExcelModelImporter manuellt.
    Args:
        filepath:          Sökväg till Excel-fil
        vehicle_storage:   VehicleDataStorage-instans
        column_mapping:    Custom mappning (None = default/sparad)
        progress_callback: Progress callback
    Returns:
        Importresultat (se ExcelModelImporter.import_file)
    """
    importer = ExcelModelImporter(
        vehicle_storage=vehicle_storage,
        column_mapping=column_mapping,
    )
    return importer.import_file(
        filepath,
        progress_callback=progress_callback,
    )

# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS

# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "ExcelModelImporter",
    "import_excel_to_registry",
    "DEFAULT_COLUMN_MAPPING",
    "SKIP_SHEETS",
    "VERSION",
    "AUTHOR",
    "VIN3_SLICE_START",
    "VIN3_SLICE_END",
    "ConflictAction",
]
