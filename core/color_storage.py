"""Försiktig lagring av färgregister och mappningar, en fil åt gången."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading

_LOCK = threading.RLock()


def read_snapshot(path: Path) -> bytes | None:
    if path.is_symlink():
        raise ValueError(f'{path.name} får inte vara en symbolisk länk')
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def decode_snapshot(raw: bytes | None, default):
    if raw is None:
        return default
    text = raw.decode('utf-8-sig')
    content = '\n'.join(line for line in text.splitlines()
                        if not line.lstrip().startswith(('//', '#'))).strip()
    if not content:
        raise ValueError('Filen är tom eller saknar JSON')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"JSON innehåller en dubblerad nyckel: {key}")
            result[key] = value
        return result
    return json.loads(content, object_pairs_hook=unique_object)


def save_snapshot(path: Path, expected: bytes | None, payload, *, other_path: Path, other_expected: bytes | None, backup_dir_name: str = "backup_farger"):
    """Verifiera båda filerna, säkerhetskopiera originalet och ersätt en fil atomiskt."""
    comments = [] if expected is None else [line for line in expected.decode('utf-8-sig').splitlines()
                                           if line.lstrip().startswith(('//', '#'))]
    content = (('\n'.join(comments) + '\n' if comments else '')
               + json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    with _LOCK:
        if read_snapshot(path) != expected or read_snapshot(other_path) != other_expected:
            raise ValueError('Färgdata har ändrats sedan den lästes. Uppdatera och försök igen.')
        backup_dir = path.parent / backup_dir_name
        if backup_dir.is_symlink():
            raise ValueError('Säkerhetskopiekatalogen får inte vara en symbolisk länk')
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        fd, name = tempfile.mkstemp(prefix=f'{path.stem}-{stamp}-', suffix='.json', dir=backup_dir)
        backup = Path(name)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(expected if expected is not None else content)
                out.flush(); os.fsync(out.fileno())
            if (backup.read_bytes() != (expected if expected is not None else content)
                    or read_snapshot(path) != expected or read_snapshot(other_path) != other_expected):
                raise OSError('Säkerhetskopian eller originalfilerna kunde inte verifieras')
        except BaseException:
            try: backup.unlink()
            except OSError: pass
            raise
        fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(content); out.flush(); os.fsync(out.fileno())
            if read_snapshot(path) != expected or read_snapshot(other_path) != other_expected:
                raise ValueError('Färgdata har ändrats under sparning. Försök igen.')
            os.replace(name, path)
        finally:
            if os.path.exists(name): os.unlink(name)
    return content
