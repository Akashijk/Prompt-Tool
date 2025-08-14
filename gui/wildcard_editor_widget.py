"""
A structured editor for the JSON-based wildcard files, providing a
user-friendly alternative to raw text editing.
"""

import tkinter as tk
import re
import copy
import json
import sys
from tkinter import ttk
from typing import Dict, List, Any, Optional, Tuple, Callable, TYPE_CHECKING
from .common import Tooltip
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
        self.tag_frame.columnconfigure(0, weight=1) # Let columns share space
        self.tag_frame.columnconfigure(1, weight=1)

        self.tag_match_type_var = tk.StringVar(value="any")
        ttk.Label(self.tag_frame, text="Match Type:").grid(row=0, column=0, columnspan=2, sticky='w')
        ttk.Radiobutton(self.tag_frame, text="Any of these tags", variable=self.tag_match_type_var, value="any").grid(row=1, column=0, sticky='w', padx=10)
        ttk.Radiobutton(self.tag_frame, text="All of these tags", variable=self.tag_match_type_var, value="all").grid(row=1, column=1, sticky='w', padx=10)
        
        ttk.Label(self.tag_frame, text="Required Tags (comma-separated):").grid(row=2, column=0, columnspan=2, sticky='w', pady=(10, 2))
        self.tags_entry = ttk.Entry(self.tag_frame)
        self.tags_entry.grid(row=3, column=0, columnspan=2, sticky='ew')

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
        self.parent_app = parent.parent_app

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
        requires_frame.columnconfigure(0, weight=1)
        ttk.Entry(requires_frame, textvariable=self.requires_var).grid(row=0, column=0, sticky='ew')
        ttk.Button(requires_frame, text="Add...", command=self._add_requirement).grid(row=0, column=1, padx=(5, 0))

        ttk.Label(main_frame, text="Includes (list or template string):").grid(row=4, column=0, sticky='w', pady=2)
        
        includes_frame = ttk.Frame(main_frame)
        includes_frame.grid(row=4, column=1, sticky='ew', pady=2)
        includes_frame.columnconfigure(0, weight=1)
        ttk.Entry(includes_frame, textvariable=self.includes_var).grid(row=0, column=0, sticky='ew')
        ttk.Button(includes_frame, text="Add...", command=self._add_include).grid(row=0, column=1, padx=(5, 0))
        
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
        if not dialog.result:
            return

        # Get current requirements, handling invalid JSON gracefully
        try:
            current_req_str = self.requires_var.get()
            current_reqs = json.loads(current_req_str) if current_req_str else {}
            if not isinstance(current_reqs, dict): # Ensure it's a dict
                current_reqs = {}
        except json.JSONDecodeError:
            current_reqs = {}

        # --- Intelligent Merge Logic ---
        new_key, new_value = list(dialog.result.items())[0]

        if new_key == 'tags':
            # --- Handle Tag Merging ---
            if 'tags' not in current_reqs or not isinstance(current_reqs.get('tags'), dict):
                current_reqs['tags'] = new_value
            else:
                # Merge new tags into existing tag rules
                existing_tags_rule = current_reqs['tags']
                new_tags_rule = new_value
                
                for condition, tags_to_add in new_tags_rule.items(): # e.g., "any", ["tag1"]
                    if condition not in existing_tags_rule:
                        existing_tags_rule[condition] = tags_to_add
                    else:
                        # Combine and unique the lists
                        combined = set(existing_tags_rule[condition]) | set(tags_to_add)
                        existing_tags_rule[condition] = sorted(list(combined))
        else:
            # --- Handle Value Merging ---
            if new_key not in current_reqs:
                current_reqs[new_key] = new_value
            else:
                existing_value = current_reqs[new_key]
                all_values = set()
                
                if isinstance(existing_value, list): all_values.update(existing_value)
                else: all_values.add(existing_value)
                
                if isinstance(new_value, list): all_values.update(new_value)
                else: all_values.add(new_value)
                
                merged_list = sorted(list(all_values))
                current_reqs[new_key] = merged_list[0] if len(merged_list) == 1 else merged_list

        # Convert back to a compact JSON string for the entry field
        new_req_str = json.dumps(current_reqs, separators=(',', ':')) if current_reqs else ""
        self.requires_var.set(new_req_str)

    def _add_include(self):
        """Opens a dialog to add wildcards to the includes field."""
        dialog = WildcardSelectorDialog(self, self.processor)
        if not dialog.result:
            return

        current_text = self.includes_var.get().strip()
        to_append = " ".join([f"[{w}]" for w in dialog.result])
        new_text = f"{current_text} {to_append}".strip()
        self.includes_var.set(new_text)

class WildcardSelectorDialog(_CustomDialog):
    """A dialog for selecting wildcards to include."""
    def __init__(self, parent, processor: 'PromptProcessor'):
        super().__init__(parent, "Select Wildcards to Include")
        
        # Get the main app instance for callbacks
        self.parent_app = parent.parent_app
        self.processor = processor
        
        # Create main frame
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add search box
        search_frame = ttk.Frame(main_frame)
        search_frame.pack(fill=tk.X, pady=(0, 5))
        search_frame.columnconfigure(1, weight=1)

        ttk.Label(search_frame, text="Search:").grid(row=0, column=0, sticky='w')
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._filter_wildcards)
        ttk.Entry(search_frame, textvariable=self.search_var).grid(row=0, column=1, sticky='ew', padx=(5, 0))
        
        # Create listbox with scrollbar inside a container frame
        list_container = ttk.Frame(main_frame)
        list_container.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_container, selectmode=tk.MULTIPLE, height=15)
        scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL, 
                                command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Populate with wildcards
        self.all_wildcards = sorted(processor.get_wildcard_names())
        for wildcard in self.all_wildcards:
            self.listbox.insert(tk.END, wildcard)
        
        # --- Tooltip for preview ---
        self.tooltip = Tooltip(self.listbox)
        self.tooltip_after_id = None
        self.last_hovered_index = -1
        self.listbox.bind("<Motion>", self._schedule_tooltip)
        self.listbox.bind("<Leave>", self._hide_tooltip)

        # --- Context Menu for full review ---
        self.context_menu = tk.Menu(self.listbox, tearoff=0)
        self.context_menu.add_command(label="Open in Wildcard Manager", command=self._open_in_manager)
        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        self.listbox.bind(right_click_event, self._show_context_menu)

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

    def _schedule_tooltip(self, event):
        """Schedules a tooltip to appear after a short delay."""
        if self.tooltip_after_id:
            self.after_cancel(self.tooltip_after_id)

        index = self.listbox.nearest(event.y)
        if index != self.last_hovered_index:
            self.tooltip.hide() # Hide immediately if moving to a new item
        self.last_hovered_index = index
        self.tooltip_after_id = self.after(500, lambda: self._display_tooltip(index, event))

    def _display_tooltip(self, index, event):
        """Fetches content and displays the tooltip. This is called after a delay."""
        try:
            wildcard_name = self.listbox.get(index)
            options = self.processor.get_wildcard_options(wildcard_name)

            if not options:
                self.tooltip.text = f"{wildcard_name} (empty)"
            else:
                preview_count = 10
                preview_options = options[:preview_count]
                
                tooltip_text = f"'{wildcard_name}' choices:\n" + "\n".join([f"- {opt}" for opt in preview_options])
                if len(options) > preview_count:
                    tooltip_text += f"\n...and {len(options) - preview_count} more"
                
                self.tooltip.text = tooltip_text
            
            self.tooltip.show(event)
        except tk.TclError:
            # This can happen if the mouse is over an empty part of the listbox
            self.tooltip.hide()

    def _hide_tooltip(self, event=None):
        """Hides the wildcard preview tooltip."""
        self.last_hovered_index = -1
        if self.tooltip_after_id:
            self.after_cancel(self.tooltip_after_id)
            self.tooltip_after_id = None
        self.tooltip.hide()

    def _show_context_menu(self, event):
        """Shows the context menu for the listbox."""
        index = self.listbox.nearest(event.y)
        if index != -1:
            if not self.listbox.selection_includes(index):
                self.listbox.selection_clear(0, tk.END)
                self.listbox.selection_set(index)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _open_in_manager(self):
        """Opens the selected wildcard in the Wildcard Manager."""
        selection = self.listbox.curselection()
        if not selection:
            return
        
        wildcard_name = self.listbox.get(selection[0])
        self.parent_app._open_wildcard_manager(initial_file=f"{wildcard_name}.json")

class WildcardEditor(ttk.Frame):
    """A structured editor for wildcard files."""
    def __init__(self, parent, processor: 'PromptProcessor', suggestion_callback: Optional[Callable] = None, refinement_callback: Optional[Callable] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.processor = processor
        self.suggestion_callback = suggestion_callback
        self.refinement_callback = refinement_callback
        self.iid_to_choice_map: Dict[str, Any] = {}
        # The parent is a frame inside the WildcardManagerWindow.
        # self.winfo_toplevel() will give us the WildcardManagerWindow instance, which has parent_app.
        self.validation_error_tag = "validation_error"
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

        # --- Main Vertical Paned Window for a more compact layout ---
        main_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        # --- Choices Pane (Top) ---
        choices_frame = ttk.LabelFrame(main_pane, text="Choices", padding=5)
        main_pane.add(choices_frame, weight=4)

        choices_toolbar = ttk.Frame(choices_frame)
        choices_toolbar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(choices_toolbar, text="Add", command=self._add_item).pack(side=tk.LEFT)
        ttk.Button(choices_toolbar, text="Delete", command=self._delete_item).pack(side=tk.LEFT, padx=5)

        # AI buttons on the right
        ai_button_frame = ttk.Frame(choices_toolbar)
        ai_button_frame.pack(side=tk.RIGHT)
        self.suggest_button = ttk.Button(ai_button_frame, text="Suggest Choices (AI)", command=self._on_suggest_choices, state=tk.DISABLED)
        self.suggest_button.pack(side=tk.LEFT)
        self.refine_button = ttk.Button(ai_button_frame, text="Refine Choices (AI)", command=self._on_refine_choices, state=tk.DISABLED)
        self.refine_button.pack(side=tk.LEFT, padx=(5,0))

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

        # --- Includes Pane (Bottom) ---
        includes_frame = ttk.LabelFrame(main_pane, text="Global Includes (as list or template string)", padding=5)
        main_pane.add(includes_frame, weight=1)

        includes_toolbar = ttk.Frame(includes_frame)
        includes_toolbar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(includes_toolbar, text="Insert Wildcard...", command=self._insert_include_wildcard).pack(side=tk.LEFT)

        # The new text widget for includes
        self.includes_text = tk.Text(includes_frame, height=5, wrap=tk.WORD, undo=True, exportselection=False)
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

        # Update includes text area
        self.includes_text.delete("1.0", tk.END)
        if isinstance(data.get('includes'), str):
            self.includes_text.insert("1.0", includes_data)

        # Update refine button state
        has_choices = bool(choices)
        self.refine_button.config(state=tk.NORMAL if has_choices else tk.DISABLED)

    def get_data(self) -> Dict[str, Any]:
        """Constructs the JSON data object from the UI widgets."""
        choices = [self._get_choice_from_tree_item(iid) for iid in self.tree.get_children()]
        
        includes_text = self.includes_text.get("1.0", "end-1c").strip()
        data_dict = {"description": self.description_entry.get(), "choices": choices}
        if includes_text:
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

    def _on_edit_item(self, event=None):
        selection = self.tree.selection()
        if len(selection) != 1: return
        
        item_id = selection[0]

        manager_window = self.winfo_toplevel()

        # This editor can be used in WildcardManager or ReviewAndSaveWindow.
        # The focus-loss issue only applies to the WildcardManager, which has a listbox.
        # We check for the listbox to avoid crashing in other contexts.
        is_in_manager = hasattr(manager_window, 'wildcard_listbox')

        if is_in_manager:
            manager_window.dialog_is_open = True
            manager_window.wildcard_listbox.unbind("<<ListboxSelect>>")

        try:
            dialog = _EditChoiceDialog(self, "Edit Choice", self.tree.item(item_id, 'values'), self.processor)
            if dialog.result:
                self.tree.item(item_id, values=dialog.result)
                updated_choice = self._get_choice_from_tree_item(item_id)
                self.iid_to_choice_map[item_id] = updated_choice
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

    def _insert_include_wildcard(self):
        """Opens a dialog to select wildcards and inserts them into the includes text widget."""
        manager_window = self.winfo_toplevel()
        is_in_manager = hasattr(manager_window, 'wildcard_listbox')

        if is_in_manager:
            manager_window.dialog_is_open = True
            manager_window.wildcard_listbox.unbind("<<ListboxSelect>>")
        
        try:
            dialog = WildcardSelectorDialog(self, self.processor)
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

    def _create_context_menu(self):
        """Creates the right-click context menu for the choices treeview."""
        self.context_menu = tk.Menu(self.tree, tearoff=0)
        self.context_menu.add_command(label="Edit...", command=self._on_edit_item)
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
            if key in merged_reqs and isinstance(merged_reqs.get(key), list) and isinstance(value2, list):
                # Both values are lists, so combine them into a unique set
                merged_reqs[key] = sorted(list(set(merged_reqs[key]) | set(value2)))
            else:
                # Otherwise, the second value overwrites the first (standard dict update behavior)
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
