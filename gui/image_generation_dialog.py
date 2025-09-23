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

    def _toggle_all_models(self):
        """Toggles the selection state of all visible models."""
        if not self.model_vars:
            return

        # Only consider visible models based on the search filter
        visible_models = [name for name, widget in self.model_widgets.items() if widget.winfo_ismapped()]
        if not visible_models:
            return

        # Determine the new state based on the visible models
        any_unchecked = any(not self.model_vars[name].get() for name in visible_models)
        new_state = any_unchecked

        for model_name in visible_models:
            self.model_vars[model_name].set(new_state)

    def __init__(self, parent, processor: 'PromptProcessor', initial_params: Optional[Dict[str, Any]] = None, is_editing: bool = False, is_adding_more: bool = False, disabled_models: Optional[List[str]] = None, base_model_type: str = 'sdxl'):
        # The parent could be the main app or another Toplevel window.
        # We need to find the root GUIApp instance for context.
        if hasattr(parent, 'parent_app'):
            self.parent_app = parent.parent_app
        else:
            self.parent_app = parent
        super().__init__(parent, "Image Generation Options")
        self.processor = processor
        self.model_usage_manager: 'ModelUsageManager' = parent.model_usage_manager
        self.client = processor.invokeai_client
        self.models: Dict[str, List[Dict[str, Any]]] = {}
        self.schedulers: List[str] = []
        self.model_data: Dict[str, Dict[str, Any]] = {}  # name -> full model object
        self.lora_data: Dict[str, Dict[str, Any]] = {}   # name -> full lora object
        self.is_editing = is_editing
        self.disabled_models = disabled_models or []
        self.is_adding_more = is_adding_more
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
        self.avg_gen_times: Dict[str, float] = {}
        self.original_negative_prompt_text: str = ""
        self.after_id: Optional[str] = None
        self.lora_tooltip: Optional[Tooltip] = None
        self.lora_tooltip_after_id: Optional[str] = None
        self.last_hovered_lora: Optional[str] = None
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
                schedulers = self.client.get_schedulers()
                model_stats = self.processor.get_model_stats()
                avg_times = {model: data['avg_duration'] for model, data in model_stats.items()}
                self.model_queue.put({'success': True, 'main': main_models, 'lora': lora_models, 'avg_times': avg_times, 'schedulers': schedulers})
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
                self.schedulers = result.get('schedulers', [])
                self.avg_gen_times = result.get('avg_times', {})
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

        # Handle main models
        self.model_container.columnconfigure(0, weight=1)
        main_models = self.models.get('main', [])
        if main_models:
            self.model_data = {m['name']: m for m in main_models}
            main_model_names = sorted(list(self.model_data.keys()), key=str.lower)

            initial_model_name = self.initial_params.get('model', {}).get('name')
            initial_model_names = {m.get('name') for m in self.initial_params.get('models', []) if m.get('name')}
            if initial_model_name:
                initial_model_names.add(initial_model_name)

            if self.is_adding_more:
                initial_model_names.clear()

            for i, model_name in enumerate(main_model_names):
                var = tk.BooleanVar()
                if model_name in initial_model_names:
                    var.set(True)
                # No default selection. User must explicitly choose.
                
                var.trace_add("write", self._on_model_checkbox_change)
                
                cb = ttk.Checkbutton(self.model_container, text=model_name, variable=var)
                cb.bind("<MouseWheel>", self.model_scroll_view._on_mouse_wheel)

                avg_time = self.avg_gen_times.get(model_name)
                tooltip_text = f"Average generation time: {avg_time:.2f}s" if avg_time else "No generation time data available."
                Tooltip(cb, tooltip_text)
                
                if model_name in self.disabled_models:
                    cb.config(state=tk.DISABLED)
                    Tooltip(cb, "This model is already in the current generation batch.")

                cb.grid(row=i, column=0, sticky='ew', padx=5)
                self.model_vars[model_name] = var
                self.model_widgets[model_name] = cb
        else:
            ttk.Label(self.model_container, text="No SDXL models found").pack()

        # Handle LoRA models - store both name and key
        self.lora_container.columnconfigure(0, weight=1)
        lora_models = self.models.get('lora', [])
        if self.processor.verbose:
            print(f"DEBUG: Found {len(lora_models)} LoRA models to populate.")

        if lora_models:
            # Create mapping from display name to model key
            self.lora_data = {m['name']: m for m in lora_models}
            initial_loras = self.initial_params.get('loras', [])
            # Create a map for easy lookup of initial weights
            initial_lora_map = {l['lora_object']['name']: l['weight'] for l in initial_loras}

            for i, lora_name in enumerate(sorted(self.lora_data.keys(), key=str.lower)):
                if self.processor.verbose:
                    print(f"DEBUG: Creating widget for LoRA: {lora_name}")
                lora_frame = ttk.Frame(self.lora_container)
                # Bind events to the frame for tooltip functionality
                lora_frame.bind("<Motion>", lambda e, ln=lora_name: self._schedule_lora_tooltip(e, ln))
                lora_frame.bind("<Leave>", self._hide_lora_tooltip)
                lora_frame.bind("<MouseWheel>", self.lora_scroll_view._on_mouse_wheel)
                lora_frame.grid(row=i, column=0, sticky='ew', pady=1, padx=5)
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
        
        # --- NEW: Update scheduler combobox with fetched values ---
        self.scheduler_combo['values'] = self.schedulers
        # Ensure the default value is valid.
        default_scheduler = self.initial_params.get('scheduler', 'dpmpp_2m')
        if self.schedulers and default_scheduler not in self.schedulers:
            # If the old default isn't available, pick the first one from the new list
            self.scheduler_var.set(self.schedulers[0])
        else:
            self.scheduler_var.set(default_scheduler)

        # Apply initial filter to show all LoRAs
        self._filter_loras()

        self._update_override_button_state()        
        self._update_total_images_label()        
    
    def _populate_widgets(self):
        """Schedules the actual widget population to run after the window is drawn."""
        self.after(50, self._do_populate_widgets)

    def _filter_models(self, *args):
        """Filters the model list based on the search term."""
        self.model_scroll_view.canvas.yview_moveto(0)
        search_term = self.model_search_var.get().lower()
        for i, (model_name, widget) in enumerate(self.model_widgets.items()):
            if search_term in model_name.lower():
                widget.grid(row=i, column=0, sticky='ew', padx=5)
            else:
                widget.grid_remove()

    def _filter_loras(self, *args):
        """Filters the LoRA list based on the search term."""
        self.lora_scroll_view.canvas.yview_moveto(0)
        search_term = self.lora_search_var.get().lower()
        for i, (lora_name, widget_frame) in enumerate(self.lora_widgets.items()):
            if search_term in lora_name.lower():
                widget_frame.grid(row=i, column=0, sticky='ew', pady=1, padx=5)
            else:
                widget_frame.grid_remove()

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
        ttk.Button(model_select_frame, text="Toggle All", command=self._toggle_all_models).pack(side=tk.LEFT)

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
        # Initialize the tooltip, attached to the container that holds the LoRAs
        self.lora_tooltip = Tooltip(self.lora_container, "")
        
        # Negative Prompt
        neg_prompt_frame = ttk.LabelFrame(main_frame, text="Negative Prompt", padding=10)
        neg_prompt_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        neg_prompt_controls = ttk.Frame(neg_prompt_frame)
        neg_prompt_controls.pack(fill=tk.X, pady=(0, 5))
        neg_prompt_controls.columnconfigure(1, weight=1) # Let the combobox expand
        
        ttk.Label(neg_prompt_controls, text="Preset:").grid(row=0, column=0, sticky='w', padx=(0, 5))
        
        self.negative_prompts = self.processor.get_available_negative_prompts()
        self.neg_prompt_names = [p['name'] for p in self.negative_prompts]
        self.neg_prompt_var = tk.StringVar()
        self.neg_prompt_names.insert(0, "Custom")
        self.neg_prompt_combo = ttk.Combobox(neg_prompt_controls, textvariable=self.neg_prompt_var, values=self.neg_prompt_names, state="readonly")
        self.neg_prompt_combo.grid(row=0, column=1, sticky='ew')
        self.neg_prompt_combo.bind("<<ComboboxSelected>>", self._on_negative_prompt_select)

        self.save_preset_button = ttk.Button(neg_prompt_controls, text="Save...", command=self._save_negative_prompt_preset, state=tk.DISABLED)
        self.save_preset_button.grid(row=0, column=2, sticky='w', padx=(5, 0))

        override_controls = ttk.Frame(neg_prompt_frame)
        override_controls.pack(fill=tk.X, pady=(5, 0))
        self.override_button = ttk.Button(override_controls, text="Set Per-Model Negative Prompts...", command=self._set_overrides, state=tk.DISABLED)
        self.override_button.pack(side=tk.RIGHT)
        self.lora_override_button = ttk.Button(override_controls, text="Set Per-Model LoRAs...", command=self._set_lora_overrides, state=tk.DISABLED)
        self.lora_override_button.pack(side=tk.RIGHT, padx=(0, 5))

        self.neg_prompt_text = tk.Text(neg_prompt_frame, height=4, wrap=tk.WORD, undo=True, exportselection=False)
        self.neg_prompt_text.pack(fill=tk.BOTH, expand=True)
        
        # If a negative prompt is passed, use it. Otherwise, get the user's default.
        initial_neg_prompt = self.initial_params.get('negative_prompt')
        # If no negative prompt is provided, or if an empty one is provided,
        # fall back to the user's configured default.
        if not initial_neg_prompt:
            initial_neg_prompt = self.processor.get_default_negative_prompt_text()

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
        seed_frame.grid(row=0, column=1, sticky='ew', pady=2)
        self.seed_var = tk.StringVar(value=str(int(self.initial_params.get('seed', random.randint(0, 2**32 - 1)))))
        VerticalSpinbox(seed_frame, from_=0, to=2**32 - 1, increment=1, textvariable=self.seed_var, width=10).pack(side=tk.LEFT)

        # --- NEW: Always show the randomize button, but conditionally show the "New Seed on Regen" button ---
        self.random_seed_button = ttk.Button(seed_frame, text="🎲", width=3, command=self._randomize_seed)
        self.random_seed_button.pack(side=tk.LEFT, padx=(5,0))
        Tooltip(self.random_seed_button, "Set a new random seed.")

        if self.is_editing:
            self.random_seed_button.pack(side=tk.LEFT, padx=(5,0))
            
        ttk.Label(params_frame, text="Steps:").grid(row=0, column=2, sticky='w', padx=(10, 5), pady=2)
        self.steps_var = tk.StringVar(value=str(self.initial_params.get('steps', 30)))
        VerticalSpinbox(params_frame, from_=1, to=150, increment=1, textvariable=self.steps_var, width=3).grid(row=0, column=3, sticky='w', pady=2)

        ttk.Label(params_frame, text="# Imgs:").grid(row=0, column=4, sticky='w', padx=(10, 5), pady=2)
        self.num_images_var = tk.StringVar(value=str(self.initial_params.get('num_images', 1)))
        self.num_images_var.trace_add("write", self._update_total_images_label)
        num_images_spinbox = VerticalSpinbox(params_frame, from_=1, to=100, increment=1, textvariable=self.num_images_var, width=3)
        num_images_spinbox.grid(row=0, column=5, sticky='w', pady=2)
        if self.is_editing and not self.is_adding_more:
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
        self.scheduler_var = tk.StringVar(value=self.initial_params.get('scheduler', 'dpmpp_2m'))
        self.scheduler_combo = ttk.Combobox(params_frame, textvariable=self.scheduler_var, values=[], state="readonly")
        self.scheduler_combo.grid(row=2, column=1, columnspan=5, sticky='ew', pady=(5,0))

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

    def _schedule_lora_tooltip(self, event, lora_name: str):
        """Schedules a tooltip to appear over a LoRA after a delay."""
        if self.lora_tooltip_after_id:
            self.after_cancel(self.lora_tooltip_after_id)

        if lora_name != self.last_hovered_lora:
            if self.lora_tooltip: self.lora_tooltip.hide()

        self.last_hovered_lora = lora_name
        self.lora_tooltip_after_id = self.after(500, lambda: self._display_lora_tooltip(lora_name, event))

    def _display_lora_tooltip(self, lora_name: str, event):
        """Fetches prefix content and displays the tooltip."""
        if not self.lora_tooltip: return

        prefix_data = self.processor.lora_prefixes.get(lora_name, {})
        positive_prefix = prefix_data.get("positive_prefix", "").strip()
        negative_prefix = prefix_data.get("negative_prefix", "").strip()

        tooltip_parts = []
        if positive_prefix:
            tooltip_parts.append(f"Positive Prefix:\n- {positive_prefix}")
        if negative_prefix:
            tooltip_parts.append(f"Negative Prefix:\n- {negative_prefix}")

        if tooltip_parts:
            self.lora_tooltip.text = "\n\n".join(tooltip_parts)
            self.lora_tooltip.show(event)

    def _hide_lora_tooltip(self, event=None):
        """Hides the LoRA tooltip and cancels any scheduled appearance."""
        self.last_hovered_lora = None
        if self.lora_tooltip_after_id:
            self.after_cancel(self.lora_tooltip_after_id)
            self.lora_tooltip_after_id = None
        if self.lora_tooltip:
            self.lora_tooltip.hide(event)

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

    def _on_model_checkbox_change(self, *args):
        self._update_override_button_state()
        self._update_total_images_label()

        selected_models = [name for name, var in self.model_vars.items() if var.get()]
        
        # If exactly one model is selected, try to set its default scheduler.
        if len(selected_models) == 1:
            model_name = selected_models[0]

            # --- FIX: Do not override the scheduler if we are editing an existing generation ---
            if self.is_editing:
                return

            model_prefix_data = self.processor.model_prefixes.get(model_name, {})
            default_scheduler = model_prefix_data.get('scheduler')
            
            # Check if the scheduler is valid for the current context
            if default_scheduler and default_scheduler in self.schedulers:
                self.scheduler_var.set(default_scheduler)
        # If no models are selected, or multiple are selected, we don't change the scheduler automatically.
        # The user can set it manually. The last-selected model's scheduler will stick, which is fine.

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
                self.save_preset_button.config(state=tk.DISABLED)
                self.neg_prompt_var.set(matching_preset)
        else:
            if self.neg_prompt_var.get() != "Custom":
                self.neg_prompt_var.set("Custom")
            # Enable save button only if there is text to save
            self.save_preset_button.config(state=tk.NORMAL if current_text else tk.DISABLED)

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

    def _save_negative_prompt_preset(self):
        """Handles the logic for saving a new or updated negative prompt preset."""
        current_neg_prompt_text = self.neg_prompt_text.get("1.0", "end-1c").strip()
        if not current_neg_prompt_text:
            return

        selected_preset_name = self.neg_prompt_var.get()

        if selected_preset_name == "Custom":
            if self._save_new_negative_prompt(current_neg_prompt_text):
                self.save_preset_button.config(state=tk.DISABLED)
        else: # An existing preset was modified
            res = custom_dialogs.ask_yes_no_cancel(self, "Save Negative Prompt Changes", f"You have modified the '{selected_preset_name}' preset. Would you like to save the changes?\n\nYes: Update the existing preset.\nNo: Save as a new preset.")
            if res is True:
                if self._update_existing_negative_prompt(selected_preset_name, current_neg_prompt_text):
                    self.save_preset_button.config(state=tk.DISABLED)
            elif res is False:
                if self._save_new_negative_prompt(current_neg_prompt_text):
                    self.save_preset_button.config(state=tk.DISABLED)
            # If res is None (Cancel), do nothing.

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

    def _on_ok(self, event=None):
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.is_destroyed = True
        
        # --- VRAM Management ---
        # This is the correct place to check and unload models, right before generation starts.
        if not self.parent_app._unload_ollama_models_for_vram():
            self._on_cancel() # This will set result to None and destroy the window
            return

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
