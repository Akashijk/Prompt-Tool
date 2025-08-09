"""A window to review, edit, and save AI-generated content."""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Optional, Callable, TYPE_CHECKING

from core.prompt_processor import PromptProcessor
from core.config import config
from .common import TextContextMenu, LoadingAnimation

if TYPE_CHECKING:
    from .gui_app import GUIApp

class ReviewAndSaveWindow(tk.Toplevel):
    """A window to review, edit, and save AI-generated content."""
    def __init__(self, parent, processor: PromptProcessor, content_type: str, generated_content: str, update_callback: Callable, filename: Optional[str] = None, regenerate_callback: Optional[Callable] = None):
        super().__init__(parent)
        self.processor = processor
        self.content_type = content_type # "wildcard" or "template"
        self.update_callback = update_callback
        self.prefilled_filename = filename
        self.regenerate_callback = regenerate_callback
        self.parent_app: 'GUIApp' = parent.winfo_toplevel() # Get the main GUIApp instance for theme access

        title = f"Review: {self.prefilled_filename}" if self.prefilled_filename else f"Review New {self.content_type.capitalize()}"
        self.title(title)
        self.geometry("600x700")

        self.text_widget = tk.Text(self, wrap=tk.WORD, font=("Courier", 11), undo=True)
        self.text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10,0))
        self.text_widget.insert("1.0", generated_content)
        TextContextMenu(self.text_widget)

        button_frame = ttk.Frame(self, padding=10)
        button_frame.pack(fill=tk.X)

        # Container for save button
        save_frame = ttk.Frame(button_frame)
        save_frame.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.save_button = ttk.Button(save_frame, text="Save", command=self._save)
        self.save_button.pack(fill=tk.X)

        # Container for regenerate button and spinner
        regen_frame = ttk.Frame(button_frame)
        regen_frame.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5,0))

        if self.regenerate_callback:
            self.regenerate_button = ttk.Button(regen_frame, text="Regenerate", command=self._regenerate)
            self.regenerate_button.pack(fill=tk.X)

            self.loading_animation = LoadingAnimation(regen_frame, size=24)
            is_dark = self.parent_app.theme_manager.current_theme == "dark"
            status_bar_dot_color = "lightgrey" if is_dark else "dimgray"
            status_bar_bg = self.cget('background')
            self.loading_animation.update_style(bg_color=status_bar_bg, dot_color=status_bar_dot_color, is_dark_theme=is_dark)
            # Don't pack the animation yet

    def update_content(self, new_content: str):
        """Updates the text widget with new content and re-enables buttons."""
        if hasattr(self, 'loading_animation'):
            self.loading_animation.stop()
            self.loading_animation.pack_forget()

        self.text_widget.delete("1.0", tk.END)
        self.text_widget.insert("1.0", new_content)
        self.title(f"Review: {self.prefilled_filename}" if self.prefilled_filename else f"Review New {self.content_type.capitalize()}")
        self.save_button.config(state=tk.NORMAL)
        if hasattr(self, 'regenerate_button'):
            self.regenerate_button.pack(fill=tk.X) # Show button
            self.regenerate_button.config(state=tk.NORMAL)

    def _regenerate(self):
        """Calls the provided callback to regenerate content and updates UI to a loading state."""
        if self.regenerate_callback:
            # Disable buttons and show loading state
            self.save_button.config(state=tk.DISABLED)
            if hasattr(self, 'regenerate_button'):
                self.regenerate_button.pack_forget() # Hide button
            if hasattr(self, 'loading_animation'):
                self.loading_animation.pack(fill=tk.X) # Show spinner
                self.loading_animation.start()

            # Clear the text widget and show a generating message
            self.text_widget.delete("1.0", tk.END)
            self.text_widget.insert("1.0", f"Generating new {self.content_type}...")

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