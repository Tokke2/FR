# -*- coding: utf-8 -*-
# Fil: plugins/reports/plugin.py
"""
Reports Plugin v2.1.1 (PySide6)
Rapportgenerering och HistoryPage - VIN, Återförsäljare, System

UPPDATERAD v2.1.0:
- Använder get_plugin() helper istället för plugin_manager
- Bättre felhantering
- Stöd för både plugin_loader och plugin_manager

Funktioner:
- VIN-rapporter per år/månad
- Återförsäljarrapporter
- Systemrapporter
- HistoryPage UI för visning och export

FÖRÄNDRINGAR v2.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (låst regel, KRAV 60): AUTHOR = "TADEGA AB" ->
      "Rickard Längkvist" (TADEGA AB är legacy — samma regel som
      ts_file_generator/ts_spec_viewer-granskningarna).
    - FIX (låst regel): ALLA print()-anrop -> module-level _log
      (lazy %s) — initialize, save_year_report, export_to_csv/excel/
      pdf, _save-sökväg.
    - VERSION/AUTHOR/get_copyright_string module-level tillagda
      (Plugin.VERSION/AUTHOR refererar dem).
    - FIX (atomer, låst regel): save_year_report()/export_to_csv()
      skrev med write_text/open — korrupta filer vid krasch. Nu
      mkstemp -> fsync -> os.replace (delad _atomic_write_text).
    - FIX (kraschsäkerhet): _setup_paths() — app.config kan vara
      None eller dict (guard saknades). Nu getattr + dict-stöd.
    - FIX (kraschsäkerhet): _register_events() anropade
      event_bus.on(..., source=...) — TypeError-fallback saknas
      (samma mönster som main.py/plugin_base). Nu try/except
      TypeError.
    - FIX (PySide6-enums, full form): Qt.Horizontal ->
      Qt.Orientation.Horizontal; QAbstractItemView.SelectRows ->
      SelectionBehavior.SelectRows; QMessageBox.Yes/No ->
      StandardButton.Yes/No.
    - config_schema() + get_diagnostics() tillagda (standardmönster).
    - OBSERVATION (EJ ändrad, inväntar beslut): PySide6 importeras på
      TOPPNIVÅ — paketet kraschar i headless/test (samma som
      response_viewer). Rekommendation: lokal import i
      create_widget()/register_ui() vid nästa rotation.
    - OBSERVATION (EJ ändrad): HistoryPage/export använder EGET
      hårdkodat färgschema (setStyleSheet) — tema-migrering inväntar
      beslut (samma som response_viewer StyleGenerator).
    - Övrig logik OFÖRÄNDRAD (MONTHS, get_plugin, VIN-rapporter,
      export CSV/Excel/PDF, statistik, list_reports, HistoryPage).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFileDialog,
    QComboBox, QTextEdit, QSplitter, QInputDialog,
    QAbstractItemView,
)

from core.plugin_base import PluginBase


# ══════════════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT / LOGGER
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "2.1.1"
AUTHOR: str = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback om logging ej konfigurerat.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("reports")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log = _get_logger()


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """
    Skriv text ATOMISKT: mkstemp -> fsync -> os.replace.

    Förhindrar korrupta filer vid krasch under skrivning.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.tmp_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTION FÖR PLUGIN-ACCESS
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin(app: Any, name: str) -> Optional[Any]:
    """
    Hämta plugin med fallback för olika attributnamn.

    Stödjer:
    - app.plugin_loader.get_plugin()
    - app.plugin_manager.get_plugin()
    - app.get_plugin()
    - app.<plugin_name>
    """
    # Normalisera namn
    normalized_name = name.lower().replace(" ", "_").replace("-", "_")
    names_to_try = [name, normalized_name]

    for try_name in names_to_try:
        # Försök app.get_plugin()
        if hasattr(app, 'get_plugin'):
            try:
                plugin = app.get_plugin(try_name)
                if plugin:
                    return plugin
            except Exception:
                pass

        # Försök plugin_loader
        if hasattr(app, 'plugin_loader'):
            try:
                plugin = app.plugin_loader.get_plugin(try_name)
                if plugin:
                    return plugin
            except Exception:
                pass

        # Fallback: plugin_manager
        if hasattr(app, 'plugin_manager'):
            try:
                plugin = app.plugin_manager.get_plugin(try_name)
                if plugin:
                    return plugin
            except Exception:
                pass

        # Fallback: direkt attribut
        attr = getattr(app, try_name, None)
        if attr:
            return attr

        attr = getattr(app, normalized_name, None)
        if attr:
            return attr

    return None


# ══════════════════════════════════════════════════════════════════════════════
# KONSTANTER
# ══════════════════════════════════════════════════════════════════════════════

# Svenska månader
MONTHS = {
    "01": "Januari", "02": "Februari", "03": "Mars", "04": "April",
    "05": "Maj", "06": "Juni", "07": "Juli", "08": "Augusti",
    "09": "September", "10": "Oktober", "11": "November", "12": "December"
}

# Exportera-beroenden
try:
    import pandas as pd
    EXCEL_AVAILABLE = True
except ImportError:
    pd = None
    EXCEL_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph,
    )
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN-KLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    Reports Plugin (PySide6)

    Genererar rapporter och visar historik.
    """

    NAME = "Reports"
    VERSION = VERSION
    DESCRIPTION = "Rapportgenerering och historik (PySide6)"
    AUTHOR = AUTHOR
    DEPENDENCIES = ["core_config"]
    OPTIONAL_DEPENDENCIES = ["vehicle_registry"]

    def __init__(self, app):
        super().__init__(app)
        self._paths: Dict[str, Path] = {}
        self._widget: Optional["HistoryPage"] = None

    # ══════════════════════════════════════════════════════════════════════════
    # LIVSCYKEL
    # ══════════════════════════════════════════════════════════════════════════

    def initialize(self) -> None:
        """Initiera plugin."""
        self._setup_paths()
        self._register_events()

        excel_status = "✅" if EXCEL_AVAILABLE else "❌"
        pdf_status = "✅" if PDF_AVAILABLE else "❌"
        _log.info("%s v%s initierad", self.NAME, self.VERSION)
        _log.info("Excel: %s | PDF: %s", excel_status, pdf_status)

    def init(self) -> None:
        self.initialize()

    def activate(self) -> None:
        """Aktivera plugin."""
        self.is_active = True

    def deactivate(self) -> None:
        """Deaktivera plugin."""
        self._unregister_events()
        self._widget = None
        self.is_active = False

    def shutdown(self) -> None:
        self.deactivate()

    def register_ui(self, parent: Any) -> Any:
        """Registrera widget (PluginBase v3.x kontrakt)."""
        return self.create_widget(parent)

    def config_schema(self) -> Dict[str, Any]:
        """Returnerar pluginets konfigurationsschema."""
        return {
            "plugin": self.NAME,
            "version": VERSION,
            "author": AUTHOR,
            "copyright": get_copyright_string(),
            "settings": {
                "reports_dir": "ut/rapporter",
            },
        }

    def get_diagnostics(self) -> Dict[str, Any]:
        """Hämta diagnostik (standardmönster)."""
        return {
            "plugin_name": self.NAME,
            "plugin_version": VERSION,
            "copyright": get_copyright_string(),
            "active": self.is_active,
            "excel_available": EXCEL_AVAILABLE,
            "pdf_available": PDF_AVAILABLE,
            "reports_dir": str(self._paths.get("reports", "")),
            "available_years": self.get_available_years(),
        }

    def create_widget(self, parent: QWidget) -> QWidget:
        """Skapa widget för main_gui."""
        self._widget = HistoryPage(parent, self.app, self)
        return self._widget

    def _setup_paths(self) -> None:
        """Konfigurera sökvägar (kraschsäkert)."""
        config = getattr(self.app, "config", None)

        base_dir = "."
        if config is not None:
            try:
                if hasattr(config, "get"):
                    base_dir = config.get("base_dir", ".") or "."
                elif isinstance(config, dict):
                    base_dir = config.get("base_dir", ".") or "."
            except Exception:
                pass

        base_path = Path(str(base_dir))
        self._paths = {
            "base": base_path,
            "reports": base_path / "ut" / "rapporter",
        }
        self._paths["reports"].mkdir(parents=True, exist_ok=True)

    def _register_events(self) -> None:
        """Registrera events."""
        bus = getattr(self.app, "event_bus", None)
        if bus is None:
            return
        try:
            bus.on(
                "reports:generate",
                self._on_generate_event,
                source=self.NAME,
            )
        except TypeError:
            # Fallback om on() inte stödjer source-parametern
            bus.on("reports:generate", self._on_generate_event)
        try:
            bus.on(
                "reports:refresh",
                self._on_refresh_event,
                source=self.NAME,
            )
        except TypeError:
            bus.on("reports:refresh", self._on_refresh_event)

    def _unregister_events(self) -> None:
        """Avregistrera events."""
        bus = getattr(self.app, "event_bus", None)
        if bus is None:
            return
        try:
            bus.off("reports:generate", self._on_generate_event)
            bus.off("reports:refresh", self._on_refresh_event)
        except Exception:
            pass

    def _on_generate_event(self, data: Optional[Dict] = None) -> None:
        """Hantera generate event."""
        if data:
            report_type = data.get("type", "vin")
            year = data.get("year")

            if report_type == "vin":
                self.generate_year_report(
                    int(year) if year else datetime.now().year
                )

    def _on_refresh_event(self, data: Optional[Dict] = None) -> None:
        """Hantera refresh event."""
        if self._widget:
            self._widget.refresh()

    # ══════════════════════════════════════════════════════════════════════════
    # VIN-RAPPORTER
    # ══════════════════════════════════════════════════════════════════════════

    def _get_vehicle_registry(self):
        """Hämta vehicle_registry plugin."""
        return get_plugin(self.app, "vehicle_registry")

    def _get_vins_data(self) -> Dict[str, Any]:
        """Hämta VIN-data från vehicle_registry."""
        vehicle_registry = self._get_vehicle_registry()

        if not vehicle_registry:
            return {}

        # Försök olika sätt att hämta data
        if (
            hasattr(vehicle_registry, 'vin_registry')
            and vehicle_registry.vin_registry
        ):
            try:
                return vehicle_registry.vin_registry.get_all()
            except Exception:
                pass

        # Fallback: Ladda direkt från JSON
        try:
            config = getattr(self.app, "config", None)
            base_dir = "."
            if config is not None:
                try:
                    if hasattr(config, "get"):
                        base_dir = config.get("base_dir", ".") or "."
                    elif isinstance(config, dict):
                        base_dir = config.get("base_dir", ".") or "."
                except Exception:
                    pass
            json_path = (
                Path(str(base_dir))
                / "data"
                / "vehicle_registry"
                / "registered_vins.json"
            )

            if json_path.exists():
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get("registered_vins", data)
        except Exception:
            pass

        return {}

    def generate_year_report(self, year: int) -> str:
        """
        Skapar textrapport för ett givet år.
        """
        vins_db = self._get_vins_data()
        report_data = vins_db.get(str(year), {})

        if not report_data:
            return f"Inga registrerade fordon hittades för år {year}."

        lines = [
            "═" * 60,
            f"  ÅRSRAPPORT {year}",
            f"  Genererad: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "═" * 60, ""
        ]

        total = 0
        for month in sorted(report_data.keys()):
            if month.startswith('_'):
                continue

            month_vins = report_data[month]
            if not isinstance(month_vins, list):
                continue

            count = len(month_vins)
            total += count

            month_name = MONTHS.get(month, f"Månad {month}")

            lines.append(f"📅 {month_name} ({month}): {count} fordon")

            # Visa VIN-nummer
            for vin in month_vins[:10]:  # Max 10 per månad
                lines.append(f"   └── {vin}")

            if count > 10:
                lines.append(f"   └── ... och {count - 10} till")

            lines.append("")

        lines.extend([
            "═" * 60,
            f"  TOTALT ÅR {year}: {total} fordon",
            "═" * 60
        ])

        return "\n".join(lines)

    def save_year_report(
        self, year: int, filepath: Optional[Path] = None
    ) -> Optional[Path]:
        """Sparar årsrapport till fil (atomiskt)."""
        report = self.generate_year_report(year)

        if filepath is None:
            filepath = self._paths["reports"] / f"arsrapport_{year}.txt"

        try:
            _atomic_write_text(filepath, report, encoding="utf-8")
            _log.info("Rapport sparad: %s", filepath)
            return filepath
        except Exception as e:
            _log.error("Kunde inte spara rapport: %s", e)
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # EXPORT FUNKTIONER
    # ══════════════════════════════════════════════════════════════════════════

    def export_to_csv(self, year: int) -> Optional[Path]:
        """Exportera till CSV (atomiskt)."""
        vins_db = self._get_vins_data()
        report_data = vins_db.get(str(year), {})

        if not report_data:
            return None

        filepath = self._paths["reports"] / f"vin_rapport_{year}.csv"

        try:
            import io
            buffer = io.StringIO()
            writer = csv.writer(buffer, delimiter=';')
            writer.writerow(['År', 'Månad', 'VIN', 'Månad (namn)'])

            for month in sorted(report_data.keys()):
                if month.startswith('_'):
                    continue

                month_vins = report_data[month]
                if not isinstance(month_vins, list):
                    continue

                month_name = MONTHS.get(month, month)

                for vin in month_vins:
                    writer.writerow([year, month, vin, month_name])

            _atomic_write_text(
                filepath,
                buffer.getvalue(),
                encoding="utf-8-sig",
            )
            _log.info("CSV exporterad: %s", filepath)
            return filepath

        except Exception as e:
            _log.error("CSV-exportfel: %s", e)
            return None

    def export_to_excel(self, year: int) -> Optional[Path]:
        """Exportera till Excel."""
        if not EXCEL_AVAILABLE:
            _log.error("pandas krävs för Excel-export")
            return None

        vins_db = self._get_vins_data()
        report_data = vins_db.get(str(year), {})

        if not report_data:
            return None

        filepath = self._paths["reports"] / f"vin_rapport_{year}.xlsx"

        try:
            # Samla data
            rows = []
            for month in sorted(report_data.keys()):
                if month.startswith('_'):
                    continue

                month_vins = report_data[month]
                if not isinstance(month_vins, list):
                    continue

                month_name = MONTHS.get(month, month)

                for vin in month_vins:
                    rows.append({
                        'År': year,
                        'Månad': month,
                        'Månad (namn)': month_name,
                        'VIN': vin
                    })

            df = pd.DataFrame(rows)
            df.to_excel(filepath, index=False, engine='openpyxl')

            _log.info("Excel exporterad: %s", filepath)
            return filepath

        except Exception as e:
            _log.error("Excel-exportfel: %s", e)
            return None

    def export_to_pdf(self, year: int) -> Optional[Path]:
        """Exportera till PDF."""
        if not PDF_AVAILABLE:
            _log.error("reportlab krävs för PDF-export")
            return None

        vins_db = self._get_vins_data()
        report_data = vins_db.get(str(year), {})

        if not report_data:
            return None

        filepath = self._paths["reports"] / f"vin_rapport_{year}.pdf"

        try:
            doc = SimpleDocTemplate(str(filepath), pagesize=A4)
            elements = []
            styles = getSampleStyleSheet()

            # Titel
            elements.append(Paragraph(f"VIN-rapport {year}", styles['Title']))
            elements.append(Paragraph(
                f"Genererad: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                styles['Normal']
            ))

            # Tabell
            table_data = [['Månad', 'Antal VIN']]
            total = 0

            for month in sorted(report_data.keys()):
                if month.startswith('_'):
                    continue

                month_vins = report_data[month]
                if not isinstance(month_vins, list):
                    continue

                count = len(month_vins)
                total += count
                month_name = MONTHS.get(month, month)
                table_data.append([month_name, str(count)])

            table_data.append(['TOTALT', str(total)])

            table = Table(table_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))

            elements.append(table)
            doc.build(elements)

            _log.info("PDF exporterad: %s", filepath)
            return filepath

        except Exception as e:
            _log.error("PDF-exportfel: %s", e)
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # STATISTIK
    # ══════════════════════════════════════════════════════════════════════════

    def get_statistics(self) -> Dict[str, Any]:
        """Hämtar statistik."""
        stats = {
            "total_registered": 0,
            "by_year": {},
            "available_years": [],
            "generated_at": datetime.now().isoformat()
        }

        vehicle_registry = self._get_vehicle_registry()

        if vehicle_registry:
            # Försök hämta statistik från plugin
            if (
                hasattr(vehicle_registry, 'vin_registry')
                and vehicle_registry.vin_registry
            ):
                try:
                    reg_stats = vehicle_registry.vin_registry.get_statistics()
                    stats["total_registered"] = reg_stats.get("total", 0)
                    stats["by_year"] = reg_stats.get("per_year", {})
                    stats["available_years"] = sorted(
                        stats["by_year"].keys(), reverse=True
                    )
                    return stats
                except Exception:
                    pass

            # Fallback: Beräkna från data
            if hasattr(vehicle_registry, 'get_registration_statistics'):
                try:
                    reg_stats = vehicle_registry.get_registration_statistics()
                    stats["total_registered"] = reg_stats.get("total", 0)
                    stats["by_year"] = reg_stats.get("per_year", {})
                    stats["available_years"] = sorted(
                        stats["by_year"].keys(), reverse=True
                    )
                    return stats
                except Exception:
                    pass

        # Sista fallback: Beräkna från JSON
        vins_db = self._get_vins_data()

        for year, year_data in vins_db.items():
            if year.startswith('_'):
                continue
            if not isinstance(year_data, dict):
                continue

            year_count = sum(
                len(m) for m in year_data.values()
                if isinstance(m, list)
            )

            stats["by_year"][year] = year_count
            stats["total_registered"] += year_count

        stats["available_years"] = sorted(
            stats["by_year"].keys(), reverse=True
        )

        return stats

    def get_available_years(self) -> List[str]:
        """Returnerar år med registrerade VIN."""
        stats = self.get_statistics()
        return stats.get("available_years", [])

    def list_reports(self) -> List[Dict[str, Any]]:
        """Listar genererade rapporter."""
        reports = []

        if not self._paths.get("reports"):
            return reports

        try:
            for filepath in sorted(
                self._paths["reports"].glob("*.*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            ):
                stat = filepath.stat()
                reports.append({
                    "filename": filepath.name,
                    "path": filepath,
                    "format": filepath.suffix.upper().lstrip("."),
                    "size_kb": round(stat.st_size / 1024, 1),
                    "created": datetime.fromtimestamp(
                        stat.st_mtime
                    ).isoformat(),
                })
        except Exception:
            pass

        return reports


# ══════════════════════════════════════════════════════════════════════════════
# HISTORY PAGE
# ══════════════════════════════════════════════════════════════════════════════

class HistoryPage(QWidget):
    """
    Sida för registreringshistorik och rapporter.
    """

    def __init__(self, parent: QWidget, app, plugin: Plugin):
        super().__init__(parent)
        self.app = app
        self.plugin = plugin
        self._setup_ui()

        # Ladda data efter kort fördröjning
        QTimer.singleShot(100, self.refresh)

    def _setup_ui(self) -> None:
        """Bygg UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Titel
        title = QLabel("📊 Registrerade Fordon (Historik)")
        title.setObjectName("PageTitle")
        title.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #ffffff;"
        )
        layout.addWidget(title)

        # Knappar
        btn_layout = QHBoxLayout()

        self.btn_refresh = QPushButton("🔄 Uppdatera")
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.clicked.connect(self.refresh)
        btn_layout.addWidget(self.btn_refresh)

        self.btn_report = QPushButton("📊 Skapa Årsrapport")
        self.btn_report.setObjectName("PrimaryButton")
        self.btn_report.setStyleSheet(
            "background-color: #007bff; color: white;"
        )
        self.btn_report.clicked.connect(self._create_report)
        btn_layout.addWidget(self.btn_report)

        self.btn_export_csv = QPushButton("📤 Exportera CSV")
        self.btn_export_csv.setObjectName("SecondaryButton")
        self.btn_export_csv.clicked.connect(self._export_csv)
        btn_layout.addWidget(self.btn_export_csv)

        if EXCEL_AVAILABLE:
            self.btn_export_excel = QPushButton("📊 Exportera Excel")
            self.btn_export_excel.setObjectName("SecondaryButton")
            self.btn_export_excel.clicked.connect(self._export_excel)
            btn_layout.addWidget(self.btn_export_excel)

        if PDF_AVAILABLE:
            self.btn_export_pdf = QPushButton("📄 Exportera PDF")
            self.btn_export_pdf.setObjectName("SecondaryButton")
            self.btn_export_pdf.clicked.connect(self._export_pdf)
            btn_layout.addWidget(self.btn_export_pdf)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Splitter för tabell + preview
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Vänster: Årstabell
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("År med registreringar:"))

        self.year_table = QTableWidget()
        self.year_table.setObjectName("YearTable")
        self.year_table.setColumnCount(3)
        self.year_table.setHorizontalHeaderLabels(
            ["År", "Antal VIN", "Månader"]
        )
        self.year_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.year_table.setAlternatingRowColors(True)
        self.year_table.itemSelectionChanged.connect(self._on_year_selected)
        self.year_table.setStyleSheet("""
            QTableWidget {
                background: #222; gridline-color: #444;
                color: #fff; alternate-background-color: #2a2a2a;
            }
            QHeaderView::section {
                background: #333; color: #fff;
                padding: 6px;
            }
        """)
        left_layout.addWidget(self.year_table)

        splitter.addWidget(left_widget)

        # Höger: Förhandsvisning
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addWidget(QLabel("Förhandsvisning:"))

        self.preview = QTextEdit()
        self.preview.setObjectName("ReportPreview")
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet("""
            QTextEdit {
                background: #1a1a1a; color: #ccc;
                font-family: 'Consolas', monospace;
                border: 1px solid #333;
            }
        """)
        right_layout.addWidget(self.preview)

        splitter.addWidget(right_widget)
        splitter.setSizes([300, 500])

        layout.addWidget(splitter)

        # Statistik
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("StatusLabel")
        self.stats_label.setStyleSheet("color: #888; padding: 5px;")
        layout.addWidget(self.stats_label)

    def refresh(self) -> None:
        """Uppdatera data."""
        vehicle_registry = get_plugin(self.app, "vehicle_registry")

        # Invalidera cache om möjligt
        if (
            vehicle_registry
            and hasattr(vehicle_registry, 'vin_registry')
        ):
            if vehicle_registry.vin_registry:
                try:
                    vehicle_registry.vin_registry.invalidate_cache()
                except Exception:
                    pass

        # Hämta data
        vins = self.plugin._get_vins_data()

        if not vins:
            self.stats_label.setText("❌ Ingen VIN-data tillgänglig")
            self._show_no_data()
            return

        # Fyll tabell
        self.year_table.setRowCount(0)
        total = 0

        for year in sorted(vins.keys(), reverse=True):
            if year.startswith('_'):
                continue

            year_data = vins[year]
            if not isinstance(year_data, dict):
                continue

            year_count = sum(
                len(m) for m in year_data.values()
                if isinstance(m, list)
            )
            month_count = len([
                m for m in year_data.keys()
                if not m.startswith('_')
            ])

            total += year_count

            row = self.year_table.rowCount()
            self.year_table.insertRow(row)
            self.year_table.setItem(row, 0, QTableWidgetItem(str(year)))
            self.year_table.setItem(row, 1, QTableWidgetItem(str(year_count)))
            self.year_table.setItem(row, 2, QTableWidgetItem(str(month_count)))

        self.stats_label.setText(f"Totalt: {total} registrerade VIN")

        # Visa sammanfattning i preview
        self._show_summary()

    def _show_no_data(self) -> None:
        """Visa meddelande om ingen data."""
        self.preview.setText(
            "Ingen VIN-data tillgänglig.\n\n"
            "Möjliga orsaker:\n"
            "• vehicle_registry plugin inte laddad\n"
            "• Inga VIN har registrerats ännu\n"
            "• JSON-filen saknas eller är tom\n\n"
            "Registrera några fordon först via TS-fil generering."
        )

    def _show_summary(self) -> None:
        """Visa sammanfattning."""
        stats = self.plugin.get_statistics()

        lines = [
            "REGISTRERADE VIN (År/Månad)",
            "═" * 40,
            "",
            f"Totalt: {stats.get('total_registered', 0)} fordon",
            "",
            "Per år:",
        ]

        for year, count in sorted(
            stats.get("by_year", {}).items(), reverse=True
        ):
            lines.append(f"  📅 {year}: {count} fordon")

        if not stats.get("by_year"):
            lines.append("  (inga data)")

        self.preview.setText("\n".join(lines))

    def _on_year_selected(self) -> None:
        """Visa rapport för valt år."""
        selected = self.year_table.selectedItems()
        if not selected:
            return

        year = selected[0].text()

        try:
            report = self.plugin.generate_year_report(int(year))
            self.preview.setText(report)
        except Exception as e:
            self.preview.setText(f"Fel vid generering: {e}")

    def _create_report(self) -> None:
        """Skapa och spara årsrapport."""
        current_year = datetime.now().year

        year, ok = QInputDialog.getInt(
            self, "Årsrapport", "Ange år:",
            value=current_year, min=2020, max=2100
        )

        if not ok:
            return

        # Generera rapport
        report = self.plugin.generate_year_report(year)

        # Visa i preview
        self.preview.setText(report)

        # Fråga om sparning
        reply = QMessageBox.question(
            self, "Spara rapport",
            f"Vill du spara rapporten för {year}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Spara rapport",
                f"Arsrapport_{year}.txt",
                "Text (*.txt)"
            )

            if filepath:
                try:
                    Path(filepath).write_text(report, encoding="utf-8")
                    QMessageBox.information(
                        self, "Sparad",
                        f"Rapport sparad:\n{filepath}"
                    )
                except Exception as e:
                    QMessageBox.critical(
                        self, "Fel",
                        f"Kunde inte spara:\n{e}"
                    )

    def _get_selected_year(self) -> Optional[int]:
        """Hämta valt år eller visa meddelande."""
        selected = self.year_table.selectedItems()
        if not selected:
            QMessageBox.information(self, "Info", "Välj ett år först")
            return None
        return int(selected[0].text())

    def _export_csv(self) -> None:
        """Exportera till CSV."""
        year = self._get_selected_year()
        if year is None:
            return

        filepath = self.plugin.export_to_csv(year)

        if filepath:
            QMessageBox.information(
                self, "Export klar",
                f"CSV exporterad:\n{filepath}"
            )
        else:
            QMessageBox.warning(self, "Fel", "Kunde inte exportera CSV")

    def _export_excel(self) -> None:
        """Exportera till Excel."""
        year = self._get_selected_year()
        if year is None:
            return

        filepath = self.plugin.export_to_excel(year)

        if filepath:
            QMessageBox.information(
                self, "Export klar",
                f"Excel exporterad:\n{filepath}"
            )
        else:
            QMessageBox.warning(self, "Fel", "Kunde inte exportera Excel")

    def _export_pdf(self) -> None:
        """Exportera till PDF."""
        year = self._get_selected_year()
        if year is None:
            return

        filepath = self.plugin.export_to_pdf(year)

        if filepath:
            QMessageBox.information(
                self, "Export klar",
                f"PDF exporterad:\n{filepath}"
            )
        else:
            QMessageBox.warning(self, "Fel", "Kunde inte exportera PDF")


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "Plugin",
    "HistoryPage",
    "get_plugin",
    "get_copyright_string",
    "MONTHS",
    "EXCEL_AVAILABLE",
    "PDF_AVAILABLE",
    "VERSION",
    "AUTHOR",
]
