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

from .common import SmartWindowMixin, LoadingAnimation, Tooltip, TextContextMenu
from . import custom_dialogs
from core.config import config

if TYPE_CHECKING:
    from .gui_app import GUIApp
    from core.prompt_processor import PromptProcessor

class FavoriteImagesViewer(tk.Toplevel, SmartWindowMixin):
    """A window to view and manage all favorited images."""
    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor'):
        super().__init__(parent)
        self.title("Favorite Images")
        self.parent_app = parent
        self.processor = processor
        self.load_queue = queue.Queue()
        self.after_id: Optional[str] = None
        self.favorite_widgets: List[Dict[str, Any]] = []

        self._create_widgets()
        self._start_loading_favorites()

        self.smart_geometry(min_width=1000, min_height=700)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _on_mouse_wheel(self, event):
        """Handles mouse wheel scrolling for the list."""
        delta = -1 * (event.delta if sys.platform == 'darwin' else event.delta // 120)
        self.canvas.yview_scroll(delta, "units")

    def close(self):
        """Safely close the window, cancelling any pending after() jobs."""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.destroy()

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.loading_animation = LoadingAnimation(main_frame, size=32)
        self.loading_label = ttk.Label(main_frame, text="Loading favorite images...")

        self.canvas = tk.Canvas(main_frame, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.canvas.yview)
        self.container = ttk.Frame(self.canvas)
        self.canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        canvas_frame = self.canvas.create_window((0, 0), window=self.container, anchor="nw")

        def on_frame_configure(event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def on_canvas_configure(event):
            self.canvas.itemconfig(canvas_frame, width=event.width)

        self.container.bind("<Configure>", on_frame_configure)
        self.canvas.bind("<Configure>", on_canvas_configure)
        # Add mouse wheel scrolling
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.container.bind("<MouseWheel>", self._on_mouse_wheel)

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
        self.after_id = self.after(100, self._check_load_queue)

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
            self.after_id = self.after(100, self._check_load_queue)

    def _populate_viewer(self, favorites_data: List[Dict[str, Any]]):
        """Clears and fills the view with favorite image entries."""
        for widget_info in self.favorite_widgets:
            widget_info['frame'].destroy()
        self.favorite_widgets.clear()

        if not favorites_data:
            ttk.Label(self.container, text="No favorite images found.", padding=20).pack()
            return

        for fav_data in favorites_data:
            item_frame = ttk.Frame(self.container, style="HistoryItem.TFrame", relief="groove", borderwidth=1, padding=10)
            item_frame.pack(fill=tk.X, pady=5, padx=5)
            item_frame.bind("<MouseWheel>", self._on_mouse_wheel)

            # Image
            img_label = ttk.Label(item_frame, anchor=tk.CENTER)
            img_label.pack(side=tk.LEFT, padx=(0, 10))
            self._load_thumbnail(img_label, fav_data.get('image_path'))

            # Info and actions
            info_frame = ttk.Frame(item_frame)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            info_frame.bind("<MouseWheel>", self._on_mouse_wheel)

            prompt_label = ttk.Label(info_frame, text=f"Prompt ({fav_data.get('prompt_type', 'N/A')}):", font=self.parent_app.small_font)
            prompt_label.pack(anchor='w')
            prompt_text = tk.Text(info_frame, height=4, wrap=tk.WORD, font=self.parent_app.default_font, relief=tk.FLAT)
            prompt_text.insert("1.0", fav_data.get('prompt', ''))
            prompt_text.config(state=tk.DISABLED)
            prompt_text.pack(fill=tk.X, expand=True, pady=(0, 5))
            prompt_text.bind("<MouseWheel>", self._on_mouse_wheel)
            TextContextMenu(prompt_text)

            # Generation parameters
            gen_params = fav_data.get('generation_params', {})
            model_name = gen_params.get('model', {}).get('name', 'N/A')
            seed = gen_params.get('seed', 'N/A')
            params_str = f"Model: {model_name} | Seed: {seed}"
            params_label = ttk.Label(info_frame, text=params_str, font=self.parent_app.small_font)
            params_label.bind("<MouseWheel>", self._on_mouse_wheel)
            params_label.pack(anchor='w')
            Tooltip(params_label, json.dumps(gen_params, indent=2))

            # Action buttons
            button_frame = ttk.Frame(info_frame)
            button_frame.bind("<MouseWheel>", self._on_mouse_wheel)
            button_frame.pack(fill=tk.X, pady=(10, 0))
            
            unfav_button = ttk.Button(button_frame, text="Unfavorite", command=lambda d=fav_data, f=item_frame: self._unfavorite_image(d, f))
            unfav_button.pack(side=tk.LEFT)
            
            perm_button = ttk.Button(button_frame, text="Generate Permutations...")
            perm_button.config(command=lambda d=fav_data, b=perm_button: self._generate_permutations(d, b))
            perm_button.pack(side=tk.LEFT, padx=5)

            self.favorite_widgets.append({'frame': item_frame, 'data': fav_data})

    def _load_thumbnail(self, label_widget: ttk.Label, image_path: Optional[str]):
        """Loads an image thumbnail into a label."""
        if not image_path:
            label_widget.config(text="Path\nMissing")
            return

        try:
            full_path = os.path.join(config.get_history_file_dir(), image_path)
            if not os.path.exists(full_path):
                label_widget.config(text="Image\nNot Found")
                return

            img = Image.open(full_path)
            img.thumbnail((128, 128))
            img_ref = ImageTk.PhotoImage(img)
            label_widget.config(image=img_ref)
            label_widget.image = img_ref  # Keep a reference
        except Exception as e:
            label_widget.config(text="Load\nError")
            print(f"Error loading thumbnail {image_path}: {e}")

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
            saved_images_data = [{'image_path': self.processor.save_generated_image(img['bytes']), 'generation_params': img.get('generation_params')} for img in images_to_save]
            original_history_id = fav_data.get('history_id')
            entry = {
                'original_prompt': images_to_save[0]['prompt'], 
                'status': 'generated_only', 
                'original_images': saved_images_data, 
                'template_name': f"Permutation of history ID {original_history_id}" if original_history_id else "Permutation from favorite"
            }
            self.processor.history_manager.save_result(**entry)
            custom_dialogs.show_info(self, "Image Saved", f"{len(saved_images_data)} image(s) and prompt saved to history.")

        self.parent_app._start_image_generation_workflow(
            parent_window=self,
            prompt=prompt,
            initial_dialog_params=gen_params,
            button_to_manage=button,
            spinner_to_manage=None, # This window doesn't have a dedicated spinner
            on_success_callback=on_success
        )