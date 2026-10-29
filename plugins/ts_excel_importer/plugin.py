# -*- coding: utf-8 -*-
# Fil: plugins/ts_excel_importer/plugin.py
"""
TS Excel Importer Plugin v2.0.1

Importerar TS-specifikationer från Excel-filer.
Samarbetar med ts_schema_manager och ts_spec_import.

FÖRÄNDRINGAR v2.0.1 (granskad — spec v1.6 förbättringsregeln):
    - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2025 ..." i
      docstringen BORTTAGEN — copyright genereras dynamiskt via
      get_copyright_string().
    - FIX (låst regel): logger/self._local_logger ->
      module-level _log; ALLA f-string-logganrop ersatta med lazy %s.
    - FIX (widget-integration, KRITISK): widget.py v1.0.0 anropar
      self.plugin.get_plugin_safe("ts_schema_manager") som METOD —
      metoden fanns inte på Plugin → AttributeError. Nu:
      Plugin.get_plugin_safe(name) delegerar till modul-funktionen.
    - FIX (korrekthet, DATA-FÖRLUST): preview_import(),
      auto_detect_post_types(), compare_with_existing() och
      validate_excel_file() läste getattr(sheet, 'post_type') men
      parser.SheetInfo exponerar detected_post_type →
      posttyper rapporterades alltid som tomma. Nu:
      detected_post_type ELLER post_type (bakåtkompatibel).
    - FIX (låst regel, atomer): _save_history() skrev med öppen
      write() — korrupt historik vid krasch. Nu mkstemp → fsync →
      os.replace.
    - FIX (PluginBase v3.x kontrakt): init()/shutdown()/
      register_ui()/config_schema() tillagda; initialize()/
      activate()/deactivate() BEHÅLLNA som legacy-kompatibilitet med
      äldre loaders (init() → initialize(), shutdown() →
      deactivate()).
    - FIX (kraschsäkerhet): PySide6-importen flyttad till
      create_widget() (local import) — pluginen kan laddas/initieras
      även utan GUI (headless/test); oanvända Qt-imports borttagna.
    - create_widget(parent=None) + fallback-widget med setObjectName.
    - emit_event_safe(): data=None → data or {} (default).
    - Header normaliserad (coding före Fil — spec v1.11 KRAV 58).
    - Övrig logik OFÖRÄNDRAD (20 publika funktioner, dataclasses,
      lazy parser, samarbete, historik).

FUNKTIONER (1-10): CORE IMPORT
    1. analyze_file() - Analysera Excel-fil
    2. parse_sheet() - Parsa ett ark
    3. import_file() - Importera komplett fil
    4. get_column_mapping() - Auto-detektera kolumner
    5. generate_next_version() - Generera versionsnamn
    6. validate_excel_file() - Validera fil innan import
    7. preview_import() - Förhandsgranska import
    8. get_import_statistics() - Importstatistik
    9. export_to_excel() - Exportera scheman till Excel
    10. compare_with_existing() - Jämför med befintliga

FUNKTIONER (11-20): ADVANCED
    11. auto_detect_post_types() - Auto-detektera posttyper
    12. batch_import() - Importera flera filer
    13. get_field_coverage_preview() - Förhandsgranska täckning
    14. validate_column_mapping() - Validera mappning
    15. get_import_history() - Importhistorik
    16. get_supported_formats() - Lista stödda format
    17. repair_column_mapping() - Reparera mappning
    18. get_sheet_preview() - Förhandsgranska ark
    19. sync_with_schema_manager() - Synka med ts_schema_manager
    20. get_diagnostics() - Diagnostikinformation

SAMARBETE:
    - ts_schema_manager: Sparar importerade scheman
    - ts_spec_import: Alternativ schema-källa
    - data_viewer: Visar importresultat

Användning:
    importer = app.get_plugin("ts_excel_importer")
    sheets = importer.analyze_file(Path("spec.xlsx"))
    result = importer.import_file(filepath, sheets_config, version)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from core.plugin_base import PluginBase

if TYPE_CHECKING:
    from plugins.ts_schema_manager.models import PostSpec, FieldSpec


# ══════════════════════════════════════════════════════════════════════════════
# COPYRIGHT & VERSION
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "2.0.1"
AUTHOR: str = "Rickard Längkvist"
TS_POST_LENGTH: int = 2500


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


def _get_logger() -> logging.Logger:
    """Hämta logger. KRASCHSÄKER."""
    try:
        return logging.getLogger("ts_excel_importer")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log = _get_logger()


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """Hämta plugin säkert. KRASCHSÄKER."""
    if app is None:
        return None

    methods = [
        lambda: app.get_plugin(name) if hasattr(app, 'get_plugin') else None,
        lambda: app.plugin_loader.get_plugin(name) if hasattr(app, 'plugin_loader') else None,
        lambda: getattr(app, name.replace("-", "_"), None),
    ]

    for method in methods:
        try:
            result = method()
            if result is not None:
                return result
        except Exception:
            pass

    return None


def emit_event_safe(app: Any, event_name: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Emittera event säkert. KRASCHSÄKER."""
    try:
        if hasattr(app, 'event_bus') and hasattr(app.event_bus, 'emit'):
            app.event_bus.emit(event_name, data or {})
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

class SyncAction(str, Enum):
    """Synkroniseringsåtgärder."""
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class SyncResult:
    """Resultat från synkronisering av en specifikation."""
    post_type: str
    action: SyncAction
    changes: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def is_success(self) -> bool:
        return self.action != SyncAction.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            "post_type": self.post_type,
            "action": self.action.value,
            "changes": self.changes,
            "error": self.error,
            "is_success": self.is_success,
        }


@dataclass
class ImportResult:
    """Totalt resultat från en import."""
    source_file: str
    version: str = ""
    sheets_found: int = 0
    specs_imported: int = 0
    specs_updated: int = 0
    specs_unchanged: int = 0
    specs_failed: int = 0
    sync_results: List[SyncResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def is_success(self) -> bool:
        return self.specs_failed == 0 and (
            self.specs_imported > 0 or self.specs_updated > 0
        )

    @property
    def total_processed(self) -> int:
        return self.specs_imported + self.specs_updated + self.specs_unchanged + self.specs_failed

    def summary(self) -> str:
        parts = []
        if self.specs_imported:
            parts.append(f"{self.specs_imported} nya")
        if self.specs_updated:
            parts.append(f"{self.specs_updated} uppdaterade")
        if self.specs_unchanged:
            parts.append(f"{self.specs_unchanged} oförändrade")
        if self.specs_failed:
            parts.append(f"{self.specs_failed} misslyckade")
        return ", ".join(parts) or "Inga ändringar"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_file": self.source_file,
            "version": self.version,
            "sheets_found": self.sheets_found,
            "specs_imported": self.specs_imported,
            "specs_updated": self.specs_updated,
            "specs_unchanged": self.specs_unchanged,
            "specs_failed": self.specs_failed,
            "sync_results": [r.to_dict() for r in self.sync_results],
            "warnings": self.warnings,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
            "is_success": self.is_success,
            "summary": self.summary(),
        }


@dataclass
class ImportPreview:
    """Förhandsvisning av import."""
    filepath: str
    sheets: List[Dict[str, Any]]
    estimated_fields: int = 0
    estimated_post_types: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════════════
# LAZY IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

_parser_loaded = False
_TSExcelParser = None
_SheetInfo = None
_ParsedSpec = None
_ParsedField = None


def _ensure_parser():
    """Lazy-load parser för att undvika cirkulär import. KRASCHSÄKER."""
    global _parser_loaded, _TSExcelParser, _SheetInfo, _ParsedSpec, _ParsedField

    if _parser_loaded:
        return True

    try:
        from .parser import TSExcelParser, SheetInfo, ParsedSpec, ParsedField
        _TSExcelParser = TSExcelParser
        _SheetInfo = SheetInfo
        _ParsedSpec = ParsedSpec
        _ParsedField = ParsedField
        _parser_loaded = True
        return True
    except ImportError as e:
        _log.warning("Kunde inte importera parser: %s", e)
        return False


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    TS Excel Importer v2.0.1

    Importerar TS-specifikationer från Excel-filer.
    Samarbetar med ts_schema_manager och ts_spec_import.

    20 publika funktioner för komplett Excel-import.

    FIXAT I v2.0.1 (granskad):
    - _log module-level (ingen self.logger / _local_logger)
    - init/shutdown/register_ui/config_schema (PluginBase v3.x)
    - Plugin.get_plugin_safe() (widget v1.0.0-integration)
    - detected_post_type-fixar (preview/compare/auto_detect)
    - Atomisk historik-skrivning
    - PySide6 local import (headless-safe)
    - Lazy %s-loggning

    FIXAT I v2.0.0:
    - Använder _local_logger istället för self.logger
    - Ingen setter på PluginBase.logger
    - 10 nya funktioner (11-20)
    - Bättre samarbete med ts_schema_manager och ts_spec_import
    - Förbättrad kraschsäkerhet
    - Import-historik
    """

    NAME = "TS Excel Importer"
    VERSION = VERSION
    DESCRIPTION = "Importera TS-specifikationer från Excel (20 funktioner)"
    AUTHOR = AUTHOR
    DEPENDENCIES = []
    OPTIONAL_DEPENDENCIES = ["ts_schema_manager", "ts_spec_import"]

    def __init__(self, app):
        super().__init__(app)

        self._parser: Optional[Any] = None
        self._widget: Optional[Any] = None
        self._initialized: bool = False
        self._import_history: List[Dict[str, Any]] = []
        self._schema_manager: Optional[Any] = None
        self._ts_spec_import: Optional[Any] = None
        self._history_file: Optional[Path] = None

    @property
    def copyright(self) -> str:
        """Dynamisk copyright-sträng."""
        return get_copyright_string()

    def get_plugin_safe(self, name: str) -> Optional[Any]:
        """
        Hämta plugin säkert (delegerar till modul-funktionen).

        Krävs av widget.py v1.0.0 som anropar self.plugin.get_plugin_safe(...).

        Args:
            name: Pluginnamn

        Returns:
            Plugin-instans eller None
        """
        return get_plugin_safe(self.app, name)

    # ═══════════════════════════════════════════════════════════════════════════
    # LIFECYCLE (PluginBase v3.x-kontrakt + legacy-alias)
    # ═══════════════════════════════════════════════════════════════════════════

    def init(self) -> None:
        """Initiera plugin (PluginBase v3.x kontrakt). KRASCHSÄKER."""
        self.initialize()

    def shutdown(self) -> None:
        """Stäng ner (PluginBase v3.x kontrakt). KRASCHSÄKER."""
        self.deactivate()

    def register_ui(self, parent: Any) -> Any:
        """Registrera UI-widget (PluginBase v3.x kontrakt). KRASCHSÄKER."""
        return self.create_widget(parent)

    def config_schema(self) -> Dict[str, Any]:
        """Returnera konfig-schema (PluginBase v3.x kontrakt)."""
        return {
            "plugin": self.NAME,
            "version": VERSION,
            "author": AUTHOR,
            "copyright": get_copyright_string(),
            "settings": {
                "history_limit": 100,
                "supported_extensions": [".xlsx", ".xls", ".xlsm"],
            },
        }

    def initialize(self) -> None:
        """Initiera plugin. KRASCHSÄKER. (legacy-alias för äldre loaders)"""
        try:
            # Lazy-load parser
            if _ensure_parser() and _TSExcelParser:
                self._parser = _TSExcelParser()

            # Sätt upp history-fil
            base_path = getattr(self.app, 'base_path', Path.cwd())
            if isinstance(base_path, str):
                base_path = Path(base_path)

            data_dir = base_path / "data" / "ts_excel_importer"
            data_dir.mkdir(parents=True, exist_ok=True)
            self._history_file = data_dir / "import_history.json"

            # Ladda historik
            self._load_history()

            # Registrera i app
            try:
                self.app.ts_excel_importer = self
            except Exception:
                pass

            self._initialized = True

            _log.info(
                "TS Excel Importer v%s initierad",
                VERSION,
            )
            _log.info("  %s", self.copyright)
            _log.info("  20 publika funktioner tillgängliga")
            _log.info(
                "  Parser: %s",
                "laddad" if self._parser else "ej tillgänglig",
            )

            # Detektera samarbetspartners
            self._detect_collaborators()

        except Exception as e:
            _log.error("Initiering misslyckades: %s", e, exc_info=True)
            self._initialized = False

    def _detect_collaborators(self) -> None:
        """Detektera samarbetspartners. KRASCHSÄKER."""
        try:
            self._schema_manager = get_plugin_safe(self.app, "ts_schema_manager")
            if self._schema_manager:
                _log.debug("ts_schema_manager detekterad")

            self._ts_spec_import = get_plugin_safe(self.app, "ts_spec_import")
            if self._ts_spec_import:
                _log.debug("ts_spec_import detekterad")
        except Exception:
            pass

    def _load_history(self) -> None:
        """Ladda importhistorik. KRASCHSÄKER."""
        try:
            if self._history_file and self._history_file.exists():
                with open(self._history_file, 'r', encoding='utf-8') as f:
                    self._import_history = json.load(f)
        except Exception as e:
            _log.warning("Kunde inte ladda historik: %s", e)
            self._import_history = []

    def _save_history(self) -> None:
        """Spara importhistorik ATOMISKT. KRASCHSÄKER."""
        try:
            if self._history_file:
                self._history_file.parent.mkdir(parents=True, exist_ok=True)

                # Begränsa historik till 100 poster
                history_to_save = self._import_history[-100:]

                fd, tmp_path = tempfile.mkstemp(
                    dir=str(self._history_file.parent),
                    prefix=".history_",
                    suffix=".tmp",
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(history_to_save, f, indent=2, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, str(self._history_file))
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
        except Exception as e:
            _log.warning("Kunde inte spara historik: %s", e)

    def activate(self) -> None:
        """Aktivera plugin. KRASCHSÄKER. (legacy)"""
        try:
            self.is_active = True
            self._detect_collaborators()
            emit_event_safe(self.app, "ts_excel_importer:activated", {})
        except Exception as e:
            _log.error("Aktivering misslyckades: %s", e)

    def deactivate(self) -> None:
        """Deaktivera plugin. KRASCHSÄKER. (legacy)"""
        try:
            self._save_history()
            self._widget = None
            self.is_active = False
        except Exception as e:
            _log.error("Deaktivering misslyckades: %s", e)

    def create_widget(self, parent: Any = None) -> Any:
        """
        Skapa import-widget. KRASCHSÄKER.

        PySide6 importeras lokalt — pluginen fungerar utan GUI.

        Args:
            parent: Förälder-widget (valfri)

        Returns:
            TSExcelImportWidget eller fallback/None
        """
        try:
            from .widget import TSExcelImportWidget
            self._widget = TSExcelImportWidget(parent, self)
            return self._widget
        except Exception as e:
            _log.error("Kunde inte skapa widget: %s", e)
            try:
                from PySide6.QtWidgets import (
                    QWidget, QVBoxLayout, QLabel,
                )
                fallback = QWidget(parent)
                fallback.setObjectName("TSExcelImportFallback")
                layout = QVBoxLayout(fallback)
                layout.addWidget(QLabel(f"❌ Widget-creation misslyckades: {e}"))
                return fallback
            except Exception:
                return None

    def _get_schema_manager(self) -> Optional[Any]:
        """Hämta schema manager. KRASCHSÄKER."""
        if self._schema_manager:
            return self._schema_manager

        self._schema_manager = get_plugin_safe(self.app, "ts_schema_manager")
        return self._schema_manager

    def _get_ts_spec_import(self) -> Optional[Any]:
        """Hämta ts_spec_import. KRASCHSÄKER."""
        if self._ts_spec_import:
            return self._ts_spec_import

        self._ts_spec_import = get_plugin_safe(self.app, "ts_spec_import")
        return self._ts_spec_import

    # ═══════════════════════════════════════════════════════════════════════════
    # FUNCTIONS 1-10: CORE IMPORT
    # ═══════════════════════════════════════════════════════════════════════════

    def analyze_file(self, filepath: Path) -> List[Any]:
        """
        1. Analysera Excel-fil för att hitta postspecifikationer. KRASCHSÄKER.

        Args:
            filepath: Sökväg till Excel-fil

        Returns:
            Lista med SheetInfo-objekt
        """
        if not self._parser:
            if not _ensure_parser() or not _TSExcelParser:
                _log.error("Parser ej tillgänglig")
                return []
            self._parser = _TSExcelParser()

        try:
            return self._parser.get_sheet_info(filepath)
        except Exception as e:
            _log.error("Kunde inte analysera fil: %s", e)
            return []

    def parse_sheet(self, filepath: Path, sheet_name: str, **kwargs) -> Optional[Any]:
        """
        2. Parsa ett Excel-ark. KRASCHSÄKER.

        Args:
            filepath: Sökväg till Excel-fil
            sheet_name: Namn på ark
            **kwargs: Extra parametrar

        Returns:
            ParsedSpec eller None
        """
        if not self._parser:
            if not _ensure_parser() or not _TSExcelParser:
                return None
            self._parser = _TSExcelParser()

        try:
            return self._parser.parse_sheet(filepath, sheet_name, **kwargs)
        except Exception as e:
            _log.error("Kunde inte parsaa ark: %s", e)
            return None

    def import_file(
        self,
        filepath: Path,
        sheets_config: List[Dict[str, Any]],
        version: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> ImportResult:
        """
        3. Importera specifikationer från Excel-fil. KRASCHSÄKER.

        Args:
            filepath: Sökväg till Excel-fil
            sheets_config: Konfiguration per ark
            version: Versionsnamn
            progress_callback: Callback(current, total, message)

        Returns:
            ImportResult med detaljer
        """
        start_time = time.perf_counter()
        result = ImportResult(source_file=str(filepath.name), version=version)
        result.sheets_found = len(sheets_config)

        try:
            # Hämta schema manager
            schema_mgr = self._get_schema_manager()

            if not self._parser:
                if not _ensure_parser() or not _TSExcelParser:
                    result.warnings.append("Parser ej tillgänglig")
                    return result
                self._parser = _TSExcelParser()

            # Importera datamodeller
            try:
                from plugins.ts_schema_manager.models import PostSpec, FieldSpec
            except ImportError:
                # Fallback: försök från ts_spec_import
                try:
                    from plugins.ts_spec_import.models import PostSpec, FieldSpec
                except ImportError:
                    result.warnings.append("Kunde inte importera schema-modeller")
                    return result

            parsed_specs: List[Any] = []

            for i, config in enumerate(sheets_config):
                if progress_callback:
                    try:
                        progress_callback(i + 1, len(sheets_config), config.get("sheet_name", ""))
                    except Exception:
                        pass

                try:
                    # Parsa
                    parsed = self._parser.parse_sheet(
                        filepath=filepath,
                        sheet_name=config["sheet_name"],
                        column_mapping=config.get("column_mapping"),
                        post_type=config.get("post_type"),
                        post_name=config.get("post_name"),
                        total_length=config.get("total_length", TS_POST_LENGTH)
                    )

                    if hasattr(parsed, 'parse_warnings'):
                        result.warnings.extend(parsed.parse_warnings)

                    if parsed and hasattr(parsed, 'is_valid') and parsed.is_valid:
                        # Konvertera ParsedField -> FieldSpec
                        fields = []
                        for f in parsed.fields:
                            try:
                                field_spec = FieldSpec(
                                    name=f.name,
                                    position=f.position,
                                    length=f.length,
                                    field_type=getattr(f, 'field_type', 'alphanumeric'),
                                    mandatory=getattr(f, 'required', True),
                                    description=getattr(f, 'description', ''),
                                    valid_values=getattr(f, 'valid_values', []),
                                    default=getattr(f, 'default', ''),
                                    source_mapping=getattr(f, 'source_mapping', ''),
                                )
                                fields.append(field_spec)
                            except Exception as fe:
                                _log.warning("Kunde inte konvertera fält: %s", fe)

                        post_spec = PostSpec(
                            post_type=parsed.post_type,
                            name=getattr(parsed, 'post_name', f"Posttyp {parsed.post_type}"),
                            total_length=getattr(parsed, 'total_length', TS_POST_LENGTH),
                            fields=fields,
                            source_file=str(filepath.name),
                        )

                        parsed_specs.append(post_spec)

                        # Bestäm action
                        action = SyncAction.CREATED
                        if schema_mgr:
                            try:
                                existing = schema_mgr.get_schema(
                                    parsed.post_type,
                                    schema_mgr.get_active_version()
                                )

                                if existing is None:
                                    result.specs_imported += 1
                                    action = SyncAction.CREATED
                                elif hasattr(existing, 'checksum') and hasattr(post_spec, 'checksum'):
                                    if existing.checksum != post_spec.checksum:
                                        result.specs_updated += 1
                                        action = SyncAction.UPDATED
                                    else:
                                        result.specs_unchanged += 1
                                        action = SyncAction.UNCHANGED
                                else:
                                    result.specs_updated += 1
                                    action = SyncAction.UPDATED
                            except Exception:
                                result.specs_imported += 1
                        else:
                            result.specs_imported += 1

                        result.sync_results.append(SyncResult(
                            post_type=parsed.post_type,
                            action=action,
                            changes=[f"{len(fields)} fält"]
                        ))
                    else:
                        result.specs_failed += 1
                        result.sync_results.append(SyncResult(
                            post_type=config.get("post_type", "?"),
                            action=SyncAction.ERROR,
                            error="Kunde inte parsaa specifikation"
                        ))

                except Exception as e:
                    _log.exception("Kunde inte importera ark")
                    result.specs_failed += 1
                    result.sync_results.append(SyncResult(
                        post_type=config.get("post_type", "?"),
                        action=SyncAction.ERROR,
                        error=str(e)
                    ))

            # Spara version via schema manager
            if parsed_specs and schema_mgr:
                try:
                    schema_mgr.create_version(
                        version=version,
                        specs=parsed_specs,
                        source_file=str(filepath.name),
                        description=f"Importerad {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        set_active=True
                    )
                except Exception as e:
                    result.warnings.append(f"Kunde inte spara version: {e}")

                    # Försök via ts_spec_import som fallback
                    ts_spec = self._get_ts_spec_import()
                    if ts_spec and hasattr(ts_spec, 'create_version'):
                        try:
                            ts_spec.create_version(
                                version=version,
                                specs=parsed_specs,
                                source_file=str(filepath.name),
                                set_active=True
                            )
                            result.warnings.append("Sparad via ts_spec_import istället")
                        except Exception as e2:
                            result.warnings.append(f"Fallback också misslyckades: {e2}")

            result.duration_ms = (time.perf_counter() - start_time) * 1000

            # Emit event
            emit_event_safe(self.app, "schema:loaded", {
                "source": "ts_excel_importer",
                "version": version,
                "post_types": [s.post_type for s in parsed_specs],
                "result": result.summary()
            })

            emit_event_safe(self.app, "ts_spec:imported", {
                "version": version,
                "post_types": [s.post_type for s in parsed_specs],
            })

            # Spara i historik
            self._import_history.append(result.to_dict())
            self._save_history()

        except Exception as e:
            _log.error("Import misslyckades: %s", e, exc_info=True)
            result.warnings.append(f"Import misslyckades: {e}")

        return result

    def get_column_mapping(self, columns: List[str]) -> Dict[str, str]:
        """
        4. Auto-detektera kolumnmappning. KRASCHSÄKER.

        Args:
            columns: Lista med kolumnnamn

        Returns:
            Dict med mappning
        """
        if not self._parser:
            if not _ensure_parser() or not _TSExcelParser:
                return {}
            self._parser = _TSExcelParser()

        try:
            if hasattr(self._parser, '_auto_detect_columns'):
                return self._parser._auto_detect_columns(columns)
            return {}
        except Exception:
            return {}

    def generate_next_version(self) -> str:
        """
        5. Generera nästa versionsnamn. KRASCHSÄKER.

        Returns:
            Versionsnamn (YYYY.MM.DD_N)
        """
        try:
            base = datetime.now().strftime("%Y.%m.%d")

            existing = []

            # Försök hämta befintliga versioner
            schema_mgr = self._get_schema_manager()
            if schema_mgr:
                try:
                    versions = schema_mgr.list_versions()
                    existing = [v.version if hasattr(v, 'version') else str(v) for v in versions]
                except Exception:
                    pass

            # Fallback: ts_spec_import
            if not existing:
                ts_spec = self._get_ts_spec_import()
                if ts_spec:
                    try:
                        versions = ts_spec.list_versions()
                        existing = [v.version if hasattr(v, 'version') else str(v) for v in versions]
                    except Exception:
                        pass

            counter = 1
            while True:
                candidate = f"{base}_{counter}"
                if candidate not in existing:
                    return candidate
                counter += 1
                if counter > 99:
                    return f"{base}_{datetime.now().strftime('%H%M%S')}"

        except Exception:
            return datetime.now().strftime("%Y%m%d_%H%M%S")

    def validate_excel_file(self, filepath: Path) -> Dict[str, Any]:
        """
        6. Validera Excel-fil innan import. KRASCHSÄKER.

        Args:
            filepath: Sökväg till fil

        Returns:
            Dict med valideringsresultat
        """
        result = {
            "valid": False,
            "filepath": str(filepath),
            "exists": False,
            "readable": False,
            "sheets": [],
            "errors": [],
            "warnings": [],
        }

        try:
            # Kontrollera existens
            filepath = Path(filepath)
            result["exists"] = filepath.exists()

            if not result["exists"]:
                result["errors"].append(f"Filen finns inte: {filepath}")
                return result

            # Kontrollera filtyp
            if filepath.suffix.lower() not in ['.xlsx', '.xls', '.xlsm']:
                result["errors"].append(f"Ogiltig filtyp: {filepath.suffix}")
                return result

            # Försök läsa
            try:
                import openpyxl
                wb = openpyxl.load_workbook(filepath, read_only=True)
                result["sheets"] = wb.sheetnames
                result["readable"] = True
                wb.close()
            except Exception as e:
                result["errors"].append(f"Kunde inte läsa fil: {e}")
                return result

            # Analysera ark
            if self._parser or _ensure_parser():
                if not self._parser and _TSExcelParser:
                    self._parser = _TSExcelParser()

                if self._parser:
                    try:
                        sheet_info = self._parser.get_sheet_info(filepath)
                        for info in sheet_info:
                            pt = (
                                getattr(info, 'detected_post_type', None)
                                or getattr(info, 'post_type', None)
                            )
                            if not pt:
                                result["warnings"].append(
                                    f"Ark '{getattr(info, 'name', '?')}' "
                                    f"saknar tydlig posttyp"
                                )
                    except Exception as e:
                        result["warnings"].append(f"Kunde inte analysera ark: {e}")

            result["valid"] = len(result["errors"]) == 0

        except Exception as e:
            result["errors"].append(str(e))

        return result

    def preview_import(self, filepath: Path) -> ImportPreview:
        """
        7. Förhandsgranska import utan att faktiskt importera. KRASCHSÄKER.

        Args:
            filepath: Sökväg till fil

        Returns:
            ImportPreview med detaljer
        """
        preview = ImportPreview(
            filepath=str(filepath),
            sheets=[],
            valid=False
        )

        try:
            # Validera först
            validation = self.validate_excel_file(filepath)
            preview.warnings = validation.get("warnings", [])

            if not validation.get("valid"):
                preview.warnings.extend(validation.get("errors", []))
                return preview

            # Analysera ark
            sheets = self.analyze_file(Path(filepath))

            total_fields = 0
            post_types = []

            for sheet in sheets:
                sheet_info = {
                    "name": getattr(sheet, 'name', str(sheet)),
                    "post_type": (
                        getattr(sheet, 'detected_post_type', None)
                        or getattr(sheet, 'post_type', None)
                    ),
                    "row_count": getattr(sheet, 'row_count', 0),
                    "has_data": getattr(sheet, 'has_data', False),
                }
                preview.sheets.append(sheet_info)

                if sheet_info["post_type"]:
                    post_types.append(sheet_info["post_type"])

                # Parsa för att räkna fält
                try:
                    parsed = self.parse_sheet(Path(filepath), sheet_info["name"])
                    if parsed and hasattr(parsed, 'fields'):
                        total_fields += len(parsed.fields)
                        sheet_info["field_count"] = len(parsed.fields)
                except Exception:
                    pass

            preview.estimated_fields = total_fields
            preview.estimated_post_types = post_types
            preview.valid = True

        except Exception as e:
            preview.warnings.append(str(e))

        return preview

    def get_import_statistics(self) -> Dict[str, Any]:
        """
        8. Hämta statistik om imports. KRASCHSÄKER.

        Returns:
            Dict med statistik
        """
        stats = {
            "total_imports": 0,
            "successful_imports": 0,
            "failed_imports": 0,
            "total_schemas_imported": 0,
            "total_schemas_updated": 0,
            "last_import": None,
            "imports_by_month": {},
            "top_source_files": [],
        }

        try:
            stats["total_imports"] = len(self._import_history)

            file_counts = {}

            for imp in self._import_history:
                if imp.get("is_success"):
                    stats["successful_imports"] += 1
                else:
                    stats["failed_imports"] += 1

                stats["total_schemas_imported"] += imp.get("specs_imported", 0)
                stats["total_schemas_updated"] += imp.get("specs_updated", 0)

                # Per månad
                timestamp = imp.get("timestamp", "")
                if timestamp:
                    month = timestamp[:7]  # YYYY-MM
                    stats["imports_by_month"][month] = stats["imports_by_month"].get(month, 0) + 1

                # Per fil
                source = imp.get("source_file", "")
                if source:
                    file_counts[source] = file_counts.get(source, 0) + 1

            # Senaste import
            if self._import_history:
                stats["last_import"] = self._import_history[-1]

            # Top filer
            stats["top_source_files"] = sorted(
                [{"file": f, "count": c} for f, c in file_counts.items()],
                key=lambda x: x["count"],
                reverse=True
            )[:5]

        except Exception as e:
            stats["error"] = str(e)

        return stats

    def export_to_excel(self, output_path: Path, version: Optional[str] = None) -> Dict[str, Any]:
        """
        9. Exportera scheman till Excel. KRASCHSÄKER.

        Args:
            output_path: Sökväg för output
            version: Version att exportera

        Returns:
            Dict med exportresultat
        """
        result = {
            "success": False,
            "filepath": str(output_path),
            "sheets_exported": 0,
            "errors": [],
        }

        try:
            import pandas as pd
        except ImportError:
            result["errors"].append("pandas krävs för Excel-export")
            return result

        try:
            # Hämta scheman
            schemas = {}

            schema_mgr = self._get_schema_manager()
            if schema_mgr:
                schemas = schema_mgr.get_all_schemas(version)

            if not schemas:
                ts_spec = self._get_ts_spec_import()
                if ts_spec:
                    schemas = ts_spec.get_all_schemas(version)

            if not schemas:
                result["errors"].append("Inga scheman att exportera")
                return result

            # Skapa Excel
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                for post_type, schema in schemas.items():
                    try:
                        # Konvertera fält till DataFrame
                        field_data = []
                        for f in schema.fields if hasattr(schema, 'fields') else []:
                            field_data.append({
                                "Fältnamn": f.name,
                                "Position": f.position,
                                "Längd": f.length,
                                "Typ": getattr(f, 'field_type', 'AN'),
                                "Obligatoriskt": "Ja" if getattr(f, 'mandatory', True) else "Nej",
                                "Beskrivning": getattr(f, 'description', ''),
                            })

                        df = pd.DataFrame(field_data)
                        df.to_excel(writer, sheet_name=f"PT{post_type}", index=False)
                        result["sheets_exported"] += 1

                    except Exception as e:
                        result["errors"].append(f"PT{post_type}: {e}")

            result["success"] = result["sheets_exported"] > 0
            _log.info(
                "Exporterade %d scheman till %s",
                result["sheets_exported"],
                output_path,
            )

        except Exception as e:
            result["errors"].append(str(e))
            _log.error("Export misslyckades: %s", e)

        return result

    def compare_with_existing(self, filepath: Path) -> Dict[str, Any]:
        """
        10. Jämför importfil med befintliga scheman. KRASCHSÄKER.

        Args:
            filepath: Sökväg till fil

        Returns:
            Dict med jämförelseresultat
        """
        result = {
            "filepath": str(filepath),
            "comparisons": [],
            "new_post_types": [],
            "updated_post_types": [],
            "unchanged_post_types": [],
            "summary": "",
        }

        try:
            # Analysera fil
            sheets = self.analyze_file(Path(filepath))

            # Hämta befintliga scheman
            existing = {}
            schema_mgr = self._get_schema_manager()
            if schema_mgr:
                existing = schema_mgr.get_all_schemas()

            if not existing:
                ts_spec = self._get_ts_spec_import()
                if ts_spec:
                    existing = ts_spec.get_all_schemas()

            for sheet in sheets:
                post_type = (
                    getattr(sheet, 'detected_post_type', None)
                    or getattr(sheet, 'post_type', None)
                )
                if not post_type:
                    continue

                comparison = {
                    "post_type": post_type,
                    "status": "new",
                    "existing_fields": 0,
                    "new_fields": 0,
                    "changes": [],
                }

                if post_type in existing:
                    existing_schema = existing[post_type]
                    comparison["existing_fields"] = len(existing_schema.fields) if hasattr(existing_schema, 'fields') else 0

                    # Parsa för jämförelse
                    try:
                        parsed = self.parse_sheet(Path(filepath), getattr(sheet, 'name', ''))
                        if parsed and hasattr(parsed, 'fields'):
                            comparison["new_fields"] = len(parsed.fields)

                            if comparison["new_fields"] != comparison["existing_fields"]:
                                comparison["status"] = "updated"
                                comparison["changes"].append(
                                    f"Antal fält: {comparison['existing_fields']} -> {comparison['new_fields']}"
                                )
                                result["updated_post_types"].append(post_type)
                            else:
                                comparison["status"] = "unchanged"
                                result["unchanged_post_types"].append(post_type)
                    except Exception:
                        comparison["status"] = "error"
                else:
                    comparison["status"] = "new"
                    result["new_post_types"].append(post_type)

                result["comparisons"].append(comparison)

            # Sammanfattning
            parts = []
            if result["new_post_types"]:
                parts.append(f"{len(result['new_post_types'])} nya")
            if result["updated_post_types"]:
                parts.append(f"{len(result['updated_post_types'])} uppdaterade")
            if result["unchanged_post_types"]:
                parts.append(f"{len(result['unchanged_post_types'])} oförändrade")

            result["summary"] = ", ".join(parts) or "Inga ändringar"

        except Exception as e:
            result["error"] = str(e)

        return result

    # ═══════════════════════════════════════════════════════════════════════════
    # FUNCTIONS 11-20: ADVANCED
    # ═══════════════════════════════════════════════════════════════════════════

    def auto_detect_post_types(self, filepath: Path) -> List[Dict[str, Any]]:
        """
        11. Auto-detektera posttyper i fil. KRASCHSÄKER.

        Args:
            filepath: Sökväg till fil

        Returns:
            Lista med detekterade posttyper
        """
        results = []

        try:
            sheets = self.analyze_file(Path(filepath))

            for sheet in sheets:
                detected = (
                    getattr(sheet, 'detected_post_type', None)
                    or getattr(sheet, 'post_type', None)
                )
                info = {
                    "sheet_name": getattr(sheet, 'name', str(sheet)),
                    "detected_post_type": detected,
                    "confidence": "high" if detected else "low",
                    "row_count": getattr(sheet, 'row_count', 0),
                    "suggestions": [],
                }

                # Lägg till förslag baserat på arknamn
                name = info["sheet_name"].upper()
                if "28" in name or "IDENT" in name:
                    info["suggestions"].append("28")
                if "45" in name or "REG" in name or "FORDON" in name:
                    info["suggestions"].append("45")
                if "99" in name or "SLUT" in name:
                    info["suggestions"].append("99")

                results.append(info)

        except Exception as e:
            results.append({"error": str(e)})

        return results

    def batch_import(
        self,
        filepaths: List[Path],
        version_prefix: str = "",
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        12. Importera flera filer. KRASCHSÄKER.

        Args:
            filepaths: Lista med filsökvägar
            version_prefix: Prefix för versioner
            progress_callback: Progress callback

        Returns:
            Dict med sammanlagt resultat
        """
        result = {
            "success": False,
            "files_processed": 0,
            "files_successful": 0,
            "files_failed": 0,
            "total_schemas": 0,
            "results": [],
            "errors": [],
        }

        try:
            for i, filepath in enumerate(filepaths):
                if progress_callback:
                    progress_callback(i + 1, len(filepaths), str(filepath.name))

                try:
                    # Generera version
                    version = f"{version_prefix}{self.generate_next_version()}" if version_prefix else self.generate_next_version()

                    # Analysera och skapa config
                    sheets = self.analyze_file(filepath)
                    sheets_config = []

                    for sheet in sheets:
                        pt = (
                            getattr(sheet, 'detected_post_type', None)
                            or getattr(sheet, 'post_type', None)
                        )
                        if pt:
                            sheets_config.append({
                                "sheet_name": getattr(sheet, 'name', ''),
                                "post_type": pt,
                            })

                    if sheets_config:
                        import_result = self.import_file(filepath, sheets_config, version)
                        result["results"].append(import_result.to_dict())
                        result["total_schemas"] += import_result.specs_imported + import_result.specs_updated

                        if import_result.is_success:
                            result["files_successful"] += 1
                        else:
                            result["files_failed"] += 1

                    result["files_processed"] += 1

                except Exception as e:
                    result["errors"].append(f"{filepath}: {e}")
                    result["files_failed"] += 1
                    result["files_processed"] += 1

            result["success"] = result["files_failed"] == 0 and result["files_successful"] > 0

        except Exception as e:
            result["errors"].append(str(e))

        return result

    def get_field_coverage_preview(self, filepath: Path, sheet_name: str) -> Dict[str, Any]:
        """
        13. Förhandsgranska fälttäckning. KRASCHSÄKER.

        Args:
            filepath: Sökväg till fil
            sheet_name: Arknamn

        Returns:
            Dict med täckningsinfo
        """
        result = {
            "sheet_name": sheet_name,
            "total_length": TS_POST_LENGTH,
            "covered_positions": 0,
            "coverage_percent": 0.0,
            "gaps": [],
            "fields": [],
        }

        try:
            parsed = self.parse_sheet(Path(filepath), sheet_name)

            if not parsed or not hasattr(parsed, 'fields'):
                return result

            result["total_length"] = getattr(parsed, 'total_length', TS_POST_LENGTH)

            covered = set()
            for f in parsed.fields:
                start = f.position
                end = f.position + f.length - 1

                for pos in range(start, end + 1):
                    covered.add(pos)

                result["fields"].append({
                    "name": f.name,
                    "start": start,
                    "end": end,
                    "length": f.length,
                })

            result["covered_positions"] = len(covered)
            result["coverage_percent"] = len(covered) / result["total_length"] * 100

            # Hitta luckor
            all_positions = set(range(1, result["total_length"] + 1))
            gaps = sorted(all_positions - covered)

            if gaps:
                # Komprimera till ranges
                ranges = []
                start = gaps[0]
                end = gaps[0]

                for pos in gaps[1:]:
                    if pos == end + 1:
                        end = pos
                    else:
                        ranges.append({"start": start, "end": end, "length": end - start + 1})
                        start = end = pos

                ranges.append({"start": start, "end": end, "length": end - start + 1})
                result["gaps"] = ranges

        except Exception as e:
            result["error"] = str(e)

        return result

    def validate_column_mapping(self, columns: List[str], mapping: Dict[str, str]) -> Dict[str, Any]:
        """
        14. Validera kolumnmappning. KRASCHSÄKER.

        Args:
            columns: Tillgängliga kolumner
            mapping: Föreslagen mappning

        Returns:
            Dict med valideringsresultat
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "unmapped_columns": [],
            "missing_required": [],
        }

        try:
            required_mappings = ["position", "length", "name"]

            # Kontrollera att alla mappade kolumner finns
            for source, target in mapping.items():
                if target not in columns:
                    result["errors"].append(f"Kolumn '{target}' finns inte")
                    result["valid"] = False

            # Kontrollera required
            mapped_targets = set(mapping.keys())
            for req in required_mappings:
                if req not in mapped_targets:
                    result["missing_required"].append(req)
                    result["valid"] = False

            # Hitta omappade kolumner
            mapped_columns = set(mapping.values())
            result["unmapped_columns"] = [c for c in columns if c not in mapped_columns]

            if result["unmapped_columns"]:
                result["warnings"].append(f"{len(result['unmapped_columns'])} kolumner är inte mappade")

        except Exception as e:
            result["errors"].append(str(e))
            result["valid"] = False

        return result

    def get_import_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        15. Hämta importhistorik. KRASCHSÄKER.

        Args:
            limit: Max antal poster

        Returns:
            Lista med historikposter
        """
        try:
            return self._import_history[-limit:]
        except Exception:
            return []

    def get_supported_formats(self) -> Dict[str, Any]:
        """
        16. Lista stödda filformat. KRASCHSÄKER.

        Returns:
            Dict med formatinfo
        """
        return {
            "supported_extensions": [".xlsx", ".xls", ".xlsm"],
            "recommended": ".xlsx",
            "required_columns": ["position", "length", "name"],
            "optional_columns": ["type", "description", "mandatory", "default"],
            "max_file_size_mb": 50,
        }

    def repair_column_mapping(self, columns: List[str]) -> Dict[str, str]:
        """
        17. Försök reparera/förbättra kolumnmappning. KRASCHSÄKER.

        Args:
            columns: Tillgängliga kolumner

        Returns:
            Förbättrad mappning
        """
        mapping = self.get_column_mapping(columns)

        # Extra försök med fuzzy matching
        try:
            required = {"position": ["pos", "start", "från", "from"],
                       "length": ["len", "längd", "size", "antal"],
                       "name": ["namn", "fält", "field", "id"]}

            for target, alternatives in required.items():
                if target not in mapping:
                    for col in columns:
                        col_lower = col.lower()
                        for alt in alternatives:
                            if alt in col_lower:
                                mapping[target] = col
                                break
                        if target in mapping:
                            break
        except Exception:
            pass

        return mapping

    def get_sheet_preview(self, filepath: Path, sheet_name: str, rows: int = 10) -> Dict[str, Any]:
        """
        18. Förhandsgranska ark. KRASCHSÄKER.

        Args:
            filepath: Sökväg till fil
            sheet_name: Arknamn
            rows: Antal rader att visa

        Returns:
            Dict med preview-data
        """
        result = {
            "sheet_name": sheet_name,
            "columns": [],
            "data": [],
            "total_rows": 0,
        }

        try:
            import pandas as pd

            df = pd.read_excel(filepath, sheet_name=sheet_name, nrows=rows + 10)

            # Hoppa över tomma rader i början
            for i, row in df.iterrows():
                if not row.isna().all():
                    df = df.iloc[i:]
                    break

            result["columns"] = list(df.columns)
            result["data"] = df.head(rows).fillna("").to_dict('records')
            result["total_rows"] = len(df)

        except Exception as e:
            result["error"] = str(e)

        return result

    def sync_with_schema_manager(self) -> Dict[str, Any]:
        """
        19. Synkronisera med ts_schema_manager. KRASCHSÄKER.

        Returns:
            Dict med synk-resultat
        """
        result = {
            "success": False,
            "schema_manager_available": False,
            "ts_spec_import_available": False,
            "synced": False,
        }

        try:
            schema_mgr = self._get_schema_manager()
            result["schema_manager_available"] = schema_mgr is not None

            ts_spec = self._get_ts_spec_import()
            result["ts_spec_import_available"] = ts_spec is not None

            if schema_mgr and ts_spec:
                # Försök synka
                if hasattr(ts_spec, 'sync_with_schema_manager'):
                    sync_result = ts_spec.sync_with_schema_manager()
                    result["synced"] = sync_result.get("success", False)

            result["success"] = True

        except Exception as e:
            result["error"] = str(e)

        return result

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        20. Hämta diagnostikinformation. KRASCHSÄKER.

        Returns:
            Dict med diagnostik
        """
        return {
            "plugin_name": self.NAME,
            "plugin_version": self.VERSION,
            "copyright": self.copyright,
            "initialized": self._initialized,
            "parser_available": self._parser is not None,
            "schema_manager_available": self._get_schema_manager() is not None,
            "ts_spec_import_available": self._get_ts_spec_import() is not None,
            "import_history_count": len(self._import_history),
            "history_file": str(self._history_file) if self._history_file else None,
            "supported_formats": self.get_supported_formats(),
            "functions_available": 20,
        }


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "Plugin",
    "ImportResult",
    "ImportPreview",
    "SyncResult",
    "SyncAction",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]
