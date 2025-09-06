"""
A structured editor for the JSON-based wildcard files, providing a
user-friendly alternative to raw text editing.
"""

import tkinter as tk
import re
import os
import copy
import json
import sys
from tkinter import ttk
import difflib
from typing import Dict, List, Any, Optional, Tuple, Callable, TYPE_CHECKING
from .common import Tooltip, TextContextMenu
from . import custom_dialogs # Keep this for WildcardSelectorDialog

if TYPE_CHECKING:
    from .wildcard_manager import WildcardManagerWindow
    from core.prompt_processor import PromptProcessor

class _AutocompletePopup(tk.Toplevel):
    """A popup window for autocomplete suggestions."""
    def __init__(self, parent, suggestions, x, y, insert_callback):
        super().__init__(parent)
        self.overrideredirect(True)
        self.wm_geometry(f"+{x}+{y}")
        self.insert_callback = insert_callback

        self.listbox = tk.Listbox(self, height=min(10, len(suggestions)), exportselection=False)
        self.listbox.pack(fill=tk.BOTH, expand=True)

        for suggestion in suggestions:
            self.listbox.insert(tk.END, suggestion)
        
        if suggestions:
            self.listbox.selection_set(0)

        self.listbox.bind("<Return>", self._on_select)
        self.listbox.bind("<Escape>", lambda e: self.destroy())
        self.listbox.bind("<Double-Button-1>", self._on_select)
        
        self.listbox.focus_set()
        self.bind("<FocusOut>", lambda e: self.destroy())

    def _on_select(self, event=None):
        selection = self.listbox.curselection()
        if selection:
            self.insert_callback(self.listbox.get(selection[0]))
        self.destroy()


class WildcardEditor(ttk.Frame):
    """A structured editor for wildcard files."""
    def __init__(self, parent, processor: 'PromptProcessor', suggestion_callback: Optional[Callable] = None, refinement_callback: Optional[Callable] = None, autotag_callback: Optional[Callable] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.processor = processor
        self.suggestion_callback = suggestion_callback
        self.refinement_callback = refinement_callback
        self.autotag_callback = autotag_callback
        self.iid_to_choice_map: Dict[str, Any] = {}
        # The parent is a frame inside the WildcardManagerWindow.
        self.autocomplete_popup: Optional[_AutocompletePopup] = None
        self.validation_error_tag = "validation_error"
        self.item_errors: Dict[str, List[str]] = {} # Map iid to list of error messages
        self.validation_debounce_timer: Optional[str] = None
        # self.winfo_toplevel() will give us the WildcardManagerWindow instance, which has parent_app.
        self.parent_app = self.winfo_toplevel().parent_app
        self.inplace_edit_entry: Optional[ttk.Entry] = None

        # Define colors for included items
        self.included_tag = "included"
        self.duplicate_tag = "duplicate"
        self._create_widgets()
        self.error_tooltip = Tooltip(self.tree)
        self.error_tooltip_after_id: Optional[str] = None
        self.last_hovered_iid: Optional[str] = None
        self.update_theme() # Set initial theme-based colors

    def _create_widgets(self):
        # --- Description ---
        desc_frame = ttk.Frame(self)
        desc_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(desc_frame, text="Description:").pack(side=tk.LEFT, padx=(0, 5))
        self.description_entry = ttk.Entry(desc_frame)
        self.description_entry.pack(fill=tk.X, expand=True)

        self.file_error_label = ttk.Label(self, text="", foreground="red", wraplength=500)
        self.file_error_label.pack(fill=tk.X, pady=(0, 5), padx=5)

        # --- Main Vertical Paned Window for a more compact layout ---
        main_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        # --- Choices Pane (Top) ---
        choices_frame = ttk.LabelFrame(main_pane, text="Choices", padding=5)
        main_pane.add(choices_frame, weight=4)

        choices_toolbar = ttk.Frame(choices_frame)
        choices_toolbar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(choices_toolbar, text="Add", command=self._add_item).pack(side=tk.LEFT)
        ttk.Button(choices_toolbar, text="Mass Edit...", command=self._mass_edit_choices).pack(side=tk.LEFT, padx=5)
        ttk.Button(choices_toolbar, text="Delete", command=self._delete_item).pack(side=tk.LEFT, padx=5)

        # AI buttons on the right
        ai_button_frame = ttk.Frame(choices_toolbar)
        ai_button_frame.pack(side=tk.RIGHT)
        self.suggest_button = ttk.Button(ai_button_frame, text="Suggest Choices (AI)", command=self._on_suggest_choices, state=tk.DISABLED)
        self.suggest_button.pack(side=tk.LEFT)
        self.refine_button = ttk.Button(ai_button_frame, text="Refine Choices (AI)", command=self._on_refine_choices, state=tk.DISABLED)
        self.refine_button.pack(side=tk.LEFT, padx=(5,0))
        self.autotag_button = ttk.Button(ai_button_frame, text="Auto-Tag All (AI)", command=self._on_auto_tag_choices, state=tk.DISABLED)
        self.autotag_button.pack(side=tk.LEFT, padx=(5,0))

        tree_container = ttk.Frame(choices_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)

        columns = ('value', 'weight', 'tags', 'requires', 'includes')
        self.tree = ttk.Treeview(tree_container, columns=columns, show='headings', selectmode=tk.EXTENDED)
        self.tree.heading('value', text='Value')
        self.tree.heading('weight', text='Weight')
        self.tree.heading('tags', text='Tags')
        self.tree.heading('requires', text='Requires')
        self.tree.heading('includes', text='Includes')
        self.tree.column('value', width=200)
        self.tree.column('weight', width=50, anchor='center')
        self.tree.column('tags', width=100)
        self.tree.column('requires', width=150)
        self.tree.column('includes', width=150)
        tree_scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Double-1>", self._on_double_click_item)

        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)

        # Add context menu
        self._create_context_menu()
        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        self.tree.bind(right_click_event, self._show_context_menu)

        # --- Includes Pane (Bottom) ---
        includes_frame = ttk.LabelFrame(main_pane, text="Global Includes (as list or template string)", padding=5)
        main_pane.add(includes_frame, weight=1)

        includes_toolbar = ttk.Frame(includes_frame)
        includes_toolbar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(includes_toolbar, text="Insert Wildcard...", command=self._insert_include_wildcard).pack(side=tk.LEFT)

        # The new text widget for includes
        self.includes_text = tk.Text(includes_frame, height=5, wrap=tk.WORD, undo=True, exportselection=False)
        self.includes_text.bind("<KeyRelease>", self._on_includes_key_release)
        self.includes_text.pack(fill=tk.BOTH, expand=True)

    def _get_included_choices(self, includes: List[str]) -> Dict[str, List[str]]:
        """Get all choices from included wildcards with their source files."""
        included_choices: Dict[str, List[str]] = {}
        
        for include_name in includes:
            # Get data from the processor's in-memory cache, which is much more reliable
            included_data = self.processor.template_engine.wildcards.get(include_name)
            
            if included_data and 'choices' in included_data:
                for choice in included_data['choices']:
                    value = None
                    if isinstance(choice, str):
                        value = choice
                    elif isinstance(choice, dict) and 'value' in choice:
                        value = choice['value']
                    
                    if value is not None:
                        if value not in included_choices:
                            included_choices[value] = []
                        included_choices[value].append(include_name)
                
        return included_choices

    def set_data(self, data: Dict[str, Any]):
        """Set the editor data and highlight included choices."""
        self.clear_highlights() # Always clear highlights when loading new data

        self.description_entry.delete(0, tk.END)
        self.description_entry.insert(0, data.get('description', ''))
        
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.iid_to_choice_map.clear()
        
        # Get all choices from includes
        includes_data = data.get('includes')
        includes_for_check = []
        if isinstance(includes_data, list):
            includes_for_check = includes_data
        elif isinstance(includes_data, str):
            # If it's a string, parse wildcards from it for highlighting
            includes_for_check = list(set(re.findall(r'__([a-zA-Z0-9_.-]+)__', includes_data)))
        included_choices = self._get_included_choices(includes_for_check)
            
        # Add choices and highlight those from includes
        choices = data.get('choices', [])
        for choice in choices:
            if isinstance(choice, str):
                item_id = self.tree.insert('', tk.END, values=(choice, '', '', '', ''))
                self.iid_to_choice_map[item_id] = choice
                if choice in included_choices:
                    self.tree.item(item_id, tags=(self.included_tag,))
            elif isinstance(choice, dict):
                value = choice.get('value', '')
                weight = choice.get('weight', '')
                tags = ", ".join(choice.get('tags', []))
                requires_dict = choice.get('requires', {})
                requires = json.dumps(requires_dict, separators=(',', ':')) if requires_dict else ""
                
                includes_val = choice.get('includes')
                if isinstance(includes_val, list):
                    includes_display = json.dumps(includes_val)
                else:
                    includes_display = includes_val or ''
                
                item_id = self.tree.insert('', tk.END, 
                    values=(value, weight, tags, requires, includes_display))
                self.iid_to_choice_map[item_id] = choice
                
                if value in included_choices:
                    self.tree.item(item_id, tags=(self.included_tag,))

        # Update includes text area, handling both string and list types
        self.includes_text.delete("1.0", tk.END)
        includes_data = data.get('includes')
        if isinstance(includes_data, str):
            self.includes_text.insert("1.0", includes_data)
        elif isinstance(includes_data, list):
            # Convert list to a display string of bracketed wildcards for easy editing
            display_str = " ".join([f"[{w}]" for w in includes_data])
            self.includes_text.insert("1.0", display_str)

        # Update refine button state
        has_choices = bool(choices)

        self._validate_all_items()
        self.refine_button.config(state=tk.NORMAL if has_choices else tk.DISABLED)
        self.autotag_button.config(state=tk.NORMAL if has_choices else tk.DISABLED)

    def get_data(self) -> Dict[str, Any]:
        """Constructs the JSON data object from the UI widgets."""
        choices = [self._get_choice_from_tree_item(iid) for iid in self.tree.get_children()]
        
        includes_text = self.includes_text.get("1.0", "end-1c").strip()
        data_dict = {"description": self.description_entry.get(), "choices": choices}
        
        if includes_text:
            # Check if the text consists only of bracketed wildcards, suggesting it should be a list
            bracket_wildcards = re.findall(r'\[([a-zA-Z0-9_.-]+)\]', includes_text)
            reconstructed_text = " ".join([f"[{w}]" for w in bracket_wildcards])
            
            if len(bracket_wildcards) > 0 and includes_text == reconstructed_text:
                data_dict['includes'] = bracket_wildcards
            else:
                data_dict['includes'] = includes_text
        
        return data_dict

    def _get_choice_from_tree_item(self, item_id) -> Any:
        """Converts a single Treeview item into a string or a dictionary."""
        item_data = self.tree.item(item_id, 'values')
        value, weight_str, tags_str, requires_str, includes_str = item_data

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
        
        # Parse includes
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

    def _get_values_tuple_from_choice(self, choice: Any) -> Tuple[str, str, str, str, str]:
        """Converts a choice object (string or dict) into a tuple for the treeview."""
        if isinstance(choice, str):
            return (choice, '', '', '', '')
        
        if not isinstance(choice, dict):
            return ('', '', '', '', '') # Should not happen, but safe fallback

        value = choice.get('value', '')
        weight = choice.get('weight', '')
        tags = ", ".join(choice.get('tags', []))
        requires_dict = choice.get('requires', {})
        requires = json.dumps(requires_dict, separators=(',', ':')) if requires_dict else ""
        
        includes_val = choice.get('includes')
        if isinstance(includes_val, list):
            # A simple representation for lists in the treeview
            includes_display = json.dumps(includes_val)
        else:
            includes_display = includes_val or ''
            
        return (str(value), str(weight), str(tags), str(requires), str(includes_display))

    def _add_item(self):
        """Opens a dialog to add a new choice, then inserts it into the tree."""
        initial_values = ('', '1', '', '', '') # Start with an empty value and default weight
        manager_window = self.winfo_toplevel()
        is_in_manager = hasattr(manager_window, 'wildcard_listbox')

        if is_in_manager:
            manager_window.dialog_is_open = True
            manager_window.wildcard_listbox.unbind("<<ListboxSelect>>")

        try:
            dialog = custom_dialogs.EditChoiceDialog(self, "Add New Choice", initial_values, self.processor)
            if dialog.result:
                new_values = dialog.result
                
                # Don't add if the value is empty
                if not new_values[0].strip():
                    return

                item_id = self.tree.insert('', tk.END, values=new_values)
                new_choice_obj = self._get_choice_from_tree_item(item_id)
                self.iid_to_choice_map[item_id] = new_choice_obj
                self._validate_item(item_id)

                self.tree.see(item_id)
                self.tree.selection_set(item_id)

                if hasattr(manager_window, 'save_button'):
                    manager_window.save_button.config(state=tk.NORMAL)
        finally:
            try:
                if is_in_manager and manager_window.winfo_exists():
                    manager_window.dialog_is_open = False
                    manager_window.wildcard_listbox.bind("<<ListboxSelect>>", manager_window._on_wildcard_file_select)
            except tk.TclError:
                pass # Window was likely destroyed.

    def _mass_edit_choices(self):
        """Opens a dialog to mass-edit choice values as plain text."""
        current_choices = self.get_data().get('choices', [])
        if not current_choices:
            return

        # Extract just the values for the text editor
        initial_text = "\n".join([str(c.get('value') if isinstance(c, dict) else c) for c in current_choices])

        # Unbind focus to prevent issues with the dialog
        manager_window = self.winfo_toplevel()
        is_in_manager = hasattr(manager_window, 'wildcard_listbox')
        if is_in_manager:
            manager_window.dialog_is_open = True
            manager_window.wildcard_listbox.unbind("<<ListboxSelect>>")

        try:
            dialog = custom_dialogs.MassEditDialog(self, initial_text, self.processor)
            if dialog.result is not None:
                self._process_mass_edit(current_choices, dialog.result)
        finally:
            try:
                if is_in_manager and manager_window.winfo_exists():
                    manager_window.dialog_is_open = False
                    manager_window.wildcard_listbox.bind("<<ListboxSelect>>", manager_window._on_wildcard_file_select)
            except tk.TclError:
                pass # Window was likely destroyed.

    def _process_mass_edit(self, original_choices: List[Any], new_text: str):
        """Compares the original choices with the new text and applies changes."""
        original_values = [str(c.get('value') if isinstance(c, dict) else c) for c in original_choices]
        new_values = [line.strip() for line in new_text.splitlines() if line.strip()]

        # Check if there are any actual changes before proceeding
        if original_values == new_values:
            return # No changes, do nothing.

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
        
        self.set_data({'description': self.description_entry.get(), 'choices': final_choices})

        # After applying changes, enable the save button on the parent window.
        manager_window = self.winfo_toplevel()
        if hasattr(manager_window, 'save_button'):
            manager_window.save_button.config(state=tk.NORMAL)

    def _delete_item(self):
        for selected_item in self.tree.selection():
            if selected_item in self.iid_to_choice_map:
                del self.iid_to_choice_map[selected_item]
            self.tree.delete(selected_item)

    def _edit_cell_in_place(self, event):
        """Handles in-place editing of a cell in the treeview."""
        # First, destroy any existing in-place editor to prevent conflicts
        if self.inplace_edit_entry:
            self.inplace_edit_entry.destroy()
            self.inplace_edit_entry = None

        # Identify what was clicked
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        column_id = self.tree.identify_column(event.x)
        item_id = self.tree.identify_row(event.y)
        if not item_id: return

        # Only allow in-place editing for the 'value' and 'weight' columns
        if column_id not in ['#1', '#2']: # 'value', 'weight'
            self._open_full_edit_dialog(item_id)
            return

        # Get cell geometry
        x, y, width, height = self.tree.bbox(item_id, column_id)

        # Create and place the entry widget
        self.inplace_edit_entry = ttk.Entry(self.tree, justify='left')
        self.inplace_edit_entry.place(x=x, y=y, width=width, height=height)

        # Get current value and populate the entry
        current_value = self.tree.set(item_id, column_id)
        self.inplace_edit_entry.insert(0, current_value)
        self.inplace_edit_entry.select_range(0, tk.END)
        self.inplace_edit_entry.focus_set()

        # Bind events to save or cancel the edit
        self.inplace_edit_entry.bind("<Return>", lambda e, i=item_id, c=column_id: self._save_inplace_edit(i, c))
        self.inplace_edit_entry.bind("<FocusOut>", lambda e, i=item_id, c=column_id: self._save_inplace_edit(i, c))
        self.inplace_edit_entry.bind("<Escape>", lambda e: self.inplace_edit_entry.destroy())

    def _save_inplace_edit(self, item_id: str, column_id: str):
        """Saves the content of the in-place editor back to the tree and data model."""
        if not self.inplace_edit_entry:
            return

        new_value = self.inplace_edit_entry.get()
        self.inplace_edit_entry.destroy()
        self.inplace_edit_entry = None

        # Update the treeview display
        self.tree.set(item_id, column_id, new_value)

        # Update the underlying data model
        choice_obj = self.iid_to_choice_map.get(item_id)
        if choice_obj:
            column_key = self.tree.heading(column_id, "text").lower() # 'value' or 'weight'
            if isinstance(choice_obj, dict):
                choice_obj[column_key] = new_value
            elif column_key == 'value': # It was a simple string
                self.iid_to_choice_map[item_id] = new_value

        self._validate_item(item_id)
        self.winfo_toplevel().save_button.config(state=tk.NORMAL)

    def _on_double_click_item(self, event):
        """Handles a double-click event, routing it to in-place or full dialog editing."""
        self._edit_cell_in_place(event)

    def _open_full_edit_dialog_from_selection(self):
        """Wrapper to open the full edit dialog for the current selection."""
        selection = self.tree.selection()
        if len(selection) != 1: return
        item_id = selection[0]
        self._open_full_edit_dialog(item_id)

    def _open_full_edit_dialog(self, item_id: str):
        """Opens the full, multi-field edit dialog for a given item."""
        original_choice_obj = copy.deepcopy(self.iid_to_choice_map.get(item_id)) # Get a snapshot before editing
        original_values = self.tree.item(item_id, 'values')
        original_value_str = original_values[0] if original_values else ""

        manager_window = self.winfo_toplevel()

        # This editor can be used in WildcardManager or ReviewAndSaveWindow.
        # The focus-loss issue only applies to the WildcardManager, which has a listbox.
        # We check for the listbox to avoid crashing in other contexts.
        is_in_manager = hasattr(manager_window, 'wildcard_listbox')

        if is_in_manager:
            manager_window.dialog_is_open = True
            manager_window.wildcard_listbox.unbind("<<ListboxSelect>>")

        try:
            dialog = custom_dialogs.EditChoiceDialog(self, "Edit Choice", original_values, self.processor)
            if dialog.result:
                new_values = dialog.result
                new_value_str = new_values[0] if new_values else ""
                
                # Check if the value changed and register it for refactoring
                if new_value_str != original_value_str and hasattr(manager_window, 'register_value_change'):
                    manager_window.register_value_change(original_value_str, new_value_str)

                self.tree.item(item_id, values=new_values)
                updated_choice = self._get_choice_from_tree_item(item_id)
                self.iid_to_choice_map[item_id] = updated_choice
                self._validate_item(item_id)

                # After a successful edit, check if we can apply this fix to other items.
                self._find_and_offer_mass_fix(item_id, original_choice_obj, updated_choice)

        finally:
            try:
                # Always re-bind the event to restore normal functionality if it was unbound
                if is_in_manager and manager_window.winfo_exists():
                    manager_window.dialog_is_open = False
                    manager_window.wildcard_listbox.bind("<<ListboxSelect>>", manager_window._on_wildcard_file_select)
            except tk.TclError:
                pass # Window was likely destroyed.

    def _on_suggest_choices(self):
        """Callback to ask the manager window to trigger AI suggestions."""
        if self.suggestion_callback:
            current_data = self.get_data()
            self.suggestion_callback(current_data)

    def _on_refine_choices(self):
        """Callback to ask the manager window to trigger AI refinement."""
        if self.refinement_callback:
            current_data = self.get_data()
            self.refinement_callback(current_data)

    def _on_auto_tag_choices(self):
        """Callback to ask the manager window to trigger AI auto-tagging."""
        if self.autotag_callback:
            current_data = self.get_data()
            self.autotag_callback(current_data)

    def _find_and_offer_mass_fix(self, edited_item_id: str, original_choice: Any, updated_choice: Any):
        """
        After an item is edited, this checks if the change can be applied to other
        items with the same original, problematic property.
        """
        # Standardize to dicts for easier comparison
        original_dict = original_choice if isinstance(original_choice, dict) else {'value': original_choice}
        updated_dict = updated_choice if isinstance(updated_choice, dict) else {'value': updated_choice}

        # Find all keys that have changed
        all_keys = set(original_dict.keys()) | set(updated_dict.keys())
        changed_keys = {key for key in all_keys if original_dict.get(key) != updated_dict.get(key)}

        if not changed_keys:
            return

        # For now, let's focus on one change at a time to keep the UX simple.
        key_to_fix = list(changed_keys)[0]
        
        original_value = original_dict.get(key_to_fix)
        new_value = updated_dict.get(key_to_fix)

        # Find other items with the exact same problematic value for the changed key
        matches_to_fix = []
        for iid, choice_obj in self.iid_to_choice_map.items():
            if iid == edited_item_id: continue

            current_dict = choice_obj if isinstance(choice_obj, dict) else {'value': choice_obj}
            if current_dict.get(key_to_fix) == original_value:
                matches_to_fix.append(iid)

        if not matches_to_fix:
            return

        # Prompt the user
        message = (
            f"You changed the '{key_to_fix}' property.\n\n"
            f"Original: {str(original_value)}\n"
            f"New: {str(new_value)}\n\n"
            f"Found {len(matches_to_fix)} other choice(s) with the same original value. "
            f"Would you like to apply this fix to all of them?"
        )
        
        if custom_dialogs.ask_yes_no(self, "Apply Fix to Similar Items?", message):
            for iid in matches_to_fix:
                choice_to_update = copy.deepcopy(self.iid_to_choice_map[iid])
                if isinstance(choice_to_update, str): choice_to_update = {'value': choice_to_update}
                
                if new_value is None: del choice_to_update[key_to_fix]
                else: choice_to_update[key_to_fix] = new_value
                
                self.iid_to_choice_map[iid] = choice_to_update if len(choice_to_update) > 1 or 'value' not in choice_to_update else choice_to_update['value']
                self.tree.item(iid, values=self._get_values_tuple_from_choice(choice_to_update))
                self._validate_item(iid)
            
            custom_dialogs.show_info(self, "Mass Fix Applied", f"Updated {len(matches_to_fix)} other choices.")
            self.winfo_toplevel().save_button.config(state=tk.NORMAL)

    def update_choice_value(self, item_id: str, new_value: str):
        """Updates the value of a specific choice by its item ID."""
        if item_id not in self.iid_to_choice_map:
            return

        # Update the treeview display
        self.tree.set(item_id, 'value', new_value)

        # Update the underlying data model
        choice_obj = self.iid_to_choice_map.get(item_id)
        if choice_obj:
            if isinstance(choice_obj, dict):
                choice_obj['value'] = new_value
            else: # It was a simple string
                self.iid_to_choice_map[item_id] = new_value
        
        self._validate_item(item_id)

    def delete_choice_by_iid(self, item_id: str):
        """Deletes a specific choice by its item ID."""
        if item_id in self.iid_to_choice_map:
            del self.iid_to_choice_map[item_id]
        if self.tree.exists(item_id):
            self.tree.delete(item_id)

    def add_suggested_choices(self, new_choices: List[Any]):
        """Adds choices suggested by the AI to the treeview."""
        if not new_choices:
            return
        
        # Use set of existing values to avoid adding duplicates
        existing_values = {self.tree.item(iid, 'values')[0] for iid in self.tree.get_children()}

        for choice in new_choices:
            if isinstance(choice, str):
                if choice not in existing_values:
                    item_id = self.tree.insert('', tk.END, values=(choice, '', '', '', ''))
                    self.iid_to_choice_map[item_id] = choice
            elif isinstance(choice, dict) and 'value' in choice:
                if choice['value'] not in existing_values:
                    value = choice.get('value', '')
                    weight = choice.get('weight', '')
                    tags = ", ".join(choice.get('tags', []))
                    
                    requires_dict = choice.get('requires', {})
                    # Correctly serialize the requires dict to a JSON string
                    requires = json.dumps(requires_dict, separators=(',', ':')) if requires_dict else ""

                    includes = ", ".join(choice.get('includes', []))
                    item_id = self.tree.insert('', tk.END, values=(value, weight, tags, requires, includes))
                    self.iid_to_choice_map[item_id] = choice

    def update_with_refined_choices(self, refined_choices: List[Any]):
        """Replaces the current choices with a refined list from the AI."""
        if not refined_choices:
            return

        # Get the current full data structure
        current_data = self.get_data()
        
        # Replace the old choices list with the new
        current_data['choices'] = refined_choices
        
        # Reload the editor with the updated data
        self.set_data(current_data)

    def update_with_tagged_choices(self, tagged_choices: List[Any]):
        """Replaces the current choices with a tagged list from the AI."""
        if not tagged_choices:
            return

        current_data = self.get_data()
        
        # Replace the old choices list with the new tagged one
        current_data['choices'] = tagged_choices
        self.set_data(current_data)

    def _insert_include_wildcard(self):
        """Opens a dialog to select wildcards and inserts them into the includes text widget."""
        manager_window = self.winfo_toplevel()
        is_in_manager = hasattr(manager_window, 'wildcard_listbox')

        if is_in_manager:
            manager_window.dialog_is_open = True
            manager_window.wildcard_listbox.unbind("<<ListboxSelect>>")
        
        try:
            dialog = custom_dialogs.WildcardSelectorDialog(self, self.processor)
            if dialog.result:
                for wildcard in dialog.result:
                    self.includes_text.insert(tk.INSERT, f"[{wildcard}] ")
                self._refresh_ui_from_includes_change()
        finally:
            try:
                if is_in_manager and manager_window.winfo_exists():
                    manager_window.dialog_is_open = False
                    manager_window.wildcard_listbox.bind("<<ListboxSelect>>", manager_window._on_wildcard_file_select)
            except tk.TclError:
                pass # Window was likely destroyed.

    def _refresh_ui_from_includes_change(self):
        """Refreshes the editor data to update highlighting after an include change."""
        self.set_data(self.get_data())

    def clear_highlights(self):
        """Removes all custom highlighting tags from the tree."""
        tags_to_remove = [self.duplicate_tag, self.validation_error_tag]
        for item_id in self.tree.get_children():
            current_tags = list(self.tree.item(item_id, 'tags'))
            new_tags = [tag for tag in current_tags if tag not in tags_to_remove]
            self.tree.item(item_id, tags=tuple(new_tags))

    def highlight_duplicates(self, iids_to_highlight: List[str]):
        """Applies the duplicate highlight tag to a list of item IDs."""
        for item_id in iids_to_highlight:
            current_tags = list(self.tree.item(item_id, 'tags'))
            if self.duplicate_tag not in current_tags:
                current_tags.append(self.duplicate_tag)
                self.tree.item(item_id, tags=tuple(current_tags))

    def highlight_validation_error(self, iid_to_highlight: str):
        """Applies the validation error highlight tag to a specific item ID."""
        current_tags = list(self.tree.item(iid_to_highlight, 'tags'))
        if self.validation_error_tag not in current_tags:
            current_tags.append(self.validation_error_tag)
            self.tree.item(iid_to_highlight, tags=tuple(current_tags))

    def highlight_choice_by_value(self, value_to_find: str):
        """Finds a choice by its value and applies the validation error highlight."""
        self.clear_highlights()
        for iid, choice_obj in self.iid_to_choice_map.items():
            value = choice_obj if isinstance(choice_obj, str) else choice_obj.get('value')
            if str(value) == str(value_to_find):
                self.highlight_validation_error(iid)
                self.tree.see(iid)
                self.tree.selection_set(iid)
                break

    def update_theme(self):
        """Updates the tag colors in the treeview to match the current theme."""
        is_dark = self.parent_app.theme_manager.current_theme == "dark"

        included_bg = "#2c3e50" if is_dark else "#e6f3ff" # Dark muted blue / Light blue
        duplicate_bg = "#5e3333" if is_dark else "#ffcccc" # Dark muted red / Light red
        validation_error_bg = "#6b4226" if is_dark else "#ffe4b5" # Dark muted orange / Moccasin

        self.tree.tag_configure(
            self.included_tag, 
            background=included_bg
        )
        self.tree.tag_configure(
            self.duplicate_tag,
            background=duplicate_bg
        )
        self.tree.tag_configure(
            self.validation_error_tag,
            background=validation_error_bg
        )

    def _on_includes_key_release(self, event):
        """Handle key release in the includes text widget for validation and autocomplete."""
        self._schedule_validation()

        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return

        cursor_index = self.includes_text.index(tk.INSERT)
        line_start = self.includes_text.index(f"{cursor_index} linestart")
        text_before_cursor = self.includes_text.get(line_start, cursor_index)
        
        match = re.search(r'\[([a-zA-Z0-9_.-]*)$', text_before_cursor)
        if not match:
            if self.autocomplete_popup: self.autocomplete_popup.destroy()
            return

        prefix = match.group(1)
        all_wildcards = self.processor.get_wildcard_names()
        suggestions = [wc for wc in all_wildcards if wc.lower().startswith(prefix.lower())]

        if suggestions: self._show_autocomplete(suggestions)
        elif self.autocomplete_popup: self.autocomplete_popup.destroy()

    def _show_autocomplete(self, suggestions):
        if self.autocomplete_popup: self.autocomplete_popup.destroy()
        cursor_bbox = self.includes_text.bbox(tk.INSERT)
        if not cursor_bbox: return
        x = self.includes_text.winfo_rootx() + cursor_bbox[0]
        y = self.includes_text.winfo_rooty() + cursor_bbox[1] + cursor_bbox[3]
        self.autocomplete_popup = _AutocompletePopup(self, suggestions, x, y, self._insert_completion)

    def _insert_completion(self, completion):
        cursor_index = self.includes_text.index(tk.INSERT)
        line_start = self.includes_text.index(f"{cursor_index} linestart")
        text_before_cursor = self.includes_text.get(line_start, cursor_index)
        match = re.search(r'\[([a-zA-Z0-9_.-]*)$', text_before_cursor)
        if not match: return
        start_replace = self.includes_text.index(f"{cursor_index} - {len(match.group(1))}c")
        self.includes_text.delete(start_replace, cursor_index)
        self.includes_text.insert(start_replace, f"{completion}] ")
        if self.autocomplete_popup: self.autocomplete_popup.destroy()

    def _schedule_validation(self, event=None):
        """Schedules a validation check to run after a short delay."""
        if self.validation_debounce_timer:
            self.after_cancel(self.validation_debounce_timer)
        self.validation_debounce_timer = self.after(750, self._validate_all_items)

    def _on_tree_motion(self, event):
        """Schedules an error tooltip to appear after a short delay."""
        if self.error_tooltip_after_id:
            self.after_cancel(self.error_tooltip_after_id)

        iid = self.tree.identify_row(event.y)
        
        if iid != self.last_hovered_iid:
            self.error_tooltip.hide()
        
        self.last_hovered_iid = iid
        
        if iid and iid in self.item_errors:
            self.error_tooltip_after_id = self.after(500, lambda: self._display_error_tooltip(iid, event))

    def _display_error_tooltip(self, iid: str, event):
        """Fetches error content and displays the tooltip."""
        if iid and iid in self.item_errors:
            error_text = "\n- ".join(self.item_errors[iid])
            self.error_tooltip.text = f"Validation Errors:\n- {error_text}"
            self.error_tooltip.show(event)

    def _on_tree_leave(self, event=None):
        """Hides the error tooltip and cancels any scheduled appearance."""
        self.last_hovered_iid = None
        if self.error_tooltip_after_id:
            self.after_cancel(self.error_tooltip_after_id)
            self.error_tooltip_after_id = None
        self.error_tooltip.hide()

    def _validate_all_items(self):
        """Runs validation on all items in the treeview."""
        self.item_errors.clear()
        for iid in self.tree.get_children():
            self._validate_item(iid)
        
        # Perform file-level validation like circular dependency checks
        self.file_error_label.config(text="") # Clear previous error
        manager_window = self.winfo_toplevel()
        if hasattr(manager_window, 'selected_wildcard_file') and manager_window.selected_wildcard_file:
            current_wildcard_name, _ = os.path.splitext(manager_window.selected_wildcard_file)
            cycle = self.processor.check_for_circular_dependencies(current_wildcard_name, temp_node_data=self.get_data())
            if cycle:
                self.file_error_label.config(text=f"Circular dependency detected: {' -> '.join(cycle)}")

    def _validate_item(self, iid: str):
        """Validates a single item in the treeview for dependency errors."""
        choice_obj = self.iid_to_choice_map.get(iid)
        errors = []
        all_known_wildcards = self.processor.get_wildcard_names()

        # --- Check Global Includes ---
        global_includes_text = self.includes_text.get("1.0", "end-1c").strip()
        if global_includes_text:
            global_includes = re.findall(r'__([a-zA-Z0-9_.\s-]+?)__', global_includes_text)
            for wc in global_includes:
                if wc not in all_known_wildcards:
                    errors.append(f"Global include '{wc}' not found.")

        # --- Check Choice-Specific Properties ---
        if isinstance(choice_obj, dict):
            # Validate choice-level includes
            choice_includes = choice_obj.get('includes')
            if isinstance(choice_includes, list):
                for wc in choice_includes:
                    if wc not in all_known_wildcards:
                        errors.append(f"Choice include '{wc}' not found.")
            elif isinstance(choice_includes, str):
                found_in_str = re.findall(r'__([a-zA-Z0-9_.\s-]+?)__', choice_includes)
                for wc in found_in_str:
                    if wc not in all_known_wildcards:
                        errors.append(f"Choice include '{wc}' not found.")

            # Validate requires
            rules = choice_obj.get('requires')
            if isinstance(rules, dict):
                self._check_rules_recursive(rules, errors)

        # --- Update UI based on errors ---
        if errors:
            self.item_errors[iid] = sorted(list(set(errors))) # Remove duplicate error messages
            current_tags = list(self.tree.item(iid, 'tags'))
            if self.validation_error_tag not in current_tags:
                current_tags.append(self.validation_error_tag)
                self.tree.item(iid, tags=tuple(current_tags))
        else:
            if iid in self.item_errors:
                del self.item_errors[iid]
            current_tags = list(self.tree.item(iid, 'tags'))
            if self.validation_error_tag in current_tags:
                current_tags.remove(self.validation_error_tag)
                self.tree.item(iid, tags=tuple(current_tags))

    def _check_rules_recursive(self, rules: Dict, errors: List[str]):
        """Recursively checks 'requires' rules for non-existent wildcards and values."""
        all_known_wildcards = self.processor.get_wildcard_names()
        for key, condition in rules.items():
            if key in ['and', 'or', 'not']:
                sub_rules = condition if isinstance(condition, list) else [condition]
                for sub_rule in sub_rules:
                    if isinstance(sub_rule, dict): self._check_rules_recursive(sub_rule, errors)
            elif key != 'tags': # It's a wildcard name
                if key not in all_known_wildcards:
                    errors.append(f"Requires non-existent wildcard: '{key}'")
                    continue

                target_wc_options = self.processor.get_wildcard_options(key)
                values_to_check = []
                if isinstance(condition, str): values_to_check.append(condition)
                elif isinstance(condition, list): values_to_check.extend(condition)
                elif isinstance(condition, dict):
                    if 'any' in condition and isinstance(condition['any'], list): values_to_check.extend(condition['any'])
                    if 'not' in condition:
                        not_val = condition['not']
                        if isinstance(not_val, str): values_to_check.append(not_val)
                        elif isinstance(not_val, list): values_to_check.extend(not_val)
                
                for v in values_to_check:
                    if str(v) not in target_wc_options:
                        errors.append(f"Requires value '{v}' not found in '{key}'.")

    def _create_context_menu(self):
        """Creates the right-click context menu for the choices treeview."""
        self.context_menu = tk.Menu(self.tree, tearoff=0)
        self.context_menu.add_command(label="Edit...", command=self._open_full_edit_dialog_from_selection)
        self.context_menu.add_command(label="Merge Selected Items... (2)", command=self._merge_selected_items)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Add New Choice", command=self._add_item)
        self.context_menu.add_command(label="Delete Selected", command=self._delete_item)
        self.context_menu.add_command(label="Duplicate Selected", command=self._duplicate_items)

    def _show_context_menu(self, event):
        """Shows the context menu and configures its state based on the selection."""
        # First, handle the selection logic to prevent macOS from clearing it.
        iid = self.tree.identify_row(event.y)
        if iid:
            # If the right-clicked item is not already part of the selection,
            # then clear the old selection and select only the new item.
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)

        selection = self.tree.selection()
        
        self.context_menu.entryconfig("Edit...", state=tk.NORMAL if len(selection) == 1 else tk.DISABLED)
        self.context_menu.entryconfig("Merge Selected Items... (2)", state=tk.NORMAL if len(selection) == 2 else tk.DISABLED)
        self.context_menu.entryconfig("Delete Selected", state=tk.NORMAL if selection else tk.DISABLED)
        self.context_menu.entryconfig("Duplicate Selected", state=tk.NORMAL if selection else tk.DISABLED)

        self.context_menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _merge_selected_items(self):
        """Merges two selected items into a NEW item, with an option to delete the originals."""
        selection = self.tree.selection()
        if len(selection) != 2:
            return

        item1_id, item2_id = selection
        
        # Get data for both items
        choice1 = self._get_choice_from_tree_item(item1_id)
        choice2 = self._get_choice_from_tree_item(item2_id)
        # Ensure they are dicts for merging complex properties
        if isinstance(choice1, str): choice1 = {'value': choice1}
        if isinstance(choice2, str): choice2 = {'value': choice2}

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

        new_values = (
            merged_value,
            str(merged_weight) if merged_weight is not None and merged_weight != '' else '',
            ", ".join(merged_tags),
            json.dumps(merged_reqs, separators=(',', ':')) if merged_reqs else "",
            includes_display
        )

        # Get index of the last selected item to insert the new one after it
        last_index = max(self.tree.index(item1_id), self.tree.index(item2_id))

        # Insert new merged item after the selection
        new_item_id = self.tree.insert('', last_index + 1, values=new_values)
        
        
        # Construct the object to store in the map, cleaning up empty keys
        new_choice_obj = {'value': merged_value}
        # Clean up None/empty values, but preserve weight if it is 0
        if merged_weight is not None and merged_weight != '':
            new_choice_obj['weight'] = merged_weight
        if merged_tags: new_choice_obj['tags'] = merged_tags
        if merged_reqs: new_choice_obj['requires'] = merged_reqs
        if merged_includes: new_choice_obj['includes'] = merged_includes

        self.iid_to_choice_map[new_item_id] = new_choice_obj
        self._validate_item(new_item_id)

        # --- Ask to delete originals, handling focus ---
        manager_window = self.winfo_toplevel()
        is_in_manager = hasattr(manager_window, 'wildcard_listbox')
        
        should_delete = False
        try:
            if is_in_manager:
                manager_window.dialog_is_open = True
                manager_window.wildcard_listbox.unbind("<<ListboxSelect>>")
            should_delete = custom_dialogs.ask_yes_no(self, "Delete Originals?", "Would you like to delete the original items after merging?")
        finally:
            try:
                if is_in_manager and manager_window.winfo_exists():
                    manager_window.dialog_is_open = False
                    manager_window.wildcard_listbox.bind("<<ListboxSelect>>", manager_window._on_wildcard_file_select)
            except tk.TclError:
                pass # Window was likely destroyed.

        if should_delete:
            self.tree.delete(item1_id)
            self.tree.delete(item2_id)
            if item1_id in self.iid_to_choice_map: del self.iid_to_choice_map[item1_id]
            if item2_id in self.iid_to_choice_map: del self.iid_to_choice_map[item2_id]

    def _duplicate_items(self):
        """Duplicates the selected items in the treeview."""
        selection = self.tree.selection()
        if not selection:
            return

        for item_id in reversed(selection): # Reverse to insert correctly after each original
            original_choice = self.iid_to_choice_map.get(item_id)
            if not original_choice:
                continue

            # Deep copy the underlying data object to avoid shared references
            new_choice_obj = copy.deepcopy(original_choice)

            # Get the display values from the tree
            original_values = list(self.tree.item(item_id, 'values'))
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
            original_index = self.tree.index(item_id)
            new_item_id = self.tree.insert('', original_index + 1, values=tuple(new_values))
            
            # Update the map with the new item's ID and its new data object
            self.iid_to_choice_map[new_item_id] = new_choice_obj
            self._validate_item(new_item_id)
