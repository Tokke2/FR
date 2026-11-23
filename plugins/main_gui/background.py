"""Kör tunga läsningar i bakgrunden med förlopp och avbryt (förslag 9).

Endast arbete som inte ritar gränssnitt får köras här. Vid avbrott returneras
``cancelled`` och anroparen ska då inte skriva något – arbetet här är läsning.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from core.background_task import CancellationToken, run

_log = logging.getLogger(__name__)


class _Worker(QThread):
    progress = Signal(int, int, str)

    def __init__(self, work: Callable, token: CancellationToken, parent=None):
        super().__init__(parent)
        self.work = work
        self.token = token
        self.outcome: dict[str, Any] = {}

    def run(self) -> None:
        self.outcome = run(self.work, token=self.token, progress=self.progress.emit)


class CancellableDialog(QDialog):
    def __init__(self, parent, title: str, work: Callable):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(430)
        self.setModal(True)
        self._done = False
        self.token = CancellationToken()
        layout = QVBoxLayout(self)
        self.message = QLabel('Förbereder...')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        layout.addWidget(self.bar)
        note = QLabel('Arbetet läser filen. Avbryter du, ändras ingenting.')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_button = QPushButton('Avbryt')
        self.cancel_button.clicked.connect(self._cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.worker = _Worker(work, self.token, self)
        self.worker.progress.connect(self._update)
        self.worker.finished.connect(self._finished)

    def _cancel(self) -> None:
        self.token.cancel()
        self.cancel_button.setEnabled(False)
        self.message.setText('Avbryter...')

    def _update(self, current: int, total: int, message: str) -> None:
        if message:
            self.message.setText(message)
        if total > 0:
            self.bar.setRange(0, max(1, total))
            self.bar.setValue(max(0, min(current, total)))
        else:
            self.bar.setRange(0, 0)

    def _finished(self) -> None:
        self._done = True
        self.accept()

    def reject(self) -> None:
        if self._done:
            super().reject()
        else:
            self._cancel()

    def closeEvent(self, event) -> None:
        if self._done:
            super().closeEvent(event)
        else:
            event.ignore()
            self._cancel()


def run_cancellable(parent, title: str, work: Callable) -> dict:
    """Kör work(progress) i en tråd och returnera resultatet från core.background_task."""
    dialog = CancellableDialog(parent, title, work)
    dialog.worker.start()
    try:
        dialog.exec()
        dialog.worker.wait(30_000)
    finally:
        if dialog.worker.isRunning():
            dialog.token.cancel()
            dialog.worker.wait(10_000)
    outcome = dialog.worker.outcome or {"ok": False, "cancelled": True, "value": None, "error": None}
    if outcome.get("cancelled"):
        _log.info('Bakgrundsarbetet avbröts av användaren: %s', title)
    return outcome
