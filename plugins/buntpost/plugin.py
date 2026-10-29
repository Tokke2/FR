# -*- coding: utf-8 -*-
"""
Buntpost Plugin v2.0.0

Hanterar dynamiska postbeskrivningar för fixed-length filgenerering.

Features:
    - Ladda postspecifikationer från JSON/Excel/CSV
    - Validera specifikationer och värden
    - Generera poster dynamiskt
    - Parsa befintliga poster
    - GUI-editor för specifikationer
    - Stöd för Transportstyrelsen-format (2500 tecken)

Används av:
    - ts_file_generator
    - identity_post
    - end_post
    - vehicle_registration_post
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from core.plugin_base import PluginBase

try:
    from core.exceptions import CoreError, ValidationError
except Exception:
    class CoreError(Exception):
        """Fallback om core.exceptions saknas."""

    class ValidationError(CoreError):
        """Fallback om core.exceptions saknas."""
        pass


logger = logging.getLogger(__name__)

VERSION: Final[str] = "2.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


def _make_validation_error(message: str, field_name: str = "") -> ValidationError:
    """Skapa ValidationError kompatibelt med flera signaturer."""
    try:
        return ValidationError(message, field=field_name)
    except TypeError:
        return ValidationError(message)


def _parse_bool(value: Any) -> bool:
    """Parsa bool från olika format."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "ja", "1", "x"}
    return bool(value)


def get_config_value(app: Any, key: str, default: Any = None) -> Any:
    """Hämta config-värde säkert."""
    if app is None:
        return default

    config = getattr(app, "config", None)
    if config is not None:
        try:
            if hasattr(config, "get") and callable(config.get):
                value = config.get(key, default)
                return default if value is None else value
            if isinstance(config, dict):
                value = config.get(key, default)
                return default if value is None else value
        except Exception:
            pass

    plugin_manager = getattr(app, "plugin_manager", None)
    if plugin_manager is not None and hasattr(plugin_manager, "get_plugin"):
        try:
            core_config = plugin_manager.get_plugin("core_config")
            if core_config is not None:
                if hasattr(core_config, "get_config_value") and callable(core_config.get_config_value):
                    value = core_config.get_config_value(key, default)
                    return default if value is None else value
                if hasattr(core_config, "get") and callable(core_config.get):
                    value = core_config.get(key, default)
                    return default if value is None else value
        except Exception:
            pass

    return default


def get_event_bus(app: Any) -> Any:
    """Hämta event bus säkert."""
    if app is None:
        return None
    return getattr(app, "event_bus", None) or getattr(app, "events", None)


def subscribe_event_safe(app: Any, event_name: str, handler: Any) -> bool:
    """Registrera event-handler säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False

    try:
        if hasattr(bus, "on") and callable(bus.on):
            bus.on(event_name, handler)
            return True
        if hasattr(bus, "subscribe") and callable(bus.subscribe):
            bus.subscribe(event_name, handler)
            return True
    except Exception:
        logger.exception("Kunde inte prenumerera på event '%s'", event_name)

    return False


def unsubscribe_event_safe(app: Any, event_name: str, handler: Any) -> bool:
    """Avregistrera event-handler säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False

    try:
        if hasattr(bus, "off") and callable(bus.off):
            bus.off(event_name, handler)
            return True
        if hasattr(bus, "unsubscribe") and callable(bus.unsubscribe):
            bus.unsubscribe(event_name, handler)
            return True
    except Exception:
        logger.exception("Kunde inte avregistrera event '%s'", event_name)

    return False


def emit_event_safe(app: Any, event_name: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """Emittera event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False

    payload = data or {}

    try:
        if hasattr(bus, "emit") and callable(bus.emit):
            bus.emit(event_name, payload)
            return True
        if hasattr(bus, "publish") and callable(bus.publish):
            bus.publish(event_name, payload)
            return True
    except Exception:
        logger.exception("Kunde inte emittera event '%s'", event_name)

    return False


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Skriv JSON atomiskt."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.stem}_",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with open(fd, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


class FieldType(str, Enum):
    """Fälttyper för postspecifikation."""

    TEXT = "text"
    NUMERIC = "numeric"
    DATE = "date"
    ALPHANUMERIC = "alphanumeric"
    CONSTANT = "constant"

    @classmethod
    def choices(cls) -> List[str]:
        return [enum_value.value for enum_value in cls]


class Alignment(str, Enum):
    """Textjustering."""

    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"

    @classmethod
    def choices(cls) -> List[str]:
        return [enum_value.value for enum_value in cls]


class PadChar(str, Enum):
    """Utfyllnadstecken."""

    SPACE = " "
    ZERO = "0"

    @classmethod
    def from_string(cls, value: str) -> "PadChar":
        if value == "0":
            return cls.ZERO
        return cls.SPACE


STANDARD_POST_LENGTHS: Final[Dict[str, int]] = {
    "TS": 2500,
    "STANDARD": 80,
    "WIDE": 132,
}

DATE_FORMATS: Final[List[str]] = [
    "%Y%m%d",
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%y%m%d",
]


@dataclass
class FieldSpec:
    """Specifikation för ett fält i posten."""

    name: str
    position: int
    length: int
    field_type: str = FieldType.TEXT.value
    required: bool = True
    default: str = ""
    description: str = ""
    alignment: str = Alignment.LEFT.value
    pad_char: str = PadChar.SPACE.value
    valid_values: List[str] = field(default_factory=list)
    regex_pattern: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    date_format: str = "%Y%m%d"

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
        self.field_type = str(self.field_type).strip().lower()
        self.alignment = str(self.alignment).strip().lower()
        self.pad_char = str(self.pad_char or " ")

        if self.position < 1:
            raise _make_validation_error(
                f"Position must be >= 1, got {self.position}",
                "position",
            )
        if self.length < 1:
            raise _make_validation_error(
                f"Length must be >= 1, got {self.length}",
                "length",
            )
        if not self.name:
            raise _make_validation_error("Field name cannot be empty", "name")

    @property
    def end_position(self) -> int:
        return self.position + self.length - 1

    @property
    def slice(self) -> slice:
        return slice(self.position - 1, self.position - 1 + self.length)

    def format_value(self, value: Any) -> Tuple[str, List[str]]:
        warnings: List[str] = []

        if value is None or str(value).strip() == "":
            value = self.default

        str_value = self._convert_value(value, warnings)

        if len(str_value) > self.length:
            str_value = str_value[: self.length]
            warnings.append(f"{self.name}: Truncated to {self.length} chars")

        str_value = self._pad_value(str_value)
        return str_value, warnings

    def _convert_value(self, value: Any, warnings: List[str]) -> str:
        str_value = str(value).strip()

        if self.field_type == FieldType.NUMERIC.value:
            clean = re.sub(r"[^\d.\-]", "", str_value)
            if not clean or clean in {"", "-", "."}:
                clean = "0"

            if "." in clean:
                str_value = clean
            else:
                try:
                    str_value = str(int(clean))
                except ValueError:
                    str_value = "0"
                    warnings.append(f"{self.name}: Invalid numeric value")

        elif self.field_type == FieldType.DATE.value:
            str_value = self._format_date(value, warnings)

        elif self.field_type == FieldType.CONSTANT.value:
            str_value = self.default

        elif self.field_type == FieldType.ALPHANUMERIC.value:
            str_value = re.sub(r"[^A-Za-z0-9]", "", str_value)

        return str_value

    def _format_date(self, value: Any, warnings: List[str]) -> str:
        parsed_date: Optional[datetime] = None

        if isinstance(value, datetime):
            parsed_date = value
        elif isinstance(value, date):
            parsed_date = datetime.combine(value, datetime.min.time())
        elif isinstance(value, str):
            for date_format in DATE_FORMATS:
                try:
                    parsed_date = datetime.strptime(value.strip(), date_format)
                    break
                except ValueError:
                    continue

        if parsed_date is None:
            warnings.append(f"{self.name}: Could not parse date '{value}'")
            parsed_date = datetime.now()

        return parsed_date.strftime(self.date_format)

    def _pad_value(self, value: str) -> str:
        if self.alignment == Alignment.RIGHT.value:
            return value.rjust(self.length, self.pad_char)
        if self.alignment == Alignment.CENTER.value:
            return value.center(self.length, self.pad_char)
        return value.ljust(self.length, self.pad_char)

    def validate_value(self, value: Any) -> List[str]:
        errors: List[str] = []

        if value is None or str(value).strip() == "":
            if self.required and not self.default:
                errors.append(f"{self.name}: Required field is empty")
            return errors

        str_value = str(value).strip()

        if len(str_value) > self.length:
            errors.append(
                f"{self.name}: Value too long ({len(str_value)} > {self.length})"
            )

        if self.regex_pattern and not re.match(self.regex_pattern, str_value):
            errors.append(f"{self.name}: Does not match pattern {self.regex_pattern}")

        if self.valid_values and str_value not in self.valid_values:
            preview = ", ".join(self.valid_values[:5])
            errors.append(
                f"{self.name}: Invalid value '{str_value}' (allowed: {preview})"
            )

        if self.field_type == FieldType.NUMERIC.value:
            try:
                number = float(re.sub(r"[^\d.\-]", "", str_value) or "0")
                if self.min_value is not None and number < self.min_value:
                    errors.append(f"{self.name}: Value {number} < min {self.min_value}")
                if self.max_value is not None and number > self.max_value:
                    errors.append(f"{self.name}: Value {number} > max {self.max_value}")
            except ValueError:
                errors.append(f"{self.name}: Not a valid number")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FieldSpec":
        return cls(
            name=data.get("name", ""),
            position=int(data.get("position", data.get("pos", 1))),
            length=int(data.get("length", data.get("längd", 1))),
            field_type=data.get("field_type", data.get("typ", FieldType.TEXT.value)),
            required=_parse_bool(data.get("required", data.get("obligatorisk", True))),
            default=str(data.get("default", "")),
            description=data.get("description", data.get("beskrivning", "")),
            alignment=data.get("alignment", Alignment.LEFT.value),
            pad_char=data.get("pad_char", PadChar.SPACE.value),
            valid_values=data.get("valid_values", []),
            regex_pattern=data.get("regex_pattern", ""),
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            date_format=data.get("date_format", "%Y%m%d"),
        )


@dataclass
class PostSpec:
    """Specifikation för en komplett post."""

    name: str
    post_type: str
    total_length: int
    description: str = ""
    fields: List[FieldSpec] = field(default_factory=list)
    version: str = "1.0"
    source: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
        self.post_type = str(self.post_type).strip()

        if not self.name:
            raise _make_validation_error("Post name cannot be empty", "name")
        if not self.post_type:
            raise _make_validation_error("Post type cannot be empty", "post_type")
        if self.total_length < 1:
            raise _make_validation_error(
                f"Total length must be >= 1, got {self.total_length}",
                "total_length",
            )

    @property
    def calculated_length(self) -> int:
        if not self.fields:
            return 0
        return max(field_spec.end_position for field_spec in self.fields)

    @property
    def field_names(self) -> List[str]:
        return [field_spec.name for field_spec in self.fields]

    def get_field(self, name: str) -> Optional[FieldSpec]:
        for field_spec in self.fields:
            if field_spec.name == name:
                return field_spec
        return None

    def validate(self) -> Tuple[bool, List[str]]:
        errors: List[str] = []

        if not self.fields:
            errors.append("No fields defined")
            return False, errors

        positions: Dict[int, str] = {}
        for field_spec in self.fields:
            for pos in range(field_spec.position, field_spec.end_position + 1):
                if pos in positions:
                    errors.append(
                        f"Position {pos} overlap: {positions[pos]} and {field_spec.name}"
                    )
                else:
                    positions[pos] = field_spec.name

        for field_spec in self.fields:
            if field_spec.end_position > self.total_length:
                errors.append(
                    f"Field {field_spec.name} exceeds total length "
                    f"(ends at {field_spec.end_position}, max {self.total_length})"
                )

        all_positions = set(range(1, self.total_length + 1))
        used_positions = set(positions.keys())
        gaps = all_positions - used_positions

        if gaps and len(gaps) <= 20:
            errors.append(f"Undefined positions: {sorted(gaps)}")
        elif gaps:
            errors.append(f"{len(gaps)} undefined positions")

        return len(errors) == 0, errors

    def generate(self, values: Dict[str, Any]) -> Tuple[str, List[str]]:
        warnings: List[str] = []
        post = [" "] * self.total_length

        for field_spec in self.fields:
            value = values.get(field_spec.name)
            formatted, field_warnings = field_spec.format_value(value)
            warnings.extend(field_warnings)

            for index, character in enumerate(formatted):
                target_index = field_spec.position - 1 + index
                if target_index < len(post):
                    post[target_index] = character

        return "".join(post), warnings

    def parse(self, post_string: str) -> Tuple[Dict[str, str], List[str]]:
        errors: List[str] = []
        values: Dict[str, str] = {}

        if len(post_string) != self.total_length:
            errors.append(
                f"Post length {len(post_string)} != expected {self.total_length}"
            )

        for field_spec in self.fields:
            try:
                raw = post_string[field_spec.slice]
                if field_spec.field_type == FieldType.NUMERIC.value:
                    value = raw.lstrip("0 ").strip() or "0"
                else:
                    value = raw.strip()
                values[field_spec.name] = value
            except IndexError:
                values[field_spec.name] = ""
                errors.append(f"Field {field_spec.name} out of bounds")

        return values, errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "post_type": self.post_type,
            "total_length": self.total_length,
            "description": self.description,
            "fields": [field_spec.to_dict() for field_spec in self.fields],
            "version": self.version,
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostSpec":
        fields = [FieldSpec.from_dict(item) for item in data.get("fields", [])]
        return cls(
            name=data.get("name", ""),
            post_type=data.get("post_type", ""),
            total_length=int(data.get("total_length", 0)),
            description=data.get("description", ""),
            fields=fields,
            version=data.get("version", "1.0"),
            source=data.get("source", ""),
            created_at=data.get("created_at", datetime.now().isoformat()),
        )


class PostSpecService:
    """Service för hantering av postspecifikationer."""

    def __init__(self, specs_dir: Path):
        self.specs_dir = specs_dir
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        self._specs: Dict[str, PostSpec] = {}
        self._loaded = False

    def load_all(self) -> int:
        self._specs.clear()

        for spec_file in self.specs_dir.glob("*.json"):
            try:
                spec = self._load_json(spec_file)
                self._specs[spec.post_type] = spec
                logger.debug("Loaded spec: %s (type %s)", spec.name, spec.post_type)
            except Exception as exc:
                logger.warning("Failed to load %s: %s", spec_file.name, exc)

        self._loaded = True
        logger.info("Loaded %s post specifications", len(self._specs))
        return len(self._specs)

    def get(self, post_type: str) -> Optional[PostSpec]:
        self._ensure_loaded()
        return self._specs.get(post_type)

    def get_all(self) -> List[PostSpec]:
        self._ensure_loaded()
        return list(self._specs.values())

    def list_types(self) -> List[str]:
        self._ensure_loaded()
        return list(self._specs.keys())

    def add(self, spec: PostSpec) -> bool:
        is_valid, errors = spec.validate()
        if not is_valid:
            for error in errors:
                logger.warning("Spec validation: %s", error)

        self._specs[spec.post_type] = spec
        return self._save_spec(spec)

    def delete(self, post_type: str) -> bool:
        if post_type not in self._specs:
            return False

        del self._specs[post_type]

        spec_file = self.specs_dir / f"{post_type}.json"
        if spec_file.exists():
            spec_file.unlink()

        logger.info("Deleted spec: %s", post_type)
        return True

    def load_from_file(self, filepath: Path) -> Optional[PostSpec]:
        if not filepath.exists():
            logger.error("File not found: %s", filepath)
            return None

        suffix = filepath.suffix.lower()

        try:
            if suffix == ".json":
                spec = self._load_json(filepath)
            elif suffix in (".xlsx", ".xls"):
                spec = self._load_excel(filepath)
            elif suffix == ".csv":
                spec = self._load_csv(filepath)
            else:
                logger.error("Unsupported format: %s", suffix)
                return None

            spec.source = str(filepath)
            spec.created_at = datetime.now().isoformat()

            is_valid, errors = spec.validate()
            if not is_valid:
                for error in errors[:5]:
                    logger.warning("Validation: %s", error)

            self._specs[spec.post_type] = spec
            self._save_spec(spec)

            logger.info(
                "Loaded spec: %s (type %s, %s fields, %s chars)",
                spec.name,
                spec.post_type,
                len(spec.fields),
                spec.total_length,
            )
            return spec

        except Exception:
            logger.exception("Failed to load spec from %s", filepath)
            return None

    def generate_post(
        self,
        post_type: str,
        values: Dict[str, Any],
    ) -> Tuple[Optional[str], List[str]]:
        spec = self.get(post_type)
        if not spec:
            return None, [f"No spec for post type: {post_type}"]
        return spec.generate(values)

    def parse_post(
        self,
        post_type: str,
        post_string: str,
    ) -> Tuple[Dict[str, str], List[str]]:
        spec = self.get(post_type)
        if not spec:
            return {}, [f"No spec for post type: {post_type}"]
        return spec.parse(post_string)

    def validate_values(
        self,
        post_type: str,
        values: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        spec = self.get(post_type)
        if not spec:
            return False, [f"No spec for post type: {post_type}"]

        errors: List[str] = []
        for field_spec in spec.fields:
            value = values.get(field_spec.name)
            errors.extend(field_spec.validate_value(value))

        return len(errors) == 0, errors

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load_all()

    def _load_json(self, filepath: Path) -> PostSpec:
        with open(filepath, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return PostSpec.from_dict(data)

    def _load_excel(self, filepath: Path) -> PostSpec:
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "pandas required for Excel (pip install pandas openpyxl)"
            ) from exc

        df = pd.read_excel(filepath, dtype=str).fillna("")
        fields: List[FieldSpec] = []

        for _, row in df.iterrows():
            try:
                field_spec = FieldSpec.from_dict(row.to_dict())
                fields.append(field_spec)
            except ValidationError as exc:
                logger.warning("Invalid field in Excel: %s", exc)

        name = filepath.stem
        post_type = "01"
        total_length = max((field_spec.end_position for field_spec in fields), default=0)

        return PostSpec(
            name=name,
            post_type=post_type,
            total_length=total_length,
            fields=fields,
        )

    def _load_csv(self, filepath: Path) -> PostSpec:
        fields: List[FieldSpec] = []

        with open(filepath, "r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(1024)
            handle.seek(0)

            delimiter = ";" if ";" in sample else ","
            reader = csv.DictReader(handle, delimiter=delimiter)

            for row in reader:
                try:
                    normalized_row = {
                        str(key).lower().strip(): value
                        for key, value in row.items()
                    }
                    field_spec = FieldSpec.from_dict(normalized_row)
                    fields.append(field_spec)
                except ValidationError as exc:
                    logger.warning("Invalid field in CSV: %s", exc)

        name = filepath.stem
        post_type = "01"
        total_length = max((field_spec.end_position for field_spec in fields), default=0)

        return PostSpec(
            name=name,
            post_type=post_type,
            total_length=total_length,
            fields=fields,
        )

    def _save_spec(self, spec: PostSpec) -> bool:
        try:
            spec_file = self.specs_dir / f"{spec.post_type}.json"
            atomic_write_json(spec_file, spec.to_dict())
            return True
        except Exception as exc:
            logger.error("Failed to save spec: %s", exc)
            return False


class Plugin(PluginBase):
    """Buntpost Plugin."""

    NAME = "Buntpost"
    VERSION = "2.0.0"
    DESCRIPTION = "Dynamisk hantering av postbeskrivningar"
    AUTHOR = AUTHOR
    COPYRIGHT = get_copyright_string()
    DEPENDENCIES: List[str] = []

    def __init__(self, app: Any):
        super().__init__(app)
        self.is_active: bool = False
        self._service: Optional[PostSpecService] = None
        self._widget: Optional["PostFormatWidget"] = None
        self._event_registered: bool = False

    @property
    def service(self) -> PostSpecService:
        if self._service is None:
            raise RuntimeError("Plugin not initialized")
        return self._service

    def initialize(self) -> bool:
        try:
            base_dir = Path(get_config_value(self.app, "base_dir", ".") or ".")
            data_dir_name = get_config_value(self.app, "data_dir", "data")
            specs_dir = base_dir / data_dir_name / "post_specs"

            self._service = PostSpecService(specs_dir)

            count = self._service.load_all()

            if self.app is not None:
                setattr(self.app, "buntpost", self)
                setattr(self.app, "post_format", self)

            logger.info("Buntpost initialized with %s specs", count)
            return True

        except Exception:
            logger.exception("Failed to initialize Buntpost")
            return False

    def activate(self) -> bool:
        self.is_active = True
        self._event_registered = subscribe_event_safe(
            self.app,
            "postformat:generate",
            self._on_generate_request,
        )
        return True

    def deactivate(self) -> bool:
        if self._event_registered:
            unsubscribe_event_safe(self.app, "postformat:generate", self._on_generate_request)
            self._event_registered = False

        self._widget = None
        self.is_active = False
        return True

    def init(self) -> bool:
        return self.initialize()

    def register_ui(self, parent: QWidget) -> QWidget:
        return self.create_widget(parent)

    def shutdown(self) -> bool:
        return self.deactivate()

    def config_schema(self) -> Dict[str, Any]:
        return {
            "enabled": {
                "type": "boolean",
                "default": True,
                "description": "Aktivera buntpost-pluginet.",
            },
            "specs_dir": {
                "type": "string",
                "default": "data/post_specs",
                "description": "Katalog där postspecifikationer lagras.",
            },
        }

    def create_widget(self, parent: QWidget) -> QWidget:
        self._widget = PostFormatWidget(parent, self.service)
        return self._widget

    def get_spec(self, post_type: str) -> Optional[PostSpec]:
        return self.service.get(post_type)

    def list_specs(self) -> List[Dict[str, Any]]:
        return [
            {
                "post_type": spec.post_type,
                "name": spec.name,
                "total_length": spec.total_length,
                "fields_count": len(spec.fields),
            }
            for spec in self.service.get_all()
        ]

    def load_spec_from_file(self, filepath: Path) -> Optional[PostSpec]:
        return self.service.load_from_file(filepath)

    def generate_post(
        self,
        post_type: str,
        values: Dict[str, Any],
    ) -> Tuple[Optional[str], List[str]]:
        return self.service.generate_post(post_type, values)

    def parse_post(
        self,
        post_type: str,
        post_string: str,
    ) -> Tuple[Dict[str, str], List[str]]:
        return self.service.parse_post(post_type, post_string)

    def validate_values(
        self,
        post_type: str,
        values: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        return self.service.validate_values(post_type, values)

    def create_spec(
        self,
        name: str,
        post_type: str,
        total_length: int,
        fields: List[Dict[str, Any]],
        description: str = "",
    ) -> PostSpec:
        field_specs = [FieldSpec.from_dict(field_data) for field_data in fields]

        spec = PostSpec(
            name=name,
            post_type=post_type,
            total_length=total_length,
            description=description,
            fields=field_specs,
        )

        self.service.add(spec)
        return spec

    def delete_spec(self, post_type: str) -> bool:
        return self.service.delete(post_type)

    def _on_generate_request(self, data: Dict[str, Any]) -> None:
        post_type = data.get("post_type")
        values = data.get("values", {})
        callback = data.get("callback")

        if not post_type:
            return

        result, warnings = self.generate_post(post_type, values)

        if callable(callback):
            callback(result, warnings)

        emit_event_safe(
            self.app,
            "postformat:generated",
            {
                "post_type": post_type,
                "success": result is not None,
                "warnings": warnings,
            },
        )


class PostFormatWidget(QWidget):
    """Widget för postspecifikationer."""

    def __init__(self, parent: QWidget, service: PostSpecService):
        super().__init__(parent)
        self.service = service
        self._current_spec: Optional[PostSpec] = None

        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("📋 Buntpost / Postbeskrivningar")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setWordWrap(True)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)

        left_panel = self._create_list_panel()
        splitter.addWidget(left_panel)

        right_panel = self._create_detail_panel()
        splitter.addWidget(right_panel)

        splitter.setSizes([300, 700])
        layout.addWidget(splitter, 1)

    def _create_list_panel(self) -> QGroupBox:
        group = QGroupBox("Posttyper")
        layout = QVBoxLayout(group)

        self.spec_list = QListWidget()
        self.spec_list.currentItemChanged.connect(self._on_spec_selected)
        layout.addWidget(self.spec_list)

        btn_layout = QHBoxLayout()

        btn_load = QPushButton("📂 Ladda fil...")
        btn_load.clicked.connect(self._on_load_file)
        btn_layout.addWidget(btn_load)

        btn_new = QPushButton("➕ Ny")
        btn_new.clicked.connect(self._on_new_spec)
        btn_layout.addWidget(btn_new)

        btn_delete = QPushButton("🗑️")
        btn_delete.setFixedWidth(40)
        btn_delete.clicked.connect(self._on_delete_spec)
        btn_layout.addWidget(btn_delete)

        layout.addLayout(btn_layout)
        return group

    def _create_detail_panel(self) -> QTabWidget:
        tabs = QTabWidget()

        fields_tab = self._create_fields_tab()
        tabs.addTab(fields_tab, "📝 Fält")

        test_tab = self._create_test_tab()
        tabs.addTab(test_tab, "🧪 Test")

        return tabs

    def _create_fields_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info_frame = QFrame()
        info_frame.setFrameStyle(QFrame.StyledPanel)
        info_layout = QGridLayout(info_frame)

        info_layout.addWidget(QLabel("Namn:"), 0, 0)
        self.info_name = QLabel("-")
        self.info_name.setWordWrap(True)
        info_layout.addWidget(self.info_name, 0, 1)

        info_layout.addWidget(QLabel("Posttyp:"), 0, 2)
        self.info_type = QLabel("-")
        self.info_type.setWordWrap(True)
        info_layout.addWidget(self.info_type, 0, 3)

        info_layout.addWidget(QLabel("Längd:"), 1, 0)
        self.info_length = QLabel("-")
        self.info_length.setWordWrap(True)
        info_layout.addWidget(self.info_length, 1, 1)

        info_layout.addWidget(QLabel("Fält:"), 1, 2)
        self.info_fields = QLabel("-")
        self.info_fields.setWordWrap(True)
        info_layout.addWidget(self.info_fields, 1, 3)

        layout.addWidget(info_frame)

        self.fields_table = QTableWidget()
        self.fields_table.setColumnCount(6)
        self.fields_table.setHorizontalHeaderLabels(
            ["Namn", "Position", "Längd", "Typ", "Oblig.", "Default"]
        )
        self.fields_table.setAlternatingRowColors(True)
        self.fields_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fields_table.verticalHeader().setVisible(False)

        header = self.fields_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)

        layout.addWidget(self.fields_table, 1)

        btn_layout = QHBoxLayout()

        btn_add = QPushButton("➕ Lägg till fält")
        btn_add.clicked.connect(self._on_add_field)
        btn_layout.addWidget(btn_add)

        btn_edit = QPushButton("✏️ Redigera")
        btn_edit.clicked.connect(self._on_edit_field)
        btn_layout.addWidget(btn_edit)

        btn_remove = QPushButton("🗑️ Ta bort")
        btn_remove.clicked.connect(self._on_remove_field)
        btn_layout.addWidget(btn_remove)

        btn_layout.addStretch()

        btn_save = QPushButton("💾 Spara ändringar")
        save_font = btn_save.font()
        save_font.setBold(True)
        btn_save.setFont(save_font)
        btn_save.clicked.connect(self._on_save_spec)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)
        return widget

    def _create_test_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        input_group = QGroupBox("Testvärden (JSON)")
        input_layout = QVBoxLayout(input_group)

        self.test_input = QPlainTextEdit()
        self.test_input.setPlaceholderText('{\n  "field_name": "value"\n}')
        self.test_input.setMaximumHeight(150)
        input_layout.addWidget(self.test_input)

        btn_generate = QPushButton("▶️ Generera post")
        btn_generate.clicked.connect(self._on_generate_test)
        input_layout.addWidget(btn_generate)

        layout.addWidget(input_group)

        output_group = QGroupBox("Genererad post")
        output_layout = QVBoxLayout(output_group)

        self.test_output = QPlainTextEdit()
        self.test_output.setReadOnly(True)
        mono_font = QFont("Courier New")
        self.test_output.setFont(mono_font)
        output_layout.addWidget(self.test_output)

        self.length_label = QLabel("Längd: -")
        self.length_label.setWordWrap(True)
        output_layout.addWidget(self.length_label)

        layout.addWidget(output_group, 1)
        return widget

    def refresh(self) -> None:
        self.spec_list.clear()

        for spec in self.service.get_all():
            item = QListWidgetItem(f"{spec.post_type}: {spec.name}")
            item.setData(Qt.UserRole, spec.post_type)
            self.spec_list.addItem(item)

    def _show_spec(self, spec: PostSpec) -> None:
        self._current_spec = spec

        self.info_name.setText(spec.name)
        self.info_type.setText(spec.post_type)
        self.info_length.setText(str(spec.total_length))
        self.info_fields.setText(str(len(spec.fields)))

        self.fields_table.setRowCount(0)

        for field_spec in spec.fields:
            row = self.fields_table.rowCount()
            self.fields_table.insertRow(row)

            self.fields_table.setItem(row, 0, QTableWidgetItem(field_spec.name))
            self.fields_table.setItem(row, 1, QTableWidgetItem(str(field_spec.position)))
            self.fields_table.setItem(row, 2, QTableWidgetItem(str(field_spec.length)))
            self.fields_table.setItem(row, 3, QTableWidgetItem(field_spec.field_type))
            self.fields_table.setItem(row, 4, QTableWidgetItem("✓" if field_spec.required else ""))
            self.fields_table.setItem(row, 5, QTableWidgetItem(field_spec.default))

        template = {field_spec.name: field_spec.default or "" for field_spec in spec.fields}
        self.test_input.setPlainText(json.dumps(template, indent=2, ensure_ascii=False))

    def _on_spec_selected(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        _ = previous
        if not current:
            return

        post_type = current.data(Qt.UserRole)
        spec = self.service.get(post_type)
        if spec:
            self._show_spec(spec)

    def _on_load_file(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Ladda postbeskrivning",
            "",
            "Alla stödda (*.json *.xlsx *.xls *.csv);;JSON (*.json);;Excel (*.xlsx *.xls);;CSV (*.csv)",
        )

        if filepath:
            spec = self.service.load_from_file(Path(filepath))
            if spec:
                self.refresh()
                QMessageBox.information(
                    self,
                    "Laddad",
                    f"Laddade: {spec.name}\nTyp: {spec.post_type}\nFält: {len(spec.fields)}",
                )

    def _on_new_spec(self) -> None:
        dialog = NewSpecDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()

            spec = PostSpec(
                name=data["name"],
                post_type=data["post_type"],
                total_length=data["total_length"],
                description=data.get("description", ""),
                fields=[],
            )

            self.service.add(spec)
            self.refresh()

    def _on_delete_spec(self) -> None:
        item = self.spec_list.currentItem()
        if not item:
            return

        post_type = item.data(Qt.UserRole)

        reply = QMessageBox.question(
            self,
            "Bekräfta",
            f"Ta bort posttyp {post_type}?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.service.delete(post_type)
            self.refresh()

    def _on_add_field(self) -> None:
        if not self._current_spec:
            return

        dialog = FieldDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            field_spec = FieldSpec.from_dict(data)
            self._current_spec.fields.append(field_spec)
            self._show_spec(self._current_spec)

    def _on_edit_field(self) -> None:
        row = self.fields_table.currentRow()
        if row < 0 or not self._current_spec:
            return

        field_spec = self._current_spec.fields[row]

        dialog = FieldDialog(self, field_spec)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self._current_spec.fields[row] = FieldSpec.from_dict(data)
            self._show_spec(self._current_spec)

    def _on_remove_field(self) -> None:
        row = self.fields_table.currentRow()
        if row < 0 or not self._current_spec:
            return

        del self._current_spec.fields[row]
        self._show_spec(self._current_spec)

    def _on_save_spec(self) -> None:
        if not self._current_spec:
            return

        is_valid, errors = self._current_spec.validate()
        if not is_valid:
            QMessageBox.warning(self, "Valideringsfel", "\n".join(errors[:10]))

        self.service.add(self._current_spec)
        QMessageBox.information(self, "Sparat", f"Sparade: {self._current_spec.name}")

    def _on_generate_test(self) -> None:
        if not self._current_spec:
            return

        try:
            values = json.loads(self.test_input.toPlainText())
        except json.JSONDecodeError as exc:
            self.test_output.setPlainText(f"JSON-fel: {exc}")
            return

        post, warnings = self._current_spec.generate(values)

        output_lines = [post]
        if warnings:
            output_lines.append("")
            output_lines.append("Varningar:")
            output_lines.extend(f"  - {warning}" for warning in warnings)

        self.test_output.setPlainText("\n".join(output_lines))
        self.length_label.setText(f"Längd: {len(post)} tecken")


class NewSpecDialog(QDialog):
    """Dialog för ny specifikation."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Ny postbeskrivning")
        self.setModal(True)
        self.setMinimumWidth(400)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QGridLayout()

        form.addWidget(QLabel("Namn:"), 0, 0)
        self.name_input = QLineEdit()
        form.addWidget(self.name_input, 0, 1)

        form.addWidget(QLabel("Posttyp:"), 1, 0)
        self.type_input = QLineEdit()
        self.type_input.setPlaceholderText("T.ex. 28, 45, 99")
        form.addWidget(self.type_input, 1, 1)

        form.addWidget(QLabel("Total längd:"), 2, 0)
        self.length_input = QSpinBox()
        self.length_input.setRange(1, 10000)
        self.length_input.setValue(2500)
        form.addWidget(self.length_input, 2, 1)

        form.addWidget(QLabel("Beskrivning:"), 3, 0)
        self.desc_input = QLineEdit()
        form.addWidget(self.desc_input, 3, 1)

        layout.addLayout(form)

        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Preset:"))

        for preset_name, preset_length in STANDARD_POST_LENGTHS.items():
            btn = QPushButton(f"{preset_name} ({preset_length})")
            btn.clicked.connect(
                lambda checked=False, value=preset_length: self.length_input.setValue(value)
            )
            preset_layout.addWidget(btn)

        preset_layout.addStretch()
        layout.addLayout(preset_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Validering", "Namn krävs")
            return
        if not self.type_input.text().strip():
            QMessageBox.warning(self, "Validering", "Posttyp krävs")
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        return {
            "name": self.name_input.text().strip(),
            "post_type": self.type_input.text().strip(),
            "total_length": self.length_input.value(),
            "description": self.desc_input.text().strip(),
        }


class FieldDialog(QDialog):
    """Dialog för fältdefinition."""

    def __init__(self, parent: QWidget, field_spec: Optional[FieldSpec] = None):
        super().__init__(parent)
        self.setWindowTitle("Fältdefinition")
        self.setModal(True)
        self.setMinimumWidth(450)

        self._field_spec = field_spec
        self._setup_ui()

        if field_spec:
            self._populate(field_spec)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QGridLayout()

        form.addWidget(QLabel("Namn:"), 0, 0)
        self.name_input = QLineEdit()
        form.addWidget(self.name_input, 0, 1)

        form.addWidget(QLabel("Position:"), 1, 0)
        self.pos_input = QSpinBox()
        self.pos_input.setRange(1, 10000)
        form.addWidget(self.pos_input, 1, 1)

        form.addWidget(QLabel("Längd:"), 2, 0)
        self.length_input = QSpinBox()
        self.length_input.setRange(1, 1000)
        form.addWidget(self.length_input, 2, 1)

        form.addWidget(QLabel("Typ:"), 3, 0)
        self.type_combo = QComboBox()
        self.type_combo.addItems(FieldType.choices())
        form.addWidget(self.type_combo, 3, 1)

        form.addWidget(QLabel("Justering:"), 4, 0)
        self.align_combo = QComboBox()
        self.align_combo.addItems(Alignment.choices())
        form.addWidget(self.align_combo, 4, 1)

        form.addWidget(QLabel("Padding:"), 5, 0)
        self.pad_combo = QComboBox()
        self.pad_combo.addItems(["Mellanslag", "Nolla"])
        form.addWidget(self.pad_combo, 5, 1)

        self.required_check = QCheckBox("Obligatoriskt")
        self.required_check.setChecked(True)
        form.addWidget(self.required_check, 6, 1)

        form.addWidget(QLabel("Default:"), 7, 0)
        self.default_input = QLineEdit()
        form.addWidget(self.default_input, 7, 1)

        form.addWidget(QLabel("Beskrivning:"), 8, 0)
        self.desc_input = QLineEdit()
        form.addWidget(self.desc_input, 8, 1)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, field_spec: FieldSpec) -> None:
        self.name_input.setText(field_spec.name)
        self.pos_input.setValue(field_spec.position)
        self.length_input.setValue(field_spec.length)

        idx = self.type_combo.findText(field_spec.field_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        idx = self.align_combo.findText(field_spec.alignment)
        if idx >= 0:
            self.align_combo.setCurrentIndex(idx)

        self.pad_combo.setCurrentIndex(0 if field_spec.pad_char == " " else 1)
        self.required_check.setChecked(field_spec.required)
        self.default_input.setText(field_spec.default)
        self.desc_input.setText(field_spec.description)

    def _validate_and_accept(self) -> None:
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Validering", "Namn krävs")
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        return {
            "name": self.name_input.text().strip(),
            "position": self.pos_input.value(),
            "length": self.length_input.value(),
            "field_type": self.type_combo.currentText(),
            "alignment": self.align_combo.currentText(),
            "pad_char": " " if self.pad_combo.currentIndex() == 0 else "0",
            "required": self.required_check.isChecked(),
            "default": self.default_input.text(),
            "description": self.desc_input.text().strip(),
        }


__all__ = [
    "Plugin",
    "PostSpecService",
    "PostSpec",
    "FieldSpec",
    "FieldType",
    "Alignment",
    "PadChar",
]