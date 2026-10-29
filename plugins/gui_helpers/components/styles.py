# -*- coding: utf-8 -*-
# Fil: plugins/gui_helpers/components/styles.py

"""
Style Constants v1.0.1

Färger, typsnitt och stilkonstanter för hela systemet (dark-tema som
design-tokens). Innehåller även plugin-kontraktet för
gui_helpers/plugin.py v2.0.1: get_stylesheet()/get_button_style()/
get_table_style().

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil: plugins/gui_helpers/components/styles.py"
    tillagd (saknades — stod utan "Fil:"-prefix).
  - FIX (låst regel, inga hårdkodade årtal): COPYRIGHT_YEAR_START
    (2024) BORT — get_copyright_string() returnerar nu enbart
    innevarande år, konsistent med övriga moduler. Docstring-
    placeholdern "{current_year}" ersatt med dynamisk formulering.
  - FIX (integration, korrekthet): get_stylesheet(theme)/
    get_button_style(style)/get_table_style() LAGT TILL —
    gui_helpers/plugin.py v2.0.1 anropar dessa via self.styles;
    utan dem AttributeError/TypeError så fort komponenterna
    används. get_button_style mappar style → COLORS-nyckel
    (_STYLE_TO_COLOR) → create_button_style (okänd style → default).
  - TILLÄGG (design-tokens): _STYLE_TO_COLOR som namngiven konstant
    (inga hårdkodade färgsträngar i logiken).
  - FIX (konsistens): VERSION tillagd + i __all__.
  - FIX (radbrytningsartefakt): dubblerade blankrader före def/class
    kollapsade till max 1 (transport-artefakt).
  - OBS (KRAV 86, kommande): ljust tema ("light"/"system") aktiveras
    med tema-väljaren (implementeras vid main_gui/plugin.py eller
    core/settings_manager.py) — tills dess returnerar
    get_stylesheet() dark-temat för alla värden (kontraktet är
    uppfyllt; växlingen är KRAV 86:s omfattning).
  - Övrig logik OFÖRÄNDRAD (COLORS/FONTS/SPACING, samtliga
    stilblock, get_app_stylesheet, create_button_style,
    create_input_style, get_color, get_font_size).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict

AUTHOR: str = "Rickard Längkvist"
VERSION: str = "1.0.1"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# COLORS
# ══════════════════════════════════════════════════════════════════════════════

# Dark theme colors (design-tokens — enda stället färger definieras).
COLORS: Dict[str, str] = {
    # Backgrounds
    "bg_primary": "#1e1e1e",
    "bg_secondary": "#2b2b2b",
    "bg_tertiary": "#3a3f44",
    "bg_hover": "#4a4f54",
    "bg_active": "#2a2f34",

    # Text
    "text_primary": "#d4d4d4",
    "text_secondary": "#888888",
    "text_muted": "#666666",
    "text_light": "#ffffff",

    # Brand colors
    "primary": "#007bff",
    "primary_hover": "#0069d9",
    "primary_active": "#0056b3",

    "success": "#28a745",
    "success_hover": "#218838",
    "success_active": "#1e7e34",

    "warning": "#ffc107",
    "warning_hover": "#e0a800",
    "warning_active": "#d39e00",

    "danger": "#dc3545",
    "danger_hover": "#c82333",
    "danger_active": "#bd2130",

    "info": "#17a2b8",
    "info_hover": "#138496",
    "info_active": "#117a8b",

    # Borders
    "border_light": "#555555",
    "border_dark": "#444444",
    "border_focus": "#007bff",

    # Status
    "status_ok": "#4caf50",
    "status_warning": "#ff9800",
    "status_error": "#f44336",
}

# Mappning style-namn → COLORS-nyckel (för get_button_style).
_STYLE_TO_COLOR: Dict[str, str] = {
    "default": "bg_tertiary",
    "primary": "primary",
    "success": "success",
    "warning": "warning",
    "danger": "danger",
    "info": "info",
}


# ══════════════════════════════════════════════════════════════════════════════
# FONTS
# ══════════════════════════════════════════════════════════════════════════════

FONTS: Dict[str, str] = {
    "family": "Segoe UI, Arial, sans-serif",
    "family_mono": "Consolas, Monaco, monospace",

    "size_xs": "10px",
    "size_sm": "12px",
    "size_base": "14px",
    "size_lg": "16px",
    "size_xl": "18px",
    "size_2xl": "24px",
    "size_3xl": "32px",

    "weight_normal": "400",
    "weight_medium": "500",
    "weight_bold": "700",
}


# ══════════════════════════════════════════════════════════════════════════════
# SPACING
# ══════════════════════════════════════════════════════════════════════════════

SPACING: Dict[str, str] = {
    "xs": "4px",
    "sm": "8px",
    "md": "12px",
    "lg": "16px",
    "xl": "24px",
    "2xl": "32px",
}


# ══════════════════════════════════════════════════════════════════════════════
# COMPONENT STYLES
# ══════════════════════════════════════════════════════════════════════════════

# Main window style
MAIN_WINDOW_STYLE: str = f"""
    QMainWindow {{
        background: {COLORS['bg_primary']};
    }}
    QWidget {{
        color: {COLORS['text_primary']};
        font-family: {FONTS['family']};
        font-size: {FONTS['size_base']};
    }}
"""

# Sidebar style
SIDEBAR_STYLE: str = f"""
    QFrame#sidebar {{
        background: {COLORS['bg_secondary']};
        border-right: 1px solid {COLORS['border_dark']};
    }}
    QPushButton#sidebarButton {{
        background: transparent;
        color: {COLORS['text_primary']};
        border: none;
        text-align: left;
        padding: 12px 16px;
        font-size: {FONTS['size_base']};
    }}
    QPushButton#sidebarButton:hover {{
        background: {COLORS['bg_hover']};
    }}
    QPushButton#sidebarButton:checked {{
        background: {COLORS['primary']};
    }}
"""

# Table style
TABLE_STYLE: str = f"""
    QTableWidget {{
        background: {COLORS['bg_primary']};
        color: {COLORS['text_primary']};
        gridline-color: {COLORS['border_dark']};
        border: 1px solid {COLORS['border_dark']};
        border-radius: 4px;
    }}
    QTableWidget::item {{
        padding: 8px;
    }}
    QTableWidget::item:selected {{
        background: {COLORS['primary']};
    }}
    QTableWidget::item:hover {{
        background: {COLORS['bg_hover']};
    }}
    QHeaderView::section {{
        background: {COLORS['bg_tertiary']};
        color: {COLORS['text_light']};
        padding: 10px;
        border: none;
        border-right: 1px solid {COLORS['border_dark']};
        border-bottom: 1px solid {COLORS['border_dark']};
    }}
"""

# Tab widget style
TAB_STYLE: str = f"""
    QTabWidget::pane {{
        border: 1px solid {COLORS['border_dark']};
        border-radius: 4px;
        background: {COLORS['bg_secondary']};
    }}
    QTabBar::tab {{
        background: {COLORS['bg_tertiary']};
        color: {COLORS['text_primary']};
        padding: 10px 20px;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }}
    QTabBar::tab:selected {{
        background: {COLORS['primary']};
    }}
    QTabBar::tab:hover:!selected {{
        background: {COLORS['bg_hover']};
    }}
"""

# Scrollbar style
SCROLLBAR_STYLE: str = f"""
    QScrollBar:vertical {{
        background: {COLORS['bg_secondary']};
        width: 12px;
        border-radius: 6px;
    }}
    QScrollBar::handle:vertical {{
        background: {COLORS['border_light']};
        border-radius: 6px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {COLORS['text_secondary']};
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: {COLORS['bg_secondary']};
        height: 12px;
        border-radius: 6px;
    }}
    QScrollBar::handle:horizontal {{
        background: {COLORS['border_light']};
        border-radius: 6px;
        min-width: 30px;
    }}
"""

# Tooltip style
TOOLTIP_STYLE: str = f"""
    QToolTip {{
        background: {COLORS['bg_tertiary']};
        color: {COLORS['text_light']};
        border: 1px solid {COLORS['border_light']};
        border-radius: 4px;
        padding: 6px 10px;
        font-size: {FONTS['size_sm']};
    }}
"""

# Status bar style
STATUSBAR_STYLE: str = f"""
    QStatusBar {{
        background: {COLORS['bg_secondary']};
        color: {COLORS['text_secondary']};
        border-top: 1px solid {COLORS['border_dark']};
    }}
    QStatusBar::item {{
        border: none;
    }}
"""


# ══════════════════════════════════════════════════════════════════════════════
# COMBINED STYLES
# ══════════════════════════════════════════════════════════════════════════════

def get_app_stylesheet() -> str:
    """Hämta komplett app-stylesheet (alla block)."""
    return "\n".join([
        MAIN_WINDOW_STYLE,
        SIDEBAR_STYLE,
        TABLE_STYLE,
        TAB_STYLE,
        SCROLLBAR_STYLE,
        TOOLTIP_STYLE,
        STATUSBAR_STYLE,
    ])


def get_stylesheet(theme: str = "dark") -> str:
    """
    Hämta komplett app-stylesheet (plugin-kontraktet).

    Args:
        theme: "dark" (default). Ljust tema ("light"/"system")
            aktiveras med KRAV 86 (tema-väljaren, implementeras vid
            main_gui/plugin.py eller core/settings_manager.py) —
            tills dess returneras dark-temat för alla värden.

    Returns:
        Komplett QSS-stylesheet (aldrig tom)
    """
    return get_app_stylesheet()


def get_color(name: str, default: str = "#ffffff") -> str:
    """Hämta färg med fallback."""
    return COLORS.get(name, default)


def get_font_size(size: str = "base") -> str:
    """Hämta typsnittsstorlek (fallback: base)."""
    return FONTS.get("size_%s" % size, FONTS["size_base"])


def get_button_style(style: str = "default") -> str:
    """
    Hämta färdig knapp-stylesheet (plugin-kontraktet).

    Mappar style ("default", "primary", "success", "warning",
    "danger", "info") till COLORS-nyckel; okänd style → default.

    Returns:
        QSS för QPushButton (aldrig tom)
    """
    key = _STYLE_TO_COLOR.get(str(style).strip().lower(), "bg_tertiary")
    return create_button_style(bg=key)


def get_table_style() -> str:
    """Hämta tabell-stylesheet (plugin-kontraktet)."""
    return TABLE_STYLE


def create_button_style(
    bg: str = "primary",
    text: str = "text_light",
    padding: str = "8px 16px",
    border_radius: str = "4px",
) -> str:
    """
    Skapa knapp-stil dynamiskt.

    Args:
        bg: Bakgrundsfärg (nyckel från COLORS)
        text: Textfärg (nyckel från COLORS)
        padding: Padding
        border_radius: Hörnradie
    """
    bg_color = COLORS.get(bg, bg)
    hover_color = COLORS.get("%s_hover" % bg, bg_color)
    active_color = COLORS.get("%s_active" % bg, bg_color)
    text_color = COLORS.get(text, text)

    return f"""
        QPushButton {{
            background: {bg_color};
            color: {text_color};
            border: none;
            border-radius: {border_radius};
            padding: {padding};
            font-size: {FONTS['size_base']};
        }}
        QPushButton:hover {{ background: {hover_color}; }}
        QPushButton:pressed {{ background: {active_color}; }}
        QPushButton:disabled {{ background: {COLORS['bg_tertiary']}; color: {COLORS['text_muted']}; }}
    """


def create_input_style(
    bg: str = "bg_primary",
    border: str = "border_light",
    focus_border: str = "border_focus",
) -> str:
    """Skapa input-stil dynamiskt."""
    return f"""
        QLineEdit, QTextEdit, QSpinBox, QComboBox {{
            background: {COLORS.get(bg, bg)};
            color: {COLORS['text_primary']};
            border: 1px solid {COLORS.get(border, border)};
            border-radius: 4px;
            padding: 8px;
        }}
        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
            border-color: {COLORS.get(focus_border, focus_border)};
        }}
    """


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Metadata
    "VERSION",
    "AUTHOR",
    # Colors
    "COLORS",
    "get_color",
    # Fonts
    "FONTS",
    "get_font_size",
    # Spacing
    "SPACING",
    # Component styles
    "MAIN_WINDOW_STYLE",
    "SIDEBAR_STYLE",
    "TABLE_STYLE",
    "TAB_STYLE",
    "SCROLLBAR_STYLE",
    "TOOLTIP_STYLE",
    "STATUSBAR_STYLE",
    # Generators
    "get_app_stylesheet",
    "get_stylesheet",
    "get_button_style",
    "get_table_style",
    "create_button_style",
    "create_input_style",
    # Utils
    "get_copyright_string",
]
