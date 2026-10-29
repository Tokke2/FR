# -*- coding: utf-8 -*-
"""
Core Auth Plugin v2.0.0

Säker autentisering och lösenordshantering för systemet.

FUNKTIONER (1-12):
    1. verify_password() - Verifiera lösenord
    2. change_password() - Ändra lösenord
    3. is_authenticated() - Kontrollera om autentiserad
    4. login() - Logga in användare
    5. logout() - Logga ut användare
    6. get_login_attempts() - Hämta inloggningsförsök
    7. reset_login_attempts() - Återställ räknare
    8. is_locked_out() - Kolla om utelåst
    9. get_session_info() - Hämta session-info
    10. require_auth() - Decorator för autentisering
    11. hash_password() - Hasha lösenord (säker)
    12. get_diagnostics() - Diagnostik

SÄKERHETSFUNKTIONER:
    - SHA-256 hashning av lösenord
    - Brute-force skydd (låsning efter X försök)
    - Session-hantering
    - Event-loggning av login/logout
    - Säker lösenordsjämförelse (timing-safe)

SAMARBETE:
    - core_config: Konfigurationsvärden
    - core_json: JSON-lagring (om tillgänglig)
    - core_logger: Event-loggning (om tillgänglig)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Final, List, Optional, Tuple

from core.plugin_base import PluginBase

if TYPE_CHECKING:
    from core.application import Application


# ══════════════════════════════════════════════════════════════════════════════
# COPYRIGHT & CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "2.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"

DEFAULT_PASSWORD: Final[str] = "admin123"
MAX_LOGIN_ATTEMPTS: Final[int] = 5
LOCKOUT_DURATION_MINUTES: Final[int] = 15
PASSWORD_MIN_LENGTH: Final[int] = 4
SESSION_TIMEOUT_MINUTES: Final[int] = 480  # 8 timmar

# Salt för hashning
PASSWORD_SALT: Final[str] = "ts_filreg_2025_salt"


def get_copyright_year() -> int:
    """Hämta aktuellt år."""
    return datetime.now().year


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {get_copyright_year()} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def setup_logger() -> logging.Logger:
    """Konfigurera och returnera logger. Kraschsäker."""
    try:
        log = logging.getLogger("plugins.core_auth")
        if not log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S",
                )
            )
            log.addHandler(handler)
            log.setLevel(logging.INFO)
        return log
    except Exception:
        return logging.getLogger(__name__)


logger = setup_logger()


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Robust plugin-hämtning. Kraschsäker.
    """
    if app is None:
        return None

    normalized = name.lower().replace(" ", "_").replace("-", "_")
    names_to_try = [name, normalized]

    for try_name in names_to_try:
        if hasattr(app, "get_plugin"):
            try:
                result = app.get_plugin(try_name)
                if result is not None:
                    return result
            except Exception:
                pass

        if hasattr(app, "plugin_loader"):
            try:
                result = app.plugin_loader.get_plugin(try_name)
                if result is not None:
                    return result
            except Exception:
                pass

        if hasattr(app, "plugin_manager"):
            try:
                result = app.plugin_manager.get_plugin(try_name)
                if result is not None:
                    return result
            except Exception:
                pass

        try:
            result = getattr(app, try_name, None)
            if result is not None:
                return result
        except Exception:
            pass

    return None


def get_event_bus(app: Any) -> Any:
    """Hämta event bus säkert."""
    if app is None:
        return None
    return getattr(app, "event_bus", None) or getattr(app, "events", None)


def emit_event_safe(app: Any, event_name: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """Emit event säkert. Kraschsäker."""
    bus = get_event_bus(app)
    if bus is None:
        return False

    payload = data or {}

    try:
        if hasattr(bus, "emit") and callable(bus.emit):
            bus.emit(event_name, payload)
            return True
        if hasattr(bus, "publish") and callable(bus.publish):
            bus.publish(event_name, payload)
            return True
    except Exception as exc:
        logger.debug("Event emit failed: %s: %s", event_name, exc)

    return False


def get_config_value(app: Any, key: str, default: Any = None) -> Any:
    """Hämta config-värde säkert. Kraschsäker."""
    try:
        config_plugin = get_plugin_safe(app, "core_config")
        if config_plugin is not None:
            if hasattr(config_plugin, "get_config_value") and callable(config_plugin.get_config_value):
                result = config_plugin.get_config_value(key, default)
                if result is not None:
                    return result
            if hasattr(config_plugin, "get") and callable(config_plugin.get):
                result = config_plugin.get(key, default)
                if result is not None:
                    return result

        cfg = getattr(app, "config", None)
        if cfg:
            if hasattr(cfg, "get") and callable(cfg.get):
                return cfg.get(key, default)
            if isinstance(cfg, dict):
                return cfg.get(key, default)
    except Exception:
        pass

    return default


def atomic_write_json(path: Path, data: Dict[str, Any]) -> bool:
    """Skriv JSON atomiskt."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{path.stem}_",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )
        try:
            with open(fd, "w", encoding="utf-8", closefd=False) as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
            return True
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
    except Exception:
        logger.exception("Atomisk JSON-skrivning misslyckades för %s", path)
        return False


# ══════════════════════════════════════════════════════════════════════════════
# PASSWORD UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def hash_password_internal(password: str, salt: str = PASSWORD_SALT) -> str:
    """
    Hasha lösenord med SHA-256. Kraschsäker.
    """
    try:
        salted = f"{salt}{password}{salt}"
        return hashlib.sha256(salted.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def secure_compare(a: str, b: str) -> bool:
    """
    Timing-safe jämförelse av strängar. Kraschsäker.
    """
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    Core Auth Plugin v2.0.0

    Säker autentisering och lösenordshantering.
    """

    NAME: str = "Core Auth"
    VERSION: str = VERSION
    DESCRIPTION: str = "Säker autentisering och lösenordshantering (12 funktioner)"
    AUTHOR: str = AUTHOR
    COPYRIGHT: str = get_copyright_string()
    DEPENDENCIES: List[str] = []
    OPTIONAL_DEPENDENCIES: List[str] = ["core_json", "core_config", "core_logger"]

    def __init__(self, app: "Application") -> None:
        super().__init__(app)

        self.is_active: bool = False
        self._password_path: Optional[Path] = None
        self._data_dir: Optional[Path] = None

        self._password_config: Dict[str, Any] = {}
        self._session: Dict[str, Any] = {}
        self._login_attempts: int = 0
        self._lockout_until: Optional[datetime] = None
        self._initialized: bool = False
        self._authenticated: bool = False

    @property
    def copyright(self) -> str:
        """Dynamisk copyright-sträng."""
        return get_copyright_string()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Initiera plugin. Kraschsäker."""
        try:
            logger.info("=" * 60)
            logger.info("Core Auth v%s", VERSION)
            logger.info("%s", self.copyright)
            logger.info("=" * 60)

            base_dir = Path(get_config_value(self.app, "base_dir", "."))
            data_dir_name = get_config_value(self.app, "data_dir", "data")
            self._data_dir = base_dir / data_dir_name / "core_auth"
            self._data_dir.mkdir(parents=True, exist_ok=True)

            self._password_path = self._data_dir / "auth_config.json"

            self._password_config = self._load_password_config()
            self._migrate_to_hashed()

            try:
                self.app.auth = self
                self.app.core_auth = self
            except Exception:
                pass

            self._initialized = True
            logger.info("12 public functions available")
            logger.info("Initialized successfully")
            return True

        except Exception as exc:
            logger.exception("Failed to initialize: %s", exc)
            self._initialized = False
            return False

    def activate(self) -> bool:
        """Aktivera plugin. Kraschsäker."""
        try:
            self.is_active = True
            emit_event_safe(self.app, "auth:activated", {})
            logger.info("Activated")
            return True
        except Exception as exc:
            logger.error("Activation failed: %s", exc)
            return False

    def deactivate(self) -> bool:
        """Deaktivera plugin. Kraschsäker."""
        try:
            if self._authenticated:
                self.logout()

            self.is_active = False
            logger.info("Deactivated")
            return True
        except Exception as exc:
            logger.error("Deactivation failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Plugin contract compatibility
    # ------------------------------------------------------------------

    def init(self) -> bool:
        """Alias för initialize()."""
        return self.initialize()

    def register_ui(self, parent: Any) -> None:
        """Ingen egen standardwidget i denna version."""
        _ = parent
        return None

    def shutdown(self) -> bool:
        """Alias för deactivate()."""
        return self.deactivate()

    def config_schema(self) -> Dict[str, Any]:
        """Konfigurationsschema."""
        return {
            "enabled": {
                "type": "boolean",
                "default": True,
                "description": "Aktivera core_auth-pluginet.",
            },
            "max_login_attempts": {
                "type": "integer",
                "default": MAX_LOGIN_ATTEMPTS,
                "description": "Max antal felaktiga inloggningsförsök före låsning.",
            },
            "lockout_duration_minutes": {
                "type": "integer",
                "default": LOCKOUT_DURATION_MINUTES,
                "description": "Låstid i minuter efter för många felaktiga försök.",
            },
            "session_timeout_minutes": {
                "type": "integer",
                "default": SESSION_TIMEOUT_MINUTES,
                "description": "Session timeout i minuter.",
            },
        }

    # ------------------------------------------------------------------
    # Public API - functions 1-6
    # ------------------------------------------------------------------

    def verify_password(self, password: str) -> bool:
        """
        1. Verifiera lösenord. Kraschsäker.
        """
        try:
            if not password:
                return False

            if self.is_locked_out():
                logger.warning("Login attempt while locked out")
                return False

            is_valid = self._verify_password_value(password)

            if not is_valid:
                self._login_attempts += 1
                self._check_lockout()
                logger.warning(
                    "Invalid password attempt (%s/%s)",
                    self._login_attempts,
                    MAX_LOGIN_ATTEMPTS,
                )

            return is_valid

        except Exception as exc:
            logger.error("verify_password failed: %s", exc)
            return False

    def change_password(self, old_password: str, new_password: str) -> Tuple[bool, str]:
        """
        2. Ändra lösenord. Kraschsäker.
        """
        try:
            if not self._verify_password_value(old_password):
                return False, "Felaktigt nuvarande lösenord"

            if len(new_password) < PASSWORD_MIN_LENGTH:
                return False, f"Nytt lösenord måste vara minst {PASSWORD_MIN_LENGTH} tecken"

            new_hash = hash_password_internal(new_password)

            self._password_config["password_hash"] = new_hash
            self._password_config["last_changed"] = datetime.now().isoformat()
            self._password_config["changed_count"] = (
                self._password_config.get("changed_count", 0) + 1
            )
            self._password_config.pop("admin_password", None)

            if self._save_password_config():
                logger.info("Password changed successfully")
                emit_event_safe(
                    self.app,
                    "auth:password_changed",
                    {"timestamp": datetime.now().isoformat()},
                )
                return True, "Lösenord ändrat"

            return False, "Kunde inte spara nytt lösenord"

        except Exception as exc:
            logger.error("change_password failed: %s", exc)
            return False, f"Fel: {exc}"

    def is_authenticated(self) -> bool:
        """
        3. Kontrollera om autentiserad. Kraschsäker.
        """
        try:
            if not self._authenticated:
                return False

            session_start = self._session.get("started_at")
            if session_start:
                try:
                    started = datetime.fromisoformat(session_start)
                    if datetime.now() - started > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                        logger.info("Session expired")
                        self.logout()
                        return False
                except Exception:
                    pass

            return self._authenticated

        except Exception:
            return False

    def login(self, password: str) -> Tuple[bool, str]:
        """
        4. Logga in användare. Kraschsäker.
        """
        try:
            if self.is_locked_out():
                remaining = self._get_lockout_remaining()
                return False, f"Utelåst. Försök igen om {remaining} minuter."

            if not self.verify_password(password):
                remaining_attempts = MAX_LOGIN_ATTEMPTS - self._login_attempts
                if remaining_attempts > 0:
                    return False, f"Felaktigt lösenord. {remaining_attempts} försök kvar."
                return False, "Utelåst på grund av för många försök."

            self._authenticated = True
            self._login_attempts = 0
            self._lockout_until = None

            self._session = {
                "started_at": datetime.now().isoformat(),
                "session_id": secrets.token_hex(16),
            }

            logger.info("User logged in")
            emit_event_safe(
                self.app,
                "auth:login",
                {
                    "session_id": self._session.get("session_id"),
                    "timestamp": self._session.get("started_at"),
                },
            )

            return True, "Inloggad"

        except Exception as exc:
            logger.error("login failed: %s", exc)
            return False, f"Fel: {exc}"

    def logout(self) -> bool:
        """
        5. Logga ut användare. Kraschsäker.
        """
        try:
            was_authenticated = self._authenticated

            self._authenticated = False
            session_id = self._session.get("session_id")
            self._session = {}

            if was_authenticated:
                logger.info("User logged out")
                emit_event_safe(
                    self.app,
                    "auth:logout",
                    {
                        "session_id": session_id,
                        "timestamp": datetime.now().isoformat(),
                    },
                )

            return True

        except Exception as exc:
            logger.error("logout failed: %s", exc)
            return False

    def get_login_attempts(self) -> int:
        """
        6. Hämta antal misslyckade inloggningsförsök. Kraschsäker.
        """
        return self._login_attempts

    # ------------------------------------------------------------------
    # Public API - functions 7-12
    # ------------------------------------------------------------------

    def reset_login_attempts(self, admin_password: str) -> Tuple[bool, str]:
        """
        7. Återställ inloggningsförsök. Kraschsäker.
        """
        try:
            if not self._verify_password_value(admin_password):
                return False, "Felaktigt admin-lösenord"

            self._login_attempts = 0
            self._lockout_until = None

            logger.info("Login attempts reset by admin")
            emit_event_safe(self.app, "auth:attempts_reset", {})

            return True, "Inloggningsförsök återställda"

        except Exception as exc:
            logger.error("reset_login_attempts failed: %s", exc)
            return False, f"Fel: {exc}"

    def is_locked_out(self) -> bool:
        """
        8. Kolla om utelåst. Kraschsäker.
        """
        try:
            if self._lockout_until is None:
                return False

            if datetime.now() >= self._lockout_until:
                self._lockout_until = None
                self._login_attempts = 0
                return False

            return True

        except Exception:
            return False

    def get_session_info(self) -> Dict[str, Any]:
        """
        9. Hämta session-info. Kraschsäker.
        """
        try:
            if not self._authenticated:
                return {
                    "authenticated": False,
                    "session_id": None,
                }

            return {
                "authenticated": True,
                "session_id": self._session.get("session_id"),
                "started_at": self._session.get("started_at"),
                "timeout_minutes": SESSION_TIMEOUT_MINUTES,
            }

        except Exception as exc:
            return {"error": str(exc)}

    def require_auth(self, func: Callable) -> Callable:
        """
        10. Decorator för att kräva autentisering. Kraschsäker.
        """
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not self.is_authenticated():
                raise PermissionError("Autentisering krävs")
            return func(*args, **kwargs)

        return wrapper

    def hash_password(self, password: str) -> str:
        """
        11. Hasha lösenord (publik utility). Kraschsäker.
        """
        return hash_password_internal(password)

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        12. Hämta diagnostik. Kraschsäker.
        """
        try:
            return {
                "plugin_name": self.NAME,
                "plugin_version": self.VERSION,
                "copyright": self.copyright,
                "initialized": self._initialized,
                "is_active": self.is_active,
                "authenticated": self._authenticated,
                "login_attempts": self._login_attempts,
                "is_locked_out": self.is_locked_out(),
                "lockout_remaining_minutes": self._get_lockout_remaining(),
                "session_active": bool(self._session),
                "password_last_changed": self._password_config.get("last_changed"),
                "password_change_count": self._password_config.get("changed_count", 0),
                "password_hashed": bool(self._password_config.get("password_hash")),
                "max_login_attempts": MAX_LOGIN_ATTEMPTS,
                "lockout_duration_minutes": LOCKOUT_DURATION_MINUTES,
                "session_timeout_minutes": SESSION_TIMEOUT_MINUTES,
                "functions_available": 12,
            }
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _verify_password_value(self, password: str) -> bool:
        """Intern verifiering utan att öka login-attempts."""
        if not password:
            return False

        stored_hash = self._password_config.get("password_hash", "")
        if not stored_hash:
            return password == DEFAULT_PASSWORD

        input_hash = hash_password_internal(password)
        return secure_compare(input_hash, stored_hash)

    def _load_password_config(self) -> Dict[str, Any]:
        """Ladda lösenordskonfiguration. Kraschsäker."""
        default: Dict[str, Any] = {}

        try:
            if not self._password_path or not self._password_path.exists():
                return default

            json_plugin = get_plugin_safe(self.app, "core_json")
            if json_plugin and hasattr(json_plugin, "load_json"):
                data = json_plugin.load_json(self._password_path, default)
                return data if isinstance(data, dict) else default

            with open(self._password_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else default

        except Exception as exc:
            logger.error("Failed to load password config: %s", exc)
            return default

    def _save_password_config(self) -> bool:
        """Spara lösenordskonfiguration. Kraschsäker."""
        try:
            if not self._password_path:
                return False

            json_plugin = get_plugin_safe(self.app, "core_json")
            if json_plugin and hasattr(json_plugin, "save_json"):
                return bool(json_plugin.save_json(self._password_path, self._password_config))

            return atomic_write_json(self._password_path, self._password_config)

        except Exception as exc:
            logger.error("Failed to save password config: %s", exc)
            return False

    def _migrate_to_hashed(self) -> None:
        """Migrera från klartext till hashat lösenord. Kraschsäker."""
        try:
            cleartext = self._password_config.get("admin_password")
            existing_hash = self._password_config.get("password_hash")

            if cleartext and not existing_hash:
                logger.info("Migrating password to hashed storage")

                self._password_config["password_hash"] = hash_password_internal(cleartext)
                self._password_config["migrated_at"] = datetime.now().isoformat()
                del self._password_config["admin_password"]

                self._save_password_config()
                logger.info("Password migration complete")

        except Exception as exc:
            logger.error("Password migration failed: %s", exc)

    def _check_lockout(self) -> None:
        """Kontrollera och sätt lockout vid behov. Kraschsäker."""
        try:
            if self._login_attempts >= MAX_LOGIN_ATTEMPTS:
                self._lockout_until = datetime.now() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                logger.warning("Account locked for %s minutes", LOCKOUT_DURATION_MINUTES)
                emit_event_safe(
                    self.app,
                    "auth:lockout",
                    {
                        "until": self._lockout_until.isoformat(),
                        "attempts": self._login_attempts,
                    },
                )
        except Exception:
            pass

    def _get_lockout_remaining(self) -> int:
        """Hämta återstående lockout-tid i minuter. Kraschsäker."""
        try:
            if self._lockout_until is None:
                return 0

            remaining = self._lockout_until - datetime.now()
            if remaining.total_seconds() <= 0:
                return 0

            return int(remaining.total_seconds() / 60) + 1

        except Exception:
            return 0


__all__ = [
    "VERSION",
    "AUTHOR",
    "DEFAULT_PASSWORD",
    "MAX_LOGIN_ATTEMPTS",
    "LOCKOUT_DURATION_MINUTES",
    "PASSWORD_MIN_LENGTH",
    "SESSION_TIMEOUT_MINUTES",
    "get_copyright_year",
    "get_copyright_string",
    "get_plugin_safe",
    "emit_event_safe",
    "hash_password_internal",
    "secure_compare",
    "Plugin",
]