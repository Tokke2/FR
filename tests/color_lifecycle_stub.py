"""Verklig pluginladdning och färg-CRUD i temporär katalog med Qt-stubbar."""
from __future__ import annotations
import asyncio
import importlib
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace

from core.plugin_loader import PluginLoader
from core.dealer_pin import DealerPin

package = ModuleType('PySide6'); package.__path__ = []
qtcore = ModuleType('PySide6.QtCore'); qtcore.Qt = SimpleNamespace()
qtgui = ModuleType('PySide6.QtGui')
for name in ('QColor', 'QBrush', 'QFont'): setattr(qtgui, name, type(name, (), {}))
widgets = ModuleType('PySide6.QtWidgets')
for name in ('QAbstractItemView', 'QComboBox', 'QDialog', 'QDialogButtonBox', 'QFrame', 'QGridLayout',
             'QGroupBox', 'QHBoxLayout', 'QLabel', 'QLineEdit', 'QMessageBox', 'QPushButton', 'QSplitter',
             'QTableWidget', 'QTableWidgetItem', 'QVBoxLayout', 'QWidget', 'QHeaderView'):
    setattr(widgets, name, type(name, (), {}))
sys.modules.update({'PySide6': package, 'PySide6.QtCore': qtcore, 'PySide6.QtGui': qtgui, 'PySide6.QtWidgets': widgets})

with tempfile.TemporaryDirectory() as folder:
    root = Path(__file__).resolve().parents[1]
    pin = DealerPin(Path(folder) / '.js data' / 'aterforsaljare_pin.json'); pin.create('123456')
    app = SimpleNamespace(config=SimpleNamespace(get=lambda key, default=None: folder if key == 'base_dir' else default),
                          event_bus=SimpleNamespace(emit=lambda *args: None, on=lambda *args, **kwargs: None, off=lambda *args, **kwargs: None),
                          dealers=SimpleNamespace(dealer_pin=lambda: pin))
    loader = PluginLoader(root / 'plugins', app=app, auto_discover=True)
    plugin = asyncio.run(loader.load('colors_manager', retry=False))
    assert plugin is not None
    loader._load_order = ['colors_manager']
    assert 'colors_manager' in asyncio.run(loader.initialize_all()).success
    assert 'colors_manager' in asyncio.run(loader.activate_all()).success
    module = importlib.import_module('plugins.colors_manager.plugin')
    widget = object()
    module.ColorsWidget = lambda parent, service: widget
    assert plugin.create_widget(object()) is widget
    assert not plugin.add_color('01', 'Vit', 'WIT').success
    assert plugin.add_color('01', 'Vit', 'WIT', pin='123456').success
    assert plugin.lookup_ts_code('Vit') == 'WIT'
    assert (Path(folder) / 'data/colors_manager/farger.json').is_file()
    assert asyncio.run(loader.shutdown_all()).success
print('color lifecycle OK')
