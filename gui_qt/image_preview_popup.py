"""A reusable Qt widget for displaying a full-size image preview on hover."""

from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPixmap, QCursor

class ImagePreviewPopup(QWidget):
    """A frameless popup window to display a full-size image."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setLayout(QVBoxLayout())
        self.label = QLabel(self)
        self.layout().addWidget(self.label)
        self.adjustSize()

    def show_image(self, image_path: str):
        """Loads and displays an image, adjusting the popup size."""
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            return

        # Get screen geometry to ensure the popup stays on screen
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        
        # Scale the pixmap to fit if it's too large for the screen
        max_width = screen_geometry.width() * 0.8
        max_height = screen_geometry.height() * 0.8
        if pixmap.width() > max_width or pixmap.height() > max_height:
            pixmap = pixmap.scaled(int(max_width), int(max_height), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        self.label.setPixmap(pixmap)
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