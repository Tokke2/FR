# -*- coding: utf-8 -*-
"""
Color Import Plugin v3.0.0

Importerar färgdata från Excel-filer och integrerar med colors_manager.

Copyright © {year} Rickard Längkvist
Alla rättigheter förbehållna.

FUNKTIONER (1-12):
    1. import_from_file() - Importera från Excel-fil
    2. import_from_directory() - Batch-import från katalog
    3. export_to_pdf() - Exportera färglista till PDF
    4. analyze_file() - Analysera Excel-fil före import
    5. get_import_history() - Hämta importhistorik
    6. validate_colors() - Validera färgdata
    7. auto_detect_columns() - Auto-detektera kolumner
    8. suggest_ts_codes() - Föreslå TS-koder
    9. merge_duplicates() - Slå samman dubletter
    10. export_import_report() - Exportera importrapport
    11. get_statistics() - Importstatistik
    12. get_diagnostics() - Diagnostik
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Final, List, Optional, Set, Tuple

from PySide6.QtCore import QEventLoop, QThread, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.plugin_base import PluginBase

if TYPE_CHECKING:
    from core.application import Application
    from pandas import DataFrame


# ══════════════════════════════════════════════════════════════════════════════
# COPYRIGHT & CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "3.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"


def get_copyright_year() -> int:
    """Hämta aktuellt år."""
    return datetime.now().year


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {get_copyright_year()} {AUTHOR}"


CODE_COLUMN_PATTERNS: Final[List[str]] = [
    "se color code",
    "färgkod",
    "color code",
    "code",
    "kod",
    "fargkod",
    "colour code",
    "paint code",
    "lackkod",
    "color_code",
]

NAME_COLUMN_PATTERNS: Final[List[str]] = [
    "color",
    "färg",
    "colour",
    "färgnamn",
    "colorname",
    "paint",
    "färgbenämning",
    "color name",
    "namn",
    "name",
]

AUTO_IMPORT_PATTERNS: Final[List[str]] = [
    "färg",
    "colour",
    "color",
    "farg",
    "paint",
    "lack",
]

DEFAULT_COLOR_CODES: Final[Dict[str, str]] = {
    "svart": "SWA",
    "vit": "WIT",
    "vitt": "WIT",
    "silver": "GRA",
    "grå": "GRA",
    "grått": "GRA",
    "blå": "BLA",
    "röd": "ROT",
    "grön": "GRO",
    "gul": "GUL",
    "brun": "BRU",
    "orange": "ORA",
    "beige": "BEI",
}


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def setup_logger() -> logging.Logger:
    """Konfigurera och returnera logger. Kraschsäker."""
    try:
        log = logging.getLogger("plugins.color_import")
        if not log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S",
                )
            )
            log.addHandler(handler)
            log.setLevel(logging.INFO)
        return log
    except Exception:
        return logging.getLogger(__name__)


logger = setup_logger()


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Robust plugin-hämtning. Kraschsäker.

    Försöker i ordning:
    1. app.get_plugin(name)
    2. app.plugin_loader.get_plugin(name)
    3. app.plugin_manager.get_plugin(name)
    4. getattr(app, name)
    """
    if app is None:
        return None

    normalized = name.lower().replace(" ", "_").replace("-", "_")
    names_to_try = [name, normalized]

    for try_name in names_to_try:
        if hasattr(app, "get_plugin"):
            try:
                result = app.get_plugin(try_name)
                if result is not None:
                    return result
            except Exception:
                pass

        if hasattr(app, "plugin_loader"):
            try:
                result = app.plugin_loader.get_plugin(try_name)
                if result is not None:
                    return result
            except Exception:
                pass

        if hasattr(app, "plugin_manager"):
            try:
                result = app.plugin_manager.get_plugin(try_name)
                if result is not None:
                    return result
            except Exception:
                pass

        try:
            result = getattr(app, try_name, None)
            if result is not None:
                return result
        except Exception:
            pass

    return None


def emit_event_safe(app: Any, event_name: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """Emit event säkert. Kraschsäker."""
    try:
        bus = getattr(app, "event_bus", None) or getattr(app, "events", None)
        if bus and hasattr(bus, "emit") and callable(bus.emit):
            bus.emit(event_name, data or {})
            return True
        if bus and hasattr(bus, "publish") and callable(bus.publish):
            bus.publish(event_name, data or {})
            return True
    except Exception as exc:
        logger.debug("Event emit failed: %s: %s", event_name, exc)
    return False


def get_config_value(app: Any, key: str, default: Any = None) -> Any:
    """Hämta config-värde säkert. Kraschsäker."""
    try:
        config_plugin = get_plugin_safe(app, "core_config")
        if config_plugin is not None:
            if hasattr(config_plugin, "get_config_value") and callable(config_plugin.get_config_value):
                result = config_plugin.get_config_value(key, default)
                if result is not None:
                    return result
            if hasattr(config_plugin, "get") and callable(config_plugin.get):
                result = config_plugin.get(key)
                if result is not None:
                    return result

        cfg = getattr(app, "config", None)
        if cfg is not None:
            if hasattr(cfg, "get") and callable(cfg.get):
                return cfg.get(key, default)
            if isinstance(cfg, dict):
                return cfg.get(key, default)
    except Exception:
        pass
    return default


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Skriv JSON atomiskt."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.stem}_",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with open(fd, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            try:
                import os
                os.fsync(handle.fileno())
            except Exception:
                pass
        import os
        os.replace(tmp_path, path)
    finally:
        try:
            import os
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ImportedColor:
    """En importerad färg."""

    code: str
    name: str
    ts_code: str = ""
    source_file: str = ""
    row_number: int = 0
    status: str = ""  # new, updated, skipped, error, pending
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "code": self.code,
            "name": self.name,
            "ts_code": self.ts_code,
            "source_file": self.source_file,
            "row_number": self.row_number,
            "status": self.status,
            "error_message": self.error_message,
        }


@dataclass
class ImportResult:
    """Resultat från en import-operation."""

    success: bool = False
    source_file: str = ""
    total_rows: int = 0
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    colors: List[ImportedColor] = field(default_factory=list)
    error_message: str = ""
    duration_ms: float = 0.0

    @property
    def processed(self) -> int:
        """Antal processade."""
        return self.imported + self.updated + self.skipped + self.errors

    def summary(self) -> str:
        """Sammanfattning."""
        if not self.success:
            return f"❌ {self.error_message}"
        return (
            f"✅ {self.source_file}: {self.imported} nya, "
            f"{self.updated} uppdaterade, {self.skipped} hoppade över, "
            f"{self.errors} fel"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict."""
        return {
            "success": self.success,
            "source_file": self.source_file,
            "total_rows": self.total_rows,
            "imported": self.imported,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "colors": [c.to_dict() for c in self.colors],
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
        }


@dataclass
class BatchImportResult:
    """Resultat från batch-import."""

    files_processed: int = 0
    files_failed: int = 0
    total_imported: int = 0
    total_updated: int = 0
    total_skipped: int = 0
    total_errors: int = 0
    results: List[ImportResult] = field(default_factory=list)
    duration_ms: float = 0.0

    def add(self, result: ImportResult) -> None:
        """Lägg till resultat."""
        self.results.append(result)
        if result.success:
            self.files_processed += 1
            self.total_imported += result.imported
            self.total_updated += result.updated
            self.total_skipped += result.skipped
            self.total_errors += result.errors
        else:
            self.files_failed += 1

    def summary(self) -> str:
        """Sammanfattning."""
        return (
            f"Filer: {self.files_processed} OK, {self.files_failed} fel\n"
            f"Färger: {self.total_imported} nya, {self.total_updated} uppdaterade"
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXCEL READER
# ══════════════════════════════════════════════════════════════════════════════

class ExcelColorReader:
    """Läser färgdata från Excel-filer."""

    def __init__(self, header_scan_rows: int = 20) -> None:
        self.header_scan_rows = header_scan_rows
        self._pandas_available = self._check_pandas()

    def _check_pandas(self) -> bool:
        """Kontrollera om pandas finns."""
        try:
            import pandas  # noqa: F401
            return True
        except ImportError:
            logger.warning("pandas saknas - Excel-import är inte tillgänglig")
            return False

    @property
    def is_available(self) -> bool:
        """Om Excel-läsning är tillgänglig."""
        return self._pandas_available

    def read_file(self, filepath: Path) -> Tuple[Optional["DataFrame"], str]:
        """Läs Excel-fil."""
        if not self._pandas_available:
            return None, "pandas krävs för Excel-import (pip install pandas openpyxl)"

        if not filepath.exists():
            return None, f"Filen finns inte: {filepath}"

        try:
            import pandas as pd

            if filepath.suffix.lower() == ".xls":
                df = pd.read_excel(filepath, engine="xlrd")
            else:
                df = pd.read_excel(filepath, engine="openpyxl")

            if df.empty:
                return None, "Filen är tom"

            df.columns = [str(c).strip() for c in df.columns]
            return df, f"Läste {len(df)} rader"

        except Exception as exc:
            logger.error("Excel read error: %s", exc)
            return None, f"Kunde inte läsa fil: {exc}"

    def find_columns(self, df: "DataFrame") -> Tuple[Optional[str], Optional[str]]:
        """Hitta kod- och namnkolumner."""
        try:
            columns_lower = {str(c).lower(): str(c) for c in df.columns}

            code_col = None
            name_col = None

            for pattern in CODE_COLUMN_PATTERNS:
                for col_lower, col_orig in columns_lower.items():
                    if pattern in col_lower:
                        code_col = col_orig
                        break
                if code_col:
                    break

            for pattern in NAME_COLUMN_PATTERNS:
                for col_lower, col_orig in columns_lower.items():
                    if pattern in col_lower and col_orig != code_col:
                        name_col = col_orig
                        break
                if name_col:
                    break

            return code_col, name_col
        except Exception as exc:
            logger.error("find_columns failed: %s", exc)
            return None, None

    def extract_colors(
        self,
        df: "DataFrame",
        code_col: str,
        name_col: str,
        source_file: str = "",
    ) -> List[ImportedColor]:
        """Extrahera färger från DataFrame."""
        colors: List[ImportedColor] = []

        try:
            for idx, row in df.iterrows():
                row_num = int(idx) + 2

                name_raw = row.get(name_col)
                code_raw = row.get(code_col)

                name = self._normalize_name(name_raw)
                if not name:
                    continue

                code = self._normalize_code(code_raw)
                if not code:
                    code = self._guess_code(name)

                if not code:
                    colors.append(
                        ImportedColor(
                            code="",
                            name=name,
                            source_file=source_file,
                            row_number=row_num,
                            status="skipped",
                            error_message="Saknar färgkod",
                        )
                    )
                    continue

                colors.append(
                    ImportedColor(
                        code=code,
                        name=name,
                        source_file=source_file,
                        row_number=row_num,
                        status="pending",
                    )
                )
        except Exception as exc:
            logger.error("extract_colors failed: %s", exc)

        return colors

    def _normalize_name(self, value: Any) -> str:
        """Normalisera färgnamn."""
        try:
            if value is None:
                return ""

            import pandas as pd

            if pd.isna(value):
                return ""

            name = str(value).strip()
            name = re.sub(r"[\r\n\t]+", " ", name)
            name = re.sub(r"\s+", " ", name)

            if len(name) < 2 or len(name) > 100:
                return ""

            if name.lower() in {"nan", "none", "null", "-", ""}:
                return ""

            return name
        except Exception:
            return ""

    def _normalize_code(self, value: Any) -> str:
        """Normalisera färgkod."""
        try:
            if value is None:
                return ""

            import pandas as pd

            if pd.isna(value):
                return ""

            code = str(value).strip().upper()
            if code.lower() in {"nan", "none", "null", "-", ""}:
                return ""

            code = re.sub(r"[^A-Z0-9]", "", code)

            if len(code) < 1 or len(code) > 10:
                return ""

            return code
        except Exception:
            return ""

    def _guess_code(self, name: str) -> str:
        """Gissa färgkod från namn."""
        try:
            name_lower = name.lower()
            for keyword, code in DEFAULT_COLOR_CODES.items():
                if keyword in name_lower:
                    return code
        except Exception:
            pass
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# PDF EXPORTER
# ══════════════════════════════════════════════════════════════════════════════

class PdfExporter:
    """Exporterar färglista till PDF. Kräver reportlab."""

    _available: Optional[bool] = None

    @classmethod
    def is_available(cls) -> bool:
        """Kontrollera om PDF-export är tillgängligt."""
        if cls._available is None:
            try:
                import reportlab  # noqa: F401
                cls._available = True
            except ImportError:
                cls._available = False
        return cls._available

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        colors: List[Tuple[str, str]],
        title: str = "Färglista",
        filename: Optional[str] = None,
    ) -> Optional[Path]:
        """Exportera färglista till PDF."""
        if not self.is_available():
            logger.error("reportlab not available")
            return None

        if not colors:
            logger.warning("No colors to export")
            return None

        try:
            from reportlab.lib import colors as rl_colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"farglista_{timestamp}.pdf"

            pdf_path = self.output_dir / filename

            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=A4,
                rightMargin=20 * mm,
                leftMargin=20 * mm,
                topMargin=20 * mm,
                bottomMargin=20 * mm,
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                "CustomTitle",
                parent=styles["Heading1"],
                fontSize=18,
                spaceAfter=12,
            )

            elements = []
            elements.append(Paragraph(title, title_style))
            elements.append(
                Paragraph(
                    f"Exporterad: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Antal: {len(colors)}",
                    styles["Normal"],
                )
            )
            elements.append(Spacer(1, 10 * mm))

            table_data = [["Kod", "Namn"]]
            table_data.extend(list(colors))

            table = Table(table_data, colWidths=[30 * mm, 120 * mm])
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), rl_colors.grey),
                        ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                        ("BACKGROUND", (0, 1), (-1, -1), rl_colors.white),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.grey),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [rl_colors.white, rl_colors.Color(0.95, 0.95, 0.95)],
                        ),
                    ]
                )
            )

            elements.append(table)
            doc.build(elements)

            logger.info("Exported %s colors to %s", len(colors), pdf_path.name)
            return pdf_path

        except Exception as exc:
            logger.error("PDF export failed: %s", exc)
            return None


# ══════════════════════════════════════════════════════════════════════════════
# IMPORT WORKER
# ══════════════════════════════════════════════════════════════════════════════

class ImportWorker(QThread):
    """Bakgrundstråd för import."""

    progress_changed = Signal(int, int, str)
    file_complete = Signal(object)
    batch_finished = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, files: List[Path], plugin: "Plugin", parent: Any = None) -> None:
        super().__init__(parent)
        self.files = files
        self.plugin = plugin
        self._cancelled = False
        self._reader = ExcelColorReader()

    def cancel(self) -> None:
        """Avbryt import."""
        self._cancelled = True

    def run(self) -> None:
        """Kör import i bakgrundstråd."""
        import time

        start_time = time.perf_counter()
        batch_result = BatchImportResult()

        try:
            for index, filepath in enumerate(self.files, start=1):
                if self._cancelled:
                    break

                self.progress_changed.emit(index, len(self.files), filepath.name)
                result = self._import_file(filepath)
                batch_result.add(result)
                self.file_complete.emit(result)

            batch_result.duration_ms = (time.perf_counter() - start_time) * 1000
            self.batch_finished.emit(batch_result)

        except Exception as exc:
            logger.exception("Worker crashed")
            self.error_occurred.emit(str(exc))

    def _import_file(self, filepath: Path) -> ImportResult:
        """Importera en fil."""
        import time

        start_time = time.perf_counter()
        result = ImportResult(source_file=filepath.name)

        try:
            df, status = self._reader.read_file(filepath)
            if df is None:
                result.error_message = status
                return result

            code_col, name_col = self._reader.find_columns(df)
            if not code_col or not name_col:
                result.error_message = self._build_column_error(df)
                return result

            result.total_rows = len(df)

            colors = self._reader.extract_colors(df, code_col, name_col, filepath.name)

            for color in colors:
                if self._cancelled:
                    break

                if color.status == "skipped":
                    result.skipped += 1
                    result.colors.append(color)
                    continue

                try:
                    add_success, message, was_update = self.plugin._store_color(
                        code=color.code,
                        name=color.name,
                        ts_code=color.ts_code,
                    )

                    if add_success and not was_update:
                        color.status = "new"
                        result.imported += 1
                    elif add_success and was_update:
                        color.status = "updated"
                        result.updated += 1
                    else:
                        color.status = "skipped"
                        color.error_message = message or "Kunde inte spara färg"
                        result.skipped += 1

                    result.colors.append(color)

                except Exception as exc:
                    color.status = "error"
                    color.error_message = str(exc)
                    result.errors += 1
                    result.colors.append(color)

            result.success = True

        except Exception as exc:
            result.error_message = str(exc)
            logger.exception("Import failed: %s", filepath)

        result.duration_ms = (time.perf_counter() - start_time) * 1000
        return result

    def _build_column_error(self, df: "DataFrame") -> str:
        """Bygg felmeddelande för saknade kolumner."""
        try:
            cols = list(df.columns)[:8]
            return (
                "Kunde inte hitta rätt kolumner.\n"
                f"Hittade: {', '.join(str(c) for c in cols)}\n\n"
                "Förväntade:\n"
                "- Kod: 'SE color code', 'färgkod'\n"
                "- Namn: 'Color', 'Färg'"
            )
        except Exception:
            return "Kunde inte hitta kolumner"


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """Color Import Plugin v3.0.0."""

    NAME: str = "Color Import"
    VERSION: str = VERSION
    DESCRIPTION: str = "Import av färgdata från Excel med PDF-export (12 funktioner)"
    AUTHOR: str = AUTHOR
    DEPENDENCIES: List[str] = ["colors_manager"]
    OPTIONAL_DEPENDENCIES: List[str] = ["ts_spec_import"]

    def __init__(self, app: "Application") -> None:
        super().__init__(app)
        self.is_active: bool = False
        self._colors_manager: Optional[Any] = None
        self._widget: Optional[Any] = None
        self._pdf_exporter: Optional[PdfExporter] = None
        self._import_worker: Optional[ImportWorker] = None
        self._initialized: bool = False
        self._import_history: List[ImportResult] = []

    @property
    def copyright(self) -> str:
        """Dynamisk copyright-sträng."""
        return get_copyright_string()

    @property
    def colors_service(self) -> Optional[Any]:
        """Hämta färgservice eller plugin direkt."""
        try:
            if self._colors_manager is None:
                return None

            service = getattr(self._colors_manager, "service", None)
            if service is not None:
                return service

            return self._colors_manager
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Initiera plugin."""
        try:
            logger.info("=" * 60)
            logger.info("Color Import v%s", VERSION)
            logger.info("%s", self.copyright)
            logger.info("=" * 60)

            self._colors_manager = get_plugin_safe(self.app, "colors_manager")
            if not self._colors_manager:
                logger.warning("colors_manager not found - limited functionality")

            base_dir = Path(get_config_value(self.app, "base_dir", "."))
            output_dir = base_dir / get_config_value(self.app, "ut_dir", "ut")
            self._pdf_exporter = PdfExporter(output_dir)

            try:
                self.app.color_import = self
            except Exception:
                pass

            self._initialized = True

            pdf_status = "✅" if PdfExporter.is_available() else "❌"
            logger.info("Initialized (PDF: %s)", pdf_status)
            logger.info("12 public functions available")
            return True

        except Exception as exc:
            logger.exception("Failed to initialize: %s", exc)
            self._initialized = False
            return False

    def activate(self) -> bool:
        """Aktivera plugin."""
        try:
            self.is_active = True

            event_bus = getattr(self.app, "event_bus", None)
            if event_bus and hasattr(event_bus, "on") and callable(event_bus.on):
                try:
                    event_bus.on("colors:import_request", self._on_import_request)
                except Exception:
                    pass
            elif event_bus and hasattr(event_bus, "subscribe") and callable(event_bus.subscribe):
                try:
                    event_bus.subscribe("colors:import_request", self._on_import_request)
                except Exception:
                    pass

            emit_event_safe(self.app, "color_import:activated", {})
            logger.info("Activated")
            return True

        except Exception as exc:
            logger.exception("Activation failed: %s", exc)
            return False

    def deactivate(self) -> bool:
        """Deaktivera plugin."""
        try:
            if self._import_worker and self._import_worker.isRunning():
                self._import_worker.cancel()
                self._import_worker.wait(3000)

            self._widget = None
            self.is_active = False
            logger.info("Deactivated")
            return True

        except Exception as exc:
            logger.exception("Deactivation failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Kontraktskompatibilitet
    # ------------------------------------------------------------------

    def init(self) -> bool:
        """Alias för initialize()."""
        return self.initialize()

    def register_ui(self, parent: QWidget) -> QWidget:
        """Alias för create_widget()."""
        return self.create_widget(parent)

    def shutdown(self) -> bool:
        """Alias för deactivate()."""
        return self.deactivate()

    def config_schema(self) -> Dict[str, Any]:
        """Returnera plugin-konfiguration."""
        return {
            "enabled": {
                "type": "boolean",
                "default": True,
                "description": "Aktivera Color Import-pluginet.",
            },
            "auto_import_patterns": {
                "type": "array",
                "default": list(AUTO_IMPORT_PATTERNS),
                "description": "Filnamnsmönster för auto-import från katalog.",
            },
            "pdf_enabled": {
                "type": "boolean",
                "default": True,
                "description": "Tillåt PDF-export om reportlab finns installerat.",
            },
        }

    def create_widget(self, parent: QWidget) -> QWidget:
        """Skapa widget."""
        try:
            self._widget = ColorImportWidget(parent, self)
            return self._widget
        except Exception as exc:
            logger.exception("Failed to create widget: %s", exc)
            fallback = QWidget(parent)
            layout = QVBoxLayout(fallback)
            label = QLabel(f"❌ Widget creation failed: {exc}")
            label.setWordWrap(True)
            layout.addWidget(label)
            return fallback

    # ------------------------------------------------------------------
    # Public API 1-12
    # ------------------------------------------------------------------

    def import_from_file(
        self,
        filepath: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ) -> Optional[ImportResult]:
        """1. Importera från Excel-fil."""
        try:
            if filepath is None:
                filepath_str, _ = QFileDialog.getOpenFileName(
                    parent,
                    "Välj Excel-fil med färger",
                    str(self._get_data_dir()),
                    "Excel-filer (*.xlsx *.xls *.xlsm);;Alla filer (*.*)",
                )
                if not filepath_str:
                    return None
                filepath = Path(filepath_str)

            if not self.colors_service:
                QMessageBox.warning(parent, "Fel", "colors_manager plugin ej tillgänglig")
                return None

            worker = ImportWorker([filepath], self)
            batch_result = self._run_worker_sync(
                worker=worker,
                parent=parent,
                label_text=f"Importerar {filepath.name}...",
                maximum=1,
            )
            if not batch_result or not batch_result.results:
                return None

            result = batch_result.results[0]
            self._import_history.append(result)
            self._show_result_dialog(parent, result)

            emit_event_safe(
                self.app,
                "colors:imported",
                {
                    "file": filepath.name,
                    "imported": result.imported,
                    "updated": result.updated,
                    "errors": result.errors,
                },
            )
            return result

        except Exception as exc:
            logger.exception("import_from_file failed: %s", exc)
            return None

    def import_from_directory(
        self,
        directory: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ) -> Optional[BatchImportResult]:
        """2. Batch-import från katalog."""
        try:
            if directory is None:
                directory = self._get_data_dir()

            files = self._find_color_files(directory)
            if not files:
                QMessageBox.information(
                    parent,
                    "Info",
                    f"Inga färgfiler hittades i:\n{directory}\n\n"
                    "Filnamnet måste innehålla 'färg', 'color' etc.",
                )
                return None

            if not self.colors_service:
                QMessageBox.warning(parent, "Fel", "colors_manager plugin ej tillgänglig")
                return None

            preview = "\n".join(f"• {f.name}" for f in files[:5])
            if len(files) > 5:
                preview += f"\n... +{len(files) - 5} fler"

            reply = QMessageBox.question(
                parent,
                "Bekräfta import",
                f"Importera {len(files)} färgfiler?\n\n{preview}",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return None

            worker = ImportWorker(files, self)
            result = self._run_worker_sync(
                worker=worker,
                parent=parent,
                label_text="Startar import...",
                maximum=len(files),
            )
            if result is None:
                return None

            for file_result in result.results:
                self._import_history.append(file_result)

            self._show_batch_result_dialog(parent, result)
            emit_event_safe(
                self.app,
                "colors:batch_imported",
                {
                    "files": len(files),
                    "imported": result.total_imported,
                    "updated": result.total_updated,
                    "errors": result.total_errors,
                },
            )
            return result

        except Exception as exc:
            logger.exception("import_from_directory failed: %s", exc)
            return None

    def export_to_pdf(self, parent: Optional[QWidget] = None) -> Optional[Path]:
        """3. Exportera till PDF."""
        try:
            if not PdfExporter.is_available():
                QMessageBox.warning(
                    parent,
                    "PDF ej tillgängligt",
                    "Installera reportlab:\n\npip install reportlab",
                )
                return None

            if not self.colors_service:
                QMessageBox.warning(parent, "Fel", "Inga färger tillgängliga")
                return None

            colors = self._service_get_all_colors()
            if not colors:
                QMessageBox.information(parent, "Info", "Inga färger att exportera")
                return None

            color_tuples = [(code, name) for code, name in colors]
            pdf_path = self._pdf_exporter.export(color_tuples) if self._pdf_exporter else None

            if pdf_path:
                reply = QMessageBox.question(
                    parent,
                    "PDF Export",
                    f"Exporterade {len(colors)} färger till:\n{pdf_path.name}\n\nÖppna filen?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    self._open_file(pdf_path)

            return pdf_path

        except Exception as exc:
            logger.exception("export_to_pdf failed: %s", exc)
            return None

    def analyze_file(self, filepath: Path) -> Dict[str, Any]:
        """4. Analysera Excel-fil."""
        result: Dict[str, Any] = {
            "success": False,
            "filepath": str(filepath),
            "rows": 0,
            "columns": [],
            "detected_code_col": None,
            "detected_name_col": None,
            "preview_colors": [],
        }

        try:
            reader = ExcelColorReader()
            if not reader.is_available:
                result["error"] = "pandas not available"
                return result

            df, status = reader.read_file(filepath)
            if df is None:
                result["error"] = status
                return result

            result["rows"] = len(df)
            result["columns"] = list(df.columns)

            code_col, name_col = reader.find_columns(df)
            result["detected_code_col"] = code_col
            result["detected_name_col"] = name_col

            if code_col and name_col:
                colors = reader.extract_colors(df, code_col, name_col)
                result["preview_colors"] = [
                    {"code": c.code, "name": c.name}
                    for c in colors[:10]
                ]

            result["success"] = True

        except Exception as exc:
            result["error"] = str(exc)

        return result

    def get_import_history(self, limit: int = 10) -> List[ImportResult]:
        """5. Hämta importhistorik."""
        try:
            return self._import_history[-limit:]
        except Exception:
            return []

    def validate_colors(self, colors: List[ImportedColor]) -> Tuple[List[ImportedColor], List[str]]:
        """6. Validera färgdata."""
        valid: List[ImportedColor] = []
        errors: List[str] = []

        try:
            seen_codes: Set[str] = set()

            for color in colors:
                if not color.code:
                    errors.append(f"Rad {color.row_number}: Saknar kod")
                    continue

                if color.code in seen_codes:
                    errors.append(f"Rad {color.row_number}: Dublett av '{color.code}'")
                    continue

                if not color.name or len(color.name) < 2:
                    errors.append(f"Rad {color.row_number}: Ogiltigt namn")
                    continue

                seen_codes.add(color.code)
                valid.append(color)

        except Exception as exc:
            errors.append(f"Valideringsfel: {exc}")

        return valid, errors

    def auto_detect_columns(self, df: "DataFrame") -> Dict[str, Optional[str]]:
        """7. Auto-detektera kolumner."""
        try:
            reader = ExcelColorReader()
            code_col, name_col = reader.find_columns(df)
            return {"code": code_col, "name": name_col}
        except Exception as exc:
            logger.error("auto_detect_columns failed: %s", exc)
            return {"code": None, "name": None}

    def suggest_ts_codes(self, colors: List[ImportedColor]) -> List[ImportedColor]:
        """8. Föreslå TS-koder."""
        try:
            reader = ExcelColorReader()
            for color in colors:
                if not color.ts_code and color.name:
                    guessed = reader._guess_code(color.name)
                    if guessed:
                        color.ts_code = guessed
        except Exception as exc:
            logger.error("suggest_ts_codes failed: %s", exc)
        return colors

    def merge_duplicates(self, colors: List[ImportedColor]) -> List[ImportedColor]:
        """9. Slå samman dubletter."""
        try:
            seen: Dict[str, ImportedColor] = {}

            for color in colors:
                key = color.code.upper()
                if key in seen:
                    if len(color.name) > len(seen[key].name):
                        seen[key] = color
                else:
                    seen[key] = color

            return list(seen.values())
        except Exception as exc:
            logger.error("merge_duplicates failed: %s", exc)
            return colors

    def export_import_report(
        self,
        result: ImportResult,
        output_path: Optional[Path] = None,
    ) -> Optional[Path]:
        """10. Exportera importrapport."""
        try:
            if output_path is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = self._get_data_dir() / f"import_report_{timestamp}.json"

            data = result.to_dict()
            data["copyright"] = self.copyright
            data["exported_at"] = datetime.now().isoformat()

            atomic_write_json(output_path, data)
            logger.info("Exported import report to %s", output_path)
            return output_path

        except Exception as exc:
            logger.error("export_import_report failed: %s", exc)
            return None

    def get_statistics(self) -> Dict[str, Any]:
        """11. Hämta importstatistik."""
        try:
            total_imports = len(self._import_history)
            total_colors = sum(r.imported for r in self._import_history)
            total_errors = sum(r.errors for r in self._import_history)
            failed_imports = sum(1 for r in self._import_history if not r.success)

            return {
                "total_imports": total_imports,
                "total_colors_imported": total_colors,
                "total_errors": total_errors,
                "success_rate": round(
                    ((total_imports - failed_imports) / total_imports) * 100,
                    1,
                ) if total_imports > 0 else 0.0,
                "recent_imports": [r.to_dict() for r in self._import_history[-5:]],
            }
        except Exception as exc:
            return {"error": str(exc)}

    def get_diagnostics(self) -> Dict[str, Any]:
        """12. Hämta diagnostik."""
        try:
            reader = ExcelColorReader()

            return {
                "plugin_name": self.NAME,
                "plugin_version": self.VERSION,
                "copyright": self.copyright,
                "initialized": self._initialized,
                "is_active": self.is_active,
                "colors_manager_available": self._colors_manager is not None,
                "pandas_available": reader.is_available,
                "pdf_export_available": PdfExporter.is_available(),
                "import_history_count": len(self._import_history),
                "functions_available": 12,
            }
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_data_dir(self) -> Path:
        """Hämta data-katalog."""
        try:
            base_dir = Path(get_config_value(self.app, "base_dir", "."))
            return base_dir / get_config_value(self.app, "data_dir", "data")
        except Exception:
            return Path("data")

    def _find_color_files(self, directory: Path) -> List[Path]:
        """Hitta färgfiler."""
        try:
            if not directory.exists():
                return []

            all_excel = (
                list(directory.glob("*.xlsx"))
                + list(directory.glob("*.xls"))
                + list(directory.glob("*.xlsm"))
            )
            all_excel = [f for f in all_excel if not f.name.startswith("~$")]

            return [
                f for f in all_excel
                if any(pattern in f.stem.lower() for pattern in AUTO_IMPORT_PATTERNS)
            ]
        except Exception:
            return []

    def _on_import_request(self, data: Dict[str, Any]) -> None:
        """Hantera import-request event."""
        try:
            filepath = data.get("filepath")
            if filepath:
                self.import_from_file(Path(filepath))
        except Exception as exc:
            logger.debug("Import request failed: %s", exc)

    def _run_worker_sync(
        self,
        worker: ImportWorker,
        parent: Optional[QWidget],
        label_text: str,
        maximum: int,
    ) -> Optional[BatchImportResult]:
        """Kör worker med progressdialog och invänta resultat."""
        self._import_worker = worker

        progress = QProgressDialog(label_text, "Avbryt", 0, maximum, parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(True)
        progress.setMinimumDuration(0)

        loop = QEventLoop()
        batch_result: Optional[BatchImportResult] = None
        error_message: Optional[str] = None

        def on_progress(current: int, total: int, message: str) -> None:
            progress.setMaximum(max(total, 1))
            progress.setValue(current)
            progress.setLabelText(f"[{current}/{total}] {message}")

        def on_finished(result: BatchImportResult) -> None:
            nonlocal batch_result
            batch_result = result
            progress.setValue(progress.maximum())
            loop.quit()

        def on_error(message: str) -> None:
            nonlocal error_message
            error_message = message
            loop.quit()

        worker.progress_changed.connect(on_progress)
        worker.batch_finished.connect(on_finished)
        worker.error_occurred.connect(on_error)
        progress.canceled.connect(worker.cancel)

        worker.start()
        loop.exec()

        progress.close()

        if error_message:
            QMessageBox.critical(parent, "Fel", error_message)
            return None

        return batch_result

    def _store_color(self, code: str, name: str, ts_code: str = "") -> Tuple[bool, str, bool]:
        """
        Spara färg via colors_manager.

        Returnerar:
            (success, message, was_update)
        """
        service = self.colors_service
        if service is None:
            return False, "colors_manager ej tillgänglig", False

        existing = self._service_get_by_code(code)
        if existing is not None:
            updated = self._service_update_color(code=code, name=name, ts_code=ts_code)
            return updated, "" if updated else "Kunde inte uppdatera befintlig färg", True

        created = self._service_add_color(code=code, name=name, ts_code=ts_code)
        return created, "" if created else "Kunde inte skapa färg", False

    def _service_add_color(self, code: str, name: str, ts_code: str = "") -> bool:
        """Försök skapa färg via olika API-varianter."""
        service = self.colors_service
        if service is None:
            return False

        candidate_calls = [
            ("add", {"code": code, "name": name, "ts_code": ts_code}),
            ("add_color", {"code": code, "name": name, "ts_code": ts_code}),
            ("create", {"code": code, "name": name, "ts_code": ts_code}),
        ]

        for method_name, kwargs in candidate_calls:
            method = getattr(service, method_name, None)
            if not callable(method):
                continue

            try:
                result = method(**kwargs)
                return self._normalize_operation_result(result)
            except TypeError:
                try:
                    result = method(code, name, ts_code)
                    return self._normalize_operation_result(result)
                except Exception:
                    continue
            except Exception:
                continue

        return False

    def _service_update_color(self, code: str, name: str, ts_code: str = "") -> bool:
        """Försök uppdatera färg via olika API-varianter."""
        service = self.colors_service
        if service is None:
            return False

        candidate_calls = [
            ("update", {"code": code, "name": name, "ts_code": ts_code}),
            ("update_color", {"code": code, "name": name, "ts_code": ts_code}),
            ("set", {"code": code, "name": name, "ts_code": ts_code}),
        ]

        for method_name, kwargs in candidate_calls:
            method = getattr(service, method_name, None)
            if not callable(method):
                continue

            try:
                result = method(**kwargs)
                return self._normalize_operation_result(result)
            except TypeError:
                try:
                    result = method(code, name, ts_code)
                    return self._normalize_operation_result(result)
                except Exception:
                    continue
            except Exception:
                continue

        return False

    def _service_get_by_code(self, code: str) -> Any:
        """Hämta färg via olika API-varianter."""
        service = self.colors_service
        if service is None:
            return None

        for method_name in ("get_by_code", "get", "find_by_code"):
            method = getattr(service, method_name, None)
            if not callable(method):
                continue

            try:
                return method(code)
            except Exception:
                continue

        return None

    def _service_get_all_colors(self) -> List[Tuple[str, str]]:
        """Hämta alla färger och normalisera till lista av tuples."""
        service = self.colors_service
        if service is None:
            return []

        raw_colors: Any = []
        for method_name in ("get_all", "list", "all"):
            method = getattr(service, method_name, None)
            if not callable(method):
                continue

            try:
                raw_colors = method()
                break
            except Exception:
                continue

        if raw_colors is None:
            return []

        normalized: List[Tuple[str, str]] = []
        try:
            for item in raw_colors:
                if isinstance(item, dict):
                    code = str(item.get("code", "")).strip()
                    name = str(item.get("name", "")).strip()
                else:
                    code = str(getattr(item, "code", "")).strip()
                    name = str(getattr(item, "name", "")).strip()

                if code and name:
                    normalized.append((code, name))
        except Exception:
            return []

        return normalized

    def _normalize_operation_result(self, result: Any) -> bool:
        """Normalisera resultat från service-anrop till bool."""
        try:
            if isinstance(result, bool):
                return result
            if isinstance(result, tuple) and result:
                return bool(result[0])
            if hasattr(result, "success"):
                return bool(result.success)
            if result is None:
                return False
            return True
        except Exception:
            return False

    def _show_result_dialog(self, parent: Optional[QWidget], result: ImportResult) -> None:
        """Visa resultatdialog."""
        try:
            if result.success:
                msg = (
                    "✅ Import klar!\n\n"
                    f"Fil: {result.source_file}\n"
                    f"Totalt: {result.total_rows} rader\n\n"
                    f"• Nya: {result.imported}\n"
                    f"• Uppdaterade: {result.updated}\n"
                    f"• Hoppade över: {result.skipped}\n"
                    f"• Fel: {result.errors}"
                )
                QMessageBox.information(parent, "Import klar", msg)
            else:
                QMessageBox.warning(
                    parent,
                    "Import misslyckades",
                    f"❌ {result.error_message}",
                )
        except Exception:
            pass

    def _show_batch_result_dialog(self, parent: Optional[QWidget], result: BatchImportResult) -> None:
        """Visa batch-resultat."""
        try:
            msg = (
                "✅ Batch-import klar!\n\n"
                f"Filer: {result.files_processed} OK, {result.files_failed} fel\n\n"
                "Färger:\n"
                f"• Nya: {result.total_imported}\n"
                f"• Uppdaterade: {result.total_updated}\n"
                f"• Hoppade över: {result.total_skipped}\n"
                f"• Fel: {result.total_errors}\n\n"
                f"Tid: {result.duration_ms / 1000:.1f}s"
            )
            QMessageBox.information(parent, "Batch-import klar", msg)
        except Exception:
            pass

    def _open_file(self, filepath: Path) -> None:
        """Öppna fil med standardprogram."""
        try:
            if sys.platform == "win32":
                subprocess.run(["cmd", "/c", "start", "", str(filepath)], check=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(filepath)], check=False)
            else:
                subprocess.run(["xdg-open", str(filepath)], check=False)
        except Exception as exc:
            logger.debug("Could not open file: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class ColorImportWidget(QWidget):
    """Widget för färgimport."""

    def __init__(self, parent: QWidget, plugin: Plugin) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.status_label: Optional[QLabel] = None

        self.setObjectName("colorImportWidget")
        self.setAcceptDrops(True)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Bygg UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("📥 Färgimport")
        header.setObjectName("pageTitle")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setWordWrap(True)
        layout.addWidget(header)

        description = QLabel(
            "Importera färglistor från Excel och spara dem via colors_manager."
        )
        description.setObjectName("infoLabel")
        description.setWordWrap(True)
        layout.addWidget(description)

        drop_zone = self._create_drop_zone()
        layout.addWidget(drop_zone)

        actions = self._create_actions()
        layout.addWidget(actions)

        self.status_label = QLabel("Dra och släpp Excel-filer här")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addStretch()

        footer = QLabel(self.plugin.copyright)
        footer.setObjectName("footerLabel")
        footer.setAlignment(Qt.AlignRight)
        footer.setWordWrap(True)
        layout.addWidget(footer)

    def _create_drop_zone(self) -> QFrame:
        """Skapa drop-zone."""
        frame = QFrame()
        frame.setObjectName("dropZone")
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setFrameShadow(QFrame.Sunken)
        frame.setMinimumHeight(150)
        frame.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(frame)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("📁")
        icon.setAlignment(Qt.AlignCenter)
        icon_font = QFont()
        icon_font.setPointSize(28)
        icon.setFont(icon_font)
        layout.addWidget(icon)

        text = QLabel("Dra Excel-filer hit\neller klicka för att välja")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        layout.addWidget(text)

        def on_click(event: Any) -> None:
            _ = event
            self._on_drop_zone_click()

        frame.mousePressEvent = on_click  # type: ignore[method-assign]
        return frame

    def _create_actions(self) -> QGroupBox:
        """Skapa action-knappar."""
        group = QGroupBox("Åtgärder")
        group.setObjectName("actionGroup")

        layout = QHBoxLayout(group)

        btn_file = QPushButton("📄 Importera fil...")
        btn_file.setObjectName("primaryButton")
        btn_file.clicked.connect(lambda: self.plugin.import_from_file(parent=self))
        layout.addWidget(btn_file)

        btn_auto = QPushButton("📁 Auto-import katalog")
        btn_auto.setObjectName("secondaryButton")
        btn_auto.clicked.connect(lambda: self.plugin.import_from_directory(parent=self))
        layout.addWidget(btn_auto)

        btn_pdf = QPushButton("📄 Exportera PDF")
        btn_pdf.setObjectName("secondaryButton")
        btn_pdf.setEnabled(PdfExporter.is_available())
        btn_pdf.clicked.connect(lambda: self.plugin.export_to_pdf(parent=self))
        layout.addWidget(btn_pdf)

        return group

    def _on_drop_zone_click(self) -> None:
        """Hantera klick på drop-zone."""
        self.plugin.import_from_file(parent=self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Hantera drag enter."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
                        event.acceptProposedAction()
                        if self.status_label:
                            self.status_label.setText("Släpp för att importera...")
                        return
        event.ignore()

    def dragLeaveEvent(self, event: Any) -> None:
        """Hantera drag leave."""
        _ = event
        if self.status_label:
            self.status_label.setText("Dra och släpp Excel-filer här")

    def dropEvent(self, event: QDropEvent) -> None:
        """Hantera drop."""
        files: List[Path] = []

        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
                    files.append(path)

        if files:
            event.acceptProposedAction()
            if self.status_label:
                self.status_label.setText(f"Importerar {len(files)} fil(er)...")

            for filepath in files:
                self.plugin.import_from_file(filepath, parent=self)

            if self.status_label:
                self.status_label.setText("Dra och släpp Excel-filer här")
        else:
            event.ignore()

    def refresh(self) -> None:
        """Refresh widget."""
        if self.status_label:
            self.status_label.setText("Dra och släpp Excel-filer här")


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "VERSION",
    "AUTHOR",
    "CODE_COLUMN_PATTERNS",
    "NAME_COLUMN_PATTERNS",
    "AUTO_IMPORT_PATTERNS",
    "DEFAULT_COLOR_CODES",
    "get_copyright_year",
    "get_copyright_string",
    "get_plugin_safe",
    "emit_event_safe",
    "ImportedColor",
    "ImportResult",
    "BatchImportResult",
    "ExcelColorReader",
    "PdfExporter",
    "ImportWorker",
    "Plugin",
    "ColorImportWidget",
]