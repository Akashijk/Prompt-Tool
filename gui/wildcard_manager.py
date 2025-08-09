"""A pop-up window to manage wildcard files."""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Optional, Callable, TYPE_CHECKING

from core.prompt_processor import PromptProcessor
from core.config import config
from .common import TextContextMenu

if TYPE_CHECKING:
    from .gui_app import GUIApp

class WildcardManagerWindow(tk.Toplevel):
    """A pop-up window to manage wildcard files."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor, update_callback: Callable, initial_file: Optional[str] = None):
        super().__init__(parent)
        self.title("Wildcard Manager")
        self.geometry("700x500")
        
        self.processor = processor
        self.update_callback = update_callback
        self.selected_wildcard_file: Optional[str] = None
        self.parent_app = parent

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
            self.editor_text.config(state=tk.NORMAL)
            self.editor_text.delete("1.0", tk.END)
            self.editor_text.config(state=tk.DISABLED)
            self.save_button.config(state=tk.DISABLED)
            self.archive_button.config(state=tk.DISABLED)
            self.brainstorm_button.config(state=tk.DISABLED)
            self.editor_frame.config(text="No file selected")
            self._populate_wildcard_list()
            self.update_callback()
        except Exception as e:
            messagebox.showerror("Archive Error", f"Could not archive file:\n{e}", parent=self)

    def _brainstorm_with_ai(self):
        """Sends the current wildcard content to the brainstorming window."""
        if not self.selected_wildcard_file: return
        content = self.editor_text.get("1.0", "end-1c")
        self.parent_app._brainstorm_with_content("wildcard", self.selected_wildcard_file, content)

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