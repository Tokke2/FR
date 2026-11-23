"""Planera Excelimport med explicita val för varje VIN3-dubblett.

Planeringen är ren: inga filer skrivs förrän alla konflikter är lösta.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Any


def _vin(row: dict) -> str:
    return str(row.get('vin_kod') or '').strip().upper()


def _approval(row: dict) -> str:
    return str(row.get('avgaskrav_tillagg') or '').strip().upper()


def plan_year(year: int, existing: list[dict], incoming: list[dict], choices: dict) -> dict[str, Any]:
    """Planera en årgång; stoppa vid första olösta konflikt utan att skriva.

    Konfliktnyckeln binder valet till innehållet i båda sidor, så en ändrad
    fil eller ett ändrat register inte kan återanvända ett gammalt beslut.
    """
    rows = copy.deepcopy(existing)
    if any(not isinstance(row, dict) or not _vin(row) for row in rows):
        raise ValueError(f'År {year}: befintliga poster saknar VIN3 eller har ogiltigt format')
    by_vin: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_vin.setdefault(_vin(row), []).append(index)
    counts = Counter(_vin(row) for row in incoming)
    ordinals: Counter = Counter()
    imported = updated = skipped = 0
    for original in incoming:
        row = {k: copy.deepcopy(v) for k, v in original.items() if not str(k).startswith('_')}
        vin = _vin(row)
        if not vin:
            skipped += 1
            continue
        ordinal = ordinals[vin]
        ordinals[vin] += 1
        matches = [(i, rows[i]) for i in by_vin.get(vin, [])]
        if not matches:
            by_vin.setdefault(vin, []).append(len(rows))
            rows.append(row)
            imported += 1
            continue
        incoming_approval = _approval(row)
        exact = [(i, r) for i, r in matches if incoming_approval and _approval(r) == incoming_approval]
        if len(exact) == 1:
            target = exact[0]
        elif len(matches) == 1 and not (incoming_approval and _approval(matches[0][1]) and incoming_approval != _approval(matches[0][1])):
            target = matches[0]
        else:
            target = None
        different = (incoming_approval and all(_approval(r) and _approval(r) != incoming_approval for _, r in matches))
        if different:
            allowed = ['keep_both']
        elif target is None:
            allowed = ['keep_both', 'skip']
        else:
            allowed = ['keep_both', 'skip', 'replace', 'merge']
        signature = hashlib.sha256(json.dumps(
            {'incoming': original, 'existing': [r for _, r in matches]},
            ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str,
        ).encode('utf-8')).hexdigest()
        key = (year, vin, ordinal, signature)
        action = choices.get(key)
        # Bakåtkompatibelt bara när en enda inkommande och befintlig post kan
        # identifieras entydigt och inget känt godkännande skiljer sig.
        if action is None and counts[vin] == 1 and len(matches) == 1 and not different:
            action = choices.get((year, vin), choices.get(vin))
        if action not in allowed:
            return {'conflict': {
                'key': key, 'year': year, 'vin_kod': vin,
                'existing': copy.deepcopy(target[1] if target else matches[0][1]),
                'existing_candidates': [copy.deepcopy(r) for _, r in matches],
                'incoming': row, 'source_sheet': original.get('_source_sheet', ''),
                'source_row': original.get('_source_row', ''),
                'different_approval': bool(different), 'allowed_actions': allowed,
            }}
        if action == 'keep_both':
            by_vin[vin].append(len(rows))
            rows.append(row)
            imported += 1
        elif action == 'skip':
            skipped += 1
        else:
            idx, old = target
            previous_sources = old.get('sap_originalvarden')
            previous_sources = dict(previous_sources) if isinstance(previous_sources, dict) else {}
            if action == 'merge':
                for name, value in row.items():
                    if value not in (None, ''):
                        old[name] = value
            else:
                old.update(row)
            incoming_sources = row.get('sap_originalvarden')
            if isinstance(incoming_sources, dict):
                previous_sources.update(incoming_sources)
                old['sap_originalvarden'] = previous_sources
            rows[idx] = old
            updated += 1
    return {'rows': rows, 'imported': imported, 'updated': updated, 'skipped': skipped}
