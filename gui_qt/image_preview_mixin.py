"""A mixin class to provide image preview functionality on hover."""

from PySide6.QtCore import QTimer
from .image_preview_popup import ImagePreviewPopup
from typing import Optional

class ImagePreviewMixin:
    """Provides functionality to show a popup image preview on hover."""

    def __init__(self):
        self.image_preview_popup: Optional[ImagePreviewPopup] = None
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(500) # 500ms delay before showing

    def _schedule_preview(self, image_path: str):
        """Schedules the preview popup to appear after a short delay."""
        if not self.image_preview_popup:
            self.image_preview_popup = ImagePreviewPopup()
        
        # Connect the timer's timeout to a lambda that shows the image
        self.preview_timer.timeout.connect(lambda: self.image_preview_popup.show_image(image_path))
        self.preview_timer.start()

    def _hide_preview(self):
        """Hides the preview popup and cancels any pending show requests."""
        self.preview_timer.stop()
        if self.image_preview_popup:
            self.image_preview_popup.hide()