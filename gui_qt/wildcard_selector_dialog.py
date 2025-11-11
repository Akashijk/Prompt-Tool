from typing import Optional, List, Any

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QDialogButtonBox,
    QWidget
)
from PySide6.QtCore import Slot
from .custom_widgets import SmoothListWidget

class WildcardSelectorDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, processor: Optional[Any] = None):
        super().__init__(parent)
        self.setWindowTitle("Select Wildcard")
        self.processor = processor
        self.result: Optional[List[str]] = None # Can select multiple wildcards

        self._create_widgets()
        self._connect_signals()
        self._populate_wildcards()

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search wildcards...")
        main_layout.addWidget(self.search_edit)

        self.list_widget = SmoothListWidget()
        self.list_widget.setSelectionMode(SmoothListWidget.ExtendedSelection) # Allow multi-selection
        main_layout.addWidget(self.list_widget)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.search_edit.textChanged.connect(self._filter_wildcards)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)

    def _populate_wildcards(self):
        if self.processor:
            wildcard_names = self.processor.get_wildcard_names()
            self.list_widget.addItems(sorted(wildcard_names, key=lambda x: x.lower()))

    @Slot(str)
    def _filter_wildcards(self, search_text: str):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(search_text.lower() not in item.text().lower())

    @Slot()
    def _on_accept(self):
        self.result = [item.text() for item in self.list_widget.selectedItems()]
        self.accept()
