# -*- coding: utf-8 -*-
# core/autostart.py
"""
AutostartManager v1.0.0 — OS-specifik autostart.

Transportstyrelsen Fordonsregistreringssystem.

ANSVAR:
    - Aktivera/inaktivera autostart vid OS-inloggning:
        * Windows: Fordonsreg-genväg med ikon i Startup-mappen.
          Äldre Registry- och .bat-poster migreras efter verifiering.
        * Linux: ~/.config/autostart/<app>.desktop (XDG Desktop Entry).
        * macOS: ~/Library/LaunchAgents/<bundle_id>.plist (launchd).
    - verify(): kontrollera sökvägar och ikon; reparera egna poster.
    - sync(): körs vid app-start — synkar OS-läget mot
      settings.json-nyckeln "startup" (settings är source of
      truth) och auto-reparerar trasiga poster

API (spec Sektion D):
    AutostartManager.is_enabled()       -> bool
    AutostartManager.set_enabled(bool)  -> bool
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
    - Vid fel bevaras tidigare autostart i möjligaste mån
    - Saknade kataloger skapas vid behov
    - Filskrivning atomisk (mkstemp -> fsync -> os.replace)

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
import os
import plistlib
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
                        or self._win_shortcut_owned()
                    )
                if IS_MACOS:
                    return self._mac_plist_path().exists()
                if IS_LINUX:
                    return self._linux_desktop_path().exists()
                return False
            except Exception as exc:
                _log.error("is_enabled-fel: %s", exc)
                return False

    def set_enabled(self, enabled: bool) -> bool:
        """Ändra autostart och spara inställningen först när åtgärden lyckas."""
        with self._lock:
            try:
                if enabled:
                    ok = self._install()
                else:
                    removed = self._uninstall()
                    ok = removed is not False and not self.is_enabled()
                if ok:
                    self._save_setting(enabled)
                    _log.info("Autostart %s", "aktiverad" if enabled else "inaktiverad")
                else:
                    _log.error("Autostart kunde inte ändras; tidigare inställning bevaras")
                return ok
            except Exception:
                _log.exception("set_enabled(%s) misslyckades", enabled)
                return False

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
                        # Ersätt posten först när den nya är klar.
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
                # Den gamla Registry-/bat-varianten behöver migreras även om
                # kommandot fortfarande fungerar, annars visas Python-ikonen.
                return (self._win_registry_get() is None
                        and not self._win_bat_path().exists()
                        and self._win_shortcut_matches()
                        and self._command_paths_valid(expected))

            if IS_MACOS:
                plist = self._mac_plist_path()
                if not plist.exists():
                    return False
                info = plistlib.loads(plist.read_bytes())
                expected_args = ([str(Path(sys.executable).resolve())]
                                 if getattr(sys, "frozen", False) else
                                 [self._find_interpreter(), str(self._find_entry_script())])
                return (info.get("ProgramArguments") == expected_args
                        and info.get("WorkingDirectory") == str(self._base_dir)
                        and all(Path(arg).exists() for arg in expected_args))

            if IS_LINUX:
                desktop = self._linux_desktop_path()
                if not desktop.exists():
                    return False
                content = desktop.read_text(
                    encoding="utf-8", errors="replace"
                )
                icon_path = self._base_dir / "ikon_256.png"
                return (
                    f"Name={self._desktop_value(self._read_app_display_name())}\n" in content
                    and f"Exec={expected}" in content
                    and f"Path={self._desktop_value(str(self._base_dir))}" in content
                    and icon_path.is_file()
                    and f"Icon={self._desktop_value(str(icon_path))}" in content
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
        """Installera autostart-post; Windows migreras utan att först radera den gamla."""
        command = self.build_command()
        if not self._command_paths_valid(command):
            _log.error(
                "Vägrar installera autostart — ogiltig sökväg "
                "i kommandot: %s",
                command,
            )
            return False

        if IS_WINDOWS:
            return self._win_shortcut_install()

        if IS_MACOS:
            return self._mac_plist_install()

        if IS_LINUX:
            return self._linux_desktop_install(command)

        _log.warning(
            "Okänd plattform '%s' — autostart stöds ej",
            sys.platform,
        )
        return False

    def _uninstall(self) -> bool:
        """Ta bort egna poster, men lämna okända eller oläsbara genvägar orörda."""
        if IS_WINDOWS:
            ok = self._win_registry_delete()
            bat = self._win_bat_path()
            self._safe_unlink(bat)
            ok = ok and not bat.exists()
            path = self._win_shortcut_path()
            if path.exists() or path.is_symlink():
                details = self._win_shortcut_details()
                if details is None:
                    _log.error("Kan inte kontrollera autostartgenvägen; lämnar den orörd")
                    return False
                if details.get("description") == "Fordonsreg autostart":
                    self._safe_unlink(path)
                    ok = ok and not (path.exists() or path.is_symlink())
            return ok
        if IS_MACOS:
            self._safe_unlink(self._mac_plist_path())
            return not self._mac_plist_path().exists()
        if IS_LINUX:
            self._safe_unlink(self._linux_desktop_path())
            return not self._linux_desktop_path().exists()
        return False

    # ──────────────────────────────────────────────────────────────────
    # WINDOWS: GENVÄG OCH MIGRERING AV ÄLDRE AUTOSTART
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

    def _win_registry_delete(self) -> bool:
        """Ta bort Registry-värdet. Ofarligt om det saknas."""
        if not _HAS_WINREG:
            return True
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY,
                0, winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, self._app_name)
            _log.debug("Registry-autostart borttagen")
            return True
        except FileNotFoundError:
            return True
        except Exception as exc:
            _log.warning("Registry-borttagning fel: %s", exc)
            return False

    def _win_startup_dir(self) -> Path:
        """Användarens Startup-mapp."""
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
        """Sökväg till tidigare fallback-.bat."""
        return self._win_startup_dir() / f"{self._app_name}.bat"

    def _win_shortcut_path(self) -> Path:
        return self._win_startup_dir() / "Fordonsreg autostart.lnk"

    def _win_shortcut_details(self) -> Optional[Dict[str, str]]:
        path = self._win_shortcut_path()
        if path.is_symlink() or not path.is_file():
            return None
        try:
            from core.desktop_shortcut import read_windows_shortcut
            return read_windows_shortcut(path)
        except Exception as exc:
            _log.warning("Kunde inte läsa autostartgenvägen: %s", exc)
            return None

    def _win_shortcut_owned(self) -> bool:
        details = self._win_shortcut_details()
        return bool(details and details.get("description") == "Fordonsreg autostart")

    def _win_shortcut_matches(self, details: Optional[Dict[str, str]] = None) -> bool:
        if details is None:
            details = self._win_shortcut_details()
        if not details or details.get("description") != "Fordonsreg autostart":
            return False
        exe = str(Path(sys.executable).resolve()) if getattr(sys, "frozen", False) else self._find_interpreter()
        arguments = "" if getattr(sys, "frozen", False) else f'"{self._find_entry_script()}"'
        icon = self._base_dir / "ikon.ico"
        def same_path(actual: str, expected: str) -> bool:
            return os.path.normcase(os.path.normpath(actual)) == os.path.normcase(os.path.normpath(expected))
        return (icon.is_file()
                and same_path(details.get("target", ""), exe)
                and details.get("arguments", "") == arguments
                and same_path(details.get("directory", ""), str(self._base_dir))
                and same_path(details.get("icon", ""), str(icon) + ",0"))

    def _win_shortcut_install(self) -> bool:
        """Skapa genväg först; rensa gamla startposter endast om det lyckas."""
        from core.desktop_shortcut import read_windows_shortcut, write_windows_shortcut
        path = self._win_shortcut_path()
        try:
            details = self._win_shortcut_details()
            exists = path.exists() or path.is_symlink()
            if exists and (not details or details.get("description") != "Fordonsreg autostart"):
                _log.error("Okänd genväg finns redan och lämnas orörd: %s", path)
                return False
            if not self._win_shortcut_matches(details):
                previous = path.read_bytes() if exists else None
                path.parent.mkdir(parents=True, exist_ok=True)
                frozen = getattr(sys, "frozen", False)
                exe = Path(sys.executable).resolve() if frozen else Path(self._find_interpreter())
                script = None if frozen else self._find_entry_script()
                write_windows_shortcut(path, exe, script, self._base_dir,
                                       self._base_dir / "ikon.ico", "Fordonsreg autostart",
                                       replace=exists,
                                       validator=lambda temp: self._win_shortcut_matches(read_windows_shortcut(temp)),
                                       replace_guard=lambda: (not path.is_symlink()
                                                              and path.is_file()
                                                              and path.read_bytes() == previous))
            # Rör inte gamla poster om skapande/verifiering misslyckades.
            if self._win_registry_get() is not None and not self._win_registry_delete():
                _log.error("Kunde inte ta bort tidigare autostart i Registry")
                if not exists:
                    self._safe_unlink(path)
                return False
            bat = self._win_bat_path()
            self._safe_unlink(bat)
            if bat.exists():
                _log.error("Kunde inte ta bort tidigare autostartfil: %s", bat)
                if not exists:
                    self._safe_unlink(path)
                return False
            return True
        except Exception:
            _log.exception("Kunde inte skapa Fordonsregs autostartgenväg")
            return False

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

    @staticmethod
    def _desktop_value(value: str) -> str:
        """Escape XDG Desktop Entry string values."""
        return (value.replace("\\", "\\\\").replace("\n", "\\n")
                .replace("\r", "\\r").replace("\t", "\\t"))

    def _linux_desktop_install(self, command: str) -> bool:
        """Skriv XDG Desktop Entry (atomiskt)."""
        try:
            app_display = self._read_app_display_name()
            icon_path = self._base_dir / "ikon_256.png"
            if not icon_path.is_file():
                _log.error("Programikonen saknas; befintlig autostart bevaras")
                return False
            icon_line = f"Icon={self._desktop_value(str(icon_path))}\n"
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={self._desktop_value(app_display)}\n"
                f"Comment={get_copyright_string()}\n"
                f"Exec={command}\n"
                f"Path={self._desktop_value(str(self._base_dir))}\n"
                f"{icon_line}"
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
        """Skriv en korrekt escapad launchd-plist atomiskt."""
        try:
            if getattr(sys, "frozen", False):
                args = [str(Path(sys.executable).resolve())]
            else:
                args = [self._find_interpreter(), str(self._find_entry_script())]
            content = plistlib.dumps({
                "Label": self._bundle_id,
                "ProgramArguments": args,
                "RunAtLoad": True,
                "WorkingDirectory": str(self._base_dir),
            }).decode("utf-8")
            _atomic_write_text(self._mac_plist_path(), content)
            _log.info(".plist-autostart skriven: %s", self._mac_plist_path())
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
        # Startfilen kan erbjuda installation innan Qt importeras.
        launcher = self._base_dir / "start.pyw"
        if launcher.exists():
            return launcher
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
                        from core.branding import display_name
                        return display_name(name)
            except Exception:
                pass
        return "Fordonsreg"

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