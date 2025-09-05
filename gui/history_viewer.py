"""A window to view and search the prompt generation history."""

import tkinter as tk
from tkinter import ttk
import json
import queue
import random
import threading
import tkinter.font as tkfont
import copy
import sys
import os
from PIL import Image, ImageTk
from typing import List, Dict, Optional, TYPE_CHECKING, Any
from . import custom_dialogs
from core.config import config
from core.config import config
from core.prompt_processor import PromptProcessor
from .common import TextContextMenu, SmartWindowMixin

if TYPE_CHECKING:
    from .gui_app import GUIApp
    from .image_generation_dialog import ImageGenerationOptionsDialog
    from .image_preview_dialog import ImagePreviewDialog

class HistoryViewerWindow(tk.Toplevel, SmartWindowMixin):
    """A window to view and search the prompt generation history."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor):
        super().__init__(parent)
        self.title("Prompt History Viewer")

        self.processor = processor
        self.parent_app = parent
        self.all_history_data: List[Dict[str, str]] = []
        
        # --- Attributes for the new Canvas-based list ---
        self.history_canvas: Optional[tk.Canvas] = None
        self.history_container: Optional[ttk.Frame] = None
        self.history_widgets: List[Dict[str, Any]] = [] # Stores {'frame': widget, 'label': widget, 'data': row_data}
        self.selected_item_frame: Optional[ttk.Frame] = None
        self.selected_row_data: Optional[Dict[str, Any]] = None

        self.show_favorites_only_var = tk.BooleanVar(value=False)
        self.details_notebook: Optional[ttk.Notebook] = None
        self.filter_debounce_timer: Optional[str] = None
        self.detail_tabs: Dict[str, Dict[str, Any]] = {}
        self.original_edit_content: Optional[str] = None
        self.image_ref: Optional[ImageTk.PhotoImage] = None
        self.image_gen_queue = queue.Queue()
        self.image_gen_after_id: Optional[str] = None
        self.available_variations_map = {v['key']: v['name'] for v in self.processor.get_available_variations()}
        self.context_menu = tk.Menu(self, tearoff=0)

        self._create_styles()
        self._create_widgets()
        self.load_and_display_history()

        self.smart_geometry(min_width=1200, min_height=800)
        self.image_gen_after_id = self.after(100, self._check_image_gen_queue)

    def _create_styles(self):
        """Creates custom ttk styles for the history list."""
        style = ttk.Style()
        is_dark = self.parent_app.theme_manager.current_theme == "dark"
        
        # Base style for the item frame
        style.configure("HistoryItem.TFrame", padding=5)
        
        # Style for a selected item frame
        selected_bg = '#4a90e2' if is_dark else '#d8e9f3'
        style.configure("Selected.HistoryItem.TFrame", background=selected_bg)

        # Style for the prompt label
        style.configure("HistoryPrompt.TLabel")
        
        # Style for a favorite prompt label
        favorite_fg = "#FFD700" # Gold
        style.configure("Favorite.HistoryPrompt.TLabel", foreground=favorite_fg, font=tkfont.Font(family="Helvetica", size=config.font_size, weight="bold"))

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

        favorites_check = ttk.Checkbutton(search_frame, text="Favorites Only ⭐", variable=self.show_favorites_only_var, command=self._apply_filters)
        favorites_check.pack(side=tk.LEFT, padx=5)

        # --- Main Horizontal Pane ---
        h_pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        h_pane.pack(fill=tk.BOTH, expand=True)

        # --- History Table (Left Pane) ---
        list_frame = ttk.Frame(h_pane, padding=5)
        h_pane.add(list_frame, weight=2) # Give it less weight as it's narrower now

        # --- NEW: Create Canvas instead of Treeview ---
        self.history_canvas = tk.Canvas(list_frame, borderwidth=0, highlightthickness=0)
        history_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.history_canvas.yview)
        self.history_container = ttk.Frame(self.history_canvas)
        self.history_canvas.configure(yscrollcommand=history_scrollbar.set)
        
        history_scrollbar.pack(side="right", fill="y")
        self.history_canvas.pack(side="left", fill="both", expand=True)
        history_canvas_frame = self.history_canvas.create_window((0, 0), window=self.history_container, anchor="nw")

        def on_history_frame_configure(event):
            self.history_canvas.configure(scrollregion=self.history_canvas.bbox("all"))

        def on_history_canvas_configure(event):
            self.history_canvas.itemconfig(history_canvas_frame, width=event.width)
            # Adjust wraplength of all visible prompt labels
            for widget_info in self.history_widgets:
                if widget_info['frame'].winfo_ismapped():
                    widget_info['label'].configure(wraplength=event.width - 20) # -20 for padding

        self.history_container.bind("<Configure>", on_history_frame_configure)
        self.history_canvas.bind("<Configure>", on_history_canvas_configure)

        # --- Right Pane (for details and image) ---
        right_pane = ttk.Frame(h_pane, padding=5)
        h_pane.add(right_pane, weight=2)

        # This will hold the image preview at the top and the prompt details below
        v_pane_right = ttk.PanedWindow(right_pane, orient=tk.VERTICAL)
        v_pane_right.pack(fill=tk.BOTH, expand=True)

        # --- Image Preview (Top of Right Pane) ---
        image_frame = ttk.LabelFrame(v_pane_right, text="Image Preview", padding=5)
        v_pane_right.add(image_frame, weight=3) # Give more space to the image
        self.image_label = ttk.Label(image_frame, text="No image generated for this entry.", anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)

        # --- Details View (Bottom of Right Pane) ---
        details_frame = ttk.LabelFrame(v_pane_right, text="Selected Prompt Details", padding=5)
        v_pane_right.add(details_frame, weight=3)

        self.details_notebook = ttk.Notebook(details_frame)
        self.details_notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.details_notebook.pack(fill=tk.BOTH, expand=True)

        # Create the static tabs that are always present.
        # Variation tabs will be created dynamically as needed.
        self._create_detail_tab('original', 'Original')
        self._create_detail_tab('enhanced', 'Enhanced')

    def load_and_display_history(self):
        """Loads data from the history file and populates the list."""
        self.all_history_data = self.processor.get_full_history()
        self._populate_history_list(self.all_history_data)

    def _populate_history_list(self, data: List[Dict[str, str]]):
        """Clears and fills the history list with the given data."""
        if not self.history_container: return
        
        # Clear old widgets
        for widget_info in self.history_widgets:
            widget_info['frame'].destroy()
        self.history_widgets.clear()
        self.selected_item_frame = None
        self.selected_row_data = None

        current_width = self.history_canvas.winfo_width()

        for row in data:
            original_prompt = row.get('original_prompt', 'No original prompt found.')
            is_fav = row.get('favorite', False)

            # Create a frame for each item for better layout and binding
            item_frame = ttk.Frame(self.history_container, style="HistoryItem.TFrame", relief="groove", borderwidth=1)
            item_frame.pack(fill=tk.X, pady=2, padx=2)

            # Create and pack the main prompt label
            label_style = "Favorite.HistoryPrompt.TLabel" if is_fav else "HistoryPrompt.TLabel"
            prompt_label = ttk.Label(item_frame, text=original_prompt, style=label_style, wraplength=current_width - 20, anchor="w", justify="left")
            prompt_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)

            # Store widget and data together
            widget_info = {'frame': item_frame, 'label': prompt_label, 'data': row}
            self.history_widgets.append(widget_info)

            # Bind events to the frame and its labels
            right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
            for widget in [item_frame, prompt_label]:
                widget.bind("<Button-1>", lambda e, info=widget_info: self._on_item_select(info))
                widget.bind("<Double-1>", lambda e, info=widget_info: self._load_to_main_window())
                widget.bind(right_click_event, lambda e, info=widget_info: self._show_context_menu(e, info))
                # Make mousewheel work on the labels too
                widget.bind("<MouseWheel>", lambda e: self.history_canvas.yview_scroll(-1 * (e.delta if sys.platform == 'darwin' else e.delta // 120), "units"))

    def _apply_filters(self):
        """Shows or hides list items based on the current filter criteria."""
        if not self.history_container: return
        
        search_term = self.search_var.get().lower()
        show_favorites_only = self.show_favorites_only_var.get()

        for widget_info in self.history_widgets:
            row_data = widget_info['data']
            is_favorite_match = not show_favorites_only or row_data.get('favorite')

            original_prompt = str(row_data.get('original_prompt', '')).lower()
            enhanced_prompt = str(row_data.get('enhanced', {}).get('prompt', '')).lower()
            is_search_match = not search_term or (search_term in original_prompt or search_term in enhanced_prompt)
            
            if is_favorite_match and is_search_match:
                widget_info['frame'].pack(fill=tk.X, pady=2, padx=2) # Show it
            else:
                widget_info['frame'].pack_forget() # Hide it

    def _schedule_filter_update(self):
        """Schedules a filter update after a short delay to avoid excessive updates during typing."""
        if self.filter_debounce_timer:
            self.after_cancel(self.filter_debounce_timer)
        self.filter_debounce_timer = self.after(300, self._apply_filters) # 300ms delay

    def _on_item_select(self, selected_widget_info: Dict[str, Any]):
        """Handles selection of an item in the custom list."""
        if not self.details_notebook: return

        # --- Visual Selection Highlighting ---
        # Deselect the previously selected frame
        if self.selected_item_frame and self.selected_item_frame.winfo_exists():
            self.selected_item_frame.config(style="HistoryItem.TFrame")
        
        # Select the new frame
        self.selected_item_frame = selected_widget_info['frame']
        self.selected_item_frame.config(style="Selected.HistoryItem.TFrame")
        
        # Store the data for other methods to use (delete, favorite, etc.)
        self.selected_row_data = selected_widget_info['data']
        full_row_data = self.selected_row_data

        # Before doing anything, ensure we exit edit mode if it was active
        if 'edit_button' in self.detail_tabs['enhanced']:
            self._cancel_edit_mode('enhanced', force=True)
        
        # Forget all tabs to ensure a clean slate for each selection
        for tab_id in self.details_notebook.tabs():
            self.details_notebook.forget(tab_id)

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
        display_order = ['original', 'enhanced']
        if 'variations' in full_row_data:
            display_order.extend(sorted(full_row_data['variations'].keys()))

        # 2. Iterate and display tabs
        for key in display_order:
            prompt = ""
            model = ""
            data_exists = False
            generation_params = None
            image_path_for_model_check = None

            if key == 'original':
                prompt = full_row_data.get('original_prompt', '')
                if prompt: data_exists = True
            elif key == 'enhanced':
                enhanced_data = full_row_data.get('enhanced', {})
                prompt = enhanced_data.get('prompt', '')
                model = enhanced_data.get('sd_model', '')
                generation_params = enhanced_data.get('generation_params')
                image_path_for_model_check = enhanced_data.get('image_path')
                if prompt: data_exists = True
            else: # It's a variation
                var_data = full_row_data.get('variations', {}).get(key)
                if var_data:
                    prompt = var_data.get('prompt', '')
                    model = var_data.get('sd_model', '')
                    generation_params = var_data.get('generation_params')
                    image_path_for_model_check = var_data.get('image_path')
                    if prompt: data_exists = True
            
            if data_exists:
                # 3. Ensure the tab widgets exist, creating them if necessary
                if key not in self.detail_tabs:
                    self._create_detail_tab(key, key.capitalize() if key not in ['negative', 'params'] else 'Negative' if key == 'negative' else 'Parameters')

                tab = self.detail_tabs[key]
                
                # Update tab content
                tab['text'].config(state=tk.NORMAL)
                tab['text'].delete("1.0", tk.END)
                tab['text'].insert("1.0", prompt)
                tab['text'].config(state=tk.DISABLED)
                
                # --- Model Label Logic ---
                model_display_text = ""
                if image_path_for_model_check and generation_params:
                    gen_model_obj = generation_params.get('model', {})
                    gen_model_name = gen_model_obj.get('name', 'Unknown Model')
                    model_display_text = f"Generated with: {gen_model_name}"
                elif model:
                    model_display_text = f"Recommended Model: {model}"
                tab['model_label'].config(text=model_display_text)
                
                # Reset button state based on the current row's data and InvokeAI connection status
                if 'generate_image_button' in tab:
                    can_generate = self.processor.is_invokeai_connected()

                    if not can_generate:
                        # If InvokeAI isn't configured, hide the button entirely.
                        tab['generate_image_button'].pack_forget()
                    else:
                        # Otherwise, ensure it's visible and set its state.
                        tab['generate_image_button'].pack(side=tk.LEFT, padx=(5,0))
                        image_path = None
                        if key == 'original':
                            image_path = full_row_data.get('original_image_path')
                        if key == 'enhanced':
                            image_path = full_row_data.get('enhanced', {}).get('image_path')
                        elif key in full_row_data.get('variations', {}):
                            image_path = full_row_data['variations'][key].get('image_path')
                        
                        if image_path:
                            tab['generate_image_button'].config(text="Regenerate Image", state=tk.NORMAL)
                        else:
                            tab['generate_image_button'].config(text="Generate Image", state=tk.NORMAL)

                # Add tab to notebook
                self.details_notebook.add(self.detail_tabs[key]['frame'], text=self.detail_tabs[key]['title'])
        
        # After populating tabs, show the image for the first available tab with an image
        self._update_image_for_current_tab()

    def _on_tab_changed(self, event=None):
        """Updates the image preview when the user switches tabs."""
        self._update_image_for_current_tab()

    def _update_image_for_current_tab(self):
        """Finds the image for the currently selected tab and displays it."""
        if not self.selected_row_data or not self.details_notebook:
            self._clear_image_preview()
            return
        
        full_row_data = self.selected_row_data
        if not full_row_data:
            self._clear_image_preview()
            return

        try:
            selected_tab_id = self.details_notebook.select()
            selected_tab_widget = self.details_notebook.nametowidget(selected_tab_id)
        except tk.TclError:
            return # Tab might be gone

        image_path = None
        for key, tab_info in self.detail_tabs.items():
            if tab_info['frame'] == selected_tab_widget:
                if key == 'original':
                    image_path = full_row_data.get('original_image_path')
                if key == 'enhanced':
                    image_path = full_row_data.get('enhanced', {}).get('image_path')
                elif key in full_row_data.get('variations', {}):
                    image_path = full_row_data['variations'][key].get('image_path')
                break
        
        self._display_image(image_path)

    def _display_image(self, relative_image_path: Optional[str]):
        """Loads and displays an image in the preview pane."""
        if not relative_image_path:
            self._clear_image_preview()
            return

        try:
            # The path in history is relative to the workflow's history folder
            full_path = os.path.join(config.get_history_file_dir(), relative_image_path)
            if not os.path.exists(full_path):
                self.image_label.config(text=f"Image not found:\n{relative_image_path}", image='')
                self.image_ref = None # Clear the reference
                return

            img = Image.open(full_path)
            img.thumbnail((400, 400)) # Resize for display
            self.image_ref = ImageTk.PhotoImage(img)
            self.image_label.config(image=self.image_ref, text="")
        except Exception as e:
            self.image_label.config(text=f"Error loading image:\n{e}", image='')
            self.image_ref = None

    def _generate_image_from_history(self, key: str):
        """Starts the image generation process for a prompt from the history."""
        if not self.selected_row_data: return
        full_row_data = self.selected_row_data

        prompt = ""
        # Start with the global default negative prompt.
        negative_prompt = config.DEFAULT_NEGATIVE_PROMPT

        if key == 'original':
            prompt = full_row_data.get('original_prompt', '')
        if key == 'enhanced':
            enhanced_data = full_row_data.get('enhanced', {})
            prompt = enhanced_data.get('prompt', '')
            # If generation params exist for this prompt, use its negative prompt.
            if 'generation_params' in enhanced_data:
                negative_prompt = enhanced_data['generation_params'].get('negative_prompt', negative_prompt)
        elif key in full_row_data.get('variations', {}):
            variation_data = full_row_data['variations'][key]
            prompt = variation_data.get('prompt', '')
            # If generation params exist for this variation, use its negative prompt.
            if 'generation_params' in variation_data:
                negative_prompt = variation_data['generation_params'].get('negative_prompt', negative_prompt)
        
        if not prompt:
            custom_dialogs.show_error(self, "Error", "No prompt available to generate an image.")
            return

        try:
            from .image_generation_dialog import ImageGenerationOptionsDialog
            dialog = ImageGenerationOptionsDialog(self, self.processor.invokeai_client, initial_negative_prompt=negative_prompt)
            options = dialog.result
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not open image generation options:\n{e}")
            return

        if not options:
            return # User cancelled

        # Disable the button
        if key in self.detail_tabs and 'generate_image_button' in self.detail_tabs[key]:
            self.detail_tabs[key]['generate_image_button'].config(state=tk.DISABLED, text="Generating...")
        
        def task():
            try:
                seed = random.randint(0, 2**32 - 1)
                gen_args = {
                    "prompt": prompt,
                    "negative_prompt": options["negative_prompt"],
                    "seed": seed,
                    "model_object": options["model"],
                    "loras": options["loras"],
                    "steps": options["steps"],
                    "cfg_scale": options["cfg_scale"],
                    "scheduler": options["scheduler"],
                }
                image_bytes = self.processor.generate_image_with_invokeai(**gen_args)
                self.image_gen_queue.put({'success': True, 'key': key, 'bytes': image_bytes, 'prompt': prompt, 'generation_params': options})
            except Exception as e:
                self.image_gen_queue.put({'success': False, 'key': key, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()

    def _check_image_gen_queue(self):
        """Checks for image generation results and updates the UI."""
        if not self.winfo_exists():
            return

        try:
            result = self.image_gen_queue.get_nowait()
            key = result['key']
            
            # Re-enable the button on failure
            if not result['success']:
                custom_dialogs.show_error(self, "Image Generation Error", f"Failed to generate image:\n{result['error']}")
                if key in self.detail_tabs and 'generate_image_button' in self.detail_tabs[key]:
                    self.detail_tabs[key]['generate_image_button'].config(state=tk.NORMAL, text="Generate Image")
                return

            # Open the preview dialog
            from .image_preview_dialog import ImagePreviewDialog
            preview_dialog = ImagePreviewDialog(self, result['bytes'], result['prompt'])
            
            if preview_dialog.result: # User clicked "Save to History"
                # Get the currently selected row to update it
                if not self.selected_row_data: return
                original_row = self.selected_row_data
                if not original_row: return

                # Save the image and get the path
                image_path = self.processor.save_generated_image(result['bytes'])
                generation_params = result.get('generation_params')
                
                # Create a copy to modify and save
                updated_row = copy.deepcopy(original_row)
                
                # Store image path and params with the specific prompt that generated it
                if key == 'original':
                    updated_row['original_image_path'] = image_path
                    updated_row['original_generation_params'] = generation_params
                if key == 'enhanced':
                    if 'enhanced' not in updated_row: updated_row['enhanced'] = {}
                    updated_row['enhanced']['image_path'] = image_path
                    updated_row['enhanced']['generation_params'] = generation_params
                elif key in updated_row.get('variations', {}):
                    updated_row['variations'][key]['image_path'] = image_path
                    updated_row['variations'][key]['generation_params'] = generation_params
                
                # Save the updated history entry
                success = self.processor.update_history_entry(original_row, updated_row)
                if success:
                    # Update in-memory data
                    self.selected_row_data = updated_row
                    for i, row in enumerate(self.all_history_data):
                        if row.get('id') == original_row.get('id'):
                            self.all_history_data[i] = updated_row
                            break
                    
                    custom_dialogs.show_info(self, "Image Saved", f"Image saved and history updated for '{key}' prompt.")
                    if key in self.detail_tabs and 'generate_image_button' in self.detail_tabs[key]:
                        self.detail_tabs[key]['generate_image_button'].config(text="Image Saved") # Don't re-enable, it's done.
                    
                    # Refresh the image preview
                    self._display_image(image_path)
                else:
                    custom_dialogs.show_error(self, "History Update Error", "Could not update the history file with the new image path.")
                    if key in self.detail_tabs and 'generate_image_button' in self.detail_tabs[key]:
                        self.detail_tabs[key]['generate_image_button'].config(state=tk.NORMAL, text="Generate Image")

            else: # User clicked "Discard"
                if key in self.detail_tabs and 'generate_image_button' in self.detail_tabs[key]:
                    self.detail_tabs[key]['generate_image_button'].config(state=tk.NORMAL, text="Generate Image") # Re-enable
        
        except queue.Empty:
            pass
        except tk.TclError:
            # This can happen if the window is destroyed while the queue is being processed.
            # We can safely ignore it and stop the loop.
            return
        finally:
            if self.winfo_exists():
                self.image_gen_after_id = self.after(100, self._check_image_gen_queue)

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

        # Store base widgets
        self.detail_tabs[key] = {'frame': frame, 'text': text_widget, 'title': title}

        bottom_bar = ttk.Frame(frame)
        bottom_bar.pack(fill=tk.X, pady=(5,0))

        button_container = ttk.Frame(bottom_bar)
        button_container.pack(side=tk.RIGHT)

        model_label = ttk.Label(bottom_bar, text="", font=self.parent_app.small_font, foreground="gray")
        model_label.pack(side=tk.LEFT, anchor='w', fill=tk.X, expand=True)

        self.detail_tabs[key].update({'model_label': model_label, 'button_container': button_container})

        # Special handling for the 'enhanced' and 'negative' tab's edit buttons
        if key == 'enhanced':
            edit_button = ttk.Button(button_container, text="Edit", command=lambda k=key: self._enter_edit_mode(k))
            update_button = ttk.Button(button_container, text="Update", style="Accent.TButton", command=lambda k=key: self._update_edited_prompt(k))
            cancel_button = ttk.Button(button_container, text="Cancel", command=lambda k=key: self._cancel_edit_mode(k))
            
            self.detail_tabs[key].update({'edit_button': edit_button, 'update_button': update_button, 'cancel_button': cancel_button})
            edit_button.pack(side=tk.LEFT)

        # Add a "Generate Image" button placeholder for relevant tabs
        if key not in ['negative', 'params']:
            generate_image_button = ttk.Button(button_container, text="Generate Image", command=lambda k=key: self._generate_image_from_history(k))
            self.detail_tabs[key]['generate_image_button'] = generate_image_button
            # The button is packed/unpacked dynamically in _on_row_select to ensure consistent state.

    def _clear_image_preview(self):
        """Resets the image preview to its default state."""
        self.image_label.config(image='', text="No image generated for this entry.")
        self.image_ref = None

    def _on_double_click(self, event=None):
        """Handles double-click on an item to load it into the main window."""
        self._load_to_main_window()

    def _delete_selected_history(self):
        """Deletes the selected row from the history file and the view."""
        if not self.selected_row_data:
            return

        full_row_data = self.selected_row_data

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
                # Remove from the view and internal data cache
                widget_to_remove = None
                for widget_info in self.history_widgets:
                    if widget_info['data'].get('id') == full_row_data.get('id'):
                        widget_to_remove = widget_info
                        break
                
                if widget_to_remove:
                    widget_to_remove['frame'].destroy()
                    self.history_widgets.remove(widget_to_remove)
                    if self.selected_item_frame == widget_to_remove['frame']:
                        self.selected_item_frame = None
                        self.selected_row_data = None

                self.all_history_data = [row for row in self.all_history_data if row.get('id') != full_row_data.get('id')]
                custom_dialogs.show_info(self, "Success", "History entry deleted.")
            else:
                custom_dialogs.show_error(self, "Error", "Could not delete the history entry. It may have already been deleted.")
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"An error occurred while deleting the entry:\n{e}")

    def _toggle_favorite(self):
        """Toggles the favorite status of the selected item."""
        if not self.selected_row_data: return
        original_row = self.selected_row_data
        if not original_row: return

        # Create a copy to modify
        updated_row = original_row.copy()
        current_status = updated_row.get('favorite', False)
        updated_row['favorite'] = not current_status

        # Update the CSV file
        success = self.processor.update_history_entry(original_row, updated_row)
        if success:
            # Update the in-memory data
            self.selected_row_data = updated_row
            for i, row in enumerate(self.all_history_data):
                if row.get('id') == original_row.get('id'):
                    self.all_history_data[i] = updated_row
                    break
            
            # Update the visible row directly in the list
            is_fav = updated_row.get('favorite')
            for widget_info in self.history_widgets:
                if widget_info['data'].get('id') == original_row.get('id'):
                    new_style = "Favorite.HistoryPrompt.TLabel" if is_fav else "HistoryPrompt.TLabel"
                    widget_info['label'].config(style=new_style)
                    # If the favorites filter is on, the item might need to be hidden
                    if self.show_favorites_only_var.get() and not is_fav:
                        widget_info['frame'].pack_forget()
                    break
        else:
            custom_dialogs.show_error(self, "Error", "Failed to update favorite status.")

    def _show_context_menu(self, event, selected_widget_info: Dict[str, Any]):
        """Dynamically builds and shows the right-click context menu for a list item."""
        self._on_item_select(selected_widget_info)
        full_row_data = selected_widget_info['data']
        if not full_row_data: return

        self.context_menu.delete(0, tk.END)

        # --- Build the menu dynamically ---
        self.context_menu.add_command(label="Copy Original Prompt", command=lambda: self._copy_selected_prompt_part('original_prompt'))
        self.context_menu.add_command(label="Copy Enhanced Prompt", command=lambda: self._copy_selected_prompt_part('enhanced_prompt'))
        
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
        if not self.selected_row_data: return
        full_row_data = self.selected_row_data
        if full_row_data:
            content_to_copy = ""
            if part_key in ['original_prompt', 'template_name']:
                content_to_copy = full_row_data.get(part_key, '')
            elif part_key == 'enhanced_prompt': # Match the key used in the context menu
                content_to_copy = full_row_data.get('enhanced', {}).get('prompt', '')
            else: # It's a variation
                var_type = part_key.replace('_variation', '')
                content_to_copy = full_row_data.get('variations', {}).get(var_type, {}).get('prompt', '')

            if content_to_copy:
                self.clipboard_clear()
                self.clipboard_append(content_to_copy)

    def _load_to_main_window(self):
        """Sends the selected original prompt back to the main app for re-enhancement."""
        if not self.selected_row_data: return
        full_row_data = self.selected_row_data
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
        if not tab_controls or not self.selected_row_data: return
        original_row = self.selected_row_data
        if not original_row: return

        new_text = tab_controls['text'].get("1.0", "end-1c").strip()
        if not new_text:
            custom_dialogs.show_warning(self, "Warning", "Prompt cannot be empty.")
            return

        updated_row = copy.deepcopy(original_row)
        if key == 'enhanced':
            if 'enhanced' not in updated_row: updated_row['enhanced'] = {}
            updated_row['enhanced']['prompt'] = new_text
        else:
            return # Should not happen

        success = self.processor.update_history_entry(original_row, updated_row)
        if success:
            # Update the in-memory data
            self.selected_row_data = updated_row
            for i, row in enumerate(self.all_history_data):
                # Use the unique ID for a robust match
                if row.get('id') and row.get('id') == original_row.get('id'):
                    self.all_history_data[i] = updated_row
                    break
            
            # Exit edit mode
            self._cancel_edit_mode(key, force=True)
            custom_dialogs.show_info(self, "Success", "Prompt updated successfully.")
        else:
            custom_dialogs.show_error(self, "Error", "Failed to update the prompt in the history file.")