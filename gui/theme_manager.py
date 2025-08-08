"""Manages the application's visual theme (light/dark mode)."""

import json
import os
import sv_ttk
from tkinter import Tk

# The config file will be stored in the user's home directory for persistence
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".prompt_tool_v2")
CONFIG_FILE = os.path.join(CONFIG_DIR, "theme.json")

class ThemeManager:
    """Handles loading, applying, and saving the application theme."""

    def __init__(self):
        self.current_theme = self._load_theme()

    def _load_theme(self) -> str:
        """Loads the theme preference from the config file."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    theme = config.get("theme", "light")
                    if theme in ["light", "dark"]:
                        return theme
            except (json.JSONDecodeError, IOError):
                pass
        return "light"  # Default theme

    def _save_theme(self):
        """Saves the current theme preference to the config file."""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_FILE, 'w') as f:
                json.dump({"theme": self.current_theme}, f)
        except IOError as e:
            print(f"Warning: Could not save theme preference: {e}")

    def set_theme(self, theme_name: str):
        """Sets the application's theme and saves the preference."""
        if theme_name not in ["light", "dark"]:
            return
        
        sv_ttk.set_theme(theme_name)
        self.current_theme = theme_name
        self._save_theme()

    def apply_theme(self, root: Tk):
        """Applies the currently loaded theme to the application root."""
        sv_ttk.set_theme(self.current_theme)