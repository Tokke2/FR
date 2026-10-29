# -*- coding: utf-8 -*-
# Fil: plugins/data_viewer/plugin.py
"""
Data Viewer Plugin v3.0.0 (PySide6)

Visar all data i systemet med sök, sortering, export och schema-integration.

FUNKTIONER:
1. Fordonsdata (modellregister via vehicle_registry)
2. Återförsäljare
3. Färger
4. VIN per år/månad
5. TS-scheman (från ts_spec_import/ts_schema_manager)
6. Data-validering
7. Systemdiagnostik
8. Export CSV/Excel/JSON
9. Data-diff/jämförelse
10. Statistik-dashboard

NYA FUNKTIONER I v3.0.0:
1. show_schema_tab() - Visa TS-scheman dynamiskt
2. show_validation_results() - Visa valideringsresultat
3. export_to_json() - Exportera data till JSON
4. compare_data() - Jämför data mellan versioner
5. get_statistics() - Hämta statistik för all data
6. get_field_coverage() - Analysera fälttäckning
7. global_search() - Sök i alla flikar
8. preview_ts_output() - Förhandsgranska TS-output
9. show_audit_log() - Visa audit-logg
10. show_diagnostics() - Visa systemdiagnostik

SAMARBETE:
- ts_spec_import: Schema-data och validering
- ts_schema_manager: Schema-versioner
- vehicle_registry: Fordonsdata
- dealers_manager: Återförsäljardata
- colors_manager: Färgdata
- core_logger: Loggning

Copyright © 2025 Rickard Längkvist
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Tuple

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QTabWidget, QGroupBox,
    QComboBox, QSpinBox, QFileDialog, QMessageBox,
    QAbstractItemView, QSplitter, QTextEdit, QApplication,
    QFrame, QProgressBar, QCheckBox, QDialog, QDialogButtonBox,
    QPlainTextEdit, QTreeWidget, QTreeWidgetItem
)

from core.plugin_base import PluginBase


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS & HELPERS
# ══════════════════════════════════════════════════════════════════════════════

AUTHOR = "Rickard Längkvist"
VERSION = "3.0.0"
TS_POST_LENGTH = 2500


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


def _get_logger() -> logging.Logger:
    """Hämta logger. KRASCHSÄKER."""
    try:
        return logging.getLogger("data_viewer")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)


logger = _get_logger()


def get_plugin_safe(app: Any, name: str) -> Optional[Any]:
    """
    Hämta plugin med fallback för olika attributnamn. KRASCHSÄKER.
    
    Stödjer:
    - app.get_plugin()
    - app.plugin_loader.get_plugin()
    - app.plugin_manager.get_plugin()
    - app.<plugin_name>
    """
    try:
        # Försök app.get_plugin() först
        if hasattr(app, 'get_plugin'):
            plugin = app.get_plugin(name)
            if plugin:
                return plugin
        
        # Försök plugin_loader
        if hasattr(app, 'plugin_loader'):
            try:
                plugin = app.plugin_loader.get_plugin(name)
                if plugin:
                    return plugin
            except Exception:
                pass
        
        # Fallback: plugin_manager
        if hasattr(app, 'plugin_manager'):
            try:
                plugin = app.plugin_manager.get_plugin(name)
                if plugin:
                    return plugin
            except Exception:
                pass
        
        # Fallback: direkt attribut
        return getattr(app, name, None)
        
    except Exception:
        return None


def emit_event_safe(app: Any, event_name: str, data: Dict[str, Any]) -> None:
    """Emittera event säkert. KRASCHSÄKER."""
    try:
        if hasattr(app, 'event_bus') and hasattr(app.event_bus, 'emit'):
            app.event_bus.emit(event_name, data)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN-KLASS
# ══════════════════════════════════════════════════════════════════════════════

class Plugin(PluginBase):
    """
    Data Viewer Plugin v3.0.0 (PySide6)
    
    Visar all data i systemet med:
    - Sök och sortering
    - Export CSV/Excel/JSON
    - Schema-integration
    - Validering
    - Diagnostik
    
    10 publika funktioner för komplett datavisning.
    """
    
    NAME = "Data Viewer"
    VERSION = VERSION
    DESCRIPTION = "Visa och exportera systemdata med schema-integration (10 funktioner)"
    AUTHOR = AUTHOR
    DEPENDENCIES = []
    OPTIONAL_DEPENDENCIES = [
        "core_config",
        "vehicle_registry", 
        "dealers_manager", 
        "colors_manager",
        "ts_spec_import",
        "ts_schema_manager",
        "core_logger"
    ]
    
    def __init__(self, app):
        super().__init__(app)
        self._local_logger = _get_logger()
        self._widget: Optional[DataViewerWidget] = None
        self._initialized: bool = False
        self._event_subscriptions: List[str] = []
    
    @property
    def copyright(self) -> str:
        """Dynamisk copyright-sträng."""
        return get_copyright_string()
    
    def initialize(self) -> None:
        """Initiera plugin. KRASCHSÄKER."""
        try:
            self._register_events()
            self._initialized = True
            self._local_logger.info(f"{self.NAME} v{self.VERSION} initialized")
            self._local_logger.info(f"  {self.copyright}")
            self._local_logger.info(f"  10 public functions available")
        except Exception as e:
            self._local_logger.error(f"Initialization failed: {e}")
            self._initialized = False
    
    def activate(self) -> None:
        """Aktivera plugin. KRASCHSÄKER."""
        try:
            self.is_active = True
            emit_event_safe(self.app, "data_viewer:activated", {})
        except Exception as e:
            self._local_logger.error(f"Activation failed: {e}")
    
    def deactivate(self) -> None:
        """Deaktivera plugin. KRASCHSÄKER."""
        try:
            self._unregister_events()
            self._widget = None
            self.is_active = False
        except Exception as e:
            self._local_logger.error(f"Deactivation failed: {e}")
    
    def create_widget(self, parent: QWidget) -> QWidget:
        """Skapa widget för main_gui's stackwidget. KRASCHSÄKER."""
        try:
            self._widget = DataViewerWidget(parent, self.app, self)
            return self._widget
        except Exception as e:
            self._local_logger.error(f"Widget creation failed: {e}")
            fallback = QWidget(parent)
            layout = QVBoxLayout(fallback)
            layout.addWidget(QLabel(f"❌ Widget creation failed: {e}"))
            return fallback
    
    def _register_events(self) -> None:
        """Registrera events. KRASCHSÄKER."""
        if not hasattr(self.app, 'event_bus'):
            return
        
        events = [
            ("viewer:refresh", self._on_refresh),
            ("viewer:show_tab", self._on_show_tab),
            ("data:changed", self._on_refresh),
            ("schema:version_changed", self._on_schema_changed),
            ("ts_spec:imported", self._on_schema_changed),
        ]
        
        for event_name, handler in events:
            try:
                self.app.event_bus.on(event_name, handler, source=self.NAME)
                self._event_subscriptions.append(event_name)
            except Exception:
                pass
    
    def _unregister_events(self) -> None:
        """Avregistrera events. KRASCHSÄKER."""
        if not hasattr(self.app, 'event_bus'):
            return
        
        for event in self._event_subscriptions:
            try:
                self.app.event_bus.off(event, getattr(self, f"_on_{event.split(':')[1]}", None))
            except Exception:
                pass
        self._event_subscriptions.clear()
    
    def _on_refresh(self, data: Optional[Dict] = None) -> None:
        """Uppdatera data. KRASCHSÄKER."""
        if self._widget:
            try:
                self._widget.refresh_all()
            except Exception as e:
                self._local_logger.error(f"Refresh failed: {e}")
    
    def _on_show_tab(self, data: Optional[Dict] = None) -> None:
        """Visa specifik flik. KRASCHSÄKER."""
        if self._widget and data:
            try:
                tab_name = data.get("tab", "vehicles")
                self._widget.show_tab(tab_name)
            except Exception as e:
                self._local_logger.error(f"Show tab failed: {e}")
    
    def _on_schema_changed(self, data: Optional[Dict] = None) -> None:
        """Hantera schema-ändring. KRASCHSÄKER."""
        if self._widget:
            try:
                self._widget.refresh_schema_tab()
            except Exception as e:
                self._local_logger.debug(f"Schema refresh failed: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 10 PUBLIKA FUNKTIONER
    # ═══════════════════════════════════════════════════════════════════════════
    
    def show_schema_tab(self, post_type: Optional[str] = None) -> None:
        """
        1. Visa TS-scheman dynamiskt.
        
        Args:
            post_type: Specifik posttyp att visa (None = alla)
        """
        if self._widget:
            try:
                self._widget.show_tab("schemas")
                if post_type:
                    self._widget.schemas_tab.select_post_type(post_type)
            except Exception as e:
                self._local_logger.error(f"show_schema_tab failed: {e}")
    
    def show_validation_results(self, results: List[Dict[str, Any]]) -> None:
        """
        2. Visa valideringsresultat.
        
        Args:
            results: Lista med valideringsresultat
        """
        if self._widget:
            try:
                self._widget.show_tab("validation")
                self._widget.validation_tab.display_results(results)
            except Exception as e:
                self._local_logger.error(f"show_validation_results failed: {e}")
    
    def export_to_json(self, tab_name: str = "vehicles") -> Optional[Path]:
        """
        3. Exportera data till JSON.
        
        Args:
            tab_name: Namn på flik att exportera
        
        Returns:
            Path till exporterad fil eller None
        """
        if not self._widget:
            return None
        
        try:
            return self._widget.export_tab_to_json(tab_name)
        except Exception as e:
            self._local_logger.error(f"export_to_json failed: {e}")
            return None
    
    def compare_data(self, data1: List[Dict], data2: List[Dict], key_field: str = "vin_kod") -> Dict[str, Any]:
        """
        4. Jämför data mellan versioner.
        
        Args:
            data1: Första datamängden
            data2: Andra datamängden
            key_field: Nyckelfält för jämförelse
        
        Returns:
            Dict med added, removed, changed
        """
        try:
            set1 = {row.get(key_field): row for row in data1 if row.get(key_field)}
            set2 = {row.get(key_field): row for row in data2 if row.get(key_field)}
            
            keys1 = set(set1.keys())
            keys2 = set(set2.keys())
            
            added = keys2 - keys1
            removed = keys1 - keys2
            common = keys1 & keys2
            
            changed = []
            for key in common:
                if set1[key] != set2[key]:
                    changed.append({
                        "key": key,
                        "old": set1[key],
                        "new": set2[key]
                    })
            
            return {
                "added": list(added),
                "removed": list(removed),
                "changed": changed,
                "added_count": len(added),
                "removed_count": len(removed),
                "changed_count": len(changed),
                "unchanged_count": len(common) - len(changed)
            }
            
        except Exception as e:
            self._local_logger.error(f"compare_data failed: {e}")
            return {"error": str(e)}
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        5. Hämta statistik för all data.
        
        Returns:
            Dict med statistik per datakälla
        """
        stats = {
            "timestamp": datetime.now().isoformat(),
            "vehicles": {"count": 0, "years": []},
            "dealers": {"count": 0},
            "colors": {"count": 0},
            "vins": {"count": 0, "years": []},
            "schemas": {"count": 0, "post_types": []},
        }
        
        try:
            # Fordonsstatistik
            vehicle_registry = get_plugin_safe(self.app, "vehicle_registry")
            if vehicle_registry:
                try:
                    years = vehicle_registry.get_vehicle_years()
                    stats["vehicles"]["years"] = years
                    for year in years:
                        vehicles = vehicle_registry.load_vehicles_for_year(year)
                        stats["vehicles"]["count"] += len(vehicles)
                except Exception:
                    pass
            
            # Återförsäljarstatistik
            dealers = get_plugin_safe(self.app, "dealers_manager")
            if dealers:
                try:
                    all_dealers = dealers.get_all_dealers() if hasattr(dealers, 'get_all_dealers') else []
                    stats["dealers"]["count"] = len(all_dealers)
                except Exception:
                    pass
            
            # Färgstatistik
            colors = get_plugin_safe(self.app, "colors_manager")
            if colors:
                try:
                    all_colors = colors.get_all_colors() if hasattr(colors, 'get_all_colors') else []
                    stats["colors"]["count"] = len(all_colors)
                except Exception:
                    pass
            
            # Schema-statistik
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if ts_spec:
                try:
                    schemas = ts_spec.get_all_schemas()
                    stats["schemas"]["count"] = len(schemas)
                    stats["schemas"]["post_types"] = list(schemas.keys())
                except Exception:
                    pass
            
        except Exception as e:
            stats["error"] = str(e)
        
        return stats
    
    def get_field_coverage(self, post_type: str, data: List[Dict]) -> Dict[str, Any]:
        """
        6. Analysera fälttäckning för given data mot schema.
        
        Args:
            post_type: Posttyp att validera mot
            data: Data att analysera
        
        Returns:
            Dict med täckningsanalys
        """
        result = {
            "post_type": post_type,
            "data_count": len(data),
            "fields": {},
            "coverage_percent": 0,
            "missing_required": [],
        }
        
        try:
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if not ts_spec:
                result["error"] = "ts_spec_import not available"
                return result
            
            schema = ts_spec.get_schema(post_type)
            if not schema or not hasattr(schema, 'fields'):
                result["error"] = f"Schema for PT{post_type} not found"
                return result
            
            # Analysera varje fält
            for field in schema.fields:
                field_name = field.name
                is_required = getattr(field, 'required', False)
                
                present_count = sum(1 for row in data if row.get(field_name))
                coverage = present_count / len(data) * 100 if data else 0
                
                result["fields"][field_name] = {
                    "required": is_required,
                    "present_count": present_count,
                    "missing_count": len(data) - present_count,
                    "coverage_percent": round(coverage, 1)
                }
                
                if is_required and coverage < 100:
                    result["missing_required"].append(field_name)
            
            # Total täckning
            if result["fields"]:
                total_coverage = sum(f["coverage_percent"] for f in result["fields"].values())
                result["coverage_percent"] = round(total_coverage / len(result["fields"]), 1)
            
        except Exception as e:
            result["error"] = str(e)
        
        return result
    
    def global_search(self, query: str) -> Dict[str, List[Dict]]:
        """
        7. Sök i alla flikar.
        
        Args:
            query: Sökfråga
        
        Returns:
            Dict med resultat per flik
        """
        results = {
            "vehicles": [],
            "dealers": [],
            "colors": [],
            "schemas": [],
            "total_count": 0
        }
        
        if not query or not self._widget:
            return results
        
        query_lower = query.lower()
        
        try:
            # Sök i fordon
            if hasattr(self._widget, 'vehicles_tab'):
                for row in self._widget.vehicles_tab._data:
                    for val in row.values():
                        if query_lower in str(val).lower():
                            results["vehicles"].append(row)
                            break
            
            # Sök i återförsäljare
            if hasattr(self._widget, 'dealers_tab'):
                for row in self._widget.dealers_tab._data:
                    for val in row.values():
                        if query_lower in str(val).lower():
                            results["dealers"].append(row)
                            break
            
            # Sök i färger
            if hasattr(self._widget, 'colors_tab'):
                for row in self._widget.colors_tab._data:
                    for val in row.values():
                        if query_lower in str(val).lower():
                            results["colors"].append(row)
                            break
            
            # Sök i scheman
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if ts_spec:
                try:
                    found_fields = ts_spec.find_fields_by_pattern(query, search_in="both")
                    results["schemas"] = found_fields
                except Exception:
                    pass
            
            results["total_count"] = sum(len(v) for v in results.values() if isinstance(v, list))
            
        except Exception as e:
            results["error"] = str(e)
        
        return results
    
    def preview_ts_output(self, post_type: str, data: Dict[str, Any]) -> Optional[str]:
        """
        8. Förhandsgranska TS-output.
        
        Args:
            post_type: Posttyp
            data: Data att formatera
        
        Returns:
            Formaterad sträng (2500 tecken) eller None
        """
        try:
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if not ts_spec:
                return None
            
            return ts_spec.format_record(post_type, data)
            
        except Exception as e:
            self._local_logger.error(f"preview_ts_output failed: {e}")
            return None
    
    def show_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        9. Visa audit-logg.
        
        Args:
            limit: Max antal poster att visa
        
        Returns:
            Lista med loggposter
        """
        logs = []
        
        try:
            # Försök läsa audit.log
            log_path = Path(getattr(self.app, 'base_path', '.')) / "logs" / "audit.log"
            if log_path.exists():
                with open(log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[-limit:]
                
                for line in lines:
                    try:
                        # Parse log line
                        parts = line.strip().split(' - ', 3)
                        if len(parts) >= 3:
                            logs.append({
                                "timestamp": parts[0],
                                "level": parts[1] if len(parts) > 1 else "INFO",
                                "message": parts[-1]
                            })
                    except Exception:
                        logs.append({"message": line.strip()})
            
        except Exception as e:
            self._local_logger.error(f"show_audit_log failed: {e}")
        
        return logs
    
    def show_diagnostics(self) -> Dict[str, Any]:
        """
        10. Visa systemdiagnostik.
        
        Returns:
            Dict med diagnostikinformation
        """
        diag = {
            "plugin_name": self.NAME,
            "plugin_version": self.VERSION,
            "copyright": self.copyright,
            "initialized": self._initialized,
            "widget_active": self._widget is not None,
            "event_subscriptions": self._event_subscriptions.copy(),
            "available_plugins": [],
            "schema_status": {},
            "data_sources": {},
        }
        
        try:
            # Kolla tillgängliga plugins
            for plugin_name in self.OPTIONAL_DEPENDENCIES:
                plugin = get_plugin_safe(self.app, plugin_name)
                if plugin:
                    diag["available_plugins"].append(plugin_name)
            
            # Schema-status
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if ts_spec:
                try:
                    diag["schema_status"] = ts_spec.get_diagnostics()
                except Exception:
                    diag["schema_status"] = {"available": True}
            
            # Datakällor
            diag["data_sources"]["vehicles"] = get_plugin_safe(self.app, "vehicle_registry") is not None
            diag["data_sources"]["dealers"] = get_plugin_safe(self.app, "dealers_manager") is not None
            diag["data_sources"]["colors"] = get_plugin_safe(self.app, "colors_manager") is not None
            
        except Exception as e:
            diag["error"] = str(e)
        
        return diag
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CONVENIENCE METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def refresh(self) -> None:
        """Uppdatera all data. KRASCHSÄKER."""
        if self._widget:
            try:
                self._widget.refresh_all()
            except Exception as e:
                self._local_logger.error(f"Refresh failed: {e}")
    
    def get_selected_vehicle(self) -> Optional[Dict]:
        """Hämta valt fordon. KRASCHSÄKER."""
        if self._widget:
            try:
                return self._widget.get_selected_vehicle()
            except Exception:
                pass
        return None


# ══════════════════════════════════════════════════════════════════════════════
# HUVUDWIDGET
# ══════════════════════════════════════════════════════════════════════════════

class DataViewerWidget(QWidget):
    """Huvudwidget för datavisning med flikar."""
    
    def __init__(self, parent: QWidget, app, plugin: Plugin):
        super().__init__(parent)
        self.app = app
        self.plugin = plugin
        self._setup_ui()
        
        # Ladda data efter kort fördröjning
        QTimer.singleShot(100, self.refresh_all)
    
    def _setup_ui(self) -> None:
        """Bygg UI. KRASCHSÄKER."""
        try:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(10)
            
            # Header
            header = QHBoxLayout()
            
            title = QLabel("📋 Datavisning")
            title.setObjectName("PageTitle")
            title.setStyleSheet("font-size: 22px; font-weight: bold; color: #ffffff;")
            header.addWidget(title)
            
            header.addStretch()
            
            # Global sökning
            self.global_search = QLineEdit()
            self.global_search.setPlaceholderText("🔍 Global sökning...")
            self.global_search.setMinimumWidth(200)
            self.global_search.setStyleSheet("""
                QLineEdit { 
                    background: #2b2b2b; color: #fff; 
                    border: 1px solid #444; border-radius: 4px; 
                    padding: 6px; 
                }
            """)
            self.global_search.returnPressed.connect(self._on_global_search)
            header.addWidget(self.global_search)
            
            # Refresh-knapp
            btn_refresh = QPushButton("🔄")
            btn_refresh.setToolTip("Uppdatera alla flikar")
            btn_refresh.setFixedWidth(40)
            btn_refresh.clicked.connect(self.refresh_all)
            header.addWidget(btn_refresh)
            
            layout.addLayout(header)
            
            # Flikar
            self.tabs = QTabWidget()
            self.tabs.setStyleSheet("""
                QTabWidget::pane { border: 1px solid #444; background: #222; }
                QTabBar::tab { 
                    background: #333; color: #ccc; padding: 8px 16px; 
                    border: 1px solid #444; border-bottom: none;
                }
                QTabBar::tab:selected { background: #222; color: #fff; }
                QTabBar::tab:hover { background: #3a3a3a; }
            """)
            
            # Skapa flikar
            self.vehicles_tab = VehiclesTab(self, self.app)
            self.dealers_tab = DealersViewTab(self, self.app)
            self.colors_tab = ColorsViewTab(self, self.app)
            self.vins_tab = VinsTab(self, self.app)
            self.schemas_tab = SchemasTab(self, self.app)
            self.validation_tab = ValidationTab(self, self.app)
            self.diagnostics_tab = DiagnosticsTab(self, self.app, self.plugin)
            
            self.tabs.addTab(self.vehicles_tab, "🚗 Fordon")
            self.tabs.addTab(self.dealers_tab, "🏢 Återförsäljare")
            self.tabs.addTab(self.colors_tab, "🎨 Färger")
            self.tabs.addTab(self.vins_tab, "📊 VIN")
            self.tabs.addTab(self.schemas_tab, "📐 Scheman")
            self.tabs.addTab(self.validation_tab, "✅ Validering")
            self.tabs.addTab(self.diagnostics_tab, "🔧 Diagnostik")
            
            layout.addWidget(self.tabs)
            
            # Footer
            footer = QLabel(self.plugin.copyright)
            footer.setStyleSheet("color: #666; font-size: 10px;")
            footer.setAlignment(Qt.AlignRight)
            layout.addWidget(footer)
            
        except Exception as e:
            logger.error(f"UI setup failed: {e}")
    
    def refresh_all(self) -> None:
        """Uppdatera alla flikar. KRASCHSÄKER."""
        tabs = [
            ("vehicles", self.vehicles_tab),
            ("dealers", self.dealers_tab),
            ("colors", self.colors_tab),
            ("vins", self.vins_tab),
            ("schemas", self.schemas_tab),
            ("diagnostics", self.diagnostics_tab),
        ]
        
        for name, tab in tabs:
            try:
                if hasattr(tab, 'refresh'):
                    tab.refresh()
            except Exception as e:
                logger.warning(f"Failed to refresh {name}: {e}")
    
    def refresh_schema_tab(self) -> None:
        """Uppdatera schema-flik. KRASCHSÄKER."""
        try:
            self.schemas_tab.refresh()
        except Exception:
            pass
    
    def show_tab(self, tab_name: str) -> None:
        """Visa specifik flik. KRASCHSÄKER."""
        tab_map = {
            "vehicles": 0, "fordon": 0,
            "dealers": 1, "aterforsaljare": 1,
            "colors": 2, "farger": 2,
            "vins": 3,
            "schemas": 4, "scheman": 4,
            "validation": 5, "validering": 5,
            "diagnostics": 6, "diagnostik": 6,
        }
        index = tab_map.get(tab_name.lower(), 0)
        self.tabs.setCurrentIndex(index)
    
    def get_selected_vehicle(self) -> Optional[Dict]:
        """Hämta valt fordon. KRASCHSÄKER."""
        try:
            return self.vehicles_tab.get_selected()
        except Exception:
            return None
    
    def export_tab_to_json(self, tab_name: str) -> Optional[Path]:
        """Exportera flik till JSON. KRASCHSÄKER."""
        try:
            tab_data_map = {
                "vehicles": self.vehicles_tab._data,
                "dealers": self.dealers_tab._data,
                "colors": self.colors_tab._data,
            }
            
            data = tab_data_map.get(tab_name.lower())
            if not data:
                return None
            
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Exportera JSON",
                f"{tab_name}_{datetime.now().strftime('%Y%m%d')}.json",
                "JSON-filer (*.json)"
            )
            
            if not filepath:
                return None
            
            # Filtrera bort interna fält
            export_data = [
                {k: v for k, v in row.items() if not k.startswith('_')}
                for row in data
            ]
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            return Path(filepath)
            
        except Exception as e:
            logger.error(f"JSON export failed: {e}")
            return None
    
    def _on_global_search(self) -> None:
        """Hantera global sökning. KRASCHSÄKER."""
        try:
            query = self.global_search.text().strip()
            if not query:
                return
            
            results = self.plugin.global_search(query)
            
            # Visa resultat i dialog
            dialog = GlobalSearchResultsDialog(self, query, results)
            dialog.exec()
            
        except Exception as e:
            logger.error(f"Global search failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# FORDON-FLIK
# ══════════════════════════════════════════════════════════════════════════════

class VehiclesTab(QWidget):
    """Flik för fordonsdata. KRASCHSÄKER."""
    
    def __init__(self, parent: QWidget, app):
        super().__init__(parent)
        self.app = app
        self._data: List[Dict] = []
        self._filtered_data: List[Dict] = []
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Bygg UI. KRASCHSÄKER."""
        try:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(5, 5, 5, 5)
            
            # Sökrad
            search_layout = QHBoxLayout()
            
            search_layout.addWidget(QLabel("🔍 Sök:"))
            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("Sök på VIN, modell, typ...")
            self.search_input.setStyleSheet("""
                QLineEdit { 
                    background: #2b2b2b; color: #fff; 
                    border: 1px solid #444; border-radius: 4px; 
                    padding: 6px; 
                }
            """)
            self.search_input.textChanged.connect(self._apply_filters)
            search_layout.addWidget(self.search_input, 1)
            
            # Årsfilter
            search_layout.addWidget(QLabel("År:"))
            self.year_filter = QComboBox()
            self.year_filter.setMinimumWidth(100)
            self.year_filter.addItem("Alla")
            self.year_filter.currentTextChanged.connect(self._apply_filters)
            search_layout.addWidget(self.year_filter)
            
            # Uppdatera-knapp
            self.btn_refresh = QPushButton("🔄")
            self.btn_refresh.setFixedWidth(40)
            self.btn_refresh.clicked.connect(self.refresh)
            search_layout.addWidget(self.btn_refresh)
            
            layout.addLayout(search_layout)
            
            # Status
            self.status_label = QLabel("📊 Laddar...")
            self.status_label.setStyleSheet("color: #888; font-size: 12px;")
            layout.addWidget(self.status_label)
            
            # Tabell
            self.table = QTableWidget()
            self.table.setAlternatingRowColors(True)
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SingleSelection)
            self.table.setSortingEnabled(True)
            self.table.setStyleSheet("""
                QTableWidget {
                    background: #222; gridline-color: #444;
                    color: #fff; alternate-background-color: #2a2a2a;
                }
                QHeaderView::section { 
                    background: #333; color: #fff; 
                    padding: 6px; border: 1px solid #444;
                }
                QTableWidget::item:selected {
                    background: #007bff; color: #fff;
                }
            """)
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            self.table.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(self.table)
            
            # Knappar
            btn_layout = QHBoxLayout()
            
            self.btn_csv = QPushButton("📤 CSV")
            self.btn_csv.clicked.connect(self._export_csv)
            btn_layout.addWidget(self.btn_csv)
            
            self.btn_excel = QPushButton("📊 Excel")
            self.btn_excel.clicked.connect(self._export_excel)
            btn_layout.addWidget(self.btn_excel)
            
            self.btn_json = QPushButton("📋 JSON")
            self.btn_json.clicked.connect(self._export_json)
            btn_layout.addWidget(self.btn_json)
            
            self.btn_copy = QPushButton("📋 Kopiera")
            self.btn_copy.clicked.connect(self._copy_selected)
            btn_layout.addWidget(self.btn_copy)
            
            self.btn_preview = QPushButton("👁️ Förhandsvisa TS")
            self.btn_preview.clicked.connect(self._preview_ts)
            btn_layout.addWidget(self.btn_preview)
            
            btn_layout.addStretch()
            
            self.count_label = QLabel("0 fordon")
            self.count_label.setStyleSheet("color: #888;")
            btn_layout.addWidget(self.count_label)
            
            layout.addLayout(btn_layout)
            
        except Exception as e:
            logger.error(f"VehiclesTab UI setup failed: {e}")
    
    def refresh(self) -> None:
        """Ladda data från vehicle_registry eller databas. KRASCHSÄKER."""
        try:
            self._data.clear()
            self.year_filter.blockSignals(True)
            self.year_filter.clear()
            self.year_filter.addItem("Alla")
            self.year_filter.blockSignals(False)
            
            # Försök 1: vehicle_registry (filbaserad)
            vehicle_registry = get_plugin_safe(self.app, "vehicle_registry")
            if vehicle_registry:
                try:
                    years = vehicle_registry.get_vehicle_years()
                    
                    for year in sorted(years, reverse=True):
                        self.year_filter.addItem(str(year))
                        
                        vehicles = vehicle_registry.load_vehicles_for_year(year)
                        for v in vehicles:
                            v['_year'] = year
                            self._data.append(v)
                    
                    self._filtered_data = self._data.copy()
                    self._update_table()
                    self.status_label.setText(f"✅ {len(self._data)} fordon (vehicle_registry)")
                    return
                    
                except Exception as e:
                    logger.debug(f"vehicle_registry failed: {e}")
            
            # Försök 2: Ladda direkt från JSON-filer
            try:
                base_path = getattr(self.app, 'base_path', Path.cwd())
                data_dir = Path(base_path) / "data" / "vehicles"
                
                if data_dir.exists():
                    for json_file in sorted(data_dir.glob("*.json"), reverse=True):
                        try:
                            year = int(json_file.stem)
                            if 1900 <= year <= 2100:
                                self.year_filter.addItem(str(year))
                                
                                with open(json_file, 'r', encoding='utf-8') as f:
                                    data = json.load(f)
                                
                                vehicles = data.get("vehicles", data if isinstance(data, list) else [])
                                for v in vehicles:
                                    v['_year'] = year
                                    self._data.append(v)
                        except (ValueError, json.JSONDecodeError):
                            pass
                    
                    self._filtered_data = self._data.copy()
                    self._update_table()
                    self.status_label.setText(f"✅ {len(self._data)} fordon (JSON)")
                    return
            except Exception as e:
                logger.debug(f"JSON loading failed: {e}")
            
            self.status_label.setText("❌ Ingen datakälla")
            
        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            self.status_label.setText(f"❌ Fel: {e}")
    
    def _apply_filters(self) -> None:
        """Applicera sök och filter. KRASCHSÄKER."""
        try:
            query = self.search_input.text().strip().lower()
            year_filter = self.year_filter.currentText()
            
            self._filtered_data = []
            
            for row in self._data:
                # Årsfilter
                if year_filter != "Alla":
                    row_year = str(row.get("MODELYEAR", row.get("_year", "")))
                    if row_year != year_filter:
                        continue
                
                # Sökning
                if query:
                    match = False
                    for val in row.values():
                        if query in str(val).lower():
                            match = True
                            break
                    if not match:
                        continue
                
                self._filtered_data.append(row)
            
            self._update_table()
            
        except Exception as e:
            logger.error(f"Filter failed: {e}")
    
    def _update_table(self) -> None:
        """Uppdatera tabellen. KRASCHSÄKER."""
        try:
            self.table.setRowCount(0)
            
            if not self._filtered_data:
                self.count_label.setText("0 fordon")
                return
            
            # Välj kolumner att visa
            display_cols = [
                "vin_kod", "VINCODE",
                "MODELYEAR", "_year",
                "handelsbeteckning", "MODELNAME", "COMNAME",
                "typ", "TYPE",
                "variant", "VARIANTE",
                "version", "VERSION",
            ]
            
            available_cols = list(self._filtered_data[0].keys())
            cols = []
            seen = set()
            
            for c in display_cols:
                if c in available_cols and c not in seen:
                    cols.append(c)
                    seen.add(c)
            
            if len(cols) < 8:
                for c in available_cols:
                    if c not in seen and not c.startswith('_'):
                        cols.append(c)
                        if len(cols) >= 8:
                            break
            
            if not cols:
                cols = [c for c in available_cols[:8] if not c.startswith('_')]
            
            self.table.setColumnCount(len(cols))
            self.table.setHorizontalHeaderLabels(cols)
            
            for row_data in self._filtered_data:
                row = self.table.rowCount()
                self.table.insertRow(row)
                
                for col, key in enumerate(cols):
                    value = str(row_data.get(key, ""))
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, col, item)
            
            self.count_label.setText(f"{len(self._filtered_data)} fordon")
            
        except Exception as e:
            logger.error(f"Table update failed: {e}")
    
    def get_selected(self) -> Optional[Dict]:
        """Hämta valt fordon. KRASCHSÄKER."""
        try:
            selected = self.table.selectedItems()
            if not selected:
                return None
            
            row = selected[0].row()
            if row < len(self._filtered_data):
                return self._filtered_data[row]
        except Exception:
            pass
        return None
    
    def _export_csv(self) -> None:
        """Exportera till CSV. KRASCHSÄKER."""
        try:
            if not self._filtered_data:
                QMessageBox.warning(self, "Ingen data", "Ingen data att exportera")
                return
            
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Exportera CSV",
                f"fordon_{datetime.now().strftime('%Y%m%d')}.csv",
                "CSV-filer (*.csv)"
            )
            
            if not filepath:
                return
            
            export_data = [
                {k: v for k, v in row.items() if not k.startswith('_')}
                for row in self._filtered_data
            ]
            
            with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=export_data[0].keys(), delimiter=';')
                writer.writeheader()
                writer.writerows(export_data)
            
            QMessageBox.information(self, "Export klar", f"Exporterade {len(export_data)} rader")
            
        except Exception as e:
            QMessageBox.critical(self, "Fel", f"Kunde inte exportera: {e}")
    
    def _export_excel(self) -> None:
        """Exportera till Excel. KRASCHSÄKER."""
        try:
            import pandas as pd
        except ImportError:
            QMessageBox.warning(self, "Saknas", "pandas krävs för Excel-export\npip install pandas openpyxl")
            return
        
        try:
            if not self._filtered_data:
                QMessageBox.warning(self, "Ingen data", "Ingen data att exportera")
                return
            
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Exportera Excel",
                f"fordon_{datetime.now().strftime('%Y%m%d')}.xlsx",
                "Excel-filer (*.xlsx)"
            )
            
            if not filepath:
                return
            
            export_data = [
                {k: v for k, v in row.items() if not k.startswith('_')}
                for row in self._filtered_data
            ]
            
            df = pd.DataFrame(export_data)
            df.to_excel(filepath, index=False, engine='openpyxl')
            QMessageBox.information(self, "Export klar", f"Exporterade {len(export_data)} rader")
            
        except Exception as e:
            QMessageBox.critical(self, "Fel", f"Kunde inte exportera: {e}")
    
    def _export_json(self) -> None:
        """Exportera till JSON. KRASCHSÄKER."""
        try:
            if not self._filtered_data:
                QMessageBox.warning(self, "Ingen data", "Ingen data att exportera")
                return
            
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Exportera JSON",
                f"fordon_{datetime.now().strftime('%Y%m%d')}.json",
                "JSON-filer (*.json)"
            )
            
            if not filepath:
                return
            
            export_data = [
                {k: v for k, v in row.items() if not k.startswith('_')}
                for row in self._filtered_data
            ]
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            QMessageBox.information(self, "Export klar", f"Exporterade {len(export_data)} rader")
            
        except Exception as e:
            QMessageBox.critical(self, "Fel", f"Kunde inte exportera: {e}")
    
    def _copy_selected(self) -> None:
        """Kopiera vald rad till urklipp. KRASCHSÄKER."""
        try:
            selected = self.get_selected()
            if not selected:
                QMessageBox.information(self, "Info", "Välj en rad först")
                return
            
            clean_data = {k: v for k, v in selected.items() if not k.startswith('_')}
            text = "\t".join(str(v) for v in clean_data.values())
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Kopierat", "Rad kopierad till urklipp")
        except Exception as e:
            QMessageBox.critical(self, "Fel", f"Kunde inte kopiera: {e}")
    
    def _preview_ts(self) -> None:
        """Förhandsgranska TS-formatering. KRASCHSÄKER."""
        try:
            selected = self.get_selected()
            if not selected:
                QMessageBox.information(self, "Info", "Välj en rad först")
                return
            
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if not ts_spec:
                QMessageBox.warning(self, "Saknas", "ts_spec_import plugin ej tillgänglig")
                return
            
            # Försök formatera som PT45
            result = ts_spec.format_record("45", selected)
            
            if result:
                dialog = TSPreviewDialog(self, "45", result)
                dialog.exec()
            else:
                QMessageBox.warning(self, "Kunde inte formatera", "Schema för PT45 kanske saknas")
                
        except Exception as e:
            QMessageBox.critical(self, "Fel", f"Kunde inte förhandsgranska: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ÅTERFÖRSÄLJARE-FLIK
# ══════════════════════════════════════════════════════════════════════════════

class DealersViewTab(QWidget):
    """Flik för återförsäljare. KRASCHSÄKER."""
    
    def __init__(self, parent: QWidget, app):
        super().__init__(parent)
        self.app = app
        self._data: List[Dict] = []
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Bygg UI. KRASCHSÄKER."""
        try:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(5, 5, 5, 5)
            
            # Sökrad
            search_layout = QHBoxLayout()
            search_layout.addWidget(QLabel("🔍 Sök:"))
            
            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("Sök på namn, orgnr, dealer number...")
            self.search_input.setStyleSheet("""
                QLineEdit { 
                    background: #2b2b2b; color: #fff; 
                    border: 1px solid #444; border-radius: 4px; 
                    padding: 6px; 
                }
            """)
            self.search_input.textChanged.connect(self._update_table)
            search_layout.addWidget(self.search_input, 1)
            
            self.btn_refresh = QPushButton("🔄")
            self.btn_refresh.setFixedWidth(40)
            self.btn_refresh.clicked.connect(self.refresh)
            search_layout.addWidget(self.btn_refresh)
            
            layout.addLayout(search_layout)
            
            # Status
            self.status_label = QLabel("📊 Laddar...")
            self.status_label.setStyleSheet("color: #888; font-size: 12px;")
            layout.addWidget(self.status_label)
            
            # Tabell
            self.table = QTableWidget()
            self.table.setAlternatingRowColors(True)
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setSortingEnabled(True)
            self.table.setStyleSheet("""
                QTableWidget {
                    background: #222; gridline-color: #444;
                    color: #fff; alternate-background-color: #2a2a2a;
                }
                QHeaderView::section { 
                    background: #333; color: #fff; 
                    padding: 6px; border: 1px solid #444;
                }
            """)
            self.table.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(self.table)
            
            # Knappar
            btn_layout = QHBoxLayout()
            
            self.btn_csv = QPushButton("📤 CSV")
            self.btn_csv.clicked.connect(self._export_csv)
            btn_layout.addWidget(self.btn_csv)
            
            btn_layout.addStretch()
            
            self.count_label = QLabel("0 återförsäljare")
            self.count_label.setStyleSheet("color: #888;")
            btn_layout.addWidget(self.count_label)
            
            layout.addLayout(btn_layout)
            
        except Exception as e:
            logger.error(f"DealersViewTab UI setup failed: {e}")
    
    def refresh(self) -> None:
        """Ladda data. KRASCHSÄKER."""
        try:
            self._data.clear()
            
            # Försök 1: dealers_manager
            dealers = get_plugin_safe(self.app, "dealers_manager")
            if dealers:
                try:
                    if hasattr(dealers, "get_all_dealers"):
                        self._data = dealers.get_all_dealers()
                    elif hasattr(dealers, "get_all"):
                        self._data = dealers.get_all()
                except Exception as e:
                    logger.debug(f"dealers_manager failed: {e}")
            
            # Försök 2: core_config
            if not self._data:
                config = get_plugin_safe(self.app, "core_config")
                if config:
                    try:
                        if hasattr(config, 'load_dealers'):
                            self._data = config.load_dealers()
                        elif hasattr(config, 'get_dealers'):
                            self._data = config.get_dealers()
                    except Exception as e:
                        logger.debug(f"core_config dealers failed: {e}")
            
            # Försök 3: JSON
            if not self._data:
                try:
                    base_path = getattr(self.app, 'base_path', Path.cwd())
                    json_path = Path(base_path) / "data" / "dealers.json"
                    if json_path.exists():
                        with open(json_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        self._data = data if isinstance(data, list) else data.get("dealers", [])
                except Exception as e:
                    logger.debug(f"JSON dealers failed: {e}")
            
            self._update_table()
            self.status_label.setText(f"✅ {len(self._data)} återförsäljare")
            
        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            self.status_label.setText(f"❌ Fel: {e}")
    
    def _update_table(self) -> None:
        """Uppdatera tabellen. KRASCHSÄKER."""
        try:
            self.table.setRowCount(0)
            
            query = self.search_input.text().strip().lower()
            filtered = []
            
            for row in self._data:
                if query:
                    match = False
                    for val in row.values():
                        if query in str(val).lower():
                            match = True
                            break
                    if not match:
                        continue
                filtered.append(row)
            
            if not filtered:
                self.count_label.setText("0 återförsäljare")
                return
            
            cols = ["namn", "orgnr", "dealer_number", "dn", "adress", "postnummer", "ort"]
            available = list(filtered[0].keys())
            cols = [c for c in cols if c in available] or available[:5]
            
            self.table.setColumnCount(len(cols))
            self.table.setHorizontalHeaderLabels(cols)
            
            for row_data in filtered:
                row = self.table.rowCount()
                self.table.insertRow(row)
                
                for col, key in enumerate(cols):
                    value = str(row_data.get(key, ""))
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, col, item)
            
            self.count_label.setText(f"{len(filtered)} återförsäljare")
            
        except Exception as e:
            logger.error(f"Table update failed: {e}")
    
    def _export_csv(self) -> None:
        """Exportera till CSV. KRASCHSÄKER."""
        try:
            if not self._data:
                QMessageBox.warning(self, "Ingen data", "Ingen data att exportera")
                return
            
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Exportera CSV",
                f"aterforsaljare_{datetime.now().strftime('%Y%m%d')}.csv",
                "CSV-filer (*.csv)"
            )
            
            if not filepath:
                return
            
            with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self._data[0].keys(), delimiter=';')
                writer.writeheader()
                writer.writerows(self._data)
            
            QMessageBox.information(self, "Export klar", f"Exporterade {len(self._data)} rader")
            
        except Exception as e:
            QMessageBox.critical(self, "Fel", f"Kunde inte exportera: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# FÄRGER-FLIK
# ══════════════════════════════════════════════════════════════════════════════

class ColorsViewTab(QWidget):
    """Flik för färger. KRASCHSÄKER."""
    
    def __init__(self, parent: QWidget, app):
        super().__init__(parent)
        self.app = app
        self._data: List[Dict] = []
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Bygg UI. KRASCHSÄKER."""
        try:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(5, 5, 5, 5)
            
            # Sökrad
            search_layout = QHBoxLayout()
            search_layout.addWidget(QLabel("🔍 Sök:"))
            
            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("Sök på färgnamn, kod...")
            self.search_input.setStyleSheet("""
                QLineEdit { 
                    background: #2b2b2b; color: #fff; 
                    border: 1px solid #444; border-radius: 4px; 
                    padding: 6px; 
                }
            """)
            self.search_input.textChanged.connect(self._update_table)
            search_layout.addWidget(self.search_input, 1)
            
            self.btn_refresh = QPushButton("🔄")
            self.btn_refresh.setFixedWidth(40)
            self.btn_refresh.clicked.connect(self.refresh)
            search_layout.addWidget(self.btn_refresh)
            
            layout.addLayout(search_layout)
            
            # Status
            self.status_label = QLabel("📊 Laddar...")
            self.status_label.setStyleSheet("color: #888; font-size: 12px;")
            layout.addWidget(self.status_label)
            
            # Tabell
            self.table = QTableWidget()
            self.table.setAlternatingRowColors(True)
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setSortingEnabled(True)
            self.table.setStyleSheet("""
                QTableWidget {
                    background: #222; gridline-color: #444;
                    color: #fff; alternate-background-color: #2a2a2a;
                }
                QHeaderView::section { 
                    background: #333; color: #fff; 
                    padding: 6px; border: 1px solid #444;
                }
            """)
            self.table.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(self.table)
            
            # Knappar
            btn_layout = QHBoxLayout()
            
            self.btn_csv = QPushButton("📤 CSV")
            self.btn_csv.clicked.connect(self._export_csv)
            btn_layout.addWidget(self.btn_csv)
            
            btn_layout.addStretch()
            
            self.count_label = QLabel("0 färger")
            self.count_label.setStyleSheet("color: #888;")
            btn_layout.addWidget(self.count_label)
            
            layout.addLayout(btn_layout)
            
        except Exception as e:
            logger.error(f"ColorsViewTab UI setup failed: {e}")
    
    def refresh(self) -> None:
        """Ladda data. KRASCHSÄKER."""
        try:
            self._data.clear()
            
            # Försök 1: colors_manager
            colors = get_plugin_safe(self.app, "colors_manager")
            if colors:
                try:
                    if hasattr(colors, "get_all_colors"):
                        self._data = colors.get_all_colors()
                    elif hasattr(colors, "get_all"):
                        self._data = colors.get_all()
                except Exception as e:
                    logger.debug(f"colors_manager failed: {e}")
            
            # Försök 2: core_config
            if not self._data:
                config = get_plugin_safe(self.app, "core_config")
                if config:
                    try:
                        if hasattr(config, 'load_colors'):
                            self._data = config.load_colors()
                        elif hasattr(config, 'get_colors'):
                            self._data = config.get_colors()
                    except Exception as e:
                        logger.debug(f"core_config colors failed: {e}")
            
            # Försök 3: JSON
            if not self._data:
                try:
                    base_path = getattr(self.app, 'base_path', Path.cwd())
                    json_path = Path(base_path) / "data" / "colors.json"
                    if json_path.exists():
                        with open(json_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        self._data = data if isinstance(data, list) else data.get("colors", [])
                except Exception as e:
                    logger.debug(f"JSON colors failed: {e}")
            
            self._update_table()
            self.status_label.setText(f"✅ {len(self._data)} färger")
            
        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            self.status_label.setText(f"❌ Fel: {e}")
    
    def _update_table(self) -> None:
        """Uppdatera tabellen. KRASCHSÄKER."""
        try:
            self.table.setRowCount(0)
            
            query = self.search_input.text().strip().lower()
            filtered = []
            
            for row in self._data:
                if query:
                    match = False
                    for val in row.values():
                        if query in str(val).lower():
                            match = True
                            break
                    if not match:
                        continue
                filtered.append(row)
            
            if not filtered:
                self.count_label.setText("0 färger")
                return
            
            cols = list(filtered[0].keys())[:6]
            
            self.table.setColumnCount(len(cols))
            self.table.setHorizontalHeaderLabels(cols)
            
            for row_data in filtered:
                row = self.table.rowCount()
                self.table.insertRow(row)
                
                for col, key in enumerate(cols):
                    value = str(row_data.get(key, ""))
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, col, item)
            
            self.count_label.setText(f"{len(filtered)} färger")
            
        except Exception as e:
            logger.error(f"Table update failed: {e}")
    
    def _export_csv(self) -> None:
        """Exportera till CSV. KRASCHSÄKER."""
        try:
            if not self._data:
                QMessageBox.warning(self, "Ingen data", "Ingen data att exportera")
                return
            
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Exportera CSV",
                f"farger_{datetime.now().strftime('%Y%m%d')}.csv",
                "CSV-filer (*.csv)"
            )
            
            if not filepath:
                return
            
            with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self._data[0].keys(), delimiter=';')
                writer.writeheader()
                writer.writerows(self._data)
            
            QMessageBox.information(self, "Export klar", f"Exporterade {len(self._data)} rader")
            
        except Exception as e:
            QMessageBox.critical(self, "Fel", f"Kunde inte exportera: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# VIN-FLIK
# ══════════════════════════════════════════════════════════════════════════════

class VinsTab(QWidget):
    """Flik för registrerade VIN per år/månad. KRASCHSÄKER."""
    
    MONTH_NAMES = {
        '01': 'Januari', '02': 'Februari', '03': 'Mars',
        '04': 'April', '05': 'Maj', '06': 'Juni',
        '07': 'Juli', '08': 'Augusti', '09': 'September',
        '10': 'Oktober', '11': 'November', '12': 'December'
    }
    
    def __init__(self, parent: QWidget, app):
        super().__init__(parent)
        self.app = app
        self._data: Dict = {}
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Bygg UI. KRASCHSÄKER."""
        try:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(5, 5, 5, 5)
            
            # Header
            header_layout = QHBoxLayout()
            header_layout.addWidget(QLabel("📊 Registrerade VIN per år"))
            
            self.btn_refresh = QPushButton("🔄 Uppdatera")
            self.btn_refresh.clicked.connect(self.refresh)
            header_layout.addStretch()
            header_layout.addWidget(self.btn_refresh)
            
            layout.addLayout(header_layout)
            
            # Splitter
            splitter = QSplitter(Qt.Horizontal)
            
            # Vänster: Årstabell
            left_widget = QWidget()
            left_layout = QVBoxLayout(left_widget)
            left_layout.setContentsMargins(0, 0, 0, 0)
            
            left_layout.addWidget(QLabel("År:"))
            self.year_table = QTableWidget()
            self.year_table.setColumnCount(2)
            self.year_table.setHorizontalHeaderLabels(["År", "Antal VIN"])
            self.year_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.year_table.setAlternatingRowColors(True)
            self.year_table.itemSelectionChanged.connect(self._on_year_selected)
            self.year_table.setStyleSheet("""
                QTableWidget {
                    background: #222; gridline-color: #444;
                    color: #fff; alternate-background-color: #2a2a2a;
                }
                QHeaderView::section { 
                    background: #333; color: #fff; 
                    padding: 6px;
                }
            """)
            left_layout.addWidget(self.year_table)
            
            splitter.addWidget(left_widget)
            
            # Höger: Detaljer
            right_widget = QWidget()
            right_layout = QVBoxLayout(right_widget)
            right_layout.setContentsMargins(0, 0, 0, 0)
            
            self.detail_label = QLabel("Månader:")
            right_layout.addWidget(self.detail_label)
            
            self.detail_table = QTableWidget()
            self.detail_table.setColumnCount(2)
            self.detail_table.setHorizontalHeaderLabels(["Månad", "Antal VIN"])
            self.detail_table.setAlternatingRowColors(True)
            self.detail_table.setStyleSheet("""
                QTableWidget {
                    background: #222; gridline-color: #444;
                    color: #fff; alternate-background-color: #2a2a2a;
                }
                QHeaderView::section { 
                    background: #333; color: #fff; 
                    padding: 6px;
                }
            """)
            right_layout.addWidget(self.detail_table)
            
            splitter.addWidget(right_widget)
            splitter.setSizes([200, 400])
            
            layout.addWidget(splitter)
            
            # Statistik
            self.stats_label = QLabel("")
            self.stats_label.setStyleSheet("color: #888; padding: 5px;")
            layout.addWidget(self.stats_label)
            
        except Exception as e:
            logger.error(f"VinsTab UI setup failed: {e}")
    
    def refresh(self) -> None:
        """Ladda data. KRASCHSÄKER."""
        try:
            self._data.clear()
            self.year_table.setRowCount(0)
            self.detail_table.setRowCount(0)
            
            # Hämta från vehicle_registry
            vehicle_registry = get_plugin_safe(self.app, "vehicle_registry")
            if vehicle_registry and hasattr(vehicle_registry, "vin_registry"):
                try:
                    vin_reg = vehicle_registry.vin_registry
                    if hasattr(vin_reg, 'get_all'):
                        self._data = vin_reg.get_all()
                    elif hasattr(vin_reg, '_data'):
                        self._data = vin_reg._data
                except Exception as e:
                    logger.debug(f"VIN registry failed: {e}")
            
            # Fallback: Ladda från JSON
            if not self._data:
                try:
                    base_path = getattr(self.app, 'base_path', Path.cwd())
                    json_path = Path(base_path) / "data" / "vehicle_registry" / "registered_vins.json"
                    if json_path.exists():
                        with open(json_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        self._data = data.get("registered_vins", data)
                except Exception as e:
                    logger.debug(f"VIN JSON failed: {e}")
            
            # Fyll årstabell
            total = 0
            for year in sorted(self._data.keys(), reverse=True):
                if year.startswith('_'):
                    continue
                
                year_data = self._data[year]
                count = sum(len(v) for v in year_data.values() if isinstance(v, list))
                total += count
                
                row = self.year_table.rowCount()
                self.year_table.insertRow(row)
                self.year_table.setItem(row, 0, QTableWidgetItem(str(year)))
                self.year_table.setItem(row, 1, QTableWidgetItem(str(count)))
            
            self.stats_label.setText(f"Totalt: {total} registrerade VIN")
            
        except Exception as e:
            logger.error(f"Refresh failed: {e}")
    
    def _on_year_selected(self) -> None:
        """Visa månader för valt år. KRASCHSÄKER."""
        try:
            selected = self.year_table.selectedItems()
            if not selected:
                return
            
            year = selected[0].text()
            year_data = self._data.get(year, {})
            
            self.detail_label.setText(f"Månader för {year}:")
            self.detail_table.setRowCount(0)
            
            for month in sorted(year_data.keys()):
                if month.startswith('_'):
                    continue
                
                vins = year_data[month]
                if not isinstance(vins, list):
                    continue
                
                name = self.MONTH_NAMES.get(month, month)
                
                row = self.detail_table.rowCount()
                self.detail_table.insertRow(row)
                self.detail_table.setItem(row, 0, QTableWidgetItem(f"{month} ({name})"))
                self.detail_table.setItem(row, 1, QTableWidgetItem(str(len(vins))))
                
        except Exception as e:
            logger.error(f"Year selection failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA-FLIK (NY!)
# ══════════════════════════════════════════════════════════════════════════════

class SchemasTab(QWidget):
    """Flik för TS-scheman. KRASCHSÄKER."""
    
    def __init__(self, parent: QWidget, app):
        super().__init__(parent)
        self.app = app
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Bygg UI. KRASCHSÄKER."""
        try:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(5, 5, 5, 5)
            
            # Header
            header = QHBoxLayout()
            header.addWidget(QLabel("📐 TS-scheman (från ts_spec_import)"))
            header.addStretch()
            
            self.version_label = QLabel("Version: -")
            self.version_label.setStyleSheet("color: #888;")
            header.addWidget(self.version_label)
            
            self.btn_refresh = QPushButton("🔄")
            self.btn_refresh.clicked.connect(self.refresh)
            header.addWidget(self.btn_refresh)
            
            layout.addLayout(header)
            
            # Splitter
            splitter = QSplitter(Qt.Horizontal)
            
            # Vänster: Posttyper
            left_widget = QWidget()
            left_layout = QVBoxLayout(left_widget)
            left_layout.setContentsMargins(0, 0, 0, 0)
            left_layout.addWidget(QLabel("Posttyper:"))
            
            self.post_list = QTableWidget()
            self.post_list.setColumnCount(3)
            self.post_list.setHorizontalHeaderLabels(["PT", "Namn", "Fält"])
            self.post_list.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.post_list.itemSelectionChanged.connect(self._on_post_selected)
            self.post_list.setStyleSheet("""
                QTableWidget {
                    background: #222; gridline-color: #444;
                    color: #fff;
                }
                QHeaderView::section { 
                    background: #333; color: #fff; 
                    padding: 6px;
                }
            """)
            left_layout.addWidget(self.post_list)
            splitter.addWidget(left_widget)
            
            # Höger: Fält
            right_widget = QWidget()
            right_layout = QVBoxLayout(right_widget)
            right_layout.setContentsMargins(0, 0, 0, 0)
            
            self.fields_label = QLabel("Fält:")
            right_layout.addWidget(self.fields_label)
            
            self.fields_table = QTableWidget()
            self.fields_table.setColumnCount(5)
            self.fields_table.setHorizontalHeaderLabels(["Namn", "Pos", "Längd", "Typ", "Oblig."])
            self.fields_table.setAlternatingRowColors(True)
            self.fields_table.setStyleSheet("""
                QTableWidget {
                    background: #222; gridline-color: #444;
                    color: #fff; alternate-background-color: #2a2a2a;
                }
                QHeaderView::section { 
                    background: #333; color: #fff; 
                    padding: 6px;
                }
            """)
            self.fields_table.horizontalHeader().setStretchLastSection(True)
            right_layout.addWidget(self.fields_table)
            
            splitter.addWidget(right_widget)
            splitter.setSizes([250, 500])
            
            layout.addWidget(splitter)
            
            # Status
            self.status_label = QLabel("")
            self.status_label.setStyleSheet("color: #888;")
            layout.addWidget(self.status_label)
            
        except Exception as e:
            logger.error(f"SchemasTab UI setup failed: {e}")
    
    def refresh(self) -> None:
        """Ladda scheman. KRASCHSÄKER."""
        try:
            self.post_list.setRowCount(0)
            self.fields_table.setRowCount(0)
            
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if not ts_spec:
                self.status_label.setText("❌ ts_spec_import ej tillgänglig")
                return
            
            # Hämta aktiv version
            version = ts_spec.get_active_version()
            self.version_label.setText(f"Version: {version or 'ingen'}")
            
            # Hämta scheman
            schemas = ts_spec.get_all_schemas()
            
            for post_type, schema in sorted(schemas.items()):
                row = self.post_list.rowCount()
                self.post_list.insertRow(row)
                
                self.post_list.setItem(row, 0, QTableWidgetItem(f"PT{post_type}"))
                
                name = getattr(schema, 'name', f"Posttyp {post_type}")
                self.post_list.setItem(row, 1, QTableWidgetItem(name))
                
                field_count = len(schema.fields) if hasattr(schema, 'fields') else 0
                self.post_list.setItem(row, 2, QTableWidgetItem(str(field_count)))
            
            self.status_label.setText(f"✅ {len(schemas)} scheman laddade")
            
        except Exception as e:
            logger.error(f"Schema refresh failed: {e}")
            self.status_label.setText(f"❌ Fel: {e}")
    
    def _on_post_selected(self) -> None:
        """Visa fält för vald posttyp. KRASCHSÄKER."""
        try:
            selected = self.post_list.selectedItems()
            if not selected:
                return
            
            post_type = selected[0].text().replace("PT", "")
            
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if not ts_spec:
                return
            
            schema = ts_spec.get_schema(post_type)
            if not schema or not hasattr(schema, 'fields'):
                return
            
            self.fields_label.setText(f"Fält för PT{post_type}:")
            self.fields_table.setRowCount(0)
            
            for field in sorted(schema.fields, key=lambda f: f.position):
                row = self.fields_table.rowCount()
                self.fields_table.insertRow(row)
                
                self.fields_table.setItem(row, 0, QTableWidgetItem(field.name))
                self.fields_table.setItem(row, 1, QTableWidgetItem(str(field.position)))
                self.fields_table.setItem(row, 2, QTableWidgetItem(str(field.length)))
                self.fields_table.setItem(row, 3, QTableWidgetItem(str(getattr(field, 'field_type', 'AN'))))
                self.fields_table.setItem(row, 4, QTableWidgetItem("Ja" if getattr(field, 'required', False) else ""))
                
        except Exception as e:
            logger.error(f"Post selection failed: {e}")
    
    def select_post_type(self, post_type: str) -> None:
        """Välj specifik posttyp. KRASCHSÄKER."""
        try:
            for row in range(self.post_list.rowCount()):
                item = self.post_list.item(row, 0)
                if item and item.text() == f"PT{post_type}":
                    self.post_list.selectRow(row)
                    break
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# VALIDERING-FLIK (NY!)
# ══════════════════════════════════════════════════════════════════════════════

class ValidationTab(QWidget):
    """Flik för valideringsresultat. KRASCHSÄKER."""
    
    def __init__(self, parent: QWidget, app):
        super().__init__(parent)
        self.app = app
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Bygg UI. KRASCHSÄKER."""
        try:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(5, 5, 5, 5)
            
            # Header
            header = QHBoxLayout()
            header.addWidget(QLabel("✅ Datavalidering"))
            header.addStretch()
            
            self.btn_validate = QPushButton("🔍 Validera data")
            self.btn_validate.clicked.connect(self._run_validation)
            header.addWidget(self.btn_validate)
            
            layout.addLayout(header)
            
            # Resultat
            self.results_table = QTableWidget()
            self.results_table.setColumnCount(4)
            self.results_table.setHorizontalHeaderLabels(["Typ", "Fält", "Status", "Meddelande"])
            self.results_table.setAlternatingRowColors(True)
            self.results_table.setStyleSheet("""
                QTableWidget {
                    background: #222; gridline-color: #444;
                    color: #fff; alternate-background-color: #2a2a2a;
                }
                QHeaderView::section { 
                    background: #333; color: #fff; 
                    padding: 6px;
                }
            """)
            self.results_table.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(self.results_table)
            
            # Sammanfattning
            self.summary_label = QLabel("Kör validering för att se resultat")
            self.summary_label.setStyleSheet("color: #888; padding: 5px;")
            layout.addWidget(self.summary_label)
            
        except Exception as e:
            logger.error(f"ValidationTab UI setup failed: {e}")
    
    def _run_validation(self) -> None:
        """Kör validering. KRASCHSÄKER."""
        try:
            self.results_table.setRowCount(0)
            
            ts_spec = get_plugin_safe(self.app, "ts_spec_import")
            if not ts_spec:
                self.summary_label.setText("❌ ts_spec_import ej tillgänglig")
                return
            
            # Validera scheman
            validation = ts_spec.validate_all_schemas()
            
            total_issues = 0
            for post_type, issues in validation.items():
                for issue in issues:
                    row = self.results_table.rowCount()
                    self.results_table.insertRow(row)
                    
                    self.results_table.setItem(row, 0, QTableWidgetItem(f"PT{post_type}"))
                    self.results_table.setItem(row, 1, QTableWidgetItem("-"))
                    self.results_table.setItem(row, 2, QTableWidgetItem("⚠️"))
                    self.results_table.setItem(row, 3, QTableWidgetItem(issue))
                    
                    total_issues += 1
            
            if total_issues == 0:
                self.summary_label.setText("✅ Inga problem hittades!")
            else:
                self.summary_label.setText(f"⚠️ {total_issues} problem hittades")
                
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            self.summary_label.setText(f"❌ Fel: {e}")
    
    def display_results(self, results: List[Dict[str, Any]]) -> None:
        """Visa externa valideringsresultat. KRASCHSÄKER."""
        try:
            self.results_table.setRowCount(0)
            
            for result in results:
                row = self.results_table.rowCount()
                self.results_table.insertRow(row)
                
                self.results_table.setItem(row, 0, QTableWidgetItem(str(result.get("type", "-"))))
                self.results_table.setItem(row, 1, QTableWidgetItem(str(result.get("field", "-"))))
                self.results_table.setItem(row, 2, QTableWidgetItem(str(result.get("status", "-"))))
                self.results_table.setItem(row, 3, QTableWidgetItem(str(result.get("message", "-"))))
            
            self.summary_label.setText(f"Visar {len(results)} resultat")
            
        except Exception as e:
            logger.error(f"Display results failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIK-FLIK (NY!)
# ══════════════════════════════════════════════════════════════════════════════

class DiagnosticsTab(QWidget):
    """Flik för systemdiagnostik. KRASCHSÄKER."""
    
    def __init__(self, parent: QWidget, app, plugin: Plugin):
        super().__init__(parent)
        self.app = app
        self.plugin = plugin
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Bygg UI. KRASCHSÄKER."""
        try:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(5, 5, 5, 5)
            
            # Header
            header = QHBoxLayout()
            header.addWidget(QLabel("🔧 Systemdiagnostik"))
            header.addStretch()
            
            self.btn_refresh = QPushButton("🔄 Uppdatera")
            self.btn_refresh.clicked.connect(self.refresh)
            header.addWidget(self.btn_refresh)
            
            layout.addLayout(header)
            
            # Diagnostik-text
            self.diag_text = QPlainTextEdit()
            self.diag_text.setReadOnly(True)
            self.diag_text.setStyleSheet("""
                QPlainTextEdit {
                    background: #1a1a1a; color: #00ff00;
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 12px;
                    border: 1px solid #444;
                }
            """)
            layout.addWidget(self.diag_text)
            
        except Exception as e:
            logger.error(f"DiagnosticsTab UI setup failed: {e}")
    
    def refresh(self) -> None:
        """Uppdatera diagnostik. KRASCHSÄKER."""
        try:
            diag = self.plugin.show_diagnostics()
            
            lines = [
                "=" * 60,
                f"  SYSTEMDIAGNOSTIK - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "=" * 60,
                "",
                f"Plugin: {diag.get('plugin_name', 'N/A')} v{diag.get('plugin_version', 'N/A')}",
                f"Copyright: {diag.get('copyright', 'N/A')}",
                f"Initierad: {'Ja' if diag.get('initialized') else 'Nej'}",
                f"Widget aktiv: {'Ja' if diag.get('widget_active') else 'Nej'}",
                "",
                "TILLGÄNGLIGA PLUGINS:",
                "-" * 40,
            ]
            
            for plugin_name in diag.get('available_plugins', []):
                lines.append(f"  ✅ {plugin_name}")
            
            lines.extend([
                "",
                "DATAKÄLLOR:",
                "-" * 40,
            ])
            
            for source, available in diag.get('data_sources', {}).items():
                status = "✅" if available else "❌"
                lines.append(f"  {status} {source}")
            
            # Schema-status
            schema_status = diag.get('schema_status', {})
            if schema_status:
                lines.extend([
                    "",
                    "SCHEMA-STATUS:",
                    "-" * 40,
                    f"  Aktiv version: {schema_status.get('active_version', 'N/A')}",
                    f"  Antal versioner: {schema_status.get('version_count', 0)}",
                    f"  Antal scheman: {schema_status.get('schema_count', 0)}",
                ])
            
            # Event-prenumerationer
            lines.extend([
                "",
                "EVENT-PRENUMERATIONER:",
                "-" * 40,
            ])
            for event in diag.get('event_subscriptions', []):
                lines.append(f"  📡 {event}")
            
            lines.extend([
                "",
                "=" * 60,
            ])
            
            self.diag_text.setPlainText("\n".join(lines))
            
        except Exception as e:
            logger.error(f"Diagnostics refresh failed: {e}")
            self.diag_text.setPlainText(f"FEL: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGER
# ══════════════════════════════════════════════════════════════════════════════

class GlobalSearchResultsDialog(QDialog):
    """Dialog för global sökresultat. KRASCHSÄKER."""
    
    def __init__(self, parent: QWidget, query: str, results: Dict[str, Any]):
        super().__init__(parent)
        self.setWindowTitle(f"Sökresultat: {query}")
        self.setMinimumSize(600, 400)
        self._setup_ui(query, results)
    
    def _setup_ui(self, query: str, results: Dict[str, Any]) -> None:
        """Bygg UI. KRASCHSÄKER."""
        try:
            layout = QVBoxLayout(self)
            
            # Header
            header = QLabel(f"🔍 Resultat för '{query}': {results.get('total_count', 0)} träffar")
            header.setStyleSheet("font-size: 14px; font-weight: bold;")
            layout.addWidget(header)
            
            # Tabs för varje kategori
            tabs = QTabWidget()
            
            for category, items in results.items():
                if category in ('total_count', 'error') or not isinstance(items, list):
                    continue
                
                tab = QWidget()
                tab_layout = QVBoxLayout(tab)
                
                table = QTableWidget()
                if items:
                    cols = list(items[0].keys())[:5]
                    table.setColumnCount(len(cols))
                    table.setHorizontalHeaderLabels(cols)
                    
                    for item in items[:50]:  # Begränsa till 50
                        row = table.rowCount()
                        table.insertRow(row)
                        for col, key in enumerate(cols):
                            table.setItem(row, col, QTableWidgetItem(str(item.get(key, ""))))
                
                table.horizontalHeader().setStretchLastSection(True)
                tab_layout.addWidget(table)
                
                tabs.addTab(tab, f"{category} ({len(items)})")
            
            layout.addWidget(tabs)
            
            # Stäng-knapp
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            
        except Exception as e:
            logger.error(f"Dialog setup failed: {e}")


class TSPreviewDialog(QDialog):
    """Dialog för TS-förhandsvisning. KRASCHSÄKER."""
    
    def __init__(self, parent: QWidget, post_type: str, formatted: str):
        super().__init__(parent)
        self.setWindowTitle(f"TS-förhandsvisning PT{post_type}")
        self.setMinimumSize(800, 400)
        self._setup_ui(post_type, formatted)
    
    def _setup_ui(self, post_type: str, formatted: str) -> None:
        """Bygg UI. KRASCHSÄKER."""
        try:
            layout = QVBoxLayout(self)
            
            # Info
            info = QLabel(f"PT{post_type} | Längd: {len(formatted)} tecken | Krav: {TS_POST_LENGTH}")
            info.setStyleSheet("color: #888;")
            layout.addWidget(info)
            
            # Status
            if len(formatted) == TS_POST_LENGTH:
                status = QLabel("✅ Korrekt längd!")
                status.setStyleSheet("color: #4caf50; font-weight: bold;")
            else:
                status = QLabel(f"⚠️ Fel längd! Diff: {len(formatted) - TS_POST_LENGTH}")
                status.setStyleSheet("color: #f44336; font-weight: bold;")
            layout.addWidget(status)
            
            # Innehåll
            text = QPlainTextEdit()
            text.setPlainText(formatted)
            text.setReadOnly(True)
            text.setStyleSheet("""
                QPlainTextEdit {
                    background: #1a1a1a; color: #00ff00;
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 11px;
                }
            """)
            layout.addWidget(text)
            
            # Knappar
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            
        except Exception as e:
            logger.error(f"Preview dialog setup failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "Plugin",
    "DataViewerWidget",
    "VehiclesTab",
    "DealersViewTab",
    "ColorsViewTab",
    "VinsTab",
    "SchemasTab",
    "ValidationTab",
    "DiagnosticsTab",
    "get_plugin_safe",
]