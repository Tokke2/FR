# -*- coding: utf-8 -*-
# plugins/core_config/__init__.py
"""
Core Config Plugin — Package Init v4.0.0

Centraliserad konfigurationshantering.

Copyright © 2026 Rickard Längkvist
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import Plugin as PluginType

__plugin_name__: str = "Core Config"
__plugin_version__: str = "4.0.0"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = "Central JSON-konfigurationshantering"
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = []

_log = logging.getLogger("core_config")

cached_plugin_class: Optional[Type["PluginType"]] = None


def get_plugin_class() -> Type["PluginType"]:
    global cached_plugin_class
    if cached_plugin_class is None:
        from .plugin import Plugin
        cached_plugin_class = Plugin
    return cached_plugin_class


def get_plugin_info() -> Dict[str, Any]:
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(__plugin_optional_dependencies__),
        "has_ui": False
    }


def clear_cache() -> None:
    global cached_plugin_class
    cached_plugin_class = None


def __getattr__(name: str) -> Any:
    if name == "Plugin":
        return get_plugin_class()
    if name == "VERSION":
        return __plugin_version__
    if name == "AUTHOR":
        return __plugin_author__
    raise AttributeError(f"module 'plugins.core_config' has no attribute '{name}'")


__all__ = [
    "__plugin_name__",
    "__plugin_version__",
    "__plugin_author__",
    "__plugin_description__",
    "get_plugin_class",
    "get_plugin_info",
    "clear_cache"
]
