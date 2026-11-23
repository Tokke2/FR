from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.ts_source_import import import_source
from core.dispatch_color_gate import dispatch_color_errors, dispatch_vehicle_color_errors
from core.dealer_pin import DealerPin
from test_color_tab import load_color_module

try:
    import openpyxl
    import pandas as pd
except ImportError:
    openpyxl = pd = None


@unittest.skipIf(openpyxl is None, 'Excel-testberoenden saknas')
class TSSourceTests(unittest.TestCase):
    def test_safe_import_preserves_original_and_does_not_activate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'spec.xlsx'
            wb = openpyxl.Workbook(); wb.active.title = 'PT28'; wb.create_sheet('PT45'); wb.create_sheet('PT99')
            wb.active['A1'] = 'underlag'; wb.save(source); wb.close()
            original = source.read_bytes()
            info = import_source(source, root / 'archive')
            self.assertEqual(info['status'], 'ej_granskat')
            self.assertEqual(info['sheets'], ['PT28', 'PT45', 'PT99'])
            self.assertEqual(info['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual((Path(info['directory']) / info['file']).read_bytes(), original)
            self.assertEqual(json.loads((Path(info['directory']) / 'information.json').read_text())['status'], 'ej_granskat')
            again = import_source(source, root / 'archive')
            self.assertNotEqual(again['directory'], info['directory'])

    def test_corrupt_excel_leaves_no_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'bad.xlsx'; source.write_bytes(b'not excel')
            with self.assertRaises(ValueError): import_source(source, root / 'archive')
            self.assertFalse((root / 'archive').exists())
            self.assertEqual(source.read_bytes(), b'not excel')


@unittest.skipIf(pd is None, 'pandas saknas')
class DispatchGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        pin = DealerPin(root / 'pin.json'); pin.create('123456')
        module = load_color_module()
        self.service = module.ColorService(root / 'colors.json', root / 'map.json', pin_provider=lambda: pin)
        self.service.load()
        self.assertTrue(self.service.add('A', 'Alpine', 'WIT', pin='123456').success)
        self.dispatch = SimpleNamespace(get_current_data=lambda: self.frame)
        self.app = SimpleNamespace(dispatch_viewer=self.dispatch, colors_manager=SimpleNamespace(service=self.service))

    def test_unmapped_missing_conflicts_and_multiple_columns_block(self):
        self.frame = pd.DataFrame({'Color': ['Alpine', 'red metallic']})
        self.assertTrue(dispatch_color_errors(self.app))  # Fuzzy/keywords are not approval.
        self.assertTrue(self.service.add_mapping('red metallic', 'ROT', pin='123456'))
        self.assertEqual(dispatch_color_errors(self.app), [])
        self.frame = pd.DataFrame({'Color': ['Alpine'], 'COLORCODE': ['MISSING']})
        self.assertTrue(dispatch_color_errors(self.app))
        self.frame = pd.DataFrame({'Color': ['Alpine'], 'COLORCODE': ['A']})
        self.assertEqual(dispatch_color_errors(self.app), [])
        self.frame = pd.DataFrame({'Color': ['Wrong'], 'COLORCODE': ['A']})
        self.assertTrue(dispatch_color_errors(self.app))
        self.frame = pd.DataFrame({'Color': ['Alpine'], 'Färg': ['Alpine']})
        self.assertTrue(dispatch_color_errors(self.app))

    def test_vehicle_ts_code_must_match_unique_dispatch_vin(self):
        self.frame = pd.DataFrame({'VIN': ['VIN1'], 'Color': ['Alpine']})
        self.assertEqual(dispatch_vehicle_color_errors(self.app, [{'vin': 'VIN1', 'color_ts_code': 'WIT'}]), [])
        self.assertTrue(dispatch_vehicle_color_errors(self.app, [{'vin': 'VIN1', 'color_ts_code': 'ROT'}]))
        self.assertTrue(dispatch_vehicle_color_errors(self.app, [{'vin': 'VIN2', 'color_ts_code': 'WIT'}]))
        self.frame = pd.concat([self.frame, self.frame], ignore_index=True)
        self.assertTrue(dispatch_vehicle_color_errors(self.app, [{'vin': 'VIN1', 'color_ts_code': 'WIT'}]))

    def test_corrupt_data_and_absent_dispatch_fail_closed(self):
        self.frame = pd.DataFrame({'Color': ['Alpine']})
        self.service.colors_file.write_text('broken')
        self.assertTrue(dispatch_color_errors(self.app))
        self.assertTrue(dispatch_color_errors(None))

    def test_generator_does_not_overwrite_even_if_global_block_is_disabled(self):
        from plugins.ts_file_generator import plugin as ts
        self.frame = pd.DataFrame({'Color': ['unmapped']})
        with tempfile.TemporaryDirectory() as tmp, patch.object(ts, 'generation_block_reason', return_value=''):
            target = Path(tmp) / 'ts.txt'; target.write_text('old')
            result = ts.Plugin(self.app).generate_complete_file([{'vin': 'ABC'}], output_path=target)
            self.assertFalse(result.success)
            self.assertIn('Dispatch-färger', result.errors[0])
            self.assertEqual(target.read_text(), 'old')


if __name__ == '__main__':
    unittest.main()
