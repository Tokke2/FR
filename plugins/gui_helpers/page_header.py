"""Gemensamt sidhuvud för alla sidor (förslag 5).

Varje sida hade tidigare sin egen rubrik med egen storlek, egen luft och ibland
egen färg. Här finns en enda rubrik som alla sidor använder, så att höjden,
typsnittet och avståndet blir identiskt och innehållet inte hoppar när man
bytar sida.

Modulen importerar Qt först när widgeten skapas, så den går att importera i
test utan PySide6.
"""
from __future__ import annotations

from typing import Any, Final

# Höjden på rubrikraden. Sidomenyns knappar och tabellraderna utgår från samma
# mått, så att sidan inte "hoppar" när man byter flik.
TITLE_HEIGHT: Final[int] = 34


class PageHeader:
    """Bygg en rubrikrad: ikon, rubrik, förklaring och valfria knappar.

    Klassen är medvetet ingen QWidget – den skapar en widget och lägger sina
    delar i den, så att Qt bara behövs när den faktiskt används::

        header = PageHeader.build("Fordonsdata", "vehicle",
                                  subtitle="Ett fordon per rad och år")
        layout.addWidget(header)
    """

    @staticmethod
    def build(title: str, icon_name: str = "", subtitle: str = "",
              parent: Any = None) -> Any:
        """Skapa rubrikraden och returnera widgeten."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

        from core import theme as design

        widget = QWidget(parent)
        widget.setObjectName("PageHeader")
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(design.GAP)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(0)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(design.GAP)
        if icon_name:
            icon_label = QLabel(widget)
            icon_label.setObjectName("PageHeaderIcon")
            pixmap = design.page_icon(icon_name, widget=widget)
            if pixmap is not None and not pixmap.isNull():
                icon_label.setPixmap(pixmap)
                title_row.addWidget(icon_label)
        heading = QLabel(design.strip_emoji_prefix(title), widget)
        heading.setObjectName("PageTitle")
        heading.setMinimumHeight(TITLE_HEIGHT - 8)
        heading.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(heading)
        title_row.addStretch()
        text_column.addLayout(title_row)

        if subtitle:
            description = QLabel(subtitle, widget)
            description.setObjectName("Muted")
            description.setWordWrap(True)
            text_column.addWidget(description)

        row.addLayout(text_column, 1)
        widget.setFixedHeight(TITLE_HEIGHT if not subtitle else TITLE_HEIGHT + 16)
        return widget


def attach(layout: Any, title: str, icon_name: str = "", subtitle: str = "",
           parent: Any = None) -> Any:
    """Bygg rubriken och lägg den först i en befintlig layout."""
    header = PageHeader.build(title, icon_name, subtitle, parent)
    try:
        layout.addWidget(header)
    except Exception:
        pass
    return header
