from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import theme as _design

from core.responsive_layout import fit_columns, flow_positions
from core.dealer_fields import FIELDS


class ResponsiveCalculationsTests(unittest.TestCase):
    def test_columns_expand_to_available_width_without_shrinking_content(self):
        self.assertEqual(fit_columns([40, 30, 30], 205), [75, 65, 65])
        self.assertEqual(fit_columns([40, 30, 30], 80), [40, 30, 30])
        self.assertEqual(fit_columns([40, 30, 30], 101), [41, 30, 30])
        self.assertEqual(fit_columns([], 100), [])
        self.assertEqual(fit_columns([1, 2], 0), [1, 2])

    def test_buttons_wrap_without_overlap_and_height_tracks_width(self):
        sizes = [(80, 30), (90, 32), (70, 30), (85, 30)]
        wide, height_wide = flow_positions(sizes, 400, 8)
        narrow, height_narrow = flow_positions(sizes, 180, 8)
        self.assertEqual(wide, [(0, 0), (88, 0), (186, 0), (264, 0)])
        self.assertEqual(height_wide, 32)
        self.assertEqual(narrow, [(0, 0), (88, 0), (0, 40), (78, 40)])
        self.assertEqual(height_narrow, 70)
        self.assertEqual(flow_positions([], 100), ([], 0))
        # A tiny area does not hide the oversized control; outer scrolling can expose it.
        self.assertEqual(flow_positions([(100, 30)], 10), ([(0, 0)], 30))


class FlowWidgetStubTests(unittest.TestCase):
    def test_widget_layout_wraps_and_honors_margins_and_minimum(self):
        class Size:
            def __init__(self, width=0, height=0): self.w, self.h = width, height
            def width(self): return self.w
            def height(self): return self.h
            def expandedTo(self, other): return Size(max(self.w, other.w), max(self.h, other.h))
            def __add__(self, other): return Size(self.w + other.w, self.h + other.h)
        class Point:
            def __init__(self, x, y): self.x, self.y = x, y
        class Rect:
            def __init__(self, a, b, w=None, h=None):
                if isinstance(a, Point): self._x, self._y, self._w, self._h = a.x, a.y, b.width(), b.height()
                else: self._x, self._y, self._w, self._h = a, b, w, h
            def adjusted(self, left, top, right, bottom):
                return Rect(self._x+left, self._y+top, self._w-left+right, self._h-top+bottom)
            def width(self): return self._w
            def x(self): return self._x
            def y(self): return self._y
        class BaseLayout:
            def __init__(self, parent=None): self.margins = (0, 0, 0, 0)
            def setContentsMargins(self, *m): self.margins = m
            def setSpacing(self, spacing): self.gap = spacing
            def spacing(self): return self.gap
            def invalidate(self): pass
            def setGeometry(self, rect): pass
            def contentsMargins(self):
                l, t, r, b = self.margins
                return SimpleNamespace(left=lambda: l, top=lambda: t, right=lambda: r, bottom=lambda: b)
        class Item:
            def __init__(self, w, h, visible=True): self.size = Size(w, h); self.visible = visible
            def sizeHint(self): return self.size
            def minimumSize(self): return self.size
            def isEmpty(self): return not self.visible
            def setGeometry(self, rect): self.rect = rect
        package = types.ModuleType('PySide6'); package.__path__ = []
        qtcore = types.ModuleType('PySide6.QtCore')
        qtcore.QPoint, qtcore.QRect, qtcore.QSize = Point, Rect, Size
        qtcore.Qt = SimpleNamespace(Orientation=lambda x: x)
        widgets = types.ModuleType('PySide6.QtWidgets'); widgets.QLayout = BaseLayout
        spec = importlib.util.spec_from_file_location('flow_layout_test', 'plugins/main_gui/flow_layout.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'PySide6': package, 'PySide6.QtCore': qtcore, 'PySide6.QtWidgets': widgets}):
            spec.loader.exec_module(module)
        layout = module.FlowLayout(spacing=8)
        items = [Item(80, 30), Item(90, 32), Item(70, 30), Item(10, 10, False)]
        for item in items: layout.addItem(item)
        layout.setContentsMargins(5, 3, 5, 3)
        self.assertTrue(layout.hasHeightForWidth())
        self.assertEqual(layout.heightForWidth(190), 76)
        layout.setGeometry(Rect(0, 0, 190, 100))
        self.assertEqual([(i.rect.x(), i.rect.y()) for i in items[:3]], [(5, 3), (93, 3), (5, 43)])
        self.assertFalse(hasattr(items[-1], 'rect'))
        self.assertEqual(layout.minimumSize().width(), 100)
        self.assertEqual(layout.count(), 4)
        self.assertIs(layout.takeAt(1), items[1])
        self.assertEqual(layout.count(), 3)


class NavigationTests(unittest.TestCase):
    def test_sidebar_scrolls_instead_of_hiding_navigation(self):
        tree = ast.parse(Path('plugins/main_gui/plugin.py').read_text(encoding='utf-8'))
        source = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'MainWindow')
        method = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == '_create_sidebar')
        cls = ast.ClassDef(name='Window', bases=[], keywords=[], body=[method], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[]))
        class Scroll:
            def __init__(self): self.actions = {}
            def setWidgetResizable(self, value): self.actions['resizable'] = value
            def setFrameShape(self, value): self.actions['frame'] = value
            def setHorizontalScrollBarPolicy(self, value): self.actions['horizontal'] = value
            def setVerticalScrollBarPolicy(self, value): self.actions['vertical'] = value
            def setFixedWidth(self, value): self.actions['width'] = value
            def setMinimumWidth(self, value): self.actions['min_width'] = value
            def setMaximumWidth(self, value): self.actions['max_width'] = value
            def setStyleSheet(self, value): pass
            def setObjectName(self, value): self.actions['name'] = value
            def setWidget(self, value): self.child = value
        class Layout:
            def __init__(self, widget=None): self.widget = widget; self.items = []
            def setContentsMargins(self, *args): pass
            def addWidget(self, item, *args): self.items.append(item)
            def addLayout(self, item): self.items.append(item)
            def addSpacing(self, item): pass
        class Label:
            def __init__(self, text=''): self.text = text
            def setObjectName(self, value): self.name = value
            def setStyleSheet(self, value): pass
            def setWordWrap(self, value): pass
            def setPixmap(self, pixmap): pass
            def setToolTip(self, value): pass
        widgets = types.ModuleType('PySide6.QtWidgets')
        widgets.QScrollArea = Scroll; widgets.QFrame = SimpleNamespace(Shape=SimpleNamespace(NoFrame=0))
        package = types.ModuleType('PySide6'); package.__path__ = []
        class Widget:
            def setObjectName(self, value): self.name = value
        env = {'QWidget': Widget, 'QVBoxLayout': Layout, 'QHBoxLayout': Layout, 'QLabel': Label,
               'QApplication': SimpleNamespace(windowIcon=lambda: SimpleNamespace(pixmap=lambda *args: SimpleNamespace(isNull=lambda: False))),
               'Qt': SimpleNamespace(ScrollBarPolicy=SimpleNamespace(ScrollBarAsNeeded=1)),
               'get_config_value_safe': lambda app, key, default: default,
               'design': _design}
        exec(compile(module, '<sidebar-test>', 'exec'), env)
        window = env['Window'](); window.app = object(); window.window_config = SimpleNamespace(sidebar_width=220)
        window.width = lambda: 1280
        with patch.dict(sys.modules, {'PySide6': package, 'PySide6.QtWidgets': widgets}):
            result = window._create_sidebar()
        self.assertEqual(result.actions['vertical'], 1)
        self.assertEqual(result.actions['horizontal'], 1)
        # Sidomenyn går att dra i, men har alltid en undre och övre gräns.
        self.assertEqual(result.actions['min_width'], _design.SIDEBAR_MIN_WIDTH)
        self.assertGreaterEqual(result.actions['max_width'], result.actions['min_width'])
        self.assertTrue(result.actions['resizable'])
        self.assertIs(window.sidebar_layout.widget, result.child)
        # Bredden sätts på delaren (förslag 2), inte som fast bredd här.
        self.assertNotIn('width', result.actions)


class DealerResizeLogicTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(Path('plugins/dealers_manager/plugin.py').read_text(encoding='utf-8'))
        source = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'DealersWidget')
        names = {'_column_resized', '_restore_auto_columns', '_fit_dealer_columns', '_apply_dealer_column_widths'}
        methods = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in names]
        cls = ast.ClassDef(name='View', bases=[], keywords=[], body=methods, decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[]))
        env = {'FIELDS': FIELDS}
        exec(compile(module, '<dealer-resize-test>', 'exec'), env)
        self.widget = env['View']()
        self.widget._auto_columns = True
        self.widget._setting_column_widths = False
        self.widget._column_natural_widths = []
        self.widget._column_fit_timer = SimpleNamespace(stop=Mock())
        natural = [30, 90, 150, 60, 80, 75, 40, 40, 80, 80]
        self.current = list(natural)
        def resize(index, width):
            old = self.current[index]
            self.current[index] = width
            self.widget._column_resized(index, old, width)
        self.header = SimpleNamespace(sectionSize=lambda index: self.current[index], resizeSection=Mock(side_effect=resize))
        self.viewport = SimpleNamespace(width=lambda: 1000)
        self.table = SimpleNamespace(horizontalHeader=lambda: self.header,
                                     viewport=lambda: self.viewport,
                                     resizeColumnsToContents=Mock(side_effect=lambda: self.current.__setitem__(slice(None), natural)))
        self.widget._table_view = self.table

    def test_auto_sizes_to_content_and_expands_then_narrow_scrolls(self):
        self.widget._fit_dealer_columns()
        self.assertEqual(sum(self.current), 1000)
        self.assertTrue(self.widget._auto_columns)  # programmatic signals are not manual changes
        self.widget._apply_dealer_column_widths(300)
        self.assertEqual(self.current, self.widget._column_natural_widths)
        self.assertGreater(sum(self.current), 300)
        self.widget._apply_dealer_column_widths(1200)
        self.assertEqual(sum(self.current), 1200)

    def test_manual_resize_is_preserved_and_button_restores_auto(self):
        self.widget._fit_dealer_columns()
        self.header.resizeSection(0, 300)
        self.assertFalse(self.widget._auto_columns)
        old = list(self.current)
        self.widget._apply_dealer_column_widths(1200)
        self.assertEqual(self.current, old)
        self.widget._column_fit_timer.stop.assert_called_once()
        self.widget._restore_auto_columns()
        self.assertTrue(self.widget._auto_columns)
        self.assertEqual(sum(self.current), 1000)


if __name__ == '__main__':
    unittest.main()


class ColumnWidthTests(unittest.TestCase):
    """Kolumnbredder som anpassar sig efter innehåll och skärm."""

    def test_visible_header_and_longest_value_are_used(self):
        from core.responsive_layout import column_widths
        widths = column_widths(["VIN-kod", "Modell", "Färg"])
        self.assertEqual(len(widths), 3)
        self.assertTrue(all(width >= 60 for width in widths))

    def test_wide_values_get_more_room_than_narrow_ones(self):
        from core.responsive_layout import column_widths
        widths = column_widths(["År", "Återförsäljare"], [None, "Långt företagsnamn AB"])
        self.assertGreater(widths[1], widths[0])

    def test_narrow_window_shrinks_columns_but_never_below_minimum(self):
        from core.responsive_layout import column_widths
        widths = column_widths(["VIN-kod", "Modell", "Färg", "Återförsäljare"],
                               available=300)
        self.assertLessEqual(sum(widths), 300 + 4)
        self.assertTrue(all(width >= 60 for width in widths))

    def test_impossible_width_keeps_the_minimum(self):
        from core.responsive_layout import column_widths
        widths = column_widths(["VIN-kod", "Modell"], available=20)
        self.assertEqual(widths, [60, 60])

    def test_no_available_width_leaves_the_hints_untouched(self):
        from core.responsive_layout import column_widths
        widths = column_widths(["VIN-kod", "Färg"], available=0)
        self.assertGreater(sum(widths), 0)

    def test_scroll_check(self):
        from core.responsive_layout import fits_without_scroll
        self.assertTrue(fits_without_scroll([100, 100], 200))
        self.assertTrue(fits_without_scroll([100, 100], 201))
        self.assertFalse(fits_without_scroll([100, 100], 150))
        self.assertTrue(fits_without_scroll([], 0))

    def test_compact_threshold(self):
        from core.responsive_layout import needs_compact
        self.assertTrue(needs_compact(1099))
        self.assertFalse(needs_compact(1100))
        self.assertFalse(needs_compact("trasigt"))
