from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QApplication, QWidget
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QPoint, QEvent
from PIL import Image
from PIL.ImageQt import ImageQt
from typing import Optional

class ImagePreviewPopup(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 180); border: 1px solid #555; border-radius: 5px;")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.image_label)
        self.setLayout(self.layout)

        self.setMouseTracking(True) # Enable mouse tracking for the popup itself

    def show_image(self, pil_image: Image.Image, global_pos: QPoint):
        if pil_image is None:
            self.hide()
            return

        screen_geometry = QApplication.primaryScreen().availableGeometry()
        
        # Scale image to fit screen, maintaining aspect ratio
        img_copy = pil_image.copy()
        max_width = screen_geometry.width() * 0.6
        max_height = screen_geometry.height() * 0.6
        img_copy.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        qimage = ImageQt(img_copy)
        pixmap = QPixmap.fromImage(qimage)
        self.image_label.setPixmap(pixmap)
        self.adjustSize()

        # Position the popup near the mouse cursor, but ensure it's on screen
        x = global_pos.x() + 20
        y = global_pos.y() + 20

        # Adjust if it goes off-screen
        if x + self.width() > screen_geometry.right():
            x = global_pos.x() - self.width() - 20
        if y + self.height() > screen_geometry.bottom():
            y = screen_geometry.bottom() - self.height()
        if x < screen_geometry.left():
            x = screen_geometry.left()
        if y < screen_geometry.top():
            y = screen_geometry.top()

        self.move(x, y)
        self.show()

    def event(self, event: QEvent):
        # If mouse leaves the popup, hide it
        if event.type() == QEvent.Type.Leave:
            self.hide()
        return super().event(event)
