"""The main action bar with Generate, Enhance, and variation selection."""

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Callable
from .common import Tooltip

VARIATION_TOOLTIPS = {
    'cinematic': 'Re-writes the prompt with a focus on dramatic lighting, camera angles, and movie-like composition.',
    'artistic': 'Re-writes the prompt to emphasize painterly qualities, specific art movements, or artistic techniques.',
    'photorealistic': 'Re-writes the prompt to include technical photography details, realistic lighting, and high-quality descriptors.'
}

class ActionBar(ttk.Frame):
    """The main action bar with Generate, Enhance, and variation selection."""
    def __init__(self, parent, generate_callback: Callable, enhance_callback: Callable, copy_callback: Callable, **kwargs):
        super().__init__(parent, **kwargs)

        self.generate_button = ttk.Button(self, text="Generate Next Preview", command=generate_callback, state=tk.DISABLED)
        self.generate_button.pack(side=tk.LEFT, padx=(0, 5))

        self.select_button = ttk.Button(self, text="Enhance This Prompt", command=enhance_callback, state=tk.DISABLED)
        self.select_button.pack(side=tk.LEFT)

        self.variations_frame = ttk.LabelFrame(self, text="Variations", padding=(10, 5))
        self.variations_frame.pack(side=tk.LEFT, padx=(10, 0))
        
        self.variation_vars: Dict[str, tk.BooleanVar] = {}
        self.variation_tooltips: List[Tooltip] = []

        self.copy_prompt_button = ttk.Button(self, text="Copy Prompt", command=copy_callback, state=tk.DISABLED)
        self.copy_prompt_button.pack(side=tk.LEFT, padx=(10, 0))

    def rebuild_variations(self, variation_keys: List[str]):
        """Clears and recreates the variation checkboxes."""
        for widget in self.variations_frame.winfo_children():
            widget.destroy()

        self.variation_vars.clear()
        self.variation_tooltips.clear()

        for key in variation_keys:
            var = tk.BooleanVar(value=True)
            self.variation_vars[key] = var
            cb = ttk.Checkbutton(self.variations_frame, text=key.capitalize(), variable=var)
            cb.pack(side=tk.LEFT, padx=5)
            tooltip = Tooltip(cb, VARIATION_TOOLTIPS.get(key, "Generate this variation."))
            cb.bind("<Enter>", tooltip.show)
            cb.bind("<Leave>", tooltip.hide)
            self.variation_tooltips.append(tooltip)

    def get_selected_variations(self) -> List[str]:
        """Returns a list of the names of the selected variations."""
        return [key for key, var in self.variation_vars.items() if var.get()]

    def set_button_states(self, generate: str, enhance: str, copy: str):
        self.generate_button.config(state=generate)
        self.select_button.config(state=enhance)
        self.copy_prompt_button.config(state=copy)