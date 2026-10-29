# -*- coding: utf-8 -*-
# core/plugin_loader.py
"""
Dynamisk plugin-laddare med dependency resolution v2.3.0
Features:
    - Automatisk upptäckt av plugins i plugins/-katalogen
    - Dependency resolution med topologisk sortering
    - Circular dependency detection
    - Graceful error handling
    - Hot reload support (optional)
    - Plugin metadata validation
    - Centraliserad plugin-access via app
    - Thread-safe plugin registry
Ändringar v2.3.0:
    - logger -> _log (spec-konvention, module-level)
    - All loggning: f-string -> lazy %s-formatering (spec)
    - asyncio.get_event_loop() (deprecated i 3.12) ersatt med
      asyncio.get_running_loop()-detektering + asyncio.run()
      i get_plugin() lazy-load
    - Oanvänd import (Union) borttagen, re flyttad till modulnivå
    - Dynamisk copyright-helper (get_copyright_string)
    - KONSOLIDERAD (Session 10): dubbeldefinition to_class_name/
      _to_class_name borttagen (endast to_class_name behålls,
      _find_plugin_class anropar den); alla markdown-artefakter
      borttagna ([url]-länkar, **-markeringar, *x*-mönster,
      &gt;/&lt;/&amp; osv.).
Ändringar v2.2.0:
    - Förbättrad robusthet vid lazy loading
    - Bättre hantering av async/sync context mixing
    - Thread-safe plugin access med RLock
    - Utökad logging för debugging
    - Support för plugin aliases (t.ex. "sap" -> "sap_import")
    - Automatisk retry vid transient load failures
    - Plugin health checks
    - Metrics tracking (load times, success rates)
Ändringar v2.1.0:
    - Injicerar centrala accessors på app-objektet:
        * app.plugin_loader = loader
        * app.plugin_manager = loader (bakåtkompat alias)
        * app.get_plugin = loader.get_plugin
        * app.get_plugin_safe = loader.get_plugin_safe
        * app.event_bus = bus
    - Robusta get_plugin() som fungerar oavsett tillstånd
    - Bättre felhantering vid missing dependencies
    - Support för OPTIONAL_DEPENDENCIES
Användning:
    from core import PluginLoader, EventBus
    bus = EventBus()
    loader = PluginLoader("plugins/", event_bus=bus, app=app)
    # Ladda alla plugins
    plugins = await loader.load_all()
    # Initiera i rätt ordning (dependencies först)
    await loader.initialize_all()
    # Aktivera
    await loader.activate_all()
    # Health check
    health = loader.check_health()
    if health["unhealthy"]:
        _log.warning("Unhealthy plugins: %s", health["unhealthy"])
    # Cleanup vid shutdown
    await loader.shutdown_all()
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""
from __future__ import annotations
import asyncio
import importlib
import importlib.util
import logging
import re
import sys
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any, Callable, Dict, List, Optional, Set,
    Tuple, Type, TYPE_CHECKING,
)
if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.plugin_base import PluginBase
from core.exceptions import (
    PluginLoadError,
    PluginInitError,
    PluginActivationError,
    DependencyError,
)
_log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS

# ══════════════════════════════════════════════════════════════════════════════
VERSION = "2.3.0"
AUTHOR = "Rickard Längkvist"

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"

# Plugins utan hårda dependencies (laddas alltid)
CORE_PLUGINS = frozenset([
    "core_config",
    "core_logger",
    "core_events",
])
# Retry-inställningar för transient failures
MAX_LOAD_RETRIES = 2
RETRY_DELAY_MS = 100

# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES

# ══════════════════════════════════════════════════════════════════════════════

class LoadState(Enum):
    """Plugin load state."""
    DISCOVERED = auto()
    LOADING = auto()
    LOADED = auto()
    INITIALIZING = auto()
    INITIALIZED = auto()
    ACTIVATING = auto()
    ACTIVE = auto()
    FAILED = auto()
    DISABLED = auto()
    UNLOADING = auto()

@dataclass

class PluginMetrics:
    """Metrics för en plugin."""
    load_attempts: int = 0
    load_failures: int = 0
    last_load_time_ms: float = 0.0
    total_load_time_ms: float = 0.0
    initialization_time_ms: float = 0.0
    activation_time_ms: float = 0.0
    last_error: Optional[str] = None
    last_success_timestamp: float = 0.0
    last_failure_timestamp: float = 0.0
    @property

    def success_rate(self) -> float:
        if self.load_attempts == 0:
            return 0.0
        return (self.load_attempts - self.load_failures) / self.load_attempts
    @property

    def average_load_time_ms(self) -> float:
        if self.load_attempts == 0:
            return 0.0
        return self.total_load_time_ms / self.load_attempts

@dataclass

class PluginInfo:
    """
    Information om en upptäckt plugin.
    Attributes:
        name: Plugin-namn (från METADATA eller mappnamn)
        path: Sökväg till plugin-katalogen
        module_name: Python module name
        plugin_class: Plugin-klassen (efter laddning)
        instance: Plugin-instansen (efter instantiering)
        state: Nuvarande tillstånd
        dependencies: Lista med required dependencies
        optional_dependencies: Lista med optionella dependencies
        aliases: Alternativa namn för plugin
        error: Eventuellt fel vid laddning
        metrics: Performance metrics
    """
    name: str
    path: Path
    module_name: str
    plugin_class: Optional[Type[PluginBase]] = None
    instance: Optional[PluginBase] = None
    state: LoadState = LoadState.DISCOVERED
    dependencies: List[str] = field(default_factory=list)
    optional_dependencies: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    error: Optional[Exception] = None
    metrics: PluginMetrics = field(default_factory=PluginMetrics)
    # Internal
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    @property

    def load_time_ms(self) -> float:
        """Bakåtkompatibilitet."""
        return self.metrics.last_load_time_ms
    @load_time_ms.setter

    def load_time_ms(self, value: float):
        """Bakåtkompatibilitet."""
        self.metrics.last_load_time_ms = value
        self.metrics.total_load_time_ms += value
    @property

    def is_loaded(self) -> bool:
        return self.state in (
            LoadState.LOADED,
            LoadState.INITIALIZED,
            LoadState.ACTIVE,
        )
    @property

    def is_active(self) -> bool:
        return self.state == LoadState.ACTIVE
    @property

    def has_error(self) -> bool:
        return self.state == LoadState.FAILED or self.error is not None
    @property

    def all_dependencies(self) -> List[str]:
        """Alla dependencies (required + optional)."""
        return self.dependencies + self.optional_dependencies
    @contextmanager

    def state_transition(self, new_state: LoadState):
        """Context manager för säker state-transition."""
        with self._lock:
            old_state = self.state
            self.state = new_state
            try:
                yield
            except Exception:
                self.state = LoadState.FAILED
                raise
            else:
                _log.debug(
                    "%s: %s -> %s",
                    self.name, old_state.name, new_state.name,
                )

@dataclass

class LoadResult:
    """Resultat av en laddningsoperation."""
    success: List[str] = field(default_factory=list)
    failed: List[Tuple[str, Exception]] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    @property

    def total(self) -> int:
        return len(self.success) + len(self.failed) + len(self.skipped)
    @property

    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return len(self.success) / self.total

    def summary(self) -> str:
        return (
            f"Loaded {len(self.success)}/{self.total} plugins "
            f"({len(self.failed)} failed, {len(self.skipped)} skipped)"
        )

# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN LOADER

# ══════════════════════════════════════════════════════════════════════════════

class PluginLoader:
    """
    Dynamisk plugin-laddare med dependency resolution.
    Thread-safe och robust mot async/sync context mixing.
    """
    PLUGIN_FILENAME = "plugin.py"
    INIT_FILENAME = "__init__.py"
    DISABLED_PREFIX = "_"

    def __init__(
        self,
        plugins_dir: str | Path,
        event_bus: Optional[EventBus] = None,
        app: Any = None,
        *,
        auto_discover: bool = True,
        strict_dependencies: bool = False,
        enable_hot_reload: bool = False,
    ):
        """
        Initiera plugin loader.
        Args:
            plugins_dir: Katalog med plugins
            event_bus: EventBus för kommunikation
            app: App-instans att skicka till plugins
            auto_discover: Kör discover() automatiskt
            strict_dependencies: Fail om REQUIRED dependencies saknas
            enable_hot_reload: Aktivera hot reload (experimentellt)
        """
        self.plugins_dir = Path(plugins_dir)
        self.event_bus = event_bus
        self.app = app
        self.strict_dependencies = strict_dependencies
        self.enable_hot_reload = enable_hot_reload
        # Plugin registry (thread-safe)
        self._plugins: Dict[str, PluginInfo] = {}
        self._load_order: List[str] = []
        self._plugin_aliases: Dict[str, str] = {}  # alias -> real_name
        self._lock = threading.RLock()
        # Callbacks
        self._on_load_callbacks: List[Callable] = []
        self._on_error_callbacks: List[Callable] = []
        # Metrics
        self._global_metrics = {
            "total_loads": 0,
            "total_failures": 0,
            "start_time": time.time(),
        }
        # Validate directory
        if not self.plugins_dir.exists():
            _log.warning(
                "Plugins directory does not exist: %s", self.plugins_dir,
            )
            self.plugins_dir.mkdir(parents=True, exist_ok=True)
        # Injicera centrala accessors på app (v2.1.0+)
        if self.app is not None:
            self._inject_app_accessors()
        if auto_discover:
            self.discover()

    def _inject_app_accessors(self) -> None:
        """
        Injicera centrala plugin-accessors på app-objektet.
        """
        # Primär access
        self.app.plugin_loader = self
        # Bakåtkompatibelt alias
        self.app.plugin_manager = self
        # Convenience methods
        self.app.get_plugin = self.get_plugin
        self.app.get_plugin_safe = self.get_plugin_safe
        # Event bus (om tillgänglig)
        if self.event_bus is not None and not hasattr(self.app, "event_bus"):
            self.app.event_bus = self.event_bus
        _log.debug(
            "Injected app.get_plugin(), app.get_plugin_safe(), "
            "app.plugin_loader, app.plugin_manager"
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # DISCOVERY

    # ═══════════════════════════════════════════════════════════════════════════

    def discover(self) -> List[str]:
        """
        Upptäck plugins i plugins-katalogen.
        Returns:
            Lista med upptäckta plugin-namn
        """
        discovered = []
        if not self.plugins_dir.exists():
            _log.error("Plugins directory not found: %s", self.plugins_dir)
            return discovered
        with self._lock:
            for item in self.plugins_dir.iterdir():
                # Hoppa över filer och dolda/disabled
                if not item.is_dir():
                    continue
                if item.name.startswith(self.DISABLED_PREFIX):
                    _log.debug("Skipping disabled plugin: %s", item.name)
                    continue
                if item.name.startswith("__"):
                    continue
                # Kolla efter plugin.py eller __init__.py
                plugin_file = item / self.PLUGIN_FILENAME
                init_file = item / self.INIT_FILENAME
                if plugin_file.exists() or init_file.exists():
                    plugin_name = item.name
                    if plugin_name not in self._plugins:
                        self._plugins[plugin_name] = PluginInfo(
                            name=plugin_name,
                            path=item,
                            module_name=f"plugins.{plugin_name}.plugin",
                        )
                        discovered.append(plugin_name)
                        _log.debug("Discovered plugin: %s", plugin_name)
        _log.info(
            "Discovered %d plugins in %s", len(discovered), self.plugins_dir,
        )
        return discovered

    def get_discovered(self) -> List[str]:
        """Returnera lista med alla upptäckta plugins."""
        with self._lock:
            return list(self._plugins.keys())

    def get_plugin_info(self, name: str) -> Optional[PluginInfo]:
        """
        Hämta info om en specifik plugin.
        Stödjer aliases.
        """
        with self._lock:
            # Kolla om det är ett alias
            real_name = self._plugin_aliases.get(name, name)
            return self._plugins.get(real_name)

    # ═══════════════════════════════════════════════════════════════════════════
    # LOADING

    # ═══════════════════════════════════════════════════════════════════════════
    async def load(self, name: str, retry: bool = True) -> PluginBase:
        """
        Ladda en specifik plugin.
        Args:
            name: Plugin-namn (eller alias)
            retry: Aktivera automatisk retry vid transient failures
        Returns:
            Plugin-instans
        Raises:
            PluginLoadError: Om laddning misslyckas
            DependencyError: Om dependencies saknas
        """
        # Resolve alias
        real_name = self._plugin_aliases.get(name, name)
        info = self._plugins.get(real_name)
        if not info:
            # Försök discover först
            self.discover()
            info = self._plugins.get(real_name)
            if not info:
                raise PluginLoadError(
                    f"Plugin '{name}' not found",
                    plugin_name=name,
                    plugin_path=self.plugins_dir / name,
                )
        # Om redan laddat, returnera genom instans
        if info.is_loaded and info.instance:
            return info.instance
        # Ladda plugin med retry
        attempts = MAX_LOAD_RETRIES if retry else 1
        last_error = None
        for attempt in range(attempts):
            try:
                return await self._load_plugin(info)
            except Exception as e:
                last_error = e
                info.metrics.load_failures += 1
                info.metrics.last_failure_timestamp = time.time()
                if attempt < attempts - 1:
                    _log.warning(
                        "Load attempt %d/%d failed for %s, "
                        "retrying in %dms...",
                        attempt + 1, attempts, real_name, RETRY_DELAY_MS,
                    )
                    await asyncio.sleep(RETRY_DELAY_MS / 1000)
                else:
                    _log.error(
                        "All %d load attempts failed for %s",
                        attempts, real_name,
                    )
        raise last_error
    async def load_all(self) -> LoadResult:
        """
        Ladda alla upptäckta plugins i dependency-ordning.
        Returns:
            LoadResult med statistik
        """
        result = LoadResult()
        with self._lock:
            # Säkerställ att vi har upptäckt plugins
            if not self._plugins:
                self.discover()
            # Resolve dependency order
            try:
                self._load_order = self._resolve_load_order()
            except DependencyError as e:
                _log.error("Dependency resolution failed: %s", e)
                # Ladda i alfabetisk ordning istället (graceful degradation)
                self._load_order = sorted(self._plugins.keys())
                _log.warning(
                    "Loading in alphabetical order instead: %s",
                    self._load_order,
                )
        # Ladda i ordning
        for name in self._load_order:
            info = self._plugins.get(name)
            if not info:
                continue
            try:
                await self._load_plugin(info)
                result.success.append(name)
            except Exception as e:
                with info._lock:
                    info.state = LoadState.FAILED
                    info.error = e
                    info.metrics.last_error = str(e)
                result.failed.append((name, e))
                _log.error("Failed to load plugin: %s", name, exc_info=e)
                # Notify error callbacks
                for callback in self._on_error_callbacks:
                    try:
                        callback(name, e)
                    except Exception:
                        pass
        _log.info("%s", result.summary())
        # Emit event
        if self.event_bus:
            try:
                self.event_bus.emit("plugins:loaded", {
                    "success": result.success,
                    "failed": [name for name, _ in result.failed],
                    "total": result.total,
                })
            except Exception as e:
                _log.debug("Could not emit plugins:loaded: %s", e)
        return result
    async def _load_plugin(self, info: PluginInfo) -> PluginBase:
        """Intern metod för att ladda en plugin."""
        start_time = time.perf_counter()
        with info.state_transition(LoadState.LOADING):
            info.metrics.load_attempts += 1
            self._global_metrics["total_loads"] += 1
            try:
                # Import module
                _log.debug("Importing module: %s", info.module_name)
                if info.module_name in sys.modules and not self.enable_hot_reload:
                    module = sys.modules[info.module_name]
                    _log.debug(
                        "Module %s already in sys.modules", info.module_name,
                    )
                else:
                    plugin_file = info.path / self.PLUGIN_FILENAME
                    if not plugin_file.exists():
                        plugin_file = info.path / self.INIT_FILENAME
                    if not plugin_file.exists():
                        raise PluginLoadError(
                            f"No plugin file found in {info.path}",
                            plugin_name=info.name,
                            plugin_path=info.path,
                        )
                    spec = importlib.util.spec_from_file_location(
                        info.module_name,
                        plugin_file,
                    )
                    if spec is None or spec.loader is None:
                        raise PluginLoadError(
                            "Cannot create module spec",
                            plugin_name=info.name,
                            plugin_path=info.path,
                        )
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[info.module_name] = module
                    spec.loader.exec_module(module)
                # Hitta plugin-klassen
                plugin_class = self._find_plugin_class(module, info.name)
                if not plugin_class:
                    raise PluginLoadError(
                        f"No PluginBase subclass found in {info.module_name}",
                        plugin_name=info.name,
                        plugin_path=info.path,
                    )
                info.plugin_class = plugin_class
                # Extrahera metadata
                self._extract_metadata(info, plugin_class)
                # Skapa instans
                instance = plugin_class(self.app)
                with info._lock:
                    info.instance = instance
                    info.state = LoadState.LOADED
                # Registrera aliases
                for alias in info.aliases:
                    self._plugin_aliases[alias] = info.name
                # Registrera på app för snabb access
                if self.app is not None:
                    attr_name = info.name.replace("-", "_").lower()
                    if not hasattr(self.app, attr_name):
                        setattr(self.app, attr_name, instance)
                        _log.debug("Registered app.%s", attr_name)
                # Timing
                load_time_ms = (time.perf_counter() - start_time) * 1000
                info.load_time_ms = load_time_ms
                info.metrics.last_success_timestamp = time.time()
                _log.info(
                    "Loaded plugin: %s v%s (%.1fms)",
                    info.name,
                    getattr(instance, "VERSION", "?"),
                    load_time_ms,
                )
                # Notify callbacks
                for callback in self._on_load_callbacks:
                    try:
                        callback(info.name, instance)
                    except Exception:
                        pass
                return instance
            except PluginLoadError:
                self._global_metrics["total_failures"] += 1
                raise
            except Exception as e:
                self._global_metrics["total_failures"] += 1
                raise PluginLoadError(
                    f"Failed to load plugin: {str(e)}",
                    plugin_name=info.name,
                    plugin_path=info.path,
                    original_error=e,
                ) from e

    def _extract_metadata(
        self, info: PluginInfo, plugin_class: Type[PluginBase]
    ) -> None:
        """Extrahera metadata från plugin-klass."""
        # Dependencies
        if hasattr(plugin_class, "METADATA"):
            metadata = plugin_class.METADATA
            if hasattr(metadata, "dependencies"):
                info.dependencies = list(metadata.dependencies)
        elif hasattr(plugin_class, "DEPENDENCIES"):
            info.dependencies = list(plugin_class.DEPENDENCIES)
        # Optional dependencies
        if hasattr(plugin_class, "OPTIONAL_DEPENDENCIES"):
            info.optional_dependencies = list(
                plugin_class.OPTIONAL_DEPENDENCIES
            )
        # Aliases
        if hasattr(plugin_class, "ALIASES"):
            info.aliases = list(plugin_class.ALIASES)
        elif hasattr(plugin_class, "METADATA") and hasattr(
            plugin_class.METADATA, "aliases"
        ):
            info.aliases = list(plugin_class.METADATA.aliases)

    def _find_plugin_class(
        self, module: Any, plugin_name: str
    ) -> Optional[Type[PluginBase]]:
        """Hitta PluginBase-subklass i modul."""
        from core.plugin_base import PluginBase
        # Försök standard-namn först
        standard_names = [
            "Plugin",  # Mest vanligt
            f"{self.to_class_name(plugin_name)}Plugin",
            f"{self.to_class_name(plugin_name)}",
        ]
        for name in standard_names:
            cls = getattr(module, name, None)
            if (
                cls
                and isinstance(cls, type)
                and issubclass(cls, PluginBase)
                and cls is not PluginBase
            ):
                return cls
        # Sök igenom alla klasser
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, PluginBase)
                and attr is not PluginBase
            ):
                return attr
        return None
    @staticmethod

    def to_class_name(plugin_name: str) -> str:
        """Konvertera plugin-namn till klassnamn (snake_case → PascalCase)."""
        return "".join(word.capitalize() for word in plugin_name.split("_"))

    # ═══════════════════════════════════════════════════════════════════════════
    # DEPENDENCY RESOLUTION

    # ═══════════════════════════════════════════════════════════════════════════

    def _resolve_load_order(self) -> List[str]:
        """
        Resolve dependency order med topologisk sortering.
        Returns:
            Lista med plugin-namn i korrekt laddningsordning
        Raises:
            DependencyError: Vid circular dependencies eller saknade
                REQUIRED deps
        """
        with self._lock:
            # Bygg dependency graph
            graph: Dict[str, Set[str]] = {}
            in_degree: Dict[str, int] = {}
            for name in self._plugins.keys():
                graph[name] = set()
                in_degree[name] = 0
            # Lägg till dependencies
            missing_deps: Dict[str, List[str]] = {}
            for name, info in self._plugins.items():
                # Peek dependencies från fil
                deps, optional_deps = self._peek_dependencies(info)
                info.dependencies = deps
                info.optional_dependencies = optional_deps
                # Lägg endast till REQUIRED dependencies i grafen
                for dep in deps:
                    if dep not in self._plugins:
                        # Required dependency saknas
                        if name not in missing_deps:
                            missing_deps[name] = []
                        missing_deps[name].append(dep)
                    else:
                        graph[dep].add(name)
                        in_degree[name] = in_degree.get(name, 0) + 1
            # Kolla missing REQUIRED dependencies
            if missing_deps and self.strict_dependencies:
                first_plugin = next(iter(missing_deps))
                raise DependencyError(
                    f"Plugin '{first_plugin}' has missing dependencies",
                    plugin_name=first_plugin,
                    missing=missing_deps[first_plugin],
                )
            elif missing_deps:
                # Logga varning men fortsätt (graceful degradation)
                for plugin, deps in missing_deps.items():
                    _log.warning(
                        "Plugin '%s' has missing dependencies: %s",
                        plugin, deps,
                    )
            # Kahn's algorithm för topologisk sortering
            queue = [name for name, degree in in_degree.items() if degree == 0]
            result = []
            while queue:
                # Sortera queue för deterministisk ordning
                queue.sort()
                node = queue.pop(0)
                result.append(node)
                # Uppdatera in_degree för dependents
                for dependent in graph.get(node, []):
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)
            # Kolla circular dependencies
            if len(result) != len(self._plugins):
                remaining = set(self._plugins.keys()) - set(result)
                cycle = self._find_cycle(graph, remaining)
                raise DependencyError(
                    "Circular dependency detected",
                    circular=cycle,
                )
            return result

    def _peek_dependencies(
        self, info: PluginInfo
    ) -> Tuple[List[str], List[str]]:
        """
        Läs dependencies utan att fullständigt ladda plugin.
        Returns:
            (required_dependencies, optional_dependencies)
        """
        plugin_file = info.path / self.PLUGIN_FILENAME
        if not plugin_file.exists():
            plugin_file = info.path / self.INIT_FILENAME
        if not plugin_file.exists():
            return [], []
        try:
            content = plugin_file.read_text(encoding="utf-8")
            required_deps = []
            optional_deps = []
            # DEPENDENCIES = [...]
            dep_match = re.search(
                r'DEPENDENCIES\s*=\s*\[(.*?)\]',
                content,
                re.DOTALL,
            )
            if dep_match:
                deps_str = dep_match.group(1)
                required_deps = re.findall(
                    r'["\']([^"\']+)["\']', deps_str,
                )
            # OPTIONAL_DEPENDENCIES = [...]
            opt_match = re.search(
                r'OPTIONAL_DEPENDENCIES\s*=\s*\[(.*?)\]',
                content,
                re.DOTALL,
            )
            if opt_match:
                deps_str = opt_match.group(1)
                optional_deps = re.findall(
                    r'["\']([^"\']+)["\']', deps_str,
                )
            # METADATA dependencies=(...) (fallback)
            if not required_deps:
                meta_match = re.search(
                    r'dependencies\s*=\s*[\(\[](.*?)[\)\]]',
                    content,
                    re.DOTALL,
                )
                if meta_match:
                    deps_str = meta_match.group(1)
                    required_deps = re.findall(
                        r'["\']([^"\']+)["\']', deps_str,
                    )
            return required_deps, optional_deps
        except Exception as e:
            _log.debug(
                "Could not peek dependencies for %s: %s", info.name, e,
            )
            return [], []

    def _find_cycle(
        self, graph: Dict[str, Set[str]], nodes: Set[str]
    ) -> List[str]:
        """Hitta en cykel i grafen (DFS-baserad)."""
        visited = set()
        path = []
        def dfs(node: str) -> Optional[List[str]]:
            if node in path:
                cycle_start = path.index(node)
                return path[cycle_start:] + [node]
            if node in visited:
                return None
            visited.add(node)
            path.append(node)
            for dependent in graph.get(node, []):
                if dependent in nodes:
                    res = dfs(dependent)
                    if res:
                        return res
            path.pop()
            return None
        for node in nodes:
            res = dfs(node)
            if res:
                return res
        return list(nodes)[:5]  # Fallback

    # ═══════════════════════════════════════════════════════════════════════════
    # INITIALIZATION & ACTIVATION

    # ═══════════════════════════════════════════════════════════════════════════
    async def initialize_all(self) -> LoadResult:
        """
        Initiera alla laddade plugins i dependency-ordning.
        Returns:
            LoadResult med statistik
        """
        result = LoadResult()
        for name in self._load_order:
            info = self._plugins.get(name)
            if not info or not info.instance:
                result.skipped.append(name)
                continue
            if info.state == LoadState.FAILED:
                result.skipped.append(name)
                continue
            try:
                _log.debug("Initializing plugin: %s", name)
                start_time = time.perf_counter()
                with info.state_transition(LoadState.INITIALIZING):
                    # Kör initialize (sync eller async)
                    init_method = info.instance.init
                    if asyncio.iscoroutinefunction(init_method):
                        await init_method()
                    else:
                        init_method()
                    info.state = LoadState.INITIALIZED
                info.metrics.initialization_time_ms = (
                    time.perf_counter() - start_time
                ) * 1000
                result.success.append(name)
                _log.info(
                    "Initialized plugin: %s (%.1fms)",
                    name, info.metrics.initialization_time_ms,
                )
            except Exception as e:
                with info._lock:
                    info.state = LoadState.FAILED
                    info.error = e
                    info.metrics.last_error = str(e)
                result.failed.append((name, e))
                _log.error(
                    "Failed to initialize plugin: %s", name, exc_info=e,
                )
        return result
    async def activate_all(self) -> LoadResult:
        """
        Aktivera alla initierade plugins.
        Returns:
            LoadResult med statistik
        """
        result = LoadResult()
        for name in self._load_order:
            info = self._plugins.get(name)
            if not info or not info.instance:
                result.skipped.append(name)
                continue
            if info.state != LoadState.INITIALIZED:
                result.skipped.append(name)
                continue
            try:
                _log.debug("Activating plugin: %s", name)
                start_time = time.perf_counter()
                with info.state_transition(LoadState.ACTIVATING):
                    # Kör activate (sync eller async)
                    activate_method = info.instance.activate
                    if asyncio.iscoroutinefunction(activate_method):
                        await activate_method()
                    else:
                        activate_method()
                    info.state = LoadState.ACTIVE
                info.metrics.activation_time_ms = (
                    time.perf_counter() - start_time
                ) * 1000
                result.success.append(name)
                _log.info(
                    "Activated plugin: %s (%.1fms)",
                    name, info.metrics.activation_time_ms,
                )
            except Exception as e:
                with info._lock:
                    info.state = LoadState.FAILED
                    info.error = e
                    info.metrics.last_error = str(e)
                result.failed.append((name, e))
                _log.error(
                    "Failed to activate plugin: %s", name, exc_info=e,
                )
        # Emit event om event_bus finns
        if self.event_bus:
            try:
                self.event_bus.emit("plugins:all_activated", {
                    "count": len(result.success),
                    "plugins": result.success,
                })
            except Exception as e:
                _log.debug("Could not emit plugins:all_activated: %s", e)
        _log.info(
            "Plugin activation complete: %d active", len(result.success),
        )
        return result

    # ═══════════════════════════════════════════════════════════════════════════
    # SHUTDOWN

    # ═══════════════════════════════════════════════════════════════════════════
    async def shutdown_all(self) -> LoadResult:
        """
        Stäng ner alla aktiva plugins (i omvänd ordning).
        Returns:
            LoadResult med statistik
        """
        result = LoadResult()
        # Stäng i omvänd laddningsordning
        for name in reversed(self._load_order):
            info = self._plugins.get(name)
            if not info or not info.instance:
                continue
            if info.state not in (LoadState.ACTIVE, LoadState.INITIALIZED):
                continue
            try:
                _log.debug("Deactivating plugin: %s", name)
                with info.state_transition(LoadState.UNLOADING):
                    # Kör shutdown (sync eller async)
                    shutdown_method = info.instance.shutdown
                    if asyncio.iscoroutinefunction(shutdown_method):
                        await shutdown_method()
                    else:
                        shutdown_method()
                    info.state = LoadState.LOADED
                result.success.append(name)
                _log.info("Deactivated plugin: %s", name)
            except Exception as e:
                result.failed.append((name, e))
                _log.error(
                    "Error deactivating plugin: %s", name, exc_info=e,
                )
        return result

    # ═══════════════════════════════════════════════════════════════════════════
    # PLUGIN ACCESS (ROBUST)

    # ═══════════════════════════════════════════════════════════════════════════

    def get_plugin(self, name: str) -> Optional[PluginBase]:
        """
        Hämta plugin-instans (ROBUST).
        Stödjer aliases. Fungerar även om plugin inte är aktiverad ännu.
        FIXAT v2.3.0: asyncio.get_event_loop() (deprecated i Python
        3.12 utan körande loop) ersatt med get_running_loop()-
        detektering + asyncio.run() för sync-vägen.
        Args:
            name: Plugin-namn eller alias
        Returns:
            Plugin-instans eller None
        """
        with self._lock:
            # Resolve alias
            real_name = self._plugin_aliases.get(name, name)
            info = self._plugins.get(real_name)
            if info and info.instance:
                return info.instance
            # Försök ladda om inte redan laddat (lazy loading)
            if info and not info.instance and info.state == LoadState.DISCOVERED:
                # Kolla om vi är i async-kontext
                try:
                    asyncio.get_running_loop()
                    # Loop körs — kan inte köra sync i async-kontext
                    _log.warning(
                        "Cannot lazy-load plugin '%s' in async context. "
                        "Use 'await loader.load()' instead.",
                        name,
                    )
                    return None
                except RuntimeError:
                    # Ingen loop körs — säkert att köra synkront
                    pass
                try:
                    instance = asyncio.run(self.load(real_name))
                    return instance
                except Exception as e:
                    _log.error(
                        "Lazy-loading plugin '%s' failed: %s", name, e,
                    )
                    return None
            return None

    def get_plugin_safe(
        self, name: str, default: Any = None
    ) -> Optional[PluginBase]:
        """
        Hämta plugin-instans (SAFE - returnerar aldrig exception).
        Args:
            name: Plugin-namn eller alias
            default: Värde att returnera om plugin inte finns
        Returns:
            Plugin-instans, default, eller None
        """
        try:
            result = self.get_plugin(name)
            return result if result is not None else default
        except Exception as e:
            _log.debug("get_plugin_safe('%s') failed: %s", name, e)
            return default

    def get_active_plugins(self) -> List[PluginBase]:
        """Hämta alla aktiva plugin-instanser."""
        with self._lock:
            return [
                info.instance
                for info in self._plugins.values()
                if info.instance and info.state == LoadState.ACTIVE
            ]

    def get_all_plugins(self) -> Dict[str, PluginBase]:
        """
        Hämta alla laddade plugins (även ej-aktiverade).
        Returns:
            Dict med plugin_name -> plugin_instance
        """
        with self._lock:
            return {
                name: info.instance
                for name, info in self._plugins.items()
                if info.instance
            }

    def has_plugin(self, name: str) -> bool:
        """Kolla om plugin finns och är laddat."""
        with self._lock:
            real_name = self._plugin_aliases.get(name, name)
            info = self._plugins.get(real_name)
            return info is not None and info.instance is not None

    # ═══════════════════════════════════════════════════════════════════════════
    # HEALTH CHECKS

    # ═══════════════════════════════════════════════════════════════════════════

    def check_health(self) -> Dict[str, Any]:
        """
        Kör health check på alla plugins.
        Returns:
            Dict med health status
        """
        healthy = []
        unhealthy = []
        with self._lock:
            for name, info in self._plugins.items():
                if not info.instance:
                    continue
                try:
                    # Kolla om plugin har health check
                    if hasattr(info.instance, "health_check"):
                        is_healthy = info.instance.health_check()
                    else:
                        # Fallback: kolla state
                        is_healthy = info.state == LoadState.ACTIVE
                    if is_healthy:
                        healthy.append(name)
                    else:
                        unhealthy.append({
                            "name": name,
                            "state": info.state.name,
                            "error": str(info.error) if info.error else None,
                        })
                except Exception as e:
                    unhealthy.append({
                        "name": name,
                        "state": info.state.name,
                        "error": str(e),
                    })
        total_count = len(healthy) + len(unhealthy)
        return {
            "healthy": healthy,
            "unhealthy": unhealthy,
            "total": total_count,
            "health_rate": (
                len(healthy) / total_count if total_count > 0 else 0.0
            ),
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITIES

    # ═══════════════════════════════════════════════════════════════════════════

    def get_load_order(self) -> List[str]:
        """Hämta laddningsordning."""
        with self._lock:
            return self._load_order.copy()

    def on_load(self, callback: Callable[[str, PluginBase], None]) -> None:
        """Registrera callback för plugin-laddning."""
        self._on_load_callbacks.append(callback)

    def on_error(self, callback: Callable[[str, Exception], None]) -> None:
        """Registrera callback för laddningsfel."""
        self._on_error_callbacks.append(callback)

    def get_status(self) -> Dict[str, Any]:
        """Hämta status för alla plugins."""
        with self._lock:
            by_state = defaultdict(int)
            for info in self._plugins.values():
                by_state[info.state.name] += 1
            return {
                "total": len(self._plugins),
                "active": by_state.get("ACTIVE", 0),
                "initialized": by_state.get("INITIALIZED", 0),
                "loaded": by_state.get("LOADED", 0),
                "failed": by_state.get("FAILED", 0),
                "disabled": by_state.get("DISABLED", 0),
                "by_state": dict(by_state),
                "load_order": self._load_order,
                "global_metrics": self._global_metrics,
                "plugins": {
                    name: {
                        "state": info.state.name,
                        "dependencies": info.dependencies,
                        "optional_dependencies": info.optional_dependencies,
                        "aliases": info.aliases,
                        "metrics": {
                            "load_time_ms": info.metrics.last_load_time_ms,
                            "success_rate": info.metrics.success_rate,
                            "load_attempts": info.metrics.load_attempts,
                            "load_failures": info.metrics.load_failures,
                        },
                        "has_instance": info.instance is not None,
                        "error": str(info.error) if info.error else None,
                    }
                    for name, info in self._plugins.items()
                },
            }

    def get_metrics(self) -> Dict[str, Any]:
        """Hämta metrics för alla plugins."""
        with self._lock:
            uptime = time.time() - self._global_metrics["start_time"]
            return {
                "uptime_seconds": uptime,
                "total_loads": self._global_metrics["total_loads"],
                "total_failures": self._global_metrics["total_failures"],
                "global_success_rate": (
                    (
                        self._global_metrics["total_loads"]
                        - self._global_metrics["total_failures"]
                    )
                    / self._global_metrics["total_loads"]
                    if self._global_metrics["total_loads"] > 0 else 0.0
                ),
                "plugins": {
                    name: {
                        "load_attempts": info.metrics.load_attempts,
                        "load_failures": info.metrics.load_failures,
                        "success_rate": info.metrics.success_rate,
                        "last_load_time_ms": info.metrics.last_load_time_ms,
                        "average_load_time_ms": (
                            info.metrics.average_load_time_ms
                        ),
                        "initialization_time_ms": (
                            info.metrics.initialization_time_ms
                        ),
                        "activation_time_ms": (
                            info.metrics.activation_time_ms
                        ),
                    }
                    for name, info in self._plugins.items()
                },
            }

    def get_dependency_tree(self) -> Dict[str, List[str]]:
        """
        Hämta dependency tree.
        Returns:
            Dict med plugin -> lista av dependencies
        """
        with self._lock:
            return {
                name: info.dependencies
                for name, info in self._plugins.items()
            }

    def get_dependents(self, plugin_name: str) -> List[str]:
        """
        Hämta plugins som beror på denna plugin.
        Args:
            plugin_name: Plugin att kolla
        Returns:
            Lista med plugin-namn som har plugin_name som dependency
        """
        with self._lock:
            dependents = []
            for name, info in self._plugins.items():
                if plugin_name in info.dependencies:
                    dependents.append(name)
            return dependents

    def __repr__(self) -> str:
        with self._lock:
            active = sum(
                1 for p in self._plugins.values()
                if p.state == LoadState.ACTIVE
            )
            total = len(self._plugins)
            return (
                f"<PluginLoader v{VERSION} plugins={total} "
                f"active={active} dir={self.plugins_dir}>"
            )

    def __str__(self) -> str:
        status = self.get_status()
        return (
            f"PluginLoader v{VERSION} ({status['total']} plugins, "
            f"{status['active']} active, "
            f"{status['failed']} failed)"
        )

# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS

# ══════════════════════════════════════════════════════════════════════════════

def create_loader(
    plugins_dir: str | Path = "plugins",
    event_bus: Optional[EventBus] = None,
    app: Any = None,
    auto_discover: bool = True,
    enable_hot_reload: bool = False,
) -> PluginLoader:
    """
    Factory function för att skapa PluginLoader.
    """
    return PluginLoader(
        plugins_dir=plugins_dir,
        event_bus=event_bus,
        app=app,
        auto_discover=auto_discover,
        enable_hot_reload=enable_hot_reload,
    )

# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS

# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "PluginLoader",
    "PluginInfo",
    "PluginMetrics",
    "LoadState",
    "LoadResult",
    "CORE_PLUGINS",
    "VERSION",
    "AUTHOR",
    "create_loader",
]
