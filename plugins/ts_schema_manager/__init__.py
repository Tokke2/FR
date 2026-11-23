# -*- coding: utf-8 -*-
# Fil: plugins/ts_schema_manager/__init__.py
"""
TS Schema Manager — Package Init v3.6.0

Lazy-laddning och metadata-åtkomst för TS-schemahanteraren
(source of truth för TS-scheman).

Ändringar v3.6.0 (spec v1.10 KRAV 56-länkning + spec v1.6):
    - NY FIL: plugins/ts_schema_manager/__init__.py skapad för
      paketlänkning — plugin.py:s absoluta importer
      (from plugins.ts_schema_manager.constants import ...) kräver
      detta för att IDE/loader ska lösa modulerna
      (fönstret "Import ... could not be resolved" försvinner).
    - Versionssynk: __plugin_version__ = "3.6.0" (plugin.py v3.6.0;
      models.py v2.2.1, constants.py v2.2.1, version_manager v2.2.1,
      schema_store v1.0.1, schema_diff v1.0.1, widget v1.0.1).
    - COPYRIGHT/__getattr__: genererar FÄRSKT år vid anrop
      (get_copyright_string()) — samma mönster som ts_spec_import
      v4.0.2 och vin_tracking v1.2.0.
    - Privata cache-variabler (_cached_plugin_class/_cached_widget_class).
    - Widget-klass: TSSchemaManagerWidget i .widget (v1.0.1).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import Plugin as PluginType
    from .widget import TSSchemaManagerWidget as WidgetType

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "TS Schema Manager"
__plugin_version__: str = "3.6.0"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Hanterar TS-scheman och versioner (source of truth, 30+ funktioner)"
)
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "ts_spec_import",
    "ts_excel_importer",
    "ts_file_generator",
    "main_gui",
    "core_config",
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
    """Hämta TSSchemaManagerWidget-klassen (lazy, cachad)."""
    global _cached_widget_class
    if _cached_widget_class is None:
        try:
            from .widget import TSSchemaManagerWidget
            _cached_widget_class = TSSchemaManagerWidget
        except ImportError:
            _log.debug("TSSchemaManagerWidget ej tillgänglig")
            return None
        _log.debug("Widget-klass laddad: TSSchemaManagerWidget")
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
    _log.debug("Cache rensad för ts_schema_manager.")


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST
# ══════════════════════════════════════════════════════════════════════════════

def __getattr__(name: str) -> Any:
    if name == "Plugin":
        return get_plugin_class()
    if name in ("TSSchemaManagerWidget", "Widget"):
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
        "module 'plugins.ts_schema_manager' has no attribute '%s'" % name
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
