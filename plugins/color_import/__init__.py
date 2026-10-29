# -*- coding: utf-8 -*-
"""Paketinitiering för Color Import-pluginet."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import Plugin as _PluginType


def _get_logger() -> logging.Logger:
    """Returnerar modulens logger."""
    return logging.getLogger("plugins.color_import")


def _get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return f"Copyright © {datetime.now().year} Rickard Längkvist"


__plugin_name__ = "Color Import"
__plugin_version__ = "3.0.0"
__plugin_author__ = "Rickard Längkvist"
__plugin_description__ = "Import av färgdata från Excel med PDF-export"
__plugin_dependencies__ = ["colors_manager"]
__plugin_optional_dependencies__ = ["ts_spec_import"]
__plugin_copyright__ = _get_copyright_string()

_cached_plugin_class: type["_PluginType"] | None = None


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
    "NAME",
    "VERSION",
    "AUTHOR",
    "DESCRIPTION",
    "DEPENDENCIES",
    "OPTIONAL_DEPENDENCIES",
    "COPYRIGHT",
]