"""GUI for the Stable Diffusion Prompt Generator."""

import json
import os
import tkinter as tk
import tkinter.font as tkfont
import threading
import re
import random
import sys
import queue
from typing import Optional, List, Tuple, Dict, Any
from tkinter import ttk
from core.prompt_processor import PromptProcessor
from core.template_engine import PromptSegment
from core.config import config, DEFAULT_SFW_VARIATION_INSTRUCTIONS, DEFAULT_NSFW_VARIATION_INSTRUCTIONS, save_settings, load_settings
from .enhancement_window import EnhancementResultWindow
from .brainstorming_window import BrainstormingWindow
from .action_bar import ActionBar
from .common import Tooltip, LoadingAnimation, TextContextMenu, TemplateEditorContextMenu
from .history_viewer import HistoryViewerWindow
from .review_window import ReviewAndSaveWindow
from .system_prompt_editor import SystemPromptEditorWindow
from .wildcard_manager import WildcardManagerWindow
from .template_editor import TemplateEditor
from .wildcard_inserter import WildcardInserter
from . import custom_dialogs
from .theme_manager import ThemeManager

         
class GUIApp(tk.Tk):
    """A GUI for the Stable Diffusion Prompt Generator."""

    def __init__(self):
        super().__init__()
        self.geometry("900x700")

        # Set application icon
        # FONT MANAGEMENT
        self._initialize_fonts()

        # Initialize and apply the theme first
        self.theme_manager = ThemeManager()
        self.theme_manager.apply_theme(self)
        try:
            icon_path = os.path.join(config.PROJECT_ROOT, 'assets', 'icon.png')
            if os.path.exists(icon_path):
                self.iconphoto(True, tk.PhotoImage(file=icon_path))
        except Exception as e:
            print(f"Warning: Could not load application icon: {e}")

        # Core logic
        self.processor = PromptProcessor()
        self.processor.initialize()
        self.processor.set_callbacks(status_callback=self._update_status_bar)
        self.enhancement_total_calls = 0
        self.enhancement_calls_made = 0
        self.active_api_calls = 0
        self.enhancement_cancellation_event: Optional[threading.Event] = None

        # State
        self.current_template_content: Optional[str] = None
        self.current_template_file: Optional[str] = None
        self.current_structured_prompt: List[PromptSegment] = []
        self.segment_map: List[Tuple[str, str, int]] = []  # start, end, segment_index
        self.tooltip: Optional[Tooltip] = None
        self.debounce_timer: Optional[str] = None
        self.active_models: Dict[str, int] = {}
        self.active_enhancement_model: Optional[str] = None
        self.brainstorming_window: Optional[BrainstormingWindow] = None
        self.wildcard_manager_window: Optional[WildcardManagerWindow] = None
        self.history_viewer_window: Optional[HistoryViewerWindow] = None
        self.loading_animation: Optional[LoadingAnimation] = None
        self.template_editor: Optional[TemplateEditor] = None
        self.wildcard_inserter: Optional[WildcardInserter] = None
        self.file_menu: Optional[tk.Menu] = None
        self.enhancement_model_var = tk.StringVar()
        self.font_size_var = tk.IntVar(value=config.font_size)
        self.workflow_var = tk.StringVar(value=config.workflow)
        self.enhancement_queue = queue.Queue()
        self.enhancement_suggestion_queue = queue.Queue()
        self.enhancement_suggestion_after_id: Optional[str] = None

        # Create widgets
        self._create_widgets()
        self._update_text_widget_colors() # Set initial theme-based colors
        self._load_templates()
        self._load_models()
        self._populate_wildcard_lists()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self._update_window_title() # Set initial title

    def _initialize_fonts(self):
        """Initializes named fonts for the application."""
        self.default_font = tkfont.Font(family="Helvetica", size=config.font_size)
        self.fixed_font = tkfont.Font(family="Courier", size=config.font_size)
        self.large_font = tkfont.Font(family="Helvetica", size=config.font_size + 2)
        self.small_font = tkfont.Font(family="Helvetica", size=config.font_size - 1)

        # Update default ttk styles
        style = ttk.Style()
        style.configure(".", font=self.default_font)
        style.configure("TLabel", font=self.default_font)
        style.configure("TButton", font=self.default_font)
        style.configure("TCheckbutton", font=self.default_font)
        style.configure("TRadiobutton", font=self.default_font)
        style.configure("TEntry", font=self.default_font)
        style.configure("TCombobox", font=self.default_font)
        style.configure("TLabelFrame.Label", font=self.default_font)
        style.configure("TNotebook.Tab", font=self.default_font)

    def _create_widgets(self):
        """Create and layout the main widgets."""
        self._create_menu_bar()

        # --- Top Control Frame ---
        control_frame = ttk.Frame(self, padding="10")
        control_frame.pack(fill=tk.X)

        # Template Dropdown
        ttk.Label(control_frame, text="Template:").pack(side=tk.LEFT, padx=(0, 5))
        self.template_var = tk.StringVar()
        self.template_var.trace_add("write", self._on_template_var_change)
        self.template_dropdown = ttk.OptionMenu(control_frame, self.template_var, "Select a template")
        self.template_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        # Model Dropdown
        ttk.Label(control_frame, text="Model:").pack(side=tk.LEFT, padx=(0, 5))
        self.enhancement_model_var.trace_add("write", self._on_enhancement_model_change)
        self.model_dropdown = ttk.OptionMenu(control_frame, self.enhancement_model_var, "Select a model")
        self.model_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._create_main_view(self)

        # --- Bottom Action Frame ---
        action_frame = ttk.Frame(self, padding=(10, 5, 10, 10))
        action_frame.pack(fill=tk.X)
        self._create_action_bar(action_frame)
        self.action_bar.pack(fill=tk.X)

        # --- Status Bar ---
        status_frame = ttk.Frame(self, relief=tk.SUNKEN)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.loading_animation = LoadingAnimation(status_frame)
        self.loading_animation.pack(side=tk.LEFT, padx=5, pady=2)

        self.status_var = tk.StringVar()
        status_bar = ttk.Label(status_frame, textvariable=self.status_var, anchor=tk.W, padding=(0, 5, 5, 5))
        status_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _create_menu_bar(self):
        """Creates the main application menu bar."""
        menubar = tk.Menu(self)

        # --- File Menu ---
        self.file_menu = tk.Menu(menubar, tearoff=0)
        self.file_menu.add_command(label="New Template...", command=self._create_new_template_file)
        self.file_menu.add_command(label="Save Template", command=self._save_template, state=tk.DISABLED)
        self.file_menu.add_command(label="Archive Template...", command=self._archive_current_template, state=tk.DISABLED)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self._on_closing)
        menubar.add_cascade(label="File", menu=self.file_menu)

        # --- Workflow Menu ---
        workflow_menu = tk.Menu(menubar, tearoff=0)
        workflow_menu.add_radiobutton(label="SFW (Safe For Work)", variable=self.workflow_var, value="sfw", command=self._switch_workflow)
        workflow_menu.add_radiobutton(label="NSFW (Not Safe For Work)", variable=self.workflow_var, value="nsfw", command=self._switch_workflow)
        menubar.add_cascade(label="Workflow", menu=workflow_menu)
        self.workflow_var.set(config.workflow) # Ensure it's set on startup

        # --- View Menu ---
        view_menu = tk.Menu(menubar, tearoff=0)
        theme_menu = tk.Menu(view_menu, tearoff=0)
        theme_menu.add_command(label="Light", command=lambda: self._set_theme("light"))
        theme_menu.add_command(label="Dark", command=lambda: self._set_theme("dark"))
        view_menu.add_cascade(label="Theme", menu=theme_menu)

        font_menu = tk.Menu(view_menu, tearoff=0)
        for size in [10, 11, 12, 14, 16]:
            font_menu.add_radiobutton(label=f"{size} pt", variable=self.font_size_var, value=size, command=self._set_font_size)
        view_menu.add_cascade(label="Font Size", menu=font_menu)

        menubar.add_cascade(label="View", menu=view_menu)

        # --- Tools Menu ---
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Wildcard Manager", command=self._open_wildcard_manager)
        tools_menu.add_command(label="Ollama Server...", command=self._change_ollama_server)
        tools_menu.add_command(label="AI Brainstorming", command=self._open_brainstorming_window)
        tools_menu.add_command(label="System Prompt Editor", command=self._open_system_prompt_editor)
        tools_menu.add_command(label="History Viewer", command=self._open_history_viewer)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        self.config(menu=menubar)

    def _create_main_view(self, parent):
        """Creates the widgets for the main prompt generation view."""
        v_pane = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        v_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Top horizontal splitter for editor and wildcard list
        top_h_pane = ttk.PanedWindow(v_pane, orient=tk.HORIZONTAL)
        v_pane.add(top_h_pane, weight=2)

        # --- Template editor (left side of top pane) ---
        self.template_editor = TemplateEditor(
            top_h_pane,
            self,
            live_update_callback=self._schedule_live_update,
            double_click_callback=self._on_template_double_click,
            generate_wildcard_callback=self._generate_missing_wildcard,
            brainstorm_callback=self._brainstorm_with_template,
            create_wildcard_callback=self._create_wildcard_from_selection
        )
        top_h_pane.add(self.template_editor, weight=3)

        # --- Wildcard inserter (right side of top pane) ---
        self.wildcard_inserter = WildcardInserter(
            top_h_pane,
            self,
            insert_callback=self._insert_wildcard_tag,
            manage_callback=self._open_wildcard_manager
        )
        top_h_pane.add(self.wildcard_inserter, weight=1)

        # Generated prompt (bottom pane of vertical splitter)
        preview_pane = ttk.LabelFrame(v_pane, text="Generated Prompt (Wildcards are highlighted)", padding=5)
        self.prompt_text = tk.Text(preview_pane, wrap=tk.WORD, height=10, font=self.large_font)
        self.prompt_text.pack(fill=tk.BOTH, expand=True)
        TextContextMenu(self.prompt_text)
        self.prompt_text.config(state=tk.DISABLED)

        # Configure tags and bindings for the interactive prompt text
        self.prompt_text.tag_configure("wildcard", relief="raised", borderwidth=1)
        self.prompt_text.tag_bind("wildcard", "<Enter>", self._on_wildcard_enter)
        self.prompt_text.tag_bind("wildcard", "<Leave>", self._on_wildcard_leave)
        self.prompt_text.tag_bind("wildcard", "<Button-1>", self._on_wildcard_click)
        self.prompt_text.tag_configure("wildcard_hover")
        v_pane.add(preview_pane, weight=3)

    def _create_action_bar(self, parent):
        """Creates the main action buttons at the bottom of the window."""
        self.action_bar = ActionBar(
            parent,
            generate_callback=self._generate_preview,
            enhance_callback=self._on_select_for_enhancement,
            copy_callback=self._copy_generated_prompt,
            suggest_callback=self._suggest_enhancement
        )
        self._update_action_bar_variations()

    def _update_window_title(self):
        """Updates the main window title to reflect the current workflow."""
        base_title = "Prompt Tool GUI"
        if config.workflow == 'nsfw':
            self.title(f"{base_title} - [NSFW Mode]")
        else:
            self.title(base_title)

    def _set_font_size(self):
        """Updates all named fonts to the new size and saves the setting."""
        new_size = self.font_size_var.get()
        
        self.default_font.config(size=new_size)
        self.fixed_font.config(size=new_size)
        self.large_font.config(size=new_size + 2)
        self.small_font.config(size=new_size - 1)
        
        # Save the setting
        config.font_size = new_size
        settings = load_settings()
        settings['font_size'] = new_size
        save_settings(settings)
        
        self.status_var.set(f"Font size set to {new_size}pt.")

    def _set_theme(self, theme_name: str):
        """Sets the theme and updates UI elements that need manual color changes."""
        self.theme_manager.set_theme(theme_name)
        self._update_text_widget_colors()

    def _update_text_widget_colors(self):
        """Updates colors for text widgets and tags based on the current theme."""
        is_dark = self.theme_manager.current_theme == "dark"

        # Define colors for light and dark modes
        wildcard_bg = "#3c4c5c" if is_dark else "#d8e9f3"
        wildcard_hover_bg = "#4a5e73" if is_dark else "#b8d9e3"
        missing_wildcard_bg = "#6b2b2b" if is_dark else "#ffcccc"
        status_bar_dot_color = "lightgrey" if is_dark else "dimgray"
        status_bar_bg = self.cget('background')

        # Apply colors to tags
        self.prompt_text.tag_configure("wildcard", background=wildcard_bg)
        self.prompt_text.tag_configure("wildcard_hover", background=wildcard_hover_bg)
        self.template_editor.text_widget.tag_configure("missing_wildcard", background=missing_wildcard_bg)

        if self.loading_animation:
            self.loading_animation.update_style(bg_color=status_bar_bg, dot_color=status_bar_dot_color, is_dark_theme=is_dark)

    def _load_templates(self):
        """Loads available templates into the dropdown menu."""
        # Always reset the view to a clean state before loading new templates
        self._clear_template_view()

        templates = self.processor.get_available_templates()
        menu = self.template_dropdown["menu"]
        menu.delete(0, "end")

        if not templates:
            workflow_dir = config.get_template_dir()
            custom_dialogs.show_warning(self, "No Templates", f"No template files found for the '{config.workflow.upper()}' workflow.\n\nPlease add .txt files to:\n{workflow_dir}")
            self.template_var.set("No templates found")
            self.template_dropdown.config(state=tk.DISABLED)
            return
        
        self.template_dropdown.config(state=tk.NORMAL)
        for template in templates:
            menu.add_command(label=template, command=lambda value=template: self.template_var.set(value))
        
        # Prompt the user to make a selection
        self.template_var.set("Select a template")

    def _update_action_bar_variations(self):
        """Updates the variation checkboxes in the action bar based on the current workflow."""
        variation_keys = list(DEFAULT_SFW_VARIATION_INSTRUCTIONS.keys()) if config.workflow == 'sfw' else list(DEFAULT_NSFW_VARIATION_INSTRUCTIONS.keys())
        self.action_bar.rebuild_variations(variation_keys)

    def _load_models(self):
        """Loads available Ollama models into the dropdown menu."""
        try:
            models = self.processor.get_available_models()
            if not models:
                self.enhancement_model_var.set("No models found")
                return

            menu = self.model_dropdown["menu"]
            menu.delete(0, "end")
            for model in models:
                menu.add_command(label=model, command=lambda value=model: self.enhancement_model_var.set(value))

            # Set a default model if possible
            default_model = next((m for m in models if 'qwen' in m.lower()), models[0])
            self.enhancement_model_var.set(default_model)
            
            # Register initial model usage
            self.active_enhancement_model = default_model
            self._handle_model_change(None, self.active_enhancement_model)

        except Exception as e:
            custom_dialogs.show_error(self, "Model Error", f"Could not load Ollama models:\n{e}")
            self.enhancement_model_var.set("Error loading models")

    def _switch_workflow(self):
        """Handles the logic for switching between SFW and NSFW modes."""
        new_workflow = self.workflow_var.get()
        if new_workflow == config.workflow:
            return

        config.workflow = new_workflow
        settings = load_settings()
        settings['workflow'] = new_workflow
        save_settings(settings)

        # Tell the processor to reload its internal wildcard state
        self.processor.reload_wildcards()

        # Update UI components that depend on the workflow
        self._update_action_bar_variations()
        self._load_templates() # This will now reset the view and prompt for selection
        self._populate_wildcard_lists()
        self._update_window_title()

        # Close history viewer if it's open, as its data is now stale
        if self.history_viewer_window and self.history_viewer_window.winfo_exists():
            self.history_viewer_window.destroy()
            self.history_viewer_window = None

        self.status_var.set(f"Switched to {new_workflow.upper()} workflow. Select a template.")

    def _clear_template_view(self):
        """Resets the UI to a state where no template is loaded."""
        self.current_template_file = None
        self.current_template_content = None
        self.current_structured_prompt = []
        self.template_editor.clear()
        self.template_editor.set_label("Template Content")
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.config(state=tk.DISABLED)
        self.action_bar.set_button_states(generate=tk.DISABLED, enhance=tk.DISABLED, copy=tk.DISABLED, suggest=tk.DISABLED)
        self.file_menu.entryconfig("Save Template", state=tk.DISABLED)
        self.file_menu.entryconfig("Archive Template...", state=tk.DISABLED)
    def _populate_wildcard_lists(self):
        """Populates both the inserter and editor wildcard lists."""
        wildcard_files = self.processor.get_wildcard_files()
        if not wildcard_files:
            shared_dir = config.WILDCARD_DIR
            message = (
                f"No wildcard files found for the '{config.workflow.upper()}' workflow.\n\n"
                f"Please add .json or .txt files to the shared folder:\n{shared_dir}"
            )
            if config.workflow == 'nsfw':
                message += f"\n\nor the NSFW-specific folder:\n{config.WILDCARD_NSFW_DIR}"
            custom_dialogs.show_warning(self, "No Wildcards", message)
        self.wildcard_inserter.populate(wildcard_files)

    def _on_template_var_change(self, *args):
        """Callback for when the template_var changes."""
        new_template_name = self.template_var.get()

        # Ignore placeholder text to prevent errors
        if new_template_name in ["Select a template", "No templates found"]:
            return

        # Prevent redundant updates if the value is set to the same thing
        if new_template_name and new_template_name != self.current_template_file:
            self._on_template_select(new_template_name)

    def _on_enhancement_model_change(self, *args):
        """Handles when the user selects a new model for enhancement."""
        new_model = self.enhancement_model_var.get()
        old_model = self.active_enhancement_model
        if new_model and "model" not in new_model.lower() and new_model != old_model:
            self._handle_model_change(old_model, new_model)
            self.active_enhancement_model = new_model

    def _on_template_select(self, template_name: str):
        """Callback for when a template is selected from the dropdown."""
        self.current_template_file = template_name
        self.template_editor.set_label("Template Content") # Reset label

        # Load template content into both state and the template view
        self.current_template_content = self.processor.load_template_content(template_name)
        self.template_editor.set_content(self.current_template_content)
        self._highlight_template_wildcards()

        # Update UI state
        self.action_bar.set_button_states(generate=tk.NORMAL, enhance=tk.DISABLED, copy=tk.DISABLED, suggest=tk.NORMAL)
        self.file_menu.entryconfig("Save Template", state=tk.NORMAL)
        self.file_menu.entryconfig("Archive Template...", state=tk.NORMAL)
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert(tk.END, f"Template '{template_name}' loaded. Click 'Generate Next Preview' to start.")
        self.prompt_text.config(state=tk.DISABLED)
        self.current_structured_prompt = []
        self.status_var.set(f"Loaded template: {template_name}")

    def _generate_preview(self):
        """Generates a single prompt and displays it in the text box."""
        # Get content directly from the live editor
        live_content = self.template_editor.get_content() # Get all text except the final newline
        if not live_content.strip():
            return

        # Generate with fresh random wildcards, so pass existing_segments=None
        self.current_structured_prompt = self.processor.generate_single_structured_prompt(live_content, existing_segments=None)
        self._display_structured_prompt()
        is_prompt_available = bool(self.current_structured_prompt)
        self.action_bar.set_button_states(generate=tk.NORMAL, enhance=tk.NORMAL if is_prompt_available else tk.DISABLED, copy=tk.NORMAL if is_prompt_available else tk.DISABLED, suggest=tk.NORMAL)

    def _display_structured_prompt(self):
        """Renders the structured prompt with highlighting."""
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.segment_map = []

        for i, segment in enumerate(self.current_structured_prompt):
            start = self.prompt_text.index(tk.INSERT)
            self.prompt_text.insert(tk.INSERT, segment.text)
            end = self.prompt_text.index(tk.INSERT)

            if segment.wildcard_name:
                tag_name = f"wildcard_{i}"
                self.prompt_text.tag_add(tag_name, start, end)
                self.prompt_text.tag_add("wildcard", start, end)
                self.segment_map.append((start, end, i))

        self.prompt_text.config(state=tk.DISABLED)

    def _on_wildcard_enter(self, event):
        """Handle mouse entering a wildcard tag."""
        if self.tooltip:
            self.tooltip.hide()

        # Find the tag under the cursor
        tag_ranges = self.prompt_text.tag_ranges("wildcard")
        for i in range(0, len(tag_ranges), 2):
            start, end = tag_ranges[i], tag_ranges[i+1]
            if self.prompt_text.compare(start, "<=", "current") and self.prompt_text.compare("current", "<", end):
                # Find which segment this corresponds to
                for seg_start, seg_end, seg_index in self.segment_map:
                    if self.prompt_text.compare(start, "==", seg_start):
                        wildcard_name = self.current_structured_prompt[seg_index].wildcard_name
                        self.tooltip = Tooltip(self.prompt_text, f"Source: {wildcard_name}.json")
                        self.tooltip.show(event)
                        self.prompt_text.tag_add("wildcard_hover", start, end)
                        break
                break

    def _on_wildcard_leave(self, event):
        """Handle mouse leaving a wildcard tag."""
        if self.tooltip:
            self.tooltip.hide()
        self.prompt_text.tag_remove("wildcard_hover", "1.0", tk.END)

    def _on_wildcard_click(self, event):
        """Handle clicking on a wildcard tag."""
        # Find the segment that was clicked
        clicked_segment_index = -1
        for start, end, seg_index in self.segment_map:
            if self.prompt_text.compare(start, "<=", "current") and self.prompt_text.compare("current", "<", end):
                clicked_segment_index = seg_index
                break

        if clicked_segment_index != -1:
            self._show_swap_menu(event, clicked_segment_index)

    def _show_swap_menu(self, event, segment_index: int):
        """Display a context menu to swap the wildcard value."""
        segment = self.current_structured_prompt[segment_index]
        if not segment.wildcard_name:
            return

        options = self.processor.get_wildcard_options(segment.wildcard_name)
        if not options:
            return

        menu = tk.Menu(self, tearoff=0)
        for option in options:
            # Truncate long options for display in the menu
            display_option = (option[:75] + '...') if len(option) > 75 else option
            menu.add_command(
                label=display_option,
                command=lambda opt=option: self._swap_wildcard(segment_index, opt)
            )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _swap_wildcard(self, segment_index: int, new_value: str):
        """Swap the text of a wildcard segment and redisplay the prompt."""
        if 0 <= segment_index < len(self.current_structured_prompt):
            self.current_structured_prompt[segment_index].text = new_value
            self._display_structured_prompt()

    def _schedule_live_update(self, event=None):
        """Schedules a live update of the prompt preview after a short delay."""
        if self.debounce_timer:
            self.after_cancel(self.debounce_timer)
        
        has_text = bool(self.template_editor.get_content().strip())
        self.action_bar.suggest_button.config(state=tk.NORMAL if has_text else tk.DISABLED)

        self.debounce_timer = self.after(500, self._perform_live_update)

    def _perform_live_update(self, force_reroll: Optional[List[str]] = None):
        """Updates the prompt preview using the current template text and existing wildcards."""
        self.debounce_timer = None
        if not self.current_template_content:
            return
            
        live_content = self.template_editor.get_content()
        if not live_content.strip():
            return
            
        # Regenerate the prompt, reusing the existing wildcard choices
        self.current_structured_prompt = self.processor.generate_single_structured_prompt(
            live_content,
            existing_segments=self.current_structured_prompt,
            force_reroll=force_reroll
        )
        self._display_structured_prompt()
        self._highlight_template_wildcards()
        if force_reroll:
            self.status_var.set(f"Wildcard '{force_reroll[0]}' updated.")
        else:
            self.status_var.set("Preview updated based on template changes.")

    def _save_template(self):
        """Save the currently edited template content to its file."""
        if not self.current_template_file:
            self.status_var.set("No template selected to save.")
            return

        content = self.template_editor.get_content()
        try:
            self.processor.save_template_content(self.current_template_file, content)
            self.status_var.set(f"Template '{self.current_template_file}' saved successfully.")
            self.current_template_content = content # Update internal state
        except Exception as e:
            custom_dialogs.show_error(self, "Save Error", f"Could not save template:\n{e}")
            self.status_var.set(f"Error saving template: {self.current_template_file}")

    def _copy_generated_prompt(self):
        """Copies the current generated prompt text to the clipboard."""
        prompt_text = ""
        if self.current_template_file:
            # Reconstruct the full prompt string from segments
            prompt_text = "".join(seg.text for seg in self.current_structured_prompt)
        else:
            # Get the prompt directly from the editor pane
            prompt_text = self.template_editor.get_content().strip()

        if not prompt_text:
            self.status_var.set("Nothing to copy.")
            return
        
        self.clipboard_clear()
        self.clipboard_append(prompt_text)
        self.status_var.set("Prompt copied to clipboard.")

    def _on_select_for_enhancement(self):
        """Handles the 'Enhance This Prompt' button click."""
        model = self.enhancement_model_var.get()
        if not model or "model" in model.lower():
            custom_dialogs.show_error(self, "Error", "Please select a valid Ollama model first.")
            return

        # Determine if we are enhancing from a template-generated prompt or a manually edited one
        if self.current_template_file:
            # Reconstruct the full prompt string from segments
            prompt_text = "".join(seg.text for seg in self.current_structured_prompt)
        else:
            # Get the prompt directly from the editor pane
            prompt_text = self.template_editor.get_content().strip()

        if not prompt_text:
            custom_dialogs.show_error(self, "Error", "No prompt to enhance.")
            return

        # Create the results window immediately
        selected_variations = self.action_bar.get_selected_variations()
        initial_data = {'original': prompt_text, 'variations': {}}

        # Set up call counters for the new batch
        self.enhancement_calls_made = 0
        self.enhancement_total_calls = 1 + len(selected_variations)
        self.active_api_calls = self.enhancement_total_calls
        if self.active_api_calls > 0:
            self.loading_animation.start()

        self.enhancement_cancellation_event = threading.Event()
        result_window = EnhancementResultWindow(self, initial_data, self.processor, model, selected_variations, self._cancel_enhancement_batch, self.report_api_call_finished)

        # Define a thread-safe callback to update the results window
        def result_callback(key, data):
            result_window.result_queue.put((key, data))

        # Set callbacks for the processor
        self.processor.set_callbacks(
            status_callback=self._update_status_bar_from_event,
            result_callback=result_callback
        )

        self.action_bar.select_button.config(state=tk.DISABLED)
        self.status_var.set(f"Enhancing prompt with {model}...")

        # Run enhancement in a separate thread to avoid freezing the GUI
        thread = threading.Thread(target=self._run_enhancement_thread, args=(prompt_text, model, selected_variations, self.enhancement_cancellation_event), daemon=True)
        thread.start()

    def _run_enhancement_thread(self, prompt: str, model: str, selected_variations: List[str], cancellation_event: threading.Event):
        """The function that runs in a separate thread to process the prompt."""
        try:
            # This is now a fire-and-forget process from the GUI's perspective.
            # The processor will use callbacks to update the UI.
            self.processor.process_enhancement_batch([prompt], model, selected_variations, cancellation_event)
        except Exception as e:
            self.after(0, lambda: custom_dialogs.show_error(self, "Enhancement Error", f"An error occurred during processing:\n{e}"))
        finally:
            # Re-enable the main enhance button when processing is complete
            self.action_bar.select_button.config(state=tk.NORMAL)

    def _update_status_bar(self, message: str):
        """Thread-safe method to update the status bar."""
        self.after(0, lambda: self.status_var.set(message))

    def _update_status_bar_from_event(self, event_type: str, **kwargs):
        """Handles structured status events from the processor."""
        # If a cancellation has been requested, ignore any "complete" message for this batch
        if self.enhancement_cancellation_event and self.enhancement_cancellation_event.is_set() and event_type == 'batch_complete':
            return

        self.enhancement_calls_made += 1
        message = ""
        if event_type == 'enhancement_start':
            message = f"Enhancing main prompt... (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        elif event_type == 'variation_start':
            var_type = kwargs.get('var_type', 'unknown')
            message = f"Creating '{var_type}' variation... (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        elif event_type == 'batch_complete':
            message = "Batch processing complete."
        elif event_type == 'batch_cancelled':
            message = "Processing cancelled."
        
        if message:
            self._update_status_bar(message)

    def register_regeneration_call(self, prompt_key: str):
        """Increments the total call counter when a regeneration is requested."""
        self.active_api_calls += 1
        if self.active_api_calls > 0:
            self.loading_animation.start()

        self.enhancement_total_calls += 1
        message = f"Regenerating '{prompt_key}'... (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        self._update_status_bar(message)

    def report_regeneration_finished(self, success: bool):
        """Updates counters and status after a regeneration call is finished."""
        self.report_api_call_finished()

        if success:
            self.enhancement_calls_made += 1
            message = f"Regeneration complete. (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        else:
            message = f"Regeneration failed. (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        self._update_status_bar(message)
    
    def report_api_call_finished(self):
        """Decrements the active API call counter and stops the animation if complete."""
        if self.active_api_calls > 0:
            self.active_api_calls -= 1
        
        if self.active_api_calls == 0:
            self.loading_animation.stop()

    def _cancel_enhancement_batch(self):
        """Sets the cancellation event for the current enhancement batch."""
        if self.enhancement_cancellation_event and not self.enhancement_cancellation_event.is_set():
            self.enhancement_cancellation_event.set()
            self._update_status_bar("Processing cancelled.")
            self.active_api_calls = 0
            self.loading_animation.stop()

    def _open_wildcard_manager(self, initial_file: Optional[str] = None, initial_content: Optional[str] = None):
        """Opens the wildcard management window."""
        if self.wildcard_manager_window and self.wildcard_manager_window.winfo_exists():
            self.wildcard_manager_window.lift()
            self.wildcard_manager_window.focus_force()
            if initial_file:
                # The manager doesn't currently support loading new content into an existing window.
                self.wildcard_manager_window.select_and_load_file(initial_file)
        else:
            self.wildcard_manager_window = WildcardManagerWindow(self, self.processor, self._handle_wildcard_update, initial_file=initial_file, initial_content=initial_content)
            self.wildcard_manager_window.protocol("WM_DELETE_WINDOW", self._on_wildcard_manager_close)

    def _on_wildcard_manager_close(self):
        if self.wildcard_manager_window:
            self.wildcard_manager_window.close()
            self.wildcard_manager_window = None

    def _handle_wildcard_update(self, modified_file: Optional[str] = None):
        """Refreshes wildcard lists and triggers a prompt update if a relevant wildcard was modified."""
        # First, always refresh the inserter list
        self._populate_wildcard_lists()

        if not modified_file or not self.current_structured_prompt:
            return

        modified_wildcard_name = modified_file[:-5]  # remove .json

        # Check if the modified wildcard is used in the current prompt
        needs_update = any(
            segment.wildcard_name == modified_wildcard_name
            for segment in self.current_structured_prompt
        )

        if needs_update:
            self._perform_live_update(force_reroll=[modified_wildcard_name])

    def _insert_wildcard_tag(self, event):
        """Inserts a wildcard tag, overwriting a selection or the tag under the cursor."""
        wildcard_name = self.wildcard_inserter.get_selected_wildcard_name()
        if not wildcard_name:
            return

        self.template_editor.insert_wildcard_tag(wildcard_name)
        self._highlight_template_wildcards() # Update tags immediately for the next action
        self._schedule_live_update() # Trigger a live preview update for the bottom pane

    def _on_template_double_click(self, event):
        """Handle double-click in template editor to open wildcard file."""
        index = self.template_editor.text_widget.index(f"@{event.x},{event.y}")
        
        # Find the range of the double-clicked word
        word_start = self.template_editor.text_widget.index(f"{index} wordstart")
        word_end = self.template_editor.text_widget.index(f"{index} wordend")
        clicked_word = self.template_editor.text_widget.get(word_start, word_end)

        # Check if it's a wildcard tag
        match = re.fullmatch(r'__([a-zA-Z0-9_.-]+)__', clicked_word)
        if match:
            wildcard_name = match.group(1)
            self._open_wildcard_manager(initial_file=f"{wildcard_name}.json")

    def _highlight_template_wildcards(self):
        """Highlights missing wildcards and tags all wildcards in the template editor."""
        known_wildcards = self.processor.get_wildcard_names()
        self.template_editor.highlight_wildcards(known_wildcards)

    def _create_new_template_file(self):
        """Prompts user for a new template filename and creates it."""
        filename = custom_dialogs.ask_string(self, "New Template", "Enter new template filename:")
        if not filename:
            return
        
        if not filename.endswith('.txt'):
            filename += '.txt'
            
        try:
            # Create an empty file by saving empty content
            self.processor.save_template_content(filename, "")
            self._load_templates()
            self.template_var.set(filename) # This will trigger the update via trace
            self.status_var.set(f"Created and loaded new template: {filename}")
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not create template file:\n{e}")

    def _archive_current_template(self):
        """Moves the current template file to an archive folder."""
        if not self.current_template_file:
            custom_dialogs.show_warning(self, "No Template", "No template is currently selected to archive.")
            return

        if not custom_dialogs.ask_yes_no(self, "Confirm Archive", f"Are you sure you want to archive '{self.current_template_file}'?\n\nThis will move the file to a subfolder named 'archive'."):
            return

        try:
            self.processor.archive_template(self.current_template_file)
            self.status_var.set(f"Archived template: {self.current_template_file}")
            
            # Clear the UI and load the next available template
            self.template_editor.clear()
            self.prompt_text.config(state=tk.NORMAL)
            self.prompt_text.delete("1.0", tk.END)
            self.prompt_text.config(state=tk.DISABLED)
            self.current_template_file = None
            self.file_menu.entryconfig("Save Template", state=tk.DISABLED)
            self.file_menu.entryconfig("Archive Template...", state=tk.DISABLED)
            self._load_templates()

        except Exception as e:
            custom_dialogs.show_error(self, "Archive Error", f"Could not archive file:\n{e}")

    def _open_brainstorming_window(self):
        """Opens the brainstorming window."""
        if self.brainstorming_window and self.brainstorming_window.winfo_exists():
            self.brainstorming_window.lift()
            self.brainstorming_window.focus_force()
        else:
            try:
                models = self.processor.get_available_models()
                if not models:
                    custom_dialogs.show_error(self, "Error", "No Ollama models available for brainstorming.")
                    return
                default_model = self.enhancement_model_var.get()
                if default_model not in models:
                    default_model = models[0]
                
                self.brainstorming_window = BrainstormingWindow(self, self.processor, models, default_model, self._handle_model_change, self._handle_ai_content_update)
                self.brainstorming_window.protocol("WM_DELETE_WINDOW", self._on_brainstorming_window_close)
            except Exception as e:
                custom_dialogs.show_error(self, "Error", f"Could not open brainstorming window:\n{e}")

    def _on_brainstorming_window_close(self):
        if self.brainstorming_window:
            # Decrement the usage count of the model active in the brainstorming window
            active_model = self.brainstorming_window.active_brainstorm_model
            self._handle_model_change(active_model, None)
            
            self.brainstorming_window.close()
            self.brainstorming_window = None

    def _open_history_viewer(self):
        """Opens the history viewer window."""
        if self.history_viewer_window and self.history_viewer_window.winfo_exists():
            self.history_viewer_window.lift()
            self.history_viewer_window.focus_force()
        else:
            self.history_viewer_window = HistoryViewerWindow(self, self.processor)
            self.history_viewer_window.protocol("WM_DELETE_WINDOW", self._on_history_viewer_close)

    def _on_history_viewer_close(self):
        if self.history_viewer_window:
            self.history_viewer_window.destroy()
            self.history_viewer_window = None

    def load_prompt_from_history(self, prompt_text: str):
        """Loads a prompt from the history viewer into the main UI for re-enhancement."""
        # Clear template-related state and UI
        self.template_var.set("") # Clear dropdown selection
        self.current_template_file = None
        self.current_template_content = None
        self.current_structured_prompt = []
        self.file_menu.entryconfig("Save Template", state=tk.DISABLED)
        self.file_menu.entryconfig("Archive Template...", state=tk.DISABLED)
        self.action_bar.generate_button.config(state=tk.DISABLED) # Can't generate from a non-template
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.config(state=tk.DISABLED)

        # Load the historical prompt into the editable text area
        self.template_editor.set_label("Editable Prompt (from History)")
        self.template_editor.set_content(prompt_text)

        # Enable enhancement actions
        self.action_bar.set_button_states(generate=tk.DISABLED, enhance=tk.NORMAL, copy=tk.NORMAL)
        self.status_var.set("Loaded prompt from history. Ready to enhance.")

    def _brainstorm_with_template(self):
        """Sends the current template content to the brainstorming window."""
        if not self.template_editor: return
        content = self.template_editor.get_content()
        filename = self.current_template_file or "Unsaved Template"
        self._brainstorm_with_content("template", filename, content)

    def _brainstorm_with_content(self, content_type: str, filename: str, content: str):
        """Opens the brainstorming window and loads the specified content."""
        self._open_brainstorming_window()
        if self.brainstorming_window and self.brainstorming_window.winfo_exists():
            self.brainstorming_window.lift()
            self.brainstorming_window.focus_force()
            self.brainstorming_window.load_content_for_brainstorming(content_type, filename, content)

    def _generate_missing_wildcard(self, wildcard_name: str):
        """Opens the brainstorming window and triggers generation for a missing wildcard."""
        # The topic for the wildcard is derived from its name
        topic = wildcard_name.replace('_', ' ').replace('-', ' ')
        
        # Open brainstorming window if not already open
        self._open_brainstorming_window()
        
        if self.brainstorming_window and self.brainstorming_window.winfo_exists():
            self.brainstorming_window.lift()
            self.brainstorming_window.focus_force()
            # Call the new method to start generation
            self.brainstorming_window.generate_wildcard_with_topic(topic)

    def _suggest_enhancement(self):
        """Asks the AI to suggest an enhancement for the current prompt text."""
        model = self.enhancement_model_var.get()
        if not model or "model" in model.lower():
            custom_dialogs.show_error(self, "Error", "Please select a valid Ollama model first.")
            return

        # Get the current text from the editor
        prompt_text = self.template_editor.get_content().strip()
        if not prompt_text:
            custom_dialogs.show_error(self, "Error", "There is no prompt text to get suggestions for.")
            return

        self.action_bar.suggest_button.config(state=tk.DISABLED, text="Suggesting...")
        self.status_var.set(f"Getting enhancement suggestion from {model}...")

        def task():
            try:
                suggestion = self.processor.suggest_enhancement(prompt_text, model)
                self.enhancement_suggestion_queue.put({'success': True, 'suggestion': suggestion})
            except Exception as e:
                self.enhancement_suggestion_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.enhancement_suggestion_after_id = self.after(100, self._check_enhancement_suggestion_queue)

    def _check_enhancement_suggestion_queue(self):
        """Checks for AI enhancement suggestions and updates the editor."""
        try:
            result = self.enhancement_suggestion_queue.get_nowait()
            self.action_bar.suggest_button.config(state=tk.NORMAL, text="Suggest (AI)")
            
            if result['success']:
                suggestion = result.get('suggestion', '')
                self.template_editor.set_content(suggestion)
                self.status_var.set("AI suggestion applied to the template editor.")
                # Trigger a live update to see the new prompt preview
                self._schedule_live_update()
            else:
                custom_dialogs.show_error(self, "Suggestion Error", f"An error occurred while generating a suggestion:\n{result['error']}")
                self.status_var.set("Suggestion failed.")
        except queue.Empty:
            self.enhancement_suggestion_after_id = self.after(100, self._check_enhancement_suggestion_queue)

    def _create_wildcard_from_selection(self, selected_text: str):
        """Creates a new wildcard file from the selected text in the template editor."""
        # Suggest a filename based on the selection
        suggested_name = re.sub(r'\s+', '_', selected_text.strip()).lower()
        suggested_name = re.sub(r'[^a-z0-9_]', '', suggested_name)
        suggested_name = suggested_name[:50] # Truncate long names

        wildcard_name = custom_dialogs.ask_string(
            self,
            "Create New Wildcard",
            "Enter a name for the new wildcard (without .json):",
            initialvalue=suggested_name
        )

        if not wildcard_name:
            return

        # Create the initial JSON content
        initial_data = {"description": f"Wildcard created from template selection: '{selected_text}'", "choices": [selected_text]}
        initial_content_str = json.dumps(initial_data, indent=2)

        self.template_editor.insert_wildcard_tag(wildcard_name)
        self._open_wildcard_manager(initial_file=f"{wildcard_name}.json", initial_content=initial_content_str)

    def _handle_ai_content_update(self, content_type: str):
        """Callback for when AI generates a new file, to refresh UI lists."""
        if content_type == 'template':
            self._load_templates()
        self._populate_wildcard_lists()
        self._highlight_template_wildcards()
        self.status_var.set(f"New AI-generated {content_type} saved.")

    def _open_system_prompt_editor(self):
        """Opens the system prompt editor window."""
        SystemPromptEditorWindow(self, self.processor)

    def _change_ollama_server(self):
        """Opens a dialog to change the Ollama server URL."""
        current_url = config.OLLAMA_BASE_URL
        new_url = custom_dialogs.ask_string(
            self,
            "Ollama Server",
            "Enter the base URL for your Ollama server (e.g., http://192.168.1.100:11434):",
            initialvalue=current_url
        )

        if new_url and new_url.strip() and new_url.strip() != current_url:
            new_url = new_url.strip()
            # Test connection by trying to list models
            try:
                from core.ollama_client import OllamaClient
                test_client = OllamaClient(base_url=new_url)
                test_client.list_models() # This will raise an exception on failure
                
                # If successful, save and update
                config.OLLAMA_BASE_URL = new_url
                
                # Save the setting to file
                user_settings = load_settings()
                user_settings["ollama_base_url"] = new_url
                save_settings(user_settings)

                # Re-initialize the processor's client with the new URL
                self.processor.ollama_client = OllamaClient(base_url=new_url)
                self._load_models() # Reload models in the GUI
                custom_dialogs.show_info(self, "Success", f"Successfully connected to Ollama server at:\n{new_url}")
                self.status_var.set(f"Ollama server set to {new_url}")
            except Exception as e:
                custom_dialogs.show_error(self, "Connection Failed", f"Could not connect to Ollama server at:\n{new_url}\n\nError: {e}")

    def _handle_model_change(self, old_model: Optional[str], new_model: Optional[str]):
        """Manages the usage count of models and unloads them when no longer active."""
        if old_model:
            if old_model in self.active_models:
                self.active_models[old_model] -= 1
                if self.active_models[old_model] <= 0:
                    print(f"Model '{old_model}' is no longer active. Unloading in background...")
                    # We don't need to join this thread; it can clean up on its own.
                    # This prevents the UI from hanging if the unload takes time.
                    thread = threading.Thread(target=self.processor.cleanup_model, args=(old_model,), daemon=True)
                    thread.start()
                    del self.active_models[old_model]

        if new_model and "model" not in new_model.lower():
            self.active_models[new_model] = self.active_models.get(new_model, 0) + 1

    def _on_closing(self):
        """Handles the main window closing event to clean up resources."""
        if self.active_models:
            print(f"Unloading all active models: {', '.join(self.active_models.keys())}...")
            for model in list(self.active_models.keys()):
                self.processor.cleanup_model(model)
            print("Cleanup complete.")
        if self.enhancement_suggestion_after_id:
            self.after_cancel(self.enhancement_suggestion_after_id)
        self.destroy()