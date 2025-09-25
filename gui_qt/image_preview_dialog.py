"""A Qt dialog to display a full-size image and its metadata."""

import json
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QTextEdit, QLabel, QScrollArea, QWidget,
    QDialogButtonBox
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt


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

        # Load the pixmap
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.image_label.setText(f"Error: Could not load image from\n{image_path}")
        else:
            # Scale pixmap to fit window width, preserving aspect ratio
            # A fixed reasonable size to start with. The scroll area will handle overflow.
            self.image_label.setPixmap(pixmap.scaledToWidth(800, Qt.TransformationMode.SmoothTransformation))

        # --- Parameters Display ---
        self.params_text = QTextEdit()
        self.params_text.setReadOnly(True)
        try:
            # Pretty-print the JSON parameters
            params_str = json.dumps(params, indent=2)
            self.params_text.setPlainText(params_str)
        except (TypeError, ValueError):
            self.params_text.setPlainText("Could not display parameters.")
        self.main_layout.addWidget(self.params_text)

        # --- Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        self.main_layout.addWidget(button_box)