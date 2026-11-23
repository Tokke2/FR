"""Granskning av underlaget för PT45 och spärr för icke verifierade TS-filer.

Positionerna kommer från de bifogade bilderna av Transportstyrelsens
13.2-postbeskrivning för MC/moped enligt 168/2013/EG, sidorna 1–4.
Jämförelse av intervall är INTE bevis för att fältens namn, typer, obligatoriska
värden, kodtabeller eller hela filformatet är korrekta.
"""
from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# En post per tabellrad i underlaget: (första position, sista position).
PT45_MC_MOPED_LAYOUT = (
    (1, 4), (5, 6), (7, 16), (17, 22), (23, 26), (27, 106),
    (107, 114), (115, 118), (119, 122), (123, 146), (147, 149),
    (150, 155), (156, 179), (180, 219), (220, 259), (260, 283),
    (284, 291), (292, 308), (309, 333), (334, 341), (342, 349),
    (350, 351), (352, 354), (355, 361), (362, 366), (367, 371),
    (372, 375), (376, 381), (382, 387), (388, 393), (394, 399),
    (400, 405), (406, 410), (411, 415), (416, 421), (422, 426),
    (427, 432), (433, 437), (438, 443), (444, 449), (450, 459),
    (460, 464), (465, 469), (470, 489), (490, 509), (510, 510),
    (511, 516), (517, 519), (520, 524), (525, 527), (528, 530),
    (531, 535), (536, 538), (539, 568), (569, 570), (571, 576),
    (577, 577), (578, 578), (579, 579), (580, 584), (585, 589),
    (590, 594), (595, 600), (601, 606), (607, 2500),
)


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def generation_block_reason(root=None) -> str:
    """Spärra TS-generering tills ett riktigt underlag verifierats.

    Godkännandet hanteras av :mod:`core.ts_verification`, binds till underlagets
    SHA-256 och måste finnas i programmets rotmapp. Saknas det – eller om det är
    skadat – är genereringen spärrad.
    """
    if root is None:
        root = _default_root()
    if root is not None:
        try:
            from core.ts_verification import approval
            if approval(Path(root)) is not None:
                return ''
        except Exception as exc:  # ett trasigt godkännande spärrar, aldrig tvärtom
            _log.warning('TS-godkännandet kunde inte kontrolleras: %s', exc)
    return ('TS-genereringen är spärrad: PT45 för MC/moped är ännu inte '
            'fullständigt verifierad mot ett riktigt underlag och '
            'postbeskrivningarna för PT28 och PT99 saknas. Ingen TS-fil har '
            'skapat eller ändrats. Verifiera underlaget via Verktyg → '
            'Verifiera TS-underlag.')


def audit_pt45_schema(schema) -> list[str]:
    """Jämför samtliga fältintervall med underlaget; godkänner inte formatet."""
    if schema is None:
        return ['PT45-schema saknas.']
    try:
        if int(getattr(schema, 'total_length')) != 2500:
            return ['PT45-schemats postlängd är inte 2500.']
        fields = list(getattr(schema, 'fields'))
        actual = sorted((int(field.position), int(field.position) + int(field.length) - 1) for field in fields)
    except (AttributeError, TypeError, ValueError):
        return ['PT45-schemats fält eller positioner kunde inte läsas.']
    expected = list(PT45_MC_MOPED_LAYOUT)
    if actual == expected:
        return []
    missing = [f'{a}–{b}' for a, b in expected if (a, b) not in actual]
    extra = [f'{a}–{b}' for a, b in actual if (a, b) not in expected]
    errors = []
    if missing:
        errors.append('Saknade eller ändrade fältintervall: ' + ', '.join(missing))
    if extra:
        errors.append('Okända eller överlappande fältintervall: ' + ', '.join(extra))
    if len(actual) != len(set(actual)):
        errors.append('Dubblerade fältintervall.')
    return errors


def audit_pt45_record(record: str, sequence_no: int, vin: str) -> list[str]:
    """Kontrollera några säkert läsbara indatafält; inte en fullständig validering."""
    if not isinstance(record, str) or len(record) != 2500:
        return ['PT45-posten är inte exakt 2500 tecken.']
    errors = []
    if not (isinstance(sequence_no, int) and 1 <= sequence_no <= 9999) or record[:4] != f'{sequence_no:04d}':
        errors.append('Löpnummer ska ligga på position 1–4.')
    if record[4:6] != '45':
        errors.append('Posttyp 45 ska ligga på position 5–6.')
    if record[16:114] != ' ' * 98:
        errors.append('Svarsfälten position 17–114 ska lämnas blanka i indata.')
    if len(vin) != 17 or record[291:308] != vin:
        errors.append('VIN ska ligga på position 292–308 och vara 17 tecken.')
    if record[375:381] != '000000':
        errors.append('Reservfältet position 376–381 ska vara 000000.')
    if '\n' in record or '\r' in record:
        errors.append('Posten innehåller radbrytning.')
    try:
        record.encode('iso-8859-1')
    except UnicodeEncodeError:
        errors.append('Posten kan inte kodas som Latin-1.')
    return errors
