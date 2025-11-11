"""A manager to handle loading and applying Qt stylesheets for theming."""

import os
import re
from PySide6.QtWidgets import QApplication
from core.config import config

class ThemeManager:
    """Manages loading and applying application-wide themes from QSS files."""

    def __init__(self):
        self.themes_dir = os.path.join(os.path.dirname(__file__), 'themes')
        self.assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets')
        
        self.light_stylesheet_content = self._load_stylesheet_content('light.qss')
        self.dark_stylesheet_content = self._load_stylesheet_content('dark.qss')

        self.light_chevron_path = os.path.join(self.assets_dir, 'chevron-down-light.svg').replace(os.sep, '/')
        self.dark_chevron_path = os.path.join(self.assets_dir, 'chevron-down-dark.svg').replace(os.sep, '/')

    def _load_stylesheet_content(self, filename: str) -> str:
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

        stylesheet_to_apply = ""
        if theme_name == 'dark':
            stylesheet_to_apply = self.dark_stylesheet_content
            chevron_path = self.light_chevron_path # Dark theme uses light chevron
        else:
            stylesheet_to_apply = self.light_stylesheet_content
            chevron_path = self.dark_chevron_path # Light theme uses dark chevron
        
        # Dynamically replace the chevron image URL
        # This regex looks for QComboBox::down-arrow { ... image: url(...) ... }
        # and replaces the url content.
        # It's important to use re.DOTALL to match across newlines.
        modified_stylesheet = re.sub(
            r"(QComboBox::down-arrow\s*\{[^}]*image:\s*url\()[^)]*(\);[^}]*\})",
            r"\1" + f"'{chevron_path}'" + r"\2",
            stylesheet_to_apply,
            flags=re.DOTALL
        )

        app.setStyleSheet(modified_stylesheet)
        config.theme = theme_name