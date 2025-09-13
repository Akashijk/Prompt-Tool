"""A window for managing automatic prompt prefixes for specific InvokeAI LoRAs."""

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

class LoraPrefixEditorWindow(tk.Toplevel, SmartWindowMixin):
    """A window for managing automatic prompt prefixes for specific InvokeAI LoRAs."""
    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor'):
        super().__init__(parent)
        self.title("InvokeAI LoRA Prefixes")
        self.transient(parent)
        self.grab_set()

        self.processor = processor
        self.parent_app = parent
        self.lora_prefixes = self.processor.load_lora_prefixes()
        self.fetch_queue = queue.Queue()
        self.after_id: Optional[str] = None

        self._create_widgets()
        self.smart_geometry(min_width=600, min_height=400)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._fetch_loras()

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # --- LoRA Selection ---
        lora_pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        lora_pane.pack(fill=tk.BOTH, expand=True)

        tree_frame = ttk.LabelFrame(lora_pane, text="InvokeAI LoRAs", padding=5)
        lora_pane.add(tree_frame, weight=1)
        self.lora_tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        self.lora_tree.pack(fill=tk.BOTH, expand=True)
        self.lora_tree.bind("<<TreeviewSelect>>", self._on_lora_select)

        editor_frame = ttk.Frame(lora_pane)
        editor_frame.rowconfigure(1, weight=1)
        editor_frame.rowconfigure(3, weight=1)
        editor_frame.columnconfigure(0, weight=1)
        lora_pane.add(editor_frame, weight=2)

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

    def _fetch_loras(self):
        """Fetches InvokeAI LoRAs in a background thread."""
        if not self.processor.is_invokeai_connected():
            custom_dialogs.show_error(self, "Not Connected", "InvokeAI is not configured. Please set the URL in Tools > Settings.")
            return

        self.lora_tree.insert("", "end", text="Loading LoRAs...", iid="loading")

        def task():
            try:
                sdxl_loras = self.processor.get_invokeai_loras(base_model='sdxl')
                sd1x_loras = self.processor.get_invokeai_loras(base_model='sd-1.5')
                self.fetch_queue.put({'success': True, 'sdxl': sdxl_loras, 'sd1x': sd1x_loras})
            except Exception as e:
                self.fetch_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_fetch_queue)

    def _check_fetch_queue(self):
        """Checks the queue for fetched LoRAs and updates the UI."""
        try:
            result = self.fetch_queue.get_nowait()

            # Clear existing tree
            for i in self.lora_tree.get_children():
                self.lora_tree.delete(i)

            if result['success']:
                sdxl_loras = sorted([m['name'] for m in result.get('sdxl', [])])
                sd1x_loras = sorted([m['name'] for m in result.get('sd1x', [])])

                if sdxl_loras:
                    sdxl_id = self.lora_tree.insert("", "end", text="SDXL LoRAs", open=True)
                    for lora_name in sdxl_loras:
                        self.lora_tree.insert(sdxl_id, "end", text=lora_name)
                
                if sd1x_loras:
                    sd1x_id = self.lora_tree.insert("", "end", text="SD-1.5 LoRAs", open=True)
                    for lora_name in sd1x_loras:
                        self.lora_tree.insert(sd1x_id, "end", text=lora_name)
            else:
                custom_dialogs.show_error(self, "Fetch Error", f"Could not fetch LoRAs from InvokeAI:\n{result['error']}")
        except queue.Empty:
            self.after_id = self.after(100, self._check_fetch_queue)

    def _on_lora_select(self, event=None):
        """Loads the prefixes for the selected LoRA into the text widgets."""
        selection = self.lora_tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        if not self.lora_tree.parent(item_id):
            return
        
        lora_name = self.lora_tree.item(item_id, "text")

        prefixes = self.lora_prefixes.get(lora_name, {})
        self.positive_text.delete("1.0", tk.END)
        self.positive_text.insert("1.0", prefixes.get("positive_prefix", ""))
        self.negative_text.delete("1.0", tk.END)
        self.negative_text.insert("1.0", prefixes.get("negative_prefix", ""))

    def _save_prefixes(self):
        """Saves the current prefixes for the selected LoRA and writes to file."""
        selection = self.lora_tree.selection()
        if not selection:
            custom_dialogs.show_warning(self, "No LoRA Selected", "Please select a LoRA to save prefixes for.")
            return
        
        item_id = selection[0]
        if not self.lora_tree.parent(item_id):
            custom_dialogs.show_warning(self, "Invalid Selection", "Please select a LoRA, not a category.")
            return

        positive_prefix = self.positive_text.get("1.0", "end-1c").strip()
        negative_prefix = self.negative_text.get("1.0", "end-1c").strip()

        lora_name = self.lora_tree.item(item_id, "text")
        if not positive_prefix and not negative_prefix:
            if lora_name in self.lora_prefixes:
                del self.lora_prefixes[lora_name]
        else:
            self.lora_prefixes[lora_name] = {
                "positive_prefix": positive_prefix,
                "negative_prefix": negative_prefix
            }

        try:
            self.processor.save_lora_prefixes(self.lora_prefixes)
            custom_dialogs.show_info(self, "Saved", f"Prefixes for '{lora_name}' have been saved.")
        except Exception as e:
            custom_dialogs.show_error(self, "Save Error", f"Could not save LoRA prefixes:\n{e}")