"""A window to review, edit, and save AI-generated content."""

import json
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable, TYPE_CHECKING

from core.prompt_processor import PromptProcessor
from core.config import config
from . import custom_dialogs
from .wildcard_editor_widget import WildcardEditor
from .common import TextContextMenu, LoadingAnimation, SmartWindowMixin

if TYPE_CHECKING:
    from .gui_app import GUIApp

class ReviewAndSaveWindow(tk.Toplevel, SmartWindowMixin):
    """A window to review, edit, and save AI-generated content."""
    def __init__(self, parent, processor: PromptProcessor, content_type: str, generated_content: str, update_callback: Callable, filename: Optional[str] = None, regenerate_callback: Optional[Callable] = None, is_loading: bool = False):
        super().__init__(parent)
        self.processor = processor
        self.content_type = content_type # "wildcard" or "template"
        self.update_callback = update_callback
        self.prefilled_filename = filename
        self.regenerate_callback = regenerate_callback

        # Get the main GUIApp instance. This is tricky because the parent could be
        # the main app itself or another Toplevel window (like BrainstormingWindow).
        # The BrainstormingWindow stores a reference to the main app, which we can use.
        if hasattr(parent, 'parent_app'):
            self.parent_app: 'GUIApp' = parent.parent_app
        else:
            self.parent_app: 'GUIApp' = parent.winfo_toplevel()

        title = f"Review: {self.prefilled_filename}" if self.prefilled_filename else f"Review New {self.content_type.capitalize()}"
        self.title(title)
        
        if self.content_type == 'wildcard':
            self.editor_notebook = ttk.Notebook(self)
            self.editor_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10,0))

            self.structured_editor_frame = ttk.Frame(self.editor_notebook)
            # No suggestion callback is passed, so the button will be disabled.
            self.structured_editor = WildcardEditor(self.structured_editor_frame, self.processor)
            self.structured_editor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            self.editor_notebook.add(self.structured_editor_frame, text="Structured Editor")

            self.raw_text_frame = ttk.Frame(self.editor_notebook)
            self.raw_text_editor = tk.Text(self.raw_text_frame, wrap=tk.WORD, font=self.parent_app.fixed_font, undo=True)
            TextContextMenu(self.raw_text_editor)
            self.raw_text_editor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            self.editor_notebook.add(self.raw_text_frame, text="Raw Text Editor")
            
            # For compatibility with existing methods that use self.text_widget
            self.text_widget = self.raw_text_editor
        else: # 'template'
            self.text_widget = tk.Text(self, wrap=tk.WORD, font=self.parent_app.fixed_font, undo=True)
            self.text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10,0))
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

        # Now that all widgets are created, set the initial state.
        if is_loading:
            self._set_ui_loading(True)
        else:
            self.update_content(generated_content)

        self.smart_geometry(min_width=600, min_height=600)

    def _set_ui_loading(self, is_loading: bool, verb: str = "Generating"):
        """Centralized method to toggle the UI between loading and interactive states."""
        if is_loading:
            self.save_button.config(state=tk.DISABLED)
            if hasattr(self, 'regenerate_button'):
                self.regenerate_button.pack_forget()
            if hasattr(self, 'loading_animation'):
                self.loading_animation.pack(fill=tk.X)
                self.loading_animation.start()
            
            if self.content_type == 'wildcard':
                self.structured_editor.set_data({})
                self.raw_text_editor.delete("1.0", tk.END)
            
            self.text_widget.config(state=tk.NORMAL) # Use the alias
            self.text_widget.delete("1.0", tk.END)
            self.text_widget.insert("1.0", f"{verb} new {self.content_type}...")
            self.text_widget.config(state=tk.DISABLED)

            title = f"{verb}: {self.prefilled_filename}" if self.prefilled_filename else f"{verb} New {self.content_type.capitalize()}"
            self.title(title)
        else:  # Not loading
            if hasattr(self, 'loading_animation'):
                self.loading_animation.stop()
                self.loading_animation.pack_forget()
            
            self.text_widget.config(state=tk.NORMAL)
            self.save_button.config(state=tk.NORMAL)
            if hasattr(self, 'regenerate_button'):
                self.regenerate_button.pack(fill=tk.X)
                self.regenerate_button.config(state=tk.NORMAL)

            title = f"Review: {self.prefilled_filename}" if self.prefilled_filename else f"Review New {self.content_type.capitalize()}"
            self.title(title)

    def update_content(self, new_content: str):
        """Updates the text widget with new content and re-enables buttons."""
        self._set_ui_loading(False)
        if self.content_type == 'wildcard':
            self.raw_text_editor.delete("1.0", tk.END)
            try:
                parsed_data = json.loads(new_content)
                self.structured_editor.set_data(parsed_data)
                self.raw_text_editor.insert("1.0", json.dumps(parsed_data, indent=2))
                self.editor_notebook.select(self.structured_editor_frame)
            except (json.JSONDecodeError, TypeError):
                # If content is not valid JSON, show it in the raw editor
                self.structured_editor.set_data({})
                self.raw_text_editor.insert("1.0", new_content)
                self.editor_notebook.select(self.raw_text_frame)
        else: # template
            self.text_widget.delete("1.0", tk.END)
            self.text_widget.insert("1.0", new_content)

    def _regenerate(self):
        """Calls the provided callback to regenerate content and updates UI to a loading state."""
        if self.regenerate_callback:
            self._set_ui_loading(True, verb="Regenerating")
            # Pass self to the callback so it can update this window instance
            self.regenerate_callback(self)

    def _save(self):
        filename = custom_dialogs.ask_string(
            self,
            f"Save {self.content_type.capitalize()}",
            "Enter filename:",
            initialvalue=self.prefilled_filename
        )
        if not filename: return
        if self.content_type == 'wildcard' and not filename.endswith('.json'):
            filename += '.json'
        elif self.content_type == 'template' and not filename.endswith('.txt'):
            filename += '.txt'

        content = ""
        if self.content_type == 'wildcard':
            active_tab_index = self.editor_notebook.index(self.editor_notebook.select())
            if active_tab_index == 0: # Structured Editor
                data = self.structured_editor.get_data()
                content = json.dumps(data, indent=2)
            else: # Raw Text Editor
                content = self.raw_text_editor.get("1.0", "end-1c")
        else: # template
            content = self.text_widget.get("1.0", "end-1c")

        try:
            if self.content_type == "wildcard":
                json.loads(content) # Validate JSON before saving
                is_nsfw_only = False
                if config.workflow == 'nsfw':
                    is_nsfw_only = custom_dialogs.ask_yes_no(
                        self,
                        "Wildcard Scope",
                        "Save this as an NSFW-only wildcard?\n\n"
                        "(Choosing 'No' will save it to the shared folder, making it available in both SFW and NSFW modes.)"
                    )
                # Save the new wildcard, respecting the user's choice of scope
                self.processor.save_wildcard_content(filename, content, is_nsfw_only=is_nsfw_only)
            elif self.content_type == "template":
                self.processor.save_template_content(filename, content)
            
            self.update_callback(self.content_type) # Refresh lists in the main UI
            self.destroy()
        except Exception as e:
            custom_dialogs.show_error(self, "Save Error", f"Could not save file:\n{e}")