# -*- coding: utf-8 -*-
"""
Colors Manager Plugin v3.0.0

Hanterar färgkoder och mappning till Transportstyrelsen.

Features:
    - Färgregister med CRUD-operationer
    - PIN-skyddat färgregister med verifierade säkerhetskopior
    - Bekräftade mappningar och förslag som aldrig sparas automatiskt
    - Caching för snabba uppslagningar
    - Event-baserad kommunikation

Används av:
    - ts_file_generator (lookup_ts_code)
    - vehicle_registry (get_color_display)
    - dispatch_viewer (color validation)
"""

from __future__ import annotations

import json
import copy
import uuid
import logging
import os
import tempfile
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from core.plugin_base import PluginBase
from core.dealer_pin import PinError
from core.color_storage import read_snapshot, decode_snapshot, save_snapshot

try:
    from core.exceptions import CoreError, ValidationError
except Exception:
    class CoreError(Exception):
        """Fallback om core.exceptions saknas."""

    class ValidationError(CoreError):
        """Fallback om core.exceptions saknas."""
        pass


logger = logging.getLogger(__name__)

VERSION: Final[str] = "3.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


def _make_validation_error(message: str, field_name: str = "") -> ValidationError:
    """Skapa ValidationError kompatibelt med flera signaturer."""
    try:
        return ValidationError(message, field=field_name)
    except TypeError:
        return ValidationError(message)


def get_config_value(app: Any, key: str, default: Any = None) -> Any:
    """Hämta config-värde säkert."""
    if app is None:
        return default

    config = getattr(app, "config", None)
    if config is not None:
        try:
            if hasattr(config, "get") and callable(config.get):
                value = config.get(key, default)
                return default if value is None else value
            if isinstance(config, dict):
                value = config.get(key, default)
                return default if value is None else value
        except Exception:
            pass

    plugin_manager = getattr(app, "plugin_manager", None)
    if plugin_manager is not None and hasattr(plugin_manager, "get_plugin"):
        try:
            core_config = plugin_manager.get_plugin("core_config")
            if core_config is not None:
                if hasattr(core_config, "get_config_value") and callable(core_config.get_config_value):
                    value = core_config.get_config_value(key, default)
                    return default if value is None else value
                if hasattr(core_config, "get") and callable(core_config.get):
                    value = core_config.get(key, default)
                    return default if value is None else value
        except Exception:
            pass

    return default


def get_event_bus(app: Any) -> Any:
    """Hämta event bus säkert."""
    if app is None:
        return None
    return getattr(app, "event_bus", None) or getattr(app, "events", None)


def emit_event_safe(app: Any, event_name: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """Emittera event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False

    payload = data or {}

    try:
        if hasattr(bus, "emit") and callable(bus.emit):
            bus.emit(event_name, payload)
            return True
        if hasattr(bus, "publish") and callable(bus.publish):
            bus.publish(event_name, payload)
            return True
    except Exception:
        logger.exception("Kunde inte emittera event '%s'", event_name)

    return False


def subscribe_event_safe(app: Any, event_name: str, handler: Any) -> bool:
    """Prenumerera på event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False

    try:
        if hasattr(bus, "on") and callable(bus.on):
            bus.on(event_name, handler)
            return True
        if hasattr(bus, "subscribe") and callable(bus.subscribe):
            bus.subscribe(event_name, handler)
            return True
    except Exception:
        logger.exception("Kunde inte prenumerera på event '%s'", event_name)

    return False


def unsubscribe_event_safe(app: Any, event_name: str, handler: Any) -> bool:
    """Avprenumerera från event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False

    try:
        if hasattr(bus, "off") and callable(bus.off):
            bus.off(event_name, handler)
            return True
        if hasattr(bus, "unsubscribe") and callable(bus.unsubscribe):
            bus.unsubscribe(event_name, handler)
            return True
    except Exception:
        logger.exception("Kunde inte avprenumerera från event '%s'", event_name)

    return False


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Skriv text atomiskt."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.stem}_",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with open(fd, "w", encoding=encoding, closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


def read_json_with_comments(path: Path) -> Any:
    """Läs JSON med stöd för BOM och fullradskommentarer."""
    text = path.read_text(encoding="utf-8")

    if text.startswith("\ufeff"):
        text = text[1:]

    cleaned_lines: List[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        cleaned_lines.append(line)

    content = "\n".join(cleaned_lines).strip()
    if not content:
        return []

    return json.loads(content)


def write_json_with_header(path: Path, data: Any) -> None:
    """Skriv JSON med enkel preamble."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    header = (
        f"// Auto-generated: {timestamp}\n"
        f"// File: {path.name}\n\n"
    )
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    atomic_write_text(path, header + payload, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════


class TSColorCode(Enum):
    """
    Äldre inbyggd kodlista; inte verifierad mot komplett TS-underlag.
    """

    UNKNOWN = ("0", "Okänd färg")
    BEIGE = ("BEI", "Beige")
    BLUE = ("BLA", "Blå")
    BROWN = ("BRU", "Brun")
    GRAY = ("GRA", "Grå/Silver")
    GREEN = ("GRO", "Grön")
    YELLOW = ("GUL", "Gul")
    ORANGE = ("ORA", "Orange")
    PINK = ("ROS", "Rosa")
    RED = ("ROT", "Röd")
    BLACK = ("SWA", "Svart")
    VIOLET = ("VIO", "Violett")
    WHITE = ("WIT", "Vit")
    MULTICOLOR = ("FLE", "Flerfärgad")

    def __init__(self, code: str, display_name: str):
        self.code = code
        self.display_name = display_name

    @classmethod
    def from_code(cls, code: str) -> Optional["TSColorCode"]:
        """Hämta enum från kod."""
        code = str(code).strip().upper()
        for item in cls:
            if item.code == code:
                return item
        return None

    @classmethod
    def all_codes(cls) -> Dict[str, str]:
        """Returnera alla koder som dict."""
        return {item.code: item.display_name for item in cls}


COLOR_KEYWORDS: Final[Dict[str, str]] = {
    "svart": "SWA",
    "kolsvart": "SWA",
    "sotsvart": "SWA",
    "vit": "WIT",
    "vitt": "WIT",
    "snövit": "WIT",
    "pärlvit": "WIT",
    "grå": "GRA",
    "silver": "GRA",
    "silvergrå": "GRA",
    "metallic": "GRA",
    "blå": "BLA",
    "marinblå": "BLA",
    "himmelsblå": "BLA",
    "mörkblå": "BLA",
    "röd": "ROT",
    "vinröd": "ROT",
    "mörkröd": "ROT",
    "brandröd": "ROT",
    "grön": "GRO",
    "mörkgrön": "GRO",
    "ljusgrön": "GRO",
    "olivgrön": "GRO",
    "gul": "GUL",
    "citrongul": "GUL",
    "solrosgul": "GUL",
    "brun": "BRU",
    "mörkbrun": "BRU",
    "ljusbrun": "BRU",
    "kastanj": "BRU",
    "orange": "ORA",
    "beige": "BEI",
    "sandbeige": "BEI",
    "champagne": "BEI",
    "violett": "VIO",
    "lila": "VIO",
    "purpur": "VIO",
    "aubergine": "VIO",
    "rosa": "ROS",
    "pink": "ROS",
    "cerise": "ROS",
    "black": "SWA",
    "white": "WIT",
    "grey": "GRA",
    "gray": "GRA",
    "blue": "BLA",
    "red": "ROT",
    "green": "GRO",
    "yellow": "GUL",
    "brown": "BRU",
    "purple": "VIO",
    "violet": "VIO",
    "alpinweiss": "WIT",
    "alpine": "WIT",
    "saphirschwarz": "SWA",
    "sapphire": "BLA",
    "mineralweiss": "WIT",
    "mineral": "GRA",
    "spacegrau": "GRA",
    "space": "GRA",
}


# ══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Color:
    """
    Färgpost i registret.
    """

    code: str
    name: str
    ts_code: str = ""
    manufacturer: str = ""
    hex_value: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    _original: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.code = str(self.code).strip()
        self.name = str(self.name).strip()
        self.ts_code = str(self.ts_code).strip().upper()
        self.manufacturer = str(self.manufacturer).strip()
        self.hex_value = str(self.hex_value).strip()

        if not self.name:
            raise _make_validation_error("Color name cannot be empty", "name")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Color":
        """Skapa från dictionary."""
        return cls(
            code=data.get("kod", data.get("code", "")),
            name=data.get("namn", data.get("name", "")),
            ts_code=data.get("ts_kod", data.get("ts_code", "")),
            manufacturer=data.get("manufacturer", ""),
            hex_value=data.get("hex", data.get("hex_value", "")),
            created_at=data.get("created_at", datetime.now().isoformat()),
            _original=copy.deepcopy(data),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Behåll även fält som denna version inte känner till."""
        result = copy.deepcopy(self._original)
        values = {"kod": self.code, "namn": self.name, "ts_kod": self.ts_code,
                  "manufacturer": self.manufacturer, "hex": self.hex_value, "created_at": self.created_at}
        result.update(values)
        for alias, key in (("code", "kod"), ("name", "namn"), ("ts_code", "ts_kod"), ("hex_value", "hex")):
            if alias in result:
                result[alias] = values[key]
        return result

    @property
    def storage_key(self) -> str:
        return self.code or self._original.get("dispatch_pending_id", "")

    @property
    def ts_display(self) -> str:
        """TS-kod med beskrivning."""
        ts = TSColorCode.from_code(self.ts_code)
        if ts:
            return f"{ts.code} - {ts.display_name}"
        return self.ts_code or "Ej mappad"


@dataclass
class ColorLookupResult:
    """Resultat från färguppslagning."""

    ts_code: str
    confidence: float
    match_type: str
    source_color: str
    matched_to: str = ""

    @property
    def is_confident(self) -> bool:
        """True bara för ett uttryckligen sparat/exakt värde, inte en gissning."""
        return self.match_type == "exact"


@dataclass
class ColorOperationResult:
    """Resultat från färgoperation."""

    success: bool
    message: str
    color: Optional[Color] = None
    affected_count: int = 0


# ══════════════════════════════════════════════════════════════════════════════
# COLOR SERVICE
# ══════════════════════════════════════════════════════════════════════════════


class ColorService:
    """
    Service för färghantering.
    """

    def __init__(
        self,
        colors_file: Path,
        mappings_file: Path,
        event_bus: Optional[Any] = None,
        pin_provider=None,
    ):
        self._pin_provider = pin_provider
        self.colors_file = colors_file
        self.mappings_file = mappings_file
        self.event_bus = event_bus

        self._colors: Dict[str, Color] = {}
        self._mappings: Dict[str, str] = {}
        self._loaded = False
        self._colors_snapshot = None
        self._mappings_snapshot = None
        self._colors_payload = []
        self._mappings_payload = {"mappings": {}}

    def dealer_pin(self):
        if self._pin_provider is None:
            raise PinError("Den gemensamma PIN-koden för återförsäljare är inte tillgänglig")
        return self._pin_provider()

    def _authorized(self, pin) -> bool:
        try:
            return self.dealer_pin().verify(pin)
        except (OSError, ValueError, RuntimeError):
            return False

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------

    def load(self) -> int:
        """Läs strikt. Ett fel får aldrig förvandlas till ett tomt register."""
        self._loaded = False
        color_bytes = read_snapshot(self.colors_file)
        mapping_bytes = read_snapshot(self.mappings_file)
        payload = decode_snapshot(color_bytes, [])
        mapping_payload = decode_snapshot(mapping_bytes, {"mappings": {}})
        rows = payload.get("colors") if isinstance(payload, dict) and "colors" in payload else payload
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Färgfilen innehåller ogiltiga poster och har lämnats orörd")
        colors = {}
        seen = set()
        for row in rows:
            for primary, alias in (("kod", "code"), ("namn", "name"), ("ts_kod", "ts_code"), ("hex", "hex_value")):
                if primary in row and alias in row and row[primary] != row[alias]:
                    raise ValueError("Färgfilen har motstridiga fält och har lämnats orörd")
            for key in ("kod", "code", "namn", "name", "ts_kod", "ts_code", "manufacturer", "hex", "hex_value"):
                if key in row and not isinstance(row[key], str):
                    raise ValueError("Färgfilen innehåller ett ogiltigt fält och har lämnats orörd")
            color = Color.from_dict(row)
            pending_id = row.get("dispatch_pending_id", "")
            if not color.code and (not isinstance(pending_id, str) or not pending_id.startswith("@dispatch:") or len(pending_id) != 42):
                raise ValueError("Färgfilen saknar färgkod eller giltigt Dispatch-ID")
            key = color.storage_key
            code_key = key.casefold()
            if not code_key or code_key in seen:
                raise ValueError("Färgfilen saknar färgkod eller innehåller dubblettkoder; inga poster ändrades")
            seen.add(code_key)
            colors[key] = color
        if (not isinstance(mapping_payload, dict) or "mappings" not in mapping_payload
                or not isinstance(mapping_payload["mappings"], dict)):
            raise ValueError("Färgmappningarna har ogiltigt format och har lämnats orörda")
        mappings = mapping_payload.get("mappings", {})
        if any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) for k, v in mappings.items()):
            raise ValueError("Färgmappningarna innehåller ogiltiga värden och har lämnats orörda")
        if len({k.strip().lower() for k in mappings}) != len(mappings):
            raise ValueError("Färgmappningarna innehåller tvetydiga namn och har lämnats orörda")
        self._colors, self._mappings = colors, {k.strip().lower(): v for k, v in mappings.items()}
        self._colors_snapshot, self._mappings_snapshot = color_bytes, mapping_bytes
        self._colors_payload, self._mappings_payload = payload, mapping_payload
        self._loaded = True
        self._clear_cache()
        return len(colors)

    def _save_colors(self, colors: Dict[str, Color]) -> None:
        # Orörda poster behåller sina ursprungliga fält, formatering och värden.
        rows = [copy.deepcopy(color._original)
                if self._colors.get(key) is color and color._original else color.to_dict()
                for key, color in colors.items()]
        if isinstance(self._colors_payload, dict) and "colors" in self._colors_payload:
            payload = copy.deepcopy(self._colors_payload)
            payload["colors"] = rows
        elif isinstance(self._colors_payload, dict) and len(rows) == 1:
            payload = rows[0]
        else:
            payload = rows
        new_snapshot = save_snapshot(self.colors_file, self._colors_snapshot, payload,
                                     other_path=self.mappings_file, other_expected=self._mappings_snapshot)
        self._colors_snapshot, self._colors_payload = new_snapshot, payload
        self._colors = {color.storage_key: color for color in (Color.from_dict(row) for row in rows)}
        self._clear_cache()

    def _save_mappings(self, mappings: Dict[str, str]) -> None:
        payload = copy.deepcopy(self._mappings_payload)
        old = payload.get("mappings", {})
        preserved = {key: mappings[key.strip().lower()] for key in old if key.strip().lower() in mappings}
        already = {key.strip().lower() for key in preserved}
        preserved.update({key: value for key, value in mappings.items() if key not in already})
        payload["mappings"] = preserved
        new_snapshot = save_snapshot(self.mappings_file, self._mappings_snapshot, payload,
                                     other_path=self.colors_file, other_expected=self._colors_snapshot)
        self._mappings_snapshot, self._mappings_payload, self._mappings = new_snapshot, payload, mappings
        self._clear_cache()

    def save(self) -> bool:
        """Ingen äldre massparning: ändringar måste gå via PIN-skyddade operationer."""
        logger.warning("Äldre massparning av färger är spärrad; använd PIN-skyddad ändring")
        return False

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_all(self) -> List[Color]:
        """Hämta alla färger."""
        self._ensure_loaded()
        return copy.deepcopy(list(self._colors.values()))

    def get_by_code(self, code: str) -> Optional[Color]:
        """Hämta färg med kod."""
        self._ensure_loaded()
        return copy.deepcopy(self._colors.get(str(code).strip()))

    def get_by_name(self, name: str) -> Optional[Color]:
        """Hämta färg med namn."""
        self._ensure_loaded()
        name_lower = str(name).lower().strip()

        for color in self._colors.values():
            if color.name.lower() == name_lower:
                return copy.deepcopy(color)
        return None

    def add_dispatch_names(self, names: List[str]) -> ColorOperationResult:
        """Lägg endast till saknade namn, utan kod eller TS-mappning."""
        try:
            self._ensure_loaded()
            if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
                raise ValueError("Ogiltiga färgnamn från Dispatch")
            existing = {c.name.casefold() for c in self._colors.values()}
            updated = dict(self._colors)
            count = 0
            for name in names:
                name = name.strip()
                if not name or name.casefold() in existing:
                    continue
                key = "@dispatch:" + uuid.uuid4().hex
                if key.casefold() in {k.casefold() for k in updated}:
                    raise ValueError("Kunde inte skapa ett unikt Dispatch-ID")
                color = Color(code="", name=name, _original={"dispatch_pending_id": key})
                updated[key] = color
                existing.add(name.casefold())
                count += 1
            if count:
                self._save_colors(updated)
                self._emit("colors:dispatch_added", {"count": count})
            return ColorOperationResult(True, f"{count} nya färgnamn från Dispatch", affected_count=count)
        except Exception as exc:
            logger.warning("Dispatch-färger kunde inte sparas: %s", exc)
            return ColorOperationResult(False, f"Inga Dispatch-färger sparades: {exc}")

    def add(self, code: str, name: str, ts_code: str = "", *, pin=None, **extra: Any) -> ColorOperationResult:
        try:
            self._ensure_loaded()
            if not self._authorized(pin):
                return ColorOperationResult(False, "Gemensam PIN krävs för att ändra färger")
            code, name = str(code).strip(), str(name).strip()
            if not code or not name or code.casefold().startswith("@dispatch:"):
                return ColorOperationResult(False, "Kod och namn krävs; @dispatch: är reserverat")
            if any(existing.casefold() == code.casefold() for existing in self._colors):
                return ColorOperationResult(False, "Färgkoden finns redan")
            if self.get_by_name(name):
                return ColorOperationResult(False, "Färgnamnet finns redan")
            color = Color(code=code, name=name, ts_code=ts_code,
                          manufacturer=str(extra.get("manufacturer", "")), hex_value=str(extra.get("hex_value", "")))
            updated = dict(self._colors); updated[code] = color
            self._save_colors(updated)
            self._emit("colors:added", {"color": color.to_dict()})
            return ColorOperationResult(True, f"Färg '{name}' tillagd", copy.deepcopy(color), 1)
        except Exception as exc:
            logger.warning("Färgen kunde inte läggas till: %s", exc)
            return ColorOperationResult(False, f"Ingen färg sparades: {exc}")

    def update(self, code: str, *, pin=None, expected_color=None, **updates: Any) -> ColorOperationResult:
        try:
            self._ensure_loaded()
            if not self._authorized(pin):
                return ColorOperationResult(False, "Gemensam PIN krävs för att ändra färger")
            code = str(code).strip()
            old = self._colors.get(code)
            if old is None:
                return ColorOperationResult(False, "Färgen finns inte")
            if expected_color is not None and old.to_dict() != expected_color.to_dict():
                return ColorOperationResult(False, "Färgen ändrades medan dialogen var öppen")
            name = str(updates.get("name", old.name)).strip()
            new_code = str(updates.get("new_code", old.code)).strip()
            pending = not old.code and bool(old._original.get("dispatch_pending_id"))
            if not name or (not new_code and not pending) or new_code.casefold().startswith("@dispatch:"):
                return ColorOperationResult(False, "Kod och namn krävs")
            new_key = new_code or code
            if any(key != code and key.casefold() == new_key.casefold() for key in self._colors):
                return ColorOperationResult(False, "Färgkoden finns redan")
            if any(key != code and c.name.casefold() == name.casefold() for key, c in self._colors.items()):
                return ColorOperationResult(False, "Färgnamnet finns redan")
            color = copy.deepcopy(old)
            color.code = new_code
            if new_code:
                color._original.pop("dispatch_pending_id", None)
            color.name = name
            color.ts_code = str(updates.get("ts_code", old.ts_code)).strip().upper()
            color.manufacturer = str(updates.get("manufacturer", old.manufacturer)).strip()
            color.hex_value = str(updates.get("hex_value", old.hex_value)).strip()
            updated = {new_key if key == code else key: color if key == code else value
                       for key, value in self._colors.items()}
            self._save_colors(updated)
            self._emit("colors:updated", {"color": color.to_dict()})
            return ColorOperationResult(True, f"Färg '{name}' uppdaterad", copy.deepcopy(color), 1)
        except Exception as exc:
            logger.warning("Färgen kunde inte uppdateras: %s", exc)
            return ColorOperationResult(False, f"Ingen färg sparades: {exc}")

    def delete(self, code: str, *, pin=None, expected_color=None) -> ColorOperationResult:
        try:
            self._ensure_loaded()
            if not self._authorized(pin):
                return ColorOperationResult(False, "Gemensam PIN krävs för att ändra färger")
            code = str(code).strip()
            color = self._colors.get(code)
            if color is None:
                return ColorOperationResult(False, "Färgen finns inte")
            if expected_color is not None and color.to_dict() != expected_color.to_dict():
                return ColorOperationResult(False, "Färgen ändrades före borttagning")
            updated = dict(self._colors); del updated[code]
            self._save_colors(updated)
            self._emit("colors:deleted", {"code": code, "name": color.name})
            return ColorOperationResult(True, f"Färg '{color.name}' borttagen", copy.deepcopy(color), 1)
        except Exception as exc:
            logger.warning("Färgen kunde inte tas bort: %s", exc)
            return ColorOperationResult(False, f"Ingen färg togs bort: {exc}")

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup_ts_code(self, color_name: str) -> str:
        """Slå upp TS-kod för färgnamn."""
        result = self.lookup_ts_code_detailed(color_name)
        return result.ts_code if result.match_type == "exact" else ""

    def lookup_ts_code_detailed(self, color_name: str) -> ColorLookupResult:
        """Slå upp TS-kod med detaljer."""
        if not color_name:
            return ColorLookupResult(
                ts_code="",
                confidence=0.0,
                match_type="none",
                source_color="",
            )

        return self._cached_lookup(color_name.strip().lower())

    @lru_cache(maxsize=1000)
    def _cached_lookup(self, clean_name: str) -> ColorLookupResult:
        """Cachad uppslagning."""
        self._ensure_loaded()

        registered = {color.ts_code.upper() for color in self._colors.values()
                      if color.name.lower() == clean_name and color.ts_code}
        saved = self._mappings.get(clean_name, "").strip().upper()
        known = registered | ({saved} if saved else set())
        if len(known) > 1:
            return ColorLookupResult("", 0.0, "conflict", clean_name)
        if known:
            return ColorLookupResult(next(iter(known)), 1.0, "exact", clean_name, clean_name)
        # Kodlistan och nyckelord är endast förslag tills underlaget verifierats.
        for ts_code in TSColorCode:
            if clean_name == ts_code.display_name.lower():
                return ColorLookupResult(ts_code.code, 1.0, "suggestion", clean_name, ts_code.display_name)

        for keyword, code in COLOR_KEYWORDS.items():
            if keyword in clean_name:
                return ColorLookupResult(
                    ts_code=code,
                    confidence=0.85,
                    match_type="keyword",
                    source_color=clean_name,
                    matched_to=keyword,
                )

        best_match = self._fuzzy_match(clean_name)
        if best_match:
            return best_match

        return ColorLookupResult(
            ts_code="",
            confidence=0.0,
            match_type="none",
            source_color=clean_name,
        )

    def _fuzzy_match(
        self,
        name: str,
        threshold: float = 0.7,
    ) -> Optional[ColorLookupResult]:
        """Fuzzy matching mot kända färger."""
        best_ratio = 0.0
        best_match = ""
        best_code = ""

        for mapped_name, ts_code in self._mappings.items():
            ratio = SequenceMatcher(None, name, mapped_name).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = mapped_name
                best_code = ts_code

        for color in self._colors.values():
            ratio = SequenceMatcher(None, name, color.name.lower()).ratio()
            if ratio > best_ratio and color.ts_code:
                best_ratio = ratio
                best_match = color.name
                best_code = color.ts_code

        if best_ratio >= threshold:
            return ColorLookupResult(
                ts_code=best_code,
                confidence=best_ratio,
                match_type="fuzzy",
                source_color=name,
                matched_to=best_match,
            )

        return None

    def add_mapping(self, color_name: str, ts_code: str, *, pin=None, overwrite=False) -> bool:
        """Spara endast användargodkända mappningar; tyst ersättning är förbjuden."""
        try:
            self._ensure_loaded()
            if not self._authorized(pin):
                return False
            color_name, ts_code = str(color_name).strip(), str(ts_code).strip().upper()
            if not color_name or not ts_code or not TSColorCode.from_code(ts_code):
                return False
            key = color_name.lower()
            if key in self._mappings and self._mappings[key] != ts_code and not overwrite:
                return False
            mappings = dict(self._mappings); mappings[key] = ts_code
            self._save_mappings(mappings)
            self._emit("colors:mapping_added", {"color": color_name, "ts_code": ts_code})
            return True
        except Exception as exc:
            logger.warning("Färgmappningen kunde inte sparas: %s", exc)
            return False

    def delete_mapping(self, color_name: str, *, pin=None) -> bool:
        try:
            self._ensure_loaded()
            if not self._authorized(pin):
                return False
            key = str(color_name).strip().lower()
            if key not in self._mappings:
                return False
            mappings = dict(self._mappings); del mappings[key]
            self._save_mappings(mappings)
            self._emit("colors:mapping_deleted", {"color": color_name})
            return True
        except Exception as exc:
            logger.warning("Färgmappningen kunde inte tas bort: %s", exc)
            return False

    def get_mapping_display(self) -> Dict[str, str]:
        """Visa ursprungliga namnformer, utan att lämna ut en muterbar referens."""
        self._ensure_loaded()
        return dict(self._mappings_payload.get("mappings", {}))

    def get_all_mappings(self) -> Dict[str, str]:
        """Hämta alla mappningar."""
        self._ensure_loaded()
        return self._mappings.copy()

    def get_unmapped_sample(
        self,
        colors: List[str],
        limit: Optional[int] = None,
    ) -> List[Tuple[str, ColorLookupResult]]:
        """Analysera lista med färger och returnera osäkra/omappade."""
        results: List[Tuple[str, ColorLookupResult]] = []
        seen = set()

        for color_name in colors:
            if not color_name:
                continue

            lowered = color_name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)

            result = self.lookup_ts_code_detailed(color_name)
            if result.match_type != "exact":
                results.append((color_name, result))
                if limit is not None and len(results) >= limit:
                    break

        results.sort(key=lambda item: item[1].confidence)
        return results

    # ------------------------------------------------------------------
    # Search / stats / helpers
    # ------------------------------------------------------------------

    def search(self, query: str) -> List[Color]:
        """Sök färger."""
        self._ensure_loaded()

        if not query:
            return copy.deepcopy(list(self._colors.values()))

        query_lower = query.lower()
        results: List[Color] = []

        for color in self._colors.values():
            if (
                query_lower in color.code.lower()
                or query_lower in color.name.lower()
                or query_lower in color.ts_code.lower()
                or query_lower in (TSColorCode.from_code(color.ts_code).display_name.lower()
                                   if TSColorCode.from_code(color.ts_code) else "")
                or query_lower in color.manufacturer.lower()
                or query_lower in color.hex_value.lower()
            ):
                results.append(color)

        return copy.deepcopy(results)

    def get_statistics(self) -> Dict[str, Any]:
        """Hämta statistik."""
        self._ensure_loaded()

        mapped_count = sum(1 for color in self._colors.values() if color.ts_code)

        ts_distribution: Dict[str, int] = {}
        for color in self._colors.values():
            if color.ts_code:
                ts_distribution[color.ts_code] = ts_distribution.get(color.ts_code, 0) + 1

        by_name = {}
        for color in self._colors.values():
            if color.ts_code:
                by_name.setdefault(color.name.lower(), set()).add(color.ts_code.upper())
        for name, code in self._mappings.items():
            if code:
                by_name.setdefault(name, set()).add(code.upper())
        return {
            "conflicts": sum(len(codes) > 1 for codes in by_name.values()),
            "total_colors": len(self._colors),
            "mapped_colors": mapped_count,
            "unmapped_colors": len(self._colors) - mapped_count,
            "total_mappings": len(self._mappings),
            "ts_distribution": ts_distribution,
            "coverage_percent": (mapped_count / len(self._colors) * 100.0) if self._colors else 0.0,
        }

    def get_color_display(self, color_name: str) -> str:
        """Returnera visningssträng för en färg inklusive TS-kod om möjligt."""
        result = self.lookup_ts_code_detailed(color_name)
        if result.ts_code and result.match_type == "exact":
            ts = TSColorCode.from_code(result.ts_code)
            if ts:
                return f"{color_name} ({ts.code} - {ts.display_name})"
            return f"{color_name} ({result.ts_code})"
        return color_name

    def _ensure_loaded(self) -> None:
        """Säkerställ att data är laddad."""
        if not self._loaded:
            self.load()

    def _clear_cache(self) -> None:
        """Rensa lookup-cache."""
        self._cached_lookup.cache_clear()

    def _emit(self, event_name: str, data: Dict[str, Any]) -> None:
        """Emittera event om event_bus finns."""
        bus = self.event_bus
        if bus is None:
            return

        try:
            if hasattr(bus, "emit") and callable(bus.emit):
                bus.emit(event_name, data)
            elif hasattr(bus, "publish") and callable(bus.publish):
                bus.publish(event_name, data)
        except Exception:
            logger.exception("Kunde inte emittera event '%s'", event_name)


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════


class Plugin(PluginBase):
    """
    Colors Manager Plugin.

    Fasad för ColorService med integration i app-ekosystemet.
    """

    NAME = "Colors Manager"
    VERSION = "3.0.0"
    DESCRIPTION = "Färghantering med TS-mappning"
    AUTHOR = AUTHOR
    COPYRIGHT = get_copyright_string()

    DEPENDENCIES: List[str] = []
    OPTIONAL_DEPENDENCIES: List[str] = ["core_config"]

    def __init__(self, app: Any):
        super().__init__(app)
        self.is_active: bool = False
        self._service: Optional[ColorService] = None
        self._widget: Optional["ColorsWidget"] = None
        self._event_registered: bool = False

    @property
    def service(self) -> ColorService:
        """Hämta color service."""
        if self._service is None:
            raise RuntimeError("Plugin not initialized")
        return self._service

    def initialize(self) -> bool:
        """Initiera plugin."""
        try:
            base_dir = Path(get_config_value(self.app, "base_dir", ".") or ".")
            data_dir_name = get_config_value(self.app, "data_dir", "data")
            data_dir = base_dir / data_dir_name / "colors_manager"
            data_dir.mkdir(parents=True, exist_ok=True)

            self._service = ColorService(
                colors_file=data_dir / "farger.json",
                mappings_file=data_dir / "color_mappings.json",
                event_bus=get_event_bus(self.app),
                pin_provider=self._shared_dealer_pin,
            )

            try:
                count = self._service.load()
            except Exception as exc:
                # Visa felet på fliken och spärra skrivning; ersätt aldrig med tom data.
                logger.error("Färgdata kunde inte läsas: %s", exc)
                count = 0

            self.app.colors = self
            self.app.colors_manager = self

            logger.info("Colors Manager initialized with %s colors", count)
            return True

        except Exception:
            logger.exception("Failed to initialize Colors Manager")
            return False

    def _shared_dealer_pin(self):
        try:
            dealer = getattr(self.app, "dealers", None)
            if dealer is None and hasattr(self.app, "get_plugin"):
                dealer = self.app.get_plugin("dealers_manager")
            if dealer is None or not callable(getattr(dealer, "dealer_pin", None)):
                raise PinError("Återförsäljarpluginet behövs för den gemensamma PIN-koden")
            return dealer.dealer_pin()
        except PinError:
            raise
        except Exception as exc:
            raise PinError("Den gemensamma PIN-koden är inte tillgänglig") from exc

    def activate(self) -> bool:
        """Aktivera plugin."""
        self.is_active = True
        self._event_registered = subscribe_event_safe(
            self.app,
            "dispatch:colors_found",
            self._on_colors_found,
        )
        return True

    def deactivate(self) -> bool:
        """Deaktivera plugin."""
        if self._event_registered:
            unsubscribe_event_safe(self.app, "dispatch:colors_found", self._on_colors_found)
            self._event_registered = False

        self._widget = None
        self.is_active = False
        return True

    def init(self) -> bool:
        """Alias för initialize()."""
        return self.initialize()

    def register_ui(self, parent: QWidget) -> QWidget:
        """Skapa widget."""
        return self.create_widget(parent)

    def shutdown(self) -> bool:
        """Alias för deactivate()."""
        return self.deactivate()

    def config_schema(self) -> Dict[str, Any]:
        """Konfigurationsschema."""
        return {
            "enabled": {
                "type": "boolean",
                "default": True,
                "description": "Aktivera colors_manager-pluginet.",
            },
            "data_dir": {
                "type": "string",
                "default": "data/colors_manager",
                "description": "Katalog för färgregister och mappningar.",
            },
        }

    def create_widget(self, parent: QWidget) -> QWidget:
        """Skapa widget för main_gui."""
        self._widget = ColorsWidget(parent, self.service)
        return self._widget

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup_ts_code(self, color_name: str) -> str:
        """Slå upp TS-kod för färg."""
        return self.service.lookup_ts_code(color_name)

    def lookup_ts_code_detailed(self, color_name: str) -> ColorLookupResult:
        """Slå upp TS-kod med detaljer."""
        return self.service.lookup_ts_code_detailed(color_name)

    def get_all_colors(self) -> List[Color]:
        """Hämta alla färger."""
        return self.service.get_all()

    def get_color_display(self, color_name: str) -> str:
        """Hämta visningssträng för färg."""
        return self.service.get_color_display(color_name)

    def add_color(
        self,
        code: str,
        name: str,
        ts_code: str = "",
        *, pin=None,
    ) -> ColorOperationResult:
        """Lägg till färg med gemensam PIN."""
        return self.service.add(code, name, ts_code, pin=pin)

    def update_color(self, code: str, **updates: Any) -> ColorOperationResult:
        """Uppdatera färg."""
        return self.service.update(code, **updates)

    def delete_color(self, code: str, *, pin=None) -> ColorOperationResult:
        """Ta bort färg med gemensam PIN."""
        return self.service.delete(code, pin=pin)

    def map_color(self, color_name: str, ts_code: str, *, pin=None, overwrite=False) -> bool:
        """Mappa färg till TS-kod med gemensam PIN."""
        return self.service.add_mapping(color_name, ts_code, pin=pin, overwrite=overwrite)

    def get_color_mappings(self) -> Dict[str, str]:
        """Hämta alla mappningar."""
        return self.service.get_all_mappings()

    def search_colors(self, query: str) -> List[Color]:
        """Sök färger."""
        return self.service.search(query)

    def get_statistics(self) -> Dict[str, Any]:
        """Hämta statistik."""
        return self.service.get_statistics()

    # ------------------------------------------------------------------
    # Legacy API
    # ------------------------------------------------------------------

    def load_from_json(self) -> List[Dict[str, Any]]:
        """Legacy: Ladda färger som dict-lista."""
        return [color.to_dict() for color in self.service.get_all()]

    def save_to_json(self, data: Any = None) -> bool:
        """Legacy: Spara färger."""
        _ = data
        return self.service.save()

    def set_original_colors(self, colors: List[str]) -> None:
        """Legacy: Sätt omappade färger."""
        if self._widget:
            unmapped = self.service.get_unmapped_sample(colors)
            self._widget.set_unmapped_colors(unmapped)

    def sync_to_db(self, colors: Any = None) -> int:
        """Legacy: Synka till databas."""
        _ = colors
        return 0

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def record_dispatch_colors(self, colors: List[str]) -> ColorOperationResult:
        result = self.service.add_dispatch_names(colors)
        if result.success and self._widget:
            self._widget.set_unmapped_colors(self.service.get_unmapped_sample(colors))
            self._widget.refresh()
        return result

    def _on_colors_found(self, data: Dict[str, Any]) -> None:
        colors = data.get("colors", [])
        if colors:
            result = self.record_dispatch_colors(colors)
            if not result.success and self._widget:
                QMessageBox.warning(self._widget, "Dispatch-färger", result.message)



# ══════════════════════════════════════════════════════════════════════════════
# WIDGET
# ══════════════════════════════════════════════════════════════════════════════


class ColorsWidget(QWidget):
    """
    Widget för färghantering.
    """

    def __init__(self, parent: QWidget, service: ColorService):
        super().__init__(parent)
        self.service = service
        self._unmapped: List[Tuple[str, ColorLookupResult]] = []
        self._mapping_drafts: Dict[str, str] = {}

        self._setup_ui()
        self._connect_signals()
        self.refresh()

    def _setup_ui(self) -> None:
        """Bygg UI."""
        from PySide6.QtWidgets import QScrollArea
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        outer.addWidget(scroll)
        scroll.setWidget(inner)

        header = self._create_header()
        layout.addWidget(header)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        left_panel = self._create_colors_panel()
        splitter.addWidget(left_panel)

        right_panel = self._create_unmapped_panel()
        splitter.addWidget(right_panel)

        splitter.setSizes([500, 200])
        layout.addWidget(splitter, 1)

        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)
        note = QLabel("Ändringar kräver samma PIN som för återförsäljare. TS-koder och förslag är ännu inte verifierade mot en komplett specifikation.")
        note.setWordWrap(True)
        layout.addWidget(note)

    def _create_header(self) -> QWidget:
        """Skapa header."""
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 8)

        title = QLabel("🎨 Färghantering")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setWordWrap(True)
        layout.addWidget(title)

        layout.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Sök färg...")
        self.search_input.setMinimumWidth(100)
        layout.addWidget(self.search_input, 1)

        btn_refresh = QPushButton("🔄")
        btn_refresh.setFixedSize(36, 36)
        btn_refresh.clicked.connect(self.refresh)
        layout.addWidget(btn_refresh)

        return frame

    def _create_colors_panel(self) -> QGroupBox:
        """Skapa färgpanel."""
        group = QGroupBox("Registrerade färger")
        layout = QVBoxLayout(group)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Kod", "Namn", "TS-kod", "TS-namn", "Tillverkare", "Hex"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setResizeContentsPrecision(-1)
        header.setStretchLastSection(False)
        self._auto_color_columns = True
        self._setting_color_widths = False
        self._color_natural_widths = []
        from PySide6.QtCore import QTimer
        self._color_resize_timer = QTimer(self)
        self._color_resize_timer.setSingleShot(True)
        self._color_resize_timer.timeout.connect(
            lambda: self._apply_color_column_widths(self.table.viewport().width()))
        header.sectionResized.connect(self._color_column_resized)
        self.table.viewport().installEventFilter(self)

        layout.addWidget(self.table)

        from plugins.main_gui.flow_layout import FlowLayout
        btn_layout = FlowLayout()

        self.btn_add = QPushButton("➕ Lägg till")
        self.btn_add.clicked.connect(self._on_add)
        btn_layout.addWidget(self.btn_add)

        self.btn_edit = QPushButton("✏️ Redigera")
        self.btn_edit.clicked.connect(self._on_edit)
        btn_layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton("🗑️ Ta bort")
        self.btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.btn_delete)

        btn_fit = QPushButton("↔ Anpassa kolumner")
        btn_fit.clicked.connect(self._restore_color_columns)
        btn_layout.addWidget(btn_fit)

        self.count_label = QLabel("0 färger")
        self.count_label.setWordWrap(True)
        btn_layout.addWidget(self.count_label)

        layout.addLayout(btn_layout)
        return group

    def _create_unmapped_panel(self) -> QGroupBox:
        """Skapa panel för omappade färger."""
        group = QGroupBox("Färgmappningar och förslag")
        layout = QVBoxLayout(group)

        self.unmapped_table = QTableWidget()
        self.unmapped_table.setColumnCount(5)
        self.unmapped_table.setHorizontalHeaderLabels(["Färg", "Sparad kod", "Förslag – ej verifierat", "Träff", "Välj kod"])
        self.unmapped_table.setAlternatingRowColors(True)
        self.unmapped_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.unmapped_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.unmapped_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.unmapped_table.verticalHeader().setVisible(False)

        header = self.unmapped_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        layout.addWidget(self.unmapped_table)

        from plugins.main_gui.flow_layout import FlowLayout
        btn_layout = FlowLayout()

        self.btn_map = QPushButton("🔗 Bekräfta vald mappning")
        self.btn_map.clicked.connect(self._on_map)
        btn_layout.addWidget(self.btn_map)
        self.btn_remove_mapping = QPushButton("🗑 Ta bort mappning")
        self.btn_remove_mapping.clicked.connect(self._on_remove_mapping)
        btn_layout.addWidget(self.btn_remove_mapping)

        layout.addLayout(btn_layout)

        return group

    def _connect_signals(self) -> None:
        """Koppla signaler."""
        self.search_input.textChanged.connect(self._on_search)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

    def refresh(self) -> None:
        """Uppdatera data."""
        try:
            self.service.load()
            self._populate_table()
            self._update_stats()
            self._populate_unmapped_table()
            self.btn_add.setEnabled(True)
            self.btn_map.setEnabled(True)
            self.btn_remove_mapping.setEnabled(True)
            self._on_selection_changed()
        except Exception as exc:
            self.stats_label.setText(f"Färgdata kunde inte läsas: {exc}. Inga uppgifter har ändrats.")
            self.btn_add.setEnabled(False)
            self.btn_edit.setEnabled(False)
            self.btn_delete.setEnabled(False)
            self.btn_map.setEnabled(False)
            self.btn_remove_mapping.setEnabled(False)

    def set_unmapped_colors(
        self,
        unmapped: List[Tuple[str, ColorLookupResult]],
    ) -> None:
        """Sätt omappade färger."""
        self._unmapped = unmapped
        self._populate_unmapped_table()

    def _populate_table(self) -> None:
        """Fyll tabell med färger."""
        query = self.search_input.text().strip()
        colors = self.service.search(query)

        # Sortering under insättning kan flytta rader innan alla celler satts.
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        try:
            self.table.setRowCount(0)
            mapping = self.service.get_all_mappings()
            for color in colors:
                row = self.table.rowCount()
                self.table.insertRow(row)
                ts = TSColorCode.from_code(color.ts_code)
                ts_name = ts.display_name if ts else ""
                saved = mapping.get(color.name.lower(), "").upper()
                if saved and color.ts_code and saved != color.ts_code:
                    ts_name = (ts_name + " ⚠ Motstridig mappning").strip()
                values = (color.code, color.name, color.ts_code, ts_name,
                          color.manufacturer, color.hex_value)
                for col, value in enumerate(values):
                    text = str(value or "")
                    item = QTableWidgetItem(" ↵ ".join(text.splitlines()))
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, color.storage_key)
                    item.setToolTip(text)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, col, item)
        finally:
            self.table.setSortingEnabled(sorting)
        if self._auto_color_columns:
            self._fit_color_columns()
        self.count_label.setText(f"{len(colors)} färger")

    def _color_column_resized(self, _index, _old, _new) -> None:
        if not self._setting_color_widths:
            self._auto_color_columns = False

    def _restore_color_columns(self) -> None:
        self._auto_color_columns = True
        self._fit_color_columns()

    def _fit_color_columns(self) -> None:
        if not self._auto_color_columns:
            return
        header = self.table.horizontalHeader()
        self._setting_color_widths = True
        try:
            self.table.resizeColumnsToContents()
            self._color_natural_widths = [header.sectionSize(i) for i in range(self.table.columnCount())]
        finally:
            self._setting_color_widths = False
        self._apply_color_column_widths(self.table.viewport().width())

    def _apply_color_column_widths(self, width: int) -> None:
        if not self._auto_color_columns or not self._color_natural_widths or self._setting_color_widths:
            return
        from core.responsive_layout import fit_columns
        header = self.table.horizontalHeader()
        self._setting_color_widths = True
        try:
            for index, value in enumerate(fit_columns(self._color_natural_widths, width)):
                header.resizeSection(index, value)
        finally:
            self._setting_color_widths = False

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if hasattr(self, "table") and watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            self._color_resize_timer.start(0)
        return super().eventFilter(watched, event)

    def _populate_unmapped_table(self) -> None:
        """Fyll omappade-tabell."""
        self.unmapped_table.setRowCount(0)
        saved = self.service.get_mapping_display()
        pending = {name.strip().lower(): (name, result) for name, result in self._unmapped}
        rows = [(name, pending.pop(name.strip().lower(), None), code) for name, code in saved.items()]
        rows.extend((name, (name, result), "") for name, result in pending.values())
        query = self.search_input.text().strip().casefold()
        for color_name, candidate, saved_code in rows:
            result = candidate[1] if candidate else self.service.lookup_ts_code_detailed(color_name)
            if query and not any(query in str(value).casefold() for value in (color_name, saved_code, result.ts_code, result.match_type)):
                continue
            row = self.unmapped_table.rowCount()
            self.unmapped_table.insertRow(row)
            proposal = ("Motstridiga sparade värden" if result.match_type == "conflict" else
                        result.ts_code if result.match_type != "exact" and result.ts_code else "")
            for col, text in enumerate((color_name, saved_code, proposal, result.match_type)):
                item = QTableWidgetItem(str(text))
                item.setToolTip(str(text))
                self.unmapped_table.setItem(row, col, item)
            combo = QComboBox()
            combo.addItem("-- Välj själv --", "")
            for ts in TSColorCode:
                combo.addItem(f"{ts.code} - {ts.display_name}", ts.code)
            draft = self._mapping_drafts.get(color_name.strip().lower(), "")
            if draft:
                index = combo.findData(draft)
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(
                lambda _index, name=color_name, widget=combo: self._remember_mapping_draft(name, widget.currentData()))
            self.unmapped_table.setCellWidget(row, 4, combo)

    def _remember_mapping_draft(self, color_name: str, value) -> None:
        key = color_name.strip().lower()
        if value:
            self._mapping_drafts[key] = str(value)
        else:
            self._mapping_drafts.pop(key, None)

    def _update_stats(self) -> None:
        """Uppdatera statistik."""
        stats = self.service.get_statistics()
        self.stats_label.setText(
            f"📊 {stats['total_colors']} färger | "
            f"{stats['mapped_colors']} färgposter med kod | "
            f"{stats['total_mappings']} sparade mappningar | "
            f"{stats['conflicts']} motstridiga namn"
        )

    def _on_search(self, _text: str = "") -> None:
        """Hantera sökning."""
        try:
            self._populate_table()
            self._populate_unmapped_table()
        except Exception as exc:
            self.stats_label.setText(f"Sökningen kunde inte slutföras: {exc}")

    def _on_selection_changed(self) -> None:
        """Hantera vald rad."""
        has_selection = len(self.table.selectedItems()) > 0
        self.btn_edit.setEnabled(has_selection)
        self.btn_delete.setEnabled(has_selection)

    def _on_add(self) -> None:
        """Lägg till färg."""
        dialog = ColorDialog(self, "Lägg till färg")
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            from plugins.main_gui.dialogs.dealer_pin import request_pin
            pin = request_pin(self, self.service, resource="färgregistret")
            if pin is None:
                return
            result = self.service.add(**data, pin=pin)

            if result.success:
                self.refresh()
                QMessageBox.information(self, "Tillagd", result.message)
            else:
                QMessageBox.warning(self, "Fel", result.message)

    def _on_edit(self) -> None:
        """Redigera vald färg."""
        row = self.table.currentRow()
        if row < 0:
            return

        code = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        color = self.service.get_by_code(code)
        if not color:
            return

        dialog = ColorDialog(self, "Redigera färg", color)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            new_code = data.pop("code")
            if color.code and new_code != color.code:
                answer = QMessageBox.question(self, "Ändra färgkod",
                    "Andra uppgifter kan hänvisa till den gamla färgkoden. De uppdateras inte automatiskt. Fortsätta?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    return
            from plugins.main_gui.dialogs.dealer_pin import request_pin
            pin = request_pin(self, self.service, resource="färgregistret")
            if pin is None:
                return
            result = self.service.update(code, new_code=new_code, pin=pin, expected_color=color, **data)

            if result.success:
                self.refresh()
            else:
                QMessageBox.warning(self, "Fel", result.message)

    def _on_delete(self) -> None:
        """Ta bort vald färg."""
        row = self.table.currentRow()
        if row < 0:
            return

        code = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        name = self.table.item(row, 1).text()

        color = self.service.get_by_code(code)
        if color is None:
            return
        reply = QMessageBox.question(
            self, "Bekräfta borttagning",
            f"Ta bort färg '{name}' ({code})? Separata färgmappningar bevaras.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            from plugins.main_gui.dialogs.dealer_pin import request_pin
            pin = request_pin(self, self.service, resource="färgregistret")
            if pin is None:
                return
            result = self.service.delete(code, pin=pin, expected_color=color)
            if result.success:
                self.refresh()
            else:
                QMessageBox.warning(self, "Fel", result.message)

    def _on_map(self) -> None:
        """Mappa vald omappad färg."""
        row = self.unmapped_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Info", "Välj en färg att mappa")
            return

        color_name = self.unmapped_table.item(row, 0).text()
        combo = self.unmapped_table.cellWidget(row, 4)

        if not isinstance(combo, QComboBox):
            return

        ts_code = combo.currentData()
        if not ts_code:
            QMessageBox.warning(self, "Välj kod", "Välj en TS-kod")
            return

        existing = self.service.get_all_mappings().get(color_name.strip().lower())
        overwrite = False
        if existing and existing != ts_code:
            answer = QMessageBox.question(self, "Mappningen finns redan",
                f"Befintlig kod: {existing}\nNy kod: {ts_code}\nVill du ersätta den sparade mappningen?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            overwrite = True
        from plugins.main_gui.dialogs.dealer_pin import request_pin
        pin = request_pin(self, self.service, resource="färgmappningarna")
        if pin is None:
            return
        if self.service.add_mapping(color_name, ts_code, pin=pin, overwrite=overwrite):
            self._mapping_drafts.pop(color_name.strip().lower(), None)
            self._unmapped = [
                (color, result)
                for color, result in self._unmapped
                if color != color_name
            ]
            self._populate_unmapped_table()
            self.refresh()

            ts = TSColorCode.from_code(ts_code)
            ts_name = ts.display_name if ts else ts_code

            QMessageBox.information(
                self,
                "Mappat",
                f"'{color_name}' → {ts_code} ({ts_name}). Kontrollera koden mot den officiella specifikationen.",
            )
        else:
            QMessageBox.warning(self, "Kunde inte spara", "Mappningen sparades inte. Kontrollera PIN, filer och säkerhetskopiering.")

    def _on_remove_mapping(self) -> None:
        row = self.unmapped_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Info", "Välj en sparad mappning först")
            return
        name = self.unmapped_table.item(row, 0).text()
        mappings = self.service.get_all_mappings()
        if name.strip().lower() not in mappings:
            QMessageBox.information(self, "Info", "Raden är ett förslag och saknar sparad mappning.")
            return
        existing = mappings[name.strip().lower()]
        answer = QMessageBox.question(self, "Ta bort färgmappning",
            f"Ta bort den sparade mappningen '{name}' → {existing}? Färgposter påverkas inte.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        from plugins.main_gui.dialogs.dealer_pin import request_pin
        pin = request_pin(self, self.service, resource="färgmappningarna")
        if pin is None:
            return
        if self.service.delete_mapping(name, pin=pin):
            self._mapping_drafts.pop(name.strip().lower(), None)
            self.refresh()
        else:
            QMessageBox.warning(self, "Kunde inte spara", "Mappningen togs inte bort. Kontrollera PIN, filer och säkerhetskopiering.")

    def _on_auto_map(self) -> None:
        """Förslag får aldrig automatiskt bli en sparad TS-mappning."""
        QMessageBox.information(self, "Färgmappning", "Välj och bekräfta varje mappning manuellt.")


# ══════════════════════════════════════════════════════════════════════════════
# COLOR DIALOG
# ══════════════════════════════════════════════════════════════════════════════


class ColorDialog(QDialog):
    """Dialog för att lägga till/redigera färg."""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        color: Optional[Color] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)

        self._color = color
        self._setup_ui()

        if color:
            self._populate(color)

    def _setup_ui(self) -> None:
        """Bygg UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QGridLayout()
        form.setSpacing(8)

        form.addWidget(QLabel("Kod:"), 0, 0)
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("T.ex. 300, A96")
        form.addWidget(self.code_input, 0, 1)

        form.addWidget(QLabel("Namn:"), 1, 0)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("T.ex. Alpine White")
        form.addWidget(self.name_input, 1, 1)

        form.addWidget(QLabel("TS-kod:"), 2, 0)
        self.ts_combo = QComboBox()
        self.ts_combo.addItem("-- Välj --", "")
        for ts in TSColorCode:
            self.ts_combo.addItem(f"{ts.code} - {ts.display_name}", ts.code)
        form.addWidget(self.ts_combo, 2, 1)

        form.addWidget(QLabel("Tillverkare:"), 3, 0)
        self.manufacturer_input = QLineEdit()
        self.manufacturer_input.setPlaceholderText("T.ex. BMW, Volvo")
        form.addWidget(self.manufacturer_input, 3, 1)

        form.addWidget(QLabel("Hex-färg:"), 4, 0)
        self.hex_input = QLineEdit()
        self.hex_input.setPlaceholderText("#FFFFFF")
        form.addWidget(self.hex_input, 4, 1)

        layout.addLayout(form)

        auto_btn = QPushButton("🔍 Visa förslag (ej verifierat)")
        auto_btn.clicked.connect(self._auto_detect)
        layout.addWidget(auto_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, color: Color) -> None:
        """Fyll i fält från Color."""
        self.code_input.setText(color.code)

        self.name_input.setText(color.name)

        idx = self.ts_combo.findData(color.ts_code)
        if idx < 0 and color.ts_code:
            self.ts_combo.addItem(f"{color.ts_code} - befintligt värde", color.ts_code)
            idx = self.ts_combo.findData(color.ts_code)
        if idx >= 0:
            self.ts_combo.setCurrentIndex(idx)

        self.manufacturer_input.setText(color.manufacturer)
        self.hex_input.setText(color.hex_value)

    def _auto_detect(self) -> None:
        """Auto-detektera TS-kod från namn."""
        name = self.name_input.text().strip()
        if not name:
            return

        name_lower = name.lower()
        for keyword, code in COLOR_KEYWORDS.items():
            if keyword in name_lower:
                idx = self.ts_combo.findData(code)
                if idx >= 0:
                    QMessageBox.information(self, "Förslag – ej verifierat",
                        f"Namnmatchning föreslår {code}. Välj själv i listan och kontrollera koden mot specifikationen.")
                    return
        QMessageBox.information(self, "Förslag", "Inget namnförslag hittades.")

    def _validate_and_accept(self) -> None:
        """Validera och acceptera."""
        code = self.code_input.text().strip()
        name = self.name_input.text().strip()

        if not code and not (self._color and self._color._original.get("dispatch_pending_id")):
            QMessageBox.warning(self, "Validering", "Kod krävs")
            self.code_input.setFocus()
            return

        if not name:
            QMessageBox.warning(self, "Validering", "Namn krävs")
            self.name_input.setFocus()
            return

        self.accept()

    def get_data(self) -> Dict[str, str]:
        """Hämta data."""
        return {
            "code": self.code_input.text().strip(),
            "name": self.name_input.text().strip(),
            "ts_code": self.ts_combo.currentData() or "",
            "manufacturer": self.manufacturer_input.text().strip(),
            "hex_value": self.hex_input.text().strip(),
        }


__all__ = [
    "Plugin",
    "ColorService",
    "Color",
    "ColorLookupResult",
    "ColorOperationResult",
    "TSColorCode",
    "COLOR_KEYWORDS",
]