# -*- coding: utf-8 -*-
# Fil: plugins/end_post/plugin.py

"""
End Post Plugin v3.1.1

Genererar slutposter (posttyp 99) för Transportstyrelsen.
Integrerar med ts_spec_import för schemadefinitioner.

Features:
    - Genererar PT99 med korrekt format (2500 tecken)
    - Använder ts_spec_import schema om tillgängligt
    - Fallback till hårdkodad generering om schema saknas
    - Korrekt antal poster-räkning
    - Latin-1 (ISO 8859-1) kompatibilitet
    - Robust plugin-access via helpers

PT99 innehåller:
    - Löpnummer (sista postens nummer)
    - Posttyp "99"
    - Antal poster (totalt antal i filen, inklusive PT99)
    - Eventuell checksumma/kontrolldata

FÖRÄNDRINGAR v3.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 60): AUTHOR "TADEGA AB" BORT → "Rickard Längkvist"
    (modulnivå AUTHOR + klass-AUTHOR; dynamisk copyright via
    get_copyright_string()).
  - FIX (KRAV 58): "# Fil: plugins/end_post/plugin.py" tillagd
    (saknades).
  - FIX (låst regel): logger → modul-nivå _log; ALLA f-string-
    logganrop → lazy %s.
  - FIX (låst regel, atomisk skrivning): _save_config använde
    temp_path = config.with_suffix('.tmp') + Path.replace() —
    ersatt med mkstemp → fsync → os.replace (unik temp-fil,
    ingen krock vid parallella processer).
  - FIX (KRAV Z, sökväg): konfigurationen skrivs nu till
    json/end_post/config.json (primär) i stället för
    "data/end_post/config.json" (master Z-sektionen). Legacy-fil
    läses + migreras vid init (raderas ALDRIG automatiskt).
  - FIX (base_dir): getattr(app, "base_path", ".") →
    fallback-kedja base_dir → base_path → cwd (konsistent med
    identity_post v3.2.1).
  - FIX (livscykel, korrekthet): activate() anropar super().activate()
    (is_active via PluginBase); shutdown() anropar super().deactivate()
    + _shutdown_done-flagga (idempotent — PluginBase.shutdown()
    anropar polymorft self.deactivate() → ömsesidig rekursion om
    super().shutdown() används, samma fix som identity_post);
    deactivate() = bakåtkompatibel delegat till shutdown().
  - FIX (kraschsäkerhet): självregistrering app.end_post i
    try/except; _handle_generate walrus → vanlig tilldelning;
    tomt TYPE_CHECKING-block bort.
  - TILLÄGG (metadata): modulnivå VERSION/AUTHOR + get_copyright_string
    (+ privat alias _get_copyright_string).
  - FIX (radbrytningsartefakt): dubblerade blankrader före
    def/class kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (FIELD_POSITIONS, hårdkodad generering,
    schema-väg med alias-nycklar, extract/validate, MD5-checksumma,
    event-hantering, update_config).
FÖRÄNDRINGAR v3.1.0:
  - Robusta helper-funktioner för plugin/event-access
  - Förbättrad ts_spec_import integration
  - Lyssnar på ts_spec:imported event
  - Bättre felhantering
  - Inga hårda dependencies
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.plugin_base import PluginBase

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "3.1.1"
AUTHOR: str = "Rickard Längkvist"
PLUGIN_NAME: str = "End Post"

# Standard TS-postlängd
RECORD_LENGTH: int = 2500

# Teckenkodning enligt TS-spec
TS_ENCODING: str = "iso-8859-1"

# PT99-specifika konstanter (fallback om ts_spec_import saknas)
PT99_POSTTYP: str = "99"

# Fältpositioner (1-baserade enligt TS-spec) - fallback-värden
FIELD_POSITIONS: Dict[str, Tuple[int, int]] = {
    "LOPNUMMER": (1, 4),       # N4: Löpnummer (sista posten)
    "VERSION": (5, 2),         # N2: Version
    "POSTTYP": (7, 2),         # N2: Posttyp = "99"
    "ANTAL_POSTER": (9, 6),    # N6: Totalt antal poster
    "RESERV": (15, 66),        # AN66: Reserv
}

# Konfigurationssökvägar (json/ primär enligt KRAV Z; legacy data/).
_CONFIG_RELATIVE: str = "json/end_post/config.json"
_LEGACY_CONFIG_RELATIVE: str = "data/end_post/config.json"

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# Bakåtkompatibilitet: privat alias.
_get_copyright_string = get_copyright_string


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log: logging.Logger = logging.getLogger("end_post")


# ══════════════════════════════════════════════════════════════════════════════
# ATOMISK SKRIVNING (låst regel: mkstemp → fsync → os.replace)
# ══════════════════════════════════════════════════════════════════════════════

def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    """Atomisk JSON-skrivning. KRASCHSÄKER (kastar vid fel)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".end_post_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# ROBUST HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Robust plugin-hämtning som fungerar oavsett app-konfiguration.

    Försöker i ordning:
    1. app.get_plugin(name)
    2. app.plugin_loader.get_plugin(name)
    3. app.plugin_manager.get_plugin(name)
    4. getattr(app, name)
    """
    if app is None:
        return None

    # Metod 1: app.get_plugin()
    try:
        if hasattr(app, "get_plugin") and callable(app.get_plugin):
            result = app.get_plugin(name)
            if result is not None:
                return result
    except Exception:
        pass

    # Metod 2: app.plugin_loader.get_plugin()
    try:
        loader = getattr(app, "plugin_loader", None)
        if loader and hasattr(loader, "get_plugin"):
            result = loader.get_plugin(name)
            if result is not None:
                return result
    except Exception:
        pass

    # Metod 3: app.plugin_manager.get_plugin() (legacy)
    try:
        manager = getattr(app, "plugin_manager", None)
        if manager and hasattr(manager, "get_plugin"):
            result = manager.get_plugin(name)
            if result is not None:
                return result
    except Exception:
        pass

    # Metod 4: direktattribut
    try:
        attr_name = name.replace("-", "_").lower()
        if hasattr(app, attr_name):
            return getattr(app, attr_name)
    except Exception:
        pass

    return None

def get_event_bus(app: Any) -> Optional[Any]:
    """Hämta event bus från app. KRASCHSÄKER."""
    if app is None:
        return None

    if hasattr(app, "event_bus") and app.event_bus is not None:
        return app.event_bus

    if hasattr(app, "events") and app.events is not None:
        return app.events

    events_plugin = get_plugin_safe(app, "core_events")
    if events_plugin is not None:
        if hasattr(events_plugin, "bus"):
            return events_plugin.bus
        if hasattr(events_plugin, "emit"):
            return events_plugin

    return None

def emit_event_safe(
    app: Any,
    event_name: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Emit event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        bus.emit(event_name, data or {})
        return True
    except Exception as exc:
        _log.debug(
            "Kunde inte emit '%s': %s", event_name, exc
        )
        return False

def subscribe_event_safe(
    app: Any, event_name: str, handler: Callable
) -> bool:
    """Prenumerera på event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        if hasattr(bus, "on"):
            bus.on(event_name, handler)
        elif hasattr(bus, "subscribe"):
            bus.subscribe(event_name, handler)
        else:
            return False
        return True
    except Exception as exc:
        _log.debug(
            "Kunde inte prenumerera på '%s': %s", event_name, exc
        )
        return False

def unsubscribe_event_safe(
    app: Any, event_name: str, handler: Callable
) -> bool:
    """Avprenumerera från event säkert."""
    bus = get_event_bus(app)
    if bus is None:
        return False
    try:
        if hasattr(bus, "off"):
            bus.off(event_name, handler)
        elif hasattr(bus, "unsubscribe"):
            bus.unsubscribe(event_name, handler)
        else:
            return False
        return True
    except Exception as exc:
        _log.debug(
            "Kunde inte avprenumerera från '%s': %s",
            event_name,
            exc,
        )
        return False


# ══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EndPostConfig:
    """Konfiguration för slutposter."""

    version: str = "00"
    validate_post_length: bool = True
    post_length: int = RECORD_LENGTH

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EndPostConfig":
        """Skapa från dictionary."""
        return cls(
            version=data.get("version", "00"),
            validate_post_length=data.get(
                "validate_post_length", True
            ),
            post_length=data.get("post_length", RECORD_LENGTH),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "version": self.version,
            "validate_post_length": self.validate_post_length,
            "post_length": self.post_length,
        }


# ══════════════════════════════════════════════════════════════════════════════
# POST GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class PostGenerator:
    """
    Genererar slutposter (PT99).

    Kan använda ts_spec_import schema eller fallback till hårdkodad
    generering.
    """

    def __init__(
        self, app: Any = None, config: Optional[EndPostConfig] = None
    ) -> None:
        """
        Args:
            app: App-referens för att hämta ts_spec_import
            config: Konfiguration
        """
        self.app = app
        self.config = config or EndPostConfig()
        self._schema: Optional[Any] = None
        self._schema_loaded: bool = False

    @property
    def schema(self) -> Optional[Any]:
        """Hämta PT99-schema (lazy loading)."""
        if not self._schema_loaded:
            self._load_schema()
        return self._schema

    def _load_schema(self) -> None:
        """Ladda schema från ts_spec_import. KRASCHSÄKER."""
        self._schema_loaded = True
        self._schema = None

        if self.app is None:
            return

        ts_spec = get_plugin_safe(self.app, "ts_spec_import")
        if ts_spec is None:
            ts_spec = getattr(self.app, "ts_spec_import", None)

        if ts_spec and hasattr(ts_spec, "get_schema"):
            try:
                self._schema = ts_spec.get_schema("99")
                if self._schema:
                    _log.info(
                        "PT99-schema laddat (version: %s)",
                        getattr(self._schema, "version", "?"),
                    )
            except Exception as exc:
                _log.warning(
                    "Kunde inte ladda PT99-schema: %s", exc
                )

    def invalidate_schema_cache(self) -> None:
        """Rensa cachad schema."""
        self._schema = None
        self._schema_loaded = False
        _log.debug("PT99 schema-cache ogiltigförklarad")

    def generate(
        self,
        post_count: int,
        lopnummer: Optional[int] = None,
        checksum: Optional[str] = None,
    ) -> str:
        """
        Generera slutpost (PT99).

        Args:
            post_count: Totalt antal poster i filen (inklusive PT99)
            lopnummer: Löpnummer för PT99 (default: post_count)
            checksum: Valfri checksumma att inkludera

        Returns:
            Formaterad post (exakt 2500 tecken)

        Raises:
            ValueError: Om ogiltiga indata
        """
        if post_count < 1:
            raise ValueError(
                "Ogiltigt antal poster: %d" % post_count
            )

        # Löpnummer = sista postens nummer (normalt = antal poster)
        if lopnummer is None:
            lopnummer = post_count

        # Använd schema om tillgängligt
        if self.schema:
            return self._generate_from_schema(
                post_count, lopnummer, checksum
            )

        # Fallback: hårdkodad generering
        return self._generate_hardcoded(
            post_count, lopnummer, checksum
        )

    def _generate_from_schema(
        self,
        post_count: int,
        lopnummer: int,
        checksum: Optional[str],
    ) -> str:
        """Generera post från ts_spec_import schema."""
        # Bygg data-dict med alla möjliga fältnamn
        data: Dict[str, Any] = {
            # Standardnamn
            "LOPNUMMER": lopnummer,
            "LÖPNUMMER": lopnummer,
            "VERSION": self.config.version,
            "POSTTYP": PT99_POSTTYP,
            "POST_TYP": PT99_POSTTYP,
            "PT": PT99_POSTTYP,

            # Antal poster
            "ANTAL_POSTER": post_count,
            "ANTAL": post_count,
            "TOTALT_ANTAL": post_count,
            "POST_COUNT": post_count,
            "RECORDS": post_count,

            # Checksumma (om tillhandahållen)
            "CHECKSUM": checksum or "",
            "CHECKSUMMA": checksum or "",
            "KONTROLLSUMMA": checksum or "",

            # Reserverade fält
            "RESERV": "",
            "RESERV1": "",
            "RESERV2": "",
        }

        # Använd schemats format_record
        post = self.schema.format_record(data)

        # Verifiera längd
        if len(post) != RECORD_LENGTH:
            _log.warning(
                "PT99 från schema: %d tecken, förväntat %d",
                len(post),
                RECORD_LENGTH,
            )
            post = post[:RECORD_LENGTH].ljust(RECORD_LENGTH)

        # Validera Latin-1
        try:
            post.encode(TS_ENCODING)
        except UnicodeEncodeError:
            post = post.encode(
                TS_ENCODING, errors="replace"
            ).decode(TS_ENCODING)
            _log.warning("PT99: Icke-Latin-1-tecken ersatta")

        _log.debug(
            "PT99 från schema: %d tecken, %d poster",
            len(post),
            post_count,
        )
        return post

    def _generate_hardcoded(
        self,
        post_count: int,
        lopnummer: int,
        checksum: Optional[str],
    ) -> str:
        """Fallback: hårdkodad generering enligt TS-format."""
        _log.warning(
            "Hårdkodad PT99-generering (inget schema tillgängligt)"
        )

        # Formatera fält enligt TS-regler
        # Numeriska: högerställda, noll-paddade
        # Alfanumeriska: vänsterställda, space-paddade

        # Position 1-4: Löpnummer (N4)
        lopnr_field = str(lopnummer).zfill(4)

        # Position 5-6: Version (N2)
        version_field = self.config.version.zfill(2)

        # Position 7-8: Posttyp (N2)
        posttyp_field = PT99_POSTTYP.zfill(2)

        # Position 9-14: Antal poster (N6)
        antal_field = str(post_count).zfill(6)

        # Position 15-80: Reserv/Checksumma (AN66)
        if checksum:
            reserv_field = checksum[:66].ljust(66)
        else:
            reserv_field = " " * 66

        # Bygg prefix (position 1-80)
        prefix = (
            lopnr_field +      # 1-4
            version_field +    # 5-6
            posttyp_field +    # 7-8
            antal_field +      # 9-14
            reserv_field       # 15-80
        )

        # Verifiera prefix-längd
        expected_prefix_len = 80
        if len(prefix) != expected_prefix_len:
            _log.warning(
                "PT99-prefix: %d tecken, förväntat %d",
                len(prefix),
                expected_prefix_len,
            )
            prefix = prefix[:expected_prefix_len].ljust(
                expected_prefix_len
            )

        # Fyll ut till 2500 tecken med spaces
        post = prefix.ljust(RECORD_LENGTH)

        # Validera Latin-1
        try:
            post.encode(TS_ENCODING)
        except UnicodeEncodeError:
            post = post.encode(
                TS_ENCODING, errors="replace"
            ).decode(TS_ENCODING)
            _log.warning("PT99: Icke-Latin-1-tecken ersatta")

        if len(post) != RECORD_LENGTH:
            raise ValueError(
                "Postlängd %d, förväntat %d"
                % (len(post), RECORD_LENGTH)
            )

        _log.debug("PT99 hårdkodad: %d poster", post_count)
        return post

    @staticmethod
    def extract_post_count(post: str) -> int:
        """
        Extrahera antal poster från PT99.

        Args:
            post: Slutpost (2500 tecken)

        Returns:
            Antal poster
        """
        start = FIELD_POSITIONS["ANTAL_POSTER"][0] - 1
        length = FIELD_POSITIONS["ANTAL_POSTER"][1]

        if len(post) < start + length:
            raise ValueError(
                "Post för kort för att extrahera antal"
            )

        antal_str = post[start:start + length].strip()

        try:
            return int(antal_str)
        except ValueError:
            raise ValueError(
                "Ogiltigt antal poster: '%s'" % antal_str
            )

    @staticmethod
    def extract_lopnummer(post: str) -> int:
        """Extrahera löpnummer från post."""
        start = FIELD_POSITIONS["LOPNUMMER"][0] - 1
        length = FIELD_POSITIONS["LOPNUMMER"][1]

        if len(post) < start + length:
            raise ValueError(
                "Post för kort för att extrahera löpnummer"
            )

        lopnr_str = post[start:start + length].strip()

        try:
            return int(lopnr_str)
        except ValueError:
            raise ValueError(
                "Ogiltigt löpnummer: '%s'" % lopnr_str
            )

    @staticmethod
    def extract_posttyp(post: str) -> str:
        """Extrahera posttyp från post."""
        start = FIELD_POSITIONS["POSTTYP"][0] - 1
        length = FIELD_POSITIONS["POSTTYP"][1]

        if len(post) < start + length:
            raise ValueError(
                "Post för kort för att extrahera posttyp"
            )

        return post[start:start + length].strip()

    @staticmethod
    def validate_post(post: str) -> Tuple[bool, List[str]]:
        """
        Validera en genererad post.

        Returns:
            (is_valid, list_of_errors)
        """
        errors: List[str] = []

        # Längd
        if len(post) != RECORD_LENGTH:
            errors.append(
                "Längd %d, förväntat %d"
                % (len(post), RECORD_LENGTH)
            )

        # Latin-1
        try:
            post.encode(TS_ENCODING)
        except UnicodeEncodeError as exc:
            errors.append(
                "Innehåller ogiltiga tecken: %s" % exc
            )

        # Posttyp
        if len(post) >= 8:
            posttyp = post[6:8]
            if posttyp != "99":
                errors.append(
                    "Posttyp '%s', förväntat '99'" % posttyp
                )

        # Antal poster (ska vara > 0)
        if len(post) >= 14:
            try:
                antal = int(post[8:14])
                if antal < 1:
                    errors.append(
                        "Ogiltigt antal poster: %d" % antal
                    )
            except ValueError:
                errors.append("Kunde inte tolka antal poster")

        return len(errors) == 0, errors

    @staticmethod
    def calculate_checksum(posts: List[str]) -> str:
        """
        Beräkna checksumma för alla poster.

        Args:
            posts: Lista med poster (PT28 + PT45-poster, UTAN PT99)

        Returns:
            MD5 checksumma (32 tecken)
        """
        content = "".join(posts)
        return hashlib.md5(
            content.encode(TS_ENCODING, errors="replace")
        ).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    End Post Plugin v3.1.1.

    Genererar slutposter (PT99) för Transportstyrelsen.
    Integrerar med ts_spec_import för schemadefinitioner.

    API:
        # Generera PT99
        result = app.end_post.generate_post(post_count=100)
        post = result['post']  # 2500 tecken

        # Med checksumma
        result = app.end_post.generate_post(
            post_count=100,
            checksum=app.end_post.calculate_checksum(other_posts)
        )
    """

    NAME: str = PLUGIN_NAME
    VERSION: str = VERSION
    DESCRIPTION: str = "Genererar slutposter (PT99)"
    AUTHOR: str = AUTHOR

    # Inga hårda beroenden
    DEPENDENCIES: List[str] = []
    OPTIONAL_DEPENDENCIES: List[str] = [
        "ts_spec_import", "core_config", "core_logger",
    ]

    def __init__(self, app: Any) -> None:
        super().__init__(app)

        # Konfiguration
        self.config: Optional[EndPostConfig] = None

        # Generator
        self.post_generator: Optional[PostGenerator] = None

        # Sökvägar
        self._base_dir: Optional[Path] = None
        self._config_path: Optional[Path] = None
        self._legacy_config_path: Optional[Path] = None

        # Event handlers (för cleanup)
        self._event_handlers: List[Tuple[str, Callable]] = []
        self._shutdown_done: bool = False

    def initialize(self) -> None:
        """Initiera plugin. KRASCHSÄKER."""
        try:
            # Sökvägar (base_dir → base_path → cwd)
            base = getattr(self.app, "base_dir", None)
            if not base:
                base = getattr(self.app, "base_path", ".")
            self._base_dir = Path(str(base))
            self._config_path = self._base_dir / _CONFIG_RELATIVE
            self._legacy_config_path = (
                self._base_dir / _LEGACY_CONFIG_RELATIVE
            )

            # Ladda konfiguration (med legacy-migrering)
            self._load_config()

            # Skapa generator
            self.post_generator = PostGenerator(
                self.app, self.config
            )

            # Registrera i app
            try:
                self.app.end_post = self
            except Exception:
                pass

            # Registrera event handlers
            self._register_events()

            _log.info(
                "%s v%s initierad", PLUGIN_NAME, VERSION
            )
        except Exception as exc:
            _log.error(
                "Initiering misslyckades: %s", exc, exc_info=True
            )

    def activate(self) -> None:
        """Aktivera plugin (is_active via PluginBase)."""
        try:
            super().activate()
        except Exception:
            _log.exception("PluginBase.activate misslyckades.")

        emit_event_safe(self.app, "end_post:activated", {
            "version": VERSION,
        })

        _log.info("%s aktiverad", PLUGIN_NAME)

    def shutdown(self) -> None:
        """
        Städa upp (avregistrerar events + state → INACTIVE).

        Anropar super().deactivate() (INTE super().shutdown() —
        PluginBase.shutdown() anropar polymorft self.deactivate() →
        ömsesidig rekursion). Idempotent via _shutdown_done.
        """
        if self._shutdown_done:
            return
        self._shutdown_done = True
        try:
            self._unregister_events()
            _log.info("%s deaktiverad", PLUGIN_NAME)
        except Exception as exc:
            _log.error(
                "Shutdown misslyckades: %s", exc, exc_info=True
            )
        finally:
            try:
                super().deactivate()
            except Exception:
                _log.exception("PluginBase.deactivate misslyckades.")

    def deactivate(self) -> None:
        """Bakåtkompatibel deactivate. Delegerar till shutdown()."""
        self.shutdown()

    def _register_events(self) -> None:
        """Registrera event handlers."""
        events = [
            ("end_post:generate", self._handle_generate),
            ("ts_spec:version_changed", self._on_spec_changed),
            ("ts_spec:imported", self._on_spec_imported),
        ]

        for event_name, handler in events:
            if subscribe_event_safe(self.app, event_name, handler):
                self._event_handlers.append((event_name, handler))
                _log.debug("Prenumererar på: %s", event_name)

    def _unregister_events(self) -> None:
        """Avregistrera event handlers."""
        for event_name, handler in self._event_handlers:
            unsubscribe_event_safe(self.app, event_name, handler)
        self._event_handlers.clear()

    def _on_spec_changed(self, data: Optional[Dict] = None) -> None:
        """Hantera när TS-spec version ändras."""
        if self.post_generator:
            self.post_generator.invalidate_schema_cache()
        _log.info(
            "TS-spec version ändrad till: %s",
            (data or {}).get("version"),
        )

    def _on_spec_imported(self, data: Optional[Dict] = None) -> None:
        """Hantera när ny TS-spec importeras."""
        if self.post_generator:
            self.post_generator.invalidate_schema_cache()
        _log.info(
            "TS-spec importerad: %s, posttyper: %s",
            (data or {}).get("version"),
            (data or {}).get("post_types"),
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════════════════

    def generate_post(
        self,
        post_count: int,
        lopnummer: Optional[int] = None,
        checksum: Optional[str] = None,
        include_checksum: bool = False,
        preceding_posts: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generera slutpost (PT99).

        Args:
            post_count: Totalt antal poster i filen (inklusive PT99)
            lopnummer: Löpnummer för PT99 (default: post_count)
            checksum: Förberäknad checksumma
            include_checksum: Beräkna checksumma från
                preceding_posts
            preceding_posts: Lista med föregående poster (för
                checksumma)

        Returns:
            Dict med:
                - success: bool
                - post: str (2500 tecken)
                - post_count: int
                - lopnummer: int
                - checksum: Optional[str]
                - length: int
                - spec_version: Optional[str]
                - used_schema: bool
                - error: Optional[str]
        """
        try:
            _log.info(
                "Genererar slutpost (PT99) för %d poster...",
                post_count,
            )

            # Beräkna checksumma om begärt
            if include_checksum and preceding_posts and not checksum:
                checksum = self.calculate_checksum(preceding_posts)

            # Generera post
            post = self.post_generator.generate(
                post_count=post_count,
                lopnummer=lopnummer,
                checksum=checksum,
            )

            # Validera
            is_valid, errors = PostGenerator.validate_post(post)
            if not is_valid:
                _log.warning(
                    "PT99-valideringsvarningar: %s", errors
                )

            # Emit event
            emit_event_safe(self.app, "end_post:generated", {
                "post_count": post_count,
                "lopnummer": lopnummer or post_count,
                "timestamp": datetime.now().isoformat(),
            })

            _log.info(
                "PT99 genererad: %d totala poster", post_count
            )

            return {
                "success": True,
                "post": post,
                "post_count": post_count,
                "lopnummer": lopnummer or post_count,
                "checksum": checksum,
                "length": len(post),
                "spec_version": self._get_spec_version(),
                "used_schema": (
                    self.post_generator.schema is not None
                ),
            }

        except Exception as exc:
            _log.exception("Kunde inte generera PT99")
            return {"success": False, "error": str(exc)}

    def calculate_checksum(self, posts: List[str]) -> str:
        """
        Beräkna checksumma för en lista med poster.

        Args:
            posts: Lista med poster (PT28 + PT45-poster)

        Returns:
            MD5 checksumma (32 tecken hex)
        """
        return PostGenerator.calculate_checksum(posts)

    def validate_post(self, post: str) -> Tuple[bool, List[str]]:
        """
        Validera en PT99-post.

        Args:
            post: Post att validera

        Returns:
            (is_valid, list_of_errors)
        """
        return PostGenerator.validate_post(post)

    def extract_post_count(self, post: str) -> int:
        """
        Extrahera antal poster från en PT99.

        Args:
            post: PT99-post

        Returns:
            Antal poster
        """
        return PostGenerator.extract_post_count(post)

    def get_config(self) -> Dict[str, Any]:
        """Hämta konfiguration."""
        return self.config.to_dict() if self.config else {}

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Uppdatera konfiguration.

        Args:
            updates: Dict med uppdateringar

        Returns:
            Dict med success och ny config
        """
        try:
            if self.config is None:
                self.config = EndPostConfig()

            if "version" in updates:
                self.config.version = updates["version"]
            if "validate_post_length" in updates:
                self.config.validate_post_length = updates[
                    "validate_post_length"
                ]

            self._save_config()

            # Återskapa generator med ny config
            self.post_generator = PostGenerator(
                self.app, self.config
            )

            emit_event_safe(self.app, "end_post:config_updated", {
                "config": self.config.to_dict(),
            })

            _log.info("Konfiguration uppdaterad")
            return {
                "success": True,
                "config": self.config.to_dict(),
            }

        except Exception as exc:
            _log.error("Kunde inte uppdatera konfig: %s", exc)
            return {"success": False, "error": str(exc)}

    # ═══════════════════════════════════════════════════════════════════════════
    # EVENT HANDLERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _handle_generate(self, data: Dict[str, Any]) -> None:
        """Hantera generate event."""
        result = self.generate_post(
            post_count=data.get("post_count", 1),
            lopnummer=data.get("lopnummer"),
            checksum=data.get("checksum"),
            include_checksum=data.get("include_checksum", False),
            preceding_posts=data.get("preceding_posts"),
        )

        callback = data.get("callback")
        if callback:
            callback(result)

    # ═══════════════════════════════════════════════════════════════════════════
    # PRIVATE METHODS
    # ═══════════════════════════════════════════════════════════════════════════

    def _load_config(self) -> None:
        """
        Ladda konfiguration.

        Primär: json/end_post/config.json (KRAV Z). Fallback:
        legacy "data/end_post/config.json" (migreras vid nästa
        spara — filen raderas ALDRIG automatiskt). Defaults om
        ingen fil finns.
        """
        try:
            candidates: List[Path] = []
            if self._config_path:
                candidates.append(self._config_path)
            if (
                self._legacy_config_path
                and self._legacy_config_path != self._config_path
            ):
                candidates.append(self._legacy_config_path)

            for path in candidates:
                if path.exists():
                    with path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.config = EndPostConfig.from_dict(data)
                    if path == self._legacy_config_path:
                        _log.info(
                            "Legacy-konfig läst från %s — migreras "
                            "till %s vid nästa spara",
                            path.name,
                            self._config_path,
                        )
                    else:
                        _log.info("Konfiguration laddad")
                    return

            self.config = EndPostConfig()
            self._save_config()
            _log.info("Ny konfiguration skapad")
        except Exception as exc:
            _log.warning(
                "Konfig-läsning misslyckades, använder defaults: %s",
                exc,
            )
            self.config = EndPostConfig()

    def _save_config(self) -> None:
        """Spara konfiguration till fil (atomiskt). KRASCHSÄKER."""
        if self.config is None or self._config_path is None:
            return

        try:
            data = self.config.to_dict()
            data["_meta"] = {
                "updated_at": datetime.now().isoformat(),
                "version": self.VERSION,
            }

            _atomic_write_json(self._config_path, data)

        except Exception as exc:
            _log.error("Kunde inte spara konfig: %s", exc)

    def _get_spec_version(self) -> Optional[str]:
        """Hämta aktiv TS-spec version. KRASCHSÄKER."""
        ts_spec = get_plugin_safe(self.app, "ts_spec_import")
        if ts_spec is None:
            ts_spec = getattr(self.app, "ts_spec_import", None)

        if ts_spec and hasattr(ts_spec, "get_active_version"):
            try:
                return ts_spec.get_active_version()
            except Exception:
                pass
        return None


# Bakåtkompatibilitet
EndPostPlugin = Plugin


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Plugin
    "Plugin",
    "EndPostPlugin",
    # Config
    "EndPostConfig",
    # Generator
    "PostGenerator",
    # Helper functions
    "get_plugin_safe",
    "get_event_bus",
    "emit_event_safe",
    "subscribe_event_safe",
    "unsubscribe_event_safe",
    # Utils
    "get_copyright_string",
    # Constants
    "RECORD_LENGTH",
    "TS_ENCODING",
    "FIELD_POSITIONS",
    "VERSION",
    "AUTHOR",
]
