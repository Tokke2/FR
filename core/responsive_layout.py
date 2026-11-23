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
