"""Dialog för skärmbild till support (förslag 25).

Bilden tas av programmets eget fönster, PIN-fält maskas, och användaren ser en
förhandsgranskning innan något sparas. Filen hamnar i ``logs/support/``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from core import screenshot
from core import theme as design

_log = logging.getLogger(__name__)

PREVIEW_MAX_WIDTH = 720
PREVIEW_MAX_HEIGHT = 460


class ScreenshotDialog(QDialog):
    """Visa skärmbilden, låt användaren spara eller kopiera den."""

    def __init__(self, window: Any, root: Optional[Path] = None,
                 parent: Any = None) -> None:
        super().__init__(parent or window)
        self._window = window
        self._root = Path(root) if root else Path.cwd()
        self._pixmap = screenshot.capture(window)
        self._saved_to: Optional[Path] = None
        self.setWindowTitle("Skärmbild för support")
        self.setObjectName("ScreenshotDialog")
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(design.GAP)

        title = QLabel("Skärmbild av programmets fönster")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        info = QLabel(
            "Bilden visar bara det här fönstret – inget annat på skärmen. "
            "PIN- och lösenordsfält är maskerade.\n"
            "Kontrollera bilden innan du skickar den till support."
        )
        info.setObjectName("Muted")
        info.setWordWrap(True)
        layout.addWidget(info)

        preview = QLabel()
        preview.setObjectName("ScreenshotPreview")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                PREVIEW_MAX_WIDTH, PREVIEW_MAX_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            preview.setPixmap(scaled)
            layout.addWidget(preview, 1)
        else:
            preview.setText("Kunde inte ta någon bild av fönstret.")
            preview.setStyleSheet(f"color: {design.palette('dark')['warning']};")
            layout.addWidget(preview, 1)

        folder = QLabel(f"Sparas i: {screenshot.SUPPORT_DIR}")
        folder.setObjectName("Caption")
        layout.addWidget(folder)

        buttons = QDialogButtonBox(self)
        self._save_button = buttons.addButton("Spara bild…", QDialogButtonBox.ButtonRole.AcceptRole)
        self._copy_button = buttons.addButton("Kopiera till urklipp", QDialogButtonBox.ButtonRole.ActionRole)
        close_button = buttons.addButton("Stäng", QDialogButtonBox.ButtonRole.RejectRole)
        self._save_button.clicked.connect(self._save)
        self._copy_button.clicked.connect(self._copy)
        close_button.clicked.connect(self.reject)
        enabled = self._pixmap is not None and not self._pixmap.isNull()
        self._save_button.setEnabled(enabled)
        self._copy_button.setEnabled(enabled)
        layout.addWidget(buttons)

        design.set_accessible(self._save_button, "Spara bild",
                              "Sparar skärmbilden som PNG i supportmappen")
        design.set_accessible(self._copy_button, "Kopiera till urklipp",
                              "Lägger skärmbilden i urklipp för att klistras in i ett meddelande")

    # ── Åtgärder ────────────────────────────────────────────────────────
    def _save(self) -> None:
        suggested = screenshot.support_path(self._root)
        target, _filter = QFileDialog.getSaveFileName(
            self, "Spara skärmbild", str(suggested), "PNG-bild (*.png)")
        if not target:
            return
        path = Path(target)
        if screenshot.save(self._pixmap, path):
            self._saved_to = path
            _log.info("Skärmbild sparad: %s", path)
            self.accept()
        else:
            QMessageBox.warning(self, "Kunde inte spara",
                                f"Bilden kunde inte sparas till:\n{path}")

    def _copy(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None and self._pixmap is not None:
            clipboard.setPixmap(self._pixmap)
            _log.info("Skärmbild kopierad till urklipp")

    @property
    def saved_to(self) -> Optional[Path]:
        return self._saved_to
