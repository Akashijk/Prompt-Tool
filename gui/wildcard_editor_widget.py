"""
A structured editor for the JSON-based wildcard files, providing a
user-friendly alternative to raw text editing.
"""

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Any, Optional, Tuple

class _EditChoiceDialog(tk.Toplevel):
    """A dialog for editing a single choice from a wildcard file."""
    def __init__(self, parent, title: str, initial_values: Tuple[str, str, str, str]):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.result: Optional[Tuple[str, str, str, str]] = None

        self.value_var = tk.StringVar(value=initial_values[0])
        self.weight_var = tk.StringVar(value=initial_values[1])
        self.tags_var = tk.StringVar(value=initial_values[2])
        self.requires_var = tk.StringVar(value=initial_values[3])

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Value:").grid(row=0, column=0, sticky='w', pady=2)
        ttk.Entry(main_frame, textvariable=self.value_var, width=50).grid(row=0, column=1, sticky='ew', pady=2)
        
        ttk.Label(main_frame, text="Weight:").grid(row=1, column=0, sticky='w', pady=2)
        ttk.Entry(main_frame, textvariable=self.weight_var).grid(row=1, column=1, sticky='ew', pady=2)

        ttk.Label(main_frame, text="Tags (comma-separated):").grid(row=2, column=0, sticky='w', pady=2)
        ttk.Entry(main_frame, textvariable=self.tags_var).grid(row=2, column=1, sticky='ew', pady=2)

        ttk.Label(main_frame, text="Requires (key:val, ...):").grid(row=3, column=0, sticky='w', pady=2)
        ttk.Entry(main_frame, textvariable=self.requires_var).grid(row=3, column=1, sticky='ew', pady=2)
        
        main_frame.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=(10,0), sticky='e')
        
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
            self.requires_var.get()
        )
        self.destroy()

class WildcardEditor(ttk.Frame):
    """A structured editor for wildcard files."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
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

        columns = ('value', 'weight', 'tags', 'requires')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings')
        self.tree.heading('value', text='Value')
        self.tree.heading('weight', text='Weight')
        self.tree.heading('tags', text='Tags')
        self.tree.heading('requires', text='Requires')
        
        self.tree.column('value', width=200, stretch=True)
        self.tree.column('weight', width=60, stretch=False, anchor='center')
        self.tree.column('tags', width=120, stretch=True)
        self.tree.column('requires', width=150, stretch=True)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self.tree.pack(side='left', fill='both', expand=True)
        
        self.tree.bind("<Double-1>", self._on_edit_item)

        # Action buttons for the tree
        tree_button_frame = ttk.Frame(self)
        tree_button_frame.pack(fill=tk.X, pady=(5,0), padx=5)
        ttk.Button(tree_button_frame, text="Add Choice", command=self._add_item).pack(side=tk.LEFT)
        ttk.Button(tree_button_frame, text="Delete Selected", command=self._delete_item).pack(side=tk.LEFT, padx=5)

    def set_data(self, data: Dict[str, Any]):
        self.description_entry.delete(0, tk.END)
        self.description_entry.insert(0, data.get('description', ''))
        
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        for choice in data.get('choices', []):
            if isinstance(choice, str):
                self.tree.insert('', tk.END, values=(choice, '', '', ''))
            elif isinstance(choice, dict):
                value = choice.get('value', '')
                weight = choice.get('weight', '')
                tags = ", ".join(choice.get('tags', []))
                requires_dict = choice.get('requires', {})
                requires = ", ".join([f"{k}:{v}" for k,v in requires_dict.items()])
                self.tree.insert('', tk.END, values=(value, weight, tags, requires))

    def get_data(self) -> Dict[str, Any]:
        choices = []
        for iid in self.tree.get_children():
            item_data = self.tree.item(iid, 'values')
            value, weight, tags, requires = item_data

            if not weight and not tags and not requires:
                choices.append(value)
            else:
                choice_obj = {'value': value}
                if weight:
                    try: choice_obj['weight'] = int(weight)
                    except (ValueError, TypeError): pass
                if tags:
                    choice_obj['tags'] = [t.strip() for t in tags.split(',') if t.strip()]
                if requires:
                    try:
                        req_dict = {}
                        for pair in requires.split(','):
                            if ':' in pair:
                                k, v = pair.split(':', 1)
                                req_dict[k.strip()] = v.strip()
                        if req_dict: choice_obj['requires'] = req_dict
                    except Exception: pass
                choices.append(choice_obj)
        
        return {"description": self.description_entry.get(), "choices": choices}

    def _add_item(self):
        self.tree.insert('', tk.END, values=('new value', '1', '', ''))

    def _delete_item(self):
        for selected_item in self.tree.selection():
            self.tree.delete(selected_item)

    def _on_edit_item(self, event):
        selection = self.tree.selection()
        if not selection: return
        
        item_id = selection[0]
        dialog = _EditChoiceDialog(self, "Edit Choice", self.tree.item(item_id, 'values'))
        if dialog.result:
            self.tree.item(item_id, values=dialog.result)