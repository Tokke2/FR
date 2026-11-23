"""Visa medföljande användningslicens utan redigeringsmöjlighet."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout


def show_license(parent=None) -> None:
    path = Path(__file__).resolve().parents[3] / 'LICENSE'
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise OSError('Licensfilen saknas eller är ogiltig')
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        text = ('Licensfilen kunde inte läsas. Kontrollera att LICENSE finns '
                'i programmets installationsmapp.')
    dialog = QDialog(parent)
    dialog.setWindowTitle('Licens och användningsvillkor')
    dialog.resize(680, 560)
    layout = QVBoxLayout(dialog)
    label = QLabel('Fordonsreg · licens och användningsvillkor')
    label.setWordWrap(True)
    layout.addWidget(label)
    viewer = QPlainTextEdit()
    viewer.setReadOnly(True)
    viewer.setPlainText(text)
    layout.addWidget(viewer)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
