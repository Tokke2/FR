"""Starthälsokontroll med automatiskt återfall (förslag 22).

Flödet är medvetet enkelt och granskningsbart:

1. Efter en uppdatering skriver uppdateraren en markör med vilka filer som
   byttes och var säkerhetskopian finns.
2. Vid nästa start kontrolleras markören. Finns den kvar betyder det att
   föregående start inte hann bekräfta att programmet fungerade – då återställs
   säkerhetskopian innan appen startar.
3. När huvudfönstret är uppe bekräftas starten och markören tas bort.

Ingen fil återställs utan att säkerhetskopian först verifierats mot sin
manifestfil. Allt som görs skrivs till appens vanliga loggning.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile

_log = logging.getLogger(__name__)

HEALTH_VERSION = 1
STATE_DIR = ".health"
BACKUP_DIR = ".update-backups"
PENDING_NAME = "pending.json"
HISTORY_NAME = "recovery.jsonl"
MAX_PENDING_BYTES = 1024 * 1024
MAX_FILES = 500
MAX_FILE_BYTES = 20 * 1024 * 1024


class HealthError(Exception):
    """Markören eller säkerhetskopian kan inte användas på ett säkert sätt."""


def _state_dir(root: Path) -> Path:
    path = Path(root).resolve() / STATE_DIR
    if path.is_symlink():
        raise HealthError("Hälsokatalogen får inte vara en symbolisk länk.")
    return path


def _reject_link(path: Path) -> None:
    if path.is_symlink():
        raise HealthError(f"Symbolisk länk tillåts inte: {path.name}")


def _atomic_write(path: Path, content: bytes) -> None:
    _reject_link(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".health-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _safe_relative(name: str) -> tuple[str, ...]:
    parts = PurePosixPath(str(name)).parts
    if not parts or any(part in (".", "..") or ":" in part or "\\" in part for part in parts):
        raise HealthError(f"Otillåten sökväg i markören: {name!r}")
    if any(part.startswith(".") for part in parts):
        raise HealthError(f"Dold sökväg i markören: {name!r}")
    return parts


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mark_pending(root: Path, backup: Path | None, files: list[str]) -> Path | None:
    """Skriv markören efter en genomförd uppdatering. Utan filer görs ingenting."""
    if not files:
        return None
    if len(files) > MAX_FILES:
        raise HealthError("Uppdateringen omfattar fler filer än hälsokontrollen hanterar.")
    root = Path(root).resolve()
    entries = []
    for name in files:
        parts = _safe_relative(name)
        target = root.joinpath(*parts)
        if not target.is_file() or target.is_symlink():
            raise HealthError(f"Uppdaterad fil saknas: {name}")
        entries.append({"name": name, "sha256": _hash_file(target),
                        "size": target.stat().st_size})
    backup_path = None
    if backup is not None:
        backup = Path(backup)
        if not backup.is_dir() or backup.is_symlink():
            raise HealthError("Säkerhetskopian saknas eller är en länk.")
        backup_path = str(backup.resolve())
    record = {"version": HEALTH_VERSION, "backup": backup_path, "files": entries}
    path = _state_dir(root) / PENDING_NAME
    _atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
    return path


def _load_pending(root: Path) -> dict | None:
    path = _state_dir(root) / PENDING_NAME
    _reject_link(path)
    if not path.exists():
        return None
    if path.stat().st_size > MAX_PENDING_BYTES:
        raise HealthError("Markören är för stor.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise HealthError("Markören är skadad.") from exc
    if not isinstance(data, dict) or data.get("version") != HEALTH_VERSION:
        raise HealthError("Markören har okänt format.")
    files = data.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise HealthError("Markören saknar giltig fillista.")
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise HealthError("Markörens fillista är ogiltig.")
        if not isinstance(entry.get("sha256"), str) or len(entry["sha256"]) != 64:
            raise HealthError("Markören saknar kontrollsumma.")
    return data


def remove_backup(root: Path, backup: Path | str | None) -> bool:
    """Radera en säkerhetskopia som inte längre behövs.

    Anropas först när appen har startat och fungerat efter uppdateringen.
    Katalogen måste ligga direkt under ``<rot>/.update-backups``; allt annat
    lämnas orört, och en symbolisk länk raderas aldrig.
    """
    if not backup:
        return False
    root = Path(root).resolve()
    allowed = root / BACKUP_DIR
    try:
        path = Path(backup).resolve()
    except (OSError, ValueError):
        return False
    if path == allowed or allowed not in path.parents:
        _log.warning("Säkerhetskopian ligger utanför backupkatalogen och behålls: %s", path)
        return False
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        shutil.rmtree(path)
    except OSError as exc:
        _log.warning("Säkerhetskopian kunde inte tas bort: %s", exc)
        return False
    _log.info("Säkerhetskopian togs bort efter lyckad uppdatering: %s", path.name)
    return True


def confirm_healthy(root: Path) -> bool:
    """Bekräfta att appen startat: ta bort markören och säkerhetskopian.

    Markören tas bort först när appen är uppe. Då är uppdateringen bevisat
    fungerande och säkerhetskopian behövs inte längre – den tas bort direkt,
    så att inget gammalt skräp ligger kvar. Misslyckades starten finns
    markören kvar och kopian återställs i stället.
    """
    try:
        path = _state_dir(root) / PENDING_NAME
        _reject_link(path)
    except HealthError:
        _log.warning("Startmarkören är en symbolisk länk och lämnas orörd")
        return False
    if not path.exists():
        return False
    backup = None
    try:
        backup = _load_pending(root).get("backup")
    except (HealthError, AttributeError):
        backup = None
    try:
        path.unlink()
    except OSError as exc:
        _log.warning("Startmarkören kunde inte tas bort: %s", exc)
        return False
    if backup and remove_backup(root, backup):
        _append_history(root, {"event": "backup_removed", "backup": str(backup)})
    return True


def _append_history(root: Path, record: dict) -> None:
    try:
        path = _state_dir(root) / HISTORY_NAME
        _reject_link(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        _log.warning("Återställningshistoriken kunde inte skrivas: %s", exc)


def _restore_from_backup(root: Path, backup: Path, files: list[dict]) -> list[str]:
    manifest_path = backup / "manifest.json"
    _reject_link(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise HealthError("Säkerhetskopians manifest kunde inte läsas.") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise HealthError("Säkerhetskopians manifest har okänt format.")
    copied: list[str] = []
    for entry in files:
        name = entry["name"]
        parts = _safe_relative(name)
        source = backup.joinpath(*parts)
        if source.is_symlink() or not source.is_file():
            raise HealthError(f"Säkerhetskopian saknar {name}; ingenting återställs.")
        if source.stat().st_size > MAX_FILE_BYTES:
            raise HealthError(f"{name} i säkerhetskopian är för stor.")
        content = source.read_bytes()
        target = root.joinpath(*parts)
        if target.exists() and not target.is_file():
            raise HealthError(f"Målet för {name} är inte en vanlig fil.")
        _atomic_write(target, content)
        copied.append(name)
    return copied


def check_and_recover(root: Path) -> dict:
    """Kontrollera föregående start och återställ vid behov. Kasta aldrig vidare."""
    root = Path(root).resolve()
    result = {"checked": True, "pending": False, "recovered": [], "removed_files": [],
              "error": None}
    try:
        data = _load_pending(root)
    except HealthError as exc:
        _log.error("Starthälsokontrollen kunde inte läsa markören: %s", exc)
        result["error"] = str(exc)
        return result
    if data is None:
        return result
    result["pending"] = True
    files = data["files"]
    backup = data.get("backup")
    if not isinstance(backup, str) or not Path(backup).is_dir():
        message = ("Föregående start bekräftades aldrig och säkerhetskopian saknas. "
                   "Inga filer ändrades. Använd Återställningscenter om problemet kvarstår.")
        _log.error(message)
        result["error"] = message
        return result
    backup_path = Path(backup)
    try:
        if backup_path.is_symlink():
            raise HealthError("Säkerhetskopian är en symbolisk länk.")
        restored = _restore_from_backup(root, backup_path, files)
    except HealthError as exc:
        _log.error("Automatisk återställning avbröts: %s", exc)
        result["error"] = str(exc)
        return result
    except OSError as exc:
        _log.exception("Automatisk återställning misslyckades")
        result["error"] = str(exc)
        return result
    result["recovered"] = restored
    # Kopian behövs inte när filerna är återställda och verifierade.
    confirm_healthy(root)
    _append_history(root, {"event": "automatic_rollback", "files": restored,
                           "backup": str(backup_path)})
    _log.warning("Föregående start bekräftades inte. Återställde %d fil(er) från %s",
                 len(restored), backup_path)
    return result
