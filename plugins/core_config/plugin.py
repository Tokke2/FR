# -*- coding: utf-8 -*-
# Fil: plugins/core_config/plugin.py
"""
Core Config Plugin v4.0.0

Centraliserad konfigurationshantering.

Copyright © 2026 Rickard Längkvist
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Final,
    List,
    Optional,
    Protocol,
    Set,
    Tuple,
    TypedDict,
    Union,
    TYPE_CHECKING,
)

from core.plugin_base import PluginBase

if TYPE_CHECKING:
    from core.application import Application as App

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# EXCEPTIONS
# ══════════════════════════════════════════════════════════════════════════════

class CoreConfigError(Exception):
    """Basfel för Core Config."""
    pass


class ValidationError(CoreConfigError):
    """Valideringsfel."""
    pass


class FileOperationError(CoreConfigError):
    """Fil-operationsfel."""
    pass


class BackupError(CoreConfigError):
    """Backup-fel."""
    pass


# ══════════════════════════════════════════════════════════════════════════════
# KONSTANTER
# ══════════════════════════════════════════════════════════════════════════════

class ConfigFiles(str, Enum):
    """Konfigurationsfilnamn."""
    ATERFORSALJARE = "aterforsaljare.json"
    FARGER = "farger.json"
    CONFIG = "config.json"
    MATCHNING = "matchning_config.json"
    VIN_REGISTRY = "registrerade_vin.json"
    LOSENORD = "losenord.json"
    IDENTITET = "identitet_config.json"
    BUNTPOST = "buntpost_config.json"
    SETTINGS = "settings.json"
    FILE_ID = "file_id_config.json"


class ConfigEvent(str, Enum):
    """Event-namn för config-systemet."""
    RELOAD = "config:reload"
    BACKUP_ALL = "config:backup_all"
    CLEANUP_BACKUPS = "config:cleanup_backups"
    SETTINGS_CHANGED = "settings:changed"
    PIN_CHANGED = "settings:pin_changed"
    FILE_ID_UPDATED = "file_id:updated"
    FILE_ID_PREFIX_CHANGED = "file_id:prefix_changed"
    FILE_ID_SERIES_RESET = "file_id:series_reset"
    FILE_ID_INCREMENTED = "file_id:incremented"
    APP_CLOSING = "app:closing"


# Unika nycklar för merge
DEFAULT_UNIQUE_KEYS: Final[List[str]] = [
    "id", "dn", "kod", "namn", "vin", "VIN", "VINCODE"
]

# Backup-inställningar
DEFAULT_BACKUP_MAX_AGE_DAYS: Final[int] = 30
DEFAULT_BACKUP_MAX_COUNT: Final[int] = 100
BACKUP_DIR_NAME: Final[str] = "backup"

# Validering
MIN_PIN_LENGTH: Final[int] = 4
VALID_ORG_NR_LENGTHS: Final[Tuple[int, ...]] = (10, 12)
EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)

# JSON Preamble
JSON_PREAMBLE_TEMPLATE: Final[str] = """// Auto-genererad fil
// Ändra inte manuellt
// Fil: {filename}
// Genererad: {timestamp}

"""

# Default config
DEFAULT_CONFIG: Final[Dict[str, Any]] = {
    "app_name": "TADEGA Fordonsregistrering",
    "app_version": "3.1.0",
    "app_author": "TADEGA AB",
    "base_dir": ".",
    "data_dir": "data",
    "vehicles_dir": "data/vehicles",
    "dispatch_dir": "dispatch",
    "ut_dir": "ut",
    "logs_dir": "logs",
    "js_data_dir": ".js data",
    "window_width": 1400,
    "window_height": 900,
    "sidebar_width": 220,
    "defaults": {
        "pin": "1234",
        "sender_org": "556677-8899",
        "responsible": "Admin",
        "company_name": "TADEGA AB",
        "color_code": "0",
        "file_id_prefix": "BLN",
    },
    "vehicle_data": {
        "pin": None,
        "auto_lock_minutes": 10,
        "autosave_delay_ms": 700,
        "default_years": [2024, 2025],
    },
    "features": {
        "auto_load_dispatch": True,
        "auto_load_delay_ms": 500,
        "skip_registered_vins": True,
        "validate_before_generate": True,
        "auto_backup": True,
        "backup_max_age_days": 30,
        "backup_max_count": 50,
    },
    "database": {
        "type": "sqlite",
        "filename": "tadega_fordon.db",
        "backup_on_close": True,
    },
    "logging": {
        "level": "INFO",
        "log_to_file": True,
        "log_to_console": True,
        "max_log_size_mb": 10,
        "max_log_files": 5,
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# TYPE DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════

class DealerDict(TypedDict, total=False):
    """Återförsäljardata."""
    dn: str
    namn: str
    t6: str
    orgnr: str


class ColorDict(TypedDict):
    """Färgdata."""
    kod: str
    namn: str


class FileIdInfo(TypedDict):
    """FilID-information."""
    prefix: str
    current_number: int
    next_id: str
    format: str
    history_count: int


class BackupInfo(TypedDict):
    """Backup-statistik."""
    count: int
    total_size_bytes: int
    total_size_mb: float
    oldest: Optional[str]
    newest: Optional[str]
    path: str


class ValidationResult(TypedDict):
    """Valideringsresultat."""
    valid: bool
    errors: List[str]


class DiagnosticsResult(TypedDict):
    """Diagnostikresultat."""
    timestamp: str
    plugin_version: str
    paths: Dict[str, str]
    files: Dict[str, Any]
    backup_info: BackupInfo
    errors: List[str]
    warnings: List[str]


class DiffChange(TypedDict):
    """Diff-ändring."""
    path: str
    type: str
    old: Any
    new: Any


# ══════════════════════════════════════════════════════════════════════════════
# PROTOCOLS
# ══════════════════════════════════════════════════════════════════════════════

class EventBusProtocol(Protocol):
    """Protocol för event bus."""
    def on(self, event: str, callback: Callable[..., Any]) -> None: ...
    def off(self, event: str) -> None: ...
    def emit(self, event: str, data: Optional[Dict[str, Any]] = None) -> None: ...


# ══════════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FileInfo:
    """Information om en fil."""
    exists: bool
    path: str
    size_bytes: int = 0
    modified: Optional[str] = None
    created: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "exists": self.exists,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "modified": self.modified,
            "created": self.created,
        }


@dataclass
class SettingsDefaults:
    """Default-värden för settings."""
    pin: str = "1234"
    sender_org: str = "556677-8899"
    responsible: str = "Admin"
    company_name: str = "TADEGA AB"
    color_code: str = "0"


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATORS
# ══════════════════════════════════════════════════════════════════════════════

def validate_json_structure(
    data: Any,
    expected_type: type,
    required_keys: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    Validerar JSON-datastruktur.

    Args:
        data: Data att validera
        expected_type: Förväntad typ
        required_keys: Obligatoriska nycklar (för dict)

    Returns:
        (is_valid, error_message)
    """
    if not isinstance(data, expected_type):
        return False, f"Förväntade {expected_type.__name__}, fick {type(data).__name__}"

    if required_keys and isinstance(data, dict):
        missing = [k for k in required_keys if k not in data]
        if missing:
            return False, f"Saknar obligatoriska nycklar: {', '.join(missing)}"

    return True, ""


def validate_aterforsaljare(data: Any) -> ValidationResult:
    """Validerar återförsäljardata."""
    errors: List[str] = []

    if not isinstance(data, list):
        return {"valid": False, "errors": ["Data måste vara en lista"]}

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"Post {i}: Måste vara ett objekt")
            continue

        dn = item.get("dn")
        if not dn or not str(dn).strip():
            errors.append(f"Post {i}: Saknar eller tomt 'dn' (återförsäljarnummer)")

        namn = item.get("namn")
        if not namn or not str(namn).strip():
            errors.append(f"Post {i}: Saknar eller tomt 'namn'")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_farger(data: Any) -> ValidationResult:
    """Validerar färgdata."""
    errors: List[str] = []

    if not isinstance(data, list):
        return {"valid": False, "errors": ["Data måste vara en lista"]}

    seen_codes: Dict[str, int] = {}
    seen_names: Dict[str, int] = {}

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"Post {i}: Måste vara ett objekt")
            continue

        kod = item.get("kod")
        namn = item.get("namn")

        if not kod:
            errors.append(f"Post {i}: Saknar 'kod' (färgkod)")
        else:
            kod_str = str(kod).strip()
            if kod_str in seen_codes:
                errors.append(
                    f"Post {i}: Duplicerad kod '{kod_str}' (först på post {seen_codes[kod_str]})"
                )
            else:
                seen_codes[kod_str] = i

        if not namn:
            errors.append(f"Post {i}: Saknar 'namn' (färgnamn)")
        else:
            namn_str = str(namn).strip()
            if namn_str in seen_names:
                errors.append(
                    f"Post {i}: Duplicerat namn '{namn_str}' (först på post {seen_names[namn_str]})"
                )
            else:
                seen_names[namn_str] = i

    return {"valid": len(errors) == 0, "errors": errors}


def validate_vin_registry(data: Any) -> ValidationResult:
    """Validerar VIN-register."""
    errors: List[str] = []

    if not isinstance(data, dict):
        return {"valid": False, "errors": ["Data måste vara ett objekt"]}

    registered = data.get("registered_vins", data.get("registered"))

    if registered is None:
        errors.append("Saknar 'registered' eller 'registered_vins'")
    elif isinstance(registered, dict):
        for year, months in registered.items():
            if year.startswith("_"):
                continue
            if not isinstance(months, dict):
                errors.append(f"År {year}: Måste vara ett objekt med månader")
    elif isinstance(registered, list):
        for i, vin in enumerate(registered):
            if not isinstance(vin, str):
                errors.append(f"VIN {i}: Måste vara en sträng")
            elif len(vin) < 10:
                errors.append(f"VIN {i}: För kort ({len(vin)} tecken)")
    else:
        errors.append("'registered' måste vara en lista eller objekt")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_config(data: Any) -> ValidationResult:
    """Validerar allmän config."""
    errors: List[str] = []

    if not isinstance(data, dict):
        return {"valid": False, "errors": ["Config måste vara ett objekt"]}

    if "version" in data:
        version = data["version"]
        if not isinstance(version, (str, int, float)):
            errors.append("'version' måste vara en sträng eller nummer")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_matchning_config(data: Any) -> ValidationResult:
    """Validerar matchningskonfiguration."""
    errors: List[str] = []

    if not isinstance(data, dict):
        return {"valid": False, "errors": ["Matchning config måste vara ett objekt"]}

    if "synonyms" in data:
        synonyms = data["synonyms"]
        if not isinstance(synonyms, dict):
            errors.append("'synonyms' måste vara ett objekt")
        else:
            for key, aliases in synonyms.items():
                if not isinstance(aliases, list):
                    errors.append(f"Synonymer för '{key}' måste vara en lista")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_pin(pin: str) -> bool:
    """Validera PIN-kod (minst 4 tecken)."""
    return bool(pin and len(str(pin).strip()) >= MIN_PIN_LENGTH)


def validate_org_nr(org_nr: str) -> bool:
    """Validera organisationsnummer (10 eller 12 siffror)."""
    cleaned = re.sub(r"\D", "", str(org_nr))
    return len(cleaned) in VALID_ORG_NR_LENGTHS


def validate_email(email: str) -> bool:
    """Validera e-postadress."""
    return bool(EMAIL_PATTERN.match(str(email).strip()))


# Validator-mappning
_VALIDATORS: Dict[str, Callable[[Any], ValidationResult]] = {
    ConfigFiles.ATERFORSALJARE.value: validate_aterforsaljare,
    ConfigFiles.FARGER.value: validate_farger,
    ConfigFiles.CONFIG.value: validate_config,
    ConfigFiles.MATCHNING.value: validate_matchning_config,
    ConfigFiles.VIN_REGISTRY.value: validate_vin_registry,
}


# ══════════════════════════════════════════════════════════════════════════════
# MERGE UTILS
# ══════════════════════════════════════════════════════════════════════════════

def merge_json_data(
    existing_data: Any,
    new_data: Any,
    unique_keys: Optional[List[str]] = None,
) -> Any:
    """
    Slår samman två JSON-strukturer intelligent.

    Args:
        existing_data: Befintlig data
        new_data: Ny data att merga
        unique_keys: Nycklar för dubblettidentifiering

    Returns:
        Sammanslagen data
    """
    if unique_keys is None:
        unique_keys = list(DEFAULT_UNIQUE_KEYS)

    if isinstance(existing_data, list) and isinstance(new_data, list):
        return _merge_lists(existing_data, new_data, unique_keys)

    if isinstance(existing_data, dict) and isinstance(new_data, dict):
        return deep_merge_dicts(existing_data, new_data, unique_keys)

    return new_data


def _merge_lists(
    list1: List[Any],
    list2: List[Any],
    unique_keys: List[str],
) -> List[Any]:
    """Slår samman två listor med dubbletthantering."""
    merged: List[Any] = []
    seen: Set[str] = set()
    seen_items: Dict[str, int] = {}

    for item in list1 + list2:
        if isinstance(item, dict):
            unique_key = _get_unique_key(item, unique_keys)

            if unique_key:
                if unique_key in seen:
                    idx = seen_items[unique_key]
                    merged[idx] = {**merged[idx], **item}
                else:
                    seen.add(unique_key)
                    seen_items[unique_key] = len(merged)
                    merged.append(item)
            elif item not in merged:
                merged.append(item)
        elif item not in merged:
            merged.append(item)

    return merged


def _get_unique_key(item: Dict[str, Any], unique_keys: List[str]) -> Optional[str]:
    """Försöker hitta en unik nyckel för ett item."""
    for key in unique_keys:
        if key in item and item[key]:
            return f"{key}:{item[key]}"
    return None


def deep_merge_dicts(
    dict1: Dict[str, Any],
    dict2: Dict[str, Any],
    unique_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Djup merge av två dictionaries."""
    if unique_keys is None:
        unique_keys = list(DEFAULT_UNIQUE_KEYS)

    result = dict(dict1)

    for key, value in dict2.items():
        if key in result:
            existing = result[key]

            if isinstance(existing, dict) and isinstance(value, dict):
                result[key] = deep_merge_dicts(existing, value, unique_keys)
            elif isinstance(existing, list) and isinstance(value, list):
                result[key] = merge_json_data(existing, value, unique_keys)
            else:
                result[key] = value
        else:
            result[key] = value

    return result


def diff_json_data(
    old_data: Any,
    new_data: Any,
    path: str = "",
) -> List[DiffChange]:
    """Jämför två JSON-strukturer och returnerar skillnader."""
    changes: List[DiffChange] = []

    if type(old_data) is not type(new_data):
        changes.append({
            "path": path or "root",
            "type": "type_change",
            "old": type(old_data).__name__,
            "new": type(new_data).__name__,
        })
        return changes

    if isinstance(old_data, dict):
        all_keys = set(old_data.keys()) | set(new_data.keys())

        for key in all_keys:
            new_path = f"{path}.{key}" if path else key

            if key not in old_data:
                changes.append({
                    "path": new_path,
                    "type": "added",
                    "old": None,
                    "new": new_data[key],
                })
            elif key not in new_data:
                changes.append({
                    "path": new_path,
                    "type": "removed",
                    "old": old_data[key],
                    "new": None,
                })
            else:
                changes.extend(diff_json_data(old_data[key], new_data[key], new_path))

    elif isinstance(old_data, list):
        if len(old_data) != len(new_data):
            changes.append({
                "path": path or "root",
                "type": "length_change",
                "old": len(old_data),
                "new": len(new_data),
            })

        for i in range(min(len(old_data), len(new_data))):
            changes.extend(diff_json_data(old_data[i], new_data[i], f"{path}[{i}]"))

    elif old_data != new_data:
        changes.append({
            "path": path or "root",
            "type": "value_change",
            "old": old_data,
            "new": new_data,
        })

    return changes


# ══════════════════════════════════════════════════════════════════════════════
# BACKUP MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class BackupManager:
    """
    Hanterar backups av JSON-filer.

    Features:
    - Automatisk backup med tidsstämpel
    - Rensning av gamla backups
    - Återställning från backup
    - Trådsäker
    """

    __slots__ = ("base_dir", "backup_dir", "_lock")

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.backup_dir = self.base_dir / BACKUP_DIR_NAME
        self._lock = threading.Lock()
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, filepath: Path) -> Optional[Path]:
        """Skapar en backup av en fil."""
        if not filepath.exists():
            return None

        with self._lock:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = f"{filepath.stem}_{timestamp}{filepath.suffix}"
                backup_path = self.backup_dir / backup_filename

                shutil.copy2(filepath, backup_path)
                logger.debug("Backup skapad: %s", backup_path.name)
                return backup_path

            except OSError as e:
                logger.error("Backup misslyckades för %s: %s", filepath.name, e)
                return None

    def list_backups(self, original_filename: Optional[str] = None) -> List[Path]:
        """Listar backups, sorterade efter tid (nyast först)."""
        if not self.backup_dir.exists():
            return []

        all_backups = list(self.backup_dir.glob("*.json"))

        if original_filename:
            stem = Path(original_filename).name
            all_backups = [f for f in all_backups if f.stem.startswith(f"{stem}_")]

        return sorted(all_backups, key=lambda p: p.stat().st_mtime, reverse=True)

    def get_latest_backup(self, original_filename: str) -> Optional[Path]:
        """Returnerar senaste backup för en fil."""
        backups = self.list_backups(original_filename)
        return backups[0] if backups else None

    def restore_backup(
        self,
        backup_path: Path,
        target_path: Path,
        create_current_backup: bool = True,
    ) -> bool:
        """Återställer en backup."""
        if not backup_path.exists():
            logger.error("Backup finns inte: %s", backup_path)
            return False

        with self._lock:
            try:
                if create_current_backup and target_path.exists():
                    self.create_backup(target_path)

                shutil.copy2(backup_path, target_path)
                logger.info("Återställd från: %s", backup_path.name)
                return True

            except OSError as e:
                logger.error("Återställning misslyckades: %s", e)
                return False

    def cleanup(
        self,
        max_age_days: int = DEFAULT_BACKUP_MAX_AGE_DAYS,
        max_count: int = DEFAULT_BACKUP_MAX_COUNT,
    ) -> int:
        """Rensar gamla backups."""
        if not self.backup_dir.exists():
            return 0

        deleted = 0
        now = datetime.now()

        with self._lock:
            try:
                all_backups = sorted(
                    self.backup_dir.glob("*.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )

                for i, filepath in enumerate(all_backups):
                    should_delete = False

                    mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
                    age_days = (now - mtime).days

                    if age_days > max_age_days or i >= max_count:
                        should_delete = True

                    if should_delete:
                        try:
                            filepath.unlink()
                            deleted += 1
                        except OSError as e:
                            logger.warning("Kunde inte radera %s: %s", filepath.name, e)

                if deleted > 0:
                    logger.info("Raderade %d gamla backups", deleted)

            except OSError as e:
                logger.error("Fel vid rensning: %s", e)

        return deleted

    def get_backup_info(self) -> BackupInfo:
        """Returnerar information om backups."""
        if not self.backup_dir.exists():
            return {
                "count": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
                "oldest": None,
                "newest": None,
                "path": str(self.backup_dir),
            }

        backups = list(self.backup_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in backups)

        oldest: Optional[str] = None
        newest: Optional[str] = None

        if backups:
            sorted_backups = sorted(backups, key=lambda p: p.stat().st_mtime)
            oldest = datetime.fromtimestamp(sorted_backups[0].stat().st_mtime).isoformat()
            newest = datetime.fromtimestamp(sorted_backups[-1].stat().st_mtime).isoformat()

        return {
            "count": len(backups),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "oldest": oldest,
            "newest": newest,
            "path": str(self.backup_dir),
        }


# ══════════════════════════════════════════════════════════════════════════════
# JSON FILE HANDLER
# ══════════════════════════════════════════════════════════════════════════════

class JsonFileHandler:
    """
    Hanterar JSON-filer med säkra läs/skriv-operationer.

    Features:
    - Atomiska skrivningar (via temp-fil)
    - Automatisk backup före skrivning
    - Preamble-stöd för genererade filer
    - Trådsäker
    """

    __slots__ = ("base_dir", "_backup_callback", "_lock")

    def __init__(
        self,
        base_dir: Path,
        backup_callback: Optional[Callable[[Path], Optional[Path]]] = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._backup_callback = backup_callback
        self._lock = threading.Lock()

    def get_path(self, filename: str) -> Path:
        """Returnerar verifierad sökväg för en fil."""
        return self.base_dir / filename

    def exists(self, filename: str) -> bool:
        """Kontrollerar om en fil finns."""
        return self.get_path(filename).exists()

    def load(
        self,
        filename: str,
        default: Any = None,
        skip_preamble: bool = True,
    ) -> Any:
        """Läser JSON-fil säkert."""
        filepath = self.get_path(filename)

        if not filepath.exists():
            return default

        try:
            content = filepath.read_text(encoding="utf-8")

            if skip_preamble:
                content = self._strip_preamble(content)

            if not content.strip():
                return default

            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.warning("JSON-fel i %s: %s", filename, e)
            return default
        except OSError as e:
            logger.error("Kunde inte läsa %s: %s", filename, e)
            return default

    def save(
        self,
        filename: str,
        data: Any,
        create_backup: bool = True,
        add_preamble: bool = False,
        indent: int = 2,
    ) -> bool:
        """Sparar data till JSON-fil atomiskt."""
        filepath = self.get_path(filename)

        with self._lock:
            try:
                if create_backup and filepath.exists() and self._backup_callback:
                    self._backup_callback(filepath)

                json_content = json.dumps(
                    data,
                    indent=indent,
                    ensure_ascii=False,
                    default=self._json_serializer,
                )

                if add_preamble:
                    preamble = JSON_PREAMBLE_TEMPLATE.format(
                        filename=filename,
                        timestamp=datetime.now().isoformat(timespec="seconds"),
                    )
                    content = preamble + json_content
                else:
                    content = json_content

                self._atomic_write(filepath, content)
                return True

            except (OSError, TypeError, ValueError) as e:
                logger.error("Kunde inte spara %s: %s", filename, e)
                return False

    def update(
        self,
        filename: str,
        update_func: Callable[[Any], Any],
        default: Any = None,
    ) -> bool:
        """Uppdaterar en fil atomiskt med en funktion."""
        try:
            current = self.load(filename, default)
            updated = update_func(current)
            return self.save(filename, updated)
        except Exception as e:
            logger.error("Kunde inte uppdatera %s: %s", filename, e)
            return False

    def append_to_list(self, filename: str, item: Any) -> bool:
        """Lägger till ett item i en JSON-lista."""

        def append_func(data: Any) -> List[Any]:
            if not isinstance(data, list):
                data = []
            data.append(item)
            return data

        return self.update(filename, append_func, default=[])

    def delete(self, filename: str) -> bool:
        """Raderar en fil."""
        filepath = self.get_path(filename)

        with self._lock:
            try:
                if filepath.exists():
                    if self._backup_callback:
                        self._backup_callback(filepath)
                    filepath.unlink()
                return True
            except OSError as e:
                logger.error("Kunde inte radera %s: %s", filename, e)
                return False

    def list_files(self, pattern: str = "*.json") -> List[Path]:
        """Listar JSON-filer i mappen."""
        return list(self.base_dir.glob(pattern))

    def get_file_info(self, filename: str) -> Optional[FileInfo]:
        """Returnerar information om en fil."""
        filepath = self.get_path(filename)

        if not filepath.exists():
            return None

        try:
            stat = filepath.stat()
            return FileInfo(
                exists=True,
                path=str(filepath),
                size_bytes=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                created=datetime.fromtimestamp(stat.st_ctime).isoformat(),
            )
        except OSError:
            return None

    @staticmethod
    def _strip_preamble(content: str) -> str:
        """Tar bort kommentarsrader från början av innehållet."""
        lines = content.split("\n")

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("//"):
                return "\n".join(lines[i:])

        return ""

    def _atomic_write(self, filepath: Path, content: str) -> None:
        """Skriver atomiskt via temp-fil."""
        fd, temp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=f"{filepath.stem}_",
            dir=filepath.parent,
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)

            Path(temp_path).replace(filepath)

        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _json_serializer(obj: Any) -> Any:
        """Custom serializer för speciella typer."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Path):
            return str(obj)
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIK
# ══════════════════════════════════════════════════════════════════════════════

def run_diagnostics(plugin: Plugin) -> DiagnosticsResult:
    """Kör diagnostik på JSON-konfigurationen."""
    results: DiagnosticsResult = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "plugin_version": plugin.VERSION,
        "paths": {},
        "files": {},
        "backup_info": plugin._backup_manager.get_backup_info() if plugin._backup_manager else {},
        "errors": [],
        "warnings": [],
    }

    results["paths"] = {
        "base_dir": str(plugin._paths.get("base", "")),
        "js_data_dir": str(plugin._paths.get("js_data", "")),
        "backup_dir": str(plugin._backup_manager.backup_dir) if plugin._backup_manager else "",
    }

    critical_files = [
        (ConfigFiles.ATERFORSALJARE.value, "list", ["dn", "namn"]),
        (ConfigFiles.FARGER.value, "list", ["kod", "namn"]),
        (ConfigFiles.CONFIG.value, "dict", []),
        (ConfigFiles.MATCHNING.value, "dict", []),
        (ConfigFiles.VIN_REGISTRY.value, "dict", []),
    ]

    for filename, expected_type, required_keys in critical_files:
        file_info = _check_file(plugin, filename, expected_type, required_keys)
        results["files"][filename] = file_info

        if file_info.get("error"):
            results["errors"].append(f"{filename}: {file_info['error']}")
        elif file_info.get("warning"):
            results["warnings"].append(f"{filename}: {file_info['warning']}")

    return results


def _check_file(
    plugin: Plugin,
    filename: str,
    expected_type: str,
    required_keys: List[str],
) -> Dict[str, Any]:
    """Kontrollerar en enskild fil."""
    info: Dict[str, Any] = {"exists": False, "valid": False, "path": ""}

    try:
        filepath = plugin._file_handler.get_path(filename)
        info["path"] = str(filepath)
        info["exists"] = filepath.exists()

        if not info["exists"]:
            info["warning"] = "Filen finns inte"
            return info

        stat = filepath.stat()
        info["size_bytes"] = stat.st_size
        info["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()

        data = plugin._file_handler.load(filename)

        if data is None:
            info["error"] = "Kunde inte ladda fil"
            return info

        if expected_type == "list":
            if not isinstance(data, list):
                info["error"] = f"Förväntade lista, fick {type(data).__name__}"
                return info
            info["record_count"] = len(data)
        elif expected_type == "dict":
            if not isinstance(data, dict):
                info["error"] = f"Förväntade objekt, fick {type(data).__name__}"
                return info
            info["key_count"] = len(data)

        if required_keys:
            if isinstance(data, dict):
                missing = [k for k in required_keys if k not in data]
                if missing:
                    info["warning"] = f"Saknar nycklar: {', '.join(missing)}"
            elif isinstance(data, list) and data:
                first_item = data[0]
                if isinstance(first_item, dict):
                    missing = [k for k in required_keys if k not in first_item]
                    if missing:
                        info["warning"] = f"Poster saknar nycklar: {', '.join(missing)}"

        info["valid"] = True

    except OSError as e:
        info["error"] = str(e)

    return info


def create_sample_data(plugin: Plugin) -> Dict[str, bool]:
    """Skapar exempeldata för testning."""
    results: Dict[str, bool] = {}

    sample_dealers: List[DealerDict] = [
        {"dn": "1001", "namn": "AB Bilhandel", "t6": "NORD", "orgnr": "5566778899"},
        {"dn": "1002", "namn": "CD Motors", "t6": "SYD", "orgnr": "5566779900"},
        {"dn": "1003", "namn": "EF Bilar", "t6": "ÖST", "orgnr": "5566770011"},
    ]
    results[ConfigFiles.ATERFORSALJARE.value] = plugin.save_dealers(sample_dealers)

    sample_colors: List[ColorDict] = [
        {"kod": "02", "namn": "Blå"},
        {"kod": "16", "namn": "Röd"},
        {"kod": "19", "namn": "Svart"},
        {"kod": "20", "namn": "Vit"},
    ]
    results[ConfigFiles.FARGER.value] = plugin.save_colors(sample_colors)

    sample_config = {
        "version": "1.0",
        "created": datetime.now().isoformat(timespec="seconds"),
        "settings": {"auto_backup": True, "max_log_size_mb": 50},
    }
    results[ConfigFiles.CONFIG.value] = plugin.save_config(sample_config)

    logger.info(
        "Exempeldata skapad: %d/%d filer",
        sum(results.values()),
        len(results),
    )

    return results


# ══════════════════════════════════════════════════════════════════════════════
# HUVUDPLUGIN
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    Core Config Plugin v4.0.0

    Central hantering av JSON-konfigurationsfiler.
    Tillhandahåller säker läsning/skrivning med backup och validering.
    """

    NAME: str = "Core Config"
    VERSION: str = "4.0.0"
    DESCRIPTION: str = "Central JSON-konfigurationshantering"
    AUTHOR: str = "Rickard Längkvist"
    DEPENDENCIES: List[str] = []

    # Defaults
    DEFAULTS: SettingsDefaults = SettingsDefaults()

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self._paths: Dict[str, Path] = {}
        self._file_handler: Optional[JsonFileHandler] = None
        self._backup_manager: Optional[BackupManager] = None
        self._settings_cache: Optional[Dict[str, Any]] = None
        self._file_id_cache: Optional[Dict[str, Any]] = None
        self._event_bus: Optional[EventBusProtocol] = None
        self._lock = threading.RLock()

    # ══════════════════════════════════════════════════════════════════════════
    # PROPERTIES
    # ══════════════════════════════════════════════════════════════════════════

    @property
    def file_handler(self) -> JsonFileHandler:
        """Returnerar file handler."""
        if self._file_handler is None:
            raise RuntimeError("Plugin ej initierad")
        return self._file_handler

    @property
    def backup_manager(self) -> BackupManager:
        """Returnerar backup manager."""
        if self._backup_manager is None:
            raise RuntimeError("Plugin ej initierad")
        return self._backup_manager

    @property
    def js_data_dir(self) -> Path:
        """Returnerar .js data mappen."""
        return self._paths.get("js_data", Path(".js data"))

    # ══════════════════════════════════════════════════════════════════════════
    # LIVSCYKEL
    # ══════════════════════════════════════════════════════════════════════════

    def initialize(self) -> None:
        """Initiera plugin."""
        self._setup_paths()
        self._setup_components()
        self._setup_event_bus()
        self._register_events()
        self._load_settings_cache()
        self._load_file_id_cache()

        logger.info(
            "%s v%s initierad – JSON-mapp: %s",
            self.NAME,
            self.VERSION,
            self.js_data_dir,
        )

    def init(self) -> None:
        self.initialize()

    def activate(self) -> None:
        """Aktivera plugin."""
        self.is_active = True
        self._ensure_directories()

        if self._backup_manager:
            self._backup_manager.cleanup()

    def deactivate(self) -> None:
        """Deaktivera plugin."""
        self._save_settings_cache()
        self._save_file_id_cache()
        self._unregister_events()
        self.is_active = False

    def shutdown(self) -> None:
        self.deactivate()

    def _setup_paths(self) -> None:
        """Konfigurera sökvägar."""
        base_dir = Path(self.app.config.get("base_dir", ".")) if hasattr(self.app, "config") else Path(".")
        js_data_dir = base_dir / self.app.config.get("js_data_dir", ".js data") if hasattr(self.app, "config") else base_dir / ".js data"

        self._paths = {
            "base": base_dir,
            "js_data": js_data_dir,
            "data": base_dir / self.app.config.get("data_dir", "data") if hasattr(self.app, "config") else base_dir / "data",
            "vehicles": base_dir / self.app.config.get("vehicles_dir", "data/vehicles") if hasattr(self.app, "config") else base_dir / "data/vehicles",
            "ut": base_dir / self.app.config.get("ut_dir", "ut") if hasattr(self.app, "config") else base_dir / "ut",
            "logs": base_dir / self.app.config.get("logs_dir", "logs") if hasattr(self.app, "config") else base_dir / "logs",
            "dispatch": base_dir / self.app.config.get("dispatch_dir", "dispatch") if hasattr(self.app, "config") else base_dir / "dispatch",
        }

        self._paths["js_data"].mkdir(parents=True, exist_ok=True)

    def _setup_components(self) -> None:
        """Initiera komponenter."""
        js_data_dir = self._paths["js_data"]
        self._backup_manager = BackupManager(js_data_dir)
        self._file_handler = JsonFileHandler(
            js_data_dir,
            backup_callback=self._backup_manager.create_backup,
        )

    def _setup_event_bus(self) -> None:
        """Cache:a event bus referens."""
        if hasattr(self.app, "event_bus"):
            self._event_bus = self.app.event_bus

    def _ensure_directories(self) -> None:
        """Säkerställ att alla kataloger finns."""
        for name, path in self._paths.items():
            if name != "base":
                path.mkdir(parents=True, exist_ok=True)

    def _register_events(self) -> None:
        """Registrera events."""
        if not self._event_bus:
            return

        self._event_bus.on(ConfigEvent.RELOAD.value, self._on_reload_event)
        self._event_bus.on(ConfigEvent.BACKUP_ALL.value, self._on_backup_all_event)
        self._event_bus.on(ConfigEvent.CLEANUP_BACKUPS.value, self._on_cleanup_event)
        self._event_bus.on(ConfigEvent.SETTINGS_CHANGED.value, self._on_settings_changed)
        self._event_bus.on(ConfigEvent.FILE_ID_UPDATED.value, self._on_file_id_updated)
        self._event_bus.on(ConfigEvent.APP_CLOSING.value, self._on_app_closing)

    def _unregister_events(self) -> None:
        """Avregistrera events."""
        if not self._event_bus:
            return

        for event in [
            ConfigEvent.RELOAD,
            ConfigEvent.BACKUP_ALL,
            ConfigEvent.CLEANUP_BACKUPS,
            ConfigEvent.SETTINGS_CHANGED,
            ConfigEvent.FILE_ID_UPDATED,
            ConfigEvent.APP_CLOSING,
        ]:
            self._event_bus.off(event.value)

    def _emit(self, event: Union[ConfigEvent, str], data: Optional[Dict[str, Any]] = None) -> None:
        """Emit event om event bus finns."""
        if self._event_bus:
            event_name = event.value if isinstance(event, ConfigEvent) else event
            self._event_bus.emit(event_name, data)

    # ══════════════════════════════════════════════════════════════════════════
    # EVENT HANDLERS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_reload_event(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Hantera reload event."""
        filename = data.get("filename") if data else None
        if filename:
            loaded = self.load(filename)
            self._emit(f"config:{filename}:loaded", {"data": loaded})

    def _on_backup_all_event(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Backup alla konfigurationsfiler."""
        self.backup_all()

    def _on_cleanup_event(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Rensa gamla backups."""
        max_age = data.get("max_age_days", DEFAULT_BACKUP_MAX_AGE_DAYS) if data else DEFAULT_BACKUP_MAX_AGE_DAYS
        max_count = data.get("max_count", DEFAULT_BACKUP_MAX_COUNT) if data else DEFAULT_BACKUP_MAX_COUNT
        self._backup_manager.cleanup(max_age, max_count)

    def _on_settings_changed(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Hantera settings change."""
        self._save_settings_cache()

    def _on_file_id_updated(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Hantera FilID update."""
        self._save_file_id_cache()

    def _on_app_closing(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Hantera app-stängning."""
        self._save_settings_cache()
        self._save_file_id_cache()

    # ══════════════════════════════════════════════════════════════════════════
    # SETTINGS MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════

    def _load_settings_cache(self) -> None:
        """Laddar settings från JSON."""
        with self._lock:
            self._settings_cache = self.load(ConfigFiles.SETTINGS.value, {})

            defaults = {
                "pin": self.DEFAULTS.pin,
                "sender_org": self.DEFAULTS.sender_org,
                "responsible": self.DEFAULTS.responsible,
                "company_name": self.DEFAULTS.company_name,
            }

            for key, value in defaults.items():
                if key not in self._settings_cache:
                    self._settings_cache[key] = value

    def _save_settings_cache(self) -> None:
        """Sparar settings till JSON."""
        with self._lock:
            if self._settings_cache is None:
                return

            self._settings_cache["_meta"] = {
                "updated_at": datetime.now().isoformat(),
                "version": self.VERSION,
            }

            self.save(ConfigFiles.SETTINGS.value, self._settings_cache, create_backup=True)

    def get_pin(self) -> str:
        """Hämtar PIN-kod."""
        with self._lock:
            if self._settings_cache is None:
                self._load_settings_cache()
            return self._settings_cache.get("pin", self.DEFAULTS.pin)

    def set_pin(self, new_pin: str) -> bool:
        """Sätter PIN-kod."""
        if not validate_pin(new_pin):
            return False

        with self._lock:
            if self._settings_cache is None:
                self._load_settings_cache()

            self._settings_cache["pin"] = new_pin
            self._save_settings_cache()

        self._emit(ConfigEvent.PIN_CHANGED, {"pin": new_pin})
        return True

    def verify_pin(self, pin: str) -> bool:
        """Verifierar PIN-kod."""
        return pin == self.get_pin()

    def get_sender_org(self) -> str:
        """Hämtar avsändare org.nr."""
        with self._lock:
            if self._settings_cache is None:
                self._load_settings_cache()
            return self._settings_cache.get("sender_org", self.DEFAULTS.sender_org)

    def set_sender_org(self, org: str) -> bool:
        """Sätter avsändare org.nr."""
        with self._lock:
            if self._settings_cache is None:
                self._load_settings_cache()

            self._settings_cache["sender_org"] = org
            self._save_settings_cache()
        return True

    def get_responsible(self) -> str:
        """Hämtar ansvarig person."""
        with self._lock:
            if self._settings_cache is None:
                self._load_settings_cache()
            return self._settings_cache.get("responsible", self.DEFAULTS.responsible)

    def set_responsible(self, person: str) -> bool:
        """Sätter ansvarig person."""
        with self._lock:
            if self._settings_cache is None:
                self._load_settings_cache()

            self._settings_cache["responsible"] = person
            self._save_settings_cache()
        return True

    def get_company_name(self) -> str:
        """Hämtar företagsnamn."""
        with self._lock:
            if self._settings_cache is None:
                self._load_settings_cache()
            return self._settings_cache.get("company_name", self.DEFAULTS.company_name)

    def set_company_name(self, name: str) -> bool:
        """Sätter företagsnamn."""
        with self._lock:
            if self._settings_cache is None:
                self._load_settings_cache()

            self._settings_cache["company_name"] = name
            self._save_settings_cache()
        return True

    # ══════════════════════════════════════════════════════════════════════════
    # FILE ID MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════

    def _load_file_id_cache(self) -> None:
        """Laddar FilID-konfiguration."""
        with self._lock:
            self._file_id_cache = self.load(
                ConfigFiles.FILE_ID.value,
                {
                    "prefix": "BLN",
                    "current_number": 1,
                    "format": "BLN{:04d}",
                    "history": [],
                },
            )

    def _save_file_id_cache(self) -> None:
        """Sparar FilID-konfiguration."""
        with self._lock:
            if self._file_id_cache is None:
                return

            self._file_id_cache["updated_at"] = datetime.now().isoformat()
            self.save(ConfigFiles.FILE_ID.value, self._file_id_cache, create_backup=False)

    def get_file_id_info(self) -> FileIdInfo:
        """Hämtar FilID-information."""
        with self._lock:
            if self._file_id_cache is None:
                self._load_file_id_cache()

            prefix = self._file_id_cache.get("prefix", "BLN")
            current_num = self._file_id_cache.get("current_number", 1)

            return {
                "prefix": prefix,
                "current_number": current_num,
                "next_id": f"{prefix}{current_num:04d}",
                "format": f"{prefix}NNNN",
                "history_count": len(self._file_id_cache.get("history", [])),
            }

    def peek_next_file_id(self) -> str:
        """Visar nästa FilID utan att konsumera."""
        with self._lock:
            if self._file_id_cache is None:
                self._load_file_id_cache()

            prefix = self._file_id_cache.get("prefix", "BLN")
            current_num = self._file_id_cache.get("current_number", 1)
            return f"{prefix}{current_num:04d}"

    def get_next_file_id(self) -> str:
        """Hämtar och konsumerar nästa FilID."""
        return self.increment_file_id()

    def set_file_id_prefix(self, prefix: str) -> bool:
        """Sätter FilID-prefix."""
        with self._lock:
            if self._file_id_cache is None:
                self._load_file_id_cache()

            self._file_id_cache["prefix"] = prefix.upper().strip()[:6]
            self._save_file_id_cache()

        self._emit(ConfigEvent.FILE_ID_PREFIX_CHANGED, {"prefix": prefix})
        return True

    def reset_file_id_series(self, start_number: int = 1) -> bool:
        """Återställer FilID-serien."""
        with self._lock:
            if self._file_id_cache is None:
                self._load_file_id_cache()

            self._file_id_cache["current_number"] = max(1, start_number)
            self._file_id_cache["history"] = []
            self._save_file_id_cache()

        self._emit(ConfigEvent.FILE_ID_SERIES_RESET, {"start_number": start_number})
        return True

    def increment_file_id(self) -> str:
        """Inkrementerar FilID och returnerar nästa ID."""
        with self._lock:
            if self._file_id_cache is None:
                self._load_file_id_cache()

            prefix = self._file_id_cache.get("prefix", "BLN")
            current = self._file_id_cache.get("current_number", 1)

            next_id = f"{prefix}{current:04d}"

            self._file_id_cache["current_number"] = current + 1

            if "history" not in self._file_id_cache:
                self._file_id_cache["history"] = []

            self._file_id_cache["history"].append({
                "file_id": next_id,
                "used_at": datetime.now().isoformat(),
            })

            # Behåll max 100 i historik
            if len(self._file_id_cache["history"]) > 100:
                self._file_id_cache["history"] = self._file_id_cache["history"][-100:]

            self._save_file_id_cache()

        self._emit(
            ConfigEvent.FILE_ID_INCREMENTED,
            {"file_id": next_id, "next_number": current + 1},
        )

        return next_id

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API - GENERELL JSON-HANTERING
    # ══════════════════════════════════════════════════════════════════════════

    def load(self, filename: str, default: Any = None) -> Any:
        """Läser en JSON-fil."""
        return self._file_handler.load(filename, default)

    def save(
        self,
        filename: str,
        data: Any,
        create_backup: bool = True,
        add_preamble: bool = False,
    ) -> bool:
        """Sparar data till JSON-fil."""
        success = self._file_handler.save(filename, data, create_backup, add_preamble)

        if success:
            self._emit(
                f"config:{filename}:saved",
                {"filename": filename, "timestamp": datetime.now().isoformat()},
            )

        return success

    def update(
        self,
        filename: str,
        update_func: Callable[[Any], Any],
        default: Any = None,
    ) -> bool:
        """Uppdaterar en fil atomiskt."""
        return self._file_handler.update(filename, update_func, default)

    def exists(self, filename: str) -> bool:
        """Kontrollerar om en fil finns."""
        return self._file_handler.exists(filename)

    def get_path(self, filename: str) -> Path:
        """Returnerar full sökväg för en fil."""
        return self._file_handler.get_path(filename)

    def merge(
        self,
        filename: str,
        new_data: Any,
        unique_keys: Optional[List[str]] = None,
    ) -> bool:
        """Slår samman ny data med befintlig fil."""

        def merge_func(existing: Any) -> Any:
            return merge_json_data(existing, new_data, unique_keys)

        return self.update(filename, merge_func, default=new_data)

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API - ÅTERFÖRSÄLJARE
    # ══════════════════════════════════════════════════════════════════════════

    def load_dealers(self) -> List[Dict[str, Any]]:
        """Läser återförsäljare från JSON."""
        data = self.load(ConfigFiles.ATERFORSALJARE.value, [])
        return data if isinstance(data, list) else []

    def save_dealers(self, dealers: List[Dict[str, Any]]) -> bool:
        """Sparar återförsäljare till JSON."""
        result = validate_aterforsaljare(dealers)
        if not result["valid"]:
            logger.warning("Valideringsfel: %s", result["errors"])

        return self.save(ConfigFiles.ATERFORSALJARE.value, dealers, add_preamble=True)

    def add_dealer(self, dealer: Dict[str, Any]) -> bool:
        """Lägger till en återförsäljare."""
        return self._file_handler.append_to_list(ConfigFiles.ATERFORSALJARE.value, dealer)

    # Alias för bakåtkompatibilitet
    las_aterforsaljare_fran_json = load_dealers
    spara_aterforsaljare_till_json = save_dealers

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API - FÄRGER
    # ══════════════════════════════════════════════════════════════════════════

    def load_colors(self) -> List[Dict[str, Any]]:
        """Läser färger från JSON."""
        data = self.load(ConfigFiles.FARGER.value, [])
        return data if isinstance(data, list) else []

    def save_colors(self, colors: List[Dict[str, Any]]) -> bool:
        """Sparar färger till JSON."""
        result = validate_farger(colors)
        if not result["valid"]:
            logger.warning("Valideringsfel: %s", result["errors"])

        return self.save(ConfigFiles.FARGER.value, colors, add_preamble=True)

    def add_color(self, color: Dict[str, Any]) -> bool:
        """Lägger till en färg."""
        return self._file_handler.append_to_list(ConfigFiles.FARGER.value, color)

    # Alias
    las_farger_fran_json = load_colors
    spara_farger_till_json = save_colors

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API - CONFIG
    # ══════════════════════════════════════════════════════════════════════════

    def load_config(self) -> Dict[str, Any]:
        """Läser allmän konfiguration."""
        data = self.load(ConfigFiles.CONFIG.value, {})
        return data if isinstance(data, dict) else {}

    def save_config(self, config: Dict[str, Any]) -> bool:
        """Sparar allmän konfiguration."""
        config["last_updated"] = datetime.now().isoformat(timespec="seconds")
        return self.save(ConfigFiles.CONFIG.value, config)

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Hämtar ett konfigurationsvärde med dot-notation."""
        config = self.load_config()

        if "." in key:
            keys = key.split(".")
            value = config
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
            return value

        return config.get(key, default)

    def set_config_value(self, key: str, value: Any) -> bool:
        """Sätter ett konfigurationsvärde med dot-notation."""

        def update_func(config: Dict[str, Any]) -> Dict[str, Any]:
            if "." in key:
                keys = key.split(".")
                current = config
                for k in keys[:-1]:
                    if k not in current:
                        current[k] = {}
                    current = current[k]
                current[keys[-1]] = value
            else:
                config[key] = value
            return config

        return self.update(ConfigFiles.CONFIG.value, update_func, default={})

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API - MATCHNING CONFIG
    # ══════════════════════════════════════════════════════════════════════════

    def load_matchning_config(self) -> Dict[str, Any]:
        """Läser matchningskonfiguration."""
        data = self.load(ConfigFiles.MATCHNING.value, {})
        return data if isinstance(data, dict) else {}

    def save_matchning_config(self, config: Dict[str, Any]) -> bool:
        """Sparar matchningskonfiguration."""
        return self.save(ConfigFiles.MATCHNING.value, config)

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API - VIN-REGISTER
    # ══════════════════════════════════════════════════════════════════════════

    def load_vin_registry(self) -> Dict[str, Any]:
        """Läser VIN-register."""
        default: Dict[str, Any] = {"registered_vins": {}, "last_updated": None}
        data = self.load(ConfigFiles.VIN_REGISTRY.value, default)
        return data if isinstance(data, dict) else default

    def save_vin_registry(self, registry: Dict[str, Any]) -> bool:
        """Sparar VIN-register."""
        registry["last_updated"] = datetime.now().isoformat()
        return self.save(ConfigFiles.VIN_REGISTRY.value, registry)

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API - BACKUP
    # ══════════════════════════════════════════════════════════════════════════

    def create_backup(self, filename: str) -> Optional[Path]:
        """Skapar backup av en fil."""
        filepath = self._file_handler.get_path(filename)
        return self._backup_manager.create_backup(filepath)

    def backup_all(self) -> Dict[str, Optional[Path]]:
        """Skapar backup av alla konfigurationsfiler."""
        files_to_backup = [
            ConfigFiles.ATERFORSALJARE.value,
            ConfigFiles.FARGER.value,
            ConfigFiles.CONFIG.value,
            ConfigFiles.MATCHNING.value,
            ConfigFiles.VIN_REGISTRY.value,
            ConfigFiles.SETTINGS.value,
            ConfigFiles.FILE_ID.value,
        ]

        results: Dict[str, Optional[Path]] = {}

        for filename in files_to_backup:
            if self.exists(filename):
                results[filename] = self.create_backup(filename)
            else:
                results[filename] = None

        return results

    def list_backups(self, filename: Optional[str] = None) -> List[Path]:
        """Listar backups."""
        return self._backup_manager.list_backups(filename)

    def restore_backup(self, backup_path: Path, target_filename: str) -> bool:
        """Återställer en backup."""
        target_path = self._file_handler.get_path(target_filename)
        return self._backup_manager.restore_backup(backup_path, target_path)

    def cleanup_backups(
        self,
        max_age_days: int = DEFAULT_BACKUP_MAX_AGE_DAYS,
        max_count: int = DEFAULT_BACKUP_MAX_COUNT,
    ) -> int:
        """Rensar gamla backups."""
        return self._backup_manager.cleanup(max_age_days, max_count)

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API - VALIDERING
    # ══════════════════════════════════════════════════════════════════════════

    def validate_file(self, filename: str) -> ValidationResult:
        """Validerar en konfigurationsfil."""
        data = self.load(filename)

        validator = _VALIDATORS.get(filename)
        if validator:
            return validator(data)

        is_valid, error = validate_json_structure(data, dict)
        return {"valid": is_valid, "errors": [error] if error else []}

    def validate_all(self) -> Dict[str, ValidationResult]:
        """Validerar alla konfigurationsfiler."""
        results: Dict[str, ValidationResult] = {}

        for config_file in [
            ConfigFiles.ATERFORSALJARE,
            ConfigFiles.FARGER,
            ConfigFiles.CONFIG,
            ConfigFiles.MATCHNING,
        ]:
            filename = config_file.value
            if self.exists(filename):
                results[filename] = self.validate_file(filename)

        return results

    def validate_org_nr(self, org_nr: str) -> bool:
        """Validera organisationsnummer."""
        return validate_org_nr(org_nr)

    def validate_email(self, email: str) -> bool:
        """Validera e-postadress."""
        return validate_email(email)

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API - MERGE & DIFF
    # ══════════════════════════════════════════════════════════════════════════

    def merge_data(
        self,
        existing: Any,
        new: Any,
        unique_keys: Optional[List[str]] = None,
    ) -> Any:
        """Slår samman två datastrukturer."""
        return merge_json_data(existing, new, unique_keys)

    def diff_data(self, old: Any, new: Any) -> List[DiffChange]:
        """Jämför två datastrukturer."""
        return diff_json_data(old, new)

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API - DIAGNOSTIK
    # ══════════════════════════════════════════════════════════════════════════

    def run_diagnostics(self) -> DiagnosticsResult:
        """Kör diagnostik."""
        return run_diagnostics(self)

    def create_sample_data(self) -> Dict[str, bool]:
        """Skapar exempeldata för testning."""
        return create_sample_data(self)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Exceptions
    "CoreConfigError",
    "ValidationError",
    "FileOperationError",
    "BackupError",
    # Enums
    "ConfigFiles",
    "ConfigEvent",
    # Types
    "DealerDict",
    "ColorDict",
    "FileIdInfo",
    "BackupInfo",
    "ValidationResult",
    "DiagnosticsResult",
    "DiffChange",
    # Classes
    "BackupManager",
    "JsonFileHandler",
    "FileInfo",
    "SettingsDefaults",
    "Plugin",
    # Functions
    "validate_json_structure",
    "validate_aterforsaljare",
    "validate_farger",
    "validate_vin_registry",
    "validate_config",
    "validate_matchning_config",
    "validate_pin",
    "validate_org_nr",
    "validate_email",
    "merge_json_data",
    "deep_merge_dicts",
    "diff_json_data",
    "run_diagnostics",
    "create_sample_data",
    # Constants
    "DEFAULT_UNIQUE_KEYS",
    "DEFAULT_BACKUP_MAX_AGE_DAYS",
    "DEFAULT_BACKUP_MAX_COUNT",
    "DEFAULT_CONFIG",
]
