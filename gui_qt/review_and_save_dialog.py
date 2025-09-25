"""A Qt dialog to review and save AI-generated content."""

import json
from typing import Optional, Callable, TYPE_CHECKING, Dict, Any

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QTextEdit, QLineEdit,
    QDialogButtonBox, QLabel, QMessageBox, QTabWidget, QWidget, QHBoxLayout, QGroupBox
)
from PySide6.QtCore import Slot, Qt, QTimer

from core.prompt_processor import PromptProcessor
from core.config import config
# Placeholder for WildcardEditor - will need to be ported or replaced
class StructuredEditorPlaceholder(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Structured Editor Placeholder (Port WildcardEditor from Tkinter)"))
    def set_data(self, data: Dict):
        pass
    def get_data(self) -> Dict:
        return {}

class LoadingAnimation(QLabel):
    def __init__(self, parent=None, size: int = 24):
        super().__init__(parent)
        self.animation_chars = ["-", "\\", "|", "/"]
        self.animation_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_animation)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)

    def _update_animation(self):
        self.setText(self.animation_chars[self.animation_index])
        self.animation_index = (self.animation_index + 1) % len(self.animation_chars)

    def start(self):
        self.timer.start(100) # Update every 100ms
        self.show()

    def stop(self):
        self.timer.stop()
        self.hide()

class ReviewAndSaveDialog(QDialog):
    """A dialog to show AI-generated content and allow saving it."""

    def __init__(self, parent, processor: PromptProcessor, content_type: str, generated_content: str, update_callback: Callable, filename: Optional[str] = None, regenerate_callback: Optional[Callable] = None, is_loading: bool = False, next_step_callback: Optional[Callable] = None):
        super().__init__(parent)
        self.processor = processor
        self.content_type = content_type
        self.update_callback = update_callback
        self.prefilled_filename = filename
        self.regenerate_callback = regenerate_callback
        self.next_step_callback = next_step_callback
        self.is_loading = is_loading

        title = f"Review: {self.prefilled_filename}" if self.prefilled_filename else f"Review New {self.content_type.capitalize()}"
        self.setWindowTitle(title)
        self.resize(800, 600)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

        self._create_widgets()

        if self.is_loading:
            self._set_ui_loading(True)
        else:
            self.update_content(generated_content)

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        if self.content_type == 'wildcard':
            self.editor_notebook = QTabWidget(self)
            main_layout.addWidget(self.editor_notebook)

            self.structured_editor_frame = QWidget()
            structured_editor_layout = QVBoxLayout(self.structured_editor_frame)
            self.structured_editor = StructuredEditorPlaceholder(self.structured_editor_frame) # Placeholder
            structured_editor_layout.addWidget(self.structured_editor)
            self.editor_notebook.addTab(self.structured_editor_frame, "Structured Editor")

            self.raw_text_frame = QWidget()
            raw_text_layout = QVBoxLayout(self.raw_text_frame)
            self.raw_text_editor = QTextEdit()
            raw_text_layout.addWidget(self.raw_text_editor)
            self.editor_notebook.addTab(self.raw_text_frame, "Raw Text Editor")
            
            self.text_widget = self.raw_text_editor # Alias for compatibility
        else: # 'template'
            self.text_widget = QTextEdit()
            main_layout.addWidget(self.text_widget)
            
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        main_layout.addWidget(button_frame)

        # Filename input
        filename_layout = QVBoxLayout()
        filename_layout.addWidget(QLabel("Filename:"))
        self.filename_edit = QLineEdit(self.prefilled_filename)
        button_layout.addLayout(filename_layout)
        button_layout.addWidget(self.filename_edit)

        # Save button
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self._on_save)
        button_layout.addWidget(self.save_button)

        # Regenerate button and loading animation
        if self.regenerate_callback:
            self.regenerate_button = QPushButton("Regenerate")
            self.regenerate_button.clicked.connect(self._regenerate)
            button_layout.addWidget(self.regenerate_button)

            self.loading_animation = LoadingAnimation(self)
            button_layout.addWidget(self.loading_animation)
            self.loading_animation.hide() # Hidden by default

        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

    def _set_ui_loading(self, is_loading: bool, verb: str = "Generating"):
        """Centralized method to toggle the UI between loading and interactive states."""
        self.save_button.setEnabled(not is_loading)
        if hasattr(self, 'regenerate_button'):
            self.regenerate_button.setEnabled(not is_loading)
            if is_loading:
                self.regenerate_button.hide()
                self.loading_animation.start()
            else:
                self.regenerate_button.show()
                self.loading_animation.stop()
        
        self.text_widget.setReadOnly(is_loading)
        if is_loading:
            self.text_widget.clear()
            self.text_widget.setText(f"{verb} new {self.content_type}...")
        
        title = f"{verb}: {self.prefilled_filename}" if self.prefilled_filename else f"{verb} New {self.content_type.capitalize()}"
        self.setWindowTitle(title)

    def update_content(self, new_content: str):
        """Updates the text widget with new content and re-enables buttons."""
        self._set_ui_loading(False)
        if self.content_type == 'wildcard':
            self.raw_text_editor.clear()
            try:
                parsed_data = json.loads(new_content)
                self.structured_editor.set_data(parsed_data)
                self.raw_text_editor.setText(json.dumps(parsed_data, indent=2))
                self.editor_notebook.setCurrentWidget(self.structured_editor_frame)
            except (json.JSONDecodeError, TypeError):
                # If content is not valid JSON, show it in the raw editor
                self.structured_editor.set_data({})
                self.raw_text_editor.setText(new_content)
                self.editor_notebook.setCurrentWidget(self.raw_text_frame)
        else: # template
            self.text_widget.setText(new_content)

        if self.prefilled_filename:
            self.filename_edit.setText(self.prefilled_filename)

    @Slot()
    def _regenerate(self):
        """Calls the provided callback to regenerate content and updates UI to a loading state."""
        if self.regenerate_callback:
            self._set_ui_loading(True, verb="Regenerating")
            # Pass self to the callback so it can update this window instance
            self.regenerate_callback(self)

    @Slot()
    def _on_save(self):
        filename = self.filename_edit.text().strip()
        content = ""

        if self.content_type == 'wildcard':
            if self.editor_notebook.currentWidget() == self.structured_editor_frame:
                data = self.structured_editor.get_data()
                content = json.dumps(data, indent=2)
            else:
                content = self.raw_text_editor.toPlainText().strip()
        else: # template
            content = self.text_widget.toPlainText().strip()

        if not filename or not content:
            QMessageBox.warning(self, "Invalid Input", "Filename and content cannot be empty.")
            return

        try:
            if self.content_type == "wildcard":
                json.loads(content) # Validate JSON before saving
                is_nsfw_only = False
                if config.workflow == 'nsfw':
                    reply = QMessageBox.question(
                        self,
                        "Wildcard Scope",
                        "Save this as an NSFW-only wildcard?\n\n"
                        "(Choosing 'No' will save it to the shared folder, making it available in both SFW and NSFW modes.)",
                        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
                    )
                    if reply == QMessageBox.Cancel:
                        return
                    is_nsfw_only = (reply == QMessageBox.Yes)
                self.processor.save_wildcard_content(filename, content, is_nsfw_only=is_nsfw_only)
            elif self.content_type == "template":
                self.processor.save_template_content(filename, content)
            
            self.update_callback(self.content_type)
            if self.next_step_callback:
                self.next_step_callback(filename)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save the {self.content_type}:\n{e}")