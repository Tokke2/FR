# -*- coding: utf-8 -*-
# Fil: plugins/sap_editor/plugin.py
"""SAP Editor Plugin — lösenordsskyddad redigering av SAP-data (v1.0.1).

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (KRAV 58): filkommentar "# Fil: plugins/sap_editor/plugin.py"
      tillagd (saknades).
    - get_logger() -> _get_logger() (privat, konvention — samma
      mönster som övriga granskade moduler).
    - get_diagnostics() tillagd (standardmönster — plugin-status,
      menyregistrering, editor-UI, versionsinfo) för diagnostik-
      center/support.
    - VERSION bumpad till 1.0.1 (granskad).
    - OBSERVATION (EJ ändrad, inväntar beslut): master v1.4 anger
      sap_editor 2.0.0 (4 filer) och trädet (KRAV 68–73) visar
      plugin.py + ui/editor_window.py (2 filer) — denna leverans är
      v1.0.0. Granskad till v1.0.1; versionssynk sker vid leverans av
      övriga filer (ui/editor_window.py m.fl.).
    - Övrig logik OFÖRÄNDRAD (dual lifecycle init/initialize +
      shutdown/deactivate, menyregistrering via events, open_editor,
      config_schema, kraschsäkra emit-helpers).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from core.plugin_base import PluginBase


def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback om logging ej konfigurerat.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("plugins.sap_editor")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return f"Copyright © {datetime.now().year} Rickard Längkvist"


_log = _get_logger()

NAME = "SAP Editor"
VERSION = "1.0.1"
DESCRIPTION = "Lösenordsskyddad redigering av SAP-data"
AUTHOR = "Rickard Längkvist"
COPYRIGHT = get_copyright_string()
DEPENDENCIES = ["core_auth"]


class Plugin(PluginBase):
    """Plugin för lösenordsskyddad redigering av SAP-data."""

    NAME = NAME
    VERSION = VERSION
    DESCRIPTION = DESCRIPTION
    AUTHOR = AUTHOR
    COPYRIGHT = COPYRIGHT
    DEPENDENCIES = DEPENDENCIES

    def __init__(self, app: Any) -> None:
        """Initiera plugin-instansen."""
        super().__init__(app)
        self.is_active: bool = False
        self._menu_registered: bool = False
        self._initialized: bool = False
        self.show_editor: Optional[Callable[..., Any]] = None

    # -----------------------------------------------------------------
    # Primär livscykel för aktuell appstruktur
    # -----------------------------------------------------------------

    def initialize(self) -> bool:
        """Initiera plugin och koppla editorfönstret."""
        try:
            from .ui.editor_window import show_sap_editor

            self.show_editor = show_sap_editor
            setattr(self.app, "sap_editor", self)
            self._initialized = True

            _log.info("%s v%s initierad", self.NAME, self.VERSION)
            return True

        except Exception as exc:
            self.show_editor = None
            self._initialized = False
            _log.exception("Kunde inte initiera %s: %s", self.NAME, exc)
            return False

    def activate(self) -> bool:
        """Aktivera plugin och registrera menyval."""
        self.is_active = True
        success = self._register_menu()

        if success:
            _log.info("%s aktiverad", self.NAME)
        else:
            _log.warning(
                "%s aktiverad men meny kunde inte registreras",
                self.NAME,
            )

        return success

    def deactivate(self) -> bool:
        """Avaktivera plugin."""
        self.is_active = False
        self._unregister_menu_best_effort()
        _log.info("%s avaktiverad", self.NAME)
        return True

    # -----------------------------------------------------------------
    # Kompatibilitet med striktare plugin-kontrakt
    # -----------------------------------------------------------------

    def init(self) -> bool:
        """Bakåt-/framåtkompatibel alias för initialize()."""
        return self.initialize()

    def register_ui(self, parent: Any) -> None:
        """SAP Editor registrerar meny via event bus och ingen egen tabb här."""
        _ = parent
        return None

    def shutdown(self) -> bool:
        """Bakåt-/framåtkompatibel alias för deactivate()."""
        return self.deactivate()

    def config_schema(self) -> Dict[str, Any]:
        """Returnerar pluginets konfigurationsschema."""
        return {
            "enabled": {
                "type": "boolean",
                "default": True,
                "description": "Aktivera SAP Editor-pluginet.",
            },
            "require_auth": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Kräv autentisering via core_auth innan "
                    "SAP-editor öppnas."
                ),
            },
        }

    # -----------------------------------------------------------------
    # Publika hjälpfunktioner
    # -----------------------------------------------------------------

    def open_editor(self) -> bool:
        """Öppna SAP-editorfönstret."""
        if not callable(self.show_editor):
            _log.error("SAP Editor UI är inte tillgängligt.")
            return False

        try:
            root = getattr(self.app, "root", None)
            self.show_editor(root, self.app)
            _log.info("SAP Editor öppnades")
            return True

        except Exception as exc:
            _log.exception("Kunde inte öppna SAP Editor: %s", exc)
            return False

    def get_diagnostics(self) -> Dict[str, Any]:
        """Hämta diagnostik (standardmönster)."""
        return {
            "plugin_name": self.NAME,
            "plugin_version": VERSION,
            "copyright": get_copyright_string(),
            "initialized": self._initialized,
            "active": self.is_active,
            "menu_registered": self._menu_registered,
            "editor_ui_available": callable(self.show_editor),
            "dependencies": list(DEPENDENCIES),
        }

    # -----------------------------------------------------------------
    # Intern logik
    # -----------------------------------------------------------------

    def _get_event_bus(self) -> Any:
        """Returnerar appens event bus om den finns."""
        return getattr(self.app, "event_bus", None)

    def _emit_safe(
        self,
        event_name: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Emitterar event på säkert sätt mot olika event bus-varianter."""
        bus = self._get_event_bus()
        if bus is None:
            _log.warning(
                "Ingen event_bus tillgänglig för event '%s'",
                event_name,
            )
            return False

        payload = data or {}

        try:
            if hasattr(bus, "emit") and callable(bus.emit):
                bus.emit(event_name, payload)
                return True

            if hasattr(bus, "publish") and callable(bus.publish):
                bus.publish(event_name, payload)
                return True

            _log.warning(
                "Event bus saknar både 'emit' och 'publish' "
                "för event '%s'",
                event_name,
            )
            return False

        except Exception as exc:
            _log.exception(
                "Kunde inte emittera event '%s': %s",
                event_name,
                exc,
            )
            return False

    def _build_menu_payload(self) -> Dict[str, Any]:
        """Bygger payload för menyregistrering."""
        return {
            "menu": "Redigera",
            "items": [
                {
                    "id": "sap_editor.open",
                    "label": "🔧 Redigera SAP-data",
                    "command": self.open_editor,
                }
            ],
        }

    def _register_menu(self) -> bool:
        """Registrera pluginets menyval."""
        payload = self._build_menu_payload()
        success = self._emit_safe("menu:register", payload)

        if success:
            self._menu_registered = True
            _log.info("Meny registrerad för %s", self.NAME)
        else:
            _log.warning(
                "Menyregistrering misslyckades för %s",
                self.NAME,
            )

        return success

    def _unregister_menu_best_effort(self) -> None:
        """Försök att avregistrera menyval om systemet stödjer det."""
        if not self._menu_registered:
            return

        payload = {
            "menu": "Redigera",
            "item_id": "sap_editor.open",
        }

        success = self._emit_safe("menu:unregister", payload)
        if success:
            _log.info("Meny avregistrerad för %s", self.NAME)
        else:
            _log.debug(
                "menu:unregister stöds inte eller misslyckades för %s",
                self.NAME,
            )

        self._menu_registered = False
