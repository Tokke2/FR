# plugins/core_logger/plugin.py
# -*- coding: utf-8 -*-
"""
Core Logger Plugin v3.0.0

Central logghantering för hela systemet med avancerad event-driven arkitektur.

Copyright © 2024-{current_year} Rickard Längkvist, TADEGA AB
Alla rättigheter förbehållna.

UPPDATERINGAR v3.0.0:
    - Samarbetar med ts_schema_manager, ts_spec_import och alla plugins
    - Loggar ALLT: schema-events, import, generering, GUI-navigation, fel
    - Plugin-specifika loggers (varje plugin får egen loggfil)
    - Event audit trail (full historik av alla systemhändelser)
    - Strukturerad JSON-loggning för analys
    - Avancerad roterande loggning (storlek + tid + gzip)
    - Dynamiskt år i copyright
    - Framtidssäker design för nya posttyper och plugins
    - Robust mot cirkulära imports och saknade beroenden
    
Huvudfunktioner:
    - Roterande loggfiler (storlek/tid)
    - Gzip-komprimering av gamla loggar
    - JSON-format för strukturerad loggning
    - Färgad konsolutskrift
    - Multipla loggers (per plugin)
    - Event-driven loggning (lyssnar på alla system-events)
    - Auto-loggning av flikbyten i GUI
    - Schema-change tracking
    - Import/export audit trail
"""

from __future__ import annotations

import gzip
import json
import logging
import logging.handlers
import os
import platform
import shutil
import sys
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union, Callable

# Importera PluginBase direkt (inte via relativ import)
try:
    from core.plugin_base import PluginBase
except ImportError:
    # Fallback om core inte finns i path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from core.plugin_base import PluginBase


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# Copyright info - dynamiskt år
AUTHOR = "Rickard Längkvist"
COMPANY = "TADEGA AB"
COPYRIGHT_YEAR_START = 2024

def get_copyright_year() -> int:
    """Hämta aktuellt år för copyright."""
    return datetime.now().year

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    current_year = get_copyright_year()
    if current_year > COPYRIGHT_YEAR_START:
        return f"Copyright © {COPYRIGHT_YEAR_START}-{current_year} {AUTHOR}, {COMPANY}"
    return f"Copyright © {COPYRIGHT_YEAR_START} {AUTHOR}, {COMPANY}"

# Logger-namn för olika system-komponenter
SYSTEM_LOGGERS = {
    "app": "AppLogger",
    "core": "CoreLogger",
    "plugins": "PluginLogger",
    "events": "EventLogger",
    "schema": "SchemaLogger",
    "import": "ImportLogger",
    "export": "ExportLogger",
    "gui": "GUILogger",
    "errors": "ErrorLogger",
    "audit": "AuditLogger",
    "ts_file": "TSFileLogger",
    "vehicle": "VehicleLogger",
    "response": "ResponseLogger",
}

# Event-kategorier att logga
EVENT_CATEGORIES = {
    # Schema events (nya + legacy)
    "schema": [
        "ts:schema:loaded", 
        "ts:schema:version_changed", 
        "ts:schema:updated",
        "ts:schema:created",
        "ts_spec:activated",
        "ts_spec:version_changed",
        "ts_spec:imported",
        "schema:loaded", 
        "schema:version_changed",
    ],
    
    # Import/Export events
    "import": [
        "ts:import:started", 
        "ts:import:completed", 
        "ts:import:failed",
        "sap:import:started", 
        "sap:import:completed",
        "sap:import:failed",
        "dispatch:import:started", 
        "dispatch:import:completed",
        "dispatch:import:failed",
        "excel:import:started",
        "excel:import:completed",
    ],
    
    # File generation events
    "generation": [
        "ts:file:generated", 
        "ts:file:failed", 
        "ts:file:validation_error",
        "ts:file:started",
        "ts:file:preview",
        "ts:record:formatted",
    ],
    
    # Response events
    "response": [
        "response:received", 
        "response:parsed", 
        "response:error",
        "response:file_detected",
        "response:status_updated",
    ],
    
    # GUI events
    "gui": [
        "gui:tab_changed", 
        "gui:page_loaded", 
        "gui:dialog_opened",
        "gui:dialog_closed",
        "gui:action_triggered",
        "gui:button_clicked",
        "gui:form_submitted",
        "gui:table_selected",
        "gui:initialized",
        "main_gui:ready",
    ],
    
    # Plugin lifecycle
    "plugin": [
        "plugin:loaded", 
        "plugin:activated", 
        "plugin:deactivated",
        "plugin:initialized",
        "plugin:error",
        "plugin:warning",
    ],
    
    # Data events
    "data": [
        "data:saved", 
        "data:loaded", 
        "data:updated", 
        "data:deleted",
        "data:validated",
        "data:error",
        "vehicle:registered",
        "vehicle:updated",
        "vehicle:status_changed",
    ],
    
    # Error events
    "error": [
        "error:occurred", 
        "error:handled", 
        "error:unhandled",
        "error:validation",
        "error:critical",
    ],
    
    # System events
    "system": [
        "app:started",
        "app:shutdown",
        "config:loaded",
        "config:saved",
        "config:changed",
    ],
}

# Log levels mapping
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS (för samarbete med andra plugins)
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Robust plugin-hämtning som fungerar oavsett app-konfiguration.
    
    Args:
        app: Applikationsobjektet
        name: Plugin-namn
        
    Returns:
        Plugin-instans eller None
    """
    if app is None:
        return None
    
    # Metod 1: app.get_plugin()
    try:
        if hasattr(app, 'get_plugin') and callable(app.get_plugin):
            result = app.get_plugin(name)
            if result is not None:
                return result
    except Exception:
        pass
    
    # Metod 2: app.plugin_loader.get_plugin()
    try:
        loader = getattr(app, 'plugin_loader', None)
        if loader and hasattr(loader, 'get_plugin'):
            result = loader.get_plugin(name)
            if result is not None:
                return result
    except Exception:
        pass
    
    # Metod 3: direktattribut
    try:
        attr_name = name.replace("-", "_").lower()
        if hasattr(app, attr_name):
            return getattr(app, attr_name)
    except Exception:
        pass
    
    return None


def get_event_bus(app: Any) -> Optional[Any]:
    """
    Hämta event bus från app.
    
    Args:
        app: Applikationsobjektet
        
    Returns:
        Event bus eller None
    """
    if app is None:
        return None
    
    if hasattr(app, 'event_bus') and app.event_bus is not None:
        return app.event_bus
    
    if hasattr(app, 'events') and app.events is not None:
        return app.events
    
    return None


def emit_event_safe(app: Any, event_name: str, data: Dict[str, Any] = None) -> bool:
    """
    Emit event säkert (utan att krascha om event bus saknas).
    
    Args:
        app: Applikationsobjektet
        event_name: Event-namn
        data: Event-data
        
    Returns:
        True om event emitterades, False annars
    """
    bus = get_event_bus(app)
    if bus is None:
        return False
    
    try:
        bus.emit(event_name, data or {})
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# INBYGGD KONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class LoggerConfig:
    """
    Konfiguration för en logger.
    
    Attributes:
        name: Logger-namn
        log_file: Loggfil-sökväg (None = endast konsol)
        file_level: Loggnivå för fil
        console_level: Loggnivå för konsol
        max_bytes: Max filstorlek före rotation
        backup_count: Antal backup-filer
        compress: Komprimera roterade filer
        json_format: Använd JSON-formatering
        date_in_filename: Datumsuffix för filnamn
        encoding: Teckenkodning
        log_format: Log-format-sträng
        date_format: Datumformat
        include_system_info: Logga systeminformation vid start
        track_events: Lista med event-kategorier att logga
    """
    name: str = "AppLogger"
    log_file: Optional[Path] = None
    file_level: int = logging.DEBUG
    console_level: int = logging.INFO
    max_bytes: int = 50 * 1024 * 1024  # 50 MB
    backup_count: int = 10
    compress: bool = True
    json_format: bool = False
    date_in_filename: Optional[str] = None
    encoding: str = "utf-8"
    
    # Formatering
    log_format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    
    # Advanced features
    include_system_info: bool = True
    track_events: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Konvertera log_file till Path om det är en sträng."""
        if isinstance(self.log_file, str):
            self.log_file = Path(self.log_file)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoggerConfig":
        """Skapa config från dictionary."""
        # Parsa nivåer
        if "file_level" in data and isinstance(data["file_level"], str):
            data["file_level"] = LOG_LEVELS.get(data["file_level"].upper(), logging.DEBUG)
        if "console_level" in data and isinstance(data["console_level"], str):
            data["console_level"] = LOG_LEVELS.get(data["console_level"].upper(), logging.INFO)
        
        # Parsa log_file
        if "log_file" in data and isinstance(data["log_file"], str):
            data["log_file"] = Path(data["log_file"])
        
        # Filtrera endast kända fält
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        
        return cls(**filtered)
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "name": self.name,
            "log_file": str(self.log_file) if self.log_file else None,
            "file_level": logging.getLevelName(self.file_level),
            "console_level": logging.getLevelName(self.console_level),
            "max_bytes": self.max_bytes,
            "backup_count": self.backup_count,
            "compress": self.compress,
            "json_format": self.json_format,
            "date_in_filename": self.date_in_filename,
            "encoding": self.encoding,
            "log_format": self.log_format,
            "date_format": self.date_format,
            "include_system_info": self.include_system_info,
            "track_events": self.track_events,
        }


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTERS
# ══════════════════════════════════════════════════════════════════════════════

class ColoredFormatter(logging.Formatter):
    """Formatter med färgkoder för konsol."""
    
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Grön
        'WARNING': '\033[33m',    # Gul
        'ERROR': '\033[31m',      # Röd
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'
    
    # Ikoner för olika nivåer
    ICONS = {
        'DEBUG': '🔍',
        'INFO': '✅',
        'WARNING': '⚠️',
        'ERROR': '❌',
        'CRITICAL': '🔥',
    }
    
    def __init__(self, fmt: str = None, datefmt: str = None, use_icons: bool = True):
        super().__init__(fmt, datefmt)
        self._supports_color = self._check_color_support()
        self._use_icons = use_icons
    
    def _check_color_support(self) -> bool:
        """Kontrollera om terminalen stödjer färger."""
        if os.name == 'nt':
            # Windows: aktivera ANSI-stöd
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                return True
            except Exception:
                return False
        return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    
    def format(self, record: logging.LogRecord) -> str:
        """Formatera med färg och ikoner."""
        message = super().format(record)
        
        if self._supports_color:
            color = self.COLORS.get(record.levelname, '')
            if color:
                message = message.replace(
                    record.levelname,
                    f"{color}{record.levelname}{self.RESET}"
                )
        
        return message


class CompactFormatter(logging.Formatter):
    """Kompakt formatter för filer."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Formatera kompakt."""
        record.message = record.getMessage()
        
        # Kortare tid
        record.asctime = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
        
        # Kortare nivå
        level_map = {
            'DEBUG': 'D',
            'INFO': 'I', 
            'WARNING': 'W',
            'ERROR': 'E',
            'CRITICAL': 'C',
        }
        level = level_map.get(record.levelname, record.levelname[0])
        
        return f"{record.asctime} {level} {record.name}: {record.message}"


class EnhancedJSONFormatter(logging.Formatter):
    """
    Förbättrad JSON-formatter med extra metadata.
    
    Inkluderar:
    - Standard logginfo (tid, nivå, meddelande)
    - Plugin-information
    - Event-data
    - Stack traces
    - Custom fields
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Formatera som JSON."""
        log_obj = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.thread,
        }
        
        # Lägg till exception info
        if record.exc_info:
            log_obj["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info),
            }
        
        # Lägg till extra fält (event-data, plugin-info, etc)
        if hasattr(record, 'extra_data'):
            log_obj["extra"] = record.extra_data
        
        if hasattr(record, 'event_name'):
            log_obj["event"] = {
                "name": record.event_name,
                "category": getattr(record, 'event_category', None),
                "data": getattr(record, 'event_data', None),
            }
        
        if hasattr(record, 'plugin_name'):
            log_obj["plugin"] = {
                "name": record.plugin_name,
                "version": getattr(record, 'plugin_version', None),
            }
        
        return json.dumps(log_obj, ensure_ascii=False, default=str)


# ══════════════════════════════════════════════════════════════════════════════
# HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

class GZipRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """
    RotatingFileHandler som komprimerar roterade filer med gzip.
    """
    
    def __init__(
        self,
        filename: str,
        mode: str = 'a',
        maxBytes: int = 0,
        backupCount: int = 0,
        encoding: str = 'utf-8',
        delay: bool = False,
        compress: bool = True
    ):
        self.compress = compress
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)
    
    def doRollover(self) -> None:
        """Rotera och komprimera."""
        if self.stream:
            self.stream.close()
            self.stream = None
        
        if self.backupCount > 0:
            # Ta bort äldsta backup
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename(f"{self.baseFilename}.{i}")
                dfn = self.rotation_filename(f"{self.baseFilename}.{i + 1}")
                
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)
                
                # Hantera .gz filer också
                sfn_gz = f"{sfn}.gz"
                dfn_gz = f"{dfn}.gz"
                if os.path.exists(sfn_gz):
                    if os.path.exists(dfn_gz):
                        os.remove(dfn_gz)
                    os.rename(sfn_gz, dfn_gz)
            
            # Rotera nuvarande fil
            dfn = self.rotation_filename(f"{self.baseFilename}.1")
            if os.path.exists(dfn):
                os.remove(dfn)
            
            if os.path.exists(self.baseFilename):
                os.rename(self.baseFilename, dfn)
                
                # Komprimera om aktiverat
                if self.compress:
                    self._compress_file(dfn)
        
        # Skapa ny loggfil
        if not self.delay:
            self.stream = self._open()
    
    def _compress_file(self, filepath: str) -> None:
        """Komprimera fil med gzip."""
        try:
            gz_path = f"{filepath}.gz"
            with open(filepath, 'rb') as f_in:
                with gzip.open(gz_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            os.remove(filepath)
        except Exception as e:
            # Logga inte här - kan orsaka rekursion
            print(f"Warning: Could not compress {filepath}: {e}")


class SafeTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """
    TimedRotatingFileHandler med säker filhantering och komprimering.
    """
    
    def __init__(
        self,
        filename: str,
        when: str = 'midnight',
        interval: int = 1,
        backupCount: int = 30,
        encoding: str = 'utf-8',
        delay: bool = False,
        utc: bool = False,
        compress: bool = True
    ):
        self.compress = compress
        super().__init__(filename, when, interval, backupCount, encoding, delay, utc)
    
    def doRollover(self) -> None:
        """Rotera med komprimering."""
        super().doRollover()
        
        if self.compress:
            self._compress_old_files()
    
    def _compress_old_files(self) -> None:
        """Komprimera alla roterade filer."""
        log_dir = Path(self.baseFilename).parent
        base_name = Path(self.baseFilename).name
        
        for log_file in log_dir.glob(f"{base_name}.*"):
            if log_file.suffix != '.gz' and not str(log_file).endswith('.gz'):
                try:
                    gz_path = f"{log_file}.gz"
                    with open(log_file, 'rb') as f_in:
                        with gzip.open(gz_path, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.remove(log_file)
                except Exception:
                    pass


# ══════════════════════════════════════════════════════════════════════════════
# LOGGER FACTORY
# ══════════════════════════════════════════════════════════════════════════════

class LoggerFactory:
    """Factory för att skapa loggers."""
    
    _cache: Dict[str, logging.Logger] = {}
    
    @classmethod
    def create_logger(
        cls,
        config: LoggerConfig,
        reset: bool = False
    ) -> logging.Logger:
        """
        Skapa en logger från konfiguration.
        
        Args:
            config: LoggerConfig
            reset: Rensa befintliga handlers
            
        Returns:
            Logger-instans
        """
        # Kolla cache
        if not reset and config.name in cls._cache:
            return cls._cache[config.name]
        
        # Skapa logger
        logger = logging.getLogger(config.name)
        
        # Rensa om begärt
        if reset:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
        
        # Sätt nivå till lägsta av file/console
        logger.setLevel(min(config.file_level, config.console_level))
        
        # Undvik duplicerade handlers
        if not logger.handlers:
            # Fil-handler
            if config.log_file:
                cls._add_file_handler(logger, config)
            
            # Konsol-handler
            cls._add_console_handler(logger, config)
        
        # Cachea
        cls._cache[config.name] = logger
        
        return logger
    
    @classmethod
    def _add_file_handler(cls, logger: logging.Logger, config: LoggerConfig) -> None:
        """Lägg till fil-handler."""
        log_file = config.log_file
        
        # Skapa mapp om den inte finns
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Hantera datum i filnamn
        if config.date_in_filename:
            date_str = datetime.now().strftime(config.date_in_filename)
            log_file = log_file.parent / f"{log_file.stem}_{date_str}{log_file.suffix}"
        
        # Skapa handler
        handler = GZipRotatingFileHandler(
            filename=str(log_file),
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding=config.encoding,
            compress=config.compress
        )
        handler.setLevel(config.file_level)
        
        # Formatter
        if config.json_format:
            formatter = EnhancedJSONFormatter()
        else:
            formatter = logging.Formatter(config.log_format, config.date_format)
        
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    @classmethod
    def _add_console_handler(cls, logger: logging.Logger, config: LoggerConfig) -> None:
        """Lägg till konsol-handler."""
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(config.console_level)
        
        # Färgad formatter för konsol
        formatter = ColoredFormatter(config.log_format, config.date_format)
        handler.setFormatter(formatter)
        
        logger.addHandler(handler)
    
    @classmethod
    def clear_cache(cls) -> None:
        """Rensa cache."""
        cls._cache.clear()
    
    @classmethod
    def get_cached_loggers(cls) -> List[str]:
        """Hämta lista med cachade loggers."""
        return list(cls._cache.keys())


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM INFO UTILS
# ══════════════════════════════════════════════════════════════════════════════

def get_system_info() -> Dict[str, Any]:
    """Hämta systeminformation."""
    info = {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "cwd": os.getcwd(),
        "timestamp": datetime.now().isoformat(),
    }
    
    # Lägg till minnesinfo om psutil finns
    try:
        import psutil
        mem = psutil.virtual_memory()
        info["memory_total_gb"] = round(mem.total / (1024**3), 2)
        info["memory_available_gb"] = round(mem.available / (1024**3), 2)
        info["memory_percent"] = mem.percent
        info["cpu_count"] = psutil.cpu_count()
        info["cpu_percent"] = psutil.cpu_percent(interval=0.1)
    except ImportError:
        pass
    
    return info


def log_system_info(logger: logging.Logger) -> None:
    """Logga systeminformation."""
    info = get_system_info()
    
    logger.info("=" * 80)
    logger.info("SYSTEMINFORMATION")
    logger.info("=" * 80)
    
    for key, value in info.items():
        logger.info(f"  {key}: {value}")
    
    logger.info("=" * 80)


def log_copyright(logger: logging.Logger) -> None:
    """Logga copyright-information."""
    copyright_str = get_copyright_string()
    
    logger.info("=" * 80)
    logger.info(copyright_str)
    logger.info("Alla rättigheter förbehållna.")
    logger.info("=" * 80)


def log_python_packages(
    logger: logging.Logger,
    packages: Optional[List[str]] = None
) -> None:
    """Logga Python-paket."""
    try:
        import pkg_resources
        
        if packages is None:
            # Logga viktiga paket
            packages = [
                "PySide6", "pandas", "openpyxl", "psutil",
                "requests", "python-dateutil", "chardet"
            ]
        
        installed = {}
        for pkg_name in packages:
            try:
                version = pkg_resources.get_distribution(pkg_name).version
                installed[pkg_name] = version
            except pkg_resources.DistributionNotFound:
                installed[pkg_name] = "NOT INSTALLED"
        
        logger.info("Installerade paket:")
        for name, version in sorted(installed.items()):
            status = "✅" if version != "NOT INSTALLED" else "❌"
            logger.info(f"  {status} {name}: {version}")
            
    except ImportError:
        logger.warning("pkg_resources inte tillgängligt")


# ══════════════════════════════════════════════════════════════════════════════
# EVENT LOGGER (specialiserad för event-tracking)
# ══════════════════════════════════════════════════════════════════════════════

class EventLogger:
    """
    Specialiserad logger för event audit trail.
    
    Loggar alla system-events med strukturerad data.
    """
    
    def __init__(self, logger: logging.Logger, audit_logger: Optional[logging.Logger] = None):
        self.logger = logger
        self.audit_logger = audit_logger
        self._event_counter: Dict[str, int] = {}
        self._event_history: List[Dict[str, Any]] = []
        self._max_history: int = 1000
    
    def log_event(
        self,
        event_name: str,
        event_data: Dict[str, Any] = None,
        category: str = "general"
    ) -> None:
        """
        Logga ett event.
        
        Args:
            event_name: Event-namn
            event_data: Event-data
            category: Event-kategori
        """
        # Räkna events
        self._event_counter[event_name] = self._event_counter.get(event_name, 0) + 1
        count = self._event_counter[event_name]
        
        # Skapa historik-entry
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event_name,
            "category": category,
            "data": event_data or {},
            "count": count,
        }
        
        # Spara i historik (begränsad storlek)
        self._event_history.append(entry)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
        
        # Formatera meddelande
        msg = f"📡 Event: {event_name}"
        if event_data:
            msg += f" | {self._format_event_data(event_data)}"
        msg += f" (#{count})"
        
        self.logger.info(msg)
        
        # Logga till audit (JSON-format)
        if self.audit_logger:
            self.audit_logger.info(
                json.dumps(entry, ensure_ascii=False, default=str)
            )
    
    def _format_event_data(self, data: Dict[str, Any], max_len: int = 100) -> str:
        """Formatera event-data för läsbarhet."""
        if not data:
            return "{}"
        
        # Ta endast viktiga nycklar
        priority_keys = ['version', 'post_type', 'post_types', 'file', 'status', 
                        'count', 'result', 'tab', 'page', 'error']
        
        relevant = {}
        for key in priority_keys:
            if key in data:
                relevant[key] = data[key]
        
        if not relevant:
            relevant = {k: v for k, v in list(data.items())[:3]}
        
        formatted = json.dumps(relevant, ensure_ascii=False, default=str)
        
        if len(formatted) > max_len:
            formatted = formatted[:max_len-3] + "..."
        
        return formatted
    
    def get_event_stats(self) -> Dict[str, int]:
        """Hämta event-statistik."""
        return self._event_counter.copy()
    
    def get_event_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Hämta senaste events."""
        return self._event_history[-limit:]
    
    def get_events_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Hämta events för en specifik kategori."""
        return [e for e in self._event_history if e.get("category") == category]
    
    def clear_history(self) -> None:
        """Rensa historik."""
        self._event_history.clear()


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN-KLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    Core Logger Plugin v3.0.0
    
    Central logghantering med avancerad event-driven arkitektur.
    
    Features:
    - Roterande loggfiler (storlek/tid)
    - Gzip-komprimering
    - JSON-format för strukturerad loggning
    - Färgad konsolutskrift
    - Multipla loggers (per plugin)
    - Event audit trail
    - Auto-loggning av GUI-navigation
    - Schema-change tracking
    - Import/export tracking
    
    API:
        # Hämta logger för din plugin
        logger = app.core_logger.get_plugin_logger("my_plugin")
        logger.info("Meddelande")
        
        # Logga event manuellt
        app.core_logger.log_event_manually("custom:event", {"key": "value"})
        
        # Hämta event-statistik
        stats = app.core_logger.get_event_stats()
    """
    
    NAME = "Core Logger"
    VERSION = "3.0.0"
    DESCRIPTION = "Central logghantering med event-driven arkitektur"
    AUTHOR = f"{AUTHOR}, {COMPANY}"
    DEPENDENCIES = []  # Core plugin - inga beroenden
    
    def __init__(self, app):
        super().__init__(app)
        self._paths: Dict[str, Path] = {}
        self._loggers: Dict[str, logging.Logger] = {}
        self._default_logger: Optional[logging.Logger] = None
        self._configs: Dict[str, LoggerConfig] = {}
        self._event_logger: Optional[EventLogger] = None
        self._plugin_loggers: Dict[str, logging.Logger] = {}
        self._event_handlers: Dict[str, Callable] = {}
        self._initialized: bool = False
    
    # ══════════════════════════════════════════════════════════════════════════
    # PROPERTIES
    # ══════════════════════════════════════════════════════════════════════════
    
    @property
    def default_logger(self) -> logging.Logger:
        """Returnerar default logger."""
        if self._default_logger is None:
            self._default_logger = self.get_logger()
        return self._default_logger
    
    @property
    def log_dir(self) -> Path:
        """Returnerar loggmappen."""
        return self._paths.get("logs", Path("logs"))
    
    @property
    def copyright(self) -> str:
        """Returnerar copyright-sträng med dynamiskt år."""
        return get_copyright_string()
    
    # ══════════════════════════════════════════════════════════════════════════
    # LIVSCYKEL
    # ══════════════════════════════════════════════════════════════════════════
    
    def initialize(self) -> None:
        """Initiera plugin."""
        if self._initialized:
            return
        
        self._setup_paths()
        self._load_config()
        self._setup_default_logger()
        self._setup_system_loggers()
        self._setup_event_logger()
        self._register_events()
        
        # Registrera i app för enkel åtkomst
        if self.app:
            self.app.core_logger = self
        
        self._initialized = True
        
        print(f"✅ {self.NAME} v{self.VERSION} initierad")
        print(f"   📁 Loggmapp: {self.log_dir}")
        print(f"   📋 {self.copyright}")
        
        # Logga copyright och systeminformation
        if self._default_logger:
            log_copyright(self._default_logger)
            log_system_info(self._default_logger)
            log_python_packages(self._default_logger)
            self._default_logger.info(f"Core Logger v{self.VERSION} initierad")
    
    def activate(self) -> None:
        """Aktivera plugin."""
        self.is_active = True
        if self._default_logger:
            self._default_logger.info(f"🟢 {self.NAME} aktiverad")
        
        # Emit event
        emit_event_safe(self.app, "plugin:activated", {
            "plugin": self.NAME,
            "version": self.VERSION
        })
    
    def deactivate(self) -> None:
        """Deaktivera plugin."""
        if self._default_logger:
            self._default_logger.info(f"🔴 {self.NAME} deaktiveras...")
        
        # Stäng alla loggers
        self._close_all_loggers()
        self._unregister_events()
        
        self.is_active = False
        self._initialized = False
    
    def _setup_paths(self) -> None:
        """Konfigurera sökvägar."""
        base_dir = Path(".")
        
        # Försök hämta base_dir från app
        if self.app:
            if hasattr(self.app, 'base_path'):
                base_dir = Path(self.app.base_path) if self.app.base_path else base_dir
            elif hasattr(self.app, 'config'):
                try:
                    if hasattr(self.app.config, 'get'):
                        base_dir = Path(self.app.config.get("base_dir", "."))
                    elif isinstance(self.app.config, dict):
                        base_dir = Path(self.app.config.get("base_dir", "."))
                except Exception:
                    pass
        
        self._paths = {
            "base": base_dir,
            "logs": base_dir / "logs",
        }
        
        # Skapa loggmapp
        self._paths["logs"].mkdir(parents=True, exist_ok=True)
    
    def _load_config(self) -> None:
        """Ladda konfiguration från app config."""
        app_config: Dict[str, Any] = {}
        
        # Robust hämtning av config
        if self.app and hasattr(self.app, 'config'):
            try:
                if hasattr(self.app.config, 'get'):
                    app_config = self.app.config.get("core_logger", {}) or {}
                elif isinstance(self.app.config, dict):
                    app_config = self.app.config.get("core_logger", {}) or {}
            except Exception:
                pass
        
        # Default logger config
        default_config = LoggerConfig(
            name="AppLogger",
            log_file=self.log_dir / "app.log",
            file_level=self._parse_level(
                os.environ.get("LOG_LEVEL", app_config.get("file_level", "DEBUG"))
            ),
            console_level=self._parse_level(
                os.environ.get("LOG_CONSOLE_LEVEL", app_config.get("console_level", "INFO"))
            ),
            max_bytes=app_config.get("max_bytes", 50 * 1024 * 1024),
            backup_count=app_config.get("backup_count", 10),
            compress=app_config.get("compress", True),
            json_format=app_config.get("json_format", False),
            date_in_filename=app_config.get("date_in_filename"),
            include_system_info=app_config.get("include_system_info", True),
            track_events=app_config.get("track_events", []),
        )
        
        self._configs["default"] = default_config
        
        # Ladda extra loggers från config
        extra_loggers = app_config.get("extra_loggers", [])
        if isinstance(extra_loggers, list):
            for cfg_dict in extra_loggers:
                if isinstance(cfg_dict, dict):
                    try:
                        config = LoggerConfig.from_dict(cfg_dict)
                        self._configs[config.name] = config
                    except Exception:
                        pass
    
    def _setup_default_logger(self) -> None:
        """Skapar default logger."""
        config = self._configs.get("default")
        if config:
            self._default_logger = self.create_logger(config)
            self._loggers[config.name] = self._default_logger
    
    def _setup_system_loggers(self) -> None:
        """Skapa system-loggers."""
        for key, name in SYSTEM_LOGGERS.items():
            if name not in self._loggers:
                config = LoggerConfig(
                    name=name,
                    log_file=self.log_dir / f"{key}.log",
                    file_level=logging.DEBUG,
                    console_level=logging.WARNING,
                    max_bytes=10 * 1024 * 1024,  # 10 MB
                    backup_count=5,
                    compress=True,
                )
                logger = self.create_logger(config)
                self._loggers[name] = logger
    
    def _setup_event_logger(self) -> None:
        """Skapa event audit logger."""
        event_logger = self._loggers.get(SYSTEM_LOGGERS["events"])
        
        # Audit logger med JSON-format
        audit_config = LoggerConfig(
            name=SYSTEM_LOGGERS["audit"],
            log_file=self.log_dir / "audit.log",
            file_level=logging.INFO,
            console_level=logging.CRITICAL,  # Endast i fil
            max_bytes=50 * 1024 * 1024,
            backup_count=20,
            compress=True,
            json_format=True,
        )
        audit_logger = self.create_logger(audit_config)
        self._loggers[SYSTEM_LOGGERS["audit"]] = audit_logger
        
        # Skapa EventLogger instans
        self._event_logger = EventLogger(event_logger, audit_logger)
    
    def _register_events(self) -> None:
        """Registrera events att lyssna på."""
        event_bus = get_event_bus(self.app)
        if not event_bus:
            return
        
        # Samla alla events från alla kategorier
        all_events: Set[str] = set()
        for category, events in EVENT_CATEGORIES.items():
            all_events.update(events)
        
        # Registrera handlers
        for event_name in all_events:
            try:
                # Hitta kategori för eventet
                category = "general"
                for cat, events in EVENT_CATEGORIES.items():
                    if event_name in events:
                        category = cat
                        break
                
                handler = self._create_event_handler(event_name, category)
                event_bus.on(event_name, handler)
                self._event_handlers[event_name] = handler
                
            except Exception as e:
                if self._default_logger:
                    self._default_logger.debug(f"Could not register event '{event_name}': {e}")
    
    def _create_event_handler(self, event_name: str, category: str) -> Callable:
        """Skapa event handler."""
        def handler(data: Dict[str, Any] = None):
            try:
                data = data or {}
                
                # Logga via event logger
                if self._event_logger:
                    self._event_logger.log_event(event_name, data, category)
                
                # Logga till kategori-specifik logger
                logger_key = category if category in SYSTEM_LOGGERS else "events"
                logger_name = SYSTEM_LOGGERS.get(logger_key, SYSTEM_LOGGERS["events"])
                logger = self._loggers.get(logger_name)
                
                if logger and logger != self._loggers.get(SYSTEM_LOGGERS["events"]):
                    # Undvik dubbel-loggning till events logger
                    msg = f"📡 {event_name}"
                    if data:
                        data_str = json.dumps(data, ensure_ascii=False, default=str)[:150]
                        msg += f" | {data_str}"
                    logger.debug(msg)
                
                # Specialhantering för vissa events
                self._handle_special_event(event_name, data, category)
                
            except Exception as e:
                if self._default_logger:
                    self._default_logger.error(f"Error handling event '{event_name}': {e}")
        
        return handler
    
    def _handle_special_event(
        self, 
        event_name: str, 
        data: Dict[str, Any],
        category: str
    ) -> None:
        """Specialhantering för vissa events."""
        
        # Schema-ändringar - logga tydligt
        if category == "schema":
            schema_logger = self._loggers.get(SYSTEM_LOGGERS["schema"])
            if schema_logger:
                if "version_changed" in event_name:
                    version = data.get("version", "?")
                    schema_logger.info(f"📋 Schema version ändrad till: {version}")
                elif "loaded" in event_name:
                    post_types = data.get("post_types", [])
                    if post_types:
                        schema_logger.info(f"📋 Schema laddat: PT{', PT'.join(str(pt) for pt in post_types)}")
                elif "imported" in event_name:
                    version = data.get("version", "?")
                    result = data.get("result", "")
                    schema_logger.info(f"📥 Schema importerat: v{version} - {result}")
        
        # Import-events
        elif category == "import":
            import_logger = self._loggers.get(SYSTEM_LOGGERS["import"])
            if import_logger:
                if "completed" in event_name:
                    result = data.get("result", data.get("count", "?"))
                    import_logger.info(f"✅ Import klar: {result}")
                elif "failed" in event_name:
                    error = data.get("error", "Okänt fel")
                    import_logger.error(f"❌ Import misslyckades: {error}")
                elif "started" in event_name:
                    file_name = data.get("file", data.get("source", "?"))
                    import_logger.info(f"📥 Import startad: {file_name}")
        
        # GUI-navigation - logga flikbyten
        elif category == "gui":
            gui_logger = self._loggers.get(SYSTEM_LOGGERS["gui"])
            if gui_logger:
                if "tab_changed" in event_name:
                    tab = data.get("tab", data.get("name", "?"))
                    gui_logger.info(f"📑 Flikbyte: {tab}")
                elif "page_loaded" in event_name:
                    page = data.get("page", data.get("name", "?"))
                    gui_logger.debug(f"📄 Sida laddad: {page}")
                elif "dialog_opened" in event_name:
                    dialog = data.get("dialog", data.get("title", "?"))
                    gui_logger.debug(f"💬 Dialog öppnad: {dialog}")
        
        # Filgenerering
        elif category == "generation":
            ts_logger = self._loggers.get(SYSTEM_LOGGERS["ts_file"])
            if ts_logger:
                if "generated" in event_name:
                    file_name = data.get("file", data.get("filename", "?"))
                    count = data.get("count", data.get("records", "?"))
                    ts_logger.info(f"📄 TS-fil genererad: {file_name} ({count} poster)")
                elif "failed" in event_name:
                    error = data.get("error", "Okänt fel")
                    ts_logger.error(f"❌ TS-fil generering misslyckades: {error}")
        
        # Fel - alltid logga till error logger
        elif category == "error":
            error_logger = self._loggers.get(SYSTEM_LOGGERS["errors"])
            if error_logger:
                error = data.get("error", data.get("message", "Okänt fel"))
                plugin = data.get("plugin", data.get("source", "?"))
                error_logger.error(f"❌ Fel i {plugin}: {error}")
                
                # Logga stack trace om den finns
                tb = data.get("traceback", data.get("stack_trace"))
                if tb:
                    error_logger.debug(f"Stack trace:\n{tb}")
    
    def _unregister_events(self) -> None:
        """Avregistrera events."""
        event_bus = get_event_bus(self.app)
        if not event_bus:
            return
        
        for event_name, handler in self._event_handlers.items():
            try:
                if hasattr(event_bus, 'off'):
                    event_bus.off(event_name, handler)
            except Exception:
                pass
        
        self._event_handlers.clear()
    
    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIKT API
    # ══════════════════════════════════════════════════════════════════════════
    
    def create_logger(
        self,
        config: Union[LoggerConfig, Dict[str, Any]],
        reset: bool = False
    ) -> logging.Logger:
        """
        Skapar en ny logger.
        
        Args:
            config: LoggerConfig eller dict
            reset: Rensa befintliga handlers
            
        Returns:
            Logger-instans
        """
        if isinstance(config, dict):
            config = LoggerConfig.from_dict(config)
        
        # Sätt default log_file om inte angiven
        if config.log_file is None:
            safe_name = config.name.replace(" ", "_").replace(".", "_").lower()
            config.log_file = self.log_dir / f"{safe_name}.log"
        
        # Skapa via factory
        logger = LoggerFactory.create_logger(config, reset)
        
        # Cachea
        self._loggers[config.name] = logger
        self._configs[config.name] = config
        
        return logger
    
    def get_logger(self, name: str = "AppLogger") -> logging.Logger:
        """
        Hämtar en befintlig logger eller skapar ny.
        
        Args:
            name: Logger-namn
            
        Returns:
            Logger-instans
        """
        if name in self._loggers:
            return self._loggers[name]
        
        # Finns config?
        if name in self._configs:
            return self.create_logger(self._configs[name])
        
        # Skapa ny med standardinställningar
        config = LoggerConfig(
            name=name,
            log_file=self.log_dir / f"{name.lower().replace(' ', '_')}.log"
        )
        return self.create_logger(config)
    
    def get_plugin_logger(self, plugin_name: str) -> logging.Logger:
        """
        Hämta logger för en specifik plugin.
        
        Varje plugin får sin egen loggfil.
        
        Args:
            plugin_name: Plugin-namn
            
        Returns:
            Logger-instans
        """
        if plugin_name in self._plugin_loggers:
            return self._plugin_loggers[plugin_name]
        
        # Skapa plugin-specifik logger
        safe_name = plugin_name.replace(" ", "_").replace("-", "_").lower()
        config = LoggerConfig(
            name=f"Plugin.{plugin_name}",
            log_file=self.log_dir / f"plugin_{safe_name}.log",
            file_level=logging.DEBUG,
            console_level=logging.INFO,
            max_bytes=10 * 1024 * 1024,
            backup_count=5,
            compress=True,
        )
        
        logger = self.create_logger(config)
        self._plugin_loggers[plugin_name] = logger
        
        return logger
    
    def get_system_logger(self, system_key: str) -> logging.Logger:
        """
        Hämta system-logger.
        
        Args:
            system_key: Nyckel från SYSTEM_LOGGERS (t.ex. "schema", "import", "gui")
            
        Returns:
            Logger-instans
        """
        logger_name = SYSTEM_LOGGERS.get(system_key, SYSTEM_LOGGERS["app"])
        return self._loggers.get(logger_name, self.default_logger)
    
    def create_multiple_loggers(
        self,
        configs: List[Union[LoggerConfig, Dict[str, Any]]]
    ) -> Dict[str, logging.Logger]:
        """
        Skapar flera loggers.
        
        Args:
            configs: Lista med konfigurationer
            
        Returns:
            Dict med {name: logger}
        """
        loggers: Dict[str, logging.Logger] = {}
        
        for cfg in configs:
            logger = self.create_logger(cfg)
            loggers[logger.name] = logger
        
        return loggers
    
    def list_loggers(self) -> List[str]:
        """Returnerar lista med aktiva loggers."""
        return list(self._loggers.keys())
    
    def get_logger_config(self, name: str) -> Optional[LoggerConfig]:
        """Hämtar konfiguration för en logger."""
        return self._configs.get(name)
    
    def set_level(
        self,
        level: Union[int, str],
        logger_name: Optional[str] = None,
        handler_type: Optional[str] = None
    ) -> bool:
        """
        Ändrar loggnivå för en logger eller specifik handler.
        
        Args:
            level: Ny nivå (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            logger_name: Logger-namn (None = default)
            handler_type: Handler-typ att ändra ("file", "console", None = alla)
            
        Returns:
            True om lyckad
        """
        try:
            logger = self.get_logger(logger_name) if logger_name else self.default_logger
            parsed_level = self._parse_level(level)
            
            if handler_type:
                # Ändra specifik handler-typ
                for handler in logger.handlers:
                    handler_class = type(handler).__name__.lower()
                    if handler_type.lower() in handler_class:
                        handler.setLevel(parsed_level)
                        self.default_logger.debug(
                            f"Set {handler_type} level to {logging.getLevelName(parsed_level)} "
                            f"for {logger.name}"
                        )
            else:
                # Ändra alla handlers
                logger.setLevel(parsed_level)
                for handler in logger.handlers:
                    handler.setLevel(parsed_level)
                self.default_logger.debug(
                    f"Set all levels to {logging.getLevelName(parsed_level)} for {logger.name}"
                )
            
            return True
            
        except Exception as e:
            if self._default_logger:
                self._default_logger.error(f"Kunde inte ändra loggnivå: {e}")
            return False
    
    def log_system_info(self, logger_name: Optional[str] = None) -> None:
        """
        Loggar systeminformation.
        
        Args:
            logger_name: Logger att använda (None = default)
        """
        logger = self.get_logger(logger_name) if logger_name else self.default_logger
        log_system_info(logger)
        log_copyright(logger)
    
    def log_packages(
        self,
        packages: Optional[List[str]] = None,
        logger_name: Optional[str] = None
    ) -> None:
        """
        Loggar Python-paket.
        
        Args:
            packages: Lista med paket (None = standard-paket)
            logger_name: Logger att använda
        """
        logger = self.get_logger(logger_name) if logger_name else self.default_logger
        log_python_packages(logger, packages)
    
    def log_event_manually(
        self,
        event_name: str,
        data: Dict[str, Any] = None,
        category: str = "general"
    ) -> None:
        """
        Logga ett event manuellt (utanför event bus).
        
        Användbart för plugins som vill logga utan att emittera events.
        
        Args:
            event_name: Event-namn
            data: Event-data
            category: Event-kategori
        """
        if self._event_logger:
            self._event_logger.log_event(event_name, data, category)
    
    def get_event_stats(self) -> Dict[str, int]:
        """
        Hämta event-statistik.
        
        Returns:
            Dict med event_name -> antal
        """
        if self._event_logger:
            return self._event_logger.get_event_stats()
        return {}
    
    def get_event_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Hämta senaste loggade events.
        
        Args:
            limit: Max antal events att returnera
            
        Returns:
            Lista med event-entries
        """
        if self._event_logger:
            return self._event_logger.get_event_history(limit)
        return []
    
    def get_events_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        Hämta events för en specifik kategori.
        
        Args:
            category: Kategorinamn (schema, import, gui, error, etc.)
            
        Returns:
            Lista med event-entries
        """
        if self._event_logger:
            return self._event_logger.get_events_by_category(category)
        return []
    
    def run_diagnostics(self) -> Dict[str, Any]:
        """
        Kör diagnostik och returnera status.
        
        Returns:
            Dict med diagnostik-information
        """
        return {
            "plugin_name": self.NAME,
            "plugin_version": self.VERSION,
            "copyright": self.copyright,
            "initialized": self._initialized,
            "is_active": self.is_active,
            "log_dir": str(self.log_dir),
            "log_dir_exists": self.log_dir.exists(),
            "loggers": self.list_loggers(),
            "plugin_loggers": list(self._plugin_loggers.keys()),
            "configs": {name: cfg.to_dict() for name, cfg in self._configs.items()},
            "factory_cache": LoggerFactory.get_cached_loggers(),
            "registered_events": list(self._event_handlers.keys()),
            "event_stats": self.get_event_stats(),
            "system_loggers": SYSTEM_LOGGERS,
            "event_categories": list(EVENT_CATEGORIES.keys()),
        }
    
    def test_functionality(self) -> Dict[str, bool]:
        """
        Testar alla funktioner.
        
        Returns:
            Dict med test_name -> passed
        """
        results: Dict[str, bool] = {}
        
        try:
            # Test 1: Skapa logger
            test_logger = self.get_logger("TestLogger")
            results["create_logger"] = test_logger is not None
            
            # Test 2: Logga meddelanden
            test_logger.debug("Test DEBUG message")
            test_logger.info("Test INFO message")
            test_logger.warning("Test WARNING message")
            results["log_messages"] = True
            
            # Test 3: Fil skapad
            test_log_file = self.log_dir / "testlogger.log"
            results["file_created"] = test_log_file.exists()
            
            # Test 4: Event logger
            if self._event_logger:
                self._event_logger.log_event("test:event", {"test": "data"}, "test")
                stats = self._event_logger.get_event_stats()
                results["event_logger"] = "test:event" in stats
            else:
                results["event_logger"] = False
            
            # Test 5: Plugin logger
            plugin_logger = self.get_plugin_logger("TestPlugin")
            plugin_logger.info("Plugin test message")
            results["plugin_logger"] = plugin_logger is not None
            
            # Test 6: System logger
            schema_logger = self.get_system_logger("schema")
            results["system_logger"] = schema_logger is not None
            
            # Test 7: Set level
            results["set_level"] = self.set_level("WARNING", "TestLogger")
            
            # Test 8: Diagnostics
            diag = self.run_diagnostics()
            results["diagnostics"] = len(diag) > 0
            
        except Exception as e:
            results["error"] = False
            results["error_message"] = str(e)
        
        return results
    
    # ══════════════════════════════════════════════════════════════════════════
    # INTERNA METODER
    # ══════════════════════════════════════════════════════════════════════════
    
    def _parse_level(self, level: Any) -> int:
        """Parsear loggnivå."""
        if isinstance(level, int):
            return level
        
        if isinstance(level, str):
            return LOG_LEVELS.get(level.upper(), logging.DEBUG)
        
        return logging.DEBUG
    
    def _close_all_loggers(self) -> None:
        """Stänger alla loggers."""
        for logger in self._loggers.values():
            for handler in logger.handlers[:]:
                try:
                    handler.flush()
                    handler.close()
                except Exception:
                    pass
        
        for logger in self._plugin_loggers.values():
            for handler in logger.handlers[:]:
                try:
                    handler.flush()
                    handler.close()
                except Exception:
                    pass
        
        # Rensa cache
        LoggerFactory.clear_cache()
        self._loggers.clear()
        self._plugin_loggers.clear()


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Plugin
    "Plugin",
    
    # Config
    "LoggerConfig",
    
    # Factory
    "LoggerFactory",
    
    # Event logger
    "EventLogger",
    
    # Formatters
    "ColoredFormatter",
    "CompactFormatter", 
    "EnhancedJSONFormatter",
    
    # Handlers
    "GZipRotatingFileHandler",
    "SafeTimedRotatingFileHandler",
    
    # Utility functions
    "get_system_info",
    "log_system_info",
    "log_copyright",
    "log_python_packages",
    "get_copyright_string",
    "get_copyright_year",
    
    # Helper functions (för andra plugins)
    "get_plugin_safe",
    "get_event_bus",
    "emit_event_safe",
    
    # Constants
    "SYSTEM_LOGGERS",
    "EVENT_CATEGORIES",
    "LOG_LEVELS",
    "AUTHOR",
    "COMPANY",
]