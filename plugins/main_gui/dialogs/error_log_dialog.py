"""Läsvy för den gemensamma felsökningsloggen."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from core.error_log_view import MAX_DISPLAY_BYTES, current_summary_path, read_log_tail
from core.error_summary import BACKUPS


class ErrorLogDialog(QDialog):
    def __init__(self, parent=None, log_path: Path | None = None):
        super().__init__(parent)
        self._log_path = Path(log_path) if log_path is not None else current_summary_path()
        self.setWindowTitle("Felsökningslogg")
        self.resize(1000, 650)
        layout = QVBoxLayout(self)

        info = QLabel("Varningar och fel från appens loggning. Loggen kan innehålla känsliga uppgifter.")
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(info)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Logg:"))
        self._files = QComboBox()
        self._files.addItem("Aktuell logg", 0)
        for index in range(1, BACKUPS + 1):
            self._files.addItem(f"Tidigare logg {index} (.log.{index})", index)
        self._files.addItem("Programfelkoder (aktiva och verifierat åtgärdade)", -1)
        self._files.currentIndexChanged.connect(self._reload)
        controls.addWidget(self._files)
        refresh = QPushButton("Uppdatera")
        refresh.clicked.connect(self._reload)
        controls.addWidget(refresh)
        self._copy = QPushButton("Kopiera visad text")
        self._copy.clicked.connect(self._copy_text)
        controls.addWidget(self._copy)
        guide = QPushButton("Felkodsguide...")
        guide.clicked.connect(self._open_guide)
        controls.addWidget(guide)
        controls.addStretch()
        layout.addLayout(controls)

        self._path_label = QLabel()
        self._path_label.setTextFormat(Qt.TextFormat.PlainText)
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._path_label.setWordWrap(True)
        layout.addWidget(self._path_label)
        self._viewer = QPlainTextEdit()
        self._viewer.setReadOnly(True)
        self._viewer.setPlaceholderText("Loggen är tom. Inga varningar eller fel har registrerats här.")
        layout.addWidget(self._viewer)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._status)
        close = QPushButton("Stäng")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self._reload()

    def _open_guide(self) -> None:
        from plugins.main_gui.dialogs.error_guide_dialog import ErrorGuideDialog
        ErrorGuideDialog(self).exec()

    def _selected_path(self) -> Path:
        index = self._files.currentData()
        if index == -1:
            return self._log_path.parent / "felkoder.json"
        if index in range(1, BACKUPS + 1):
            return self._log_path.with_name(f"{self._log_path.name}.{index}")
        return self._log_path

    def _reload(self, *_args) -> None:
        path = self._selected_path()
        self._path_label.setText(str(path))
        try:
            text, truncated = read_log_tail(path)
        except FileNotFoundError:
            self._viewer.clear()
            self._copy.setEnabled(False)
            if path.name == "felkoder.json":
                self._status.setText("Felkodsregistret skapas när en uttrycklig programfelkod registreras.")
            else:
                self._status.setText("Den här loggfilen finns inte ännu. Tidigare loggar skapas vid rotation.")
            return
        except (OSError, ValueError) as exc:
            self._viewer.clear()
            self._copy.setEnabled(False)
            self._status.setText(f"Kunde inte läsa loggen: {exc}")
            return
        self._viewer.setPlainText(text)
        self._copy.setEnabled(bool(text))
        if truncated:
            self._status.setText(f"Visar de senaste {MAX_DISPLAY_BYTES // (1024 * 1024)} MB. Äldre poster finns i loggfilen.")
        elif not text:
            self._status.setText("Loggen är tom.")
        else:
            self._status.setText("Visar hela den valda loggfilen. Uppdatera för att läsa nya poster.")

    def reload(self) -> None:
        """Uppdatera visningen när fönstret öppnas igen."""
        self._reload()

    def _copy_text(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._viewer.toPlainText())
