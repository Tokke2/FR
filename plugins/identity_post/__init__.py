# -*- coding: utf-8 -*-
# Fil: plugins/identity_post/__init__.py

"""
Identity Post Plugin — Package Init v3.2.1

Genererar identitetsposter (posttyp 28) för Transportstyrelsen.

EXPORTERAR:
  Plugin              — Identity Post plugin-klass
  IdentityPostPlugin  — Bakåtkompatibelt alias
  IdentityConfig      — Konfigurationsdataclass
  DataNormalizer      — VIN/år/orgnr-normalisering
  PostGenerator       — PT28-generering (schema + fallback)
  ModelYearValidator  — Dispatch vs SAP validering

METADATA:
  __plugin_name__        = "Identity Post"
  __plugin_version__     = "3.2.1"
  __plugin_author__      = "Rickard Längkvist"
  __plugin_description__ = "Genererar identitetsposter (PT28)"

Användning:
    >>> result = app.identity_post.generate_post()
    >>> print(result['post'])  # 2500 tecken

    >>> app.event_bus.emit("identity_post:generate", {...})

Se även:
    - ts_spec_import: Hämtar PT28-schema
    - end_post: Genererar PT99 (slutpost)
    - vehicle_registration_post: Genererar PT45

FÖRÄNDRINGAR v3.2.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (versionsharmonisering): __plugin_version__ 3.2.0 → 3.2.1
    (matchar plugin.py v3.2.1 — spec-regeln att versioner ska vara
    konsistenta inom plugin); __version__/VERSION uppdaterade.
  - FIX (KRAV 58): "# Fil: plugins/identity_post/__init__.py"
    tillagd (saknades — stod utan "Fil:"-prefix).
  - FIX (stabilitet, mallen): get_plugin_class() kastar INTE längre
    ImportError — returnerar None med debug-logg om plugin.py inte
    kan importeras (kraschsäkert headless, samma mönster som
    main_gui/__init__.py v1.0.1 och dialogs/__init__.py v1.0.1).
    Normal drift påverkas inte (plugin.py har inga PySide6-beroenden
    — importeras direkt i appen).
  - FIX (konsistens): publik get_copyright_string() tillagd +
    privat alias _get_copyright_string behållet (bakåtkompatibilitet,
    samma mönster som identity_post/plugin.py v3.2.1).
  - TILLÄGG (mallen): VERSION/AUTHOR som modulvariabler +
    __getattr__-fallback för NAME/DESCRIPTION/DEPENDENCIES/COPYRIGHT.
  - __all__ utökad (get_copyright_string, VERSION, AUTHOR,
    _get_copyright_string).
  - Övrig logik OFÖRÄNDRAD (lazy-cache, get_plugin_info med
    post_type/events/has_ui, __getattr__ för hjälpklasserna).
FÖRÄNDRINGAR v3.2.0:
  - NY FIL (inklistrad original): paketinit med lazy-laddning.
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import (
        Plugin as PluginType,
        IdentityConfig as IdentityConfigType,
        DataNormalizer as DataNormalizerType,
        PostGenerator as PostGeneratorType,
        ModelYearValidator as ModelYearValidatorType,
    )

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log: logging.Logger = logging.getLogger("identity_post")

# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "Identity Post"
__plugin_version__: str = "3.2.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Genererar identitetsposter (PT28) med ts_spec_import-stöd"
)
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "ts_spec_import",
    "core_config",
    "sap_import",
    "core_logger",
]
__version__: str = __plugin_version__
__author__: str = __plugin_author__
__description__: str = __plugin_description__

COPYRIGHT_YEAR: int = datetime.now().year
__plugin_copyright__: str = (
    f"Copyright © {COPYRIGHT_YEAR} {__plugin_author__}"
)

VERSION: str = __plugin_version__
AUTHOR: str = __plugin_author__

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
        (t.ex. headless/test utan core.plugin_base) — med logg.
    """
    global _cached_plugin_class
    if _cached_plugin_class is None:
        try:
            from .plugin import Plugin
            _cached_plugin_class = Plugin
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
    Hämta plugin-metadata utan att ladda klassen.

    Returns:
        Dict med name, version, author, description, copyright
    """
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "copyright": get_copyright_string(),
        "post_type": "28",
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(
            __plugin_optional_dependencies__
        ),
        "has_ui": False,
        "events": {
            "emits": [
                "identity_post:activated",
                "identity_post:generated",
                "identity_post:config_updated",
            ],
            "listens": [
                "identity_post:generate",
                "identity_post:validate",
                "ts_spec:version_changed",
                "ts_spec:imported",
            ],
        },
    }

def clear_cache() -> None:
    """Rensa lazy-laddad klass. Används vid hot reload."""
    global _cached_plugin_class
    _cached_plugin_class = None
    _log.debug("Cache rensad för identity_post.")


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST
# ══════════════════════════════════════════════════════════════════════════════

def __getattr__(name: str) -> Any:
    """
    Lazy loading av Plugin, IdentityPostPlugin, IdentityConfig,
    DataNormalizer, PostGenerator, ModelYearValidator, FileHandler
    + metadata-fallback (NAME/DESCRIPTION/DEPENDENCIES/COPYRIGHT).
    """
    if name == "Plugin":
        return get_plugin_class()

    if name == "IdentityPostPlugin":
        return get_plugin_class()

    if name in (
        "IdentityConfig",
        "DataNormalizer",
        "PostGenerator",
        "ModelYearValidator",
        "FileHandler",
    ):
        try:
            from . import plugin as _plugin_module
            return getattr(_plugin_module, name)
        except Exception as exc:
            raise AttributeError(
                "module 'plugins.identity_post' attribute '{}' "
                "could not be loaded: {}".format(name, exc)
            ) from exc

    if name == "NAME":
        return __plugin_name__
    if name == "DESCRIPTION":
        return __plugin_description__
    if name == "DEPENDENCIES":
        return list(__plugin_dependencies__)
    if name == "COPYRIGHT":
        return get_copyright_string()

    raise AttributeError(
        "module 'plugins.identity_post' has no attribute '{}'".format(name)
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
