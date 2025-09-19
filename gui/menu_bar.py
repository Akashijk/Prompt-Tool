"""The main menu bar for the application."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gui_app import GUIApp

class MenuBar(tk.Menu):
    """The main menu bar for the application."""
    def __init__(self, parent_app: 'GUIApp'):
        super().__init__(parent_app)
        self.parent_app = parent_app

        # --- File Menu ---
        self.file_menu = tk.Menu(self, tearoff=0)
        self.file_menu.add_command(label="New Template", command=self.parent_app._create_new_template_file)
        self.file_menu.add_command(label="Save Template", command=self.parent_app._save_template, state=tk.DISABLED)
        self.file_menu.add_command(label="Archive Template", command=self.parent_app._archive_current_template, state=tk.DISABLED)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Quit", command=self.parent_app._on_closing)
        self.add_cascade(label="File", menu=self.file_menu)

        # --- View Menu ---
        view_menu = tk.Menu(self, tearoff=0)
        theme_menu = tk.Menu(view_menu, tearoff=0)
        theme_menu.add_radiobutton(label="Light", variable=self.parent_app.theme_manager.theme_var, value="light", command=lambda: self.parent_app._set_theme("light"))
        theme_menu.add_radiobutton(label="Dark", variable=self.parent_app.theme_manager.theme_var, value="dark", command=lambda: self.parent_app._set_theme("dark"))
        view_menu.add_cascade(label="Theme", menu=theme_menu)
        
        font_menu = tk.Menu(view_menu, tearoff=0)
        for size in [10, 11, 12, 13, 14, 16]:
            font_menu.add_radiobutton(label=f"{size}pt", variable=self.parent_app.font_size_var, value=size, command=self.parent_app._set_font_size)
        view_menu.add_cascade(label="Font Size", menu=font_menu)
        self.add_cascade(label="View", menu=view_menu)

        # --- Workflow Menu ---
        workflow_menu = tk.Menu(self, tearoff=0)
        workflow_menu.add_radiobutton(label="SFW", variable=self.parent_app.workflow_var, value="sfw", command=self.parent_app._switch_workflow)
        workflow_menu.add_radiobutton(label="NSFW", variable=self.parent_app.workflow_var, value="nsfw", command=self.parent_app._switch_workflow)
        self.add_cascade(label="Workflow", menu=workflow_menu)

        # --- Tools Menu ---
        tools_menu = tk.Menu(self, tearoff=0)
        tools_menu.add_command(label="AI Brainstorming...", command=self.parent_app._open_brainstorming_window)
        tools_menu.add_command(label="Wildcard Manager...", command=self.parent_app._open_wildcard_manager)
        tools_menu.add_command(label="History Viewer...", command=self.parent_app._open_history_viewer)
        tools_menu.add_separator()
        tools_menu.add_command(label="Image Interrogator...", command=self.parent_app._open_image_interrogator)
        tools_menu.add_command(label="Prompt Evolver...", command=self.parent_app._open_prompt_evolver)
        tools_menu.add_command(label="Favorite Images Viewer...", command=self.parent_app._open_favorite_images_viewer)
        tools_menu.add_command(label="Model Usage Statistics...", command=self.parent_app._open_model_usage_viewer)
        tools_menu.add_separator()
        tools_menu.add_command(label="InvokeAI Asset Prefixes...", command=self.parent_app._open_asset_prefix_editor)
        tools_menu.add_command(label="System Prompt Editor...", command=self.parent_app._open_system_prompt_editor)
        tools_menu.add_command(label="Settings...", command=self.parent_app._open_settings_window)
        tools_menu.add_separator()
        tools_menu.add_command(label="Clear Wildcard Cache", command=self.parent_app._clear_wildcard_cache)
        self.add_cascade(label="Tools", menu=tools_menu)

        parent_app.config(menu=self)

    def update_file_menu_state(self, save_enabled: bool, archive_enabled: bool):
        """Updates the state of the File menu items."""
        self.file_menu.entryconfig("Save Template", state=tk.NORMAL if save_enabled else tk.DISABLED)
        self.file_menu.entryconfig("Archive Template", state=tk.NORMAL if archive_enabled else tk.DISABLED)