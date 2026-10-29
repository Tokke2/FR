# -*- coding: utf-8 -*-
# Fil: plugins/ts_file_generator/plugin.py
"""
TS File Generator Plugin v6.0.1

Fullständigt omskriven enligt PluginBase-kontrakt (v6.0.0) + granskad
v6.0.1 (spec v1.6 förbättringsregeln + spec v1.12).

✅ PluginBase v3.x kompatibel (init/register_ui/shutdown/config_schema)
✅ Module-level _log (ingen self.logger)
✅ Dynamisk copyright
✅ Schema-first (ts_schema_manager → fallback ts_spec_import via
   RecordBuilder — spec v1.12 INTEGRATION)
✅ Latin-1 (ISO-8859-1)
✅ 2500 tecken per rad
✅ Atomisk skrivning
✅ Cross-plugin tolerant
✅ Event-driven
✅ health_check()
✅ get_diagnostics()

FÖRÄNDRINGAR v6.0.1 (granskad):
    - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2026 ..." i
      docstringen BORTTAGEN — copyright genereras dynamiskt via
      get_copyright_string().
    - FIX (spec v1.12 OBS 2): generate_complete_file() accepterar nu
      sender_org, responsible, include_pt28/45/99, manual_batch_file_id,
      skip_registered — widget.py v5.0.1 anropar med dessa som kwargs
      (tidigare svaldes de av **kwargs och IGNORERADES: checkboxarna
      hade ingen effekt och avsändar-org användes inte i PT28).
      Flaggor + org respekteras nu fullt ut.
    - FIX (spec v1.12 OBS 3): get_output_dir() tillagd — widgeten
      v5.0.1 anropar plugin.get_output_dir() (fanns ej -> AttributeError
      vid refresh).
    - FIX (dokumentationslöfte): get_diagnostics() SAKNADES trots att
      docstringen lovade den — tillagd.
    - FIX (spec v1.12 INTEGRATION): RecordBuilder (.record_builder
      v2.0.1) integrerad för postbyggnad — schema-first med korrekta
      fallbacks (orgnummer/FilID/VIN/ANTAL_POSTER i stället för tomma
      "000128"-rader), Latin-1-varningar, required-fältvalidering.
    - FIX: _get_schema_manager() — onödig get_plugin_class-import
      (oanvänd variabel) borttagen; kraschsäker med app.get_plugin +
      getattr-fallback.
    - FIX (Sektion Z): _setup_paths() baserad på app.base_path i
      stället för relativ Path("data") — ut-katalog = base_path/ut
      enligt master v1.4; data/ts_file_generator för status/backup.
    - get_logger() (StreamHandler-manipulation) -> _get_logger()
      (privat, konvention — loggkonfiguration sköts av core.logger_setup).
    - Oanvända importer borttagna (json, shutil, Tuple); try/except-
      fallback för PluginBase (samma mönster som ts_schema_manager).
    - GenerationResult: to_dict() + batch_file_id/file_id-alias
      (widget v5.0.1 läser getattr(result, "batch_file_id", ...)).
    - Filkommentar "# Fil: plugins/ts_file_generator/plugin.py"
      (spec v1.11, KRAV 58).
    - OBS (inväntar beslut): skip_registered accepteras för framtida
      statuslagring men är ännu no-op (ingen StatusStore i v6.x).
    - Övrig logik OFÖRÄNDRAD (atomisk skrivning, Latin-1-normalisering,
      SHA-256-checksumma, events).
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Final

try:
    from core.plugin_base import PluginBase
except Exception:
    class PluginBase:  # type: ignore
        def __init__(self, app: Any) -> None:
            self.app = app
            self.is_active = False

# RecordBuilder (schema-driven postbyggnad + fallback) — granskad v2.0.1
try:
    from .record_builder import RecordBuilder
except ImportError:
    RecordBuilder = None  # type: ignore[assignment,misc]

# ═══════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT
# ═══════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "6.0.1"
AUTHOR: Final[str] = "Rickard Längkvist"
TS_ENCODING: Final[str] = "iso-8859-1"
TS_RECORD_LENGTH: Final[int] = 2500


def get_copyright_string() -> str:
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ═══════════════════════════════════════════════════════════════════════
# LOGGER (MODULE LEVEL – EJ self.logger)
# ═══════════════════════════════════════════════════════════════════════

def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback om logging ej konfigurerat.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("ts_file_generator")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log = _get_logger()


# ═══════════════════════════════════════════════════════════════════════
# EVENT HELPERS (KRASCHSÄKRA)
# ═══════════════════════════════════════════════════════════════════════

def get_event_bus(app: Any) -> Optional[Any]:
    if app is None:
        return None
    for attr in ("event_bus", "events", "_event_bus"):
        bus = getattr(app, attr, None)
        if bus is not None:
            return bus
    return None


def _emit(app: Any, event: str, data: Optional[Dict[str, Any]] = None) -> None:
    try:
        bus = get_event_bus(app)
        if bus and hasattr(bus, "publish"):
            bus.publish(event, data or {})
        elif bus and hasattr(bus, "emit"):
            bus.emit(event, data or {})
    except Exception as e:
        _log.debug("Event emit misslyckades: %s", e)


# ═══════════════════════════════════════════════════════════════════════
# ATOMIC WRITE
# ═══════════════════════════════════════════════════════════════════════

def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ═══════════════════════════════════════════════════════════════════════
# DATAMODELL
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class GenerationResult:
    """
    Resultat från TS-filgenerering.

    Attributes:
        success:          True om filen genererades korrekt
        filepath:         Sökväg till genererad fil
        batch_id:         Batch/FilID (t.ex. TS20260817_120000)
        total_records:    Totalt antal poster i filen (PT28+PT45×n+PT99)
        errors:           Felmeddelanden
        warnings:         Varningsmeddelanden
        checksum_sha256:  SHA-256-checksumma av filinnehållet
        ts_spec_version:  Aktiv schemaversion vid generering
    """
    success: bool = False
    filepath: Optional[Path] = None
    batch_id: Optional[str] = None
    total_records: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checksum_sha256: Optional[str] = None
    ts_spec_version: Optional[str] = None

    @property
    def batch_file_id(self) -> Optional[str]:
        """Alias för batch_id (widget v5.0.1 / äldre anropare)."""
        return self.batch_id

    @property
    def file_id(self) -> Optional[str]:
        """Alias för batch_id (widget v5.0.1 / äldre anropare)."""
        return self.batch_id

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary (events/callbacks)."""
        return {
            "success": self.success,
            "filepath": str(self.filepath) if self.filepath else None,
            "batch_id": self.batch_id,
            "total_records": self.total_records,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "checksum_sha256": self.checksum_sha256,
            "ts_spec_version": self.ts_spec_version,
        }


# ═══════════════════════════════════════════════════════════════════════
# MAIN PLUGIN
# ═══════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    TS File Generator
    """

    NAME: Final[str] = "ts_file_generator"
    VERSION: Final[str] = VERSION
    DESCRIPTION: Final[str] = "TS-filgenerering (PT28/PT45/PT99, schema-driven)"
    AUTHOR: Final[str] = AUTHOR
    DEPENDENCIES: Final[Tuple[str, ...]] = ()

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._initialized: bool = False
        self._paths: Dict[str, Path] = {}
        self._builder: Optional[Any] = None

    # ─────────────────────────────────────────────────────────────
    # PLUGINBASE KONTRAKT
    # ─────────────────────────────────────────────────────────────

    def init(self) -> None:
        """
        Initieras av core.
        """
        try:
            _log.info("=" * 60)
            _log.info("TS File Generator v%s", VERSION)
            _log.info("%s", get_copyright_string())
            _log.info("=" * 60)

            self._paths = self._setup_paths()
            self._initialized = True

            _emit(self.app, "ts_file_generator:initialized", {
                "version": VERSION
            })

        except Exception as e:
            _log.exception("Init misslyckades: %s", e)
            self._initialized = False

    def register_ui(self, parent: Any) -> Any:
        """
        Skapa och returnera UI-widget.
        """
        try:
            from .widget import TSFileGeneratorWidget
            return TSFileGeneratorWidget(parent, self)
        except Exception as e:
            _log.error(
                "Kunde inte registrera UI för TSFileGenerator: %s", e
            )
            return None

    def shutdown(self) -> None:
        """
        Cleanup.
        """
        try:
            self._initialized = False
            _log.info("Shutdown klar.")
        except Exception as e:
            _log.debug("Shutdown error: %s", e)

    def config_schema(self) -> Dict[str, Any]:
        """
        Settings.json schema.
        """
        return {
            "type": "object",
            "properties": {
                "ts_encoding": {
                    "type": "string",
                    "default": TS_ENCODING
                },
                "record_length": {
                    "type": "integer",
                    "default": TS_RECORD_LENGTH
                }
            }
        }

    # ─────────────────────────────────────────────────────────────
    # HEALTH & DIAGNOSTICS
    # ─────────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        try:
            if not self._initialized:
                return False
            ut = self._paths.get("ut")
            if ut is None or not ut.exists():
                return False
            return True
        except Exception:
            return False

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        Hämta diagnostik (version, status, paths, schema-version).

        Returns:
            Dict med diagnostikinformation
        """
        try:
            schema_mgr = self._get_schema_manager()
            schema_version = None
            if schema_mgr is not None and hasattr(
                schema_mgr, "get_active_version"
            ):
                try:
                    schema_version = schema_mgr.get_active_version()
                except Exception:
                    schema_version = None
            return {
                "plugin_name": self.NAME,
                "plugin_version": VERSION,
                "copyright": get_copyright_string(),
                "initialized": self._initialized,
                "healthy": self.health_check(),
                "paths": {k: str(v) for k, v in self._paths.items()},
                "schema_version": schema_version,
                "record_length": TS_RECORD_LENGTH,
                "encoding": TS_ENCODING,
            }
        except Exception as exc:
            return {"error": str(exc)}

    # ─────────────────────────────────────────────────────────────
    # GENERATION
    # ─────────────────────────────────────────────────────────────

    def generate_complete_file(
        self,
        vehicles: List[Dict[str, Any]],
        output_path: Optional[Path] = None,
        manual_batch_file_id: Optional[str] = None,
        skip_registered: bool = True,
        sender_org: str = "",
        responsible: str = "",
        include_pt28: bool = True,
        include_pt45: bool = True,
        include_pt99: bool = True,
    ) -> GenerationResult:
        """
        Generera komplett TS-fil (PT28 + PT45 × n + PT99).

        Postbyggnad sker via RecordBuilder (.record_builder v2.0.1):
        schema-first (ts_schema_manager → ts_spec_import) med
        minimala fallbacks (orgnummer/FilID/VIN/ANTAL_POSTER).

        Args:
            vehicles:           Lista av fordonsdata-dicts (VIN krävs)
            output_path:        Målsökväg (default: ut/TS_<timestamp>.txt)
            manual_batch_file_id: Manuellt batch/FilID (annars auto)
            skip_registered:    Hoppa över redan registrerade VIN —
                                accepteras för framtida statuslagring,
                                ännu no-op i v6.x (OBS, inväntar beslut)
            sender_org:         Avsändar-organisationsnummer (PT28)
            responsible:        Ansvarig kontaktperson (PT28-metadata,
                                används av schema om fält finns)
            include_pt28:       Inkludera PT28 (identitetspost)
            include_pt45:       Inkludera PT45 (fordonsposter)
            include_pt99:       Inkludera PT99 (slutpost)

        Returns:
            GenerationResult
        """
        result = GenerationResult(success=False)

        if not vehicles:
            result.errors.append("Inga fordon att generera.")
            return result

        try:
            schema_mgr = self._get_schema_manager()
            if schema_mgr is not None and hasattr(
                schema_mgr, "get_active_version"
            ):
                try:
                    result.ts_spec_version = schema_mgr.get_active_version()
                except Exception:
                    result.ts_spec_version = None

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_id = (manual_batch_file_id or "").strip() or f"TS{timestamp}"
            batch_id = (manual_batch_file_id or "").strip() or f"TS_{timestamp}"

            lines: List[str] = []
            seq = 0

            # PT28 — identitetspost
            if include_pt28:
                seq += 1
                try:
                    lines.append(
                        self._generate_identity_post(
                            seq, sender_org, file_id, responsible
                        )
                    )
                except ValueError as exc:
                    result.errors.append(str(exc))
                    return result

            # PT45 — en post per fordon
            if include_pt45:
                for vehicle in vehicles:
                    seq += 1
                    try:
                        lines.append(
                            self._generate_vehicle_post(seq, vehicle)
                        )
                    except ValueError as exc:
                        result.errors.append(str(exc))
                        return result

            # PT99 — slutpost
            if include_pt99:
                seq += 1
                try:
                    lines.append(self._generate_end_post(seq, seq))
                except ValueError as exc:
                    result.errors.append(str(exc))
                    return result

            if not lines:
                result.errors.append(
                    "Inga poster genererades "
                    "(kontrollera include_pt*-flaggor)."
                )
                return result

            # Normalisera: exakt 2500 tecken + Latin-1
            normalized = []
            replaced = 0
            for ln in lines:
                ln = ln[:TS_RECORD_LENGTH].ljust(TS_RECORD_LENGTH)
                try:
                    ln.encode(TS_ENCODING)
                except UnicodeEncodeError:
                    ln = ln.encode(
                        TS_ENCODING, errors="replace"
                    ).decode(TS_ENCODING)
                    replaced += 1
                normalized.append(ln)

            content = ("\n".join(normalized) + "\n").encode(TS_ENCODING)
            checksum = hashlib.sha256(content).hexdigest()

            if output_path is None:
                output_path = self._paths["ut"] / f"TS_{timestamp}.txt"

            atomic_write_bytes(output_path, content)

            result.success = True
            result.filepath = output_path
            result.total_records = len(lines)
            result.batch_id = batch_id
            result.checksum_sha256 = checksum

            if replaced:
                result.warnings.append(
                    f"{replaced} rader innehöll ej Latin-1 och ersattes."
                )

            _emit(self.app, "ts_file:generated", {
                "filepath": str(output_path),
                "records": len(vehicles),
                "batch_id": batch_id,
                "checksum_sha256": checksum,
            })

        except Exception as e:
            _log.exception("Generering misslyckades: %s", e)
            result.errors.append(str(e))

        return result

    # ─────────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────────

    def _get_schema_manager(self) -> Optional[Any]:
        """
        Hämta ts_schema_manager kraschsäkert (source of truth).

        Returns:
            Plugin-instans eller None
        """
        if self.app is None:
            return None
        try:
            if hasattr(self.app, "get_plugin"):
                plugin = self.app.get_plugin("ts_schema_manager")
                if plugin is not None:
                    return plugin
        except Exception:
            pass
        try:
            return getattr(self.app, "ts_schema_manager", None)
        except Exception:
            return None

    def _get_builder(self) -> Any:
        """
        Hämta (eller skapa) RecordBuilder-instans (lazy).

        Returns:
            RecordBuilder-instans

        Raises:
            RuntimeError: Om .record_builder saknas
        """
        if self._builder is None:
            if RecordBuilder is None:
                raise RuntimeError(
                    "plugins/ts_file_generator/record_builder.py saknas — "
                    "kan inte bygga TS-poster."
                )
            self._builder = RecordBuilder(app=self.app)
        return self._builder

    def _generate_identity_post(
        self,
        sequence_no: int,
        sender_org: str,
        file_id: str,
        responsible: str = "",
    ) -> str:
        """
        Bygg PT28 (schema-driven via RecordBuilder).

        Args:
            sequence_no: Löpnummer
            sender_org:  Avsändar-organisationsnummer
            file_id:     FilID (max 6 tecken)
            responsible: Ansvarig kontaktperson (extra fältdata)

        Returns:
            Post med exakt 2500 tecken

        Raises:
            ValueError: Om posten inte kunde byggas
        """
        extra_data = None
        if responsible:
            extra_data = {"ANSVARIG": responsible}
        br = self._get_builder().build_identity_post(
            sequence_no=sequence_no,
            orgnummer=sender_org,
            file_id=file_id,
            extra_data=extra_data,
        )
        if not br.success:
            raise ValueError("PT28: " + "; ".join(br.errors))
        return br.record

    def _generate_vehicle_post(
        self,
        sequence_no: int,
        vehicle: Dict[str, Any],
    ) -> str:
        """
        Bygg PT45 (schema-driven via RecordBuilder).

        Args:
            sequence_no: Löpnummer
            vehicle:     Fordonsdata (VIN krävs)

        Returns:
            Post med exakt 2500 tecken

        Raises:
            ValueError: Om VIN saknas eller posten ej kan byggas
        """
        br = self._get_builder().build_vehicle_post(
            sequence_no=sequence_no,
            vehicle_data=vehicle,
        )
        if not br.success:
            raise ValueError("PT45: " + "; ".join(br.errors))
        return br.record

    def _generate_end_post(
        self,
        sequence_no: int,
        total_posts: int,
    ) -> str:
        """
        Bygg PT99 (schema-driven via RecordBuilder).

        Args:
            sequence_no: Löpnummer (= totalt antal poster)
            total_posts: Totalt antal poster i filen

        Returns:
            Post med exakt 2500 tecken

        Raises:
            ValueError: Om posten inte kunde byggas
        """
        br = self._get_builder().build_end_post(
            sequence_no=sequence_no,
            total_posts=total_posts,
        )
        if not br.success:
            raise ValueError("PT99: " + "; ".join(br.errors))
        return br.record

    def _setup_paths(self) -> Dict[str, Path]:
        """
        Sätt upp katalogstruktur (Sektion Z / master v1.4).

        base_path från app (eller cwd); data/ts_file_generator för
        status/backup, ut/ på roten för TS-filer.
        """
        base_path = getattr(self.app, "base_path", None)
        base_path = Path(base_path) if base_path else Path.cwd()

        data_dir = base_path / "data" / "ts_file_generator"
        paths = {
            "base": data_dir,
            "ut": base_path / "ut",
            "status": data_dir / "status",
            "backup": data_dir / "backup",
        }
        for p in paths.values():
            p.mkdir(parents=True, exist_ok=True)
        return paths

    # ─────────────────────────────────────────────────────────────
    # UTILITY
    # ─────────────────────────────────────────────────────────────

    def get_output_dir(self) -> str:
        """
        Returnera ut-katalogen som sträng (widget v5.0.1-anrop).

        Returns:
            Sökväg till ut-katalogen
        """
        return str(self._paths.get("ut", Path("ut")))


# ═══════════════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════════════

__all__ = [
    "Plugin",
    "GenerationResult",
    "get_copyright_string",
    "VERSION",
    "AUTHOR",
    "TS_RECORD_LENGTH",
    "TS_ENCODING",
]
