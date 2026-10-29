# -*- coding: utf-8 -*-
# core/config.py
"""
Konfigurationshantering med validering och typad access v1.1.0.

Features:
    - JSON-baserad konfiguration med kommentarsstöd
    - Dot-notation for nested access
    - Default values med type coercion
    - Schema-validering med detaljerade felmeddelanden
    - Environment variable override
    - Type-safe getters
    - Config reload med file watching
    - Plugin-specifik konfiguration
    - Environment-specifik config (dev/prod/test)
    - Obfuskerade secrets (XOR — EJ kryptografiskt stark,
      skydda nyckeln via CONFIG_ENCRYPTION_KEY)
    - Config change events via EventBus
    - Atomisk skrivning vid save (mkstemp -> fsync -> os.replace)

Användning:
    from core.config import Configuration, get_config

    # Ladda config
    config = Configuration.load("config.json")

    # Hämta värden med dot-notation
    db_url = config.get("database.url", default="sqlite:///default.db")
    port = config.get_int("server.port", default=8080)

    # Nested access
    sap_config = config.section("plugins.sap_import")
    batch_size = sap_config.get_int("batch_size", default=100)

    # Plugin-konfiguration
    plugin_config = config.plugin_config("sap_import")

    # Environment override
    # CONFIG_DATABASE_URL=postgres://... overrides database.url

    # Validera
    errors = config.validate_schema(CoreConfigSchema)

FÖRÄNDRINGAR v1.1.0:
    - logger -> _log (spec-konvention) + f-string -> lazy %s
    - save() ATOMISK: tempfile.mkstemp -> os.fdopen -> fsync ->
      os.replace (var icke-atomisk write_text — spec-brott)
    - Döda importer borttagna (ABC, abstractmethod, Set, Generic,
      overload, Mapping, lru_cache, ValidationError)
    - VERSION/AUTHOR + dynamisk copyright
    - CoreConfigSchema app.name-default ->
      "Transportstyrelsen Fordonsregistreringssystem"
    - SecretsHandler-docstring förtydligad (obfuskering, ej krypto)

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    Any, Callable, Dict, Iterator, List, Optional,
    Tuple, Type, TypeVar, TYPE_CHECKING,
)

from core.exceptions import (
    ConfigError,
    ConfigNotFoundError,
    ConfigValidationError,
    ConfigParseError,
)

if TYPE_CHECKING:
    from core.event_bus import EventBus

_log = logging.getLogger(__name__)

T = TypeVar('T')


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS & VERSION
# ══════════════════════════════════════════════════════════════════════════════

VERSION = "1.1.0"
AUTHOR = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════════════════════

class Environment(Enum):
    """Miljötyper för konfiguration."""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"

    @classmethod
    def from_string(cls, value: str) -> Environment:
        """Parse environment från string."""
        value = value.lower().strip()
        mapping = {
            "dev": cls.DEVELOPMENT,
            "development": cls.DEVELOPMENT,
            "test": cls.TESTING,
            "testing": cls.TESTING,
            "stage": cls.STAGING,
            "staging": cls.STAGING,
            "prod": cls.PRODUCTION,
            "production": cls.PRODUCTION,
        }
        return mapping.get(value, cls.DEVELOPMENT)


class ConfigChangeType(Enum):
    """Typ av konfigurationsändring."""
    SET = "set"
    DELETE = "delete"
    RELOAD = "reload"
    MERGE = "merge"


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG CHANGE EVENT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ConfigChange:
    """Representerar en konfigurationsändring."""
    change_type: ConfigChangeType
    key: str
    old_value: Any = None
    new_value: Any = None
    timestamp: float = field(default_factory=time.time)
    source: str = ""  # "file", "env", "code"

    def __str__(self) -> str:
        return f"ConfigChange({self.change_type.value}: {self.key})"


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ConfigField:
    """
    Schema-definition för ett config-fält.

    Exempel:
        ConfigField(
            type=int,
            required=True,
            default=8080,
            min_value=1,
            max_value=65535,
            description="Server port"
        )
    """
    type: Type = str
    required: bool = False
    default: Any = None
    description: str = ""

    # Validators
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    choices: Optional[List[Any]] = None
    validator: Optional[Callable[[Any], bool]] = None

    # Metadata
    secret: bool = False  # Ska krypteras/maskeras
    deprecated: bool = False
    deprecated_message: str = ""
    env_var: Optional[str] = None  # Specifik env var att använda

    def validate(self, value: Any, key: str) -> List[str]:
        """
        Validera ett värde mot detta schema.

        Returns:
            Lista med felmeddelanden (tom om valid)
        """
        errors = []

        # Check required
        if value is None:
            if self.required:
                errors.append(f"Required field missing: {key}")
            return errors

        # Check deprecated
        if self.deprecated:
            _log.warning(
                "Config field '%s' is deprecated. %s",
                key, self.deprecated_message,
            )

        # Type check
        if not isinstance(value, self.type):
            try:
                # Försök konvertera
                value = self.type(value)
            except (ValueError, TypeError):
                errors.append(
                    f"Invalid type for '{key}': "
                    f"expected {self.type.__name__}, "
                    f"got {type(value).__name__}"
                )
                return errors

        # Range validation (numbers)
        if self.min_value is not None and value < self.min_value:
            errors.append(
                f"Value for '{key}' is too small: "
                f"{value} < {self.min_value}"
            )

        if self.max_value is not None and value > self.max_value:
            errors.append(
                f"Value for '{key}' is too large: "
                f"{value} > {self.max_value}"
            )

        # Length validation (strings, lists)
        if hasattr(value, '__len__'):
            if (
                self.min_length is not None
                and len(value) < self.min_length
            ):
                errors.append(
                    f"Value for '{key}' is too short: "
                    f"length {len(value)} < {self.min_length}"
                )

            if (
                self.max_length is not None
                and len(value) > self.max_length
            ):
                errors.append(
                    f"Value for '{key}' is too long: "
                    f"length {len(value)} > {self.max_length}"
                )

        # Pattern validation
        if self.pattern and isinstance(value, str):
            if not re.match(self.pattern, value):
                errors.append(
                    f"Value for '{key}' doesn't match pattern: "
                    f"{self.pattern}"
                )

        # Choices validation
        if self.choices is not None and value not in self.choices:
            errors.append(
                f"Invalid choice for '{key}': {value}. "
                f"Valid choices: {self.choices}"
            )

        # Custom validator
        if self.validator:
            try:
                if not self.validator(value):
                    errors.append(
                        f"Custom validation failed for '{key}'"
                    )
            except Exception as e:
                errors.append(f"Validator error for '{key}': {e}")

        return errors


class ConfigSchema:
    """
    Schema för validering av konfiguration.
    """
    schema: Dict[str, ConfigField] = {}

    @classmethod
    def validate(cls, config: Configuration) -> List[str]:
        """Validera en Configuration mot detta schema."""
        errors = []

        for key, field_schema in cls.schema.items():
            value = config.get(key)
            field_errors = field_schema.validate(value, key)
            errors.extend(field_errors)

        return errors

    @classmethod
    def get_defaults(cls) -> Dict[str, Any]:
        """Hämta alla default-värden."""
        defaults = {}
        for key, field_schema in cls.schema.items():
            if field_schema.default is not None:
                defaults[key] = field_schema.default
        return defaults


# ══════════════════════════════════════════════════════════════════════════════
# SECRETS HANDLING
# ══════════════════════════════════════════════════════════════════════════════

class SecretsHandler:
    """
    Hantering av obfuskerade secrets i config.

    Secrets markeras med prefix "encrypted:" och obfuskeras med
    XOR mot en nyckel från environment variable.

    OBS: XOR-obfuskering är INTE kryptografiskt stark. Den skyddar
    mot oavsiktlig exponering i config-filer/loggar, men nyckeln
    (CONFIG_ENCRYPTION_KEY) måste hållas hemlig och riktig
    kryptering bör övervägas för känslig data.
    """

    PREFIX = "encrypted:"
    KEY_ENV_VAR = "CONFIG_ENCRYPTION_KEY"

    def __init__(self, key: Optional[bytes] = None):
        """
        Initiera SecretsHandler.

        Args:
            key: Krypteringsnyckel (32 bytes).
                 Om None, försök läsa från env.
        """
        self._key = key or self._get_key_from_env()

    def _get_key_from_env(self) -> Optional[bytes]:
        """Hämta nyckel från environment."""
        key_str = os.environ.get(self.KEY_ENV_VAR)
        if key_str:
            # Hash till 32 bytes
            return hashlib.sha256(key_str.encode()).digest()
        return None

    def encrypt(self, value: str) -> str:
        """
        Obfuskera ett värde.
        """
        if not self._key:
            _log.warning(
                "No encryption key available, storing as plain text"
            )
            return value

        try:
            # XOR-obfuskering
            data = value.encode('utf-8')
            key = self._key
            encrypted = bytes(
                d ^ key[i % len(key)] for i, d in enumerate(data)
            )
            encoded = base64.b64encode(encrypted).decode('ascii')
            return f"{self.PREFIX}{encoded}"
        except Exception as e:
            _log.error("Encryption failed: %s", e)
            return value

    def decrypt(self, value: str) -> str:
        """
        Avobfuskera ett värde.
        """
        if not value.startswith(self.PREFIX):
            return value

        if not self._key:
            _log.error("No encryption key available for decryption")
            return value

        try:
            encoded = value[len(self.PREFIX):]
            encrypted = base64.b64decode(encoded)
            key = self._key
            decrypted = bytes(
                d ^ key[i % len(key)]
                for i, d in enumerate(encrypted)
            )
            return decrypted.decode('utf-8')
        except Exception as e:
            _log.error("Decryption failed: %s", e)
            return value

    def is_encrypted(self, value: Any) -> bool:
        """Kolla om ett värde är obfuskerat."""
        return isinstance(value, str) and value.startswith(self.PREFIX)

    def mask(self, value: str, show_chars: int = 4) -> str:
        """Maska ett secret för logging."""
        if len(value) <= show_chars:
            return "*" * len(value)
        return value[:show_chars] + "*" * (len(value) - show_chars)


# ══════════════════════════════════════════════════════════════════════════════
# FILE WATCHER
# ══════════════════════════════════════════════════════════════════════════════

class ConfigFileWatcher:
    """
    Övervakar config-fil för ändringar och triggar reload.
    """

    def __init__(
        self,
        config: Configuration,
        check_interval: float = 5.0,
        on_change: Optional[Callable[[Configuration], None]] = None
    ):
        self.config = config
        self.check_interval = check_interval
        self.on_change = on_change

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_mtime: Optional[float] = None

        # Initialt mtime
        if config.source_path and config.source_path.exists():
            self._last_mtime = config.source_path.stat().st_mtime

    def start(self):
        """Starta övervakning."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="ConfigFileWatcher"
        )
        self._thread.start()
        _log.info(
            "Started watching config file: %s",
            self.config.source_path,
        )

    def stop(self):
        """Stoppa övervakning."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.check_interval + 1)
            self._thread = None
        _log.info("Stopped config file watcher")

    def _watch_loop(self):
        """Övervakningsloop."""
        while self._running:
            try:
                self._check_for_changes()
            except Exception as e:
                _log.error("Config watcher error: %s", e)

            time.sleep(self.check_interval)

    def _check_for_changes(self):
        """Kolla om filen har ändrats."""
        path = self.config.source_path
        if not path or not path.exists():
            return

        current_mtime = path.stat().st_mtime

        if (
            self._last_mtime is not None
            and current_mtime > self._last_mtime
        ):
            _log.info("Config file changed, reloading: %s", path)

            try:
                self.config.reload()

                if self.on_change:
                    self.on_change(self.config)

            except Exception as e:
                _log.error("Failed to reload config: %s", e)

        self._last_mtime = current_mtime


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Configuration:
    """
    Thread-safe konfigurationshantering.
    """

    ENV_PREFIX = "CONFIG_"
    PLUGIN_CONFIG_KEY = "plugins"
    VERSION_KEY = "_config_version"

    def __init__(
        self,
        data: Optional[Dict[str, Any]] = None,
        *,
        source_path: Optional[Path] = None,
        use_env_override: bool = True,
        strict: bool = False,
        environment: Optional[Environment] = None,
        event_bus: Optional[EventBus] = None,
        secrets_handler: Optional[SecretsHandler] = None
    ):
        """
        Skapa Configuration.
        """
        self._data: Dict[str, Any] = data or {}
        self._source_path = source_path
        self._use_env_override = use_env_override
        self._strict = strict
        self._environment = environment or self._detect_environment()
        self._event_bus = event_bus
        self._secrets = secrets_handler or SecretsHandler()

        # Thread safety
        self._lock = threading.RLock()

        # Caching
        self._cache: Dict[str, Any] = {}

        # Change tracking
        self._change_listeners: List[
            Callable[[ConfigChange], None]
        ] = []

        # File watching
        self._watcher: Optional[ConfigFileWatcher] = None

        # Config version för migration
        self._version = self._data.get(self.VERSION_KEY, 1)

    # ═══════════════════════════════════════════════════════════════════════════
    # FACTORY METHODS
    # ═══════════════════════════════════════════════════════════════════════════

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        encoding: str = "utf-8",
        use_env_override: bool = True,
        strict: bool = False,
        environment: Optional[Environment] = None,
        event_bus: Optional[EventBus] = None
    ) -> Configuration:
        """
        Ladda konfiguration från JSON-fil.
        """
        path = Path(path)

        if not path.exists():
            raise ConfigNotFoundError(
                f"Configuration file not found: {path}",
                config_path=path,
                searched_paths=[path.parent]
            )

        # Ladda bas-config
        data = cls._load_json_file(path, encoding)

        # Detektera environment
        env = environment or cls._detect_environment()

        # Ladda environment-specifik config om den finns
        env_path = (
            path.parent / f"{path.stem}.{env.value}{path.suffix}"
        )
        if env_path.exists():
            env_data = cls._load_json_file(env_path, encoding)
            data = cls._deep_merge(data, env_data)
            _log.info("Loaded environment config: %s", env_path)

        _log.info(
            "Loaded configuration from %s (env: %s)",
            path, env.value,
        )

        return cls(
            data,
            source_path=path,
            use_env_override=use_env_override,
            strict=strict,
            environment=env,
            event_bus=event_bus
        )

    @classmethod
    def _load_json_file(
        cls, path: Path, encoding: str
    ) -> Dict[str, Any]:
        """Ladda och parsa JSON-fil."""
        try:
            content = path.read_text(encoding=encoding)

            # Ta bort kommentarer (// och /* */)
            content = cls._strip_json_comments(content)

            return json.loads(content)

        except json.JSONDecodeError as e:
            raise ConfigParseError(
                f"Invalid JSON in configuration file: {e.msg}",
                config_path=path,
                line=e.lineno,
                column=e.colno,
                original_error=e
            ) from e
        except Exception as e:
            raise ConfigError(
                f"Failed to read configuration: {e}",
                config_path=path
            ) from e

    @staticmethod
    def _strip_json_comments(content: str) -> str:
        """Ta bort kommentarer från JSON (för bekvämlighet)."""
        # Ta bort // kommentarer
        content = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        # Ta bort /* */ kommentarer
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        return content

    @staticmethod
    def _deep_merge(base: Dict, override: Dict) -> Dict:
        """Deep merge two dicts, override vinner vid konflikt."""
        result = copy.deepcopy(base)

        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = Configuration._deep_merge(
                    result[key], value
                )
            else:
                result[key] = copy.deepcopy(value)

        return result

    @classmethod
    def _detect_environment(cls) -> Environment:
        """Detektera miljö från environment variables."""
        env_str = (
            os.environ.get("APP_ENV")
            or os.environ.get("ENVIRONMENT")
            or "development"
        )
        return Environment.from_string(env_str)

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any], **kwargs
    ) -> Configuration:
        """Skapa Configuration från dict."""
        return cls(data, **kwargs)

    @classmethod
    def empty(cls, **kwargs) -> Configuration:
        """Skapa tom Configuration."""
        return cls({}, **kwargs)

    @classmethod
    def from_defaults(
        cls,
        schema: Type[ConfigSchema],
        **kwargs
    ) -> Configuration:
        """Skapa Configuration från schema defaults."""
        defaults = schema.get_defaults()

        # Konvertera flat keys till nested dict
        data: Dict[str, Any] = {}
        for key, value in defaults.items():
            cls._set_nested(data, key, value)

        return cls(data, **kwargs)

    @staticmethod
    def _set_nested(data: Dict, key: str, value: Any):
        """Sätt nested value med dot-notation."""
        keys = key.split('.')
        current = data

        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        current[keys[-1]] = value

    # ═══════════════════════════════════════════════════════════════════════════
    # CORE ACCESS METHODS
    # ═══════════════════════════════════════════════════════════════════════════

    def get(
        self,
        key: str,
        default: T = None,
        *,
        type_cast: Optional[Type[T]] = None,
        decrypt: bool = True
    ) -> T:
        """
        Hämta konfigurationsvärde med dot-notation.
        """
        # Check cache first
        cache_key = f"{key}:{type_cast}:{decrypt}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        with self._lock:
            # Check env override first
            if self._use_env_override:
                env_value = self._get_env_override(key)
                if env_value is not None:
                    result = self._cast_value(env_value, type_cast)
                    self._cache[cache_key] = result
                    return result

            # Navigate to value
            value = self._get_nested(key)

            if value is None:
                if self._strict and default is None:
                    raise ConfigValidationError(
                        f"Required configuration key not found: "
                        f"{key}",
                        field=key
                    )
                return default

            # Decrypt if needed
            if decrypt and self._secrets.is_encrypted(value):
                value = self._secrets.decrypt(value)

            # Type cast if needed
            if type_cast:
                result = self._cast_value(value, type_cast)
            else:
                result = value

            self._cache[cache_key] = result
            return result

    def _get_nested(self, key: str) -> Any:
        """Hämta nested value med dot-notation."""
        keys = key.split('.')
        value = self._data

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return None

            if value is None:
                return None

        return value

    def _get_env_override(self, key: str) -> Optional[str]:
        """Kolla efter environment variable override."""
        # database.url -> CONFIG_DATABASE_URL
        env_key = self.ENV_PREFIX + key.upper().replace('.', '_')
        return os.environ.get(env_key)

    @staticmethod
    def _cast_value(value: Any, target_type: Optional[Type[T]]) -> T:
        """Casta värde till måltyp."""
        if target_type is None:
            return value

        if value is None:
            return None

        # Already correct type
        if isinstance(value, target_type):
            return value

        # Bool special handling
        if target_type == bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in (
                    'true', '1', 'yes', 'on', 'enabled'
                )
            return bool(value)

        # Numeric types
        if target_type == int:
            if isinstance(value, str):
                value = value.strip()
                if value.startswith('0x'):
                    return int(value, 16)
                if value.startswith('0o'):
                    return int(value, 8)
            return int(value)

        if target_type == float:
            return float(value)

        # String
        if target_type == str:
            return str(value)

        # List
        if target_type == list:
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [
                    x.strip() for x in value.split(',') if x.strip()
                ]
            if isinstance(value, (set, tuple)):
                return list(value)
            return [value]

        # Dict
        if target_type == dict:
            if isinstance(value, dict):
                return value
            return {}

        # Path
        if target_type == Path:
            return Path(value)

        # General case
        try:
            return target_type(value)
        except Exception:
            return value

    # ═══════════════════════════════════════════════════════════════════════════
    # TYPE-SPECIFIC GETTERS
    # ═══════════════════════════════════════════════════════════════════════════

    def get_str(self, key: str, default: str = "") -> str:
        """Hämta string-värde."""
        return self.get(key, default, type_cast=str)

    def get_int(self, key: str, default: int = 0) -> int:
        """Hämta int-värde."""
        return self.get(key, default, type_cast=int)

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Hämta float-värde."""
        return self.get(key, default, type_cast=float)

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Hämta bool-värde."""
        return self.get(key, default, type_cast=bool)

    def get_list(
        self, key: str, default: Optional[List] = None
    ) -> List:
        """Hämta list-värde."""
        result = self.get(key, default or [])
        if isinstance(result, list):
            return result
        if result is None:
            return default or []
        return [result]

    def get_dict(
        self, key: str, default: Optional[Dict] = None
    ) -> Dict:
        """Hämta dict-värde."""
        result = self.get(key, default or {})
        if isinstance(result, dict):
            return result
        return default or {}

    def get_path(
        self,
        key: str,
        default: Optional[str] = None,
        *,
        must_exist: bool = False,
        create: bool = False
    ) -> Optional[Path]:
        """
        Hämta Path-värde.
        """
        value = self.get_str(key, default or "")
        if not value:
            return None

        path = Path(value)

        if create and not path.exists():
            if path.suffix:  # Har filändelse, skapa parent
                path.parent.mkdir(parents=True, exist_ok=True)
            else:  # Directory
                path.mkdir(parents=True, exist_ok=True)

        if must_exist and not path.exists():
            raise ConfigValidationError(
                f"Path does not exist: {path}",
                field=key
            )

        return path

    def get_secret(self, key: str, default: str = "") -> str:
        """Hämta och avobfuskera ett secret-värde."""
        return self.get(key, default, type_cast=str, decrypt=True)

    def get_duration(
        self,
        key: str,
        default: float = 0.0,
        unit: str = "seconds"
    ) -> float:
        """
        Hämta duration och konvertera till sekunder.
        """
        value = self.get_str(key, "")

        if not value:
            return default

        value = value.strip().lower()

        # Parse duration string
        match = re.match(r'^(\d+(?:\.\d+)?)\s*([smhd])?$', value)
        if match:
            amount = float(match.group(1))
            unit_char = match.group(2) or 's'

            multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
            return amount * multipliers.get(unit_char, 1)

        try:
            return float(value)
        except ValueError:
            return default

    def get_bytes(self, key: str, default: int = 0) -> int:
        """
        Hämta byte-storlek.
        """
        value = self.get_str(key, "")

        if not value:
            return default

        value = value.strip().upper()

        # Parse size string
        match = re.match(
            r'^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?$', value
        )
        if match:
            amount = float(match.group(1))
            unit_val = match.group(2) or 'B'

            multipliers = {
                'B': 1,
                'KB': 1024,
                'MB': 1024**2,
                'GB': 1024**3,
                'TB': 1024**4
            }
            return int(amount * multipliers.get(unit_val, 1))

        try:
            return int(value)
        except ValueError:
            return default

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION & PLUGIN ACCESS
    # ═══════════════════════════════════════════════════════════════════════════

    def section(self, key: str) -> Configuration:
        """
        Hämta en sektion som ny Configuration.
        """
        data = self._get_nested(key)

        if not isinstance(data, dict):
            data = {}

        return Configuration(
            data,
            source_path=self._source_path,
            use_env_override=self._use_env_override,
            strict=self._strict,
            environment=self._environment,
            event_bus=self._event_bus,
            secrets_handler=self._secrets
        )

    def plugin_config(self, plugin_name: str) -> Configuration:
        """
        Hämta konfiguration för en specifik plugin.
        """
        # Försök plugins.<name> först
        plugin_key = f"{self.PLUGIN_CONFIG_KEY}.{plugin_name}"
        data = self._get_nested(plugin_key)

        if not isinstance(data, dict):
            # Fallback till root level
            data = self._get_nested(plugin_name)

        if not isinstance(data, dict):
            data = {}

        # Merge med globala plugin-defaults
        defaults = self._get_nested(
            f"{self.PLUGIN_CONFIG_KEY}._defaults"
        ) or {}
        if isinstance(defaults, dict):
            data = self._deep_merge(defaults, data)

        return Configuration(
            data,
            source_path=self._source_path,
            use_env_override=self._use_env_override,
            strict=False,  # Plugin config är aldrig strict
            environment=self._environment,
            event_bus=self._event_bus,
            secrets_handler=self._secrets
        )

    def all_plugin_configs(self) -> Dict[str, Configuration]:
        """Hämta konfiguration för alla plugins."""
        plugins_section = self._get_nested(self.PLUGIN_CONFIG_KEY)

        if not isinstance(plugins_section, dict):
            return {}

        result = {}
        for name in plugins_section:
            if not name.startswith('_'):  # Skip _defaults etc
                result[name] = self.plugin_config(name)

        return result

    def has(self, key: str) -> bool:
        """Kolla om nyckel finns."""
        return self._get_nested(key) is not None

    def keys(self, prefix: str = "") -> List[str]:
        """Lista alla nycklar (med optional prefix)."""
        if prefix:
            data = self._get_nested(prefix)
            if not isinstance(data, dict):
                return []
            return list(data.keys())
        return list(self._data.keys())

    def items(self, prefix: str = "") -> Iterator[Tuple[str, Any]]:
        """Iterera över key-value pairs."""
        data = self._get_nested(prefix) if prefix else self._data
        if isinstance(data, dict):
            for key, value in data.items():
                yield key, value

    # ═══════════════════════════════════════════════════════════════════════════
    # MODIFICATION
    # ═══════════════════════════════════════════════════════════════════════════

    def set(
        self,
        key: str,
        value: Any,
        *,
        encrypt: bool = False,
        emit_event: bool = True
    ) -> None:
        """
        Sätt ett konfigurationsvärde.
        """
        with self._lock:
            # Get old value for change tracking
            old_value = self._get_nested(key)

            # Encrypt if requested
            if encrypt and isinstance(value, str):
                value = self._secrets.encrypt(value)

            # Set the value
            keys = key.split('.')
            data = self._data

            for k in keys[:-1]:
                if k not in data or not isinstance(data[k], dict):
                    data[k] = {}
                data = data[k]

            data[keys[-1]] = value

            # Invalidate cache
            self._cache.clear()

        # Emit change event
        if emit_event:
            self._emit_change(ConfigChange(
                change_type=ConfigChangeType.SET,
                key=key,
                old_value=old_value,
                new_value=value,
                source="code"
            ))

    def delete(self, key: str, emit_event: bool = True) -> bool:
        """
        Ta bort ett konfigurationsvärde.
        """
        with self._lock:
            keys = key.split('.')
            data = self._data

            # Navigate to parent
            for k in keys[:-1]:
                if not isinstance(data, dict) or k not in data:
                    return False
                data = data[k]

            # Delete final key
            if not isinstance(data, dict) or keys[-1] not in data:
                return False

            old_value = data[keys[-1]]
            del data[keys[-1]]

            # Invalidate cache
            self._cache.clear()

        if emit_event:
            self._emit_change(ConfigChange(
                change_type=ConfigChangeType.DELETE,
                key=key,
                old_value=old_value,
                source="code"
            ))

        return True

    def update(
        self,
        data: Dict[str, Any],
        *,
        merge: bool = True,
        emit_event: bool = True
    ) -> None:
        """
        Uppdatera med dict.
        """
        with self._lock:
            if merge:
                self._data = self._deep_merge(self._data, data)
            else:
                self._data = copy.deepcopy(data)

            self._cache.clear()

        if emit_event:
            self._emit_change(ConfigChange(
                change_type=ConfigChangeType.MERGE,
                key="*",
                new_value=data,
                source="code"
            ))

    @contextmanager
    def temporary(self, overrides: Dict[str, Any]):
        """
        Tillfälliga config overrides.
        """
        original = copy.deepcopy(self._data)
        original_cache = self._cache.copy()

        try:
            # Applicera overrides
            for key, value in overrides.items():
                self.set(key, value, emit_event=False)

            yield self

        finally:
            # Återställ original
            self._data = original
            self._cache = original_cache

    # ═══════════════════════════════════════════════════════════════════════════
    # PERSISTENCE
    # ═══════════════════════════════════════════════════════════════════════════

    def save(
        self,
        path: Optional[Path] = None,
        *,
        indent: int = 2,
        sort_keys: bool = False,
        exclude_secrets: bool = False
    ) -> None:
        """
        Spara konfiguration till fil.

        FIXAT v1.1.0: ATOMISK skrivning enligt spec —
        tempfile.mkstemp -> os.fdopen -> fsync -> os.replace.
        (Tidigare användes write_text direkt, vilket riskerar
        korrupt fil vid krasch mitt i skrivningen.)
        """
        save_path = path or self._source_path

        if not save_path:
            raise ConfigError(
                "No path specified and no source path available"
            )

        save_path = Path(save_path)

        # Prepare data
        data = copy.deepcopy(self._data)

        if exclude_secrets:
            data = self._remove_secrets(data)

        try:
            content = json.dumps(
                data,
                indent=indent,
                ensure_ascii=False,
                sort_keys=sort_keys
            )

            # Skapa parent directories om de saknas
            save_path.parent.mkdir(parents=True, exist_ok=True)

            # Atomisk skrivning
            fd, tmp_path = tempfile.mkstemp(
                dir=str(save_path.parent),
                suffix=".tmp",
                prefix=f".{save_path.name}.tmp_",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, str(save_path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            _log.info("Saved configuration to %s", save_path)

        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(
                f"Failed to save configuration: {e}",
                config_path=save_path
            ) from e

    def _remove_secrets(self, data: Dict) -> Dict:
        """Ta bort obfuskerade värden från data."""
        result = {}

        for key, value in data.items():
            if isinstance(value, dict):
                result[key] = self._remove_secrets(value)
            elif (
                isinstance(value, str)
                and self._secrets.is_encrypted(value)
            ):
                result[key] = "[ENCRYPTED]"
            else:
                result[key] = value

        return result

    def reload(self) -> None:
        """
        Ladda om konfiguration från ursprunglig fil.
        """
        if not self._source_path:
            raise ConfigError("No source path available for reload")

        new_config = Configuration.load(
            self._source_path,
            use_env_override=self._use_env_override,
            strict=self._strict,
            environment=self._environment,
            event_bus=self._event_bus
        )

        with self._lock:
            old_data = self._data
            self._data = new_config._data
            self._cache.clear()

        _log.info(
            "Reloaded configuration from %s", self._source_path,
        )

        self._emit_change(ConfigChange(
            change_type=ConfigChangeType.RELOAD,
            key="*",
            old_value=old_data,
            new_value=self._data,
            source="file"
        ))

    # ═══════════════════════════════════════════════════════════════════════════
    # FILE WATCHING
    # ═══════════════════════════════════════════════════════════════════════════

    def enable_auto_reload(
        self,
        check_interval: float = 5.0,
        on_change: Optional[Callable[[Configuration], None]] = None
    ) -> None:
        """
        Aktivera automatisk reload vid filändring.
        """
        if not self._source_path:
            _log.warning(
                "Cannot enable auto-reload without source path"
            )
            return

        if self._watcher:
            self._watcher.stop()

        self._watcher = ConfigFileWatcher(
            self,
            check_interval=check_interval,
            on_change=on_change
        )
        self._watcher.start()

    def disable_auto_reload(self) -> None:
        """Inaktivera automatisk reload."""
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

    # ═══════════════════════════════════════════════════════════════════════════
    # CHANGE TRACKING
    # ═══════════════════════════════════════════════════════════════════════════

    def add_change_listener(
        self,
        listener: Callable[[ConfigChange], None]
    ) -> None:
        """Lägg till en change listener."""
        if listener not in self._change_listeners:
            self._change_listeners.append(listener)

    def remove_change_listener(
        self,
        listener: Callable[[ConfigChange], None]
    ) -> None:
        """Ta bort en change listener."""
        if listener in self._change_listeners:
            self._change_listeners.remove(listener)

    def _emit_change(self, change: ConfigChange) -> None:
        """Emittera config change event."""
        # Notify local listeners
        for listener in self._change_listeners:
            try:
                listener(change)
            except Exception as e:
                _log.error("Change listener error: %s", e)

        # Notify event bus
        if self._event_bus:
            try:
                self._event_bus.emit("config:changed", change)
            except Exception as e:
                _log.error("Failed to emit config event: %s", e)

    # ═══════════════════════════════════════════════════════════════════════════
    # VALIDATION
    # ═══════════════════════════════════════════════════════════════════════════

    def validate(
        self,
        schema: Dict[str, Any],
        raise_on_error: bool = False
    ) -> List[str]:
        """
        Validera mot ett enkelt schema.
        """
        errors = []

        for key, validator in schema.items():
            value = self._get_nested(key)

            # Handle (type, required) tuple
            required = False
            if isinstance(validator, tuple):
                validator, required = validator

            # Check required
            if value is None:
                if required:
                    errors.append(f"Missing required field: {key}")
                continue

            # Type check
            if isinstance(validator, type):
                if not isinstance(value, validator):
                    errors.append(
                        f"Invalid type for {key}: "
                        f"expected {validator.__name__}, "
                        f"got {type(value).__name__}"
                    )

            # Callable validator
            elif callable(validator):
                try:
                    if not validator(value):
                        errors.append(
                            f"Validation failed for {key}"
                        )
                except Exception as e:
                    errors.append(
                        f"Validator error for {key}: {e}"
                    )

        if raise_on_error and errors:
            raise ConfigValidationError(
                f"Configuration validation failed: "
                f"{len(errors)} error(s)",
                details={"errors": errors}
            )

        return errors

    def validate_schema(
        self,
        schema_class: Type[ConfigSchema],
        raise_on_error: bool = False
    ) -> List[str]:
        """
        Validera mot en ConfigSchema-klass.
        """
        errors = schema_class.validate(self)

        if raise_on_error and errors:
            raise ConfigValidationError(
                f"Configuration validation failed: "
                f"{len(errors)} error(s)",
                details={"errors": errors}
            )

        return errors

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════════════════════

    def to_dict(self, include_secrets: bool = False) -> Dict[str, Any]:
        """Returnera konfiguration som dict."""
        if include_secrets:
            return copy.deepcopy(self._data)
        return self._remove_secrets(copy.deepcopy(self._data))

    def to_json(
        self,
        indent: int = 2,
        include_secrets: bool = False
    ) -> str:
        """Returnera konfiguration som JSON-string."""
        data = self.to_dict(include_secrets=include_secrets)
        return json.dumps(data, indent=indent, ensure_ascii=False)

    def to_flat_dict(self) -> Dict[str, Any]:
        """
        Returnera som flat dict med dot-notation nycklar.
        """
        result = {}

        def flatten(data: Dict, prefix: str = ""):
            for key, value in data.items():
                full_key = f"{prefix}.{key}" if prefix else key

                if isinstance(value, dict):
                    flatten(value, full_key)
                else:
                    result[full_key] = value

        flatten(self._data)
        return result

    @property
    def source_path(self) -> Optional[Path]:
        """Ursprunglig filsökväg."""
        return self._source_path

    @property
    def environment(self) -> Environment:
        """Aktuell miljö."""
        return self._environment

    @property
    def version(self) -> int:
        """Config version."""
        return self._version

    @property
    def is_production(self) -> bool:
        """True om production miljö."""
        return self._environment == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        """True om development miljö."""
        return self._environment == Environment.DEVELOPMENT

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key)
        if value is None and self._strict:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __repr__(self) -> str:
        keys = len(self._data)
        source = (
            self._source_path.name if self._source_path else "memory"
        )
        return (
            f"<Configuration "
            f"keys={keys} "
            f"source={source} "
            f"env={self._environment.value}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# STANDARD SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class CoreConfigSchema(ConfigSchema):
    """Standard schema för core application config."""

    schema = {
        "app.name": ConfigField(
            type=str,
            default="Transportstyrelsen Fordonsregistreringssystem",
            description="Application name"
        ),
        "app.version": ConfigField(
            type=str,
            default="1.0.0",
            pattern=r"^\d+\.\d+\.\d+$"
        ),
        "app.debug": ConfigField(
            type=bool,
            default=False
        ),
        "paths.data": ConfigField(
            type=str,
            default="data",
            description="Data directory"
        ),
        "paths.logs": ConfigField(
            type=str,
            default="logs"
        ),
        "paths.plugins": ConfigField(
            type=str,
            default="plugins"
        ),
        "plugins.auto_load": ConfigField(
            type=bool,
            default=True
        ),
        "plugins.disabled": ConfigField(
            type=list,
            default=[]
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL ACCESS
# ══════════════════════════════════════════════════════════════════════════════

global_config: Optional[Configuration] = None
config_lock = threading.Lock()


def get_config() -> Configuration:
    """
    Hämta global configuration.
    """
    if global_config is None:
        raise ConfigError(
            "Configuration not loaded. Call load_config() first."
        )
    return global_config


def load_config(
    path: str | Path,
    *,
    set_global: bool = True,
    **kwargs
) -> Configuration:
    """
    Ladda och (optionellt) sätt global configuration.
    """
    global global_config

    config = Configuration.load(path, **kwargs)

    if set_global:
        with config_lock:
            global_config = config

    return config


def reset_config() -> None:
    """Nollställ global configuration (för tester)."""
    global global_config
    with config_lock:
        if global_config:
            global_config.disable_auto_reload()
        global_config = None


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Main class
    "Configuration",

    # Schema
    "ConfigSchema",
    "ConfigField",
    "CoreConfigSchema",

    # Supporting classes
    "ConfigChange",
    "ConfigChangeType",
    "ConfigFileWatcher",
    "Environment",
    "SecretsHandler",

    # Exceptions (re-export for convenience)
    "ConfigError",
    "ConfigNotFoundError",
    "ConfigValidationError",
    "ConfigParseError",

    # Global access
    "get_config",
    "load_config",
    "reset_config",

    # Version
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]