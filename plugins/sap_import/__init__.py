# -*- coding: utf-8 -*-
# Fil: plugins/sap_import/__init__.py

"""
SAP Import Plugin — Package Init v4.1.1

Importerar fordonsdata från SAP/Dispatch Excel-filer.

EXPORTERAR:
    Plugin           — SAP Import plugin-klass
    SAPImportConfig  — Konfigurationsdataclass
    VehicleData      — Fordonsdata-dataclass
    ProcessedFile    — Resultat per fil
    ProcessedSheet   — Resultat per blad
    ImportSummary    — Sammanfattning av import

METADATA:
    __plugin_name__        = "SAP Import"
    __plugin_version__     = "4.1.1"
    __plugin_author__      = "Rickard Längkvist"
    __plugin_description__ = "Import av SAP/Dispatch Excel-filer"

Dataflöde:
    xlsx/*.xlsx → SAP Import → data/sap_cache/*.json
                                  ↓
                    sync_to_vehicle_registry() (NY v4.1.0)
                                  ↓
                    data/vehicles/{year}.json
                                  ↓
                    vehicle_registration_post → TS-fil

Ändringar v4.1.1 (granskad — spec v1.6 förbättringsregeln):
    - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2026 ..." i
      docstringen BORTTAGEN — copyright genereras dynamiskt via
      get_copyright_string().
    - Versionssynk: __plugin_version__ = "4.1.1" (plugin.py är
      v4.1.1).
    - COPYRIGHT_YEAR-konstanten (fryst årtal) BORTTAGEN —
      __plugin_copyright__ följer mallen (datetime.now().year vid
      import) och __getattr__("COPYRIGHT") returnerar FÄRSKT år via
      get_copyright_string() (samma mönster som ts_file_generator
      v6.0.1 / ts_excel_importer v2.0.1).
    - get_plugin_info(): + plugin_class="Plugin" + features=[...]
      (spec v1.12 KRAV 62-mönstret; events/data_files behållna).
    - Header normaliserad: "# Fil: plugins/sap_import/__init__.py"
      (spec v1.11, KRAV 58).
    - Övrig logik OFÖRÄNDRAD (lazy, kraschsäker, metadata-alias
      __version__/__author__/__description__).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import (
        Plugin as PluginType,
        SAPImportConfig as SAPImportConfigType,
        VehicleData as VehicleDataType,
        ProcessedFile as ProcessedFileType,
        ProcessedSheet as ProcessedSheetType,
        ImportSummary as ImportSummaryType,
        DataNormalizer as DataNormalizerType,
        ColumnResolver as ColumnResolverType,
        ExcelReader as ExcelReaderType,
        VehicleCache as VehicleCacheType,
    )

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log: logging.Logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "SAP Import"
__plugin_version__: str = "4.1.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = "Import av SAP/Dispatch Excel-filer (filbaserad)"
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "vin_tracking",
    "vehicle_registry",
    "ts_spec_import",
    "core_config",
]

__version__: str = __plugin_version__
__author__: str = __plugin_author__
__description__: str = __plugin_description__

__plugin_copyright__: str = "Copyright © %s %s" % (
    datetime.now().year,
    __plugin_author__,
)


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {__plugin_author__}"


# ══════════════════════════════════════════════════════════════════════════════
# LAZY LOADING
# ══════════════════════════════════════════════════════════════════════════════

_cached_plugin_class: Optional[Type["PluginType"]] = None


def get_plugin_class() -> Type["PluginType"]:
    """
    Hämta Plugin-klassen (lazy, cachad).

    Returns:
        Plugin-klassen

    Raises:
        ImportError: Om plugin.py inte kan importeras
    """
    global _cached_plugin_class
    if _cached_plugin_class is None:
        try:
            from .plugin import Plugin
            _cached_plugin_class = Plugin
            _log.debug(
                "Plugin-klass laddad: %s v%s",
                __plugin_name__,
                __plugin_version__,
            )
        except ImportError as exc:
            _log.error(
                "Kunde inte ladda Plugin-klass för '%s': %s",
                __plugin_name__,
                exc,
            )
            raise
        except Exception as exc:
            _log.exception(
                "Oväntat fel vid laddning av Plugin-klass för '%s'.",
                __plugin_name__,
            )
            raise ImportError(
                f"Kunde inte ladda Plugin-klass: {exc}"
            ) from exc
    return _cached_plugin_class


def get_plugin_info() -> Dict[str, Any]:
    """
    Hämta plugin-metadata utan att ladda klassen.

    Returns:
        Dict med name, version, author, description, copyright,
        plugin_class, features, events, data_files
    """
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "copyright": get_copyright_string(),
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(__plugin_optional_dependencies__),
        "plugin_class": "Plugin",
        "features": [
            "sap_import",
            "excel_reading",
            "vin_normalization",
            "cache_storage",
            "registry_sync",
        ],
        "has_ui": False,
        "events": {
            "emits": [
                "sap_import:started",
                "sap_import:file_complete",
                "sap_import:complete",
                "sap_import:synced_to_registry",
            ],
            "listens": [
                "sap_import:auto_import",
                "sap_import:import_file",
            ],
        },
        "data_files": [
            "data/sap_cache/*.json",
        ],
    }


def clear_cache() -> None:
    """Rensa lazy-laddad klass. Används vid hot reload."""
    global _cached_plugin_class
    _cached_plugin_class = None
    _log.debug("Cache rensad för sap_import.")


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST
# ══════════════════════════════════════════════════════════════════════════════

def __getattr__(name: str) -> Any:
    """
    Lazy loading av Plugin, SAPImportConfig, VehicleData,
    ProcessedFile, ProcessedSheet, ImportSummary,
    DataNormalizer, ColumnResolver, ExcelReader, VehicleCache.
    """
    if name == "Plugin":
        return get_plugin_class()

    plugin_attrs = {
        "SAPImportConfig",
        "VehicleData",
        "ProcessedFile",
        "ProcessedSheet",
        "ImportSummary",
        "DataNormalizer",
        "ColumnResolver",
        "ExcelReader",
        "VehicleCache",
    }

    if name in plugin_attrs:
        try:
            from . import plugin as plugin_module
            return getattr(plugin_module, name)
        except Exception as exc:
            raise AttributeError(
                f"module 'plugins.sap_import' attribute '{name}' "
                f"could not be loaded: {exc}"
            ) from exc

    _constants = {
        "VERSION": __plugin_version__,
        "AUTHOR": __plugin_author__,
        "NAME": __plugin_name__,
        "DESCRIPTION": __plugin_description__,
        "COPYRIGHT": get_copyright_string(),
    }

    if name in _constants:
        return _constants[name]

    raise AttributeError(
        f"module 'plugins.sap_import' has no attribute '{name}'"
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
    "__version__",
    # Loaders
    "get_plugin_class",
    "get_plugin_info",
    "clear_cache",
    "get_copyright_string",
]
