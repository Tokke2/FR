# -*- coding: utf-8 -*-
# core/__init__.py
"""
Kärnmoduler för Transportstyrelsen Fordonsregistreringssystem.

Innehåller:
    - Application: Applikationens livscykel
    - EventBus: Pub/Sub event-system för plugin-kommunikation
    - PluginBase: Abstrakt basklass för alla plugins
    - PluginLoader: Dynamisk plugin-laddning, dependency resolution
    - Configuration: Centraliserad konfigurationshantering
    - SettingsManager: Bakåtkompatibel settings-wrapper
    - logger_setup: Central loggkonfiguration (avancerad loggning)
    - Exceptions: Centraliserade exceptions för hela systemet

Version: 3.1.0
Python: 3.12+ (senaste stabila LTS enligt spec)

ALLA importer är lazy (via __getattr__) för att undvika cirkulära
beroenden och hålla uppstart snabb. Importera direkt från core:

    from core import EventBus, PluginBase, PluginLoader

    bus = EventBus()
    loader = PluginLoader(plugins_dir="plugins", event_bus=bus)
    plugins = await loader.load_all()
    await loader.initialize_all()
    await loader.activate_all()

ARKITEKTUR (översikt):
    Application Layer:  plugins/ (main_gui, sap_import,
                        ts_file_generator, ...)
    Core Layer:         EventBus (pub/sub, prioritet, trådsäker)
                        PluginBase (lifecycle, screen, events)
                        PluginLoader (dynamisk laddning, deps)
                        Configuration (settings, scheman,
                        validering)
                        logger_setup (kategoriloggar, debug.log,
                        exception-hooks)

FÖRÄNDRINGAR v3.1.0:
    - KORRUPT FIL KONSOLIDERAD: två hopklistrade __init__-versioner
      (lazy v3.0.0 + eager v2.0.0) sammanslagna till EN lazy version
    - __author__ -> Rickard Längkvist (var "Filregistrering Team")
    - Python-krav höjt till 3.12 (spec: senaste stabila LTS)
    - tkinter-check borttagen (FÖRBJUDET enligt spec — PySide6 ONLY),
      ersatt med PySide6-check
    - FIXAD lazy-importväg: PluginLoadError/PluginInitError/
      PluginActivationError/DependencyError importeras nu från
      core.exceptions (inte core.plugin_loader)
    - NYA lazy-exporter: Application, Events, LoadState, LoadResult,
      PluginMetrics, get_config, load_config, SettingsManager,
      ValidationError, PluginInitError, PluginActivationError,
      setup_logger, get_logger, setup_all_loggers, log_call,
      LogContext, install_exception_hooks, shutdown_logging,
      SESSION_ID
    - _core_logger -> _log (spec-konvention)
    - Dynamisk copyright

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Union

# ══════════════════════════════════════════════════════════════════════════════
# VERSION INFORMATION
# ══════════════════════════════════════════════════════════════════════════════

__version__ = "3.1.0"
__author__ = "Rickard Längkvist"
__python_requires__ = ">=3.12"

VERSION_INFO = {
    "major": 3,
    "minor": 1,
    "patch": 0,
    "release": "stable",
    "build": None,
}


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {__author__}"


# ══════════════════════════════════════════════════════════════════════════════
# PYTHON VERSION CHECK (spec: Python 3.12.x LTS)
# ══════════════════════════════════════════════════════════════════════════════

if sys.version_info < (3, 12):
    raise RuntimeError(
        f"Transportstyrelsen Fordonsregistreringssystem kräver "
        f"Python 3.12+, du kör Python "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# MODULE LOGGER (spec-konvention: _log)
# ══════════════════════════════════════════════════════════════════════════════

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())  # Default: no output
# Aktiveras via: logging.getLogger("core").setLevel(logging.DEBUG)


# ══════════════════════════════════════════════════════════════════════════════
# TYPE CHECKING IMPORTS (endast för statisk analys)
# ══════════════════════════════════════════════════════════════════════════════

if TYPE_CHECKING:
    from core.application import Application
    from core.event_bus import EventBus, Priority, Events
    from core.plugin_base import (
        PluginBase,
        PluginMetadata,
        PluginState,
        HealthStatus,
        ScreenCategory,
        ScreenConfig,
        ScreenChangeEvent,
        WindowEvent,
        UIComponent,
        WindowManager,
    )
    from core.plugin_loader import (
        PluginLoader,
        PluginInfo,
        PluginMetrics,
        LoadState,
        LoadResult,
    )
    from core.config import (
        Configuration,
        ConfigSchema,
        get_config,
        load_config,
    )
    from core.settings_manager import SettingsManager
    from core.exceptions import (
        CoreError,
        PluginError,
        PluginLoadError,
        PluginInitError,
        PluginActivationError,
        DependencyError,
        EventError,
        ConfigError,
        ConfigurationError,
        ValidationError,
    )
    from core.logger_setup import (
        setup_logger,
        get_logger,
        setup_all_loggers,
        install_exception_hooks,
        log_call,
        LogContext,
        shutdown_logging,
    )


# ══════════════════════════════════════════════════════════════════════════════
# LAZY IMPORT TABLE (attribut -> (modul, namn))
# ══════════════════════════════════════════════════════════════════════════════

_LAZY_IMPORTS: Dict[str, tuple] = {
    # Application
    "Application": ("core.application", "Application"),

    # EventBus och relaterade
    "EventBus": ("core.event_bus", "EventBus"),
    "Priority": ("core.event_bus", "Priority"),
    "Events": ("core.event_bus", "Events"),

    # PluginBase och relaterade
    "PluginBase": ("core.plugin_base", "PluginBase"),
    "PluginMetadata": ("core.plugin_base", "PluginMetadata"),
    "PluginState": ("core.plugin_base", "PluginState"),
    "HealthStatus": ("core.plugin_base", "HealthStatus"),
    "ScreenCategory": ("core.plugin_base", "ScreenCategory"),
    "ScreenConfig": ("core.plugin_base", "ScreenConfig"),
    "ScreenChangeEvent": ("core.plugin_base", "ScreenChangeEvent"),
    "WindowEvent": ("core.plugin_base", "WindowEvent"),
    "UIComponent": ("core.plugin_base", "UIComponent"),
    "WindowManager": ("core.plugin_base", "WindowManager"),

    # PluginLoader och relaterade
    "PluginLoader": ("core.plugin_loader", "PluginLoader"),
    "PluginInfo": ("core.plugin_loader", "PluginInfo"),
    "PluginMetrics": ("core.plugin_loader", "PluginMetrics"),
    "LoadState": ("core.plugin_loader", "LoadState"),
    "LoadResult": ("core.plugin_loader", "LoadResult"),
    "create_loader": ("core.plugin_loader", "create_loader"),

    # Configuration och relaterade
    "Configuration": ("core.config", "Configuration"),
    "ConfigSchema": ("core.config", "ConfigSchema"),
    "get_config": ("core.config", "get_config"),
    "load_config": ("core.config", "load_config"),

    # Settings (bakåtkompatibel wrapper)
    "SettingsManager": ("core.settings_manager", "SettingsManager"),

    # Exceptions (FIXAT v3.1.0: korrekt källa = core.exceptions)
    "CoreError": ("core.exceptions", "CoreError"),
    "PluginError": ("core.exceptions", "PluginError"),
    "PluginLoadError": ("core.exceptions", "PluginLoadError"),
    "PluginInitError": ("core.exceptions", "PluginInitError"),
    "PluginActivationError": (
        "core.exceptions", "PluginActivationError",
    ),
    "DependencyError": ("core.exceptions", "DependencyError"),
    "EventError": ("core.exceptions", "EventError"),
    "ConfigError": ("core.exceptions", "ConfigError"),
    "ConfigurationError": ("core.exceptions", "ConfigurationError"),
    "ValidationError": ("core.exceptions", "ValidationError"),

    # Logger setup (NY v3.1.0)
    "setup_logger": ("core.logger_setup", "setup_logger"),
    "get_logger": ("core.logger_setup", "get_logger"),
    "setup_all_loggers": ("core.logger_setup", "setup_all_loggers"),
    "install_exception_hooks": (
        "core.logger_setup", "install_exception_hooks",
    ),
    "log_call": ("core.logger_setup", "log_call"),
    "LogContext": ("core.logger_setup", "LogContext"),
    "shutdown_logging": ("core.logger_setup", "shutdown_logging"),
    "SESSION_ID": ("core.logger_setup", "SESSION_ID"),
}


def __getattr__(name: str) -> Any:
    """
    Lazy import för core-moduler.
    Importerar endast när attributet faktiskt används.
    Undviker cirkulära beroenden och håller uppstarten snabb.
    """
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        try:
            import importlib
            module = importlib.import_module(module_path)
            value = getattr(module, attr_name)
            # Cacha på modulnivå så __getattr__ inte körs igen
            globals()[name] = value
            return value
        except ImportError as exc:
            raise AttributeError(
                f"module '{__name__}' attribute '{name}' could not "
                f"be loaded from {module_path}: {exc}"
            ) from exc
        except AttributeError as exc:
            raise AttributeError(
                f"module '{module_path}' has no attribute "
                f"'{attr_name}': {exc}"
            ) from exc

    # Utility functions (definierade lokalt)
    if name == "get_version":
        return get_version
    if name == "get_core_path":
        return get_core_path
    if name == "get_copyright_string":
        return get_copyright_string

    raise AttributeError(
        f"module '{__name__}' has no attribute '{name}'"
    )


def __dir__() -> list:
    """Returnera alla tillgängliga attribut (för IDE/dir())."""
    return sorted(
        set(list(globals().keys()) + list(_LAZY_IMPORTS.keys()))
    )


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_version(as_string: bool = True) -> Union[str, dict]:
    """
    Hämta version-information.

    Args:
        as_string: Om True, returnera som string, annars som dict

    Returns:
        Version som string eller dict

    Exempel:
        >>> get_version()
        '3.1.0'
        >>> get_version(as_string=False)
        {'major': 3, 'minor': 1, 'patch': 0, ...}
    """
    if as_string:
        version = (
            f"{VERSION_INFO['major']}."
            f"{VERSION_INFO['minor']}."
            f"{VERSION_INFO['patch']}"
        )
        if VERSION_INFO.get("build"):
            version += f"+{VERSION_INFO['build']}"
        return version
    return VERSION_INFO.copy()


def get_core_path() -> Path:
    """
    Hämta sökväg till core-katalogen.

    Returns:
        Path-objekt till core/

    Exempel:
        >>> core_path = get_core_path()
        >>> settings = core_path.parent / "settings.json"
    """
    return Path(__file__).parent


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP DIAGNOSTICS
# ══════════════════════════════════════════════════════════════════════════════

def _run_startup_checks() -> None:
    """
    Kör grundläggande startup-kontroller.
    Loggar varningar om något är fel. Kraschar ALDRIG.

    FIXAT v3.1.0: tkinter-check borttagen (FÖRBJUDET enligt spec,
    PySide6 ONLY) — ersatt med PySide6-tillgänglighetskontroll.
    """
    # Kolla att PySide6 finns (spec: UI = PySide6)
    try:
        import PySide6  # noqa: F401
    except ImportError:
        warnings.warn(
            "PySide6 not available - GUI will not work "
            "(pip install PySide6)",
            RuntimeWarning,
        )

    # Kolla core-struktur
    core_path = get_core_path()
    required_files = [
        "event_bus.py",
        "plugin_base.py",
        "plugin_loader.py",
        "exceptions.py",
        "logger_setup.py",
    ]

    for filename in required_files:
        if not (core_path / filename).exists():
            warnings.warn(
                f"Core file missing: {filename}",
                RuntimeWarning,
            )

    _log.debug(
        "Core initialized: version=%s python=%s.%s core_path=%s",
        __version__,
        sys.version_info.major,
        sys.version_info.minor,
        core_path,
    )


# Kör startup checks vid import
_run_startup_checks()


# ══════════════════════════════════════════════════════════════════════════════
# __all__ - EXPLICIT EXPORT LIST
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Version & utilities
    "__version__",
    "VERSION_INFO",
    "get_version",
    "get_core_path",
    "get_copyright_string",

    # Application
    "Application",

    # EventBus
    "EventBus",
    "Priority",
    "Events",

    # PluginBase
    "PluginBase",
    "PluginMetadata",
    "PluginState",
    "HealthStatus",

    # Screen Management
    "ScreenCategory",
    "ScreenConfig",
    "ScreenChangeEvent",
    "WindowEvent",
    "UIComponent",
    "WindowManager",

    # Plugin Loader
    "PluginLoader",
    "PluginInfo",
    "PluginMetrics",
    "LoadState",
    "LoadResult",
    "create_loader",

    # Configuration
    "Configuration",
    "ConfigSchema",
    "get_config",
    "load_config",
    "SettingsManager",

    # Exceptions
    "CoreError",
    "PluginError",
    "PluginLoadError",
    "PluginInitError",
    "PluginActivationError",
    "DependencyError",
    "EventError",
    "ConfigError",
    "ConfigurationError",
    "ValidationError",

    # Logger setup
    "setup_logger",
    "get_logger",
    "setup_all_loggers",
    "install_exception_hooks",
    "log_call",
    "LogContext",
    "shutdown_logging",
    "SESSION_ID",
]