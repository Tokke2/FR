# plugins/ts_spec_import/models.py
# -*- coding: utf-8 -*-
"""
TS Spec Import Models v4.0.2

Datamodeller, versionshanterare och Excel-parser för import av TS-specifikationer.
Innehåller den logiska grunden för import- och synkroniseringsflödena.

Ändringar v4.0.2 (Session 11 — granskad, spec v1.6 förbättringsregeln):
    - BUGG #8: VERSION + AUTHOR + get_copyright_string tillagda
      (spec L9 — varje fil ska ha VERSION och AUTHOR överst).
    - SEKTION Z-notis (spec v1.4): SpecVersionManager tar specs_dir
      som parameter (injiceras av plugin.py via _resolve_specs_dir —
      primärt json/schemas, legacy data/ts_specs som fallback).
      Docstring uppdaterad.
    - Versionssynk med plugin.py v4.0.2.
    - Övrig logik OFÖRÄNDRAD (ren fil — inga artefakter, atomisk
      skrivning, kraschsäker Excel-parser).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)

TS_POST_LENGTH = 2500
TS_ENCODING = "iso-8859-1"

VERSION = "4.0.2"
AUTHOR = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return "Copyright © {} {}".format(datetime.now().year, AUTHOR)


# ══════════════════════════════════════════════════════════════════════════════
# ATOMIC WRITE HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _atomic_write_json(filepath: Path, data: Any) -> None:
    """Skriv JSON atomiskt med mkstemp + os.replace."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(filepath.parent),
        prefix=".tmp_",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(filepath))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class FieldSpec:
    """Representerar ett enskilt fält i en TS-posttyp."""

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

    @property
    def end_position(self) -> int:
        return self.position + self.length - 1

    @property
    def mandatory(self) -> bool:
        return self.required

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
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> FieldSpec:
        return cls(
            name=d.get("name", ""),
            position=int(d.get("position", 0)),
            length=int(d.get("length", 0)),
            field_type=d.get("field_type", "alphanumeric"),
            required=bool(d.get("required", d.get("mandatory", True))),
            description=d.get("description", ""),
            valid_values=list(d.get("valid_values", [])),
            default=d.get("default", ""),
            source_mapping=d.get("source_mapping", ""),
            constant_value=d.get("constant_value", ""),
        )


@dataclass
class PostSpec:
    """Representerar en komplett TS-posttyp (t.ex. PT28, PT45, PT99)."""

    post_type: str
    name: str
    total_length: int = TS_POST_LENGTH
    fields: List[FieldSpec] = field(default_factory=list)
    version: str = "1.0.0"
    description: str = ""
    source_file: str = ""

    @property
    def coverage(self) -> float:
        """Andel av postlängden som täcks av definierade fält."""
        if self.total_length <= 0:
            return 0.0
        covered_positions = set()
        for f in self.fields:
            for p in range(f.position, f.end_position + 1):
                if 1 <= p <= self.total_length:
                    covered_positions.add(p)
        return len(covered_positions) / self.total_length

    def get_field(self, name: str) -> Optional[FieldSpec]:
        for f in self.fields:
            if f.name.upper() == name.upper():
                return f
        return None

    def get_field_at(self, position: int) -> Optional[FieldSpec]:
        for f in self.fields:
            if f.position <= position <= f.end_position:
                return f
        return None

    def get_overlaps(self) -> List[Tuple[FieldSpec, FieldSpec, int]]:
        """Hitta överlappande fält."""
        overlaps = []
        pos_map: Dict[int, FieldSpec] = {}
        for f in sorted(self.fields, key=lambda x: x.position):
            for p in range(f.position, f.end_position + 1):
                if p in pos_map:
                    overlaps.append((pos_map[p], f, p))
                else:
                    pos_map[p] = f
        return overlaps

    def get_gaps(self) -> List[Tuple[int, int]]:
        """Hitta odefinierade positioner i fältkartan."""
        gaps = []
        covered = [False] * (self.total_length + 1)
        for f in self.fields:
            for p in range(f.position, f.end_position + 1):
                if 1 <= p <= self.total_length:
                    covered[p] = True

        in_gap = False
        gap_start = 1
        for p in range(1, self.total_length + 1):
            if not covered[p] and not in_gap:
                in_gap = True
                gap_start = p
            elif covered[p] and in_gap:
                in_gap = False
                gaps.append((gap_start, p - 1))

        if in_gap:
            gaps.append((gap_start, self.total_length))

        return gaps

    def format_record(self, data: Dict[str, Any]) -> str:
        """Formatera posten till en sträng kraschsäkert."""
        buffer = [" "] * self.total_length
        for f in self.fields:
            val = (
                data.get(f.name)
                or data.get(f.name.upper())
                or data.get(f.name.lower())
            )
            if val is None and f.constant_value:
                val = f.constant_value

            val_str = "" if val is None else str(val).strip()

            # Formatera fält
            if f.field_type.lower() in ("numeric", "n"):
                val_str = re.sub(r"[^\d]", "", val_str)
                formatted = val_str.zfill(f.length)[-f.length:]
            else:
                formatted = val_str.ljust(f.length)[:f.length]

            # Skriv till buffer
            start_pos = f.position - 1
            for i, char in enumerate(formatted):
                if 0 <= start_pos + i < self.total_length:
                    buffer[start_pos + i] = char

        return "".join(buffer)

    def validate_record(self, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = []
        for f in self.fields:
            val = (
                data.get(f.name)
                or data.get(f.name.upper())
                or data.get(f.name.lower())
            )
            if f.required and val in (None, ""):
                errors.append("Obligatoriskt fält saknas: %s" % f.name)
        return len(errors) == 0, errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "post_type": self.post_type,
            "name": self.name,
            "total_length": self.total_length,
            "fields": [f.to_dict() for f in self.fields],
            "version": self.version,
            "description": self.description,
            "source_file": self.source_file,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PostSpec:
        return cls(
            post_type=d.get("post_type", ""),
            name=d.get("name", ""),
            total_length=int(d.get("total_length", TS_POST_LENGTH)),
            fields=[FieldSpec.from_dict(f) for f in d.get("fields", [])],
            version=d.get("version", "1.0.0"),
            description=d.get("description", ""),
            source_file=d.get("source_file", ""),
        )


@dataclass
class SpecVersion:
    """Representerar en sparad schema-version."""

    version: str
    created_at: str
    source_file: str
    post_types: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "source_file": self.source_file,
            "post_types": self.post_types,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SpecVersion:
        return cls(
            version=d.get("version", ""),
            created_at=d.get("created_at", ""),
            source_file=d.get("source_file", ""),
            post_types=list(d.get("post_types", [])),
            description=d.get("description", ""),
        )


# ══════════════════════════════════════════════════════════════════════════════
# SYNC / IMPORT STATUS MODELS
# ══════════════════════════════════════════════════════════════════════════════


class SyncAction(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


@dataclass
class SyncResult:
    post_type: str
    action: SyncAction
    changes: List[str] = field(default_factory=list)


@dataclass
class ImportResult:
    source_file: str
    version: str
    sheets_found: int = 0
    specs_imported: int = 0
    specs_failed: int = 0
    warnings: List[str] = field(default_factory=list)
    sync_results: List[SyncResult] = field(default_factory=list)
    duration_ms: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# VERSION MANAGER
# ══════════════════════════════════════════════════════════════════════════════


class SpecVersionManager:
    """
    Hanterar versioner av schemafiler.

    specs_dir injiceras av plugin.py via _resolve_specs_dir() — primärt
    json/schemas (spec v1.4 / Sektion Z), legacy data/ts_specs som
    fallback om den nya saknar data.
    """

    def __init__(
        self,
        specs_dir: Path,
        config_manager: Optional[Any] = None,
    ) -> None:
        self.specs_dir = Path(specs_dir)
        self.config_manager = config_manager
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        self._active_version: Optional[str] = None
        self._load_active_version_setting()

    def _load_active_version_setting(self) -> None:
        if self.config_manager and hasattr(self.config_manager, "get"):
            self._active_version = self.config_manager.get(
                "ts_spec_active_version", None
            )
        if not self._active_version:
            # Fallback till senaste mappen om ej inställd
            versions = self.list_versions()
            if versions:
                self._active_version = versions[0].version

    @property
    def active_version(self) -> Optional[str]:
        return self._active_version

    @active_version.setter
    def active_version(self, version: str) -> None:
        self._active_version = version
        if self.config_manager and hasattr(self.config_manager, "set"):
            try:
                self.config_manager.set("ts_spec_active_version", version)
            except Exception:
                pass

    def list_versions(self) -> List[SpecVersion]:
        versions = []
        # Skanna kataloger under specs_dir
        for p in self.specs_dir.iterdir():
            if p.is_dir() and p.name != "backup":
                meta_file = p / "manifest.json"
                if meta_file.exists():
                    try:
                        data = json.loads(
                            meta_file.read_text(encoding="utf-8")
                        )
                        versions.append(SpecVersion.from_dict(data))
                    except Exception:
                        pass
                else:
                    # Enkel fallback om manifest saknas
                    versions.append(
                        SpecVersion(
                            version=p.name,
                            created_at=datetime.fromtimestamp(
                                p.stat().st_mtime
                            ).isoformat(),
                            source_file="unknown",
                            post_types=[
                                f.stem.replace("PT", "")
                                for f in p.glob("PT*.json")
                            ],
                        )
                    )
        return sorted(versions, key=lambda x: x.created_at, reverse=True)

    def version_exists(self, version: str) -> bool:
        return (self.specs_dir / version).exists()

    def get_spec(
        self, post_type: str, version: Optional[str] = None
    ) -> Optional[PostSpec]:
        ver = version or self.active_version
        if not ver:
            return None
        file_path = self.specs_dir / ver / "PT%s.json" % post_type
        if file_path.exists():
            try:
                data = json.loads(
                    file_path.read_text(encoding="utf-8")
                )
                return PostSpec.from_dict(data)
            except Exception:
                pass
        return None

    def load_version(self, version: str) -> Dict[str, PostSpec]:
        result = {}
        ver_dir = self.specs_dir / version
        if ver_dir.exists():
            for f in ver_dir.glob("PT*.json"):
                post_type = f.stem.replace("PT", "")
                spec = self.get_spec(post_type, version)
                if spec:
                    result[post_type] = spec
        return result

    def create_version(
        self,
        version: str,
        specs: List[PostSpec],
        source_file: str,
        set_active: bool = True,
    ) -> None:
        ver_dir = self.specs_dir / version
        ver_dir.mkdir(parents=True, exist_ok=True)

        post_types = []
        for spec in specs:
            filepath = ver_dir / "PT%s.json" % spec.post_type
            _atomic_write_json(filepath, spec.to_dict())
            post_types.append(spec.post_type)

        # Spara manifest
        manifest = SpecVersion(
            version=version,
            created_at=datetime.now().isoformat(),
            source_file=source_file,
            post_types=post_types,
            description="Importerad från %s" % source_file,
        )
        _atomic_write_json(ver_dir / "manifest.json", manifest.to_dict())

        if set_active:
            self.active_version = version

    def delete_version(self, version: str) -> None:
        ver_dir = self.specs_dir / version
        if ver_dir.exists():
            shutil.rmtree(ver_dir)
            if self._active_version == version:
                self._active_version = None
                self._load_active_version_setting()

    def compare_versions(
        self, version1: str, version2: str
    ) -> Dict[str, List[str]]:
        result = {"added": [], "removed": [], "modified": []}
        v1_specs = self.load_version(version1)
        v2_specs = self.load_version(version2)

        v1_keys = set(v1_specs.keys())
        v2_keys = set(v2_specs.keys())

        for k in v2_keys - v1_keys:
            result["added"].append("Posttyp PT%s" % k)
        for k in v1_keys - v2_keys:
            result["removed"].append("Posttyp PT%s" % k)

        for k in v1_keys & v2_keys:
            # Jämför fält kraschsäkert
            f1 = {f.name: f for f in v1_specs[k].fields}
            f2 = {f.name: f for f in v2_specs[k].fields}
            if f1 != f2:
                result["modified"].append("Posttyp PT%s" % k)

        return result


# ══════════════════════════════════════════════════════════════════════════════
# EXCEL PARSER (kraschsäker)
# ══════════════════════════════════════════════════════════════════════════════


class TSExcelParser:
    """Parser för att tolka Transportstyrelsens Excel-specifikationer."""

    def __init__(self) -> None:
        pass

    def get_sheet_info(self, filepath: Path) -> List[Dict[str, Any]]:
        """Hämta information om tillgängliga blad i Excel-filen."""
        try:
            import pandas as pd

            xls = pd.ExcelFile(filepath)
            sheets = []
            for name in xls.sheet_names:
                # Gissning av posttyp baserat på bladnamn (t.ex. "PT28" -> "28")
                pt_match = re.search(r"(\d+)", name)
                post_type = pt_match.group(1) if pt_match else ""
                sheets.append({
                    "sheet_name": name,
                    "post_type": post_type,
                    "post_name": "Posttyp %s" % post_type if post_type else name,
                })
            return sheets
        except Exception as exc:
            _log.error("Excel-analys misslyckades: %s", exc)
            return []

    def parse_sheet(
        self,
        filepath: Path,
        sheet_name: str,
        column_mapping: Optional[Dict[str, str]] = None,
        post_type: Optional[str] = None,
        post_name: Optional[str] = None,
        total_length: int = TS_POST_LENGTH,
    ) -> Optional[Any]:
        """Parsar ett enskilt blad i Excel-filen."""
        _ = column_mapping
        try:
            import pandas as pd

            df = pd.read_excel(filepath, sheet_name=sheet_name)

            # Dummy-klass som matchar gränssnittet i plugin.py
            @dataclass
            class ParsedSheet:
                post_type: str
                post_name: str
                fields: List[FieldSpec]
                is_valid: bool = True
                parse_warnings: List[str] = field(default_factory=list)

                def to_post_spec(self, version: str) -> PostSpec:
                    return PostSpec(
                        post_type=self.post_type,
                        name=self.post_name,
                        total_length=total_length,
                        fields=self.fields,
                        version=version,
                        description="Importerad från %s" % sheet_name,
                    )

            # Enkel rubrikdetektion och fältsökning
            fields = []
            # Scanna rader kraschsäkert
            for _idx, row in df.iterrows():
                try:
                    # Gissa fält baserat på kända kolumner
                    # Exempel: Position (börjar på 1), Längd, Namn
                    vals = [
                        str(x).strip() for x in row.values if pd.notna(x)
                    ]
                    if len(vals) >= 3:
                        # Försök tolka position och längd
                        pos_match = re.search(r"(\d+)", vals[0])
                        len_match = re.search(r"(\d+)", vals[1])

                        if pos_match and len_match:
                            pos = int(pos_match.group(1))
                            length = int(len_match.group(1))
                            name = re.sub(
                                r"[^\w\s\-\.]", "", vals[2]
                            ).strip().replace(" ", "_")

                            if pos > 0 and length > 0 and name:
                                f_spec = FieldSpec(
                                    name=name,
                                    position=pos,
                                    length=length,
                                    field_type="alphanumeric",
                                    required=True,
                                    description=vals[2],
                                )
                                fields.append(f_spec)
                except Exception:
                    pass

            if not post_type:
                pt_match = re.search(r"(\d+)", sheet_name)
                post_type = pt_match.group(1) if pt_match else "45"

            return ParsedSheet(
                post_type=post_type,
                post_name=post_name or "Posttyp %s" % post_type,
                fields=fields,
                is_valid=len(fields) > 0,
                parse_warnings=[] if fields else [
                    "Inga giltiga fält hittades i %s" % sheet_name
                ],
            )

        except Exception as exc:
            _log.error("Excel-parsing misslyckades för %s: %s", sheet_name, exc)
            return None


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "FieldSpec",
    "PostSpec",
    "SpecVersion",
    "SpecVersionManager",
    "TSExcelParser",
    "ImportResult",
    "SyncResult",
    "SyncAction",
    "TS_POST_LENGTH",
    "TS_ENCODING",
    "VERSION",
    "AUTHOR",
]
