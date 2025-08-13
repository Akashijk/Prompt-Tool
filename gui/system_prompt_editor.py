"""A window for editing system-level prompts (enhancement, variations)."""

import json
import os
import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict

from . import custom_dialogs
from core.config import config
from core.prompt_processor import PromptProcessor
from .common import TextContextMenu, SmartWindowMixin

class SystemPromptEditorWindow(tk.Toplevel, SmartWindowMixin):
    """A window for editing system-level prompts (enhancement, variations)."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor):
        super().__init__(parent)
        self.title("System Prompt Editor")
        self.parent_app = parent

        self.processor = processor
        self.selected_file: Optional[str] = None
        self.display_name_to_file_map: Dict[str, str] = {}

        self._create_widgets()
        self._populate_file_list()

        self.smart_geometry(min_width=800, min_height=600)

    def _create_widgets(self):
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- File List ---
        list_frame = ttk.LabelFrame(main_pane, text="System Prompts", padding=5)
        main_pane.add(list_frame, weight=1)

        self.file_listbox = tk.Listbox(list_frame, font=self.parent_app.default_font)
        self.file_listbox.pack(fill=tk.BOTH, expand=True)
        self.file_listbox.bind("<<ListboxSelect>>", self._on_file_select)

        # --- Editor ---
        editor_frame = ttk.LabelFrame(main_pane, text="Edit Prompt", padding=5)
        main_pane.add(editor_frame, weight=3)

        self.editor_text = tk.Text(editor_frame, wrap=tk.WORD, font=self.parent_app.fixed_font, undo=True, state=tk.DISABLED, exportselection=False)
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
        self.display_name_to_file_map.clear()
        
        # The processor now returns a list of file paths relative to the system prompt dir
        for filepath in self.processor.get_system_prompt_files():
            display_name = ""
            if filepath == 'enhancement.txt':
                display_name = "Enhancement"
            elif filepath.startswith('variations/') and filepath.endswith('.json'):
                try:
                    # To get the display name, we need to load the JSON content
                    full_path = os.path.join(config.get_system_prompt_dir(), filepath)
                    with open(full_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        name = data.get('name', os.path.basename(filepath).replace('.json', ''))
                        display_name = f"{name} (Variation)"
                except Exception as e:
                    print(f"Warning: Could not load variation name from {filepath}: {e}")
                    display_name = f"{os.path.basename(filepath)} (Variation)"
            
            if display_name:
                self.file_listbox.insert(tk.END, display_name)
                self.display_name_to_file_map[display_name] = filepath

    def _on_file_select(self, event=None):
        selected_indices = self.file_listbox.curselection()
        if not selected_indices: return

        display_name = self.file_listbox.get(selected_indices[0])
        self.selected_file = self.display_name_to_file_map.get(display_name)

        if not self.selected_file:
            custom_dialogs.show_error(self, "Error", "Could not map display name to a file.")
            return

        try:
            content = self.processor.load_system_prompt_content(self.selected_file)
            self.editor_text.config(state=tk.NORMAL)
            self.editor_text.delete("1.0", tk.END)
            self.editor_text.insert("1.0", content)
            self.save_button.config(state=tk.NORMAL)
            self.reset_button.config(state=tk.NORMAL)
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not load system prompt:\n{e}")

    def _save_file(self):
        if not self.selected_file: return
        content = self.editor_text.get("1.0", "end-1c")
        try:
            self.processor.save_system_prompt_content(self.selected_file, content)
            custom_dialogs.show_info(self, "Success", f"Saved '{self.selected_file}' successfully.")
        except Exception as e:
            custom_dialogs.show_error(self, "Save Error", f"Could not save system prompt:\n{e}")

    def _reset_to_default(self):
        if not self.selected_file: return
        if not custom_dialogs.ask_yes_no(self, "Confirm Reset", f"Are you sure you want to reset '{self.selected_file}' to its default content?"):
            return
        
        default_content = self.processor.get_default_system_prompt(self.selected_file)
        self.editor_text.delete("1.0", tk.END)
        self.editor_text.insert("1.0", default_content)
        self._save_file()