# -*- coding: utf-8 -*-
# core/cache_manager.py
"""
CacheManager v1.0.0 — Smart cache-rensning (spec v7.1).

Transportstyrelsen Fordonsregistreringssystem.

ANSVAR:
    - Rensa cache i PROD mode vid exit:
        * cache/-katalogen (registrerade cache-kataloger)
        * ALLA __pycache__-kataloger rekursivt (SMART CACHE v7.1)
        * Lösa .pyc/.pyo-filer utanför __pycache__
    - DEV mode: cache BEHÅLLS (snabb iteration)
    - smart_cache-flagga i settings.json:
        * true  = smart läge enligt mode (dev=behåll, prod=rensa)
        * false = TVINGAD PROD-cleanup oavsett mode
    - RENSA ALDRIG: user data, settings, plugin data, logs
      (skyddade kataloger hoppas ALLTID över, se PROTECTED_DIRS)
    - cleanup FÅR ALDRIG krascha appen — varje borttagning körs
      i egen try/except, fel loggas till plugins.log/errors.log

SPEC v7.1 — GLOBAL CACHE POLICY:
    RENSA vid exit (PROD): cache-filer, runtime cache,
      temp-artefakter (__pycache__, .pyc, .pyo)
    RENSA ALDRIG: user data, settings, plugin data, logs
    Skyddade: data/, logs/, ut/, sap/, In/, .git/, settings.json
    Rekursiv skanning av: core/, ui/, plugins/, tests/ + roten

API (spec Sektion D v7.1):
    CacheManager.cleanup()              -> None
    CacheManager.should_cleanup()       -> bool
    CacheManager.register_cache_dir(p)  -> None
    CacheManager.find_pycache_dirs(r)   -> List[Path]   (NY v7.1)
    CacheManager.purge_pycache(r)       -> int          (NY v7.1)

ANVÄNDNING (main.pyw, vid exit):
    from core.cache_manager import CacheManager

    cm = CacheManager(base_dir=Path("."), settings=settings_manager)
    cm.register_cache_dir(Path("cache"))
    ...
    # Vid shutdown:
    if cm.should_cleanup():
        cm.cleanup()

    # Eller koppla automatiskt:
    cm.install_exit_hook()   # atexit-registrering

KRASCHSÄKERHET:
    - Varje rmtree/unlink i egen try/except
    - Symlänkar följs ALDRIG (skydd mot att radera utanför roten)
    - Sökvägar verifieras ligga under base_dir innan borttagning
    - Statistik returneras via get_last_stats()

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Set

_log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "1.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"

# Katalognamn som ALDRIG får rensas eller traverseras
# (spec: user data, settings, plugin data, logs + känsliga)
PROTECTED_DIRS: Final[Set[str]] = {
    "data",
    "logs",
    "ut",
    "sap",
    "In",
    ".git",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    "node_modules",
}

# Filer som ALDRIG får röras
PROTECTED_FILES: Final[Set[str]] = {
    "settings.json",
}

# Kataloger som skannas rekursivt efter __pycache__ (+ roten själv)
SCAN_ROOTS: Final[List[str]] = [
    "core",
    "ui",
    "plugins",
    "tests",
]

PYCACHE_NAME: Final[str] = "__pycache__"
PYC_SUFFIXES: Final[Set[str]] = {".pyc", ".pyo"}

DEFAULT_CACHE_DIRNAME: Final[str] = "cache"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# CACHE MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class CacheManager:
    """
    Smart cache-rensning enligt spec v7.1.

    Lägen (mode + smart_cache från settings.json):
      mode=dev,  smart_cache=true   -> INGEN rensning (behåll allt)
      mode=prod, smart_cache=true   -> full rensning vid exit
      smart_cache=false             -> TVINGAD rensning (som prod)

    Trådsäker. Kraschsäker — cleanup() kastar ALDRIG.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        settings: Optional[Any] = None,
        *,
        mode: Optional[str] = None,
        smart_cache: Optional[bool] = None,
    ) -> None:
        """
        Initiera CacheManager.

        Args:
            base_dir: Projektrot (None = aktuell katalog).
                      ALL rensning sker ENDAST under denna.
            settings: SettingsManager-instans (läser mode +
                      smart_cache därifrån om given)
            mode: Explicit "dev"/"prod" (överstyr settings)
            smart_cache: Explicit flagga (överstyr settings)
        """
        self._base_dir = Path(base_dir or ".").resolve()
        self._settings = settings
        self._mode_override = mode
        self._smart_override = smart_cache

        self._lock = threading.RLock()
        self._cache_dirs: List[Path] = []
        self._exit_hook_installed = False

        self._last_stats: Dict[str, Any] = {
            "ran": False,
            "timestamp": None,
            "cache_dirs_cleaned": 0,
            "pycache_removed": 0,
            "pyc_files_removed": 0,
            "errors": 0,
            "skipped_protected": 0,
        }

        # Registrera standard-cachekatalogen (cache/)
        default_cache = self._base_dir / DEFAULT_CACHE_DIRNAME
        self._cache_dirs.append(default_cache)

        _log.debug(
            "CacheManager v%s initierad (base=%s)",
            VERSION, self._base_dir,
        )

    # ──────────────────────────────────────────────────────────────────
    # PUBLIKT API (spec-kontrakt)
    # ──────────────────────────────────────────────────────────────────

    def should_cleanup(self) -> bool:
        """
        Avgör om cleanup ska köras enligt smart cache-policyn.

        Returns:
            True  = rensa (prod, eller smart_cache=false tvingar)
            False = behåll (dev med smart_cache=true)
        """
        try:
            smart = self._get_smart_cache()
            if smart is False:
                # smart_cache=false -> TVINGAD PROD-cleanup (spec)
                return True
            mode = self._get_mode()
            return mode == "prod"
        except Exception as exc:
            _log.debug("should_cleanup-fel: %s — default prod", exc)
            return True

    def cleanup(self) -> None:
        """
        Kör full cache-rensning. KRASCHAR ALDRIG.

        Rensar (endast under base_dir):
          1. Alla registrerade cache-kataloger (innehållet)
          2. Alla __pycache__-kataloger rekursivt (spec v7.1)
          3. Lösa .pyc/.pyo-filer utanför __pycache__

        Hoppar ALLTID över PROTECTED_DIRS/PROTECTED_FILES.
        """
        with self._lock:
            stats = {
                "ran": True,
                "timestamp": datetime.now().isoformat(
                    timespec="seconds"
                ),
                "cache_dirs_cleaned": 0,
                "pycache_removed": 0,
                "pyc_files_removed": 0,
                "errors": 0,
                "skipped_protected": 0,
            }

            _log.info(
                "Cache-rensning startar (mode=%s, smart_cache=%s)",
                self._get_mode(), self._get_smart_cache(),
            )

            # 1. Registrerade cache-kataloger
            for cache_dir in list(self._cache_dirs):
                try:
                    if self._clean_cache_dir(cache_dir):
                        stats["cache_dirs_cleaned"] += 1
                except Exception as exc:
                    stats["errors"] += 1
                    _log.error(
                        "Fel vid rensning av cache-katalog %s: %s",
                        cache_dir, exc,
                    )

            # 2. __pycache__ rekursivt (SMART CACHE v7.1)
            try:
                removed = self.purge_pycache(self._base_dir)
                stats["pycache_removed"] = removed
            except Exception as exc:
                stats["errors"] += 1
                _log.error("purge_pycache-fel: %s", exc)

            # 3. Lösa .pyc/.pyo-filer
            try:
                pyc_removed = self._purge_loose_pyc(self._base_dir)
                stats["pyc_files_removed"] = pyc_removed
            except Exception as exc:
                stats["errors"] += 1
                _log.error("Lös .pyc-rensning fel: %s", exc)

            self._last_stats = stats
            _log.info(
                "Cache-rensning klar: %d cache-dir, "
                "%d __pycache__, %d .pyc, %d fel",
                stats["cache_dirs_cleaned"],
                stats["pycache_removed"],
                stats["pyc_files_removed"],
                stats["errors"],
            )

    def register_cache_dir(self, path: Path) -> None:
        """
        Registrera en cache-katalog för rensning i PROD.

        Args:
            path: Katalog (relativ tolkas mot base_dir)
        """
        try:
            p = Path(path)
            if not p.is_absolute():
                p = self._base_dir / p
            p = p.resolve()

            if not self._is_under_base(p):
                _log.warning(
                    "Vägrar registrera cache-katalog utanför "
                    "base_dir: %s",
                    p,
                )
                return
            if p.name in PROTECTED_DIRS:
                _log.warning(
                    "Vägrar registrera skyddad katalog som "
                    "cache: %s",
                    p,
                )
                return

            with self._lock:
                if p not in self._cache_dirs:
                    self._cache_dirs.append(p)
                    _log.debug(
                        "Cache-katalog registrerad: %s", p,
                    )
        except Exception as exc:
            _log.error(
                "register_cache_dir misslyckades: %s", exc,
            )

    # ──────────────────────────────────────────────────────────────────
    # SMART CACHE v7.1 — __pycache__-HANTERING
    # ──────────────────────────────────────────────────────────────────

    def find_pycache_dirs(
        self, root: Optional[Path] = None
    ) -> List[Path]:
        """
        Rekursiv sökning efter __pycache__-kataloger (NY v7.1).

        Skannar roten + SCAN_ROOTS (core/, ui/, plugins/, tests/).
        Exkluderar PROTECTED_DIRS. Följer ALDRIG symlänkar.

        Args:
            root: Startkatalog (None = base_dir)

        Returns:
            Lista med hittade __pycache__-sökvägar
        """
        root = Path(root or self._base_dir).resolve()
        found: List[Path] = []

        if not self._is_under_base(root) and root != self._base_dir:
            _log.warning(
                "find_pycache_dirs: root utanför base_dir: %s",
                root,
            )
            return found

        try:
            for current, dirnames, _filenames in os.walk(
                root, topdown=True, followlinks=False
            ):
                current_path = Path(current)

                # Beskär trädet: hoppa skyddade kataloger
                kept = []
                for d in dirnames:
                    if d in PROTECTED_DIRS:
                        self._last_stats["skipped_protected"] = (
                            self._last_stats.get(
                                "skipped_protected", 0
                            ) + 1
                        )
                        continue
                    if d == PYCACHE_NAME:
                        found.append(current_path / d)
                        continue  # gå inte NER i __pycache__
                    kept.append(d)
                dirnames[:] = kept
        except Exception as exc:
            _log.error("find_pycache_dirs-fel: %s", exc)

        return found

    def purge_pycache(self, root: Optional[Path] = None) -> int:
        """
        Ta bort alla __pycache__-kataloger rekursivt (NY v7.1).

        Varje rmtree körs i egen try/except och loggas per mapp.
        KRASCHAR ALDRIG.

        Args:
            root: Startkatalog (None = base_dir)

        Returns:
            Antal borttagna __pycache__-kataloger
        """
        removed = 0
        for pycache in self.find_pycache_dirs(root):
            try:
                if not self._is_under_base(pycache):
                    _log.warning(
                        "Hoppar __pycache__ utanför base_dir: %s",
                        pycache,
                    )
                    continue
                if pycache.is_symlink():
                    _log.warning(
                        "Hoppar symlänkad __pycache__: %s", pycache,
                    )
                    continue
                shutil.rmtree(pycache, ignore_errors=False)
                removed += 1
                _log.debug("Borttagen: %s", pycache)
            except Exception as exc:
                self._last_stats["errors"] = (
                    self._last_stats.get("errors", 0) + 1
                )
                _log.warning(
                    "Kunde inte ta bort %s: %s", pycache, exc,
                )
        if removed:
            _log.info(
                "purge_pycache: %d __pycache__-kataloger "
                "borttagna",
                removed,
            )
        return removed

    # ──────────────────────────────────────────────────────────────────
    # EXIT-HOOK & DIAGNOSTIK
    # ──────────────────────────────────────────────────────────────────

    def install_exit_hook(self) -> None:
        """
        Registrera automatisk cleanup vid exit (atexit).
        Kör endast om should_cleanup() är True vid exit-tillfället.
        Idempotent.
        """
        if self._exit_hook_installed:
            return
        self._exit_hook_installed = True

        def _exit_cleanup() -> None:
            try:
                if self.should_cleanup():
                    self.cleanup()
                else:
                    _log.debug(
                        "DEV mode — cache behålls vid exit"
                    )
            except Exception:
                # cleanup FÅR ALDRIG krascha appen (spec)
                _log.exception("Exit-cleanup misslyckades")

        atexit.register(_exit_cleanup)
        _log.debug("Cache exit-hook installerad")

    def get_last_stats(self) -> Dict[str, Any]:
        """Returnera statistik från senaste cleanup-körningen."""
        with self._lock:
            return dict(self._last_stats)

    def get_registered_dirs(self) -> List[Path]:
        """Returnera registrerade cache-kataloger."""
        with self._lock:
            return list(self._cache_dirs)

    # ──────────────────────────────────────────────────────────────────
    # INTERNT
    # ──────────────────────────────────────────────────────────────────

    def _get_mode(self) -> str:
        """Läs mode (dev/prod) från override/settings/default."""
        if self._mode_override is not None:
            return str(self._mode_override).lower()
        if self._settings is not None:
            try:
                getter = getattr(self._settings, "get", None)
                if callable(getter):
                    return str(
                        getter("mode", "prod") or "prod"
                    ).lower()
            except Exception:
                pass
        return "prod"

    def _get_smart_cache(self) -> bool:
        """Läs smart_cache från override/settings/default."""
        if self._smart_override is not None:
            return bool(self._smart_override)
        if self._settings is not None:
            try:
                getter = getattr(self._settings, "get", None)
                if callable(getter):
                    value = getter("smart_cache", True)
                    return bool(
                        True if value is None else value
                    )
            except Exception:
                pass
        return True

    def _is_under_base(self, path: Path) -> bool:
        """True om path ligger under base_dir (säkerhetsspärr)."""
        try:
            path.resolve().relative_to(self._base_dir)
            return True
        except (ValueError, OSError):
            return False

    def _clean_cache_dir(self, cache_dir: Path) -> bool:
        """
        Töm en cache-katalog (innehållet, inte katalogen själv).
        Varje post i egen try/except. KRASCHAR ALDRIG.

        Returns:
            True om katalogen fanns och bearbetades
        """
        try:
            cache_dir = cache_dir.resolve()
        except Exception:
            return False

        if not cache_dir.exists() or not cache_dir.is_dir():
            return False
        if not self._is_under_base(cache_dir):
            _log.warning(
                "Hoppar cache-katalog utanför base_dir: %s",
                cache_dir,
            )
            return False
        if cache_dir.name in PROTECTED_DIRS:
            _log.warning(
                "Hoppar skyddad katalog: %s", cache_dir,
            )
            return False

        cleaned_any = False
        try:
            for entry in cache_dir.iterdir():
                try:
                    if entry.name in PROTECTED_FILES:
                        continue
                    if entry.is_symlink():
                        entry.unlink(missing_ok=True)
                    elif entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=False)
                    else:
                        entry.unlink(missing_ok=True)
                    cleaned_any = True
                except Exception as exc:
                    self._last_stats["errors"] = (
                        self._last_stats.get("errors", 0) + 1
                    )
                    _log.warning(
                        "Kunde inte rensa %s: %s", entry, exc,
                    )
        except Exception as exc:
            _log.warning(
                "Kunde inte lista %s: %s", cache_dir, exc,
            )
            return False

        if cleaned_any:
            _log.debug("Cache-katalog tömd: %s", cache_dir)
        return True

    def _purge_loose_pyc(self, root: Path) -> int:
        """
        Ta bort lösa .pyc/.pyo-filer UTANFÖR __pycache__
        (legacy-artefakter). Skyddade kataloger hoppas över.
        Följer aldrig symlänkar. KRASCHAR ALDRIG.

        Returns:
            Antal borttagna filer
        """
        removed = 0
        try:
            for current, dirnames, filenames in os.walk(
                root, topdown=True, followlinks=False
            ):
                # Beskär: skyddade + __pycache__ (redan hanterad)
                dirnames[:] = [
                    d for d in dirnames
                    if d not in PROTECTED_DIRS
                    and d != PYCACHE_NAME
                ]
                current_path = Path(current)
                for fname in filenames:
                    if Path(fname).suffix.lower() in PYC_SUFFIXES:
                        target = current_path / fname
                        try:
                            if not self._is_under_base(target):
                                continue
                            target.unlink(missing_ok=True)
                            removed += 1
                        except Exception as exc:
                            self._last_stats["errors"] = (
                                self._last_stats.get(
                                    "errors", 0
                                ) + 1
                            )
                            _log.warning(
                                "Kunde inte ta bort %s: %s",
                                target, exc,
                            )
        except Exception as exc:
            _log.error("_purge_loose_pyc-fel: %s", exc)
        if removed:
            _log.info(
                "Lösa .pyc/.pyo borttagna: %d", removed,
            )
        return removed

    def __repr__(self) -> str:
        return (
            f"<CacheManager v{VERSION} "
            f"base={self._base_dir} "
            f"mode={self._get_mode()} "
            f"smart={self._get_smart_cache()} "
            f"dirs={len(self._cache_dirs)}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "CacheManager",
    "PROTECTED_DIRS",
    "PROTECTED_FILES",
    "SCAN_ROOTS",
    "PYCACHE_NAME",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]