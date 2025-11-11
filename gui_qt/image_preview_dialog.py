"""A Qt dialog to display a full-size image and its metadata."""

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QScrollArea, QDialogButtonBox
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
from .custom_widgets import SmoothTextEdit


class ImagePreviewDialog(QDialog):
    """A dialog for showing a single image and its generation parameters."""

    def __init__(self, parent, image_path: str, params: dict):
        super().__init__(parent)
        self.setWindowTitle("Image Preview")
        self.resize(800, 900)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

        self.main_layout = QVBoxLayout(self)

        # --- Image Display ---
        # Use a scroll area in case the image is very large
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.image_label = QLabel("Loading image...")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_area.setWidget(self.image_label)
        self.main_layout.addWidget(scroll_area, 1) # Give it stretch factor

        # Load the original pixmap and store it
        self._original_pixmap = QPixmap(image_path)
        if self._original_pixmap.isNull():
            self.image_label.setText(f"Error: Could not load image from\n{image_path}")
        else:
            self._update_image_display() # Initial display

        # --- Parameters Display ---
        self.params_text = SmoothTextEdit()
        self.params_text.setReadOnly(True)
        self.params_text.setPlainText(self._format_generation_params(params))
        self.main_layout.addWidget(self.params_text)

        # --- Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        self.main_layout.addWidget(button_box)

    def _update_image_display(self):
        """Scales the original pixmap to fit the current label size and sets it."""
        if self._original_pixmap.isNull():
            return

        # Get the available size for the image (label size within scroll area)
        available_size = self.image_label.size()
        if available_size.isEmpty():
            # Fallback if size is not yet determined, use a reasonable default
            available_size = self.image_label.parentWidget().size()
            if available_size.isEmpty():
                available_size = self.size() # Fallback to dialog size

        # Scale the pixmap to fit the available size, maintaining aspect ratio
        scaled_pixmap = self._original_pixmap.scaled(available_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        """Handles resize events to rescale the image."""
        super().resizeEvent(event)
        self._update_image_display()

    def _format_generation_params(self, params: dict) -> str:
        """Formats generation parameters into a human-readable string."""
        details = []
        details.append("Generation Parameters:")
        details.append(f"  Model: {params.get('model', {}).get('name', 'N/A')}")
        details.append(f"  Seed: {params.get('seed', 'N/A')}")
        details.append(f"  Steps: {params.get('steps', 'N/A')}")
        details.append(f"  CFG Scale: {params.get('cfg_scale', 'N/A')}")
        details.append(f"  Size: {params.get('width', 'N/A')}x{params.get('height', 'N/A')}")
        details.append(f"  Scheduler: {params.get('scheduler', 'N/A')}")
        
        neg_prompt = params.get('negative_prompt', '')
        if neg_prompt:
            details.append(f"  Negative Prompt:\n    {neg_prompt}")

        loras = params.get('loras', [])
        if loras:
            details.append("  LoRAs:")
            for lora in loras:
                details.append(f"    - {lora.get('lora_object', {}).get('name', 'N/A')} (Weight: {lora.get('weight', 'N/A')})")
        
        return "\n".join(details)