# -*- coding: utf-8 -*-
# core/exceptions.py
"""
Centraliserade exceptions för Transportstyrelsen
Fordonsregistreringssystem v1.1.0.

Hierarki:
    CoreError (bas för alla)
    ├── PluginError
    │   ├── PluginLoadError
    │   ├── PluginInitError
    │   ├── PluginActivationError
    │   └── DependencyError
    ├── EventError
    │   ├── EventEmitError
    │   └── EventSubscriptionError
    ├── ConfigError (alias: ConfigurationError)
    │   ├── ConfigNotFoundError
    │   ├── ConfigValidationError
    │   └── ConfigParseError
    ├── ValidationError (GENERELL VALIDERING)
    │   ├── FieldValidationError
    │   ├── FormatValidationError
    │   ├── RangeValidationError
    │   └── UniqueConstraintError
    ├── BatchValidationError (samling av ValidationError)
    ├── DataError
    │   ├── VINValidationError
    │   ├── ImportError_ (alias: DataImportError)
    │   ├── ExportError
    │   ├── MatchingError
    │   └── MappingError
    └── FileOperationError
        ├── FileLockedError
        └── FileNotFoundError_

Användning:
    from core.exceptions import (
        PluginLoadError, DependencyError, ValidationError,
    )

    try:
        plugin = loader.load("my_plugin")
    except DependencyError as e:
        _log.error("Missing dependencies: %s", e.missing)
    except PluginLoadError as e:
        _log.error("Failed to load %s: %s", e.plugin_name, e)

    # Validering
    try:
        validate_color_code(code)
    except ValidationError as e:
        _log.warning("Ogiltigt värde för %s: %s", e.field, e.message)

FÖRÄNDRINGAR v1.1.0:
    - NY: ConfigurationError = ConfigError (bakåtkompatibelt alias,
      krävs av core/__init__.py v3.1.0 lazy-importtabell)
    - NY: VERSION/AUTHOR-konstanter + get_copyright_string()
      (dynamiskt år enligt spec)
    - Hierarki-docstring kompletterad (UniqueConstraintError,
      BatchValidationError, MappingError, FileOperationError-grenen)
    - Onödiga f-strängar utan platshållare borttagna
    - Oanvänd import (Tuple) borttagen

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from core.plugin_base import PluginBase


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "1.1.0"
AUTHOR: Final[str] = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# BASE EXCEPTION
# ══════════════════════════════════════════════════════════════════════════════

class CoreError(Exception):
    """
    Bas-exception för alla systemfel.

    Attributes:
        message: Felmeddelande
        details: Extra information för debugging
        error_code: Valfri felkod för kategorisering

    Exempel:
        raise CoreError("Something went wrong", details={"input": data})
    """

    def __init__(
        self,
        message: str = "An error occurred",
        *,
        details: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None
    ):
        self.message = message
        self.details = details or {}
        self.error_code = error_code
        super().__init__(self.message)

    def __str__(self) -> str:
        base = self.message
        if self.error_code:
            base = f"[{self.error_code}] {base}"
        return base

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"error_code={self.error_code!r}, "
            f"details={self.details!r})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict för logging/serialisering."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details
        }


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN ERRORS
# ══════════════════════════════════════════════════════════════════════════════

class PluginError(CoreError):
    """
    Bas-exception för plugin-relaterade fel.

    Attributes:
        plugin_name: Namnet på pluginen som orsakade felet
    """

    def __init__(
        self,
        message: str,
        plugin_name: Optional[str] = None,
        **kwargs
    ):
        self.plugin_name = plugin_name
        super().__init__(message, **kwargs)
        self.details["plugin_name"] = plugin_name

    def __str__(self) -> str:
        if self.plugin_name:
            return f"[Plugin: {self.plugin_name}] {self.message}"
        return self.message


class PluginLoadError(PluginError):
    """
    Fel vid laddning av plugin.

    Exempel:
        raise PluginLoadError(
            "Could not import module",
            plugin_name="sap_import",
            plugin_path=Path("plugins/sap_import"),
            original_error=e
        )
    """

    def __init__(
        self,
        message: str,
        plugin_name: Optional[str] = None,
        *,
        plugin_path: Optional[Path] = None,
        original_error: Optional[Exception] = None,
        **kwargs
    ):
        self.plugin_path = plugin_path
        self.original_error = original_error

        super().__init__(
            message,
            plugin_name=plugin_name,
            error_code="PLUGIN_LOAD_ERROR",
            **kwargs
        )

        self.details["plugin_path"] = (
            str(plugin_path) if plugin_path else None
        )
        self.details["original_error"] = (
            str(original_error) if original_error else None
        )


class PluginInitError(PluginError):
    """
    Fel vid initiering av plugin.

    Exempel:
        raise PluginInitError(
            "Database connection failed",
            plugin_name="sap_import",
            phase="database_setup"
        )
    """

    def __init__(
        self,
        message: str,
        plugin_name: Optional[str] = None,
        *,
        phase: Optional[str] = None,
        **kwargs
    ):
        self.phase = phase

        super().__init__(
            message,
            plugin_name=plugin_name,
            error_code="PLUGIN_INIT_ERROR",
            **kwargs
        )

        self.details["phase"] = phase


class PluginActivationError(PluginError):
    """
    Fel vid aktivering av plugin.

    Exempel:
        raise PluginActivationError(
            "Required service unavailable",
            plugin_name="ts_file_generator",
            required_service="sap_import"
        )
    """

    def __init__(
        self,
        message: str,
        plugin_name: Optional[str] = None,
        *,
        required_service: Optional[str] = None,
        **kwargs
    ):
        self.required_service = required_service

        super().__init__(
            message,
            plugin_name=plugin_name,
            error_code="PLUGIN_ACTIVATION_ERROR",
            **kwargs
        )

        self.details["required_service"] = required_service


class DependencyError(PluginError):
    """
    Fel vid dependency resolution.

    Attributes:
        missing: Lista med saknade dependencies
        circular: Lista med circular dependencies (om detekterade)

    Exempel:
        raise DependencyError(
            "Missing required plugins",
            plugin_name="ts_file_generator",
            missing=["sap_import", "core_logger"],
            circular=None
        )
    """

    def __init__(
        self,
        message: str,
        plugin_name: Optional[str] = None,
        *,
        missing: Optional[List[str]] = None,
        circular: Optional[List[str]] = None,
        **kwargs
    ):
        self.missing = missing or []
        self.circular = circular or []

        super().__init__(
            message,
            plugin_name=plugin_name,
            error_code="DEPENDENCY_ERROR",
            **kwargs
        )

        self.details["missing_dependencies"] = self.missing
        self.details["circular_dependencies"] = self.circular

    def __str__(self) -> str:
        base = super().__str__()
        if self.missing:
            base += f" (missing: {', '.join(self.missing)})"
        if self.circular:
            base += f" (circular: {' → '.join(self.circular)})"
        return base


# ══════════════════════════════════════════════════════════════════════════════
# EVENT ERRORS
# ══════════════════════════════════════════════════════════════════════════════

class EventError(CoreError):
    """Bas-exception för event-relaterade fel."""

    def __init__(
        self,
        message: str,
        event_name: Optional[str] = None,
        **kwargs
    ):
        self.event_name = event_name
        super().__init__(message, **kwargs)
        self.details["event_name"] = event_name


class EventEmitError(EventError):
    """
    Fel vid emittering av event.

    Exempel:
        raise EventEmitError(
            "Callback raised exception",
            event_name="vehicle:matched",
            callback_name="handle_match",
            original_error=e
        )
    """

    def __init__(
        self,
        message: str,
        event_name: Optional[str] = None,
        *,
        callback_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
        **kwargs
    ):
        self.callback_name = callback_name
        self.original_error = original_error

        super().__init__(
            message,
            event_name=event_name,
            error_code="EVENT_EMIT_ERROR",
            **kwargs
        )

        self.details["callback_name"] = callback_name
        self.details["original_error"] = (
            str(original_error) if original_error else None
        )


class EventSubscriptionError(EventError):
    """
    Fel vid prenumeration på event.

    Exempel:
        raise EventSubscriptionError(
            "Duplicate subscription not allowed",
            event_name="vehicle:matched"
        )
    """

    def __init__(
        self,
        message: str,
        event_name: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            message,
            event_name=event_name,
            error_code="EVENT_SUBSCRIPTION_ERROR",
            **kwargs
        )


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION ERRORS
# ══════════════════════════════════════════════════════════════════════════════

class ConfigError(CoreError):
    """Bas-exception för konfigurationsfel."""

    def __init__(
        self,
        message: str,
        config_path: Optional[Path] = None,
        **kwargs
    ):
        self.config_path = config_path
        super().__init__(message, **kwargs)
        self.details["config_path"] = (
            str(config_path) if config_path else None
        )


class ConfigNotFoundError(ConfigError):
    """
    Konfigurationsfil hittades inte.

    Exempel:
        raise ConfigNotFoundError(
            "Configuration file does not exist",
            config_path=Path("config.json"),
            searched_paths=[Path("."), Path("core/")]
        )
    """

    def __init__(
        self,
        message: str,
        config_path: Optional[Path] = None,
        *,
        searched_paths: Optional[List[Path]] = None,
        **kwargs
    ):
        self.searched_paths = searched_paths or []

        super().__init__(
            message,
            config_path=config_path,
            error_code="CONFIG_NOT_FOUND",
            **kwargs
        )

        self.details["searched_paths"] = [
            str(p) for p in self.searched_paths
        ]


class ConfigValidationError(ConfigError):
    """
    Valideringsfel i konfiguration.

    Exempel:
        raise ConfigValidationError(
            "Invalid value for 'database.port'",
            config_path=Path("config.json"),
            field="database.port",
            value="not-a-number",
            expected_type="int"
        )
    """

    def __init__(
        self,
        message: str,
        config_path: Optional[Path] = None,
        *,
        field: Optional[str] = None,
        value: Any = None,
        expected_type: Optional[str] = None,
        **kwargs
    ):
        self.field = field
        self.value = value
        self.expected_type = expected_type

        super().__init__(
            message,
            config_path=config_path,
            error_code="CONFIG_VALIDATION_ERROR",
            **kwargs
        )

        self.details["field"] = field
        self.details["value"] = repr(value)
        self.details["expected_type"] = expected_type


class ConfigParseError(ConfigError):
    """
    Fel vid parsing av konfigurationsfil.

    Exempel:
        raise ConfigParseError(
            "Invalid JSON syntax",
            config_path=Path("config.json"),
            line=42,
            column=15,
            original_error=json_error
        )
    """

    def __init__(
        self,
        message: str,
        config_path: Optional[Path] = None,
        *,
        line: Optional[int] = None,
        column: Optional[int] = None,
        original_error: Optional[Exception] = None,
        **kwargs
    ):
        self.line = line
        self.column = column
        self.original_error = original_error

        super().__init__(
            message,
            config_path=config_path,
            error_code="CONFIG_PARSE_ERROR",
            **kwargs
        )

        self.details["line"] = line
        self.details["column"] = column
        self.details["original_error"] = (
            str(original_error) if original_error else None
        )


# Bakåtkompatibelt alias (NY v1.1.0) — krävs av core/__init__.py
# v3.1.0 lazy-importtabell samt äldre kod som importerar
# ConfigurationError.
ConfigurationError = ConfigError


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION ERRORS (GENERELLA)
# ══════════════════════════════════════════════════════════════════════════════

class ValidationError(CoreError):
    """
    Generellt valideringsfel för data.

    Används av plugins som:
    - data_mapping: Validering av mappningar
    - colors_manager: Validering av färgkoder
    - ts_spec_import: Validering av TS-specifikationer
    - color_import: Validering av färgdata
    - buntpost: Validering av bunt-data

    Attributes:
        field: Fältnamnet som valideringen misslyckades för
        value: Det ogiltiga värdet
        constraint: Beskrivning av constraint som bröts
        expected: Förväntat värde/format

    Exempel:
        raise ValidationError(
            "Färgkod måste vara 3 tecken",
            field="color_code",
            value="AB",
            expected="3 alphanumeriska tecken",
            constraint="length == 3"
        )
    """

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        *,
        value: Any = None,
        expected: Optional[str] = None,
        constraint: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        self.field = field
        self.value = value
        self.expected = expected
        self.constraint = constraint

        super().__init__(
            message,
            error_code="VALIDATION_ERROR",
            details=details,
            **kwargs
        )

        self.details["field"] = field
        self.details["value"] = (
            repr(value) if value is not None else None
        )
        self.details["expected"] = expected
        self.details["constraint"] = constraint

    def __str__(self) -> str:
        parts = [self.message]

        if self.field:
            parts.insert(0, f"[{self.field}]")

        if self.expected:
            parts.append(f"(expected: {self.expected})")

        return " ".join(parts)

    @classmethod
    def required_field(cls, field: str) -> ValidationError:
        """Factory för obligatoriskt fält som saknas."""
        return cls(
            "Obligatoriskt fält saknas",
            field=field,
            constraint="required",
            expected="värde måste anges"
        )

    @classmethod
    def invalid_type(
        cls,
        field: str,
        value: Any,
        expected_type: str
    ) -> ValidationError:
        """Factory för fel typ."""
        return cls(
            "Fel datatyp",
            field=field,
            value=value,
            expected=expected_type,
            constraint=f"type == {expected_type}"
        )

    @classmethod
    def invalid_format(
        cls,
        field: str,
        value: Any,
        expected_format: str
    ) -> ValidationError:
        """Factory för fel format."""
        return cls(
            "Ogiltigt format",
            field=field,
            value=value,
            expected=expected_format,
            constraint="format"
        )

    @classmethod
    def out_of_range(
        cls,
        field: str,
        value: Any,
        min_val: Any = None,
        max_val: Any = None
    ) -> ValidationError:
        """Factory för värde utanför intervall."""
        if min_val is not None and max_val is not None:
            expected = f"{min_val} <= värde <= {max_val}"
        elif min_val is not None:
            expected = f"värde >= {min_val}"
        else:
            expected = f"värde <= {max_val}"

        return cls(
            "Värde utanför tillåtet intervall",
            field=field,
            value=value,
            expected=expected,
            constraint="range"
        )

    @classmethod
    def invalid_choice(
        cls,
        field: str,
        value: Any,
        valid_choices: List[Any]
    ) -> ValidationError:
        """Factory för ogiltigt val."""
        choices_str = ", ".join(repr(c) for c in valid_choices[:5])
        if len(valid_choices) > 5:
            choices_str += f", ... (+{len(valid_choices) - 5})"

        return cls(
            "Ogiltigt val",
            field=field,
            value=value,
            expected=f"ett av: {choices_str}",
            constraint="choice"
        )


class FieldValidationError(ValidationError):
    """
    Specifikt valideringsfel för ett enskilt fält.

    Exempel:
        raise FieldValidationError(
            "color_code",
            "XYZ",
            "Färgkoden finns inte i systemet"
        )
    """

    def __init__(
        self,
        field: str,
        value: Any,
        reason: str,
        **kwargs
    ):
        self.reason = reason
        super().__init__(
            reason,
            field=field,
            value=value,
            error_code="FIELD_VALIDATION_ERROR",
            **kwargs
        )


class FormatValidationError(ValidationError):
    """
    Valideringsfel för formatfel (regex, mönster, etc).

    Exempel:
        raise FormatValidationError(
            "VIN-nummer har ogiltigt format",
            field="vin",
            value="ABC123",
            pattern=r"^[A-HJ-NPR-Z0-9]{17}$",
            expected="17 tecken (bokstäver A-Z utom I,O,Q och siffror)"
        )
    """

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        *,
        value: Any = None,
        pattern: Optional[str] = None,
        expected: Optional[str] = None,
        **kwargs
    ):
        self.pattern = pattern

        super().__init__(
            message,
            field=field,
            value=value,
            expected=expected,
            error_code="FORMAT_VALIDATION_ERROR",
            **kwargs
        )

        self.details["pattern"] = pattern


class RangeValidationError(ValidationError):
    """
    Valideringsfel för värden utanför tillåtet intervall.

    Exempel:
        raise RangeValidationError(
            "Årsmodell utanför giltigt intervall",
            field="model_year",
            value=1899,
            min_value=1900,
            max_value=2030
        )
    """

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        *,
        value: Any = None,
        min_value: Any = None,
        max_value: Any = None,
        **kwargs
    ):
        self.min_value = min_value
        self.max_value = max_value

        # Bygg expected-sträng
        if min_value is not None and max_value is not None:
            expected = f"{min_value} - {max_value}"
        elif min_value is not None:
            expected = f">= {min_value}"
        elif max_value is not None:
            expected = f"<= {max_value}"
        else:
            expected = None

        super().__init__(
            message,
            field=field,
            value=value,
            expected=expected,
            error_code="RANGE_VALIDATION_ERROR",
            **kwargs
        )

        self.details["min_value"] = min_value
        self.details["max_value"] = max_value


class UniqueConstraintError(ValidationError):
    """
    Valideringsfel för duplicerade värden som måste vara unika.

    Exempel:
        raise UniqueConstraintError(
            "Färgkod existerar redan",
            field="color_code",
            value="A01",
            existing_record_id="colors/A01"
        )
    """

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        *,
        value: Any = None,
        existing_record_id: Optional[str] = None,
        **kwargs
    ):
        self.existing_record_id = existing_record_id

        super().__init__(
            message,
            field=field,
            value=value,
            constraint="unique",
            error_code="UNIQUE_CONSTRAINT_ERROR",
            **kwargs
        )

        self.details["existing_record_id"] = existing_record_id


# ══════════════════════════════════════════════════════════════════════════════
# DATA/BUSINESS ERRORS
# ══════════════════════════════════════════════════════════════════════════════

class DataError(CoreError):
    """Bas-exception för datahanteringsfel."""
    pass


class VINValidationError(DataError):
    """
    Fel vid validering av VIN-nummer.

    Attributes:
        vin: Det ogiltiga VIN-numret
        reason: Anledning till att det är ogiltigt

    Exempel:
        raise VINValidationError(
            "Invalid VIN format",
            vin="ABC123",
            reason="VIN must be exactly 17 characters"
        )
    """

    def __init__(
        self,
        message: str,
        vin: Optional[str] = None,
        *,
        reason: Optional[str] = None,
        **kwargs
    ):
        self.vin = vin
        self.reason = reason

        super().__init__(
            message,
            error_code="VIN_VALIDATION_ERROR",
            **kwargs
        )

        self.details["vin"] = vin
        self.details["reason"] = reason


class ImportError_(DataError):
    """
    Fel vid import av data.
    OBS: Namn med underscore för att undvika konflikt med builtin.

    Exempel:
        raise ImportError_(
            "Failed to read Excel file",
            source="dispatch_2024.xlsx",
            row=42,
            original_error=e
        )
    """

    def __init__(
        self,
        message: str,
        source: Optional[str] = None,
        *,
        row: Optional[int] = None,
        column: Optional[str] = None,
        original_error: Optional[Exception] = None,
        **kwargs
    ):
        self.source = source
        self.row = row
        self.column = column
        self.original_error = original_error

        super().__init__(
            message,
            error_code="IMPORT_ERROR",
            **kwargs
        )

        self.details["source"] = source
        self.details["row"] = row
        self.details["column"] = column
        self.details["original_error"] = (
            str(original_error) if original_error else None
        )


# Alias för bekvämlighet (undvik namn-konflikt med builtin ImportError)
DataImportError = ImportError_


class ExportError(DataError):
    """
    Fel vid export av data.

    Exempel:
        raise ExportError(
            "Failed to write TS file",
            destination="ut/TS0001.txt",
            reason="Disk full"
        )
    """

    def __init__(
        self,
        message: str,
        destination: Optional[str] = None,
        *,
        reason: Optional[str] = None,
        **kwargs
    ):
        self.destination = destination
        self.reason = reason

        super().__init__(
            message,
            error_code="EXPORT_ERROR",
            **kwargs
        )

        self.details["destination"] = destination
        self.details["reason"] = reason


class MatchingError(DataError):
    """
    Fel vid matchning av fordon mot SAP-data.

    Exempel:
        raise MatchingError(
            "No matching SAP record found",
            vin="WBA12345678901234",
            model_year="2024",
            strategies_tried=["vin_model_year", "vin_only", "etg_model_year"]
        )
    """

    def __init__(
        self,
        message: str,
        vin: Optional[str] = None,
        *,
        model_year: Optional[str] = None,
        strategies_tried: Optional[List[str]] = None,
        **kwargs
    ):
        self.vin = vin
        self.model_year = model_year
        self.strategies_tried = strategies_tried or []

        super().__init__(
            message,
            error_code="MATCHING_ERROR",
            **kwargs
        )

        self.details["vin"] = vin
        self.details["model_year"] = model_year
        self.details["strategies_tried"] = self.strategies_tried


class MappingError(DataError):
    """
    Fel vid datamappning.

    Används av data_mapping plugin.

    Exempel:
        raise MappingError(
            "Kunde inte mappa fordonsklass",
            source_field="vehicle_type",
            source_value="XYZ",
            target_field="ts_class"
        )
    """

    def __init__(
        self,
        message: str,
        source_field: Optional[str] = None,
        *,
        source_value: Any = None,
        target_field: Optional[str] = None,
        **kwargs
    ):
        self.source_field = source_field
        self.source_value = source_value
        self.target_field = target_field

        super().__init__(
            message,
            error_code="MAPPING_ERROR",
            **kwargs
        )

        self.details["source_field"] = source_field
        self.details["source_value"] = repr(source_value)
        self.details["target_field"] = target_field


# ══════════════════════════════════════════════════════════════════════════════
# FILE OPERATION ERRORS
# ══════════════════════════════════════════════════════════════════════════════

class FileOperationError(CoreError):
    """
    Bas-exception för filoperationsfel.

    Exempel:
        raise FileOperationError(
            "Cannot write to file",
            path=Path("ut/output.txt"),
            operation="write"
        )
    """

    def __init__(
        self,
        message: str,
        path: Optional[Path] = None,
        *,
        operation: Optional[str] = None,
        **kwargs
    ):
        self.path = path
        self.operation = operation

        super().__init__(
            message,
            error_code="FILE_OPERATION_ERROR",
            **kwargs
        )

        self.details["path"] = str(path) if path else None
        self.details["operation"] = operation


class FileLockedError(FileOperationError):
    """Fil är låst av annan process."""

    def __init__(
        self,
        message: str,
        path: Optional[Path] = None,
        **kwargs
    ):
        super().__init__(
            message,
            path=path,
            operation="access",
            error_code="FILE_LOCKED",
            **kwargs
        )


class FileNotFoundError_(FileOperationError):
    """
    Fil hittades inte.
    OBS: Underscore för att undvika konflikt med builtin.
    """

    def __init__(
        self,
        message: str,
        path: Optional[Path] = None,
        **kwargs
    ):
        super().__init__(
            message,
            path=path,
            operation="read",
            error_code="FILE_NOT_FOUND",
            **kwargs
        )


# ══════════════════════════════════════════════════════════════════════════════
# BATCH VALIDATION (för mass-validering)
# ══════════════════════════════════════════════════════════════════════════════

class BatchValidationError(CoreError):
    """
    Samling av flera valideringsfel.

    Används när man validerar många objekt och vill samla alla fel.

    Exempel:
        errors = BatchValidationError(
            "Validering misslyckades för 5 rader"
        )
        errors.add_error(ValidationError("Fel 1", field="a"))
        errors.add_error(ValidationError("Fel 2", field="b"))

        if errors.has_errors:
            raise errors
    """

    def __init__(
        self,
        message: str = "Multiple validation errors occurred",
        errors: Optional[List[ValidationError]] = None,
        **kwargs
    ):
        self.errors = errors or []

        super().__init__(
            message,
            error_code="BATCH_VALIDATION_ERROR",
            **kwargs
        )

    def add_error(
        self,
        error: Union[ValidationError, str],
        field: Optional[str] = None
    ):
        """Lägg till ett fel."""
        if isinstance(error, str):
            error = ValidationError(error, field=field)
        self.errors.append(error)
        self.details["error_count"] = len(self.errors)

    @property
    def has_errors(self) -> bool:
        """Returnera True om det finns fel."""
        return len(self.errors) > 0

    @property
    def error_count(self) -> int:
        """Antal fel."""
        return len(self.errors)

    def __str__(self) -> str:
        base = f"{self.message} ({len(self.errors)} errors)"
        if self.errors:
            error_lines = [f"  - {e}" for e in self.errors[:5]]
            if len(self.errors) > 5:
                error_lines.append(
                    f"  ... and {len(self.errors) - 5} more"
                )
            base += "\n" + "\n".join(error_lines)
        return base

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict med alla fel."""
        result = super().to_dict()
        result["errors"] = [e.to_dict() for e in self.errors]
        return result


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def format_exception_chain(exc: Exception, max_depth: int = 5) -> str:
    """
    Formatera en exception-kedja för logging.

    Args:
        exc: Exception att formatera
        max_depth: Max antal nivåer att visa

    Returns:
        Formaterad string
    """
    lines = []
    current: Optional[Exception] = exc
    depth = 0

    while current and depth < max_depth:
        prefix = "  " * depth
        exc_type = type(current).__name__

        if isinstance(current, CoreError):
            lines.append(f"{prefix}[{exc_type}] {current.message}")
            if current.error_code:
                lines.append(f"{prefix}  Code: {current.error_code}")
            if current.details:
                for key, value in current.details.items():
                    if value is not None:
                        lines.append(f"{prefix}  {key}: {value}")
        else:
            lines.append(f"{prefix}[{exc_type}] {str(current)}")

        current = current.__cause__ or current.__context__
        depth += 1

        if current:
            lines.append(f"{'  ' * depth}Caused by:")

    return "\n".join(lines)


def validate_or_raise(
    condition: bool,
    message: str,
    field: Optional[str] = None,
    error_class: type = ValidationError,
    **kwargs: Any
) -> None:
    """
    Hjälpfunktion för enkel validering.

    Exempel:
        validate_or_raise(
            len(vin) == 17, "VIN måste vara 17 tecken", field="vin",
        )
        validate_or_raise(
            value > 0, "Värde måste vara positivt", field="amount",
        )
    """
    if not condition:
        raise error_class(message, field=field, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Version
    "VERSION",
    "AUTHOR",
    "get_copyright_string",

    # Base
    "CoreError",

    # Plugin errors
    "PluginError",
    "PluginLoadError",
    "PluginInitError",
    "PluginActivationError",
    "DependencyError",

    # Event errors
    "EventError",
    "EventEmitError",
    "EventSubscriptionError",

    # Config errors
    "ConfigError",
    "ConfigurationError",  # Alias (NY v1.1.0)
    "ConfigNotFoundError",
    "ConfigValidationError",
    "ConfigParseError",

    # Validation errors (GENERELLA - används av många plugins)
    "ValidationError",
    "FieldValidationError",
    "FormatValidationError",
    "RangeValidationError",
    "UniqueConstraintError",
    "BatchValidationError",

    # Data errors
    "DataError",
    "VINValidationError",
    "ImportError_",
    "DataImportError",  # Alias
    "ExportError",
    "MatchingError",
    "MappingError",

    # File errors
    "FileOperationError",
    "FileLockedError",
    "FileNotFoundError_",

    # Helpers
    "format_exception_chain",
    "validate_or_raise",
]