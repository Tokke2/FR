# -*- coding: utf-8 -*-
# Fil: plugins/gui_helpers/components/__init__.py

"""
GUI Helper Components v1.0.1

Återanvändbara GUI-komponenter för hela systemet (paketinit med
lazy-laddning av submodulerna).

Komponenter:
    - buttons: Anpassade knappar (create_button, PrimaryButton-token, etc.)
    - dialogs: Dialoger (ConfirmDialog, ProgressDialog, etc.)
    - forms: Formulärkomponenter (FormField, DynamicForm, etc.)
    - validators: Valideringsfunktioner (VIN, datum, etc.)
    - styles: Stil-konstanter och teman (design-tokens)

Användning:
    from plugins.gui_helpers.components import buttons   # lazy
    from plugins.gui_helpers.components.buttons import create_button

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil: plugins/gui_helpers/components/
    __init__.py" tillagd (saknades — stod utan "Fil:"-prefix).
  - FIX (låst regel, inga hårdkodade årtal): COPYRIGHT_YEAR_START
    (2024) BORT — get_copyright_string() returnerar enbart
    innevarande år, konsistent med övriga moduler. Docstring-
    placeholdern "{current_year}" ersatt med dynamisk formulering.
  - FIX (låst regel, lazy %s): _StubModule-varningen använde
    f-string i logganrop → lazy %s-format ("Component '%s' är inte
    tillgänglig...", self._name).
  - FIX (korrekthet): get_button_classes() matchade
    name.endswith("Button") men buttons.py har inga klasser som
    slutar på "Button" (endast create_button m.fl.) → returnerade
    alltid {}. Matchar nu create_*-fabrikerna + BUTTON_STYLES
    (dokumenterat som "knapp-fabriker").
  - FIX (korrekthet): get_form_classes() missade DynamicForm —
    matchningen täcker nu name.endswith("Form") (fångat av
    runtime-test).
  - FIX (dödkod): oanvänd sys-import bort; _module_cache-typerna
    förtydligade; _COMPONENT_NAMES som namngiven konstant (i
    stället för att filtrera __all__ med strängjämförelse);
    __dir__ får retur-typ.
  - TILLÄGG (konsistens): VERSION + i __all__; get_copyright_string
    publik (var redan).
  - Övrig logik OFÖRÄNDRAD (lazy importlib + cache, _StubModule,
    _stub_function, get_dialog_classes/get_form_classes/
    get_validators, is_component_available, list_available_components).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any, Dict, List, Optional

AUTHOR: str = "Rickard Längkvist"
VERSION: str = "1.0.1"

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# Komponentmoduler (namngiven konstant — källa för __getattr__).
_COMPONENT_NAMES: List[str] = [
    "buttons",
    "dialogs",
    "forms",
    "validators",
    "styles",
]

# Modul-cache för att undvika upprepade imports.
_module_cache: Dict[str, Any] = {}

__all__: List[str] = [
    "buttons",
    "dialogs",
    "forms",
    "validators",
    "styles",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]

def _import_submodule(name: str) -> Optional[Any]:
    """
    Importera en submodul säkert.

    Args:
        name: Namn på submodulen

    Returns:
        Importerad modul eller None om den inte finns
    """
    # Kolla cache först
    if name in _module_cache:
        return _module_cache[name]

    # Försök importera
    full_name = "%s.%s" % (__name__, name)

    try:
        module = importlib.import_module(full_name)
        _module_cache[name] = module
        return module
    except ImportError:
        # Modulen finns inte - returnera None
        _module_cache[name] = None
        return None
    except Exception:
        # Annat fel - returnera None
        _module_cache[name] = None
        return None

def __getattr__(name: str) -> Any:
    """
    Lazy loading av komponenter.

    Använder importlib.import_module() för att undvika rekursion.
    """
    if name in _COMPONENT_NAMES:
        module = _import_submodule(name)
        if module is not None:
            # Sätt attributet på modulen för framtida direktåtkomst
            globals()[name] = module
            return module
        # Returnera en dummy-modul så att imports inte kraschar
        return _create_stub_module(name)

    raise AttributeError(
        "module %r has no attribute %r" % (__name__, name)
    )

def __dir__() -> List[str]:
    """Returnera tillgängliga attribut."""
    return __all__

class _StubModule:
    """
    Stub-modul som returneras när en komponent saknas.

    Gör att programmet inte kraschar om en komponentfil saknas.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._warned = False

    def __getattr__(self, attr: str) -> Any:
        if not self._warned:
            import logging
            logging.getLogger(__name__).warning(
                "Komponent '%s' är inte tillgänglig — attribut '%s' "
                "returnerar en stub.",
                self._name,
                attr,
            )
            self._warned = True

        # Returnera en funktion som inte gör något
        return _stub_function

    def __repr__(self) -> str:
        return "<StubModule: %s (not available)>" % self._name

def _stub_function(*args: Any, **kwargs: Any) -> None:
    """Stub-funktion som inte gör något."""
    pass

def _create_stub_module(name: str) -> _StubModule:
    """Skapa en stub-modul för saknad komponent."""
    return _StubModule(name)


# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE ACCESSORS
# ══════════════════════════════════════════════════════════════════════════════
# Komponenterna exporteras INTE vid import (undviker cirkulära
# imports). Använd i stället:
#     from plugins.gui_helpers.components import buttons

def get_button_classes() -> Dict[str, Any]:
    """
    Hämta knapp-fabrikerna (create_button, create_icon_button,
    create_button_group) + BUTTON_STYLES.

    Returns:
        Dict med knapp-fabriker (tom om komponenten saknas)
    """
    buttons_mod = _import_submodule("buttons")
    if buttons_mod is None:
        return {}

    result: Dict[str, Any] = {}
    for name in dir(buttons_mod):
        if name.startswith("create_") or name == "BUTTON_STYLES":
            value = getattr(buttons_mod, name)
            if callable(value) or name == "BUTTON_STYLES":
                result[name] = value
    return result

def get_dialog_classes() -> Dict[str, Any]:
    """
    Hämta alla dialogklasser.

    Returns:
        Dict med dialogklasser (tom om komponenten saknas)
    """
    dialogs_mod = _import_submodule("dialogs")
    if dialogs_mod is None:
        return {}

    return {
        name: getattr(dialogs_mod, name)
        for name in dir(dialogs_mod)
        if name.endswith("Dialog") and not name.startswith("_")
    }

def get_form_classes() -> Dict[str, Any]:
    """
    Hämta alla formulärklasser.

    Returns:
        Dict med formulärklasser (tom om komponenten saknas)
    """
    forms_mod = _import_submodule("forms")
    if forms_mod is None:
        return {}

    return {
        name: getattr(forms_mod, name)
        for name in dir(forms_mod)
        if (
            name.startswith("Form")
            or name.endswith("Form")   # t.ex. DynamicForm
            or name.endswith("Field")
        ) and not name.startswith("_")
    }

def get_validators() -> Dict[str, Any]:
    """
    Hämta alla valideringsfunktioner.

    Returns:
        Dict med valideringsfunktioner (tom om komponenten saknas)
    """
    validators_mod = _import_submodule("validators")
    if validators_mod is None:
        return {}

    return {
        name: getattr(validators_mod, name)
        for name in dir(validators_mod)
        if name.startswith("validate_")
        and callable(getattr(validators_mod, name))
    }

def is_component_available(name: str) -> bool:
    """
    Kontrollera om en komponent är tillgänglig.

    Args:
        name: Komponentnamn

    Returns:
        True om komponenten finns
    """
    module = _import_submodule(name)
    return module is not None and not isinstance(module, _StubModule)

def list_available_components() -> List[str]:
    """
    Lista alla tillgängliga komponenter.

    Returns:
        Lista med komponentnamn som finns
    """
    available = []
    for name in _COMPONENT_NAMES:
        if is_component_available(name):
            available.append(name)
    return available
