# -*- coding: utf-8 -*-
# Fil: plugins/dispatch_viewer/plugin.py

"""
Dispatch Viewer Plugin v3.1.1 (PySide6)

Visa dispatch-data från Excel-filer med integration mot TS-scheman.

ANSVAR:
  - Ladda och visa dispatch-data från Excel-filer
  - Robust rubrikdetektering med alias
  - Export till CSV/Excel med preamble
  - Sök och sortering
  - Data-API för data_mapping plugin
  - Schema-aware fältvalidering
  - VIN-validering
  - Event-driven kommunikation med andra plugins

IMPORTER (EXTERNA):
  csv, re, datetime, pathlib, typing
  PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets (VALFRITT —
  try/except + HAS_PYSIDE6; klasser definieras villkorligt)
  core.plugin_base (PluginBase)
  pandas (valfri, kontrolleras vid runtime)

PUBLIKT API:
  get_imported_records()      -> List[Dict]
  get_vin_column_name()       -> str
  get_column_mapping()        -> Dict[str, str]
  get_vin_list()              -> List[str]
  get_record_by_vin(vin)      -> Optional[Dict]
  load_file(filepath)         -> bool
  list_dispatch_files()       -> List[Path]
  get_current_data()          -> Optional[DataFrame]
  get_current_filename()      -> Optional[str]
  get_statistics()            -> Dict[str, Any]
  validate_vin(vin)           -> Dict[str, Any]
  validate_all_vins()         -> Dict[str, Any]
  export_to_csv(df)           -> Optional[Path]
  export_to_excel(df)         -> Optional[Path]

EVENTS SOM EMITTAS:
  dispatch:file_loaded  — när en fil laddats

LYSSNAR PÅ:
  dispatch:refresh, dispatch:load_file, schema:version_changed

SAMARBETAR MED:
  data_mapping, ts_schema_manager, vehicle_registry

FÖRÄNDRINGAR v3.1.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (KRAV 58): "# Fil:"-prefix tillagt (stod bara
    "# plugins/dispatch_viewer/plugin.py").
  - FIX (headless, låst mönster): PySide6-importen på toppnivån
    flyttad till try/except + HAS_PYSIDE6; DispatchTableModel +
    DispatchWidget definieras VILLKORLIGT (if HAS_PYSIDE6);
    register_ui()/create_widget() returnerar None utan PySide6.
    Originalet kraschade vid import i headless/test.
  - FIX (låst regel): _setup_logger() med StreamHandler BORT (störde
    appens loggning — setup sköts av core/logger_setup); _log =
    logging.getLogger("dispatch_viewer") direkt.
  - FIX (livscykel, korrekthet): activate() anropar super().activate()
    (originalet var "pass" — is_active sattes aldrig); shutdown()
    anropar super().deactivate() + _shutdown_done (idempotent —
    PluginBase.shutdown() anropar polymorft self.deactivate() →
    ömsesidig rekursion om super().shutdown() används); deactivate()
    = bakåtkompatibel delegat.
  - FIX (headless-export): export_to_csv/export_to_excel visade
    QFileDialog/QMessageBox oavsett PySide6 — utan GUI skrivs nu
    till ut/-katalogen med default-namn (dialogen visas bara när
    PySide6 finns); API:et fungerar headless.
  - FIX (konsistens): get_plugin_safe utökad med plugin_manager
    (legacy, metod 3 — 4-metoders-kedjan som identity_post);
    _setup_paths med base_dir → config.base_dir → cwd-fallback;
    publik get_copyright_string() + privat alias
    _get_copyright_string (i __all__); VERSION/AUTHOR modulnivå
    (fanns redan) + HAS_PYSIDE6 i __all__.
  - FIX (radbrytningsartefakt): dubblerade blankrader före
    def/class kollapsade till max 1 (transport-artefakt).
  - Övrig logik OFÖRÄNDRAD (alias-matchning, rubrikdetektering
    strategi 1/2/fallback, QTableView + QAbstractTableModel +
    QSortFilterProxyModel, ScrollPerPixel, setWordWrap(True) via
    Python, setObjectName-tokens, _set_bold, datum/modellår-
    normalisering, VIN-validering, preamble, data-API).
FÖRÄNDRINGAR v3.1.0:
  - AUTHOR → "Rickard Längkvist" (BUGG #5)
  - print() → module-level _log (FÖRBJUDET: print())
  - QTableWidget → QTableView + QAbstractTableModel (SPEC)
  - Alla hårdkodade färger → setObjectName() (SPEC)
  - ScrollPerPixel mushjulstöd (SPEC)
  - setWordWrap(True) via Python (SPEC)
  - _set_bold() på alla knappar (SPEC)
  - config_schema() tillagd (PluginBase kontrakt)
  - init/register_ui/shutdown kontrakt (PluginBase)
  - Dynamisk copyright
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple

# PySide6 (valfritt — kraschsäkert headless; klasserna definieras
# villkorligt nedan, samma mönster som ereko/gui_helpers).
try:
    from PySide6.QtCore import (
        QAbstractTableModel,
        QModelIndex,
        QSortFilterProxyModel,
        Qt,
        QTimer,
    )
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QFileDialog,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QTableView,
        QVBoxLayout,
        QWidget,
    )
    HAS_PYSIDE6: bool = True
except ImportError:
    HAS_PYSIDE6: bool = False

from core.plugin_base import PluginBase

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "3.1.1"
AUTHOR: Final[str] = "Rickard Längkvist"
PLUGIN_NAME: Final[str] = "Dispatch Viewer"

PANDAS_AVAILABLE: bool = False
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore[assignment]

def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# Bakåtkompatibilitet: privat alias.
_get_copyright_string = get_copyright_string


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_log: logging.Logger = logging.getLogger("dispatch_viewer")


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _set_bold(widget: Any) -> None:
    """Sätt fet text på widget. Kraschsäker."""
    try:
        font = widget.font()
        font.setBold(True)
        widget.setFont(font)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN HELPERS (kraschsäkra)
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """Robust plugin-hämtning. KRASCHSÄKER."""
    if app is None:
        return None
    normalized = name.lower().replace(" ", "_").replace("-", "_")
    for try_name in (name, normalized):
        try:
            gp = getattr(app, "get_plugin", None)
            if callable(gp):
                p = gp(try_name)
                if p is not None:
                    return p
        except Exception:
            pass
        try:
            loader = getattr(app, "plugin_loader", None)
            if loader and hasattr(loader, "get_plugin"):
                p = loader.get_plugin(try_name)
                if p is not None:
                    return p
        except Exception:
            pass
        try:
            manager = getattr(app, "plugin_manager", None)
            if manager and hasattr(manager, "get_plugin"):
                p = manager.get_plugin(try_name)
                if p is not None:
                    return p
        except Exception:
            pass
    try:
        attr_name = name.replace("-", "_").lower()
        if hasattr(app, attr_name):
            return getattr(app, attr_name)
    except Exception:
        pass
    return None

def emit_event_safe(
    app: Any, event_name: str, data: Optional[Dict[str, Any]] = None
) -> bool:
    """Emit event säkert. KRASCHSÄKER."""
    if app is None:
        return False
    try:
        bus = getattr(app, "event_bus", None)
        if bus is None:
            return False
        for method in ("emit", "publish"):
            func = getattr(bus, method, None)
            if func is not None:
                func(event_name, data or {})
                return True
    except Exception as exc:
        _log.debug("Event emit misslyckades '%s': %s", event_name, exc)
    return False

def subscribe_event_safe(
    app: Any, event_name: str, handler: Any
) -> bool:
    """Prenumerera på event säkert. KRASCHSÄKER."""
    try:
        bus = getattr(app, "event_bus", None) if app else None
        if bus is None:
            return False
        for method in ("on", "subscribe"):
            func = getattr(bus, method, None)
            if func is not None:
                func(event_name, handler)
                return True
    except Exception as exc:
        _log.debug(
            "Prenumeration misslyckades '%s': %s", event_name, exc
        )
    return False

def unsubscribe_event_safe(
    app: Any, event_name: str, handler: Any
) -> bool:
    """Avprenumerera event säkert. KRASCHSÄKER."""
    try:
        bus = getattr(app, "event_bus", None) if app else None
        if bus is None:
            return False
        for method in ("off", "unsubscribe"):
            func = getattr(bus, method, None)
            if func is not None:
                func(event_name, handler)
                return True
    except Exception as exc:
        _log.debug(
            "Avprenumeration misslyckades '%s': %s", event_name, exc
        )
    return False


# ══════════════════════════════════════════════════════════════════════════════
# KONSTANTER — KOLUMNALIAS
# ══════════════════════════════════════════════════════════════════════════════

COLUMN_ALIASES: Final[Dict[str, List[str]]] = {
    "VIN": [
        "VIN", "VIN CODE", "VINNUMBER",
        "VEHICLE IDENTIFICATION NUMBER",
        "CHASSIS", "CHASSIS NUMBER", "VIN NO", "VEHICLEID",
        "VEHICLE_ID", "VINCODE", "CHASSINUMMER", "CHASSI",
    ],
    "Model Year": [
        "MODEL YEAR", "MY", "YEAR", "ÅRSMODELL",
        "MODEL-YEAR", "MODELYEAR", "MODELLÅR", "ARSMODELL",
    ],
    "Approval": [
        "APPROVAL", "ETG", "WVTA", "CERTIFICATE", "CERT NO",
        "CERTIFICATE NO", "TYPE APPROVAL", "TYPGODKÄNNANDE",
        "GODKÄNNANDE",
    ],
    "Invoice Date": [
        "INVOICE DATE", "FAKTURADATUM", "INVDATE", "INVOICE",
        "FAKTDATUM",
    ],
    "Actual Production Date": [
        "ACTUAL PRODUCTION DATE", "PRODUKTIONSDATUM", "PRODDATE",
        "PRODUCTION DATE", "TILLVERKNINGSDATUM",
    ],
    "Sold to Dealer": [
        "SOLD TO DEALER", "CUSTOMER NUMBER", "DEALER ID", "DN",
        "KUNDNUMMER", "CUSTOMER_NUMBER", "ÅTERFÖRSÄLJARE", "DEALER",
    ],
    "Dealer Name": [
        "DEALER NAME", "SOLD TO NAME", "KUNDNAMN",
        "CUSTOMER NAME", "ÅTERFÖRSÄLJARNAMN", "DEALERNAME",
    ],
    "Color": [
        "COLOR", "COLOUR", "FÄRG", "FARG", "FÄRGKOD",
        "COLORCODE",
    ],
    "Model": [
        "MODEL", "MODELL", "MODEL NAME", "MODELLNAMN",
        "HANDELSBETECKNING",
    ],
    "Engine": [
        "ENGINE", "MOTOR", "MOTORTYP", "ENGINE TYPE",
    ],
}

# Blad att hoppa över
SKIP_SHEETS: Final[List[str]] = [
    "pow 2", "template", "mall", "info", "instructions",
]

# VIN-validering
VIN_PATTERN: Final[re.Pattern] = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


# ══════════════════════════════════════════════════════════════════════════════
# TABLE MODEL
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class DispatchTableModel(QAbstractTableModel):
        """
        Qt Table Model för dispatch-data.

        Ersätter QTableWidget för bättre prestanda vid >100 rader.
        Stöder QSortFilterProxyModel för sökning och sortering.
        """

        def __init__(
            self, parent: Optional[QWidget] = None
        ) -> None:
            super().__init__(parent)
            self._headers: List[str] = []
            self._rows: List[List[str]] = []

        def set_data(
            self, headers: List[str], rows: List[List[str]]
        ) -> None:
            """Ersätt all data och notifiera vyn."""
            self.beginResetModel()
            self._headers = list(headers)
            self._rows = list(rows)
            self.endResetModel()

        def clear(self) -> None:
            """Rensa all data."""
            self.beginResetModel()
            self._headers = []
            self._rows = []
            self.endResetModel()

        def rowCount(
            self, parent: QModelIndex = QModelIndex()
        ) -> int:
            if parent.isValid():
                return 0
            return len(self._rows)

        def columnCount(
            self, parent: QModelIndex = QModelIndex()
        ) -> int:
            if parent.isValid():
                return 0
            return len(self._headers)

        def headerData(
            self,
            section: int,
            orientation: Qt.Orientation,
            role: int = Qt.ItemDataRole.DisplayRole,
        ) -> Any:
            if role != Qt.ItemDataRole.DisplayRole:
                return None
            if (
                orientation == Qt.Orientation.Horizontal
                and 0 <= section < len(self._headers)
            ):
                return self._headers[section]
            if orientation == Qt.Orientation.Vertical:
                return section + 1
            return None

        def data(
            self,
            index: QModelIndex,
            role: int = Qt.ItemDataRole.DisplayRole,
        ) -> Any:
            if not index.isValid():
                return None
            row = index.row()
            col = index.column()
            if row < 0 or row >= len(self._rows):
                return None
            row_data = self._rows[row]
            if col < 0 or col >= len(row_data):
                return None
            if role == Qt.ItemDataRole.DisplayRole:
                value = row_data[col]
                if value.lower() in ("nan", "none", "nat"):
                    return ""
                return value
            if role == Qt.ItemDataRole.ToolTipRole:
                header = (
                    self._headers[col]
                    if col < len(self._headers)
                    else "Kolumn %d" % col
                )
                return "%s: %s" % (header, row_data[col])
            return None


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN-KLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    Dispatch Viewer Plugin v3.1.1 (PySide6)

    Visar och exporterar dispatch-data från Excel-filer.
    Tillhandahåller data-API för data_mapping plugin.
    Integrerar med ts_schema_manager för fältvalidering.

    KONTRAKT (PluginBase):
      init()              - initiera plugin, sätt upp sökvägar
      register_ui(parent) - skapa och returnera DispatchWidget
      shutdown()          - städa upp
      config_schema()     - returnera konfigurationsschema
    """

    NAME: Final[str] = PLUGIN_NAME
    VERSION: Final[str] = VERSION
    DESCRIPTION: Final[str] = (
        "Visa och exportera dispatch-data med schema-integration"
    )
    AUTHOR: Final[str] = AUTHOR
    DEPENDENCIES: Final[List[str]] = []

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._paths: Dict[str, Path] = {}
        self._widget: Optional[Any] = None
        self._current_data: Any = None  # pd.DataFrame or None
        self._current_file: Optional[str] = None
        self._vin_column_name: str = "VIN"
        self._column_mapping: Dict[str, str] = {}
        self._event_handlers: List[Tuple[str, Any]] = []
        self._shutdown_done: bool = False

    # ──────────────────────────────────────────────────────────────────────
    # PLUGINBASE KONTRAKT
    # ──────────────────────────────────────────────────────────────────────

    def init(self) -> None:
        """Initiera plugin. KRASCHSÄKER."""
        try:
            if not PANDAS_AVAILABLE:
                _log.warning(
                    "%s: pandas krävs (pip install pandas openpyxl)",
                    PLUGIN_NAME,
                )

            self._setup_paths()
            self._register_events()

            # Registrera i app (bakåtkompatibilitet)
            try:
                self.app.dispatch_tab = self
            except Exception:
                pass

            _log.info(
                "✅ %s v%s initierad", PLUGIN_NAME, VERSION,
            )
            _log.info(
                "   📁 Dispatch: %s",
                self._paths.get("dispatch", "N/A"),
            )
        except Exception as exc:
            _log.error(
                "Initiering av %s misslyckades: %s",
                PLUGIN_NAME, exc, exc_info=True,
            )

    def register_ui(
        self, parent: Optional[QWidget] = None
    ) -> Optional[Any]:
        """Skapa och returnera widget. KRASCHSÄKER (None headless)."""
        if not HAS_PYSIDE6:
            _log.debug("PySide6 saknas — ingen dispatch-widget.")
            return None
        try:
            self._widget = DispatchWidget(parent, self.app, self)
            return self._widget
        except Exception as exc:
            _log.error(
                "Widget-skapande misslyckades: %s", exc, exc_info=True,
            )
            return None

    def shutdown(self) -> None:
        """Städa upp resurser. KRASCHSÄKER (idempotent)."""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        try:
            for event_name, handler in self._event_handlers:
                unsubscribe_event_safe(self.app, event_name, handler)
            self._event_handlers.clear()
            self._widget = None
            _log.info("%s stängd.", PLUGIN_NAME)
        except Exception as exc:
            _log.error(
                "Shutdown av %s misslyckades: %s",
                PLUGIN_NAME, exc, exc_info=True,
            )
        finally:
            # PluginBase-livscykel: state → INACTIVE + cleanup.
            try:
                super().deactivate()
            except Exception:
                _log.exception(
                    "PluginBase.deactivate misslyckades för %s",
                    PLUGIN_NAME,
                )

    def config_schema(self) -> Dict[str, Any]:
        """Returnera konfigurationsschema. PluginBase kontrakt."""
        return {
            "plugin": PLUGIN_NAME,
            "version": VERSION,
            "author": AUTHOR,
            "copyright": get_copyright_string(),
            "settings": {
                "dispatch_dir": str(
                    self._paths.get("dispatch", "dispatch")
                ),
                "pandas_available": PANDAS_AVAILABLE,
            },
        }

    # ──────────────────────────────────────────────────────────────────────
    # BAKÅTKOMPATIBILITET (create_widget för main_gui)
    # ──────────────────────────────────────────────────────────────────────

    def create_widget(
        self, parent: Optional[QWidget] = None
    ) -> Optional[Any]:
        """Skapa widget för main_gui. Delegerar till register_ui."""
        return self.register_ui(parent)

    def initialize(self) -> None:
        """Bakåtkompatibel init. Delegerar till init()."""
        self.init()

    def activate(self) -> None:
        """Aktivera plugin (is_active via PluginBase)."""
        try:
            super().activate()
        except Exception:
            _log.exception("PluginBase.activate misslyckades.")
        _log.debug("%s aktiverad", PLUGIN_NAME)

    def deactivate(self) -> None:
        """Bakåtkompatibel deactivate. Delegerar till shutdown()."""
        self.shutdown()

    # ──────────────────────────────────────────────────────────────────────
    # INTERN SETUP
    # ──────────────────────────────────────────────────────────────────────

    def _setup_paths(self) -> None:
        """Konfigurera sökvägar. KRASCHSÄKER."""
        # base_dir → app.config.base_dir → cwd
        base_dir = Path(".")
        if self.app is not None:
            attr_base = getattr(self.app, "base_dir", None)
            if attr_base:
                base_dir = Path(str(attr_base))
            elif hasattr(self.app, "config"):
                try:
                    cfg = self.app.config
                    if hasattr(cfg, "get"):
                        base_dir = Path(str(cfg.get("base_dir", ".")))
                    elif isinstance(cfg, dict):
                        base_dir = Path(
                            str(cfg.get("base_dir", "."))
                        )
                except Exception:
                    pass

        # Hitta dispatch-mapp (case-insensitive)
        dispatch_dir = base_dir / "dispatch"
        if not dispatch_dir.exists():
            for alt_name in ["Dispatch", "DISPATCH", "dispatches"]:
                alt = base_dir / alt_name
                if alt.exists():
                    dispatch_dir = alt
                    break

        dispatch_dir.mkdir(parents=True, exist_ok=True)

        self._paths = {
            "base": base_dir,
            "dispatch": dispatch_dir,
            "ut": base_dir / "ut",
        }

    def _register_events(self) -> None:
        """Registrera event handlers. KRASCHSÄKER."""
        events = [
            ("dispatch:refresh", self._on_refresh),
            ("dispatch:load_file", self._on_load_file),
            ("schema:version_changed", self._on_schema_changed),
        ]
        for event_name, handler in events:
            if subscribe_event_safe(self.app, event_name, handler):
                self._event_handlers.append((event_name, handler))

    def _on_refresh(self, data: Optional[Dict] = None) -> None:
        """Uppdatera data."""
        if self._widget:
            self._widget.refresh()

    def _on_load_file(self, data: Optional[Dict] = None) -> None:
        """Ladda specifik fil."""
        if data and "filepath" in data:
            self.load_file(data["filepath"])

    def _on_schema_changed(self, data: Optional[Dict] = None) -> None:
        """Hantera schema-ändring."""
        self._update_column_mapping_from_schema()

    def _update_column_mapping_from_schema(self) -> None:
        """Uppdatera kolumnmappning från TS-schema. KRASCHSÄKER."""
        try:
            schema_mgr = get_plugin_safe(
                self.app, "ts_schema_manager"
            )
            if not schema_mgr:
                return
            schema = schema_mgr.get_schema("45")
            if schema and hasattr(schema, "fields"):
                for field in schema.fields:
                    if hasattr(field, "name"):
                        _log.debug(
                            "Schema-fält: %s", field.name,
                        )
        except Exception as exc:
            _log.debug("Schema-mappning misslyckades: %s", exc)

    # ──────────────────────────────────────────────────────────────────────
    # PUBLIKT API (används av data_mapping)
    # ──────────────────────────────────────────────────────────────────────

    def get_imported_records(self) -> List[Dict[str, Any]]:
        """Returnerar importerade poster som dict-lista. KRASCHSÄKER."""
        try:
            if self._current_data is None or self._current_data.empty:
                return []
            return self._current_data.to_dict("records")
        except Exception as exc:
            _log.error("get_imported_records misslyckades: %s", exc)
            return []

    def get_vin_column_name(self) -> str:
        """Returnerar namnet på VIN-kolumnen."""
        return self._vin_column_name

    def get_column_mapping(self) -> Dict[str, str]:
        """Returnerar mappning från dispatch-kolumner till standardnamn."""
        return self._column_mapping.copy()

    def get_vin_list(self) -> List[str]:
        """Returnerar lista med alla VIN-nummer. KRASCHSÄKER."""
        try:
            if self._current_data is None or self._current_data.empty:
                return []
            vin_col = self._vin_column_name
            if vin_col not in self._current_data.columns:
                return []
            return (
                self._current_data[vin_col].dropna().unique().tolist()
            )
        except Exception as exc:
            _log.error("get_vin_list misslyckades: %s", exc)
            return []

    def get_record_by_vin(
        self, vin: str
    ) -> Optional[Dict[str, Any]]:
        """Hämta post för specifikt VIN. KRASCHSÄKER."""
        try:
            if self._current_data is None or self._current_data.empty:
                return None
            vin_col = self._vin_column_name
            if vin_col not in self._current_data.columns:
                return None
            vin = vin.strip().upper()
            matches = self._current_data[
                self._current_data[vin_col].str.upper() == vin
            ]
            if matches.empty:
                return None
            return matches.iloc[0].to_dict()
        except Exception as exc:
            _log.error("get_record_by_vin misslyckades: %s", exc)
            return None

    def load_file(self, filepath: str) -> bool:
        """Ladda en specifik dispatch-fil. KRASCHSÄKER."""
        try:
            path = Path(filepath)
            if not path.exists():
                _log.error("Fil saknas: %s", filepath)
                return False
            df = self._load_dispatch_file(path)
            if df is None or df.empty:
                return False
            self._current_data = df
            self._current_file = path.name
            if self._widget:
                self._widget.set_data(df, path.name)
            emit_event_safe(self.app, "dispatch:file_loaded", {
                "filename": path.name,
                "rows": len(df),
                "columns": list(df.columns),
                "vin_count": len(self.get_vin_list()),
            })
            return True
        except Exception as exc:
            _log.error(
                "load_file misslyckades: %s", exc, exc_info=True
            )
            return False

    def list_dispatch_files(self) -> List[Path]:
        """Listar alla dispatch-filer. KRASCHSÄKER."""
        try:
            dispatch_dir = self._paths.get("dispatch")
            if not dispatch_dir or not dispatch_dir.exists():
                return []
            files = (
                list(dispatch_dir.glob("*.xlsx"))
                + list(dispatch_dir.glob("*.xls"))
            )
            return sorted(
                files, key=lambda p: p.stat().st_mtime, reverse=True
            )
        except Exception as exc:
            _log.error("list_dispatch_files misslyckades: %s", exc)
            return []

    def get_current_data(self) -> Any:
        """Returnerar aktuell DataFrame."""
        return self._current_data

    def get_current_filename(self) -> Optional[str]:
        """Returnerar aktuellt filnamn."""
        return self._current_file

    def get_statistics(self) -> Dict[str, Any]:
        """Returnerar statistik för aktuell data. KRASCHSÄKER."""
        try:
            if self._current_data is None or self._current_data.empty:
                return {"loaded": False, "rows": 0, "columns": 0}
            df = self._current_data
            stats: Dict[str, Any] = {
                "loaded": True,
                "filename": self._current_file,
                "rows": len(df),
                "columns": len(df.columns),
                "vin_count": len(self.get_vin_list()),
            }
            if "Model Year" in df.columns:
                years = df["Model Year"].dropna().unique().tolist()
                stats["model_years"] = sorted(
                    [str(y) for y in years if str(y).isdigit()]
                )
            if "Color" in df.columns:
                stats["color_count"] = df["Color"].nunique()
            return stats
        except Exception as exc:
            _log.error("get_statistics misslyckades: %s", exc)
            return {"loaded": False, "rows": 0, "columns": 0}

    # ──────────────────────────────────────────────────────────────────────
    # VALIDERING
    # ──────────────────────────────────────────────────────────────────────

    def validate_vin(self, vin: str) -> Dict[str, Any]:
        """Validera ett VIN-nummer. KRASCHSÄKER."""
        if not vin:
            return {"valid": False, "error": "VIN saknas", "vin": ""}
        vin = vin.strip().upper()
        if len(vin) != 17:
            return {
                "valid": False,
                "error": "VIN måste vara 17 tecken (är %d)"
                % len(vin),
                "vin": vin,
            }
        if not VIN_PATTERN.match(vin):
            return {
                "valid": False,
                "error": "VIN innehåller ogiltiga tecken "
                "(I, O, Q ej tillåtna)",
                "vin": vin,
            }
        return {"valid": True, "error": None, "vin": vin}

    def validate_all_vins(self) -> Dict[str, Any]:
        """Validera alla VIN i aktuell data. KRASCHSÄKER."""
        try:
            vins = self.get_vin_list()
            valid = []
            invalid = []
            for vin in vins:
                result = self.validate_vin(vin)
                if result["valid"]:
                    valid.append(vin)
                else:
                    invalid.append({
                        "vin": vin,
                        "error": result["error"],
                    })
            return {
                "valid_count": len(valid),
                "invalid_count": len(invalid),
                "invalid_vins": invalid,
                "total": len(vins),
            }
        except Exception as exc:
            _log.error("validate_all_vins misslyckades: %s", exc)
            return {
                "valid_count": 0,
                "invalid_count": 0,
                "invalid_vins": [],
                "total": 0,
            }

    # ──────────────────────────────────────────────────────────────────────
    # EXPORT
    # ──────────────────────────────────────────────────────────────────────

    def _export_dialog_path(
        self, default_name: str, file_filter: str
    ) -> Optional[Path]:
        """Visa spara-dialog (eller default ut/-sökväg headless)."""
        if not HAS_PYSIDE6:
            # Headless: skriv till ut/-katalogen med default-namn.
            ut_dir = self._paths.get("ut", Path("ut"))
            try:
                ut_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            return ut_dir / default_name
        filepath, _ = QFileDialog.getSaveFileName(
            None,
            "Exportera",
            default_name,
            file_filter,
        )
        if not filepath:
            return None
        return Path(filepath)

    def export_to_csv(self, df: Any = None) -> Optional[Path]:
        """Exportera till CSV med preamble. KRASCHSÄKER."""
        if df is None:
            df = self._current_data
        if df is None or df.empty:
            if HAS_PYSIDE6:
                QMessageBox.warning(
                    None, "Ingen data", "Ingen data att exportera"
                )
            _log.warning("CSV-export: ingen data att exportera.")
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = "dispatch_export_%s.csv" % timestamp
        out_path = self._export_dialog_path(
            default_name,
            "CSV-filer (*.csv);;Alla filer (*.*)",
        )
        if out_path is None:
            return None
        try:
            with open(
                out_path, "w", encoding="utf-8-sig", newline=""
            ) as f:
                writer = csv.writer(f, delimiter=";")
                preamble = self._create_preamble(out_path)
                for line in preamble:
                    f.write("# %s\n" % line)
                cols = [
                    c for c in df.columns if not c.startswith("_")
                ]
                writer.writerow(cols)
                for _, row in df.iterrows():
                    writer.writerow([row.get(c, "") for c in cols])
            _log.info("Exporterade CSV: %s", out_path.name)
            if HAS_PYSIDE6:
                QMessageBox.information(
                    None, "Export",
                    "Exporterade till:\n%s" % out_path.name,
                )
            return out_path
        except Exception as exc:
            _log.error(
                "CSV-export fel: %s", exc, exc_info=True
            )
            if HAS_PYSIDE6:
                QMessageBox.critical(
                    None, "Fel", "Kunde inte exportera:\n%s" % exc
                )
            return None

    def export_to_excel(self, df: Any = None) -> Optional[Path]:
        """Exportera till Excel. KRASCHSÄKER."""
        if df is None:
            df = self._current_data
        if df is None or df.empty:
            if HAS_PYSIDE6:
                QMessageBox.warning(
                    None, "Ingen data", "Ingen data att exportera"
                )
            _log.warning("Excel-export: ingen data att exportera.")
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = "dispatch_export_%s.xlsx" % timestamp
        out_path = self._export_dialog_path(
            default_name,
            "Excel-filer (*.xlsx);;Alla filer (*.*)",
        )
        if out_path is None:
            return None
        try:
            cols = [c for c in df.columns if not c.startswith("_")]
            df_export = df[cols]
            df_export.to_excel(
                out_path, index=False, engine="openpyxl"
            )
            _log.info("Exporterade Excel: %s", out_path.name)
            if HAS_PYSIDE6:
                QMessageBox.information(
                    None, "Export",
                    "Exporterade till:\n%s" % out_path.name,
                )
            return out_path
        except Exception as exc:
            _log.error(
                "Excel-export fel: %s", exc, exc_info=True
            )
            if HAS_PYSIDE6:
                QMessageBox.critical(
                    None, "Fel", "Kunde inte exportera:\n%s" % exc
                )
            return None

    def _create_preamble(self, filepath: Path) -> List[str]:
        """Skapa preamble-rader."""
        ts = datetime.now().isoformat(timespec="seconds")
        return [
            "// -*- coding: utf-8 -*-",
            "// Auto-generated: %s" % ts,
            "// Fil: %s" % filepath.name,
            "// Källa: %s" % (self._current_file or "Unknown"),
            "// %s" % get_copyright_string(),
            "",
        ]

    # ──────────────────────────────────────────────────────────────────────
    # FILHANTERING
    # ──────────────────────────────────────────────────────────────────────

    def _load_dispatch_file(self, filepath: Path) -> Any:
        """Ladda och kombinera alla blad. KRASCHSÄKER."""
        if not PANDAS_AVAILABLE:
            return None
        try:
            xls = pd.ExcelFile(filepath, engine="openpyxl")
            sheet_names = xls.sheet_names
            _log.info(
                "📂 Öppnade: %s | Blad: %s",
                filepath.name, sheet_names,
            )
        except Exception as exc:
            _log.error("Kunde inte öppna: %s: %s", filepath, exc)
            return None
        all_data = []
        for sheet_name in sheet_names:
            if sheet_name.strip().lower() in SKIP_SHEETS:
                _log.debug("  ⏭️ Hoppar över: %s", sheet_name)
                continue
            try:
                df_sheet = self._read_sheet_with_header_detection(
                    xls, sheet_name
                )
                if df_sheet is not None and not df_sheet.empty:
                    df_sheet["_sheet"] = sheet_name
                    all_data.append(df_sheet)
                    _log.info(
                        "  ✅ %s: %d rader",
                        sheet_name, len(df_sheet),
                    )
            except Exception as exc:
                _log.warning("  ❌ Fel i %s: %s", sheet_name, exc)
        if not all_data:
            return None
        df = pd.concat(all_data, ignore_index=True)
        df = self._process_dataframe(df)
        self._detect_vin_column(df)
        self._build_column_mapping(df)
        _log.info(
            "✅ Totalt: %d rader från %d blad",
            len(df), len(all_data),
        )
        return df

    def _read_sheet_with_header_detection(
        self, xls: Any, sheet_name: str
    ) -> Any:
        """Läs blad med automatisk header-detektion. KRASCHSÄKER."""
        # Strategi 1: header=0
        try:
            df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str)
            df = self._strip_columns(df)
            mapping, missing = self._resolve_columns(df)
            if len(missing) < len(COLUMN_ALIASES) - 1:
                return df
        except Exception:
            pass

        # Strategi 2: Skanna första 20 rader
        try:
            raw = pd.read_excel(
                xls, sheet_name=sheet_name,
                dtype=str, header=None, nrows=200,
            )
            raw = self._strip_columns(raw)
            best_idx = -1
            best_score = 0
            for i in range(min(20, len(raw))):
                header_row = [
                    str(x).strip() for x in raw.iloc[i].tolist()
                ]
                if all(
                    x == "" or x.lower() == "nan"
                    for x in header_row
                ):
                    continue
                tmp = raw.copy()
                tmp.columns = header_row
                tmp = tmp.iloc[i + 1:]
                if len(tmp) == 0:
                    continue
                mapping, missing = self._resolve_columns(tmp)
                score = len(COLUMN_ALIASES) - len(missing)
                if mapping.get("VIN"):
                    score += 3
                if mapping.get("Model Year"):
                    score += 2
                if score > best_score:
                    best_score = score
                    best_idx = i
            if best_idx >= 0 and best_score >= 2:
                df = pd.read_excel(
                    xls, sheet_name=sheet_name,
                    dtype=str, header=best_idx,
                )
                return self._strip_columns(df)
        except Exception as exc:
            _log.debug(
                "  ⚠️ Header-detektion misslyckades: %s", exc,
            )

        # Fallback
        try:
            df = pd.read_excel(
                xls, sheet_name=sheet_name, dtype=str
            )
            return self._strip_columns(df)
        except Exception:
            return None

    def _resolve_columns(
        self, df: Any
    ) -> Tuple[Dict[str, Optional[str]], List[str]]:
        """Matchar kolumner mot alias. KRASCHSÄKER."""
        cols = list(df.columns)
        norm_to_real = {self._norm_key(c): str(c) for c in cols}
        mapping: Dict[str, Optional[str]] = {}
        missing: List[str] = []
        for key, aliases in COLUMN_ALIASES.items():
            found = None
            nk = self._norm_key(key)
            if nk in norm_to_real:
                found = norm_to_real[nk]
            else:
                for alias in aliases:
                    if self._norm_key(alias) in norm_to_real:
                        found = norm_to_real[self._norm_key(alias)]
                        break
            mapping[key] = found
            if found is None:
                missing.append(key)
        return mapping, missing

    def _build_column_mapping(self, df: Any) -> None:
        """Bygg kolumnmappning från DataFrame."""
        self._column_mapping = {}
        mapping, _ = self._resolve_columns(df)
        for standard_name, actual_name in mapping.items():
            if actual_name:
                self._column_mapping[actual_name] = standard_name

    def _detect_vin_column(self, df: Any) -> None:
        """Detektera VIN-kolumnens namn. KRASCHSÄKER."""
        for col in df.columns:
            if self._norm_key(col) == "vin":
                self._vin_column_name = col
                return
        for col in df.columns:
            if self._norm_key(col) in [
                self._norm_key(a)
                for a in COLUMN_ALIASES.get("VIN", [])
            ]:
                self._vin_column_name = col
                return
        self._vin_column_name = "VIN"

    def _process_dataframe(self, df: Any) -> Any:
        """Efterbearbeta DataFrame. KRASCHSÄKER."""
        df = self._strip_columns(df)
        for col in ["Invoice Date", "Actual Production Date"]:
            if col in df.columns:
                df[col] = df[col].apply(self._to_sv_date)
        if "Model Year" in df.columns:
            df["Model Year"] = df["Model Year"].apply(
                self._normalize_model_year
            )
        vin_col = None
        for col in df.columns:
            if self._norm_key(col) == "vin":
                vin_col = col
                break
        if vin_col:
            df[vin_col] = (
                df[vin_col].astype(str).str.strip().str.upper()
            )
            df = df[df[vin_col] != ""]
            df = df[df[vin_col].str.lower() != "nan"]
            df = df[df[vin_col].str.len() > 0]
        return df

    # ──────────────────────────────────────────────────────────────────────
    # HJÄLPFUNKTIONER
    # ──────────────────────────────────────────────────────────────────────

    def _strip_columns(self, df: Any) -> Any:
        """Trimma whitespace från kolumner. KRASCHSÄKER."""
        try:
            for col in df.columns:
                if df[col].dtype == "object":
                    try:
                        df[col] = df[col].astype(str).str.strip()
                    except Exception:
                        pass
        except Exception:
            pass
        return df

    def _norm_key(self, s: Any) -> str:
        """Normalisera sträng för jämförelse."""
        if s is None:
            return ""
        x = str(s).strip().lower()
        x = x.replace("å", "a").replace("ä", "a").replace("ö", "o")
        x = re.sub(r"[\W_]+", "", x, flags=re.UNICODE)
        return x

    def _to_sv_date(self, val: Any) -> str:
        """Konvertera till svenskt datumformat. KRASCHSÄKER."""
        if val is None:
            return ""
        if PANDAS_AVAILABLE and isinstance(val, float) and pd.isna(val):
            return ""
        if PANDAS_AVAILABLE and isinstance(val, pd.Timestamp):
            return val.date().isoformat()
        if isinstance(val, (datetime, date)):
            d = val.date() if hasattr(val, "date") else val
            return d.isoformat()
        s = str(val).strip()
        if not s or s.lower() == "nan":
            return ""
        m = re.fullmatch(
            r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s
        )
        if m:
            try:
                return date(
                    int(m.group(1)),
                    int(m.group(2)),
                    int(m.group(3)),
                ).isoformat()
            except ValueError:
                return ""
        if re.fullmatch(r"\d{8}", s):
            try:
                return date(
                    int(s[:4]), int(s[4:6]), int(s[6:8])
                ).isoformat()
            except ValueError:
                return ""
        return s

    def _normalize_model_year(self, val: Any) -> str:
        """Normalisera modellår. KRASCHSÄKER."""
        s = str(val).strip()
        if not s or s.lower() == "nan":
            return ""
        m = re.search(r"\b(20\d{2})\b", s)
        if m:
            return m.group(1)
        m = re.search(r"\b(\d{2})\b", s)
        if m:
            yy = int(m.group(1))
            return "20%02d" % yy
        try:
            val_int = int(float(s.replace(",", ".")))
            if 2000 <= val_int <= 2099:
                return str(val_int)
            if 0 <= val_int <= 99:
                return "20%02d" % val_int
        except Exception:
            pass
        return s


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET (PySide6)
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:

    class DispatchWidget(QWidget):
        """
        Widget för att visa dispatch-data.

        KRAV (SPEC):
          ✅ QTableView + QAbstractTableModel (EJ QTableWidget)
          ✅ QSortFilterProxyModel för sökning
          ✅ Inga hårdkodade färger (setObjectName → theme engine)
          ✅ Mushjuls-scroll (ScrollPerPixel)
          ✅ Fet text på knappar (_set_bold)
          ✅ setWordWrap(True) via Python
          ✅ Responsiv layout
          ✅ DPI-aware
        """

        def __init__(
            self, parent: QWidget, app: Any, plugin: Plugin
        ) -> None:
            super().__init__(parent)
            self.app = app
            self.plugin = plugin
            self._data: Any = None
            self._filename: str = ""
            self._model = DispatchTableModel(self)
            self._proxy = QSortFilterProxyModel(self)
            self._proxy.setSourceModel(self._model)
            self._proxy.setFilterCaseSensitivity(
                Qt.CaseSensitivity.CaseInsensitive
            )
            self._proxy.setFilterKeyColumn(-1)
            self._setup_ui()
            QTimer.singleShot(100, self._auto_load)

        def _setup_ui(self) -> None:
            """Bygg UI. Inga hårdkodade färger — allt via objectName."""
            layout = QVBoxLayout(self)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(10)

            # ── TITEL ──
            title = QLabel("📥 Dispatch Import")
            title.setObjectName("PageTitle")
            title_font = QFont()
            title_font.setPointSize(18)
            title_font.setBold(True)
            title.setFont(title_font)
            layout.addWidget(title)

            # ── FIL-INFO ──
            info_layout = QHBoxLayout()

            self.file_label = QLabel("Ingen fil laddad")
            self.file_label.setObjectName("StatusLabel")
            self.file_label.setWordWrap(True)
            info_layout.addWidget(self.file_label)

            info_layout.addStretch()

            self.stats_label = QLabel("")
            self.stats_label.setObjectName("CountLabel")
            _set_bold(self.stats_label)
            info_layout.addWidget(self.stats_label)

            layout.addLayout(info_layout)

            # ── SÖKNING ──
            search_group = QGroupBox("Sökning & Import")
            search_group.setObjectName("SearchGroup")
            search_layout = QHBoxLayout(search_group)

            search_icon = QLabel("🔍")
            search_icon.setFixedWidth(24)
            search_layout.addWidget(search_icon)

            self.search_input = QLineEdit()
            self.search_input.setObjectName("SearchInput")
            self.search_input.setPlaceholderText(
                "Sök på VIN, modell, dealer..."
            )
            self.search_input.setClearButtonEnabled(True)
            self.search_input.textChanged.connect(self._on_search)
            search_layout.addWidget(self.search_input, 1)

            btn_load = QPushButton("📂 Ladda fil")
            btn_load.setObjectName("PrimaryButton")
            _set_bold(btn_load)
            btn_load.clicked.connect(self._load_file_dialog)
            search_layout.addWidget(btn_load)

            btn_refresh = QPushButton("🔄 Uppdatera")
            btn_refresh.setObjectName("SecondaryButton")
            _set_bold(btn_refresh)
            btn_refresh.clicked.connect(self.refresh)
            search_layout.addWidget(btn_refresh)

            layout.addWidget(search_group)

            # ── STATUS ──
            self.status_label = QLabel("Laddar...")
            self.status_label.setObjectName("StatusLabel")
            self.status_label.setWordWrap(True)
            layout.addWidget(self.status_label)

            # ── TABELL ──
            self.table_view = QTableView()
            self.table_view.setObjectName("DispatchTable")
            self.table_view.setModel(self._proxy)
            self.table_view.setAlternatingRowColors(True)
            self.table_view.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
            self.table_view.setSelectionMode(
                QAbstractItemView.SelectionMode.SingleSelection
            )
            self.table_view.setEditTriggers(
                QAbstractItemView.EditTrigger.NoEditTriggers
            )
            self.table_view.setSortingEnabled(True)
            self.table_view.setShowGrid(True)
            self.table_view.setWordWrap(True)
            self.table_view.verticalHeader().setVisible(True)
            self.table_view.horizontalHeader().setStretchLastSection(
                True
            )
            self.table_view.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
            self.table_view.setVerticalScrollMode(
                QAbstractItemView.ScrollMode.ScrollPerPixel
            )
            self.table_view.setHorizontalScrollMode(
                QAbstractItemView.ScrollMode.ScrollPerPixel
            )
            self.table_view.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            self.table_view.setMinimumHeight(200)
            layout.addWidget(self.table_view, 1)

            # ── KNAPPAR ──
            btn_group = QGroupBox("Åtgärder")
            btn_group.setObjectName("ActionGroup")
            btn_layout = QHBoxLayout(btn_group)

            btn_csv = QPushButton("📤 Exportera CSV")
            btn_csv.setObjectName("SuccessButton")
            _set_bold(btn_csv)
            btn_csv.clicked.connect(
                lambda: self.plugin.export_to_csv(self._data)
            )
            btn_layout.addWidget(btn_csv)

            btn_excel = QPushButton("📊 Exportera Excel")
            btn_excel.setObjectName("SecondaryButton")
            _set_bold(btn_excel)
            btn_excel.clicked.connect(
                lambda: self.plugin.export_to_excel(self._data)
            )
            btn_layout.addWidget(btn_excel)

            btn_validate = QPushButton("✅ Validera VIN")
            btn_validate.setObjectName("SecondaryButton")
            _set_bold(btn_validate)
            btn_validate.clicked.connect(self._validate_vins)
            btn_layout.addWidget(btn_validate)

            btn_layout.addStretch()

            self.count_label = QLabel("0 rader")
            self.count_label.setObjectName("CountLabel")
            _set_bold(self.count_label)
            btn_layout.addWidget(self.count_label)

            layout.addWidget(btn_group)

        # ──────────────────────────────────────────────────────────────────
        # WIDGET API
        # ──────────────────────────────────────────────────────────────────

        def refresh(self) -> None:
            """Ladda om aktuell fil."""
            self._auto_load()

        def set_data(self, df: Any, filename: str) -> None:
            """Sätt data från extern källa."""
            self._data = df
            self._filename = filename
            self._populate_table(df)
            self.file_label.setText("📁 %s" % filename)
            self.status_label.setText(
                "✅ Laddade %d rader" % len(df)
            )

            # Uppdatera statistik
            try:
                stats = self.plugin.get_statistics()
                years = ", ".join(stats.get("model_years", []))
                self.stats_label.setText(
                    "VIN: %s" % stats.get("vin_count", 0)
                    + (" | År: %s" % years if years else "")
                )
            except Exception:
                pass

        def _populate_table(self, df: Any) -> None:
            """Fyll tabell med DataFrame-data."""
            if df is None or df.empty:
                self._model.clear()
                self.count_label.setText("0 rader")
                return

            # Exkludera interna kolumner
            cols = [c for c in df.columns if not c.startswith("_")]
            headers = list(cols)

            rows: List[List[str]] = []
            for _, row in df.iterrows():
                row_values: List[str] = []
                for col in cols:
                    value = str(row.get(col, ""))
                    if value.lower() in ("nan", "none", "nat"):
                        value = ""
                    row_values.append(value)
                rows.append(row_values)

            self._model.set_data(headers, rows)
            self.count_label.setText("%d rader" % len(rows))

        def _auto_load(self) -> None:
            """Auto-load senaste fil. KRASCHSÄKER."""
            try:
                files = self.plugin.list_dispatch_files()
                if not files:
                    self.status_label.setText(
                        "ℹ️ Inga dispatch-filer hittades"
                    )
                    self.file_label.setText(
                        "Ingen fil — lägg filer i dispatch/"
                    )
                    return
                latest = files[0]
                self.plugin.load_file(str(latest))
            except Exception as exc:
                _log.error("Auto-load misslyckades: %s", exc)

        def _load_file_dialog(self) -> None:
            """Ladda fil via dialog."""
            start_dir = str(
                self.plugin._paths.get("dispatch", ".")
            )
            filepath, _ = QFileDialog.getOpenFileName(
                self,
                "Välj Dispatch-fil",
                start_dir,
                "Excel-filer (*.xlsx *.xls);;Alla filer (*.*)",
            )
            if filepath:
                self.plugin.load_file(filepath)

        def _on_search(self) -> None:
            """Filtrera via QSortFilterProxyModel."""
            try:
                query = self.search_input.text().strip()
                self._proxy.setFilterFixedString(query)
                visible = self._proxy.rowCount()
                total = self._model.rowCount()
                if query:
                    self.count_label.setText(
                        "%d av %d rader" % (visible, total)
                    )
                else:
                    self.count_label.setText("%d rader" % total)
            except Exception as exc:
                _log.error("Sökfel: %s", exc)

        def _validate_vins(self) -> None:
            """Validera alla VIN och visa resultat."""
            try:
                result = self.plugin.validate_all_vins()
                msg = (
                    "VIN-validering:\n\n"
                    "✅ Giltiga: %d\n"
                    "❌ Ogiltiga: %d\n"
                    "Totalt: %d"
                    % (
                        result["valid_count"],
                        result["invalid_count"],
                        result["total"],
                    )
                )
                if result["invalid_vins"]:
                    msg += "\n\nOgiltiga VIN (första 10):\n"
                    for item in result["invalid_vins"][:10]:
                        msg += "  • %s: %s\n" % (
                            item["vin"],
                            item["error"],
                        )
                QMessageBox.information(
                    self, "VIN-validering", msg
                )
            except Exception as exc:
                _log.error("VIN-validering misslyckades: %s", exc)
                QMessageBox.critical(
                    self, "Fel",
                    "VIN-validering misslyckades:\n%s" % exc,
                )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "Plugin",
    "COLUMN_ALIASES",
    "VERSION",
    "AUTHOR",
    "HAS_PYSIDE6",
    "PANDAS_AVAILABLE",
    "get_copyright_string",
]

# Klasserna finns bara när PySide6 är tillgängligt (import *
# kraschar annars på saknade namn).
if HAS_PYSIDE6:
    __all__ += [
        "DispatchWidget",
        "DispatchTableModel",
    ]
