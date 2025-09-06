"""The main action bar with Generate, Enhance, and variation selection."""

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Callable, Optional, TYPE_CHECKING
from .common import Tooltip

class ActionBar(ttk.Frame):
    """The main action bar with Generate, Enhance, and variation selection."""
    def __init__(self, parent, generate_callback: Callable, enhance_callback: Callable, copy_callback: Callable, save_as_template_callback: Callable, ai_cleanup_callback: Callable, generate_image_callback: Callable, suggest_callback: Callable, **kwargs):
        super().__init__(parent, **kwargs)

        self.generate_button = ttk.Button(self, text="Generate Next Preview", command=generate_callback, state=tk.DISABLED)

        self.enhance_template_button = ttk.Button(self, text="Enhance Template (AI)", command=suggest_callback, state=tk.DISABLED)
        Tooltip(self.enhance_template_button, "Ask the AI to enhance the current template with more detail and wildcards.")

        self.ai_cleanup_button = ttk.Button(self, text="AI Cleanup ✨", command=ai_cleanup_callback, state=tk.DISABLED)
        Tooltip(self.ai_cleanup_button, "Use AI to fix grammar and flow in the generated prompt.")

        self.select_button = ttk.Button(self, text="Enhance This Prompt", command=enhance_callback, state=tk.DISABLED)

        self.variations_frame = ttk.LabelFrame(self, text="Variations", padding=(10, 5))
        
        self.variation_vars: Dict[str, tk.BooleanVar] = {}
        self.variation_tooltips: List[Tooltip] = []

        self.copy_prompt_button = ttk.Button(self, text="Copy Prompt", command=copy_callback, state=tk.DISABLED)

        self.save_as_template_button = ttk.Button(self, text="Save as Template", command=save_as_template_callback, state=tk.DISABLED)

        # Create a container for the image generation controls on the right
        self.image_gen_frame = ttk.Frame(self)

        # The spinner will be packed to the left of the button when active
        from .common import LoadingAnimation # Local import to avoid circular dependency
        self.image_gen_spinner = LoadingAnimation(self.image_gen_frame, size=20)

        self.generate_image_button = ttk.Button(self.image_gen_frame, text="Generate Image", command=generate_image_callback, state=tk.DISABLED)
        self.generate_image_button.pack(side=tk.LEFT)

        self.bind("<Configure>", self._reflow_controls)
        self.after(10, self._reflow_controls)

    def _reflow_controls(self, event=None):
        """Reflows the action bar controls based on the available width."""
        if not self.winfo_exists():
            return

        for widget in self.winfo_children():
            widget.grid_forget()

        width = self.winfo_width()
        threshold = 950 # A reasonable threshold for when to switch to vertical layout

        if width < threshold:
            # Vertical layout
            self.columnconfigure(0, weight=1)
            self.columnconfigure(1, weight=1)
            for i in range(2, 9): self.columnconfigure(i, weight=0) # Reset others

            # Group 1: Core prompt actions
            self.generate_button.grid(row=0, column=0, sticky='ew', pady=(0, 5), padx=(0, 2))
            self.select_button.grid(row=0, column=1, sticky='ew', pady=(0, 5), padx=(2, 0))
            # Group 2: AI Tools
            self.enhance_template_button.grid(row=1, column=0, sticky='ew', pady=(0, 5), padx=(0, 2))
            self.ai_cleanup_button.grid(row=1, column=1, sticky='ew', pady=(0, 5), padx=(2, 0))
            # Group 3: Variations (full width)
            self.variations_frame.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(5, 5))
            # Group 4: Utility actions
            self.copy_prompt_button.grid(row=3, column=0, sticky='ew', pady=(0, 5), padx=(0, 2))
            self.save_as_template_button.grid(row=3, column=1, sticky='ew', pady=(0, 5), padx=(2, 0))
            # Group 5: Final image generation (full width)
            self.image_gen_frame.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(5, 0))
        else:
            # Horizontal layout
            for i in range(9): self.columnconfigure(i, weight=0) # Reset all
            self.columnconfigure(7, weight=1) # Spacer column

            self.generate_button.grid(row=0, column=0, sticky='w', padx=(0, 5))
            self.enhance_template_button.grid(row=0, column=1, sticky='w', padx=(0, 5))
            self.ai_cleanup_button.grid(row=0, column=2, sticky='w', padx=(0, 5))
            self.select_button.grid(row=0, column=3, sticky='w')
            self.variations_frame.grid(row=0, column=4, sticky='w', padx=(10, 0))
            self.copy_prompt_button.grid(row=0, column=5, sticky='w', padx=(10, 0))
            self.save_as_template_button.grid(row=0, column=6, sticky='w', padx=(5, 0))
            # Column 7 is the expanding spacer
            self.image_gen_frame.grid(row=0, column=8, sticky='e', padx=(10, 0))

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

    def set_button_states(self, generate: str, enhance: str, copy: str, save_as_template: Optional[str] = None, ai_cleanup: Optional[str] = None, generate_image: Optional[str] = None, suggest: Optional[str] = None):
        self.generate_button.config(state=generate)
        self.select_button.config(state=enhance)
        self.copy_prompt_button.config(state=copy)
        if save_as_template is not None:
            self.save_as_template_button.config(state=save_as_template)
        if ai_cleanup is not None:
            self.ai_cleanup_button.config(state=ai_cleanup)
        if suggest is not None:
            self.enhance_template_button.config(state=suggest)
        if generate_image is not None:
            self.generate_image_button.config(state=generate_image)