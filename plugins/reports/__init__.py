# -*- coding: utf-8 -*-
# Fil: plugins/reports/__init__.py
"""Reports Plugin - Rapportgenerering (v2.1.1).

Lazy-laddning och metadata-åtkomst enligt mallen (ts_spec_import
v4.0.2 / ts_file_generator v6.0.1 / sap_import v4.1.1).

Ändringar v2.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (KRAV 58): filkommentar "# Fil: plugins/reports/__init__.py"
      tillagd (saknades).
    - VERSIONS-SYNK: __plugin_version__ = "2.1.1" (plugin.py är
      v2.1.1 — ej 1.0.0; exporters.py är v1.0.1).
    - Metadata tillagd (name/author/description/dependencies/
      optional_dependencies) + get_copyright_string (färskt år).
    - Lazy get_plugin_class() med privat _cached_plugin_class +
      clear_cache().
    - get_plugin_info(): plugin_class + features + has_ui + copyright
      (spec v1.12 KRAV 62-mönstret).
    - __getattr__: Plugin/VERSION/AUTHOR/NAME/DESCRIPTION/DEPENDENCIES/
      COPYRIGHT (färskt) — fullständig bakåtkompatibilitet.
    - OBS (inväntar beslut): plugin.py importerar PySide6 på toppnivå
      — get_plugin_class() kraschar i headless/test. Rekommendation:
      lokal import vid rotation (samma som response_viewer).
    - Övrig logik OFÖRÄNDRAD (exporter).
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

__plugin_name__: str = "Reports"
__plugin_version__: str = "2.1.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Rapportgenerering och historik (VIN, Återförsäljare, System)"
)
__plugin_dependencies__: List[str] = ["core_config"]
__plugin_optional_dependencies__: List[str] = ["vehicle_registry"]

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
            "vin_reports",
            "dealer_reports",
            "system_reports",
            "history_page",
            "export_csv_excel_pdf",
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
        f"module 'plugins.reports' has no attribute '{name}'"
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
