"""Skapa genväg till Fordonsreg på uttrycklig begäran, utan filassociationer."""
from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from core.no_console import hidden_kwargs


class ShortcutError(Exception):
    pass


def _desktop_directory(platform: str) -> Path:
    if platform.startswith("win"):
        # Windows känner till om skrivbordet flyttats, t.ex. till OneDrive.
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(32768)
            result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
            if result == 0 and buf.value:
                return Path(buf.value)
        except Exception as exc:
            raise ShortcutError("Kunde inte hitta Windows skrivbord") from exc
        raise ShortcutError("Kunde inte hitta Windows skrivbord")
    if platform.startswith("linux"):
        try:
            result = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, **hidden_kwargs(),
                                    text=True, encoding="utf-8", errors="replace", timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
        return Path.home() / "Desktop"
    raise ShortcutError("Skrivbordsgenväg stöds här bara på Windows och Linux")


def _desktop_arg(value: str) -> str:
    # Desktop Entry Exec har andra regler än ett POSIX-skal. % är fältkod.
    if any(ord(char) < 32 for char in value):
        raise ShortcutError("Sökvägen innehåller otillåtna kontrolltecken")
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'


def _desktop_value(value: str) -> str:
    if any(ord(char) < 32 for char in value):
        raise ShortcutError("Sökvägen innehåller otillåtna kontrolltecken")
    return value.replace('\\', '\\\\')


def read_windows_shortcut(target: Path) -> dict[str, str]:
    """Läs egenskaperna utan att köra eller ändra genvägen."""
    env = dict(os.environ, FR_SHORTCUT=str(target))
    command = ("$ErrorActionPreference='Stop'; "
               "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
               "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:FR_SHORTCUT); "
               "@{target=$s.TargetPath; arguments=$s.Arguments; icon=$s.IconLocation; "
               "directory=$s.WorkingDirectory; description=$s.Description} | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=30, **hidden_kwargs())
        if result.returncode:
            raise ShortcutError("Kunde inte läsa Windowsgenvägen")
        details = json.loads(result.stdout.lstrip("\ufeff"))
        if not isinstance(details, dict):
            raise ValueError("invalid shortcut properties")
        return details
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise ShortcutError("Kunde inte läsa Windowsgenvägen") from exc


def write_windows_shortcut(target: Path, executable: Path, script: Path | None,
                           root: Path, icon: Path, description: str, *, replace: bool = False,
                           validator=None, replace_guard=None) -> None:
    """Skapa komplett .lnk temporärt och installera den atomiskt."""
    if not icon.is_file():
        raise ShortcutError("Programikonen ikon.ico saknas")
    if not replace and (target.exists() or target.is_symlink()):
        raise ShortcutError(f"Genvägen finns redan och skrevs inte över: {target}")
    try:
        with tempfile.TemporaryDirectory(prefix=".fordonsreg-", dir=target.parent) as temp:
            temporary = Path(temp) / "Fordonsreg.lnk"
            env = dict(os.environ, FR_SHORTCUT=str(temporary), FR_PYTHON=str(executable),
                       FR_SCRIPT=str(script) if script else "", FR_ROOT=str(root), FR_ICON=str(icon),
                       FR_DESCRIPTION=description)
            command = ("$ErrorActionPreference='Stop'; "
                       "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:FR_SHORTCUT); "
                       "$s.TargetPath=$env:FR_PYTHON; "
                       "if ($env:FR_SCRIPT) { $s.Arguments='\"' + $env:FR_SCRIPT.Replace('\"','') + '\"' }; "
                       "$s.WorkingDirectory=$env:FR_ROOT; $s.IconLocation=$env:FR_ICON + ',0'; "
                       "$s.Description=$env:FR_DESCRIPTION; $s.Save()")
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                    env=env, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=30, **hidden_kwargs())
            if result.returncode or not temporary.is_file():
                raise ShortcutError("Kunde inte skapa Windowsgenvägen. Kontrollera behörigheten.")
            if validator is not None and not validator(temporary):
                raise ShortcutError("Den nya Windowsgenvägen kunde inte verifieras")
            if replace:
                if replace_guard is not None and not replace_guard():
                    raise ShortcutError("Genvägen ändrades under kontrollen och lämnades orörd")
                os.replace(temporary, target)
            else:
                os.link(temporary, target)  # atomiskt och utan överskrivning
    except FileExistsError as exc:
        raise ShortcutError(f"Genvägen finns redan och skrevs inte över: {target}") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ShortcutError("Kunde inte skapa Windowsgenvägen") from exc


def create_desktop_shortcut(root: Path, *, desktop: Path | None = None,
                            platform: str | None = None, executable: str | None = None) -> Path:
    """Skapa ny genväg. Ersätter aldrig en befintlig fil eller ändrar Windows filtyper."""
    platform = sys.platform if platform is None else platform
    root = Path(root).resolve()
    desktop = Path(desktop) if desktop is not None else _desktop_directory(platform)
    if not desktop.is_dir():
        raise ShortcutError(f"Skrivbordskatalogen finns inte: {desktop}")
    script = root / "start.pyw"
    if not script.is_file():
        raise ShortcutError("Startfilen start.pyw saknas")
    exe = Path(executable or sys.executable).resolve()
    if not exe.is_file():
        raise ShortcutError("Python som ska starta programmet finns inte")
    if platform.startswith("win"):
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.is_file():
            exe = pythonw
        icon = root / "ikon.ico"
        if not icon.is_file():
            raise ShortcutError("Programikonen ikon.ico saknas")
        target = desktop / "Fordonsreg.lnk"
        if target.exists() or target.is_symlink():
            raise ShortcutError(f"Genvägen finns redan och skrevs inte över: {target}")
        write_windows_shortcut(target, exe, script, root, icon, "Fordonsreg")
        return target
    if platform.startswith("linux"):
        icon = root / "ikon_256.png"
        if not icon.is_file():
            raise ShortcutError("Programikonen ikon_256.png saknas")
        target = desktop / "Fordonsreg.desktop"
        content = ("[Desktop Entry]\nType=Application\nName=Fordonsreg\n"
                   f"Exec={_desktop_arg(str(exe))} {_desktop_arg(str(script))}\n"
                   f"Path={_desktop_value(str(root))}\nIcon={_desktop_value(str(icon))}\n"
                   "Terminal=false\nCategories=Office;\n")
        try:
            # O_EXCL skyddar befintliga genvägar och symlänkar mot överskrivning.
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        except FileExistsError as exc:
            raise ShortcutError(f"Genvägen finns redan och skrevs inte över: {target}") from exc
        except OSError as exc:
            raise ShortcutError(f"Kunde inte skapa genvägen: {exc}") from exc
        return target
    raise ShortcutError("Skrivbordsgenväg stöds här bara på Windows och Linux")
