"""A window to view and manage all favorited images from the history."""

import tkinter as tk
from tkinter import ttk
import sys
import os
import queue
import threading
import json
import copy
from PIL import Image, ImageTk
from typing import List, Dict, Optional, TYPE_CHECKING, Any

from .common import SmartWindowMixin, LoadingAnimation, Tooltip, TextContextMenu, ImagePreviewMixin, ScrollableFrame
from . import custom_dialogs
from core.config import config

if TYPE_CHECKING:
    from .gui_app import GUIApp
    from core.prompt_processor import PromptProcessor

class FavoriteImagesViewer(tk.Toplevel, SmartWindowMixin, ImagePreviewMixin):
    """A window to view and manage all favorited images."""
    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor'):
        super().__init__(parent)
        ImagePreviewMixin.__init__(self)
        self.title("Favorite Images")
        self.parent_app = parent
        self.processor = processor
        self.model_usage_manager = parent.model_usage_manager
        self.load_queue = queue.Queue() # For the main data
        self.thumbnail_queue = queue.Queue() # For loaded thumbnails
        self.load_after_id: Optional[str] = None
        self.thumbnail_after_id: Optional[str] = None
        self.favorite_widgets: List[Dict[str, Any]] = []

        self._create_widgets()
        self._start_loading_favorites()

        self.smart_geometry(min_width=1000, min_height=700)
        self.thumbnail_after_id = self.after(100, self._check_thumbnail_queue)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        """Safely close the window, cancelling any pending after() jobs."""
        if self.load_after_id:
            self.after_cancel(self.load_after_id)
            self.load_after_id = None
        if self.thumbnail_after_id:
            self.after_cancel(self.thumbnail_after_id)
            self.thumbnail_after_id = None
        self.close_preview_on_destroy()
        self.destroy()

    def _start_loading_favorites(self):
        """Shows loading indicator and starts fetching data in a thread."""
        self.loading_animation.pack(pady=20)
        self.loading_label.pack()

        def task():
            try:
                favorites = self.processor.get_all_favorite_images()
                self.load_queue.put({'success': True, 'data': favorites})
            except Exception as e:
                self.load_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.load_after_id = self.after(100, self._check_load_queue)

    def _check_load_queue(self):
        """Checks for loaded data and populates the view."""
        try:
            result = self.load_queue.get_nowait()
            self.loading_animation.pack_forget()
            self.loading_label.pack_forget()

            if result['success']:
                self._populate_viewer(result['data'])
            else:
                custom_dialogs.show_error(self, "Error Loading Favorites", result['error'])
        except queue.Empty:
            self.load_after_id = self.after(100, self._check_load_queue)

    def _check_thumbnail_queue(self):
        """Checks for loaded thumbnails and updates the UI."""
        try:
            label_widget, result = self.thumbnail_queue.get_nowait()
            if label_widget.winfo_exists():
                if isinstance(result, Image.Image):
                    img_ref = ImageTk.PhotoImage(result)
                    label_widget.config(image=img_ref)
                    label_widget.image = img_ref
                else: # It's an error
                    label_widget.config(text="Load\nError", image='')
        except queue.Empty:
            pass
        finally:
            if self.winfo_exists():
                self.thumbnail_after_id = self.after(100, self._check_thumbnail_queue)
    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.loading_animation = LoadingAnimation(main_frame, size=32)
        self.loading_label = ttk.Label(main_frame, text="Loading favorite images...")

        self.scroll_view = ScrollableFrame(main_frame)
        self.container = self.scroll_view.scrollable_frame

    def _populate_viewer(self, favorites_data: List[Dict[str, Any]]):
        """Clears and fills the view with favorite image entries."""
        for widget_info in self.favorite_widgets:
            widget_info['frame'].destroy()
        self.favorite_widgets.clear()

        self.scroll_view.pack(fill=tk.BOTH, expand=True)

        if not favorites_data:
            ttk.Label(self.container, text="No favorite images found.", padding=20).pack()
            return

        for fav_data in favorites_data:
            item_frame = ttk.Frame(self.container, style="HistoryItem.TFrame", relief="groove", borderwidth=1, padding=10)
            item_frame.pack(fill=tk.X, pady=5, padx=5)

            # Image
            img_label = ttk.Label(item_frame, anchor=tk.CENTER)
            img_label.pack(side=tk.LEFT, padx=(0, 10))
            self._load_thumbnail(img_label, fav_data.get('image_path'), fav_data.get('workflow_source', 'sfw'))

            # Bind preview events
            img_label.bind("<Enter>", lambda e, info=fav_data: self._schedule_preview(info))
            img_label.bind("<Leave>", lambda e: self._schedule_hide())

            # Info and actions
            info_frame = ttk.Frame(item_frame)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            prompt_label = ttk.Label(info_frame, text=f"Prompt ({fav_data.get('prompt_type', 'N/A')}):", font=self.parent_app.small_font)
            prompt_label.pack(anchor='w')
            prompt_text = tk.Text(info_frame, height=4, wrap=tk.WORD, font=self.parent_app.default_font, relief=tk.FLAT)
            prompt_text.insert("1.0", fav_data.get('prompt', ''))
            prompt_text.config(state=tk.DISABLED)
            prompt_text.pack(fill=tk.X, expand=True, pady=(0, 5))
            TextContextMenu(prompt_text)

            # Generation parameters
            gen_params = fav_data.get('generation_params', {})
            model_name = gen_params.get('model', {}).get('name', 'N/A')
            seed = gen_params.get('seed', 'N/A')
            params_str = f"Model: {model_name} | Seed: {seed}"
            params_label = ttk.Label(info_frame, text=params_str, font=self.parent_app.small_font)
            params_label.pack(anchor='w')
            Tooltip(params_label, json.dumps(gen_params, indent=2))

            # Action buttons
            button_frame = ttk.Frame(info_frame)
            button_frame.pack(fill=tk.X, pady=(10, 0))
            
            unfav_button = ttk.Button(button_frame, text="Unfavorite", command=lambda d=fav_data, f=item_frame: self._unfavorite_image(d, f))
            unfav_button.pack(side=tk.LEFT)
            
            perm_button = ttk.Button(button_frame, text="Generate Permutations...")
            perm_button.config(command=lambda d=fav_data, b=perm_button: self._generate_permutations(d, b))
            perm_button.pack(side=tk.LEFT, padx=5)

            self.favorite_widgets.append({'frame': item_frame, 'data': fav_data})

    def _get_preview_image(self, widget_info: Dict[str, Any]) -> Optional[Image.Image]:
        """Implementation of the abstract method from ImagePreviewMixin."""
        relative_image_path = widget_info.get('image_path')
        if not relative_image_path: return None

        try:
            workflow = widget_info.get('workflow_source', 'sfw')
            original_workflow = config.workflow
            config.workflow = workflow.lower()
            full_path = os.path.join(config.get_history_file_dir(), relative_image_path)
            config.workflow = original_workflow
            if not os.path.exists(full_path): return None
            return Image.open(full_path)
        except Exception as e:
            print(f"Error loading full image for preview: {e}")
            return None

    def _load_thumbnail(self, label_widget: ttk.Label, image_path: Optional[str], workflow: str):
        """Loads an image thumbnail in a background thread using the ThumbnailManager."""
        if not image_path:
            label_widget.config(text="Path\nMissing")
            return

        label_widget.config(text="...") # Placeholder while loading

        def task():
            try:
                thumbnail_image = self.processor.thumbnail_manager.get_thumbnail(image_path, workflow)
                if thumbnail_image:
                    self.thumbnail_queue.put((label_widget, thumbnail_image))
                else:
                    self.thumbnail_queue.put((label_widget, "Error"))
            except Exception as e:
                print(f"Error in thumbnail task for {image_path}: {e}")
                self.thumbnail_queue.put((label_widget, "Error"))

        thread = threading.Thread(target=task, daemon=True)
        thread.start()

    def _unfavorite_image(self, fav_data: Dict[str, Any], item_frame: ttk.Frame):
        """Finds the original history entry and removes the favorite flag."""
        history_id = fav_data.get('history_id')
        image_path = fav_data.get('image_path')
        if not history_id or not image_path:
            custom_dialogs.show_error(self, "Error", "Missing data to unfavorite image.")
            return

        original_entry = self.processor.history_manager.get_entry_by_id(history_id)
        if not original_entry:
            custom_dialogs.show_error(self, "Error", "Could not find the original history entry.")
            return

        updated_entry = copy.deepcopy(original_entry)
        image_found_and_updated = False

        # Search all possible image lists in the entry
        image_lists_to_check = []
        if 'original_images' in updated_entry: image_lists_to_check.append(updated_entry['original_images'])
        if 'enhanced' in updated_entry and 'images' in updated_entry['enhanced']: image_lists_to_check.append(updated_entry['enhanced']['images'])
        if 'variations' in updated_entry:
            for var_data in updated_entry['variations'].values():
                if 'images' in var_data: image_lists_to_check.append(var_data['images'])

        for img_list in image_lists_to_check:
            for img_data in img_list:
                if img_data.get('image_path') == image_path:
                    img_data['is_favorite'] = False
                    image_found_and_updated = True
                    break
            if image_found_and_updated:
                break

        if not image_found_and_updated:
            custom_dialogs.show_error(self, "Error", "Could not find the image within the original history entry.")
            return

        # Save the change
        success = self.processor.update_history_entry(original_entry, updated_entry)
        if success:
            custom_dialogs.show_info(self, "Success", "Image has been unfavorited.")
            item_frame.destroy()
            # Also refresh the history viewer if it's open
            if self.parent_app.history_viewer_window and self.parent_app.history_viewer_window.winfo_exists():
                self.parent_app.history_viewer_window.load_and_display_history()
        else:
            custom_dialogs.show_error(self, "Error", "Failed to update the history file.")

    def _generate_permutations(self, fav_data: Dict[str, Any], button: ttk.Button):
        """Opens the image generation dialog with the favorite's data."""
        prompt = fav_data.get('prompt')
        gen_params = fav_data.get('generation_params')

        if not prompt or not gen_params:
            custom_dialogs.show_error(self, "Error", "Missing prompt or generation data.")
            return

        def on_success(images_to_save: List[Dict[str, Any]]):
            """Callback to handle saving a new history entry for the permutation."""
            # --- NEW: Generate entry ID first ---
            entry_id = str(uuid.uuid4())
            saved_images_data = [{'image_path': self.processor.save_generated_image(img['bytes'], entry_id), 'generation_params': img.get('generation_params')} for img in images_to_save]
            
            prompt_type = fav_data.get('prompt_type', 'favorite')
            original_prompt_text = fav_data.get('prompt', '')
            prompt_preview = (original_prompt_text[:30] + '...') if len(original_prompt_text) > 30 else original_prompt_text
            template_name = f"Permutation of '{prompt_type}' prompt: \"{prompt_preview}\""

            entry = {
                'id': entry_id, # Add the ID here
                'original_prompt': images_to_save[0]['prompt'],
                'status': 'generated_only', 
                'original_images': saved_images_data, 
                'template_name': template_name
            }
            self.processor.history_manager.save_result(**entry)
            self.processor.clear_avg_gen_times_cache()
            custom_dialogs.show_info(self, "Image Saved", f"{len(saved_images_data)} image(s) and prompt saved to history.")

        self.parent_app._start_image_generation_workflow(
            parent_window=self,
            prompt=prompt,
            initial_dialog_params=gen_params,
            button_to_manage=button,
            spinner_to_manage=None, # This window doesn't have a dedicated spinner
            on_success_callback=on_success
        )