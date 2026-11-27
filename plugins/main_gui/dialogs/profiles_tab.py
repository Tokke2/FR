"""Inställningsflik för namngivna profiler.

Appen använder profiler för kolumnmappningen vid import. Profilerna ligger i
``core.vehicle_mapping_profiles`` och är användardata – de följer aldrig med en
programuppdatering. Den här fliken är den enda platsen där de skapas, byts namn
på och tas bort, så att det finns **en** tydlig plats i Inställningar i stället
för spridda "spara profil"-knappar.

Fliken finns i alla program som har profilagret inkopplat. Saknas det visas en
förklaring i stället för en tom yta.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.vehicle_mapping_profiles import ProfileError, ProfileStore, profile_rows


class ProfilesTab(QWidget):
    """Skapa, byt namn på och ta bort mappningsprofiler."""

    COLUMNS = ("Profil", "Kolumner")

    def __init__(self, parent=None, store: ProfileStore | None = None):
        super().__init__(parent)
        self._store = store or ProfileStore(
            Path(__file__).resolve().parents[2] / "json" / "mappings" / "vehicle_mapping_profiles.json")
        layout = QVBoxLayout(self)
        heading = QLabel("Profiler för import")
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)
        info = QLabel(
            "En profil sparar vilka Excel-kolumner som hör till vilka fält. "
            "Profilen återanvänds nästa gång samma filtyp importeras. "
            "Profilerna sparas lokalt och följer inte med programuppdateringar.")
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(info)

        self._table = QTableWidget(0, len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        self._new = QPushButton("Ny profil...")
        self._new.setToolTip("Skapa en profil från en importerad fil i importguiden")
        self._new.clicked.connect(self._create_profile)
        buttons.addWidget(self._new)
        self._rename = QPushButton("Byt namn...")
        self._rename.clicked.connect(self._rename_profile)
        buttons.addWidget(self._rename)
        self._delete = QPushButton("Ta bort...")
        self._delete.clicked.connect(self._delete_profile)
        buttons.addWidget(self._delete)
        buttons.addStretch()
        refresh = QPushButton("Uppdatera")
        refresh.clicked.connect(self.reload)
        buttons.addWidget(refresh)
        layout.addLayout(buttons)

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._status)
        self.reload()

    # ── Data ───────────────────────────────────────────────────────────
    def reload(self) -> None:
        try:
            rows = profile_rows(self._store)
            error = ""
        except ProfileError as exc:  # skyddsnät: trasig fil ska inte krascha fliken
            rows, error = [], str(exc)
        self._table.setRowCount(len(rows))
        for index, (name, columns) in enumerate(rows):
            self._table.setItem(index, 0, QTableWidgetItem(name))
            count = QTableWidgetItem(str(columns))
            count.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(index, 1, count)
        self._table.resizeRowsToContents()
        if error:
            self._status.setText(f"Profilfilen kunde inte läsas: {error}")
        elif rows:
            self._status.setText(f"{len(rows)} profil{'er' if len(rows) != 1 else ''} sparade.")
        else:
            self._status.setText(
                "Inga profiler ännu. Skapa den första i importguiden: mappa kolumnerna "
                "och välj Spara profil.")
        self._update_buttons()

    def _selected_name(self) -> str:
        row = self._table.currentRow()
        item = self._table.item(row, 0) if row >= 0 else None
        return item.text() if item is not None else ""

    def _update_buttons(self) -> None:
        has_selection = bool(self._selected_name())
        self._rename.setEnabled(has_selection)
        self._delete.setEnabled(has_selection)

    # ── Åtgärder ───────────────────────────────────────────────────────
    def _create_profile(self) -> None:
        # En profil behöver en mappning; den skapas där kolumnerna finns.
        QMessageBox.information(
            self, "Ny profil",
            "Öppna importguiden (Arkiv → Importera) och mappa kolumnerna. "
            "Där kan du spara mappningen som en ny profil. Den dyker sedan upp här.")

    def _rename_profile(self) -> None:
        name = self._selected_name()
        if not name:
            return
        new_name, accepted = QInputDialog.getText(
            self, "Byt namn på profil", f"Nytt namn för '{name}':", text=name)
        if not accepted or not new_name.strip() or new_name.strip() == name:
            return
        try:
            renamed = self._store.rename(name, new_name)
        except FileExistsError as exc:
            QMessageBox.warning(self, "Profilen finns redan", str(exc))
            return
        except ProfileError as exc:
            QMessageBox.warning(self, "Namnet kan inte användas", str(exc))
            return
        self.reload()
        self._status.setText(f"Profilen bytte namn till '{renamed}'.")

    def _delete_profile(self) -> None:
        name = self._selected_name()
        if not name:
            return
        answer = QMessageBox.question(
            self, "Ta bort profil",
            f"Ta bort profilen '{name}'? Mappningen går inte att ångra. "
            "Importerade data påverkas inte.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.delete(name)
        except ProfileError as exc:
            QMessageBox.warning(self, "Profilen kunde inte tas bort", str(exc))
            return
        self.reload()
        self._status.setText(f"Profilen '{name}' togs bort.")


class ProfilesDialog(QDialog):
    """Samma flik i ett eget fönster, för menyn Inställningar."""

    def __init__(self, parent=None, store: ProfileStore | None = None):
        super().__init__(parent)
        self.setWindowTitle("Profiler")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        self._tab = ProfilesTab(self, store)
        layout.addWidget(self._tab)
        close = QPushButton("Stäng")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
