from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from datetime import date
import types
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.dealer_pin import DealerPin, PinError

ROOT = Path(__file__).resolve().parents[1]


class DealerPinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'pin.json'
        self.pin = DealerPin(self.path)

    def test_first_setup_and_failed_authentication(self):
        self.assertFalse(self.pin.configured())
        self.assertFalse(self.pin.verify('123456'))
        for invalid in ('1234', '１２３４５６', 'abcdef', '1234567890123'):
            with self.assertRaises(PinError): self.pin.create(invalid)
        self.assertFalse(self.path.exists())
        self.pin.create('123456')
        self.assertTrue(self.pin.configured())
        self.assertTrue(self.pin.verify('123456'))
        self.assertFalse(self.pin.verify('654321'))
        self.assertFalse(self.pin.verify(None))
        self.assertNotIn('123456', self.path.read_text())
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError): self.pin.create('654321')
        self.assertEqual(self.path.read_bytes(), before)

    def test_change_requires_current_pin_and_is_atomic(self):
        self.pin.create('123456'); before = self.path.read_bytes()
        with self.assertRaises(PinError): self.pin.change('000000', '654321')
        with self.assertRaises(PinError): self.pin.change('123456', 'x')
        self.assertEqual(self.path.read_bytes(), before)
        self.pin.change('123456', '654321')
        self.assertFalse(self.pin.verify('123456'))
        self.assertTrue(self.pin.verify('654321'))

    def test_monthly_reminder_calendar_snooze_and_change(self):
        self.pin.create('123456')
        data = json.loads(self.path.read_text())
        data['changed_on'] = '2026-01-31'
        self.path.write_text(json.dumps(data))
        self.assertFalse(self.pin.reminder_due(date(2026, 2, 27)))
        self.assertTrue(self.pin.reminder_due(date(2026, 2, 28)))
        self.pin.mark_reminded(date(2026, 2, 28))
        self.assertFalse(self.pin.reminder_due(date(2026, 2, 28)))
        self.assertTrue(self.pin.reminder_due(date(2026, 3, 1)))
        with self.assertRaises(PinError): self.pin.change('123456', '123456')
        self.pin.change('123456', '654321')
        self.assertFalse(self.pin.reminder_due(date.today()))

    def test_corruption_is_not_reset_and_symlink_rejected(self):
        for content in (b'', b'{broken', b'\xff', b'{}', json.dumps({'version': 1, 'iterations': 1, 'salt': '', 'hash': ''}).encode()):
            self.path.write_bytes(content)
            with self.assertRaises(PinError): self.pin.configured()
            with self.assertRaises(PinError): self.pin.verify('123456')
            self.assertEqual(self.path.read_bytes(), content)
        self.path.unlink()
        target = self.path.parent / 'other'; target.write_text('secret')
        self.path.symlink_to(target)
        with self.assertRaises(PinError): self.pin.create('123456')
        with self.assertRaises(PinError): self.pin.verify('123456')
        self.assertEqual(target.read_text(), 'secret')


class PinDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.manager = DealerPin(Path(self.temp.name) / 'pin.json')
        self.plugin = SimpleNamespace(dealer_pin=lambda: self.manager)
        widgets = types.ModuleType('PySide6.QtWidgets')
        widgets.QInputDialog = SimpleNamespace(getText=Mock())
        widgets.QLineEdit = SimpleNamespace(EchoMode=SimpleNamespace(Password=1))
        widgets.QMessageBox = SimpleNamespace(
            StandardButton=SimpleNamespace(Yes=1, No=2), question=Mock(return_value=1),
            warning=Mock(), information=Mock())
        package = types.ModuleType('PySide6'); package.__path__ = []
        spec = importlib.util.spec_from_file_location('dealer_pin_dialog_test', ROOT / 'plugins/main_gui/dialogs/dealer_pin.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'PySide6': package, 'PySide6.QtWidgets': widgets}):
            spec.loader.exec_module(self.module)
        self.widgets = widgets

    def test_decline_cancel_mismatch_and_success(self):
        self.widgets.QMessageBox.question.return_value = 2
        self.assertIsNone(self.module.request_pin(None, self.plugin))
        self.assertFalse(self.manager.configured())
        self.widgets.QMessageBox.question.return_value = 1
        self.widgets.QInputDialog.getText.side_effect = [('123456', True), ('654321', True)]
        self.assertIsNone(self.module.request_pin(None, self.plugin))
        self.assertFalse(self.manager.configured())
        self.widgets.QInputDialog.getText.side_effect = [('123456', True), ('123456', True)]
        self.assertEqual(self.module.request_pin(None, self.plugin), '123456')
        self.widgets.QInputDialog.getText.side_effect = [('bad', True), ('', False), ('123456', True)]
        self.assertIsNone(self.module.request_pin(None, self.plugin))
        self.assertIsNone(self.module.request_pin(None, self.plugin))
        self.assertEqual(self.module.request_pin(None, self.plugin), '123456')

    def test_first_transition_requires_old_and_then_uses_shared_pin(self):
        self.manager.create('123456')
        calls = lambda: 'old-identity'
        self.widgets.QInputDialog.getText.side_effect = [('123456', True), ('wrong', True)]
        self.assertIsNone(self.module.request_migrated_pin(None, self.plugin, 'test', calls,
                                                            lambda pin: pin == 'old', 'resursen'))
        self.widgets.QInputDialog.getText.side_effect = [('123456', True), ('old', True)]
        self.assertEqual(self.module.request_migrated_pin(None, self.plugin, 'test', calls,
                                                         lambda pin: pin == 'old', 'resursen'), '123456')
        self.widgets.QInputDialog.getText.side_effect = [('123456', True)]
        self.assertEqual(self.module.request_migrated_pin(None, self.plugin, 'test', calls,
                                                         lambda pin: False, 'resursen'), '123456')
        self.manager.change('123456', '654321')
        self.widgets.QInputDialog.getText.side_effect = [('654321', True)]
        self.assertEqual(self.module.request_migrated_pin(None, self.plugin, 'test', calls,
                                                         lambda pin: False, 'resursen'), '654321')

    def test_change_dialog_old_pin_and_confirmation(self):
        self.manager.create('123456')
        self.widgets.QInputDialog.getText.side_effect = [('000000', True)]
        self.module.change_pin(None, self.plugin)
        self.assertTrue(self.manager.verify('123456'))
        self.widgets.QInputDialog.getText.side_effect = [('123456', True), ('654321', True), ('654321', True)]
        self.module.change_pin(None, self.plugin)
        self.assertTrue(self.manager.verify('654321'))


if __name__ == '__main__':
    unittest.main()
