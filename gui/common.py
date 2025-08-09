"""Common, reusable GUI components for the application."""

import tkinter as tk
from tkinter import ttk
import sys
import re
from typing import Callable

class Tooltip:
    """A simple tooltip for tkinter widgets."""
    def __init__(self, widget, text):
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

        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background="#ffffe0", relief='solid', borderwidth=1,
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

        # Platform-specific binding for right-click
        if sys.platform == "darwin":  # macOS
            self.widget.bind("<Button-2>", self.show_menu)
            self.widget.bind("<Control-Button-1>", self.show_menu)
        else:  # Windows/Linux
            self.widget.bind("<Button-3>", self.show_menu)

    def show_menu(self, event):
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

        self.menu.tk_popup(event.x_root, event.y_root)

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

    def show_menu(self, event):
        super().show_menu(event)
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

class TemplateEditorContextMenu(TextContextMenu):
    """A specialized context menu for the template editor with a wildcard generator."""
    def __init__(self, widget, generate_wildcard_callback: Callable, brainstorm_callback: Callable, create_wildcard_callback: Callable):
        super().__init__(widget)
        self.generate_wildcard_callback = generate_wildcard_callback
        self.brainstorm_callback = brainstorm_callback
        self.create_wildcard_callback = create_wildcard_callback
        self.last_event = None
        self.menu.add_separator()
        self.menu.add_command(label="Generate Missing Wildcard...", command=self._generate_wildcard, state=tk.DISABLED)
        self.menu.add_command(label="Create Wildcard from Selection...", command=self._create_wildcard, state=tk.DISABLED)
        self.menu.add_command(label="Brainstorm with AI...", command=self.brainstorm_callback, state=tk.DISABLED)

    def show_menu(self, event):
        self.last_event = event
        super().show_menu(event) # Call parent to set cut/copy/paste

        index = self.widget.index(f"@{event.x},{event.y}")
        tags = self.widget.tag_names(index)

        if "missing_wildcard" in tags:
            self.menu.entryconfig("Generate Missing Wildcard...", state=tk.NORMAL)
        else:
            self.menu.entryconfig("Generate Missing Wildcard...", state=tk.DISABLED)
        
        try:
            self.widget.selection_get()
            self.menu.entryconfig("Create Wildcard from Selection...", state=tk.NORMAL)
        except tk.TclError:
            self.menu.entryconfig("Create Wildcard from Selection...", state=tk.DISABLED)
        
        if self.widget.get("1.0", "end-1c").strip():
            self.menu.entryconfig("Brainstorm with AI...", state=tk.NORMAL)
        else:
            self.menu.entryconfig("Brainstorm with AI...", state=tk.DISABLED)

    def _generate_wildcard(self):
        if not self.last_event: return
        try:
            index = self.widget.index(f"@{self.last_event.x},{self.last_event.y}")
            word_start = self.widget.index(f"{index} wordstart")
            word_end = self.widget.index(f"{index} wordend")
            clicked_word = self.widget.get(word_start, word_end)
            
            match = re.fullmatch(r'__([a-zA-Z0-9_.-]+)__', clicked_word)
            if match:
                wildcard_name = match.group(1)
                self.generate_wildcard_callback(wildcard_name)
        except Exception as e:
            print(f"Error getting wildcard for generation: {e}")

    def _create_wildcard(self):
        try:
            selected_text = self.widget.selection_get()
            if selected_text:
                self.create_wildcard_callback(selected_text)
        except tk.TclError:
            pass # No selection

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