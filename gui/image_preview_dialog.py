"""A dialog to preview a generated image and ask for confirmation to save."""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import io
from .common import SmartWindowMixin
from . import custom_dialogs

class ImagePreviewDialog(custom_dialogs._CustomDialog, SmartWindowMixin):
    """A dialog to preview a generated image and ask for confirmation to save."""
    def __init__(self, parent, image_bytes: bytes, prompt_text: str):
        super().__init__(parent, "Image Generation Result")
        self.image_bytes = image_bytes
        self.image_ref = None

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Display the prompt that generated the image
        prompt_frame = ttk.LabelFrame(main_frame, text="Generated with Prompt", padding=5)
        prompt_frame.pack(fill=tk.X, pady=(0, 10))
        prompt_label = ttk.Label(prompt_frame, text=prompt_text, wraplength=580)
        prompt_label.pack(fill=tk.X)

        # Image display
        image_frame = ttk.LabelFrame(main_frame, text="Preview", padding=5)
        image_frame.pack(fill=tk.BOTH, expand=True)
        self.image_label = ttk.Label(image_frame, anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        self._display_image()

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        # Add a spacer to push buttons to the right
        spacer = ttk.Frame(button_frame)
        spacer.pack(side=tk.LEFT, expand=True)

        self.save_button = ttk.Button(button_frame, text="Save to History", command=self._on_ok, style="Accent.TButton")
        self.save_button.pack(side=tk.LEFT)
        self.discard_button = ttk.Button(button_frame, text="Discard", command=self._on_cancel)
        self.discard_button.pack(side=tk.LEFT, padx=(5, 0))

        self.smart_geometry(min_width=600, min_height=650)
        self.wait_window(self)

    def _display_image(self):
        try:
            img_data = io.BytesIO(self.image_bytes)
            img = Image.open(img_data)
            
            # Resize for display
            max_size = (600, 600)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            self.image_ref = ImageTk.PhotoImage(img)
            self.image_label.config(image=self.image_ref)
        except Exception as e:
            self.image_label.config(text=f"Error displaying image:\n{e}")

    def _on_ok(self, event=None):
        self.result = True
        self.destroy()