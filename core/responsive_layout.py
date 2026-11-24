"""Små, Qt-oberoende beräkningar för anpassningsbara layouter."""
from __future__ import annotations


def fit_columns(required: list[int], available: int) -> list[int]:
    """Ge varje kolumn minst sin läsbara bredd; fördela överbliven yta jämnt.

    Om bredden inte räcker blir summan större än vyn och tabellen kan rullas.
    """
    widths = [max(0, int(width)) for width in required]
    if not widths:
        return []
    extra = max(0, int(available) - sum(widths))
    each, remainder = divmod(extra, len(widths))
    return [width + each + (i < remainder) for i, width in enumerate(widths)]


def flow_positions(sizes: list[tuple[int, int]], width: int, spacing: int = 8):
    """Placera synliga objekt radvis utan överlapp; returnera (positioner, höjd)."""
    width, spacing = max(0, int(width)), max(0, int(spacing))
    x = y = line_height = 0
    positions = []
    for item_width, item_height in sizes:
        item_width, item_height = max(0, int(item_width)), max(0, int(item_height))
        if x and x + item_width > width:
            x = 0
            y += line_height + spacing
            line_height = 0
        positions.append((x, y))
        x += item_width + spacing
        line_height = max(line_height, item_height)
    return positions, y + line_height


# ── Kolumnbredder som anpassar sig (skärm- och skärpeomgången) ──────────────

# Ett fält behöver olika mycket plats beroende på vad det innehåller. VIN-koden
# är alltid 17 tecken, en färg kan heta "Svart metallic" och en status är kort.
COLUMN_HINTS = {
    "VIN": 150,
    "VIN-kod": 150,
    "Modell": 150,
    "Fabrikat": 120,
    "Färg": 130,
    "Godkännande": 130,
    "Godkännandenummer": 140,
    "Återförsäljare": 170,
    "Status": 140,
    "År": 60,
}
DEFAULT_COLUMN_WIDTH = 120
MIN_COLUMN_WIDTH = 60


def column_widths(headers, texts=None, available=0, minimum=MIN_COLUMN_WIDTH):
    """Fördela bredden så att rubriken alltid syns och inget klipps i onödan.

    ``texts`` är de längsta värdena per kolumn (frivilligt). Rubriken och det
    längsta värdet jämförs tecken för tecken, vilket är en grov men stabil
    uppskattning som inte kräver Qt. Summan får rymmas i ``available``; om det
    inte går krymps alla kolumner lika mycket, aldrig under ``minimum``.
    """
    headers = list(headers or [])
    if not headers:
        return []
    texts = list(texts or [])
    wanted = []
    for index, header in enumerate(headers):
        hint = COLUMN_HINTS.get(str(header), DEFAULT_COLUMN_WIDTH)
        longest = 0
        if index < len(texts) and texts[index]:
            longest = len(str(texts[index])) * 8 + 24
        wanted.append(max(int(minimum), hint, min(longest, 260)))
    try:
        room = int(available)
    except (TypeError, ValueError):
        room = 0
    if room < 0:
        room = 0
    # Utan känd bredd returneras önskad bredd – inget gissas.
    if room == 0 or sum(wanted) <= room:
        return wanted
    # Krymp proportionellt men behåll den undre gränsen.
    floor_total = minimum * len(wanted)
    if room <= floor_total:
        return [int(minimum)] * len(wanted)
    scale = (room - floor_total) / max(1, sum(wanted) - floor_total)
    return [max(int(minimum), int(round(width * scale))) for width in wanted]


def fits_without_scroll(widths, available, tolerance=2):
    """Sant när tabellen ryms utan vågrät rullning."""
    try:
        total = sum(int(width) for width in widths or [])
        room = int(available)
    except (TypeError, ValueError):
        return True
    return total <= room + max(0, int(tolerance))


def needs_compact(width, minimum=1100):
    """Ska gränssnittet gå över till kompakt läge?"""
    try:
        return int(width) < int(minimum)
    except (TypeError, ValueError):
        return False
