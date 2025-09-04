"""Manages the application's theme (light/dark)."""

import tkinter as tk
import sv_ttk
from core.config import config, save_settings, load_settings

class ThemeManager:
    """Manages the application's theme (light/dark)."""
    def __init__(self):
        settings = load_settings()
        self.current_theme = settings.get('theme', 'light') # Default to 'light' if not set
        self.theme_var = tk.StringVar(value=self.current_theme)

    def set_theme(self, theme_name: str):
        """Sets the theme and saves the setting."""
        if theme_name not in ["light", "dark"]:
            return
        
        sv_ttk.set_theme(theme_name)
        self.current_theme = theme_name
        
        settings = load_settings()
        settings['theme'] = theme_name
        save_settings(settings)

    def apply_theme(self, root: tk.Tk):
        """Applies the current theme to the root window."""
        sv_ttk.set_theme(self.current_theme)