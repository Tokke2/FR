"""Veckoschema för kontroll av Python-tillägg, utan att starta någon systemtjänst."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile

from core.error_summary import _process_lock, _reject_link

STATE_NAME = 'python_underhall.json'


def scheduled_slot(now: datetime) -> datetime:
    """Senaste måndag kl. 08 enligt datorns lokala tid."""
    monday = (now - timedelta(days=now.weekday())).replace(hour=8, minute=0, second=0, microsecond=0)
    return monday if now >= monday else monday - timedelta(days=7)


def claim_due(log_dir: Path, now: datetime | None = None) -> bool:
    """Reservera periodens enda kontroll, även om en senare kontroll misslyckas.

    Misslyckad tillståndsläsning/skrivning kastar fel i stället för att köra
    underhåll flera gånger. Ett processlås hanterar samtidiga appstarter.
    """
    now = now or datetime.now()
    slot = scheduled_slot(now)
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / STATE_NAME
    with _process_lock(log_dir / '.python_underhall.lock'):
        _reject_link(path)
        if path.exists():
            if path.stat().st_size > 4096:
                raise ValueError('Veckokontrollens statusfil är för stor')
            state = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(state, dict) or state.get('schema') != 1:
                raise ValueError('Veckokontrollens statusfil är ogiltig')
            previous = datetime.fromisoformat(state['slot'])
            if previous.tzinfo is not None or scheduled_slot(previous) != previous:
                raise ValueError('Veckokontrollens tidsstämpel är ogiltig')
            if previous >= slot:
                return False
        state = {'schema': 1, 'slot': slot.isoformat(), 'attempted_at': now.isoformat(timespec='seconds')}
        fd, temp = tempfile.mkstemp(prefix='.python_underhall-', dir=log_dir)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump(state, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            _reject_link(path)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return True
