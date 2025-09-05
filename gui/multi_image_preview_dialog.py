"""A dialog to preview multiple generated images and select which to keep."""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import io
from typing import List, Dict, Any

from .common import SmartWindowMixin
from . import custom_dialogs

class MultiImagePreviewDialog(custom_dialogs._CustomDialog, SmartWindowMixin):
    """A dialog to preview multiple generated images and select which to keep."""
    def __init__(self, parent, image_results: List[Dict[str, Any]]):
        super().__init__(parent, "Review Generated Images")
        self.image_results = image_results
        self.kept_images = [True] * len(image_results) # Start with all images marked to be kept
        self.current_index = 0
        self.image_ref = None

        self._create_widgets()
        self._display_current_image()

        self.smart_geometry(min_width=700, min_height=750)
        self.wait_window(self)

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Image display
        image_frame = ttk.LabelFrame(main_frame, text="Preview", padding=5)
        image_frame.pack(fill=tk.BOTH, expand=True)
        self.image_label = ttk.Label(image_frame, anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)

        # Pagination controls
        pagination_frame = ttk.Frame(main_frame)
        pagination_frame.pack(fill=tk.X, pady=5)
        self.prev_button = ttk.Button(pagination_frame, text="< Prev", command=self._prev_image)
        self.prev_button.pack(side=tk.LEFT)
        self.next_button = ttk.Button(pagination_frame, text="Next >", command=self._next_image)
        self.next_button.pack(side=tk.RIGHT)
        self.image_info_label = ttk.Label(pagination_frame, text="", anchor=tk.CENTER)
        self.image_info_label.pack(fill=tk.X, expand=True, padx=10)

        # Keep checkbox
        self.keep_var = tk.BooleanVar()
        self.keep_check = ttk.Checkbutton(main_frame, text="Keep this image", variable=self.keep_var, command=self._toggle_keep, style='Switch.TCheckbutton')
        self.keep_check.pack(pady=10)

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        spacer = ttk.Frame(button_frame)
        spacer.pack(side=tk.LEFT, expand=True)

        self.save_button = ttk.Button(button_frame, text="Save Kept Images", command=self._on_ok, style="Accent.TButton")
        self.save_button.pack(side=tk.LEFT)
        self.discard_button = ttk.Button(button_frame, text="Discard All", command=self._on_cancel)
        self.discard_button.pack(side=tk.LEFT, padx=(5, 0))

    def _display_current_image(self):
        if not self.image_results:
            self.destroy()
            return

        current_image_data = self.image_results[self.current_index]
        
        # Display image
        try:
            img_data = io.BytesIO(current_image_data['bytes'])
            img = Image.open(img_data)
            
            max_size = (650, 650)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            self.image_ref = ImageTk.PhotoImage(img)
            self.image_label.config(image=self.image_ref)
        except Exception as e:
            self.image_label.config(text=f"Error displaying image:\n{e}", image='')
            self.image_ref = None

        # Update info label
        model_name = current_image_data.get('generation_params', {}).get('model', {}).get('name', 'Unknown Model')
        self.image_info_label.config(text=f"({self.current_index + 1}/{len(self.image_results)}) Model: {model_name}")

        # Update checkbox
        self.keep_var.set(self.kept_images[self.current_index])

        # Update button states
        self.prev_button.config(state=tk.NORMAL if self.current_index > 0 else tk.DISABLED)
        self.next_button.config(state=tk.NORMAL if self.current_index < len(self.image_results) - 1 else tk.DISABLED)

    def _toggle_keep(self):
        self.kept_images[self.current_index] = self.keep_var.get()

    def _next_image(self):
        if self.current_index < len(self.image_results) - 1:
            self.current_index += 1
            self._display_current_image()

    def _prev_image(self):
        if self.current_index > 0:
            self.current_index -= 1
            self._display_current_image()

    def _on_ok(self, event=None):
        self.result = [img for i, img in enumerate(self.image_results) if self.kept_images[i]]
        self.destroy()

    def _on_cancel(self, event=None):
        self.result = []
        self.destroy()