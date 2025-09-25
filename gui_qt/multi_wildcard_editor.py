"""The Qt-based side-by-side wildcard editor window."""

import json
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QPushButton, QSplitter, QWidget, QGroupBox, QMessageBox
)
from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QCloseEvent
from typing import Callable, Optional, List, Any

from core.prompt_processor import PromptProcessor
from .wildcard_editor_widget import WildcardEditor


class MultiWildcardEditorWindow(QDialog):
    """A Qt-based dialog for side-by-side editing of two wildcard files."""

    def __init__(self, parent, processor: PromptProcessor, file1: Optional[str], file2: Optional[str], update_callback: Callable):
        super().__init__(parent)
        self.setWindowTitle("Compare & Edit Wildcards (Qt)")
        self.processor = processor
        self.update_callback = update_callback
        self.file1_name = file1
        self.file2_name = file2
        self.editor1_dirty = False
        self.editor2_dirty = False

        self.all_files = sorted(self.processor.get_wildcard_files(), key=str.lower)

        self._create_widgets()
        self._connect_signals()

        self._load_file_into_pane(1, self.file1_name)
        self._load_file_into_pane(2, self.file2_name)

        self.resize(1200, 800)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # --- Editor 1 (Left) ---
        self.frame1 = QGroupBox(self.file1_name or "Left Pane")
        layout1 = QVBoxLayout(self.frame1)
        self.combo1 = QComboBox()
        self.combo1.addItems(["(None)"] + self.all_files)
        if self.file1_name: self.combo1.setCurrentText(self.file1_name)
        layout1.addWidget(self.combo1)
        self.editor1 = WildcardEditor(self.processor, self)
        layout1.addWidget(self.editor1)
        splitter.addWidget(self.frame1)

        # --- Editor 2 (Right) ---
        self.frame2 = QGroupBox(self.file2_name or "Right Pane")
        layout2 = QVBoxLayout(self.frame2)
        self.combo2 = QComboBox()
        self.combo2.addItems(["(None)"] + self.all_files)
        if self.file2_name: self.combo2.setCurrentText(self.file2_name)
        layout2.addWidget(self.combo2)
        self.editor2 = WildcardEditor(self.processor, self)
        layout2.addWidget(self.editor2)
        splitter.addWidget(self.frame2)

        splitter.setSizes([600, 600])

        # --- Bottom Buttons ---
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.save_button = QPushButton("Save All & Close")
        self.save_button.setStyleSheet("font-weight: bold;")
        button_layout.addWidget(self.save_button)
        close_button = QPushButton("Close")
        button_layout.addWidget(close_button)
        main_layout.addLayout(button_layout)

        # Connect the close button to the window's close method
        close_button.clicked.connect(self.close)

    def _connect_signals(self):
        self.combo1.currentTextChanged.connect(lambda text: self._on_file_switch(1, text))
        self.combo2.currentTextChanged.connect(lambda text: self._on_file_switch(2, text))
        self.save_button.clicked.connect(self._save_all)

        # Mark dirty when any editor content changes
        self.editor1.description_entry.textChanged.connect(lambda: self._set_dirty(1))
        self.editor1.includes_text.textChanged.connect(lambda: self._set_dirty(1))
        self.editor1.tree.itemChanged.connect(lambda: self._set_dirty(1))
        self.editor2.description_entry.textChanged.connect(lambda: self._set_dirty(2))
        self.editor2.includes_text.textChanged.connect(lambda: self._set_dirty(2))
        self.editor2.tree.itemChanged.connect(lambda: self._set_dirty(2))

    def _set_dirty(self, editor_num: int):
        if editor_num == 1: self.editor1_dirty = True
        else: self.editor2_dirty = True
        self.setWindowTitle("Compare & Edit Wildcards (Qt)*")

    def _on_file_switch(self, editor_num: int, new_filename: str):
        is_dirty = self.editor1_dirty if editor_num == 1 else self.editor2_dirty
        old_filename = self.file1_name if editor_num == 1 else self.file2_name

        if is_dirty:
            reply = QMessageBox.question(self, "Unsaved Changes", f"You have unsaved changes in '{old_filename}'. Save them before switching?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save:
                if not self._save_pane(editor_num):
                    # Revert dropdown if save failed
                    combo = self.combo1 if editor_num == 1 else self.combo2
                    combo.setCurrentText(old_filename)
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                combo = self.combo1 if editor_num == 1 else self.combo2
                combo.setCurrentText(old_filename)
                return

        self._load_file_into_pane(editor_num, new_filename if new_filename != "(None)" else None)

    def _load_file_into_pane(self, editor_num: int, filename: Optional[str]):
        editor = self.editor1 if editor_num == 1 else self.editor2
        frame = self.frame1 if editor_num == 1 else self.frame2

        if editor_num == 1: self.file1_name = filename
        else: self.file2_name = filename

        frame.setTitle(filename or ("Left Pane" if editor_num == 1 else "Right Pane"))

        if not filename:
            editor.set_data({})
            return

        try:
            data, is_broken = self.processor.get_wildcard_data_for_editing(filename)
            if is_broken:
                QMessageBox.warning(self, "Load Warning", f"Could not parse {filename}. It may be corrupted. Loading as empty.")
                editor.set_data({})
            else:
                editor.set_data(data)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Could not load {filename}:\n{e}")
            editor.set_data({})

        if editor_num == 1: self.editor1_dirty = False
        else: self.editor2_dirty = False

        if not self.editor1_dirty and not self.editor2_dirty:
            self.setWindowTitle("Compare & Edit Wildcards (Qt)")

    def _save_pane(self, editor_num: int) -> bool:
        editor = self.editor1 if editor_num == 1 else self.editor2
        filename = self.file1_name if editor_num == 1 else self.file2_name
        if not filename: return True # Nothing to save

        try:
            data = editor.get_data()
            content = json.dumps(data, indent=2)
            self.processor.save_wildcard_content(filename, content)
            
            if editor_num == 1: self.editor1_dirty = False
            else: self.editor2_dirty = False

            if not self.editor1_dirty and not self.editor2_dirty:
                self.setWindowTitle("Compare & Edit Wildcards (Qt)")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save {filename}:\n{e}")
            return False

    @Slot()
    def _save_all(self):
        save1_ok, save2_ok = True, True
        if self.editor1_dirty:
            save1_ok = self._save_pane(1)
        if self.editor2_dirty:
            save2_ok = self._save_pane(2)

        if save1_ok and save2_ok:
            modified_files = []
            if self.file1_name and self.editor1_dirty: modified_files.append(self.file1_name)
            if self.file2_name and self.editor2_dirty: modified_files.append(self.file2_name)
            self.update_callback(modified_files)
            QMessageBox.information(self, "Save Complete", "All changes have been saved.")
            self.accept() # Closes the dialog with an OK result

    def closeEvent(self, event: QCloseEvent):
        """Overrides the default close event to check for unsaved changes."""
        if self.editor1_dirty or self.editor2_dirty:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save them before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Save:
                self._save_all()
                # If save was successful, accept() is called inside _save_all.
                # If it failed, the window should stay open, so we ignore the event.
                event.ignore()
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
            else: # Discard
                event.accept()
        else:
            event.accept()