"""A reusable Qt widget for displaying a text preview on hover."""

from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QCursor

class TextPreviewPopup(QWidget):
    """A frameless popup window to display text content."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setLayout(QVBoxLayout())
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.layout().addWidget(self.label)
        self.adjustSize()

    def show_text(self, text_content: str):
        """Loads and displays text, adjusting the popup size."""
        self.label.setText(text_content)
        self.adjustSize()
        self._position_and_show()

    def _position_and_show(self):
        """Calculates the best position for the popup and shows it."""
        pos = QCursor.pos()
        screen_geometry = QApplication.primaryScreen().availableGeometry()

        # Default position: to the right of the cursor
        x = pos.x() + 20
        y = pos.y()

        # Adjust if it goes off-screen
        if x + self.width() > screen_geometry.right():
            x = pos.x() - self.width() - 20 # Move to the left
        if y + self.height() > screen_geometry.bottom():
            y = screen_geometry.bottom() - self.height()

        self.move(x, y)
        self.show()