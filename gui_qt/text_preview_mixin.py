"""A mixin class to provide text preview functionality on hover."""

from PySide6.QtCore import QTimer
from .text_preview_popup import TextPreviewPopup
from typing import Optional, Callable

class TextPreviewMixin:
    """Provides functionality to show a popup text preview on hover."""

    def __init__(self):
        self.text_preview_popup: Optional[TextPreviewPopup] = None
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(1000) # 1-second delay

    def _schedule_text_preview(self, content_loader: Callable[[], Optional[str]]):
        """Schedules the preview popup to appear after a short delay."""
        if not self.text_preview_popup:
            self.text_preview_popup = TextPreviewPopup()
        
        self.preview_timer.timeout.connect(lambda: self.text_preview_popup.show_text(content_loader() or "Could not load content."))
        self.preview_timer.start()

    def _hide_text_preview(self):
        """Hides the preview popup and cancels any pending show requests."""
        self.preview_timer.stop()
        if self.text_preview_popup:
            self.text_preview_popup.hide()