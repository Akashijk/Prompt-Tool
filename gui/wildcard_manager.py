"""A pop-up window to manage wildcard files."""

import json
import os
import queue
from collections import Counter
import tkinter as tk
from tkinter import ttk
import threading
import sys
from typing import Optional, Callable, List, Dict, Any, TYPE_CHECKING
from core.prompt_processor import PromptProcessor
from core.config import config
from . import custom_dialogs
from .wildcard_editor_widget import WildcardEditor
from .common import TextContextMenu, SmartWindowMixin


if TYPE_CHECKING:
    from .gui_app import GUIApp

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

        self._create_widgets()
        self._populate_wildcard_list()

        if initial_file:
            self.select_and_load_file(initial_file)

        self.smart_geometry(min_width=800, min_height=600)

    def close(self):
        """Safely close the window, cancelling any pending after() jobs."""
        if self.suggestion_after_id:
            self.after_cancel(self.suggestion_after_id)
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
        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        self.wildcard_listbox.bind(right_click_event, self._show_file_list_context_menu)

        ttk.Button(list_frame, text="New Wildcard File", command=self._create_new_wildcard_file).pack(pady=(5, 0), fill=tk.X, side=tk.TOP)
        ttk.Button(list_frame, text="Find Unused Files", command=self._find_unused_wildcards).pack(pady=(5, 0), fill=tk.X, side=tk.TOP)
        h_pane.add(list_frame, weight=1)

        self.editor_container = ttk.LabelFrame(h_pane, text="No file selected", padding=5)
        h_pane.add(self.editor_container, weight=3)

        self.editor_notebook = ttk.Notebook(self.editor_container)
        self.editor_notebook.pack(fill=tk.BOTH, expand=True)

        # Structured Editor Tab
        self.structured_editor_frame = ttk.Frame(self.editor_notebook)
        self.structured_editor = WildcardEditor(self.structured_editor_frame, self.processor, suggestion_callback=self.suggest_choices_with_ai)
        self.structured_editor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.editor_notebook.add(self.structured_editor_frame, text="Structured Editor")

        # Raw Text Editor Tab
        self.raw_text_frame = ttk.Frame(self.editor_notebook)
        self.raw_text_editor = tk.Text(self.raw_text_frame, wrap=tk.WORD, font=self.parent_app.fixed_font, undo=True)
        TextContextMenu(self.raw_text_editor)
        self.raw_text_editor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.editor_notebook.add(self.raw_text_frame, text="Raw Text Editor")

        # Buttons below the notebook
        button_frame = ttk.Frame(self.editor_container)
        button_frame.pack(fill=tk.X, pady=5)
        self.save_button = ttk.Button(button_frame, text="Save Changes", command=self._save_wildcard_file, style="Accent.TButton", state=tk.DISABLED)
        self.save_button.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.find_duplicates_button = ttk.Button(button_frame, text="Find Duplicates", command=self._find_duplicates, state=tk.DISABLED)
        self.find_duplicates_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))
        self.sort_button = ttk.Button(button_frame, text="Sort Choices", command=self._sort_choices, state=tk.DISABLED)
        self.sort_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))
        self.brainstorm_button = ttk.Button(button_frame, text="Brainstorm with AI", command=self._brainstorm_with_ai, state=tk.DISABLED)
        self.brainstorm_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5,0))
        self.archive_button = ttk.Button(button_frame, text="Archive", command=self._archive_selected_wildcard, state=tk.DISABLED)
        self.archive_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

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

    def _on_wildcard_file_select(self, event=None):
        selected_indices = self.wildcard_listbox.curselection()
        if not selected_indices: return
        self.structured_editor.clear_highlights()
        
        self.selected_wildcard_file = self.wildcard_listbox.get(selected_indices[0])
        self.editor_container.config(text=f"Editing: {self.selected_wildcard_file}")
        
        try:
            # Always load the raw content from disk to get the latest version
            raw_content = self.processor.load_wildcard_content(self.selected_wildcard_file)
            
            # Handle .txt files by converting them to the JSON structure in memory
            if self.selected_wildcard_file.endswith('.txt'):
                lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
                wildcard_data = {
                    "description": f"Legacy wildcard from {self.selected_wildcard_file}. Saving will convert to .json.",
                    "choices": lines
                }
                self._display_valid_wildcard(wildcard_data)
            else: # Handle .json files
                # Try to parse it as JSON
                try:
                    wildcard_data = json.loads(raw_content)
                    self._display_valid_wildcard(wildcard_data)
                except json.JSONDecodeError:
                    # If parsing fails, it's an invalid file. Show the raw editor.
                    self._display_invalid_wildcard(raw_content)

        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not load wildcard file:\n{e}")
            self.save_button.config(state=tk.DISABLED)
            self.structured_editor.suggest_button.config(state=tk.DISABLED)
            self.archive_button.config(state=tk.DISABLED)
            self.brainstorm_button.config(state=tk.DISABLED)

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
        self.archive_button.config(state=tk.NORMAL)
        self.brainstorm_button.config(state=tk.NORMAL)
        self.find_duplicates_button.config(state=tk.NORMAL)
        self.sort_button.config(state=tk.NORMAL)

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
        self.editor_notebook.select(self.raw_text_frame) # Switch to raw editor
        
        self.save_button.config(state=tk.NORMAL)
        self.archive_button.config(state=tk.NORMAL)
        self.brainstorm_button.config(state=tk.DISABLED)
        self.find_duplicates_button.config(state=tk.DISABLED)
        self.sort_button.config(state=tk.DISABLED)

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
        """Moves the selected wildcard file to an archive folder."""
        if not self.selected_wildcard_file: return

        if not custom_dialogs.ask_yes_no(self, "Confirm Archive", f"Are you sure you want to archive '{self.selected_wildcard_file}'?\n\nThis will move the file to a subfolder named 'archive'."):
            return

        try:
            self.processor.archive_wildcard(self.selected_wildcard_file)
            self._clear_editor_view()
            self._populate_wildcard_list()
            self.update_callback()
        except Exception as e:
            custom_dialogs.show_error(self, "Archive Error", f"Could not archive file:\n{e}")

    def _clear_editor_view(self):
        """Resets the editor pane to its default 'no file selected' state."""
        self.selected_wildcard_file = None
        self.structured_editor.clear_highlights()
        self.wildcard_listbox.selection_clear(0, tk.END)
        self.structured_editor.set_data({})
        self.raw_text_editor.delete("1.0", tk.END)
        self.save_button.config(state=tk.DISABLED)
        self.archive_button.config(state=tk.DISABLED)
        self.brainstorm_button.config(state=tk.DISABLED)
        self.find_duplicates_button.config(state=tk.DISABLED)
        self.sort_button.config(state=tk.DISABLED)
        self.structured_editor.suggest_button.config(state=tk.DISABLED)
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

            if custom_dialogs.ask_yes_no(self, "Remove Duplicates?", message):
                # Get the full data structure to modify it
                data = self.structured_editor.get_data()
                original_choices = data.get('choices', [])
                
                cleaned_choices = []
                seen_values = set()
                
                for choice in original_choices:
                    value = choice.get('value') if isinstance(choice, dict) else choice
                    if value not in seen_values:
                        cleaned_choices.append(choice)
                        seen_values.add(value)
                
                num_removed = len(original_choices) - len(cleaned_choices)
                data['choices'] = cleaned_choices
                
                # Clear highlights and reload the editor with the cleaned data
                self.structured_editor.set_data(data)
                
                # Enable the save button to persist the change.
                self.save_button.config(state=tk.NORMAL)

                custom_dialogs.show_info(self, "Duplicates Removed", f"Removed {num_removed} duplicate choice(s).\n\nPlease save the file to apply the changes.")

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
        """Scans all files to find wildcards that are never included or used in templates."""
        try:
            used_wildcards = self.processor.get_all_used_wildcards()
            all_wildcard_files = self.processor.get_all_wildcard_files_mode_agnostic()

            # Convert filenames (e.g., 'my_wildcard.json') to basenames ('my_wildcard')
            all_wildcard_basenames = {os.path.splitext(f)[0] for f in all_wildcard_files}

            unused_wildcards = sorted(list(all_wildcard_basenames - used_wildcards))

            if not unused_wildcards:
                custom_dialogs.show_info(self, "Find Unused Wildcards", "No unused wildcard files found. All wildcards are referenced in at least one template or another wildcard's 'includes' clause.")
            else:
                message = "The following wildcard files appear to be unused:\n\n"
                message += "\n".join([f"- {wc}" for wc in unused_wildcards])
                message += "\n\nNote: This check may not detect wildcards used in complex, indirect ways. Please review before deleting."
                custom_dialogs.show_info(self, "Unused Wildcards Found", message)
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"An error occurred while checking for unused wildcards:\n{e}")

    def _create_file_list_context_menu(self):
        """Creates the right-click context menu for the wildcard file list."""
        self.file_list_context_menu = tk.Menu(self.wildcard_listbox, tearoff=0)
        self.file_list_context_menu.add_command(label="Merge Selected Files...", command=self._merge_wildcard_files)
        self.file_list_context_menu.add_command(label="Brainstorm with AI", command=self._brainstorm_with_ai)
        self.file_list_context_menu.add_separator()
        self.file_list_context_menu.add_command(label="Archive", command=self._archive_selected_wildcard)

    def _show_file_list_context_menu(self, event):
        """Shows the context menu for the file list."""
        # First, handle the selection logic to prevent macOS from clearing it.
        index = self.wildcard_listbox.nearest(event.y)
        if index != -1:
            # If the right-clicked item is not already part of the selection,
            # then clear the old selection and select only the clicked item.
            if not self.wildcard_listbox.selection_includes(index):
                self.wildcard_listbox.selection_clear(0, tk.END)
                self.wildcard_listbox.selection_set(index)
                self.wildcard_listbox.activate(index)

        # Now, configure the menu based on the (now correct) selection.
        selection_count = len(self.wildcard_listbox.curselection())

        if selection_count == 1:
            self._on_wildcard_file_select()
        elif selection_count > 1:
            self._clear_editor_view()
        
        self.file_list_context_menu.entryconfig("Merge Selected Files...", state=tk.NORMAL if selection_count == 2 else tk.DISABLED)
        self.file_list_context_menu.entryconfig("Brainstorm with AI", state=tk.NORMAL if selection_count == 1 else tk.DISABLED)
        self.file_list_context_menu.entryconfig("Archive", state=tk.NORMAL if selection_count > 0 else tk.DISABLED)

        self.file_list_context_menu.tk_popup(event.x_root, event.y_root)
        # Stop the event from propagating to the default handler, preserving multi-selection
        return "break"

    def _merge_wildcard_files(self):
        """Merges two selected wildcard files into a new file."""
        selection_indices = self.wildcard_listbox.curselection()
        if len(selection_indices) != 2:
            return

        file1 = self.wildcard_listbox.get(selection_indices[0])
        file2 = self.wildcard_listbox.get(selection_indices[1])

        basename1, _ = os.path.splitext(file1)
        basename2, _ = os.path.splitext(file2)

        # Get the parsed data from the processor's cache
        data1 = self.processor.template_engine.wildcards.get(basename1, {})
        data2 = self.processor.template_engine.wildcards.get(basename2, {})

        # --- Merge Logic ---
        desc1 = data1.get('description', f'Content from {file1}')
        desc2 = data2.get('description', f'Content from {file2}')
        merged_desc = f"Merged from '{basename1}' and '{basename2}'.\n\n--- {basename1} ---\n{desc1}\n\n--- {basename2} ---\n{desc2}"

        choices1 = data1.get('choices', [])
        choices2 = data2.get('choices', [])
        seen_values = set()
        merged_choices = []
        for choice in choices1 + choices2:
            value = choice if isinstance(choice, str) else choice.get('value')
            if value not in seen_values:
                merged_choices.append(choice)
                seen_values.add(value)

        includes1 = data1.get('includes', [])
        includes2 = data2.get('includes', [])
        merged_includes = sorted(list(set(includes1) | set(includes2)))

        merged_data = {"description": merged_desc, "choices": merged_choices, "includes": merged_includes}

        new_filename_base = custom_dialogs.ask_string(self, "New Merged Wildcard", "Enter a name for the new merged wildcard file:", initialvalue=f"{basename1}_{basename2}")
        if not new_filename_base: return

        new_filename = f"{new_filename_base}.json"
        new_content = json.dumps(merged_data, indent=2)

        try:
            is_nsfw_only = False
            if config.workflow == 'nsfw':
                is_nsfw_only = custom_dialogs.ask_yes_no(self, "Wildcard Scope", "Save this merged file as NSFW-only?")
            
            self.processor.save_wildcard_content(new_filename, new_content, is_nsfw_only)
            custom_dialogs.show_info(self, "Success", f"Successfully merged files into '{new_filename}'.")

            if custom_dialogs.ask_yes_no(self, "Archive Originals?", f"Would you like to archive the original files?\n- {file1}\n- {file2}"):
                self.processor.archive_wildcard(file1)
                self.processor.archive_wildcard(file2)

            self._populate_wildcard_list()
            self.update_callback()
            self.select_and_load_file(new_filename)
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not save merged wildcard file:\n{e}")