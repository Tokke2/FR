from __future__ import annotations

import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.ts_safety import PT45_MC_MOPED_LAYOUT, audit_pt45_record, audit_pt45_schema
from plugins.ts_file_generator import plugin as ts_plugin
from plugins.ts_file_generator.record_builder import RecordBuilder
from plugins.vehicle_registration_post import plugin as registration
from plugins.identity_post import plugin as identity
from plugins.end_post import plugin as end


class TSPositionTests(unittest.TestCase):
    def test_all_65_intervals_cover_exactly_2500_positions(self):
        fields = PT45_MC_MOPED_LAYOUT
        self.assertEqual(len(fields), 65)
        self.assertEqual(fields[0], (1, 4))
        self.assertEqual(fields[-1], (607, 2500))
        for previous, current in zip(fields, fields[1:]):
            self.assertEqual(current[0], previous[1] + 1)
        self.assertEqual(fields[17], (292, 308))
        self.assertEqual(fields[27], (376, 381))
        self.assertEqual(fields[54], (569, 570))
        # Oberoende lista med sluttalen från sidorna 1–4: varje gräns granskas.
        expected_ends = [4, 6, 16, 22, 26, 106, 114, 118, 122, 146,
                         149, 155, 179, 219, 259, 283, 291, 308, 333, 341,
                         349, 351, 354, 361, 366, 371, 375, 381, 387, 393,
                         399, 405, 410, 415, 421, 426, 432, 437, 443, 449,
                         459, 464, 469, 489, 509, 510, 516, 519, 524, 527,
                         530, 535, 538, 568, 570, 576, 577, 578, 579, 584,
                         589, 594, 600, 606, 2500]
        self.assertEqual([end for _, end in fields], expected_ends)

    def test_schema_audit_rejects_wrong_or_omitted_intervals_and_overlap(self):
        fields = [SimpleNamespace(position=a, length=b-a+1) for a, b in PT45_MC_MOPED_LAYOUT]
        schema = SimpleNamespace(total_length=2500, fields=fields)
        self.assertEqual(audit_pt45_schema(schema), [])  # Only intervals, not production approval.
        schema.fields = fields.copy()
        schema.fields[17] = SimpleNamespace(position=7, length=17)
        errors = audit_pt45_schema(schema)
        self.assertTrue(any('292–308' in e for e in errors))
        self.assertTrue(any('7–23' in e for e in errors))
        schema.fields = fields[:-1]
        self.assertTrue(any('607–2500' in e for e in audit_pt45_schema(schema)))
        schema.fields = fields + [fields[0]]
        self.assertTrue(any('Dubblerade' in e for e in audit_pt45_schema(schema)))

    def test_record_check_position_and_reserved_field(self):
        vin = 'ABCDEFGH123456789'
        record = list(' ' * 2500)
        record[0:4] = '0002'
        record[4:6] = '45'
        record[291:308] = vin
        record[375:381] = '000000'
        self.assertEqual(audit_pt45_record(''.join(record), 2, vin), [])
        bad = record.copy(); bad[291] = 'X'; bad[375] = '1'; bad[16] = 'X'
        errors = audit_pt45_record(''.join(bad), 2, vin)
        self.assertTrue(any('292–308' in e for e in errors))
        self.assertTrue(any('376–381' in e for e in errors))
        self.assertTrue(any('17–114' in e for e in errors))


class TSOutputBlockTests(unittest.TestCase):
    def test_complete_generator_never_writes_or_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'file.txt'
            output.write_text('old output')
            result = ts_plugin.Plugin(None).generate_complete_file([{'vin': 'ABCDEFGH123456789'}], output_path=output)
            self.assertFalse(result.success)
            self.assertIn('spärrad', result.errors[0])
            self.assertEqual(output.read_text(), 'old output')

    def test_builder_rejects_fallback_and_existing_unverified_schema(self):
        builder = RecordBuilder()
        with patch.object(builder, '_get_schema', return_value=object()):
            for result in (builder.build_identity_post(), builder.build_vehicle_post(2, {'vin': 'ABCDEFGH123456789'}), builder.build_end_post(3, 3)):
                self.assertFalse(result.success)
                self.assertEqual(result.record, '')
                self.assertIn('spärrad', result.errors[0])
            records, errors, _ = builder.build_file([{'vin': 'ABCDEFGH123456789'}])
            self.assertEqual(records, [])
            self.assertTrue(errors)

    def test_separate_pt45_paths_are_blocked(self):
        pg = registration.PostGenerator(registration.RegistrationConfig(), None)
        posts, errors = pg.generate_posts([{'dispatch': {}, 'sap': {}}])
        self.assertEqual(posts, [])
        self.assertIn('spärrad', errors[0]['error'])
        result = pg.generate_posts_from_matched([{'_vin': 'ABCDEFGH123456789'}])
        self.assertFalse(result['success'])
        plugin = registration.Plugin.__new__(registration.Plugin)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'file.txt'
            target.write_text('untouched')
            with self.assertRaisesRegex(ValueError, 'spärrad'):
                plugin._save_posts(target, ['invalid'])
            self.assertEqual(target.read_text(), 'untouched')
            self.assertFalse(plugin.generate_posts(Path('no-excel.xlsx'), target)['success'])

    def test_pt28_and_pt99_public_apis_are_blocked(self):
        self.assertFalse(identity.Plugin.__new__(identity.Plugin).generate_post()['success'])
        self.assertFalse(end.Plugin.__new__(end.Plugin).generate_post(3)['success'])

    def test_mapping_fallback_never_produces_a_file(self):
        tree = ast.parse(Path('plugins/data_mapping/plugin.py').read_text())
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'Plugin')
        method = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == 'generate_ts_file')
        mod = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), ast.ClassDef(name='Isolated', bases=[], keywords=[], body=[method], decorator_list=[])], type_ignores=[]))
        class Result:
            def __init__(self, success, errors): self.success, self.errors = success, errors
            def to_dict(self): return {'success': self.success, 'errors': self.errors}
        env = {'GenerateResult': Result}
        exec(compile(mod, '<mapping>', 'exec'), env)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'ts.txt'
            result = env['Isolated']().generate_ts_file([{'VIN': 'x'}], str(target))
            self.assertFalse(result['success'])
            self.assertFalse(target.exists())

    def test_active_schema_does_not_show_ts_generation_as_ready(self):
        tree = ast.parse(Path('plugins/main_gui/plugin.py').read_text())
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and any(isinstance(m, ast.FunctionDef) and m.name == '_update_schema_status' for m in x.body))
        method = next(m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name == '_update_schema_status')
        mod = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), ast.ClassDef(name='Isolated', bases=[], keywords=[], body=[method], decorator_list=[])], type_ignores=[]))
        timer = SimpleNamespace(singleShot=lambda *args: None)
        # Statusfärgerna hämtas från designsystemet, som därför behövs här.
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from core import theme as _design
        env = {'get_schema_info_safe': lambda app: SimpleNamespace(is_active=True, version='test', post_types=['45'], post_count=1), 'QTimer': timer, 'STATS_UPDATE_INTERVAL_MS': 30000, 'design': _design,
               # Energisparläget räknar nästa intervall via runtime_policy.
               'runtime_policy': __import__('core.runtime_policy', fromlist=['runtime_policy'])}
        exec(compile(mod, '<status>', 'exec'), env)
        from unittest.mock import Mock
        ui = env['Isolated'](); ui.app = None
        ui.schema_status = SimpleNamespace(setText=Mock(), setStyleSheet=Mock())
        # Nästa intervall räknas av energisparläget; här räcker standardvärdet.
        ui._next_interval = lambda base: base
        ui._update_schema_status()
        self.assertIn('spärrad', ui.schema_status.setText.call_args.args[0])

    def test_short_or_invalid_post_is_not_padded_or_written(self):
        plugin = ts_plugin.Plugin(None)
        plugin._generate_identity_post = lambda *a: 'too short'
        with tempfile.TemporaryDirectory() as folder, patch.object(ts_plugin, 'generation_block_reason', return_value=None):
            target = Path(folder) / 'existing.txt'
            target.write_text('original')
            result = plugin.generate_complete_file([{'vin': 'x'}], output_path=target, include_pt45=False, include_pt99=False)
            self.assertFalse(result.success)
            self.assertEqual(target.read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
