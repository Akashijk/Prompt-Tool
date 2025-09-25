"The wildcard inserter listbox and its frame."

import os
from typing import Callable, List, Optional, TYPE_CHECKING, Dict, Any

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QLabel, QLineEdit, QFrame, QListWidgetItem
from PySide6.QtCore import Qt, QTimer, QPoint, Slot, QEvent
from PySide6.QtGui import QCursor

from core.prompt_processor import PromptProcessor
from .text_preview_mixin import TextPreviewMixin

if TYPE_CHECKING:
    from .gui_app import GUIApp

class WildcardInserter(QWidget, TextPreviewMixin):
    """A widget to display a list of wildcards and allow insertion into the template editor."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor, insert_callback: Callable, manage_callback: Callable):
        super().__init__(parent)
        TextPreviewMixin.__init__(self)
        self.parent_app = parent
        self.processor = processor
        self.insert_callback = insert_callback
        self.manage_callback = manage_callback

        self._create_widgets()
        self._connect_signals()

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Search bar
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search wildcards...")
        search_layout.addWidget(self.search_edit)
        main_layout.addLayout(search_layout)

        self.wildcard_list = QListWidget()
        self.wildcard_list.setMouseTracking(True) # Required for hover events
        main_layout.addWidget(self.wildcard_list)

        self.manage_wildcards_button = QPushButton("Manage Wildcards...")
        main_layout.addWidget(self.manage_wildcards_button)

    def _connect_signals(self):
        self.wildcard_list.itemDoubleClicked.connect(self._on_wildcard_double_clicked)
        self.manage_wildcards_button.clicked.connect(self.manage_callback)
        self.search_edit.textChanged.connect(self._filter_list)
        self.wildcard_list.viewport().installEventFilter(self) # Install event filter for hover
        self.wildcard_list.itemEntered.connect(self._on_wildcard_item_enter)

    def populate(self, wildcard_files: List[str]):
        self.wildcard_list.clear()
        wildcard_file_map = {os.path.splitext(f)[0]: f for f in wildcard_files}
        wildcard_basenames = sorted(list(wildcard_file_map.keys()), key=str.lower)
        for basename in wildcard_basenames:
            item = QListWidgetItem(basename)
            # Store the full filename in the item's data for the tooltip loader
            full_filename = wildcard_file_map.get(basename)
            item.setData(Qt.ItemDataRole.UserRole, full_filename)
            self.wildcard_list.addItem(item)

    def get_selected_wildcard_name(self) -> Optional[str]:
        selected_items = self.wildcard_list.selectedItems()
        if not selected_items:
            return None
        return selected_items[0].text()

    @Slot(QListWidgetItem)
    def _on_wildcard_double_clicked(self, item: QListWidgetItem):
        """Inserts a wildcard tag into the editor on double-click."""
        wildcard_name = item.text()
        self.insert_callback(wildcard_name)

    @Slot(str)
    def _filter_list(self, search_text: str):
        """Filters the items in the list widget based on the search text."""
        search_term = search_text.lower()
        for i in range(self.wildcard_list.count()):
            item = self.wildcard_list.item(i)
            is_visible = search_term in item.text().lower()
            item.setHidden(not is_visible)

    def eventFilter(self, source, event):
        """Filters events to detect when the mouse leaves the wildcard list viewport."""
        if source is self.wildcard_list.viewport():
            if event.type() == QEvent.Type.Leave:
                self._hide_text_preview()
        return super().eventFilter(source, event)

    @Slot(QListWidgetItem)
    def _on_wildcard_item_enter(self, item: QListWidgetItem):
        """Handles hover events on wildcard list items to show a preview."""
        
        # If the mouse is not over any valid item, hide the preview.
        if self.wildcard_list.itemAt(self.wildcard_list.viewport().mapFromGlobal(QCursor.pos())) is None:
            self._hide_text_preview()
            return
        
        # This function will be called by the mixin's timer to load content on-demand
        def content_loader() -> Optional[str]:
            filename = item.data(Qt.ItemDataRole.UserRole)
            if not filename:
                return None
            try:
                data, _ = self.processor.get_wildcard_data_for_editing(filename)
                choices = data.get('choices', [])
                preview_choices = [str(c.get('value') if isinstance(c, dict) else c) for c in choices[:15]]
                content = "\n".join(preview_choices)
                if len(choices) > 15:
                    content += "\n...and {len(choices) - 15} more."
                return content
            except Exception:
                return "Error loading wildcard content."
        self._schedule_text_preview(content_loader)
