"""A window for managing application-wide settings like directory paths."""

import tkinter as tk
from tkinter import ttk, filedialog
from typing import TYPE_CHECKING

from core.config import config, update_and_save_paths
from .common import SmartWindowMixin, Tooltip
from . import custom_dialogs

if TYPE_CHECKING:
    from .gui_app import GUIApp

class SettingsWindow(tk.Toplevel, SmartWindowMixin):
    """A dialog for editing application settings."""

    def __init__(self, parent: 'GUIApp', on_save_callback: callable):
        super().__init__(parent)
        self.title("Settings")
        self.transient(parent)
        self.grab_set()

        self.on_save_callback = on_save_callback
        self.setting_vars = {
            "template_base_dir": tk.StringVar(value=config.TEMPLATE_BASE_DIR),
            "wildcard_dir": tk.StringVar(value=config.WILDCARD_DIR),
            "history_dir": tk.StringVar(value=config.HISTORY_DIR),
            "system_prompt_base_dir": tk.StringVar(value=config.SYSTEM_PROMPT_BASE_DIR),
            "ollama_base_url": tk.StringVar(value=config.OLLAMA_BASE_URL),
        }

        self._create_widgets()
        self.smart_geometry(min_width=600, min_height=250)

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Path Entries ---
        path_group = ttk.LabelFrame(main_frame, text="Directory Paths", padding=10)
        path_group.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 15))
        path_group.columnconfigure(1, weight=1)

        path_labels = {
            "template_base_dir": "Templates Path:",
            "wildcard_dir": "Wildcards Path:",
            "history_dir": "History Path:",
            "system_prompt_base_dir": "System Prompts Path:",
        }

        for i, (key, label_text) in enumerate(path_labels.items()):
            ttk.Label(path_group, text=label_text).grid(row=i, column=0, sticky='w', padx=(0, 10), pady=5)
            entry = ttk.Entry(path_group, textvariable=self.setting_vars[key], width=60)
            entry.grid(row=i, column=1, sticky='ew', pady=5)
            browse_button = ttk.Button(path_group, text="Browse...", command=lambda k=key: self._browse_for_directory(k))
            browse_button.grid(row=i, column=2, sticky='w', padx=(5, 0), pady=5)

        # --- Connection Settings ---
        conn_group = ttk.LabelFrame(main_frame, text="Connection Settings", padding=10)
        conn_group.grid(row=1, column=0, columnspan=3, sticky='ew')
        conn_group.columnconfigure(1, weight=1)

        ttk.Label(conn_group, text="Ollama Server URL:").grid(row=0, column=0, sticky='w', padx=(0, 10), pady=5)
        ollama_entry = ttk.Entry(conn_group, textvariable=self.setting_vars["ollama_base_url"], width=60)
        ollama_entry.grid(row=0, column=1, sticky='ew', pady=5)
        Tooltip(ollama_entry, "The base URL for your Ollama server (e.g., http://192.168.1.100:11434)")

        # --- Buttons ---
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, columnspan=3, sticky='e', pady=(20, 0))

        save_button = ttk.Button(button_frame, text="Save and Reload", command=self._on_save, style="Accent.TButton")
        save_button.pack(side=tk.RIGHT, padx=(5, 0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.destroy)
        cancel_button.pack(side=tk.RIGHT)

    def _browse_for_directory(self, key: str):
        """Opens a directory browser and updates the corresponding variable."""
        current_path = self.setting_vars[key].get()
        new_path = filedialog.askdirectory(
            parent=self,
            title=f"Select Directory for {key.replace('_', ' ').title()}",
            initialdir=current_path
        )
        if new_path:
            self.setting_vars[key].set(new_path)

    def _on_save(self):
        """Validates, saves the new settings, and triggers the callback."""
        new_settings = {key: var.get().strip() for key, var in self.setting_vars.items()}
        
        # --- Test Ollama connection if URL changed ---
        new_url = new_settings.get("ollama_base_url", "")
        if new_url and new_url != config.OLLAMA_BASE_URL:
            try:
                from core.ollama_client import OllamaClient
                test_client = OllamaClient(base_url=new_url)
                test_client.list_models() # This will raise an exception on failure
                custom_dialogs.show_info(self, "Success", f"Successfully connected to Ollama server at:\n{new_url}")
            except Exception as e:
                custom_dialogs.show_error(self, "Connection Failed", f"Could not connect to Ollama server at:\n{new_url}\n\nError: {e}\n\nSettings not saved.")
                return # Abort save
        
        # Update the config file and the live config object
        update_and_save_paths(new_settings)

        # Trigger the main app to reload its resources
        self.on_save_callback()

        self.destroy()