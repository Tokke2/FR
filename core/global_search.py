"""Lokal, snabb sökning i fordonsdata (förslag 17).

Indexet byggs av de årliga JSON-filerna och sparas bredvid dem. Sökningen är
helt lokal: inga nätverksanrop, inga ändringar av källdata och inga gissningar.
Ett inaktuellt eller skadat index byggs om automatiskt.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile

_log = logging.getLogger(__name__)

INDEX_NAME = "search_index.json"
INDEX_VERSION = 1
MAX_RESULTS = 50
EPSILON = 1e-9

# Fält som är särskilt intressanta att söka på, med svensk etikett.
FIELD_LABELS = {
    "vin_kod": "VIN-kod",
    "vin": "VIN",
    "godkannandenummer": "Godkännandenummer",
    "approval": "Godkännandenummer",
    "fordonsidentitet": "Fordonsidentitet",
    "registreringsnummer": "Registreringsnummer",
    "regnr": "Registreringsnummer",
    "handelsbeteckning": "Handelsbeteckning",
    "modellkod": "Modellkod",
    "typ": "Typ",
    "variant": "Variant",
    "version": "Version",
    "fordonskategori": "Fordonskategori",
    "fordonsklass": "Fordonsklass",
    "farg": "Färg",
    "color": "Färg",
    "aterforsaljare": "Återförsäljare",
    "dealer": "Återförsäljare",
}
PRIORITY_FIELDS = tuple(FIELD_LABELS)
MAX_FIELD_LENGTH = 400


def _text(value) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    text = str(value).strip()
    return text[:MAX_FIELD_LENGTH]


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _display_title(record: dict) -> str:
    for key in ("vin_kod", "vin", "fordonsidentitet", "registreringsnummer"):
        value = _text(record.get(key))
        if value:
            return value
    return "Fordonspost"


def _display_subtitle(record: dict) -> str:
    parts = []
    for key in ("handelsbeteckning", "modellkod", "typ", "farg", "aterforsaljare"):
        value = _text(record.get(key))
        if value and value not in parts:
            parts.append(value)
    return " · ".join(parts)


def index_record(record: dict, year: int, row: int) -> dict | None:
    """Gör en sökbar post. Poster utan något sökbart värde hoppas över."""
    if not isinstance(record, dict):
        return None
    fields = {}
    for key, value in record.items():
        text = _text(value)
        if text:
            fields[str(key)] = text
    if not fields:
        return None
    haystack = "\n".join(f"{key}\n{value}" for key, value in fields.items()).casefold()
    return {
        "year": int(year),
        "row": int(row),
        "title": _display_title(record),
        "subtitle": _display_subtitle(record),
        "fields": fields,
        "haystack": haystack,
    }


def _payload_records(payload) -> list:
    if isinstance(payload, dict):
        records = payload.get("vehicles")
        return records if isinstance(records, list) else []
    return payload if isinstance(payload, list) else []


def build_index(sources) -> dict:
    """Bygg index av (år, innehåll, källnamn) utan att röra källfilerna."""
    entries: list[dict] = []
    for year, payload, _name in sources:
        try:
            year = int(year)
        except (TypeError, ValueError):
            _log.warning("Hoppar över årsfil med ogiltigt år: %r", year)
            continue
        for row, record in enumerate(_payload_records(payload)):
            entry = index_record(record, year, row)
            if entry is not None:
                entries.append(entry)
    entries.sort(key=lambda item: (item["year"], item["row"]))
    return {"version": INDEX_VERSION, "entries": entries}


def fingerprint(path: Path) -> dict:
    """Identifiera en källfil utan att läsa hela innehållet varje gång."""
    path = Path(path)
    st = path.stat()
    return {"name": path.name, "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def source_files(vehicle_dir: Path) -> list[Path]:
    """Årsfiler i aktiv mapp och i arkivmappen, utan dolda filer."""
    vehicle_dir = Path(vehicle_dir)
    files: list[Path] = []
    for directory in (vehicle_dir, vehicle_dir / "arkiv"):
        if not directory.is_dir() or directory.is_symlink():
            continue
        files.extend(sorted(p for p in directory.glob("*.json")
                            if p.is_file() and not p.is_symlink() and not p.name.startswith(".")))
    return files


def load_sources(vehicle_dir: Path) -> tuple[list[tuple[int, object, str]], list[dict]]:
    veh = []
    prints = []
    for path in source_files(vehicle_dir):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            _log.warning("Kunde inte läsa %s för sökindex: %s", path.name, exc)
            continue
        year = path.stem if path.stem.isdigit() else -1
        if path.stem.isdigit():
            year = int(path.stem)
        elif isinstance(payload, dict) and isinstance(payload.get("_meta"), dict):
            try:
                year = int(payload["_meta"].get("year"))
            except (TypeError, ValueError):
                year = -1
        veh.append((year, payload, path.name))
        prints.append(fingerprint(path))
    return veh, prints


def valid_index(data) -> bool:
    if not isinstance(data, dict) or data.get("version") != INDEX_VERSION:
        return False
    entries = data.get("entries")
    if not isinstance(entries, list) or len(entries) > 500_000:
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        if not isinstance(entry.get("year"), int) or not isinstance(entry.get("row"), int):
            return False
        if not isinstance(entry.get("haystack"), str) or not isinstance(entry.get("fields"), dict):
            return False
    return True


def _atomic_write(path: Path, data: dict) -> None:
    path = Path(path)
    if path.is_symlink():
        raise OSError("Sökindexet får inte vara en symbolisk länk")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".search-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def ensure_index(index_path: Path, vehicle_dir: Path) -> dict:
    """Läs index om det är aktuellt, annars bygg om det från årsfilerna."""
    index_path = Path(index_path)
    sources, prints = load_sources(vehicle_dir)
    current = {"sources": prints}
    try:
        if index_path.is_symlink():
            raise OSError("Sökindexet får inte vara en symbolisk länk")
        if index_path.is_file():
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if valid_index(data) and data.get("sources") == prints:
                return data
            _log.info("Sökindexet är inaktuellt och byggs om")
    except (OSError, UnicodeError, ValueError) as exc:
        _log.warning("Sökindexet kunde inte läsas och byggs om: %s", exc)
    data = build_index(sources)
    data.update(current)
    try:
        _atomic_write(index_path, data)
    except OSError as exc:
        # Sökningen fungerar ändå; bara cachen uteblir.
        _log.warning("Sökindexet kunde inte sparas: %s", exc)
    return data


def _score(entry: dict, tokens: list[str]) -> float:
    fields = entry["fields"]
    total = 0.0
    for token in tokens:
        best = 0.0
        for key, raw in fields.items():
            value = _normalize(raw)
            if not value:
                continue
            if value == token:
                score = 100.0
            elif value.startswith(token):
                score = 70.0
            elif token in value:
                score = 40.0
            else:
                continue
            if key in PRIORITY_FIELDS:
                score += 15.0
            if score > best:
                best = score
        if best <= 0.0:
            return 0.0
        total += best
    return total


def _match_field(entry: dict, token: str) -> tuple[str, str]:
    fields = entry["fields"]
    for key in PRIORITY_FIELDS:
        raw = fields.get(key)
        if raw and token in _normalize(raw):
            return FIELD_LABELS.get(key, key), raw
    for key, raw in fields.items():
        if token in _normalize(raw):
            return key, raw
    return "", ""


def search(index: dict, query: str, limit: int = MAX_RESULTS) -> list[dict]:
    """Returnera träffar sorterade på relevans. Tom fråga ger inga träffar."""
    if not valid_index(index):
        raise ValueError("Sökindexet har ogiltigt format")
    tokens = _normalize(query).split()
    if not tokens:
        return []
    results = []
    for entry in index["entries"]:
        score = _score(entry, tokens)
        if score <= 0.0:
            continue
        field, value = _match_field(entry, tokens[0])
        results.append({
            "year": entry["year"],
            "row": entry["row"],
            "title": entry.get("title") or "Fordonspost",
            "subtitle": entry.get("subtitle") or "",
            "field": field,
            "value": value,
            "score": round(score, 2),
        })
    results.sort(key=lambda item: (-item["score"], -item["year"], item["row"]))
    if isinstance(limit, int) and limit > 0:
        return results[:limit]
    return results
