"""Datumstyrd loggkopia och beständigt register för explicita programfelkoder.

Endast loggposter som faktiskt når handlern kan fångas. Filer från ett tidigare
loggsystem ändras inte. Fel utan verifierbar lösning förblir aktiva.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading

from core.error_summary import _process_lock, _reject_link

DAILY_DIR = "dagliga"
ARCHIVE_DIR = "arkiv"
CODES_FILE = "felkoder.json"
_DATE_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.log$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")
_DAILY_MARKER = "_fordonsreg_daily_written"
_CODE_MARKER = "_fordonsreg_codes_written"


def _directory(parent: Path, name: str) -> Path:
    path = parent / name
    if path.is_symlink():
        raise OSError(f"Loggkatalogen får inte vara en symbolisk länk: {path}")
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise OSError(f"Loggkatalogen är inte en katalog: {path}")
    return path


def _append_file(path: Path, data: bytes) -> None:
    _reject_link(path)
    flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags, 0o600)
    try:
        import stat
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"Loggen är inte en vanlig fil: {path}")
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            if n <= 0:
                raise OSError('Kunde inte skriva loggposten')
            view = view[n:]
    finally:
        os.close(fd)


def _archive_locked(log_dir: Path, today: date) -> None:
    daily = _directory(log_dir, DAILY_DIR)
    archive = _directory(log_dir, ARCHIVE_DIR)
    for source in daily.iterdir():
        if not _DATE_FILE.fullmatch(source.name):
            continue
        try:
            day = date.fromisoformat(source.stem)
        except ValueError:
            continue
        if day >= today:
            continue
        _reject_link(source)
        # Skapa unikt mål utan att skriva över något befintligt arkiv. Om en
        # process kraschar under kopieringen lämnas källan kvar för nytt försök.
        number = 0
        while True:
            name = source.name if not number else f"{source.stem}-{number}.log"
            target = archive / name
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
            try:
                fd = os.open(target, flags, 0o600)
                break
            except FileExistsError:
                number += 1
        try:
            with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
                shutil.copyfileobj(input_file, output, 1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        source.unlink()


ARCHIVE_KEEP_DAYS = 7
_ARCHIVED_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-\d+)?\.log$")


def purge_archived_days(log_dir: Path, today: date | None = None,
                        keep_days: int = ARCHIVE_KEEP_DAYS) -> list[str]:
    """Radera arkiverade loggar som är äldre än ``keep_days`` dagar.

    Arkiverade filer heter ``ÅÅÅÅ-MM-DD.log`` (eller ``-2.log`` vid namnkonflikt).
    Datumet i namnet är när loggen skrevs – inte när den flyttades. Filer vars
    namn inte går att tolka lämnas orörda, liksom symboliska länkar.
    Returnerar namnen som raderades.
    """
    log_dir = Path(log_dir)
    archive = log_dir / ARCHIVE_DIR
    if not archive.is_dir() or archive.is_symlink():
        return []
    try:
        limit = max(1, int(keep_days))
    except (TypeError, ValueError):
        limit = ARCHIVE_KEEP_DAYS
    cutoff = (today or date.today()).toordinal() - limit
    removed = []
    for entry in archive.iterdir():
        match = _ARCHIVED_NAME.fullmatch(entry.name)
        if not match or entry.is_symlink() or not entry.is_file():
            continue
        try:
            day = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if day.toordinal() > cutoff:
            continue
        try:
            entry.unlink()
            removed.append(entry.name)
        except OSError:
            continue
    return removed


def archive_old_days(log_dir: Path, today: date | None = None) -> None:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    with _process_lock(log_dir / '.dagliga.lock'):
        _archive_locked(log_dir, today or date.today())
        # Arkiverade loggar sparas i sju dagar och raderas sedan automatiskt.
        purge_archived_days(log_dir, today)


def append_daily(log_dir: Path, day: date, text: str, *, today: date | None = None) -> None:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    with _process_lock(log_dir / '.dagliga.lock'):
        daily = _directory(log_dir, DAILY_DIR)
        _append_file(daily / f'{day.isoformat()}.log', (text.rstrip('\n') + '\n').encode('utf-8', errors='backslashreplace'))
        _archive_locked(log_dir, today or date.today())


def _absolute_path(value: object) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _coded_exception(record: logging.LogRecord):
    """Ta endast uttryckliga koder, aldrig en gissning utifrån text."""
    candidates = []
    if record.exc_info and record.exc_info[1] is not None:
        candidates.append(record.exc_info[1])
    if isinstance(record.args, dict):
        candidates.extend(record.args.values())
    elif isinstance(record.args, tuple):
        candidates.extend(record.args)
    explicit = getattr(record, 'error_code', None)
    if isinstance(explicit, str) and _CODE.fullmatch(explicit):
        return explicit, None
    seen = set()
    while candidates:
        exc = candidates.pop(0)
        if not isinstance(exc, BaseException) or id(exc) in seen:
            continue
        seen.add(id(exc))
        code = getattr(exc, 'error_code', None)
        if isinstance(code, str) and _CODE.fullmatch(code):
            return code, exc
        if exc.__cause__ is not None:
            candidates.append(exc.__cause__)
        elif exc.__context__ is not None:
            candidates.append(exc.__context__)
    return None, None


def _read_codes(path: Path) -> dict:
    _reject_link(path)
    if not path.exists():
        return {'version': 1, 'entries': {}}
    with path.open(encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('entries'), dict):
        raise ValueError('Felkodsregistret har ogiltigt format och lämnas orört')
    return data


def _write_codes(path: Path, data: dict) -> None:
    _reject_link(path)
    fd, temp = tempfile.mkstemp(prefix='.felkoder-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        _reject_link(path)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def record_error_code(log_dir: Path, record: logging.LogRecord) -> bool:
    code, exc = _coded_exception(record)
    if not code:
        return False
    config_path = getattr(exc, 'config_path', None) if exc is not None else None
    subject = _absolute_path(config_path) if code == 'CONFIG_PARSE_ERROR' and config_path else None
    # Utan ett entydigt ärende kan ingen kod automatiskt lösas.
    identity = [code, 'config', subject] if subject else [code, record.name, record.pathname, record.lineno, record.getMessage()]
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode('utf-8')).hexdigest()
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    with _process_lock(log_dir / '.felkoder.lock'):
        path = log_dir / CODES_FILE
        data = _read_codes(path)
        entry = data['entries'].get(key)
        if entry is not None and not isinstance(entry, dict):
            raise ValueError('Felkodsposten har ogiltigt format och lämnas orörd')
        when = datetime.fromtimestamp(record.created).astimezone().isoformat(timespec='seconds')
        if entry is None:
            entry = {'code': code, 'subject': subject, 'logger': record.name,
                     'message': record.getMessage(), 'first_seen': when, 'count': 0}
        entry.update({'status': 'aktiv', 'last_seen': when, 'last_seen_epoch': record.created,
                      'count': entry.get('count', 0) + 1, 'resolved_at': None})
        data['entries'][key] = entry
        _write_codes(path, data)
    return True


def resolve_config_parse_error(log_dir: Path, config_path: Path, *, started_at: float) -> bool:
    """Markera bara samma fils syntaxfel efter en faktisk lyckad parse.

    En felpost som registrerades efter att läsningen började löses inte.
    Övriga felkoder lämnas aktiva eftersom verifiering saknas.
    """
    log_dir = Path(log_dir)
    path = log_dir / CODES_FILE
    if not path.exists() and not path.is_symlink():
        return False
    subject = _absolute_path(config_path)
    key = hashlib.sha256(json.dumps(['CONFIG_PARSE_ERROR', 'config', subject], ensure_ascii=False).encode('utf-8')).hexdigest()
    with _process_lock(log_dir / '.felkoder.lock'):
        data = _read_codes(path)
        entry = data['entries'].get(key)
        if not isinstance(entry, dict) or entry.get('status') != 'aktiv':
            return False
        if not isinstance(entry.get('last_seen_epoch'), (int, float)) or entry['last_seen_epoch'] >= started_at:
            return False
        entry['status'] = 'åtgärdad'
        entry['resolved_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
        entry['verification'] = 'Samma konfigurationsfil har lästs och parsats som JSON utan syntaxfel.'
        _write_codes(path, data)
        return True


class DailyLogHandler(logging.Handler):
    """En datumindelad loggkopia och strukturerade felkoder, med processlås."""
    _fordonsreg_archive_handler = True

    def __init__(self, log_dir: Path, origin: str, *, monitor: bool = False):
        super().__init__(logging.DEBUG)
        self.log_dir = Path(log_dir)
        self.origin = origin
        self.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] [%(daily_origin)s] [pid=%(process)d] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'))
        self._stop = threading.Event()
        try:
            archive_old_days(self.log_dir)
        except Exception as exc:
            self._report(exc)
        if monitor:
            threading.Thread(target=self._monitor, name='daily-log-archive', daemon=True).start()

    @staticmethod
    def _report(exc: Exception) -> None:
        import sys
        try:
            sys.stderr.write(f'Kunde inte spara eller arkivera dagslogg/felkod: {exc}\n')
        except Exception:
            pass

    def _monitor(self) -> None:
        while not self._stop.wait(60):
            try:
                archive_old_days(self.log_dir)
            except Exception as exc:
                self._report(exc)

    def close(self) -> None:
        self._stop.set()
        super().close()

    def emit(self, record: logging.LogRecord) -> None:
        target = os.path.normcase(os.path.abspath(self.log_dir))
        written = getattr(record, _DAILY_MARKER, set())
        if target not in written:
            try:
                copy = logging.makeLogRecord(record.__dict__.copy())
                copy.daily_origin = self.origin
                append_daily(self.log_dir, datetime.fromtimestamp(record.created).date(), self.format(copy))
                written.add(target)
                setattr(record, _DAILY_MARKER, written)
            except Exception as exc:
                self._report(exc)
        codes_written = getattr(record, _CODE_MARKER, set())
        if record.levelno >= logging.WARNING and target not in codes_written:
            try:
                if record_error_code(self.log_dir, record):
                    codes_written.add(target)
                    setattr(record, _CODE_MARKER, codes_written)
            except Exception as exc:
                self._report(exc)


# ── Aktiva fel och åtgärdade fel ───────────────────────────────────────────

def load_error_codes(log_dir: Path) -> list[dict]:
    """Läs felkodsregistret som en lista, nyast först.

    Varje post får nyckeln ``key`` så att den kan åtgärdas eller tas bort.
    Trasigt register ger en tom lista – hellre tomt än felaktigt.
    """
    path = Path(log_dir) / CODES_FILE
    try:
        data = _read_codes(path)
    except (OSError, ValueError):
        return []
    entries = []
    for key, entry in (data.get("entries") or {}).items():
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        row["key"] = key
        row.setdefault("status", "aktiv")
        entries.append(row)
    entries.sort(key=lambda row: float(row.get("last_seen_epoch") or 0), reverse=True)
    return entries


def active_error_codes(log_dir: Path) -> list[dict]:
    """Endast de fel som fortfarande gäller."""
    return [row for row in load_error_codes(log_dir) if row.get("status") == "aktiv"]


def mark_resolved(log_dir: Path, keys, note: str = "") -> int:
    """Markera fel som åtgärdade, med tidpunkt och en frivillig notering.

    Används när användaren själv har rättat felet och väljer **Markera
    åtgärdade** i felsökningsloggen. Returnerar antalet poster som ändrades.
    """
    wanted = {str(key) for key in keys}
    if not wanted:
        return 0
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    with _process_lock(log_dir / ".felkoder.lock"):
        path = log_dir / CODES_FILE
        data = _read_codes(path)
        changed = 0
        when = datetime.now().astimezone().isoformat(timespec="seconds")
        for key in wanted:
            entry = data["entries"].get(key)
            if not isinstance(entry, dict) or entry.get("status") != "aktiv":
                continue
            entry["status"] = "åtgärdad"
            entry["resolved_at"] = when
            if note:
                entry["resolved_note"] = str(note)[:500]
            changed += 1
        if changed:
            _write_codes(path, data)
        return changed


def remove_error_codes(log_dir: Path, keys) -> int:
    """Ta bort poster ur registret när felet är åtgärdat och kontrollerat.

    Endast åtgärdade poster får tas bort – ett aktivt fel ska aldrig kunna
    försvinna av misstag. Returnerar antalet borttagna poster.
    """
    wanted = {str(key) for key in keys}
    if not wanted:
        return 0
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    with _process_lock(log_dir / ".felkoder.lock"):
        path = log_dir / CODES_FILE
        data = _read_codes(path)
        removed = 0
        for key in wanted:
            entry = data["entries"].get(key)
            if not isinstance(entry, dict) or entry.get("status") == "aktiv":
                continue
            del data["entries"][key]
            removed += 1
        if removed:
            _write_codes(path, data)
        return removed


def prune_resolved(log_dir: Path, keep_days: int = ARCHIVE_KEEP_DAYS,
                   today: date | None = None) -> int:
    """Ta bort åtgärdade fel som är äldre än ``keep_days``.

    Samma sju dagar som för arkiverade loggar, så att registret inte växer
    obegränsat. Aktiva fel rörs aldrig.
    """
    log_dir = Path(log_dir)
    path = log_dir / CODES_FILE
    if not path.exists():
        return 0
    try:
        limit = max(1, int(keep_days))
    except (TypeError, ValueError):
        limit = ARCHIVE_KEEP_DAYS
    cutoff = (today or date.today()).toordinal() - limit
    removed = 0
    with _process_lock(log_dir / ".felkoder.lock"):
        data = _read_codes(path)
        for key, entry in list(data["entries"].items()):
            if not isinstance(entry, dict) or entry.get("status") == "aktiv":
                continue
            stamp = entry.get("resolved_at")
            if not isinstance(stamp, str):
                continue
            try:
                day = date.fromisoformat(stamp[:10])
            except ValueError:
                continue
            if day.toordinal() <= cutoff:
                del data["entries"][key]
                removed += 1
        if removed:
            _write_codes(path, data)
    return removed
