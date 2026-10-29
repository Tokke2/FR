# -*- coding: utf-8 -*-
# Fil: plugins/identity_post/plugin.py

"""
Identity Post Plugin v3.2.1

Genererar identitetsposter (posttyp 28) för Transportstyrelsen.
Integrerar med ts_spec_import för schemadefinitioner.

ANSVAR:
  - Generera PT28 med korrekt format (2500 tecken)
  - Använda ts_spec_import schema om tillgängligt
  - Fallback till hårdkodad generering om schema saknas
  - Hantera filidentitet-sekvens (TS0001 → TS0002)
  - Model Year-validering mellan Dispatch och SAP
  - Atomisk filskrivning
  - Latin-1 (ISO 8859-1) kompatibilitet
  - Robust plugin-access via helpers

IMPORTER (EXTERNA):
  json, logging, os, re, tempfile, dataclasses, datetime, pathlib, typing
  core.plugin_base (PluginBase)
  pandas (valfri, kontrolleras vid runtime)

PUBLIKT API:
  generate_post(...)            -> Dict[str, Any]
  validate_model_years(...)     -> Dict[str, Any]
  get_config()                  -> Dict[str, Any]
  update_config(updates)        -> Dict[str, Any]
  get_next_filidentitet()       -> str
  get_current_filidentitet()    -> str
  get_orgnummer()               -> str
  invalidate_schema_cache()     -> None

EVENTS SOM EMITTAS:
  identity_post:activated, identity_post:generated,
  identity_post:config_updated

LYSSNAR PÅ:
  identity_post:generate, identity_post:validate,
  ts_spec:version_changed, ts_spec:imported

SAMARBETAR MED:
  ts_spec_import, core_config, sap_import, core_logger

FÖRÄNDRINGAR v3.2.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV Z, sökväg): konfigurationen skrivs nu till
    json/identitet_config.json (primär) i stället för
    ".js data/identitet_config.json" (master Z-sektionen:
    "persistens-sökvägar uppdaterade till json/ med fallback till
    gamla"). Legacy-fil i ".js data/" läses fortfarande och migreras
    till json/ vid nästa spara (dataförlust-skydd; legacy-filen
    raderas ALDRIG automatiskt).
  - FIX (base_dir): getattr(app, "base_path", ".") → fallback-kedja
    base_dir → base_path → cwd (konsistent med övriga plugins).
  - FIX (livscykel, korrekthet): activate() anropar nu
    super().activate() (is_active=True — FAIL-SAFE/plugin_loader
    såg pluginen som inaktiv); shutdown() anropar super().deactivate()
    i slutet (state → INACTIVE + cleanup) + _shutdown_done-flagga
    (idempotent). Originalet åsidosatte båda utan super()-anrop;
    super().shutdown() var EJ möjlig (PluginBase.shutdown() →
    self.deactivate() → self.shutdown() = ömsesidig rekursion —
    fångad av runtime-test).
  - FIX (konsistens, mallen): _get_copyright_string() → publik
    get_copyright_string() (+ privat alias behållet för
    bakåtkompatibilitet); lagd i __all__.
  - FIX (dataförlust): IdentityConfig.to_dict()/from_dict()
    inkluderar nu dispatch_columns/sap_columns — anpassade
    kolumnmappningar överlever config-roundtrip (originalet tappade
    dem vid spara/ladda; from_dict fallback till defaults).
  - FIX (korrekthet): DataNormalizer.sanitize_vin() validerar nu
    enligt samma regel som sap_import/core/data_normalizer.py:
    exakt 17 tecken A-Z0-9 och inga I/O/Q (VIN_PATTERN
    ^[A-HJ-NPR-Z0-9]{17}$). Originalet tog bort I/O/Q före
    längdkontrollen — en 17-teckens VIN med I/O/Q blev 16 tecken och
    därmed "" (av misstag samma resultat, men otydligt); nu avvisas
    ogiltiga VIN direkt.
  - FIX (dead code): PT28_HEADER borttagen (oanvänd — LOPNUMMER-
    fältet fylls av lopnummer).
  - FIX (stabilitet): _read_dispatch-fallbacken provar nu header=4
    (samma rubrikrad) innan header=0 — en fil med för få kolumner
    för usecols="A…R" gav ParserError → header=0 → tomma
    kolumnnamn → tyst 0-rader (fångat av runtime-test med riktiga
    xlsx-filer).
  - FIX (radbrytningsartefakt): _log.info("Configuration loaded")
    normaliserad till en rad.
  - TILLÄGG (metadata): OPTIONAL_DEPENDENCIES = ["pandas"] på
    Plugin-klassen (PluginBase-kontraktet — plugin_loader får veta
    att pandas är valfri).
  - OBS: FIELD_POSITIONS oförändrade (internt konsistenta,
    80-teckens prefix 1–80); fältpositionerna är TS-spec-beroende
    och ändras inte utan spec.
FÖRÄNDRINGAR v3.2.0:
  - AUTHOR → "Rickard Längkvist" (BUGG #5)
  - logger → module-level _log (spec-konvention)
  - f-string logging → lazy %s formatting
  - PluginBase kontrakt: init/shutdown/config_schema
  - Bakåtkompatibla delegater: initialize/activate/deactivate
  - os.replace() istället för Path.replace() (atomisk skrivning)
  - self.is_active borttaget (PluginBase hanterar)
  - Dynamisk copyright
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import (
    Any, Callable, Dict, Final, List, Optional, Tuple, TYPE_CHECKING,
)

from core.plugin_base import PluginBase

if TYPE_CHECKING:
    from core.event_bus import EventBus


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "3.2.1"
AUTHOR: Final[str] = "Rickard Längkvist"
PLUGIN_NAME: Final[str] = "Identity Post"

# Standard TS-postlängd
RECORD_LENGTH: Final[int] = 2500

# Teckenkodning enligt TS-spec
TS_ENCODING: Final[str] = "iso-8859-1"

# PT28-specifika konstanter (fallback om ts_spec_import saknas)
PT28_VERSION: Final[str] = "00"
PT28_POSTTYP: Final[str] = "28"
ORGNUMMER_LEN: Final[int] = 10
RES1_LEN: Final[int] = 36
FILIDENTITET_LEN: Final[int] = 6
DATE_LEN: Final[int] = 6
RES2_LEN: Final[int] = 14

# Fältpositioner (1-baserade enligt TS-spec)
FIELD_POSITIONS: Final[Dict[str, Tuple[int, int]]] = {
    "LOPNUMMER": (1, 4),
    "VERSION": (5, 2),
    "ORGNUMMER": (7, 10),
    "RESERV1": (17, 36),
    "FILIDENTITET": (53, 6),
    "DATUM": (59, 6),
    "RESERV2": (65, 14),
    "POSTTYP": (79, 2),
}

# Ogiltiga VIN-tecken (konsistent med sap_import VIN_INVALID_CHARS).
VIN_INVALID_CHARS: Final[str] = "IOQ"

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# Bakåtkompatibilitet: privat alias.
_get_copyright_string = get_copyright_string


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def _setup_logger() -> logging.Logger:
    """Konfigurera och returnera logger. KRASCHSÄKER."""
    try:
        return logging.getLogger("identity_post")
    except Exception:
        return logging.getLogger(__name__)


_log: logging.Logger = _setup_logger()


# ══════════════════════════════════════════════════════════════════════════════
# ROBUST HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """Robust plugin-hämtning. KRASCHSÄKER."""
    if app is None:
        return None
    normalized = name.lower().replace(" ", "_").replace("-", "_")
    for try_name in (name, normalized):
        try:
            gp = getattr(app, "get_plugin", None)
            if callable(gp):
                result = gp(try_name)
                if result is not None:
                    return result
        except Exception:
            pass
        try:
            loader = getattr(app, "plugin_loader", None)
            if loader and hasattr(loader, "get_plugin"):
                result = loader.get_plugin(try_name)
                if result is not None:
                    return result
        except Exception:
            pass
        try:
            manager = getattr(app, "plugin_manager", None)
            if manager and hasattr(manager, "get_plugin"):
                result = manager.get_plugin(try_name)
                if result is not None:
                    return result
        except Exception:
            pass
    try:
        attr_name = name.replace("-", "_").lower()
        if hasattr(app, attr_name):
            return getattr(app, attr_name)
    except Exception:
        pass
    return None

def get_event_bus(app: Any) -> Optional[Any]:
    """Hämta event bus från app. KRASCHSÄKER."""
    if app is None:
        return None
    for attr in ("event_bus", "events"):
        try:
            bus = getattr(app, attr, None)
            if bus is not None:
                return bus
        except Exception:
            pass
    events_plugin = get_plugin_safe(app, "core_events")
    if events_plugin is not None:
        if hasattr(events_plugin, "bus"):
            return events_plugin.bus
        if hasattr(events_plugin, "emit"):
            return events_plugin
    return None

def emit_event_safe(
    app: Any, event_name: str, data: Optional[Dict[str, Any]] = None
) -> bool:
    """Emit event säkert. KRASCHSÄKER."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        for method in ("emit", "publish"):
            func = getattr(bus, method, None)
            if func is not None:
                func(event_name, data or {})
                return True
    except Exception as exc:
        _log.debug("Event emit misslyckades '%s': %s", event_name, exc)
    return False

def subscribe_event_safe(
    app: Any, event_name: str, handler: Callable
) -> bool:
    """Prenumerera på event säkert. KRASCHSÄKER."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        for method in ("on", "subscribe"):
            func = getattr(bus, method, None)
            if func is not None:
                func(event_name, handler)
                return True
    except Exception as exc:
        _log.debug("Prenumeration misslyckades '%s': %s", event_name, exc)
    return False

def unsubscribe_event_safe(
    app: Any, event_name: str, handler: Callable
) -> bool:
    """Avprenumerera event säkert. KRASCHSÄKER."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        for method in ("off", "unsubscribe"):
            func = getattr(bus, method, None)
            if func is not None:
                func(event_name, handler)
                return True
    except Exception as exc:
        _log.debug(
            "Avprenumeration misslyckades '%s': %s", event_name, exc
        )
    return False


# ══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class IdentityConfig:
    """Konfiguration för identitetsposter."""

    orgnummer: str = ""
    filidentitet: str = "TS0001"
    version: str = "1.0"
    last_updated: Optional[str] = None
    created_at: Optional[str] = None

    # Kolumnmappningar för Dispatch-filer
    dispatch_columns: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "VIN": [
                "vin", "vinnumber", "chassisnumber", "vehicle id",
            ],
            "Model Year": [
                "modelyear", "year", "arsmodell", "årsmodell", "my",
            ],
            "ETG Number": [
                "etgnumber", "etg", "approval", "wvta",
            ],
            "Dealer Code": [
                "sold to dealer", "dealer code", "kundnummer",
            ],
            "Color": ["color", "colour", "färg"],
            "Invoice Date": ["invoice date", "fakturadatum"],
            "Production Date": [
                "actual production date", "produktionsdatum",
            ],
        }
    )

    # Kolumnmappningar för SAP-filer
    sap_columns: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "VINCODE": ["vincode", "vin", "chassisnumber"],
            "MODELYEAR": ["modelyear", "my", "year", "årsmodell"],
            "APPROVAL": ["approval", "etg", "wvta"],
            "COLORCODE": ["colorcode", "fargkod", "färgkod"],
        }
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> IdentityConfig:
        """Skapa från dictionary. KRASCHSÄKER."""
        return cls(
            orgnummer=data.get("orgnummer", ""),
            filidentitet=data.get("filidentitet", "TS0001"),
            version=data.get("version", "1.0"),
            last_updated=data.get("last_updated"),
            created_at=data.get("created_at"),
            dispatch_columns=data.get(
                "dispatch_columns", None
            ) or cls().dispatch_columns,
            sap_columns=data.get(
                "sap_columns", None
            ) or cls().sap_columns,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary (inkl. kolumnmappningar)."""
        return {
            "orgnummer": self.orgnummer,
            "filidentitet": self.filidentitet,
            "version": self.version,
            "last_updated": self.last_updated,
            "created_at": self.created_at,
            "dispatch_columns": self.dispatch_columns,
            "sap_columns": self.sap_columns,
        }


# ══════════════════════════════════════════════════════════════════════════════
# HELPER CLASSES
# ══════════════════════════════════════════════════════════════════════════════

class DataNormalizer:
    """Normaliserar data för matchning och validering."""

    @staticmethod
    def sanitize_vin(v: Any) -> str:
        """
        Sanera VIN-nummer.

        Regel (konsistent med sap_import VIN_PATTERN
        ^[A-HJ-NPR-Z0-9]{17}$): exakt 17 tecken A-Z0-9 och inga
        I/O/Q. Ogiltiga VIN → "".
        """
        if v is None:
            return ""
        s = str(v).strip().upper()
        s = re.sub(r"[^A-Z0-9]", "", s)
        if len(s) != 17:
            return ""
        if any(c in VIN_INVALID_CHARS for c in s):
            return ""
        return s

    @staticmethod
    def normalize_year(x: Any) -> str:
        """Normalisera årsmodell till 'YYYY'. KRASCHSÄKER."""
        if x is None:
            return ""
        s = str(x).strip()
        if not s or s.lower() in ("nan", "none", "null", ""):
            return ""
        if re.fullmatch(r"20\d{2}", s):
            return s
        my_match = re.search(r"[Mm][Yy]\s*(\d{2,4})", s)
        if my_match:
            year_str = my_match.group(1)
            if len(year_str) == 2:
                return f"20{year_str}"
            return year_str
        m2 = re.search(r"\b(\d{2})\b", s)
        if m2:
            yy = int(m2.group(1))
            if 0 <= yy <= 99:
                return f"20{yy:02d}"
        try:
            val = int(float(s.replace(",", ".")))
            if 2000 <= val <= 2099:
                return str(val)
            elif 0 <= val <= 99:
                return f"20{val:02d}"
        except Exception:
            pass
        m4 = re.search(r"\b(20\d{2})\b", s)
        if m4:
            return m4.group(1)
        return ""

    @staticmethod
    def normalize_key(s: str) -> str:
        """Normalisera nycklar för jämförelse."""
        return re.sub(r"[\W_]+", "", str(s).strip().lower())

    @staticmethod
    def validate_latin1(text: str) -> Tuple[bool, List[str]]:
        """Validera Latin-1 kompatibilitet."""
        invalid = []
        for char in text:
            try:
                char.encode(TS_ENCODING)
            except UnicodeEncodeError:
                invalid.append(char)
        return len(invalid) == 0, invalid

    @staticmethod
    def clean_orgnummer(org: str) -> str:
        """Rensa organisationsnummer till 10 siffror."""
        if not org:
            return ""
        cleaned = re.sub(r"[^\d]", "", str(org).strip())
        return cleaned.zfill(10) if cleaned else ""

class FileHandler:
    """Hanterar filoperationer med atomisk skrivning."""

    @staticmethod
    def atomic_write_json(path: Path, obj: Any) -> None:
        """Atomisk skrivning av JSON-fil. mkstemp→fsync→os.replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(
            obj, indent=2, ensure_ascii=False, sort_keys=True
        )
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def atomic_write_text(
        path: Path, text: str, encoding: str = "utf-8"
    ) -> None:
        """Atomisk skrivning av textfil. mkstemp→fsync→os.replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding=encoding) as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def find_latest_excel(directory: Path) -> Optional[Path]:
        """Hitta senaste Excel-fil i katalog. KRASCHSÄKER."""
        if not directory.exists():
            return None
        files = (
            list(directory.glob("*.xlsx"))
            + list(directory.glob("*.xls"))
        )
        if not files:
            return None
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0]

    @staticmethod
    def map_columns(
        columns: List[str], aliases: Dict[str, List[str]]
    ) -> Dict[str, Optional[str]]:
        """Mappa kolumner baserat på alias."""
        norm = DataNormalizer.normalize_key
        normalized_to_actual = {norm(c): c for c in columns}
        mapping: Dict[str, Optional[str]] = {}
        for canonical, alias_list in aliases.items():
            found = None
            for alias in alias_list:
                if norm(alias) in normalized_to_actual:
                    found = normalized_to_actual[norm(alias)]
                    break
            mapping[canonical] = found
        return mapping

class PostGenerator:
    """
    Genererar identitetsposter (PT28).

    Kan använda ts_spec_import schema eller fallback till
    hårdkodad generering.
    """

    def __init__(self, app: Any = None) -> None:
        self.app = app
        self._schema: Any = None
        self._schema_loaded: bool = False

    @property
    def schema(self) -> Any:
        """Hämta PT28-schema från ts_spec_import (lazy loading)."""
        if not self._schema_loaded:
            self._load_schema()
        return self._schema

    def _load_schema(self) -> None:
        """Ladda schema från ts_spec_import. KRASCHSÄKER."""
        self._schema_loaded = True
        self._schema = None
        if self.app is None:
            return
        ts_spec = get_plugin_safe(self.app, "ts_spec_import")
        if ts_spec is None:
            ts_spec = getattr(self.app, "ts_spec_import", None)
        if ts_spec and hasattr(ts_spec, "get_schema"):
            try:
                self._schema = ts_spec.get_schema("28")
                if self._schema:
                    _log.info(
                        "Loaded PT28 schema (version: %s)",
                        getattr(self._schema, "version", "?"),
                    )
            except Exception as e:
                _log.warning("Could not load PT28 schema: %s", e)

    def invalidate_schema_cache(self) -> None:
        """Rensa cachad schema (t.ex. efter version-byte)."""
        self._schema = None
        self._schema_loaded = False
        _log.debug("PT28 schema cache invalidated")

    @staticmethod
    def increment_filidentitet(filidentitet: str) -> str:
        """Öka siffersekvensen i filidentitet. T.ex. TS0001→TS0002."""
        if not filidentitet:
            return "TS0001"
        match = re.search(r"(.*?)(\d+)$", filidentitet)
        if match:
            prefix, num = match.groups()
            new_num = int(num) + 1
            width = max(len(num), len(str(new_num)))
            return f"{prefix}{new_num:0{width}d}"
        return f"{filidentitet}0001"

    def generate(
        self,
        orgnummer: str,
        filidentitet: str,
        datum: Optional[datetime] = None,
        lopnummer: int = 1,
    ) -> str:
        """
        Generera identitetspost (PT28).

        Args:
            orgnummer:     Organisationsnummer (10 siffror)
            filidentitet:  Filidentitet (t.ex. "TS0001")
            datum:         Datum för posten (default: idag)
            lopnummer:     Löpnummer (default: 1)

        Returns:
            Formaterad post (exakt 2500 tecken)

        Raises:
            ValueError: Om ogiltiga indata
        """
        org_cleaned = DataNormalizer.clean_orgnummer(orgnummer)
        if not org_cleaned or len(org_cleaned) != 10:
            raise ValueError(
                f"Ogiltigt organisationsnummer: '{orgnummer}'"
            )
        if not filidentitet:
            raise ValueError("Filidentitet saknas")
        if datum is None:
            datum = datetime.today()
        if self.schema:
            return self._generate_from_schema(
                org_cleaned, filidentitet, datum, lopnummer
            )
        return self._generate_hardcoded(
            org_cleaned, filidentitet, datum, lopnummer
        )

    def _generate_from_schema(
        self,
        orgnummer: str,
        filidentitet: str,
        datum: datetime,
        lopnummer: int,
    ) -> str:
        """Generera post från ts_spec_import schema."""
        data = {
            "LOPNUMMER": lopnummer,
            "VERSION": "00",
            "ORGNUMMER": orgnummer,
            "RESERV1": "",
            "FILIDENTITET": filidentitet,
            "DATUM": datum.strftime("%y%m%d"),
            "RESERV2": "",
            "POSTTYP": "28",
            "LÖPNUMMER": lopnummer,
            "ORGANISATIONSNUMMER": orgnummer,
            "ORG_NR": orgnummer,
            "FIL_ID": filidentitet,
            "DATE": datum.strftime("%y%m%d"),
            "POST_TYP": "28",
            "PT": "28",
        }
        post = self.schema.format_record(data)
        if len(post) != RECORD_LENGTH:
            _log.error(
                "PT28 from schema: %d chars, expected %d",
                len(post), RECORD_LENGTH,
            )
            post = post[:RECORD_LENGTH].ljust(RECORD_LENGTH)
        _log.debug("Generated PT28 from schema: %d chars", len(post))
        return post

    def _generate_hardcoded(
        self,
        orgnummer: str,
        filidentitet: str,
        datum: datetime,
        lopnummer: int,
    ) -> str:
        """Fallback: hårdkodad generering."""
        _log.warning(
            "Using hardcoded PT28 generation (no schema available)"
        )
        lopnr_field = str(lopnummer).zfill(4)
        version_field = PT28_VERSION
        org_field = orgnummer.zfill(ORGNUMMER_LEN)
        reserv1 = " " * RES1_LEN
        filid_field = filidentitet[:FILIDENTITET_LEN].ljust(
            FILIDENTITET_LEN
        )
        date_field = datum.strftime("%y%m%d")
        reserv2 = " " * RES2_LEN
        posttyp = PT28_POSTTYP

        prefix = (
            lopnr_field
            + version_field
            + org_field
            + reserv1
            + filid_field
            + date_field
            + reserv2
            + posttyp
        )

        expected_prefix_len = 80
        if len(prefix) != expected_prefix_len:
            _log.error(
                "PT28 prefix: %d chars, expected %d",
                len(prefix), expected_prefix_len,
            )

        post = prefix.ljust(RECORD_LENGTH)

        try:
            post.encode(TS_ENCODING)
        except UnicodeEncodeError:
            post = post.encode(
                TS_ENCODING, errors="replace"
            ).decode(TS_ENCODING)
            _log.warning("PT28: Replaced non-Latin-1 characters")

        if len(post) != RECORD_LENGTH:
            raise ValueError(
                f"Postlängd {len(post)}, förväntat {RECORD_LENGTH}"
            )
        return post

    @staticmethod
    def extract_date(post: str) -> str:
        """Extrahera datum (YYMMDD) från post."""
        start = FIELD_POSITIONS["DATUM"][0] - 1
        length = FIELD_POSITIONS["DATUM"][1]
        if len(post) < start + length:
            raise ValueError(
                "Post för kort för att extrahera datum"
            )
        return post[start : start + length]

    @staticmethod
    def extract_filidentitet(post: str) -> str:
        """Extrahera filidentitet från post."""
        start = FIELD_POSITIONS["FILIDENTITET"][0] - 1
        length = FIELD_POSITIONS["FILIDENTITET"][1]
        if len(post) < start + length:
            raise ValueError(
                "Post för kort för att extrahera filidentitet"
            )
        return post[start : start + length].strip()

    @staticmethod
    def extract_orgnummer(post: str) -> str:
        """Extrahera organisationsnummer från post."""
        start = FIELD_POSITIONS["ORGNUMMER"][0] - 1
        length = FIELD_POSITIONS["ORGNUMMER"][1]
        if len(post) < start + length:
            raise ValueError(
                "Post för kort för att extrahera orgnummer"
            )
        return post[start : start + length].strip()

    @staticmethod
    def extract_posttyp(post: str) -> str:
        """Extrahera posttyp från post."""
        start = FIELD_POSITIONS["POSTTYP"][0] - 1
        length = FIELD_POSITIONS["POSTTYP"][1]
        if len(post) < start + length:
            raise ValueError(
                "Post för kort för att extrahera posttyp"
            )
        return post[start : start + length].strip()

    @staticmethod
    def validate_post(post: str) -> Tuple[bool, List[str]]:
        """Validera en genererad post."""
        errors: List[str] = []
        if len(post) != RECORD_LENGTH:
            errors.append(
                f"Längd {len(post)}, förväntat {RECORD_LENGTH}"
            )
        try:
            post.encode(TS_ENCODING)
        except UnicodeEncodeError as e:
            errors.append(f"Innehåller ogiltiga tecken: {e}")
        if len(post) >= 80:
            posttyp = post[78:80]
            if posttyp != "28":
                errors.append(
                    f"Posttyp '{posttyp}', förväntat '28'"
                )
        return len(errors) == 0, errors

class ModelYearValidator:
    """Validerar Model Year mellan Dispatch och SAP."""

    def __init__(self, config: IdentityConfig) -> None:
        self.config = config
        self.normalizer = DataNormalizer()

    def validate(
        self, dispatch_df: Any, sap_df: Any
    ) -> Dict[str, Any]:
        """Validera Model Year. KRASCHSÄKER."""
        _log.info("Validerar Model Year (Dispatch vs SAP)")

        sap_by_vin: Dict[str, Dict] = {}
        sap_by_etg: Dict[str, Dict] = {}
        for _, row in sap_df.iterrows():
            vin = self.normalizer.sanitize_vin(row.get("VINCODE"))
            if vin:
                sap_by_vin[vin] = row.to_dict()
            etg = str(row.get("APPROVAL") or "").strip().upper()
            if etg:
                sap_by_etg[etg] = row.to_dict()

        stats = {
            "checked": 0, "ok": 0, "mismatch": 0, "missing": 0,
        }
        results: List[Dict] = []
        mismatches: List[Dict] = []

        for _, row in dispatch_df.iterrows():
            vin = self.normalizer.sanitize_vin(row.get("VIN"))
            etg = str(row.get("ETG Number") or "").strip().upper()
            dispatch_year = self.normalizer.normalize_year(
                row.get("Model Year")
            )
            if not vin and not etg:
                continue
            stats["checked"] += 1

            sap_rec = sap_by_vin.get(vin)
            if not sap_rec and etg:
                sap_rec = sap_by_etg.get(etg)

            sap_year = ""
            if sap_rec:
                sap_year = self.normalizer.normalize_year(
                    sap_rec.get("MODELYEAR")
                )

            if dispatch_year and sap_year:
                if dispatch_year == sap_year:
                    status = "OK"
                    stats["ok"] += 1
                else:
                    status = "MISMATCH"
                    stats["mismatch"] += 1
                    mismatches.append({
                        "vin": vin,
                        "etg": etg,
                        "dispatch_year": dispatch_year,
                        "sap_year": sap_year,
                    })
            else:
                status = "MISSING"
                stats["missing"] += 1

            results.append({
                "vin": vin,
                "etg": etg,
                "dispatch_year": dispatch_year,
                "sap_year": sap_year,
                "status": status,
                "matched_via": (
                    "VIN" if sap_by_vin.get(vin)
                    else ("ETG" if etg and sap_by_etg.get(etg) else "NONE")
                ),
            })

        mismatch_rate = 0.0
        if stats["checked"] > 0:
            mismatch_rate = stats["mismatch"] / stats["checked"] * 100

        return {
            "summary": {
                "rows_checked": stats["checked"],
                "ok": stats["ok"],
                "mismatch": stats["mismatch"],
                "missing": stats["missing"],
                "mismatch_rate": round(mismatch_rate, 2),
            },
            "results": results,
            "mismatches": mismatches,
            "generated_at": datetime.now().isoformat(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    Identity Post Plugin v3.2.1

    Genererar identitetsposter (PT28) för Transportstyrelsen.
    Integrerar med ts_spec_import för schemadefinitioner.

    KONTRAKT (PluginBase):
      init()              - initiera plugin
      register_ui(parent) - ingen GUI (returnerar None)
      shutdown()          - städa upp
      config_schema()     - returnera konfigurationsschema
    """

    NAME: Final[str] = PLUGIN_NAME
    VERSION: Final[str] = VERSION
    DESCRIPTION: Final[str] = "Genererar identitetsposter (PT28)"
    AUTHOR: Final[str] = AUTHOR
    DEPENDENCIES: Final[List[str]] = []
    OPTIONAL_DEPENDENCIES: Final[List[str]] = ["pandas"]

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.config: Optional[IdentityConfig] = None
        self._base_dir: Optional[Path] = None
        self._config_path: Optional[Path] = None
        self._legacy_config_path: Optional[Path] = None
        self._shutdown_done: bool = False
        self.normalizer: DataNormalizer = DataNormalizer()
        self.file_handler: FileHandler = FileHandler()
        self.post_generator: Optional[PostGenerator] = None
        self.validator: Optional[ModelYearValidator] = None
        self._event_handlers: List[Tuple[str, Callable]] = []

    # ──────────────────────────────────────────────────────────────────────
    # PLUGINBASE KONTRAKT
    # ──────────────────────────────────────────────────────────────────────

    def init(self) -> None:
        """Initiera plugin. KRASCHSÄKER."""
        try:
            base_dir = getattr(self.app, "base_dir", None)
            if not base_dir:
                base_dir = getattr(self.app, "base_path", ".")
            self._base_dir = Path(str(base_dir))
            self._config_path = (
                self._base_dir / "json" / "identitet_config.json"
            )
            self._legacy_config_path = (
                self._base_dir / ".js data" / "identitet_config.json"
            )
            self._load_config()
            self.post_generator = PostGenerator(self.app)
            self.validator = ModelYearValidator(self.config)
            try:
                self.app.identity_post = self
            except Exception:
                pass
            self._register_events()
            _log.info("Configuration loaded")
            _log.info(
                "%s v%s initialized", PLUGIN_NAME, VERSION,
            )
        except Exception as exc:
            _log.error(
                "Initiering misslyckades: %s", exc, exc_info=True,
            )

    def register_ui(self, parent: Any) -> None:
        """Ingen GUI — returnerar None."""
        return None

    def shutdown(self) -> None:
        """
        Städa upp resurser. KRASCHSÄKER.

        Anropar super().deactivate() (INTE super().shutdown()) —
        PluginBase.shutdown() anropar polymorft self.deactivate(),
        som hos oss delegerar till self.shutdown() → ömsesidig
        rekursion. super().deactivate() körs direkt (icke-polymorft):
        on_deactivate + _unsubscribe_all_events + cleanup + state →
        INACTIVE. _shutdown_done gör metoden idempotent.
        """
        if self._shutdown_done:
            return
        self._shutdown_done = True
        try:
            for event_name, handler in self._event_handlers:
                unsubscribe_event_safe(
                    self.app, event_name, handler
                )
            self._event_handlers.clear()
            _log.info("%s deactivated", PLUGIN_NAME)
        except Exception as exc:
            _log.error(
                "Shutdown misslyckades: %s", exc, exc_info=True,
            )
        finally:
            # PluginBase-livscykel: state → INACTIVE + cleanup.
            try:
                super().deactivate()
            except Exception:
                _log.exception(
                    "PluginBase.deactivate misslyckades för %s",
                    PLUGIN_NAME,
                )

    def config_schema(self) -> Dict[str, Any]:
        """Returnera konfigurationsschema. PluginBase kontrakt."""
        return {
            "plugin": PLUGIN_NAME,
            "version": VERSION,
            "author": AUTHOR,
            "copyright": get_copyright_string(),
            "settings": {
                "orgnummer": (
                    self.config.orgnummer if self.config else ""
                ),
                "filidentitet": (
                    self.config.filidentitet
                    if self.config
                    else "TS0001"
                ),
            },
        }

    # ──────────────────────────────────────────────────────────────────────
    # BAKÅTKOMPATIBILITET
    # ──────────────────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Bakåtkompatibel init. Delegerar till init()."""
        self.init()

    def activate(self) -> None:
        """Aktivera plugin (is_active sätts via PluginBase)."""
        try:
            super().activate()
        except Exception:
            _log.exception("PluginBase.activate misslyckades.")
        emit_event_safe(self.app, "identity_post:activated", {
            "version": VERSION,
            "config": (
                self.config.to_dict() if self.config else {}
            ),
        })
        _log.info("%s activated", PLUGIN_NAME)

    def deactivate(self) -> None:
        """Bakåtkompatibel deactivate. Delegerar till shutdown()."""
        self.shutdown()

    # ──────────────────────────────────────────────────────────────────────
    # EVENT HANDLING
    # ──────────────────────────────────────────────────────────────────────

    def _register_events(self) -> None:
        """Registrera event handlers. KRASCHSÄKER."""
        events = [
            ("identity_post:generate", self._handle_generate),
            ("identity_post:validate", self._handle_validate),
            ("ts_spec:version_changed", self._on_spec_changed),
            ("ts_spec:imported", self._on_spec_imported),
        ]
        for event_name, handler in events:
            if subscribe_event_safe(
                self.app, event_name, handler
            ):
                self._event_handlers.append((event_name, handler))
                _log.debug("Subscribed to: %s", event_name)

    def _on_spec_changed(self, data: Optional[Dict] = None) -> None:
        """Hantera när TS-spec version ändras."""
        if self.post_generator:
            self.post_generator.invalidate_schema_cache()
        _log.info(
            "TS spec version changed to: %s",
            (data or {}).get("version"),
        )

    def _on_spec_imported(self, data: Optional[Dict] = None) -> None:
        """Hantera när ny TS-spec importeras."""
        if self.post_generator:
            self.post_generator.invalidate_schema_cache()
        _log.info(
            "TS spec imported: %s, post_types: %s",
            (data or {}).get("version"),
            (data or {}).get("post_types"),
        )

    def _handle_generate(self, data: Dict[str, Any]) -> None:
        """Hantera generate event."""
        result = self.generate_post(
            orgnummer=data.get("orgnummer"),
            filidentitet=data.get("filidentitet"),
            datum=data.get("datum"),
            lopnummer=data.get("lopnummer", 1),
            validate_years=data.get("validate_years", False),
            allow_mismatch=data.get("allow_mismatch", True),
            increment_filid=data.get("increment_filid", True),
        )
        callback = data.get("callback")
        if callback:
            callback(result)

    def _handle_validate(self, data: Dict[str, Any]) -> None:
        """Hantera validate event."""
        try:
            result = self.validate_model_years(
                dispatch_file=data.get("dispatch_file"),
                sap_file=data.get("sap_file"),
            )
        except Exception as e:
            result = {"success": False, "error": str(e)}
        callback = data.get("callback")
        if callback:
            callback(result)

    # ──────────────────────────────────────────────────────────────────────
    # PUBLIKT API
    # ──────────────────────────────────────────────────────────────────────

    def generate_post(
        self,
        orgnummer: Optional[str] = None,
        filidentitet: Optional[str] = None,
        datum: Optional[datetime] = None,
        lopnummer: int = 1,
        validate_years: bool = False,
        allow_mismatch: bool = True,
        increment_filid: bool = True,
    ) -> Dict[str, Any]:
        """Generera identitetspost (PT28). KRASCHSÄKER."""
        try:
            _log.info("Genererar identitetspost (PT28)...")
            org = orgnummer or (
                self.config.orgnummer if self.config else ""
            )
            filid = filidentitet or (
                self.config.filidentitet
                if self.config
                else "TS0001"
            )
            if not org:
                return {
                    "success": False,
                    "error": "Organisationsnummer saknas i konfiguration",
                }

            validation_result = None
            if validate_years:
                try:
                    validation_result = self.validate_model_years()
                    mismatches = (
                        validation_result.get("summary", {}).get(
                            "mismatch", 0
                        )
                    )
                    if mismatches > 0 and not allow_mismatch:
                        return {
                            "success": False,
                            "error": (
                                f"Model Year mismatch: "
                                f"{mismatches} rader"
                            ),
                            "validation": validation_result,
                        }
                except Exception as e:
                    _log.warning(
                        "Model Year validation failed: %s", e,
                    )
                    if not allow_mismatch:
                        return {
                            "success": False,
                            "error": str(e),
                        }

            post = self.post_generator.generate(
                orgnummer=org,
                filidentitet=filid,
                datum=datum,
                lopnummer=lopnummer,
            )
            is_valid, errors = PostGenerator.validate_post(post)
            if not is_valid:
                _log.warning(
                    "Generated post validation warnings: %s",
                    errors,
                )
            date_yymmdd = PostGenerator.extract_date(post)
            filid_next = PostGenerator.increment_filidentitet(filid)

            if increment_filid and self.config:
                self.config.filidentitet = filid_next
                self._save_config()

            emit_event_safe(
                self.app,
                "identity_post:generated",
                {
                    "orgnummer": org,
                    "filidentitet": filid,
                    "filidentitet_next": filid_next,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            _log.info("PT28 generated: %s → %s", filid, filid_next)

            return {
                "success": True,
                "post": post,
                "orgnummer": org,
                "filidentitet": filid,
                "filidentitet_next": filid_next,
                "date_yymmdd": date_yymmdd,
                "length": len(post),
                "validation": validation_result,
                "spec_version": self._get_spec_version(),
                "used_schema": (
                    self.post_generator.schema is not None
                ),
            }
        except Exception as e:
            _log.exception("Failed to generate PT28")
            return {"success": False, "error": str(e)}

    def validate_model_years(
        self,
        dispatch_file: Optional[Path] = None,
        sap_file: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Validera Model Year mellan Dispatch och SAP."""
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "pandas krävs för Model Year-validering"
            )
        dispatch_dir = self._base_dir / "dispatch"
        if not dispatch_dir.exists():
            dispatch_dir = self._base_dir / "Dispatch"
        xlsx_dir = self._base_dir / "xlsx"
        disp_path = (
            dispatch_file
            or self.file_handler.find_latest_excel(dispatch_dir)
        )
        sap_path = (
            sap_file
            or self.file_handler.find_latest_excel(xlsx_dir)
        )
        if not disp_path:
            raise FileNotFoundError(
                "Ingen Dispatch-fil hittades"
            )
        if not sap_path:
            raise FileNotFoundError("Ingen SAP-fil hittades")
        _log.info("Dispatch: %s", disp_path.name)
        _log.info("SAP: %s", sap_path.name)
        dispatch_df = self._read_dispatch(disp_path)
        sap_df = self._read_sap(sap_path)
        result = self.validator.validate(dispatch_df, sap_df)
        result["dispatch_file"] = str(disp_path)
        result["sap_file"] = str(sap_path)
        summary = result["summary"]
        _log.info(
            "Validation: %d OK, %d mismatch, %d missing",
            summary["ok"],
            summary["mismatch"],
            summary["missing"],
        )
        return result

    def get_config(self) -> Dict[str, Any]:
        """Hämta konfiguration."""
        return self.config.to_dict() if self.config else {}

    def update_config(
        self, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Uppdatera konfiguration. KRASCHSÄKER."""
        try:
            if self.config is None:
                self.config = IdentityConfig()
            if "orgnummer" in updates:
                self.config.orgnummer = updates["orgnummer"]
            if "filidentitet" in updates:
                self.config.filidentitet = updates["filidentitet"]
            self._save_config()
            emit_event_safe(
                self.app,
                "identity_post:config_updated",
                {"config": self.config.to_dict()},
            )
            _log.info("Configuration updated")
            return {
                "success": True,
                "config": self.config.to_dict(),
            }
        except Exception as e:
            _log.error("Failed to update config: %s", e)
            return {"success": False, "error": str(e)}

    def get_next_filidentitet(self) -> str:
        """Hämta nästa filidentitet utan att ändra."""
        current = (
            self.config.filidentitet
            if self.config
            else "TS0000"
        )
        return PostGenerator.increment_filidentitet(current)

    def get_current_filidentitet(self) -> str:
        """Hämta nuvarande filidentitet."""
        return (
            self.config.filidentitet
            if self.config
            else "TS0001"
        )

    def get_orgnummer(self) -> str:
        """Hämta organisationsnummer."""
        return self.config.orgnummer if self.config else ""

    def invalidate_schema_cache(self) -> None:
        """Rensa cachad PT28-schema."""
        if self.post_generator:
            self.post_generator.invalidate_schema_cache()

    # ──────────────────────────────────────────────────────────────────────
    # PRIVATE METHODS
    # ──────────────────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """
        Ladda konfiguration.

        Primär: json/identitet_config.json (KRAV Z). Fallback:
        legacy ".js data/identitet_config.json" (migreras vid nästa
        spara — filen raderas ALDRIG automatiskt). Defaults om ingen
        fil finns.
        """
        try:
            candidates: List[Path] = []
            if self._config_path:
                candidates.append(self._config_path)
            if (
                self._legacy_config_path
                and self._legacy_config_path != self._config_path
            ):
                candidates.append(self._legacy_config_path)

            for path in candidates:
                if path.exists():
                    with path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.config = IdentityConfig.from_dict(data)
                    if path == self._legacy_config_path:
                        _log.info(
                            "Legacy-konfig läst från %s — migreras "
                            "till %s vid nästa spara",
                            path.name,
                            self._config_path,
                        )
                    return
            self.config = IdentityConfig()
            self.config.created_at = datetime.now().isoformat()
            self._save_config()
        except Exception as e:
            _log.warning(
                "Config load failed, using defaults: %s", e,
            )
            self.config = IdentityConfig()

    def _save_config(self) -> None:
        """Spara konfiguration till fil. KRASCHSÄKER."""
        if self.config is None:
            return
        self.config.last_updated = datetime.now().isoformat()
        if self._config_path:
            try:
                self._config_path.parent.mkdir(
                    parents=True, exist_ok=True
                )
                self.file_handler.atomic_write_json(
                    self._config_path,
                    self.config.to_dict(),
                )
            except Exception as exc:
                _log.error(
                    "Config save failed: %s", exc, exc_info=True,
                )

    def _get_spec_version(self) -> Optional[str]:
        """Hämta aktiv TS-spec version. KRASCHSÄKER."""
        ts_spec = get_plugin_safe(self.app, "ts_spec_import")
        if ts_spec is None:
            ts_spec = getattr(
                self.app, "ts_spec_import", None
            )
        if ts_spec and hasattr(ts_spec, "get_active_version"):
            try:
                return ts_spec.get_active_version()
            except Exception:
                pass
        return None

    def _read_dispatch(self, path: Path) -> Any:
        """Läs Dispatch-fil till DataFrame. KRASCHSÄKER."""
        import pandas as pd
        try:
            df = pd.read_excel(
                path,
                header=4,
                usecols="A,B,C,F,H,I,Q,R",
                engine="openpyxl",
            )
            df.columns = [
                "Sold to Dealer",
                "Dealer Name",
                "VIN",
                "Model Year",
                "Color",
                "Invoice Date",
                "Actual Production Date",
                "ETG Number",
            ]
        except Exception:
            # Fallback 1: header=4 utan usecols (samma rubrikrad).
            try:
                df = pd.read_excel(path, header=4, engine="openpyxl")
            except Exception:
                # Fallback 2: header=0 (generell layout).
                df = pd.read_excel(path, engine="openpyxl")
            df.columns = [str(c).strip() for c in df.columns]
            mapping = self.file_handler.map_columns(
                df.columns.tolist(),
                (
                    self.config.dispatch_columns
                    if self.config
                    else {}
                ),
            )
            new_cols = {v: k for k, v in mapping.items() if v}
            df = df.rename(columns=new_cols)
        if "VIN" in df.columns:
            df["VIN"] = df["VIN"].apply(
                self.normalizer.sanitize_vin
            )
            df = df[df["VIN"] != ""]
        if "Model Year" in df.columns:
            df["Model Year"] = df["Model Year"].apply(
                self.normalizer.normalize_year
            )
        if "ETG Number" in df.columns:
            df["ETG Number"] = (
                df["ETG Number"].astype(str).str.strip().str.upper()
            )
        _log.info("Dispatch: %d rows", len(df))
        return df

    def _read_sap(self, path: Path) -> Any:
        """Läs SAP-fil till DataFrame. KRASCHSÄKER."""
        import pandas as pd
        df = pd.read_excel(path, dtype=str, engine="openpyxl")
        df.columns = [str(c).strip() for c in df.columns]
        mapping = self.file_handler.map_columns(
            df.columns.tolist(),
            self.config.sap_columns if self.config else {},
        )
        new_cols = {v: k for k, v in mapping.items() if v}
        df = df.rename(columns=new_cols)
        if "VINCODE" in df.columns:
            df["VINCODE"] = (
                df["VINCODE"].astype(str).str.strip()
            )
            df = df[df["VINCODE"] != ""]
        if "MODELYEAR" in df.columns:
            df["MODELYEAR"] = df["MODELYEAR"].apply(
                self.normalizer.normalize_year
            )
        if "APPROVAL" in df.columns:
            df["APPROVAL"] = (
                df["APPROVAL"].astype(str).str.strip().str.upper()
            )
        _log.info("SAP: %d rows", len(df))
        return df


# Bakåtkompatibilitet
IdentityPostPlugin = Plugin


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Plugin
    "Plugin",
    "IdentityPostPlugin",
    # Config
    "IdentityConfig",
    # Helper classes
    "DataNormalizer",
    "FileHandler",
    "PostGenerator",
    "ModelYearValidator",
    # Helper functions
    "get_plugin_safe",
    "get_event_bus",
    "emit_event_safe",
    "subscribe_event_safe",
    "unsubscribe_event_safe",
    "get_copyright_string",
    # Constants
    "RECORD_LENGTH",
    "TS_ENCODING",
    "FIELD_POSITIONS",
    "VERSION",
    "AUTHOR",
]
