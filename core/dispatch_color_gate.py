"""Fail-closed kontroll av samtliga Dispatch-färger före TS-generering."""
from __future__ import annotations

import math
import unicodedata


def _key(value):
    s = unicodedata.normalize('NFKD', str(value).strip().casefold())
    return ''.join(c for c in s if c.isalnum() and not unicodedata.combining(c))


def _text(value):
    if value is None or isinstance(value, float) and math.isnan(value):
        return ''
    return str(value).strip()


def _plugin(app, name, attr):
    if app is None:
        return None
    result = getattr(app, attr, None)
    if result is not None:
        return result
    for obj in (app, getattr(app, 'plugin_loader', None), getattr(app, 'plugin_manager', None)):
        getter = getattr(obj, 'get_plugin', None)
        if callable(getter):
            try:
                result = getter(name)
                if result is not None:
                    return result
            except Exception:
                continue
    return None


def dispatch_color_errors(app) -> list[str]:
    """Endast exakta, sparade och entydiga kopplingar godtas; inget skrivs."""
    try:
        dispatch = _plugin(app, 'dispatch_viewer', 'dispatch_viewer') or getattr(app, 'dispatch_tab', None)
        colors = _plugin(app, 'colors_manager', 'colors_manager') or getattr(app, 'colors', None)
        if dispatch is None or colors is None:
            return ['Dispatch eller färgregistret är inte tillgängligt.']
        frame = dispatch.get_current_data()
        if frame is None or frame.empty:
            return ['Ingen Dispatch-fil är inläst.']
        columns = list(frame.columns)
        names = [c for c in columns if _key(c) in {'color', 'colour', 'farg', 'colorname', 'colourname', 'fargnamn'}]
        codes = [c for c in columns if _key(c) in {'colorcode', 'colourcode', 'fargkod'}]
        if len(names) > 1 or len(codes) > 1 or not (names or codes):
            return ['Dispatch-färgens kolumner saknas eller är tvetydiga.']
        service = colors.service
        service.load()  # Läs aktuella filer; korrupt eller otillgängligt är alltid stopp.
        known = service.get_all()
        by_code = {c.code.casefold(): c for c in known if c.code}
        problems = []
        seen = set()
        for row in frame.to_dict(orient='records'):
            name = _text(row.get(names[0])) if names else ''
            code = _text(row.get(codes[0])) if codes else ''
            pair = (code, name)
            if pair in seen:
                continue
            seen.add(pair)
            if codes:
                if not code or code.casefold() not in by_code:
                    problems.append(f'{code or "(tom färgkod)"}: saknas i färgregistret')
                    continue
                record = by_code[code.casefold()]
                if names and (not name or name.casefold() != record.name.casefold()):
                    problems.append(f'{code}: färgkoden och namnet stämmer inte entydigt')
                    continue
                name = record.name
            if not name:
                problems.append('(tomt färgnamn): färgkoppling saknas')
                continue
            lookup = service.lookup_ts_code_detailed(name)
            if lookup.match_type != 'exact' or not lookup.ts_code:
                problems.append(f'{name}: saknar en entydigt sparad TS-koppling')
        if problems:
            return [f'{len(problems)} Dispatch-färger kräver åtgärd: ' + '; '.join(problems[:20])
                    + ('; …' if len(problems) > 20 else '')]
        return []
    except Exception as exc:
        return [f'Dispatch-färgerna kunde inte kontrolleras: {exc}']


def dispatch_vehicle_color_errors(app, vehicles) -> list[str]:
    """Kontrollera att genererade fordons färgvärden motsvarar aktuell Dispatch."""
    errors = dispatch_color_errors(app)
    if errors:
        return errors
    try:
        dispatch = _plugin(app, 'dispatch_viewer', 'dispatch_viewer') or getattr(app, 'dispatch_tab', None)
        colors = _plugin(app, 'colors_manager', 'colors_manager') or getattr(app, 'colors', None)
        frame = dispatch.get_current_data()
        columns = list(frame.columns)
        vin_keys = {'vin', 'vincode', 'vinnumber', 'vehicleidentificationnumber', 'chassis',
                    'chassisnumber', 'vinno', 'vehicleid', 'chassinummer', 'chassi'}
        vins = [c for c in columns if _key(c) in vin_keys]
        if len(vins) != 1:
            return ['Dispatch saknar entydig VIN-kolumn för kontroll av fordonsfärg.']
        names = [c for c in columns if _key(c) in {'color', 'colour', 'farg', 'colorname', 'colourname', 'fargnamn'}]
        codes = [c for c in columns if _key(c) in {'colorcode', 'colourcode', 'fargkod'}]
        by_code = {color.code.casefold(): color for color in colors.service.get_all() if color.code}
        rows_by_vin = {}
        for row in frame.to_dict(orient='records'):
            vin = _text(row.get(vins[0])).upper()
            if vin:
                rows_by_vin.setdefault(vin, []).append(row)
        for vehicle in vehicles:
            if not isinstance(vehicle, dict):
                return ['Fordonslistan har ett ogiltigt format.']
            data = vehicle.get('data') if isinstance(vehicle.get('data'), dict) else {}
            vin = _text(vehicle.get('vin') or vehicle.get('VIN') or vehicle.get('_vin') or data.get('vin')).upper()
            matched = rows_by_vin.get(vin, [])
            if not vin or len(matched) != 1:
                return [f'VIN {vin or "(saknas)"} har ingen entydig rad i Dispatch.']
            row = matched[0]
            if codes:
                color = by_code.get(_text(row.get(codes[0])).casefold())
                if color is None:
                    return [f'Färgen för VIN {vin} saknas i färgregistret.']
                name = color.name
            else:
                name = _text(row.get(names[0]))
            expected = colors.service.lookup_ts_code(name)
            actual = _text(vehicle.get('color_ts_code') or data.get('color_ts_code')).upper()
            if not expected or actual != expected.upper():
                return [f'TS-färgen för VIN {vin} saknas eller stämmer inte med Dispatch och färgfliken.']
        return []
    except Exception as exc:
        return [f'Fordonsfärgerna kunde inte kontrolleras: {exc}']
