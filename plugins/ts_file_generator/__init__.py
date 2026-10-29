# -*- coding: utf-8 -*-
# Fil: plugins/ts_file_generator/__init__.py
"""
TS File Generator Plugin — Package Init v6.0.1

Lazy loading av Plugin, Widget, RecordBuilder och latin1_utils.

Ändringar v6.0.1 (granskad — spec v1.6 förbättringsregeln + spec v1.12
KRAV 62 + spec v1.10 KRAV 56-länkning):
    - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2026 ..." i
      docstringen BORTTAGEN — copyright genereras dynamiskt via
      get_copyright_string().
    - Versionssynk: __plugin_version__ = "6.0.1" (plugin.py är v6.0.1;
      widget v5.0.1, record_builder v2.0.1, latin1_utils v2.0.1).
    - get_logger() -> _log = logging.getLogger(__name__) direkt
      (mallen: ts_spec_import v4.0.2 / ts_schema_manager v3.6.0).
    - Privata cache-variabler: cached_* -> _cached_* (konvention).
    - get_widget_class()/get_record_builder_class()/get_latin1_utils():
      returnerar None vid ImportError (kraschsäker — mallen);
      get_plugin_class() loggar + propagerar ImportError (fatalt).
    - __getattr__("COPYRIGHT") returnerar FÄRSKT år via
      get_copyright_string() (ej fryst __plugin_copyright__).
    - get_plugin_info(): + plugin_class="Plugin" + features=[...]
      (spec v1.12 KRAV 62).
    - COPYRIGHT_YEAR-konstant borttagen (fryst årtal — __plugin_copyright__
      följer mallen; färskt år via get_copyright_string()).
    - __all__ kompletterad med get_copyright_string.
    - Filkommentar "# Fil: plugins/ts_file_generator/__init__.py"
      (spec v1.11, KRAV 58).
    - Övrig logik OFÖRÄNDRAD (lazy loaders, metadata, clear_cache,
      dynamisk attributåtkomst).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import Plugin as PluginType
    from .widget import TSFileGeneratorWidget as WidgetType
    from .record_builder import RecordBuilder as RecordBuilderType


# ══════════════════════════════════════════════════════════════════════
# LOGGER
# ══════════════════════════════════════════════════════════════════════

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════

__plugin_name__: str = "TS File Generator"
__plugin_version__: str = "6.0.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Genererar TS-filer (PT28/PT45/PT99), schema-driven, "
    "Latin-1, 2500 tecken/rad, atomisk skrivning"
)
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "ts_schema_manager",
    "ts_spec_import",
    "vehicle_registry",
    "dealers_manager",
    "colors_manager",
    "identity_post",
    "vehicle_registration_post",
    "end_post",
    "ereko",
    "sap_import",
    "dispatch_viewer",
    "data_mapping",
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
_cached_record_builder_class: Optional[Type["RecordBuilderType"]] = None
_cached_latin1_utils: Optional[Dict[str, Any]] = None


# ══════════════════════════════════════════════════════════════════════
# LOADERS
# ══════════════════════════════════════════════════════════════════════

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
            _log.error("Kunde inte ladda Plugin: %s", exc)
            raise
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av Plugin.")
            raise ImportError(str(exc)) from exc
    return _cached_plugin_class


def get_widget_class() -> Optional[Type["WidgetType"]]:
    """
    Hämta TSFileGeneratorWidget (lazy, cachad).

    Returnerar None om widget.py inte kan importeras (kraschsäker —
    widget saknas är inte fatalt).

    Returns:
        TSFileGeneratorWidget-klassen eller None
    """
    global _cached_widget_class
    if _cached_widget_class is None:
        try:
            from .widget import TSFileGeneratorWidget
            _cached_widget_class = TSFileGeneratorWidget
            _log.debug("Widget-klass laddad: TSFileGeneratorWidget.")
        except ImportError as exc:
            _log.debug("Kunde inte ladda TSFileGeneratorWidget: %s", exc)
            return None
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av widget.")
            return None
    return _cached_widget_class


def get_record_builder_class() -> Optional[Type["RecordBuilderType"]]:
    """
    Hämta RecordBuilder-klassen (lazy, cachad).

    Returnerar None om record_builder.py inte kan importeras
    (kraschsäker — plugin.py har egen fallback).

    Returns:
        RecordBuilder-klassen eller None
    """
    global _cached_record_builder_class
    if _cached_record_builder_class is None:
        try:
            from .record_builder import RecordBuilder
            _cached_record_builder_class = RecordBuilder
            _log.debug("RecordBuilder-klass laddad.")
        except ImportError as exc:
            _log.debug("Kunde inte ladda RecordBuilder: %s", exc)
            return None
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av RecordBuilder.")
            return None
    return _cached_record_builder_class


def get_latin1_utils() -> Optional[Dict[str, Any]]:
    """
    Hämta latin1_utils-funktioner (lazy, cachad).

    Returnerar None om latin1_utils.py inte kan importeras
    (kraschsäker — widget/record_builder har egna fallbacks).

    Returns:
        Dict med funktioner: validate_latin1, sanitize_for_ts,
        ensure_latin1, sanitize_and_ensure, is_latin1_safe,
        get_invalid_chars, validate_ts_record, LATIN1_REPLACEMENTS
        eller None
    """
    global _cached_latin1_utils
    if _cached_latin1_utils is None:
        try:
            from .latin1_utils import (
                validate_latin1,
                sanitize_for_ts,
                ensure_latin1,
                sanitize_and_ensure,
                is_latin1_safe,
                get_invalid_chars,
                validate_ts_record,
                LATIN1_REPLACEMENTS,
            )
            _cached_latin1_utils = {
                "validate_latin1": validate_latin1,
                "sanitize_for_ts": sanitize_for_ts,
                "ensure_latin1": ensure_latin1,
                "sanitize_and_ensure": sanitize_and_ensure,
                "is_latin1_safe": is_latin1_safe,
                "get_invalid_chars": get_invalid_chars,
                "validate_ts_record": validate_ts_record,
                "LATIN1_REPLACEMENTS": LATIN1_REPLACEMENTS,
            }
            _log.debug("latin1_utils laddade.")
        except ImportError as exc:
            _log.debug("Kunde inte ladda latin1_utils: %s", exc)
            return None
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av latin1_utils.")
            return None
    return _cached_latin1_utils


def get_plugin_info() -> Dict[str, Any]:
    """
    Hämta plugin-metadata utan att ladda klassen.

    Returns:
        Dict med name, version, author, description, copyright,
        dependencies, optional_dependencies, plugin_class, features
        (spec v1.12 KRAV 62)
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
            "ts_file_generation",
            "response_import",
            "status_tracking",
            "file_id_management",
            "latin1_encoding",
            "schema_driven",
        ],
        "has_ui": True,
        "record_length": 2500,
        "encoding": "iso-8859-1",
        "post_types": ["28", "45", "99"],
    }


def clear_cache() -> None:
    """
    Rensa alla lazy-cacher.

    Används vid hot reload eller testning.
    """
    global _cached_plugin_class
    global _cached_widget_class
    global _cached_record_builder_class
    global _cached_latin1_utils

    _cached_plugin_class = None
    _cached_widget_class = None
    _cached_record_builder_class = None
    _cached_latin1_utils = None
    _log.debug("Cache rensad för ts_file_generator.")


# ══════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST
# ══════════════════════════════════════════════════════════════════════

_LAZY_ATTR_MAP: Dict[str, str] = {
    "Plugin": "get_plugin_class",
    "TSFileGeneratorWidget": "get_widget_class",
    "Widget": "get_widget_class",
    "RecordBuilder": "get_record_builder_class",
}

_METADATA_ATTR_MAP: Dict[str, Any] = {
    "VERSION": __plugin_version__,
    "AUTHOR": __plugin_author__,
    "NAME": __plugin_name__,
    "DESCRIPTION": __plugin_description__,
    "COPYRIGHT": get_copyright_string(),
}


def __getattr__(name: str) -> Any:
    """
    Dynamisk attributåtkomst — bakåtkompatibel lazy loading.

    Stöder: Plugin, TSFileGeneratorWidget, Widget,
    RecordBuilder, VERSION, AUTHOR, NAME, DESCRIPTION, COPYRIGHT
    """
    if name in _METADATA_ATTR_MAP:
        return _METADATA_ATTR_MAP[name]

    loader_name = _LAZY_ATTR_MAP.get(name)
    if loader_name is not None:
        loader_func = globals().get(loader_name)
        if loader_func is not None and callable(loader_func):
            try:
                result = loader_func()
                if result is None:
                    raise AttributeError(
                        f"module 'plugins.ts_file_generator' attribute "
                        f"'{name}' could not be loaded"
                    )
                return result
            except AttributeError:
                raise
            except Exception as exc:
                _log.error(
                    "Lazy loading av '%s' misslyckades: %s", name, exc
                )
                raise AttributeError(
                    f"module 'plugins.ts_file_generator' attribute '{name}' "
                    f"could not be loaded: {exc}"
                ) from exc

    raise AttributeError(
        f"module 'plugins.ts_file_generator' has no attribute '{name}'"
    )


# ══════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════

__all__: List[str] = [
    "__plugin_name__",
    "__plugin_version__",
    "__plugin_author__",
    "__plugin_description__",
    "__plugin_copyright__",
    "__plugin_dependencies__",
    "__plugin_optional_dependencies__",
    "get_plugin_class",
    "get_widget_class",
    "get_record_builder_class",
    "get_latin1_utils",
    "get_plugin_info",
    "clear_cache",
    "get_copyright_string",
]
