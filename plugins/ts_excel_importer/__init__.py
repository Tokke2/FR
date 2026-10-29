# -*- coding: utf-8 -*-
# Fil: plugins/ts_excel_importer/__init__.py
"""
TS Excel Importer — Package Init v2.0.1

Lazy-laddning och metadata-åtkomst för TS-specifikationsimportören
(Excel → scheman).

Ändringar v2.0.1 (versionssynk — plugin.py levererad v2.0.1):
    - __plugin_version__ = "2.0.1" (synk med plugin.py v2.0.1 +
      parser.py v2.0.1; widget.py v1.0.0).
    - get_plugin_class() laddar nu plugin.py (levererad).
    - Övrig logik OFÖRÄNDRAD (lazy, kraschsäker, metadata).

Ändringar v1.0.0 (spec v1.10 KRAV 56-länkning + spec v1.6):
    - NY FIL: plugins/ts_excel_importer/__init__.py skapad för
      paketlänkning — widget.py:s relativa importer
      (from .parser import ...) och IDE-upplösning kräver paketstruktur
      (fönstret "Import ... could not be resolved" försvinner).
    - Metadata enligt ts_spec_import v4.0.2-mallen; färskt
      copyright-år via get_copyright_string().
    - Privata cache-variabler (_cached_*).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .widget import TSExcelImportWidget as WidgetType
    from .plugin import Plugin as PluginType

# ══════════════════════════════════════════════════════════════════════
# LOGGER
# ══════════════════════════════════════════════════════════════════════

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════

__plugin_name__: str = "TS Excel Importer"
__plugin_version__: str = "2.0.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Import av TS-postspecifikationer från Excel (ark → scheman)"
)
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "ts_schema_manager",
    "ts_spec_import",
    "ts_spec_viewer",
]

__plugin_copyright__: str = "Copyright © %s %s" % (
    datetime.now().year,
    __plugin_author__,
)


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return "Copyright © %s %s" % (datetime.now().year, __plugin_author__)


# ══════════════════════════════════════════════════════════════════════
# LAZY CACHES (privata)
# ══════════════════════════════════════════════════════════════════════

_cached_plugin_class: Optional[Type["PluginType"]] = None
_cached_widget_class: Optional[Type["WidgetType"]] = None


# ══════════════════════════════════════════════════════════════════════
# LOADERS
# ══════════════════════════════════════════════════════════════════════

def get_plugin_class() -> Optional[Type["PluginType"]]:
    """
    Hämta Plugin-klassen (lazy, cachad).

    Returnerar None tills plugin.py levereras (kraschsäkert).

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


def get_widget_class() -> Optional[Type["WidgetType"]]:
    """
    Hämta TSExcelImportWidget-klassen (lazy, cachad).

    Returnerar None om widget.py inte kan importeras (kraschsäkert).

    Returns:
        TSExcelImportWidget-klassen eller None
    """
    global _cached_widget_class
    if _cached_widget_class is None:
        try:
            from .widget import TSExcelImportWidget
            _cached_widget_class = TSExcelImportWidget
            _log.debug("Widget-klass laddad: TSExcelImportWidget.")
        except ImportError as exc:
            _log.debug("Kunde inte ladda TSExcelImportWidget: %s", exc)
            return None
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av widget.")
            return None
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
        "plugin_class": "Plugin",
        "features": ["excel_import", "schema_generation"],
        "has_ui": True,
    }


def clear_cache() -> None:
    """Rensa lazy-cache. Används vid hot reload."""
    global _cached_plugin_class, _cached_widget_class
    _cached_plugin_class = None
    _cached_widget_class = None
    _log.debug("Cache rensad för ts_excel_importer.")


# ══════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST
# ══════════════════════════════════════════════════════════════════════

def __getattr__(name: str) -> Any:
    if name == "Plugin":
        return get_plugin_class()
    if name in ("TSExcelImportWidget", "Widget"):
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
        "module 'plugins.ts_excel_importer' has no attribute '%s'" % name
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
