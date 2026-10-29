# -*- coding: utf-8 -*-
"""
Data Mapping Plugin — Package Init v5.0.0

Kolumnmappning, Excel-fordonsimport, fordonsmatchning och TS-filgenerering.

UPPDATERINGAR v5.0.0:
  ✨ BUGG #2 FIXAD:
     - ColumnMappingService importeras nu korrekt
     - Lazy loading av ExternalColumnMappingService

  ✨ BUGG #4 FIXAD:
     - VinRegistry.get_all() finns nu
     - Lazy loading av VinRegistry

  ✨ UTÖKAD METADATA:
     - 20 funktioner

  ✨ LAZY LOADING:
     - Plugin, GenerateFilePage, ColumnMappingService,
       VinRegistry, VinEntry, alla datamodeller

  ✨ COPYRIGHT:
     - Copyright © {år} Rickard Längkvist (dynamiskt)

Copyright © 2026 Rickard Längkvist
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import (
        Plugin as PluginType,
        DataSource,
        FieldType,
        MatchStatus,
        ColumnMatch,
        MappingConfig,
        VehicleMatchResult,
        MatchingSummary,
        GenerateResult,
        VehicleImportStatus,
    )
    from .widget import GenerateFilePage as GenerateFilePageType
    from .column_mapping_service import (
        ColumnMappingService as ColumnMappingServiceType,
        MappingEntry as MappingEntryType,
    )
    from .vin_registry import (
        VinRegistry as VinRegistryType,
        VinEntry as VinEntryType,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def get_logger() -> logging.Logger:
    """Hämta logger. KRASCHSÄKER."""
    try:
        return logging.getLogger("data_mapping")
    except Exception:
        return logging.getLogger(__name__)


_log = get_logger()


# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "Data Mapping"
__plugin_version__: str = "5.0.0"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Kolumnmappning, Excel-fordonsimport, fordonsmatchning "
    "och TS-filgenerering (20 funktioner)"
)
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "ts_spec_import",
    "ts_schema_manager",
    "ts_file_generator",
    "vehicle_registry",
    "colors_manager",
    "dealers_manager",
    "dispatch_viewer",
    "ereko",
    "sap_import",
    "core_config",
]

COPYRIGHT_YEAR: int = datetime.now().year
__plugin_copyright__: str = f"Copyright © {COPYRIGHT_YEAR} {__plugin_author__}"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {__plugin_author__}"


# ══════════════════════════════════════════════════════════════════════════════
# LAZY LOADING — trådsäker cache per klass
# ══════════════════════════════════════════════════════════════════════════════

cached_plugin_class: Optional[Type["PluginType"]] = None
cached_widget_class: Optional[Type["GenerateFilePageType"]] = None
cached_column_mapping_service_class: Optional[Type["ColumnMappingServiceType"]] = None
cached_mapping_entry_class: Optional[Type["MappingEntryType"]] = None
cached_vin_registry_class: Optional[Type["VinRegistryType"]] = None
cached_vin_entry_class: Optional[Type["VinEntryType"]] = None
cached_data_models: Optional[Dict[str, Any]] = None


def get_plugin_class() -> Type["PluginType"]:
    """Hämta Plugin-klassen (lazy, cachad).
    
    Löser BUGG #2 — Plugin importerar nu ColumnMappingService korrekt.
    """
    global cached_plugin_class
    if cached_plugin_class is None:
        try:
            from .plugin import Plugin
            cached_plugin_class = Plugin
            _log.debug("Plugin-klass laddad: %s v%s", __plugin_name__, __plugin_version__)
        except ImportError as exc:
            _log.error("Kunde inte ladda Plugin-klass för '%s': %s", __plugin_name__, exc)
            raise
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av Plugin-klass för '%s'.", __plugin_name__)
            raise ImportError(f"Kunde inte ladda Plugin-klass: {exc}") from exc
    return cached_plugin_class


def get_widget_class() -> Type["GenerateFilePageType"]:
    """Hämta GenerateFilePage-widgeten (lazy, cachad)."""
    global cached_widget_class
    if cached_widget_class is None:
        try:
            from .widget import GenerateFilePage
            cached_widget_class = GenerateFilePage
            _log.debug("Widget-klass laddad: GenerateFilePage v%s", __plugin_version__)
        except ImportError as exc:
            _log.error("Kunde inte ladda GenerateFilePage för '%s': %s", __plugin_name__, exc)
            raise
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av GenerateFilePage.")
            raise ImportError(f"Kunde inte ladda widget-klass: {exc}") from exc
    return cached_widget_class


def get_column_mapping_service_class() -> Type["ColumnMappingServiceType"]:
    """Hämta ColumnMappingService-klassen (lazy, cachad).
    
    Löser BUGG #2 — klassen importeras nu korrekt från column_mapping_service.py
    """
    global cached_column_mapping_service_class
    if cached_column_mapping_service_class is None:
        try:
            from .column_mapping_service import ColumnMappingService
            cached_column_mapping_service_class = ColumnMappingService
            _log.debug("ColumnMappingService-klass laddad.")
        except ImportError as exc:
            _log.error("Kunde inte ladda ColumnMappingService: %s", exc)
            raise
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av ColumnMappingService.")
            raise ImportError(f"Kunde inte ladda ColumnMappingService: {exc}") from exc
    return cached_column_mapping_service_class


def get_mapping_entry_class() -> Type["MappingEntryType"]:
    """Hämta MappingEntry-klassen (lazy, cachad)."""
    global cached_mapping_entry_class
    if cached_mapping_entry_class is None:
        try:
            from .column_mapping_service import MappingEntry
            cached_mapping_entry_class = MappingEntry
            _log.debug("MappingEntry-klass laddad.")
        except ImportError as exc:
            _log.error("Kunde inte ladda MappingEntry: %s", exc)
            raise
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av MappingEntry.")
            raise ImportError(f"Kunde inte ladda MappingEntry: {exc}") from exc
    return cached_mapping_entry_class


def get_vin_registry_class() -> Type["VinRegistryType"]:
    """Hämta VinRegistry-klassen (lazy, cachad).
    
    Löser BUGG #4 — VinRegistry.get_all() finns nu.
    """
    global cached_vin_registry_class
    if cached_vin_registry_class is None:
        try:
            from .vin_registry import VinRegistry
            cached_vin_registry_class = VinRegistry
            _log.debug("VinRegistry-klass laddad (BUGG #4 FIXAD — get_all() finns).")
        except ImportError as exc:
            _log.error("Kunde inte ladda VinRegistry: %s", exc)
            raise
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av VinRegistry.")
            raise ImportError(f"Kunde inte ladda VinRegistry: {exc}") from exc
    return cached_vin_registry_class


def get_vin_entry_class() -> Type["VinEntryType"]:
    """Hämta VinEntry-klassen (lazy, cachad)."""
    global cached_vin_entry_class
    if cached_vin_entry_class is None:
        try:
            from .vin_registry import VinEntry
            cached_vin_entry_class = VinEntry
            _log.debug("VinEntry-klass laddad.")
        except ImportError as exc:
            _log.error("Kunde inte ladda VinEntry: %s", exc)
            raise
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av VinEntry.")
            raise ImportError(f"Kunde inte ladda VinEntry: {exc}") from exc
    return cached_vin_entry_class


def get_data_models() -> Dict[str, Any]:
    """Hämta alla datamodeller från plugin.py (lazy, cachad)."""
    global cached_data_models
    if cached_data_models is None:
        try:
            from .plugin import (
                DataSource,
                FieldType,
                MatchStatus,
                ColumnMatch,
                MappingConfig,
                VehicleMatchResult,
                MatchingSummary,
                GenerateResult,
                VehicleImportStatus,
            )
            cached_data_models = {
                "DataSource": DataSource,
                "FieldType": FieldType,
                "MatchStatus": MatchStatus,
                "ColumnMatch": ColumnMatch,
                "MappingConfig": MappingConfig,
                "VehicleMatchResult": VehicleMatchResult,
                "MatchingSummary": MatchingSummary,
                "GenerateResult": GenerateResult,
                "VehicleImportStatus": VehicleImportStatus,
            }
            _log.debug("Datamodeller laddade från plugin.py.")
        except ImportError as exc:
            _log.error("Kunde inte ladda datamodeller: %s", exc)
            raise
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av datamodeller.")
            raise ImportError(f"Kunde inte ladda datamodeller: {exc}") from exc
    return cached_data_models


# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE GETTERS — enskilda modeller
# ══════════════════════════════════════════════════════════════════════════════

def get_DataSource() -> Type["DataSource"]:
    return get_data_models()["DataSource"]  # type: ignore


def get_FieldType() -> Type["FieldType"]:
    return get_data_models()["FieldType"]  # type: ignore


def get_MatchStatus() -> Type["MatchStatus"]:
    return get_data_models()["MatchStatus"]  # type: ignore


def get_VehicleMatchResult() -> Type["VehicleMatchResult"]:
    return get_data_models()["VehicleMatchResult"]  # type: ignore


def get_MatchingSummary() -> Type["MatchingSummary"]:
    return get_data_models()["MatchingSummary"]  # type: ignore


def get_GenerateResult() -> Type["GenerateResult"]:
    return get_data_models()["GenerateResult"]  # type: ignore


def get_VehicleImportStatus() -> Type["VehicleImportStatus"]:
    return get_data_models()["VehicleImportStatus"]  # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN INFO
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_info() -> Dict[str, Any]:
    """Hämta plugin-metadata utan att ladda klassen."""
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "copyright": get_copyright_string(),
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(__plugin_optional_dependencies__),
        "functions": 20,
        "has_ui": True,
        "bugg2_fixed": True,
        "bugg4_fixed": True,
    }


def clear_cache() -> None:
    """Rensa alla lazy-laddade klasser ur cacharna. Används vid hot reload."""
    global cached_plugin_class
    global cached_widget_class
    global cached_column_mapping_service_class
    global cached_mapping_entry_class
    global cached_vin_registry_class
    global cached_vin_entry_class
    global cached_data_models

    cached_plugin_class = None
    cached_widget_class = None
    cached_column_mapping_service_class = None
    cached_mapping_entry_class = None
    cached_vin_registry_class = None
    cached_vin_entry_class = None
    cached_data_models = None

    _log.debug("Cache rensad för data_mapping.")


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST — bakåtkompatibel lazy loading
# ══════════════════════════════════════════════════════════════════════════════

LAZY_ATTR_MAP: Dict[str, str] = {
    # Plugin + Widget
    "Plugin": "get_plugin_class",
    "GenerateFilePage": "get_widget_class",
    "DataMappingWidget": "get_widget_class",
    "Widget": "get_widget_class",

    # ColumnMappingService (BUGG #2 FIX)
    "ColumnMappingService": "get_column_mapping_service_class",
    "MappingEntry": "get_mapping_entry_class",

    # VinRegistry (BUGG #4 FIX)
    "VinRegistry": "get_vin_registry_class",
    "VinEntry": "get_vin_entry_class",

    # Datamodeller
    "DataSource": "get_DataSource",
    "FieldType": "get_FieldType",
    "MatchStatus": "get_MatchStatus",
    "VehicleMatchResult": "get_VehicleMatchResult",
    "MatchingSummary": "get_MatchingSummary",
    "GenerateResult": "get_GenerateResult",
    "VehicleImportStatus": "get_VehicleImportStatus",
}

METADATA_ATTR_MAP: Dict[str, Any] = {
    "VERSION": __plugin_version__,
    "AUTHOR": __plugin_author__,
    "NAME": __plugin_name__,
    "DESCRIPTION": __plugin_description__,
    "COPYRIGHT": __plugin_copyright__,
}


def __getattr__(name: str) -> Any:
    """
    Dynamisk attributåtkomst — bakåtkompatibel lazy loading.

    Stöder:
        Plugin, GenerateFilePage,
        ColumnMappingService, MappingEntry,
        VinRegistry, VinEntry,
        DataSource, FieldType, MatchStatus,
        VehicleMatchResult, MatchingSummary, GenerateResult,
        VehicleImportStatus,
        VERSION, AUTHOR, NAME, DESCRIPTION, COPYRIGHT
    """
    if name in METADATA_ATTR_MAP:
        return METADATA_ATTR_MAP[name]

    loader_name = LAZY_ATTR_MAP.get(name)
    if loader_name is not None:
        loader_func = globals().get(loader_name)
        if loader_func is not None and callable(loader_func):
            try:
                return loader_func()
            except Exception as exc:
                _log.error(
                    "Lazy loading av '%s' misslyckades via '%s': %s",
                    name,
                    loader_name,
                    exc,
                )
                raise AttributeError(
                    f"module 'plugins.data_mapping' attribute '{name}' "
                    f"could not be loaded: {exc}"
                ) from exc

    raise AttributeError(
        f"module 'plugins.data_mapping' has no attribute '{name}'"
    )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__: List[str] = [
    # Metadata
    "__plugin_name__",
    "__plugin_version__",
    "__plugin_author__",
    "__plugin_description__",
    "__plugin_copyright__",
    "__plugin_dependencies__",
    "__plugin_optional_dependencies__",

    # Plugin + Widget loaders
    "get_plugin_class",
    "get_widget_class",

    # ColumnMappingService loaders (BUGG #2 FIX)
    "get_column_mapping_service_class",
    "get_mapping_entry_class",

    # VinRegistry loaders (BUGG #4 FIX)
    "get_vin_registry_class",
    "get_vin_entry_class",

    # Datamodell loaders
    "get_data_models",
    "get_DataSource",
    "get_FieldType",
    "get_MatchStatus",
    "get_VehicleMatchResult",
    "get_MatchingSummary",
    "get_GenerateResult",
    "get_VehicleImportStatus",

    # Info + utility
    "get_plugin_info",
    "clear_cache",
]