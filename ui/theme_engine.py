# -*- coding: utf-8 -*-
"""
ui/theme_engine.py — Tema-motor för Filregistrering.

Hanterar tre teman:
    - "light"  : Ljust tema
    - "dark"   : Mörkt tema
    - "auto"   : Följer operativsystemets färgschema och växlar live

Temat läses och sparas via core.settings_manager.SettingsManager
(settings.json, SCHEMA v1, nyckel "theme"). Vid byte publiceras eventet
"theme:changed" på event-bussen med payload:
    {"mode": <vald inställning>, "effective": <"light"|"dark">}

ALLA färger i applikationen definieras HÄR som semantiska tokens.
Övriga moduler får ALDRIG hårdkoda färger — de använder setObjectName()
och träffas av QSS-selektorerna i _build_stylesheet(), eller hämtar
enskilda tokens via ThemeEngine.get_color().

VIKTIGT:
    - word-wrap får ALDRIG förekomma i QSS (Qt stödjer det inte).
      Radbrytning görs med setWordWrap(True) i Python-koden.
    - Ingen GUI-logik här utöver applicering av stylesheet — temat är
      en ren tjänst som ui/main_window.py m.fl. konsumerar.

Copyright © %s Rickard Längkvist
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Any, Callable, Dict, Final, List, Optional

VERSION: Final[str] = "1.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"
COPYRIGHT: Final[str] = "Copyright © {} Rickard Längkvist".format(datetime.now().year)

_log = logging.getLogger(__name__)

try:
    from PySide6.QtCore import QObject, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QWidget

    HAS_PYSIDE6: Final[bool] = True
except ImportError:  # pragma: no cover - PySide6 är ett hårt krav i appen
    HAS_PYSIDE6 = False  # type: ignore[misc]

# ---------------------------------------------------------------------------
# Konstanter
# ---------------------------------------------------------------------------

MODE_LIGHT: Final[str] = "light"
MODE_DARK: Final[str] = "dark"
MODE_AUTO: Final[str] = "auto"
VALID_MODES: Final[frozenset[str]] = frozenset({MODE_LIGHT, MODE_DARK, MODE_AUTO})
DEFAULT_MODE: Final[str] = MODE_AUTO
SETTINGS_KEY: Final[str] = "theme"
EVENT_THEME_CHANGED: Final[str] = "theme:changed"

# ---------------------------------------------------------------------------
# Färgpaletter — ENDA platsen i hela kodbasen där färger definieras.
# Tokens är semantiska (roll, inte kulör) så att teman kan bytas fritt.
# Obligatoriska StyleEngine-nycklar enligt spec finns med.
# ---------------------------------------------------------------------------

LIGHT_PALETTE: Final[Dict[str, str]] = {
    # Grundytor
    "background": "#f5f6f8",
    "window_bg": "#f5f6f8",
    "surface": "#ffffff",
    "surface_bg": "#ffffff",
    "surface_alt": "#eef0f3",
    "surface_alt_bg": "#eef0f3",
    "bg_secondary": "#e7eaee",
    "panel_bg": "#ffffff",
    "card_bg": "#ffffff",
    "card_hover": "#f4f6f8",
    # Text
    "text": "#1c2430",
    "text_primary": "#1c2430",
    "text_secondary": "#5a6472",
    "muted": "#9aa3af",
    "text_disabled": "#9aa3af",
    "disabled_fg": "#9aa3af",
    "disabled_bg": "#eef0f3",
    "inverse_text": "#ffffff",
    # Accent
    "accent": "#1d5fa8",
    "accent_hover": "#2a72c4",
    "accent_active": "#174c87",
    "accent_pressed": "#174c87",
    "accent_soft": "#e3edf8",
    "accent_subtle_bg": "#e3edf8",
    "link": "#1d5fa8",
    # Knappar
    "button_bg": "#555555",
    "button_fg": "#ffffff",
    "button_hover": "#444444",
    "button_active": "#333333",
    # Flikar
    "tab_bg": "#e0e4e9",
    "tab_fg": "#5a6472",
    "tab_active_bg": "#ffffff",
    "tab_active_fg": "#1c2430",
    # Gränser
    "border": "#c9ced6",
    "border_soft": "#d7dbe1",
    "border_strong": "#9aa3af",
    # Status
    "success": "#1e7e34",
    "success_bg": "#e6f4ea",
    "warning": "#b86e00",
    "warning_bg": "#fdf3e1",
    "error": "#b02a37",
    "error_bg": "#fbe9eb",
    "info": "#0c63e4",
    "info_bg": "#e7f0fe",
    # Inmatning
    "input_bg": "#ffffff",
    "input_border": "#b9c0ca",
    "input_focus_border": "#1d5fa8",
    "input_disabled_bg": "#eef0f3",
    # Tabeller / listor
    "table_header_bg": "#e7eaee",
    "table_row_alt_bg": "#f4f6f8",
    "table_grid": "#d7dbe1",
    "selection_bg": "#cfe2f6",
    "selection_fg": "#10243c",
    "selection_text": "#10243c",
    # Övrigt
    "tooltip_bg": "#2a3442",
    "tooltip_fg": "#f5f6f8",
    "tooltip_text": "#f5f6f8",
    "scrollbar_handle": "#b9c0ca",
    "scrollbar_hover": "#9aa3af",
    "statusbar_bg": "#e7eaee",
    "menu_bg": "#ffffff",
    "tab_inactive_bg": "#e0e4e9",
}

DARK_PALETTE: Final[Dict[str, str]] = {
    # Grundytor
    "background": "#15191f",
    "window_bg": "#15191f",
    "surface": "#1d232b",
    "surface_bg": "#1d232b",
    "surface_alt": "#242b35",
    "surface_alt_bg": "#242b35",
    "bg_secondary": "#1a2028",
    "panel_bg": "#1d232b",
    "card_bg": "#1d232b",
    "card_hover": "#242b35",
    # Text
    "text": "#e8ebef",
    "text_primary": "#e8ebef",
    "text_secondary": "#a3adba",
    "muted": "#5f6a78",
    "text_disabled": "#5f6a78",
    "disabled_fg": "#5f6a78",
    "disabled_bg": "#242b35",
    "inverse_text": "#15191f",
    # Accent
    "accent": "#4d94e0",
    "accent_hover": "#65a6ea",
    "accent_active": "#3a7fc8",
    "accent_pressed": "#3a7fc8",
    "accent_soft": "#23344a",
    "accent_subtle_bg": "#23344a",
    "link": "#4d94e0",
    # Knappar
    "button_bg": "#5a5a7a",
    "button_fg": "#ffffff",
    "button_hover": "#6a6a8a",
    "button_active": "#7a7a9a",
    # Flikar
    "tab_bg": "#161b22",
    "tab_fg": "#a3adba",
    "tab_active_bg": "#1d232b",
    "tab_active_fg": "#e8ebef",
    # Gränser
    "border": "#3a4350",
    "border_soft": "#303845",
    "border_strong": "#566272",
    # Status
    "success": "#4fbf6b",
    "success_bg": "#1d3324",
    "warning": "#e0a23f",
    "warning_bg": "#3a2f17",
    "error": "#e06570",
    "error_bg": "#3a2026",
    "info": "#5e9bf0",
    "info_bg": "#1f2d45",
    # Inmatning
    "input_bg": "#1a1f27",
    "input_border": "#3a4350",
    "input_focus_border": "#4d94e0",
    "input_disabled_bg": "#242b35",
    # Tabeller / listor
    "table_header_bg": "#242b35",
    "table_row_alt_bg": "#1a2028",
    "table_grid": "#303845",
    "selection_bg": "#2e4a6b",
    "selection_fg": "#e8ebef",
    "selection_text": "#e8ebef",
    # Övrigt
    "tooltip_bg": "#e8ebef",
    "tooltip_fg": "#15191f",
    "tooltip_text": "#15191f",
    "scrollbar_handle": "#3a4350",
    "scrollbar_hover": "#566272",
    "statusbar_bg": "#1a2028",
    "menu_bg": "#1d232b",
    "tab_inactive_bg": "#161b22",
}

_PALETTES: Final[Dict[str, Dict[str, str]]] = {
    MODE_LIGHT: LIGHT_PALETTE,
    MODE_DARK: DARK_PALETTE,
}

# ---------------------------------------------------------------------------
# QSS-byggare
# ---------------------------------------------------------------------------


def _build_stylesheet(p: Dict[str, str]) -> str:
    """Bygg komplett applikations-QSS från en palett.

    OBS: word-wrap används ALDRIG här (Qt-stylesheets stödjer det inte).
    Radbrytning sköts med setWordWrap(True) i Python-koden.
    """
    return """\
/* == Grund ============================================================ */
QWidget {
    background-color: %(background)s;
    color: %(text)s;
    font-size: 10pt;
}
QWidget:disabled {
    color: %(disabled_fg)s;
}
#MainWindow, QMainWindow {
    background-color: %(background)s;
}
QFrame#ContentPanel, QWidget#ContentPanel {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: 6px;
}

/* == Rubriker / etiketter ============================================ */
QLabel {
    background-color: transparent;
}
QLabel#TitleLabel {
    font-size: 15pt;
    font-weight: bold;
    color: %(text)s;
}
QLabel#SubtitleLabel {
    font-size: 11pt;
    color: %(text_secondary)s;
}
QLabel#SectionLabel {
    font-weight: bold;
    color: %(accent)s;
}
QLabel#ErrorLabel {
    color: %(error)s;
}
QLabel#WarningLabel {
    color: %(warning)s;
}
QLabel#SuccessLabel {
    color: %(success)s;
}
QLabel#InfoLabel {
    color: %(info)s;
}
QLabel#CopyrightLabel {
    color: %(text_secondary)s;
    font-size: 8pt;
}

/* == Knappar ========================================================== */
QPushButton {
    background-color: %(surface_alt)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 4px;
    padding: 6px 14px;
}
QPushButton:hover {
    border-color: %(border_strong)s;
    background-color: %(surface)s;
}
QPushButton:pressed {
    background-color: %(accent_soft)s;
}
QPushButton:disabled {
    color: %(disabled_fg)s;
    background-color: %(disabled_bg)s;
}
QPushButton#PrimaryButton {
    background-color: %(accent)s;
    color: %(inverse_text)s;
    border: 1px solid %(accent)s;
    font-weight: bold;
}
QPushButton#PrimaryButton:hover {
    background-color: %(accent_hover)s;
}
QPushButton#PrimaryButton:pressed {
    background-color: %(accent_active)s;
}
QPushButton#DangerButton {
    background-color: %(error)s;
    color: %(inverse_text)s;
    border: 1px solid %(error)s;
}
QPushButton#FlatButton {
    background-color: transparent;
    border: none;
    color: %(accent)s;
}
QPushButton#FlatButton:hover {
    color: %(accent_hover)s;
}

/* == Inmatningsfält =================================================== */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
QDateEdit, QTimeEdit, QDateTimeEdit, QComboBox {
    background-color: %(input_bg)s;
    color: %(text)s;
    border: 1px solid %(input_border)s;
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: %(selection_bg)s;
    selection-color: %(selection_fg)s;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus, QComboBox:focus {
    border: 1px solid %(input_focus_border)s;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    background-color: %(input_disabled_bg)s;
    color: %(disabled_fg)s;
}
QLineEdit#SearchField {
    border: 1px solid %(accent)s;
    border-radius: 12px;
    padding: 4px 12px;
}
QComboBox QAbstractItemView {
    background-color: %(menu_bg)s;
    border: 1px solid %(border)s;
    selection-background-color: %(selection_bg)s;
    selection-color: %(selection_fg)s;
}

/* == Tabeller / listor / träd ======================================== */
QTableView, QTableWidget, QListView, QListWidget, QTreeView, QTreeWidget {
    background-color: %(surface)s;
    alternate-background-color: %(table_row_alt_bg)s;
    gridline-color: %(table_grid)s;
    border: 1px solid %(border)s;
    selection-background-color: %(selection_bg)s;
    selection-color: %(selection_fg)s;
}
QHeaderView::section {
    background-color: %(table_header_bg)s;
    color: %(text)s;
    border: none;
    border-right: 1px solid %(table_grid)s;
    border-bottom: 1px solid %(border)s;
    padding: 5px 8px;
    font-weight: bold;
}
QTableCornerButton::section {
    background-color: %(table_header_bg)s;
    border: none;
}

/* == Flikar =========================================================== */
QTabWidget::pane {
    border: 1px solid %(border)s;
    background-color: %(tab_active_bg)s;
    border-radius: 4px;
}
QTabBar::tab {
    background-color: %(tab_bg)s;
    color: %(tab_fg)s;
    border: 1px solid %(border)s;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    padding: 6px 16px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: %(tab_active_bg)s;
    color: %(tab_active_fg)s;
    font-weight: bold;
    border-bottom: 2px solid %(accent)s;
}
QTabBar::tab:hover:!selected {
    color: %(text)s;
}

/* == Menyer / verktygsfält =========================================== */
QMenuBar {
    background-color: %(surface_alt)s;
    border-bottom: 1px solid %(border)s;
}
QMenuBar::item {
    background-color: transparent;
    padding: 5px 10px;
}
QMenuBar::item:selected {
    background-color: %(accent_soft)s;
    border-radius: 4px;
}
QMenu {
    background-color: %(menu_bg)s;
    border: 1px solid %(border)s;
}
QMenu::item {
    padding: 6px 28px 6px 20px;
}
QMenu::item:selected {
    background-color: %(selection_bg)s;
    color: %(selection_fg)s;
}
QMenu::separator {
    height: 1px;
    background-color: %(border)s;
    margin: 4px 8px;
}
QToolBar {
    background-color: %(surface_alt)s;
    border-bottom: 1px solid %(border)s;
    spacing: 4px;
}

/* == Statusrad ======================================================== */
QStatusBar, #StatusBar {
    background-color: %(statusbar_bg)s;
    color: %(text_secondary)s;
    border-top: 1px solid %(border)s;
}

/* == Grupper / ramar ================================================== */
QGroupBox {
    border: 1px solid %(border)s;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: %(accent)s;
}

/* == Rullningslister ================================================== */
QScrollBar:vertical {
    background-color: transparent;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background-color: %(scrollbar_handle)s;
    border-radius: 5px;
    min-height: 30px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background-color: %(scrollbar_hover)s;
}
QScrollBar:horizontal {
    background-color: transparent;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background-color: %(scrollbar_handle)s;
    border-radius: 5px;
    min-width: 30px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background-color: %(scrollbar_hover)s;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* == Diverse ========================================================== */
QToolTip {
    background-color: %(tooltip_bg)s;
    color: %(tooltip_fg)s;
    border: 1px solid %(border_strong)s;
    padding: 4px 8px;
}
QProgressBar {
    background-color: %(surface_alt)s;
    border: 1px solid %(border)s;
    border-radius: 4px;
    text-align: center;
    color: %(text)s;
}
QProgressBar::chunk {
    background-color: %(accent)s;
    border-radius: 3px;
}
QCheckBox, QRadioButton {
    background-color: transparent;
    spacing: 6px;
}
QSplitter::handle {
    background-color: %(border)s;
}
QStatusBar::item {
    border: none;
}
""" % p


# ---------------------------------------------------------------------------
# Hjälpfunktioner — settings- och eventbus-åtkomst med tolerant API
# ---------------------------------------------------------------------------


def _settings_get(settings: Any, key: str, default: Any) -> Any:
    """Läs en inställning oavsett om SettingsManager exponerar get()
    eller direkt dict-åtkomst. Returnerar default vid alla fel."""
    if settings is None:
        return default
    try:
        if hasattr(settings, "get"):
            return settings.get(key, default)
        if isinstance(settings, dict):
            return settings.get(key, default)
    except Exception:
        _log.exception("Kunde inte läsa inställningen '%s'", key)
    return default


def _settings_set(settings: Any, key: str, value: Any) -> bool:
    """Skriv en inställning med tolerant API (set() + ev. save()).

    Returnerar True vid lyckad skrivning.
    """
    if settings is None:
        return False
    try:
        if hasattr(settings, "set"):
            settings.set(key, value)
        elif isinstance(settings, dict):
            settings[key] = value
        else:
            return False
        if hasattr(settings, "save"):
            settings.save()
        return True
    except Exception:
        _log.exception("Kunde inte spara inställningen '%s'", key)
        return False


def _emit_event(event_bus: Any, event: str, payload: Dict[str, Any]) -> None:
    """Publicera event med publish→emit-fallback.

    core.event_bus v2.1.0 exponerar emit/on; vissa kärnor använder
    publish/subscribe. Denna funktion hanterar båda kontrakt.
    """
    if event_bus is None:
        return
    try:
        if hasattr(event_bus, "emit"):
            event_bus.emit(event, payload)
        elif hasattr(event_bus, "publish"):
            event_bus.publish(event, payload)
        else:
            _log.warning(
                "Event-bussen saknar publish/emit — '%s' skickades inte",
                event,
            )
    except Exception:
        _log.exception("Fel vid publicering av eventet '%s'", event)


# ---------------------------------------------------------------------------
# Systemtema-detektering (för läget "auto")
# ---------------------------------------------------------------------------


def detect_system_theme() -> str:
    """Detektera operativsystemets färgschema.

    Ordning:
        1. Qt 6.5+ QStyleHints.colorScheme (plattformsoberoende)
        2. Windows-registret: AppsUseLightTheme (HKCU)
        3. Fallback: ljust tema

    Returnerar MODE_LIGHT eller MODE_DARK (aldrig MODE_AUTO).
    """
    # 1) Qt styleHints (kräver en QGuiApplication-instans)
    if HAS_PYSIDE6:
        try:
            app = QGuiApplication.instance()
            if app is not None:
                hints = app.styleHints()
                scheme = getattr(hints, "colorScheme", None)
                if callable(scheme):
                    value = scheme()
                    if value == Qt.ColorScheme.Dark:
                        return MODE_DARK
                    if value == Qt.ColorScheme.Light:
                        return MODE_LIGHT
                    # Qt.ColorScheme.Unknown → fortsätt till nästa metod
        except Exception:
            _log.debug("Qt colorScheme-detektering misslyckades", exc_info=True)

    # 2) Windows-registret
    if sys.platform == "win32":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return MODE_LIGHT if int(value) == 1 else MODE_DARK
        except OSError:
            _log.debug(
                "Kunde inte läsa AppsUseLightTheme ur registret",
                exc_info=True,
            )
        except Exception:
            _log.exception("Oväntat fel vid registerläsning av systemtema")

    # 3) Fallback
    _log.debug("Systemtema kunde inte avgöras — använder ljust tema")
    return MODE_LIGHT


# ---------------------------------------------------------------------------
# ThemeEngine
# ---------------------------------------------------------------------------


class ThemeEngine:
    """Central tema-tjänst.

    Användning (i main.py / main_window.py):
        engine = ThemeEngine(settings_manager=settings, event_bus=bus)
        engine.apply(app)                  # applicera sparat tema
        engine.set_mode("dark")            # byt tema + spara + event
        engine.get_color("accent")         # hämta enskild token

    Vid mode "auto" lyssnar motorn på Qt:s colorSchemeChanged (om
    tillgängligt, Qt 6.5+) och applicerar om temat automatiskt när
    operativsystemet växlar ljust/mörkt.
    """

    def __init__(
        self,
        settings_manager: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._settings = settings_manager
        self._event_bus = event_bus
        self._target: Optional[Any] = None
        self._mode: str = self._load_mode()
        self._effective: str = self._resolve_effective(self._mode)
        self._scheme_listener_connected: bool = False
        self._extra_listeners: List[Callable[[str, str], None]] = []
        _log.info(
            "ThemeEngine v%s initierad (mode=%s, effektivt=%s)",
            VERSION,
            self._mode,
            self._effective,
        )

    # -- Publikt API -------------------------------------------------------

    def get_theme(self) -> str:
        """Returnera effektivt tema: 'light' eller 'dark'.

        StyleEngine-kontrakt enligt spec.
        """
        return self._effective

    def get_mode(self) -> str:
        """Returnera vald inställning: 'light', 'dark' eller 'auto'."""
        return self._mode

    def get_effective_theme(self) -> str:
        """Returnera det tema som faktiskt visas: 'light' eller 'dark'."""
        return self._effective

    def set_mode(self, mode: str) -> bool:
        """Byt tema-läge, spara i settings, applicera och publicera event.

        Returnerar True om läget är giltigt och bytet genomfördes.
        """
        mode = str(mode).strip().lower()
        if mode not in VALID_MODES:
            _log.warning(
                "Ogiltigt tema-läge: '%s' (tillåtna: %s)",
                mode,
                ", ".join(sorted(VALID_MODES)),
            )
            return False

        old_mode = self._mode
        self._mode = mode
        self._effective = self._resolve_effective(mode)
        if not _settings_set(self._settings, SETTINGS_KEY, mode):
            _log.warning("Tema-läget '%s' kunde inte sparas i settings", mode)

        self._apply_current()
        _log.info(
            "Tema bytt: %s -> %s (effektivt=%s)",
            old_mode,
            mode,
            self._effective,
        )
        self._notify_changed()
        return True

    def apply(self, target: Any) -> None:
        """Applicera aktuellt tema på en QApplication- eller QWidget-instans.

        Kopplar även colorSchemeChanged-lyssnaren (en gång) så att
        läget 'auto' följer operativsystemet live.
        """
        if not HAS_PYSIDE6:
            _log.error("PySide6 saknas — tema kan inte appliceras")
            return

        self._target = target
        self._connect_scheme_listener()
        self._effective = self._resolve_effective(self._mode)
        self._apply_current()

    def get_palette(self) -> Dict[str, str]:
        """Returnera en KOPIA av den effektiva palettens tokens."""
        return dict(_PALETTES[self._effective])

    def get_colors(self) -> Dict[str, str]:
        """Returnera alla färgtokens för effektivt tema.

        StyleEngine-kontrakt enligt spec.
        """
        return self.get_palette()

    def get_color(self, token: str, default: str = "") -> str:
        """Hämta en enskild färg-token ur den effektiva paletten.

        StyleEngine-kontrakt enligt spec.
        """
        palette = _PALETTES[self._effective]
        if token not in palette:
            _log.warning("Okänd färg-token: '%s'", token)
            return default
        return palette[token]

    def get_stylesheet(self) -> str:
        """Returnera komplett QSS för den effektiva paletten."""
        return _build_stylesheet(_PALETTES[self._effective])

    def generate_stylesheet(self) -> str:
        """Returnera komplett QSS för den effektiva paletten.

        StyleEngine-kontrakt enligt spec.
        """
        return self.get_stylesheet()

    def add_listener(self, callback: Callable[[str, str], None]) -> None:
        """Registrera lokal lyssnare: callback(mode, effective).

        Komplement till eventet 'theme:changed' för komponenter som
        inte har tillgång till event-bussen.
        """
        if callback not in self._extra_listeners:
            self._extra_listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, str], None]) -> None:
        """Avregistrera en lokal lyssnare."""
        try:
            self._extra_listeners.remove(callback)
        except ValueError:
            pass

    # -- Internt -----------------------------------------------------------

    def _load_mode(self) -> str:
        """Läs tema-läget från settings med validering och fallback."""
        raw = _settings_get(self._settings, SETTINGS_KEY, DEFAULT_MODE)
        mode = str(raw).strip().lower()
        if mode not in VALID_MODES:
            _log.warning(
                "Ogiltigt tema-läge '%s' i settings — använder '%s'",
                raw,
                DEFAULT_MODE,
            )
            return DEFAULT_MODE
        return mode

    def _resolve_effective(self, mode: str) -> str:
        """Översätt vald inställning till effektivt tema (light/dark)."""
        if mode == MODE_AUTO:
            return detect_system_theme()
        return mode

    def _apply_current(self) -> None:
        """Sätt QSS på sparad target-instans (om en finns)."""
        if not HAS_PYSIDE6:
            return

        target = self._target or QApplication.instance()
        if target is None:
            _log.debug("Ingen QApplication/QWidget ännu — tema appliceras vid apply()")
            return

        try:
            target.setStyleSheet(_build_stylesheet(_PALETTES[self._effective]))
            _log.debug("Stylesheet applicerad (effektivt=%s)", self._effective)
        except Exception:
            _log.exception("Fel vid applicering av stylesheet")

    def _connect_scheme_listener(self) -> None:
        """Koppla Qt colorSchemeChanged → _on_system_scheme_changed (en gång)."""
        if self._scheme_listener_connected or not HAS_PYSIDE6:
            return
        try:
            app = QGuiApplication.instance()
            if app is None:
                return
            hints = app.styleHints()
            signal = getattr(hints, "colorSchemeChanged", None)
            if signal is not None:
                signal.connect(self._on_system_scheme_changed)
                self._scheme_listener_connected = True
                _log.debug("colorSchemeChanged-lyssnare kopplad")
        except Exception:
            _log.debug("colorSchemeChanged ej tillgänglig", exc_info=True)

    def _on_system_scheme_changed(self, *_args: Any) -> None:
        """Systemets färgschema ändrades — uppdatera om läget är 'auto'."""
        if self._mode != MODE_AUTO:
            return
        new_effective = detect_system_theme()
        if new_effective == self._effective:
            return
        _log.info(
            "Systemtema ändrades: %s -> %s (auto-läge)",
            self._effective,
            new_effective,
        )
        self._effective = new_effective
        self._apply_current()
        self._notify_changed()

    def _notify_changed(self) -> None:
        """Publicera 'theme:changed' + anropa lokala lyssnare."""
        payload = {"mode": self._mode, "effective": self._effective}
        _emit_event(self._event_bus, EVENT_THEME_CHANGED, payload)
        for callback in list(self._extra_listeners):
            try:
                callback(self._mode, self._effective)
            except Exception:
                _log.exception("Fel i tema-lyssnare %r", callback)


__all__ = [
    "VERSION",
    "AUTHOR",
    "COPYRIGHT",
    "MODE_LIGHT",
    "MODE_DARK",
    "MODE_AUTO",
    "VALID_MODES",
    "DEFAULT_MODE",
    "SETTINGS_KEY",
    "EVENT_THEME_CHANGED",
    "LIGHT_PALETTE",
    "DARK_PALETTE",
    "ThemeEngine",
    "detect_system_theme",
]
