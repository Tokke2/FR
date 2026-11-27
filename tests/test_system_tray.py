from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from core import runtime_policy
from plugins.auto_update import plugin as update_plugin


def index_of(menu, action):
    """Systemfältet kan innehålla både (text, callback)-poster och riktiga QAction-objekt."""
    for position, entry in enumerate(menu.entries):
        if entry is action:
            return position
    raise AssertionError('Åtgärden finns inte i systemfältets meny')


def main_window_methods(names, env, base=None):
    path = Path('plugins/main_gui/plugin.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    original = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'MainWindow')
    methods = [n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(methods) == len(names)
    if base is not None:
        env['Base'] = base
    cls = ast.ClassDef(name='Window', bases=[ast.Name(id='Base', ctx=ast.Load())] if base else [],
                       keywords=[], body=methods, decorator_list=[])
    mod = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[]))
    exec(compile(mod, str(path), 'exec'), env)
    return env['Window']


class SignalStub:
    def __init__(self): self.callbacks = []
    def connect(self, callback): self.callbacks.append(callback)
    def emit(self, *args):
        for callback in self.callbacks: callback(*args)


class MenuStub:
    def __init__(self, parent=None): self.entries = []
    def addAction(self, *args): self.entries.append(args); return args
    def addSeparator(self):
        sep = object(); self.entries.append(sep); return sep
    def insertAction(self, before, action): self.entries.insert(self.entries.index(before), action)


class TrayStub:
    available = True
    instances = []
    ActivationReason = SimpleNamespace(DoubleClick='double', Trigger='single')
    @staticmethod
    def isSystemTrayAvailable(): return TrayStub.available
    def __init__(self, icon, parent):
        self.icon, self.parent = icon, parent
        self.activated = SignalStub(); self.messageClicked = SignalStub(); self._visible = False
        self.showMessage = Mock()
        self.MessageIcon = SimpleNamespace(Information='info')
        self.show = Mock(side_effect=lambda: setattr(self, '_visible', True))
        self.hide = Mock(side_effect=lambda: setattr(self, '_visible', False))
        self.__class__.instances.append(self)
    def isVisible(self): return self._visible
    def setContextMenu(self, menu): self.menu = menu
    def setToolTip(self, text): self.tooltip = text


class TimerStub:
    pending = []
    def __init__(self, parent=None): self.timeout = SignalStub(); self.start = Mock()
    @staticmethod
    def singleShot(delay, callback): TimerStub.pending.append(callback)


class IconStub:
    def __init__(self, *args, null=False): self.null = null; self.args = args
    def isNull(self): return self.null


class FakeAction:
    def __init__(self, label, parent):
        self.label = label; self.parent = parent; self.triggered = SignalStub()
        self.toggled = SignalStub(); self.enabled = True
    def setToolTip(self, text): pass
    def setCheckable(self, value): pass
    def setChecked(self, value): pass
    def setEnabled(self, value): self.enabled = value
    def trigger(self):
        if self.enabled: self.triggered.emit()


def qt_stubs():
    core = ModuleType('PySide6.QtCore'); gui = ModuleType('PySide6.QtGui'); widgets = ModuleType('PySide6.QtWidgets')
    core.QObject = type('QObject', (), {'__init__': lambda self, parent: None})
    core.QTimer = SimpleNamespace(singleShot=Mock())
    core.Qt = SimpleNamespace(ToolButtonStyle=SimpleNamespace(ToolButtonTextOnly=1))
    core.Signal = lambda *args: SignalStub()
    core.Slot = lambda *args: lambda func: func
    gui.QIcon = IconStub; gui.QAction = FakeAction
    widgets.QSystemTrayIcon = TrayStub
    package = ModuleType('PySide6'); package.QtCore = core; package.QtGui = gui; package.QtWidgets = widgets
    return {'PySide6': package, 'PySide6.QtCore': core, 'PySide6.QtGui': gui, 'PySide6.QtWidgets': widgets}


class SystemTrayTests(unittest.TestCase):
    def setUp(self):
        TrayStub.available = True; TrayStub.instances.clear(); TimerStub.pending.clear()
        self.qt = qt_stubs()

    def make_window(self, icon=None):
        app_instance = SimpleNamespace(quit=Mock())
        app = SimpleNamespace(windowIcon=lambda: icon or IconStub(), instance=lambda: app_instance)
        env = {'QApplication': app, 'QMenu': MenuStub, 'QTimer': TimerStub, 'Path': Path,
               '__file__': str(Path('plugins/main_gui/plugin.py').resolve()), '_log': Mock(),
               'get_plugin_safe': lambda app, name: None,
               # Bakgrundsläget räknar intervall med runtime_policy (energisparläge).
               'runtime_policy': runtime_policy}
        methods = {'_setup_system_tray', '_show_from_tray', '_tray_activated', 'add_update_tray_action',
                   '_watched_message_clicked',
                   '_quit_application', '_can_hide_to_tray', '_check_tray_available', '_hide_if_still_minimized',
                   # Avslutet ber uppdateringen starta om appen när en
                   # uppdatering väntar.
                   '_restart_after_update'}
        cls = main_window_methods(methods, env)
        window = cls(); window._tray_icon = window._tray_menu = window._tray_separator = None
        # Snabbåtgärderna i systemfältet anropar fönstrets metoder.
        for name in ('_show_global_search', '_import_file_dialog', '_show_dashboard', '_show_error_log'):
            setattr(window, name, Mock())
        window._quit_requested = False; window.app_instance = app_instance
        window.close = Mock(return_value=True); window.show = Mock(); window.showNormal = Mock()
        window.hide = Mock(); window.showMinimized = Mock(); window.isVisible = Mock(return_value=True)
        window.isMinimized = Mock(return_value=True); window.raise_ = Mock(); window.activateWindow = Mock()
        return window

    def test_tray_action_uses_same_updater_action_and_restores_window(self):
        window = self.make_window()
        with patch.dict(sys.modules, self.qt):
            window._setup_system_tray()
            self.assertEqual(len(TrayStub.instances), 1)
            tray = TrayStub.instances[0]; tray.show.assert_called_once()
            self.assertEqual(tray.tooltip, 'Fordonsreg')
            self.assertEqual(tray.menu.entries[0][0], 'Öppna Fordonsreg')
            self.assertEqual(tray.menu.entries[-1][0], 'Avsluta Fordonsreg')
            plugin = update_plugin.Plugin(SimpleNamespace())
            plugin._window = window
            action = FakeAction('Sök efter uppdateringar', window)
            action.triggered.connect(plugin._start_manual_check)
            plugin._update_action = action
            self.assertTrue(window.add_update_tray_action(action))
            # Snabbåtgärderna ligger mellan "Öppna" och uppdateringsvalet.
            labels = [entry[0] if isinstance(entry, tuple) else entry for entry in tray.menu.entries]
            self.assertIn('🔎 Sök (Ctrl+K)', labels)
            self.assertIn('📥 Ny import...', labels)
            self.assertIs(tray.menu.entries[index_of(tray.menu, action)], action)
            with patch.object(update_plugin.threading, 'Thread') as thread:
                action.trigger()
                window.showNormal.assert_called_once()
                window.raise_.assert_called_once(); window.activateWindow.assert_called_once()
                self.assertFalse(action.enabled)
                self.assertEqual(thread.call_args.kwargs['kwargs'], {'interactive': True})
                thread.return_value.start.assert_called_once()
                action.trigger()  # Samma QAction är inaktiverad i alla menyer.
                thread.return_value.start.assert_called_once()
            tray.activated.emit('double')
            self.assertEqual(window.showNormal.call_count, 2)

    def test_updater_installs_the_same_action_in_toolbar_menu_and_tray(self):
        window = self.make_window()
        menubar_menu = MenuStub()
        toolbar = SimpleNamespace(setObjectName=Mock(), setMovable=Mock(),
                                  setToolButtonStyle=Mock(), addAction=Mock())
        window.menuBar = lambda: SimpleNamespace(addMenu=lambda text: menubar_menu)
        window.addToolBar = lambda text: toolbar
        self.qt['PySide6.QtWidgets'].QMainWindow = type(window)
        self.qt['PySide6.QtWidgets'].QApplication = SimpleNamespace(topLevelWidgets=lambda: [window])
        plugin = update_plugin.Plugin(SimpleNamespace())
        plugin.autostart = SimpleNamespace(is_enabled=lambda: False)
        with patch.dict(sys.modules, self.qt):
            window._setup_system_tray()
            plugin._install_menu(0)
            labels = [entry[0] if isinstance(entry, tuple) else entry
                      for entry in window._tray_menu.entries]
            self.assertIn('🔎 Sök (Ctrl+K)', labels)
            update_index = index_of(window._tray_menu, plugin._update_action)
            self.assertIs(window._tray_menu.entries[update_index], plugin._update_action)
            toolbar.addAction.assert_called_once_with(plugin._update_action)
            self.assertIs(menubar_menu.entries[0][0], plugin._update_action)
            with patch.object(update_plugin.threading, 'Thread') as thread:
                window._tray_menu.entries[update_index].trigger()
                thread.return_value.start.assert_called_once()
                self.assertEqual(thread.call_args.kwargs['target'], plugin._check_for_updates)

    def test_tray_unavailable_is_nonfatal(self):
        TrayStub.available = False
        window = self.make_window()
        with patch.dict(sys.modules, self.qt): window._setup_system_tray()
        self.assertIsNone(window._tray_icon)
        self.assertFalse(window.add_update_tray_action(object()))

    def test_fallback_uses_fordonsreg_icon_if_application_icon_is_empty(self):
        window = self.make_window(icon=IconStub(null=True))
        with patch.dict(sys.modules, self.qt): window._setup_system_tray()
        self.assertTrue(str(TrayStub.instances[0].icon.args[0]).endswith('ikon_256.png'))

    def test_close_to_tray_does_not_quit_or_discard_unsaved_work(self):
        class Base:
            def closeEvent(self, event): event.accepted = True
        env = {}
        cls = main_window_methods({'closeEvent'}, env, Base)
        window = cls(); window._quit_requested = False; window._can_hide_to_tray = lambda: True
        window._tray_icon = SimpleNamespace(hide=Mock()); window.hide = Mock()
        window.vehicle_data_page = SimpleNamespace(confirm_close=Mock(return_value=False))
        event = SimpleNamespace(ignore=Mock(), isAccepted=lambda: False)
        window.closeEvent(event)
        event.ignore.assert_called_once(); window.hide.assert_called_once()
        window.vehicle_data_page.confirm_close.assert_not_called()
        window._tray_icon.hide.assert_not_called()

    def test_real_exit_checks_unsaved_and_cancel_keeps_tray(self):
        class Base:
            def closeEvent(self, event): event.accepted = True
        cls = main_window_methods({'closeEvent'}, {}, Base)
        window = cls(); window._quit_requested = True; window._can_hide_to_tray = lambda: True
        window._tray_icon = SimpleNamespace(hide=Mock())
        window.vehicle_data_page = SimpleNamespace(confirm_close=Mock(return_value=False))
        event = SimpleNamespace(ignore=Mock(), accepted=False, isAccepted=lambda: event.accepted)
        window.closeEvent(event)
        event.ignore.assert_called_once(); window._tray_icon.hide.assert_not_called()
        window.vehicle_data_page.confirm_close.return_value = True
        window.closeEvent(event)
        window._tray_icon.hide.assert_called_once(); self.assertTrue(event.accepted)

    def test_explicit_exit_quits_and_cancellation_resets_flag(self):
        window = self.make_window()
        with patch.dict(sys.modules, self.qt):
            window._setup_system_tray()
            window.close.return_value = False
            window._quit_application()
            self.assertFalse(window._quit_requested)
            window.app_instance.quit.assert_not_called()
            window.close.return_value = True
            window._quit_application()
            self.assertTrue(window._quit_requested)
            window.app_instance.quit.assert_called_once()
            self.assertEqual(window._tray_menu.entries[-1][1], window._quit_application)

    def test_close_without_tray_really_closes_and_checks_changes(self):
        class Base:
            def closeEvent(self, event): event.accepted = True
        cls = main_window_methods({'closeEvent'}, {}, Base)
        window = cls(); window._quit_requested = False; window._can_hide_to_tray = lambda: False
        window._tray_icon = None
        window.vehicle_data_page = SimpleNamespace(confirm_close=Mock(return_value=True))
        event = SimpleNamespace(ignore=Mock(), accepted=False, isAccepted=lambda: event.accepted)
        window.closeEvent(event)
        window.vehicle_data_page.confirm_close.assert_called_once()
        self.assertTrue(event.accepted); event.ignore.assert_not_called()

    def test_deactivation_is_real_close_and_cancel_keeps_events(self):
        tree = ast.parse(Path('plugins/main_gui/plugin.py').read_text(encoding='utf-8'))
        source = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'Plugin')
        method = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'deactivate')
        cls = ast.ClassDef(name='P', bases=[], keywords=[], body=[method], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
        unsub = Mock(); env = {'unsubscribe_event_safe': unsub, '_log': Mock()}
        exec(compile(module, '<deactivate-test>', 'exec'), env)
        plugin = env['P'](); plugin.NAME = 'main_gui'; plugin.app = object(); plugin.is_active = True
        plugin._event_handlers = [('event', object())]
        window = SimpleNamespace(_quit_requested=False, isVisible=Mock(return_value=False),
                                 isMinimized=Mock(return_value=True), _show_from_tray=Mock(),
                                 close=Mock(return_value=False))
        plugin._main_window = window
        plugin.deactivate()
        self.assertFalse(window._quit_requested); self.assertTrue(plugin.is_active)
        self.assertEqual(len(plugin._event_handlers), 1); unsub.assert_not_called()
        window._show_from_tray.assert_called_once()
        window.close.return_value = True
        plugin.deactivate()
        self.assertFalse(plugin.is_active); self.assertIsNone(plugin._main_window)
        unsub.assert_called_once()

    def test_minimize_restoration_and_tray_loss(self):
        window = self.make_window()
        with patch.dict(sys.modules, self.qt):
            window._setup_system_tray()
            window._hide_if_still_minimized()
            window.hide.assert_called_once()
            window.isMinimized.return_value = False
            window._hide_if_still_minimized()  # fokusåterställning vann kapplöpningen
            window.hide.assert_called_once()
            window.isVisible.return_value = False
            TrayStub.available = False
            window._check_tray_available()
            window.showMinimized.assert_called_once()
            window.isMinimized.return_value = True
            window._hide_if_still_minimized()
            window.hide.assert_called_once()

    def test_minimize_event_schedules_hide_and_single_click_opens(self):
        class Base:
            def changeEvent(self, event): pass
        cls = main_window_methods({'changeEvent'}, {'QTimer': TimerStub, 'Qt': SimpleNamespace(WindowState=SimpleNamespace(WindowMaximized=2))}, Base)
        subject = cls(); subject._quit_requested = False; subject.isMinimized = Mock(return_value=True)
        subject._hide_if_still_minimized = Mock()
        self.qt['PySide6.QtCore'].QEvent = SimpleNamespace(Type=SimpleNamespace(WindowStateChange=1))
        event = SimpleNamespace(type=lambda: 1, oldState=lambda: 2)
        with patch.dict(sys.modules, self.qt):
            subject.changeEvent(event)
            self.assertTrue(subject._restore_maximized)
            self.assertEqual(len(TimerStub.pending), 1)
            TimerStub.pending[0](); subject._hide_if_still_minimized.assert_called_once()
            window = self.make_window(); window._setup_system_tray()
            window._tray_activated('single')
            window.showNormal.assert_called_once()
            window._restore_maximized = True
            window.showMaximized = Mock()
            window._show_from_tray()
            window.showMaximized.assert_called_once()


if __name__ == '__main__':
    unittest.main()
