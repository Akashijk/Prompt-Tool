"""Common, reusable GUI components for the application."""

import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont
from PIL import Image, ImageTk
import difflib
import sys
import os
import re
from typing import Callable, Optional, Dict, Any, List
import queue
import threading
from . import custom_dialogs

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
    """A context menu for tkinter Text and Entry widgets."""
    def __init__(self, widget, insert_wildcard_callback: Optional[Callable] = None):
        self.widget = widget
        self.insert_wildcard_callback = insert_wildcard_callback
        self.menu = tk.Menu(widget, tearoff=0)
        self.menu.add_command(label="Cut", command=self.cut)
        self.menu.add_command(label="Copy", command=self.copy)
        self.menu.add_command(label="Paste", command=self.paste)
        self.menu.add_command(label="Insert Wildcard...", command=self._insert_wildcard, state=tk.DISABLED)
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
        # For Text widgets, move cursor to click position if there's no selection.
        # For Entry widgets, this is generally the default behavior.
        if isinstance(self.widget, tk.Text):
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

        # Enable the insert wildcard option if the callback is provided
        if self.insert_wildcard_callback:
            self.menu.entryconfig("Insert Wildcard...", state=tk.NORMAL)

    def cut(self): self.widget.event_generate("<<Cut>>")
    def copy(self): self.widget.event_generate("<<Copy>>")
    def paste(self): self.widget.event_generate("<<Paste>>")
    def select_all(self):
        if isinstance(self.widget, tk.Text):
            self.widget.tag_add("sel", "1.0", "end")
        elif isinstance(self.widget, (tk.Entry, ttk.Entry)):
            self.widget.selection_range(0, 'end')
        return "break"

    def _insert_wildcard(self):
        if self.insert_wildcard_callback:
            self.insert_wildcard_callback()

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
    def __init__(self, widget, generate_wildcard_callback: Callable, brainstorm_callback: Callable, create_wildcard_callback: Callable, edit_wildcard_callback: Callable, live_update_callback: Callable, toggle_roll_unique_callback: Callable, select_n_items_callback: Callable):
        super().__init__(widget)
        self.generate_wildcard_callback = generate_wildcard_callback
        self.brainstorm_callback = brainstorm_callback
        self.create_wildcard_callback = create_wildcard_callback
        self.edit_wildcard_callback = edit_wildcard_callback
        self.live_update_callback = live_update_callback
        self.toggle_roll_unique_callback = toggle_roll_unique_callback
        self.select_n_items_callback = select_n_items_callback
        self.last_event = None
        self.menu.add_command(label="Increase Weight (+)", command=self._increase_weight, state=tk.DISABLED)
        self.menu.add_command(label="Decrease Weight (-)", command=self._decrease_weight, state=tk.DISABLED)
        self.menu.add_separator()
        self.menu.add_command(label="Roll Unique Value (!)", command=self.toggle_roll_unique_callback, state=tk.DISABLED)
        self.menu.add_command(label="Select N Items...", command=self.select_n_items_callback, state=tk.DISABLED)
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
        
        # Dynamically update labels for advanced syntax
        if is_wildcard:
            wildcard_text = self._get_wildcard_at_event()
            if wildcard_text:
                # Regex to capture all parts
                pattern = re.compile(r'__(!)?([a-zA-Z0-9_.\s-]+?)((?::\d+(?:-\d+)?)?)__')
                match = pattern.fullmatch(wildcard_text)
                if match:
                    force_unique_str, _, multi_select_part = match.groups()
                    
                    self.menu.entryconfig(9, label="Roll Consistent Value (remove !)" if force_unique_str else "Roll Unique Value (!)")
                    self.menu.entryconfig(10, label="Change/Remove N Items..." if multi_select_part else "Select N Items...")
        else:
            # Reset labels if not over a wildcard
            self.menu.entryconfig(9, label="Roll Unique Value (!)")
            self.menu.entryconfig(10, label="Select N Items...")

        self.menu.entryconfig(9, state=tk.NORMAL if is_wildcard else tk.DISABLED)
        self.menu.entryconfig(10, state=tk.NORMAL if is_wildcard else tk.DISABLED)
        
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
    # --- NEW: Class-level variables for a shared animation loop ---
    _active_animations: List['LoadingAnimation'] = []
    _animation_job_id: Optional[str] = None

    def __init__(self, parent, size=16):
        super().__init__(parent, width=size, height=size)
        self.canvas = tk.Canvas(self, width=size, height=size, highlightthickness=0)
        self.canvas.pack(expand=True)
        
        self.size = size
        self.color = "gray"
        self.is_running = False
        
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
            self.angle = 0 # Reset angle on start

            # --- OPTIMIZATION: Create the arc object once on start ---
            if self.arc_id is None:
                padding = 2
                box = (padding, padding, self.size - padding, self.size - padding)
                self.arc_id = self.canvas.create_arc(box, start=self.angle, extent=self.extent, style=tk.ARC, outline=self.color, width=2)

            if self not in LoadingAnimation._active_animations:
                LoadingAnimation._active_animations.append(self)
            
            # If the master loop isn't already running, start it.
            if not LoadingAnimation._animation_job_id:
                LoadingAnimation._master_animate_loop()
    def stop(self):
        if self.is_running:
            self.is_running = False
            # Use a try-except block in case the item was already removed
            try:
                LoadingAnimation._active_animations.remove(self)
            except ValueError:
                pass
            
            # If this was the last active animation, stop the master loop.
            if not LoadingAnimation._active_animations and LoadingAnimation._animation_job_id:
                # Need a widget to cancel the job. `self` is fine.
                self.after_cancel(LoadingAnimation._animation_job_id)
                LoadingAnimation._animation_job_id = None
            # --- OPTIMIZATION: Delete the arc object on stop ---
            if self.arc_id:
                self.canvas.delete(self.arc_id)
                self.arc_id = None

    def _draw_single_frame(self):
        """Draws one frame of the animation. Called by the master loop."""
        if not self.is_running or not self.arc_id:
            return

        # --- OPTIMIZATION: Use itemconfig to modify the existing arc instead of recreating it ---
        self.canvas.itemconfig(self.arc_id, start=self.angle)

        self.angle = (self.angle - self.speed) % 360
        
    @classmethod
    def _master_animate_loop(cls):
        """The single, shared loop that updates all active animations."""
        # --- FIX: Check for active animations *before* stopping the loop ---
        # This prevents a race condition where the loop stops before new animations are added.
        if not cls._active_animations:
            cls._animation_job_id = None
            return

        # Find a valid, existing widget to schedule the next call.
        # This is important because some animations might be destroyed while the loop is running.
        widget_for_after = next((anim for anim in cls._active_animations if anim.winfo_exists()), None)
        
        if not widget_for_after:
            # All animations were destroyed. Stop the loop.
            cls._animation_job_id = None
            return

        # Update all active and existing animations
        for anim in cls._active_animations:
            if anim.winfo_exists():
                anim._draw_single_frame()
        
        # Schedule the next iteration
        cls._animation_job_id = widget_for_after.after(30, cls._master_animate_loop)


class SmartWindowMixin:
    """Mixin class to add smart window sizing behavior."""
    def smart_geometry(self, min_width: int = 600, min_height: int = 400, padding: int = 50, width_percent: Optional[float] = None, height_percent: Optional[float] = None):
        """
        Calculates and sets appropriate window geometry based on content and screen size.
        
        Args:
            min_width: Minimum window width
            min_height: Minimum window height
            padding: Extra space to add around the content
            width_percent: Desired width as a percentage of screen width (e.g., 0.7 for 70%)
            height_percent: Desired height as a percentage of screen height (e.g., 0.8 for 80%)
        """
        # Hide the window to prevent flickering during positioning
        self.withdraw()

        # Update all idle tasks to ensure widgets are rendered
        self.update_idletasks()

        # Get required size for all widgets
        required_width = self.winfo_reqwidth()
        required_height = self.winfo_reqheight()

        # Get screen dimensions
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # Calculate desired width based on percentage if provided
        desired_width = 0
        if width_percent:
            desired_width = int(screen_width * width_percent)

        # Calculate desired height based on percentage if provided
        desired_height = 0
        if height_percent:
            desired_height = int(screen_height * height_percent)

        # Determine final width and height, capped by screen size
        width = min(screen_width - padding, max(required_width + padding, min_width, desired_width))
        height = min(screen_height - padding, max(required_height + padding, min_height, desired_height))

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

class ScrollableFrame(ttk.Frame):
    """
    A reusable frame that contains a scrollable area.
    Widgets should be packed into the `self.scrollable_frame` attribute.
    """
    def __init__(self, parent, scroll_callback: Optional[Callable] = None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.scroll_callback = scroll_callback

        # Create the canvas and scrollbar
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._on_scroll)
        
        # This is the frame that will hold the content and be scrolled
        self.scrollable_frame = ttk.Frame(self.canvas)

        # Bind the frame's size to the canvas's scroll region
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        # Create a window in the canvas that holds the frame
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Bind the canvas resizing to update the window width
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Pack the widgets
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        # Bind mouse wheel scrolling to the canvas and the frame
        for widget in [self.canvas, self.scrollable_frame]:
            widget.bind("<MouseWheel>", self._on_mouse_wheel)

    def _on_canvas_configure(self, event):
        """Updates the width of the frame inside the canvas to match the canvas width."""
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_scroll(self, *args):
        self.canvas.yview(*args)
        if self.scroll_callback:
            self.scroll_callback()

    def _on_mouse_wheel(self, event):
        delta = -1 * (event.delta if sys.platform == 'darwin' else event.delta // 120)
        self.canvas.yview_scroll(delta, "units")
        if self.scroll_callback:
            self.scroll_callback()

class DiffViewer(ttk.Frame):
    """A reusable widget for displaying text diffs with highlighting."""
    def __init__(self, parent, font, **kwargs):
        super().__init__(parent, **kwargs)
        self.font = font
        self.text_widget = tk.Text(self, wrap=tk.WORD, font=self.font, state=tk.DISABLED, exportselection=False)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.text_widget.tag_configure("addition", foreground="green")
        self.text_widget.tag_configure("deletion", foreground="red")

    def set_diff_text(self, diff_text: str):
        """Sets the text in the widget and applies highlighting."""
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.delete("1.0", tk.END)
        self.text_widget.insert("1.0", diff_text)
        
        for i, line in enumerate(diff_text.splitlines(), 1):
            if line.startswith('+') and not line.startswith('+++'):
                self.text_widget.tag_add("addition", f"{i}.0", f"{i}.end")
            elif line.startswith('-') and not line.startswith('---'):
                self.text_widget.tag_add("deletion", f"{i}.0", f"{i}.end")
        
        self.text_widget.config(state=tk.DISABLED)

    def set_diff_from_texts(self, original_text: str, new_text: str, fromfile: str = 'original', tofile: str = 'new'):
        """Calculates a diff between two texts and displays it."""
        diff_text = "".join(difflib.unified_diff(original_text.splitlines(keepends=True), new_text.splitlines(keepends=True), fromfile=fromfile, tofile=tofile))
        self.set_diff_text(diff_text if diff_text else "No changes proposed.")

class VerticalSpinbox(ttk.Frame):
    """A custom spinbox with vertical buttons for a more compact look."""
    def __init__(self, parent, from_=0.0, to=100.0, increment=1.0, width=5, textvariable=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.from_ = from_
        self.to = to
        self.increment = increment
        self.textvariable = textvariable if textvariable else tk.StringVar()

        # Determine the format string based on the increment
        if isinstance(self.increment, int) or self.increment == 1.0:
            self.format_spec = "{:.0f}"
        elif self.increment < 0.1:
            self.format_spec = "{:.2f}"
        else:
            self.format_spec = "{:.1f}"

        # Entry widget
        self.entry = ttk.Entry(self, textvariable=self.textvariable, width=width, justify='center')
        self.entry.pack(side=tk.LEFT, fill=tk.Y)

        # Frame for buttons
        button_frame = ttk.Frame(self)
        button_frame.pack(side=tk.LEFT, fill=tk.Y)

        # --- Smart Sizing Logic ---
        # Get the default font size to make the buttons proportionally smaller.
        default_font = tkfont.nametofont("TkDefaultFont")
        default_size = default_font.cget("size")
        button_font_size = max(6, default_size - 3) # Make it smaller but not tiny.

        # Create a unique style name to avoid conflicts if this widget is used multiple times.
        style_name = f"{id(self)}.Small.Toolbutton"
        style = ttk.Style()
        style.configure(style_name, font=('Helvetica', button_font_size), padding=(2, 0, 2, 0))

        # Up and Down buttons
        self.up_button = ttk.Button(button_frame, text="⏶", command=self._increment, width=1, style=style_name)
        self.up_button.pack(side=tk.TOP, fill=tk.Y, expand=True, pady=(0,1))
        self.down_button = ttk.Button(button_frame, text="⏷", command=self._decrement, width=1, style=style_name)
        self.down_button.pack(side=tk.TOP, fill=tk.Y, expand=True)

        # Bind mouse wheel for increment/decrement
        for widget in [self.entry, self.up_button, self.down_button]:
            widget.bind("<MouseWheel>", self._on_mouse_wheel) # For Windows and macOS
            widget.bind("<Button-4>", self._on_mouse_wheel)   # For Linux scroll up
            widget.bind("<Button-5>", self._on_mouse_wheel)   # For Linux scroll down

    def _on_mouse_wheel(self, event):
        """Handles mouse wheel scrolling to increment/decrement the value."""
        # Differentiate between platforms for scroll direction
        if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
            self._increment()
        elif event.num == 5 or (hasattr(event, 'delta') and event.delta < 0):
            self._decrement()

    def _increment(self):
        try:
            current_value = float(self.textvariable.get())
            new_value = min(self.to, current_value + self.increment)
            self.textvariable.set(self.format_spec.format(new_value))
        except (ValueError, tk.TclError):
            self.textvariable.set(self.format_spec.format(self.from_))

    def _decrement(self):
        try:
            current_value = float(self.textvariable.get())
            new_value = max(self.from_, current_value - self.increment)
            self.textvariable.set(self.format_spec.format(new_value))
        except (ValueError, tk.TclError):
            self.textvariable.set(self.format_spec.format(self.from_))

class ImagePreviewMixin:
    """A mixin class to provide hover-to-preview functionality for images."""
    def __init__(self, *args, **kwargs):
        # This assumes it's mixed into a tk.Widget class
        super().__init__(*args, **kwargs)
        self.preview_window: Optional[tk.Toplevel] = None
        self.preview_show_id: Optional[str] = None
        self.preview_hide_id: Optional[str] = None
        self.preview_image_ref: Optional[ImageTk.PhotoImage] = None

    def _get_preview_image(self, widget_info: Dict[str, Any]) -> Optional[Image.Image]:
        """
        Abstract method to be implemented by the inheriting class.
        Should return a PIL.Image.Image object for the preview, or None.
        """
        raise NotImplementedError("_get_preview_image must be implemented by the inheriting class.")

    def _cancel_scheduled_hide(self, event=None):
        """Cancels any pending hide operation. Called when mouse enters thumbnail or preview."""
        if self.preview_hide_id:
            self.after_cancel(self.preview_hide_id)
            self.preview_hide_id = None

    def _schedule_preview(self, widget_info: Dict[str, Any]):
        """Schedules the preview window to appear after a delay."""
        self._cancel_scheduled_hide()
        if self.preview_show_id:
            self.after_cancel(self.preview_show_id)
        self.preview_show_id = self.after(750, lambda: self._show_preview(widget_info))

    def _schedule_hide(self, event=None):
        """Schedules the preview to be hidden after a short delay, allowing the cursor to move into it."""
        if self.preview_show_id:
            self.after_cancel(self.preview_show_id)
            self.preview_show_id = None
        if not self.preview_hide_id:
            self.preview_hide_id = self.after(100, self._hide_preview)

    def _hide_preview(self):
        """Performs the actual destruction of the preview window."""
        if self.preview_window:
            self.preview_window.destroy()
            self.preview_window = None
        self.preview_hide_id = None

    def _show_preview(self, widget_info: Dict[str, Any]):
        """Creates and displays the full-size image preview window."""
        self._cancel_scheduled_hide()
        if self.preview_show_id: self.after_cancel(self.preview_show_id)
        if self.preview_window: self.preview_window.destroy()

        pil_image = self._get_preview_image(widget_info)
        if not pil_image: return

        self.preview_window = tk.Toplevel(self)
        self.preview_window.wm_overrideredirect(True)
        self.preview_window.wm_attributes("-topmost", True)

        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        img_copy = pil_image.copy()
        img_copy.thumbnail((screen_width - 100, screen_height - 100), Image.Resampling.LANCZOS)
        self.preview_image_ref = ImageTk.PhotoImage(img_copy)
        
        preview_label = ttk.Label(self.preview_window, image=self.preview_image_ref, borderwidth=2, relief="solid")
        preview_label.pack()
        for widget in [self.preview_window, preview_label]:
            widget.bind("<Enter>", lambda e: self._cancel_scheduled_hide())
            widget.bind("<Leave>", lambda e: self._schedule_hide())

        x = (screen_width // 2) - (img_copy.width // 2)
        y = (screen_height // 2) - (img_copy.height // 2)
        self.preview_window.wm_geometry(f"+{x}+{y}")

    def close_preview_on_destroy(self):
        """Call this in the main window's close/destroy method."""
        if self.preview_show_id: self.after_cancel(self.preview_show_id)
        if self.preview_hide_id: self.after_cancel(self.preview_hide_id)
        if self.preview_window: self.preview_window.destroy()

class AutocompleteCombobox(ttk.Combobox):
    """
    A standard, read-only dropdown combobox.
    The custom autocomplete implementation has been reverted for stability.
    """
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        # Set to readonly to behave like a simple dropdown list, preventing typing.
        self.config(state="readonly")