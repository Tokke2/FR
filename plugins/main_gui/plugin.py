# -*- coding: utf-8 -*-
# plugins/main_gui/plugin.py
"""
Main GUI Plugin v6.0.3
Huvudgränssnitt för fordonsregistrering (PySide6).
Full integration med ts_schema_manager, ts_excel_importer och dynamiska scheman.
FÖRÄNDRINGAR v6.0.3 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (radbrytningsdubbling, transport-artefakt): tomrader mellan
    decoratorer (@dataclass/@property) och definitioner (class/def)
    BORTTAGNA — 6 st. Ingen logikändring.
  - GUI-pluginet skapar fönstret; Application.start äger Qt:s eventloop.
    En timer hanterar fokusbegäran från andra starter.

FÖRÄNDRINGAR v6.0.2 (Session 10 — spec v1.4):
  - Hela filen omskriven REN: markdown-artefakter borttagna
    ([url]-länkar, **-markeringar, *x*-mönster, &gt;/&lt;/&amp; osv.).
  - logger -> _log (spec-konvention: module-level _log, ej logger/self.logger).
  - BUGG #5: "TADEGA AB" bort. app_author-default = "Rickard Längkvist";
    setApplicationName via config app_name (default
    "Fordonsreg").
  - VIN3-konsistens (G6) verifierad: all VIN-validering sker via
    vehicle_registry.validate_vin (VIN3 = tecken 2-4, slice [1:4]).
    Ingen egen VIN3-extraktion i denna fil.
  - Kompatibel med vehicle_registry_page v5.5.0 + vehicle_registry_helpers
    v1.0.0 (create_page-kontraktet oförändrat — sidan skapas via
    vehicle_registry.create_page()).
FÖRÄNDRINGAR v6.0.1:
  - BUGG #3 FIXAD: word-wrap borttagen från stylesheet
    Rad 966/975: setStyleSheet("... word-wrap: anywhere;") ->
    setStyleSheet("...") + setWordWrap(True)
Copyright © Rickard Längkvist
Alla rättigheter förbehållna.
"""
from __future__ import annotations
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Final,
    List,
    Optional,
    Protocol,
    Set,
    Tuple,
    TYPE_CHECKING,
)
from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)
from core import layout_memory
from core import memory_guard
from core import runtime_policy
from core import theme as design
from core.plugin_base import PluginBase
if TYPE_CHECKING:
    from PySide6.QtWidgets import QMenuBar
_log = logging.getLogger(__name__)
__version__ = "6.0.3"

# ══════════════════════════════════════════════════════════════════════════════
# ENUMS

# ══════════════════════════════════════════════════════════════════════════════

class SchemaEvent(str, Enum):
    """Event-namn för schema-händelser."""
    # ts_schema_manager v2.0+
    TS_SCHEMA_LOADED = "ts:schema:loaded"
    TS_VERSION_CHANGED = "ts:schema:version_changed"
    TS_SCHEMA_CREATED = "ts:schema:created"
    # Legacy (bakåtkompatibilitet)
    SCHEMA_LOADED = "schema:loaded"
    SCHEMA_VERSION_CHANGED = "schema:version_changed"
    SCHEMA_IMPORT_STARTED = "schema:import_started"
    SCHEMA_IMPORT_COMPLETED = "schema:import_completed"
    # ts_spec_import (äldre)
    TS_SPEC_IMPORTED = "ts_spec:imported"
    TS_SPEC_VERSION_CHANGED = "ts_spec:version_changed"

class MessageIcon(Enum):
    """Meddelandeikoner."""
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    QUESTION = auto()

# ══════════════════════════════════════════════════════════════════════════════
# PROTOCOLS

# ══════════════════════════════════════════════════════════════════════════════

class EventBusProtocol(Protocol):
    """Protocol för event bus."""

    def on(self, event: str, handler: Callable[..., Any]) -> None: ...

    def off(self, event: str, handler: Callable[..., Any]) -> None: ...

    def emit(self, event: str, data: Dict[str, Any]) -> None: ...

class ConfigProtocol(Protocol):
    """Protocol för config."""

    def get(self, key: str, default: Any = None) -> Any: ...

    def set(self, key: str, value: Any) -> bool: ...

class SchemaManagerProtocol(Protocol):
    """Protocol för schema manager."""

    def get_active_version(self) -> Optional[str]: ...

    def get_all_schemas(self) -> Dict[str, Any]: ...

    def list_versions(self) -> List[str]: ...

    def set_active_version(self, version: str) -> bool: ...

# ══════════════════════════════════════════════════════════════════════════════
# DATACLASSES

# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class WindowConfig:
    """Fönsterkonfiguration."""
    width: int = 1400
    height: int = 900
    sidebar_width: int = 220

@dataclass
class SchemaInfo:
    """Schema-information."""
    version: Optional[str] = None
    post_types: List[str] = field(default_factory=list)
    versions: List[str] = field(default_factory=list)
    @property
    def is_active(self) -> bool:
        """Kontrollera om ett schema är aktivt."""
        return self.version is not None
    @property
    def post_count(self) -> int:
        """Antal posttyper."""
        return len(self.post_types)

@dataclass
class PageInfo:
    """Sidinformation."""
    name: str
    widget: QWidget
    icon: str = "📄"

@dataclass
class VehicleStatistics:
    """Fordonsstatistik."""
    total: int = 0
    years_count: int = 0
    registered_total: int = 0
    registered_this_year: int = 0
    registered_this_month: int = 0

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS

# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_WINDOW_CONFIG: Final[WindowConfig] = WindowConfig()
STATS_UPDATE_INTERVAL_MS: Final[int] = 30000  # 30 sekunder
AUTOLOAD_MAX_AGE_HOURS: Final[int] = 24
MIN_PIN_LENGTH: Final[int] = 4

# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS

# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Robust plugin-hämtning.
    Försöker flera metoder i prioritetsordning.
    """
    if app is None:
        return None
    # Metod 1: app.get_plugin()
    try:
        getter = getattr(app, "get_plugin", None)
        if callable(getter):
            plugin = getter(name)
            if plugin is not None:
                return plugin
    except Exception as e:
        _log.debug("app.get_plugin failed for %s: %s", name, e)
    # Metod 2: app.plugin_loader.get_plugin()
    try:
        loader = getattr(app, "plugin_loader", None)
        if loader and hasattr(loader, "get_plugin"):
            plugin = loader.get_plugin(name)
            if plugin is not None:
                return plugin
    except Exception as e:
        _log.debug("plugin_loader.get_plugin failed for %s: %s", name, e)
    # Metod 3: app.plugin_manager.get_plugin() (legacy)
    try:
        manager = getattr(app, "plugin_manager", None)
        if manager and hasattr(manager, "get_plugin"):
            plugin = manager.get_plugin(name)
            if plugin is not None:
                return plugin
    except Exception as e:
        _log.debug("plugin_manager.get_plugin failed for %s: %s", name, e)
    # Metod 4: Direktattribut
    try:
        attr_name = name.replace("-", "_").lower()
        if hasattr(app, attr_name):
            return getattr(app, attr_name)
    except Exception as e:
        _log.debug("getattr failed for %s: %s", name, e)
    return None

def get_schema_info_safe(app: Any) -> SchemaInfo:
    """
    Hämta schema-information säkert.
    Returns:
        SchemaInfo med aktuell data (aldrig None)
    """
    info = SchemaInfo()
    # Försök ts_schema_manager först
    schema_mgr = get_plugin_safe(app, "ts_schema_manager")
    if schema_mgr:
        try:
            if hasattr(schema_mgr, "get_active_version"):
                info.version = schema_mgr.get_active_version()
            if hasattr(schema_mgr, "get_all_schemas"):
                schemas = schema_mgr.get_all_schemas()
                if schemas:
                    info.post_types = [f"PT{t}" for t in sorted(schemas.keys())]
            if hasattr(schema_mgr, "list_versions"):
                versions = schema_mgr.list_versions()
                if versions:
                    # Hantera både SpecVersion-objekt och strängar
                    if versions and hasattr(versions[0], "version"):
                        info.versions = [v.version for v in versions]
                    else:
                        info.versions = list(versions)
            return info
        except Exception as e:
            _log.debug("ts_schema_manager query failed: %s", e)
    # Fallback till ts_spec_import
    ts_spec = get_plugin_safe(app, "ts_spec_import")
    if ts_spec:
        try:
            if hasattr(ts_spec, "get_active_version"):
                info.version = ts_spec.get_active_version()
            if hasattr(ts_spec, "get_all_schemas"):
                schemas = ts_spec.get_all_schemas()
                if schemas:
                    info.post_types = [f"PT{t}" for t in sorted(schemas.keys())]
            if hasattr(ts_spec, "list_versions"):
                versions = ts_spec.list_versions()
                if versions:
                    if versions and hasattr(versions[0], "version"):
                        info.versions = [v.version for v in versions]
                    else:
                        info.versions = list(versions)
        except Exception as e:
            _log.debug("ts_spec_import query failed: %s", e)
    return info

def get_event_bus(app: Any) -> Optional[EventBusProtocol]:
    """Hämta event bus från app."""
    if app is None:
        return None
    # Direkt attribut
    for attr_name in ("event_bus", "events"):
        if hasattr(app, attr_name):
            bus = getattr(app, attr_name)
            if bus is not None:
                return bus
    # Via plugin
    events_plugin = get_plugin_safe(app, "core_events")
    if events_plugin:
        if hasattr(events_plugin, "bus"):
            return events_plugin.bus
        if hasattr(events_plugin, "emit"):
            return events_plugin
    return None

def emit_event_safe(app: Any, event: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """Emit event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        bus.emit(event, data or {})
        return True
    except Exception as e:
        _log.debug("Failed to emit event '%s': %s", event, e)
        return False

def subscribe_event_safe(app: Any, event: str, handler: Callable[..., Any]) -> bool:
    """Prenumerera på event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        if hasattr(bus, "on"):
            bus.on(event, handler)
        elif hasattr(bus, "subscribe"):
            bus.subscribe(event, handler)
        else:
            return False
        return True
    except Exception as e:
        _log.debug("Failed to subscribe to '%s': %s", event, e)
        return False

def unsubscribe_event_safe(app: Any, event: str, handler: Callable[..., Any]) -> bool:
    """Avprenumerera från event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        if hasattr(bus, "off"):
            bus.off(event, handler)
        elif hasattr(bus, "unsubscribe"):
            bus.unsubscribe(event, handler)
        else:
            return False
        return True
    except Exception as e:
        _log.debug("Failed to unsubscribe from '%s': %s", event, e)
        return False

def get_config_value_safe(
    app: Any,
    key: str,
    default: Any = None,
) -> Any:
    """Hämta config-värde robust."""
    if app is None:
        return default
    # Direkt från app.config
    try:
        config = getattr(app, "config", None)
        if config and hasattr(config, "get"):
            result = config.get(key, default)
            if result is not None:
                return result
    except Exception:
        pass
    # Via core_config plugin
    config_plugin = get_plugin_safe(app, "core_config")
    if config_plugin:
        for method_name in ("get_config_value", "get", "get_value"):
            if hasattr(config_plugin, method_name):
                try:
                    result = getattr(config_plugin, method_name)(key, default)
                    if result is not None:
                        return result
                except Exception:
                    pass
    return default

def set_config_value_safe(app: Any, key: str, value: Any) -> bool:
    """Sätt config-värde robust."""
    if app is None:
        return False
    # Direkt från app.config
    try:
        config = getattr(app, "config", None)
        if config and hasattr(config, "set"):
            config.set(key, value)
            return True
    except Exception:
        pass
    # Via core_config plugin
    config_plugin = get_plugin_safe(app, "core_config")
    if config_plugin:
        for method_name in ("set_config_value", "set", "set_value"):
            if hasattr(config_plugin, method_name):
                try:
                    getattr(config_plugin, method_name)(key, value)
                    return True
                except Exception:
                    pass
    return False

# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE DIALOGS

# ══════════════════════════════════════════════════════════════════════════════

def show_message(
    parent: Optional[QWidget],
    title: str,
    message: str,
    icon: MessageIcon = MessageIcon.INFO,
) -> None:
    """Visa meddelandebox."""
    icon_map = {
        MessageIcon.INFO: QMessageBox.Icon.Information,
        MessageIcon.WARNING: QMessageBox.Icon.Warning,
        MessageIcon.ERROR: QMessageBox.Icon.Critical,
        MessageIcon.QUESTION: QMessageBox.Icon.Question,
    }
    msg_box = QMessageBox(parent)
    msg_box.setIcon(icon_map[icon])
    msg_box.setWindowTitle(title)
    msg_box.setText(message)
    msg_box.exec()

def show_info(parent: Optional[QWidget], title: str, message: str) -> None:
    """Visa info-meddelande."""
    show_message(parent, title, message, MessageIcon.INFO)

def show_warning(parent: Optional[QWidget], title: str, message: str) -> None:
    """Visa varning."""
    show_message(parent, title, message, MessageIcon.WARNING)

def show_error(parent: Optional[QWidget], title: str, message: str) -> None:
    """Visa fel."""
    show_message(parent, title, message, MessageIcon.ERROR)

def ask_yes_no(parent: Optional[QWidget], title: str, question: str) -> bool:
    """Fråga ja/nej."""
    result = QMessageBox.question(
        parent,
        title,
        question,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes

# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS

# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    Main GUI Plugin v6.0.2
    Huvudgränssnitt med flikar för all funktionalitet.
    Integrerar dynamiskt med ts_schema_manager, ts_excel_importer och vehicle_registry.
    """
    NAME: str = "Main GUI"
    VERSION: str = __version__
    DESCRIPTION: str = "Huvudgränssnitt för fordonsregistrering (PySide6)"
    AUTHOR: str = "Rickard Längkvist"
    DEPENDENCIES: List[str] = []

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._qapp: Optional[QApplication] = None
        self._main_window: Optional[MainWindow] = None
        self._event_handlers: List[Tuple[str, Callable[..., Any]]] = []

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle

    # ──────────────────────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Initiera plugin."""
        _log.info("%s v%s initializing...", self.NAME, self.VERSION)
        # Skärpan: skalfaktorn måste vara vald innan QApplication finns.
        design.enable_high_dpi()
        # Skapa QApplication
        if QApplication.instance() is None:
            self._qapp = QApplication(sys.argv)
            self._qapp.setApplicationName(
                get_config_value_safe(
                    self.app,
                    "app_name",
                    "Fordonsreg",
                )
            )
        else:
            self._qapp = QApplication.instance()
        # Registrera events
        self._register_events()
        schema_info = get_schema_info_safe(self.app)
        _log.info(
            "%s v%s initialized: TS-spec=%s (%d posttyper)",
            self.NAME,
            self.VERSION,
            schema_info.version or "none",
            schema_info.post_count,
        )

    def activate(self) -> None:
        """Aktivera plugin - skapa huvudfönster."""
        self.is_active = True
        try:
            self._main_window = MainWindow(self.app)
            # En normal ny start ska alltid hamna minimerad i aktivitetsfältet.
            # En separat fokusbegäran kan därefter återställa fönstret.
            self._main_window.showMinimized()
            # Application.start() äger eventloopen och ordnad avslutning.
        except Exception as e:
            _log.error("Failed to activate Main GUI: %s", e, exc_info=True)
            raise

    def deactivate(self) -> None:
        """Deaktivera plugin."""
        if self._main_window:
            window = self._main_window
            if not window.isVisible() or window.isMinimized():
                window._show_from_tray()
            window._quit_requested = True
            if not window.close():
                window._quit_requested = False
                return
            self._main_window = None
        # Behåll registrerade händelser om användaren avbröt stängningen.
        for event_name, handler in self._event_handlers:
            unsubscribe_event_safe(self.app, event_name, handler)
        self._event_handlers.clear()
        self.is_active = False
        _log.info("%s deactivated", self.NAME)

    # ──────────────────────────────────────────────────────────────────────────
    # Event handling

    # ──────────────────────────────────────────────────────────────────────────

    def _register_events(self) -> None:
        """Registrera event handlers."""
        if not self.app:
            return
        events = [
            ("app:ready", self._on_app_ready),
            # Schema events
            (SchemaEvent.TS_SCHEMA_LOADED.value, self._on_schema_changed),
            (SchemaEvent.TS_VERSION_CHANGED.value, self._on_schema_changed),
            (SchemaEvent.TS_SCHEMA_CREATED.value, self._on_schema_changed),
            (SchemaEvent.SCHEMA_LOADED.value, self._on_schema_changed),
            (SchemaEvent.SCHEMA_VERSION_CHANGED.value, self._on_schema_changed),
            (SchemaEvent.SCHEMA_IMPORT_COMPLETED.value, self._on_schema_changed),
            (SchemaEvent.TS_SPEC_IMPORTED.value, self._on_schema_changed),
            (SchemaEvent.TS_SPEC_VERSION_CHANGED.value, self._on_schema_changed),
        ]
        for event_name, handler in events:
            if subscribe_event_safe(self.app, event_name, handler):
                self._event_handlers.append((event_name, handler))
                _log.debug("Subscribed to: %s", event_name)

    def _on_app_ready(self, data: Dict[str, Any]) -> None:
        """Hantera app ready event."""
        _log.info("App is ready, refreshing UI")
        if self._main_window:
            self._main_window.refresh_all()

    def _on_schema_changed(self, data: Dict[str, Any]) -> None:
        """Hantera när schema ändrats."""
        version = data.get("version") or data.get("active_version") or data.get("new_version")
        _log.info("Schema changed: %s", version)
        if self._main_window:
            self._main_window.on_schema_changed(data)

    # ──────────────────────────────────────────────────────────────────────────
    # Public API

    # ──────────────────────────────────────────────────────────────────────────

    @property
    def main_window(self) -> Optional[MainWindow]:
        return self._main_window

    def create_main_window(self) -> MainWindow:
        """Skapa huvudfönster."""
        if self._main_window is None:
            self._main_window = MainWindow(self.app)
        return self._main_window

    def get_vehicle_data_page(self) -> Optional[QWidget]:
        """Hämta VehicleDataPage instans."""
        if self._main_window:
            return self._main_window.vehicle_data_page
        return None

    def show_message(
        self,
        title: str,
        message: str,
        icon: MessageIcon = MessageIcon.INFO,
    ) -> None:
        """Visa meddelandebox."""
        if self._main_window:
            show_message(self._main_window, title, message, icon)

    def ask_question(self, title: str, question: str) -> bool:
        """Visa ja/nej-fråga."""
        if self._main_window:
            return ask_yes_no(self._main_window, title, question)
        return False

# ══════════════════════════════════════════════════════════════════════════════
# MAIN WINDOW

# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    """Applikationens huvudfönster med TS-schema integration."""

    def __init__(self, app: Any) -> None:
        super().__init__()
        self.app = app
        # Programmet startar alltid minimerat. Flaggan stängs av först när
        # användaren själv öppnar fönstret från systemfältet.
        self._startup_phase = True
        self.vehicle_data_page: Optional[QWidget] = None
        self.ts_schema_page: Optional[QWidget] = None
        self._error_log_dialog = None
        self._tray_icon = None
        self._tray_menu = None
        self._tray_separator = None
        self._tray_watch_timer = None
        self._watched_timer = None
        self._watched_pending = []
        self._dashboard_pending = True
        self._quit_requested = False
        # Config
        self.window_config = self._load_window_config()
        # Setup
        self._setup_window()
        self._apply_stylesheet()
        self._init_pages()
        self._init_navigation()
        self._init_menu()
        self._setup_system_tray()
        self._setup_instance_focus()
        self._setup_shortcuts()
        self._setup_watched_folder()
        self._confirm_startup_health()
        # Auto-load dispatch efter 500ms
        QTimer.singleShot(500, self._auto_load_dispatch)
        self._pin_reminder_timer = QTimer(self)
        self._pin_reminder_timer.timeout.connect(self._check_pin_reminder)
        self._pin_reminder_timer.start(60000)
        QTimer.singleShot(2000, self._check_pin_reminder)

    # ──────────────────────────────────────────────────────────────────────────
    # Setup

    # ──────────────────────────────────────────────────────────────────────────

    def _setup_instance_focus(self) -> None:
        """Hantera även begäran som kommit under uppstart, på GUI-tråden."""
        instance = getattr(self.app, "single_instance", None)
        if instance is None:
            return
        instance.set_show_callback(self._show_from_tray)
        self._instance_focus_timer = QTimer(self)
        self._instance_focus_timer.timeout.connect(instance.check_show_request)
        self._instance_focus_timer.start(500)
        QTimer.singleShot(0, instance.check_show_request)

    def _setup_system_tray(self) -> None:
        """Använd systemfält endast när en synlig ikon finns att återvända till."""
        try:
            from PySide6.QtGui import QIcon
            from PySide6.QtWidgets import QSystemTrayIcon
            if not QSystemTrayIcon.isSystemTrayAvailable():
                _log.info("Systemfält saknas; vanlig minimering och stängning används")
                return
            icon = QApplication.windowIcon()
            if icon.isNull():
                icon = QIcon(str(Path(__file__).resolve().parents[2] / "ikon_256.png"))
            if icon.isNull():
                _log.warning("Systemfältsikonen kunde inte laddas")
                return
            tray = QSystemTrayIcon(icon, self)
            menu = QMenu(self)
            menu.addAction("Öppna Fordonsreg", self._show_from_tray)
            menu.addAction("🔎 Sök (Ctrl+K)", self._show_global_search)
            menu.addAction("📥 Ny import...", self._import_file_dialog)
            menu.addAction("📊 Översikt", self._show_dashboard)
            menu.addAction("📋 Felsökningslogg", self._show_error_log)
            separator = menu.addSeparator()
            menu.addAction("Avsluta Fordonsreg", self._quit_application)
            tray.setContextMenu(menu)
            tray.setToolTip("Fordonsreg")
            tray.activated.connect(self._tray_activated)
            tray.messageClicked.connect(self._watched_message_clicked)
            self._tray_icon, self._tray_menu, self._tray_separator = tray, menu, separator
            tray.show()
            self._tray_watch_timer = QTimer(self)
            self._tray_watch_timer.timeout.connect(self._check_tray_available)
            self._tray_watch_timer.start(runtime_policy.BASE_TRAY_INTERVAL_MS)
        except Exception:
            _log.exception("Kunde inte skapa systemfältsikon")
            if self._tray_icon is not None:
                self._tray_icon.hide()
            self._tray_icon = self._tray_menu = self._tray_separator = None

    def _can_hide_to_tray(self) -> bool:
        try:
            from PySide6.QtWidgets import QSystemTrayIcon
            return bool(self._tray_icon is not None and self._tray_icon.isVisible()
                        and QSystemTrayIcon.isSystemTrayAvailable())
        except Exception:
            _log.exception("Systemfältet kunde inte kontrolleras")
            return False

    def _check_tray_available(self) -> None:
        # Om skrivbordets panel försvinner får det dolda fönstret inte bli oåtkomligt.
        if not self._quit_requested and not self._can_hide_to_tray() and not self.isVisible():
            _log.warning("Systemfältet försvann; visar Fordonsreg minimerat igen")
            self.showMinimized()

    def event(self, event) -> bool:
        """Fånga mushändelser så att inaktivt läge nollställs."""
        from PySide6.QtCore import QEvent

        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
                            QEvent.Type.KeyPress, QEvent.Type.Wheel):
            self._note_activity()
        return super().event(event)

    def changeEvent(self, event) -> None:
        from PySide6.QtCore import QEvent
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            # Synligt eller dolt: anpassa hur ofta bakgrunden får arbeta.
            policy = getattr(self, "_apply_timer_policy", None)
            if policy is not None:
                QTimer.singleShot(0, policy)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized() and not getattr(self, "_quit_requested", False):
            self._restore_maximized = bool(event.oldState() & Qt.WindowState.WindowMaximized)
            QTimer.singleShot(0, self._hide_if_still_minimized)

    def _hide_if_still_minimized(self) -> None:
        # En fokusbegäran kan ha återställt fönstret innan timern körs.
        if not self._quit_requested and self.isMinimized() and self._can_hide_to_tray():
            self.hide()

    def _quit_application(self, *_args) -> None:
        """En uttrycklig Avsluta-åtgärd sparar/frågar och avslutar Qt-loopen."""
        if not self.isVisible() or self.isMinimized():
            self._show_from_tray()
        self._quit_requested = True
        try:
            if not self.close():
                self._quit_requested = False
                return
            # En väntande uppdatering installeras när appen avslutas. Då ska
            # appen komma tillbaka av sig själv, utan terminalfönster.
            self._restart_after_update()
            application = QApplication.instance()
            if application is not None:
                application.quit()
        except Exception:
            self._quit_requested = False
            _log.exception("Kunde inte avsluta Fordonsreg")
            raise

    def _restart_after_update(self) -> bool:
        """Be uppdateringen starta om appen. Fel får aldrig hindra avslutet."""
        try:
            plugin = get_plugin_safe(self.app, "auto_update")
        except Exception:
            plugin = None
        starter = getattr(plugin, "restart_after_update", None)
        if starter is None:
            return False
        try:
            return bool(starter())
        except Exception:
            _log.exception("Automatisk omstart efter uppdateringen misslyckades")
            return False

    def _watched_message_clicked(self) -> None:
        """Tray-notisen om en ny fil öppnar importen – användaren väljer själv fil."""
        if not self._watched_pending:
            self._show_from_tray()
            return
        names = ", ".join(item["name"] for item in self._watched_pending[:5])
        answer = QMessageBox.question(
            self, "Ny importfil hittad",
            f"{names}\n\nÖppna importen? Du väljer fil och godkänner själv. "
            "Ingenting importeras automatiskt.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._show_from_tray()
            self._import_file_dialog()

    def _tray_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_from_tray()

    def _show_from_tray(self, *_args) -> None:
        self._startup_phase = False
        if self.isMinimized():
            if getattr(self, "_restore_maximized", False):
                self.showMaximized()
            else:
                self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        # En modal dialog kan blockera huvudfönstret; lyft även den.
        active_modal = getattr(QApplication, "activeModalWidget", None)
        modal = active_modal() if callable(active_modal) else None
        if modal is not None and (modal is self or self.isAncestorOf(modal)):
            modal.raise_()
            modal.activateWindow()

    def add_update_tray_action(self, action: QAction) -> bool:
        """Återanvänd uppdaterarens QAction, inklusive dess aktiverade tillstånd."""
        if self._tray_menu is None:
            return False
        self._tray_menu.insertAction(self._tray_separator, action)
        return True

    def _load_window_config(self) -> WindowConfig:
        """Räkna fram fönsterstorlek och sidomeny utifrån skärmen.

        Programmet ska passa på skärmen det startar på, inte kräva en fast
        storlek. På en liten bärbar dator blir fönstret mindre och sidomenyn
        smalare, så att innehållet får plats utan att något göms.
        """
        width, height = design.PREFERRED_WIDTH, design.PREFERRED_HEIGHT
        self._restore_position = None
        # Tidpunkter för senaste aktivitet och senaste bakgrundskörning.
        import time as _time

        self._last_activity = _time.monotonic()
        self._last_run: dict[str, float] = {}
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width, height = design.window_size(available.width(), available.height())
            # En sparad placering används bara om den fortfarande ryms helt.
            saved = layout_memory.screen_geometry(
                self._root(), screen.name(), available.width(), available.height())
            if saved:
                width, height = saved["width"], saved["height"]
                self._restore_position = (saved["x"], saved["y"])
        return WindowConfig(
            width=width,
            height=height,
            sidebar_width=design.sidebar_width(width),
        )

    def _setup_window(self) -> None:
        """Konfigurera fönster."""
        app_name = get_config_value_safe(self.app, "app_name", "Fordonsreg")
        app_version = get_config_value_safe(self.app, "app_version", __version__)
        self.setWindowTitle(f"{app_name} v{app_version}")
        self.setWindowIcon(QApplication.windowIcon())
        self.resize(self.window_config.width, self.window_config.height)
        position = getattr(self, "_restore_position", None)
        if position:
            self.move(position[0], position[1])
        else:
            # Fönstret fyller skärmens höjd: lägg det i överkanten av
            # arbetsytan så att statusraden syns och inget hamnar utanför.
            screen = QApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                self.move(available.x(), available.y())
        # Fönstret får aldrig bli mindre än skärmen tillåter.
        self.setMinimumSize(min(design.MIN_WINDOW_WIDTH, self.window_config.width),
                            min(design.MIN_WINDOW_HEIGHT, self.window_config.height))

    def _apply_stylesheet(self) -> None:
        """Applicera tema, typsnitt, densitet och skalning på hela fönstret."""
        application = QApplication.instance()
        self._font_family = design.apply_font(QApplication.instance() or self,
                                              font_size=self._font_size())
        self._theme = design.resolve_mode(self._theme_mode(),
                                          design.system_is_dark(application) if application else True)
        self._density = design.resolve_density(self._density_mode(), self.width(), self.height())
        self._scale = design.clamp_scale(self._ui_scale())
        self.setStyleSheet(design.stylesheet(self._theme, self._font_family, self._font_size(),
                                             self._density, self._scale))
        _log.info("Tema %s, typsnitt %s %dpt, densitet %s, skalning %.2f",
                  self._theme, self._font_family, self._font_size(), self._density, self._scale)

    def _appearance_changed(self, *_args) -> None:
        """Växla tema eller textstorlek direkt, utan omstart."""
        self._apply_stylesheet()
        self._refresh_theme_actions()
        self._refresh_nav_icons()

    def _theme_mode(self) -> str:
        """Läst temaläge ur konfigurationen: dark, light eller auto."""
        for key, default in (("ui.theme", design.DEFAULT_MODE), ("theme.mode", design.DEFAULT_MODE)):
            try:
                value = get_config_value_safe(self.app, key, default)
            except Exception:
                continue
            value = str(value or default).strip().lower()
            if value in design.THEME_MODES:
                return value
        return design.DEFAULT_MODE

    def _density_mode(self) -> str:
        """Läst densitet: luftig, kompakt eller automatisk."""
        try:
            value = get_config_value_safe(self.app, "ui.density", design.DEFAULT_DENSITY)
        except Exception:
            value = design.DEFAULT_DENSITY
        value = str(value or design.DEFAULT_DENSITY).strip().lower()
        return value if value in design.DENSITY_MODES else design.DEFAULT_DENSITY

    def _ui_scale(self) -> float:
        """Läst skalning av hela gränssnittet (0,90–1,50)."""
        try:
            value = get_config_value_safe(self.app, "ui.scale", 1.0)
        except Exception:
            value = 1.0
        return design.clamp_scale(value)

    def _font_size(self) -> int:
        """Textstorlek i punkter, alltid inom läsbara gränser."""
        try:
            value = get_config_value_safe(self.app, "ui.font_size", design.DEFAULT_FONT_SIZE)
        except Exception:
            value = design.DEFAULT_FONT_SIZE
        return design.clamp_font_size(value)

    def _init_pages(self) -> None:
        """Initiera sidor från plugins.

        Bara fordonsdata byggs före första ritningen – det är sidan som visas.
        Övriga sidor skapas i :meth:`_init_remaining_pages` när fönstret är
        färdigt, vilket gör starten märkbart snabbare och minskar minnet för
        den som aldrig öppnar dem.
        """
        self.pages: List[Tuple[str, QWidget]] = []
        self.page_widgets: Dict[str, QWidget] = {}
        self._deferred_pages_ready = False
        # 1. Fordonsdata (prioritet 1) – behövs direkt.
        self._init_vehicle_data_page()
        _log.info("Initialized %d pages (resten skapas efter första ritningen)",
                  len(self.pages))

    def _init_remaining_pages(self) -> None:
        """Skapa resten av sidorna när fönstret redan syns."""
        if getattr(self, "_deferred_pages_ready", True):
            return
        self._deferred_pages_ready = True
        try:
            self._init_ts_schema_page()
            self._init_other_pages()
            self._attach_pages_to_stack()
            _log.info("Initialized %d pages totalt", len(self.pages))
        except Exception:
            _log.exception("Resten av sidorna kunde inte skapas")

    def _attach_pages_to_stack(self) -> None:
        """Lägg till sidor som skapades efter att navigeringen byggdes."""
        stack = getattr(self, "stack", None)
        group = getattr(self, "nav_group", None)
        if stack is None or group is None:
            return
        for index, (page_name, widget) in enumerate(self.pages):
            if stack.indexOf(widget) >= 0:
                continue
            stack.addWidget(widget)
            # Knappen skapades redan i _init_navigation; koppla bara widgeten.
            button = group.button(index)
            if button is not None:
                button.setEnabled(True)

    def _init_vehicle_data_page(self) -> None:
        """Initiera fordonsdata-sidan."""
        vehicle_plugin = get_plugin_safe(self.app, "vehicle_registry")
        if not vehicle_plugin or not hasattr(vehicle_plugin, "create_page"):
            placeholder = self._create_placeholder(
                "🚗 Fordonsdata",
                "vehicle_registry saknas eller har ingen create_page",
            )
            self.pages.append(("🚗 Fordonsdata", placeholder))
            self.page_widgets["Fordonsdata"] = placeholder
            return
        try:
            self.vehicle_data_page = vehicle_plugin.create_page(self._get_pin_getter())
            if self.vehicle_data_page:
                self.pages.append(("🚗 Fordonsdata", self.vehicle_data_page))
                self.page_widgets["Fordonsdata"] = self.vehicle_data_page
            else:
                placeholder = self._create_placeholder(
                    "🚗 Fordonsdata",
                    "create_page returnerade None",
                )
                self.pages.append(("🚗 Fordonsdata", placeholder))
                self.page_widgets["Fordonsdata"] = placeholder
        except Exception as e:
            _log.warning("Could not create VehicleDataPage: %s", e, exc_info=True)
            placeholder = self._create_placeholder(
                "🚗 Fordonsdata",
                f"Fel vid skapande: {e}",
            )
            self.pages.append(("🚗 Fordonsdata", placeholder))
            self.page_widgets["Fordonsdata"] = placeholder

    def _init_ts_schema_page(self) -> None:
        """Initiera TS Schema-sidan."""
        # Försök ts_excel_importer (har GUI wizard)
        for plugin_name in ("ts_excel_importer", "ts_spec_viewer", "ts_spec_import"):
            plugin = get_plugin_safe(self.app, plugin_name)
            if plugin and hasattr(plugin, "create_widget"):
                try:
                    widget = plugin.create_widget(self)
                    if widget:
                        self.ts_schema_page = widget
                        self.pages.append(("📋 TS Schema", widget))
                        self.page_widgets["TS Schema"] = widget
                        _log.info("TS Schema page: %s", plugin_name)
                        return
                except Exception as e:
                    _log.debug("Could not create %s widget: %s", plugin_name, e)
        # Fallback: minimal sida
        _log.warning("No TS schema plugin available, creating minimal page")
        self.ts_schema_page = self._create_minimal_ts_schema_page()
        self.pages.append(("📋 TS Schema", self.ts_schema_page))
        self.page_widgets["TS Schema"] = self.ts_schema_page

    def _init_other_pages(self) -> None:
        """Initiera övriga sidor."""
        plugins_map = [
            ("📊 Data Viewer", "data_viewer"),
            ("🏢 Återförsäljare", "dealers_manager"),
            ("🎨 Färger", "colors_manager"),
            ("📥 Dispatch Import", "dispatch_viewer"),
            ("⚙️ Generera TS-fil", "data_mapping"),
            ("📊 Rapporter/Historik", "reports"),
        ]
        for page_name, plugin_name in plugins_map:
            plugin = get_plugin_safe(self.app, plugin_name)
            if plugin and hasattr(plugin, "create_widget"):
                try:
                    widget = plugin.create_widget(self)
                    if widget:
                        self.pages.append((page_name, widget))
                        self.page_widgets[page_name] = widget
                    else:
                        self._add_placeholder_page(page_name, f"{plugin_name} (widget=None)")
                except Exception as e:
                    _log.warning("Could not create %s widget: %s", plugin_name, e)
                    self._add_placeholder_page(page_name, f"{plugin_name} ({e})")
            else:
                reason = f"{plugin_name} saknas" if not plugin else f"{plugin_name} (no create_widget)"
                self._add_placeholder_page(page_name, reason)

    def _add_placeholder_page(self, page_name: str, reason: str) -> None:
        """Lägg till placeholder-sida."""
        placeholder = self._create_placeholder(page_name, reason)
        self.pages.append((page_name, placeholder))
        self.page_widgets[page_name] = placeholder

    def _create_placeholder(self, page_name: str, reason: str) -> QWidget:
        """Skapa placeholder för saknad plugin."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(design.strip_emoji_prefix(page_name))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        msg = QLabel(f"Plugin ej tillgänglig: {reason}")
        msg.setObjectName("Muted")
        msg.setStyleSheet(f"color: {design.palette(self._theme)['warning']};")
        layout.addWidget(msg)
        info = QLabel(
            "Kontrollera att plugin är installerad och aktiverad korrekt\n\n"
            "Tips: Starta om programmet eller kontakta administratör"
        )
        info.setObjectName("Muted")
        info.setWordWrap(True)
        layout.addWidget(info)
        return widget

    def _create_minimal_ts_schema_page(self) -> QWidget:
        """Skapa minimal TS Schema-sida."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        title = QLabel("TS Schema-hantering")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        # Schema-info
        schema_info = get_schema_info_safe(self.app)
        info_box = QGroupBox("Aktiv version")
        info_layout = QFormLayout(info_box)
        version_label = QLabel(schema_info.version or "Ingen version aktiv")
        colors = design.palette(getattr(self, "_theme", "dark"))
        version_label.setStyleSheet(
            f"color: {colors['success'] if schema_info.is_active else colors['warning']}; "
            "font-weight: bold;"
        )
        info_layout.addRow("Version:", version_label)
        types_label = QLabel(
            ", ".join(schema_info.post_types) if schema_info.post_types else "Inga posttyper"
        )
        info_layout.addRow("Posttyper:", types_label)
        layout.addWidget(info_box)
        # Import-knapp
        import_btn = QPushButton("📥 Importera TS-spec från Excel...")
        import_btn.setObjectName("PrimaryButton")
        import_btn.clicked.connect(self._import_ts_schema_dialog)
        layout.addWidget(import_btn)
        # Versionsväljare
        if schema_info.versions:
            version_box = QGroupBox("Byt version")
            version_layout = QVBoxLayout(version_box)
            combo = QComboBox()
            combo.addItems(schema_info.versions)
            if schema_info.version and schema_info.version in schema_info.versions:
                combo.setCurrentText(schema_info.version)
            combo.currentTextChanged.connect(self._change_schema_version)
            version_layout.addWidget(combo)
            layout.addWidget(version_box)
        layout.addStretch()
        return widget

    def _init_navigation(self) -> None:
        """Initiera navigation (sidebar + stackwidget)."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        # Sidebar
        self.sidebar = self._create_sidebar()
        # En delare gör sidomenyn justerbar och ihågkommen (förslag 2), så att
        # den som vill se mer av tabellen kan dra i kanten. Delarens handtag
        # är smalt och syns först när muspekaren är över kanten.
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("MainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(4)
        self.main_splitter.addWidget(self.sidebar)
        # Stackwidget
        self.stack = QStackedWidget()
        self.main_splitter.addWidget(self.stack)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        start_width = design.sidebar_initial_width(
            get_config_value_safe(self.app, "ui.sidebar_width", 0),
            self.window_config.width, self._density_mode())
        self._sidebar_user_width = start_width
        self.main_splitter.setSizes([
            max(1, start_width),
            max(200, self.window_config.width - start_width),
        ])
        self.main_splitter.splitterMoved.connect(self._on_sidebar_resized)
        main_layout.addWidget(self.main_splitter)
        # Lägg till alla sidor
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for i, (page_name, widget) in enumerate(self.pages):
            self.stack.addWidget(widget)
            btn = QPushButton(design.strip_emoji_prefix(page_name))
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            # Skärmläsaren ska alltid få hela sidnamnet, även när bara ikonen syns.
            design.set_accessible(btn, design.label_for_icon_button(design.strip_emoji_prefix(page_name)),
                                  f"Öppna {design.strip_emoji_prefix(page_name)}")
            btn.setToolTip(page_name)
            # Ikonknapparna centreras när texten är borta, annars hamnar de
            # olika långt in beroende på textens längd.
            btn.setStyleSheet("text-align: center;" if not design.icon_only_sidebar(
                self.window_config.width) else "")
            self._apply_nav_icon(btn, page_name)
            btn.clicked.connect(lambda checked, idx=i: self._navigate_to_page(idx))
            self.nav_group.addButton(btn, i)
            self.sidebar_layout.addWidget(btn)
        self.sidebar_layout.addStretch()
        # Statistik-labels
        self._add_stats_labels()
        # Default sida
        if self.pages:
            if self.nav_group.button(0):
                self.nav_group.button(0).setChecked(True)
                self.stack.setCurrentIndex(0)
        # Sidor som skapas efter första ritningen kopplas in här.
        self._attach_pages_to_stack()
        # Starta timers. De första uppdateringarna sker efter att fönstret
        # ritats, så att starten inte fördröjs av statistikberäkningar.
        QTimer.singleShot(1200, self._update_statistics)
        QTimer.singleShot(1600, self._update_schema_status)

    def _create_sidebar(self) -> QWidget:
        """Skapa navigation som kan rullas om skärmen är för låg."""
        from PySide6.QtWidgets import QScrollArea, QFrame
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sidebar_scroll.setObjectName("Sidebar")
        sidebar_scroll.setMinimumWidth(design.SIDEBAR_MIN_WIDTH)
        sidebar_scroll.setMaximumWidth(design.sidebar_max_width(self.width()))
        sidebar = QWidget()
        sidebar.setObjectName("SidebarBody")
        self.sidebar_layout = QVBoxLayout(sidebar)
        self.sidebar_layout.setContentsMargins(10, 18, 10, 18)
        # Samma symbol som på fönster och i systemfältet.
        app_name = get_config_value_safe(self.app, "app_name", "Fordonsreg")
        brand_row = QHBoxLayout()
        brand_icon = QLabel()
        pixmap = QApplication.windowIcon().pixmap(32, 32)
        if not pixmap.isNull():
            brand_icon.setPixmap(pixmap)
            brand_icon.setToolTip("Fordonsreg")
            brand_row.addWidget(brand_icon)
        logo = QLabel(app_name)
        logo.setObjectName("Brand")
        logo.setWordWrap(True)
        brand_row.addWidget(logo, 1)
        self.sidebar_layout.addLayout(brand_row)
        self.sidebar_layout.addSpacing(20)
        sidebar_scroll.setWidget(sidebar)
        return sidebar_scroll

    def _add_stats_labels(self) -> None:
        """Lägg till statistik-labels i sidebar."""
        # Schema-status
        schema_header = QLabel("TS SCHEMA")
        schema_header.setObjectName("SidebarSection")
        self.sidebar_layout.addWidget(schema_header)
        self.schema_status = QLabel("Laddar...")
        self.schema_status.setObjectName("SidebarStat")
        self.schema_status.setWordWrap(True)
        self.sidebar_layout.addWidget(self.schema_status)
        # Fordons-statistik
        stats_header = QLabel("STATISTIK")
        stats_header.setObjectName("SidebarSection")
        self.sidebar_layout.addWidget(stats_header)
        self.stats_info = QLabel("Laddar...")
        self.stats_info.setObjectName("SidebarStat")
        self.stats_info.setWordWrap(True)
        self.sidebar_layout.addWidget(self.stats_info)

    def _init_menu(self) -> None:
        """Initiera menybar."""
        menubar = self.menuBar()
        # Menyraden får sitt utseende från programmets gemensamma stilark.
        self._create_file_menu(menubar)
        self._create_schema_menu(menubar)
        self._create_view_menu(menubar)
        self._create_settings_menu(menubar)
        self._create_tools_menu(menubar)
        self._create_help_menu(menubar)

    def _create_file_menu(self, menubar: QMenuBar) -> None:
        """Skapa Arkiv-meny."""
        file_menu = menubar.addMenu("Arkiv")
        file_menu.addAction("📥 Importera fil...", self._import_file_dialog)
        file_menu.addAction("📤 Exportera fordonsdata...", self._export_vehicle_data)
        file_menu.addSeparator()
        file_menu.addAction("🚪 Avsluta", self._quit_application)

    def _import_file_dialog(self) -> None:
        from plugins.main_gui.dialogs.import_dialog import start_import
        start_import(self, self.app, self.vehicle_data_page,
                     self.page_widgets.get("🏢 Återförsäljare"))

    def _create_schema_menu(self, menubar: QMenuBar) -> None:
        """Skapa Schema-meny."""
        schema_menu = menubar.addMenu("Schema")
        schema_menu.addAction("📥 Importera TS-spec...", self._import_ts_schema_dialog)
        schema_menu.addAction("🔄 Byt version...", self._change_version_dialog)
        schema_menu.addSeparator()
        schema_menu.addAction("ℹ️ Visa schema-info...", self._show_schema_info)
        schema_menu.addAction("📊 Jämför versioner...", self._compare_versions_dialog)

    def _create_view_menu(self, menubar: QMenuBar) -> None:
        """Skapa Visa-menyn med tema, textstorlek och fönsteråterställning."""
        view_menu = menubar.addMenu("Visa")
        theme_menu = view_menu.addMenu("Tema")
        theme_menu.setIcon(self._menu_icon("theme-auto"))
        self._theme_actions = {}
        from PySide6.QtGui import QActionGroup
        group = QActionGroup(self)
        group.setExclusive(True)
        for mode in design.THEME_MODES:
            action = QAction(design.THEME_LABELS[mode], self)
            action.setCheckable(True)
            action.setData(mode)
            icon = self._menu_icon(f"theme-{mode}")
            if not icon.isNull():
                action.setIcon(icon)
            action.setStatusTip(f"Använd {design.THEME_LABELS[mode].lower()} tema")
            action.triggered.connect(lambda checked=False, value=mode: self._set_theme_mode(value))
            group.addAction(action)
            theme_menu.addAction(action)
            self._theme_actions[mode] = action

        density_menu = view_menu.addMenu("Densitet")
        self._density_actions = {}
        from PySide6.QtGui import QActionGroup as _DensityGroup
        density_group = _DensityGroup(self)
        density_group.setExclusive(True)
        for mode in design.DENSITY_MODES:
            action = QAction(design.DENSITY_LABELS[mode], self)
            action.setCheckable(True)
            action.setData(mode)
            action.setStatusTip("Kompakt läge ger fler rader och mindre luft")
            action.triggered.connect(lambda checked=False, value=mode: self._set_density(value))
            density_group.addAction(action)
            density_menu.addAction(action)
            self._density_actions[mode] = action

        rows_menu = view_menu.addMenu("Radhöjd i tabeller")
        self._row_actions = {}
        for mode in design.TABLE_ROW_MODES:
            action = QAction(design.TABLE_ROW_LABELS[mode], self)
            action.setCheckable(True)
            action.setStatusTip(f"{design.row_height(mode)} pixlar per rad")
            action.triggered.connect(lambda checked=False, value=mode: self._set_row_mode(value))
            rows_menu.addAction(action)
            self._row_actions[mode] = action
        wrap_action = QAction("Bryt lång text i celler", self)
        wrap_action.setCheckable(True)
        wrap_action.setStatusTip("Visa hela värdet i stället för att klippa det")
        wrap_action.triggered.connect(lambda checked=False: self._set_word_wrap(checked))
        rows_menu.addSeparator()
        rows_menu.addAction(wrap_action)
        self._wrap_action = wrap_action

        scale_menu = view_menu.addMenu("Skala gränssnittet")
        self._scale_actions = {}
        for value in design.scale_steps():
            action = QAction(f"{int(round(value * 100))} %", self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, step=value: self._set_ui_scale(step))
            scale_menu.addAction(action)
            self._scale_actions[value] = action

        text_menu = view_menu.addMenu("Textstorlek")
        for label, size in (("Mindre", design.clamp_font_size(self._font_size() - 1)),
                            ("Standard", design.DEFAULT_FONT_SIZE),
                            ("Större", design.clamp_font_size(self._font_size() + 1))):
            action = QAction(f"{label} ({size} pt)", self)
            action.triggered.connect(lambda checked=False, value=size: self._set_font_size(value))
            text_menu.addAction(action)
        view_menu.addSeparator()
        scaling = view_menu.addAction("Skalningstest…")
        scaling.setStatusTip("Kontrollera att ingen text klipps vid 100–200 %")
        scaling.triggered.connect(self._show_scaling_audit)
        contrast = view_menu.addAction("Kontrastkontroll…")
        contrast.setStatusTip("Visa kontrasten för alla text- och bakgrundspar")
        contrast.triggered.connect(self._show_contrast_check)
        reset = view_menu.addAction("Anpassa fönstret till skärmen")
        reset.setStatusTip("Räkna om storleken efter den skärm fönstret ligger på")
        reset.triggered.connect(self._fit_window_to_screen)
        self._refresh_theme_actions()

    def _refresh_theme_actions(self) -> None:
        """Markera det tema, den densitet och den skalning som används."""
        if getattr(self, "_theme_actions", None):
            current = self._theme_mode()
            for mode, action in self._theme_actions.items():
                action.setChecked(mode == current)
        if getattr(self, "_density_actions", None):
            current_density = self._density_mode()
            for mode, action in self._density_actions.items():
                action.setChecked(mode == current_density)
        if getattr(self, "_row_actions", None):
            current_row = self._row_mode()
            for mode, action in self._row_actions.items():
                action.setChecked(mode == current_row)
        if getattr(self, "_wrap_action", None) is not None:
            self._wrap_action.setChecked(self._wrap_enabled())
        if getattr(self, "_scale_actions", None):
            current_scale = round(self._ui_scale(), 2)
            for value, action in self._scale_actions.items():
                action.setChecked(abs(value - current_scale) < 0.001)

    def _set_density(self, mode: str) -> None:
        """Spara och tillämpa vald densitet direkt."""
        if mode not in design.DENSITY_MODES:
            return
        set_config_value_safe(self.app, "ui.density", mode)
        _log.info("Densitet vald: %s", mode)
        self._appearance_changed()

    def _set_ui_scale(self, value: float) -> None:
        """Spara och tillämpa vald skalning direkt."""
        step = design.clamp_scale(value)
        set_config_value_safe(self.app, "ui.scale", step)
        _log.info("Gränssnittet skalas till %.2f", step)
        self._appearance_changed()

    def _set_row_mode(self, mode: str) -> None:
        """Radhöjd i tabeller: kompakt, normal eller luftig (förslag 8)."""
        if mode not in design.TABLE_ROW_MODES:
            return
        set_config_value_safe(self.app, "ui.row_height", mode)
        self._row_mode = mode
        self._appearance_changed()

    def _set_word_wrap(self, enabled: bool) -> None:
        """Textbrytning i celler, så att långa värden syns hela (förslag 8)."""
        set_config_value_safe(self.app, "ui.word_wrap", bool(enabled))
        self._word_wrap = bool(enabled)
        self._appearance_changed()

    def _row_mode(self) -> str:
        """Läst radhöjd, med de gamla värdena kvar som alias."""
        try:
            value = get_config_value_safe(self.app, "ui.row_height", "")
        except Exception:
            value = ""
        if not value:
            # Utan eget val följer radhöjden densiteten.
            return "compact" if self._density == "compact" else "normal"
        return design.resolve_row_mode(value)

    def _wrap_enabled(self) -> bool:
        """Läst textbrytning. Standard: på, utom i kompakt läge."""
        try:
            return bool(get_config_value_safe(self.app, "ui.word_wrap",
                                             self._density != "compact"))
        except Exception:
            return self._density != "compact"

    def _show_memory_status(self) -> None:
        """Visa minnesläget och låt användaren frigöra minne."""
        from plugins.main_gui.dialogs.memory_dialog import MemoryDialog
        views = []
        table = getattr(getattr(self, "vehicle_data_page", None), "_table", None)
        if table is not None:
            views.append(table)
        MemoryDialog(self, self._root(), views).exec()

    # ── Bakgrundsläge: spara batteri och minne ─────────────────────────
    def _is_silent(self) -> bool:
        """Sant när fönstret är dolt eller minimerat och inget behöver ritas."""
        try:
            return self.isMinimized() or not self.isVisible()
        except Exception:
            return False

    def _is_idle(self) -> bool:
        """Sant när fönstret stått orört en längre stund."""
        try:
            from PySide6.QtGui import QCursor
            import time

            last = getattr(self, "_last_activity", time.monotonic())
            return (time.monotonic() - last) >= runtime_policy.idle_after_seconds(self._is_silent())
        except Exception:
            return False

    def _timer_interval(self, base_ms: int) -> int:
        """Aktuellt intervall för en återkommande uppgift."""
        return runtime_policy.effective_interval(base_ms, self._is_silent(), self._is_idle())

    def _next_interval(self, base_ms: int) -> int:
        """Intervall för nästa körning, med ett säkert standardvärde."""
        try:
            return self._timer_interval(base_ms)
        except Exception:
            return base_ms

    def _background_allowed(self, name: str, base_ms: int) -> bool:
        """Får en bakgrundsuppgift köra nu, med hänsyn till dolt läge?"""
        import time

        if not self._is_silent() and not self._is_idle():
            self._last_run[name] = time.monotonic()
            return True
        last = getattr(self, "_last_run", {}).get(name)
        now = time.monotonic()
        interval = runtime_policy.effective_interval(base_ms, True, self._is_idle()) / 1000
        if last is None or (now - last) >= interval:
            self._last_run[name] = now
            return True
        return False

    def _apply_timer_policy(self) -> None:
        """Ställ om alla återkommande timers efter synligt, dolt eller inaktivt läge."""
        try:
            if getattr(self, "_last_run", None) is None:
                self._last_run = {}
            silent = self._is_silent()
            pairs = (
                ("_watched_timer", runtime_policy.BASE_WATCH_INTERVAL_MS),
                ("_tray_watch_timer", runtime_policy.BASE_TRAY_INTERVAL_MS),
                ("_instance_focus_timer", runtime_policy.BASE_INSTANCE_INTERVAL_MS),
                ("_year_timer", 60 * 60 * 1000),
            )
            for attribute, base in pairs:
                timer = getattr(self, attribute, None)
                if timer is None or not hasattr(timer, "setInterval"):
                    continue
                interval = runtime_policy.effective_interval(base, silent, self._is_idle())
                if timer.interval() != interval:
                    timer.setInterval(interval)
            _log.debug("Timerläge: %s", "dolt" if silent else "synligt")
        except Exception:
            _log.debug("Timerläget kunde inte ställas om", exc_info=True)

    def _note_activity(self) -> None:
        """Anteckna att användaren gjorde något, så inaktivt läge nollställs."""
        import time

        self._last_activity = time.monotonic()

    def _show_scaling_audit(self) -> None:
        """Mät fönstret och rapportera text som klipps (förslag 4)."""
        from core import layout_audit
        levels = layout_audit.scaling_levels()
        results = [layout_audit.audit_widget(self, level) for level in levels]
        lines = []
        for row in results:
            head = f"{row['scale']} %: {'OK' if row['ok'] else 'problem'}"
            lines.append(head)
            for item in row["clipped"][:12]:
                text_preview = item['text']
                lines.append(f"    klippt: {item['widget']} – "
                             f"\"{text_preview}\" behöver {item['needed']} px, "
                             f"har {item['available']} px")
            if row["overflow"]:
                lines.append(f"    tabellen är {row['overflow']} px bredare än vyn")
        text = "\n".join(lines)
        summary = layout_audit.summary_text(results[-1:]) if results else "Inget att mäta."
        box = QMessageBox(self)
        box.setWindowTitle("Skalningstest")
        box.setIcon(QMessageBox.Icon.Information if all(r["ok"] for r in results)
                    else QMessageBox.Icon.Warning)
        box.setText("Kontroll av text och tabeller vid olika skalning")
        box.setInformativeText(summary)
        box.setDetailedText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _show_screenshot(self) -> None:
        """Skärmbild av fönstret med PIN-fält maskade (förslag 25)."""
        from plugins.main_gui.dialogs.screenshot_dialog import ScreenshotDialog
        dialog = ScreenshotDialog(self, self._root(), self)
        dialog.exec()

    def _show_contrast_check(self) -> None:
        """Visa kontrasten för alla text- och bakgrundspar (förslag 22)."""
        rows = []
        for theme in ("dark", "light"):
            rows.extend(design.contrast_report(theme))
        problems = [row for row in rows if not row["passes"]]
        lines = []
        for row in rows:
            mark = "OK" if row["passes"] else "FÖR LÅG"
            lines.append(f"{design.THEME_LABELS.get(row['theme'], row['theme']):<6} "
                         f"{row['label']:<30} {row['ratio']:.2f}:1  (krav {row['required']:.1f})  {mark}")
        text = "\n".join(lines)
        if problems:
            text += f"\n\n{len(problems)} par ligger under kravet och bör justeras."
        else:
            text += "\n\nAlla par klarar WCAG-kravet för sin typ."
        box = QMessageBox(self)
        box.setWindowTitle("Kontrastkontroll")
        box.setIcon(QMessageBox.Icon.Warning if problems else QMessageBox.Icon.Information)
        box.setText("Kontrast i mörkt och ljust tema")
        box.setInformativeText("Text kräver 4,5:1 och ramar 3:1 enligt WCAG 2.1 AA.")
        box.setDetailedText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _set_theme_mode(self, mode: str) -> None:
        """Spara och tillämpa valt tema direkt."""
        if mode not in design.THEME_MODES:
            return
        set_config_value_safe(self.app, "ui.theme", mode)
        _log.info("Tema valt: %s", mode)
        self._appearance_changed()

    def _set_font_size(self, size: int) -> None:
        """Spara och tillämpa vald textstorlek direkt."""
        value = design.clamp_font_size(size)
        set_config_value_safe(self.app, "ui.font_size", value)
        _log.info("Textstorlek vald: %d pt", value)
        self._appearance_changed()

    def _fit_window_to_screen(self) -> None:
        """Anpassa fönstret till skärmen det ligger på."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width, height = design.window_size(available.width(), available.height())
        self.window_config = WindowConfig(width=width, height=height,
                                          sidebar_width=design.sidebar_width(width))
        self.resize(width, height)
        self.move(available.x(), available.y())
        # Bredden sätts på delaren, så att användaren fortfarande kan dra i den.
        if getattr(self, "main_splitter", None) is not None:
            self.main_splitter.setSizes([self.window_config.sidebar_width,
                                         max(200, width - self.window_config.sidebar_width)])

    def _menu_icon(self, name: str):
        """Ikon till menyval, ritad i skärmens upplösning."""
        from PySide6.QtGui import QIcon
        icon = design.icon(self._root(), name, getattr(self, "_theme", "dark"),
                           design.ICON_SIZE_REGULAR, widget=self)
        return icon if icon is not None else QIcon()

    def _apply_nav_icon(self, button: QPushButton, page_name: str) -> None:
        """Sätt temafärgad ikon på en sidomenyknapp.

        Ikonen ritas i 24 px och visas i 16 px i den smala menyn. Den ritas i
        skärmens egen upplösning, så den blir lika skarp som texten bredvid.
        """
        size = design.icon_size("sidebar")
        icon = design.icon(self._root(), design.page_icon(page_name),
                           getattr(self, "_theme", "dark"), design.ICON_SIZE_REGULAR,
                           widget=button)
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QSize(size, size))

    def _refresh_nav_icons(self) -> None:
        """Rita om sidomenyns ikoner när temat ändras."""
        buttons = getattr(self, "nav_group", None)
        if buttons is None or not self.pages:
            return
        for index, (page_name, _widget) in enumerate(self.pages):
            button = buttons.button(index)
            if button is not None:
                self._apply_nav_icon(button, page_name)

    def _root(self):
        """Programmets rotmapp, för ikoner och resurser."""
        return Path(__file__).resolve().parents[2]

    def _create_settings_menu(self, menubar: QMenuBar) -> None:
        """Skapa Inställningar-meny."""
        settings_menu = menubar.addMenu("Inställningar")
        settings_menu.addAction("🔐 Gemensam PIN-kod...", self._settings_shared_pin)
        settings_menu.addAction("🔢 Hantera FilID-serie...", self._manage_file_id)
        settings_menu.addSeparator()
        # Profiler för importen har en egen flik i stället för spridda
        # "spara profil"-knappar. Gäller de program som använder profilagret.
        settings_menu.addAction("🗂 Profiler för import...", self._settings_profiles)

    def _settings_profiles(self) -> None:
        """Öppna profilfliken. En trasig profilfil får inte hindra resten."""
        try:
            from plugins.main_gui.dialogs.profiles_tab import ProfilesDialog
            ProfilesDialog(self).exec()
        except Exception as exc:
            _log.exception("Kunde inte öppna profilinställningarna")
            QMessageBox.warning(self, "Profiler", f"Profilinställningarna kunde inte öppnas: {exc}")

    def _settings_shared_pin(self) -> None:
        from plugins.main_gui.dialogs.dealer_pin import change_pin
        dealer = get_plugin_safe(self.app, "dealers_manager") or getattr(self.app, "dealers", None)
        if dealer is None:
            show_error(self, "PIN", "Den gemensamma PIN-hanteraren är inte tillgänglig.")
            return
        change_pin(self, dealer)

    def _check_pin_reminder(self) -> None:
        # Stör inte en app som startar minimerad; påminn när fönstret används.
        if not self.isVisible() or self.isMinimized():
            return
        dealer = get_plugin_safe(self.app, "dealers_manager") or getattr(self.app, "dealers", None)
        if dealer is None:
            return
        try:
            manager = dealer.dealer_pin()
            if not manager.reminder_due():
                return
            manager.mark_reminded()
            answer = QMessageBox.question(self, "Byt PIN-kod",
                "Det är minst en månad sedan PIN-koden byttes. Vill du byta den nu? "
                "Du kan välja Nej och ändra den senare i Inställningar.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                self._settings_shared_pin()
        except Exception as exc:
            _log.warning("PIN-påminnelsen kunde inte kontrolleras: %s", exc)

    def _create_tools_menu(self, menubar: QMenuBar) -> None:
        """Skapa Verktyg-meny."""
        tools_menu = menubar.addMenu("Verktyg")
        tools_menu.addAction("🔎 Sök i allt (Ctrl+K)...", self._show_global_search)
        tools_menu.addAction("📊 Översikt...", self._show_dashboard)
        tools_menu.addAction("📁 Bevakad mapp...", self._show_watched_folder)
        tools_menu.addSeparator()
        tools_menu.addAction("🧾 Verifiera TS-underlag...", self._show_ts_verification)
        tools_menu.addSeparator()
        tools_menu.addAction("🔍 Validera VIN...", self._validate_vin_dialog)
        tools_menu.addAction("📊 Visa statistik...", self._show_statistics)
        tools_menu.addSeparator()
        tools_menu.addAction("🔄 Uppdatera cache", self._refresh_cache)
        tools_menu.addAction("🔧 Bygg om index", self._rebuild_index)
        tools_menu.addSeparator()
        tools_menu.addAction("⚡ Minne och prestanda...", self._show_memory_status)
        tools_menu.addSeparator()
        tools_menu.addAction("📋 Visa felsökningslogg...", self._show_error_log)
        tools_menu.addAction("🧭 Felkodsguide...", self._show_error_guide)
        tools_menu.addSeparator()
        tools_menu.addAction("🧠 Visa inlärning...", self._show_learning_info)
        tools_menu.addAction("⏯ Aktivera eller pausa inlärning", self._toggle_learning)
        tools_menu.addAction("🗑 Rensa inlärda förslag...", self._clear_learning)

    def _learning_store(self):
        from core.learning import LearningStore
        return LearningStore(Path(__file__).resolve().parents[2] / "json" / "mappings" / "learning.json")

    def _show_learning_info(self) -> None:
        try:
            status = self._learning_store().status()
            state = "aktiv" if status["enabled"] else "pausad"
            QMessageBox.information(self, "Inlärning",
                f"Inlärning är {state}.\n"
                f"Sparade rubrikregler: {status['rules']}, motsägande regler: {status['conflicts']}.\n\n"
                "Fordonsreg lär sig kolumnmappningar för Fordonsdata och Återförsäljare. "
                "Den sparar inga rader eller PIN-koder. Du granskar alltid mappningen. "
                "Andra funktioner och TS-formatet lär sig inte automatiskt ännu.")
        except Exception as exc:
            _log.warning("Kunde inte läsa inlärningsstatus: %s", exc)
            QMessageBox.warning(self, "Inlärning", f"Kunde inte läsa inlärningsminnet: {exc}")

    def _toggle_learning(self) -> None:
        try:
            store = self._learning_store()
            enabled = not store.status()["enabled"]
            store.set_enabled(enabled)
            QMessageBox.information(self, "Inlärning", "Inlärning aktiverad." if enabled else "Inlärning pausad. Inlärda förslag bevaras men används inte; manuellt sparade mappningar påverkas inte.")
        except Exception as exc:
            _log.warning("Kunde inte ändra inlärning: %s", exc)
            QMessageBox.warning(self, "Inlärning", f"Kunde inte ändra inställningen: {exc}")

    def _clear_learning(self) -> None:
        try:
            answer = QMessageBox.question(self, "Rensa inlärning",
                "Rensa alla automatiskt inlärda förslag? Namngivna och PIN-skyddade mappningar ändras inte.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self._learning_store().clear()
                QMessageBox.information(self, "Inlärning", "De inlärda förslagen har rensats.")
        except Exception as exc:
            _log.warning("Kunde inte rensa inlärning: %s", exc)
            QMessageBox.warning(self, "Inlärning", f"Kunde inte rensa inlärningsminnet: {exc}")

    def _show_error_guide(self) -> None:
        from plugins.main_gui.dialogs.error_guide_dialog import ErrorGuideDialog
        ErrorGuideDialog(self).exec()

    def _show_error_log(self) -> None:
        """Öppna den gemensamma felloggen i en skrivskyddad vy."""
        try:
            from plugins.main_gui.dialogs.error_log_dialog import ErrorLogDialog
            if self._error_log_dialog is None:
                self._error_log_dialog = ErrorLogDialog(self)
            self._error_log_dialog.reload()
            self._error_log_dialog.show()
            self._error_log_dialog.raise_()
            self._error_log_dialog.activateWindow()
        except Exception as exc:
            _log.exception("Kunde inte öppna felsökningsloggen")
            QMessageBox.warning(self, "Felsökningslogg", f"Kunde inte öppna loggen: {exc}")

    def _create_help_menu(self, menubar: QMenuBar) -> None:
        """Skapa Hjälp-meny."""
        help_menu = menubar.addMenu("Hjälp")
        help_menu.addAction("📖 Manual", self._show_manual)
        help_menu.addAction("📸 Skärmbild för support...", self._show_screenshot)
        help_menu.addAction("📜 Licens och användningsvillkor...", self._show_license)
        help_menu.addAction("💙 Stöd Fordonsreg (donation)...", self._show_swish_qr)
        help_menu.addSeparator()
        help_menu.addAction("ℹ️ Om programmet", self._show_about)

    def _show_license(self) -> None:
        from plugins.main_gui.dialogs.license_dialog import show_license
        show_license(self)

    def _show_swish_qr(self) -> None:
        from plugins.main_gui.dialogs.swish_qr_dialog import SwishQrDialog
        SwishQrDialog(self).exec()

    # ──────────────────────────────────────────────────────────────────────────
    # Sökning, översikt, bevakad mapp och starthälsa

    def _setup_shortcuts(self) -> None:
        """Ctrl+K ska fungera även när fokus ligger i en tabell."""
        shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(self._show_global_search)
        self._search_shortcut = shortcut

    def _root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _show_global_search(self) -> None:
        from plugins.main_gui.dialogs.global_search_dialog import GlobalSearchDialog
        GlobalSearchDialog(self, on_open_vehicle=self._open_vehicle_from_search).exec()

    def _open_vehicle_from_search(self, year: int, row: int) -> None:
        """Öppna rätt år och markera posten som sökträffen pekar på."""
        page = self.vehicle_data_page
        if page is None:
            QMessageBox.information(self, "Sökning", "Fordonsdata är inte tillgängligt.")
            return
        try:
            self._navigate_to_named_page("Fordonsdata")
            opener = getattr(page, "open_year", None)
            if callable(opener):
                tab = opener(int(year))
            else:
                tab = None
            if tab is not None and hasattr(tab, "select_row"):
                tab.select_row(int(row))
        except Exception as exc:
            _log.warning("Sökträffen kunde inte öppnas: %s", exc)
            QMessageBox.warning(self, "Sökning", f"Posten kunde inte öppnas: {exc}")

    def _navigate_to_named_page(self, name: str) -> None:
        widget = self.page_widgets.get(name)
        if widget is None:
            return
        index = self.stack.indexOf(widget)
        if index >= 0:
            self._navigate_to_page(index)

    def _show_dashboard(self) -> None:
        from plugins.main_gui.dialogs.dashboard_dialog import DashboardDialog
        self._dashboard_pending = False
        DashboardDialog(self).exec()

    def _show_ts_verification(self) -> None:
        from plugins.main_gui.dialogs.ts_verification_dialog import TsVerificationDialog
        TsVerificationDialog(self).exec()

    def _show_watched_folder(self) -> None:
        from plugins.main_gui.dialogs.watched_folder_dialog import WatchedFolderDialog
        dialog = WatchedFolderDialog(self)
        if dialog.exec() and dialog.changed:
            self._reload_watched_folder()

    def _watched_settings_path(self) -> Path:
        return self._root() / "json" / "watched_folder.json"

    def _setup_watched_folder(self) -> None:
        """Kontrollera mappen då och då. Ingenting importeras automatiskt."""
        self._watched_timer = QTimer(self)
        self._watched_timer.timeout.connect(self._check_watched_folder)
        self._watched_timer.start(30000)
        QTimer.singleShot(6000, self._check_watched_folder)

    def _reload_watched_folder(self) -> None:
        self._check_watched_folder(force=True)

    def _check_watched_folder(self, force: bool = False) -> None:
        # I dolt läge läses mappen bara med det längre intervallet, så att en
        # nätverksmapp inte frågas var 30:e sekund i onödan.
        if not force and not self._background_allowed(
                "watched", runtime_policy.BASE_WATCH_INTERVAL_MS):
            return
        try:
            from core.watched_folder import load_settings, mark_reported, save_settings, scan
            settings = load_settings(self._watched_settings_path())
            new_files = scan(settings)
            if not new_files:
                return
            settings = mark_reported(settings, new_files)
            save_settings(self._watched_settings_path(), settings)
            self._watched_pending = new_files
            names = ", ".join(item["name"] for item in new_files[:3])
            more = "" if len(new_files) <= 3 else f" (+{len(new_files) - 3} fler)"
            if self._tray_icon is not None and self._tray_icon.isVisible():
                self._tray_icon.showMessage(
                    "Ny importfil hittad", f"{names}{more}\nInget importeras automatiskt.",
                    self._tray_icon.MessageIcon.Information, 8000)
            else:
                self.statusBar().showMessage(f"Ny importfil hittad: {names}{more}", 8000)
        except Exception as exc:
            _log.warning("Bevakad mapp kunde inte kontrolleras: %s", exc)

    def _confirm_startup_health(self) -> None:
        try:
            from core.startup_health import confirm_healthy
            if confirm_healthy(self._root()):
                _log.info("Starten bekräftad efter uppdatering")
        except Exception as exc:
            _log.warning("Startbekräftelsen kunde inte sparas: %s", exc)

    def moveEvent(self, event) -> None:
        """Kom ihåg fönstrets placering, men spara inte vid varje pixel."""
        super().moveEvent(event)
        self._schedule_geometry_save()

    def _schedule_geometry_save(self) -> None:
        """Spara fönstrets geometri en kort stund efter sista ändringen."""
        timer = getattr(self, "_geometry_timer", None)
        if timer is None:
            self._geometry_timer = QTimer(self)
            self._geometry_timer.setSingleShot(True)
            self._geometry_timer.setInterval(700)
            self._geometry_timer.timeout.connect(self._save_geometry)
            timer = self._geometry_timer
        timer.start()

    def _save_geometry(self) -> None:
        """Spara storlek och placering för den skärm fönstret ligger på."""
        try:
            screen = self.screen()
            if screen is None or self.isMinimized():
                return
            geometry = self.geometry()
            available = screen.availableGeometry()
            layout_memory.save_screen_geometry(
                self._root(), screen.name(),
                width=geometry.width(), height=geometry.height(),
                x=geometry.x() - available.x(), y=geometry.y() - available.y(),
                maximized=self.isMaximized(),
                used=datetime.now().isoformat(timespec="seconds"))
        except Exception:
            _log.debug("Fönstrets placering kunde inte sparas", exc_info=True)

    def resizeEvent(self, event) -> None:
        """Anpassa sidomenyn när fönstret ändrar bredd.

        Layouten ska alltid passa: på en smal bärbar datorskärm blir menyn
        smalare så att tabeller och formulär får plats, på en bred skärm får
        menyn mer luft. Ingenting göms och inget kräver rullning i sidled.
        """
        super().resizeEvent(event)
        self._fit_sidebar_to_window()
        self._schedule_geometry_save()

    def _fit_sidebar_to_window(self) -> None:
        """Anpassa sidomenyn efter fönstrets bredd och vald densitet.

        På smala skärmar visas bara ikoner (med sidnamnet som verktygstips), så
        att innehållet får plats utan att något göms. Breda skärmar behåller
        ikon + text.
        """
        sidebar = getattr(self, "sidebar", None)
        if sidebar is None:
            return
        icon_only = design.icon_only_sidebar(self.width())
        user_width = getattr(self, "_sidebar_user_width", 0) or 0
        if icon_only:
            width = design.design_icon_width()
        elif user_width:
            # Användaren har dragit i kanten – behåll den bredden.
            width = max(design.SIDEBAR_MIN_WIDTH,
                        min(design.sidebar_max_width(self.width()), int(user_width)))
        else:
            width = design.sidebar_width(self.width())
        # Automatisk densitet följer fönstret; ett eget val rörs inte.
        if self._density_mode() == "auto":
            density = design.resolve_density("auto", self.width(), self.height())
            if density != getattr(self, "_density", density):
                self._appearance_changed()
                return
        if (width == getattr(self, "window_config", WindowConfig()).sidebar_width
                and icon_only == getattr(self, "_icon_only_sidebar", None)):
            return
        try:
            self._icon_only_sidebar = icon_only
            self.window_config.sidebar_width = width
            # Delaren äger bredden: här sätts bara gränserna, så att den aldrig
            # kan bli smalare än ikonerna eller ta mer än en tredjedel.
            sidebar.setMinimumWidth(design.SIDEBAR_MIN_WIDTH)
            sidebar.setMaximumWidth(design.sidebar_max_width(self.width()))
            splitter = getattr(self, "main_splitter", None)
            if splitter is not None:
                sizes = splitter.sizes()
                if sizes:
                    sizes[0] = width
                    splitter.setSizes(sizes)
            layout = getattr(self, "sidebar_layout", None)
            if layout is not None:
                margin = 4 if icon_only else (6 if width < 200 else 10)
                layout.setContentsMargins(margin, 18, margin, 18)
            self._apply_nav_icon_mode(icon_only)
        except Exception:
            _log.debug("Sidomenyn kunde inte anpassas till fönsterbredden", exc_info=True)

    def _on_sidebar_resized(self, position: int, _index: int) -> None:
        """Användaren har dragit i sidomenyns kant – kom ihåg bredden."""
        try:
            width = int(position)
        except (TypeError, ValueError):
            return
        if width < design.SIDEBAR_MIN_WIDTH:
            return
        self._sidebar_user_width = width
        self._pending_sidebar_width = width
        timer = getattr(self, "_sidebar_save_timer", None)
        if timer is None:
            self._sidebar_save_timer = QTimer(self)
            self._sidebar_save_timer.setSingleShot(True)
            self._sidebar_save_timer.setInterval(800)
            self._sidebar_save_timer.timeout.connect(self._save_sidebar_width)
            timer = self._sidebar_save_timer
        timer.start()
        self._apply_nav_icon_mode(design.icon_only_sidebar(width))

    def _save_sidebar_width(self) -> None:
        """Spara den bredd användaren valt, så den gäller nästa gång."""
        width = getattr(self, "_pending_sidebar_width", None)
        if not width:
            return
        try:
            set_config_value_safe(self.app, "ui.sidebar_width", int(width))
            _log.info("Sidomenyns bredd sparad: %d px", int(width))
        except Exception:
            _log.debug("Sidomenyns bredd kunde inte sparas", exc_info=True)

    def _apply_nav_icon_mode(self, icon_only: bool) -> None:
        """Visa bara ikoner i sidomenyn, eller ikon med text."""
        group = getattr(self, "nav_group", None)
        if group is None or not getattr(self, "pages", None):
            return
        for index, (page_name, _widget) in enumerate(self.pages):
            button = group.button(index)
            if button is None:
                continue
            label = design.strip_emoji_prefix(page_name)
            button.setText("" if icon_only else label)
            # Ikonen centreras när texten är borta, annars linjerar den snett.
            button.setStyleSheet("text-align: center;" if icon_only else "")
            button.setToolTip(label)
            design.set_accessible(button, design.label_for_icon_button(label), f"Öppna {label}")

    def hideEvent(self, event) -> None:
        """När fönstret döljs går programmet ner i sparläge direkt."""
        super().hideEvent(event)
        QTimer.singleShot(0, self._apply_timer_policy)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Resten av sidorna skapas först när fönstret visas, i en enda omgång
        # efter den första ritningen – starten blir kortare och minnet mindre
        # för de sidor som aldrig öppnas.
        if not getattr(self, "_deferred_pages_ready", True):
            QTimer.singleShot(0, self._init_remaining_pages)
        # Startar alltid minimerat: syns fönstret ändå under startfasen
        # minimeras det direkt, så att ingen ruta hinner bli störande.
        if self._startup_phase:
            self._startup_phase = False
            if not self.isMinimized():
                self.showMinimized()
                if self._can_hide_to_tray():
                    self.hide()
                return
        # Panelen visas först när fönstret faktiskt öppnas, så att starten
        # aldrig stör.
        if self._dashboard_pending and self.isVisible() and not self.isMinimized():
            self._dashboard_pending = False
            QTimer.singleShot(400, self._show_dashboard)

    def closeEvent(self, event) -> None:
        if not self._quit_requested and self._can_hide_to_tray():
            event.ignore()
            self.hide()
            return
        page = self.vehicle_data_page
        if page is not None and hasattr(page, "confirm_close"):
            if not page.confirm_close():
                event.ignore()
                return
        super().closeEvent(event)
        if event.isAccepted() and self._tray_icon is not None:
            self._tray_icon.hide()

    # ──────────────────────────────────────────────────────────────────────────
    # Navigation & Updates

    # ──────────────────────────────────────────────────────────────────────────

    def _navigate_to_page(self, index: int) -> None:
        """Navigera till en sida."""
        self.stack.setCurrentIndex(index)
        # Refresh vid navigering
        widget = self.stack.widget(index)
        if widget and hasattr(widget, "refresh"):
            try:
                widget.refresh()
            except Exception:
                pass

    def refresh_all(self) -> None:
        """Uppdatera all data."""
        try:
            # Invalidera schema-cache
            self._invalidate_schema_cache()
            # Uppdatera VehicleDataPage
            if self.vehicle_data_page:
                for method_name in ("on_ts_spec_changed", "on_schema_changed", "refresh"):
                    if hasattr(self.vehicle_data_page, method_name):
                        try:
                            getattr(self.vehicle_data_page, method_name)()
                            break
                        except Exception:
                            pass
            # Refresh alla widgets
            for _, widget in self.pages:
                for method_name in ("refresh", "on_schema_changed"):
                    if hasattr(widget, method_name):
                        try:
                            getattr(widget, method_name)()
                            break
                        except Exception:
                            pass
            # Uppdatera statistik
            self._update_statistics()
            self._update_schema_status()
            _log.info("Refreshed all pages")
        except Exception as e:
            _log.error("Could not refresh all pages: %s", e)

    def _invalidate_schema_cache(self) -> None:
        """Invalidera schema-cache i alla relevanta plugins."""
        plugin_names = [
            "identity_post",
            "vehicle_registration_post",
            "end_post",
            "ts_file_generator",
            "data_mapping",
            "buntpost",
        ]
        for plugin_name in plugin_names:
            plugin = get_plugin_safe(self.app, plugin_name)
            if plugin:
                for method_name in ("invalidate_schema_cache", "reload_schema"):
                    if hasattr(plugin, method_name):
                        try:
                            getattr(plugin, method_name)()
                            _log.debug("Invalidated cache in %s", plugin_name)
                            break
                        except Exception as e:
                            _log.debug("Could not invalidate %s: %s", plugin_name, e)

    def on_schema_changed(self, data: Dict[str, Any]) -> None:
        """Hantera när schema ändrats."""
        version = data.get("version") or data.get("active_version") or data.get("new_version")
        _log.info("Schema changed: %s", version)
        self.refresh_all()

    def _update_schema_status(self) -> None:
        """Uppdatera schema-status i sidebar."""
        try:
            schema_info = get_schema_info_safe(self.app)
            from core.ts_safety import generation_block_reason
            colors = design.palette(getattr(self, "_theme", "dark"))
            if generation_block_reason():
                schema_text = f"Schema: {schema_info.version}" if schema_info.is_active else "Ingen version aktiv"
                self.schema_status.setText(f"TS-generering spärrad\n{schema_text}")
                self.schema_status.setStyleSheet(f"color: {colors['warning']};")
            elif schema_info.is_active:
                post_types_str = ", ".join(schema_info.post_types)
                self.schema_status.setText(
                    f"{schema_info.version}\n{post_types_str or f'{schema_info.post_count} posttyper'}"
                )
                self.schema_status.setStyleSheet(f"color: {colors['success']};")
            else:
                self.schema_status.setText("Ingen version aktiv\nImportera TS-spec")
                self.schema_status.setStyleSheet(f"color: {colors['warning']};")
        except Exception as e:
            self.schema_status.setText(f"Fel: {str(e)[:20]}")
            self.schema_status.setStyleSheet(f"color: {design.palette(getattr(self, '_theme', 'dark'))['danger']};")
        # Ny uppdatering – men i dolt läge bara en bråkdel så ofta, så att
        # programmet inte arbetar i bakgrunden (energi och minne).
        QTimer.singleShot(self._next_interval(STATS_UPDATE_INTERVAL_MS), self._update_schema_status)

    def _update_statistics(self) -> None:
        """Uppdatera statistik i sidebar."""
        try:
            stats = self._get_vehicle_statistics()
            self.stats_info.setText(
                f"Fordon: {stats.total}\n"
                f"År: {stats.years_count}\n"
                f"Reg VIN: {stats.registered_total}"
            )
        except Exception as e:
            self.stats_info.setText(f"Fel: {str(e)[:20]}")
        QTimer.singleShot(self._next_interval(STATS_UPDATE_INTERVAL_MS), self._update_statistics)

    def _get_vehicle_statistics(self) -> VehicleStatistics:
        """Hämta fordonsstatistik."""
        vehicle_plugin = get_plugin_safe(self.app, "vehicle_registry")
        if not vehicle_plugin or not hasattr(vehicle_plugin, "get_statistics"):
            return VehicleStatistics()
        try:
            stats = vehicle_plugin.get_statistics()
            vehicles_stats = stats.get("vehicles", {})
            reg_stats = stats.get("registered", {})
            return VehicleStatistics(
                total=vehicles_stats.get("total", 0),
                years_count=len(vehicles_stats.get("years", [])),
                registered_total=reg_stats.get("total", 0),
                registered_this_year=reg_stats.get("this_year", 0),
                registered_this_month=reg_stats.get("this_month", 0),
            )
        except Exception:
            return VehicleStatistics()

    # ──────────────────────────────────────────────────────────────────────────
    # Menu Actions - SCHEMA

    # ──────────────────────────────────────────────────────────────────────────

    def _import_ts_schema_dialog(self) -> None:
        """Importera en orörd underlagskopia; aktivera aldrig ett overifierat schema."""
        filepath, _ = QFileDialog.getOpenFileName(self, "Importera TS-underlag från Excel", "",
                                                  "Excel-filer (*.xlsx *.xlsm *.xls)")
        if not filepath:
            return
        try:
            from core.ts_source_import import import_source
            root = Path(get_config_value_safe(self.app, "base_dir", ".") or ".")
            result = import_source(Path(filepath), root / "data" / "ts_spec_underlag")
            show_info(self, "Underlag importerat – ej verifierat",
                "En oförändrad kopia har sparats för granskning. Inget TS-schema har aktiverats.\n\n"
                + "Blad: " + ", ".join(result['sheets']) + "\n\n"
                + "TS-generering är fortfarande spärrad tills hela underlaget har kontrollerats.")
        except Exception as exc:
            _log.warning("TS-underlag kunde inte importeras: %s", exc)
            show_error(self, "Import misslyckades", str(exc))

    def _change_schema_version(self, version: str) -> None:
        """Byt aktiv schema-version."""
        if not version:
            return
        # Försök ts_schema_manager
        schema_mgr = get_plugin_safe(self.app, "ts_schema_manager")
        if schema_mgr and hasattr(schema_mgr, "set_active_version"):
            try:
                if schema_mgr.set_active_version(version):
                    show_info(self, "Version ändrad", f"Aktiv version är nu: {version}")
                    self.refresh_all()
                    return
            except Exception as e:
                _log.error("Failed to change version: %s", e)
        # Fallback till ts_spec_import
        ts_spec = get_plugin_safe(self.app, "ts_spec_import")
        if ts_spec and hasattr(ts_spec, "set_active_version"):
            try:
                ts_spec.set_active_version(version)
                show_info(self, "Version ändrad", f"Aktiv version är nu: {version}")
                self.refresh_all()
                return
            except Exception as e:
                _log.error("Failed to change version via ts_spec_import: %s", e)
        show_error(self, "Fel", f"Kunde inte byta till version '{version}'")

    def _change_version_dialog(self) -> None:
        """Dialog för att byta schema-version."""
        schema_info = get_schema_info_safe(self.app)
        if not schema_info.versions:
            show_info(
                self,
                "Inga versioner",
                "Inga TS-schema versioner finns sparade.\n\n"
                "Importera en TS-spec från Excel först.",
            )
            return
        current_index = 0
        if schema_info.version and schema_info.version in schema_info.versions:
            current_index = schema_info.versions.index(schema_info.version)
        version, ok = QInputDialog.getItem(
            self,
            "Byt schema-version",
            "Välj version:",
            schema_info.versions,
            current_index,
            False,
        )
        if ok and version:
            self._change_schema_version(version)

    def _show_schema_info(self) -> None:
        """Visa detaljerad schema-info."""
        schema_info = get_schema_info_safe(self.app)
        msg = (
            f"📋 TS SCHEMA-INFORMATION\n\n"
            f"Aktiv version: {schema_info.version or 'Ingen'}\n\n"
            f"Posttyper:\n"
            + (
                "\n".join(f"  • {pt}" for pt in schema_info.post_types)
                if schema_info.post_types
                else "  Inga posttyper laddade"
            )
            + "\n\n"
            f"Tillgängliga versioner: {', '.join(schema_info.versions) if schema_info.versions else 'Inga'}"
        )
        show_info(self, "Schema-information", msg)

    def _compare_versions_dialog(self) -> None:
        """Dialog för att jämföra schema-versioner."""
        schema_info = get_schema_info_safe(self.app)
        if len(schema_info.versions) < 2:
            show_info(
                self,
                "För få versioner",
                "Minst två versioner krävs för jämförelse.\n\n"
                "Importera fler TS-spec versioner först.",
            )
            return
        # Välj versioner
        v1, ok1 = QInputDialog.getItem(
            self, "Jämför versioner", "Första version:", schema_info.versions, 0, False
        )
        if not ok1:
            return
        v2, ok2 = QInputDialog.getItem(
            self, "Jämför versioner", "Andra version:", schema_info.versions, 1, False
        )
        if not ok2:
            return
        # Hitta compare-funktion
        compare_func = None
        schema_mgr = get_plugin_safe(self.app, "ts_schema_manager")
        if schema_mgr and hasattr(schema_mgr, "compare_versions"):
            compare_func = schema_mgr.compare_versions
        else:
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if ts_spec and hasattr(ts_spec, "compare_versions"):
                compare_func = ts_spec.compare_versions
        if not compare_func:
            show_warning(
                self,
                "Ej tillgängligt",
                "Versionsjämförelse är inte tillgänglig.",
            )
            return
        try:
            diff = compare_func(v1, v2)
            msg = f"📊 JÄMFÖRELSE: {v1} ↔ {v2}\n\n"
            added = diff.get("added", [])
            removed = diff.get("removed", [])
            modified = diff.get("modified", [])
            if added:
                msg += f"✅ Tillagda: {', '.join(str(x) for x in added)}\n"
            if removed:
                msg += f"❌ Borttagna: {', '.join(str(x) for x in removed)}\n"
            if modified:
                msg += f"🔄 Ändrade: {', '.join(str(x) for x in modified)}\n"
            if not any([added, removed, modified]):
                msg += "✓ Inga skillnader hittades"
            if diff.get("error"):
                msg += f"\n\n⚠️ {diff['error']}"
            show_info(self, "Versionsjämförelse", msg)
        except Exception as e:
            show_error(self, "Fel", f"Kunde inte jämföra versioner:\n\n{e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Menu Actions - ARKIV

    # ──────────────────────────────────────────────────────────────────────────

    def _export_vehicle_data(self) -> None:
        """Exportera fordonsdata."""
        vehicle_plugin = get_plugin_safe(self.app, "vehicle_registry")
        if not vehicle_plugin:
            show_warning(
                self,
                "Plugin saknas",
                "vehicle_registry plugin är inte tillgänglig",
            )
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Exportera fordonsdata",
            f"fordonsdata_export_{datetime.now().strftime('%Y%m%d')}.xlsx",
            "Excel-filer (*.xlsx);;JSON-filer (*.json)",
        )
        if not filepath:
            return
        try:
            is_json = filepath.endswith(".json")
            export_method = "export_to_json" if is_json else "export_to_excel"
            if not hasattr(vehicle_plugin, export_method):
                show_warning(
                    self,
                    "Ej stött",
                    f"{'JSON' if is_json else 'Excel'}-export stöds inte",
                )
                return
            success = getattr(vehicle_plugin, export_method)(Path(filepath))
            if success:
                show_info(
                    self,
                    "Export klar",
                    f"Fordonsdata exporterad till:\n{filepath}",
                )
            else:
                show_error(self, "Export misslyckades", "Kunde inte exportera data.")
        except Exception as e:
            _log.error("Export failed: %s", e, exc_info=True)
            show_error(self, "Export fel", f"Fel vid export:\n\n{e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Menu Actions - INSTÄLLNINGAR

    # ──────────────────────────────────────────────────────────────────────────

    def _change_password(self) -> None:
        """Byt huvudlösenord."""
        config = get_plugin_safe(self.app, "core_config")
        if not config:
            show_warning(self, "Fel", "core_config plugin saknas")
            return
        # Verifiera nuvarande lösenord
        current_pin = self._get_pin_from_config(config)
        old_pin, ok = QInputDialog.getText(
            self,
            "Säkerhet",
            "Ange nuvarande lösenord:",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        if old_pin != current_pin:
            show_error(self, "Fel", "Felaktigt lösenord!")
            return
        # Ange nytt lösenord
        new_pin, ok = QInputDialog.getText(
            self,
            "Nytt Lösenord",
            f"Ange nytt lösenord (minst {MIN_PIN_LENGTH} tecken):",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not new_pin:
            return
        if len(new_pin) < MIN_PIN_LENGTH:
            show_error(
                self,
                "För kort",
                f"Lösenordet måste vara minst {MIN_PIN_LENGTH} tecken.",
            )
            return
        # Bekräfta nytt lösenord
        confirm_pin, ok = QInputDialog.getText(
            self,
            "Bekräfta Lösenord",
            "Bekräfta nytt lösenord:",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        if new_pin != confirm_pin:
            show_error(self, "Fel", "Lösenorden matchar inte!")
            return
        # Spara nytt lösenord
        if hasattr(config, "set_pin"):
            config.set_pin(new_pin)
        elif set_config_value_safe(self.app, "pin", new_pin):
            pass
        else:
            show_error(self, "Fel", "Kunde inte spara lösenord")
            return
        show_info(self, "Klart", "Lösenordet har uppdaterats.")

    def _change_vehicle_pin(self) -> None:
        """Ändra PIN för fordonsdata."""
        config = get_plugin_safe(self.app, "core_config")
        if not config:
            show_warning(self, "Fel", "core_config plugin saknas")
            return
        # Verifiera huvudlösenord
        current_pin = self._get_pin_from_config(config)
        main_pin, ok = QInputDialog.getText(
            self,
            "Säkerhet",
            "Ange huvudlösenord:",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        if main_pin != current_pin:
            show_error(self, "Fel", "Felaktigt lösenord!")
            return
        # Ange ny fordonsdata-PIN
        new_pin, ok = QInputDialog.getText(
            self,
            "Fordonsdata PIN",
            "Ange ny PIN för fordonsdata\n(lämna tomt för att använda huvudlösenord):",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        if new_pin and len(new_pin) < MIN_PIN_LENGTH:
            show_error(
                self,
                "För kort",
                f"PIN måste vara minst {MIN_PIN_LENGTH} tecken.",
            )
            return
        # Spara
        if new_pin:
            set_config_value_safe(self.app, "vehicle_data_pin", new_pin)
            show_info(self, "Klart", "Fordonsdata-PIN uppdaterad.")
        else:
            set_config_value_safe(self.app, "vehicle_data_pin", None)
            show_info(self, "Klart", "Fordonsdata använder nu huvudlösenordet.")

    def _manage_file_id(self) -> None:
        """Hantera FilID-serie."""
        config = get_plugin_safe(self.app, "core_config")
        if not config:
            show_warning(self, "Fel", "core_config plugin saknas")
            return
        # Hämta aktuell info
        info: Dict[str, Any] = {}
        if hasattr(config, "get_file_id_info"):
            info = config.get_file_id_info()
        current_prefix = info.get("prefix", "BLN")
        current_number = info.get("current_number", 1)
        # Dialog för prefix
        prefix, ok = QInputDialog.getText(
            self,
            "FilID Prefix",
            "Prefix (max 6 tecken):",
            text=current_prefix,
        )
        if not ok:
            return
        prefix = prefix.upper().strip()[:6]
        if not prefix:
            show_error(self, "Fel", "Prefix kan inte vara tomt")
            return
        # Dialog för startnummer
        num, ok = QInputDialog.getInt(
            self,
            "FilID Nummer",
            "Startnummer:",
            value=current_number,
            min=1,
            max=9999,
        )
        if not ok:
            return
        # Spara
        if hasattr(config, "set_file_id_prefix"):
            config.set_file_id_prefix(prefix)
        if hasattr(config, "reset_file_id_series"):
            config.reset_file_id_series(num)
        # Uppdatera data_mapping om tillgänglig
        data_mapping = get_plugin_safe(self.app, "data_mapping")
        if data_mapping and hasattr(data_mapping, "refresh_file_id_info"):
            try:
                data_mapping.refresh_file_id_info()
            except Exception:
                pass
        show_info(self, "Klart", f"FilID uppdaterad: {prefix}{num:04d}")

    # ──────────────────────────────────────────────────────────────────────────
    # Menu Actions - VERKTYG

    # ──────────────────────────────────────────────────────────────────────────

    def _validate_vin_dialog(self) -> None:
        """Dialog för att validera VIN."""
        vin, ok = QInputDialog.getText(
            self,
            "Validera VIN",
            "Ange VIN-nummer (17 tecken):",
        )
        if not ok or not vin:
            return
        vehicle_plugin = get_plugin_safe(self.app, "vehicle_registry")
        if not vehicle_plugin:
            show_warning(
                self,
                "Plugin saknas",
                "vehicle_registry plugin är inte tillgänglig",
            )
            return
        # Använd plugin-validering om tillgänglig
        if hasattr(vehicle_plugin, "validate_vin"):
            try:
                result = vehicle_plugin.validate_vin(vin)
                if result.get("valid"):
                    msg = (
                        f"✅ VIN är giltigt!\n\n"
                        f"VIN: {result.get('vin', vin)}\n"
                        f"VIN3-kod: {result.get('vin3', 'N/A')}\n"
                        f"Land: {result.get('country', 'Okänt')}\n"
                        f"Årsmodell: {result.get('year_code', 'N/A')}"
                    )
                    show_info(self, "VIN Validerat", msg)
                else:
                    show_error(
                        self,
                        "Ogiltigt VIN",
                        f"❌ VIN är ogiltigt!\n\n{result.get('error', 'Okänt fel')}",
                    )
                return
            except Exception as e:
                _log.error("VIN validation failed: %s", e)
        # Enkel validering
        if len(vin) == 17 and vin.isalnum():
            show_info(self, "VIN Format OK", f"VIN '{vin}' har korrekt format (17 tecken)")
        else:
            show_warning(self, "VIN Format Fel", "VIN måste vara exakt 17 alfanumeriska tecken")

    def _show_statistics(self) -> None:
        """Visa detaljerad statistikdialog."""
        stats = self._get_vehicle_statistics()
        schema_info = get_schema_info_safe(self.app)
        msg = (
            f"📊 STATISTIK\n\n"
            f"Fordonsdata:\n"
            f"  • Totalt: {stats.total} fordon\n"
            f"  • År: {stats.years_count}\n\n"
            f"Registrerade VIN:\n"
            f"  • Totalt: {stats.registered_total}\n"
            f"  • I år: {stats.registered_this_year}\n"
            f"  • Denna månad: {stats.registered_this_month}\n\n"
            f"TS Schema:\n"
            f"  • Aktiv version: {schema_info.version or 'Ingen'}\n"
            f"  • Posttyper: {schema_info.post_count}\n"
            f"  • Versioner: {len(schema_info.versions)}\n"
        )
        show_info(self, "Statistik", msg)

    def _refresh_cache(self) -> None:
        """Uppdatera all cache."""
        vehicle_plugin = get_plugin_safe(self.app, "vehicle_registry")
        # Invalidera vehicle cache
        if vehicle_plugin:
            for attr_name in ("vin_registry", "vehicle_cache"):
                obj = getattr(vehicle_plugin, attr_name, None)
                if obj:
                    for method_name in ("invalidate_cache", "invalidate"):
                        if hasattr(obj, method_name):
                            try:
                                getattr(obj, method_name)()
                                _log.debug("Invalidated %s", attr_name)
                                break
                            except Exception:
                                pass
        # Invalidera schema-cache
        self._invalidate_schema_cache()
        # Emit event
        emit_event_safe(self.app, "cache:invalidated", {})
        show_info(self, "Cache uppdaterad", "All cache har rensats och uppdaterats.")

    def _rebuild_index(self) -> None:
        """Bygg om VIN3-index."""
        vehicle_plugin = get_plugin_safe(self.app, "vehicle_registry")
        if not vehicle_plugin or not hasattr(vehicle_plugin, "rebuild_index"):
            show_warning(
                self,
                "Ej tillgängligt",
                "Indexfunktionen är inte tillgänglig",
            )
            return
        if not ask_yes_no(
            self,
            "Bygg om index",
            "Detta kommer att scanna alla JSON-filer och bygga om VIN3-indexet.\n\nFortsätta?",
        ):
            return
        try:
            count = vehicle_plugin.rebuild_index()
            show_info(
                self,
                "Index ombyggt",
                f"VIN3-index ombyggt!\n\n{count} VIN3-koder indexerade.",
            )
        except Exception as e:
            _log.error("Index rebuild failed: %s", e, exc_info=True)
            show_error(self, "Fel", f"Kunde inte bygga om index:\n\n{e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Menu Actions - HJÄLP

    # ──────────────────────────────────────────────────────────────────────────

    def _show_manual(self) -> None:
        """Visa manual."""
        show_info(self, "Manual", MANUAL_TEXT)

    def _show_about(self) -> None:
        """Visa om-dialog."""
        app_name = get_config_value_safe(self.app, "app_name", "Fordonsreg")
        app_version = get_config_value_safe(self.app, "app_version", __version__)
        app_author = get_config_value_safe(self.app, "app_author", "Rickard Längkvist")
        vehicle_plugin = get_plugin_safe(self.app, "vehicle_registry")
        vehicle_version = getattr(vehicle_plugin, "VERSION", "N/A") if vehicle_plugin else "N/A"
        schema_mgr = get_plugin_safe(self.app, "ts_schema_manager")
        schema_version = getattr(schema_mgr, "VERSION", "N/A") if schema_mgr else "N/A"
        QMessageBox.about(
            self,
            "Om",
            f"{app_name} v{app_version}\n\n"
            f"Fordonsregistrering för Transportstyrelsen\n\n"
            f"Main GUI: v{__version__}\n"
            f"Vehicle Registry: v{vehicle_version}\n"
            f"TS Schema Manager: v{schema_version}\n\n"
            f"© Copyright {app_author} {datetime.now().year}",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers

    # ──────────────────────────────────────────────────────────────────────────

    def _get_pin_getter(self) -> Callable:
        """Begär gemensam PIN; äldre fordons-PIN verifieras vid övergång."""
        def request(parent):
            import hmac
            from plugins.main_gui.dialogs.dealer_pin import request_migrated_pin
            config = get_plugin_safe(self.app, "core_config")
            dealer = get_plugin_safe(self.app, "dealers_manager") or getattr(self.app, "dealers", None)
            if config is None or dealer is None:
                show_error(parent, "PIN-skydd", "PIN-hanteraren eller tidigare inställningar är inte tillgängliga.")
                return None
            def identity_now():
                value = get_config_value_safe(self.app, "vehicle_data_pin", None) or self._get_pin_from_config(config)
                if not isinstance(value, str) or not value:
                    raise ValueError("Den tidigare fordons-PIN-koden kan inte läsas")
                return value
            return request_migrated_pin(parent, dealer, "fordonsdata", identity_now,
                lambda old: isinstance(old, str) and hmac.compare_digest(old, identity_now()), "Fordonsdata")
        return request

    def _get_pin_from_config(self, config: Any) -> str:
        """Hämta PIN från config-plugin."""
        if not config:
            return "1234"
        for method_name in ("get_pin", "get_config_value", "get"):
            if hasattr(config, method_name):
                try:
                    if method_name == "get_pin":
                        result = config.get_pin()
                    elif method_name == "get_config_value":
                        result = config.get_config_value("pin", "1234")
                    else:
                        result = config.get("pin", "1234")
                    if result:
                        return result
                except Exception:
                    pass
        return "1234"

    def _auto_load_dispatch(self) -> None:
        """Auto-ladda senaste dispatch-fil."""
        dispatch_dir = Path(get_config_value_safe(self.app, "dispatch_dir", "dispatch"))
        if not dispatch_dir.exists():
            return
        files = sorted(
            list(dispatch_dir.glob("*.xlsx")) + list(dispatch_dir.glob("*.xls")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return
        latest = files[0]
        file_age = datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)
        if file_age > timedelta(hours=AUTOLOAD_MAX_AGE_HOURS):
            return
        if not ask_yes_no(
            self,
            "Dispatch-fil hittad",
            f"Hittade ny fil:\n{latest.name}\n\nVill du importera den?",
        ):
            return
        # Navigera till Dispatch-sidan
        for i, (page_name, _) in enumerate(self.pages):
            if "Dispatch" in page_name:
                self.stack.setCurrentIndex(i)
                btn = self.nav_group.button(i)
                if btn:
                    btn.setChecked(True)
                break
        # Ladda filen
        dispatch_plugin = get_plugin_safe(self.app, "dispatch_viewer")
        if dispatch_plugin and hasattr(dispatch_plugin, "load_file"):
            try:
                dispatch_plugin.load_file(str(latest))
            except Exception as e:
                _log.warning("Could not load dispatch: %s", e)

# ══════════════════════════════════════════════════════════════════════════════
# STYLESHEETS

# ══════════════════════════════════════════════════════════════════════════════
# Stilarken byggs numera av core/theme.py så att mörkt och ljust tema har
# samma mått och färger överallt. Konstanterna finns kvar som exporterade
# standardvärden (mörkt tema) för kod som importerar dem direkt.
MAIN_STYLESHEET: Final[str] = design.stylesheet("dark")
SIDEBAR_BUTTON_STYLE: Final[str] = ""  # Sidomenyns knappar styrs av #NavButton
MENUBAR_STYLE: Final[str] = design.menubar_stylesheet("dark")

MANUAL_TEXT: Final[str] = """📖 SNABBGUIDE
1. Fordonsdata: Hantera fordonsspecifikationer per år
2. TS Schema: Importera och hantera TS-specifikationer
3. Data Viewer: Visa/importera modellregister
4. Återförsäljare: Hantera återförsäljarregister
5. Färger: Hantera färgkoder
6. Dispatch: Importera från dispatch-fil
7. Generera TS-fil: Skapa fil för Transportstyrelsen
8. Rapporter: Visa historik och generera rapporter
Tips:
• Schema → Importera TS-spec: Ladda ny postbeskrivning från Excel
• Schema → Byt version: Växla mellan olika TS-spec versioner
• Ctrl+F: Sök efter VIN (i Fordonsdata)
• Verktyg → Validera VIN: Snabbvalidering
• Verktyg → Uppdatera cache: Rensa cache vid problem
"""

# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS

# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Main classes
    "Plugin",
    "MainWindow",
    # Enums
    "SchemaEvent",
    "MessageIcon",
    # Dataclasses
    "WindowConfig",
    "SchemaInfo",
    "PageInfo",
    "VehicleStatistics",
    # Helpers
    "get_plugin_safe",
    "get_schema_info_safe",
    "get_event_bus",
    "emit_event_safe",
    "subscribe_event_safe",
    "unsubscribe_event_safe",
    "get_config_value_safe",
    "set_config_value_safe",
    # Dialogs
    "show_message",
    "show_info",
    "show_warning",
    "show_error",
    "ask_yes_no",
    # Version
    "__version__",
]
