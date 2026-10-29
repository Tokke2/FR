# -*- coding: utf-8 -*-

"""VIN Tracking Plugin - VIN-register per år och månad."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from .plugin import Plugin as _PluginType


def get_logger() -> logging.Logger:
    """Returnerar modulens logger."""
    return logging.getLogger(__name__)


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return "Copyright © {} Rickard Längkvist".format(datetime.now().year)


__plugin_name__ = "VIN Tracking"
__plugin_version__ = "1.1.0"
__plugin_author__ = "Rickard Längkvist"
__plugin_description__ = "VIN-registrering per år och månad"
__plugin_dependencies__ = []
__plugin_copyright__ = get_copyright_string()

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

    if name == "COPYRIGHT":
        return __plugin_copyright__

    raise AttributeError(
        "module {!r} has no attribute {!r}".format(__name__, name)
    )


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
    "COPYRIGHT",
]
