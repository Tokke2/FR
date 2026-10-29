# -*- coding: utf-8 -*-
# Fil: plugins/response_viewer/plugin.py
"""
Response Viewer Plugin v2.0.1

Hantering av TAD-svarsfiler från Transportstyrelsen.

NYA FUNKTIONER i v2.0:
- ✅ Dynamiska fönster som anpassar sig efter skärmstorlek
- ✅ 5 skärmkategorier (SMALL → ULTRA)
- ✅ DPI-medveten skalning
- ✅ Responsiva tabeller och knappar
- ✅ Auto-skalande typsnitt

BEFINTLIGA FUNKTIONER:
- Auto-scan av In-mappen
- Import med ett knapptryck
- Historik över importerade filer
- Tabell med alla fordon
- Filter och sök
- Rapport: Ägare, Regnr, VIN
- Export till Excel och PDF
- Utskrift direkt till skrivare

FÖRÄNDRINGAR v2.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2026 ..." i
      docstringen BORTTAGEN — copyright genereras dynamiskt via
      get_copyright_string().
    - FIX (låst regel): ALLA print()-anrop ersatta med module-level
      _log (lazy %s) — WindowManager, TADResponseParser,
      _load_history/_save_history, Plugin.initialize.
    - FIX (PluginBase v3.x-kontrakt): config_schema() tillagd;
      VERSION/AUTHOR-modulkonstanter + get_copyright_string tillagda.
    - FIX (kraschsäkerhet): Plugin.get_dealers_map() anropade
      app.plugin_manager.get_plugin() utan guard — AttributeError om
      plugin_manager saknas. Nu get_plugin_safe-mönster (app.get_plugin
      / plugin_loader / getattr).
    - FIX (kraschsäkerhet): Plugin._setup_paths() — app.config kan
      vara None eller sakna .get; js_data_dir kunde vara Path eller
      str. Nu guard + Path()-konvertering.
    - FIX (PySide6-enums, full form): Qt.AlignCenter ->
      Qt.AlignmentFlag.AlignCenter; QHeaderView.Interactive ->
      QHeaderView.ResizeMode.Interactive; QAbstractItemView.SelectRows
      -> SelectionBehavior.SelectRows; QMessageBox.Yes/No ->
      StandardButton.Yes/No; QPrinter(QPrinter.HighResolution) ->
      QPrinter(QPrinter.PrinterMode.HighResolution);
      QPrintDialog.Accepted -> QPrintDialog.DialogCode.Accepted.
    - FIX (städning): oanvända importer borttagna (QScreen, QScrollArea,
      QSizePolicy).
    - OBSERVATION (EJ ändrad, inväntar beslut): StyleGenerator/Colors
      bygger på ett EGET hårdkodat färgschema (setStyleSheet) — avviker
      från tema-regeln (setObjectName + ThemeEngine) men är centralt
      för widgetens dynamiska skalning. Migrering till tema-tokens
      kräver beslut.
    - OBSERVATION (EJ ändrad): dubblerade publika alias-metoder
      (setup_ui/create_import_section/import_from_in_folder m.fl.)
      behålls för bakåtkompatibilitet.
    - Övrig logik OFÖRÄNDRAD (WindowManager CONFIGS, TAD-format-
      parsning, StyleGenerator, historik atomisk, export/utskrift).
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QFrame, QComboBox, QLineEdit, QSplitter,
    QAbstractItemView, QDialog, QTextEdit, QGroupBox,
    QApplication,
)
from core.plugin_base import PluginBase


# ══════════════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT / LOGGER
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "2.0.1"
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
        return logging.getLogger("response_viewer")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log = _get_logger()


# ══════════════════════════════════════════════════════════════════════════════
# SKÄRMKATEGORIER OCH KONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

class ScreenCategory(Enum):
    """Skärmstorlek-kategorier"""
    SMALL = "small"       # < 1366px (laptops, äldre skärmar)
    MEDIUM = "medium"     # 1366-1920px (HD)
    LARGE = "large"       # 1920-2560px (Full HD)
    XLARGE = "xlarge"     # 2560-3840px (QHD)
    ULTRA = "ultra"       # > 3840px (4K+)


@dataclass
class ScreenConfig:
    """Konfiguration baserad på skärmstorlek"""
    category: ScreenCategory

    # Typsnitt
    font_size_small: int
    font_size_normal: int
    font_size_large: int
    font_size_header: int
    font_size_title: int
    font_size_icon: int
    font_size_table: int

    # Knappar
    button_padding_x: int
    button_padding_y: int
    button_height: int
    button_height_large: int
    button_border_radius: int

    # Tabeller
    table_row_height: int
    table_header_height: int
    table_column_nr: int
    table_column_orgnr: int
    table_column_name: int
    table_column_regnr: int
    table_column_vin: int
    table_column_fabrikat: int
    table_column_modell: int
    table_column_kategori: int

    # Layout
    padding: int
    margin: int
    spacing: int
    frame_border_radius: int

    # Sidebar/Historik
    sidebar_min_width: int
    sidebar_max_width: int
    history_row_height: int

    # Statistik
    stat_value_size: int
    stat_title_size: int
    stat_padding: int

    # Dialoger
    dialog_width: int
    dialog_height: int
    report_dialog_width: int
    report_dialog_height: int

    # Skalning
    scale_factor: float


# ══════════════════════════════════════════════════════════════════════════════
# WINDOW MANAGER - Dynamiska storlekar
# ══════════════════════════════════════════════════════════════════════════════

class WindowManager:
    """Hanterar dynamiska fönsterstorlekar baserat på skärm"""

    # Konfigurationer per skärmkategori
    CONFIGS = {
        ScreenCategory.SMALL: ScreenConfig(
            category=ScreenCategory.SMALL,
            font_size_small=8,
            font_size_normal=9,
            font_size_large=10,
            font_size_header=11,
            font_size_title=16,
            font_size_icon=12,
            font_size_table=9,
            button_padding_x=10,
            button_padding_y=6,
            button_height=28,
            button_height_large=36,
            button_border_radius=4,
            table_row_height=24,
            table_header_height=28,
            table_column_nr=35,
            table_column_orgnr=80,
            table_column_name=120,
            table_column_regnr=60,
            table_column_vin=130,
            table_column_fabrikat=90,
            table_column_modell=120,
            table_column_kategori=50,
            padding=8,
            margin=8,
            spacing=6,
            frame_border_radius=6,
            sidebar_min_width=280,
            sidebar_max_width=380,
            history_row_height=22,
            stat_value_size=16,
            stat_title_size=9,
            stat_padding=10,
            dialog_width=400,
            dialog_height=300,
            report_dialog_width=850,
            report_dialog_height=550,
            scale_factor=0.75
        ),
        ScreenCategory.MEDIUM: ScreenConfig(
            category=ScreenCategory.MEDIUM,
            font_size_small=9,
            font_size_normal=10,
            font_size_large=11,
            font_size_header=12,
            font_size_title=20,
            font_size_icon=14,
            font_size_table=10,
            button_padding_x=15,
            button_padding_y=8,
            button_height=32,
            button_height_large=42,
            button_border_radius=5,
            table_row_height=28,
            table_header_height=32,
            table_column_nr=40,
            table_column_orgnr=90,
            table_column_name=150,
            table_column_regnr=70,
            table_column_vin=150,
            table_column_fabrikat=110,
            table_column_modell=150,
            table_column_kategori=60,
            padding=10,
            margin=10,
            spacing=8,
            frame_border_radius=7,
            sidebar_min_width=320,
            sidebar_max_width=450,
            history_row_height=26,
            stat_value_size=18,
            stat_title_size=10,
            stat_padding=12,
            dialog_width=480,
            dialog_height=360,
            report_dialog_width=950,
            report_dialog_height=650,
            scale_factor=0.9
        ),
        ScreenCategory.LARGE: ScreenConfig(
            category=ScreenCategory.LARGE,
            font_size_small=10,
            font_size_normal=11,
            font_size_large=12,
            font_size_header=14,
            font_size_title=24,
            font_size_icon=16,
            font_size_table=11,
            button_padding_x=20,
            button_padding_y=10,
            button_height=36,
            button_height_large=48,
            button_border_radius=6,
            table_row_height=32,
            table_header_height=38,
            table_column_nr=45,
            table_column_orgnr=100,
            table_column_name=180,
            table_column_regnr=80,
            table_column_vin=170,
            table_column_fabrikat=130,
            table_column_modell=180,
            table_column_kategori=70,
            padding=12,
            margin=12,
            spacing=10,
            frame_border_radius=8,
            sidebar_min_width=350,
            sidebar_max_width=500,
            history_row_height=30,
            stat_value_size=20,
            stat_title_size=11,
            stat_padding=15,
            dialog_width=550,
            dialog_height=420,
            report_dialog_width=1100,
            report_dialog_height=750,
            scale_factor=1.0
        ),
        ScreenCategory.XLARGE: ScreenConfig(
            category=ScreenCategory.XLARGE,
            font_size_small=11,
            font_size_normal=12,
            font_size_large=14,
            font_size_header=16,
            font_size_title=28,
            font_size_icon=18,
            font_size_table=12,
            button_padding_x=25,
            button_padding_y=12,
            button_height=40,
            button_height_large=54,
            button_border_radius=7,
            table_row_height=36,
            table_header_height=44,
            table_column_nr=50,
            table_column_orgnr=110,
            table_column_name=220,
            table_column_regnr=90,
            table_column_vin=190,
            table_column_fabrikat=150,
            table_column_modell=220,
            table_column_kategori=80,
            padding=15,
            margin=15,
            spacing=12,
            frame_border_radius=9,
            sidebar_min_width=400,
            sidebar_max_width=550,
            history_row_height=34,
            stat_value_size=24,
            stat_title_size=12,
            stat_padding=18,
            dialog_width=650,
            dialog_height=500,
            report_dialog_width=1300,
            report_dialog_height=900,
            scale_factor=1.15
        ),
        ScreenCategory.ULTRA: ScreenConfig(
            category=ScreenCategory.ULTRA,
            font_size_small=12,
            font_size_normal=14,
            font_size_large=16,
            font_size_header=18,
            font_size_title=32,
            font_size_icon=20,
            font_size_table=13,
            button_padding_x=30,
            button_padding_y=14,
            button_height=46,
            button_height_large=62,
            button_border_radius=8,
            table_row_height=42,
            table_header_height=50,
            table_column_nr=55,
            table_column_orgnr=130,
            table_column_name=260,
            table_column_regnr=100,
            table_column_vin=220,
            table_column_fabrikat=180,
            table_column_modell=260,
            table_column_kategori=90,
            padding=18,
            margin=18,
            spacing=15,
            frame_border_radius=10,
            sidebar_min_width=450,
            sidebar_max_width=650,
            history_row_height=40,
            stat_value_size=28,
            stat_title_size=14,
            stat_padding=22,
            dialog_width=800,
            dialog_height=600,
            report_dialog_width=1500,
            report_dialog_height=1000,
            scale_factor=1.35
        )
    }

    def __init__(self, widget: Optional[QWidget] = None):
        self.widget = widget
        self._detect_screen()
        self.config = self._get_config_for_screen()

        _log.info(
            "Skärm: %dx%d (DPI: %.2f) → %s",
            self.screen_width,
            self.screen_height,
            self.dpi_scale,
            self.config.category.value,
        )

    def _detect_screen(self):
        """Detektera skärmstorlek och DPI"""
        try:
            app = QApplication.instance()
            if app:
                screen = app.primaryScreen()
                if screen:
                    geometry = screen.availableGeometry()
                    self.screen_width = geometry.width()
                    self.screen_height = geometry.height()
                    self.dpi_scale = screen.devicePixelRatio()
                else:
                    self._set_defaults()
            else:
                self._set_defaults()
        except Exception:
            self._set_defaults()

        # Normalisera DPI
        self.dpi_scale = max(0.5, min(3.0, self.dpi_scale))

    def _set_defaults(self):
        """Sätt standardvärden"""
        self.screen_width = 1920
        self.screen_height = 1080
        self.dpi_scale = 1.0

    def _get_config_for_screen(self) -> ScreenConfig:
        """Hämta konfiguration baserat på skärmstorlek"""
        # Justera för DPI
        effective_width = self.screen_width / self.dpi_scale

        if effective_width < 1366:
            return self.CONFIGS[ScreenCategory.SMALL]
        elif effective_width < 1920:
            return self.CONFIGS[ScreenCategory.MEDIUM]
        elif effective_width < 2560:
            return self.CONFIGS[ScreenCategory.LARGE]
        elif effective_width < 3840:
            return self.CONFIGS[ScreenCategory.XLARGE]
        else:
            return self.CONFIGS[ScreenCategory.ULTRA]

    # === FONT HELPERS ===

    def get_font(self, style: str = 'normal', bold: bool = False) -> QFont:
        """Hämta font baserat på stil"""
        cfg = self.config

        sizes = {
            'small': cfg.font_size_small,
            'normal': cfg.font_size_normal,
            'large': cfg.font_size_large,
            'header': cfg.font_size_header,
            'title': cfg.font_size_title,
            'icon': cfg.font_size_icon,
            'table': cfg.font_size_table,
            'stat_value': cfg.stat_value_size,
            'stat_title': cfg.stat_title_size,
        }

        size = sizes.get(style, cfg.font_size_normal)
        font = QFont("Segoe UI", size)

        if bold or style in ['header', 'title', 'stat_value']:
            font.setBold(True)

        return font

    def get_monospace_font(self, style: str = 'normal') -> QFont:
        """Hämta monospace font"""
        cfg = self.config

        sizes = {
            'small': cfg.font_size_small,
            'normal': cfg.font_size_normal,
            'large': cfg.font_size_large,
            'table': cfg.font_size_table,
        }

        size = sizes.get(style, cfg.font_size_normal)
        return QFont("Consolas", size)

    # === DIMENSION HELPERS ===

    def scale(self, value: int) -> int:
        """Skala ett värde baserat på skärmstorlek"""
        return max(1, int(value * self.config.scale_factor))

    def get_padding(self) -> int:
        return self.config.padding

    def get_margin(self) -> int:
        return self.config.margin

    def get_spacing(self) -> int:
        return self.config.spacing

    def get_button_height(self, large: bool = False) -> int:
        return (
            self.config.button_height_large
            if large
            else self.config.button_height
        )

    def get_table_column_widths(self) -> Dict[str, int]:
        """Hämta kolumnbredder för huvudtabellen"""
        cfg = self.config
        return {
            'nr': cfg.table_column_nr,
            'orgnr': cfg.table_column_orgnr,
            'name': cfg.table_column_name,
            'regnr': cfg.table_column_regnr,
            'vin': cfg.table_column_vin,
            'fabrikat': cfg.table_column_fabrikat,
            'modell': cfg.table_column_modell,
            'kategori': cfg.table_column_kategori,
        }

    def get_dialog_size(self) -> Tuple[int, int]:
        return (self.config.dialog_width, self.config.dialog_height)

    def get_report_dialog_size(self) -> Tuple[int, int]:
        return (
            self.config.report_dialog_width,
            self.config.report_dialog_height,
        )


# ══════════════════════════════════════════════════════════════════════════════
# FÄRGKONSTANTER (OBS: eget schema — tema-migrering inväntar beslut)
# ══════════════════════════════════════════════════════════════════════════════

class Colors:
    """Centraliserat färgschema"""
    # Bakgrund
    BG_DARK = '#1e1e1e'
    BG_MEDIUM = '#252526'
    BG_LIGHT = '#2d2d2d'
    BG_FRAME = '#252830'
    BG_TABLE = '#2b2b2b'
    BG_TABLE_ALT = '#323232'
    BG_INPUT = '#2b2b2b'

    # Knappar
    BTN_PRIMARY = '#007bff'
    BTN_PRIMARY_HOVER = '#0056b3'
    BTN_SUCCESS = '#28a745'
    BTN_SUCCESS_HOVER = '#218838'
    BTN_INFO = '#17a2b8'
    BTN_INFO_HOVER = '#138496'
    BTN_DANGER = '#dc3545'
    BTN_DANGER_HOVER = '#c82333'
    BTN_SECONDARY = '#6c757d'
    BTN_SECONDARY_HOVER = '#5a6268'
    BTN_DARK = '#3a3f44'
    BTN_DARK_HOVER = '#4a4f54'

    # Text
    FG_WHITE = '#ffffff'
    FG_NORMAL = '#d4d4d4'
    FG_DIM = '#888888'
    FG_SUCCESS = '#28a745'
    FG_WARNING = '#ffc107'
    FG_DANGER = '#dc3545'
    FG_INFO = '#17a2b8'

    # Ramar
    BORDER_NORMAL = '#3a3f44'
    BORDER_DARK = '#444444'
    BORDER_TABLE = '#3a3a3a'

    # Selektion
    SELECTION = '#007bff'


# ══════════════════════════════════════════════════════════════════════════════
# KONSTANTER - TAD FORMAT
# ══════════════════════════════════════════════════════════════════════════════

POSTTYP_IDENTITET = "28"
POSTTYP_FORETAG = "11"
POSTTYP_FORDON = "45"
POSTTYP_SLUT = "99"

# Fältpositioner för FORDONSPOST (45) - TAD-format
VEHICLE_FIELDS = {
    "lopnr": (0, 4),
    "posttyp": (4, 6),
    "agare_orgnr": (6, 16),
    "regnr": (16, 22),
    "regnr_extra": (22, 26),
    "felkod": (106, 114),
    "fabrikat": (114, 134),
    "typ_kod": (134, 154),
    "variant": (154, 174),
    "version": (174, 194),
    "modell": (194, 218),
    "kategori": (218, 226),
    "vin": (228, 245),
    "typgodkannande": (245, 270),
    "datum_forsta_reg": (270, 278),
    "datum_reg": (278, 286),
}

IDENTITY_FIELDS = {
    "lopnr": (0, 4),
    "subtyp": (4, 6),
    "orgnr": (6, 16),
    "filid": (52, 64),
    "posttyp": (78, 80),
}

COMPANY_FIELDS = {
    "lopnr": (0, 4),
    "posttyp": (4, 6),
    "orgnr": (6, 16),
    "foretag": (16, 56),
    "kontakt": (56, 96),
    "status": (96, 110),
}


# ══════════════════════════════════════════════════════════════════════════════
# DATAKLASSER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class VehicleRecord:
    """Representerar ett fordon från svarsfil"""
    lopnr: int = 0
    vin: str = ""
    regnr: str = ""
    agare_orgnr: str = ""
    agare_namn: str = ""
    fabrikat: str = ""
    modell: str = ""
    kategori: str = ""
    typgodkannande: str = ""
    datum_reg: str = ""
    felkod: str = ""
    feltext: str = ""
    fil_id: str = ""
    raw_line: str = ""

    @property
    def has_regnr(self) -> bool:
        """Har tilldelat registreringsnummer"""
        regnr = self.regnr.strip()
        if not regnr:
            return False
        if regnr.replace("0", "") == "":
            return False
        return bool(re.match(r'^[A-Z]{3}\d{2}[A-Z0-9]?$', regnr))

    @property
    def is_ok(self) -> bool:
        return self.has_regnr and (not self.felkod or self.felkod == "00000000")

    @property
    def has_error(self) -> bool:
        return bool(self.felkod and self.felkod != "00000000")

    @property
    def status_display(self) -> str:
        if self.has_regnr:
            return f"✅ {self.regnr}"
        elif self.has_error:
            return f"❌ Fel: {self.felkod}"
        else:
            return "⏳ Väntande"

    @property
    def status_simple(self) -> str:
        if self.has_regnr:
            return "Registrerad"
        elif self.has_error:
            return "Fel"
        else:
            return "Väntande"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lopnr": self.lopnr,
            "vin": self.vin,
            "regnr": self.regnr,
            "agare_orgnr": self.agare_orgnr,
            "agare_namn": self.agare_namn,
            "fabrikat": self.fabrikat,
            "modell": self.modell,
            "kategori": self.kategori,
            "typgodkannande": self.typgodkannande,
            "datum_reg": self.datum_reg,
            "felkod": self.felkod,
            "feltext": self.feltext,
            "fil_id": self.fil_id,
        }


@dataclass
class ResponseFile:
    """Representerar en importerad svarsfil"""
    filename: str
    filepath: str
    imported_at: str
    file_id: str = ""
    orgnr: str = ""
    foretag: str = ""
    kontakt: str = ""
    total_records: int = 0
    successful: int = 0
    failed: int = 0
    pending: int = 0
    records: List[VehicleRecord] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_records == 0:
            return 0.0
        return round(self.successful / self.total_records * 100, 1)

    @property
    def display_name(self) -> str:
        if len(self.filename) > 18:
            return self.filename[:15] + "..."
        return self.filename


# ══════════════════════════════════════════════════════════════════════════════
# PARSER FÖR TAD-FORMAT
# ══════════════════════════════════════════════════════════════════════════════

class TADResponseParser:
    """Parser för TAD svarsfiler från Transportstyrelsen"""

    def __init__(self, dealers_map: Optional[Dict[str, str]] = None):
        self.dealers_map = dealers_map or {}

    def parse_file(self, filepath: Path) -> ResponseFile:
        """Parsar en TAD svarsfil"""
        response = ResponseFile(
            filename=filepath.name,
            filepath=str(filepath),
            imported_at=datetime.now().isoformat(timespec="seconds")
        )

        if not filepath.exists():
            return response

        try:
            content = self._read_file(filepath)
            if not content:
                return response

            lines = content.split('\n')

            for line in lines:
                line = line.rstrip('\r\n')

                if len(line) < 6:
                    continue

                lopnr = line[0:4]
                posttyp_area = line[4:6]

                if len(line) >= 80 and line[78:80] == POSTTYP_IDENTITET:
                    self._parse_identity(line, response)
                elif posttyp_area == POSTTYP_FORETAG:
                    self._parse_company(line, response)
                elif posttyp_area == POSTTYP_FORDON:
                    record = self._parse_vehicle(line, response.file_id)
                    if record:
                        response.records.append(record)
                        if record.has_regnr:
                            response.successful += 1
                        elif record.has_error:
                            response.failed += 1
                        else:
                            response.pending += 1

            response.total_records = len(response.records)

        except Exception as e:
            _log.error("Parser-fel för %s: %s", filepath.name, e)
            _log.debug("Parser-fel detaljerat", exc_info=True)

        return response

    def _read_file(self, filepath: Path) -> str:
        encodings = ['utf-8', 'utf-8-sig', 'iso-8859-1', 'cp1252', 'latin-1']

        for encoding in encodings:
            try:
                return filepath.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue

        try:
            return filepath.read_bytes().decode('utf-8', errors='replace')
        except Exception:
            return ""

    def read_file(self, filepath: Path) -> str:
        return self._read_file(filepath)

    def _extract(self, line: str, start: int, end: int) -> str:
        if len(line) >= end:
            return line[start:end].strip()
        elif len(line) > start:
            return line[start:].strip()
        return ""

    def _parse_identity(self, line: str, response: ResponseFile) -> None:
        response.orgnr = self._extract(line, *IDENTITY_FIELDS["orgnr"])
        response.file_id = self._extract(line, *IDENTITY_FIELDS["filid"])

    def parse_identity(self, line: str, response: ResponseFile) -> None:
        self._parse_identity(line, response)

    def _parse_company(self, line: str, response: ResponseFile) -> None:
        response.foretag = self._extract(line, *COMPANY_FIELDS["foretag"])
        response.kontakt = self._extract(line, *COMPANY_FIELDS["kontakt"])

    def parse_company(self, line: str, response: ResponseFile) -> None:
        self._parse_company(line, response)

    def _parse_vehicle(self, line: str, file_id: str) -> Optional[VehicleRecord]:
        try:
            record = VehicleRecord()
            record.raw_line = line
            record.fil_id = file_id

            lopnr_str = self._extract(line, *VEHICLE_FIELDS["lopnr"])
            record.lopnr = int(lopnr_str) if lopnr_str.isdigit() else 0

            record.agare_orgnr = self._extract(
                line, *VEHICLE_FIELDS["agare_orgnr"]
            )
            record.regnr = self._extract(line, *VEHICLE_FIELDS["regnr"])
            record.felkod = self._extract(line, *VEHICLE_FIELDS["felkod"])
            record.fabrikat = self._extract(line, *VEHICLE_FIELDS["fabrikat"])
            record.modell = self._extract(line, *VEHICLE_FIELDS["modell"])
            record.kategori = self._extract(line, *VEHICLE_FIELDS["kategori"])
            record.vin = self._extract(line, *VEHICLE_FIELDS["vin"])
            record.typgodkannande = self._extract(
                line, *VEHICLE_FIELDS["typgodkannande"]
            )
            record.datum_reg = self._extract(
                line, *VEHICLE_FIELDS["datum_forsta_reg"]
            )

            if record.datum_reg and len(record.datum_reg) == 8:
                record.datum_reg = (
                    f"{record.datum_reg[:4]}-{record.datum_reg[4:6]}-"
                    f"{record.datum_reg[6:8]}"
                )

            if record.agare_orgnr and record.agare_orgnr in self.dealers_map:
                record.agare_namn = self.dealers_map[record.agare_orgnr]

            if not record.vin or len(record.vin) < 10:
                vin_match = re.search(r'[A-Z0-9]{17}', line)
                if vin_match:
                    record.vin = vin_match.group(0)
                else:
                    return None

            return record

        except Exception as e:
            _log.warning("Kunde inte parsa fordonspost: %s", e)
            return None

    def parse_vehicle(self, line: str, file_id: str) -> Optional[VehicleRecord]:
        return self._parse_vehicle(line, file_id)


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK STYLES GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class StyleGenerator:
    """Genererar dynamiska CSS-stilar baserat på WindowManager"""

    def __init__(self, wm: WindowManager):
        self.wm = wm
        self.cfg = wm.config

    def get_frame_style(self, bg: str = Colors.BG_FRAME) -> str:
        return f"""
            QFrame {{
                background: {bg};
                border: 1px solid {Colors.BORDER_NORMAL};
                border-radius: {self.cfg.frame_border_radius}px;
            }}
        """

    def get_button_style(self, bg: str, hover: str, large: bool = False) -> str:
        height = (
            self.cfg.button_height_large
            if large
            else self.cfg.button_height
        )
        font_size = (
            self.cfg.font_size_large
            if large
            else self.cfg.font_size_normal
        )

        return f"""
            QPushButton {{
                background: {bg};
                color: {Colors.FG_WHITE};
                border: none;
                padding: {self.cfg.button_padding_y}px {self.cfg.button_padding_x}px;
                border-radius: {self.cfg.button_border_radius}px;
                font-size: {font_size}px;
                font-weight: bold;
                min-height: {height}px;
            }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:pressed {{ background: {hover}; }}
        """

    def get_primary_button(self, large: bool = False) -> str:
        return self.get_button_style(
            Colors.BTN_PRIMARY, Colors.BTN_PRIMARY_HOVER, large
        )

    def get_success_button(self, large: bool = False) -> str:
        return self.get_button_style(
            Colors.BTN_SUCCESS, Colors.BTN_SUCCESS_HOVER, large
        )

    def get_info_button(self, large: bool = False) -> str:
        return self.get_button_style(
            Colors.BTN_INFO, Colors.BTN_INFO_HOVER, large
        )

    def get_danger_button(self, large: bool = False) -> str:
        return self.get_button_style(
            Colors.BTN_DANGER, Colors.BTN_DANGER_HOVER, large
        )

    def get_secondary_button(self, large: bool = False) -> str:
        return self.get_button_style(
            Colors.BTN_SECONDARY, Colors.BTN_SECONDARY_HOVER, large
        )

    def get_dark_button(self, large: bool = False) -> str:
        return self.get_button_style(
            Colors.BTN_DARK, Colors.BTN_DARK_HOVER, large
        )

    def get_table_style(self) -> str:
        return f"""
            QTableWidget {{
                background: {Colors.BG_TABLE};
                color: {Colors.FG_WHITE};
                border: 1px solid {Colors.BORDER_DARK};
                gridline-color: {Colors.BORDER_TABLE};
                alternate-background-color: {Colors.BG_TABLE_ALT};
                font-size: {self.cfg.font_size_table}px;
            }}
            QHeaderView::section {{
                background: {Colors.BTN_DARK};
                color: {Colors.FG_WHITE};
                padding: {self.cfg.padding}px;
                font-weight: bold;
                font-size: {self.cfg.font_size_table}px;
                border: none;
            }}
            QTableWidget::item:selected {{
                background: {Colors.SELECTION};
            }}
        """

    def get_input_style(self) -> str:
        return f"""
            QLineEdit, QComboBox {{
                background: {Colors.BG_INPUT};
                color: {Colors.FG_WHITE};
                border: 1px solid {Colors.BORDER_NORMAL};
                padding: {self.cfg.padding // 2}px;
                border-radius: {self.cfg.button_border_radius}px;
                font-size: {self.cfg.font_size_normal}px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
        """

    def get_label_style(self, style: str = 'normal') -> str:
        sizes = {
            'small': self.cfg.font_size_small,
            'normal': self.cfg.font_size_normal,
            'large': self.cfg.font_size_large,
            'header': self.cfg.font_size_header,
            'title': self.cfg.font_size_title,
        }
        size = sizes.get(style, self.cfg.font_size_normal)
        weight = 'bold' if style in ['header', 'title'] else 'normal'

        return (
            f"font-size: {size}px; font-weight: {weight}; "
            f"color: {Colors.FG_WHITE};"
        )


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMISK DIALOG BASKLASS
# ══════════════════════════════════════════════════════════════════════════════

class DynamicDialog(QDialog):
    """Bas för dynamiskt skalade dialoger"""

    def __init__(
        self,
        parent: QWidget,
        wm: WindowManager,
        title: str = "",
    ):
        super().__init__(parent)
        self.wm = wm
        self.styles = StyleGenerator(wm)

        self.setWindowTitle(title)
        self.setStyleSheet(f"background: {Colors.BG_DARK};")

        # Standardstorlek
        width, height = wm.get_dialog_size()
        self.resize(width, height)

        # Centrera
        self._center_on_screen()

    def _center_on_screen(self):
        self.center_on_screen()

    def center_on_screen(self):
        """Centrera dialogen på skärmen"""
        screen = QApplication.primaryScreen()
        if screen:
            geometry = screen.availableGeometry()
            x = (geometry.width() - self.width()) // 2
            y = (geometry.height() - self.height()) // 2
            self.move(x, y)


# ══════════════════════════════════════════════════════════════════════════════
# GUI WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class ResponseViewerWidget(QWidget):
    """Huvudwidget för svarsfil-visning med dynamisk skalning"""

    file_imported = Signal(str)

    def __init__(self, plugin: "Plugin"):
        super().__init__()
        self.plugin = plugin

        # Window Manager
        self.wm = WindowManager(self)
        self.styles = StyleGenerator(self.wm)
        self.cfg = self.wm.config

        # Data
        self._current_response: Optional[ResponseFile] = None
        self._history: List[ResponseFile] = []
        self._all_records: List[VehicleRecord] = []

        self._setup_ui()
        self._load_history()

        # Auto-scan efter 1 sekund
        QTimer.singleShot(1000, self._check_in_folder)

    def _setup_ui(self) -> None:
        """Bygg UI med dynamisk skalning"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            self.cfg.margin, self.cfg.margin,
            self.cfg.margin, self.cfg.margin
        )
        layout.setSpacing(self.cfg.spacing)

        # === HEADER ===
        header = QLabel("📋 Svarsfiler från Transportstyrelsen")
        header.setStyleSheet(self.styles.get_label_style('title'))
        layout.addWidget(header)

        # === IMPORT FRAME ===
        self._create_import_section(layout)

        # === RAPPORT FRAME ===
        self._create_report_section(layout)

        # === STATISTIK ===
        self._create_stats_section(layout)

        # === SPLITTER: HISTORIK + TABELL ===
        self._create_main_content(layout)

    def setup_ui(self) -> None:
        self._setup_ui()

    def _create_import_section(self, parent_layout: QVBoxLayout) -> None:
        """Skapa import-sektionen"""
        import_frame = QFrame()
        import_frame.setStyleSheet(self.styles.get_frame_style())
        import_layout = QHBoxLayout(import_frame)
        import_layout.setContentsMargins(
            self.cfg.padding, self.cfg.padding,
            self.cfg.padding, self.cfg.padding
        )

        # Huvudknapp: Importera
        self._btn_scan = QPushButton("📥 IMPORTERA FRÅN IN-MAPPEN")
        self._btn_scan.setStyleSheet(self.styles.get_primary_button(large=True))
        self._btn_scan.setMinimumWidth(self.wm.scale(280))
        self._btn_scan.clicked.connect(self._import_from_in_folder)
        import_layout.addWidget(self._btn_scan)

        # Bläddra-knapp
        self._btn_browse = QPushButton("📂 Välj fil...")
        self._btn_browse.setStyleSheet(self.styles.get_dark_button())
        self._btn_browse.clicked.connect(self._browse_file)
        import_layout.addWidget(self._btn_browse)

        import_layout.addStretch()

        # In-mapp info
        in_path = self.plugin.get_in_path()
        self._in_folder_label = QLabel(f"📁 In-mapp: {in_path}")
        self._in_folder_label.setStyleSheet(
            f"color: {Colors.FG_DIM}; font-size: {self.cfg.font_size_small}px;"
        )
        import_layout.addWidget(self._in_folder_label)

        parent_layout.addWidget(import_frame)

    def create_import_section(self, parent_layout: QVBoxLayout) -> None:
        self._create_import_section(parent_layout)

    def _create_report_section(self, parent_layout: QVBoxLayout) -> None:
        """Skapa rapport-sektionen"""
        report_frame = QFrame()
        report_frame.setStyleSheet(self.styles.get_frame_style(Colors.BG_MEDIUM))
        report_layout = QHBoxLayout(report_frame)
        report_layout.setContentsMargins(
            self.cfg.padding, self.cfg.padding // 2,
            self.cfg.padding, self.cfg.padding // 2
        )

        # Rapport-knapp
        self._btn_print_report = QPushButton(
            "🖨️ SKRIV UT RAPPORT (Ägare, Regnr, VIN)"
        )
        self._btn_print_report.setStyleSheet(
            self.styles.get_success_button(large=True)
        )
        self._btn_print_report.clicked.connect(self._print_report)
        report_layout.addWidget(self._btn_print_report)

        # Excel
        self._btn_export_excel = QPushButton("📊 Excel")
        self._btn_export_excel.setStyleSheet(self.styles.get_info_button())
        self._btn_export_excel.clicked.connect(self._export_excel)
        report_layout.addWidget(self._btn_export_excel)

        # PDF
        self._btn_export_pdf = QPushButton("📄 PDF")
        self._btn_export_pdf.setStyleSheet(self.styles.get_danger_button())
        self._btn_export_pdf.clicked.connect(self._export_pdf)
        report_layout.addWidget(self._btn_export_pdf)

        report_layout.addSpacing(self.wm.scale(30))

        # Filter
        filter_label = QLabel("Visa:")
        filter_label.setStyleSheet(self.styles.get_label_style())
        report_layout.addWidget(filter_label)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(
            ["Alla", "Endast med regnr", "Utan regnr", "Fel"]
        )
        self._filter_combo.currentIndexChanged.connect(self._apply_filter)
        self._filter_combo.setFixedWidth(self.wm.scale(140))
        self._filter_combo.setStyleSheet(self.styles.get_input_style())
        report_layout.addWidget(self._filter_combo)

        # Sök
        search_label = QLabel("Sök:")
        search_label.setStyleSheet(self.styles.get_label_style())
        report_layout.addWidget(search_label)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("VIN, regnr, ägare, modell...")
        self._search_input.setFixedWidth(self.wm.scale(200))
        self._search_input.textChanged.connect(self._apply_filter)
        self._search_input.setStyleSheet(self.styles.get_input_style())
        report_layout.addWidget(self._search_input)

        report_layout.addStretch()

        # Rensa
        self._btn_clear = QPushButton("🗑️ Rensa")
        self._btn_clear.setStyleSheet(self.styles.get_secondary_button())
        self._btn_clear.clicked.connect(self._clear_history)
        report_layout.addWidget(self._btn_clear)

        parent_layout.addWidget(report_frame)

    def create_report_section(self, parent_layout: QVBoxLayout) -> None:
        self._create_report_section(parent_layout)

    def _create_stats_section(self, parent_layout: QVBoxLayout) -> None:
        """Skapa statistik-sektionen"""
        stats_frame = QFrame()
        stats_frame.setStyleSheet(self.styles.get_frame_style(Colors.BG_LIGHT))
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(
            self.cfg.stat_padding, self.cfg.stat_padding // 2,
            self.cfg.stat_padding, self.cfg.stat_padding // 2
        )

        self._stats_files = self._create_stat_widget(
            "Filer", "0", Colors.FG_INFO
        )
        self._stats_total = self._create_stat_widget(
            "Fordon totalt", "0", Colors.FG_WHITE
        )
        self._stats_regnr = self._create_stat_widget(
            "Med regnr", "0", Colors.FG_SUCCESS
        )
        self._stats_no_regnr = self._create_stat_widget(
            "Utan regnr", "0", Colors.FG_WARNING
        )
        self._stats_fail = self._create_stat_widget(
            "Fel", "0", Colors.FG_DANGER
        )
        self._stats_rate = self._create_stat_widget(
            "Registreringsgrad", "0%", Colors.FG_DIM
        )

        stats_layout.addWidget(self._stats_files)
        stats_layout.addWidget(self._stats_total)
        stats_layout.addStretch()
        stats_layout.addWidget(self._stats_regnr)
        stats_layout.addWidget(self._stats_no_regnr)
        stats_layout.addWidget(self._stats_fail)
        stats_layout.addWidget(self._stats_rate)

        parent_layout.addWidget(stats_frame)

    def create_stats_section(self, parent_layout: QVBoxLayout) -> None:
        self._create_stats_section(parent_layout)

    def _create_stat_widget(
        self, title: str, value: str, color: str
    ) -> QWidget:
        """Skapar statistik-widget med dynamisk storlek"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(
            self.cfg.stat_padding, self.cfg.padding // 2,
            self.cfg.stat_padding, self.cfg.padding // 2
        )
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {Colors.FG_DIM}; font-size: {self.cfg.stat_title_size}px;"
        )
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        value_label = QLabel(value)
        value_label.setStyleSheet(
            f"color: {color}; font-size: {self.cfg.stat_value_size}px; "
            f"font-weight: bold;"
        )
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setObjectName("value")

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return widget

    def create_stat_widget(self, title: str, value: str, color: str) -> QWidget:
        return self._create_stat_widget(title, value, color)

    def _update_stat(self, widget: QWidget, value: str) -> None:
        """Uppdaterar statistik-värde"""
        label = widget.findChild(QLabel, "value")
        if label:
            label.setText(value)

    def update_stat(self, widget: QWidget, value: str) -> None:
        self._update_stat(widget, value)

    def _create_main_content(self, parent_layout: QVBoxLayout) -> None:
        """Skapa huvudinnehåll med splitter"""
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # === HISTORIK (VÄNSTER) ===
        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)

        history_header = QLabel("📚 Importerade filer")
        history_header.setStyleSheet(
            f"font-weight: bold; font-size: {self.cfg.font_size_header}px; "
            f"padding: {self.cfg.padding}px; color: {Colors.FG_WHITE};"
        )
        history_layout.addWidget(history_header)

        self._history_table = QTableWidget()
        self._history_table.setColumnCount(5)
        self._history_table.setHorizontalHeaderLabels(
            ["Fil", "FilID", "Datum", "Antal", "Regnr"]
        )
        self._history_table.horizontalHeader().setStretchLastSection(True)
        self._history_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._history_table.setMaximumWidth(self.cfg.sidebar_max_width)
        self._history_table.setMinimumWidth(self.cfg.sidebar_min_width)
        self._history_table.itemClicked.connect(self._on_history_selected)
        self._history_table.setStyleSheet(self.styles.get_table_style())

        # Kolumnbredder
        self._history_table.setColumnWidth(0, self.wm.scale(90))
        self._history_table.setColumnWidth(1, self.wm.scale(80))
        self._history_table.setColumnWidth(2, self.wm.scale(75))
        self._history_table.setColumnWidth(3, self.wm.scale(45))

        history_layout.addWidget(self._history_table)
        splitter.addWidget(history_widget)

        # === HUVUDTABELL (HÖGER) ===
        table_widget = QWidget()
        table_layout = QVBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)

        table_header = QLabel("🚗 Fordon")
        table_header.setStyleSheet(
            f"font-weight: bold; font-size: {self.cfg.font_size_header}px; "
            f"padding: {self.cfg.padding}px; color: {Colors.FG_WHITE};"
        )
        table_layout.addWidget(table_header)

        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels([
            "Nr", "ÄGARE (ORGNR)", "ÄGARE (NAMN)", "REGNR", "VIN",
            "FABRIKAT", "MODELL", "KATEGORI", "STATUS"
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.setStyleSheet(self.styles.get_table_style())

        # Kolumnbredder
        widths = self.wm.get_table_column_widths()
        self._table.setColumnWidth(0, widths['nr'])
        self._table.setColumnWidth(1, widths['orgnr'])
        self._table.setColumnWidth(2, widths['name'])
        self._table.setColumnWidth(3, widths['regnr'])
        self._table.setColumnWidth(4, widths['vin'])
        self._table.setColumnWidth(5, widths['fabrikat'])
        self._table.setColumnWidth(6, widths['modell'])
        self._table.setColumnWidth(7, widths['kategori'])

        table_layout.addWidget(self._table)
        splitter.addWidget(table_widget)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        parent_layout.addWidget(splitter)

    def create_main_content(self, parent_layout: QVBoxLayout) -> None:
        self._create_main_content(parent_layout)

    # ═══════════════════════════════════════════════════════════════════════════
    # IMPORT FUNKTIONER
    # ═══════════════════════════════════════════════════════════════════════════

    def _check_in_folder(self) -> None:
        """Kontrollerar om det finns filer i In-mappen"""
        in_path = self.plugin.get_in_path()
        files = list(in_path.glob("tad*")) + list(in_path.glob("TAD*"))

        count = len(files)
        if count > 0:
            self._btn_scan.setText(
                f"📥 IMPORTERA FRÅN IN-MAPPEN ({count} filer)"
            )
            self._btn_scan.setStyleSheet(
                self.styles.get_success_button(large=True)
            )
        else:
            self._btn_scan.setText("📥 IMPORTERA FRÅN IN-MAPPEN")
            self._btn_scan.setStyleSheet(
                self.styles.get_primary_button(large=True)
            )

    def check_in_folder(self) -> None:
        self._check_in_folder()

    def _import_from_in_folder(self) -> None:
        """Importera alla TAD-filer från In-mappen"""
        in_path = self.plugin.get_in_path()
        files = list(in_path.glob("tad*")) + list(in_path.glob("TAD*"))

        if not files:
            QMessageBox.information(
                self, "Inga filer",
                f"Inga TAD-filer hittades i:\n\n{in_path}\n\n"
                f"Lägg svarsfiler (t.ex. tad28r628) i In-mappen."
            )
            return

        dealers_map = self.plugin.get_dealers_map()
        parser = TADResponseParser(dealers_map)

        imported = 0
        total_records = 0
        total_regnr = 0
        total_fail = 0

        for filepath in files:
            response = parser.parse_file(filepath)
            if response.total_records > 0:
                existing = [
                    h for h in self._history
                    if h.filename == response.filename
                ]
                if not existing:
                    self._history.insert(0, response)
                    self._all_records.extend(response.records)
                    imported += 1
                    total_records += response.total_records
                    total_regnr += response.successful
                    total_fail += response.failed

        if imported > 0:
            self._save_history()
            self._update_history_table()
            self._update_display()

            QMessageBox.information(
                self, "Import klar",
                f"✅ Importerade {imported} ny(a) fil(er)\n\n"
                f"📊 Fordon: {total_records}\n"
                f"🚗 Med regnr: {total_regnr}\n"
                f"❌ Fel: {total_fail}\n\n"
                f"Klicka 'SKRIV UT RAPPORT' för att skriva ut."
            )
        else:
            QMessageBox.information(
                self, "Inga nya filer",
                "Alla filer i In-mappen har redan importerats."
            )

        self._check_in_folder()

    def import_from_in_folder(self) -> None:
        self._import_from_in_folder()

    def _browse_file(self) -> None:
        """Välj fil manuellt"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Välj svarsfil",
            str(self.plugin.get_in_path()),
            "TAD-filer (tad*);;Alla filer (*)"
        )

        if filepath:
            self._import_single_file(Path(filepath))

    def browse_file(self) -> None:
        self._browse_file()

    def _import_single_file(self, filepath: Path) -> bool:
        """Importerar en enskild fil"""
        dealers_map = self.plugin.get_dealers_map()
        parser = TADResponseParser(dealers_map)
        response = parser.parse_file(filepath)

        if response.total_records > 0:
            existing = [
                h for h in self._history
                if h.filename == response.filename
            ]
            if existing:
                result = QMessageBox.question(
                    self, "Fil finns redan",
                    f"Filen '{response.filename}' har redan importerats.\n\n"
                    f"Vill du importera igen?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                )
                if result != QMessageBox.StandardButton.Yes:
                    return False

                self._history = [
                    h for h in self._history
                    if h.filename != response.filename
                ]
                self._all_records = [
                    r for r in self._all_records
                    if r.fil_id != response.file_id
                ]

            self._history.insert(0, response)
            self._all_records.extend(response.records)
            self._save_history()
            self._update_history_table()
            self._update_display()

            QMessageBox.information(
                self, "Import klar",
                f"✅ {response.filename}\n"
                f"🏷️ FilID: {response.file_id}\n"
                f"🏢 Företag: {response.foretag}\n\n"
                f"📊 Fordon: {response.total_records}\n"
                f"🚗 Med regnr: {response.successful}\n"
                f"❌ Fel: {response.failed}"
            )
            return True
        else:
            QMessageBox.warning(
                self, "Inga poster", "Inga fordon hittades i filen."
            )
            return False

    def import_single_file(self, filepath: Path) -> bool:
        return self._import_single_file(filepath)

    # ═══════════════════════════════════════════════════════════════════════════
    # DISPLAY FUNKTIONER
    # ═══════════════════════════════════════════════════════════════════════════

    def _update_display(self) -> None:
        """Uppdaterar statistik och tabell"""
        total = len(self._all_records)
        with_regnr = sum(1 for r in self._all_records if r.has_regnr)
        without_regnr = sum(
            1 for r in self._all_records
            if not r.has_regnr and not r.has_error
        )
        failed = sum(1 for r in self._all_records if r.has_error)
        rate = round(with_regnr / total * 100, 1) if total > 0 else 0

        self._update_stat(self._stats_files, str(len(self._history)))
        self._update_stat(self._stats_total, str(total))
        self._update_stat(self._stats_regnr, str(with_regnr))
        self._update_stat(self._stats_no_regnr, str(without_regnr))
        self._update_stat(self._stats_fail, str(failed))
        self._update_stat(self._stats_rate, f"{rate}%")

        self._populate_table(self._all_records)

    def update_display(self) -> None:
        self._update_display()

    def _update_history_table(self) -> None:
        """Uppdaterar historiktabellen"""
        self._history_table.setRowCount(len(self._history))

        for row, response in enumerate(self._history):
            self._history_table.setItem(
                row, 0, QTableWidgetItem(response.display_name)
            )
            self._history_table.setItem(
                row, 1, QTableWidgetItem(response.file_id)
            )

            date_str = (
                response.imported_at[:10] if response.imported_at else ""
            )
            self._history_table.setItem(row, 2, QTableWidgetItem(date_str))

            item = QTableWidgetItem(str(response.total_records))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._history_table.setItem(row, 3, item)

            item = QTableWidgetItem(f"{response.successful} ✅")
            item.setForeground(QColor(Colors.FG_SUCCESS))
            self._history_table.setItem(row, 4, item)

    def update_history_table(self) -> None:
        self._update_history_table()

    def _populate_table(self, records: List[VehicleRecord]) -> None:
        """Fyller huvudtabellen med poster"""
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(records))

        # Fonter
        normal_font = self.wm.get_font('table')
        bold_font = self.wm.get_font('table', bold=True)
        mono_font = self.wm.get_monospace_font('table')

        for row, r in enumerate(records):
            # Nr
            item = QTableWidgetItem(str(r.lopnr))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFont(normal_font)
            self._table.setItem(row, 0, item)

            # Ägare orgnr
            item = QTableWidgetItem(r.agare_orgnr)
            item.setFont(normal_font)
            self._table.setItem(row, 1, item)

            # Ägare namn
            item = QTableWidgetItem(r.agare_namn)
            item.setFont(normal_font)
            self._table.setItem(row, 2, item)

            # Regnr
            item = QTableWidgetItem(r.regnr if r.has_regnr else "")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if r.has_regnr:
                item.setForeground(QColor(Colors.FG_SUCCESS))
                item.setFont(bold_font)
            self._table.setItem(row, 3, item)

            # VIN
            item = QTableWidgetItem(r.vin)
            item.setFont(mono_font)
            self._table.setItem(row, 4, item)

            # Fabrikat
            item = QTableWidgetItem(r.fabrikat)
            item.setFont(normal_font)
            self._table.setItem(row, 5, item)

            # Modell
            item = QTableWidgetItem(r.modell)
            item.setFont(normal_font)
            self._table.setItem(row, 6, item)

            # Kategori
            item = QTableWidgetItem(r.kategori)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFont(normal_font)
            self._table.setItem(row, 7, item)

            # Status
            item = QTableWidgetItem(r.status_display)
            item.setFont(normal_font)
            if r.has_regnr:
                item.setForeground(QColor(Colors.FG_SUCCESS))
            elif r.has_error:
                item.setForeground(QColor(Colors.FG_DANGER))
            else:
                item.setForeground(QColor(Colors.FG_WARNING))
            self._table.setItem(row, 8, item)

        self._table.setSortingEnabled(True)

    def populate_table(self, records: List[VehicleRecord]) -> None:
        self._populate_table(records)

    def _apply_filter(self) -> None:
        """Applicerar filter på tabellen"""
        filter_type = self._filter_combo.currentText()
        search_text = self._search_input.text().strip().upper()

        filtered = []

        for r in self._all_records:
            if filter_type == "Endast med regnr" and not r.has_regnr:
                continue
            elif filter_type == "Utan regnr" and r.has_regnr:
                continue
            elif filter_type == "Fel" and not r.has_error:
                continue

            if search_text:
                match = (
                    search_text in r.vin.upper() or
                    search_text in r.regnr.upper() or
                    search_text in r.agare_orgnr or
                    search_text in r.agare_namn.upper() or
                    search_text in r.modell.upper() or
                    search_text in r.fabrikat.upper()
                )
                if not match:
                    continue

            filtered.append(r)

        self._populate_table(filtered)

    def apply_filter(self) -> None:
        self._apply_filter()

    def _on_history_selected(self, item) -> None:
        """Hanterar val i historiklistan"""
        row = item.row()
        if 0 <= row < len(self._history):
            response = self._history[row]
            self._current_response = response
            self._populate_table(response.records)
            self._filter_combo.setCurrentIndex(0)
            self._search_input.clear()

    def on_history_selected(self, item) -> None:
        self._on_history_selected(item)

    # ═══════════════════════════════════════════════════════════════════════════
    # RAPPORT FUNKTIONER
    # ═══════════════════════════════════════════════════════════════════════════

    def _print_report(self) -> None:
        """Visa och skriv ut rapport"""
        with_regnr = [r for r in self._all_records if r.has_regnr]

        if not with_regnr:
            QMessageBox.warning(
                self, "Ingen data",
                "Inga fordon med registreringsnummer att rapportera.\n\n"
                "Importera svarsfiler först."
            )
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        lines = [
            "═" * 110,
            "  RAPPORT: REGISTRERADE FORDON FRÅN TRANSPORTSTYRELSEN",
            f"  Genererad: {now}",
            f"  Antal filer: {len(self._history)}",
            f"  Totalt registrerade: {len(with_regnr)} fordon",
            "═" * 110,
            "",
            f"  {'ÄGARE (ORGNR)':<14} {'ÄGARE (NAMN)':<30} {'REGNR':<10} "
            f"{'VIN':<20} {'MODELL':<30}",
            "─" * 110,
        ]

        sorted_records = sorted(
            with_regnr, key=lambda r: (r.agare_orgnr, r.regnr)
        )

        current_owner = None
        for r in sorted_records:
            if r.agare_orgnr != current_owner:
                if current_owner is not None:
                    lines.append("")
                current_owner = r.agare_orgnr

            namn = (
                (r.agare_namn[:28] + "..")
                if len(r.agare_namn) > 30
                else r.agare_namn
            )
            modell = (
                (r.modell[:28] + "..")
                if len(r.modell) > 30
                else r.modell
            )

            lines.append(
                f"  {r.agare_orgnr:<14} {namn:<30} {r.regnr:<10} "
                f"{r.vin:<20} {modell:<30}"
            )

        lines.extend([
            "",
            "─" * 110,
            f"  TOTALT: {len(with_regnr)} fordon registrerade",
            "═" * 110,
        ])

        report_text = "\n".join(lines)
        self._show_report_dialog(report_text, len(with_regnr))

    def print_report(self) -> None:
        self._print_report()

    def _show_report_dialog(self, report_text: str, count: int) -> None:
        """Visar rapport i dynamiskt skalad dialog"""
        dialog = DynamicDialog(
            self, self.wm, f"Rapport - {count} registrerade fordon"
        )

        # Använd rapport-storlek
        width, height = self.wm.get_report_dialog_size()
        dialog.resize(width, height)
        dialog._center_on_screen()

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(
            self.cfg.padding, self.cfg.padding,
            self.cfg.padding, self.cfg.padding
        )

        # Textfält
        text_edit = QTextEdit()
        text_edit.setPlainText(report_text)
        text_edit.setReadOnly(True)
        text_edit.setFont(self.wm.get_monospace_font('normal'))
        text_edit.setStyleSheet(f"""
            QTextEdit {{
                background: {Colors.BG_DARK};
                color: {Colors.FG_NORMAL};
                border: 1px solid {Colors.BORDER_DARK};
                padding: {self.cfg.padding}px;
            }}
        """)
        layout.addWidget(text_edit)

        # Knappar
        btn_layout = QHBoxLayout()

        btn_copy = QPushButton("📋 Kopiera till urklipp")
        btn_copy.setStyleSheet(self.styles.get_primary_button())
        btn_copy.clicked.connect(
            lambda: self._copy_to_clipboard(report_text, dialog)
        )
        btn_layout.addWidget(btn_copy)

        btn_save = QPushButton("💾 Spara som textfil")
        btn_save.setStyleSheet(self.styles.get_success_button())
        btn_save.clicked.connect(lambda: self._save_report_text(report_text))
        btn_layout.addWidget(btn_save)

        btn_print = QPushButton("🖨️ Skriv ut")
        btn_print.setStyleSheet(self.styles.get_secondary_button())
        btn_print.clicked.connect(lambda: self._print_to_printer(report_text))
        btn_layout.addWidget(btn_print)

        btn_layout.addStretch()

        btn_close = QPushButton("Stäng")
        btn_close.setStyleSheet(self.styles.get_dark_button())
        btn_close.clicked.connect(dialog.close)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

        dialog.exec()

    def show_report_dialog(self, report_text: str, count: int) -> None:
        self._show_report_dialog(report_text, count)

    def _copy_to_clipboard(self, text: str, parent_dialog: QDialog) -> None:
        """Kopiera till urklipp"""
        QApplication.clipboard().setText(text)
        QMessageBox.information(
            parent_dialog, "Kopierat",
            "Rapporten kopierades till urklipp!",
        )

    def copy_to_clipboard(self, text: str, parent_dialog: QDialog) -> None:
        self._copy_to_clipboard(text, parent_dialog)

    def _save_report_text(self, text: str) -> None:
        """Spara rapport som textfil"""
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Spara rapport",
            f"rapport_regnr_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            "Textfiler (*.txt)"
        )

        if filepath:
            try:
                Path(filepath).write_text(text, encoding='utf-8')
                QMessageBox.information(
                    self, "Sparat", f"Rapport sparad:\n{filepath}"
                )
            except Exception as e:
                QMessageBox.critical(self, "Fel", f"Kunde inte spara:\n{e}")

    def save_report_text(self, text: str) -> None:
        self._save_report_text(text)

    def _print_to_printer(self, text: str) -> None:
        """Skriv ut till skrivare"""
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
            from PySide6.QtGui import QTextDocument

            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            dialog = QPrintDialog(printer, self)

            if dialog.exec() == QPrintDialog.DialogCode.Accepted:
                doc = QTextDocument()
                doc.setPlainText(text)
                doc.setDefaultFont(self.wm.get_monospace_font('small'))
                doc.print_(printer)
                QMessageBox.information(
                    self, "Utskrift",
                    "Rapporten skickades till skrivaren.",
                )
        except Exception as e:
            QMessageBox.critical(
                self, "Utskriftsfel", f"Kunde inte skriva ut:\n{e}"
            )

    def print_to_printer(self, text: str) -> None:
        self._print_to_printer(text)

    # ═══════════════════════════════════════════════════════════════════════════
    # EXPORT FUNKTIONER
    # ═══════════════════════════════════════════════════════════════════════════

    def _export_excel(self) -> None:
        """Exportera till Excel"""
        if not self._all_records:
            QMessageBox.warning(self, "Ingen data", "Ingen data att exportera.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Spara Excel-fil",
            f"svarsfil_export_{datetime.now().strftime('%Y%m%d')}.xlsx",
            "Excel-filer (*.xlsx)"
        )

        if filepath:
            try:
                import pandas as pd

                data = []
                for r in self._all_records:
                    data.append({
                        "Nr": r.lopnr,
                        "Ägare Orgnr": r.agare_orgnr,
                        "Ägare Namn": r.agare_namn,
                        "Regnr": r.regnr if r.has_regnr else "",
                        "VIN": r.vin,
                        "Fabrikat": r.fabrikat,
                        "Modell": r.modell,
                        "Kategori": r.kategori,
                        "Typgodkännande": r.typgodkannande,
                        "Datum": r.datum_reg,
                        "Status": r.status_simple,
                        "Felkod": r.felkod if r.has_error else "",
                    })

                df = pd.DataFrame(data)
                df.to_excel(filepath, index=False, sheet_name="Fordon")

                QMessageBox.information(
                    self, "Export klar",
                    f"Data exporterad till:\n{filepath}",
                )

            except ImportError:
                QMessageBox.critical(
                    self, "Fel",
                    "pandas eller openpyxl saknas.\n\nInstallera med:\n"
                    "pip install pandas openpyxl"
                )
            except Exception as e:
                QMessageBox.critical(self, "Export misslyckades", str(e))

    def export_excel(self) -> None:
        self._export_excel()

    def _export_pdf(self) -> None:
        """Exportera till PDF"""
        with_regnr = [r for r in self._all_records if r.has_regnr]

        if not with_regnr:
            QMessageBox.warning(
                self, "Ingen data",
                "Inga registrerade fordon att exportera.",
            )
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Spara PDF-fil",
            f"rapport_regnr_{datetime.now().strftime('%Y%m%d')}.pdf",
            "PDF-filer (*.pdf)"
        )

        if filepath:
            try:
                from reportlab.lib import colors
                from reportlab.lib.pagesizes import A4, landscape
                from reportlab.lib.styles import (
                    getSampleStyleSheet, ParagraphStyle,
                )
                from reportlab.platypus import (
                    SimpleDocTemplate, Table, TableStyle,
                    Paragraph, Spacer,
                )
                from reportlab.lib.units import mm

                doc = SimpleDocTemplate(
                    filepath,
                    pagesize=landscape(A4),
                    leftMargin=15 * mm,
                    rightMargin=15 * mm,
                    topMargin=15 * mm,
                    bottomMargin=15 * mm
                )

                elements = []
                styles = getSampleStyleSheet()

                title_style = ParagraphStyle(
                    'Title',
                    parent=styles['Title'],
                    fontSize=16,
                    spaceAfter=10
                )
                title = Paragraph(
                    "<b>REGISTRERADE FORDON - "
                    f"{datetime.now().strftime('%Y-%m-%d')}</b>",
                    title_style
                )
                elements.append(title)

                stats = Paragraph(
                    f"Totalt: {len(with_regnr)} fordon | "
                    f"Antal filer: {len(self._history)}",
                    styles['Normal']
                )
                elements.append(stats)
                elements.append(Spacer(1, 15))

                table_data = [
                    ["Ägare (Orgnr)", "Ägare (Namn)", "Regnr", "VIN", "Modell"]
                ]

                for r in with_regnr:
                    table_data.append([
                        r.agare_orgnr,
                        r.agare_namn[:25] if r.agare_namn else "",
                        r.regnr,
                        r.vin,
                        r.modell[:25] if r.modell else ""
                    ])

                table = Table(table_data, repeatRows=1)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3a3f44')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                    ('TOPPADDING', (0, 0), (-1, 0), 10),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                    (
                        'ROWBACKGROUNDS', (0, 1), (-1, -1),
                        [colors.white, colors.HexColor('#f8f9fa')],
                    ),
                ]))

                elements.append(table)
                doc.build(elements)

                QMessageBox.information(
                    self, "Export klar", f"PDF skapad:\n{filepath}"
                )

            except ImportError:
                QMessageBox.critical(
                    self, "Fel",
                    "reportlab saknas.\n\nInstallera med:\n"
                    "pip install reportlab"
                )
            except Exception as e:
                QMessageBox.critical(self, "Export misslyckades", str(e))

    def export_pdf(self) -> None:
        self._export_pdf()

    # ═══════════════════════════════════════════════════════════════════════════
    # HISTORIK FUNKTIONER
    # ═══════════════════════════════════════════════════════════════════════════

    def _clear_history(self) -> None:
        """Rensa all historik"""
        if not self._history:
            QMessageBox.information(
                self, "Tom historik", "Ingen historik att rensa."
            )
            return

        result = QMessageBox.question(
            self,
            "Bekräfta rensning",
            f"Vill du rensa all historik?\n\n"
            f"Detta tar bort {len(self._history)} fil(er) och "
            f"{len(self._all_records)} fordon.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if result == QMessageBox.StandardButton.Yes:
            self._history.clear()
            self._all_records.clear()
            self._current_response = None
            self._save_history()
            self._update_history_table()
            self._update_display()
            QMessageBox.information(self, "Rensat", "All historik har rensats.")

    def clear_history_widget(self) -> None:
        self._clear_history()

    def _load_history(self) -> None:
        """Laddar historik från fil"""
        history_path = self.plugin.get_history_path()

        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                for item in data.get("history", [])[:50]:
                    records = []
                    for rec_data in item.get("records", []):
                        try:
                            record = VehicleRecord(**rec_data)
                            records.append(record)
                        except Exception:
                            pass

                    response = ResponseFile(
                        filename=item.get("filename", ""),
                        filepath=item.get("filepath", ""),
                        imported_at=item.get("imported_at", ""),
                        file_id=item.get("file_id", ""),
                        orgnr=item.get("orgnr", ""),
                        foretag=item.get("foretag", ""),
                        kontakt=item.get("kontakt", ""),
                        total_records=item.get("total_records", 0),
                        successful=item.get("successful", 0),
                        failed=item.get("failed", 0),
                        pending=item.get("pending", 0),
                        records=records
                    )

                    self._history.append(response)
                    self._all_records.extend(records)

                self._update_history_table()
                self._update_display()

            except Exception as e:
                _log.warning("Kunde inte ladda historik: %s", e)

    def load_history(self) -> None:
        self._load_history()

    def _save_history(self) -> None:
        """Sparar historik till fil (atomiskt)"""
        history_path = self.plugin.get_history_path()

        try:
            data = {
                "history": [
                    {
                        "filename": r.filename,
                        "filepath": r.filepath,
                        "imported_at": r.imported_at,
                        "file_id": r.file_id,
                        "orgnr": r.orgnr,
                        "foretag": r.foretag,
                        "kontakt": r.kontakt,
                        "total_records": r.total_records,
                        "successful": r.successful,
                        "failed": r.failed,
                        "pending": r.pending,
                        "records": [rec.to_dict() for rec in r.records]
                    }
                    for r in self._history[:50]
                ],
                "updated_at": datetime.now().isoformat()
            }

            history_path.parent.mkdir(parents=True, exist_ok=True)

            # Atomisk sparning
            fd, tmp = tempfile.mkstemp(dir=str(history_path.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, history_path)

        except Exception as e:
            _log.warning("Kunde inte spara historik: %s", e)

    def save_history(self) -> None:
        self._save_history()


# ══════════════════════════════════════════════════════════════════════════════
# HUVUDPLUGIN
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    Response Viewer Plugin v2.0.1

    Hantering av TAD-svarsfiler från Transportstyrelsen med dynamisk UI.
    """

    NAME = "Response Viewer"
    VERSION = VERSION
    DESCRIPTION = "Importera TAD-svarsfiler med dynamiskt skalat UI"
    AUTHOR = AUTHOR
    DEPENDENCIES = ["core_config"]

    def __init__(self, app):
        super().__init__(app)
        self._widget: Optional[ResponseViewerWidget] = None
        self._paths: Dict[str, Path] = {}

    def initialize(self) -> None:
        """Initiera plugin"""
        self._setup_paths()
        _log.info("%s v%s initierad", self.NAME, self.VERSION)
        _log.info("In-mapp: %s", self._paths["in"])

    def init(self) -> None:
        self.initialize()

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False

    def shutdown(self) -> None:
        self.deactivate()

    def config_schema(self) -> Dict[str, Any]:
        """Returnerar pluginets konfigurationsschema."""
        return {
            "plugin": self.NAME,
            "version": VERSION,
            "author": AUTHOR,
            "copyright": get_copyright_string(),
            "settings": {
                "in_dir": "In",
                "js_data_dir": ".js data",
                "history_max": 50,
            },
        }

    def _setup_paths(self) -> None:
        """Konfigurera sökvägar (kraschsäkert)"""
        config = getattr(self.app, "config", None)

        base_dir = "."
        js_data_dir = ".js data"
        if config is not None:
            try:
                if hasattr(config, "get"):
                    base_dir = config.get("base_dir", ".") or "."
                    js_data_dir = config.get("js_data_dir", ".js data") or ".js data"
                elif isinstance(config, dict):
                    base_dir = config.get("base_dir", ".") or "."
                    js_data_dir = config.get("js_data_dir", ".js data") or ".js data"
            except Exception:
                pass

        base_path = Path(str(base_dir))
        js_path = Path(str(js_data_dir))

        self._paths = {
            "base": base_path,
            "in": base_path / "In",
            "js_data": base_path / js_path,
            "history": base_path / js_path / "response_history.json",
        }

        self._paths["in"].mkdir(parents=True, exist_ok=True)

    def setup_paths(self) -> None:
        self._setup_paths()

    def create_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        """Skapar GUI-widget med dynamisk skalning"""
        self._widget = ResponseViewerWidget(self)
        return self._widget

    def register_ui(self, parent: Optional[QWidget] = None) -> QWidget:
        return self.create_widget(parent)

    def get_in_path(self) -> Path:
        return self._paths.get("in", Path("In"))

    def get_history_path(self) -> Path:
        return self._paths.get(
            "history", Path(".js data/response_history.json")
        )

    def get_dealers_map(self) -> Dict[str, str]:
        """Hämtar ägare-map från dealers_manager plugin (kraschsäkert)"""
        dealers_map = {}

        dealers_plugin = self._get_plugin_safe("dealers_manager")
        if dealers_plugin and hasattr(dealers_plugin, "get_all_dealers"):
            try:
                dealers = dealers_plugin.get_all_dealers()
                for dealer in dealers:
                    orgnr = str(dealer.get("orgnr", "")).replace("-", "")
                    namn = dealer.get("namn", dealer.get("name", ""))
                    if orgnr and namn:
                        dealers_map[orgnr] = namn
            except Exception as e:
                _log.warning("Kunde inte hämta dealers: %s", e)

        return dealers_map

    def _get_plugin_safe(self, name: str) -> Optional[Any]:
        """Hämta plugin kraschsäkert (app.get_plugin / plugin_loader /
        plugin_manager / getattr)."""
        if self.app is None:
            return None

        try:
            gp = getattr(self.app, "get_plugin", None)
            if callable(gp):
                result = gp(name)
                if result is not None:
                    return result
        except Exception:
            pass

        try:
            loader = getattr(self.app, "plugin_loader", None)
            if loader is not None and hasattr(loader, "get_plugin"):
                result = loader.get_plugin(name)
                if result is not None:
                    return result
        except Exception:
            pass

        try:
            manager = getattr(self.app, "plugin_manager", None)
            if manager is not None and hasattr(manager, "get_plugin"):
                result = manager.get_plugin(name)
                if result is not None:
                    return result
        except Exception:
            pass

        try:
            return getattr(self.app, name, None)
        except Exception:
            return None

    def import_file(self, filepath: str) -> bool:
        """Importerar en svarsfil programmatiskt"""
        if self._widget:
            return self._widget._import_single_file(Path(filepath))
        return False

    def get_all_records(self) -> List[Dict[str, Any]]:
        """Returnerar alla importerade poster"""
        if self._widget:
            return [r.to_dict() for r in self._widget._all_records]
        return []

    def get_registered_vehicles(self) -> List[Dict[str, Any]]:
        """Returnerar endast fordon med registreringsnummer"""
        if self._widget:
            return [
                r.to_dict()
                for r in self._widget._all_records
                if r.has_regnr
            ]
        return []

    def get_screen_info(self) -> Dict[str, Any]:
        """Returnerar information om skärminställningar"""
        if self._widget:
            wm = self._widget.wm
            return {
                'category': wm.config.category.value,
                'screen_width': wm.screen_width,
                'screen_height': wm.screen_height,
                'dpi_scale': wm.dpi_scale,
                'scale_factor': wm.config.scale_factor,
            }
        return {}
