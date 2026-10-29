# -*- coding: utf-8 -*-
"""
plugins.vehicle_registration_post — Paketinit (spec v1.10)
Gör vehicle_registration_post till ett PYTHONPAKET så att relativa
importer löses i IDE/typkontroll (Pylance):
    from .plugin import Plugin   (krävs av PluginLoader och andra)
FÖRÄNDRINGAR v1.0.0 (Session 11 — spec v1.10, KRAV 56):
  - NY FIL: paketinit för vehicle_registration_post.
  - Lazy-export av Plugin-klassen enligt konvention.
  - Synkad version med plugin.py v3.1.1.
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Any, Dict
_log = logging.getLogger(__name__)
VERSION = "1.0.0"
AUTHOR = "Rickard Längkvist"
__plugin_name__ = "Vehicle Registration Post"
__plugin_version__ = "3.1.1"
__plugin_author__ = "Rickard Längkvist"
__plugin_description__ = (
    "Genererar registreringsposter (PT45) för Transportstyrelsen"
)
__plugin_dependencies__ = []
__plugin_optional_dependencies__ = [
    "ts_spec_import",
    "sap_import",
    "core_config",
    "core_logger",
]

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return "Copyright © {} {}".format(datetime.now().year, AUTHOR)

_cached_plugin_class: type | None = None

def get_plugin_class() -> type:
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
        "copyright": get_copyright_string(),
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
        return get_copyright_string()
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
