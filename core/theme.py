"""Design, typsnitt, ikoner, skärmbredd och tema för Fordonsreg.

Modulen är delad i två lager:

* **Rena beräkningar** (paletter, typsnittsval, storlekar, stilark som text) –
  de importerar aldrig Qt och kan därför testas utan PySide6.
* **Tunna Qt-hjälpare** (``icon``, ``apply_font``, ``apply_stylesheet``) som
  importerar Qt först när de används.

Allt som rör utseende ska hämtas härifrån. Ingen annan fil ska behöva skriva
egna färgkoder eller typsnittsnamn, vilket gör att mörkt och ljust tema följer
med överallt och att kontrasten kan kontrolleras på ett ställe.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Final, Iterable

THEME_MODES: Final[tuple[str, ...]] = ("dark", "light", "auto")
THEME_LABELS: Final[dict[str, str]] = {
    "dark": "Mörkt",
    "light": "Ljust",
    "auto": "Följ systemet",
}
DEFAULT_MODE: Final[str] = "auto"

# ── Paletter ────────────────────────────────────────────────────────────────
# Varje palett innehåller exakt samma nycklar, så stilarket kan byggas utan
# villkor. Text-färgerna är valda för minst 4,5:1 mot sin bakgrund.
PALETTES: Final[dict[str, dict[str, str]]] = {
    "dark": {
        "window": "#151a21",
        "surface": "#1c232c",
        "surface_alt": "#232c37",
        "surface_hover": "#2c3743",
        "sidebar": "#10151b",
        "sidebar_active": "#1f2a36",
        "border": "#41505f",
        "border_strong": "#6b8299",
        "text": "#e7edf3",
        "text_muted": "#a7b4c2",
        "text_disabled": "#8b99a8",
        "accent": "#2f9ff0",
        "accent_hover": "#4db2f5",
        "accent_text": "#08131d",
        "success": "#37c26f",
        "warning": "#e8a33d",
        "danger": "#ef5b5b",
        "info": "#43bfd0",
        "selection": "#274a63",
        "shadow": "#0b0f14",
    },
    "light": {
        "window": "#eef2f6",
        "surface": "#ffffff",
        "surface_alt": "#f4f7fa",
        "surface_hover": "#e6edf4",
        "sidebar": "#e3eaf1",
        "sidebar_active": "#ffffff",
        "border": "#b3c0cd",
        "border_strong": "#748898",
        "text": "#16222d",
        "text_muted": "#4d5f70",
        "text_disabled": "#6b7885",
        "accent": "#1668a8",
        "accent_hover": "#12598f",
        "accent_text": "#ffffff",
        "success": "#1b7f4b",
        "warning": "#8a5a00",
        "danger": "#b3261e",
        "info": "#0d6b7a",
        "selection": "#cfe4f6",
        "shadow": "#c3ced9",
    },
}

# ── Typsnitt ────────────────────────────────────────────────────────────────
# Systemets eget gränssnittstypsnitt först: det ser inbyggt ut, har full
# teckentäckning och renderas skarpt på högupplösta skärmar.
FONT_CANDIDATES: Final[dict[str, tuple[str, ...]]] = {
    "win32": (
        "Segoe UI Variable Text", "Segoe UI", "Tahoma", "Arial",
    ),
    "darwin": (
        "SF Pro Text", "Helvetica Neue", "Helvetica", "Arial",
    ),
    "linux": (
        "Inter", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans", "Liberation Sans",
    ),
}
FONT_FALLBACK: Final[str] = "sans-serif"
MONO_CANDIDATES: Final[dict[str, tuple[str, ...]]] = {
    "win32": ("Cascadia Mono", "Consolas", "Courier New"),
    "darwin": ("SF Mono", "Menlo", "Monaco"),
    "linux": ("JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", "Liberation Mono"),
}
MONO_FALLBACK: Final[str] = "monospace"

MIN_FONT_SIZE: Final[int] = 9
MAX_FONT_SIZE: Final[int] = 18
DEFAULT_FONT_SIZE: Final[int] = 10

# Radie, luft och kontrollhöjd i pixlar. Samma mått används i hela gränssnittet
# så att knappar, fält och tabeller linjerar.
RADIUS: Final[int] = 8
RADIUS_SMALL: Final[int] = 6
GAP: Final[int] = 8
CONTROL_HEIGHT: Final[int] = 32


def system_platform(platform: str | None = None) -> str:
    """Returnera nyckeln till rätt typsnittslista."""
    name = (platform or sys.platform).lower()
    if name.startswith("win"):
        return "win32"
    if name.startswith("darwin"):
        return "darwin"
    return "linux"


def font_family(platform: str | None = None, available: Iterable[str] | None = None) -> str:
    """Välj första tillgängliga typsnitt, annars en generisk reserv.

    ``available`` används av Qt-hjälparna för att fråga vilka typsnitt som
    faktiskt finns installerat. Utan lista returneras den ordning
    operativsystemet normalt erbjuder.
    """
    candidates = FONT_CANDIDATES[system_platform(platform)]
    if available is None:
        return candidates[0]
    installed = {name.casefold() for name in available}
    for name in candidates:
        if name.casefold() in installed:
            return name
    return candidates[-1]


def mono_family(platform: str | None = None, available: Iterable[str] | None = None) -> str:
    """Motsvarande val för fast bredd (loggar, tekniska värden)."""
    candidates = MONO_CANDIDATES[system_platform(platform)]
    if available is None:
        return candidates[0]
    installed = {name.casefold() for name in available}
    for name in candidates:
        if name.casefold() in installed:
            return name
    return candidates[-1]


def font_chain(platform: str | None = None) -> str:
    """Hela typsnittskedjan som Qt kan tolka, i prioritetsordning."""
    return ", ".join(FONT_CANDIDATES[system_platform(platform)]) + f", {FONT_FALLBACK}"


def mono_chain(platform: str | None = None) -> str:
    return ", ".join(MONO_CANDIDATES[system_platform(platform)]) + f", {MONO_FALLBACK}"


def clamp_font_size(size: Any, default: int = DEFAULT_FONT_SIZE) -> int:
    """Håll textstorleken inom läsbara gränser, även om konfigurationen är trasig."""
    try:
        value = int(size)
    except (TypeError, ValueError):
        return default
    return max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, value))


def scaled_font_size(base: int, dpi_ratio: float = 1.0) -> int:
    """Skalning för högupplösta skärmar utan att texten blir för stor."""
    base = clamp_font_size(base)
    try:
        ratio = float(dpi_ratio)
    except (TypeError, ValueError):
        ratio = 1.0
    if ratio <= 1.0:
        return base
    return clamp_font_size(round(base * min(ratio, 1.5)))


def resolve_mode(mode: str | None, system_is_dark: bool = True) -> str:
    """Avgör vilket tema som ska användas: ``dark`` eller ``light``."""
    value = (mode or DEFAULT_MODE).strip().lower()
    if value not in THEME_MODES:
        value = DEFAULT_MODE
    if value == "auto":
        return "dark" if system_is_dark else "light"
    return value


def palette(theme: str = "dark") -> dict[str, str]:
    """Returnera en kopia av paletten så att anroparen inte kan ändra den."""
    return dict(PALETTES["light" if theme == "light" else "dark"])


def _relative_luminance(color: str) -> float:
    """WCAG-luminans för ``#rrggbb``."""
    value = color.lstrip("#")
    channels = []
    for index in (0, 2, 4):
        part = int(value[index:index + 2], 16) / 255
        channels.append(part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    """Kontrast mellan två färger enligt WCAG (1–21)."""
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


# ── Skärmbredd ──────────────────────────────────────────────────────────────

MIN_WINDOW_WIDTH: Final[int] = 960
MIN_WINDOW_HEIGHT: Final[int] = 600
PREFERRED_WIDTH: Final[int] = 1400
PREFERRED_HEIGHT: Final[int] = 900


def window_size(available_width: int, available_height: int,
                preferred: tuple[int, int] = (PREFERRED_WIDTH, PREFERRED_HEIGHT)) -> tuple[int, int]:
    """Anpassa fönstret till skärmen i stället för att kräva 1400×900.

    Fönstret tar högst 90 % av skärmens arbetsyta, aldrig mer än den
    föredragna storleken, och aldrig mindre än minimimåtten – men minimimåtten
    får inte heller överskrida skärmen. Resultatet blir alltid ett fönster som
    ryms, även på en liten bärbar datorskärm.
    """
    try:
        width = int(available_width)
        height = int(available_height)
    except (TypeError, ValueError):
        return preferred
    if width <= 0 or height <= 0:
        return preferred
    usable_w = max(1, int(width * 0.90))
    usable_h = max(1, int(height * 0.90))
    target_w = min(preferred[0], usable_w)
    target_h = min(preferred[1], usable_h)
    min_w = min(MIN_WINDOW_WIDTH, usable_w)
    min_h = min(MIN_WINDOW_HEIGHT, usable_h)
    return max(target_w, min_w), max(target_h, min_h)


def sidebar_width(window_width: int) -> int:
    """Sidomenyn krymper på smala skärmar så att innehållet får plats."""
    try:
        width = int(window_width)
    except (TypeError, ValueError):
        width = PREFERRED_WIDTH
    if width < 1100:
        return 180
    if width < 1400:
        return 210
    return 240


def content_margins(window_width: int) -> tuple[int, int, int, int]:
    """Luft runt innehållet: tightare i smala fönster, luftigare i breda."""
    try:
        width = int(window_width)
    except (TypeError, ValueError):
        width = PREFERRED_WIDTH
    side = 10 if width < 1100 else (14 if width < 1500 else 18)
    return side, 10, side, 10


# ── Densitet (förslag 1, 8 och 13) ──────────────────────────────────────────

DENSITY_MODES: Final[tuple[str, ...]] = ("comfortable", "compact", "auto")
DENSITY_LABELS: Final[dict[str, str]] = {
    "comfortable": "Luftig",
    "compact": "Kompakt",
    "auto": "Automatisk",
}
DEFAULT_DENSITY: Final[str] = "auto"
# Under den här bredden (och på låga skärmar) väljs kompakt läge automatiskt.
COMPACT_BREAKPOINT: Final[int] = 1100
COMPACT_HEIGHT_BREAKPOINT: Final[int] = 800

TABLE_ROW_MODES: Final[tuple[str, ...]] = ("compact", "normal", "airy")
TABLE_ROW_LABELS: Final[dict[str, str]] = {
    "compact": "Kompakt",
    "normal": "Normal",
    "airy": "Luftig",
}
DEFAULT_ROW_MODE: Final[str] = "normal"
ROW_HEIGHTS: Final[dict[str, int]] = {"compact": 24, "normal": 32, "airy": 42}
SIDEBAR_ICON_ONLY_BREAKPOINT: Final[int] = 1100
# Sidomenyn går att dra i, men aldrig smalare än ikonerna eller bredare än en
# tredjedel av fönstret.
SIDEBAR_MIN_WIDTH: Final[int] = 48
SIDEBAR_MAX_RATIO: Final[float] = 0.34


def sidebar_max_width(window_width: int) -> int:
    """Övre gräns för sidomenyn, så att innehållet alltid får plats."""
    try:
        return max(SIDEBAR_MIN_WIDTH, int(int(window_width) * SIDEBAR_MAX_RATIO))
    except (TypeError, ValueError):
        return 420


def sidebar_initial_width(saved: Any, window_width: int, density: str = "comfortable") -> int:
    """Välj startbredd: användarens sparade val, annars skärmens förslag."""
    try:
        value = int(saved)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        if density == "compact":
            return design_icon_width()
        return sidebar_width(window_width)
    return max(SIDEBAR_MIN_WIDTH, min(sidebar_max_width(window_width), value))


def design_icon_width() -> int:
    """Bredden när bara ikoner visas."""
    return 64


def resolve_density(mode: str | None, width: int, height: int = 900) -> str:
    """Avgör om gränssnittet ska vara luftigt eller kompakt.

    ``auto`` väljer kompakt när fönstret är smalt eller skärmen låg – det är
    där rullning annars blir nödvändig. Ett uttryckligt val av användaren
    respekteras alltid.
    """
    value = str(mode or DEFAULT_DENSITY).strip().lower()
    if value not in DENSITY_MODES:
        value = DEFAULT_DENSITY
    if value != "auto":
        return value
    try:
        width, height = int(width), int(height)
    except (TypeError, ValueError):
        return "comfortable"
    return "compact" if width < COMPACT_BREAKPOINT or height < COMPACT_HEIGHT_BREAKPOINT else "comfortable"


def resolve_row_mode(value: Any) -> str:
    """Radhöjd: kompakt, normal eller luftig. Trasiga värden blir normal."""
    text = str(value or DEFAULT_ROW_MODE).strip().lower()
    return text if text in TABLE_ROW_MODES else DEFAULT_ROW_MODE


def row_height(density: str = "normal") -> int:
    """Radhöjd i tabeller och listor.

    Tre nivåer: kompakt (24 px), normal (32 px) och luftig (42 px). Den gamla
    benämningen ``comfortable`` motsvarar normal, så att sparade inställningar
    fortsätter att fungera.
    """
    text = str(density or "normal").strip().lower()
    if text in ("comfortable", "auto"):
        return ROW_HEIGHTS["normal"]
    return ROW_HEIGHTS.get(text, ROW_HEIGHTS[DEFAULT_ROW_MODE])


def spacing(density: str = "comfortable") -> int:
    """Luft mellan element, så att kompakt läge verkligen blir kompaktare."""
    return 4 if density == "compact" else GAP


def icon_only_sidebar(width: int) -> bool:
    """Visa bara ikoner i sidomenyn när utrymmet är litet."""
    try:
        return int(width) < SIDEBAR_ICON_ONLY_BREAKPOINT
    except (TypeError, ValueError):
        return False


# ── Skalning av hela gränssnittet (förslag 13) ──────────────────────────────

SCALE_MIN: Final[float] = 0.90
SCALE_MAX: Final[float] = 1.50
SCALE_STEP: Final[float] = 0.05


def clamp_scale(value: Any, default: float = 1.0) -> float:
    """Håll gränssnittets skalning inom rimliga gränser."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(SCALE_MIN, min(SCALE_MAX, round(number, 2)))


def scaled(value: int, scale: float = 1.0) -> int:
    """Skala ett pixelmått, minst 1 px."""
    try:
        return max(1, int(round(int(value) * clamp_scale(scale))))
    except (TypeError, ValueError):
        return max(1, int(value))


def scale_steps() -> list[float]:
    """Alla valbara skalsteg, för reglaget under Visa."""
    steps = []
    value = SCALE_MIN
    while value <= SCALE_MAX + 1e-9:
        steps.append(round(value, 2))
        value += SCALE_STEP
    return steps


# ── Kontrastgranskning (förslag 22) ─────────────────────────────────────────

WCAG_AA_NORMAL: Final[float] = 4.5
WCAG_AA_LARGE: Final[float] = 3.0
# Varje post är (förgrund, bakgrund, beskrivning, krav). Kravet följer WCAG:
# 4,5:1 för text och 3:1 för ramar och andra icke-textliga gränser.
_CONTRAST_PAIRS: Final[tuple[tuple[str, str, str, float], ...]] = (
    ("text", "window", "Brödtext på bakgrund", 4.5),
    ("text", "surface", "Text i fält och kort", 4.5),
    ("text", "surface_alt", "Text på knapp", 4.5),
    ("text_muted", "surface", "Dämpad text", 4.5),
    ("text_muted", "sidebar", "Sidomenyns text", 4.5),
    ("accent_text", "accent", "Text på markerad knapp", 4.5),
    ("accent", "surface", "Länk och fokusram", 4.5),
    ("success", "surface", "Lyckad status", 4.5),
    ("warning", "surface", "Varning", 4.5),
    ("danger", "surface", "Fel", 4.5),
    ("border_strong", "surface", "Ram runt fält och tabell", 3.0),
    ("border_strong", "window", "Ram mot bakgrunden", 3.0),
    ("text_disabled", "surface", "Inaktiverad text", 4.5),
)


def contrast_report(theme: str = "dark") -> list[dict[str, Any]]:
    """Granska alla viktiga text/bakgrund-par i ett tema.

    Returnerar en rad per par med ``ratio``, ``theme``, ``label`` och
    ``passes`` (minst 4,5:1). Används av **Verktyg → Kontrastkontroll** och av
    testerna, så att en ändrad palett inte kan smyga in oläsbar text.
    """
    colors = palette(theme)
    rows = []
    for foreground, background, label, required in _CONTRAST_PAIRS:
        ratio = contrast_ratio(colors[foreground], colors[background])
        rows.append({
            "theme": theme,
            "foreground": foreground,
            "background": background,
            "label": label,
            "ratio": round(ratio, 2),
            "required": required,
            "passes": ratio >= required,
        })
    return rows


def contrast_problems(theme: str | None = None) -> list[dict[str, Any]]:
    """Alla par som inte klarar 4,5:1, i ett eller båda temana."""
    themes = ("dark", "light") if theme is None else (theme,)
    return [row for name in themes for row in contrast_report(name) if not row["passes"]]


# ── Tillgänglighet (förslag 15) ─────────────────────────────────────────────

def accessible_text(*parts: str) -> str:
    """Bygg en beskrivning för skärmläsare av flera textdelar."""
    return ", ".join(part.strip() for part in parts if part and part.strip())


def set_accessible(widget: Any, name: str, description: str = "") -> Any:
    """Sätt namn och beskrivning som skärmläsare läser upp."""
    try:
        widget.setAccessibleName(name)
        if description:
            widget.setAccessibleDescription(description)
    except Exception:
        pass
    return widget


def label_for_icon_button(name: str) -> str:
    """En ikonknapp får aldrig vara utan text för skärmläsaren."""
    clean = str(name or "").strip()
    return clean or "Knapp"


# ── Stilark ─────────────────────────────────────────────────────────────────

def stylesheet(theme: str = "dark", font_family_name: str | None = None,
               font_size: int = DEFAULT_FONT_SIZE, density: str = "comfortable",
               scale: float = 1.0) -> str:
    """Bygg hela programmets stilark för valt tema.

    Stilarket täcker de widgetar som faktiskt används: fönster, knappar med
    varianter, inmatningsfält, tabeller med rubriker, flikar, menyer,
    verktygsfält, rullningslister, grupprutor, kryssrutor, verktygstips och
    statusfält. Fokus markeras alltid med en tydlig ram, så att tangentbordet
    går att använda utan att gissa var markören är.
    """
    colors = palette(theme)
    size = clamp_font_size(font_size)
    compact = density == "compact"
    pad_v = scaled(4 if compact else 6, scale)
    pad_h = scaled(9 if compact else 14, scale)
    control = scaled(CONTROL_HEIGHT - (4 if compact else 0), scale)
    radius = scaled(RADIUS if compact else RADIUS, scale)
    small_radius = scaled(RADIUS_SMALL, scale)
    small = max(MIN_FONT_SIZE, size - 1)
    tiny = max(MIN_FONT_SIZE - 1, size - 2)
    title = size + 8
    family = font_family_name or font_chain()
    mono = mono_chain()
    return f"""
QWidget {{
    font-family: {family};
    font-size: {size}pt;
    color: {colors['text']};
}}
QMainWindow, QDialog {{ background: {colors['window']}; }}
QScrollArea, QStackedWidget, QSplitter {{ background: transparent; border: none; }}
QWidget#Page, QWidget#Content {{ background: {colors['window']}; }}

/* Etiketter */
QLabel {{ background: transparent; }}
QLabel#PageTitle {{ font-size: {title}pt; font-weight: 700; color: {colors['text']}; }}
QLabel#SectionTitle {{ font-size: {size + 2}pt; font-weight: 600; color: {colors['text']}; }}
QLabel#Muted, QLabel#Hint {{ color: {colors['text_muted']}; font-size: {small}pt; }}
QLabel#Caption {{ color: {colors['text_muted']}; font-size: {tiny}pt; }}

/* Knappar */
QPushButton, QToolButton {{
    background: {colors['surface_alt']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
    border-radius: {small_radius}px;
    padding: {pad_v}px {pad_h}px;
    min-height: {control - scaled(12, scale)}px;
}}
QPushButton:hover, QToolButton:hover {{
    background: {colors['surface_hover']};
    border-color: {colors['border_strong']};
}}
QPushButton:pressed, QToolButton:pressed {{ background: {colors['border']}; }}
QPushButton:focus, QToolButton:focus {{
    border: 2px solid {colors['accent']};
    padding: {max(0, pad_v - scaled(1, scale))}px {max(0, pad_h - scaled(1, scale))}px;
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {colors['text_disabled']};
    background: {colors['surface']};
    border-color: {colors['border']};
}}
QPushButton:checked, QToolButton:checked {{
    background: {colors['accent']};
    color: {colors['accent_text']};
    border-color: {colors['accent']};
}}
QPushButton#PrimaryButton {{
    background: {colors['accent']};
    color: {colors['accent_text']};
    border-color: {colors['accent']};
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{ background: {colors['accent_hover']}; }}
QPushButton#SuccessButton {{
    background: {colors['success']};
    color: {colors['accent_text']};
    border-color: {colors['success']};
}}
QPushButton#DangerButton {{
    background: {colors['danger']};
    color: #ffffff;
    border-color: {colors['danger']};
}}
QPushButton#LinkButton {{
    background: transparent;
    border: none;
    color: {colors['accent']};
    text-align: left;
    padding: 2px 4px;
}}

/* Inmatning */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox {{
    background: {colors['surface']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
    border-radius: {small_radius}px;
    padding: {pad_v - scaled(1, scale)}px {scaled(9, scale)}px;
    min-height: {control - scaled(12, scale)}px;
    selection-background-color: {colors['selection']};
    selection-color: {colors['text']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus, QComboBox:focus {{
    border: 1px solid {colors['accent']};
}}
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled {{
    color: {colors['text_disabled']};
    background: {colors['surface_alt']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {colors['surface']};
    color: {colors['text']};
    border: 1px solid {colors['border_strong']};
    border-radius: {RADIUS_SMALL}px;
    selection-background-color: {colors['selection']};
    selection-color: {colors['text']};
    outline: none;
}}

/* Tabeller */
QTableView, QTableWidget, QTreeView, QListWidget {{
    background: {colors['surface']};
    alternate-background-color: {colors['surface_alt']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
    border-radius: {RADIUS_SMALL}px;
    gridline-color: {colors['border']};
    selection-background-color: {colors['selection']};
    selection-color: {colors['text']};
}}
QTableView::item, QTableWidget::item {{
    padding: {scaled(2 if compact else 4, scale)}px {scaled(6, scale)}px;
}}
QHeaderView::section {{
    background: {colors['surface_alt']};
    color: {colors['text_muted']};
    border: none;
    border-bottom: 1px solid {colors['border_strong']};
    border-right: 1px solid {colors['border']};
    padding: 6px 8px;
    font-weight: 600;
}}
QHeaderView::section:hover {{ background: {colors['surface_hover']}; }}
QTableCornerButton::section {{ background: {colors['surface_alt']}; border: none; }}

/* Flikar */
QTabWidget::pane {{
    border: 1px solid {colors['border']};
    border-radius: {radius}px;
    background: {colors['surface']};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {colors['text_muted']};
    border: none;
    border-bottom: 2px solid transparent;
    padding: {scaled(5 if compact else 8, scale)}px {scaled(16, scale)}px;
    margin-right: 2px;
}}
QTabBar::tab:hover {{ color: {colors['text']}; }}
QTabBar::tab:selected {{
    color: {colors['text']};
    border-bottom: 2px solid {colors['accent']};
    font-weight: 600;
}}

/* Grupprutor och kort */
QGroupBox {{
    background: {colors['surface']};
    border: 1px solid {colors['border']};
    border-radius: {RADIUS}px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {colors['text_muted']};
}}
QFrame#Card, QFrame#Panel {{
    background: {colors['surface']};
    border: 1px solid {colors['border']};
    border-radius: {RADIUS}px;
}}
QFrame#Divider {{ background: {colors['border']}; max-height: 1px; border: none; }}

/* Val och reglage */
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {colors['border_strong']};
    background: {colors['surface']};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {colors['accent']};
    border-color: {colors['accent']};
}}
QSplitter::handle {{ background: {colors['border']}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}

/* Menyer och verktygsfält */
QMenuBar {{
    background: {colors['surface']};
    color: {colors['text']};
    border-bottom: 1px solid {colors['border']};
    padding: 2px 4px;
}}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {colors['surface_hover']}; }}
QMenu {{
    background: {colors['surface']};
    color: {colors['text']};
    border: 1px solid {colors['border_strong']};
    border-radius: {RADIUS_SMALL}px;
    padding: 6px;
}}
QMenu::item {{ padding: 7px 24px 7px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {colors['selection']}; }}
QMenu::item:disabled {{ color: {colors['text_disabled']}; }}
QMenu::separator {{ height: 1px; background: {colors['border']}; margin: 5px 8px; }}
QToolBar {{
    background: {colors['surface']};
    border: none;
    border-bottom: 1px solid {colors['border']};
    padding: 4px;
    spacing: 6px;
}}

/* Rullningslister */
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {colors['border_strong']};
    border-radius: 6px;
    min-height: 32px;
    min-width: 32px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {colors['text_muted']};
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Statusfält, verktygstips och förlopp */
QStatusBar {{
    background: {colors['surface']};
    color: {colors['text_muted']};
    border-top: 1px solid {colors['border']};
}}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {colors['surface_alt']};
    color: {colors['text']};
    border: 1px solid {colors['border_strong']};
    border-radius: 4px;
    padding: 6px 8px;
}}
QProgressBar {{
    background: {colors['surface_alt']};
    border: 1px solid {colors['border']};
    border-radius: {RADIUS_SMALL}px;
    text-align: center;
    color: {colors['text']};
    min-height: 16px;
}}
QProgressBar::chunk {{ background: {colors['accent']}; border-radius: 4px; }}
QPlainTextEdit#Mono, QTextEdit#Mono, QLabel#Mono {{
    font-family: {mono};
    font-size: {small}pt;
}}

/* Sidomenyn */
QScrollArea#Sidebar {{ background: {colors['sidebar']}; border: none; }}
QWidget#SidebarBody {{ background: {colors['sidebar']}; }}
QLabel#Brand {{ color: {colors['accent']}; font-size: {size + 4}pt; font-weight: 700; }}
QLabel#SidebarSection {{ color: {colors['text_muted']}; font-size: {tiny}pt;
    font-weight: 600; letter-spacing: 1px; }}
QLabel#SidebarStat {{ color: {colors['text_muted']}; font-size: {tiny}pt; }}
/* Snabbfilterchip ovanför tabeller (förslag 9) */
QToolButton#FilterChip {{
    background: {colors['surface_alt']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
    border-radius: {scaled(12, scale)}px;
    padding: {scaled(3, scale)}px {scaled(10, scale)}px;
    font-size: {size}pt;
}}
QToolButton#FilterChip:hover {{
    background: {colors['surface_hover']};
    border-color: {colors['border_strong']};
}}
QToolButton#FilterChip:checked {{
    background: {colors['accent']};
    color: {colors['accent_text']};
    border-color: {colors['accent']};
    font-weight: 600;
}}
QToolButton#FilterChip:focus {{
    border: 2px solid {colors['accent']};
}}

/* Statusrad under tabeller (förslag 10) */
QLabel#Caption {{
    color: {colors['text_muted']};
    font-size: {max(8, size - 1)}pt;
}}

/* Huvudfönstrets delare (förslag 2) */
QSplitter#MainSplitter::handle {{
    background: {colors['border']};
}}
QSplitter#MainSplitter::handle:hover {{
    background: {colors['accent']};
}}

QPushButton#NavButton {{
    text-align: left;
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    padding: {scaled(5 if compact else 9, scale)}px {scaled(10, scale)}px;
    color: {colors['text_muted']};
    font-size: {size}pt;
}}
QPushButton#NavButton:hover {{
    background: {colors['sidebar_active']};
    color: {colors['text']};
}}
QPushButton#NavButton:checked {{
    background: {colors['sidebar_active']};
    color: {colors['text']};
    border-left: 3px solid {colors['accent']};
    font-weight: 600;
}}
"""


def sidebar_stylesheet(theme: str = "dark") -> str:
    """Bakåtkompatibel delmängd för sidomenyn."""
    colors = palette(theme)
    return (f"QScrollArea#Sidebar {{ background: {colors['sidebar']}; border: none; }}\n"
            f"QWidget#SidebarBody {{ background: {colors['sidebar']}; }}")


def menubar_stylesheet(theme: str = "dark") -> str:
    """Bakåtkompatibel delmängd för menyraden."""
    colors = palette(theme)
    return (f"QMenuBar {{ background: {colors['surface']}; color: {colors['text']}; }}\n"
            f"QMenuBar::item:selected {{ background: {colors['surface_hover']}; }}")


# ── Ikoner ──────────────────────────────────────────────────────────────────

# Två storlekar används i gränssnittet. De är valda så att 24-pixelsrutnätet
# delas jämnt: 24 px ritas rakt av och 16 px blir 2/3, vilket håller strecken
# jämna i stället för att göra dem grumliga.
ICON_SIZE_SMALL: Final[int] = 16
ICON_SIZE_REGULAR: Final[int] = 24
ICON_SIZES: Final[tuple[int, ...]] = (ICON_SIZE_SMALL, ICON_SIZE_REGULAR)


def icon_size(context: str = "menu") -> int:
    """Rätt storlek för sammanhanget: meny/knapp 16 px, sida 24 px."""
    value = str(context or "").strip().lower()
    return ICON_SIZE_SMALL if value in ("menu", "button", "sidebar", "toolbar") else ICON_SIZE_REGULAR


def icon_scale(size: int) -> float:
    """Hur mycket en ikon ska skalas från 24-pixelsrutnätet.

    Streckbredden följer med, annars ser en 16-pixelsikon grövre ut än en
    24-pixelsikon – det är den vanligaste orsaken till att ikoner känns
    "optiskt ojämna".
    """
    try:
        value = int(size)
    except (TypeError, ValueError):
        value = ICON_SIZE_REGULAR
    return max(0.5, min(2.0, value / ICON_SIZE_REGULAR))


ICON_NAMES: Final[tuple[str, ...]] = (
    "vehicle", "schema", "table", "dealers", "colors", "dispatch",
    "generate", "reports", "search", "dashboard", "folder", "error",
    "help", "exit", "refresh", "save", "settings", "theme-dark", "theme-light", "theme-auto",
)


# Sidomenyns ikoner. Nycklarna matchas mot sidans namn (utan emoji) så att
# ikonen följer med även om texten ändras i versaler eller mellanslag.
PAGE_ICONS: Final[tuple[tuple[str, str], ...]] = (
    ("fordonsdata", "vehicle"),
    ("ts schema", "schema"),
    ("data viewer", "table"),
    ("återförsäljare", "dealers"),
    ("färger", "colors"),
    ("dispatch", "dispatch"),
    ("generera", "generate"),
    ("rapport", "reports"),
    ("sök", "search"),
    ("översikt", "dashboard"),
)


def page_icon(page_name: str) -> str:
    """Välj ikon till en sida utifrån dess namn."""
    value = page_name.casefold()
    for keyword, name in PAGE_ICONS:
        if keyword in value:
            return name
    return "folder"


def strip_emoji_prefix(text: str) -> str:
    """Ta bort en inledande symbol (emoji) så att ikonen kan ersätta den."""
    value = str(text or "")
    stripped = value.lstrip(" \t")
    if not stripped:
        return ""
    # Emoji och symboler ligger utanför ASCII. En ledande sekvens som inte är
    # en bokstav eller siffra tas bort, inklusive det mellanslag som följer.
    index = 0
    while index < len(stripped) and not stripped[index].isalnum():
        index += 1
    candidate = stripped[index:].lstrip() if index else stripped
    return candidate or stripped


def icons_directory(root: Path) -> Path:
    return Path(root) / "assets" / "icons"


def icon_path(root: Path, name: str) -> Path | None:
    """Sökväg till en ikon, eller ``None`` om namnet är okänt eller filen saknas."""
    if name not in ICON_NAMES:
        return None
    path = icons_directory(root) / f"{name}.svg"
    return path if path.is_file() else None


def icon_names_available(root: Path) -> list[str]:
    return [name for name in ICON_NAMES if icon_path(root, name) is not None]


def colorize(pixmap: Any, color: str) -> Any:
    """Färga en svartvit pixmap med temats färg (Qt krävs)."""
    from PySide6.QtGui import QPainter
    from PySide6.QtCore import Qt as QtCore

    tinted = pixmap
    painter = QPainter(tinted)
    try:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), QtCore.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.fillRect(tinted.rect(), color)
    finally:
        painter.end()
    return tinted


# Ikoner ritas en gång per (namn, tema, storlek, skalfaktor) och återanvänds.
# Utan cachen ritas samma SVG om varje gång menyn byggs eller temat byts, vilket
# kostar både tid och minne. Cachen töms när den blir för stor.
_ICON_CACHE: Final[dict[tuple[str, str, int, float], Any]] = {}
ICON_CACHE_LIMIT: Final[int] = 96


def clear_icon_cache() -> int:
    """Töm ikoncachen. Returnerar antalet poster som släpptes."""
    count = len(_ICON_CACHE)
    _ICON_CACHE.clear()
    return count


def icon_cache_size() -> int:
    """Antal cachade ikoner, för minnesöversikten och testerna."""
    return len(_ICON_CACHE)


def icon(root: Path, name: str, theme: str = "dark", size: int = 20,
         widget: Any = None) -> Any:
    """Ladda en temafärgad ikon i skärmens verkliga upplösning.

    Vektorbilden ritas med ``size × skalfaktor`` pixlar och får samma
    enhetspixelkvot som skärmen. Utan det ritar Qt om ikonen i efterhand och
    resultatet blir suddigt på 125–200 % skalning. Resultatet cachas per namn,
    tema, storlek och skalfaktor så att samma ikon inte ritas om i onödan.
    Returnerar ``None`` om Qt eller filen saknas.
    """
    path = icon_path(root, name)
    if path is None:
        return None
    ratio = device_pixel_ratio(widget)
    key = (f"{Path(root).resolve()}|{name}", theme, int(size), round(float(ratio), 2))
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from PySide6.QtGui import QIcon, QPixmap
        from PySide6.QtCore import Qt as QtCore
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtGui import QPainter

        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return None
        pixels = max(1, int(round(size * ratio)))
        pixmap = QPixmap(pixels, pixels)
        pixmap.fill(QtCore.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            renderer.render(painter)
        finally:
            painter.end()
        pixmap.setDevicePixelRatio(ratio)
        tinted = colorize(pixmap, palette(theme)["text_muted"])
        icon_value = QIcon(tinted)
        if len(_ICON_CACHE) >= ICON_CACHE_LIMIT:
            # Enkel men förutsägbar tömning: hellre några omritningar än en
            # cache som växer under en hel arbetsdag.
            _ICON_CACHE.clear()
        _ICON_CACHE[key] = icon_value
        return icon_value
    except Exception:
        return None


def enable_high_dpi() -> bool:
    """Slå på skarp rendering på högupplösta skärmar.

    Måste anropas **innan** ``QApplication`` skapas; inställningarna gäller för
    hela processen. ``PassThrough`` låter Windows skala med 125 % och 150 %
    utan att avrunda till hela steg, vilket är det som annars gör text och
    ikoner suddiga. Returnerar ``True`` när inställningen lyckades.
    """
    try:
        from PySide6.QtCore import Qt as QtCore
        from PySide6.QtGui import QGuiApplication

        rounding = getattr(QtCore.HighDpiScaleFactorRoundingPolicy, "PassThrough", None)
        if rounding is not None:
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(rounding)
        return True
    except Exception:
        return False


def device_pixel_ratio(widget: Any = None) -> float:
    """Skärmens skalfaktor, så att ikoner kan ritas i rätt upplösning."""
    try:
        screen = None
        if widget is not None:
            getter = getattr(widget, "screen", None)
            if callable(getter):
                screen = getter()
        if screen is None:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
        ratio = float(screen.devicePixelRatio()) if screen is not None else 1.0
    except Exception:
        ratio = 1.0
    return max(1.0, min(4.0, ratio))


def qr_image(matrix: tuple[str, ...], scale: int = 9, ratio: float = 1.0) -> Any:
    """Rita en QR-kod som skarp bild i skärmens upplösning.

    Modulerna ritas i hela enheter av skalfaktorn, så att varje modul blir
    exakt jämn och koden går att skanna även efter skalning. Ingen
    kantutjämning används – kanterna ska vara knivskarpa.
    """
    from PySide6.QtCore import Qt as QtCore
    from PySide6.QtGui import QImage, QPainter, QPixmap

    ratio = max(1.0, float(ratio))
    module = max(1, int(round(scale * ratio)))
    size = len(matrix) * module
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QtCore.GlobalColor.white)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for y, row in enumerate(matrix):
            for x, value in enumerate(row):
                if value == "1":
                    painter.fillRect(x * module, y * module, module, module, QtCore.GlobalColor.black)
    finally:
        painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def apply_font(app: Any, *, font_size: int = DEFAULT_FONT_SIZE) -> str:
    """Sätt programmets gränssnittstypsnitt och returnera det valda namnet."""
    from PySide6.QtGui import QFont, QFontDatabase

    family = font_family(available=QFontDatabase.families())
    font = QFont(family, clamp_font_size(font_size))
    # PreferAntialias + full hinting: jämna kanter utan att bokstäverna blir
    # suddiga, vilket annars händer när Qt väljer en bitmap-hinting som inte
    # passar skärmens skalfaktor.
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    try:
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    except Exception:
        pass
    app.setFont(font)
    return family


def system_is_dark(app: Any) -> bool:
    """Läs skrivbordets eget tema, så att ``auto`` blir rätt."""
    try:
        from PySide6.QtGui import QPalette
        window = app.palette().color(QPalette.ColorRole.Window)
        return window.lightness() < 128
    except Exception:
        return True


def apply_stylesheet(widget: Any, mode: str, *, font_size: int = DEFAULT_FONT_SIZE,
                     app: Any | None = None) -> str:
    """Sätt stilarket på ett fönster och returnera det tema som användes."""
    theme = resolve_mode(mode, system_is_dark(app) if app is not None else True)
    widget.setStyleSheet(stylesheet(theme, font_size=font_size))
    return theme
