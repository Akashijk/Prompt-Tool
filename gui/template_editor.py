"""The template editor text widget and its frame."""

import tkinter as tk
from tkinter import ttk
import re
from typing import Callable, List, Dict

from .common import TemplateEditorContextMenu, Tooltip

class TemplateEditor(ttk.Frame):
    """The template editor text widget and its frame."""
    def __init__(self, parent, app_instance, live_update_callback: Callable, double_click_callback: Callable, generate_wildcard_callback: Callable, brainstorm_callback: Callable, create_wildcard_callback: Callable, edit_wildcard_callback: Callable, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_instance = app_instance
        
        self.frame = ttk.LabelFrame(self, text="Template Content", padding=5)
        self.text_widget = tk.Text(self.frame, wrap=tk.WORD, font=self.app_instance.fixed_font, undo=True, exportselection=False)
        self.text_widget.tag_configure("any_wildcard")
        self.text_widget.tag_configure("missing_wildcard")
        self.text_widget.tag_configure("ordering_error")
        self.is_dragging = False
        self.drag_start_index = None
        self.ordering_error_tooltip = Tooltip(self.text_widget)
        self.ordering_errors: Dict[str, str] = {}
        self.dragged_text = ""
        TemplateEditorContextMenu(
            self.text_widget, 
            generate_wildcard_callback, 
            brainstorm_callback,
            create_wildcard_callback,
            edit_wildcard_callback,
            live_update_callback
        )
        self.text_widget.pack(fill=tk.BOTH, expand=True)
        self.text_widget.bind("<KeyRelease>", live_update_callback)
        self.text_widget.bind("<Double-Button-1>", double_click_callback)
        # Drag and drop bindings for wildcard tags
        self.text_widget.tag_bind("any_wildcard", "<ButtonPress-1>", self._on_drag_start)
        self.text_widget.tag_bind("any_wildcard", "<B1-Motion>", self._on_drag_motion)
        # Bind release to the whole widget to catch it even if the mouse moves off the tag
        self.text_widget.bind("<ButtonRelease-1>", self._on_drag_end)
        # Bindings for the ordering error tooltip
        self.text_widget.tag_bind("ordering_error", "<Enter>", self._on_ordering_error_enter)
        self.text_widget.tag_bind("ordering_error", "<Leave>", self._on_ordering_error_leave)
        
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
        self.text_widget.tag_remove("ordering_error", "1.0", tk.END)
        self.text_widget.tag_remove("any_wildcard", "1.0", tk.END)

        content = self.get_content()
        if not content:
            return

        # Validate the template for requires-clause ordering issues
        self.ordering_errors = self.app_instance.processor.validate_template_order(content)

        for match in re.finditer(r'__([a-zA-Z0-9_.\s-]+?)__', content):
            wildcard_name = match.group(1)
            start_index = f"1.0+{match.start()}c"
            end_index = f"1.0+{match.end()}c"
            self.text_widget.tag_add("any_wildcard", start_index, end_index)
            if wildcard_name not in known_wildcards:
                self.text_widget.tag_add("missing_wildcard", start_index, end_index)
            if wildcard_name in self.ordering_errors:
                self.text_widget.tag_add("ordering_error", start_index, end_index)

    def insert_wildcard_tag(self, wildcard_name: str):
        """Inserts a wildcard tag, overwriting a selection or the tag under the cursor."""
        tag_to_insert = f"__{wildcard_name}__"
        try:
            # Priority 1: Overwrite active selection
            if self.text_widget.tag_ranges("sel"):
                self.text_widget.delete("sel.first", "sel.last")
                self.text_widget.insert(tk.INSERT, tag_to_insert)
                self.text_widget.focus_set()
                return

            # Priority 2: Overwrite wildcard tag under cursor if no selection
            cursor_index = self.text_widget.index(tk.INSERT)
            ranges = self.text_widget.tag_ranges("any_wildcard")
            for i in range(0, len(ranges), 2):
                start, end = ranges[i], ranges[i+1]
                if self.text_widget.compare(cursor_index, ">=", start) and self.text_widget.compare(cursor_index, "<=", end):
                    self.text_widget.delete(start, end)
                    self.text_widget.insert(start, tag_to_insert)
                    self.text_widget.focus_set()
                    return # Exit after replacing
            
            # Fallback: Insert at cursor
            self.text_widget.insert(tk.INSERT, tag_to_insert)
        except tk.TclError:
            # Fallback for edge cases, e.g., if selection is gone
            self.text_widget.insert(tk.INSERT, tag_to_insert)

        self.text_widget.focus_set()

    def _on_drag_start(self, event):
        """Initiates a drag operation for a wildcard tag."""
        index = self.text_widget.index(f"@{event.x},{event.y}")
        tag_ranges = self.text_widget.tag_ranges("any_wildcard")
        for i in range(0, len(tag_ranges), 2):
            start, end = tag_ranges[i], tag_ranges[i+1]
            if self.text_widget.compare(index, ">=", start) and self.text_widget.compare(index, "<", end):
                self.is_dragging = True
                self.drag_start_index = start
                self.dragged_text = self.text_widget.get(start, end)
                self.text_widget.config(cursor="hand2")
                return "break" # Prevent default text selection behavior

    def _on_drag_motion(self, event):
        """Handles the motion during a drag operation (currently just for visual feedback)."""
        if not self.is_dragging:
            return
        # This is where you could add more advanced visual feedback, like a ghost image.
        # For now, the cursor change is sufficient.

    def _on_drag_end(self, event):
        """Completes the drag-and-drop operation."""
        if not self.is_dragging:
            return

        self.is_dragging = False
        self.text_widget.config(cursor="")

        raw_drop_index = self.text_widget.index(f"@{event.x},{event.y}")
        start_index_obj = self.text_widget.index(self.drag_start_index)

        if self.text_widget.compare(raw_drop_index, ">=", start_index_obj) and self.text_widget.compare(raw_drop_index, "<=", f"{start_index_obj} + {len(self.dragged_text)}c"):
            return # Dropped on itself, do nothing

        # --- Smart Drop Logic ---
        insertion_point = raw_drop_index
        text_to_insert = self.dragged_text

        # Check if we are dropping onto another wildcard
        tag_ranges = self.text_widget.tag_ranges("any_wildcard")
        for i in range(0, len(tag_ranges), 2):
            start, end = tag_ranges[i], tag_ranges[i+1]
            # Skip the tag we are currently dragging
            if self.text_widget.compare(start, "==", self.drag_start_index):
                continue

            if self.text_widget.compare(raw_drop_index, ">=", start) and self.text_widget.compare(raw_drop_index, "<", end):
                # We dropped onto another tag. Decide whether to prepend or append.
                # A simple heuristic: check if the drop point is in the first or second half of the target tag.
                start_num = float(str(self.text_widget.index(start)).split('.')[1])
                end_num = float(str(self.text_widget.index(end)).split('.')[1])
                drop_num = float(str(self.text_widget.index(raw_drop_index)).split('.')[1])
                midpoint = start_num + (end_num - start_num) / 2

                if drop_num < midpoint: # Dropped on the first half
                    insertion_point = start
                    text_to_insert = f"{self.dragged_text}, "
                else: # Dropped on the second half
                    insertion_point = end
                    text_to_insert = f", {self.dragged_text}"
                break

        self.text_widget.delete(self.drag_start_index, f"{self.drag_start_index} + {len(self.dragged_text)}c")

        # Adjust insertion point if it was after the deleted text
        if self.text_widget.compare(insertion_point, ">", start_index_obj):
            insertion_point = self.text_widget.index(f"{insertion_point} - {len(self.dragged_text)}c")

        self.text_widget.insert(insertion_point, text_to_insert)
        self.app_instance._schedule_live_update()

    def _on_ordering_error_enter(self, event):
        """Show tooltip for ordering errors."""
        index = self.text_widget.index(f"@{event.x},{event.y}")
        
        # Find the wildcard name under the cursor
        tag_ranges = self.text_widget.tag_ranges("ordering_error")
        for i in range(0, len(tag_ranges), 2):
            start, end = tag_ranges[i], tag_ranges[i+1]
            if self.text_widget.compare(index, ">=", start) and self.text_widget.compare(index, "<", end):
                wildcard_text = self.text_widget.get(start, end)
                match = re.search(r'__([a-zA-Z0-9_.\s-]+?)__', wildcard_text)
                if match:
                    wildcard_name = match.group(1)
                    if wildcard_name in self.ordering_errors:
                        error_message = self.ordering_errors[wildcard_name]
                        self.ordering_error_tooltip.text = f"Ordering Error: {error_message}"
                        self.ordering_error_tooltip.show(event)
                break

    def _on_ordering_error_leave(self, event):
        """Hide tooltip for ordering errors."""
        self.ordering_error_tooltip.hide(event)