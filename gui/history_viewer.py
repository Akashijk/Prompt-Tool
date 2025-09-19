"""A window to view and search the prompt generation history."""

import tkinter as tk
from tkinter import ttk
import json
import traceback
import queue
import random
import threading
import tkinter.font as tkfont
import copy
import sys
import os
from PIL import Image, ImageTk
from typing import List, Dict, Optional, TYPE_CHECKING, Any, Tuple, Callable
from . import custom_dialogs
from core.config import config, PROJECT_ROOT
from core.prompt_processor import PromptProcessor
from .common import TextContextMenu, SmartWindowMixin, LoadingAnimation, ImagePreviewMixin, ScrollableFrame
from .task_runner import TaskRunnerMixin
from .common import Tooltip

if TYPE_CHECKING:
    from .gui_app import GUIApp

class HistoryViewerWindow(tk.Toplevel, SmartWindowMixin, ImagePreviewMixin, TaskRunnerMixin):
    """A window to view and search the prompt generation history."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor):
        super().__init__(parent)
        ImagePreviewMixin.__init__(self)
        self.title("Prompt History Viewer")

        self.processor = processor
        self.model_usage_manager = parent.model_usage_manager
        TaskRunnerMixin.__init__(self)
        self.parent_app = parent
        self.all_history_data: List[Dict[str, str]] = []
        self.scrollable_list: Optional[ScrollableFrame] = None
        self.BATCH_SIZE = 50
        self.current_offset = 0
        # --- Attributes for the new Canvas-based list ---
        self.history_canvas: Optional[tk.Canvas] = None
        self.regen_prompt_queue = queue.Queue()
        self.image_gen_queue = queue.Queue()
        self.thumbnail_work_queue = queue.Queue()
        self.history_container: Optional[ttk.Frame] = None
        self.history_widgets: List[Dict[str, Any]] = [] # Stores {'frame': widget, 'label': widget, 'data': row_data}
        self.history_load_queue = queue.Queue()
        self.thumbnail_queue = queue.Queue()
        self.history_load_after_id: Optional[str] = None
        self.image_gen_after_id: Optional[str] = None
        self.history_loading_animation: Optional[LoadingAnimation] = None
        self.selected_widget_info: Optional[Dict[str, Any]] = None
        self.selected_row_data: Optional[Dict[str, Any]] = None

        self.image_favorite_var = tk.BooleanVar()
        self.show_favorites_only_var = tk.BooleanVar(value=False)
        self.thumbnail_cancellation_event = threading.Event()
        self.details_notebook: Optional[ttk.Notebook] = None
        self.prompt_version_map: Dict[str, str] = {}
        self.prompt_version_var = tk.StringVar()
        self.detail_tabs: Dict[str, Dict[str, Any]] = {}
        self.original_edit_content: Optional[str] = None
        self.current_pil_image: Optional[Image.Image] = None
        self.image_ref: Optional[ImageTk.PhotoImage] = None
        self.image_tooltip: Optional[Tooltip] = None
        self.image_tooltip_after_id: Optional[str] = None
        self.current_images: List[Dict[str, Any]] = []
        self._resize_debounce_id: Optional[str] = None
        self._pagination_reflow_debounce_id: Optional[str] = None
        self.filter_debounce_timer: Optional[str] = None
        self.image_context_menu = tk.Menu(self, tearoff=0)
        self.context_menu = tk.Menu(self, tearoff=0)

        # --- FIX: Initialize the variations map ---
        variations = self.processor.get_available_variations()
        self.available_variations_map = {v['key']: v['name'] for v in variations}

        self._create_styles()
        self._create_widgets()
        self.load_and_display_history()

        self.smart_geometry(min_width=1200, min_height=800)
        self.regen_prompt_after_id = self.after(100, self._check_regen_prompt_queue)
        self.thumbnail_after_id = self.after(100, self._check_thumbnail_queue)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _get_active_ai_model(self) -> str:
        """Implementation for TaskRunnerMixin, not used here but required."""
        return self.parent_app.enhancement_model_var.get()

    def close(self):
        """Safely close the window, cancelling any pending after() jobs."""
        if self.history_load_after_id:
            self.after_cancel(self.history_load_after_id)
            self.history_load_after_id = None
        if self.thumbnail_after_id:
            self.after_cancel(self.thumbnail_after_id)
            self.thumbnail_after_id = None
        self.thumbnail_cancellation_event.set()
        if self._resize_debounce_id:
            self.after_cancel(self._resize_debounce_id)
            self._resize_debounce_id = None
        if self._pagination_reflow_debounce_id:
            self.after_cancel(self._pagination_reflow_debounce_id)
            self._pagination_reflow_debounce_id = None
        if self.regen_prompt_after_id:
            self.after_cancel(self.regen_prompt_after_id)
            self.regen_prompt_after_id = None
        if self.image_gen_after_id:
            self.cancellation_event.set()
            self.after_cancel(self.image_gen_after_id)
            self.image_gen_after_id = None
        
        # Clear InvokeAI cache on close, as generations might have happened.
        if self.processor.is_invokeai_connected():
            self.processor.clear_invokeai_cache_async()

        self.close_preview_on_destroy()
        self.destroy()

    def _schedule_pagination_reflow(self, event=None):
        """Schedules a reflow of pagination controls to avoid excessive updates."""
        if self._pagination_reflow_debounce_id:
            self.after_cancel(self._pagination_reflow_debounce_id)
        self._pagination_reflow_debounce_id = self.after(100, self._reflow_pagination_controls)

    def _update_visible_thumbnails(self):
        """Loads thumbnails only for the items currently visible in the history list."""
        if not self.history_canvas or not self.history_container.winfo_exists():
            return

        try:
            # The y-coordinate of the top of the visible part of the canvas
            canvas_top = self.history_canvas.canvasy(0)
            # The y-coordinate of the bottom of the visible part of the canvas
            canvas_bottom = self.history_canvas.canvasy(self.history_canvas.winfo_height())
        except tk.TclError:
            return # This can happen if the window is being destroyed.

        for widget_info in self.history_widgets:
            frame = widget_info['frame']
            if not frame.winfo_exists(): continue
            
            widget_top = frame.winfo_y()
            widget_bottom = widget_top + frame.winfo_reqheight()
            
            # If the widget is visible and its thumbnail hasn't been loaded yet...
            if not (widget_bottom < canvas_top or widget_top > canvas_bottom) and not widget_info.get('thumbnail_loaded'):
                widget_info['thumbnail_loaded'] = True
                image_path = widget_info.get('cover_image_path')
                workflow = widget_info.get('workflow_tag')
                label_widget = widget_info.get('thumb_label')

                if image_path and workflow and label_widget:
                    self._load_history_thumbnail(label_widget, image_path, workflow)

    def _get_preview_image(self, widget_info: Dict[str, Any]) -> Optional[Image.Image]:
        """Implementation of the abstract method from ImagePreviewMixin."""
        relative_image_path = widget_info.get('cover_image_path')
        if not relative_image_path: return None

        try:
            # The workflow tag is already on the widget_info from _populate_history_list
            workflow = widget_info.get('workflow_tag', 'sfw')
            original_workflow = config.workflow
            config.workflow = workflow.lower()
            full_path = os.path.join(config.get_history_file_dir(), relative_image_path)
            config.workflow = original_workflow # Restore immediately
            if not os.path.exists(full_path): return None
            return Image.open(full_path)
        except Exception as e:
            print(f"Error loading full image for preview: {e}")
            return None

    def _get_cover_image_path_for_row(self, row: Dict[str, Any]) -> Optional[str]:
        """Finds the cover image path for a given history row data."""
        image_lists_to_check = []
        if row.get('original_images'): image_lists_to_check.append(row['original_images'])
        if row.get('enhanced', {}).get('images'): image_lists_to_check.append(row['enhanced']['images'])
        for var_data in row.get('variations', {}).values():
            if var_data.get('images'): image_lists_to_check.append(var_data['images'])

        # Prioritize finding the explicitly set cover image first
        cover_image_path = None
        for img_list in image_lists_to_check:
            for img_data in img_list:
                if img_data.get('is_cover_image'):
                    cover_image_path = img_data.get('image_path')
                    break
            if cover_image_path: break

        # Fallback: If no cover is set, find the first available image
        if not cover_image_path and image_lists_to_check:
            for img_list in image_lists_to_check:
                if img_list:
                    cover_image_path = img_list[0].get('image_path')
                    break
        return cover_image_path

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

        self.history_loading_animation = LoadingAnimation(list_frame, size=32)

        # --- NEW: Use ScrollableFrame ---
        self.scrollable_list = ScrollableFrame(list_frame, scroll_callback=self._update_visible_thumbnails)
        self.scrollable_list.pack(fill=tk.BOTH, expand=True)
        self.history_container = self.scrollable_list.scrollable_frame
        self.history_canvas = self.scrollable_list.canvas

        self.load_more_button = ttk.Button(list_frame, text="Load More", command=self._load_next_history_batch, style="Accent.TButton")
        # The button is packed later by _load_next_history_batch

        def on_history_canvas_configure(event):
            # Adjust wraplength of all visible prompt labels
            for widget_info in self.history_widgets:
                if widget_info['frame'].winfo_ismapped():
                    widget_info['label'].configure(wraplength=event.width - 20) # -20 for padding

        self.history_canvas.bind("<Configure>", on_history_canvas_configure)

        # --- Right Pane (for details and image) ---
        right_pane = ttk.Frame(h_pane)
        h_pane.add(right_pane, weight=2)

        # This will hold the image preview at the top and the prompt details below
        v_pane_right = ttk.PanedWindow(right_pane, orient=tk.VERTICAL)
        v_pane_right.pack(fill=tk.BOTH, expand=True)

        # --- Image Preview Area (Top of Right Pane) ---
        self.image_frame = ttk.LabelFrame(v_pane_right, text="Image Preview", padding=5)
        v_pane_right.add(self.image_frame, weight=3) # Give more space to the image

        # --- NEW: Create a dedicated frame for buttons at the bottom ---
        self.button_pagination_frame = ttk.Frame(self.image_frame)
        self.button_pagination_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))

        # --- NEW: Create a scrollable frame for the info label ---
        self.info_label_frame = ttk.Frame(self.image_frame, height=40) # Fixed height
        self.info_label_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))
        self.info_label_frame.pack_propagate(False) # Prevent it from resizing to fit content

        self.image_info_label = ttk.Label(self.info_label_frame, text="", anchor=tk.W, justify=tk.LEFT, wraplength=1) # Wraplength will be set dynamically
        self.image_info_label.pack(fill=tk.BOTH, expand=True, padx=5)
        self.info_label_frame.bind("<Configure>", lambda e: self.image_info_label.config(wraplength=e.width - 10))

        # The main image label takes the remaining space
        self.image_label = ttk.Label(self.image_frame, text="No image generated for this entry.", anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        self.image_label.bind("<Configure>", self._on_image_container_resize)

        # Add a spinner for when the image is regenerating
        self.main_image_spinner = LoadingAnimation(self.image_frame, size=48)
        # Don't pack it yet.

        self.image_tooltip = Tooltip(self.image_label)
        self.image_label.bind("<Enter>", self._schedule_image_tooltip)
        self.image_label.bind("<Leave>", self._hide_image_tooltip)
        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        self.image_label.bind(right_click_event, self._show_image_context_menu)

        # Create the pagination widgets inside their dedicated button frame.
        self.prev_button = ttk.Button(self.button_pagination_frame, text="< Prev", command=self._prev_image)
        self.favorite_image_button = ttk.Checkbutton(self.button_pagination_frame, text="⭐", variable=self.image_favorite_var, command=self._toggle_image_favorite, style='Switch.TCheckbutton')
        Tooltip(self.favorite_image_button, "Add this image to your Favorites collection.")
        self.regen_frame = ttk.Frame(self.button_pagination_frame)
        self.regen_image_spinner = LoadingAnimation(self.regen_frame, size=20)
        self.regen_image_button = ttk.Button(self.regen_frame, text="Regen Image", command=self._regenerate_current_image)
        self.regen_image_button.pack(side=tk.LEFT)
        Tooltip(self.regen_image_button, "Regenerate this image with a new seed.")
        self.next_button = ttk.Button(self.button_pagination_frame, text="Next >", command=self._next_image)

        # --- Details View (Bottom of Right Pane) ---
        details_frame = ttk.LabelFrame(v_pane_right, text="Selected Prompt Details", padding=5)
        v_pane_right.add(details_frame, weight=3)

        # --- NEW: Dropdown for prompt versions ---
        self.prompt_version_combo = ttk.Combobox(details_frame, textvariable=self.prompt_version_var, state="readonly")
        self.prompt_version_combo.pack(fill=tk.X, pady=(0, 5))
        self.prompt_version_combo.bind("<<ComboboxSelected>>", self._on_prompt_version_select)

        # --- NEW: Container for the currently displayed prompt version ---
        self.detail_content_container = ttk.Frame(details_frame)
        self.detail_content_container.pack(fill=tk.BOTH, expand=True)

    def _reflow_pagination_controls(self, event=None):
        if not hasattr(self, 'button_pagination_frame') or not self.button_pagination_frame.winfo_exists():
            return

        if not self.current_images:
            # If there are no images, hide all controls.
            for widget in self.button_pagination_frame.winfo_children():
                widget.pack_forget()
            return

        # --- NEW: Simplified, stable layout using pack ---
        # Clear existing layout
        for widget in self.button_pagination_frame.winfo_children():
            widget.pack_forget()

        # Pack from left to right and right to left
        if len(self.current_images) > 1:
            self.prev_button.pack(side=tk.LEFT, padx=(0, 5))
            self.next_button.pack(side=tk.RIGHT, padx=(5, 0))

        self.favorite_image_button.pack(side=tk.RIGHT, padx=(5, 0))
        self.regen_frame.pack(side=tk.RIGHT)

    def load_and_display_history(self):
        """Loads data from the history file and populates the list."""
        self._clear_list_and_state()
        self.history_loading_animation.pack(pady=50)
        self.history_loading_animation.start()

        def task():
            try:
                all_history = self.processor.get_all_history_across_workflows()
                if self.parent_app.workflow_var.get() == 'sfw':
                    history_data = [item for item in all_history if item.get('workflow_source') == 'SFW']
                else: # nsfw mode shows only nsfw
                    history_data = [item for item in all_history if item.get('workflow_source') == 'NSFW']
                self.history_load_queue.put({'success': True, 'data': history_data})
            except Exception as e:
                self.history_load_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.history_load_after_id = self.after(100, self._check_history_load_queue)

    def _clear_list_and_state(self):
        """Clears the list and resets pagination state."""
        for widget_info in self.history_widgets:
            widget_info['frame'].destroy()
        self.history_widgets.clear()
        self.current_offset = 0
        self.all_history_data = []
        self.load_more_button.pack_forget()

    def _check_history_load_queue(self):
        """Checks for loaded history data and populates the view."""
        try:
            result = self.history_load_queue.get_nowait()
            self.history_loading_animation.stop()
            self.history_loading_animation.pack_forget()

            if result['success']:
                self.all_history_data = result['data']
                self.current_offset = 0
                self._load_next_history_batch()
            else:
                custom_dialogs.show_error(self, "Error Loading History", result['error'])
        except queue.Empty:
            self.history_load_after_id = self.after(100, self._check_history_load_queue)

    def _load_next_history_batch(self):
        """Loads the next batch of history items into the view."""
        if self.current_offset >= len(self.all_history_data):
            self.load_more_button.pack_forget()
            return

        start = self.current_offset
        end = min(self.current_offset + self.BATCH_SIZE, len(self.all_history_data))
        batch_data = self.all_history_data[start:end]
        
        self._populate_history_list(batch_data)
        self.current_offset = end

        self.load_more_button.pack(side=tk.BOTTOM, fill=tk.X, pady=(5,0))
        self.after(100, self._update_visible_thumbnails)

    def _populate_history_list(self, data: List[Dict[str, str]]):
        """Appends a batch of history items to the list view."""
        if not self.history_container or not data: return

        current_width = self.history_canvas.winfo_width()
        
        for row in data:
            cover_image_path = self._get_cover_image_path_for_row(row)

            original_prompt = row.get('original_prompt', 'No original prompt found.')
            is_fav = row.get('favorite', False)

            # Get the correct workflow source for this specific entry from the data.
            workflow_tag = row.get('workflow_source', 'SFW')

            # Create a frame for each item for better layout and binding
            item_frame = ttk.Frame(self.history_container, style="HistoryItem.TFrame", relief="groove", borderwidth=1)
            item_frame.pack(fill=tk.X, pady=2, padx=2)

            # --- Thumbnail Label (Left) ---
            thumb_label = ttk.Label(item_frame, text="🖼️", width=12, anchor=tk.CENTER)
            thumb_label.pack(side=tk.LEFT, padx=5, pady=5)

            # --- Text Info (Right) ---
            text_frame = ttk.Frame(item_frame, style="HistoryItem.TFrame") # Match style for seamless selection color
            text_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

            label_style = "Favorite.HistoryPrompt.TLabel" if is_fav else "HistoryPrompt.TLabel"
            prompt_label = ttk.Label(text_frame, text=original_prompt, style=label_style, wraplength=current_width - 150, anchor="nw", justify="left")
            prompt_label.pack(fill=tk.X, expand=True, padx=5, pady=(5,0))

            # Add date/template info
            timestamp = row.get('timestamp', 'Unknown date')
            template_name = row.get('template_name')
            info_text = f"Date: {timestamp.split('T')[0]}"
            if template_name:
                info_text += f" | Template: {os.path.basename(template_name)}"
            
            info_label = ttk.Label(text_frame, text=info_text, foreground="gray")
            info_label.pack(fill=tk.X, expand=True, padx=5, pady=(0,5))

            # Store widget and data together
            widget_info = {
                'frame': item_frame, 'label': prompt_label, 'data': row, 
                'thumb_label': thumb_label, 'text_frame': text_frame,
                # --- NEW: Store data for lazy loading ---
                'cover_image_path': cover_image_path,
                'workflow_tag': workflow_tag,
                'thumbnail_loaded': False
            }
            self.history_widgets.append(widget_info)

            # Bind preview events to the thumbnail
            thumb_label.bind("<Enter>", lambda e, info=widget_info: self._schedule_preview(info))
            thumb_label.bind("<Leave>", lambda e: self._schedule_hide())

            # Bind events to the frame and its labels
            right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
            for widget in [item_frame, thumb_label, text_frame, prompt_label, info_label]:
                widget.bind("<Button-1>", lambda e, info=widget_info: self._on_item_select(info))
                widget.bind("<Double-1>", lambda e, info=widget_info: self._load_to_main_window())
                widget.bind(right_click_event, lambda e, info=widget_info: self._show_context_menu(e, info))
                widget.bind("<MouseWheel>", self.scrollable_list._on_mouse_wheel)

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
        if not self.prompt_version_combo: return

        # --- Visual Selection Highlighting ---
        # Deselect the previously selected frame
        if self.selected_widget_info and self.selected_widget_info['frame'].winfo_exists():
            self.selected_widget_info['frame'].config(style="HistoryItem.TFrame")
            if 'text_frame' in self.selected_widget_info:
                self.selected_widget_info['text_frame'].config(style="HistoryItem.TFrame")
        
        # Select the new frame
        self.selected_widget_info = selected_widget_info
        self.selected_widget_info['frame'].config(style="Selected.HistoryItem.TFrame")
        if 'text_frame' in self.selected_widget_info:
            self.selected_widget_info['text_frame'].config(style="Selected.HistoryItem.TFrame")
        
        # Store the data for other methods to use (delete, favorite, etc.)
        self.selected_row_data = selected_widget_info['data']
        full_row_data = self.selected_row_data

        # Before doing anything, ensure we exit edit mode if it was active
        if 'enhanced' in self.detail_tabs and 'edit_button' in self.detail_tabs['enhanced']:
            self._cancel_edit_mode('enhanced', force=True)

        # --- NEW: DYNAMIC DROPDOWN LOGIC ---
        # 1. Determine the available prompt versions for this entry
        display_order = ['original', 'enhanced']
        if 'variations' in full_row_data and full_row_data.get('variations'):
            display_order.extend(sorted(full_row_data['variations'].keys()))

        # 2. Create user-friendly names and a map to the internal keys
        self.prompt_version_map.clear()
        dropdown_values = []
        for key in display_order:
            prompt_data = None
            display_name = ""
            
            if key == 'original':
                if full_row_data.get('original_prompt'):
                    prompt_data = full_row_data
                    display_name = 'Original'
            elif key == 'enhanced':
                if full_row_data.get('enhanced', {}).get('prompt'):
                    prompt_data = full_row_data.get('enhanced', {})
                    display_name = 'Enhanced'
            else: # Variation
                variation_data = full_row_data.get('variations', {}).get(key)
                if variation_data and variation_data.get('prompt'):
                    prompt_data = variation_data
                    friendly_name = self.available_variations_map.get(key, key.capitalize())
                    display_name = f"{friendly_name} (Variation)"

            if prompt_data and display_name:
                # Determine if this prompt version has images.
                # The key for images is different for 'original'.
                image_key = 'original_images' if key == 'original' else 'images'
                has_images = bool(prompt_data.get(image_key))
                
                final_display_name = f"{display_name} 🖼️" if has_images else display_name
                self.prompt_version_map[final_display_name] = key
                dropdown_values.append(final_display_name)

        # 3. Populate and set the combobox
        self.prompt_version_combo['values'] = dropdown_values
        if dropdown_values:
            self.prompt_version_combo.set(dropdown_values[0])
            self._on_prompt_version_select() # Manually trigger the display update
        else:
            # No valid prompts to show, clear the view
            self.prompt_version_combo.set('')
            for child in self.detail_content_container.winfo_children():
                child.pack_forget()
            self._clear_image_preview()

    def _on_prompt_version_select(self, event=None):
        """Handles selection of a prompt version from the dropdown."""
        selected_display_name = self.prompt_version_var.get()
        if not selected_display_name or not self.selected_row_data:
            return

        key = self.prompt_version_map.get(selected_display_name)
        if not key: return

        # Hide all other detail frames
        for frame in self.detail_tabs.values():
            frame['frame'].pack_forget()

        # Ensure the frame for the selected key exists
        if key not in self.detail_tabs:
            self._create_detail_tab(key, selected_display_name)

        # Show and populate the selected frame
        tab = self.detail_tabs[key]
        tab['frame'].pack(fill=tk.BOTH, expand=True)

        # Get data for the selected key
        full_row_data = self.selected_row_data
        prompt, images, prompt_data = "", [], {}
        if key == 'original':
            prompt = full_row_data.get('original_prompt', '')
            images = full_row_data.get('original_images', [])
            prompt_data = full_row_data
        elif key == 'enhanced':
            prompt_data = full_row_data.get('enhanced', {})
            prompt = prompt_data.get('prompt', '')
            images = prompt_data.get('images', [])
        else: # Variation
            prompt_data = full_row_data.get('variations', {}).get(key, {})
            prompt = prompt_data.get('prompt', '')
            images = prompt_data.get('images', [])

        # Update widgets in the frame
        self._update_text_widget(tab['text'], prompt)

        sd_model_text = ""
        ollama_model_text = prompt_data.get('ollama_model', '')
        if images:
            first_image_params = images[0].get('generation_params', {})
            gen_model_obj = first_image_params.get('model', {})
            sd_model_text = f"SD: {gen_model_obj.get('name', 'Unknown')}"
        display_parts = [part for part in [f"LLM: {ollama_model_text}" if ollama_model_text else "", sd_model_text] if part]
        tab['model_label'].config(text=" | ".join(display_parts))

        if 'negative_prompt_text' in tab:
            neg_prompt = images[0].get('generation_params', {}).get('negative_prompt', '') if images else ""
            self._update_text_widget(tab['negative_prompt_text'], neg_prompt)

        if 'generate_image_button' in tab:
            if not self.processor.is_invokeai_connected():
                tab['gen_image_frame'].pack_forget()
            else:
                tab['gen_image_frame'].pack(side=tk.LEFT, padx=(5,0))
                tab['generate_image_button'].config(text="Generate Additional Images" if images else "Generate Image", state=tk.NORMAL)

        # Update the main image preview
        self._display_images(images)

    def _update_text_widget(self, widget: tk.Text, content: str):
        """Helper to safely update a text widget's content."""
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        widget.config(state=tk.DISABLED)

    def _display_images(self, images: Optional[List[Dict[str, Any]]]):
        """Loads a list of images and displays the first one."""
        if not images:
            self._clear_image_preview()
            return

        self.current_images = images

        # Find the cover image, if one exists in this group
        cover_image_index = -1
        for i, img_data in enumerate(self.current_images):
            if img_data.get('is_cover_image'):
                cover_image_index = i
                break
        self.current_image_index = cover_image_index if cover_image_index != -1 else 0
        
        self._reflow_pagination_controls()
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
                self.current_pil_image = None
                return

            self.current_pil_image = Image.open(full_path)
            self._update_image_display()
            
            # Update pagination info
            gen_params = image_data.get('generation_params', {})
            model_name = gen_params.get('model', {}).get('name', 'Unknown Model')
            duration = gen_params.get('duration')
            is_fav = image_data.get('is_favorite', False)
            self.image_favorite_var.set(is_fav)

            # --- NEW: Display LoRAs ---
            lora_info = gen_params.get('loras', [])
            lora_display_text = ""
            duration_text = f" ({duration:.2f}s)" if duration else ""

            if lora_info:
                lora_names = [f"{l['lora_object']['name']} (w: {l['weight']})" for l in lora_info]
                lora_display_text = " | LoRAs: " + ", ".join(lora_names)

            info_text = f"({self.current_image_index + 1}/{len(self.current_images)}) Model: {model_name}{duration_text}{lora_display_text}"
            self.image_info_label.config(text=info_text)

            # Update the negative prompt for the current image
            selected_key = self._get_current_version_key()
            if selected_key:
                neg_prompt_widget = self.detail_tabs.get(selected_key, {}).get('negative_prompt_text')
                if neg_prompt_widget:
                    neg_prompt = gen_params.get('negative_prompt', '')
                    self._update_text_widget(neg_prompt_widget, neg_prompt)
            
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
            self.current_pil_image = None

    def _get_current_version_key(self) -> Optional[str]:
        """Helper to get the internal key of the currently selected prompt version."""
        if not self.prompt_version_var: return None
        display_name = self.prompt_version_var.get()
        return self.prompt_version_map.get(display_name)

    def _prev_image(self):
        if self.current_image_index > 0:
            self.current_image_index -= 1
            self._show_current_image()

    def _next_image(self):
        if self.current_image_index < len(self.current_images) - 1:
            self.current_image_index += 1
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

    def _show_image_context_menu(self, event):
        """Shows a context menu for the image preview."""
        if not self.current_images:
            return

        image_data = self.current_images[self.current_image_index]
        gen_params = image_data.get('generation_params', {})
        seed = gen_params.get('seed')

        self.image_context_menu.delete(0, tk.END)
        
        copy_seed_state = tk.NORMAL if seed is not None else tk.DISABLED
        self.image_context_menu.add_command(
            label="Copy Seed", 
            command=lambda s=seed: self._copy_seed_to_clipboard(s),
            state=copy_seed_state
        )

        is_current_cover = image_data.get('is_cover_image', False)
        if is_current_cover:
            self.image_context_menu.add_command(
                label="Remove as Cover Image",
                command=lambda: self._set_as_cover_image(remove=True)
            )
        else:
            self.image_context_menu.add_command(
                label="Set as Cover Image", 
                command=lambda: self._set_as_cover_image(remove=False)
            )

        self.image_context_menu.add_separator()
        self.image_context_menu.add_command(label="Delete Image", command=self._delete_current_image)

        self.image_context_menu.tk_popup(event.x_root, event.y_root)

    def _copy_seed_to_clipboard(self, seed: Optional[int]):
        """Copies the provided seed to the clipboard."""
        if seed is not None:
            self.clipboard_clear()
            self.clipboard_append(str(seed))

    def _set_as_cover_image(self, remove: bool = False):
        """Sets the currently viewed image as the cover image for the entire history entry."""
        if not self.selected_row_data or not self.current_images:
            return

        current_version_key = self._get_current_version_key()
        if not current_version_key: return

        updated_row = copy.deepcopy(self.selected_row_data)
        
        # --- FIX: Clear all cover image flags across the ENTIRE entry ---
        image_lists_to_clear = []
        if 'original_images' in updated_row: image_lists_to_clear.append(updated_row['original_images'])
        if 'enhanced' in updated_row and 'images' in updated_row['enhanced']: image_lists_to_clear.append(updated_row['enhanced']['images'])
        if 'variations' in updated_row:
            for var_data in updated_row['variations'].values():
                if 'images' in var_data: image_lists_to_clear.append(var_data['images'])
        
        for img_list in image_lists_to_clear:
            for img in img_list:
                if 'is_cover_image' in img:
                    img['is_cover_image'] = False # type: ignore
        
        new_cover_image_path = None
        if not remove:
            # Now, set the new cover image flag on the correct image
            target_obj, image_list_key = self._get_target_object_for_images(updated_row, current_version_key)
            if not target_obj or not image_list_key: return
            image_list = target_obj.get(image_list_key, [])
            if not image_list or self.current_image_index >= len(image_list): return
            image_list[self.current_image_index]['is_cover_image'] = True
            new_cover_image_path = image_list[self.current_image_index].get('image_path')

        if self._save_and_refresh_row(updated_row, "Cover image updated."):
            # Find the widget in the list and update it.
            row_id = updated_row.get('id')
            widget_info = next((w for w in self.history_widgets if w['data'].get('id') == row_id), None)
            
            if widget_info:
                widget_info['data'] = updated_row
                final_cover_path = self._get_cover_image_path_for_row(updated_row)
                widget_info['cover_image_path'] = final_cover_path
                
                thumb_label = widget_info.get('thumb_label')
                workflow_tag = widget_info.get('workflow_tag')
                if thumb_label and final_cover_path and workflow_tag:
                    self._load_history_thumbnail(thumb_label, final_cover_path, workflow_tag)

    def _toggle_image_favorite(self):
        """Toggles the favorite status for the currently viewed image within its group."""
        if not self.selected_row_data or not self.current_images:
            return

        current_version_key = self._get_current_version_key()
        if not current_version_key: return

        updated_row = copy.deepcopy(self.selected_row_data)
        target_obj, image_list_key = self._get_target_object_for_images(updated_row, current_version_key)
        if not target_obj or not image_list_key: return
        image_list = target_obj.get(image_list_key, [])
        if not image_list or self.current_image_index >= len(image_list): return

        new_favorite_status = self.image_favorite_var.get()
        
        # Just toggle the flag for the current image
        image_list[self.current_image_index]['is_favorite'] = new_favorite_status

        self._save_and_refresh_row(updated_row, "Favorite status updated.", on_fail_callback=lambda: self.image_favorite_var.set(not new_favorite_status))

    def _save_and_refresh_row(self, updated_row: Dict[str, Any], success_message: str, on_fail_callback: Optional[Callable] = None) -> bool:
        """Saves the updated row data and refreshes the UI state."""
        success = self.processor.update_history_entry(self.selected_row_data, updated_row)
        if success:
            self.selected_row_data = updated_row
            custom_dialogs.show_info(self, "Success", success_message)
            return True
        else:
            custom_dialogs.show_error(self, "Error", "Failed to update the history entry.")
            if on_fail_callback:
                on_fail_callback()
            return False

    def _regenerate_prompt_with_ai(self, key: str):
        """Regenerates a single prompt (enhanced or variation) using the AI."""
        if not self.selected_row_data: return
        
        model = self.parent_app.enhancement_model_var.get()
        if not model or "model" in model.lower():
            custom_dialogs.show_error(self, "Error", "Please select a valid Ollama model in the main window.")
            return

        button = self.detail_tabs.get(key, {}).get('regen_ai_button')
        if button:
            button.config(state=tk.DISABLED, text="Regening...")

        def task():
            try:
                if key == 'enhanced':
                    original_prompt = self.selected_row_data.get('original_prompt', '')
                    if not original_prompt: raise ValueError("Original prompt not found for re-enhancement.")
                    new_prompt = self.processor.regenerate_enhancement(original_prompt, model)
                    result_data = {'prompt': new_prompt, 'ollama_model': model}
                else: # It's a variation
                    # Use the ENHANCED prompt as the base for regenerating a variation for better context.
                    base_prompt_for_variation = self.selected_row_data.get('enhanced', {}).get('prompt')
                    # Fallback to original prompt if enhanced doesn't exist for some reason
                    if not base_prompt_for_variation:
                        base_prompt_for_variation = self.selected_row_data.get('original_prompt', '')
                    original_prompt_for_context = self.selected_row_data.get('original_prompt', '')
                    if not base_prompt_for_variation: raise ValueError("Base prompt not found to generate variation from.")
                    variation_result = self.processor.regenerate_variation(base_prompt_for_variation, model, key, original_prompt_context=original_prompt_for_context)
                    result_data = {'prompt': variation_result['prompt'], 'ollama_model': model}
                
                self.regen_prompt_queue.put({'success': True, 'key': key, 'data': result_data})
            except Exception as e:
                self.regen_prompt_queue.put({'success': False, 'error': str(e), 'key': key})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()

    def _check_regen_prompt_queue(self):
        """Checks for AI prompt regeneration results and updates the UI."""
        try:
            result = self.regen_prompt_queue.get_nowait()
            key = result.get('key')
            
            button = self.detail_tabs.get(key, {}).get('regen_ai_button')
            if button:
                button.config(state=tk.NORMAL, text="Regen Prompt")

            if not result.get('success'):
                custom_dialogs.show_error(self, "Regeneration Error", result.get('error', 'An unknown error occurred.'))
            else:
                # Success path
                data_to_update = result.get('data')
                if data_to_update:
                    data_to_update['key'] = key
                    self._update_prompt_from_ai(data_to_update)
        except queue.Empty:
            pass
        except Exception as e:
            # Add a general exception handler to prevent the loop from dying silently.
            print(f"ERROR: Unhandled exception in _check_regen_prompt_queue: {e}")
            traceback.print_exc()
        finally:
            if self.winfo_exists():
                self.regen_prompt_after_id = self.after(100, self._check_regen_prompt_queue)

    def _delete_current_image(self):
        """Deletes the currently viewed image from disk and history."""
        if not self.current_images or not self.selected_row_data:
            return

        image_data = self.current_images[self.current_image_index]
        image_path = image_data.get('image_path')
        if not image_path:
            custom_dialogs.show_error(self, "Error", "Cannot delete image: path not found.")
            return

        if not custom_dialogs.ask_yes_no(self, "Confirm Delete", f"Are you sure you want to permanently delete this image?\n\n{os.path.basename(image_path)}\n\nThis action cannot be undone."):
            return

        current_version_key = self._get_current_version_key()
        if not current_version_key: return

        original_row = self.selected_row_data
        updated_row = copy.deepcopy(original_row)
        target_obj, image_list_key = self._get_target_object_for_images(updated_row, current_version_key)
        if not target_obj or not image_list_key: return
        
        image_list = target_obj.get(image_list_key, [])
        if not image_list or self.current_image_index >= len(image_list): return

        del image_list[self.current_image_index]

        # The update_history_entry method in the processor will handle deleting the file from disk
        if self.processor.update_history_entry(original_row, updated_row):
            self._update_ui_after_image_delete(updated_row)

    def _regenerate_current_image(self): # noqa: C901
        """Regenerates the current image asynchronously with a new seed."""
        if not self.current_images or not self.selected_row_data:
            return

        image_data = self.current_images[self.current_image_index]
        gen_params = image_data.get('generation_params')
        if not gen_params:
            custom_dialogs.show_error(self, "Error", "No generation parameters found for this image.")
            return

        current_version_key = self._get_current_version_key()
        if not current_version_key: return

        prompt = self._get_prompt_for_key(current_version_key)
        if not prompt:
            custom_dialogs.show_error(self, "Error", "Could not determine the prompt for this image.")
            return
        
        # --- NEW: Unload Ollama models to free VRAM for InvokeAI ---
        if not self.parent_app._unload_ollama_models_for_vram():
            return # User cancelled
        
        # Get the negative prompt from the specific image being regenerated
        gen_params = image_data.get('generation_params', {})
        negative_prompt = gen_params.get('negative_prompt', self.processor.get_default_negative_prompt_text())
        initial_dialog_params = copy.deepcopy(gen_params)
        initial_dialog_params['negative_prompt'] = negative_prompt

        # --- Start of async logic ---
        self.main_image_spinner.place(in_=self.image_label, relx=0.5, rely=0.5, anchor=tk.CENTER)
        self.main_image_spinner.start()
        self.regen_image_button.config(state=tk.DISABLED)

        # Create a copy of params and set a new seed
        new_gen_params = copy.deepcopy(gen_params)
        new_gen_params['seed'] = random.randint(0, 2**32 - 1)
        
        def task(key_for_thread: str):
            try:
                gen_args = {
                    "prompt": prompt,
                    "negative_prompt": new_gen_params.get("negative_prompt", ""),
                    "seed": new_gen_params.get("seed"),
                    "model_object": new_gen_params.get("model"),
                    "loras": new_gen_params.get("loras", []),
                    "steps": new_gen_params.get("steps", 30),
                    "cfg_scale": new_gen_params.get("cfg_scale", 7.5),
                    "scheduler": new_gen_params.get("scheduler", "dpmpp_2m"),
                    "cfg_rescale_multiplier": new_gen_params.get("cfg_rescale_multiplier", 0.0),
                    "save_to_gallery": False,
                    "cancellation_event": self.cancellation_event, # type: ignore
                }
                image_data = self.processor.generate_image_with_invokeai(**gen_args)
                
                # Add the new duration to the generation parameters
                new_gen_params['duration'] = image_data.get('duration')

                result_data = {'bytes': image_data['bytes'], 'prompt': prompt, 'generation_params': new_gen_params}
                self.image_gen_queue.put({'success': True, 'data': result_data, 'tab_key': key_for_thread})
            except Exception as e:
                self.image_gen_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, args=(current_version_key,), daemon=True)
        thread.start()
        self.image_gen_after_id = self.after(100, self._check_image_gen_queue)

    def _check_image_gen_queue(self):
        """Checks for regenerated images and updates the UI."""
        try:
            result = self.image_gen_queue.get_nowait()
            
            self.main_image_spinner.place_forget() # Hide the spinner
            self.regen_image_button.config(state=tk.NORMAL) # Re-enable the button

            if not result['success']:
                custom_dialogs.show_error(self, "Image Regeneration Error", result['error'])
                # On failure, the spinner is hidden and the old image remains.
                return

            new_image_data = result.get('data')
            if not new_image_data: return # type: ignore
            current_tab_key = result.get('tab_key')

            if not self.selected_row_data: return
            
            # --- NEW: Get the entry ID ---
            entry_id = self.selected_row_data.get('id')
            if not entry_id:
                custom_dialogs.show_error(self, "History Error", "Could not find the ID for the history entry. Cannot save image.")
                return
            
            # Save the new image and get its path
            saved_image_path = self.processor.save_generated_image(new_image_data['bytes'], entry_id)
            final_image_object = {'image_path': saved_image_path, 'generation_params': new_image_data.get('generation_params')}

            original_row = self.selected_row_data
            updated_row = copy.deepcopy(original_row)
            target_obj, image_list_key = self._get_target_object_for_images(updated_row, current_tab_key)
            if target_obj is None or image_list_key is None: return

            if image_list_key not in target_obj: target_obj[image_list_key] = []
            
            # Append the new image to the existing list
            target_obj[image_list_key].append(final_image_object)
            
            if self.processor.update_history_entry(original_row, updated_row):
                self.selected_row_data = updated_row
                self.processor.clear_avg_gen_times_cache()
                self.current_images = target_obj[image_list_key]
                self.current_image_index = len(self.current_images) - 1 # Go to the new image
                self._show_current_image()
                custom_dialogs.show_info(self, "Success", "Image regenerated and added to the set.")
            else:
                custom_dialogs.show_error(self, "History Update Error", "Could not update the history file with the new image.")
            
            # After the UI is updated, clear the model cache.
            if self.processor.is_invokeai_connected():
                self.processor.clear_invokeai_cache_async()

        except queue.Empty:
            pass
        finally:
            if self.winfo_exists():
                self.image_gen_after_id = self.after(100, self._check_image_gen_queue)

    def _generate_image_from_history(self, key: str):
        """Starts the image generation process for a prompt from the history."""
        if not self.selected_row_data: return

        prompt = self._get_prompt_for_key(key)
        # Get the negative prompt from the text widget associated with this tab
        neg_prompt_widget = self.detail_tabs.get(key, {}).get('negative_prompt_text')
        negative_prompt = neg_prompt_widget.get("1.0", "end-1c").strip() if neg_prompt_widget else self.processor.get_default_negative_prompt_text()
        
        if not prompt:
            custom_dialogs.show_error(self, "Error", "No prompt available to generate an image.")
            return

        def on_success(images_to_save: List[Dict[str, Any]]):
            """Callback to handle updating the history entry with new images."""
            if not self.selected_row_data: return # type: ignore
            
            # --- NEW: Get the entry ID ---
            entry_id = self.selected_row_data.get('id')
            if not entry_id:
                custom_dialogs.show_error(self, "History Error", "Could not find the ID for the history entry. Cannot save image.")
                return

            original_row = self.selected_row_data
            updated_row = copy.deepcopy(original_row)
            target_obj, image_list_key = self._get_target_object_for_images(updated_row, key)

            if target_obj is None or image_list_key is None:
                custom_dialogs.show_error(self, "Internal Error", "Could not determine where to save image data.")
                return

            final_images = self._build_final_image_list(target_obj, image_list_key, images_to_save, entry_id)
            target_obj[image_list_key] = final_images
            
            success = self.processor.update_history_entry(original_row, updated_row)
            if success:
                button = self.detail_tabs.get(key, {}).get('generate_image_button')
                self.processor.clear_avg_gen_times_cache()
                self._update_ui_after_save(original_row['id'], updated_row, button, final_images)
                custom_dialogs.show_info(self, "Image Saved", f"Image saved and history updated for '{key}' prompt.")
            else:
                custom_dialogs.show_error(self, "History Update Error", "Could not update the history file with the new image path.")

        button = self.detail_tabs.get(key, {}).get('generate_image_button')
        self.parent_app._start_image_generation_workflow(
            parent_window=self,
            prompt=prompt, 
            initial_dialog_params={'negative_prompt': negative_prompt},
            button_to_manage=button, spinner_to_manage=self.detail_tabs.get(key, {}).get('image_gen_spinner'),
            on_success_callback=on_success
        )

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

    def _build_final_image_list(self, target_obj: Dict[str, Any], image_list_key: str, new_images_to_save: List[Dict[str, Any]], entry_id: str) -> List[Dict[str, Any]]:
        """Builds a new list of images, handling replacements and additions."""
        # Start with a copy of the existing images.
        final_images = target_obj.get(image_list_key, [])
        if not isinstance(final_images, list):
            final_images = []
        else:
            final_images = copy.deepcopy(final_images)

        # Append the new images.
        for new_image_data in new_images_to_save:
            image_path = self.processor.save_generated_image(new_image_data['bytes'], entry_id)
            generation_params = new_image_data.get('generation_params')
            final_images.append({'image_path': image_path, 'generation_params': generation_params})
        
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

        frame = ttk.Frame(self.detail_content_container)
        
        # --- NEW: Add scrollbar to the text widget ---
        text_container = ttk.Frame(frame)
        text_container.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        text_scrollbar = ttk.Scrollbar(text_container, orient=tk.VERTICAL)
        text_widget = tk.Text(text_container, wrap=tk.WORD, height=5, font=self.parent_app.default_font, state=tk.DISABLED, yscrollcommand=text_scrollbar.set)
        text_scrollbar.config(command=text_widget.yview)
        text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        TextContextMenu(text_widget)

        # Store base widgets
        self.detail_tabs[key] = {'frame': frame, 'text': text_widget, 'title': title}
        # --- END NEW ---

        bottom_bar = ttk.Frame(frame)
        bottom_bar.pack(fill=tk.X, pady=(5,0))

        button_container = ttk.Frame(bottom_bar)
        button_container.pack(side=tk.RIGHT)

        model_label = ttk.Label(bottom_bar, text="", font=self.parent_app.small_font, foreground="gray")
        model_label.pack(side=tk.LEFT, anchor='w', fill=tk.X, expand=True)

        # Add a frame for the negative prompt
        neg_prompt_frame = ttk.LabelFrame(frame, text="Negative Prompt", padding=5)
        neg_prompt_frame.pack(fill=tk.X, expand=False, pady=(5,0))
        neg_prompt_text = tk.Text(neg_prompt_frame, wrap=tk.WORD, height=2, font=self.parent_app.small_font, state=tk.DISABLED, relief=tk.FLAT, exportselection=False)
        neg_prompt_text.pack(fill=tk.X, expand=True)

        self.detail_tabs[key].update({'model_label': model_label, 'button_container': button_container})

        # Special handling for the 'enhanced' and 'negative' tab's edit buttons
        if key != 'original':
            edit_button = ttk.Button(button_container, text="Edit", command=lambda k=key: self._enter_edit_mode(k))
            update_button = ttk.Button(button_container, text="Update", style="Accent.TButton", command=lambda k=key: self._update_edited_prompt(k))
            cancel_button = ttk.Button(button_container, text="Cancel", command=lambda k=key: self._cancel_edit_mode(k))
            self.detail_tabs[key].update({'edit_button': edit_button, 'update_button': update_button, 'cancel_button': cancel_button})
            edit_button.pack(side=tk.LEFT)

        # Add a "Regen (AI)" button for relevant tabs
        if key != 'original':
            regen_ai_button = ttk.Button(button_container, text="Regen Prompt", command=lambda k=key: self._regenerate_prompt_with_ai(k))
            regen_ai_button.pack(side=tk.LEFT, padx=(5,0))
            self.detail_tabs[key]['regen_ai_button'] = regen_ai_button

        # Add a "Generate Image" button placeholder for relevant tabs
        if key not in ['negative', 'params']:
            gen_image_frame = ttk.Frame(button_container)
            gen_image_frame.columnconfigure(1, weight=1) # Let the button expand
            # The frame is packed in _on_item_select
            self.detail_tabs[key]['gen_image_frame'] = gen_image_frame

            image_gen_spinner = LoadingAnimation(gen_image_frame, size=20)
            image_gen_spinner.grid(row=0, column=0, padx=(0, 5))
            image_gen_spinner.grid_remove() # Hide initially
            self.detail_tabs[key]['image_gen_spinner'] = image_gen_spinner

            generate_image_button = ttk.Button(gen_image_frame, text="Generate Image", command=lambda k=key: self._generate_image_from_history(k))
            generate_image_button.grid(row=0, column=1, sticky='ew')
            self.detail_tabs[key]['generate_image_button'] = generate_image_button
            self.detail_tabs[key]['negative_prompt_text'] = neg_prompt_text
        
        # Hide the frame by default. It will be packed when its version is selected.
        frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP, pady=5)

    def _clear_image_preview(self):
        """Resets the image preview to its default state."""
        self._hide_image_tooltip()
        self.image_label.config(image='', text="No image generated for this entry.")
        self.image_tooltip.text = ""
        self.current_pil_image = None
        self.image_ref = None
        self.current_images = []
        self.current_image_index = 0
        self.image_info_label.config(text="")
        # Trigger a reflow which will see current_images is empty and hide the controls.
        self._reflow_pagination_controls()

    def _update_prompt_from_ai(self, data: Dict[str, Any]):
        """Updates the UI and history data after a successful AI regeneration."""
        key = data['key']
        new_prompt = data['prompt']
        new_ollama_model = data.get('ollama_model', '')

        # Update the text widget
        text_widget = self.detail_tabs[key]['text']
        text_widget.config(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        text_widget.insert("1.0", new_prompt)
        text_widget.config(state=tk.DISABLED)

        # Update the model label
        model_label = self.detail_tabs[key]['model_label']
        current_label_text = model_label.cget("text")
        sd_model_part = ""
        if "SD:" in current_label_text:
            parts = current_label_text.split(" | ")
            sd_model_part = next((p for p in parts if p.startswith("SD:")), "")
        display_parts = []
        if new_ollama_model: display_parts.append(f"LLM: {new_ollama_model}")
        if sd_model_part: display_parts.append(sd_model_part)
        model_label.config(text=" | ".join(display_parts))

        # Update the underlying history data
        original_row = self.selected_row_data
        updated_row = copy.deepcopy(original_row)

        if key == 'enhanced':
            if 'enhanced' not in updated_row: updated_row['enhanced'] = {}
            updated_row['enhanced']['prompt'] = new_prompt
        else: # Variation
            if 'variations' not in updated_row: updated_row['variations'] = {}
            if key not in updated_row['variations']: updated_row['variations'][key] = {}
            updated_row['variations'][key]['prompt'] = new_prompt
        
        # Update the ollama_model for the specific part that was regenerated
        if key == 'enhanced':
            updated_row['enhanced']['ollama_model'] = new_ollama_model
            if 'sd_model' in updated_row['enhanced']: del updated_row['enhanced']['sd_model']
        else:
            updated_row['variations'][key]['ollama_model'] = new_ollama_model
            if 'sd_model' in updated_row['variations'][key]: del updated_row['variations'][key]['sd_model']
        
        self._save_and_refresh_row(updated_row, f"'{self.detail_tabs[key]['title']}' prompt has been regenerated.")

    def _check_thumbnail_queue(self):
        """Checks for loaded thumbnails and updates the UI."""
        try:
            label_widget, image_data = self.thumbnail_queue.get_nowait()
            if label_widget.winfo_exists():
                img_ref = ImageTk.PhotoImage(image_data)
                label_widget.config(image=img_ref, text="")
                label_widget.image = img_ref  # Keep a reference
        except queue.Empty:
            pass
        finally:
            if self.winfo_exists():
                self.thumbnail_after_id = self.after(100, self._check_thumbnail_queue)

    def _load_history_thumbnail(self, label_widget: ttk.Label, image_path: str, workflow: str):
        """Starts a background thread to load a thumbnail using the ThumbnailManager."""
        def task():
            try:
                # The thumbnail manager handles caching and creation.
                thumbnail_image = self.processor.thumbnail_manager.get_thumbnail(image_path, workflow)
                if thumbnail_image:
                    self.thumbnail_queue.put((label_widget, thumbnail_image))
            except Exception as e:
                print(f"Error in thumbnail task for {image_path}: {e}")

        thread = threading.Thread(target=task, daemon=True)
        thread.start()

    def _on_image_container_resize(self, event=None):
        """Handles resizing of the image container to re-thumbnail the image."""
        if self._resize_debounce_id:
            self.after_cancel(self._resize_debounce_id)
        self._resize_debounce_id = self.after(100, self._update_image_display)

    def _update_image_display(self):
        """Renders the current PIL image into the image_label, fitting the container."""
        if not self.current_pil_image or not self.image_label.winfo_exists():
            return

        container = self.image_label
        # Subtract a small padding to avoid scrollbars appearing due to rounding errors
        container_w = container.winfo_width()
        container_h = container.winfo_height()

        if container_w <= 1 or container_h <= 1:
            return # Widget not yet rendered

        img_copy = self.current_pil_image.copy()
        img_copy.thumbnail((container_w, container_h), Image.Resampling.LANCZOS)
        
        self.image_ref = ImageTk.PhotoImage(img_copy)
        self.image_label.config(image=self.image_ref, text="")
        self.image_label.image = self.image_ref # Keep a reference

    def _update_ui_after_image_delete(self, updated_row: Dict[str, Any]):
        """Updates the UI after an image has been successfully deleted."""
        self.selected_row_data = updated_row
        self.current_images.pop(self.current_image_index)

        # Adjust the index to prevent out-of-bounds error
        if self.current_image_index >= len(self.current_images):
            self.current_image_index = len(self.current_images) - 1

        if not self.current_images:
            self._clear_image_preview()
        else:
            self._show_current_image()
        
        custom_dialogs.show_info(self, "Success", "Image deleted successfully.")

    def _get_prompt_for_key(self, key: str) -> Optional[str]:
        """Helper to get the prompt text for a given tab key."""
        if not self.selected_row_data: return None
        
        if key == 'original':
            return self.selected_row_data.get('original_prompt')
        elif key == 'enhanced':
            return self.selected_row_data.get('enhanced', {}).get('prompt')
        else: # variation
            return self.selected_row_data.get('variations', {}).get(key, {}).get('prompt')

    def _prune_history(self):
        """Starts the process of pruning missing image entries from the history file."""
        if not custom_dialogs.ask_yes_no(
            self, 
            "Confirm Prune", 
            "This will scan your entire history file and remove any references to image files that no longer exist on disk.\n\nThis action cannot be undone. Are you sure you want to continue?"
        ):
            return

        def on_success(pruned_count):
            custom_dialogs.show_info(self, "Prune Complete", f"Removed {pruned_count} missing image references from the history file.")
            self.load_and_display_history()

        def on_error(error_message):
            custom_dialogs.show_error(self, "Prune Error", f"An error occurred while pruning history:\n{error_message}")

        self.run_task(
            task_callable=self.processor.prune_missing_image_entries,
            on_success=on_success,
            on_error=on_error,
            loading_dialog_title="Pruning History",
            loading_dialog_message="Scanning history for missing images..."
        )

    def _garbage_collect_images(self):
        """Starts the process of pruning missing image entries from the history file."""
        if not custom_dialogs.ask_yes_no(
            self, 
            "Confirm Garbage Collect", 
            "This will scan your image history directories and delete any image files that are NOT referenced in your history file.\n\nThis action cannot be undone. Are you sure you want to continue?"
        ):
            return

        def on_success(deleted_count):
            custom_dialogs.show_info(self, "Garbage Collection Complete", f"Deleted {deleted_count} orphaned image files.")

        def on_error(error_message):
            custom_dialogs.show_error(self, "Garbage Collection Error", f"An error occurred during garbage collection:\n{error_message}")

        self.run_task(
            task_callable=self.processor.garbage_collect_orphaned_images,
            on_success=on_success,
            on_error=on_error,
            loading_dialog_title="Garbage Collecting Images",
            loading_dialog_message="Scanning for and deleting orphaned images..."
        )

    def _on_double_click(self, event=None):
        """Handles double-click on an item to load it into the main window."""
        self._load_to_main_window()

    def _load_to_main_window(self):
        """Intelligently loads the selected history item into the main window."""
        if not self.selected_row_data:
            return

        # Prioritize reloading the template if context is available, as it's more editable.
        has_template_context = self.selected_row_data.get('template_name') and self.selected_row_data.get('context')
        if has_template_context:
            self._reload_template_to_main_window()
        else:
            self._load_prompt_to_main_window()

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
                    if self.selected_widget_info == widget_to_remove:
                        self.selected_widget_info = None
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

        updated_row = copy.deepcopy(original_row)
        updated_row['favorite'] = not updated_row.get('favorite', False)

        success = self.processor.update_history_entry(original_row, updated_row)
        if success:
            # Update the master data list
            row_id = original_row.get('id')
            for i, row in enumerate(self.all_history_data):
                if row.get('id') == row_id:
                    self.all_history_data[i] = updated_row
                    break
            
            # Find the widget associated with this data
            widget_info = next((w for w in self.history_widgets if w['data'].get('id') == row_id), None)
            if widget_info:
                # Update the widget's internal data reference
                widget_info['data'] = updated_row
                
                # Re-apply filters to handle visibility
                self._apply_filters()
                
                # Re-select the item to update its style and the details pane.
                self._on_item_select(widget_info)
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
        
        # --- Loading Sub-menu ---
        load_menu = tk.Menu(self.context_menu, tearoff=0)
        load_menu.add_command(label="Load Final Prompt to Editor", command=self._load_prompt_to_main_window)
        has_template_context = full_row_data.get('template_name') and full_row_data.get('context')
        load_menu.add_command(label="Reload Template & Choices", command=self._reload_template_to_main_window, state=tk.NORMAL if has_template_context else tk.DISABLED)
        self.context_menu.add_cascade(label="Load to Main Window", menu=load_menu)

        # --- Enhancement ---
        has_original = bool(full_row_data.get('original_prompt'))
        has_enhanced = 'enhanced' in full_row_data and full_row_data.get('enhanced')
        num_variations = len(full_row_data.get('variations', {}))
        total_possible_variations = len(self.available_variations_map)
        can_enhance = has_original and (not has_enhanced or num_variations < total_possible_variations)

        self.context_menu.add_command(
            label="Enhance This Prompt...", 
            command=self._enhance_from_history, 
            state=tk.NORMAL if can_enhance else tk.DISABLED
        )

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

    def _load_prompt_to_main_window(self):
        """Sends the selected original prompt back to the main app for re-enhancement."""
        if not self.selected_row_data: return
        full_row_data = self.selected_row_data
        if full_row_data:
            original_prompt = full_row_data.get('original_prompt', '')
            if original_prompt:
                # Pass the ID of the history entry to be updated
                entry_id = full_row_data.get('id')
                self.parent_app.load_prompt_from_history(original_prompt, history_entry_id=entry_id)
                self.destroy()

    def _enhance_from_history(self):
        """Starts the enhancement process for the selected history item directly."""
        if not self.selected_row_data:
            return

        full_row_data = self.selected_row_data
        original_prompt = full_row_data.get('original_prompt')
        if not original_prompt:
            custom_dialogs.show_error(self, "Error", "No original prompt found in this entry to enhance.")
            return

        template_name = full_row_data.get('template_name')
        context = full_row_data.get('context')
        entry_id = full_row_data.get('id')

        # This will open the enhancement window and start the process.
        # The enhancement window will then handle saving the updated data back to the existing entry ID.
        self.parent_app.start_enhancement_for_prompt(prompt_text=original_prompt, template_name=template_name, context=context, existing_entry_id=entry_id)

    def _reload_template_to_main_window(self):
        """Sends the selected entry's template and context back to the main app."""
        if not self.selected_row_data: return
        template_name = self.selected_row_data.get('template_name')
        context = self.selected_row_data.get('context')
        if template_name and context:
            self.parent_app.load_template_from_history(template_name, context)
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
        elif 'variations' in updated_row and key in updated_row['variations']:
            updated_row['variations'][key]['prompt'] = new_text
        else:
            # This case should not be reached if edit buttons are only on valid tabs
            custom_dialogs.show_error(self, "Error", f"Could not find data for '{key}' to update.")
            return

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