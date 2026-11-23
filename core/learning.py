"""Lokalt inlärningsminne för uttryckligen godkända, säkra förslag.

Bara anslutna funktioner lär sig. Minnen ger förslag, inte dataskrivningar.
Inga arbetsboksrader, personuppgifter eller PIN-koder ska skickas hit.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Iterable

_LOCK = threading.RLock()
VERSION = 1
MAX_BYTES = 2 * 1024 * 1024
MAX_RULES = 5000
MIN_CONFIRMATIONS = 2


class LearningError(ValueError):
    pass


class LearningStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if self.path.is_symlink():
            raise LearningError('Inlärningsfilen får inte vara en symbolisk länk')
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return {'version': VERSION, 'enabled': True, 'contexts': {}}
        except OSError as exc:
            raise LearningError('Inlärningsfilen kunde inte läsas') from exc
        if len(raw) > MAX_BYTES:
            raise LearningError('Inlärningsfilen är för stor och har lämnats orörd')
        try:
            data = json.loads(raw.decode('utf-8'))
        except (UnicodeError, ValueError) as exc:
            raise LearningError('Inlärningsfilen är oläsbar och har lämnats orörd') from exc
        if (not isinstance(data, dict) or type(data.get('version')) is not int or data.get('version') != VERSION
                or type(data.get('enabled')) is not bool or not isinstance(data.get('contexts'), dict)):
            raise LearningError('Inlärningsfilen har okänt format och har lämnats orörd')
        total = 0
        for context, rules in data['contexts'].items():
            if not isinstance(context, str) or not context or not isinstance(rules, dict):
                raise LearningError('Inlärningsfilen är ogiltig och har lämnats orörd')
            for header, votes in rules.items():
                total += 1
                if (not isinstance(header, str) or not header or len(header) > 200
                        or not isinstance(votes, dict) or not votes
                        or any(not isinstance(field, str) or not field or len(field) > 200
                               or type(count) is not int or not 1 <= count <= 1000000
                               for field, count in votes.items())):
                    raise LearningError('Inlärningsfilen är ogiltig och har lämnats orörd')
        if total > MAX_RULES:
            raise LearningError('Inlärningsfilen har för många regler och har lämnats orörd')
        return data

    def _save(self, data: dict) -> None:
        content = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
        if len(content) > MAX_BYTES:
            raise LearningError('Inlärningsfilen skulle bli för stor')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.learning-', suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
            if self.path.is_symlink():
                raise LearningError('Inlärningsfilen får inte vara en symbolisk länk')
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def status(self) -> dict:
        with _LOCK:
            data = self._load()
            contexts = data['contexts']
            return {'enabled': data['enabled'],
                    'rules': sum(len(rules) for rules in contexts.values()),
                    'conflicts': sum(1 for rules in contexts.values() for votes in rules.values() if len(votes) > 1),
                    'contexts': sorted(contexts)}

    def set_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise LearningError('Ogiltigt statusvärde')
        with _LOCK:
            data = self._load()
            data['enabled'] = enabled
            self._save(data)

    def clear(self) -> None:
        with _LOCK:
            data = self._load()  # Okänd eller korrupt fil får inte raderas.
            data['contexts'] = {}
            self._save(data)

    def observe_mapping(self, context: str, mapping: dict[str, str], allowed_fields: Iterable[str]) -> bool:
        """Registrera endast ett godkänt, framgångsrikt resultat från anroparen."""
        allowed = set(allowed_fields)
        if (not isinstance(context, str) or not context or len(context) > 100
                or not isinstance(mapping, dict) or not mapping
                or any(not isinstance(h, str) or not h or len(h) > 200
                       or not isinstance(f, str) or f not in allowed or len(f) > 200
                       for h, f in mapping.items())):
            raise LearningError('Ogiltig mappning för inlärning')
        with _LOCK:
            data = self._load()
            if not data['enabled']:
                return False
            rules = data['contexts'].setdefault(context, {})
            if sum(len(r) for r in data['contexts'].values()) + len(set(mapping) - set(rules)) > MAX_RULES:
                raise LearningError('Inlärningsminnet är fullt')
            for header, field in mapping.items():
                votes = rules.setdefault(header, {})
                votes[field] = min(1000000, votes.get(field, 0) + 1)
            self._save(data)
            return True

    def suggestions(self, context: str, headers: Iterable[str], allowed_fields: Iterable[str]) -> dict[str, str]:
        """Bara exakta rubriker med minst två godkännanden och utan motsägelser."""
        with _LOCK:
            data = self._load()
        if not data['enabled']:
            return {}
        allowed = set(allowed_fields)
        rules = data['contexts'].get(context, {})
        result = {}
        for header in headers:
            votes = rules.get(header, {})
            if len(votes) == 1:
                field, count = next(iter(votes.items()))
                if field in allowed and count >= MIN_CONFIRMATIONS:
                    result[header] = field
        return result

VEHICLE_IMPORT = 'vehicle_import.v1'


def vehicle_mapping_suggestions(store: LearningStore, headers: list[str], initial: dict[str, str],
                                allowed_fields: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    """Fyll dialogen; användaren måste fortfarande kontrollera och godkänna."""
    learned = store.suggestions(VEHICLE_IMPORT, headers, allowed_fields)
    merged = dict(initial)
    applied = []
    for header in headers:
        field = learned.get(header)
        if not field or merged.get(header) == field:
            continue
        # En annan kolumn kan inte tyst tilldelas samma målfält av inlärningen.
        if any(key != header and value == field for key, value in merged.items()):
            continue
        merged[header] = field
        applied.append(header)
    return merged, applied


def learn_vehicle_import(store: LearningStore, mapping: dict[str, str], allowed_fields: Iterable[str],
                         result: dict, expected_fingerprint: str, *, approved_save: bool,
                         protected: bool) -> bool:
    """Bara en slutförd import och ett faktiskt godkännande får ge belägg."""
    if (not approved_save or protected or not expected_fingerprint
            or not result.get('success') or result.get('errors') or result.get('row_errors')
            or result.get('skipped', 0) or result.get('needs_resolution')
            or result.get('needs_year_resolution') or result.get('fingerprint') != expected_fingerprint
            or result.get('mapping_used') != mapping):
        return False
    return store.observe_mapping(VEHICLE_IMPORT, mapping, allowed_fields)
