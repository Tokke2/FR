from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace, ModuleType
import sys
import unittest
from unittest.mock import Mock, patch


def extracted(path, class_name, name, env):
    tree = ast.parse(Path(path).read_text(encoding='utf-8-sig'))
    if class_name:
        parent = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == class_name)
        node = next(c for c in parent.body if isinstance(c, ast.FunctionDef) and c.name == name)
        body = [ast.ClassDef(name='Subject', bases=[], keywords=[], body=[node], decorator_list=[])]
    else:
        node = next(c for c in tree.body if isinstance(c, ast.FunctionDef) and c.name == name)
        body = [node]
    module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *body], type_ignores=[]))
    exec(compile(module, '<gui-contract>', 'exec'), env)
    return env['Subject'] if class_name else env[name]


class PinGuiContracts(unittest.TestCase):
    def test_vehicle_unlock_respects_shared_pin_callback(self):
        state = SimpleNamespace(UNLOCKED='unlocked')
        cls = extracted('plugins/main_gui/vehicle_registry_page.py', 'VehicleDataPage', '_unlock', {'LockState': state})
        subject = cls(); subject._update_lock_state = Mock(); subject._autolock_timer = SimpleNamespace(start=Mock())
        subject._pin_getter = Mock(return_value=None)
        subject._unlock()
        subject._update_lock_state.assert_not_called()
        subject._autolock_timer.start.assert_not_called()
        subject._pin_getter.return_value = '123456'
        subject._unlock()
        self.assertEqual(subject._lock_state, 'unlocked')
        subject._update_lock_state.assert_called_once()
        subject._autolock_timer.start.assert_called_once()

    def test_sap_editor_cancellation_and_success_use_transition(self):
        dealer, auth = object(), object()
        app = SimpleNamespace(dealers=dealer, auth=auth)
        editor = Mock(); editor.exec.return_value = 1
        env = {'_coerce_parent': lambda parent: parent, '_get_plugin_safe': lambda app, name: {'core_auth': auth, 'dealers_manager': dealer}[name],
               'QMessageBox': SimpleNamespace(critical=Mock()), 'SapEditorWindow': Mock(return_value=editor),
               'QDialog': SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
               '_verify_password': lambda a, p: p == 'old', '_log': SimpleNamespace(info=Mock())}
        show = extracted('plugins/sap_editor/ui/editor_window.py', None, 'show_sap_editor', env)
        dialog = ModuleType('plugins.main_gui.dialogs.dealer_pin'); dialog.request_migrated_pin = Mock(return_value=None)
        with patch.dict(sys.modules, {'plugins.main_gui.dialogs.dealer_pin': dialog}):
            self.assertFalse(show(None, app, {}))
            env['SapEditorWindow'].assert_not_called()
            dialog.request_migrated_pin.return_value = '123456'
            self.assertTrue(show(None, app, {}))
            self.assertEqual(dialog.request_migrated_pin.call_args.args[2], 'sap_editor')
            env['SapEditorWindow'].assert_called_once()


if __name__ == '__main__':
    unittest.main()
