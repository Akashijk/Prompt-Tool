"""Common, reusable GUI components for the application."""

import tkinter as tk
from tkinter import ttk
import sys
import re
from typing import Callable, Optional

class Tooltip:
    """A simple tooltip for tkinter widgets."""
    def __init__(self, widget, text=""):
        self.widget = widget
        self.text = text
        self.tooltip_window = None

    def show(self, event):
        if self.tooltip_window:
            return
        x = event.x_root + 15
        y = event.y_root + 10

        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        # Determine colors based on the current theme by checking the top-level window
        is_dark = False
        try:
            # The top-level window should be the GUIApp instance which has the theme manager
            if hasattr(self.widget.winfo_toplevel(), 'theme_manager'):
                is_dark = self.widget.winfo_toplevel().theme_manager.current_theme == "dark"
        except tk.TclError:
            # This can happen if the widget is being destroyed.
            pass

        bg_color = "#2b2b2b" if is_dark else "#ffffe0"
        fg_color = "#ffffff" if is_dark else "#000000"

        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background=bg_color, foreground=fg_color, relief='solid', borderwidth=1,
                         font=("Helvetica", "10", "normal"))
        label.pack(ipadx=1)

    def hide(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None

class TextContextMenu:
    """A context menu for tkinter Text widgets."""
    def __init__(self, widget):
        self.widget = widget
        self.menu = tk.Menu(widget, tearoff=0)
        self.menu.add_command(label="Cut", command=self.cut)
        self.menu.add_command(label="Copy", command=self.copy)
        self.menu.add_command(label="Paste", command=self.paste)
        self.menu.add_separator()
        self.menu.add_command(label="Select All", command=self.select_all)

        # Use ButtonPress to handle the event before the widget's default selection behavior
        if sys.platform == "darwin":  # macOS
            self.widget.bind("<ButtonPress-2>", self.show_menu)
            self.widget.bind("<Control-Button-1>", self.show_menu)
        else:  # Windows/Linux
            self.widget.bind("<ButtonPress-3>", self.show_menu)

    def show_menu(self, event):
        """
        The main entry point for showing the context menu. It sets the cursor,
        calls the configuration hook, and then displays the menu.
        """
        # Move cursor to click position
        # Only move the cursor if there is no active selection.
        # Right-clicking on a selection should not move the cursor.
        if not self.widget.tag_ranges("sel"):
            self.widget.mark_set(tk.INSERT, f"@{event.x},{event.y}")
        # This is the hook for subclasses to configure their specific menu items.
        self._configure_menu_items(event)

        self.menu.tk_popup(event.x_root, event.y_root)
        return "break" # Prevent default OS behavior (like text selection)

    def _configure_menu_items(self, event):
        """
        Configures the state of the base menu items (Cut, Copy, Paste).
        Subclasses should override this method to add their own logic after
        calling super()._configure_menu_items(event).
        """
        # Disable/enable menu items based on state
        try:
            self.widget.selection_get()
            self.menu.entryconfig("Cut", state=tk.NORMAL)
            self.menu.entryconfig("Copy", state=tk.NORMAL)
        except tk.TclError:
            self.menu.entryconfig("Cut", state=tk.DISABLED)
            self.menu.entryconfig("Copy", state=tk.DISABLED)

        try:
            self.widget.clipboard_get()
            self.menu.entryconfig("Paste", state=tk.NORMAL)
        except tk.TclError:
            self.menu.entryconfig("Paste", state=tk.DISABLED)

    def cut(self): self.widget.event_generate("<<Cut>>")
    def copy(self): self.widget.event_generate("<<Copy>>")
    def paste(self): self.widget.event_generate("<<Paste>>")
    def select_all(self): self.widget.tag_add("sel", "1.0", "end"); return "break"

class BrainstormingContextMenu(TextContextMenu):
    """A context menu for the brainstorming history with a rewrite function."""
    def __init__(self, widget, rewrite_callback: Callable):
        super().__init__(widget)
        self.rewrite_callback = rewrite_callback
        self.menu.add_separator()
        self.menu.add_command(label="Rewrite Selection with AI...", command=self._rewrite_selection, state=tk.DISABLED)

    def _configure_menu_items(self, event):
        super()._configure_menu_items(event)
        try:
            self.widget.selection_get()
            self.menu.entryconfig("Rewrite Selection with AI...", state=tk.NORMAL)
        except tk.TclError:
            self.menu.entryconfig("Rewrite Selection with AI...", state=tk.DISABLED)

    def _rewrite_selection(self):
        try:
            self.rewrite_callback()
        except tk.TclError:
            pass # No selection

class PromptPreviewContextMenu(TextContextMenu):
    """A context menu for the prompt preview with a wildcard generator."""
    def __init__(self, widget, parent_app, generate_wildcard_callback: Callable, edit_wildcard_callback: Callable):
        super().__init__(widget)
        self.parent_app = parent_app
        self.generate_wildcard_callback = generate_wildcard_callback
        self.edit_wildcard_callback = edit_wildcard_callback
        self.last_event = None
        self.menu.add_separator()
        self.menu.add_command(label="Generate Missing Wildcard...", command=self._generate_wildcard, state=tk.DISABLED)
        self.menu.add_command(label="Edit Wildcard...", command=self._edit_wildcard, state=tk.DISABLED)

    def _configure_menu_items(self, event):
        self.last_event = event
        # We need to temporarily enable the widget to check tags if it's disabled
        original_state = self.widget.cget("state")
        if original_state == tk.DISABLED:
            self.widget.config(state=tk.NORMAL)

        super()._configure_menu_items(event) # Call parent to set cut/copy/paste
        
        index = self.widget.index(f"@{event.x},{event.y}")
        tags = self.widget.tag_names(index)
        
        is_missing = "missing_wildcard" in tags
        is_wildcard = "wildcard" in tags

        self.menu.entryconfig("Generate Missing Wildcard...", state=tk.NORMAL if is_missing else tk.DISABLED)
        self.menu.entryconfig("Edit Wildcard...", state=tk.NORMAL if is_wildcard and not is_missing else tk.DISABLED)
        
        if original_state == tk.DISABLED:
            self.widget.config(state=original_state)

    def _get_wildcard_name_from_event(self) -> Optional[str]:
        """Finds the wildcard name associated with the segment under the cursor."""
        if not self.last_event: return None
        try:
            index = self.widget.index(f"@{self.last_event.x},{self.last_event.y}")
            
            # Use the robust segment map instead of parsing tags
            for start, end, seg_index in self.parent_app.segment_map:
                if self.widget.compare(index, ">=", start) and self.widget.compare(index, "<", end):
                    segment = self.parent_app.current_structured_prompt[seg_index]
                    return segment.wildcard_name
        except (IndexError, tk.TclError) as e:
            print(f"Error getting wildcard name from event: {e}")
        return None

    def _generate_wildcard(self):
        wildcard_name = self._get_wildcard_name_from_event()
        if wildcard_name:
            self.generate_wildcard_callback(wildcard_name)

    def _edit_wildcard(self):
        wildcard_name = self._get_wildcard_name_from_event()
        if wildcard_name:
            self.edit_wildcard_callback(wildcard_name)

class TemplateEditorContextMenu(TextContextMenu):
    """A specialized context menu for the template editor with a wildcard generator."""
    def __init__(self, widget, generate_wildcard_callback: Callable, brainstorm_callback: Callable, create_wildcard_callback: Callable, edit_wildcard_callback: Callable, live_update_callback: Callable):
        super().__init__(widget)
        self.generate_wildcard_callback = generate_wildcard_callback
        self.brainstorm_callback = brainstorm_callback
        self.create_wildcard_callback = create_wildcard_callback
        self.edit_wildcard_callback = edit_wildcard_callback
        self.live_update_callback = live_update_callback
        self.last_event = None
        self.menu.add_command(label="Increase Weight (+)", command=self._increase_weight, state=tk.DISABLED)
        self.menu.add_command(label="Decrease Weight (-)", command=self._decrease_weight, state=tk.DISABLED)
        self.menu.add_separator()
        self.menu.add_command(label="Generate Missing Wildcard...", command=self._generate_wildcard, state=tk.DISABLED)
        self.menu.add_command(label="Create Wildcard from Selection...", command=self._create_wildcard, state=tk.DISABLED)
        self.menu.add_command(label="Brainstorm with AI...", command=self.brainstorm_callback, state=tk.DISABLED)
        self.menu.add_separator()
        self.menu.add_command(label="Edit Wildcard...", command=self._edit_wildcard, state=tk.DISABLED)

    def _configure_menu_items(self, event):
        self.last_event = event
        super()._configure_menu_items(event) # Call parent to set cut/copy/paste

        # Get the text to operate on first. This will be a selection or a word.
        target = self._get_text_to_modify()
        
        # Enable/disable based on whether we found a target
        can_operate = target is not None
        self.menu.entryconfig("Increase Weight (+)", state=tk.NORMAL if can_operate else tk.DISABLED)
        
        # Decrease weight is only possible if the text is already weighted
        can_decrease = False
        if can_operate:
            text_to_modify = target[2].strip()
            if text_to_modify.startswith(('(', '[')):
                can_decrease = True
        self.menu.entryconfig("Decrease Weight (-)", state=tk.NORMAL if can_decrease else tk.DISABLED)

        # Handle other menu items
        index = self.widget.index(f"@{event.x},{event.y}")
        tags = self.widget.tag_names(index)
        is_missing = "missing_wildcard" in tags
        is_wildcard = "any_wildcard" in tags

        self.menu.entryconfig("Generate Missing Wildcard...", state=tk.NORMAL if is_missing else tk.DISABLED)
        self.menu.entryconfig("Edit Wildcard...", state=tk.NORMAL if is_wildcard and not is_missing else tk.DISABLED)
        
        has_selection = False
        try:
            self.widget.selection_get()
            has_selection = True
        except tk.TclError:
            pass
        self.menu.entryconfig("Create Wildcard from Selection...", state=tk.NORMAL if has_selection else tk.DISABLED)
        
        if self.widget.get("1.0", "end-1c").strip():
            self.menu.entryconfig("Brainstorm with AI...", state=tk.NORMAL)
        else:
            self.menu.entryconfig("Brainstorm with AI...", state=tk.DISABLED)

    def _get_wildcard_at_event(self) -> Optional[str]:
        """Helper to get the full wildcard tag text under the last click event."""
        if not self.last_event: return None
        index = self.widget.index(f"@{self.last_event.x},{self.last_event.y}")
        # Find the tag range that contains the index
        tag_ranges = self.widget.tag_ranges("any_wildcard")
        for i in range(0, len(tag_ranges), 2):
            start, end = tag_ranges[i], tag_ranges[i+1]
            if self.widget.compare(index, ">=", start) and self.widget.compare(index, "<", end):
                return self.widget.get(start, end)
        return None

    def _generate_wildcard(self):
        wildcard_text = self._get_wildcard_at_event()
        if not wildcard_text: return
        
        match = re.fullmatch(r'__([a-zA-Z0-9_.\s-]+)__', wildcard_text)
        if match:
            wildcard_name = match.group(1)
            self.generate_wildcard_callback(wildcard_name)

    def _edit_wildcard(self):
        wildcard_text = self._get_wildcard_at_event()
        if not wildcard_text: return
        
        match = re.fullmatch(r'__([a-zA-Z0-9_.\s-]+)__', wildcard_text)
        if match:
            wildcard_name = match.group(1)
            self.edit_wildcard_callback(wildcard_name)

    def _create_wildcard(self):
        try:
            selected_text = self.widget.selection_get()
            if selected_text:
                self.create_wildcard_callback(selected_text)
        except tk.TclError:
            pass # No selection

    def _get_text_to_modify(self) -> Optional[tuple[str, str, str]]:
        """
        Gets the text to operate on. The priority is:
        1. Active text selection.
        2. A full __wildcard__ tag under the cursor.
        If a wildcard is found, it expands to include any weighting wrappers.
        """
        # Priority 1: Active selection
        try:
            start = self.widget.index("sel.first")
            end = self.widget.index("sel.last")
            text = self.widget.get(start, end)
            if text.strip(): # Ensure selection is not just whitespace
                return start, end, text
        except tk.TclError:
            pass # No selection

        # Priority 2: Wildcard tag under cursor (and its potential wrapper)
        if self.last_event:
            index_at_click = self.widget.index(f"@{self.last_event.x},{self.last_event.y}")
            tag_ranges = self.widget.tag_ranges("any_wildcard")
            for i in range(0, len(tag_ranges), 2):
                start, end = tag_ranges[i], tag_ranges[i+1]
                if self.widget.compare(index_at_click, ">=", start) and self.widget.compare(index_at_click, "<", end):
                    # Found the core wildcard tag. Now, expand outwards to find the full weighted expression.
                    final_start = start
                    final_end = end

                    while True:
                        char_before = self.widget.get(f"{final_start}-1c", final_start)
                        # Look for a closing parenthesis and a number
                        potential_end_text = self.widget.get(final_end, f"{final_end}+10c") # Get enough text
                        match = re.match(r'\)([\d.]+)', potential_end_text)

                        if char_before == '(' and match:
                            # Found a wrapper. Expand our boundaries and loop again.
                            final_start = self.widget.index(f"{final_start}-1c")
                            final_end = self.widget.index(f"{final_end}+{len(match.group(0))}c")
                        else:
                            # No more wrappers found, break the loop.
                            break
                    
                    return final_start, final_end, self.widget.get(final_start, final_end)
            
        return None

    def _increase_weight(self):
        target = self._get_text_to_modify()
        if not target: return

        start_index, end_index, text_to_modify = target
        text = text_to_modify.strip()
        new_text = text

        match_weighted = re.fullmatch(r'\((.*)\)([\d.]+)$', text, re.DOTALL)
        match_decreased = re.fullmatch(r'\[(.*)\]$', text, re.DOTALL)
        match_simple = re.fullmatch(r'\((.*)\)$', text, re.DOTALL)

        if match_weighted:
            base, weight_str = match_weighted.groups()
            new_weight = min(2.0, float(weight_str) + 0.1)
            new_text = f"({base}){new_weight:.1f}"
        elif match_decreased:
            base = match_decreased.group(1)
            new_text = base
        elif match_simple:
            base = match_simple.group(1)
            new_text = f"({base})1.1"
        else: # Plain text
            base = text
            new_text = f"({base})1.1"

        self.widget.delete(start_index, end_index)
        self.widget.insert(start_index, new_text)
        self.live_update_callback()

        # Re-select the modified text to allow for repeated operations
        new_end_index = self.widget.index(f"{start_index} + {len(new_text)}c")
        self.widget.tag_add("sel", start_index, new_end_index)

    def _decrease_weight(self):
        target = self._get_text_to_modify()
        if not target: return

        start_index, end_index, text_to_modify = target
        text = text_to_modify.strip()
        new_text = text

        match_weighted = re.fullmatch(r'\((.*)\)([\d.]+)$', text, re.DOTALL)
        match_decreased = re.fullmatch(r'\[(.*)\]$', text, re.DOTALL)
        match_simple = re.fullmatch(r'\((.*)\)$', text, re.DOTALL)

        if match_weighted:
            base, weight_str = match_weighted.groups()
            new_weight = float(weight_str) - 0.1
            if new_weight <= 1.0:
                new_text = f"({base})" # back to simple emphasis
            else:
                new_text = f"({base}){new_weight:.1f}"
        elif match_simple:
            base = match_simple.group(1)
            new_text = base
        elif match_decreased:
            return # Already at minimum emphasis
        else: # Plain text
            base = text
            new_text = f"[{base}]"

        self.widget.delete(start_index, end_index)
        self.widget.insert(start_index, new_text)
        self.live_update_callback()

        # Re-select the modified text to allow for repeated operations
        new_end_index = self.widget.index(f"{start_index} + {len(new_text)}c")
        self.widget.tag_add("sel", start_index, new_end_index)

class LoadingAnimation(ttk.Frame):
    """A smooth, spinning arc loading animation widget."""
    def __init__(self, parent, size=16):
        super().__init__(parent, width=size, height=size)
        self.canvas = tk.Canvas(self, width=size, height=size, highlightthickness=0)
        self.canvas.pack()
        
        self.size = size
        self.color = "gray"
        self.is_running = False
        self.animation_job = None
        
        self.angle = 0
        self.arc_id = None
        self.speed = 10  # degrees per frame
        self.extent = 120  # length of the arc in degrees

    def update_style(self, bg_color, dot_color, is_dark_theme=False):
        """Updates the colors to match the theme."""
        self.canvas.config(bg=bg_color)
        self.color = dot_color

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.angle = 0
            self._animate()

    def stop(self):
        if self.is_running:
            self.is_running = False
            if self.animation_job:
                self.after_cancel(self.animation_job)
                self.animation_job = None
            if self.arc_id:
                self.canvas.delete(self.arc_id)
                self.arc_id = None

    def _animate(self):
        if not self.is_running:
            return

        if self.arc_id:
            self.canvas.delete(self.arc_id)

        padding = 2
        box = (padding, padding, self.size - padding, self.size - padding)
        
        self.arc_id = self.canvas.create_arc(
            box, start=self.angle, extent=self.extent, style=tk.ARC, outline=self.color, width=2
        )

        self.angle = (self.angle - self.speed) % 360
        self.animation_job = self.after(30, self._animate)  # ~33 FPS for a smooth spin

class SmartWindowMixin:
    """Mixin class to add smart window sizing behavior."""
    def smart_geometry(self, min_width=600, min_height=400, padding=50):
        """
        Calculates and sets appropriate window geometry based on content.
        
        Args:
            min_width: Minimum window width
            min_height: Minimum window height
            padding: Extra space to add around the content
        """
        # Hide the window to prevent flickering during positioning
        self.withdraw()

        # Update all idle tasks to ensure widgets are rendered
        self.update_idletasks()
        
        # Get required size for all widgets
        required_width = self.winfo_reqwidth()
        required_height = self.winfo_reqheight()
        
        # Add padding and ensure minimums
        width = max(required_width + padding, min_width)
        height = max(required_height + padding, min_height)
        
        # Get screen dimensions
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        # Center the window
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        
        # Set geometry
        self.geometry(f"{width}x{height}+{x}+{y}")
        
        # Set minimum size
        self.minsize(min_width, min_height)

        # Bind to Configure event to handle window resizing
        self.bind("<Configure>", self._on_window_configure)

        # Make the window visible now that it's positioned
        self.deiconify()
        
    def _on_window_configure(self, event):
        """Handle window resize events to maintain proper layout."""
        if event.widget == self:
            # Update widget layouts if needed
            self.update_idletasks()