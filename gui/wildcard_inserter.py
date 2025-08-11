"""The wildcard inserter listbox and its frame."""

import os
import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional, TYPE_CHECKING

from .common import Tooltip

if TYPE_CHECKING:
    from .gui_app import GUIApp

class WildcardInserter(ttk.Frame):
    """The wildcard inserter listbox and its frame."""
    def __init__(self, parent, app_instance: 'GUIApp', insert_callback: Callable, manage_callback: Callable, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_instance = app_instance
        
        frame = ttk.LabelFrame(self, text="Insert Wildcard", padding=5)
        self.wildcard_list_var = tk.StringVar()

        list_scroll_frame = ttk.Frame(frame)
        list_scroll_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_scroll_frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(list_scroll_frame, font=self.app_instance.default_font, yscrollcommand=scrollbar.set, listvariable=self.wildcard_list_var)
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-Button-1>", insert_callback)

        # Add tooltip for previewing wildcard content
        self.tooltip = Tooltip(self.listbox)
        self.listbox.bind("<Motion>", self._show_wildcard_preview)
        self.listbox.bind("<Leave>", self._hide_wildcard_preview)
        self.tooltip_after_id = None
        self.last_hovered_index = -1

        ttk.Button(frame, text="Manage Wildcards...", command=manage_callback).pack(pady=(5, 0), fill=tk.X)
        frame.pack(fill=tk.BOTH, expand=True)

    def populate(self, wildcard_files: List[str]):
        basenames = [os.path.splitext(f)[0] for f in wildcard_files]
        self.wildcard_list_var.set(basenames)

    def get_selected_wildcard_name(self) -> Optional[str]:
        selected_indices = self.listbox.curselection()
        if not selected_indices:
            return None
        return self.listbox.get(selected_indices[0])

    def _display_tooltip_content(self, index, event):
        """Fetches content and displays the tooltip. This is called after a delay."""
        try:
            wildcard_name = self.listbox.get(index)
            options = self.app_instance.processor.get_wildcard_options(wildcard_name)

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

    def _show_wildcard_preview(self, event):
        """Schedules a tooltip to appear after a short delay."""
        if self.tooltip_after_id:
            self.after_cancel(self.tooltip_after_id)

        index = self.listbox.nearest(event.y)
        if index != self.last_hovered_index:
            self.tooltip.hide() # Hide immediately if moving to a new item
        self.last_hovered_index = index
        self.tooltip_after_id = self.after(500, lambda: self._display_tooltip_content(index, event))

    def _hide_wildcard_preview(self, event=None):
        """Hides the wildcard preview tooltip."""
        self.last_hovered_index = -1
        if self.tooltip_after_id:
            self.after_cancel(self.tooltip_after_id)
            self.tooltip_after_id = None
        self.tooltip.hide()