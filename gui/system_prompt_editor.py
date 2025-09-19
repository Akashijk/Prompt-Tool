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

        self._create_widgets()
        self._populate_file_list()

        self.smart_geometry(min_width=800, min_height=600)

    def _create_widgets(self):
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- File List ---
        list_frame = ttk.LabelFrame(main_pane, text="System Prompts", padding=5)
        main_pane.add(list_frame, weight=1)

        # --- File action buttons ---
        file_actions_frame = ttk.Frame(list_frame)
        file_actions_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.new_button = ttk.Button(file_actions_frame, text="New...", command=self._create_new_prompt)
        self.new_button.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        self.rename_button = ttk.Button(file_actions_frame, text="Rename...", command=self._rename_prompt, state=tk.DISABLED)
        self.rename_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        self.set_default_button = ttk.Button(file_actions_frame, text="Set as Default", command=self._set_as_default_negative_prompt, state=tk.DISABLED)
        self.set_default_button.pack(side=tk.LEFT, expand=True, fill=tk.X)

        self.archive_button = ttk.Button(file_actions_frame, text="Archive", command=self._archive_prompt, state=tk.DISABLED)
        self.archive_button.pack(side=tk.LEFT, expand=True, fill=tk.X)

        self.file_tree = ttk.Treeview(list_frame, show="tree", selectmode="browse")
        self.file_tree.pack(fill=tk.BOTH, expand=True)
        self.file_tree.bind("<<TreeviewSelect>>", self._on_file_select)

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

    def _clear_editor(self):
        """Clears the editor pane and disables all action buttons."""
        self.selected_file = None
        self.editor_text.config(state=tk.NORMAL)
        self.editor_text.delete("1.0", tk.END)
        self.editor_text.config(state=tk.DISABLED)
        self.save_button.config(state=tk.DISABLED)
        self.reset_button.config(state=tk.DISABLED)
        self.rename_button.config(state=tk.DISABLED)
        self.set_default_button.config(state=tk.DISABLED)
        self.archive_button.config(state=tk.DISABLED)

    def _populate_file_list(self):
        for i in self.file_tree.get_children():
            self.file_tree.delete(i)
        
        files_by_category = self.processor.get_system_prompt_files()

        for category, files in files_by_category.items():
            category_id = self.file_tree.insert("", "end", text=category, open=True)
            for file_info in files:
                # Store the relative path in the 'values' tuple
                self.file_tree.insert(category_id, "end", text=file_info['display_name'], values=(file_info['relative_path'],))

    def _on_file_select(self, event=None):
        selection = self.file_tree.selection()
        if not selection:
            self._clear_editor()
            return
        
        item_id = selection[0]
        # Ignore clicks on category headers which have no parent
        if not self.file_tree.parent(item_id):
            self._clear_editor()
            return

        self.selected_file = self.file_tree.item(item_id, "values")[0]

        if not self.selected_file:
            custom_dialogs.show_error(self, "Error", "Could not map display name to a file.")
            return

        try:
            content = self.processor.load_system_prompt_content(self.selected_file)
            self.editor_text.config(state=tk.NORMAL)
            self.editor_text.delete("1.0", tk.END)
            self.editor_text.insert("1.0", content)
            self.save_button.config(state=tk.NORMAL)
            
            # A file is considered a "default" if it has default content defined.
            # User-created files will not have default content.
            has_default = bool(self.processor.get_default_system_prompt(self.selected_file))
            
            # The top button is always "Archive"
            self.archive_button.config(text="Archive", command=self._archive_prompt)
            
            # Enable/disable buttons based on whether it's a default file.
            # Default files can be reset, but not renamed or archived.
            # User-created files can be renamed and archived, but not reset.
            self.rename_button.config(state=tk.DISABLED if has_default else tk.NORMAL)
            self.archive_button.config(state=tk.DISABLED if has_default else tk.NORMAL)
            self.reset_button.config(state=tk.NORMAL if has_default else tk.DISABLED)

            # --- NEW: Handle "Set as Default" button state ---
            is_negative_prompt = self.selected_file.startswith('negative_prompts/')
            self.set_default_button.config(state=tk.NORMAL if is_negative_prompt else tk.DISABLED)
            if is_negative_prompt:
                key = os.path.splitext(os.path.basename(self.selected_file))[0]
                if key == config.DEFAULT_NEGATIVE_PROMPT_KEY:
                    self.set_default_button.config(text="Remove Default")
                else:
                    self.set_default_button.config(text="Set as Default")

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

    def _set_as_default_negative_prompt(self):
        """Sets the selected negative prompt as the default, or removes the default."""
        if not self.selected_file or not self.selected_file.startswith('negative_prompts/'):
            return

        key = os.path.splitext(os.path.basename(self.selected_file))[0]
        
        # If it's already the default, we're un-setting it.
        if key == config.DEFAULT_NEGATIVE_PROMPT_KEY:
            new_default_key = "" # Set to empty to remove the default
            message = f"'{key}' is no longer the default negative prompt."
        else:
            new_default_key = key
            message = f"'{key}' is now the default negative prompt."

        try:
            from core.config import update_and_save_settings
            update_and_save_settings({'default_negative_prompt_key': new_default_key})
            self.processor.clear_default_negative_prompt_cache() # Invalidate the cache
            self._populate_file_list() # Refresh the list to show the new (Default) tag
            custom_dialogs.show_info(self, "Default Set", message)
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not set default negative prompt:\n{e}")

    def _create_new_prompt(self):
        dialog = custom_dialogs._CreateSystemPromptDialog(self)
        if not dialog.result:
            return

        prompt_type = dialog.result['type'] # 'variation' or 'enhancement'
        filename = dialog.result['filename']

        try:
            self.processor.create_system_prompt(filename, prompt_type, content_data=None)
            self._populate_file_list()
            
            # Find and select the new file in the tree
            if prompt_type == 'variation':
                new_relative_path = os.path.join('variations', f"{filename}.json")
            elif prompt_type == 'negative_prompt':
                new_relative_path = os.path.join('negative_prompts', f"{filename}.txt")
            else:
                new_relative_path = f"{filename}.txt"
            
            for category_id in self.file_tree.get_children():
                for item_id in self.file_tree.get_children(category_id):
                    if self.file_tree.item(item_id, "values")[0] == new_relative_path:
                        self.file_tree.selection_set(item_id)
                        self.file_tree.see(item_id)
                        return

            custom_dialogs.show_info(self, "Success", f"Created new system prompt '{filename}'.")
        except Exception as e:
            custom_dialogs.show_error(self, "Creation Error", f"Could not create system prompt:\n{e}")

    def _archive_prompt(self):
        if not self.selected_file:
            return

        if not custom_dialogs.ask_yes_no(self, "Confirm Archive", f"Are you sure you want to archive '{self.selected_file}'?"):
            return
        
        try:
            self.processor.archive_system_prompt(self.selected_file)
            self._clear_editor()
            self._populate_file_list()
            custom_dialogs.show_info(self, "Success", f"Archived '{self.selected_file}'.")
        except Exception as e:
            custom_dialogs.show_error(self, "Archive Error", f"Could not archive system prompt:\n{e}")

    def _rename_prompt(self):
        if not self.selected_file:
            return

        old_basename, ext = os.path.splitext(os.path.basename(self.selected_file))
        
        new_basename = custom_dialogs.ask_string(self, "Rename Prompt", "Enter new name (without extension):", initialvalue=old_basename, validator=custom_dialogs.is_valid_filename_component)
        if not new_basename or new_basename.strip() == old_basename:
            return
        
        new_filename = f"{new_basename.strip()}{ext}"

        try:
            self.processor.rename_system_prompt(self.selected_file, new_filename)
            
            # After renaming, the old self.selected_file is invalid.
            # We need to find the new relative path to re-select it.
            new_relative_path = os.path.join(os.path.dirname(self.selected_file), new_filename)
            
            self._populate_file_list()
            
            # Find and select the renamed file in the tree
            for category_id in self.file_tree.get_children():
                for item_id in self.file_tree.get_children(category_id):
                    if self.file_tree.item(item_id, "values")[0] == new_relative_path:
                        self.file_tree.selection_set(item_id)
                        self.file_tree.see(item_id)
                        return
            custom_dialogs.show_info(self, "Success", f"Renamed to '{new_filename}'.")
        except Exception as e:
            custom_dialogs.show_error(self, "Rename Error", f"Could not rename system prompt:\n{e}")