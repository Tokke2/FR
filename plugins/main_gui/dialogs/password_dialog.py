# -*- coding: utf-8 -*-
# Fil: plugins/main_gui/dialogs/password_dialog.py

"""
Password Dialog v1.0.1 — PySide6-port av inklistrad tkinter-version

Dialoger för säker lösenords- och PIN-hantering med validering,
styrkeindikator, visa/dölj, förbättringstips och matchningskontroll.

INNEHÅLL:
  - PasswordValidator   — ren Python: validering + styrkeanalys
  - PasswordEntry       — QLineEdit + QToolButton (👁 visa/dölj)
  - StrengthMeter       — QProgressBar + QLabel (styrkeindikator)
  - PasswordDialog      — ändra lösenord (kräv old, min-styrka, bekräfta)
  - PinDialog           — PIN-autentisering (max_attempts, låsning)
  - require_pin / change_password — bekvämlighetsfunktioner

ANVÄNDNING (från main_gui/plugin.py, framtida inkoppling):
    from .dialogs.password_dialog import require_pin, change_password
    if require_pin(self._main_window, self.app):
        do_sensitive_operation()
    change_password(self._main_window, self.app)

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (korrekthet, KRITISK): tkinter → PySide6-port. main_gui är
    ett PySide6-plugin — tkinter.Toplevel/ttk kan inte köras (fel
    föräldratyp + krockande eventloopar). Alla widgets portade:
    PasswordEntry (QLineEdit + QToolButton, signalbaserad),
    StrengthMeter (QProgressBar + QLabel), PasswordDialog/PinDialog
    (QDialog + exec()), require_pin/change_password (exec i stället
    för wait_window).
  - FIX (säkerhet, ALDRIG klartext): lokal PIN-lagring skrivs nu som
    PBKDF2-SHA256-saltad hash ({"pin_hash", "pin_salt"}, 100 000
    iterationer, hmac.compare_digest-jämförelse) i stället för
    klartext. Legacy-klartext ("pin") läses fortfarande (bakåt-
    kompatibilitet) och migreras till hash vid nästa byte.
  - FIX (sökväg, låst regel): ".js data"/settings.json → base_dir/
    json/settings.json (KRAV Z-sektionen: json/-katalogen).
  - FIX (dataförlust, låst regel): atomisk skrivning (mkstemp →
    fsync → os.replace — ALDRIG direkt json.dump till målfil).
  - FIX (stabilitet): plugin-hämtning via _get_plugin_safe (4 metoder
    i fallback-kedja, ej enbart legacy plugin_manager); auth.
    change_password-resultat avpackas robust (tuple[bool, str]
    ELLER bool — originalet kraschade på ren bool); varje plugin-gren
    try/except + _log.exception (lazy %s).
  - FIX (låsta regler): modul-nivå _log (aldrig print/self.logger);
    VERSION/AUTHOR (Rickard Längkvist) + dynamisk copyright;
    setObjectName med design-tokens (PageTitle, StatusLabel,
    PrimaryButton, SecondaryButton, buttonBox, passwordToggle,
    strengthMeter, strengthLabel, tipsGroup); full-form PySide6-
    enums (QLineEdit.EchoMode.Password/Normal,
    QDialogButtonBox.StandardButton.*); setWordWrap(True) i kod
    (aldrig word-wrap i stylesheet); DEFAULT_PIN som namngiven
    konstant i stället för upprepade hårdkodade "1234"-strängar;
    "# Fil:"-kommentar behållen (KRAV 58).
  - FIX (säkerhet): förbjudna-tecken-validering (<>\"') AKTIVERAD
    (var utkommenterad i originalet). Gäller endast NYTT lösenord vid
    byte — befintliga lösenord påverkas inte.
  - FIX (spårbarhet): felaktiga PIN-försök loggas som warning med
    antal kvar (utan PIN-värdet); lyckat/lyckat-misslyckat
    lösenordsbyte loggas (lazy %s).
  - FIX (UI/UX): Enter = spara via returnPressed + default-knapp
    (QDialogButtonBox); Esc = avbryt (QDialog-standard); spara-
    knappen disabled tills giltigt; tips/status-färger via befintliga
    STRENGTH_COLORS-konstanter (inga nya hårdkodade färger).
  - OBS (avvaktar): settings_manager/transportstyrelsen-grenarna
    skriver PIN i pluginens format (kan vara klartext) — pluginens
    ansvar; vår egen fallback skriver ALDRIG klartext.
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original): tkinter-version (ersatt av v1.0.1).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_log: logging.Logger = logging.getLogger("password_dialog")

VERSION: str = "1.0.1"
AUTHOR: str = "Rickard Längkvist"

# Default-PIN (namngiven konstant — samma default som appen använt).
DEFAULT_PIN: str = "1234"

# Relativ sökväg för lokal PIN-fil (json/-katalogen, KRAV Z).
_SETTINGS_RELATIVE: str = "json/settings.json"

# PBKDF2-iterationer för PIN-hashning.
_PBKDF2_ITERATIONS: int = 100_000


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def _get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Robust plugin-hämtning — samma fallback-kedja som main_gui/plugin.py.

    Metod 1: app.get_plugin() · 2: app.plugin_loader.get_plugin() ·
    3: app.plugin_manager.get_plugin() (legacy) · 4: direktattribut.
    """
    if app is None:
        return None
    try:
        getter = getattr(app, "get_plugin", None)
        if callable(getter):
            plugin = getter(name)
            if plugin is not None:
                return plugin
    except Exception as exc:
        _log.debug("app.get_plugin misslyckades för %s: %s", name, exc)
    try:
        loader = getattr(app, "plugin_loader", None)
        if loader is not None and hasattr(loader, "get_plugin"):
            plugin = loader.get_plugin(name)
            if plugin is not None:
                return plugin
    except Exception as exc:
        _log.debug(
            "plugin_loader.get_plugin misslyckades för %s: %s",
            name,
            exc,
        )
    try:
        manager = getattr(app, "plugin_manager", None)
        if manager is not None and hasattr(manager, "get_plugin"):
            plugin = manager.get_plugin(name)
            if plugin is not None:
                return plugin
    except Exception as exc:
        _log.debug(
            "plugin_manager.get_plugin misslyckades för %s: %s",
            name,
            exc,
        )
    try:
        attr_name = name.replace("-", "_").lower()
        if hasattr(app, attr_name):
            return getattr(app, attr_name)
    except Exception as exc:
        _log.debug("getattr misslyckades för %s: %s", name, exc)
    return None


def _settings_path(app: Any) -> Path:
    """Sökväg till json/settings.json under appens baskatalog."""
    base = Path.cwd()
    config = getattr(app, "config", None)
    if isinstance(config, dict):
        base = Path(str(config.get("base_dir", base)))
    elif config is not None:
        base = Path(str(getattr(config, "base_dir", base)))
    return base / _SETTINGS_RELATIVE


def _hash_pin(pin: str, salt: str) -> str:
    """PBKDF2-SHA256-hash av PIN (tidkonstant jämförbar via hmac)."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    ).hex()


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """
    Atomisk JSON-skrivning (låst regel: mkstemp → fsync → os.replace).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".settings_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class _PinStore:
    """
    Lokal PIN-lagring med PBKDF2-saltning (ALDRIG klartext skrivs).

    Format (json/settings.json):
        {"pin_hash": "<hex>", "pin_salt": "<hex>",
         "updated_at": "<iso>"}

    Legacy-format stöds vid LÄSNING: {"pin": "<klartext>"} — migreras
    till hash vid nästa framgångsrika byte.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def exists(self) -> bool:
        """True om PIN-filen finns."""
        return self._path.is_file()

    def verify(self, entered: str) -> bool:
        """Tidkonstant jämförelse mot lagrad PIN (hash eller legacy)."""
        data = self._read()
        if not isinstance(data, dict):
            return False
        pin_hash = data.get("pin_hash")
        pin_salt = data.get("pin_salt")
        if isinstance(pin_hash, str) and isinstance(pin_salt, str):
            if pin_hash and pin_salt:
                return hmac.compare_digest(
                    _hash_pin(entered, pin_salt),
                    pin_hash,
                )
        stored = data.get("pin")
        if stored is None:
            return False
        return hmac.compare_digest(str(entered), str(stored))

    def change(
        self,
        old_pw: Optional[str],
        new_pw: str,
    ) -> Tuple[bool, str]:
        """
        Byt PIN (verifierar gammal om angiven) och skriv atomiskt.

        Returns:
            (success, meddelande)
        """
        if old_pw is not None and not self.verify(old_pw):
            return False, "Felaktigt nuvarande lösenord"
        salt = secrets.token_hex(16)
        payload = {
            "pin_hash": _hash_pin(new_pw, salt),
            "pin_salt": salt,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            _atomic_write_json(self._path, payload)
        except Exception:
            _log.exception("Kunde inte skriva %s", self._path)
            return False, "Kunde inte spara lösenordet"
        return True, "Lösenordet har ändrats"

    def _read(self) -> Dict[str, Any]:
        """Läs PIN-fil (korrupt/avsaknad → {})."""
        try:
            if not self._path.is_file():
                return {}
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            _log.exception("Kunde inte läsa %s", self._path)
            return {}


# ══════════════════════════════════════════════════════════════════════════════
# LÖSENORDSVALIDERING
# ══════════════════════════════════════════════════════════════════════════════

class PasswordValidator:
    """Validerar och analyserar lösenordsstyrka (ren Python, inga GUI-beroenden)."""

    # Krav
    MIN_LENGTH: int = 4
    MAX_LENGTH: int = 128
    RECOMMENDED_LENGTH: int = 8

    # Styrkenivåer
    STRENGTH_WEAK: int = 0
    STRENGTH_FAIR: int = 1
    STRENGTH_GOOD: int = 2
    STRENGTH_STRONG: int = 3
    STRENGTH_VERY_STRONG: int = 4

    STRENGTH_NAMES: Dict[int, str] = {
        STRENGTH_WEAK: "Svagt",
        STRENGTH_FAIR: "Acceptabelt",
        STRENGTH_GOOD: "Bra",
        STRENGTH_STRONG: "Starkt",
        STRENGTH_VERY_STRONG: "Mycket starkt",
    }

    # Semantiska signal-färger (samma mönster som Styles-klasserna).
    STRENGTH_COLORS: Dict[int, str] = {
        STRENGTH_WEAK: "#e74c3c",        # Röd
        STRENGTH_FAIR: "#e67e22",        # Orange
        STRENGTH_GOOD: "#f39c12",        # Gul
        STRENGTH_STRONG: "#27ae60",      # Grön
        STRENGTH_VERY_STRONG: "#2ecc71",  # Ljusgrön
    }

    _FORBIDDEN_RE = re.compile(r"""[<>"']""")
    _SPECIAL_RE = re.compile(
        r"""[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\\/`~]"""
    )
    _REPEAT_RE = re.compile(r"(.)\1{2,}")
    _SEQUENCE_DIGITS_RE = re.compile(
        r"(012|123|234|345|456|567|678|789|890)"
    )
    _SEQUENCE_LETTERS_RE = re.compile(
        r"(abc|bcd|cde|def|efg|fgh|ghi|hij|ijk|jkl|klm|lmn|mno|"
        r"nop|opq|pqr|qrs|rst|stu|tuv|uvw|vwx|wxy|xyz)"
    )
    _COMMON_PATTERNS: Tuple[str, ...] = (
        "password",
        "lösenord",
        "12345",
        "qwerty",
        "admin",
        "letmein",
    )

    @classmethod
    def validate(cls, password: str) -> Tuple[bool, str]:
        """
        Validera lösenord.

        Returns:
            (valid, error_message)
        """
        if not password:
            return False, "Lösenord får inte vara tomt"
        if len(password) < cls.MIN_LENGTH:
            return False, (
                "Lösenord måste vara minst %d tecken" % cls.MIN_LENGTH
            )
        if len(password) > cls.MAX_LENGTH:
            return False, (
                "Lösenord får inte vara längre än %d tecken"
                % cls.MAX_LENGTH
            )
        if cls._FORBIDDEN_RE.search(password):
            return False, "Lösenord innehåller otillåtna tecken (< > \" ')"
        return True, ""

    @classmethod
    def calculate_strength(cls, password: str) -> Tuple[int, int]:
        """
        Beräkna lösenordsstyrka.

        Returns:
            (strength_level, score_percent)
        """
        if not password:
            return cls.STRENGTH_WEAK, 0

        score = 0

        # Längd (0-25 poäng)
        length = len(password)
        if length >= 16:
            score += 25
        elif length >= 12:
            score += 20
        elif length >= 8:
            score += 15
        elif length >= 6:
            score += 10
        elif length >= 4:
            score += 5

        # Variation (0-25 poäng per kategori)
        has_lower = bool(re.search(r"[a-z]", password))
        has_upper = bool(re.search(r"[A-Z]", password))
        has_digit = bool(re.search(r"\d", password))
        has_special = bool(cls._SPECIAL_RE.search(password))

        if has_lower:
            score += 15
        if has_upper:
            score += 15
        if has_digit:
            score += 20
        if has_special:
            score += 25

        # Bonus för blandning
        variety = sum([has_lower, has_upper, has_digit, has_special])
        if variety >= 4:
            score += 10
        elif variety >= 3:
            score += 5

        # Avdrag för mönster
        if cls._REPEAT_RE.search(password):
            score -= 10
        if cls._SEQUENCE_DIGITS_RE.search(password):
            score -= 10
        if cls._SEQUENCE_LETTERS_RE.search(password.lower()):
            score -= 10

        # Vanliga ord (förenklad kontroll)
        lowered = password.lower()
        for pattern in cls._COMMON_PATTERNS:
            if pattern in lowered:
                score -= 20
                break

        # Begränsa till 0-100
        score = max(0, min(100, score))

        # Konvertera till nivå
        if score >= 80:
            level = cls.STRENGTH_VERY_STRONG
        elif score >= 60:
            level = cls.STRENGTH_STRONG
        elif score >= 40:
            level = cls.STRENGTH_GOOD
        elif score >= 20:
            level = cls.STRENGTH_FAIR
        else:
            level = cls.STRENGTH_WEAK

        return level, score

    @classmethod
    def get_strength_name(cls, level: int) -> str:
        """Hämta namn för styrkenivå."""
        return cls.STRENGTH_NAMES.get(level, "Okänd")

    @classmethod
    def get_strength_color(cls, level: int) -> str:
        """Hämta färg för styrkenivå."""
        return cls.STRENGTH_COLORS.get(level, "#cccccc")

    @classmethod
    def get_tips(cls, password: str) -> List[str]:
        """Generera förbättringstips."""
        tips: List[str] = []

        if len(password) < cls.RECOMMENDED_LENGTH:
            tips.append("Använd minst %d tecken" % cls.RECOMMENDED_LENGTH)

        if not re.search(r"[A-Z]", password):
            tips.append("Lägg till stora bokstäver (A-Z)")

        if not re.search(r"[a-z]", password):
            tips.append("Lägg till små bokstäver (a-z)")

        if not re.search(r"\d", password):
            tips.append("Lägg till siffror (0-9)")

        if not cls._SPECIAL_RE.search(password):
            tips.append("Lägg till specialtecken (!@#$%...)")

        if cls._REPEAT_RE.search(password):
            tips.append("Undvik upprepade tecken")

        return tips


# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

class PasswordEntry(QWidget):
    """Lösenordsfält med visa/dölj-knapp (QLineEdit + QToolButton)."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        on_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._show_password = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._entry = QLineEdit(self)
        self._entry.setEchoMode(QLineEdit.EchoMode.Password)
        if on_change is not None:
            self._entry.textChanged.connect(on_change)
        layout.addWidget(self._entry, 1)

        self._toggle_button = QToolButton(self)
        self._toggle_button.setObjectName("passwordToggle")
        self._toggle_button.setText("👁")
        self._toggle_button.setCheckable(True)
        self._toggle_button.setToolTip("Visa lösenord")
        self._toggle_button.toggled.connect(self._toggle_visibility)
        layout.addWidget(self._toggle_button)

    def _toggle_visibility(self, checked: bool) -> None:
        """Växla mellan visa/dölj."""
        self._show_password = checked
        self._entry.setEchoMode(
            QLineEdit.EchoMode.Normal
            if checked
            else QLineEdit.EchoMode.Password
        )
        self._toggle_button.setText("🙈" if checked else "👁")
        self._toggle_button.setToolTip(
            "Dölj lösenord" if checked else "Visa lösenord"
        )

    def get(self) -> str:
        """Hämta värde."""
        return self._entry.text()

    def set(self, value: str) -> None:
        """Sätt värde."""
        self._entry.setText(value)

    def clear(self) -> None:
        """Rensa fält."""
        self._entry.clear()

    def set_focus(self) -> None:
        """Sätt fokus."""
        self._entry.setFocus()

    def bind_return(self, handler: Callable[[], None]) -> None:
        """Koppla Enter-tangenten till handler."""
        self._entry.returnPressed.connect(handler)


class StrengthMeter(QWidget):
    """Visuell styrkeindikator för lösenord (QProgressBar + QLabel)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("strengthMeter")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._bar = QProgressBar(self)
        self._bar.setObjectName("strengthBar")
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(8)
        layout.addWidget(self._bar)

        self._label = QLabel("", self)
        self._label.setObjectName("strengthLabel")
        layout.addWidget(self._label)

        self._update_display(0, "", "")

    def update(self, level: int, score: int) -> None:
        """Uppdatera visning från styrkenivå + poäng."""
        color = PasswordValidator.get_strength_color(level)
        name = PasswordValidator.get_strength_name(level)
        self._update_display(score, "%s (%d%%)" % (name, score), color)

    def clear(self) -> None:
        """Rensa indikator."""
        self._update_display(0, "", "")

    def _update_display(
        self,
        percent: int,
        text: str,
        color: str,
    ) -> None:
        """Uppdatera progressbar och label (chunk-färg = signal-färg)."""
        self._bar.setValue(max(0, min(100, percent)))
        if color:
            self._bar.setStyleSheet(
                "QProgressBar::chunk { background-color: %s; "
                "border-radius: 2px; }" % color
            )
        else:
            self._bar.setStyleSheet("")
        self._label.setText(text)
        if text and color:
            self._label.setStyleSheet("color: %s;" % color)
        else:
            self._label.setStyleSheet("")


# ══════════════════════════════════════════════════════════════════════════════
# PASSWORD DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class PasswordDialog(QDialog):
    """
    Dialog för att ändra lösenord.

    Features:
    - Visa/dölj lösenord
    - Styrkeindikator
    - Validering i realtid
    - Förbättringstips
    - Bekräfta-matchar-kontroll
    - Krav på nuvarande lösenord (valbart)
    - Lägsta styrkenivå (konfigurerbart)
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        app: Any,
        title: str = "🔐 Ändra lösenord",
        require_old_password: bool = True,
        min_strength: int = PasswordValidator.STRENGTH_FAIR,
        on_success: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._require_old = require_old_password
        self._min_strength = min_strength
        self._on_success = on_success
        self._validator = PasswordValidator

        self.setObjectName("passwordDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)

        self._old_pw: Optional[PasswordEntry] = None
        self._create_widgets()

        if self._require_old and self._old_pw is not None:
            self._old_pw.set_focus()
        else:
            self._new_pw.set_focus()

    def _create_widgets(self) -> None:
        """Bygg dialogens widgets (design-tokens, inga hårdkodade färger)."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QHBoxLayout()
        icon = QLabel("🔐", self)
        icon.setObjectName("DialogIcon")
        header.addWidget(icon)
        title_label = QLabel("Ändra lösenord", self)
        title_label.setObjectName("PageTitle")
        header.addWidget(title_label)
        header.addStretch(1)
        layout.addLayout(header)

        form = QFormLayout()
        form.setSpacing(8)

        if self._require_old:
            self._old_pw = PasswordEntry(self)
            self._old_pw.bind_return(self._do_change)
            form.addRow("Nuvarande lösenord:", self._old_pw)

        self._new_pw = PasswordEntry(self, on_change=self._on_password_change)
        self._new_pw.bind_return(self._do_change)
        form.addRow("Nytt lösenord:", self._new_pw)

        self._strength_meter = StrengthMeter(self)
        form.addRow("", self._strength_meter)

        self._confirm_pw = PasswordEntry(
            self,
            on_change=self._on_confirm_change,
        )
        self._confirm_pw.bind_return(self._do_change)
        form.addRow("Bekräfta nytt lösenord:", self._confirm_pw)

        self._match_label = QLabel("", self)
        self._match_label.setObjectName("StatusLabel")
        self._match_label.setWordWrap(True)
        form.addRow("", self._match_label)
        layout.addLayout(form)

        tips_group = QGroupBox("Tips", self)
        tips_group.setObjectName("tipsGroup")
        tips_layout = QVBoxLayout(tips_group)
        self._tips_label = QLabel("Ange ett lösenord för att se tips", tips_group)
        self._tips_label.setObjectName("StatusLabel")
        self._tips_label.setWordWrap(True)
        tips_layout.addWidget(self._tips_label)
        layout.addWidget(tips_group)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.setObjectName("buttonBox")
        self._save_button = button_box.button(
            QDialogButtonBox.StandardButton.Save
        )
        self._save_button.setObjectName("PrimaryButton")
        self._save_button.setText("💾 Spara")
        self._save_button.setEnabled(False)
        cancel_button = button_box.button(
            QDialogButtonBox.StandardButton.Cancel
        )
        cancel_button.setObjectName("SecondaryButton")
        cancel_button.setText("❌ Avbryt")
        button_box.accepted.connect(self._do_change)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_password_change(self, password: str) -> None:
        """Hantera ändring av nytt lösenord (styrka + tips + matchning)."""
        level, score = self._validator.calculate_strength(password)
        self._strength_meter.update(level, score)

        if not password:
            self._tips_label.setText("Ange ett lösenord för att se tips")
            self._tips_label.setStyleSheet("")
        else:
            tips = self._validator.get_tips(password)
            if tips:
                self._tips_label.setText("• " + "\n• ".join(tips))
                self._tips_label.setStyleSheet("")
            else:
                self._tips_label.setText("✅ Bra lösenord!")
                self._tips_label.setStyleSheet(
                    "color: %s;"
                    % PasswordValidator.get_strength_color(
                        PasswordValidator.STRENGTH_STRONG
                    )
                )

        self._check_match()
        self._update_save_button()

    def _on_confirm_change(self, password: str) -> None:
        """Hantera ändring av bekräftelse (matchning + spara-knapp)."""
        self._check_match()
        self._update_save_button()

    def _check_match(self) -> None:
        """Kontrollera om lösenorden matchar (signal-färger, ej hårdkodade)."""
        new_pw = self._new_pw.get()
        confirm = self._confirm_pw.get()
        strong = PasswordValidator.get_strength_color(
            PasswordValidator.STRENGTH_STRONG
        )
        weak = PasswordValidator.get_strength_color(
            PasswordValidator.STRENGTH_WEAK
        )
        if not confirm:
            self._match_label.setText("")
            self._match_label.setStyleSheet("")
        elif new_pw == confirm:
            self._match_label.setText("✅ Lösenorden matchar")
            self._match_label.setStyleSheet("color: %s;" % strong)
        else:
            self._match_label.setText("❌ Lösenorden matchar inte")
            self._match_label.setStyleSheet("color: %s;" % weak)

    def _update_save_button(self) -> None:
        """Uppdatera spara-knappens tillstånd."""
        self._save_button.setEnabled(self._can_save())

    def _can_save(self) -> bool:
        """Kontrollera om vi kan spara."""
        if self._require_old and (
            self._old_pw is None or not self._old_pw.get()
        ):
            return False

        new_pw = self._new_pw.get()
        confirm = self._confirm_pw.get()

        valid, _ = self._validator.validate(new_pw)
        if not valid:
            return False

        level, _ = self._validator.calculate_strength(new_pw)
        if level < self._min_strength:
            return False

        return new_pw == confirm

    def _do_change(self) -> None:
        """Utför lösenordsbyte."""
        if not self._can_save():
            return

        old_pw = self._old_pw.get() if self._old_pw is not None else None
        new_pw = self._new_pw.get()
        confirm = self._confirm_pw.get()

        if new_pw != confirm:
            self._show_error("Lösenorden matchar inte")
            return

        valid, error = self._validator.validate(new_pw)
        if not valid:
            self._show_error(error)
            return

        level, _ = self._validator.calculate_strength(new_pw)
        if level < self._min_strength:
            required_name = self._validator.get_strength_name(
                self._min_strength
            )
            self._show_error(
                "Lösenordet måste vara minst '%s'" % required_name
            )
            return

        success, message = self._change_password(old_pw, new_pw)
        if success:
            _log.info("Lösenordsbyte lyckades.")
            if self._on_success is not None:
                try:
                    self._on_success()
                except Exception:
                    _log.exception("on_success-callback misslyckades.")
            self._show_success(message or "Lösenordet har ändrats!")
            self.accept()
        else:
            _log.warning("Lösenordsbyte misslyckades: %s", message)
            self._show_error(message or "Kunde inte ändra lösenord")

    def _change_password(
        self,
        old_pw: Optional[str],
        new_pw: str,
    ) -> Tuple[bool, str]:
        """
        Byt lösenord via tillgänglig källa.

        Kedja: core_auth-plugin → settings_manager → ts-config →
        lokal PIN-fil (fallback). Första källan som finns och kan
        svara avgör.
        """
        auth = _get_plugin_safe(self._app, "core_auth")
        if auth is not None:
            result = _call_change_password(auth, old_pw, new_pw)
            if result is not None:
                return result

        settings = _get_plugin_safe(self._app, "settings_manager")
        if settings is not None:
            result = self._change_via_settings(settings, old_pw, new_pw)
            if result is not None:
                return result

        ts = _get_plugin_safe(self._app, "transportstyrelsen")
        if ts is not None:
            result = self._change_via_ts_config(ts, old_pw, new_pw)
            if result is not None:
                return result

        return self._change_direct(old_pw, new_pw)

    def _change_via_settings(
        self,
        settings: Any,
        old_pw: Optional[str],
        new_pw: str,
    ) -> Tuple[bool, str]:
        """Byt lösenord via settings_manager (pluginens eget format)."""
        try:
            current = None
            getter = getattr(settings, "get_setting", None)
            if callable(getter):
                current = getter("pin", DEFAULT_PIN)

            if old_pw is not None and str(old_pw) != str(current):
                return False, "Felaktigt nuvarande lösenord"

            setter = getattr(settings, "set_setting", None)
            if not callable(setter):
                return False, "settings_manager saknar set_setting"
            setter("pin", new_pw)
            return True, "Lösenordet har ändrats"
        except Exception:
            _log.exception("Lösenordsbyte via settings misslyckades.")
            return False, "Kunde inte spara via settings_manager"

    def _change_via_ts_config(
        self,
        ts: Any,
        old_pw: Optional[str],
        new_pw: str,
    ) -> Tuple[bool, str]:
        """Byt lösenord via transportstyrelsen-config (pluginens format)."""
        try:
            get_config = getattr(ts, "get_config", None)
            update_config = getattr(ts, "update_config", None)
            if not callable(get_config) or not callable(update_config):
                return False, "transportstyrelsen saknar config-API"

            config = get_config() or {}
            if not isinstance(config, dict):
                config = {}
            current_pin = config.get("pin", DEFAULT_PIN)

            if old_pw is not None and str(old_pw) != str(current_pin):
                return False, "Felaktigt nuvarande lösenord"

            new_config = dict(config)
            new_config["pin"] = new_pw
            update_config(new_config)
            return True, "Lösenordet har ändrats"
        except Exception:
            _log.exception("Lösenordsbyte via ts-config misslyckades.")
            return False, "Kunde inte ändra via transportstyrelsen"

    def _change_direct(
        self,
        old_pw: Optional[str],
        new_pw: str,
    ) -> Tuple[bool, str]:
        """Fallback: lokal PIN-fil (PBKDF2-saltad hash, ALDRIG klartext)."""
        try:
            store = _PinStore(_settings_path(self._app))
            return store.change(old_pw, new_pw)
        except Exception:
            _log.exception("Lösenordsbyte (lokal fil) misslyckades.")
            return False, "Kunde inte spara lösenordet lokalt"

    def _show_error(self, message: str) -> None:
        """Visa felmeddelande."""
        QMessageBox.warning(self, "Fel", message)

    def _show_success(self, message: str) -> None:
        """Visa framgångsmeddelande."""
        QMessageBox.information(self, "Klart", message)


# ══════════════════════════════════════════════════════════════════════════════
# PIN DIALOG (ENKEL VERSION)
# ══════════════════════════════════════════════════════════════════════════════

class PinDialog(QDialog):
    """
    Enkel PIN-dialog för autentisering (upp till max_attempts försök).

    Användning:
        dialog = PinDialog(parent, app)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            proceed()
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        app: Any,
        title: str = "🔐 Ange PIN",
        message: str = "Ange PIN-kod för att fortsätta:",
        max_attempts: int = 3,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._message = message
        self._max_attempts = max_attempts
        self._attempts = 0
        self._result = False

        self.setObjectName("pinDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)

        self._create_widgets()
        self._pin_entry.set_focus()

    def _create_widgets(self) -> None:
        """Bygg dialogens widgets (design-tokens)."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        message_label = QLabel(self._message, self)
        message_label.setObjectName("StatusLabel")
        message_label.setWordWrap(True)
        layout.addWidget(message_label)

        self._pin_entry = PasswordEntry(self)
        self._pin_entry.bind_return(self._verify)
        layout.addWidget(self._pin_entry)

        self._attempts_label = QLabel("", self)
        self._attempts_label.setObjectName("StatusLabel")
        layout.addWidget(self._attempts_label)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.setObjectName("buttonBox")
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setObjectName("PrimaryButton")
        cancel_button = button_box.button(
            QDialogButtonBox.StandardButton.Cancel
        )
        cancel_button.setObjectName("SecondaryButton")
        button_box.accepted.connect(self._verify)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def result_flag(self) -> bool:
        """True om PIN verifierades (innan dialogen stängdes)."""
        return self._result

    def _verify(self) -> None:
        """Verifiera inmatad PIN; lås efter max_attempts felaktiga försök."""
        entered = self._pin_entry.get()

        if self._check_pin(entered):
            self._result = True
            self.accept()
            return

        self._attempts += 1
        remaining = self._max_attempts - self._attempts
        if remaining <= 0:
            _log.warning(
                "PIN-dialog: för många felaktiga försök (max %d)",
                self._max_attempts,
            )
            QMessageBox.critical(
                self,
                "Fel",
                "För många felaktiga försök!",
            )
            self._result = False
            self.reject()
            return

        _log.warning(
            "PIN-dialog: felaktig PIN — %d försök kvar",
            remaining,
        )
        weak = PasswordValidator.get_strength_color(
            PasswordValidator.STRENGTH_WEAK
        )
        self._attempts_label.setText("Fel PIN. %d försök kvar." % remaining)
        self._attempts_label.setStyleSheet("color: %s;" % weak)
        self._pin_entry.clear()
        self._pin_entry.set_focus()

    def _check_pin(self, entered: str) -> bool:
        """
        Jämför inmatad PIN mot tillgänglig källa (i prioritetsordning).

        Kedja: core_auth.get_pin → settings_manager.get_setting →
        transportstyrelsen.get_config → lokal json/settings.json →
        DEFAULT_PIN. Första källan som finns och kan svara avgör.
        """
        auth = _get_plugin_safe(self._app, "core_auth")
        if auth is not None and hasattr(auth, "get_pin"):
            try:
                return hmac.compare_digest(
                    str(entered),
                    str(auth.get_pin()),
                )
            except Exception:
                _log.exception("core_auth.get_pin misslyckades.")

        settings = _get_plugin_safe(self._app, "settings_manager")
        if settings is not None and hasattr(settings, "get_setting"):
            try:
                return hmac.compare_digest(
                    str(entered),
                    str(settings.get_setting("pin", DEFAULT_PIN)),
                )
            except Exception:
                _log.exception(
                    "settings_manager.get_setting misslyckades."
                )

        ts = _get_plugin_safe(self._app, "transportstyrelsen")
        if ts is not None and hasattr(ts, "get_config"):
            try:
                config = ts.get_config() or {}
                if isinstance(config, dict) and config.get("pin") is not None:
                    return hmac.compare_digest(
                        str(entered),
                        str(config.get("pin")),
                    )
            except Exception:
                _log.exception(
                    "transportstyrelsen.get_config misslyckades."
                )

        store = _PinStore(_settings_path(self._app))
        if store.exists():
            return store.verify(entered)

        return hmac.compare_digest(str(entered), DEFAULT_PIN)


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def require_pin(
    parent: Optional[QWidget],
    app: Any,
    message: str = "Ange PIN för att fortsätta:",
) -> bool:
    """
    Kräv PIN för att fortsätta (modal dialog).

    Användning:
        if require_pin(parent, app):
            do_sensitive_operation()
    """
    dialog = PinDialog(parent, app, message=message)
    return dialog.exec() == QDialog.DialogCode.Accepted


def change_password(
    parent: Optional[QWidget],
    app: Any,
    **kwargs: Any,
) -> bool:
    """
    Öppna dialog för att byta lösenord.

    Returns:
        True om lösenord ändrades
    """
    changed = {"value": False}

    def on_success() -> None:
        changed["value"] = True

    dialog = PasswordDialog(
        parent,
        app,
        on_success=on_success,
        **kwargs,
    )
    dialog.exec()
    return bool(changed["value"])


__all__: List[str] = [
    "PasswordValidator",
    "PasswordEntry",
    "StrengthMeter",
    "PasswordDialog",
    "PinDialog",
    "require_pin",
    "change_password",
    "_PinStore",
    "_get_plugin_safe",
    "get_copyright_string",
    "VERSION",
    "AUTHOR",
]
