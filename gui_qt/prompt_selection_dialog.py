"""A Qt dialog to select multiple prompts from history."""

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLineEdit, QDialogButtonBox,
    QAbstractItemView
)
from PySide6.QtCore import Slot
from typing import List

from core.prompt_processor import PromptProcessor
from .custom_widgets import SmoothListWidget

import os

class PromptSelectionDialog(QDialog):
    """A dialog to select multiple prompts from history."""

    def __init__(self, parent, processor: PromptProcessor):
        super().__init__(parent)
        self.setWindowTitle("Select Prompts from History")
        self.processor = processor
        self.all_prompts_data: List[Dict[str, Any]] = []
        self.selected_prompts: List[Dict[str, Any]] = []

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

        self.prompt_list = SmoothListWidget()
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
        self.all_prompts_data = []
        processed_prompts = set()

        for entry in history:
            image_path = None
            if entry.get('original_images'):
                image_path = entry['original_images'][0].get('image_path')
                if image_path and not os.path.isabs(image_path):
                    image_path = os.path.join(self.processor.history_manager.history_dir, image_path)

            # Original Prompt
            original_prompt = entry.get('original_prompt', '').strip()
            if original_prompt and original_prompt not in processed_prompts:
                self.all_prompts_data.append({'prompt': original_prompt, 'image_path': image_path, 'version': 'Original'})
                processed_prompts.add(original_prompt)

            # Enhanced Prompt
            enhanced_prompt_data = entry.get('enhanced', {})
            enhanced_prompt = enhanced_prompt_data.get('prompt', '').strip()
            if enhanced_prompt and enhanced_prompt not in processed_prompts:
                self.all_prompts_data.append({'prompt': enhanced_prompt, 'image_path': image_path, 'version': 'Enhanced'})
                processed_prompts.add(enhanced_prompt)

            # Variations
            variations = enhanced_prompt_data.get('variations', [])
            for i, variation in enumerate(variations):
                variation_prompt = variation.get('prompt', '').strip()
                if variation_prompt and variation_prompt not in processed_prompts:
                    self.all_prompts_data.append({'prompt': variation_prompt, 'image_path': image_path, 'version': f'Variation {i+1}'})
                    processed_prompts.add(variation_prompt)

        self.all_prompts_data.sort(key=lambda x: x['prompt'])
        self.prompt_list.addItems([f"[{d['version']}] {d['prompt']}" for d in self.all_prompts_data])

    @Slot(str)
    def _filter_prompts(self, text: str):
        search_term = text.lower()
        for i in range(self.prompt_list.count()):
            item = self.prompt_list.item(i)
            item.setHidden(search_term not in item.text().lower())

    @Slot()
    def _on_accept(self):
        selected_items = self.prompt_list.selectedItems()
        self.selected_prompts = []
        for item in selected_items:
            # Find the corresponding data in all_prompts_data
            for data in self.all_prompts_data:
                if f"[{data['version']}] {data['prompt']}" == item.text():
                    self.selected_prompts.append(data)
                    break
        self.accept()