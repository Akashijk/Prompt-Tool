"""A window for managing automatic prompt prefixes for specific InvokeAI assets."""

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

class AssetPrefixEditorWindow(tk.Toplevel, SmartWindowMixin):
    """A window for managing automatic prompt prefixes for InvokeAI models and LoRAs."""
    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor'):
        super().__init__(parent)
        self.title("InvokeAI Asset Prefixes")
        self.transient(parent)
        self.grab_set()

        self.processor = processor
        self.parent_app = parent
        self.model_prefixes = self.processor.load_model_prefixes()
        self.lora_prefixes = self.processor.load_lora_prefixes()
        self.fetch_queue = queue.Queue()
        self.after_id: Optional[str] = None

        # --- Data Storage ---
        self.model_asset_data: Dict[str, List[str]] = {'sdxl': [], 'sd1x': []}
        self.lora_asset_data: Dict[str, List[str]] = {'sdxl': [], 'sd1x': []}
        self.search_vars: Dict[str, tk.StringVar] = {}

        # --- UI Widget Storage ---
        self.notebook: Optional[ttk.Notebook] = None
        self.trees: Dict[str, ttk.Treeview] = {}
        self.positive_texts: Dict[str, tk.Text] = {}
        self.negative_texts: Dict[str, tk.Text] = {}

        self._create_widgets()
        self.smart_geometry(min_width=700, min_height=500)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._fetch_assets()

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # --- Models Tab ---
        models_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(models_tab, text="Main Models")
        self._create_asset_tab(models_tab, 'model')

        # --- LoRAs Tab ---
        loras_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(loras_tab, text="LoRAs")
        self._create_asset_tab(loras_tab, 'lora')

        # --- Buttons ---
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        self.save_button = ttk.Button(button_frame, text="Save", command=self._save_prefixes, style="Accent.TButton")
        self.save_button.pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _create_asset_tab(self, parent_frame: ttk.Frame, asset_type: str):
        """Creates the content for a single tab (models or LoRAs)."""
        pane = ttk.PanedWindow(parent_frame, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)

        # Left side: Treeview
        tree_frame = ttk.LabelFrame(pane, text=f"InvokeAI {asset_type.capitalize()}s", padding=5)
        pane.add(tree_frame, weight=2) # Give more space to the tree
        
        # --- Search Bar ---
        search_frame = ttk.Frame(tree_frame)
        search_frame.pack(fill=tk.X, pady=(0, 5))
        search_var = tk.StringVar()
        search_var.trace_add("write", lambda *args, at=asset_type: self._repopulate_tree(at))
        self.search_vars[asset_type] = search_var
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        ttk.Entry(search_frame, textvariable=search_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5,0))
        
        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse", yscrollcommand=tree_scroll_y.set)
        tree_scroll_y.config(command=tree.yview)
        
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tree.bind("<<TreeviewSelect>>", lambda e, at=asset_type: self._on_asset_select(e, at))
        self.trees[asset_type] = tree

        # Right side: Editors
        editor_frame = ttk.Frame(pane)
        editor_frame.rowconfigure(1, weight=1) # Positive text
        editor_frame.rowconfigure(3, weight=1) # Negative text
        editor_frame.columnconfigure(0, weight=1) # Text widgets
        pane.add(editor_frame, weight=1) # Give less space to the editors

        ttk.Label(editor_frame, text="Positive Prompt Prefix:", anchor='w').grid(row=0, column=0, sticky='ew', pady=(0, 5))
        
        # Positive text with scrollbar
        pos_text_frame = ttk.Frame(editor_frame)
        pos_text_frame.grid(row=1, column=0, sticky='nsew', pady=(0, 10))
        pos_text_frame.rowconfigure(0, weight=1)
        pos_text_frame.columnconfigure(0, weight=1)
        pos_scroll = ttk.Scrollbar(pos_text_frame, orient=tk.VERTICAL)
        positive_text = tk.Text(pos_text_frame, height=4, wrap=tk.WORD, undo=True, exportselection=False, yscrollcommand=pos_scroll.set)
        pos_scroll.config(command=positive_text.yview)
        pos_scroll.grid(row=0, column=1, sticky='ns')
        positive_text.grid(row=0, column=0, sticky='nsew')
        TextContextMenu(positive_text)
        self.positive_texts[asset_type] = positive_text

        ttk.Label(editor_frame, text="Negative Prompt Prefix:", anchor='w').grid(row=2, column=0, sticky='ew', pady=(0, 5))
        
        # Negative text with scrollbar
        neg_text_frame = ttk.Frame(editor_frame)
        neg_text_frame.grid(row=3, column=0, sticky='nsew', pady=(0, 10))
        neg_text_frame.rowconfigure(0, weight=1)
        neg_text_frame.columnconfigure(0, weight=1)
        neg_scroll = ttk.Scrollbar(neg_text_frame, orient=tk.VERTICAL)
        negative_text = tk.Text(neg_text_frame, height=4, wrap=tk.WORD, undo=True, exportselection=False, yscrollcommand=neg_scroll.set)
        neg_scroll.config(command=negative_text.yview)
        neg_scroll.grid(row=0, column=1, sticky='ns')
        negative_text.grid(row=0, column=0, sticky='nsew')
        TextContextMenu(negative_text)
        self.negative_texts[asset_type] = negative_text

    def _fetch_assets(self):
        """Fetches both models and LoRAs in a background thread."""
        if not self.processor.is_invokeai_connected():
            custom_dialogs.show_error(self, "Not Connected", "InvokeAI is not configured. Please set the URL in Tools > Settings.")
            return

        self.trees['model'].insert("", "end", text="Loading models...", iid="loading")
        self.trees['lora'].insert("", "end", text="Loading LoRAs...", iid="loading")

        def task():
            try:
                assets = {
                    'model': {
                        'sdxl': self.processor.get_invokeai_models(base_model='sdxl'),
                        'sd1x': self.processor.get_invokeai_models(base_model='sd-1.5')
                    },
                    'lora': {
                        'sdxl': self.processor.get_invokeai_loras(base_model='sdxl'),
                        'sd1x': self.processor.get_invokeai_loras(base_model='sd-1.5')
                    }
                }
                self.fetch_queue.put({'success': True, 'assets': assets})
            except Exception as e:
                self.fetch_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_fetch_queue)

    def _check_fetch_queue(self):
        """Checks the queue for fetched assets and populates the UI."""
        try:
            result = self.fetch_queue.get_nowait()
            for asset_type, tree in self.trees.items():
                for i in tree.get_children(): tree.delete(i)

            if result['success']:
                # Store the full lists of assets
                self.model_asset_data['sdxl'] = sorted([m['name'] for m in result['assets']['model'].get('sdxl', [])], key=str.lower)
                self.model_asset_data['sd1x'] = sorted([m['name'] for m in result['assets']['model'].get('sd1x', [])], key=str.lower)
                self.lora_asset_data['sdxl'] = sorted([m['name'] for m in result['assets']['lora'].get('sdxl', [])], key=str.lower)
                self.lora_asset_data['sd1x'] = sorted([m['name'] for m in result['assets']['lora'].get('sd1x', [])], key=str.lower)

                # Initial population of both trees
                self._repopulate_tree('model')
                self._repopulate_tree('lora')
            else:
                custom_dialogs.show_error(self, "Fetch Error", f"Could not fetch assets from InvokeAI:\n{result['error']}")
        except queue.Empty:
            self.after_id = self.after(100, self._check_fetch_queue)

    def _repopulate_tree(self, asset_type: str):
        """Filters and repopulates a treeview based on the search term."""
        tree = self.trees.get(asset_type)
        search_var = self.search_vars.get(asset_type)
        if not tree or not search_var: return

        search_term = search_var.get().lower()
        asset_data = self.model_asset_data if asset_type == 'model' else self.lora_asset_data

        for i in tree.get_children(): tree.delete(i)

        sdxl_assets = [name for name in asset_data.get('sdxl', []) if search_term in name.lower()]
        if sdxl_assets:
            sdxl_id = tree.insert("", "end", text=f"SDXL {asset_type.capitalize()}s", open=True)
            for name in sdxl_assets: tree.insert(sdxl_id, "end", text=name)

        sd1x_assets = [name for name in asset_data.get('sd1x', []) if search_term in name.lower()]
        if sd1x_assets:
            sd1x_id = tree.insert("", "end", text=f"SD-1.5 {asset_type.capitalize()}s", open=True)
            for name in sd1x_assets: tree.insert(sd1x_id, "end", text=name)

    def _on_asset_select(self, event, asset_type: str):
        """Loads the prefixes for the selected asset into the text widgets."""
        tree = self.trees[asset_type]
        selection = tree.selection()
        if not selection or not tree.parent(selection[0]): return

        asset_name = tree.item(selection[0], "text")
        prefix_map = self.model_prefixes if asset_type == 'model' else self.lora_prefixes
        prefixes = prefix_map.get(asset_name, {})
        
        self.positive_texts[asset_type].delete("1.0", tk.END)
        self.positive_texts[asset_type].insert("1.0", prefixes.get("positive_prefix", ""))
        self.negative_texts[asset_type].delete("1.0", tk.END)
        self.negative_texts[asset_type].insert("1.0", prefixes.get("negative_prefix", ""))

    def _save_prefixes(self):
        """Saves the current prefixes for the selected asset and writes to file."""
        if not self.notebook: return
        current_tab_index = self.notebook.index(self.notebook.select())
        asset_type = 'model' if current_tab_index == 0 else 'lora'

        tree = self.trees[asset_type]
        selection = tree.selection()
        if not selection or not tree.parent(selection[0]):
            custom_dialogs.show_warning(self, "No Asset Selected", f"Please select a {asset_type} to save prefixes for.")
            return

        asset_name = tree.item(selection[0], "text")
        positive_prefix = self.positive_texts[asset_type].get("1.0", "end-1c").strip()
        negative_prefix = self.negative_texts[asset_type].get("1.0", "end-1c").strip()

        prefix_map = self.model_prefixes if asset_type == 'model' else self.lora_prefixes
        save_func = self.processor.save_model_prefixes if asset_type == 'model' else self.processor.save_lora_prefixes

        if not positive_prefix and not negative_prefix:
            if asset_name in prefix_map: del prefix_map[asset_name]
        else:
            prefix_map[asset_name] = {"positive_prefix": positive_prefix, "negative_prefix": negative_prefix}

        try:
            save_func(prefix_map)
            custom_dialogs.show_info(self, "Saved", f"Prefixes for '{asset_name}' have been saved.")
        except Exception as e:
            custom_dialogs.show_error(self, "Save Error", f"Could not save {asset_type} prefixes:\n{e}")