"""A pop-up window to manage wildcard files."""

import json
import os
import re
import copy
import queue
from collections import Counter
import tkinter as tk
from tkinter import ttk
import threading
import sys
from typing import Optional, Callable, List, Dict, Any, TYPE_CHECKING, Tuple
from core.prompt_processor import PromptProcessor
from core.config import config
from . import custom_dialogs
from .wildcard_editor_widget import WildcardEditor
from .common import TextContextMenu, SmartWindowMixin


if TYPE_CHECKING:
    from .gui_app import GUIApp

class _FindReplaceDialog(custom_dialogs._CustomDialog):
    """A dialog for finding and replacing text in wildcard choices."""
    def __init__(self, parent, selection_exists: bool):
        super().__init__(parent, "Find and Replace in Choices")

        self.find_var = tk.StringVar()
        self.replace_var = tk.StringVar()
        self.case_sensitive_var = tk.BooleanVar(value=False)
        self.whole_word_var = tk.BooleanVar(value=False)
        self.selected_only_var = tk.BooleanVar(value=False)

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Find
        ttk.Label(main_frame, text="Find what:").grid(row=0, column=0, sticky='w', pady=2)
        self.find_entry = ttk.Entry(main_frame, textvariable=self.find_var, width=40)
        self.find_entry.grid(row=0, column=1, sticky='ew', pady=2)
        self.find_entry.focus_set()

        # Replace
        ttk.Label(main_frame, text="Replace with:").grid(row=1, column=0, sticky='w', pady=2)
        ttk.Entry(main_frame, textvariable=self.replace_var).grid(row=1, column=1, sticky='ew', pady=2)
        
        main_frame.columnconfigure(1, weight=1)

        # Options
        options_frame = ttk.Frame(main_frame)
        options_frame.grid(row=2, column=0, columnspan=2, sticky='w', pady=(10, 0))
        ttk.Checkbutton(options_frame, text="Case sensitive", variable=self.case_sensitive_var).pack(side=tk.LEFT)
        ttk.Checkbutton(options_frame, text="Match whole word", variable=self.whole_word_var).pack(side=tk.LEFT, padx=10)
        self.selected_only_check = ttk.Checkbutton(options_frame, text="In selection only", variable=self.selected_only_var)
        self.selected_only_check.pack(side=tk.LEFT, padx=10)
        if not selection_exists:
            self.selected_only_check.config(state=tk.DISABLED)

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=(20, 0), sticky='e')
        ok_button = ttk.Button(button_frame, text="Replace All", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5, 0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self._center_window()
        self.wait_window(self)

    def _on_ok(self, event=None):
        find_text = self.find_var.get()
        if not find_text:
            self.result = None
        else:
            self.result = {
                "find": find_text,
                "replace": self.replace_var.get(),
                "case": self.case_sensitive_var.get(),
                "whole": self.whole_word_var.get(),
                "selected_only": self.selected_only_var.get()
            }
        self.destroy()

class WildcardManagerWindow(tk.Toplevel, SmartWindowMixin):
    """A pop-up window to manage wildcard files."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor, update_callback: Callable, initial_file: Optional[str] = None, initial_content: Optional[str] = None):
        super().__init__(parent)
        self.title("Wildcard Manager")
        
        self.processor = processor
        self.update_callback = update_callback
        self.selected_wildcard_file: Optional[str] = None
        self.all_wildcard_files: List[str] = []
        self.parent_app = parent
        self.wildcard_list_var = tk.StringVar()
        self.initial_content = initial_content
        self.suggestion_queue = queue.Queue()
        self.suggestion_after_id: Optional[str] = None
        self.refinement_queue = queue.Queue()
        self.refinement_after_id: Optional[str] = None
        self.find_unused_queue = queue.Queue()
        self.find_unused_after_id: Optional[str] = None
        self.validation_queue = queue.Queue()
        self.validation_after_id: Optional[str] = None

        self._create_widgets()
        self._populate_wildcard_list()

        if initial_file:
            self.select_and_load_file(initial_file)

        self.smart_geometry(min_width=800, min_height=600)

    def close(self):
        """Safely close the window, cancelling any pending after() jobs."""
        if self.suggestion_after_id:
            self.after_cancel(self.suggestion_after_id)
        if self.refinement_after_id:
            self.after_cancel(self.refinement_after_id)
        if self.find_unused_after_id:
            self.after_cancel(self.find_unused_after_id)
        if self.validation_after_id:
            self.after_cancel(self.validation_after_id)
        self.destroy()

    def update_theme(self):
        """Updates the theme for its child widgets."""
        self.structured_editor.update_theme()

    def _create_widgets(self):
        h_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        h_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        list_frame = ttk.LabelFrame(h_pane, text="Wildcard Files", padding=5)

        # --- Search Bar ---
        search_frame = ttk.Frame(list_frame)
        search_frame.pack(fill=tk.X, pady=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._filter_wildcard_list)
        ttk.Entry(search_frame, textvariable=self.search_var, font=self.parent_app.small_font).pack(fill=tk.X)

        list_scroll_frame = ttk.Frame(list_frame)
        list_scroll_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_scroll_frame, orient=tk.VERTICAL)
        self.wildcard_listbox = tk.Listbox(list_scroll_frame, font=self.parent_app.default_font, yscrollcommand=scrollbar.set, listvariable=self.wildcard_list_var, selectmode=tk.EXTENDED)
        scrollbar.config(command=self.wildcard_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.wildcard_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)

        # Add context menu for the file list
        self._create_file_list_context_menu()
        if sys.platform == "darwin":
            # On macOS, we bind to Button-2 (right-click) and Control-Button-1 (for trackpads/one-button mice).
            # Using ButtonPress is important to catch the event before the default selection-clearing behavior.
            self.wildcard_listbox.bind("<ButtonPress-2>", self._show_file_list_context_menu)
            self.wildcard_listbox.bind("<Control-Button-1>", self._show_file_list_context_menu)
        else:
            # On Windows/Linux, Button-3 is the standard right-click.
            self.wildcard_listbox.bind("<Button-3>", self._show_file_list_context_menu)

        button_container = ttk.Frame(list_frame)
        button_container.pack(pady=(5, 0), fill=tk.X, side=tk.TOP)
        ttk.Button(button_container, text="New Wildcard File", command=self._create_new_wildcard_file).pack(fill=tk.X)
        self.merge_button = ttk.Button(button_container, text="Merge Selected (2+)", command=self._merge_wildcard_files, state=tk.DISABLED)
        self.merge_button.pack(fill=tk.X, pady=(5, 0))
        self.archive_button = ttk.Button(button_container, text="Archive Selected", command=self._archive_selected_wildcard, state=tk.DISABLED)
        self.archive_button.pack(fill=tk.X, pady=(5, 0))
        self.find_unused_button = ttk.Button(button_container, text="Find Unused Files", command=self._find_unused_wildcards)
        self.find_unused_button.pack(fill=tk.X, pady=(5, 0))
        self.validate_button = ttk.Button(button_container, text="Validate All Files", command=self._validate_all_wildcards)
        self.validate_button.pack(fill=tk.X, pady=(5, 0))
        h_pane.add(list_frame, weight=1)

        self.editor_container = ttk.LabelFrame(h_pane, text="No file selected", padding=5)
        h_pane.add(self.editor_container, weight=3)

        self.editor_notebook = ttk.Notebook(self.editor_container)
        self.editor_notebook.pack(fill=tk.BOTH, expand=True)

        # Structured Editor Tab
        self.structured_editor_frame = ttk.Frame(self.editor_notebook)
        self.structured_editor = WildcardEditor(self.structured_editor_frame, self.processor, suggestion_callback=self.suggest_choices_with_ai, refinement_callback=self.refine_choices_with_ai)
        self.structured_editor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.editor_notebook.add(self.structured_editor_frame, text="Structured Editor")

        # Raw Text Editor Tab
        self.raw_text_frame = ttk.Frame(self.editor_notebook)
        self.raw_text_editor = tk.Text(self.raw_text_frame, wrap=tk.WORD, font=self.parent_app.fixed_font, undo=True, exportselection=False)
        TextContextMenu(self.raw_text_editor)
        self.raw_text_editor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.editor_notebook.add(self.raw_text_frame, text="Raw Text Editor")

        # Buttons below the notebook
        action_frame = ttk.Frame(self.editor_container, padding=(0, 5, 0, 0))
        action_frame.pack(fill=tk.X, pady=5)

        self.save_button = ttk.Button(action_frame, text="Save Changes", command=self._save_wildcard_file, style="Accent.TButton", state=tk.DISABLED)
        self.save_button.pack(side=tk.LEFT, expand=True, fill=tk.X)

        # Create a single "Tools" Menubutton for a more compact layout
        self.tools_menubutton = ttk.Menubutton(action_frame, text="Tools", state=tk.DISABLED)
        self.tools_menubutton.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5,0))
        tools_menu = tk.Menu(self.tools_menubutton, tearoff=0)
        self.tools_menubutton['menu'] = tools_menu
        tools_menu.add_command(label="Find and Replace...", command=self._find_and_replace)
        tools_menu.add_command(label="Find Exact Duplicates", command=self._find_duplicates)
        tools_menu.add_command(label="Find Similar...", command=self._find_similar_choices)
        tools_menu.add_command(label="Sort Choices", command=self._sort_choices)
        tools_menu.add_separator()
        tools_menu.add_command(label="Brainstorm with AI", command=self._brainstorm_with_ai)

    def _populate_wildcard_list(self):
        """Populates the list of wildcard files."""
        self.all_wildcard_files = self.processor.get_wildcard_files()
        self.wildcard_list_var.set(self.all_wildcard_files)
        # Clear search to ensure the full list is displayed initially
        self.search_var.set("")

    def _filter_wildcard_list(self, *args):
        """Filters the wildcard listbox based on the search term."""
        search_term = self.search_var.get().lower()
        
        filtered_list = [f for f in self.all_wildcard_files if search_term in f.lower()]
        self.wildcard_list_var.set(filtered_list)

    def _update_merge_button_state(self, num_selected: int):
        """Updates the state and text of the merge button based on selection count."""
        if num_selected >= 2:
            self.merge_button.config(state=tk.NORMAL, text=f"Merge Selected ({num_selected})")
        else:
            self.merge_button.config(state=tk.DISABLED, text="Merge Selected (2+)")

    def _load_selected_file_into_editor(self, index: int):
        """Loads the content of the selected file into the editor pane, preferring the in-memory cache."""
        self.structured_editor.clear_highlights()
        self.selected_wildcard_file = self.wildcard_listbox.get(index)
        self.editor_container.config(text=f"Editing: {self.selected_wildcard_file}")
        
        basename, _ = os.path.splitext(self.selected_wildcard_file)
        
        try:
            # Prefer the fast, already-parsed in-memory cache from the template engine.
            wildcard_data = self.processor.template_engine.wildcards.get(basename)
            
            if wildcard_data:
                # If we got data, it's already parsed. Display it directly.
                self._display_valid_wildcard(wildcard_data)
            else:
                # This case means the file might be invalid JSON and failed to load into the cache.
                # The safest fallback is to load the raw content from disk to allow the user to see and fix it.
                raw_content = self.processor.load_wildcard_content(self.selected_wildcard_file)
                self._parse_and_display_wildcard_content(raw_content)
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not load wildcard file:\n{e}")
            self._clear_editor_view(preserve_selection=True)

    def _parse_and_display_wildcard_content(self, raw_content: str):
        """Parses raw file content and displays it in the appropriate editor state."""
        if self.selected_wildcard_file.endswith('.txt'):
            lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
            wildcard_data = {
                "description": f"Legacy wildcard from {self.selected_wildcard_file}. Saving will convert to .json.",
                "choices": lines
            }
            self._display_valid_wildcard(wildcard_data)
        else:
            try:
                wildcard_data = json.loads(raw_content)
                self._display_valid_wildcard(wildcard_data)
            except json.JSONDecodeError:
                self._display_invalid_wildcard(raw_content)

    def _on_wildcard_file_select(self, event=None):
        selected_indices = self.wildcard_listbox.curselection()
        num_selected = len(selected_indices)
        self._update_merge_button_state(num_selected)
        self.archive_button.config(state=tk.NORMAL if num_selected > 0 else tk.DISABLED)

        if num_selected == 1:
            self._load_selected_file_into_editor(selected_indices[0])
        else:
            # Multiple or no selection: clear the editor
            self._clear_editor_view(preserve_selection=True)

    def _display_valid_wildcard(self, wildcard_data: Dict[str, Any]):
        """Updates the editor UI for a successfully loaded wildcard."""
        self.structured_editor.clear_highlights()
        self.structured_editor.set_data(wildcard_data)
        
        pretty_content = json.dumps(wildcard_data, indent=2)
        self.raw_text_editor.delete("1.0", tk.END)
        self.raw_text_editor.insert("1.0", pretty_content)
        self.editor_notebook.select(self.structured_editor_frame)
        
        self.structured_editor.suggest_button.config(state=tk.NORMAL)
        self.save_button.config(state=tk.NORMAL)
        self.tools_menubutton.config(state=tk.NORMAL)

    def _display_invalid_wildcard(self, raw_content: str):
        """
        Updates the editor UI for a file that failed to load from memory,
        likely due to a JSON parsing error.
        """
        error_message = (
            f"Could not load '{self.selected_wildcard_file}' from memory. "
            "This usually means the file contains invalid JSON or has read permission issues.\n\n"
            "The raw file content is shown below for you to fix. "
            "Please correct the syntax and save."
        )
        custom_dialogs.show_warning(self, "File Load Warning", error_message)

        # Load the raw content into the raw editor so the user can fix it
        self.structured_editor.clear_highlights()
        self.raw_text_editor.delete("1.0", tk.END)
        self.raw_text_editor.insert("1.0", raw_content)
        self.structured_editor.set_data({}) # Clear structured editor
        self.structured_editor.suggest_button.config(state=tk.DISABLED)
        self.structured_editor.refine_button.config(state=tk.DISABLED)
        self.editor_notebook.select(self.raw_text_frame) # Switch to raw editor
        
        self.save_button.config(state=tk.NORMAL)
        self.tools_menubutton.config(state=tk.DISABLED)

    def _save_wildcard_file(self):
        if not self.selected_wildcard_file: return

        content = ""
        try:
            # Get content from the currently active tab
            active_tab_index = self.editor_notebook.index(self.editor_notebook.select())
            if active_tab_index == 0: # Structured Editor
                data = self.structured_editor.get_data()
                content = json.dumps(data, indent=2)
            else: # Raw Text Editor
                content = self.raw_text_editor.get("1.0", "end-1c")
            
            # Validate that it's proper JSON before saving
            json.loads(content)

            # The processor will handle saving and migration (.txt -> .json)
            self.processor.save_wildcard_content(self.selected_wildcard_file, content)

            # The filename might have changed from .txt to .json
            basename, _ = os.path.splitext(self.selected_wildcard_file)
            new_filename = f"{basename}.json"
            custom_dialogs.show_info(self, "Success", f"Successfully saved {new_filename}")

            # If the file was new, or if its name changed (migration), refresh the list
            if new_filename != self.selected_wildcard_file:
                self.selected_wildcard_file = new_filename # Update the tracked filename
                self._populate_wildcard_list()
                self.select_and_load_file(self.selected_wildcard_file)
            else:
                # If the name didn't change, just reload the content to ensure it's up-to-date
                self._on_wildcard_file_select()

            self.update_callback(modified_file=self.selected_wildcard_file)
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not save wildcard file. Please ensure it is valid JSON.\n\n{e}")

    def _create_new_wildcard_file(self):
        filename = custom_dialogs.ask_string(self, "New Wildcard File", "Enter new wildcard filename:")
        if not filename: return
        if not filename.endswith('.json'): filename += '.json'
        try:
            # Create a default JSON structure for the new file
            default_content = '{\n  "description": "A new wildcard file.",\n  "choices": [\n    "item 1",\n    "item 2"\n  ]\n}'
            is_nsfw_only = False
            if config.workflow == 'nsfw':
                is_nsfw_only = custom_dialogs.ask_yes_no(
                    self,
                    "Wildcard Scope",
                    "Save this as an NSFW-only wildcard?\n\n"
                    "(Choosing 'No' will save it to the shared folder, making it available in both SFW and NSFW modes.)"
                )

            # Create an empty file by saving empty content, respecting the user's choice
            self.processor.save_wildcard_content(filename, default_content, is_nsfw_only=is_nsfw_only)
            self._populate_wildcard_list()
            self.update_callback()
            self.select_and_load_file(filename, initial_content=default_content)
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not create wildcard file:\n{e}")

    def _archive_selected_wildcard(self):
        """Moves the selected wildcard file(s) to an archive folder."""
        selected_indices = self.wildcard_listbox.curselection()
        if not selected_indices:
            custom_dialogs.show_warning(self, "No Selection", "No wildcard files selected to archive.")
            return

        files_to_archive = [self.wildcard_listbox.get(i) for i in selected_indices]
        num_files = len(files_to_archive)
        
        message = f"Are you sure you want to archive the selected {num_files} file(s)?\n\n"
        message += "\n".join([f"- {f}" for f in files_to_archive[:5]])
        if num_files > 5:
            message += f"\n...and {num_files - 5} more."
        
        if not custom_dialogs.ask_yes_no(self, "Confirm Archive", message):
            return

        try:
            for filename in files_to_archive:
                self.processor.archive_wildcard(filename)
            
            self._clear_editor_view()
            self._populate_wildcard_list()
            self.update_callback()
            custom_dialogs.show_info(self, "Archive Complete", f"Successfully archived {num_files} file(s).")
        except Exception as e:
            custom_dialogs.show_error(self, "Archive Error", f"Could not archive file:\n{e}")

    def _clear_editor_view(self, preserve_selection: bool = False):
        """Resets the editor pane to its default 'no file selected' state."""
        self.selected_wildcard_file = None
        self.structured_editor.clear_highlights()
        if not preserve_selection:
            self.wildcard_listbox.selection_clear(0, tk.END)
        self.structured_editor.set_data({})
        self.raw_text_editor.delete("1.0", tk.END)
        self.save_button.config(state=tk.DISABLED)
        self.tools_menubutton.config(state=tk.DISABLED)
        self.structured_editor.suggest_button.config(state=tk.DISABLED)
        self.structured_editor.refine_button.config(state=tk.DISABLED)
        self.editor_container.config(text="No file selected")

    def _brainstorm_with_ai(self):
        """Sends the current wildcard content to the brainstorming window."""
        if not self.selected_wildcard_file: return
        
        content = ""
        active_tab_index = self.editor_notebook.index(self.editor_notebook.select())
        if active_tab_index == 0: # Structured Editor
            data = self.structured_editor.get_data()
            content = json.dumps(data, indent=2)
        else: # Raw Text Editor
            content = self.raw_text_editor.get("1.0", "end-1c")
            
        self.parent_app._brainstorm_with_content("wildcard", self.selected_wildcard_file, content)

    def select_and_load_file(self, filename: str, initial_content: Optional[str] = None):
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
            self._clear_editor_view()
            self.selected_wildcard_file = filename
            self.editor_container.config(text=f"New File: {self.selected_wildcard_file}")
            
            # Use the passed initial content, or the one from init, or nothing.
            content_to_load = initial_content or self.initial_content
            if content_to_load:
                try:
                    parsed_data = json.loads(content_to_load)
                    self.structured_editor.set_data(parsed_data)
                    self.raw_text_editor.insert("1.0", json.dumps(parsed_data, indent=2))
                except json.JSONDecodeError:
                    self.raw_text_editor.insert("1.0", content_to_load)
                    self.editor_notebook.select(self.raw_text_frame)
            else:
                self.structured_editor.set_data({})
                self.raw_text_editor.delete("1.0", tk.END)

            self.save_button.config(state=tk.NORMAL)

    def suggest_choices_with_ai(self, current_data: Dict[str, Any]):
        """Starts the AI suggestion process in a background thread."""
        self.structured_editor.suggest_button.config(state=tk.DISABLED, text="Suggesting...")
        current_wildcard_file = self.selected_wildcard_file
        
        def task():
            try:
                model = self.parent_app.enhancement_model_var.get()
                if not model or "model" in model.lower():
                    raise Exception("Please select a valid Ollama model in the main window.")
                
                new_choices = self.processor.suggest_wildcard_choices(current_data, model, current_wildcard_file)
                self.suggestion_queue.put({'success': True, 'choices': new_choices})
            except Exception as e:
                self.suggestion_queue.put({'success': False, 'error': str(e)})
        
        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.suggestion_after_id = self.after(100, self._check_suggestion_queue)

    def _check_suggestion_queue(self):
        """Checks for AI suggestions and updates the UI."""
        try:
            result = self.suggestion_queue.get_nowait()
            self.structured_editor.suggest_button.config(state=tk.NORMAL, text="Suggest Choices (AI)")
            
            if result['success']:
                self.structured_editor.add_suggested_choices(result.get('choices', []))
                custom_dialogs.show_info(self, "Suggestions Added", f"{len(result.get('choices', []))} new choices have been added to the editor.")
            else:
                custom_dialogs.show_error(self, "Suggestion Error", f"An error occurred while generating suggestions:\n{result['error']}")
        except queue.Empty:
            self.suggestion_after_id = self.after(100, self._check_suggestion_queue)

    def refine_choices_with_ai(self, current_data: Dict[str, Any]):
        """Starts the AI refinement process in a background thread."""
        self.structured_editor.refine_button.config(state=tk.DISABLED, text="Refining...")
        current_wildcard_file = self.selected_wildcard_file
        
        def task():
            try:
                model = self.parent_app.enhancement_model_var.get()
                if not model or "model" in model.lower():
                    raise Exception("Please select a valid Ollama model in the main window.")
                
                refined_choices = self.processor.refine_wildcard_choices(current_data, model, current_wildcard_file)
                self.refinement_queue.put({'success': True, 'choices': refined_choices})
            except Exception as e:
                self.refinement_queue.put({'success': False, 'error': str(e)})
        
        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.refinement_after_id = self.after(100, self._check_refinement_queue)

    def _check_refinement_queue(self):
        """Checks for AI refinement results and updates the UI."""
        try:
            result = self.refinement_queue.get_nowait()
            self.structured_editor.refine_button.config(state=tk.NORMAL, text="Refine Choices (AI)")
            
            if result['success']:
                self.structured_editor.update_with_refined_choices(result.get('choices', []))
                custom_dialogs.show_info(self, "Refinement Complete", "The choices have been refined by the AI.\n\nPlease review and save the file.")
                self.save_button.config(state=tk.NORMAL)
            else:
                custom_dialogs.show_error(self, "Refinement Error", f"An error occurred while refining choices:\n{result['error']}")
        except queue.Empty:
            self.refinement_after_id = self.after(100, self._check_refinement_queue)

    def _find_duplicates(self):
        """Finds, highlights, and reports duplicate 'value' entries in the current wildcard file."""
        if not self.selected_wildcard_file:
            return

        # Always clear previous highlights first
        self.structured_editor.clear_highlights()

        # Use the fast in-memory map from the editor for performance
        iid_map = self.structured_editor.iid_to_choice_map
        if not iid_map:
            custom_dialogs.show_info(self, "Find Duplicates", "No choices found in the file to check.")
            return

        # Map values to a list of their iids
        value_to_iids = {}
        for iid, choice in iid_map.items():
            # Get the 'value' from the choice object (which can be a string or dict)
            value = choice if isinstance(choice, str) else choice.get('value')
            if value is not None:
                if value not in value_to_iids:
                    value_to_iids[value] = []
                value_to_iids[value].append(iid)

        # Find duplicates and collect all iids to be highlighted
        duplicates = {}
        iids_to_highlight = []
        for value, iids in value_to_iids.items():
            if len(iids) > 1:
                duplicates[value] = len(iids)
                iids_to_highlight.extend(iids)

        if not duplicates:
            custom_dialogs.show_info(self, "Find Duplicates", "No duplicate choices found in this file.")
        else:
            # Highlight the rows first
            self.structured_editor.highlight_duplicates(iids_to_highlight)

            message = "The following duplicate choices were found and have been highlighted:\n\n"
            for value, count in sorted(duplicates.items()):
                display_value = (value[:75] + '...') if len(value) > 75 else value
                message += f'\n- "{display_value}" (found {count} times)'
            
            message += "\n\nWould you like to automatically remove these duplicates? (The first occurrence of each will be kept)"

            # Unbind the selection event to prevent the dialog from clearing the editor on focus loss.
            self.wildcard_listbox.unbind("<<ListboxSelect>>")
            try:
                should_remove = custom_dialogs.ask_yes_no(self, "Remove Duplicates?", message)
            finally:
                self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)

            if should_remove:
                iids_to_delete = []
                seen_values = set()
                
                # Iterate through tree items in display order to decide which to keep
                for iid in self.structured_editor.tree.get_children():
                    # Get the choice object from the editor's fast map
                    choice = self.structured_editor.iid_to_choice_map.get(iid)
                    if not choice:
                        continue
                    
                    value = choice if isinstance(choice, str) else choice.get('value')
                    
                    if value in seen_values:
                        # This is a duplicate, mark for deletion
                        iids_to_delete.append(iid)
                    else:
                        # First time seeing this value, keep it
                        if value is not None:
                            seen_values.add(value)
                
                num_removed = len(iids_to_delete)
                if num_removed > 0:
                    # Perform the deletion directly on the tree and the map
                    for iid in iids_to_delete:
                        self.structured_editor.tree.delete(iid)
                        if iid in self.structured_editor.iid_to_choice_map:
                            del self.structured_editor.iid_to_choice_map[iid]
                    
                    # Clear highlights as they are now invalid
                    self.structured_editor.clear_highlights()
                    
                    # Enable the save button to persist the change.
                    self.save_button.config(state=tk.NORMAL)

                    custom_dialogs.show_info(self, "Duplicates Removed", f"Removed {num_removed} duplicate choice(s).\n\nPlease save the file to apply the changes.")

    def _find_similar_choices(self):
        """Finds choices that are similar but not identical using fuzzy string matching."""
        if not self.selected_wildcard_file:
            return

        if len(self.structured_editor.iid_to_choice_map) < 2:
            custom_dialogs.show_info(self, "Find Similar", "Not enough choices to compare.")
            return

        try:
            from thefuzz import fuzz
        except ImportError:
            custom_dialogs.show_error(self, "Missing Library", "The 'thefuzz' library is required for this feature.\n\nPlease install it by running:\npip install thefuzz")
            return

        # Unbind the selection event to prevent the dialog from clearing the editor on focus loss.
        self.wildcard_listbox.unbind("<<ListboxSelect>>")
        try:
            threshold_str = custom_dialogs.ask_string(
                self,
                "Similarity Threshold",
                "Enter a similarity threshold (1-100).\nHigher values mean more similar.",
                initialvalue="85"
            )
        finally:
            # Always re-bind the event to restore normal functionality
            self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)

        if not threshold_str: return
        try:
            threshold = int(threshold_str)
            if not (1 <= threshold <= 100):
                raise ValueError
        except (ValueError, TypeError):
            custom_dialogs.show_error(self, "Invalid Input", "Please enter a whole number between 1 and 100.")
            return

        self.structured_editor.clear_highlights()
        
        # Now that the dialog is closed and the editor is safe, get the choices.
        choices = []
        for iid, choice_obj in self.structured_editor.iid_to_choice_map.items():
            value = choice_obj if isinstance(choice_obj, str) else choice_obj.get('value')
            if value:
                choices.append({'iid': iid, 'value': str(value)})

        # Use a disjoint set union (DSU) data structure to efficiently group similar items.
        parent = {item['iid']: item['iid'] for item in choices}
        def find(iid):
            if parent[iid] == iid: return iid
            parent[iid] = find(parent[iid])
            return parent[iid]

        def union(iid1, iid2):
            root1, root2 = find(iid1), find(iid2)
            if root1 != root2: parent[root2] = root1

        for i in range(len(choices)):
            for j in range(i + 1, len(choices)):
                item1, item2 = choices[i], choices[j]
                if fuzz.token_sort_ratio(item1['value'], item2['value']) >= threshold:
                    union(item1['iid'], item2['iid'])

        groups = {}
        for item in choices:
            root = find(item['iid'])
            if root not in groups: groups[root] = []
            groups[root].append(item)
        
        similar_groups = [group for group in groups.values() if len(group) > 1]

        if not similar_groups:
            custom_dialogs.show_info(self, "Find Similar", f"No similar choices found with a threshold of {threshold}%.")
            return

        iids_to_highlight = [item['iid'] for group in similar_groups for item in group]
        self.structured_editor.highlight_duplicates(iids_to_highlight)

        message = f"Found {len(similar_groups)} group(s) of similar choices (threshold: {threshold}%).\n\nThey have been highlighted for your review. Please check them manually."
        message += "\n\n--- Similar Groups (Preview) ---"
        for i, group in enumerate(similar_groups[:10]):
            message += "\n" + "\n".join([f"- \"{item['value'][:75]}\"" for item in group])
        if len(similar_groups) > 10: message += f"\n...and {len(similar_groups) - 10} more groups."
        custom_dialogs.show_info(self, "Similar Choices Found", message)

    def _find_and_replace(self):
        """Finds and replaces text across all choice values in the current file."""
        if not self.selected_wildcard_file:
            return

        selection = self.structured_editor.tree.selection()
        dialog = _FindReplaceDialog(self, selection_exists=bool(selection))
        if not dialog.result:
            return

        params = dialog.result
        find_text = params['find']
        replace_text = params['replace']
        
        # Prepare regex pattern
        pattern = re.escape(find_text)
        if params['whole']:
            pattern = r'\b' + pattern + r'\b'
        
        flags = 0 if params['case'] else re.IGNORECASE

        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            custom_dialogs.show_error(self, "Invalid Regex", f"The search term could not be compiled into a valid regular expression:\n{e}")
            return

        replacements_made = 0
        choices_affected = 0

        if params['selected_only'] and selection:
            # --- Logic for selected items only ---
            for iid in selection:
                choice_obj = self.structured_editor.iid_to_choice_map.get(iid)
                if not choice_obj: continue

                is_dict = isinstance(choice_obj, dict)
                original_value = choice_obj.get('value') if is_dict else choice_obj

                if not isinstance(original_value, str): continue

                new_value, num_subs = regex.subn(replace_text, original_value)

                if num_subs > 0:
                    replacements_made += num_subs
                    choices_affected += 1
                    
                    new_choice_obj = copy.deepcopy(choice_obj)
                    if is_dict:
                        new_choice_obj['value'] = new_value
                    else:
                        new_choice_obj = new_value
                    
                    self.structured_editor.iid_to_choice_map[iid] = new_choice_obj
                    self.structured_editor.tree.set(iid, 'value', new_value)
        else:
            # --- Logic for entire file ---
            current_data = self.structured_editor.get_data()
            updated_choices = []
            
            for choice in current_data.get('choices', []):
                is_dict = isinstance(choice, dict)
                original_value = choice.get('value') if is_dict else choice
                
                if not isinstance(original_value, str):
                    updated_choices.append(choice)
                    continue

                new_value, num_subs = regex.subn(replace_text, original_value)

                if num_subs > 0:
                    replacements_made += num_subs
                    choices_affected += 1
                    if is_dict:
                        choice['value'] = new_value
                    else:
                        choice = new_value
                updated_choices.append(choice)
            
            if replacements_made > 0:
                current_data['choices'] = updated_choices
                self.structured_editor.set_data(current_data)

        if replacements_made > 0:
            self.save_button.config(state=tk.NORMAL)
            custom_dialogs.show_info(self, "Replace Complete", f"Made {replacements_made} replacement(s) across {choices_affected} choice(s).\n\nPlease save the file to apply the changes.")
        else:
            custom_dialogs.show_info(self, "Find and Replace", f"No occurrences of '{find_text}' were found.")

    def _sort_choices(self):
        """Sorts the choices in the structured editor alphabetically by value."""
        if not self.selected_wildcard_file:
            return

        data = self.structured_editor.get_data()
        choices = data.get('choices', [])

        if not choices:
            custom_dialogs.show_info(self, "Sort Choices", "No choices to sort.")
            return

        # Define a key function for case-insensitive sorting
        def sort_key(choice):
            value = choice.get('value') if isinstance(choice, dict) else choice
            return value.lower() if isinstance(value, str) else ""

        # Sort the choices list
        choices.sort(key=sort_key)
        
        data['choices'] = choices
        self.structured_editor.set_data(data)
        
        self.save_button.config(state=tk.NORMAL)
        custom_dialogs.show_info(self, "Sort Complete", "Choices have been sorted alphabetically.\n\nPlease save the file to apply the changes.")

    def _find_unused_wildcards(self):
        """Starts the 'find unused wildcards' process in a background thread."""
        self.find_unused_button.config(state=tk.DISABLED, text="Scanning...")

        def task():
            try:
                used_wildcards = self.processor.get_all_used_wildcards()
                all_wildcard_files = self.processor.get_all_wildcard_files_mode_agnostic()
                all_wildcard_basenames = {os.path.splitext(f)[0] for f in all_wildcard_files}
                unused_wildcards = sorted(list(all_wildcard_basenames - used_wildcards))
                self.find_unused_queue.put({'success': True, 'unused': unused_wildcards})
            except Exception as e:
                self.find_unused_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.find_unused_after_id = self.after(100, self._check_find_unused_queue)

    def _check_find_unused_queue(self):
        """Checks for results from the 'find unused' task and updates the UI."""
        try:
            result = self.find_unused_queue.get_nowait()
            self.find_unused_button.config(state=tk.NORMAL, text="Find Unused Files")

            if result['success']:
                unused_wildcards = result['unused']
                if not unused_wildcards:
                    custom_dialogs.show_info(self, "Find Unused Wildcards", "No unused wildcard files found. All wildcards are referenced in at least one template or another wildcard's 'includes' clause.")
                else:
                    message = "The following wildcard files appear to be unused:\n\n" + "\n".join([f"- {wc}" for wc in unused_wildcards]) + "\n\nNote: This check may not detect wildcards used in complex, indirect ways. Please review before deleting."
                    custom_dialogs.show_info(self, "Unused Wildcards Found", message)
            else:
                custom_dialogs.show_error(self, "Error", f"An error occurred while checking for unused wildcards:\n{result['error']}")
        except queue.Empty:
            self.find_unused_after_id = self.after(100, self._check_find_unused_queue)

    def _validate_all_wildcards(self):
        """Starts the wildcard validation process in a background thread."""
        self.validate_button.config(state=tk.DISABLED, text="Validating...")

        def task():
            try:
                errors = self.processor.validate_all_wildcards()
                self.validation_queue.put({'success': True, 'errors': errors})
            except Exception as e:
                self.validation_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.validation_after_id = self.after(100, self._check_validation_queue)

    def _check_validation_queue(self):
        """Checks for results from the validation task and updates the UI."""
        try:
            result = self.validation_queue.get_nowait()
            self.validate_button.config(state=tk.NORMAL, text="Validate All Files")

            if result['success']:
                errors = result['errors']
                if not errors:
                    custom_dialogs.show_info(self, "Validation Complete", "No validation errors found in 'requires' clauses.")
                else:
                    self._show_validation_errors(errors)
            else:
                custom_dialogs.show_error(self, "Error", f"An error occurred during validation:\n{result['error']}")
        except queue.Empty:
            self.validation_after_id = self.after(100, self._check_validation_queue)

    def _show_validation_errors(self, errors: List[Dict[str, Any]]):
        """Displays validation errors in an interactive Toplevel window."""
        error_window = tk.Toplevel(self)
        error_window.title("Wildcard Validation Errors")
        error_window.transient(self)
        error_window.grab_set()
        error_window.geometry("800x500")

        main_frame = ttk.Frame(error_window, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text="The following issues were found. Double-click an error to jump to the file.", wraplength=780).pack(anchor='w', pady=(0, 10))

        # --- Treeview for errors ---
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ('file', 'choice', 'message')
        tree = ttk.Treeview(text_frame, columns=columns, show='headings')
        tree.heading('file', text='File', command=lambda: self._sort_treeview_column(tree, 'file', False))
        tree.heading('choice', text='Problematic Choice', command=lambda: self._sort_treeview_column(tree, 'choice', False))
        tree.heading('message', text='Error Details', command=lambda: self._sort_treeview_column(tree, 'message', False))
        tree.column('file', width=150, stretch=False)
        tree.column('choice', width=200, stretch=False)
        tree.column('message', width=400)
        
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        iid_map = {}
        for error in errors:
            values = (error.get('source_file', ''), error.get('choice_value', ''), error.get('message', ''))
            iid = tree.insert('', tk.END, values=values)
            iid_map[iid] = error

        def _on_error_double_click(event):
            iid = tree.identify_row(event.y)
            if not iid: return
            error = iid_map.get(iid)
            if not error: return
            
            self.select_and_load_file(error['source_file'])
            self.structured_editor.highlight_choice_by_value(error['choice_value'])
            self.lift() # Bring the main manager window to the front

        def _add_missing_wildcard_value(error_data: Dict[str, Any]):
            details = error_data.get('details')
            if not details or details.get('type') != 'missing_value': return

            target_file = details['target_wildcard']
            missing_value = details['missing_value']

            try:
                # Load the target file's content
                target_data = self._load_and_parse_wildcard_file(target_file)
                if target_data is None:
                    custom_dialogs.show_error(error_window, "Error", f"Could not load target file '{target_file}' to add value.")
                    return
                
                # Add the new choice
                if 'choices' not in target_data:
                    target_data['choices'] = []
                target_data['choices'].append(missing_value)

                # Save the modified file
                new_content = json.dumps(target_data, indent=2)
                self.processor.save_wildcard_content(target_file, new_content)

                custom_dialogs.show_info(error_window, "Success", f"Added '{missing_value}' to '{target_file}'.\n\nPlease re-run validation.")
                error_window.destroy() # Close the error window as it's now stale
            except Exception as e:
                custom_dialogs.show_error(error_window, "Error", f"Failed to add missing value:\n{e}")

        context_menu = tk.Menu(tree, tearoff=0)
        def _show_context_menu(event):
            iid = tree.identify_row(event.y)
            if not iid: return
            tree.selection_set(iid)
            
            error = iid_map.get(iid)
            if not error: return

            context_menu.delete(0, tk.END)
            context_menu.add_command(label="Go to Error", command=lambda: _on_error_double_click(event))
            
            details = error.get('details')
            if details and details.get('type') == 'missing_value':
                context_menu.add_separator()
                label = f"Add '{details['missing_value']}' to '{details['target_wildcard']}'"
                context_menu.add_command(label=label, command=lambda e=error: _add_missing_wildcard_value(e))
            
            context_menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Double-1>", _on_error_double_click)
        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        tree.bind(right_click_event, _show_context_menu)

        ttk.Button(main_frame, text="Close", command=error_window.destroy).pack(pady=(10, 0))
        
    def _sort_treeview_column(self, tv, col, reverse):
        """Sort treeview contents when a column is clicked on."""
        l = [(tv.set(k, col), k) for k in tv.get_children('')]
        try:
            # Try to sort numerically if possible
            l.sort(key=lambda t: float(t[0]), reverse=reverse)
        except ValueError:
            # Fallback to case-insensitive string sort
            l.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for index, (val, k) in enumerate(l):
            tv.move(k, '', index)

        # reverse sort next time
        tv.heading(col, command=lambda: self._sort_treeview_column(tv, col, not reverse))


    def _load_and_parse_wildcard_file(self, filename: str) -> Optional[Dict[str, Any]]:
        """Loads and parses a single wildcard file, preferring the in-memory cache."""
        basename, _ = os.path.splitext(filename)
        
        # Prefer the fast, already-parsed in-memory cache.
        wildcard_data = self.processor.template_engine.wildcards.get(basename)
        if wildcard_data:
            return wildcard_data

        # Fallback to disk read if not in cache (e.g., parse error on startup)
        try:
            raw_content = self.processor.load_wildcard_content(filename)
            if filename.endswith('.txt'):
                lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
                return {"description": f"Content from legacy file {filename}.", "choices": lines}
            else: # .json
                return json.loads(raw_content)
        except Exception as e:
            custom_dialogs.show_error(self, "File Load Error", f"Could not load or parse '{filename}':\n{e}")
            return None

    def _create_file_list_context_menu(self):
        """Creates the right-click context menu for the wildcard file list."""
        self.file_list_context_menu = tk.Menu(self.wildcard_listbox, tearoff=0)
        self.file_list_context_menu.add_command(label="Brainstorm with AI", command=self._brainstorm_with_ai)
        self.file_list_context_menu.add_separator()
        self.file_list_context_menu.add_command(label="Archive", command=self._archive_selected_wildcard)

    def _show_file_list_context_menu(self, event):
        """
        Handles the right-click event on the file list, preserving selection on macOS.
        """
        # Identify the item under the cursor.
        index = self.wildcard_listbox.nearest(event.y)

        # If the click is on an actual item and that item is not already selected,
        # then we perform the standard "select only this item" behavior.
        # This mimics native OS context menu behavior.
        if index != -1 and not self.wildcard_listbox.selection_includes(index):
            self.wildcard_listbox.selection_clear(0, tk.END)
            self.wildcard_listbox.selection_set(index)
            self.wildcard_listbox.activate(index)

        # We now have the correct selection. We can configure and post the menu.
        # We use self.after(1, ...) to delay the popup slightly. This is a common
        # technique on macOS to prevent the default binding from interfering
        # with our custom selection logic.
        self.after(1, lambda: self._popup_context_menu(event))

        # Crucially, we return "break" to stop the event propagation immediately.
        # This should prevent the default listbox binding that clears the selection.
        return "break"

    def _popup_context_menu(self, event):
        """Configures and displays the context menu. Called via self.after()."""
        selection_count = len(self.wildcard_listbox.curselection())

        # Update the editor view based on the selection count
        if selection_count == 1:
            # A single selection should always trigger the file load.
            self._on_wildcard_file_select()
        elif selection_count > 1:
            # A multi-selection should clear the editor pane.
            self._clear_editor_view(preserve_selection=True)

        # Configure menu items based on the final selection
        self.file_list_context_menu.entryconfig("Brainstorm with AI", state=tk.NORMAL if selection_count == 1 else tk.DISABLED)
        self.file_list_context_menu.entryconfig("Archive", state=tk.NORMAL if selection_count > 0 else tk.DISABLED)

        self.file_list_context_menu.tk_popup(event.x_root, event.y_root)

    def _perform_merge(self, all_data: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
        """Contains the core logic for merging data from multiple wildcard files."""
        basenames = [os.path.splitext(name)[0] for name, _ in all_data]

        # --- Merge Descriptions ---
        merged_desc_parts = []
        for file_name, data in all_data:
            basename, _ = os.path.splitext(file_name)
            desc = data.get('description', f'Content from {file_name}')
            merged_desc_parts.append(f"--- {basename} ---\n{desc}")
        merged_desc = f"Merged from {len(basenames)} files: {', '.join(basenames)}.\n\n" + "\n\n".join(merged_desc_parts)

        # --- Merge Choices (uniquely) ---
        seen_values = set()
        merged_choices = []
        for _, data in all_data:
            for choice in data.get('choices', []):
                value = choice if isinstance(choice, str) else choice.get('value')
                if value is not None and value not in seen_values:
                    merged_choices.append(choice)
                    seen_values.add(value)

        # --- Merge Includes (intelligently) ---
        all_includes = set()
        for _, data in all_data:
            includes = data.get('includes')
            if not includes:
                continue
            
            if isinstance(includes, list):
                all_includes.update(includes)
            elif isinstance(includes, str):
                # Find wildcards in both __wildcard__ and [wildcard] format
                found_wc = re.findall(r'__([a-zA-Z0-9_.\s-]+?)__', includes)
                all_includes.update(found_wc)
                found_wc_bracket = re.findall(r'\[([a-zA-Z0-9_.\s-]+?)\]', includes)
                all_includes.update(found_wc_bracket)

        merged_data = {"description": merged_desc, "choices": merged_choices}
        if all_includes:
            merged_data['includes'] = sorted(list(all_includes))
        
        return merged_data

    def _save_and_finalize_merge(self, merged_data: Dict[str, Any], original_files: List[str]):
        """Handles user dialogs, saving, and UI updates for a merge operation."""
        basenames = [os.path.splitext(name)[0] for name in original_files]
        suggested_name = f"merged_{basenames[0]}_{basenames[-1]}" if len(basenames) > 1 else f"merged_{basenames[0]}"
        new_filename_base = custom_dialogs.ask_string(self, "New Merged Wildcard", "Enter a name for the new merged wildcard file:", initialvalue=suggested_name)
        if not new_filename_base: return

        new_filename = f"{new_filename_base}.json"
        new_content = json.dumps(merged_data, indent=2)

        try:
            is_nsfw_only = False
            if config.workflow == 'nsfw':
                is_nsfw_only = custom_dialogs.ask_yes_no(self, "Wildcard Scope", "Save this merged file as an NSFW-only wildcard?\n\n(Choosing 'No' will save it to the shared folder.)")

            self.processor.save_wildcard_content(new_filename, new_content, is_nsfw_only=is_nsfw_only)
            custom_dialogs.show_info(self, "Success", f"Successfully merged {len(original_files)} files into '{new_filename}'.")

            if custom_dialogs.ask_yes_no(self, "Archive Originals?", f"Would you like to archive the {len(original_files)} original files?\n- " + "\n- ".join(original_files)):
                for file_name in original_files:
                    self.processor.archive_wildcard(file_name)

            self._populate_wildcard_list()
            self.update_callback()
            self.select_and_load_file(new_filename)
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not save merged wildcard file:\n{e}")

    def _merge_wildcard_files(self):
        """Coordinates the process of merging selected wildcard files."""
        selection_indices = self.wildcard_listbox.curselection()
        if len(selection_indices) < 2:
            return

        file_names = [self.wildcard_listbox.get(i) for i in selection_indices]
        all_data = []
        for file_name in file_names:
            data = self._load_and_parse_wildcard_file(file_name)
            if data is None:
                return # Error was already shown
            all_data.append((file_name, data))

        merged_data = self._perform_merge(all_data)
        self._save_and_finalize_merge(merged_data, file_names)