# -*- coding: utf-8 -*-
# core/logger_setup.py
"""
Logger Setup Module v2.0.0 — AVANCERAD LOGGNING

Hanterar central loggkonfiguration för hela Transportstyrelsens
Fordonsregistreringssystem. Skapar rotationsvänliga loggfiler
(5MB x 3) i UTF-8-kodning uppdelade i kategorier.

PRINCIP v2.0.0: "LOGGA VARJE SAK"
    - ALLT som händer i systemet hamnar i debug.log (DEBUG-nivå,
      catch-all på root, 10MB x 5)
    - ALLA ohanterade exceptions fångas via sys.excepthook och
      threading.excepthook -> errors.log (inga silent crashes)
    - ALLA Python-warnings fångas (logging.captureWarnings)
      -> errors.log
    - Funktionsanrop kan loggas med @log_call (entry, argument,
      resultat, exekveringstid, exceptions)
    - Kodblock kan tidtas/loggas med LogContext
    - Varje session får unikt SESSION-ID som loggas i alla
      kategoriloggar vid start

ANSVAR:
    - Skapa och underhålla "logs/"-katalogen kraschsäkert.
    - Konfigurera separata loggfiler per kategori.
    - Global felsamlare (logs/errors.log) för WARNING+.
    - Global allt-samlare (logs/debug.log) för DEBUG+.
    - Kraschsäkra metoder: setup_logger, get_logger,
      setup_all_loggers.
    - Runtime-kontroll: enable_debug_mode, set_global_level.
    - Diagnostik: get_log_stats, shutdown_logging.

DOKUMENTATION AV KATEGORIER:
    - schema:       ts_schema_manager           (logs/schema.log)
    - import:       ts_spec_import, sap_import,
                    dispatch_viewer, color_import,
                    ts_excel_importer           (logs/import.log)
    - export:       ts_file_generator,
                    identity_post, end_post,
                    buntpost, reports           (logs/export.log)
    - gui:          ui/, main_gui, Qt           (logs/gui.log)
    - response:     response_viewer/handler     (logs/response.log)
    - errors:       Alla WARNING+ globalt       (logs/errors.log)
    - debug:        ALLT (DEBUG+) globalt       (logs/debug.log)
    - audit:        Lösenord, CRUD, PIN,
                    dealers_manager, sap_editor,
                    core_config                 (logs/audit.log)
    - vehicle:      vehicle_registry,
                    vin_registry, vin_tracking  (logs/vehicle.log)
    - plugins:      plugin_loader, plugin_base,
                    core/-moduler, about        (logs/plugins.log)
    - events:       event_bus                   (logs/events.log)
    - data_mapping: data_mapping plugin         (logs/data_mapping.log)

FÖRÄNDRINGAR v2.0.0:
    - KRASCHBUGG FIXAD: tempfile användes utan import
      (NameError i båda fallback-vägarna)
    - print() -> _bootstrap_report() via sys.stderr (spec: inga print)
    - NY: debug.log catch-all (DEBUG, 10MB x 5) — loggar VARJE sak
    - NY: install_exception_hooks() — sys.excepthook +
      threading.excepthook -> errors.log
    - NY: logging.captureWarnings(True) -> errors.log
    - NY: @log_call dekorator (entry/args/result/duration/exception)
    - NY: LogContext context manager (tidtagning av block)
    - NY: enable_debug_mode(), set_global_level()
    - NY: SESSION_ID + startbanner i alla kategoriloggar
    - NY: get_log_stats(), shutdown_logging()
    - LOGGER_MAPPINGS utökad till ALLA kända plugins
    - Dynamisk copyright

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import functools
import logging
import logging.handlers
import os
import sys
import tempfile
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Final, List, Optional, TypeVar

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "2.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"

LOGS_DIR: Final[str] = "logs"
MAX_LOG_SIZE: Final[int] = 5 * 1024 * 1024   # 5 MB per kategorilogg
DEBUG_LOG_SIZE: Final[int] = 10 * 1024 * 1024  # 10 MB för debug.log
BACKUP_COUNT: Final[int] = 3
DEBUG_BACKUP_COUNT: Final[int] = 5
LOG_ENCODING: Final[str] = "utf-8"

# Standardiserat format (timestamp + module + level + fil:rad + message)
LOG_FORMAT: Final[str] = (
    "%(asctime)s [%(name)s] [%(levelname)s] "
    "(%(filename)s:%(lineno)d) - %(message)s"
)
# Utökat format för debug.log (inkluderar tråd + funktion)
DEBUG_FORMAT: Final[str] = (
    "%(asctime)s.%(msecs)03d [%(name)s] [%(levelname)s] "
    "[%(threadName)s] (%(filename)s:%(lineno)d %(funcName)s) "
    "- %(message)s"
)
DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

# Unikt sessions-ID (loggas vid start i alla kategorier)
SESSION_ID: Final[str] = uuid.uuid4().hex[:12]

F = TypeVar("F", bound=Callable[..., Any])


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


def _bootstrap_report(message: str) -> None:
    """
    Nödrapportering INNAN loggsystemet är uppe.
    Spec förbjuder print() — skriver direkt till stderr.
    """
    try:
        sys.stderr.write(f"[logger_setup] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# LOGGER CATEGORY MAPPINGS (UTÖKAD v2.0.0 — alla kända plugins)
# ══════════════════════════════════════════════════════════════════════════════

LOGGER_MAPPINGS: Final[Dict[str, str]] = {
    # ── Schema log ──
    "schema": "schema.log",
    "ts_schema_manager": "schema.log",
    "ts_schema_manager.plugin": "schema.log",
    "ts_schema_manager.models": "schema.log",
    "ts_schema_manager.constants": "schema.log",
    "ts_schema_manager.version_manager": "schema.log",
    "ts_schema_manager.schema_store": "schema.log",
    "ts_schema_manager.schema_diff": "schema.log",
    "ts_schema_manager.widget": "schema.log",

    # ── Import log ──
    "import": "import.log",
    "ts_spec_import": "import.log",
    "sap_import": "import.log",
    "sap_import.plugin": "import.log",
    "sap_import.excel_reader": "import.log",
    "sap_import.column_resolver": "import.log",
    "sap_import.data_normalizer": "import.log",
    "dispatch_viewer": "import.log",
    "color_import": "import.log",
    "ts_excel_importer": "import.log",
    "vehicle_registry.excel_importer": "import.log",

    # ── Export log ──
    "export": "export.log",
    "ts_file_generator": "export.log",
    "ts_file_generator.plugin": "export.log",
    "ts_file_generator.record_builder": "export.log",
    "ts_file_generator.latin1_utils": "export.log",
    "identity_post": "export.log",
    "end_post": "export.log",
    "buntpost": "export.log",
    "reports": "export.log",
    "vehicle_registration_post": "export.log",

    # ── GUI / UI log ──
    "gui": "gui.log",
    "ui": "gui.log",
    "ui.theme_engine": "gui.log",
    "ui.main_window": "gui.log",
    "ui.tab_manager": "gui.log",
    "ui.tray_icon": "gui.log",
    "main_gui": "gui.log",
    "main_gui.plugin": "gui.log",
    "main_gui.vehicle_registry_page": "gui.log",
    "gui_helpers": "gui.log",

    # ── Response log ──
    "response": "response.log",
    "response_handler": "response.log",
    "response_viewer": "response.log",
    "response_viewer.plugin": "response.log",
    "ereko": "response.log",

    # ── Audit log (säkerhet, lösenord, CRUD, PIN, config) ──
    "audit": "audit.log",
    "dealers_manager": "audit.log",
    "dealers_manager.plugin": "audit.log",
    "dealers_manager.password_manager": "audit.log",
    "sap_editor": "audit.log",
    "sap_editor.editor_window": "audit.log",
    "core_config": "audit.log",
    "core_auth": "audit.log",

    # ── Vehicle log ──
    "vehicle": "vehicle.log",
    "vehicle_registry": "vehicle.log",
    "data_mapping.vin_registry": "vehicle.log",
    "plugins.vin_tracking": "vehicle.log",
    "vin_tracking": "vehicle.log",

    # ── Plugins log (core + plugin-infrastruktur) ──
    "plugins": "plugins.log",
    "core": "plugins.log",
    "core.plugin_loader": "plugins.log",
    "core.plugin_base": "plugins.log",
    "core.app": "plugins.log",
    "core.application": "plugins.log",
    "core.config": "plugins.log",
    "core.settings_manager": "plugins.log",
    "core.single_instance": "plugins.log",
    "core.cache_manager": "plugins.log",
    "core.autostart": "plugins.log",
    "core_logger": "plugins.log",
    "about": "plugins.log",
    "about.plugin": "plugins.log",
    "data_viewer": "plugins.log",
    "colors_manager": "plugins.log",
    "ts_spec_viewer": "plugins.log",

    # ── Events log ──
    "events": "events.log",
    "core.event_bus": "events.log",

    # ── Data mapping log ──
    "data_mapping": "data_mapping.log",
    "data_mapping.plugin": "data_mapping.log",
    "data_mapping.column_mapping_service": "data_mapping.log",
    "data_mapping.widget": "data_mapping.log",
}


# ══════════════════════════════════════════════════════════════════════════════
# CENTRAL LOGGER SETUP ENGINE
# ══════════════════════════════════════════════════════════════════════════════

# Internt register för att hålla koll på alla initierade handlers
_initialized_handlers: Dict[str, logging.Handler] = {}
_setup_lock = threading.RLock()
_hooks_installed = False


def _resolve_logs_dir() -> Path:
    """Lös logs-katalog kraschsäkert med tempdir-fallback."""
    logs_dir_path = Path(LOGS_DIR)
    try:
        logs_dir_path.mkdir(exist_ok=True, parents=True)
        return logs_dir_path
    except Exception as exc:
        _bootstrap_report(f"Kunde inte skapa logs-katalog: {exc}")
        fallback = Path(tempfile.gettempdir()) / "ts_vehicle_system_logs"
        try:
            fallback.mkdir(exist_ok=True, parents=True)
        except Exception:
            pass
        return fallback


def setup_logger(
    name: str,
    log_file: Optional[str] = None,
    level: int = logging.DEBUG,
) -> logging.Logger:
    """
    Initiera och konfigurera en specifik logger kraschsäkert.
    Säkerställer roterande loggfiler (5MB x 3), UTF-8-kodning
    och korrekt formatering.

    v2.0.0: Default-nivå är DEBUG (logga varje sak) — handlers
    filtrerar. Loggern propagerar till root så att debug.log och
    errors.log alltid fångar allt.

    Args:
        name: Loggerns namn (t.ex. 'core.event_bus')
        log_file: Specifik loggfil (None = via LOGGER_MAPPINGS)
        level: Loggningsnivå (default: DEBUG)

    Returns:
        logging.Logger-instans
    """
    with _setup_lock:
        log = logging.getLogger(name)
        log.setLevel(level)
        # Propagerar till root för global samling
        # (debug.log + errors.log)
        log.propagate = True

        # Undvik dubbla handlers om loggern redan är konfigurerad
        if log.handlers:
            return log

        # Bestäm filnamn
        if not log_file:
            log_file = LOGGER_MAPPINGS.get(
                name, f"{name.split('.')[0]}.log"
            )

        logs_dir_path = _resolve_logs_dir()
        log_path = logs_dir_path / log_file

        try:
            # Återanvänd existerande handler för samma fil
            # (undviker fildelningstvister på Windows)
            file_key = str(log_path.resolve())
            if file_key in _initialized_handlers:
                log.addHandler(_initialized_handlers[file_key])
            else:
                handler = logging.handlers.RotatingFileHandler(
                    log_path,
                    maxBytes=MAX_LOG_SIZE,
                    backupCount=BACKUP_COUNT,
                    encoding=LOG_ENCODING,
                )
                handler.setFormatter(
                    logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
                )
                handler.setLevel(logging.DEBUG)
                log.addHandler(handler)
                _initialized_handlers[file_key] = handler

        except Exception as exc:
            # Kris-fallback till ström-logger
            _bootstrap_report(
                f"Filhandler misslyckades för '{name}': {exc}"
            )
            console = logging.StreamHandler()
            console.setFormatter(
                logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
            )
            log.addHandler(console)

        return log


def get_logger(name: str) -> logging.Logger:
    """
    Kraschsäker genväg för att hämta en konfigurerad logger.
    Om loggern inte har ställts in, konfigureras den automatiskt.

    Args:
        name: Loggerns namn

    Returns:
        logging.Logger
    """
    log = logging.getLogger(name)
    if not log.handlers:
        return setup_logger(name)
    return log


# ══════════════════════════════════════════════════════════════════════════════
# GLOBALA HOOKS — FÅNGA ALLT (NY v2.0.0)
# ══════════════════════════════════════════════════════════════════════════════

def install_exception_hooks() -> None:
    """
    Installera globala exception-hooks så att ALLA ohanterade
    exceptions loggas till errors.log (via root) — även från
    bakgrundstrådar. Inga silent crashes.
    """
    global _hooks_installed
    if _hooks_installed:
        return

    root = logging.getLogger()

    def _sys_hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            # Låt Ctrl+C bete sig normalt
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        root.critical(
            "OHANTERAT UNDANTAG (main thread): %s",
            exc_value,
            exc_info=(exc_type, exc_value, exc_tb),
        )

    def _thread_hook(args):
        root.critical(
            "OHANTERAT UNDANTAG (tråd '%s'): %s",
            args.thread.name if args.thread else "?",
            args.exc_value,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    try:
        sys.excepthook = _sys_hook
    except Exception as exc:
        _bootstrap_report(f"Kunde inte sätta sys.excepthook: {exc}")

    try:
        threading.excepthook = _thread_hook
    except Exception as exc:
        _bootstrap_report(f"Kunde inte sätta threading.excepthook: {exc}")

    # Fånga Python-warnings -> logging (py.warnings -> root -> errors)
    try:
        logging.captureWarnings(True)
        warn_log = logging.getLogger("py.warnings")
        warn_log.setLevel(logging.WARNING)
    except Exception as exc:
        _bootstrap_report(f"Kunde inte aktivera captureWarnings: {exc}")

    _hooks_installed = True


def setup_all_loggers(
    console_level: int = logging.INFO,
    debug_log_enabled: bool = True,
) -> None:
    """
    Initierar och sätter upp HELA loggsystemet:

      1. logs/-katalogen (med tempdir-fallback)
      2. Root-logger på DEBUG (allt propagerar hit)
      3. Console-handler (default INFO, konfigurerbar)
      4. logs/errors.log  — WARNING+ globalt (felsamlare)
      5. logs/debug.log   — DEBUG+  globalt (ALLT, 10MB x 5)
      6. Exception-hooks (sys + threading) + captureWarnings
      7. Alla kategoriloggar för-registreras
      8. Startbanner med SESSION_ID i alla kategoriloggar

    Args:
        console_level: Nivå för konsolutskrift (default INFO)
        debug_log_enabled: Aktivera catch-all debug.log
    """
    with _setup_lock:
        # 1. Säkerställ logs-katalogen
        logs_dir_path = _resolve_logs_dir()

        # 2. Konfigurera global root-logger — DEBUG fångar ALLT
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        # Rensa gamla handlers på root (omstarter/tester)
        for h in list(root_logger.handlers):
            root_logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

        # 3. Console-handler för utveckling/debug
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        )
        console_handler.setLevel(console_level)
        root_logger.addHandler(console_handler)

        # 4. Central felsamlare (logs/errors.log) — WARNING+
        try:
            errors_path = logs_dir_path / "errors.log"
            errors_handler = logging.handlers.RotatingFileHandler(
                errors_path,
                maxBytes=MAX_LOG_SIZE,
                backupCount=BACKUP_COUNT,
                encoding=LOG_ENCODING,
            )
            errors_handler.setFormatter(
                logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
            )
            errors_handler.setLevel(logging.WARNING)
            root_logger.addHandler(errors_handler)
            _initialized_handlers[str(errors_path.resolve())] = (
                errors_handler
            )
        except Exception as exc:
            _bootstrap_report(f"Kunde inte binda errors.log: {exc}")

        # 5. Global allt-samlare (logs/debug.log) — DEBUG+ (NY v2.0.0)
        if debug_log_enabled:
            try:
                debug_path = logs_dir_path / "debug.log"
                debug_handler = logging.handlers.RotatingFileHandler(
                    debug_path,
                    maxBytes=DEBUG_LOG_SIZE,
                    backupCount=DEBUG_BACKUP_COUNT,
                    encoding=LOG_ENCODING,
                )
                debug_handler.setFormatter(
                    logging.Formatter(DEBUG_FORMAT, datefmt=DATE_FORMAT)
                )
                debug_handler.setLevel(logging.DEBUG)
                root_logger.addHandler(debug_handler)
                _initialized_handlers[str(debug_path.resolve())] = (
                    debug_handler
                )
            except Exception as exc:
                _bootstrap_report(f"Kunde inte binda debug.log: {exc}")

        # 6. Globala hooks — fånga ohanterade exceptions + warnings
        install_exception_hooks()

        # 7. För-registrera alla definierade kategorier kraschsäkert
        for logger_name, log_file in LOGGER_MAPPINGS.items():
            try:
                setup_logger(logger_name, log_file)
            except Exception as exc:
                _bootstrap_report(
                    f"Kunde inte initiera logger "
                    f"'{logger_name}': {exc}"
                )

        # 8. Startbanner med SESSION_ID i alla kategoriloggar
        start_msg = (
            f"=== SYSTEM STARTUP | session={SESSION_ID} | "
            f"{datetime.now().isoformat()} | "
            f"logger_setup v{VERSION} | {get_copyright_string()} ==="
        )
        banner_categories = sorted(set(LOGGER_MAPPINGS.values()))
        logged_files: set = set()
        for logger_name, log_file in LOGGER_MAPPINGS.items():
            if log_file in logged_files:
                continue
            try:
                get_logger(logger_name).info(start_msg)
                logged_files.add(log_file)
            except Exception:
                pass
            if len(logged_files) >= len(banner_categories):
                break

        root_logger.info(start_msg)


# ══════════════════════════════════════════════════════════════════════════════
# RUNTIME-KONTROLL (NY v2.0.0)
# ══════════════════════════════════════════════════════════════════════════════

def set_global_level(level: int) -> None:
    """
    Sätt loggnivå på root-loggerns CONSOLE-handler vid runtime.
    Filhandlers (debug.log/errors.log/kategorier) påverkas EJ —
    de fortsätter logga allt enligt sina nivåer.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.handlers.RotatingFileHandler
        ):
            handler.setLevel(level)
    root.info(
        "Console-loggnivå ändrad till %s",
        logging.getLevelName(level),
    )


def enable_debug_mode() -> None:
    """Aktivera DEBUG-utskrift även i konsolen (DEV-läge)."""
    set_global_level(logging.DEBUG)


def disable_debug_mode() -> None:
    """Återgå till INFO-utskrift i konsolen (PROD-läge)."""
    set_global_level(logging.INFO)


# ══════════════════════════════════════════════════════════════════════════════
# FUNKTIONSANROPS-LOGGNING (NY v2.0.0 — "logga varje sak")
# ══════════════════════════════════════════════════════════════════════════════

def log_call(
    logger_name: Optional[str] = None,
    log_args: bool = True,
    log_result: bool = False,
    level: int = logging.DEBUG,
) -> Callable[[F], F]:
    """
    Dekorator som loggar varje anrop till en funktion:
    entry (+ argument), exit (+ ev. resultat), exekveringstid
    samt exceptions (med full traceback).

    Användning:
        @log_call()
        def min_funktion(x, y): ...

        @log_call("data_mapping", log_result=True)
        def match(df): ...

    Args:
        logger_name: Logger att använda (None = funktionens modul)
        log_args: Logga positionella/keyword-argument
        log_result: Logga returvärdet (trunkeras till 200 tecken)
        level: Loggnivå för entry/exit (default DEBUG)
    """
    def decorator(func: F) -> F:
        log = get_logger(logger_name or func.__module__)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if log_args:
                try:
                    arg_repr = ", ".join(
                        [repr(a)[:80] for a in args]
                        + [f"{k}={repr(v)[:80]}" for k, v in kwargs.items()]
                    )
                except Exception:
                    arg_repr = "<repr-fel>"
                log.log(
                    level, "→ %s(%s)", func.__qualname__, arg_repr,
                )
            else:
                log.log(level, "→ %s()", func.__qualname__)

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                log.error(
                    "✗ %s kastade %s efter %.1fms: %s",
                    func.__qualname__,
                    type(exc).__name__,
                    elapsed,
                    exc,
                    exc_info=True,
                )
                raise

            elapsed = (time.perf_counter() - start) * 1000
            if log_result:
                try:
                    res_repr = repr(result)[:200]
                except Exception:
                    res_repr = "<repr-fel>"
                log.log(
                    level, "← %s (%.1fms) = %s",
                    func.__qualname__, elapsed, res_repr,
                )
            else:
                log.log(
                    level, "← %s (%.1fms)",
                    func.__qualname__, elapsed,
                )
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


class LogContext:
    """
    Context manager som loggar start/slut/tid för ett kodblock.
    Exceptions loggas med traceback och re-raisas.

    Användning:
        with LogContext("Importerar Excel", "import"):
            ...tung operation...
    """

    def __init__(
        self,
        description: str,
        logger_name: str = "plugins",
        level: int = logging.INFO,
    ) -> None:
        self.description = description
        self.log = get_logger(logger_name)
        self.level = level
        self._start: float = 0.0

    def __enter__(self) -> "LogContext":
        self._start = time.perf_counter()
        self.log.log(self.level, "▶ START: %s", self.description)
        return self

    def __exit__(self, exc_type, exc_value, exc_tb) -> bool:
        elapsed = (time.perf_counter() - self._start) * 1000
        if exc_type is not None:
            self.log.error(
                "✗ FEL: %s efter %.1fms — %s: %s",
                self.description,
                elapsed,
                exc_type.__name__,
                exc_value,
                exc_info=(exc_type, exc_value, exc_tb),
            )
            return False  # re-raise
        self.log.log(
            self.level, "✔ KLART: %s (%.1fms)",
            self.description, elapsed,
        )
        return False


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIK & SHUTDOWN (NY v2.0.0)
# ══════════════════════════════════════════════════════════════════════════════

def get_log_stats() -> Dict[str, Any]:
    """
    Returnera statistik om alla loggfiler (storlek, antal,
    senaste ändring). Kraschsäker.
    """
    stats: Dict[str, Any] = {
        "session_id": SESSION_ID,
        "version": VERSION,
        "logs_dir": str(_resolve_logs_dir()),
        "handlers": len(_initialized_handlers),
        "files": {},
        "total_size_bytes": 0,
    }
    try:
        logs_dir = _resolve_logs_dir()
        for fp in sorted(logs_dir.glob("*.log*")):
            try:
                st = fp.stat()
                stats["files"][fp.name] = {
                    "size_bytes": st.st_size,
                    "modified": datetime.fromtimestamp(
                        st.st_mtime
                    ).isoformat(timespec="seconds"),
                }
                stats["total_size_bytes"] += st.st_size
            except Exception:
                pass
    except Exception:
        pass
    return stats


def shutdown_logging() -> None:
    """
    Flusha och stäng alla handlers kontrollerat vid app-exit.
    Loggar avslutningsbanner först. Kraschar ALDRIG.
    """
    try:
        end_msg = (
            f"=== SYSTEM SHUTDOWN | session={SESSION_ID} | "
            f"{datetime.now().isoformat()} ==="
        )
        logging.getLogger().info(end_msg)
    except Exception:
        pass
    try:
        logging.shutdown()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "setup_logger",
    "get_logger",
    "setup_all_loggers",
    "install_exception_hooks",
    "set_global_level",
    "enable_debug_mode",
    "disable_debug_mode",
    "log_call",
    "LogContext",
    "get_log_stats",
    "shutdown_logging",
    "LOGS_DIR",
    "SESSION_ID",
    "LOGGER_MAPPINGS",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]