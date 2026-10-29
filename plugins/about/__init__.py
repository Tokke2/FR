
# -*- coding: utf-8 -*-
# plugins/about/__init__.py
"""
About Plugin — Package Init v3.0.0

Lazy-laddning och metadata-åtkomst för informative About-sidan.

Copyright © 2026 Rickard Längkvist
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import Plugin as PluginType, AboutWidget as WidgetType

__plugin_name__: str = "About"
__plugin_version__: str = "3.0.0"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = "Om systemet - dokumentation, hälsostatus och information"
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "ts_spec_import",
    "ts_schema_manager",
    "core_logger",
    "core_config",
]

_log = logging.getLogger("about")

cached_plugin_class: Optional[Type["PluginType"]] = None
cached_widget_class: Optional[Type["WidgetType"]] = None


def get_plugin_class() -> Type["PluginType"]:
    global cached_plugin_class
    if cached_plugin_class is None:
        from .plugin import Plugin
        cached_plugin_class = Plugin
    return cached_plugin_class


def get_widget_class() -> Optional[Type["WidgetType"]]:
    global cached_widget_class
    if cached_widget_class is None:
        try:
            from .plugin import AboutWidget
            cached_widget_class = AboutWidget
        except ImportError:
            return None
    return cached_widget_class


def get_plugin_info() -> Dict[str, Any]:
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(__plugin_optional_dependencies__),
        "has_ui": True
    }


def clear_cache() -> None:
    global cached_plugin_class
    global cached_widget_class
    cached_plugin_class = None
    cached_widget_class = None


def __getattr__(name: str) -> Any:
    if name == "Plugin":
        return get_plugin_class()
    if name == "AboutWidget" or name == "Widget":
        return get_widget_class()
    if name == "VERSION":
        return __plugin_version__
    if name == "AUTHOR":
        return __plugin_author__
    raise AttributeError(f"module 'plugins.about' has no attribute '{name}'")


__all__ = [
    "__plugin_name__",
    "__plugin_version__",
    "__plugin_author__",
    "__plugin_description__",
    "get_plugin_class",
    "get_widget_class",
    "get_plugin_info",
    "clear_cache"
]
