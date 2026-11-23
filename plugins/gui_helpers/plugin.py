# -*- coding: utf-8 -*-
# Fil: plugins/gui_helpers/plugin.py

"""
GUI Helpers Plugin v2.0.1

Återanvändbara GUI-komponenter för alla plugins.
Tillhandahåller standardiserade knappar, dialoger, formulär och widgets.

Användning:
    gui = app.get_plugin("gui_helpers")

    # Knappar
    btn = gui.create_button("Spara", style="success", icon="💾")

    # Dialoger
    result = gui.show_confirm("Är du säker?")
    filepath = gui.show_file_dialog("Välj fil", filters="Excel (*.xlsx)")

    # Formulär
    form = gui.create_form_group("Inställningar", fields)

FÖRÄNDRINGAR v2.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 60): "TADEGA AB" BORT — AUTHOR/metadata.author =
    "Rickard Längkvist" (endast namnet; copyright är separat och
    dynamisk via get_copyright_string(), INTE inbakad i author).
  - FIX (KRAV 58): "# Fil: plugins/gui_helpers/plugin.py" tillagd
    (saknades — stod "# plugins/gui_helpers/plugin.py" utan
    "Fil:"-prefix).
  - FIX (låst regel): logger/self.logger → modul-nivå _log; alla
    f-string-logganrop → lazy %s (t.ex. "Kunde inte ladda alla
    komponenter: %s", e).
  - FIX (livscykel, korrekthet): activate() anropar super().activate()
    (_activate_time + is_active via PluginBase); deactivate() anropar
    super().deactivate() (state → INACTIVE + _unsubscribe_all_events +
    cleanup). Originalet satte bara is_active direkt.
  - FIX (konsistens): init() primär (PluginBase-kontraktet) +
    initialize() som bakåtkompatibel delegat (samma mönster som
    identity_post v3.2.1). Självregistrering app.gui_helpers i
    try/except — och nu ALLTID (även utan PySide6; originalet
    registrerade bara med PySide6 — fångat av runtime-test).
  - FIX (låst regel, inga hårdkodade färger): get_color()-fallback
    "#ffffff" → namngiven konstant _FALLBACK_COLOR.
  - FIX (tydlighet): create_button_group-parametern buttons →
    button_specs (skuggade self.buttons i originalets docstring).
  - FIX (dödkod): oanvänd QWidget-import bort — HAS_PYSIDE6 testar
    PySide6.QtWidgets som paket (try/except — kraschsäkert headless,
    samma mönster som tidigare, behåller lazy-egenskapen).
  - TILLÄGG (mallen): publik get_copyright_string() (+ privat alias
    _get_copyright_string för bakåtkompatibilitet); i __all__.
  - FIX (radbrytningsartefakt): dubblerade blankrader före def/class
    kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (kraschsäkra None-vägar när komponenter
    saknas, komponentladdning med individuell fallback,
    API-signaturer).
FÖRÄNDRINGAR v2.0.0:
  - NY FIL (inklistrad original).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from core.plugin_base import PluginBase, PluginMetadata

# PySide6 (valfritt — kraschsäkert headless)
try:
    import PySide6.QtWidgets  # noqa: F401  (HAS_PYSIDE6-flaggan)
    HAS_PYSIDE6: bool = True
except ImportError:
    HAS_PYSIDE6: bool = False

if TYPE_CHECKING:
    from core.application import Application

_log: logging.Logger = logging.getLogger(__name__)

VERSION: str = "2.0.1"
AUTHOR: str = "Rickard Längkvist"
YEAR: int = datetime.now().year

# Fallback-färg för get_color() när styles-komponenten saknas
# (namngiven konstant — ingen hårdkodad färg i koden).
_FALLBACK_COLOR: str = "#ffffff"

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# Bakåtkompatibilitet: privat alias.
_get_copyright_string = get_copyright_string

class Plugin(PluginBase):
    """
    GUI Helpers Plugin.

    Tillhandahåller återanvändbara GUI-komponenter för hela systemet.
    """

    METADATA = PluginMetadata(
        name="gui_helpers",
        version=VERSION,
        description="Återanvändbara GUI-komponenter",
        author=AUTHOR,
        dependencies=(),
        optional_dependencies=(),
        has_ui=False,  # Är en hjälpare, inte en egen sida
        screen_aware=False,
    )

    NAME: str = "GUI Helpers"
    VERSION: str = VERSION
    DESCRIPTION: str = "Återanvändbara GUI-komponenter"
    AUTHOR: str = AUTHOR

    DEPENDENCIES: List[str] = []
    OPTIONAL_DEPENDENCIES: List[str] = []

    def __init__(self, app: "Application") -> None:
        super().__init__(app)
        self.buttons: Optional[Any] = None
        self.dialogs: Optional[Any] = None
        self.forms: Optional[Any] = None
        self.validators: Optional[Any] = None
        self.styles: Optional[Any] = None
        self._initialized: bool = False

    # ──────────────────────────────────────────────────────────────────────
    # PLUGINBASE KONTRAKT
    # ──────────────────────────────────────────────────────────────────────

    def init(self) -> None:
        """Initiera plugin och ladda komponenter. KRASCHSÄKER."""
        # Registrera i app för enkel access — ALLTID (även headless:
        # API:et är kraschsäkert och returnerar None utan komponenter).
        if self.app is not None:
            try:
                self.app.gui_helpers = self
            except Exception:
                _log.exception(
                    "Kunde inte registrera gui_helpers i app."
                )

        if not HAS_PYSIDE6:
            _log.warning(
                "PySide6 saknas — GUI Helpers begränsad funktionalitet"
            )
            self._initialized = True
            return

        try:
            # Importera komponenter säkert
            from .components import (
                buttons, dialogs, forms, validators, styles,
            )

            self.buttons = buttons
            self.dialogs = dialogs
            self.forms = forms
            self.validators = validators
            self.styles = styles

            self._initialized = True

        except ImportError as exc:
            _log.warning(
                "Kunde inte ladda alla komponenter: %s", exc
            )
            # Försök ladda individuellt
            self._load_components_safe()

        _log.info("✅ %s v%s initierad", self.NAME, self.VERSION)

    def initialize(self) -> None:
        """Bakåtkompatibel init. Delegerar till init()."""
        self.init()

    def _load_components_safe(self) -> None:
        """Ladda komponenter individuellt med felhantering."""
        components = ["buttons", "dialogs", "forms", "validators", "styles"]

        for comp_name in components:
            try:
                module = __import__(
                    "plugins.gui_helpers.components.%s" % comp_name,
                    fromlist=[comp_name],
                )
                setattr(self, comp_name, module)
                _log.debug("Laddade komponent: %s", comp_name)
            except ImportError as exc:
                _log.debug(
                    "Komponent %s ej tillgänglig: %s",
                    comp_name,
                    exc,
                )
                setattr(self, comp_name, None)

    def activate(self) -> None:
        """Aktivera plugin (is_active via PluginBase)."""
        try:
            super().activate()
        except Exception:
            _log.exception("PluginBase.activate misslyckades.")
        _log.debug("%s aktiverad", self.NAME)

    def deactivate(self) -> None:
        """Deaktivera plugin (state → INACTIVE + cleanup)."""
        try:
            super().deactivate()
        except Exception:
            _log.exception("PluginBase.deactivate misslyckades.")
        _log.debug("%s deaktiverad", self.NAME)

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API - BUTTONS
    # ═══════════════════════════════════════════════════════════════════════════

    def create_button(
        self,
        text: str,
        style: str = "default",
        icon: str = "",
        tooltip: str = "",
        enabled: bool = True,
        on_click: Optional[Callable] = None,
    ) -> Optional[Any]:
        """
        Skapa en standardiserad knapp.

        Args:
            text: Knapptext
            style: "default", "primary", "success", "warning", "danger"
            icon: Emoji eller ikon (t.ex. "💾")
            tooltip: Tooltip-text
            enabled: Om knappen är aktiv
            on_click: Callback vid klick

        Returns:
            QPushButton eller None
        """
        if not self.buttons:
            return None
        return self.buttons.create_button(
            text, style, icon, tooltip, enabled, on_click
        )

    def create_icon_button(
        self,
        icon: str,
        tooltip: str = "",
        size: int = 32,
        on_click: Optional[Callable] = None,
    ) -> Optional[Any]:
        """Skapa en ikon-knapp (utan text)."""
        if not self.buttons:
            return None
        return self.buttons.create_icon_button(icon, tooltip, size, on_click)

    def create_button_group(
        self,
        button_specs: List[Dict[str, Any]],
        layout: str = "horizontal",
    ) -> Optional[Any]:
        """
        Skapa en grupp med knappar.

        Args:
            button_specs: Lista med
                {"text": ..., "style": ..., "on_click": ...}
            layout: "horizontal" eller "vertical"

        Returns:
            Widget med knappgrupp eller None
        """
        if not self.buttons:
            return None
        return self.buttons.create_button_group(button_specs, layout)

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API - DIALOGS
    # ═══════════════════════════════════════════════════════════════════════════

    def show_info(
        self,
        message: str,
        title: str = "Information",
        parent: Any = None,
    ) -> None:
        """Visa info-dialog."""
        if self.dialogs:
            self.dialogs.show_info(message, title, parent)

    def show_warning(
        self,
        message: str,
        title: str = "Varning",
        parent: Any = None,
    ) -> None:
        """Visa varnings-dialog."""
        if self.dialogs:
            self.dialogs.show_warning(message, title, parent)

    def show_error(
        self,
        message: str,
        title: str = "Fel",
        parent: Any = None,
    ) -> None:
        """Visa fel-dialog."""
        if self.dialogs:
            self.dialogs.show_error(message, title, parent)

    def show_confirm(
        self,
        message: str,
        title: str = "Bekräfta",
        parent: Any = None,
    ) -> bool:
        """
        Visa bekräftelse-dialog.

        Returns:
            True om användaren klickade Ja
        """
        if self.dialogs:
            return self.dialogs.show_confirm(message, title, parent)
        return False

    def show_input(
        self,
        message: str,
        title: str = "Ange värde",
        default: str = "",
        parent: Any = None,
    ) -> Optional[str]:
        """
        Visa input-dialog.

        Returns:
            Inmatat värde eller None om avbruten
        """
        if self.dialogs:
            return self.dialogs.show_input(message, title, default, parent)
        return None

    def show_file_dialog(
        self,
        title: str = "Välj fil",
        directory: str = "",
        filters: str = "Alla filer (*.*)",
        save: bool = False,
        parent: Any = None,
    ) -> Optional[str]:
        """
        Visa fil-dialog.

        Args:
            title: Dialogtitel
            directory: Startkatalog
            filters: Filfilter (t.ex. "Excel (*.xlsx);;CSV (*.csv)")
            save: True för spara-dialog, False för öppna

        Returns:
            Filsökväg eller None
        """
        if self.dialogs:
            return self.dialogs.show_file_dialog(
                title, directory, filters, save, parent
            )
        return None

    def show_folder_dialog(
        self,
        title: str = "Välj mapp",
        directory: str = "",
        parent: Any = None,
    ) -> Optional[str]:
        """Visa mapp-dialog."""
        if self.dialogs:
            return self.dialogs.show_folder_dialog(title, directory, parent)
        return None

    def show_progress_dialog(
        self,
        title: str = "Bearbetar...",
        message: str = "",
        maximum: int = 100,
        parent: Any = None,
    ) -> Optional[Any]:
        """
        Skapa progress-dialog.

        Returns:
            QProgressDialog eller liknande
        """
        if self.dialogs:
            return self.dialogs.create_progress_dialog(
                title, message, maximum, parent
            )
        return None

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API - FORMS
    # ═══════════════════════════════════════════════════════════════════════════

    def create_form_group(
        self,
        title: str,
        fields: List[Dict[str, Any]],
        parent: Any = None,
    ) -> Optional[Any]:
        """
        Skapa en formulärgrupp.

        Args:
            title: Grupptitel
            fields: Lista med fältdefinitioner:
                [{"name": "field1", "label": "Fält 1", "type": "text", ...}]

        Returns:
            QGroupBox med formulär eller None
        """
        if self.forms:
            return self.forms.create_form_group(title, fields, parent)
        return None

    def create_form_field(
        self,
        name: str,
        label: str,
        field_type: str = "text",
        **kwargs: Any,
    ) -> Optional[Any]:
        """
        Skapa ett enskilt formulärfält.

        Args:
            name: Fältnamn
            label: Etikett
            field_type: "text", "number", "dropdown", "checkbox", "date"
            **kwargs: Ytterligare options (min, max, items, etc.)

        Returns:
            Widget eller None
        """
        if self.forms:
            return self.forms.create_form_field(
                name, label, field_type, **kwargs
            )
        return None

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API - VALIDATORS
    # ═══════════════════════════════════════════════════════════════════════════

    def create_vin_validator(self) -> Optional[Any]:
        """Skapa VIN-validator för QLineEdit."""
        if self.validators:
            return self.validators.create_vin_validator()
        return None

    def create_numeric_validator(
        self,
        min_val: int = 0,
        max_val: int = 999999,
    ) -> Optional[Any]:
        """Skapa numerisk validator."""
        if self.validators:
            return self.validators.create_numeric_validator(
                min_val, max_val
            )
        return None

    def create_text_validator(
        self,
        pattern: str = r".*",
        max_length: int = 100,
    ) -> Optional[Any]:
        """Skapa text-validator med regex."""
        if self.validators:
            return self.validators.create_text_validator(
                pattern, max_length
            )
        return None

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API - STYLES
    # ═══════════════════════════════════════════════════════════════════════════

    def get_stylesheet(self, theme: str = "dark") -> str:
        """Hämta komplett stylesheet."""
        if self.styles:
            return self.styles.get_stylesheet(theme)
        return ""

    def get_button_style(self, style: str = "default") -> str:
        """Hämta knapp-stylesheet."""
        if self.styles:
            return self.styles.get_button_style(style)
        return ""

    def get_table_style(self) -> str:
        """Hämta tabell-stylesheet."""
        if self.styles:
            return self.styles.get_table_style()
        return ""

    def get_color(self, name: str) -> str:
        """Hämta färg från tema (fallback: namngiven konstant)."""
        if self.styles:
            return self.styles.get_color(name)
        return _FALLBACK_COLOR


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "Plugin",
    "VERSION",
    "AUTHOR",
    "YEAR",
    "HAS_PYSIDE6",
    "get_copyright_string",
]
