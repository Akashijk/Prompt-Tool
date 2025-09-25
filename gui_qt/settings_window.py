"""A Qt dialog for editing application settings."""

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QGridLayout,
    QDialogButtonBox, QGroupBox, QHBoxLayout, QFileDialog, QWidget, QMessageBox,
    QCheckBox
)
from PySide6.QtCore import Slot
from typing import Callable, TYPE_CHECKING
if TYPE_CHECKING:
    from .gui_app import GUIApp

from core.config import config, load_settings, save_settings

class SettingsWindow(QDialog):
    """A dialog for editing application settings."""

    def __init__(self, parent: 'GUIApp', on_save_callback: Callable):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.on_save_callback = on_save_callback

        self.settings = load_settings()

        self._create_widgets()
        self._load_initial_values()
        self._connect_signals()
        self.resize(850, 450)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        # Use a grid layout to organize the main settings groups
        grid_layout = QGridLayout()
        main_layout.addLayout(grid_layout)

        # --- Server URLs ---
        server_group = QGroupBox("Server URLs")
        server_layout = QFormLayout(server_group)
        server_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.ollama_url_edit = QLineEdit()
        self.invokeai_url_edit = QLineEdit()
        server_layout.addRow("Ollama Base URL:", self.ollama_url_edit)
        server_layout.addRow("InvokeAI Base URL:", self.invokeai_url_edit)
        grid_layout.addWidget(server_group, 0, 0)

        # --- Directory Paths ---
        paths_group = QGroupBox("Directory Paths")
        paths_layout = QFormLayout(paths_group)
        paths_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.template_dir_edit = self._create_path_editor(paths_layout, "Templates Base Dir:")
        self.wildcard_dir_edit = self._create_path_editor(paths_layout, "Wildcards Base Dir:")
        self.history_dir_edit = self._create_path_editor(paths_layout, "History Base Dir:")
        self.system_prompts_dir_edit = self._create_path_editor(paths_layout, "System Prompts Dir:")
        grid_layout.addWidget(paths_group, 0, 1)

        # --- Generation Defaults ---
        generation_group = QGroupBox("Generation Defaults")
        generation_layout = QFormLayout(generation_group)
        self.save_to_gallery_default_check = QCheckBox("Save generated images to InvokeAI gallery by default")
        generation_layout.addRow(self.save_to_gallery_default_check)
        grid_layout.addWidget(generation_group, 1, 0, 1, 2) # Span across both columns

        main_layout.addStretch()

        # --- Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        main_layout.addWidget(self.button_box)

    def _create_path_editor(self, parent_layout: QFormLayout, label: str) -> QLineEdit:
        """Helper to create a line edit with a browse button."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        line_edit = QLineEdit()
        layout.addWidget(line_edit)
        
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(lambda: self._browse_for_directory(line_edit))
        layout.addWidget(browse_button)
        
        parent_layout.addRow(label, widget)
        return line_edit

    def _load_initial_values(self):
        self.ollama_url_edit.setText(self.settings.get('ollama_base_url', ''))
        self.invokeai_url_edit.setText(self.settings.get('invokeai_base_url', ''))
        self.template_dir_edit.setText(self.settings.get('template_base_dir', ''))
        self.wildcard_dir_edit.setText(self.settings.get('wildcard_base_dir', ''))
        self.history_dir_edit.setText(self.settings.get('history_dir', ''))
        self.system_prompts_dir_edit.setText(self.settings.get('system_prompt_base_dir', ''))
        self.save_to_gallery_default_check.setChecked(self.settings.get('save_to_gallery_by_default', False))

    def _connect_signals(self):
        self.button_box.accepted.connect(self._on_save)
        self.button_box.rejected.connect(self.reject)

    @Slot()
    def _browse_for_directory(self, line_edit: QLineEdit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", line_edit.text())
        if directory:
            line_edit.setText(directory)

    @Slot()
    def _on_save(self):
        """Saves the settings and closes the dialog."""
        self.settings['ollama_base_url'] = self.ollama_url_edit.text().strip()
        self.settings['invokeai_base_url'] = self.invokeai_url_edit.text().strip()
        self.settings['template_base_dir'] = self.template_dir_edit.text().strip()
        self.settings['wildcard_base_dir'] = self.wildcard_dir_edit.text().strip()
        self.settings['history_dir'] = self.history_dir_edit.text().strip()
        self.settings['system_prompt_base_dir'] = self.system_prompts_dir_edit.text().strip()
        self.settings['save_to_gallery_by_default'] = self.save_to_gallery_default_check.isChecked()

        try:
            save_settings(self.settings)
            self.on_save_callback()
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save settings:\n{e}")