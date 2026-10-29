# -*- coding: utf-8 -*-
# Fil: plugins/about/plugin.py
"""
About Plugin v3.0.0

Informativ "Om systemet"-sida som beskriver hur hela fordonsregistreringssystemet
fungerar, inklusive arkitektur, dataflöden, tekniska detaljer och systemhälsa.

Copyright © 2026 Rickard Längkvist
Alla rättigheter förbehållna.

FUNKTIONER (1-15):
    1. get_system_health() - Systemhälsostatus
    2. get_plugin_dependencies_graph() - Beroendeträd för plugins
    3. get_event_statistics() - Event-statistik från core_logger
    4. get_schema_summary() - Sammanfattning av aktiva scheman
    5. get_recent_activity() - Senaste aktiviteter
    6. export_system_report() - Exportera systemrapport
    7. get_disk_usage() - Diskanvändning för data-mappar
    8. get_config_summary() - Konfigurationsöversikt
    9. get_error_log_summary() - Senaste fel från loggar
    10. refresh_all_data() - Uppdatera all dynamisk data
    11. get_plugin_info() - Detaljerad info om specifik plugin
    12. get_ts_spec_status() - Status för ts_spec_import
    13. get_system_info() - Systeminformation (Python, OS, etc.)
    14. get_memory_usage() - Minnesanvändning
    15. get_diagnostics() - Komplett diagnostik

SAMARBETE:
    - ts_spec_import: Hämtar schema-status
    - ts_schema_manager: Hämtar aktiv version
    - core_logger: Hämtar event-statistik
    - core_config: Hämtar konfiguration
    - Alla plugins: Visar status och beroenden
"""

from __future__ import annotations

import gc
import json
import logging
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, TYPE_CHECKING

from core.plugin_base import PluginBase

# PySide6 (optional - för GUI)
try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QScrollArea, QTabWidget, QTextEdit, QTableWidget, 
        QTableWidgetItem, QHeaderView, QMessageBox, QApplication
    )
    from PySide6.QtGui import QColor, QBrush
    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False
    # Dummy för type hints
    QWidget = object

if TYPE_CHECKING:
    from core.application import Application

# ══════════════════════════════════════════════════════════════════════════════
# COPYRIGHT & CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "3.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"

# Cache-timeout i sekunder
CACHE_TIMEOUT: Final[int] = 30


def get_copyright_year() -> int:
    """Hämta aktuellt år."""
    return datetime.now().year


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {get_copyright_year()} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def setup_logger() -> logging.Logger:
    """Konfigurera och returnera logger. KRASCHSÄKER."""
    try:
        log = logging.getLogger("about")
        if not log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%H:%M:%S"
            ))
            log.addHandler(handler)
            log.setLevel(logging.INFO)
        return log
    except Exception:
        return logging.getLogger(__name__)


logger = setup_logger()


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS — Alla är 100% kraschsäkra
# ══════════════════════════════════════════════════════════════════════════════

def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Robust plugin-hämtning. KRASCHSÄKER.
    
    Försöker i ordning:
    1. app.get_plugin(name)
    2. app.plugin_loader.get_plugin(name)
    3. app.plugin_manager.get_plugin(name)
    4. getattr(app, name)
    """
    if app is None:
        return None

    normalized = name.lower().replace(" ", "_").replace("-", "_")
    names_to_try = [name, normalized]
    
    for try_name in names_to_try:
        # app.get_plugin()
        if hasattr(app, 'get_plugin'):
            try:
                result = app.get_plugin(try_name)
                if result is not None:
                    return result
            except Exception:
                pass
        
        # plugin_loader
        if hasattr(app, 'plugin_loader'):
            try:
                result = app.plugin_loader.get_plugin(try_name)
                if result is not None:
                    return result
            except Exception:
                pass
        
        # plugin_manager (legacy)
        if hasattr(app, 'plugin_manager'):
            try:
                result = app.plugin_manager.get_plugin(try_name)
                if result is not None:
                    return result
            except Exception:
                pass
        
        # Direkt attribut
        try:
            result = getattr(app, try_name, None)
            if result is not None:
                return result
        except Exception:
            pass

    return None


def get_loaded_plugins(app: Any) -> Dict[str, Any]:
    """Hämta alla laddade plugins. KRASCHSÄKER."""
    if app is None:
        return {}
    
    try:
        loader = getattr(app, 'plugin_loader', None)
        if loader:
            if hasattr(loader, 'get_all_plugins'):
                return loader.get_all_plugins() or {}
            if hasattr(loader, 'plugins'):
                return loader.plugins or {}
    except Exception:
        pass
    
    return {}


def get_event_bus(app: Any) -> Optional[Any]:
    """Hämta event bus. KRASCHSÄKER."""
    if app is None:
        return None

    for attr in ('event_bus', 'events', '_event_bus'):
        try:
            bus = getattr(app, attr, None)
            if bus is not None:
                return bus
        except Exception:
            pass

    return None


def emit_event_safe(app: Any, event_name: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """Emit event säkert. KRASCHSÄKER."""
    try:
        bus = get_event_bus(app)
        if bus and hasattr(bus, 'emit'):
            bus.emit(event_name, data or {})
            return True
    except Exception as e:
        logger.debug(f"Event emit failed: {event_name}: {e}")
    return False


def get_config_value(app: Any, key: str, default: Any = None) -> Any:
    """Hämta config-värde säkert. KRASCHSÄKER."""
    try:
        # Försök core_config plugin
        config = get_plugin_safe(app, "core_config")
        if config and hasattr(config, 'get'):
            result = config.get(key)
            if result is not None:
                return result
        
        # Fallback till app.config
        cfg = getattr(app, 'config', None)
        if cfg:
            if hasattr(cfg, 'get'):
                return cfg.get(key, default)
            elif isinstance(cfg, dict):
                return cfg.get(key, default)
    except Exception:
        pass
    return default


def format_bytes(size: int) -> str:
    """Formatera bytes till läsbar sträng. KRASCHSÄKER."""
    try:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
    except Exception:
        return "? B"


# ══════════════════════════════════════════════════════════════════════════════
# CONTENT - SYSTEM DOCUMENTATION
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_OVERVIEW: Final[str] = """
<h2>🚗 Fordonsregistrering</h2>

<p>Detta system hanterar fordonsregistreringar mot <b>Transportstyrelsen (TS)</b>. 
Systemet är byggt med en <b>modulär, plugin-baserad arkitektur</b> som gör det 
flexibelt och lätt att underhålla.</p>

<h3>Huvudfunktioner:</h3>
<ul>
    <li>📥 <b>Import av fordonsdata</b> från SAP och Dispatch-filer</li>
    <li>📋 <b>Schema-driven formatering</b> baserat på TS postbeskrivningar</li>
    <li>📤 <b>Generering av TS-filer</b> (PT28 + PT45 + PT99)</li>
    <li>📨 <b>Hantering av svarsfiler</b> från Transportstyrelsen</li>
    <li>📊 <b>Rapporter och historik</b></li>
</ul>

<h3>Nyckelkoncept:</h3>
<ul>
    <li><b>Datadriven:</b> TS-specifikationer importeras som JSON-scheman</li>
    <li><b>Plugin-baserad:</b> All affärslogik finns i plugins, inte i core</li>
    <li><b>Event-driven:</b> Plugins kommunicerar via events</li>
    <li><b>Framtidssäker:</b> Nya posttyper och fält hanteras automatiskt</li>
</ul>
"""

ARCHITECTURE_INFO: Final[str] = """
<h2>🏗️ Systemarkitektur</h2>

<h3>Mappstruktur:</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4;">
Filregistrering/
├── core/                    # LÅST (ändras ej)
│   ├── application.py       # Huvudapplikation
│   ├── plugin_base.py       # Bas för alla plugins
│   ├── plugin_loader.py     # Laddar/aktiverar plugins
│   └── event_bus.py         # Event-kommunikation
│
├── plugins/                 # ALL AFFÄRSLOGIK HÄR
│   ├── ts_spec_import/      # Importerar TS Excel-spec
│   ├── ts_schema_manager/   # Source of truth för scheman
│   ├── ts_file_generator/   # Genererar TS-filer
│   ├── vehicle_registry/    # Fordonsdata + VIN
│   ├── data_mapping/        # Kolumnmappning
│   ├── identity_post/       # PT28 - Identitetspost
│   ├── vehicle_registration_post/ # PT45 - Registreringspost
│   ├── end_post/            # PT99 - Slutpost
│   └── about/               # Denna plugin
│
├── data/                    # DATA & KONFIG
│   ├── ts_specs/            # Scheman/versioner (JSON)
│   ├── vehicles/            # Fordonsdata per år
│   └── transportstyrelsen/  # Status/backup
│
├── In/                      # Svarsfiler från TS
├── ut/                      # Genererade TS-filer
└── dispatch/                # Dispatch-filer
</pre>

<h3>Plugin-kommunikation:</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4;">
# Event-baserad (lös koppling)
emit_event_safe(app, "ts:schema:loaded", {"version": "2025-01"})

# Direkt access (säker)
schema_mgr = get_plugin_safe(app, "ts_schema_manager")
if schema_mgr:
    schema = schema_mgr.get_schema("45")
</pre>
"""

DATAFLOW_INFO: Final[str] = """
<h2>🔄 Dataflöden</h2>

<h3>1. Schema-import (engångsprocess)</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4;">
┌─────────────────────┐
│  TS Excel-spec      │   Transportstyrelsens postbeskrivning
│  (PT28, PT45, PT99) │   i Excel-format
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  ts_spec_import     │   Parser Excel, skapar PostSpec/FieldSpec
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  ts_schema_manager  │   Sparar som JSON i data/ts_specs/
│  (source of truth)  │   Hanterar versioner
└─────────────────────┘
</pre>

<h3>2. Fordonsregistrering (dagligt flöde)</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4;">
┌──────────────┐     ┌──────────────┐
│  SAP Excel   │     │  Dispatch    │
│  (modelldata)│     │  (VIN-lista) │
└──────┬───────┘     └──────┬───────┘
       │                    │
       ▼                    ▼
┌──────────────┐     ┌──────────────┐
│  sap_import  │     │dispatch_viewer│
└──────┬───────┘     └──────┬───────┘
       │                    │
       └────────┬───────────┘
                │
                ▼
       ┌────────────────┐
       │  data_mapping  │   Mapps VIN → fordonsdata
       └────────┬───────┘
                │
                ▼
       ┌────────────────┐
       │ts_file_generator│   Orkestrerar postgenerering
       └────────┬───────┘
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌────────┐ ┌────────┐ ┌────────┐
│PT28    │ │PT45    │ │PT99    │
└───┬────┘ └───┬────┘ └───┬────┘
    │          │          │
    └──────────┴──────────┘
                │
                ▼
       ┌────────────────┐
       │   ut/BLN0001   │   TS-fil (2500 tecken/rad, Latin-1)
       └────────────────┘
</pre>
"""

TS_FORMAT_INFO: Final[str] = """
<h2>📋 TS-filformat</h2>

<h3>Hårda krav:</h3>
<table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
    <tr style="background: #333;">
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Krav</th>
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Värde</th>
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Beskrivning</th>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;">Radlängd</td>
        <td style="padding: 8px; border: 1px solid #555; color: #4ec9b0;"><b>EXAKT 2500 tecken</b></td>
        <td style="padding: 8px; border: 1px solid #555;">Varje rad måste vara exakt 2500 tecken</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;">Encoding</td>
        <td style="padding: 8px; border: 1px solid #555; color: #4ec9b0;"><b>ISO-8859-1 (Latin-1)</b></td>
        <td style="padding: 8px; border: 1px solid #555;">Svenska tecken (åäö) stöds</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;">Filskrivning</td>
        <td style="padding: 8px; border: 1px solid #555; color: #4ec9b0;"><b>Atomisk</b></td>
        <td style="padding: 8px; border: 1px solid #555;">Skriv .tmp → rename (säker)</td>
    </tr>
</table>

<h3>Fältformatering:</h3>
<table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
    <tr style="background: #333;">
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Typ</th>
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Kod</th>
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Justering</th>
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Padding</th>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;">Numerisk</td>
        <td style="padding: 8px; border: 1px solid #555;">N</td>
        <td style="padding: 8px; border: 1px solid #555;">Höger</td>
        <td style="padding: 8px; border: 1px solid #555;">Nollor (0)</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;">Alfanumerisk</td>
        <td style="padding: 8px; border: 1px solid #555;">AN</td>
        <td style="padding: 8px; border: 1px solid #555;">Vänster</td>
        <td style="padding: 8px; border: 1px solid #555;">Mellanslag</td>
    </tr>
</table>

<h3>Posttyper:</h3>
<table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
    <tr style="background: #333;">
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Post</th>
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Namn</th>
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Antal</th>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><b>PT28</b></td>
        <td style="padding: 8px; border: 1px solid #555;">Identitetspost</td>
        <td style="padding: 8px; border: 1px solid #555;">1 (först)</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><b>PT45</b></td>
        <td style="padding: 8px; border: 1px solid #555;">Registreringspost</td>
        <td style="padding: 8px; border: 1px solid #555;">N (per fordon)</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><b>PT99</b></td>
        <td style="padding: 8px; border: 1px solid #555;">Slutpost</td>
        <td style="padding: 8px; border: 1px solid #555;">1 (sist)</td>
    </tr>
</table>
"""

SCHEMA_INFO: Final[str] = """
<h2>📑 Schema-hantering</h2>

<h3>Source of Truth:</h3>
<p><code>ts_schema_manager</code> är <b>source of truth</b> för alla TS-scheman. 
<code>ts_spec_import</code> importerar och hanterar versioner.</p>

<h3>Schema-struktur (JSON):</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4;">
data/ts_specs/
├── 2025.01.15_1/           # Version
│   ├── PT28.json
│   ├── PT45.json
│   ├── PT99.json
│   └── manifest.json
└── 2024.06.01_1/           # Äldre version
    └── ...
</pre>

<h3>PostSpec-objekt:</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4;">
{
  "post_type": "45",
  "name": "Registreringspost",
  "total_length": 2500,
  "fields": [
    {
      "name": "POSTTYP",
      "position": 1,
      "length": 2,
      "field_type": "alphanumeric",
      "required": true,
      "constant_value": "45"
    },
    {
      "name": "VIN",
      "position": 50,
      "length": 17,
      "field_type": "alphanumeric",
      "required": true
    }
  ]
}
</pre>

<h3>Användning:</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4;">
# Hämta schema via ts_spec_import
ts_spec = get_plugin_safe(app, "ts_spec_import")
if ts_spec:
    schema = ts_spec.get_schema("45")
    record = schema.format_record(data)
    # → exakt 2500 tecken, Latin-1
</pre>
"""

USER_GUIDE: Final[str] = """
<h2>📖 Användarguide</h2>

<h3>Steg-för-steg: Registrera fordon</h3>

<h4>1. Importera TS-specifikation (första gången)</h4>
<ol>
    <li>Gå till <b>📋 TS Schema</b></li>
    <li>Klicka <b>📥 Importera TS-spec från Excel</b></li>
    <li>Välj Transportstyrelsens postbeskrivning (Excel)</li>
    <li>Systemet skapar en ny version och sätter den som aktiv</li>
</ol>

<h4>2. Importera fordonsdata</h4>
<ol>
    <li>Gå till <b>🚗 Fordonsdata</b></li>
    <li>Välj årsmodell och lägg till fordon</li>
    <li>Fyll i tekniska specifikationer</li>
    <li>Spara</li>
</ol>

<h4>3. Importera Dispatch</h4>
<ol>
    <li>Gå till <b>📥 Dispatch Import</b></li>
    <li>Ladda dispatch-fil (Excel med VIN-lista)</li>
    <li>Systemet matchar VIN mot fordonsdata</li>
</ol>

<h4>4. Generera TS-fil</h4>
<ol>
    <li>Gå till <b>⚙️ Generera TS-fil</b></li>
    <li>Välj vilka fordon som ska inkluderas</li>
    <li>Klicka <b>Generera</b></li>
    <li>Filen skapas i <code>ut/</code>-mappen</li>
</ol>

<h3>Vanliga problem:</h3>
<table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
    <tr style="background: #333;">
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Problem</th>
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Lösning</th>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;">"Ingen schema-version aktiv"</td>
        <td style="padding: 8px; border: 1px solid #555;">Importera TS-spec via Schema → Importera</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;">"VIN hittades inte"</td>
        <td style="padding: 8px; border: 1px solid #555;">Kontrollera att VIN finns i Fordonsdata</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;">"Färgkod okänd"</td>
        <td style="padding: 8px; border: 1px solid #555;">Lägg till färgmappning i Färger-sidan</td>
    </tr>
</table>
"""

DEVELOPER_INFO: Final[str] = """
<h2>👨‍💻 Utvecklarinformation</h2>

<h3>Plugin-utveckling:</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4;">
from core.plugin_base import PluginBase

class Plugin(PluginBase):
    NAME = "my_plugin"
    VERSION = "1.0.0"
    DESCRIPTION = "Min plugin"
    AUTHOR = "Rickard Längkvist"
    DEPENDENCIES = []
    
    def initialize(self):
        logger.info("Plugin initierad")
    
    def activate(self):
        self.is_active = True
    
    def create_widget(self, parent=None):
        return MyWidget(self.app, parent)
</pre>

<h3>Säker plugin-access:</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4;">
# RÄTT: Använd get_plugin_safe (aldrig exception)
ts_spec = get_plugin_safe(app, "ts_spec_import")
if ts_spec:
    schema = ts_spec.get_schema("45")

# RÄTT: Emit event säkert
emit_event_safe(app, "my_event", {"data": "value"})
</pre>

<h3>Viktiga event-namn:</h3>
<table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
    <tr style="background: #333;">
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Event</th>
        <th style="padding: 8px; text-align: left; border: 1px solid #555;">Beskrivning</th>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><code>ts_spec:imported</code></td>
        <td style="padding: 8px; border: 1px solid #555;">Schema importerades</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><code>ts_spec:version_changed</code></td>
        <td style="padding: 8px; border: 1px solid #555;">Aktiv version byttes</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><code>ts:file_generated</code></td>
        <td style="padding: 8px; border: 1px solid #555;">TS-fil genererades</td>
    </tr>
</table>
"""

CREDITS_TEMPLATE: Final[str] = """
<h2>ℹ️ Om programmet</h2>

<h3>Fordonsregistrering</h3>
<p>System för automatiserad fordonsregistrering mot Transportstyrelsen.</p>

<table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
    <tr>
        <td style="padding: 8px; border: 1px solid #555; width: 150px;"><b>Version:</b></td>
        <td style="padding: 8px; border: 1px solid #555;">{app_version}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><b>Utvecklare:</b></td>
        <td style="padding: 8px; border: 1px solid #555;">{author}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><b>Python:</b></td>
        <td style="padding: 8px; border: 1px solid #555;">{python_version}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><b>Plattform:</b></td>
        <td style="padding: 8px; border: 1px solid #555;">{platform}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><b>Schema-version:</b></td>
        <td style="padding: 8px; border: 1px solid #555;">{schema_version}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #555;"><b>Minne:</b></td>
        <td style="padding: 8px; border: 1px solid #555;">{memory_usage}</td>
    </tr>
</table>

<h3>Systemhälsa:</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4;">
{system_health}
</pre>

<h3>Laddade plugins ({plugin_count}):</h3>
<pre style="background: #1e1e1e; padding: 15px; border-radius: 4px; color: #d4d4d4; max-height: 200px; overflow-y: auto;">
{plugins_list}
</pre>

<h3>Licens:</h3>
<p>{copyright}</p>
<p>Alla rättigheter förbehållna.</p>
"""


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    About Plugin v3.0.0
    
    Systemdokumentation, hälsostatus och information.
    15 publika funktioner. 100% kraschsäker.
    """
    
    NAME: str = "About"
    VERSION: str = VERSION
    DESCRIPTION: str = "Om systemet - dokumentation, hälsostatus och information (15 funktioner)"
    AUTHOR: str = AUTHOR
    DEPENDENCIES: List[str] = []
    OPTIONAL_DEPENDENCIES: List[str] = [
        "ts_spec_import",
        "ts_schema_manager",
        "core_logger",
        "core_config",
    ]

    def __init__(self, app: Application) -> None:
        """Initiera plugin."""
        super().__init__(app)
        self._widget: Optional[Any] = None
        self._cached_health: Optional[Dict[str, Any]] = None
        self._cache_timestamp: float = 0
        self._initialized: bool = False

    @property
    def copyright(self) -> str:
        """Dynamisk copyright-sträng."""
        return get_copyright_string()

    # ═══════════════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════════

    def initialize(self) -> None:
        """Initiera plugin. KRASCHSÄKER."""
        try:
            logger.info("=" * 60)
            logger.info(f"About v{VERSION}")
            logger.info(self.copyright)
            logger.info("=" * 60)
            
            self._initialized = True
            logger.info("15 public functions available")
            
        except Exception as e:
            logger.error(f"Failed to initialize: {e}")

    def init(self) -> None:
        self.initialize()

    def activate(self) -> None:
        """Aktivera plugin. KRASCHSÄKER."""
        try:
            self.is_active = True
            emit_event_safe(self.app, "about:activated", {
                "version": self.VERSION
            })
            logger.info("Activated")
        except Exception as e:
            logger.error(f"Activation failed: {e}")

    def deactivate(self) -> None:
        """Deaktivera plugin. KRASCHSÄKER."""
        try:
            self.is_active = False
            self._widget = None
            self._cached_health = None
            logger.info("Deactivated")
        except Exception as e:
            logger.error(f"Deactivation failed: {e}")

    def shutdown(self) -> None:
        self.deactivate()

    def create_widget(self, parent: Any = None) -> Optional[Any]:
        """Skapa widget. KRASCHSÄKER."""
        if not HAS_PYSIDE6:
            logger.warning("PySide6 not available - GUI disabled")
            return None

        try:
            self._widget = AboutWidget(self.app, self, parent)
            return self._widget
        except Exception as e:
            logger.error(f"Failed to create widget: {e}")
            return None

    def register_ui(self, parent: Any = None) -> Optional[Any]:
        return self.create_widget(parent)

    # ═══════════════════════════════════════════════════════════════════════════
    # FUNCTIONS 1-5
    # ═══════════════════════════════════════════════════════════════════════════

    def get_system_health(self) -> Dict[str, Any]:
        """
        1. Hämta systemhälsostatus. KRASCHSÄKER.
        
        Returns:
            Dict med hälsostatus
        """
        # Cache
        if self._cached_health and (time.time() - self._cache_timestamp) < CACHE_TIMEOUT:
            return self._cached_health
        
        health: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "overall": "healthy",
            "components": {},
            "warnings": [],
            "errors": [],
        }
        
        try:
            # ts_spec_import
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if ts_spec:
                is_ready = ts_spec.is_ready() if hasattr(ts_spec, "is_ready") else False
                active_version = ts_spec.get_active_version() if hasattr(ts_spec, "get_active_version") else None
                
                health["components"]["ts_spec_import"] = {
                    "status": "ok" if is_ready else "warning",
                    "active_version": active_version,
                    "ready": is_ready,
                }
                if not active_version:
                    health["warnings"].append("Ingen aktiv schema-version")
            else:
                health["components"]["ts_spec_import"] = {"status": "missing"}
                health["warnings"].append("ts_spec_import plugin saknas")
            
            # ts_schema_manager
            schema_mgr = get_plugin_safe(self.app, "ts_schema_manager")
            if schema_mgr:
                health["components"]["ts_schema_manager"] = {
                    "status": "ok",
                    "available": True,
                }
            else:
                health["components"]["ts_schema_manager"] = {"status": "missing"}
            
            # core_logger
            core_logger = get_plugin_safe(self.app, "core_logger")
            if core_logger:
                health["components"]["core_logger"] = {"status": "ok"}
            else:
                health["components"]["core_logger"] = {"status": "missing"}
            
            # Kolla mappar
            paths = {
                "data/ts_specs": Path("data/ts_specs"),
                "In": Path("In"),
                "ut": Path("ut"),
            }
            
            for name, path in paths.items():
                exists = path.exists()
                health["components"][f"dir:{name}"] = {
                    "status": "ok" if exists else "warning",
                    "exists": exists,
                }
                if not exists:
                    health["warnings"].append(f"Mapp saknas: {name}")
            
            # Sätt overall
            if health["errors"]:
                health["overall"] = "error"
            elif health["warnings"]:
                health["overall"] = "warning"
            
            self._cached_health = health
            self._cache_timestamp = time.time()
            
        except Exception as e:
            health["errors"].append(str(e))
            health["overall"] = "error"
        
        return health

    def get_plugin_dependencies_graph(self) -> Dict[str, List[str]]:
        """
        2. Hämta beroendeträd för alla plugins. KRASCHSÄKER.
        
        Returns:
            Dict med plugin_name -> [dependencies]
        """
        try:
            plugins = get_loaded_plugins(self.app)
            graph: Dict[str, List[str]] = {}
            
            for name, plugin in plugins.items():
                deps = []
                
                if hasattr(plugin, "DEPENDENCIES"):
                    deps.extend(plugin.DEPENDENCIES or [])
                if hasattr(plugin, "OPTIONAL_DEPENDENCIES"):
                    deps.extend(plugin.OPTIONAL_DEPENDENCIES or [])
                
                graph[name] = list(set(deps))
            
            return graph
        except Exception as e:
            logger.error(f"get_plugin_dependencies_graph failed: {e}")
            return {}

    def get_event_statistics(self) -> Dict[str, Any]:
        """
        3. Hämta event-statistik. KRASCHSÄKER.
        
        Returns:
            Dict med event-statistik
        """
        stats: Dict[str, Any] = {
            "available": False,
            "event_count": 0,
            "events": {},
        }
        
        try:
            core_logger = get_plugin_safe(self.app, "core_logger")
            if core_logger and hasattr(core_logger, "get_event_stats"):
                event_stats = core_logger.get_event_stats()
                stats["available"] = True
                stats["events"] = event_stats
                stats["event_count"] = sum(event_stats.values()) if event_stats else 0
        except Exception as e:
            stats["error"] = str(e)
        
        return stats

    def get_schema_summary(self) -> Dict[str, Any]:
        """
        4. Hämta sammanfattning av scheman. KRASCHSÄKER.
        
        Returns:
            Dict med schema-information
        """
        summary: Dict[str, Any] = {
            "active_version": None,
            "version_count": 0,
            "schemas": {},
            "total_fields": 0,
            "source": None,
        }
        
        try:
            # Försök ts_spec_import först
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if ts_spec:
                summary["source"] = "ts_spec_import"
                
                if hasattr(ts_spec, "get_active_version"):
                    summary["active_version"] = ts_spec.get_active_version()
                
                if hasattr(ts_spec, "list_versions"):
                    summary["version_count"] = len(ts_spec.list_versions())
                
                if hasattr(ts_spec, "get_all_schemas"):
                    schemas = ts_spec.get_all_schemas()
                    for pt, spec in schemas.items():
                        field_count = len(spec.fields) if hasattr(spec, "fields") else 0
                        summary["schemas"][pt] = {
                            "name": getattr(spec, "name", pt),
                            "field_count": field_count,
                        }
                        summary["total_fields"] += field_count
            else:
                # Fallback till ts_schema_manager
                schema_mgr = get_plugin_safe(self.app, "ts_schema_manager")
                if schema_mgr:
                    summary["source"] = "ts_schema_manager"
                    if hasattr(schema_mgr, "get_active_version"):
                        summary["active_version"] = schema_mgr.get_active_version()
                    if hasattr(schema_mgr, "list_versions"):
                        summary["version_count"] = len(schema_mgr.list_versions())
                        
        except Exception as e:
            summary["error"] = str(e)
        
        return summary

    def get_recent_activity(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        5. Hämta senaste aktiviteter. KRASCHSÄKER.
        
        Args:
            limit: Max antal
            
        Returns:
            Lista med aktiviteter
        """
        try:
            core_logger = get_plugin_safe(self.app, "core_logger")
            if core_logger and hasattr(core_logger, "get_event_history"):
                return core_logger.get_event_history(limit)
        except Exception as e:
            logger.debug(f"get_recent_activity failed: {e}")
        
        return []

    # ═══════════════════════════════════════════════════════════════════════════
    # FUNCTIONS 6-10
    # ═══════════════════════════════════════════════════════════════════════════

    def export_system_report(self, output_path: Optional[Path] = None) -> Optional[Path]:
        """
        6. Exportera systemrapport. KRASCHSÄKER.
        
        Args:
            output_path: Utfilssökväg (auto-genereras om None)
            
        Returns:
            Path till skapad fil eller None
        """
        try:
            if output_path is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = Path(f"ut/rapporter/system_report_{timestamp}.json")
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            report = {
                "generated_at": datetime.now().isoformat(),
                "copyright": self.copyright,
                "system": self.get_system_info(),
                "health": self.get_system_health(),
                "plugins": {},
                "schema_summary": self.get_schema_summary(),
                "disk_usage": self.get_disk_usage(),
                "config_summary": self.get_config_summary(),
            }
            
            # Plugin-info
            plugins = get_loaded_plugins(self.app)
            for name, plugin in plugins.items():
                report["plugins"][name] = {
                    "version": getattr(plugin, "VERSION", "?"),
                    "is_active": getattr(plugin, "is_active", False),
                }
            
            # Spara kraschsäkert
            fd, tmp = tempfile.mkstemp(dir=str(output_path.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, output_path)
            
            logger.info(f"System report exported: {output_path}")
            emit_event_safe(self.app, "about:report_exported", {"path": str(output_path)})
            
            return output_path
            
        except Exception as e:
            logger.error(f"export_system_report failed: {e}")
            return None

    def get_disk_usage(self) -> Dict[str, Any]:
        """
        7. Hämta diskanvändning. KRASCHSÄKER.
        
        Returns:
            Dict med mappstorlekar
        """
        usage: Dict[str, Any] = {}
        
        paths = [
            Path("data"),
            Path("logs"),
            Path("In"),
            Path("ut"),
            Path("dispatch"),
        ]
        
        for path in paths:
            try:
                if path.exists():
                    total_size = sum(
                        f.stat().st_size
                        for f in path.rglob("*")
                        if f.is_file()
                    )
                    file_count = sum(1 for f in path.rglob("*") if f.is_file())
                    
                    usage[str(path)] = {
                        "exists": True,
                        "size_bytes": total_size,
                        "size_formatted": format_bytes(total_size),
                        "file_count": file_count,
                    }
                else:
                    usage[str(path)] = {"exists": False}
            except Exception as e:
                usage[str(path)] = {"exists": True, "error": str(e)}
        
        return usage

    def get_config_summary(self) -> Dict[str, Any]:
        """
        8. Hämta konfigurationsöversikt. KRASCHSÄKER.
        
        Returns:
            Dict med konfiguration
        """
        summary: Dict[str, Any] = {
            "app_version": get_config_value(self.app, "app_version", "?"),
            "debug_mode": get_config_value(self.app, "debug", False),
            "log_level": get_config_value(self.app, "log_level", "INFO"),
        }
        
        try:
            core_config = get_plugin_safe(self.app, "core_config")
            if core_config and hasattr(core_config, "get_all"):
                all_config = core_config.get_all()
                for key in ["ts_specs_dir", "output_dir", "encoding"]:
                    if key in all_config:
                        summary[key] = all_config[key]
        except Exception:
            pass
        
        return summary

    def get_error_log_summary(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        9. Hämta senaste fel. KRASCHSÄKER.
        
        Args:
            limit: Max antal
            
        Returns:
            Lista med fel
        """
        try:
            core_logger = get_plugin_safe(self.app, "core_logger")
            if core_logger and hasattr(core_logger, "get_events_by_category"):
                return core_logger.get_events_by_category("error")[-limit:]
        except Exception:
            pass
        
        return []

    def refresh_all_data(self) -> Dict[str, Any]:
        """
        10. Uppdatera all data. KRASCHSÄKER.
        
        Returns:
            Dict med uppdaterad data
        """
        try:
            # Rensa cache
            self._cached_health = None
            self._cache_timestamp = 0
            
            data = {
                "timestamp": datetime.now().isoformat(),
                "health": self.get_system_health(),
                "schema_summary": self.get_schema_summary(),
                "plugin_count": len(get_loaded_plugins(self.app)),
            }
            
            emit_event_safe(self.app, "about:data_refreshed", data)
            
            return data
        except Exception as e:
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # FUNCTIONS 11-15
    # ═══════════════════════════════════════════════════════════════════════════

    def get_plugin_info(self, plugin_name: str) -> Dict[str, Any]:
        """
        11. Hämta info om specifik plugin. KRASCHSÄKER.
        
        Args:
            plugin_name: Plugin-namn
            
        Returns:
            Dict med plugin-info
        """
        info: Dict[str, Any] = {
            "name": plugin_name,
            "found": False,
        }
        
        try:
            plugin = get_plugin_safe(self.app, plugin_name)
            if plugin:
                info["found"] = True
                info["version"] = getattr(plugin, "VERSION", "?")
                info["description"] = getattr(plugin, "DESCRIPTION", "")
                info["author"] = getattr(plugin, "AUTHOR", "")
                info["is_active"] = getattr(plugin, "is_active", False)
                info["dependencies"] = getattr(plugin, "DEPENDENCIES", [])
                info["optional_dependencies"] = getattr(plugin, "OPTIONAL_DEPENDENCIES", [])
                
                # Diagnostik om tillgänglig
                if hasattr(plugin, "get_diagnostics"):
                    info["diagnostics"] = plugin.get_diagnostics()
        except Exception as e:
            info["error"] = str(e)
        
        return info

    def get_ts_spec_status(self) -> Dict[str, Any]:
        """
        12. Hämta status för ts_spec_import. KRASCHSÄKER.
        
        Returns:
            Dict med ts_spec_import status
        """
        status: Dict[str, Any] = {
            "available": False,
            "ready": False,
            "active_version": None,
            "version_count": 0,
            "schema_count": 0,
        }
        
        try:
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if ts_spec:
                status["available"] = True
                
                if hasattr(ts_spec, "is_ready"):
                    status["ready"] = ts_spec.is_ready()
                
                if hasattr(ts_spec, "get_active_version"):
                    status["active_version"] = ts_spec.get_active_version()
                
                if hasattr(ts_spec, "list_versions"):
                    status["version_count"] = len(ts_spec.list_versions())
                
                if hasattr(ts_spec, "get_all_schemas"):
                    status["schema_count"] = len(ts_spec.get_all_schemas())
                
                if hasattr(ts_spec, "get_diagnostics"):
                    status["diagnostics"] = ts_spec.get_diagnostics()
        except Exception as e:
            status["error"] = str(e)
        
        return status

    def get_system_info(self) -> Dict[str, Any]:
        """
        13. Hämta systeminformation. KRASCHSÄKER.
        
        Returns:
            Dict med systeminformation
        """
        try:
            return {
                "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "platform": f"{platform.system()} {platform.release()}",
                "architecture": platform.machine(),
                "cwd": os.getcwd(),
                "pid": os.getpid(),
            }
        except Exception as e:
            return {"error": str(e)}

    def get_memory_usage(self) -> Dict[str, Any]:
        """
        14. Hämta minnesanvändning. KRASCHSÄKER.
        
        Returns:
            Dict med minnesinfo
        """
        try:
            # Garbage collection
            gc.collect()
            
            # Tracked objects
            tracked = len(gc.get_objects())
            
            info: Dict[str, Any] = {
                "gc_tracked_objects": tracked,
            }
            
            # Försök psutil om tillgänglig
            try:
                import psutil
                process = psutil.Process(os.getpid())
                mem_info = process.memory_info()
                info["rss_bytes"] = mem_info.rss
                info["rss_formatted"] = format_bytes(mem_info.rss)
                info["vms_bytes"] = mem_info.vms
                info["vms_formatted"] = format_bytes(mem_info.vms)
            except ImportError:
                info["note"] = "Install psutil for detailed memory info"
            
            return info
        except Exception as e:
            return {"error": str(e)}

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        15. Hämta komplett diagnostik. KRASCHSÄKER.
        
        Returns:
            Dict med all diagnostik
        """
        try:
            return {
                "plugin_name": self.NAME,
                "plugin_version": self.VERSION,
                "copyright": self.copyright,
                "initialized": self._initialized,
                "is_active": self.is_active,
                "has_widget": self._widget is not None,
                "cache_valid": self._cached_health is not None,
                "system_info": self.get_system_info(),
                "memory_usage": self.get_memory_usage(),
                "health": self.get_system_health(),
                "plugin_count": len(get_loaded_plugins(self.app)),
                "ts_spec_status": self.get_ts_spec_status(),
                "functions_available": 15,
            }
        except Exception as e:
            return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# GUI WIDGET
# ══════════════════════════════════════════════════════════════════════════════

if HAS_PYSIDE6:
    
    class AboutWidget(QWidget):
        """
        Huvudwidget för About-sidan.
        
        Visar:
        - Systemdokumentation (tabs)
        - Hälsostatus
        - Plugin-info
        - Systeminformation
        """
        
        def __init__(
            self, 
            app: Any, 
            plugin: Plugin, 
            parent: Any = None
        ) -> None:
            """Initiera widget."""
            super().__init__(parent)
            self.app = app
            self.plugin = plugin
            self._setup_ui()
            
            # Auto-refresh var 60:e sekund
            self._refresh_timer = QTimer(self)
            self._refresh_timer.timeout.connect(self._refresh_dynamic_tabs)
            self._refresh_timer.start(60000)

        def _setup_ui(self) -> None:
            """Konfigurera UI."""
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)

            # Tabs
            self.tabs = QTabWidget()
            self.tabs.setStyleSheet("""
                QTabWidget::pane { 
                    border: 1px solid #444; 
                    border-radius: 4px; 
                    background: #2b2b2b; 
                }
                QTabBar::tab { 
                    background: #343a40; 
                    color: #fff; 
                    padding: 10px 20px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                }
                QTabBar::tab:selected { 
                    background: #007bff; 
                }
                QTabBar::tab:hover:!selected { 
                    background: #495057; 
                }
            """)
            
            # Statiska tabs
            self.tabs.addTab(self._create_content_tab(SYSTEM_OVERVIEW), "🏠 Översikt")
            self.tabs.addTab(self._create_content_tab(ARCHITECTURE_INFO), "🏗️ Arkitektur")
            self.tabs.addTab(self._create_content_tab(DATAFLOW_INFO), "🔄 Dataflöden")
            self.tabs.addTab(self._create_content_tab(TS_FORMAT_INFO), "📋 TS-format")
            self.tabs.addTab(self._create_content_tab(SCHEMA_INFO), "📑 Scheman")
            self.tabs.addTab(self._create_content_tab(USER_GUIDE), "📖 Guide")
            self.tabs.addTab(self._create_content_tab(DEVELOPER_INFO), "👨‍💻 Utvecklare")
            
            # Dynamiska tabs
            self.tabs.addTab(self._create_health_tab(), "🏥 Hälsa")
            self.tabs.addTab(self._create_credits_tab(), "ℹ️ Om")
            
            layout.addWidget(self.tabs)

        def setup_ui(self) -> None:
            self._setup_ui()

        def _create_content_tab(self, html_content: str) -> QWidget:
            """Skapa tab med HTML-innehåll."""
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("""
                QScrollArea { border: none; background: #1e1e1e; }
                QScrollBar:vertical {
                    background: #2b2b2b;
                    width: 12px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #555;
                    border-radius: 6px;
                    min-height: 30px;
                }
            """)
            
            content = QLabel()
            content.setTextFormat(Qt.RichText)
            content.setWordWrap(True)
            content.setAlignment(Qt.AlignTop)
            content.setStyleSheet("""
                QLabel { 
                    background: #1e1e1e; 
                    color: #d4d4d4; 
                    padding: 30px;
                    font-size: 14px;
                }
            """)
            content.setText(html_content)
            content.setOpenExternalLinks(True)
            
            scroll.setWidget(content)
            layout.addWidget(scroll)
            
            return widget

        def create_content_tab(self, html_content: str) -> QWidget:
            return self._create_content_tab(html_content)

        def _create_health_tab(self) -> QWidget:
            """Skapa hälsostatus-tab."""
            widget = QWidget()
            layout = QVBoxLayout(widget)
            
            # Header
            header = QHBoxLayout()
            header.addWidget(QLabel("<h2>🏥 Systemhälsa</h2>"))
            header.addStretch()
            
            refresh_btn = QPushButton("🔄 Uppdatera")
            refresh_btn.clicked.connect(self._refresh_dynamic_tabs)
            header.addWidget(refresh_btn)
            
            export_btn = QPushButton("📥 Exportera rapport")
            export_btn.clicked.connect(self._export_report)
            header.addWidget(export_btn)
            
            layout.addLayout(header)
            
            # Health table
            self.health_table = QTableWidget()
            self.health_table.setColumnCount(3)
            self.health_table.setHorizontalHeaderLabels(["Komponent", "Status", "Detaljer"])
            self.health_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.health_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            self.health_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
            self.health_table.setStyleSheet("""
                QTableWidget {
                    background: #1e1e1e;
                    color: #d4d4d4;
                    gridline-color: #444;
                }
                QHeaderView::section {
                    background: #333;
                    color: #fff;
                    padding: 8px;
                    border: 1px solid #444;
                }
            """)
            layout.addWidget(self.health_table)
            
            # Messages
            self.health_messages = QTextEdit()
            self.health_messages.setReadOnly(True)
            self.health_messages.setMaximumHeight(150)
            self.health_messages.setStyleSheet("""
                QTextEdit {
                    background: #1e1e1e;
                    color: #d4d4d4;
                    border: 1px solid #444;
                    border-radius: 4px;
                }
            """)
            layout.addWidget(self.health_messages)
            
            self._update_health_table()
            
            return widget

        def create_health_tab(self) -> QWidget:
            return self._create_health_tab()

        def _update_health_table(self) -> None:
            """Uppdatera hälsotabell."""
            health = self.plugin.get_system_health()
            
            self.health_table.setRowCount(0)
            
            for component, data in health.get("components", {}).items():
                row = self.health_table.rowCount()
                self.health_table.insertRow(row)
                
                self.health_table.setItem(row, 0, QTableWidgetItem(component))
                
                status = data.get("status", "unknown")
                status_item = QTableWidgetItem(status.upper())
                
                if status == "ok":
                    status_item.setForeground(QBrush(QColor("#4caf50")))
                elif status == "warning":
                    status_item.setForeground(QBrush(QColor("#ff9800")))
                elif status == "error":
                    status_item.setForeground(QBrush(QColor("#f44336")))
                else:
                    status_item.setForeground(QBrush(QColor("#888")))
                
                self.health_table.setItem(row, 1, status_item)
                
                details = ", ".join(f"{k}: {v}" for k, v in data.items() if k != "status")
                self.health_table.setItem(row, 2, QTableWidgetItem(details))
            
            # Messages
            messages = []
            for warn in health.get("warnings", []):
                messages.append(f"⚠️ {warn}")
            for err in health.get("errors", []):
                messages.append(f"❌ {err}")
            
            if messages:
                self.health_messages.setPlainText("\n".join(messages))
            else:
                self.health_messages.setPlainText("✅ Inga varningar eller fel")

        def update_health_table(self) -> None:
            self._update_health_table()

        def _create_credits_tab(self) -> QWidget:
            """Skapa Om-tab."""
            try:
                app_version = get_config_value(self.app, "app_version", "5.0.0")
                python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
                platform_info = f"{platform.system()} {platform.release()}"
                
                # Schema
                schema_summary = self.plugin.get_schema_summary()
                schema_version = schema_summary.get("active_version", "Ej konfigurerad")
                
                # Memory
                memory = self.plugin.get_memory_usage()
                memory_usage = memory.get("rss_formatted", "N/A")
                
                # Health
                health = self.plugin.get_system_health()
                health_lines = [f"Status: {health['overall'].upper()}"]
                health_lines.extend(health.get("warnings", [])[:3])
                system_health = "\n".join(health_lines)
                
                # Plugins
                plugins = get_loaded_plugins(self.app)
                plugins_lines = []
                for name, plugin in sorted(plugins.items()):
                    version_val = getattr(plugin, 'VERSION', '?')
                    status = "✓" if getattr(plugin, 'is_active', False) else "○"
                    plugins_lines.append(f"{status} {name} v{version_val}")
                
                plugins_list = "\n".join(plugins_lines) if plugins_lines else "Inga plugins"
                
                html = CREDITS_TEMPLATE.format(
                    app_version=app_version,
                    author=AUTHOR,
                    python_version=python_version,
                    platform=platform_info,
                    schema_version=schema_version,
                    memory_usage=memory_usage,
                    system_health=system_health,
                    plugin_count=len(plugins),
                    plugins_list=plugins_list,
                    copyright=get_copyright_string(),
                )
                
                return self._create_content_tab(html)
            except Exception as e:
                return self._create_content_tab(f"<p>Error: {e}</p>")

        def create_credits_tab(self) -> QWidget:
            return self._create_credits_tab()

        def _refresh_dynamic_tabs(self) -> None:
            """Uppdatera dynamiska tabs."""
            try:
                self._update_health_table()
                
                # Uppdatera Om-tab
                credits_index = self.tabs.count() - 1
                current_tab = self.tabs.currentIndex()
                
                self.tabs.removeTab(credits_index)
                self.tabs.addTab(self._create_credits_tab(), "ℹ️ Om")
                
                if current_tab < self.tabs.count():
                    self.tabs.setCurrentIndex(current_tab)
            except Exception as e:
                logger.error(f"Failed to refresh tabs: {e}")

        def refresh_dynamic_tabs(self) -> None:
            self._refresh_dynamic_tabs()

        def _export_report(self) -> None:
            """Exportera rapport."""
            output_path = self.plugin.export_system_report()
            
            if output_path:
                QMessageBox.information(
                    self,
                    "Rapport exporterad",
                    f"Systemrapport sparad:\n{output_path}"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Export misslyckades",
                    "Kunde inte exportera systemrapport."
                )

        def export_report(self) -> None:
            self._export_report()

        def refresh(self) -> None:
            """Uppdatera widget."""
            self._refresh_dynamic_tabs()


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    # Constants
    "VERSION",
    "AUTHOR",
    
    # Copyright
    "get_copyright_year",
    "get_copyright_string",
    
    # Helpers
    "get_plugin_safe",
    "get_loaded_plugins",
    "emit_event_safe",
    "get_config_value",
    "format_bytes",
    
    # Plugin
    "Plugin",
    
    # GUI availability
    "HAS_PYSIDE6",
]

if HAS_PYSIDE6:
    __all__.append("AboutWidget")
