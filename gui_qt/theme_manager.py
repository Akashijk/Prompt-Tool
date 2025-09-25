"""A manager to handle loading and applying Qt stylesheets for theming."""

import os
from PySide6.QtWidgets import QApplication
from core.config import config

class ThemeManager:
    """Manages loading and applying application-wide themes from QSS files."""

    def __init__(self):
        self.themes_dir = os.path.join(os.path.dirname(__file__), 'themes')
        self.light_stylesheet = self._load_stylesheet('light.qss')
        self.dark_stylesheet = self._load_stylesheet('dark.qss')

    def _load_stylesheet(self, filename: str) -> str:
        """Loads a QSS file from the themes directory."""
        path = os.path.join(self.themes_dir, filename)
        if not os.path.exists(path):
            print(f"Warning: Stylesheet not found at {path}")
            return ""
        try:
            with open(path, 'r') as f:
                return f.read()
        except Exception as e:
            print(f"Error loading stylesheet {filename}: {e}")
            return ""

    def apply_theme(self, theme_name: str):
        """Applies the specified theme to the entire application."""
        app = QApplication.instance()
        if not app:
            return

        if theme_name == 'dark':
            app.setStyleSheet(self.dark_stylesheet)
        else:
            # Default to light theme if the name is unknown or 'light'
            app.setStyleSheet(self.light_stylesheet)
        
        config.theme = theme_name