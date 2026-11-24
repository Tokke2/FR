"""Minnesöversikt: visa mätvärden och frigör minne (prestandaomgången).

Dialogen visar bara uppmätta siffror: processens arbetsminne, antal Python-objekt
och vad den senaste frigöringen faktiskt gav. Inga procentsatser eller
"optimerade X MB" som inte går att mäta.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core import memory_guard
from core import runtime_policy
from core import theme as design

_log = logging.getLogger(__name__)


class MemoryDialog(QDialog):
    """Visa minnesläget och låt användaren frigöra minne."""

    def __init__(self, parent: Any = None, root: Optional[Path] = None,
                 views: Optional[list[Any]] = None) -> None:
        super().__init__(parent)
        self._root = Path(root) if root else None
        self._views = list(views or [])
        self.setWindowTitle("Minne och prestanda")
        self.setObjectName("MemoryDialog")
        self.setMinimumWidth(460)
        self._build()
        self._refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(design.GAP)

        title = QLabel("Minne och prestanda")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self._usage = QLabel()
        self._usage.setObjectName("SectionTitle")
        layout.addWidget(self._usage)

        self._advice = QLabel()
        self._advice.setObjectName("Muted")
        self._advice.setWordWrap(True)
        layout.addWidget(self._advice)

        self._details = QLabel()
        self._details.setObjectName("Caption")
        self._details.setWordWrap(True)
        layout.addWidget(self._details)

        self._result = QLabel()
        self._result.setObjectName("Muted")
        self._result.setWordWrap(True)
        layout.addWidget(self._result)

        buttons = QDialogButtonBox(self)
        self._release = buttons.addButton("Frigör minne", QDialogButtonBox.ButtonRole.ActionRole)
        close = buttons.addButton("Stäng", QDialogButtonBox.ButtonRole.RejectRole)
        self._release.clicked.connect(self._do_release)
        close.clicked.connect(self.accept)
        layout.addWidget(buttons)

        design.set_accessible(self._release, "Frigör minne",
                              "Släpper cachade ikoner, tömmer tabellvyer och kör skräpsamlaren")

    def _refresh(self) -> None:
        status = memory_guard.diagnose(self._root)
        self._status = status
        self._usage.setText(runtime_policy.memory_summary(status, status.get("objects", 0)))
        self._advice.setText(status.get("advice", ""))
        colours = design.palette(design.resolve_mode("auto", True))
        level = status.get("level", "ok")
        colour = colours.get({"ok": "success", "warning": "warning",
                              "critical": "danger"}.get(level, "text"))
        self._usage.setStyleSheet(f"color: {colour};")
        self._details.setText(
            f"Gräns för varning: {status.get('limit_mb')} MB · "
            f"Python {status.get('python')} · {status.get('platform')}")
        self._result.setText("")

    def _do_release(self) -> None:
        cleaned = memory_guard.trim_view_caches(self._views)
        result = memory_guard.release({"closed_tabs": 0})
        text = result["summary"]
        if cleaned:
            text += f" {cleaned} tabellvy(er) rensades."
        _log.info("Minne frigjort: %s", text)
        # Mätningen sker efter frigöringen, så siffrorna är de som gäller nu.
        self._refresh()
        self._result.setText(text)

    @property
    def status(self) -> dict[str, Any]:
        return getattr(self, "_status", {})
