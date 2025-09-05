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
from typing import List, Dict, Optional, TYPE_CHECKING, Any, Tuple
from . import custom_dialogs
from core.config import config
from core.prompt_processor import PromptProcessor
from .common import TextContextMenu, SmartWindowMixin, LoadingAnimation
from .common import Tooltip

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
        self.image_tooltip: Optional[Tooltip] = None
        self.image_tooltip_after_id: Optional[str] = None
        self.current_images: List[Dict[str, Any]] = []
        self.current_image_index: int = 0
        self.image_gen_queue = queue.Queue()
        self.image_gen_after_id: Optional[str] = None
        self.available_variations_map = {v['key']: v['name'] for v in self.processor.get_available_variations()}
        self.context_menu = tk.Menu(self, tearoff=0)

        self._create_styles()
        self._create_widgets()
        self.load_and_display_history()

        self.smart_geometry(min_width=1200, min_height=800)
        self.image_gen_after_id = self.after(100, self._check_image_gen_queue)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        """Safely close the window, cancelling any pending after() jobs."""
        if self.image_gen_after_id:
            self.after_cancel(self.image_gen_after_id)
            self.image_gen_after_id = None
        self.destroy()

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

        prune_button = ttk.Button(search_frame, text="Prune History", command=self._prune_history)
        prune_button.pack(side=tk.RIGHT, padx=(5,0))

        gc_button = ttk.Button(search_frame, text="Garbage Collect Images", command=self._garbage_collect_images)
        gc_button.pack(side=tk.RIGHT)

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

        # Create a frame for pagination controls at the bottom of the image frame and pack it first.
        self.pagination_frame = ttk.Frame(image_frame)
        self.pagination_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))

        # Create a container for the image itself to center it
        image_container = ttk.Frame(image_frame)
        image_container.pack(fill=tk.BOTH, expand=True)
        self.image_label = ttk.Label(image_container, text="No image generated for this entry.", anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        self.image_tooltip = Tooltip(self.image_label)
        self.image_label.bind("<Enter>", self._schedule_image_tooltip)
        self.image_label.bind("<Leave>", self._hide_image_tooltip)

        # Create the pagination widgets inside their frame. They will be managed later.
        self.prev_button = ttk.Button(self.pagination_frame, text="< Prev", command=self._prev_image)

        self.image_info_label = ttk.Label(self.pagination_frame, text="", anchor=tk.CENTER)

        self.next_button = ttk.Button(self.pagination_frame, text="Next >", command=self._next_image)

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
            images = []

            if key == 'original':
                prompt = full_row_data.get('original_prompt', '')
                images = full_row_data.get('original_images', [])
                if prompt: data_exists = True
            elif key == 'enhanced':
                enhanced_data = full_row_data.get('enhanced', {})
                prompt = enhanced_data.get('prompt', '')
                model = enhanced_data.get('sd_model', '')
                images = enhanced_data.get('images', [])
                if prompt: data_exists = True
            else: # It's a variation
                var_data = full_row_data.get('variations', {}).get(key)
                if var_data:
                    prompt = var_data.get('prompt', '')
                    model = var_data.get('sd_model', '')
                    images = var_data.get('images', [])
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
                if images:
                    first_image_params = images[0].get('generation_params', {})
                    gen_model_obj = first_image_params.get('model', {})
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
                        tab['gen_image_frame'].pack_forget()
                    else:
                        # Otherwise, ensure it's visible and set its state.
                        tab['gen_image_frame'].pack(side=tk.LEFT, padx=(5,0))
                        
                        if images:
                            tab['generate_image_button'].config(text=f"Regen ({len(images)})", state=tk.NORMAL)
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

        images = None
        for key, tab_info in self.detail_tabs.items():
            if tab_info['frame'] == selected_tab_widget:
                if key == 'original':
                    images = full_row_data.get('original_images')
                elif key == 'enhanced':
                    images = full_row_data.get('enhanced', {}).get('images')
                elif key in full_row_data.get('variations', {}):
                    images = full_row_data['variations'][key].get('images')
                break
        
        self._display_images(images)

    def _display_images(self, images: Optional[List[Dict[str, Any]]]):
        """Loads a list of images and displays the first one."""
        if not images:
            self._clear_image_preview()
            return

        self.current_images = images
        self.current_image_index = 0
        
        # Always forget everything first for a clean slate
        self.prev_button.pack_forget()
        self.next_button.pack_forget()
        self.image_info_label.pack_forget()

        # Pack controls. The info label will fill the space between the buttons.
        if len(self.current_images) > 1:
            self.prev_button.pack(side=tk.LEFT, padx=5)
            self.next_button.pack(side=tk.RIGHT, padx=5)
        
        # The info label should always be visible if there are images.
        self.image_info_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            
        self._show_current_image()

    def _show_current_image(self):
        """Loads and displays an image in the preview pane."""
        if not self.current_images:
            self._clear_image_preview()
            return

        image_data = self.current_images[self.current_image_index]
        relative_image_path = image_data.get('image_path')
        
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
            
            # Update pagination info
            gen_params = image_data.get('generation_params', {})
            model_name = gen_params.get('model', {}).get('name', 'Unknown Model')
            info_text = f"({self.current_image_index + 1}/{len(self.current_images)}) Model: {model_name}"
            self.image_info_label.config(text=info_text)
            
            # Update tooltip with all params
            if gen_params:
                # Exclude the large model object from the tooltip for clarity
                params_for_tooltip = {k: v for k, v in gen_params.items() if k not in ['model', 'models', 'loras']}
                # Handle loras separately to make it readable
                lora_info = gen_params.get('loras', [])
                if lora_info:
                    lora_names = [f"{l['lora_object']['name']} (w: {l['weight']})" for l in lora_info]
                    params_for_tooltip['loras'] = ", ".join(lora_names)
                
                self.image_tooltip.text = "Generation Parameters:\n" + "\n".join([f"- {key}: {value}" for key, value in params_for_tooltip.items()])
            else:
                self.image_tooltip.text = "No generation parameters found."

            self.prev_button.config(state=tk.NORMAL if self.current_image_index > 0 else tk.DISABLED)
            self.next_button.config(state=tk.NORMAL if self.current_image_index < len(self.current_images) - 1 else tk.DISABLED)

        except Exception as e:
            self.image_label.config(text=f"Error loading image:\n{e}", image='')
            self.image_ref = None

    def _next_image(self):
        if self.current_image_index < len(self.current_images) - 1:
            self.current_image_index += 1
            self._show_current_image()

    def _prev_image(self):
        if self.current_image_index > 0:
            self.current_image_index -= 1
            self._show_current_image()

    def _schedule_image_tooltip(self, event):
        """Schedules a tooltip to appear over the image after a delay."""
        if self.image_tooltip_after_id:
            self.after_cancel(self.image_tooltip_after_id)
        
        # Only schedule if there's actually an image displayed
        if self.image_ref:
            self.image_tooltip_after_id = self.after(500, lambda: self.image_tooltip.show(event))

    def _hide_image_tooltip(self, event=None):
        """Hides the image tooltip and cancels any scheduled appearance."""
        if self.image_tooltip_after_id:
            self.after_cancel(self.image_tooltip_after_id)
            self.image_tooltip_after_id = None
        if self.image_tooltip:
            self.image_tooltip.hide(event)

    def _generate_image_from_history(self, key: str):
        """Starts the image generation process for a prompt from the history."""
        if not self.selected_row_data: return
        full_row_data = self.selected_row_data

        prompt = ""
        # Start with the global default negative prompt.
        negative_prompt = config.DEFAULT_NEGATIVE_PROMPT

        if key == 'original':
            prompt = full_row_data.get('original_prompt', '')
            original_images = full_row_data.get('original_images', [])
            if original_images:
                negative_prompt = original_images[0].get('generation_params', {}).get('negative_prompt', negative_prompt)
        elif key == 'enhanced':
            enhanced_data = full_row_data.get('enhanced', {})
            prompt = enhanced_data.get('prompt', '')
            enhanced_images = enhanced_data.get('images', [])
            if enhanced_images:
                negative_prompt = enhanced_images[0].get('generation_params', {}).get('negative_prompt', negative_prompt)
        elif key in full_row_data.get('variations', {}):
            variation_data = full_row_data['variations'][key]
            prompt = variation_data.get('prompt', '')
            variation_images = variation_data.get('images', [])
            if variation_images:
                negative_prompt = variation_images[0].get('generation_params', {}).get('negative_prompt', negative_prompt)
        
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
        button = self.detail_tabs.get(key, {}).get('generate_image_button')
        spinner = self.detail_tabs.get(key, {}).get('image_gen_spinner')
        if button:
            button.config(state=tk.DISABLED)
        if spinner:
            spinner.pack(side=tk.LEFT, padx=(0, 5))
            spinner.start()
        
        def task():
            generated_images = []
            errors = []
            total_models = len(options['models'])
            seed_for_batch = options["seed"]
            for i, model_object in enumerate(options['models']):
                if button:
                    self.after(0, lambda i=i, t=total_models: button.config(text=f"Generating ({i+1}/{t})..."))
                try:
                    # Create a unique set of generation_params for this specific image
                    current_gen_params = options.copy()
                    current_gen_params['model'] = model_object
                    del current_gen_params['models']
                    
                    gen_args = {
                        "prompt": prompt,
                        "negative_prompt": options["negative_prompt"],
                        "seed": seed_for_batch,
                        "model_object": model_object,
                        "loras": options["loras"],
                        "steps": options["steps"],
                        "cfg_scale": options["cfg_scale"],
                        "scheduler": options["scheduler"],
                        "cfg_rescale_multiplier": options["cfg_rescale_multiplier"],
                    }
                    image_bytes = self.processor.generate_image_with_invokeai(**gen_args)
                    generated_images.append({'bytes': image_bytes, 'prompt': prompt, 'generation_params': current_gen_params})
                except Exception as e:
                    errors.append(f"Model '{model_object.get('name', 'Unknown')}': {e}")
            
            self.image_gen_queue.put({'success': not errors, 'key': key, 'images': generated_images, 'errors': errors})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()

    def _check_image_gen_queue(self):
        """Checks for image generation results and updates the UI."""
        if not self.winfo_exists():
            return

        try:
            result = self.image_gen_queue.get_nowait()
            key = result['key']
            button = self.detail_tabs.get(key, {}).get('generate_image_button')
            spinner = self.detail_tabs.get(key, {}).get('image_gen_spinner')

            if spinner:
                spinner.stop()
                spinner.pack_forget()
            if button:
                button.config(state=tk.NORMAL)
            
            # Handle errors that occurred during generation
            if result.get('errors'):
                error_str = "\n".join(result['errors'])
                custom_dialogs.show_error(self, "Image Generation Errors", f"Some images failed to generate:\n{error_str}")

            # If no images were successful at all, just re-enable the button and stop.
            if not result.get('images'):
                return

            # Open the preview dialog
            from .multi_image_preview_dialog import MultiImagePreviewDialog
            preview_dialog = MultiImagePreviewDialog(self, result['images'])
            images_to_save = preview_dialog.result
            
            # Get the currently selected row to update it. This is needed for both saving and discarding.
            if not self.selected_row_data: return
            original_row = self.selected_row_data
            if not original_row: return

            if images_to_save:  # User clicked "Save Kept Images"
                updated_row = copy.deepcopy(original_row)
                target_obj, image_list_key = self._get_target_object_for_images(updated_row, key)

                if target_obj is None:
                    custom_dialogs.show_error(self, "Internal Error", "Could not determine where to save image data.")
                    if button: button.config(state=tk.NORMAL, text="Regen")
                    return

                final_images = self._build_final_image_list(target_obj, image_list_key, images_to_save)
                target_obj[image_list_key] = final_images
                
                # Save the updated history entry
                success = self.processor.update_history_entry(original_row, updated_row)
                if success:
                    self._update_ui_after_save(original_row['id'], updated_row, button, final_images)
                    custom_dialogs.show_info(self, "Image Saved", f"Image saved and history updated for '{key}' prompt.")
                else:
                    custom_dialogs.show_error(self, "History Update Error", "Could not update the history file with the new image path.")
                    if button:
                        button.config(state=tk.NORMAL, text="Regenerate Image(s)")
            else: # User clicked "Discard"
                # Revert button to its pre-generation state
                if button:
                    original_images = original_row.get('original_images', []) if key == 'original' else \
                                      original_row.get('enhanced', {}).get('images', []) if key == 'enhanced' else \
                                      original_row.get('variations', {}).get(key, {}).get('images', [])
                    if original_images:
                        button.config(text=f"Regen ({len(original_images)})", state=tk.NORMAL)
                    else:
                        button.config(text="Generate Image", state=tk.NORMAL)
        
        except queue.Empty:
            pass
        except tk.TclError:
            # This can happen if the window is destroyed while the queue is being processed.
            # We can safely ignore it and stop the loop.
            return
        finally:
            try:
                if self.winfo_exists():
                    self.image_gen_after_id = self.after(100, self._check_image_gen_queue)
            except tk.TclError:
                pass # Window was destroyed, do nothing.

    def _get_target_object_for_images(self, data_row: Dict[str, Any], key: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Finds the correct dictionary and key within a history entry to store an image list."""
        if key == 'original':
            return data_row, 'original_images'
        elif key == 'enhanced':
            if 'enhanced' not in data_row: data_row['enhanced'] = {}
            return data_row['enhanced'], 'images'
        elif key in data_row.get('variations', {}):
            return data_row['variations'][key], 'images'
        return None, None

    def _build_final_image_list(self, target_obj: Dict[str, Any], image_list_key: str, new_images_to_save: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Builds a new list of images, handling replacements and additions."""
        existing_images = target_obj.get(image_list_key, [])
        if not isinstance(existing_images, list):
            existing_images = []

        new_images_by_model = {
            img.get('generation_params', {}).get('model', {}).get('name'): img
            for img in new_images_to_save
        }

        final_images = []
        for old_img in existing_images:
            old_model_name = old_img.get('generation_params', {}).get('model', {}).get('name')
            if old_model_name not in new_images_by_model:
                final_images.append(old_img)

        for new_image_data in new_images_to_save:
            image_path = self.processor.save_generated_image(new_image_data['bytes'])
            generation_params = new_image_data.get('generation_params')
            final_images.append({'image_path': image_path, 'generation_params': generation_params})
        
        final_images.sort(key=lambda img: img.get('generation_params', {}).get('model', {}).get('name', ''))
        return final_images

    def _update_ui_after_save(self, entry_id: str, updated_row: Dict[str, Any], button: Optional[ttk.Button], final_images: List[Dict[str, Any]]):
        """Updates all necessary UI components after a successful history save."""
        # Update the selected row data in memory
        self.selected_row_data = updated_row
        
        # Find the corresponding widget in the list and update its data
        found_widget_info = None
        for i, row in enumerate(self.all_history_data):
            if row.get('id') == entry_id:
                self.all_history_data[i] = updated_row
                if i < len(self.history_widgets):
                    self.history_widgets[i]['data'] = updated_row
                    found_widget_info = self.history_widgets[i]
                break
        
        if button:
            button.config(text=f"Regen ({len(final_images)})", state=tk.NORMAL)
        
        # Refresh the details pane with the new data
        if found_widget_info:
            self._on_item_select(found_widget_info)

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
            gen_image_frame = ttk.Frame(button_container)
            # The frame is packed in _on_item_select
            self.detail_tabs[key]['gen_image_frame'] = gen_image_frame

            image_gen_spinner = LoadingAnimation(gen_image_frame, size=20)
            self.detail_tabs[key]['image_gen_spinner'] = image_gen_spinner

            generate_image_button = ttk.Button(gen_image_frame, text="Generate Image", command=lambda k=key: self._generate_image_from_history(k))
            generate_image_button.pack(side=tk.LEFT, expand=True, fill=tk.X)
            self.detail_tabs[key]['generate_image_button'] = generate_image_button

    def _clear_image_preview(self):
        """Resets the image preview to its default state."""
        self._hide_image_tooltip()
        self.image_label.config(image='', text="No image generated for this entry.")
        self.image_tooltip.text = ""
        self.image_ref = None
        self.current_images = []
        self.current_image_index = 0
        self.image_info_label.config(text="") # Clear the text instead of hiding the widget

    def _prune_history(self):
        """Starts the process of pruning missing image entries from the history file."""
        if not custom_dialogs.ask_yes_no(
            self, 
            "Confirm Prune", 
            "This will scan your entire history file and remove any references to image files that no longer exist on disk.\n\nThis action cannot be undone. Are you sure you want to continue?"
        ):
            return

        pruned_count = self.processor.prune_missing_image_entries()
        custom_dialogs.show_info(self, "Prune Complete", f"Removed {pruned_count} missing image references from the history file.")
        # Reload the view to reflect the changes
        self.load_and_display_history()

    def _garbage_collect_images(self):
        """Starts the process of pruning missing image entries from the history file."""
        if not custom_dialogs.ask_yes_no(
            self, 
            "Confirm Prune", 
            "This will scan your entire history file and remove any references to image files that no longer exist on disk.\n\nThis action cannot be undone. Are you sure you want to continue?"
        ):
            return

        deleted_count = self.processor.garbage_collect_orphaned_images()
        custom_dialogs.show_info(self, "Garbage Collection Complete", f"Deleted {deleted_count} orphaned image files.")

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
            # Update the in-memory data for the main history list
            for i, row in enumerate(self.all_history_data):
                if row.get('id') == original_row.get('id'):
                    self.all_history_data[i] = updated_row
                    break
            
            # Find the corresponding widget and update its data and appearance
            is_fav = updated_row.get('favorite')
            found_widget_info = None
            for widget_info in self.history_widgets:
                if widget_info['data'].get('id') == original_row.get('id'):
                    found_widget_info = widget_info
                    # CRITICAL: Update the data object within the widget info itself
                    widget_info['data'] = updated_row
                    
                    new_style = "Favorite.HistoryPrompt.TLabel" if is_fav else "HistoryPrompt.TLabel"
                    widget_info['label'].config(style=new_style)
                    # If the favorites filter is on, the item might need to be hidden
                    if self.show_favorites_only_var.get() and not is_fav:
                        widget_info['frame'].pack_forget()
                    break
            
            # After updating the list item, refresh the details pane to reflect the change.
            if found_widget_info:
                self._on_item_select(found_widget_info)
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
        
        has_enhanced = 'enhanced' in full_row_data and full_row_data['enhanced']
        if has_enhanced:
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
        
        # --- Deletion Sub-menu ---
        delete_menu = tk.Menu(self.context_menu, tearoff=0)
        delete_menu.add_command(label="Delete Entire Entry", command=self._delete_selected_history)
        delete_menu.add_separator()
        
        delete_menu.add_command(label="Delete Enhanced Prompt", command=lambda: self._delete_prompt_part('enhanced'), state=tk.NORMAL if has_enhanced else tk.DISABLED)
        
        if variations:
            for var_key in sorted(variations.keys()):
                var_name = self.available_variations_map.get(var_key, var_key.capitalize())
                delete_menu.add_command(label=f"Delete '{var_name}' Variation", command=lambda k=var_key: self._delete_prompt_part(k))

        self.context_menu.add_cascade(label="Delete...", menu=delete_menu)

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

    def _delete_prompt_part(self, part_key: str):
        """Deletes a specific part (enhanced or a variation) of a history entry."""
        if not self.selected_row_data:
            return

        original_row = self.selected_row_data
        
        part_name = part_key
        if part_key != 'enhanced':
            part_name = self.available_variations_map.get(part_key, part_key.capitalize())

        if not custom_dialogs.ask_yes_no(self, f"Confirm Delete '{part_name}'", f"Are you sure you want to permanently delete the '{part_name}' prompt and its associated images from this history entry?"):
            return

        updated_row = copy.deepcopy(original_row)

        if part_key == 'enhanced':
            if 'enhanced' in updated_row:
                del updated_row['enhanced']
        elif 'variations' in updated_row and part_key in updated_row['variations']:
            del updated_row['variations'][part_key]
        else:
            custom_dialogs.show_error(self, "Error", f"Could not find part '{part_name}' to delete.")
            return

        try:
            success = self.processor.update_history_entry(original_row, updated_row)
            if success:
                # Update in-memory data and refresh the UI by re-selecting the item
                for i, row in enumerate(self.all_history_data):
                    if row.get('id') == original_row.get('id'):
                        self.all_history_data[i] = updated_row
                        # Find the corresponding widget to re-select it and refresh the view
                        if i < len(self.history_widgets):
                            # CRITICAL: Update the widget's internal data before re-selecting
                            self.history_widgets[i]['data'] = updated_row
                            self._on_item_select(self.history_widgets[i])
                        break
                custom_dialogs.show_info(self, "Success", f"'{part_name}' prompt deleted successfully.")
            else:
                custom_dialogs.show_error(self, "Error", "Could not update the history entry.")
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"An error occurred while deleting the prompt part:\n{e}")

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