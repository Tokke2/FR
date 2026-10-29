# -*- coding: utf-8 -*-
# Fil: plugins/dealers_manager/password_manager.py
# Copyright © 2025 Rickard Längkvist
"""
Lösenordshantering för återförsäljare-redigering.

ANSVAR:
  - SHA-256 hashning av lösenord med salt
  - Ladda/spara lösenordskonfiguration till JSON (atomiskt)
  - Verifiera lösenord
  - Byta lösenord med validering
  - Lazy-loading av konfiguration (cachas efter första läsning)

IMPORTER:
  hashlib, logging, os, tempfile, json
  datetime (datetime)
  pathlib (Path)
  typing (Dict, Optional, Tuple)

EXPORTERAR:
  DealersPasswordManager   - huvudklass
  DEFAULT_SALT             - standard-salt (str)
  DEFAULT_PASSWORD         - klartextlösenord för default (str)

ANVÄNDS AV:
  plugins/dealers_manager/plugin.py
    → Plugin.__init__()
    → Plugin.password_manager (property)
    → DealersWidget._change_password()

NOTERA:
  - Använder INTE json_helper (extern dependency borttagen)
  - Atomisk filskrivning via _atomic_write_text()
  - Ingen self.logger – använder module-level _log
  - DEFAULT_PASSWORD är "admin" (ej "password")
  - Salt är per-installation konstant (ändras ej vid lösenordsbyte)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Final, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL LOGGER
# ──────────────────────────────────────────────────────────────────────────────

_log: logging.Logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

# Salt är per-installation konstant – ändras aldrig efter skapande
DEFAULT_SALT: Final[str] = "dealers_manager_salt_2025"

# Klartextlösenord för default (visas i dokumentation, ej i kod i övrigt)
DEFAULT_PASSWORD: Final[str] = "admin"

# Minsta tillåtna lösenordslängd
_MIN_PASSWORD_LENGTH: Final[int] = 4

# Konfigurationsschema-version
_CONFIG_VERSION: Final[str] = "1.1"


# ══════════════════════════════════════════════════════════════════════════════
# ATOMISK FILSKRIVNING (lokal kopia – undviker cirkulär import från plugin.py)
# ══════════════════════════════════════════════════════════════════════════════

def _atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    Atomisk filskrivning: skriv till .tmp → fsync → rename → slutlig fil.

    Förhindrar korrupta filer vid krasch under skrivning.

    Args:
        path:     Slutlig sökväg
        content:  Textinnehåll att skriva
        encoding: Teckenkodning (default utf-8)

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
        with os.fdopen(tmp_fd, "w", encoding=encoding) as f:
            f.write(content)
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
# PASSWORD MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class DealersPasswordManager:
    """
    Lösenordshanterare för återförsäljare-plugin.

    Lagrar SHA-256(lösenord + salt) i JSON-fil.
    Konfigurationen cachas i minnet efter första läsning (lazy loading).
    Default-lösenord: "admin"

    PUBLIKA METODER:
      verify(password)              -> bool
      change(old, new)              -> Tuple[bool, str]
      reset_to_default()            -> bool
      get_last_changed()            -> Optional[str]

    INTERNA METODER:
      _load_config()                -> Dict
      _save_config(config)          -> bool
      _hash_password(pw, salt)      -> str
      _build_default_config()       -> Dict
    """

    def __init__(self, password_file: Path) -> None:
        """
        Initiera lösenordshanteraren.

        Args:
            password_file: Sökväg till JSON-fil för lösenordskonfiguration.
                           Skapas med default-lösenord om den inte finns.
        """
        self._file: Path = password_file
        self._config: Optional[Dict[str, str]] = None
        _log.debug("DealersPasswordManager initierad: %s", self._file)

    # ──────────────────────────────────────────────────────────────────────
    # PUBLIKA METODER
    # ──────────────────────────────────────────────────────────────────────

    def verify(self, password: str) -> bool:
        """
        Verifiera om lösenord är korrekt.

        Args:
            password: Klartextlösenord att verifiera

        Returns:
            True om korrekt, False annars
        """
        try:
            config = self._load_config()
            stored_hash = config.get("password_hash", "")
            salt = config.get("salt", DEFAULT_SALT)

            if not stored_hash:
                _log.warning("Ingen lösenordshash i konfiguration")
                return False

            result = self._hash_password(password, salt) == stored_hash
            if not result:
                _log.debug("Felaktigt lösenord angett")
            return result

        except Exception as exc:
            _log.error("Fel i verify(): %s", exc, exc_info=True)
            return False

    def change(self, old_password: str, new_password: str) -> Tuple[bool, str]:
        """
        Byt lösenord.

        Validering:
          - Nuvarande lösenord måste vara korrekt
          - Nytt lösenord måste vara minst {_MIN_PASSWORD_LENGTH} tecken
          - Nytt lösenord får inte vara tomt

        Args:
            old_password: Nuvarande klartextlösenord
            new_password: Nytt klartextlösenord

        Returns:
            Tuple (success: bool, message: str)
            - (True, "Lösenord ändrat") vid framgång
            - (False, felanledning) vid misslyckande
        """
        try:
            if not self.verify(old_password):
                _log.warning("Felaktigt nuvarande lösenord vid byte")
                return False, "Felaktigt nuvarande lösenord"

            if not new_password:
                return False, "Nytt lösenord får inte vara tomt"

            if len(new_password) < _MIN_PASSWORD_LENGTH:
                return (
                    False,
                    f"Nytt lösenord måste vara minst "
                    f"{_MIN_PASSWORD_LENGTH} tecken",
                )

            config = self._load_config()
            salt = config.get("salt", DEFAULT_SALT)
            config["password_hash"] = self._hash_password(new_password, salt)
            config["updated_at"] = datetime.now().isoformat()

            if self._save_config(config):
                _log.info("Lösenord bytt för Dealers Manager")
                return True, "Lösenord ändrat"

            return False, "Kunde inte spara nytt lösenord"

        except Exception as exc:
            _log.error("Fel i change(): %s", exc, exc_info=True)
            return False, f"Oväntat fel: {exc}"

    def reset_to_default(self) -> bool:
        """
        Återställ lösenord till default ("admin").

        Används vid återställning om lösenord glömts.

        Returns:
            True vid framgång, False vid fel
        """
        try:
            config = self._load_config()
            salt = config.get("salt", DEFAULT_SALT)
            config["password_hash"] = self._hash_password(DEFAULT_PASSWORD, salt)
            config["updated_at"] = datetime.now().isoformat()
            config["reset_at"] = datetime.now().isoformat()

            if self._save_config(config):
                _log.info("Lösenord återställt till default för Dealers Manager")
                return True
            return False

        except Exception as exc:
            _log.error("Fel i reset_to_default(): %s", exc, exc_info=True)
            return False

    def get_last_changed(self) -> Optional[str]:
        """
        Hämta tidsstämpel för senaste lösenordsbyte.

        Returns:
            ISO-formaterad tidsstämpel, eller None om okänd
        """
        try:
            config = self._load_config()
            return config.get("updated_at")
        except Exception as exc:
            _log.error("Fel i get_last_changed(): %s", exc, exc_info=True)
            return None

    # ──────────────────────────────────────────────────────────────────────
    # INTERNA METODER
    # ──────────────────────────────────────────────────────────────────────

    def _build_default_config(self) -> Dict[str, str]:
        """
        Bygg default-konfiguration med admin-lösenord.

        Returns:
            Dict med password_hash, salt, timestamps och version
        """
        now = datetime.now().isoformat()
        return {
            "password_hash": self._hash_password(DEFAULT_PASSWORD, DEFAULT_SALT),
            "salt": DEFAULT_SALT,
            "created_at": now,
            "updated_at": now,
            "version": _CONFIG_VERSION,
        }

    def _load_config(self) -> Dict[str, str]:
        """
        Ladda konfiguration från JSON-fil (lazy, cachas efter första läsning).

        Skapar default-konfiguration om filen saknas eller är korrupt.

        Returns:
            Dict med lösenordskonfiguration (aldrig None)
        """
        # Returnera cachad konfiguration om tillgänglig
        if self._config is not None:
            return self._config

        default = self._build_default_config()

        if not self._file.exists():
            _log.info(
                "Lösenordsfil saknas – skapar med default-lösenord ('%s'): %s",
                DEFAULT_PASSWORD,
                self._file,
            )
            self._save_config(default)
            self._config = default
            return default

        try:
            raw = self._file.read_text(encoding="utf-8")
            loaded = json.loads(raw)

            if not isinstance(loaded, dict):
                _log.warning(
                    "Ogiltigt format i lösenordsfil – återställer default"
                )
                self._save_config(default)
                self._config = default
                return default

            # Säkerställ att alla nycklar finns (migration)
            for key, val in default.items():
                if key not in loaded:
                    loaded[key] = val
                    _log.debug("Migration: lade till nyckel '%s'", key)

            self._config = loaded
            _log.debug("Lösenordskonfiguration laddad: %s", self._file)
            return self._config

        except json.JSONDecodeError as exc:
            _log.error(
                "Korrupt lösenordsfil (%s) – återställer default: %s",
                self._file, exc,
            )
            self._save_config(default)
            self._config = default
            return default

        except Exception as exc:
            _log.error(
                "Fel vid läsning av lösenordsfil: %s", exc, exc_info=True
            )
            self._config = default
            return default

    def _save_config(self, config: Dict[str, str]) -> bool:
        """
        Spara konfiguration atomiskt till JSON-fil.

        Args:
            config: Konfigurationsdict att spara

        Returns:
            True vid framgång, False vid fel
        """
        try:
            content = json.dumps(
                config,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            _atomic_write_text(self._file, content)
            self._config = config
            _log.debug("Lösenordskonfiguration sparad: %s", self._file)
            return True

        except Exception as exc:
            _log.error(
                "Fel vid sparande av lösenordskonfiguration: %s",
                exc, exc_info=True,
            )
            return False

    def _hash_password(self, password: str, salt: str) -> str:
        """
        Beräkna SHA-256 hash av lösenord + salt.

        Args:
            password: Klartextlösenord
            salt:     Salt-sträng

        Returns:
            Hex-digest av SHA-256(password + salt)
        """
        return hashlib.sha256(
            (password + salt).encode("utf-8")
        ).hexdigest()