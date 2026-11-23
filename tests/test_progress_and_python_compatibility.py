from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from core.vehicle_text_export import write_vehicle_text_file
from plugins.ts_file_generator import plugin as ts_plugin


class TextExportTests(unittest.TestCase):
    def test_progress_reaches_100_only_after_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'vehicles.txt'
            path.write_text('original')
            updates = []
            def progress(current, total, message):
                updates.append((current, total, message))
                if current < total:
                    self.assertEqual(path.read_text(), 'original')
                else:
                    self.assertIn('2025;A,B test', path.read_text())
            write_vehicle_text_file(path, [(2025, {'name': 'A;B\ntest'})], ['name'], progress)
            self.assertEqual(updates[0][:2], (0, 2))
            self.assertEqual(updates[-1][:2], (2, 2))
            self.assertFalse(list(path.parent.glob('*.tmp')))

    def test_write_failure_keeps_existing_file_and_never_reports_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'vehicles.txt'
            path.write_text('original')
            updates = []
            with patch('core.vehicle_text_export.os.replace', side_effect=OSError('disk')):
                with self.assertRaises(OSError):
                    write_vehicle_text_file(path, [(2025, {})], ['name'], lambda *p: updates.append(p))
            self.assertEqual(path.read_text(), 'original')
            self.assertTrue(all(current < total for current, total, _ in updates))
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ['vehicles.txt'])


class TSGenerationTests(unittest.TestCase):
    def setUp(self):
        self.plugin = ts_plugin.Plugin(None)
        gate = patch.object(ts_plugin, 'generation_block_reason', return_value=None)
        gate.start()
        self.addCleanup(gate.stop)
        # Frikoppla även Dispatch-kontrollen i just detta test av skrivning och förlopp.
        for name in ('dispatch_color_errors', 'dispatch_vehicle_color_errors'):
            color_gate = patch('core.dispatch_color_gate.' + name, return_value=[])
            color_gate.start()
            self.addCleanup(color_gate.stop)
        # Mockade poster testar endast förlopp/atomisk skrivning, inte TS-format.
        self.plugin._generate_identity_post = lambda *args: 'header'.ljust(2500)
        self.plugin._generate_vehicle_post = lambda seq, vehicle: vehicle['vin'].ljust(2500)
        self.plugin._generate_end_post = lambda *args: 'end'.ljust(2500)

    def test_real_generation_reports_actual_work_and_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'ts.txt'
            updates = []
            def progress(current, total, message):
                updates.append((current, total, message))
                self.assertEqual(output.exists(), current == total)
            result = self.plugin.generate_complete_file([{'vin': 'VIN1'}, {'vin': 'VIN2'}], output_path=output, progress_callback=progress)
            self.assertTrue(result.success, result.errors)
            self.assertEqual(result.total_records, 4)
            self.assertEqual(updates[-1][:2], (4, 4))
            self.assertEqual(len(output.read_bytes().splitlines()), 4)

    def test_write_failure_does_not_report_success_or_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'ts.txt'
            updates = []
            with patch.object(ts_plugin, 'atomic_write_bytes', side_effect=OSError('disk')):
                result = self.plugin.generate_complete_file([{'vin': 'VIN'}], output_path=output, progress_callback=lambda *p: updates.append(p))
            self.assertFalse(result.success)
            self.assertFalse(output.exists())
            self.assertTrue(all(current < total for current, total, _ in updates))


class ExcelEngineTests(unittest.TestCase):
    @staticmethod
    def engine_class(pd, write):
        # The engine is defined in a Qt widget module. Extract the unchanged
        # class so its real import logic can be exercised without a Qt runtime.
        source = Path('plugins/data_mapping/widget.py').read_text()
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ExcelImportEngine')
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[])
        env = {'pd': pd, 'Path': Path, 'datetime': datetime, 'PANDAS_AVAILABLE': True,
               '_get_excel_engine': lambda p: 'openpyxl', '_should_skip_sheet': lambda s: False,
               '_normalize_header': str.strip, 'SKIP_SHEETS_DEFAULT': [], '_atomic_write_json': write}
        exec(compile(ast.fix_missing_locations(module), '<excel_engine>', 'exec'), env)
        return env['ExcelImportEngine']

    def test_sheet_and_save_progress_are_not_reported_in_advance(self):
        events = []
        xls = SimpleNamespace(sheet_names=['A', 'B'], close=lambda: events.append(('closed',)))
        def read_excel(xls, sheet_name, **kwargs):
            events.append(('reading', sheet_name))
            return SimpleNamespace(fillna=lambda _: SimpleNamespace(columns=[' VIN '], values=SimpleNamespace(tolist=lambda: [['X']])))
        pd = SimpleNamespace(ExcelFile=lambda *a, **kw: xls, read_excel=read_excel)
        engine = self.engine_class(pd, lambda *args: events.append(('saved',)))()
        with tempfile.TemporaryDirectory() as tmp, patch('pathlib.Path.mkdir'):
            result = engine.import_file(Path(tmp) / 'test.xlsx', lambda *p: events.append(p))
        self.assertEqual(result[0], ['VIN'])
        self.assertEqual(len(result[1]), 2)
        self.assertLess(events.index(('saved',)), next(i for i, event in enumerate(events) if len(event) == 3 and event[0] == 3))
        self.assertIn((0, 3, 'Läser blad A (1/2)'), events)
        self.assertIn((1, 3, 'Läser blad B (2/2)'), events)
        self.assertLess(events.index(('reading', 'B')), events.index((2, 3, 'Bearbetat 2 av 2 blad')))

    def test_real_excel_workbook(self):
        try:
            import pandas as pd
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("pandas/openpyxl saknas i testmiljön")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'user.xlsx'
            with pd.ExcelWriter(path) as writer:
                pd.DataFrame({' VIN ': ['ABC', 'DEF']}).to_excel(writer, sheet_name='First', index=False)
                pd.DataFrame({' VIN ': ['GHI']}).to_excel(writer, sheet_name='Second', index=False)
            saved = []
            engine = self.engine_class(pd, lambda path, data: saved.append(data))()
            updates = []
            with patch('pathlib.Path.mkdir'):
                headers, rows, info = engine.import_file(path, lambda *args: updates.append(args))
            self.assertEqual(headers, ['VIN'])
            self.assertEqual(len(rows), 3)
            self.assertEqual(len(info), 2)
            self.assertEqual(len(saved), 1)
            self.assertEqual(updates[-1][:2], (3, 3))

    def test_failed_metadata_write_does_not_report_completion(self):
        xls = SimpleNamespace(sheet_names=[], close=lambda: None)
        pd = SimpleNamespace(ExcelFile=lambda *a, **kw: xls)
        def fail(*args):
            raise OSError('disk')
        engine = self.engine_class(pd, fail)()
        updates = []
        with patch('pathlib.Path.mkdir'), self.assertRaises(RuntimeError):
            engine.import_file(Path('test.xlsx'), lambda *args: updates.append(args))
        self.assertTrue(all(current < total for current, total, _ in updates))



if __name__ == '__main__':
    unittest.main()
