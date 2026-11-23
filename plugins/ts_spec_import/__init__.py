# plugins/ts_spec_import/__init__.py
# -*- coding: utf-8 -*-
"""
TS Spec Import Plugin — Package Init v4.0.2

Lazy-laddning och metadata-åtkomst för TS-postspecifikationsimportör.

Ändringar v4.0.2 (Session 11 — granskad, spec v1.6 förbättringsregeln):
    - Versionssynk: __plugin_version__ = "4.0.2" (plugin.py + models.py
      är v4.0.2; widget.py är v4.0.1 — alla i mappen synkade).
    - COPYRIGHT/__getattr__: genererar FÄRSKT år vid anrop
      (get_copyright_string()) i stället för statisk __plugin_copyright__
      (samma förbättring som vin_tracking v1.2.0).
    - Privata cache-variabler: cached_plugin_class/cached_widget_class ->
      _cached_plugin_class/_cached_widget_class (konvention).
    - Övrig logik OFÖRÄNDRAD (lazy, kraschsäker).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import Plugin as PluginType
    from .plugin import TSSpecImportWidget as WidgetType

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "TS Spec Import"
__plugin_version__: str = "4.0.2"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = "Import och hantering av TS-postspecifikationer"
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "ts_schema_manager",
    "ts_excel_importer",
    "ts_spec_viewer",
    "ts_file_generator",
    "core_config",
    "core_events",
]

__plugin_copyright__: str = "Copyright © %s %s" % (
    datetime.now().year,
    __plugin_author__,
)


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return "Copyright © %s %s" % (datetime.now().year, __plugin_author__)


# ══════════════════════════════════════════════════════════════════════════════
# LAZY LOADING
# ══════════════════════════════════════════════════════════════════════════════

_cached_plugin_class: Optional[Type["PluginType"]] = None
_cached_widget_class: Optional[Type["WidgetType"]] = None


def get_plugin_class() -> Type["PluginType"]:
    """Hämta Plugin-klassen (lazy, cachad)."""
    global _cached_plugin_class
    if _cached_plugin_class is None:
        from .plugin import Plugin
        _cached_plugin_class = Plugin
        _log.debug(
            "Plugin-klass laddad: %s v%s",
            __plugin_name__,
            __plugin_version__,
        )
    return _cached_plugin_class


def get_widget_class() -> Optional[Type["WidgetType"]]:
    """Hämta TSSpecImportWidget-klassen (lazy, cachad).

    NOTE: Widget ligger primärt i .widget (v4.0.1), med fallback till
    plugin.py för bakåtkompatibilitet. Om ingen widget finns
    returneras None istället för att krascha.
    """
    global _cached_widget_class
    if _cached_widget_class is None:
        try:
            from .widget import TSSpecImportWidget
            _cached_widget_class = TSSpecImportWidget
        except ImportError:
            try:
                from .plugin import TSSpecImportWidget
                _cached_widget_class = TSSpecImportWidget
            except ImportError:
                _log.debug("TSSpecImportWidget ej tillgänglig")
                return None
        _log.debug("Widget-klass laddad: TSSpecImportWidget")
    return _cached_widget_class


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
        "has_ui": True,
    }


def clear_cache() -> None:
    """Rensa lazy-cache. Används vid hot reload."""
    global _cached_plugin_class, _cached_widget_class
    _cached_plugin_class = None
    _cached_widget_class = None
    _log.debug("Cache rensad för ts_spec_import.")


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST
# ══════════════════════════════════════════════════════════════════════════════

def __getattr__(name: str) -> Any:
    if name == "Plugin":
        return get_plugin_class()
    if name in ("TSSpecImportWidget", "Widget"):
        return get_widget_class()
    if name == "VERSION":
        return __plugin_version__
    if name == "AUTHOR":
        return __plugin_author__
    if name == "NAME":
        return __plugin_name__
    if name == "DESCRIPTION":
        return __plugin_description__
    if name == "COPYRIGHT":
        return get_copyright_string()
    raise AttributeError(
        "module 'plugins.ts_spec_import' has no attribute '%s'" % name
    )


__all__ = [
    "__plugin_name__",
    "__plugin_version__",
    "__plugin_author__",
    "__plugin_description__",
    "__plugin_copyright__",
    "__plugin_dependencies__",
    "__plugin_optional_dependencies__",
    "get_plugin_class",
    "get_widget_class",
    "get_plugin_info",
    "clear_cache",
    "get_copyright_string",
]
