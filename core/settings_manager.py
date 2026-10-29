# -*- coding: utf-8 -*-
# core/settings_manager.py
"""
SettingsManager v1.0.0 — Bakåtkompatibel settings-wrapper.

Transportstyrelsen Fordonsregistreringssystem.

ANSVAR:
    - ALL applikationskonfiguration via settings.json (SCHEMA v1)
    - Atomisk skrivning: tempfile.mkstemp -> os.fdopen -> fsync
      -> os.replace (ALDRIG Path.replace, ALDRIG direkt write)
    - Schema-validering mot SCHEMA v1 (typkontroll per nyckel)
    - Auto-repair: saknade/korrupta nycklar ersätts med defaults
    - Migration av legacy-nycklar från äldre installationer:
        * window_width/window_height  -> window.width/height
        * plugins_enabled (lista)     -> plugin_states (dict)
        * theme "clam"/okänt tema     -> "auto"
    - Trådsäker (RLock)
    - Kraschsäker: load() kraschar ALDRIG — korrupt fil ->
      backup (.corrupt) + defaults

SCHEMA v1 (spec Sektion A):
    {
      "schema_version": 1,
      "app_name": str,
      "startup": false,
      "start_minimized": true,
      "theme": "auto",            # EXAKT: light | dark | auto
      "visible_tabs": [],
      "minimize_to_tray": true,
      "close_to_tray": true,
      "plugin_states": {},
      "mode": "prod",             # dev | prod
      "smart_cache": true,
      "window": {width, height, x, y, maximized}
    }

ANVÄNDNING:
    from core.settings_manager import SettingsManager

    sm = SettingsManager()          # laddar settings.json
    theme = sm.get("theme", "auto")
    sm.set("close_to_tray", True)   # auto-save (atomiskt)

    # Nested via dot-notation:
    w = sm.get("window.width", 1200)
    sm.set("window.maximized", True)

API (spec Sektion D):
    get(key, default) -> Any
    set(key, value)   -> None     [atomisk auto-save]
    save()            -> None     [atomisk]
    load()            -> None
    validate()        -> List[str]
    repair()          -> bool
    migrate()         -> bool

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Final, List, Optional

_log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "1.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"

SETTINGS_FILENAME: Final[str] = "settings.json"
CURRENT_SCHEMA_VERSION: Final[int] = 1
VALID_THEMES: Final[tuple] = ("light", "dark", "auto")
VALID_MODES: Final[tuple] = ("dev", "prod")


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# SCHEMA v1 — defaults (källa: spec Sektion A + settings.json)
DEFAULT_SETTINGS: Final[Dict[str, Any]] = {
    "schema_version": CURRENT_SCHEMA_VERSION,
    "app_name": "Transportstyrelsen Fordonsregistreringssystem",
    "startup": False,
    "start_minimized": True,
    "theme": "auto",
    "visible_tabs": [],
    "minimize_to_tray": True,
    "close_to_tray": True,
    "plugin_states": {},
    "mode": "prod",
    "smart_cache": True,
    "window": {
        "width": 1200,
        "height": 800,
        "x": -1,
        "y": -1,
        "maximized": False,
    },
}

# Typkrav per toppnivånyckel (för validate/repair)
_SCHEMA_TYPES: Final[Dict[str, type]] = {
    "schema_version": int,
    "app_name": str,
    "startup": bool,
    "start_minimized": bool,
    "theme": str,
    "visible_tabs": list,
    "minimize_to_tray": bool,
    "close_to_tray": bool,
    "plugin_states": dict,
    "mode": str,
    "smart_cache": bool,
    "window": dict,
}

_WINDOW_TYPES: Final[Dict[str, type]] = {
    "width": int,
    "height": int,
    "x": int,
    "y": int,
    "maximized": bool,
}


# ══════════════════════════════════════════════════════════════════════════════
# ATOMIC WRITE
# ══════════════════════════════════════════════════════════════════════════════

def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """
    Skriv JSON atomiskt enligt spec:
    tempfile.mkstemp -> os.fdopen -> fsync -> os.replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=f".{path.name}.tmp_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                data, handle,
                indent=2, ensure_ascii=False, sort_keys=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class SettingsManager:
    """
    Trådsäker hantering av settings.json (SCHEMA v1).

    Kraschsäker: load() kraschar aldrig — korrupt fil backas upp
    som settings.json.corrupt och defaults används. set() sparar
    atomiskt direkt (auto_save=True som default).
    """

    def __init__(
        self,
        settings_path: Optional[Path] = None,
        *,
        auto_save: bool = True,
        auto_load: bool = True,
    ) -> None:
        """
        Initiera SettingsManager.

        Args:
            settings_path: Sökväg till settings.json
                           (None = ./settings.json)
            auto_save: Spara atomiskt direkt vid set()
            auto_load: Kör load() direkt
        """
        self._path = Path(settings_path or SETTINGS_FILENAME)
        self._auto_save = auto_save
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
        self._loaded = False

        if auto_load:
            self.load()

    # ──────────────────────────────────────────────────────────────────
    # PROPERTIES
    # ──────────────────────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        """Sökväg till settings-filen."""
        return self._path

    @property
    def is_loaded(self) -> bool:
        """True om load() har körts."""
        return self._loaded

    @property
    def is_dev_mode(self) -> bool:
        """True om mode == 'dev'."""
        return str(self.get("mode", "prod")).lower() == "dev"

    @property
    def is_prod_mode(self) -> bool:
        """True om mode == 'prod'."""
        return not self.is_dev_mode

    # ──────────────────────────────────────────────────────────────────
    # CORE API (spec-kontrakt)
    # ──────────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """
        Hämta värde. Stödjer dot-notation för nested
        (t.ex. "window.width").

        Args:
            key: Nyckel ("theme" eller "window.width")
            default: Returneras om nyckeln saknas

        Returns:
            Värdet eller default
        """
        with self._lock:
            node: Any = self._data
            for part in key.split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    return default
            return node

    def set(self, key: str, value: Any) -> None:
        """
        Sätt värde. Stödjer dot-notation. Sparar atomiskt direkt
        om auto_save=True.

        Args:
            key: Nyckel ("theme" eller "window.width")
            value: Nytt värde
        """
        with self._lock:
            parts = key.split(".")
            node = self._data
            for part in parts[:-1]:
                if (
                    part not in node
                    or not isinstance(node[part], dict)
                ):
                    node[part] = {}
                node = node[part]
            old = node.get(parts[-1])
            node[parts[-1]] = value

        if old != value:
            _log.debug(
                "Setting ändrad: %s = %r (var %r)",
                key, value, old,
            )
            if self._auto_save:
                self.save()

    def save(self) -> None:
        """
        Spara settings atomiskt
        (mkstemp -> fdopen -> fsync -> os.replace).
        Kraschar ALDRIG appen — fel loggas.
        """
        with self._lock:
            snapshot = copy.deepcopy(self._data)
        try:
            _atomic_write_json(self._path, snapshot)
            _log.debug("Settings sparade: %s", self._path)
        except Exception as exc:
            _log.error(
                "Kunde inte spara settings till %s: %s",
                self._path, exc, exc_info=True,
            )

    def load(self) -> None:
        """
        Ladda settings.json. KRASCHSÄKER:
          - Fil saknas      -> defaults skrivs (atomiskt)
          - Korrupt JSON    -> backup .corrupt + defaults
          - Efter laddning  -> migrate() + repair() körs alltid
        """
        with self._lock:
            if not self._path.exists():
                _log.info(
                    "settings.json saknas — skapar med defaults: %s",
                    self._path,
                )
                self._data = copy.deepcopy(DEFAULT_SETTINGS)
                self._loaded = True
                self.save()
                return

            try:
                raw = self._path.read_text(encoding="utf-8")
                if raw.startswith("\ufeff"):  # BOM
                    raw = raw[1:]
                loaded = json.loads(raw)
                if not isinstance(loaded, dict):
                    raise ValueError("settings.json är inte ett objekt")
                self._data = loaded
                self._loaded = True
            except Exception as exc:
                _log.error(
                    "Korrupt settings.json (%s) — backar upp och "
                    "återställer defaults",
                    exc,
                )
                self._backup_corrupt()
                self._data = copy.deepcopy(DEFAULT_SETTINGS)
                self._loaded = True
                self.save()
                return

        # Migration + repair körs ALLTID efter lyckad laddning
        changed = self.migrate()
        changed = self.repair() or changed
        if changed:
            self.save()
        _log.info("Settings laddade: %s", self._path)

    def validate(self) -> List[str]:
        """
        Validera mot SCHEMA v1.

        Returns:
            Lista med felbeskrivningar (tom = giltig)
        """
        errors: List[str] = []
        with self._lock:
            data = self._data

            for key, expected in _SCHEMA_TYPES.items():
                if key not in data:
                    errors.append(f"Saknad nyckel: {key}")
                    continue
                value = data[key]
                # bool är subklass av int — kräv exakt typ för bool
                if expected is bool:
                    if not isinstance(value, bool):
                        errors.append(
                            f"Fel typ för {key}: förväntade bool, "
                            f"fick {type(value).__name__}"
                        )
                elif expected is int:
                    if isinstance(value, bool) or not isinstance(
                        value, int
                    ):
                        errors.append(
                            f"Fel typ för {key}: förväntade int, "
                            f"fick {type(value).__name__}"
                        )
                elif not isinstance(value, expected):
                    errors.append(
                        f"Fel typ för {key}: förväntade "
                        f"{expected.__name__}, "
                        f"fick {type(value).__name__}"
                    )

            theme = data.get("theme")
            if theme not in VALID_THEMES:
                errors.append(
                    f"Ogiltigt tema: {theme!r} "
                    f"(giltiga: {', '.join(VALID_THEMES)})"
                )

            mode = data.get("mode")
            if mode not in VALID_MODES:
                errors.append(
                    f"Ogiltigt mode: {mode!r} "
                    f"(giltiga: {', '.join(VALID_MODES)})"
                )

            window = data.get("window")
            if isinstance(window, dict):
                for wkey, wtype in _WINDOW_TYPES.items():
                    if wkey not in window:
                        errors.append(f"Saknad nyckel: window.{wkey}")
                    elif wtype is bool:
                        if not isinstance(window[wkey], bool):
                            errors.append(
                                f"Fel typ för window.{wkey}"
                            )
                    elif isinstance(window[wkey], bool) or not (
                        isinstance(window[wkey], wtype)
                    ):
                        errors.append(f"Fel typ för window.{wkey}")

        return errors

    def repair(self) -> bool:
        """
        Auto-repair: ersätt saknade/feltypade nycklar med defaults.
        Okända extra-nycklar BEHÅLLS (framtida plugins kan lagra
        eget — settings.json är enda tillåtna platsen).

        Returns:
            True om något reparerades
        """
        repaired = False
        with self._lock:
            data = self._data

            for key, default_value in DEFAULT_SETTINGS.items():
                expected = _SCHEMA_TYPES[key]
                value = data.get(key, None)

                bad = key not in data
                if not bad:
                    if expected is bool:
                        bad = not isinstance(value, bool)
                    elif expected is int:
                        bad = isinstance(value, bool) or not (
                            isinstance(value, int)
                        )
                    else:
                        bad = not isinstance(value, expected)

                if bad:
                    data[key] = copy.deepcopy(default_value)
                    repaired = True
                    _log.warning(
                        "Reparerade settings-nyckel '%s' -> %r",
                        key, default_value,
                    )

            # Enum-värden
            if data.get("theme") not in VALID_THEMES:
                _log.warning(
                    "Ogiltigt tema %r -> 'auto'", data.get("theme"),
                )
                data["theme"] = "auto"
                repaired = True

            if data.get("mode") not in VALID_MODES:
                _log.warning(
                    "Ogiltigt mode %r -> 'prod'", data.get("mode"),
                )
                data["mode"] = "prod"
                repaired = True

            # window-undernycklar
            window = data["window"]
            for wkey, wdefault in DEFAULT_SETTINGS["window"].items():
                wtype = _WINDOW_TYPES[wkey]
                wval = window.get(wkey, None)
                wbad = wkey not in window
                if not wbad:
                    if wtype is bool:
                        wbad = not isinstance(wval, bool)
                    else:
                        wbad = isinstance(wval, bool) or not (
                            isinstance(wval, int)
                        )
                if wbad:
                    window[wkey] = wdefault
                    repaired = True
                    _log.warning(
                        "Reparerade window.%s -> %r", wkey, wdefault,
                    )

        return repaired

    def migrate(self) -> bool:
        """
        Migrera legacy-nycklar från äldre installationer.

        Migreringar (flaggade vid settings.json-uppdateringen):
          1. window_width/window_height -> window.width/height
          2. plugins_enabled (lista)    -> plugin_states (dict)
          3. theme 'clam'/okänt ttk-tema -> 'auto'
          4. schema_version saknas      -> 1

        Returns:
            True om någon migrering utfördes
        """
        migrated = False
        with self._lock:
            data = self._data

            # 1. Legacy fönstergeometri
            if "window_width" in data or "window_height" in data:
                window = data.setdefault(
                    "window",
                    copy.deepcopy(DEFAULT_SETTINGS["window"]),
                )
                if not isinstance(window, dict):
                    window = copy.deepcopy(
                        DEFAULT_SETTINGS["window"]
                    )
                    data["window"] = window
                ww = data.pop("window_width", None)
                wh = data.pop("window_height", None)
                if isinstance(ww, int) and not isinstance(ww, bool):
                    window["width"] = ww
                if isinstance(wh, int) and not isinstance(wh, bool):
                    window["height"] = wh
                migrated = True
                _log.info(
                    "Migrerade window_width/window_height -> "
                    "window.width/height"
                )

            # 2. Legacy plugin-lista
            if "plugins_enabled" in data:
                legacy = data.pop("plugins_enabled")
                states = data.setdefault("plugin_states", {})
                if not isinstance(states, dict):
                    states = {}
                    data["plugin_states"] = states
                if isinstance(legacy, list):
                    for plugin_name in legacy:
                        if isinstance(plugin_name, str):
                            states.setdefault(
                                plugin_name, {"enabled": True},
                            )
                migrated = True
                _log.info(
                    "Migrerade plugins_enabled -> plugin_states "
                    "(%d poster)",
                    len(legacy) if isinstance(legacy, list) else 0,
                )

            # 3. Legacy ttk-teman (tkinter förbjudet — PySide6 ONLY)
            theme = data.get("theme")
            if isinstance(theme, str) and theme not in VALID_THEMES:
                _log.info(
                    "Migrerade legacy-tema %r -> 'auto'", theme,
                )
                data["theme"] = "auto"
                migrated = True

            # 4. schema_version
            if data.get("schema_version") != CURRENT_SCHEMA_VERSION:
                old = data.get("schema_version")
                data["schema_version"] = CURRENT_SCHEMA_VERSION
                if old is not None:
                    _log.info(
                        "schema_version %r -> %d",
                        old, CURRENT_SCHEMA_VERSION,
                    )
                migrated = True

        return migrated

    # ──────────────────────────────────────────────────────────────────
    # CONVENIENCE
    # ──────────────────────────────────────────────────────────────────

    def get_plugin_state(self, plugin_name: str) -> Dict[str, Any]:
        """Hämta state-dict för en plugin (tom dict om saknas)."""
        states = self.get("plugin_states", {})
        if isinstance(states, dict):
            state = states.get(plugin_name, {})
            return state if isinstance(state, dict) else {}
        return {}

    def set_plugin_state(
        self, plugin_name: str, state: Dict[str, Any]
    ) -> None:
        """Sätt state-dict för en plugin (auto-save)."""
        with self._lock:
            states = self._data.setdefault("plugin_states", {})
            if not isinstance(states, dict):
                states = {}
                self._data["plugin_states"] = states
            states[plugin_name] = dict(state)
        if self._auto_save:
            self.save()

    def is_plugin_enabled(self, plugin_name: str) -> bool:
        """True om plugin är aktiverad (default: True)."""
        return bool(
            self.get_plugin_state(plugin_name).get("enabled", True)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Returnera djup kopia av alla settings."""
        with self._lock:
            return copy.deepcopy(self._data)

    def reset_to_defaults(self) -> None:
        """Återställ ALLT till defaults och spara atomiskt."""
        with self._lock:
            self._data = copy.deepcopy(DEFAULT_SETTINGS)
        self.save()
        _log.warning("Settings återställda till defaults")

    # ──────────────────────────────────────────────────────────────────
    # INTERNT
    # ──────────────────────────────────────────────────────────────────

    def _backup_corrupt(self) -> None:
        """Backa upp korrupt settings-fil som .corrupt. Kraschsäker."""
        try:
            backup = self._path.with_suffix(
                self._path.suffix + ".corrupt"
            )
            os.replace(str(self._path), str(backup))
            _log.warning("Korrupt fil backad: %s", backup)
        except Exception as exc:
            _log.error("Kunde inte backa korrupt fil: %s", exc)

    def __contains__(self, key: str) -> bool:
        return self.get(key, _SENTINEL) is not _SENTINEL

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"<SettingsManager v{VERSION} "
                f"path={self._path} "
                f"keys={len(self._data)} "
                f"mode={self._data.get('mode')}>"
            )


_SENTINEL: Final[object] = object()


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "SettingsManager",
    "DEFAULT_SETTINGS",
    "CURRENT_SCHEMA_VERSION",
    "VALID_THEMES",
    "VALID_MODES",
    "SETTINGS_FILENAME",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]