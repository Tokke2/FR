"""Modal, trådsäker förloppsvisning för arbeten utan säker avbrytning."""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

_log = logging.getLogger(__name__)


class _Worker(QThread):
    progress = Signal(int, int, str)

    def __init__(self, task: Callable, parent: QDialog):
        super().__init__(parent)
        self.task = task
        self.result: Any = None
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            self.result = self.task(self.progress.emit)
        except Exception as exc:
            _log.exception("Bakgrundsarbetet misslyckades")
            self.error = exc


class _TaskDialog(QDialog):
    def __init__(self, parent, title: str, task: Callable):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self._running = True
        layout = QVBoxLayout(self)
        self.message = QLabel("Förbereder...")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        layout.addWidget(self.bar)
        self.note = QLabel("Arbetet kan inte avbrytas säkert medan det pågår.")
        layout.addWidget(self.note)
        self.worker = _Worker(task, self)
        self.worker.progress.connect(self._update)
        self.worker.finished.connect(self._finished)

    def _update(self, current: int, total: int, message: str) -> None:
        self.message.setText(message)
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(max(0, min(current, total)))
        else:
            self.bar.setRange(0, 0)

    def _finished(self) -> None:
        self._running = False
        self.accept()

    def reject(self) -> None:
        if not self._running:
            super().reject()

    def closeEvent(self, event) -> None:
        if self._running:
            event.ignore()
        else:
            super().closeEvent(event)


def run_task(parent, title: str, task: Callable) -> Any:
    """Kör task(progress) i en tråd. progress(current, total, text); total=0 är okänd.

    Dialogen kan inte stängas medan arbetet skriver. Resultat och undantag
    hanteras efteråt på GUI-tråden. task får inte röra Qt-widgets.
    """
    dialog = _TaskDialog(parent, title, task)
    dialog.worker.start()
    try:
        dialog.exec()
    finally:
        # Även om applikationen avslutas under dialogen får tråden inte
        # förstöras mitt i en filskrivning.
        dialog.worker.wait()
    if dialog.worker.error is not None:
        raise dialog.worker.error
    return dialog.worker.result
