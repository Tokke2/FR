# -*- coding: utf-8 -*-
# Fil: plugins/ts_schema_manager/version_manager.py
"""
Versionshantering för TS-specifikationer v2.2.1

ANSVAR:
  - Hantera versioner av TS-specifikationer (skapa, ladda, ta bort)
  - Atomisk skrivning (.tmp → rename) för all filhantering
  - Caching av laddade versioner (TTL-baserad)
  - Versions-jämförelse (diff)
  - Backup-hantering
  - Historik-spårning (JSON-fil)
  - Callback-notifieringar vid ändringar
  - Config manager integration för persistent active_version
  - 10 avancerade funktioner (export, import, metadata, rename,
    duplicate, get_all_post_types, find_spec_by_field,
    validate_version_integrity, compact_version, get_version_timeline)

LAGRING (spec v1.4 / Sektion Z):
  specs_dir injiceras av plugin.py via _resolve_specs_dir():
    json/schemas/<version>/   (primärt)
    data/ts_specs/<version>/  (legacy fallback)
    ├── manifest.json    - versionsmetadata
    ├── PT28.json        - PT28-specifikation
    ├── PT45.json        - PT45-specifikation
    └── PT99.json        - PT99-specifikation

IMPORTER (EXTERNA):
  json, logging, os, shutil, tempfile, time, dataclasses, datetime,
  pathlib, typing
  .models (FieldSpec, PostSpec, SpecVersion) via lazy import

EXPORTERAR:
  SpecVersionManager     - huvudklass för versionshantering
  VersionHistoryEntry    - dataclass för historikposter
  VERSION, AUTHOR        - str konstanter
  TS_POST_LENGTH         - int = 2500
  TS_ENCODING            - str = "iso-8859-1"
  ACTIVE_VERSION_KEY     - str konstant
  BACKUP_DIR_NAME        - str konstant
  get_copyright_string() - funktion

PUBLIKT API (SpecVersionManager):
  active_version                          -> property (get/set)
  backup_dir                              -> property Path
  history_file                            -> property Path
  list_versions()                         -> List[SpecVersion]
  list_backups()                          -> List[Dict]
  get_version_dir(version)                -> Path
  version_exists(version)                 -> bool
  load_version(version, use_cache)        -> Dict[str, PostSpec]
  get_spec(post_type, version)            -> Optional[PostSpec]
  create_version(version, specs, ...)     -> None
  save_spec(post_type, spec, version)     -> None
  delete_version(version)                 -> None
  compare_versions(v1, v2)               -> Dict[str, List[str]]
  export_version_to_dir(version, path)   -> Dict
  import_version_from_dir(path, ...)     -> Dict
  get_version_metadata(version)          -> Dict
  rename_version(old, new)               -> bool
  duplicate_version(source, new)         -> bool
  get_all_post_types()                   -> Dict[str, List[str]]
  find_spec_by_field(field_name, ver)    -> List[Dict]
  validate_version_integrity(version)    -> Dict
  compact_version(version)               -> Dict
  get_version_timeline()                 -> List[Dict]
  get_history(post_type, limit)          -> List[Dict]
  subscribe(callback)                    -> None
  unsubscribe(callback)                  -> None
  clear_cache(version)                   -> None
  get_stats()                            -> Dict

ANVÄNDS AV:
  plugins/ts_schema_manager/plugin.py
  plugins/ts_spec_import/ (indirekt via plugin.py)
  plugins/ts_file_generator/ (indirekt via plugin.py)

FÖRÄNDRINGAR v2.2.1 (Session 11 — granskad, spec v1.6 förbättringsregeln):
  - FIX (BUGG #5): hårdkodad copyright-rad "# Copyright © 2025 ..."
    BORTTAGEN — copyright genereras dynamiskt via get_copyright_string().
  - logger -> _log (spec-konvention: module-level _log, ej logger).
  - import time flyttad till modulnivå (var lokal dubbel-import i
    load_version()).
  - SEKTION Z-notis (spec v1.4): specs_dir injiceras av plugin.py via
    _resolve_specs_dir() — json/schemas primärt, data/ts_specs legacy.
  - Övrig logik OFÖRÄNDRAD (atomisk skrivning, TTL-cache, diff,
    backup, historik, callbacks, 10 avancerade funktioner).

FÖRÄNDRINGAR v2.2.0:
  - Copyright uppdaterad: dynamiskt år via datetime.now().year
  - _get_copyright_year() tillagd
  - logger = _get_logger() (module-level, ej self.logger)
  - _atomic_write_text() använder os.replace() + fsync
  - compact_version() ej atomisk → fixad till atomisk skrivning
  - strip_object_columns()-pattern i _load_history() (nan-säkring)
  - get_stats() returnerar nu även "copyright" nyckel
  - __all__ komplett
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    Any, Callable, Dict, Final, List, Optional,
    Tuple, Union,
)

# ──────────────────────────────────────────────────────────────────────────────
# LAZY IMPORTS — undviker cirkulär import från models.py
# ──────────────────────────────────────────────────────────────────────────────

_models_cache: Dict[str, Any] = {}


def _get_FieldSpec() -> Any:
    """Lazy import av FieldSpec från models.py."""
    if "FieldSpec" not in _models_cache:
        from .models import FieldSpec  # type: ignore[import]
        _models_cache["FieldSpec"] = FieldSpec
    return _models_cache["FieldSpec"]


def _get_PostSpec() -> Any:
    """Lazy import av PostSpec från models.py."""
    if "PostSpec" not in _models_cache:
        from .models import PostSpec  # type: ignore[import]
        _models_cache["PostSpec"] = PostSpec
    return _models_cache["PostSpec"]


def _get_SpecVersion() -> Any:
    """Lazy import av SpecVersion från models.py."""
    if "SpecVersion" not in _models_cache:
        from .models import SpecVersion  # type: ignore[import]
        _models_cache["SpecVersion"] = SpecVersion
    return _models_cache["SpecVersion"]


def _get_models() -> Tuple[Any, Any, Any]:
    """Hämta alla tre modeller lazy."""
    return _get_FieldSpec(), _get_PostSpec(), _get_SpecVersion()


# ──────────────────────────────────────────────────────────────────────────────
# COPYRIGHT & VERSION
# ──────────────────────────────────────────────────────────────────────────────

VERSION: Final[str] = "2.2.1"
AUTHOR: Final[str] = "Rickard Längkvist"


def _get_copyright_year() -> int:
    """Hämta aktuellt år för copyright (dynamiskt)."""
    return datetime.now().year


def get_copyright_string() -> str:
    """
    Generera copyright-sträng med dynamiskt år.

    Returns:
        Sträng på formen "Copyright © YYYY Rickard Längkvist"
    """
    return f"Copyright © {_get_copyright_year()} {AUTHOR}"


# ──────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL LOGGER
# ──────────────────────────────────────────────────────────────────────────────

def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback om logging ej konfigurerat.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("ts_schema_manager.version_manager")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


_log: logging.Logger = _get_logger()

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

TS_POST_LENGTH: Final[int] = 2500
TS_ENCODING: Final[str] = "iso-8859-1"
ACTIVE_VERSION_KEY: Final[str] = "ts_schema_active_version"
BACKUP_DIR_NAME: Final[str] = "backup"
HISTORY_FILE_NAME: Final[str] = "history.json"
MAX_HISTORY_ENTRIES: Final[int] = 500
CACHE_TTL_SECONDS: Final[int] = 300

# Kataloger att hoppa över vid versionslisting
_SKIP_DIRS: Final[List[str]] = [BACKUP_DIR_NAME]


# ══════════════════════════════════════════════════════════════════════════════
# ATOMISK FILSKRIVNING (lokal, undviker cirkulär import)
# ══════════════════════════════════════════════════════════════════════════════

def _atomic_write_json(path: Path, data: Any) -> None:
    """
    Skriv JSON atomiskt: temp-fil → fsync → os.replace → slutlig fil.

    Förhindrar korrupta filer vid krasch under skrivning.

    Args:
        path: Slutlig målsökväg
        data: Data att serialisera till JSON

    Raises:
        OSError: Om rename misslyckas efter skrivning
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
# VERSION HISTORY ENTRY
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class VersionHistoryEntry:
    """
    En historikpost för versionsändringar.

    Attributes:
        timestamp: ISO-8601 tidsstämpel
        action:    Åtgärd (created, deleted, renamed, set_active,
                   spec_saved, compacted, exported, imported, duplicated)
        version:   Berörd version
        details:   Extra detaljer (dict, valfritt)
    """

    timestamp: str
    action: str
    version: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VersionHistoryEntry":
        """
        Skapa från dictionary. Kraschsäker – saknade nycklar ger default.

        Args:
            data: Dictionary med historikdata

        Returns:
            VersionHistoryEntry instans
        """
        return cls(
            timestamp=str(data.get("timestamp", "")),
            action=str(data.get("action", "")),
            version=str(data.get("version", "")),
            details=dict(data.get("details", {})),
        )

    def __repr__(self) -> str:
        return (
            f"<VersionHistoryEntry "
            f"{self.timestamp} {self.action} {self.version}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# SPEC VERSION MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class SpecVersionManager:
    """
    Hanterar versioner av TS-specifikationer.

    FEATURES:
      - Atomisk skrivning (temp → fsync → rename)
      - TTL-baserad caching (CACHE_TTL_SECONDS)
      - Versions-diff (compare_versions)
      - Backup via temp-dir-pattern vid create_version
      - Historik-spårning (history.json, max 500 poster)
      - Config manager integration (active_version persistent)
      - Callback-notifieringar (subscribe/unsubscribe)
      - Lazy loading av models.py (undviker cirkulär import)

    PUBLIKA METODER:
      Se modulens docstring ovan.

    USAGE:
      manager = SpecVersionManager(Path("json/schemas"))
      manager.create_version("v1", specs, set_active=True)
      spec = manager.get_spec("45")
    """

    def __init__(
        self,
        specs_dir: Path,
        config_manager: Any = None,
    ) -> None:
        """
        Initiera version manager.

        Args:
            specs_dir:      Katalog för specifikationsfiler
                            (json/schemas primärt, spec v1.4/Sektion Z)
            config_manager: Optional config manager för persistent
                            active_version. Stöder .get()/.set() eller dict.
        """
        self.specs_dir: Path = Path(specs_dir)
        self.config_manager: Any = config_manager

        self.specs_dir.mkdir(parents=True, exist_ok=True)

        # Cache: version → {post_type: PostSpec}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._active_version_cache: Optional[str] = None

        # Historik
        self._history: List[VersionHistoryEntry] = []
        self._load_history()

        # Callbacks
        self._change_callbacks: List[
            Callable[[str, Dict[str, Any]], None]
        ] = []

        _log.debug(
            "SpecVersionManager initierad: %s", self.specs_dir
        )

    # ──────────────────────────────────────────────────────────────────────
    # PROPERTIES
    # ──────────────────────────────────────────────────────────────────────

    @property
    def active_version(self) -> Optional[str]:
        """
        Hämta aktiv version.

        Prioritetsordning:
          1. In-memory cache
          2. Config manager (.get() eller dict)
          3. Fallback: senaste versionen i listan
        """
        if self._active_version_cache:
            return self._active_version_cache

        if self.config_manager:
            try:
                if hasattr(self.config_manager, "get"):
                    result = self.config_manager.get(ACTIVE_VERSION_KEY)
                elif isinstance(self.config_manager, dict):
                    result = self.config_manager.get(ACTIVE_VERSION_KEY)
                else:
                    result = None

                if result:
                    self._active_version_cache = result
                    return result
            except Exception as exc:
                _log.debug(
                    "Kunde inte hämta active_version från config: %s", exc
                )

        versions = self.list_versions()
        if versions:
            return versions[-1].version

        return None

    @active_version.setter
    def active_version(self, version: str) -> None:
        """
        Sätt aktiv version.

        Args:
            version: Versionsnamn

        Raises:
            ValueError: Om versionen inte finns
        """
        if not self.version_exists(version):
            raise ValueError(f"Version '{version}' existerar inte")

        old_version = self._active_version_cache
        self._active_version_cache = version

        if self.config_manager:
            try:
                if hasattr(self.config_manager, "set"):
                    self.config_manager.set(ACTIVE_VERSION_KEY, version)
                elif isinstance(self.config_manager, dict):
                    self.config_manager[ACTIVE_VERSION_KEY] = version
            except Exception as exc:
                _log.warning(
                    "Kunde inte spara active_version till config: %s", exc
                )

        self._add_history(
            "set_active", version, {"old_version": old_version}
        )
        self._notify_change(
            "version_changed",
            {"old_version": old_version, "new_version": version},
        )
        _log.info(
            "Aktiv version satt: %s → %s", old_version, version
        )

    @property
    def backup_dir(self) -> Path:
        """Backup-katalog (skapas om den saknas)."""
        backup = self.specs_dir / BACKUP_DIR_NAME
        backup.mkdir(exist_ok=True)
        return backup

    @property
    def history_file(self) -> Path:
        """Sökväg till historik-JSON-fil."""
        return self.specs_dir / HISTORY_FILE_NAME

    # ──────────────────────────────────────────────────────────────────────
    # VERSION LISTING
    # ──────────────────────────────────────────────────────────────────────

    def list_versions(self) -> List[Any]:
        """
        Lista alla versioner sorterade efter katalognamn.

        Hoppar över dolda kataloger (.), backup-katalog och
        kataloger utan manifest.json.

        Returns:
            Lista med SpecVersion-objekt (kan vara tom)
        """
        SpecVersion = _get_SpecVersion()
        versions: List[Any] = []

        if not self.specs_dir.exists():
            return versions

        try:
            for version_dir in sorted(self.specs_dir.iterdir()):
                if not version_dir.is_dir():
                    continue
                if version_dir.name.startswith("."):
                    continue
                if version_dir.name in _SKIP_DIRS:
                    continue

                manifest_path = version_dir / "manifest.json"
                if not manifest_path.exists():
                    continue

                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    spec_version = SpecVersion.from_dict(data)
                    spec_version.is_active = (
                        spec_version.version == self.active_version
                    )
                    versions.append(spec_version)

                except Exception as exc:
                    _log.error(
                        "Kunde inte läsa manifest: %s: %s",
                        manifest_path, exc,
                    )

        except Exception as exc:
            _log.error("Kunde inte lista versioner: %s", exc, exc_info=True)

        return versions

    def list_backups(self) -> List[Dict[str, Any]]:
        """
        Lista tillgängliga backups i backup-katalogen.

        Returns:
            Lista med backup-metadata (namn, sökväg, storlek, datum)
        """
        backups: List[Dict[str, Any]] = []

        try:
            for item in sorted(self.backup_dir.iterdir()):
                try:
                    stat = item.stat()
                    backups.append({
                        "name": item.stem if item.is_file() else item.name,
                        "path": str(item),
                        "is_zip": item.suffix == ".zip",
                        "size_bytes": stat.st_size,
                        "created_at": datetime.fromtimestamp(
                            stat.st_mtime
                        ).isoformat(),
                    })
                except Exception:
                    pass
        except Exception:
            pass

        return backups

    def get_version_dir(self, version: str) -> Path:
        """
        Hämta katalog-sökväg för en version.

        Args:
            version: Versionsnamn

        Returns:
            Path till versions-katalogen
        """
        return self.specs_dir / version

    def version_exists(self, version: str) -> bool:
        """
        Kontrollera om version finns (manifest.json existerar).

        Args:
            version: Versionsnamn

        Returns:
            True om versionen finns
        """
        return (self.get_version_dir(version) / "manifest.json").exists()

    # ──────────────────────────────────────────────────────────────────────
    # LOADING / GET
    # ──────────────────────────────────────────────────────────────────────

    def load_version(
        self,
        version: str,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Ladda specifikationer för en version.

        Cachar resultatet i CACHE_TTL_SECONDS sekunder.
        Laddar alla PT*.json-filer i versions-katalogen.

        Args:
            version:   Versionsnamn
            use_cache: Använd cache om tillgänglig och ej utgången

        Returns:
            Dict med post_type (str) → PostSpec.
            Tom dict om versionen saknas eller fel uppstår.
        """
        if use_cache and version in self._cache:
            age = time.time() - self._cache_timestamps.get(version, 0)
            if age < CACHE_TTL_SECONDS:
                return self._cache[version]

        PostSpec = _get_PostSpec()
        version_dir = self.get_version_dir(version)

        if not version_dir.exists():
            _log.debug("Versions-katalog saknas: %s", version_dir)
            return {}

        specs: Dict[str, Any] = {}

        try:
            for spec_file in sorted(version_dir.glob("PT*.json")):
                try:
                    with open(spec_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    spec = PostSpec.from_dict(data)
                    specs[spec.post_type] = spec
                except Exception as exc:
                    _log.error(
                        "Kunde inte ladda spec: %s: %s",
                        spec_file, exc,
                    )

        except Exception as exc:
            _log.error(
                "Kunde inte ladda version '%s': %s",
                version, exc, exc_info=True,
            )

        if use_cache:
            self._cache[version] = specs
            self._cache_timestamps[version] = time.time()

        _log.debug(
            "Laddade version '%s': %d posttyper", version, len(specs)
        )
        return specs

    def get_spec(
        self,
        post_type: str,
        version: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Hämta specifikation för posttyp.

        Args:
            post_type: Posttypskod (t.ex. "28", "45", "99")
            version:   Versionsnamn (default: aktiv version)

        Returns:
            PostSpec eller None om ej hittad
        """
        target_version = version or self.active_version
        if not target_version:
            _log.warning("get_spec: ingen aktiv version")
            return None

        try:
            specs = self.load_version(target_version)
            result = specs.get(post_type)
            if result is None:
                _log.debug(
                    "PT%s ej hittad i version '%s'",
                    post_type, target_version,
                )
            return result
        except Exception as exc:
            _log.error(
                "Fel i get_spec(PT%s, %s): %s",
                post_type, target_version, exc, exc_info=True,
            )
            return None

    # ──────────────────────────────────────────────────────────────────────
    # CREATING / SAVING
    # ──────────────────────────────────────────────────────────────────────

    def create_version(
        self,
        version: str,
        specs: Union[List[Any], Dict[str, Any]],
        source_file: str = "",
        description: str = "",
        set_active: bool = True,
    ) -> None:
        """
        Skapa ny version med specifikationer.

        Använder atomisk skrivning via temp-katalog → rename.
        Skapar backup av befintlig version om den redan finns.

        Args:
            version:     Versionsnamn
            specs:       Lista med PostSpec eller Dict[post_type, PostSpec]
            source_file: Källfil (för metadata)
            description: Beskrivning (för metadata)
            set_active:  Om True, sätt som aktiv version

        Raises:
            Exception: Vidarekastar exception vid kritiska fel (temp rensas)
        """
        SpecVersion = _get_SpecVersion()

        if isinstance(specs, dict):
            specs_list = list(specs.values())
        else:
            specs_list = list(specs)

        version_dir = self.get_version_dir(version)
        temp_dir = version_dir.parent / f".{version}_temp"

        try:
            temp_dir.mkdir(parents=True, exist_ok=True)

            post_types: List[str] = []
            for spec in specs_list:
                spec.version = version
                spec_path = temp_dir / f"PT{spec.post_type}.json"
                _atomic_write_json(spec_path, spec.to_dict())
                post_types.append(spec.post_type)

            manifest = SpecVersion(
                version=version,
                created_at=datetime.now().isoformat(),
                source_file=source_file,
                post_types=sorted(post_types),
                description=description,
            )
            _atomic_write_json(
                temp_dir / "manifest.json",
                manifest.to_dict(),
            )

            # Backup av befintlig version
            backup_path = version_dir.parent / f".{version}_backup"
            if version_dir.exists():
                if backup_path.exists():
                    shutil.rmtree(backup_path)
                version_dir.rename(backup_path)

            # Atomisk flytt: temp → slutlig
            temp_dir.rename(version_dir)

            # Rensa backup
            if backup_path.exists():
                shutil.rmtree(backup_path)

            # Invalidera cache
            self._cache.pop(version, None)
            self._cache_timestamps.pop(version, None)

            # Sätt aktiv
            if set_active:
                self._active_version_cache = version
                if self.config_manager:
                    try:
                        if hasattr(self.config_manager, "set"):
                            self.config_manager.set(
                                ACTIVE_VERSION_KEY, version
                            )
                        elif isinstance(self.config_manager, dict):
                            self.config_manager[ACTIVE_VERSION_KEY] = version
                    except Exception as exc:
                        _log.warning(
                            "Kunde inte spara active_version: %s", exc
                        )

            self._add_history(
                "created",
                version,
                {
                    "post_types": post_types,
                    "source_file": source_file,
                    "set_active": set_active,
                },
            )
            self._notify_change(
                "version_created",
                {"version": version, "post_types": post_types},
            )
            _log.info(
                "Version '%s' skapad med %d posttyper",
                version, len(specs_list),
            )

        except Exception as exc:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            _log.error(
                "Fel vid skapande av version '%s': %s",
                version, exc, exc_info=True,
            )
            raise

    def save_spec(
        self,
        post_type: str,
        spec: Any,
        version: str,
    ) -> None:
        """
        Spara enskild specifikation till befintlig version.

        Uppdaterar manifest.json om post_type är ny.
        Invaliderar cache för versionen.

        Args:
            post_type: Posttypskod
            spec:      PostSpec att spara
            version:   Versionsnamn

        Raises:
            ValueError: Om versionen inte finns
        """
        version_dir = self.get_version_dir(version)
        if not version_dir.exists():
            raise ValueError(f"Version '{version}' existerar inte")

        spec_path = version_dir / f"PT{post_type}.json"
        _atomic_write_json(spec_path, spec.to_dict())

        # Uppdatera manifest om post_type är ny
        manifest_path = version_dir / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)

                if post_type not in manifest_data.get("post_types", []):
                    manifest_data["post_types"].append(post_type)
                    manifest_data["post_types"].sort()
                    _atomic_write_json(manifest_path, manifest_data)

            except Exception as exc:
                _log.warning(
                    "Kunde inte uppdatera manifest: %s", exc
                )

        self._cache.pop(version, None)
        self._cache_timestamps.pop(version, None)

        self._add_history(
            "spec_saved", version, {"post_type": post_type}
        )
        _log.debug("Sparade PT%s till version '%s'", post_type, version)

    # ──────────────────────────────────────────────────────────────────────
    # DELETION
    # ──────────────────────────────────────────────────────────────────────

    def delete_version(self, version: str) -> None:
        """
        Ta bort en version permanent.

        Kan ej ta bort aktiv version.

        Args:
            version: Versionsnamn

        Raises:
            ValueError: Om försök att ta bort aktiv version
        """
        if version == self.active_version:
            raise ValueError("Kan inte ta bort aktiv version")

        version_dir = self.get_version_dir(version)
        if version_dir.exists():
            shutil.rmtree(version_dir)

            self._cache.pop(version, None)
            self._cache_timestamps.pop(version, None)

            self._add_history("deleted", version, {})
            self._notify_change("version_deleted", {"version": version})
            _log.info("Version borttagen: %s", version)

    # ──────────────────────────────────────────────────────────────────────
    # COMPARISON
    # ──────────────────────────────────────────────────────────────────────

    def compare_versions(
        self,
        version1: str,
        version2: str,
    ) -> Dict[str, List[str]]:
        """
        Jämför två versioner och returnera diff per posttyp.

        Args:
            version1: Bas-version
            version2: Jämförelseversion

        Returns:
            Dict med post_type → lista med ändringstext.
            Endast posttyper med ändringar inkluderas.
        """
        specs1 = self.load_version(version1)
        specs2 = self.load_version(version2)

        all_types = set(specs1.keys()) | set(specs2.keys())
        changes: Dict[str, List[str]] = {}

        for pt in sorted(all_types):
            spec1 = specs1.get(pt)
            spec2 = specs2.get(pt)
            pt_changes: List[str] = []

            if spec1 is None:
                pt_changes.append("+ Ny posttyp")
            elif spec2 is None:
                pt_changes.append("- Borttagen")
            else:
                pt_changes.extend(self._compare_specs(spec1, spec2))

            if pt_changes:
                changes[pt] = pt_changes

        return changes

    def _compare_specs(self, spec1: Any, spec2: Any) -> List[str]:
        """
        Jämför två PostSpec och returnera lista med ändringstext.

        Kontrollerar: total_length, fältpositioner, fältlängder, typer.
        Nya/borttagna fält identifieras.

        Args:
            spec1: Bas-specifikation
            spec2: Jämförelsespecifikation

        Returns:
            Lista med ändringstext (tom = inga ändringar)
        """
        changes: List[str] = []

        if spec1.total_length != spec2.total_length:
            changes.append(
                f"Längd: {spec1.total_length} → {spec2.total_length}"
            )

        fields1 = {f.name: f for f in spec1.fields}
        fields2 = {f.name: f for f in spec2.fields}

        for name in sorted(set(fields2.keys()) - set(fields1.keys())):
            f = fields2[name]
            changes.append(
                f"+ {name} (pos {f.position}, len {f.length})"
            )

        for name in sorted(set(fields1.keys()) - set(fields2.keys())):
            changes.append(f"- {name}")

        for name in sorted(set(fields1.keys()) & set(fields2.keys())):
            f1, f2 = fields1[name], fields2[name]
            field_changes: List[str] = []

            if f1.position != f2.position:
                field_changes.append(
                    f"pos {f1.position}→{f2.position}"
                )
            if f1.length != f2.length:
                field_changes.append(
                    f"len {f1.length}→{f2.length}"
                )
            if f1.field_type != f2.field_type:
                field_changes.append(
                    f"typ {f1.field_type}→{f2.field_type}"
                )

            if field_changes:
                changes.append(f"~ {name}: {', '.join(field_changes)}")

        return changes

    # ──────────────────────────────────────────────────────────────────────
    # AVANCERADE FUNKTIONER 1–10
    # ──────────────────────────────────────────────────────────────────────

    def export_version_to_dir(
        self,
        version: str,
        output_dir: Path,
    ) -> Dict[str, Any]:
        """
        1. Exportera version till extern katalog.

        Kopierar alla *.json-filer från versions-katalogen.

        Args:
            version:    Versionsnamn att exportera
            output_dir: Målkatalog (skapas om den saknas)

        Returns:
            Dict med:
              success:        bool
              version:        str
              output_dir:     str
              files_exported: int
              errors:         List[str]
        """
        result: Dict[str, Any] = {
            "success": False,
            "version": version,
            "output_dir": str(output_dir),
            "files_exported": 0,
            "errors": [],
        }

        version_dir = self.get_version_dir(version)
        if not version_dir.exists():
            result["errors"].append(f"Version '{version}' hittades ej")
            return result

        try:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)

            for src_file in sorted(version_dir.glob("*.json")):
                dst_file = out / src_file.name
                shutil.copy2(src_file, dst_file)
                result["files_exported"] += 1

            self._add_history(
                "exported",
                version,
                {"output_dir": str(output_dir), "files": result["files_exported"]},
            )
            result["success"] = True
            _log.info(
                "Exporterade version '%s' till %s (%d filer)",
                version, output_dir, result["files_exported"],
            )

        except Exception as exc:
            result["errors"].append(str(exc))
            _log.error(
                "Export misslyckades för '%s': %s", version, exc, exc_info=True
            )

        return result

    def import_version_from_dir(
        self,
        input_dir: Path,
        version: Optional[str] = None,
        set_active: bool = False,
    ) -> Dict[str, Any]:
        """
        2. Importera version från extern katalog.

        Letar efter PT*.json-filer och skapar en ny version.
        Auto-genererar versionsnamn om inte angivet.

        Args:
            input_dir:  Källkatalog
            version:    Versionsnamn (auto om None)
            set_active: Sätt som aktiv version

        Returns:
            Dict med:
              success:        bool
              version:        str
              input_dir:      str
              specs_imported: int
              errors:         List[str]
        """
        PostSpec = _get_PostSpec()

        result: Dict[str, Any] = {
            "success": False,
            "version": version,
            "input_dir": str(input_dir),
            "specs_imported": 0,
            "errors": [],
        }

        src = Path(input_dir)
        if not src.exists():
            result["errors"].append(f"Katalog '{src}' hittades ej")
            return result

        try:
            specs: List[Any] = []

            for spec_file in sorted(src.glob("PT*.json")):
                try:
                    with open(spec_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    spec = PostSpec.from_dict(data)
                    specs.append(spec)
                except Exception as exc:
                    result["errors"].append(
                        f"Kunde inte ladda {spec_file.name}: {exc}"
                    )

            if not specs:
                result["errors"].append(
                    "Inga PT*.json-filer hittades i källkatalogen"
                )
                return result

            if not version:
                version = (
                    f"imported_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )

            result["version"] = version

            self.create_version(
                version=version,
                specs=specs,
                source_file=str(src),
                description=f"Importerad från {src.name}",
                set_active=set_active,
            )

            result["success"] = True
            result["specs_imported"] = len(specs)

            self._add_history(
                "imported",
                version,
                {"input_dir": str(src), "specs": len(specs)},
            )
            _log.info(
                "Importerade %d specs som version '%s'",
                len(specs), version,
            )

        except Exception as exc:
            result["errors"].append(str(exc))
            _log.error(
                "Import misslyckades från '%s': %s",
                input_dir, exc, exc_info=True,
            )

        return result

    def get_version_metadata(self, version: str) -> Dict[str, Any]:
        """
        3. Hämta detaljerad metadata för version.

        Inkluderar: manifest-data, is_active, filstorlek,
        antal fält, täckningsgrad, ålder i dagar.

        Args:
            version: Versionsnamn

        Returns:
            Dict med metadata. "found": False om ej hittad.
        """
        result: Dict[str, Any] = {
            "found": False,
            "version": version,
        }

        version_dir = self.get_version_dir(version)
        if not version_dir.exists():
            return result

        try:
            manifest_path = version_dir / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                result.update(manifest)

            result["found"] = True
            result["is_active"] = (version == self.active_version)

            # Filstatistik
            total_size = 0
            file_count = 0
            for json_file in version_dir.glob("*.json"):
                total_size += json_file.stat().st_size
                file_count += 1

            result["file_count"] = file_count
            result["total_size_bytes"] = total_size

            # Schemastatistik
            specs = self.load_version(version)
            result["schema_count"] = len(specs)

            total_fields = 0
            total_coverage = 0.0
            for spec in specs.values():
                total_fields += len(spec.fields)
                total_coverage += getattr(spec, "coverage", 0.0)

            result["total_fields"] = total_fields
            result["avg_coverage"] = (
                total_coverage / len(specs) if specs else 0.0
            )

            # Ålder
            try:
                created_str = result.get("created_at", "")
                if created_str:
                    created = datetime.fromisoformat(created_str)
                    result["age_days"] = (datetime.now() - created).days
                else:
                    result["age_days"] = -1
            except Exception:
                result["age_days"] = -1

        except Exception as exc:
            result["error"] = str(exc)
            _log.error(
                "Kunde inte hämta metadata för '%s': %s",
                version, exc, exc_info=True,
            )

        return result

    def rename_version(self, old_name: str, new_name: str) -> bool:
        """
        4. Byt namn på version.

        Uppdaterar manifest + alla spec-filer + byter katalognamn.
        Kan ej byta namn på aktiv version.

        Args:
            old_name: Nuvarande namn
            new_name: Nytt namn

        Returns:
            True om lyckades, False annars

        Raises:
            ValueError: Om old_name är aktiv version eller
                        om new_name redan finns
        """
        if old_name == self.active_version:
            raise ValueError("Kan inte byta namn på aktiv version")

        if self.version_exists(new_name):
            raise ValueError(f"Version '{new_name}' finns redan")

        old_dir = self.get_version_dir(old_name)
        new_dir = self.get_version_dir(new_name)

        if not old_dir.exists():
            raise ValueError(f"Version '{old_name}' hittades ej")

        try:
            # Uppdatera manifest
            manifest_path = old_dir / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                manifest["version"] = new_name
                _atomic_write_json(manifest_path, manifest)

            # Uppdatera alla spec-filer
            for spec_file in old_dir.glob("PT*.json"):
                with open(spec_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["version"] = new_name
                _atomic_write_json(spec_file, data)

            # Byt namn på katalog
            old_dir.rename(new_dir)

            # Uppdatera cache
            if old_name in self._cache:
                self._cache[new_name] = self._cache.pop(old_name)
            if old_name in self._cache_timestamps:
                self._cache_timestamps[new_name] = (
                    self._cache_timestamps.pop(old_name)
                )

            self._add_history(
                "renamed", new_name, {"old_name": old_name}
            )
            self._notify_change(
                "version_renamed",
                {"old_name": old_name, "new_name": new_name},
            )
            _log.info(
                "Version bytte namn: %s → %s", old_name, new_name
            )
            return True

        except Exception as exc:
            _log.error(
                "Namnbyte misslyckades: %s → %s: %s",
                old_name, new_name, exc, exc_info=True,
            )
            return False

    def duplicate_version(
        self,
        source_version: str,
        new_version: str,
    ) -> bool:
        """
        5. Duplicera version med nytt namn.

        Skapar en exakt kopia med nytt versionsnamn.
        Sätter EJ den nya versionen som aktiv.

        Args:
            source_version: Version att kopiera
            new_version:    Namn på kopian

        Returns:
            True om lyckades, False annars

        Raises:
            ValueError: Om new_version redan finns eller source saknas
        """
        if self.version_exists(new_version):
            raise ValueError(f"Version '{new_version}' finns redan")

        specs = self.load_version(source_version)
        if not specs:
            raise ValueError(
                f"Version '{source_version}' hittades ej eller är tom"
            )

        try:
            self.create_version(
                version=new_version,
                specs=list(specs.values()),
                source_file=f"duplicerat från {source_version}",
                description=f"Kopia av {source_version}",
                set_active=False,
            )
            self._add_history(
                "duplicated",
                new_version,
                {"source_version": source_version},
            )
            _log.info(
                "Duplicerade version: %s → %s",
                source_version, new_version,
            )
            return True

        except Exception as exc:
            _log.error(
                "Duplicering misslyckades: %s → %s: %s",
                source_version, new_version, exc, exc_info=True,
            )
            return False

    def get_all_post_types(self) -> Dict[str, List[str]]:
        """
        6. Lista alla posttyper över alla versioner.

        Returns:
            Dict med post_type (str) → lista med versioner där den finns.
            Sorterat alfabetiskt på posttyp.
        """
        result: Dict[str, List[str]] = {}

        for version_info in self.list_versions():
            try:
                specs = self.load_version(version_info.version)
                for post_type in specs.keys():
                    if post_type not in result:
                        result[post_type] = []
                    result[post_type].append(version_info.version)
            except Exception as exc:
                _log.warning(
                    "Kunde inte ladda version '%s' i get_all_post_types: %s",
                    version_info.version, exc,
                )

        return dict(sorted(result.items()))

    def find_spec_by_field(
        self,
        field_name: str,
        version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        7. Sök specifikationer som innehåller ett visst fältnamn.

        Case-insensitive substring-sökning på fältnamn.

        Args:
            field_name: Fältnamn eller del av fältnamn att söka efter
            version:    Specifik version (None = alla versioner)

        Returns:
            Lista med matchningar. Varje match är en dict med:
              version, post_type, field_name, position,
              length, type, required
        """
        results: List[Dict[str, Any]] = []
        pattern = field_name.upper()

        if version:
            versions_to_check = [version]
        else:
            versions_to_check = [
                v.version for v in self.list_versions()
            ]

        for ver in versions_to_check:
            try:
                specs = self.load_version(ver)
                for post_type, spec in specs.items():
                    for fld in spec.fields:
                        if pattern in fld.name.upper():
                            results.append({
                                "version": ver,
                                "post_type": post_type,
                                "field_name": fld.name,
                                "position": fld.position,
                                "length": fld.length,
                                "type": getattr(fld, "field_type", ""),
                                "required": getattr(fld, "mandatory", False),
                            })
            except Exception as exc:
                _log.warning(
                    "Fel vid sökning i version '%s': %s", ver, exc
                )

        return results

    def validate_version_integrity(
        self, version: str
    ) -> Dict[str, Any]:
        """
        8. Validera integritet för version.

        Kontrollerar:
          - manifest.json existerar
          - Alla deklarerade PT*.json-filer finns
          - Inga fält-överlapp
          - Inga fält utanför bounds
          - Checksumma (om tillgänglig)

        Args:
            version: Versionsnamn

        Returns:
            Dict med:
              valid:    bool
              version:  str
              errors:   List[str]
              warnings: List[str]
              stats:    Dict
        """
        result: Dict[str, Any] = {
            "valid": False,
            "version": version,
            "errors": [],
            "warnings": [],
            "stats": {},
        }

        version_dir = self.get_version_dir(version)
        if not version_dir.exists():
            result["errors"].append("Versions-katalog saknas")
            return result

        try:
            manifest_path = version_dir / "manifest.json"
            if not manifest_path.exists():
                result["errors"].append("manifest.json saknas")
            else:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                declared_types: set = set(
                    manifest.get("post_types", [])
                )
                for pt in declared_types:
                    spec_file = version_dir / f"PT{pt}.json"
                    if not spec_file.exists():
                        result["errors"].append(
                            f"Deklarerad PT{pt}.json saknas"
                        )

            specs = self.load_version(version)
            result["stats"]["schema_count"] = len(specs)

            total_fields = 0
            for post_type, spec in specs.items():
                total_fields += len(spec.fields)

                # Checksumma
                if hasattr(spec, "_calculate_checksum"):
                    calculated = spec._calculate_checksum()
                    stored = getattr(spec, "checksum", None)
                    if stored and stored != calculated:
                        result["warnings"].append(
                            f"PT{post_type}: checksumma stämmer ej"
                        )

                # Fält-överlapp
                positions: Dict[int, str] = {}
                for fld in spec.fields:
                    end = getattr(
                        fld, "end_position", fld.position + fld.length - 1
                    )
                    for pos in range(fld.position, end + 1):
                        if pos in positions:
                            result["errors"].append(
                                f"PT{post_type}: överlapp vid position "
                                f"{pos} ({positions[pos]} och {fld.name})"
                            )
                        else:
                            positions[pos] = fld.name

                # Fält utanför bounds
                for fld in spec.fields:
                    if fld.position < 1:
                        result["errors"].append(
                            f"PT{post_type}: {fld.name} ogiltig "
                            f"position ({fld.position})"
                        )
                    end = getattr(
                        fld, "end_position", fld.position + fld.length - 1
                    )
                    if end > spec.total_length:
                        result["errors"].append(
                            f"PT{post_type}: {fld.name} överskrider "
                            f"längd ({end} > {spec.total_length})"
                        )

            result["stats"]["total_fields"] = total_fields
            result["valid"] = len(result["errors"]) == 0

        except Exception as exc:
            result["errors"].append(str(exc))
            _log.error(
                "Validering misslyckades för '%s': %s",
                version, exc, exc_info=True,
            )

        return result

    def compact_version(self, version: str) -> Dict[str, Any]:
        """
        9. Komprimera/optimera version.

        Sorterar fält efter position och skriver med konsekvent
        JSON-formatering. Använder atomisk skrivning.

        Args:
            version: Versionsnamn

        Returns:
            Dict med:
              success:         bool
              version:         str
              files_compacted: int
              bytes_saved:     int
              error:           str (om misslyckades)
        """
        result: Dict[str, Any] = {
            "success": False,
            "version": version,
            "files_compacted": 0,
            "bytes_saved": 0,
        }

        version_dir = self.get_version_dir(version)
        if not version_dir.exists():
            result["error"] = "Version hittades ej"
            return result

        try:
            for json_file in sorted(version_dir.glob("*.json")):
                original_size = json_file.stat().st_size

                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Sortera fält efter position om det är en spec
                if "fields" in data:
                    data["fields"] = sorted(
                        data["fields"],
                        key=lambda fld: fld.get("position", 0),
                    )

                # Atomisk skrivning med sort_keys
                _atomic_write_json(json_file, data)

                new_size = json_file.stat().st_size
                result["bytes_saved"] += max(0, original_size - new_size)
                result["files_compacted"] += 1

            self._cache.pop(version, None)
            self._cache_timestamps.pop(version, None)

            self._add_history(
                "compacted",
                version,
                {
                    "files": result["files_compacted"],
                    "bytes_saved": result["bytes_saved"],
                },
            )
            result["success"] = True
            _log.info(
                "Komprimerade version '%s': %d filer, %d bytes sparade",
                version,
                result["files_compacted"],
                result["bytes_saved"],
            )

        except Exception as exc:
            result["error"] = str(exc)
            _log.error(
                "Komprimering misslyckades för '%s': %s",
                version, exc, exc_info=True,
            )

        return result

    def get_version_timeline(self) -> List[Dict[str, Any]]:
        """
        10. Tidslinje över versioner.

        Hämtar metadata för varje version och returnerar sorterad lista
        med nyaste versionen först.

        Returns:
            Lista med dicts (en per version):
              version, created_at, age_days, is_active,
              post_types, schema_count, total_fields,
              avg_coverage, source_file, description
        """
        timeline: List[Dict[str, Any]] = []

        for version_info in self.list_versions():
            try:
                metadata = self.get_version_metadata(version_info.version)
                timeline.append({
                    "version": version_info.version,
                    "created_at": version_info.created_at,
                    "age_days": metadata.get("age_days", -1),
                    "is_active": version_info.is_active,
                    "post_types": version_info.post_types,
                    "schema_count": len(version_info.post_types),
                    "total_fields": metadata.get("total_fields", 0),
                    "avg_coverage": metadata.get("avg_coverage", 0.0),
                    "source_file": version_info.source_file,
                    "description": getattr(version_info, "description", ""),
                })
            except Exception as exc:
                _log.warning(
                    "Kunde inte hämta metadata för '%s' i timeline: %s",
                    version_info.version, exc,
                )

        timeline.sort(
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )
        return timeline

    # ──────────────────────────────────────────────────────────────────────
    # HISTORY
    # ──────────────────────────────────────────────────────────────────────

    def _load_history(self) -> None:
        """
        Ladda historik från history.json.

        Kraschsäker – tom lista vid korrupt fil eller saknad fil.
        """
        if not self.history_file.exists():
            self._history = []
            return

        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                raw = json.load(f)

            if not isinstance(raw, list):
                _log.warning("history.json har ogiltigt format – återställer")
                self._history = []
                return

            self._history = [
                VersionHistoryEntry.from_dict(e)
                for e in raw
                if isinstance(e, dict)
            ]
            _log.debug(
                "Laddade %d historikposter", len(self._history)
            )

        except Exception as exc:
            _log.warning(
                "Kunde inte ladda historik: %s", exc
            )
            self._history = []

    def _save_history(self) -> None:
        """
        Spara historik till history.json (atomisk, max MAX_HISTORY_ENTRIES).

        Kraschsäker – loggar fel men kraschar ej.
        """
        try:
            entries = self._history[-MAX_HISTORY_ENTRIES:]
            data = [e.to_dict() for e in entries]
            _atomic_write_json(self.history_file, data)
        except Exception as exc:
            _log.warning("Kunde inte spara historik: %s", exc)

    def _add_history(
        self,
        action: str,
        version: str,
        details: Dict[str, Any],
    ) -> None:
        """
        Lägg till historikpost och spara.

        Args:
            action:  Åtgärdstext
            version: Berörd version
            details: Extra metadata
        """
        entry = VersionHistoryEntry(
            timestamp=datetime.now().isoformat(),
            action=action,
            version=version,
            details=details,
        )
        self._history.append(entry)
        self._save_history()

    def get_history(
        self,
        post_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Hämta historikposter (nyaste först).

        Args:
            post_type: Filtrera på posttyp (None = alla)
            limit:     Max antal poster att returnera

        Returns:
            Lista med historikposter som dicts (nyaste först)
        """
        history = self._history[-limit:]

        if post_type:
            history = [
                e for e in history
                if post_type in e.details.get("post_types", [])
                or e.details.get("post_type") == post_type
            ]

        return [e.to_dict() for e in reversed(history)]

    # ──────────────────────────────────────────────────────────────────────
    # CALLBACKS
    # ──────────────────────────────────────────────────────────────────────

    def subscribe(
        self,
        callback: Callable[[str, Dict[str, Any]], None],
    ) -> None:
        """
        Prenumerera på versionsändringar.

        Callback anropas med (event_type: str, data: dict).

        Args:
            callback: Funktion att anropa vid ändringar
        """
        if callback not in self._change_callbacks:
            self._change_callbacks.append(callback)
            _log.debug("Callback registrerad: %s", callback)

    def unsubscribe(
        self,
        callback: Callable[[str, Dict[str, Any]], None],
    ) -> None:
        """
        Avregistrera callback.

        Args:
            callback: Funktion att ta bort
        """
        if callback in self._change_callbacks:
            self._change_callbacks.remove(callback)
            _log.debug("Callback avregistrerad: %s", callback)

    def _notify_change(
        self,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """
        Notifiera alla prenumeranter om en ändring.

        Kraschsäker – loggar fel per callback utan att avbryta.

        Args:
            event_type: Typ av händelse
            data:       Händelsedata
        """
        for callback in list(self._change_callbacks):
            try:
                callback(event_type, data)
            except Exception as exc:
                _log.warning(
                    "Callback misslyckades (%s): %s", callback, exc
                )

    # ──────────────────────────────────────────────────────────────────────
    # UTILITIES
    # ──────────────────────────────────────────────────────────────────────

    def clear_cache(self, version: Optional[str] = None) -> None:
        """
        Rensa cache.

        Args:
            version: Specifik version (None = rensa alla)
        """
        if version:
            self._cache.pop(version, None)
            self._cache_timestamps.pop(version, None)
            _log.debug("Cache rensad för version: %s", version)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
            self._active_version_cache = None
            _log.debug("All cache rensad")

    def get_stats(self) -> Dict[str, Any]:
        """
        Hämta övergripande statistik.

        Returns:
            Dict med:
              version_count, active_version, versions,
              cached_versions, backup_count, total_specs,
              history_entries, specs_dir, copyright
        """
        versions = self.list_versions()

        total_specs = sum(len(v.post_types) for v in versions)

        return {
            "version_count": len(versions),
            "active_version": self.active_version,
            "versions": [v.version for v in versions],
            "cached_versions": list(self._cache.keys()),
            "backup_count": len(self.list_backups()),
            "total_specs": total_specs,
            "history_entries": len(self._history),
            "specs_dir": str(self.specs_dir),
            "copyright": get_copyright_string(),
        }

    def __repr__(self) -> str:
        return (
            f"<SpecVersionManager "
            f"dir={self.specs_dir} "
            f"versions={len(self.list_versions())} "
            f"active={self.active_version}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "SpecVersionManager",
    "VersionHistoryEntry",
    "VERSION",
    "AUTHOR",
    "TS_POST_LENGTH",
    "TS_ENCODING",
    "ACTIVE_VERSION_KEY",
    "BACKUP_DIR_NAME",
    "HISTORY_FILE_NAME",
    "MAX_HISTORY_ENTRIES",
    "CACHE_TTL_SECONDS",
    "get_copyright_string",
]
