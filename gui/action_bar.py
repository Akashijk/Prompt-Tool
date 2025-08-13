"""The main action bar with Generate, Enhance, and variation selection."""

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Callable, Optional
from .common import Tooltip

class ActionBar(ttk.Frame):
    """The main action bar with Generate, Enhance, and variation selection."""
    def __init__(self, parent, generate_callback: Callable, enhance_callback: Callable, copy_callback: Callable, suggest_callback: Callable, save_as_template_callback: Callable, **kwargs):
        super().__init__(parent, **kwargs)

        self.generate_button = ttk.Button(self, text="Generate Next Preview", command=generate_callback, state=tk.DISABLED)
        self.generate_button.pack(side=tk.LEFT, padx=(0, 5))

        self.select_button = ttk.Button(self, text="Enhance This Prompt", command=enhance_callback, state=tk.DISABLED)
        self.select_button.pack(side=tk.LEFT)

        self.suggest_button = ttk.Button(self, text="Suggest (AI)", command=suggest_callback, state=tk.DISABLED)
        self.suggest_button.pack(side=tk.LEFT, padx=(5,0))
        suggest_tooltip = Tooltip(self.suggest_button, "Ask the AI to suggest an improved version of the current prompt in the editor.")
        self.suggest_button.bind("<Enter>", suggest_tooltip.show)
        self.suggest_button.bind("<Leave>", suggest_tooltip.hide)

        self.variations_frame = ttk.LabelFrame(self, text="Variations", padding=(10, 5))
        self.variations_frame.pack(side=tk.LEFT, padx=(10, 0))
        
        self.variation_vars: Dict[str, tk.BooleanVar] = {}
        self.variation_tooltips: List[Tooltip] = []

        self.copy_prompt_button = ttk.Button(self, text="Copy Prompt", command=copy_callback, state=tk.DISABLED)
        self.copy_prompt_button.pack(side=tk.LEFT, padx=(10, 0))

        self.save_as_template_button = ttk.Button(self, text="Save as Template", command=save_as_template_callback, state=tk.DISABLED)
        self.save_as_template_button.pack(side=tk.LEFT, padx=(5, 0))

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

    def set_button_states(self, generate: str, enhance: str, copy: str, suggest: Optional[str] = None, save_as_template: Optional[str] = None):
        self.generate_button.config(state=generate)
        self.select_button.config(state=enhance)
        self.copy_prompt_button.config(state=copy)
        if suggest is not None:
            self.suggest_button.config(state=suggest)
        if save_as_template is not None:
            self.save_as_template_button.config(state=save_as_template)