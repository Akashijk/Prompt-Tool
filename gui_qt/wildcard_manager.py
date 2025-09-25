"""The Qt-based Wildcard Manager window."""

import json
import os
from collections import Counter
import re
import copy
import difflib
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QSplitter, QTabWidget, QWidget, QGroupBox, QListWidgetItem, QCheckBox,
    QFormLayout,
    QTextEdit, QMessageBox, QInputDialog
)
from PySide6.QtGui import QCloseEvent
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from typing import Callable, List, Dict, Optional, Any, Tuple

from core.prompt_processor import PromptProcessor
from .wildcard_editor_widget import WildcardEditor
from .multi_wildcard_editor import MultiWildcardEditorWindow


class FindReplaceDialog(QDialog):
    """A dialog for finding and replacing text in wildcard choices."""
    def __init__(self, parent, selection_exists: bool):
        super().__init__(parent)
        self.setWindowTitle("Find and Replace in Choices")
        self.result: Optional[Dict[str, Any]] = None

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.find_edit = QLineEdit()
        self.replace_edit = QLineEdit()
        form_layout.addRow("Find what:", self.find_edit)
        form_layout.addRow("Replace with:", self.replace_edit)
        layout.addLayout(form_layout)

        options_layout = QHBoxLayout()
        self.case_sensitive_check = QCheckBox("Case sensitive")
        self.whole_word_check = QCheckBox("Match whole word")
        self.selected_only_check = QCheckBox("In selection only")
        self.selected_only_check.setEnabled(selection_exists)
        options_layout.addWidget(self.case_sensitive_check)
        options_layout.addWidget(self.whole_word_check)
        options_layout.addWidget(self.selected_only_check)
        layout.addLayout(options_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Replace All")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept(self):
        self.result = {
            "find": self.find_edit.text(), "replace": self.replace_edit.text(),
            "case": self.case_sensitive_check.isChecked(), "whole": self.whole_word_check.isChecked(),
            "selected_only": self.selected_only_check.isChecked()
        }
        super().accept()


class WildcardLoaderWorker(QObject):
    """Worker to load wildcard files in the background."""
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor):
        super().__init__()
        self.processor = processor

    @Slot()
    def run(self):
        try:
            wildcard_files = self.processor.get_wildcard_files()
            self.finished.emit({'success': True, 'files': wildcard_files})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

class WildcardContentLoaderWorker(QObject):
    """Worker to load the content of a single wildcard file."""
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor, filename: str):
        super().__init__()
        self.processor = processor
        self.filename = filename

    @Slot()
    def run(self):
        try:
            # This processor method is robust and handles .txt, .json, and broken JSON.
            data, is_broken = self.processor.get_wildcard_data_for_editing(self.filename)
            self.finished.emit({'success': True, 'data': data, 'is_broken': is_broken})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

class WildcardMergeWorker(QObject):
    """Worker to load and merge multiple wildcard files in the background."""
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor, filenames: List[str]):
        super().__init__()
        self.processor = processor
        self.filenames = filenames

    @Slot()
    def run(self):
        try:
            all_data = []
            for file_name in self.filenames:
                data, is_broken = self.processor.get_wildcard_data_for_editing(file_name)
                if is_broken:
                    raise Exception(f"Could not parse file for merging: {file_name}")
                all_data.append((file_name, data))
            
            merged_data = self._perform_merge(all_data)
            self.finished.emit({'success': True, 'data': merged_data})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

    def _perform_merge(self, all_data: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
        """Performs the logic of merging data from multiple wildcard files."""
        basenames = [os.path.splitext(name)[0] for name, _ in all_data]

        # Merge Descriptions
        merged_desc_parts = [f"--- {os.path.splitext(name)[0]} ---\n{data.get('description', f'Content from {name}')}" for name, data in all_data]
        merged_desc = f"Merged from {len(basenames)} files: {', '.join(basenames)}.\n\n" + "\n\n".join(merged_desc_parts)

        # Merge Choices (uniquely and intelligently)
        merged_choices_map: Dict[str, Any] = {}
        for _, data in all_data:
            for choice in data.get('choices', []):
                is_new_dict = isinstance(choice, dict)
                value = choice.get('value') if is_new_dict else choice
                if value is None: continue

                if value not in merged_choices_map:
                    merged_choices_map[value] = copy.deepcopy(choice)
                else:
                    existing_choice = merged_choices_map[value]
                    if not isinstance(existing_choice, dict): existing_choice = {'value': existing_choice}
                    new_choice_data = choice if is_new_dict else {'value': choice}

                    # Merge tags
                    existing_tags = set(existing_choice.get('tags', [])); new_tags = set(new_choice_data.get('tags', []))
                    if existing_tags or new_tags: existing_choice['tags'] = sorted(list(existing_tags | new_tags))

                    # Merge requires
                    existing_reqs = existing_choice.get('requires', {}); new_reqs = new_choice_data.get('requires', {})
                    if existing_reqs or new_reqs:
                        merged_reqs = copy.deepcopy(existing_reqs)
                        for key, value2 in new_reqs.items():
                            if key in merged_reqs:
                                value1 = merged_reqs[key]
                                set1 = set(value1) if isinstance(value1, list) else {value1}; set2 = set(value2) if isinstance(value2, list) else {value2}
                                merged_values = sorted(list(set1 | set2))
                                merged_reqs[key] = merged_values[0] if len(merged_values) == 1 else merged_values
                            else: merged_reqs[key] = value2
                        existing_choice['requires'] = merged_reqs
                    
                    # Merge includes
                    inc1 = existing_choice.get('includes'); inc2 = new_choice_data.get('includes')
                    s1 = " ".join([f"[{w}]" for w in inc1]) if isinstance(inc1, list) else (inc1 or ''); s2 = " ".join([f"[{w}]" for w in inc2]) if isinstance(inc2, list) else (inc2 or '')
                    combined_str = f"{s1} {s2}".strip()
                    if combined_str: existing_choice['includes'] = combined_str
                    merged_choices_map[value] = existing_choice
        
        # Merge Global Includes
        all_includes = set()
        for _, data in all_data:
            includes = data.get('includes')
            if not includes: continue
            if isinstance(includes, list): all_includes.update(includes)
            elif isinstance(includes, str): all_includes.update(re.findall(r'__([a-zA-Z0-9_.\s-]+?)__', includes)); all_includes.update(re.findall(r'\[([a-zA-Z0-9_.-]+?)\]', includes))

        merged_data = {"description": merged_desc, "choices": list(merged_choices_map.values())}
        if all_includes: merged_data['includes'] = sorted(list(all_includes))
        return merged_data

class WildcardManagerWindow(QDialog):
    """A Qt-based window for managing wildcard files."""

    def __init__(self, parent, processor: PromptProcessor, update_callback: Callable, initial_file: Optional[str] = None, initial_content: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Wildcard Manager (Qt)")
        self.processor = processor
        self.update_callback = update_callback
        self.all_wildcard_files: List[str] = []
        self.selected_wildcard_file: Optional[str] = None
        self.is_dirty = False

        self._create_widgets()
        self._connect_signals()
        self._start_loading()

        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning
        self.resize(1000, 700)

    def _create_widgets(self):
        self.main_layout = QHBoxLayout(self)
        
        # Main splitter for left (list) and right (editor) panes
        splitter = QSplitter(self)
        self.main_layout.addWidget(splitter)

        # --- Left Pane: File List and Actions ---
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        
        # Search bar
        search_frame = QGroupBox("Search")
        search_layout = QHBoxLayout(search_frame)
        self.search_edit = QLineEdit()
        search_layout.addWidget(self.search_edit)
        left_layout.addWidget(search_frame)

        # File list
        list_frame = QGroupBox("Wildcard Files")
        list_layout = QVBoxLayout(list_frame)
        self.file_list = QListWidget()
        loading_item = QListWidgetItem("Loading files...")
        loading_item.setFlags(loading_item.flags() & ~Qt.ItemIsSelectable)
        self.file_list.addItem(loading_item)
        list_layout.addWidget(self.file_list)
        left_layout.addWidget(list_frame)

        # Action buttons
        actions_frame = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_frame)
        self.new_button = QPushButton("New Wildcard File")
        self.merge_button = QPushButton("Merge Selected (2+)")
        self.merge_button.setEnabled(False)
        self.compare_button = QPushButton("Compare & Edit")
        self.archive_button = QPushButton("Archive Selected")
        self.archive_button.setEnabled(False)
        actions_layout.addWidget(self.new_button)
        actions_layout.addWidget(self.merge_button)
        actions_layout.addWidget(self.compare_button)
        actions_layout.addWidget(self.archive_button)
        actions_layout.addStretch()
        left_layout.addWidget(actions_frame)

        splitter.addWidget(left_pane)

        # --- Right Pane: Editor ---
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        
        self.editor_tabs = QTabWidget()
        
        # Structured Editor Tab
        structured_tab = QWidget()
        structured_layout = QVBoxLayout(structured_tab) # Layout for the tab
        self.structured_editor = WildcardEditor(
            self.processor, self,
            suggestion_callback=self._suggest_choices_with_ai,
            autotag_callback=self._autotag_choices_with_ai,
            enrich_callback=self._enrich_choices_with_ai,
            find_replace_callback=self._find_and_replace,
            find_duplicates_callback=self._find_duplicates
        )
        raw_text_tab = QWidget()
        raw_text_layout = QVBoxLayout(raw_text_tab) # Layout for the tab
        self.raw_text_editor = QTextEdit()
        raw_text_layout.addWidget(self.raw_text_editor)
        self.editor_tabs.addTab(raw_text_tab, "Raw Text Editor")

        right_layout.addWidget(self.editor_tabs)
        structured_layout.addWidget(self.structured_editor)
        self.editor_tabs.addTab(structured_tab, "Structured Editor")


        # --- NEW: Save button for the editor ---
        self.save_button = QPushButton("Save Changes")
        self.save_button.setEnabled(False)
        right_layout.addWidget(self.save_button)

        splitter.addWidget(right_pane)

        splitter.setSizes([300, 700])

    def _connect_signals(self):
        self.search_edit.textChanged.connect(self._filter_wildcards)
        self.file_list.itemDoubleClicked.connect(self._on_file_selected)
        self.save_button.clicked.connect(self._on_save_file)
        self.structured_editor.description_entry.textChanged.connect(self._mark_dirty)
        self.structured_editor.includes_text.textChanged.connect(self._mark_dirty)
        self.structured_editor.tree.itemChanged.connect(self._mark_dirty)
        self.raw_text_editor.textChanged.connect(self._mark_dirty)
        self.file_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.archive_button.clicked.connect(self._on_archive_selected)
        self.merge_button.clicked.connect(self._on_merge_selected)
        self.compare_button.clicked.connect(self._on_compare_and_edit)
        self.file_list.itemSelectionChanged.connect(self._on_selection_changed) # Ensure this is connected
        self.new_button.clicked.connect(self._on_new_file)

    def _start_loading(self):
        """Starts the background thread to load wildcard files."""
        self.thread = QThread(self)
        self.worker = WildcardLoaderWorker(self.processor)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_load_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

    @Slot(dict)
    def _on_load_finished(self, result: dict):
        """Slot to receive the list of wildcard files."""
        if result['success']:
            self.all_wildcard_files = result.get('files', [])
            self.file_list.clear()
            if self.all_wildcard_files:
                self.file_list.addItems(self.all_wildcard_files)
            else:
                no_files_item = QListWidgetItem("No wildcard files found.")
                no_files_item.setTextAlignment(Qt.AlignCenter)
                no_files_item.setFlags(no_files_item.flags() & ~Qt.ItemIsSelectable)
                self.file_list.addItem(no_files_item)
        else:
            print(f"Error loading wildcard files: {result['error']}")
            self.file_list.clear()
            error_item = QListWidgetItem("Error loading files.")
            error_item.setFlags(error_item.flags() & ~Qt.ItemIsSelectable)
            error_item.setTextAlignment(Qt.AlignCenter)
            self.file_list.addItem(error_item)

    @Slot(str)
    def _filter_wildcards(self, search_text: str):
        """Filters the list of wildcards based on the search input."""
        search_term = search_text.lower()
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            is_visible = search_term in item.text().lower()
            item.setHidden(not is_visible)

    @Slot()
    def _on_selection_changed(self):
        """Updates button states based on the number of selected files."""
        selection_count = len(self.file_list.selectedItems())
        self.merge_button.setEnabled(selection_count >= 2)
        self.archive_button.setEnabled(selection_count >= 1)
        self.compare_button.setEnabled(selection_count <= 2)

    @Slot(QListWidgetItem)
    def _on_file_selected(self, item: QListWidgetItem):
        """Handles selection of a file in the list, prompting to save if dirty."""
        if self.is_dirty:
            reply = QMessageBox.question(self, "Unsaved Changes", "You have unsaved changes. Do you want to save them before switching?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save:
                self._on_save_file()
            elif reply == QMessageBox.StandardButton.Cancel:
                # TODO: Revert selection in listbox
                return

        """Loads the content of the selected file into the editor panes."""
        filename = item.text()
        self.selected_wildcard_file = filename
        
        # Start a background worker to load the file content
        self.content_thread = QThread(self)
        self.content_worker = WildcardContentLoaderWorker(self.processor, filename)
        self.content_worker.moveToThread(self.content_thread)

        self.content_thread.started.connect(self.content_worker.run)
        self.content_worker.finished.connect(self._on_content_load_finished)
        self.content_worker.finished.connect(self.content_thread.quit)
        self.content_worker.finished.connect(self.content_worker.deleteLater)
        self.content_thread.finished.connect(self.content_thread.deleteLater)

        self.content_thread.start()
        self.structured_editor.set_data({})
        self.raw_text_editor.setPlainText("Loading content...")

    @Slot(dict)
    def _on_content_load_finished(self, result: dict):
        """Slot to receive the loaded wildcard content."""
        if not result['success']:
            print(f"Error loading {self.selected_wildcard_file}: {result['error']}")
            # TODO: Show error in UI
            return

        data = result.get('data')
        is_broken = result.get('is_broken', False)

        if is_broken:
            self.structured_editor.set_data({})
            self.raw_text_editor.setPlainText(data)
            self.editor_tabs.setCurrentWidget(self.raw_text_editor.parentWidget())
        else:
            self.structured_editor.set_data(data)
            pretty_json = json.dumps(data, indent=2)
            self.raw_text_editor.setPlainText(pretty_json)
            self.editor_tabs.setCurrentWidget(self.structured_editor.parentWidget())

        # Clear dirty state and update window title after loading new content
        self.is_dirty = False
        self.save_button.setEnabled(False)
        self.setWindowTitle("Wildcard Manager (Qt)")

        # --- NEW: Enable AI buttons now that a file is loaded ---
        self.structured_editor.suggest_button.setEnabled(True)
        self.structured_editor.autotag_button.setEnabled(True)
        self.structured_editor.enrich_button.setEnabled(bool(data.get('choices')))
    @Slot()
    def _on_archive_selected(self):
        """Archives the selected wildcard files."""
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select one or more wildcard files to archive.")
            return

        files_to_archive = [item.text() for item in selected_items]

        if len(files_to_archive) == 1:
            confirmation_message = f"Are you sure you want to archive '{files_to_archive[0]}'?"
        else:
            confirmation_message = f"Are you sure you want to archive the following {len(files_to_archive)} files?\n\n" + "\n".join(files_to_archive)

        reply = QMessageBox.question(
            self,
            "Confirm Archive",
            confirmation_message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.No:
            return

        archived_count = 0
        errors = []
        for filename in files_to_archive:
            try:
                self.processor.archive_wildcard_file(filename)
                archived_count += 1
                self.update_callback(filename) # Notify main window that a file was archived
                if self.selected_wildcard_file == filename:
                    self._clear_editor_view() # Clear editor if the currently viewed file was archived
            except Exception as e:
                errors.append(f"Failed to archive '{filename}': {e}")

        if errors:
            QMessageBox.critical(self, "Archive Errors", "\n".join(errors))
        
        if archived_count > 0:
            QMessageBox.information(self, "Archive Complete", f"Successfully archived {archived_count} file(s).")
            self._start_loading() # Reload the list to reflect changes

    def _clear_editor_view(self):
        """Clears the content of the editor panes and resets state."""
        self.structured_editor.set_data({})
        self.raw_text_editor.setPlainText("")
        self.selected_wildcard_file = None
        self.is_dirty = False
        self.save_button.setEnabled(False)
        self.setWindowTitle("Wildcard Manager (Qt)")
        self.editor_tabs.setCurrentIndex(0) # Go back to structured editor tab
        self.structured_editor.suggest_button.setEnabled(False)
        self.structured_editor.autotag_button.setEnabled(False)
        self.structured_editor.enrich_button.setEnabled(False)

    @Slot()
    def _on_merge_selected(self):
        """Merges selected wildcard files into a new one."""
        selected_items = self.file_list.selectedItems()
        if len(selected_items) < 2:
            QMessageBox.warning(self, "Merge Wildcards", "Please select at least two wildcard files to merge.")
            return

        files_to_merge = [item.text() for item in selected_items]

        new_filename_base, ok = QInputDialog.getText(self, "Merge Wildcards", "Enter a name for the new merged wildcard file (without extension):")
        if not ok or not new_filename_base:
            return

        new_filename = f"{new_filename_base}.json"
        if new_filename in self.all_wildcard_files:
            QMessageBox.warning(self, "File Exists", f"A wildcard file named '{new_filename}' already exists. Please choose a different name.")
            return

        # Disable buttons and show progress
        self.merge_button.setEnabled(False)
        self.new_button.setEnabled(False)
        self.archive_button.setEnabled(False)
        self.compare_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)

        # Start background worker
        self.merge_thread = QThread(self)
        self.merge_worker = WildcardMergeWorker(self.processor, files_to_merge)
        self.merge_worker.moveToThread(self.merge_thread)

        self.merge_thread.started.connect(self.merge_worker.run)
        self.merge_worker.finished.connect(lambda result: self._on_merge_finished(result, new_filename))
        self.merge_worker.finished.connect(self.merge_thread.quit)
        self.merge_worker.finished.connect(self.merge_worker.deleteLater)
        self.merge_thread.finished.connect(self.merge_thread.deleteLater)

        self.merge_thread.start()

    @Slot(dict, str)
    def _on_merge_finished(self, result: dict, new_filename: str):
        """Slot to handle the result of the wildcard merge operation."""
        # Re-enable buttons and restore cursor
        self.new_button.setEnabled(True) # This one is not managed by selection changed
        QApplication.restoreOverrideCursor()
        # Other buttons (merge, archive, compare) will have their state updated
        # automatically by _on_selection_changed after _start_loading() repopulates the list.

        if result['success']:
            merged_data = result.get('data')
            try:
                content_str = json.dumps(merged_data, indent=2)
                self.processor.save_wildcard_content(new_filename, content_str)
                self.update_callback(new_filename) # Notify main window
                QMessageBox.information(self, "Merge Successful", f"Successfully merged files into '{new_filename}'.")
                self._start_loading() # Reload the list to reflect changes
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Could not save merged file '{new_filename}':\n{e}")
        else:
            QMessageBox.critical(self, "Merge Error", f"An error occurred during merge:\n{result['error']}")

    @Slot()
    def _on_merge_selected(self):
        """Merges selected wildcard files into a new one."""
        selected_items = self.file_list.selectedItems()
        if len(selected_items) < 2:
            QMessageBox.warning(self, "Merge Wildcards", "Please select at least two wildcard files to merge.")
            return

        files_to_merge = [item.text() for item in selected_items]

        new_filename_base, ok = QInputDialog.getText(self, "Merge Wildcards", "Enter a name for the new merged wildcard file (without extension):")
        if not ok or not new_filename_base:
            return

        new_filename = f"{new_filename_base}.json"
        if new_filename in self.all_wildcard_files:
            QMessageBox.warning(self, "File Exists", f"A wildcard file named '{new_filename}' already exists. Please choose a different name.")
            return

        # Disable buttons and show progress
        self.merge_button.setEnabled(False)
        self.new_button.setEnabled(False)
        self.archive_button.setEnabled(False)
        self.compare_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)

        # Start background worker
        self.merge_thread = QThread(self)
        self.merge_worker = WildcardMergeWorker(self.processor, files_to_merge)
        self.merge_worker.moveToThread(self.merge_thread)

        self.merge_thread.started.connect(self.merge_worker.run)
        self.merge_worker.finished.connect(lambda result: self._on_merge_finished(result, new_filename))
        self.merge_worker.finished.connect(self.merge_thread.quit)
        self.merge_worker.finished.connect(self.merge_worker.deleteLater)
        self.merge_thread.finished.connect(self.merge_thread.deleteLater)

        self.merge_thread.start()

    @Slot(dict, str)
    def _on_merge_finished(self, result: dict, new_filename: str):
        """Slot to handle the result of the wildcard merge operation."""
        # Re-enable buttons and restore cursor
        self.new_button.setEnabled(True) # This one is not managed by selection changed
        QApplication.restoreOverrideCursor()
        # Other buttons (merge, archive, compare) will have their state updated
        # automatically by _on_selection_changed after _start_loading() repopulates the list.

        if result['success']:
            merged_data = result.get('data')
            try:
                content_str = json.dumps(merged_data, indent=2)
                self.processor.save_wildcard_content(new_filename, content_str)
                self.update_callback(new_filename) # Notify main window
                QMessageBox.information(self, "Merge Successful", f"Successfully merged files into '{new_filename}'.")
                
                # Add a pending selection to be handled after the list reloads
                self._pending_selection_filename = new_filename
                self._start_loading() # Reload the list to reflect changes

            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Could not save merged file '{new_filename}':\n{e}")
        else:
            QMessageBox.critical(self, "Merge Error", f"An error occurred during merge:\n{result['error']}")

    @Slot()
    def _on_compare_and_edit(self):
        """Opens the MultiWildcardEditorWindow for selected files."""
        selected_items = self.file_list.selectedItems()
        file1 = None
        file2 = None

        if len(selected_items) == 1:
            file1 = selected_items[0].text()
            # Ask user for a second file to compare with
            all_files_except_selected = [f for f in self.all_wildcard_files if f != file1]
            if not all_files_except_selected:
                QMessageBox.information(self, "Compare & Edit", "No other wildcard files available to compare with.")
                return
            
            # Use QInputDialog.getItem for selecting the second file
            file2, ok = QInputDialog.getItem(self, "Compare & Edit", f"Select a second file to compare with '{file1}':", all_files_except_selected, 0, False)
            if not ok or not file2:
                return
        elif len(selected_items) == 2:
            file1 = selected_items[0].text()
            file2 = selected_items[1].text()
        elif len(selected_items) > 2:
            QMessageBox.warning(self, "Compare & Edit", "Please select at most two wildcard files for comparison.")
            return
        # If 0 selected, open with (None, None) allowing user to select from combos

        # Check for unsaved changes before opening another window
        if self.is_dirty:
            reply = QMessageBox.question(self, "Unsaved Changes", "You have unsaved changes in the current editor. Do you want to save them before opening the comparison tool?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save:
                self._on_save_file()
                if self.is_dirty: # If save failed, don't proceed
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        
        # Open the MultiWildcardEditorWindow
        self.multi_editor_window = MultiWildcardEditorWindow(self, self.processor, file1, file2, self._on_multi_editor_update)
        self.multi_editor_window.show()

    @Slot()
    def _mark_dirty(self):
        """Marks the current file as having unsaved changes."""
        if not self.is_dirty:
            self.is_dirty = True
            self.save_button.setEnabled(True)
            self.setWindowTitle(self.windowTitle() + "*")

    @Slot()
    def _on_save_file(self):
        """Saves the changes from the active editor to the selected wildcard file."""
        if not self.selected_wildcard_file:
            QMessageBox.warning(self, "No File Selected", "There is no file selected to save.")
            return

        try:
            current_tab_widget = self.editor_tabs.currentWidget()
            
            if self.raw_text_editor.parentWidget() == current_tab_widget:
                content_str = self.raw_text_editor.toPlainText()
                try:
                    # Validate JSON before saving from raw editor
                    json.loads(content_str)
                except json.JSONDecodeError as e:
                    QMessageBox.critical(self, "Invalid JSON", f"The content is not valid JSON and cannot be saved.\n\nError: {e}")
                    return
            else:
                # Get data from structured editor and convert to JSON string
                data = self.structured_editor.get_data()
                content_str = json.dumps(data, indent=2)

            self.processor.save_wildcard_content(self.selected_wildcard_file, content_str)
            
            # Update UI state after successful save
            self.is_dirty = False
            self.save_button.setEnabled(False)
            self.setWindowTitle("Wildcard Manager (Qt)")
            
            # Notify the main application that a file has been updated
            self.update_callback(self.selected_wildcard_file)
            
            QMessageBox.information(self, "Save Successful", f"'{self.selected_wildcard_file}' has been saved.")

        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save file '{self.selected_wildcard_file}':\n{e}")

    @Slot()
    def _on_new_file(self):
        """Handles the 'New Wildcard File' button click."""
        filename, ok = QInputDialog.getText(self, "New Wildcard File", "Enter new wildcard filename (without extension):")
        if ok and filename:
            # Ensure it has a .json extension for the processor
            if not filename.endswith('.json'):
                filename_with_ext = f"{filename}.json"
            else:
                filename_with_ext = filename

            # Check if file already exists
            if filename_with_ext in self.all_wildcard_files:
                QMessageBox.warning(self, "File Exists", f"A wildcard file named '{filename_with_ext}' already exists.")
                return

            # Create default content
            default_content = {
                "description": f"New wildcard file for {filename}",
                "choices": ["Sample choice 1", "Sample choice 2"]
            }
            content_str = json.dumps(default_content, indent=2)

            try:
                self.processor.save_wildcard_content(filename_with_ext, content_str)
                self.update_callback(filename_with_ext) # Notify main window
                self._start_loading() # Reload the list in this window
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not create new wildcard file:\n{e}")

    def _on_multi_editor_update(self, modified_files: Optional[List[str]] = None):
        """Callback for when the MultiWildcardEditorWindow saves changes."""
        # Reload the main list of files
        self._start_loading()
        # If the currently selected file was modified, reload its content
        if self.selected_wildcard_file and modified_files and self.selected_wildcard_file in modified_files:
            # This will trigger a content load for the currently selected file
            # Need to find the item and call _on_file_selected
            items = self.file_list.findItems(self.selected_wildcard_file, Qt.MatchExactly)
            if items:
                self.file_list.setCurrentItem(items[0])
                self._on_file_selected(items[0])
        
        # Also notify the main GUI app
        if modified_files:
            for f in modified_files:
                self.update_callback(f)
        else:
            self.update_callback() # Generic update if we don't know specifics
    def closeEvent(self, event: QCloseEvent):
        """Overrides the default close event to check for unsaved changes."""
        if self.is_dirty:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save them before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Save:
                self._on_save_file()
                # If save was successful, is_dirty will be False.
                if self.is_dirty:
                    event.ignore() # Save failed, so don't close.
                else:
                    event.accept() # Save was successful, close.
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
            else: # Discard
                event.accept()
        else:
            event.accept()