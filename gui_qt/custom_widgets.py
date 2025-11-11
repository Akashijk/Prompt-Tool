"""Custom Qt widgets with extended functionality."""
from PySide6.QtWidgets import QTableWidget, QListWidget, QTextEdit, QTreeWidget, QTextBrowser, QWidget
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QColor, QPen
from .smooth_scroll_mixin import SmoothScrollMixin

class SmoothTableWidget(SmoothScrollMixin, QTableWidget):
    """A QTableWidget with smooth scrolling."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class SmoothListWidget(SmoothScrollMixin, QListWidget):
    """A QListWidget with smooth scrolling."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class SmoothTextEdit(SmoothScrollMixin, QTextEdit):
    """A QTextEdit with smooth scrolling."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class SmoothTreeWidget(SmoothScrollMixin, QTreeWidget):
    """A QTreeWidget with smooth scrolling."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class SmoothTextBrowser(SmoothScrollMixin, QTextBrowser):
    """A QTextBrowser with smooth scrolling."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class LoadingSpinner(QWidget):
    """A simple animated loading spinner widget."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_angle)
        self.setFixedSize(48, 48)

    def start(self):
        self.timer.start(20) # Update every 20ms

    def stop(self):
        self.timer.stop()

    def _update_angle(self):
        self.angle = (self.angle + 10) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#3498db"), 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawArc(rect, self.angle * 16, 120 * 16)
