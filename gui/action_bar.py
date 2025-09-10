"""The main action bar with Generate, Enhance, and variation selection."""

import tkinter as tk
from tkinter import ttk
import random
from typing import Dict, List, Callable, Optional, TYPE_CHECKING
from .common import Tooltip

class ActionBar(ttk.Frame):
    """The main action bar with Generate, Enhance, and variation selection."""
    def __init__(self, parent, generate_callback: Callable, enhance_callback: Callable, 
                 copy_callback: Callable, save_as_template_callback: Callable, 
                 generate_image_callback: Callable, suggest_callback: Callable, 
                 seed_var: tk.StringVar, random_seed_var: tk.BooleanVar, 
                 randomize_seed_callback: Callable, **kwargs):
        super().__init__(parent, **kwargs)
        
        # Store callbacks as instance variables
        self.generate_callback = generate_callback
        self.enhance_callback = enhance_callback
        self.copy_callback = copy_callback
        self.save_as_template_callback = save_as_template_callback
        self.generate_image_callback = generate_image_callback
        self.suggest_callback = suggest_callback
        self.seed_var = seed_var
        self.random_seed_var = random_seed_var
        self.randomize_seed_callback = randomize_seed_callback
        
        # Main container that will center everything
        self.main_container = ttk.Frame(self)
        self.main_container.pack(expand=True, fill='both', padx=20, pady=10)
        
        # Configure main container to center content
        self.main_container.columnconfigure(0, weight=1)
        self.main_container.columnconfigure(1, weight=0)  # Content column
        self.main_container.columnconfigure(2, weight=1)
        
        # Content frame - all our actual widgets go here
        self.content_frame = ttk.Frame(self.main_container)
        self.content_frame.grid(row=0, column=1, sticky='')
        
        self._create_primary_actions()
        self._create_secondary_actions()
        self._create_seed_controls()
        self._create_variations_section()
        
    def _create_primary_actions(self):
        """Create the main action buttons (top row)"""
        primary_frame = ttk.LabelFrame(self.content_frame, text="Generate Actions", 
                                     padding=(12, 8))
        primary_frame.pack(pady=(0, 10), fill='x')
        
        # Center the buttons in this frame
        button_container = ttk.Frame(primary_frame)
        button_container.pack()
        
        self.enhance_template_button = ttk.Button(
            button_container, 
            text="Enhance Template (AI)", 
            command=self.suggest_callback, 
            state=tk.DISABLED
        )
        self.enhance_template_button.pack(side='left', padx=(0, 8))
        Tooltip(self.enhance_template_button, 
                "Ask the AI to enhance the current template with more detail and wildcards.")
        
        self.generate_button = ttk.Button(
            button_container, 
            text="Generate Next Preview", 
            command=self.generate_callback, 
            state=tk.DISABLED
        )
        self.generate_button.pack(side='left', padx=8)
        
        self.select_button = ttk.Button(
            button_container, 
            text="Enhance This Prompt", 
            command=self.enhance_callback, 
            state=tk.DISABLED
        )
        self.select_button.pack(side='left', padx=(8, 0))
        
    def _create_secondary_actions(self):
        """Create output/utility buttons (second row)"""
        secondary_frame = ttk.LabelFrame(self.content_frame, text="Output Actions", 
                                       padding=(12, 8))
        secondary_frame.pack(pady=(0, 10), fill='x')
        
        # Container to center all the content
        button_container = ttk.Frame(secondary_frame)
        button_container.pack()
        
        # Left side: Copy and Save buttons
        left_actions = ttk.Frame(button_container)
        left_actions.pack(side='left', padx=(0, 20))
        
        self.copy_prompt_button = ttk.Button(left_actions, text="Copy Prompt", 
                                           command=self.copy_callback, state=tk.DISABLED)
        self.copy_prompt_button.pack(side='left', padx=(0, 8))
        
        self.save_as_template_button = ttk.Button(left_actions, text="Save as Template", 
                                                command=self.save_as_template_callback, 
                                                state=tk.DISABLED)
        self.save_as_template_button.pack(side='left')
        
        # Right side: Image generation
        self.image_gen_frame = ttk.Frame(button_container)
        self.image_gen_frame.pack(side='left')
        
        # The spinner will be packed to the left of the button when active
        from .common import LoadingAnimation  # Local import to avoid circular dependency
        self.image_gen_spinner = LoadingAnimation(self.image_gen_frame, size=20)
        
        self.generate_image_button = ttk.Button(self.image_gen_frame, text="Generate Image", 
                                              command=self.generate_image_callback, 
                                              state=tk.DISABLED)
        self.generate_image_button.pack(side='left')
        
    def _create_seed_controls(self):
        """Create seed input and randomization controls"""
        seed_frame = ttk.LabelFrame(self.content_frame, text="Seed Controls", 
                                  padding=(12, 8))
        seed_frame.pack(pady=(0, 10), fill='x')
        
        # Container to center the seed controls
        seed_container = ttk.Frame(seed_frame)
        seed_container.pack()
        
        ttk.Label(seed_container, text="Seed:").pack(side='left')
        seed_entry = ttk.Entry(seed_container, textvariable=self.seed_var, width=12)
        seed_entry.pack(side='left', padx=(5, 8))
        
        dice_btn = ttk.Button(seed_container, text="🎲", width=3, 
                             command=self.randomize_seed_callback)
        dice_btn.pack(side='left', padx=(0, 8))
        Tooltip(dice_btn, "Generate random seed")
        
        lock_switch = ttk.Checkbutton(seed_container, text="Random", 
                                     variable=self.random_seed_var, 
                                     style='Switch.TCheckbutton')
        lock_switch.pack(side='left')
        Tooltip(lock_switch, 
                "Use a new random seed for each generation. Turn off to use the specific seed in the box.")
        
    def _create_variations_section(self):
        """Create the variations selection area"""
        self.variations_frame = ttk.LabelFrame(self.content_frame, text="Variations", 
                                             padding=(12, 8))
        self.variations_frame.pack(fill='x')
        
        # Container for variation checkboxes
        self.variations_container = ttk.Frame(self.variations_frame)
        self.variations_container.pack()
        
        self.variation_vars: Dict[str, tk.BooleanVar] = {}
        self.variation_tooltips: List[Tooltip] = []
        
    def rebuild_variations(self, variations: List[Dict[str, str]]):
        """Clears and recreates the variation checkboxes."""
        # Clear existing variations
        for widget in self.variations_container.winfo_children():
            widget.destroy()
            
        self.variation_vars.clear()
        self.variation_tooltips.clear()
        
        if not variations:
            return
            
        # Create new variations in a more organized layout
        for i, variation in enumerate(variations):
            key = variation['key']
            name = variation['name']
            description = variation.get('description', 'Generate this variation.')
            
            var = tk.BooleanVar(value=True)
            self.variation_vars[key] = var
            
            cb = ttk.Checkbutton(self.variations_container, text=name, variable=var)
            cb.pack(side='left', padx=(0, 12))
            
            tooltip = Tooltip(cb, description)
            cb.bind("<Enter>", tooltip.show)
            cb.bind("<Leave>", tooltip.hide)
            self.variation_tooltips.append(tooltip)
            
    def get_selected_variations(self) -> List[str]:
        """Returns a list of the names of the selected variations."""
        return [key for key, var in self.variation_vars.items() if var.get()]
        
    def set_button_states(self, generate: str, enhance: str, copy: str, 
                         save_as_template: Optional[str] = None, 
                         generate_image: Optional[str] = None, 
                         suggest: Optional[str] = None):
        """Update button states"""
        self.generate_button.config(state=generate)
        self.select_button.config(state=enhance)
        self.copy_prompt_button.config(state=copy)
        
        if save_as_template is not None:
            self.save_as_template_button.config(state=save_as_template)
        if suggest is not None:
            self.enhance_template_button.config(state=suggest)
        if generate_image is not None:
            self.generate_image_button.config(state=generate_image)