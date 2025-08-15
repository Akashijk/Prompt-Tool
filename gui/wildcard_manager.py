"""A pop-up window to manage wildcard files."""

import json
import os
import re
import copy
import queue
import threading
import difflib
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

class _DependencyViewerWindow(custom_dialogs._CustomDialog):
    """A modal dialog to display the wildcard dependency graph."""
    def __init__(self, parent, processor: PromptProcessor, manager_window: 'WildcardManagerWindow'):
        super().__init__(parent, "Wildcard Dependency Viewer")
        self.processor = processor
        self.manager_window = manager_window
        self.graph = self.processor.get_wildcard_dependency_graph()
        self.all_wildcards = sorted(list(self.graph.keys()))

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Search bar
        search_frame = ttk.Frame(main_frame)
        search_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(search_frame, text="Filter:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._filter_tree)
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Treeview
        tree_container = ttk.Frame(main_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_container, columns=('dependencies', 'dependents'), show='tree headings')
        self.tree.heading('#0', text='Wildcard')
        self.tree.heading('dependencies', text='Uses (Dependencies)')
        self.tree.heading('dependents', text='Used By (Dependents)')
        self.tree.column('dependencies', width=150, anchor='center')
        self.tree.column('dependents', width=150, anchor='center')

        scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.bind("<Double-1>", self._on_double_click)
        
        self._populate_tree()

        # Close button
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(button_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)
        
        self.geometry("800x600")
        self._center_window()
        self.wait_window(self)

    def _populate_tree(self):
        for wc_name in self.all_wildcards:
            data = self.graph.get(wc_name, {'dependencies': [], 'dependents': []})
            deps_count = len(data['dependencies'])
            dependents_count = len(data['dependents'])
            
            parent_iid = self.tree.insert('', 'end', text=wc_name, values=(deps_count, dependents_count), open=False)

            if deps_count > 0:
                uses_iid = self.tree.insert(parent_iid, 'end', text=f"Uses ({deps_count})")
                for dep in data['dependencies']:
                    self.tree.insert(uses_iid, 'end', text=dep)
            
            if dependents_count > 0:
                used_by_iid = self.tree.insert(parent_iid, 'end', text=f"Used By ({dependents_count})")
                for dep in data['dependents']:
                    self.tree.insert(used_by_iid, 'end', text=dep)

    def _filter_tree(self, *args):
        search_term = self.search_var.get().lower()
        for iid in self.tree.get_children():
            if search_term in self.tree.item(iid, 'text').lower():
                self.tree.move(iid, '', self.tree.index(iid)) # Make it visible
                self.tree.item(iid, open=True if search_term else False) # Auto-expand on search
            else:
                self.tree.detach(iid)

    def _on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid: return

        wildcard_name = self.tree.item(iid, 'text')
        
        # Ignore category nodes
        if wildcard_name.startswith("Uses (") or wildcard_name.startswith("Used By ("):
            return

        filename_to_open = f"{wildcard_name}.json"
        
        if filename_to_open in self.manager_window.all_wildcard_files:
            self.manager_window.select_and_load_file(filename_to_open)
            self.manager_window.lift()
            self.destroy()
        else:
            custom_dialogs.show_warning(self, "File Not Found", f"The wildcard file '{filename_to_open}' could not be found in the current workflow.")

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
        self.dialog_is_open = False
        self.validation_queue = queue.Queue()
        self.validation_after_id: Optional[str] = None
        self.fix_queue = queue.Queue()
        self.fix_after_id: Optional[str] = None
        self.refactor_queue = queue.Queue()
        self.refactor_after_id: Optional[str] = None
        self.pending_value_refactors: List[Tuple[str, str, str]] = []
        self.json_fix_queue = queue.Queue()
        self.json_fix_after_id: Optional[str] = None

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
        if self.fix_after_id:
            self.after_cancel(self.fix_after_id)
        if self.refactor_after_id:
            self.after_cancel(self.refactor_after_id)
        if self.json_fix_after_id:
            self.after_cancel(self.json_fix_after_id)
        self.destroy()

    def _on_editor_focus_in(self, event=None):
        """Unbinds the listbox selection event when an editor widget gains focus to prevent clearing the view."""
        self.wildcard_listbox.unbind("<<ListboxSelect>>")

    def _on_editor_focus_out(self, event=None):
        """Re-binds the listbox selection event when an editor widget loses focus."""
        # Do not re-bind if a modal dialog is expected to be open.
        if self.dialog_is_open:
            return

        # Check if the window still exists before trying to bind.
        if self.winfo_exists():
            self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)

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
        self.dependencies_button = ttk.Button(button_container, text="View Dependencies", command=self._view_dependencies)
        self.dependencies_button.pack(fill=tk.X, pady=(5, 0))
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
        # Bind focus events to prevent the editor from clearing when interacting with its components.
        self.structured_editor.description_entry.bind("<FocusIn>", self._on_editor_focus_in)
        self.structured_editor.description_entry.bind("<FocusOut>", self._on_editor_focus_out)
        self.structured_editor.tree.bind("<FocusIn>", self._on_editor_focus_in)
        self.structured_editor.tree.bind("<FocusOut>", self._on_editor_focus_out)
        self.structured_editor.includes_text.bind("<FocusIn>", self._on_editor_focus_in)
        self.structured_editor.includes_text.bind("<FocusOut>", self._on_editor_focus_out)
        self.structured_editor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.editor_notebook.add(self.structured_editor_frame, text="Structured Editor")

        # Raw Text Editor Tab
        self.raw_text_frame = ttk.Frame(self.editor_notebook)
        self.raw_text_editor = tk.Text(self.raw_text_frame, wrap=tk.WORD, font=self.parent_app.fixed_font, undo=True, exportselection=False)
        # Also bind focus events to the raw text editor.
        self.raw_text_editor.bind("<FocusIn>", self._on_editor_focus_in)
        self.raw_text_editor.bind("<FocusOut>", self._on_editor_focus_out)
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
        tools_menu.add_separator()
        tools_menu.add_command(label="Remove All 'requires'...", command=lambda: self._remove_all_keys('requires'))
        tools_menu.add_command(label="Remove All 'includes'...", command=lambda: self._remove_all_keys('includes'))
        tools_menu.add_separator()
        tools_menu.add_command(label="Brainstorm with AI", command=self._brainstorm_with_ai)

    def _populate_wildcard_list(self):
        """Populates the list of wildcard files."""
        self.all_wildcard_files = self.processor.get_wildcard_files()
        self.wildcard_list_var.set(self.all_wildcard_files)
        # Force the UI to update the listbox from the variable before we try to select an item in it.
        self.update_idletasks()
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
        # Work on a copy to avoid modifying the in-memory cache directly
        display_data = copy.deepcopy(wildcard_data)

        # --- Auto-sort choices upon loading ---
        choices = display_data.get('choices', [])
        if choices:
            def sort_key(choice):
                # Handles both simple strings and complex dicts for sorting
                value = choice.get('value') if isinstance(choice, dict) else choice
                return str(value).lower() if value is not None else ""
            choices.sort(key=sort_key)
            display_data['choices'] = choices
        # --- End auto-sort ---

        self.structured_editor.clear_highlights()
        self.structured_editor.set_data(display_data)
        
        pretty_content = json.dumps(display_data, indent=2)
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
        if not self.selected_wildcard_file:
            return

        content = ""
        is_raw_editor = self.editor_notebook.index(self.editor_notebook.select()) == 1

        if is_raw_editor:
            content = self.raw_text_editor.get("1.0", "end-1c")
            try:
                # Validate JSON from raw editor
                json.loads(content)
            except json.JSONDecodeError as e:
                # If invalid, show the AI fix dialog and stop the save process.
                self._handle_invalid_json_save(content, str(e))
                return  # Stop here. The user will have to click save again after fixing.
        else:  # Structured Editor
            data = self.structured_editor.get_data()
            content = json.dumps(data, indent=2)

        # If we reach here, the content is valid JSON.
        try:
            # The processor will handle saving and migration (.txt -> .json)
            self.processor.save_wildcard_content(self.selected_wildcard_file, content)

            # --- Handle pending value refactors ---
            if self.pending_value_refactors:
                # Make a copy to iterate over, as the background tasks might take a while
                refactors_to_process = self.pending_value_refactors[:]
                self.pending_value_refactors.clear()

                for basename, old_value, new_value in refactors_to_process:
                    if custom_dialogs.ask_yes_no(
                        self,
                        "Refactor Value Change?",
                        f"You changed the value '{old_value}' to '{new_value}' in '{basename}'.\n\n"
                        f"Would you like to scan all other wildcards and update any 'requires' clauses that depend on the old value?"
                    ):
                        def on_value_refactor_complete(modified_count, ov=old_value):
                            custom_dialogs.show_info(self, "Refactor Complete", f"Updated {modified_count} file(s) that required the value '{ov}'.")
                            self.update_callback()

                        self._run_background_task(
                            task_callable=lambda b=basename, o=old_value, n=new_value: self.processor.refactor_wildcard_value_references(b, o, n),
                            title="Refactoring Value",
                            message=f"Scanning for dependencies on '{old_value}'...",
                            on_complete=on_value_refactor_complete
                        )
            # The filename might have changed from .txt to .json
            basename, _ = os.path.splitext(self.selected_wildcard_file)
            new_filename = f"{basename}.json"
            custom_dialogs.show_info(self, "Success", f"Successfully saved {new_filename}")

            # If the file was new, or if its name changed (migration), refresh the list
            if new_filename != self.selected_wildcard_file:
                self.selected_wildcard_file = new_filename  # Update the tracked filename
                self._populate_wildcard_list()
                self.select_and_load_file(self.selected_wildcard_file)
            else:
                # If the name didn't change, just reload the content to ensure it's up-to-date
                # and the structured editor reflects the raw text changes.
                self._on_wildcard_file_select()

            self.update_callback(modified_file=self.selected_wildcard_file)
        except Exception as e:
            # This will catch file system errors, etc.
            custom_dialogs.show_error(self, "Save Error", f"Could not save wildcard file:\n{e}")

    def _handle_invalid_json_save(self, broken_content: str, error_message: str):
        """Shows a dialog when the user tries to save invalid JSON from the raw editor."""
        message = f"The content is not valid JSON.\n\nError: {error_message}\n\nWould you like to ask an AI to try and fix the syntax?"
        
        if custom_dialogs.ask_yes_no(self, "Invalid JSON", message):
            self._run_ai_json_fix(broken_content)

    def _run_ai_json_fix(self, broken_content: str):
        """Runs the AI JSON fixer in a background thread."""
        loading_dialog = custom_dialogs._CustomDialog(self, "AI Fixing JSON")
        ttk.Label(loading_dialog, text="Asking AI to fix JSON syntax...\nThis may take a moment.").pack(padx=20, pady=20)
        loading_dialog.update_idletasks()
        loading_dialog._center_window()

        def task():
            try:
                model = self.parent_app.enhancement_model_var.get()
                if not model or "model" in model.lower():
                    raise Exception("Please select a valid Ollama model in the main window.")
                
                fixed_json = self.processor.fix_json_syntax_with_ai(broken_content, model)
                self.json_fix_queue.put({'success': True, 'fixed_json': fixed_json})
            except Exception as e:
                self.json_fix_queue.put({'success': False, 'error': str(e)})
            finally:
                # Ensure the loading dialog is closed from the main thread
                loading_dialog.after(0, loading_dialog.destroy)

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self._check_json_fix_queue()

    def _check_json_fix_queue(self):
        """Checks for results from the AI JSON fixer thread."""
        try:
            result = self.json_fix_queue.get_nowait()
            if result['success']:
                fixed_json = result['fixed_json']
                self.raw_text_editor.delete("1.0", tk.END)
                self.raw_text_editor.insert("1.0", fixed_json)
                custom_dialogs.show_info(self, "JSON Fixed", "The AI has corrected the JSON syntax. Please review and click 'Save Changes' again.")
            else:
                custom_dialogs.show_error(self, "AI Fix Failed", f"The AI could not fix the JSON syntax:\n{result['error']}")
        except queue.Empty:
            self.json_fix_after_id = self.after(100, self._check_json_fix_queue)

    def _create_new_wildcard_file(self):
        filename_result = None
        is_nsfw_only = False

        # Unbind to protect dialogs from causing focus loss issues
        self.wildcard_listbox.unbind("<<ListboxSelect>>")
        try:
            filename_result = custom_dialogs.ask_string(self, "New Wildcard File", "Enter new wildcard filename:")
            if not filename_result:
                return # User cancelled

            if config.workflow == 'nsfw':
                is_nsfw_only = custom_dialogs.ask_yes_no(
                    self,
                    "Wildcard Scope",
                    "Save this as an NSFW-only wildcard?\n\n"
                    "(Choosing 'No' will save it to the shared folder, making it available in both SFW and NSFW modes.)"
                )
        finally:
            # Always re-bind the event to restore normal functionality
            if self.winfo_exists():
                self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)

        if not filename_result:
            return

        filename = filename_result
        if not filename.endswith('.json'):
            filename += '.json'

        try:
            default_content = '{\n  "description": "A new wildcard file.",\n  "choices": [\n    "item 1",\n    "item 2"\n  ]\n}'
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
        
        # Unbind to prevent focus loss from clearing the editor
        should_archive = False
        self.wildcard_listbox.unbind("<<ListboxSelect>>")
        self.dialog_is_open = True
        try:
            should_archive = custom_dialogs.ask_yes_no(self, "Confirm Archive", message)
        finally:
            self.dialog_is_open = False
            if self.winfo_exists():
                self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)

        if not should_archive: return
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
        
        self.pending_value_refactors.clear()

    def _run_background_task(self, task_callable: Callable, title: str, message: str, on_complete: Callable):
        """Runs a potentially long task in a background thread with a loading dialog."""
        loading_dialog = custom_dialogs._CustomDialog(self, title)
        ttk.Label(loading_dialog, text=message).pack(padx=20, pady=20)
        loading_dialog.update_idletasks()
        loading_dialog._center_window()

        def task_wrapper():
            try:
                result = task_callable()
                self.refactor_queue.put({'success': True, 'result': result, 'on_complete': on_complete})
            except Exception as e:
                self.refactor_queue.put({'success': False, 'error': str(e)})
            finally:
                # Ensure the loading dialog is closed from the main thread
                loading_dialog.after(0, loading_dialog.destroy)

        thread = threading.Thread(target=task_wrapper, daemon=True)
        thread.start()
        self._check_refactor_queue()

    def _check_refactor_queue(self):
        """Checks for results from a background refactoring task."""
        try:
            result = self.refactor_queue.get_nowait()
            if result['success']:
                result['on_complete'](result['result'])
            else:
                custom_dialogs.show_error(self, "Refactor Error", result['error'])
        except queue.Empty:
            self.refactor_after_id = self.after(100, self._check_refactor_queue)

    def register_value_change(self, old_value: str, new_value: str):
        """Registers that a choice's value has been changed, to be handled on save."""
        if not self.selected_wildcard_file: return
        basename, _ = os.path.splitext(self.selected_wildcard_file)
        # Avoid queuing up redundant changes for the same value.
        # If user changes 'a' -> 'b' then 'b' -> 'c', we only care about 'a' -> 'c'.
        self.pending_value_refactors = [
            (b, o, n) for b, o, n in self.pending_value_refactors if not (b == basename and n == old_value)
        ]
        self.pending_value_refactors.append((basename, old_value, new_value))

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
            should_remove = False
            self.wildcard_listbox.unbind("<<ListboxSelect>>")
            self.dialog_is_open = True
            try:
                dialog = custom_dialogs._MessageBox(self, "Remove Duplicates?", message, yes_no=True)
                should_remove = dialog.result
            finally:
                self.dialog_is_open = False
                if self.winfo_exists():
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
        threshold_str = None
        self.wildcard_listbox.unbind("<<ListboxSelect>>")
        self.dialog_is_open = True
        try:
            dialog = custom_dialogs._AskStringDialog(
                self,
                "Similarity Threshold",
                "Enter a similarity threshold (1-100).\nHigher values mean more similar.",
                initialvalue="85"
            )
            threshold_str = dialog.result
        finally:
            # Always re-bind the event to restore normal functionality
            self.dialog_is_open = False
            if self.winfo_exists():
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

        # Unbind the selection event to prevent the dialog from clearing the editor on focus loss.
        dialog_result = None
        self.wildcard_listbox.unbind("<<ListboxSelect>>")
        self.dialog_is_open = True
        try:
            selection = self.structured_editor.tree.selection()
            dialog = _FindReplaceDialog(self, selection_exists=bool(selection))
            dialog_result = dialog.result
        finally:
            # Always re-bind the event to restore normal functionality
            self.dialog_is_open = False
            if self.winfo_exists():
                self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)

        if not dialog_result:
            return

        params = dialog_result
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

                    # Update the entire treeview item to prevent UI desync.
                    if isinstance(new_choice_obj, dict):
                        value = new_choice_obj.get('value', '')
                        weight = new_choice_obj.get('weight', '')
                        tags = ", ".join(new_choice_obj.get('tags', []))
                        requires_dict = new_choice_obj.get('requires', {})
                        requires = json.dumps(requires_dict, separators=(',', ':')) if requires_dict else ""
                        
                        includes_val = new_choice_obj.get('includes')
                        if isinstance(includes_val, list):
                            includes_display = json.dumps(includes_val)
                        else:
                            includes_display = includes_val or ''
                        
                        new_values_tuple = (value, str(weight) if weight is not None and weight != '' else '', tags, requires, includes_display)
                    else: # it's a string
                        new_values_tuple = (new_choice_obj, '', '', '', '')

                    self.structured_editor.tree.item(iid, values=new_values_tuple)
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

    def _remove_all_keys(self, key_to_remove: str):
        """Removes all instances of a specific key ('requires' or 'includes') from all choices."""
        if not self.selected_wildcard_file:
            return

        # Unbind to protect dialog from causing focus loss issues
        should_proceed = False
        self.wildcard_listbox.unbind("<<ListboxSelect>>")
        self.dialog_is_open = True
        try:
            should_proceed = custom_dialogs.ask_yes_no(
                self,
                f"Confirm Removal",
                f"Are you sure you want to remove ALL '{key_to_remove}' entries from every choice in this file?\n\nThis action cannot be undone."
            )
        finally:
            self.dialog_is_open = False
            if self.winfo_exists():
                self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)

        if not should_proceed:
            return

        # Proceed with the logic if the user confirmed
        data = self.structured_editor.get_data() # Get data *after* dialog
        choices = data.get('choices', [])
        keys_removed_count = 0

        for choice in choices:
            if isinstance(choice, dict) and key_to_remove in choice:
                del choice[key_to_remove]
                keys_removed_count += 1
        
        # Also remove the global includes if that's what we're targeting
        if key_to_remove == 'includes' and 'includes' in data:
            del data['includes']
            keys_removed_count += 1

        if keys_removed_count > 0:
            self.structured_editor.set_data(data)
            self.save_button.config(state=tk.NORMAL)
            custom_dialogs.show_info(self, "Removal Complete", f"Removed {keys_removed_count} '{key_to_remove}' entries.\n\nPlease save the file to apply the changes.")
        else:
            custom_dialogs.show_info(self, "No Changes", f"No '{key_to_remove}' entries were found to remove.")

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

            # This is a dialog, so it needs focus protection
            self.wildcard_listbox.unbind("<<ListboxSelect>>")
            self.dialog_is_open = True
            try:
                if result['success']:
                    unused_wildcards = result['unused']
                    if not unused_wildcards:
                        custom_dialogs.show_info(self, "Find Unused Wildcards", "No unused wildcard files found. All wildcards are referenced in at least one template or another wildcard's 'includes' clause.")
                    else:
                        message = "The following wildcard files appear to be unused:\n\n" + "\n".join([f"- {wc}" for wc in unused_wildcards]) + "\n\nNote: This check may not detect wildcards used in complex, indirect ways. Please review before deleting."
                        custom_dialogs.show_info(self, "Unused Wildcards Found", message)
                else:
                    custom_dialogs.show_error(self, "Error", f"An error occurred while checking for unused wildcards:\n{result['error']}")
            finally:
                self.dialog_is_open = False
                if self.winfo_exists():
                    self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)
        except queue.Empty:
            self.find_unused_after_id = self.after(100, self._check_find_unused_queue)

    def _view_dependencies(self):
        """Opens the dependency viewer window."""
        _DependencyViewerWindow(self, self.processor, self)

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
                    # This is a dialog, so it needs focus protection
                    self.wildcard_listbox.unbind("<<ListboxSelect>>")
                    self.dialog_is_open = True
                    try:
                        custom_dialogs.show_info(self, "Validation Complete", "No validation errors found in 'requires' clauses.")
                    finally:
                        self.dialog_is_open = False
                        if self.winfo_exists():
                            self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)
                else:
                    self.wildcard_listbox.unbind("<<ListboxSelect>>")
                    self.dialog_is_open = True
                    try:
                        self._show_validation_errors(errors)
                    finally:
                        self.dialog_is_open = False
                        if self.winfo_exists():
                            self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)
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

        # --- Action Buttons ---
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(action_frame, text="Attempt to Fix All Missing Values...", command=lambda: self._fix_all_missing_values(errors, error_window), style="Accent.TButton").pack(side=tk.LEFT)
        ttk.Button(action_frame, text="Fix Selected with AI...", command=lambda: self._fix_error_with_ai(tree, iid_map, error_window)).pack(side=tk.LEFT, padx=5)

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
        
    def _fix_error_with_ai(self, error_tree: ttk.Treeview, iid_map: Dict[str, Any], parent_window: tk.Toplevel):
        """Handles the full workflow for fixing a selected error with AI."""
        selection = error_tree.selection()
        if not selection:
            custom_dialogs.show_warning(parent_window, "No Selection", "Please select an error to fix.")
            return

        iid = selection[0]
        error_details = iid_map.get(iid)
        if not error_details: return

        filename = error_details.get('source_file')
        if not filename: return

        try:
            original_content = self.processor.load_wildcard_content(filename)
        except Exception as e:
            custom_dialogs.show_error(parent_window, "Error", f"Could not load file '{filename}':\n{e}")
            return

        loading_dialog = custom_dialogs._CustomDialog(parent_window, "AI Fixing Error")
        ttk.Label(loading_dialog, text=f"Asking AI to fix error in '{filename}'...\nThis may take a moment.").pack(padx=20, pady=20)
        loading_dialog.update_idletasks()
        loading_dialog._center_window()

        def task():
            try:
                model = self.parent_app.enhancement_model_var.get()
                if not model or "model" in model.lower():
                    raise Exception("Please select a valid Ollama model in the main window.")
                
                fixed_content = self.processor.fix_wildcard_error_with_ai(original_content, error_details, model)
                self.fix_queue.put({'success': True, 'original': original_content, 'fixed': fixed_content, 'filename': filename})
            except Exception as e:
                self.fix_queue.put({'success': False, 'error': str(e)})
            finally:
                loading_dialog.after(0, loading_dialog.destroy)

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self._check_fix_queue(parent_window)

    def _check_fix_queue(self, parent_window: tk.Toplevel):
        """Checks for results from the AI fixer thread."""
        try:
            result = self.fix_queue.get_nowait()
            if result['success']:
                self._show_fix_confirmation(result['original'], result['fixed'], result['filename'], parent_window)
            else:
                custom_dialogs.show_error(parent_window, "AI Fix Error", f"The AI failed to fix the error:\n{result['error']}")
        except queue.Empty:
            self.fix_after_id = self.after(100, lambda: self._check_fix_queue(parent_window))

    def _show_fix_confirmation(self, original_content: str, fixed_content: str, filename: str, parent_window: tk.Toplevel):
        """Shows a diff view for the user to confirm the AI's proposed changes."""
        if original_content.strip() == fixed_content.strip():
            custom_dialogs.show_info(parent_window, "AI Fix", "The AI returned the content without any changes.")
            return

        diff = difflib.unified_diff(original_content.splitlines(keepends=True), fixed_content.splitlines(keepends=True), fromfile='original', tofile='fixed_by_ai')
        diff_text = "".join(diff)

        # This is a complex dialog, so we create it here instead of a separate class for now.
        diff_window = custom_dialogs._CustomDialog(parent_window, f"Confirm AI Fix for {filename}")
        diff_window.geometry("700x500")
        self._create_diff_dialog_widgets(diff_window, diff_text, filename, fixed_content, parent_window)

    def _fix_all_missing_values(self, errors: List[Dict[str, Any]], parent_window: tk.Toplevel):
        """Attempts to automatically fix all 'missing_value' errors by adding the values to the target files."""
        fixable_errors = [e for e in errors if e.get('details', {}).get('type') == 'missing_value']
        
        if not fixable_errors:
            custom_dialogs.show_info(parent_window, "No Fixable Errors", "No errors of type 'missing value' were found to fix automatically.")
            return

        if not custom_dialogs.ask_yes_no(
            parent_window,
            "Confirm Auto-Fix",
            f"Found {len(fixable_errors)} errors that can be automatically fixed by adding missing values to other wildcards.\n\nAre you sure you want to proceed?"
        ):
            return

        # Group fixes by target file to avoid reading/writing the same file multiple times.
        fixes_by_file: Dict[str, Set[str]] = {}
        for error in fixable_errors:
            details = error['details']
            target_file = details['target_wildcard']
            missing_value = details['missing_value']
            if target_file not in fixes_by_file:
                fixes_by_file[target_file] = set()
            fixes_by_file[target_file].add(missing_value)

        files_modified_count = 0
        values_added_count = 0
        errors_encountered = []

        for target_file, values_to_add in fixes_by_file.items():
            try:
                target_data = self._load_and_parse_wildcard_file(target_file)
                if target_data is None:
                    errors_encountered.append(f"Could not load target file '{target_file}'.")
                    continue
                
                if 'choices' not in target_data: target_data['choices'] = []
                
                existing_choices = {str(c.get('value') if isinstance(c, dict) else c) for c in target_data['choices']}
                newly_added_count = 0
                for value in values_to_add:
                    if value not in existing_choices:
                        target_data['choices'].append(value)
                        newly_added_count += 1
                
                if newly_added_count > 0:
                    new_content = json.dumps(target_data, indent=2)
                    self.processor.save_wildcard_content(target_file, new_content)
                    files_modified_count += 1
                    values_added_count += newly_added_count
            except Exception as e:
                errors_encountered.append(f"Failed to modify '{target_file}': {e}")

        summary_message = f"Auto-fix complete.\n\n- Added {values_added_count} missing values across {files_modified_count} files."
        if errors_encountered:
            summary_message += "\n\nErrors encountered:\n" + "\n".join([f"- {e}" for e in errors_encountered])
        summary_message += "\n\nPlease re-run validation to confirm the fixes."
        
        custom_dialogs.show_info(parent_window, "Auto-Fix Complete", summary_message)
        parent_window.destroy()

    def _create_diff_dialog_widgets(self, diff_window: tk.Toplevel, diff_text: str, filename: str, fixed_content: str, parent_window: tk.Toplevel):
        """Creates the widgets inside the diff confirmation dialog."""
        main_frame = ttk.Frame(diff_window, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="The AI has proposed the following changes. Review the diff and click 'Apply Fix' to save.", wraplength=680).pack(anchor='w', pady=(0, 10))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        diff_widget = tk.Text(text_frame, wrap=tk.WORD, font=self.parent_app.fixed_font)
        diff_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=diff_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        diff_widget.configure(yscrollcommand=scrollbar.set)

        diff_widget.insert("1.0", diff_text)

        # Add color highlighting for diff
        diff_widget.tag_configure("addition", foreground="green")
        diff_widget.tag_configure("deletion", foreground="red")

        for i, line in enumerate(diff_text.splitlines(), 1):
            if line.startswith('+') and not line.startswith('+++'):
                diff_widget.tag_add("addition", f"{i}.0", f"{i}.end")
            elif line.startswith('-') and not line.startswith('---'):
                diff_widget.tag_add("deletion", f"{i}.0", f"{i}.end")
        
        diff_widget.config(state=tk.DISABLED)

        def apply_fix():
            try:
                self.processor.save_wildcard_content(filename, fixed_content)
                custom_dialogs.show_info(parent_window, "Success", f"Successfully applied AI fix to '{filename}'.\n\nPlease re-run validation.")
                diff_window.destroy()
                parent_window.destroy() # Close the validation error window too
            except Exception as e:
                custom_dialogs.show_error(diff_window, "Save Error", f"Could not save file:\n{e}")

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(button_frame, text="Apply Fix", command=apply_fix, style="Accent.TButton").pack(side=tk.RIGHT)
        ttk.Button(button_frame, text="Cancel", command=diff_window.destroy).pack(side=tk.RIGHT, padx=(0, 5))

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

    def _rename_selected_wildcard(self):
        """Renames the selected wildcard file."""
        selected_indices = self.wildcard_listbox.curselection()
        if len(selected_indices) != 1:
            return

        old_filename = self.wildcard_listbox.get(selected_indices[0])
        old_basename, _ = os.path.splitext(old_filename)

        # Unbind to prevent focus loss from clearing the editor
        new_basename = None
        self.wildcard_listbox.unbind("<<ListboxSelect>>")
        self.dialog_is_open = True
        try:
            dialog = custom_dialogs._AskStringDialog(
                self, 
                "Rename Wildcard", 
                "Enter new name (without extension):", 
                initialvalue=old_basename
            )
            new_basename = dialog.result
        finally:
            self.dialog_is_open = False
            if self.winfo_exists():
                self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)

        if not new_basename or new_basename.strip() == old_basename:
            return

        new_filename = f"{new_basename.strip()}.json"

        try:
            self.processor.rename_wildcard(old_filename, new_filename)
            
            self._populate_wildcard_list()
            self.update_callback(modified_file=new_filename)
            self.select_and_load_file(new_filename)
            
            if custom_dialogs.ask_yes_no(
                self, 
                "Refactor References?", 
                f"Successfully renamed to '{new_filename}'.\n\nWould you like to scan all other wildcards and update references from '{old_basename}' to '{new_basename}'?"
            ):
                def on_rename_refactor_complete(modified_count):
                    custom_dialogs.show_info(self, "Refactor Complete", f"Updated {modified_count} file(s) that referenced '{old_basename}'.")
                    self.update_callback() 

                self._run_background_task(
                    task_callable=lambda: self.processor.refactor_wildcard_references(old_basename, new_basename.strip()),
                    title="Refactoring References",
                    message=f"Scanning for references to '{old_basename}'...",
                    on_complete=on_rename_refactor_complete
                )
        except FileExistsError as e:
            custom_dialogs.show_error(self, "Rename Error", str(e))
        except Exception as e:
            custom_dialogs.show_error(self, "Rename Error", f"Could not rename file:\n{e}")

    def _create_file_list_context_menu(self):
        """Creates the right-click context menu for the wildcard file list."""
        self.file_list_context_menu = tk.Menu(self.wildcard_listbox, tearoff=0)
        self.file_list_context_menu.add_command(label="Brainstorm with AI", command=self._brainstorm_with_ai)
        self.file_list_context_menu.add_separator()
        self.file_list_context_menu.add_command(label="Archive", command=self._archive_selected_wildcard)
        self.file_list_context_menu.add_command(label="Rename...", command=self._rename_selected_wildcard)

    def _show_file_list_context_menu(self, event):
        """
        Handles the right-click event on the file list, preserving selection on macOS.
        """
        index = self.wildcard_listbox.nearest(event.y)

        # If the click is on an actual item and that item is not already selected,
        # then we perform the standard "select only this item" behavior.
        # This will trigger the <<ListboxSelect>> event, which correctly updates the editor.
        if index != -1 and not self.wildcard_listbox.selection_includes(index):
            self.wildcard_listbox.selection_clear(0, tk.END)
            self.wildcard_listbox.selection_set(index)
            self.wildcard_listbox.activate(index)

        # Now that the selection is correct, configure and show the menu.
        selection_count = len(self.wildcard_listbox.curselection())

        # Configure menu items based on the final selection
        self.file_list_context_menu.entryconfig("Brainstorm with AI", state=tk.NORMAL if selection_count == 1 else tk.DISABLED)
        self.file_list_context_menu.entryconfig("Rename...", state=tk.NORMAL if selection_count == 1 else tk.DISABLED)
        self.file_list_context_menu.entryconfig("Archive", state=tk.NORMAL if selection_count > 0 else tk.DISABLED)

        self.file_list_context_menu.tk_popup(event.x_root, event.y_root)
        
        # Return "break" to prevent any other default bindings from firing.
        return "break"

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

        # --- Merge Choices (uniquely and intelligently) ---
        merged_choices_map: Dict[str, Any] = {}
        for _, data in all_data:
            for choice in data.get('choices', []):
                is_new_dict = isinstance(choice, dict)
                value = choice.get('value') if is_new_dict else choice
                
                if value is None:
                    continue

                if value not in merged_choices_map:
                    # First time seeing this value, add a deepcopy to avoid modifying original data.
                    merged_choices_map[value] = copy.deepcopy(choice)
                else:
                    # Duplicate value found, merge properties.
                    existing_choice = merged_choices_map[value]
                    
                    # Ensure both are dicts for merging.
                    if not isinstance(existing_choice, dict):
                        existing_choice = {'value': existing_choice}
                    
                    new_choice_data = choice if is_new_dict else {'value': choice}

                    # Merge 'tags'
                    existing_tags = set(existing_choice.get('tags', []))
                    new_tags = set(new_choice_data.get('tags', []))
                    if existing_tags or new_tags:
                        existing_choice['tags'] = sorted(list(existing_tags | new_tags))

                    # Merge 'requires'
                    existing_reqs = existing_choice.get('requires', {})
                    new_reqs = new_choice_data.get('requires', {})
                    if existing_reqs or new_reqs:
                        merged_reqs = copy.deepcopy(existing_reqs)
                        for key, value2 in new_reqs.items():
                            if key in merged_reqs:
                                value1 = merged_reqs[key]
                                set1 = set(value1) if isinstance(value1, list) else {value1}
                                set2 = set(value2) if isinstance(value2, list) else {value2}
                                merged_values = sorted(list(set1 | set2))
                                # Keep it as a single value if only one results from the merge
                                merged_reqs[key] = merged_values[0] if len(merged_values) == 1 else merged_values
                            else:
                                merged_reqs[key] = value2

                        existing_choice['requires'] = merged_reqs
                    
                    # Merge 'includes'
                    inc1 = existing_choice.get('includes')
                    inc2 = new_choice_data.get('includes')
                    is_inc1_list = isinstance(inc1, list)
                    is_inc2_list = isinstance(inc2, list)

                    merged_includes = None
                    if is_inc1_list and is_inc2_list:
                        merged_includes = sorted(list(set(inc1) | set(inc2)))
                    elif inc1 or inc2:
                        s1 = " ".join([f"[{w}]" for w in inc1]) if is_inc1_list else (inc1 or '')
                        s2 = " ".join([f"[{w}]" for w in inc2]) if is_inc2_list else (inc2 or '')
                        combined_str = f"{s1} {s2}".strip()
                        if combined_str:
                            merged_includes = combined_str
                    
                    if merged_includes:
                        existing_choice['includes'] = merged_includes

                    # Update the map with the merged choice object.
                    merged_choices_map[value] = existing_choice
        
        merged_choices = list(merged_choices_map.values())

        # --- Merge Global Includes (intelligently) ---
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

        # Unbind here to protect all dialogs within the merge and save steps.
        self.wildcard_listbox.unbind("<<ListboxSelect>>")
        self.dialog_is_open = True
        try:
            merged_data = self._perform_merge(all_data)
            self._save_and_finalize_merge(merged_data, file_names)
        finally:
            self.dialog_is_open = False
            if self.winfo_exists():
                self.wildcard_listbox.bind("<<ListboxSelect>>", self._on_wildcard_file_select)