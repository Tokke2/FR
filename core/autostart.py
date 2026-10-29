# -*- coding: utf-8 -*-
# core/autostart.py
"""
AutostartManager v1.0.0 — OS-specifik autostart.

Transportstyrelsen Fordonsregistreringssystem.

ANSVAR:
    - Aktivera/inaktivera autostart vid OS-inloggning:
        * Windows: Registry
          (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run)
          + .bat-fallback i Startup-mappen om Registry nekas
        * Linux:   ~/.config/autostart/<app>.desktop
          (XDG Desktop Entry)
        * macOS:   ~/Library/LaunchAgents/<bundle_id>.plist
          (launchd)
    - verify(): kontrollera att registrerad sökväg fortfarande
      pekar på korrekt körbar fil/skript
    - auto-repair: trasig/flyttad sökväg skrivs om automatiskt
    - inga dubbletter: Registry-värde + .bat hålls synkade,
      gammal post tas bort innan ny skrivs
    - sync(): körs vid app-start — synkar OS-läget mot
      settings.json-nyckeln "startup" (settings är source of
      truth) och auto-reparerar trasiga poster

API (spec Sektion D):
    AutostartManager.is_enabled()       -> bool
    AutostartManager.set_enabled(bool)  -> None
    AutostartManager.sync()             -> None
    AutostartManager.build_command()    -> str

ANVÄNDNING (main.pyw, vid startup):
    from core.autostart import AutostartManager

    am = AutostartManager(settings=settings_manager)
    am.sync()   # synkar OS mot settings["startup"] + auto-repair

    # Från inställnings-UI:
    am.set_enabled(True)    # uppdaterar OS + settings.json

START-KOMMANDO:
    Spec: appen startar ALLTID utan terminal. build_command()
    föredrar main.pyw via pythonw.exe (Windows) resp. main.pyw
    direkt (POSIX, python3). Fallback: sys.executable + main.py.
    Vid frusen app (PyInstaller): sys.executable direkt.

KRASCHSÄKERHET:
    - ALLA publika metoder kraschsäkra (fel loggas, appen
      kraschar aldrig p.g.a. autostart-hantering)
    - Saknad winreg/otillgängligt Registry -> .bat-fallback
    - Saknade kataloger skapas vid behov
    - Filskrivning atomisk (mkstemp -> fsync -> os.replace)

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Final, Optional

_log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "1.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"

DEFAULT_APP_NAME: Final[str] = (
    "TSFordonsregistreringssystem"
)
DEFAULT_BUNDLE_ID: Final[str] = (
    "se.langkvist.ts_fordonsregistreringssystem"
)

IS_WINDOWS: Final[bool] = sys.platform.startswith("win")
IS_MACOS: Final[bool] = sys.platform == "darwin"
IS_LINUX: Final[bool] = (
    sys.platform.startswith("linux")
)

# Windows Registry
_RUN_KEY: Final[str] = (
    r"Software\Microsoft\Windows\CurrentVersion\Run"
)

SETTINGS_KEY: Final[str] = "startup"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# winreg endast på Windows (kraschsäker import)
_HAS_WINREG = False
if IS_WINDOWS:
    try:
        import winreg  # noqa: F401
        _HAS_WINREG = True
    except ImportError:
        _HAS_WINREG = False


def _atomic_write_text(path: Path, content: str) -> None:
    """Skriv text atomiskt: mkstemp -> fdopen -> fsync -> os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=f".{path.name}.tmp_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# AUTOSTART MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class AutostartManager:
    """
    Plattformsoberoende autostart-hantering.

    settings.json-nyckeln "startup" är source of truth:
      sync() ser till att OS-registreringen matchar den.

    Trådsäker. ALLA publika metoder kraschsäkra.
    """

    def __init__(
        self,
        app_name: str = DEFAULT_APP_NAME,
        *,
        settings: Optional[Any] = None,
        base_dir: Optional[Path] = None,
        bundle_id: str = DEFAULT_BUNDLE_ID,
    ) -> None:
        """
        Initiera AutostartManager.

        Args:
            app_name: Namn på Registry-värde/.desktop/.bat
                      (endast alfanumeriskt + _ -)
            settings: SettingsManager (läser/skriver "startup")
            base_dir: Projektrot där main.pyw/main.py finns
                      (None = katalogen ovanför core/)
            bundle_id: macOS launchd-label
        """
        self._app_name = self._sanitize_name(app_name)
        self._settings = settings
        self._bundle_id = bundle_id
        self._lock = threading.RLock()

        if base_dir is not None:
            self._base_dir = Path(base_dir).resolve()
        else:
            # core/autostart.py -> projektrot = parent.parent
            self._base_dir = Path(
                __file__
            ).resolve().parent.parent

        _log.debug(
            "AutostartManager v%s initierad (app=%s, base=%s)",
            VERSION, self._app_name, self._base_dir,
        )

    # ──────────────────────────────────────────────────────────────────
    # PUBLIKT API (spec-kontrakt)
    # ──────────────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """
        Kontrollera om autostart är registrerad i OS.
        KRASCHSÄKER.

        Returns:
            True om en autostart-post finns
        """
        with self._lock:
            try:
                if IS_WINDOWS:
                    return (
                        self._win_registry_get() is not None
                        or self._win_bat_path().exists()
                    )
                if IS_MACOS:
                    return self._mac_plist_path().exists()
                if IS_LINUX:
                    return self._linux_desktop_path().exists()
                return False
            except Exception as exc:
                _log.error("is_enabled-fel: %s", exc)
                return False

    def set_enabled(self, enabled: bool) -> None:
        """
        Aktivera/inaktivera autostart. KRASCHSÄKER.

        Uppdaterar både OS-registrering och settings.json
        ("startup"). Inga dubbletter — gammal post tas alltid
        bort först.

        Args:
            enabled: True = aktivera, False = inaktivera
        """
        with self._lock:
            try:
                if enabled:
                    ok = self._install()
                    if ok:
                        _log.info(
                            "Autostart aktiverad (%s)",
                            self._platform_name(),
                        )
                    else:
                        _log.error(
                            "Autostart kunde inte aktiveras"
                        )
                else:
                    self._uninstall()
                    _log.info("Autostart inaktiverad")

                self._save_setting(enabled and ok if enabled
                                   else False)
            except Exception as exc:
                _log.error(
                    "set_enabled(%s) misslyckades: %s",
                    enabled, exc, exc_info=True,
                )

    def sync(self) -> None:
        """
        Synka OS-läget mot settings.json vid app-start.
        KRASCHSÄKER.

        Regler (settings = source of truth):
          - settings startup=True,  OS saknas    -> installera
          - settings startup=True,  OS trasig    -> auto-repair
            (skriv om med korrekt kommando)
          - settings startup=False, OS finns     -> avregistrera
          - settings startup=True,  OS OK        -> ingen åtgärd
        """
        with self._lock:
            try:
                desired = self._read_setting()
                os_enabled = self.is_enabled()

                if desired and not os_enabled:
                    _log.info(
                        "sync: settings=on, OS=av -> installerar"
                    )
                    self._install()
                elif desired and os_enabled:
                    if not self.verify():
                        _log.warning(
                            "sync: trasig autostart-post -> "
                            "auto-repair"
                        )
                        self._uninstall()
                        self._install()
                    else:
                        _log.debug("sync: autostart OK")
                elif not desired and os_enabled:
                    _log.info(
                        "sync: settings=av, OS=på -> "
                        "avregistrerar"
                    )
                    self._uninstall()
                else:
                    _log.debug("sync: inget att göra")
            except Exception as exc:
                _log.error(
                    "sync misslyckades: %s", exc, exc_info=True,
                )

    def build_command(self) -> str:
        """
        Bygg start-kommandot för autostart. KRASCHSÄKER.

        Prioritet (spec: ALDRIG terminalfönster):
          1. Frusen app (PyInstaller)  -> "<exe>"
          2. Windows: pythonw + main.pyw
          3. POSIX:   python3 + main.pyw (eller main.py)
        Alla sökvägar citeras (tål mellanslag).

        Returns:
            Komplett kommandosträng
        """
        try:
            # Frusen app (PyInstaller/Nuitka)
            if getattr(sys, "frozen", False):
                return f'"{Path(sys.executable).resolve()}"'

            entry = self._find_entry_script()
            interpreter = self._find_interpreter()
            return f'"{interpreter}" "{entry}"'
        except Exception as exc:
            _log.error("build_command-fel: %s", exc)
            return f'"{sys.executable}"'

    # ──────────────────────────────────────────────────────────────────
    # VERIFY / DIAGNOSTIK
    # ──────────────────────────────────────────────────────────────────

    def verify(self) -> bool:
        """
        Verifiera att registrerad autostart-post pekar på en
        existerande, korrekt sökväg. KRASCHSÄKER.

        Returns:
            True om posten är giltig (eller ingen post finns
            och inget förväntas)
        """
        try:
            expected = self.build_command()

            if IS_WINDOWS:
                current = self._win_registry_get()
                if current is not None:
                    return self._command_paths_valid(
                        current
                    ) and current.strip() == expected.strip()
                bat = self._win_bat_path()
                if bat.exists():
                    content = bat.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    return expected.strip() in content
                return False

            if IS_MACOS:
                plist = self._mac_plist_path()
                if not plist.exists():
                    return False
                content = plist.read_text(
                    encoding="utf-8", errors="replace"
                )
                return self._all_paths_in_text(content)

            if IS_LINUX:
                desktop = self._linux_desktop_path()
                if not desktop.exists():
                    return False
                content = desktop.read_text(
                    encoding="utf-8", errors="replace"
                )
                return (
                    f"Exec={expected}" in content
                    and self._command_paths_valid(expected)
                )

            return False
        except Exception as exc:
            _log.error("verify-fel: %s", exc)
            return False

    def get_status(self) -> Dict[str, Any]:
        """Diagnostik: aktuellt autostart-läge."""
        return {
            "version": VERSION,
            "platform": self._platform_name(),
            "app_name": self._app_name,
            "enabled": self.is_enabled(),
            "valid": self.verify(),
            "settings_startup": self._read_setting(),
            "command": self.build_command(),
            "base_dir": str(self._base_dir),
        }

    # ──────────────────────────────────────────────────────────────────
    # INSTALL / UNINSTALL (plattformsväxel)
    # ──────────────────────────────────────────────────────────────────

    def _install(self) -> bool:
        """Installera autostart-post. Tar bort dubbletter först."""
        # Inga dubbletter: rensa befintliga poster först
        self._uninstall()

        command = self.build_command()
        if not self._command_paths_valid(command):
            _log.error(
                "Vägrar installera autostart — ogiltig sökväg "
                "i kommandot: %s",
                command,
            )
            return False

        if IS_WINDOWS:
            if self._win_registry_set(command):
                return True
            _log.warning(
                "Registry nekades — använder .bat-fallback"
            )
            return self._win_bat_install(command)

        if IS_MACOS:
            return self._mac_plist_install()

        if IS_LINUX:
            return self._linux_desktop_install(command)

        _log.warning(
            "Okänd plattform '%s' — autostart stöds ej",
            sys.platform,
        )
        return False

    def _uninstall(self) -> None:
        """Ta bort ALLA autostart-poster (Registry + .bat etc.)."""
        if IS_WINDOWS:
            self._win_registry_delete()
            self._safe_unlink(self._win_bat_path())
        elif IS_MACOS:
            self._safe_unlink(self._mac_plist_path())
        elif IS_LINUX:
            self._safe_unlink(self._linux_desktop_path())

    # ──────────────────────────────────────────────────────────────────
    # WINDOWS: REGISTRY + .BAT-FALLBACK
    # ──────────────────────────────────────────────────────────────────

    def _win_registry_get(self) -> Optional[str]:
        """Läs Registry-värdet. None om saknas/fel."""
        if not _HAS_WINREG:
            return None
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY,
                0, winreg.KEY_READ,
            ) as key:
                value, _type = winreg.QueryValueEx(
                    key, self._app_name
                )
                return str(value)
        except FileNotFoundError:
            return None
        except Exception as exc:
            _log.debug("Registry-läsning fel: %s", exc)
            return None

    def _win_registry_set(self, command: str) -> bool:
        """Skriv Registry-värdet. KRASCHSÄKER."""
        if not _HAS_WINREG:
            return False
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY,
                0, winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key, self._app_name, 0,
                    winreg.REG_SZ, command,
                )
            _log.info(
                "Registry-autostart satt: %s = %s",
                self._app_name, command,
            )
            return True
        except Exception as exc:
            _log.warning("Registry-skrivning nekades: %s", exc)
            return False

    def _win_registry_delete(self) -> None:
        """Ta bort Registry-värdet. Ofarligt om det saknas."""
        if not _HAS_WINREG:
            return
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY,
                0, winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, self._app_name)
            _log.debug("Registry-autostart borttagen")
        except FileNotFoundError:
            pass
        except Exception as exc:
            _log.debug("Registry-borttagning fel: %s", exc)

    def _win_startup_dir(self) -> Path:
        """Användarens Startup-mapp (för .bat-fallback)."""
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return (
                Path(appdata)
                / "Microsoft" / "Windows" / "Start Menu"
                / "Programs" / "Startup"
            )
        return (
            Path.home()
            / "AppData" / "Roaming"
            / "Microsoft" / "Windows" / "Start Menu"
            / "Programs" / "Startup"
        )

    def _win_bat_path(self) -> Path:
        """Sökväg till fallback-.bat i Startup-mappen."""
        return self._win_startup_dir() / f"{self._app_name}.bat"

    def _win_bat_install(self, command: str) -> bool:
        """Skriv .bat-fallback (atomiskt). Startar UTAN fönster."""
        try:
            content = (
                "@echo off\r\n"
                f"rem {get_copyright_string()}\r\n"
                f"rem Autogenererad av AutostartManager "
                f"v{VERSION}\r\n"
                f'start "" {command}\r\n'
            )
            _atomic_write_text(self._win_bat_path(), content)
            _log.info(
                ".bat-autostart skriven: %s", self._win_bat_path(),
            )
            return True
        except Exception as exc:
            _log.error(".bat-fallback misslyckades: %s", exc)
            return False

    # ──────────────────────────────────────────────────────────────────
    # LINUX: XDG .DESKTOP
    # ──────────────────────────────────────────────────────────────────

    def _linux_desktop_path(self) -> Path:
        """Sökväg till ~/.config/autostart/<app>.desktop."""
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg else Path.home() / ".config"
        return base / "autostart" / f"{self._app_name}.desktop"

    def _linux_desktop_install(self, command: str) -> bool:
        """Skriv XDG Desktop Entry (atomiskt)."""
        try:
            app_display = self._read_app_display_name()
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={app_display}\n"
                f"Comment={get_copyright_string()}\n"
                f"Exec={command}\n"
                "Terminal=false\n"
                "Hidden=false\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
            _atomic_write_text(
                self._linux_desktop_path(), content
            )
            _log.info(
                ".desktop-autostart skriven: %s",
                self._linux_desktop_path(),
            )
            return True
        except Exception as exc:
            _log.error(".desktop-skrivning fel: %s", exc)
            return False

    # ──────────────────────────────────────────────────────────────────
    # MACOS: LAUNCHD .PLIST
    # ──────────────────────────────────────────────────────────────────

    def _mac_plist_path(self) -> Path:
        """Sökväg till ~/Library/LaunchAgents/<bundle>.plist."""
        return (
            Path.home() / "Library" / "LaunchAgents"
            / f"{self._bundle_id}.plist"
        )

    def _mac_plist_install(self) -> bool:
        """Skriv launchd-plist (atomiskt)."""
        try:
            if getattr(sys, "frozen", False):
                args = [str(Path(sys.executable).resolve())]
            else:
                args = [
                    self._find_interpreter(),
                    str(self._find_entry_script()),
                ]

            args_xml = "\n".join(
                f"        <string>{a}</string>" for a in args
            )
            content = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC '
                '"-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/'
                'PropertyList-1.0.dtd">\n'
                '<plist version="1.0">\n'
                "<dict>\n"
                "    <key>Label</key>\n"
                f"    <string>{self._bundle_id}</string>\n"
                "    <key>ProgramArguments</key>\n"
                "    <array>\n"
                f"{args_xml}\n"
                "    </array>\n"
                "    <key>RunAtLoad</key>\n"
                "    <true/>\n"
                "    <key>WorkingDirectory</key>\n"
                f"    <string>{self._base_dir}</string>\n"
                "</dict>\n"
                "</plist>\n"
            )
            _atomic_write_text(self._mac_plist_path(), content)
            _log.info(
                ".plist-autostart skriven: %s",
                self._mac_plist_path(),
            )
            return True
        except Exception as exc:
            _log.error(".plist-skrivning fel: %s", exc)
            return False

    # ──────────────────────────────────────────────────────────────────
    # KOMMANDO-BYGGE & VALIDERING
    # ──────────────────────────────────────────────────────────────────

    def _find_entry_script(self) -> Path:
        """
        Hitta entry-skriptet. Föredrar main.pyw (spec: ingen
        terminal), fallback main.py.
        """
        pyw = self._base_dir / "main.pyw"
        if pyw.exists():
            return pyw
        py = self._base_dir / "main.py"
        if py.exists():
            return py
        # Sista utväg — returnera förväntad pyw-sökväg
        # (verify() flaggar den som ogiltig tills filen finns)
        return pyw

    def _find_interpreter(self) -> str:
        """
        Hitta tolk som startar UTAN terminalfönster.
        Windows: pythonw.exe bredvid python.exe.
        POSIX: sys.executable (main.pyw + Terminal=false räcker).
        """
        exe = Path(sys.executable).resolve()
        if IS_WINDOWS:
            pythonw = exe.with_name("pythonw.exe")
            if pythonw.exists():
                return str(pythonw)
        return str(exe)

    def _command_paths_valid(self, command: str) -> bool:
        """
        Verifiera att alla citerade sökvägar i kommandot
        existerar (verify paths, auto-repair-underlag).
        """
        try:
            paths = self._extract_quoted_paths(command)
            if not paths:
                return False
            return all(Path(p).exists() for p in paths)
        except Exception:
            return False

    def _all_paths_in_text(self, text: str) -> bool:
        """macOS-plist: kontrollera att tolk + skript finns."""
        try:
            if getattr(sys, "frozen", False):
                return str(
                    Path(sys.executable).resolve()
                ) in text
            interp = self._find_interpreter()
            entry = str(self._find_entry_script())
            return (
                interp in text
                and entry in text
                and Path(interp).exists()
                and Path(entry).exists()
            )
        except Exception:
            return False

    @staticmethod
    def _extract_quoted_paths(command: str) -> list:
        """Plocka ut alla "..."-citerade sökvägar ur kommandot."""
        paths = []
        parts = command.split('"')
        # Udda index = innehåll mellan citattecken
        for i in range(1, len(parts), 2):
            if parts[i].strip():
                paths.append(parts[i].strip())
        return paths

    # ──────────────────────────────────────────────────────────────────
    # SETTINGS-INTEGRATION
    # ──────────────────────────────────────────────────────────────────

    def _read_setting(self) -> bool:
        """Läs 'startup' från settings (default False)."""
        if self._settings is None:
            return False
        try:
            getter = getattr(self._settings, "get", None)
            if callable(getter):
                return bool(getter(SETTINGS_KEY, False))
        except Exception as exc:
            _log.debug("Settings-läsning fel: %s", exc)
        return False

    def _save_setting(self, enabled: bool) -> None:
        """Skriv 'startup' till settings. Kraschsäker."""
        if self._settings is None:
            return
        try:
            setter = getattr(self._settings, "set", None)
            if callable(setter):
                setter(SETTINGS_KEY, bool(enabled))
        except Exception as exc:
            _log.debug("Settings-skrivning fel: %s", exc)

    def _read_app_display_name(self) -> str:
        """Visningsnamn till .desktop (från settings om möjligt)."""
        if self._settings is not None:
            try:
                getter = getattr(self._settings, "get", None)
                if callable(getter):
                    name = getter("app_name", "")
                    if name:
                        return str(name)
            except Exception:
                pass
        return "Transportstyrelsen Fordonsregistreringssystem"

    # ──────────────────────────────────────────────────────────────────
    # HJÄLPARE
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Sanera namn till säkra tecken."""
        cleaned = "".join(
            c if c.isalnum() or c in ("_", "-") else "_"
            for c in str(name).strip()
        )
        return cleaned or DEFAULT_APP_NAME

    @staticmethod
    def _platform_name() -> str:
        """Läsbart plattformsnamn."""
        if IS_WINDOWS:
            return "Windows"
        if IS_MACOS:
            return "macOS"
        if IS_LINUX:
            return "Linux"
        return sys.platform

    def _safe_unlink(self, path: Path) -> None:
        """Ta bort fil ofarligt."""
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            _log.debug("Kunde inte ta bort %s: %s", path, exc)

    def __repr__(self) -> str:
        return (
            f"<AutostartManager v{VERSION} "
            f"app={self._app_name} "
            f"platform={self._platform_name()} "
            f"enabled={self.is_enabled()}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "AutostartManager",
    "DEFAULT_APP_NAME",
    "DEFAULT_BUNDLE_ID",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]