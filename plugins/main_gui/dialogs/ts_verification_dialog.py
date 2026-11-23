"""Granska ett riktigt TS-underlag innan spärren kan öppnas (förslag 11).

Verktyget skriver aldrig en TS-fil. Det läser ett underlag som du väljer,
sammanfattar strukturen och kräver en uttrycklig bekräftelse med anteckning
innan godkännandet sparas.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from core.ts_verification import VerificationError, approve, report, status

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]


def _format_report(data: dict) -> str:
    structure = data['structure']
    lines = [
        f"Underlag: {data['file']}",
        f"Kontrollerad: {data['checked_at']}",
        f"SHA-256: {structure['sha256']}",
        "",
        f"Teckenkodning: {structure['encoding']}" + (" (med BOM)" if structure['bom'] else ""),
        f"Radslut: {structure['line_endings']}",
        f"Rader: {structure['lines']} (varav {structure['records']} poster)",
        f"Postlängder: {', '.join(str(v) for v in structure['record_lengths'][:8])} tecken",
        f"Förväntad postlängd: {structure['expected_record_length']} tecken",
        f"Semicolon: {structure['semicolons_min']}–{structure['semicolons_max']} per post",
        f"Tabulatorer: {'ja' if structure['tabs_present'] else 'nej'}",
        f"Decimalkomma: {structure['decimal_comma_count']}, decimalpunkt: {structure['decimal_point_count']}",
        "",
    ]
    if data['problems']:
        lines.append('Hinder innan spärren kan öppnas:')
        lines.extend(f"• {problem}" for problem in data['problems'])
    else:
        lines.append('Inga hinder hittades i den här kontrollen.')
        lines.append('Kontrollen visar att filen har förväntad struktur. Den bevisar inte att '
                     'fältens betydelse, kodtabeller eller PT28/PT99 är verifierade.')
    return '\n'.join(lines)


class TsVerificationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Verifiera TS-underlag')
        self.resize(820, 640)
        self._report: dict | None = None
        layout = QVBoxLayout(self)

        self.status_label = QLabel(status(ROOT))
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        info = QLabel('Välj en riktig TS-fil som du har fått eller skapat tidigare. '
                      'Filen läses bara – ingenting skrivs, flyttas eller genereras.')
        info.setWordWrap(True)
        layout.addWidget(info)

        pick = QHBoxLayout()
        self._path = QLineEdit()
        self._path.setReadOnly(True)
        self._path.setPlaceholderText('Ingen fil vald')
        pick.addWidget(self._path, 1)
        browse = QPushButton('Välj TS-fil...')
        browse.clicked.connect(self._browse)
        pick.addWidget(browse)
        layout.addLayout(pick)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setPlaceholderText('Välj en fil för att granska strukturen.')
        layout.addWidget(self._view, 1)

        self._note = QLineEdit()
        self._note.setPlaceholderText('Anteckning: vad har du jämfört och mot vilket underlag? (krävs)')
        layout.addWidget(self._note)

        self._confirm = QCheckBox('Jag har granskat rapporten och godkänner att PT45-formatet låses upp.')
        self._confirm.setEnabled(False)
        self._confirm.stateChanged.connect(self._update_approve_state)
        layout.addWidget(self._confirm)

        buttons = QHBoxLayout()
        self._approve = QPushButton('Godkänn och lås upp')
        self._approve.setEnabled(False)
        self._approve.clicked.connect(self._approve)
        buttons.addWidget(self._approve)
        buttons.addStretch(1)
        close = QPushButton('Stäng')
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _browse(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, 'Välj TS-underlag', '', 'TS-filer (*.txt *.dat *.ts);;Alla filer (*)')
        if not filename:
            return
        self._path.setText(filename)
        self._confirm.setChecked(False)
        try:
            self._report = report(Path(filename))
        except VerificationError as exc:
            self._report = None
            self._view.setPlainText(f'Underlaget kunde inte granskas:\n{exc}')
            self._confirm.setEnabled(False)
            self._update_approve_state()
            return
        self._view.setPlainText(_format_report(self._report))
        self._confirm.setEnabled(bool(self._report.get('can_lock_open')))
        if not self._report.get('can_lock_open'):
            self._confirm.setText('Rätta hindren ovan innan ett godkännande är möjligt.')
        else:
            self._confirm.setText('Jag har granskat rapporten och godkänner att PT45-formatet låses upp.')
        self._update_approve_state()

    def _update_approve_state(self, *_args) -> None:
        self._approve.setEnabled(bool(self._report and self._report.get('can_lock_open')
                                      and self._confirm.isChecked()
                                      and len(self._note.text().strip()) >= 10))

    def _approve(self) -> None:
        if self._report is None:
            return
        try:
            record = approve(ROOT, self._report, confirmed=self._confirm.isChecked(),
                             note=self._note.text())
        except VerificationError as exc:
            self._view.appendPlainText(f'\nGodkännandet kunde inte sparas: {exc}')
            return
        _log.info('TS-underlag godkänt: %s', record.get('source_file'))
        self.status_label.setText(status(ROOT))
        self._approve.setEnabled(False)
        self._view.appendPlainText(
            '\nGodkännandet är sparat. Spärren kontrollerar fortfarande underlagets '
            'SHA-256 och PT28/PT99 saknas. Inga TS-filer har skapats.')
