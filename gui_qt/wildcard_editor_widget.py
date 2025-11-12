import json
import re
import copy
import difflib
from typing import Dict, List, Any, Optional, Tuple, Callable, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QGroupBox,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QMenu,
    QMessageBox, QApplication, QLabel, QListWidgetItem, QDialog
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QPoint
from PySide6.QtGui import QColor, QAction, QTextCursor

from core.config import config
from .edit_choice_dialog import EditChoiceDialog
from .mass_edit_dialog import MassEditDialog
from .wildcard_selector_dialog import WildcardSelectorDialog
from .custom_widgets import SmoothListWidget, SmoothTextEdit
# Assuming PromptProcessor is available via parent or direct import
if TYPE_CHECKING:
    from core.prompt_processor import PromptProcessor

# Placeholder for AutocompletePopup - will be implemented later
class _AutocompletePopup(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Basic setup for now
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setLayout(QVBoxLayout())
        self.list_widget = SmoothListWidget(self)
        self.layout().addWidget(self.list_widget)
        self.list_widget.itemClicked.connect(self._on_select)

    def set_suggestions(self, suggestions: List[str]):
                                                                self.list_widget.clear()
                                                                self.list_widget.addItems(suggestions)
                                                                if suggestions:
                                                                    self.list_widget.setCurrentRow(0)
                                                                self.adjustSize()

    def _on_select(self, item: QListWidgetItem):
        # This will need to be connected to the actual insert callback
        pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return:
            self._on_select(self.list_widget.currentItem())
        elif event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Up:
            self.list_widget.setCurrentRow(max(0, self.list_widget.currentRow() - 1))
        elif event.key() == Qt.Key_Down:
            self.list_widget.setCurrentRow(min(self.list_widget.count() - 1, self.list_widget.currentRow() + 1))
        else:
            super().keyPressEvent(event)


class WildcardEditor(QWidget):
    """A structured editor for wildcard files."""
    # Signals to communicate changes to the parent
    dataChanged = Signal()
    requestSuggestion = Signal(dict) # Emits current data for AI suggestion
    requestAutotag = Signal(dict)    # Emits current data for AI autotagging
    requestEnrichment = Signal(dict) # Emits current data for AI enrichment
    requestAddRequirement = Signal(str) # Emits iid of selected item
    requestValueChangeRefactor = Signal(str, str) # Emits old_value, new_value

    def __init__(self, 
                 parent: Optional[QWidget] = None, 
                 processor: Optional['PromptProcessor'] = None,
                 suggestion_callback: Optional[Callable] = None,
                 autotag_callback: Optional[Callable] = None,
                 enrich_callback: Optional[Callable] = None,
                 find_replace_callback: Optional[Callable] = None,
                 find_duplicates_callback: Optional[Callable] = None):
        super().__init__(parent)
        self.processor = processor
        self.iid_to_choice_map: Dict[int, Any] = {} # Use id(QTreeWidgetItem) as key
        # Store callbacks
        self.suggestion_callback = suggestion_callback
        self.autotag_callback = autotag_callback
        self.enrich_callback = enrich_callback
        self.find_replace_callback = find_replace_callback
        self.find_duplicates_callback = find_duplicates_callback

        self.item_errors: Dict[int, List[str]] = {} # Map iid to list of error messages
        self.validation_debounce_timer = QTimer(self)
        self.validation_debounce_timer.setSingleShot(True)
        self.validation_debounce_timer.setInterval(750) # 750ms delay
        self.validation_debounce_timer.timeout.connect(self._validate_all_items)

        self.autocomplete_popup: Optional[_AutocompletePopup] = None
        self.validation_error_tag = "validation_error"
        self.included_tag = "included"
        self.duplicate_tag = "duplicate"

        self._create_widgets()
        self._connect_signals()
        self.update_theme() # Set initial theme-based colors

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        # --- Description ---
        desc_group = QGroupBox("Description")
        desc_layout = QHBoxLayout(desc_group)
        self.description_entry = QLineEdit()
        self.description_entry.textChanged.connect(lambda: self.dataChanged.emit())
        desc_layout.addWidget(self.description_entry)
        main_layout.addWidget(desc_group)

        self.file_error_label = QLabel("")
        self.file_error_label.setStyleSheet("color: red;")
        self.file_error_label.setWordWrap(True)
        main_layout.addWidget(self.file_error_label)

        # --- Choices Pane ---
        choices_group = QGroupBox("Choices")
        choices_layout = QVBoxLayout(choices_group)

        # Choices Toolbar - Group 1: Basic Actions
        basic_actions_toolbar = QHBoxLayout()
        add_button = QPushButton("Add")
        add_button.clicked.connect(self._add_item)
        basic_actions_toolbar.addWidget(add_button)

        mass_edit_button = QPushButton("Mass Edit...")
        mass_edit_button.clicked.connect(self._mass_edit_choices)
        basic_actions_toolbar.addWidget(mass_edit_button)

        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._delete_item)
        basic_actions_toolbar.addWidget(delete_button)
        basic_actions_toolbar.addStretch() # Push buttons to the left
        choices_layout.addLayout(basic_actions_toolbar)

        # Choices Toolbar - Group 2: AI Actions
        ai_actions_toolbar = QHBoxLayout()
        self.suggest_button = QPushButton("Suggest (AI)")
        self.suggest_button.clicked.connect(self._on_suggest_choices)
        self.suggest_button.setEnabled(self.suggestion_callback is not None)
        ai_actions_toolbar.addWidget(self.suggest_button)

        self.autotag_button = QPushButton("Auto-Tag (AI)")
        self.autotag_button.clicked.connect(self._on_auto_tag_choices)
        self.autotag_button.setEnabled(self.autotag_callback is not None)
        ai_actions_toolbar.addWidget(self.autotag_button)

        self.enrich_button = QPushButton("Enrich (AI)")
        self.enrich_button.clicked.connect(self._on_enrich_choices)
        self.enrich_button.setEnabled(self.enrich_callback is not None)
        ai_actions_toolbar.addWidget(self.enrich_button)
        ai_actions_toolbar.addStretch() # Push buttons to the left
        choices_layout.addLayout(ai_actions_toolbar)

        # Choices Treeview
        columns = ['Value', 'Weight', 'Tags', 'Requires', 'Includes']
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(columns)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch) # Value column stretches
        self.tree.setColumnWidth(1, 60) # Weight
        self.tree.header().setSectionResizeMode(2, QHeaderView.Stretch) # Tags
        self.tree.header().setSectionResizeMode(3, QHeaderView.Stretch) # Requires
        self.tree.header().setSectionResizeMode(4, QHeaderView.Stretch) # Includes
        self.tree.setColumnWidth(2, 100) # Minimum width for Tags
        self.tree.setColumnWidth(3, 100) # Minimum width for Requires
        self.tree.setColumnWidth(4, 100) # Minimum width for Includes
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click_item)
        self.tree.itemChanged.connect(self._on_item_changed) # For checkable items or in-place edits

        choices_layout.addWidget(self.tree)
        main_layout.addWidget(choices_group)

        # --- Includes Pane ---
        includes_group = QGroupBox("Global Includes") # Shortened title
        includes_layout = QVBoxLayout(includes_group)

        includes_toolbar = QHBoxLayout()
        insert_wildcard_button = QPushButton("Insert Wildcard...")
        insert_wildcard_button.clicked.connect(self._insert_include_wildcard)
        includes_toolbar.addWidget(insert_wildcard_button)
        includes_toolbar.addStretch()
        includes_layout.addLayout(includes_toolbar)

        self.includes_text = SmoothTextEdit()
        self.includes_text.textChanged.connect(lambda: self.dataChanged.emit())
        self.includes_text.textChanged.connect(self.validation_debounce_timer.start) # Trigger validation
        includes_layout.addWidget(self.includes_text)
        main_layout.addWidget(includes_group)

    def _connect_signals(self):
        # self.tree.itemDoubleClicked.connect(self._on_double_click_item) # Removed duplicate connection
        self.tree.customContextMenuRequested.connect(self._show_context_menu) # Already connected in _create_widgets

    def _on_suggest_choices(self):
        if self.suggestion_callback:
            # Pass current choices and description as context for AI
            current_data = self.get_data()
            current_choices = [c.get('value') if isinstance(c, dict) else c for c in current_data.get('choices', [])]
            context = current_data.get('description', '')
            self.suggestion_callback(current_choices, context)

    def _on_auto_tag_choices(self):
        if self.autotag_callback:
            current_choices = self.get_data().get('choices', [])
            autotagged_choices = self.autotag_callback(current_choices)
            if autotagged_choices:
                self.set_data({'description': self.description_entry.text(), 'choices': autotagged_choices, 'includes': self.includes_text.toPlainText()})
                self.dataChanged.emit()

    def _on_enrich_choices(self):
        if self.enrich_callback:
            current_data = self.get_data()
            current_choices = current_data.get('choices', [])
            context = current_data.get('description', '')
            enriched_choices = self.enrich_callback(current_choices, context)
            if enriched_choices:
                self.set_data({'description': self.description_entry.text(), 'choices': enriched_choices, 'includes': self.includes_text.toPlainText()})
                self.dataChanged.emit()

    def update_theme(self):
        """Updates the tag colors in the treeview to match the current theme."""
        # Assuming config.theme is accessible and updated
        is_dark = config.theme == "dark"

        included_bg = QColor("#2c3e50") if is_dark else QColor("#e6f3ff") # Dark muted blue / Light blue
        duplicate_bg = QColor("#5e3333") if is_dark else QColor("#ffcccc") # Dark muted red / Light red
        validation_error_bg = QColor("#6b4226") if is_dark else QColor("#ffe4b5") # Dark muted orange / Moccasin

        # QTreeWidget items don't have tag_configure like ttk.Treeview.
        # We need to apply colors directly to items when setting them or when their state changes.
        # For now, this method will be called to re-apply colors to existing items.
        for iid_item in self.tree.findItems("", Qt.MatchContains | Qt.MatchRecursive):
            # Check if the item has associated tags (stored in UserRole + 1)
            item_tags = iid_item.data(0, Qt.UserRole + 1) or []
            if self.included_tag in item_tags:
                iid_item.setBackground(0, included_bg)
            elif self.duplicate_tag in item_tags:
                iid_item.setBackground(0, duplicate_bg)
            elif self.validation_error_tag in item_tags:
                iid_item.setBackground(0, validation_error_bg)
            else:
                # Clear any previous background if no special tags apply
                iid_item.setBackground(0, QColor(Qt.transparent))

    def _format_includes_for_display(self, includes_data: Any) -> str:
        """Formats the includes data for display in the QTextEdit."""
        if isinstance(includes_data, list):
            return " ".join([f"[{w}]" for w in includes_data])
        elif isinstance(includes_data, str):
            return includes_data
        return ""

    def _get_values_tuple_from_choice(self, choice: Any) -> Tuple[str, str, str, str, str]:
        """Converts a choice object (string or dict) into a tuple of strings for the treeview."""
        if isinstance(choice, str):
            return choice, "", "", "", ""
        elif isinstance(choice, dict):
            value = str(choice.get('value', ''))
            weight = str(choice.get('weight', ''))
            
            # Summarize tags
            tags_list = choice.get('tags', [])
            tags_display = f"{len(tags_list)} tags" if tags_list else ""

            # Summarize requires
            requires_dict = choice.get('requires', {})
            requires_display = "Yes" if requires_dict else ""

            # Summarize includes
            includes_data = choice.get('includes')
            includes_display = "Yes" if includes_data else ""

            return value, weight, tags_display, requires_display, includes_display
        return "", "", "", "", ""

    def set_data(self, data: Dict[str, Any]):
        self.description_entry.setText(data.get('description', ''))
        self.tree.clear()
        self.iid_to_choice_map.clear()
        self.item_errors.clear()

        self.description_entry.setText(data.get('description', ''))

        # Populate includes
        includes_data = data.get('includes')
        self.includes_text.setText(self._format_includes_for_display(includes_data))

        # Populate choices, sorted alphabetically by value
        choices = sorted(data.get('choices', []), key=lambda c: str(c.get('value') if isinstance(c, dict) else c).lower())
        for choice in choices:
            item = QTreeWidgetItem()
            values_tuple = self._get_values_tuple_from_choice(choice)
            for i, value in enumerate(values_tuple):
                item.setText(i, str(value))
            item.setData(0, Qt.UserRole, choice)
            self.iid_to_choice_map[id(item)] = choice
            self.tree.addTopLevelItem(item)
        
        self.tree.setUpdatesEnabled(True) # Re-enable updates
        self._validate_all_items()

    def get_data(self) -> Dict[str, Any]:
        """Constructs the JSON data object from the UI widgets."""
        choices = [self._get_choice_from_tree_item(item) for item in self.tree.findItems("", Qt.MatchContains | Qt.MatchRecursive)]
        
        includes_text = self.includes_text.toPlainText().strip()
        data_dict = {"description": self.description_entry.text(), "choices": choices}
        
        if includes_text:
            bracket_wildcards = re.findall(r'\[([a-zA-Z0-9_.-]+)\]', includes_text)
            reconstructed_text = " ".join([f"[{w}]" for w in bracket_wildcards])
            
            if len(bracket_wildcards) > 0 and includes_text == reconstructed_text:
                data_dict['includes'] = bracket_wildcards
            else:
                data_dict['includes'] = includes_text
        
        return data_dict

    def _get_choice_from_tree_item(self, item: QTreeWidgetItem) -> Any:
        """Converts a single QTreeWidgetItem into a string or a dictionary."""
        # Retrieve the original choice object stored in UserRole
        choice_obj = item.data(0, Qt.UserRole)
        if choice_obj is not None:
            return choice_obj
        
        # Fallback if not stored (e.g., new item added directly)
        value = item.text(0)
        weight_str = item.text(1)
        tags_str = item.text(2)
        requires_str = item.text(3)
        includes_str = item.text(4)

        # If no extra data, return a simple string
        if not weight_str and not tags_str and not requires_str and not includes_str:
            return value

        choice_obj = {'value': value}
        
        if weight_str:
            try:
                choice_obj['weight'] = int(weight_str)
            except (ValueError, TypeError):
                pass

        if tags_str:
            choice_obj['tags'] = [t.strip() for t in tags_str.split(',') if t.strip()]

        if requires_str:
            try:
                req_dict = json.loads(requires_str)
                if req_dict:
                    choice_obj['requires'] = req_dict
            except json.JSONDecodeError:
                pass
        
        if includes_str:
            try:
                parsed_includes = json.loads(includes_str)
                if isinstance(parsed_includes, list):
                    choice_obj['includes'] = parsed_includes
                else:
                    choice_obj['includes'] = includes_str
            except json.JSONDecodeError:
                choice_obj['includes'] = includes_str
        
        return choice_obj

    def _get_choice_from_values_tuple(self, values_tuple: Tuple[str, str, str, str, str]) -> Any:
        value, weight_str, tags_str, requires_str, includes_str = values_tuple

        # If no extra data, return a simple string
        if not weight_str and not tags_str and not requires_str and not includes_str:
            return value

        choice_obj = {'value': value}
        
        # Parse weight
        if weight_str:
            try:
                choice_obj['weight'] = int(weight_str)
            except (ValueError, TypeError):
                pass  # Ignore invalid weight

        # Parse tags
        if tags_str:
            choice_obj['tags'] = [t.strip() for t in tags_str.split(',') if t.strip()]

        # Parse requires
        if requires_str:
            try:
                req_dict = json.loads(requires_str)
                if req_dict:
                    choice_obj['requires'] = req_dict
            except json.JSONDecodeError:
                pass # Ignore malformed JSON string
        
        if includes_str:
            try:
                # Try to parse as JSON list first
                parsed_includes = json.loads(includes_str)
                if isinstance(parsed_includes, list):
                    choice_obj['includes'] = parsed_includes
                else: # It's some other JSON type, store as string
                    choice_obj['includes'] = includes_str
            except json.JSONDecodeError:
                # Not a valid JSON, so it's a template string
                choice_obj['includes'] = includes_str
        
        return choice_obj

    @Slot()
    def _add_item(self):
        dialog = EditChoiceDialog(self, "Add New Choice", initial_values=("", "1", "", "", ""), processor=self.processor)
        if dialog.exec() == QDialog.Accepted and dialog.result:
            new_values = dialog.result
            
            # Don't add if the value is empty
            if not new_values[0].strip():
                return

            item = QTreeWidgetItem(self.tree)
            for i, value in enumerate(new_values):
                item.setText(i, str(value))
            
            # Store the new choice object with the item
            new_choice_obj = self._get_choice_from_values_tuple(new_values)
            item.setData(0, Qt.UserRole, new_choice_obj)
            self.iid_to_choice_map[id(item)] = new_choice_obj
            
            self._validate_all_items()
            self.dataChanged.emit()
            self.tree.scrollToItem(item)
            self.tree.setCurrentItem(item)

    @Slot()
    def _mass_edit_choices(self):
        current_choices = self.get_data().get('choices', [])
        if not current_choices:
            return

        # Extract just the values for the text editor
        initial_text = "\n".join([str(c.get('value') if isinstance(c, dict) else c) for c in current_choices])

        dialog = MassEditDialog(self, initial_text)
        if dialog.exec() == QDialog.Accepted and dialog.result is not None:
            self._process_mass_edit(current_choices, dialog.result)

    def _merge_selected_items(self):
        selected_items = self.tree.selectedItems()
        if len(selected_items) != 2:
            return

        item1, item2 = selected_items
        
        # Get data for both items
        choice1 = self.iid_to_choice_map.get(id(item1))
        choice2 = self.iid_to_choice_map.get(id(item2))
        
        if not choice1 or not choice2:
            return

        # Ensure they are dicts for merging complex properties
        if isinstance(choice1, str):
            choice1 = {'value': choice1}
        if isinstance(choice2, str):
            choice2 = {'value': choice2}

        # --- Merge Logic ---
        # Use the value and weight of the first selected item as the base
        merged_value = choice1.get('value', '')
        merged_weight = choice1.get('weight', '')

        # Combine tags into a unique, sorted list
        merged_tags = sorted(list(set(choice1.get('tags', [])) | set(choice2.get('tags', []))))

        # Merge 'includes' intelligently
        inc1 = choice1.get('includes')
        inc2 = choice2.get('includes')
        merged_includes = None

        is_inc1_list = isinstance(inc1, list)
        is_inc2_list = isinstance(inc2, list)

        if is_inc1_list and is_inc2_list:
            # Both are lists, so we can safely merge them.
            merged_includes = sorted(list(set(inc1) | set(inc2)))
        elif inc1 or inc2: # At least one exists, and they are not both lists.
            # To avoid data corruption, we convert both to template strings and concatenate.
            # A list `["a", "b"]` becomes a string `[a] [b]`.
            s1 = " ".join([f"[{w}]" for w in inc1]) if is_inc1_list else (inc1 or '')
            s2 = " ".join([f"[{w}]" for w in inc2]) if is_inc2_list else (inc2 or '')
            
            combined_str = f"{s1} {s2}".strip()
            if combined_str:
                merged_includes = combined_str

        # Intelligently merge 'requires' dictionaries.
        merged_reqs = choice1.get('requires', {}).copy()
        reqs2 = choice2.get('requires', {})
        for key, value2 in reqs2.items():
            if key in merged_reqs:
                # Key exists, so we need to merge values robustly.
                value1 = merged_reqs[key]
                
                # Create sets of values to merge, handling both strings and lists.
                set1 = set(value1) if isinstance(value1, list) else {value1}
                set2 = set(value2) if isinstance(value2, list) else {value2}
                
                merged_values = sorted(list(set1 | set2))
                
                # If the result is a single item, store it as a string, otherwise as a list.
                # This keeps the format clean and readable.
                merged_reqs[key] = merged_values[0] if len(merged_values) == 1 else merged_values
            else:
                # Key is new, just add it.
                merged_reqs[key] = value2

        # --- Create new choice object and values tuple for the treeview ---
        
        # Format includes for display
        if isinstance(merged_includes, list):
            includes_display = json.dumps(merged_includes)
        else: # It's a string or None
            includes_display = merged_includes or ""

        new_values_tuple = (
            merged_value,
            str(merged_weight) if merged_weight is not None and merged_weight != '' else '',
            ", ".join(merged_tags),
            json.dumps(merged_reqs, separators=(',', ':')) if merged_reqs else "",
            includes_display
        )

        # Get index of the last selected item to insert the new one after it
        # Find the row index of the items
        row1 = self.tree.indexOfTopLevelItem(item1)
        row2 = self.tree.indexOfTopLevelItem(item2)
        insert_row_index = max(row1, row2) + 1

        # Insert new merged item into the tree
        new_item = QTreeWidgetItem(self.tree)
        for i, value in enumerate(new_values_tuple):
            new_item.setText(i, str(value))
        
        # Construct the object to store in the map, cleaning up empty keys
        new_choice_obj = {'value': merged_value}
        # Clean up None/empty values, but preserve weight if it is 0
        if merged_weight is not None and merged_weight != '':
            new_choice_obj['weight'] = merged_weight
        if merged_tags:
            new_choice_obj['tags'] = merged_tags
        if merged_reqs:
            new_choice_obj['requires'] = merged_reqs
        if merged_includes:
            new_choice_obj['includes'] = merged_includes

        new_item.setData(0, Qt.UserRole, new_choice_obj)
        self.iid_to_choice_map[id(new_item)] = new_choice_obj
        
        self.tree.insertTopLevelItem(insert_row_index, new_item)
        self._validate_all_items()

        # --- Ask to delete originals ---
        reply = QMessageBox.question(self, "Delete Originals?", "Would you like to delete the original items after merging?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item1))
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item2))
            del self.iid_to_choice_map[id(item1)]
            del self.iid_to_choice_map[id(item2)]
        
        self.dataChanged.emit()

    def _process_mass_edit(self, original_choices: List[Any], new_text: str):
        original_values = [str(c.get('value') if isinstance(c, dict) else c) for c in original_choices]
        new_values = [line.strip() for line in new_text.splitlines() if line.strip()]

        # Check if there are any actual changes before proceeding
        if original_values == new_values:
            return # No changes, do nothing.

        # Use difflib to compare and apply changes
        matcher = difflib.SequenceMatcher(None, original_values, new_values, autojunk=False)
        final_choices = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                # These choices were unchanged, so we keep the original full objects.
                final_choices.extend(original_choices[i1:i2])
            elif tag == 'replace':
                # If the lengths of the slices are the same, we can do a 1-to-1 replacement
                # and preserve the metadata for each corresponding item.
                if (i2 - i1) == (j2 - j1):
                    for i in range(i2 - i1):
                        original_choice = original_choices[i1 + i]
                        new_value = new_values[j1 + i]
                        if isinstance(original_choice, dict):
                            new_choice = original_choice.copy()
                            new_choice['value'] = new_value
                            final_choices.append(new_choice)
                        else: # It was a simple string, so the new value is also a simple string.
                            final_choices.append(new_value)
                else:
                    # Lengths differ. Treat as a pure insertion of new values. Metadata is lost for this block.
                    final_choices.extend(new_values[j1:j2])
            elif tag == 'insert':
                # These are new choices. Add them as simple strings.
                final_choices.extend(new_values[j1:j2])
        
        self.set_data({'description': self.description_entry.text(), 'choices': final_choices, 'includes': self.includes_text.toPlainText()})
        self.dataChanged.emit()

    @Slot()
    def _delete_item(self):
        selected_items = self.tree.selectedItems()
        if not selected_items:
            return

        reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete {len(selected_items)} selected item(s)?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            for item in selected_items:
                del self.iid_to_choice_map[id(item)]
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item)) # Remove from tree
            self._validate_all_items()
            self.dataChanged.emit()

    @Slot(QPoint)
    def _show_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        selected_items = self.tree.selectedItems()
        num_selected = len(selected_items)

        # Actions
        edit_action = QAction("Edit...", self)
        edit_action.setEnabled(num_selected == 1)
        edit_action.triggered.connect(lambda: self._open_full_edit_dialog(selected_items[0]))
        menu.addAction(edit_action)

        merge_action = QAction("Merge Selected Items (2)", self)
        merge_action.setEnabled(num_selected == 2)
        merge_action.triggered.connect(self._merge_selected_items)
        menu.addAction(merge_action)

        menu.addSeparator()

        # Add Requirement action (requires a callback from parent)
        add_requirement_action = QAction("Add Requirement for Selected", self)
        add_requirement_action.setEnabled(num_selected == 1 and self.requestAddRequirement.receivers(self.requestAddRequirement) > 0)
        add_requirement_action.triggered.connect(lambda: self.requestAddRequirement.emit(str(id(selected_items[0]))))
        menu.addAction(add_requirement_action)

        copy_as_requires_action = QAction("Copy as 'requires' JSON", self)
        copy_as_requires_action.setEnabled(num_selected == 1)
        copy_as_requires_action.triggered.connect(self._copy_as_requires_json)
        menu.addAction(copy_as_requires_action)

        menu.addSeparator()

        add_new_action = QAction("Add New Choice", self)
        add_new_action.triggered.connect(self._add_item)
        menu.addAction(add_new_action)

        delete_action = QAction("Delete Selected", self)
        delete_action.setEnabled(num_selected > 0)
        delete_action.triggered.connect(self._delete_item)
        menu.addAction(delete_action)

        duplicate_action = QAction("Duplicate Selected", self)
        duplicate_action.setEnabled(num_selected > 0)
        duplicate_action.triggered.connect(self._duplicate_items)
        menu.addAction(duplicate_action)

        menu.exec(self.tree.mapToGlobal(pos))

    @Slot(QTreeWidgetItem, int)
    def _on_double_click_item(self, item: QTreeWidgetItem, column: int):
        # Get current values from the item
        current_values = (
            item.text(0), # Value
            item.text(1), # Weight
            item.text(2), # Tags
            item.text(3), # Requires
            item.text(4)  # Includes
        )
        
        dialog = EditChoiceDialog(self, "Edit Choice", initial_values=current_values, processor=self.processor)
        if dialog.exec() == QDialog.Accepted and dialog.result:
            new_values = dialog.result
            
            # Update the QTreeWidgetItem
            for i, value in enumerate(new_values):
                item.setText(i, str(value))
            
            # Update the internal data structure (iid_to_choice_map)
            new_choice_obj = self._get_choice_from_values_tuple(new_values)
            item.setData(0, Qt.UserRole, new_choice_obj) # Update stored object
            self.iid_to_choice_map[id(item)] = new_choice_obj
            
            self._validate_all_items()
            self.dataChanged.emit()

    @Slot(QTreeWidgetItem, int)
    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        # This slot is triggered by in-place edits or check state changes
        # For now, just emit dataChanged
        self.dataChanged.emit()
        self.validation_debounce_timer.start()

    def _copy_as_requires_json(self):
        selected_items = self.tree.selectedItems()
        if len(selected_items) != 1:
            return
        
        item = selected_items[0]
        choice_obj = self.iid_to_choice_map.get(id(item))
        if not choice_obj:
            return

        value = choice_obj.get('value') if isinstance(choice_obj, dict) else choice_obj
        
        # Assuming the parent widget (ReviewAndSaveDialog) has a way to get the current filename
        # Or, if used in WildcardManagerWindow, it would have current_filename_callback
        # For this context, we'll just use a placeholder for the wildcard name.
        wildcard_name = "current_wildcard" # Placeholder

        req_dict = {wildcard_name: value}
        req_json = json.dumps(req_dict)

        clipboard = QApplication.clipboard()
        clipboard.setText(req_json)
        QMessageBox.information(self, "Copied", "Requires JSON copied to clipboard.")

    def _duplicate_items(self):
        selected_items = self.tree.selectedItems()
        if not selected_items:
            return

        for item in reversed(selected_items): # Reverse to insert correctly after each original
            original_choice = self.iid_to_choice_map.get(id(item))
            if not original_choice:
                continue

            # Deep copy the underlying data object to avoid shared references
            new_choice_obj = copy.deepcopy(original_choice)

            # Get the display values from the tree
            original_values = [item.text(i) for i in range(self.tree.columnCount())]
            new_values = original_values[:] # Create a copy

            # Modify the value to indicate it's a copy
            if isinstance(new_choice_obj, dict):
                new_value_str = f"{new_choice_obj.get('value', '')} (copy)"
                new_choice_obj['value'] = new_value_str
                new_values[0] = new_value_str
            else: # It's a string
                new_value_str = f"{original_choice} (copy)"
                new_choice_obj = new_value_str # The object itself is the new string
                new_values[0] = new_value_str

            # Insert the new item into the treeview, right after the original
            original_index = self.tree.indexOfTopLevelItem(item)
            new_item = QTreeWidgetItem(self.tree)
            for i, value in enumerate(new_values):
                new_item.setText(i, str(value))
            
            # Update the map with the new item's ID and its new data object
            new_item.setData(0, Qt.UserRole, new_choice_obj)
            self.iid_to_choice_map[id(new_item)] = new_choice_obj
            
            self.tree.insertTopLevelItem(original_index + 1, new_item)
            self._validate_all_items()
        self.dataChanged.emit()

    @Slot()
    def _insert_include_wildcard(self):
        dialog = WildcardSelectorDialog(self, self.processor)
        if dialog.exec() == QDialog.Accepted and dialog.result:
            for wildcard_name in dialog.result:
                self.includes_text.insertPlainText(f"[{wildcard_name}] ")
            self.dataChanged.emit()
            self.validation_debounce_timer.start()

    def _on_includes_text_changed(self):
        self.dataChanged.emit()
        self.validation_debounce_timer.start()

        cursor = self.includes_text.textCursor()
        text_before_cursor = self.includes_text.toPlainText()[:cursor.position()]
        
        match = re.search(r'\[([a-zA-Z0-9_.-]*)$', text_before_cursor)
        if not match:
            if self.autocomplete_popup:
                self.autocomplete_popup.close()
            return

        prefix = match.group(1)
        all_wildcards = self.processor.get_wildcard_names() if self.processor else []
        suggestions = [wc for wc in all_wildcards if wc.lower().startswith(prefix.lower())]

        if suggestions:
            self._show_autocomplete(suggestions)
        elif self.autocomplete_popup:
            self.autocomplete_popup.close()

    def _show_autocomplete(self, suggestions: List[str]):
        if not self.autocomplete_popup:
            self.autocomplete_popup = _AutocompletePopup(self)
            self.autocomplete_popup.suggestionSelected.connect(self._insert_completion)

        self.autocomplete_popup.set_suggestions(suggestions)
        
        cursor_rect = self.includes_text.cursorRect()
        global_pos = self.includes_text.mapToGlobal(cursor_rect.bottomLeft())
        self.autocomplete_popup.move(global_pos)
        self.autocomplete_popup.show()

    def _insert_completion(self, completion: str):
        cursor = self.includes_text.textCursor()
        text_before_cursor = self.includes_text.toPlainText()[:cursor.position()]
        match = re.search(r'\[([a-zA-Z0-9_.-]*)$', text_before_cursor)
        if not match:
            return
        
        start_pos = cursor.position() - len(match.group(1))
        cursor.setPosition(start_pos)
        cursor.setPosition(cursor.position(), QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(f"{completion}] ")
        self.includes_text.setTextCursor(cursor)
        if self.autocomplete_popup:
            self.autocomplete_popup.close()

    def _validate_all_items(self):
        self.item_errors.clear()
        self.file_error_label.setText("")
        
        all_known_wildcards = self.processor.get_wildcard_names() if self.processor else []

        # --- Pre-calculate global errors once to avoid redundant checks ---
        global_include_errors = []
        global_includes_text = self.includes_text.toPlainText().strip()
        if global_includes_text:
            # Find wildcards in both __wildcard__ and [wildcard] format
            global_includes = re.findall(r'__([a-zA-Z0-9_.-]+)__', global_includes_text)
            global_includes.extend(re.findall(r'\[([a-zA-Z0-9_.-]+)\]', global_includes_text))
            
            for wc in set(global_includes): # Use set to check each unique name only once
                if wc not in all_known_wildcards:
                    global_include_errors.append(f"Global include '{wc}' not found.")

        for iid_item in self.tree.findItems("", Qt.MatchContains | Qt.MatchRecursive):
            self._validate_item(iid_item, all_known_wildcards, global_include_errors)
        
        # Perform file-level validation like circular dependency checks
        # This part needs context from the parent WildcardManagerWindow, so it will be handled there
        # For now, just clear the file error label
        self.file_error_label.setText("")
        
        self.update_theme() # Re-apply colors based on new validation state

    def _validate_item(self, iid_item: QTreeWidgetItem, all_known_wildcards: List[str], global_errors: List[str]):
        """Validates a single item in the treeview for dependency errors."""
        choice_obj = self.iid_to_choice_map.get(id(iid_item))
        errors = global_errors[:] # Start with a copy of global errors

        # --- Check Choice-Specific Properties ---
        if isinstance(choice_obj, dict):
            # Validate choice-level includes
            choice_includes = choice_obj.get('includes')
            if isinstance(choice_includes, list):
                for wc in choice_includes:
                    if wc not in all_known_wildcards:
                        errors.append(f"Choice include '{wc}' not found.")
            elif isinstance(choice_includes, str):
                found_in_str = re.findall(r'__([a-zA-Z0-9_.-]+)__', choice_includes)
                for wc in found_in_str:
                    if wc not in all_known_wildcards:
                        errors.append(f"Choice include '{wc}' not found.")

            # Validate requires
            rules = choice_obj.get('requires')
            if isinstance(rules, dict):
                self._check_rules_recursive(rules, errors, all_known_wildcards)

        # --- Update UI based on errors ---
        if errors:
            self.item_errors[id(iid_item)] = sorted(list(set(errors))) # Remove duplicate error messages
            # Store tags with the item for update_theme
            iid_item.setData(0, Qt.UserRole + 1, [self.validation_error_tag])
        else:
            if id(iid_item) in self.item_errors:
                del self.item_errors[id(iid_item)]
            iid_item.setData(0, Qt.UserRole + 1, []) # Clear tags

    def _check_rules_recursive(self, rules: Dict, errors: List[str], all_known_wildcards: List[str]):
        """Recursively checks 'requires' rules for non-existent wildcards and values."""
        for key, condition in rules.items():
            if key in ['and', 'or', 'not']:
                sub_rules = condition if isinstance(condition, list) else [condition]
                for sub_rule in sub_rules:
                    if isinstance(sub_rule, dict):
                        self._check_rules_recursive(sub_rule, errors, all_known_wildcards)
            elif key != 'tags': # It's a wildcard name
                if key not in all_known_wildcards:
                    errors.append(f"Requires non-existent wildcard: '{key}'")
                    continue

                # This part needs access to processor.get_wildcard_options, which is not directly available here
                # For now, we'll just check if the wildcard exists.
                # target_wc_options = self.processor.get_wildcard_options(key)
                # values_to_check = []
                # if isinstance(condition, str): values_to_check.append(condition)
                # elif isinstance(condition, list): values_to_check.extend(condition)
                # elif isinstance(condition, dict):
                #     if 'any' in condition and isinstance(condition['any'], list): values_to_check.extend(condition['any'])
                #     if 'not' in condition:
                #         not_val = condition['not']
                #         if isinstance(not_val, str): values_to_check.append(not_val)
                #         elif isinstance(not_val, list): values_to_check.extend(not_val)
                
                # for v in values_to_check:
                #     if str(v) not in target_wc_options:
                #         errors.append(f"Requires value '{v}' not found in '{key}'.")
