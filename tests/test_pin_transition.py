from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from core.dealer_pin import DealerPin, PinError
from core.pin_transition import PinTransitions, sap_legacy_identity
from plugins.vehicle_registry.excel_importer import ExcelModelImporter


class PinTransitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pin = DealerPin(self.root / 'pin.json'); self.pin.create('123456')
        self.store = PinTransitions(self.pin)

    def test_requires_both_and_identity_remains_bound(self):
        identity = ['old']
        def migrate(shared, old):
            self.store.migrate('fordon', identity[0], shared, old,
                               legacy_verify=lambda v: v == identity[0], identity_now=lambda: identity[0])
        with self.assertRaises(PinError): migrate('wrong', 'old')
        with self.assertRaises(PinError): migrate('123456', 'wrong')
        self.assertFalse(self.store.path.exists())
        migrate('123456', 'old')
        self.assertTrue(self.store.migrated('fordon', 'old'))
        self.assertFalse(self.store.migrated('fordon', 'changed'))
        self.pin.change('123456', '654321')
        self.assertTrue(self.store.migrated('fordon', 'old'))
        self.assertFalse(self.pin.verify('123456'))
        self.assertTrue(self.pin.verify('654321'))
        self.assertNotIn('old', self.store.path.read_text())

    def test_legacy_pin_metadata_is_upgraded_only_after_authentication(self):
        data = json.loads(self.pin.path.read_text()); data.pop('pin_id'); data['unknown'] = 'keep'
        self.pin.path.write_text(json.dumps(data))
        before = self.pin.path.read_bytes()
        with self.assertRaises(PinError): self.pin.ensure_identity('bad')
        self.assertEqual(self.pin.path.read_bytes(), before)
        identity = self.pin.ensure_identity('123456')
        self.assertEqual(self.pin.identity(), identity)
        self.assertEqual(json.loads(self.pin.path.read_text())['unknown'], 'keep')
        self.assertTrue(any(p.read_bytes() == before for p in (self.root / 'backup_pin').iterdir()))
        self.pin.change('123456', '654321')
        self.assertEqual(self.pin.identity(), identity)

    def test_recreated_pin_file_does_not_inherit_transitions(self):
        self.store.migrate('fordon', 'old', '123456', 'old',
                           legacy_verify=lambda v: v == 'old', identity_now=lambda: 'old')
        self.assertTrue(self.store.migrated('fordon', 'old'))
        self.pin.path.unlink()
        self.pin.create('654321')
        self.assertFalse(self.store.migrated('fordon', 'old'))

    def test_corrupt_migration_data_is_never_reset(self):
        self.store.path.write_text('broken')
        with self.assertRaises(ValueError): self.store.migrated('test', 'x')
        with self.assertRaises(ValueError):
            self.store.migrate('test', 'x', '123456', 'x', legacy_verify=lambda p: True, identity_now=lambda: 'x')
        self.assertEqual(self.store.path.read_text(), 'broken')

    def test_sap_identity_tracks_existing_file(self):
        path = self.root / 'auth.json'
        path.write_text('{"password_hash":"abc"}')
        auth = Mock(_initialized=True, _password_path=path, _password_config={'password_hash': 'abc'})
        before = sap_legacy_identity(auth)
        path.write_text('{"password_hash":"def"}')
        with self.assertRaises(PinError): sap_legacy_identity(auth)
        auth._password_config['password_hash'] = 'def'
        self.assertNotEqual(before, sap_legacy_identity(auth))
        path.write_text('broken')
        with self.assertRaises(PinError): sap_legacy_identity(auth)

    def test_mapping_needs_both_old_and_shared_then_survives_rotation(self):
        directory = self.root / 'json' / 'mappings'
        legacy = ExcelModelImporter(Mock(), directory)
        legacy.set_column_mapping({'VIN': 'vin_kod'}, fingerprint='abc', pin='1234', protected=True)
        path = directory / 'vehicle_import_mapping.json'
        data = json.loads(path.read_text()); data['mappings']['abc']['extra'] = 'keep'; path.write_text(json.dumps(data))
        original = path.read_bytes()
        new = ExcelModelImporter(Mock(), directory, pin_provider=lambda: self.pin)
        with self.assertRaises(PermissionError):
            new.set_column_mapping({'VIN': 'typ'}, fingerprint='abc', pin='1234', protected=True)
        self.assertEqual(path.read_bytes(), original)
        identity = new.mapping_legacy_identity('abc')
        with self.assertRaises(PinError):
            self.store.migrate('mapping:abc', identity, '123456', 'bad',
                               legacy_verify=lambda value: new.verify_legacy_mapping_pin('abc', value),
                               identity_now=lambda: new.mapping_legacy_identity('abc'))
        self.store.migrate('mapping:abc', identity, '123456', '1234',
                           legacy_verify=lambda value: new.verify_legacy_mapping_pin('abc', value),
                           identity_now=lambda: new.mapping_legacy_identity('abc'))
        new.set_column_mapping({'VIN': 'typ'}, fingerprint='abc', pin='123456', protected=False)
        entry = json.loads(path.read_text())['mappings']['abc']
        self.assertEqual(entry['extra'], 'keep')
        self.assertEqual(entry['pin_mode'], 'shared')
        self.assertTrue(entry['protected'])
        self.assertEqual(entry['pin_hash'], identity)
        self.assertTrue(any(p.read_bytes() == original for p in (directory / 'backup_mappningar').iterdir()))
        self.pin.change('123456', '654321')
        self.assertFalse(new.verify_mapping_pin('abc', '123456'))
        self.assertTrue(new.verify_mapping_pin('abc', '654321'))
        new.set_column_mapping({'VIN': 'variant'}, fingerprint='abc', pin='654321')
        # En ny PIN-fil får inte automatiskt ärva det gamla skyddet.
        self.pin.path.unlink(); self.pin.create('777777')
        self.assertFalse(new.verify_mapping_pin('abc', '777777'))
        with self.assertRaises(PermissionError):
            new.set_column_mapping({'VIN': 'typ'}, fingerprint='abc', pin='777777')

    def test_new_protected_mapping_only_accepts_shared_pin(self):
        importer = ExcelModelImporter(Mock(), self.root / 'mappings', pin_provider=lambda: self.pin)
        with self.assertRaises(PermissionError):
            importer.set_column_mapping({'VIN': 'typ'}, fingerprint='new', pin='1234', protected=True)
        importer.set_column_mapping({'VIN': 'typ'}, fingerprint='new', pin='123456', protected=True)
        self.assertTrue(importer.verify_mapping_pin('new', '123456'))
        self.assertFalse(importer.verify_mapping_pin('new', '1234'))


if __name__ == '__main__':
    unittest.main()
