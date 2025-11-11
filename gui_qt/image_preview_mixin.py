from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QTimer, QObject, QEvent
from PySide6.QtGui import QCursor
from typing import Optional, Dict, Any
from PIL import Image
import os

from .image_preview_popup import ImagePreviewPopup
from core.config import config

class ImagePreviewMixin:
    def __init__(self):
        self.preview_popup: Optional[ImagePreviewPopup] = None
        self.preview_show_timer: Optional[QTimer] = None
        self.preview_hide_timer: Optional[QTimer] = None
        self.current_preview_data: Optional[Dict[str, Any]] = None

    def _init_image_preview_mixin(self, parent_widget: QWidget):
        self.preview_popup = ImagePreviewPopup(parent_widget)
        self.preview_show_timer = QTimer(parent_widget)
        self.preview_show_timer.setSingleShot(True)
        self.preview_show_timer.timeout.connect(self._show_preview_popup)

        self.preview_hide_timer = QTimer(parent_widget)
        self.preview_hide_timer.setSingleShot(True)
        self.preview_hide_timer.timeout.connect(self._hide_preview_popup)

    def _schedule_preview(self, item_data: Dict[str, Any]):
        self.current_preview_data = item_data
        self.preview_show_timer.stop()
        self.preview_hide_timer.stop()
        self.preview_show_timer.start(750) # Show after 750ms

    def _schedule_hide(self):
        self.preview_show_timer.stop()
        self.preview_hide_timer.stop()
        self.preview_hide_timer.start(100) # Hide after 100ms

    def _show_preview_popup(self):
        if self.current_preview_data:
            pil_image = self._get_preview_image(self.current_preview_data)
            if pil_image:
                self.preview_popup.show_image(pil_image, QCursor.pos())
                # Ensure the popup hides if mouse leaves it
                self.preview_popup.installEventFilter(self)
        self.current_preview_data = None

    def _hide_preview_popup(self):
        if self.preview_popup:
            self.preview_popup.hide()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj == self.preview_popup and event.type() == QEvent.Type.Enter:
            # If mouse re-enters the popup, cancel hide timer
            self.preview_hide_timer.stop()
        return super().eventFilter(obj, event)

    def _get_preview_image(self, item_data: Dict[str, Any]) -> Optional[Image.Image]:
        """
        Abstract method to be implemented by the class mixing this in.
        Should return a PIL Image object for the given item_data.
        """
        relative_image_path = item_data.get('cover_image_path')
        if not relative_image_path:
            return None

        try:
            workflow = item_data.get('workflow_source', 'sfw').lower()
            original_workflow = config.workflow
            config.workflow = workflow
            full_path = os.path.join(config.get_history_file_dir(), relative_image_path)
            config.workflow = original_workflow # Restore immediately
            if not os.path.exists(full_path):
                return None
            return Image.open(full_path)
        except Exception as e:
            print(f"Error loading full image for preview: {e}")
            return None
