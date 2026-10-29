#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# main.py
"""
Filregistrering — Fordonsfilregistreringssystem
Huvudentry för utvecklingsläge (med terminal).
Detta är den primära entry pointen under utveckling.
För produktion används main.pyw (ingen terminal).
═══════════════════════════════════════════════════════════════════════════════
DENNA FIL ÄR AVSEDD ATT VARA STABIL. Ändringar görs endast på uttrycklig order.
All funktionalitet kommer från plugins.
═══════════════════════════════════════════════════════════════════════════════
Arkitektur:
    - Kärnan laddar endast plugins och tillhandahåller infrastruktur
    - EventBus för all kommunikation
    - Configuration för central konfiguration
    - PluginLoader för automatisk plugin-hantering
    - SingleInstance säkerställer max en aktiv instans
    - CacheManager sköter smart cache och uppstädning
    - GUI skapas av main_gui-pluginet
Användning:
    python main.py                     # Normal start
    python main.py --debug             # Debug-läge
    python main.py --plugins-only      # Lista plugins och avsluta
    python main.py --validate-config   # Validera konfiguration
Environment Variables:
    APP_DEBUG=1                        # Aktivera debug
    APP_CONFIG=path/to/config.json     # Alternativ config-fil
    APP_LOG_LEVEL=DEBUG                # Log level
FÖRÄNDRINGAR v1.0.2 (Session 11 — förbättringsregel, spec v1.6):

    - FIX: APP_LOG_LEVEL-miljövariabeln (dokumenterad men oanvänd)
      prioriteras nu före config-värdet logging.level.

    - FIX: list_plugins() detekterar nu plugin.py ELLER __init__.py
      (samma regel som PluginLoader) — inga falska "FEL" för
      __init__.py-baserade plugins.

    - FIX: validate_config() använder use_env_override=True
      (konsistent med _load_configuration()).

FÖRÄNDRINGAR v1.0.1 (Session 10 — spec v1.4):
    - FIX: from core.logger_setup import setup_logging -> setup_all_loggers
      (spec API: setup_all_loggers(console_level, debug_log_enabled)).
      Anropet i start() anpassat till spec-signaturen.
    - FIX: SingleInstanceManager -> SingleInstance (core/single_instance
      v1.0.0 API: acquire()/release()/focus_existing()). _setup_single_instance()
      använder nu acquire() och main() anropar focus_existing().
    - FIX: CacheManager(project_root=..., config=...) -> CacheManager(
      base_dir=..., settings=...) enligt spec v1.0.0.
    - FIX: event_bus.on("app:error", ..., source=...) wrappat med
      TypeError-fallback (samma mönster som plugin_base).
    - Hela filen omskriven REN: markdown-artefakter borttagna
      ([url]-länkar, **-markeringar, *x*-mönster, &gt;/&lt;/&amp; osv.).
Version: 1.0.2
Python: 3.12+
Author: Rickard Längkvist
"""
from __future__ import annotations
import sys
import os
import signal
import logging
import argparse
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum, auto
VERSION = "1.0.2"
AUTHOR = "Rickard Längkvist"
APP_NAME = "Filregistrering"
_log = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
from core.event_bus import EventBus
from core.plugin_base import PluginBase
from core.plugin_loader import PluginLoader, LoadResult, LoadState
from core.config import Configuration, load_config, get_config
from core.exceptions import (
    CoreError,
    PluginError,
    PluginLoadError,
    DependencyError,
    ConfigError,
    ConfigNotFoundError,
)
from core.logger_setup import setup_all_loggers, shutdown_logging
from core.single_instance import SingleInstance
from core.cache_manager import CacheManager

class AppState(Enum):
    """Applikationstillstånd."""
    CREATED = auto()
    CONFIGURING = auto()
    LOADING_PLUGINS = auto()
    INITIALIZING = auto()
    RUNNING = auto()
    SHUTTING_DOWN = auto()
    TERMINATED = auto()

@dataclass

class AppMetrics:
    """Runtime-metrics för diagnostik."""
    start_time: datetime = field(default_factory=datetime.now)
    plugins_loaded: int = 0
    plugins_failed: int = 0
    events_emitted: int = 0
    errors_caught: int = 0
    @property

    def uptime_seconds(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time": self.start_time.isoformat(),
            "uptime_seconds": self.uptime_seconds,
            "plugins_loaded": self.plugins_loaded,
            "plugins_failed": self.plugins_failed,
            "events_emitted": self.events_emitted,
            "errors_caught": self.errors_caught,
        }

class Application:
    """
    Huvudapplikation — en stabil kärna som plugins bygger på.
    Tillhandahåller:
    - EventBus för plugin-kommunikation
    - Configuration för central konfiguration
    - PluginLoader för automatisk plugin-hantering
    - SingleInstance för eninstanskontroll
    - CacheManager för smart cache och uppstädning
    - Graceful shutdown
    - Diagnostik och metrics
    All UI och affärslogik kommer från plugins.
    """
    VERSION = VERSION
    APP_NAME = APP_NAME
    AUTHOR = AUTHOR
    _instance: Optional[Application] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> Application:
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        config_path: Optional[Path] = None,
        debug: bool = False,
        headless: bool = False,
    ) -> None:
        """Initiera applikation."""
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self._state = AppState.CREATED
        self._debug = debug
        self._headless = headless
        self._shutdown_requested = False
        self.metrics = AppMetrics()
        self._qapp: Optional[Any] = None
        self.main_window: Optional[Any] = None
        self.config: Optional[Configuration] = None
        self.event_bus: Optional[EventBus] = None
        self.plugin_loader: Optional[PluginLoader] = None
        self.single_instance: Optional[SingleInstance] = None
        self.cache_manager: Optional[CacheManager] = None
        self._project_root = PROJECT_ROOT
        self._config_path = config_path or self._find_config_file()
        self._setup_signal_handlers()

    # ═══════════════════════════════════════════════════════════════════════════
    # INITIALIZATION

    # ═══════════════════════════════════════════════════════════════════════════

    def _find_config_file(self) -> Path:
        """Hitta konfigurationsfil."""
        env_config = os.environ.get("APP_CONFIG")
        if env_config:
            return Path(env_config)
        return self._project_root / "config.json"

    def _setup_signal_handlers(self) -> None:
        """Registrera signal handlers för graceful shutdown."""
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGHUP, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Hantera OS-signaler."""
        sig_name = signal.Signals(signum).name
        _log.info("Received signal: %s", sig_name)
        self._shutdown_requested = True
        app = self._qapp
        if app is not None:
            try:
                app.quit()
            except Exception as exc:  # pragma: no cover
                _log.warning(
                    "Could not quit QApplication from signal: %s", exc,
                )

    def _create_default_config(self) -> Dict[str, Any]:
        """Skapa default-konfiguration."""
        return {
            "app_name": self.APP_NAME,
            "app_version": self.VERSION,
            "app_author": self.AUTHOR,
            "debug": self._debug,
            "paths": {
                "base_dir": str(self._project_root),
                "data_dir": "data",
                "vehicles_dir": "data/vehicles",
                "dispatch_dir": "data/dispatch",
                "output_dir": "ut",
                "logs_dir": "logs",
                "plugins_dir": "plugins",
                "cache_dir": "cache",
                "mappings_dir": "data/mappings",
            },
            "window": {
                "width": 1400,
                "height": 900,
                "sidebar_width": 220,
                "remember_position": True,
                "start_minimized": True,
            },
            "plugins": {
                "enabled": [
                    "core_config",
                    "core_logger",
                    "vehicle_registry",
                    "dealers_manager",
                    "colors_manager",
                    "sap_import",
                    "dispatch_viewer",
                    "data_viewer",
                    "reports",
                    "main_gui",
                ],
                "load_order": [
                    "core_config",
                    "core_logger",
                    "vehicle_registry",
                    "dealers_manager",
                    "colors_manager",
                    "sap_import",
                    "dispatch_viewer",
                    "data_viewer",
                    "reports",
                    "main_gui",
                ],
                "disabled": [],
            },
            "logging": {
                "level": "DEBUG" if self._debug else "INFO",
                "file_logging": True,
                "max_log_files": 10,
            },
            "theme": {
                "mode": "auto",
            },
            "smart_cache": {
                "enabled": True,
            },
            "_meta": {
                "created_at": datetime.now().isoformat(),
                "schema_version": "1.0",
            },
        }
    async def _load_configuration(self) -> None:
        """Ladda konfiguration."""
        self._state = AppState.CONFIGURING
        try:
            if self._config_path.exists():
                self.config = Configuration.load(
                    self._config_path,
                    use_env_override=True,
                )
                _log.debug("Loaded config from %s", self._config_path)
            else:
                default_data = self._create_default_config()
                self.config = Configuration.from_dict(
                    default_data,
                    source_path=self._config_path,
                    use_env_override=True,
                )
                self.config.save()
                _log.info(
                    "Created default config at %s", self._config_path,
                )
            try:
                load_config.__globals__["_global_config"] = self.config
            except Exception as exc:
                _log.debug("Could not set global config: %s", exc)
        except ConfigError as exc:
            _log.error("Configuration error: %s", exc)
            raise

    def _ensure_directories(self) -> None:
        """Skapa nödvändiga kataloger."""
        path_keys = [
            "paths.data_dir",
            "paths.vehicles_dir",
            "paths.dispatch_dir",
            "paths.output_dir",
            "paths.logs_dir",
            "paths.cache_dir",
            "paths.mappings_dir",
        ]
        for key in path_keys:
            dir_name = self.config.get_str(key, "")
            if not dir_name:
                continue
            full_path = self._project_root / dir_name
            full_path.mkdir(parents=True, exist_ok=True)
    async def _create_event_bus(self) -> None:
        """Skapa och konfigurera EventBus."""
        self.event_bus = EventBus()
        try:
            self.event_bus.on(
                "app:error", self._on_app_error, source="Application"
            )
        except TypeError:
            # Fallback om on() inte stödjer source-parametern
            self.event_bus.on("app:error", self._on_app_error)

    def _on_app_error(self, data: Dict[str, Any]) -> None:
        """Hantera app-errors via event bus."""
        self.metrics.errors_caught += 1
        _log.error(
            "App error: %s",
            data.get("message", "Unknown error"),
            extra=data,
        )

    def _setup_single_instance(self) -> bool:
        """
        Initiera eninstanskontroll.
        Returns:
            True om vi är första/enda instansen (lås taget)
        """
        self.single_instance = SingleInstance()
        return self.single_instance.acquire()

    def _setup_cache_manager(self) -> None:
        """Initiera cache-hantering och exit-hook."""
        self.cache_manager = CacheManager(
            base_dir=self._project_root,
            settings=self.config,
        )
        self.cache_manager.install_exit_hook()

    # ═══════════════════════════════════════════════════════════════════════════
    # PLUGIN MANAGEMENT

    # ═══════════════════════════════════════════════════════════════════════════
    async def _load_plugins(self) -> LoadResult:
        """Ladda alla plugins."""
        self._state = AppState.LOADING_PLUGINS
        plugins_dir = self._project_root / self.config.get_str(
            "paths.plugins_dir", "plugins"
        )
        self.plugin_loader = PluginLoader(
            plugins_dir=plugins_dir,
            event_bus=self.event_bus,
            app=self,
            auto_discover=True,
            strict_dependencies=not self._debug,
        )
        disabled = set(self.config.get_list("plugins.disabled", []))
        discovered = self.plugin_loader.get_discovered()
        for name in list(discovered):
            if name in disabled:
                _log.debug("Plugin disabled: %s", name)
                if name in self.plugin_loader._plugins:
                    del self.plugin_loader._plugins[name]
        result = await self.plugin_loader.load_all()
        self.metrics.plugins_loaded = len(result.success)
        self.metrics.plugins_failed = len(result.failed)
        return result
    async def _initialize_plugins(self) -> LoadResult:
        """Initiera alla plugins."""
        self._state = AppState.INITIALIZING
        return await self.plugin_loader.initialize_all()
    async def _activate_plugins(self) -> LoadResult:
        """Aktivera alla plugins."""
        result = await self.plugin_loader.activate_all()
        self.event_bus.emit("plugins:ready", {
            "count": len(result.success),
            "plugins": result.success,
        })
        return result

    # ═══════════════════════════════════════════════════════════════════════════
    # QT INTEGRATION

    # ═══════════════════════════════════════════════════════════════════════════

    def _init_qt(self) -> None:
        """Initiera Qt Application."""
        if self._headless:
            return
        from PySide6.QtWidgets import QApplication
        self._qapp = QApplication.instance()
        if not self._qapp:
            self._qapp = QApplication(sys.argv)
        self._qapp.setApplicationName(
            self.config.get_str("app_name", self.APP_NAME)
        )
        self._qapp.setApplicationVersion(self.VERSION)
        self._qapp.setOrganizationName(
            self.config.get_str("app_author", self.AUTHOR)
        )
        self._qapp.aboutToQuit.connect(self._on_qt_quit)

    def _on_qt_quit(self) -> None:
        """Hantera Qt quit."""
        if not self._shutdown_requested:
            self._shutdown_requested = True

    def _find_main_window(self) -> bool:
        """Hitta huvudfönster från main_gui plugin."""
        if self._headless:
            return True
        main_gui = self.get_plugin("main_gui")
        if main_gui and hasattr(main_gui, "main_window"):
            self.main_window = main_gui.main_window
            return True
        results = self.event_bus.emit_collect("app:get_main_window")
        for result in results:
            if result is not None:
                self.main_window = result
                return True
        return False

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API

    # ═══════════════════════════════════════════════════════════════════════════

    def get_plugin(self, name: str) -> Optional[PluginBase]:
        """Hämta en plugin."""
        if not self.plugin_loader:
            return None
        return self.plugin_loader.get_plugin(name)

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Hämta konfigurationsvärde."""
        if not self.config:
            return default
        return self.config.get(key, default)

    def set_config_value(self, key: str, value: Any) -> None:
        """Sätt konfigurationsvärde."""
        if self.config:
            self.config.set(key, value)

    def emit(self, event_name: str, data: Any = None) -> int:
        """Emittera event."""
        self.metrics.events_emitted += 1
        return self.event_bus.emit(event_name, data)
    @property

    def project_root(self) -> Path:
        """Projektets rotkatalog."""
        return self._project_root
    @property

    def state(self) -> AppState:
        """Nuvarande applikationstillstånd."""
        return self._state
    @property

    def is_debug(self) -> bool:
        """True om debug-läge är aktivt."""
        return self._debug

    # ═══════════════════════════════════════════════════════════════════════════
    # LIFECYCLE

    # ═══════════════════════════════════════════════════════════════════════════
    async def start(self) -> int:
        """Starta applikationen."""
        exit_code = 0
        try:
            self._print_banner()
            await self._load_configuration()
            self._setup_cache_manager()
            log_level = (
                os.environ.get("APP_LOG_LEVEL")
                or self.config.get_str("logging.level", "INFO")
            )
            setup_all_loggers(
                console_level=log_level,
                debug_log_enabled=True,
            )
            self._ensure_directories()
            await self._create_event_bus()
            self._init_qt()
            self._print_section("Laddar plugins")
            load_result = await self._load_plugins()
            self._print_load_result(load_result, "Laddade")
            self._print_section("Initierar plugins")
            init_result = await self._initialize_plugins()
            self._print_load_result(init_result, "Initierade")
            self._print_section("Aktiverar plugins")
            activate_result = await self._activate_plugins()
            self._print_load_result(activate_result, "Aktiverade")
            if not self._find_main_window():
                _log.error("Inget huvudfönster skapades")
                self._print_error_and_plugins()
                return 1
            self._state = AppState.RUNNING
            self._print_ready()
            self.event_bus.emit("app:started", {
                "version": self.VERSION,
                "debug": self._debug,
                "metrics": self.metrics.to_dict(),
            })
            if not self._headless and self._qapp:
                exit_code = self._qapp.exec()
        except KeyboardInterrupt:
            _log.info("Interrupted by user")
            exit_code = 130
        except ConfigError as exc:
            _log.error("Configuration error: %s", exc)
            exit_code = 2
        except PluginError as exc:
            _log.error("Plugin error: %s", exc)
            exit_code = 3
        except Exception as exc:
            _log.exception("Unexpected error: %s", exc)
            exit_code = 1
        finally:
            if self._state != AppState.TERMINATED:
                await self.shutdown()
        return exit_code
    async def shutdown(self) -> None:
        """Stäng ner applikationen gracefully."""
        if self._state in (AppState.SHUTTING_DOWN, AppState.TERMINATED):
            return
        self._state = AppState.SHUTTING_DOWN
        self._shutdown_requested = True
        _log.info("Stänger applikation")
        if self.event_bus:
            try:
                self.event_bus.emit("app:closing", {
                    "uptime_seconds": self.metrics.uptime_seconds,
                })
            except Exception as exc:
                _log.error("Error emitting app:closing: %s", exc)
        if self.plugin_loader:
            try:
                result = await self.plugin_loader.shutdown_all()
                _log.debug(
                    "Shutdown: %s plugins, %s failed",
                    len(result.success),
                    len(result.failed),
                )
            except Exception as exc:
                _log.error("Error during plugin shutdown: %s", exc)
        if self.config:
            try:
                self.config.set(
                    "_meta.last_shutdown",
                    datetime.now().isoformat(),
                )
                self.config.save()
            except Exception as exc:
                _log.error("Error saving config: %s", exc)
        try:
            shutdown_logging()
        except Exception as exc:
            _log.error("Error shutting down logging: %s", exc)
        self._state = AppState.TERMINATED
        _log.info("Avslutad")

    # ═══════════════════════════════════════════════════════════════════════════
    # OUTPUT FORMATTING (logg-baserad, inga print())

    # ═══════════════════════════════════════════════════════════════════════════

    def _print_banner(self) -> None:
        """Skriv ut start-banner."""
        _log.info("")
        _log.info("=" * 60)
        _log.info("  %s v%s", self.APP_NAME, self.VERSION)
        if self._debug:
            _log.info("  Debug-läge aktiverat")
        _log.info("=" * 60)

    def _print_section(self, title: str) -> None:
        """Skriv ut sektionsrubrik."""
        _log.info("")
        _log.info("%s...", title)
        _log.info("-" * 40)

    def _print_load_result(self, result: LoadResult, verb: str) -> None:
        """Skriv ut laddningsresultat."""
        for name in result.success:
            plugin = self.plugin_loader.get_plugin(name)
            if plugin:
                version = getattr(
                    plugin, "VERSION", getattr(plugin, "version", "?")
                )
                _log.info("  OK %s v%s", name, version)
            else:
                _log.info("  OK %s", name)
        for name, error in result.failed:
            _log.error("  FEL %s: %s", name, error)
        for name in result.skipped:
            _log.info("  HOPPAR %s", name)

    def _print_ready(self) -> None:
        """Skriv ut ready-meddelande."""
        total = self.metrics.plugins_loaded + self.metrics.plugins_failed
        active = self.metrics.plugins_loaded
        _log.info("")
        _log.info("=" * 60)
        _log.info("  %s/%s plugins aktiva", active, total)
        _log.info("  Starttid: %.2f s", self.metrics.uptime_seconds)
        _log.info("=" * 60)
        _log.info("")

    def _print_error_and_plugins(self) -> None:
        """Skriv ut felmeddelande och lista plugins."""
        _log.error("")
        _log.error("KRITISKT FEL: Inget huvudfönster skapades")
        _log.error("  Kontrollera att 'main_gui'-plugin är aktiverat")
        _log.error("")
        _log.error("Laddade plugins:")
        if self.plugin_loader:
            for name in self.plugin_loader._load_order:
                info = self.plugin_loader.get_plugin_info(name)
                if info:
                    status = "OK" if info.is_active else "FEL"
                    _log.error(
                        "  %s %s (%s)", status, name, info.state.name,
                    )

    def __repr__(self) -> str:
        return (
            "<Application "
            "v{} state={} plugins={}>".format(
                self.VERSION,
                self._state.name,
                self.metrics.plugins_loaded,
            )
        )

# ══════════════════════════════════════════════════════════════════════════════
# COMMAND LINE INTERFACE

# ══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="{} v{}".format(APP_NAME, VERSION),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py                   # Normal start\n"
            "  python main.py --debug           # Debug mode\n"
            "  python main.py --plugins-only    # List plugins and exit\n"
            "  python main.py --validate-config # Validate configuration\n"
        ),
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version="{} {}".format(APP_NAME, VERSION),
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable debug mode",
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        help="Path to configuration file",
    )
    parser.add_argument(
        "--plugins-only",
        action="store_true",
        help="List discovered plugins and exit",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate configuration and exit",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without GUI (for testing)",
    )
    return parser.parse_args()

def list_plugins() -> int:
    """Lista plugins och avsluta."""
    plugins_dir = PROJECT_ROOT / "plugins"
    _log.info("Plugins in %s:", plugins_dir)
    _log.info("")
    if not plugins_dir.exists():
        _log.error("  (directory does not exist)")
        return 1
    count = 0
    for item in sorted(plugins_dir.iterdir()):
        if item.is_dir() and not item.name.startswith("_"):
            plugin_file = item / "plugin.py"
            init_file = item / "__init__.py"
            # Samma detektering som PluginLoader: plugin.py ELLER __init__.py
            status = (
                "OK" if plugin_file.exists() or init_file.exists() else "FEL"
            )
            _log.info("  %s %s", status, item.name)
            count += 1
    _log.info("  Total: %s plugins", count)
    return 0

def validate_config(config_path: Optional[Path]) -> int:
    """Validera konfiguration och avsluta."""
    path = config_path or PROJECT_ROOT / "config.json"
    _log.info("Validating %s...", path)
    _log.info("")
    try:
        config = Configuration.load(path, use_env_override=True)
        errors = config.validate({
            "app_name": str,
            "plugins.enabled": list,
        })
        if errors:
            _log.error("Validation errors:")
            for error in errors:
                _log.error("  - %s", error)
            return 1
        _log.info("Configuration is valid")
        _log.info("  Keys: %s", len(config.to_dict()))
        _log.info(
            "  Plugins enabled: %s",
            len(config.get_list("plugins.enabled", [])),
        )
        return 0
    except ConfigError as exc:
        _log.error("Error: %s", exc)
        return 1

# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT

# ══════════════════════════════════════════════════════════════════════════════

def _setup_basic_stderr_logging() -> None:
    """Bootstrap-loggning till stderr innan riktig loggning är igång."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
        root.setLevel(logging.INFO)

def main() -> int:
    """Application entry point."""
    _setup_basic_stderr_logging()
    args = parse_args()
    if os.environ.get("APP_DEBUG", "").lower() in ("1", "true", "yes"):
        args.debug = True
    if args.plugins_only:
        return list_plugins()
    if args.validate_config:
        return validate_config(args.config)
    app = Application(
        config_path=args.config,
        debug=args.debug,
        headless=args.headless,
    )
    if not app._setup_single_instance():
        _log.info(
            "Another instance is already running; focusing it"
        )
        try:
            app.single_instance.focus_existing()
        except Exception as exc:
            _log.error("Could not focus existing instance: %s", exc)
        return 0
    try:
        exit_code = asyncio.run(app.start())
    except KeyboardInterrupt:
        exit_code = 130
    return exit_code

if __name__ == "__main__":
    sys.exit(main())
