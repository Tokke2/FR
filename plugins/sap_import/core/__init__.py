# -*- coding: utf-8 -*-
# Fil: plugins/sap_import/core/__init__.py
"""Core-funktioner för SAP Import (v2.1.1).

Paket-länkning (KRAV 56) för sap_import/core — exporterar
alias-tabeller, kolumnresolver, datumkonvertering, header-detektion
och normalisering.

Ändringar v2.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (KRAV 58): header normaliserad — "# Fil: plugins/sap_import/
      core/__init__.py".
    - VERSION/AUTHOR/get_copyright_string tillagda (konvention,
      samma mönster som models/__init__.py och database/__init__.py).
    - FIX (kraschsäkerhet): importerna utan try/except — om någon
      core-modul saknas på disken kunde hela paketet inte importeras.
      Nu try/except med None-fallback (samma mönster som övriga
      paket-init).
    - __all__ kompletterad med get_copyright_string.
    - Övrig logik OFÖRÄNDRAD (exporter, metadata).
"""

from __future__ import annotations

from datetime import datetime
from typing import List

# ══════════════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "2.1.1"
AUTHOR: str = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTER (kraschsäkra imports — alla core-moduler levererade)
# ══════════════════════════════════════════════════════════════════════════════

try:
    from .column_resolver import (
        DISPATCH_ALIAS,
        resolve_columns,
        normalize_key,
    )
except ImportError:  # pragma: no cover
    DISPATCH_ALIAS = None  # type: ignore
    resolve_columns = None  # type: ignore
    normalize_key = None  # type: ignore

try:
    from .date_converter import to_iso_date
except ImportError:  # pragma: no cover
    to_iso_date = None  # type: ignore

try:
    from .excel_reader import read_excel_with_header_detection
except ImportError:  # pragma: no cover
    read_excel_with_header_detection = None  # type: ignore

try:
    from .data_normalizer import normalize_dataframe
except ImportError:  # pragma: no cover
    normalize_dataframe = None  # type: ignore


__all__: List[str] = [
    "DISPATCH_ALIAS",
    "resolve_columns",
    "normalize_key",
    "to_iso_date",
    "read_excel_with_header_detection",
    "normalize_dataframe",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]
