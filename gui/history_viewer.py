"""A window to view and search the prompt generation history."""

import tkinter as tk
from tkinter import ttk, messagebox
import sys
from typing import List, Dict, Optional, TYPE_CHECKING

from core.prompt_processor import PromptProcessor
from .common import TextContextMenu, SmartWindowMixin

if TYPE_CHECKING:
    from .gui_app import GUIApp

class HistoryViewerWindow(tk.Toplevel, SmartWindowMixin):
    """A window to view and search the prompt generation history."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor):
        super().__init__(parent)
        self.title("Prompt History Viewer")

        self.processor = processor
        self.parent_app = parent
        self.all_history_data: List[Dict[str, str]] = []
        self.tree: Optional[ttk.Treeview] = None
        self.iid_map: Dict[str, Dict[str, str]] = {}

        self._create_widgets()
        self.load_and_display_history()

        self.smart_geometry(min_width=1000, min_height=700)

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

        self.details_text = tk.Text(details_frame, wrap=tk.WORD, state=tk.DISABLED, font=self.parent_app.default_font)
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
        if not self.tree: return
        # Clear old data
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.iid_map.clear()

        for row in data:
            values = (row.get('original_prompt', ''), row.get('enhanced_prompt', ''), row.get('status', ''), row.get('enhanced_sd_model', ''))
            iid = self.tree.insert('', tk.END, values=values)
            self.iid_map[iid] = row

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
        if not self.tree: return
        selected_items = self.tree.selection()
        if not selected_items: return

        # Find the full data dictionary for the selected row
        selected_iid = selected_items[0]
        full_row_data = self.iid_map.get(selected_iid)

        if not full_row_data:
            self.details_text.config(state=tk.NORMAL)
            self.details_text.delete("1.0", tk.END)
            self.details_text.insert("1.0", "Error: Could not find details for the selected row.")
            self.details_text.config(state=tk.DISABLED)
            return

        original_prompt = full_row_data.get('original_prompt', '')
        enhanced_prompt = full_row_data.get('enhanced_prompt', '')

        details_content = f"ORIGINAL PROMPT:\n{'-'*20}\n{original_prompt}\n\n"
        details_content += f"ENHANCED PROMPT:\n{'-'*20}\n{enhanced_prompt}"

        # Check for and add variations
        variations_content = ""
        for var_key in ['cinematic', 'artistic', 'photorealistic']:
            prompt_key = f'{var_key}_variation'
            model_key = f'{var_key}_sd_model'
            if full_row_data.get(prompt_key):
                variations_content += f"\n\n{var_key.upper()} VARIATION:\n{'-'*20}\n{full_row_data[prompt_key]}\n(Model: {full_row_data.get(model_key, 'N/A')})"

        if variations_content:
            details_content += "\n" + variations_content
        
        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert("1.0", details_content)
        self.details_text.config(state=tk.DISABLED)

    def _delete_selected_history(self):
        """Deletes the selected row from the history file and the view."""
        if not self.tree: return
        selected_items = self.tree.selection()
        if not selected_items:
            return

        item_id = selected_items[0]
        full_row_data = self.iid_map.get(item_id)

        if not full_row_data:
            messagebox.showerror("Error", "Could not find data for the selected row to delete.", parent=self)
            return

        original_prompt_preview = full_row_data.get('original_prompt', 'Unknown Prompt')

        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to permanently delete this history entry?\n\nOriginal: \"{original_prompt_preview[:80]}...\"", parent=self):
            return

        try:
            # Pass the entire dictionary to ensure the correct row is deleted
            success = self.processor.delete_history_entry(full_row_data)
            if success:
                # Remove from the Treeview and the internal data cache
                self.tree.delete(item_id)
                if item_id in self.iid_map:
                    del self.iid_map[item_id]
                self.all_history_data = list(self.iid_map.values())
                messagebox.showinfo("Success", "History entry deleted.", parent=self)
            else:
                messagebox.showerror("Error", "Could not delete the history entry. It may have already been deleted.", parent=self)
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred while deleting the entry:\n{e}", parent=self)

    def _show_context_menu(self, event):
        """Shows the right-click context menu for a treeview row."""
        if not self.tree: return
        row_id = self.tree.identify_row(event.y)
        if row_id:
            # Select the row that was right-clicked
            self.tree.selection_set(row_id)
            self._on_row_select() # Update the details pane

            # Find full data to configure menu
            full_row_data = self.iid_map.get(row_id)

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
        if not self.tree: return
        selected_items = self.tree.selection()
        if not selected_items:
            return

        selected_iid = selected_items[0]
        full_row_data = self.iid_map.get(selected_iid)
        if full_row_data:
            content_to_copy = full_row_data.get(part_key, '')
            if content_to_copy:
                self.clipboard_clear()
                self.clipboard_append(content_to_copy)

    def _load_to_main_window(self):
        """Sends the selected original prompt back to the main app for re-enhancement."""
        if not self.tree: return
        selected_items = self.tree.selection()
        if not selected_items:
            return

        selected_iid = selected_items[0]
        full_row_data = self.iid_map.get(selected_iid)
        if full_row_data:
            original_prompt = full_row_data.get('original_prompt', '')
            if original_prompt:
                self.parent_app.load_prompt_from_history(original_prompt)
                self.destroy()