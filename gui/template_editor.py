"""The template editor text widget and its frame."""

import tkinter as tk
from tkinter import ttk
import re
from typing import Callable, List

from .common import TemplateEditorContextMenu

class TemplateEditor(ttk.Frame):
    """The template editor text widget and its frame."""
    def __init__(self, parent, live_update_callback: Callable, double_click_callback: Callable, generate_wildcard_callback: Callable, brainstorm_callback: Callable, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.frame = ttk.LabelFrame(self, text="Template Content", padding=5)
        self.text_widget = tk.Text(self.frame, wrap=tk.WORD, font=("Courier", 11), undo=True)
        self.text_widget.tag_configure("any_wildcard")
        self.text_widget.tag_configure("missing_wildcard")
        TemplateEditorContextMenu(self.text_widget, generate_wildcard_callback, brainstorm_callback)
        self.text_widget.pack(fill=tk.BOTH, expand=True)
        self.text_widget.bind("<KeyRelease>", live_update_callback)
        self.text_widget.bind("<Double-Button-1>", double_click_callback)
        
        self.frame.pack(fill=tk.BOTH, expand=True)

    def get_content(self) -> str:
        return self.text_widget.get("1.0", "end-1c")

    def set_content(self, content: str):
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.delete("1.0", tk.END)
        self.text_widget.insert("1.0", content)

    def clear(self):
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.delete("1.0", tk.END)

    def set_label(self, text: str):
        self.frame.config(text=text)

    def highlight_wildcards(self, known_wildcards: List[str]):
        """Highlights missing wildcards and tags all wildcards
 in the template editor."""
        self.text_widget.tag_remove("missing_wildcard", "1.0", tk.END)
        self.text_widget.tag_remove("any_wildcard", "1.0", tk.END)

        content = self.get_content()
        if not content:
            return

        for match in re.finditer(r'__([a-zA-Z0-9_.-]+)__', content):
            wildcard_name = match.group(1)
            start_index = f"1.0+{match.start()}c"
            end_index = f"1.0+{match.end()}c"
            self.text_widget.tag_add("any_wildcard", start_index, end_index)
            if wildcard_name not in known_wildcards:
                self.text_widget.tag_add("missing_wildcard", start_index, end_index)

    def insert_wildcard_tag(self, wildcard_name: str):
        """Inserts a wildcard tag, overwriting a selection or the tag under the cursor."""
        tag_to_insert = f"__{wildcard_name}__"
        try:
            if self.text_widget.tag_ranges("sel"):
                self.text_widget.delete("sel.first", "sel.last")
            self.text_widget.insert(tk.INSERT, tag_to_insert)
        except tk.TclError:
            # Fallback for edge cases, e.g., if selection is gone
            self.text_widget.insert(tk.INSERT, tag_to_insert)

        self.text_widget.focus_set()