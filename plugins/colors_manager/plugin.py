# -*- coding: utf-8 -*-
"""
Colors Manager Plugin v3.0.0

Hanterar färgkoder och mappning till Transportstyrelsen.

Features:
    - Färgregister med CRUD-operationer
    - TS-kodmappning med fuzzy matching
    - Caching för snabba uppslagningar
    - Event-baserad kommunikation
    - Import/Export-stöd
    - Auto-mappning av okända färger

Används av:
    - ts_file_generator (lookup_ts_code)
    - vehicle_registry (get_color_display)
    - dispatch_viewer (color validation)
"""

from __future__ import annotations

import json
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
    Transportstyrelsens färgkoder.
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
        )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "kod": self.code,
            "namn": self.name,
            "ts_kod": self.ts_code,
            "manufacturer": self.manufacturer,
            "hex": self.hex_value,
            "created_at": self.created_at,
        }

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
        """True om vi är säkra på matchningen."""
        return self.confidence >= 0.8


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
    ):
        self.colors_file = colors_file
        self.mappings_file = mappings_file
        self.event_bus = event_bus

        self._colors: Dict[str, Color] = {}
        self._mappings: Dict[str, str] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------

    def load(self) -> int:
        """Ladda färger och mappningar från disk."""
        self._colors.clear()
        self._mappings.clear()

        if self.colors_file.exists():
            try:
                data = read_json_with_comments(self.colors_file)

                if isinstance(data, dict) and "colors" in data:
                    data = data["colors"]

                if isinstance(data, dict):
                    data = [data]

                for item in data:
                    if isinstance(item, dict):
                        try:
                            color = Color.from_dict(item)
                            self._colors[color.code] = color
                        except ValidationError as exc:
                            logger.warning("Invalid color data: %s", exc)

            except Exception as exc:
                logger.error("Failed to load colors: %s", exc)

        if self.mappings_file.exists():
            try:
                data = read_json_with_comments(self.mappings_file)
                if isinstance(data, dict):
                    self._mappings = dict(data.get("mappings", {}))
            except Exception as exc:
                logger.warning("Failed to load mappings: %s", exc)

        self._loaded = True
        self._clear_cache()

        logger.info(
            "Loaded %s colors, %s mappings",
            len(self._colors),
            len(self._mappings),
        )
        return len(self._colors)

    def save(self) -> bool:
        """Spara färger och mappningar till disk."""
        try:
            colors_data = [color.to_dict() for color in self._colors.values()]
            write_json_with_header(self.colors_file, colors_data)

            mappings_data = {
                "mappings": self._mappings,
                "_meta": {
                    "updated_at": datetime.now().isoformat(),
                    "count": len(self._mappings),
                },
            }
            write_json_with_header(self.mappings_file, mappings_data)

            logger.info("Saved %s colors", len(self._colors))
            return True

        except Exception as exc:
            logger.error("Failed to save colors: %s", exc)
            return False

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_all(self) -> List[Color]:
        """Hämta alla färger."""
        self._ensure_loaded()
        return list(self._colors.values())

    def get_by_code(self, code: str) -> Optional[Color]:
        """Hämta färg med kod."""
        self._ensure_loaded()
        return self._colors.get(str(code).strip())

    def get_by_name(self, name: str) -> Optional[Color]:
        """Hämta färg med namn."""
        self._ensure_loaded()
        name_lower = str(name).lower().strip()

        for color in self._colors.values():
            if color.name.lower() == name_lower:
                return color
        return None

    def add(
        self,
        code: str,
        name: str,
        ts_code: str = "",
        **extra: Any,
    ) -> ColorOperationResult:
        """Lägg till färg."""
        self._ensure_loaded()

        code = str(code).strip()
        name = str(name).strip()

        if not code or not name:
            return ColorOperationResult(False, "Kod och namn krävs")

        if code in self._colors:
            return ColorOperationResult(False, f"Färg med kod '{code}' finns redan")

        if self.get_by_name(name):
            return ColorOperationResult(False, f"Färg med namn '{name}' finns redan")

        try:
            color = Color(
                code=code,
                name=name,
                ts_code=ts_code,
                manufacturer=str(extra.get("manufacturer", "")),
                hex_value=str(extra.get("hex_value", "")),
            )

            self._colors[code] = color

            if ts_code:
                self._mappings[name.lower()] = ts_code.upper()

            self.save()
            self._clear_cache()

            self._emit("colors:added", {"color": color.to_dict()})
            logger.info("Added color: %s - %s", code, name)

            return ColorOperationResult(
                success=True,
                message=f"Färg '{name}' tillagd",
                color=color,
                affected_count=1,
            )

        except ValidationError as exc:
            return ColorOperationResult(False, str(exc))

    def update(self, code: str, **updates: Any) -> ColorOperationResult:
        """Uppdatera färg."""
        self._ensure_loaded()

        code = str(code).strip()
        color = self._colors.get(code)
        if not color:
            return ColorOperationResult(False, f"Färg '{code}' finns inte")

        new_name = str(updates.get("name", color.name)).strip()
        if new_name.lower() != color.name.lower():
            duplicate = self.get_by_name(new_name)
            if duplicate and duplicate.code != code:
                return ColorOperationResult(
                    False,
                    f"Färg med namn '{new_name}' finns redan",
                )

        old_name_lower = color.name.lower()
        self._mappings.pop(old_name_lower, None)

        color.name = new_name
        color.ts_code = str(updates.get("ts_code", color.ts_code)).strip().upper()
        color.manufacturer = str(updates.get("manufacturer", color.manufacturer)).strip()
        color.hex_value = str(updates.get("hex_value", color.hex_value)).strip()

        if color.ts_code:
            self._mappings[color.name.lower()] = color.ts_code

        self.save()
        self._clear_cache()

        self._emit("colors:updated", {"color": color.to_dict()})

        return ColorOperationResult(
            success=True,
            message=f"Färg '{color.name}' uppdaterad",
            color=color,
            affected_count=1,
        )

    def delete(self, code: str) -> ColorOperationResult:
        """Ta bort färg."""
        self._ensure_loaded()

        code = str(code).strip()
        color = self._colors.pop(code, None)
        if not color:
            return ColorOperationResult(False, f"Färg '{code}' finns inte")

        self._mappings.pop(color.name.lower(), None)

        self.save()
        self._clear_cache()

        self._emit("colors:deleted", {"code": code, "name": color.name})
        logger.info("Deleted color: %s - %s", code, color.name)

        return ColorOperationResult(
            success=True,
            message=f"Färg '{color.name}' borttagen",
            color=color,
            affected_count=1,
        )

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup_ts_code(self, color_name: str) -> str:
        """Slå upp TS-kod för färgnamn."""
        result = self.lookup_ts_code_detailed(color_name)
        return result.ts_code

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

        if clean_name in self._mappings:
            return ColorLookupResult(
                ts_code=self._mappings[clean_name],
                confidence=1.0,
                match_type="exact",
                source_color=clean_name,
                matched_to=clean_name,
            )

        for ts_code in TSColorCode:
            if clean_name == ts_code.display_name.lower():
                return ColorLookupResult(
                    ts_code=ts_code.code,
                    confidence=1.0,
                    match_type="exact",
                    source_color=clean_name,
                    matched_to=ts_code.display_name,
                )

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

    def add_mapping(self, color_name: str, ts_code: str) -> bool:
        """Lägg till färgmappning."""
        color_name = str(color_name).strip()
        ts_code = str(ts_code).strip().upper()

        if not color_name or not ts_code:
            return False

        if not TSColorCode.from_code(ts_code):
            logger.warning("Invalid TS code: %s", ts_code)
            return False

        self._mappings[color_name.lower()] = ts_code
        self.save()
        self._clear_cache()

        self._emit(
            "colors:mapping_added",
            {"color": color_name, "ts_code": ts_code},
        )

        logger.debug("Added mapping: %s -> %s", color_name, ts_code)
        return True

    def get_all_mappings(self) -> Dict[str, str]:
        """Hämta alla mappningar."""
        self._ensure_loaded()
        return self._mappings.copy()

    def get_unmapped_sample(
        self,
        colors: List[str],
        limit: int = 50,
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
            if result.confidence < 0.8:
                results.append((color_name, result))
                if len(results) >= limit:
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
            return list(self._colors.values())

        query_lower = query.lower()
        results: List[Color] = []

        for color in self._colors.values():
            if (
                query_lower in color.code.lower()
                or query_lower in color.name.lower()
                or query_lower in color.ts_code.lower()
                or query_lower in color.manufacturer.lower()
            ):
                results.append(color)

        return results

    def get_statistics(self) -> Dict[str, Any]:
        """Hämta statistik."""
        self._ensure_loaded()

        mapped_count = sum(1 for color in self._colors.values() if color.ts_code)

        ts_distribution: Dict[str, int] = {}
        for color in self._colors.values():
            if color.ts_code:
                ts_distribution[color.ts_code] = ts_distribution.get(color.ts_code, 0) + 1

        return {
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
        if result.ts_code:
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
            )

            count = self._service.load()

            self.app.colors = self
            self.app.colors_manager = self

            logger.info("Colors Manager initialized with %s colors", count)
            return True

        except Exception:
            logger.exception("Failed to initialize Colors Manager")
            return False

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
    ) -> ColorOperationResult:
        """Lägg till färg."""
        return self.service.add(code, name, ts_code)

    def update_color(self, code: str, **updates: Any) -> ColorOperationResult:
        """Uppdatera färg."""
        return self.service.update(code, **updates)

    def delete_color(self, code: str) -> ColorOperationResult:
        """Ta bort färg."""
        return self.service.delete(code)

    def map_color(self, color_name: str, ts_code: str) -> bool:
        """Mappa färg till TS-kod."""
        return self.service.add_mapping(color_name, ts_code)

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

    def _on_colors_found(self, data: Dict[str, Any]) -> None:
        """Hantera färger från dispatch."""
        colors = data.get("colors", [])
        if colors and self._widget:
            unmapped = self.service.get_unmapped_sample(colors)
            self._widget.set_unmapped_colors(unmapped)


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

        self._setup_ui()
        self._connect_signals()
        self.refresh()

    def _setup_ui(self) -> None:
        """Bygg UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = self._create_header()
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)

        left_panel = self._create_colors_panel()
        splitter.addWidget(left_panel)

        right_panel = self._create_unmapped_panel()
        splitter.addWidget(right_panel)

        splitter.setSizes([600, 400])
        layout.addWidget(splitter, 1)

        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)

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
        self.search_input.setFixedWidth(250)
        layout.addWidget(self.search_input)

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
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Kod", "Namn", "TS-kod", "TS-namn"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()

        self.btn_add = QPushButton("➕ Lägg till")
        self.btn_add.clicked.connect(self._on_add)
        btn_layout.addWidget(self.btn_add)

        self.btn_edit = QPushButton("✏️ Redigera")
        self.btn_edit.clicked.connect(self._on_edit)
        btn_layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton("🗑️ Ta bort")
        self.btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.btn_delete)

        btn_layout.addStretch()

        self.count_label = QLabel("0 färger")
        self.count_label.setWordWrap(True)
        btn_layout.addWidget(self.count_label)

        layout.addLayout(btn_layout)
        return group

    def _create_unmapped_panel(self) -> QGroupBox:
        """Skapa panel för omappade färger."""
        group = QGroupBox("⚠️ Omappade färger")
        layout = QVBoxLayout(group)

        self.unmapped_table = QTableWidget()
        self.unmapped_table.setColumnCount(3)
        self.unmapped_table.setHorizontalHeaderLabels(["Färg", "Confidence", "TS-kod"])
        self.unmapped_table.setAlternatingRowColors(True)
        self.unmapped_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.unmapped_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.unmapped_table.verticalHeader().setVisible(False)

        header = self.unmapped_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        layout.addWidget(self.unmapped_table)

        btn_layout = QHBoxLayout()

        self.btn_map = QPushButton("🔗 Mappa vald")
        self.btn_map.clicked.connect(self._on_map)
        btn_layout.addWidget(self.btn_map)

        self.btn_auto_map = QPushButton("⚡ Auto-mappa alla")
        self.btn_auto_map.clicked.connect(self._on_auto_map)
        btn_layout.addWidget(self.btn_auto_map)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return group

    def _connect_signals(self) -> None:
        """Koppla signaler."""
        self.search_input.textChanged.connect(self._on_search)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

    def refresh(self) -> None:
        """Uppdatera data."""
        self._populate_table()
        self._update_stats()
        self._on_selection_changed()

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

        self.table.setRowCount(0)

        for color in colors:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(color.code))
            self.table.setItem(row, 1, QTableWidgetItem(color.name))

            ts_item = QTableWidgetItem(color.ts_code)
            if not color.ts_code:
                ts_item.setForeground(QBrush(QColor("#ff4444")))
            self.table.setItem(row, 2, ts_item)

            ts = TSColorCode.from_code(color.ts_code)
            ts_name = ts.display_name if ts else ""
            self.table.setItem(row, 3, QTableWidgetItem(ts_name))

        self.count_label.setText(f"{len(colors)} färger")

    def _populate_unmapped_table(self) -> None:
        """Fyll omappade-tabell."""
        self.unmapped_table.setRowCount(0)

        for color_name, result in self._unmapped:
            row = self.unmapped_table.rowCount()
            self.unmapped_table.insertRow(row)

            self.unmapped_table.setItem(row, 0, QTableWidgetItem(color_name))

            conf_pct = f"{result.confidence * 100:.0f}%"
            conf_item = QTableWidgetItem(conf_pct)
            if result.confidence < 0.5:
                conf_item.setForeground(QBrush(QColor("#ff4444")))
            elif result.confidence < 0.8:
                conf_item.setForeground(QBrush(QColor("#ffaa00")))
            self.unmapped_table.setItem(row, 1, conf_item)

            combo = QComboBox()
            combo.addItem("-- Välj --", "")
            for ts in TSColorCode:
                combo.addItem(f"{ts.code} - {ts.display_name}", ts.code)

            if result.ts_code:
                idx = combo.findData(result.ts_code)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

            self.unmapped_table.setCellWidget(row, 2, combo)

    def _update_stats(self) -> None:
        """Uppdatera statistik."""
        stats = self.service.get_statistics()
        self.stats_label.setText(
            f"📊 {stats['total_colors']} färger | "
            f"{stats['mapped_colors']} mappade ({stats['coverage_percent']:.0f}%) | "
            f"{stats['total_mappings']} mappningar"
        )

    def _on_search(self, _text: str = "") -> None:
        """Hantera sökning."""
        self._populate_table()

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
            result = self.service.add(**data)

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

        code = self.table.item(row, 0).text()
        color = self.service.get_by_code(code)
        if not color:
            return

        dialog = ColorDialog(self, "Redigera färg", color)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            data.pop("code", None)  # kod är låst vid redigering
            result = self.service.update(code, **data)

            if result.success:
                self.refresh()
            else:
                QMessageBox.warning(self, "Fel", result.message)

    def _on_delete(self) -> None:
        """Ta bort vald färg."""
        row = self.table.currentRow()
        if row < 0:
            return

        code = self.table.item(row, 0).text()
        name = self.table.item(row, 1).text()

        reply = QMessageBox.question(
            self,
            "Bekräfta borttagning",
            f"Ta bort färg '{name}' ({code})?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            result = self.service.delete(code)
            if result.success:
                self.refresh()

    def _on_map(self) -> None:
        """Mappa vald omappad färg."""
        row = self.unmapped_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Info", "Välj en färg att mappa")
            return

        color_name = self.unmapped_table.item(row, 0).text()
        combo = self.unmapped_table.cellWidget(row, 2)

        if not isinstance(combo, QComboBox):
            return

        ts_code = combo.currentData()
        if not ts_code:
            QMessageBox.warning(self, "Välj kod", "Välj en TS-kod")
            return

        if self.service.add_mapping(color_name, ts_code):
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
                f"'{color_name}' → {ts_code} ({ts_name})",
            )

    def _on_auto_map(self) -> None:
        """Auto-mappa alla med hög confidence."""
        mapped = 0

        for color_name, result in self._unmapped[:]:
            if result.confidence >= 0.8 and result.ts_code:
                if self.service.add_mapping(color_name, result.ts_code):
                    self._unmapped.remove((color_name, result))
                    mapped += 1

        self._populate_unmapped_table()
        self.refresh()

        if mapped:
            QMessageBox.information(
                self,
                "Auto-mappning",
                f"Mappade {mapped} färger automatiskt",
            )
        else:
            QMessageBox.information(
                self,
                "Auto-mappning",
                "Inga färger kunde mappas automatiskt.\nMappa dem manuellt.",
            )


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

        auto_btn = QPushButton("🔍 Auto-detektera TS-kod")
        auto_btn.clicked.connect(self._auto_detect)
        layout.addWidget(auto_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, color: Color) -> None:
        """Fyll i fält från Color."""
        self.code_input.setText(color.code)
        self.code_input.setReadOnly(True)

        self.name_input.setText(color.name)

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
                    self.ts_combo.setCurrentIndex(idx)
                    return

    def _validate_and_accept(self) -> None:
        """Validera och acceptera."""
        code = self.code_input.text().strip()
        name = self.name_input.text().strip()

        if not code:
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