"""Felkodsguide (förslag 24): förklaring och åtgärdssteg per kod."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QPlainTextEdit, QPushButton, QHBoxLayout, QLabel, QVBoxLayout,
)

from core.error_codes import guide_lines, read_entries, summary

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]


def _logs_dir() -> Path:
    for candidate in (ROOT / "logs", ROOT / "data" / "logs"):
        if candidate.is_dir():
            return candidate
    return ROOT / "logs"


class ErrorGuideDialog(QDialog):
    def __init__(self, parent=None, code: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Felkodsguide")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        row = QHBoxLayout()
        row.addWidget(QLabel("Felkod:"))
        self._codes = QComboBox()
        self._codes.currentIndexChanged.connect(self._show_selected)
        row.addWidget(self._codes, 1)
        refresh = QPushButton("Uppdatera")
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)
        layout.addLayout(row)
        self._viewer = QPlainTextEdit()
        self._viewer.setReadOnly(True)
        layout.addWidget(self._viewer, 1)
        close = QPushButton("Stäng")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._preselect = code
        self.reload()

    def reload(self) -> None:
        entries = read_entries(_logs_dir() / "felkoder.json")
        self._codes.blockSignals(True)
        self._codes.clear()
        seen = []
        for entry in entries:
            if entry["code"] in seen:
                continue
            seen.append(entry["code"])
            self._codes.addItem(f"{entry['code']}  ({entry['status']})", entry["code"])
        for code in ("CONFIG_PARSE_ERROR", "DEPENDENCY_ERROR", "PLUGIN_LOAD_ERROR"):
            if code not in seen:
                self._codes.addItem(f"{code}  (ingen registrerad förekomst)", code)
        self._codes.blockSignals(False)
        self._summary.setText(summary(entries) + "  Guiden ändrar aldrig en kods status.")
        wanted = self._preselect or self._codes.currentData()
        for index in range(self._codes.count()):
            if self._codes.itemData(index) == wanted:
                self._codes.setCurrentIndex(index)
                break
        self._show_selected()

    def _show_selected(self, *_args) -> None:
        code = self._codes.currentData()
        if not code:
            self._viewer.clear()
            return
        self._viewer.setPlainText("\n".join(guide_lines(code)))
