# -*- coding: utf-8 -*-
# Fil: plugins/dispatch_viewer/__init__.py

"""
Dispatch Viewer Plugin — Package Init v3.1.1

Visa och exportera dispatch-data från Excel-filer
med integration mot TS-scheman.

EXPORTERAR:
  Plugin             — Dispatch Viewer plugin-klass
  DispatchWidget     — PySide6 widget
  DispatchTableModel — QAbstractTableModel för dispatch-data
  COLUMN_ALIASES     — Kolumnalias för rubrikdetektering

METADATA:
  __plugin_name__        = "Dispatch Viewer"
  __plugin_version__     = "3.1.1"
  __plugin_author__      = "Rickard Längkvist"
  __plugin_description__ = "Visa och exportera dispatch-data med schema-integration"

FÖRÄNDRINGAR v3.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil: plugins/dispatch_viewer/__init__.py"
    tillagd (saknades — stod utan "Fil:"-prefix).
  - FIX (versionsharmonisering): __plugin_version__ 3.1.0 → 3.1.1
    (matchar plugin.py v3.1.1 — spec-regeln om konsistenta versioner
    inom plugin); __version__/VERSION uppdaterade.
  - FIX (stabilitet, mallen): get_plugin_class() kastar INTE längre
    ImportError — returnerar None med debug-logg om plugin.py inte
    kan importeras (kraschsäkert headless, samma mönster som
    identity_post v3.2.1 / end_post v3.1.1 / ereko v1.0.1).
  - FIX (korrekthet, rekursion): "from . import plugin" i __getattr__
    triggar paketets __getattr__("plugin") via import-maskineriets
    hasattr → oändlig rekursion (samma bugg som ereko fångade).
    Nu: importlib.import_module(__name__ + ".plugin") med
    fullständigt namn.
  - FIX (konsistens): publik get_copyright_string() + privat alias
    _get_copyright_string (bakåtkompatibilitet); VERSION/AUTHOR som
    modulvariabler; __getattr__-fallback NAME/DESCRIPTION/
    DEPENDENCIES/COPYRIGHT (mallen).
  - TILLÄGG (mallen): get_plugin_info() utökad med "plugin_class":
    "Plugin", "features" och "module" (metadata-kontraktet).
  - __all__ utökad (VERSION, AUTHOR, get_copyright_string,
    _get_copyright_string, COLUMN_ALIASES — nås via __getattr__,
    headless-säkert eftersom plugin.py har HAS_PYSIDE6-guard).
  - FIX (radbrytningsartefakt): dubblerade blankrader före
    def/class kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (lazy-cache, clear_cache, övriga
    metadata).
FÖRÄNDRINGAR v3.1.0:
  - NY FIL (inklistrad original): paketinit med lazy-laddning.
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import importlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import (
        Plugin as PluginType,
        DispatchWidget as DispatchWidgetType,
        DispatchTableModel as DispatchTableModelType,
    )

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log: logging.Logger = logging.getLogger("dispatch_viewer")

# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "Dispatch Viewer"
__plugin_version__: str = "3.1.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Visa och exportera dispatch-data med schema-integration"
)
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "ts_schema_manager",
    "data_mapping",
    "vehicle_registry",
]

VERSION: str = __plugin_version__
AUTHOR: str = __plugin_author__
__version__: str = __plugin_version__
__author__: str = __plugin_author__
__description__: str = __plugin_description__

COPYRIGHT_YEAR: int = datetime.now().year
__plugin_copyright__: str = (
    "Copyright © %s %s" % (COPYRIGHT_YEAR, __plugin_author__)
)

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {__plugin_author__}"


# Bakåtkompatibilitet: privat alias.
_get_copyright_string = get_copyright_string


# ══════════════════════════════════════════════════════════════════════════════
# LAZY LOADING
# ══════════════════════════════════════════════════════════════════════════════

_cached_plugin_class: Optional[Type["PluginType"]] = None

def get_plugin_class() -> Optional[Type["PluginType"]]:
    """
    Hämta Plugin-klassen (lazy, cachad, kraschsäker).

    Returns:
        Plugin-klassen eller None om plugin.py inte kan importeras
        (t.ex. headless/test) — med debug-logg.
    """
    global _cached_plugin_class
    if _cached_plugin_class is None:
        try:
            module = importlib.import_module(__name__ + ".plugin")
            _cached_plugin_class = module.Plugin
            _log.debug(
                "Plugin-klass laddad: %s v%s",
                __plugin_name__,
                __plugin_version__,
            )
        except ImportError as exc:
            _log.debug(
                "Kunde inte ladda Plugin-klass för '%s': %s",
                __plugin_name__,
                exc,
            )
            return None
        except Exception as exc:
            _log.exception(
                "Oväntat fel vid laddning av Plugin-klass för '%s'.",
                __plugin_name__,
            )
            return None
    return _cached_plugin_class

def get_plugin_info() -> Dict[str, Any]:
    """
    Hämta plugin-metadata utan att ladda klassen.

    Returns:
        Dict med name, version, author, description, copyright
    """
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "copyright": get_copyright_string(),
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(__plugin_optional_dependencies__),
        "has_ui": True,
        "plugin_class": "Plugin",
        "features": [
            "dispatch_view",
            "header_detection",
            "vin_validation",
            "csv_export",
            "excel_export",
            "data_api",
        ],
        "module": __name__,
    }

def clear_cache() -> None:
    """Rensa lazy-laddad klass. Används vid hot reload."""
    global _cached_plugin_class
    _cached_plugin_class = None
    _log.debug("Cache rensad för dispatch_viewer.")


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST
# ══════════════════════════════════════════════════════════════════════════════

def __getattr__(name: str) -> Any:
    """
    Lazy loading av Plugin, DispatchWidget, DispatchTableModel,
    COLUMN_ALIASES + metadata-fallback (NAME/DESCRIPTION/
    DEPENDENCIES/COPYRIGHT).
    """
    if name == "Plugin":
        return get_plugin_class()
    if name in (
        "DispatchWidget",
        "DispatchTableModel",
        "COLUMN_ALIASES",
        "PANDAS_AVAILABLE",
        "get_plugin_safe",
        "emit_event_safe",
        "subscribe_event_safe",
        "unsubscribe_event_safe",
    ):
        try:
            module = importlib.import_module(__name__ + ".plugin")
            return getattr(module, name)
        except Exception as exc:
            raise AttributeError(
                "module 'plugins.dispatch_viewer' attribute '%s' "
                "could not be loaded: %s" % (name, exc)
            ) from exc

    # Metadata-fallback (mallen)
    if name == "NAME":
        return __plugin_name__
    if name == "DESCRIPTION":
        return __plugin_description__
    if name == "DEPENDENCIES":
        return list(__plugin_dependencies__)
    if name == "COPYRIGHT":
        return get_copyright_string()

    raise AttributeError(
        "module 'plugins.dispatch_viewer' has no attribute '%s'"
        % name
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
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
    "_get_copyright_string",
    # Loaders
    "get_plugin_class",
    "get_plugin_info",
    "clear_cache",
    # Lazy (via __getattr__ — headless-säkert)
    "COLUMN_ALIASES",
]
