# -*- coding: utf-8 -*-
# Fil: plugins/main_gui/__init__.py

"""
Main GUI Plugin — Package Init v1.0.1

Lazy-laddning och metadata-åtkomst enligt mallen (ts_spec_import
v4.0.2 / ts_file_generator v6.0.1 / sap_import v4.1.1).

Gör main_gui till ett PYTHONPAKET så att relativa importer löses i
IDE/typkontroll (Pylance):

    from .vehicle_registry_helpers import ...   (vehicle_registry_page.py)
    from .vehicle_registry_page import VehicleDataPage  (plugin.py)

Utan denna fil varnar IDE:n med:
    Import ".vehicle_registry_helpers" could not be resolved

Ändringar v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (konsistens): paketinit uppgraderat till fullständigt
      lazy-mönster — metadata (name/author/description/dependencies/
      optional_dependencies), get_plugin_class() (kraschsäker,
      returnerar None om PySide6 saknas i headless), get_plugin_info()
      (+ plugin_class/features/has_ui/copyright färskt, KRAV 62),
      clear_cache(), __getattr__ (Plugin/VERSION/AUTHOR/NAME/
      DESCRIPTION/DEPENDENCIES/COPYRIGHT färskt).
    - KRAV 58: "# Fil: plugins/main_gui/__init__.py" (fanns som
      "# plugins/main_gui/__init__.py" utan Fil-prefix).
    - OBS (inväntar beslut): plugin.py importerar PySide6 på toppnivå
      — get_plugin_class() kraschar i headless (returnerar None med
      logg). Rekommendation: lokal import vid rotation (samma som
      response_viewer/reports).

Ändringar v1.0.0 (Session 11 — spec v1.10, KRAV 56):
    - NY FIL: paketinit för main_gui.
    - Metadata + dynamisk copyright enligt konvention.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import Plugin as PluginType
    from .vehicle_registry_page import VehicleDataPage as PageType

# ══════════════════════════════════════════════════════════════════════════════
# LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "Main GUI"
__plugin_version__: str = "1.0.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Huvudgränssnitt för fordonsregistrering (PySide6)"
)
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "vehicle_registry",
    "ts_excel_importer",
    "ts_spec_viewer",
    "ts_spec_import",
    "data_viewer",
    "dealers_manager",
    "colors_manager",
    "dispatch_viewer",
    "data_mapping",
    "reports",
    "core_config",
    "core_events",
]

__plugin_copyright__: str = "Copyright © %s %s" % (
    datetime.now().year,
    __plugin_author__,
)


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {__plugin_author__}"


VERSION: str = __plugin_version__
AUTHOR: str = __plugin_author__


# ══════════════════════════════════════════════════════════════════════════════
# LAZY CACHES (privata)
# ══════════════════════════════════════════════════════════════════════════════

_cached_plugin_class: Optional[Type["PluginType"]] = None
_cached_page_class: Optional[Type["PageType"]] = None


# ══════════════════════════════════════════════════════════════════════════════
# LOADERS
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_class() -> Optional[Type["PluginType"]]:
    """
    Hämta Plugin-klassen (lazy, cachad).

    Returnerar None om plugin.py inte kan importeras (t.ex. PySide6
    saknas i headless/test) — kraschsäkert.

    Returns:
        Plugin-klassen eller None
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
            _log.debug("Kunde inte ladda Plugin: %s", exc)
            return None
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av Plugin.")
            return None
    return _cached_plugin_class


def get_plugin_info() -> Dict[str, Any]:
    """Hämta plugin-metadata utan att ladda klassen."""
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(__plugin_optional_dependencies__),
        "plugin_class": "Plugin",
        "features": [
            "main_window",
            "navigation",
            "schema_integration",
            "vehicle_data_page",
            "menu_actions",
        ],
        "has_ui": True,
        "copyright": get_copyright_string(),
    }


def clear_cache() -> None:
    """Rensa lazy-cache. Används vid hot reload."""
    global _cached_plugin_class, _cached_page_class
    _cached_plugin_class = None
    _cached_page_class = None
    _log.debug("Cache rensad för main_gui.")


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST
# ══════════════════════════════════════════════════════════════════════════════

def __getattr__(name: str) -> Any:
    """Dynamisk attributåtkomst för bakåtkompatibilitet."""
    if name == "Plugin":
        return get_plugin_class()
    if name == "VERSION":
        return __plugin_version__
    if name == "AUTHOR":
        return __plugin_author__
    if name == "NAME":
        return __plugin_name__
    if name == "DESCRIPTION":
        return __plugin_description__
    if name == "DEPENDENCIES":
        return list(__plugin_dependencies__)
    if name == "COPYRIGHT":
        return get_copyright_string()
    raise AttributeError(
        f"module 'plugins.main_gui' has no attribute '{name}'"
    )


__all__: List[str] = [
    "__plugin_name__",
    "__plugin_version__",
    "__plugin_author__",
    "__plugin_description__",
    "get_plugin_class",
    "get_plugin_info",
    "clear_cache",
    "get_copyright_string",
    "VERSION",
    "AUTHOR",
]
