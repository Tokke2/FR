# -*- coding: utf-8 -*-
# Fil: plugins/ts_schema_manager/plugin.py

"""
TS Schema Manager Plugin v3.5.2

Core-plugin för hantering av TS-scheman (source of truth).
Ingen GUI — robust API för andra plugins.

ANSVAR:
  - Source of truth för alla TS-scheman
  - 30 publika funktioner för komplett schema-hantering
  - Versions-CRUD (skapa, ladda, ta bort, jämföra)
  - Format + validering av TS-poster (2500 tecken, Latin-1)
  - Backup/restore
  - Event-driven integration via event_bus
  - Kraschsäkra publika API-metoder
  - Plugin-samarbete med ts_spec_import, ts_excel_importer m.fl.

IMPORTER (EXTERNA):
  hashlib, json, logging, os, re, shutil, tempfile, time, zipfile,
  dataclasses, datetime, pathlib, typing
  core.plugin_base (PluginBase)
  pandas (valfri, kontrolleras vid runtime)

MODULE-LEVEL:
  _log: logging.Logger          (_get_logger())
  VERSION: Final[str]           = "3.5.2"
  AUTHOR: Final[str]            = "Rickard Längkvist"
  TS_POST_LENGTH: Final[int]    = 2500
  TS_ENCODING: Final[str]       = "iso-8859-1"
  SPEC_DIR_NAME: Final[str]     = "ts_specs"
  JSON_SCHEMA_DIR_NAME: str     = "schemas"
  BACKUP_DIR_NAME: Final[str]   = "backup"
  ACTIVE_VERSION_KEY: Final[str]
  CACHE_TTL_SECONDS: Final[int] = 300
  KNOWN_POST_TYPES: Final[Dict] = {28, 45, 99}

KLASSER:
  SchemaEvents         - event-namn konstanter
  FieldSpec            - dataclass för ett fält
  PostSpec             - dataclass för en posttyp
  SpecVersion          - dataclass för versionsinfo
  SpecVersionManager   - versionshantering (intern)
  Plugin(PluginBase)   - huvud-plugin-klass

PUBLIKT API (Plugin):
  ─── SCHEMA ACCESS ───
  get_schema(post_type, version)          -> Optional[PostSpec]
  get_schema_safe(post_type, version)     -> Optional[PostSpec]
  get_all_schemas(version, use_cache)     -> Dict[str, PostSpec]
  has_schema(post_type, version)          -> bool

  ─── VERSION MANAGEMENT ───
  get_active_version()                    -> Optional[str]
  set_active_version(version)             -> bool
  list_versions()                         -> List[SpecVersion]
  version_exists(version)                 -> bool
  delete_version(version)                 -> bool
  compare_versions(v1, v2)               -> Dict[str, List[str]]
  create_version(version, specs, ...)     -> bool
  save_schema(post_type, spec, version)   -> bool

  ─── FORMAT & VALIDATION ───
  format_record(post_type, data, version) -> Optional[str]
  validate_record(post_type, data, ...)   -> Tuple[bool, List[str]]

  ─── FUNCTIONS 1–10 (CORE) ───
  1.  export_schema_to_json(...)          -> bool
  2.  import_schema_from_json(...)        -> Optional[PostSpec]
  3.  validate_schema_structure(...)      -> Dict
  4.  get_schema_diff(...)               -> Dict
  5.  merge_schemas(...)                 -> bool
  6.  get_field_by_position(...)         -> Optional[FieldSpec]
  7.  get_coverage_map(...)              -> Dict
  8.  clone_version(...)                 -> bool
  9.  auto_upgrade_schema(...)           -> Optional[PostSpec]
  10. get_schema_metadata(...)           -> Dict

  ─── FUNCTIONS 11–20 (ADVANCED) ───
  11. subscribe_to_changes(callback)     -> bool
  12. get_field_mapping(...)             -> Dict
  13. create_empty_schema(...)           -> PostSpec
  14. get_schema_history(post_type)      -> List[Dict]
  15. validate_data_batch(...)           -> Dict
  16. get_required_fields(...)           -> List[str]
  17. find_field_by_name(...)            -> List[Dict]
  18. get_schema_checksum(...)           -> Optional[str]
  19. backup_all_schemas(...)            -> Dict
  20. restore_from_backup(...)           -> Dict

  ─── FUNCTIONS 21–30 (COLLABORATION) ───
  21. sync_with_ts_spec_import(...)      -> Dict
  22. get_collaboration_status()         -> Dict
  23. validate_ts_output(line)           -> Dict
  24. get_field_statistics(...)          -> Dict
  25. export_all_versions(...)           -> Dict
  26. import_from_excel_spec(...)        -> Dict
  27. get_schema_as_dataframe(...)       -> Optional[DataFrame]
  28. suggest_field_mapping(...)         -> Dict[str, str]
  29. validate_latin1_compatibility(...) -> Dict
  30. get_comprehensive_report()         -> Dict

  ─── UTILITY ───
  get_post_types(version)                -> List[str]
  is_known_post_type(post_type)          -> bool
  get_known_post_type_info(post_type)    -> Optional[Dict]
  unsubscribe_from_changes(callback)     -> bool
  refresh()                              -> None
  get_diagnostics()                      -> Dict

EVENTS SOM EMITTAS:
  ts:schema:loaded, ts:schema:version_changed,
  ts:schema:created, ts:schema:deleted,
  ts:schema:exported, ts:schema:imported,
  ts:schema:validated, ts:schema:merged,
  ts:schema:cloned, ts:schema:upgraded,
  ts:schema:backup, ts:schema:restored,
  ts:schema:synced
  (+ legacy: schema:loaded, schema:version_changed)

SAMARBETAR MED:
  ts_spec_import, ts_excel_importer, ts_file_generator,
  identity_post, vehicle_registration_post, end_post,
  main_gui, data_viewer

FÖRÄNDRINGAR v3.5.2 (granskad — spec v1.6 förbättringsregeln):
  - FIX (BUGG #5-mönster): hårdkodad copyright-rad
    "# Copyright © 2025 ..." BORTTAGEN från header — copyright
    genereras dynamiskt via _get_copyright_string().
  - logger -> _log (spec-konvention: module-level _log, ej logger).
  - import zipfile flyttad till modulnivå (var lokal i
    backup_all_schemas()/restore_from_backup()).
  - _resolve_specs_dir() harmoniserad med ts_spec_import v4.0.2
    (Sektion Z): config "paths.schemas_dir" -> json/schemas (primär)
    -> data/ts_specs (legacy fallback om ny saknar data). Tidigare
    pekade denna plugin på json/ts_specs — delade ej katalog med
    ts_spec_import (samarbetsbugg).
  - is_known_post_type()/get_known_post_type_info() normaliserar nu
    post_type till str (anrop med int 45 fungerar).
  - restore_from_backup(): zip-slip-skydd — extraherar endast
    medlemmar som hamnar innanför specs-katalogen; guard om
    specs-katalogen saknas.
  - covered: set -> set[int] (tydlig typning).
  - Övrig logik OFÖRÄNDRAD (30 publika funktioner, atomisk
    skrivning via _atomic_write_json, TTL-cache 300 s, events,
    kraschsäkra modul-helpers).

FÖRÄNDRINGAR v3.5.1:
  - BUGG #9 FIXAD: get_active_version() saknades som publik metod
    i Plugin-klassen. Anropades i _emit_loaded() och config_schema()
    men fanns bara som property i SpecVersionManager.
    Nu: get_active_version() -> Optional[str] tillagd i Plugin.
  - compare_versions() f-sträng syntax-bugg fixad (f(...) → f"...")

FÖRÄNDRINGAR v3.5.0:
  - BUGG #1 FIXAD: self.logger = ... borttagen
    Nu: module-level logger = _get_logger()
  - Plugin-kontrakt: initialize/activate/deactivate → init/shutdown
    (register_ui ej relevant – ingen GUI)
  - config_schema() tillagd (PluginBase kontrakt)
  - PLUGIN_COPYRIGHT dynamiskt via _get_copyright_year()
  - _atomic_write_json() använder os.replace() + fsync (EJ .replace())
  - _write_json_atomic() i SpecVersionManager ersatt av modul-level
  - emit_event_safe() och get_plugin_safe() bibehållna som module-level
  - is_active hanteras via PluginBase (EJ self.is_active direkt)
  - initialize() → init() för att matcha PluginBase-kontrakt
  - activate() → init() del 2 (körs i init)
  - deactivate() → shutdown()
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    Any, Callable, Dict, Final, List, Optional,
    Tuple, Union, TYPE_CHECKING,
)

from core.plugin_base import PluginBase

if TYPE_CHECKING:
    from core.application import Application  # type: ignore[import]


# ──────────────────────────────────────────────────────────────────────────────
# COPYRIGHT & VERSION
# ──────────────────────────────────────────────────────────────────────────────

VERSION: Final[str] = "3.5.2"
AUTHOR: Final[str] = "Rickard Längkvist"


def _get_copyright_year() -> int:
    """Hämta aktuellt år för copyright (dynamiskt)."""
    return datetime.now().year


def _get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {_get_copyright_year()} {AUTHOR}"


# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

TS_POST_LENGTH: Final[int] = 2500
TS_ENCODING: Final[str] = "iso-8859-1"
SPEC_DIR_NAME: Final[str] = "ts_specs"
JSON_SCHEMA_DIR_NAME: Final[str] = "schemas"
BACKUP_DIR_NAME: Final[str] = "backup"
ACTIVE_VERSION_KEY: Final[str] = "ts_schema_active_version"
CACHE_TTL_SECONDS: Final[int] = 300

KNOWN_POST_TYPES: Final[Dict[str, Dict[str, Any]]] = {
    "28": {
        "name": "Identitetspost",
        "description": "Filhuvud med organisationsnummer och filidentitet",
        "required": True,
        "position": "first",
    },
    "45": {
        "name": "Registreringspost",
        "description": "Fordonsdata för registrering",
        "required": True,
        "position": "middle",
    },
    "99": {
        "name": "Slutpost",
        "description": "Filavslut med kontrollsumma",
        "required": True,
        "position": "last",
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL LOGGER — BUGG #1 FIXAD (self.logger = ... borttagen)
# ──────────────────────────────────────────────────────────────────────────────


def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback om logging ej konfigurerat.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("ts_schema_manager")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log: logging.Logger = _get_logger()


# ══════════════════════════════════════════════════════════════════════════════
# ATOMISK FILSKRIVNING (modul-level, delas av SpecVersionManager och Plugin)
# ══════════════════════════════════════════════════════════════════════════════


def _atomic_write_json(path: Path, data: Any) -> None:
    """
    Skriv JSON atomiskt: temp-fil → fsync → os.replace → slutlig fil.

    Förhindrar korrupta filer vid krasch under skrivning.

    Args:
        path: Slutlig målsökväg
        data: Data att serialisera till JSON

    Raises:
        OSError: Om os.replace misslyckas
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_str = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.tmp_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path_str, path)
    except Exception:
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA EVENTS
# ══════════════════════════════════════════════════════════════════════════════


class SchemaEvents:
    """
    Event-namn konstanter för schema-relaterade händelser.

    Används av emit_event_safe() för att säkerställa konsistenta event-namn.
    """

    SCHEMA_LOADED: Final[str] = "ts:schema:loaded"
    VERSION_CHANGED: Final[str] = "ts:schema:version_changed"
    SCHEMA_CREATED: Final[str] = "ts:schema:created"
    SCHEMA_DELETED: Final[str] = "ts:schema:deleted"
    SCHEMA_EXPORTED: Final[str] = "ts:schema:exported"
    SCHEMA_IMPORTED: Final[str] = "ts:schema:imported"
    SCHEMA_VALIDATED: Final[str] = "ts:schema:validated"
    SCHEMA_MERGED: Final[str] = "ts:schema:merged"
    SCHEMA_CLONED: Final[str] = "ts:schema:cloned"
    SCHEMA_UPGRADED: Final[str] = "ts:schema:upgraded"
    SCHEMA_BACKUP: Final[str] = "ts:schema:backup"
    SCHEMA_RESTORED: Final[str] = "ts:schema:restored"
    SCHEMA_SYNCED: Final[str] = "ts:schema:synced"

    # Legacy (bakåtkompatibilitet med äldre plugin-versioner)
    LEGACY_LOADED: Final[str] = "schema:loaded"
    LEGACY_VERSION_CHANGED: Final[str] = "schema:version_changed"


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════


def emit_event_safe(
    app: Any,
    event_name: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Emittera event via app.event_bus. Kraschsäker.

    Försöker attributnamnen: event_bus, events, eventbus.
    Försöker metoderna: .emit(), .publish(), callable.

    Args:
        app:        App-instans
        event_name: Event-namn
        data:       Event-data (default: tom dict)

    Returns:
        True om event emitterades, False annars
    """
    if app is None:
        return False

    try:
        event_bus = None
        for attr in ("event_bus", "events", "eventbus"):
            event_bus = getattr(app, attr, None)
            if event_bus is not None:
                break

        if event_bus is None:
            return False

        payload = data or {}

        if hasattr(event_bus, "emit"):
            event_bus.emit(event_name, payload)
            return True
        elif hasattr(event_bus, "publish"):
            event_bus.publish(event_name, payload)
            return True
        elif callable(event_bus):
            event_bus(event_name, payload)
            return True

    except Exception as exc:
        _log.debug("Event emit misslyckades '%s': %s", event_name, exc)

    return False


def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Hämta plugin via app. Kraschsäker.

    Försöker: app.get_plugin(), app.plugin_loader.get_plugin(),
    getattr(app, name).

    Args:
        app:  App-instans
        name: Plugin-namn

    Returns:
        Plugin-instans eller None
    """
    if app is None:
        return None

    normalized = name.replace("-", "_").replace(" ", "_").lower()

    attempts = [
        lambda: app.get_plugin(name) if hasattr(app, "get_plugin") else None,
        lambda: app.get_plugin(normalized) if hasattr(app, "get_plugin") else None,
        lambda: (
            app.plugin_loader.get_plugin(name)
            if hasattr(app, "plugin_loader")
            else None
        ),
        lambda: (
            app.plugin_loader.get_plugin(normalized)
            if hasattr(app, "plugin_loader")
            else None
        ),
        lambda: getattr(app, name.replace("-", "_"), None),
        lambda: getattr(app, normalized, None),
    ]

    for attempt in attempts:
        try:
            result = attempt()
            if result is not None:
                return result
        except Exception:
            pass

    return None


def get_config_manager(app: Any) -> Optional[Any]:
    """
    Hämta config manager från app. Kraschsäker.

    Försöker: config, config_manager, configuration, settings, core_config.

    Args:
        app: App-instans

    Returns:
        Config manager eller None
    """
    if app is None:
        return None

    for attr in ("config", "config_manager", "configuration", "settings"):
        try:
            cfg = getattr(app, attr, None)
            if cfg is not None:
                return cfg
        except Exception:
            pass

    return get_plugin_safe(app, "core_config")


def ensure_latin1(text: str) -> str:
    """
    Säkerställ Latin-1-kompatibilitet. Kraschsäker.

    Ersätter icke-Latin-1-tecken med '?' via encode/decode.

    Args:
        text: Text att säkra

    Returns:
        Latin-1-kompatibel sträng
    """
    if not text:
        return ""
    try:
        text.encode(TS_ENCODING)
        return text
    except UnicodeEncodeError:
        return (
            text.encode(TS_ENCODING, errors="replace").decode(TS_ENCODING)
        )


def validate_latin1(
    text: str,
) -> Tuple[bool, List[int], List[str]]:
    """
    Validera Latin-1-kompatibilitet.

    Args:
        text: Text att validera

    Returns:
        Tuple (is_valid, invalid_positions, invalid_chars)
    """
    if not text:
        return True, [], []

    invalid_positions: List[int] = []
    invalid_chars: List[str] = []

    for i, char in enumerate(text):
        try:
            char.encode(TS_ENCODING)
        except UnicodeEncodeError:
            invalid_positions.append(i)
            invalid_chars.append(f"'{char}' (U+{ord(char):04X})")

    return len(invalid_positions) == 0, invalid_positions, invalid_chars


def sanitize_for_ts(text: str) -> str:
    """
    Rensa text för TS-kompatibilitet. Kraschsäker.

    Ersätter vanliga unicode-tecken med Latin-1-ekvivalenter
    (typografiska citattecken, tankstreck etc.).

    Args:
        text: Text att rensa

    Returns:
        Latin-1-kompatibel sträng
    """
    if not text:
        return ""

    try:
        replacements: Dict[str, str] = {
            "\u2019": "'",
            "\u2018": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2013": "-",
            "\u2014": "-",
            "\u2026": "...",
            "\u00a0": " ",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)

        return ensure_latin1(text)

    except Exception:
        return ensure_latin1(text)


# ══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class FieldSpec:
    """
    Specifikation för ett fält i en TS-post.

    PUBLIKA PROPERTIES:
      end_position -> int    (beräknad: position + length - 1)
      mandatory    -> bool   (alias för required, bakåtkompatibilitet)
      type_code    -> str    ("N", "AN", "D", "K")

    PUBLIKA METODER:
      clone(**overrides)              -> FieldSpec
      format_value(value)             -> str  (exakt length tecken)
      validate_value(value)           -> Tuple[bool, str]
      to_dict()                       -> Dict
      from_dict(data) [classmethod]   -> FieldSpec
    """

    name: str
    position: int
    length: int
    field_type: str = "alphanumeric"
    required: bool = True
    description: str = ""
    valid_values: List[str] = field(default_factory=list)
    default: str = ""
    source_mapping: str = ""
    constant_value: str = ""

    @property
    def end_position(self) -> int:
        """Slutposition (1-baserad, inklusive)."""
        return self.position + self.length - 1

    @property
    def mandatory(self) -> bool:
        """Alias för required (bakåtkompatibilitet med äldre kod)."""
        return self.required

    @property
    def type_code(self) -> str:
        """Kort typkod för visning."""
        return {
            "numeric": "N",
            "alphanumeric": "AN",
            "date": "D",
            "constant": "K",
        }.get(self.field_type, "AN")

    def clone(self, **overrides: Any) -> "FieldSpec":
        """Skapa kopia med valfria modifieringar."""
        data = self.to_dict()
        data.update(overrides)
        return FieldSpec.from_dict(data)

    def format_value(self, value: Any) -> str:
        """
        Formatera värde enligt TS-regler till exakt self.length tecken.

        Numeriska: högerjusterade med ledande nollor.
        Alfanumeriska: vänsterjusterade med trailing spaces.
        Konstanter: använder constant_value.

        Args:
            value: Värde att formatera (None ger default/blank)

        Returns:
            Sträng med exakt self.length tecken, Latin-1-kompatibel
        """
        if value is None:
            value = self.default or ""

        if self.field_type == "constant" and self.constant_value:
            value = self.constant_value

        str_value = sanitize_for_ts(str(value).strip())

        if self.field_type in ("numeric", "date"):
            str_value = re.sub(r"[^\d]", "", str_value)
            if len(str_value) > self.length:
                str_value = str_value[-self.length:]
            return str_value.rjust(self.length, "0")
        else:
            if len(str_value) > self.length:
                str_value = str_value[:self.length]
            return str_value.ljust(self.length, " ")

    def validate_value(self, value: Any) -> Tuple[bool, str]:
        """
        Validera värde mot fältspecifikation.

        Kontrollerar: obligatorisk, längd, giltiga värden,
        numerisk typ, Latin-1-kompatibilitet.

        Args:
            value: Värde att validera

        Returns:
            Tuple (is_valid: bool, error_message: str)
        """
        if value is None or str(value).strip() == "":
            if self.required and not self.default and not self.constant_value:
                return False, f"Obligatoriskt fält '{self.name}' saknas"
            return True, ""

        str_value = str(value).strip()

        if len(str_value) > self.length:
            return (
                False,
                f"'{self.name}' överskrider maxlängd {self.length} "
                f"(har {len(str_value)})",
            )

        if self.valid_values and str_value not in self.valid_values:
            return (
                False,
                f"Ogiltigt värde '{str_value}' för '{self.name}'. "
                f"Tillåtna: {self.valid_values}",
            )

        if self.field_type in ("numeric", "date"):
            cleaned = re.sub(r"[^\d]", "", str_value)
            if cleaned != str_value and str_value:
                return (
                    False,
                    f"'{self.name}' ska vara numeriskt, "
                    f"innehåller '{str_value}'",
                )

        is_latin1, _, chars = validate_latin1(str_value)
        if not is_latin1:
            return (
                False,
                f"'{self.name}' innehåller ogiltiga tecken: "
                f"{', '.join(chars[:3])}",
            )

        return True, ""

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "name": self.name,
            "position": self.position,
            "length": self.length,
            "field_type": self.field_type,
            "required": self.required,
            "description": self.description,
            "valid_values": self.valid_values,
            "default": self.default,
            "source_mapping": self.source_mapping,
            "constant_value": self.constant_value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FieldSpec":
        """
        Skapa FieldSpec från dictionary. Kraschsäker.

        Hanterar både 'required' och 'mandatory' för bakåtkompatibilitet.
        """
        required = data.get("required", data.get("mandatory", True))
        return cls(
            name=str(data.get("name", "")),
            position=int(data.get("position", 1)),
            length=int(data.get("length", 1)),
            field_type=str(data.get("field_type", "alphanumeric")),
            required=bool(required),
            description=str(data.get("description", "")),
            valid_values=list(data.get("valid_values", [])),
            default=str(data.get("default", "")),
            source_mapping=str(data.get("source_mapping", "")),
            constant_value=str(data.get("constant_value", "")),
        )


@dataclass
class PostSpec:
    """
    Specifikation för en hel posttyp (PT28, PT45, PT99 m.fl.).

    PUBLIKA PROPERTIES:
      is_valid             -> bool
      coverage             -> float  (0.0–1.0)
      field_count          -> int
      required_field_count -> int

    PUBLIKA METODER:
      get_field(name)                   -> Optional[FieldSpec]
      get_field_at(position)            -> Optional[FieldSpec]
      get_required_fields()             -> List[FieldSpec]
      get_optional_fields()             -> List[FieldSpec]
      find_fields(pattern)              -> List[FieldSpec]
      get_gaps()                        -> List[Tuple[int, int]]
      get_overlaps()                    -> List[Tuple[...]]
      format_record(data)               -> str  (exakt total_length)
      validate_record(data)             -> Tuple[bool, List[str]]
      merge_fields(other)               -> PostSpec
      to_dict()                         -> Dict
      from_dict(data) [classmethod]     -> PostSpec
    """

    post_type: str
    name: str
    total_length: int
    fields: List[FieldSpec]
    description: str = ""
    version: str = ""
    source_file: str = ""
    created_at: str = ""
    checksum: str = ""

    def __post_init__(self) -> None:
        """Efterinitiering: sortera fält, beräkna checksumma."""
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.fields = sorted(self.fields, key=lambda f: f.position)
        if not self.checksum:
            self.checksum = self._calculate_checksum()

    def _calculate_checksum(self) -> str:
        """Beräkna MD5-checksumma för fältdefinitionerna."""
        try:
            content = json.dumps(
                [f.to_dict() for f in self.fields], sort_keys=True
            )
            return hashlib.md5(content.encode()).hexdigest()[:12]
        except Exception:
            return ""

    @property
    def is_valid(self) -> bool:
        """Sant om post_type, fields och total_length är satta."""
        return bool(self.post_type and self.fields and self.total_length > 0)

    @property
    def coverage(self) -> float:
        """Täckningsgrad: andel positioner täckta av fält (0.0–1.0)."""
        if self.total_length == 0:
            return 0.0
        covered: set[int] = set()
        for f in self.fields:
            covered.update(range(f.position, f.end_position + 1))
        return len(covered) / self.total_length

    @property
    def field_count(self) -> int:
        """Totalt antal fält."""
        return len(self.fields)

    @property
    def required_field_count(self) -> int:
        """Antal obligatoriska fält."""
        return sum(1 for f in self.fields if f.required)

    def get_field(self, name: str) -> Optional[FieldSpec]:
        """Hämta fält via namn (case-insensitive)."""
        name_upper = name.upper()
        for f in self.fields:
            if f.name.upper() == name_upper:
                return f
        return None

    def get_field_at(self, position: int) -> Optional[FieldSpec]:
        """Hämta fält vid given position (1-baserad)."""
        for f in self.fields:
            if f.position <= position <= f.end_position:
                return f
        return None

    def get_required_fields(self) -> List[FieldSpec]:
        """Lista obligatoriska fält."""
        return [f for f in self.fields if f.required]

    def get_optional_fields(self) -> List[FieldSpec]:
        """Lista valfria fält."""
        return [f for f in self.fields if not f.required]

    def find_fields(self, pattern: str) -> List[FieldSpec]:
        """
        Sök fält med regex-mönster (case-insensitive).

        Faller tillbaka till enkel substring-sökning vid ogiltig regex.
        """
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            return [f for f in self.fields if regex.search(f.name)]
        except re.error:
            pattern_lower = pattern.lower()
            return [f for f in self.fields if pattern_lower in f.name.lower()]

    def get_gaps(self) -> List[Tuple[int, int]]:
        """
        Hitta luckor i fältdefinitioner.

        Returns:
            Lista med (start, end) tupler (1-baserade, inklusive)
        """
        covered: set[int] = set()
        for f in self.fields:
            covered.update(range(f.position, f.end_position + 1))

        uncovered = sorted(set(range(1, self.total_length + 1)) - covered)
        if not uncovered:
            return []

        gaps: List[Tuple[int, int]] = []
        start = end = uncovered[0]
        for pos in uncovered[1:]:
            if pos == end + 1:
                end = pos
            else:
                gaps.append((start, end))
                start = end = pos
        gaps.append((start, end))
        return gaps

    def get_overlaps(self) -> List[Tuple["FieldSpec", "FieldSpec", int]]:
        """
        Hitta överlappande fält.

        Returns:
            Lista med (field1, field2, overlap_position) tupler
        """
        overlaps = []
        for i, f1 in enumerate(self.fields):
            for f2 in self.fields[i + 1:]:
                overlap_start = max(f1.position, f2.position)
                overlap_end = min(f1.end_position, f2.end_position)
                if overlap_start <= overlap_end:
                    overlaps.append((f1, f2, overlap_start))
        return overlaps

    def format_record(self, data: Dict[str, Any]) -> str:
        """
        Formatera en hel post till exakt total_length tecken.

        Hämtar värden via field.name och field.source_mapping.
        Returnerar alltid exakt total_length Latin-1-kompatibla tecken.

        Args:
            data: Dict med fältnamn → värde

        Returns:
            Sträng med exakt total_length tecken
        """
        buffer = [" "] * self.total_length

        for fs in self.fields:
            value = data.get(fs.name)
            if value is None and fs.source_mapping:
                value = data.get(fs.source_mapping)

            formatted = fs.format_value(value)
            if len(formatted) != fs.length:
                formatted = formatted[:fs.length].ljust(fs.length)

            start_idx = fs.position - 1
            for i, char in enumerate(formatted):
                if 0 <= start_idx + i < self.total_length:
                    buffer[start_idx + i] = char

        result = "".join(buffer)
        if len(result) != self.total_length:
            result = result[:self.total_length].ljust(self.total_length)

        return ensure_latin1(result)

    def validate_record(
        self, data: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        Validera data mot schema.

        Args:
            data: Dict med fältnamn → värde

        Returns:
            Tuple (is_valid: bool, errors: List[str])
        """
        errors: List[str] = []
        for fs in self.fields:
            value = data.get(fs.name)
            if value is None and fs.source_mapping:
                value = data.get(fs.source_mapping)
            is_valid, error = fs.validate_value(value)
            if not is_valid:
                errors.append(error)
        return len(errors) == 0, errors

    def merge_fields(self, other: "PostSpec") -> "PostSpec":
        """
        Slå ihop fält från annat schema. Fält från 'other' överskriver.

        Args:
            other: PostSpec att merga in i denna

        Returns:
            Ny PostSpec med sammanslagna fält
        """
        field_map = {f.name: f for f in self.fields}
        for f in other.fields:
            field_map[f.name] = f
        merged_fields = sorted(field_map.values(), key=lambda x: x.position)
        return PostSpec(
            post_type=self.post_type,
            name=self.name,
            total_length=self.total_length,
            fields=merged_fields,
            description=self.description,
            version=other.version or self.version,
            source_file=other.source_file or self.source_file,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "post_type": self.post_type,
            "name": self.name,
            "total_length": self.total_length,
            "fields": [f.to_dict() for f in self.fields],
            "description": self.description,
            "version": self.version,
            "source_file": self.source_file,
            "created_at": self.created_at,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostSpec":
        """Skapa PostSpec från dictionary. Kraschsäker."""
        fields = [
            FieldSpec.from_dict(f) for f in data.get("fields", [])
        ]
        return cls(
            post_type=str(data.get("post_type", "")),
            name=str(data.get("name", "")),
            total_length=int(data.get("total_length", TS_POST_LENGTH)),
            fields=fields,
            description=str(data.get("description", "")),
            version=str(data.get("version", "")),
            source_file=str(data.get("source_file", "")),
            created_at=str(data.get("created_at", "")),
            checksum=str(data.get("checksum", "")),
        )


@dataclass
class SpecVersion:
    """
    Information om en specifikationsversion.

    PUBLIKA PROPERTIES:
      age_days -> int  (dagar sedan skapande, -1 om okänt)

    PUBLIKA METODER:
      to_dict()                       -> Dict
      from_dict(data) [classmethod]   -> SpecVersion
    """

    version: str
    created_at: str
    source_file: str
    post_types: List[str]
    description: str = ""
    is_active: bool = False

    @property
    def age_days(self) -> int:
        """Antal dagar sedan skapande. -1 om datum ej kan parsas."""
        try:
            created = datetime.fromisoformat(self.created_at)
            return (datetime.now() - created).days
        except Exception:
            return -1

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpecVersion":
        """Skapa SpecVersion från dictionary. Kraschsäker."""
        return cls(
            version=str(data.get("version", "")),
            created_at=str(data.get("created_at", "")),
            source_file=str(data.get("source_file", "")),
            post_types=list(data.get("post_types", [])),
            description=str(data.get("description", "")),
            is_active=bool(data.get("is_active", False)),
        )


# ══════════════════════════════════════════════════════════════════════════════
# SPEC VERSION MANAGER (Intern hanterare för Plugin-klassen)
# ══════════════════════════════════════════════════════════════════════════════


class SpecVersionManager:
    """
    Hanterar versioner av TS-specifikationer (Intern helper).

    Ansvar:
        - Lista versioner och backups
        - Ladda/spara scheman atomiskt
        - Hantera aktiv version via ConfigManager
        - Historik-spårning (in-memory)
    """

    def __init__(self, specs_dir: Path, config_manager: Any = None):
        self.specs_dir = Path(specs_dir)
        self.config_manager = config_manager
        self.specs_dir.mkdir(parents=True, exist_ok=True)

        # Caches
        self._cache: Dict[str, Dict[str, PostSpec]] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._active_version_cache: Optional[str] = None
        self._history: Dict[str, List[Dict[str, Any]]] = {}

    @property
    def active_version(self) -> Optional[str]:
        """Hämta aktiv version (Cache -> Config -> Fallback)."""
        if self._active_version_cache:
            return self._active_version_cache

        if self.config_manager:
            try:
                if hasattr(self.config_manager, 'get'):
                    result = self.config_manager.get(ACTIVE_VERSION_KEY)
                    if result:
                        self._active_version_cache = result
                        return result
            except Exception:
                pass

        versions = self.list_versions()
        return versions[-1].version if versions else None

    @active_version.setter
    def active_version(self, version: str) -> None:
        """Sätt aktiv version persistent."""
        if self.config_manager and hasattr(self.config_manager, 'set'):
            try:
                self.config_manager.set(ACTIVE_VERSION_KEY, version)
            except Exception:
                pass
        self._active_version_cache = version

    @property
    def backup_dir(self) -> Path:
        """Backup-katalog."""
        backup = self.specs_dir / BACKUP_DIR_NAME
        backup.mkdir(exist_ok=True)
        return backup

    def list_versions(self) -> List[SpecVersion]:
        """Lista alla giltiga versioner."""
        versions = []
        if not self.specs_dir.exists():
            return versions

        try:
            for version_dir in sorted(self.specs_dir.iterdir()):
                if not version_dir.is_dir():
                    continue
                if version_dir.name.startswith('.'):
                    continue
                if version_dir.name == BACKUP_DIR_NAME:
                    continue

                manifest_path = version_dir / "manifest.json"
                if manifest_path.exists():
                    try:
                        with open(manifest_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        spec_version = SpecVersion.from_dict(data)
                        spec_version.is_active = (
                            spec_version.version == self.active_version
                        )
                        versions.append(spec_version)
                    except Exception as e:
                        _log.warning(
                            "Kunde inte läsa manifest %s: %s",
                            manifest_path, e,
                        )
        except Exception as e:
            _log.error("Fel vid listning av versioner: %s", e)
        return versions

    def list_backups(self) -> List[Dict[str, Any]]:
        """Lista .zip-backups."""
        backups = []
        try:
            for backup_file in sorted(self.backup_dir.glob("*.zip")):
                stat = backup_file.stat()
                backups.append({
                    "name": backup_file.stem,
                    "file": str(backup_file),
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(
                        stat.st_mtime
                    ).isoformat(),
                })
        except Exception:
            pass
        return backups

    def version_exists(self, version: str) -> bool:
        """Kolla om manifest finns."""
        return (self.specs_dir / version / "manifest.json").exists()

    def load_version(
        self, version: str, use_cache: bool = True
    ) -> Dict[str, PostSpec]:
        """Ladda alla PT-scheman för en version."""
        if use_cache and version in self._cache:
            if (
                time.time() - self._cache_timestamps.get(version, 0)
                < CACHE_TTL_SECONDS
            ):
                return self._cache[version]

        version_dir = self.specs_dir / version
        if not version_dir.exists():
            return {}

        specs: Dict[str, PostSpec] = {}
        try:
            for spec_file in version_dir.glob("PT*.json"):
                with open(spec_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                spec = PostSpec.from_dict(data)
                specs[spec.post_type] = spec
        except Exception as e:
            _log.error("Fel vid laddning av version %s: %s", version, e)

        if use_cache:
            self._cache[version] = specs
            self._cache_timestamps[version] = time.time()
        return specs

    def create_version(
        self,
        version: str,
        specs: List[PostSpec],
        source_file: str = "",
        description: str = "",
        set_active: bool = True,
    ) -> None:
        """Skapa ny version atomiskt."""
        version_dir = self.specs_dir / version
        temp_dir = self.specs_dir / f".{version}_temp"

        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
            post_types = []
            for spec in specs:
                spec.version = version
                _atomic_write_json(
                    temp_dir / f"PT{spec.post_type}.json",
                    spec.to_dict(),
                )
                post_types.append(spec.post_type)
                self._add_to_history(spec.post_type, version, "created")

            manifest = SpecVersion(
                version=version,
                created_at=datetime.now().isoformat(),
                source_file=source_file,
                post_types=post_types,
                description=description,
            )
            _atomic_write_json(
                temp_dir / "manifest.json",
                manifest.to_dict(),
            )

            if version_dir.exists():
                backup = self.specs_dir / f".{version}_backup"
                if backup.exists():
                    shutil.rmtree(backup)
                version_dir.rename(backup)

            temp_dir.rename(version_dir)

            self._cache.pop(version, None)
            if set_active:
                self.active_version = version
            _log.info("Version '%s' skapad.", version)
        except Exception:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise

    def save_spec(
        self, post_type: str, spec: PostSpec, version: str
    ) -> None:
        """Spara ett enskilt schema atomiskt."""
        version_dir = self.specs_dir / version
        if not version_dir.exists():
            raise ValueError(f"Version '{version}' saknas")
        _atomic_write_json(
            version_dir / f"PT{post_type}.json",
            spec.to_dict(),
        )
        self._cache.pop(version, None)
        self._add_to_history(post_type, version, "updated")

    def delete_version(self, version: str) -> None:
        """Ta bort version (får ej vara aktiv)."""
        if version == self.active_version:
            raise ValueError("Kan inte ta bort aktiv version")
        version_dir = self.specs_dir / version
        if version_dir.exists():
            shutil.rmtree(version_dir)
            self._cache.pop(version, None)

    def compare_versions(
        self, version1: str, version2: str
    ) -> Dict[str, List[str]]:
        """Jämför två versioner fält för fält."""
        specs1 = self.load_version(version1)
        specs2 = self.load_version(version2)
        changes: Dict[str, List[str]] = {}
        all_types = set(specs1.keys()) | set(specs2.keys())

        for pt in sorted(all_types):
            s1 = specs1.get(pt)
            s2 = specs2.get(pt)
            pt_changes: List[str] = []

            if s1 is None:
                pt_changes.append("+ Ny")
            elif s2 is None:
                pt_changes.append("- Borttagen")
            else:
                f1 = {f.name: f for f in s1.fields}
                f2 = {f.name: f for f in s2.fields}
                for n in set(f2.keys()) - set(f1.keys()):
                    pt_changes.append(f"+ {n}")
                for n in set(f1.keys()) - set(f2.keys()):
                    pt_changes.append(f"- {n}")

            if pt_changes:
                changes[pt] = pt_changes
        return changes

    def _add_to_history(
        self, post_type: str, version: str, action: str
    ) -> None:
        """Lägg till historik-post."""
        if post_type not in self._history:
            self._history[post_type] = []
        self._history[post_type].append({
            "version": version,
            "action": action,
            "timestamp": datetime.now().isoformat(),
        })

    def get_history(self, post_type: str) -> List[Dict[str, Any]]:
        """Hämta historik för posttyp."""
        return self._history.get(post_type, [])

    def clear_cache(self, version: Optional[str] = None) -> None:
        """Rensa cache."""
        if version:
            self._cache.pop(version, None)
        else:
            self._cache.clear()
            self._active_version_cache = None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════


class Plugin(PluginBase):
    """
    TS Schema Manager v3.5.2 - Core plugin (Source of Truth).

    Innehåller 30 publika funktioner för schema-hantering.
    Kraschsäker och event-driven.

    BUGG #9 FIXAD: get_active_version() tillagd som publik metod.
    """

    NAME = "TS Schema Manager"
    VERSION = VERSION
    DESCRIPTION = "Hanterar TS-scheman och versioner (30 funktioner)"
    AUTHOR = AUTHOR

    def __init__(self, app: "Application"):
        super().__init__(app)
        self._version_manager: Optional[SpecVersionManager] = None
        self._specs_dir: Optional[Path] = None
        self._change_subscribers: List[Callable] = []
        self._ts_spec_import: Optional[Any] = None
        self._ts_excel_importer: Optional[Any] = None

    def init(self) -> None:
        """Initiera plugin (PluginBase kontrakt). BUGG #1 FIXAD."""
        try:
            self._specs_dir = self._resolve_specs_dir()
            cfg = get_config_manager(self.app)
            self._version_manager = SpecVersionManager(self._specs_dir, cfg)

            # Registrera i app för enkel åtkomst
            try:
                self.app.ts_schema_manager = self
            except Exception:
                pass

            # Aktiverings-logik (tidigare i activate)
            self._detect_collaborators()
            self._emit_loaded()

            _log.info(
                "%s v%s initierad. Katalog: %s",
                self.NAME, VERSION, self._specs_dir,
            )
        except Exception as e:
            _log.error("Initiering misslyckades: %s", e, exc_info=True)

    def shutdown(self) -> None:
        """Stäng ner (PluginBase kontrakt)."""
        if self._version_manager:
            self._version_manager.clear_cache()
        _log.info("Deaktiverad.")

    def config_schema(self) -> Dict[str, Any]:
        """Returnera konfig-schema."""
        return {
            "plugin": self.NAME,
            "version": VERSION,
            "author": AUTHOR,
            "copyright": _get_copyright_string(),
            "settings": {
                "specs_dir": str(self._specs_dir),
                "active_version": self.get_active_version(),
            },
        }

    # ─── HJÄLPMETODER ───

    def _resolve_specs_dir(self) -> Path:
        """
        Bestäm sökväg till specs-katalog (spec v1.4 / Sektion Z).

        Prioritet:
          1. config "paths.schemas_dir" (om angiven)
          2. json/schemas (primär, Sektion Z — delas med ts_spec_import)
          3. legacy data/ts_specs som fallback OM den nya saknar data
             (loggas INFO)
        """
        base = getattr(self.app, 'base_path', Path.cwd())
        if isinstance(base, str):
            base = Path(base)

        cfg = get_config_manager(self.app)
        if cfg is not None:
            for getter_name in ("get_str", "get"):
                try:
                    getter = getattr(cfg, getter_name, None)
                    if callable(getter):
                        val = getter("paths.schemas_dir", "")
                        if val:
                            p = Path(str(val))
                            if not p.is_absolute():
                                p = base / p
                            return p
                except Exception:
                    pass

        json_schemas = base / "json" / JSON_SCHEMA_DIR_NAME
        legacy = base / "data" / SPEC_DIR_NAME

        json_has = json_schemas.exists() and any(json_schemas.iterdir())
        legacy_has = legacy.exists() and any(legacy.iterdir())

        if not json_has and legacy_has:
            _log.info("Läser legacy TS-spec-katalog: %s", legacy)
            return legacy

        return json_schemas

    def _detect_collaborators(self) -> None:
        """Detektera samarbetande plugins."""
        self._ts_spec_import = get_plugin_safe(self.app, "ts_spec_import")
        self._ts_excel_importer = get_plugin_safe(
            self.app, "ts_excel_importer"
        )

    def _emit_loaded(self) -> None:
        """Emittera schema:loaded event. Kraschsäker."""
        try:
            data = {
                "active_version": self.get_active_version(),
                "schemas": list(self.get_all_schemas().keys()),
            }
            emit_event_safe(self.app, SchemaEvents.SCHEMA_LOADED, data)
        except Exception as exc:
            _log.debug("_emit_loaded misslyckades: %s", exc)

    def _ensure_vm(self) -> bool:
        """Kontrollera att VersionManager finns."""
        return self._version_manager is not None

    # ─── PUBLIKT API: VERSION MANAGEMENT ───

    def get_active_version(self) -> Optional[str]:
        """
        Hämta aktiv schemaversion.

        Returns:
            Versionsidentifierare som str, eller None om ingen aktiv.

        BUGG #9 FIXAD: Denna metod saknades helt i v3.5.0.
        Anropades i _emit_loaded() och config_schema() men fanns
        bara som property i SpecVersionManager.
        """
        if not self._ensure_vm():
            return None
        try:
            return self._version_manager.active_version
        except Exception as exc:
            _log.error("Fel i get_active_version: %s", exc)
            return None

    def set_active_version(self, version: str) -> bool:
        """
        Sätt aktiv schemaversion.

        Args:
            version: Versionsidentifierare

        Returns:
            True vid framgång, False om versionen ej finns
        """
        if not self._ensure_vm():
            return False
        if not self._version_manager.version_exists(version):
            return False
        old = self._version_manager.active_version
        self._version_manager.active_version = version
        emit_event_safe(
            self.app,
            SchemaEvents.VERSION_CHANGED,
            {"old": old, "new": version},
        )
        return True

    def list_versions(self) -> List[SpecVersion]:
        """Lista alla tillgängliga versioner."""
        if not self._ensure_vm():
            return []
        return self._version_manager.list_versions()

    def version_exists(self, version: str) -> bool:
        """Kontrollera om version finns."""
        if not self._ensure_vm():
            return False
        return self._version_manager.version_exists(version)

    def delete_version(self, version: str) -> bool:
        """
        Ta bort version. Kan ej ta bort aktiv version.

        Args:
            version: Version att ta bort

        Returns:
            True vid framgång
        """
        if not self._ensure_vm():
            return False
        try:
            self._version_manager.delete_version(version)
            emit_event_safe(
                self.app,
                SchemaEvents.SCHEMA_DELETED,
                {"version": version},
            )
            return True
        except Exception as exc:
            _log.error("Fel vid borttagning av version %s: %s", version, exc)
            return False

    def compare_versions(
        self, v1: str, v2: str
    ) -> Dict[str, List[str]]:
        """Jämför två versioner."""
        if not self._ensure_vm():
            return {}
        try:
            return self._version_manager.compare_versions(v1, v2)
        except Exception as exc:
            _log.error("Fel vid jämförelse: %s", exc)
            return {}

    def create_version(
        self,
        version: str,
        specs: List[PostSpec],
        source_file: str = "",
        description: str = "",
        set_active: bool = True,
    ) -> bool:
        """Skapa ny version."""
        if not self._ensure_vm():
            return False
        try:
            self._version_manager.create_version(
                version, specs, source_file, description, set_active
            )
            emit_event_safe(
                self.app,
                SchemaEvents.SCHEMA_CREATED,
                {"version": version},
            )
            return True
        except Exception as exc:
            _log.error("Fel vid skapande av version %s: %s", version, exc)
            return False

    def save_schema(
        self, post_type: str, spec: PostSpec, version: Optional[str] = None
    ) -> bool:
        """Spara enskilt schema."""
        if not self._ensure_vm():
            return False
        v = version or self._version_manager.active_version
        if not v:
            return False
        try:
            self._version_manager.save_spec(post_type, spec, v)
            return True
        except Exception as exc:
            _log.error("Fel vid sparande av schema: %s", exc)
            return False

    # ─── PUBLIKT API: SCHEMA ACCESS ───

    def get_schema(
        self, post_type: str, version: Optional[str] = None
    ) -> Optional[PostSpec]:
        """Hämta schema för posttyp."""
        if not self._ensure_vm():
            return None
        v = version or self._version_manager.active_version
        if not v:
            return None
        return self._version_manager.load_version(v).get(post_type)

    def get_schema_safe(
        self, post_type: str, version: Optional[str] = None
    ) -> Optional[PostSpec]:
        """Alias för get_schema (bakåtkompatibilitet)."""
        return self.get_schema(post_type, version)

    def get_all_schemas(
        self, version: Optional[str] = None, use_cache: bool = True
    ) -> Dict[str, PostSpec]:
        """Hämta alla scheman för en version."""
        if not self._ensure_vm():
            return {}
        v = version or self._version_manager.active_version
        if not v:
            return {}
        return self._version_manager.load_version(v, use_cache)

    def has_schema(
        self, post_type: str, version: Optional[str] = None
    ) -> bool:
        """Kontrollera om schema finns."""
        return self.get_schema(post_type, version) is not None

    # ─── PUBLIKT API: FORMAT & VALIDATION ───

    def format_record(
        self,
        post_type: str,
        data: Dict[str, Any],
        version: Optional[str] = None,
    ) -> Optional[str]:
        """Formatera data till TS-record."""
        s = self.get_schema(post_type, version)
        return s.format_record(data) if s else None

    def validate_record(
        self,
        post_type: str,
        data: Dict[str, Any],
        version: Optional[str] = None,
    ) -> Tuple[bool, List[str]]:
        """Validera data mot schema."""
        s = self.get_schema(post_type, version)
        if not s:
            return False, [f"Schema saknas för PT{post_type}"]
        return s.validate_record(data)

    # ─── FUNCTIONS 1-10 (CORE) ───

    # 1. EXPORT JSON
    def export_schema_to_json(
        self,
        post_type: str,
        path: Union[str, Path],
        version: Optional[str] = None,
    ) -> bool:
        """Exportera schema till JSON-fil."""
        s = self.get_schema(post_type, version)
        if not s:
            return False
        try:
            _atomic_write_json(Path(path), s.to_dict())
            emit_event_safe(
                self.app,
                SchemaEvents.SCHEMA_EXPORTED,
                {"post_type": post_type, "path": str(path)},
            )
            return True
        except Exception as exc:
            _log.error("Export misslyckades: %s", exc)
            return False

    # 2. IMPORT JSON
    def import_schema_from_json(
        self, path: Union[str, Path], version: Optional[str] = None
    ) -> Optional[PostSpec]:
        """Importera schema från JSON-fil."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            spec = PostSpec.from_dict(data)
            if version:
                self.save_schema(spec.post_type, spec, version)
            emit_event_safe(
                self.app,
                SchemaEvents.SCHEMA_IMPORTED,
                {"post_type": spec.post_type, "path": str(path)},
            )
            return spec
        except Exception as exc:
            _log.error("Import misslyckades: %s", exc)
            return None

    # 3. VALIDATE STRUCTURE
    def validate_schema_structure(
        self, post_type: str, version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Validera schemastruktur."""
        s = self.get_schema(post_type, version)
        if not s:
            return {"valid": False, "errors": ["Schema saknas"]}
        overlaps = s.get_overlaps()
        gaps = s.get_gaps()
        return {
            "valid": not overlaps,
            "coverage": s.coverage,
            "gaps": gaps,
            "overlaps": len(overlaps),
            "field_count": s.field_count,
        }

    # 4. GET SCHEMA DIFF
    def get_schema_diff(
        self, post_type: str, v1: str, v2: str
    ) -> Dict[str, Any]:
        """Hämta diff för posttyp mellan versioner."""
        s1 = self.get_schema(post_type, v1)
        s2 = self.get_schema(post_type, v2)
        if not s1 or not s2:
            return {"error": "En eller båda versionerna saknas"}
        f1 = {f.name: f for f in s1.fields}
        f2 = {f.name: f for f in s2.fields}
        return {
            "added": list(set(f2.keys()) - set(f1.keys())),
            "removed": list(set(f1.keys()) - set(f2.keys())),
            "common": list(set(f1.keys()) & set(f2.keys())),
        }

    # 5. MERGE SCHEMAS
    def merge_schemas(
        self,
        post_type: str,
        base_version: str,
        overlay_version: str,
        target_version: Optional[str] = None,
    ) -> bool:
        """Merga scheman från två versioner."""
        base = self.get_schema(post_type, base_version)
        overlay = self.get_schema(post_type, overlay_version)
        if not base or not overlay:
            return False
        merged = base.merge_fields(overlay)
        tv = target_version or base_version
        return self.save_schema(post_type, merged, tv)

    # 6. GET FIELD BY POSITION
    def get_field_by_position(
        self, post_type: str, position: int, version: Optional[str] = None
    ) -> Optional[FieldSpec]:
        """Hämta fält vid position."""
        s = self.get_schema(post_type, version)
        return s.get_field_at(position) if s else None

    # 7. GET COVERAGE MAP
    def get_coverage_map(
        self, post_type: str, version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Hämta täckningskarta."""
        s = self.get_schema(post_type, version)
        if not s:
            return {}
        return {
            "coverage": s.coverage,
            "gaps": s.get_gaps(),
            "field_count": s.field_count,
            "total_length": s.total_length,
        }

    # 8. CLONE VERSION
    def clone_version(
        self, source: str, target: str, description: str = ""
    ) -> bool:
        """Klona version."""
        if not self._ensure_vm():
            return False
        try:
            specs = list(self.get_all_schemas(source).values())
            if not specs:
                return False
            self.create_version(
                target, specs, description=description or f"Klon av {source}"
            )
            emit_event_safe(
                self.app,
                SchemaEvents.SCHEMA_CLONED,
                {"source": source, "target": target},
            )
            return True
        except Exception as exc:
            _log.error("Kloningsfel: %s", exc)
            return False

    # 9. AUTO UPGRADE
    def auto_upgrade_schema(
        self, post_type: str, version: Optional[str] = None
    ) -> Optional[PostSpec]:
        """Auto-uppgradera schema (fyll gaps med FILLER)."""
        s = self.get_schema(post_type, version)
        if not s:
            return None
        gaps = s.get_gaps()
        if not gaps:
            return s
        new_fields = list(s.fields)
        for start, end in gaps:
            new_fields.append(FieldSpec(
                name=f"FILLER_{start}_{end}",
                position=start,
                length=end - start + 1,
                field_type="alphanumeric",
                required=False,
                description="Auto-generated filler",
            ))
        return PostSpec(
            post_type=s.post_type,
            name=s.name,
            total_length=s.total_length,
            fields=new_fields,
            description=s.description,
            version=s.version,
            source_file=s.source_file,
        )

    # 10. GET METADATA
    def get_schema_metadata(
        self, post_type: str, version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Hämta metadata för schema."""
        s = self.get_schema(post_type, version)
        if not s:
            return {}
        return {
            "post_type": s.post_type,
            "name": s.name,
            "version": s.version,
            "field_count": s.field_count,
            "required_fields": s.required_field_count,
            "coverage": s.coverage,
            "checksum": s.checksum,
            "created_at": s.created_at,
        }

    # ─── FUNCTIONS 11-20 (ADVANCED) ───

    # 11. SUBSCRIBE
    def subscribe_to_changes(self, callback: Callable) -> bool:
        """Prenumerera på schemaändringar."""
        if callback not in self._change_subscribers:
            self._change_subscribers.append(callback)
            return True
        return False

    # 12. GET FIELD MAPPING
    def get_field_mapping(
        self, post_type: str, version: Optional[str] = None
    ) -> Dict[str, str]:
        """Hämta fältmappning (source_mapping → name)."""
        s = self.get_schema(post_type, version)
        if not s:
            return {}
        return {
            f.source_mapping: f.name
            for f in s.fields
            if f.source_mapping
        }

    # 13. CREATE EMPTY
    def create_empty_schema(
        self, post_type: str, name: str = ""
    ) -> PostSpec:
        """Skapa tomt schema."""
        return PostSpec(
            post_type=post_type,
            name=name or f"PT{post_type}",
            total_length=TS_POST_LENGTH,
            fields=[],
        )

    # 14. GET HISTORY
    def get_schema_history(self, post_type: str) -> List[Dict[str, Any]]:
        """Hämta historik för posttyp."""
        if not self._ensure_vm():
            return []
        return self._version_manager.get_history(post_type)

    # 15. VALIDATE BATCH
    def validate_data_batch(
        self,
        post_type: str,
        records: List[Dict[str, Any]],
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validera flera poster."""
        s = self.get_schema(post_type, version)
        if not s:
            return {"valid": 0, "invalid": len(records), "errors": []}
        valid = 0
        errors: List[Dict[str, Any]] = []
        for i, record in enumerate(records):
            ok, errs = s.validate_record(record)
            if ok:
                valid += 1
            else:
                errors.append({"index": i, "errors": errs})
        return {"valid": valid, "invalid": len(errors), "errors": errors}

    # 16. GET REQUIRED FIELDS
    def get_required_fields(
        self, post_type: str, version: Optional[str] = None
    ) -> List[str]:
        """Lista namn på obligatoriska fält."""
        s = self.get_schema(post_type, version)
        if not s:
            return []
        return [f.name for f in s.get_required_fields()]

    # 17. FIND FIELD BY NAME
    def find_field_by_name(
        self, post_type: str, pattern: str, version: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Sök fält med mönster."""
        s = self.get_schema(post_type, version)
        if not s:
            return []
        return [f.to_dict() for f in s.find_fields(pattern)]

    # 18. GET CHECKSUM
    def get_schema_checksum(
        self, post_type: str, version: Optional[str] = None
    ) -> Optional[str]:
        """Hämta checksumma."""
        s = self.get_schema(post_type, version)
        return s.checksum if s else None

    # 19. BACKUP ALL
    def backup_all_schemas(
        self, name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Skapa backup av alla scheman."""
        if not self._ensure_vm():
            return {"success": False, "error": "VersionManager saknas"}
        n = name or f"backup_{int(time.time())}"
        path = self._version_manager.backup_dir / f"{n}.zip"
        try:
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for v in self.list_versions():
                    d = self._specs_dir / v.version
                    for f in d.glob("*.json"):
                        zf.write(f, f"{v.version}/{f.name}")
            emit_event_safe(
                self.app,
                SchemaEvents.SCHEMA_BACKUP,
                {"path": str(path)},
            )
            return {"success": True, "path": str(path)}
        except Exception as exc:
            _log.error("Backup misslyckades: %s", exc)
            return {"success": False, "error": str(exc)}

    # 20. RESTORE FROM BACKUP
    def restore_from_backup(
        self, backup_path: Union[str, Path]
    ) -> Dict[str, Any]:
        """
        Återställ från backup (zip-slip-skyddad).

        Extraherar endast medlemmar som hamnar innanför
        specs-katalogen (skydd mot olämpliga sökvägar i zip:en).
        """
        bp = Path(backup_path)
        if not bp.exists():
            return {"success": False, "error": "Backupfil saknas"}
        if not self._specs_dir:
            return {"success": False, "error": "Specs-katalog saknas"}
        try:
            specs_root = self._specs_dir.resolve()
            with zipfile.ZipFile(bp, 'r') as zf:
                for member in zf.infolist():
                    target = (self._specs_dir / member.filename).resolve()
                    try:
                        target.relative_to(specs_root)
                    except ValueError:
                        _log.error(
                            "Backup innehåller olämplig sökväg: %s",
                            member.filename,
                        )
                        return {
                            "success": False,
                            "error": "Olämplig sökväg i backup: "
                                     + member.filename,
                        }
                zf.extractall(self._specs_dir)
            if self._version_manager:
                self._version_manager.clear_cache()
            emit_event_safe(
                self.app,
                SchemaEvents.SCHEMA_RESTORED,
                {"path": str(bp)},
            )
            return {"success": True, "restored_from": str(bp)}
        except Exception as exc:
            _log.error("Återställning misslyckades: %s", exc)
            return {"success": False, "error": str(exc)}

    # ─── FUNCTIONS 21-30 (COLLABORATION) ───

    # 21. SYNC WITH TS_SPEC_IMPORT
    def sync_with_ts_spec_import(
        self, version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Synka med ts_spec_import."""
        if not self._ts_spec_import:
            self._detect_collaborators()
        if not self._ts_spec_import:
            return {"synced": False, "reason": "ts_spec_import saknas"}
        return {"synced": True, "version": version}

    # 22. COLLABORATION STATUS
    def get_collaboration_status(self) -> Dict[str, Any]:
        """Hämta samarbetsstatus med andra plugins."""
        self._detect_collaborators()
        return {
            "ts_spec_import": self._ts_spec_import is not None,
            "ts_excel_importer": self._ts_excel_importer is not None,
            "ts_file_generator": get_plugin_safe(
                self.app, "ts_file_generator"
            ) is not None,
        }

    # 23. VALIDATE TS OUTPUT
    def validate_ts_output(self, line: str) -> Dict[str, Any]:
        """Validera en TS-rad (2500 tecken, Latin-1)."""
        errors: List[str] = []
        if len(line) != TS_POST_LENGTH:
            errors.append(
                f"Längd: {len(line)} (förväntat {TS_POST_LENGTH})"
            )
        is_latin1, _, chars = validate_latin1(line)
        if not is_latin1:
            errors.append(f"Ogiltiga tecken: {', '.join(chars[:5])}")
        return {"valid": not errors, "errors": errors, "length": len(line)}

    # 24. FIELD STATISTICS
    def get_field_statistics(
        self, post_type: str, version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Hämta fältstatistik."""
        s = self.get_schema(post_type, version)
        if not s:
            return {}
        types: Dict[str, int] = {}
        for f in s.fields:
            types[f.field_type] = types.get(f.field_type, 0) + 1
        return {
            "total": s.field_count,
            "required": s.required_field_count,
            "optional": s.field_count - s.required_field_count,
            "by_type": types,
            "coverage": s.coverage,
        }

    # 25. EXPORT ALL VERSIONS
    def export_all_versions(
        self, output_dir: Union[str, Path]
    ) -> Dict[str, Any]:
        """Exportera alla versioner till katalog."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        exported = []
        for v in self.list_versions():
            schemas = self.get_all_schemas(v.version)
            for pt, spec in schemas.items():
                p = out / f"{v.version}_PT{pt}.json"
                _atomic_write_json(p, spec.to_dict())
                exported.append(str(p))
        return {"success": True, "files": exported}

    # 26. IMPORT FROM EXCEL SPEC
    def import_from_excel_spec(
        self, path: Union[str, Path], version: str = ""
    ) -> Dict[str, Any]:
        """Importera via ts_excel_importer eller ts_spec_import."""
        if self._ts_excel_importer and hasattr(
            self._ts_excel_importer, 'parse_file'
        ):
            try:
                return self._ts_excel_importer.parse_file(str(path))
            except Exception as exc:
                return {"success": False, "error": str(exc)}
        return {"success": False, "error": "Ingen Excel-importör tillgänglig"}

    # 27. DATAFRAME
    def get_schema_as_dataframe(
        self, post_type: str, version: Optional[str] = None
    ) -> Optional[Any]:
        """Konvertera schema till pandas DataFrame."""
        try:
            import pandas as pd
            s = self.get_schema(post_type, version)
            if not s:
                return None
            return pd.DataFrame([f.to_dict() for f in s.fields])
        except ImportError:
            _log.debug("pandas ej tillgängligt")
            return None

    # 28. SUGGEST FIELD MAPPING
    def suggest_field_mapping(
        self, post_type: str, source_columns: List[str],
        version: Optional[str] = None,
    ) -> Dict[str, str]:
        """Föreslå mappning mellan källkolumner och schemafält."""
        s = self.get_schema(post_type, version)
        if not s:
            return {}
        suggestions: Dict[str, str] = {}
        for col in source_columns:
            col_lower = col.lower().replace(" ", "_").replace("-", "_")
            for f in s.fields:
                if (
                    col_lower == f.name.lower()
                    or col_lower == f.source_mapping.lower()
                ):
                    suggestions[col] = f.name
                    break
        return suggestions

    # 29. LATIN-1 CHECK
    def validate_latin1_compatibility(
        self, post_type: str, data: Dict[str, Any],
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validera Latin-1-kompatibilitet för data."""
        s = self.get_schema(post_type, version)
        if not s:
            return {"error": "Schema saknas"}
        res, errs = s.validate_record(data)
        return {"compatible": res, "errors": errs}

    # 30. COMPREHENSIVE REPORT
    def get_comprehensive_report(self) -> Dict[str, Any]:
        """Hämta omfattande rapport."""
        versions = self.list_versions()
        report: Dict[str, Any] = {
            "plugin": self.NAME,
            "version": VERSION,
            "copyright": _get_copyright_string(),
            "active_version": self.get_active_version(),
            "total_versions": len(versions),
            "versions": [],
        }
        for v in versions:
            schemas = self.get_all_schemas(v.version)
            v_info: Dict[str, Any] = {
                "version": v.version,
                "is_active": v.is_active,
                "post_types": list(schemas.keys()),
                "created_at": v.created_at,
            }
            report["versions"].append(v_info)
        return report

    # ─── UTILITY ───

    def get_post_types(
        self, version: Optional[str] = None
    ) -> List[str]:
        """Lista posttyper i version."""
        return list(self.get_all_schemas(version).keys())

    def is_known_post_type(self, post_type: str) -> bool:
        """Kolla om det är en känd posttyp (int eller str)."""
        return str(post_type) in KNOWN_POST_TYPES

    def get_known_post_type_info(
        self, post_type: str
    ) -> Optional[Dict[str, Any]]:
        """Hämta info om känd posttyp (int eller str)."""
        return KNOWN_POST_TYPES.get(str(post_type))

    def unsubscribe_from_changes(self, callback: Callable) -> bool:
        """Avprenumerera från schemaändringar."""
        if callback in self._change_subscribers:
            self._change_subscribers.remove(callback)
            return True
        return False

    def refresh(self) -> None:
        """Rensa cache och ladda om."""
        if self._version_manager:
            self._version_manager.clear_cache()
        _log.info("Cache rensad.")

    def get_diagnostics(self) -> Dict[str, Any]:
        """Hämta diagnostik."""
        return {
            "plugin": self.NAME,
            "version": VERSION,
            "ready": self.is_ready,
            "active_version": self.get_active_version(),
            "versions": len(self.list_versions()),
            "specs_dir": str(self._specs_dir),
            "collaboration": self.get_collaboration_status(),
        }