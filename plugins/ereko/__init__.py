# -*- coding: utf-8 -*-
# Fil: plugins/ereko/__init__.py

"""
eReKo / IVI Generator Plugin — Package Init v1.0.1

Lazy-laddning och metadata-åtkomst enligt mallen (ts_spec_import
v4.0.2 / identity_post v3.2.1 / main_gui v1.0.1). Gör ereko till ett
PYTHONPAKET så att relativa importer löses i IDE/typkontroll.

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil: plugins/ereko/__init__.py" tillagd
    (saknades — stod utan "Fil:"-prefix).
  - FIX (versionsharmonisering): __version__ 1.0.0 → 1.0.1
    (matchar plugin.py + models.py v1.0.1 — spec-regeln om
    konsistenta versioner inom plugin); __plugin_version__/
    VERSION uppdaterade.
  - FIX (låst regel, inga hårdkodade årtal): docstringens
    "Copyright © 2025" bort — dynamisk copyright via
    get_copyright_string() (konsistent med plugin.py/models.py).
  - FIX (stabilitet, mallen): get_plugin_class() kastar INTE längre
    ImportError — returnerar None med debug-logg om plugin.py inte
    kan importeras (kraschsäkert headless, samma mönster som
    identity_post/__init__.py v3.2.1). Normal drift påverkas inte.
  - FIX (korrekthet, rekursion — fångat av runtime-test):
    get_models_module() använde "from . import models" som triggar
    paketets __getattr__("models") via import-maskineriets hasattr
    → oändlig rekursion. Nu: importlib.import_module(__name__ +
    ".models") med fullständigt namn (samma mönster som
    main_gui/dialogs). get_plugin_class() uppdaterad på samma sätt
    (importlib i stället för "from .plugin import Plugin").
  - FIX (konsistens): publik get_copyright_string() + privat alias
    _get_copyright_string (bakåtkompatibilitet, samma mönster som
    plugin.py v1.0.1); VERSION/AUTHOR som modulvariabler;
    __getattr__-fallback för NAME/DESCRIPTION/DEPENDENCIES/
    COPYRIGHT; clear_cache() tillagd (mallen — hot reload).
  - TILLÄGG (mallen): get_plugin_info() utökad med
    "plugin_class": "Plugin", "features" och "has_ui": True
    (metadata-kontraktet).
  - TYP-fix: _plugin_class: Optional[type] → Optional[Type["Plugin"]].
  - FIX (radbrytningsartefakt): dubblerade blankrader före
    def/class kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (lazy get_models_module, __getattr__-
    kedja plugin.py → models.py, __all__-struktur).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original).
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
# METADATA (för plugin discovery)
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "eReKo / IVI Generator"
__plugin_version__: str = "1.0.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Generering av elektroniska registreringsbevis (IVI/eCoC) "
    "enligt EU-standard"
)

VERSION: str = __plugin_version__
AUTHOR: str = __plugin_author__
__version__: str = __plugin_version__
__author__: str = __plugin_author__
__description__: str = __plugin_description__

def get_copyright_year() -> int:
    """Hämta aktuellt år."""
    return datetime.now().year

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {get_copyright_year()} {AUTHOR}"


# Bakåtkompatibilitet: privat alias.
_get_copyright_string = get_copyright_string

__copyright__: str = get_copyright_string()

__dependencies__: List[str] = []  # Inga hårda beroenden

__optional_dependencies__: List[str] = [
    "vehicle_registry",
    "colors_manager",
    "dealers_manager",
    "sap_import",
    "dispatch_viewer",
    "ts_spec_import",
]


# ══════════════════════════════════════════════════════════════════════════════
# LAZY LOADING
# ══════════════════════════════════════════════════════════════════════════════

_plugin_class: Optional[Type["PluginType"]] = None
_models_module: Optional[Any] = None

def get_plugin_info() -> Dict[str, Any]:
    """
    Hämta plugin-metadata utan att ladda plugin-klassen.

    Används av plugin_loader för discovery.

    Returns:
        Dict med metadata
    """
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "copyright": get_copyright_string(),
        "dependencies": list(__dependencies__),
        "optional_dependencies": list(__optional_dependencies__),
        "has_ui": True,
        "module": __name__,
        "plugin_class": "Plugin",
        "features": [
            "ivi_generation",
            "batch_generation",
            "ivi_validation",
            "eucaris_export",
            "generation_log",
        ],
    }

def get_plugin_class() -> Optional[Type["PluginType"]]:
    """
    Hämta plugin-klassen (lazy, cachad, kraschsäker).

    Laddar endast vid första anropet.

    Returns:
        Plugin-klass eller None om plugin.py inte kan importeras
        (t.ex. headless/test) — med debug-logg.
    """
    global _plugin_class

    if _plugin_class is None:
        try:
            module = importlib.import_module(__name__ + ".plugin")
            _plugin_class = module.Plugin
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

    return _plugin_class

def get_models_module() -> Optional[Any]:
    """
    Hämta models-modulen (lazy, cachad, kraschsäker).

    Returns:
        models-modul eller None om den inte kan importeras
    """
    global _models_module

    if _models_module is None:
        try:
            _models_module = importlib.import_module(
                __name__ + ".models"
            )
        except ImportError as exc:
            _log.debug("Kunde inte ladda models-modulen: %s", exc)
            return None
        except Exception as exc:
            _log.exception("Oväntat fel vid laddning av models.")
            return None

    return _models_module

def clear_cache() -> None:
    """Rensa lazy-cache. Används vid hot reload."""
    global _plugin_class, _models_module
    _plugin_class = None
    _models_module = None
    _log.debug("Cache rensad för ereko.")


# ══════════════════════════════════════════════════════════════════════════════
# LAZY ATTRIBUTE ACCESS
# ══════════════════════════════════════════════════════════════════════════════

def __getattr__(name: str) -> Any:
    """
    Lazy loading via attribute access.

    Tillåter:
        from plugins.ereko import Plugin
        from plugins.ereko import IVIDocument
        from plugins.ereko import FuelType

    utan att ladda allt direkt (kedja: plugin.py → models.py →
    metadata-fallback).

    Args:
        name: Attributnamn

    Returns:
        Attribut från plugin.py eller models.py

    Raises:
        AttributeError: Om attributet inte finns
    """
    # Försök ladda från plugin.py
    try:
        plugin_cls = get_plugin_class()
        if plugin_cls is not None:
            mod = importlib.import_module(plugin_cls.__module__)
            if hasattr(mod, name):
                return getattr(mod, name)
    except (ImportError, AttributeError):
        pass

    # Försök ladda från models.py
    try:
        models = get_models_module()
        if models is not None and hasattr(models, name):
            return getattr(models, name)
    except (ImportError, AttributeError):
        pass

    # Metadata-fallback (mallen)
    if name == "NAME":
        return __plugin_name__
    if name == "DESCRIPTION":
        return __plugin_description__
    if name == "DEPENDENCIES":
        return list(__dependencies__)
    if name == "COPYRIGHT":
        return get_copyright_string()

    # Om inget hittas, kasta AttributeError
    raise AttributeError(
        "module '%s' has no attribute '%s'" % (__name__, name)
    )


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API (optional — för explicit import)
# ══════════════════════════════════════════════════════════════════════════════

__all__: List[str] = [
    # Metadata
    "__plugin_name__",
    "__plugin_version__",
    "__plugin_author__",
    "__plugin_description__",
    "__copyright__",
    "__dependencies__",
    "__optional_dependencies__",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
    "_get_copyright_string",
    # Discovery functions
    "get_plugin_info",
    "get_plugin_class",
    "get_models_module",
    "clear_cache",
]
