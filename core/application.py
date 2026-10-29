# -*- coding: utf-8 -*-
# core/application.py
"""
Central Application-klass som koordinerar alla plugins v1.1.0.

Transportstyrelsen Fordonsregistreringssystem.

ALLA plugins pratar med Application, inte direkt med varandra.
Om något ändras, ändra HÄR - inte i 20 olika plugin-filer.

Användning i plugins:
    # Istället för:
    plugin = self.app.plugin_manager.get_plugin("vehicle_registry")

    # Använd:
    plugin = self.app.get_plugin("vehicle_registry")

FÖRÄNDRINGAR v1.1.0:
    - logger -> _log (spec-konvention) + f-string -> lazy %s
    - asyncio.get_event_loop() (deprecated i 3.12) fixad i
      shutdown(): get_running_loop()-detektering + asyncio.run()
    - get_all_plugins() använder publika
      plugin_loader.get_all_plugins() (grävde tidigare i privata
      _plugins)
    - NY: get_plugin_safe(name, default) — robust egen
      implementation (förväntas av plugins/plugin_loader)
    - NY: data_dir-property (krävs av
      PluginBase.get_app_data_dir v3.3.0)
    - import re flyttad till modulnivå, oanvänd List borttagen
    - shutdown() stänger även event_bus (best-effort)
    - VERSION/AUTHOR + dynamisk copyright

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.plugin_loader import PluginLoader
    from core.event_bus import EventBus
    from core.config import Configuration

_log = logging.getLogger(__name__)

VERSION = "1.1.0"
AUTHOR = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


class Application:
    """
    Central applikationsklass.

    Alla plugins får en referens till denna och använder dess
    metoder för att kommunicera med andra plugins och systemet.

    Attributes:
        config: Konfiguration
        event_bus: Event-system
        plugin_loader: Plugin-laddare

    Exempel i plugin:
        class Plugin(PluginBase):
            def initialize(self):
                # Hämta annan plugin
                vehicle_reg = self.app.get_plugin("vehicle_registry")

                # Emit event
                self.app.emit("my_plugin:ready", {"status": "ok"})

                # Hämta config
                value = self.app.config.get("my_setting", default="x")
    """

    def __init__(
        self,
        config: Optional["Configuration"] = None,
        base_dir: Optional[Path] = None
    ):
        """
        Initiera Application.

        Args:
            config: Configuration-instans
            base_dir: Bas-katalog för applikationen
        """
        self._base_dir = base_dir or Path(".")
        self._config = config

        # Dessa sätts av startup-processen
        self._plugin_loader: Optional["PluginLoader"] = None
        self._event_bus: Optional["EventBus"] = None

        # Plugin-cache för snabb access
        self._plugin_cache: Dict[str, Any] = {}

        # Status
        self._initialized = False
        self._shutting_down = False

        _log.info("Application instance created (v%s)", VERSION)

    # ═══════════════════════════════════════════════════════════════════════════
    # PROPERTIES
    # ═══════════════════════════════════════════════════════════════════════════

    @property
    def config(self) -> "Configuration":
        """Hämta konfiguration."""
        if self._config is None:
            raise RuntimeError("Configuration not loaded")
        return self._config

    @config.setter
    def config(self, value: "Configuration") -> None:
        """Sätt konfiguration."""
        self._config = value

    @property
    def event_bus(self) -> Optional["EventBus"]:
        """Hämta EventBus."""
        return self._event_bus

    @event_bus.setter
    def event_bus(self, value: "EventBus") -> None:
        """Sätt EventBus."""
        self._event_bus = value

    @property
    def plugin_loader(self) -> Optional["PluginLoader"]:
        """Hämta PluginLoader."""
        return self._plugin_loader

    @plugin_loader.setter
    def plugin_loader(self, value: "PluginLoader") -> None:
        """Sätt PluginLoader."""
        self._plugin_loader = value

    @property
    def base_dir(self) -> Path:
        """Hämta bas-katalog."""
        return self._base_dir

    @property
    def data_dir(self) -> Path:
        """
        Hämta data-katalog (NY v1.1.0).

        Används av PluginBase.get_app_data_dir() och därmed av
        get_ts_specs_dir(), get_vehicle_registry_dir(), m.fl.
        Läser paths.data från config om satt, annars base_dir/data.
        """
        if self._config is not None:
            try:
                configured = self._config.get("paths.data", "data")
                return self._base_dir / str(configured)
            except Exception:
                pass
        return self._base_dir / "data"

    @property
    def is_initialized(self) -> bool:
        """True om applikationen är initierad."""
        return self._initialized

    # ═══════════════════════════════════════════════════════════════════════════
    # PLUGIN ACCESS - HUVUDMETODEN
    # ═══════════════════════════════════════════════════════════════════════════

    def get_plugin(self, name: str) -> Optional[Any]:
        """
        Hämta en plugin via namn.

        DETTA ÄR DEN ENDA METODEN PLUGINS SKA ANVÄNDA!

        Args:
            name: Plugin-namn (t.ex. "vehicle_registry",
                  "core_config"). Stödjer olika format:
                  "Vehicle Registry", "vehicle-registry"

        Returns:
            Plugin-instans eller None om inte hittad

        Exempel:
            vehicle_reg = self.app.get_plugin("vehicle_registry")
            if vehicle_reg:
                data = vehicle_reg.find_vehicle_by_vin(vin)
        """
        # Normalisera namn
        normalized = self._normalize_plugin_name(name)

        # Kolla cache först
        if normalized in self._plugin_cache:
            return self._plugin_cache[normalized]

        plugin = self._find_plugin(name, normalized)

        # Cacha resultatet
        if plugin:
            self._plugin_cache[normalized] = plugin
            # Cacha också original-namn
            if name != normalized:
                self._plugin_cache[name] = plugin

        return plugin

    def get_plugin_safe(
        self, name: str, default: Any = None
    ) -> Optional[Any]:
        """
        Hämta plugin utan att någonsin kasta exception (NY v1.1.0).

        Args:
            name: Plugin-namn eller alias
            default: Returneras om plugin inte finns

        Returns:
            Plugin-instans, default, eller None
        """
        try:
            result = self.get_plugin(name)
            return result if result is not None else default
        except Exception as e:
            _log.debug("get_plugin_safe('%s') failed: %s", name, e)
            return default

    def _find_plugin(
        self, name: str, normalized: str
    ) -> Optional[Any]:
        """Intern metod för att hitta plugin."""
        names_to_try = [name, normalized]

        # Lägg till varianter
        if " " in name:
            names_to_try.append(name.replace(" ", "_"))
        if "-" in name:
            names_to_try.append(name.replace("-", "_"))

        for try_name in names_to_try:
            # 1. Försök plugin_loader
            if self._plugin_loader:
                try:
                    plugin = self._plugin_loader.get_plugin(try_name)
                    if plugin:
                        return plugin
                except Exception:
                    pass

            # 2. Fallback: direkt attribut på self
            attr = getattr(self, try_name, None)
            if attr and not try_name.startswith('_'):
                return attr

            # 3. Fallback: normaliserat namn som attribut
            attr = getattr(self, normalized, None)
            if attr and not normalized.startswith('_'):
                return attr

        return None

    @staticmethod
    def _normalize_plugin_name(name: str) -> str:
        """
        Normalisera plugin-namn.

        "Vehicle Registry" -> "vehicle_registry"
        "core-config" -> "core_config"
        "CoreConfig" -> "core_config"
        """
        # Hantera CamelCase -> snake_case
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1)

        # Ersätt mellanslag och bindestreck
        result = s2.lower().replace(" ", "_").replace("-", "_")

        # Ta bort dubbla understreck
        while "__" in result:
            result = result.replace("__", "_")

        return result.strip("_")

    def has_plugin(self, name: str) -> bool:
        """Kontrollera om en plugin finns och är laddad."""
        return self.get_plugin(name) is not None

    def get_all_plugins(self) -> Dict[str, Any]:
        """
        Hämta alla laddade plugins.

        FIXAT v1.1.0: använder publika
        plugin_loader.get_all_plugins() istället för att gräva i
        privata _plugins.
        """
        if self._plugin_loader:
            try:
                return self._plugin_loader.get_all_plugins()
            except Exception as e:
                _log.debug("get_all_plugins failed: %s", e)
        return {}

    def invalidate_plugin_cache(
        self, name: Optional[str] = None
    ) -> None:
        """
        Invalidera plugin-cache.

        Args:
            name: Specifik plugin att invalidera, eller None för alla
        """
        if name:
            normalized = self._normalize_plugin_name(name)
            self._plugin_cache.pop(name, None)
            self._plugin_cache.pop(normalized, None)
        else:
            self._plugin_cache.clear()

    # ═══════════════════════════════════════════════════════════════════════════
    # EVENT SHORTCUTS
    # ═══════════════════════════════════════════════════════════════════════════

    def emit(
        self, event_name: str, data: Any = None, **kwargs
    ) -> int:
        """
        Emittera event - shortcut för event_bus.emit().

        Args:
            event_name: Event-namn
            data: Event-data
            **kwargs: Extra argument till emit

        Returns:
            Antal lyssnare som anropades

        Exempel:
            self.app.emit("vehicle:created", {"vin": vin})
        """
        if self._event_bus:
            return self._event_bus.emit(event_name, data, **kwargs)
        return 0

    def on(
        self,
        event_name: str,
        callback,
        **kwargs
    ):
        """
        Prenumerera på event - shortcut för event_bus.on().

        Args:
            event_name: Event att lyssna på
            callback: Funktion att anropa
            **kwargs: Extra argument (priority, source, etc)

        Returns:
            callback för kedja

        Exempel:
            self.app.on("vehicle:created", self.handle_vehicle)
        """
        if self._event_bus:
            return self._event_bus.on(event_name, callback, **kwargs)
        return callback

    def off(self, event_name: str, callback=None) -> int:
        """
        Avprenumerera från event.

        Args:
            event_name: Event att avprenumerera från
            callback: Specifik callback eller None för alla

        Returns:
            Antal borttagna prenumerationer
        """
        if self._event_bus:
            return self._event_bus.off(event_name, callback)
        return 0

    # ═══════════════════════════════════════════════════════════════════════════
    # CONFIG SHORTCUTS
    # ═══════════════════════════════════════════════════════════════════════════

    def get_config(self, key: str, default: Any = None) -> Any:
        """
        Hämta config-värde - shortcut.

        Args:
            key: Config-nyckel (dot-notation stöds)
            default: Default-värde

        Returns:
            Värdet eller default

        Exempel:
            timeout = self.app.get_config(
                "network.timeout", default=30,
            )
        """
        if self._config:
            return self._config.get(key, default)
        return default

    def set_config(self, key: str, value: Any) -> None:
        """Sätt config-värde."""
        if self._config:
            self._config.set(key, value)

    # ═══════════════════════════════════════════════════════════════════════════
    # PATH HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def get_path(self, *parts: str) -> Path:
        """
        Hämta sökväg relativt till base_dir.

        Args:
            *parts: Sökvägsdelar

        Returns:
            Fullständig Path

        Exempel:
            data_path = self.app.get_path(
                "data", "vehicles", "2024.json",
            )
        """
        return self._base_dir / Path(*parts)

    def ensure_dir(self, *parts: str) -> Path:
        """
        Hämta sökväg och skapa katalog om den inte finns.

        Args:
            *parts: Sökvägsdelar

        Returns:
            Skapad/existerande Path
        """
        path = self.get_path(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ═══════════════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════════

    def mark_initialized(self) -> None:
        """Markera applikationen som initierad."""
        self._initialized = True
        self.emit("app:initialized")
        _log.info("Application marked as initialized")

    def shutdown(self) -> None:
        """
        Stäng ner applikationen.

        FIXAT v1.1.0: asyncio.get_event_loop() (deprecated i 3.12)
        ersatt med get_running_loop()-detektering + asyncio.run().
        Stänger nu även event_bus (best-effort).
        """
        if self._shutting_down:
            return

        self._shutting_down = True
        _log.info("Application shutting down...")

        # Emit shutdown event
        self.emit("app:shutdown")

        # Stäng ner plugins
        if self._plugin_loader:
            try:
                asyncio.get_running_loop()
                # Loop körs redan — kan inte köra sync här
                _log.warning(
                    "shutdown() called inside running event loop; "
                    "use 'await plugin_loader.shutdown_all()' "
                    "directly instead"
                )
            except RuntimeError:
                # Ingen körande loop — säkert att köra synkront
                try:
                    asyncio.run(self._plugin_loader.shutdown_all())
                except Exception as e:
                    _log.error(
                        "Error during plugin shutdown: %s", e,
                    )

        # Stäng event_bus (best-effort)
        if self._event_bus is not None:
            try:
                shutdown_fn = getattr(
                    self._event_bus, "shutdown", None
                )
                if callable(shutdown_fn):
                    shutdown_fn()
            except Exception as e:
                _log.error("Error during event_bus shutdown: %s", e)

        # Rensa
        self._plugin_cache.clear()

        _log.info("Application shutdown complete")

    # ═══════════════════════════════════════════════════════════════════════════
    # DEBUG / INFO
    # ═══════════════════════════════════════════════════════════════════════════

    def get_status(self) -> Dict[str, Any]:
        """Hämta applikationsstatus."""
        return {
            "version": VERSION,
            "initialized": self._initialized,
            "shutting_down": self._shutting_down,
            "base_dir": str(self._base_dir),
            "data_dir": str(self.data_dir),
            "plugins": {
                "loaded": len(self.get_all_plugins()),
                "cached": len(self._plugin_cache),
            },
            "event_bus": self._event_bus is not None,
            "config": self._config is not None,
        }

    def __repr__(self) -> str:
        plugins = len(self.get_all_plugins())
        return (
            f"<Application "
            f"v{VERSION} "
            f"initialized={self._initialized} "
            f"plugins={plugins}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "Application",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]