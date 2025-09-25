"""A Qt-based window for the Image Interrogator tool."""

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QComboBox, QFileDialog, QMessageBox, QGroupBox
)
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtGui import QPixmap
from typing import Optional, TYPE_CHECKING

from core.prompt_processor import PromptProcessor
if TYPE_CHECKING:
    from .gui_app import GUIApp

class InterrogationWorker(QObject):
    """Worker to run image interrogation in the background."""
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor, image_path: str, model: str):
        super().__init__()
        self.processor = processor
        self.image_path = image_path
        self.model = model

    @Slot()
    def run(self):
        try:
            prompt = self.processor.interrogate_image(self.image_path, self.model)
            self.finished.emit({'success': True, 'prompt': prompt})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

class ImageInterrogatorWindow(QDialog):
    """A window for generating prompts from images."""

    def __init__(self, parent: 'GUIApp', processor: PromptProcessor):
        super().__init__(parent)
        self.setWindowTitle("Image Interrogator")
        self.processor = processor
        self.parent_app = parent
        self.image_path: Optional[str] = None
        self.interrogation_thread: Optional[QThread] = None

        self.models = [m['name'] for m in self.processor.get_available_models() if 'llava' in m['name'].lower() or 'vision' in m.get('family', '').lower()]

        self._create_widgets()
        self._connect_signals()
        self.resize(800, 600)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        # Top section for image selection and preview
        top_layout = QHBoxLayout()
        self.select_image_button = QPushButton("Select Image...")
        top_layout.addWidget(self.select_image_button)
        
        self.image_preview_label = QLabel("No image selected.")
        self.image_preview_label.setFixedSize(256, 256)
        self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview_label.setStyleSheet("border: 1px solid gray;")
        top_layout.addWidget(self.image_preview_label)
        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # Model selection
        model_group = QGroupBox("Vision Model")
        model_layout = QHBoxLayout(model_group)
        self.model_combo = QComboBox()
        if self.models:
            self.model_combo.addItems(self.models)
        else:
            self.model_combo.addItem("No vision models found (e.g., LLaVA)")
            self.model_combo.setEnabled(False)
        model_layout.addWidget(self.model_combo)
        self.interrogate_button = QPushButton("Interrogate Image")
        self.interrogate_button.setEnabled(False)
        model_layout.addWidget(self.interrogate_button)
        main_layout.addWidget(model_group)

        # Result section
        result_group = QGroupBox("Generated Prompt")
        result_layout = QVBoxLayout(result_group)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        result_layout.addWidget(self.result_text)
        main_layout.addWidget(result_group)

        # Action buttons
        action_layout = QHBoxLayout()
        action_layout.addStretch()
        self.copy_button = QPushButton("Copy Prompt")
        self.load_button = QPushButton("Load in Editor")
        self.generate_button = QPushButton("Generate Image")
        self.copy_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        action_layout.addWidget(self.copy_button)
        action_layout.addWidget(self.load_button)
        action_layout.addWidget(self.generate_button)
        main_layout.addLayout(action_layout)

    def _connect_signals(self):
        self.select_image_button.clicked.connect(self._on_select_image)
        self.interrogate_button.clicked.connect(self._on_interrogate)
        self.copy_button.clicked.connect(self._on_copy)
        self.load_button.clicked.connect(self._on_load)

    @Slot()
    def _on_select_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select an Image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if file_path:
            self.image_path = file_path
            pixmap = QPixmap(file_path)
            self.image_preview_label.setPixmap(pixmap.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.interrogate_button.setEnabled(bool(self.models))
            self.result_text.clear()
            self.copy_button.setEnabled(False)
            self.load_button.setEnabled(False)
            self.generate_button.setEnabled(False)

    @Slot()
    def _on_interrogate(self):
        if not self.image_path or not self.models: return
        
        model = self.model_combo.currentText()
        self.interrogate_button.setEnabled(False)
        self.result_text.setPlainText("Interrogating image with AI...")

        self.interrogation_thread = QThread(self)
        worker = InterrogationWorker(self.processor, self.image_path, model)
        worker.moveToThread(self.interrogation_thread)

        self.interrogation_thread.started.connect(worker.run)
        worker.finished.connect(self._on_interrogation_finished)
        worker.finished.connect(self.interrogation_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self.interrogation_thread.finished.connect(self.interrogation_thread.deleteLater)
        self.interrogation_thread.start()

    @Slot(dict)
    def _on_interrogation_finished(self, result: dict):
        self.interrogate_button.setEnabled(True)
        if result['success']:
            prompt = result.get('prompt', '')
            self.result_text.setPlainText(prompt)
            self.copy_button.setEnabled(bool(prompt))
            self.load_button.setEnabled(bool(prompt))
            self.generate_button.setEnabled(bool(prompt) and self.processor.is_invokeai_connected())
        else:
            error_msg = result.get('error', 'Unknown error')
            self.result_text.setPlainText(f"Error: {error_msg}")
            QMessageBox.critical(self, "Interrogation Error", error_msg)

    @Slot()
    def _on_copy(self):
        QApplication.clipboard().setText(self.result_text.toPlainText())
        self.parent_app.status_bar.showMessage("Interrogated prompt copied to clipboard.", 3000)

    @Slot()
    def _on_load(self):
        prompt = self.result_text.toPlainText()
        if prompt:
            # The parent_app is the GUIApp instance.
            self.parent_app._load_prompt_from_history({'original_prompt': prompt})
            self.close()