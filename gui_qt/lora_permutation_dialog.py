"""A Qt dialog for creating LoRA permutations for an image generation."""

import uuid
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QApplication
)

from core.prompt_processor import PromptProcessor
from .custom_widgets import SmoothListWidget


class LoraPermutationDialog(QDialog):
    """A dialog for creating LoRA permutations for an image generation."""

    def __init__(self, parent, processor: PromptProcessor, base_params: Dict[str, Any]):
        super().__init__(parent)
        self.setWindowTitle("Generate LoRA Permutations")
        self.processor = processor
        self.base_params = base_params
        self.all_loras: Dict[str, Any] = {}
        self.permutations: List[Dict[str, Any]] = []
        self.current_permutation_index = -1
        self.result: Optional[List[List[Dict[str, Any]]]] = None

        self._create_widgets()
        self._load_loras()

        # Add initial permutation based on the original image's LoRAs
        initial_loras = self.base_params.get('loras', [])
        self._add_permutation(initial_loras)

        if self.permutations:
            self.perm_list.setCurrentRow(0)

        self.resize(800, 500)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Left Pane: Permutation List
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.addWidget(QLabel("Permutations:"))
        self.perm_list = SmoothListWidget()
        self.perm_list.currentItemChanged.connect(self._on_permutation_select)
        left_layout.addWidget(self.perm_list)

        perm_actions = QHBoxLayout()
        add_button = QPushButton("Add")
        add_button.clicked.connect(lambda: self._add_permutation())
        perm_actions.addWidget(add_button)
        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(self._duplicate_permutation)
        perm_actions.addWidget(duplicate_button)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_permutation)
        perm_actions.addWidget(remove_button)
        left_layout.addLayout(perm_actions)
        splitter.addWidget(left_pane)

        # Right Pane: LoRA Configuration
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.addWidget(QLabel("LoRAs for Selected Permutation:"))
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.lora_rows_container = QWidget()
        self.lora_rows_layout = QVBoxLayout(self.lora_rows_container)
        self.lora_rows_layout.setAlignment(Qt.AlignTop)
        scroll_area.setWidget(self.lora_rows_container)
        right_layout.addWidget(scroll_area)

        add_lora_button = QPushButton("Add LoRA to Permutation")
        add_lora_button.clicked.connect(self._add_lora_row_to_current_perm)
        right_layout.addWidget(add_lora_button)
        splitter.addWidget(right_pane)

        splitter.setSizes([250, 550])

        # Bottom Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Generate")
        button_box.accepted.connect(self._on_ok)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def _load_loras(self):
        try:
            base_model_obj = self.base_params.get('model', {})
            base_model_type = base_model_obj.get('base')
            lora_models = self.processor.get_invokeai_loras(base_model=base_model_type)
            self.all_loras = {m['name']: m for m in lora_models}
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load LoRAs: {e}")
            self.reject()

    def _add_permutation(self, initial_loras: Optional[List[Dict[str, Any]]] = None):
        perm_id = str(uuid.uuid4())
        lora_rows = [self._create_lora_row(lora) for lora in initial_loras] if initial_loras else [self._create_lora_row()]
        
        new_perm = {'id': perm_id, 'lora_rows': lora_rows}
        self.permutations.append(new_perm)
        
        item = QListWidgetItem()
        self.perm_list.addItem(item)
        self._update_perm_list_item_text(item, new_perm)

    def _create_lora_row(self, lora_info: Optional[Dict[str, Any]] = None) -> Dict[str, QWidget]:
        row_frame = QFrame()
        row_layout = QHBoxLayout(row_frame)
        row_layout.setContentsMargins(0, 0, 0, 0)

        lora_names = ["(None)"] + sorted(list(self.all_loras.keys()), key=str.lower)
        lora_combo = QComboBox()
        lora_combo.addItems(lora_names)
        row_layout.addWidget(lora_combo, 1)

        weight_spinbox = QDoubleSpinBox()
        weight_spinbox.setRange(-1.0, 2.0)
        weight_spinbox.setSingleStep(0.05)
        row_layout.addWidget(weight_spinbox)

        delete_button = QPushButton("Delete")
        delete_button.setFixedSize(QSize(60, 25))
        row_layout.addWidget(delete_button)

        row_widgets = {"frame": row_frame, "combo": lora_combo, "spinbox": weight_spinbox}
        delete_button.clicked.connect(lambda: self._delete_lora_row(row_widgets))
        lora_combo.currentTextChanged.connect(self._update_current_perm_name)

        if lora_info:
            lora_name = lora_info.get('lora_object', {}).get('name')
            if lora_name in lora_names:
                lora_combo.setCurrentText(lora_name)
            weight_spinbox.setValue(lora_info.get('weight', 0.75))
        else:
            weight_spinbox.setValue(0.75)

        return row_widgets

    def _on_permutation_select(self, current: QListWidgetItem, previous: QListWidgetItem):
        if not current:
            return
        new_index = self.perm_list.row(current)
        if new_index == self.current_permutation_index:
            return

        # Clear old widgets
        while self.lora_rows_layout.count():
            child = self.lora_rows_layout.takeAt(0)
            if child.widget():
                child.widget().setParent(None)

        # Add new widgets
        self.current_permutation_index = new_index
        current_perm = self.permutations[self.current_permutation_index]
        for row in current_perm['lora_rows']:
            self.lora_rows_layout.addWidget(row['frame'])

    def _update_perm_list_item_text(self, item: QListWidgetItem, perm_data: Dict[str, Any]):
        lora_names = []
        for row in perm_data['lora_rows']:
            lora_name = row['combo'].currentText()
            if lora_name and lora_name != "(None)":
                lora_names.append(lora_name)
        
        display_name = f"Permutation {self.permutations.index(perm_data) + 1}"
        if lora_names:
            display_name += f" ({' + '.join(lora_names)})"
        item.setText(display_name)

        if self.current_permutation_index == -1:
            return
        item = self.perm_list.item(self.current_permutation_index)
        perm_data = self.permutations[self.current_permutation_index]
        self._update_perm_list_item_text(item, perm_data)

    def _add_lora_row_to_current_perm(self):
        if self.current_permutation_index == -1:
            return
        new_row = self._create_lora_row()
        self.permutations[self.current_permutation_index]['lora_rows'].append(new_row)
        self.lora_rows_layout.addWidget(new_row['frame'])

    def _delete_lora_row(self, row_widgets: Dict[str, QWidget]):
        if self.current_permutation_index == -1:
            return
        current_perm = self.permutations[self.current_permutation_index]
        current_perm['lora_rows'].remove(row_widgets)
        row_widgets['frame'].deleteLater()
        self._update_current_perm_name()

    def _duplicate_permutation(self):
        if self.current_permutation_index == -1:
            return
        perm_to_copy = self.permutations[self.current_permutation_index]
        new_loras = []
        for row in perm_to_copy['lora_rows']:
            lora_name = row['combo'].currentText()
            lora_obj = self.all_loras.get(lora_name)
            if lora_obj:
                new_loras.append({'lora_object': lora_obj, 'weight': row['spinbox'].value()})
        self._add_permutation(new_loras)

    def _remove_permutation(self):
        if self.current_permutation_index == -1:
            return
        row_to_remove = self.current_permutation_index
        perm_to_remove = self.permutations.pop(row_to_remove)
        for row in perm_to_remove['lora_rows']:
            row['frame'].deleteLater()
        self.perm_list.takeItem(row_to_remove)

    def _on_ok(self):
        self.result = []
        for perm in self.permutations:
            loras_for_perm = []
            for row in perm['lora_rows']:
                lora_name = row['combo'].currentText()
                if lora_name == "(None)":
                    continue
                lora_obj = self.all_loras.get(lora_name)
                if lora_obj:
                    loras_for_perm.append({'lora_object': lora_obj, 'weight': row['spinbox'].value()})
            self.result.append(loras_for_perm)
        
        if not self.result:
            self.result.append([]) # Add a default permutation with no LoRAs
        self.accept()