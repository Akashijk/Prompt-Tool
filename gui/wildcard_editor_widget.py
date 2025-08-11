"""
A structured editor for the JSON-based wildcard files, providing a
user-friendly alternative to raw text editing.
"""

import tkinter as tk
import json
import sys
from tkinter import ttk
from typing import Dict, List, Any, Optional, Tuple, Callable, TYPE_CHECKING

from .custom_dialogs import _CustomDialog

if TYPE_CHECKING:
    from .wildcard_manager import WildcardManagerWindow
    from core.prompt_processor import PromptProcessor

class _AddRequirementDialog(_CustomDialog):
    """A dialog to help build a 'requires' clause."""
    def __init__(self, parent, processor: 'PromptProcessor'):
        super().__init__(parent, "Add Requirement")
        self.processor = processor

        # --- Main Frames ---
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Type Selection ---
        type_frame = ttk.LabelFrame(main_frame, text="Requirement Type", padding=10)
        type_frame.pack(fill=tk.X, pady=(0, 10))
        self.req_type_var = tk.StringVar(value="value")
        ttk.Radiobutton(type_frame, text="Wildcard Value", variable=self.req_type_var, value="value", command=self._update_ui).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(type_frame, text="Tag Presence", variable=self.req_type_var, value="tag", command=self._update_ui).pack(side=tk.LEFT, padx=5)

        # --- Dynamic Frames ---
        self.value_frame = ttk.LabelFrame(main_frame, text="Value Requirement", padding=10)
        self.tag_frame = ttk.LabelFrame(main_frame, text="Tag Requirement", padding=10)

        # --- Widgets for Value Frame ---
        self.wildcard_var = tk.StringVar()
        ttk.Label(self.value_frame, text="Wildcard Name:").grid(row=0, column=0, sticky='w', pady=2)
        self.wildcard_combo = ttk.Combobox(self.value_frame, textvariable=self.wildcard_var, state="readonly", width=30)
        self.wildcard_combo['values'] = sorted(self.processor.get_wildcard_names())
        self.wildcard_combo.grid(row=0, column=1, sticky='ew', pady=2)
        self.wildcard_combo.bind("<<ComboboxSelected>>", self._on_wildcard_select)

        ttk.Label(self.value_frame, text="Required Value(s):").grid(row=1, column=0, sticky='nw', pady=2)
        self.value_listbox = tk.Listbox(self.value_frame, selectmode=tk.EXTENDED, height=6)
        self.value_listbox.grid(row=1, column=1, sticky='nsew')
        self.value_frame.rowconfigure(1, weight=1)
        self.value_frame.columnconfigure(1, weight=1)

        # --- Widgets for Tag Frame ---
        self.tag_match_type_var = tk.StringVar(value="any")
        ttk.Label(self.tag_frame, text="Match Type:").pack(anchor='w')
        ttk.Radiobutton(self.tag_frame, text="Any of these tags", variable=self.tag_match_type_var, value="any").pack(anchor='w', padx=10)
        ttk.Radiobutton(self.tag_frame, text="All of these tags", variable=self.tag_match_type_var, value="all").pack(anchor='w', padx=10)
        ttk.Label(self.tag_frame, text="Required Tags (comma-separated):").pack(anchor='w', pady=(10, 2))
        self.tags_entry = ttk.Entry(self.tag_frame)
        self.tags_entry.pack(fill=tk.X, expand=True)

        # --- OK/Cancel Buttons ---
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10,0))
        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5,0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self._update_ui() # Set initial visibility
        self._center_window()
        self.wait_window(self)

    def _update_ui(self):
        """Shows the relevant frame based on the selected requirement type."""
        req_type = self.req_type_var.get()
        if req_type == "value":
            self.tag_frame.pack_forget()
            self.value_frame.pack(fill=tk.BOTH, expand=True)
        else: # tag
            self.value_frame.pack_forget()
            self.tag_frame.pack(fill=tk.BOTH, expand=True)

    def _on_wildcard_select(self, event=None):
        wildcard_name = self.wildcard_var.get()
        if wildcard_name:
            self.value_listbox.delete(0, tk.END)
            options = self.processor.get_wildcard_options(wildcard_name)
            for option in options:
                self.value_listbox.insert(tk.END, option)
    
    def _on_ok(self, event=None):
        req_type = self.req_type_var.get()
        if req_type == "value":
            wildcard_name = self.wildcard_var.get()
            selected_indices = self.value_listbox.curselection()
            selected_values = [self.value_listbox.get(i) for i in selected_indices]
            if not wildcard_name or not selected_values:
                self.destroy()
                return
            
            # If only one value is selected, it's a simple key:value match.
            # If multiple, it's a key:[val1, val2] "any of" match.
            if len(selected_values) == 1:
                self.result = {wildcard_name: selected_values[0]}
            else:
                self.result = {wildcard_name: selected_values}
        else: # tag
            match_type = self.tag_match_type_var.get()
            tags = [t.strip() for t in self.tags_entry.get().split(',') if t.strip()]
            if not tags:
                self.destroy()
                return
            self.result = {"tags": {match_type: tags}}

        self.destroy()

class _EditChoiceDialog(_CustomDialog):
    """A dialog for editing a single choice from a wildcard file."""
    def __init__(self, parent, title: str, initial_values: Tuple[str, str, str, str, str], processor: 'PromptProcessor'):
        super().__init__(parent, title)

        self.value_var = tk.StringVar(value=initial_values[0])
        self.weight_var = tk.StringVar(value=initial_values[1])
        self.tags_var = tk.StringVar(value=initial_values[2])
        self.requires_var = tk.StringVar(value=initial_values[3])
        self.includes_var = tk.StringVar(value=initial_values[4])
        self.processor = processor

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Value:").grid(row=0, column=0, sticky='w', pady=2)
        ttk.Entry(main_frame, textvariable=self.value_var, width=50).grid(row=0, column=1, sticky='ew', pady=2)
        
        ttk.Label(main_frame, text="Weight:").grid(row=1, column=0, sticky='w', pady=2)
        ttk.Entry(main_frame, textvariable=self.weight_var).grid(row=1, column=1, sticky='ew', pady=2)

        ttk.Label(main_frame, text="Tags (comma-separated):").grid(row=2, column=0, sticky='w', pady=2)
        ttk.Entry(main_frame, textvariable=self.tags_var).grid(row=2, column=1, sticky='ew', pady=2)

        ttk.Label(main_frame, text="Requires (key:val, ...):").grid(row=3, column=0, sticky='w', pady=2)
        
        requires_frame = ttk.Frame(main_frame)
        requires_frame.grid(row=3, column=1, sticky='ew', pady=2)
        ttk.Entry(requires_frame, textvariable=self.requires_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(requires_frame, text="Add...", command=self._add_requirement).pack(side=tk.LEFT, padx=(5,0))

        ttk.Label(main_frame, text="Includes (wildcards, comma-sep):").grid(row=4, column=0, sticky='w', pady=2)
        ttk.Entry(main_frame, textvariable=self.includes_var).grid(row=4, column=1, sticky='ew', pady=2)
        
        main_frame.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=2, pady=(10,0), sticky='e')
        
        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5,0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self._center_window()
        self.wait_window(self)

    def _on_ok(self, event=None):
        self.result = (
            self.value_var.get(),
            self.weight_var.get(),
            self.tags_var.get(),
            self.requires_var.get(),
            self.includes_var.get()
        )
        self.destroy()
    
    def _add_requirement(self):
        dialog = _AddRequirementDialog(self, self.processor)
        if dialog.result:
            try:
                current_req_str = self.requires_var.get()
                # If empty, start a new dict, otherwise parse existing
                current_reqs = json.loads(current_req_str) if current_req_str else {}
                
                # Merge the new rule into the existing ones
                current_reqs.update(dialog.result)
                
                # Convert back to a compact JSON string for the entry field
                new_req_str = json.dumps(current_reqs, separators=(',', ':'))
                self.requires_var.set(new_req_str)
            except json.JSONDecodeError:
                # Handle case where existing text is not valid JSON by overwriting it
                new_req_str = json.dumps(dialog.result, separators=(',', ':'))
                self.requires_var.set(new_req_str)

class WildcardSelectorDialog(_CustomDialog):
    """A dialog for selecting wildcards to include."""
    def __init__(self, parent, processor: 'PromptProcessor'):
        super().__init__(parent, "Select Wildcards to Include")
        
        # Create main frame
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add search box
        search_frame = ttk.Frame(main_frame)
        search_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._filter_wildcards)
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side=tk.LEFT, 
                                                                  fill=tk.X, 
                                                                  expand=True, 
                                                                  padx=(5, 0))
        
        # Create listbox with scrollbar
        self.listbox = tk.Listbox(main_frame, selectmode=tk.MULTIPLE, height=15)
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, 
                                command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        
        # Populate with wildcards
        self.all_wildcards = sorted(processor.get_wildcard_names())
        for wildcard in self.all_wildcards:
            self.listbox.insert(tk.END, wildcard)
        
        # Add buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(button_frame, text="OK", 
                  command=self._on_ok, 
                  style="Accent.TButton").pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Cancel",
                  command=self._on_cancel).pack(side=tk.RIGHT)
        
        # Center the dialog
        self.geometry("300x400")
        self._center_window()

        # Make dialog modal
        self.wait_window(self)
    
    def _filter_wildcards(self, *args):
        """Filter the wildcard list based on search text."""
        search_text = self.search_var.get().lower()
        self.listbox.delete(0, tk.END)
        
        for wildcard in self.all_wildcards:
            if search_text in wildcard.lower():
                self.listbox.insert(tk.END, wildcard)
    
    def _on_ok(self):
        """Handle OK button click."""
        selection = self.listbox.curselection()
        if selection:
            self.result = [self.listbox.get(i) for i in selection]
        self.destroy()

class WildcardEditor(ttk.Frame):
    """A structured editor for wildcard files."""
    def __init__(self, parent, processor: 'PromptProcessor', suggestion_callback: Optional[Callable] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.processor = processor
        self.suggestion_callback = suggestion_callback
        self.iid_to_choice_map: Dict[str, Any] = {}
        # The parent is a frame inside the WildcardManagerWindow.
        # self.winfo_toplevel() will give us the WildcardManagerWindow instance, which has parent_app.
        self.parent_app = self.winfo_toplevel().parent_app
        
        # Define colors for included items
        self.included_tag = "included"
        self.duplicate_tag = "duplicate"
        self._create_widgets()
        self.update_theme() # Set initial theme-based colors

    def _create_widgets(self):
        # --- Description ---
        desc_frame = ttk.Frame(self)
        desc_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(desc_frame, text="Description:").pack(side=tk.LEFT, padx=(0, 5))
        self.description_entry = ttk.Entry(desc_frame)
        self.description_entry.pack(fill=tk.X, expand=True)

        # --- Main Paned Window (Choices and Includes) ---
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        # --- Choices Pane ---
        choices_frame = ttk.LabelFrame(main_pane, text="Choices", padding=5)
        main_pane.add(choices_frame, weight=3)

        choices_toolbar = ttk.Frame(choices_frame)
        choices_toolbar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(choices_toolbar, text="Add", command=self._add_item).pack(side=tk.LEFT)
        ttk.Button(choices_toolbar, text="Delete", command=self._delete_item).pack(side=tk.LEFT, padx=5)
        self.suggest_button = ttk.Button(choices_toolbar, text="Suggest Choices (AI)", command=self._on_suggest_choices, state=tk.DISABLED)
        self.suggest_button.pack(side=tk.RIGHT)

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
        self.tree.bind("<Double-1>", self._on_edit_item)

        # Add context menu
        self._create_context_menu()
        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        self.tree.bind(right_click_event, self._show_context_menu)

        # --- Includes Listbox ---
        includes_frame = ttk.LabelFrame(main_pane, text="Global Includes", padding=5)
        main_pane.add(includes_frame, weight=1)

        includes_toolbar = ttk.Frame(includes_frame)
        includes_toolbar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(includes_toolbar, text="Add...", command=self._show_include_selector).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(includes_toolbar, text="Remove", command=self._remove_include).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        listbox_container = ttk.Frame(includes_frame)
        listbox_container.pack(fill=tk.BOTH, expand=True)
        
        self.includes_listbox = tk.Listbox(listbox_container)
        includes_scrollbar = ttk.Scrollbar(listbox_container, orient="vertical", command=self.includes_listbox.yview)
        self.includes_listbox.configure(yscrollcommand=includes_scrollbar.set)

        self.includes_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        includes_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

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
        included_choices = self._get_included_choices(data.get('includes', []))
            
        # Add choices and highlight those from includes
        for choice in data.get('choices', []):
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
                includes = ", ".join(choice.get('includes', []))
                
                item_id = self.tree.insert('', tk.END, 
                    values=(value, weight, tags, requires, includes))
                self.iid_to_choice_map[item_id] = choice
                
                if value in included_choices:
                    self.tree.item(item_id, tags=(self.included_tag,))

        # Update includes listbox
        self.includes_listbox.delete(0, tk.END)
        for include in data.get('includes', []):
            self.includes_listbox.insert(tk.END, include)

    def get_data(self) -> Dict[str, Any]:
        """Constructs the JSON data object from the UI widgets."""
        choices = [self._get_choice_from_tree_item(iid) for iid in self.tree.get_children()]
        includes = [self.includes_listbox.get(i) for i in range(self.includes_listbox.size())]
        return {"description": self.description_entry.get(), "choices": choices, "includes": includes}

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
            choice_obj['includes'] = [i.strip() for i in includes_str.split(',') if i.strip()]
        
        return choice_obj

    def _add_item(self):
        new_choice_str = 'new value'
        new_choice_obj = {'value': new_choice_str, 'weight': 1}
        item_id = self.tree.insert('', tk.END, values=(new_choice_str, '1', '', '', ''))
        self.iid_to_choice_map[item_id] = new_choice_obj

    def _delete_item(self):
        for selected_item in self.tree.selection():
            if selected_item in self.iid_to_choice_map:
                del self.iid_to_choice_map[selected_item]
            self.tree.delete(selected_item)

    def _on_edit_item(self, event):
        selection = self.tree.selection()
        if len(selection) != 1: return
        
        item_id = selection[0]
        dialog = _EditChoiceDialog(self, "Edit Choice", self.tree.item(item_id, 'values'), self.processor)
        if dialog.result:
            self.tree.item(item_id, values=dialog.result)
            updated_choice = self._get_choice_from_tree_item(item_id)
            self.iid_to_choice_map[item_id] = updated_choice

    def _on_suggest_choices(self):
        """Callback to ask the manager window to trigger AI suggestions."""
        if self.suggestion_callback:
            current_data = self.get_data()
            self.suggestion_callback(current_data)

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

    def _show_include_selector(self):
        """Shows a dialog to select wildcards to include."""
        dialog = WildcardSelectorDialog(self, self.processor)
        if dialog.result:
            current_includes = set(self.includes_listbox.get(0, tk.END))
            for wildcard in dialog.result:
                if wildcard not in current_includes:
                    self.includes_listbox.insert(tk.END, wildcard)
            self._refresh_ui_from_includes_change()

    def _remove_include(self):
        """Removes the selected include from the list."""
        selection = self.includes_listbox.curselection()
        if selection:
            self.includes_listbox.delete(selection)
            self._refresh_ui_from_includes_change()

    def _refresh_ui_from_includes_change(self):
        """Refreshes the editor data to update highlighting after an include change."""
        self.set_data(self.get_data())

    def clear_highlights(self):
        """Removes all custom highlighting tags from the tree."""
        for item_id in self.tree.get_children():
            # Get current tags and remove the duplicate tag if present
            current_tags = list(self.tree.item(item_id, 'tags'))
            if self.duplicate_tag in current_tags:
                current_tags.remove(self.duplicate_tag)
                self.tree.item(item_id, tags=tuple(current_tags))

    def highlight_duplicates(self, iids_to_highlight: List[str]):
        """Applies the duplicate highlight tag to a list of item IDs."""
        for item_id in iids_to_highlight:
            current_tags = list(self.tree.item(item_id, 'tags'))
            if self.duplicate_tag not in current_tags:
                current_tags.append(self.duplicate_tag)
                self.tree.item(item_id, tags=tuple(current_tags))

    def update_theme(self):
        """Updates the tag colors in the treeview to match the current theme."""
        is_dark = self.parent_app.theme_manager.current_theme == "dark"

        included_bg = "#2c3e50" if is_dark else "#e6f3ff" # Dark muted blue / Light blue
        duplicate_bg = "#5e3333" if is_dark else "#ffcccc" # Dark muted red / Light red

        self.tree.tag_configure(
            self.included_tag, 
            background=included_bg
        )
        self.tree.tag_configure(
            self.duplicate_tag,
            background=duplicate_bg
        )

    def _create_context_menu(self):
        """Creates the right-click context menu for the choices treeview."""
        self.context_menu = tk.Menu(self.tree, tearoff=0)
        self.context_menu.add_command(label="Edit...", command=self._on_edit_item)
        self.context_menu.add_command(label="Merge into New Item (2)", command=self._merge_selected_items)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Add New Choice", command=self._add_item)
        self.context_menu.add_command(label="Delete Selected", command=self._delete_item)

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
        self.context_menu.entryconfig("Merge into New Item (2)", state=tk.NORMAL if len(selection) == 2 else tk.DISABLED)
        self.context_menu.entryconfig("Delete Selected", state=tk.NORMAL if selection else tk.DISABLED)

        self.context_menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _merge_selected_items(self):
        """Merges two selected items into a NEW item, leaving the originals."""
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

        # Combine tags and includes into unique, sorted lists
        merged_tags = sorted(list(set(choice1.get('tags', [])) | set(choice2.get('tags', []))))
        merged_includes = sorted(list(set(choice1.get('includes', [])) | set(choice2.get('includes', []))))

        # Intelligently merge 'requires' dictionaries.
        # This will combine lists for the same key instead of overwriting.
        merged_reqs = choice1.get('requires', {}).copy()
        reqs2 = choice2.get('requires', {})
        for key, value2 in reqs2.items():
            if key in merged_reqs and isinstance(merged_reqs.get(key), list) and isinstance(value2, list):
                # Both values are lists, so combine them into a unique set
                merged_reqs[key] = sorted(list(set(merged_reqs[key]) | set(value2)))
            else:
                # Otherwise, the second value overwrites the first (standard dict update behavior)
                merged_reqs[key] = value2

        # --- Create new choice object and values tuple for the treeview ---
        new_values = (
            merged_value,
            str(merged_weight) if merged_weight else '',
            ", ".join(merged_tags),
            json.dumps(merged_reqs, separators=(',', ':')) if merged_reqs else "",
            ", ".join(merged_includes)
        )

        # Get index of the last selected item to insert the new one after it
        last_index = max(self.tree.index(item1_id), self.tree.index(item2_id))

        # Insert new merged item after the selection
        new_item_id = self.tree.insert('', last_index + 1, values=new_values)
        
        # Construct the object to store in the map, cleaning up empty keys
        new_choice_obj = {
            'value': merged_value,
            'weight': merged_weight,
            'tags': merged_tags,
            'requires': merged_reqs,
            'includes': merged_includes
        }
        if not new_choice_obj.get('weight'): del new_choice_obj['weight']
        if not new_choice_obj.get('tags'): del new_choice_obj['tags']
        if not new_choice_obj.get('requires'): del new_choice_obj['requires']
        if not new_choice_obj.get('includes'): del new_choice_obj['includes']

        self.iid_to_choice_map[new_item_id] = new_choice_obj