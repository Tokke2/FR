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
  - OBSERVATION (EJ ändrad, inväntar beslut): activate() anropar
    sys.exit(self._qapp.exec()) — SystemExit avslutar processen när
    fönstret stängs och main.py:s start()-sekvens (app:started-emit,
    exit_code) körs aldrig klart. Rekommendation: main.py äger
    QApplication.exec() och activate() skapar endast fönstret; eller
    sys.exit tas bort (exec utan exit). Kräver beslut + runtime-test.

FÖRÄNDRINGAR v6.0.2 (Session 10 — spec v1.4):
  - Hela filen omskriven REN: markdown-artefakter borttagna
    ([url]-länkar, **-markeringar, *x*-mönster, &gt;/&lt;/&amp; osv.).
  - logger -> _log (spec-konvention: module-level _log, ej logger/self.logger).
  - BUGG #5: "TADEGA AB" bort. app_author-default = "Rickard Längkvist";
    setApplicationName via config app_name (default
    "Transportstyrelsen Fordonsregistreringssystem").
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
from PySide6.QtCore import QTimer, Qt, Signal
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
        # Skapa QApplication
        if QApplication.instance() is None:
            self._qapp = QApplication(sys.argv)
            self._qapp.setApplicationName(
                get_config_value_safe(
                    self.app,
                    "app_name",
                    "Transportstyrelsen Fordonsregistreringssystem",
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
            self._main_window.show()
            # Kör event loop om vi inte redan kör
            if self._qapp and not self._qapp.startingUp():
                sys.exit(self._qapp.exec())
        except Exception as e:
            _log.error("Failed to activate Main GUI: %s", e, exc_info=True)
            raise

    def deactivate(self) -> None:
        """Deaktivera plugin."""
        # Avregistrera events
        for event_name, handler in self._event_handlers:
            unsubscribe_event_safe(self.app, event_name, handler)
        self._event_handlers.clear()
        if self._main_window:
            self._main_window.close()
            self._main_window = None
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
        self.vehicle_data_page: Optional[QWidget] = None
        self.ts_schema_page: Optional[QWidget] = None
        # Config
        self.window_config = self._load_window_config()
        # Setup
        self._setup_window()
        self._apply_stylesheet()
        self._init_pages()
        self._init_navigation()
        self._init_menu()
        # Auto-load dispatch efter 500ms
        QTimer.singleShot(500, self._auto_load_dispatch)

    # ──────────────────────────────────────────────────────────────────────────
    # Setup

    # ──────────────────────────────────────────────────────────────────────────

    def _load_window_config(self) -> WindowConfig:
        """Ladda fönsterkonfiguration."""
        return WindowConfig(
            width=get_config_value_safe(self.app, "window_width", 1400),
            height=get_config_value_safe(self.app, "window_height", 900),
            sidebar_width=get_config_value_safe(self.app, "sidebar_width", 220),
        )

    def _setup_window(self) -> None:
        """Konfigurera fönster."""
        app_name = get_config_value_safe(self.app, "app_name", "Fordonsregistrering")
        app_version = get_config_value_safe(self.app, "app_version", __version__)
        self.setWindowTitle(f"{app_name} v{app_version}")
        self.resize(self.window_config.width, self.window_config.height)

    def _apply_stylesheet(self) -> None:
        """Applicera stylesheet."""
        self.setStyleSheet(MAIN_STYLESHEET)

    def _init_pages(self) -> None:
        """Initiera sidor från plugins."""
        self.pages: List[Tuple[str, QWidget]] = []
        self.page_widgets: Dict[str, QWidget] = {}
        # 1. Fordonsdata (prioritet 1)
        self._init_vehicle_data_page()
        # 2. TS Schema (ny i v5.0)
        self._init_ts_schema_page()
        # 3. Övriga sidor
        self._init_other_pages()
        _log.info("Initialized %d pages", len(self.pages))

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
        title = QLabel(f"⚠️ {page_name}")
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #ffc107;")
        layout.addWidget(title)
        msg = QLabel(f"Plugin ej tillgänglig: {reason}")
        msg.setStyleSheet("color: #ffc107; font-size: 14px;")
        layout.addWidget(msg)
        info = QLabel(
            "Kontrollera att plugin är installerad och aktiverad korrekt\n\n"
            "Tips: Starta om programmet eller kontakta administratör"
        )
        info.setStyleSheet("color: #888; font-size: 12px;")
        info.setWordWrap(True)
        layout.addWidget(info)
        return widget

    def _create_minimal_ts_schema_page(self) -> QWidget:
        """Skapa minimal TS Schema-sida."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        title = QLabel("📋 TS Schema-hantering")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        # Schema-info
        schema_info = get_schema_info_safe(self.app)
        info_box = QGroupBox("Aktiv version")
        info_layout = QFormLayout(info_box)
        version_label = QLabel(schema_info.version or "Ingen version aktiv")
        version_label.setStyleSheet(
            f"color: {'#28a745' if schema_info.is_active else '#ffc107'}; font-weight: bold;"
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
        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)
        # Stackwidget
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)
        # Lägg till alla sidor
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for i, (page_name, widget) in enumerate(self.pages):
            self.stack.addWidget(widget)
            btn = QPushButton(page_name)
            btn.setCheckable(True)
            btn.setStyleSheet(SIDEBAR_BUTTON_STYLE)
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
        # Starta timers
        QTimer.singleShot(1000, self._update_statistics)
        QTimer.singleShot(1000, self._update_schema_status)

    def _create_sidebar(self) -> QWidget:
        """Skapa sidebar."""
        sidebar = QWidget()
        sidebar.setFixedWidth(self.window_config.sidebar_width)
        sidebar.setStyleSheet("background: #14161a;")
        self.sidebar_layout = QVBoxLayout(sidebar)
        self.sidebar_layout.setContentsMargins(10, 20, 10, 20)
        # Logo
        app_name = get_config_value_safe(self.app, "app_name", "Fordonsregistrering")
        logo = QLabel(app_name)
        logo.setStyleSheet("font-size: 18px; font-weight: bold; color: #007bff;")
        self.sidebar_layout.addWidget(logo)
        self.sidebar_layout.addSpacing(20)
        return sidebar

    def _add_stats_labels(self) -> None:
        """Lägg till statistik-labels i sidebar."""
        # Schema-status
        schema_header = QLabel("📋 TS Schema")
        schema_header.setStyleSheet("color: #888; font-size: 12px; margin-top: 10px;")
        self.sidebar_layout.addWidget(schema_header)
        self.schema_status = QLabel("Laddar...")
        # BUGG #3 FIXAD: word-wrap borttagen från stylesheet
        # Använder setWordWrap(True) via Python istället
        self.schema_status.setStyleSheet("color: #aaa; font-size: 11px;")
        self.schema_status.setWordWrap(True)
        self.sidebar_layout.addWidget(self.schema_status)
        # Fordons-statistik
        stats_header = QLabel("📊 Statistik")
        stats_header.setStyleSheet("color: #888; font-size: 12px; margin-top: 10px;")
        self.sidebar_layout.addWidget(stats_header)
        self.stats_info = QLabel("Laddar...")
        # BUGG #3 FIXAD: word-wrap borttagen från stylesheet
        # Använder setWordWrap(True) via Python istället
        self.stats_info.setStyleSheet("color: #aaa; font-size: 11px;")
        self.stats_info.setWordWrap(True)
        self.sidebar_layout.addWidget(self.stats_info)

    def _init_menu(self) -> None:
        """Initiera menybar."""
        menubar = self.menuBar()
        menubar.setStyleSheet(MENUBAR_STYLE)
        # Menyer
        self._create_file_menu(menubar)
        self._create_schema_menu(menubar)
        self._create_settings_menu(menubar)
        self._create_tools_menu(menubar)
        self._create_help_menu(menubar)

    def _create_file_menu(self, menubar: QMenuBar) -> None:
        """Skapa Arkiv-meny."""
        file_menu = menubar.addMenu("Arkiv")
        file_menu.addAction("📤 Exportera fordonsdata...", self._export_vehicle_data)
        file_menu.addSeparator()
        file_menu.addAction("🚪 Avsluta", self.close)

    def _create_schema_menu(self, menubar: QMenuBar) -> None:
        """Skapa Schema-meny."""
        schema_menu = menubar.addMenu("Schema")
        schema_menu.addAction("📥 Importera TS-spec...", self._import_ts_schema_dialog)
        schema_menu.addAction("🔄 Byt version...", self._change_version_dialog)
        schema_menu.addSeparator()
        schema_menu.addAction("ℹ️ Visa schema-info...", self._show_schema_info)
        schema_menu.addAction("📊 Jämför versioner...", self._compare_versions_dialog)

    def _create_settings_menu(self, menubar: QMenuBar) -> None:
        """Skapa Inställningar-meny."""
        settings_menu = menubar.addMenu("Inställningar")
        settings_menu.addAction("🔐 Byt Lösenord...", self._change_password)
        settings_menu.addAction("🔢 Hantera FilID-serie...", self._manage_file_id)
        settings_menu.addSeparator()
        settings_menu.addAction("🚗 Fordonsdata PIN...", self._change_vehicle_pin)

    def _create_tools_menu(self, menubar: QMenuBar) -> None:
        """Skapa Verktyg-meny."""
        tools_menu = menubar.addMenu("Verktyg")
        tools_menu.addAction("🔍 Validera VIN...", self._validate_vin_dialog)
        tools_menu.addAction("📊 Visa statistik...", self._show_statistics)
        tools_menu.addSeparator()
        tools_menu.addAction("🔄 Uppdatera cache", self._refresh_cache)
        tools_menu.addAction("🔧 Bygg om index", self._rebuild_index)

    def _create_help_menu(self, menubar: QMenuBar) -> None:
        """Skapa Hjälp-meny."""
        help_menu = menubar.addMenu("Hjälp")
        help_menu.addAction("📖 Manual", self._show_manual)
        help_menu.addAction("ℹ️ Om programmet", self._show_about)

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
            if schema_info.is_active:
                post_types_str = ", ".join(schema_info.post_types)
                self.schema_status.setText(
                    f"✓ {schema_info.version}\n{post_types_str or f'{schema_info.post_count} posttyper'}"
                )
                self.schema_status.setStyleSheet("color: #28a745; font-size: 11px;")
            else:
                self.schema_status.setText("⚠ Ingen version aktiv\nImportera TS-spec")
                self.schema_status.setStyleSheet("color: #ffc107; font-size: 11px;")
        except Exception as e:
            self.schema_status.setText(f"❌ Fel: {str(e)[:20]}")
            self.schema_status.setStyleSheet("color: #dc3545; font-size: 11px;")
        # Uppdatera igen om 30 sekunder
        QTimer.singleShot(STATS_UPDATE_INTERVAL_MS, self._update_schema_status)

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
        # Uppdatera igen om 30 sekunder
        QTimer.singleShot(STATS_UPDATE_INTERVAL_MS, self._update_statistics)

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
        """Dialog för att importera TS-schema."""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Välj TS-spec Excel-fil",
            "",
            "Excel-filer (*.xlsx *.xls)",
        )
        if not filepath:
            return
        importer = get_plugin_safe(self.app, "ts_excel_importer")
        if not importer:
            show_error(
                self,
                "Plugin saknas",
                "ts_excel_importer är inte tillgänglig.\n\n"
                "Kontrollera att pluginen är installerad och aktiverad.",
            )
            return
        try:
            success = False
            if hasattr(importer, "import_from_excel"):
                success = importer.import_from_excel(Path(filepath))
            elif hasattr(importer, "parse_excel"):
                specs = importer.parse_excel(Path(filepath))
                if specs:
                    schema_mgr = get_plugin_safe(self.app, "ts_schema_manager")
                    if schema_mgr and hasattr(schema_mgr, "create_version"):
                        version_name = Path(filepath).stem
                        schema_mgr.create_version(
                            version=version_name,
                            specs=specs,
                            source_file=str(filepath),
                            set_active=True,
                        )
                        success = True
            if success:
                show_info(
                    self,
                    "Import klar",
                    f"TS-schema importerat från:\n{filepath}",
                )
                self.refresh_all()
            else:
                show_error(
                    self,
                    "Import misslyckades",
                    "Kunde inte importera schema.\n\n"
                    "Kontrollera att filen har rätt format.",
                )
        except Exception as e:
            _log.error("Failed to import TS schema: %s", e, exc_info=True)
            show_error(self, "Import fel", f"Fel vid import:\n\n{e}")

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
        app_name = get_config_value_safe(self.app, "app_name", "Fordonsregistrering")
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

    def _get_pin_getter(self) -> Callable[[], str]:
        """Returnera PIN-getter funktion."""
        config = get_plugin_safe(self.app, "core_config")
        def pin_getter() -> str:
            if not config:
                return "1234"
            # Försök vehicle_data_pin först
            vehicle_pin = get_config_value_safe(self.app, "vehicle_data_pin", None)
            if vehicle_pin:
                return vehicle_pin
            # Fallback till main PIN
            return self._get_pin_from_config(config)
        return pin_getter

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
MAIN_STYLESHEET: Final[str] = """
QMainWindow { background: #191b1f; color: #e0e0e0; }
QWidget { font-family: 'Segoe UI', sans-serif; font-size: 14px; }
QPushButton {
    background: #3a3f44; color: white;
    border-radius: 4px; padding: 8px 16px; border: 1px solid #555;
}
QPushButton:hover { background: #4a4f54; }
QPushButton#PrimaryButton { background: #007bff; border-color: #007bff; }
QPushButton#PrimaryButton:hover { background: #0056b3; }
QPushButton#SuccessButton { background: #28a745; border-color: #28a745; }
QPushButton#SuccessButton:hover { background: #218838; }
QLabel#PageTitle { font-size: 22px; font-weight: bold; color: #ffffff; }
QLineEdit, QComboBox, QTextEdit {
    background: #2b2b2b; color: #fff;
    border: 1px solid #444; border-radius: 4px; padding: 6px;
}
QLineEdit:focus { border-color: #007bff; }
QGroupBox {
    font-weight: bold; border: 1px solid #444;
    border-radius: 6px; margin-top: 12px; padding-top: 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
"""
SIDEBAR_BUTTON_STYLE: Final[str] = """
QPushButton {
    text-align: left; border: none; padding: 12px 10px; background: transparent;
}
QPushButton:checked {
    background: #2a2d33; color: #fff; border-left: 3px solid #007bff;
}
QPushButton:hover { background: #1f2226; }
"""
MENUBAR_STYLE: Final[str] = """
QMenuBar { background: #14161a; color: #fff; }
QMenuBar::item:selected { background: #2a2d33; }
QMenu { background: #2b2b2b; color: #fff; border: 1px solid #444; }
QMenu::item:selected { background: #007bff; }
"""
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
