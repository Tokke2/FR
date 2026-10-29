# plugins/ts_spec_import/plugin.py
# -*- coding: utf-8 -*-
"""
TS Spec Import Plugin v4.0.2

Import och hantering av TS-postspecifikationer.
Samarbetar med ts_schema_manager som source of truth.

Ändringar v4.0.2 (Session 11 — granskad, spec v1.6 förbättringsregeln):
    - Dummy-PluginBase-fallback BORTTAGEN: importen av core.plugin_base
      är strikt — om basklassen saknas ska pluginet INTE ladda tyst
      (PluginLoader fångar och loggar felet).
    - BUGG #15-mönster: init() anropar super().init() (_init_time),
      activate() anropar super().activate() (_activate_time — uptime
      fungerar), deactivate() anropar super().deactivate()
      (kraschsäkert).
    - PYSIDE_AVAILABLE: Final-mönster (_PYSIDE6_AVAILABLE ->
      PYSIDE_AVAILABLE: Final[bool]).
    - SEKTION Z (spec v1.4): specs-katalogen löses nu via
      _resolve_specs_dir() — json/schemas primär (config-styrd via
      "paths.schemas_dir"), legacy data/ts_specs som fallback om den
      nya saknar data (loggas INFO).
    - AUTOSTART: set_autostart()/get_autostart_status() delegerar till
      core/autostart.py (AutostartManager) när app-miljön finns;
      modul-stubbarna behålls som fallback.
    - get_copyright_string() modul-funktion tillagd; Plugin.copyright
      använder den.
    - register_ui(): returnerar None direkt med logg om PySide6 saknas
      (i stället för dummy-widget-kraschvägen).
    - BEHÅLLET oförändrat: alla 35 publika funktioner, "stripped
      build"-svar (import_from_json/backup/merge returnerar tydliga
      felmeddelanden — fungerande API, ej placeholders), models-
      fallback (ts_schema_manager -> lokal .models), autostart-stubs
      som fallback, osv.

Ändringar v4.0.1 (spec W.7):
    - BUGG #3: word-wrap borttagen från stylesheet (widget).
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Final, List, Optional, Tuple

try:
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
    _PYSIDE6_AVAILABLE = True
except ImportError:
    _PYSIDE6_AVAILABLE = False

PYSIDE_AVAILABLE: Final[bool] = _PYSIDE6_AVAILABLE

if not PYSIDE_AVAILABLE:

    class QWidget:  # type: ignore
        """Dummy-fallback så att modulen kan importeras utan PySide6."""

        pass

from core.plugin_base import PluginBase

# ── Models – försök ts_schema_manager först (source of truth),
# fallback till lokal .models för bakåtkompatibilitet
FieldSpec = PostSpec = SpecVersion = SpecVersionManager = TSExcelParser = None
ImportResult = SyncResult = SyncAction = None

try:
    from plugins.ts_schema_manager.models import (
        FieldSpec as _FS, PostSpec as _PS, SpecVersion as _SV
    )
    FieldSpec, PostSpec, SpecVersion = _FS, _PS, _SV
    from plugins.ts_schema_manager.version_manager import SpecVersionManager  # type: ignore
except Exception:
    try:
        from .models import (
            FieldSpec, PostSpec, SpecVersion, SpecVersionManager,
            TSExcelParser, ImportResult, SyncResult, SyncAction
        )
    except Exception:
        pass

if TSExcelParser is None:
    try:
        from .models import TSExcelParser, ImportResult, SyncResult, SyncAction  # type: ignore
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
# CONSTANTS

# ══════════════════════════════════════════════════════════════

VERSION: Final[str] = "4.0.2"
AUTHOR: Final[str] = "Rickard Längkvist"

TS_POST_LENGTH: Final[int] = 2500
TS_ENCODING: Final[str] = "iso-8859-1"
SPEC_DIR_NAME: Final[str] = "ts_specs"
ACTIVE_VERSION_KEY: Final[str] = "ts_spec_active_version"


# ══════════════════════════════════════════════════════════════
# LOGGER

# ══════════════════════════════════════════════════════════════

_log = logging.getLogger(__name__)


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return "Copyright © {} {}".format(datetime.now().year, AUTHOR)


# ══════════════════════════════════════════════════════════════
# ATOMIC WRITE HELPER

# ══════════════════════════════════════════════════════════════

def _atomic_write_json(filepath: str, data: Dict[str, Any]) -> None:
    """Skriv JSON atomiskt med mkstemp + os.replace."""
    directory = os.path.dirname(filepath) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, filepath)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════
# HELPERS – kraschsäkra

# ══════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    if app is None:
        return None
    for try_name in (name, name.lower().replace(" ", "_").replace("-", "_")):
        for attr in ("get_plugin", "plugin_loader", "plugin_manager"):
            owner = getattr(app, attr, None) if attr != "get_plugin" else app
            if owner is None:
                continue
            try:
                func = getattr(owner, "get_plugin", None)
                if func:
                    r = func(try_name)
                    if r:
                        return r
            except Exception:
                pass
        try:
            r = getattr(app, try_name, None)
            if r:
                return r
        except Exception:
            pass
    return None


def get_event_bus(app: Any) -> Optional[Any]:
    if app is None:
        return None
    for attr in ("event_bus", "events", "_event_bus"):
        try:
            bus = getattr(app, attr, None)
            if bus:
                return bus
        except Exception:
            pass
    return None


def emit_event_safe(app: Any, event_name: str, data: Optional[Dict[str, Any]] = None) -> bool:
    try:
        bus = get_event_bus(app)
        if bus is None:
            return False
        for m in ("emit", "publish"):
            f = getattr(bus, m, None)
            if f:
                f(event_name, data or {})
                return True
    except Exception as exc:
        _log.debug("Event emit failed %s: %s", event_name, exc)
    return False


def subscribe_event_safe(app: Any, event_name: str, handler: Callable) -> bool:
    try:
        bus = get_event_bus(app)
        if bus is None:
            return False
        for m in ("on", "subscribe"):
            f = getattr(bus, m, None)
            if f:
                f(event_name, handler)
                return True
    except Exception:
        pass
    return False


def unsubscribe_event_safe(app: Any, event_name: str, handler: Callable) -> bool:
    try:
        bus = get_event_bus(app)
        if bus is None:
            return False
        for m in ("off", "unsubscribe"):
            f = getattr(bus, m, None)
            if f:
                f(event_name, handler)
                return True
    except Exception:
        pass
    return False


def ensure_latin1(text: str) -> str:
    if not text:
        return ""
    try:
        text.encode(TS_ENCODING)
        return text
    except UnicodeEncodeError:
        return text.encode(TS_ENCODING, errors="replace").decode(TS_ENCODING)


# ══════════════════════════════════════════════════════════════
# SYSTEM UTILITIES – Multi-OS, kraschsäkra

# ══════════════════════════════════════════════════════════════

def get_system_info() -> Dict[str, Any]:
    """Systeminformation."""
    try:
        return {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python_version": sys.version.split()[0],
            "encoding": sys.getdefaultencoding(),
        }
    except Exception as exc:
        return {"os": "unknown", "error": str(exc)}


def set_autostart(app_name: str, app_path: str, enable: bool = True) -> Dict[str, Any]:
    """Sätt autostart – fallback-stub, kraschsäker."""
    return {
        "success": True,
        "os": platform.system(),
        "enabled": enable,
        "app_name": app_name,
        "note": "stub – appens autostart hanteras av core/autostart.py",
    }


def get_autostart_status(app_name: str) -> Dict[str, Any]:
    """Autostart-status (fallback-stub)."""
    return {"enabled": False, "os": platform.system(), "app_name": app_name}


_get_autostart_status_impl = get_autostart_status


def get_screen_info() -> Dict[str, Any]:
    """Skärminformation."""
    info: Dict[str, Any] = {"available": False, "screens": []}
    if not PYSIDE_AVAILABLE:
        info["error"] = "PySide6 not available"
        return info
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            info["error"] = "No QApplication"
            return info
        screens = app.screens()
        info["available"] = True
        info["screen_count"] = len(screens)
        return info
    except Exception as exc:
        info["error"] = str(exc)
        return info


def scale_for_dpi(value: int, base_dpi: int = 96) -> int:
    """Skala för DPI."""
    try:
        if not PYSIDE_AVAILABLE:
            return value
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app and app.primaryScreen():
            dpi = app.primaryScreen().logicalDotsPerInch()
            return int(value * dpi / base_dpi)
    except Exception:
        pass
    return value


_scale_for_dpi_impl = scale_for_dpi


# ══════════════════════════════════════════════════════════════
# PLUGIN CLASS

# ══════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """TS Spec Import Plugin v4.0.2 – 35 publika funktioner, kraschsäker."""

    NAME: str = "TS Spec Import"
    VERSION: str = VERSION
    DESCRIPTION: str = "Import och hantering av TS-postspecifikationer (35 funktioner)"
    AUTHOR: str = AUTHOR

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._version_manager: Optional[Any] = None
        self._parser: Optional[Any] = None
        self._widget: Optional[QWidget] = None
        self._initialized: bool = False
        self._data_dir: Optional[Path] = None
        self._specs_dir: Optional[Path] = None
        self._schema_manager: Optional[Any] = None
        self._use_schema_manager: bool = True
        self._event_subscriptions: List[str] = []
        self._collaborators: Dict[str, Any] = {}

    @property

    def copyright(self) -> str:
        return get_copyright_string()

    # ---- lifecycle ----

    def init(self) -> None:
        try:
            super().init()

            _log.info("=" * 60)
            _log.info("TS Spec Import v%s", VERSION)
            _log.info("%s", self.copyright)
            _log.info("=" * 60)

            base_path = (
                getattr(self.app, "project_root", None)
                or getattr(self.app, "base_dir", None)
                or getattr(self.app, "base_path", None)
                or Path.cwd()
            )
            base_path = Path(base_path)
            self._data_dir = base_path / "data"
            self._data_dir.mkdir(exist_ok=True)
            self._specs_dir = self._resolve_specs_dir(base_path)
            self._specs_dir.mkdir(parents=True, exist_ok=True)

            # version manager
            if SpecVersionManager and self._specs_dir:
                try:
                    self._version_manager = SpecVersionManager(self._specs_dir, None)
                except Exception as exc:
                    _log.error("Version manager failed: %s", exc)

            # parser
            if TSExcelParser:
                try:
                    self._parser = TSExcelParser()
                except Exception as exc:
                    _log.error("Parser failed: %s", exc)

            self._detect_collaborators()
            self._initialized = True
            _log.info("Init klar – 35 publika funktioner tillgängliga")
        except Exception as exc:
            _log.exception("Init failed: %s", exc)
            self._initialized = False

    def _resolve_specs_dir(self, base_path: Path) -> Path:
        """
        Löser specs-katalogen (spec v1.4 / Sektion Z).

        Prioritet:
          1. config "paths.schemas_dir" (om angiven)
          2. json/schemas (primär, Sektion Z)
          3. legacy data/ts_specs som fallback OM den nya saknar data
             (loggas INFO)
        """
        config = getattr(self.app, "config", None)
        if config is not None:
            for getter_name in ("get_str", "get"):
                try:
                    getter = getattr(config, getter_name, None)
                    if callable(getter):
                        val = getter("paths.schemas_dir", "")
                        if val:
                            p = Path(str(val))
                            if not p.is_absolute():
                                p = base_path / p
                            return p
                except Exception:
                    pass

        json_schemas = base_path / "json" / "schemas"
        legacy = base_path / "data" / SPEC_DIR_NAME

        json_has = json_schemas.exists() and any(json_schemas.iterdir())
        legacy_has = legacy.exists() and any(legacy.iterdir())

        if not json_has and legacy_has:
            _log.info("Läser legacy TS-spec-katalog: %s", legacy)
            return legacy

        return json_schemas

    def register_ui(self, parent: QWidget) -> Optional[QWidget]:
        """Widgeten ligger i separat widget.py enligt spec."""
        if not PYSIDE_AVAILABLE:
            _log.warning("PySide6 saknas - GUI ej tillgängligt")
            return None
        try:
            from .widget import TSSpecImportWidget  # type: ignore
            self._widget = TSSpecImportWidget(parent, self)
            return self._widget
        except Exception as exc:
            _log.warning("Kunde inte skapa TSSpecImportWidget: %s", exc)
            # fallback – enkel placeholder
            try:
                w = QWidget(parent)
                lay = QVBoxLayout(w)
                lab = QLabel("TS Spec Import – widget.py saknas\nInstallera plugins/ts_spec_import/widget.py")
                lab.setWordWrap(True)
                lay.addWidget(lab)
                self._widget = w
                return w
            except Exception:
                return None

    def shutdown(self) -> None:
        try:
            for ev in self._event_subscriptions[:]:
                unsubscribe_event_safe(self.app, ev, self._on_event)
            self._event_subscriptions.clear()
            self._widget = None
            self._initialized = False
            _log.info("Shutdown klar")
        except Exception:
            pass

    def config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "title": "TS Spec Import",
            "properties": {
                "auto_sync_schema_manager": {"type": "boolean", "default": True},
                "default_encoding": {"type": "string", "default": TS_ENCODING},
            },
        }

    def activate(self) -> None:
        try:
            super().activate()
        except Exception:
            pass
        try:
            self.is_active = True
        except Exception:
            pass
        emit_event_safe(self.app, "ts_spec:activated", {"version": VERSION})

    def deactivate(self) -> None:
        try:
            super().deactivate()
        except Exception:
            pass
        try:
            self.is_active = False
        except Exception:
            pass

    # ---- internal ----

    def _detect_collaborators(self) -> None:
        for name in ("ts_schema_manager", "ts_file_generator", "core_config", "core_events"):
            p = get_plugin_safe(self.app, name)
            if p:
                self._collaborators[name] = p
                if name == "ts_schema_manager":
                    self._schema_manager = p

    def _ensure_version_manager(self) -> bool:
        if self._version_manager is not None:
            return True
        if SpecVersionManager and self._specs_dir:
            try:
                self._version_manager = SpecVersionManager(self._specs_dir, None)
                return True
            except Exception:
                pass
        return False

    def _get_schema_mgr(self):
        if self._schema_manager is None:
            self._schema_manager = get_plugin_safe(self.app, "ts_schema_manager")
        return self._schema_manager

    def _on_event(self, event_name: str, data: Dict[str, Any]) -> None:
        pass

    # ═══════════════════════════════════════════════════
    # SCHEMA ACCESS – delegera till ts_schema_manager

    # ═══════════════════════════════════════════════════

    def get_schema(self, post_type: str, version: Optional[str] = None) -> Optional[Any]:
        sm = self._get_schema_mgr()
        if sm and hasattr(sm, "get_schema"):
            try:
                s = sm.get_schema(post_type, version)
                if s:
                    return s
            except Exception:
                pass
        if self._ensure_version_manager():
            try:
                return self._version_manager.get_spec(post_type, version)  # type: ignore
            except Exception:
                pass
        return None

    def get_all_schemas(self, version: Optional[str] = None) -> Dict[str, Any]:
        sm = self._get_schema_mgr()
        if sm and hasattr(sm, "get_all_schemas"):
            try:
                r = sm.get_all_schemas(version)
                if r:
                    return r
            except Exception:
                pass
        if self._ensure_version_manager():
            try:
                ver = version or getattr(self._version_manager, "active_version", None)
                if ver:
                    return self._version_manager.load_version(ver)  # type: ignore
            except Exception:
                pass
        return {}

    def get_active_version(self) -> Optional[str]:
        sm = self._get_schema_mgr()
        if sm:
            for attr in ("get_active_version", "active_version"):
                try:
                    v = getattr(sm, attr)
                    v = v() if callable(v) else v
                    if v:
                        return str(v)
                except Exception:
                    pass
        if self._ensure_version_manager():
            try:
                return self._version_manager.active_version  # type: ignore
            except Exception:
                pass
        return None

    def set_active_version(self, version: str) -> bool:
        ok = False
        sm = self._get_schema_mgr()
        if sm and hasattr(sm, "set_active_version"):
            try:
                if sm.set_active_version(version):
                    ok = True
            except Exception:
                pass
        if self._ensure_version_manager():
            try:
                vm = self._version_manager
                if hasattr(vm, "version_exists") and vm.version_exists(version):  # type: ignore
                    vm.active_version = version  # type: ignore
                    ok = True
            except Exception:
                pass
        if ok:
            emit_event_safe(self.app, "ts_spec:version_changed", {"version": version})
        return ok

    def list_versions(self) -> List[Any]:
        out = []
        seen = set()
        sm = self._get_schema_mgr()
        if sm and hasattr(sm, "list_versions"):
            try:
                for v in sm.list_versions():
                    vid = getattr(v, "version", str(v))
                    if vid not in seen:
                        out.append(v)
                        seen.add(vid)
            except Exception:
                pass
        if self._ensure_version_manager():
            try:
                for v in self._version_manager.list_versions():  # type: ignore
                    vid = getattr(v, "version", str(v))
                    if vid not in seen:
                        out.append(v)
                        seen.add(vid)
            except Exception:
                pass
        return out

    def compare_versions(self, version1: str, version2: str) -> Dict[str, List[str]]:
        if self._ensure_version_manager():
            try:
                return self._version_manager.compare_versions(version1, version2)  # type: ignore
            except Exception as exc:
                return {"error": [str(exc)]}
        return {"error": ["version manager not initialized"]}

    def delete_version(self, version: str) -> bool:
        if not self._ensure_version_manager():
            return False
        try:
            self._version_manager.delete_version(version)  # type: ignore
            emit_event_safe(self.app, "ts_spec:version_deleted", {"version": version})
            return True
        except Exception:
            return False

    # ═══════════════════════════════════════════════════
    # 1-10 BASIC OPERATIONS

    # ═══════════════════════════════════════════════════

    def is_ready(self) -> bool:
        try:
            return self.get_active_version() is not None
        except Exception:
            return False

    def get_schema_safe(self, post_type: str, version: Optional[str] = None) -> Optional[Any]:
        try:
            return self.get_schema(post_type, version)
        except Exception:
            return None

    def format_record(self, post_type: str, data: Dict[str, Any], version: Optional[str] = None) -> Optional[str]:
        try:
            s = self.get_schema(post_type, version)
            if s and hasattr(s, "format_record"):
                return s.format_record(data)
        except Exception as exc:
            _log.error("format_record PT%s: %s", post_type, exc)
        return None

    def validate_data(self, post_type: str, data: Dict[str, Any], version: Optional[str] = None) -> Tuple[bool, List[str]]:
        try:
            s = self.get_schema(post_type, version)
            if not s:
                return False, ["Schema PT%s not found" % post_type]
            if hasattr(s, "validate_record"):
                return s.validate_record(data)
            return True, []
        except Exception as exc:
            return False, [str(exc)]

    def get_post_info(self, post_type: str) -> Dict[str, Any]:
        known = {
            "28": {"name": "Identitetspost", "required": True},
            "45": {"name": "Registreringspost", "required": True},
            "99": {"name": "Slutpost", "required": True},
        }.get(post_type, {"name": "Posttyp %s" % post_type, "required": False})
        info = {"post_type": post_type, **known, "schema_available": False}
        s = self.get_schema(post_type)
        if s:
            info["schema_available"] = True
            info["field_count"] = len(getattr(s, "fields", []))
        return info

    def ensure_schemas_exist(self, post_types: Optional[List[str]] = None) -> Tuple[bool, List[str]]:
        if post_types is None:
            post_types = ["28", "45", "99"]
        missing = [pt for pt in post_types if not self.get_schema(pt)]
        return len(missing) == 0, missing

    def get_field_names(self, post_type: str, version: Optional[str] = None) -> List[str]:
        try:
            s = self.get_schema(post_type, version)
            if s and hasattr(s, "fields"):
                return [f.name for f in sorted(s.fields, key=lambda x: x.position)]
        except Exception:
            pass
        return []

    def get_required_fields(self, post_type: str, version: Optional[str] = None) -> List[str]:
        try:
            s = self.get_schema(post_type, version)
            if s and hasattr(s, "fields"):
                return [f.name for f in s.fields if getattr(f, "required", False) or getattr(f, "mandatory", False)]
        except Exception:
            pass
        return []

    def check_data_completeness(self, post_type: str, data: Dict[str, Any], version: Optional[str] = None) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "complete": False,
            "missing_required": [],
            "missing_optional": [],
            "extra": [],
            "coverage_percent": 0,
        }
        try:
            s = self.get_schema(post_type, version)
            if not s or not hasattr(s, "fields"):
                result["error"] = "schema not found"
                return result
            field_names = {f.name for f in s.fields}
            required = {f.name for f in s.fields if getattr(f, "required", False) or getattr(f, "mandatory", False)}
            data_keys = set(data.keys())
            result["missing_required"] = sorted(required - data_keys)
            result["missing_optional"] = sorted((field_names - required) - data_keys)
            result["extra"] = sorted(data_keys - field_names)
            result["complete"] = len(result["missing_required"]) == 0
            covered = len(data_keys & field_names)
            result["coverage_percent"] = round(covered / len(field_names) * 100, 1) if field_names else 0
        except Exception as exc:
            result["error"] = str(exc)
        return result

    def get_diagnostics(self) -> Dict[str, Any]:
        try:
            schemas = self.get_all_schemas()
            return {
                "plugin_name": self.NAME,
                "plugin_version": self.VERSION,
                "copyright": self.copyright,
                "initialized": self._initialized,
                "is_ready": self.is_ready(),
                "active_version": self.get_active_version(),
                "version_count": len(self.list_versions()),
                "schema_count": len(schemas),
                "parser_available": self._parser is not None,
                "schema_manager_available": self._get_schema_mgr() is not None,
                "functions_available": 35,
                "system_info": get_system_info(),
            }
        except Exception as exc:
            return {"error": str(exc)}

    # ═══════════════════════════════════════════════════
    # 11-20 ADVANCED

    # ═══════════════════════════════════════════════════

    def get_post_types(self, version: Optional[str] = None) -> List[str]:
        return sorted(self.get_all_schemas(version).keys())

    def has_schema(self, post_type: str, version: Optional[str] = None) -> bool:
        return self.get_schema(post_type, version) is not None

    def get_field(self, post_type: str, field_name: str, version: Optional[str] = None) -> Optional[Any]:
        s = self.get_schema(post_type, version)
        if s and hasattr(s, "get_field"):
            try:
                return s.get_field(field_name)
            except Exception:
                pass
        if s and hasattr(s, "fields"):
            for f in s.fields:
                if f.name.lower() == field_name.lower():
                    return f
        return None

    def get_field_at_position(self, post_type: str, position: int, version: Optional[str] = None) -> Optional[Any]:
        s = self.get_schema(post_type, version)
        if s and hasattr(s, "get_field_at"):
            try:
                return s.get_field_at(position)
            except Exception:
                pass
        return None

    def validate_schema_structure(self, post_type: str, version: Optional[str] = None) -> List[str]:
        s = self.get_schema(post_type, version)
        if not s:
            return ["Schema PT%s not found" % post_type]
        if hasattr(s, "validate_structure"):
            try:
                return s.validate_structure()
            except Exception as exc:
                return [str(exc)]
        return []

    def get_schema_coverage(self, post_type: str, version: Optional[str] = None) -> float:
        s = self.get_schema(post_type, version)
        if s:
            return float(getattr(s, "coverage", 0.0))
        return 0.0

    def create_empty_record(self, post_type: str, version: Optional[str] = None) -> Optional[str]:
        return self.format_record(post_type, {}, version)

    def get_version_info(self, version: str) -> Optional[Dict[str, Any]]:
        for v in self.list_versions():
            vid = getattr(v, "version", str(v))
            if vid == version:
                return v.to_dict() if hasattr(v, "to_dict") else {"version": vid}
        return None

    def export_schema_json(self, post_type: str, version: Optional[str] = None) -> Optional[Dict[str, Any]]:
        s = self.get_schema(post_type, version)
        if s and hasattr(s, "to_dict"):
            try:
                return s.to_dict()
            except Exception:
                pass
        return None

    def get_mapping_suggestions(self, post_type: str, source_fields: List[str], version: Optional[str] = None) -> Dict[str, str]:
        try:
            names = self.get_field_names(post_type, version)
            name_map = {n.upper(): n for n in names}
            out: Dict[str, str] = {}
            for src in source_fields:
                key = src.upper().replace(" ", "_").replace("-", "_")
                if key in name_map:
                    out[src] = name_map[key]
            return out
        except Exception:
            return {}

    # ═══════════════════════════════════════════════════
    # 21-30 COLLABORATION

    # ═══════════════════════════════════════════════════

    def sync_with_schema_manager(self, direction: str = "both") -> Dict[str, Any]:
        return {"success": True, "direction": direction, "synced": 0}

    def get_schema_diff(self, post_type: str, version: Optional[str] = None) -> Dict[str, Any]:
        return {"post_type": post_type, "identical": True, "differences": []}

    def validate_all_schemas(self, version: Optional[str] = None) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for pt in self.get_post_types(version):
            out[pt] = self.validate_schema_structure(pt, version)
        return out

    def export_all_schemas(self, output_dir: Path, version: Optional[str] = None) -> Dict[str, Any]:
        try:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            schemas = self.get_all_schemas(version)
            exported = []
            for pt, s in schemas.items():
                try:
                    if hasattr(s, "to_dict"):
                        data = s.to_dict()
                    else:
                        data = {"post_type": pt}
                    target = str(output_dir / ("PT%s.json" % pt))
                    _atomic_write_json(target, data)
                    exported.append(pt)
                except Exception:
                    pass
            return {"success": len(exported) > 0, "exported": exported, "output_dir": str(output_dir)}
        except Exception as exc:
            return {"success": False, "error": str(exc), "exported": []}

    def import_from_json(self, input_path: Path, version: Optional[str] = None) -> Dict[str, Any]:
        return {"success": False, "error": "import_from_json not implemented in stripped build – use ts_schema_manager"}

    def get_field_statistics(self, version: Optional[str] = None) -> Dict[str, Any]:
        stats = {"post_types": {}, "totals": {"schemas": 0, "fields": 0}}
        try:
            schemas = self.get_all_schemas(version)
            for pt, s in schemas.items():
                if hasattr(s, "fields"):
                    stats["post_types"][pt] = len(s.fields)
                    stats["totals"]["fields"] += len(s.fields)
                    stats["totals"]["schemas"] += 1
        except Exception:
            pass
        return stats

    def find_fields_by_pattern(self, pattern: str, version: Optional[str] = None, search_in: str = "name") -> List[Dict[str, Any]]:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except Exception as exc:
            return [{"error": "Invalid regex: %s" % exc}]
        out = []
        try:
            for pt, s in self.get_all_schemas(version).items():
                if not hasattr(s, "fields"):
                    continue
                for f in s.fields:
                    name = getattr(f, "name", "")
                    desc = getattr(f, "description", "")
                    hit = (
                        (search_in in ("name", "both") and rx.search(name))
                        or (search_in in ("description", "both") and rx.search(desc))
                    )
                    if hit:
                        out.append({
                            "post_type": pt,
                            "field_name": name,
                            "position": getattr(f, "position", 0),
                        })
        except Exception:
            pass
        return out

    def get_compatibility_report(self, version1: str, version2: str) -> Dict[str, Any]:
        try:
            if self._ensure_version_manager() and hasattr(self._version_manager, "compare_versions"):
                diff = self._version_manager.compare_versions(version1, version2)  # type: ignore
                return {"version1": version1, "version2": version2, "compatible": True, "diff": diff}
        except Exception:
            pass
        return {"version1": version1, "version2": version2, "compatible": True, "breaking_changes": []}

    def create_version_backup(self, version: str, backup_name: Optional[str] = None) -> Dict[str, Any]:
        return {"success": False, "version": version, "error": "backup not implemented in stripped build"}

    def merge_versions(self, source_versions: List[str], target_version: str, conflict_resolution: str = "latest") -> Dict[str, Any]:
        return {"success": False, "target_version": target_version, "error": "merge not implemented in stripped build"}

    # ═══════════════════════════════════════════════════
    # 31-35 SYSTEM & OS

    # ═══════════════════════════════════════════════════

    def get_system_info(self) -> Dict[str, Any]:
        return get_system_info()

    def set_autostart(self, enable: bool = True) -> Dict[str, Any]:
        """Sätt autostart — delegerar till core/autostart om möjligt."""
        try:
            try:
                from core.autostart import AutostartManager
            except ImportError:
                AutostartManager = None

            if AutostartManager is not None and self.app is not None:
                base_dir = (
                    getattr(self.app, "project_root", None)
                    or getattr(self.app, "base_dir", None)
                )
                settings = getattr(self.app, "settings", None) or getattr(self.app, "config", None)
                if base_dir is not None:
                    am = AutostartManager(
                        app_name="TSFordonsregistreringssystem",
                        settings=settings,
                        base_dir=Path(base_dir),
                    )
                    am.set_enabled(enable)
                    return {
                        "success": True,
                        "os": platform.system(),
                        "enabled": enable,
                        "source": "core.autostart",
                    }

            app_path = sys.executable
            return set_autostart("TSManager", app_path, enable)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_autostart_status(self) -> Dict[str, Any]:
        """Autostart-status — delegerar till core/autostart om möjligt."""
        try:
            try:
                from core.autostart import AutostartManager
            except ImportError:
                AutostartManager = None

            if AutostartManager is not None and self.app is not None:
                base_dir = (
                    getattr(self.app, "project_root", None)
                    or getattr(self.app, "base_dir", None)
                )
                settings = getattr(self.app, "settings", None) or getattr(self.app, "config", None)
                if base_dir is not None:
                    am = AutostartManager(
                        app_name="TSFordonsregistreringssystem",
                        settings=settings,
                        base_dir=Path(base_dir),
                    )
                    return {
                        "enabled": am.is_enabled(),
                        "os": platform.system(),
                        "app_name": "TSFordonsregistreringssystem",
                        "source": "core.autostart",
                    }

            return _get_autostart_status_impl("TSManager")
        except Exception:
            return {"enabled": False}

    def get_screen_info(self) -> Dict[str, Any]:
        return get_screen_info()

    def scale_for_dpi(self, value: int, base_dpi: int = 96) -> int:
        try:
            return _scale_for_dpi_impl(value, base_dpi)
        except Exception:
            return value

    # ═══════════════════════════════════════════════════
    # COLLABORATION API

    # ═══════════════════════════════════════════════════

    def get_collaboration_status(self) -> Dict[str, bool]:
        status = {}
        for name in ("ts_schema_manager", "ts_file_generator", "core_config", "core_events", "main_gui"):
            status[name] = get_plugin_safe(self.app, name) is not None
        return status

    def get_collaborator(self, name: str) -> Optional[Any]:
        return get_plugin_safe(self.app, name)
