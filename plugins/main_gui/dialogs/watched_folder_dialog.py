"""Inställning för bevakad mapp (förslag 7). Avstängd som standard."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QVBoxLayout,
)

from core.watched_folder import (
    clear_seen, default_settings, load_settings, normalize_folders, save_settings,
)

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]


class WatchedFolderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Bevakad mapp')
        self.resize(560, 420)
        self.changed = False
        self._path = ROOT / 'json' / 'watched_folder.json'
        self._settings = load_settings(self._path)

        layout = QVBoxLayout(self)
        info = QLabel(
            'Fordonsreg kan hålla ett öga på en mapp och visa en diskret notis när en ny '
            'Excel-, CSV- eller PDF-fil dyker upp. Ingenting importeras automatiskt: du '
            'öppnar alltid importen själv och godkänner filen som vanligt.')
        info.setWordWrap(True)
        layout.addWidget(info)

        self._enabled = QCheckBox('Bevaka mappen och visa notis vid nya filer')
        self._enabled.setChecked(bool(self._settings.get('enabled')))
        layout.addWidget(self._enabled)

        layout.addWidget(QLabel('Mappar (högst fem):'))
        self._list = QListWidget()
        for folder in self._settings.get('folders') or []:
            self._list.addItem(folder)
        layout.addWidget(self._list)

        buttons = QHBoxLayout()
        add = QPushButton('Lägg till mapp...')
        add.clicked.connect(self._add)
        buttons.addWidget(add)
        remove = QPushButton('Ta bort vald')
        remove.clicked.connect(self._remove)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        note = QLabel('Notisen visar bara filnamn. Filer som redan rapporterats visas inte igen.')
        note.setWordWrap(True)
        layout.addWidget(note)

        bottom = QHBoxLayout()
        reset = QPushButton('Glöm rapporterade filer')
        reset.clicked.connect(self._reset_seen)
        bottom.addWidget(reset)
        bottom.addStretch(1)
        cancel = QPushButton('Avbryt')
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        save = QPushButton('Spara')
        save.setDefault(True)
        save.clicked.connect(self._save)
        bottom.addWidget(save)
        layout.addLayout(bottom)

    def _add(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, 'Välj mapp att bevaka')
        if not folder:
            return
        folders = [self._list.item(i).text() for i in range(self._list.count())]
        accepted = normalize_folders(folders + [folder])
        self._list.clear()
        self._list.addItems(accepted)

    def _remove(self) -> None:
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))

    def _reset_seen(self) -> None:
        self._settings = clear_seen(self._settings)

    def _save(self) -> None:
        folders = normalize_folders([self._list.item(i).text() for i in range(self._list.count())])
        data = dict(self._settings)
        data.setdefault('version', 1)
        data['enabled'] = bool(self._enabled.isChecked()) and bool(folders)
        data['folders'] = folders
        if self._enabled.isChecked() and not folders:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, 'Bevakad mapp', 'Lägg till minst en mapp först.')
            return
        if not isinstance(data.get('seen'), dict):
            data['seen'] = default_settings()['seen']
        try:
            save_settings(self._path, data)
        except (OSError, ValueError) as exc:
            _log.exception('Bevakningsinställningen kunde inte sparas')
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Bevakad mapp', f'Inställningen kunde inte sparas: {exc}')
            return
        self.changed = True
        self.accept()
