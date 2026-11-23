"""Planera återförsäljarimport utan skrivning eller tyst ersättning."""
from __future__ import annotations

from core.tabular_import import ImportFormatError, Table
from plugins.vehicle_registry.excel_importer import _normalize_column_name

from core.dealer_fields import FIELDS
CONTEXT = 'dealer_import.v1'


def plan(table: Table, mapping: dict[str, str], existing: list[dict], decisions: dict[str, str] | None = None) -> dict:
    decisions = decisions or {}
    allowed = set(FIELDS)
    if any(field not in allowed for field in mapping.values()):
        raise ImportFormatError('Mappningen innehåller ett okänt målfält')
    if len(set(mapping.values())) != len(mapping):
        raise ImportFormatError('Flera kolumner är mappade till samma fält')
    if not {'dealer_number', 'namn'}.issubset(mapping.values()):
        raise ImportFormatError('Dealer Number och Namn måste vara mappade')
    columns = {mapping[key]: i for i, header in enumerate(table.headers)
               if (key := _normalize_column_name(header)) in mapping}
    if not {'dealer_number', 'namn'}.issubset(columns):
        raise ImportFormatError('De nödvändiga kolumnerna finns inte i filen')
    updated = [dict(row) for row in existing]
    by_dn: dict[str, list[int]] = {}
    for i, row in enumerate(updated):
        dn = str(row.get('dealer_number', row.get('dn', ''))).strip().upper()
        if dn:
            by_dn.setdefault(dn, []).append(i)
    seen = set(); conflicts = []; added = changed = unchanged = skipped = 0
    for row_number, row in enumerate(table.rows, 2):
        values = {field: row[i].strip() for field, i in columns.items()}
        dn = values['dealer_number'].upper()
        if not dn or not values['namn']:
            raise ImportFormatError(f'Rad {row_number} saknar dealer number eller namn; inget importerades')
        if dn in seen:
            raise ImportFormatError(f'Dealernummer {dn} förekommer flera gånger i filen; inget importerades')
        seen.add(dn)
        matches = by_dn.get(dn, [])
        incoming = dict(values)
        incoming['dealer_number'] = dn
        if not matches:
            incoming.setdefault('orgnr', '')
            updated.append(incoming); added += 1
            continue
        if len(matches) != 1:
            raise ImportFormatError(f'Dealernummer {dn} förekommer flera gånger i registret; inget importerades')
        old = updated[matches[0]]
        if all(str(old.get(k, '')).strip() == v for k, v in incoming.items() if k != 'dealer_number'):
            unchanged += 1
            continue
        choice = decisions.get(dn)
        if choice is None:
            conflicts.append({'dn': dn, 'existing': dict(old), 'incoming': incoming})
        elif choice == 'skip':
            skipped += 1
        elif choice == 'replace':
            updated[matches[0]] = {**old, **incoming}
            changed += 1
        else:
            raise ImportFormatError('Ogiltigt konfliktval')
    return {'rows': updated, 'conflicts': conflicts, 'added': added, 'changed': changed,
            'unchanged': unchanged, 'skipped': skipped}
