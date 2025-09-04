"""A window for generating a prompt from an image using a multimodal AI model."""

import tkinter as tk
from tkinter import ttk, filedialog
import base64
import sys
import os
import threading
import queue
from typing import Optional, List, Callable, TYPE_CHECKING
from PIL import Image, ImageTk

from .common import SmartWindowMixin, TextContextMenu
from . import custom_dialogs
from core.default_content import DEFAULT_AI_INTERROGATE_IMAGE_SFW_PROMPT, DEFAULT_AI_INTERROGATE_IMAGE_NSFW_PROMPT

if TYPE_CHECKING:
    from .gui_app import GUIApp
    from core.prompt_processor import PromptProcessor

class ImageInterrogatorWindow(tk.Toplevel, SmartWindowMixin):
    """A window for generating a prompt from an image."""
    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor', models: List[str], default_model: str, load_prompt_callback: Callable):
        super().__init__(parent)
        self.title("Image Interrogator")
        self.parent_app = parent
        self.processor = processor
        self.load_prompt_callback = load_prompt_callback
        self.image_path: Optional[str] = None
        self.image_ref: Optional[ImageTk.PhotoImage] = None
        self.interrogation_queue = queue.Queue()
        self.after_id: Optional[str] = None

        # --- Widgets ---
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top controls
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(control_frame, text="Select Image...", command=self._select_image).pack(side=tk.LEFT)
        
        ttk.Label(control_frame, text="Model:").pack(side=tk.LEFT, padx=(10, 5))
        
        vision_models = [m for m in models if 'llava' in m.lower() or 'bakllava' in m.lower()]
        if not vision_models:
            custom_dialogs.show_warning(self, "No Vision Models", "No LLaVA or BakLLaVA models found in Ollama. Please pull one to use this feature (e.g., 'ollama run llava').")
            self.model_var = tk.StringVar(value="No vision models found")
            model_menu = ttk.OptionMenu(control_frame, self.model_var, "No vision models found")
        else:
            # If the main app's model is a vision model, use it. Otherwise, default to the first available vision model.
            vision_default = default_model if default_model in vision_models else vision_models[0]
            self.model_var = tk.StringVar(value=vision_default)
            model_menu = ttk.OptionMenu(control_frame, self.model_var, vision_default, *vision_models)
        model_menu.pack(side=tk.LEFT)

        self.generate_button = ttk.Button(control_frame, text="Generate Prompt", command=self._generate_prompt, state=tk.DISABLED)
        self.generate_button.pack(side=tk.RIGHT)

        # Main content area
        content_pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        content_pane.pack(fill=tk.BOTH, expand=True)

        # Image display
        image_frame = ttk.LabelFrame(content_pane, text="Image Preview", padding=5)
        self.image_label = ttk.Label(image_frame, text="No image selected.", anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        content_pane.add(image_frame, weight=1)

        # Prompt display
        prompt_frame = ttk.LabelFrame(content_pane, text="Generated Prompt", padding=5)
        self.prompt_text = tk.Text(prompt_frame, wrap=tk.WORD, height=10, font=self.parent_app.default_font, undo=True, exportselection=False)
        self.prompt_text.pack(fill=tk.BOTH, expand=True)
        TextContextMenu(self.prompt_text)
        content_pane.add(prompt_frame, weight=1)

        # Bottom action buttons
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(10, 0))
        self.copy_button = ttk.Button(bottom_frame, text="Copy Prompt", command=self._copy_prompt, state=tk.DISABLED)
        self.copy_button.pack(side=tk.LEFT)
        self.send_button = ttk.Button(bottom_frame, text="Send to Main Editor", command=self._send_to_editor, state=tk.DISABLED)
        self.send_button.pack(side=tk.RIGHT)

        self.smart_geometry(min_width=800, min_height=500)

    def _select_image(self):
        """Opens a file dialog to select an image."""
        # Suppress a known harmless macOS stderr warning about NSOpenPanel.
        original_stderr = sys.stderr
        sys.stderr = open(os.devnull, 'w')
        try:
            file_path = filedialog.askopenfilename(
                title="Select an Image",
                filetypes=[("Image Files", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")]
            )
        finally:
            sys.stderr.close()
            sys.stderr = original_stderr

        if not file_path:
            return

        self.image_path = file_path
        try:
            img = Image.open(self.image_path)
            img.thumbnail((400, 400)) # Create a thumbnail for display
            self.image_ref = ImageTk.PhotoImage(img)
            self.image_label.config(image=self.image_ref, text="")
            self.generate_button.config(state=tk.NORMAL)
        except Exception as e:
            custom_dialogs.show_error(self, "Image Error", f"Could not load or display the image:\n{e}")
            self.image_path = None
            self.generate_button.config(state=tk.DISABLED)

    def _generate_prompt(self):
        """Starts the prompt generation in a background thread."""
        if not self.image_path: return
        model = self.model_var.get()
        if "model" in model.lower():
            custom_dialogs.show_error(self, "Model Error", "Please select a valid vision model.")
            return

        self.generate_button.config(state=tk.DISABLED, text="Generating...")
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", "Analyzing image with AI...")

        # Determine which prompt to use based on the current workflow
        workflow = self.parent_app.workflow_var.get()
        interrogation_prompt = DEFAULT_AI_INTERROGATE_IMAGE_NSFW_PROMPT if workflow == 'nsfw' else DEFAULT_AI_INTERROGATE_IMAGE_SFW_PROMPT

        def task():
            try:
                with open(self.image_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                prompt = self.processor.ai_interrogate_image(encoded_string, model, interrogation_prompt)
                self.interrogation_queue.put({'success': True, 'prompt': prompt})
            except Exception as e:
                self.interrogation_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_queue)

    def _check_queue(self):
        """Checks the queue for results from the background thread."""
        try:
            result = self.interrogation_queue.get_nowait()
            self.generate_button.config(state=tk.NORMAL, text="Generate Prompt")
            self.prompt_text.delete("1.0", tk.END)
            if result['success']:
                self.prompt_text.insert("1.0", result['prompt'])
                self.copy_button.config(state=tk.NORMAL)
                self.send_button.config(state=tk.NORMAL)
            else:
                self.prompt_text.insert("1.0", f"Error: {result['error']}")
        except queue.Empty:
            self.after_id = self.after(100, self._check_queue)

    def _copy_prompt(self):
        """Copies the generated prompt to the clipboard."""
        prompt = self.prompt_text.get("1.0", "end-1c").strip()
        if prompt:
            self.clipboard_clear()
            self.clipboard_append(prompt)
            custom_dialogs.show_info(self, "Copied", "Prompt copied to clipboard.")

    def _send_to_editor(self):
        """Sends the generated prompt to the main editor window."""
        prompt = self.prompt_text.get("1.0", "end-1c").strip()
        if prompt:
            self.load_prompt_callback(prompt)
            custom_dialogs.show_info(self, "Sent", "Prompt loaded into the main editor.")
            self.destroy()