# -*- coding: utf-8 -*-
# Fil: plugins/sap_editor/ui/__init__.py
"""UI-paket för SAP Editor-pluginet (v1.0.1).

Exponerar SapEditorWindow och show_sap_editor med kraschsäker
lazy-laddning (PySide6 krävs — headless ska inte krascha paketimport).

Ändringar v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (KRAV 58): filkommentar "# Fil: plugins/sap_editor/ui/
      __init__.py" tillagd (saknades).
    - VERSION/AUTHOR/get_copyright_string tillagda (konvention,
      samma mönster som models/__init__.py och database/__init__.py).
    - FIX (kraschsäkerhet): direkt import utan try/except — om
      PySide6 saknas (headless/test) kunde hela paketet inte
      importeras. Nu: try/except med None-fallback + lazy getters
      (get_editor_window/get_show_editor) + __getattr__.
    - __all__ kompletterad med get_copyright_string.
    - Övrig logik OFÖRÄNDRAD (exporter).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Optional

_log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "1.0.1"
AUTHOR: str = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTER (kraschsäkra — PySide6 krävs för UI)
# ══════════════════════════════════════════════════════════════════════════════

try:
    from .editor_window import SapEditorWindow, show_sap_editor
except ImportError:  # pragma: no cover — PySide6 saknas (headless)
    SapEditorWindow = None  # type: ignore
    show_sap_editor = None  # type: ignore

    def _no_pyside(*args: Any, **kwargs: Any) -> None:
        """Fallback när PySide6 saknas."""
        _log.error("PySide6 saknas — SAP Editor-UI ej tillgängligt.")

    # Ersätt show_sap_editor med tydlig fallback-funktion
    def show_sap_editor(*args: Any, **kwargs: Any) -> bool:  # type: ignore
        """Fallback som loggar och returnerar False."""
        _log.error(
            "PySide6 saknas — SAP Editor-UI ej tillgängligt "
            "(show_sap_editor)."
        )
        return False


def get_editor_window() -> Optional[Any]:
    """Hämta SapEditorWindow-klassen (eller None om PySide6 saknas)."""
    return SapEditorWindow


def get_show_editor() -> Optional[Any]:
    """Hämta show_sap_editor-funktionen (eller None om PySide6 saknas)."""
    return show_sap_editor


def __getattr__(name: str) -> Any:
    """Dynamisk attributåtkomst för bakåtkompatibilitet."""
    if name in ("SapEditorWindow", "show_sap_editor"):
        if name == "SapEditorWindow":
            return get_editor_window()
        return get_show_editor()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__: List[str] = [
    "SapEditorWindow",
    "show_sap_editor",
    "get_editor_window",
    "get_show_editor",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]
