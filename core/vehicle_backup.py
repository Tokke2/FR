"""Kopiera befintlig årsdata innan den ändras, separat från programuppdateringar."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import tempfile


def backup_new_year(content: bytes, backup_root: Path, year: int) -> Path:
    """Säkra första versionen innan en ny årsfil skapas."""
    backup_root = Path(backup_root)
    if backup_root.is_symlink():
        raise ValueError('Säkerhetskopians katalog får inte vara en symbolisk länk')
    backup_root.mkdir(parents=True, exist_ok=True)
    year_dir = backup_root / str(year)
    if year_dir.is_symlink():
        raise ValueError('Årets säkerhetskopiekatalog får inte vara en symbolisk länk')
    year_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    fd, name = tempfile.mkstemp(prefix=f'{year}-{stamp}-', suffix='.json', dir=str(year_dir))
    target = Path(name)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if target.read_bytes() != content:
            raise OSError('Säkerhetskopian kunde inte verifieras')
        return target
    except Exception:
        try:
            target.unlink()
        except OSError:
            pass
        raise


def backup_year(source: Path, backup_root: Path, year: int) -> Path:
    """Spara en exakt kopia av en befintlig årsfil; misslyckas hellre än att skriva över utan backup."""
    source = Path(source)
    backup_root = Path(backup_root)
    if source.is_symlink():
        raise ValueError('Årsfilen är en symbolisk länk och kan inte säkerhetskopieras')
    if backup_root.is_symlink():
        raise ValueError('Säkerhetskopians katalog får inte vara en symbolisk länk')
    backup_root.mkdir(parents=True, exist_ok=True)
    if not backup_root.is_dir():
        raise ValueError('Säkerhetskopians katalog är inte en katalog')
    year_dir = backup_root / str(year)
    if year_dir.is_symlink():
        raise ValueError('Årets säkerhetskopiekatalog får inte vara en symbolisk länk')
    year_dir.mkdir(exist_ok=True)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    src = os.open(source, flags)
    target = None
    try:
        before = os.fstat(src)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Årsfilen är inte en vanlig fil')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        fd, name = tempfile.mkstemp(prefix=f'{year}-{stamp}-', suffix='.json', dir=str(year_dir))
        target = Path(name)
        with os.fdopen(fd, 'wb') as output:
            while True:
                chunk = os.read(src, 1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        after = os.fstat(src)
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise OSError('Årsfilen ändrades under säkerhetskopieringen')
        # Återläs båda kopior för att kontrollera att säkerhetskopian är exakt.
        os.lseek(src, 0, os.SEEK_SET)
        with target.open('rb') as copied:
            while True:
                original = os.read(src, 1024 * 1024)
                if copied.read(1024 * 1024) != original:
                    raise OSError('Säkerhetskopian kunde inte verifieras')
                if not original:
                    break
        final = os.fstat(src)
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (final.st_size, final.st_mtime_ns, final.st_ino):
            raise OSError('Årsfilen ändrades under säkerhetskopieringen')
        return target
    except Exception:
        if target is not None:
            try:
                target.unlink()
            except OSError:
                pass
        raise
    finally:
        os.close(src)
