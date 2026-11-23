"""Global sökning (Ctrl+K) i fordonsdata och menyval (förslag 17)."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
)

from core.global_search import MAX_RESULTS, ensure_index, search

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
DEBOUNCE_MS = 180


class GlobalSearchDialog(QDialog):
    def __init__(self, parent, *, on_open_vehicle=None):
        super().__init__(parent)
        self.setWindowTitle('Sök i Fordonsreg  (Ctrl+K)')
        self.resize(720, 520)
        self._on_open_vehicle = on_open_vehicle
        self._index: dict | None = None
        self._index_error = ''
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._run_search)

        layout = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setPlaceholderText('Sök VIN-kod, godkännandenummer, modellkod, färg, återförsäljare eller menyval...')
        self.query.textChanged.connect(lambda _text: self._timer.start())
        self.query.returnPressed.connect(self._run_search)
        layout.addWidget(self.query)
        self.info = QLabel('Söker i lokala data – ingenting skickas över nätet.')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.results = QListWidget()
        self.results.itemActivated.connect(self._open_item)
        self.results.itemClicked.connect(self._open_item)
        layout.addWidget(self.results, 1)
        self.hint = QLabel('Enter öppnar vald träff. Esc stänger.')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self._load_index()
        self.query.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _load_index(self) -> None:
        try:
            self._index = ensure_index(ROOT / 'data' / 'search_index.json', ROOT / 'data' / 'vehicles')
            count = len(self._index.get('entries') or [])
            self.hint.setText(f'{count} poster indexerade. Enter öppnar vald träff. Esc stänger.')
        except Exception as exc:
            _log.exception('Sökindexet kunde inte byggas')
            self._index_error = str(exc)
            self.info.setText(f'Sökindexet kunde inte läsas: {exc}')
            self.hint.setText('Sökningen fungerar inte förrän indexet kan byggas.')

    def _actions(self) -> list[QAction]:
        window = self.parent()
        if window is None:
            return []
        return [action for action in window.findChildren(QAction)
                if action.text() and action.isEnabled() and not action.isSeparator()
                and action.menu() is None]

    def _run_search(self) -> None:
        self.results.clear()
        query = self.query.text().strip()
        if not query:
            self.info.setText('Skriv minst ett tecken för att söka.')
            return
        if self._index is None:
            return
        try:
            hits = search(self._index, query, MAX_RESULTS)
        except Exception as exc:
            _log.exception('Sökningen misslyckades')
            self.info.setText(f'Sökningen misslyckades: {exc}')
            return
        lowered = query.casefold()
        shown = 0
        for hit in hits:
            label = f"{hit['year']} · {hit['title']}"
            if hit['subtitle']:
                label += f"  –  {hit['subtitle']}"
            if hit['field']:
                label += f"   [{hit['field']}: {hit['value']}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ('vehicle', hit))
            self.results.addItem(item)
            shown += 1
        for action in self._actions():
            text = action.text().replace('&', '').strip()
            if lowered in text.casefold():
                item = QListWidgetItem(f'Meny · {text}')
                item.setData(Qt.ItemDataRole.UserRole, ('action', action))
                self.results.addItem(item)
                shown += 1
        if shown:
            self.results.setCurrentRow(0)
            self.info.setText(f'{shown} träffar. Välj en rad och tryck Enter.')
        else:
            self.info.setText('Inga träffar. Prova ett kortare sökord.')

    def _open_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple) or len(data) != 2:
            return
        kind, payload = data
        if kind == 'action' and isinstance(payload, QAction):
            self.accept()
            payload.trigger()
            return
        if kind == 'vehicle' and callable(self._on_open_vehicle):
            self.accept()
            self._on_open_vehicle(payload['year'], payload['row'])
