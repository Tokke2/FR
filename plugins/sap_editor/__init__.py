# -*- coding: utf-8 -*-
# Fil: plugins/sap_editor/__init__.py
"""Paketinitiering för SAP Editor-pluginet (v1.0.1).

Lazy-laddning och metadata-åtkomst enligt mallen (ts_spec_import
v4.0.2 / ts_file_generator v6.0.1 / sap_import v4.1.1).

Ändringar v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (KRAV 58): filkommentar "# Fil: plugins/sap_editor/__init__.py"
      tillagd (saknades).
    - VERSIONS-SYNK: __plugin_version__ = "1.0.1" (plugin.py är v1.0.1
      — ej 2.0.0; master anger 2.0.0 (4 filer), trädet 2 filer;
      versionssynk sker vid leverans av ui/editor_window.py m.fl.).
    - FIX (färskt år): __getattr__("COPYRIGHT") och
      get_plugin_info()["copyright"] returnerar nu FÄRSKT år via
      get_copyright_string() (inte fryst __plugin_copyright__) —
      samma förbättring som ts_file_generator/sap_import-__init__.
    - _get_logger/_get_copyright_string -> _log/get_copyright_string
      (publik, mallen); __all__ + get_copyright_string.
    - Typning enligt mallen: Optional[Type["PluginType"]] (i stället
      för type[...] | None) + List/Optional/Type-importer.
    - get_plugin_info(): + plugin_class="Plugin" + features=[...] +
      has_ui=True + optional_dependencies (spec v1.12 KRAV 62-mönstret).
    - Övrig logik OFÖRÄNDRAD (lazy get_plugin_class, clear_cache,
      __getattr__-bakåtkompatibilitet).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import Plugin as _PluginType

# ══════════════════════════════════════════════════════════════════════════════
# LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log = logging.getLogger(__name__)


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng (färskt år)."""
    return f"Copyright © {datetime.now().year} Rickard Längkvist"


# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__ = "SAP Editor"
__plugin_version__ = "1.0.1"
__plugin_author__ = "Rickard Längkvist"
__plugin_description__ = "Lösenordsskyddad redigering av SAP-data"
__plugin_dependencies__ = ["core_auth"]
__plugin_optional_dependencies__ = ["main_gui"]
__plugin_copyright__ = "Copyright © %s %s" % (
    datetime.now().year,
    __plugin_author__,
)

_cached_plugin_class: Optional[Type["_PluginType"]] = None


def get_plugin_class() -> Type["_PluginType"]:
    """Returnerar plugin-klassen med lazy import."""
    global _cached_plugin_class

    if _cached_plugin_class is None:
        from .plugin import Plugin

        _cached_plugin_class = Plugin

    return _cached_plugin_class


def get_plugin_info() -> Dict[str, Any]:
    """Returnerar plugin-metadata utan att importera pluginmodulen fullt ut."""
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(__plugin_optional_dependencies__),
        "plugin_class": "Plugin",
        "features": [
            "sap_editing",
            "password_protected",
            "menu_integration",
        ],
        "has_ui": True,
        "copyright": get_copyright_string(),
    }


def clear_cache() -> None:
    """Rensar interna lazy caches."""
    global _cached_plugin_class
    _cached_plugin_class = None


def __getattr__(name: str) -> Any:
    """Dynamisk attributåtkomst för bakåtkompatibilitet."""
    if name == "Plugin":
        return get_plugin_class()

    if name == "NAME":
        return __plugin_name__

    if name == "VERSION":
        return __plugin_version__

    if name == "AUTHOR":
        return __plugin_author__

    if name == "DESCRIPTION":
        return __plugin_description__

    if name == "DEPENDENCIES":
        return list(__plugin_dependencies__)

    if name == "COPYRIGHT":
        return get_copyright_string()

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "get_plugin_class",
    "get_plugin_info",
    "clear_cache",
    "get_copyright_string",
    "Plugin",
    "NAME",
    "VERSION",
    "AUTHOR",
    "DESCRIPTION",
    "DEPENDENCIES",
    "COPYRIGHT",
]
