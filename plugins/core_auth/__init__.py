# -*- coding: utf-8 -*-
"""Core Auth Plugin - säker autentisering och lösenordshantering."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from .plugin import Plugin as _PluginType


def _get_logger() -> logging.Logger:
    """Returnerar modulens logger."""
    return logging.getLogger("plugins.core_auth")


def _get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return f"Copyright © {datetime.now().year} Rickard Längkvist"


__plugin_name__ = "Core Auth"
__plugin_version__ = "2.0.0"
__plugin_author__ = "Rickard Längkvist"
__plugin_description__ = "Säker autentisering och lösenordshantering"
__plugin_dependencies__ = []
__plugin_optional_dependencies__ = ["core_json", "core_config", "core_logger"]
__plugin_copyright__ = _get_copyright_string()

_cached_plugin_class: type["_PluginType"] | None = None
_cached_exports: Dict[str, Any] | None = None


def _load_exports() -> Dict[str, Any]:
    """Lazy-ladda publika exports från pluginmodulen."""
    global _cached_exports

    if _cached_exports is None:
        from .plugin import (
            AUTHOR,
            DEFAULT_PASSWORD,
            LOCKOUT_DURATION_MINUTES,
            MAX_LOGIN_ATTEMPTS,
            PASSWORD_MIN_LENGTH,
            SESSION_TIMEOUT_MINUTES,
            VERSION,
            Plugin,
            emit_event_safe,
            get_copyright_string,
            get_copyright_year,
            get_plugin_safe,
            hash_password_internal,
            secure_compare,
        )

        _cached_exports = {
            "Plugin": Plugin,
            "VERSION": VERSION,
            "AUTHOR": AUTHOR,
            "DEFAULT_PASSWORD": DEFAULT_PASSWORD,
            "MAX_LOGIN_ATTEMPTS": MAX_LOGIN_ATTEMPTS,
            "LOCKOUT_DURATION_MINUTES": LOCKOUT_DURATION_MINUTES,
            "PASSWORD_MIN_LENGTH": PASSWORD_MIN_LENGTH,
            "SESSION_TIMEOUT_MINUTES": SESSION_TIMEOUT_MINUTES,
            "get_copyright_year": get_copyright_year,
            "get_copyright_string": get_copyright_string,
            "get_plugin_safe": get_plugin_safe,
            "emit_event_safe": emit_event_safe,
            "hash_password_internal": hash_password_internal,
            "secure_compare": secure_compare,
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
        "VERSION",
        "AUTHOR",
        "DEFAULT_PASSWORD",
        "MAX_LOGIN_ATTEMPTS",
        "LOCKOUT_DURATION_MINUTES",
        "PASSWORD_MIN_LENGTH",
        "SESSION_TIMEOUT_MINUTES",
        "get_copyright_year",
        "get_copyright_string",
        "get_plugin_safe",
        "emit_event_safe",
        "hash_password_internal",
        "secure_compare",
    }:
        exports = _load_exports()
        return exports[name]

    if name == "NAME":
        return __plugin_name__

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
    "DEFAULT_PASSWORD",
    "MAX_LOGIN_ATTEMPTS",
    "LOCKOUT_DURATION_MINUTES",
    "PASSWORD_MIN_LENGTH",
    "SESSION_TIMEOUT_MINUTES",
    "get_copyright_year",
    "get_copyright_string",
    "get_plugin_safe",
    "emit_event_safe",
    "hash_password_internal",
    "secure_compare",
]
