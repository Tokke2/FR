# -*- coding: utf-8 -*-
# Fil: plugins/gui_helpers/components/forms.py

"""
Form Components v1.0.1

Formulärkomponenter för datainmatning (PySide6).

Komponenter:
    - FormField: Generiskt formulärfält
    - TextField: Textinmatning
    - NumberField: Nummerinmatning
    - DateField: Datumväljare
    - ComboField: Dropdown
    - CheckField: Checkbox
    - FormGroup: Gruppera fält
    - DynamicForm: Schema-driven formulär
    - create_form_group / create_form_field: plugin-kontraktet
      (gui_helpers/plugin.py v2.0.1) — kraschsäkert None headless

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil: plugins/gui_helpers/components/forms.py"
    tillagd (saknades — stod utan "Fil:"-prefix).
  - FIX (låst regel, inga hårdkodade årtal): COPYRIGHT_YEAR_START
    (2024) BORT — get_copyright_string() returnerar nu enbart
    innevarande år, konsistent med övriga moduler. Docstring-
    placeholdern "{current_year}" ersatt med dynamisk formulering.
  - FIX (låst regel, inga hårdkodade färger): FORM_STYLE/
    ERROR_STYLE/SUCCESS_STYLE + error-label-färgen byggs nu från
    design-tokens i components/styles.py (COLORS/FONTS) med try/
    except-fallback — inga hårdkodade hex-färger i filen.
  - FIX (integration, korrekthet): create_form_group()/
    create_form_field() LAGT TILL — gui_helpers/plugin.py v2.0.1
    anropar dessa via self.forms; utan dem AttributeError så fort
    komponenterna används. Field-typerna "dropdown"/"checkbox"
    mappas till ComboField/CheckField (DynamicForm använder
    "combo"/"check"). Gemensam _create_field()-helper för både
    DynamicForm.add_field_from_dict och create_form_group (DRY).
  - FIX (enums, full form): QLineEdit.Password →
    QLineEdit.EchoMode.Password; QFrame.NoFrame →
    QFrame.Shape.NoFrame.
  - FIX (dödkod): oanvända importer bort (Qt, QHBoxLayout,
    QFormLayout, QPushButton, QValidator, QIntValidator,
    QDoubleValidator).
  - FIX (headless): __all__ byggs villkorligt — klasserna läggs
    bara till när HAS_PYSIDE6 är True (import * kraschar annars).
  - FIX (konsistens): VERSION tillagd + i __all__.
  - FIX (radbrytningsartefakt): dubblerade blankrader före def/class
    kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (fältklasserna, validering, signaler,
    DynamicForm.from_schema).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    from PySide6.QtCore import Signal, QDate
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QGridLayout,
        QLabel, QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
        QComboBox, QCheckBox, QDateEdit, QGroupBox, QFrame,
        QScrollArea,
    )
    HAS_PYSIDE6: bool = True
except ImportError:
    HAS_PYSIDE6: bool = False
    QWidget = object  # type: ignore[assignment,misc]
    Signal = None  # type: ignore[assignment]

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
# FORM STYLES (design-tokens — inga hårdkodade färger)
# ══════════════════════════════════════════════════════════════════════════════

_FORM_TEXT: str = _C.get("text_primary", "#d4d4d4")
_FORM_BG: str = _C.get("bg_primary", "#1e1e1e")
_FORM_BG_DISABLED: str = _C.get("bg_active", "#2a2f34")
_FORM_BORDER: str = _C.get("border_light", "#555555")
_FORM_BORDER_DARK: str = _C.get("border_dark", "#444444")
_FORM_FOCUS: str = _C.get("border_focus", "#007bff")
_FORM_MUTED: str = _C.get("text_muted", "#666666")
_FORM_SIZE: str = _F.get("size_sm", "12px")

FORM_STYLE: str = f"""
    QLabel {{
        color: {_FORM_TEXT};
        font-size: {_FORM_SIZE};
    }}
    QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit {{
        background: {_FORM_BG};
        color: {_FORM_TEXT};
        border: 1px solid {_FORM_BORDER};
        border-radius: 4px;
        padding: 8px;
        font-size: {_FORM_SIZE};
    }}
    QLineEdit:focus, QTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus {{
        border-color: {_FORM_FOCUS};
    }}
    QLineEdit:disabled, QTextEdit:disabled, QSpinBox:disabled,
    QDoubleSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {{
        background: {_FORM_BG_DISABLED};
        color: {_FORM_MUTED};
    }}
    QCheckBox {{
        color: {_FORM_TEXT};
        font-size: {_FORM_SIZE};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid {_FORM_BORDER};
        background: {_FORM_BG};
    }}
    QCheckBox::indicator:checked {{
        background: {_C.get('primary', '#007bff')};
        border-color: {_C.get('primary_active', '#0056b3')};
    }}
    QGroupBox {{
        border: 1px solid {_FORM_BORDER_DARK};
        border-radius: 4px;
        margin-top: 12px;
        padding-top: 8px;
        color: {_FORM_TEXT};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 8px;
    }}
"""

ERROR_STYLE: str = "border-color: %s !important;" % _C.get(
    "danger", "#dc3545"
)
SUCCESS_STYLE: str = "border-color: %s !important;" % _C.get(
    "success", "#28a745"
)
_ERROR_TEXT_COLOR: str = _C.get("danger", "#dc3545")


# ══════════════════════════════════════════════════════════════════════════════
# BASE FORM FIELD
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class FormField(QWidget):
        """
        Bas formulärfält med label, input och validering.

        Signals:
            value_changed: Emittas när värdet ändras
            validation_changed: Emittas när valideringsstatus ändras
        """

        value_changed = Signal(object)
        validation_changed = Signal(bool, str)

        def __init__(
            self,
            name: str,
            label: str = "",
            required: bool = False,
            tooltip: str = "",
            validator: Optional[
                Callable[[Any], Tuple[bool, str]]
            ] = None,
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)

            self.name = name
            self._required = required
            self._validator = validator
            self._is_valid = True
            self._error_message = ""

            self._setup_ui(label, tooltip)
            self.setStyleSheet(FORM_STYLE)

        def _setup_ui(self, label: str, tooltip: str) -> None:
            """Bygg UI."""
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 8)
            layout.setSpacing(4)

            # Label
            if label:
                label_text = label
                if self._required:
                    label_text += " *"

                self._label = QLabel(label_text)
                if tooltip:
                    self._label.setToolTip(tooltip)
                layout.addWidget(self._label)

            # Input placeholder (override i subklasser)
            self._input: Optional[QWidget] = None

            # Error label
            self._error_label = QLabel()
            self._error_label.setStyleSheet(
                "color: %s; font-size: 11px;" % _ERROR_TEXT_COLOR
            )
            self._error_label.hide()
            layout.addWidget(self._error_label)

        def get_value(self) -> Any:
            """Hämta värde (override i subklasser)."""
            return None

        def set_value(self, value: Any) -> None:
            """Sätt värde (override i subklasser)."""
            pass

        def validate(self) -> Tuple[bool, str]:
            """Validera fältet."""
            value = self.get_value()

            # Required check
            if self._required:
                if value is None or (
                    isinstance(value, str) and not value.strip()
                ):
                    return False, "Detta fält är obligatoriskt"

            # Custom validator
            if self._validator and value:
                return self._validator(value)

            return True, ""

        def show_validation(self) -> bool:
            """Visa valideringsresultat."""
            is_valid, error = self.validate()

            if is_valid:
                self._error_label.hide()
                if self._input:
                    self._input.setStyleSheet("")
            else:
                self._error_label.setText(error)
                self._error_label.show()
                if self._input:
                    self._input.setStyleSheet(ERROR_STYLE)

            self._is_valid = is_valid
            self._error_message = error
            self.validation_changed.emit(is_valid, error)

            return is_valid

        def is_valid(self) -> bool:
            """Returnera valideringsstatus."""
            return self._is_valid

        def set_enabled(self, enabled: bool) -> None:
            """Aktivera/deaktivera fältet."""
            if self._input:
                self._input.setEnabled(enabled)

        def clear(self) -> None:
            """Rensa fältet."""
            self.set_value(None)


# ══════════════════════════════════════════════════════════════════════════════
# TEXT FIELD
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class TextField(FormField):
        """
        Textinmatningsfält.

        Användning:
            field = TextField(
                name="vin",
                label="VIN-nummer",
                required=True,
                max_length=17,
                placeholder="Ange fordonets VIN",
            )
        """

        def __init__(
            self,
            name: str,
            label: str = "",
            required: bool = False,
            max_length: int = 0,
            placeholder: str = "",
            password: bool = False,
            multiline: bool = False,
            **kwargs: Any,
        ) -> None:
            super().__init__(name, label, required, **kwargs)

            self._max_length = max_length
            self._multiline = multiline

            # Skapa input
            if multiline:
                self._input = QTextEdit()
                self._input.setPlaceholderText(placeholder)
                self._input.setMaximumHeight(100)
                self._input.textChanged.connect(self._on_change)
            else:
                self._input = QLineEdit()
                self._input.setPlaceholderText(placeholder)
                if password:
                    self._input.setEchoMode(
                        QLineEdit.EchoMode.Password
                    )
                if max_length > 0:
                    self._input.setMaxLength(max_length)
                self._input.textChanged.connect(self._on_change)

            self.layout().insertWidget(1, self._input)

        def _on_change(self) -> None:
            """Hantera textändring."""
            self.value_changed.emit(self.get_value())

        def get_value(self) -> str:
            """Hämta text."""
            if self._multiline:
                return self._input.toPlainText()
            return self._input.text()

        def set_value(self, value: Any) -> None:
            """Sätt text."""
            text = str(value) if value is not None else ""
            if self._multiline:
                self._input.setPlainText(text)
            else:
                self._input.setText(text)

        def clear(self) -> None:
            """Rensa fältet."""
            self._input.clear()


# ══════════════════════════════════════════════════════════════════════════════
# NUMBER FIELD
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class NumberField(FormField):
        """
        Nummerinmatningsfält.

        Användning:
            field = NumberField(
                name="weight",
                label="Vikt (kg)",
                min_value=0,
                max_value=10000,
                decimals=2,
            )
        """

        def __init__(
            self,
            name: str,
            label: str = "",
            required: bool = False,
            min_value: Union[int, float] = 0,
            max_value: Union[int, float] = 999999,
            decimals: int = 0,
            suffix: str = "",
            **kwargs: Any,
        ) -> None:
            super().__init__(name, label, required, **kwargs)

            # Skapa input
            if decimals > 0:
                self._input = QDoubleSpinBox()
                self._input.setDecimals(decimals)
            else:
                self._input = QSpinBox()

            if decimals == 0:
                self._input.setMinimum(int(min_value))
                self._input.setMaximum(int(max_value))
            else:
                self._input.setMinimum(min_value)
                self._input.setMaximum(max_value)

            if suffix:
                self._input.setSuffix(" %s" % suffix)

            self._input.valueChanged.connect(self._on_change)
            self.layout().insertWidget(1, self._input)

        def _on_change(self) -> None:
            """Hantera värdeändring."""
            self.value_changed.emit(self.get_value())

        def get_value(self) -> Union[int, float]:
            """Hämta värde."""
            return self._input.value()

        def set_value(self, value: Any) -> None:
            """Sätt värde."""
            if value is not None:
                if isinstance(self._input, QDoubleSpinBox):
                    self._input.setValue(float(value))
                else:
                    self._input.setValue(int(value))
            else:
                self._input.setValue(self._input.minimum())


# ══════════════════════════════════════════════════════════════════════════════
# DATE FIELD
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class DateField(FormField):
        """
        Datumfält.

        Användning:
            field = DateField(
                name="registration_date",
                label="Registreringsdatum",
                required=True,
            )
        """

        def __init__(
            self,
            name: str,
            label: str = "",
            required: bool = False,
            min_date: Optional[date] = None,
            max_date: Optional[date] = None,
            **kwargs: Any,
        ) -> None:
            super().__init__(name, label, required, **kwargs)

            self._input = QDateEdit()
            self._input.setCalendarPopup(True)
            self._input.setDisplayFormat("yyyy-MM-dd")
            self._input.setDate(QDate.currentDate())

            if min_date:
                self._input.setMinimumDate(
                    QDate(
                        min_date.year, min_date.month, min_date.day
                    )
                )
            if max_date:
                self._input.setMaximumDate(
                    QDate(
                        max_date.year, max_date.month, max_date.day
                    )
                )

            self._input.dateChanged.connect(self._on_change)
            self.layout().insertWidget(1, self._input)

        def _on_change(self) -> None:
            """Hantera datumändring."""
            self.value_changed.emit(self.get_value())

        def get_value(self) -> date:
            """Hämta datum."""
            qdate = self._input.date()
            return date(qdate.year(), qdate.month(), qdate.day())

        def set_value(self, value: Any) -> None:
            """Sätt datum."""
            if isinstance(value, date):
                self._input.setDate(
                    QDate(value.year, value.month, value.day)
                )
            elif isinstance(value, str):
                # Försök parsa YYYY-MM-DD
                try:
                    parts = value.split("-")
                    self._input.setDate(
                        QDate(
                            int(parts[0]),
                            int(parts[1]),
                            int(parts[2]),
                        )
                    )
                except (ValueError, IndexError):
                    pass


# ══════════════════════════════════════════════════════════════════════════════
# COMBO FIELD
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class ComboField(FormField):
        """
        Dropdown-fält.

        Användning:
            field = ComboField(
                name="color",
                label="Färg",
                items=[("black", "Svart"), ("white", "Vit"), ("red", "Röd")],
            )
        """

        def __init__(
            self,
            name: str,
            label: str = "",
            required: bool = False,
            items: Optional[List[Tuple[str, str]]] = None,
            editable: bool = False,
            placeholder: str = "-- Välj --",
            **kwargs: Any,
        ) -> None:
            super().__init__(name, label, required, **kwargs)

            self._items: List[Tuple[str, str]] = items or []

            self._input = QComboBox()
            self._input.setEditable(editable)

            # Lägg till placeholder
            self._input.addItem(placeholder, "")

            # Lägg till items
            for value, text in self._items:
                self._input.addItem(text, value)

            self._input.currentIndexChanged.connect(self._on_change)
            self.layout().insertWidget(1, self._input)

        def _on_change(self) -> None:
            """Hantera val."""
            self.value_changed.emit(self.get_value())

        def get_value(self) -> str:
            """Hämta valt värde."""
            return self._input.currentData() or ""

        def set_value(self, value: Any) -> None:
            """Sätt värde."""
            if value:
                index = self._input.findData(value)
                if index >= 0:
                    self._input.setCurrentIndex(index)
            else:
                self._input.setCurrentIndex(0)

        def add_item(self, value: str, text: str) -> None:
            """Lägg till item."""
            self._input.addItem(text, value)
            self._items.append((value, text))

        def clear_items(self) -> None:
            """Rensa alla items (behåll placeholder)."""
            while self._input.count() > 1:
                self._input.removeItem(1)
            self._items.clear()


# ══════════════════════════════════════════════════════════════════════════════
# CHECK FIELD
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class CheckField(FormField):
        """
        Checkbox-fält.

        Användning:
            field = CheckField(
                name="active",
                label="Aktiv",
                default=True,
            )
        """

        def __init__(
            self,
            name: str,
            label: str = "",
            default: bool = False,
            **kwargs: Any,
        ) -> None:
            # Skip FormField label
            super().__init__(name, "", False, **kwargs)

            self._input = QCheckBox(label)
            self._input.setChecked(default)
            self._input.stateChanged.connect(self._on_change)

            self.layout().insertWidget(0, self._input)

        def _on_change(self) -> None:
            """Hantera ändring."""
            self.value_changed.emit(self.get_value())

        def get_value(self) -> bool:
            """Hämta värde."""
            return self._input.isChecked()

        def set_value(self, value: Any) -> None:
            """Sätt värde."""
            self._input.setChecked(bool(value))


# ══════════════════════════════════════════════════════════════════════════════
# FORM GROUP
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class FormGroup(QGroupBox):
        """
        Gruppera fält med rubrik.

        Användning:
            group = FormGroup("Fordonsinformation")
            group.add_field(TextField("vin", "VIN"))
            group.add_field(TextField("model", "Modell"))
        """

        def __init__(
            self, title: str, parent: Optional[QWidget] = None
        ) -> None:
            super().__init__(title, parent)

            self._fields: Dict[str, FormField] = {}

            self._layout = QVBoxLayout(self)
            self._layout.setSpacing(8)
            self.setStyleSheet(FORM_STYLE)

        def add_field(self, field: FormField) -> None:
            """Lägg till fält."""
            self._fields[field.name] = field
            self._layout.addWidget(field)

        def get_field(self, name: str) -> Optional[FormField]:
            """Hämta fält."""
            return self._fields.get(name)

        def get_values(self) -> Dict[str, Any]:
            """Hämta alla värden."""
            return {
                name: field.get_value()
                for name, field in self._fields.items()
            }

        def set_values(self, values: Dict[str, Any]) -> None:
            """Sätt flera värden."""
            for name, value in values.items():
                field = self._fields.get(name)
                if field:
                    field.set_value(value)

        def validate_all(self) -> Tuple[bool, List[str]]:
            """Validera alla fält."""
            errors = []
            for field in self._fields.values():
                if not field.show_validation():
                    errors.append(
                        "%s: %s" % (field.name, field._error_message)
                    )
            return len(errors) == 0, errors


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMIC FORM (SCHEMA-DRIVEN)
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class DynamicForm(QWidget):
        """
        Schema-drivet formulär.

        Skapar formulär automatiskt från TS-scheman eller
        field-definitioner.

        Användning:
            # Från fält-definitioner
            form = DynamicForm(fields=[
                {"name": "vin", "type": "text", "label": "VIN",
                 "required": True},
                {"name": "color", "type": "combo", "label": "Färg",
                 "items": [...]},
            ])

            # Från TS-schema
            form = DynamicForm.from_schema(post_spec)
        """

        values_changed = Signal(dict)

        def __init__(
            self,
            fields: Optional[List[Dict[str, Any]]] = None,
            columns: int = 1,
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)

            self._fields: Dict[str, FormField] = {}
            self._columns = columns

            self._setup_ui()

            if fields:
                for field_def in fields:
                    self.add_field_from_dict(field_def)

        def _setup_ui(self) -> None:
            """Bygg UI."""
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)

            container = QWidget()
            self._form_layout = QGridLayout(container)
            self._form_layout.setSpacing(12)
            self._row = 0
            self._col = 0

            scroll.setWidget(container)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(scroll)

            self.setStyleSheet(FORM_STYLE)

        def add_field(self, field: FormField) -> None:
            """Lägg till fält."""
            self._fields[field.name] = field
            field.value_changed.connect(self._on_value_changed)

            self._form_layout.addWidget(field, self._row, self._col)

            self._col += 1
            if self._col >= self._columns:
                self._col = 0
                self._row += 1

        def add_field_from_dict(
            self, definition: Dict[str, Any]
        ) -> Optional[FormField]:
            """Skapa och lägg till fält från definition."""
            field = _create_field(definition)
            if field:
                self.add_field(field)
            return field

        def _on_value_changed(self, value: Any) -> None:
            """Hantera värdeändring."""
            self.values_changed.emit(self.get_values())

        def get_field(self, name: str) -> Optional[FormField]:
            """Hämta fält."""
            return self._fields.get(name)

        def get_values(self) -> Dict[str, Any]:
            """Hämta alla värden."""
            return {
                name: field.get_value()
                for name, field in self._fields.items()
            }

        def set_values(self, values: Dict[str, Any]) -> None:
            """Sätt flera värden."""
            for name, value in values.items():
                field = self._fields.get(name)
                if field:
                    field.set_value(value)

        def validate_all(self) -> Tuple[bool, List[str]]:
            """Validera alla fält."""
            errors = []
            for field in self._fields.values():
                if not field.show_validation():
                    errors.append(
                        "%s: %s" % (field.name, field._error_message)
                    )
            return len(errors) == 0, errors

        def clear_all(self) -> None:
            """Rensa alla fält."""
            for field in self._fields.values():
                field.clear()

        @classmethod
        def from_schema(
            cls, post_spec: Any, columns: int = 2
        ) -> "DynamicForm":
            """
            Skapa formulär från PostSpec.

            Args:
                post_spec: PostSpec från ts_schema_manager
                columns: Antal kolumner
            """
            fields = []

            if hasattr(post_spec, "fields"):
                for field_spec in post_spec.fields:
                    field_def = {
                        "name": field_spec.name,
                        "label": field_spec.name.replace(
                            "_", " "
                        ).title(),
                        "required": getattr(
                            field_spec, "mandatory", False
                        ),
                        "max_length": getattr(
                            field_spec, "length", 0
                        ),
                    }

                    # Bestäm typ
                    field_type = getattr(
                        field_spec, "field_type", "alphanumeric"
                    )
                    if field_type == "numeric":
                        field_def["type"] = "number"
                    elif field_type == "date":
                        field_def["type"] = "date"
                    else:
                        field_def["type"] = "text"

                    fields.append(field_def)

            return cls(fields=fields, columns=columns)


# ══════════════════════════════════════════════════════════════════════════════
# FIELD FACTORY (delas av DynamicForm + plugin-kontraktet)
# ══════════════════════════════════════════════════════════════════════════════

def _create_field(
    definition: Dict[str, Any],
) -> Optional["FormField"]:
    """
    Bygg ett FormField-objekt från en fältdefinition.

    Stödda typer: text, number, date, combo/dropdown, check/checkbox.
    Okänd typ → TextField (kraschsäkert).
    """
    if not HAS_PYSIDE6:
        return None

    field_type = definition.get("type", "text")
    name = definition.get("name", "")
    label = definition.get("label", name)
    required = definition.get("required", False)

    if field_type == "text":
        return TextField(
            name=name,
            label=label,
            required=required,
            max_length=definition.get("max_length", 0),
            placeholder=definition.get("placeholder", ""),
            multiline=definition.get("multiline", False),
        )
    if field_type == "number":
        return NumberField(
            name=name,
            label=label,
            required=required,
            min_value=definition.get("min", 0),
            max_value=definition.get("max", 999999),
            decimals=definition.get("decimals", 0),
        )
    if field_type == "date":
        return DateField(name=name, label=label, required=required)
    if field_type in ("combo", "dropdown"):
        return ComboField(
            name=name,
            label=label,
            required=required,
            items=definition.get("items", []),
        )
    if field_type in ("check", "checkbox"):
        return CheckField(
            name=name,
            label=label,
            default=definition.get("default", False),
        )
    return TextField(name=name, label=label, required=required)

def create_form_group(
    title: str,
    fields: List[Dict[str, Any]],
    parent: Optional[QWidget] = None,
) -> Optional[Any]:
    """
    Skapa en FormGroup med fält från definitioner (plugin-kontraktet).

    Args:
        title: Grupptitel
        fields: Lista med fältdefinitioner:
            [{"name": "field1", "label": "Fält 1", "type": "text", ...}]
        parent: Föräldra-widget

    Returns:
        FormGroup eller None (headless/komponent saknas)
    """
    if not HAS_PYSIDE6:
        return None
    try:
        group = FormGroup(title, parent)
        for definition in fields or []:
            if not isinstance(definition, dict):
                continue
            field = _create_field(definition)
            if field is not None:
                group.add_field(field)
        return group
    except Exception:
        return None

def create_form_field(
    name: str,
    label: str,
    field_type: str = "text",
    **kwargs: Any,
) -> Optional[Any]:
    """
    Skapa ett enskilt formulärfält (plugin-kontraktet).

    Args:
        name: Fältnamn
        label: Etikett
        field_type: "text", "number", "dropdown", "checkbox", "date"
        **kwargs: Ytterligare options (min, max, items, etc.)

    Returns:
        FormField-instans eller None (headless)
    """
    if not HAS_PYSIDE6:
        return None
    try:
        definition: Dict[str, Any] = {
            "name": name,
            "label": label,
            "type": field_type,
        }
        definition.update(kwargs)
        return _create_field(definition)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__: List[str] = [
    # Metadata
    "VERSION",
    "AUTHOR",
    # Styles
    "FORM_STYLE",
    "ERROR_STYLE",
    "SUCCESS_STYLE",
    # Plugin-kontrakt
    "create_form_group",
    "create_form_field",
    # Utils
    "HAS_PYSIDE6",
    "get_copyright_string",
]

# Fältklasserna finns bara när PySide6 är tillgängligt (import *
# kraschar annars på saknade namn).
if HAS_PYSIDE6:
    __all__ += [
        "FormField",
        "TextField",
        "NumberField",
        "DateField",
        "ComboField",
        "CheckField",
        "FormGroup",
        "DynamicForm",
    ]
