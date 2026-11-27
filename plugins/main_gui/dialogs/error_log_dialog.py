"""Felsökningslogg: apploggens filer och de aktiva felen.

Loggflikarna visar appens egen logg (aktuell och tidigare). Fliken **Aktiva
fel** visar registret över fel som fortfarande gäller, med möjlighet att
markera dem som åtgärdade och sedan ta bort dem ur loggen – det är den enda
platsen där loggen ändras, och bara efter att användaren valt det.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.daily_logging import active_error_codes, mark_resolved, remove_error_codes
from core.error_log_view import MAX_DISPLAY_BYTES, current_summary_path, read_log_tail
from core.error_summary import BACKUPS

ERROR_COLUMNS = ("Felkod", "Senast", "Antal", "Status", "Meddelande")


def error_rows(log_dir: Path) -> list[tuple[str, str, int, str, str]]:
    """Bygg tabellrader av de aktiva felen – endast verkliga värden."""
    rows = []
    for entry in active_error_codes(log_dir):
        rows.append((
            str(entry.get("code") or "—"),
            str(entry.get("last_seen") or "—").replace("T", " ")[:19],
            int(entry.get("count") or 0),
            str(entry.get("status") or "aktiv"),
            str(entry.get("message") or ""),
        ))
    return rows


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
        self._files.addItem("Aktiva fel", -1)
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

        faults = QWidget()
        self._faults_panel = faults
        faults_layout = QVBoxLayout(faults)
        faults_layout.setContentsMargins(0, 0, 0, 0)
        self._faults = QTableWidget(0, len(ERROR_COLUMNS))
        self._faults.setHorizontalHeaderLabels(list(ERROR_COLUMNS))
        self._faults.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._faults.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._faults.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._faults.setAlternatingRowColors(True)
        self._faults.verticalHeader().setVisible(False)
        header = self._faults.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(ERROR_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        faults_layout.addWidget(self._faults)
        fault_buttons = QHBoxLayout()
        self._resolve = QPushButton("Markera åtgärdade")
        self._resolve.setToolTip("Flytta de valda felen till åtgärdade när du själv har rättat dem")
        self._resolve.clicked.connect(self._mark_selected_resolved)
        fault_buttons.addWidget(self._resolve)
        self._remove = QPushButton("Ta bort ur felloggen")
        self._remove.setToolTip("Ta bort åtgärdade fel ur registret. Aktiva fel kan inte tas bort.")
        self._remove.clicked.connect(self._remove_selected)
        fault_buttons.addWidget(self._remove)
        fault_buttons.addStretch()
        faults_layout.addLayout(fault_buttons)
        self._faults_note = QLabel(
            "Bara fel som fortfarande gäller visas här. När ett fel är rättat markerar du "
            "det som åtgärdat och kan sedan ta bort det.")
        self._faults_note.setWordWrap(True)
        self._faults_note.setTextFormat(Qt.TextFormat.PlainText)
        faults_layout.addWidget(self._faults_note)
        layout.addWidget(faults)

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
        showing_faults = self._files.currentData() == -1
        self._viewer.setVisible(not showing_faults)
        self._faults_panel.setVisible(showing_faults)
        if showing_faults:
            self._reload_faults()
            return
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

    def _reload_faults(self) -> None:
        """Fyll tabellen med de fel som fortfarande är aktiva."""
        log_dir = self._log_path.parent
        self._path_label.setText(str(log_dir / "felkoder.json"))
        rows = error_rows(log_dir)
        self._faults.setRowCount(len(rows))
        keys = [entry["key"] for entry in active_error_codes(log_dir)]
        for index, row in enumerate(rows):
            for column, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                if column in (1, 2):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column == 0 and index < len(keys):
                    # Nyckeln följer raden, så att två fel med samma kod kan
                    # hanteras var för sig.
                    item.setData(Qt.ItemDataRole.UserRole, keys[index])
                self._faults.setItem(index, column, item)
        self._copy.setEnabled(False)
        if rows:
            self._status.setText(f"{len(rows)} aktiv{'t' if len(rows) == 1 else 'a'} fel. "
                                 "Markera ett fel och välj Markera åtgärdade när det är rättat.")
        else:
            self._status.setText("Inga aktiva fel. Loggen är tom eftersom allt som registrerats är åtgärdat.")

    def _selected_keys(self) -> list[str]:
        keys = []
        for index in sorted({item.row() for item in self._faults.selectedItems()}):
            item = self._faults.item(index, 0)
            key = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if isinstance(key, str) and key:
                keys.append(key)
        return keys

    def _mark_selected_resolved(self) -> None:
        keys = self._selected_keys()
        if not keys:
            QMessageBox.information(self, "Inga valda fel",
                                    "Markera först ett eller flera fel i listan.")
            return
        changed = mark_resolved(self._log_path.parent, keys, "Markerad som åtgärdad i felsökningsloggen.")
        self._reload()
        if changed:
            self._status.setText(f"{changed} fel markerades som åtgärdade och kan nu tas bort ur loggen.")

    def _remove_selected(self) -> None:
        keys = self._selected_keys()
        if not keys:
            QMessageBox.information(self, "Inga valda fel",
                                    "Markera först ett eller flera fel i listan.")
            return
        # Bara åtgärdade fel tas bort; aktiva fel behålls och förklaras.
        removed = remove_error_codes(self._log_path.parent, keys)
        self._reload()
        if removed:
            self._status.setText(f"{removed} åtgärdat fel togs bort ur felloggen.")
        else:
            self._status.setText("Inget togs bort. Markera felet som åtgärdat innan det kan tas bort.")

    def reload(self) -> None:
        """Uppdatera visningen när fönstret öppnas igen."""
        self._reload()

    def _copy_text(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._viewer.toPlainText())
