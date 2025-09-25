"""A Qt dialog to select multiple prompts from history."""

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QListWidget, QLineEdit, QDialogButtonBox,
    QAbstractItemView
)
from PySide6.QtCore import Slot
from typing import List

from core.prompt_processor import PromptProcessor

class PromptSelectionDialog(QDialog):
    """A dialog to select multiple prompts from history."""

    def __init__(self, parent, processor: PromptProcessor):
        super().__init__(parent)
        self.setWindowTitle("Select Prompts from History")
        self.processor = processor
        self.all_prompts: List[str] = []
        self.selected_prompts: List[str] = []

        self._create_widgets()
        self._connect_signals()
        self._load_history()
        self.resize(600, 500)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        layout = QVBoxLayout(self)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter prompts...")
        layout.addWidget(self.search_edit)

        self.prompt_list = QListWidget()
        self.prompt_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.prompt_list)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.search_edit.textChanged.connect(self._filter_prompts)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)

    def _load_history(self):
        history = self.processor.get_all_history_across_workflows()
        prompts = {entry.get('enhanced', {}).get('prompt', entry.get('original_prompt', '')).strip() for entry in history if entry.get('enhanced', {}).get('prompt') or entry.get('original_prompt')}
        self.all_prompts = sorted(list(prompts))
        self.prompt_list.addItems(self.all_prompts)

    @Slot(str)
    def _filter_prompts(self, text: str):
        search_term = text.lower()
        for i in range(self.prompt_list.count()):
            item = self.prompt_list.item(i)
            item.setHidden(search_term not in item.text().lower())

    @Slot()
    def _on_accept(self):
        self.selected_prompts = [item.text() for item in self.prompt_list.selectedItems()]
        self.accept()