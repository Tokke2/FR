# -*- coding: utf-8 -*-
"""Colors Manager Plugin - Färghantering."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from .plugin import (
        Color,
        ColorLookupResult,
        ColorOperationResult,
        ColorService,
        Plugin as _PluginType,
        TSColorCode,
    )


def _get_logger() -> logging.Logger:
    """Returnerar modulens logger."""
    return logging.getLogger("plugins.colors_manager")


def _get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return f"Copyright © {datetime.now().year} Rickard Längkvist"


__plugin_name__ = "Colors Manager"
__plugin_version__ = "3.0.0"
__plugin_author__ = "Rickard Längkvist"
__plugin_description__ = "Färghantering med TS-mappning"
__plugin_dependencies__ = []
__plugin_optional_dependencies__ = ["core_config"]
__plugin_copyright__ = _get_copyright_string()

_cached_plugin_class: type["_PluginType"] | None = None
_cached_exports: Dict[str, Any] | None = None


def _load_exports() -> Dict[str, Any]:
    """Lazy-ladda publika exports från pluginmodulen."""
    global _cached_exports

    if _cached_exports is None:
        from .plugin import (
            COLOR_KEYWORDS,
            TSColorCode,
            Color,
            ColorLookupResult,
            ColorOperationResult,
            ColorService,
            Plugin,
        )

        _cached_exports = {
            "Plugin": Plugin,
            "ColorService": ColorService,
            "Color": Color,
            "ColorLookupResult": ColorLookupResult,
            "ColorOperationResult": ColorOperationResult,
            "TSColorCode": TSColorCode,
            "COLOR_KEYWORDS": COLOR_KEYWORDS,
        }

    return _cached_exports


def get_plugin_class() -> type["_PluginType"]:
    """Returnerar plugin-klassen med lazy import."""
    global _cached_plugin_class

    if _cached_plugin_class is None:
        from .plugin import Plugin

        _cached_plugin_class = Plugin

    return _cached_plugin_class


def get_plugin_info() -> Dict[str, Any]:
    """Returnerar plugin-metadata utan full modulimport."""
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(__plugin_optional_dependencies__),
        "copyright": __plugin_copyright__,
    }


def clear_cache() -> None:
    """Rensar interna lazy caches."""
    global _cached_plugin_class, _cached_exports
    _cached_plugin_class = None
    _cached_exports = None


def __getattr__(name: str) -> Any:
    """Dynamisk attributåtkomst för bakåtkompatibilitet."""
    if name == "Plugin":
        return get_plugin_class()

    if name in {
        "ColorService",
        "Color",
        "ColorLookupResult",
        "ColorOperationResult",
        "TSColorCode",
        "COLOR_KEYWORDS",
    }:
        exports = _load_exports()
        return exports[name]

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

    if name == "OPTIONAL_DEPENDENCIES":
        return list(__plugin_optional_dependencies__)

    if name == "COPYRIGHT":
        return __plugin_copyright__

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "get_plugin_class",
    "get_plugin_info",
    "clear_cache",
    "Plugin",
    "ColorService",
    "Color",
    "ColorLookupResult",
    "ColorOperationResult",
    "TSColorCode",
    "COLOR_KEYWORDS",
    "NAME",
    "VERSION",
    "AUTHOR",
    "DESCRIPTION",
    "DEPENDENCIES",
    "OPTIONAL_DEPENDENCIES",
    "COPYRIGHT",
]