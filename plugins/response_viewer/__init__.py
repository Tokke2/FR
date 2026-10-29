# -*- coding: utf-8 -*-
# Fil: plugins/response_viewer/__init__.py
"""
Response Viewer Plugin — Package Init v2.0.1

Lazy-laddning och metadata-åtkomst för TAD-svarsfilshanteraren.

Ändringar v2.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2026 ..." i
      docstringen BORTTAGEN — copyright genereras dynamiskt via
      get_copyright_string().
    - VERSIONS-SYNK: __plugin_version__ = "2.0.1" (plugin.py är
      v2.0.1).
    - FIX (KRAV 58): filkommentar "# Fil: plugins/response_viewer/
      __init__.py" tillagd (saknades).
    - Privata cache-variabler: cached_plugin_class ->
      _cached_plugin_class (konvention).
    - get_plugin_info(): + plugin_class="Plugin" + features=[...] +
      copyright (färskt år) (spec v1.12 KRAV 62-mönstret).
    - __getattr__: + NAME/DESCRIPTION/DEPENDENCIES/COPYRIGHT
      (COPYRIGHT färskt via get_copyright_string()) — fullständig
      bakåtkompatibilitet.
    - get_copyright_string() tillagd + i __all__.
    - Övrig logik OFÖRÄNDRAD (lazy get_plugin_class, clear_cache).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import Plugin as PluginType

# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "Response Viewer"
__plugin_version__: str = "2.0.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Hantering av TAD-svarsfiler från Transportstyrelsen"
)
__plugin_dependencies__: List[str] = ["core_config"]
__plugin_optional_dependencies__: List[str] = ["dealers_manager"]

__plugin_copyright__: str = "Copyright © %s %s" % (
    datetime.now().year,
    __plugin_author__,
)

_log = logging.getLogger(__name__)


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {__plugin_author__}"


_cached_plugin_class: Optional[Type["PluginType"]] = None


def get_plugin_class() -> Type["PluginType"]:
    """Hämta Plugin-klassen (lazy, cachad)."""
    global _cached_plugin_class
    if _cached_plugin_class is None:
        from .plugin import Plugin
        _cached_plugin_class = Plugin
    return _cached_plugin_class


def get_plugin_info() -> Dict[str, Any]:
    """Hämta plugin-metadata utan att ladda klassen."""
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(__plugin_optional_dependencies__),
        "plugin_class": "Plugin",
        "features": [
            "tad_response_import",
            "history",
            "reporting",
            "export_excel_pdf",
            "print",
            "dynamic_ui",
        ],
        "has_ui": True,
        "copyright": get_copyright_string(),
    }


def clear_cache() -> None:
    """Rensa lazy-cache. Används vid hot reload."""
    global _cached_plugin_class
    _cached_plugin_class = None


def __getattr__(name: str) -> Any:
    """Dynamisk attributåtkomst för bakåtkompatibilitet."""
    if name == "Plugin":
        return get_plugin_class()
    if name == "VERSION":
        return __plugin_version__
    if name == "AUTHOR":
        return __plugin_author__
    if name == "NAME":
        return __plugin_name__
    if name == "DESCRIPTION":
        return __plugin_description__
    if name == "DEPENDENCIES":
        return list(__plugin_dependencies__)
    if name == "COPYRIGHT":
        return get_copyright_string()
    raise AttributeError(
        f"module 'plugins.response_viewer' has no attribute '{name}'"
    )


__all__ = [
    "__plugin_name__",
    "__plugin_version__",
    "__plugin_author__",
    "__plugin_description__",
    "get_plugin_class",
    "get_plugin_info",
    "clear_cache",
    "get_copyright_string",
]
