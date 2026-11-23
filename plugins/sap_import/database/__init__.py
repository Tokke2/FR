# -*- coding: utf-8 -*-
# Fil: plugins/sap_import/database/__init__.py

"""
Databasoperationer för SAP Import Plugin (v2.1.1).

Detta package hanterar all databasrelaterad funktionalitet för
SAP Import, inklusive:

    - Tabellhantering och schema
    - Batch-import med konfliktlösning
    - Transaktionshantering
    - Index-optimering
    - Legacy-stöd för äldre kod

Exporterade klasser och funktioner:
    - DatabaseImporter      : Huvudklass för databasimport
    - ImportResult          : Resultat från import-operation
    - ConflictResolution    : Enum för konflikthantering
    - TableSchema           : Schema-definition
    - build_schema()        : Bygg tabellschema
    - ensure_table()        : Legacy: säkerställ tabell
    - batch_insert()        : Legacy: batch-insert

Användning:
    >>> from plugins.sap_import.database import DatabaseImporter
    >>>
    >>> with DatabaseImporter("data/vehicles.db") as importer:
    ...     result = importer.import_rows(rows)
    ...     print(result.summary())

Se även:
    - plugins/sap_import/database/importer.py

FÖRÄNDRINGAR v2.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (spec v1.11 KRAV 58): header normaliserad — "# Fil: ...".
    - FIX (versionssynk): __version__ = "2.1.1" (importer.py är
      v2.1.1).
    - VERSION/AUTHOR/get_copyright_string tillagda (konvention,
      samma mönster som models/__init__.py).
    - __all__ kompletterad med get_copyright_string.
    - Övrig logik OFÖRÄNDRAD (lazy imports, legacy-fallbacks).
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


# Legacy-funktioner (bakåtkompatibilitet)
try:
    from .importer import batch_insert, ensure_table
except ImportError:
    batch_insert = None  # type: ignore
    ensure_table = None  # type: ignore

# Nya klasser
try:
    from .importer import (
        DatabaseImporter,
        ImportResult,
        ConflictResolution,
        TableSchema,
        build_schema,
    )
except ImportError:
    pass


__all__: List[str] = [
    # Huvudklass
    "DatabaseImporter",
    # Data structures
    "ImportResult",
    "ConflictResolution",
    "TableSchema",
    # Helpers
    "build_schema",
    # Legacy (bakåtkompatibilitet)
    "ensure_table",
    "batch_insert",
    # Metadata
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]

__version__ = "2.1.1"
