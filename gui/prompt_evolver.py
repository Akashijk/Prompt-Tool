"""A window for 'breeding' new prompts from existing ones in the history."""

import tkinter as tk
import os
import tkinter.font as tkfont
import sys
from tkinter import ttk
import re
import queue
import threading
import copy
from typing import Optional, List, Callable, TYPE_CHECKING, Dict, Any
from PIL import Image, ImageTk

from .common import SmartWindowMixin
from core.config import config
from . import custom_dialogs

if TYPE_CHECKING:
    from .gui_app import GUIApp
    from core.prompt_processor import PromptProcessor

class PromptEvolverWindow(tk.Toplevel, SmartWindowMixin):
    """A window for 'breeding' new prompts from existing ones."""
    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor', load_prompt_callback: Callable):
        super().__init__(parent)
        self.title("Prompt Evolver")
        self.parent_app = parent
        self.processor = processor
        self.load_prompt_callback = load_prompt_callback
        self.history_data: List[Dict[str, str]] = []
        self.generation_queue = queue.Queue()
        self.child_image_gen_spinners: Dict[str, 'LoadingAnimation'] = {}
        self.parent_widgets: List[Dict[str, Any]] = [] # To hold {'label': widget, 'prompt': text, 'selected': bool}
        self.child_widgets: List[Dict[str, Any]] = [] # To hold {'label': widget, 'prompt': text, 'selected': bool}
        self.after_id: Optional[str] = None
        self.history_context_menu = tk.Menu(self, tearoff=0)
        self.parent_context_menu = tk.Menu(self, tearoff=0)
        self.child_context_menu = tk.Menu(self, tearoff=0)

        # Model management
        self.model_usage_manager = self.parent_app.model_usage_manager
        self.active_model = self.parent_app.enhancement_model_var.get()
        self.model_usage_manager.register_usage(self.active_model)

        self._create_widgets()
        self.refresh_data() # Initial population
        self.smart_geometry(min_width=1200, min_height=700)

        # Define a custom style for selected labels
        style = ttk.Style()
        is_dark = self.parent_app.theme_manager.current_theme == "dark"
        # Use theme-appropriate selection colors
        selected_bg = '#4a90e2' if is_dark else '#3399ff'
        selected_fg = 'white' # This is fine for both themes
        nsfw_color = "#F08080" if is_dark else "red"
        favorite_color = "#FFD700" # Gold looks good on both

        style.configure("Selected.TLabel", background=selected_bg, foreground=selected_fg)
        style.configure("Grooved.TLabel", borderwidth=1, relief="groove", padding=5)
        style.configure("Selected.Grooved.TLabel", borderwidth=1, relief="groove", padding=5, background=selected_bg, foreground=selected_fg)
        style.configure("History.TFrame")
        style.configure("SFW.History.TLabel", foreground="gray")
        style.configure("NSFW.History.TLabel", foreground=nsfw_color)
        style.configure("Favorite.History.TLabel", font=tkfont.Font(family="Helvetica", size=config.font_size, weight="bold"), foreground=favorite_color)
        style.configure("Prompt.History.TLabel")

    def _on_history_mouse_wheel(self, event):
        delta = -1 * (event.delta if sys.platform == 'darwin' else event.delta // 120)
        self.history_canvas.yview_scroll(delta, "units")

    def _on_parents_mouse_wheel(self, event):
        delta = -1 * (event.delta if sys.platform == 'darwin' else event.delta // 120)
        self.parents_canvas.yview_scroll(delta, "units")

    def _on_children_mouse_wheel(self, event):
        delta = -1 * (event.delta if sys.platform == 'darwin' else event.delta // 120)
        self.children_canvas.yview_scroll(delta, "units")

    def close(self):
        """Safely close the window, cancelling any pending after() jobs."""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.model_usage_manager.unregister_usage(self.active_model)
        self.destroy()

    def refresh_data(self):
        """Reloads history data and repopulates the listbox."""
        all_history = self.processor.get_all_history_across_workflows()
        if self.parent_app.workflow_var.get() == 'sfw':
            self.history_data = [item for item in all_history if item.get('workflow_source') == 'SFW']
        else: # nsfw mode shows both
            self.history_data = all_history
        self._populate_history_list()
        self.update_idletasks() # Ensure canvas is ready before configuring scroll region

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Main horizontal pane
        h_pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        h_pane.pack(fill=tk.BOTH, expand=True)

        # Left pane: History
        history_frame = ttk.LabelFrame(h_pane, text="Prompt History (Double-click to add as parent)", padding=5)
        self.history_canvas = tk.Canvas(history_frame, borderwidth=0)
        history_scrollbar = ttk.Scrollbar(history_frame, orient="vertical", command=self.history_canvas.yview)
        self.history_container = ttk.Frame(self.history_canvas)
        self.history_canvas.configure(yscrollcommand=history_scrollbar.set)
        history_scrollbar.pack(side="right", fill="y")
        self.history_canvas.pack(side="left", fill="both", expand=True)
        history_canvas_frame = self.history_canvas.create_window((0, 0), window=self.history_container, anchor="nw")

        def on_history_frame_configure(event):
            self.history_canvas.configure(scrollregion=self.history_canvas.bbox("all"))

        def on_history_canvas_configure(event):
            self.history_canvas.itemconfig(history_canvas_frame, width=event.width)
            for child in self.history_container.winfo_children():
                # The prompt label is the one that expands to fill the space.
                for label in child.winfo_children():
                    if isinstance(label, ttk.Label) and label.pack_info().get('expand'):
                        label.configure(wraplength=event.width - 60)

        self.history_container.bind("<Configure>", on_history_frame_configure)
        self.history_canvas.bind("<Configure>", on_history_canvas_configure)
        self.history_canvas.bind("<MouseWheel>", self._on_history_mouse_wheel)
        self.history_container.bind("<MouseWheel>", self._on_history_mouse_wheel)
        h_pane.add(history_frame, weight=2)

        # Right pane: Evolution Area
        evolution_frame = ttk.Frame(h_pane)
        h_pane.add(evolution_frame, weight=3)

        # Parents Area
        parents_frame = ttk.LabelFrame(evolution_frame, text="Parent Prompts (Click to select, press Delete to remove)", padding=5)
        parents_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 5))
        self.parents_canvas = tk.Canvas(parents_frame, borderwidth=0)
        parents_scrollbar = ttk.Scrollbar(parents_frame, orient="vertical", command=self.parents_canvas.yview)
        self.parents_container = ttk.Frame(self.parents_canvas)
        self.parents_canvas.configure(yscrollcommand=parents_scrollbar.set)
        parents_scrollbar.pack(side="right", fill="y")
        self.parents_canvas.pack(side="left", fill="both", expand=True)
        parents_canvas_frame = self.parents_canvas.create_window((0, 0), window=self.parents_container, anchor="nw")

        # --- Controls (now in the middle) ---
        control_frame = ttk.Frame(evolution_frame, padding=(0, 5, 0, 5))
        control_frame.pack(side=tk.TOP, fill=tk.X)

        def on_parents_frame_configure(event):
            self.parents_canvas.configure(scrollregion=self.parents_canvas.bbox("all"))

        def on_parents_canvas_configure(event):
            self.parents_canvas.itemconfig(parents_canvas_frame, width=event.width)
            for widget_info in self.parent_widgets:
                widget_info['label'].configure(wraplength=event.width - 15)

        self.parents_container.bind("<Configure>", on_parents_frame_configure)
        self.parents_canvas.bind("<Configure>", on_parents_canvas_configure)
        self.parents_canvas.bind("<MouseWheel>", self._on_parents_mouse_wheel)
        self.parents_container.bind("<MouseWheel>", self._on_parents_mouse_wheel)
        # Bind delete key to the canvas. It must have focus to receive the event.
        self.parents_canvas.bind("<FocusIn>", lambda e: self.parents_canvas.focus_set())
        self.parents_canvas.bind("<Delete>", self._remove_selected_parents)
        self.parents_canvas.bind("<BackSpace>", self._remove_selected_parents)

        # Children Area
        children_frame = ttk.LabelFrame(evolution_frame, text="Child Prompts (Generated, click to select)", padding=5)
        children_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(5, 0))
        
        # Create a canvas and a scrollbar for a scrollable list of labels
        self.children_canvas = tk.Canvas(children_frame, borderwidth=0)
        scrollbar = ttk.Scrollbar(children_frame, orient="vertical", command=self.children_canvas.yview)
        self.children_container = ttk.Frame(self.children_canvas)

        self.children_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.children_canvas.pack(side="left", fill="both", expand=True)
        canvas_frame = self.children_canvas.create_window((0, 0), window=self.children_container, anchor="nw")

        def on_frame_configure(event):
            self.children_canvas.configure(scrollregion=self.children_canvas.bbox("all"))

        def on_canvas_configure(event):
            self.children_canvas.itemconfig(canvas_frame, width=event.width)
            for widget_info in self.child_widgets:
                widget_info['label'].configure(wraplength=event.width - 15)

        self.children_container.bind("<Configure>", on_frame_configure)
        self.children_canvas.bind("<Configure>", on_canvas_configure)

        self.children_canvas.bind("<MouseWheel>", self._on_children_mouse_wheel)
        self.children_container.bind("<MouseWheel>", self._on_children_mouse_wheel)

        # --- Breed Button and Spinner ---
        breed_frame = ttk.Frame(control_frame)
        breed_frame.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        from .common import LoadingAnimation # Local import
        self.breed_spinner = LoadingAnimation(breed_frame, size=20)
        # Don't pack spinner yet

        self.breed_button = ttk.Button(breed_frame, text="Breed Prompts", command=self._breed_prompts, style="Accent.TButton")
        self.breed_button.pack(side=tk.LEFT, expand=True, fill=tk.X)

        self.use_as_parents_button = ttk.Button(control_frame, text="Use Selected Children as New Parents", command=self._use_children_as_parents)
        self.use_as_parents_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        self.send_to_editor_button = ttk.Button(control_frame, text="Send Selected Child to Main Editor", command=self._send_to_editor)
        self.send_to_editor_button.pack(side=tk.LEFT, expand=True, fill=tk.X)

    def _populate_history_list(self):
        for widget in self.history_container.winfo_children():
            widget.destroy()

        if not self.history_data:
            ttk.Label(self.history_container, text="No prompt history found.", padding=10).pack()
            return
        
        current_width = self.history_canvas.winfo_width()

        for i, item in enumerate(self.history_data):
            prompt_text = item.get('enhanced', {}).get('prompt') or item.get('original_prompt', '')
            if not prompt_text: continue # Skip empty history entries

            # --- Find the cover image for the thumbnail ---
            cover_image_path = None
            image_lists_to_check = []
            if item.get('original_images'): image_lists_to_check.append(item['original_images'])
            if item.get('enhanced', {}).get('images'): image_lists_to_check.append(item['enhanced']['images'])
            for var_data in item.get('variations', {}).values():
                if var_data.get('images'): image_lists_to_check.append(var_data['images'])

            for img_list in image_lists_to_check:
                for img_data in img_list:
                    if img_data.get('is_cover_image'):
                        cover_image_path = img_data.get('image_path')
                        break
                if cover_image_path: break
            
            # Fallback to the first image of any kind if no cover is set
            if not cover_image_path and image_lists_to_check:
                first_list = image_lists_to_check[0]
                if first_list:
                    cover_image_path = first_list[0].get('image_path')

            workflow_tag = item.get('workflow_source', 'N/A')
            is_favorite = item.get('favorite', False)
            
            # Create a frame for each history item for better layout and binding
            item_frame = ttk.Frame(self.history_container, style="History.TFrame", relief="groove", borderwidth=1, padding=5)
            item_frame.pack(fill=tk.X, pady=2, padx=2)

            thumb_label = ttk.Label(item_frame, text="🖼️", width=12, anchor=tk.CENTER)
            thumb_label.pack(side=tk.LEFT, padx=5, pady=5)
            if cover_image_path:
                self._load_history_thumbnail(thumb_label, cover_image_path, workflow_tag)

            # Create and pack the prefix label
            prefix_style = "SFW.History.TLabel" if workflow_tag == "SFW" else "NSFW.History.TLabel"
            prefix_label = ttk.Label(item_frame, text=f"[{workflow_tag}] ", style=prefix_style)
            prefix_label.pack(side=tk.LEFT)

            prompt_style = "Favorite.History.TLabel" if is_favorite else "Prompt.History.TLabel"
            prompt_label = ttk.Label(item_frame, text=prompt_text, style=prompt_style, wraplength=current_width - 60)
            prompt_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # Bind events to the frame and its labels
            right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
            for widget in [item_frame, prefix_label, prompt_label]:
                widget.bind("<Double-1>", lambda e, history_item=item: self._add_history_item_to_parents(history_item))
                widget.bind("<MouseWheel>", self._on_history_mouse_wheel)
                widget.bind(right_click_event, lambda e, item=item: self._show_history_context_menu(e, item))

    def _load_history_thumbnail(self, label_widget: ttk.Label, image_path: str, workflow: str):
        """Loads a thumbnail for the history list, handling potential errors."""
        try:
            # Temporarily set config to get the correct path
            original_workflow = config.workflow
            config.workflow = workflow.lower()
            full_path = os.path.join(config.get_history_file_dir(), image_path)
            config.workflow = original_workflow # Restore it immediately

            if not os.path.exists(full_path):
                label_widget.config(text="Not\nFound")
                return

            img = Image.open(full_path)
            img.thumbnail((96, 96))
            img_ref = ImageTk.PhotoImage(img)
            label_widget.config(image=img_ref, text="")
            label_widget.image = img_ref  # Keep a reference
        except Exception:
            label_widget.config(text="Load\nError")

    def _add_parent_widget(self, prompt_text: str):
        """Helper to create and add a new parent widget."""
        # Check for duplicates
        if any(p['prompt'] == prompt_text for p in self.parent_widgets):
            return

        label = ttk.Label(self.parents_container, text=prompt_text, style="Grooved.TLabel", wraplength=self.parents_canvas.winfo_width() - 15)
        label.pack(fill=tk.X, pady=2, padx=2)
        widget_info = {'label': label, 'prompt': prompt_text, 'selected': False}
        self.parent_widgets.append(widget_info)
        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        label.bind("<Button-1>", lambda e, info=widget_info: self._toggle_parent_selection(info))
        label.bind("<MouseWheel>", self._on_parents_mouse_wheel)
        label.bind(right_click_event, lambda e, info=widget_info: self._show_parent_context_menu(e, info))

    def _add_history_item_to_parents(self, history_item: Dict[str, Any]):
        full_prompt = history_item.get('enhanced', {}).get('prompt') or history_item.get('original_prompt', '')
        if full_prompt:
            self._add_parent_widget(full_prompt)

    def _toggle_parent_selection(self, widget_info: Dict[str, Any]):
        """Toggles the selection state of a parent prompt label."""
        widget_info['selected'] = not widget_info['selected']
        if widget_info['selected']:
            widget_info['label'].configure(style="Selected.Grooved.TLabel")
        else:
            widget_info['label'].configure(style="Grooved.TLabel")
        self.parents_canvas.focus_set() # Set focus to receive key events

    def _remove_selected_parents(self, event=None):
        # Iterate backwards to safely remove items from the list
        for widget_info in reversed(self.parent_widgets):
            if widget_info['selected']:
                widget_info['label'].destroy()
                self.parent_widgets.remove(widget_info)

    def _breed_prompts(self):
        parent_prompts = [p['prompt'] for p in self.parent_widgets]
        if len(parent_prompts) < 2:
            custom_dialogs.show_warning(self, "Not Enough Parents", "Please select at least two parent prompts.")
            return

        model = self.parent_app.enhancement_model_var.get()
        if not model or "model" in model.lower():
            custom_dialogs.show_error(self, "Model Error", "Please select a valid Ollama model in the main window.")
            return
            
        num_children = custom_dialogs.ask_string(self, "Number of Children", "How many child prompts should be generated?", initialvalue="5")
        if not num_children or not num_children.isdigit() or int(num_children) == 0:
            return

        self.breed_button.config(state=tk.DISABLED)
        self.breed_spinner.pack(side=tk.LEFT, padx=(0, 5))
        self.breed_spinner.start()

        # Clear old widgets and add a placeholder
        for widget_info in self.child_widgets:
            widget_info['label'].destroy()
        self.child_widgets.clear()
        placeholder = ttk.Label(self.children_container, text="Generating with AI...", style="TLabel", padding=10)
        placeholder.pack(fill=tk.X, pady=2, padx=2)
        self.child_widgets.append({'label': placeholder, 'prompt': '', 'selected': False})

        def task():
            try:
                child_prompts = self.processor.ai_breed_prompts(parent_prompts, int(num_children), model)
                self.generation_queue.put({'success': True, 'prompts': child_prompts})
            except Exception as e:
                self.generation_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_queue)

    def _toggle_child_selection(self, widget_info: Dict[str, Any]):
        """Toggles the selection state of a child prompt label."""
        widget_info['selected'] = not widget_info['selected']
        if widget_info['selected']:
            widget_info['label'].configure(style="Selected.Grooved.TLabel")
        else:
            widget_info['label'].configure(style="Grooved.TLabel")

    def _check_queue(self):
        try:
            result = self.generation_queue.get_nowait()
            self.breed_button.config(state=tk.NORMAL)
            self.breed_spinner.stop()
            self.breed_spinner.pack_forget()
            
            # Clear placeholder/old content
            for widget_info in self.child_widgets:
                widget_info['label'].destroy()
            self.child_widgets.clear()

            if result['success']:
                prompts = result.get('prompts', [])
                # Get current canvas width to set initial wraplength correctly.
                # The -15 is a buffer for scrollbar and padding.
                current_width = self.children_canvas.winfo_width()
                for prompt in prompts:
                    item_frame = ttk.Frame(self.children_container)
                    item_frame.pack(fill=tk.X, pady=2, padx=2)

                    label = ttk.Label(item_frame, text=prompt, style="Grooved.TLabel", wraplength=current_width - 15)
                    label.pack(side=tk.LEFT, fill=tk.X, expand=True)

                    widget_info = {'frame': item_frame, 'label': label, 'prompt': prompt, 'selected': False}
                    self.child_widgets.append(widget_info)
                    right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
                    label.bind("<Button-1>", lambda e, info=widget_info: self._toggle_child_selection(info))
                    label.bind("<MouseWheel>", self._on_children_mouse_wheel)
                    item_frame.bind("<MouseWheel>", self._on_children_mouse_wheel)
                    label.bind(right_click_event, lambda e, info=widget_info: self._show_child_context_menu(e, info))
            else:
                error_msg = f"The AI failed to generate child prompts:\n{result['error']}"
                custom_dialogs.show_error(self, "Breeding Error", error_msg)
                error_label = ttk.Label(self.children_container, text=error_msg, style="TLabel", padding=10)
                error_label.pack(fill=tk.X, pady=2, padx=2)
                self.child_widgets.append({'label': error_label, 'prompt': '', 'selected': False})

        except queue.Empty:
            self.after_id = self.after(100, self._check_queue)

    def _use_children_as_parents(self):
        selected_prompts = [info['prompt'] for info in self.child_widgets if info['selected']]
        if not selected_prompts:
            custom_dialogs.show_warning(self, "No Selection", "Please click on one or more child prompts to select them.")
            return

        # Clear children
        for widget_info in self.child_widgets:
            widget_info['label'].destroy()
        self.child_widgets.clear()
        # Clear and repopulate parents
        self._clear_and_repopulate_parents(selected_prompts)

    def _send_to_editor(self):
        selected_prompts = [info['prompt'] for info in self.child_widgets if info['selected']]
        if len(selected_prompts) != 1:
            custom_dialogs.show_warning(self, "Selection Error", "Please select exactly one child prompt to send to the editor.")
            return
        
        prompt_to_load = selected_prompts[0]
        self.load_prompt_callback(prompt_to_load)
        self.destroy()

    def _show_history_context_menu(self, event, history_item):
        self.history_context_menu.delete(0, tk.END)
        self.history_context_menu.add_command(label="Copy Enhanced/Original Prompt", command=lambda: self._copy_history_prompt(history_item))
        self.history_context_menu.add_command(label="Add as Parent", command=lambda: self._add_history_item_to_parents(history_item))
        self.history_context_menu.tk_popup(event.x_root, event.y_root)

    def _copy_history_prompt(self, history_item):
        prompt = history_item.get('enhanced', {}).get('prompt') or history_item.get('original_prompt', '')
        if prompt:
            self.clipboard_clear()
            self.clipboard_append(prompt)

    def _show_parent_context_menu(self, event, widget_info):
        self.parent_context_menu.delete(0, tk.END)
        self.parent_context_menu.add_command(label="Copy Prompt", command=lambda: self._copy_parent_prompt(widget_info))
        self.parent_context_menu.add_command(label="Remove", command=lambda: self._remove_single_parent(widget_info))
        self.parent_context_menu.tk_popup(event.x_root, event.y_root)

    def _copy_parent_prompt(self, widget_info):
        prompt = widget_info.get('prompt')
        if prompt:
            self.clipboard_clear()
            self.clipboard_append(prompt)

    def _remove_single_parent(self, widget_info):
        widget_info['label'].destroy()
        self.parent_widgets.remove(widget_info)

    def _show_child_context_menu(self, event, widget_info):
        self.child_context_menu.delete(0, tk.END)
        self.child_context_menu.add_command(label="Copy Prompt", command=lambda: self._copy_child_prompt(widget_info))
        self.child_context_menu.add_command(label="Add as Parent", command=lambda: self._add_child_to_parents(widget_info))
        self.child_context_menu.add_separator()
        self.child_context_menu.add_command(label="Generate Image...", command=lambda: self._generate_image_for_child_from_menu(widget_info))
        self.child_context_menu.add_command(label="Enhance and Save...", command=lambda: self._enhance_child_prompt(widget_info))
        self.child_context_menu.add_command(label="Send to Main Editor", command=lambda: self._send_child_to_editor(widget_info))
        self.child_context_menu.tk_popup(event.x_root, event.y_root)

    def _copy_child_prompt(self, widget_info):
        prompt = widget_info.get('prompt')
        if prompt:
            self.clipboard_clear()
            self.clipboard_append(prompt)

    def _add_child_to_parents(self, widget_info):
        prompt = widget_info.get('prompt')
        if prompt:
            self._add_parent_widget(prompt)

    def _generate_image_for_child_from_menu(self, widget_info: Dict[str, Any]):
        """Starts the image generation workflow for a child prompt from the context menu."""
        prompt = widget_info.get('prompt')
        if not prompt:
            return

        def on_success(images_to_save: List[Dict[str, Any]]):
            if not images_to_save: return
            
            # Use the current app workflow for saving.
            saved_images_data = [{'image_path': self.processor.save_generated_image(img['bytes']), 'generation_params': img.get('generation_params')} for img in images_to_save]
            
            entry = {
                'original_prompt': images_to_save[0]['prompt'],
                'status': 'generated_only',
                'original_images': saved_images_data,
                'template_name': "Evolved from Prompt Evolver"
            }
            self.processor.history_manager.save_result(**entry)
            custom_dialogs.show_info(self, "Image Saved", f"{len(saved_images_data)} image(s) and prompt saved to history.")
            # After saving, refresh the history list in the evolver
            self.refresh_data()

        self.parent_app._start_image_generation_workflow(
            parent_window=self, prompt=prompt, initial_dialog_params={'negative_prompt': config.DEFAULT_NEGATIVE_PROMPT},
            button_to_manage=None, spinner_to_manage=None, on_success_callback=on_success
        )

    def _enhance_child_prompt(self, widget_info):
        """Sends a child prompt to the main app's enhancement workflow."""
        prompt_to_enhance = widget_info.get('prompt')
        if prompt_to_enhance:
            # The template name is not relevant here, but we can pass something descriptive.
            self.parent_app.start_enhancement_for_prompt(prompt_to_enhance, template_name="From Prompt Evolver")

    def _send_child_to_editor(self, widget_info):
        prompt_to_load = widget_info.get('prompt')
        if prompt_to_load:
            self.load_prompt_callback(prompt_to_load)
            self.destroy()

    def _clear_and_repopulate_parents(self, new_parents: List[str]):
        """Clears all current parent widgets and adds new ones from a list of prompts."""
        # Clear existing parent widgets
        for widget_info in self.parent_widgets:
            widget_info['label'].destroy()
        self.parent_widgets.clear()

        # Add new parent widgets
        for prompt in new_parents:
            self._add_parent_widget(prompt)