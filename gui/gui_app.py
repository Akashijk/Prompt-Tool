"""GUI for the Stable Diffusion Prompt Generator."""

import os
import tkinter as tk
import threading
import re
import random
import sys
import queue
from typing import Optional, List, Tuple, Dict, Any
from tkinter import ttk, messagebox, simpledialog
from core.prompt_processor import PromptProcessor
from core.template_engine import PromptSegment
from core.config import config, DEFAULT_SFW_VARIATION_INSTRUCTIONS, DEFAULT_NSFW_VARIATION_INSTRUCTIONS, save_settings, load_settings
from .theme_manager import ThemeManager

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
    def __init__(self, widget, rewrite_callback: callable):
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
    def __init__(self, widget, generate_wildcard_callback: callable, brainstorm_callback: callable):
        super().__init__(widget)
        self.generate_wildcard_callback = generate_wildcard_callback
        self.brainstorm_callback = brainstorm_callback
        self.last_event = None
        self.menu.add_separator()
        self.menu.add_command(label="Generate Missing Wildcard...", command=self._generate_wildcard, state=tk.DISABLED)
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



VARIATION_TOOLTIPS = {
    'cinematic': 'Re-writes the prompt with a focus on dramatic lighting, camera angles, and movie-like composition.',
    'artistic': 'Re-writes the prompt to emphasize painterly qualities, specific art movements, or artistic techniques.',
    'photorealistic': 'Re-writes the prompt to include technical photography details, realistic lighting, and high-quality descriptors.'
}

class HistoryViewerWindow(tk.Toplevel):
    """A window to view and search the prompt generation history."""
    def __init__(self, parent, processor: PromptProcessor):
        super().__init__(parent)
        self.title("Prompt History Viewer")
        self.geometry("1200x800")

        self.processor = processor
        self.parent_app = parent
        self.all_history_data: List[Dict[str, str]] = []
        self.tree: Optional[ttk.Treeview] = None

        self._create_widgets()
        self.load_and_display_history()

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Search Bar ---
        search_frame = ttk.Frame(main_frame)
        search_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._search_history())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Main paned window for table and details
        main_pane = ttk.PanedWindow(main_frame, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        # --- History Table ---
        tree_frame = ttk.Frame(main_pane)
        main_pane.add(tree_frame, weight=3)

        columns = ('original_prompt', 'enhanced_prompt', 'status', 'enhanced_sd_model')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings')

        # --- Context Menu ---
        self.context_menu = tk.Menu(self.tree, tearoff=0)
        self.context_menu.add_command(label="Copy Original Prompt", command=lambda: self._copy_selected_prompt_part('original_prompt'))
        self.context_menu.add_command(label="Copy Enhanced Prompt", command=lambda: self._copy_selected_prompt_part('enhanced_prompt'))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Copy Cinematic Variation", command=lambda: self._copy_selected_prompt_part('cinematic_variation'), state=tk.DISABLED)
        self.context_menu.add_command(label="Copy Artistic Variation", command=lambda: self._copy_selected_prompt_part('artistic_variation'), state=tk.DISABLED)
        self.context_menu.add_command(label="Copy Photorealistic Variation", command=lambda: self._copy_selected_prompt_part('photorealistic_variation'), state=tk.DISABLED)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Load to Main Window", command=self._load_to_main_window)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Delete Entry", command=self._delete_selected_history)

        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        self.tree.bind(right_click_event, self._show_context_menu)

        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        # Define headings
        self.tree.heading('original_prompt', text='Original Prompt')
        self.tree.heading('enhanced_prompt', text='Enhanced Prompt')
        self.tree.heading('status', text='Status')
        self.tree.heading('enhanced_sd_model', text='SD Model')

        # Define column widths
        self.tree.column('original_prompt', width=300, minwidth=200)
        self.tree.column('enhanced_prompt', width=400, minwidth=200)
        self.tree.column('status', width=80, anchor='center', stretch=False)
        self.tree.column('enhanced_sd_model', width=200, minwidth=150)

        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self.tree.pack(side='left', fill='both', expand=True)

        # --- Details View ---
        details_frame = ttk.LabelFrame(main_pane, text="Selected Prompt Details", padding=5)
        main_pane.add(details_frame, weight=2)

        self.details_text = tk.Text(details_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Helvetica", 11))
        details_scrollbar = ttk.Scrollbar(details_frame, orient="vertical", command=self.details_text.yview)
        self.details_text.configure(yscrollcommand=details_scrollbar.set)
        details_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.details_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        TextContextMenu(self.details_text)

    def load_and_display_history(self):
        """Loads data from the CSV and populates the treeview."""
        self.all_history_data = self.processor.get_full_history()
        self._populate_treeview(self.all_history_data)

    def _populate_treeview(self, data: List[Dict[str, str]]):
        """Clears and fills the treeview with the given data."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in data:
            values = (row.get('original_prompt', ''), row.get('enhanced_prompt', ''), row.get('status', ''), row.get('enhanced_sd_model', ''))
            self.tree.insert('', tk.END, values=values)

    def _search_history(self):
        """Filters the treeview based on the search term."""
        search_term = self.search_var.get().lower()
        if not search_term:
            self._populate_treeview(self.all_history_data)
            return
        
        filtered_data = [
            row for row in self.all_history_data
            if search_term in row.get('original_prompt', '').lower() or
               search_term in row.get('enhanced_prompt', '').lower()
        ]
        self._populate_treeview(filtered_data)

    def _on_row_select(self, event=None):
        """Displays the full content of the selected row in the details view."""
        selected_items = self.tree.selection()
        if not selected_items: return
        
        # Get the values from the selected row
        item = self.tree.item(selected_items[0])
        values = item['values']
        original_prompt = values[0]

        # Find the full data dictionary for the selected row
        full_row_data = next((row for row in self.all_history_data if row.get('original_prompt') == original_prompt), None)
        if not full_row_data:
            return

        enhanced_prompt = full_row_data.get('enhanced_prompt', '')

        details_content = f"ORIGINAL PROMPT:\n{'-'*20}\n{original_prompt}\n\n"
        details_content += f"ENHANCED PROMPT:\n{'-'*20}\n{enhanced_prompt}"

        # Check for and add variations
        variations_content = ""
        cinematic_prompt = full_row_data.get('cinematic_variation', '')
        if cinematic_prompt:
            cinematic_model = full_row_data.get('cinematic_sd_model', '')
            variations_content += f"\n\nCINEMATIC VARIATION:\n{'-'*20}\n{cinematic_prompt}\n(Model: {cinematic_model})"

        artistic_prompt = full_row_data.get('artistic_variation', '')
        if artistic_prompt:
            artistic_model = full_row_data.get('artistic_sd_model', '')
            variations_content += f"\n\nARTISTIC VARIATION:\n{'-'*20}\n{artistic_prompt}\n(Model: {artistic_model})"

        photorealistic_prompt = full_row_data.get('photorealistic_variation', '')
        if photorealistic_prompt:
            photo_model = full_row_data.get('photorealistic_sd_model', '')
            variations_content += f"\n\nPHOTOREALISTIC VARIATION:\n{'-'*20}\n{photorealistic_prompt}\n(Model: {photo_model})"

        if variations_content:
            details_content += "\n" + variations_content

        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert("1.0", details_content)
        self.details_text.config(state=tk.DISABLED)

    def _delete_selected_history(self):
        """Deletes the selected row from the history file and the view."""
        selected_items = self.tree.selection()
        if not selected_items:
            return

        item_id = selected_items[0]
        values = self.tree.item(item_id, 'values')
        original_prompt_to_delete = values[0]

        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to permanently delete this history entry?\n\nOriginal: \"{original_prompt_to_delete[:80]}...\"", parent=self):
            return

        try:
            success = self.processor.delete_history_entry(original_prompt_to_delete)
            if success:
                # Remove from the Treeview and the internal data cache
                self.tree.delete(item_id)
                self.all_history_data = [row for row in self.all_history_data if row.get('original_prompt') != original_prompt_to_delete]
                messagebox.showinfo("Success", "History entry deleted.", parent=self)
            else:
                messagebox.showerror("Error", "Could not delete the history entry. It may have already been deleted.", parent=self)
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred while deleting the entry:\n{e}", parent=self)

    def _show_context_menu(self, event):
        """Shows the right-click context menu for a treeview row."""
        row_id = self.tree.identify_row(event.y)
        if row_id:
            # Select the row that was right-clicked
            self.tree.selection_set(row_id)
            self._on_row_select() # Update the details pane

            # Find full data to configure menu
            item_values = self.tree.item(row_id, 'values')
            original_prompt = item_values[0]
            full_row_data = next((row for row in self.all_history_data if row.get('original_prompt') == original_prompt), None)

            if full_row_data:
                # Enable/disable variation copy options
                has_cinematic = bool(full_row_data.get('cinematic_variation'))
                has_artistic = bool(full_row_data.get('artistic_variation'))
                has_photo = bool(full_row_data.get('photorealistic_variation'))
                
                self.context_menu.entryconfig("Copy Cinematic Variation", state=tk.NORMAL if has_cinematic else tk.DISABLED)
                self.context_menu.entryconfig("Copy Artistic Variation", state=tk.NORMAL if has_artistic else tk.DISABLED)
                self.context_menu.entryconfig("Copy Photorealistic Variation", state=tk.NORMAL if has_photo else tk.DISABLED)

            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _copy_selected_prompt_part(self, part_key: str):
        """Copies a specific part of the selected prompt by its column key."""
        selected_items = self.tree.selection()
        if not selected_items:
            return

        # Find the full data dictionary for the selected row
        item_values = self.tree.item(selected_items[0], 'values')
        original_prompt = item_values[0]
        full_row_data = next((row for row in self.all_history_data if row.get('original_prompt') == original_prompt), None)

        if full_row_data:
            content_to_copy = full_row_data.get(part_key, '')
            if content_to_copy:
                self.clipboard_clear()
                self.clipboard_append(content_to_copy)

    def _load_to_main_window(self):
        """Sends the selected original prompt back to the main app for re-enhancement."""
        selected_items = self.tree.selection()
        if not selected_items:
            return

        item_values = self.tree.item(selected_items[0], 'values')
        original_prompt = item_values[0]
        self.parent_app.load_prompt_from_history(original_prompt)
        self.destroy()

class ReviewAndSaveWindow(tk.Toplevel):
    """A window to review, edit, and save AI-generated content."""
    def __init__(self, parent, processor: PromptProcessor, content_type: str, generated_content: str, update_callback: callable, filename: Optional[str] = None, regenerate_callback: Optional[callable] = None):
        super().__init__(parent)
        self.processor = processor
        self.content_type = content_type # "wildcard" or "template"
        self.update_callback = update_callback
        self.prefilled_filename = filename
        self.regenerate_callback = regenerate_callback

        title = f"Review: {self.prefilled_filename}" if self.prefilled_filename else f"Review New {self.content_type.capitalize()}"
        self.title(title)
        self.geometry("600x700")

        self.text_widget = tk.Text(self, wrap=tk.WORD, font=("Courier", 11), undo=True)
        self.text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10,0))
        self.text_widget.insert("1.0", generated_content)
        TextContextMenu(self.text_widget)

        button_frame = ttk.Frame(self, padding=10)
        button_frame.pack(fill=tk.X)
        self.save_button = ttk.Button(button_frame, text="Save", command=self._save)
        self.save_button.pack(side=tk.LEFT, expand=True, fill=tk.X)
        if self.regenerate_callback:
            self.regenerate_button = ttk.Button(button_frame, text="Regenerate", command=self._regenerate)
            self.regenerate_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5,0))

    def update_content(self, new_content: str):
        """Updates the text widget with new content and re-enables buttons."""
        self.text_widget.delete("1.0", tk.END)
        self.text_widget.insert("1.0", new_content)
        self.title(f"Review: {self.prefilled_filename}" if self.prefilled_filename else f"Review New {self.content_type.capitalize()}")
        self.save_button.config(state=tk.NORMAL)
        if hasattr(self, 'regenerate_button'):
            self.regenerate_button.config(state=tk.NORMAL)

    def _regenerate(self):
        """Calls the provided callback to regenerate content and updates UI to a loading state."""
        if self.regenerate_callback:
            # Disable buttons and show loading state
            self.save_button.config(state=tk.DISABLED)
            self.regenerate_button.config(state=tk.DISABLED)
            title = f"Regenerating: {self.prefilled_filename}" if self.prefilled_filename else f"Regenerating New {self.content_type.capitalize()}"
            self.title(title)
            # Pass self to the callback so it can update this window instance
            self.regenerate_callback(self)

    def _save(self):
        filename = simpledialog.askstring(
            f"Save {self.content_type.capitalize()}",
            "Enter filename:",
            parent=self,
            initialvalue=self.prefilled_filename
        )
        if not filename: return
        if not filename.endswith('.txt'): filename += '.txt'

        content = self.text_widget.get("1.0", "end-1c")
        try:
            if self.content_type == "wildcard":
                is_nsfw_only = False
                if config.workflow == 'nsfw':
                    is_nsfw_only = messagebox.askyesno(
                        "Wildcard Scope",
                        "Save this as an NSFW-only wildcard?\n\n"
                        "(Choosing 'No' will save it to the shared folder, making it available in both SFW and NSFW modes.)",
                        parent=self
                    )
                # Save the new wildcard, respecting the user's choice of scope
                self.processor.save_wildcard_content(filename, content, is_nsfw_only=is_nsfw_only)
            elif self.content_type == "template":
                self.processor.save_template_content(filename, content)
            
            self.update_callback(self.content_type) # Refresh lists in the main UI
            self.destroy()
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save file:\n{e}", parent=self)

class BrainstormingWindow(tk.Toplevel):
    """An interactive window for brainstorming with an AI model."""
    def __init__(self, parent, processor: PromptProcessor, models: List[str], default_model: str, model_change_callback: callable):
        super().__init__(parent)
        self.title("AI Brainstorming Session")
        self.geometry("800x600")

        self.processor = processor
        self.models = models
        self.chat_queue = queue.Queue()
        self.model_change_callback = model_change_callback
        self.active_brainstorm_model: Optional[str] = None

        # --- Widgets ---
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill=tk.X)
        ttk.Label(top_frame, text="Model:").pack(side=tk.LEFT)
        self.model_var = tk.StringVar(value=default_model)
        model_menu = ttk.OptionMenu(top_frame, self.model_var, default_model, *models, style="Toolbutton")
        self.model_var.trace_add("write", self._on_model_var_change)
        model_menu.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(top_frame, text="Generate Wildcard File...", command=self._generate_wildcard_file).pack(side=tk.LEFT)
        ttk.Button(top_frame, text="Generate Template File...", command=self._generate_template_file).pack(side=tk.LEFT, padx=5)

        main_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # --- Conversation History ---
        history_frame = ttk.LabelFrame(main_pane, text="Conversation History", padding=5)
        main_pane.add(history_frame, weight=4)

        history_scroll_frame = ttk.Frame(history_frame)
        history_scroll_frame.pack(fill=tk.BOTH, expand=True)
        history_scrollbar = ttk.Scrollbar(history_scroll_frame, orient=tk.VERTICAL)
        self.history_text = tk.Text(history_scroll_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Helvetica", 11), yscrollcommand=history_scrollbar.set)
        history_scrollbar.config(command=self.history_text.yview)
        history_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.history_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        BrainstormingContextMenu(self.history_text, self._rewrite_selection)

        self.history_text.tag_configure("user", foreground="blue", font=("Helvetica", 11, "bold"))
        self.history_text.tag_configure("ai", foreground="#006400")
        self.history_text.tag_configure("error", foreground="red", font=("Helvetica", 11, "bold"))
        self.history_text.tag_configure("thinking", foreground="gray", font=("Helvetica", 11, "italic"))
        self.history_text.tag_configure("new_wildcard_link", foreground="blue", underline=True)
        self.history_text.tag_bind("new_wildcard_link", "<Enter>", lambda e: self.history_text.config(cursor="hand2"))
        self.history_text.tag_bind("new_wildcard_link", "<Leave>", lambda e: self.history_text.config(cursor=""))

        # --- Input Area ---
        input_area_frame = ttk.LabelFrame(main_pane, text="Your Message (Enter to send, Shift+Enter for new line)", padding=5)
        main_pane.add(input_area_frame, weight=1)

        self.input_text = tk.Text(input_area_frame, height=4, wrap=tk.WORD, font=("Helvetica", 11))
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.input_text.bind("<Return>", self._on_send_message_event)
        TextContextMenu(self.input_text)
        
        self.send_button = ttk.Button(input_area_frame, text="Send", command=self._send_message)
        self.send_button.pack(side=tk.LEFT, padx=(10, 0), fill=tk.Y)
        
        self._add_message("AI", "Hello! How can I help you brainstorm today? You can ask me to improve a list of wildcards, create a new template, or anything else you can think of.", "ai")

        # Register initial model usage
        self.active_brainstorm_model = default_model
        self.model_change_callback(None, self.active_brainstorm_model)

    def _handle_wildcard_link_click(self, wildcard_name: str, tag_name: str):
        """Handles a click on a new wildcard link, disabling it and starting generation."""
        # Disable the link to prevent multiple clicks
        self.history_text.tag_config(tag_name, foreground="gray", underline=False)
        self.history_text.tag_unbind(tag_name, "<Button-1>")
        
        self.generate_wildcard_with_topic(wildcard_name)

    def _on_send_message_event(self, event):
        # If shift is pressed, allow default newline behavior. Otherwise, send message.
        if event.state & 1:
            return
        else:
            self._send_message()
            return "break"

    def _send_message(self):
        user_prompt = self.input_text.get("1.0", "end-1c").strip()
        if not user_prompt: return

        model = self.model_var.get()

        self._add_message("User", user_prompt, "user")
        self.input_text.delete("1.0", tk.END)
        self.send_button.config(state=tk.DISABLED)
        self._add_message("AI", "Thinking...", "thinking")

        thread = threading.Thread(target=self._get_ai_response, args=(model, user_prompt), daemon=True)
        thread.start()
        self.after(100, self._check_chat_queue)

    def _get_ai_response(self, model, prompt):
        try:
            response = self.processor.chat_with_model(model, prompt)
            self.chat_queue.put({'response': response, 'tag': 'ai'})
        except Exception as e:
            self.chat_queue.put({'response': f"An error occurred: {e}", 'tag': 'error'})

    def _check_chat_queue(self):
        try:
            result = self.chat_queue.get_nowait()
            self.history_text.config(state=tk.NORMAL)
            self.history_text.delete("end-2l", "end-1c")
            self.history_text.config(state=tk.DISABLED)

            if result.get('tag') == 'ai_generated':
                content_type = result.get('content_type')
                response = result.get('response', '')
                metadata = result.get('metadata')
                if content_type == 'template':
                    template, new_wildcards = self._parse_template_generation_response(response)
                    self._handle_generated_template(template, new_wildcards, metadata)
                elif content_type == 'wildcard':
                    self._add_message("AI", f"Generated a new wildcard. See the new window to review and save.", "ai")
                    self._handle_generated_content(response, 'wildcard', metadata)
                elif content_type == 'rewrite':
                    if metadata:
                        self._handle_rewritten_text(response, metadata['start_index'], metadata['end_index'])
            else:
                # Handle regular chat or errors
                self._add_message("AI", result['response'], result['tag'])
            
            self.send_button.config(state=tk.NORMAL)
        except queue.Empty:
            self.after(100, self._check_chat_queue)

    def _add_message(self, sender, message, tag):
        self.history_text.config(state=tk.NORMAL)
        if self.history_text.get("1.0", "end-1c"):
            self.history_text.insert(tk.END, "\n\n")
        
        self.history_text.insert(tk.END, f"{sender}:\n", (tag,))
        self.history_text.insert(tk.END, message)
        self.history_text.see(tk.END)
        self.history_text.config(state=tk.DISABLED)

    def load_content_for_brainstorming(self, content_type: str, filename: str, content: str):
        """Loads existing content into the chat window for refinement."""
        message = (
            f"Loaded {content_type} '{filename}' for brainstorming.\n\n"
            f"You can now ask me to refine it. For example: 'make this list more diverse', 'rewrite this template to be more cinematic', or 'add more technical terms'.\n\n"
            f"CONTENT:\n"
            f"----------------\n"
            f"{content}"
        )
        self._add_message("System", message, "thinking")

    def _generate_wildcard_file(self):
        """Guides the user to generate a new wildcard file."""
        topic = simpledialog.askstring("Generate Wildcard", "What is the topic for the new wildcard file?\n(e.g., 'sci-fi helmet designs', 'fantasy potion names')", parent=self)
        self.generate_wildcard_with_topic(topic)

    def generate_wildcard_with_topic(self, topic: str, existing_window: Optional[ReviewAndSaveWindow] = None):
        """Starts the generation process for a wildcard with a given topic."""
        if not topic: return
        
        # Add workflow context to the prompt
        workflow_context = ""
        if config.workflow == 'nsfw':
            workflow_context = (
                "The user is currently in NSFW (Not Safe For Work) mode. "
                "The generated items should be explicit, adult-oriented, and suitable for generating pornographic imagery. "
                "Do not censor the content."
            )
        else:
            workflow_context = "The user is currently in SFW (Safe For Work) mode. The items should be general-purpose and not contain any explicit content."

        prompt = (
            f"You are an expert content creator specializing in generating diverse and thematic lists for Stable Diffusion wildcards.\n\n"
            f"The user needs a list for a wildcard file named '{topic}'. Your task is to generate a list of 20-30 items that are **strictly and creatively** related to this topic.\n\n"
            f"**CONTEXT:** {workflow_context}\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n"
            f"1.  **Stay on Theme:** Every single item must be a specific example of '{topic}'. Do not stray from the topic.\n"
            f"2.  **Be Creative and Diverse:** The items should be varied and interesting, not just simple variations of the same idea.\n"
            f"3.  **Use English:** The entire list must be in English.\n"
            f"4.  **Formatting:**\n"
            f"    - Each item must be on a new line.\n"
            f"    - Use normal spaces for multi-word items (e.g., 'ancient stone temple', NOT 'ancient_stone_temple').\n"
            f"    - Do NOT add numbers, bullets, or any other formatting.\n"
            f"    - Do NOT repeat the topic '{topic}' as a prefix for each item.\n\n"
            f"**EXAMPLE for topic 'fantasy_potions':**\n"
            f"Elixir of Sun's Vigor\n"
            f"Draught of Shadowy Concealment\n"
            f"Philter of Gilded Luck\n\n"
            f"Now, generate the list for the topic: '{topic}'."
        )
        self._add_message("AI", f"Generating wildcard ideas for '{topic}'...", "thinking")
        # The 'topic' is the base name for the wildcard file.
        self._run_generation_task(prompt, "wildcard", metadata={'filename': topic, 'topic': topic, 'window': existing_window})

    def _generate_template_file(self):
        """Guides the user to generate a new template file."""
        concept = simpledialog.askstring("Generate Template", "What is the high-level concept for the new template?\n(e.g., 'a character portrait in a dark forest', 'a futuristic city street scene')", parent=self)
        self.generate_template_with_concept(concept)

    def generate_template_with_concept(self, concept: str, existing_window: Optional[ReviewAndSaveWindow] = None):
        """Starts the generation process for a template with a given concept."""
        if not concept: return

        wildcard_names = self.processor.get_wildcard_names()
        # Suggest a smaller, random sample of wildcards to avoid overwhelming the AI
        sample_size = min(15, len(wildcard_names))
        wildcard_sample_str = ", ".join(random.sample(wildcard_names, sample_size)) if wildcard_names else "none"

        # Add workflow context to the prompt
        workflow_context = ""
        if config.workflow == 'nsfw':
            workflow_context = (
                "The user is currently in NSFW (Not Safe For Work) mode. "
                "The template should be designed for generating explicit, adult-oriented, and pornographic imagery. "
                "It should be descriptive and graphic where appropriate."
            )
        else:
            workflow_context = "The user is currently in SFW (Safe For Work) mode. The template should be suitable for general-purpose, non-explicit imagery."

        prompt = (
            f"You are an AI assistant that creates templates for a Stable Diffusion prompt generator. "
            f"The user wants a template for the concept: '{concept}'.\n\n"
            f"**CONTEXT:** {workflow_context}\n\n"
            f"Your task is to write a descriptive prompt template. You can use existing wildcards from the list below, but you are also **strongly encouraged to invent new, relevant wildcard names** to make the template more versatile.\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n"
            f"1.  All wildcard names, existing or new, MUST be in the exact format `__wildcard_name__`.\n"
            f"2.  The final template should be a single paragraph of comma-separated keywords and phrases.\n"
            f"3.  You MUST return your response in the following format, with nothing before or after:\n"
            f"TEMPLATE: [The full template text you generated]\n"
            f"NEW_WILDCARDS: [A comma-separated list of any new wildcard names you invented. If you invented none, write 'none'.]\n\n"
            f"**EXAMPLE RESPONSE:**\n"
            f"TEMPLATE: a portrait of a __character_class__, __hair_style__ hair, wearing __fantasy_armor__, holding a __weapon_type__, in a __fantasy_forest__, __lighting_style__\n"
            f"NEW_WILDCARDS: fantasy_armor, fantasy_forest\n\n"
            f"Here is a sample of EXISTING wildcards you can use: {wildcard_sample_str}\n\n"
            f"Now, generate the template for the concept: '{concept}'."
        )
        self._add_message("AI", f"Generating a template for '{concept}'...", "thinking")
        self._run_generation_task(prompt, "template", metadata={'concept': concept, 'window': existing_window})

    def _run_generation_task(self, prompt: str, content_type: str, metadata: Optional[Dict] = None):
        """Runs a generation task in a background thread."""
        model = self.model_var.get()
        self.send_button.config(state=tk.DISABLED)

        def task():
            try:
                response = self.processor.chat_with_model(model, prompt)
                self.chat_queue.put({'response': response, 'tag': 'ai_generated', 'content_type': content_type, 'metadata': metadata})
            except Exception as e:
                self.chat_queue.put({'response': f"An error occurred: {e}", 'tag': 'error'})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after(100, self._check_chat_queue)

    def _rewrite_selection(self):
        """Handles the AI-powered rewriting of selected text in the history."""
        try:
            start_index = self.history_text.index("sel.first")
            end_index = self.history_text.index("sel.last")
            selected_text = self.history_text.get(start_index, end_index)
        except tk.TclError:
            return # No selection

        instructions = simpledialog.askstring(
            "Rewrite with AI",
            "How should I rewrite the selected text?\n(e.g., 'make it more poetic', 'add more technical terms')",
            parent=self
        )
        if not instructions: return

        prompt = (
            f"You are an AI assistant. Your task is to rewrite the following text based on the user's instruction.\n\n"
            f"INSTRUCTION: {instructions}\n\n"
            f"ORIGINAL TEXT:\n---\n{selected_text}\n---\n\n"
            f"Return only the rewritten text, with no extra commentary."
        )
        
        # Replace selected text with a loading message
        self.history_text.config(state=tk.NORMAL)
        self.history_text.delete(start_index, end_index)
        placeholder = f"[Rewriting to '{instructions}'...]"
        self.history_text.insert(start_index, placeholder, ("thinking",))
        new_end_index = self.history_text.index(f"{start_index} + {len(placeholder)}c")
        self.history_text.config(state=tk.DISABLED)
        
        metadata = {'start_index': start_index, 'end_index': new_end_index}
        self._run_generation_task(prompt, "rewrite", metadata=metadata)

    def _parse_template_generation_response(self, response: str) -> Tuple[str, List[str]]:
        """Parses the AI response for template and new wildcards."""
        template_content = ""
        new_wildcards = []
        
        # Use re.IGNORECASE to handle variations in casing like 'TEMPLATE:' vs 'Template:'
        template_match = re.search(r"TEMPLATE:\s*(.*)", response, re.DOTALL | re.IGNORECASE)
        if template_match:
            # Further split by NEW_WILDCARDS to ensure we only get the template part
            template_content = template_match.group(1).split("NEW_WILDCARDS:")[0].strip()

        wildcards_match = re.search(r"NEW_WILDCARDS:\s*(.*)", response, re.DOTALL | re.IGNORECASE)
        if wildcards_match:
            wildcards_str = wildcards_match.group(1).strip()
            if wildcards_str.lower() != 'none':
                new_wildcards = [w.strip() for w in wildcards_str.split(',') if w.strip()]

        # If parsing fails (e.g., AI didn't follow format), fall back to treating the whole response as the template
        if not template_content:
            template_content = response
            
        return template_content, new_wildcards

    def _handle_generated_template(self, template: str, new_wildcards: List[str], metadata: Optional[Dict] = None):
        """Handles the display of a newly generated template and its new wildcards."""
        # Get the ground truth of all currently loaded wildcards.
        existing_wildcards = set(self.processor.get_wildcard_names())
        
        # Find all wildcards used in the template to be safe
        used_wildcards = set(re.findall(r'__([a-zA-Z0-9_.-]+)__', template))
        
        # Combine the AI's list with the parsed list, and then find what's genuinely new.
        all_potential_new = set(new_wildcards) | used_wildcards
        genuinely_new_wildcards = sorted(list(all_potential_new - existing_wildcards))

        self.history_text.config(state=tk.NORMAL)
        
        # Add the main message and the generated template
        self.history_text.insert(tk.END, "AI:\n", ("ai",))
        self.history_text.insert(tk.END, "Generated a new template. See below to review and save. ")
        
        if genuinely_new_wildcards:
            self.history_text.insert(tk.END, "Click any new wildcard links to generate content for them.\n\n")
            self.history_text.insert(tk.END, "New Wildcards to Generate:\n")
            for i, wc in enumerate(genuinely_new_wildcards):
                tag_name = f"new_wc_{wc}_{i}" # Unique tag
                self.history_text.insert(tk.END, wc, ("new_wildcard_link", tag_name))
                # Use a default argument in lambda to capture the current value of wc
                self.history_text.tag_bind(tag_name, "<Button-1>", lambda e, w=wc, t=tag_name: self._handle_wildcard_link_click(w, t))
                if i < len(genuinely_new_wildcards) - 1:
                    self.history_text.insert(tk.END, ", ")
            self.history_text.insert(tk.END, "\n\n")

        self.history_text.insert(tk.END, "Template:\n")
        self.history_text.insert(tk.END, template)
        
        self.history_text.see(tk.END)
        self.history_text.config(state=tk.DISABLED)

        # Open the review window for the template itself
        self._handle_generated_content(template, 'template', metadata)

    def _handle_rewritten_text(self, rewritten_text: str, start_index: str, end_index: str):
        """Replaces the selected text with the AI's rewritten version."""
        self.history_text.config(state=tk.NORMAL)
        self.history_text.delete(start_index, end_index)
        self.history_text.insert(start_index, rewritten_text)
        self.history_text.config(state=tk.DISABLED)

    def _handle_generated_content(self, content: str, content_type: str, metadata: Optional[Dict] = None):
        """Opens the review window for newly generated content."""
        existing_window = metadata.get('window') if metadata else None

        if existing_window and existing_window.winfo_exists():
            existing_window.update_content(content)
            existing_window.lift()
        else:
            filename = metadata.get('filename') if metadata else None
            regenerate_callback = None
            if metadata:
                if content_type == 'wildcard' and 'topic' in metadata:
                    regenerate_callback = lambda window: self.generate_wildcard_with_topic(metadata['topic'], window)
                elif content_type == 'template' and 'concept' in metadata:
                    regenerate_callback = lambda window: self.generate_template_with_concept(metadata['concept'], window)

            main_app_update_callback = self.master._handle_ai_content_update
            ReviewAndSaveWindow(self, self.processor, content_type, content, main_app_update_callback, filename=filename, regenerate_callback=regenerate_callback)

    def _on_model_var_change(self, *args):
        """Handles when the user selects a new model in the dropdown."""
        new_model = self.model_var.get()
        old_model = self.active_brainstorm_model
        if new_model and new_model != old_model:
            self.model_change_callback(old_model, new_model)
            self.active_brainstorm_model = new_model

class SystemPromptEditorWindow(tk.Toplevel):
    """A window for editing system-level prompts (enhancement, variations)."""
    def __init__(self, parent, processor: PromptProcessor):
        super().__init__(parent)
        self.title("System Prompt Editor")
        self.geometry("900x700")

        self.processor = processor
        self.selected_file: Optional[str] = None

        self._create_widgets()
        self._populate_file_list()

    def _create_widgets(self):
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- File List ---
        list_frame = ttk.LabelFrame(main_pane, text="System Prompts", padding=5)
        main_pane.add(list_frame, weight=1)

        self.file_listbox = tk.Listbox(list_frame, font=("Helvetica", 10))
        self.file_listbox.pack(fill=tk.BOTH, expand=True)
        self.file_listbox.bind("<<ListboxSelect>>", self._on_file_select)

        # --- Editor ---
        editor_frame = ttk.LabelFrame(main_pane, text="Edit Prompt", padding=5)
        main_pane.add(editor_frame, weight=3)

        self.editor_text = tk.Text(editor_frame, wrap=tk.WORD, font=("Courier", 11), undo=True, state=tk.DISABLED)
        TextContextMenu(self.editor_text)
        self.editor_text.pack(fill=tk.BOTH, expand=True)

        button_frame = ttk.Frame(editor_frame)
        button_frame.pack(fill=tk.X, pady=5)
        self.save_button = ttk.Button(button_frame, text="Save Changes", command=self._save_file, state=tk.DISABLED)
        self.save_button.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.reset_button = ttk.Button(button_frame, text="Reset to Default", command=self._reset_to_default, state=tk.DISABLED)
        self.reset_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5,0))

    def _populate_file_list(self):
        self.file_listbox.delete(0, tk.END)
        for filename in self.processor.get_system_prompt_files():
            self.file_listbox.insert(tk.END, filename)

    def _on_file_select(self, event=None):
        selected_indices = self.file_listbox.curselection()
        if not selected_indices: return

        self.selected_file = self.file_listbox.get(selected_indices[0])
        try:
            content = self.processor.load_system_prompt_content(self.selected_file)
            self.editor_text.config(state=tk.NORMAL)
            self.editor_text.delete("1.0", tk.END)
            self.editor_text.insert("1.0", content)
            self.save_button.config(state=tk.NORMAL)
            self.reset_button.config(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load system prompt:\n{e}", parent=self)

    def _save_file(self):
        if not self.selected_file: return
        content = self.editor_text.get("1.0", "end-1c")
        try:
            self.processor.save_system_prompt_content(self.selected_file, content)
            messagebox.showinfo("Success", f"Saved '{self.selected_file}' successfully.", parent=self)
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save system prompt:\n{e}", parent=self)

    def _reset_to_default(self):
        if not self.selected_file: return
        if not messagebox.askyesno("Confirm Reset", f"Are you sure you want to reset '{self.selected_file}' to its default content?", parent=self):
            return
        
        default_content = self.processor.get_default_system_prompt(self.selected_file)
        self.editor_text.delete("1.0", tk.END)
        self.editor_text.insert("1.0", default_content)
        self._save_file()

class WildcardManagerWindow(tk.Toplevel):
    """A pop-up window to manage wildcard files."""
    def __init__(self, parent, processor: PromptProcessor, update_callback: callable, initial_file: Optional[str] = None):
        super().__init__(parent)
        self.title("Wildcard Manager")
        self.geometry("700x500")
        
        self.processor = processor
        self.update_callback = update_callback
        self.selected_wildcard_file: Optional[str] = None

        self._create_widgets()
        self._populate_wildcard_list()

        if initial_file:
            self.select_and_load_file(initial_file)

    def _create_widgets(self):
        h_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        h_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        list_frame = ttk.LabelFrame(h_pane, text="Wildcard Files", padding=5)

        list_scroll_frame = ttk.Frame(list_frame)
        list_scroll_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_scroll_frame, orient=tk.VERTICAL)
        self.wildcard_listbox = tk.Listbox(list_scroll_frame, font=("Helvetica", 10), yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.wildcard_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.wildcard_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)

        ttk.Button(list_frame, text="New Wildcard File", command=self._create_new_wildcard_file).pack(pady=(5, 0), fill=tk.X)
        h_pane.add(list_frame, weight=1)

        self.editor_frame = ttk.LabelFrame(h_pane, text="No file selected", padding=5)
        self.editor_text = tk.Text(self.editor_frame, wrap=tk.WORD, font=("Courier", 11), undo=True, state=tk.DISABLED)
        TextContextMenu(self.editor_text)
        self.editor_text.pack(fill=tk.BOTH, expand=True)
        
        button_frame = ttk.Frame(self.editor_frame)
        button_frame.pack(fill=tk.X, pady=5)
        self.save_button = ttk.Button(button_frame, text="Save Changes", command=self._save_wildcard_file, state=tk.DISABLED)
        self.save_button.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.archive_button = ttk.Button(button_frame, text="Archive", command=self._archive_selected_wildcard, state=tk.DISABLED)
        self.archive_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))
        self.brainstorm_button = ttk.Button(button_frame, text="Brainstorm with AI", command=self._brainstorm_with_ai, state=tk.DISABLED)
        self.brainstorm_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5,0))
        h_pane.add(self.editor_frame, weight=3)

    def _populate_wildcard_list(self):
        """Populates the list of wildcard files."""
        self.wildcard_listbox.delete(0, tk.END)
        wildcard_files = self.processor.get_wildcard_files()
        for f in wildcard_files:
            self.wildcard_listbox.insert(tk.END, f)

    def _on_wildcard_file_select(self, event=None):
        selected_indices = self.wildcard_listbox.curselection()
        if not selected_indices: return
        self.selected_wildcard_file = self.wildcard_listbox.get(selected_indices[0])
        self.editor_frame.config(text=f"Editing: {self.selected_wildcard_file}")
        try:
            # Load and sort the content before displaying
            content = self.processor.load_wildcard_content(self.selected_wildcard_file)
            lines = [line for line in content.split('\n') if line.strip()]
            sorted_content = "\n".join(sorted(lines, key=str.lower))
            self.editor_text.config(state=tk.NORMAL)
            self.editor_text.delete("1.0", tk.END)
            self.editor_text.insert("1.0", sorted_content)
            self.save_button.config(state=tk.NORMAL)
            self.archive_button.config(state=tk.NORMAL)
            self.brainstorm_button.config(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load wildcard file:\n{e}", parent=self)

    def _save_wildcard_file(self):
        if not self.selected_wildcard_file: return

        is_new_file = self.selected_wildcard_file not in self.wildcard_listbox.get(0, tk.END)
        content = self.editor_text.get("1.0", "end-1c")

        # Sort the content before saving to maintain consistency
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        sorted_content = "\n".join(sorted(lines, key=str.lower))

        try:
            # When saving an existing file, we don't need to specify the scope.
            # The processor will find its original location and save it there.
            self.processor.save_wildcard_content(self.selected_wildcard_file, sorted_content)
            messagebox.showinfo("Success", f"Successfully saved and sorted {self.selected_wildcard_file}", parent=self)

            # After saving, reload the sorted content into the editor to reflect the change
            self.editor_text.delete("1.0", tk.END)
            self.editor_text.insert("1.0", sorted_content)

            if is_new_file:
                self._populate_wildcard_list()
                # Reselect the newly created file
                if self.selected_wildcard_file in self.wildcard_listbox.get(0, tk.END):
                    idx = self.wildcard_listbox.get(0, tk.END).index(self.selected_wildcard_file)
                    self.wildcard_listbox.selection_clear(0, tk.END)
                    self.wildcard_listbox.selection_set(idx)
                    self.wildcard_listbox.see(idx)

            self.update_callback(modified_file=self.selected_wildcard_file)
        except Exception as e:
            messagebox.showerror("Error", f"Could not save wildcard file:\n{e}", parent=self)

    def _create_new_wildcard_file(self):
        filename = simpledialog.askstring("New Wildcard File", "Enter new wildcard filename:", parent=self)
        if not filename: return
        if not filename.endswith('.txt'): filename += '.txt'
        try:
            is_nsfw_only = False
            if config.workflow == 'nsfw':
                is_nsfw_only = messagebox.askyesno(
                    "Wildcard Scope",
                    "Save this as an NSFW-only wildcard?\n\n"
                    "(Choosing 'No' will save it to the shared folder, making it available in both SFW and NSFW modes.)",
                    parent=self
                )

            # Create an empty file by saving empty content, respecting the user's choice
            self.processor.save_wildcard_content(filename, "", is_nsfw_only=is_nsfw_only)
            self._populate_wildcard_list()
            self.update_callback()
            if filename in self.wildcard_listbox.get(0, tk.END):
                idx = self.wildcard_listbox.get(0, tk.END).index(filename)
                self.wildcard_listbox.selection_clear(0, tk.END)
                self.wildcard_listbox.selection_set(idx)
                self.wildcard_listbox.see(idx)
                self._on_wildcard_file_select(None)
        except Exception as e:
            messagebox.showerror("Error", f"Could not create wildcard file:\n{e}", parent=self)

    def _archive_selected_wildcard(self):
        """Moves the selected wildcard file to an archive folder."""
        if not self.selected_wildcard_file: return

        if not messagebox.askyesno("Confirm Archive", f"Are you sure you want to archive '{self.selected_wildcard_file}'?\n\nThis will move the file to a subfolder named 'archive'.", parent=self):
            return

        try:
            self.processor.archive_wildcard(self.selected_wildcard_file)
            self.editor_text.delete("1.0", tk.END)
            self.editor_text.config(state=tk.DISABLED)
            self.save_button.config(state=tk.DISABLED)
            self.archive_button.config(state=tk.DISABLED)
            self._populate_wildcard_list()
            self.update_callback()
        except Exception as e:
            messagebox.showerror("Archive Error", f"Could not archive file:\n{e}", parent=self)

    def _brainstorm_with_ai(self):
        """Sends the current wildcard content to the brainstorming window."""
        if not self.selected_wildcard_file: return
        content = self.editor_text.get("1.0", "end-1c")
        self.master._brainstorm_with_content("wildcard", self.selected_wildcard_file, content)

    def select_and_load_file(self, filename: str):
        """Selects a file in the listbox or prepares the editor for a new file."""
        all_files = self.wildcard_listbox.get(0, tk.END)
        if filename in all_files:
            idx = all_files.index(filename)
            self.wildcard_listbox.selection_clear(0, tk.END)
            self.wildcard_listbox.selection_set(idx)
            self.wildcard_listbox.activate(idx)
            self.wildcard_listbox.see(idx)
            self._on_wildcard_file_select()
        else: # Prepare for a new file
            self.wildcard_listbox.selection_clear(0, tk.END)
            self.selected_wildcard_file = filename
            self.editor_frame.config(text=f"New File: {self.selected_wildcard_file}")
            self.editor_text.config(state=tk.NORMAL)
            self.editor_text.delete("1.0", tk.END)
            self.save_button.config(state=tk.NORMAL)
            self.archive_button.config(state=tk.DISABLED)
            self.brainstorm_button.config(state=tk.DISABLED)

class EnhancementResultWindow(tk.Toplevel):
    """A pop-up window to display enhancement results."""
    def __init__(self, parent: 'GUIApp', result_data: dict, processor: PromptProcessor, model: str, selected_variations: List[str], cancel_callback: callable, api_call_finish_callback: callable):
        super().__init__(parent)
        self.title("Enhancement Result")
        self.geometry("700x750")
        self.transient(parent)
        self.grab_set()
        self.api_call_finish_callback = api_call_finish_callback
        self.cancel_callback = cancel_callback
        self.parent_app = parent

        self.processor = processor
        self.model = model
        self.result_data = result_data
        self.selected_variations = selected_variations

        # UI element storage
        self.text_widgets = {}
        self.sd_model_labels = {}
        self.loading_animations = {}
        self.copy_buttons = {}
        self.regen_buttons = {}
        self.regen_queue = queue.Queue()
        self.result_queue = queue.Queue()

        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Create all text areas with placeholder content for dynamic fields
        self._create_text_area(main_frame, 'original', "Original Prompt", self.result_data['original'], height=3)
        self._create_text_area(main_frame, 'enhanced', "Enhanced Prompt", "Generating...", sd_model="Generating...", height=6)

        if self.selected_variations:
            variations_frame = ttk.LabelFrame(main_frame, text="Variations", padding="10")
            variations_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            for var_type in self.selected_variations:
                self._create_text_area(variations_frame, var_type, var_type.capitalize(), "Generating...", sd_model="Generating...", height=4)

        # --- Action Buttons ---
        button_frame = ttk.Frame(main_frame, padding=(0, 10, 0, 0))
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="Save to History", command=self._save).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Close", command=self._on_close).pack(side=tk.RIGHT)

        self.after(100, self._check_result_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        # Only trigger the cancellation logic if there are still active API calls.
        if self.parent_app.active_api_calls > 0:
            self.cancel_callback()
        self.destroy()
    
    def _create_text_area(self, parent, prompt_key: str, title: str, content: str, height: int, sd_model: Optional[str] = None):
        frame = ttk.LabelFrame(parent, text=title, padding="5")
        frame.pack(fill=tk.X, pady=5)
        
        # Frame to hold text and copy button
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.X, expand=True)

        # Scrollbar and Text widget
        scroll_text_frame = ttk.Frame(text_frame)
        scroll_text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(scroll_text_frame, orient=tk.VERTICAL)
        text_widget = tk.Text(scroll_text_frame, wrap=tk.WORD, height=height, font=("Helvetica", 11), yscrollcommand=scrollbar.set)
        scrollbar.config(command=text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_widget.insert("1.0", content)
        text_widget.config(state=tk.DISABLED)
        self.text_widgets[prompt_key] = text_widget
        
        # Button container
        button_container = ttk.Frame(text_frame)
        button_container.pack(side=tk.LEFT, padx=(5, 0), anchor='n')
        
        copy_button = ttk.Button(button_container, text="Copy", command=lambda key=prompt_key: self._copy_current_prompt(key))
        copy_button.pack(fill=tk.X)
        self.copy_buttons[prompt_key] = copy_button

        if prompt_key != 'original':
            # Create spinner and regen button, but only show the spinner initially
            loading_animation = LoadingAnimation(button_container)
            is_dark = self.parent_app.theme_manager.current_theme == "dark"
            status_bar_dot_color = "lightgrey" if is_dark else "dimgray"
            status_bar_bg = self.cget('background')
            loading_animation.update_style(bg_color=status_bar_bg, dot_color=status_bar_dot_color, is_dark_theme=is_dark)
            loading_animation.pack(fill=tk.X, pady=(5,0))
            loading_animation.start()
            self.loading_animations[prompt_key] = loading_animation

            regen_button = ttk.Button(button_container, text="Regen", command=lambda key=prompt_key: self._start_regeneration(key))
            # Don't pack the regen button yet
            self.regen_buttons[prompt_key] = regen_button
            copy_button.config(state=tk.DISABLED)

        # Add SD model label if provided
        if sd_model:
            model_label = ttk.Label(frame, text=f"Recommended Model: {sd_model}", font=("Helvetica", 9, "italic"), foreground="gray")
            model_label.pack(anchor='w', padx=5, pady=(2, 0))
            self.sd_model_labels[prompt_key] = model_label

    def _save(self):
        """Save the result to the CSV history."""
        self.processor.save_results([self.result_data])
        messagebox.showinfo("Saved", "Result saved to history.", parent=self)
        self.destroy()

    def _copy_to_clipboard(self, content: str):
        """Copies the given content to the clipboard."""
        self.clipboard_clear()
        self.clipboard_append(content)

    def _copy_current_prompt(self, prompt_key: str):
        """Copies the current prompt text from the internal data structure."""
        content_to_copy = ""
        if prompt_key == 'original':
            content_to_copy = self.result_data['original']
        elif prompt_key == 'enhanced':
            content_to_copy = self.result_data['enhanced']
        elif prompt_key in self.result_data.get('variations', {}):
            content_to_copy = self.result_data['variations'][prompt_key]['prompt']
        
        if content_to_copy:
            self._copy_to_clipboard(content_to_copy)

    def _start_regeneration(self, prompt_key: str):
        """Starts the regeneration process for a specific prompt in a background thread."""
        # Notify the parent app to update its counters and status
        self.parent_app.register_regeneration_call(prompt_key)

        # Hide regen button and show spinner
        self.regen_buttons[prompt_key].pack_forget()
        self.loading_animations[prompt_key].pack(fill=tk.X, pady=(5,0))
        self.loading_animations[prompt_key].start()
        
        text_widget = self.text_widgets[prompt_key]
        text_widget.config(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        text_widget.insert("1.0", "Regenerating...")
        text_widget.config(state=tk.DISABLED)

        thread = threading.Thread(target=self._regenerate_thread, args=(prompt_key,), daemon=True)
        thread.start()
        self.after(100, self._check_regen_queue)

    def _regenerate_thread(self, prompt_key: str):
        """The background task that calls the AI model for regeneration."""
        try:
            if prompt_key == 'enhanced':
                new_prompt, new_sd_model = self.processor.ollama_client.enhance_prompt(self.result_data['original'], self.model)
                result = {'key': prompt_key, 'prompt': new_prompt, 'sd_model': new_sd_model}
            else: # It's a variation
                base_enhanced = self.result_data['enhanced']
                variation_result = self.processor.ollama_client.create_single_variation(base_enhanced, self.model, prompt_key)
                result = {'key': prompt_key, 'prompt': variation_result['prompt'], 'sd_model': variation_result['sd_model']}
            self.regen_queue.put(result)
        except Exception as e:
            self.regen_queue.put({'key': prompt_key, 'error': str(e)})

    def _check_regen_queue(self):
        """Checks for regeneration results and updates the UI."""
        try:
            result = self.regen_queue.get_nowait()
            key = result['key']

            # Hide spinner and show regen button
            self.loading_animations[key].stop()
            self.loading_animations[key].pack_forget()
            self.regen_buttons[key].pack(fill=tk.X, pady=(5,0))
            
            if 'error' in result:
                messagebox.showerror("Regeneration Error", result['error'], parent=self)
                # Notify parent that the call failed
                self.parent_app.report_regeneration_finished(success=False)
                return

            new_prompt, new_sd_model = result['prompt'], result['sd_model']
            
            # Update UI
            self.text_widgets[key].config(state=tk.NORMAL)
            self.text_widgets[key].delete("1.0", tk.END)
            self.text_widgets[key].insert("1.0", new_prompt)
            self.text_widgets[key].config(state=tk.DISABLED)
            if key in self.sd_model_labels:
                self.sd_model_labels[key].config(text=f"Recommended Model: {new_sd_model}")
            
            # Update internal data for saving
            if key == 'enhanced':
                self.result_data['enhanced'] = new_prompt
                self.result_data['enhanced_sd_model'] = new_sd_model
            else:
                self.result_data['variations'][key]['prompt'] = new_prompt
                self.result_data['variations'][key]['sd_model'] = new_sd_model
            
            # Notify parent that the call is complete
            self.parent_app.report_regeneration_finished(success=True)
            
        except queue.Empty:
            self.after(100, self._check_regen_queue)

    def _check_result_queue(self):
        """Checks for incoming results from the main processing thread and updates the UI."""
        try:
            key, data = self.result_queue.get_nowait()
            
            # Update internal data for saving
            if key == 'enhanced':
                self.result_data['enhanced'] = data['prompt']
                self.result_data['enhanced_sd_model'] = data['sd_model']
            else:
                self.result_data['variations'][key] = data

            self.text_widgets[key].config(state=tk.NORMAL)
            self.text_widgets[key].delete("1.0", tk.END)
            self.text_widgets[key].insert("1.0", data['prompt'])
            self.text_widgets[key].config(state=tk.DISABLED)

            self.sd_model_labels[key].config(text=f"Recommended Model: {data['sd_model']}")
            # Hide spinner and show regen button
            self.loading_animations[key].stop()
            self.loading_animations[key].pack_forget()
            self.regen_buttons[key].pack(fill=tk.X, pady=(5,0))
            self.copy_buttons[key].config(state=tk.NORMAL)

            # Notify parent that an API call has finished
            self.api_call_finish_callback()
        except queue.Empty:
            pass # No new results yet
        finally:
            self.after(100, self._check_result_queue)

class ActionBar(ttk.Frame):
    """The main action bar with Generate, Enhance, and variation selection."""
    def __init__(self, parent, generate_callback: callable, enhance_callback: callable, copy_callback: callable, **kwargs):
        super().__init__(parent, **kwargs)

        self.generate_button = ttk.Button(self, text="Generate Next Preview", command=generate_callback, state=tk.DISABLED)
        self.generate_button.pack(side=tk.LEFT, padx=(0, 5))

        self.select_button = ttk.Button(self, text="Enhance This Prompt", command=enhance_callback, state=tk.DISABLED)
        self.select_button.pack(side=tk.LEFT)

        self.variations_frame = ttk.LabelFrame(self, text="Variations", padding=(10, 5))
        self.variations_frame.pack(side=tk.LEFT, padx=(10, 0))
        
        self.variation_vars: Dict[str, tk.BooleanVar] = {}
        self.variation_tooltips: List[Tooltip] = []

        self.copy_prompt_button = ttk.Button(self, text="Copy Prompt", command=copy_callback, state=tk.DISABLED)
        self.copy_prompt_button.pack(side=tk.LEFT, padx=(10, 0))

    def rebuild_variations(self, variation_keys: List[str]):
        """Clears and recreates the variation checkboxes."""
        for widget in self.variations_frame.winfo_children():
            widget.destroy()

        self.variation_vars.clear()
        self.variation_tooltips.clear()

        for key in variation_keys:
            var = tk.BooleanVar(value=True)
            self.variation_vars[key] = var
            cb = ttk.Checkbutton(self.variations_frame, text=key.capitalize(), variable=var)
            cb.pack(side=tk.LEFT, padx=5)
            tooltip = Tooltip(cb, VARIATION_TOOLTIPS.get(key, "Generate this variation."))
            cb.bind("<Enter>", tooltip.show)
            cb.bind("<Leave>", tooltip.hide)
            self.variation_tooltips.append(tooltip)

    def get_selected_variations(self) -> List[str]:
        """Returns a list of the names of the selected variations."""
        return [key for key, var in self.variation_vars.items() if var.get()]

    def set_button_states(self, generate: str, enhance: str, copy: str):
        self.generate_button.config(state=generate)
        self.select_button.config(state=enhance)
        self.copy_prompt_button.config(state=copy)

class TemplateEditor(ttk.Frame):
    """The template editor text widget and its frame."""
    def __init__(self, parent, live_update_callback: callable, double_click_callback: callable, generate_wildcard_callback: callable, brainstorm_callback: callable, **kwargs):
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
        """Highlights missing wildcards and tags all wildcards in the template editor."""
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
        cursor_index = self.text_widget.index(tk.INSERT)
        tags_at_cursor = self.text_widget.tag_names(cursor_index)

        if "any_wildcard" in tags_at_cursor:
            tag_range = self.text_widget.tag_prevrange("any_wildcard", cursor_index + "+1c")
            if tag_range:
                self.text_widget.delete(tag_range[0], tag_range[1])
                self.text_widget.insert(tag_range[0], tag_to_insert)
        elif self.text_widget.tag_ranges("sel"):
            self.text_widget.delete("sel.first", "sel.last")
            self.text_widget.insert(tk.INSERT, tag_to_insert)
        else:
            self.text_widget.insert(tk.INSERT, tag_to_insert)

        self.text_widget.focus_set()

class WildcardInserter(ttk.Frame):
    """The wildcard inserter listbox and its frame."""
    def __init__(self, parent, insert_callback: callable, manage_callback: callable, **kwargs):
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

class GUIApp(tk.Tk):
    """A GUI for the Stable Diffusion Prompt Generator."""

    def __init__(self):
        super().__init__()
        self.geometry("900x700")

        # Set application icon
        try:
            icon_path = os.path.join(config.PROJECT_ROOT, 'assets', 'icon.png')
            if os.path.exists(icon_path):
                self.iconphoto(True, tk.PhotoImage(file=icon_path))
        except Exception as e:
            print(f"Warning: Could not load application icon: {e}")

        # Initialize and apply the theme first
        self.theme_manager = ThemeManager()
        self.theme_manager.apply_theme(self)

        # Core logic
        self.processor = PromptProcessor()
        self.processor.initialize()
        self.processor.set_callbacks(status_callback=self._update_status_bar)
        self.enhancement_total_calls = 0
        self.enhancement_calls_made = 0
        self.active_api_calls = 0
        self.enhancement_cancellation_event: Optional[threading.Event] = None

        # State
        self.current_template_content: Optional[str] = None
        self.current_template_file: Optional[str] = None
        self.current_structured_prompt: List[PromptSegment] = []
        self.segment_map: List[Tuple[str, str, int]] = [] # start, end, segment_index
        self.preview_font = ("Helvetica", 13)
        self.tooltip: Optional[Tooltip] = None
        self.debounce_timer: Optional[str] = None
        self.active_models: Dict[str, int] = {}
        self.active_enhancement_model: Optional[str] = None
        self.brainstorming_window: Optional[BrainstormingWindow] = None
        self.wildcard_manager_window: Optional[WildcardManagerWindow] = None
        self.history_viewer_window: Optional[HistoryViewerWindow] = None
        self.loading_animation: Optional[LoadingAnimation] = None
        self.template_editor: Optional[TemplateEditor] = None
        self.wildcard_inserter: Optional[WildcardInserter] = None
        self.file_menu: Optional[tk.Menu] = None
        self.enhancement_model_var = tk.StringVar()
        self.workflow_var = tk.StringVar(value=config.workflow)
        self.enhancement_queue = queue.Queue()

        # Create widgets
        self._create_widgets()
        self._update_text_widget_colors() # Set initial theme-based colors
        self._load_templates()
        self._load_models()
        self._populate_wildcard_lists()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self._update_window_title() # Set initial title

    def _create_widgets(self):
        """Create and layout the main widgets."""
        self._create_menu_bar()

        # --- Top Control Frame ---
        control_frame = ttk.Frame(self, padding="10")
        control_frame.pack(fill=tk.X)

        # Template Dropdown
        ttk.Label(control_frame, text="Template:").pack(side=tk.LEFT, padx=(0, 5))
        self.template_var = tk.StringVar()
        self.template_var.trace_add("write", self._on_template_var_change)
        self.template_dropdown = ttk.OptionMenu(control_frame, self.template_var, "Select a template")
        self.template_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        # Model Dropdown
        ttk.Label(control_frame, text="Model:").pack(side=tk.LEFT, padx=(0, 5))
        self.enhancement_model_var.trace_add("write", self._on_enhancement_model_change)
        self.model_dropdown = ttk.OptionMenu(control_frame, self.enhancement_model_var, "Select a model")
        self.model_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._create_main_view(self)

        # --- Bottom Action Frame ---
        action_frame = ttk.Frame(self, padding=(10, 5, 10, 10))
        action_frame.pack(fill=tk.X)
        self._create_action_bar(action_frame)
        self.action_bar.pack(fill=tk.X)

        # --- Status Bar ---
        status_frame = ttk.Frame(self, relief=tk.SUNKEN)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.loading_animation = LoadingAnimation(status_frame)
        self.loading_animation.pack(side=tk.LEFT, padx=5, pady=2)

        self.status_var = tk.StringVar()
        status_bar = ttk.Label(status_frame, textvariable=self.status_var, anchor=tk.W, padding=(0, 5, 5, 5))
        status_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _create_menu_bar(self):
        """Creates the main application menu bar."""
        menubar = tk.Menu(self)

        # --- File Menu ---
        self.file_menu = tk.Menu(menubar, tearoff=0)
        self.file_menu.add_command(label="New Template...", command=self._create_new_template_file)
        self.file_menu.add_command(label="Save Template", command=self._save_template, state=tk.DISABLED)
        self.file_menu.add_command(label="Archive Template...", command=self._archive_current_template, state=tk.DISABLED)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self._on_closing)
        menubar.add_cascade(label="File", menu=self.file_menu)

        # --- Workflow Menu ---
        workflow_menu = tk.Menu(menubar, tearoff=0)
        workflow_menu.add_radiobutton(label="SFW (Safe For Work)", variable=self.workflow_var, value="sfw", command=self._switch_workflow)
        workflow_menu.add_radiobutton(label="NSFW (Not Safe For Work)", variable=self.workflow_var, value="nsfw", command=self._switch_workflow)
        menubar.add_cascade(label="Workflow", menu=workflow_menu)
        self.workflow_var.set(config.workflow) # Ensure it's set on startup

        # --- View Menu ---
        view_menu = tk.Menu(menubar, tearoff=0)
        theme_menu = tk.Menu(view_menu, tearoff=0)
        theme_menu.add_command(label="Light", command=lambda: self._set_theme("light"))
        theme_menu.add_command(label="Dark", command=lambda: self._set_theme("dark"))
        view_menu.add_cascade(label="Theme", menu=theme_menu)
        menubar.add_cascade(label="View", menu=view_menu)

        # --- Tools Menu ---
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Wildcard Manager", command=self._open_wildcard_manager)
        tools_menu.add_command(label="Ollama Server...", command=self._change_ollama_server)
        tools_menu.add_command(label="AI Brainstorming", command=self._open_brainstorming_window)
        tools_menu.add_command(label="System Prompt Editor", command=self._open_system_prompt_editor)
        tools_menu.add_command(label="History Viewer", command=self._open_history_viewer)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        self.config(menu=menubar)

    def _create_main_view(self, parent):
        """Creates the widgets for the main prompt generation view."""
        v_pane = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        v_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Top horizontal splitter for editor and wildcard list
        top_h_pane = ttk.PanedWindow(v_pane, orient=tk.HORIZONTAL)
        v_pane.add(top_h_pane, weight=2)

        # --- Template editor (left side of top pane) ---
        self.template_editor = TemplateEditor(
            top_h_pane,
            live_update_callback=self._schedule_live_update,
            double_click_callback=self._on_template_double_click,
            generate_wildcard_callback=self._generate_missing_wildcard,
            brainstorm_callback=self._brainstorm_with_template
        )
        top_h_pane.add(self.template_editor, weight=3)

        # --- Wildcard inserter (right side of top pane) ---
        self.wildcard_inserter = WildcardInserter(
            top_h_pane,
            insert_callback=self._insert_wildcard_tag,
            manage_callback=self._open_wildcard_manager
        )
        top_h_pane.add(self.wildcard_inserter, weight=1)

        # Generated prompt (bottom pane of vertical splitter)
        preview_pane = ttk.LabelFrame(v_pane, text="Generated Prompt (Wildcards are highlighted)", padding=5)
        self.prompt_text = tk.Text(preview_pane, wrap=tk.WORD, height=10, font=self.preview_font)
        self.prompt_text.pack(fill=tk.BOTH, expand=True)
        self.prompt_text.config(state=tk.DISABLED)

        # Configure tags and bindings for the interactive prompt text
        self.prompt_text.tag_configure("wildcard", relief="raised", borderwidth=1)
        self.prompt_text.tag_bind("wildcard", "<Enter>", self._on_wildcard_enter)
        self.prompt_text.tag_bind("wildcard", "<Leave>", self._on_wildcard_leave)
        self.prompt_text.tag_bind("wildcard", "<Button-1>", self._on_wildcard_click)
        self.prompt_text.tag_configure("wildcard_hover")
        v_pane.add(preview_pane, weight=3)

    def _create_action_bar(self, parent):
        """Creates the main action buttons at the bottom of the window."""
        self.action_bar = ActionBar(
            parent,
            generate_callback=self._generate_preview,
            enhance_callback=self._on_select_for_enhancement,
            copy_callback=self._copy_generated_prompt
        )
        self._update_action_bar_variations()

    def _update_window_title(self):
        """Updates the main window title to reflect the current workflow."""
        base_title = "Prompt Tool GUI"
        workflow_text = config.workflow.upper()
        self.title(f"{base_title} - [{workflow_text} Mode]")

    def _set_theme(self, theme_name: str):
        """Sets the theme and updates UI elements that need manual color changes."""
        self.theme_manager.set_theme(theme_name)
        self._update_text_widget_colors()

    def _update_text_widget_colors(self):
        """Updates colors for text widgets and tags based on the current theme."""
        is_dark = self.theme_manager.current_theme == "dark"

        # Define colors for light and dark modes
        wildcard_bg = "#3c4c5c" if is_dark else "#d8e9f3"
        wildcard_hover_bg = "#4a5e73" if is_dark else "#b8d9e3"
        missing_wildcard_bg = "#6b2b2b" if is_dark else "#ffcccc"
        status_bar_dot_color = "lightgrey" if is_dark else "dimgray"
        status_bar_bg = self.cget('background')

        # Apply colors to tags
        self.prompt_text.tag_configure("wildcard", background=wildcard_bg)
        self.prompt_text.tag_configure("wildcard_hover", background=wildcard_hover_bg)
        self.template_editor.text_widget.tag_configure("missing_wildcard", background=missing_wildcard_bg)

        if self.loading_animation:
            self.loading_animation.update_style(bg_color=status_bar_bg, dot_color=status_bar_dot_color, is_dark_theme=is_dark)

    def _load_templates(self):
        """Loads available templates into the dropdown menu."""
        # Always reset the view to a clean state before loading new templates
        self._clear_template_view()

        templates = self.processor.get_available_templates()
        menu = self.template_dropdown["menu"]
        menu.delete(0, "end")

        if not templates:
            workflow_dir = config.get_template_dir()
            messagebox.showwarning("No Templates", f"No template files found for the '{config.workflow.upper()}' workflow.\n\nPlease add .txt files to:\n{workflow_dir}")
            self.template_var.set("No templates found")
            self.template_dropdown.config(state=tk.DISABLED)
            return
        
        self.template_dropdown.config(state=tk.NORMAL)
        for template in templates:
            menu.add_command(label=template, command=lambda value=template: self.template_var.set(value))
        
        # Prompt the user to make a selection
        self.template_var.set("Select a template")

    def _update_action_bar_variations(self):
        """Updates the variation checkboxes in the action bar based on the current workflow."""
        variation_keys = list(DEFAULT_SFW_VARIATION_INSTRUCTIONS.keys()) if config.workflow == 'sfw' else list(DEFAULT_NSFW_VARIATION_INSTRUCTIONS.keys())
        self.action_bar.rebuild_variations(variation_keys)

    def _load_models(self):
        """Loads available Ollama models into the dropdown menu."""
        try:
            models = self.processor.get_available_models()
            if not models:
                self.enhancement_model_var.set("No models found")
                return

            menu = self.model_dropdown["menu"]
            menu.delete(0, "end")
            for model in models:
                menu.add_command(label=model, command=lambda value=model: self.enhancement_model_var.set(value))

            # Set a default model if possible
            default_model = next((m for m in models if 'qwen' in m.lower()), models[0])
            self.enhancement_model_var.set(default_model)
            
            # Register initial model usage
            self.active_enhancement_model = default_model
            self._handle_model_change(None, self.active_enhancement_model)

        except Exception as e:
            messagebox.showerror("Model Error", f"Could not load Ollama models:\n{e}")
            self.enhancement_model_var.set("Error loading models")

    def _switch_workflow(self):
        """Handles the logic for switching between SFW and NSFW modes."""
        new_workflow = self.workflow_var.get()
        if new_workflow == config.workflow:
            return

        config.workflow = new_workflow
        settings = load_settings()
        settings['workflow'] = new_workflow
        save_settings(settings)

        # Tell the processor to reload its internal wildcard state
        self.processor.reload_wildcards()

        # Update UI components that depend on the workflow
        self._update_action_bar_variations()
        self._load_templates() # This will now reset the view and prompt for selection
        self._populate_wildcard_lists()
        self._update_window_title()

        # Close history viewer if it's open, as its data is now stale
        if self.history_viewer_window and self.history_viewer_window.winfo_exists():
            self.history_viewer_window.destroy()
            self.history_viewer_window = None

        self.status_var.set(f"Switched to {new_workflow.upper()} workflow. Select a template.")

    def _clear_template_view(self):
        """Resets the UI to a state where no template is loaded."""
        self.current_template_file = None
        self.current_template_content = None
        self.current_structured_prompt = []
        self.template_editor.clear()
        self.template_editor.set_label("Template Content")
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.config(state=tk.DISABLED)
        self.action_bar.set_button_states(generate=tk.DISABLED, enhance=tk.DISABLED, copy=tk.DISABLED)
        self.file_menu.entryconfig("Save Template", state=tk.DISABLED)
        self.file_menu.entryconfig("Archive Template...", state=tk.DISABLED)
    def _populate_wildcard_lists(self):
        """Populates both the inserter and editor wildcard lists."""
        wildcard_files = self.processor.get_wildcard_files()
        if not wildcard_files:
            workflow_dir = config.get_wildcard_dir()
            shared_dir = config.WILDCARD_SHARED_DIR
            messagebox.showwarning("No Wildcards", f"No wildcard files found for the '{config.workflow.upper()}' workflow.\n\nPlease add .txt files to the workflow-specific folder:\n{workflow_dir}\n\nor the shared folder:\n{shared_dir}")
        self.wildcard_inserter.populate(wildcard_files)

    def _on_template_var_change(self, *args):
        """Callback for when the template_var changes."""
        new_template_name = self.template_var.get()

        # Ignore placeholder text to prevent errors
        if new_template_name in ["Select a template", "No templates found"]:
            return

        # Prevent redundant updates if the value is set to the same thing
        if new_template_name and new_template_name != self.current_template_file:
            self._on_template_select(new_template_name)

    def _on_enhancement_model_change(self, *args):
        """Handles when the user selects a new model for enhancement."""
        new_model = self.enhancement_model_var.get()
        old_model = self.active_enhancement_model
        if new_model and "model" not in new_model.lower() and new_model != old_model:
            self._handle_model_change(old_model, new_model)
            self.active_enhancement_model = new_model

    def _on_template_select(self, template_name: str):
        """Callback for when a template is selected from the dropdown."""
        self.current_template_file = template_name
        self.template_editor.set_label("Template Content") # Reset label

        # Load template content into both state and the template view
        self.current_template_content = self.processor.load_template_content(template_name)
        self.template_editor.set_content(self.current_template_content)
        self._highlight_template_wildcards()

        # Update UI state
        self.action_bar.set_button_states(generate=tk.NORMAL, enhance=tk.DISABLED, copy=tk.DISABLED)
        self.file_menu.entryconfig("Save Template", state=tk.NORMAL)
        self.file_menu.entryconfig("Archive Template...", state=tk.NORMAL)
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert(tk.END, f"Template '{template_name}' loaded. Click 'Generate Next Preview' to start.")
        self.prompt_text.config(state=tk.DISABLED)
        self.current_structured_prompt = []
        self.status_var.set(f"Loaded template: {template_name}")

    def _generate_preview(self):
        """Generates a single prompt and displays it in the text box."""
        # Get content directly from the live editor
        live_content = self.template_editor.get_content() # Get all text except the final newline
        if not live_content.strip():
            return

        # Generate with fresh random wildcards, so pass existing_segments=None
        self.current_structured_prompt = self.processor.generate_single_structured_prompt(live_content, existing_segments=None)
        self._display_structured_prompt()
        is_prompt_available = bool(self.current_structured_prompt)
        self.action_bar.set_button_states(generate=tk.NORMAL, enhance=tk.NORMAL if is_prompt_available else tk.DISABLED, copy=tk.NORMAL if is_prompt_available else tk.DISABLED)

    def _display_structured_prompt(self):
        """Renders the structured prompt with highlighting."""
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.segment_map = []

        for i, segment in enumerate(self.current_structured_prompt):
            start = self.prompt_text.index(tk.INSERT)
            self.prompt_text.insert(tk.INSERT, segment.text)
            end = self.prompt_text.index(tk.INSERT)

            if segment.wildcard_name:
                tag_name = f"wildcard_{i}"
                self.prompt_text.tag_add(tag_name, start, end)
                self.prompt_text.tag_add("wildcard", start, end)
                self.segment_map.append((start, end, i))

        self.prompt_text.config(state=tk.DISABLED)

    def _on_wildcard_enter(self, event):
        """Handle mouse entering a wildcard tag."""
        if self.tooltip:
            self.tooltip.hide()

        # Find the tag under the cursor
        tag_ranges = self.prompt_text.tag_ranges("wildcard")
        for i in range(0, len(tag_ranges), 2):
            start, end = tag_ranges[i], tag_ranges[i+1]
            if self.prompt_text.compare(start, "<=", "current") and self.prompt_text.compare("current", "<", end):
                # Find which segment this corresponds to
                for seg_start, seg_end, seg_index in self.segment_map:
                    if self.prompt_text.compare(start, "==", seg_start):
                        wildcard_name = self.current_structured_prompt[seg_index].wildcard_name
                        self.tooltip = Tooltip(self.prompt_text, f"Source: {wildcard_name}.txt")
                        self.tooltip.show(event)
                        self.prompt_text.tag_add("wildcard_hover", start, end)
                        break
                break

    def _on_wildcard_leave(self, event):
        """Handle mouse leaving a wildcard tag."""
        if self.tooltip:
            self.tooltip.hide()
        self.prompt_text.tag_remove("wildcard_hover", "1.0", tk.END)

    def _on_wildcard_click(self, event):
        """Handle clicking on a wildcard tag."""
        # Find the segment that was clicked
        clicked_segment_index = -1
        for start, end, seg_index in self.segment_map:
            if self.prompt_text.compare(start, "<=", "current") and self.prompt_text.compare("current", "<", end):
                clicked_segment_index = seg_index
                break

        if clicked_segment_index != -1:
            self._show_swap_menu(event, clicked_segment_index)

    def _show_swap_menu(self, event, segment_index: int):
        """Display a context menu to swap the wildcard value."""
        segment = self.current_structured_prompt[segment_index]
        if not segment.wildcard_name:
            return

        options = self.processor.get_wildcard_options(segment.wildcard_name)
        if not options:
            return

        menu = tk.Menu(self, tearoff=0)
        for option in options:
            # Truncate long options for display in the menu
            display_option = (option[:75] + '...') if len(option) > 75 else option
            menu.add_command(
                label=display_option,
                command=lambda opt=option: self._swap_wildcard(segment_index, opt)
            )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _swap_wildcard(self, segment_index: int, new_value: str):
        """Swap the text of a wildcard segment and redisplay the prompt."""
        if 0 <= segment_index < len(self.current_structured_prompt):
            self.current_structured_prompt[segment_index].text = new_value
            self._display_structured_prompt()

    def _schedule_live_update(self, event=None):
        """Schedules a live update of the prompt preview after a short delay."""
        if self.debounce_timer:
            self.after_cancel(self.debounce_timer)
        
        self.debounce_timer = self.after(500, self._perform_live_update)

    def _perform_live_update(self, force_reroll: Optional[List[str]] = None):
        """Updates the prompt preview using the current template text and existing wildcards."""
        self.debounce_timer = None
        if not self.current_template_content:
            return
            
        live_content = self.template_editor.get_content()
        if not live_content.strip():
            return
            
        # Regenerate the prompt, reusing the existing wildcard choices
        self.current_structured_prompt = self.processor.generate_single_structured_prompt(
            live_content,
            existing_segments=self.current_structured_prompt,
            force_reroll=force_reroll
        )
        self._display_structured_prompt()
        self._highlight_template_wildcards()
        if force_reroll:
            self.status_var.set(f"Wildcard '{force_reroll[0]}' updated.")
        else:
            self.status_var.set("Preview updated based on template changes.")

    def _save_template(self):
        """Save the currently edited template content to its file."""
        if not self.current_template_file:
            self.status_var.set("No template selected to save.")
            return

        content = self.template_editor.get_content()
        try:
            self.processor.save_template_content(self.current_template_file, content)
            self.status_var.set(f"Template '{self.current_template_file}' saved successfully.")
            self.current_template_content = content # Update internal state
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save template:\n{e}")
            self.status_var.set(f"Error saving template: {self.current_template_file}")

    def _copy_generated_prompt(self):
        """Copies the current generated prompt text to the clipboard."""
        prompt_text = ""
        if self.current_template_file:
            # Reconstruct the full prompt string from segments
            prompt_text = "".join(seg.text for seg in self.current_structured_prompt)
        else:
            # Get the prompt directly from the editor pane
            prompt_text = self.template_editor.get_content().strip()

        if not prompt_text:
            self.status_var.set("Nothing to copy.")
            return
        
        self.clipboard_clear()
        self.clipboard_append(prompt_text)
        self.status_var.set("Prompt copied to clipboard.")

    def _on_select_for_enhancement(self):
        """Handles the 'Enhance This Prompt' button click."""
        model = self.enhancement_model_var.get()
        if not model or "model" in model.lower():
            messagebox.showerror("Error", "Please select a valid Ollama model first.")
            return

        # Determine if we are enhancing from a template-generated prompt or a manually edited one
        if self.current_template_file:
            # Reconstruct the full prompt string from segments
            prompt_text = "".join(seg.text for seg in self.current_structured_prompt)
        else:
            # Get the prompt directly from the editor pane
            prompt_text = self.template_editor.get_content().strip()

        if not prompt_text:
            messagebox.showerror("Error", "No prompt to enhance.")
            return

        # Create the results window immediately
        selected_variations = self.action_bar.get_selected_variations()
        initial_data = {'original': prompt_text, 'variations': {}}

        # Set up call counters for the new batch
        self.enhancement_calls_made = 0
        self.enhancement_total_calls = 1 + len(selected_variations)
        self.active_api_calls = self.enhancement_total_calls
        if self.active_api_calls > 0:
            self.loading_animation.start()

        self.enhancement_cancellation_event = threading.Event()
        result_window = EnhancementResultWindow(self, initial_data, self.processor, model, selected_variations, self._cancel_enhancement_batch, self.report_api_call_finished)

        # Define a thread-safe callback to update the results window
        def result_callback(key, data):
            result_window.result_queue.put((key, data))

        # Set callbacks for the processor
        self.processor.set_callbacks(
            status_callback=self._update_status_bar_from_event,
            result_callback=result_callback
        )

        self.action_bar.select_button.config(state=tk.DISABLED)
        self.status_var.set(f"Enhancing prompt with {model}...")

        # Run enhancement in a separate thread to avoid freezing the GUI
        thread = threading.Thread(target=self._run_enhancement_thread, args=(prompt_text, model, selected_variations, self.enhancement_cancellation_event), daemon=True)
        thread.start()

    def _run_enhancement_thread(self, prompt: str, model: str, selected_variations: List[str], cancellation_event: threading.Event):
        """The function that runs in a separate thread to process the prompt."""
        try:
            # This is now a fire-and-forget process from the GUI's perspective.
            # The processor will use callbacks to update the UI.
            self.processor.process_enhancement_batch([prompt], model, selected_variations, cancellation_event)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Enhancement Error", f"An error occurred during processing:\n{e}"))
        finally:
            # Re-enable the main enhance button when processing is complete
            self.action_bar.select_button.config(state=tk.NORMAL)

    def _update_status_bar(self, message: str):
        """Thread-safe method to update the status bar."""
        self.after(0, lambda: self.status_var.set(message))

    def _update_status_bar_from_event(self, event_type: str, **kwargs):
        """Handles structured status events from the processor."""
        # If a cancellation has been requested, ignore any "complete" message for this batch
        if self.enhancement_cancellation_event and self.enhancement_cancellation_event.is_set() and event_type == 'batch_complete':
            return

        self.enhancement_calls_made += 1
        message = ""
        if event_type == 'enhancement_start':
            message = f"Enhancing main prompt... (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        elif event_type == 'variation_start':
            var_type = kwargs.get('var_type', 'unknown')
            message = f"Creating '{var_type}' variation... (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        elif event_type == 'batch_complete':
            message = "Batch processing complete."
        elif event_type == 'batch_cancelled':
            message = "Processing cancelled."
        
        if message:
            self._update_status_bar(message)

    def register_regeneration_call(self, prompt_key: str):
        """Increments the total call counter when a regeneration is requested."""
        self.active_api_calls += 1
        if self.active_api_calls > 0:
            self.loading_animation.start()

        self.enhancement_total_calls += 1
        message = f"Regenerating '{prompt_key}'... (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        self._update_status_bar(message)

    def report_regeneration_finished(self, success: bool):
        """Updates counters and status after a regeneration call is finished."""
        self.report_api_call_finished()

        if success:
            self.enhancement_calls_made += 1
            message = f"Regeneration complete. (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        else:
            message = f"Regeneration failed. (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        self._update_status_bar(message)
    
    def report_api_call_finished(self):
        """Decrements the active API call counter and stops the animation if complete."""
        if self.active_api_calls > 0:
            self.active_api_calls -= 1
        
        if self.active_api_calls == 0:
            self.loading_animation.stop()

    def _cancel_enhancement_batch(self):
        """Sets the cancellation event for the current enhancement batch."""
        if self.enhancement_cancellation_event and not self.enhancement_cancellation_event.is_set():
            self.enhancement_cancellation_event.set()
            self._update_status_bar("Processing cancelled.")
            self.active_api_calls = 0
            self.loading_animation.stop()

    def _open_wildcard_manager(self, initial_file: Optional[str] = None):
        """Opens the wildcard management window."""
        if self.wildcard_manager_window and self.wildcard_manager_window.winfo_exists():
            self.wildcard_manager_window.lift()
            self.wildcard_manager_window.focus_force()
            if initial_file:
                self.wildcard_manager_window.select_and_load_file(initial_file)
        else:
            self.wildcard_manager_window = WildcardManagerWindow(self, self.processor, self._handle_wildcard_update, initial_file=initial_file)
            self.wildcard_manager_window.protocol("WM_DELETE_WINDOW", self._on_wildcard_manager_close)

    def _on_wildcard_manager_close(self):
        if self.wildcard_manager_window:
            self.wildcard_manager_window.destroy()
            self.wildcard_manager_window = None

    def _handle_wildcard_update(self, modified_file: Optional[str] = None):
        """Refreshes wildcard lists and triggers a prompt update if a relevant wildcard was modified."""
        # First, always refresh the inserter list
        self._populate_wildcard_lists()

        if not modified_file or not self.current_structured_prompt:
            return

        modified_wildcard_name = modified_file[:-4]  # remove .txt

        # Check if the modified wildcard is used in the current prompt
        needs_update = any(
            segment.wildcard_name == modified_wildcard_name
            for segment in self.current_structured_prompt
        )

        if needs_update:
            self._perform_live_update(force_reroll=[modified_wildcard_name])

    def _insert_wildcard_tag(self, event):
        """Inserts a wildcard tag, overwriting a selection or the tag under the cursor."""
        wildcard_name = self.wildcard_inserter.get_selected_wildcard_name()
        if not wildcard_name:
            return

        self.template_editor.insert_wildcard_tag(wildcard_name)
        self._highlight_template_wildcards() # Update tags immediately for the next action
        self._schedule_live_update() # Trigger a live preview update for the bottom pane

    def _on_template_double_click(self, event):
        """Handle double-click in template editor to open wildcard file."""
        index = self.template_editor.text_widget.index(f"@{event.x},{event.y}")
        
        # Find the range of the double-clicked word
        word_start = self.template_editor.text_widget.index(f"{index} wordstart")
        word_end = self.template_editor.text_widget.index(f"{index} wordend")
        clicked_word = self.template_editor.text_widget.get(word_start, word_end)

        # Check if it's a wildcard tag
        match = re.fullmatch(r'__([a-zA-Z0-9_.-]+)__', clicked_word)
        if match:
            wildcard_name = match.group(1)
            self._open_wildcard_manager(initial_file=f"{wildcard_name}.txt")

    def _highlight_template_wildcards(self):
        """Highlights missing wildcards and tags all wildcards in the template editor."""
        known_wildcards = self.processor.get_wildcard_names()
        self.template_editor.highlight_wildcards(known_wildcards)

    def _create_new_template_file(self):
        """Prompts user for a new template filename and creates it."""
        filename = simpledialog.askstring("New Template", "Enter new template filename:", parent=self)
        if not filename:
            return
        
        if not filename.endswith('.txt'):
            filename += '.txt'
            
        try:
            # Create an empty file by saving empty content
            self.processor.save_template_content(filename, "")
            self._load_templates()
            self.template_var.set(filename) # This will trigger the update via trace
            self.status_var.set(f"Created and loaded new template: {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not create template file:\n{e}")

    def _archive_current_template(self):
        """Moves the current template file to an archive folder."""
        if not self.current_template_file:
            messagebox.showwarning("No Template", "No template is currently selected to archive.", parent=self)
            return

        if not messagebox.askyesno("Confirm Archive", f"Are you sure you want to archive '{self.current_template_file}'?\n\nThis will move the file to a subfolder named 'archive'.", parent=self):
            return

        try:
            self.processor.archive_template(self.current_template_file)
            self.status_var.set(f"Archived template: {self.current_template_file}")
            
            # Clear the UI and load the next available template
            self.template_editor.clear()
            self.prompt_text.config(state=tk.NORMAL)
            self.prompt_text.delete("1.0", tk.END)
            self.prompt_text.config(state=tk.DISABLED)
            self.current_template_file = None
            self.file_menu.entryconfig("Save Template", state=tk.DISABLED)
            self.file_menu.entryconfig("Archive Template...", state=tk.DISABLED)
            self._load_templates()

        except Exception as e:
            messagebox.showerror("Archive Error", f"Could not archive file:\n{e}", parent=self)

    def _open_brainstorming_window(self):
        """Opens the brainstorming window."""
        if self.brainstorming_window and self.brainstorming_window.winfo_exists():
            self.brainstorming_window.lift()
            self.brainstorming_window.focus_force()
        else:
            try:
                models = self.processor.get_available_models()
                if not models:
                    messagebox.showerror("Error", "No Ollama models available for brainstorming.")
                    return
                default_model = self.enhancement_model_var.get()
                if default_model not in models:
                    default_model = models[0]
                
                self.brainstorming_window = BrainstormingWindow(self, self.processor, models, default_model, self._handle_model_change)
                self.brainstorming_window.protocol("WM_DELETE_WINDOW", self._on_brainstorming_window_close)
            except Exception as e:
                messagebox.showerror("Error", f"Could not open brainstorming window:\n{e}")

    def _on_brainstorming_window_close(self):
        if self.brainstorming_window:
            # Decrement the usage count of the model active in the brainstorming window
            active_model = self.brainstorming_window.active_brainstorm_model
            self._handle_model_change(active_model, None)
            
            self.brainstorming_window.destroy()
            self.brainstorming_window = None

    def _open_history_viewer(self):
        """Opens the history viewer window."""
        if self.history_viewer_window and self.history_viewer_window.winfo_exists():
            self.history_viewer_window.lift()
            self.history_viewer_window.focus_force()
        else:
            self.history_viewer_window = HistoryViewerWindow(self, self.processor)
            self.history_viewer_window.protocol("WM_DELETE_WINDOW", self._on_history_viewer_close)

    def _on_history_viewer_close(self):
        if self.history_viewer_window:
            self.history_viewer_window.destroy()
            self.history_viewer_window = None

    def load_prompt_from_history(self, prompt_text: str):
        """Loads a prompt from the history viewer into the main UI for re-enhancement."""
        # Clear template-related state and UI
        self.template_var.set("") # Clear dropdown selection
        self.current_template_file = None
        self.current_template_content = None
        self.current_structured_prompt = []
        self.file_menu.entryconfig("Save Template", state=tk.DISABLED)
        self.file_menu.entryconfig("Archive Template...", state=tk.DISABLED)
        self.action_bar.generate_button.config(state=tk.DISABLED) # Can't generate from a non-template
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.config(state=tk.DISABLED)

        # Load the historical prompt into the editable text area
        self.template_editor.set_label("Editable Prompt (from History)")
        self.template_editor.set_content(prompt_text)

        # Enable enhancement actions
        self.action_bar.set_button_states(generate=tk.DISABLED, enhance=tk.NORMAL, copy=tk.NORMAL)
        self.status_var.set("Loaded prompt from history. Ready to enhance.")

    def _brainstorm_with_template(self):
        """Sends the current template content to the brainstorming window."""
        if not self.template_editor: return
        content = self.template_editor.get_content()
        filename = self.current_template_file or "Unsaved Template"
        self._brainstorm_with_content("template", filename, content)

    def _brainstorm_with_content(self, content_type: str, filename: str, content: str):
        """Opens the brainstorming window and loads the specified content."""
        self._open_brainstorming_window()
        if self.brainstorming_window and self.brainstorming_window.winfo_exists():
            self.brainstorming_window.lift()
            self.brainstorming_window.focus_force()
            self.brainstorming_window.load_content_for_brainstorming(content_type, filename, content)

    def _generate_missing_wildcard(self, wildcard_name: str):
        """Opens the brainstorming window and triggers generation for a missing wildcard."""
        # The topic for the wildcard is derived from its name
        topic = wildcard_name.replace('_', ' ').replace('-', ' ')
        
        # Open brainstorming window if not already open
        self._open_brainstorming_window()
        
        if self.brainstorming_window and self.brainstorming_window.winfo_exists():
            self.brainstorming_window.lift()
            self.brainstorming_window.focus_force()
            # Call the new method to start generation
            self.brainstorming_window.generate_wildcard_with_topic(topic)

    def _handle_ai_content_update(self, content_type: str):
        """Callback for when AI generates a new file, to refresh UI lists."""
        if content_type == 'template':
            self._load_templates()
        self._populate_wildcard_lists()
        self._highlight_template_wildcards()
        self.status_var.set(f"New AI-generated {content_type} saved.")

    def _open_system_prompt_editor(self):
        """Opens the system prompt editor window."""
        SystemPromptEditorWindow(self, self.processor)

    def _change_ollama_server(self):
        """Opens a dialog to change the Ollama server URL."""
        current_url = config.OLLAMA_BASE_URL
        new_url = simpledialog.askstring(
            "Ollama Server",
            "Enter the base URL for your Ollama server (e.g., http://192.168.1.100:11434):",
            initialvalue=current_url,
            parent=self
        )

        if new_url and new_url.strip() and new_url.strip() != current_url:
            new_url = new_url.strip()
            # Test connection by trying to list models
            try:
                from core.ollama_client import OllamaClient
                test_client = OllamaClient(base_url=new_url)
                test_client.list_models() # This will raise an exception on failure
                
                # If successful, save and update
                config.OLLAMA_BASE_URL = new_url
                
                # Save the setting to file
                user_settings = load_settings()
                user_settings["ollama_base_url"] = new_url
                save_settings(user_settings)

                # Re-initialize the processor's client with the new URL
                self.processor.ollama_client = OllamaClient(base_url=new_url)
                self._load_models() # Reload models in the GUI
                messagebox.showinfo("Success", f"Successfully connected to Ollama server at:\n{new_url}", parent=self)
                self.status_var.set(f"Ollama server set to {new_url}")
            except Exception as e:
                messagebox.showerror("Connection Failed", f"Could not connect to Ollama server at:\n{new_url}\n\nError: {e}", parent=self)

    def _handle_model_change(self, old_model: Optional[str], new_model: Optional[str]):
        """Manages the usage count of models and unloads them when no longer active."""
        if old_model:
            if old_model in self.active_models:
                self.active_models[old_model] -= 1
                if self.active_models[old_model] <= 0:
                    print(f"Model '{old_model}' is no longer active. Unloading in background...")
                    thread = threading.Thread(target=self.processor.cleanup_model, args=(old_model,), daemon=True)
                    thread.start()
                    del self.active_models[old_model]

        if new_model and "model" not in new_model.lower():
            self.active_models[new_model] = self.active_models.get(new_model, 0) + 1

    def _on_closing(self):
        """Handles the main window closing event to clean up resources."""
        if self.active_models:
            print(f"Unloading all active models: {', '.join(self.active_models.keys())}...")
            for model in list(self.active_models.keys()):
                self.processor.cleanup_model(model)
            print("Cleanup complete.")
        self.destroy()