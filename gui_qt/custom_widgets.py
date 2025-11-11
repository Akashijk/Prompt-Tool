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

class LinkOnlyTextBrowser(SmoothTextBrowser):
    """A QTextBrowser that only allows clicking on links and emits a signal when a link is clicked."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False) # Disable automatic opening of links
        self.setReadOnly(True)

    def mousePressEvent(self, event):
        anchor = self.anchorAt(event.pos())
        if anchor:
            self.anchorClicked.emit(QUrl(anchor))
        else:
            super().mousePressEvent(event)

class ImageGalleryItemWidget(QWidget):
    """A custom widget for displaying an image and text in the history viewer's image gallery."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(128, 160) # Match QListWidget icon size and leave space for text
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFixedSize(128, 128) # Thumbnail size
        self.image_label.setStyleSheet("border: 1px solid transparent;") # Default transparent border
        self.layout.addWidget(self.image_label)

        self.text_label = QLabel()
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setWordWrap(True)
        self.text_label.setFixedHeight(32) # Space for 2 lines of text
        self.layout.addWidget(self.text_label)

        self.setLayout(self.layout)

    def set_image(self, pixmap: QPixmap):
        self.image_label.setPixmap(pixmap.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_text(self, text: str):
        self.text_label.setText(text)

    def set_is_cover_image(self, is_cover: bool):
        if is_cover:
            self.image_label.setStyleSheet("border: 3px solid #FFD700;") # Gold border for cover image
        else:
            self.image_label.setStyleSheet("border: 1px solid transparent;") # Transparent border

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
