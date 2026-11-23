"""Verifiering av ett riktigt TS-underlag före upplåsning (förslag 11).

Verktyget analyserar en TS-fil som användaren själv väljer: teckenkodning,
radslut, postlängd och avgränsare. Resultatet jämförs med den granskade
PT45-layouten. Ingenting skrivs, flyttas eller genereras här.

En upplåsning kräver tre saker samtidigt: ett underlag som klarar kontrollerna,
en uttrycklig bekräftelse och en sparad granskningsrapport. Godkännandet binds
till underlagets SHA-256, så en ändrad fil upphäver det automatiskt.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from core.ts_safety import PT45_MC_MOPED_LAYOUT

_log = logging.getLogger(__name__)

VERIFICATION_NAME = "ts_verification.json"
VERIFICATION_VERSION = 1
MAX_BYTES = 40 * 1024 * 1024
MAX_RECORDS = 100_000
EXPECTED_RECORD_LENGTH = 2500
SUPPORTED_SCHEMAS = ("PT45",)


class VerificationError(Exception):
    """Underlaget kan inte verifieras eller godkännas."""


def _read_bytes(path: Path) -> bytes:
    path = Path(path)
    if path.is_symlink():
        raise VerificationError("Underlaget får inte vara en symbolisk länk.")
    if not path.is_file():
        raise VerificationError("Underlaget finns inte eller är inte en vanlig fil.")
    if path.stat().st_size > MAX_BYTES:
        raise VerificationError("Underlaget är för stort för att granskas här.")
    data = path.read_bytes()
    if b"\x00" in data:
        raise VerificationError("Underlaget innehåller nollbyte och kan inte vara en TS-textfil.")
    return data


def decode(data: bytes) -> tuple[str, str, bool]:
    """Avkoda utan att gissa tyst: BOM styr, annars UTF-8, annars cp1252."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8-sig", True
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "cp1252", False
    except UnicodeDecodeError as exc:
        raise VerificationError("Teckenkodningen kunde inte fastställas.") from exc


def analyze(data: bytes) -> dict:
    """Sammanfatta strukturen i ett underlag. Ändrar ingenting."""
    if b"\x00" in data:
        raise VerificationError("Underlaget innehåller nollbyte och kan inte vara en TS-textfil.")
    text, encoding, bom = decode(data)
    crlf = text.count("\r\n")
    stripped = text.replace("\r\n", "")
    lone_cr = stripped.count("\r")
    lone_lf = stripped.count("\n")
    endings = "crlf" if crlf and not (lone_cr or lone_lf) else (
        "lf" if lone_lf and not (crlf or lone_cr) else (
            "cr" if lone_cr and not (crlf or lone_lf) else "mixed"))
    lines = text.splitlines()
    if not lines:
        raise VerificationError("Underlaget är tomt.")
    if len(lines) > MAX_RECORDS:
        raise VerificationError("Underlaget har fler poster än vad som kan granskas här.")
    lengths = sorted({len(line) for line in lines})
    widths = [end - start + 1 for start, end in PT45_MC_MOPED_LAYOUT]
    clean = [line for line in lines if line.strip()]
    semicolons = [line.count(";") for line in clean]
    tabs = [line.count("\t") for line in clean]
    decimals_comma = sum(line.count(",") for line in clean)
    decimals_point = sum(line.count(".") for line in clean)
    return {
        "encoding": encoding,
        "bom": bom,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "lines": len(lines),
        "records": len(clean),
        "empty_lines": len(lines) - len(clean),
        "line_endings": endings,
        "trailing_newline": text.endswith(("\n", "\r")),
        "record_lengths": lengths,
        "expected_record_length": EXPECTED_RECORD_LENGTH,
        "field_widths": widths,
        "declared_width_sum": sum(widths),
        "semicolons_min": min(semicolons) if semicolons else 0,
        "semicolons_max": max(semicolons) if semicolons else 0,
        "tabs_present": any(tabs),
        "decimal_comma_count": decimals_comma,
        "decimal_point_count": decimals_point,
    }


def compare(structure: dict) -> list[str]:
    """Lista skillnader mot den granskade PT45-layouten. Tomt = inga hinder."""
    problems: list[str] = []
    if structure.get("declared_width_sum") != EXPECTED_RECORD_LENGTH:
        problems.append("Den granskade PT45-layouten summerar inte till 2500 tecken.")
    lengths = structure.get("record_lengths") or []
    if not lengths:
        problems.append("Ingen post kunde mätas.")
    elif lengths != [EXPECTED_RECORD_LENGTH]:
        shown = ", ".join(str(value) for value in lengths[:5])
        problems.append(f"Postlängderna är {shown} tecken; PT45 ska vara {EXPECTED_RECORD_LENGTH}.")
    if structure.get("line_endings") == "mixed":
        problems.append("Blandade radslut i filen; formatet är inte entydigt.")
    if structure.get("empty_lines"):
        problems.append("Filen innehåller tomma rader.")
    if structure.get("semicolons_max"):
        problems.append("Filen innehåller semikolon; PT45 är ett fast breddformat.")
    if structure.get("tabs_present"):
        problems.append("Filen innehåller tabulatortecken.")
    return problems


def report(path: Path) -> dict:
    """Skapa en granskningsrapport utan att spara eller godkänna något."""
    data = _read_bytes(path)
    structure = analyze(data)
    problems = compare(structure)
    return {
        "file": Path(path).name,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "structure": structure,
        "problems": problems,
        "can_lock_open": not problems,
    }


def _approval_path(root: Path) -> Path:
    return Path(root).resolve() / VERIFICATION_NAME


def _load_record(root: Path) -> dict | None:
    path = _approval_path(root)
    if path.is_symlink():
        raise VerificationError("Godkännandefilen får inte vara en symbolisk länk.")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise VerificationError("Godkännandefilen är skadad och kan inte användas.") from exc
    if not isinstance(data, dict) or data.get("version") != VERIFICATION_VERSION:
        raise VerificationError("Godkännandefilen har okänt format.")
    return data


def approve(root: Path, report_data: dict, *, confirmed: bool, note: str) -> dict:
    """Spara ett godkännande. Kräver bekräftelse, felfri rapport och en anteckning."""
    if not confirmed:
        raise VerificationError("Ingen upplåsning utan uttrycklig bekräftelse.")
    if not isinstance(note, str) or len(note.strip()) < 10:
        raise VerificationError("Anteckningen måste beskriva vad som verifierats (minst 10 tecken).")
    if not isinstance(report_data, dict) or report_data.get("problems"):
        raise VerificationError("Rapporten innehåller hinder och kan inte godkännas.")
    structure = report_data.get("structure") or {}
    if not structure.get("sha256") or not structure.get("encoding"):
        raise VerificationError("Rapporten saknar underlagets identitet.")
    record = {
        "version": VERIFICATION_VERSION,
        "schema": "PT45",
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": structure["sha256"],
        "source_file": report_data.get("file"),
        "encoding": structure.get("encoding"),
        "line_endings": structure.get("line_endings"),
        "record_length": EXPECTED_RECORD_LENGTH,
        "note": note.strip()[:1000],
        "verified_by": "användaren via Fordonsregs granskningsverktyg",
    }
    path = _approval_path(root)
    if path.is_symlink():
        raise VerificationError("Godkännandefilen får inte vara en symbolisk länk.")
    fd, temp = tempfile.mkstemp(prefix=".tsver-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    _log.info("TS-formatet PT45 godkändes för underlag %s", structure["sha256"][:12])
    return record


def approval(root: Path, *, source: Path | None = None) -> dict | None:
    """Läs ett giltigt godkännande. En ändrad källfil upphäver godkännandet."""
    try:
        record = _load_record(root)
    except VerificationError as exc:
        _log.warning("TS-godkännandet kunde inte läsas: %s", exc)
        return None
    if record is None:
        return None
    if record.get("schema") not in SUPPORTED_SCHEMAS:
        return None
    if not isinstance(record.get("sha256"), str) or len(record["sha256"]) != 64:
        return None
    if not isinstance(record.get("note"), str) or len(record["note"].strip()) < 10:
        return None
    if source is not None:
        try:
            current = hashlib.sha256(_read_bytes(source)).hexdigest()
        except VerificationError:
            return None
        if current != record["sha256"]:
            _log.warning("TS-underlaget har ändrats sedan godkännandet")
            return None
    return record


def status(root: Path) -> str:
    """Kort text om verifieringsläget, för GUI och logg."""
    try:
        record = _load_record(root)
    except VerificationError as exc:
        return f"Godkännandet kan inte användas: {exc}"
    if record is None:
        return ("TS-formatet är inte verifierat. Använd Verktyg → Verifiera TS-underlag "
                "med en riktig TS-fil innan något får genereras.")
    return (f"PT45 verifierat {record.get('approved_at')} mot "
            f"{record.get('source_file')} ({str(record.get('sha256'))[:12]}…).")
