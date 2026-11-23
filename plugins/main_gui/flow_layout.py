"""En flödeslayout som bryter om knappar när fönstrets bredd ändras."""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout
from core.responsive_layout import flow_positions


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            result = self._items.pop(index)
            self.invalidate()
            return result
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        margins = self.contentsMargins()
        effective_width = max(0, width - margins.left() - margins.right())
        _positions, height = flow_positions(self._sizes(), effective_width, self.spacing())
        return height + margins.top() + margins.bottom()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def sizeHint(self):
        return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        items = [item for item in self._items if not item.isEmpty()]
        sizes = [item.sizeHint().expandedTo(item.minimumSize()) for item in items]
        positions, _height = flow_positions([(s.width(), s.height()) for s in sizes], area.width(), self.spacing())
        for item, size, (x, y) in zip(items, sizes, positions):
            item.setGeometry(QRect(QPoint(area.x() + x, area.y() + y), size))

    def _sizes(self):
        sizes = []
        for item in self._items:
            if not item.isEmpty():
                size = item.sizeHint().expandedTo(item.minimumSize())
                sizes.append((size.width(), size.height()))
        return sizes
