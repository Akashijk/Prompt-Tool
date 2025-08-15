"""A window to view and search the prompt generation history."""

import tkinter as tk
from tkinter import ttk
import sys
from typing import List, Dict, Optional, TYPE_CHECKING
from . import custom_dialogs

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
        self.filter_debounce_timer: Optional[str] = None
        self.detail_tabs: Dict[str, Dict[str, Any]] = {}
        self.original_edit_content: Optional[str] = None
        self.available_variations_map = {v['key']: v['name'] for v in self.processor.get_available_variations()}

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
        self.search_var.trace_add("write", lambda *args: self._schedule_filter_update())
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

        columns = ('favorite', 'template_name', 'original_prompt', 'enhanced_prompt', 'status', 'enhanced_sd_model')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings')

        # --- Context Menu (built dynamically in _show_context_menu) ---
        self.context_menu = tk.Menu(self.tree, tearoff=0)

        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        self.tree.bind(right_click_event, self._show_context_menu)

        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        # Define headings
        self.tree.heading('favorite', text='⭐')
        self.tree.heading('template_name', text='Template')
        self.tree.heading('original_prompt', text='Original Prompt')
        self.tree.heading('enhanced_prompt', text='Enhanced Prompt')
        self.tree.heading('status', text='Status')
        self.tree.heading('enhanced_sd_model', text='SD Model')

        # Define column widths
        self.tree.column('favorite', width=30, anchor='center', stretch=False)
        self.tree.column('template_name', width=150, minwidth=100)
        self.tree.column('original_prompt', width=250, minwidth=150)
        self.tree.column('enhanced_prompt', width=350, minwidth=200)
        self.tree.column('status', width=70, anchor='center', stretch=False)
        self.tree.column('enhanced_sd_model', width=180, minwidth=150)

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

        # Create the static tabs that are always present.
        # Variation tabs will be created dynamically as needed.
        self._create_detail_tab('original', 'Original')
        self._create_detail_tab('enhanced', 'Enhanced')

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
            values = (
                is_fav, 
                row.get('template_name', ''),
                row.get('original_prompt', ''), 
                row.get('enhanced_prompt', ''), 
                row.get('status', ''), 
                row.get('enhanced_sd_model', '')
            )
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

    def _schedule_filter_update(self):
        """Schedules a filter update after a short delay to avoid excessive updates during typing."""
        if self.filter_debounce_timer:
            self.after_cancel(self.filter_debounce_timer)
        self.filter_debounce_timer = self.after(300, self._apply_filters) # 300ms delay

    def _on_row_select(self, event=None):
        """Displays the full content of the selected row in the details view."""
        if not self.tree or not self.details_notebook:
            return

        # Before doing anything, ensure we exit edit mode if it was active
        if 'edit_button' in self.detail_tabs['enhanced']:
            self._cancel_edit_mode('enhanced', force=True)

        # Forget all tabs to ensure a clean slate for each selection
        for tab_id in self.details_notebook.tabs():
            self.details_notebook.forget(tab_id)

        selected_items = self.tree.selection()
        if not selected_items:
            return # No selection, so no tabs should be visible.

        selected_iid = selected_items[0]
        full_row_data = self.iid_map.get(selected_iid)

        if not full_row_data:
            # Ensure the 'original' tab exists before trying to use it for an error message
            if 'original' not in self.detail_tabs:
                self._create_detail_tab('original', 'Original')
            error_tab = self.detail_tabs.get('original')
            if not error_tab: return # Should not happen

            error_tab['text'].config(state=tk.NORMAL)
            error_tab['text'].delete("1.0", tk.END)
            error_tab['text'].insert("1.0", "Error: Could not find details for the selected row.")
            error_tab['text'].config(state=tk.DISABLED)
            error_tab['model_label'].config(text="")
            self.details_notebook.add(error_tab['frame'], text=error_tab['title'])
            return

        # --- DYNAMIC TAB LOGIC ---
        # 1. Determine the order of tabs to display for this specific entry
        display_order = ['original', 'enhanced', 'negative']
        if 'variations' in full_row_data:
            display_order.extend(sorted(full_row_data['variations'].keys()))

        # 2. Iterate and display tabs
        for key in display_order:
            # Skip negative tab if there's no content for it
            if key == 'negative' and not full_row_data.get('negative_prompt'):
                continue

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
            elif key == 'negative':
                prompt = full_row_data.get('negative_prompt', '')
                if prompt: data_exists = True
            else: # It's a variation
                var_data = full_row_data.get('variations', {}).get(key)
                if var_data:
                    prompt = var_data.get('prompt', '')
                    model = var_data.get('sd_model', '')
                    if prompt: data_exists = True
            
            if data_exists:
                # 3. Ensure the tab widgets exist, creating them if necessary
                if key not in self.detail_tabs:
                    self._create_detail_tab(key, key.capitalize() if key != 'negative' else 'Negative')

                tab = self.detail_tabs[key]
                
                # Update tab content
                tab['text'].config(state=tk.NORMAL)
                tab['text'].delete("1.0", tk.END)
                tab['text'].insert("1.0", prompt)
                tab['text'].config(state=tk.DISABLED)
                tab['model_label'].config(text=f"Recommended Model: {model}" if model else "")
                
                # Add tab to notebook
                self.details_notebook.add(self.detail_tabs[key]['frame'], text=self.detail_tabs[key]['title'])

    def _create_detail_tab(self, key: str, title: Optional[str] = None):
        """Creates the widgets for a single detail tab if they don't already exist."""
        if key in self.detail_tabs:
            return

        if title is None:
            # For variations, get the friendly name or capitalize the key
            title = self.available_variations_map.get(key, key.capitalize())

        frame = ttk.Frame(self.details_notebook, padding=5)
        
        text_widget = tk.Text(frame, wrap=tk.WORD, height=5, font=self.parent_app.default_font, state=tk.DISABLED)
        TextContextMenu(text_widget)
        text_widget.pack(fill=tk.BOTH, expand=True)

        bottom_bar = ttk.Frame(frame)
        bottom_bar.pack(fill=tk.X, pady=(5,0))

        model_label = ttk.Label(bottom_bar, text="", font=self.parent_app.small_font, foreground="gray")
        model_label.pack(side=tk.LEFT, anchor='w')

        self.detail_tabs[key] = {'frame': frame, 'text': text_widget, 'model_label': model_label, 'title': title}

        # Special handling for the 'enhanced' and 'negative' tab's edit buttons
        if key in ['enhanced', 'negative']:
            button_container = ttk.Frame(bottom_bar)
            button_container.pack(side=tk.RIGHT)
            
            edit_button = ttk.Button(button_container, text="Edit", command=lambda k=key: self._enter_edit_mode(k))
            update_button = ttk.Button(button_container, text="Update", style="Accent.TButton", command=lambda k=key: self._update_edited_prompt(k))
            cancel_button = ttk.Button(button_container, text="Cancel", command=lambda k=key: self._cancel_edit_mode(k))
            
            self.detail_tabs[key].update({'edit_button': edit_button, 'update_button': update_button, 'cancel_button': cancel_button})
            edit_button.pack(side=tk.LEFT)

    def _delete_selected_history(self):
        """Deletes the selected row from the history file and the view."""
        if not self.tree: return
        selected_items = self.tree.selection()
        if not selected_items:
            return

        item_id = selected_items[0]
        full_row_data = self.iid_map.get(item_id)

        if not full_row_data:
            custom_dialogs.show_error(self, "Error", "Could not find data for the selected row to delete.")
            return

        original_prompt_preview = full_row_data.get('original_prompt', 'Unknown Prompt')

        if not custom_dialogs.ask_yes_no(self, "Confirm Delete", f"Are you sure you want to permanently delete this history entry?\n\nOriginal: \"{original_prompt_preview[:80]}...\""):
            return

        try:
            # Pass the entire dictionary to ensure the correct row is deleted
            success = self.processor.delete_history_entry(full_row_data)
            if success:
                # Remove from the Treeview and rebuild the internal data cache for robustness
                row_to_remove = self.iid_map.pop(item_id, None)
                self.tree.delete(item_id)
                if row_to_remove: # Rebuild the list by filtering out the deleted item by its unique ID
                    self.all_history_data = [row for row in self.all_history_data if row.get('id') != row_to_remove.get('id')]
                custom_dialogs.show_info(self, "Success", "History entry deleted.")
            else:
                custom_dialogs.show_error(self, "Error", "Could not delete the history entry. It may have already been deleted.")
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"An error occurred while deleting the entry:\n{e}")

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
            custom_dialogs.show_error(self, "Error", "Failed to update favorite status.")

    def _show_context_menu(self, event):
        """Dynamically builds and shows the right-click context menu for a treeview row."""
        if not self.tree: return
        row_id = self.tree.identify_row(event.y)
        if not row_id: return

        # Select the row that was right-clicked
        self.tree.selection_set(row_id)
        self._on_row_select() # Update the details pane

        # Find full data to configure menu
        full_row_data = self.iid_map.get(row_id)
        if not full_row_data: return

        # Clear the existing menu
        self.context_menu.delete(0, tk.END)

        # --- Build the menu dynamically ---
        self.context_menu.add_command(label="Copy Original Prompt", command=lambda: self._copy_selected_prompt_part('original_prompt'))
        self.context_menu.add_command(label="Copy Enhanced Prompt", command=lambda: self._copy_selected_prompt_part('enhanced_prompt'))
        self.context_menu.add_command(label="Copy Negative Prompt", command=lambda: self._copy_selected_prompt_part('negative_prompt'))
        
        # Add variations if they exist
        variations = full_row_data.get('variations', {})
        if variations:
            self.context_menu.add_separator()
            # Sort to ensure consistent order
            for var_key in sorted(variations.keys()):
                # Get the friendly name from the map, fall back to the key
                var_name = self.available_variations_map.get(var_key, var_key.capitalize())
                self.context_menu.add_command(label=f"Copy {var_name} Variation", command=lambda k=var_key: self._copy_selected_prompt_part(f"{k}_variation"))
        
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Copy Template Name", command=lambda: self._copy_selected_prompt_part('template_name'))
        self.context_menu.add_command(label="Load to Main Window", command=self._load_to_main_window)
        self.context_menu.add_separator()
        
        # Favorite toggle
        is_fav = full_row_data.get('favorite', False)
        fav_label = "Unfavorite ⭐" if is_fav else "Favorite ⭐"
        self.context_menu.add_command(label=fav_label, command=self._toggle_favorite)
        
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Delete Entry", command=self._delete_selected_history)

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
            if part_key in ['original_prompt', 'enhanced_prompt', 'negative_prompt', 'template_name']:
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

    def _enter_edit_mode(self, key: str):
        """Enables editing for a specific prompt text widget."""
        tab_controls = self.detail_tabs.get(key)
        if not tab_controls: return

        text_widget = tab_controls['text']
        
        # Store original content for cancellation
        self.original_edit_content = text_widget.get("1.0", "end-1c")
        
        text_widget.config(state=tk.NORMAL)
        text_widget.focus_set()

        tab_controls['edit_button'].pack_forget()
        tab_controls['update_button'].pack(side=tk.LEFT, padx=(0, 5))
        tab_controls['cancel_button'].pack(side=tk.LEFT)

    def _cancel_edit_mode(self, key: str, force: bool = False):
        """Disables editing and reverts changes if necessary."""
        tab_controls = self.detail_tabs.get(key)
        if not tab_controls or 'edit_button' not in tab_controls: return

        text_widget = tab_controls['text']
        
        # Only revert if not forced (i.e., user clicked cancel)
        if not force and hasattr(self, 'original_edit_content'):
            text_widget.config(state=tk.NORMAL) # Enable to modify
            text_widget.delete("1.0", tk.END)
            text_widget.insert("1.0", self.original_edit_content)

        text_widget.config(state=tk.DISABLED)

        tab_controls['update_button'].pack_forget()
        tab_controls['cancel_button'].pack_forget()
        tab_controls['edit_button'].pack(side=tk.LEFT)
        
        if hasattr(self, 'original_edit_content'):
            del self.original_edit_content

    def _update_edited_prompt(self, key: str):
        """Saves the edited prompt to history."""
        tab_controls = self.detail_tabs.get(key)
        if not tab_controls or not self.tree: return

        selected_items = self.tree.selection()
        if not selected_items: return
        item_id = selected_items[0]

        original_row = self.iid_map.get(item_id)
        if not original_row: return

        new_text = tab_controls['text'].get("1.0", "end-1c").strip()
        if not new_text:
            custom_dialogs.show_warning(self, "Warning", "Prompt cannot be empty.")
            return

        updated_row = original_row.copy()
        if key == 'enhanced':
            updated_row['enhanced_prompt'] = new_text
        elif key == 'negative':
            updated_row['negative_prompt'] = new_text
        else:
            return # Should not happen

        success = self.processor.update_history_entry(original_row, updated_row)
        if success:
            # Update the in-memory data
            self.iid_map[item_id] = updated_row
            for i, row in enumerate(self.all_history_data):
                # Use the unique ID for a robust match
                if row.get('id') and row.get('id') == original_row.get('id'):
                    self.all_history_data[i] = updated_row
                    break
            
            # Update the visible row in the treeview
            if key == 'enhanced':
                self.tree.set(item_id, 'enhanced_prompt', new_text)
            
            # Exit edit mode
            self._cancel_edit_mode(key, force=True)
            custom_dialogs.show_info(self, "Success", "Prompt updated successfully.")
        else:
            custom_dialogs.show_error(self, "Error", "Failed to update the prompt in the history file.")