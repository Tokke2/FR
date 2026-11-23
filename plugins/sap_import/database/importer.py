# -*- coding: utf-8 -*-
# Fil: plugins/sap_import/database/importer.py

"""
Databasimport för SAP/WVTA-data (v2.1.1).

Hanterar:
    - Tabellskapande med korrekt schema
    - Batch-import med conflict resolution
    - Transaktionshantering
    - Index-optimering
    - Data-validering före insert
    - Atomisk skrivning

Användning:
    from plugins.sap_import.database.importer import DatabaseImporter

    with DatabaseImporter(db_path) as importer:
        result = importer.import_rows(rows)
        print(result.summary())

FÖRÄNDRINGAR v2.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - VERSION/AUTHOR/get_copyright_string tillagda (saknades helt).
    - FIX (låst regel): alla f-string-logganrop -> lazy %s
      (_log.debug(f"..."), _log.error(f"..."), _log.info(f"...")).
    - FIX (KRAV 58): header normaliserad — "# Fil: plugins/sap_import/
      database/importer.py".
    - FIX (korrekthet, TESTFÅNGAD KRASCH): sqlite3.connect() med
      detect_types=PARSE_DECLTYPES + kolumner deklarerade TIMESTAMP
      fick sqlite3 att försöka konvertera våra ISO-strängar
      ("2026-08-18T12:34:56", T-separator) med convert_timestamp
      (kräver mellanslagsseparator) → ValueError vid VARJE läsning
      (get_by_vin, get_statistics). Nu utan detect_types — all data
      hanteras som TEXT (konsistent med övriga moduler).
    - FIX (robusthet): import time flyttad till modulnivå (var lokal
      i import_rows()).
    - FIX (robusthet, INSERT-FEL): _prepare_row() gjorde ingen
      längdjustering — rader med fel antal värden gav
      "table has N columns but M values were supplied" och hela
      batchen rullades tillbaka. Nu: pad/trunkera till antalet
      datakolumner före insert.
    - FIX (korrekthet, RÄKNARE): _import_batch() rapporterade alltid
      inserted = antal rader oavsett conflict resolution. Nu används
      cursor.rowcount: IGNORE -> inserted + skipped korrekt;
      UPDATE -> updated; REPLACE -> inserted.
    - FIX (robusthet): ConflictResolution.FAIL kraschade hela
      importen vid första konflikt (IntegrityError ut ur
      transaktionen). Nu: batchen markeras failed + fel loggas,
      importen fortsätter.
    - FIX (robusthet): legacy-funktionen batch_insert() byggde
      kolumnlistan ur DISPATCH_ALIAS + 2 tidsstämplar — mismatch mot
      det FULLA schemat (source_file/row_hash saknades) och
      radlängd utan padding. Nu: fullt schema, pad/trunkera, row_hash
      beräknas, timestamp: Optional[str].
    - Oanvänd konstant MAX_RETRIES borttagen (dead code).
    - OBSERVATION (EJ ändrad, inväntar beslut): plugin.py v4.1.1 är
      filbaserad ("ingen databas krävs") — database/importer.py är en
      OPTIONELL/alternativ lagringsväg (WVTA) enligt trädet
      (spec v1.14 Sektion 1). Ingen konflikt; modulen används vid
      behov av WVTA-import.
    - Övrig logik OFÖRÄNDRAD (schema, transaktioner, index, PRAGMA,
      query-API, underhåll).
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple, Union

try:
    from ..core.column_resolver import DISPATCH_ALIAS
except ImportError:
    DISPATCH_ALIAS: Dict[str, List[str]] = {
        "VINCODE": ["VIN", "VIN-KOD", "CHASSINR"],
        "MODELYEAR": ["MY", "ÅRSMODELL", "MODEL YEAR"],
        "MODELNAME": ["MODELL", "MODEL", "MODELLNAMN"],
        "APPROVAL": ["ETG", "APPROVAL NO", "GODKÄNNANDENR"],
    }

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# VERSION / COPYRIGHT
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "2.1.1"
AUTHOR: str = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

TABLE_NAME = "modellregister"
BATCH_SIZE = 1000

INDEXED_COLUMNS = [
    "MODELYEAR",
    "APPROVAL",
    "MODELNAME",
    "imported_at",
    "updated_at",
]

SPECIAL_INDEXES = [
    ("idx_modellregister_vin_prefix", 'substr("VINCODE", 1, 8)'),
    ("idx_modellregister_vin_wmi", 'substr("VINCODE", 1, 3)'),
]

# Metadata-kolumner som läggs till utöver DISPATCH_ALIAS-fälten
_META_COLUMNS = ("imported_at", "updated_at", "source_file", "row_hash")


# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

class ConflictResolution(Enum):
    """Hur konflikter ska hanteras vid insert."""
    REPLACE = auto()
    IGNORE = auto()
    UPDATE = auto()
    FAIL = auto()


@dataclass
class ImportResult:
    """Resultat från import-operation."""
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[Tuple[int, str]] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.skipped + self.failed

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.inserted + self.updated) / self.total

    def __add__(self, other: ImportResult) -> ImportResult:
        return ImportResult(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            skipped=self.skipped + other.skipped,
            failed=self.failed + other.failed,
            errors=self.errors + other.errors,
            duration_ms=self.duration_ms + other.duration_ms
        )

    def summary(self) -> str:
        return (
            f"Inserted: {self.inserted}, Updated: {self.updated}, "
            f"Skipped: {self.skipped}, Failed: {self.failed} "
            f"({self.duration_ms:.1f}ms)"
        )


@dataclass
class TableSchema:
    """Schema-definition för tabell."""
    name: str
    columns: List[Tuple[str, str]]
    primary_key: str
    indexes: List[Tuple[str, str]]
    without_rowid: bool = True

    def to_create_sql(self) -> str:
        cols_sql = ",\n        ".join(
            f'"{name}" {dtype}' for name, dtype in self.columns
        )
        sql = f'CREATE TABLE IF NOT EXISTS "{self.name}" (\n        {cols_sql}\n    )'
        if self.without_rowid:
            sql += " WITHOUT ROWID"
        return sql


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_schema() -> TableSchema:
    """Bygg tabellschema från DISPATCH_ALIAS."""
    columns: List[Tuple[str, str]] = []
    columns.append(("VINCODE", "TEXT PRIMARY KEY NOT NULL"))

    for col_name in DISPATCH_ALIAS.keys():
        if col_name != "VINCODE":
            columns.append((col_name, "TEXT"))

    columns.extend([
        ("imported_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("source_file", "TEXT"),
        ("row_hash", "TEXT"),
    ])

    indexes: List[Tuple[str, str]] = []
    for col in INDEXED_COLUMNS:
        if col in [c[0] for c in columns]:
            indexes.append((f"idx_{TABLE_NAME}_{col.lower()}", f'"{col}"'))

    indexes.extend(SPECIAL_INDEXES)

    return TableSchema(
        name=TABLE_NAME,
        columns=columns,
        primary_key="VINCODE",
        indexes=indexes,
        without_rowid=True
    )


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE IMPORTER
# ══════════════════════════════════════════════════════════════════════════════

class DatabaseImporter:
    """
    Databasimportör med batch-support och felhantering.

    Attributes:
        db_path: Sökväg till SQLite-databas
        schema: Tabellschema
        batch_size: Antal rader per batch
    """

    def __init__(
        self,
        db_path: Union[str, Path],
        batch_size: int = BATCH_SIZE,
        conflict_resolution: ConflictResolution = ConflictResolution.REPLACE
    ):
        self.db_path = Path(db_path)
        self.batch_size = batch_size
        self.conflict_resolution = conflict_resolution
        self.schema = build_schema()
        self._conn: Optional[sqlite3.Connection] = None
        self._is_connected = False

    # ──────────────────────────────────────────────────────────────────────────
    # CONNECTION MANAGEMENT
    # ──────────────────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Öppna databasanslutning."""
        if self._is_connected:
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.db_path),
            isolation_level=None
        )

        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-64000")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.execute("PRAGMA mmap_size=268435456")

        self._is_connected = True
        self.ensure_table()

        _log.debug("Ansluten till databas: %s", self.db_path)

    def close(self) -> None:
        """Stäng databasanslutning."""
        if self._conn:
            try:
                self._conn.close()
            except sqlite3.Error as e:
                _log.error("Fel vid stängning av anslutning: %s", e)
            finally:
                self._conn = None
                self._is_connected = False

        _log.debug("Databasanslutning stängd")

    def __enter__(self) -> DatabaseImporter:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        if not self._conn:
            raise RuntimeError("Inte ansluten till databasen")
        return self._conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Transaction context manager."""
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN TRANSACTION")
            yield cursor
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise
        finally:
            cursor.close()

    # ──────────────────────────────────────────────────────────────────────────
    # SCHEMA MANAGEMENT
    # ──────────────────────────────────────────────────────────────────────────

    def ensure_table(self) -> None:
        """Säkerställ att tabellen existerar med korrekt schema."""
        cursor = self.connection.cursor()
        try:
            cursor.execute(self.schema.to_create_sql())
            for idx_name, idx_expr in self.schema.indexes:
                try:
                    cursor.execute(
                        f'CREATE INDEX IF NOT EXISTS "{idx_name}" '
                        f'ON "{self.schema.name}" ({idx_expr})'
                    )
                except sqlite3.DatabaseError:
                    pass
            self.connection.commit()
        finally:
            cursor.close()

    def get_column_names(self) -> List[str]:
        return [col[0] for col in self.schema.columns]

    def _get_data_column_count(self) -> int:
        """Antal datakolumner (exkl. metadata-kolumner)."""
        return len(self.get_column_names()) - len(_META_COLUMNS)

    # ──────────────────────────────────────────────────────────────────────────
    # IMPORT OPERATIONS
    # ──────────────────────────────────────────────────────────────────────────

    def import_rows(
        self,
        rows: Sequence[Sequence[Any]],
        source_file: Optional[str] = None,
        validate: bool = True
    ) -> ImportResult:
        """Importera rader till databasen."""
        if not self._is_connected:
            raise RuntimeError(
                "Inte ansluten till databasen. Anropa connect() först."
            )

        if not rows:
            return ImportResult()

        start_time = time.perf_counter()
        result = ImportResult()
        timestamp = datetime.now().isoformat(timespec="seconds")

        for batch_start in range(0, len(rows), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(rows))
            batch = rows[batch_start:batch_end]

            batch_result = self._import_batch(
                batch,
                timestamp=timestamp,
                source_file=source_file,
                validate=validate,
                row_offset=batch_start
            )
            result = result + batch_result

        result.duration_ms = (time.perf_counter() - start_time) * 1000
        _log.info("Import klar: %s", result.summary())
        return result

    def _import_batch(
        self,
        rows: Sequence[Sequence[Any]],
        timestamp: str,
        source_file: Optional[str],
        validate: bool,
        row_offset: int
    ) -> ImportResult:
        """Importera en batch av rader."""
        result = ImportResult()
        prepared_rows: List[Tuple] = []

        for idx, row in enumerate(rows):
            global_idx = row_offset + idx
            try:
                if validate:
                    validation_error = self._validate_row(row)
                    if validation_error:
                        result.failed += 1
                        result.errors.append((global_idx, validation_error))
                        continue

                prepared = self._prepare_row(
                    row, timestamp=timestamp, source_file=source_file
                )
                prepared_rows.append(prepared)
            except Exception as e:
                result.failed += 1
                result.errors.append((global_idx, str(e)))

        if not prepared_rows:
            return result

        try:
            with self.transaction() as cursor:
                affected = self._batch_insert(cursor, prepared_rows)
        except sqlite3.IntegrityError as exc:
            # FAIL-semantik: hela batchen misslyckas utan att krascha
            # importen; övriga resolutioner ska inte nå hit.
            result.failed += len(prepared_rows)
            result.errors.append((row_offset, f"Konflikt: {exc}"))
            return result

        # Räkna resultat utifrån faktiskt påverkade rader (rowcount)
        affected = max(affected, 0)
        if self.conflict_resolution == ConflictResolution.IGNORE:
            result.inserted = affected
            result.skipped = max(len(prepared_rows) - affected, 0)
        elif self.conflict_resolution == ConflictResolution.UPDATE:
            result.updated = affected
        else:  # REPLACE (och FAIL som inte nått hit)
            result.inserted = affected

        return result

    def _validate_row(self, row: Sequence[Any]) -> Optional[str]:
        """Validera en rad."""
        if not row:
            return "Tom rad"
        vincode = row[0] if row else None
        if not vincode:
            return "Saknar VINCODE"
        vincode_str = str(vincode).strip().upper()
        if len(vincode_str) != 17:
            return f"Ogiltig VIN-längd: {len(vincode_str)}"
        invalid_chars = set(vincode_str) - set(
            "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
        )
        if invalid_chars:
            return f"Ogiltiga tecken i VIN: {invalid_chars}"
        return None

    def _prepare_row(
        self,
        row: Sequence[Any],
        timestamp: str,
        source_file: Optional[str]
    ) -> Tuple:
        """
        Förbered rad för insert.

        Justerar alltid radlängden till antalet datakolumner
        (pad med tomma strängar / trunkera) — förhindrar
        "table has N columns but M values were supplied".
        """
        data_count = self._get_data_column_count()

        values = list(row)
        if len(values) < data_count:
            values.extend([""] * (data_count - len(values)))
        elif len(values) > data_count:
            values = values[:data_count]

        if values:
            values[0] = str(values[0]).strip().upper()

        row_hash = self._calculate_hash(values)
        values.extend([timestamp, timestamp, source_file, row_hash])
        return tuple(values)

    def _calculate_hash(self, values: List[Any]) -> str:
        """Beräkna hash för en rad."""
        content = "|".join(str(v) if v is not None else "" for v in values)
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _batch_insert(self, cursor: sqlite3.Cursor, rows: List[Tuple]) -> int:
        """Utför batch insert. Returnerar antal påverkade rader (rowcount)."""
        if not rows:
            return 0

        columns = self.get_column_names()
        columns_sql = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(["?"] * len(columns))

        if self.conflict_resolution == ConflictResolution.REPLACE:
            sql = (
                f'INSERT OR REPLACE INTO "{self.schema.name}" '
                f'({columns_sql}) VALUES ({placeholders})'
            )
        elif self.conflict_resolution == ConflictResolution.IGNORE:
            sql = (
                f'INSERT OR IGNORE INTO "{self.schema.name}" '
                f'({columns_sql}) VALUES ({placeholders})'
            )
        elif self.conflict_resolution == ConflictResolution.UPDATE:
            update_cols = [
                c for c in columns
                if c not in ("VINCODE", "imported_at")
            ]
            update_sql = ", ".join(
                f'"{c}"=excluded."{c}"' for c in update_cols
            )
            sql = (
                f'INSERT INTO "{self.schema.name}" ({columns_sql}) '
                f'VALUES ({placeholders}) '
                f'ON CONFLICT("VINCODE") DO UPDATE SET {update_sql}'
            )
        else:
            sql = (
                f'INSERT INTO "{self.schema.name}" ({columns_sql}) '
                f'VALUES ({placeholders})'
            )

        cursor.executemany(sql, rows)
        return cursor.rowcount if cursor.rowcount is not None else len(rows)

    # ──────────────────────────────────────────────────────────────────────────
    # QUERY OPERATIONS
    # ──────────────────────────────────────────────────────────────────────────

    def get_by_vin(self, vincode: str) -> Optional[Dict[str, Any]]:
        """Hämta rad med VIN."""
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                f'SELECT * FROM "{self.schema.name}" WHERE "VINCODE" = ?',
                (str(vincode).strip().upper(),)
            )
            row = cursor.fetchone()
            if row:
                columns = self.get_column_names()
                return dict(zip(columns, row))
            return None
        finally:
            cursor.close()

    def count(self) -> int:
        """Räkna antal rader i tabellen."""
        cursor = self.connection.cursor()
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{self.schema.name}"')
            return cursor.fetchone()[0]
        finally:
            cursor.close()

    def get_statistics(self) -> Dict[str, Any]:
        """Hämta statistik om databasen."""
        cursor = self.connection.cursor()
        try:
            stats = {}
            cursor.execute(f'SELECT COUNT(*) FROM "{self.schema.name}"')
            stats["total_rows"] = cursor.fetchone()[0]

            cursor.execute(
                f'SELECT "MODELYEAR", COUNT(*) FROM "{self.schema.name}" '
                f'GROUP BY "MODELYEAR" ORDER BY "MODELYEAR" DESC LIMIT 10'
            )
            stats["by_model_year"] = dict(cursor.fetchall())

            cursor.execute(
                f'SELECT MAX("imported_at") FROM "{self.schema.name}"'
            )
            stats["latest_import"] = cursor.fetchone()[0]

            stats["db_size_mb"] = round(
                self.db_path.stat().st_size / (1024 * 1024), 2
            ) if self.db_path.exists() else 0

            return stats
        finally:
            cursor.close()

    # ──────────────────────────────────────────────────────────────────────────
    # MAINTENANCE
    # ──────────────────────────────────────────────────────────────────────────

    def vacuum(self) -> None:
        """Komprimera databasen."""
        _log.info("Kör VACUUM...")
        self.connection.execute("VACUUM")
        _log.info("VACUUM klar")

    def analyze(self) -> None:
        """Uppdatera query planner statistics."""
        _log.info("Kör ANALYZE...")
        self.connection.execute("ANALYZE")
        _log.info("ANALYZE klar")

    def optimize(self) -> None:
        """Kör full optimering (VACUUM + ANALYZE)."""
        self.vacuum()
        self.analyze()

    def __repr__(self) -> str:
        status = "connected" if self._is_connected else "disconnected"
        return f"<DatabaseImporter db={self.db_path.name} {status}>"


# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def ensure_table(cursor: sqlite3.Cursor) -> None:
    """Legacy-funktion för bakåtkompatibilitet."""
    schema = build_schema()
    cursor.execute(schema.to_create_sql())
    for idx_name, idx_expr in schema.indexes:
        try:
            cursor.execute(
                f'CREATE INDEX IF NOT EXISTS "{idx_name}" '
                f'ON "{schema.name}" ({idx_expr})'
            )
        except sqlite3.DatabaseError:
            pass


def batch_insert(
    cursor: sqlite3.Cursor,
    rows: List[List[Any]],
    timestamp: Optional[str] = None
) -> int:
    """
    Legacy-funktion för bakåtkompatibilitet.

    Bygger rader mot det FULLA schemat (inkl. source_file/row_hash)
    med längdjustering — konsistent med DatabaseImporter._prepare_row().
    """
    if not rows:
        return 0
    if timestamp is None:
        timestamp = datetime.now().isoformat(timespec="seconds")

    schema_cols = [c[0] for c in build_schema().columns]
    data_cols = [c for c in schema_cols if c not in _META_COLUMNS]

    columns_sql = ", ".join(f'"{c}"' for c in schema_cols)
    placeholders = ", ".join(["?"] * len(schema_cols))

    sql = (
        f'INSERT OR REPLACE INTO "modellregister" ({columns_sql}) '
        f'VALUES ({placeholders})'
    )

    prepared: List[Tuple] = []
    for row in rows:
        values = list(row)
        if len(values) < len(data_cols):
            values.extend([""] * (len(data_cols) - len(values)))
        elif len(values) > len(data_cols):
            values = values[:len(data_cols)]
        if values:
            values[0] = str(values[0]).strip().upper()
        content = "|".join(
            str(v) if v is not None else "" for v in values
        )
        row_hash = hashlib.md5(content.encode()).hexdigest()[:16]
        prepared.append(
            tuple(values) + (timestamp, timestamp, "", row_hash)
        )

    cursor.executemany(sql, prepared)
    return len(prepared)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "DatabaseImporter",
    "ImportResult",
    "TableSchema",
    "ConflictResolution",
    "build_schema",
    "ensure_table",
    "batch_insert",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]
