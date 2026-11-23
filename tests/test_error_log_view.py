from __future__ import annotations

import ast
import logging
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.error_log_view import current_summary_path, read_log_tail
from core.error_summary import ErrorSummaryHandler, _append

ROOT = Path(__file__).resolve().parents[1]


def isolated_methods(path: Path, class_name: str, names: set[str], env: dict):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    original = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    methods = [node for node in original.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(methods) == len(names)
    cls = ast.ClassDef(name='Isolated', bases=[], keywords=[], body=methods, decorator_list=[])
    mod = ast.fix_missing_locations(ast.Module(body=[
        ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls,
    ], type_ignores=[]))
    exec(compile(mod, str(path), 'exec'), env)
    return env['Isolated']


class FakeViewer:
    def __init__(self): self.text = ''
    def clear(self): self.text = ''
    def setPlainText(self, text): self.text = text
    def toPlainText(self): return self.text


class ErrorLogViewTests(unittest.TestCase):
    def test_reads_current_and_previous_log_without_modifying_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _append(folder, 'första felet', max_bytes=20, backups=3)
            _append(folder, 'andra felet', max_bytes=20, backups=3)
            current = folder / 'felsokning.log'
            rotated = folder / 'felsokning.log.1'
            before = (current.read_bytes(), rotated.read_bytes())
            self.assertEqual(read_log_tail(current), ('andra felet\n', False))
            self.assertEqual(read_log_tail(rotated), ('första felet\n', False))
            self.assertEqual(before, (current.read_bytes(), rotated.read_bytes()))

    def test_tail_is_bounded_and_handles_split_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'felsokning.log'
            path.write_text('FIRST ' + ('å' * 30) + ' LAST', encoding='utf-8')
            text, truncated = read_log_tail(path, max_bytes=12)
            self.assertTrue(truncated)
            self.assertTrue(text.endswith(' LAST'))
            self.assertNotIn('FIRST', text)
            with self.assertRaises(ValueError): read_log_tail(path, 0)

    def test_missing_and_symlink_files_are_not_created_or_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); path = folder / 'felsokning.log'
            with self.assertRaises(FileNotFoundError): read_log_tail(path)
            self.assertFalse(path.exists())
            target = folder / 'private.txt'; target.write_text('secret')
            try:
                path.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest('Symboliska länkar är inte tillgängliga')
            with self.assertRaises(OSError): read_log_tail(path)
            self.assertEqual(target.read_text(), 'secret')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO stöds inte')
    def test_non_regular_file_does_not_block_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'felsokning.log'; os.mkfifo(path)
            with self.assertRaises(OSError): read_log_tail(path)

    def test_uses_the_active_log_handler_not_a_guessed_root_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = logging.getLogger(); handler = ErrorSummaryHandler(Path(tmp), 'app')
            root.addHandler(handler)
            try:
                self.assertEqual(current_summary_path(), Path(tmp) / 'felsokning.log')
            finally:
                root.removeHandler(handler); handler.close()

    def test_missing_handler_is_not_replaced_with_a_guessed_log_path(self):
        root = SimpleNamespace(handlers=[])
        with patch('core.error_log_view.logging.getLogger', return_value=root):
            with self.assertRaisesRegex(RuntimeError, 'Ingen aktiv felsökningslogg'):
                current_summary_path()

    def test_view_reload_switches_files_and_handles_absent_or_unreadable_logs(self):
        clipboard = Mock()
        env = {'Path': Path, 'BACKUPS': 3, 'MAX_DISPLAY_BYTES': 2 * 1024 * 1024,
               'read_log_tail': read_log_tail,
               'QApplication': SimpleNamespace(clipboard=lambda: clipboard)}
        cls = isolated_methods(ROOT / 'plugins/main_gui/dialogs/error_log_dialog.py', 'ErrorLogDialog',
                               {'_selected_path', '_reload', '_copy_text'}, env)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'felsokning.log'
            path.write_text('Felet inträffade\n', encoding='utf-8')
            path.with_name(path.name + '.1').write_text('Äldre fel\n', encoding='utf-8')
            selected = [0]
            dialog = cls(); dialog._log_path = path
            dialog._files = SimpleNamespace(currentData=lambda: selected[0])
            dialog._path_label = SimpleNamespace(setText=Mock())
            dialog._status = SimpleNamespace(setText=Mock())
            dialog._copy = SimpleNamespace(setEnabled=Mock())
            dialog._viewer = FakeViewer()
            dialog._reload()
            self.assertEqual(dialog._viewer.text, 'Felet inträffade\n')
            dialog._copy_text(); clipboard.setText.assert_called_once_with('Felet inträffade\n')
            selected[0] = 1; dialog._reload()
            self.assertEqual(dialog._viewer.text, 'Äldre fel\n')
            path.with_name('felkoder.json').write_text('{"status": "aktiv"}', encoding='utf-8')
            selected[0] = -1; dialog._reload()
            self.assertIn('aktiv', dialog._viewer.text)
            self.assertEqual(dialog._path_label.setText.call_args.args[0], str(path.with_name('felkoder.json')))
            selected[0] = 2; dialog._reload()
            self.assertEqual(dialog._viewer.text, '')
            self.assertIn('finns inte', dialog._status.setText.call_args.args[0])
            with patch.dict(env, {'read_log_tail': Mock(side_effect=PermissionError('nekad'))}):
                dialog._reload()
            self.assertIn('nekad', dialog._status.setText.call_args.args[0])
            dialog._copy.setEnabled.assert_called_with(False)
            with patch.dict(env, {'read_log_tail': Mock(return_value=('senaste fel', True))}):
                dialog._reload()
            self.assertEqual(dialog._viewer.text, 'senaste fel')
            self.assertIn('senaste 2 MB', dialog._status.setText.call_args.args[0])

    def test_menu_action_opens_reusable_nonmodal_dialog(self):
        env = {'QMenuBar': object, '_log': Mock(), 'QMessageBox': SimpleNamespace(warning=Mock())}
        cls = isolated_methods(ROOT / 'plugins/main_gui/plugin.py', 'MainWindow',
                               {'_create_tools_menu', '_show_error_log'}, env)
        page = cls(); page._error_log_dialog = None
        page._validate_vin_dialog = page._show_statistics = page._refresh_cache = page._rebuild_index = Mock()
        page._show_learning_info = page._toggle_learning = page._clear_learning = Mock()
        page._show_global_search = page._show_dashboard = page._show_watched_folder = Mock()
        page._show_ts_verification = page._show_error_guide = Mock()
        menu = SimpleNamespace(addAction=Mock(), addSeparator=Mock())
        menubar = SimpleNamespace(addMenu=Mock(return_value=menu))
        page._create_tools_menu(menubar)
        actions = menu.addAction.call_args_list
        entry = next(call for call in actions if 'felsökningslogg' in call.args[0])
        dialog = Mock()
        module = ModuleType('plugins.main_gui.dialogs.error_log_dialog')
        module.ErrorLogDialog = Mock(return_value=dialog)
        with patch.dict(sys.modules, {'plugins.main_gui.dialogs.error_log_dialog': module}):
            entry.args[1]()
            page._show_error_log()
        module.ErrorLogDialog.assert_called_once_with(page)
        self.assertEqual(dialog.show.call_count, 2)
        self.assertEqual(dialog.reload.call_count, 2)
        dialog.exec.assert_not_called()


if __name__ == '__main__':
    unittest.main()
