"""Inga terminalfönster – varken vid start eller vid skanning.

Windows öppnar ett svart konsolfönster varje gång ``python.exe``, ``pip`` eller
``cmd`` startas. Det syns när appen startar, när paketen skannas efter
uppdateringar och när ett tillägg installeras. Här samlas de flaggor som gör
hjälpprocesserna helt osynliga, samt hjälpare för att starta appen med
``pythonw.exe`` (Python utan konsol) och för att dölja en konsol som redan
skapats av en genväg eller ett skript.

Modulen importerar aldrig Qt och kan därför användas redan i ``start.pyw``
innan beroendena är kontrollerade.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any

IS_WINDOWS = sys.platform == "win32"

# CREATE_NO_WINDOW hindrar Windows från att skapa en konsol för processen.
# Värdet finns inte i subprocess på alla Python-versioner, därför sätts det här.
CREATE_NO_WINDOW = 0x08000000
# DETACHED_PROCESS används medvetet inte: det kopplar bort ut- och indata.
SW_HIDE = 0


def startup_info() -> Any:
    """``STARTUPINFO`` som ber Windows att inte visa något fönster."""
    if not IS_WINDOWS:
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = SW_HIDE
    return info


def hidden_kwargs() -> dict[str, Any]:
    """Nyckelord till ``subprocess.run``/``Popen`` som ger en osynlig process.

    På andra plattformar än Windows returneras en tom dict, så anropet kan
    användas direkt i befintlig kod utan plattformskontroll på varje ställe.
    """
    if not IS_WINDOWS:
        return {}
    return {"creationflags": CREATE_NO_WINDOW, "startupinfo": startup_info()}


def merged(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Lägg till de osynliga flaggorna utan att skriva över anroparens val."""
    options = dict(kwargs)
    for key, value in hidden_kwargs().items():
        options.setdefault(key, value)
    return options


def gui_executable() -> str:
    """Returnera ``pythonw.exe`` när det finns, annars nuvarande tolk.

    ``pythonw.exe`` startar Python utan konsol. Det är den tolk genvägar,
    autostart och uppdateraren ska använda så att inget terminalfönster syns.
    """
    if IS_WINDOWS:
        try:
            exe = Path(sys.executable)
            pythonw = exe.with_name("pythonw.exe")
            if pythonw.is_file():
                return str(pythonw)
        except (OSError, ValueError):
            pass
    return sys.executable


def pythonw_or_none() -> str | None:
    """``pythonw.exe`` om det finns, annars ``None`` (används av startfilerna)."""
    if not IS_WINDOWS:
        return None
    try:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.is_file():
            return str(pythonw)
    except (OSError, ValueError):
        pass
    return None


def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """``subprocess.run`` utan terminalfönster."""
    return subprocess.run(command, **merged(kwargs))


def popen(command: list[str], **kwargs: Any) -> subprocess.Popen:
    """``subprocess.Popen`` utan terminalfönster."""
    return subprocess.Popen(command, **merged(kwargs))


def hide_console_window() -> bool:
    """Dölj ett konsolfönster som redan finns (t.ex. från ``python.exe``).

    Returnerar ``True`` om ett fönster faktiskt doldes. Anropas tidigt i
    starten, före Qt, så att ingen terminal hinner synas.
    """
    if not IS_WINDOWS:
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        handle = kernel32.GetConsoleWindow()
        if not handle:
            return False
        # Fönstret kan höra till en annan process (t.ex. en förälderterminal);
        # bara det egna konsolfönstret döljs, aldrig en förälders.
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value not in (0, os.getpid()):
            return False
        user32.ShowWindow(handle, SW_HIDE)
        return True
    except Exception:
        return False


def default_creation_flags() -> int:
    """Flaggor för ``Popen`` där anroparen själv bygger kommandot."""
    return CREATE_NO_WINDOW if IS_WINDOWS else 0
