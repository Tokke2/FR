# plugins/ts_schema_manager/widget.py
# -*- coding: utf-8 -*-
"""
TS Schema Manager Widget v1.0.1

Administrativ GUI-widget för ts_schema_manager (source of truth).
Skapas via Plugin.create_widget(parent=None) — registreras INTE
automatiskt som flik (main_gui/annan plugin integrerar den).

Tabs:
    1. Schema        - posttyper, fält, täckning/luckor/överlapp
    2. Diff          - jämförelse mellan versioner
    3. Preview       - format_record + validering (Latin-1)
    4. Backup & hist - backuper, export/import, historik
    5. Diagnostik    - basdiagnostik, metadata, statistik, rapport

Ändringar v1.0.1 (Session 11 — granskad, spec v1.6 förbättringsregeln):
    - FIX: QObjectLike -> QObject (importerad från QtCore) i
      PostTypesTableModel/FieldsTableModel/HistoryTableModel-
      konstruktorerna (QObjectLike finns inte — fungerade endast via
      from __future__ import annotations).
    - FIX: _export_diff_report skriver nu ATOMISKT (mkstemp ->
      os.fdopen -> fsync -> os.replace) i stället för Path.write_text.
    - _get_copyright_string använder AUTHOR-konstanten (ej hårdkodat
      namn) med lazy-format.
    - Övrig logik OFÖRÄNDRAD (QTableView/QAbstractTableModel,
      ScrollPerPixel, setWordWrap, setObjectName, kraschsäkra
      callables).

OBS (storlek): filen överstiger 1800 rader — enligt spec Sektion A
ska hjälpfil föreslås. Föreslagen uppdelning vid behov:
    widget_models.py (3 tabellmodeller) + widget_dialogs.py
    (3 dialoger) + widget.py (huvudwidget) — samma struktur som
    ts_schema_manager-dokumentationen (X/Y).
"""
from __future__ import annotations

import copy
import inspect
import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QSortFilterProxyModel, Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .constants import TS_POST_LENGTH, validate_latin1 as constants_validate_latin1
from .models import FieldSpec as ModelFieldSpec
from .models import FieldType, PostSpec as ModelPostSpec
from .models import create_empty_post_spec, create_minimal_spec
from .schema_diff import get_schema_diff

VERSION = "1.0.1"
AUTHOR = "Rickard Längkvist"


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


_log = _get_logger()


def _get_copyright_string() -> str:
    return "Copyright © {} {}".format(datetime.now().year, AUTHOR)


def _set_bold(widget: QWidget) -> None:
    try:
        font = widget.font()
        font.setBold(True)
        widget.setFont(font)
    except Exception:
        _log.exception("Kunde inte sätta fet stil på widget.")


def _mono_font() -> QFont:
    try:
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    except Exception:
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        return font


def _normalize_post_type(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if text.startswith("PT"):
        return text
    if text.isdigit():
        return f"PT{text.zfill(2)}" if len(text) <= 2 else f"PT{text}"
    return text


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _bool_text(value: bool) -> str:
    return "Ja" if bool(value) else "Nej"


def _obj_to_dict(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return copy.deepcopy(obj)
    try:
        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            data = obj.to_dict()
            if isinstance(data, dict):
                return copy.deepcopy(data)
    except Exception:
        _log.exception("to_dict() misslyckades för objekt: %r", obj)
    try:
        if is_dataclass(obj):
            data = asdict(obj)
            if isinstance(data, dict):
                return copy.deepcopy(data)
    except Exception:
        _log.exception("asdict() misslyckades för objekt: %r", obj)
    try:
        if hasattr(obj, "__dict__"):
            return {
                key: copy.deepcopy(value)
                for key, value in vars(obj).items()
                if not key.startswith("_")
            }
    except Exception:
        _log.exception("__dict__-avläsning misslyckades för objekt: %r", obj)
    return {}


def _clone_object(obj: Any) -> Any:
    if obj is None:
        return None
    try:
        if hasattr(obj, "clone") and callable(obj.clone):
            return obj.clone()
    except Exception:
        _log.exception("clone() misslyckades för objekt: %r", obj)
    try:
        cls = type(obj)
        data = _obj_to_dict(obj)
        if hasattr(cls, "from_dict") and callable(cls.from_dict):
            return cls.from_dict(data)
    except Exception:
        _log.exception("from_dict() misslyckades för klon av objekt: %r", obj)
    try:
        return copy.deepcopy(obj)
    except Exception:
        _log.exception("deepcopy() misslyckades för objekt: %r", obj)
    return obj


def _field_required(field: Any) -> bool:
    if hasattr(field, "required"):
        try:
            return bool(getattr(field, "required"))
        except Exception:
            pass
    if hasattr(field, "mandatory"):
        try:
            return bool(getattr(field, "mandatory"))
        except Exception:
            pass
    return False


def _field_position(field: Any) -> int:
    return _safe_int(getattr(field, "position", 0), 0)


def _field_length(field: Any) -> int:
    return _safe_int(getattr(field, "length", 0), 0)


def _field_end(field: Any) -> int:
    try:
        return _safe_int(getattr(field, "end_position"), 0)
    except Exception:
        pos = _field_position(field)
        length = _field_length(field)
        if pos <= 0 or length <= 0:
            return 0
        return pos + length - 1


def _field_type_text(field: Any) -> str:
    value = getattr(field, "field_type", "")
    try:
        if isinstance(value, FieldType):
            return str(value.value)
    except Exception:
        pass
    try:
        if hasattr(value, "value"):
            return str(value.value)
    except Exception:
        pass
    return str(value or "")


def _iter_fields(spec: Any) -> List[Any]:
    try:
        fields = list(getattr(spec, "fields", []) or [])
    except Exception:
        fields = []
    return sorted(fields, key=_field_position)


def _spec_length(spec: Any) -> int:
    return _safe_int(getattr(spec, "total_length", TS_POST_LENGTH), TS_POST_LENGTH)


def _spec_name(spec: Any) -> str:
    return str(getattr(spec, "name", "") or "")


def _spec_post_type(spec: Any) -> str:
    return _normalize_post_type(getattr(spec, "post_type", "") or "")


def _compute_coverage(spec: Any) -> float:
    total_length = max(1, _spec_length(spec))
    covered_positions: set[int] = set()
    for field in _iter_fields(spec):
        start = max(1, _field_position(field))
        end = min(total_length, _field_end(field))
        if end >= start:
            covered_positions.update(range(start, end + 1))
    return round((len(covered_positions) / total_length) * 100.0, 2)


def _get_required_field_count(spec: Any) -> int:
    return sum(1 for field in _iter_fields(spec) if _field_required(field))


def _try_get_gaps(spec: Any) -> List[Any]:
    try:
        if hasattr(spec, "get_gaps") and callable(spec.get_gaps):
            return list(spec.get_gaps() or [])
    except Exception:
        _log.exception("get_gaps() misslyckades.")
    try:
        if hasattr(spec, "find_gaps") and callable(spec.find_gaps):
            return list(spec.find_gaps() or [])
    except Exception:
        _log.exception("find_gaps() misslyckades.")
    return []


def _try_get_overlaps(spec: Any) -> List[Any]:
    try:
        if hasattr(spec, "get_overlaps") and callable(spec.get_overlaps):
            return list(spec.get_overlaps() or [])
    except Exception:
        _log.exception("get_overlaps() misslyckades.")
    try:
        if hasattr(spec, "find_overlaps") and callable(spec.find_overlaps):
            return list(spec.find_overlaps() or [])
    except Exception:
        _log.exception("find_overlaps() misslyckades.")
    return []


def _format_gap_item(item: Any) -> str:
    if isinstance(item, dict):
        start = item.get("start") or item.get("from") or item.get("position")
        end = item.get("end") or item.get("to")
        length = item.get("length")
        parts = []
        if start is not None and end is not None:
            parts.append(f"{start}-{end}")
        if length is not None:
            parts.append(f"längd={length}")
        if not parts:
            parts.append(json.dumps(item, ensure_ascii=False))
        return ", ".join(parts)
    if isinstance(item, (list, tuple)):
        if len(item) == 2:
            return f"{item[0]}-{item[1]}"
        if len(item) >= 3:
            return f"{item[0]}-{item[1]}, längd={item[2]}"
    return str(item)


def _format_overlap_item(item: Any) -> str:
    if isinstance(item, dict):
        fields = item.get("fields")
        start = item.get("start")
        end = item.get("end")
        if fields and isinstance(fields, (list, tuple)):
            field_text = " ↔ ".join(str(x) for x in fields)
            if start is not None and end is not None:
                return f"{field_text} ({start}-{end})"
            return field_text
        return json.dumps(item, ensure_ascii=False)
    if isinstance(item, (list, tuple)):
        if len(item) == 2:
            return f"{item[0]} ↔ {item[1]}"
        if len(item) >= 4:
            return f"{item[0]} ↔ {item[1]} ({item[2]}-{item[3]})"
    return str(item)


def _pretty_json(data: Any) -> str:
    try:
        return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)
    except Exception:
        return str(data)


def _format_result_text(result: Any) -> str:
    if result is None:
        return "Inget resultat."
    if isinstance(result, bool):
        return "OK" if result else "Inte OK"
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return _pretty_json(result)
    if isinstance(result, (list, tuple, set)):
        return "\n".join(str(x) for x in result)
    return str(result)


def _build_field_from_dict(
    field_class_hint: Optional[type],
    data: Dict[str, Any],
) -> Any:
    payload = dict(data)
    if "required" in payload and "mandatory" not in payload:
        payload["mandatory"] = bool(payload["required"])
    if "mandatory" in payload and "required" not in payload:
        payload["required"] = bool(payload["mandatory"])

    for cls in (field_class_hint, ModelFieldSpec):
        if cls is None:
            continue
        try:
            if hasattr(cls, "from_dict") and callable(cls.from_dict):
                return cls.from_dict(payload)
        except Exception:
            _log.exception("from_dict() misslyckades för fältklass %r.", cls)

    try:
        return ModelFieldSpec.from_dict(payload)
    except Exception:
        _log.exception("Fallback via ModelFieldSpec.from_dict() misslyckades.")
        raise


def _build_spec_from_dict(
    spec_class_hint: Optional[type],
    data: Dict[str, Any],
) -> Any:
    for cls in (spec_class_hint, ModelPostSpec):
        if cls is None:
            continue
        try:
            if hasattr(cls, "from_dict") and callable(cls.from_dict):
                return cls.from_dict(data)
        except Exception:
            _log.exception("from_dict() misslyckades för specklass %r.", cls)
    try:
        return ModelPostSpec.from_dict(data)
    except Exception:
        _log.exception("Fallback via ModelPostSpec.from_dict() misslyckades.")
        raise


def _supports_arg(func: Callable[..., Any], arg_name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return arg_name in signature.parameters


def _invoke_callable(
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        signature = inspect.signature(func)
        has_var_kw = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if not has_var_kw:
            kwargs = {k: v for k, v in kwargs.items() if k in signature.parameters}
    except (TypeError, ValueError):
        pass

    try:
        return func(*args, **kwargs)
    except TypeError:
        if kwargs:
            try:
                return func(*args)
            except Exception:
                _log.exception("Anrop misslyckades för %r.", func)
                raise
        _log.exception("Anrop misslyckades för %r.", func)
        raise
    except Exception:
        _log.exception("Anrop misslyckades för %r.", func)
        raise


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """
    Skriv text atomiskt: mkstemp -> os.fdopen -> flush -> fsync ->
    os.replace (spec v1.4 / Sektion B punkt 16).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".{}_".format(path.stem),
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class PostTypesTableModel(QAbstractTableModel):
    HEADERS = ["Posttyp", "Namn", "Fält", "Obl.", "Täckning %", "Längd"]

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def get_row(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return section + 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.get_row(index.row())
        if row is None:
            return None

        if role == Qt.DisplayRole:
            values = [
                row.get("post_type", ""),
                row.get("name", ""),
                row.get("field_count", 0),
                row.get("required_count", 0),
                f"{row.get('coverage', 0.0):.2f}",
                row.get("total_length", 0),
            ]
            if 0 <= index.column() < len(values):
                return values[index.column()]

        if role == Qt.TextAlignmentRole and index.column() >= 2:
            return int(Qt.AlignCenter)

        if role == Qt.ToolTipRole:
            return (
                f"Posttyp: {row.get('post_type', '')}\n"
                f"Namn: {row.get('name', '')}\n"
                f"Fält: {row.get('field_count', 0)}\n"
                f"Obligatoriska: {row.get('required_count', 0)}\n"
                f"Täckning: {row.get('coverage', 0.0):.2f}%\n"
                f"Längd: {row.get('total_length', 0)}"
            )

        return None


class FieldsTableModel(QAbstractTableModel):
    HEADERS = ["Namn", "Pos", "Längd", "Slut", "Typ", "Obl.", "Beskrivning"]

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._fields: List[Any] = []

    def set_fields(self, fields: List[Any]) -> None:
        self.beginResetModel()
        self._fields = list(fields)
        self.endResetModel()

    def get_field(self, row: int) -> Optional[Any]:
        if 0 <= row < len(self._fields):
            return self._fields[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._fields)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return section + 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        field = self.get_field(index.row())
        if field is None:
            return None

        if role == Qt.DisplayRole:
            values = [
                getattr(field, "name", ""),
                _field_position(field),
                _field_length(field),
                _field_end(field),
                _field_type_text(field),
                _bool_text(_field_required(field)),
                getattr(field, "description", "") or "",
            ]
            if 0 <= index.column() < len(values):
                return values[index.column()]

        if role == Qt.TextAlignmentRole and index.column() in {1, 2, 3, 5}:
            return int(Qt.AlignCenter)

        if role == Qt.ToolTipRole:
            data = _obj_to_dict(field)
            return _pretty_json(data)

        return None


class HistoryTableModel(QAbstractTableModel):
    HEADERS = ["Tid", "Åtgärd", "Version", "Detaljer"]

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def get_row(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return section + 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.get_row(index.row())
        if row is None:
            return None

        details = row.get("details", {})
        details_text = details if isinstance(details, str) else _pretty_json(details)

        if role == Qt.DisplayRole:
            values = [
                row.get("timestamp", ""),
                row.get("action", ""),
                row.get("version", ""),
                details_text.replace("\n", " ")[:180],
            ]
            if 0 <= index.column() < len(values):
                return values[index.column()]

        if role == Qt.ToolTipRole:
            return (
                f"Tid: {row.get('timestamp', '')}\n"
                f"Åtgärd: {row.get('action', '')}\n"
                f"Version: {row.get('version', '')}\n\n"
                f"{details_text}"
            )

        return None


class VersionDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        existing_data: Optional[Dict[str, Any]] = None,
        title: str = "Version",
        version_readonly: bool = False,
    ) -> None:
        super().__init__(parent)
        self._existing_data = existing_data or {}
        self.setWindowTitle(title)
        self.setObjectName("SchemaVersionDialog")
        self.resize(520, 180)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.version_edit = QLineEdit(str(self._existing_data.get("version", "") or ""))
        self.version_edit.setObjectName("VersionEdit")
        self.version_edit.setReadOnly(version_readonly)

        self.source_edit = QLineEdit(str(self._existing_data.get("source_file", "") or ""))
        self.source_edit.setObjectName("VersionSourceEdit")

        self.description_edit = QLineEdit(
            str(self._existing_data.get("description", "") or "")
        )
        self.description_edit.setObjectName("VersionDescriptionEdit")

        form.addRow("Version:", self.version_edit)
        form.addRow("Källa:", self.source_edit)
        form.addRow("Beskrivning:", self.description_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        version = self.version_edit.text().strip()
        if not version:
            QMessageBox.warning(self, "Validering", "Version måste anges.")
            self.version_edit.setFocus()
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        return {
            "version": self.version_edit.text().strip(),
            "source_file": self.source_edit.text().strip(),
            "description": self.description_edit.text().strip(),
        }


class PostTypeDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        existing_data: Optional[Dict[str, Any]] = None,
        title: str = "Posttyp",
    ) -> None:
        super().__init__(parent)
        self._existing_data = existing_data or {}
        self.setWindowTitle(title)
        self.setObjectName("SchemaPostTypeDialog")
        self.resize(520, 220)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.post_type_edit = QLineEdit(
            _normalize_post_type(self._existing_data.get("post_type", ""))
        )
        self.post_type_edit.setObjectName("PostTypeEdit")

        self.name_edit = QLineEdit(str(self._existing_data.get("name", "") or ""))
        self.name_edit.setObjectName("PostTypeNameEdit")

        self.length_spin = QSpinBox()
        self.length_spin.setObjectName("PostTypeLengthSpin")
        self.length_spin.setRange(1, TS_POST_LENGTH)
        self.length_spin.setValue(
            _safe_int(self._existing_data.get("total_length", TS_POST_LENGTH), TS_POST_LENGTH)
        )

        form.addRow("Posttyp:", self.post_type_edit)
        form.addRow("Namn:", self.name_edit)
        form.addRow("Total längd:", self.length_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        post_type = _normalize_post_type(self.post_type_edit.text())
        if not post_type:
            QMessageBox.warning(self, "Validering", "Posttyp måste anges.")
            self.post_type_edit.setFocus()
            return
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validering", "Namn måste anges.")
            self.name_edit.setFocus()
            return
        self.post_type_edit.setText(post_type)
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        return {
            "post_type": _normalize_post_type(self.post_type_edit.text()),
            "name": self.name_edit.text().strip(),
            "total_length": int(self.length_spin.value()),
        }


class FieldDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        existing_data: Optional[Dict[str, Any]] = None,
        title: str = "Fält",
    ) -> None:
        super().__init__(parent)
        self._existing_data = existing_data or {}
        self.setWindowTitle(title)
        self.setObjectName("SchemaFieldDialog")
        self.resize(560, 280)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit(str(self._existing_data.get("name", "") or ""))
        self.name_edit.setObjectName("FieldNameEdit")

        self.position_spin = QSpinBox()
        self.position_spin.setObjectName("FieldPositionSpin")
        self.position_spin.setRange(1, TS_POST_LENGTH)
        self.position_spin.setValue(_safe_int(self._existing_data.get("position", 1), 1))

        self.length_spin = QSpinBox()
        self.length_spin.setObjectName("FieldLengthSpin")
        self.length_spin.setRange(1, TS_POST_LENGTH)
        self.length_spin.setValue(_safe_int(self._existing_data.get("length", 1), 1))

        self.type_combo = QComboBox()
        self.type_combo.setObjectName("FieldTypeCombo")
        for field_type in FieldType:
            self.type_combo.addItem(str(field_type.value), str(field_type.value))

        existing_type = str(self._existing_data.get("field_type", "") or "")
        if hasattr(self._existing_data.get("field_type"), "value"):
            existing_type = str(self._existing_data["field_type"].value)
        idx = self.type_combo.findData(existing_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        required = bool(
            self._existing_data.get(
                "required",
                self._existing_data.get("mandatory", False),
            )
        )
        self.required_check = QCheckBox("Obligatoriskt fält")
        self.required_check.setObjectName("FieldRequiredCheck")
        self.required_check.setChecked(required)

        self.description_edit = QLineEdit(str(self._existing_data.get("description", "") or ""))
        self.description_edit.setObjectName("FieldDescriptionEdit")

        form.addRow("Fältnamn:", self.name_edit)
        form.addRow("Position:", self.position_spin)
        form.addRow("Längd:", self.length_spin)
        form.addRow("Typ:", self.type_combo)
        form.addRow("", self.required_check)
        form.addRow("Beskrivning:", self.description_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validering", "Fältnamn måste anges.")
            self.name_edit.setFocus()
            return
        if self.position_spin.value() < 1:
            QMessageBox.warning(self, "Validering", "Position måste vara minst 1.")
            self.position_spin.setFocus()
            return
        if self.length_spin.value() < 1:
            QMessageBox.warning(self, "Validering", "Längd måste vara minst 1.")
            self.length_spin.setFocus()
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        required = bool(self.required_check.isChecked())
        return {
            "name": self.name_edit.text().strip(),
            "position": int(self.position_spin.value()),
            "length": int(self.length_spin.value()),
            "field_type": str(self.type_combo.currentData() or self.type_combo.currentText()),
            "required": required,
            "mandatory": required,
            "description": self.description_edit.text().strip(),
        }


class TSSchemaManagerWidget(QWidget):
    def __init__(self, plugin: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.schema_diff = get_schema_diff()

        self._versions: List[str] = []
        self._current_version: str = ""
        self._current_post_type: str = ""
        self._schemas_by_post_type: Dict[str, Any] = {}
        self._backups: List[str] = []
        self._history_rows: List[Dict[str, Any]] = []

        self.setObjectName("TSSchemaManagerWidget")
        self._setup_ui()
        self.refresh()

    # -----------------------------------------------------------------
    # UI setup
    # -----------------------------------------------------------------
    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        header_layout = QHBoxLayout()

        self.title_label = QLabel("TS Schema Manager")
        self.title_label.setObjectName("PageTitle")
        _set_bold(self.title_label)

        self.status_label = QLabel("Klar.")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)

        self.count_label = QLabel("0 versioner • 0 posttyper • 0 fält")
        self.count_label.setObjectName("CountLabel")
        _set_bold(self.count_label)

        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.status_label, 2)
        header_layout.addWidget(self.count_label, 0)
        root_layout.addLayout(header_layout)

        root_layout.addWidget(self._build_version_group())

        self.tabs = QTabWidget()
        self.tabs.setObjectName("SchemaMainTabs")
        root_layout.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_schema_tab(), "Schema")
        self.tabs.addTab(self._build_diff_tab(), "Diff")
        self.tabs.addTab(self._build_preview_tab(), "Preview")
        self.tabs.addTab(self._build_backup_tab(), "Backup & historik")
        self.tabs.addTab(self._build_diagnostics_tab(), "Diagnostik")

    def _build_version_group(self) -> QWidget:
        group = QGroupBox("Versioner")
        group.setObjectName("ActionGroup")
        layout = QGridLayout(group)

        version_label = QLabel("Aktiv version:")
        version_label.setObjectName("StatusLabel")
        _set_bold(version_label)

        self.version_combo = QComboBox()
        self.version_combo.setObjectName("VersionCombo")
        self.version_combo.currentTextChanged.connect(self._on_version_combo_changed)

        self.activate_button = QPushButton("Aktivera")
        self.activate_button.setObjectName("PrimaryButton")
        _set_bold(self.activate_button)
        self.activate_button.clicked.connect(self._activate_selected_version)

        self.refresh_button = QPushButton("Uppdatera")
        self.refresh_button.setObjectName("SecondaryButton")
        _set_bold(self.refresh_button)
        self.refresh_button.clicked.connect(self.refresh)

        self.new_version_button = QPushButton("Ny version")
        self.new_version_button.setObjectName("SuccessButton")
        _set_bold(self.new_version_button)
        self.new_version_button.clicked.connect(self._create_version)

        self.duplicate_version_button = QPushButton("Duplicera")
        self.duplicate_version_button.setObjectName("SecondaryButton")
        _set_bold(self.duplicate_version_button)
        self.duplicate_version_button.clicked.connect(self._duplicate_version)

        self.rename_version_button = QPushButton("Byt namn")
        self.rename_version_button.setObjectName("SecondaryButton")
        _set_bold(self.rename_version_button)
        self.rename_version_button.clicked.connect(self._rename_version)

        self.delete_version_button = QPushButton("Ta bort")
        self.delete_version_button.setObjectName("DangerButton")
        _set_bold(self.delete_version_button)
        self.delete_version_button.clicked.connect(self._delete_version)

        layout.addWidget(version_label, 0, 0)
        layout.addWidget(self.version_combo, 0, 1)
        layout.addWidget(self.activate_button, 0, 2)
        layout.addWidget(self.refresh_button, 0, 3)
        layout.addWidget(self.new_version_button, 1, 0)
        layout.addWidget(self.duplicate_version_button, 1, 1)
        layout.addWidget(self.rename_version_button, 1, 2)
        layout.addWidget(self.delete_version_button, 1, 3)
        layout.setColumnStretch(1, 1)

        return group

    def _build_schema_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Left panel - post types
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        post_group = QGroupBox("Posttyper")
        post_group.setObjectName("SearchGroup")
        post_layout = QVBoxLayout(post_group)

        self.post_type_search = QLineEdit()
        self.post_type_search.setPlaceholderText("Sök posttyp...")
        self.post_type_search.setObjectName("PostTypeSearchEdit")
        self.post_type_search.textChanged.connect(self._on_post_type_search)

        self.post_types_model = PostTypesTableModel(self)
        self.post_types_proxy = QSortFilterProxyModel(self)
        self.post_types_proxy.setSourceModel(self.post_types_model)
        self.post_types_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.post_types_proxy.setFilterKeyColumn(-1)

        self.post_types_table = QTableView()
        self.post_types_table.setObjectName("PostTypesTable")
        self.post_types_table.setModel(self.post_types_proxy)
        self.post_types_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.post_types_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.post_types_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.post_types_table.setAlternatingRowColors(True)
        self.post_types_table.setSortingEnabled(True)
        self.post_types_table.setWordWrap(True)
        self.post_types_table.verticalHeader().setVisible(False)
        self.post_types_table.horizontalHeader().setStretchLastSection(True)
        self.post_types_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.post_types_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.post_types_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.post_types_table.doubleClicked.connect(self._edit_post_type)

        selection_model = self.post_types_table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(self._on_post_type_selection_changed)

        post_buttons = QHBoxLayout()
        self.add_post_type_button = QPushButton("Ny")
        self.add_post_type_button.setObjectName("SuccessButton")
        _set_bold(self.add_post_type_button)
        self.add_post_type_button.clicked.connect(self._add_post_type)

        self.edit_post_type_button = QPushButton("Redigera")
        self.edit_post_type_button.setObjectName("SecondaryButton")
        _set_bold(self.edit_post_type_button)
        self.edit_post_type_button.clicked.connect(self._edit_post_type)

        self.clone_post_type_button = QPushButton("Klona")
        self.clone_post_type_button.setObjectName("SecondaryButton")
        _set_bold(self.clone_post_type_button)
        self.clone_post_type_button.clicked.connect(self._clone_post_type)

        self.delete_post_type_button = QPushButton("Ta bort")
        self.delete_post_type_button.setObjectName("DangerButton")
        _set_bold(self.delete_post_type_button)
        self.delete_post_type_button.clicked.connect(self._delete_post_type)

        post_buttons.addWidget(self.add_post_type_button)
        post_buttons.addWidget(self.edit_post_type_button)
        post_buttons.addWidget(self.clone_post_type_button)
        post_buttons.addWidget(self.delete_post_type_button)

        post_layout.addWidget(self.post_type_search)
        post_layout.addWidget(self.post_types_table, 1)
        post_layout.addLayout(post_buttons)

        left_layout.addWidget(post_group)
        splitter.addWidget(left_panel)

        # Right panel - details + fields + structure
        right_splitter = QSplitter(Qt.Vertical)

        details_group = QGroupBox("Vald posttyp")
        details_group.setObjectName("ActionGroup")
        details_layout = QGridLayout(details_group)

        self.selected_post_type_label = QLabel("—")
        self.selected_post_type_label.setObjectName("CountLabel")
        _set_bold(self.selected_post_type_label)

        self.selected_post_name_label = QLabel("—")
        self.selected_post_name_label.setObjectName("StatusLabel")
        self.selected_post_name_label.setWordWrap(True)

        self.selected_post_meta_label = QLabel("—")
        self.selected_post_meta_label.setObjectName("StatusLabel")
        self.selected_post_meta_label.setWordWrap(True)

        self.schema_summary_text = QPlainTextEdit()
        self.schema_summary_text.setObjectName("SchemaSummaryText")
        self.schema_summary_text.setReadOnly(True)
        self.schema_summary_text.setFont(_mono_font())
        self.schema_summary_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        self.validate_structure_button = QPushButton("Validera struktur")
        self.validate_structure_button.setObjectName("PrimaryButton")
        _set_bold(self.validate_structure_button)
        self.validate_structure_button.clicked.connect(self._validate_current_structure)

        details_layout.addWidget(QLabel("Posttyp:"), 0, 0)
        details_layout.addWidget(self.selected_post_type_label, 0, 1)
        details_layout.addWidget(QLabel("Namn:"), 1, 0)
        details_layout.addWidget(self.selected_post_name_label, 1, 1)
        details_layout.addWidget(QLabel("Info:"), 2, 0)
        details_layout.addWidget(self.selected_post_meta_label, 2, 1)
        details_layout.addWidget(self.schema_summary_text, 3, 0, 1, 2)
        details_layout.addWidget(self.validate_structure_button, 4, 1, 1, 1)

        fields_group = QGroupBox("Fält")
        fields_group.setObjectName("SearchGroup")
        fields_layout = QVBoxLayout(fields_group)

        self.field_search = QLineEdit()
        self.field_search.setPlaceholderText("Sök fält...")
        self.field_search.setObjectName("FieldSearchEdit")
        self.field_search.textChanged.connect(self._on_field_search)

        self.fields_model = FieldsTableModel(self)
        self.fields_proxy = QSortFilterProxyModel(self)
        self.fields_proxy.setSourceModel(self.fields_model)
        self.fields_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.fields_proxy.setFilterKeyColumn(-1)

        self.fields_table = QTableView()
        self.fields_table.setObjectName("FieldsTable")
        self.fields_table.setModel(self.fields_proxy)
        self.fields_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.fields_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.fields_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fields_table.setAlternatingRowColors(True)
        self.fields_table.setSortingEnabled(True)
        self.fields_table.setWordWrap(True)
        self.fields_table.verticalHeader().setVisible(False)
        self.fields_table.horizontalHeader().setStretchLastSection(True)
        self.fields_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.fields_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.fields_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.fields_table.doubleClicked.connect(self._edit_field)

        field_buttons = QHBoxLayout()
        self.add_field_button = QPushButton("Nytt fält")
        self.add_field_button.setObjectName("SuccessButton")
        _set_bold(self.add_field_button)
        self.add_field_button.clicked.connect(self._add_field)

        self.edit_field_button = QPushButton("Redigera")
        self.edit_field_button.setObjectName("SecondaryButton")
        _set_bold(self.edit_field_button)
        self.edit_field_button.clicked.connect(self._edit_field)

        self.delete_field_button = QPushButton("Ta bort")
        self.delete_field_button.setObjectName("DangerButton")
        _set_bold(self.delete_field_button)
        self.delete_field_button.clicked.connect(self._delete_field)

        self.refresh_fields_button = QPushButton("Ladda om")
        self.refresh_fields_button.setObjectName("SecondaryButton")
        _set_bold(self.refresh_fields_button)
        self.refresh_fields_button.clicked.connect(self._refresh_field_panel_only)

        field_buttons.addWidget(self.add_field_button)
        field_buttons.addWidget(self.edit_field_button)
        field_buttons.addWidget(self.delete_field_button)
        field_buttons.addWidget(self.refresh_fields_button)

        fields_layout.addWidget(self.field_search)
        fields_layout.addWidget(self.fields_table, 1)
        fields_layout.addLayout(field_buttons)

        structure_group = QGroupBox("Täckning, luckor och överlapp")
        structure_group.setObjectName("ActionGroup")
        structure_layout = QGridLayout(structure_group)

        self.coverage_progress = QProgressBar()
        self.coverage_progress.setObjectName("CoverageProgress")
        self.coverage_progress.setRange(0, 100)
        self.coverage_progress.setFormat("%p%")

        self.coverage_label = QLabel("Täckning: 0.00%")
        self.coverage_label.setObjectName("CountLabel")
        _set_bold(self.coverage_label)

        self.gaps_text = QPlainTextEdit()
        self.gaps_text.setObjectName("GapsText")
        self.gaps_text.setReadOnly(True)
        self.gaps_text.setFont(_mono_font())
        self.gaps_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        self.overlaps_text = QPlainTextEdit()
        self.overlaps_text.setObjectName("OverlapsText")
        self.overlaps_text.setReadOnly(True)
        self.overlaps_text.setFont(_mono_font())
        self.overlaps_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        structure_layout.addWidget(self.coverage_label, 0, 0, 1, 2)
        structure_layout.addWidget(self.coverage_progress, 1, 0, 1, 2)
        structure_layout.addWidget(QLabel("Luckor:"), 2, 0)
        structure_layout.addWidget(QLabel("Överlapp:"), 2, 1)
        structure_layout.addWidget(self.gaps_text, 3, 0)
        structure_layout.addWidget(self.overlaps_text, 3, 1)

        right_splitter.addWidget(details_group)
        right_splitter.addWidget(fields_group)
        right_splitter.addWidget(structure_group)
        right_splitter.setSizes([220, 420, 240])

        splitter.addWidget(right_splitter)
        splitter.setSizes([340, 900])

        return tab

    def _build_diff_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        options_group = QGroupBox("Jämför versioner")
        options_group.setObjectName("ActionGroup")
        options_layout = QGridLayout(options_group)

        self.diff_version1_combo = QComboBox()
        self.diff_version1_combo.setObjectName("DiffVersion1Combo")

        self.diff_version2_combo = QComboBox()
        self.diff_version2_combo.setObjectName("DiffVersion2Combo")

        self.diff_post_type_combo = QComboBox()
        self.diff_post_type_combo.setObjectName("DiffPostTypeCombo")
        self.diff_post_type_combo.addItem("Alla", "")

        self.compare_button = QPushButton("Jämför")
        self.compare_button.setObjectName("PrimaryButton")
        _set_bold(self.compare_button)
        self.compare_button.clicked.connect(self._compare_versions)

        self.export_diff_button = QPushButton("Spara rapport")
        self.export_diff_button.setObjectName("SecondaryButton")
        _set_bold(self.export_diff_button)
        self.export_diff_button.clicked.connect(self._export_diff_report)

        options_layout.addWidget(QLabel("Version A:"), 0, 0)
        options_layout.addWidget(self.diff_version1_combo, 0, 1)
        options_layout.addWidget(QLabel("Version B:"), 0, 2)
        options_layout.addWidget(self.diff_version2_combo, 0, 3)
        options_layout.addWidget(QLabel("Filtrera posttyp:"), 1, 0)
        options_layout.addWidget(self.diff_post_type_combo, 1, 1)
        options_layout.addWidget(self.compare_button, 1, 2)
        options_layout.addWidget(self.export_diff_button, 1, 3)

        summary_group = QGroupBox("Sammanfattning")
        summary_group.setObjectName("ActionGroup")
        summary_layout = QGridLayout(summary_group)

        self.diff_summary_changed = QLabel("Ändrade: 0")
        self.diff_summary_added = QLabel("Tillagda: 0")
        self.diff_summary_removed = QLabel("Borttagna: 0")
        self.diff_summary_breaking = QLabel("Breaking: 0")

        for label in (
            self.diff_summary_changed,
            self.diff_summary_added,
            self.diff_summary_removed,
            self.diff_summary_breaking,
        ):
            label.setObjectName("CountLabel")
            _set_bold(label)

        summary_layout.addWidget(self.diff_summary_changed, 0, 0)
        summary_layout.addWidget(self.diff_summary_added, 0, 1)
        summary_layout.addWidget(self.diff_summary_removed, 1, 0)
        summary_layout.addWidget(self.diff_summary_breaking, 1, 1)

        self.diff_output_text = QPlainTextEdit()
        self.diff_output_text.setObjectName("DiffOutputText")
        self.diff_output_text.setReadOnly(True)
        self.diff_output_text.setFont(_mono_font())
        self.diff_output_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        layout.addWidget(options_group)
        layout.addWidget(summary_group)
        layout.addWidget(self.diff_output_text, 1)

        return tab

    def _build_preview_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        top_group = QGroupBox("Format record / validering")
        top_group.setObjectName("ActionGroup")
        top_layout = QGridLayout(top_group)

        self.preview_post_type_combo = QComboBox()
        self.preview_post_type_combo.setObjectName("PreviewPostTypeCombo")

        self.load_template_button = QPushButton("Ladda mall")
        self.load_template_button.setObjectName("SecondaryButton")
        _set_bold(self.load_template_button)
        self.load_template_button.clicked.connect(self._load_preview_template)

        self.preview_format_button = QPushButton("Formatera post")
        self.preview_format_button.setObjectName("PrimaryButton")
        _set_bold(self.preview_format_button)
        self.preview_format_button.clicked.connect(self._format_preview_record)

        self.preview_validate_button = QPushButton("Validera")
        self.preview_validate_button.setObjectName("SecondaryButton")
        _set_bold(self.preview_validate_button)
        self.preview_validate_button.clicked.connect(self._validate_preview_record)

        self.copy_preview_button = QPushButton("Kopiera output")
        self.copy_preview_button.setObjectName("SecondaryButton")
        _set_bold(self.copy_preview_button)
        self.copy_preview_button.clicked.connect(self._copy_preview_output)

        self.clear_preview_button = QPushButton("Rensa")
        self.clear_preview_button.setObjectName("DangerButton")
        _set_bold(self.clear_preview_button)
        self.clear_preview_button.clicked.connect(self._clear_preview)

        self.preview_length_label = QLabel("Radlängd: 0")
        self.preview_length_label.setObjectName("CountLabel")
        _set_bold(self.preview_length_label)

        self.preview_latin1_label = QLabel("Latin-1: —")
        self.preview_latin1_label.setObjectName("StatusLabel")
        _set_bold(self.preview_latin1_label)

        top_layout.addWidget(QLabel("Posttyp:"), 0, 0)
        top_layout.addWidget(self.preview_post_type_combo, 0, 1)
        top_layout.addWidget(self.load_template_button, 0, 2)
        top_layout.addWidget(self.preview_format_button, 0, 3)
        top_layout.addWidget(self.preview_validate_button, 1, 2)
        top_layout.addWidget(self.copy_preview_button, 1, 3)
        top_layout.addWidget(self.clear_preview_button, 1, 4)
        top_layout.addWidget(self.preview_length_label, 0, 4)
        top_layout.addWidget(self.preview_latin1_label, 1, 1)

        splitter = QSplitter(Qt.Vertical)

        self.preview_input_text = QPlainTextEdit()
        self.preview_input_text.setObjectName("PreviewInputText")
        self.preview_input_text.setPlaceholderText(
            '{\n  "fält1": "värde",\n  "fält2": "värde"\n}'
        )
        self.preview_input_text.setFont(_mono_font())
        self.preview_input_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        output_splitter = QSplitter(Qt.Horizontal)

        self.preview_output_text = QPlainTextEdit()
        self.preview_output_text.setObjectName("PreviewOutputText")
        self.preview_output_text.setReadOnly(True)
        self.preview_output_text.setFont(_mono_font())
        self.preview_output_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.preview_validation_text = QPlainTextEdit()
        self.preview_validation_text.setObjectName("PreviewValidationText")
        self.preview_validation_text.setReadOnly(True)
        self.preview_validation_text.setFont(_mono_font())
        self.preview_validation_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        output_splitter.addWidget(self.preview_output_text)
        output_splitter.addWidget(self.preview_validation_text)
        output_splitter.setSizes([800, 420])

        splitter.addWidget(self.preview_input_text)
        splitter.addWidget(output_splitter)
        splitter.setSizes([260, 360])

        layout.addWidget(top_group)
        layout.addWidget(splitter, 1)

        return tab

    def _build_backup_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        button_group = QGroupBox("Backup, import och export")
        button_group.setObjectName("ActionGroup")
        button_layout = QHBoxLayout(button_group)

        self.create_backup_button = QPushButton("Skapa backup")
        self.create_backup_button.setObjectName("SuccessButton")
        _set_bold(self.create_backup_button)
        self.create_backup_button.clicked.connect(self._create_backup)

        self.restore_backup_button = QPushButton("Återställ vald")
        self.restore_backup_button.setObjectName("PrimaryButton")
        _set_bold(self.restore_backup_button)
        self.restore_backup_button.clicked.connect(self._restore_selected_backup)

        self.export_version_button = QPushButton("Exportera version")
        self.export_version_button.setObjectName("SecondaryButton")
        _set_bold(self.export_version_button)
        self.export_version_button.clicked.connect(self._export_selected_version)

        self.import_version_button = QPushButton("Importera version")
        self.import_version_button.setObjectName("SecondaryButton")
        _set_bold(self.import_version_button)
        self.import_version_button.clicked.connect(self._import_version_from_directory)

        self.export_all_versions_button = QPushButton("Exportera alla")
        self.export_all_versions_button.setObjectName("SecondaryButton")
        _set_bold(self.export_all_versions_button)
        self.export_all_versions_button.clicked.connect(self._export_all_versions)

        self.refresh_backup_button = QPushButton("Uppdatera")
        self.refresh_backup_button.setObjectName("SecondaryButton")
        _set_bold(self.refresh_backup_button)
        self.refresh_backup_button.clicked.connect(self._refresh_backup_and_history)

        button_layout.addWidget(self.create_backup_button)
        button_layout.addWidget(self.restore_backup_button)
        button_layout.addWidget(self.export_version_button)
        button_layout.addWidget(self.import_version_button)
        button_layout.addWidget(self.export_all_versions_button)
        button_layout.addWidget(self.refresh_backup_button)

        splitter = QSplitter(Qt.Horizontal)

        left_group = QGroupBox("Tillgängliga backuper")
        left_group.setObjectName("SearchGroup")
        left_layout = QVBoxLayout(left_group)

        self.backups_text = QPlainTextEdit()
        self.backups_text.setObjectName("BackupsText")
        self.backups_text.setReadOnly(True)
        self.backups_text.setFont(_mono_font())
        self.backups_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        left_layout.addWidget(self.backups_text)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Sök i historik...")
        self.history_search.setObjectName("HistorySearchEdit")
        self.history_search.textChanged.connect(self._on_history_search)

        self.history_model = HistoryTableModel(self)
        self.history_proxy = QSortFilterProxyModel(self)
        self.history_proxy.setSourceModel(self.history_model)
        self.history_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.history_proxy.setFilterKeyColumn(-1)

        self.history_table = QTableView()
        self.history_table.setObjectName("HistoryTable")
        self.history_table.setModel(self.history_proxy)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSortingEnabled(True)
        self.history_table.setWordWrap(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.history_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.history_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        if self.history_table.selectionModel() is not None:
            self.history_table.selectionModel().selectionChanged.connect(
                self._on_history_selection_changed
            )

        self.history_details_text = QPlainTextEdit()
        self.history_details_text.setObjectName("HistoryDetailsText")
        self.history_details_text.setReadOnly(True)
        self.history_details_text.setFont(_mono_font())
        self.history_details_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        right_layout.addWidget(self.history_search)
        right_layout.addWidget(self.history_table, 1)
        right_layout.addWidget(self.history_details_text, 1)

        splitter.addWidget(left_group)
        splitter.addWidget(right_panel)
        splitter.setSizes([360, 860])

        layout.addWidget(button_group)
        layout.addWidget(splitter, 1)

        return tab

    def _build_diagnostics_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        button_layout = QHBoxLayout()

        self.refresh_diagnostics_button = QPushButton("Basdiagnostik")
        self.refresh_diagnostics_button.setObjectName("PrimaryButton")
        _set_bold(self.refresh_diagnostics_button)
        self.refresh_diagnostics_button.clicked.connect(self._load_basic_diagnostics)

        self.metadata_button = QPushButton("Metadata")
        self.metadata_button.setObjectName("SecondaryButton")
        _set_bold(self.metadata_button)
        self.metadata_button.clicked.connect(self._load_metadata)

        self.field_stats_button = QPushButton("Fältstatistik")
        self.field_stats_button.setObjectName("SecondaryButton")
        _set_bold(self.field_stats_button)
        self.field_stats_button.clicked.connect(self._load_field_statistics)

        self.collaboration_button = QPushButton("Samarbetsstatus")
        self.collaboration_button.setObjectName("SecondaryButton")
        _set_bold(self.collaboration_button)
        self.collaboration_button.clicked.connect(self._load_collaboration_status)

        self.comprehensive_report_button = QPushButton("Komplett rapport")
        self.comprehensive_report_button.setObjectName("SecondaryButton")
        _set_bold(self.comprehensive_report_button)
        self.comprehensive_report_button.clicked.connect(self._load_comprehensive_report)

        self.sync_import_button = QPushButton("Synka TS-spec-import")
        self.sync_import_button.setObjectName("SuccessButton")
        _set_bold(self.sync_import_button)
        self.sync_import_button.clicked.connect(self._sync_ts_spec_import)

        for button in (
            self.refresh_diagnostics_button,
            self.metadata_button,
            self.field_stats_button,
            self.collaboration_button,
            self.comprehensive_report_button,
            self.sync_import_button,
        ):
            button_layout.addWidget(button)

        self.diagnostics_text = QPlainTextEdit()
        self.diagnostics_text.setObjectName("DiagnosticsText")
        self.diagnostics_text.setReadOnly(True)
        self.diagnostics_text.setFont(_mono_font())
        self.diagnostics_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        layout.addLayout(button_layout)
        layout.addWidget(self.diagnostics_text, 1)

        return tab

    # -----------------------------------------------------------------
    # Generic helpers
    # -----------------------------------------------------------------
    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _info(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)

    def _warning(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    def _error(self, title: str, text: str) -> None:
        QMessageBox.critical(self, title, text)

    def _confirm(self, title: str, text: str) -> bool:
        result = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def _get_manager(self) -> Any:
        for attr_name in ("version_manager", "_version_manager", "manager", "_manager"):
            try:
                value = getattr(self.plugin, attr_name, None)
                if value is not None:
                    return value
            except Exception:
                _log.exception("Kunde inte läsa attribut %s från plugin.", attr_name)
        return None

    def _get_store(self) -> Any:
        manager = self._get_manager()
        for owner in (self.plugin, manager):
            if owner is None:
                continue
            for attr_name in ("store", "_store", "schema_store", "_schema_store"):
                try:
                    value = getattr(owner, attr_name, None)
                    if value is not None:
                        return value
                except Exception:
                    _log.exception("Kunde inte läsa store-attribut %s.", attr_name)
        return None

    def _find_callable(self, owner: Any, *names: str) -> Optional[Callable[..., Any]]:
        if owner is None:
            return None
        for name in names:
            try:
                candidate = getattr(owner, name, None)
                if callable(candidate):
                    return candidate
            except Exception:
                _log.exception("Kunde inte läsa metod %s.", name)
        return None

    def _call_first_available(
        self,
        candidates: Sequence[Tuple[Any, Sequence[str]]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        last_error: Optional[Exception] = None
        for owner, names in candidates:
            func = self._find_callable(owner, *names)
            if func is None:
                continue
            try:
                return _invoke_callable(func, *args, **kwargs)
            except Exception as exc:
                last_error = exc
                _log.exception("Metodanrop misslyckades för %r.", names)
        if last_error is not None:
            raise last_error
        raise AttributeError("Ingen kompatibel metod hittades.")

    def _list_versions(self) -> List[str]:
        manager = self._get_manager()
        try:
            versions = self._call_first_available(
                (
                    (self.plugin, ("list_versions",)),
                    (manager, ("list_versions",)),
                    (self._get_store(), ("list_versions",)),
                )
            )
            return sorted([str(v) for v in list(versions or [])])
        except Exception:
            _log.exception("Kunde inte hämta versionslista.")
            return []

    def _get_active_version(self) -> str:
        manager = self._get_manager()

        for owner, attr_name in (
            (self.plugin, "active_version"),
            (manager, "active_version"),
        ):
            if owner is None:
                continue
            try:
                value = getattr(owner, attr_name, "")
                if isinstance(value, str) and value.strip():
                    return value.strip()
            except Exception:
                _log.exception("Kunde inte läsa aktiv version från %s.", attr_name)

        if self._current_version:
            return self._current_version
        if self._versions:
            return self._versions[0]
        return ""

    def _set_active_version(self, version: str) -> bool:
        manager = self._get_manager()
        try:
            func = self._find_callable(self.plugin, "set_active_version")
            if func is not None:
                _invoke_callable(func, version)
                self._current_version = version
                return True
        except Exception:
            _log.exception("set_active_version() misslyckades i plugin.")

        try:
            if manager is not None and hasattr(manager, "active_version"):
                setattr(manager, "active_version", version)
                self._current_version = version
                return True
        except Exception:
            _log.exception("Sättning av manager.active_version misslyckades.")

        return False

    def _load_version_schemas(self, version: str) -> Dict[str, Any]:
        manager = self._get_manager()
        store = self._get_store()

        if manager is not None:
            func = self._find_callable(manager, "load_version")
            if func is not None:
                try:
                    data = _invoke_callable(func, version)
                    if isinstance(data, dict):
                        return {
                            _normalize_post_type(k): v
                            for k, v in data.items()
                            if _normalize_post_type(k)
                        }
                except Exception:
                    _log.exception("manager.load_version() misslyckades för %s.", version)

        if store is not None:
            func = self._find_callable(store, "load_all_specs")
            if func is not None:
                try:
                    data = _invoke_callable(func, version)
                    if isinstance(data, dict):
                        return {
                            _normalize_post_type(k): v
                            for k, v in data.items()
                            if _normalize_post_type(k)
                        }
                except Exception:
                    _log.exception("store.load_all_specs() misslyckades för %s.", version)

        try:
            func = self._find_callable(self.plugin, "get_all_schemas")
            if func is not None:
                data = _invoke_callable(func, version=version)
                if isinstance(data, dict):
                    return {
                        _normalize_post_type(k): v
                        for k, v in data.items()
                        if _normalize_post_type(k)
                    }
        except Exception:
            _log.exception("plugin.get_all_schemas() misslyckades för %s.", version)

        return {}

    def _get_current_spec(self) -> Optional[Any]:
        if not self._current_post_type:
            return None
        return self._schemas_by_post_type.get(self._current_post_type)

    def _get_selected_post_type(self) -> str:
        selection_model = self.post_types_table.selectionModel()
        if selection_model is None:
            return ""
        indexes = selection_model.selectedRows()
        if not indexes:
            return ""
        source_index = self.post_types_proxy.mapToSource(indexes[0])
        row = self.post_types_model.get_row(source_index.row())
        if row is None:
            return ""
        return str(row.get("post_type", "") or "")

    def _get_selected_field(self) -> Optional[Any]:
        selection_model = self.fields_table.selectionModel()
        if selection_model is None:
            return None
        indexes = selection_model.selectedRows()
        if not indexes:
            return None
        source_index = self.fields_proxy.mapToSource(indexes[0])
        return self.fields_model.get_field(source_index.row())

    def _save_schema(self, post_type: str, spec: Any, version: Optional[str] = None) -> bool:
        version = version or self._current_version or self._get_active_version()
        manager = self._get_manager()
        store = self._get_store()

        try:
            result = self._call_first_available(
                (
                    (self.plugin, ("save_schema", "save_spec", "update_schema")),
                    (manager, ("save_spec", "save_schema")),
                    (store, ("save_spec", "save_schema")),
                ),
                post_type,
                spec,
                version=version,
            )
            if hasattr(result, "success"):
                return bool(getattr(result, "success"))
            return bool(True if result is None else result)
        except Exception:
            _log.exception("Kunde inte spara schema %s i version %s.", post_type, version)
            return False

    def _delete_schema(self, post_type: str, version: Optional[str] = None) -> bool:
        version = version or self._current_version or self._get_active_version()
        manager = self._get_manager()
        store = self._get_store()

        try:
            result = self._call_first_available(
                (
                    (self.plugin, ("delete_schema", "delete_spec")),
                    (manager, ("delete_spec", "delete_schema")),
                    (store, ("delete_spec", "delete_schema")),
                ),
                post_type,
                version=version,
            )
            if hasattr(result, "success"):
                return bool(getattr(result, "success"))
            return bool(True if result is None else result)
        except Exception:
            _log.exception("Kunde inte ta bort schema %s i version %s.", post_type, version)
            return False

    def _create_new_version(self, version: str, source_file: str = "", description: str = "") -> bool:
        manager = self._get_manager()
        try:
            result = self._call_first_available(
                (
                    (self.plugin, ("create_version",)),
                    (manager, ("create_version",)),
                ),
                version,
                source=source_file,
                source_file=source_file,
                description=description,
            )
            return bool(True if result is None else result)
        except Exception:
            _log.exception("Kunde inte skapa version %s.", version)
            return False

    def _duplicate_existing_version(self, source_version: str, target_version: str) -> bool:
        manager = self._get_manager()
        try:
            result = self._call_first_available(
                (
                    (self.plugin, ("duplicate_version", "clone_version")),
                    (manager, ("duplicate_version", "clone_version")),
                ),
                source_version,
                target_version,
            )
            return bool(True if result is None else result)
        except Exception:
            _log.exception(
                "Kunde inte duplicera version %s -> %s.", source_version, target_version
            )
            return False

    def _rename_existing_version(self, old_version: str, new_version: str) -> bool:
        manager = self._get_manager()
        try:
            result = self._call_first_available(
                (
                    (self.plugin, ("rename_version",)),
                    (manager, ("rename_version",)),
                ),
                old_version,
                new_version,
            )
            return bool(True if result is None else result)
        except Exception:
            _log.exception("Kunde inte byta namn på version %s -> %s.", old_version, new_version)
            return False

    def _delete_existing_version(self, version: str) -> bool:
        manager = self._get_manager()
        try:
            result = self._call_first_available(
                (
                    (self.plugin, ("delete_version",)),
                    (manager, ("delete_version",)),
                    (self._get_store(), ("delete_version",)),
                ),
                version,
            )
            if hasattr(result, "success"):
                return bool(getattr(result, "success"))
            return bool(True if result is None else result)
        except Exception:
            _log.exception("Kunde inte ta bort version %s.", version)
            return False

    def _list_backups(self) -> List[str]:
        manager = self._get_manager()
        try:
            backups = self._call_first_available(
                (
                    (self.plugin, ("list_backups",)),
                    (manager, ("list_backups",)),
                )
            )
            return [str(x) for x in list(backups or [])]
        except Exception:
            _log.exception("Kunde inte läsa backups.")
            return []

    def _create_backup_internal(self) -> bool:
        try:
            result = self._call_first_available(
                (
                    (self.plugin, ("backup_all", "create_backup", "backup")),
                )
            )
            return bool(True if result is None else result)
        except Exception:
            _log.exception("Kunde inte skapa backup.")
            return False

    def _restore_backup_internal(self, backup_identifier: str) -> bool:
        try:
            result = self._call_first_available(
                (
                    (self.plugin, ("restore_from_backup", "restore_backup")),
                ),
                backup_identifier,
            )
            return bool(True if result is None else result)
        except Exception:
            _log.exception("Kunde inte återställa backup %s.", backup_identifier)
            return False

    def _get_history(self) -> List[Dict[str, Any]]:
        manager = self._get_manager()
        try:
            history = self._call_first_available(
                (
                    (self.plugin, ("get_history", "history")),
                    (manager, ("get_history",)),
                )
            )
            rows = []
            for item in list(history or []):
                if isinstance(item, dict):
                    rows.append(item)
                else:
                    rows.append(_obj_to_dict(item))
            return rows
        except Exception:
            _log.exception("Kunde inte läsa historik.")
            return []

    def _export_version_to_dir(self, version: str, target_dir: str) -> bool:
        manager = self._get_manager()
        store = self._get_store()
        try:
            result = self._call_first_available(
                (
                    (self.plugin, ("export_version_to_dir",)),
                    (manager, ("export_version_to_dir",)),
                    (store, ("export_version_to_dir",)),
                ),
                version,
                target_dir,
                path=target_dir,
            )
            if hasattr(result, "success"):
                return bool(getattr(result, "success"))
            return bool(True if result is None else result)
        except Exception:
            _log.exception("Kunde inte exportera version %s till %s.", version, target_dir)
            return False

    def _import_version_from_dir(self, source_dir: str, version: str) -> bool:
        manager = self._get_manager()
        store = self._get_store()
        try:
            result = self._call_first_available(
                (
                    (self.plugin, ("import_version_from_dir",)),
                    (manager, ("import_version_from_dir",)),
                    (store, ("import_version_from_dir",)),
                ),
                source_dir,
                version,
                path=source_dir,
            )
            if hasattr(result, "success"):
                return bool(getattr(result, "success"))
            return bool(True if result is None else result)
        except Exception:
            _log.exception("Kunde inte importera version %s från %s.", version, source_dir)
            return False

    def _export_all_versions_internal(self, target_dir: str) -> bool:
        try:
            func = self._find_callable(self.plugin, "export_all_versions")
            if func is not None:
                result = _invoke_callable(func, target_dir)
                return bool(True if result is None else result)
        except Exception:
            _log.exception("plugin.export_all_versions() misslyckades.")

        success = True
        for version in self._list_versions():
            if not self._export_version_to_dir(version, target_dir):
                success = False
        return success

    def _compare_version_data(self, version1: str, version2: str) -> Any:
        manager = self._get_manager()
        try:
            func = self._find_callable(self.plugin, "compare_versions")
            if func is not None:
                return _invoke_callable(func, version1, version2)
        except Exception:
            _log.exception("plugin.compare_versions() misslyckades.")

        try:
            func = self._find_callable(manager, "compare_versions")
            if func is not None:
                return _invoke_callable(func, version1, version2)
        except Exception:
            _log.exception("manager.compare_versions() misslyckades.")

        schemas1 = self._load_version_schemas(version1)
        schemas2 = self._load_version_schemas(version2)
        return self.schema_diff.diff_versions(schemas1, schemas2, version1, version2)

    def _format_record(self, post_type: str, data: Dict[str, Any]) -> str:
        spec = self._schemas_by_post_type.get(post_type)
        try:
            func = self._find_callable(self.plugin, "format_record")
            if func is not None:
                try:
                    result = _invoke_callable(func, post_type, data, version=self._current_version)
                    if isinstance(result, str):
                        return result
                except Exception:
                    _log.exception("plugin.format_record() misslyckades, försöker fallback.")
        except Exception:
            _log.exception("Kunde inte anropa plugin.format_record().")

        if spec is not None and hasattr(spec, "format_record") and callable(spec.format_record):
            result = spec.format_record(data)
            if isinstance(result, str):
                return result

        raise RuntimeError("Ingen kompatibel format_record-funktion tillgänglig.")

    def _validate_record(self, post_type: str, data: Dict[str, Any]) -> Any:
        spec = self._schemas_by_post_type.get(post_type)
        try:
            func = self._find_callable(self.plugin, "validate_record")
            if func is not None:
                return _invoke_callable(func, post_type, data, version=self._current_version)
        except Exception:
            _log.exception("plugin.validate_record() misslyckades, försöker fallback.")

        if spec is not None and hasattr(spec, "validate_record") and callable(spec.validate_record):
            return spec.validate_record(data)

        return {"valid": False, "error": "Ingen validate_record-funktion tillgänglig."}

    def _validate_structure(self, spec: Any) -> Any:
        try:
            if hasattr(spec, "validate_structure") and callable(spec.validate_structure):
                return spec.validate_structure()
        except Exception:
            _log.exception("validate_structure() misslyckades.")
        try:
            valid = bool(getattr(spec, "is_valid", True))
            return {"valid": valid}
        except Exception:
            return {"valid": False, "error": "Kunde inte validera struktur."}

    def _create_empty_spec(self, post_type: str, name: str, total_length: int) -> Any:
        try:
            func = self._find_callable(self.plugin, "create_empty_schema", "empty_schema")
            if func is not None:
                return _invoke_callable(
                    func,
                    post_type,
                    name=name,
                    total_length=total_length,
                    version=self._current_version,
                )
        except Exception:
            _log.exception("Plugin create_empty_schema()/empty_schema misslyckades.")

        try:
            return create_empty_post_spec(
                post_type=post_type,
                name=name,
                length=total_length,
                version=self._current_version,
            )
        except Exception:
            _log.exception("create_empty_post_spec() misslyckades, försöker minimal spec.")

        spec = create_minimal_spec(post_type)
        try:
            spec.name = name
        except Exception:
            pass
        try:
            spec.total_length = total_length
        except Exception:
            pass
        return spec

    # -----------------------------------------------------------------
    # Refresh and population
    # -----------------------------------------------------------------
    def refresh(self) -> None:
        try:
            self._set_status("Laddar schema...")
            self._versions = self._list_versions()

            active_version = self._get_active_version()
            if active_version and active_version not in self._versions and self._versions:
                active_version = self._versions[0]
            if not active_version and self._versions:
                active_version = self._versions[0]
            self._current_version = active_version

            self._populate_versions()
            self._schemas_by_post_type = (
                self._load_version_schemas(self._current_version) if self._current_version else {}
            )

            if self._current_post_type not in self._schemas_by_post_type:
                self._current_post_type = next(iter(sorted(self._schemas_by_post_type.keys())), "")

            self._populate_post_types()
            self._refresh_field_panel_only()
            self._populate_diff_controls()
            self._populate_preview_post_types()
            self._refresh_backup_and_history()
            self._load_basic_diagnostics()
            self._update_counts()
            self._set_status("Schema laddat.")
        except Exception:
            _log.exception("refresh() misslyckades i TSSchemaManagerWidget.")
            self._set_status("Fel vid laddning av schema.")
            self._error("Fel", "Kunde inte ladda TS Schema Manager.")

    def _populate_versions(self) -> None:
        current = self._current_version
        self.version_combo.blockSignals(True)
        self.diff_version1_combo.blockSignals(True)
        self.diff_version2_combo.blockSignals(True)

        self.version_combo.clear()
        self.diff_version1_combo.clear()
        self.diff_version2_combo.clear()

        for version in self._versions:
            self.version_combo.addItem(version)
            self.diff_version1_combo.addItem(version)
            self.diff_version2_combo.addItem(version)

        if current:
            idx = self.version_combo.findText(current)
            if idx >= 0:
                self.version_combo.setCurrentIndex(idx)

            idx1 = self.diff_version1_combo.findText(current)
            if idx1 >= 0:
                self.diff_version1_combo.setCurrentIndex(idx1)

            if len(self._versions) > 1:
                idx2 = self.diff_version2_combo.findText(self._versions[-1])
                if idx2 >= 0:
                    self.diff_version2_combo.setCurrentIndex(idx2)
            else:
                idx2 = self.diff_version2_combo.findText(current)
                if idx2 >= 0:
                    self.diff_version2_combo.setCurrentIndex(idx2)

        self.version_combo.blockSignals(False)
        self.diff_version1_combo.blockSignals(False)
        self.diff_version2_combo.blockSignals(False)

    def _populate_post_types(self) -> None:
        rows: List[Dict[str, Any]] = []
        for post_type, spec in sorted(self._schemas_by_post_type.items()):
            fields = _iter_fields(spec)
            rows.append(
                {
                    "post_type": post_type,
                    "name": _spec_name(spec),
                    "field_count": len(fields),
                    "required_count": _get_required_field_count(spec),
                    "coverage": _compute_coverage(spec),
                    "total_length": _spec_length(spec),
                }
            )

        self.post_types_model.set_rows(rows)
        self._restore_post_type_selection()

    def _restore_post_type_selection(self) -> None:
        if not self._current_post_type:
            self._update_selected_post_type_panels()
            return

        for row_index in range(self.post_types_proxy.rowCount()):
            proxy_index = self.post_types_proxy.index(row_index, 0)
            source_index = self.post_types_proxy.mapToSource(proxy_index)
            row = self.post_types_model.get_row(source_index.row())
            if row and row.get("post_type") == self._current_post_type:
                self.post_types_table.selectRow(row_index)
                break

        self._update_selected_post_type_panels()

    def _populate_diff_controls(self) -> None:
        all_post_types = sorted(self._schemas_by_post_type.keys())
        current_data = self.diff_post_type_combo.currentData()

        self.diff_post_type_combo.blockSignals(True)
        self.diff_post_type_combo.clear()
        self.diff_post_type_combo.addItem("Alla", "")
        for post_type in all_post_types:
            self.diff_post_type_combo.addItem(post_type, post_type)

        idx = self.diff_post_type_combo.findData(current_data)
        if idx >= 0:
            self.diff_post_type_combo.setCurrentIndex(idx)
        self.diff_post_type_combo.blockSignals(False)

    def _populate_preview_post_types(self) -> None:
        current = self.preview_post_type_combo.currentData()
        self.preview_post_type_combo.blockSignals(True)
        self.preview_post_type_combo.clear()
        for post_type in sorted(self._schemas_by_post_type.keys()):
            self.preview_post_type_combo.addItem(post_type, post_type)

        preferred = self._current_post_type or current
        if preferred:
            idx = self.preview_post_type_combo.findData(preferred)
            if idx >= 0:
                self.preview_post_type_combo.setCurrentIndex(idx)
        self.preview_post_type_combo.blockSignals(False)

    def _refresh_field_panel_only(self) -> None:
        spec = self._get_current_spec()
        fields = _iter_fields(spec) if spec is not None else []
        self.fields_model.set_fields(fields)
        self._update_selected_post_type_panels()

    def _update_selected_post_type_panels(self) -> None:
        spec = self._get_current_spec()
        if spec is None:
            self.selected_post_type_label.setText("—")
            self.selected_post_name_label.setText("—")
            self.selected_post_meta_label.setText("Ingen posttyp vald.")
            self.schema_summary_text.setPlainText("")
            self.coverage_label.setText("Täckning: 0.00%")
            self.coverage_progress.setValue(0)
            self.gaps_text.setPlainText("")
            self.overlaps_text.setPlainText("")
            return

        post_type = _spec_post_type(spec)
        name = _spec_name(spec)
        fields = _iter_fields(spec)
        required_count = _get_required_field_count(spec)
        coverage = _compute_coverage(spec)
        total_length = _spec_length(spec)
        gaps = _try_get_gaps(spec)
        overlaps = _try_get_overlaps(spec)

        self.selected_post_type_label.setText(post_type)
        self.selected_post_name_label.setText(name)
        self.selected_post_meta_label.setText(
            f"Fält: {len(fields)} • Obligatoriska: {required_count} • "
            f"Längd: {total_length} • Täckning: {coverage:.2f}%"
        )

        summary = {
            "post_type": post_type,
            "name": name,
            "version": self._current_version,
            "field_count": len(fields),
            "required_count": required_count,
            "total_length": total_length,
            "coverage_percent": coverage,
            "gaps": len(gaps),
            "overlaps": len(overlaps),
            "valid_structure": self._validation_is_valid(self._validate_structure(spec)),
        }
        self.schema_summary_text.setPlainText(_pretty_json(summary))

        self.coverage_label.setText(f"Täckning: {coverage:.2f}%")
        self.coverage_progress.setValue(int(round(coverage)))

        self.gaps_text.setPlainText(
            "\n".join(_format_gap_item(item) for item in gaps) if gaps else "Inga luckor."
        )
        self.overlaps_text.setPlainText(
            "\n".join(_format_overlap_item(item) for item in overlaps)
            if overlaps
            else "Inga överlapp."
        )

    def _update_counts(self) -> None:
        post_type_count = len(self._schemas_by_post_type)
        field_count = sum(len(_iter_fields(spec)) for spec in self._schemas_by_post_type.values())
        self.count_label.setText(
            f"{len(self._versions)} versioner • {post_type_count} posttyper • {field_count} fält"
        )

    def _refresh_backup_and_history(self) -> None:
        self._backups = self._list_backups()
        self._history_rows = self._get_history()

        self.backups_text.setPlainText(
            "\n".join(self._backups) if self._backups else "Inga backuper hittades."
        )
        self.history_model.set_rows(self._history_rows)
        self.history_details_text.setPlainText("")

    # -----------------------------------------------------------------
    # Selection / search
    # -----------------------------------------------------------------
    def _on_version_combo_changed(self, version: str) -> None:
        self._current_version = version.strip()

    def _activate_selected_version(self) -> None:
        version = self.version_combo.currentText().strip()
        if not version:
            self._warning("Version", "Ingen version vald.")
            return
        if not self._set_active_version(version):
            self._error("Version", f"Kunde inte aktivera version '{version}'.")
            return
        self._set_status(f"Aktiv version satt till {version}.")
        self.refresh()

    def _on_post_type_search(self, text: str) -> None:
        self.post_types_proxy.setFilterFixedString(text)

    def _on_field_search(self, text: str) -> None:
        self.fields_proxy.setFilterFixedString(text)

    def _on_history_search(self, text: str) -> None:
        self.history_proxy.setFilterFixedString(text)

    def _on_post_type_selection_changed(self) -> None:
        post_type = self._get_selected_post_type()
        if not post_type:
            return
        self._current_post_type = post_type
        self._refresh_field_panel_only()
        idx = self.preview_post_type_combo.findData(post_type)
        if idx >= 0:
            self.preview_post_type_combo.setCurrentIndex(idx)

    def _on_history_selection_changed(self) -> None:
        selection_model = self.history_table.selectionModel()
        if selection_model is None:
            return
        indexes = selection_model.selectedRows()
        if not indexes:
            self.history_details_text.setPlainText("")
            return
        source_index = self.history_proxy.mapToSource(indexes[0])
        row = self.history_model.get_row(source_index.row())
        self.history_details_text.setPlainText(_pretty_json(row or {}))

    # -----------------------------------------------------------------
    # Versions
    # -----------------------------------------------------------------
    def _create_version(self) -> None:
        dialog = VersionDialog(
            self,
            existing_data={
                "version": f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "source_file": "",
                "description": "",
            },
            title="Skapa ny version",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        version = data["version"]
        if version in self._versions:
            self._warning("Version", f"Version '{version}' finns redan.")
            return

        if not self._create_new_version(version, data["source_file"], data["description"]):
            self._error("Version", f"Kunde inte skapa version '{version}'.")
            return

        self._set_active_version(version)
        self.refresh()
        self._info("Version", f"Version '{version}' skapades.")

    def _duplicate_version(self) -> None:
        source_version = self.version_combo.currentText().strip()
        if not source_version:
            self._warning("Version", "Ingen källversion vald.")
            return

        dialog = VersionDialog(
            self,
            existing_data={
                "version": f"{source_version}_copy",
                "source_file": "",
                "description": f"Kopia av {source_version}",
            },
            title="Duplicera version",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        target_version = dialog.get_data()["version"]
        if target_version in self._versions:
            self._warning("Version", f"Version '{target_version}' finns redan.")
            return

        if not self._duplicate_existing_version(source_version, target_version):
            self._error(
                "Version",
                f"Kunde inte duplicera version '{source_version}' till '{target_version}'.",
            )
            return

        self._set_active_version(target_version)
        self.refresh()
        self._info("Version", f"Version '{target_version}' skapades från '{source_version}'.")

    def _rename_version(self) -> None:
        current_version = self.version_combo.currentText().strip()
        if not current_version:
            self._warning("Version", "Ingen version vald.")
            return

        dialog = VersionDialog(
            self,
            existing_data={"version": current_version},
            title="Byt namn på version",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_version = dialog.get_data()["version"]
        if new_version == current_version:
            return
        if new_version in self._versions:
            self._warning("Version", f"Version '{new_version}' finns redan.")
            return

        if not self._rename_existing_version(current_version, new_version):
            self._error(
                "Version",
                f"Kunde inte byta namn från '{current_version}' till '{new_version}'.",
            )
            return

        self._current_version = new_version
        self.refresh()
        self._info("Version", f"Version '{current_version}' döptes om till '{new_version}'.")

    def _delete_version(self) -> None:
        version = self.version_combo.currentText().strip()
        if not version:
            self._warning("Version", "Ingen version vald.")
            return
        if not self._confirm(
            "Ta bort version",
            f"Är du säker på att du vill ta bort version '{version}'?",
        ):
            return

        if not self._delete_existing_version(version):
            self._error("Version", f"Kunde inte ta bort version '{version}'.")
            return

        self._current_version = ""
        self.refresh()
        self._info("Version", f"Version '{version}' togs bort.")

    # -----------------------------------------------------------------
    # Post type CRUD
    # -----------------------------------------------------------------
    def _add_post_type(self) -> None:
        dialog = PostTypeDialog(
            self,
            existing_data={
                "post_type": "",
                "name": "",
                "total_length": TS_POST_LENGTH,
            },
            title="Ny posttyp",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        post_type = data["post_type"]

        if post_type in self._schemas_by_post_type:
            self._warning("Posttyp", f"Posttyp '{post_type}' finns redan.")
            return

        spec = self._create_empty_spec(post_type, data["name"], data["total_length"])
        if not self._save_schema(post_type, spec):
            self._error("Posttyp", f"Kunde inte spara posttyp '{post_type}'.")
            return

        self._current_post_type = post_type
        self.refresh()
        self._info("Posttyp", f"Posttyp '{post_type}' skapades.")

    def _edit_post_type(self) -> None:
        spec = self._get_current_spec()
        if spec is None:
            self._warning("Posttyp", "Ingen posttyp vald.")
            return

        current_post_type = self._current_post_type
        current_data = _obj_to_dict(spec)
        dialog = PostTypeDialog(self, existing_data=current_data, title="Redigera posttyp")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        new_post_type = data["post_type"]

        if new_post_type != current_post_type and new_post_type in self._schemas_by_post_type:
            self._warning("Posttyp", f"Posttyp '{new_post_type}' finns redan.")
            return

        new_data = _obj_to_dict(spec)
        new_data["post_type"] = new_post_type
        new_data["name"] = data["name"]
        new_data["total_length"] = data["total_length"]

        new_spec = _build_spec_from_dict(type(spec), new_data)
        if not self._save_schema(new_post_type, new_spec):
            self._error("Posttyp", "Kunde inte spara ändringar.")
            return

        if new_post_type != current_post_type:
            self._delete_schema(current_post_type)

        self._current_post_type = new_post_type
        self.refresh()
        self._info("Posttyp", f"Posttyp '{new_post_type}' uppdaterades.")

    def _clone_post_type(self) -> None:
        spec = self._get_current_spec()
        if spec is None:
            self._warning("Posttyp", "Ingen posttyp vald.")
            return

        base_post_type = self._current_post_type
        dialog = PostTypeDialog(
            self,
            existing_data={
                "post_type": f"{base_post_type}_COPY",
                "name": f"{_spec_name(spec)} kopia",
                "total_length": _spec_length(spec),
            },
            title="Klona posttyp",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        target_post_type = data["post_type"]
        if target_post_type in self._schemas_by_post_type:
            self._warning("Posttyp", f"Posttyp '{target_post_type}' finns redan.")
            return

        cloned_spec = _clone_object(spec)
        try:
            setattr(cloned_spec, "post_type", target_post_type)
        except Exception:
            pass
        try:
            setattr(cloned_spec, "name", data["name"])
        except Exception:
            pass
        try:
            setattr(cloned_spec, "total_length", data["total_length"])
        except Exception:
            pass

        if not self._save_schema(target_post_type, cloned_spec):
            self._error("Posttyp", "Kunde inte spara klonad posttyp.")
            return

        self._current_post_type = target_post_type
        self.refresh()
        self._info("Posttyp", f"Posttyp '{target_post_type}' skapades som kopia.")

    def _delete_post_type(self) -> None:
        post_type = self._current_post_type
        if not post_type:
            self._warning("Posttyp", "Ingen posttyp vald.")
            return
        if not self._confirm(
            "Ta bort posttyp",
            f"Är du säker på att du vill ta bort posttypen '{post_type}'?",
        ):
            return

        if not self._delete_schema(post_type):
            self._error("Posttyp", f"Kunde inte ta bort posttyp '{post_type}'.")
            return

        self._current_post_type = ""
        self.refresh()
        self._info("Posttyp", f"Posttyp '{post_type}' togs bort.")

    # -----------------------------------------------------------------
    # Field CRUD
    # -----------------------------------------------------------------
    def _add_field(self) -> None:
        spec = self._get_current_spec()
        if spec is None:
            self._warning("Fält", "Ingen posttyp vald.")
            return

        dialog = FieldDialog(self, title="Nytt fält")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        existing_names = {str(getattr(field, "name", "")) for field in _iter_fields(spec)}
        if data["name"] in existing_names:
            self._warning("Fält", f"Fältet '{data['name']}' finns redan.")
            return

        field_class_hint = type(_iter_fields(spec)[0]) if _iter_fields(spec) else ModelFieldSpec
        new_field = _build_field_from_dict(field_class_hint, data)

        new_spec = _clone_object(spec)
        try:
            if hasattr(new_spec, "add_field") and callable(new_spec.add_field):
                new_spec.add_field(new_field)
            else:
                fields = list(getattr(new_spec, "fields", []) or [])
                fields.append(new_field)
                fields.sort(key=_field_position)
                setattr(new_spec, "fields", fields)
        except Exception:
            _log.exception("Kunde inte lägga till fält lokalt.")
            self._error("Fält", "Kunde inte lägga till fältet.")
            return

        if not self._save_schema(self._current_post_type, new_spec):
            self._error("Fält", "Kunde inte spara nytt fält.")
            return

        self.refresh()
        self._info("Fält", f"Fältet '{data['name']}' skapades.")

    def _edit_field(self) -> None:
        spec = self._get_current_spec()
        field = self._get_selected_field()
        if spec is None or field is None:
            self._warning("Fält", "Inget fält valt.")
            return

        old_name = str(getattr(field, "name", "") or "")
        existing_data = _obj_to_dict(field)
        dialog = FieldDialog(self, existing_data=existing_data, title="Redigera fält")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        existing_names = {
            str(getattr(item, "name", ""))
            for item in _iter_fields(spec)
            if str(getattr(item, "name", "")) != old_name
        }
        if data["name"] in existing_names:
            self._warning("Fält", f"Fältet '{data['name']}' finns redan.")
            return

        merged_data = existing_data.copy()
        merged_data.update(data)
        updated_field = _build_field_from_dict(type(field), merged_data)

        new_spec = _clone_object(spec)
        try:
            if hasattr(new_spec, "update_field") and callable(new_spec.update_field):
                new_spec.update_field(old_name, updated_field)
            else:
                fields = []
                for item in list(getattr(new_spec, "fields", []) or []):
                    if str(getattr(item, "name", "")) == old_name:
                        fields.append(updated_field)
                    else:
                        fields.append(item)
                fields.sort(key=_field_position)
                setattr(new_spec, "fields", fields)
        except Exception:
            _log.exception("Kunde inte uppdatera fält lokalt.")
            self._error("Fält", "Kunde inte uppdatera fältet.")
            return

        if not self._save_schema(self._current_post_type, new_spec):
            self._error("Fält", "Kunde inte spara uppdaterat fält.")
            return

        self.refresh()
        self._info("Fält", f"Fältet '{data['name']}' uppdaterades.")

    def _delete_field(self) -> None:
        spec = self._get_current_spec()
        field = self._get_selected_field()
        if spec is None or field is None:
            self._warning("Fält", "Inget fält valt.")
            return

        field_name = str(getattr(field, "name", "") or "")
        if not self._confirm(
            "Ta bort fält",
            f"Är du säker på att du vill ta bort fältet '{field_name}'?",
        ):
            return

        new_spec = _clone_object(spec)
        try:
            if hasattr(new_spec, "remove_field") and callable(new_spec.remove_field):
                new_spec.remove_field(field_name)
            else:
                fields = [
                    item
                    for item in list(getattr(new_spec, "fields", []) or [])
                    if str(getattr(item, "name", "")) != field_name
                ]
                setattr(new_spec, "fields", fields)
        except Exception:
            _log.exception("Kunde inte ta bort fält lokalt.")
            self._error("Fält", "Kunde inte ta bort fältet.")
            return

        if not self._save_schema(self._current_post_type, new_spec):
            self._error("Fält", "Kunde inte spara efter borttagning av fält.")
            return

        self.refresh()
        self._info("Fält", f"Fältet '{field_name}' togs bort.")

    # -----------------------------------------------------------------
    # Validation / structure
    # -----------------------------------------------------------------
    def _validation_is_valid(self, result: Any) -> bool:
        if isinstance(result, bool):
            return result
        if isinstance(result, dict):
            for key in ("valid", "is_valid", "success", "ok"):
                if key in result:
                    return bool(result[key])
        if isinstance(result, (list, tuple, set)):
            return len(result) == 0
        return bool(result)

    def _validate_current_structure(self) -> None:
        spec = self._get_current_spec()
        if spec is None:
            self._warning("Validering", "Ingen posttyp vald.")
            return

        result = self._validate_structure(spec)
        valid = self._validation_is_valid(result)
        text = _format_result_text(result)
        self.diagnostics_text.setPlainText(text)

        if valid:
            self._info("Validering", "Strukturen är giltig.")
        else:
            self._warning("Validering", f"Strukturen innehåller problem:\n\n{text}")

    # -----------------------------------------------------------------
    # Diff
    # -----------------------------------------------------------------
    def _compare_versions(self) -> None:
        version1 = self.diff_version1_combo.currentText().strip()
        version2 = self.diff_version2_combo.currentText().strip()
        filter_post_type = str(self.diff_post_type_combo.currentData() or "")

        if not version1 or not version2:
            self._warning("Diff", "Välj två versioner att jämföra.")
            return

        try:
            diff = self._compare_version_data(version1, version2)

            if hasattr(diff, "post_type_diffs"):
                post_type_diffs = list(getattr(diff, "post_type_diffs", []) or [])
                if filter_post_type:
                    post_type_diffs = [
                        item
                        for item in post_type_diffs
                        if str(getattr(item, "post_type", "")) == filter_post_type
                    ]
                    try:
                        clone = copy.deepcopy(diff)
                        clone.post_type_diffs = post_type_diffs
                        diff = clone
                    except Exception:
                        pass

                text = self.schema_diff.format_version_diff_text(diff)
                summary = self.schema_diff.get_version_summary(diff)
                self.diff_summary_changed.setText(
                    f"Ändrade: {summary.get('changed_post_types', 0)}"
                )
                self.diff_summary_added.setText(f"Tillagda: {summary.get('added_post_types', 0)}")
                self.diff_summary_removed.setText(
                    f"Borttagna: {summary.get('removed_post_types', 0)}"
                )
                self.diff_summary_breaking.setText(
                    f"Breaking: {summary.get('breaking_post_types', 0)}"
                )
                self.diff_output_text.setPlainText(text)
                return

            if isinstance(diff, dict):
                text = _pretty_json(diff)
                self.diff_output_text.setPlainText(text)
                self.diff_summary_changed.setText("Ändrade: —")
                self.diff_summary_added.setText("Tillagda: —")
                self.diff_summary_removed.setText("Borttagna: —")
                self.diff_summary_breaking.setText("Breaking: —")
                return

            self.diff_output_text.setPlainText(_format_result_text(diff))
        except Exception:
            _log.exception("Jämförelse mellan versioner misslyckades.")
            self._error("Diff", "Kunde inte jämföra versionerna.")

    def _export_diff_report(self) -> None:
        text = self.diff_output_text.toPlainText().strip()
        if not text:
            self._warning("Diff", "Ingen diff-rapport att spara.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Spara diff-rapport",
            str(Path.cwd() / "schema_diff_report.txt"),
            "Textfiler (*.txt);;Alla filer (*.*)",
        )
        if not path:
            return

        try:
            _atomic_write_text(Path(path), text, encoding="utf-8")
            self._info("Diff", f"Rapport sparad:\n{path}")
        except Exception:
            _log.exception("Kunde inte spara diff-rapport till %s.", path)
            self._error("Diff", "Kunde inte spara diff-rapporten.")

    # -----------------------------------------------------------------
    # Preview / record formatting
    # -----------------------------------------------------------------
    def _load_preview_template(self) -> None:
        post_type = str(self.preview_post_type_combo.currentData() or "")
        spec = self._schemas_by_post_type.get(post_type)
        if spec is None:
            self._warning("Preview", "Ingen posttyp vald.")
            return

        template: Dict[str, Any] = {}
        for field in _iter_fields(spec):
            if _field_required(field):
                template[str(getattr(field, "name", ""))] = ""
        if not template:
            for field in _iter_fields(spec)[:10]:
                template[str(getattr(field, "name", ""))] = ""

        self.preview_input_text.setPlainText(_pretty_json(template))

    def _parse_preview_input(self) -> Optional[Dict[str, Any]]:
        raw = self.preview_input_text.toPlainText().strip()
        if not raw:
            self._warning("Preview", "Ingen input att läsa.")
            return None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                self._warning("Preview", "Input måste vara ett JSON-objekt.")
                return None
            return data
        except Exception:
            _log.exception("Kunde inte tolka preview JSON.")
            self._warning("Preview", "Input är inte giltig JSON.")
            return None

    def _format_preview_record(self) -> None:
        post_type = str(self.preview_post_type_combo.currentData() or "")
        if not post_type:
            self._warning("Preview", "Ingen posttyp vald.")
            return

        data = self._parse_preview_input()
        if data is None:
            return

        try:
            record = self._format_record(post_type, data)
            self.preview_output_text.setPlainText(record)
            self.preview_length_label.setText(f"Radlängd: {len(record)}")

            valid_latin1, invalid_chars = constants_validate_latin1(record)
            if valid_latin1:
                self.preview_latin1_label.setText("Latin-1: OK")
            else:
                self.preview_latin1_label.setText(
                    f"Latin-1: Fel ({', '.join(invalid_chars[:10])})"
                )

            validation_result = self._validate_record(post_type, data)
            validation_text = _format_result_text(validation_result)
            self.preview_validation_text.setPlainText(validation_text)
        except Exception:
            _log.exception("Formatering av preview-record misslyckades.")
            self._error("Preview", "Kunde inte formatera posten.")

    def _validate_preview_record(self) -> None:
        post_type = str(self.preview_post_type_combo.currentData() or "")
        if not post_type:
            self._warning("Preview", "Ingen posttyp vald.")
            return

        data = self._parse_preview_input()
        if data is None:
            return

        try:
            validation_result = self._validate_record(post_type, data)
            validation_text = _format_result_text(validation_result)
            self.preview_validation_text.setPlainText(validation_text)

            record_text = self.preview_output_text.toPlainText()
            if record_text:
                valid_latin1, invalid_chars = constants_validate_latin1(record_text)
                if valid_latin1:
                    self.preview_latin1_label.setText("Latin-1: OK")
                else:
                    self.preview_latin1_label.setText(
                        f"Latin-1: Fel ({', '.join(invalid_chars[:10])})"
                    )
        except Exception:
            _log.exception("Validering av preview-record misslyckades.")
            self._error("Preview", "Kunde inte validera posten.")

    def _copy_preview_output(self) -> None:
        text = self.preview_output_text.toPlainText()
        if not text:
            self._warning("Preview", "Det finns ingen output att kopiera.")
            return
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)
        self._info("Preview", "Output kopierad till urklipp.")

    def _clear_preview(self) -> None:
        self.preview_input_text.clear()
        self.preview_output_text.clear()
        self.preview_validation_text.clear()
        self.preview_length_label.setText("Radlängd: 0")
        self.preview_latin1_label.setText("Latin-1: —")

    # -----------------------------------------------------------------
    # Backup / import / export
    # -----------------------------------------------------------------
    def _create_backup(self) -> None:
        if not self._create_backup_internal():
            self._error("Backup", "Kunde inte skapa backup.")
            return
        self._refresh_backup_and_history()
        self._info("Backup", "Backup skapad.")

    def _restore_selected_backup(self) -> None:
        if not self._backups:
            self._warning("Backup", "Det finns inga backuper att återställa.")
            return

        lines = [line for line in self.backups_text.toPlainText().splitlines() if line.strip()]
        if not lines:
            self._warning("Backup", "Ingen backup vald.")
            return

        backup_id = lines[0]
        if not self._confirm(
            "Återställ backup",
            f"Återställ backup '{backup_id}'?\nDetta kan skriva över befintliga data.",
        ):
            return

        if not self._restore_backup_internal(backup_id):
            self._error("Backup", f"Kunde inte återställa backup '{backup_id}'.")
            return

        self.refresh()
        self._info("Backup", f"Backup '{backup_id}' återställd.")

    def _export_selected_version(self) -> None:
        version = self.version_combo.currentText().strip()
        if not version:
            self._warning("Export", "Ingen version vald.")
            return

        target_dir = QFileDialog.getExistingDirectory(self, "Välj exportkatalog")
        if not target_dir:
            return

        if not self._export_version_to_dir(version, target_dir):
            self._error("Export", f"Kunde inte exportera version '{version}'.")
            return

        self._info("Export", f"Version '{version}' exporterades till:\n{target_dir}")

    def _import_version_from_directory(self) -> None:
        source_dir = QFileDialog.getExistingDirectory(self, "Välj katalog att importera från")
        if not source_dir:
            return

        dialog = VersionDialog(
            self,
            existing_data={
                "version": f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "source_file": source_dir,
                "description": "Importerad version",
            },
            title="Importera version",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        version = dialog.get_data()["version"]
        if version in self._versions:
            self._warning("Import", f"Version '{version}' finns redan.")
            return

        if not self._import_version_from_dir(source_dir, version):
            self._error("Import", f"Kunde inte importera version från:\n{source_dir}")
            return

        self._current_version = version
        self.refresh()
        self._info("Import", f"Version '{version}' importerades.")

    def _export_all_versions(self) -> None:
        target_dir = QFileDialog.getExistingDirectory(self, "Välj exportkatalog för alla versioner")
        if not target_dir:
            return

        if not self._export_all_versions_internal(target_dir):
            self._error("Export", "Kunde inte exportera alla versioner.")
            return

        self._info("Export", f"Alla versioner exporterades till:\n{target_dir}")

    # -----------------------------------------------------------------
    # Diagnostics
    # -----------------------------------------------------------------
    def _load_basic_diagnostics(self) -> None:
        spec = self._get_current_spec()
        diagnostics = {
            "widget_version": VERSION,
            "plugin_class": type(self.plugin).__name__,
            "active_version": self._current_version,
            "version_count": len(self._versions),
            "post_type_count": len(self._schemas_by_post_type),
            "current_post_type": self._current_post_type,
            "field_count_current": len(_iter_fields(spec)) if spec is not None else 0,
            "copyright": _get_copyright_string(),
        }

        try:
            plugin_diag = self._find_callable(self.plugin, "get_diagnostics")
            if plugin_diag is not None:
                diagnostics["plugin_diagnostics"] = _invoke_callable(plugin_diag)
        except Exception:
            _log.exception("plugin.get_diagnostics() misslyckades.")

        self.diagnostics_text.setPlainText(_pretty_json(diagnostics))

    def _load_metadata(self) -> None:
        manager = self._get_manager()
        metadata: Any = None

        try:
            func = self._find_callable(self.plugin, "get_metadata", "metadata")
            if func is not None:
                metadata = _invoke_callable(
                    func,
                    self._current_post_type,
                    version=self._current_version,
                )
        except Exception:
            _log.exception("plugin.get_metadata()/metadata() misslyckades.")

        if metadata is None and manager is not None:
            try:
                func = self._find_callable(manager, "get_version_metadata")
                if func is not None:
                    metadata = _invoke_callable(func, self._current_version)
            except Exception:
                _log.exception("manager.get_version_metadata() misslyckades.")

        if metadata is None:
            spec = self._get_current_spec()
            metadata = _obj_to_dict(spec) if spec is not None else {"message": "Ingen metadata."}

        self.diagnostics_text.setPlainText(_format_result_text(metadata))

    def _load_field_statistics(self) -> None:
        post_type = self._current_post_type or None
        result: Any = None

        try:
            func = self._find_callable(self.plugin, "get_field_statistics", "field_statistics")
            if func is not None:
                if post_type:
                    result = _invoke_callable(func, post_type, version=self._current_version)
                else:
                    result = _invoke_callable(func, version=self._current_version)
        except Exception:
            _log.exception("plugin.get_field_statistics()/field_statistics() misslyckades.")

        if result is None:
            spec = self._get_current_spec()
            if spec is None:
                result = {"message": "Ingen posttyp vald."}
            else:
                fields = _iter_fields(spec)
                by_type: Dict[str, int] = {}
                for field in fields:
                    key = _field_type_text(field)
                    by_type[key] = by_type.get(key, 0) + 1
                result = {
                    "post_type": self._current_post_type,
                    "field_count": len(fields),
                    "required_count": _get_required_field_count(spec),
                    "coverage_percent": _compute_coverage(spec),
                    "field_types": by_type,
                }

        self.diagnostics_text.setPlainText(_format_result_text(result))

    def _load_collaboration_status(self) -> None:
        result: Any = None
        for name in (
            "get_collaboration_status",
            "collaboration_status",
            "get_status",
        ):
            try:
                func = self._find_callable(self.plugin, name)
                if func is not None:
                    result = _invoke_callable(func)
                    break
            except Exception:
                _log.exception("%s() misslyckades.", name)

        if result is None:
            result = {
                "status": "ok",
                "message": "Ingen explicit samarbetsstatus tillgänglig.",
                "active_version": self._current_version,
                "post_types_loaded": len(self._schemas_by_post_type),
            }

        self.diagnostics_text.setPlainText(_format_result_text(result))

    def _load_comprehensive_report(self) -> None:
        result: Any = None
        for name in (
            "get_comprehensive_report",
            "generate_comprehensive_report",
            "comprehensive_report",
        ):
            try:
                func = self._find_callable(self.plugin, name)
                if func is not None:
                    result = _invoke_callable(
                        func,
                        self._current_post_type,
                        version=self._current_version,
                    )
                    break
            except Exception:
                _log.exception("%s() misslyckades.", name)

        if result is None:
            spec = self._get_current_spec()
            result = {
                "active_version": self._current_version,
                "current_post_type": self._current_post_type,
                "post_type_count": len(self._schemas_by_post_type),
                "field_count_current": len(_iter_fields(spec)) if spec is not None else 0,
                "coverage_percent": _compute_coverage(spec) if spec is not None else 0.0,
                "gaps": [_format_gap_item(x) for x in _try_get_gaps(spec)] if spec else [],
                "overlaps": [_format_overlap_item(x) for x in _try_get_overlaps(spec)]
                if spec
                else [],
            }

        self.diagnostics_text.setPlainText(_format_result_text(result))

    def _sync_ts_spec_import(self) -> None:
        for name in ("sync_ts_spec_import", "sync_with_ts_spec_import"):
            try:
                func = self._find_callable(self.plugin, name)
                if func is not None:
                    result = _invoke_callable(func)
                    self.diagnostics_text.setPlainText(_format_result_text(result))
                    self._info("Synk", "Synkronisering genomförd.")
                    self.refresh()
                    return
            except Exception:
                _log.exception("%s() misslyckades.", name)

        self._warning("Synk", "Ingen synkroniseringsfunktion tillgänglig i pluginet.")

    # -----------------------------------------------------------------
    # Public convenience API
    # -----------------------------------------------------------------
    def cleanup(self) -> None:
        self._set_status("Widget stängd.")

    def get_current_version(self) -> str:
        return self._current_version

    def get_current_post_type(self) -> str:
        return self._current_post_type


SchemaManagerWidget = TSSchemaManagerWidget
Widget = TSSchemaManagerWidget

__all__ = [
    "VERSION",
    "AUTHOR",
    "TSSchemaManagerWidget",
    "SchemaManagerWidget",
    "Widget",
    "PostTypesTableModel",
    "FieldsTableModel",
    "HistoryTableModel",
    "VersionDialog",
    "PostTypeDialog",
    "FieldDialog",
]
