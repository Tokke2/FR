"""Rita en förhandsvisning av Fordonsregs tema utan Qt.

Bilden används som granskningsunderlag: den visar palett, typsnitt, ikoner,
sidomeny, tabell, knappar och fält i mörkt respektive ljust tema.

    python tools/theme_preview.py docs/tema.png
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import theme as design  # noqa: E402

WINDOW_W, WINDOW_H = 980, 620
SIDEBAR_W = 230


def render_icon(name: str, color: str, size: int = 18):
    """Rendera en riktig SVG-ikon och färga den med temats färg."""
    from PIL import Image

    path = design.icon_path(ROOT, name)
    if path is None:
        return None
    source = path.read_text(encoding='utf-8')
    tinted = source.replace('stroke="#ffffff"', f'stroke="{color}"')
    tinted = tinted.replace('fill="#ffffff"', f'fill="{color}"')
    try:
        import resvg_py

        png = resvg_py.svg_to_bytes(svg_string=tinted, width=size, height=size)
        from io import BytesIO

        return Image.open(BytesIO(bytes(png))).convert('RGBA')
    except Exception:
        return None


def _mix(first: str, second: str, amount: float) -> str:
    """Blanda två färger (0 = första, 1 = andra)."""
    a = first.lstrip('#')
    b = second.lstrip('#')
    channels = []
    for index in (0, 2, 4):
        left = int(a[index:index + 2], 16)
        right = int(b[index:index + 2], 16)
        channels.append(round(left + (right - left) * amount))
    return '#%02x%02x%02x' % tuple(channels)


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold
        else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text(draw, xy, text, font, color):
    draw.text(xy, text, font=font, fill=color)


def _button(draw, box, label, font, colors, kind='default'):
    from PIL import ImageDraw

    left, top, right, bottom = box
    if kind == 'primary':
        fill, text = colors['accent'], colors['accent_text']
    elif kind == 'success':
        fill, text = colors['success'], '#0b1a12'
    else:
        fill, text = colors['surface_alt'], colors['text']
    draw.rounded_rectangle(box, radius=6, fill=fill, outline=colors['border'])
    width = draw.textlength(label, font=font)
    _text(draw, (left + (right - left - width) / 2, top + 7), label, font, text)


def _chip(draw, box, label, font, colors, active: bool) -> None:
    """Ett snabbfilterchip, som i tabellen."""
    fill = colors['accent'] if active else colors['surface_alt']
    text = colors['accent_text'] if active else colors['text']
    draw.rounded_rectangle(box, radius=12, fill=fill, outline=colors['border'])
    width = draw.textlength(label, font=font)
    _text(draw, (box[0] + (box[2] - box[0] - width) / 2, box[1] + 3), label, font, text)


def draw_theme(colors: dict[str, str], title: str, font_family: str,
               density: str = 'comfortable', row_mode: str = 'normal',
               icon_only: bool = False, icon_size: int = 16) -> 'object':
    from PIL import Image, ImageDraw

    compact = density == 'compact'
    row_px = design.row_height(row_mode) if not compact else design.row_height('compact')
    pad = 12 if compact else 18

    image = Image.new('RGB', (WINDOW_W + 40, WINDOW_H + 70), colors['shadow'])
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((20, 20, 20 + WINDOW_W, 20 + WINDOW_H), radius=12,
                           fill=colors['window'], outline=colors['border'])
    left, top = 20, 20

    # Menyrad
    draw.rectangle((left + 1, top + 1, left + WINDOW_W - 1, top + 34), fill=colors['surface'])
    draw.line((left + 1, top + 34, left + WINDOW_W - 1, top + 34), fill=colors['border'])
    x = left + 16
    for label in ('Arkiv', 'Schema', 'Visa', 'Inställningar', 'Verktyg', 'Hjälp'):
        _text(draw, (x, top + 10), label, _font(13), colors['text'])
        x += draw.textlength(label, font=_font(13)) + 26

    # Sidomeny. I kompakt läge visas bara ikonerna, precis som i programmet.
    sidebar_w = 64 if icon_only else SIDEBAR_W
    draw.rectangle((left + 1, top + 35, left + sidebar_w, top + WINDOW_H - 1), fill=colors['sidebar'])
    if icon_only:
        _text(draw, (left + 14, top + 54), 'FR', _font(17, True), colors['accent'])
    else:
        _text(draw, (left + 20, top + 54), 'Fordonsreg', _font(19, True), colors['accent'])

    rows = (('vehicle', 'Fordonsdata'), ('schema', 'TS Schema'), ('table', 'Data Viewer'),
            ('dealers', 'Återförsäljare'), ('colors', 'Färger'), ('dispatch', 'Dispatch Import'),
            ('generate', 'Generera TS-fil'), ('reports', 'Rapporter'))
    y = top + 96
    step = 30 if compact else 36
    icon_x = left + (20 if icon_only else 16)
    for index, (icon_name, label) in enumerate(rows):
        active = index == 0
        if active:
            draw.rectangle((left + 1, y - 7, left + sidebar_w, y + 25), fill=colors['sidebar_active'])
            draw.rectangle((left + 1, y - 7, left + 4, y + 25), fill=colors['accent'])
        colour = colors['text'] if active else colors['text_muted']
        glyph = render_icon(icon_name, colour, icon_size)
        if glyph is not None:
            image.paste(glyph, (icon_x, y - 1), glyph)
        else:
            draw.rounded_rectangle((icon_x, y, icon_x + icon_size, y + icon_size), radius=3,
                                   outline=colour, width=2)
        if not icon_only:
            _text(draw, (icon_x + icon_size + 10, y), label, _font(13, active), colour)
        y += step
    if not icon_only:
        _text(draw, (left + 16, y + 12), 'TS SCHEMA', _font(9, True), colors['text_muted'])
        _text(draw, (left + 16, y + 30), 'v1.6 · 42 posttyper', _font(10), colors['text_muted'])
        _text(draw, (left + 16, y + 54), 'STATISTIK', _font(9, True), colors['text_muted'])
        _text(draw, (left + 16, y + 72), '128 fordon · 3 år', _font(10), colors['text_muted'])

    # Innehåll
    content_left = left + sidebar_w + 26
    _text(draw, (content_left, top + 56), 'Fordonsdata', _font(23, True), colors['text'])
    _text(draw, (content_left, top + 90), '128 fordon i 3 årsflikar · senast uppdaterad i dag',
          _font(11), colors['text_muted'])

    # Verktygsrad
    bx = content_left
    for label, kind in (('Importera', 'primary'), ('Exportera', 'default'),
                        ('Uppdatera', 'default'), ('Spara', 'success')):
        width = max(96, int(draw.textlength(label, font=_font(12))) + 34)
        _button(draw, (bx, top + 116, bx + width, top + 148), label, _font(12), colors, kind)
        bx += width + 10

    # Sökfält
    field = (content_left, top + 158, content_left + 320, top + 190)
    draw.rounded_rectangle(field, radius=6, fill=colors['surface'], outline=colors['border'])
    _text(draw, (field[0] + 12, field[1] + 8), 'Sök VIN-kod, modell eller färg…', _font(11), colors['text_muted'])
    focus = (content_left + 336, top + 158, content_left + 336 + 150, top + 190)
    draw.rounded_rectangle(focus, radius=6, fill=colors['surface'], outline=colors['accent'])
    _text(draw, (focus[0] + 12, focus[1] + 8), 'Fält med fokus', _font(11), colors['text'])

    # Snabbfilter ovanför tabellen (förslag 9)
    chip_y = top + 198
    chip_x = content_left
    for label, active in (('Ofullständiga', False), ('Saknar färg', True),
                          ('Saknar approval', False)):
        width = int(draw.textlength(label, font=_font(10))) + 22
        _chip(draw, (chip_x, chip_y, chip_x + width, chip_y + 22), label, _font(10),
              colors, active)
        chip_x += width + 6

    # Tabell
    table = (content_left, top + 232, left + WINDOW_W - 24, top + 470)
    draw.rounded_rectangle(table, radius=8, fill=colors['surface'], outline=colors['border'])
    columns = ('VIN-kod', 'Modell', 'År', 'Färg', 'Godkännande')
    widths = (150, 170, 70, 130, 150)
    draw.rectangle((table[0] + 1, table[1] + 1, table[2] - 1, table[1] + 34), fill=colors['surface_alt'])
    draw.line((table[0] + 1, table[1] + 34, table[2] - 1, table[1] + 34), fill=colors['border_strong'])
    cx = table[0] + 14
    for label, width in zip(columns, widths):
        _text(draw, (cx, table[1] + 10), label, _font(11, True), colors['text_muted'])
        cx += width
    data = (('YAJ4M123456', 'TADEGA 45', '2026', 'Polarvit', 'e5*2007/46'),
            ('YAJ7N654321', 'TADEGA 35', '2025', 'Svart metallic', 'e5*2007/46'),
            ('YAJ2P987654', 'TADEGA 25', '2024', 'Röd', 'e5*2007/46'),
            ('YAJ9R111222', 'TADEGA 55', '2023', 'Blå metallic', 'e5*2007/46'))
    y = table[1] + 44
    for index, row in enumerate(data):
        if index % 2:
            draw.rectangle((table[0] + 1, y - 6, table[2] - 1, y + 28), fill=colors['surface_alt'])
        if index == 1:
            draw.rectangle((table[0] + 1, y - 6, table[2] - 1, y + 28), fill=colors['selection'])
        cx = table[0] + 14
        for value, width in zip(row, widths):
            _text(draw, (cx, y), value, _font(11), colors['text'])
            cx += width
        y += row_px

    # Statusrad under tabellen (förslag 10)
    _text(draw, (content_left, top + 478),
          '8 fordon · 5 fullständiga · 3 ofullständiga · 3 saknar färg',
          _font(10), colors['text_muted'])

    # Ikonrad: alla ikoner i temats färg, i två storlekar (förslag 11)
    icon_y = top + 520
    icon_x = content_left
    _text(draw, (content_left, icon_y - 22), 'IKONER', _font(9, True), colors['text_muted'])
    for name in design.ICON_NAMES:
        glyph = render_icon(name, colors['text_muted'], design.ICON_SIZE_REGULAR)
        if glyph is not None:
            image.paste(glyph, (icon_x, icon_y), glyph)
        icon_x += 30

    # Flikar
    tab_y = top + 560
    for index, label in enumerate(('2026', '2025', '2024', 'Arkiv')):
        tx = content_left + index * 84
        colour = colors['text'] if index == 0 else colors['text_muted']
        _text(draw, (tx, tab_y), label, _font(12, index == 0), colour)
        if index == 0:
            draw.line((tx, tab_y + 22, tx + 32, tab_y + 22), fill=colors['accent'], width=3)

    # Statusrad
    draw.rectangle((left + 1, top + WINDOW_H - 30, left + WINDOW_W - 1, top + WINDOW_H - 1),
                   fill=colors['surface'])
    draw.line((left + 1, top + WINDOW_H - 30, left + WINDOW_W - 1, top + WINDOW_H - 30),
              fill=colors['border'])
    _text(draw, (left + 14, top + WINDOW_H - 23), 'Klar · 128 fordon inlästa · inga fel', _font(10),
          colors['text_muted'])
    _text(draw, (left + WINDOW_W - 150, top + WINDOW_H - 23), 'PIN-skydd aktivt', _font(10),
          colors['text_muted'])

    # Rubrik under bilden
    _text(draw, (20, WINDOW_H + 32), title, _font(14, True), '#e7edf3')
    detail = (f'{font_family} · accent {colors["accent"]} · radhöjd {row_px} px · '
              f'ikoner 16/24 px')
    _text(draw, (20 + draw.textlength(title, font=_font(14, True)) + 16, WINDOW_H + 34),
          detail, _font(11), '#a7b4c2')
    # Ärlighetsprincipen: bilden är en illustration, inte en riktig körning.
    note = 'Illustration av temat – inte exempeldata från en riktig körning.'
    _text(draw, (WINDOW_W + 20 - draw.textlength(note, font=_font(9)) - 4, WINDOW_H + 36),
          note, _font(9), '#6d7b8a')
    return image


# Fyra varianter: båda temana, kompakt läge och ikonmeny. Det gör att
# skillnaderna kan granskas utan att Qt behöver startas.
VARIANTS = (
    ('dark', 'Mörkt tema', 'comfortable', 'normal', False),
    ('light', 'Ljust tema', 'comfortable', 'normal', False),
    ('dark', 'Mörkt tema, kompakt', 'compact', 'compact', False),
    ('dark', 'Mörkt tema, ikonmeny', 'compact', 'compact', True),
)


def main() -> int:
    from PIL import Image

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'docs' / 'tema.png'
    target.parent.mkdir(parents=True, exist_ok=True)
    if '--state' in sys.argv:
        index = sys.argv.index('--state')
        target = Path(sys.argv[index + 1])
        choice = int(sys.argv[index + 2]) if len(sys.argv) > index + 2 else 0
        theme_name, title, density, row_mode, icon_only = VARIANTS[choice % len(VARIANTS)]
        image = draw_theme(design.palette(theme_name), title, design.font_family('win32'),
                           density=density, row_mode=row_mode, icon_only=icon_only)
        image.save(target)
        print(target)
        return 0
    images = [draw_theme(design.palette(name), title, design.font_family('win32'),
                         density=density, row_mode=row_mode, icon_only=icon_only)
              for name, title, density, row_mode, icon_only in VARIANTS]
    canvas = Image.new('RGB', (WINDOW_W + 40, (WINDOW_H + 70) * len(images)), '#0b0f14')
    for index, image in enumerate(images):
        canvas.paste(image, (0, (WINDOW_H + 70) * index))
    canvas.save(target)
    print(target)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
