# -*- coding: utf-8 -*-

"""
Fil: plugins/vin_tracking/plugin.py

VIN Tracking Plugin

Hanterar registrering och spårning av VIN per år/månad.

Lagring (spec v1.4 / Sektion Z — primära sökvägar):
    json/vin_register/{YYYY}/{MM}.json
    json/rapporter/vin_rapport_{YYYY}.json

Legacy-sökvägar (läses som FALLBACK tills migrerade, Sektion Z):
    data/vin_register/{YYYY}/{MM}.json
    ut/rapporter/vin_rapport_{YYYY}.json

Event in:  vin:register              (spec)  + vin_tracking:register
Event ut:  vin:registered            (spec)  + vin_tracking:registered

FÖRÄNDRINGAR v1.2.0 (Session 11 — spec v1.4/v1.6, förbättringsregeln):

    - SPEC v1.4/SEKTION Z: registry_dir/report_dir-defaults uppdaterade
      till json/vin_register + json/rapporter. load_registry() läser
      från legacy data/vin_register som fallback om json/-katalogen
      saknar data (loggas INFO). Rapporter skrivs till json/rapporter.

    - EVENTS (spec-synk + bakåtkompatibilitet): prenumererar på både
      "vin:register" (spec) och "vin_tracking:register" (befintligt);
      emitterar både "vin:registered" (spec) och
      "vin_tracking:registered" (befintligt). Dubbla prenumerationer
      undviks.

    - PRESTANDA: register() skriver endast den aktuella månadsfilen
      i stället för hela registret (alla år/månader) per registrering.
      save_registry() finns kvar oförändrad som publik helsparare.

    - ROBUSTHET: get_statistics() tål korrupta/icke-ändliga värden
      (guard mot bool/NaN/inf, val 23-mönster); is_registered()
      normaliserar år till sträng.

    - config_schema(): defaults uppdaterade till json/-sökvägarna.

FÖRÄNDRINGAR v1.1.0 (Session 9):

    - KRASCHBUGG fixad: fd-läcka i atomic_write_text
      (closefd=False -> os.fdopen i with-block; Windows-säker
      os.replace).
    - registry_dir/report_dir läses från config (inga hårdkodade
      paths).

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugin_base import PluginBase


def get_logger() -> logging.Logger:
    """Returnerar modulens logger."""
    return logging.getLogger(__name__)


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return "Copyright © {} Rickard Längkvist".format(datetime.now().year)


_log = get_logger()

NAME = "VIN Tracking"
VERSION = "1.2.0"
DESCRIPTION = "VIN-registrering per år och månad"
AUTHOR = "Rickard Längkvist"
COPYRIGHT = get_copyright_string()
DEPENDENCIES: List[str] = []

# Config-nycklar och defaults (spec v1.4 / Sektion Z)
REGISTRY_DIR_KEY = "paths.vin_register_dir"
REGISTRY_DIR_DEFAULT = "json/vin_register"
REPORT_DIR_KEY = "paths.report_dir"
REPORT_DIR_DEFAULT = "json/rapporter"

# Legacy-fallback (Sektion Z — läses tills migrerade)
LEGACY_REGISTRY_DIR_DEFAULT = "data/vin_register"
LEGACY_REPORT_DIR_DEFAULT = "ut/rapporter"

# Event-namn (spec + bakåtkompatibilitet)
EVENT_REGISTER_SPEC = "vin:register"
EVENT_REGISTER_LEGACY = "vin_tracking:register"
EVENT_REGISTERED_SPEC = "vin:registered"
EVENT_REGISTERED_LEGACY = "vin_tracking:registered"


def get_config_value(app: Any, key: str, default: Any = None) -> Any:
    """Hämta config-värde säkert från app.config eller core_config."""
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

    core_config = None
    try:
        plugin_manager = getattr(app, "plugin_manager", None)
        if plugin_manager and hasattr(plugin_manager, "get_plugin"):
            core_config = plugin_manager.get_plugin("core_config")
    except Exception:
        core_config = None

    if core_config is not None:
        try:
            getter = getattr(core_config, "get_config_value", None)
            if callable(getter):
                value = getter(key, default)
                return default if value is None else value
        except Exception:
            pass

        try:
            getter = getattr(core_config, "get", None)
            if callable(getter):
                value = getter(key, default)
                return default if value is None else value
        except Exception:
            pass

    return default


def get_event_bus(app: Any) -> Any:
    """Hämta event bus säkert."""
    if app is None:
        return None
    return getattr(app, "event_bus", None) or getattr(app, "events", None)


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
        _log.exception("Kunde inte prenumerera på event '%s'", event_name)

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
        _log.exception("Kunde inte avprenumerera från event '%s'", event_name)

    return False


def emit_event_safe(
    app: Any,
    event_name: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
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
        _log.exception("Kunde inte emittera event '%s'", event_name)

    return False


def atomic_write_text(
    path: Path,
    content: str,
    encoding: str = "utf-8",
) -> None:
    """
    Skriv text atomiskt.

    Mönster enligt spec: tempfile.mkstemp -> os.fdopen -> flush ->
    fsync -> os.replace. ALDRIG closefd=False (BUGG #12).
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=".{}_".format(path.stem),
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
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


class Plugin(PluginBase):
    """VIN Tracking Plugin - VIN-register per år/månad."""

    NAME = NAME
    VERSION = VERSION
    DESCRIPTION = DESCRIPTION
    AUTHOR = AUTHOR
    COPYRIGHT = COPYRIGHT
    DEPENDENCIES = DEPENDENCIES

    def __init__(self, app: Any):
        super().__init__(app)
        self.is_active: bool = False
        self.registry_dir: Optional[Path] = None
        self.ut_dir: Optional[Path] = None
        self._cache: Dict[str, Any] = {}
        self._event_names: List[str] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Initiera plugin."""
        try:
            base_dir = Path(
                get_config_value(self.app, "paths.base_dir", ".") or "."
            )

            registry_sub = str(
                get_config_value(
                    self.app,
                    REGISTRY_DIR_KEY,
                    REGISTRY_DIR_DEFAULT,
                )
                or REGISTRY_DIR_DEFAULT
            )
            report_sub = str(
                get_config_value(
                    self.app,
                    REPORT_DIR_KEY,
                    REPORT_DIR_DEFAULT,
                )
                or REPORT_DIR_DEFAULT
            )

            # Legacy-fallback-sökvägar (Sektion Z)
            self._legacy_registry_dir = base_dir / LEGACY_REGISTRY_DIR_DEFAULT
            self._legacy_ut_dir = base_dir / LEGACY_REPORT_DIR_DEFAULT

            self.registry_dir = base_dir / registry_sub
            self.ut_dir = base_dir / report_sub

            self.registry_dir.mkdir(parents=True, exist_ok=True)
            self.ut_dir.mkdir(parents=True, exist_ok=True)

            if self.app is not None:
                setattr(self.app, "vin_tracking", self)

            _log.info(
                "%s v%s initierad (register: %s, rapporter: %s)",
                self.NAME,
                self.VERSION,
                self.registry_dir,
                self.ut_dir,
            )
            return True

        except Exception as exc:
            _log.exception("Kunde inte initiera %s: %s", self.NAME, exc)
            return False

    def activate(self) -> bool:
        """Aktivera plugin — prenumererar på registrerings-event."""
        self.is_active = True

        # Prenumerera på BÅDE spec-namn och legacy-namn (ingen dubbel)
        for event_name in (
            EVENT_REGISTER_SPEC,
            EVENT_REGISTER_LEGACY,
        ):
            if event_name not in self._event_names:
                if subscribe_event_safe(
                    self.app, event_name, self._on_register_event
                ):
                    self._event_names.append(event_name)

        if self._event_names:
            _log.info(
                "%s aktiverad (lyssnar: %s)",
                self.NAME,
                ", ".join(self._event_names),
            )
        else:
            _log.warning(
                "%s aktiverad men kunde inte registrera event-lyssnare",
                self.NAME,
            )

        return True

    def deactivate(self) -> bool:
        """Deaktivera plugin."""
        for event_name in self._event_names:
            unsubscribe_event_safe(
                self.app, event_name, self._on_register_event
            )
        self._event_names.clear()

        self.is_active = False
        _log.info("%s deaktiverad", self.NAME)
        return True

    # ------------------------------------------------------------------
    # Kontraktskompatibilitet
    # ------------------------------------------------------------------

    def init(self) -> bool:
        """Alias för initialize()."""
        return self.initialize()

    def register_ui(self, parent: Any) -> None:
        """Pluginet har ingen egen standardflik i denna version."""
        _ = parent
        return None

    def shutdown(self) -> bool:
        """Alias för deactivate()."""
        return self.deactivate()

    def config_schema(self) -> Dict[str, Any]:
        """Returnerar pluginets konfigurationsschema (spec v1.4/Z)."""
        return {
            "enabled": {
                "type": "boolean",
                "default": True,
                "description": "Aktivera VIN Tracking-pluginet.",
            },
            REGISTRY_DIR_KEY: {
                "type": "string",
                "default": REGISTRY_DIR_DEFAULT,
                "description": "Katalog för VIN-register per år/månad "
                               "(json/vin_register).",
            },
            REPORT_DIR_KEY: {
                "type": "string",
                "default": REPORT_DIR_DEFAULT,
                "description": "Katalog för genererade VIN-rapporter "
                               "(json/rapporter).",
            },
        }

    # ------------------------------------------------------------------
    # Event callback
    # ------------------------------------------------------------------

    def _on_register_event(self, data: Any) -> None:
        """Callback för registrerings-event."""
        if not data or not isinstance(data, dict):
            return

        try:
            self.register(
                vin=data.get("vin", ""),
                model_year=data.get("model_year", ""),
                registration_date=data.get("date"),
            )
        except Exception:
            _log.exception("Fel vid hantering av registrerings-event")

    # ------------------------------------------------------------------
    # Publika API
    # ------------------------------------------------------------------

    def _resolve_registry_source(self) -> Path:
        """
        Välj läs-katalog för registret.

        Spec v1.4 / Sektion Z: primär json/vin_register; läses från
        legacy data/vin_register som fallback OM den nya saknar data
        (loggas INFO).
        """
        if self.registry_dir is None:
            return self._legacy_registry_dir

        has_data = any(self.registry_dir.glob("20*/"))
        if not has_data and self._legacy_registry_dir.exists():
            legacy_has_data = any(self._legacy_registry_dir.glob("20*/"))
            if legacy_has_data:
                _log.info(
                    "Läser legacy VIN-register: %s",
                    self._legacy_registry_dir,
                )
                return self._legacy_registry_dir

        return self.registry_dir

    def load_registry(self) -> Dict[str, Any]:
        """
        Laddar VIN-register från json/vin_register/{YYYY}/{MM}.json
        (fallback: data/vin_register/...).

        Struktur:
            {
                "2025": {
                    "months": {
                        "05": {"name": "May", "vins": [...], "count": 0}
                    },
                    "total_count": 0,
                    "last_updated": "..."
                }
            }
        """
        source_dir = self._resolve_registry_source()

        cache_key = "registry"
        cached = self._cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

        registry: Dict[str, Any] = {}

        for year_dir in sorted(source_dir.glob("*")):
            if not year_dir.is_dir():
                continue

            year = year_dir.name
            if not re.fullmatch(r"20\d{2}", year):
                continue

            year_entry: Dict[str, Any] = {
                "months": {},
                "total_count": 0,
                "last_updated": "",
            }

            for month_file in sorted(year_dir.glob("*.json")):
                month = month_file.stem.zfill(2)

                try:
                    month_data = self._read_json(month_file)
                    if isinstance(month_data, dict):
                        vins = month_data.get("vins", [])
                        if not isinstance(vins, list):
                            vins = []

                        month_data["vins"] = sorted(
                            str(v).strip().upper()
                            for v in vins
                            if str(v).strip()
                        )
                        month_data["count"] = len(month_data["vins"])
                        year_entry["months"][month] = month_data
                        year_entry["total_count"] += len(month_data["vins"])
                except Exception:
                    _log.exception("Fel vid läsning av %s", month_file)

            year_entry["last_updated"] = datetime.now().isoformat(
                timespec="seconds"
            )
            registry[year] = year_entry

        self._cache[cache_key] = registry
        return registry

    def save_registry(self, registry: Dict[str, Any]) -> None:
        """
        Sparar VIN-register per år och månad (publik helsparare).

        Skriver ALLTID till primär sökväg (json/vin_register).
        """
        if self.registry_dir is None:
            raise RuntimeError("registry_dir är inte initierad")

        for year, year_data in registry.items():
            year_dir = self.registry_dir / str(year)
            year_dir.mkdir(parents=True, exist_ok=True)

            months = year_data.get("months", {})
            if not isinstance(months, dict):
                months = {}

            for month, month_data in months.items():
                month_file = year_dir / "{}.json".format(str(month).zfill(2))

                vins = month_data.get("vins", [])
                if not isinstance(vins, list):
                    vins = []

                cleaned_month_data = {
                    "name": month_data.get("name", ""),
                    "vins": sorted(
                        str(v).strip().upper()
                        for v in vins
                        if str(v).strip()
                    ),
                    "count": 0,
                    "last_updated": month_data.get(
                        "last_updated",
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                }
                cleaned_month_data["count"] = len(
                    cleaned_month_data["vins"]
                )

                self._write_json(month_file, cleaned_month_data)

            year_data["total_count"] = sum(
                len(month_data.get("vins", []))
                for month_data in months.values()
                if isinstance(month_data, dict)
            )
            year_data["last_updated"] = datetime.now().isoformat(
                timespec="seconds"
            )

        self._cache.pop("registry", None)
        _log.info("Sparade VIN-register för %s år", len(registry))

    def register(
        self,
        vin: str,
        model_year: str,
        registration_date: Optional[str] = None,
    ) -> bool:
        """
        Registrerar ett VIN.

        Args:
            vin: VIN-nummer
            model_year: Modellår
            registration_date: Registreringsdatum (ISO), default = nu

        Returns:
            True om nytt VIN registrerades, False om redan finns
            (inom samma år) eller ogiltigt
        """
        if not vin or not model_year:
            return False

        vin = str(vin).strip().upper()
        if not vin:
            return False

        try:
            reg_date = (
                datetime.fromisoformat(registration_date)
                if registration_date
                else datetime.now()
            )
        except ValueError:
            reg_date = datetime.now()

        year = reg_date.strftime("%Y")
        month = reg_date.strftime("%m")
        month_name = reg_date.strftime("%B")

        registry = self.load_registry()

        year_entry = registry.setdefault(
            year,
            {
                "months": {},
                "total_count": 0,
                "last_updated": "",
            },
        )

        # Dublettkontroll inom samma år (spec: dubletter stoppas inom år)
        for existing_month_data in year_entry["months"].values():
            if vin in existing_month_data.get("vins", []):
                return False

        month_entry = year_entry["months"].setdefault(
            month,
            {
                "name": month_name,
                "vins": [],
                "count": 0,
                "last_updated": "",
                "model_year": str(model_year),
            },
        )

        vins = list(month_entry.get("vins", []))
        vins.append(vin)
        month_entry["vins"] = sorted(set(vins))
        month_entry["count"] = len(month_entry["vins"])
        month_entry["last_updated"] = datetime.now().isoformat(
            timespec="seconds"
        )
        month_entry["model_year"] = str(model_year)

        # PRESTANDA (v1.2.0): skriv endast den aktuella månadsfilen
        # i stället för hela registret.
        if self.registry_dir is not None:
            month_file = self.registry_dir / year / "{}.json".format(month)
            self._write_json(month_file, month_entry)

            # Uppdatera årssumman i cache (statistik stämmer direkt)
            year_entry["total_count"] = sum(
                len(md.get("vins", []))
                for md in year_entry["months"].values()
                if isinstance(md, dict)
            )

        # Emittera spec-namn + legacy-namn (kompatibilitet)
        event_payload = {"vin": vin, "year": year, "month": month}
        emit_event_safe(self.app, EVENT_REGISTERED_SPEC, event_payload)
        emit_event_safe(self.app, EVENT_REGISTERED_LEGACY, event_payload)

        _log.info("Registrerade VIN %s för %s-%s", vin, year, month)
        return True

    def is_registered(self, vin: str, year: Optional[str] = None) -> bool:
        """
        Kontrollerar om VIN är registrerat.

        Args:
            vin: VIN-nummer
            year: Specifikt år (None = alla år)

        Returns:
            True om registrerat
        """
        if not vin:
            return False

        vin = str(vin).strip().upper()
        registry = self.load_registry()

        years_to_check = [str(year)] if year else list(registry.keys())

        for current_year in years_to_check:
            year_data = registry.get(current_year, {})
            for month_data in year_data.get("months", {}).values():
                if vin in month_data.get("vins", []):
                    return True

        return False

    def get_vins_for_year(self, year: str) -> List[str]:
        """Hämtar alla VIN för ett år."""
        registry = self.load_registry()
        year_data = registry.get(str(year), {})

        all_vins: List[str] = []
        for month_data in year_data.get("months", {}).values():
            all_vins.extend(month_data.get("vins", []))

        return sorted(set(all_vins))

    def get_statistics(self) -> Dict[str, Any]:
        """
        Hämtar statistik för VIN-registret.

        Robust mot korrupta/icke-ändliga värden (v1.2.0): ogiltiga
        räknas inte in och loggas.
        """
        registry = self.load_registry()

        stats = {
            "years": 0,
            "total_vins": 0,
            "by_year": {},
        }

        for year, year_data in registry.items():
            try:
                count_raw = year_data.get("total_count", 0)
                if isinstance(count_raw, bool) or not isinstance(
                    count_raw, (int, float)
                ):
                    raise TypeError(
                        "total_count för {} är inte numeriskt".format(year)
                    )
                count = int(count_raw)
                if count != count or abs(count) == float("inf"):
                    raise ValueError(
                        "total_count för {} är icke-ändligt".format(year)
                    )
            except (TypeError, ValueError) as exc:
                _log.warning(
                    "Korrupt total_count för år %s: %s — räknas om",
                    year, exc,
                )
                # Räkna om från månadsfilerna
                count = 0
                months = year_data.get("months", {})
                if isinstance(months, dict):
                    for month_data in months.values():
                        if not isinstance(month_data, dict):
                            continue
                        vins = month_data.get("vins", [])
                        if isinstance(vins, list):
                            count += len(vins)

            stats["total_vins"] += count
            stats["by_year"][str(year)] = count

        stats["years"] = len(registry)
        return stats

    def generate_yearly_report(self, year: str) -> Optional[Path]:
        """
        Genererar årsrapport.

        Args:
            year: År att generera rapport för

        Returns:
            Path till rapportfil (json/rapporter/) eller None
        """
        if self.ut_dir is None:
            return None

        try:
            registry = self.load_registry()
            year_data = registry.get(str(year), {})
            months = year_data.get("months", {})

            if not months:
                _log.info("Inga VIN för år %s", year)
                return None

            all_vins: List[str] = []
            monthly_counts: Dict[str, int] = {}
            monthly_details: Dict[str, Dict[str, Any]] = {}

            for month, month_data in sorted(months.items()):
                vins = month_data.get("vins", [])
                if not isinstance(vins, list):
                    vins = []

                cleaned_vins = sorted(
                    str(v).strip().upper()
                    for v in vins
                    if str(v).strip()
                )
                all_vins.extend(cleaned_vins)
                monthly_counts[month] = len(cleaned_vins)
                monthly_details[month] = {
                    "name": month_data.get("name", ""),
                    "count": len(cleaned_vins),
                    "vins": cleaned_vins,
                    "model_year": month_data.get("model_year", ""),
                }

            unique_vins = sorted(set(all_vins))

            report_data = {
                "year": str(year),
                "total_unique_vins": len(unique_vins),
                "total_registrations": len(all_vins),
                "monthly_summary": monthly_counts,
                "monthly_details": monthly_details,
                "all_vins": unique_vins,
                "generated_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
                "generated_by": "VIN Tracking Plugin",
            }

            report_file = self.ut_dir / "vin_rapport_{}.json".format(year)
            self._write_json(report_file, report_data)

            _log.info(
                "VIN-rapport %s: %s VIN -> %s",
                year,
                len(unique_vins),
                report_file.name,
            )
            return report_file

        except Exception:
            _log.exception("Fel vid rapportgenerering för %s", year)
            return None

    # ------------------------------------------------------------------
    # Internfunktioner
    # ------------------------------------------------------------------

    def _read_json(self, path: Path) -> Any:
        """Läser JSON-fil med kommentarsstöd (BOM + //-/#-preamble)."""
        text = path.read_text(encoding="utf-8")

        if text.startswith("\ufeff"):
            text = text[1:]

        lines = text.splitlines()
        start_idx = 0

        while start_idx < len(lines):
            stripped = lines[start_idx].lstrip()
            if not stripped or stripped.startswith("//") or stripped.startswith("#"):
                start_idx += 1
            else:
                break

        payload = "\n".join(lines[start_idx:])
        return json.loads(payload) if payload.strip() else {}

    def _write_json(self, path: Path, data: Any) -> None:
        """Skriver JSON med preamble och atomisk skrivning."""
        timestamp = datetime.now().isoformat(timespec="seconds")
        preamble = "\n".join(
            [
                "// -*- coding: utf-8 -*-",
                "// Auto-generated: {}".format(timestamp),
                "// Fil: {}".format(path.name),
                "",
            ]
        )

        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        atomic_write_text(path, preamble + payload, encoding="utf-8")


__all__ = [
    "Plugin",
    "NAME",
    "VERSION",
    "DESCRIPTION",
    "AUTHOR",
    "COPYRIGHT",
    "DEPENDENCIES",
]
