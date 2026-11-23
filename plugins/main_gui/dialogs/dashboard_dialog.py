"""Instrumentpanel (förslag 21): en samlad översikt över läget just nu."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.dashboard import build

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]


def _card(title: str, rows: list[tuple[str, str]], note: str = '') -> QFrame:
    card = QFrame()
    card.setStyleSheet('QFrame { background: white; border: 1px solid #dbe5ef; border-radius: 12px; }')
    box = QVBoxLayout(card)
    box.setContentsMargins(16, 14, 16, 14)
    box.setSpacing(6)
    heading = QLabel(title)
    heading.setStyleSheet('font-size: 15px; font-weight: bold; color: #132747; border: none;')
    box.addWidget(heading)
    for label, value in rows:
        row = QHBoxLayout()
        name = QLabel(label)
        name.setStyleSheet('color: #5d7285; font-size: 12px; border: none;')
        val = QLabel(str(value))
        val.setStyleSheet('color: #132747; font-size: 13px; font-weight: bold; border: none;')
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val.setWordWrap(True)
        row.addWidget(name)
        row.addStretch(1)
        row.addWidget(val, 2)
        box.addLayout(row)
    if note:
        text = QLabel(note)
        text.setWordWrap(True)
        text.setStyleSheet('color: #5d7285; font-size: 11px; border: none;')
        box.addWidget(text)
    return card


class DashboardDialog(QDialog):
    """Visar läget utan att ändra något. Uppdateras manuellt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Översikt – Fordonsreg')
        self.resize(600, 720)
        self.setStyleSheet('QDialog { background: #eef3f9; }')
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 14, 14, 12)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(10)
        self._scroll.setWidget(self._content)
        self._layout.addWidget(self._scroll, 1)
        buttons = QHBoxLayout()
        self._refresh = QPushButton('Uppdatera')
        self._refresh.clicked.connect(self.reload)
        buttons.addWidget(self._refresh)
        buttons.addStretch(1)
        close = QPushButton('Stäng')
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        self._layout.addLayout(buttons)
        self.reload()

    def reload(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        try:
            data = build(ROOT, colors_file=ROOT / 'data' / 'farger.json',
                         logs_dir=self._logs_dir())
        except Exception as exc:
            _log.exception('Instrumentpanelen kunde inte läsas')
            self._content_layout.addWidget(_card('Översikt', [('Fel', str(exc))]))
            return
        sections = data['sections']
        headline = QLabel(data['headline'])
        headline.setWordWrap(True)
        headline.setStyleSheet('font-size: 15px; font-weight: bold; color: #132747;')
        self._content_layout.addWidget(headline)

        vehicles = sections['vehicles']
        rows = [(f"År {row['year']}", f"{row['count']} fordon") for row in vehicles['rows'][:8]]
        self._content_layout.addWidget(_card(
            'Fordonsdata',
            rows or [('Fordon', 'Ingen data hittad')],
            f"Totalt {vehicles['total']} fordon i {vehicles['years']} år."
            + (f" Senast uppdaterad {vehicles['latest_update']}." if vehicles['latest_update'] else '')))

        colors = sections['colors']
        self._content_layout.addWidget(_card(
            'Färger',
            [('Kopplade', colors['mapped']), ('Väntar på koppling', colors['pending'])],
            'Färger utan koppling skapar en tom rad och kan aldrig generera en TS-kod.' if colors['pending']
            else 'Alla färger är kopplade.' if colors['available'] else 'Färgfilen hittades inte.'))

        errors = sections['errors']
        self._content_layout.addWidget(_card(
            'Fel', [('Aktiva felkoder', errors['active'])], errors['summary']))

        ts = sections['ts']
        self._content_layout.addWidget(_card(
            'TS-generering', [('Status', 'Spärrad' if ts['blocked'] else 'Verifierad')], ts['status']))

        health = sections['health']
        self._content_layout.addWidget(_card(
            'Start och uppdatering', [('Senaste start', 'Bekräftad' if not health['pending'] else 'Ej bekräftad')],
            health['text']))

        self._content_layout.addStretch(1)

    @staticmethod
    def _logs_dir() -> Path:
        for candidate in (ROOT / 'logs', ROOT / 'data' / 'logs'):
            if candidate.is_dir():
                return candidate
        return ROOT / 'logs'
