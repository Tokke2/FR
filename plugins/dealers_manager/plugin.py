# -*- coding: utf-8 -*-
# Fil: plugins/dealers_manager/plugin.py
# Copyright © 2025 Rickard Längkvist

"""
Dealers Manager Plugin v2.2.0 (PySide6)

Hanterar återförsäljare i JSON med Excel-import.

Konverterad från: Script/db_config.py + Script/import_aterforsaljare.py

ANSVAR:
  - CRUD för återförsäljare (JSON-lagring, atomisk skrivning)
  - Excel-import via excel_reader.py (header-detektering, synonym-matchning)
  - Lösenordsskydd via password_manager.py (SHA-256 + salt)
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

    HEADERS: Final[List[str]] = ["Dealer Number", "Namn", "Org.nr"]
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

        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_DN:
                return str(dealer.get("dealer_number", dealer.get("dn", "")))
            if col == self.COL_NAMN:
                return str(dealer.get("namn", ""))
            if col == self.COL_ORGNR:
                return str(dealer.get("orgnr", ""))

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

    def load_from_json(self) -> List[Dict[str, Any]]:
        """
        Läs återförsäljare från JSON-fil.

        Returns:
            Lista med återförsäljare-dict. Tom lista vid fel eller saknad fil.
        """
        try:
            if not self._json_path or not self._json_path.exists():
                _log.debug("JSON-fil saknas: %s", self._json_path)
                return []

            raw = self._read_json(self._json_path)

            if isinstance(raw, dict):
                result = [raw]
            elif isinstance(raw, list):
                result = [x for x in raw if isinstance(x, dict)]
            else:
                _log.warning(
                    "Oväntat JSON-format i %s", self._json_path
                )
                return []

            _log.debug("Laddade %d återförsäljare från JSON", len(result))
            return result

        except Exception as exc:
            _log.error(
                "Fel vid läsning av återförsäljare: %s",
                exc, exc_info=True,
            )
            return []

    def save_to_json(
        self,
        data: Union[List[Dict[str, Any]], Dict[str, Any]],
    ) -> bool:
        """
        Spara återförsäljare till JSON-fil (atomiskt).

        Args:
            data: Lista eller enskild dict

        Returns:
            True vid framgång, False vid fel

        Emittar:
            dealers.saved
        """
        try:
            if isinstance(data, dict):
                data_list: List[Dict[str, Any]] = [data]
            elif isinstance(data, list):
                data_list = [x for x in data if isinstance(x, dict)]
            else:
                _log.error("Ogiltigt data-format: %s", type(data))
                return False

            if not self._json_path:
                _log.error("json_path ej satt – kan inte spara")
                return False

            self._write_json(self._json_path, data_list)
            _log.info(
                "Sparade %d återförsäljare till %s",
                len(data_list), self._json_path,
            )
            self._emit_safe("dealers.saved", {"count": len(data_list)})
            return True

        except Exception as exc:
            _log.error(
                "Fel vid sparande av återförsäljare: %s",
                exc, exc_info=True,
            )
            return False

    def get_all_dealers(self) -> List[Dict[str, Any]]:
        """Alias för load_from_json(). Tom lista vid fel."""
        try:
            return self.load_from_json()
        except Exception as exc:
            _log.error("Fel i get_all_dealers: %s", exc, exc_info=True)
            return []

    def get_by_dn(self, dn: str) -> Optional[Dict[str, Any]]:
        """
        Hämta återförsäljare med specifikt dealer number.

        Args:
            dn: Dealer number (case-insensitive)

        Returns:
            Dict eller None om ej hittad
        """
        try:
            target = dn.strip().upper()
            for dealer in self.load_from_json():
                candidate = str(
                    dealer.get("dealer_number", dealer.get("dn", ""))
                ).strip().upper()
                if candidate == target:
                    return dealer
            return None
        except Exception as exc:
            _log.error("Fel i get_by_dn(%s): %s", dn, exc, exc_info=True)
            return None

    def add_dealer(self, dealer_data: Dict[str, Any]) -> bool:
        """
        Lägg till ny återförsäljare. Förhindrar dubbletter på DN.

        Args:
            dealer_data: Dict med dealer_number, namn, orgnr

        Returns:
            True om tillagd, False om duplikat eller fel

        Emittar:
            dealers.added
        """
        try:
            dn = str(
                dealer_data.get("dealer_number", dealer_data.get("dn", ""))
            ).strip().upper()

            if not dn:
                _log.warning("Försökte lägga till ÅF utan dealer_number")
                return False

            namn = str(dealer_data.get("namn", "")).strip()
            if not namn:
                _log.warning("Försökte lägga till ÅF utan namn")
                return False

            dealers = self.load_from_json()
            for existing in dealers:
                existing_dn = str(
                    existing.get("dealer_number", existing.get("dn", ""))
                ).strip().upper()
                if existing_dn == dn:
                    _log.warning("ÅF med DN %s finns redan", dn)
                    return False

            normalized: Dict[str, Any] = {
                "dealer_number": dn,
                "namn": namn,
                "orgnr": str(dealer_data.get("orgnr", "")).strip(),
            }
            dealers.append(normalized)

            if self.save_to_json(dealers):
                _log.info("Lade till ÅF: %s (%s)", namn, dn)
                self._emit_safe("dealers.added", {"dn": dn, "namn": namn})
                self.sync_to_db(dealers)
                return True
            return False

        except Exception as exc:
            _log.error("Fel i add_dealer: %s", exc, exc_info=True)
            return False

    def update_dealer(
        self, dn: str, updated_data: Dict[str, Any]
    ) -> bool:
        """
        Uppdatera befintlig återförsäljare.

        Args:
            dn:           Dealer number att uppdatera
            updated_data: Nya fältvärden (namn, orgnr etc.)

        Returns:
            True vid framgång, False om ej hittad eller fel

        Emittar:
            dealers.updated
        """
        try:
            target = dn.strip().upper()
            dealers = self.load_from_json()
            found = False

            for i, dealer in enumerate(dealers):
                existing_dn = str(
                    dealer.get("dealer_number", dealer.get("dn", ""))
                ).strip().upper()
                if existing_dn == target:
                    dealers[i].update(updated_data)
                    dealers[i]["dealer_number"] = target
                    found = True
                    break

            if not found:
                _log.warning(
                    "ÅF med DN %s hittades inte för uppdatering", dn
                )
                return False

            if self.save_to_json(dealers):
                _log.info("Uppdaterade ÅF: %s", dn)
                self._emit_safe("dealers.updated", {"dn": dn})
                return True
            return False

        except Exception as exc:
            _log.error(
                "Fel i update_dealer(%s): %s", dn, exc, exc_info=True
            )
            return False

    def delete_dealer(self, dn: str) -> bool:
        """
        Ta bort återförsäljare med angivet dealer number.

        Args:
            dn: Dealer number

        Returns:
            True om borttagen, False om ej hittad eller fel

        Emittar:
            dealers.deleted
        """
        try:
            target = dn.strip().upper()
            dealers = self.load_from_json()
            original_count = len(dealers)

            dealers = [
                d for d in dealers
                if str(
                    d.get("dealer_number", d.get("dn", ""))
                ).strip().upper() != target
            ]

            if len(dealers) == original_count:
                _log.warning("ÅF med DN %s hittades inte", dn)
                return False

            if self.save_to_json(dealers):
                _log.info("Tog bort ÅF med DN: %s", dn)
                self._emit_safe("dealers.deleted", {"dn": dn})
                return True
            return False

        except Exception as exc:
            _log.error(
                "Fel i delete_dealer(%s): %s", dn, exc, exc_info=True
            )
            return False

    def get_count(self) -> int:
        """Returnera antal återförsäljare. 0 vid fel."""
        try:
            return len(self.load_from_json())
        except Exception as exc:
            _log.error("Fel i get_count: %s", exc, exc_info=True)
            return 0

    def sync_to_db(
        self,
        dealers: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        Synkronisera återförsäljare till databas via core_database plugin.

        Args:
            dealers: Lista att synka. Laddar från JSON om None.

        Returns:
            Antal synkade poster. 0 om DB saknas eller fel.

        Emittar:
            dealers.synced
        """
        try:
            if dealers is None:
                dealers = self.load_from_json()

            db = self._get_plugin_safe("core_database")
            if not db:
                _log.debug("core_database saknas – hoppar DB-sync")
                return 0

            count = 0
            with db.get_connection() as conn:
                cur = conn.cursor()
                for dealer in dealers:
                    dn = str(
                        dealer.get("dealer_number", dealer.get("dn", ""))
                    ).strip()
                    namn = str(dealer.get("namn", "")).strip()
                    orgnr = str(dealer.get("orgnr", "")).strip()

                    if not dn or not namn:
                        continue

                    cur.execute(
                        """INSERT OR REPLACE INTO "aterforsaljare"
                           (dn, namn, orgnr, updated_at)
                           VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                        (dn, namn, orgnr),
                    )
                    count += 1
                conn.commit()

            _log.info("Synkade %d ÅF till DB", count)
            self._emit_safe("dealers.synced", {"count": count})
            return count

        except Exception as exc:
            _log.error("Fel i sync_to_db: %s", exc, exc_info=True)
            return 0

    # ──────────────────────────────────────────────────────────────────────
    # EXCEL-IMPORT (via import_logic/excel_reader.py)
    # ──────────────────────────────────────────────────────────────────────

    def import_from_excel(
        self,
        filepath: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> Dict[str, Any]:
        """
        Importera återförsäljare från Excel-fil.

        Använder import_logic.excel_reader.read_excel_with_header_detection()
        för automatisk header-detektering (strategi 1–4).
        Kolumnmatchning via import_logic/synonyms.py.

        Args:
            filepath: Sökväg till Excel-fil. Öppnar filväljare om None.
            parent:   Förälder för dialoger

        Returns:
            Dict med:
              success:           bool
              total_imported:    int
              processed_sheets:  List[str]
              skipped_sheets:    List[str]
              error:             Optional[str]

        Emittar:
            dealers.imported
        """
        result: Dict[str, Any] = {
            "success": False,
            "total_imported": 0,
            "processed_sheets": [],
            "skipped_sheets": [],
            "error": None,
        }

        try:
            if not PANDAS_AVAILABLE:
                result["error"] = (
                    "pandas saknas – pip install pandas openpyxl"
                )
                _log.error(result["error"])
                return result

            if not filepath:
                chosen, _ = QFileDialog.getOpenFileName(
                    parent,
                    "Välj Excel-fil med återförsäljare",
                    "",
                    "Excel-filer (*.xlsx *.xls);;Alla filer (*.*)",
                )
                if not chosen:
                    result["error"] = "Ingen fil vald"
                    return result
                filepath = chosen

            path = Path(filepath)
            if not path.exists():
                result["error"] = f"Filen finns inte: {path}"
                _log.error(result["error"])
                return result

            engine = get_excel_engine(path)
            if not engine:
                result["error"] = (
                    f"Filformatet stöds ej eller saknar engine: "
                    f"{path.suffix}"
                )
                _log.error(result["error"])
                return result

            _log.info(
                "Importerar Excel: %s (engine=%s)", path.name, engine
            )

            xls = pd.ExcelFile(path, engine=engine)
            imported_records: List[Dict[str, Any]] = []

            for sheet_name in xls.sheet_names:
                if sheet_name.strip().lower() in SKIP_SHEETS:
                    result["skipped_sheets"].append(
                        f"{sheet_name} (hoppad)"
                    )
                    _log.debug("Hoppar blad: %s", sheet_name)
                    continue

                sheet_result = self._process_excel_sheet(
                    xls, sheet_name
                )

                if sheet_result["skipped"]:
                    result["skipped_sheets"].append(
                        f"{sheet_name} ({sheet_result['reason']})"
                    )
                    continue

                imported_records.extend(sheet_result["records"])
                result["processed_sheets"].append(
                    f"{sheet_name} "
                    f"({len(sheet_result['records'])} rader)"
                )
                result["total_imported"] += len(sheet_result["records"])

            if imported_records:
                self._merge_dealers(imported_records)
                _log.info(
                    "Import klar: %d poster från %d blad",
                    result["total_imported"],
                    len(result["processed_sheets"]),
                )

            result["success"] = True
            self._emit_safe(
                "dealers.imported",
                {
                    "count": result["total_imported"],
                    "file": str(path.name),
                },
            )

        except Exception as exc:
            result["error"] = str(exc)
            _log.error("Fel vid Excel-import: %s", exc, exc_info=True)

        return result

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

    def _merge_dealers(
        self, new_records: List[Dict[str, Any]]
    ) -> None:
        """
        Merga nya poster med befintliga.

        Nya poster skriver över gamla vid DN-kollision.
        Sorterar alfabetiskt på namn efter merge.

        Args:
            new_records: Nya poster att merga in
        """
        existing = self.load_from_json()
        merged: Dict[str, Dict[str, Any]] = {}

        for rec in existing:
            dn = str(
                rec.get("dealer_number", rec.get("dn", ""))
            ).strip().upper()
            if dn:
                merged[dn] = rec

        for rec in new_records:
            dn = str(
                rec.get("dealer_number", rec.get("dn", ""))
            ).strip().upper()
            if dn:
                merged[dn] = rec

        final_list = sorted(
            merged.values(),
            key=lambda x: str(x.get("namn", "")).lower(),
        )
        self.save_to_json(final_list)
        _log.debug("Merge klar: totalt %d ÅF", len(final_list))

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
            if bus and hasattr(bus, "publish"):
                bus.publish(event, data)
                _log.debug("Event: %s %s", event, data)
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
        title = QLabel("🏢 Återförsäljare")
        title.setObjectName("PageTitle")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
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
            "Sök på namn, dealer number, org.nr..."
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
        header.setStretchLastSection(True)
        header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self._table_view, 1)

        # ── KNAPPAR ──
        btn_group = QGroupBox("Åtgärder")
        btn_group.setObjectName("ActionGroup")
        btn_layout = QHBoxLayout(btn_group)

        buttons_config: List[Dict[str, Any]] = [
            {
                "text": "📥 Importera Excel",
                "name": "PrimaryButton",
                "tooltip": "Importera återförsäljare från Excel-fil",
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
                "text": "📤 Exportera JSON",
                "name": "SecondaryButton",
                "tooltip": "Exportera alla återförsäljare till JSON-fil",
                "handler": self._export_json,
            },
            {
                "text": "🔑 Lösenord",
                "name": "SecondaryButton",
                "tooltip": "Byt lösenord för redigering",
                "handler": self._change_password,
            },
        ]

        for cfg in buttons_config:
            btn = QPushButton(cfg["text"])
            btn.setObjectName(cfg["name"])
            btn.setToolTip(cfg["tooltip"])
            _set_bold(btn)
            btn.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            btn.setMinimumHeight(36)
            btn.clicked.connect(cfg["handler"])
            btn_layout.addWidget(btn)

        layout.addWidget(btn_group)

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

    def refresh(self) -> None:
        """Ladda data från plugin och uppdatera tabell."""
        try:
            data = self.plugin.load_from_json()
            self._model.set_data(data)
            total = self._model.rowCount()
            self._status_label.setText(
                f"✅ Laddade {total} återförsäljare"
            )
            self._count_label.setText(f"{total} återförsäljare")
            _log.debug("DealersWidget uppdaterad: %d poster", total)
        except Exception as exc:
            self._status_label.setText(f"❌ Fel vid laddning: {exc}")
            _log.error("Refresh-fel: %s", exc, exc_info=True)

    def _on_search(self) -> None:
        """Filtrera tabell med QSortFilterProxyModel."""
        try:
            query = self._search_input.text().strip()
            self._proxy.setFilterFixedString(query)
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
        """Starta Excel-import via plugin.import_from_excel()."""
        try:
            result = self.plugin.import_from_excel(parent=self)
            if result["success"]:
                lines = [
                    "Import klar!",
                    "",
                    f"Totalt: {result['total_imported']} poster",
                ]
                if result["processed_sheets"]:
                    lines += ["", "Bearbetade blad:"]
                    lines += [f"  • {s}" for s in result["processed_sheets"]]
                if result["skipped_sheets"]:
                    lines += ["", "Hoppade blad:"]
                    lines += [f"  • {s}" for s in result["skipped_sheets"]]

                QMessageBox.information(
                    self, "Import klar", "\n".join(lines)
                )
                self.refresh()
            else:
                QMessageBox.critical(
                    self,
                    "Import misslyckades",
                    result.get("error", "Okänt fel"),
                )
        except Exception as exc:
            _log.error("Import-fel: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Fel", str(exc))

    def _add_dealer(self) -> None:
        """Öppna AddDealerDialog för ny ÅF."""
        try:
            dialog = AddDealerDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                data = dialog.get_data()
                if self.plugin.add_dealer(data):
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
                        "Dealer Number kanske redan finns.",
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
                    self, "Fel", f"Hittade inte ÅF med DN: {dn}"
                )
                return

            dialog = AddDealerDialog(self, existing_data=dealer)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                updated = dialog.get_data()
                if self.plugin.update_dealer(dn, updated):
                    QMessageBox.information(
                        self, "Uppdaterad", "Återförsäljare uppdaterad"
                    )
                    self.refresh()
                else:
                    QMessageBox.warning(
                        self, "Fel", "Kunde inte uppdatera"
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
            namn = dealer.get("namn", "Okänd") if dealer else "Okänd"

            reply = QMessageBox.question(
                self,
                "Bekräfta borttagning",
                f"Vill du ta bort {namn} (DN: {dn})?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                if self.plugin.delete_dealer(dn):
                    QMessageBox.information(
                        self, "Borttagen", f"{namn} har tagits bort"
                    )
                    self.refresh()
                else:
                    QMessageBox.warning(
                        self, "Fel", "Kunde inte ta bort"
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
            if self._is_edit:
                self._dn_input.setReadOnly(True)
                self._dn_input.setToolTip("DN kan inte ändras")
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
        lbl_orgnr = QLabel("Org.nr:")
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
