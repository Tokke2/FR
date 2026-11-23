from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

try:
    import pandas as pd
except ImportError:
    pd = None

from plugins.dispatch_viewer import plugin as dispatch


@unittest.skipIf(pd is None, 'pandas saknas')
class DispatchColorTests(unittest.TestCase):
    def test_load_file_passes_only_real_names_and_keeps_dispatch(self):
        colors = SimpleNamespace(record_dispatch_colors=Mock(return_value=SimpleNamespace(success=True)))
        plugin = dispatch.Plugin(SimpleNamespace(colors_manager=colors))
        df = pd.DataFrame({'VIN': ['A', 'B', 'C', 'D'], 'FÄRG': [' Alpine ', None, 'nan', 'Alpine']})
        df = plugin._strip_columns(df)
        plugin._load_dispatch_file = Mock(return_value=df)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'dispatch.xlsx'; path.touch()
            self.assertTrue(plugin.load_file(str(path)))
        self.assertEqual(plugin.get_current_data().shape[0], 4)
        self.assertEqual(colors.record_dispatch_colors.call_args.args[0], ['Alpine', 'nan', 'Alpine'])

    def test_actual_excel_adds_pending_colors_without_changing_source(self):
        from test_color_tab import load_color_module
        module = load_color_module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = module.ColorService(root / 'farger.json', root / 'mappings.json')
            service.load()
            color_plugin = object.__new__(module.Plugin)
            color_plugin._service = service
            color_plugin._widget = None
            plugin = dispatch.Plugin(SimpleNamespace(colors_manager=color_plugin))
            path = root / 'dispatch.xlsx'
            pd.DataFrame({'VIN': ['WBA12345678901234', 'WBA12345678901235'],
                          'Color': ['Alpine White', 'Black']}).to_excel(path, index=False)
            original = path.read_bytes()
            self.assertTrue(plugin.load_file(str(path)))
            self.assertEqual(path.read_bytes(), original)
            service.load()
            self.assertEqual({x.name for x in service.get_all()}, {'Alpine White', 'Black'})
            self.assertTrue(all(not x.code and not x.ts_code for x in service.get_all()))
            self.assertTrue(plugin.load_file(str(path)))
            self.assertEqual(len(service.get_all()), 2)

    def test_code_only_or_ambiguous_columns_do_not_guess(self):
        colors = SimpleNamespace(record_dispatch_colors=Mock())
        plugin = dispatch.Plugin(SimpleNamespace(colors_manager=colors))
        plugin._record_dispatch_colors(pd.DataFrame({'COLORCODE': ['123']}))
        plugin._record_dispatch_colors(pd.DataFrame({'Color': ['red'], 'Färg': ['blue']}))
        colors.record_dispatch_colors.assert_not_called()

    def test_failure_does_not_prevent_loading(self):
        colors = SimpleNamespace(record_dispatch_colors=Mock(return_value=SimpleNamespace(success=False, message='disk')))
        plugin = dispatch.Plugin(SimpleNamespace(colors_manager=colors))
        plugin._load_dispatch_file = Mock(return_value=pd.DataFrame({'VIN': ['A'], 'Color': ['Red']}))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'dispatch.xlsx'; path.touch()
            self.assertTrue(plugin.load_file(str(path)))
        colors.record_dispatch_colors.assert_called_once()


if __name__ == '__main__':
    unittest.main()
