"""
A structured editor for the JSON-based wildcard files, providing a
user-friendly alternative to raw text editing.
"""

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Any, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .wildcard_manager import WildcardManagerWindow
    from core.prompt_processor import PromptProcessor

class _AddRequirementDialog(tk.Toplevel):
    """A dialog to help build a 'requires' clause."""
    def __init__(self, parent, processor: 'PromptProcessor'):
        super().__init__(parent)
        self.title("Add Requirement")
        self.transient(parent)
        self.grab_set()
        self.processor = processor
        self.result: Optional[Tuple[str, str]] = None

        self.wildcard_var = tk.StringVar()
        self.value_var = tk.StringVar()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Wildcard Name:").grid(row=0, column=0, sticky='w', pady=2)
        self.wildcard_combo = ttk.Combobox(main_frame, textvariable=self.wildcard_var, state="readonly", width=30)
        self.wildcard_combo['values'] = sorted(self.processor.get_wildcard_names())
        self.wildcard_combo.grid(row=0, column=1, sticky='ew', pady=2)
        self.wildcard_combo.bind("<<ComboboxSelected>>", self._on_wildcard_select)

        ttk.Label(main_frame, text="Required Value:").grid(row=1, column=0, sticky='w', pady=2)
        self.value_combo = ttk.Combobox(main_frame, textvariable=self.value_var, state="readonly", width=30)
        self.value_combo.grid(row=1, column=1, sticky='ew', pady=2)
        
        main_frame.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, columnspan=2, pady=(10,0), sticky='e')
        
        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5,0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.destroy)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self.wait_window(self)

    def _on_wildcard_select(self, event=None):
        wildcard_name = self.wildcard_var.get()
        if wildcard_name:
            options = self.processor.get_wildcard_options(wildcard_name)
            self.value_combo['values'] = options
            self.value_var.set(options[0] if options else "")
    
    def _on_ok(self, event=None):
        wildcard = self.wildcard_var.get()
        value = self.value_var.get()
        if wildcard and value:
            self.result = (wildcard, value)
        self.destroy()

class _EditChoiceDialog(tk.Toplevel):
    """A dialog for editing a single choice from a wildcard file."""
    def __init__(self, parent, title: str, initial_values: Tuple[str, str, str, str, str], processor: 'PromptProcessor'):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.result: Optional[Tuple[str, str, str, str, str]] = None

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
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.destroy)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
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
            new_req_str = f"{dialog.result[0]}:{dialog.result[1]}"
            current_reqs = self.requires_var.get()
            if current_reqs:
                self.requires_var.set(f"{current_reqs}, {new_req_str}")
            else:
                self.requires_var.set(new_req_str)

class WildcardEditor(ttk.Frame):
    """A structured editor for wildcard files."""
    def __init__(self, parent, manager_window: 'WildcardManagerWindow', processor: 'PromptProcessor', **kwargs):
        super().__init__(parent, **kwargs)
        self.manager_window = manager_window
        self.processor = processor
        self.drag_data = {"item": None}
        self._create_widgets()

    def _create_widgets(self):
        # Description
        desc_frame = ttk.Frame(self)
        desc_frame.pack(fill=tk.X, pady=(0, 10), padx=5)
        ttk.Label(desc_frame, text="Description:").pack(side=tk.LEFT)
        self.description_entry = ttk.Entry(desc_frame)
        self.description_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Choices Treeview
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ('value', 'weight', 'tags', 'requires', 'includes')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings')
        self.tree.heading('value', text='Value')
        self.tree.heading('weight', text='Weight')
        self.tree.heading('tags', text='Tags')
        self.tree.heading('requires', text='Requires')
        self.tree.heading('includes', text='Includes')
        
        self.tree.column('value', width=200, stretch=True)
        self.tree.column('weight', width=60, stretch=False, anchor='center')
        self.tree.column('tags', width=120, stretch=True)
        self.tree.column('requires', width=150, stretch=True)
        self.tree.column('includes', width=150, stretch=True)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self.tree.pack(side='left', fill='both', expand=True)
        
        self.tree.bind("<Double-1>", self._on_edit_item)
        self.tree.bind("<ButtonPress-1>", self._on_drag_start)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release)

        # Action buttons for the tree
        tree_button_frame = ttk.Frame(self)
        tree_button_frame.pack(fill=tk.X, pady=(5,0), padx=5)
        ttk.Button(tree_button_frame, text="Add Choice", command=self._add_item).pack(side=tk.LEFT)
        ttk.Button(tree_button_frame, text="Delete Selected", command=self._delete_item).pack(side=tk.LEFT, padx=5)
        self.suggest_button = ttk.Button(tree_button_frame, text="Suggest Choices (AI)", command=self._on_suggest_choices, state=tk.DISABLED)
        self.suggest_button.pack(side=tk.LEFT, padx=5)

    def set_data(self, data: Dict[str, Any]):
        self.description_entry.delete(0, tk.END)
        self.description_entry.insert(0, data.get('description', ''))
        
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        for choice in data.get('choices', []):
            if isinstance(choice, str):
                self.tree.insert('', tk.END, values=(choice, '', '', '', ''))
            elif isinstance(choice, dict):
                value = choice.get('value', '')
                weight = choice.get('weight', '')
                tags = ", ".join(choice.get('tags', []))
                requires_dict = choice.get('requires', {})
                requires = ", ".join([f"{k}:{v}" for k,v in requires_dict.items()])
                includes = ", ".join(choice.get('includes', []))
                self.tree.insert('', tk.END, values=(value, weight, tags, requires, includes))

    def get_data(self) -> Dict[str, Any]:
        """Constructs the JSON data object from the UI widgets."""
        choices = [self._get_choice_from_tree_item(iid) for iid in self.tree.get_children()]
        return {"description": self.description_entry.get(), "choices": choices}

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
            req_dict = self._parse_requires_string(requires_str)
            if req_dict:
                choice_obj['requires'] = req_dict
        
        # Parse includes
        if includes_str:
            choice_obj['includes'] = [i.strip() for i in includes_str.split(',') if i.strip()]
        
        return choice_obj

    def _parse_requires_string(self, requires_str: str) -> Dict[str, str]:
        """Parses a 'key:val,key2:val2' string into a dictionary."""
        req_dict = {}
        try:
            for pair in requires_str.split(','):
                if ':' in pair:
                    key, val = pair.split(':', 1)
                    req_dict[key.strip()] = val.strip()
        except Exception:
            # Ignore malformed requires string
            pass
        return req_dict

    def _add_item(self):
        self.tree.insert('', tk.END, values=('new value', '1', '', '', ''))

    def _delete_item(self):
        for selected_item in self.tree.selection():
            self.tree.delete(selected_item)

    def _on_edit_item(self, event):
        selection = self.tree.selection()
        if not selection: return
        
        item_id = selection[0]
        dialog = _EditChoiceDialog(self, "Edit Choice", self.tree.item(item_id, 'values'), self.processor)
        if dialog.result:
            self.tree.item(item_id, values=dialog.result)

    def _on_drag_start(self, event):
        """Records the item being dragged."""
        item = self.tree.identify_row(event.y)
        if item:
            self.drag_data["item"] = item

    def _on_drag_motion(self, event):
        """Moves the dragged item as the mouse moves."""
        if not self.drag_data["item"]:
            return
        # Move item in the treeview to the position under the cursor
        self.tree.move(self.drag_data["item"], "", self.tree.index(self.tree.identify_row(event.y)))

    def _on_drag_release(self, event):
        """Finalizes the drag operation."""
        self.drag_data["item"] = None

    def _on_suggest_choices(self):
        """Callback to ask the manager window to trigger AI suggestions."""
        current_data = self.get_data()
        self.manager_window.suggest_choices_with_ai(current_data)

    def add_suggested_choices(self, new_choices: List[Any]):
        """Adds choices suggested by the AI to the treeview."""
        if not new_choices:
            return
        
        # Use set of existing values to avoid adding duplicates
        existing_values = {self.tree.item(iid, 'values')[0] for iid in self.tree.get_children()}

        for choice in new_choices:
            if isinstance(choice, str):
                if choice not in existing_values:
                    self.tree.insert('', tk.END, values=(choice, '', '', '', ''))
            elif isinstance(choice, dict) and 'value' in choice:
                if choice['value'] not in existing_values:
                    value = choice.get('value', '')
                    weight = choice.get('weight', '')
                    tags = ", ".join(choice.get('tags', []))
                    requires_dict = choice.get('requires', {})
                    requires = ", ".join([f"{k}:{v}" for k,v in requires_dict.items()])
                    includes = ", ".join(choice.get('includes', []))
                    self.tree.insert('', tk.END, values=(value, weight, tags, requires, includes))