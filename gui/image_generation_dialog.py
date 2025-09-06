"""A dialog for selecting image generation options for InvokeAI."""

import tkinter as tk
from tkinter import ttk
import queue
import sys
import random
import threading
import tkinter.font as tkfont
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from .common import SmartWindowMixin, Tooltip
from . import custom_dialogs
from .common import TextContextMenu

if TYPE_CHECKING:
    from core.invokeai_client import InvokeAIClient

class VerticalSpinbox(ttk.Frame):
    """A custom spinbox with vertical buttons for a more compact look."""
    def __init__(self, parent, from_=0.0, to=100.0, increment=1.0, width=5, textvariable=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.from_ = from_
        self.to = to
        self.increment = increment
        self.textvariable = textvariable if textvariable else tk.StringVar()

        # Determine the format string based on the increment
        if isinstance(self.increment, int) or self.increment == 1.0:
            self.format_spec = "{:.0f}"
        elif self.increment < 0.1:
            self.format_spec = "{:.2f}"
        else:
            self.format_spec = "{:.1f}"

        # Entry widget
        self.entry = ttk.Entry(self, textvariable=self.textvariable, width=width, justify='center')
        self.entry.pack(side=tk.LEFT, fill=tk.Y)

        # Frame for buttons
        button_frame = ttk.Frame(self)
        button_frame.pack(side=tk.LEFT, fill=tk.Y)

        # --- Smart Sizing Logic ---
        # Get the default font size to make the buttons proportionally smaller.
        default_font = tkfont.nametofont("TkDefaultFont")
        default_size = default_font.cget("size")
        button_font_size = max(6, default_size - 3) # Make it smaller but not tiny.

        # Create a unique style name to avoid conflicts if this widget is used multiple times.
        style_name = f"{id(self)}.Small.Toolbutton"
        style = ttk.Style()
        style.configure(style_name, font=('Helvetica', button_font_size), padding=(2, 0, 2, 0))

        # Up and Down buttons
        self.up_button = ttk.Button(button_frame, text="⏶", command=self._increment, width=1, style=style_name)
        self.up_button.pack(side=tk.TOP, fill=tk.Y, expand=True, pady=(0,1))
        self.down_button = ttk.Button(button_frame, text="⏷", command=self._decrement, width=1, style=style_name)
        self.down_button.pack(side=tk.TOP, fill=tk.Y, expand=True)

        # Bind mouse wheel for increment/decrement
        for widget in [self.entry, self.up_button, self.down_button, button_frame, self]:
            widget.bind("<MouseWheel>", self._on_mouse_wheel) # For Windows and macOS
            widget.bind("<Button-4>", self._on_mouse_wheel)   # For Linux scroll up
            widget.bind("<Button-5>", self._on_mouse_wheel)   # For Linux scroll down

    def _on_mouse_wheel(self, event):
        """Handles mouse wheel scrolling to increment/decrement the value."""
        # Differentiate between platforms for scroll direction
        if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
            self._increment()
        elif event.num == 5 or (hasattr(event, 'delta') and event.delta < 0):
            self._decrement()

    def _increment(self):
        try:
            current_value = float(self.textvariable.get())
            new_value = min(self.to, current_value + self.increment)
            self.textvariable.set(self.format_spec.format(new_value))
        except (ValueError, tk.TclError):
            self.textvariable.set(self.format_spec.format(self.from_))

    def _decrement(self):
        try:
            current_value = float(self.textvariable.get())
            new_value = max(self.from_, current_value - self.increment)
            self.textvariable.set(self.format_spec.format(new_value))
        except (ValueError, tk.TclError):
            self.textvariable.set(self.format_spec.format(self.from_))

class ImageGenerationOptionsDialog(custom_dialogs._CustomDialog, SmartWindowMixin):
    """A dialog for selecting image generation options for InvokeAI."""
    def _randomize_seed(self):
        self.seed_var.set(str(random.randint(0, 2**32 - 1)))

    def _on_model_mouse_wheel(self, event):
        """Handles mouse wheel scrolling for the model list."""
        delta = -1 * (event.delta if sys.platform == 'darwin' else event.delta // 120)
        self.model_canvas.yview_scroll(delta, "units")

    def _on_lora_mouse_wheel(self, event):
        """Handles mouse wheel scrolling for the LoRA list."""
        delta = -1 * (event.delta if sys.platform == 'darwin' else event.delta // 120)
        self.lora_canvas.yview_scroll(delta, "units")

    def __init__(self, parent, invokeai_client: 'InvokeAIClient', initial_params: Optional[Dict[str, Any]] = None, is_editing: bool = False):
        super().__init__(parent, "Image Generation Options")
        self.client = invokeai_client
        self.models: Dict[str, List[Dict[str, Any]]] = {}
        self.model_data: Dict[str, Dict[str, Any]] = {}  # name -> full model object
        self.lora_data: Dict[str, Dict[str, Any]] = {}   # name -> full lora object
        self.is_editing = is_editing
        self.initial_params = initial_params or {}
        self.model_vars: Dict[str, tk.BooleanVar] = {}
        self.lora_vars: Dict[str, tk.BooleanVar] = {}
        self.save_to_gallery_var = tk.BooleanVar(value=False)
        self.model_queue = queue.Queue()
        self.after_id: Optional[str] = None

        self._create_widgets()
        self._start_model_fetch()

        self.smart_geometry(min_width=500, min_height=600)
        self.wait_window(self)

    def _reflow_buttons(self, event=None):
        if not hasattr(self, 'button_frame') or not self.button_frame.winfo_exists():
            return

        self.ok_button.grid_forget()
        self.cancel_button.grid_forget()

        width = self.button_frame.winfo_width()
        req_w = self.ok_button.winfo_reqwidth() + self.cancel_button.winfo_reqwidth() + 20

        if width < req_w:
            # Vertical
            self.button_frame.columnconfigure(0, weight=1, minsize=0)
            self.button_frame.columnconfigure(1, weight=0)
            self.button_frame.columnconfigure(2, weight=0)
            self.ok_button.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 5))
            self.cancel_button.grid(row=1, column=0, columnspan=3, sticky='ew')
        else:
            # Horizontal
            self.button_frame.columnconfigure(0, weight=1)
            self.button_frame.columnconfigure(1, weight=0)
            self.button_frame.columnconfigure(2, weight=0)
            self.cancel_button.grid(row=0, column=1, sticky='e')
            self.ok_button.grid(row=0, column=2, sticky='e', padx=(5, 0))

    def _start_model_fetch(self):
        """Starts fetching models in a background thread."""
        self.loading_model_label = ttk.Label(self.model_container, text="Loading models...")
        self.loading_model_label.pack()
        self.loading_lora_label = ttk.Label(self.lora_container, text="Loading LoRAs...")
        self.loading_lora_label.pack()
        self.ok_button.config(state=tk.DISABLED)

        def task():
            try:
                main_models = self.client.get_models(base_model='sdxl', model_type='main')
                lora_models = self.client.get_models(base_model='sdxl', model_type='lora')
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
            else:
                # Show the error and close the dialog, as it's unusable.
                custom_dialogs.show_error(self, "Error", f"Could not fetch models from InvokeAI:\n{result['error']}")
                self.destroy()
        except queue.Empty:
            self.after_id = self.after(100, self._check_model_queue)
        except tk.TclError:
            # This can happen if the window is destroyed while the after() job is pending.
            pass

    def _populate_widgets(self):
        """Populates the widgets with fetched model data."""
        self.loading_model_label.pack_forget()
        self.loading_lora_label.pack_forget()
        self.ok_button.config(state=tk.NORMAL)

        # Handle main models - store both name and key
        main_models = self.models.get('main', [])
        if main_models:
            # Create mapping from display name to model key
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
                
                cb = ttk.Checkbutton(self.model_container, text=model_name, variable=var)
                cb.pack(anchor='w', fill='x')
                cb.bind("<MouseWheel>", self._on_model_mouse_wheel)
                self.model_vars[model_name] = var
        else:
            ttk.Label(self.model_container, text="No SDXL models found").pack()

        # Handle LoRA models - store both name and key
        lora_models = self.models.get('lora', [])
        if lora_models:
            # Create mapping from display name to model key
            self.lora_data = {m['name']: m for m in lora_models}
            initial_loras = self.initial_params.get('loras', [])
            initial_lora_names = {l['lora_object']['name'] for l in initial_loras}

            for lora_name in sorted(self.lora_data.keys()):
                var = tk.BooleanVar()
                if lora_name in initial_lora_names:
                    var.set(True)
                
                cb = ttk.Checkbutton(self.lora_container, text=lora_name, variable=var)
                cb.pack(anchor='w', fill='x')
                cb.bind("<MouseWheel>", self._on_lora_mouse_wheel)
                self.lora_vars[lora_name] = var
        else:
            ttk.Label(self.lora_container, text="No LoRAs found").pack()

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Main Model
        model_frame = ttk.LabelFrame(main_frame, text="Main Model (SDXL)", padding=10)
        model_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.model_canvas = tk.Canvas(model_frame, borderwidth=0, highlightthickness=0)
        model_scrollbar = ttk.Scrollbar(model_frame, orient="vertical", command=self.model_canvas.yview)
        self.model_container = ttk.Frame(self.model_canvas)
        self.model_canvas.configure(yscrollcommand=model_scrollbar.set)
        model_scrollbar.pack(side="right", fill="y")
        self.model_canvas.pack(side="left", fill="both", expand=True)
        model_canvas_window = self.model_canvas.create_window((0, 0), window=self.model_container, anchor="nw")

        def on_model_frame_configure(event):
            self.model_canvas.configure(scrollregion=self.model_canvas.bbox("all"))
        def on_model_canvas_configure(event):
            self.model_canvas.itemconfig(model_canvas_window, width=event.width)

        self.model_container.bind("<Configure>", on_model_frame_configure)
        self.model_canvas.bind("<Configure>", on_model_canvas_configure)

        # Add mouse wheel scrolling
        self.model_canvas.bind("<MouseWheel>", self._on_model_mouse_wheel)
        self.model_container.bind("<MouseWheel>", self._on_model_mouse_wheel)

        # LoRAs
        lora_frame = ttk.LabelFrame(main_frame, text="LoRAs", padding=10)
        lora_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        self.lora_canvas = tk.Canvas(lora_frame, borderwidth=0, highlightthickness=0)
        lora_scrollbar = ttk.Scrollbar(lora_frame, orient="vertical", command=self.lora_canvas.yview)
        self.lora_container = ttk.Frame(self.lora_canvas)
        self.lora_canvas.configure(yscrollcommand=lora_scrollbar.set)
        lora_scrollbar.pack(side="right", fill="y")
        self.lora_canvas.pack(side="left", fill="both", expand=True)
        lora_canvas_window = self.lora_canvas.create_window((0, 0), window=self.lora_container, anchor="nw")

        def on_lora_frame_configure(event):
            self.lora_canvas.configure(scrollregion=self.lora_canvas.bbox("all"))
        def on_lora_canvas_configure(event):
            self.lora_canvas.itemconfig(lora_canvas_window, width=event.width)

        self.lora_container.bind("<Configure>", on_lora_frame_configure)
        self.lora_canvas.bind("<Configure>", on_lora_canvas_configure)

        # Add mouse wheel scrolling
        self.lora_canvas.bind("<MouseWheel>", self._on_lora_mouse_wheel)
        self.lora_container.bind("<MouseWheel>", self._on_lora_mouse_wheel)

        # Negative Prompt
        neg_prompt_frame = ttk.LabelFrame(main_frame, text="Negative Prompt", padding=10)
        neg_prompt_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        self.neg_prompt_text = tk.Text(neg_prompt_frame, height=4, wrap=tk.WORD, undo=True, exportselection=False)
        self.neg_prompt_text.pack(fill=tk.BOTH, expand=True)
        self.neg_prompt_text.insert("1.0", self.initial_params.get('negative_prompt', ''))
        TextContextMenu(self.neg_prompt_text)

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
        self.ok_button = ttk.Button(self.button_frame, text="Generate", command=self._on_ok, style="Accent.TButton")
        self.cancel_button = ttk.Button(self.button_frame, text="Cancel", command=self._on_cancel)
        
        self.button_frame.bind("<Configure>", self._reflow_buttons)
        self.after(10, self._reflow_buttons)

    def _on_cancel(self, event=None):
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        super()._on_cancel(event)

    def _on_ok(self, event=None):
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        
        # Get selected models
        selected_model_names = [name for name, var in self.model_vars.items() if var.get()]
        if not selected_model_names:
            custom_dialogs.show_error(self, "Invalid Input", "Please select at least one model.")
            self.result = None
            return
            
        selected_model_objects = [self.model_data[name] for name in selected_model_names if name in self.model_data]

        if not selected_model_objects:
            custom_dialogs.show_error(self, "Invalid Input", "Could not find data for selected models.")
            self.result = None
            return
        
        # Get selected LoRAs
        selected_lora_names = [name for name, var in self.lora_vars.items() if var.get()]
        selected_loras = []
        if selected_lora_names and self.lora_data:
            for lora_name in selected_lora_names:
                lora_object = self.lora_data.get(lora_name)
                if lora_object:
                    # LoRA needs a weight. Let's default to 0.75 for now.
                    selected_loras.append({
                        'lora_object': lora_object,
                        'weight': 0.75
                    })
        
        try:
            self.result = {
                "models": selected_model_objects,
                "loras": selected_loras,
                "seed": int(self.seed_var.get()),
                "steps": int(self.steps_var.get()),
                "cfg_scale": float(self.cfg_var.get()),
                "cfg_rescale_multiplier": float(self.cfg_rescale_var.get()),
                "scheduler": self.scheduler_var.get(),
                "num_images": int(self.num_images_var.get()),
                "save_to_gallery": self.save_to_gallery_var.get(),
                "negative_prompt": self.neg_prompt_text.get("1.0", "end-1c").strip()
            }
        except (ValueError, TypeError) as e:
            custom_dialogs.show_error(self, "Invalid Input", f"Please check your parameters (Seed and Steps must be whole numbers):\n{e}")
            self.result = None
            return

        self.destroy()