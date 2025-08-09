"""The wildcard inserter listbox and its frame."""

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional

class WildcardInserter(ttk.Frame):
    """The wildcard inserter listbox and its frame."""
    def __init__(self, parent, insert_callback: Callable, manage_callback: Callable, **kwargs):
        super().__init__(parent, **kwargs)
        
        frame = ttk.LabelFrame(self, text="Insert Wildcard", padding=5)

        list_scroll_frame = ttk.Frame(frame)
        list_scroll_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_scroll_frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(list_scroll_frame, font=("Helvetica", 10), yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-Button-1>", insert_callback)

        ttk.Button(frame, text="Manage Wildcards...", command=manage_callback).pack(pady=(5, 0), fill=tk.X)
        frame.pack(fill=tk.BOTH, expand=True)

    def populate(self, wildcard_files: List[str]):
        self.listbox.delete(0, tk.END)
        for f in wildcard_files:
            self.listbox.insert(tk.END, f[:-4]) # Insert without .txt

    def get_selected_wildcard_name(self) -> Optional[str]:
        selected_indices = self.listbox.curselection()
        if not selected_indices:
            return None
        return self.listbox.get(selected_indices[0])