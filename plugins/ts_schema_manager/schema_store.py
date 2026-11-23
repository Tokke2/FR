# -*- coding: utf-8 -*-
# Fil: plugins/ts_schema_manager/schema_store.py
"""
Schema Store v1.0.1 — Persistent lagring av TS-scheman

ANSVAR:
  - Läsa och skriva PostSpec till JSON-filer (atomiskt)
  - Läsa och skriva manifest.json per version
  - Söka och filtrera scheman
  - Exportera/importera enskilda scheman
  - Validera JSON-integritet vid läsning
  - Kraschsäkra operationer med tydliga fallbacks

LAGRING (spec v1.4 / Sektion Z):
  specs_dir injiceras av plugin.py via _resolve_specs_dir():
    json/schemas/<version>/   (primärt)
    data/ts_specs/<version>/  (legacy fallback)

IMPORTER:
  json, logging, os, tempfile, shutil, hashlib, datetime, pathlib, typing
  .models (PostSpec, FieldSpec, SpecVersion) via lazy import

EXPORTERAR:
  SchemaStore  - huvudklass
  StoreResult  - dataclass för operationsresultat

PUBLIKT API (SchemaStore):
  ─── LÄSNING ───
  load_spec(post_type, version)           -> Optional[PostSpec]
  load_all_specs(version)                 -> Dict[str, PostSpec]
  load_manifest(version)                  -> Optional[SpecVersion]
  list_versions()                         -> List[str]
  list_spec_files(version)               -> List[Path]
  version_exists(version)                -> bool
  spec_exists(post_type, version)        -> bool

  ─── SKRIVNING ───
  save_spec(post_type, spec, version)    -> StoreResult
  save_all_specs(specs, version, ...)    -> StoreResult
  save_manifest(version, manifest)       -> StoreResult
  delete_spec(post_type, version)        -> StoreResult
  delete_version(version)               -> StoreResult

  ─── SÖKNING ───
  find_versions_with_post_type(pt)       -> List[str]
  find_specs_by_field(field_name)        -> List[Dict]
  get_all_post_types()                   -> Dict[str, List[str]]
  search_specs(query)                    -> List[Dict]

  ─── EXPORT/IMPORT ───
  export_spec_to_file(pt, version, path) -> StoreResult
  import_spec_from_file(path, version)   -> Optional[PostSpec]
  export_version_to_dir(version, path)   -> StoreResult
  import_version_from_dir(path, version) -> StoreResult

  ─── UTILITY ───
  get_store_stats()                      -> Dict
  verify_integrity(version)             -> Dict
  clear_version_cache(version)          -> None
  clear_all_caches()                    -> None

ANVÄNDS AV:
  plugins/ts_schema_manager/plugin.py
  plugins/ts_schema_manager/version_manager.py

FÖRÄNDRINGAR v1.0.1 (Session 11 — granskad, spec v1.6 förbättringsregeln):
  - FIX (BUGG #5): hårdkodad copyright-rad "# Copyright © 2025 ..."
    BORTTAGEN — copyright genereras dynamiskt via get_copyright_string().
  - _get_copyright_string -> get_copyright_string (publik, konsistent
    med version_manager.py och övriga filer) + i __all__.
  - SEKTION Z-notis (spec v1.4): specs_dir injiceras av plugin.py via
    _resolve_specs_dir() — json/schemas primärt, data/ts_specs legacy.
  - Övrig logik OFÖRÄNDRAD (atomisk skrivning, cache, sökning,
    export/import, integritet, kraschsäkerhet).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
MANIFEST_FILENAME: Final[str] = "manifest.json"
SPEC_FILE_PREFIX: Final[str] = "PT"
SPEC_FILE_SUFFIX: Final[str] = ".json"
SKIP_DIRS: Final[frozenset] = frozenset({"backup", ".git", "__pycache__"})


def get_copyright_string() -> str:
    """Dynamisk copyright-sträng."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# LAZY IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

_PostSpec: Optional[Any] = None
_FieldSpec: Optional[Any] = None
_SpecVersion: Optional[Any] = None


def _get_PostSpec() -> Any:
    """Lazy import av PostSpec från models.py."""
    global _PostSpec
    if _PostSpec is None:
        from .models import PostSpec  # type: ignore[import]
        _PostSpec = PostSpec
    return _PostSpec


def _get_FieldSpec() -> Any:
    """Lazy import av FieldSpec från models.py."""
    global _FieldSpec
    if _FieldSpec is None:
        from .models import FieldSpec  # type: ignore[import]
        _FieldSpec = FieldSpec
    return _FieldSpec


def _get_SpecVersion() -> Any:
    """Lazy import av SpecVersion från models.py."""
    global _SpecVersion
    if _SpecVersion is None:
        from .models import SpecVersion  # type: ignore[import]
        _SpecVersion = SpecVersion
    return _SpecVersion


# ══════════════════════════════════════════════════════════════════════════════
# ATOMISK FILSKRIVNING
# ══════════════════════════════════════════════════════════════════════════════

def _atomic_write_json(path: Path, data: Any) -> None:
    """
    Skriv JSON atomiskt: temp-fil → fsync → os.replace → slutlig fil.

    Args:
        path: Slutlig målsökväg
        data: Data att serialisera

    Raises:
        OSError: Om os.replace misslyckas
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_str = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.tmp_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path_str, path)
    except Exception:
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# STORE RESULT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class StoreResult:
    """
    Resultat från en SchemaStore-operation.

    Attributes:
        success:   Om operationen lyckades
        message:   Beskrivande meddelande
        errors:    Lista med felmeddelanden
        data:      Valfri extra data (dict)
        files:     Lista med påverkade filer
    """

    success: bool = False
    message: str = ""
    errors: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    files: List[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        """Lägg till felmeddelande och sätt success=False."""
        self.errors.append(error)
        self.success = False

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return {
            "success": self.success,
            "message": self.message,
            "errors": self.errors,
            "data": self.data,
            "files": self.files,
        }

    def __repr__(self) -> str:
        status = "OK" if self.success else "FAIL"
        return f"<StoreResult {status}: {self.message}>"


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA STORE
# ══════════════════════════════════════════════════════════════════════════════

class SchemaStore:
    """
    Persistent lagring av TS-scheman i JSON-filer.

    Ansvarar ENBART för filoperationer — ingen affärslogik.
    Alla skrivoperationer är atomiska (.tmp → fsync → os.replace).
    Alla läsoperationer är kraschsäkra med tydliga fallbacks.

    LAGRING (spec v1.4 / Sektion Z):
      {specs_dir}/
        {version}/
          manifest.json
          PT28.json
          PT45.json
          PT99.json

    CACHE:
      In-memory cache per version för laddade PostSpec.
      Invalideras vid skrivning till den versionen.
    """

    def __init__(self, specs_dir: Path) -> None:
        """
        Initiera SchemaStore.

        Args:
            specs_dir: Rotkatalog för alla versioner
                       (json/schemas primärt, spec v1.4/Sektion Z)
        """
        self._specs_dir: Path = Path(specs_dir)
        self._specs_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache: version → {post_type: PostSpec}
        self._cache: Dict[str, Dict[str, Any]] = {}

        _log.debug(
            "SchemaStore initierad: %s", self._specs_dir
        )

    # ──────────────────────────────────────────────────────────────────────
    # INTERNA HJÄLPMETODER
    # ──────────────────────────────────────────────────────────────────────

    def _version_dir(self, version: str) -> Path:
        """Sökväg till versions-katalog."""
        return self._specs_dir / version

    def _manifest_path(self, version: str) -> Path:
        """Sökväg till manifest.json."""
        return self._version_dir(version) / MANIFEST_FILENAME

    def _spec_path(self, post_type: str, version: str) -> Path:
        """Sökväg till PT{post_type}.json."""
        return (
            self._version_dir(version)
            / f"{SPEC_FILE_PREFIX}{post_type}{SPEC_FILE_SUFFIX}"
        )

    def _is_valid_version_dir(self, path: Path) -> bool:
        """
        Kontrollera om en katalog är en giltig versions-katalog.

        En giltig versions-katalog:
        - är en katalog
        - börjar inte med '.'
        - finns inte i SKIP_DIRS
        - innehåller manifest.json
        """
        if not path.is_dir():
            return False
        if path.name.startswith("."):
            return False
        if path.name in SKIP_DIRS:
            return False
        return (path / MANIFEST_FILENAME).exists()

    def _invalidate_cache(self, version: str) -> None:
        """Invalidera cache för en version."""
        self._cache.pop(version, None)

    def _read_json_file(self, path: Path) -> Optional[Any]:
        """
        Läs JSON-fil säkert.

        Args:
            path: Sökväg till JSON-fil

        Returns:
            Parsed data eller None vid fel
        """
        try:
            if not path.exists():
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as exc:
            _log.error(
                "Ogiltig JSON i %s: %s", path, exc
            )
            return None
        except Exception as exc:
            _log.error(
                "Kunde inte läsa %s: %s", path, exc, exc_info=True
            )
            return None

    # ──────────────────────────────────────────────────────────────────────
    # LÄSNING
    # ──────────────────────────────────────────────────────────────────────

    def load_spec(
        self,
        post_type: str,
        version: str,
    ) -> Optional[Any]:
        """
        Ladda PostSpec för en posttyp i en version.

        Använder cache om tillgänglig.

        Args:
            post_type: Posttypskod (t.ex. "45")
            version:   Versionsnamn

        Returns:
            PostSpec eller None om ej hittad
        """
        try:
            # Cache-träff
            if version in self._cache:
                return self._cache[version].get(post_type)

            path = self._spec_path(post_type, version)
            data = self._read_json_file(path)
            if data is None:
                return None

            PostSpec = _get_PostSpec()
            spec = PostSpec.from_dict(data)
            _log.debug(
                "Laddade PT%s från version '%s'", post_type, version
            )
            return spec

        except Exception as exc:
            _log.error(
                "Fel vid laddning av PT%s i '%s': %s",
                post_type, version, exc, exc_info=True,
            )
            return None

    def load_all_specs(self, version: str) -> Dict[str, Any]:
        """
        Ladda alla PostSpec för en version.

        Caches resultatet för snabbare framtida åtkomst.

        Args:
            version: Versionsnamn

        Returns:
            Dict med post_type → PostSpec (tom vid fel)
        """
        try:
            # Cache-träff
            if version in self._cache:
                return dict(self._cache[version])

            version_dir = self._version_dir(version)
            if not version_dir.exists():
                _log.debug(
                    "Versions-katalog saknas: %s", version_dir
                )
                return {}

            PostSpec = _get_PostSpec()
            specs: Dict[str, Any] = {}

            for spec_file in sorted(version_dir.glob(
                f"{SPEC_FILE_PREFIX}*{SPEC_FILE_SUFFIX}"
            )):
                data = self._read_json_file(spec_file)
                if data is None:
                    continue
                try:
                    spec = PostSpec.from_dict(data)
                    specs[spec.post_type] = spec
                except Exception as exc:
                    _log.warning(
                        "Kunde inte parsa %s: %s", spec_file.name, exc
                    )

            # Spara i cache
            self._cache[version] = specs
            _log.debug(
                "Laddade %d specs för version '%s'",
                len(specs), version,
            )
            return dict(specs)

        except Exception as exc:
            _log.error(
                "Fel vid laddning av version '%s': %s",
                version, exc, exc_info=True,
            )
            return {}

    def load_manifest(self, version: str) -> Optional[Any]:
        """
        Ladda manifest.json för en version.

        Args:
            version: Versionsnamn

        Returns:
            SpecVersion eller None om ej hittad
        """
        try:
            data = self._read_json_file(self._manifest_path(version))
            if data is None:
                return None

            SpecVersion = _get_SpecVersion()
            manifest = SpecVersion.from_dict(data)
            _log.debug("Laddade manifest för version '%s'", version)
            return manifest

        except Exception as exc:
            _log.error(
                "Fel vid laddning av manifest '%s': %s",
                version, exc, exc_info=True,
            )
            return None

    def list_versions(self) -> List[str]:
        """
        Lista alla giltiga versioner (sorterade).

        Returns:
            Lista med versionsnamn (tom vid fel)
        """
        try:
            if not self._specs_dir.exists():
                return []

            versions = [
                d.name
                for d in sorted(self._specs_dir.iterdir())
                if self._is_valid_version_dir(d)
            ]
            return versions

        except Exception as exc:
            _log.error(
                "Fel vid listning av versioner: %s", exc, exc_info=True
            )
            return []

    def list_spec_files(self, version: str) -> List[Path]:
        """
        Lista alla PT*.json-filer för en version.

        Args:
            version: Versionsnamn

        Returns:
            Lista med Path-objekt (sorterade, tom vid fel)
        """
        try:
            version_dir = self._version_dir(version)
            if not version_dir.exists():
                return []
            return sorted(version_dir.glob(
                f"{SPEC_FILE_PREFIX}*{SPEC_FILE_SUFFIX}"
            ))
        except Exception as exc:
            _log.error(
                "Fel vid listning av spec-filer '%s': %s",
                version, exc,
            )
            return []

    def version_exists(self, version: str) -> bool:
        """
        Kontrollera om en version finns (manifest.json existerar).

        Args:
            version: Versionsnamn

        Returns:
            True om versionen finns
        """
        return self._manifest_path(version).exists()

    def spec_exists(self, post_type: str, version: str) -> bool:
        """
        Kontrollera om en spec-fil finns.

        Args:
            post_type: Posttypskod
            version:   Versionsnamn

        Returns:
            True om PT{post_type}.json finns
        """
        return self._spec_path(post_type, version).exists()

    # ──────────────────────────────────────────────────────────────────────
    # SKRIVNING
    # ──────────────────────────────────────────────────────────────────────

    def save_spec(
        self,
        post_type: str,
        spec: Any,
        version: str,
    ) -> StoreResult:
        """
        Spara en PostSpec till fil (atomiskt).

        Invaliderar cache för versionen.

        Args:
            post_type: Posttypskod
            spec:      PostSpec att spara
            version:   Versionsnamn

        Returns:
            StoreResult med success/error
        """
        result = StoreResult()

        try:
            if not self.version_exists(version):
                result.add_error(
                    f"Version '{version}' saknas (skapa med save_all_specs)"
                )
                return result

            path = self._spec_path(post_type, version)
            _atomic_write_json(path, spec.to_dict())
            self._invalidate_cache(version)

            result.success = True
            result.message = f"PT{post_type} sparad i '{version}'"
            result.files.append(str(path))
            _log.debug(
                "Sparade PT%s i version '%s'", post_type, version
            )

        except Exception as exc:
            result.add_error(str(exc))
            _log.error(
                "Fel vid sparande av PT%s: %s",
                post_type, exc, exc_info=True,
            )

        return result

    def save_all_specs(
        self,
        specs: Dict[str, Any],
        version: str,
        source_file: str = "",
        description: str = "",
        set_active: bool = False,
    ) -> StoreResult:
        """
        Spara alla PostSpec för en version atomiskt.

        Skapar katalogen och manifest.json.
        Använder temp-katalog → rename för atomisk operation.

        Args:
            specs:       Dict med post_type → PostSpec
            version:     Versionsnamn
            source_file: Källfil (metadata)
            description: Beskrivning (metadata)
            set_active:  Ignoreras här (hanteras av VersionManager)

        Returns:
            StoreResult med success/error och antal sparade specs
        """
        result = StoreResult()
        version_dir = self._version_dir(version)
        temp_dir = self._specs_dir / f".{version}_temp"

        try:
            temp_dir.mkdir(parents=True, exist_ok=True)

            post_types: List[str] = []
            saved_files: List[str] = []

            for pt, spec in specs.items():
                spec_path = (
                    temp_dir
                    / f"{SPEC_FILE_PREFIX}{pt}{SPEC_FILE_SUFFIX}"
                )
                _atomic_write_json(spec_path, spec.to_dict())
                post_types.append(pt)
                saved_files.append(str(spec_path))

            # Skapa manifest
            SpecVersion = _get_SpecVersion()
            manifest = SpecVersion(
                version=version,
                created_at=datetime.now().isoformat(),
                source_file=source_file,
                post_types=sorted(post_types),
                description=description,
            )
            manifest_path = temp_dir / MANIFEST_FILENAME
            _atomic_write_json(manifest_path, manifest.to_dict())
            saved_files.append(str(manifest_path))

            # Backup av befintlig version
            backup_path = self._specs_dir / f".{version}_backup"
            if version_dir.exists():
                if backup_path.exists():
                    shutil.rmtree(backup_path)
                version_dir.rename(backup_path)

            # Atomisk rename: temp → slutlig
            temp_dir.rename(version_dir)

            # Ta bort backup
            if backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)

            # Invalidera cache
            self._invalidate_cache(version)

            result.success = True
            result.message = (
                f"Sparade {len(post_types)} specs för version '{version}'"
            )
            result.files = saved_files
            result.data = {
                "version": version,
                "post_types": post_types,
                "count": len(post_types),
            }
            _log.info(
                "Sparade %d specs för version '%s'",
                len(post_types), version,
            )

        except Exception as exc:
            # Städa upp temp-katalog
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            result.add_error(str(exc))
            _log.error(
                "Fel vid sparande av version '%s': %s",
                version, exc, exc_info=True,
            )

        return result

    def save_manifest(
        self,
        version: str,
        manifest: Any,
    ) -> StoreResult:
        """
        Spara manifest.json för en version (atomiskt).

        Args:
            version:  Versionsnamn
            manifest: SpecVersion att spara

        Returns:
            StoreResult med success/error
        """
        result = StoreResult()

        try:
            path = self._manifest_path(version)
            if not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)

            _atomic_write_json(path, manifest.to_dict())
            result.success = True
            result.message = f"Manifest sparad för version '{version}'"
            result.files.append(str(path))
            _log.debug("Sparade manifest för version '%s'", version)

        except Exception as exc:
            result.add_error(str(exc))
            _log.error(
                "Fel vid sparande av manifest '%s': %s",
                version, exc, exc_info=True,
            )

        return result

    def delete_spec(
        self,
        post_type: str,
        version: str,
    ) -> StoreResult:
        """
        Ta bort en spec-fil.

        Args:
            post_type: Posttypskod
            version:   Versionsnamn

        Returns:
            StoreResult med success/error
        """
        result = StoreResult()

        try:
            path = self._spec_path(post_type, version)
            if not path.exists():
                result.add_error(
                    f"PT{post_type}.json finns inte i version '{version}'"
                )
                return result

            path.unlink()
            self._invalidate_cache(version)

            # Uppdatera manifest
            manifest = self.load_manifest(version)
            if manifest and post_type in manifest.post_types:
                manifest.post_types.remove(post_type)
                self.save_manifest(version, manifest)

            result.success = True
            result.message = (
                f"PT{post_type} borttagen från version '{version}'"
            )
            result.files.append(str(path))
            _log.info(
                "Tog bort PT%s från version '%s'", post_type, version
            )

        except Exception as exc:
            result.add_error(str(exc))
            _log.error(
                "Fel vid borttagning av PT%s: %s",
                post_type, exc, exc_info=True,
            )

        return result

    def delete_version(self, version: str) -> StoreResult:
        """
        Ta bort en hel version (katalog och allt innehåll).

        Args:
            version: Versionsnamn

        Returns:
            StoreResult med success/error
        """
        result = StoreResult()

        try:
            version_dir = self._version_dir(version)
            if not version_dir.exists():
                result.add_error(f"Version '{version}' finns inte")
                return result

            # Lista filer innan borttagning
            for f in version_dir.glob("*.json"):
                result.files.append(str(f))

            shutil.rmtree(version_dir)
            self._invalidate_cache(version)

            result.success = True
            result.message = f"Version '{version}' borttagen"
            _log.info("Tog bort version: %s", version)

        except Exception as exc:
            result.add_error(str(exc))
            _log.error(
                "Fel vid borttagning av version '%s': %s",
                version, exc, exc_info=True,
            )

        return result

    # ──────────────────────────────────────────────────────────────────────
    # SÖKNING
    # ──────────────────────────────────────────────────────────────────────

    def find_versions_with_post_type(
        self, post_type: str
    ) -> List[str]:
        """
        Hitta alla versioner som innehåller en viss posttyp.

        Args:
            post_type: Posttypskod

        Returns:
            Lista med versionsnamn (sorterade)
        """
        try:
            return [
                v for v in self.list_versions()
                if self.spec_exists(post_type, v)
            ]
        except Exception as exc:
            _log.error(
                "Fel i find_versions_with_post_type(%s): %s",
                post_type, exc,
            )
            return []

    def find_specs_by_field(
        self,
        field_name: str,
        version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Sök specs som innehåller ett fält med givet namn.

        Case-insensitive substring-sökning på fältnamn.

        Args:
            field_name: Fältnamn eller del av fältnamn
            version:    Specifik version (None = alla versioner)

        Returns:
            Lista med matchningar:
              version, post_type, field_name, position, length, type
        """
        results: List[Dict[str, Any]] = []
        pattern = field_name.upper()

        versions_to_check = (
            [version] if version else self.list_versions()
        )

        for ver in versions_to_check:
            try:
                specs = self.load_all_specs(ver)
                for pt, spec in specs.items():
                    for fld in spec.fields:
                        if pattern in fld.name.upper():
                            results.append({
                                "version": ver,
                                "post_type": pt,
                                "field_name": fld.name,
                                "position": fld.position,
                                "length": fld.length,
                                "type": fld.field_type,
                                "required": fld.mandatory,
                                "description": fld.description,
                            })
            except Exception as exc:
                _log.warning(
                    "Fel vid sökning i version '%s': %s", ver, exc
                )

        return results

    def get_all_post_types(self) -> Dict[str, List[str]]:
        """
        Lista alla posttyper över alla versioner.

        Returns:
            Dict med post_type → lista med versioner
            Sorterat alfabetiskt på posttyp.
        """
        result: Dict[str, List[str]] = {}

        for version in self.list_versions():
            try:
                manifest = self.load_manifest(version)
                post_types = (
                    manifest.post_types if manifest else []
                )
                for pt in post_types:
                    if pt not in result:
                        result[pt] = []
                    result[pt].append(version)
            except Exception as exc:
                _log.warning(
                    "Fel vid hämtning av posttyper för '%s': %s",
                    version, exc,
                )

        return dict(sorted(result.items()))

    def search_specs(self, query: str) -> List[Dict[str, Any]]:
        """
        Sök i alla specs (fältnamn, posttypsnamn, version).

        Case-insensitive substring-sökning.

        Args:
            query: Sökterm

        Returns:
            Lista med matchande specs (version, post_type, name, match_type)
        """
        results: List[Dict[str, Any]] = []
        q = query.upper()

        for version in self.list_versions():
            try:
                specs = self.load_all_specs(version)
                for pt, spec in specs.items():
                    # Matcha på posttyp
                    if q in pt.upper():
                        results.append({
                            "version": version,
                            "post_type": pt,
                            "name": spec.name,
                            "match_type": "post_type",
                        })
                        continue

                    # Matcha på spec-namn
                    if q in spec.name.upper():
                        results.append({
                            "version": version,
                            "post_type": pt,
                            "name": spec.name,
                            "match_type": "name",
                        })
                        continue

                    # Matcha på fältnamn
                    for fld in spec.fields:
                        if q in fld.name.upper():
                            results.append({
                                "version": version,
                                "post_type": pt,
                                "name": spec.name,
                                "match_type": "field",
                                "field_name": fld.name,
                            })
                            break
            except Exception as exc:
                _log.warning(
                    "Fel vid sökning i version '%s': %s", version, exc
                )

        return results

    # ──────────────────────────────────────────────────────────────────────
    # EXPORT / IMPORT
    # ──────────────────────────────────────────────────────────────────────

    def export_spec_to_file(
        self,
        post_type: str,
        version: str,
        output_path: Path,
    ) -> StoreResult:
        """
        Exportera en enskild PostSpec till extern JSON-fil.

        Args:
            post_type:   Posttypskod
            version:     Versionsnamn
            output_path: Sökväg till output-fil

        Returns:
            StoreResult med success/error
        """
        result = StoreResult()

        try:
            spec = self.load_spec(post_type, version)
            if spec is None:
                result.add_error(
                    f"PT{post_type} hittades inte i version '{version}'"
                )
                return result

            out = Path(output_path)
            _atomic_write_json(out, spec.to_dict())

            result.success = True
            result.message = (
                f"Exporterade PT{post_type} till {out.name}"
            )
            result.files.append(str(out))
            _log.info(
                "Exporterade PT%s till %s", post_type, out
            )

        except Exception as exc:
            result.add_error(str(exc))
            _log.error(
                "Fel vid export av PT%s: %s",
                post_type, exc, exc_info=True,
            )

        return result

    def import_spec_from_file(
        self,
        input_path: Path,
        version: str,
    ) -> Optional[Any]:
        """
        Importera en PostSpec från extern JSON-fil och spara till version.

        Args:
            input_path: Sökväg till JSON-fil
            version:    Versionsnamn att spara i

        Returns:
            PostSpec vid framgång, None vid fel
        """
        try:
            data = self._read_json_file(Path(input_path))
            if data is None:
                _log.error(
                    "Kunde inte läsa %s", input_path
                )
                return None

            PostSpec = _get_PostSpec()
            spec = PostSpec.from_dict(data)

            result = self.save_spec(spec.post_type, spec, version)
            if result.success:
                _log.info(
                    "Importerade PT%s från %s",
                    spec.post_type, input_path,
                )
                return spec

            _log.error(
                "Kunde inte spara importerad spec: %s",
                result.errors,
            )
            return None

        except Exception as exc:
            _log.error(
                "Fel vid import från %s: %s",
                input_path, exc, exc_info=True,
            )
            return None

    def export_version_to_dir(
        self,
        version: str,
        output_dir: Path,
    ) -> StoreResult:
        """
        Exportera alla filer för en version till extern katalog.

        Args:
            version:    Versionsnamn
            output_dir: Målkatalog (skapas om den saknas)

        Returns:
            StoreResult med success/error och antal exporterade filer
        """
        result = StoreResult()

        try:
            version_dir = self._version_dir(version)
            if not version_dir.exists():
                result.add_error(
                    f"Version '{version}' finns inte"
                )
                return result

            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)

            count = 0
            for src in sorted(version_dir.glob("*.json")):
                dst = out / src.name
                shutil.copy2(src, dst)
                result.files.append(str(dst))
                count += 1

            result.success = True
            result.message = (
                f"Exporterade {count} filer från '{version}' till {out.name}"
            )
            result.data = {
                "version": version,
                "output_dir": str(out),
                "file_count": count,
            }
            _log.info(
                "Exporterade version '%s' (%d filer) till %s",
                version, count, out,
            )

        except Exception as exc:
            result.add_error(str(exc))
            _log.error(
                "Fel vid export av version '%s': %s",
                version, exc, exc_info=True,
            )

        return result

    def import_version_from_dir(
        self,
        input_dir: Path,
        version: Optional[str] = None,
    ) -> StoreResult:
        """
        Importera en version från extern katalog.

        Letar efter PT*.json och manifest.json.
        Auto-genererar versionsnamn om inte angivet.

        Args:
            input_dir: Källkatalog
            version:   Versionsnamn (auto om None)

        Returns:
            StoreResult med success/error och info om importerad version
        """
        result = StoreResult()

        try:
            src = Path(input_dir)
            if not src.exists():
                result.add_error(f"Källkatalog '{src}' finns inte")
                return result

            PostSpec = _get_PostSpec()
            specs: Dict[str, Any] = {}

            for spec_file in sorted(src.glob(
                f"{SPEC_FILE_PREFIX}*{SPEC_FILE_SUFFIX}"
            )):
                data = self._read_json_file(spec_file)
                if data is None:
                    result.errors.append(
                        f"Kunde inte läsa {spec_file.name}"
                    )
                    continue
                try:
                    spec = PostSpec.from_dict(data)
                    specs[spec.post_type] = spec
                except Exception as exc:
                    result.errors.append(
                        f"Kunde inte parsa {spec_file.name}: {exc}"
                    )

            if not specs:
                result.add_error(
                    "Inga giltiga PT*.json-filer hittades"
                )
                return result

            # Hämta/generera versionsnamn
            target_version = version
            if not target_version:
                # Försök läsa från manifest
                manifest_data = self._read_json_file(
                    src / MANIFEST_FILENAME
                )
                if manifest_data and "version" in manifest_data:
                    target_version = manifest_data["version"]
                else:
                    target_version = (
                        f"imported_"
                        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    )

            # Spara
            store_result = self.save_all_specs(
                specs,
                target_version,
                source_file=str(src),
                description=f"Importerad från {src.name}",
            )

            if store_result.success:
                result.success = True
                result.message = (
                    f"Importerade {len(specs)} specs som version "
                    f"'{target_version}'"
                )
                result.files = store_result.files
                result.data = {
                    "version": target_version,
                    "post_types": list(specs.keys()),
                    "count": len(specs),
                }
                _log.info(
                    "Importerade version '%s' (%d specs) från %s",
                    target_version, len(specs), src,
                )
            else:
                result.errors.extend(store_result.errors)
                result.add_error(
                    f"Kunde inte spara version '{target_version}'"
                )

        except Exception as exc:
            result.add_error(str(exc))
            _log.error(
                "Fel vid import från '%s': %s",
                input_dir, exc, exc_info=True,
            )

        return result

    # ──────────────────────────────────────────────────────────────────────
    # UTILITY
    # ──────────────────────────────────────────────────────────────────────

    def get_store_stats(self) -> Dict[str, Any]:
        """
        Hämta statistik om store-innehållet.

        Returns:
            Dict med version_count, total_specs, total_size_bytes,
            versions, copyright
        """
        try:
            versions = self.list_versions()
            total_specs = 0
            total_size = 0

            for version in versions:
                specs = self.load_all_specs(version)
                total_specs += len(specs)
                for f in self._version_dir(version).glob("*.json"):
                    try:
                        total_size += f.stat().st_size
                    except OSError:
                        pass

            return {
                "version_count": len(versions),
                "versions": versions,
                "total_specs": total_specs,
                "total_size_bytes": total_size,
                "cached_versions": list(self._cache.keys()),
                "specs_dir": str(self._specs_dir),
                "copyright": get_copyright_string(),
            }

        except Exception as exc:
            _log.error(
                "Fel i get_store_stats: %s", exc, exc_info=True
            )
            return {"error": str(exc)}

    def verify_integrity(self, version: str) -> Dict[str, Any]:
        """
        Verifiera integritet för en version.

        Kontrollerar:
        - manifest.json finns
        - Alla deklarerade PT*.json finns
        - JSON-filer är parsningsbara
        - Checksummor (om tillgängliga)

        Args:
            version: Versionsnamn

        Returns:
            Dict med valid, errors, warnings, stats
        """
        result: Dict[str, Any] = {
            "valid": False,
            "version": version,
            "errors": [],
            "warnings": [],
            "stats": {},
        }

        try:
            # Manifest
            manifest = self.load_manifest(version)
            if manifest is None:
                result["errors"].append("manifest.json saknas eller korrupt")
                return result

            declared = set(manifest.post_types)
            result["stats"]["declared_post_types"] = list(declared)

            # Kontrollera att deklarerade filer finns
            for pt in declared:
                if not self.spec_exists(pt, version):
                    result["errors"].append(
                        f"Deklarerad PT{pt}.json saknas"
                    )

            # Ladda och kontrollera specs
            specs = self.load_all_specs(version)
            result["stats"]["loaded_specs"] = len(specs)
            result["stats"]["total_fields"] = sum(
                len(s.fields) for s in specs.values()
            )

            # Kontrollera undeklared filer
            for spec_file in self.list_spec_files(version):
                pt_from_file = spec_file.stem.replace(SPEC_FILE_PREFIX, "")
                if pt_from_file not in declared:
                    result["warnings"].append(
                        f"PT{pt_from_file}.json finns men ej deklarerad i manifest"
                    )

            # Checksummor
            for pt, spec in specs.items():
                if spec.checksum:
                    actual = spec._calculate_checksum()
                    if actual != spec.checksum:
                        result["warnings"].append(
                            f"PT{pt}: checksumma stämmer ej "
                            f"(lagrad: {spec.checksum}, beräknad: {actual})"
                        )

            result["valid"] = len(result["errors"]) == 0

        except Exception as exc:
            result["errors"].append(str(exc))
            _log.error(
                "Fel vid integritetsverifiering av '%s': %s",
                version, exc, exc_info=True,
            )

        return result

    def clear_version_cache(self, version: str) -> None:
        """
        Rensa cache för en specifik version.

        Args:
            version: Versionsnamn
        """
        self._invalidate_cache(version)
        _log.debug("Cache rensad för version: %s", version)

    def clear_all_caches(self) -> None:
        """Rensa all in-memory cache."""
        self._cache.clear()
        _log.debug("All cache rensad")

    def __repr__(self) -> str:
        versions = len(self.list_versions())
        cached = len(self._cache)
        return (
            f"<SchemaStore "
            f"dir={self._specs_dir.name} "
            f"versions={versions} "
            f"cached={cached}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "SchemaStore",
    "StoreResult",
    "VERSION",
    "AUTHOR",
    "MANIFEST_FILENAME",
    "SPEC_FILE_PREFIX",
    "SPEC_FILE_SUFFIX",
    "get_copyright_string",
]
