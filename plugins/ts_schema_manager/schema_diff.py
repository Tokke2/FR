# -*- coding: utf-8 -*-
# Fil: plugins/ts_schema_manager/schema_diff.py
"""
Schema Diff v1.0.1 — Jämförelse och analys av TS-scheman

ANSVAR:
  - Jämföra två PostSpec (fält-för-fält diff)
  - Jämföra två versioner (alla posttyper)
  - Generera läsbara diff-rapporter
  - Identifiera: nya fält, borttagna fält, ändrade fält
  - Identifiera: position-, längd-, typ- och obligatorisk-ändringar
  - Exportera diff till text/JSON
  - Kraschsäkra operationer med tydliga fallbacks

IMPORTER:
  json, logging, datetime, pathlib, typing
  .models (PostSpec, FieldSpec, SpecVersion) via lazy import

EXPORTERAR:
  FieldDiff      - dataclass för ett fälts ändringar
  PostTypeDiff   - dataclass för en posttyps ändringar
  VersionDiff    - dataclass för en hel versions ändringar
  SchemaDiff     - huvudklass för diff-operationer

PUBLIKT API (SchemaDiff):
  ─── JÄMFÖRELSE ───
  diff_specs(spec1, spec2, label1, label2)       -> PostTypeDiff
  diff_versions(specs1, specs2, v1, v2)          -> VersionDiff
  diff_field(field1, field2)                     -> FieldDiff
  compare_post_types(v1_specs, v2_specs)         -> Dict[str, str]

  ─── RAPPORTER ───
  format_diff_text(diff)                         -> str
  format_version_diff_text(version_diff)         -> str
  format_field_diff_text(field_diff)             -> str
  get_summary(diff)                              -> Dict[str, int]
  get_version_summary(version_diff)              -> Dict[str, Any]

  ─── EXPORT ───
  diff_to_dict(diff)                             -> Dict
  version_diff_to_dict(version_diff)             -> Dict
  diff_to_json(diff, indent)                     -> str
  version_diff_to_json(version_diff, indent)     -> str

  ─── UTILITY ───
  has_changes(diff)                              -> bool
  is_breaking_change(field_diff)                -> bool
  get_breaking_changes(diff)                     -> List[FieldDiff]

ANVÄNDS AV:
  plugins/ts_schema_manager/plugin.py
    → get_schema_diff() (funktion 4)
    → compare_versions()
  plugins/ts_schema_manager/widget.py
    → diff-visning i GUI

FÖRÄNDRINGAR v1.0.1 (Session 11 — granskad, spec v1.6 förbättringsregeln):
  - FIX (BUGG #5): hårdkodad copyright-rad "# Copyright © 2025 ..."
    BORTTAGEN — copyright genereras dynamiskt via get_copyright_string().
  - _get_copyright_string -> get_copyright_string (publik, konsistent
    med version_manager.py och schema_store.py) + i __all__.
  - Övrig logik OFÖRÄNDRAD (kraschsäkra diffs, rapporter, export).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Final, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL LOGGER
# ──────────────────────────────────────────────────────────────────────────────

_log: logging.Logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

VERSION: Final[str] = "1.0.1"
AUTHOR: Final[str] = "Rickard Längkvist"

# Symboler för diff-output
SYMBOL_ADDED: Final[str] = "+"
SYMBOL_REMOVED: Final[str] = "-"
SYMBOL_CHANGED: Final[str] = "~"
SYMBOL_UNCHANGED: Final[str] = "="
SYMBOL_SEPARATOR: Final[str] = "─"


def get_copyright_string() -> str:
    """Dynamisk copyright-sträng."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ──────────────────────────────────────────────────────────────────────────────
# LAZY IMPORTS
# ──────────────────────────────────────────────────────────────────────────────

_PostSpec: Optional[Any] = None
_FieldSpec: Optional[Any] = None
_SpecVersion: Optional[Any] = None


def _get_PostSpec() -> Any:
    """Lazy import av PostSpec."""
    global _PostSpec
    if _PostSpec is None:
        from .models import PostSpec  # type: ignore[import]
        _PostSpec = PostSpec
    return _PostSpec


def _get_FieldSpec() -> Any:
    """Lazy import av FieldSpec."""
    global _FieldSpec
    if _FieldSpec is None:
        from .models import FieldSpec  # type: ignore[import]
        _FieldSpec = FieldSpec
    return _FieldSpec


# ══════════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FieldChange:
    """
    En enskild förändring på ett attribut i ett fält.

    Attributes:
        attribute:   Attributnamn (t.ex. "position", "length", "field_type")
        old_value:   Gammalt värde
        new_value:   Nytt värde
        is_breaking: Om ändringen är en breaking change
    """

    attribute: str
    old_value: Any
    new_value: Any
    is_breaking: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "attribute": self.attribute,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "is_breaking": self.is_breaking,
        }

    def format_text(self) -> str:
        """Formatera som läsbar text."""
        breaking = " ⚠ BREAKING" if self.is_breaking else ""
        return (
            f"  {self.attribute}: "
            f"{self.old_value!r} → {self.new_value!r}"
            f"{breaking}"
        )

    def __repr__(self) -> str:
        return (
            f"<FieldChange {self.attribute}: "
            f"{self.old_value!r} → {self.new_value!r}>"
        )


@dataclass
class FieldDiff:
    """
    Diff för ett enskilt fält mellan två scheman.

    Attributes:
        field_name:  Fältets namn
        status:      "added", "removed" eller "changed"
        changes:     Lista med FieldChange (vid status="changed")
        field1:      Fältet i schema 1 (None om added)
        field2:      Fältet i schema 2 (None om removed)
    """

    field_name: str
    status: str
    changes: List[FieldChange] = field(default_factory=list)
    field1: Optional[Any] = None
    field2: Optional[Any] = None

    @property
    def is_breaking(self) -> bool:
        """Sant om något av ändringarna är breaking changes."""
        if self.status == "removed":
            return True
        return any(c.is_breaking for c in self.changes)

    @property
    def symbol(self) -> str:
        """Diff-symbol för statusen."""
        return {
            "added": SYMBOL_ADDED,
            "removed": SYMBOL_REMOVED,
            "changed": SYMBOL_CHANGED,
        }.get(self.status, SYMBOL_UNCHANGED)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "field_name": self.field_name,
            "status": self.status,
            "is_breaking": self.is_breaking,
            "changes": [c.to_dict() for c in self.changes],
        }

    def __repr__(self) -> str:
        breaking = " [BREAKING]" if self.is_breaking else ""
        return (
            f"<FieldDiff {self.symbol} {self.field_name} "
            f"({self.status}){breaking}>"
        )


@dataclass
class PostTypeDiff:
    """
    Diff för en hel posttyp mellan två scheman.

    Attributes:
        post_type:      Posttypskod
        status:         "added", "removed", "changed" eller "unchanged"
        label1:         Etikett för schema 1 (t.ex. versionsnamn)
        label2:         Etikett för schema 2
        field_diffs:    Lista med FieldDiff
        length_changed: Om total_length ändrats
        old_length:     Gammal total_length
        new_length:     Ny total_length
        generated_at:   Tidsstämpel
    """

    post_type: str
    status: str
    label1: str = ""
    label2: str = ""
    field_diffs: List[FieldDiff] = field(default_factory=list)
    length_changed: bool = False
    old_length: int = 0
    new_length: int = 0
    generated_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    @property
    def added_fields(self) -> List[FieldDiff]:
        """Fält som lagts till."""
        return [d for d in self.field_diffs if d.status == "added"]

    @property
    def removed_fields(self) -> List[FieldDiff]:
        """Fält som tagits bort."""
        return [d for d in self.field_diffs if d.status == "removed"]

    @property
    def changed_fields(self) -> List[FieldDiff]:
        """Fält som ändrats."""
        return [d for d in self.field_diffs if d.status == "changed"]

    @property
    def breaking_changes(self) -> List[FieldDiff]:
        """Alla breaking changes."""
        return [d for d in self.field_diffs if d.is_breaking]

    @property
    def has_changes(self) -> bool:
        """Sant om det finns några ändringar."""
        return bool(
            self.field_diffs
            or self.length_changed
            or self.status in ("added", "removed")
        )

    @property
    def has_breaking_changes(self) -> bool:
        """Sant om det finns breaking changes."""
        return bool(self.breaking_changes) or self.length_changed

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "post_type": self.post_type,
            "status": self.status,
            "label1": self.label1,
            "label2": self.label2,
            "has_changes": self.has_changes,
            "has_breaking_changes": self.has_breaking_changes,
            "length_changed": self.length_changed,
            "old_length": self.old_length,
            "new_length": self.new_length,
            "added_count": len(self.added_fields),
            "removed_count": len(self.removed_fields),
            "changed_count": len(self.changed_fields),
            "breaking_count": len(self.breaking_changes),
            "field_diffs": [d.to_dict() for d in self.field_diffs],
            "generated_at": self.generated_at,
        }

    def __repr__(self) -> str:
        return (
            f"<PostTypeDiff PT{self.post_type} "
            f"status={self.status} "
            f"added={len(self.added_fields)} "
            f"removed={len(self.removed_fields)} "
            f"changed={len(self.changed_fields)}>"
        )


@dataclass
class VersionDiff:
    """
    Diff för en hel version (alla posttyper).

    Attributes:
        version1:        Versionsnamn 1
        version2:        Versionsnamn 2
        post_type_diffs: Dict med post_type → PostTypeDiff
        generated_at:    Tidsstämpel
    """

    version1: str
    version2: str
    post_type_diffs: Dict[str, PostTypeDiff] = field(
        default_factory=dict
    )
    generated_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    @property
    def added_post_types(self) -> List[str]:
        """Posttyper som lagts till."""
        return [
            pt for pt, d in self.post_type_diffs.items()
            if d.status == "added"
        ]

    @property
    def removed_post_types(self) -> List[str]:
        """Posttyper som tagits bort."""
        return [
            pt for pt, d in self.post_type_diffs.items()
            if d.status == "removed"
        ]

    @property
    def changed_post_types(self) -> List[str]:
        """Posttyper med ändringar."""
        return [
            pt for pt, d in self.post_type_diffs.items()
            if d.has_changes and d.status not in ("added", "removed")
        ]

    @property
    def unchanged_post_types(self) -> List[str]:
        """Posttyper utan ändringar."""
        return [
            pt for pt, d in self.post_type_diffs.items()
            if not d.has_changes
        ]

    @property
    def has_breaking_changes(self) -> bool:
        """Sant om versionen innehåller breaking changes."""
        return any(d.has_breaking_changes for d in self.post_type_diffs.values())

    @property
    def total_changes(self) -> int:
        """Totalt antal ändrade fält."""
        return sum(
            len(d.field_diffs)
            for d in self.post_type_diffs.values()
        )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "version1": self.version1,
            "version2": self.version2,
            "generated_at": self.generated_at,
            "has_breaking_changes": self.has_breaking_changes,
            "added_post_types": self.added_post_types,
            "removed_post_types": self.removed_post_types,
            "changed_post_types": self.changed_post_types,
            "unchanged_post_types": self.unchanged_post_types,
            "total_changes": self.total_changes,
            "post_type_diffs": {
                pt: d.to_dict()
                for pt, d in self.post_type_diffs.items()
            },
        }

    def __repr__(self) -> str:
        return (
            f"<VersionDiff {self.version1} → {self.version2} "
            f"added={len(self.added_post_types)} "
            f"removed={len(self.removed_post_types)} "
            f"changed={len(self.changed_post_types)}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA DIFF
# ══════════════════════════════════════════════════════════════════════════════

class SchemaDiff:
    """
    Jämförelse och analys av TS-scheman.

    Kraschsäker i alla operationer.
    Inga hårdkodade fältpositioner — all jämförelse är dynamisk.

    BREAKING CHANGES definieras som:
      - Fält borttaget
      - Position ändrad
      - Längd minskad
      - Typ ändrad (numeric ↔ alphanumeric)
      - Total längd ändrad
    """

    # Attribut att jämföra på FieldSpec
    _FIELD_ATTRIBUTES: Final[List[Tuple[str, bool]]] = [
        ("position", True),       # (attributnamn, is_breaking)
        ("length", True),
        ("field_type", True),
        ("mandatory", False),
        ("description", False),
        ("default", False),
        ("constant_value", False),
        ("source_mapping", False),
    ]

    def __init__(self) -> None:
        """Initiera SchemaDiff."""
        _log.debug("SchemaDiff initierad")

    # ──────────────────────────────────────────────────────────────────────
    # JÄMFÖRELSE
    # ──────────────────────────────────────────────────────────────────────

    def diff_field(
        self,
        field1: Any,
        field2: Any,
    ) -> FieldDiff:
        """
        Jämför två FieldSpec och returnera FieldDiff.

        Kontrollerar alla relevanta attribut:
        position, length, field_type, mandatory,
        description, default, constant_value, source_mapping.

        Breaking changes:
          - position ändrad
          - length ändrad (minskning är värre men båda räknas)
          - field_type ändrad

        Args:
            field1: FieldSpec i schema 1
            field2: FieldSpec i schema 2

        Returns:
            FieldDiff med status="changed" och lista av FieldChange
        """
        try:
            changes: List[FieldChange] = []

            for attr, breaking_base in self._FIELD_ATTRIBUTES:
                val1 = getattr(field1, attr, None)
                val2 = getattr(field2, attr, None)

                if val1 != val2:
                    # Längd: minskning är alltid breaking
                    is_breaking = breaking_base
                    if attr == "length" and isinstance(val1, int) and isinstance(val2, int):
                        is_breaking = val2 < val1

                    changes.append(FieldChange(
                        attribute=attr,
                        old_value=val1,
                        new_value=val2,
                        is_breaking=is_breaking,
                    ))

            return FieldDiff(
                field_name=field1.name,
                status="changed" if changes else "unchanged",
                changes=changes,
                field1=field1,
                field2=field2,
            )

        except Exception as exc:
            _log.error(
                "Fel i diff_field(%s): %s",
                getattr(field1, "name", "?"), exc, exc_info=True,
            )
            return FieldDiff(
                field_name=getattr(field1, "name", "?"),
                status="changed",
                changes=[FieldChange(
                    attribute="error",
                    old_value=None,
                    new_value=str(exc),
                    is_breaking=False,
                )],
            )

    def diff_specs(
        self,
        spec1: Any,
        spec2: Any,
        label1: str = "version1",
        label2: str = "version2",
    ) -> PostTypeDiff:
        """
        Jämför två PostSpec fält-för-fält.

        Identifierar:
          - Nya fält (finns i spec2 men inte spec1)
          - Borttagna fält (finns i spec1 men inte spec2)
          - Ändrade fält (finns i båda men med olika attribut)
          - Ändrad total_length

        Args:
            spec1:  PostSpec (bas)
            spec2:  PostSpec (jämförelse)
            label1: Etikett för spec1
            label2: Etikett för spec2

        Returns:
            PostTypeDiff med fullständig diff-information
        """
        try:
            post_type = spec1.post_type if spec1 else (
                spec2.post_type if spec2 else "?"
            )

            if spec1 is None and spec2 is None:
                return PostTypeDiff(
                    post_type=post_type,
                    status="unchanged",
                    label1=label1,
                    label2=label2,
                )

            if spec1 is None:
                return PostTypeDiff(
                    post_type=spec2.post_type,
                    status="added",
                    label1=label1,
                    label2=label2,
                )

            if spec2 is None:
                return PostTypeDiff(
                    post_type=spec1.post_type,
                    status="removed",
                    label1=label1,
                    label2=label2,
                )

            # Bygg fältkartor
            fields1: Dict[str, Any] = {
                f.name: f for f in spec1.fields
            }
            fields2: Dict[str, Any] = {
                f.name: f for f in spec2.fields
            }

            all_field_names = sorted(
                set(fields1.keys()) | set(fields2.keys())
            )
            field_diffs: List[FieldDiff] = []

            for fname in all_field_names:
                f1 = fields1.get(fname)
                f2 = fields2.get(fname)

                if f1 is None:
                    # Nytt fält
                    field_diffs.append(FieldDiff(
                        field_name=fname,
                        status="added",
                        field1=None,
                        field2=f2,
                    ))
                elif f2 is None:
                    # Borttaget fält
                    field_diffs.append(FieldDiff(
                        field_name=fname,
                        status="removed",
                        field1=f1,
                        field2=None,
                    ))
                else:
                    # Jämför fält
                    fd = self.diff_field(f1, f2)
                    if fd.status != "unchanged":
                        field_diffs.append(fd)

            # Kontrollera total_length
            length_changed = spec1.total_length != spec2.total_length

            # Bestäm övergripande status
            if not field_diffs and not length_changed:
                status = "unchanged"
            else:
                status = "changed"

            return PostTypeDiff(
                post_type=post_type,
                status=status,
                label1=label1,
                label2=label2,
                field_diffs=field_diffs,
                length_changed=length_changed,
                old_length=spec1.total_length,
                new_length=spec2.total_length,
            )

        except Exception as exc:
            _log.error(
                "Fel i diff_specs(PT%s): %s",
                getattr(spec1, "post_type", "?"), exc, exc_info=True,
            )
            return PostTypeDiff(
                post_type=getattr(spec1, "post_type", "?"),
                status="changed",
                label1=label1,
                label2=label2,
            )

    def diff_versions(
        self,
        specs1: Dict[str, Any],
        specs2: Dict[str, Any],
        version1: str = "version1",
        version2: str = "version2",
    ) -> VersionDiff:
        """
        Jämför två kompletta versioner (alla posttyper).

        Args:
            specs1:   Dict med post_type → PostSpec (version 1)
            specs2:   Dict med post_type → PostSpec (version 2)
            version1: Namn på version 1
            version2: Namn på version 2

        Returns:
            VersionDiff med diff per posttyp
        """
        try:
            all_post_types = sorted(
                set(specs1.keys()) | set(specs2.keys())
            )
            post_type_diffs: Dict[str, PostTypeDiff] = {}

            for pt in all_post_types:
                s1 = specs1.get(pt)
                s2 = specs2.get(pt)

                diff = self.diff_specs(
                    s1, s2,
                    label1=version1,
                    label2=version2,
                )
                post_type_diffs[pt] = diff

            version_diff = VersionDiff(
                version1=version1,
                version2=version2,
                post_type_diffs=post_type_diffs,
            )

            _log.debug(
                "Versions-diff %s → %s: %d posttyper",
                version1, version2, len(all_post_types),
            )
            return version_diff

        except Exception as exc:
            _log.error(
                "Fel i diff_versions(%s, %s): %s",
                version1, version2, exc, exc_info=True,
            )
            return VersionDiff(version1=version1, version2=version2)

    def compare_post_types(
        self,
        specs1: Dict[str, Any],
        specs2: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Snabb jämförelse av posttyper mellan versioner.

        Returnerar enkel status per posttyp.

        Args:
            specs1: Dict post_type → PostSpec (version 1)
            specs2: Dict post_type → PostSpec (version 2)

        Returns:
            Dict med post_type → status
            Status: "added", "removed", "changed", "unchanged"
        """
        try:
            all_types = set(specs1.keys()) | set(specs2.keys())
            result: Dict[str, str] = {}

            for pt in sorted(all_types):
                s1 = specs1.get(pt)
                s2 = specs2.get(pt)

                if s1 is None:
                    result[pt] = "added"
                elif s2 is None:
                    result[pt] = "removed"
                else:
                    diff = self.diff_specs(s1, s2)
                    result[pt] = diff.status

            return result

        except Exception as exc:
            _log.error(
                "Fel i compare_post_types: %s", exc, exc_info=True
            )
            return {}

    # ──────────────────────────────────────────────────────────────────────
    # RAPPORTER
    # ──────────────────────────────────────────────────────────────────────

    def format_field_diff_text(self, fd: FieldDiff) -> str:
        """
        Formatera ett FieldDiff som läsbar text.

        Args:
            fd: FieldDiff att formatera

        Returns:
            Formaterad text
        """
        try:
            lines: List[str] = []

            if fd.status == "added":
                f = fd.field2
                pos = getattr(f, "position", "?")
                length = getattr(f, "length", "?")
                ftype = getattr(f, "field_type", "?")
                lines.append(
                    f"  {SYMBOL_ADDED} {fd.field_name} "
                    f"(pos={pos}, len={length}, typ={ftype})"
                )

            elif fd.status == "removed":
                f = fd.field1
                pos = getattr(f, "position", "?")
                length = getattr(f, "length", "?")
                lines.append(
                    f"  {SYMBOL_REMOVED} {fd.field_name} "
                    f"(pos={pos}, len={length})"
                    + (" ⚠ BREAKING" if fd.is_breaking else "")
                )

            elif fd.status == "changed":
                breaking = " ⚠ BREAKING" if fd.is_breaking else ""
                lines.append(
                    f"  {SYMBOL_CHANGED} {fd.field_name}{breaking}"
                )
                for change in fd.changes:
                    lines.append(change.format_text())

            return "\n".join(lines)

        except Exception as exc:
            _log.error(
                "Fel i format_field_diff_text: %s", exc
            )
            return f"  ? {fd.field_name} (formateringsfel)"

    def format_diff_text(self, diff: PostTypeDiff) -> str:
        """
        Formatera en PostTypeDiff som läsbar text.

        Args:
            diff: PostTypeDiff att formatera

        Returns:
            Formaterad text med rubrik och fält-diffs
        """
        try:
            sep = SYMBOL_SEPARATOR * 60
            lines: List[str] = [
                sep,
                f"PT{diff.post_type} — {diff.status.upper()}",
                f"  {diff.label1} → {diff.label2}",
            ]

            if diff.status == "added":
                lines.append("  Posttypen är NY i version 2")
                return "\n".join(lines)

            if diff.status == "removed":
                lines.append("  ⚠ BREAKING: Posttypen är BORTTAGEN i version 2")
                return "\n".join(lines)

            if diff.status == "unchanged":
                lines.append("  Inga ändringar")
                return "\n".join(lines)

            # Längdändring
            if diff.length_changed:
                lines.append(
                    f"  ⚠ BREAKING: Längd ändrad: "
                    f"{diff.old_length} → {diff.new_length}"
                )

            # Statistik
            lines.append(
                f"  Ändringar: "
                f"+{len(diff.added_fields)} "
                f"-{len(diff.removed_fields)} "
                f"~{len(diff.changed_fields)}"
            )

            if diff.has_breaking_changes:
                lines.append(
                    f"  ⚠ {len(diff.breaking_changes)} breaking change(s)"
                )

            # Fält-diffs
            if diff.removed_fields:
                lines.append("")
                lines.append("  BORTTAGNA FÄLT:")
                for fd in diff.removed_fields:
                    lines.append(self.format_field_diff_text(fd))

            if diff.added_fields:
                lines.append("")
                lines.append("  NYA FÄLT:")
                for fd in diff.added_fields:
                    lines.append(self.format_field_diff_text(fd))

            if diff.changed_fields:
                lines.append("")
                lines.append("  ÄNDRADE FÄLT:")
                for fd in diff.changed_fields:
                    lines.append(self.format_field_diff_text(fd))

            return "\n".join(lines)

        except Exception as exc:
            _log.error(
                "Fel i format_diff_text(PT%s): %s",
                diff.post_type, exc, exc_info=True,
            )
            return f"PT{diff.post_type}: formateringsfel ({exc})"

    def format_version_diff_text(
        self, version_diff: VersionDiff
    ) -> str:
        """
        Formatera en VersionDiff som komplett läsbar rapport.

        Args:
            version_diff: VersionDiff att formatera

        Returns:
            Komplett textrapport
        """
        try:
            sep = SYMBOL_SEPARATOR * 60
            double_sep = "═" * 60
            lines: List[str] = [
                double_sep,
                f"SCHEMA DIFF RAPPORT",
                f"  {version_diff.version1} → {version_diff.version2}",
                f"  Genererad: {version_diff.generated_at}",
                double_sep,
                "",
            ]

            # Sammanfattning
            summary = self.get_version_summary(version_diff)
            lines.extend([
                "SAMMANFATTNING:",
                f"  Posttyper totalt: {summary['total_post_types']}",
                f"  Nya posttyper:    {summary['added_post_types']}",
                f"  Borttagna:        {summary['removed_post_types']}",
                f"  Ändrade:          {summary['changed_post_types']}",
                f"  Oförändrade:      {summary['unchanged_post_types']}",
                f"  Totala fältändringar: {summary['total_field_changes']}",
                f"  Breaking changes: "
                f"{'⚠ JA' if version_diff.has_breaking_changes else 'Nej'}",
                "",
            ])

            # Oförändrade (kompakt)
            if version_diff.unchanged_post_types:
                unchanged_str = ", ".join(
                    f"PT{pt}" for pt in sorted(
                        version_diff.unchanged_post_types
                    )
                )
                lines.append(f"OFÖRÄNDRADE: {unchanged_str}")
                lines.append("")

            # Detaljerade diffs (bara posttyper med ändringar)
            changed_diffs = [
                d for d in version_diff.post_type_diffs.values()
                if d.has_changes
            ]

            if changed_diffs:
                lines.append("DETALJERADE ÄNDRINGAR:")
                lines.append("")
                for diff in sorted(
                    changed_diffs,
                    key=lambda d: d.post_type
                ):
                    lines.append(self.format_diff_text(diff))
                    lines.append("")

            lines.append(double_sep)
            return "\n".join(lines)

        except Exception as exc:
            _log.error(
                "Fel i format_version_diff_text: %s",
                exc, exc_info=True,
            )
            return f"Versions-diff formateringsfel: {exc}"

    # ──────────────────────────────────────────────────────────────────────
    # SAMMANFATTNING
    # ──────────────────────────────────────────────────────────────────────

    def get_summary(self, diff: PostTypeDiff) -> Dict[str, int]:
        """
        Hämta numerisk sammanfattning av en PostTypeDiff.

        Args:
            diff: PostTypeDiff

        Returns:
            Dict med räknare:
              added, removed, changed, unchanged,
              breaking_changes, total_changes
        """
        try:
            return {
                "added": len(diff.added_fields),
                "removed": len(diff.removed_fields),
                "changed": len(diff.changed_fields),
                "unchanged": (
                    0 if diff.has_changes else len(
                        [f for f in diff.field_diffs]
                    )
                ),
                "breaking_changes": len(diff.breaking_changes),
                "total_changes": len(diff.field_diffs),
            }
        except Exception as exc:
            _log.error("Fel i get_summary: %s", exc)
            return {
                "added": 0, "removed": 0, "changed": 0,
                "unchanged": 0, "breaking_changes": 0,
                "total_changes": 0,
            }

    def get_version_summary(
        self, version_diff: VersionDiff
    ) -> Dict[str, Any]:
        """
        Hämta sammanfattning av en VersionDiff.

        Args:
            version_diff: VersionDiff

        Returns:
            Dict med räknare och listor
        """
        try:
            total_field_changes = sum(
                len(d.field_diffs)
                for d in version_diff.post_type_diffs.values()
            )

            return {
                "version1": version_diff.version1,
                "version2": version_diff.version2,
                "total_post_types": len(version_diff.post_type_diffs),
                "added_post_types": len(version_diff.added_post_types),
                "removed_post_types": len(version_diff.removed_post_types),
                "changed_post_types": len(version_diff.changed_post_types),
                "unchanged_post_types": len(version_diff.unchanged_post_types),
                "total_field_changes": total_field_changes,
                "has_breaking_changes": version_diff.has_breaking_changes,
                "generated_at": version_diff.generated_at,
            }
        except Exception as exc:
            _log.error("Fel i get_version_summary: %s", exc)
            return {
                "version1": version_diff.version1,
                "version2": version_diff.version2,
                "error": str(exc),
            }

    # ──────────────────────────────────────────────────────────────────────
    # EXPORT
    # ──────────────────────────────────────────────────────────────────────

    def diff_to_dict(self, diff: PostTypeDiff) -> Dict[str, Any]:
        """
        Konvertera PostTypeDiff till dictionary.

        Args:
            diff: PostTypeDiff

        Returns:
            Dict med all diff-information
        """
        try:
            return diff.to_dict()
        except Exception as exc:
            _log.error("Fel i diff_to_dict: %s", exc)
            return {"error": str(exc)}

    def version_diff_to_dict(
        self, version_diff: VersionDiff
    ) -> Dict[str, Any]:
        """
        Konvertera VersionDiff till dictionary.

        Args:
            version_diff: VersionDiff

        Returns:
            Dict med all versions-diff-information
        """
        try:
            return version_diff.to_dict()
        except Exception as exc:
            _log.error("Fel i version_diff_to_dict: %s", exc)
            return {"error": str(exc)}

    def diff_to_json(
        self,
        diff: PostTypeDiff,
        indent: int = 2,
    ) -> str:
        """
        Serialisera PostTypeDiff till JSON-sträng.

        Args:
            diff:   PostTypeDiff
            indent: JSON-indentering

        Returns:
            JSON-sträng
        """
        try:
            return json.dumps(
                self.diff_to_dict(diff),
                ensure_ascii=False,
                indent=indent,
            )
        except Exception as exc:
            _log.error("Fel i diff_to_json: %s", exc)
            return json.dumps({"error": str(exc)})

    def version_diff_to_json(
        self,
        version_diff: VersionDiff,
        indent: int = 2,
    ) -> str:
        """
        Serialisera VersionDiff till JSON-sträng.

        Args:
            version_diff: VersionDiff
            indent:       JSON-indentering

        Returns:
            JSON-sträng
        """
        try:
            return json.dumps(
                self.version_diff_to_dict(version_diff),
                ensure_ascii=False,
                indent=indent,
            )
        except Exception as exc:
            _log.error("Fel i version_diff_to_json: %s", exc)
            return json.dumps({"error": str(exc)})

    # ──────────────────────────────────────────────────────────────────────
    # UTILITY
    # ──────────────────────────────────────────────────────────────────────

    def has_changes(self, diff: PostTypeDiff) -> bool:
        """
        Kontrollera om en PostTypeDiff innehåller ändringar.

        Args:
            diff: PostTypeDiff

        Returns:
            True om det finns ändringar
        """
        try:
            return diff.has_changes
        except Exception:
            return False

    def is_breaking_change(self, field_diff: FieldDiff) -> bool:
        """
        Kontrollera om ett FieldDiff är en breaking change.

        Breaking changes:
          - Fält borttaget
          - Position ändrad
          - Längd minskad
          - Typ ändrad

        Args:
            field_diff: FieldDiff

        Returns:
            True om breaking change
        """
        try:
            return field_diff.is_breaking
        except Exception:
            return False

    def get_breaking_changes(
        self, diff: PostTypeDiff
    ) -> List[FieldDiff]:
        """
        Hämta alla breaking changes från en PostTypeDiff.

        Args:
            diff: PostTypeDiff

        Returns:
            Lista med FieldDiff som är breaking changes
        """
        try:
            return diff.breaking_changes
        except Exception as exc:
            _log.error("Fel i get_breaking_changes: %s", exc)
            return []

    def __repr__(self) -> str:
        return f"<SchemaDiff v{VERSION}>"


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL SINGLETON (convenience)
# ══════════════════════════════════════════════════════════════════════════════

# Förkonfigurerad instans för direkt användning
_default_diff: Optional[SchemaDiff] = None


def get_schema_diff() -> SchemaDiff:
    """
    Hämta den gemensamma SchemaDiff-instansen (singleton).

    Returns:
        SchemaDiff-instans
    """
    global _default_diff
    if _default_diff is None:
        _default_diff = SchemaDiff()
    return _default_diff


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "FieldChange",
    "FieldDiff",
    "PostTypeDiff",
    "VersionDiff",
    "SchemaDiff",
    "get_schema_diff",
    "VERSION",
    "AUTHOR",
    "SYMBOL_ADDED",
    "SYMBOL_REMOVED",
    "SYMBOL_CHANGED",
    "SYMBOL_UNCHANGED",
    "get_copyright_string",
]
