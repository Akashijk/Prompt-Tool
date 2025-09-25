"""The structured editor widget for wildcard files, rewritten in Qt."""

import json
from typing import Any, Callable, Dict, List, Optional
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QSplitter,
    QGroupBox,
    QPushButton,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QBrush, QColor

from core.prompt_processor import PromptProcessor


class WildcardEditor(QWidget):
    """A structured editor for wildcard files, rewritten in Qt."""

    def __init__(self, 
                 processor: PromptProcessor, 
                 parent=None,
                 suggestion_callback: Optional[Callable] = None,
                 autotag_callback: Optional[Callable] = None,
                 enrich_callback: Optional[Callable] = None,
                 find_replace_callback: Optional[Callable] = None,
                 find_duplicates_callback: Optional[Callable] = None):
        super().__init__(parent)
        self.processor = processor
        self.iid_to_choice_map: Dict[QTreeWidgetItem, Any] = {}
        
        # Callbacks for AI actions
        self.suggestion_callback = suggestion_callback
        self.autotag_callback = autotag_callback
        self.enrich_callback = enrich_callback
        self.find_replace_callback = find_replace_callback
        self.find_duplicates_callback = find_duplicates_callback
        
        self.highlighted_items: List[QTreeWidgetItem] = []
        
        self._create_widgets()
        # Store the default brush after widgets are created and styled
        self.default_item_brush = self.tree.palette().brush(self.tree.backgroundRole())
        self.highlight_brush = QBrush(QColor("#FFA07A")) # Light Salmon

    def _create_widgets(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Description ---
        desc_group = QGroupBox("Description")
        desc_layout = QHBoxLayout(desc_group)
        self.description_entry = QLineEdit()
        desc_layout.addWidget(self.description_entry)
        layout.addWidget(desc_group)

        # --- Choices Tree ---
        choices_group = QGroupBox("Choices")
        choices_layout = QVBoxLayout(choices_group)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(['Value', 'Weight', 'Tags', 'Requires', 'Includes'])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(1, 60)  # Weight
        choices_layout.addWidget(self.tree)
        layout.addWidget(choices_group)
        
        # --- NEW: AI and Editor Tools ---
        tools_splitter = QSplitter(Qt.Horizontal)
        
        # AI Tools
        ai_tools_group = QGroupBox("AI Tools")
        ai_tools_layout = QHBoxLayout(ai_tools_group)
        self.suggest_button = QPushButton("Suggest Choices")
        self.autotag_button = QPushButton("Auto-Tag All")
        self.enrich_button = QPushButton("Enrich Choices")
        ai_tools_layout.addWidget(self.suggest_button)
        ai_tools_layout.addWidget(self.autotag_button)
        ai_tools_layout.addWidget(self.enrich_button)
        tools_splitter.addWidget(ai_tools_group)

        # Editor Tools
        editor_tools_group = QGroupBox("Editor Tools")
        editor_tools_layout = QHBoxLayout(editor_tools_group)
        self.find_replace_button = QPushButton("Find & Replace...")
        self.find_duplicates_button = QPushButton("Find Duplicates")
        editor_tools_layout.addWidget(self.find_replace_button)
        editor_tools_layout.addWidget(self.find_duplicates_button)
        tools_splitter.addWidget(editor_tools_group)
        layout.addWidget(tools_splitter)

        # Connect AI and Editor buttons to callbacks
        if self.suggestion_callback: self.suggest_button.clicked.connect(lambda: self.suggestion_callback(self.get_data()))
        if self.autotag_callback: self.autotag_button.clicked.connect(lambda: self.autotag_callback(self.get_data()))
        if self.enrich_callback: self.enrich_button.clicked.connect(lambda: self.enrich_callback(self.get_data()))
        if self.find_replace_callback: self.find_replace_button.clicked.connect(self.find_replace_callback)
        if self.find_duplicates_callback: self.find_duplicates_button.clicked.connect(self.find_duplicates_callback)

        # --- Global Includes ---
        includes_group = QGroupBox("Global Includes (as list or template string)")
        includes_layout = QVBoxLayout(includes_group)
        self.includes_text = QTextEdit()
        includes_layout.addWidget(self.includes_text)
        layout.addWidget(includes_group)

    def highlight_items(self, items_to_highlight: List[QTreeWidgetItem]):
        """Highlights a list of items in the tree."""
        self.clear_highlights()
        for item in items_to_highlight:
            for i in range(self.tree.columnCount()):
                item.setBackground(i, self.highlight_brush)
        self.highlighted_items = items_to_highlight

    def clear_highlights(self):
        """Removes highlighting from all previously highlighted items."""
        for item in self.highlighted_items:
            for i in range(self.tree.columnCount()):
                # Reset to the default background
                item.setBackground(i, self.default_item_brush)
        self.highlighted_items.clear()

    def set_data(self, data: Dict[str, Any]):
        """Populates the editor with data from a wildcard file."""
        self.tree.clear()
        self.iid_to_choice_map.clear()

        self.description_entry.setText(data.get('description', ''))

        choices = data.get('choices', [])
        for choice in choices:
            item = self._create_tree_item(choice)
            self.tree.addTopLevelItem(item)
            self.iid_to_choice_map[item] = choice

        includes_data = data.get('includes')
        if isinstance(includes_data, str):
            self.includes_text.setPlainText(includes_data)
        elif isinstance(includes_data, list):
            display_str = " ".join([f"[{w}]" for w in includes_data])
            self.includes_text.setPlainText(display_str)
        else:
            self.includes_text.clear()

    def add_choices(self, new_choices: List[Any]):
        """Appends new choices to the editor."""
        for choice in new_choices:
            item = self._create_tree_item(choice)
            self.tree.addTopLevelItem(item)
            self.iid_to_choice_map[item] = choice

    def get_data(self) -> Dict[str, Any]:
        """Constructs the JSON data object from the UI widgets."""
        choices = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            choice = self._get_choice_from_tree_item(item)
            choices.append(choice)

        data_dict = {
            "description": self.description_entry.text(),
            "choices": choices
        }

        includes_text = self.includes_text.toPlainText().strip()
        if includes_text:
            data_dict['includes'] = includes_text

        return data_dict

    def _create_tree_item(self, choice: Any) -> QTreeWidgetItem:
        """Creates a QTreeWidgetItem from a choice object."""
        if isinstance(choice, str):
            return QTreeWidgetItem([choice, '', '', '', ''])

        if isinstance(choice, dict):
            value = str(choice.get('value', ''))
            weight = str(choice.get('weight', ''))
            tags = ", ".join(choice.get('tags', []))
            requires = json.dumps(choice.get('requires', {})) if choice.get('requires') else ""
            
            includes_val = choice.get('includes')
            if isinstance(includes_val, list):
                includes_display = json.dumps(includes_val)
            else:
                includes_display = includes_val or ''
                
            return QTreeWidgetItem([value, weight, tags, requires, includes_display])
        
        return QTreeWidgetItem(["Invalid Choice"])

    def _get_choice_from_tree_item(self, item: QTreeWidgetItem) -> Any:
        """Converts a QTreeWidgetItem back into a choice object."""
        value, weight_str, tags_str, requires_str, includes_str = [item.text(i) for i in range(5)]

        if not weight_str and not tags_str and not requires_str and not includes_str:
            return value

        choice_obj = {'value': value}
        if weight_str:
            try: choice_obj['weight'] = int(weight_str)
            except (ValueError, TypeError): pass
        if tags_str:
            choice_obj['tags'] = [t.strip() for t in tags_str.split(',') if t.strip()]
        if requires_str:
            try: choice_obj['requires'] = json.loads(requires_str)
            except json.JSONDecodeError: pass
        if includes_str:
            choice_obj['includes'] = includes_str
        
        return choice_obj