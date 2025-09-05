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
from core.config import config, save_settings, load_settings
from .enhancement_window import EnhancementResultWindow
from .brainstorming_window import BrainstormingWindow
from .action_bar import ActionBar
from .common import Tooltip, LoadingAnimation, TextContextMenu, TemplateEditorContextMenu, SmartWindowMixin, PromptPreviewContextMenu
from .history_viewer import HistoryViewerWindow
from .review_window import ReviewAndSaveWindow
from .system_prompt_editor import SystemPromptEditorWindow
from .settings_window import SettingsWindow
from .wildcard_manager import WildcardManagerWindow
from .prompt_evolver import PromptEvolverWindow
from .image_interrogator import ImageInterrogatorWindow
from .menu_bar import MenuBar
from .template_editor import TemplateEditor
from .wildcard_inserter import WildcardInserter
from . import custom_dialogs
from .model_usage_manager import ModelUsageManager
from core.ollama_client import OllamaClient
from .theme_manager import ThemeManager

         
class GUIApp(tk.Tk, SmartWindowMixin):
    """A GUI for the Stable Diffusion Prompt Generator."""

    def __init__(self, verbose: bool = False):
        super().__init__()
        if verbose:
            print("--- VERBOSE MODE ENABLED ---", flush=True)
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
        self.processor = PromptProcessor(verbose=verbose)
        self.processor.initialize()
        self.processor.set_callbacks(status_callback=self._update_status_bar_from_event)
        self.model_usage_manager = ModelUsageManager(self.processor)
        self.enhancement_total_calls = 0
        self.enhancement_calls_made = 0
        self.active_api_calls = 0
        self.enhancement_cancellation_event: Optional[threading.Event] = None

        # State
        self.current_template_content: Optional[str] = None
        self.current_template_file: Optional[str] = None
        self.last_generation_result: Dict[str, Any] = {}
        self.current_structured_prompt: List[PromptSegment] = []
        self.segment_map: List[Tuple[str, str, int]] = []  # start, end, segment_index
        self.wildcard_tooltip: Optional[Tooltip] = None
        self.wildcard_tooltip_after_id: Optional[str] = None
        self.last_hovered_segment_index: int = -1
        self.debounce_timer: Optional[str] = None
        self.main_window_model: Optional[str] = None
        self.brainstorming_window: Optional[BrainstormingWindow] = None
        self.wildcard_manager_window: Optional[WildcardManagerWindow] = None
        self.image_interrogator_window: Optional[ImageInterrogatorWindow] = None
        self.prompt_evolver_window: Optional[PromptEvolverWindow] = None
        self.history_viewer_window: Optional[HistoryViewerWindow] = None
        self.loading_animation: Optional[LoadingAnimation] = None
        self.template_editor: Optional[TemplateEditor] = None
        self.wildcard_inserter: Optional[WildcardInserter] = None
        self.menubar: Optional[MenuBar] = None
        self.wildcard_swap_menu: tk.Menu = tk.Menu(self, tearoff=0)
        self.settings_window: Optional[SettingsWindow] = None
        self.enhancement_model_var = tk.StringVar()
        self.font_size_var = tk.IntVar(value=config.font_size)
        self.workflow_var = tk.StringVar(value=config.workflow)
        self.enhancement_queue = queue.Queue()
        self.ai_cleanup_queue = queue.Queue()
        self.ai_cleanup_after_id: Optional[str] = None
        self.missing_wildcards_container: Optional[ttk.Frame] = None
        self.enhancement_windows: List[EnhancementResultWindow] = []
        self.main_image_gen_queue = queue.Queue()
        self.last_saved_entry_id_from_preview: Optional[str] = None
        self.main_image_gen_after_id: Optional[str] = None

        # Create widgets
        self._create_widgets()
        self.wildcard_tooltip = Tooltip(self.prompt_text)
        self._update_text_widget_colors() # Set initial theme-based colors
        self._load_templates()
        self._load_models()
        self._populate_wildcard_lists()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self._update_window_title() # Set initial title

        # Configure the switch style for the seed lock
        style = ttk.Style()
        style.configure('Switch.TCheckbutton',
                       font=self.small_font,
                       padding=2)

        # After creating all widgets, set smart geometry
        self.smart_geometry(min_width=900, min_height=700)

    def destroy(self):
        """
        Overrides the default destroy method to prevent the clipboard from being
        cleared on some platforms (Linux/macOS) when the app closes.
        """
        try:
            # This is a workaround. By appending the current clipboard content to itself
            # and then immediately processing events with update_idletasks, we can
            # encourage the window manager to take ownership of the clipboard
            # content before the application window is destroyed.
            self.clipboard_append(self.clipboard_get())
            self.update_idletasks()
        except tk.TclError:
            # This will happen if the clipboard is empty or contains non-string data.
            # In this case, there's nothing to preserve, so we can ignore it.
            pass
        
        # Now, call the original destroy method from the parent class.
        super().destroy()

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
        self.menubar = MenuBar(self)

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

    def _generate_new_template(self):
        """Opens a dialog to generate a new template with AI."""
        concept = custom_dialogs.ask_string(self, "Generate Template", "What kind of template would you like to generate?\n\nDescribe the concept:")
        if not concept:
            return

        # Open brainstorming window if not already open
        self._open_brainstorming_window()

        if self.brainstorming_window and self.brainstorming_window.winfo_exists():
            self.brainstorming_window.lift()
            self.brainstorming_window.focus_force()
            # Call the method to start generation
            self.brainstorming_window.generate_template_with_concept(concept)

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
            create_wildcard_callback=self._create_wildcard_from_selection,
            edit_wildcard_callback=self._edit_wildcard_file
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
        bottom_pane_container = ttk.Frame(v_pane)

        preview_pane = ttk.LabelFrame(bottom_pane_container, text="Generated Prompt (Wildcards are highlighted)", padding=5)
        preview_pane.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        self.prompt_text = tk.Text(preview_pane, wrap=tk.WORD, height=10, font=self.large_font, undo=True)
        self.prompt_text.pack(fill=tk.BOTH, expand=True)
        PromptPreviewContextMenu(self.prompt_text, self, self._generate_missing_wildcard, self._edit_wildcard_file)
        self.prompt_text.config(state=tk.DISABLED)

        # Configure tags and bindings for the interactive prompt text
        self.prompt_text.tag_configure("wildcard", relief="raised", borderwidth=1)
        self.prompt_text.tag_bind("wildcard", "<Motion>", self._schedule_wildcard_tooltip)
        self.prompt_text.tag_bind("wildcard", "<Leave>", self._hide_wildcard_tooltip)
        self.prompt_text.tag_bind("wildcard", "<Button-1>", self._on_wildcard_click)
        self.prompt_text.tag_configure("wildcard_hover")

        self.missing_wildcards_frame = ttk.LabelFrame(
            bottom_pane_container, 
            text="Missing Wildcards (Click to generate, right-click for more options)", 
            padding=5
        )
        # This frame is packed/unpacked dynamically by _check_and_display_missing_includes
        
        # Create a persistent container for the labels to flow nicely
        self.missing_wildcards_container = ttk.Frame(self.missing_wildcards_frame)
        self.missing_wildcards_container.pack(fill=tk.X)

        v_pane.add(bottom_pane_container, weight=3)

    def _create_action_bar(self, parent):
        """Creates the main action buttons at the bottom of the window."""
        self.action_bar = ActionBar(
            parent,
            generate_callback=self._generate_preview,
            enhance_callback=self._on_select_for_enhancement,
            copy_callback=self._copy_generated_prompt,
            save_as_template_callback=self._save_preview_as_template,
            ai_cleanup_callback=self._ai_cleanup_prompt,
            generate_image_callback=self._generate_image_from_preview
        )
        self._update_action_bar_variations()

        # Add compact seed management frame
        seed_frame = ttk.Frame(parent)
        seed_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        # Create a label with a small font
        ttk.Label(seed_frame, text="Seed:", font=self.small_font).pack(side=tk.LEFT)
        
        # Create a smaller entry for the seed
        self.seed_var = tk.StringVar()
        self.seed_var.set(str(random.randint(0, 2**32 - 1)))  # Start with a random seed
        seed_entry = ttk.Entry(seed_frame, textvariable=self.seed_var, width=12, font=self.small_font)
        seed_entry.pack(side=tk.LEFT, padx=(2, 5))
        
        # Add a small "🎲" button for new random seed
        dice_btn = ttk.Button(seed_frame, text="🎲", width=3, 
                             command=self._randomize_seed)
        dice_btn.pack(side=tk.LEFT)
        Tooltip(dice_btn, "Generate random seed")
        
        # Add a switch for locking instead of checkbox
        self.random_seed_var = tk.BooleanVar(value=True) # Start with random ON
        lock_switch = ttk.Checkbutton(seed_frame, text="Random", 
                                     variable=self.random_seed_var,
                                     style='Switch.TCheckbutton')
        lock_switch.pack(side=tk.LEFT, padx=5)
        Tooltip(lock_switch, "Use a new random seed for each generation. Turn off to use the specific seed in the box.")

    def _randomize_seed(self):
        """Generate and set a new random seed in the entry box."""
        self.seed_var.set(str(random.randint(0, 2**32 - 1)))

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

        # Notify open tool windows of the theme change
        if self.brainstorming_window and self.brainstorming_window.winfo_exists():
            self.brainstorming_window.update_theme()
        if self.wildcard_manager_window and self.wildcard_manager_window.winfo_exists():
            self.wildcard_manager_window.update_theme()

    def _update_text_widget_colors(self):
        """Updates colors for text widgets and tags based on the current theme."""
        is_dark = self.theme_manager.current_theme == "dark"

        # Define colors for light and dark modes
        wildcard_bg = "#3c4c5c" if is_dark else "#d8e9f3"
        wildcard_hover_bg = "#4a5e73" if is_dark else "#b8d9e3"
        included_wildcard_bg = "#2c503e" if is_dark else "#d8f3e9" # Muted green
        error_bg = "#6b2b2b" if is_dark else "#ffcccc" # Muted red
        ordering_error_bg = "#6b4226" if is_dark else "#ffe4b5" # Muted orange
        status_bar_dot_color = "lightgrey" if is_dark else "dimgray"
        status_bar_bg = self.cget('background')

        # Apply colors to tags
        self.prompt_text.tag_configure("wildcard", background=wildcard_bg)
        self.prompt_text.tag_configure("wildcard_hover", background=wildcard_hover_bg)
        self.prompt_text.tag_configure("included_wildcard", background=included_wildcard_bg)
        self.prompt_text.tag_configure("missing_wildcard", background=error_bg)
        self.template_editor.text_widget.tag_configure("missing_wildcard", background=error_bg)
        self.template_editor.text_widget.tag_configure("ordering_error", background=ordering_error_bg)

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
        
        # Force the UI to update the dropdown menu before any subsequent code tries to set its value.
        self.update_idletasks()
        
        # Prompt the user to make a selection
        self.template_var.set("Select a template")

    def _update_action_bar_variations(self):
        """Updates the variation checkboxes in the action bar based on the current workflow."""
        variations = self.processor.get_available_variations()
        self.action_bar.rebuild_variations(variations)

    def _load_models(self):
        """Loads available Ollama models into the dropdown menu."""
        try:
            models = self.processor.get_available_models()
            if not models:
                custom_dialogs.show_warning(
                    self,
                    "No Models Found",
                    "Successfully connected to Ollama, but no models were found.\n\n"
                    "Please pull a model using 'ollama run <model_name>' to enable AI features.")
                self.enhancement_model_var.set("No models available")
                return

            menu = self.model_dropdown["menu"]
            menu.delete(0, "end")
            for model in models:
                menu.add_command(label=model, command=lambda value=model: self.enhancement_model_var.set(value))

            # Set a default model by finding the highest-priority recommended model.
            recommendations = self.processor.get_model_recommendations(models)
            if recommendations:
                # The recommendations are sorted by priority. The first one is the best.
                # The tuple is (index, model_name, reason). We want the model name.
                default_model = recommendations[0][1]
            else:
                # Fallback if no models match our recommendation rules
                default_model = models[0]

            self.enhancement_model_var.set(default_model)
            
            # Register initial model usage
            self.main_window_model = default_model
            self.model_usage_manager.register_usage(self.main_window_model)

        except Exception as e:
            error_message = (
                f"Could not connect to the Ollama server.\n\n"
                f"All AI features (Enhancement, Brainstorming, etc.) will be disabled until the connection is restored.\n\n"
                f"Please ensure Ollama is running and the server URL is correct in 'Tools -> Settings...'.\n\n"
                f"Details: {e}"
            )
            custom_dialogs.show_error(self, "Ollama Connection Error", error_message)
            self.enhancement_model_var.set("Error: No connection")

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
        
        # Also close the prompt evolver as its data is now stale
        if self.prompt_evolver_window and self.prompt_evolver_window.winfo_exists():
            self.prompt_evolver_window.destroy()
            self.prompt_evolver_window = None

        self.status_var.set(f"Switched to {new_workflow.upper()} workflow. Select a template.")

    def _clear_template_view(self):
        """Resets the UI to a state where no template is loaded."""
        self.current_template_file = None
        self.current_template_content = None
        self.current_structured_prompt = []
        self.template_editor.clear()
        self.template_editor.set_label("Template Content") # This line is duplicated, but it's fine.
        self.last_saved_entry_id_from_preview = None
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.config(state=tk.DISABLED)
        self.action_bar.set_button_states(generate=tk.DISABLED, enhance=tk.DISABLED, copy=tk.DISABLED, save_as_template=tk.DISABLED, ai_cleanup=tk.DISABLED)
        self.menubar.update_file_menu_state(save_enabled=False, archive_enabled=False)
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
        old_model = self.main_window_model
        if new_model and "model" not in new_model.lower() and new_model != old_model:
            self.model_usage_manager.unregister_usage(old_model)
            self.model_usage_manager.register_usage(new_model)
            self.main_window_model = new_model
            # Notify the wildcard manager if it's open
            if self.wildcard_manager_window and self.wildcard_manager_window.winfo_exists():
                self.wildcard_manager_window.update_active_model(old_model, new_model)

    def _on_template_select(self, template_name: str):
        """Callback for when a template is selected from the dropdown."""
        self.current_template_file = template_name
        self.template_editor.set_label("Template Content") # Reset label

        # Load template content into both state and the template view
        self.current_template_content = self.processor.load_template_content(template_name)
        self.template_editor.set_content(self.current_template_content)
        self._highlight_template_wildcards()

        self.action_bar.set_button_states(generate=tk.NORMAL, enhance=tk.DISABLED, copy=tk.DISABLED, save_as_template=tk.DISABLED, ai_cleanup=tk.DISABLED)
        self.menubar.update_file_menu_state(save_enabled=True, archive_enabled=True)
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert(tk.END, f"Template '{template_name}' loaded. Click 'Generate Next Preview' to start.")
        self.prompt_text.config(state=tk.DISABLED)
        self.current_structured_prompt = []
        self.last_saved_entry_id_from_preview = None
        self.status_var.set(f"Loaded template: {template_name}")

    def _generate_preview(self):
        """Generates a single prompt and displays it in the text box."""
        # Get content directly from the live editor
        live_content = self.template_editor.get_content() # Get all text except the final newline
        if not live_content.strip():
            return

        seed = None
        # If random is on, generate a new seed and update the UI
        if self.random_seed_var.get():
            seed = random.randint(0, 2**32 - 1)
            self.seed_var.set(str(seed))
        else:
            # Otherwise, use the seed from the box
            try:
                seed = int(self.seed_var.get())
            except (ValueError, TypeError):
                seed = random.randint(0, 2**32 - 1)
                self.seed_var.set(str(seed))

        # Generate with fresh random wildcards
        segments, context = self.processor.generate_single_structured_prompt(
            live_content, existing_context=None, seed=seed
        )
        self.last_generation_result = {'segments': segments, 'context': context}
        self.current_structured_prompt = segments # Keep this for UI rendering
        self.last_saved_entry_id_from_preview = None
        self._update_prompt_preview()

    def _update_prompt_preview(self):
        """Update the prompt preview with the latest generation."""
        self._display_structured_prompt()
        self._check_and_display_missing_includes()
        is_prompt_available = bool(self.current_structured_prompt)
        self.action_bar.set_button_states(
            generate=tk.NORMAL, 
            enhance=tk.NORMAL if is_prompt_available else tk.DISABLED, 
            copy=tk.NORMAL if is_prompt_available else tk.DISABLED, 
            save_as_template=tk.NORMAL if is_prompt_available else tk.DISABLED,
            ai_cleanup=tk.NORMAL if is_prompt_available else tk.DISABLED,
            generate_image=tk.NORMAL if is_prompt_available and self.processor.is_invokeai_connected() else tk.DISABLED
        )

    def _display_structured_prompt(self):
        """Renders the structured prompt with highlighting."""
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.tag_remove("missing_wildcard", "1.0", tk.END)
        self.segment_map = []

        for i, segment in enumerate(self.current_structured_prompt):
            start = self.prompt_text.index(tk.INSERT)
            self.prompt_text.insert(tk.INSERT, segment.text)
            end = self.prompt_text.index(tk.INSERT)

            if segment.wildcard_name:
                tag_name = f"wildcard_{i}"
                self.prompt_text.tag_add(tag_name, start, end)
                # Add the base tag for functionality (hover, click)
                self.prompt_text.tag_add("wildcard", start, end)
                
                # Add a specific tag for styling based on its origin
                if segment.is_from_include:
                    self.prompt_text.tag_add("included_wildcard", start, end)

                self.segment_map.append((start, end, i))
                if segment.wildcard_name and segment.text == f"__{segment.wildcard_name}__":
                    self.prompt_text.tag_add("missing_wildcard", start, end)

        self.prompt_text.config(state=tk.DISABLED)

    def _schedule_wildcard_tooltip(self, event):
        """Schedules a tooltip to appear over a wildcard segment after a delay."""
        if self.wildcard_tooltip_after_id:
            self.after_cancel(self.wildcard_tooltip_after_id)

        # Find the segment under the cursor
        index_at_cursor = self.prompt_text.index(f"@{event.x},{event.y}")
        current_segment_index = -1
        for start, end, seg_index in self.segment_map:
            if self.prompt_text.compare(start, "<=", index_at_cursor) and self.prompt_text.compare(index_at_cursor, "<", end):
                current_segment_index = seg_index
                break

        if current_segment_index != self.last_hovered_segment_index:
            self._hide_wildcard_tooltip() # Hide immediately if moving to a new segment

        self.last_hovered_segment_index = current_segment_index

        if current_segment_index != -1:
            self.wildcard_tooltip_after_id = self.after(500, lambda: self._display_wildcard_tooltip(current_segment_index, event))

    def _display_wildcard_tooltip(self, segment_index: int, event):
        """Displays the tooltip for the specified wildcard segment."""
        wildcard_name = self.current_structured_prompt[segment_index].wildcard_name
        if self.wildcard_tooltip and wildcard_name:
            self.wildcard_tooltip.text = f"Source: {wildcard_name}.json"
            self.wildcard_tooltip.show(event)

    def _hide_wildcard_tooltip(self, event=None):
        """Hides the wildcard tooltip and cancels any scheduled appearance."""
        self.last_hovered_segment_index = -1
        if self.wildcard_tooltip_after_id:
            self.after_cancel(self.wildcard_tooltip_after_id)
            self.wildcard_tooltip_after_id = None
        if self.wildcard_tooltip:
            self.wildcard_tooltip.hide(event)
        self.prompt_text.tag_remove("wildcard_hover", "1.0", tk.END)

    def _on_wildcard_click(self, event):
        """Handle clicking on a wildcard tag."""
        # Find the segment that was clicked
        clicked_segment_index = -1
        # Use the event coordinates for a more reliable index
        index_at_click = self.prompt_text.index(f"@{event.x},{event.y}")
        for start, end, seg_index in self.segment_map:
            if self.prompt_text.compare(start, "<=", index_at_click) and self.prompt_text.compare(index_at_click, "<", end):
                clicked_segment_index = seg_index
                break

        if clicked_segment_index != -1:
            self._show_swap_menu(event, clicked_segment_index)
            return "break" # Prevent the default text selection behavior

    def _show_swap_menu(self, event, segment_index: int):
        """Display a context menu to swap the wildcard value."""
        segment = self.current_structured_prompt[segment_index]
        if not segment.wildcard_name:
            return

        options = self.processor.get_wildcard_options(segment.wildcard_name)
        if not options:
            return

        self.wildcard_swap_menu.delete(0, "end")
        for option in options:
            # Truncate long options for display in the menu
            display_option = (option[:75] + '...') if len(option) > 75 else option
            self.wildcard_swap_menu.add_command(
                label=display_option,
                command=lambda opt=option: self._swap_wildcard(segment_index, opt)
            )

        try:
            self.wildcard_swap_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.wildcard_swap_menu.grab_release()

    def _swap_wildcard(self, segment_index: int, new_value: str):
        """Swap the text of a wildcard segment and redisplay the prompt."""
        if not (0 <= segment_index < len(self.current_structured_prompt)):
            return

        segment = self.current_structured_prompt[segment_index]
        wildcard_to_swap = segment.wildcard_name
        if not wildcard_to_swap: return

        # We tell the live update function to force this wildcard to the new value.
        self._perform_live_update(force_swap={wildcard_to_swap: new_value})

    def _schedule_live_update(self, event=None, force_swap: Optional[Dict[str, str]] = None):
        """Schedules a live update of the prompt preview after a short delay."""
        if self.debounce_timer:
            self.after_cancel(self.debounce_timer)

        self.debounce_timer = self.after(500, self._perform_live_update)

    def _perform_live_update(self, force_reroll: Optional[List[str]] = None, force_swap: Optional[Dict[str, str]] = None):
        """Updates the prompt preview using the current template text and existing wildcards."""
        self.debounce_timer = None
        if not self.current_template_content:
            return
            
        live_content = self.template_editor.get_content()
        if not live_content.strip():
            return
            
        # For live updates (typing, swapping), ALWAYS use the seed currently in the box
        # to provide a stable editing experience.
        try:
            seed = int(self.seed_var.get())
        except (ValueError, TypeError):
            seed = random.randint(0, 2**32 - 1)
            self.seed_var.set(str(seed))

        # Get the existing context from the last generation result
        existing_context = self.last_generation_result.get('context')

        # Regenerate the prompt, reusing the existing wildcard choices
        segments, new_context = self.processor.generate_single_structured_prompt(
            live_content,
            existing_context=existing_context,
            force_reroll=force_reroll,
            force_swap=force_swap,
            seed=seed
        )
        self.last_generation_result = {'segments': segments, 'context': new_context}
        self.current_structured_prompt = segments
        self._update_prompt_preview()
        self._highlight_template_wildcards()
        if force_reroll:
            self.status_var.set(f"Wildcard '{force_reroll[0]}' updated.")
        else:
            self.status_var.set("Preview updated based on template changes.")

    def _check_and_display_missing_includes(self):
        """Checks the current prompt for missing 'included' wildcards and displays links to generate them."""
        all_includes = set()
        if self.current_structured_prompt:
            for segment in self.current_structured_prompt:
                if segment.includes:
                    if isinstance(segment.includes, list):
                        # It's a list of wildcard names
                        for included_wc in segment.includes:
                            all_includes.add(included_wc)
                    elif isinstance(segment.includes, str):
                        # It's a template string, find wildcards within it
                        found_wildcards = re.findall(r'__([a-zA-Z0-9_.\s-]+?)__', segment.includes)
                        all_includes.update(found_wildcards)

                # Also check if the segment itself represents a missing wildcard placeholder
                if segment.wildcard_name and segment.text == f"__{segment.wildcard_name}__":
                    all_includes.add(segment.wildcard_name)
        
        known_wildcards = set(self.processor.get_wildcard_names())
        missing_wildcards = sorted(list(all_includes - known_wildcards))

        # Clear any previously displayed widgets
        for widget in self.missing_wildcards_container.winfo_children():
            widget.destroy()

        if not missing_wildcards:
            self.missing_wildcards_frame.pack_forget()
            return

        # Show the frame and create new widgets
        self.missing_wildcards_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(5,0))
        ttk.Label(self.missing_wildcards_container, 
                 text="Missing wildcards: ", 
                 font=self.small_font).pack(side=tk.LEFT)
        
        for i, wc_name in enumerate(missing_wildcards):
            link = ttk.Label(self.missing_wildcards_container, 
                           text=wc_name,
                           foreground="orange",
                           cursor="hand2",
                           font=self.small_font)
            link.pack(side=tk.LEFT, padx=2)
            link.bind("<Button-1>", lambda e, name=wc_name: self._handle_missing_wildcard_click(name))
            link.bind("<Button-3>", lambda e, name=wc_name: self._show_missing_wildcard_menu(e, name))

            if i < len(missing_wildcards) - 1:
                ttk.Label(self.missing_wildcards_container, text=",", font=self.small_font).pack(side=tk.LEFT)

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

    def _save_preview_as_template(self):
        """Saves the content of the preview pane as a new template file."""
        prompt_text = self.prompt_text.get("1.0", "end-1c").strip()
        if not prompt_text:
            self.status_var.set("No prompt in preview to save.")
            return

        filename = custom_dialogs.ask_string(
            self,
            "Save as New Template",
            "Enter a filename for the new template:"
        )
        if not filename:
            return
        
        if not filename.endswith('.txt'):
            filename += '.txt'
        
        self.processor.save_template_content(filename, prompt_text)
        self._load_templates()
        self.template_var.set(filename) # This will trigger the update via trace
        self.status_var.set(f"Saved and loaded new template: {filename}")

    def _copy_generated_prompt(self):
        """Copies the current generated prompt text to the clipboard."""
        # If the structured prompt is empty, it means the preview pane is showing
        # a static prompt (e.g., after AI cleanup). In this case, get the text directly.
        if not self.current_structured_prompt:
            prompt_text = self.prompt_text.get("1.0", "end-1c").strip()
        else:
            # Otherwise, construct the string from the interactive segments.
            prompt_text = self._get_current_prompt_string()

        if not prompt_text:
            self.status_var.set("Nothing to copy.")
            return
        
        self.clipboard_clear()
        self.clipboard_append(prompt_text)
        self.status_var.set("Prompt copied to clipboard.")

    def _get_current_prompt_string(self) -> str:
        """
        Constructs the full prompt string from the current state (preview or editor)
        and runs it through the cleanup process.
        """
        if self.current_structured_prompt:
            # Reconstruct the full prompt string from segments
            raw_prompt = "".join(seg.text for seg in self.current_structured_prompt)
        else:
            # Get the prompt directly from the editor pane if no preview has been generated
            raw_prompt = self.template_editor.get_content().strip()
        
        return self.processor.cleanup_prompt_string(raw_prompt)

    def _on_select_for_enhancement(self):
        """Handles the 'Enhance This Prompt' button click."""
        prompt_text = self._get_current_prompt_string()
        template_name = self.current_template_file
        existing_entry_id = self.last_saved_entry_id_from_preview
        self.start_enhancement_for_prompt(prompt_text, template_name, existing_entry_id=existing_entry_id)
        self.last_saved_entry_id_from_preview = None # Consume the ID so it's not reused

    def start_enhancement_for_prompt(self, prompt_text: str, template_name: Optional[str] = None, existing_entry_id: Optional[str] = None):
        """Handles starting an enhancement process for a given prompt string."""
        model = self.enhancement_model_var.get()
        if not model or "model" in model.lower():
            custom_dialogs.show_error(self, "Error", "Please select a valid Ollama model first.")
            return
        
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
        result_window = EnhancementResultWindow(self, initial_data, self.processor, model, selected_variations, self._cancel_enhancement_batch, self.report_api_call_finished, existing_entry_id=existing_entry_id)
        self.enhancement_windows.append(result_window)

        # Define a thread-safe callback to update the results window
        def result_callback(key, data):
            result_window.result_queue.put((key, data))

        self.processor.set_callbacks(status_callback=self._update_status_bar_from_event, result_callback=result_callback)

        self.action_bar.select_button.config(state=tk.DISABLED)
        self.status_var.set(f"Enhancing prompt with {model}...")

        # Run enhancement in a separate thread to avoid freezing the GUI
        thread = threading.Thread(target=self._run_enhancement_thread, args=(prompt_text, model, selected_variations, self.enhancement_cancellation_event, template_name), daemon=True)
        thread.start()

    def _run_enhancement_thread(self, prompt: str, model: str, selected_variations: List[str], cancellation_event: threading.Event, template_name: Optional[str]):
        """The function that runs in a separate thread to process the prompt."""
        try:
            # This is now a fire-and-forget process from the GUI's perspective.
            # The processor will use callbacks to update the UI.
            self.processor.process_enhancement_batch([prompt], model, selected_variations, cancellation_event, template_name)
        except Exception as e:
            self.after(0, lambda err=e: custom_dialogs.show_error(self, "Enhancement Error", f"An error occurred during processing:\n{err}"))
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

        message = ""
        if event_type == 'enhancement_start':
            self.enhancement_calls_made += 1
            message = f"Enhancing main prompt... (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        elif event_type == 'variation_start':
            self.enhancement_calls_made += 1
            var_type = kwargs.get('var_type', 'unknown')
            message = f"Creating '{var_type}' variation... (call {self.enhancement_calls_made}/{self.enhancement_total_calls})"
        elif event_type == 'batch_complete':
            message = "Batch processing complete."
        elif event_type == 'batch_cancelled':
            message = "Processing cancelled."
        elif event_type == 'compatibility_check_step':
            step = kwargs.get('step', '?')
            total_steps = kwargs.get('total_steps', '?')
            step_message = kwargs.get('message', 'Processing...')
            message = f"Step {step}/{total_steps}: {step_message}"
        elif event_type == 'brainstorm_template_step':
            step = kwargs.get('step', '?')
            total_steps = kwargs.get('total_steps', '?')
            step_message = kwargs.get('message', 'Processing...')
            message = f"Generating Template (Step {step}/{total_steps}: {step_message})"
        else:
            # Fallback for simple status updates from the processor
            message = kwargs.get('message', event_type)
        
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

    def report_enhancement_window_closed(self, window: EnhancementResultWindow):
        """Callback for when an enhancement window is closed."""
        if window in self.enhancement_windows:
            self.enhancement_windows.remove(window)

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

    def _open_prompt_evolver(self):
        """Opens the Prompt Evolver window."""
        if self.prompt_evolver_window and self.prompt_evolver_window.winfo_exists():
            self.prompt_evolver_window.lift()
            self.prompt_evolver_window.focus_force()
        else:
            self.prompt_evolver_window = PromptEvolverWindow(self, self.processor, self.load_prompt_from_history)
            self.prompt_evolver_window.protocol("WM_DELETE_WINDOW", self._on_prompt_evolver_close)

    def _on_prompt_evolver_close(self):
        if self.prompt_evolver_window:
            self.prompt_evolver_window.close()
            self.prompt_evolver_window = None

    def _open_image_interrogator(self):
        """Opens the image interrogator window."""
        if self.image_interrogator_window and self.image_interrogator_window.winfo_exists():
            self.image_interrogator_window.lift()
            self.image_interrogator_window.focus_force()
        else:
            try:
                models = self.processor.get_available_models()
                default_model = self.enhancement_model_var.get()
                self.image_interrogator_window = ImageInterrogatorWindow(self, self.processor, models, default_model, self.load_prompt_from_history)
                self.image_interrogator_window.protocol("WM_DELETE_WINDOW", self._on_image_interrogator_close)
            except Exception as e:
                custom_dialogs.show_error(self, "Error", f"Could not open Image Interrogator:\n{e}")

    def _on_image_interrogator_close(self):
        if self.image_interrogator_window:
            self.image_interrogator_window.close()
            self.image_interrogator_window = None

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
        match = re.fullmatch(r'__([a-zA-Z0-9_.\s-]+)__', clicked_word)
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
            self.menubar.update_file_menu_state(save_enabled=False, archive_enabled=False)
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
                
                self.brainstorming_window = BrainstormingWindow(self, self.processor, models, default_model, self.model_usage_manager, self._handle_ai_content_update)
                self.brainstorming_window.protocol("WM_DELETE_WINDOW", self._on_brainstorming_window_close)
            except Exception as e:
                custom_dialogs.show_error(self, "Error", f"Could not open brainstorming window:\n{e}")

    def _on_brainstorming_window_close(self):
        if self.brainstorming_window:
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
        self.last_saved_entry_id_from_preview = None
        self.menubar.update_file_menu_state(save_enabled=False, archive_enabled=False)
        self.action_bar.generate_button.config(state=tk.DISABLED) # Can't generate from a non-template
        self.prompt_text.config(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.config(state=tk.DISABLED)

        # Load the historical prompt into the editable text area
        self.template_editor.set_label("Editable Prompt (from History)")
        self.template_editor.set_content(prompt_text)

        # Enable enhancement actions
        self.action_bar.set_button_states(generate=tk.DISABLED, enhance=tk.NORMAL, copy=tk.NORMAL, ai_cleanup=tk.NORMAL)
        self.status_var.set("Loaded prompt from history. Ready to enhance.")

    def _ai_cleanup_prompt(self):
        """Uses AI to clean up the currently generated prompt."""
        model = self.enhancement_model_var.get()
        if not model or "model" in model.lower():
            custom_dialogs.show_error(self, "Error", "Please select a valid Ollama model first.")
            return
        
        prompt_to_clean = self._get_current_prompt_string()
        if not prompt_to_clean:
            custom_dialogs.show_error(self, "Error", "No prompt to clean up.")
            return

        self.action_bar.ai_cleanup_button.config(state=tk.DISABLED, text="Cleaning...")
        self.loading_animation.start()

        def task():
            try:
                cleaned_prompt = self.processor.ai_cleanup_prompt(prompt_to_clean, model)
                self.ai_cleanup_queue.put({'success': True, 'prompt': cleaned_prompt})
            except Exception as e:
                self.ai_cleanup_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.ai_cleanup_after_id = self.after(100, self._check_ai_cleanup_queue)

    def _generate_image_from_preview(self):
        """Generates an image from the current prompt preview."""
        prompt = self._get_current_prompt_string()
        if not prompt:
            custom_dialogs.show_error(self, "Error", "No prompt in preview to generate an image from.")
            return

        try:
            from .image_generation_dialog import ImageGenerationOptionsDialog
            dialog = ImageGenerationOptionsDialog(self, self.processor.invokeai_client, initial_negative_prompt=config.DEFAULT_NEGATIVE_PROMPT)
            options = dialog.result
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not open image generation options:\n{e}")
            return

        if not options:
            return # User cancelled

        self.action_bar.generate_image_button.config(state=tk.DISABLED, text="Generating...")

        def task():
            try:
                seed = random.randint(0, 2**32 - 1)
                gen_args = {
                    "prompt": prompt,
                    "negative_prompt": options["negative_prompt"],
                    "seed": seed,
                    "model_object": options["model"],
                    "loras": options["loras"],
                    "steps": options["steps"],
                    "cfg_scale": options["cfg_scale"],
                    "scheduler": options["scheduler"],
                }
                image_bytes = self.processor.generate_image_with_invokeai(**gen_args)
                self.main_image_gen_queue.put({'success': True, 'bytes': image_bytes, 'prompt': prompt, 'generation_params': options})
            except Exception as e:
                self.main_image_gen_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.main_image_gen_after_id = self.after(100, self._check_main_image_gen_queue)

    def _check_main_image_gen_queue(self):
        """Checks for image generation results from the main window."""
        try:
            result = self.main_image_gen_queue.get_nowait()
            self.action_bar.generate_image_button.config(state=tk.NORMAL, text="Generate Image")

            if result['success']:
                from .image_preview_dialog import ImagePreviewDialog
                preview_dialog = ImagePreviewDialog(self, result['bytes'], result['prompt'])
                if preview_dialog.result: # User clicked "Save to History"
                    image_path = self.processor.save_generated_image(result['bytes'])
                    entry = {'original_prompt': result['prompt'], 'status': 'generated_only', 'original_image_path': image_path, 'original_generation_params': result.get('generation_params'), 'template_name': self.current_template_file}
                    saved_entry = self.processor.history_manager.save_result(**entry)
                    if saved_entry:
                        self.last_saved_entry_id_from_preview = saved_entry.get('id')
                    custom_dialogs.show_info(self, "Image Saved", "Image and prompt saved to history.")
            else:
                custom_dialogs.show_error(self, "Image Generation Error", f"Failed to generate image:\n{result['error']}")
        except queue.Empty:
            self.main_image_gen_after_id = self.after(100, self._check_main_image_gen_queue)

    def _check_ai_cleanup_queue(self):
        """Checks for results from the AI cleanup thread."""
        try:
            result = self.ai_cleanup_queue.get_nowait()
            self.loading_animation.stop()
            self.action_bar.ai_cleanup_button.config(state=tk.NORMAL, text="AI Cleanup ✨")

            if result['success']:
                cleaned_prompt = result['prompt']
                
                # The cleanup action invalidates the structured prompt, as the text has changed.
                # We display the cleaned text as a final, static result.
                self.current_structured_prompt = []
                self.segment_map = []
                
                self.prompt_text.config(state=tk.NORMAL)
                self.prompt_text.delete("1.0", tk.END)
                self.prompt_text.insert("1.0", cleaned_prompt)
                self.prompt_text.config(state=tk.DISABLED)
                
                # The user can now copy or enhance this final prompt.
                # The "Generate" button remains active to create a new preview from the original template.
                self.action_bar.set_button_states(generate=tk.NORMAL, enhance=tk.NORMAL, copy=tk.NORMAL, save_as_template=tk.NORMAL, ai_cleanup=tk.NORMAL)
                
                self.status_var.set("Prompt cleaned up by AI.")
            else:
                custom_dialogs.show_error(self, "AI Cleanup Error", f"An error occurred during cleanup:\n{result['error']}")
                self.status_var.set("AI cleanup failed.")
        except queue.Empty:
            self.ai_cleanup_after_id = self.after(100, self._check_ai_cleanup_queue)
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
        
        # Get the current template content to provide context to the AI
        template_context = self.template_editor.get_content().strip()

        # Open brainstorming window if not already open
        self._open_brainstorming_window()
        
        if self.brainstorming_window and self.brainstorming_window.winfo_exists():
            self.brainstorming_window.lift()
            self.brainstorming_window.focus_force()
            # Call the method to start generation, passing the original name as the filename
            # and the template content as context.
            self.brainstorming_window.generate_wildcard_with_topic(
                topic, 
                filename=wildcard_name,
                template_context=template_context
            )

    def _suggest_template_additions(self):
        """Asks the AI to suggest additions for the current prompt template."""
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
                suggestion = self.processor.suggest_template_additions(prompt_text, model)
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
                suggestion = result.get('suggestion', '').strip()
                if suggestion:
                    current_content = self.template_editor.get_content().strip()
                    # Add a comma and space if needed
                    if current_content and not current_content.endswith(','):
                        separator = ", "
                    else:
                        separator = " " if current_content else ""
                    
                    new_content = current_content + separator + suggestion
                    self.template_editor.set_content(new_content)
                    self.status_var.set("AI suggestions appended to the template.")
                    self._schedule_live_update() # Trigger a live preview update
                else:
                    self.status_var.set("AI returned no suggestions.")
            else:
                custom_dialogs.show_error(self, "Suggestion Error", f"An error occurred while generating a suggestion:\n{result['error']}")
                self.status_var.set("Suggestion failed.")
        except queue.Empty:
            self.enhancement_suggestion_after_id = self.after(100, self._check_enhancement_suggestion_queue)

    def _generate_template_from_all_wildcards(self):
        """Asks for a theme and generates a template using all available wildcards."""
        theme = custom_dialogs.ask_string(self, "Generate Template from Wildcards", "Enter a theme or concept for the new template:")
        if not theme:
            return

        model = self.enhancement_model_var.get()
        if not model or "model" in model.lower():
            custom_dialogs.show_error(self, "Error", "Please select a valid Ollama model first.")
            return

        self.status_var.set(f"Generating template for '{theme}' using all wildcards...")
        self.loading_animation.start()

        def task():
            try:
                template_content = self.processor.generate_template_from_all_wildcards(model, theme)
                self.generate_from_wildcards_queue.put({'success': True, 'template': template_content, 'theme': theme})
            except Exception as e:
                self.generate_from_wildcards_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.generate_from_wildcards_after_id = self.after(100, self._check_generate_from_wildcards_queue)

    def _check_generate_from_wildcards_queue(self):
        """Checks for the result of the template generation and opens the review window."""
        try:
            result = self.generate_from_wildcards_queue.get_nowait()
            self.loading_animation.stop()
            self.status_var.set("Ready")

            if result['success']:
                template_content = result.get('template', '')
                theme = result.get('theme', 'new_template')
                suggested_filename = re.sub(r'\s+', '_', theme.strip()).lower()
                suggested_filename = re.sub(r'[^a-z0-9_]', '', suggested_filename)
                
                ReviewAndSaveWindow(self, self.processor, content_type='template', generated_content=template_content, update_callback=self._handle_ai_content_update, filename=f"{suggested_filename}.txt")
            else:
                custom_dialogs.show_error(self, "Generation Error", f"An error occurred while generating the template:\n{result['error']}")
        except queue.Empty:
            self.generate_from_wildcards_after_id = self.after(100, self._check_generate_from_wildcards_queue)

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

    def _clear_wildcard_cache(self):
        """Clears the wildcard cache and reloads all wildcard-dependent UI components."""
        if not custom_dialogs.ask_yes_no(
            self,
            "Confirm Clear Cache",
            "Are you sure you want to clear the wildcard cache?\n\n"
            "This will force the application to re-read all wildcard files from disk. "
            "This can be useful for troubleshooting if wildcards seem out of date."
        ):
            return

        try:
            # The processor method handles both clearing and reloading.
            self.processor.clear_wildcard_cache_and_reload()
            
            # Refresh UI components that depend on wildcards.
            self._populate_wildcard_lists()
            
            # If the wildcard manager is open, it also needs to be refreshed.
            if self.wildcard_manager_window and self.wildcard_manager_window.winfo_exists():
                self.wildcard_manager_window._populate_wildcard_list()
                self.wildcard_manager_window._clear_editor_view()

            custom_dialogs.show_info(self, "Success", "Wildcard cache has been cleared and reloaded.")
            self.status_var.set("Wildcard cache cleared and reloaded.")
        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Failed to clear wildcard cache:\n{e}")

    def _open_settings_window(self):
        """Opens the application settings window."""
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
        else:
            self.settings_window = SettingsWindow(self, on_save_callback=self._on_settings_saved)
            self.settings_window.protocol("WM_DELETE_WINDOW", self._on_settings_window_close)

    def _on_settings_window_close(self):
        if self.settings_window:
            self.settings_window.destroy()
            self.settings_window = None

    def _on_settings_saved(self):
        """Called when settings are saved, to reload necessary resources."""
        # Re-initialize the processor's client with the new URL from the global config
        # which was updated by the settings window.
        self.processor.ollama_client = OllamaClient(base_url=config.OLLAMA_BASE_URL)
        self.processor.invokeai_client = self.processor.invokeai_client.__class__(base_url=config.INVOKEAI_BASE_URL)
        
        # Re-initialize other parts of the processor that depend on paths
        self.processor.initialize()
        
        # Reload UI components that depend on the new settings
        self._load_templates()
        self._populate_wildcard_lists()
        self._load_models() # Reload models in case the server changed

    def _on_closing(self):
        """Handles the main window closing event to clean up resources."""
        # Explicitly close child windows first to allow them to unregister their models.
        # This prevents the main window from prematurely unloading a model that's still
        # in use by a tool window.
        if self.wildcard_manager_window and self.wildcard_manager_window.winfo_exists():
            self.wildcard_manager_window.close()
        if self.brainstorming_window and self.brainstorming_window.winfo_exists():
            self.brainstorming_window.close()
        for window in list(self.enhancement_windows):
            if window.winfo_exists():
                window.close()
        active_models_on_exit = self.model_usage_manager.get_active_models()
        if active_models_on_exit:
            print(f"Unloading all active models: {', '.join(active_models_on_exit)}...")
            for model in active_models_on_exit:
                self.processor.cleanup_model(model)
            print("Cleanup complete.")
        if self.debounce_timer:
            self.after_cancel(self.debounce_timer)
        if self.ai_cleanup_after_id:
            self.after_cancel(self.ai_cleanup_after_id)
        if self.main_image_gen_after_id:
            self.after_cancel(self.main_image_gen_after_id)
        if self.last_saved_entry_id_from_preview:
            self.last_saved_entry_id_from_preview = None
        self.destroy()

    def _show_missing_wildcard_menu(self, event, wildcard_name: str):
        """Shows a context menu for missing wildcard actions."""
        menu = tk.Menu(self, tearoff=0)
        
        # Add menu items
        menu.add_command(
            label=f"Generate '{wildcard_name}' with AI",
            command=lambda: self._generate_missing_wildcard(wildcard_name)
        )
        menu.add_command(
            label=f"Create '{wildcard_name}' manually",
            command=lambda: self._create_empty_wildcard(wildcard_name)
        )
        menu.add_separator()
        menu.add_command(
            label="Open Wildcard Manager",
            command=lambda: self._open_wildcard_manager(f"{wildcard_name}.json")
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _handle_missing_wildcard_click(self, wildcard_name: str):
        """Handles click on a missing wildcard link."""
        if not custom_dialogs.ask_yes_no(
            self,
            "Generate Wildcard",
            f"Would you like to generate content for the missing wildcard '{wildcard_name}'?\n\n"
            f"Click 'Yes' to generate with AI\n"
            f"Click 'No' to create manually"
        ):
            self._create_empty_wildcard(wildcard_name)
        else:
            self._generate_missing_wildcard(wildcard_name)

    def _create_empty_wildcard(self, wildcard_name: str):
        """Creates an empty wildcard file with basic structure."""
        initial_data = {
            "description": f"Wildcard file for {wildcard_name}",
            "choices": ["Sample choice 1", "Sample choice 2"]
        }
        initial_content = json.dumps(initial_data, indent=2)
        self._open_wildcard_manager(f"{wildcard_name}.json", initial_content)

    def _edit_wildcard_file(self, wildcard_name: str):
        """Opens the wildcard manager to edit a specific wildcard file."""
        if not wildcard_name:
            return
        self._open_wildcard_manager(initial_file=f"{wildcard_name}.json")