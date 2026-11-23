"""Säker lokal lagring av återförsäljare, utan beroende av Qt."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading

_lock = threading.RLock()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise


class DealerStorage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.backup_dir = self.path.parent / 'backup_aterforsaljare'

    def _read_bytes(self) -> bytes | None:
        if self.path.is_symlink():
            raise ValueError('Återförsäljarfilen får inte vara en symbolisk länk')
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return None

    @staticmethod
    def _decode(content: bytes | None) -> list[dict]:
        if content is None:
            return []
        text = content.decode('utf-8-sig')
        payload = '\n'.join(line for line in text.splitlines()
                            if not line.lstrip().startswith(('//', '#'))).strip()
        if not payload:
            raise ValueError('Återförsäljarfilen är tom eller saknar JSON')
        raw = json.loads(payload)
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
            raise ValueError('Återförsäljarfilen innehåller ett ogiltigt format eller ogiltiga poster')
        return raw

    def snapshot(self) -> tuple[list[dict], bytes | None]:
        with _lock:
            content = self._read_bytes()
            return self._decode(content), content

    def save(self, records: list[dict], expected: bytes | None) -> None:
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise ValueError('Alla återförsäljarposter måste vara objekt')
        content = (json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
        with _lock:
            current = self._read_bytes()
            self._decode(current)  # Vägra skriva över oläsbar data.
            if current != expected:
                raise ValueError('Återförsäljarfilen har ändrats sedan den lästes. Uppdatera och försök igen.')
            # Kopiera även första versionen innan en ny fil skapas.
            backup = current if current is not None else content
            if self.backup_dir.is_symlink():
                raise ValueError('Säkerhetskopiekatalogen får inte vara en symbolisk länk')
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            fd, name = tempfile.mkstemp(prefix=f'aterforsaljare-{stamp}-', suffix='.json', dir=self.backup_dir)
            target = Path(name)
            try:
                with os.fdopen(fd, 'wb') as out:
                    out.write(backup)
                    out.flush()
                    os.fsync(out.fileno())
                if target.read_bytes() != backup or self._read_bytes() != expected:
                    raise OSError('Säkerhetskopian eller originalfilen kunde inte verifieras')
            except BaseException:
                try:
                    target.unlink()
                except OSError:
                    pass
                raise
            _atomic_write(self.path, content)
