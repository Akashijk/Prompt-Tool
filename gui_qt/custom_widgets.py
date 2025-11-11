"""Custom Qt widgets with extended functionality."""
from PySide6.QtWidgets import QTableWidget, QListWidget, QTextEdit, QTreeWidget, QTextBrowser
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
