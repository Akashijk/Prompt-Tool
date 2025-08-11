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
        self.show_favorites_only_var = tk.BooleanVar(value=False)
        self.iid_map: Dict[str, Dict[str, str]] = {}
        self.details_notebook: Optional[ttk.Notebook] = None
        self.detail_tabs: Dict[str, Dict[str, Any]] = {}
        self.tab_order = ['original', 'enhanced', 'cinematic', 'artistic', 'photorealistic']

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
        self.search_var.trace_add("write", lambda *args: self._apply_filters())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Add favorites filter
        favorites_check = ttk.Checkbutton(search_frame, text="Favorites Only ⭐", variable=self.show_favorites_only_var, command=self._apply_filters)
        favorites_check.pack(side=tk.LEFT, padx=5)

        # Main paned window for table and details
        main_pane = ttk.PanedWindow(main_frame, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        # --- History Table ---
        tree_frame = ttk.Frame(main_pane)
        main_pane.add(tree_frame, weight=3)

        columns = ('favorite', 'original_prompt', 'enhanced_prompt', 'status', 'enhanced_sd_model')
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
        self.context_menu.add_command(label="Toggle Favorite ⭐", command=self._toggle_favorite)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Delete Entry", command=self._delete_selected_history)

        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        self.tree.bind(right_click_event, self._show_context_menu)

        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        # Define headings
        self.tree.heading('favorite', text='⭐')
        self.tree.heading('original_prompt', text='Original Prompt')
        self.tree.heading('enhanced_prompt', text='Enhanced Prompt')
        self.tree.heading('status', text='Status')
        self.tree.heading('enhanced_sd_model', text='SD Model')

        # Define column widths
        self.tree.column('favorite', width=40, anchor='center', stretch=False)
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
        details_notebook_frame = ttk.LabelFrame(main_pane, text="Selected Prompt Details", padding=5)
        main_pane.add(details_notebook_frame, weight=2)

        self.details_notebook = ttk.Notebook(details_notebook_frame)
        self.details_notebook.pack(fill=tk.BOTH, expand=True)

        # Create tab content holders
        tab_titles = {
            'original': 'Original', 'enhanced': 'Enhanced',
            'cinematic': 'Cinematic', 'artistic': 'Artistic', 'photorealistic': 'Photorealistic'
        }

        for key in self.tab_order:
            frame = ttk.Frame(self.details_notebook, padding=5)
            
            text_widget = tk.Text(frame, wrap=tk.WORD, height=5, font=self.parent_app.default_font, state=tk.DISABLED)
            TextContextMenu(text_widget)
            text_widget.pack(fill=tk.BOTH, expand=True)
            
            model_label = ttk.Label(frame, text="", font=self.parent_app.small_font, foreground="gray")
            model_label.pack(anchor='w', pady=(5,0))
            
            self.detail_tabs[key] = {
                'frame': frame,
                'text': text_widget,
                'model_label': model_label,
                'title': tab_titles.get(key, key.capitalize())
            }

    def load_and_display_history(self):
        """Loads data from the history file and populates the treeview once."""
        self.all_history_data = self.processor.get_full_history()
        self._populate_treeview(self.all_history_data)

    def _populate_treeview(self, data: List[Dict[str, str]]):
        """Clears and fills the treeview with the given data. Called only on initial load."""
        if not self.tree: return
        # Clear old data efficiently
        self.tree.delete(*self.tree.get_children())
        self.iid_map.clear()

        for row in data:
            is_fav = "⭐" if row.get('favorite') else ""
            values = (is_fav, row.get('original_prompt', ''), row.get('enhanced_prompt', ''), row.get('status', ''), row.get('enhanced_sd_model', ''))
            iid = self.tree.insert('', tk.END, values=values)
            self.iid_map[iid] = row

    def _apply_filters(self):
        """Shows or hides treeview items based on the current filter criteria without rebuilding the tree."""
        if not self.tree: return
        
        search_term = self.search_var.get().lower()
        show_favorites_only = self.show_favorites_only_var.get()

        # Instead of deleting and re-inserting, we detach and move items.
        # This is significantly faster for large lists.
        for iid, row in self.iid_map.items():
            is_favorite_match = not show_favorites_only or row.get('favorite')

            original_prompt = row.get('original_prompt', '').lower()
            enhanced_prompt = row.get('enhanced_prompt', '').lower()
            is_search_match = not search_term or (search_term in original_prompt or search_term in enhanced_prompt)
            
            if is_favorite_match and is_search_match:
                self.tree.move(iid, '', 'end') # Ensure the item is visible and in order
            else:
                self.tree.detach(iid) # Detach the item so it's not visible

    def _on_row_select(self, event=None):
        """Displays the full content of the selected row in the details view."""
        if not self.tree or not self.details_notebook:
            return

        # Forget all tabs to ensure a clean slate for each selection
        for tab_id in self.details_notebook.tabs():
            self.details_notebook.forget(tab_id)

        selected_items = self.tree.selection()
        if not selected_items:
            return # No selection, so no tabs should be visible.

        selected_iid = selected_items[0]
        full_row_data = self.iid_map.get(selected_iid)

        if not full_row_data:
            # Handle case where data for the selected row is missing
            error_tab = self.detail_tabs['original']
            error_tab['text'].config(state=tk.NORMAL)
            error_tab['text'].delete("1.0", tk.END)
            error_tab['text'].insert("1.0", "Error: Could not find details for the selected row.")
            error_tab['text'].config(state=tk.DISABLED)
            error_tab['model_label'].config(text="")
            self.details_notebook.add(error_tab['frame'], text=error_tab['title'])
            return

        # Iterate through the predefined tab order and add tabs if data exists
        for key in self.tab_order:
            prompt = ""
            model = ""
            data_exists = False

            if key == 'original':
                prompt = full_row_data.get('original_prompt', '')
                if prompt: data_exists = True
            elif key == 'enhanced':
                prompt = full_row_data.get('enhanced_prompt', '')
                model = full_row_data.get('enhanced_sd_model', '')
                if prompt: data_exists = True
            else: # It's a variation
                var_data = full_row_data.get('variations', {}).get(key)
                if var_data:
                    prompt = var_data.get('prompt', '')
                    model = var_data.get('sd_model', '')
                    if prompt: data_exists = True
            
            if data_exists:
                tab = self.detail_tabs[key]
                
                # Update tab content
                tab['text'].config(state=tk.NORMAL)
                tab['text'].delete("1.0", tk.END)
                tab['text'].insert("1.0", prompt)
                tab['text'].config(state=tk.DISABLED)
                tab['model_label'].config(text=f"Recommended Model: {model}" if model else "")
                
                # Add tab to notebook
                self.details_notebook.add(self.detail_tabs[key]['frame'], text=self.detail_tabs[key]['title'])

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
                row_to_remove = self.iid_map.pop(item_id, None)
                self.tree.delete(item_id)
                if row_to_remove:
                    try:
                        self.all_history_data.remove(row_to_remove)
                    except ValueError:
                        # This can happen if the list is out of sync, but pop should handle the iid_map.
                        self.all_history_data = list(self.iid_map.values())
                messagebox.showinfo("Success", "History entry deleted.", parent=self)
            else:
                messagebox.showerror("Error", "Could not delete the history entry. It may have already been deleted.", parent=self)
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred while deleting the entry:\n{e}", parent=self)

    def _toggle_favorite(self):
        """Toggles the favorite status of the selected item."""
        if not self.tree: return
        selected_items = self.tree.selection()
        if not selected_items: return

        item_id = selected_items[0]
        original_row = self.iid_map.get(item_id)
        if not original_row: return

        # Create a copy to modify
        updated_row = original_row.copy()
        current_status = updated_row.get('favorite', False)
        updated_row['favorite'] = not current_status

        # Update the CSV file
        success = self.processor.update_history_entry(original_row, updated_row)
        if success:
            # Update the in-memory data
            self.iid_map[item_id] = updated_row
            for i, row in enumerate(self.all_history_data):
                if row.get('id') == original_row.get('id'):
                    self.all_history_data[i] = updated_row
                    break
            
            # Update the visible row directly in the treeview
            is_fav = "⭐" if updated_row.get('favorite') else ""
            self.tree.set(item_id, 'favorite', is_fav)

            # If the favorites filter is on, the item might need to be hidden
            if self.show_favorites_only_var.get() and not updated_row.get('favorite'):
                self.tree.detach(item_id)
        else:
            messagebox.showerror("Error", "Failed to update favorite status.", parent=self)

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
                variations = full_row_data.get('variations', {})
                has_cinematic = 'cinematic' in variations
                has_artistic = 'artistic' in variations
                has_photo = 'photorealistic' in variations
                
                self.context_menu.entryconfig("Copy Cinematic Variation", state=tk.NORMAL if has_cinematic else tk.DISABLED)
                self.context_menu.entryconfig("Copy Artistic Variation", state=tk.NORMAL if has_artistic else tk.DISABLED)
                self.context_menu.entryconfig("Copy Photorealistic Variation", state=tk.NORMAL if has_photo else tk.DISABLED)

                # Update favorite toggle label
                is_fav = full_row_data.get('favorite', False)
                self.context_menu.entryconfig("Toggle Favorite ⭐", label="Unfavorite ⭐" if is_fav else "Favorite ⭐")

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
            content_to_copy = ""
            if part_key in ['original_prompt', 'enhanced_prompt']:
                content_to_copy = full_row_data.get(part_key, '')
            else: # It's a variation
                var_type = part_key.replace('_variation', '')
                content_to_copy = full_row_data.get('variations', {}).get(var_type, {}).get('prompt', '')

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