from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QDialogButtonBox,
    QLabel, QWidget
)
from PySide6.QtCore import Slot
from .custom_widgets import SmoothTextEdit

class MassEditDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, initial_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Mass Edit Choices")
        self.result: Optional[str] = None

        self._create_widgets(initial_text)
        self._connect_signals()

    def _create_widgets(self, initial_text: str):
        main_layout = QVBoxLayout(self)

        main_layout.addWidget(QLabel("Edit choices (one per line):"))
        self.text_edit = SmoothTextEdit()
        self.text_edit.setPlainText(initial_text)
        main_layout.addWidget(self.text_edit)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)

    @Slot()
    def _on_accept(self):
        self.result = self.text_edit.toPlainText()
        self.accept()
