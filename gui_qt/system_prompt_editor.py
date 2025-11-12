"""A Qt-based window for editing system-level prompts (enhancement, variations)."""

import os
from typing import Optional

from PySide6.QtCore import Slot, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget, QGroupBox,
    QTreeWidget, QTreeWidgetItem, QPushButton, QMessageBox,
    QInputDialog
)
from PySide6.QtGui import QCloseEvent

from core.prompt_processor import PromptProcessor
from core.config import config, update_and_save_settings
from .custom_widgets import SmoothTextEdit

class SystemPromptEditorWindow(QDialog):
    """A Qt-based window for editing system-level prompts."""

    def __init__(self, parent, processor: PromptProcessor):
        super().__init__(parent)
        self.setWindowTitle("System Prompt Editor")
        self.parent_app = parent
        self.processor = processor
        self.selected_file: Optional[str] = None
        self.is_dirty = False

        # UI Widgets
        self.file_tree: Optional[QTreeWidget] = None
        self.editor_text: Optional[SmoothTextEdit] = None
        self.save_button: Optional[QPushButton] = None
        self.reset_button: Optional[QPushButton] = None
        self.rename_button: Optional[QPushButton] = None
        self.archive_button: Optional[QPushButton] = None
        self.set_default_button: Optional[QPushButton] = None

        self._create_widgets()
        self._connect_signals()
        self._populate_file_list()
        self.resize(900, 600)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # --- Left Pane: File List and Actions ---
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        
        file_actions_layout = QHBoxLayout()
        new_button = QPushButton("New...")
        new_button.clicked.connect(self._create_new_prompt)
        self.rename_button = QPushButton("Rename...")
        self.archive_button = QPushButton("Archive")
        file_actions_layout.addWidget(new_button)
        file_actions_layout.addWidget(self.rename_button)
        file_actions_layout.addWidget(self.archive_button)
        left_layout.addLayout(file_actions_layout)

        self.set_default_button = QPushButton("Set as Default")
        left_layout.addWidget(self.set_default_button)

        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderHidden(True)
        left_layout.addWidget(self.file_tree)
        splitter.addWidget(left_pane)

        # --- Right Pane: Editor ---
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        
        editor_group = QGroupBox("Edit Prompt")
        editor_layout = QVBoxLayout(editor_group)
        self.editor_text = SmoothTextEdit()
        editor_layout.addWidget(self.editor_text)
        right_layout.addWidget(editor_group)

        editor_actions_layout = QHBoxLayout()
        self.save_button = QPushButton("Save Changes")
        self.reset_button = QPushButton("Reset to Default")
        editor_actions_layout.addWidget(self.save_button)
        editor_actions_layout.addWidget(self.reset_button)
        right_layout.addLayout(editor_actions_layout)
        splitter.addWidget(right_pane)

        splitter.setSizes([300, 600])
        self._update_button_states() # Set initial disabled state

    def _connect_signals(self):
        self.file_tree.itemSelectionChanged.connect(self._on_file_select)
        self.editor_text.textChanged.connect(self._mark_dirty)
        self.save_button.clicked.connect(self._save_file)
        self.reset_button.clicked.connect(self._reset_to_default)
        self.rename_button.clicked.connect(self._rename_prompt)
        self.archive_button.clicked.connect(self._archive_prompt)
        self.set_default_button.clicked.connect(self._set_as_default_negative_prompt)

    def _populate_file_list(self):
        self.file_tree.clear()
        self.file_tree.setUpdatesEnabled(False)
        
        files_by_category = self.processor.get_system_prompt_files()

        for category, files in files_by_category.items():
            if not files:
                continue
            category_item = QTreeWidgetItem(self.file_tree, [category])
            for file_info in files:
                file_item = QTreeWidgetItem(category_item, [file_info['display_name']])
                file_item.setData(0, Qt.ItemDataRole.UserRole, file_info['relative_path'])
            category_item.setExpanded(True)
        
        self.file_tree.setUpdatesEnabled(True)

    @Slot()
    def _on_file_select(self):
        selected_items = self.file_tree.selectedItems()
        if not selected_items:
            self._clear_editor()
            return

        item = selected_items[0]
        if not item.parent(): # It's a category header
            self._clear_editor()
            return

        self.selected_file = item.data(0, Qt.ItemDataRole.UserRole)
        if not self.selected_file:
            QMessageBox.critical(self, "Error", "Could not map display name to a file.")
            return

        try:
            content = self.processor.load_system_prompt_content(self.selected_file)
            self.editor_text.setPlainText(content)
            self._clear_dirty()
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Could not load system prompt:\n{e}")
        
        self._update_button_states()

    def _update_button_states(self):
        is_file_selected = self.selected_file is not None
        self.editor_text.setEnabled(is_file_selected)
        self.save_button.setEnabled(self.is_dirty and is_file_selected)

        has_default = is_file_selected and bool(self.processor.get_default_system_prompt(self.selected_file))
        self.reset_button.setEnabled(has_default)
        self.rename_button.setEnabled(is_file_selected and not has_default)
        self.archive_button.setEnabled(is_file_selected and not has_default)

        is_negative_prompt = is_file_selected and self.selected_file.startswith('negative_prompts/')
        self.set_default_button.setEnabled(is_negative_prompt)
        if is_negative_prompt:
            key = os.path.splitext(os.path.basename(self.selected_file))[0]
            self.set_default_button.setText("Remove Default" if key == config.DEFAULT_NEGATIVE_PROMPT_KEY else "Set as Default")

    def _clear_editor(self):
        self.selected_file = None
        self.editor_text.clear()
        self._clear_dirty()
        self._update_button_states()

    @Slot()
    def _mark_dirty(self):
        if not self.is_dirty:
            self.is_dirty = True
            self.setWindowTitle(self.windowTitle() + "*")
            self._update_button_states()

    def _clear_dirty(self):
        self.is_dirty = False
        self.setWindowTitle("System Prompt Editor")
        self._update_button_states()

    @Slot()
    def _save_file(self):
        if not self.selected_file:
            return
        content = self.editor_text.toPlainText()
        try:
            self.processor.save_system_prompt_content(self.selected_file, content)
            self._clear_dirty()
            self.parent_app.status_bar.showMessage(f"Saved '{self.selected_file}' successfully.", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save system prompt:\n{e}")

    @Slot()
    def _reset_to_default(self):
        if not self.selected_file: return
        if QMessageBox.question(self, "Confirm Reset", f"Are you sure you want to reset '{self.selected_file}' to its default content?") == QMessageBox.StandardButton.No:
            return
        
        default_content = self.processor.get_default_system_prompt(self.selected_file)
        self.editor_text.setPlainText(default_content)
        self._save_file()

    @Slot()
    def _set_as_default_negative_prompt(self):
        if not self.selected_file or not self.selected_file.startswith('negative_prompts/'):
            return

        key = os.path.splitext(os.path.basename(self.selected_file))[0]
        new_default_key = "" if key == config.DEFAULT_NEGATIVE_PROMPT_KEY else key
        message = f"'{key}' is no longer the default negative prompt." if new_default_key == "" else f"'{key}' is now the default negative prompt."

        try:
            update_and_save_settings({'default_negative_prompt_key': new_default_key})
            self.processor.clear_default_negative_prompt_cache()
            self._populate_file_list()
            QMessageBox.information(self, "Default Set", message)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not set default negative prompt:\n{e}")

    @Slot()
    def _create_new_prompt(self):
        items = ["Variation", "Negative Prompt", "Enhancement Prompt"]
        item, ok = QInputDialog.getItem(self, "Select Type", "Select the type of prompt to create:", items, 0, False)
        if not ok or not item:
            return

        prompt_type_map = {"Variation": "variation", "Negative Prompt": "negative_prompt", "Enhancement Prompt": "enhancement"}
        prompt_type = prompt_type_map[item]

        filename, ok = QInputDialog.getText(self, "New Prompt", "Enter new filename (without extension):")
        if not ok or not filename:
            return

        try:
            self.processor.create_system_prompt(filename, prompt_type)
            self._populate_file_list()
            QMessageBox.information(self, "Success", f"Created new system prompt '{filename}'.")
        except Exception as e:
            QMessageBox.critical(self, "Creation Error", f"Could not create system prompt:\n{e}")

    @Slot()
    def _archive_prompt(self):
        if not self.selected_file: return
        if QMessageBox.question(self, "Confirm Archive", f"Are you sure you want to archive '{self.selected_file}'?") == QMessageBox.StandardButton.No:
            return
        
        try:
            self.processor.archive_system_prompt(self.selected_file)
            self._clear_editor()
            self._populate_file_list()
            QMessageBox.information(self, "Success", f"Archived '{self.selected_file}'.")
        except Exception as e:
            QMessageBox.critical(self, "Archive Error", f"Could not archive system prompt:\n{e}")

    @Slot()
    def _rename_prompt(self):
        if not self.selected_file: return

        old_basename, ext = os.path.splitext(os.path.basename(self.selected_file))
        new_basename, ok = QInputDialog.getText(self, "Rename Prompt", "Enter new name (without extension):", text=old_basename)
        if not ok or not new_basename or new_basename.strip() == old_basename:
            return
        
        new_filename = f"{new_basename.strip()}{ext}"
        try:
            self.processor.rename_system_prompt(self.selected_file, new_filename)
            self._populate_file_list()
            QMessageBox.information(self, "Success", f"Renamed to '{new_filename}'.")
        except Exception as e:
            QMessageBox.critical(self, "Rename Error", f"Could not rename system prompt:\n{e}")

    def closeEvent(self, event: QCloseEvent):
        if self.is_dirty:
            reply = QMessageBox.question(self, "Unsaved Changes", "You have unsaved changes. Do you want to save them before closing?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save:
                self._save_file()
                if self.is_dirty:
                    event.ignore()
                else:
                    event.accept()
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
            else:
                event.accept()
        else:
            event.accept()