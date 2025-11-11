import json
from typing import Any, Optional, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QSpinBox,
    QDialogButtonBox, QMessageBox, QWidget
)
from PySide6.QtCore import Slot
from .custom_widgets import SmoothTextEdit

class EditChoiceDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, title: str = "Edit Choice", initial_values: Optional[Tuple[str, str, str, str, str]] = None, processor: Optional[Any] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.processor = processor # Keep processor for potential future validation/AI features
        self.result: Optional[Tuple[str, str, str, str, str]] = None

        self._create_widgets(initial_values)
        self._connect_signals()

    def _create_widgets(self, initial_values: Optional[Tuple[str, str, str, str, str]]):
        main_layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.value_edit = QLineEdit(initial_values[0] if initial_values else "")
        form_layout.addRow("Value:", self.value_edit)

        self.weight_spin = QSpinBox()
        self.weight_spin.setRange(0, 1000) # Reasonable range for weights
        self.weight_spin.setValue(int(initial_values[1]) if initial_values and initial_values[1] else 1)
        form_layout.addRow("Weight:", self.weight_spin)

        self.tags_edit = QLineEdit(initial_values[2] if initial_values else "")
        form_layout.addRow("Tags (comma-separated):", self.tags_edit)

        self.requires_edit = SmoothTextEdit(initial_values[3] if initial_values else "")
        self.requires_edit.setPlaceholderText("JSON object for requirements (e.g., {\"wildcard_name\": \"value\"})")
        self.requires_edit.setMinimumHeight(60)
        form_layout.addRow("Requires (JSON):", self.requires_edit)

        self.includes_edit = SmoothTextEdit(initial_values[4] if initial_values else "")
        self.includes_edit.setPlaceholderText("JSON list of wildcards or template string (e.g., [\"wc1\", \"wc2\"] or \"__wc1__ __wc2__\")")
        self.includes_edit.setMinimumHeight(60)
        form_layout.addRow("Includes (JSON list or template):", self.includes_edit)

        main_layout.addLayout(form_layout)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)

    @Slot()
    def _on_accept(self):
        value = self.value_edit.text().strip()
        weight = str(self.weight_spin.value())
        tags = self.tags_edit.text().strip()
        requires_text = self.requires_edit.toPlainText().strip()
        includes_text = self.includes_edit.toPlainText().strip()

        if not value:
            QMessageBox.warning(self, "Validation Error", "Value cannot be empty.")
            return

        # Validate JSON for requires
        if requires_text:
            try:
                json.loads(requires_text)
            except json.JSONDecodeError:
                QMessageBox.warning(self, "Validation Error", "Requires field must contain valid JSON.")
                return
        
        # Validate JSON for includes (if it looks like JSON)
        if includes_text.startswith('[') and includes_text.endswith(']'):
            try:
                parsed_includes = json.loads(includes_text)
                if not isinstance(parsed_includes, list):
                    QMessageBox.warning(self, "Validation Error", "Includes field, if JSON, must be a list.")
                    return
            except json.JSONDecodeError:
                QMessageBox.warning(self, "Validation Error", "Includes field contains malformed JSON list.")
                return

        self.result = (value, weight, tags, requires_text, includes_text)
        self.accept()
