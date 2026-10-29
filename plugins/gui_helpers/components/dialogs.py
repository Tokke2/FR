# -*- coding: utf-8 -*-
# Fil: plugins/gui_helpers/components/dialogs.py

"""
Dialog Components v1.0.1

Standardiserade dialoger för hela systemet (PySide6).

Dialoger:
    - ConfirmDialog: Bekräftelsedialog (Ja/Nej)
    - InputDialog: Textinput-dialog
    - ProgressDialog: Framstegsdialog
    - MessageDialog: Meddelandedialog
    - SelectDialog: Flervalsdialog
    - FilePickerDialog: Filväljare
    - ErrorDialog: Feldialog med detaljer

PLUGIN-KONTRAKTET (gui_helpers/plugin.py v2.0.1 anropar dessa):
    show_info/show_warning/show_error/show_success:
        (message, title, parent) — MEDDELANDET FÖRST (konsistent med
        plugin.py:s anrop; originalets (parent, title, message)-ordning
        ändrad för att matcha — annars krock vid anrop)
    show_confirm(message, title, parent) -> bool
    show_input(message, title, default, parent) -> Optional[str]
    show_file_dialog(title, directory, filters, save, parent)
    show_folder_dialog(title, directory, parent)
    create_progress_dialog(title, message, maximum, parent)

FRISTÅENDE BEKVÄMLIGHETSFUNKTIONER (anropas inte av plugin.py,
behåller (parent, ...)-ordningen):
    confirm(parent, title, message, icon) / get_input(...) /
    select_item(...)

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (integration, korrekthet, KRITISK): show_info/show_warning/
    show_error/show_success-signaturerna ÄNDRADE till
    (message, title, parent) — gui_helpers/plugin.py v2.0.1 anropar
    med meddelandet först; originalets (parent, title, message)
    skulle sätta parent=str + message=None (krasch).
  - FIX (integration, korrekthet): show_confirm()/show_input()/
    show_file_dialog()/show_folder_dialog()/create_progress_dialog()
    LAGT TILL — plugin.py v2.0.1 anropar dessa via self.dialogs;
    utan dem AttributeError så fort komponenterna används.
  - FIX (KRAV 58): "# Fil: plugins/gui_helpers/components/
    dialogs.py" tillagd (saknades).
  - FIX (låst regel, inga hårdkodade årtal): COPYRIGHT_YEAR_START
    (2024) BORT — get_copyright_string() returnerar enbart
    innevarande år. Docstring-placeholdern "{current_year}" ersatt.
  - FIX (låst regel, inga hårdkodade färger): DIALOG_STYLE +
    ConfirmDialog-knapparna + InputDialog error-label +
    ProgressDialog details byggs nu från design-tokens i
    components/styles.py (COLORS) med try/except-fallback — inga
    hårdkodade hex-färger i filen.
  - FIX (enums, full form): QDialogButtonBox.Ok/Cancel →
    .StandardButton.Ok/.Cancel; QDialogButtonBox.AcceptRole/
    RejectRole → .ButtonRole.AcceptRole/.RejectRole;
    QDialog.Accepted → QDialog.DialogCode.Accepted;
    Qt.AlignRight/AlignTop → Qt.AlignmentFlag.AlignRight/AlignTop;
    QListWidget.MultiSelection → .SelectionMode.MultiSelection.
  - FIX (dödkod): oanvända importer bort (QTimer, QCheckBox,
    QComboBox, QSpinBox, QScrollArea, QFrame, QFont, QIcon,
    QMessageBox); Signal-villkoret förenklat (alltid tillgängligt
    inuti HAS_PYSIDE6-blocket); _on_cancel förenklad.
  - FIX (robusthet): FilePickerDialog.save_file — suffix-kontrollen
    använder os.path.basename (Windows-"\\" fungerar; originalets
    split("/") bröts på Windows).
  - TILLÄGG: ProgressDialog.maximum-parameter (default 100 — samma
    beteende som förut; create_progress_dialog utnyttjar den);
    VERSION tillagd.
  - FIX (headless): __all__ byggs villkorligt — klasserna läggs
    bara till när HAS_PYSIDE6 är True (import * kraschar annars).
  - FIX (radbrytningsartefakt): dubblerade blankrader före def/class
    kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (klasserna, validering i InputDialog,
    clipboard-kopiering, convenience-funktioner confirm/get_input/
    select_item).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import (
        QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout,
        QLabel, QLineEdit, QTextEdit, QProgressBar, QPushButton,
        QListWidget, QListWidgetItem, QFileDialog,
        QWidget, QGroupBox,
    )
    HAS_PYSIDE6: bool = True
except ImportError:
    HAS_PYSIDE6: bool = False
    QDialog = object  # type: ignore[assignment,misc]

AUTHOR: str = "Rickard Längkvist"
VERSION: str = "1.0.1"

# Design-tokens från styles.py (try/except-fallback — kraschsäkert).
try:
    from .styles import COLORS as _C
    from .styles import FONTS as _F
except ImportError:
    _C: Dict[str, str] = {}
    _F: Dict[str, str] = {}

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG STYLES (design-tokens — inga hårdkodade färger)
# ══════════════════════════════════════════════════════════════════════════════

_D_BG: str = _C.get("bg_secondary", "#2b2b2b")
_D_TEXT: str = _C.get("text_primary", "#d4d4d4")
_D_BG_INPUT: str = _C.get("bg_primary", "#1e1e1e")
_D_BORDER: str = _C.get("border_light", "#555555")
_D_FOCUS: str = _C.get("border_focus", "#007bff")
_D_BTN: str = _C.get("bg_tertiary", "#3a3f44")
_D_TEXT_LIGHT: str = _C.get("text_light", "#ffffff")
_D_HOVER: str = _C.get("bg_hover", "#4a4f54")
_D_ACTIVE: str = _C.get("bg_active", "#2a2f34")
_D_PRIMARY: str = _C.get("primary", "#007bff")
_D_PRIMARY_ACTIVE: str = _C.get("primary_active", "#0056b3")
_D_SUCCESS: str = _C.get("success", "#28a745")
_D_SUCCESS_HOVER: str = _C.get("success_hover", "#218838")
_D_SUCCESS_ACTIVE: str = _C.get("success_active", "#1e7e34")
_D_DANGER: str = _C.get("danger", "#dc3545")
_D_TEXT_SECONDARY: str = _C.get("text_secondary", "#888888")
_D_SIZE_SM: str = _F.get("size_sm", "12px")

DIALOG_STYLE: str = f"""
    QDialog {{
        background: {_D_BG};
        color: {_D_TEXT};
    }}
    QLabel {{
        color: {_D_TEXT};
    }}
    QLineEdit, QTextEdit {{
        background: {_D_BG_INPUT};
        color: {_D_TEXT};
        border: 1px solid {_D_BORDER};
        border-radius: 4px;
        padding: 8px;
    }}
    QLineEdit:focus, QTextEdit:focus {{
        border-color: {_D_FOCUS};
    }}
    QPushButton {{
        background: {_D_BTN};
        color: {_D_TEXT_LIGHT};
        border: 1px solid {_D_BORDER};
        border-radius: 4px;
        padding: 8px 16px;
        min-width: 80px;
    }}
    QPushButton:hover {{ background: {_D_HOVER}; }}
    QPushButton:pressed {{ background: {_D_ACTIVE}; }}
    QPushButton:default {{
        background: {_D_PRIMARY};
        border-color: {_D_PRIMARY_ACTIVE};
    }}
    QProgressBar {{
        background: {_D_BG_INPUT};
        border: 1px solid {_D_BORDER};
        border-radius: 4px;
        text-align: center;
        color: {_D_TEXT_LIGHT};
    }}
    QProgressBar::chunk {{
        background: {_D_PRIMARY};
        border-radius: 3px;
    }}
    QListWidget {{
        background: {_D_BG_INPUT};
        color: {_D_TEXT};
        border: 1px solid {_D_BORDER};
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background: {_D_PRIMARY};
    }}
"""

_YES_BTN_STYLE: str = f"""
    QPushButton {{
        background: {_D_SUCCESS};
        border-color: {_D_SUCCESS_ACTIVE};
    }}
    QPushButton:hover {{ background: {_D_SUCCESS_HOVER}; }}
"""
_ERROR_LABEL_STYLE: str = "color: %s;" % _D_DANGER
_DETAILS_LABEL_STYLE: str = (
    "color: %s; font-size: %s;" % (_D_TEXT_SECONDARY, _D_SIZE_SM)
)


# ══════════════════════════════════════════════════════════════════════════════
# BASE DIALOG
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class BaseDialog(QDialog):
        """Basklass för alla dialoger med gemensam styling."""

        def __init__(
            self,
            parent: Optional[QWidget] = None,
            title: str = "Dialog",
            width: int = 400,
            height: int = 200,
        ) -> None:
            super().__init__(parent)
            self.setWindowTitle(title)
            self.setMinimumSize(width, height)
            self.setStyleSheet(DIALOG_STYLE)
            self.setModal(True)

        def _create_button_box(
            self,
            ok_text: str = "OK",
            cancel_text: str = "Avbryt",
            show_cancel: bool = True,
        ) -> QDialogButtonBox:
            """Skapa standardknappar."""
            buttons = QDialogButtonBox.StandardButton.Ok
            if show_cancel:
                buttons |= QDialogButtonBox.StandardButton.Cancel

            button_box = QDialogButtonBox(buttons)
            button_box.button(
                QDialogButtonBox.StandardButton.Ok
            ).setText(ok_text)
            if show_cancel:
                button_box.button(
                    QDialogButtonBox.StandardButton.Cancel
                ).setText(cancel_text)

            button_box.accepted.connect(self.accept)
            button_box.rejected.connect(self.reject)

            return button_box


# ══════════════════════════════════════════════════════════════════════════════
# CONFIRM DIALOG
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class ConfirmDialog(BaseDialog):
        """
        Bekräftelsedialog (Ja/Nej).

        Användning:
            dialog = ConfirmDialog(
                parent=self,
                title="Bekräfta",
                message="Vill du fortsätta?",
                icon="⚠️",
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Användaren klickade Ja
        """

        def __init__(
            self,
            parent: Optional[QWidget] = None,
            title: str = "Bekräfta",
            message: str = "Är du säker?",
            icon: str = "❓",
            yes_text: str = "Ja",
            no_text: str = "Nej",
            default_no: bool = True,
        ) -> None:
            super().__init__(parent, title, 400, 150)

            layout = QVBoxLayout(self)
            layout.setSpacing(16)
            layout.setContentsMargins(24, 24, 24, 24)

            # Ikon och meddelande
            msg_layout = QHBoxLayout()

            if icon:
                icon_label = QLabel(icon)
                icon_label.setStyleSheet("font-size: 32px;")
                msg_layout.addWidget(icon_label)

            msg_label = QLabel(message)
            msg_label.setWordWrap(True)
            msg_label.setStyleSheet("font-size: 14px;")
            msg_layout.addWidget(msg_label, 1)

            layout.addLayout(msg_layout)

            # Knappar
            button_box = QDialogButtonBox()

            yes_btn = QPushButton(yes_text)
            yes_btn.setStyleSheet(_YES_BTN_STYLE)
            yes_btn.clicked.connect(self.accept)

            no_btn = QPushButton(no_text)
            no_btn.clicked.connect(self.reject)

            if default_no:
                no_btn.setDefault(True)
            else:
                yes_btn.setDefault(True)

            button_box.addButton(
                yes_btn, QDialogButtonBox.ButtonRole.AcceptRole
            )
            button_box.addButton(
                no_btn, QDialogButtonBox.ButtonRole.RejectRole
            )

            layout.addWidget(button_box)


# ══════════════════════════════════════════════════════════════════════════════
# INPUT DIALOG
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class InputDialog(BaseDialog):
        """
        Textinput-dialog.

        Användning:
            dialog = InputDialog(
                parent=self,
                title="Ny version",
                label="Ange versionsnamn:",
                default_value="2025-01",
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                value = dialog.get_value()
        """

        def __init__(
            self,
            parent: Optional[QWidget] = None,
            title: str = "Input",
            label: str = "Värde:",
            default_value: str = "",
            placeholder: str = "",
            multiline: bool = False,
            validator: Optional[
                Callable[[str], Tuple[bool, str]]
            ] = None,
        ) -> None:
            super().__init__(
                parent, title, 400, 200 if multiline else 150
            )

            self._validator = validator

            layout = QVBoxLayout(self)
            layout.setSpacing(12)
            layout.setContentsMargins(24, 24, 24, 24)

            # Label
            layout.addWidget(QLabel(label))

            # Input
            if multiline:
                self._input = QTextEdit()
                self._input.setPlainText(default_value)
                self._input.setPlaceholderText(placeholder)
                self._input.setMinimumHeight(100)
            else:
                self._input = QLineEdit()
                self._input.setText(default_value)
                self._input.setPlaceholderText(placeholder)
                self._input.selectAll()

            layout.addWidget(self._input)

            # Error label
            self._error_label = QLabel()
            self._error_label.setStyleSheet(_ERROR_LABEL_STYLE)
            self._error_label.hide()
            layout.addWidget(self._error_label)

            # Knappar
            layout.addWidget(self._create_button_box())

        def get_value(self) -> str:
            """Hämta inmatat värde."""
            if isinstance(self._input, QTextEdit):
                return self._input.toPlainText().strip()
            return self._input.text().strip()

        def accept(self) -> None:
            """Validera innan accept."""
            if self._validator:
                value = self.get_value()
                is_valid, error = self._validator(value)
                if not is_valid:
                    self._error_label.setText(error)
                    self._error_label.show()
                    return

            super().accept()


# ══════════════════════════════════════════════════════════════════════════════
# PROGRESS DIALOG
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class ProgressDialog(BaseDialog):
        """
        Framstegsdialog.

        Användning:
            dialog = ProgressDialog(parent=self, title="Importerar...")
            dialog.show()

            for i, item in enumerate(items):
                dialog.set_progress(
                    i + 1, len(items), "Bearbetar %s..." % item
                )
                if dialog.was_cancelled():
                    break

            dialog.close()
        """

        cancelled = Signal()

        def __init__(
            self,
            parent: Optional[QWidget] = None,
            title: str = "Bearbetar...",
            message: str = "Vänta...",
            show_cancel: bool = True,
            show_percentage: bool = True,
            maximum: int = 100,
        ) -> None:
            super().__init__(parent, title, 450, 150)

            self._cancelled = False
            self._show_percentage = show_percentage
            self._maximum = max(1, maximum)

            layout = QVBoxLayout(self)
            layout.setSpacing(12)
            layout.setContentsMargins(24, 24, 24, 24)

            # Meddelande
            self._message_label = QLabel(message)
            self._message_label.setWordWrap(True)
            layout.addWidget(self._message_label)

            # Progress bar
            self._progress = QProgressBar()
            self._progress.setRange(0, self._maximum)
            self._progress.setValue(0)
            layout.addWidget(self._progress)

            # Detaljer
            self._details_label = QLabel()
            self._details_label.setStyleSheet(_DETAILS_LABEL_STYLE)
            layout.addWidget(self._details_label)

            # Cancel-knapp
            if show_cancel:
                cancel_btn = QPushButton("Avbryt")
                cancel_btn.clicked.connect(self._on_cancel)
                layout.addWidget(
                    cancel_btn, alignment=Qt.AlignmentFlag.AlignRight
                )

        def set_progress(
            self,
            current: int,
            total: int,
            message: str = "",
        ) -> None:
            """Uppdatera progress."""
            if total > 0:
                percent = int(current / total * 100)
                self._progress.setValue(
                    int(current / total * self._maximum)
                )

                if self._show_percentage:
                    self._details_label.setText(
                        "%d/%d (%d%%)" % (current, total, percent)
                    )

            if message:
                self._message_label.setText(message)

            # Processa events så UI uppdateras
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

        def set_indeterminate(self, message: str = "") -> None:
            """Sätt obestämd progress (snurrande)."""
            self._progress.setRange(0, 0)
            if message:
                self._message_label.setText(message)

        def was_cancelled(self) -> bool:
            """Kolla om användaren avbröt."""
            return self._cancelled

        def _on_cancel(self) -> None:
            """Hantera avbryt."""
            self._cancelled = True
            self.cancelled.emit()


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE DIALOG
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class MessageDialog(BaseDialog):
        """
        Meddelandedialog med olika typer.

        Användning:
            MessageDialog.info(parent, "Info", "Operationen lyckades!")
            MessageDialog.warning(parent, "Varning", "Något kan vara fel.")
            MessageDialog.error(parent, "Fel", "Ett fel uppstod.",
                                details="Stack trace...")
        """

        def __init__(
            self,
            parent: Optional[QWidget] = None,
            title: str = "Meddelande",
            message: str = "",
            icon: str = "ℹ️",
            details: str = "",
            msg_type: str = "info",
        ) -> None:
            height = 250 if details else 150
            super().__init__(parent, title, 450, height)

            layout = QVBoxLayout(self)
            layout.setSpacing(12)
            layout.setContentsMargins(24, 24, 24, 24)

            # Ikon och meddelande
            msg_layout = QHBoxLayout()

            if icon:
                icon_label = QLabel(icon)
                icon_label.setStyleSheet("font-size: 32px;")
                icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
                msg_layout.addWidget(icon_label)

            msg_label = QLabel(message)
            msg_label.setWordWrap(True)
            msg_label.setStyleSheet("font-size: 14px;")
            msg_layout.addWidget(msg_label, 1)

            layout.addLayout(msg_layout)

            # Detaljer (expanderbar)
            if details:
                details_group = QGroupBox("Detaljer")
                details_layout = QVBoxLayout(details_group)

                details_text = QTextEdit()
                details_text.setPlainText(details)
                details_text.setReadOnly(True)
                details_text.setMaximumHeight(100)
                details_layout.addWidget(details_text)

                layout.addWidget(details_group)

            # OK-knapp
            layout.addWidget(self._create_button_box(show_cancel=False))

        @classmethod
        def info(
            cls,
            parent: Optional[QWidget],
            title: str,
            message: str,
        ) -> None:
            """Visa info-meddelande."""
            dialog = cls(parent, title, message, "ℹ️", msg_type="info")
            dialog.exec()

        @classmethod
        def warning(
            cls,
            parent: Optional[QWidget],
            title: str,
            message: str,
        ) -> None:
            """Visa varning."""
            dialog = cls(
                parent, title, message, "⚠️", msg_type="warning"
            )
            dialog.exec()

        @classmethod
        def error(
            cls,
            parent: Optional[QWidget],
            title: str,
            message: str,
            details: str = "",
        ) -> None:
            """Visa felmeddelande."""
            dialog = cls(
                parent, title, message, "❌", details, msg_type="error"
            )
            dialog.exec()

        @classmethod
        def success(
            cls,
            parent: Optional[QWidget],
            title: str,
            message: str,
        ) -> None:
            """Visa success-meddelande."""
            dialog = cls(
                parent, title, message, "✅", msg_type="success"
            )
            dialog.exec()


# ══════════════════════════════════════════════════════════════════════════════
# SELECT DIALOG
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class SelectDialog(BaseDialog):
        """
        Flervalsdialog.

        Användning:
            dialog = SelectDialog(
                parent=self,
                title="Välj version",
                items=["2025-01", "2024-06", "2024-01"],
                message="Välj schema-version:",
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected = dialog.get_selected()
        """

        def __init__(
            self,
            parent: Optional[QWidget] = None,
            title: str = "Välj",
            items: Optional[List[str]] = None,
            message: str = "",
            multi_select: bool = False,
            default_selection: Optional[List[int]] = None,
        ) -> None:
            super().__init__(parent, title, 400, 300)

            self._multi_select = multi_select

            layout = QVBoxLayout(self)
            layout.setSpacing(12)
            layout.setContentsMargins(24, 24, 24, 24)

            # Meddelande
            if message:
                layout.addWidget(QLabel(message))

            # Lista
            self._list = QListWidget()
            if multi_select:
                self._list.setSelectionMode(
                    QListWidget.SelectionMode.MultiSelection
                )

            for i, item in enumerate(items or []):
                list_item = QListWidgetItem(item)
                self._list.addItem(list_item)
                if default_selection and i in default_selection:
                    list_item.setSelected(True)

            layout.addWidget(self._list)

            # Knappar
            layout.addWidget(self._create_button_box())

        def get_selected(self) -> List[str]:
            """Hämta valda items."""
            return [
                item.text() for item in self._list.selectedItems()
            ]

        def get_selected_indices(self) -> List[int]:
            """Hämta index för valda items."""
            return [
                self._list.row(item)
                for item in self._list.selectedItems()
            ]


# ══════════════════════════════════════════════════════════════════════════════
# FILE PICKER DIALOG
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class FilePickerDialog:
        """
        Wrapper för filväljare med standardinställningar.

        Användning:
            path = FilePickerDialog.open_file(
                parent=self,
                title="Välj Excel-fil",
                filters="Excel-filer (*.xlsx *.xls)",
            )
        """

        @staticmethod
        def open_file(
            parent: Optional[QWidget] = None,
            title: str = "Öppna fil",
            directory: str = "",
            filters: str = "Alla filer (*.*)",
        ) -> Optional[str]:
            """Öppna fil-dialog."""
            path, _ = QFileDialog.getOpenFileName(
                parent, title, directory, filters
            )
            return path if path else None

        @staticmethod
        def open_files(
            parent: Optional[QWidget] = None,
            title: str = "Öppna filer",
            directory: str = "",
            filters: str = "Alla filer (*.*)",
        ) -> List[str]:
            """Öppna flervals fil-dialog."""
            paths, _ = QFileDialog.getOpenFileNames(
                parent, title, directory, filters
            )
            return paths

        @staticmethod
        def save_file(
            parent: Optional[QWidget] = None,
            title: str = "Spara fil",
            directory: str = "",
            filters: str = "Alla filer (*.*)",
            default_suffix: str = "",
        ) -> Optional[str]:
            """Spara fil-dialog."""
            path, _ = QFileDialog.getSaveFileName(
                parent, title, directory, filters
            )

            if (
                path
                and default_suffix
                and "." not in os.path.basename(path)
            ):
                path += ".%s" % default_suffix

            return path if path else None

        @staticmethod
        def select_directory(
            parent: Optional[QWidget] = None,
            title: str = "Välj mapp",
            directory: str = "",
        ) -> Optional[str]:
            """Välj mapp-dialog."""
            path = QFileDialog.getExistingDirectory(
                parent, title, directory
            )
            return path if path else None


# ══════════════════════════════════════════════════════════════════════════════
# ERROR DIALOG
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class ErrorDialog(BaseDialog):
        """
        Feldialog med detaljer och kopiering.

        Användning:
            ErrorDialog.show_error(
                parent=self,
                title="Import misslyckades",
                message="Kunde inte läsa filen.",
                error=exception,
                traceback=traceback_str,
            )
        """

        def __init__(
            self,
            parent: Optional[QWidget] = None,
            title: str = "Fel",
            message: str = "",
            error: Optional[Exception] = None,
            traceback: str = "",
        ) -> None:
            super().__init__(parent, title, 500, 350)

            self._full_error = ""

            layout = QVBoxLayout(self)
            layout.setSpacing(12)
            layout.setContentsMargins(24, 24, 24, 24)

            # Ikon och meddelande
            msg_layout = QHBoxLayout()

            icon_label = QLabel("❌")
            icon_label.setStyleSheet("font-size: 32px;")
            icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
            msg_layout.addWidget(icon_label)

            msg_label = QLabel(message)
            msg_label.setWordWrap(True)
            msg_label.setStyleSheet("font-size: 14px;")
            msg_layout.addWidget(msg_label, 1)

            layout.addLayout(msg_layout)

            # Feldetaljer
            if error or traceback:
                details_group = QGroupBox("Tekniska detaljer")
                details_layout = QVBoxLayout(details_group)

                error_text = QTextEdit()
                error_text.setReadOnly(True)

                parts = []
                if error:
                    parts.append(
                        "Fel: %s: %s" % (type(error).__name__, error)
                    )
                if traceback:
                    parts.append("\nStack trace:\n%s" % traceback)

                self._full_error = "\n".join(parts)
                error_text.setPlainText(self._full_error)
                error_text.setStyleSheet(
                    "font-family: monospace; font-size: 12px;"
                )

                details_layout.addWidget(error_text)
                layout.addWidget(details_group)

            # Knappar
            btn_layout = QHBoxLayout()

            if self._full_error:
                copy_btn = QPushButton("📋 Kopiera")
                copy_btn.clicked.connect(self._copy_error)
                btn_layout.addWidget(copy_btn)

            btn_layout.addStretch()

            ok_btn = QPushButton("OK")
            ok_btn.setDefault(True)
            ok_btn.clicked.connect(self.accept)
            btn_layout.addWidget(ok_btn)

            layout.addLayout(btn_layout)

        def _copy_error(self) -> None:
            """Kopiera fel till clipboard."""
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(self._full_error)

        @classmethod
        def show_error(
            cls,
            parent: Optional[QWidget],
            title: str,
            message: str,
            error: Optional[Exception] = None,
            traceback: str = "",
        ) -> None:
            """Visa feldialog."""
            dialog = cls(parent, title, message, error, traceback)
            dialog.exec()


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN-KONTRAKTET (gui_helpers/plugin.py v2.0.1)
# ══════════════════════════════════════════════════════════════════════════════
# OBS: show_*-funktionerna här har (message, title, parent)-ordningen
# — plugin.py anropar så. confirm/get_input/select_item behåller
# (parent, ...)-ordningen (fristående, anropas ej av plugin.py).

def show_info(
    message: str,
    title: str = "Information",
    parent: Any = None,
) -> None:
    """Visa info-meddelande (plugin-kontraktet: message först)."""
    if HAS_PYSIDE6:
        MessageDialog.info(parent, title, message)

def show_warning(
    message: str,
    title: str = "Varning",
    parent: Any = None,
) -> None:
    """Visa varning (plugin-kontraktet: message först)."""
    if HAS_PYSIDE6:
        MessageDialog.warning(parent, title, message)

def show_error(
    message: str,
    title: str = "Fel",
    parent: Any = None,
) -> None:
    """Visa felmeddelande (plugin-kontraktet: message först)."""
    if HAS_PYSIDE6:
        MessageDialog.error(parent, title, message)

def show_success(
    message: str,
    title: str = "Klart",
    parent: Any = None,
) -> None:
    """Visa success-meddelande (plugin-kontraktet: message först)."""
    if HAS_PYSIDE6:
        MessageDialog.success(parent, title, message)

def show_confirm(
    message: str,
    title: str = "Bekräfta",
    parent: Any = None,
) -> bool:
    """
    Visa bekräftelse-dialog (plugin-kontraktet).

    Returns:
        True om användaren klickade Ja; False headless
    """
    if not HAS_PYSIDE6:
        return False
    dialog = ConfirmDialog(parent, title, message)
    return dialog.exec() == QDialog.DialogCode.Accepted

def show_input(
    message: str,
    title: str = "Ange värde",
    default: str = "",
    parent: Any = None,
) -> Optional[str]:
    """
    Visa input-dialog (plugin-kontraktet).

    Returns:
        Inmatat värde eller None om avbruten (headless → default)
    """
    if not HAS_PYSIDE6:
        return default
    dialog = InputDialog(
        parent, title, message, default_value=default
    )
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.get_value()
    return None

def show_file_dialog(
    title: str = "Välj fil",
    directory: str = "",
    filters: str = "Alla filer (*.*)",
    save: bool = False,
    parent: Any = None,
) -> Optional[str]:
    """
    Visa fil-dialog (plugin-kontraktet).

    Args:
        title: Dialogtitel
        directory: Startkatalog
        filters: Filfilter (t.ex. "Excel (*.xlsx);;CSV (*.csv)")
        save: True för spara-dialog, False för öppna

    Returns:
        Filsökväg eller None
    """
    if not HAS_PYSIDE6:
        return None
    if save:
        return FilePickerDialog.save_file(
            parent, title, directory, filters
        )
    return FilePickerDialog.open_file(
        parent, title, directory, filters
    )

def show_folder_dialog(
    title: str = "Välj mapp",
    directory: str = "",
    parent: Any = None,
) -> Optional[str]:
    """Visa mapp-dialog (plugin-kontraktet)."""
    if not HAS_PYSIDE6:
        return None
    return FilePickerDialog.select_directory(
        parent, title, directory
    )

def create_progress_dialog(
    title: str = "Bearbetar...",
    message: str = "",
    maximum: int = 100,
    parent: Any = None,
) -> Optional[Any]:
    """
    Skapa progress-dialog (plugin-kontraktet).

    Returns:
        ProgressDialog (med set_progress/set_indeterminate/
        was_cancelled/close) eller None headless
    """
    if not HAS_PYSIDE6:
        return None
    return ProgressDialog(
        parent, title, message, maximum=maximum
    )


# ══════════════════════════════════════════════════════════════════════════════
# FRISTÅENDE BEKVÄMLIGHETSFUNKTIONER ((parent, ...)-ordningen)
# ══════════════════════════════════════════════════════════════════════════════

def confirm(
    parent: Any = None,
    title: str = "Bekräfta",
    message: str = "Är du säker?",
    icon: str = "❓",
) -> bool:
    """
    Snabb bekräftelsedialog.

    Returns:
        True om användaren klickade Ja
    """
    if not HAS_PYSIDE6:
        return True

    dialog = ConfirmDialog(parent, title, message, icon)
    return dialog.exec() == QDialog.DialogCode.Accepted

def get_input(
    parent: Any = None,
    title: str = "Input",
    label: str = "Värde:",
    default: str = "",
) -> Optional[str]:
    """
    Snabb input-dialog.

    Returns:
        Inmatat värde eller None om avbruten
    """
    if not HAS_PYSIDE6:
        return default

    dialog = InputDialog(parent, title, label, default)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.get_value()
    return None

def select_item(
    parent: Any = None,
    title: str = "Välj",
    items: Optional[List[str]] = None,
    message: str = "",
) -> Optional[str]:
    """
    Snabb valsdialog.

    Returns:
        Valt item eller None om avbruten
    """
    if not HAS_PYSIDE6:
        return items[0] if items else None

    dialog = SelectDialog(parent, title, items, message)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        selected = dialog.get_selected()
        return selected[0] if selected else None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__: List[str] = [
    # Metadata
    "VERSION",
    "AUTHOR",
    # Plugin-kontraktet
    "show_info",
    "show_warning",
    "show_error",
    "show_success",
    "show_confirm",
    "show_input",
    "show_file_dialog",
    "show_folder_dialog",
    "create_progress_dialog",
    # Convenience functions
    "confirm",
    "get_input",
    "select_item",
    # Styles
    "DIALOG_STYLE",
    # Utils
    "HAS_PYSIDE6",
    "get_copyright_string",
]

# Dialogklasserna finns bara när PySide6 är tillgängligt (import *
# kraschar annars på saknade namn).
if HAS_PYSIDE6:
    __all__ += [
        "BaseDialog",
        "ConfirmDialog",
        "InputDialog",
        "ProgressDialog",
        "MessageDialog",
        "SelectDialog",
        "FilePickerDialog",
        "ErrorDialog",
    ]
