"""Custom dialogs for setting per-model overrides for image generation."""

import copy
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QDoubleSpinBox,
    QGroupBox,
    QHeaderView,
    QSplitter,
    QListWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from core.prompt_processor import PromptProcessor
from .custom_widgets import SmoothListWidget, SmoothTextEdit


class PerModelNegativePromptDialog(QDialog):
    """A dialog to set a different negative prompt for each selected model."""

    def __init__(self, parent, processor: PromptProcessor, model_names: List[str], existing_overrides: Dict[str, str], default_prompt: str):
        super().__init__(parent)
        self.setWindowTitle("Per-Model Negative Prompts")
        self.processor = processor
        self.model_names = model_names
        self.default_prompt = default_prompt
        self.temp_overrides = copy.deepcopy(existing_overrides)
        self.negative_prompts = self.processor.get_available_negative_prompts()
        self.model_list: Optional[SmoothListWidget] = None
        self.editor: Optional[QTextEdit] = None
        self.combo: Optional[QComboBox] = None
        self.current_model_name: Optional[str] = None

        self._create_widgets()
        self.resize(800, 500)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

        if self.model_names:
            self.model_list.setCurrentRow(0)

    def _create_widgets(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # --- Left Pane: Model List ---
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        self.model_list = SmoothListWidget()
        self.model_list.addItems(self.model_names)
        self.model_list.currentItemChanged.connect(self._on_model_select)
        left_layout.addWidget(self.model_list)
        splitter.addWidget(left_pane)

        # --- Right Pane: Editor ---
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        self.editor_group = QGroupBox("Negative Prompt for Model")
        editor_group_layout = QVBoxLayout(self.editor_group)

        preset_layout = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.addItem("Custom")
        for p in self.negative_prompts:
            self.combo.addItem(p['name'], p['prompt'])
        preset_layout.addWidget(self.combo)
        editor_group_layout.addLayout(preset_layout)

        self.editor = SmoothTextEdit()
        editor_group_layout.addWidget(self.editor)
        right_layout.addWidget(self.editor_group)
        splitter.addWidget(right_pane)

        splitter.setSizes([250, 550])

        # Connect signals
        self.combo.currentTextChanged.connect(self._on_negative_prompt_preset_selected)
        self.editor.textChanged.connect(self._on_negative_prompt_text_changed)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_model_select(self, current: QListWidgetItem, previous: QListWidgetItem):
        # Save changes for the previously selected model
        if previous:
            prev_model_name = previous.text()
            self.temp_overrides[prev_model_name] = self.editor.toPlainText().strip()

        # Load data for the newly selected model
        if current:
            self.current_model_name = current.text()
            self.editor_group.setTitle(f"Negative Prompt for: {self.current_model_name}")
            
            # Block signals while we programmatically set the text
            self.editor.blockSignals(True)
            prompt_text = self.temp_overrides.get(self.current_model_name, self.default_prompt)
            self.editor.setPlainText(prompt_text)
            self.editor.blockSignals(False)
            
            # Sync the combobox to the new text
            self._sync_combo_to_text(prompt_text)

    def _on_accept(self):
        # Save the currently displayed editor content before accepting
        if self.current_model_name:
            self.temp_overrides[self.current_model_name] = self.editor.toPlainText().strip()
        
        # Filter out any empty overrides to keep the final dictionary clean
        self.result = {model: prompt for model, prompt in self.temp_overrides.items() if prompt}
        self.accept()

    def _on_negative_prompt_preset_selected(self, preset_name: str):
        if preset_name == "Custom":
            return
        if not self.combo or not self.editor:
            return

        index = self.combo.findText(preset_name)
        if index != -1:
            prompt_text = self.combo.itemData(index)
            self.editor.setPlainText(prompt_text)

    def _on_negative_prompt_text_changed(self):
        if not self.editor:
            return
        current_text = self.editor.toPlainText().strip()
        self._sync_combo_to_text(current_text)

    def _sync_combo_to_text(self, text: str):
        if not self.combo:
            return
        current_text = text.strip()
        matching_preset = next((p['name'] for p in self.negative_prompts if p['prompt'].strip() == current_text), None)
        
        self.combo.blockSignals(True)
        self.combo.setCurrentText(matching_preset or "Custom")
        self.combo.blockSignals(False)


class PerModelLoraDialog(QDialog):
    """A dialog to set a different LoRA stack for each selected model."""

    def __init__(self, parent, processor, model_names: List[str], all_loras: List[Dict], global_loras: List[Dict], existing_overrides: Dict[str, List[Dict]]):
        super().__init__(parent)
        self.setWindowTitle("Per-Model LoRAs")
        self.processor = processor
        self.model_names = model_names
        self.all_loras = sorted(all_loras, key=lambda x: x.get('name', '').lower())
        self.global_loras = global_loras
        self.temp_overrides = copy.deepcopy(existing_overrides)
        self.result: Optional[Dict[str, List[Dict]]] = None

        # UI Widgets
        self.model_list: Optional[SmoothListWidget] = None
        self.lora_tree: Optional[QTreeWidget] = None
        self.editor_group: Optional[QGroupBox] = None
        self.current_model_name: Optional[str] = None

        self._create_widgets()
        self.resize(800, 600)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

        if self.model_names:
            self.model_list.setCurrentRow(0)

    def _create_widgets(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # --- Left Pane: Model List ---
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        self.model_list = SmoothListWidget()
        self.model_list.addItems(self.model_names)
        self.model_list.currentItemChanged.connect(self._on_model_select)
        left_layout.addWidget(self.model_list)
        splitter.addWidget(left_pane)

        # --- Right Pane: LoRA Tree ---
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        self.editor_group = QGroupBox("LoRAs for Model")
        editor_group_layout = QVBoxLayout(self.editor_group)

        self.lora_tree = QTreeWidget()
        self.lora_tree.setHeaderLabels(["LoRA", "Weight"])
        self.lora_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.lora_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        editor_group_layout.addWidget(self.lora_tree)
        right_layout.addWidget(self.editor_group)
        splitter.addWidget(right_pane)

        splitter.setSizes([250, 550])

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_model_select(self, current: QListWidgetItem, previous: QListWidgetItem):
        # Save changes for the previously selected model
        if previous:
            prev_model_name = previous.text()
            self.temp_overrides[prev_model_name] = self._get_loras_from_tree(self.lora_tree)

        # Load data for the newly selected model
        if current:
            self.current_model_name = current.text()
            self.editor_group.setTitle(f"LoRAs for: {self.current_model_name}")
            selected_loras = self.temp_overrides.get(self.current_model_name, self.global_loras)
            self._populate_lora_tree(self.lora_tree, selected_loras)

    def _populate_lora_tree(self, tree: QTreeWidget, selected_loras: List[Dict]):
        tree.clear()
        selected_lora_map = {lora_item['lora_object']['name']: lora_item['weight'] for lora_item in selected_loras}

        for lora_data in self.all_loras:
            lora_name = lora_data['name']
            tree_item = QTreeWidgetItem(tree, [lora_name])
            tree_item.setFlags(tree_item.flags() | Qt.ItemIsUserCheckable)
            tree_item.setData(0, Qt.ItemDataRole.UserRole, lora_data)

            is_checked = lora_name in selected_lora_map
            tree_item.setCheckState(0, Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)

            spin_box = QDoubleSpinBox()
            spin_box.setRange(0.0, 2.0)
            spin_box.setSingleStep(0.1)
            spin_box.setValue(selected_lora_map.get(lora_name, 0.75))
            tree.setItemWidget(tree_item, 1, spin_box)
        
        QTimer.singleShot(0, lambda: tree.resizeColumnToContents(1))

    def _on_accept(self):
        # Save the currently displayed tree content before accepting
        if self.current_model_name:
            self.temp_overrides[self.current_model_name] = self._get_loras_from_tree(self.lora_tree)
        
        self.result = self.temp_overrides
        self.accept()

    def _get_loras_from_tree(self, tree: QTreeWidget) -> List[Dict[str, Any]]:
        """Extracts the selected LoRAs and their weights from a QTreeWidget."""
        selected_for_model = []
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                lora_data = item.data(0, Qt.ItemDataRole.UserRole)
                weight_widget = tree.itemWidget(item, 1)
                weight = weight_widget.value() if weight_widget else 0.75
                selected_for_model.append({'lora_object': lora_data, 'weight': weight})
        return selected_for_model