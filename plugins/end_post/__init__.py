# -*- coding: utf-8 -*-
# Fil: plugins/end_post/__init__.py

"""
End Post Plugin — Package Init v3.1.1

Genererar slutpost (posttyp 99) för Transportstyrelsen.

Detta package exporterar pluginet i ett format som fungerar både med:
- ny plugin-loader som förväntar sig `Plugin`
- äldre kod som fortfarande importerar `EndPostPlugin`

Notera:
    Själva logiken för att läsa schema från ts_spec_import ligger i
    plugin.py. Detta init sköter lazy-laddning + metadata enligt
    mallen (identity_post/__init__.py v3.2.1 / ereko/__init__.py
    v1.0.1).

FÖRÄNDRINGAR v3.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil: plugins/end_post/__init__.py" tillagd
    (saknades).
  - FIX (KRAV 60): __author__ "TADEGA AB" BORT → "Rickard Längkvist"
    (samma legacy-bugg som identity_post/ereko hade).
  - FIX (versionsharmonisering): __version__ 3.0.0 → 3.1.1 (matchar
    plugin.py v3.1.1 — spec-regeln om konsistenta versioner inom
    plugin); __plugin_version__/VERSION uppdaterade.
  - FIX (stabilitet, mallen): direkt-import på toppnivå ("from
    .plugin import Plugin") BORT → lazy get_plugin_class() som
    returnerar None med logg om plugin.py inte kan importeras
    (kraschsäkert headless, samma mönster som identity_post/ereko).
    Plugin/EndPostPlugin nås via __getattr__ (PEP 562) — fungerar
    identiskt för from-import.
  - FIX (metadata-kontraktet): get_plugin_info() omarbetad —
    "depends_on" (icke-standard) bort → "dependencies"/
    "optional_dependencies" (kontraktet); tillagd "copyright"
    (dynamisk), "plugin_class", "features", "has_ui": False
    (end_post har ingen GUI), "module".
  - TILLÄGG (mallen): __plugin_name__/__plugin_description__/
    __plugin_copyright__ + get_copyright_string (+ privat alias),
    __getattr__-fallback NAME/DESCRIPTION/DEPENDENCIES/COPYRIGHT,
    clear_cache() (hot reload), VERSION/AUTHOR som modulvariabler.
  - FIX (radbrytningsartefakt): dubblerade blankrader före
    def/class kollapsade till max 1 (transport-artefakt).
FÖRÄNDRINGAR v3.0.0:
  - NY FIL (inklistrad original): direkt-import + try/except-fallback.
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import importlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import Plugin as PluginType

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log: logging.Logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "End Post"
__plugin_version__: str = "3.1.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Genererar slutposter (PT99) med stöd för ts_spec_import"
)
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "ts_spec_import",
    "core_config",
    "core_logger",
]

VERSION: str = __plugin_version__
AUTHOR: str = __plugin_author__
__version__: str = __plugin_version__
__author__: str = __plugin_author__
__description__: str = __plugin_description__

__plugin_copyright__: str = "Copyright © %s %s" % (
    datetime.now().year,
    __plugin_author__,
)

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {__plugin_author__}"


# Bakåtkompatibilitet: privat alias.
_get_copyright_string = get_copyright_string


# ══════════════════════════════════════════════════════════════════════════════
# LAZY LOADING
# ══════════════════════════════════════════════════════════════════════════════

_cached_plugin_class: Optional[Type["PluginType"]] = None

def get_plugin_class() -> Optional[Type["PluginType"]]:
    """
    Hämta Plugin-klassen (lazy, cachad, kraschsäker).

    Returns:
        Plugin-klassen eller None om plugin.py inte kan importeras
        (t.ex. headless/test) — med debug-logg.
    """
    global _cached_plugin_class
    if _cached_plugin_class is None:
        try:
            module = importlib.import_module(__name__ + ".plugin")
            _cached_plugin_class = module.Plugin
            _log.debug(
                "Plugin-klass laddad: %s v%s",
                __plugin_name__,
                __plugin_version__,
            )
        except ImportError as exc:
            _log.debug(
                "Kunde inte ladda Plugin-klass för '%s': %s",
                __plugin_name__,
                exc,
            )
            return None
        except Exception as exc:
            _log.exception(
                "Oväntat fel vid laddning av Plugin-klass för '%s'.",
                __plugin_name__,
            )
            return None
    return _cached_plugin_class

def get_plugin_info() -> Dict[str, Any]:
    """
    Returnera metadata om pluginet (utan att ladda klassen).

    Returns:
        Dict med name, version, author, description, copyright,
        post_type, dependencies, optional_dependencies, has_ui,
        plugin_class, features, module
    """
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "copyright": get_copyright_string(),
        "post_type": "99",
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(
            __plugin_optional_dependencies__
        ),
        "has_ui": False,
        "plugin_class": "Plugin",
        "features": [
            "pt99_generation",
            "post_count_tracking",
            "checksum",
            "schema_integration",
        ],
        "module": __name__,
    }

def clear_cache() -> None:
    """Rensa lazy-cache. Används vid hot reload."""
    global _cached_plugin_class
    _cached_plugin_class = None
    _log.debug("Cache rensad för end_post.")


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST (PEP 562)
# ══════════════════════════════════════════════════════════════════════════════

def __getattr__(name: str) -> Any:
    """
    Lazy loading av Plugin, EndPostPlugin, PostGenerator,
    EndPostConfig + metadata-fallback (NAME/DESCRIPTION/
    DEPENDENCIES/COPYRIGHT).
    """
    # Plugin + bakåtkompatibelt alias
    if name in ("Plugin", "EndPostPlugin"):
        return get_plugin_class()

    # Övriga namn från plugin.py (PostGenerator, EndPostConfig, ...)
    if name in (
        "PostGenerator",
        "EndPostConfig",
        "get_plugin_safe",
        "get_event_bus",
        "emit_event_safe",
        "subscribe_event_safe",
        "unsubscribe_event_safe",
        "RECORD_LENGTH",
        "TS_ENCODING",
        "FIELD_POSITIONS",
    ):
        try:
            module = importlib.import_module(__name__ + ".plugin")
            return getattr(module, name)
        except Exception as exc:
            raise AttributeError(
                "module '%s' attribute '%s' could not be loaded: %s"
                % (__name__, name, exc)
            ) from exc

    # Metadata-fallback (mallen)
    if name == "NAME":
        return __plugin_name__
    if name == "DESCRIPTION":
        return __plugin_description__
    if name == "DEPENDENCIES":
        return list(__plugin_dependencies__)
    if name == "COPYRIGHT":
        return get_copyright_string()

    raise AttributeError(
        "module '%s' has no attribute '%s'" % (__name__, name)
    )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__: List[str] = [
    # Metadata
    "__plugin_name__",
    "__plugin_version__",
    "__plugin_author__",
    "__plugin_description__",
    "__plugin_copyright__",
    "__version__",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
    "_get_copyright_string",
    # Loaders
    "get_plugin_class",
    "get_plugin_info",
    "clear_cache",
]
