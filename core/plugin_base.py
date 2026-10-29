# -*- coding: utf-8 -*-
# core/plugin_base.py
"""
Basklass som alla plugins ärver från.
Version 3.3.0 - Full integration med PluginLoader v2.3.0 & EventBus v2.2.0
Ändringar v3.3.0:
    - KONTRAKT KOMPLETT: register_ui(parent) och config_schema()
      tillagda (saknades helt — spec-kontraktet är init/register_ui/
      shutdown/config_schema). Båda är överskridbara defaults.
    - logger -> _log på modulnivå (spec-konvention).
      self.logger-property (plugin-egen logger) oförändrad.
    - All loggning: f-string -> lazy %s-formatering (spec)
    - _activate_time sätts nu i activate() (uptime_ms fungerade
      aldrig), _init_time sätts i initialize()
    - Oanvända importer borttagna (asyncio, wraps, Union, Set);
      Iterator tillagd för korrekt managed_resource-typning
    - Felaktig docstring-claim om "@on_event decorator
      auto-registration" borttagen (funktionen finns ej)
    - Dynamisk copyright-helper (get_copyright_string)
    - KONSOLIDERAD v3.3.0 (Session 10): filen var en hopklistrad
      dubbel-fil (v3.2.0 + v3.3.0 — BUGG #14-mönstret, gav
      SyntaxError "from __future__ imports must occur at the
      beginning of the file"). Endast v3.3.0-kopian behålls;
      alla markdown-artefakter borttagna ([url]-länkar,
      **-markeringar, *x*-mönster, &gt;/&lt;/&amp; osv.).
Ändringar v3.2.0:
    - Integration med EventBus.Priority och Events-konstanter
    - get_plugin() / get_plugin_safe() för enkel plugin-access
    - get_schema() för att hämta TS-scheman från ts_spec_import
    - emit_collect() helper för request/response pattern
    - health_check() returnerar nu bool (som PluginLoader förväntar)
    - Support för ALIASES class attribute
    - Förbättrad async lifecycle (async initialize/activate)
    - Resource cleanup med context managers
    - Standardiserade data-katalog helpers (get_ts_specs_dir, etc.)
Ändringar v3.1:
    - Bakåtkompatibilitet med synkrona plugins
    - is_active har setter
    - logger property
    - Fallback för NAME/VERSION/DEPENDENCIES
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""
from __future__ import annotations
import logging
import inspect
import time
from abc import ABC
from datetime import datetime
from pathlib import Path
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import (
    Optional, Dict, Any, List, Tuple, Callable,
    Iterator, Protocol, TypeVar, TYPE_CHECKING,
)
from contextlib import contextmanager
if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.application import Application
_log = logging.getLogger(__name__)
T = TypeVar('T')
VERSION = "3.3.0"
AUTHOR = "Rickard Längkvist"

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"

# ══════════════════════════════════════════════════════════════════════════════
# ENUMS OCH TYPER

# ══════════════════════════════════════════════════════════════════════════════

class ScreenCategory(Enum):
    """Skärmstorlek-kategorier för responsiv UI."""
    SMALL = auto()
    MEDIUM = auto()
    LARGE = auto()
    XLARGE = auto()
    ULTRA = auto()
    @property

    def min_width(self) -> int:
        return {
            self.SMALL: 0,
            self.MEDIUM: 1366,
            self.LARGE: 1920,
            self.XLARGE: 2560,
            self.ULTRA: 3840
        }[self]
    @classmethod

    def from_width(cls, width: int) -> ScreenCategory:
        if width < 1366:
            return cls.SMALL
        elif width < 1920:
            return cls.MEDIUM
        elif width < 2560:
            return cls.LARGE
        elif width < 3840:
            return cls.XLARGE
        else:
            return cls.ULTRA

class PluginState(Enum):
    """Plugin lifecycle states."""
    UNINITIALIZED = auto()
    INITIALIZING = auto()
    READY = auto()
    ACTIVATING = auto()
    ACTIVE = auto()
    DEACTIVATING = auto()
    INACTIVE = auto()
    ERROR = auto()

class HealthStatus(Enum):
    """Plugin health check status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

# ══════════════════════════════════════════════════════════════════════════════
# SCREEN CONFIGURATION (Immutable)

# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)

class ScreenConfig:
    """Immutable skärmkonfiguration."""
    category: ScreenCategory
    width: int
    height: int
    dpi_scale: float
    scale_factor: float = field(init=False)
    font_size_small: int = field(init=False)
    font_size_normal: int = field(init=False)
    font_size_large: int = field(init=False)
    font_size_header: int = field(init=False)
    padding: int = field(init=False)
    margin: int = field(init=False)
    spacing: int = field(init=False)
    button_height: int = field(init=False)
    input_height: int = field(init=False)
    toolbar_height: int = field(init=False)
    statusbar_height: int = field(init=False)

    def __post_init__(self):
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Invalid dimensions: {self.width}x{self.height}")
        if self.dpi_scale <= 0:
            raise ValueError(f"Invalid DPI scale: {self.dpi_scale}")
        scale_map = {
            ScreenCategory.SMALL: 0.75,
            ScreenCategory.MEDIUM: 0.9,
            ScreenCategory.LARGE: 1.0,
            ScreenCategory.XLARGE: 1.15,
            ScreenCategory.ULTRA: 1.35
        }
        object.__setattr__(self, 'scale_factor', scale_map[self.category])
        base_font = {
            ScreenCategory.SMALL: 8,
            ScreenCategory.MEDIUM: 9,
            ScreenCategory.LARGE: 10,
            ScreenCategory.XLARGE: 11,
            ScreenCategory.ULTRA: 12
        }[self.category]
        object.__setattr__(self, 'font_size_small', base_font - 1)
        object.__setattr__(self, 'font_size_normal', base_font)
        object.__setattr__(self, 'font_size_large', base_font + 2)
        object.__setattr__(self, 'font_size_header', base_font + 4)
        sf = self.scale_factor
        object.__setattr__(self, 'padding', max(1, int(10 * sf)))
        object.__setattr__(self, 'margin', max(1, int(10 * sf)))
        object.__setattr__(self, 'spacing', max(1, int(8 * sf)))
        object.__setattr__(self, 'button_height', max(20, int(32 * sf)))
        object.__setattr__(self, 'input_height', max(18, int(28 * sf)))
        object.__setattr__(self, 'toolbar_height', max(24, int(36 * sf)))
        object.__setattr__(self, 'statusbar_height', max(18, int(24 * sf)))
    @classmethod

    def from_dimensions(
        cls, width: int, height: int, dpi_scale: float = 1.0
    ) -> ScreenConfig:
        effective_width = width / dpi_scale
        category = ScreenCategory.from_width(int(effective_width))
        return cls(
            category=category, width=width,
            height=height, dpi_scale=dpi_scale,
        )
    @property

    def effective_width(self) -> int:
        return int(self.width / self.dpi_scale)
    @property

    def effective_height(self) -> int:
        return int(self.height / self.dpi_scale)
    @property

    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height > 0 else 16 / 9

    def scale(self, value: int) -> int:
        return max(1, int(value * self.scale_factor))

# ══════════════════════════════════════════════════════════════════════════════
# EVENT PROTOCOLS

# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)

class ScreenChangeEvent:
    """Event som emitteras vid skärmändringar."""
    width: int
    height: int
    dpi_scale: float
    category: ScreenCategory
    prev_width: Optional[int] = None
    prev_height: Optional[int] = None
    prev_dpi_scale: Optional[float] = None
    prev_category: Optional[ScreenCategory] = None
    @property

    def is_category_change(self) -> bool:
        return (
            self.prev_category is not None
            and self.category != self.prev_category
        )
    @property

    def is_resize(self) -> bool:
        return self.prev_width != self.width or self.prev_height != self.height
    @property

    def is_dpi_change(self) -> bool:
        return (
            self.prev_dpi_scale is not None
            and self.prev_dpi_scale != self.dpi_scale
        )

@dataclass(frozen=True)

class WindowEvent:
    """Event för fönster-operationer."""
    event_type: str
    window_id: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None

# ══════════════════════════════════════════════════════════════════════════════
# UI COMPONENT INTERFACE

# ══════════════════════════════════════════════════════════════════════════════

class UIComponent(Protocol):
    """Protocol för UI-komponenter som behöver skärmanpassning."""

    def on_screen_change(self, config: ScreenConfig) -> None: ...

    def on_theme_change(self, theme: Dict[str, Any]) -> None: ...

    def refresh(self) -> None: ...

    def destroy(self) -> None: ...

# ══════════════════════════════════════════════════════════════════════════════
# WINDOW MANAGER

# ══════════════════════════════════════════════════════════════════════════════

class WindowManager:
    """Helper för window/screen-relaterade operationer."""

    def __init__(self, config: ScreenConfig):
        self._config = config
    @property

    def config(self) -> ScreenConfig:
        return self._config

    def update_config(self, config: ScreenConfig) -> WindowManager:
        return WindowManager(config)

    def scale(self, value: int) -> int:
        return self._config.scale(value)

    def get_font_size(self, style: str = 'normal') -> int:
        sizes = {
            'small': self._config.font_size_small,
            'normal': self._config.font_size_normal,
            'large': self._config.font_size_large,
            'header': self._config.font_size_header,
        }
        return sizes.get(style, self._config.font_size_normal)

    def calculate_dialog_size(
        self,
        base_width: int = 400,
        base_height: int = 300,
        max_width_ratio: float = 0.8,
        max_height_ratio: float = 0.8
    ) -> Tuple[int, int]:
        scaled_w = self.scale(base_width)
        scaled_h = self.scale(base_height)
        max_w = int(self._config.width * max_width_ratio)
        max_h = int(self._config.height * max_height_ratio)
        return min(scaled_w, max_w), min(scaled_h, max_h)

    def center_on_screen(
        self,
        width: int,
        height: int,
        offset_x: int = 0,
        offset_y: int = 0
    ) -> Tuple[int, int]:
        x = (self._config.width - width) // 2 + offset_x
        y = (self._config.height - height) // 2 + offset_y
        margin = 50
        x = max(margin, min(x, self._config.width - width - margin))
        y = max(margin, min(y, self._config.height - height - margin))
        return x, y

    def get_layout_metrics(self) -> Dict[str, int]:
        return {
            'padding': self._config.padding,
            'margin': self._config.margin,
            'spacing': self._config.spacing,
            'button_height': self._config.button_height,
            'input_height': self._config.input_height,
            'toolbar_height': self._config.toolbar_height,
            'statusbar_height': self._config.statusbar_height,
        }

# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN METADATA

# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)

class PluginMetadata:
    """Immutable plugin metadata."""
    name: str
    version: str
    description: str = ""
    author: str = ""
    dependencies: Tuple[str, ...] = field(default_factory=tuple)
    optional_dependencies: Tuple[str, ...] = field(default_factory=tuple)
    aliases: Tuple[str, ...] = field(default_factory=tuple)
    min_app_version: Optional[str] = None
    has_ui: bool = False
    resizable: bool = True
    min_width: int = 640
    min_height: int = 480
    screen_aware: bool = True
    dpi_aware: bool = True

    def __post_init__(self):
        if not self.name:
            raise ValueError("Plugin name cannot be empty")
        if not self.version:
            raise ValueError("Plugin version cannot be empty")

# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN BASE CLASS

# ══════════════════════════════════════════════════════════════════════════════

class PluginBase(ABC):
    """
    Abstrakt basklass för alla plugins.
    Version 3.3.0 - Full integration med PluginLoader v2.3.0
    & EventBus v2.2.0.
    KONTRAKT (spec):
        init()              - initiera (alias för initialize)
        register_ui(parent) - registrera UI, returnera widget/None
        shutdown()          - stäng ner (alias för deactivate)
        config_schema()     - returnera konfigurationsschema
    Features:
        - Synkron och async lifecycle (init, activate, shutdown)
        - Enkel access till andra plugins via get_plugin()
        - Schema-access via get_schema() för ts_spec_import integration
        - Health checks som PluginLoader förväntar sig
        - Screen-aware UI management
        - Settings management
        - Resource cleanup guarantees
    """

    # ═══════════════════════════════════════════════════════════════════════════
    # CLASS ATTRIBUTES (överskrid i subklass)

    # ═══════════════════════════════════════════════════════════════════════════
    # Nytt sätt (METADATA)
    METADATA: Optional[PluginMetadata] = None
    # Gammalt sätt (class attributes) - bakåtkompatibilitet
    NAME: str = "Unnamed Plugin"
    VERSION: str = "0.0.0"
    DESCRIPTION: str = ""
    AUTHOR: str = ""
    DEPENDENCIES: List[str] = []
    OPTIONAL_DEPENDENCIES: List[str] = []
    ALIASES: List[str] = []  # För plugin_loader alias support

    def __init__(self, app: Any):
        """
        Initiera plugin.
        Args:
            app: Application instance (injiceras av PluginLoader)
        """
        self.app = app
        self._state = PluginState.UNINITIALIZED
        self._health_status = HealthStatus.UNKNOWN
        self._is_active = False
        self._init_time: Optional[float] = None
        self._activate_time: Optional[float] = None
        # Screen management
        self._screen_config: Optional[ScreenConfig] = None
        self._window_manager: Optional[WindowManager] = None
        self._ui_components: List[UIComponent] = []
        # Event tracking
        self._event_subscriptions: List[Tuple[str, Callable]] = []
        # Settings
        self._settings: Dict[str, Any] = {}
        # Resource tracking för cleanup
        self._resources: List[Any] = []
        # Logger för denna plugin
        self._logger = logging.getLogger(f"plugin.{self.name}")
        # Setup screen awareness
        if self.metadata and self.metadata.screen_aware:
            self._setup_screen_awareness()

    # ═══════════════════════════════════════════════════════════════════════════
    # PROPERTIES (med bakåtkompatibilitet)

    # ═══════════════════════════════════════════════════════════════════════════
    @property

    def metadata(self) -> Optional[PluginMetadata]:
        """Plugin metadata (om definierad)."""
        if self.METADATA:
            return self.METADATA
        # Skapa metadata från class attributes (bakåtkompatibilitet)
        try:
            return PluginMetadata(
                name=self.NAME,
                version=self.VERSION,
                description=self.DESCRIPTION,
                author=self.AUTHOR,
                dependencies=tuple(self.DEPENDENCIES),
                optional_dependencies=tuple(self.OPTIONAL_DEPENDENCIES),
                aliases=tuple(self.ALIASES),
            )
        except Exception:
            return None
    @property

    def name(self) -> str:
        """Plugin name."""
        if self.METADATA:
            return self.METADATA.name
        return self.NAME
    @property

    def version(self) -> str:
        """Plugin version."""
        if self.METADATA:
            return self.METADATA.version
        return self.VERSION
    @property

    def state(self) -> PluginState:
        """Nuvarande plugin state."""
        return self._state
    @property

    def is_initialized(self) -> bool:
        """True om pluginen är initierad."""
        return self._state not in (
            PluginState.UNINITIALIZED,
            PluginState.INITIALIZING
        )
    @property

    def is_active(self) -> bool:
        """True om pluginen är aktiv."""
        return self._is_active or self._state == PluginState.ACTIVE
    @is_active.setter

    def is_active(self, value: bool) -> None:
        """Sätt aktiv-status."""
        self._is_active = value
        if value:
            self._state = PluginState.ACTIVE
        else:
            self._state = PluginState.INACTIVE
    @property

    def health(self) -> HealthStatus:
        """Nuvarande hälsostatus."""
        return self._health_status
    @property

    def logger(self) -> logging.Logger:
        """Logger för pluginen (ingen setter)."""
        return self._logger
    @property

    def event_bus(self) -> Optional[Any]:
        """Direct access till EventBus."""
        return getattr(self.app, 'event_bus', None)

    # ═══════════════════════════════════════════════════════════════════════════
    # PLUGIN ACCESS

    # ═══════════════════════════════════════════════════════════════════════════

    def get_plugin(self, name: str) -> Optional[Any]:
        """
        Hämta en annan plugin via namn.
        Args:
            name: Plugin-namn eller alias
        Returns:
            Plugin-instans eller None
        """
        if hasattr(self.app, 'get_plugin'):
            return self.app.get_plugin(name)
        if hasattr(self.app, 'plugin_loader'):
            return self.app.plugin_loader.get_plugin(name)
        return None

    def get_plugin_safe(self, name: str, default: Any = None) -> Any:
        """
        Hämta plugin utan att kasta exception.
        Args:
            name: Plugin-namn
            default: Returneras om plugin inte finns
        Returns:
            Plugin-instans eller default
        """
        if hasattr(self.app, 'get_plugin_safe'):
            return self.app.get_plugin_safe(name, default)
        try:
            result = self.get_plugin(name)
            return result if result is not None else default
        except Exception:
            return default

    def require_plugin(self, name: str) -> Any:
        """
        Hämta plugin, kasta exception om den saknas.
        Args:
            name: Plugin-namn
        Returns:
            Plugin-instans
        Raises:
            RuntimeError: Om plugin inte finns
        """
        plugin = self.get_plugin(name)
        if plugin is None:
            raise RuntimeError(
                f"Required plugin '{name}' not found. "
                f"Add it to DEPENDENCIES in {self.name}"
            )
        return plugin

    # ═══════════════════════════════════════════════════════════════════════════
    # SCHEMA ACCESS (för ts_spec_import integration)

    # ═══════════════════════════════════════════════════════════════════════════

    def get_schema(self, post_type: str) -> Optional[Any]:
        """
        Hämta ett TS-schema (PT28, PT45, PT99, etc).
        Kräver att ts_spec_import plugin är laddad.
        Args:
            post_type: Schema-typ (t.ex. "PT28", "PT45", "PT99")
        Returns:
            Schema-objekt eller None
        """
        spec_import = self.get_plugin_safe("ts_spec_import")
        if spec_import and hasattr(spec_import, 'get_schema'):
            return spec_import.get_schema(post_type)
        # Fallback: kolla om schemat finns i app
        if hasattr(self.app, 'schemas'):
            return self.app.schemas.get(post_type)
        return None

    def get_all_schemas(self) -> Dict[str, Any]:
        """
        Hämta alla laddade TS-scheman.
        Returns:
            Dict med post_type -> schema
        """
        spec_import = self.get_plugin_safe("ts_spec_import")
        if spec_import and hasattr(spec_import, 'get_all_schemas'):
            return spec_import.get_all_schemas()
        if hasattr(self.app, 'schemas'):
            return dict(self.app.schemas)
        return {}

    def has_schema(self, post_type: str) -> bool:
        """Kontrollera om ett schema är laddat."""
        return self.get_schema(post_type) is not None

    # ═══════════════════════════════════════════════════════════════════════════
    # SCREEN MANAGEMENT

    # ═══════════════════════════════════════════════════════════════════════════
    @property

    def screen_config(self) -> ScreenConfig:
        """Nuvarande skärmkonfiguration."""
        if self._screen_config is None:
            self._screen_config = self._detect_screen_config()
        return self._screen_config
    @property

    def window_manager(self) -> WindowManager:
        """Window manager (lazy init)."""
        if self._window_manager is None:
            self._window_manager = WindowManager(self.screen_config)
        return self._window_manager
    @property

    def screen_category(self) -> ScreenCategory:
        """Nuvarande skärmkategori."""
        return self.screen_config.category
    @property

    def scale_factor(self) -> float:
        """Nuvarande skalfaktor."""
        return self.screen_config.scale_factor

    def scale(self, value: int) -> int:
        """Skala värde baserat på skärmstorlek."""
        return self.screen_config.scale(value)

    # ═══════════════════════════════════════════════════════════════════════════
    # LIFECYCLE (Synkrona, överskridbar)

    # ═══════════════════════════════════════════════════════════════════════════

    def init(self) -> None:
        """
        Initiera pluginen (alias för initialize).
        """
        self.initialize()

    def initialize(self) -> None:
        """
        Initiera pluginen.
        Överskrid i subklass för custom initiering.
        """
        self._init_time = time.time()

    def activate(self) -> None:
        """
        Aktivera pluginen.
        Överskrid i subklass för custom aktivering.
        """
        self._activate_time = time.time()
        self.is_active = True

    def shutdown(self) -> None:
        """
        Stäng ner pluginen (alias för deactivate).
        """
        self.deactivate()

    def deactivate(self) -> None:
        """
        Deaktivera pluginen.
        Rengör resurser, avregistrerar events, etc.
        """
        self._state = PluginState.DEACTIVATING
        try:
            # Custom cleanup hook
            self.on_deactivate()
            # Avregistrera alla events
            self._unsubscribe_all_events()
            # Rensa UI-komponenter
            for component in self._ui_components:
                try:
                    if hasattr(component, 'destroy'):
                        component.destroy()
                except Exception as e:
                    self._logger.error("Error destroying component: %s", e)
            self._ui_components.clear()
            # Rensa tracked resources
            self._cleanup_resources()
            self._is_active = False
            self._state = PluginState.INACTIVE
            self._logger.info("Plugin %s deactivated", self.name)
        except Exception as e:
            self._state = PluginState.ERROR
            self._logger.exception("Error during deactivation: %s", e)
            raise

    def on_deactivate(self) -> None:
        """Hook för custom cleanup. Överskrid för egen logik."""
        pass

    # ═══════════════════════════════════════════════════════════════════════════
    # UI-KONTRAKT (NYTT v3.3.0 — saknades trots spec-kontraktet)

    # ═══════════════════════════════════════════════════════════════════════════

    def register_ui(self, parent: Any) -> Optional[Any]:
        """
        Registrera pluginets UI (spec-kontrakt).
        Överskrid i subklass för att returnera en QWidget som läggs
        som flik i huvudfönstret. Default: ingen UI (None).
        Args:
            parent: Föräldrawidget/huvudfönster
        Returns:
            QWidget eller None
        """
        _ = parent
        return None

    def config_schema(self) -> Dict[str, Any]:
        """
        Returnera pluginets konfigurationsschema (spec-kontrakt).
        Överskrid i subklass för egna inställningar.
        Default: metadata + tom settings-dict.
        Returns:
            Dict med plugin-konfiguration
        """
        return {
            "plugin": self.name,
            "version": self.version,
            "author": self.AUTHOR or (
                self.METADATA.author if self.METADATA else ""
            ),
            "settings": {},
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # HEALTH CHECKS

    # ═══════════════════════════════════════════════════════════════════════════

    def health_check(self) -> bool:
        """
        Utför health check.
        Returns:
            True om healthy, False annars
        """
        try:
            # Bas-check: är pluginen aktiv?
            if not self.is_active:
                self._health_status = HealthStatus.UNHEALTHY
                return False
            # Är state ERROR?
            if self._state == PluginState.ERROR:
                self._health_status = HealthStatus.UNHEALTHY
                return False
            # Custom validation
            if not self._validate_health():
                self._health_status = HealthStatus.DEGRADED
                return False
            self._health_status = HealthStatus.HEALTHY
            return True
        except Exception as e:
            self._logger.error("Health check failed: %s", e)
            self._health_status = HealthStatus.UNHEALTHY
            return False

    def _validate_health(self) -> bool:
        """
        Custom health validation hook.
        Returns:
            True om allt OK
        """
        return True

    def get_health_details(self) -> Dict[str, Any]:
        """Returnera detaljerad health information."""
        return {
            "plugin": self.name,
            "version": self.version,
            "status": self._health_status.value,
            "state": self._state.name,
            "active": self.is_active,
            "initialized": self.is_initialized,
            "subscriptions": len(self._event_subscriptions),
            "ui_components": len(self._ui_components),
            "resources": len(self._resources),
            "uptime_ms": self._get_uptime_ms(),
        }

    def _get_uptime_ms(self) -> Optional[float]:
        """Beräkna uptime sedan aktivering."""
        if self._activate_time:
            return (time.time() - self._activate_time) * 1000
        return None

    # ═══════════════════════════════════════════════════════════════════════════
    # EVENT BUS INTEGRATION

    # ═══════════════════════════════════════════════════════════════════════════

    def get_event_bus(self) -> Optional[Any]:
        """Hämta EventBus från app."""
        if hasattr(self.app, 'event_bus'):
            return self.app.event_bus
        return None

    def subscribe(
        self,
        event_name: str,
        callback: Callable,
        priority: int = 50
    ) -> bool:
        """
        Prenumerera på event.
        """
        return self.subscribe_event(event_name, callback, priority)

    def subscribe_event(
        self,
        event_name: str,
        callback: Callable,
        priority: int = 50
    ) -> bool:
        """Prenumerera på event."""
        event_bus = self.get_event_bus()
        if not event_bus:
            self._logger.warning(
                "No event bus available for event: %s", event_name,
            )
            return False
        try:
            event_bus.on(
                event_name, callback, priority=priority, source=self.name,
            )
        except TypeError:
            # Fallback om on() inte stödjer alla parametrar
            event_bus.on(event_name, callback)
        self._event_subscriptions.append((event_name, callback))
        self._logger.debug("Subscribed to event: %s", event_name)
        return True

    def unsubscribe_event(
        self,
        event_name: str,
        callback: Optional[Callable] = None
    ) -> bool:
        """Avsluta prenumeration."""
        event_bus = self.get_event_bus()
        if not event_bus:
            return False
        try:
            count = event_bus.off(event_name, callback)
        except Exception:
            count = 0
        if callback:
            self._event_subscriptions = [
                (e, c) for e, c in self._event_subscriptions
                if not (e == event_name and c == callback)
            ]
        else:
            self._event_subscriptions = [
                (e, c) for e, c in self._event_subscriptions
                if e != event_name
            ]
        return count > 0 if isinstance(count, int) else bool(count)

    def _unsubscribe_all_events(self) -> None:
        """Avsluta alla prenumerationer."""
        event_bus = self.get_event_bus()
        if event_bus:
            if hasattr(event_bus, 'off_all'):
                event_bus.off_all(self.name)
            else:
                for event_name, callback in self._event_subscriptions:
                    try:
                        event_bus.off(event_name, callback)
                    except Exception:
                        pass
        self._event_subscriptions.clear()

    def emit(self, event_name: str, data: Any = None) -> int:
        """
        Emittera event (alias för emit_event).
        """
        return self.emit_event(event_name, data)

    def emit_event(self, event_name: str, data: Any = None) -> int:
        """Emittera event."""
        event_bus = self.get_event_bus()
        if not event_bus:
            self._logger.warning(
                "No event bus available for event: %s", event_name,
            )
            return 0
        try:
            result = event_bus.emit(event_name, data, source=self.name)
            return result if isinstance(result, int) else 0
        except Exception as e:
            self._logger.error("Failed to emit %s: %s", event_name, e)
            return 0

    def emit_collect(
        self,
        event_name: str,
        data: Any = None,
        filter_none: bool = True,
        timeout: Optional[float] = None
    ) -> List[Any]:
        """
        Emittera och samla svar från alla lyssnare.
        """
        event_bus = self.get_event_bus()
        if not event_bus or not hasattr(event_bus, 'emit_collect'):
            self._logger.warning("emit_collect not available")
            return []
        try:
            return event_bus.emit_collect(
                event_name,
                data,
                filter_none=filter_none,
                timeout=timeout
            )
        except Exception as e:
            self._logger.error(
                "Failed to emit_collect %s: %s", event_name, e,
            )
            return []
    async def emit_async(self, event_name: str, data: Any = None) -> int:
        """
        Emittera event asynkront.
        """
        event_bus = self.get_event_bus()
        if not event_bus:
            return 0
        if hasattr(event_bus, 'emit_async'):
            return await event_bus.emit_async(event_name, data)
        else:
            return self.emit_event(event_name, data)

    # ═══════════════════════════════════════════════════════════════════════════
    # DATA DIRECTORIES

    # ═══════════════════════════════════════════════════════════════════════════

    def get_plugin_dir(self) -> Optional[Path]:
        """Hämta plugin-katalog."""
        try:
            module_file = inspect.getfile(self.__class__)
            return Path(module_file).parent
        except Exception:
            return None

    def get_data_dir(self) -> Optional[Path]:
        """Hämta plugin data-katalog."""
        if hasattr(self.app, 'get_plugin_data_dir'):
            path = self.app.get_plugin_data_dir(self.name)
            return Path(path) if path else None
        plugin_dir = self.get_plugin_dir()
        if plugin_dir:
            data_dir = plugin_dir / 'data'
            data_dir.mkdir(exist_ok=True)
            return data_dir
        return None

    def get_app_data_dir(self) -> Path:
        """Hämta applikationens data-katalog."""
        if hasattr(self.app, 'data_dir'):
            return Path(self.app.data_dir)
        return Path("data")

    def get_ts_specs_dir(self) -> Path:
        """Hämta katalog för TS-specifikationer (JSON-scheman)."""
        return self.get_app_data_dir() / "ts_specs"

    def get_vehicle_registry_dir(self) -> Path:
        """Hämta katalog för fordonsregister."""
        return self.get_app_data_dir() / "vehicle_registry"

    def get_output_dir(self) -> Path:
        """Hämta ut-katalog för genererade TS-filer."""
        base = self.get_app_data_dir().parent
        out_dir = base / "ut"
        out_dir.mkdir(exist_ok=True)
        return out_dir

    def get_input_dir(self) -> Path:
        """Hämta In-katalog för svarsfiler från TS."""
        base = self.get_app_data_dir().parent
        in_dir = base / "In"
        in_dir.mkdir(exist_ok=True)
        return in_dir

    # ═══════════════════════════════════════════════════════════════════════════
    # RESOURCE MANAGEMENT

    # ═══════════════════════════════════════════════════════════════════════════

    def track_resource(self, resource: Any) -> None:
        """Tracka en resurs för automatisk cleanup."""
        self._resources.append(resource)

    def _cleanup_resources(self) -> None:
        """Rensa alla trackade resurser."""
        for resource in self._resources:
            try:
                if hasattr(resource, 'close'):
                    resource.close()
                elif hasattr(resource, 'cleanup'):
                    resource.cleanup()
                elif hasattr(resource, 'dispose'):
                    resource.dispose()
            except Exception as e:
                self._logger.error("Error cleaning up resource: %s", e)
        self._resources.clear()
    @contextmanager

    def managed_resource(self, resource: T) -> Iterator[T]:
        """Context manager för automatisk resource cleanup."""
        self.track_resource(resource)
        try:
            yield resource
        finally:
            try:
                if hasattr(resource, 'close'):
                    resource.close()
                self._resources.remove(resource)
            except Exception:
                pass
    @contextmanager

    def temp_mute_events(self, *event_names: str):
        """Context manager för att tillfälligt tysta events."""
        event_bus = self.get_event_bus()
        if not event_bus or not hasattr(event_bus, 'muted'):
            yield
            return
        with event_bus.muted(*event_names):
            yield

    # ═══════════════════════════════════════════════════════════════════════════
    # SCREEN EVENT HANDLERS

    # ═══════════════════════════════════════════════════════════════════════════

    def _setup_screen_awareness(self) -> None:
        """Setup automatisk skärmhantering."""
        self.subscribe_event('screen:changed', self._on_screen_change)
        self.subscribe_event('theme:changed', self._on_theme_change)
        self.subscribe_event('screen:dpi_changed', self._on_dpi_change)

    def _detect_screen_config(self) -> ScreenConfig:
        """Detektera skärmkonfiguration från app."""
        if hasattr(self.app, 'get_screen_info'):
            info = self.app.get_screen_info()
            return ScreenConfig.from_dimensions(
                info.get('width', 1920),
                info.get('height', 1080),
                info.get('dpi_scale', 1.0)
            )
        return ScreenConfig.from_dimensions(1920, 1080, 1.0)

    def _on_screen_change(self, event: Any) -> None:
        """Internal handler för skärmändringar."""
        if isinstance(event, ScreenChangeEvent):
            new_config = ScreenConfig.from_dimensions(
                event.width, event.height, event.dpi_scale
            )
        elif isinstance(event, dict):
            new_config = ScreenConfig.from_dimensions(
                event.get('width', 1920),
                event.get('height', 1080),
                event.get('dpi_scale', 1.0)
            )
        else:
            return
        prev_config = self._screen_config
        self._screen_config = new_config
        if self._window_manager:
            self._window_manager = self._window_manager.update_config(
                new_config
            )
        for component in self._ui_components:
            try:
                component.on_screen_change(new_config)
            except Exception as e:
                self._logger.error("Component screen change failed: %s", e)
        self.on_screen_change(event, prev_config, new_config)

    def on_screen_change(
        self,
        event: Any,
        prev_config: Optional[ScreenConfig],
        new_config: ScreenConfig
    ) -> None:
        """Hook för skärmändringar. Överskrid för custom logik."""
        pass

    def _on_dpi_change(self, event: Any) -> None:
        """Internal handler för DPI-ändringar."""
        self.request_ui_rescale()

    def _on_theme_change(self, theme: Dict[str, Any]) -> None:
        """Internal handler för temaändringar."""
        for component in self._ui_components:
            try:
                component.on_theme_change(theme)
            except Exception as e:
                self._logger.error("Component theme change failed: %s", e)
        self.on_theme_change(theme)

    def on_theme_change(self, theme: Dict[str, Any]) -> None:
        """Hook för temaändringar. Överskrid för custom logik."""
        pass

    def request_ui_rebuild(self) -> None:
        """Begär fullständig UI-rebuild."""
        pass

    def request_ui_rescale(self) -> None:
        """Begär UI rescale."""
        pass

    # ═══════════════════════════════════════════════════════════════════════════
    # UI COMPONENT MANAGEMENT

    # ═══════════════════════════════════════════════════════════════════════════

    def register_ui_component(self, component: UIComponent) -> None:
        """Registrera UI-komponent för automatisk hantering."""
        if component not in self._ui_components:
            self._ui_components.append(component)
            if self._screen_config:
                try:
                    component.on_screen_change(self._screen_config)
                except Exception as e:
                    self._logger.error(
                        "Component registration failed: %s", e,
                    )

    def unregister_ui_component(self, component: UIComponent) -> None:
        """Avregistrera UI-komponent."""
        try:
            self._ui_components.remove(component)
        except ValueError:
            pass

    def refresh_all_components(self) -> None:
        """Uppdatera alla UI-komponenter."""
        for component in self._ui_components:
            try:
                component.refresh()
            except Exception as e:
                self._logger.error("Component refresh failed: %s", e)

    # ═══════════════════════════════════════════════════════════════════════════
    # SETTINGS MANAGEMENT

    # ═══════════════════════════════════════════════════════════════════════════

    def get_settings(self) -> Dict[str, Any]:
        """Hämta alla settings."""
        settings = self._settings.copy()
        custom = self.get_custom_settings()
        if custom:
            settings.update(custom)
        return settings

    def set_settings(self, settings: Dict[str, Any]) -> None:
        """Uppdatera settings."""
        self._settings = settings.copy()
        self.apply_custom_settings(settings)

    def get_custom_settings(self) -> Dict[str, Any]:
        """Hook för custom settings."""
        return {}

    def apply_custom_settings(self, settings: Dict[str, Any]) -> None:
        """Hook för att applicera settings."""
        pass

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Hämta specifik setting."""
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        """Sätt specifik setting."""
        old_value = self._settings.get(key)
        self._settings[key] = value
        if old_value != value:
            self.on_setting_changed(key, value, old_value)

    def on_setting_changed(
        self, key: str, new_value: Any, old_value: Any
    ) -> None:
        """Hook för setting-ändringar."""
        pass

    # ═══════════════════════════════════════════════════════════════════════════
    # REPRESENTATION

    # ═══════════════════════════════════════════════════════════════════════════

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"

    def __repr__(self) -> str:
        return (
            f"<Plugin:{self.name} "
            f"v={self.version} "
            f"state={self._state.name} "
            f"active={self.is_active}>"
        )

# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS

# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Main class
    'PluginBase',
    'PluginMetadata',
    # States
    'PluginState',
    'HealthStatus',
    # Screen management
    'ScreenCategory',
    'ScreenConfig',
    'ScreenChangeEvent',
    'WindowEvent',
    'UIComponent',
    'WindowManager',
    # Version
    'VERSION',
    'AUTHOR',
]
