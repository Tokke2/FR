# -*- coding: utf-8 -*-
# Fil: plugins/main_gui/dialogs/__init__.py

"""
Main GUI — Dialogpaket v1.0.1

Paketinit för dialog-modulerna under plugins/main_gui/dialogs/
(vin_report_dialog, password_dialog, import_progress) med lazy-
laddning enligt mallen (ts_spec_import v4.0.2 / main_gui/__init__.py
v1.0.1). Gör dialogs till ett PYTHONPAKET så att relativa importer
löses i IDE/typkontroll (Pylance):

    from .dialogs.import_progress import ProgressContext
    from .dialogs.password_dialog import require_pin
    from .dialogs import PasswordDialog          (lazy via __getattr__)

Klasserna laddas LAZY (get_dialog/__getattr__) så att en headless-
import av paketet inte kräver PySide6 (kraschsäkert: None + logg om
modulen inte kan importeras).

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - NY VERSION av inklistrad minimal stub (endast docstring).
    - KRAV 58: "# Fil: plugins/main_gui/dialogs/__init__.py"
      tillagd (saknades — stubben hade bara docstring).
    - FIX (KRAV 56): paketlänkning — relativa importer löses i
      IDE/typkontroll; från-import fungerar via __getattr__ (PEP 562).
    - Fullt lazy-mönster enligt mallen: metadata (name/version/
      author/description/dependencies/optional_dependencies),
      get_dialog() (kraschsäker — returnerar None med logg om
      PySide6 saknas i headless), get_dialogs_info() (+ dialogs/
      modules/has_ui/copyright färskt), clear_cache(), __getattr__
      (dialogklasser + VERSION/AUTHOR/NAME/DESCRIPTION/DEPENDENCIES/
      COPYRIGHT färskt).
    - VERSION/AUTHOR ("Rickard Längkvist") + dynamisk copyright.
FÖRÄNDRINGAR v1.0.0:
    - NY FIL (inklistrad original): minimal stub (ersatt av v1.0.1).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import importlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .vin_report_dialog import VinReportDialog as VinReportDialogType
    from .password_dialog import (
        PasswordDialog as PasswordDialogType,
        PinDialog as PinDialogType,
        PasswordValidator as PasswordValidatorType,
        PasswordEntry as PasswordEntryType,
        StrengthMeter as StrengthMeterType,
    )
    from .import_progress import (
        ImportProgressDialog as ImportProgressDialogType,
        ProgressContext as ProgressContextType,
        ProgressState as ProgressStateType,
    )

# ══════════════════════════════════════════════════════════════════════════════
# LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log: logging.Logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# METADATA
# ══════════════════════════════════════════════════════════════════════════════

__plugin_name__: str = "Main GUI — Dialoger"
__plugin_version__: str = "1.0.1"
__plugin_author__: str = "Rickard Längkvist"
__plugin_description__: str = (
    "Dialog-moduler för Main GUI (VIN-rapport, lösenord/PIN, "
    "import-progress) — PySide6"
)
__plugin_dependencies__: List[str] = []
__plugin_optional_dependencies__: List[str] = [
    "vin_tracking",       # vin_report_dialog (load_registry, generate_yearly_report)
    "core_auth",          # password_dialog (PIN-kedja, get_pin)
    "settings_manager",   # password_dialog (get_setting/set_setting)
    "transportstyrelsen", # password_dialog (get_config/update_config)
]

__plugin_copyright__: str = "Copyright © %s %s" % (
    datetime.now().year,
    __plugin_author__,
)

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {__plugin_author__}"


VERSION: str = __plugin_version__
AUTHOR: str = __plugin_author__


# ══════════════════════════════════════════════════════════════════════════════
# LAZY-LADDNING (namn → modul)
# ══════════════════════════════════════════════════════════════════════════════

_DIALOG_MODULES: Dict[str, str] = {
    "VinReportDialog": "vin_report_dialog",
    "PasswordDialog": "password_dialog",
    "PinDialog": "password_dialog",
    "PasswordValidator": "password_dialog",
    "PasswordEntry": "password_dialog",
    "StrengthMeter": "password_dialog",
    "require_pin": "password_dialog",
    "change_password": "password_dialog",
    "ImportProgressDialog": "import_progress",
    "ProgressContext": "import_progress",
    "ProgressState": "import_progress",
    "run_with_progress": "import_progress",
}

_cached_dialogs: Dict[str, Any] = {}


# ══════════════════════════════════════════════════════════════════════════════
# ÅTKOMSTFUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def get_dialog(name: str) -> Optional[Any]:
    """
    Hämta dialog-klass/-funktion lazy (cachad, kraschsäker).

    Returnerar None om modulen inte kan importeras (t.ex. PySide6
    saknas i headless/test) — med debug-logg.

    Args:
        name: Namn enligt _DIALOG_MODULES (t.ex. "PasswordDialog")

    Returns:
        Klass/funktion eller None
    """
    if name in _cached_dialogs:
        return _cached_dialogs[name]

    module_name = _DIALOG_MODULES.get(name)
    if module_name is None:
        _log.debug("Okänd dialog: %s", name)
        return None

    try:
        module = importlib.import_module(
            "{}.{}".format(__name__, module_name)
        )
        value = getattr(module, name)
    except Exception as exc:
        _log.debug(
            "Kunde inte ladda %s från %s: %s",
            name,
            module_name,
            exc,
        )
        return None

    _cached_dialogs[name] = value
    return value

def get_dialogs_info() -> Dict[str, Any]:
    """Metadata om paketet och dess dialoger (utan att ladda dem)."""
    return {
        "name": __plugin_name__,
        "version": __plugin_version__,
        "author": __plugin_author__,
        "description": __plugin_description__,
        "dependencies": list(__plugin_dependencies__),
        "optional_dependencies": list(__plugin_optional_dependencies__),
        "dialogs": list(_DIALOG_MODULES.keys()),
        "modules": sorted(set(_DIALOG_MODULES.values())),
        "has_ui": True,
        "copyright": get_copyright_string(),
    }

def clear_cache() -> None:
    """Rensa lazy-cache. Används vid hot reload."""
    _cached_dialogs.clear()
    _log.debug("Cache rensad för main_gui.dialogs.")

# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK ATTRIBUTÅTKOMST (PEP 562)
# ══════════════════════════════════════════════════════════════════════════════

def __getattr__(name: str) -> Any:
    """Dynamisk attributåtkomst: dialogklasser + metadata (lazy)."""
    if name in _DIALOG_MODULES:
        return get_dialog(name)
    if name == "NAME":
        return __plugin_name__
    if name == "DESCRIPTION":
        return __plugin_description__
    if name == "DEPENDENCIES":
        return list(__plugin_dependencies__)
    if name == "COPYRIGHT":
        return get_copyright_string()
    raise AttributeError(
        "module 'plugins.main_gui.dialogs' has no attribute '{}'".format(name)
    )


__all__: List[str] = [
    "get_dialog",
    "get_dialogs_info",
    "clear_cache",
    "get_copyright_string",
    "VERSION",
    "AUTHOR",
    "VinReportDialog",
    "PasswordDialog",
    "PinDialog",
    "PasswordValidator",
    "PasswordEntry",
    "StrengthMeter",
    "require_pin",
    "change_password",
    "ImportProgressDialog",
    "ProgressContext",
    "ProgressState",
    "run_with_progress",
]
