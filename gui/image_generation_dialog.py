"""A dialog for selecting image generation options for InvokeAI."""

import tkinter as tk
from tkinter import ttk
import queue
import threading
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from .common import SmartWindowMixin
from . import custom_dialogs
from .common import TextContextMenu

if TYPE_CHECKING:
    from core.invokeai_client import InvokeAIClient

class ImageGenerationOptionsDialog(custom_dialogs._CustomDialog, SmartWindowMixin):
    """A dialog for selecting image generation options for InvokeAI."""
    def __init__(self, parent, invokeai_client: 'InvokeAIClient', initial_negative_prompt: str = ""):
        super().__init__(parent, "Image Generation Options")
        self.client = invokeai_client
        self.models: Dict[str, List[Dict[str, Any]]] = {}
        self.model_data: Dict[str, Dict[str, Any]] = {}  # name -> full model object
        self.lora_data: Dict[str, Dict[str, Any]] = {}   # name -> full lora object
        self.initial_negative_prompt = initial_negative_prompt
        self.model_queue = queue.Queue()
        self.after_id: Optional[str] = None

        self._create_widgets()
        self._start_model_fetch()

        self.smart_geometry(min_width=500, min_height=600)
        self.wait_window(self)

    def _start_model_fetch(self):
        """Starts fetching models in a background thread."""
        self.model_combo.set("Loading models...")
        self.model_combo.config(state=tk.DISABLED)
        self.lora_listbox.insert(tk.END, "Loading LoRAs...")
        self.lora_listbox.config(state=tk.DISABLED)
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
        self.model_combo.config(state="readonly")
        self.lora_listbox.config(state=tk.NORMAL)
        self.ok_button.config(state=tk.NORMAL)

        # Handle main models - store both name and key
        main_models = self.models.get('main', [])
        if main_models:
            # Create mapping from display name to model key
            self.model_data = {m['name']: m for m in main_models}
            main_model_names = sorted(list(self.model_data.keys()))
            
            self.model_combo['values'] = main_model_names
            self.model_var.set(main_model_names[0])
        else:
            self.model_var.set("No SDXL models found")
            self.model_combo.config(state=tk.DISABLED)

        # Handle LoRA models - store both name and key
        self.lora_listbox.delete(0, tk.END)
        lora_models = self.models.get('lora', [])
        if lora_models:
            # Create mapping from display name to model key
            self.lora_data = {m['name']: m for m in lora_models}
            for lora_name in sorted(self.lora_data.keys()):
                self.lora_listbox.insert(tk.END, lora_name)
        else:
            self.lora_listbox.insert(tk.END, "No LoRAs found")

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Main Model
        ttk.Label(main_frame, text="Main Model (SDXL):").pack(anchor='w')
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(main_frame, textvariable=self.model_var, state="readonly")
        self.model_combo.pack(fill=tk.X, pady=(0, 10))

        # LoRAs
        lora_frame = ttk.LabelFrame(main_frame, text="LoRAs (Ctrl+Click to select multiple)", padding=10)
        lora_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        lora_scrollbar = ttk.Scrollbar(lora_frame, orient=tk.VERTICAL)
        self.lora_listbox = tk.Listbox(lora_frame, selectmode=tk.EXTENDED, yscrollcommand=lora_scrollbar.set, height=10)
        lora_scrollbar.config(command=self.lora_listbox.yview)
        lora_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.lora_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Negative Prompt
        neg_prompt_frame = ttk.LabelFrame(main_frame, text="Negative Prompt", padding=10)
        neg_prompt_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        self.neg_prompt_text = tk.Text(neg_prompt_frame, height=4, wrap=tk.WORD, undo=True, exportselection=False)
        self.neg_prompt_text.pack(fill=tk.BOTH, expand=True)
        self.neg_prompt_text.insert("1.0", self.initial_negative_prompt)
        TextContextMenu(self.neg_prompt_text)

        # Other parameters
        params_frame = ttk.Frame(main_frame)
        params_frame.pack(fill=tk.X, pady=10)
        params_frame.columnconfigure(1, weight=1)
        params_frame.columnconfigure(3, weight=1)

        ttk.Label(params_frame, text="Steps:").grid(row=0, column=0, sticky='w')
        self.steps_var = tk.StringVar(value="30")
        ttk.Entry(params_frame, textvariable=self.steps_var, width=8).grid(row=0, column=1, sticky='w')

        ttk.Label(params_frame, text="CFG Scale:").grid(row=0, column=2, sticky='w', padx=(10, 0))
        self.cfg_var = tk.StringVar(value="7.5")
        ttk.Entry(params_frame, textvariable=self.cfg_var, width=8).grid(row=0, column=3, sticky='w')

        ttk.Label(params_frame, text="Scheduler:").grid(row=1, column=0, sticky='w', pady=(5, 0))
        schedulers = ["euler", "dpmpp_2m", "dpmpp_2m_karras", "dpmpp_sde", "dpmpp_2m_sde", "dpmpp_2s_ancestral", "lms", "pndm"]
        self.scheduler_var = tk.StringVar(value="dpmpp_2m")
        ttk.Combobox(params_frame, textvariable=self.scheduler_var, values=schedulers, state="readonly").grid(row=1, column=1, columnspan=3, sticky='ew', pady=(5,0))

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        self.ok_button = ttk.Button(button_frame, text="Generate", command=self._on_ok, style="Accent.TButton")
        self.ok_button.pack(side=tk.RIGHT, padx=(5, 0))
        self.cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        self.cancel_button.pack(side=tk.RIGHT)

    def _on_cancel(self, event=None):
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        super()._on_cancel(event)

    def _on_ok(self, event=None):
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        
        # Get selected model
        selected_model_name = self.model_var.get()
        selected_model_object = self.model_data.get(selected_model_name)
        
        if not selected_model_object:
            custom_dialogs.show_error(self, "Invalid Input", "Please select a valid model.")
            self.result = None
            return
        
        # Get selected LoRAs
        selected_lora_indices = self.lora_listbox.curselection()
        selected_loras = []
        if selected_lora_indices and self.lora_data:
            lora_names = [self.lora_listbox.get(i) for i in selected_lora_indices]
            for lora_name in lora_names:
                lora_object = self.lora_data.get(lora_name)
                if lora_object:
                    # LoRA needs a weight. Let's default to 0.75 for now.
                    selected_loras.append({
                        'lora_object': lora_object,
                        'weight': 0.75
                    })
        
        try:
            self.result = {
                "model": selected_model_object,
                "loras": selected_loras,
                "steps": int(self.steps_var.get()),
                "cfg_scale": float(self.cfg_var.get()),
                "scheduler": self.scheduler_var.get(),
                "negative_prompt": self.neg_prompt_text.get("1.0", "end-1c").strip()
            }
        except (ValueError, TypeError) as e:
            custom_dialogs.show_error(self, "Invalid Input", f"Please check your parameters:\n{e}")
            self.result = None
            return

        self.destroy()