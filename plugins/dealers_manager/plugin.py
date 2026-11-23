# -*- coding: utf-8 -*-
# Fil: plugins/dealers_manager/plugin.py
# Copyright © 2025 Rickard Längkvist

"""
Dealers Manager Plugin v2.2.0 (PySide6)

Hanterar återförsäljare i JSON med Excel-import.

Konverterad från: Script/db_config.py + Script/import_aterforsaljare.py

ANSVAR:
  - CRUD för återförsäljare (JSON-lagring, atomisk skrivning)
  - Gemensam filimport med mappning och verifierad säkerhetskopia
  - Ändringar kräver separat PIN; tidigare lösenordsfil lämnas orörd
  - GUI-widget med sökning, tabell, knappar
  - Event-driven integration via event_bus
  - Kraschsäkra publika API-metoder

PUBLIKT API:
  load_from_json()          -> List[Dict]
  save_to_json(data)        -> bool
  get_all_dealers()         -> List[Dict]
  get_by_dn(dn)             -> Optional[Dict]
  add_dealer(data)          -> bool
  update_dealer(dn, data)   -> bool
  delete_dealer(dn)         -> bool
  import_from_excel(...)    -> Dict
  get_count()               -> int
  sync_to_db(dealers)       -> int
  password_manager          -> property: Optional[DealersPasswordManager]

IMPORTER (EXTERNA):
  json, logging, os, tempfile, datetime, pathlib, typing
  PySide6.QtCore, PySide6.QtWidgets, PySide6.QtGui
  core.plugin_base.PluginBase
  plugins.dealers_manager.auth.password_manager (DealersPasswordManager)
  plugins.dealers_manager.import_logic.excel_reader
    (read_excel_with_header_detection, resolve_columns, get_excel_engine)
  plugins.dealers_manager.import_logic.synonyms
    (DN_SYNONYMS, NAMN_SYNONYMS, T6_SYNONYMS)
  pandas (valfri, kontrolleras vid runtime)

EVENTS SOM EMITTAS:
  dealers.loaded    - när JSON laddats
  dealers.saved     - när JSON sparats
  dealers.imported  - när Excel importerats
  dealers.added     - när en ÅF lagts till
  dealers.updated   - när en ÅF uppdaterats
  dealers.deleted   - när en ÅF tagits bort
  dealers.synced    - när DB-sync körts

FÖRÄNDRINGAR v2.2.0:
  - DealersPasswordManager → importeras från auth/password_manager.py
  - Excel-import → använder import_logic/excel_reader.py (header-detektering)
  - Kolumnsynonymer → importeras från import_logic/synonyms.py
  - DN_ALIASES/NAMN_ALIASES/ORGNR_ALIASES → ersatta av DN_SYNONYMS etc.
  - _process_excel_sheet() → använder resolve_columns() + header-detektering
  - update_dealer() tillagd
  - change() på password_manager returnerar nu Tuple[bool, str]
  - _change_password() uppdaterad för att hantera Tuple-retur

FÖRÄNDRINGAR v2.2.1:
  - Importvägar anpassade till befintlig mappstruktur:
      auth/password_manager.py
      import_logic/synonyms.py
      import_logic/excel_reader.py
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Union

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSizePolicy,
    QTableView, QVBoxLayout, QWidget, QScrollArea,
    QFrame,
)

from core.plugin_base import PluginBase
from plugins.gui_helpers.page_header import PageHeader
from core.dealer_storage import DealerStorage
from core.dealer_fields import FIELDS
from core.dealer_pin import DealerPin, PIN_FILENAME

# ── ANPASSADE IMPORTVÄGAR (matchar befintlig mappstruktur) ──
# dealers_manager/
# ├── auth/
# │   └── password_manager.py
# ├── import_logic/
# │   ├── excel_reader.py
# │   └── synonyms.py
# ├── __init__.py
# └── plugin.py
from plugins.dealers_manager.auth.password_manager import DealersPasswordManager
from plugins.dealers_manager.import_logic.synonyms import (
    DN_SYNONYMS, NAMN_SYNONYMS, T6_SYNONYMS,
)
from plugins.dealers_manager.import_logic.excel_reader import (
    read_excel_with_header_detection,
    resolve_columns,
    get_excel_engine,
)


# ──────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL LOGGER
# ──────────────────────────────────────────────────────────────────────────────

_log: logging.Logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

PLUGIN_NAME: Final[str] = "Dealers Manager"
PLUGIN_VERSION: Final[str] = "2.2.1"
PLUGIN_DESCRIPTION: Final[str] = (
    "Hantering av återförsäljare med Excel-import (PySide6)"
)
PLUGIN_AUTHOR: Final[str] = "Rickard Längkvist"
PLUGIN_COPYRIGHT: Final[str] = (
    f"Copyright © {datetime.now().year} Rickard Längkvist"
)

_NO_SNAPSHOT = object()

JSON_FILENAME: Final[str] = "aterforsaljare.json"
PASSWORD_FILENAME: Final[str] = "aterforsaljare_password.json"
DATA_SUBDIR: Final[str] = ".js data"

# Blad att hoppa över vid Excel-import
SKIP_SHEETS: Final[List[str]] = [
    "pow 2", "sheet2", "blad2", "info", "readme",
    "instruktion", "instruktioner",
]

# Pandas-tillgänglighet
try:
    import pandas as pd  # type: ignore
    PANDAS_AVAILABLE: Final[bool] = True
except ImportError:
    pd = None  # type: ignore
    PANDAS_AVAILABLE: Final[bool] = False

if not PANDAS_AVAILABLE:
    _log.warning("pandas ej installerat – Excel-import ej tillgängligt")


# ══════════════════════════════════════════════════════════════════════════════
# ATOMIC FILE WRITER
# ══════════════════════════════════════════════════════════════════════════════


def _atomic_write_text(
    path: Path, content: str, encoding: str = "utf-8"
) -> None:
    """
    Atomisk filskrivning: skriv till .tmp → fsync → rename → slutlig fil.

    Förhindrar korrupta filer vid krasch under skrivning.

    Args:
        path:     Slutlig sökväg
        content:  Textinnehåll
        encoding: Teckenkodning (default utf-8)

    Raises:
        OSError: Om rename misslyckas efter skrivning
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.tmp_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TABLE MODEL
# ══════════════════════════════════════════════════════════════════════════════


class DealersTableModel(QAbstractTableModel):
    """
    Qt Table Model för återförsäljare.

    Bättre prestanda än QTableWidget för stora datamängder.
    Stöder QSortFilterProxyModel för sökning och sortering.

    KOLUMNER:
      0: Dealer Number
      1: Namn
      2: Org.nr

    PUBLIKA METODER:
      set_data(dealers)       -> None
      get_dealer_at(row)      -> Optional[Dict]
      rowCount(parent)        -> int
      columnCount(parent)     -> int
      headerData(...)         -> Any
      data(index, role)       -> Any
    """

    HEADERS: Final[List[str]] = list(FIELDS.values())
    KEYS: Final[List[str]] = list(FIELDS)
    COL_DN: Final[int] = 0
    COL_NAMN: Final[int] = 1
    COL_ORGNR: Final[int] = 2

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data: List[Dict[str, Any]] = []

    def set_data(self, dealers: List[Dict[str, Any]]) -> None:
        """Ersätt all data och notifiera vyn."""
        self.beginResetModel()
        self._data = list(dealers)
        self.endResetModel()

    def get_dealer_at(self, row: int) -> Optional[Dict[str, Any]]:
        """Hämta återförsäljare vid source-rad. None om ogiltigt index."""
        if 0 <= row < len(self._data):
            return self._data[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(self.HEADERS)
        ):
            return self.HEADERS[section]
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

        if row >= len(self._data):
            return None

        dealer = self._data[row]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if 0 <= col < len(self.KEYS):
                key = self.KEYS[col]
                value = dealer.get(key, dealer.get("dn", "") if key == "dealer_number" else "")
                text = "" if value is None else str(value)
                # Visa alla rader på en rad; tooltip behåller originaltexten.
                return " ↵ ".join(text.splitlines()) if role == Qt.ItemDataRole.DisplayRole else text

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == self.COL_DN:
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return None


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN-KLASS
# ══════════════════════════════════════════════════════════════════════════════


class Plugin(PluginBase):
    """
    Dealers Manager Plugin – Återförsäljare (PySide6)

    KONTRAKT (PluginBase):
      init()              - initiera plugin, sätt upp sökvägar
      register_ui(parent) - skapa och returnera DealersWidget
      shutdown()          - städa upp widget-referens
      config_schema()     - returnera konfigurationsschema

    PUBLIKT API:
      load_from_json()          -> List[Dict]
      save_to_json(data)        -> bool
      get_all_dealers()         -> List[Dict]
      get_by_dn(dn)             -> Optional[Dict]
      add_dealer(data)          -> bool
      update_dealer(dn, data)   -> bool
      delete_dealer(dn)         -> bool
      import_from_excel(...)    -> Dict
      get_count()               -> int
      sync_to_db(dealers)       -> int
      password_manager          -> property

    EVENTS SOM EMITTAS:
      dealers.loaded, dealers.saved, dealers.imported,
      dealers.added, dealers.updated, dealers.deleted, dealers.synced
    """

    NAME: Final[str] = PLUGIN_NAME
    VERSION: Final[str] = PLUGIN_VERSION
    DESCRIPTION: Final[str] = PLUGIN_DESCRIPTION
    AUTHOR: Final[str] = PLUGIN_AUTHOR
    DEPENDENCIES: Final[List[str]] = []

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._json_path: Optional[Path] = None
        self._password_manager: Optional[DealersPasswordManager] = None
        self._widget: Optional[DealersWidget] = None

    # ──────────────────────────────────────────────────────────────────────
    # PLUGIN LIFECYCLE
    # ──────────────────────────────────────────────────────────────────────

    def init(self) -> None:
        """
        Initiera plugin.

        Sätter upp JSON-sökväg och DealersPasswordManager.
        Registrerar self som app.dealers för extern åtkomst.
        Kraschsäker – loggar fel och fortsätter.
        """
        try:
            base_dir = self._get_base_dir()
            data_dir = base_dir / DATA_SUBDIR
            data_dir.mkdir(parents=True, exist_ok=True)

            self._json_path = data_dir / JSON_FILENAME
            password_file = data_dir / PASSWORD_FILENAME

            # Använder nu den separata auth/password_manager.py
            self._password_manager = DealersPasswordManager(password_file)

            try:
                self.app.dealers = self
            except Exception:
                pass

            _log.info(
                "%s v%s initierad. JSON: %s",
                PLUGIN_NAME, PLUGIN_VERSION, self._json_path,
            )
            self._emit_safe("dealers.loaded", {"count": self.get_count()})

        except Exception as exc:
            _log.error(
                "Fel vid initiering av %s: %s",
                PLUGIN_NAME, exc, exc_info=True,
            )
            raise

    def create_widget(self, parent: QWidget) -> Optional[QWidget]:
        """Huvudfönstrets standardkontrakt för en pluginsida."""
        if self._json_path is None:
            raise RuntimeError("Återförsäljarregistret är inte initierat")
        return self.register_ui(parent)

    def register_ui(self, parent: QWidget) -> Optional[QWidget]:
        """
        Skapa och returnera GUI-widget.

        Args:
            parent: Förälder-widget

        Returns:
            DealersWidget eller None vid fel
        """
        try:
            self._widget = DealersWidget(parent, self.app, self)
            _log.debug("DealersWidget skapad")
            return self._widget
        except Exception as exc:
            _log.error(
                "Fel vid skapande av DealersWidget: %s",
                exc, exc_info=True,
            )
            return None

    def shutdown(self) -> None:
        """Städa upp resurser. Rensar widget-referens."""
        try:
            self._widget = None
            _log.info("%s stängd", PLUGIN_NAME)
        except Exception as exc:
            _log.error(
                "Fel vid shutdown av %s: %s",
                PLUGIN_NAME, exc, exc_info=True,
            )

    def config_schema(self) -> Dict[str, Any]:
        """Returnera konfigurationsschema för plugin."""
        return {
            "plugin": PLUGIN_NAME,
            "version": PLUGIN_VERSION,
            "author": PLUGIN_AUTHOR,
            "copyright": PLUGIN_COPYRIGHT,
            "settings": {
                "json_filename": JSON_FILENAME,
                "data_subdir": DATA_SUBDIR,
                "pandas_available": PANDAS_AVAILABLE,
            },
        }

    # ──────────────────────────────────────────────────────────────────────
    # PUBLIKT API – CRUD
    # ──────────────────────────────────────────────────────────────────────

    def _storage(self) -> DealerStorage:
        if self._json_path is None:
            raise RuntimeError("Återförsäljarregistret är inte initierat")
        return DealerStorage(self._json_path)

    def dealer_pin(self) -> DealerPin:
        if self._json_path is None:
            raise RuntimeError("Återförsäljarregistret är inte initierat")
        return DealerPin(self._json_path.parent / PIN_FILENAME)

    def load_from_json(self) -> List[Dict[str, Any]]:
        """Läs alla poster; läsfel får inte förväxlas med ett tomt register."""
        return self._storage().snapshot()[0]

    def save_to_json(self, data, *, expected=_NO_SNAPSHOT, pin=None) -> bool:
        """Spara atomiskt efter verifierad säkerhetskopia och läskontroll."""
        try:
            if not self.dealer_pin().verify(pin):
                raise PermissionError("PIN krävs för att ändra återförsäljarregistret")
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Alla återförsäljarposter måste vara objekt")
            store = self._storage()
            if expected is _NO_SNAPSHOT:
                _, expected = store.snapshot()
            store.save(data, expected)
            self._emit_safe("dealers.saved", {"count": len(data)})
            return True
        except Exception as exc:
            _log.error("Kunde inte spara återförsäljare: %s", exc, exc_info=True)
            return False

    def get_all_dealers(self) -> List[Dict[str, Any]]:
        """Alias för load_from_json(). Tom lista vid fel."""
        try:
            return self.load_from_json()
        except Exception as exc:
            _log.error("Fel i get_all_dealers: %s", exc, exc_info=True)
            return []

    @staticmethod
    def _dn(dealer: Dict[str, Any]) -> str:
        return str(dealer.get("dealer_number", dealer.get("dn", ""))).strip().upper()

    def get_by_dn(self, dn: str) -> Optional[Dict[str, Any]]:
        try:
            target = str(dn).strip().upper()
            matches = [row for row in self.load_from_json() if target and self._dn(row) == target]
            if len(matches) != 1:
                if len(matches) > 1:
                    _log.warning("Flera återförsäljare har dealernummer %s; ändring spärras", target)
                return None
            return matches[0]
        except Exception:
            _log.exception("Kunde inte läsa återförsäljaren")
            return None

    def add_dealer(self, dealer_data: Dict[str, Any], *, pin=None) -> bool:
        try:
            dn = self._dn(dealer_data)
            name = str(dealer_data.get("namn", "")).strip()
            if not dn or not name:
                return False
            records, snapshot = self._storage().snapshot()
            if any(self._dn(row) == dn for row in records):
                _log.warning("Dealernummer %s finns redan", dn)
                return False
            row = {key: str(dealer_data.get(key, "")).strip() for key in FIELDS if key in dealer_data}
            row.update({"dealer_number": dn, "namn": name})
            records.append(row)
            if not self.save_to_json(records, expected=snapshot, pin=pin):
                return False
            self._emit_safe("dealers.added", {"dn": dn, "namn": name})
            return True
        except Exception:
            _log.exception("Kunde inte lägga till återförsäljare")
            return False

    def update_dealer(self, dn: str, updated_data: Dict[str, Any], *, expected_record=None, pin=None) -> bool:
        try:
            target = str(dn).strip().upper()
            records, snapshot = self._storage().snapshot()
            matches = [i for i, row in enumerate(records) if target and self._dn(row) == target]
            if len(matches) != 1:
                _log.warning("Dealernumret saknas eller är inte entydigt: %s", target)
                return False
            index = matches[0]
            if expected_record is not None and records[index] != expected_record:
                _log.warning("Återförsäljaren ändrades medan dialogen var öppen")
                return False
            name = str(updated_data.get("namn", "")).strip()
            new_dn = self._dn(updated_data) if ("dealer_number" in updated_data or "dn" in updated_data) else target
            if not name or not new_dn:
                return False
            if any(i != index and self._dn(row) == new_dn for i, row in enumerate(records)):
                _log.warning("Det nya dealernumret finns redan")
                return False
            changes = {key: str(updated_data[key]).strip() for key in FIELDS
                       if key in updated_data and key != "dealer_number"}
            changes.update({"dealer_number": new_dn, "namn": name})
            if "dn" in records[index] and new_dn != target:
                changes["dn"] = new_dn  # äldre format: håll aliaset konsekvent
            records[index] = {**records[index], **changes}
            if not self.save_to_json(records, expected=snapshot, pin=pin):
                return False
            self._emit_safe("dealers.updated", {"dn": target})
            return True
        except Exception:
            _log.exception("Kunde inte uppdatera återförsäljare")
            return False

    def delete_dealer(self, dn: str, *, expected_record=None, pin=None) -> bool:
        try:
            target = str(dn).strip().upper()
            records, snapshot = self._storage().snapshot()
            matches = [i for i, row in enumerate(records) if target and self._dn(row) == target]
            if len(matches) != 1:
                _log.warning("Dealernumret saknas eller är inte entydigt: %s", target)
                return False
            index = matches[0]
            if expected_record is not None and records[index] != expected_record:
                _log.warning("Återförsäljaren ändrades före borttagning")
                return False
            records.pop(index)
            if not self.save_to_json(records, expected=snapshot, pin=pin):
                return False
            self._emit_safe("dealers.deleted", {"dn": target})
            return True
        except Exception:
            _log.exception("Kunde inte ta bort återförsäljare")
            return False

    def get_count(self) -> int:
        """Returnera antal återförsäljare. 0 vid fel."""
        try:
            return len(self.load_from_json())
        except Exception as exc:
            _log.error("Fel i get_count: %s", exc, exc_info=True)
            return 0

    def sync_to_db(self, dealers: Optional[List[Dict[str, Any]]] = None) -> int:
        """Spärrad: den gamla databassynken ersatte rader utan säkerhetskopia."""
        _log.warning("Databassynk av återförsäljare är spärrad tills den kan göras säkert")
        return 0

    # ──────────────────────────────────────────────────────────────────────
    # EXCEL-IMPORT (via import_logic/excel_reader.py)
    # ──────────────────────────────────────────────────────────────────────

    def import_from_excel(self, filepath=None, parent=None) -> Dict[str, Any]:
        """Importen är pausad tills användarens fil och dubblettregler verifierats."""
        return {"success": False, "total_imported": 0, "processed_sheets": [],
                "skipped_sheets": [], "error": "Excelimporten är tillfälligt spärrad tills dubbletter och filformat har granskats."}

    # ──────────────────────────────────────────────────────────────────────
    # INTERNA HJÄLPMETODER
    # ──────────────────────────────────────────────────────────────────────

    def _process_excel_sheet(
        self, xls: Any, sheet_name: str
    ) -> Dict[str, Any]:
        """
        Bearbeta ett Excel-blad med header-detektering och synonymmatchning.

        Använder:
          - import_logic.excel_reader.read_excel_with_header_detection()
          - import_logic.excel_reader.resolve_columns()
            via DN_SYNONYMS, NAMN_SYNONYMS, T6_SYNONYMS

        Args:
            xls:        Öppen pandas ExcelFile
            sheet_name: Bladets namn

        Returns:
            Dict med:
              skipped: bool
              reason:  str (om skipped)
              records: List[Dict]
        """
        try:
            # Header-detektering via import_logic/excel_reader.py
            df = read_excel_with_header_detection(xls, sheet_name)

            # Synonymmatchning via import_logic/synonyms.py
            dn_col, namn_col, orgnr_col = resolve_columns(df)

            if not dn_col:
                return {
                    "skipped": True,
                    "reason": "saknar DN-kolumn",
                    "records": [],
                }

            if not namn_col:
                return {
                    "skipped": True,
                    "reason": "saknar namn-kolumn",
                    "records": [],
                }

            rename_map: Dict[str, str] = {
                dn_col: "dealer_number",
                namn_col: "namn",
            }
            if orgnr_col:
                rename_map[orgnr_col] = "orgnr"

            df = df.rename(columns=rename_map)

            # Rensa dealer_number
            df["dealer_number"] = df["dealer_number"].apply(
                lambda v: str(v).strip().upper()
                if v is not None and str(v).strip().lower() not in ("nan", "none", "")
                else ""
            )
            df = df[df["dealer_number"] != ""]

            # Rensa namn
            df["namn"] = df["namn"].apply(
                lambda v: str(v).strip()
                if v is not None and str(v).strip().lower() not in ("nan", "none", "")
                else ""
            )
            df = df[df["namn"] != ""]

            # Ta bort dubbletter (behåll sista)
            df = df.drop_duplicates(subset=["dealer_number"], keep="last")

            if df.empty:
                return {
                    "skipped": True,
                    "reason": "ingen giltig data efter rensning",
                    "records": [],
                }

            records: List[Dict[str, Any]] = []
            for _, row in df.iterrows():
                orgnr_val = ""
                if "orgnr" in df.columns and row.get("orgnr") is not None:
                    raw_orgnr = str(row.get("orgnr", "")).strip()
                    if raw_orgnr.lower() not in ("nan", "none", ""):
                        orgnr_val = raw_orgnr

                record: Dict[str, Any] = {
                    "dealer_number": str(row["dealer_number"]).strip(),
                    "namn": str(row["namn"]).strip(),
                    "orgnr": orgnr_val,
                }
                records.append(record)

            _log.debug(
                "Blad '%s': %d poster processade",
                sheet_name, len(records),
            )
            return {"skipped": False, "reason": "", "records": records}

        except Exception as exc:
            _log.warning(
                "Fel vid bearbetning av blad '%s': %s",
                sheet_name, exc,
            )
            return {
                "skipped": True,
                "reason": f"fel: {exc}",
                "records": [],
            }

    def _merge_dealers(self, new_records: List[Dict[str, Any]]) -> None:
        raise RuntimeError("Excelimporten är spärrad tills dubblettreglerna har granskats")

    def _read_json(self, path: Path) -> Any:
        """
        Läs JSON med BOM-stöd och filtrering av kommentarsrader (// och #).

        Args:
            path: Sökväg till JSON-fil

        Returns:
            Parsed data (list, dict eller tom lista)
        """
        text = path.read_text(encoding="utf-8-sig")
        lines = [
            line
            for line in text.splitlines()
            if not line.lstrip().startswith("//")
            and not line.lstrip().startswith("#")
        ]
        payload = "\n".join(lines).strip()
        if not payload:
            return []
        return json.loads(payload)

    def _write_json(self, path: Path, data: Any) -> None:
        """
        Skriv JSON atomiskt med preamble-kommentarer.

        Args:
            path: Slutlig sökväg
            data: Data att serialisera
        """
        timestamp = datetime.now().isoformat(timespec="seconds")
        preamble = "\n".join([
            "// -*- coding: utf-8 -*-",
            f"// Auto-generated: {timestamp}",
            f"// Fil: {path.name}",
            f"// {PLUGIN_COPYRIGHT}",
            "",
        ])
        payload = json.dumps(
            data, ensure_ascii=False, indent=2, sort_keys=True
        )
        _atomic_write_text(path, preamble + payload)

    def _get_base_dir(self) -> Path:
        """Hämta bas-katalog från app-konfiguration. Fallback: current dir."""
        try:
            return Path(self.app.config.get("base_dir", "."))
        except Exception:
            return Path(".")

    def _get_plugin_safe(self, name: str) -> Optional[Any]:
        """Hämta plugin via plugin_manager utan att krascha."""
        try:
            pm = getattr(self.app, "plugin_manager", None)
            if pm and hasattr(pm, "get_plugin"):
                return pm.get_plugin(name)
        except Exception as exc:
            _log.debug(
                "Kunde inte hämta plugin '%s': %s", name, exc
            )
        return None

    def _emit_safe(self, event: str, data: Dict[str, Any]) -> None:
        """Emittera event via event_bus utan att krascha."""
        try:
            bus = getattr(self.app, "event_bus", None)
            if bus and hasattr(bus, "emit"):
                bus.emit(event, data)
            elif bus and hasattr(bus, "publish"):
                bus.publish(event, data)
        except Exception as exc:
            _log.debug("Event-fel '%s': %s", event, exc)

    @property
    def password_manager(self) -> Optional[DealersPasswordManager]:
        """Publik åtkomst till DealersPasswordManager-instansen."""
        return self._password_manager


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET
# ══════════════════════════════════════════════════════════════════════════════


class DealersWidget(QWidget):
    """
    Widget för att visa och hantera återförsäljare.

    PUBLIKA METODER:
      refresh()          - ladda data och uppdatera tabell

    PRIVATA METODER:
      _setup_ui()        - bygg UI
      _on_search()       - QSortFilterProxyModel filter
      _get_selected_dn() - hämta DN för markerad rad
      _import_excel()    - Excel-import via plugin
      _add_dealer()      - dialog för ny ÅF
      _edit_dealer()     - dialog för redigera ÅF
      _delete_selected() - ta bort med bekräftelse
      _export_json()     - exportera till fil
      _change_password() - byt lösenord via DealersPasswordManager

    KRAV (SPEC):
      ✅ Inga hårdkodade färger (setObjectName → theme engine)
      ✅ Mushjuls-scroll (ScrollPerPixel + QScrollArea)
      ✅ Fet text på knappar (QFont.setBold)
      ✅ setWordWrap(True) via Python (EJ stylesheet)
      ✅ Responsiv layout (QSizePolicy.Expanding)
      ✅ DPI-aware (inga fasta pixelstorlekar utom minimum)
      ✅ Dubbelklick på rad → redigera
    """

    def __init__(
        self,
        parent: QWidget,
        app: Any,
        plugin: Plugin,
    ) -> None:
        super().__init__(parent)
        self.app = app
        self.plugin = plugin
        self._model = DealersTableModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )
        self._proxy.setFilterKeyColumn(-1)
        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        """Bygg UI. Inga hårdkodade färger – allt via objectName."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # ── SCROLL-AREA ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── TITEL ──
        # Gemensamt sidhuvud: storlek och färg kommer från temat (förslag 5).
        title = PageHeader.build(
            "Återförsäljare", "dealers",
            "Alla återförsäljare i kolumner, sökbara och PIN-skyddade", self)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)

        # ── SÖKNING ──
        search_group = QGroupBox("Sökning")
        search_group.setObjectName("SearchGroup")
        search_layout = QHBoxLayout(search_group)

        search_icon = QLabel("🔍")
        search_icon.setFixedWidth(24)
        search_layout.addWidget(search_icon)

        self._search_input = QLineEdit()
        self._search_input.setObjectName("SearchInput")
        self._search_input.setPlaceholderText(
            "Sök i alla kolumner..."
        )
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search)
        search_layout.addWidget(self._search_input, 1)

        btn_refresh = QPushButton("🔄 Uppdatera")
        btn_refresh.setObjectName("SecondaryButton")
        btn_refresh.setToolTip("Ladda om data från JSON")
        _set_bold(btn_refresh)
        btn_refresh.clicked.connect(self.refresh)
        search_layout.addWidget(btn_refresh)

        layout.addWidget(search_group)

        # ── STATUS ──
        self._status_label = QLabel("Laddar...")
        self._status_label.setObjectName("StatusLabel")
        status_font = QFont()
        status_font.setPointSize(10)
        self._status_label.setFont(status_font)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # ── TABELL ──
        self._table_view = QTableView()
        self._table_view.setObjectName("DealersTable")
        self._table_view.setModel(self._proxy)
        self._table_view.setAlternatingRowColors(True)
        self._table_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table_view.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table_view.setSortingEnabled(True)
        self._table_view.setShowGrid(True)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.doubleClicked.connect(self._edit_dealer)
        self._table_view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._table_view.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._table_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._table_view.setMinimumHeight(200)

        header = self._table_view.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setResizeContentsPrecision(-1)  # Inkludera alla synliga rader, inte bara ett urval.
        self._auto_columns = True
        self._setting_column_widths = False
        self._column_natural_widths = []
        from PySide6.QtCore import QTimer
        self._column_fit_timer = QTimer(self)
        self._column_fit_timer.setSingleShot(True)
        self._column_fit_timer.timeout.connect(self._fit_dealer_columns)
        self._column_resize_timer = QTimer(self)
        self._column_resize_timer.setSingleShot(True)
        self._column_resize_timer.timeout.connect(
            lambda: self._apply_dealer_column_widths(self._table_view.viewport().width()))
        header.sectionResized.connect(self._column_resized)
        self._table_view.viewport().installEventFilter(self)
        layout.addWidget(self._table_view, 1)

        # ── KNAPPAR ──
        btn_group = QGroupBox("Åtgärder")
        btn_group.setObjectName("ActionGroup")
        from plugins.main_gui.flow_layout import FlowLayout
        btn_layout = FlowLayout(btn_group)

        buttons_config: List[Dict[str, Any]] = [
            {
                "text": "📥 Importera fil",
                "name": "PrimaryButton",
                "tooltip": "Importera återförsäljare från Excel, CSV eller PDF",
                "handler": self._import_excel,
            },
            {
                "text": "➕ Lägg till",
                "name": "SuccessButton",
                "tooltip": "Lägg till ny återförsäljare manuellt",
                "handler": self._add_dealer,
            },
            {
                "text": "✏️ Redigera",
                "name": "SecondaryButton",
                "tooltip": "Redigera vald återförsäljare (eller dubbelklicka)",
                "handler": self._edit_dealer,
            },
            {
                "text": "🗑️ Ta bort",
                "name": "DangerButton",
                "tooltip": "Ta bort vald återförsäljare",
                "handler": self._delete_selected,
            },
            {
                "text": "↔ Anpassa kolumner",
                "name": "SecondaryButton",
                "tooltip": "Anpassa kolumnbredder automatiskt efter innehåll och tillgänglig bredd",
                "handler": self._restore_auto_columns,
            },
            {
                "text": "🔐 Byt PIN",
                "name": "SecondaryButton",
                "tooltip": "Byt PIN-kod för ändringar i återförsäljarregistret",
                "handler": self._change_dealer_pin,
            },
            {
                "text": "📤 Exportera JSON",
                "name": "SecondaryButton",
                "tooltip": "Exportera alla återförsäljare till JSON-fil",
                "handler": self._export_json,
            },
        ]

        for cfg in buttons_config:
            btn = QPushButton(cfg["text"])
            btn.setObjectName(cfg["name"])
            btn.setToolTip(cfg["tooltip"])
            _set_bold(btn)
            btn.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
            )
            btn.setMinimumHeight(36)
            btn.clicked.connect(cfg["handler"])
            btn_layout.addWidget(btn)

        layout.addWidget(btn_group)
        security_note = QLabel("PIN krävs vid ändringar i programmet. Registerfilen är inte krypterad.")
        security_note.setWordWrap(True)
        layout.addWidget(security_note)

        # ── FOOTER ──
        footer_layout = QHBoxLayout()

        self._count_label = QLabel("0 återförsäljare")
        self._count_label.setObjectName("CountLabel")
        count_font = QFont()
        count_font.setPointSize(10)
        count_font.setBold(True)
        self._count_label.setFont(count_font)
        footer_layout.addWidget(self._count_label)

        footer_layout.addStretch()

        pandas_lbl = QLabel(
            "✅ pandas" if PANDAS_AVAILABLE else "❌ pandas saknas"
        )
        pandas_lbl.setObjectName("PandasStatus")
        pandas_font = QFont()
        pandas_font.setPointSize(9)
        pandas_lbl.setFont(pandas_font)
        footer_layout.addWidget(pandas_lbl)

        layout.addLayout(footer_layout)

        scroll.setWidget(inner)
        main_layout.addWidget(scroll, 1)

    # ──────────────────────────────────────────────────────────────────────
    # WIDGET API
    # ──────────────────────────────────────────────────────────────────────

    def _column_resized(self, _index: int, _old: int, _new: int) -> None:
        # Manuell ändring respekteras tills användaren väljer automatisk anpassning igen.
        if not self._setting_column_widths:
            self._auto_columns = False
            self._column_fit_timer.stop()

    def _restore_auto_columns(self) -> None:
        self._auto_columns = True
        self._fit_dealer_columns()

    def _fit_dealer_columns(self) -> None:
        if not self._auto_columns:
            return
        header = self._table_view.horizontalHeader()
        self._setting_column_widths = True
        try:
            self._table_view.resizeColumnsToContents()
            self._column_natural_widths = [header.sectionSize(i) for i in range(len(FIELDS))]
        finally:
            self._setting_column_widths = False
        self._apply_dealer_column_widths(self._table_view.viewport().width())

    def _apply_dealer_column_widths(self, viewport_width: int) -> None:
        if not self._auto_columns or not self._column_natural_widths or self._setting_column_widths:
            return
        from core.responsive_layout import fit_columns
        header = self._table_view.horizontalHeader()
        widths = fit_columns(self._column_natural_widths, viewport_width)
        self._setting_column_widths = True
        try:
            for column, width in enumerate(widths):
                header.resizeSection(column, width)
        finally:
            self._setting_column_widths = False

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched is self._table_view.viewport() and event.type() == QEvent.Type.Resize:
            # Vänta tills Qt är klar med eventuella rullningslister och mät den
            # verkliga visningsbredden; undvik återinträde under kolumnändringar.
            self._column_resize_timer.start(0)
        return super().eventFilter(watched, event)

    def refresh(self) -> None:
        """Ladda data från plugin och uppdatera tabell."""
        try:
            data = self.plugin.load_from_json()
            self._model.set_data(data)
            total = self._model.rowCount()
            self._status_label.setText(
                f"✅ Laddade {total} återförsäljare"
            )
            self._on_search()  # Behåll rätt träffantal även efter omladdning.
            _log.debug("DealersWidget uppdaterad: %d poster", total)
        except Exception as exc:
            self._status_label.setText(f"❌ Fel vid laddning: {exc}")
            _log.error("Refresh-fel: %s", exc, exc_info=True)

    def _on_search(self) -> None:
        """Filtrera tabell med QSortFilterProxyModel."""
        try:
            query = self._search_input.text().strip()
            self._proxy.setFilterFixedString(query)
            if getattr(self, "_auto_columns", False):
                self._column_fit_timer.start(250)
            visible = self._proxy.rowCount()
            total = self._model.rowCount()
            self._count_label.setText(
                f"{visible} av {total} återförsäljare"
                if query
                else f"{total} återförsäljare"
            )
        except Exception as exc:
            _log.error("Sökfel: %s", exc, exc_info=True)

    def _get_selected_dn(self) -> Optional[str]:
        """Hämta dealer number för markerad rad. None om ingen markering."""
        try:
            indexes = self._table_view.selectionModel().selectedRows()
            if not indexes:
                return None

            source_index = self._proxy.mapToSource(indexes[0])
            dealer = self._model.get_dealer_at(source_index.row())
            if dealer:
                return str(
                    dealer.get("dealer_number", dealer.get("dn", ""))
                )
            return None
        except Exception as exc:
            _log.error("Fel vid hämtning av vald ÅF: %s", exc)
            return None

    def _import_excel(self) -> None:
        """Använd samma säkra filimport som Arkiv-menyn."""
        from plugins.main_gui.dialogs.import_dialog import start_import
        start_import(self, self.app, None, self, destination="Återförsäljare")

    def _add_dealer(self) -> None:
        """Öppna AddDealerDialog för ny ÅF."""
        try:
            dialog = AddDealerDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                data = dialog.get_data()
                from plugins.main_gui.dialogs.dealer_pin import request_pin
                pin = request_pin(self, self.plugin)
                if pin is None:
                    return
                if self.plugin.add_dealer(data, pin=pin):
                    QMessageBox.information(
                        self,
                        "Tillagd",
                        f"Återförsäljare {data.get('namn', '')} tillagd",
                    )
                    self.refresh()
                else:
                    QMessageBox.warning(
                        self,
                        "Fel",
                        "Kunde inte lägga till.\n"
                        "Kontrollera om dealernumret redan finns eller om registret inte kan läsas/säkerhetskopieras.",
                    )
        except Exception as exc:
            _log.error("Lägg-till-fel: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Fel", str(exc))

    def _edit_dealer(
        self, index: Optional[QModelIndex] = None
    ) -> None:
        """Öppna AddDealerDialog för redigering av markerad ÅF."""
        try:
            dn = self._get_selected_dn()
            if not dn:
                QMessageBox.information(
                    self, "Info", "Välj en återförsäljare först"
                )
                return

            dealer = self.plugin.get_by_dn(dn)
            if not dealer:
                QMessageBox.warning(
                    self, "Fel", f"Dealernumret {dn} saknas eller förekommer flera gånger. Ingen post ändrades."
                )
                return

            dialog = AddDealerDialog(self, existing_data=dealer)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                updated = dialog.get_data()
                from plugins.main_gui.dialogs.dealer_pin import request_pin
                pin = request_pin(self, self.plugin)
                if pin is None:
                    return
                if self.plugin.update_dealer(dn, updated, expected_record=dealer, pin=pin):
                    QMessageBox.information(
                        self, "Uppdaterad", "Återförsäljare uppdaterad"
                    )
                    self.refresh()
                else:
                    QMessageBox.warning(
                        self, "Fel", "Kunde inte uppdatera. Dealernumret kan redan finnas, uppgifterna ha ändrats eller säkerhetskopieringen misslyckats."
                    )
        except Exception as exc:
            _log.error("Redigera-fel: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Fel", str(exc))

    def _delete_selected(self) -> None:
        """Ta bort markerad ÅF med bekräftelsedialog."""
        try:
            dn = self._get_selected_dn()
            if not dn:
                QMessageBox.information(
                    self, "Info", "Välj en återförsäljare först"
                )
                return

            dealer = self.plugin.get_by_dn(dn)
            if not dealer:
                QMessageBox.warning(self, "Fel", "Dealernumret saknas eller förekommer flera gånger. Ingen post togs bort.")
                return
            namn = dealer.get("namn", "Okänd")

            reply = QMessageBox.question(
                self,
                "Bekräfta borttagning",
                f"Vill du ta bort {namn} (DN: {dn})?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                from plugins.main_gui.dialogs.dealer_pin import request_pin
                pin = request_pin(self, self.plugin)
                if pin is None:
                    return
                if self.plugin.delete_dealer(dn, expected_record=dealer, pin=pin):
                    QMessageBox.information(
                        self, "Borttagen", f"{namn} har tagits bort"
                    )
                    self.refresh()
                else:
                    QMessageBox.warning(
                        self, "Fel", "Kunde inte ta bort. Uppgifterna kan ha ändrats, vara dubbla eller inte gå att säkerhetskopiera."
                    )
        except Exception as exc:
            _log.error("Borttagningsfel: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Fel", str(exc))

    def _export_json(self) -> None:
        """Exportera alla ÅF till valfri JSON-fil (atomisk skrivning)."""
        try:
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Exportera återförsäljare",
                "aterforsaljare_export.json",
                "JSON-filer (*.json);;Alla filer (*.*)",
            )
            if not filepath:
                return

            target = Path(filepath).resolve()
            protected = [self.plugin._json_path, self.plugin._json_path.parent / PASSWORD_FILENAME,
                         self.plugin._json_path.parent / PIN_FILENAME]
            if any(path is not None and target == path.resolve() for path in protected):
                raise ValueError("Exporten får inte skriva över registrets data eller lösenordsfil")
            data = self.plugin.load_from_json()
            content = json.dumps(
                data, ensure_ascii=False, indent=2, sort_keys=True
            )
            _atomic_write_text(Path(filepath), content)

            QMessageBox.information(
                self,
                "Export klar",
                f"Exporterade {len(data)} återförsäljare till:\n{filepath}",
            )
            _log.info(
                "Exporterade %d ÅF till %s", len(data), filepath
            )
        except Exception as exc:
            _log.error("Exportfel: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Exportfel", str(exc))

    def _change_dealer_pin(self) -> None:
        from plugins.main_gui.dialogs.dealer_pin import change_pin
        change_pin(self, self.plugin)

    def _change_password(self) -> None:
        """
        Byt lösenord via DealersPasswordManager.

        Hanterar att change() returnerar Tuple[bool, str]
        (till skillnad från den gamla versionen som returnerade bool).
        """
        try:
            pm = self.plugin.password_manager
            if not pm:
                QMessageBox.warning(
                    self, "Fel", "Lösenordshanterare ej tillgänglig"
                )
                return

            old_pw, ok1 = QInputDialog.getText(
                self,
                "Byt lösenord",
                "Nuvarande lösenord:",
                QLineEdit.EchoMode.Password,
            )
            if not ok1 or not old_pw:
                return

            new_pw, ok2 = QInputDialog.getText(
                self,
                "Byt lösenord",
                "Nytt lösenord (minst 4 tecken):",
                QLineEdit.EchoMode.Password,
            )
            if not ok2 or not new_pw:
                return

            confirm_pw, ok3 = QInputDialog.getText(
                self,
                "Byt lösenord",
                "Bekräfta nytt lösenord:",
                QLineEdit.EchoMode.Password,
            )
            if not ok3 or not confirm_pw:
                return

            if new_pw != confirm_pw:
                QMessageBox.warning(
                    self, "Fel", "Lösenorden matchar inte"
                )
                return

            # change() returnerar Tuple[bool, str]
            success, message = pm.change(old_pw, new_pw)
            if success:
                QMessageBox.information(self, "Klart", message)
            else:
                QMessageBox.warning(self, "Fel", message)

        except Exception as exc:
            _log.error("Lösenordsfel: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Fel", str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# ADD / EDIT DEALER DIALOG
# ══════════════════════════════════════════════════════════════════════════════


class AddDealerDialog(QDialog):
    """
    Dialog för att lägga till eller redigera återförsäljare.

    PUBLIKA METODER:
      get_data() -> Dict[str, str]

    STÖDER:
      - Skapa ny  (existing_data=None)
      - Redigera  (existing_data=Dict, DN readonly)
      - Validering: DN + Namn obligatoriska
      - Tema-medveten: inga hårdkodade färger
      - Fet text på knappar
    """

    def __init__(
        self,
        parent: QWidget,
        existing_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(parent)
        self._existing = existing_data
        self._is_edit = existing_data is not None
        self.setWindowTitle(
            "Redigera återförsäljare"
            if self._is_edit
            else "Lägg till återförsäljare"
        )
        self.setModal(True)
        self.setMinimumWidth(420)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Bygg formulär. Inga hårdkodade färger."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── FORMULÄR ──
        form_group = QGroupBox(
            "Redigera uppgifter" if self._is_edit else "Nya uppgifter"
        )
        form_group.setObjectName("FormGroup")
        form_layout = QGridLayout(form_group)
        form_layout.setSpacing(10)

        # Dealer Number
        lbl_dn = QLabel("Dealer Number:")
        _set_bold(lbl_dn)
        form_layout.addWidget(lbl_dn, 0, 0)

        self._dn_input = QLineEdit()
        self._dn_input.setObjectName("DNInput")
        self._dn_input.setPlaceholderText("T.ex. 12345")
        if self._existing:
            dn_val = str(
                self._existing.get(
                    "dealer_number", self._existing.get("dn", "")
                )
            )
            self._dn_input.setText(dn_val)
        form_layout.addWidget(self._dn_input, 0, 1)

        # Namn
        lbl_namn = QLabel("Namn:")
        _set_bold(lbl_namn)
        form_layout.addWidget(lbl_namn, 1, 0)

        self._namn_input = QLineEdit()
        self._namn_input.setObjectName("NamnInput")
        self._namn_input.setPlaceholderText("Företagsnamn")
        if self._existing:
            self._namn_input.setText(
                str(self._existing.get("namn", ""))
            )
        form_layout.addWidget(self._namn_input, 1, 1)

        # Org.nr
        lbl_orgnr = QLabel("Person-/organisationsnummer:")
        _set_bold(lbl_orgnr)
        form_layout.addWidget(lbl_orgnr, 2, 0)

        self._orgnr_input = QLineEdit()
        self._orgnr_input.setObjectName("OrgnrInput")
        self._orgnr_input.setPlaceholderText("T.ex. 556123-4567")
        if self._existing:
            self._orgnr_input.setText(
                str(self._existing.get("orgnr", ""))
            )
        form_layout.addWidget(self._orgnr_input, 2, 1)

        self._extra_inputs = {}
        for row, (key, label) in enumerate(list(FIELDS.items())[3:], 3):
            heading = QLabel(label + ":")
            _set_bold(heading)
            editor = QLineEdit()
            if self._existing and self._existing.get(key) is not None:
                editor.setText(str(self._existing[key]))
            form_layout.addWidget(heading, row, 0)
            form_layout.addWidget(editor, row, 1)
            self._extra_inputs[key] = editor

        layout.addWidget(form_group)

        # ── INFO ──
        info = QLabel("* Dealer Number och Namn är obligatoriska")
        info.setObjectName("InfoLabel")
        info_font = QFont()
        info_font.setPointSize(9)
        info_font.setItalic(True)
        info.setFont(info_font)
        info.setWordWrap(True)
        layout.addWidget(info)

        # ── KNAPPAR ──
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        btn_cancel = QPushButton("Avbryt")
        btn_cancel.setObjectName("SecondaryButton")
        _set_bold(btn_cancel)
        btn_cancel.setMinimumHeight(34)
        btn_cancel.setMinimumWidth(100)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_ok = QPushButton(
            "💾 Spara" if self._is_edit else "➕ Lägg till"
        )
        btn_ok.setObjectName("PrimaryButton")
        _set_bold(btn_ok)
        btn_ok.setMinimumHeight(34)
        btn_ok.setMinimumWidth(120)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._validate_and_accept)
        btn_layout.addWidget(btn_ok)

        layout.addLayout(btn_layout)

    def _validate_and_accept(self) -> None:
        """Validera obligatoriska fält innan accept."""
        dn = self._dn_input.text().strip()
        namn = self._namn_input.text().strip()

        if not dn:
            QMessageBox.warning(
                self, "Saknas", "Dealer Number är obligatoriskt"
            )
            self._dn_input.setFocus()
            return

        if not namn:
            QMessageBox.warning(
                self, "Saknas", "Namn är obligatoriskt"
            )
            self._namn_input.setFocus()
            return

        self.accept()

    def get_data(self) -> Dict[str, str]:
        """Hämta formulärdata som Dict."""
        return {
            "dealer_number": self._dn_input.text().strip().upper(),
            "namn": self._namn_input.text().strip(),
            "orgnr": self._orgnr_input.text().strip(),
            **{key: editor.text().strip() for key, editor in self._extra_inputs.items()},
        }


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def _set_bold(widget: Any) -> None:
    """
    Sätt fet text på widget.

    Återanvändbar helper för knappar och labels.
    Undviker kodduplicering.

    Args:
        widget: QWidget (QPushButton, QLabel etc.)
    """
    font = QFont()
    font.setBold(True)
    widget.setFont(font)
