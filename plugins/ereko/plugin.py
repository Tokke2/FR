# -*- coding: utf-8 -*-
# Fil: plugins/ereko/plugin.py

"""
eReKo / IVI Generator Plugin v1.0.1

Modern, stabil plugin för generering av elektroniska registreringsbevis
(IVI/eCoC) enligt EU-standard och Transportstyrelsens eReKo-krav.

FUNKTIONER:
    1. Generera IVI från vehicle_registry-data
    2. Batchgenerering för flera fordon
    3. Validera befintliga IVI-filer
    4. Export till EUCARIS-format
    5. Historik & loggning
    6. Integration med colors_manager, dealers_manager, SAP-data

SAMARBETE:
    - vehicle_registry: Hämta fordonsdata
    - colors_manager: Färgmatchning
    - dealers_manager: Återförsäljare/tillverkare
    - sap_import: SAP-data för tekniska detaljer
    - dispatch_viewer: Dispatch-info
    - ts_spec_import: Fallback för datavalidering

ARKITEKTUR:
    - Följer PluginBase (init/activate/shutdown + subscribe)
    - Module-level _log (lazy %s — aldrig f-string i logganrop)
    - Lazy model loading (models.py, kraschsäkert)
    - PySide6 är VALFRITT (try/except + HAS_PYSIDE6) — klasser
      definieras villkorligt; headless-import kraschar inte
    - Event-driven integration
    - 100% kraschsäker

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil: plugins/ereko/plugin.py" tillagd
    (saknades — stod utan "Fil:"-prefix).
  - FIX (korrekthet, KRITISK): "finished = Signal(dict)" ÖVERSKUGGADE
    QThread.finished (inbyggd, 0-args) — batch-trådens signal bytt
    till batch_finished; stopp via requestInterruption() i stället
    för terminate() (terminate kan lämna halvskrivna filer).
  - FIX (headless, låst mönster): PySide6-importen på toppnivån
    flyttad till try/except + HAS_PYSIDE6; EReKoWidget och
    BatchGenerationWorker definieras VILLKORLIGT (if HAS_PYSIDE6);
    create_widget() returnerar None utan PySide6 (kraschsäkert,
    samma mönster som gui_helpers-komponenterna). Heltalsversionen
    kraschade vid import i headless/test.
  - FIX (låst regel): logger → modul-nivå _log; _setup_logger() med
    StreamHandler BORT (störde appens loggning — logger-setup ska
    skötas av core/logger_setup); ALLA f-string-logganrop → lazy %s.
  - FIX (KRAV Z, sökvägar): data/ereko/ → json/ereko/ (primär:
    json/ereko/generation_log.json + json/ereko/backup; ut/ereko
    är OUTPUT och behålls). Legacy data/ereko/-sökvägar läses och
    migreras vid init (kopieras till json/, raderas ALDRIG).
  - FIX (dataförlust, låst regel): GenerationLog._save + XML-
    skrivningen i generate_ivi → atomisk skrivning (mkstemp →
    fsync → os.replace); GenerationLog max 500 poster (äldsta
    först ut).
  - FIX (låst regel, inga TODOs): validate_ivi_file — TODO bort,
    riktig XML-validering via xml.etree.ElementTree (välformad +
    rot-element + varning om IVI-nyckel saknas).
  - FIX (låst regel, inga hårdkodade färger): widget-stylesheets +
    HTML-statusfärger byggs från design-tokens (COLORS via
    gui_helpers.components.styles, try/except-fallback).
  - FIX (enums, full form): Qt.green/red → Qt.GlobalColor.green/
    red; Qt.AlignRight → Qt.AlignmentFlag.AlignRight;
    QHeaderView.Stretch → QHeaderView.ResizeMode.Stretch.
  - FIX (livscykel): activate() anropar super().activate()
    (is_active via PluginBase); shutdown() tillagd med
    super().deactivate() + _shutdown_done (avregistrerar
    prenumerationerna automatiskt via _unsubscribe_all_events);
    base_dir → base_path → cwd-fallback.
  - FIX (konsistens): get_plugin_safe med 4-metoders-kedja
    (inkl. plugin_manager, samma som identity_post/gui_helpers).
  - FIX (funktion): _on_batch_start — TODO-dialog bort; batch
    hämtar nu VIN-lista från vehicle_registry (get_all_vins/
    get_vins/list_vins-fallback) eller från fil (VIN-lista),
    begränsad av batch_limit, och kör BatchGenerationWorker med
    progress + resultat + logg-uppdatering.
  - FIX (radbrytningsartefakt): dubblerade blankrader före
    def/class kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (lazy modell-laddning, safe_get,
    generate_ivi-flödet, berikning färg/tillverkare/typgodkännande,
    logg-API, statistik).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple, TYPE_CHECKING

# PySide6 (valfritt — kraschsäkert headless; klasser definieras
# villkorligt nedan, samma mönster som gui_helpers-komponenterna).
try:
    from PySide6.QtCore import Qt, QThread, Signal
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QTableWidget, QTableWidgetItem,
        QHeaderView, QMessageBox, QFileDialog, QComboBox,
        QFrame, QTabWidget, QTextEdit, QLineEdit,
        QProgressBar, QGroupBox, QCheckBox, QSpinBox,
    )
    HAS_PYSIDE6: bool = True
except ImportError:
    HAS_PYSIDE6: bool = False

from core.plugin_base import PluginBase, PluginMetadata

if TYPE_CHECKING:
    from core.application import Application
    from .models import (
        IVIDocument, FuelType, VehicleCategory,
        IVIStatus, Manufacturer, VehicleIdentification,
        TechnicalData, Dimensions, TypeApproval, Color,
    )

# ══════════════════════════════════════════════════════════════════════════════
# COPYRIGHT & CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "1.0.1"
AUTHOR: Final[str] = "Rickard Längkvist"

# Kataloger (json/ primär enligt KRAV Z; ut/ är output).
IVI_OUTPUT_DIR: Final[str] = "ut/ereko"
IVI_BACKUP_DIR: Final[str] = "json/ereko/backup"
IVI_LOG_FILE: Final[str] = "json/ereko/generation_log.json"

# Legacy-sökvägar (data/) — läses + migreras vid init, raderas aldrig.
_LEGACY_BACKUP_DIR: Final[str] = "data/ereko/backup"
_LEGACY_LOG_FILE: Final[str] = "data/ereko/generation_log.json"

# Max antal loggposter (äldsta först ut).
_MAX_LOG_ENTRIES: Final[int] = 500

# Defaults
DEFAULT_ISSUING_AUTHORITY: Final[str] = "Transportstyrelsen"
DEFAULT_ISSUING_COUNTRY: Final[str] = "SE"
DEFAULT_TYPE_APPROVAL_PREFIX: Final[str] = "e1*2018/858*"

def get_copyright_year() -> int:
    """Hämta aktuellt år."""
    return datetime.now().year

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {get_copyright_year()} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log: logging.Logger = logging.getLogger("ereko")


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS — Alla är 100% kraschsäkra
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Robust plugin-hämtning. KRASCHSÄKER.

    Försöker i ordning:
    1. app.get_plugin(name)
    2. app.plugin_loader.get_plugin(name)
    3. app.plugin_manager.get_plugin(name) (legacy)
    4. getattr(app, name)
    """
    if app is None:
        return None

    candidates = (
        name,
        name.lower().replace(" ", "_").replace("-", "_"),
    )
    for try_name in candidates:
        try:
            gp = getattr(app, "get_plugin", None)
            if callable(gp):
                result = gp(try_name)
                if result is not None:
                    return result
        except Exception:
            pass
        try:
            loader = getattr(app, "plugin_loader", None)
            if loader is not None and hasattr(loader, "get_plugin"):
                result = loader.get_plugin(try_name)
                if result is not None:
                    return result
        except Exception:
            pass
        try:
            manager = getattr(app, "plugin_manager", None)
            if manager is not None and hasattr(manager, "get_plugin"):
                result = manager.get_plugin(try_name)
                if result is not None:
                    return result
        except Exception:
            pass
    try:
        attr_name = name.replace("-", "_").replace(" ", "_").lower()
        if hasattr(app, attr_name):
            return getattr(app, attr_name)
    except Exception:
        pass
    return None

def emit_event_safe(
    app: Any,
    event_name: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Emit event säkert. KRASCHSÄKER."""
    try:
        bus = getattr(app, "event_bus", None)
        if bus is not None and hasattr(bus, "emit"):
            bus.emit(event_name, data or {})
            return True
        # Fallback: core_events-plugin
        events = get_plugin_safe(app, "core_events")
        if events is not None and hasattr(events, "emit"):
            events.emit(event_name, data or {})
            return True
    except Exception as exc:
        _log.debug(
            "Event emit misslyckades '%s': %s", event_name, exc
        )
    return False

def safe_get(
    data: Dict[str, Any], *keys: str, default: Any = None
) -> Any:
    """
    Säkert hämta värde från dict med fallback-nycklar.

    Args:
        data: Dict att söka i
        *keys: Nycklar att prova (i ordning)
        default: Default-värde om ingen nyckel finns

    Returns:
        Värde eller default
    """
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default

def _atomic_write_text(path: Path, text: str) -> None:
    """
    Atomisk textskrivning (låst regel: mkstemp → fsync → os.replace).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".ereko_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
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
# LAZY MODEL LOADING — Undviker cirkulära imports
# ══════════════════════════════════════════════════════════════════════════════

_models_cache: Dict[str, Any] = {}

def _get_model(name: str) -> Optional[Any]:
    """Lazy-load en modell från models.py. KRASCHSÄKER."""
    if name in _models_cache:
        return _models_cache[name]

    try:
        from . import models
        cls = getattr(models, name, None)
        if cls is not None:
            _models_cache[name] = cls
        return cls
    except ImportError as exc:
        _log.debug("Kunde inte importera modell %s: %s", name, exc)
        return None
    except Exception as exc:
        _log.debug("Fel vid laddning av modell %s: %s", name, exc)
        return None

def _get_IVIDocument() -> Optional[type]:
    """Lazy-load IVIDocument."""
    return _get_model("IVIDocument")

def _get_FuelType() -> Optional[type]:
    """Lazy-load FuelType."""
    return _get_model("FuelType")

def _get_VehicleCategory() -> Optional[type]:
    """Lazy-load VehicleCategory."""
    return _get_model("VehicleCategory")

def _get_Manufacturer() -> Optional[type]:
    """Lazy-load Manufacturer."""
    return _get_model("Manufacturer")

def _get_VehicleIdentification() -> Optional[type]:
    """Lazy-load VehicleIdentification."""
    return _get_model("VehicleIdentification")

def _get_TechnicalData() -> Optional[type]:
    """Lazy-load TechnicalData."""
    return _get_model("TechnicalData")

def _get_Dimensions() -> Optional[type]:
    """Lazy-load Dimensions."""
    return _get_model("Dimensions")

def _get_TypeApproval() -> Optional[type]:
    """Lazy-load TypeApproval."""
    return _get_model("TypeApproval")

def _get_Color() -> Optional[type]:
    """Lazy-load Color."""
    return _get_model("Color")


# ══════════════════════════════════════════════════════════════════════════════
# GENERATION LOG
# ══════════════════════════════════════════════════════════════════════════════

class GenerationLog:
    """
    Logg för genererade IVI-dokument.

    Sparar historik i JSON-fil (atomisk skrivning, max 500 poster).
    """

    def __init__(self, log_file: Path) -> None:
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        """Ladda befintlig logg. KRASCHSÄKER."""
        try:
            if self.log_file.exists():
                with open(self.log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._entries = data
        except Exception as exc:
            _log.warning(
                "Kunde inte läsa genereringslogg %s: %s",
                self.log_file,
                exc,
            )
            self._entries = []

    def _save(self) -> None:
        """Spara logg atomiskt. KRASCHSÄKER."""
        try:
            _atomic_write_text(
                self.log_file,
                json.dumps(
                    self._entries, indent=2, ensure_ascii=False
                ),
            )
        except Exception as exc:
            _log.error(
                "Kunde inte spara genereringslogg %s: %s",
                self.log_file,
                exc,
            )

    def add_entry(
        self,
        vin: str,
        document_id: str,
        output_path: str,
        status: str,
        errors: Optional[List[str]] = None,
    ) -> None:
        """Lägg till loggpost (max _MAX_LOG_ENTRIES, äldsta först ut)."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "vin": vin,
            "document_id": document_id,
            "output_path": output_path,
            "status": status,
            "errors": errors or [],
        }
        self._entries.append(entry)
        if len(self._entries) > _MAX_LOG_ENTRIES:
            self._entries = self._entries[-_MAX_LOG_ENTRIES:]
        self._save()

    def get_entries(
        self,
        vin: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Hämta loggposter (senaste först)."""
        entries = self._entries

        if vin:
            entries = [e for e in entries if e.get("vin") == vin]

        # Senaste först
        entries = sorted(
            entries,
            key=lambda e: e.get("timestamp", ""),
            reverse=True,
        )

        if limit:
            entries = entries[:limit]

        return entries

    def get_statistics(self) -> Dict[str, Any]:
        """Hämta statistik."""
        total = len(self._entries)
        valid = sum(
            1 for e in self._entries if e.get("status") == "valid"
        )
        invalid = sum(
            1 for e in self._entries if e.get("status") == "invalid"
        )

        return {
            "total": total,
            "valid": valid,
            "invalid": invalid,
            "success_rate": round(valid / total * 100, 1)
            if total > 0
            else 0,
        }


# ══════════════════════════════════════════════════════════════════════════════
# BATCH GENERATION WORKER
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class BatchGenerationWorker(QThread):
        """Worker-tråd för batchgenerering av IVI-dokument."""

        progress = Signal(int, int, str)  # current, total, message
        batch_finished = Signal(dict)  # result (INTE "finished" —
            # QThread har en inbyggd finished-signal (0-args) som
            # annars överskuggas)

        def __init__(
            self,
            plugin: "Plugin",
            vins: List[str],
            output_dir: Path,
        ) -> None:
            super().__init__()
            self.plugin = plugin
            self.vins = list(vins)
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)

        def run(self) -> None:
            """Kör batchgenerering (avbrytbar via requestInterruption)."""
            result: Dict[str, Any] = {
                "total": len(self.vins),
                "success": 0,
                "failed": 0,
                "errors": [],
            }

            for i, vin in enumerate(self.vins, 1):
                if self.isInterruptionRequested():
                    result["errors"].append("Avbruten av användaren")
                    break

                self.progress.emit(
                    i, len(self.vins), "Genererar %s..." % vin
                )

                try:
                    ivi_result = self.plugin.generate_ivi(
                        vin, self.output_dir
                    )
                    if ivi_result.get("success"):
                        result["success"] += 1
                    else:
                        result["failed"] += 1
                        result["errors"].append(
                            "%s: %s"
                            % (
                                vin,
                                ", ".join(
                                    ivi_result.get("errors", [])
                                ),
                            )
                        )
                except Exception as exc:
                    result["failed"] += 1
                    result["errors"].append(
                        "%s: %s" % (vin, exc)
                    )

            self.batch_finished.emit(result)


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    eReKo / IVI Generator Plugin v1.0.1

    Genererar elektroniska registreringsbevis (IVI/eCoC) enligt
    EU-standard.
    """

    METADATA = PluginMetadata(
        name="ereko",
        version=VERSION,
        description=(
            "eReKo / IVI Generator — Elektroniska registreringsbevis "
            "enligt EU-standard"
        ),
        author=AUTHOR,
        dependencies=(),  # Inga hårda beroenden
        optional_dependencies=(
            "vehicle_registry",
            "colors_manager",
            "dealers_manager",
            "sap_import",
            "dispatch_viewer",
            "ts_spec_import",
        ),
        has_ui=True,
        screen_aware=True,
        dpi_aware=True,
    )

    def __init__(self, app: "Application") -> None:
        """
        Initiera plugin.

        Args:
            app: Application-instans
        """
        super().__init__(app)

        # State
        self._initialized: bool = False
        self._output_dir: Optional[Path] = None
        self._backup_dir: Optional[Path] = None
        self._generation_log: Optional[GenerationLog] = None
        self._shutdown_done: bool = False

        # Samarbete med andra plugins
        self._vehicle_registry: Optional[Any] = None
        self._colors_manager: Optional[Any] = None
        self._dealers_manager: Optional[Any] = None
        self._sap_import: Optional[Any] = None

        # UI
        self._widget: Optional[Any] = None

    @property
    def copyright(self) -> str:
        """Dynamisk copyright-sträng."""
        return get_copyright_string()

    # ═══════════════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════════

    def initialize(self) -> None:
        """
        Initiera plugin (PluginBase-hook; anropas via init()).

        100% KRASCHSÄKER.
        """
        try:
            _log.info("=" * 60)
            _log.info("eReKo / IVI Generator v%s", VERSION)
            _log.info("%s", self.copyright)
            _log.info("=" * 60)

            # Setup directories (base_dir → base_path → cwd)
            base = getattr(self.app, "base_dir", None)
            if not base:
                base = getattr(self.app, "base_path", ".")
            base_path = Path(str(base))

            self._output_dir = base_path / IVI_OUTPUT_DIR
            self._output_dir.mkdir(parents=True, exist_ok=True)

            self._backup_dir = base_path / IVI_BACKUP_DIR
            self._backup_dir.mkdir(parents=True, exist_ok=True)

            # Migrera legacy-logg (data/ → json/) om primär saknas.
            # Legacy-filen raderas ALDRIG automatiskt.
            log_file = base_path / IVI_LOG_FILE
            legacy_log_file = base_path / _LEGACY_LOG_FILE
            if (
                not log_file.exists()
                and legacy_log_file.exists()
            ):
                try:
                    log_file.parent.mkdir(
                        parents=True, exist_ok=True
                    )
                    shutil.copy2(str(legacy_log_file), str(log_file))
                    _log.info(
                        "Legacy-logg migrerad: %s → %s",
                        legacy_log_file.name,
                        log_file,
                    )
                except Exception as exc:
                    _log.warning(
                        "Kunde inte migrera legacy-logg %s: %s",
                        legacy_log_file,
                        exc,
                    )
            self._generation_log = GenerationLog(log_file)

            # Registrera i app
            try:
                self.app.ereko = self
            except Exception:
                pass

            self._initialized = True

            _log.info("Output directory: %s", self._output_dir)
            _log.info("Backup directory: %s", self._backup_dir)
            _log.info("Initialized successfully")

        except Exception as exc:
            _log.error(
                "Initiering misslyckades: %s", exc, exc_info=True
            )
            self._initialized = False

    def activate(self) -> None:
        """Aktivera plugin. KRASCHSÄKER."""
        try:
            # PluginBase: is_active + _activate_time.
            try:
                super().activate()
            except Exception:
                _log.exception("PluginBase.activate misslyckades.")

            # Hämta andra plugins
            self._vehicle_registry = self.get_plugin_safe(
                "vehicle_registry"
            )
            self._colors_manager = self.get_plugin_safe(
                "colors_manager"
            )
            self._dealers_manager = self.get_plugin_safe(
                "dealers_manager"
            )
            self._sap_import = self.get_plugin_safe("sap_import")

            # Prenumerera på events (avregistreras automatiskt av
            # PluginBase.deactivate → _unsubscribe_all_events).
            self.subscribe("vehicle:updated", self._on_vehicle_updated)
            self.subscribe("sap:imported", self._on_sap_imported)

            emit_event_safe(self.app, "ereko:activated", {
                "version": VERSION,
                "output_dir": str(self._output_dir),
            })

            _log.info("Activated")

        except Exception as exc:
            _log.error("Aktivering misslyckades: %s", exc)

    def shutdown(self) -> None:
        """
        Städa upp (avregistrerar events + state → INACTIVE).

        Anropar super().deactivate() (INTE super().shutdown() —
        PluginBase.shutdown() anropar polymorft self.deactivate() →
        ömsesidig rekursion; super().deactivate() körs direkt).
        """
        if self._shutdown_done:
            return
        self._shutdown_done = True
        try:
            _log.info("%s deactivated", "eReKo")
        except Exception as exc:
            _log.error(
                "Shutdown misslyckades: %s", exc, exc_info=True
            )
        finally:
            try:
                super().deactivate()
            except Exception:
                _log.exception("PluginBase.deactivate misslyckades.")

    def _on_vehicle_updated(
        self, event_data: Dict[str, Any]
    ) -> None:
        """Event handler: fordon uppdaterat."""
        try:
            vin = event_data.get("vin")
            if vin:
                _log.debug("Vehicle updated: %s", vin)
        except Exception:
            pass

    def _on_sap_imported(
        self, event_data: Dict[str, Any]
    ) -> None:
        """Event handler: SAP-data importerad."""
        try:
            _log.debug("SAP data imported")
        except Exception:
            pass

    def create_widget(self, parent: Any) -> Optional[Any]:
        """
        Skapa GUI-widget (kräver PySide6).

        KRASCHSÄKER — returnerar None utan PySide6 eller vid fel.

        Args:
            parent: Parent widget

        Returns:
            EReKoWidget eller None
        """
        if not HAS_PYSIDE6:
            _log.debug("PySide6 saknas — ingen ereko-widget.")
            return None
        try:
            self._widget = EReKoWidget(parent, self)
            return self._widget
        except Exception as exc:
            _log.error(
                "Kunde inte skapa widget: %s", exc, exc_info=True
            )
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API — IVI GENERATION
    # ═══════════════════════════════════════════════════════════════════════════

    def generate_ivi(
        self,
        vin: str,
        output_dir: Optional[Path] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generera IVI-dokument för ett fordon.

        KRASCHSÄKER.

        Args:
            vin: VIN-nummer
            output_dir: Output-katalog (None = default)
            overrides: Överskrid specifika fält (optional)

        Returns:
            Dict med resultat:
            {
                "success": bool,
                "vin": str,
                "document_id": str,
                "output_path": str,
                "errors": List[str],
                "warnings": List[str],
            }
        """
        result: Dict[str, Any] = {
            "success": False,
            "vin": vin,
            "document_id": "",
            "output_path": "",
            "errors": [],
            "warnings": [],
        }

        try:
            # Hämta fordonsdata
            vehicle_data = self._get_vehicle_data(vin)
            if not vehicle_data:
                result["errors"].append(
                    "Fordon %s hittades inte" % vin
                )
                return result

            # Berika med färgdata
            vehicle_data = self._enrich_color_data(vehicle_data)

            # Berika med tillverkardata
            manufacturer_data = self._get_manufacturer_data(
                vehicle_data
            )

            # Berika med typgodkännande
            type_approval_data = self._get_type_approval_data(
                vehicle_data
            )

            # Apply overrides
            if overrides:
                vehicle_data.update(overrides)

            # Skapa IVI-dokument
            IVIDocument = _get_IVIDocument()
            if not IVIDocument:
                result["errors"].append(
                    "IVIDocument-modellen är inte tillgänglig "
                    "(models.py saknas?)"
                )
                return result

            ivi = IVIDocument.from_vehicle_data(
                vehicle_data=vehicle_data,
                manufacturer_data=manufacturer_data,
                type_approval_data=type_approval_data,
            )

            result["document_id"] = ivi.document_id

            # Validera
            if not ivi.validate():
                result["errors"].extend(ivi.validation_errors)
                result["warnings"].extend(ivi.validation_warnings)

                # Logga
                if self._generation_log:
                    self._generation_log.add_entry(
                        vin=vin,
                        document_id=ivi.document_id,
                        output_path="",
                        status="invalid",
                        errors=ivi.validation_errors,
                    )

                return result

            # Warnings (inte blockerande)
            result["warnings"].extend(ivi.validation_warnings)

            # Generera XML
            xml_content = ivi.to_xml()

            # Spara fil (atomiskt)
            if output_dir is None:
                output_dir = self._output_dir
            else:
                output_dir = Path(output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)

            filename = "IVI_%s_%s.xml" % (
                vin,
                datetime.now().strftime("%Y%m%d_%H%M%S"),
            )
            output_path = output_dir / filename

            _atomic_write_text(output_path, xml_content)

            result["success"] = True
            result["output_path"] = str(output_path)

            # Logga
            if self._generation_log:
                self._generation_log.add_entry(
                    vin=vin,
                    document_id=ivi.document_id,
                    output_path=str(output_path),
                    status="valid",
                )

            # Emit event
            emit_event_safe(self.app, "ereko:ivi_generated", {
                "vin": vin,
                "document_id": ivi.document_id,
                "output_path": str(output_path),
            })

            _log.info(
                "IVI genererad: %s → %s", vin, output_path
            )

        except Exception as exc:
            _log.exception("Kunde inte generera IVI för %s", vin)
            result["errors"].append(str(exc))

        return result

    def validate_ivi_file(self, filepath: Path) -> Dict[str, Any]:
        """
        Validera befintlig IVI-fil (XML-välformad + grundläggande
        struktur).

        KRASCHSÄKER.

        Args:
            filepath: Sökväg till IVI XML-fil

        Returns:
            Dict med valideringsresultat
        """
        result: Dict[str, Any] = {
            "success": False,
            "filepath": str(filepath),
            "is_valid": False,
            "errors": [],
            "warnings": [],
        }

        try:
            filepath = Path(filepath)
            if not filepath.exists():
                result["errors"].append("Filen finns inte")
                return result

            # Läs fil
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                result["errors"].append("Filen är tom")
                return result

            # XML-parse (välformad + rot-element)
            try:
                root = ET.fromstring(content)
            except ET.ParseError as exc:
                result["errors"].append(
                    "Inte en giltig XML-fil: %s" % exc
                )
                return result

            # Grundläggande IVI-struktur-kontroll (fuzzy — fältnamn
            # kan variera mellan EUCARIS-versioner)
            lowered = content.lower()
            has_document_id = "document_id" in lowered
            has_vin = "<vin" in lowered or "vin>" in lowered
            root_tag = (root.tag or "").lower()

            if not (
                has_document_id
                or "ecoc" in root_tag
                or "ivi" in root_tag
            ):
                result["warnings"].append(
                    "Kunde inte hitta document_id/IVI-struktur — "
                    "dokumentet kanske inte är ett IVI-bevis"
                )
            if not has_vin:
                result["warnings"].append(
                    "Kunde inte hitta VIN-fält i dokumentet"
                )

            result["is_valid"] = True
            result["success"] = True

        except Exception as exc:
            result["errors"].append(str(exc))

        return result

    def batch_generate(
        self,
        vins: List[str],
        output_dir: Optional[Path] = None,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Batch-generera IVI för flera fordon.

        KRASCHSÄKER.

        Args:
            vins: Lista med VIN-nummer
            output_dir: Output-katalog (None = default)
            progress_callback: Callback för progress (optional)

        Returns:
            Dict med sammanfattning
        """
        result: Dict[str, Any] = {
            "total": len(vins),
            "success": 0,
            "failed": 0,
            "errors": [],
        }

        if output_dir is None:
            output_dir = self._output_dir

        for i, vin in enumerate(vins, 1):
            if progress_callback:
                try:
                    progress_callback(
                        i, len(vins), "Genererar %s..." % vin
                    )
                except Exception:
                    pass

            ivi_result = self.generate_ivi(vin, output_dir)
            if ivi_result["success"]:
                result["success"] += 1
            else:
                result["failed"] += 1
                result["errors"].append(
                    "%s: %s"
                    % (vin, ", ".join(ivi_result.get("errors", [])))
                )

        return result

    def get_generation_log(
        self,
        vin: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Hämta genereringslogg.

        Args:
            vin: Filtrera på VIN (None = alla)
            limit: Max antal poster

        Returns:
            Lista med loggposter
        """
        if not self._generation_log:
            return []

        return self._generation_log.get_entries(vin=vin, limit=limit)

    def get_statistics(self) -> Dict[str, Any]:
        """
        Hämta statistik.

        Returns:
            Dict med statistik
        """
        stats: Dict[str, Any] = {
            "plugin_version": VERSION,
            "copyright": self.copyright,
            "initialized": self._initialized,
            "is_active": self.is_active,
            "output_dir": str(self._output_dir)
            if self._output_dir
            else "",
            "generation_log": {},
        }

        if self._generation_log:
            stats["generation_log"] = (
                self._generation_log.get_statistics()
            )

        return stats

    # ═══════════════════════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _get_vehicle_data(
        self, vin: str
    ) -> Optional[Dict[str, Any]]:
        """
        Hämta fordonsdata från vehicle_registry.

        KRASCHSÄKER.

        Args:
            vin: VIN-nummer

        Returns:
            Dict med fordonsdata eller None
        """
        if not self._vehicle_registry:
            _log.warning("vehicle_registry inte tillgängligt")
            return None

        try:
            # Försök olika metoder
            methods = [
                lambda: self._vehicle_registry.get_vehicle(vin),
                lambda: self._vehicle_registry.get_by_vin(vin),
                lambda: self._vehicle_registry.find_vehicle(vin),
            ]

            for method in methods:
                try:
                    vehicle = method()
                    if vehicle:
                        # Konvertera till dict om nödvändigt
                        if hasattr(vehicle, "to_dict"):
                            return vehicle.to_dict()
                        if isinstance(vehicle, dict):
                            return vehicle
                        # Försök extrahera attribut
                        return {
                            attr: getattr(vehicle, attr)
                            for attr in dir(vehicle)
                            if not attr.startswith("_")
                            and not callable(getattr(vehicle, attr))
                        }
                except Exception:
                    continue

        except Exception as exc:
            _log.error(
                "Kunde inte hämta fordonsdata för %s: %s",
                vin,
                exc,
            )

        return None

    def _enrich_color_data(
        self, vehicle_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Berika med färgdata från colors_manager.

        KRASCHSÄKER.
        """
        if not self._colors_manager:
            return vehicle_data

        try:
            color_code = safe_get(
                vehicle_data, "color_code", "fargkod"
            )
            if color_code and hasattr(
                self._colors_manager, "resolve_color"
            ):
                color_name = self._colors_manager.resolve_color(
                    color_code
                )
                if color_name:
                    vehicle_data["exterior_color"] = color_name
        except Exception:
            pass

        return vehicle_data

    def _get_manufacturer_data(
        self, vehicle_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Hämta tillverkardata.

        KRASCHSÄKER.
        """
        if not self._dealers_manager:
            # Fallback: använd märke som tillverkare
            make = safe_get(
                vehicle_data, "make", "marke", "tillverkare"
            )
            if make:
                return {
                    "name": make,
                    "country": "SE",
                }
            return None

        try:
            dealer_id = safe_get(
                vehicle_data, "dealer_id", "aterforsaljare_id"
            )
            if dealer_id and hasattr(
                self._dealers_manager, "get_dealer"
            ):
                dealer = self._dealers_manager.get_dealer(dealer_id)
                if dealer:
                    if hasattr(dealer, "to_dict"):
                        return dealer.to_dict()
                    if isinstance(dealer, dict):
                        return dealer
        except Exception:
            pass

        return None

    def _get_type_approval_data(
        self, vehicle_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Hämta typgodkännandedata.

        KRASCHSÄKER.
        """
        try:
            approval_number = safe_get(
                vehicle_data,
                "type_approval",
                "typgodkannande",
                "approval_number",
            )

            if not approval_number:
                # Generera placeholder
                approval_number = (
                    "%s00000*00" % DEFAULT_TYPE_APPROVAL_PREFIX
                )

            approval_date = safe_get(
                vehicle_data, "approval_date", "godkannandedatum"
            )

            if not approval_date:
                approval_date = datetime.now().strftime("%Y-%m-%d")

            return {
                "approval_number": approval_number,
                "approval_date": approval_date,
                "issuing_authority": DEFAULT_ISSUING_AUTHORITY,
                "issuing_country": DEFAULT_ISSUING_COUNTRY,
            }
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    # Design-tokens (try/except-fallback — kraschsäkert).
    try:
        from plugins.gui_helpers.components.styles import COLORS as _C
    except ImportError:
        _C: Dict[str, str] = {}

    _W_SUCCESS: str = _C.get("success", "#28a745")
    _W_PRIMARY: str = _C.get("primary", "#007bff")
    _W_DANGER: str = _C.get("danger", "#dc3545")
    _W_TEXT_SECONDARY: str = _C.get("text_secondary", "#888888")
    _W_TEXT_MUTED: str = _C.get("text_muted", "#666666")

    class EReKoWidget(QWidget):
        """
        GUI-widget för eReKo / IVI Generator.

        Tabs:
        1. Generera — Skapa IVI för ett fordon
        2. Batch — Massexport från vehicle_registry
        3. Validera — Validera befintlig IVI-fil
        4. Logg — Historik över genererade IVI
        """

        def __init__(
            self, parent: QWidget, plugin: "Plugin"
        ) -> None:
            """
            Initiera widget.

            Args:
                parent: Parent widget
                plugin: Plugin-instans
            """
            super().__init__(parent)
            self.plugin = plugin
            self._batch_worker: Optional[BatchGenerationWorker] = None

            try:
                self._setup_ui()
                self._refresh_log()
            except Exception as exc:
                _log.error(
                    "Widget-initiering misslyckades: %s",
                    exc,
                    exc_info=True,
                )

        def _setup_ui(self) -> None:
            """Skapa UI."""
            layout = QVBoxLayout(self)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(12)

            # Header
            header = QHBoxLayout()
            title = QLabel("📄 eReKo / IVI Generator")
            title.setStyleSheet("font-size: 18px; font-weight: bold;")
            header.addWidget(title)
            header.addStretch()

            version_label = QLabel("v%s" % VERSION)
            version_label.setStyleSheet(
                "color: %s;" % _W_TEXT_SECONDARY
            )
            header.addWidget(version_label)

            layout.addLayout(header)

            # Tabs
            self.tabs = QTabWidget()

            # Tab 1: Generera
            self.tabs.addTab(
                self._create_generate_tab(), "🔨 Generera"
            )

            # Tab 2: Batch
            self.tabs.addTab(self._create_batch_tab(), "📦 Batch")

            # Tab 3: Validera
            self.tabs.addTab(
                self._create_validate_tab(), "✓ Validera"
            )

            # Tab 4: Logg
            self.tabs.addTab(self._create_log_tab(), "📋 Logg")

            layout.addWidget(self.tabs, 1)

            # Footer
            footer = QLabel(self.plugin.copyright)
            footer.setStyleSheet(
                "color: %s; font-size: 10px;" % _W_TEXT_MUTED
            )
            footer.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(footer)

        def _create_generate_tab(self) -> QWidget:
            """Skapa Generate-tab."""
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setSpacing(12)

            # Input group
            input_group = QGroupBox("Fordonsinformation")
            input_layout = QGridLayout(input_group)

            input_layout.addWidget(QLabel("VIN:"), 0, 0)
            self.vin_input = QLineEdit()
            self.vin_input.setPlaceholderText("YV1LSXXXXX1234567")
            self.vin_input.setMaxLength(17)
            input_layout.addWidget(self.vin_input, 0, 1)

            btn_load = QPushButton("📥 Ladda från registry")
            btn_load.clicked.connect(self._on_load_vehicle)
            input_layout.addWidget(btn_load, 0, 2)

            layout.addWidget(input_group)

            # Preview
            preview_group = QGroupBox("Förhandsgranskning")
            preview_layout = QVBoxLayout(preview_group)

            self.preview_text = QTextEdit()
            self.preview_text.setReadOnly(True)
            self.preview_text.setMaximumHeight(200)
            preview_layout.addWidget(self.preview_text)

            layout.addWidget(preview_group)

            # Actions
            actions = QHBoxLayout()
            actions.addStretch()

            btn_generate = QPushButton("🔨 Generera IVI")
            btn_generate.clicked.connect(self._on_generate)
            btn_generate.setStyleSheet(
                "QPushButton { background: %s; color: white; "
                "padding: 8px 16px; }" % _W_SUCCESS
            )
            actions.addWidget(btn_generate)

            layout.addLayout(actions)
            layout.addStretch()

            return widget

        def _create_batch_tab(self) -> QWidget:
            """Skapa Batch-tab."""
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setSpacing(12)

            # Settings
            settings_group = QGroupBox("Inställningar")
            settings_layout = QGridLayout(settings_group)

            settings_layout.addWidget(QLabel("Källa:"), 0, 0)
            self.batch_source = QComboBox()
            self.batch_source.addItems([
                "vehicle_registry (alla)",
                "vehicle_registry (obehandlade)",
                "Från fil (VIN-lista)",
            ])
            settings_layout.addWidget(self.batch_source, 0, 1)

            settings_layout.addWidget(QLabel("Max antal:"), 1, 0)
            self.batch_limit = QSpinBox()
            self.batch_limit.setRange(1, 10000)
            self.batch_limit.setValue(100)
            settings_layout.addWidget(self.batch_limit, 1, 1)

            layout.addWidget(settings_group)

            # Progress
            progress_group = QGroupBox("Progress")
            progress_layout = QVBoxLayout(progress_group)

            self.batch_progress = QProgressBar()
            progress_layout.addWidget(self.batch_progress)

            self.batch_status = QLabel("Klar att starta")
            progress_layout.addWidget(self.batch_status)

            layout.addWidget(progress_group)

            # Actions
            actions = QHBoxLayout()
            actions.addStretch()

            self.btn_batch_start = QPushButton("▶️ Starta batch")
            self.btn_batch_start.clicked.connect(
                self._on_batch_start
            )
            self.btn_batch_start.setStyleSheet(
                "QPushButton { background: %s; color: white; "
                "padding: 8px 16px; }" % _W_PRIMARY
            )
            actions.addWidget(self.btn_batch_start)

            self.btn_batch_stop = QPushButton("⏹️ Stoppa")
            self.btn_batch_stop.clicked.connect(self._on_batch_stop)
            self.btn_batch_stop.setEnabled(False)
            actions.addWidget(self.btn_batch_stop)

            layout.addLayout(actions)
            layout.addStretch()

            return widget

        def _create_validate_tab(self) -> QWidget:
            """Skapa Validate-tab."""
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setSpacing(12)

            # File selection
            file_group = QGroupBox("Välj IVI-fil")
            file_layout = QHBoxLayout(file_group)

            self.validate_file_input = QLineEdit()
            self.validate_file_input.setReadOnly(True)
            file_layout.addWidget(self.validate_file_input)

            btn_browse = QPushButton("📂 Bläddra...")
            btn_browse.clicked.connect(self._on_browse_validate)
            file_layout.addWidget(btn_browse)

            layout.addWidget(file_group)

            # Results
            results_group = QGroupBox("Valideringsresultat")
            results_layout = QVBoxLayout(results_group)

            self.validate_results = QTextEdit()
            self.validate_results.setReadOnly(True)
            results_layout.addWidget(self.validate_results)

            layout.addWidget(results_group)

            # Actions
            actions = QHBoxLayout()
            actions.addStretch()

            btn_validate = QPushButton("✓ Validera")
            btn_validate.clicked.connect(self._on_validate)
            actions.addWidget(btn_validate)

            layout.addLayout(actions)

            return widget

        def _create_log_tab(self) -> QWidget:
            """Skapa Log-tab."""
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setSpacing(12)

            # Filters
            filters = QHBoxLayout()
            filters.addWidget(QLabel("VIN:"))
            self.log_vin_filter = QLineEdit()
            self.log_vin_filter.setPlaceholderText(
                "Filtrera på VIN (tom = alla)"
            )
            self.log_vin_filter.textChanged.connect(self._refresh_log)
            filters.addWidget(self.log_vin_filter)

            btn_refresh_log = QPushButton("🔄 Uppdatera")
            btn_refresh_log.clicked.connect(self._refresh_log)
            filters.addWidget(btn_refresh_log)

            layout.addLayout(filters)

            # Table
            self.log_table = QTableWidget()
            self.log_table.setColumnCount(5)
            self.log_table.setHorizontalHeaderLabels([
                "Tidpunkt", "VIN", "Dokument-ID", "Status", "Fil",
            ])
            self.log_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Stretch
            )
            layout.addWidget(self.log_table)

            # Statistics
            stats_group = QGroupBox("Statistik")
            stats_layout = QGridLayout(stats_group)

            self.stat_total = QLabel("0")
            stats_layout.addWidget(QLabel("Totalt:"), 0, 0)
            stats_layout.addWidget(self.stat_total, 0, 1)

            self.stat_valid = QLabel("0")
            stats_layout.addWidget(QLabel("Giltiga:"), 1, 0)
            stats_layout.addWidget(self.stat_valid, 1, 1)

            self.stat_invalid = QLabel("0")
            stats_layout.addWidget(QLabel("Ogiltiga:"), 2, 0)
            stats_layout.addWidget(self.stat_invalid, 2, 1)

            self.stat_success_rate = QLabel("0%")
            stats_layout.addWidget(QLabel("Framgångsgrad:"), 3, 0)
            stats_layout.addWidget(self.stat_success_rate, 3, 1)

            layout.addWidget(stats_group)

            return widget

        # ═══════════════════════════════════════════════════════════════════════
        # EVENT HANDLERS
        # ═══════════════════════════════════════════════════════════════════════

        def _on_load_vehicle(self) -> None:
            """Ladda fordon från registry."""
            vin = self.vin_input.text().strip().upper()
            if not vin:
                QMessageBox.warning(self, "Varning", "Ange VIN")
                return

            try:
                vehicle_data = self.plugin._get_vehicle_data(vin)
                if not vehicle_data:
                    QMessageBox.warning(
                        self,
                        "Varning",
                        "Fordon %s hittades inte i registry" % vin,
                    )
                    return

                # Visa preview
                preview_lines = [
                    "VIN: %s" % vin,
                    "Märke: %s"
                    % safe_get(
                        vehicle_data,
                        "make",
                        "marke",
                        default="?",
                    ),
                    "Modell: %s"
                    % safe_get(
                        vehicle_data,
                        "model",
                        "modell",
                        default="?",
                    ),
                    "Bränsle: %s"
                    % safe_get(
                        vehicle_data,
                        "fuel_type",
                        "bransle",
                        default="?",
                    ),
                    "Vikt: %s kg"
                    % safe_get(
                        vehicle_data,
                        "mass_kg",
                        "tjanstevikt",
                        default="?",
                    ),
                ]
                self.preview_text.setPlainText(
                    "\n".join(preview_lines)
                )

            except Exception as exc:
                QMessageBox.critical(
                    self, "Fel", "Kunde inte ladda fordon: %s" % exc
                )

        def _on_generate(self) -> None:
            """Generera IVI."""
            vin = self.vin_input.text().strip().upper()
            if not vin:
                QMessageBox.warning(self, "Varning", "Ange VIN")
                return

            try:
                result = self.plugin.generate_ivi(vin)

                if result["success"]:
                    msg = "✅ IVI genererad!\n\n"
                    msg += "VIN: %s\n" % vin
                    msg += "Dokument-ID: %s\n" % result["document_id"]
                    msg += "Fil: %s\n" % result["output_path"]

                    if result.get("warnings"):
                        msg += "\nVarningar:\n" + "\n".join(
                            "• %s" % w for w in result["warnings"]
                        )

                    QMessageBox.information(self, "Klart", msg)
                    self._refresh_log()
                else:
                    msg = "❌ Kunde inte generera IVI\n\n"
                    msg += "Fel:\n" + "\n".join(
                        "• %s" % e for e in result["errors"]
                    )
                    QMessageBox.critical(self, "Fel", msg)

            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Fel",
                    "Generering misslyckades: %s" % exc,
                )

        def _collect_batch_vins(self) -> List[str]:
            """
            Samla VIN-lista enligt vald batch-källa.

            Returns:
                Lista med VIN (kan vara tom)
            """
            source = self.batch_source.currentIndex()
            limit = self.batch_limit.value()

            vins: List[str] = []

            if source in (0, 1):
                # vehicle_registry (alla / obehandlade)
                registry = self.plugin._vehicle_registry
                if registry is None:
                    return []
                for method_name in (
                    "get_all_vins",
                    "get_vins",
                    "list_vins",
                    "all_vins",
                ):
                    method = getattr(registry, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, dict):
                                raw = list(raw.keys())
                            vins = [
                                str(v).strip().upper()
                                for v in (raw or [])
                                if str(v).strip()
                            ]
                            break
                        except Exception:
                            continue
            else:
                # Från fil (VIN-lista)
                filepath, _ = QFileDialog.getOpenFileName(
                    self,
                    "Välj VIN-lista",
                    "",
                    "Textfiler (*.txt *.csv);;Alla filer (*.*)",
                )
                if not filepath:
                    return []
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    vins = [
                        v.strip().upper()
                        for v in content.replace(",", "\n").splitlines()
                        if v.strip()
                    ]
                except Exception as exc:
                    QMessageBox.critical(
                        self,
                        "Fel",
                        "Kunde inte läsa VIN-listan: %s" % exc,
                    )
                    return []

            # Begränsa + deduplicera (ordning bevaras)
            seen = set()
            unique: List[str] = []
            for v in vins:
                if v not in seen:
                    seen.add(v)
                    unique.append(v)
                if len(unique) >= limit:
                    break
            return unique

        def _on_batch_start(self) -> None:
            """Starta batch-generering."""
            try:
                if (
                    self._batch_worker is not None
                    and self._batch_worker.isRunning()
                ):
                    return

                vins = self._collect_batch_vins()
                if not vins:
                    QMessageBox.warning(
                        self,
                        "Varning",
                        "Inga VIN att generera (kontrollera källan "
                        "och att vehicle_registry är aktivt)",
                    )
                    return

                output_dir = (
                    self.plugin._output_dir
                    if self.plugin._output_dir
                    else Path("ut/ereko")
                )
                worker = BatchGenerationWorker(
                    self.plugin, vins, output_dir
                )
                worker.progress.connect(self._on_batch_progress)
                worker.batch_finished.connect(self._on_batch_finished)

                self._batch_worker = worker
                self.btn_batch_start.setEnabled(False)
                self.btn_batch_stop.setEnabled(True)
                self.batch_progress.setRange(0, len(vins))
                self.batch_progress.setValue(0)
                self.batch_status.setText(
                    "Startar... (%d fordon)" % len(vins)
                )
                worker.start()

            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Fel",
                    "Kunde inte starta batch: %s" % exc,
                )

        def _on_batch_progress(
            self, current: int, total: int, message: str
        ) -> None:
            """Uppdatera progress vid batchgenerering."""
            try:
                self.batch_progress.setMaximum(max(total, 1))
                self.batch_progress.setValue(current)
                self.batch_status.setText(
                    "%s (%d/%d)" % (message, current, total)
                )
            except Exception:
                pass

        def _on_batch_finished(self, result: Dict[str, Any]) -> None:
            """Hantera batch-slutförande."""
            try:
                self.btn_batch_start.setEnabled(True)
                self.btn_batch_stop.setEnabled(False)
                self._batch_worker = None

                total = result.get("total", 0)
                success = result.get("success", 0)
                failed = result.get("failed", 0)

                msg = "📦 Batch klar!\n\n"
                msg += "Totalt: %d\n" % total
                msg += "Lyckade: %d\n" % success
                msg += "Misslyckade: %d\n" % failed

                errors = result.get("errors", [])
                if errors:
                    msg += "\nFel:\n" + "\n".join(
                        "• %s" % e for e in errors[:10]
                    )
                    if len(errors) > 10:
                        msg += "\n… (%d fler)" % (len(errors) - 10)

                self.batch_status.setText(
                    "Klar: %d lyckade, %d misslyckade"
                    % (success, failed)
                )
                QMessageBox.information(self, "Batch klar", msg)
                self._refresh_log()

            except Exception as exc:
                _log.error(
                    "Kunde inte hantera batch-resultat: %s", exc
                )

        def _on_batch_stop(self) -> None:
            """Stoppa batch-generering (requestInterruption)."""
            if (
                self._batch_worker is not None
                and self._batch_worker.isRunning()
            ):
                self._batch_worker.requestInterruption()
                self.btn_batch_stop.setEnabled(False)
                self.batch_status.setText("Stoppar...")

        def _on_browse_validate(self) -> None:
            """Bläddra efter IVI-fil."""
            filepath, _ = QFileDialog.getOpenFileName(
                self,
                "Välj IVI-fil",
                str(self.plugin._output_dir)
                if self.plugin._output_dir
                else "",
                "XML-filer (*.xml)",
            )

            if filepath:
                self.validate_file_input.setText(filepath)

        def _on_validate(self) -> None:
            """Validera IVI-fil."""
            filepath = self.validate_file_input.text().strip()
            if not filepath:
                QMessageBox.warning(
                    self, "Varning", "Välj en fil först"
                )
                return

            try:
                result = self.plugin.validate_ivi_file(Path(filepath))

                lines = ["<h3>Valideringsresultat</h3>"]
                lines.append(
                    "<p><b>Fil:</b> %s</p>" % filepath
                )

                if result["is_valid"]:
                    lines.append(
                        "<p style='color: %s;'><b>✅ Giltigt "
                        "IVI-dokument</b></p>" % _W_SUCCESS
                    )
                else:
                    lines.append(
                        "<p style='color: %s;'><b>❌ Ogiltigt "
                        "IVI-dokument</b></p>" % _W_DANGER
                    )

                if result.get("errors"):
                    lines.append("<h4>Fel:</h4><ul>")
                    for error in result["errors"]:
                        lines.append("<li>%s</li>" % error)
                    lines.append("</ul>")

                if result.get("warnings"):
                    lines.append("<h4>Varningar:</h4><ul>")
                    for warning in result["warnings"]:
                        lines.append("<li>%s</li>" % warning)
                    lines.append("</ul>")

                self.validate_results.setHtml("\n".join(lines))

            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Fel",
                    "Validering misslyckades: %s" % exc,
                )

        def _refresh_log(self) -> None:
            """Uppdatera logg-tabell."""
            try:
                vin_filter = (
                    self.log_vin_filter.text().strip().upper()
                    or None
                )
                entries = self.plugin.get_generation_log(
                    vin=vin_filter, limit=100
                )

                self.log_table.setRowCount(len(entries))

                for row, entry in enumerate(entries):
                    # Tidpunkt (utan mikrosekunder)
                    timestamp = entry.get("timestamp", "")[:19]
                    self.log_table.setItem(
                        row, 0, QTableWidgetItem(timestamp)
                    )

                    # VIN
                    self.log_table.setItem(
                        row, 1, QTableWidgetItem(entry.get("vin", ""))
                    )

                    # Dokument-ID
                    self.log_table.setItem(
                        row,
                        2,
                        QTableWidgetItem(
                            entry.get("document_id", "")
                        ),
                    )

                    # Status
                    status = entry.get("status", "")
                    status_item = QTableWidgetItem(status)
                    if status == "valid":
                        status_item.setForeground(
                            Qt.GlobalColor.green
                        )
                    elif status == "invalid":
                        status_item.setForeground(
                            Qt.GlobalColor.red
                        )
                    self.log_table.setItem(row, 3, status_item)

                    # Fil
                    output_path = entry.get("output_path", "")
                    if output_path:
                        filename = Path(output_path).name
                        self.log_table.setItem(
                            row, 4, QTableWidgetItem(filename)
                        )

                # Uppdatera statistik
                stats = self.plugin.get_statistics().get(
                    "generation_log", {}
                )
                self.stat_total.setText(str(stats.get("total", 0)))
                self.stat_valid.setText(str(stats.get("valid", 0)))
                self.stat_invalid.setText(
                    str(stats.get("invalid", 0))
                )
                self.stat_success_rate.setText(
                    "%.1f%%" % stats.get("success_rate", 0)
                )

            except Exception as exc:
                _log.error("Kunde inte uppdatera logg: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Constants
    "VERSION",
    "AUTHOR",
    "IVI_OUTPUT_DIR",
    "IVI_BACKUP_DIR",
    "IVI_LOG_FILE",
    "HAS_PYSIDE6",
    # Copyright
    "get_copyright_year",
    "get_copyright_string",
    # Helpers
    "get_plugin_safe",
    "emit_event_safe",
    "safe_get",
    # Classes
    "GenerationLog",
    "Plugin",
]

# Klasserna finns bara när PySide6 är tillgängligt (import *
# kraschar annars på saknade namn).
if HAS_PYSIDE6:
    __all__ += [
        "BatchGenerationWorker",
        "EReKoWidget",
    ]
