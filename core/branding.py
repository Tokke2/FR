"""Gemensamt appnamn utan att skriva över användarens konfiguration."""
from __future__ import annotations

import logging
import sys

APP_NAME = "Fordonsreg"
LEGACY_NAMES = frozenset({"Filregistrering", "Transportstyrelsen Fordonsregistreringssystem", "TADEGA Fordonsregistrering"})


def display_name(value: object) -> str:
    """Byt historiska standardnamn i minnet; bevara anpassade namn."""
    name = str(value or "")
    return APP_NAME if not name.strip() or name.strip() in LEGACY_NAMES else name


def set_windows_app_id() -> bool:
    """Hjälp Windows att gruppera programmets fönster rätt i aktivitetsfältet."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("se.langkvist.fordonsreg")
        if result != 0:
            logging.getLogger(__name__).warning("Windows AppUserModelID kunde inte sättas: %s", result)
            return False
        return True
    except Exception:
        logging.getLogger(__name__).exception("Kunde inte sätta Windows AppUserModelID")
        return False
