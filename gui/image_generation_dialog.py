"""A dialog for selecting image generation options for InvokeAI."""

import tkinter as tk
from tkinter import ttk
import queue
import random
import re
import sys
import threading
from typing import Optional, List, Dict, Any, TYPE_CHECKING, Callable, Tuple

from .common import SmartWindowMixin, Tooltip, VerticalSpinbox, ScrollableFrame
from . import custom_dialogs
from .common import TextContextMenu
from core.prompt_processor import PromptProcessor
from .model_usage_manager import ModelUsageManager
if TYPE_CHECKING:
    from core.invokeai_client import InvokeAIClient

def _sanitize_for_widget_name(name: str) -> str:
    """
    Sanitizes a string to be a valid Tkinter widget name by removing
    any characters that are not alphanumeric or underscores.
    """
    return re.sub(r'[^a-zA-Z0-9_]', '', name)

class ImageGenerationOptionsDialog(custom_dialogs._CustomDialog, SmartWindowMixin):
    """A dialog for selecting image generation options for InvokeAI."""
    def _randomize_seed(self):
        self.seed_var.set(str(random.randint(0, 2**32 - 1)))

    def __init__(self, parent, processor: 'PromptProcessor', initial_params: Optional[Dict[str, Any]] = None, is_editing: bool = False, disabled_models: Optional[List[str]] = None, base_model_type: str = 'sdxl'):
        super().__init__(parent, "Image Generation Options")
        self.processor = processor
        self.model_usage_manager: 'ModelUsageManager' = parent.model_usage_manager
        self.client = processor.invokeai_client
        self.models: Dict[str, List[Dict[str, Any]]] = {}
        self.model_data: Dict[str, Dict[str, Any]] = {}  # name -> full model object
        self.lora_data: Dict[str, Dict[str, Any]] = {}   # name -> full lora object
        self.is_editing = is_editing
        self.disabled_models = disabled_models or []
        self.initial_params = initial_params or {}
        self.model_vars: Dict[str, tk.BooleanVar] = {}
        self.model_widgets: Dict[str, ttk.Checkbutton] = {}
        self.lora_vars: Dict[str, tk.BooleanVar] = {}
        self.lora_widgets: Dict[str, ttk.Frame] = {}
        self.lora_search_var = tk.StringVar()
        self.lora_weight_vars: Dict[str, tk.StringVar] = {}
        self.model_search_var = tk.StringVar()
        self.save_to_gallery_var = tk.BooleanVar(value=False)
        self.lora_overrides: Dict[str, List[Dict[str, Any]]] = {}
        self.total_images_var = tk.StringVar()
        self.model_queue = queue.Queue()
        self.neg_prompt_overrides: Dict[str, str] = {}
        self.original_negative_prompt_text: str = ""
        self.after_id: Optional[str] = None
        self.base_model_type_var = tk.StringVar(value=base_model_type)
        self.is_destroyed = False

        self._create_widgets()
        self._start_model_fetch()

        self.wait_window(self)

    def _start_model_fetch(self):
        """Starts fetching models in a background thread."""
        self.loading_model_label = ttk.Label(self.model_container, text="Loading models...")
        self.loading_model_label.pack()
        self.loading_lora_label = ttk.Label(self.lora_container, text="Loading LoRAs...")
        self.loading_lora_label.pack()
        self.ok_button.config(state=tk.DISABLED)

        def task():
            try:
                base_model_type = self.base_model_type_var.get()
                main_models = self.client.get_models(base_model=base_model_type, model_type='main')
                lora_models = self.client.get_models(base_model=base_model_type, model_type='lora')
                self.model_queue.put({'success': True, 'main': main_models, 'lora': lora_models})
            except Exception as e:
                self.model_queue.put({'success': False, 'error': e})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_model_queue)

    def _check_model_queue(self):
        """Checks the queue for model data and populates the widgets."""
        try:
            result = self.model_queue.get_nowait()
            if result['success']:
                self.models['main'] = result['main']
                self.models['lora'] = result['lora']
                self._populate_widgets()
                # Defer smart_geometry to allow widgets to render and calculate their required size first.
                self.after(10, lambda: self.smart_geometry(min_width=600, min_height=700, width_percent=0.4, height_percent=0.85))
            else:
                if self.is_destroyed: return
                # Show the error and close the dialog, as it's unusable.
                custom_dialogs.show_error(self, "Error", f"Could not fetch models from InvokeAI:\n{result['error']}")
                self.destroy()
        except queue.Empty:
            if not self.is_destroyed:
                self.after_id = self.after(100, self._check_model_queue)
        except tk.TclError:
            # This can happen if the window is destroyed while the after() job is pending.
            pass
    
    def destroy(self):
        self.is_destroyed = True
        super().destroy()

    def _do_populate_widgets(self):
        """The actual widget population logic. Called after the window is drawn."""
        self.loading_model_label.pack_forget()
        self.loading_lora_label.pack_forget()
        self.ok_button.config(state=tk.NORMAL)

        # Handle main models - store both name and key
        main_models = self.models.get('main', [])
        if main_models:
            self.model_data = {m['name']: m for m in main_models}
            main_model_names = sorted(list(self.model_data.keys()))
            
            initial_model_name = self.initial_params.get('model', {}).get('name')
            initial_model_names = {m['name'] for m in self.initial_params.get('models', [])}
            if initial_model_name:
                initial_model_names.add(initial_model_name)

            for model_name in main_model_names:
                var = tk.BooleanVar()
                if model_name in initial_model_names:
                    var.set(True)
                # If no initial models are specified, check the first one by default.
                elif not initial_model_names and model_name == main_model_names[0]:
                    var.set(True)
                
                var.trace_add("write", self._on_model_checkbox_change)
                
                cb = ttk.Checkbutton(self.model_container, text=model_name, variable=var)
                cb.bind("<MouseWheel>", self.model_scroll_view._on_mouse_wheel)
                
                if model_name in self.disabled_models:
                    cb.config(state=tk.DISABLED)
                    Tooltip(cb, "This model is already in the current generation batch.")

                cb.pack(anchor='w', fill='x', padx=5)
                self.model_vars[model_name] = var
                self.model_widgets[model_name] = cb
        else:
            ttk.Label(self.model_container, text="No SDXL models found").pack()

        # Handle LoRA models - store both name and key
        lora_models = self.models.get('lora', [])
        if self.processor.verbose:
            print(f"DEBUG: Found {len(lora_models)} LoRA models to populate.")

        if lora_models:
            # Create mapping from display name to model key
            self.lora_data = {m['name']: m for m in lora_models}
            initial_loras = self.initial_params.get('loras', [])
            # Create a map for easy lookup of initial weights
            initial_lora_map = {l['lora_object']['name']: l['weight'] for l in initial_loras}

            for lora_name in sorted(self.lora_data.keys(), key=str.lower):
                if self.processor.verbose:
                    print(f"DEBUG: Creating widget for LoRA: {lora_name}")
                lora_frame = ttk.Frame(self.lora_container)
                lora_frame.bind("<MouseWheel>", self.lora_scroll_view._on_mouse_wheel)
                self.lora_widgets[lora_name] = lora_frame
                var = tk.BooleanVar()
                if lora_name in initial_lora_map:
                    var.set(True)

                sanitized_name = _sanitize_for_widget_name(lora_name)
                cb = ttk.Checkbutton(lora_frame, text=lora_name, variable=var, name=f"cb_{sanitized_name}")
                cb.bind("<MouseWheel>", self.lora_scroll_view._on_mouse_wheel)
                cb.pack(side='left', fill='x', expand=True)
                self.lora_vars[lora_name] = var

                # Add weight spinbox
                weight_var = tk.StringVar(value=str(initial_lora_map.get(lora_name, 0.75))) # type: ignore
                spinbox = VerticalSpinbox(lora_frame, from_=-1.0, to=2.0, increment=0.05, textvariable=weight_var, width=4, name=f"spin_{sanitized_name}") # type: ignore
                spinbox.bind("<MouseWheel>", self.lora_scroll_view._on_mouse_wheel)
                spinbox.pack(side='right')
                self.lora_weight_vars[lora_name] = weight_var
        else:
            ttk.Label(self.lora_container, text="No LoRAs found").pack()
        
        if self.processor.verbose:
            # This will show the container's height *before* the UI has a chance to fully update it.
            # It will likely be small (e.g., 1).
            print(f"DEBUG: Immediately after packing, lora_container reqheight: {self.lora_container.winfo_reqheight()}")

        # --- FIX: Force an update to ensure the scrollable frame calculates its full size ---
        self.update_idletasks()

        if self.processor.verbose:
            # After update_idletasks(), this should show the full, correct height of all packed widgets.
            print(f"DEBUG: After update_idletasks, lora_container reqheight: {self.lora_container.winfo_reqheight()}")
        
        # Apply initial filter to show all LoRAs
        self._filter_loras()

        self._update_override_button_state()
        self._update_total_images_label()

    def _populate_widgets(self):
        """Schedules the actual widget population to run after the window is drawn."""
        self.after(50, self._do_populate_widgets)

    def _filter_models(self, *args):
        """Filters the model list based on the search term."""
        search_term = self.model_search_var.get().lower()
        for model_name, widget in self.model_widgets.items():
            if search_term in model_name.lower():
                widget.pack(anchor='w', fill='x', padx=5)
            else:
                widget.pack_forget()

    def _filter_loras(self, *args):
        """Filters the LoRA list based on the search term."""
        search_term = self.lora_search_var.get().lower()
        for lora_name, widget_frame in self.lora_widgets.items():
            if search_term in lora_name.lower():
                widget_frame.pack(fill='x', expand=True, pady=1, padx=5)
            else:
                widget_frame.pack_forget()

    def _create_widgets(self):
        # The main_frame is the top-level container within the dialog.
        # It should not be scrolled itself; only its internal lists are scrollable.
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- NEW: Base Model Type Selector ---
        base_model_frame = ttk.Frame(main_frame)
        base_model_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(base_model_frame, text="Base Model Type:").pack(side=tk.LEFT, padx=(0, 5))
        base_model_combo = ttk.Combobox(base_model_frame, textvariable=self.base_model_type_var, values=['sdxl', 'sd-1.5'], state="readonly")
        base_model_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        base_model_combo.bind("<<ComboboxSelected>>", self._on_base_model_change)

        # --- NEW: Paned window for side-by-side layout ---
        model_lora_pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        model_lora_pane.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Main Model (Left Pane)
        self.model_frame = ttk.LabelFrame(model_lora_pane, text="Main Model (SDXL)", padding=10)
        model_lora_pane.add(self.model_frame, weight=1)

        model_select_frame = ttk.Frame(self.model_frame)
        model_select_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(model_select_frame, text="Select All", command=self._select_all_models).pack(side=tk.LEFT)
        ttk.Button(model_select_frame, text="Select None", command=self._select_none_models).pack(side=tk.LEFT, padx=5)

        # Add search entry for models
        search_model_frame = ttk.Frame(self.model_frame)
        search_model_frame.pack(fill=tk.X, pady=(5, 5))
        ttk.Label(search_model_frame, text="Search:").pack(side=tk.LEFT)
        self.model_search_var.trace_add("write", self._filter_models)
        model_search_entry = ttk.Entry(search_model_frame, textvariable=self.model_search_var)
        model_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5,0))

        self.model_scroll_view = ScrollableFrame(self.model_frame)
        self.model_scroll_view.pack(fill=tk.BOTH, expand=True)
        self.model_container = self.model_scroll_view.scrollable_frame

        # LoRAs (Right Pane)
        self.lora_frame = ttk.LabelFrame(model_lora_pane, text="LoRAs", padding=10)
        model_lora_pane.add(self.lora_frame, weight=1)

        # Add search entry for LoRAs
        search_lora_frame = ttk.Frame(self.lora_frame)
        search_lora_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(search_lora_frame, text="Search:").pack(side=tk.LEFT)
        self.lora_search_var.trace_add("write", self._filter_loras)
        lora_search_entry = ttk.Entry(search_lora_frame, textvariable=self.lora_search_var)
        lora_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5,0))


        self.lora_scroll_view = ScrollableFrame(self.lora_frame)
        self.lora_scroll_view.pack(fill=tk.BOTH, expand=True)
        self.lora_container = self.lora_scroll_view.scrollable_frame

        # Negative Prompt
        neg_prompt_frame = ttk.LabelFrame(main_frame, text="Negative Prompt", padding=10)
        neg_prompt_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        neg_prompt_controls = ttk.Frame(neg_prompt_frame)
        neg_prompt_controls.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(neg_prompt_controls, text="Preset:").pack(side=tk.LEFT, padx=(0, 5))

        self.override_button = ttk.Button(neg_prompt_controls, text="Set Per-Model Overrides...", command=self._set_overrides, state=tk.DISABLED)
        self.override_button.pack(side=tk.RIGHT)

        self.lora_override_button = ttk.Button(neg_prompt_controls, text="Set Per-Model LoRAs...", command=self._set_lora_overrides, state=tk.DISABLED)
        self.lora_override_button.pack(side=tk.RIGHT, padx=(0, 5))



        self.negative_prompts = self.processor.get_available_negative_prompts()
        self.neg_prompt_names = [p['name'] for p in self.negative_prompts]
        self.neg_prompt_var = tk.StringVar()

        self.neg_prompt_names.insert(0, "Custom")
        self.neg_prompt_combo = ttk.Combobox(neg_prompt_controls, textvariable=self.neg_prompt_var, values=self.neg_prompt_names, state="readonly")
        self.neg_prompt_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.neg_prompt_combo.bind("<<ComboboxSelected>>", self._on_negative_prompt_select)

        self.neg_prompt_text = tk.Text(neg_prompt_frame, height=4, wrap=tk.WORD, undo=True, exportselection=False)
        self.neg_prompt_text.pack(fill=tk.BOTH, expand=True)
        initial_neg_prompt = self.initial_params.get('negative_prompt', '')
        self.neg_prompt_text.insert("1.0", initial_neg_prompt)
        TextContextMenu(self.neg_prompt_text)
        self.neg_prompt_text.bind("<KeyRelease>", self._on_neg_prompt_text_change)
        self._set_initial_negative_prompt_preset(initial_neg_prompt)

        # Other parameters
        params_frame = ttk.Frame(main_frame)
        params_frame.pack(fill=tk.X, pady=10)
        params_frame.columnconfigure(1, weight=1) # Seed entry
        params_frame.columnconfigure(3, weight=0) # Steps entry
        params_frame.columnconfigure(5, weight=0) # Num images entry

        # Row 0: Seed, Steps, Num Images
        ttk.Label(params_frame, text="Seed:").grid(row=0, column=0, sticky='w', pady=2)
        seed_frame = ttk.Frame(params_frame)
        seed_frame.grid(row=0, column=1, sticky='w', pady=2)
        self.seed_var = tk.StringVar(value=str(int(self.initial_params.get('seed', random.randint(0, 2**32 - 1)))))
        VerticalSpinbox(seed_frame, from_=0, to=2**32 - 1, increment=1, textvariable=self.seed_var, width=10).pack(side=tk.LEFT)
        ttk.Button(seed_frame, text="🎲", width=3, command=self._randomize_seed).pack(side=tk.LEFT, padx=(5,0))

        ttk.Label(params_frame, text="Steps:").grid(row=0, column=2, sticky='w', padx=(10, 5), pady=2)
        self.steps_var = tk.StringVar(value=str(self.initial_params.get('steps', 30)))
        VerticalSpinbox(params_frame, from_=1, to=150, increment=1, textvariable=self.steps_var, width=3).grid(row=0, column=3, sticky='w', pady=2)

        ttk.Label(params_frame, text="# Imgs:").grid(row=0, column=4, sticky='w', padx=(10, 5), pady=2)
        self.num_images_var = tk.StringVar(value=str(self.initial_params.get('num_images', 1)))
        self.num_images_var.trace_add("write", self._update_total_images_label)
        num_images_spinbox = VerticalSpinbox(params_frame, from_=1, to=100, increment=1, textvariable=self.num_images_var, width=3)
        num_images_spinbox.grid(row=0, column=5, sticky='w', pady=2)
        if self.is_editing:
            num_images_spinbox.entry.config(state=tk.DISABLED)
            num_images_spinbox.up_button.config(state=tk.DISABLED)
            num_images_spinbox.down_button.config(state=tk.DISABLED)

        # Row 1: CFG Scale and Rescale
        ttk.Label(params_frame, text="CFG Scale:").grid(row=1, column=0, sticky='w', pady=2)
        self.cfg_var = tk.StringVar(value=str(self.initial_params.get('cfg_scale', 7.5)))
        VerticalSpinbox(params_frame, from_=0.0, to=30.0, increment=0.5, textvariable=self.cfg_var, width=4).grid(row=1, column=1, sticky='w', pady=2)

        ttk.Label(params_frame, text="CFG Rescale:").grid(row=1, column=2, sticky='w', padx=(10, 5), pady=2)
        self.cfg_rescale_var = tk.StringVar(value=str(self.initial_params.get('cfg_rescale_multiplier', 0.0)))
        VerticalSpinbox(params_frame, from_=0.0, to=1.0, increment=0.05, textvariable=self.cfg_rescale_var, width=4).grid(row=1, column=3, sticky='w', pady=2)

        # Row 2: Scheduler
        ttk.Label(params_frame, text="Scheduler:").grid(row=2, column=0, sticky='w', pady=(5, 0))
        schedulers = ["euler", "dpmpp_2m", "dpmpp_2m_karras", "dpmpp_sde", "dpmpp_2m_sde", "dpmpp_2s_ancestral", "lms", "pndm"]
        self.scheduler_var = tk.StringVar(value=self.initial_params.get('scheduler', 'dpmpp_2m'))
        ttk.Combobox(params_frame, textvariable=self.scheduler_var, values=schedulers, state="readonly").grid(row=2, column=1, columnspan=5, sticky='ew', pady=(5,0))

        # New options frame
        options_frame = ttk.Frame(main_frame)
        options_frame.pack(fill=tk.X, pady=(15, 0), anchor='w')
        self.save_check = ttk.Checkbutton(options_frame, text="Save image to InvokeAI gallery", variable=self.save_to_gallery_var)
        self.save_check.pack(side=tk.LEFT)
        save_tooltip = Tooltip(self.save_check, "If checked, the generated image will be saved permanently in the InvokeAI gallery.\nIf unchecked, it will be temporary and eventually deleted by InvokeAI.")
        self.save_check.bind("<Enter>", save_tooltip.show)
        self.save_check.bind("<Leave>", save_tooltip.hide)

        # Buttons
        self.button_frame = ttk.Frame(main_frame)
        self.button_frame.pack(fill=tk.X, pady=(20, 0))
        
        # Configure grid for the button frame
        self.button_frame.columnconfigure(0, weight=1) # Spacer on the left
        
        self.total_images_label = ttk.Label(self.button_frame, textvariable=self.total_images_var, anchor='w')
        self.total_images_label.grid(row=0, column=0, sticky='w')

        self.ok_button = ttk.Button(self.button_frame, text="Generate", command=self._on_ok, style="Accent.TButton")
        self.ok_button.grid(row=0, column=2, sticky='e', padx=(5,0))
        
        self.cancel_button = ttk.Button(self.button_frame, text="Cancel", command=self._on_cancel)
        self.cancel_button.grid(row=0, column=1, sticky='e')

    def _on_base_model_change(self, event=None):
        """Handles when the user switches between SDXL and SD-1.5."""
        # Update frame labels
        base_type_display = self.base_model_type_var.get().upper().replace('-', '.')
        self.model_frame.config(text=f"Main Model ({base_type_display})")
        self.lora_frame.config(text=f"LoRAs ({base_type_display})")

        # Clear existing widgets and data
        for widget in self.model_container.winfo_children():
            widget.destroy()
        for widget in self.lora_container.winfo_children():
            widget.destroy()
        
        self.model_vars.clear()
        self.model_widgets.clear()
        self.lora_vars.clear()
        self.lora_widgets.clear()
        self.lora_weight_vars.clear()
        self.model_data.clear()
        self.lora_data.clear()
        self.lora_overrides.clear()
        self.neg_prompt_overrides.clear()
        
        # Restart the fetch process
        self._start_model_fetch()

    def _select_all_models(self):
        """Sets all enabled model checkboxes to True."""
        for model_name, var in self.model_vars.items():
            # Only select models that are not explicitly disabled (e.g., already in a batch)
            if model_name not in self.disabled_models:
                var.set(True)

    def _select_none_models(self):
        """Sets all model checkboxes to False."""
        # This can clear even disabled models if needed, which is generally safe.
        for var in self.model_vars.values():
            var.set(False)

    def _on_model_checkbox_change(self, *args):
        self._update_override_button_state()
        self._update_total_images_label()

    def _update_override_button_state(self):
        num_selected = sum(1 for var in self.model_vars.values() if var.get())
        self.override_button.config(state=tk.NORMAL if num_selected > 1 else tk.DISABLED)
        self.lora_override_button.config(state=tk.NORMAL if num_selected > 1 else tk.DISABLED)

    def _update_total_images_label(self, *args):
        """Calculates and updates the label showing the total number of images to be generated."""
        try:
            num_models = sum(1 for var in self.model_vars.values() if var.get())
            num_images_per_model = int(self.num_images_var.get())
            total_images = num_models * num_images_per_model
            
            if total_images > 0:
                plural_model = "model" if num_models == 1 else "models"
                plural_image = "image" if total_images == 1 else "images"
                self.total_images_var.set(f"Total: {total_images} {plural_image} ({num_models} {plural_model})")
            else:
                self.total_images_var.set("")
        except (ValueError, tk.TclError):
            # This can happen if the num_images_var is empty or contains non-numeric text
            self.total_images_var.set("")

    def _on_negative_prompt_select(self, event=None):
        selected_name = self.neg_prompt_var.get()
        if selected_name == "Custom":
            return

        selected_prompt_obj = next((p for p in self.negative_prompts if p['name'] == selected_name), None)
        if selected_prompt_obj:
            self.neg_prompt_text.delete("1.0", tk.END)
            self.neg_prompt_text.insert("1.0", selected_prompt_obj['prompt'])
            self.original_negative_prompt_text = selected_prompt_obj['prompt'].strip()

    def _on_neg_prompt_text_change(self, event=None):
        """Sets the combobox to 'Custom' if the text is manually edited."""
        current_text = self.neg_prompt_text.get("1.0", "end-1c").strip()
        
        matching_preset = next((p['name'] for p in self.negative_prompts if p['prompt'].strip() == current_text), None)
        
        if matching_preset:
            if self.neg_prompt_var.get() != matching_preset:
                self.neg_prompt_var.set(matching_preset)
        else:
            if self.neg_prompt_var.get() != "Custom":
                self.neg_prompt_var.set("Custom")

    def _set_initial_negative_prompt_preset(self, initial_text: str):
        """Sets the initial value of the combobox based on the initial text."""
        stripped_initial = initial_text.strip()
        matching_preset = next((p['name'] for p in self.negative_prompts if p['prompt'].strip() == stripped_initial), None)
        self.neg_prompt_var.set(matching_preset or "Custom")
        self.original_negative_prompt_text = stripped_initial

    def _set_overrides(self):
        """Opens the dialog to set per-model negative prompt overrides."""
        selected_model_names = [name for name, var in self.model_vars.items() if var.get()]
        if len(selected_model_names) < 2:
            custom_dialogs.show_info(self, "Not Applicable", "Select at least two models to set per-model overrides.")
            return
        
        dialog = custom_dialogs._PerModelNegativePromptDialog(self, self.processor, selected_model_names, self.neg_prompt_overrides)
        if dialog.result is not None:
            self.neg_prompt_overrides = dialog.result

    def _set_lora_overrides(self):
        """Opens the dialog to set per-model LoRA overrides."""
        selected_model_names = [name for name, var in self.model_vars.items() if var.get()]
        if len(selected_model_names) < 2:
            custom_dialogs.show_info(self, "Not Applicable", "Select at least two models to set per-model LoRA overrides.")
            return

        # Get the current global LoRA selection to pass as a default
        global_selected_lora_names = [name for name, var in self.lora_vars.items() if var.get()]
        global_loras = []
        if global_selected_lora_names and self.lora_data:
            for lora_name in global_selected_lora_names:
                lora_object = self.lora_data.get(lora_name)
                if lora_object:
                    try:
                        weight = float(self.lora_weight_vars[lora_name].get())
                    except (ValueError, KeyError):
                        weight = 0.75
                    global_loras.append({'lora_object': lora_object, 'weight': weight})

        dialog = custom_dialogs._PerModelLoraDialog(self, self.processor, selected_model_names, self.lora_data, global_loras, self.lora_overrides)
        if dialog.result is not None:
            self.lora_overrides = dialog.result

    def _save_new_negative_prompt(self, prompt_text: str):
        """Handles the dialog and logic for saving a new negative prompt preset."""
        filename = custom_dialogs.ask_string(self, "Save New Preset", "Enter a filename for the new negative prompt preset:", validator=custom_dialogs.is_valid_filename_component)
        if not filename:
            return
        
        # Refresh the list of presets before saving to avoid race conditions
        self.negative_prompts = self.processor.get_available_negative_prompts()
        self.neg_prompt_names = ["Custom"] + [p['name'] for p in self.negative_prompts]
        
        # Check if a preset with this name already exists
        if filename in [p['key'] for p in self.negative_prompts]:
            custom_dialogs.show_error(self, "Save Error", f"A negative prompt preset named '{filename}' already exists.")
            return False

        filename = filename.replace(' ', '_').lower()
        
        content_data = {
            "name": filename.replace('_', ' ').title(),
            "prompt": prompt_text
        }
        
        try:
            self.processor.create_system_prompt(filename, 'negative_prompt', content_data=content_data)
            custom_dialogs.show_info(self, "Preset Saved", f"Saved new preset '{filename}'.")
            # Manually update the combobox after saving
            self.negative_prompts = self.processor.get_available_negative_prompts()
            self.neg_prompt_names = ["Custom"] + [p['name'] for p in self.negative_prompts]
            self.neg_prompt_combo['values'] = self.neg_prompt_names
            self.neg_prompt_var.set(content_data["name"])
            self.original_negative_prompt_text = prompt_text
            return True
        except Exception as e:
            custom_dialogs.show_error(self, "Save Error", f"Could not save new preset:\n{e}")
            return False

    def _update_existing_negative_prompt(self, preset_name: str, new_prompt_text: str) -> bool:
        """Handles the logic for updating an existing negative prompt preset."""
        preset_obj = next((p for p in self.negative_prompts if p['name'] == preset_name), None)
        if not preset_obj: return
        
        filename = f"negative_prompts/{preset_obj['key']}.txt"
        try:
            self.processor.save_system_prompt_content(filename, new_prompt_text)
            custom_dialogs.show_info(self, "Preset Updated", f"Updated preset '{preset_name}'.")
            # Manually update the combobox after saving
            self.negative_prompts = self.processor.get_available_negative_prompts()
            self.neg_prompt_names = ["Custom"] + [p['name'] for p in self.negative_prompts]
            self.neg_prompt_combo['values'] = self.neg_prompt_names
            self.original_negative_prompt_text = new_prompt_text
            return True
        except Exception as e:
            custom_dialogs.show_error(self, "Update Error", f"Could not update preset:\n{e}")
            return False

    def _on_cancel(self, event=None):
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.is_destroyed = True
        super()._on_cancel(event)

    def _unload_ollama_models_for_vram(self) -> bool:
        """
        Checks for running Ollama models and asks the user to unload them to free VRAM.
        Returns True if it's okay to proceed, False if the user cancelled.
        """
        active_ollama_models = self.model_usage_manager.get_active_models()
        if not active_ollama_models:
            return True # No models to unload
        
        try:
            running_models = self.processor.ollama_client.get_running_models()
        except Exception as e:
            # If we can't check, it's safer to assume all active models are running and ask the user.
            print(f"Warning: Could not check for running Ollama models. Will ask to unload all active models. Error: {e}")
            running_models = [{'name': model_name} for model_name in active_ollama_models]

        # The `running_models` can be a list of strings (on success) or a list of dicts (on exception).
        # We need to handle both cases to get a set of names.
        if running_models and isinstance(running_models[0], dict):
            running_model_names = {m.get('name') for m in running_models}
        else:
            running_model_names = set(running_models)
        
        # Find the intersection between the models our app is using and the models actually loaded in VRAM.
        models_to_unload = [model for model in active_ollama_models if model in running_model_names]

        if models_to_unload:
            if custom_dialogs.ask_yes_no(
                self, "Free VRAM?", 
                f"This will temporarily unload the following Ollama model(s) to free VRAM for image generation:\n\n- {', '.join(models_to_unload)}\n\nThe model(s) will be reloaded automatically on their next use. Continue?"
            ):
                for model in models_to_unload:
                    thread = threading.Thread(target=self.processor.cleanup_model, args=(model,), daemon=True)
                    thread.start()
                return True
            return False # User cancelled
        return True # No models were actually loaded, so we can proceed.

    def _on_ok(self, event=None):
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.is_destroyed = True
        
        # --- Check for negative prompt changes before proceeding ---
        current_neg_prompt_text = self.neg_prompt_text.get("1.0", "end-1c").strip()
        selected_preset_name = self.neg_prompt_var.get()

        is_dirty = False
        if selected_preset_name == "Custom":
            # Only prompt to save if there's actually text to save.
            if current_neg_prompt_text:
                is_dirty = True
        else:
            # Check if the text for an existing preset has been modified.
            if current_neg_prompt_text != self.original_negative_prompt_text:
                is_dirty = True
        
        if is_dirty:
            if selected_preset_name == "Custom":
                if custom_dialogs.ask_yes_no(self, "Save Negative Prompt", "You have a custom negative prompt. Would you like to save it as a new preset?"):
                    if not self._save_new_negative_prompt(current_neg_prompt_text):
                        return # Abort if user cancels the save dialog
            else: # An existing preset was modified
                res = custom_dialogs.ask_yes_no_cancel(self, "Save Negative Prompt Changes", f"You have modified the '{selected_preset_name}' preset. Would you like to save the changes?\n\nYes: Update the existing preset.\nNo: Save as a new preset.")
                if res is True:
                    self._update_existing_negative_prompt(selected_preset_name, current_neg_prompt_text)
                elif res is False:
                    if not self._save_new_negative_prompt(current_neg_prompt_text):
                        return # Abort if user cancels the save dialog
        
        # --- VRAM Management ---
        # This is the correct place to check and unload models, right before generation starts.
        if not self._unload_ollama_models_for_vram():
            return # User cancelled the VRAM unload, so we abort the whole process.
        
        # Get selected models
        selected_model_names = [name for name, var in self.model_vars.items() if var.get()]
        default_neg_prompt = self.neg_prompt_text.get("1.0", "end-1c").strip()

        if not selected_model_names:
            custom_dialogs.show_error(self, "Invalid Input", "Please select at least one model.")
            self.result = None
            return
            
        # Get GLOBAL LoRA selection to use as a default
        global_selected_lora_names = [name for name, var in self.lora_vars.items() if var.get()]
        global_selected_loras = []
        if global_selected_lora_names and self.lora_data:
            for lora_name in global_selected_lora_names:
                lora_object = self.lora_data.get(lora_name)
                if lora_object:
                    try:
                        weight = float(self.lora_weight_vars[lora_name].get())
                    except (ValueError, KeyError):
                        weight = 0.75
                    global_selected_loras.append({'lora_object': lora_object, 'weight': weight})
            
        selected_models_with_prompts_and_loras = []
        for name in selected_model_names:
            if name in self.model_data:
                # Use per-model LoRAs if they exist, otherwise use the global selection
                loras_for_this_model = self.lora_overrides.get(name, global_selected_loras)
                
                selected_models_with_prompts_and_loras.append({
                    'model': self.model_data[name], 
                    'negative_prompt': self.neg_prompt_overrides.get(name, default_neg_prompt),
                    'loras': loras_for_this_model
                })

        if not selected_models_with_prompts_and_loras:
            custom_dialogs.show_error(self, "Invalid Input", "Could not find data for the selected model(s).")
            self.result = None
            return
        
        try:
            self.result = {
                "models": selected_models_with_prompts_and_loras,
                "seed": int(self.seed_var.get()),
                "steps": int(self.steps_var.get()),
                "cfg_scale": float(self.cfg_var.get()),
                "cfg_rescale_multiplier": float(self.cfg_rescale_var.get()),
                "scheduler": self.scheduler_var.get(),
                "num_images": int(self.num_images_var.get()),
                "save_to_gallery": self.save_to_gallery_var.get()
            }
        except (ValueError, TypeError) as e:
            custom_dialogs.show_error(self, "Invalid Input", f"Please check your parameters (Seed and Steps must be whole numbers):\n{e}")
            self.result = None
            return

        self.destroy()
