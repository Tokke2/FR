"""Läsning av den gemensamma felloggen utan att ändra dess innehåll."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import stat

from core.error_summary import ErrorSummaryHandler, SUMMARY_NAME, _process_lock

MAX_DISPLAY_BYTES = 2 * 1024 * 1024


def current_summary_path() -> Path:
    """Följ appens aktiva loggkatalog."""
    for handler in reversed(logging.getLogger().handlers):
        if isinstance(handler, ErrorSummaryHandler):
            return (handler.log_dir / SUMMARY_NAME).absolute()
    raise RuntimeError("Ingen aktiv felsökningslogg hittades i appens loggning")


def read_log_tail(path: Path, max_bytes: int = MAX_DISPLAY_BYTES) -> tuple[str, bool]:
    """Läs högst max_bytes från slutet; returnera text och trunkeringsflagga.

    Samma lås som skrivaren skyddar mot att loggen roteras under läsningen.
    Inga loggposter ändras och symboliska länkar följs inte.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes måste vara större än noll")
    path = Path(path)
    if path.is_symlink():
        raise OSError("Loggfilen är en symbolisk länk och kan inte öppnas här")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"Loggmappen saknas: {path.parent}")
    # Felkodsregistret skrivs atomiskt under ett eget processlås.
    lock_name = ".felkoder.lock" if path.name == "felkoder.json" else ".felsokning.lock"
    with _process_lock(path.parent / lock_name):
        if path.is_symlink():
            raise OSError("Loggfilen är en symbolisk länk och kan inte öppnas här")
        flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                 | getattr(os, "O_NONBLOCK", 0))
        fd = os.open(path, flags)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise OSError("Loggfilen är inte en vanlig fil")
            truncated = st.st_size > max_bytes
            os.lseek(fd, max(0, st.st_size - max_bytes), os.SEEK_SET)
            chunks = []
            remaining = max_bytes
            while remaining:
                chunk = os.read(fd, min(remaining, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks).decode("utf-8", errors="replace"), truncated
        finally:
            os.close(fd)
