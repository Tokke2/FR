"""Gemensam fellogg för app, startkontroll och uppdateringsprocess.

Alla processer låser samma separata låsfil inför skrivning och rotation. Inga
filhandtag till själva loggen hålls öppna mellan poster, vilket även fungerar
när en annan process roterar den på Windows.
"""
from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import stat
import sys
import time

SUMMARY_NAME = "felsokning.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 3
_MARKER = "_fordonsreg_summary_written"


@contextmanager
def _process_lock(path: Path):
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    if path.is_symlink():
        raise OSError("Felsökningsloggens låsfil får inte vara en symbolisk länk")
    fd = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("Felsökningsloggens låsfil är inte en vanlig fil")
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            deadline = time.monotonic() + 10.0
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.025)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _reject_link(path: Path) -> None:
    if path.is_symlink():
        raise OSError(f"Felsökningsloggen får inte skriva till symbolisk länk: {path}")
    if path.exists() and not path.is_file():
        raise OSError(f"Felsökningsloggen är inte en vanlig fil: {path}")


def _ensure_log(log_dir: Path) -> None:
    """Gör den tomma felloggen synlig redan före det första felet."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / SUMMARY_NAME
    with _process_lock(log_dir / ".felsokning.lock"):
        _reject_link(path)
        flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("Felsökningsloggen är inte en vanlig fil")
        finally:
            os.close(fd)


def _append(log_dir: Path, message: str, max_bytes: int, backups: int) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / SUMMARY_NAME
    data = (message.rstrip("\n") + "\n").encode("utf-8", errors="backslashreplace")
    with _process_lock(log_dir / ".felsokning.lock"):
        _reject_link(path)
        # Kontrollera alla rotationsmål före första ändringen.
        targets = [log_dir / f"{SUMMARY_NAME}.{n}" for n in range(1, backups + 1)]
        for target in targets:
            _reject_link(target)
        if backups and path.exists() and path.stat().st_size > 0 and path.stat().st_size + len(data) > max_bytes:
            for n in range(backups, 1, -1):
                source = log_dir / f"{SUMMARY_NAME}.{n - 1}"
                if source.exists():
                    os.replace(source, log_dir / f"{SUMMARY_NAME}.{n}")
            os.replace(path, targets[0])
        flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("Felsökningsloggen är inte en vanlig fil")
            view = memoryview(data)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise OSError("Kunde inte skriva felsökningsloggen")
                view = view[count:]
        finally:
            os.close(fd)


class ErrorSummaryHandler(logging.Handler):
    """Skriv WARNING+ en gång per loggpost, inklusive traceback och källa."""

    _fordonsreg_summary_handler = True

    def __init__(self, log_dir: Path, origin: str, *, max_bytes: int = MAX_BYTES, backups: int = BACKUPS):
        super().__init__(level=logging.WARNING)
        self.log_dir = Path(log_dir)
        self.origin = origin
        self.max_bytes = max_bytes
        self.backups = backups
        try:
            _ensure_log(self.log_dir)
        except OSError as exc:
            # Felsökningsloggen får inte hindra själva programmet från att starta.
            try:
                sys.stderr.write(f"Kunde inte skapa {SUMMARY_NAME}: {exc}\n")
            except Exception:
                pass
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(summary_origin)s] [pid=%(process)d] "
            "[%(name)s] (%(filename)s:%(lineno)d) %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        target = os.path.normcase(os.path.abspath(self.log_dir / SUMMARY_NAME))
        written = getattr(record, _MARKER, None)
        if written is not None and target in written:
            return
        try:
            # Kopiera posten så att övriga handlers inte påverkas av formateringen.
            copied = logging.makeLogRecord(record.__dict__.copy())
            copied.summary_origin = self.origin
            _append(self.log_dir, self.format(copied), self.max_bytes, self.backups)
            if written is None:
                written = set()
                setattr(record, _MARKER, written)
            written.add(target)
        except Exception:
            # Den vanliga kategoriloggen fortsätter även om sammanställningen misslyckas.
            self.handleError(record)
