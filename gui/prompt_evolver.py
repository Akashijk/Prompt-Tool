"""A window for 'breeding' new prompts from existing ones in the history."""

import tkinter as tk
import os
import tkinter.font as tkfont
import sys
from tkinter import ttk
import queue
import threading
from typing import Optional, List, Callable, TYPE_CHECKING, Dict, Any
from PIL import Image, ImageTk

from .common import SmartWindowMixin, ImagePreviewMixin, ScrollableFrame
from core.config import config
from . import custom_dialogs

if TYPE_CHECKING:
    from .gui_app import GUIApp
    from core.prompt_processor import PromptProcessor

class PromptEvolverWindow(tk.Toplevel, SmartWindowMixin, ImagePreviewMixin):
    """A window for 'breeding' new prompts from existing ones."""
    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor', load_prompt_callback: Callable):
        super().__init__(parent)
        ImagePreviewMixin.__init__(self)
        self.title("Prompt Evolver")
        self.parent_app = parent
        self.processor = processor
        self.load_prompt_callback = load_prompt_callback
        self.history_data: List[Dict[str, str]] = []
        self.BATCH_SIZE = 50
        self.current_offset = 0
        self.generation_queue = queue.Queue()
        self.history_widgets: List[Dict[str, Any]] = [] # This will store widget references and data
        self.thumbnail_work_queue = queue.Queue()
        self.thumbnail_queue = queue.Queue()
        self.cancellation_event = threading.Event()
        self.child_image_gen_spinners: Dict[str, 'LoadingAnimation'] = {}
        self.parent_widgets: List[Dict[str, Any]] = [] # To hold {'label': widget, 'prompt': text, 'selected': bool}
        self.child_widgets: List[Dict[str, Any]] = [] # To hold {'label': widget, 'prompt': text, 'selected': bool}
        self.after_id: Optional[str] = None
        self.history_context_menu = tk.Menu(self, tearoff=0)
        self.parent_context_menu = tk.Menu(self, tearoff=0)
        self.child_context_menu = tk.Menu(self, tearoff=0)
        self.thumbnail_after_id: Optional[str] = None

        # Model management
        self.model_usage_manager = self.parent_app.model_usage_manager
        self.active_model = self.parent_app.enhancement_model_var.get()
        self.model_usage_manager.register_usage(self.active_model)

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

        self._create_widgets()
        self.refresh_data() # Initial population
        self.smart_geometry(min_width=1200, min_height=700)
        
    def close(self):
        """Safely close the window, cancelling any pending after() jobs."""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.close_preview_on_destroy()
        self.cancellation_event.set()
        self.model_usage_manager.unregister_usage(self.active_model)
        self.destroy()

    def update_active_model(self, old_model: Optional[str], new_model: Optional[str]):
        """Called by the parent app when the main model changes."""
        if old_model != new_model:
            # Unregister the old model that this window was tracking
            self.model_usage_manager.unregister_usage(self.active_model)
            # Register the new model
            self.model_usage_manager.register_usage(new_model)
            # Update the internal state
            self.active_model = new_model

    def refresh_data(self):
        """Reloads history data and repopulates the listbox."""
        self._clear_history_list()
        all_history = self.processor.get_all_history_across_workflows()
        if self.parent_app.workflow_var.get() == 'sfw':
            self.history_data = [item for item in all_history if item.get('workflow_source') == 'SFW']
        else: # nsfw mode shows only nsfw
            self.history_data = [item for item in all_history if item.get('workflow_source') == 'NSFW']
        self._load_next_history_batch()
        self.update_idletasks() # Ensure canvas is ready before configuring scroll region

    def _clear_history_list(self):
        """Clears the list and resets pagination state."""
        for widget_info in self.history_widgets:
            widget_info['frame'].destroy()
        self.history_widgets.clear()
        self.current_offset = 0
        self.history_data = []
        self.load_more_button.pack_forget()

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Main horizontal pane
        h_pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        h_pane.pack(fill=tk.BOTH, expand=True)

        # Left pane: History
        history_frame = ttk.LabelFrame(h_pane, text="Prompt History (Double-click to add as parent)", padding=5)
        self.history_scroll_view = ScrollableFrame(history_frame, scroll_callback=self._update_visible_thumbnails)
        self.history_scroll_view.pack(fill=tk.BOTH, expand=True)
        self.history_canvas = self.history_scroll_view.canvas
        self.history_container = self.history_scroll_view.scrollable_frame

        self.load_more_button = ttk.Button(history_frame, text="Load More", command=self._load_next_history_batch, style="Accent.TButton")
        self.load_more_button.pack(side=tk.BOTTOM, fill=tk.X, pady=(5,0))

        def on_history_canvas_configure(event):
            for child in self.history_container.winfo_children():
                # The prompt label is the one that expands to fill the space.
                for label in child.winfo_children():
                    if isinstance(label, ttk.Label) and label.pack_info().get('expand'):
                        label.configure(wraplength=event.width - 60)

        self.history_canvas.bind("<Configure>", on_history_canvas_configure)
        h_pane.add(history_frame, weight=2)

        # Right pane: Evolution Area
        evolution_frame = ttk.Frame(h_pane)
        h_pane.add(evolution_frame, weight=3)

        # Parents Area
        parents_frame = ttk.LabelFrame(evolution_frame, text="Parent Prompts (Click to select, press Delete to remove)", padding=5)
        parents_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 5))
        self.parents_scroll_view = ScrollableFrame(parents_frame)
        self.parents_scroll_view.pack(fill=tk.BOTH, expand=True)
        self.parents_canvas = self.parents_scroll_view.canvas
        self.parents_container = self.parents_scroll_view.scrollable_frame

        # --- Controls (now in the middle) ---
        control_frame = ttk.Frame(evolution_frame, padding=(0, 5, 0, 5))
        control_frame.pack(side=tk.TOP, fill=tk.X)

        def on_parents_canvas_configure(event):
            for widget_info in self.parent_widgets:
                widget_info['label'].configure(wraplength=event.width - 15)

        self.parents_canvas.bind("<Configure>", on_parents_canvas_configure)
        # Bind delete key to the canvas. It must have focus to receive the event.
        self.parents_canvas.bind("<FocusIn>", lambda e: self.parents_canvas.focus_set())
        self.parents_canvas.bind("<Delete>", self._remove_selected_parents)
        self.parents_canvas.bind("<BackSpace>", self._remove_selected_parents)

        # Children Area
        children_frame = ttk.LabelFrame(evolution_frame, text="Child Prompts (Generated, click to select)", padding=5)
        children_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(5, 0))
        self.children_scroll_view = ScrollableFrame(children_frame)
        self.children_scroll_view.pack(fill=tk.BOTH, expand=True)
        self.children_canvas = self.children_scroll_view.canvas
        self.children_container = self.children_scroll_view.scrollable_frame

        def on_canvas_configure(event):
            for widget_info in self.child_widgets:
                widget_info['label'].configure(wraplength=event.width - 15)

        self.children_canvas.bind("<Configure>", on_canvas_configure)

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

    def _update_visible_thumbnails(self):
        """Loads thumbnails only for the items currently visible in the history list."""
        if not self.history_canvas or not self.history_container.winfo_exists():
            return

        try:
            canvas_top = self.history_canvas.canvasy(0)
            canvas_bottom = self.history_canvas.canvasy(self.history_canvas.winfo_height())
        except tk.TclError:
            return

        for widget_info in self.history_widgets:
            if widget_info.get('thumbnail_loaded'): continue

            frame = widget_info['frame']
            if not frame.winfo_exists(): continue
            
            widget_top = frame.winfo_y()
            widget_bottom = widget_top + frame.winfo_reqheight()
            
            if not (widget_bottom < canvas_top or widget_top > canvas_bottom):
                widget_info['thumbnail_loaded'] = True
                image_path = widget_info.get('cover_image_path')
                label_widget = widget_info.get('thumb_label')

                workflow = widget_info.get('workflow_tag')
                if image_path and workflow and label_widget:
                    self._load_history_thumbnail(label_widget, image_path, workflow)

    def _check_thumbnail_queue(self):
        """Checks for loaded thumbnails and updates the UI."""
        try:
            label_widget, image_data = self.thumbnail_queue.get_nowait()
            if label_widget.winfo_exists():
                img_ref = ImageTk.PhotoImage(image_data)
                label_widget.config(image=img_ref, text="")
                label_widget.image = img_ref  # Keep a reference
        except queue.Empty:
            pass
        finally:
            if self.winfo_exists():
                self.thumbnail_after_id = self.after(100, self._check_thumbnail_queue)

    def _load_history_thumbnail(self, label_widget: ttk.Label, image_path: str, workflow: str):
        """Starts a background thread to load a thumbnail using the ThumbnailManager."""
        def task():
            try:
                thumbnail_image = self.processor.thumbnail_manager.get_thumbnail(image_path, workflow)
                if thumbnail_image:
                    self.thumbnail_queue.put((label_widget, thumbnail_image))
            except Exception as e:
                print(f"Error in thumbnail task for {image_path}: {e}")

        thread = threading.Thread(target=task, daemon=True)
        thread.start()

    def _load_next_history_batch(self):
        """Loads the next batch of history items into the view."""
        if self.current_offset >= len(self.history_data):
            self.load_more_button.pack_forget()
            return

        start = self.current_offset
        end = min(self.current_offset + self.BATCH_SIZE, len(self.history_data))
        batch_data = self.history_data[start:end]
        
        self._populate_history_list(batch_data)
        self.current_offset = end

    def _populate_history_list(self, data_batch: List[Dict[str, Any]]):
        """Appends a batch of history items to the list view."""
        if not data_batch:
            ttk.Label(self.history_container, text="No prompt history found.", padding=10).pack()
            return
        
        self.thumbnail_after_id = self.after(100, self._check_thumbnail_queue)
        current_width = self.history_canvas.winfo_width()

        for i, item in enumerate(data_batch):
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
                for img_list in image_lists_to_check:
                    if img_list: # Find the first non-empty image list
                        cover_image_path = img_list[0].get('image_path')
                        break # Stop after finding the first one

            workflow_tag = item.get('workflow_source', 'N/A')
            is_favorite = item.get('favorite', False)
            
            # Create a frame for each history item for better layout and binding
            item_frame = ttk.Frame(self.history_container, style="History.TFrame", relief="groove", borderwidth=1, padding=5)
            item_frame.pack(fill=tk.X, pady=2, padx=2)

            thumb_label = ttk.Label(item_frame, text="🖼️", width=12, anchor=tk.CENTER)
            thumb_label.pack(side=tk.LEFT, padx=5, pady=5)

            # Create and pack the prefix label
            prefix_style = "SFW.History.TLabel" if workflow_tag == "SFW" else "NSFW.History.TLabel"
            prefix_label = ttk.Label(item_frame, text=f"[{workflow_tag}] ", style=prefix_style)
            prefix_label.pack(side=tk.LEFT)

            prompt_style = "Favorite.History.TLabel" if is_favorite else "Prompt.History.TLabel"
            prompt_label = ttk.Label(item_frame, text=prompt_text, style=prompt_style, wraplength=current_width - 60)
            prompt_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

            widget_info = {
                'frame': item_frame,
                'thumb_label': thumb_label,
                'cover_image_path': cover_image_path,
                'workflow_tag': workflow_tag,
                'thumbnail_loaded': False
            }
            self.history_widgets.append(widget_info)

            # Bind preview events
            thumb_label.bind("<Enter>", lambda e, info=widget_info: self._schedule_preview(info))
            thumb_label.bind("<Leave>", lambda e: self._schedule_hide())

            # Bind events to the frame and its labels
            right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
            for widget in [item_frame, prefix_label, prompt_label]:
                widget.bind("<Double-1>", lambda e, history_item=item: self._add_history_item_to_parents(history_item))
                widget.bind("<MouseWheel>", self.history_scroll_view._on_mouse_wheel)
                widget.bind(right_click_event, lambda e, item=item: self._show_history_context_menu(e, item))
        self.after(100, self._update_visible_thumbnails)
    
    def _get_preview_image(self, widget_info: Dict[str, Any]) -> Optional[Image.Image]:
        """Implementation of the abstract method from ImagePreviewMixin."""
        relative_image_path = widget_info.get('cover_image_path')
        if not relative_image_path: return None

        try:
            workflow = widget_info.get('workflow_tag', 'sfw')
            original_workflow = config.workflow
            config.workflow = workflow.lower()
            full_path = os.path.join(config.get_history_file_dir(), relative_image_path)
            config.workflow = original_workflow # Restore immediately
            if not os.path.exists(full_path): return None
            return Image.open(full_path)
        except Exception as e:
            print(f"Error loading full image for preview: {e}")
            return None

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
        label.bind("<MouseWheel>", self.parents_scroll_view._on_mouse_wheel)
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
                    label.bind("<MouseWheel>", self.children_scroll_view._on_mouse_wheel)
                    item_frame.bind("<MouseWheel>", self.children_scroll_view._on_mouse_wheel)
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

        self._clear_and_repopulate_parents(selected_prompts)
        self._clear_children()

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
            
            # --- NEW: Generate entry ID first ---
            entry_id = str(uuid.uuid4())
            # Use the current app workflow for saving.
            saved_images_data = [{'image_path': self.processor.save_generated_image(img['bytes'], entry_id), 'generation_params': img.get('generation_params')} for img in images_to_save]
            
            parent_prompts = [p['prompt'] for p in self.parent_widgets]
            parent_preview = ""
            if parent_prompts:
                parent_preview = (parent_prompts[0][:20] + '...') if len(parent_prompts[0]) > 20 else parent_prompts[0]
                if len(parent_prompts) > 1:
                    parent_preview += f" + {len(parent_prompts) - 1} more"

            entry = {
                'id': entry_id, # Add the ID here
                'original_prompt': images_to_save[0]['prompt'],
                'status': 'generated_only',
                'original_images': saved_images_data,
                'template_name': f"Evolved from: \"{parent_preview}\"" if parent_preview else "Evolved from Prompt Evolver"
            }
            self.processor.history_manager.save_result(**entry)
            self.processor.clear_avg_gen_times_cache()
            custom_dialogs.show_info(self, "Image Saved", f"{len(saved_images_data)} image(s) and prompt saved to history.")
            # After saving, refresh the history list in the evolver
            self.refresh_data()

        self.parent_app._start_image_generation_workflow(
            parent_window=self, 
            prompt=prompt, 
            initial_dialog_params={'negative_prompt': self.processor.get_default_negative_prompt_text()},
            button_to_manage=None, 
            spinner_to_manage=None, on_success_callback=on_success
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

    def _clear_children(self):
        """Clears all child prompt widgets."""
        for widget_info in self.child_widgets:
            widget_info['frame'].destroy()
        self.child_widgets.clear()

    def _clear_and_repopulate_parents(self, new_parents: List[str]):
        """Clears all current parent widgets and adds new ones from a list of prompts."""
        # Clear existing parent widgets
        for widget_info in self.parent_widgets:
            widget_info['label'].destroy()
        self.parent_widgets.clear()

        # Add new parent widgets
        for prompt in new_parents:
            self._add_parent_widget(prompt)

    def _cancel_scheduled_hide(self):
        """Cancels any pending hide operation. Called when mouse enters thumbnail or preview."""
        if self.preview_hide_id:
            self.after_cancel(self.preview_hide_id)
            self.preview_hide_id = None

    def _schedule_preview(self, widget_info):
        """Schedules the preview window to appear after a delay."""
        self._cancel_scheduled_hide()

        if not widget_info.get('cover_image_path'):
            return
            
        if self.preview_show_id:
            self.after_cancel(self.preview_show_id)
        self.preview_show_id = self.after(750, lambda: self._show_preview(widget_info))

    def _schedule_hide(self, event=None):
        """Schedules the preview to be hidden after a short delay, allowing the cursor to move into it."""
        if self.preview_show_id:
            self.after_cancel(self.preview_show_id)
            self.preview_show_id = None
        
        if not self.preview_hide_id:
            self.preview_hide_id = self.after(100, self._hide_preview)

    def _hide_preview(self):
        """Performs the actual destruction of the preview window."""
        if self.preview_window:
            self.preview_window.destroy()
            self.preview_window = None
        self.preview_hide_id = None

    def _show_preview(self, widget_info):
        """Creates and displays the full-size image preview window."""
        self._cancel_scheduled_hide()
        if self.preview_show_id: self.after_cancel(self.preview_show_id)
        if self.preview_window: self.preview_window.destroy()

        relative_image_path = widget_info.get('cover_image_path')
        if not relative_image_path: return

        try:
            workflow = widget_info.get('workflow_tag', 'sfw')
            original_workflow = config.workflow
            config.workflow = workflow.lower()
            full_path = os.path.join(config.get_history_file_dir(), relative_image_path)
            config.workflow = original_workflow # Restore immediately
            if not os.path.exists(full_path): return
            pil_image = Image.open(full_path)
        except Exception as e:
            print(f"Error loading full image for preview: {e}")
            return

        self.preview_window = tk.Toplevel(self)
        self.preview_window.wm_overrideredirect(True)
        self.preview_window.wm_attributes("-topmost", True)

        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        img_copy = pil_image.copy()
        img_copy.thumbnail((screen_width - 100, screen_height - 100), Image.Resampling.LANCZOS)
        self.preview_image_ref = ImageTk.PhotoImage(img_copy)
        
        preview_label = ttk.Label(self.preview_window, image=self.preview_image_ref, borderwidth=2, relief="solid")
        preview_label.pack()
        for widget in [self.preview_window, preview_label]:
            widget.bind("<Enter>", lambda e: self._cancel_scheduled_hide())
            widget.bind("<Leave>", lambda e: self._schedule_hide())

        x = (screen_width // 2) - (img_copy.width // 2)
        y = (screen_height // 2) - (img_copy.height // 2)
        self.preview_window.wm_geometry(f"+{x}+{y}")