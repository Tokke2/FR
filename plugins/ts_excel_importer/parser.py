# -*- coding: utf-8 -*-
# Fil: plugins/ts_excel_importer/parser.py
"""
Excel-parser för TS-specifikationer v2.0.1

Hanterar:
    - Automatisk kolumndetektering
    - Flera ark (en posttyp per ark)
    - Olika namnkonventioner
    - Felhantering och varningar
    - Samarbete med ts_spec_import och ts_schema_manager

FÖRÄNDRINGAR v2.0.1 (granskad — spec v1.6 förbättringsregeln):
    - FIX (BUGG #5-mönster): hårdkodad rad "Copyright © 2025 ..." i
      docstringen BORTTAGEN — copyright genereras dynamiskt via
      get_copyright_string().
    - FIX (låst regel): logger/self._local_logger -> module-level _log;
      ALLA f-string-logganrop ersatta med lazy %s.
    - FIX (låst regel, atomer): export_parsed_to_json() skrev med öppen
      write() — korrupt JSON vid krasch. Nu mkstemp -> fsync ->
      os.replace (samma mönster som plugin.py _save_history).
    - FIX (typing): Optional[callable] -> Optional[Callable[...]] +
      Callable tillagd i typing-importen (annars NameError vid
      runtime-typkontroll/IDE).
    - FIX (korrekthet): _parse_row() raw_data byggdes med fel
      mapping-riktning (mapping.get(col) där col är excel-kolumn =
      VALUE i mapping, inte nyckel) — raw_data blev alltid tom/fel.
      Nu: col in mapping.values().
    - FIX (korrekthet, DATA-FÖRLUST): to_post_spec() — POSTTYP/PT-fält
      utan constant_value fick aldrig posttypen som värde → format_record
      genererade "00" i stället för "45" (fel posttyp i filen). Nu sätts
      constant_value = post_type automatiskt (samma fix som models.py
      create_empty_post_spec).
    - FIX (spec v1.11 KRAV 58): fil-huvud normaliserat — coding-rad
      före "# Fil:"-rad.
    - Header normaliserad: "# Fil: plugins/ts_excel_importer/parser.py".
    - Övrig logik OFÖRÄNDRAD (20 publika funktioner, dataclasses,
      kolumndetektering, posttypsdetektering, täckningsanalys,
      to_post_spec-konvertering).

FUNKTIONER (1-10): CORE PARSING
    1. get_sheet_info() - Hämta information om ark
    2. parse_sheet() - Parsa ett ark
    3. _auto_detect_columns() - Auto-detektera kolumner
    4. _detect_post_type() - Detektera posttyp
    5. _validate_sheet_structure() - Validera struktur
    6. _parse_row() - Parsa en rad
    7. _validate_fields() - Validera fält
    8. ensure_dependencies() - Kontrollera beroenden
    9. _check_pandas() - Kontrollera pandas
    10. _normalize_column_name() - Normalisera kolumnnamn

FUNKTIONER (11-20): ADVANCED PARSING
    11. validate_excel_format() - Validera Excel-format
    12. get_column_statistics() - Kolumnstatistik
    13. detect_header_row() - Auto-detektera header-rad
    14. parse_multiple_sheets() - Parsa flera ark
    15. export_parsed_to_json() - Exportera till JSON
    16. get_field_coverage_analysis() - Täckningsanalys
    17. suggest_field_mappings() - Föreslå mappningar
    18. validate_field_types() - Validera fälttyper
    19. normalize_field_names() - Normalisera fältnamn
    20. get_parser_diagnostics() - Parser-diagnostik
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Final, List, Optional, Set, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# COPYRIGHT & VERSION
# ══════════════════════════════════════════════════════════════════════════════

VERSION: str = "2.0.1"
AUTHOR: str = "Rickard Längkvist"
TS_POST_LENGTH: int = 2500
TS_ENCODING: str = "iso-8859-1"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


def _get_logger() -> logging.Logger:
    """Hämta logger. KRASCHSÄKER."""
    try:
        return logging.getLogger("ts_excel_importer.parser")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log = _get_logger()


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# Kolumnnamn-patterns för automatisk detektering
COLUMN_PATTERNS: Final[Dict[str, List[str]]] = {
    "position": [
        "pos", "position", "startpos", "start", "från", "from",
        "teckenposition", "tecken från", "fr.o", "fom", "fr.o.m",
        "startposition", "börjar", "begin"
    ],
    "end_position": [
        "t.o.m", "tom", "till", "slut", "end", "tecken till",
        "slutposition", "slutar", "end_pos", "endpos"
    ],
    "length": [
        "längd", "length", "len", "antal", "antal tecken",
        "size", "fältlängd", "ant", "storlek", "bredd", "width"
    ],
    "name": [
        "fältnamn", "namn", "name", "field", "fält", "rubrik",
        "dataelementnamn", "dataelement", "benämning", "id",
        "identifier", "fieldname", "field_name"
    ],
    "type": [
        "typ", "type", "format", "datatyp", "teckentyp", "a/n",
        "fieldtype", "field_type", "dataformat"
    ],
    "required": [
        "o/v", "oblig", "obligatorisk", "required", "mandatory",
        "krav", "måste", "ska finnas", "must", "nödvändig"
    ],
    "description": [
        "beskrivning", "description", "desc", "förklaring",
        "kommentar", "anmärkning", "info", "innehåll", "comment",
        "remarks", "notes", "anteckning"
    ],
    "valid_values": [
        "värdemängd", "värden", "values", "tillåtna", "allowed",
        "giltiga värden", "kodbeskrivning", "villkor", "valid",
        "constraints", "domain"
    ],
    "default": [
        "default", "standardvärde", "defaultvärde", "standard",
        "initial", "defaultvalue", "default_value"
    ],
    "source_field": [
        "källa", "source", "mappning", "sap-fält", "dispatch-fält",
        "från system", "datakälla", "source_field", "mapping",
        "käll-fält", "origin"
    ],
    "constant_value": [
        "konstant", "constant", "fast värde", "fixed", "const",
        "constant_value", "fixed_value"
    ],
}

# TS-typkoder
TS_TYPE_MAPPING: Final[Dict[str, str]] = {
    "n": "numeric",
    "num": "numeric",
    "numeric": "numeric",
    "numerisk": "numeric",
    "siffror": "numeric",
    "number": "numeric",
    "integer": "numeric",
    "int": "numeric",
    "a": "alphanumeric",
    "an": "alphanumeric",
    "alpha": "alphanumeric",
    "alfabetisk": "alphanumeric",
    "alfanumerisk": "alphanumeric",
    "alphanumeric": "alphanumeric",
    "text": "alphanumeric",
    "string": "alphanumeric",
    "str": "alphanumeric",
    "d": "date",
    "date": "date",
    "datum": "date",
    "k": "constant",
    "konstant": "constant",
    "const": "constant",
    "constant": "constant",
    "fixed": "constant",
}

# Kända posttyper
KNOWN_POST_TYPES: Final[Dict[str, Dict[str, Any]]] = {
    "28": {
        "name": "Identitetspost",
        "description": "Filhuvud med organisationsnummer och filidentitet",
        "aliases": ["identitet", "identity", "header", "huvud", "id"],
        "position": "first",
    },
    "45": {
        "name": "Registreringspost",
        "description": "Fordonsdata för registrering",
        "aliases": ["registrering", "registration", "fordon", "vehicle", "reg"],
        "position": "middle",
    },
    "99": {
        "name": "Slutpost",
        "description": "Filavslut med kontrollsumma",
        "aliases": ["slut", "end", "avslut", "footer", "trailer"],
        "position": "last",
    },
}

# Stödda filformat
SUPPORTED_EXTENSIONS: Final[List[str]] = [".xlsx", ".xls", ".xlsm", ".xlsb"]


# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SheetInfo:
    """Information om ett ark i Excel-filen."""
    name: str
    row_count: int
    column_count: int
    columns: List[str]
    detected_post_type: str = ""
    detected_post_name: str = ""
    is_valid: bool = False
    validation_errors: List[str] = field(default_factory=list)
    has_data: bool = False
    header_row: int = 0

    @property
    def post_type(self) -> str:
        """Alias för detected_post_type."""
        return self.detected_post_type

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedField:
    """Parserat fält (innan konvertering till FieldSpec)."""
    name: str
    position: int
    length: int
    field_type: str = "alphanumeric"
    required: bool = True
    description: str = ""
    valid_values: List[str] = field(default_factory=list)
    default: str = ""
    source_mapping: str = ""
    constant_value: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def end_position(self) -> int:
        """Slutposition (inklusive)."""
        return self.position + self.length - 1

    @property
    def type_code(self) -> str:
        """Kort typkod."""
        return {
            "numeric": "N",
            "alphanumeric": "AN",
            "date": "D",
            "constant": "K",
        }.get(self.field_type, "AN")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "length": self.length,
            "field_type": self.field_type,
            "required": self.required,
            "description": self.description,
            "valid_values": self.valid_values,
            "default": self.default,
            "source_mapping": self.source_mapping,
            "constant_value": self.constant_value,
            "end_position": self.end_position,
            "type_code": self.type_code,
        }


@dataclass
class ParsedSpec:
    """Resultat från parsning av ett Excel-ark."""
    sheet_name: str
    post_type: str
    post_name: str
    total_length: int
    fields: List[ParsedField]
    source_file: str = ""
    parse_warnings: List[str] = field(default_factory=list)
    column_mapping: Dict[str, str] = field(default_factory=dict)
    created_at: str = ""
    checksum: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.checksum:
            self.checksum = self._calculate_checksum()

    def _calculate_checksum(self) -> str:
        """Beräkna checksumma för specifikationen."""
        content = json.dumps([f.to_dict() for f in self.fields], sort_keys=True)
        return hashlib.md5(content.encode()).hexdigest()[:12]

    @property
    def is_valid(self) -> bool:
        return bool(self.post_type and self.fields)

    @property
    def field_count(self) -> int:
        return len(self.fields)

    @property
    def coverage(self) -> float:
        """Täckningsgrad (0.0-1.0)."""
        if self.total_length == 0:
            return 0.0
        covered = set()
        for f in self.fields:
            covered.update(range(f.position, f.end_position + 1))
        return len(covered) / self.total_length

    @property
    def required_field_count(self) -> int:
        return sum(1 for f in self.fields if f.required)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sheet_name": self.sheet_name,
            "post_type": self.post_type,
            "post_name": self.post_name,
            "total_length": self.total_length,
            "fields": [f.to_dict() for f in self.fields],
            "source_file": self.source_file,
            "parse_warnings": self.parse_warnings,
            "column_mapping": self.column_mapping,
            "created_at": self.created_at,
            "checksum": self.checksum,
            "is_valid": self.is_valid,
            "field_count": self.field_count,
            "coverage": self.coverage,
            "required_field_count": self.required_field_count,
        }

    def to_post_spec(self, version: str = "") -> Any:
        """
        Konvertera till PostSpec för ts_schema_manager.

        Args:
            version: Version att sätta

        Returns:
            PostSpec-objekt eller None
        """
        try:
            # Försök importera från ts_schema_manager
            try:
                from plugins.ts_schema_manager.models import PostSpec, FieldSpec
            except ImportError:
                # Fallback: ts_spec_import
                try:
                    from plugins.ts_spec_import.models import PostSpec, FieldSpec
                except ImportError:
                    _log.warning("Kunde inte importera PostSpec/FieldSpec")
                    return None

            fields = []
            for f in self.fields:
                constant_value = f.constant_value
                # DATA-FÖRLUST-FIX (v2.0.1): POSTTYP/PT-fält ska alltid
                # vara konstant = post_type. Utan detta formateras
                # posttypen till "00" när data saknas (samma bugg som
                # models.py create_empty_post_spec — åtgärdad där).
                if (
                    f.name in ("POSTTYP", "PT")
                    and not constant_value
                    and self.post_type
                ):
                    constant_value = self.post_type

                field_spec = FieldSpec(
                    name=f.name,
                    position=f.position,
                    length=f.length,
                    field_type=f.field_type,
                    mandatory=f.required,
                    description=f.description,
                    valid_values=f.valid_values,
                    default=f.default,
                    source_mapping=f.source_mapping,
                    constant_value=constant_value,
                )
                fields.append(field_spec)

            return PostSpec(
                post_type=self.post_type,
                name=self.post_name,
                total_length=self.total_length,
                fields=fields,
                source_file=self.source_file,
                version=version,
            )

        except Exception as e:
            _log.error("Kunde inte konvertera till PostSpec: %s", e)
            return None


@dataclass
class ColumnStatistics:
    """Statistik om kolumner i ett ark."""
    column_name: str
    non_empty_count: int
    empty_count: int
    unique_values: int
    numeric_count: int
    sample_values: List[str]
    detected_type: str = "unknown"
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CoverageAnalysis:
    """Detaljerad täckningsanalys."""
    total_length: int
    covered_positions: int
    coverage_percent: float
    gaps: List[Dict[str, int]]
    overlaps: List[Dict[str, Any]]
    field_distribution: Dict[str, int]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════════════
# PARSER CLASS
# ══════════════════════════════════════════════════════════════════════════════

class TSExcelParser:
    """
    Parser för Transportstyrelsens Excel-specifikationer v2.0.1

    20 publika funktioner för komplett Excel-parsning.
    Samarbetar med ts_spec_import och ts_schema_manager.

    Användning:
        parser = TSExcelParser()

        # Analysera fil
        sheets = parser.get_sheet_info(Path("spec.xlsx"))

        # Parsa ett ark
        parsed = parser.parse_sheet(Path("spec.xlsx"), "PT45")

        # Exportera till JSON
        parser.export_parsed_to_json(parsed, Path("output.json"))
    """

    VERSION = VERSION
    AUTHOR = AUTHOR

    def __init__(self):
        self._pandas_available = self._check_pandas()
        self._openpyxl_available = self._check_openpyxl()
        self._parse_count = 0
        self._last_error: Optional[str] = None

    @property
    def copyright(self) -> str:
        """Dynamisk copyright-sträng."""
        return get_copyright_string()

    # ═══════════════════════════════════════════════════════════════════════════
    # FUNCTIONS 1-10: CORE PARSING
    # ═══════════════════════════════════════════════════════════════════════════

    def get_sheet_info(self, filepath: Path) -> List[SheetInfo]:
        """
        1. Hämta information om alla ark. KRASCHSÄKER.

        Args:
            filepath: Sökväg till Excel-fil

        Returns:
            Lista med SheetInfo
        """
        try:
            self.ensure_dependencies()
            import pandas as pd

            sheets = []
            filepath = Path(filepath)

            xl = pd.ExcelFile(filepath)

            for sheet_name in xl.sheet_names:
                try:
                    df = pd.read_excel(xl, sheet_name=sheet_name, nrows=100)
                    df = df.dropna(how='all')

                    if df.empty:
                        sheets.append(SheetInfo(
                            name=sheet_name,
                            row_count=0,
                            column_count=0,
                            columns=[],
                            is_valid=False,
                            has_data=False,
                            validation_errors=["Arket är tomt"]
                        ))
                        continue

                    columns = [str(c).strip() for c in df.columns]
                    post_type, post_name = self._detect_post_type(sheet_name)
                    is_valid, errors = self._validate_sheet_structure(columns)

                    # Detektera header-rad
                    header_row = self.detect_header_row(filepath, sheet_name)

                    sheets.append(SheetInfo(
                        name=sheet_name,
                        row_count=len(df),
                        column_count=len(columns),
                        columns=columns,
                        detected_post_type=post_type,
                        detected_post_name=post_name or sheet_name,
                        is_valid=is_valid,
                        has_data=True,
                        header_row=header_row,
                        validation_errors=errors
                    ))

                except Exception as e:
                    sheets.append(SheetInfo(
                        name=sheet_name,
                        row_count=0,
                        column_count=0,
                        columns=[],
                        is_valid=False,
                        has_data=False,
                        validation_errors=[str(e)]
                    ))

            xl.close()
            return sheets

        except Exception as e:
            self._last_error = str(e)
            _log.error("get_sheet_info misslyckades: %s", e)
            return []

    def parse_sheet(
        self,
        filepath: Path,
        sheet_name: str,
        column_mapping: Optional[Dict[str, str]] = None,
        post_type: Optional[str] = None,
        post_name: Optional[str] = None,
        total_length: int = TS_POST_LENGTH,
        header_row: int = 0
    ) -> ParsedSpec:
        """
        2. Parsa ett ark till ParsedSpec. KRASCHSÄKER.

        Args:
            filepath: Sökväg till Excel-fil
            sheet_name: Arknamn att parsa
            column_mapping: Manuell kolumnmappning {target -> excel_col}
            post_type: Posttyp (eller None för auto-detect)
            post_name: Postnamn (eller None för auto-detect)
            total_length: Total postlängd
            header_row: Rad med kolumnrubriker (0-baserad)

        Returns:
            ParsedSpec
        """
        try:
            self.ensure_dependencies()
            import pandas as pd

            filepath = Path(filepath)

            df = pd.read_excel(
                filepath,
                sheet_name=sheet_name,
                dtype=str,
                header=header_row
            )
            df = df.fillna("")

            # Ta bort helt tomma rader
            df = df[df.astype(str).apply(
                lambda x: x.str.strip().str.len().sum(), axis=1
            ) > 0]

            if df.empty:
                return ParsedSpec(
                    sheet_name=sheet_name,
                    post_type="",
                    post_name="",
                    total_length=total_length,
                    fields=[],
                    source_file=str(filepath),
                    parse_warnings=["Arket är tomt"]
                )

            # Kolumnmappning
            columns = [str(c).strip() for c in df.columns]
            if column_mapping is None:
                column_mapping = self._auto_detect_columns(columns)

            # Posttyp och namn
            if post_type is None:
                post_type, _ = self._detect_post_type(sheet_name)
            if post_name is None:
                _, post_name = self._detect_post_type(sheet_name)
                post_name = post_name or sheet_name

            # Parsa fält
            fields = []
            warnings = []

            for idx, row in df.iterrows():
                try:
                    parsed_field = self._parse_row(row, column_mapping, int(idx))
                    if parsed_field:
                        fields.append(parsed_field)
                except Exception as e:
                    warnings.append(f"Rad {idx + 2}: {e}")

            # Sortera på position
            fields.sort(key=lambda f: f.position)

            # Normalisera fältnamn
            fields = self._ensure_unique_names(fields)

            # Validera
            validation_warnings = self._validate_fields(fields, total_length)
            warnings.extend(validation_warnings)

            self._parse_count += 1

            return ParsedSpec(
                sheet_name=sheet_name,
                post_type=post_type,
                post_name=post_name,
                total_length=total_length,
                fields=fields,
                source_file=str(filepath),
                parse_warnings=warnings,
                column_mapping=column_mapping
            )

        except Exception as e:
            self._last_error = str(e)
            _log.error("parse_sheet misslyckades: %s", e)
            return ParsedSpec(
                sheet_name=sheet_name,
                post_type=post_type or "",
                post_name=post_name or sheet_name,
                total_length=total_length,
                fields=[],
                source_file=str(filepath) if filepath else "",
                parse_warnings=[f"Parse misslyckades: {e}"]
            )

    def _auto_detect_columns(self, columns: List[str]) -> Dict[str, str]:
        """
        3. Automatisk kolumndetektering. KRASCHSÄKER.

        Args:
            columns: Lista med kolumnnamn

        Returns:
            Dict med mappning {target: excel_column}
        """
        try:
            mapping = {}
            used_columns: Set[str] = set()

            for target, patterns in COLUMN_PATTERNS.items():
                best_match = None
                best_score = 0.0

                for col in columns:
                    if col in used_columns:
                        continue

                    col_lower = self._normalize_column_name(col)

                    # Exakt match
                    if col_lower in patterns:
                        best_match = col
                        best_score = 1.0
                        break

                    # Partial match
                    for pattern in patterns:
                        if pattern in col_lower:
                            score = len(pattern) / max(len(col_lower), 1)
                            if score > best_score:
                                best_match = col
                                best_score = score
                        elif col_lower in pattern:
                            score = len(col_lower) / max(len(pattern), 1) * 0.8
                            if score > best_score:
                                best_match = col
                                best_score = score

                if best_match and best_score >= 0.25:
                    mapping[target] = best_match
                    used_columns.add(best_match)

            return mapping

        except Exception as e:
            _log.error("_auto_detect_columns misslyckades: %s", e)
            return {}

    def _detect_post_type(self, sheet_name: str) -> Tuple[str, str]:
        """
        4. Detektera posttyp från arknamn. KRASCHSÄKER.

        Args:
            sheet_name: Arknamn

        Returns:
            Tuple (posttyp, postnamn)
        """
        try:
            name_lower = sheet_name.lower().strip()

            # Sök efter kända posttyper
            for post_type, info in KNOWN_POST_TYPES.items():
                # Direkt match på nummer
                if post_type in name_lower:
                    return post_type, info["name"]

                # Match på namn
                if info["name"].lower() in name_lower:
                    return post_type, info["name"]

                # Match på alias
                for alias in info.get("aliases", []):
                    if alias in name_lower:
                        return post_type, info["name"]

            # Sök efter nummer
            match = re.search(r'(\d{2})', sheet_name)
            if match:
                pt = match.group(1)
                if pt in KNOWN_POST_TYPES:
                    return pt, KNOWN_POST_TYPES[pt]["name"]
                return pt, f"Posttyp {pt}"

            return "", sheet_name

        except Exception:
            return "", sheet_name

    def _validate_sheet_structure(
        self,
        columns: List[str]
    ) -> Tuple[bool, List[str]]:
        """
        5. Validera att arket ser ut som en specifikation. KRASCHSÄKER.

        Args:
            columns: Lista med kolumnnamn

        Returns:
            Tuple (is_valid, errors)
        """
        try:
            errors = []
            columns_lower = [self._normalize_column_name(c) for c in columns]

            has_position = any(
                any(p in c for p in COLUMN_PATTERNS["position"])
                for c in columns_lower
            )
            if not has_position:
                errors.append("Saknar positionskolumn")

            has_length_or_end = any(
                any(p in c for p in COLUMN_PATTERNS["length"])
                for c in columns_lower
            ) or any(
                any(p in c for p in COLUMN_PATTERNS["end_position"])
                for c in columns_lower
            )
            if not has_length_or_end:
                errors.append("Saknar längd- eller slutpositionskolumn")

            has_name = any(
                any(p in c for p in COLUMN_PATTERNS["name"])
                for c in columns_lower
            )
            if not has_name:
                errors.append("Saknar fältnamnkolumn (rekommenderat)")

            return len(errors) == 0 or (len(errors) == 1 and "Saknar fältnamnkolumn" in errors[0]), errors

        except Exception as e:
            return False, [str(e)]

    def _parse_row(
        self,
        row: Any,
        mapping: Dict[str, str],
        row_idx: int
    ) -> Optional[ParsedField]:
        """
        6. Parsa en rad till ParsedField. KRASCHSÄKER.

        Args:
            row: Pandas row
            mapping: Kolumnmappning
            row_idx: Radindex

        Returns:
            ParsedField eller None
        """
        try:
            def get_value(key: str) -> str:
                col = mapping.get(key)
                if col and col in row.index:
                    val = row[col]
                    return str(val).strip() if val and str(val).strip() not in ['nan', 'NaN', 'None'] else ""
                return ""

            # Position (obligatorisk)
            pos_str = get_value("position")
            if not pos_str:
                return None

            try:
                position = int(re.sub(r'[^\d]', '', pos_str))
            except ValueError:
                return None

            if position < 1:
                return None

            # Längd
            length_str = get_value("length")
            end_pos_str = get_value("end_position")

            length = 0
            if length_str:
                try:
                    length = int(re.sub(r'[^\d]', '', length_str))
                except ValueError:
                    pass

            if length == 0 and end_pos_str:
                try:
                    end_pos = int(re.sub(r'[^\d]', '', end_pos_str))
                    length = end_pos - position + 1
                except ValueError:
                    pass

            if length < 1:
                return None

            # Namn
            name = get_value("name")
            if not name:
                name = f"FIELD_{position}"

            name = self._normalize_field_name(name)

            # Typ
            type_str = get_value("type").lower().strip()
            field_type = TS_TYPE_MAPPING.get(type_str, "alphanumeric")

            # Obligatorisk
            req_str = get_value("required").lower()
            required = req_str not in ("v", "valfri", "optional", "nej", "n", "no", "false", "0", "")

            # Övriga fält
            description = get_value("description")[:500]

            valid_str = get_value("valid_values")
            valid_values = []
            if valid_str:
                valid_values = [
                    v.strip()
                    for v in re.split(r'[,;/\n]', valid_str)
                    if v.strip()
                ][:50]

            default = get_value("default")
            source_mapping = get_value("source_field")
            constant_value = get_value("constant_value")

            # Spara raw data för debugging (endast mappade excel-kolumner)
            raw_data = {
                col: str(row.get(col, ""))[:100]
                for col in row.index
                if col in mapping.values()
            }

            return ParsedField(
                name=name,
                position=position,
                length=length,
                field_type=field_type,
                required=required,
                description=description,
                valid_values=valid_values,
                default=default,
                source_mapping=source_mapping,
                constant_value=constant_value,
                raw_data=raw_data,
            )

        except Exception as e:
            _log.debug("_parse_row misslyckades: %s", e)
            return None

    def _validate_fields(
        self,
        fields: List[ParsedField],
        total_length: int
    ) -> List[str]:
        """
        7. Validera fält och returnera varningar. KRASCHSÄKER.

        Args:
            fields: Lista med fält
            total_length: Total postlängd

        Returns:
            Lista med varningar
        """
        try:
            warnings = []

            if not fields:
                return ["Inga fält parsade"]

            # Kontrollera överlapp
            positions: Dict[int, str] = {}
            for f in fields:
                for pos in range(f.position, f.end_position + 1):
                    if pos in positions:
                        warnings.append(
                            f"Överlapp vid pos {pos}: '{positions[pos]}' och '{f.name}'"
                        )
                    else:
                        positions[pos] = f.name

            # Kontrollera bounds
            if fields:
                max_end = max(f.end_position for f in fields)
                if max_end > total_length:
                    warnings.append(
                        f"Fält överskrider total längd ({max_end} > {total_length})"
                    )

            # Kontrollera täckning
            coverage = len(positions) / total_length if total_length > 0 else 0
            if coverage < 0.5:
                warnings.append(f"Låg täckning: {coverage:.0%} av postlängden")

            # Kontrollera dubbletter
            names = [f.name for f in fields]
            duplicates = [n for n in set(names) if names.count(n) > 1]
            if duplicates:
                warnings.append(f"Dubbletter: {', '.join(duplicates)}")

            return warnings

        except Exception as e:
            return [f"Valideringsfel: {e}"]

    def ensure_dependencies(self) -> None:
        """
        8. Kontrollera att dependencies finns. KRASCHSÄKER.

        Raises:
            ImportError om pandas/openpyxl saknas
        """
        if not self._pandas_available:
            raise ImportError(
                "pandas krävs för Excel-import. "
                "Installera med: pip install pandas"
            )
        if not self._openpyxl_available:
            raise ImportError(
                "openpyxl krävs för Excel-import. "
                "Installera med: pip install openpyxl"
            )

    def _check_pandas(self) -> bool:
        """
        9. Kontrollera om pandas finns. KRASCHSÄKER.

        Returns:
            True om pandas är tillgänglig
        """
        try:
            import pandas as pd
            return True
        except ImportError:
            return False

    def _check_openpyxl(self) -> bool:
        """Kontrollera om openpyxl finns. KRASCHSÄKER."""
        try:
            import openpyxl
            return True
        except ImportError:
            return False

    def _normalize_column_name(self, name: str) -> str:
        """
        10. Normalisera kolumnnamn. KRASCHSÄKER.

        Args:
            name: Kolumnnamn

        Returns:
            Normaliserat namn
        """
        try:
            return name.lower().strip().replace("_", " ").replace("-", " ")
        except Exception:
            return str(name).lower()

    def _normalize_field_name(self, name: str) -> str:
        """Normalisera fältnamn. KRASCHSÄKER."""
        try:
            # Ta bort specialtecken
            name = re.sub(r'[^\w\s\-åäöÅÄÖ]', '', name)
            # Ersätt mellanslag
            name = name.replace(' ', '_').upper()
            # Begränsa längd
            name = name[:50]
            # Säkerställ inte tomt
            return name or "UNNAMED"
        except Exception:
            return "FIELD"

    def _ensure_unique_names(self, fields: List[ParsedField]) -> List[ParsedField]:
        """Säkerställ unika fältnamn. KRASCHSÄKER."""
        try:
            seen = {}
            for f in fields:
                if f.name in seen:
                    seen[f.name] += 1
                    f.name = f"{f.name}_{seen[f.name]}"
                else:
                    seen[f.name] = 0
            return fields
        except Exception:
            return fields

    # ═══════════════════════════════════════════════════════════════════════════
    # FUNCTIONS 11-20: ADVANCED PARSING
    # ═══════════════════════════════════════════════════════════════════════════

    def validate_excel_format(self, filepath: Path) -> Dict[str, Any]:
        """
        11. Validera Excel-filformat. KRASCHSÄKER.

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
            "format": None,
            "sheets": [],
            "errors": [],
            "warnings": [],
        }

        try:
            filepath = Path(filepath)
            result["exists"] = filepath.exists()

            if not result["exists"]:
                result["errors"].append(f"Filen finns inte: {filepath}")
                return result

            # Kontrollera filtyp
            ext = filepath.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                result["errors"].append(f"Filtyp stöds inte: {ext}")
                result["warnings"].append(f"Stödda format: {', '.join(SUPPORTED_EXTENSIONS)}")
                return result

            result["format"] = ext

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

            # Kontrollera storlek
            file_size_mb = filepath.stat().st_size / (1024 * 1024)
            if file_size_mb > 50:
                result["warnings"].append(f"Stor fil: {file_size_mb:.1f} MB")

            result["valid"] = len(result["errors"]) == 0

        except Exception as e:
            result["errors"].append(str(e))

        return result

    def get_column_statistics(self, filepath: Path, sheet_name: str) -> List[ColumnStatistics]:
        """
        12. Hämta statistik om kolumner. KRASCHSÄKER.

        Args:
            filepath: Sökväg till fil
            sheet_name: Arknamn

        Returns:
            Lista med ColumnStatistics
        """
        try:
            self.ensure_dependencies()
            import pandas as pd

            df = pd.read_excel(filepath, sheet_name=sheet_name, dtype=str)
            df = df.fillna("")

            stats = []

            for col in df.columns:
                values = df[col].astype(str).str.strip()
                non_empty = values[values != ""]

                # Detektera typ
                numeric_count = sum(1 for v in non_empty if re.match(r'^[\d,.\-+]+$', v))
                detected_type = "numeric" if numeric_count > len(non_empty) * 0.8 else "text"

                # Beräkna confidence
                if len(non_empty) == 0:
                    confidence = 0.0
                else:
                    confidence = numeric_count / len(non_empty) if detected_type == "numeric" else 1.0

                stats.append(ColumnStatistics(
                    column_name=str(col),
                    non_empty_count=len(non_empty),
                    empty_count=len(values) - len(non_empty),
                    unique_values=non_empty.nunique(),
                    numeric_count=numeric_count,
                    sample_values=non_empty.head(5).tolist(),
                    detected_type=detected_type,
                    confidence=confidence,
                ))

            return stats

        except Exception as e:
            _log.error("get_column_statistics misslyckades: %s", e)
            return []

    def detect_header_row(self, filepath: Path, sheet_name: str, max_rows: int = 10) -> int:
        """
        13. Auto-detektera header-rad. KRASCHSÄKER.

        Args:
            filepath: Sökväg till fil
            sheet_name: Arknamn
            max_rows: Max rader att söka i

        Returns:
            Index för header-rad (0-baserad)
        """
        try:
            self.ensure_dependencies()
            import pandas as pd

            df = pd.read_excel(filepath, sheet_name=sheet_name, header=None, nrows=max_rows)

            best_row = 0
            best_score = 0

            for i in range(min(max_rows, len(df))):
                row_values = [str(v).lower().strip() for v in df.iloc[i] if pd.notna(v)]

                # Räkna matchande kolumnnamn
                score = 0
                for val in row_values:
                    for patterns in COLUMN_PATTERNS.values():
                        if any(p in val for p in patterns):
                            score += 1
                            break

                if score > best_score:
                    best_score = score
                    best_row = i

            return best_row

        except Exception as e:
            _log.error("detect_header_row misslyckades: %s", e)
            return 0

    def parse_multiple_sheets(
        self,
        filepath: Path,
        sheet_configs: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[ParsedSpec]:
        """
        14. Parsa flera ark samtidigt. KRASCHSÄKER.

        Args:
            filepath: Sökväg till fil
            sheet_configs: Lista med konfigurationer
            progress_callback: Progress callback

        Returns:
            Lista med ParsedSpec
        """
        results = []

        try:
            for i, config in enumerate(sheet_configs):
                if progress_callback:
                    try:
                        progress_callback(i + 1, len(sheet_configs), config.get("sheet_name", ""))
                    except Exception:
                        pass

                try:
                    parsed = self.parse_sheet(
                        filepath=filepath,
                        sheet_name=config["sheet_name"],
                        column_mapping=config.get("column_mapping"),
                        post_type=config.get("post_type"),
                        post_name=config.get("post_name"),
                        total_length=config.get("total_length", TS_POST_LENGTH),
                        header_row=config.get("header_row", 0),
                    )
                    results.append(parsed)
                except Exception as e:
                    _log.error(
                        "Kunde inte parsaa ark %s: %s",
                        config.get("sheet_name"),
                        e,
                    )

        except Exception as e:
            _log.error("parse_multiple_sheets misslyckades: %s", e)

        return results

    def export_parsed_to_json(self, parsed: ParsedSpec, output_path: Path) -> bool:
        """
        15. Exportera parsad spec till JSON ATOMISKT. KRASCHSÄKER.

        Args:
            parsed: Parsad specifikation
            output_path: Output-sökväg

        Returns:
            True vid success
        """
        try:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(
                dir=str(output_path.parent),
                prefix=".export_",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(parsed.to_dict(), f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(output_path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            _log.info("Exporterade till %s", output_path)
            return True

        except Exception as e:
            _log.error("export_parsed_to_json misslyckades: %s", e)
            return False

    def get_field_coverage_analysis(self, parsed: ParsedSpec) -> CoverageAnalysis:
        """
        16. Detaljerad täckningsanalys. KRASCHSÄKER.

        Args:
            parsed: Parsad specifikation

        Returns:
            CoverageAnalysis
        """
        try:
            total_length = parsed.total_length

            # Hitta täckta positioner
            covered = set()
            field_distribution = {"numeric": 0, "alphanumeric": 0, "date": 0, "constant": 0}

            for f in parsed.fields:
                covered.update(range(f.position, f.end_position + 1))
                field_distribution[f.field_type] = field_distribution.get(f.field_type, 0) + 1

            # Hitta luckor
            all_positions = set(range(1, total_length + 1))
            gap_positions = sorted(all_positions - covered)

            gaps = []
            if gap_positions:
                start = gap_positions[0]
                end = gap_positions[0]

                for pos in gap_positions[1:]:
                    if pos == end + 1:
                        end = pos
                    else:
                        gaps.append({"start": start, "end": end, "length": end - start + 1})
                        start = end = pos

                gaps.append({"start": start, "end": end, "length": end - start + 1})

            # Hitta överlapp
            overlaps = []
            positions_map: Dict[int, List[str]] = {}
            for f in parsed.fields:
                for pos in range(f.position, f.end_position + 1):
                    if pos not in positions_map:
                        positions_map[pos] = []
                    positions_map[pos].append(f.name)

            for pos, fields in positions_map.items():
                if len(fields) > 1:
                    overlaps.append({"position": pos, "fields": fields})

            # Varningar
            warnings = []
            coverage = len(covered) / total_length if total_length > 0 else 0

            if coverage < 0.5:
                warnings.append(f"Låg täckning: {coverage:.1%}")
            if gaps:
                warnings.append(f"{len(gaps)} luckor hittades")
            if overlaps:
                warnings.append(f"{len(overlaps)} överlapp hittades")

            return CoverageAnalysis(
                total_length=total_length,
                covered_positions=len(covered),
                coverage_percent=coverage * 100,
                gaps=gaps,
                overlaps=overlaps,
                field_distribution=field_distribution,
                warnings=warnings,
            )

        except Exception as e:
            _log.error("get_field_coverage_analysis misslyckades: %s", e)
            return CoverageAnalysis(
                total_length=parsed.total_length if parsed else 0,
                covered_positions=0,
                coverage_percent=0.0,
                gaps=[],
                overlaps=[],
                field_distribution={},
                warnings=[str(e)],
            )

    def suggest_field_mappings(
        self,
        parsed: ParsedSpec,
        source_fields: List[str]
    ) -> Dict[str, str]:
        """
        17. Föreslå mappningar mellan schema-fält och källfält. KRASCHSÄKER.

        Args:
            parsed: Parsad specifikation
            source_fields: Tillgängliga källfält

        Returns:
            Dict med förslag {schema_field: source_field}
        """
        suggestions = {}

        try:
            source_normalized = {self._normalize_column_name(s): s for s in source_fields}

            for field in parsed.fields:
                field_norm = self._normalize_column_name(field.name)

                # Exakt match
                if field_norm in source_normalized:
                    suggestions[field.name] = source_normalized[field_norm]
                    continue

                # Partial match
                best_match = None
                best_score = 0.0

                for source_norm, source_orig in source_normalized.items():
                    # Kontrollera innehåll
                    if field_norm in source_norm or source_norm in field_norm:
                        score = len(min(field_norm, source_norm, key=len)) / len(max(field_norm, source_norm, key=len))
                        if score > best_score:
                            best_score = score
                            best_match = source_orig

                if best_match and best_score > 0.5:
                    suggestions[field.name] = best_match

        except Exception as e:
            _log.error("suggest_field_mappings misslyckades: %s", e)

        return suggestions

    def validate_field_types(self, parsed: ParsedSpec) -> Dict[str, Any]:
        """
        18. Validera fälttypskonsistens. KRASCHSÄKER.

        Args:
            parsed: Parsad specifikation

        Returns:
            Dict med valideringsresultat
        """
        result = {
            "valid": True,
            "fields_checked": 0,
            "issues": [],
            "type_distribution": {},
        }

        try:
            for field in parsed.fields:
                result["fields_checked"] += 1

                # Räkna typfördelning
                ft = field.field_type
                result["type_distribution"][ft] = result["type_distribution"].get(ft, 0) + 1

                # Kontrollera konstanter
                if field.field_type == "constant" and not field.constant_value and not field.default:
                    result["issues"].append({
                        "field": field.name,
                        "issue": "Konstant utan värde",
                        "severity": "warning",
                    })

                # Kontrollera numeriska fält
                if field.field_type == "numeric" and field.default:
                    if not re.match(r'^[\d,.\-+]+$', field.default):
                        result["issues"].append({
                            "field": field.name,
                            "issue": f"Icke-numeriskt default: '{field.default}'",
                            "severity": "warning",
                        })

                # Kontrollera längder
                if field.length > 100:
                    result["issues"].append({
                        "field": field.name,
                        "issue": f"Ovanligt långt fält: {field.length}",
                        "severity": "info",
                    })

            result["valid"] = not any(i["severity"] == "error" for i in result["issues"])

        except Exception as e:
            result["issues"].append({"field": "*", "issue": str(e), "severity": "error"})
            result["valid"] = False

        return result

    def normalize_field_names(self, parsed: ParsedSpec) -> ParsedSpec:
        """
        19. Normalisera alla fältnamn. KRASCHSÄKER.

        Args:
            parsed: Parsad specifikation

        Returns:
            Ny ParsedSpec med normaliserade namn
        """
        try:
            normalized_fields = []
            seen_names = {}

            for field in parsed.fields:
                # Normalisera namn
                name = self._normalize_field_name(field.name)

                # Hantera dubbletter
                if name in seen_names:
                    seen_names[name] += 1
                    name = f"{name}_{seen_names[name]}"
                else:
                    seen_names[name] = 0

                # Skapa nytt fält
                new_field = ParsedField(
                    name=name,
                    position=field.position,
                    length=field.length,
                    field_type=field.field_type,
                    required=field.required,
                    description=field.description,
                    valid_values=field.valid_values,
                    default=field.default,
                    source_mapping=field.source_mapping,
                    constant_value=field.constant_value,
                    raw_data=field.raw_data,
                )
                normalized_fields.append(new_field)

            return ParsedSpec(
                sheet_name=parsed.sheet_name,
                post_type=parsed.post_type,
                post_name=parsed.post_name,
                total_length=parsed.total_length,
                fields=normalized_fields,
                source_file=parsed.source_file,
                parse_warnings=parsed.parse_warnings + ["Field names normalized"],
                column_mapping=parsed.column_mapping,
            )

        except Exception as e:
            _log.error("normalize_field_names misslyckades: %s", e)
            return parsed

    def get_parser_diagnostics(self) -> Dict[str, Any]:
        """
        20. Hämta parser-diagnostik. KRASCHSÄKER.

        Returns:
            Dict med diagnostikinformation
        """
        return {
            "parser_version": self.VERSION,
            "author": self.AUTHOR,
            "copyright": self.copyright,
            "pandas_available": self._pandas_available,
            "openpyxl_available": self._openpyxl_available,
            "parse_count": self._parse_count,
            "last_error": self._last_error,
            "supported_extensions": SUPPORTED_EXTENSIONS,
            "known_post_types": list(KNOWN_POST_TYPES.keys()),
            "column_patterns_count": len(COLUMN_PATTERNS),
            "type_mappings_count": len(TS_TYPE_MAPPING),
            "functions_available": 20,
        }


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "TSExcelParser",
    "SheetInfo",
    "ParsedField",
    "ParsedSpec",
    "ColumnStatistics",
    "CoverageAnalysis",
    "COLUMN_PATTERNS",
    "TS_TYPE_MAPPING",
    "KNOWN_POST_TYPES",
    "SUPPORTED_EXTENSIONS",
    "TS_POST_LENGTH",
    "TS_ENCODING",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]
