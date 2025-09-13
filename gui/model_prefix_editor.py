"""A window for managing automatic prompt prefixes for specific InvokeAI models."""

import tkinter as tk
from tkinter import ttk
import threading
import queue
from typing import Optional, Dict, TYPE_CHECKING, List

from . import custom_dialogs
from .common import SmartWindowMixin, TextContextMenu

if TYPE_CHECKING:
    from .gui_app import GUIApp
    from core.prompt_processor import PromptProcessor

class ModelPrefixEditorWindow(tk.Toplevel, SmartWindowMixin):
    """A window for managing automatic prompt prefixes for specific InvokeAI models."""
    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor'):
        super().__init__(parent)
        self.title("InvokeAI Model Prefixes")
        self.transient(parent)
        self.grab_set()

        self.processor = processor
        self.parent_app = parent
        self.model_prefixes = self.processor.load_model_prefixes()
        self.fetch_queue = queue.Queue()
        self.after_id: Optional[str] = None

        self._create_widgets()
        self.smart_geometry(min_width=600, min_height=400)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._fetch_models()

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # --- Model Selection ---
        model_pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        model_pane.pack(fill=tk.BOTH, expand=True)

        # Left side: Treeview
        tree_frame = ttk.LabelFrame(model_pane, text="InvokeAI Models", padding=5)
        model_pane.add(tree_frame, weight=1)
        self.model_tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        self.model_tree.pack(fill=tk.BOTH, expand=True)
        self.model_tree.bind("<<TreeviewSelect>>", self._on_model_select)

        # Right side: Editors
        editor_frame = ttk.Frame(model_pane)
        editor_frame.rowconfigure(1, weight=1)
        editor_frame.rowconfigure(3, weight=1)
        editor_frame.columnconfigure(0, weight=1)
        model_pane.add(editor_frame, weight=2)

        # --- Positive Prefix ---
        ttk.Label(editor_frame, text="Positive Prompt Prefix:", anchor='w').grid(row=0, column=0, sticky='ew', pady=(0, 5))
        self.positive_text = tk.Text(editor_frame, height=4, wrap=tk.WORD, undo=True, exportselection=False)
        self.positive_text.grid(row=1, column=0, sticky='nsew', pady=(0, 10))
        TextContextMenu(self.positive_text)

        # --- Negative Prefix ---
        ttk.Label(editor_frame, text="Negative Prompt Prefix:", anchor='w').grid(row=2, column=0, sticky='ew', pady=(0, 5))
        self.negative_text = tk.Text(editor_frame, height=4, wrap=tk.WORD, undo=True, exportselection=False)
        self.negative_text.grid(row=3, column=0, sticky='nsew', pady=(0, 10))
        TextContextMenu(self.negative_text)

        # --- Buttons ---
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10)

        self.save_button = ttk.Button(button_frame, text="Save", command=self._save_prefixes, style="Accent.TButton")
        self.save_button.pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _fetch_models(self):
        """Fetches InvokeAI models in a background thread."""
        if not self.processor.is_invokeai_connected():
            custom_dialogs.show_error(self, "Not Connected", "InvokeAI is not configured. Please set the URL in Tools > Settings.")
            return

        self.model_tree.insert("", "end", text="Loading models...", iid="loading")

        def task():
            try:
                sdxl_models = self.processor.get_invokeai_models(base_model='sdxl')
                sd1x_models = self.processor.get_invokeai_models(base_model='sd-1.5')
                self.fetch_queue.put({'success': True, 'sdxl': sdxl_models, 'sd1x': sd1x_models})
            except Exception as e:
                self.fetch_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_fetch_queue)

    def _check_fetch_queue(self):
        """Checks the queue for fetched models and updates the UI."""
        try:
            result = self.fetch_queue.get_nowait()

            # Clear existing tree
            for i in self.model_tree.get_children():
                self.model_tree.delete(i)

            if result['success']:
                sdxl_models = sorted([m['name'] for m in result.get('sdxl', [])])
                sd1x_models = sorted([m['name'] for m in result.get('sd1x', [])])

                if sdxl_models:
                    sdxl_id = self.model_tree.insert("", "end", text="SDXL Models", open=True)
                    for model_name in sdxl_models:
                        self.model_tree.insert(sdxl_id, "end", text=model_name)
                
                if sd1x_models:
                    sd1x_id = self.model_tree.insert("", "end", text="SD-1.5 Models", open=True)
                    for model_name in sd1x_models:
                        self.model_tree.insert(sd1x_id, "end", text=model_name)
            else:
                custom_dialogs.show_error(self, "Fetch Error", f"Could not fetch models from InvokeAI:\n{result['error']}")
        except queue.Empty:
            self.after_id = self.after(100, self._check_fetch_queue)

    def _on_model_select(self, event=None):
        """Loads the prefixes for the selected model into the text widgets."""
        selection = self.model_tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        # Ignore clicks on category headers
        if not self.model_tree.parent(item_id):
            return
        model_name = self.model_tree.item(item_id, "text")

        prefixes = self.model_prefixes.get(model_name, {})
        self.positive_text.delete("1.0", tk.END)
        self.positive_text.insert("1.0", prefixes.get("positive_prefix", ""))
        self.negative_text.delete("1.0", tk.END)
        self.negative_text.insert("1.0", prefixes.get("negative_prefix", ""))

    def _save_prefixes(self):
        """Saves the current prefixes for the selected model and writes to file."""
        selection = self.model_tree.selection()
        if not selection:
            custom_dialogs.show_warning(self, "No Model Selected", "Please select a model to save prefixes for.")
            return

        item_id = selection[0]
        if not self.model_tree.parent(item_id):
            custom_dialogs.show_warning(self, "Invalid Selection", "Please select a model, not a category.")
            return

        positive_prefix = self.positive_text.get("1.0", "end-1c").strip()
        negative_prefix = self.negative_text.get("1.0", "end-1c").strip()

        # If both are empty, remove the entry for this model. Otherwise, update or create it.
        model_name = self.model_tree.item(item_id, "text")
        if not positive_prefix and not negative_prefix:
            if model_name in self.model_prefixes:
                del self.model_prefixes[model_name]
        else:
            self.model_prefixes[model_name] = {
                "positive_prefix": positive_prefix,
                "negative_prefix": negative_prefix
            }

        try:
            self.processor.save_model_prefixes(self.model_prefixes)
            custom_dialogs.show_info(self, "Saved", f"Prefixes for '{model_name}' have been saved.")
        except Exception as e:
            custom_dialogs.show_error(self, "Save Error", f"Could not save model prefixes:\n{e}")