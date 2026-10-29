# -*- coding: utf-8 -*-
# Fil: plugins/reports/exporters.py
"""Exporters för rapporter - alla format (v1.0.1).

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (KRAV 58): filkommentar "# Fil: plugins/reports/exporters.py"
      tillagd (saknades).
    - VERSION/AUTHOR/get_copyright_string tillagda (saknades helt).
    - FIX (låst regel): ALLA print()-anrop -> module-level _log
      (lazy %s) — to_json/to_csv/to_excel/to_pdf.
    - FIX (låst regel, atomer): to_json()/to_csv() skrev med öppen
      write() — korrupta filer vid krasch. Nu delad
      _atomic_write_text() (mkstemp -> fsync -> os.replace).
      to_excel() skriver till temp-fil -> os.replace (pandas/openpyxl
      kan inte fsync:a enkelt, men flytten gör filen atomisk).
    - FIX (korrekthet): to_pdf() använde hårdkodad
      colWidths=[10*cm, 4*cm] — kraschar (reportlab) om tabellen har
      != 2 kolumner. Nu: dynamisk bredd per kolumn (totalt ~18 cm
      inom A4-marginaler), med sista kolumnen bredare.
    - FIX (typing): metadata: List[str] = None ->
      Optional[List[str]] = None (+ import Optional).
    - Övrig logik OFÖRÄNDRAD (JSON/CSV/Excel/PDF-struktur,
      EXCEL_AVAILABLE/PDF_AVAILABLE-flaggor, sheet_name[:31]).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

# Pandas (valfritt)
try:
    import pandas as pd
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False

# PDF (valfritt)
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    from reportlab.lib.units import cm
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT / LOGGER
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "1.0.1"
AUTHOR: str = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    from datetime import datetime
    return f"Copyright © {datetime.now().year} {AUTHOR}"


def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback om logging ej konfigurerat.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("reports.exporters")
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


class ReportExporter:
    """Exporterar rapporter till olika format."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ══════════════════════════════════════════════════════════════════════════
    # JSON
    # ══════════════════════════════════════════════════════════════════════════

    def to_json(self, data: Dict[str, Any], filename: str) -> Path:
        """Exporterar till JSON (atomiskt)."""
        filepath = self.output_dir / filename
        content = json.dumps(data, indent=2, ensure_ascii=False)
        _atomic_write_text(filepath, content, encoding="utf-8")
        _log.info("JSON: %s", filename)
        return filepath

    # ══════════════════════════════════════════════════════════════════════════
    # CSV
    # ══════════════════════════════════════════════════════════════════════════

    def to_csv(
        self,
        rows: List[List[Any]],
        filename: str,
        delimiter: str = ";",
    ) -> Path:
        """Exporterar till CSV (atomiskt)."""
        filepath = self.output_dir / filename

        import io
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=delimiter)
        writer.writerows(rows)

        _atomic_write_text(filepath, buffer.getvalue(), encoding="utf-8-sig")
        _log.info("CSV: %s", filename)
        return filepath

    # ══════════════════════════════════════════════════════════════════════════
    # Excel
    # ══════════════════════════════════════════════════════════════════════════

    def to_excel(
        self,
        sheets: Dict[str, List[Dict[str, Any]]],
        filename: str,
    ) -> Path:
        """Exporterar till Excel (kräver pandas, atomiskt)."""
        if not EXCEL_AVAILABLE:
            raise ImportError("pandas krävs för Excel-export")

        filepath = self.output_dir / filename

        # Skriv till temp-fil i samma katalog -> os.replace (atomiskt)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.output_dir),
            prefix=f".{Path(filename).name}.tmp_",
            suffix=".xlsx",
        )
        os.close(fd)
        try:
            with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
                for sheet_name, data in sheets.items():
                    df = pd.DataFrame(data)
                    df.to_excel(
                        writer, sheet_name=sheet_name[:31], index=False
                    )
            os.replace(tmp_path, str(filepath))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        _log.info("Excel: %s", filename)
        return filepath

    # ══════════════════════════════════════════════════════════════════════════
    # PDF
    # ══════════════════════════════════════════════════════════════════════════

    def to_pdf(
        self,
        title: str,
        table_data: List[List[str]],
        filename: str,
        metadata: Optional[List[str]] = None,
    ) -> Path:
        """Exporterar till PDF (kräver reportlab)."""
        if not PDF_AVAILABLE:
            raise ImportError("reportlab krävs för PDF-export")

        filepath = self.output_dir / filename

        doc = SimpleDocTemplate(str(filepath), pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        # Rubrik
        title_style = ParagraphStyle(
            'Title', parent=styles['Heading1'],
            fontSize=18, alignment=TA_CENTER,
        )
        elements.append(Paragraph(title, title_style))
        elements.append(Spacer(1, 0.5 * cm))

        # Metadata
        if metadata:
            for line in metadata:
                elements.append(Paragraph(line, styles['Normal']))
            elements.append(Spacer(1, 0.3 * cm))

        # Tabell — dynamiska kolumnbredder (totalt ~18 cm inom A4)
        num_cols = max(len(row) for row in table_data) if table_data else 1
        total_width_cm = 18.0
        if num_cols <= 1:
            col_widths = [total_width_cm * cm]
        else:
            base = total_width_cm / num_cols
            col_widths = [
                (base + 3.0 if i == num_cols - 1 else base) * cm
                for i in range(num_cols)
            ]

        table = Table(table_data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4472C4")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ]))
        elements.append(table)

        doc.build(elements)
        _log.info("PDF: %s", filename)
        return filepath
