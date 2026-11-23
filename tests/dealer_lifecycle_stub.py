"""Separat process: pluginladdarens riktiga livscykel med minimala Qt-stubbar."""
from __future__ import annotations
import asyncio
import importlib
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace

from core.plugin_loader import PluginLoader

package = ModuleType('PySide6'); package.__path__ = []
qtcore = ModuleType('PySide6.QtCore')
qtcore.Qt = SimpleNamespace(ItemDataRole=SimpleNamespace(DisplayRole=0, TextAlignmentRole=1, ToolTipRole=2))
qtcore.QModelIndex = type('QModelIndex', (), {})
qtcore.QAbstractTableModel = type('QAbstractTableModel', (), {})
qtcore.QSortFilterProxyModel = type('QSortFilterProxyModel', (), {})
qtgui = ModuleType('PySide6.QtGui'); qtgui.QFont = type('QFont', (), {})
widgets = ModuleType('PySide6.QtWidgets')
for name in ('QAbstractItemView', 'QDialog', 'QFileDialog', 'QGridLayout', 'QGroupBox',
             'QHBoxLayout', 'QHeaderView', 'QInputDialog', 'QLabel', 'QLineEdit',
             'QMessageBox', 'QPushButton', 'QSizePolicy', 'QTableView', 'QVBoxLayout',
             'QWidget', 'QScrollArea', 'QFrame'):
    setattr(widgets, name, type(name, (), {}))
sys.modules.update({'PySide6': package, 'PySide6.QtCore': qtcore,
                    'PySide6.QtGui': qtgui, 'PySide6.QtWidgets': widgets})

with tempfile.TemporaryDirectory() as folder:
    root = Path(__file__).resolve().parents[1]
    app = SimpleNamespace(config=SimpleNamespace(get=lambda key, default=None: folder if key == 'base_dir' else default),
                          event_bus=SimpleNamespace(emit=lambda *args: None, on=lambda *args, **kwargs: None, off=lambda *args, **kwargs: None))
    loader = PluginLoader(root / 'plugins', app=app, auto_discover=True)
    plugin = asyncio.run(loader.load('dealers_manager', retry=False))
    assert plugin is not None
    loader._load_order = ['dealers_manager']
    assert 'dealers_manager' in asyncio.run(loader.initialize_all()).success
    assert 'dealers_manager' in asyncio.run(loader.activate_all()).success
    module = importlib.import_module('plugins.dealers_manager.plugin')
    widget = object()
    module.DealersWidget = lambda parent, owner, plugin: widget
    assert plugin.create_widget(object()) is widget
    plugin.dealer_pin().create('123456')
    assert not plugin.add_dealer({'dealer_number': '999', 'namn': 'Test'}, pin='999999')
    assert plugin.add_dealer({'dealer_number': '007', 'namn': 'Test'}, pin='123456')
    assert plugin.get_by_dn('007')['namn'] == 'Test'
    assert (Path(folder) / '.js data' / 'aterforsaljare.json').is_file()
    assert asyncio.run(loader.shutdown_all()).success
print('dealer lifecycle OK')
