# -*- coding: utf-8 -*-
# Fil: plugins/sap_editor/ui/editor_window.py
"""Redigeringsfönster för SAP-data (v1.0.1).

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
    - FIX (KRAV 58): filkommentar "# Fil: plugins/sap_editor/ui/
      editor_window.py" tillagd (saknades).
    - VERSION tillagd (saknades helt — AUTHOR/COPYRIGHT fanns).
    - get_logger() -> _get_logger() (privat, konvention).
    - FIX (tema-konsistens): setObjectName normaliserade mot kodbasens
      design-tokens: pageTitle -> PageTitle, infoLabel -> StatusLabel,
      primaryButton -> PrimaryButton, secondaryButton -> SecondaryButton
      (samma som ts_file_generator/ts_excel_importer-widgetarna).
    - FIX (PySide6-enums, full form): Qt.AlignLeft ->
      Qt.AlignmentFlag.AlignLeft; QLineEdit.Password ->
      QLineEdit.EchoMode.Password; QDialogButtonBox.AcceptRole ->
      QDialogButtonBox.ButtonRole.AcceptRole (och RejectRole).
    - FIX (korrekthet, låst regel): _validate_data() — VIN-kontrollen
      saknade I/O/Q-regeln (teckenuppsättning). Nu: längd 17 +
      inga I/O/Q, konsistent med DataNormalizer/validate_vin och
      sap_import (VIN3-låst regel).
    - FIX (spårbarhet): sap:data_edited-payloaden utökad med
      "edited_at" (ISO-tid) + "source": "sap_editor" — event-mottagare
      kan spåra när/varifrån ändringen kom.
    - tuple[bool, str] -> Tuple[bool, str] (+ import Tuple) för
      konsistens med övriga moduler.
    - Övrig logik OFÖRÄNDRAD (coerce_parent, _get_plugin_safe,
      _verify_password med flera API-varianter, _emit_safe,
      dialog-flöde, validering, centrering).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _get_logger() -> logging.Logger:
    """
    Hämta modul-logger. Kraschsäker fallback om logging ej konfigurerat.

    Returns:
        logging.Logger instans
    """
    try:
        return logging.getLogger("plugins.sap_editor.ui.editor_window")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


def get_copyright_string() -> str:
    """Returnerar dynamisk copyright-sträng."""
    return f"Copyright © {datetime.now().year} Rickard Längkvist"


_log = _get_logger()

VERSION = "1.0.1"
AUTHOR = "Rickard Längkvist"
COPYRIGHT = get_copyright_string()


def _coerce_parent(parent: Any) -> Optional[QWidget]:
    """Försök konvertera parent till QWidget eller använd aktivt fönster."""
    if isinstance(parent, QWidget):
        return parent

    app_instance = QApplication.instance()
    if app_instance is not None:
        active_window = app_instance.activeWindow()
        if isinstance(active_window, QWidget):
            return active_window

    return None


def _get_plugin_safe(app: Any, name: str) -> Any:
    """Hämta plugin på säkert sätt från olika app-strukturer."""
    if app is None:
        return None

    try:
        manager = getattr(app, "plugin_manager", None)
        if manager is not None:
            get_plugin_safe = getattr(manager, "get_plugin_safe", None)
            if callable(get_plugin_safe):
                return get_plugin_safe(name)

            get_plugin = getattr(manager, "get_plugin", None)
            if callable(get_plugin):
                return get_plugin(name)
    except Exception:
        _log.exception("Kunde inte hämta plugin '%s' via plugin_manager", name)

    try:
        app_get_plugin_safe = getattr(app, "get_plugin_safe", None)
        if callable(app_get_plugin_safe):
            return app_get_plugin_safe(name)
    except Exception:
        _log.exception(
            "Kunde inte hämta plugin '%s' via app.get_plugin_safe()",
            name,
        )

    return None


def _verify_password(auth_plugin: Any, password: str) -> bool:
    """Verifiera lösenord via auth-plugin med stöd för flera API-varianter."""
    if auth_plugin is None:
        return False

    candidate_methods = [
        "verify_password",
        "verify",
        "check_password",
        "authenticate",
    ]

    for method_name in candidate_methods:
        method = getattr(auth_plugin, method_name, None)
        if not callable(method):
            continue

        try:
            result = method(password)

            if isinstance(result, tuple):
                return bool(result[0])

            return bool(result)

        except Exception:
            _log.exception(
                "Fel vid lösenordsverifiering via %s.%s()",
                auth_plugin.__class__.__name__,
                method_name,
            )

    _log.warning("Auth-plugin saknar stöd för lösenordsverifiering.")
    return False


def _emit_safe(
    app: Any,
    event_name: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Emittera event säkert mot event bus."""
    if app is None:
        _log.warning("Ingen app tillgänglig för event '%s'", event_name)
        return False

    event_bus = getattr(app, "event_bus", None)
    if event_bus is None:
        _log.warning("Ingen event_bus tillgänglig för event '%s'", event_name)
        return False

    payload = data or {}

    try:
        if hasattr(event_bus, "emit") and callable(event_bus.emit):
            event_bus.emit(event_name, payload)
            return True

        if hasattr(event_bus, "publish") and callable(event_bus.publish):
            event_bus.publish(event_name, payload)
            return True

        _log.warning(
            "Event bus saknar både 'emit' och 'publish' för event '%s'",
            event_name,
        )
        return False

    except Exception:
        _log.exception("Kunde inte emittera event '%s'", event_name)
        return False


class SapEditorWindow(QDialog):
    """Dialog för redigering av SAP-data."""

    FIELD_DEFINITIONS = [
        ("Namn", "name"),
        ("Fabrikat 0.1", "fabrikat"),
        ("Gruppnr", "gruppnr"),
        ("Modell", "modell"),
        ("Variant", "variant"),
        ("Version", "version"),
        ("Färg", "farg"),
        ("Årsmodell", "arsmodell"),
        ("ETG", "etg"),
        ("VIN", "vin"),
    ]

    def __init__(
        self,
        parent: Optional[QWidget],
        app: Any,
        existing_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initiera dialogen."""
        super().__init__(parent)

        self.app = app
        self.parent_widget = parent
        self.existing_data = existing_data or {}
        self.entries: Dict[str, QLineEdit] = {}

        self.setObjectName("sapEditorDialog")
        self.setWindowTitle("🔧 Redigera SAP-data")
        self.setModal(True)
        self.resize(640, 520)
        self.setMinimumSize(560, 460)
        self.setSizeGripEnabled(False)

        self.button_box: Optional[QDialogButtonBox] = None
        self.save_button: Optional[QWidget] = None
        self.cancel_button: Optional[QWidget] = None

        self._setup_ui()
        self._populate_existing_data()
        self._center_on_parent()

    def _setup_ui(self) -> None:
        """Bygg dialogens UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        header_layout = QVBoxLayout()
        header_layout.setSpacing(6)

        title_label = QLabel("Redigera SAP-data")
        title_label.setObjectName("PageTitle")
        title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        title_label.setWordWrap(True)

        info_label = QLabel(
            "Uppdatera fälten nedan och klicka på Spara för att skicka "
            "ändringarna vidare via event-bussen."
        )
        info_label.setObjectName("StatusLabel")
        info_label.setWordWrap(True)

        header_layout.addWidget(title_label)
        header_layout.addWidget(info_label)
        main_layout.addLayout(header_layout)

        form_container = QWidget(self)
        form_container.setObjectName("formContainer")

        form_layout = QFormLayout(form_container)
        form_layout.setContentsMargins(8, 8, 8, 8)
        form_layout.setSpacing(10)
        form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        form_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        for label_text, key in self.FIELD_DEFINITIONS:
            label = QLabel(label_text)
            label.setObjectName(f"label_{key}")
            label.setWordWrap(True)

            entry = QLineEdit()
            entry.setObjectName(f"entry_{key}")
            entry.setClearButtonEnabled(True)
            entry.setMinimumWidth(320)
            entry.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )

            if key == "vin":
                entry.setMaxLength(17)

            form_layout.addRow(label, entry)
            self.entries[key] = entry

        main_layout.addWidget(form_container)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.button_box = QDialogButtonBox(self)
        self.button_box.setObjectName("buttonBox")

        self.save_button = self.button_box.addButton(
            "💾 Spara",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.cancel_button = self.button_box.addButton(
            "❌ Avbryt",
            QDialogButtonBox.ButtonRole.RejectRole,
        )

        self.save_button.setObjectName("PrimaryButton")
        self.cancel_button.setObjectName("SecondaryButton")

        self.button_box.accepted.connect(self._save)
        self.button_box.rejected.connect(self.reject)

        button_row.addWidget(self.button_box)
        main_layout.addLayout(button_row)

    def _populate_existing_data(self) -> None:
        """Fyll i befintliga värden om sådana finns."""
        for _, key in self.FIELD_DEFINITIONS:
            value = self.existing_data.get(key, "")
            self.entries[key].setText("" if value is None else str(value))

    def _collect_data(self) -> Dict[str, str]:
        """Samla in formulärdata."""
        data: Dict[str, str] = {}

        for _, key in self.FIELD_DEFINITIONS:
            value = self.entries[key].text().strip()
            if key == "vin":
                value = value.upper()
            data[key] = value

        return data

    def _validate_data(self, data: Dict[str, str]) -> Tuple[bool, str]:
        """Validera användarens inmatning."""
        vin = data.get("vin", "").strip()
        arsmodell = data.get("arsmodell", "").strip()

        if vin:
            if len(vin) != 17:
                return False, "VIN måste vara exakt 17 tecken om det anges."
            if any(c in vin for c in "IOQ"):
                return (
                    False,
                    "VIN får inte innehålla tecknen I, O eller Q.",
                )

        if arsmodell and not arsmodell.isdigit():
            return False, "Årsmodell måste vara numerisk om den anges."

        if arsmodell and len(arsmodell) != 4:
            return False, "Årsmodell måste bestå av 4 siffror."

        return True, ""

    def _save(self) -> None:
        """Spara ändringar och emittera event."""
        data = self._collect_data()
        is_valid, error_message = self._validate_data(data)

        if not is_valid:
            QMessageBox.warning(self, "Ogiltiga värden", error_message)
            return

        # Spårbarhet: tid + källa (FIX v1.0.1)
        payload = dict(data)
        payload["edited_at"] = datetime.now().isoformat(timespec="seconds")
        payload["source"] = "sap_editor"

        event_success = _emit_safe(self.app, "sap:data_edited", payload)
        if not event_success:
            QMessageBox.critical(
                self,
                "Fel",
                "Kunde inte spara SAP-data eftersom event-bussen inte svarade.",
            )
            return

        _log.info("SAP-data sparad via sap:data_edited: %s", payload)

        QMessageBox.information(
            self,
            "✅ Sparat",
            "SAP-data har sparats.",
        )
        self.accept()

    def _center_on_parent(self) -> None:
        """Centrera dialogen relativt parent om möjligt."""
        if self.parent_widget is None:
            return

        try:
            parent_geometry = self.parent_widget.frameGeometry()
            dialog_geometry = self.frameGeometry()
            dialog_geometry.moveCenter(parent_geometry.center())
            self.move(dialog_geometry.topLeft())
        except Exception:
            _log.debug("Kunde inte centrera SapEditorWindow", exc_info=True)


def show_sap_editor(
    parent: Any,
    app: Any,
    existing_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Visa SAP-redigeringsfönstret med lösenordskontroll."""
    parent_widget = _coerce_parent(parent)

    auth = _get_plugin_safe(app, "core_auth")
    if auth is None:
        QMessageBox.critical(parent_widget, "Fel", "Auth-plugin saknas.")
        _log.error("Auth-plugin saknas vid öppning av SAP Editor.")
        return False

    password, ok = QInputDialog.getText(
        parent_widget,
        "Lösenord",
        "Ange lösenord för att redigera SAP-data:",
        QLineEdit.EchoMode.Password,
    )

    if not ok:
        _log.info("SAP Editor avbröts innan lösenord verifierades.")
        return False

    if not _verify_password(auth, password):
        QMessageBox.critical(parent_widget, "Fel", "Felaktigt lösenord.")
        _log.warning("Felaktigt lösenord vid försök att öppna SAP Editor.")
        return False

    dialog = SapEditorWindow(parent_widget, app, existing_data=existing_data)
    result = dialog.exec()

    opened_and_saved = result == QDialog.DialogCode.Accepted
    if opened_and_saved:
        _log.info("SAP Editor stängdes efter lyckad sparning.")
    else:
        _log.info("SAP Editor stängdes utan sparning.")

    return opened_and_saved
