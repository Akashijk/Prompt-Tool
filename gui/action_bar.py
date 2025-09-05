"""The main action bar with Generate, Enhance, and variation selection."""

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Callable, Optional, TYPE_CHECKING
from .common import Tooltip

class ActionBar(ttk.Frame):
    """The main action bar with Generate, Enhance, and variation selection."""
    def __init__(self, parent, generate_callback: Callable, enhance_callback: Callable, copy_callback: Callable, save_as_template_callback: Callable, ai_cleanup_callback: Callable, generate_image_callback: Callable, **kwargs):
        super().__init__(parent, **kwargs)

        self.generate_button = ttk.Button(self, text="Generate Next Preview", command=generate_callback, state=tk.DISABLED)
        self.generate_button.pack(side=tk.LEFT, padx=(0, 5))

        self.ai_cleanup_button = ttk.Button(self, text="AI Cleanup ✨", command=ai_cleanup_callback, state=tk.DISABLED)
        self.ai_cleanup_button.pack(side=tk.LEFT, padx=(0, 5))
        Tooltip(self.ai_cleanup_button, "Use AI to fix grammar and flow in the generated prompt.")

        self.select_button = ttk.Button(self, text="Enhance This Prompt", command=enhance_callback, state=tk.DISABLED)
        self.select_button.pack(side=tk.LEFT)

        self.variations_frame = ttk.LabelFrame(self, text="Variations", padding=(10, 5))
        self.variations_frame.pack(side=tk.LEFT, padx=(10, 0))
        
        self.variation_vars: Dict[str, tk.BooleanVar] = {}
        self.variation_tooltips: List[Tooltip] = []

        self.copy_prompt_button = ttk.Button(self, text="Copy Prompt", command=copy_callback, state=tk.DISABLED)
        self.copy_prompt_button.pack(side=tk.LEFT, padx=(10, 0))

        self.save_as_template_button = ttk.Button(self, text="Save as Template", command=save_as_template_callback, state=tk.DISABLED)
        self.save_as_template_button.pack(side=tk.LEFT, padx=(5, 0))

        # Create a container for the image generation controls on the right
        self.image_gen_frame = ttk.Frame(self)
        self.image_gen_frame.pack(side=tk.RIGHT, padx=(10, 0))

        # The spinner will be packed to the left of the button when active
        from .common import LoadingAnimation # Local import to avoid circular dependency
        self.image_gen_spinner = LoadingAnimation(self.image_gen_frame, size=20)

        self.generate_image_button = ttk.Button(self.image_gen_frame, text="Generate Image", command=generate_image_callback, state=tk.DISABLED)
        self.generate_image_button.pack(side=tk.LEFT)

    def rebuild_variations(self, variations: List[Dict[str, str]]):
        """Clears and recreates the variation checkboxes."""
        for widget in self.variations_frame.winfo_children():
            widget.destroy()

        self.variation_vars.clear()
        self.variation_tooltips.clear()

        for variation in variations:
            key = variation['key']
            name = variation['name']
            description = variation.get('description', 'Generate this variation.')
            var = tk.BooleanVar(value=True)
            self.variation_vars[key] = var
            cb = ttk.Checkbutton(self.variations_frame, text=name, variable=var)
            cb.pack(side=tk.LEFT, padx=5)
            tooltip = Tooltip(cb, description)
            cb.bind("<Enter>", tooltip.show)
            cb.bind("<Leave>", tooltip.hide)
            self.variation_tooltips.append(tooltip)

    def get_selected_variations(self) -> List[str]:
        """Returns a list of the names of the selected variations."""
        return [key for key, var in self.variation_vars.items() if var.get()]

    def set_button_states(self, generate: str, enhance: str, copy: str, save_as_template: Optional[str] = None, ai_cleanup: Optional[str] = None, generate_image: Optional[str] = None):
        self.generate_button.config(state=generate)
        self.select_button.config(state=enhance)
        self.copy_prompt_button.config(state=copy)
        if save_as_template is not None:
            self.save_as_template_button.config(state=save_as_template)
        if ai_cleanup is not None:
            self.ai_cleanup_button.config(state=ai_cleanup)
        if generate_image is not None:
            self.generate_image_button.config(state=generate_image)