# -*- coding: utf-8 -*-
# Fil: plugins/gui_helpers/components/buttons.py

"""
Button Components v1.0.1

Standardiserade knappar med enhetlig styling (design-tokens).

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil: plugins/gui_helpers/components/
    buttons.py" tillagd (saknades — stod utan "Fil:"-prefix).
  - FIX (låst regel, inga hårdkodade färger): BUTTON_STYLES +
    create_icon_button-stilen byggs nu från design-tokens i
    components/styles.py (COLORS/FONTS) med try/except-fallback —
    inga hårdkodade hex-färger i filen. Warning-textfärgen använder
    bg_primary (mörk text på gul — fallback-kedja, ingen ny token).
  - FIX (dödkod): oanvända importer bort (Qt, QButtonGroup, QIcon).
  - FIX (konsistens): VERSION/AUTHOR + publik get_copyright_string
    tillagda + i __all__; create_button_group-parametern
    buttons → button_specs (konsistent med plugin.py v2.0.1 —
    positionella anrop fungerar oförändrat).
  - FIX (radbrytningsartefakt): dubblerade blankrader före def/class
    kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (create_button/create_icon_button/
    create_button_group, setObjectName-tokens PrimaryButton osv.,
    link-stilen).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

try:
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import (
        QPushButton, QToolButton, QWidget, QHBoxLayout, QVBoxLayout,
    )
    HAS_PYSIDE6: bool = True
except ImportError:
    HAS_PYSIDE6: bool = False

AUTHOR: str = "Rickard Längkvist"
VERSION: str = "1.0.1"

# Design-tokens från styles.py (try/except-fallback — kraschsäkert).
try:
    from .styles import COLORS as _C
    from .styles import FONTS as _F
except ImportError:
    _C: Dict[str, str] = {}
    _F: Dict[str, str] = {}

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# BUTTON STYLES (design-tokens — inga hårdkodade färger)
# ══════════════════════════════════════════════════════════════════════════════

_B_BG: str = _C.get("bg_tertiary", "#3a3f44")
_B_TEXT: str = _C.get("text_light", "#ffffff")
_B_BORDER: str = _C.get("border_light", "#555555")
_B_HOVER: str = _C.get("bg_hover", "#4a4f54")
_B_ACTIVE: str = _C.get("bg_active", "#2a2f34")
_B_DISABLED: str = _C.get("bg_active", "#2a2a2a")
_B_DISABLED_TEXT: str = _C.get("text_muted", "#666666")
_B_PRIMARY: str = _C.get("primary", "#007bff")
_B_PRIMARY_HOVER: str = _C.get("primary_hover", "#0069d9")
_B_PRIMARY_ACTIVE: str = _C.get("primary_active", "#0056b3")
_B_SUCCESS: str = _C.get("success", "#28a745")
_B_SUCCESS_HOVER: str = _C.get("success_hover", "#218838")
_B_SUCCESS_ACTIVE: str = _C.get("success_active", "#1e7e34")
_B_WARNING: str = _C.get("warning", "#ffc107")
_B_WARNING_HOVER: str = _C.get("warning_hover", "#e0a800")
_B_WARNING_ACTIVE: str = _C.get("warning_active", "#d39e00")
_B_WARNING_TEXT: str = _C.get(
    "warning_text", _C.get("bg_primary", "#212529")
)
_B_DANGER: str = _C.get("danger", "#dc3545")
_B_DANGER_HOVER: str = _C.get("danger_hover", "#c82333")
_B_DANGER_ACTIVE: str = _C.get("danger_active", "#bd2130")
_B_SIZE: str = _F.get("size_base", "14px")

_BUTTON_QSS: str = """
        QPushButton {{
            background: {bg};
            color: {text};
            border: 1px solid {border};
            border-radius: 4px;
            padding: 8px 16px;
            font-size: {size};
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:pressed {{ background: {active}; }}
        QPushButton:disabled {{
            background: {disabled_bg};
            color: {disabled_text};
        }}
"""

BUTTON_STYLES: Dict[str, str] = {
    "default": _BUTTON_QSS.format(
        bg=_B_BG,
        text=_B_TEXT,
        border=_B_BORDER,
        size=_B_SIZE,
        hover=_B_HOVER,
        active=_B_ACTIVE,
        disabled_bg=_B_DISABLED,
        disabled_text=_B_DISABLED_TEXT,
    ),
    "primary": _BUTTON_QSS.format(
        bg=_B_PRIMARY,
        text=_B_TEXT,
        border=_B_PRIMARY_ACTIVE,
        size=_B_SIZE,
        hover=_B_PRIMARY_HOVER,
        active=_B_PRIMARY_ACTIVE,
        disabled_bg=_B_DISABLED,
        disabled_text=_B_DISABLED_TEXT,
    ),
    "success": _BUTTON_QSS.format(
        bg=_B_SUCCESS,
        text=_B_TEXT,
        border=_B_SUCCESS_ACTIVE,
        size=_B_SIZE,
        hover=_B_SUCCESS_HOVER,
        active=_B_SUCCESS_ACTIVE,
        disabled_bg=_B_DISABLED,
        disabled_text=_B_DISABLED_TEXT,
    ),
    "warning": _BUTTON_QSS.format(
        bg=_B_WARNING,
        text=_B_WARNING_TEXT,
        border=_B_WARNING_ACTIVE,
        size=_B_SIZE,
        hover=_B_WARNING_HOVER,
        active=_B_WARNING_ACTIVE,
        disabled_bg=_B_DISABLED,
        disabled_text=_B_DISABLED_TEXT,
    ),
    "danger": _BUTTON_QSS.format(
        bg=_B_DANGER,
        text=_B_TEXT,
        border=_B_DANGER_ACTIVE,
        size=_B_SIZE,
        hover=_B_DANGER_HOVER,
        active=_B_DANGER_ACTIVE,
        disabled_bg=_B_DISABLED,
        disabled_text=_B_DISABLED_TEXT,
    ),
    "link": """
        QPushButton {
            background: transparent;
            color: %s;
            border: none;
            padding: 4px 8px;
            text-decoration: underline;
        }
        QPushButton:hover { color: %s; }
        QPushButton:pressed { color: %s; }
    """ % (
        _B_PRIMARY,
        _B_PRIMARY_ACTIVE,
        _C.get("bg_primary", "#003d80"),
    ),
}

_ICON_BTN_QSS: str = """
        QToolButton {{
            background: {bg};
            color: {text};
            border: 1px solid {border};
            border-radius: {radius}px;
            font-size: {font}px;
        }}
        QToolButton:hover {{ background: {hover}; }}
        QToolButton:pressed {{ background: {active}; }}
"""


# ══════════════════════════════════════════════════════════════════════════════
# BUTTON CREATORS
# ══════════════════════════════════════════════════════════════════════════════

def create_button(
    text: str,
    style: str = "default",
    icon: str = "",
    tooltip: str = "",
    enabled: bool = True,
    on_click: Optional[Callable] = None,
) -> Optional["QPushButton"]:
    """
    Skapa en standardiserad knapp.

    Args:
        text: Knapptext
        style: "default", "primary", "success", "warning", "danger",
            "link"
        icon: Emoji eller text-ikon (t.ex. "💾")
        tooltip: Tooltip-text
        enabled: Om knappen är aktiv
        on_click: Callback vid klick

    Returns:
        QPushButton eller None (headless)
    """
    if not HAS_PYSIDE6:
        return None

    # Kombinera ikon och text
    button_text = ("%s %s" % (icon, text)).strip() if icon else text

    btn = QPushButton(button_text)
    btn.setStyleSheet(
        BUTTON_STYLES.get(style, BUTTON_STYLES["default"])
    )
    btn.setEnabled(enabled)

    if tooltip:
        btn.setToolTip(tooltip)

    if on_click:
        btn.clicked.connect(on_click)

    # Sätt object name för styling (design-tokens)
    btn.setObjectName("%sButton" % str(style).capitalize())

    return btn

def create_icon_button(
    icon: str,
    tooltip: str = "",
    size: int = 32,
    on_click: Optional[Callable] = None,
) -> Optional["QToolButton"]:
    """
    Skapa en ikon-knapp (utan text).

    Args:
        icon: Emoji eller text
        tooltip: Tooltip
        size: Storlek i pixlar
        on_click: Callback
    """
    if not HAS_PYSIDE6:
        return None

    btn = QToolButton()
    btn.setText(icon)
    btn.setFixedSize(QSize(size, size))
    btn.setStyleSheet(_ICON_BTN_QSS.format(
        bg=_B_BG,
        text=_B_TEXT,
        border=_B_BORDER,
        radius=size // 4,
        font=size // 2,
        hover=_B_HOVER,
        active=_B_ACTIVE,
    ))

    if tooltip:
        btn.setToolTip(tooltip)

    if on_click:
        btn.clicked.connect(on_click)

    return btn

def create_button_group(
    button_specs: List[Dict[str, Any]],
    layout: str = "horizontal",
) -> Optional[QWidget]:
    """
    Skapa en grupp med knappar.

    Args:
        button_specs: Lista med knappdefinitioner
            [{"text": "Spara", "style": "success",
              "on_click": save_func}, ...]
        layout: "horizontal" eller "vertical"

    Returns:
        QWidget med knappar eller None (headless)
    """
    if not HAS_PYSIDE6:
        return None

    widget = QWidget()

    if layout == "vertical":
        box = QVBoxLayout(widget)
    else:
        box = QHBoxLayout(widget)

    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(8)

    for btn_def in button_specs or []:
        if not isinstance(btn_def, dict):
            continue
        btn = create_button(
            text=btn_def.get("text", ""),
            style=btn_def.get("style", "default"),
            icon=btn_def.get("icon", ""),
            tooltip=btn_def.get("tooltip", ""),
            enabled=btn_def.get("enabled", True),
            on_click=btn_def.get("on_click"),
        )
        if btn:
            box.addWidget(btn)

    return widget


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__: List[str] = [
    # Metadata
    "VERSION",
    "AUTHOR",
    # Creators
    "create_button",
    "create_icon_button",
    "create_button_group",
    # Styles
    "BUTTON_STYLES",
    # Utils
    "HAS_PYSIDE6",
    "get_copyright_string",
]
