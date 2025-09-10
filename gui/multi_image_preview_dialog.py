"""A dialog to preview multiple generated images and select which to keep."""

import tkinter as tk
from tkinter import ttk
import sys
import queue
import threading
import traceback
import copy
import uuid
import random
from PIL import Image, ImageTk
import io
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Callable

from .common import SmartWindowMixin, LoadingAnimation, TextContextMenu, ImagePreviewMixin
from . import custom_dialogs

if TYPE_CHECKING:
    from core.prompt_processor import PromptProcessor

class MultiImagePreviewDialog(custom_dialogs._CustomDialog, SmartWindowMixin, ImagePreviewMixin):
    """A dialog to preview multiple generated images and select which to keep."""
    def __init__(self, parent, generation_jobs: List[Dict[str, Any]], processor: 'PromptProcessor', progress_callback: Callable, completion_callback: Callable, save_to_gallery: bool):
        super().__init__(parent, "Review Generated Images", modal=False)
        ImagePreviewMixin.__init__(self)
        self.processor = processor
        self.generation_jobs = generation_jobs
        # --- NEW: Assign unique IDs to each job for stable referencing ---
        for job in self.generation_jobs:
            job['id'] = str(uuid.uuid4())
        self.save_to_gallery_for_batch = save_to_gallery
        self.completed_jobs = 0
        self.image_widgets: List[Dict[str, Any]] = []
        self.progress_callback = progress_callback
        self.image_context_menu = tk.Menu(self, tearoff=0)
        self.context_menu_widget_info: Optional[Dict[str, Any]] = None
        self.completion_callback = completion_callback
        
        # Queues for async operations
        self.thumbnail_work_queue = queue.Queue()
        self.thumbnail_queue = queue.Queue()
        self.generation_queue = queue.Queue()
        
        # After job IDs
        self.thumbnail_after_id: Optional[str] = None
        self.generation_after_id: Optional[str] = None
        
        # Threading controls
        self.concurrency_limiter = threading.Semaphore(4) # Limit concurrent generations
        self.cancellation_event = threading.Event()
        
        self.thumbnail_size = (256, 256)
        self.item_width = self.thumbnail_size[0] + 20 # Approx width for layout calculation

        # Start the single thumbnail worker thread
        self.thumbnail_worker_thread = threading.Thread(target=self._thumbnail_worker, daemon=True)
        self.thumbnail_worker_thread.start()

        self._create_widgets()
        self.image_context_menu.add_command(label="Edit & Regenerate...", command=self._edit_and_regenerate_image)
        self.image_context_menu.add_command(label="Regenerate with New Seed", command=self._regenerate_with_new_seed_from_menu)

        self._populate_grid()

        # --- Smart Sizing Logic ---
        num_images = len(self.generation_jobs)
        min_width = 800 # Default minimum
        if num_images > 1:
            # Calculate width needed for up to 4 items
            cols_to_show = min(num_images, 4)
            # Add a bit more padding for scrollbar and window chrome
            calculated_width = (self.item_width * cols_to_show) + 60
            min_width = max(min_width, calculated_width)

        self.smart_geometry(min_width=min_width, min_height=600)
        
        # Start the generation process
        self._start_generation_threads()
        self.generation_after_id = self.after(100, self._check_generation_queue)
        self.thumbnail_after_id = self.after(100, self._check_thumbnail_queue)
        
        self.protocol("WM_DELETE_WINDOW", self.close)
        # self.wait_window(self) # This is no longer a blocking dialog

    def close(self):
        """Safely close the window, cancelling any pending after() jobs and calling the completion callback."""
        self.cancellation_event.set()
        if self.generation_after_id:
            self.after_cancel(self.generation_after_id)
        if self.thumbnail_after_id:
            self.after_cancel(self.thumbnail_after_id)
        self.close_preview_on_destroy()
        
        if self.completion_callback:
            # If result is still None, it means the window was closed via 'X' or Escape.
            self.completion_callback(self.result)
            self.completion_callback = None # Prevent double calls

        # --- NEW: Unload InvokeAI models when the window is closed ---
        # This is the most reliable place to ensure cleanup happens.
        if self.processor.is_invokeai_connected():
            self.processor.clear_invokeai_cache_async()

        self.destroy()

    def _start_generation_threads(self):
        """Starts worker threads to generate images."""
        for job in self.generation_jobs:
            if self.cancellation_event.is_set():
                break
            thread = threading.Thread(target=self._generation_worker, args=(job['id'], job), daemon=True)
            thread.start()

    def _thumbnail_worker(self):
        """A single worker thread to process all thumbnail generation tasks."""
        while not self.cancellation_event.is_set():
            try:
                # Wait for a task. Timeout allows the thread to check for cancellation.
                label_widget, image_bytes = self.thumbnail_work_queue.get(timeout=1)
                
                if image_bytes:
                    try:
                        with Image.open(io.BytesIO(image_bytes)) as img:
                            thumb = img.copy()
                            thumb.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)
                            new_img = Image.new("RGBA", self.thumbnail_size, (0, 0, 0, 0))
                            paste_x = (self.thumbnail_size[0] - thumb.width) // 2
                            paste_y = (self.thumbnail_size[1] - thumb.height) // 2
                            new_img.paste(thumb, (paste_x, paste_y))
                            self.thumbnail_queue.put((label_widget, new_img))
                    except Exception as e:
                        self.thumbnail_queue.put((label_widget, e))
            except queue.Empty:
                continue # Loop again to check for cancellation or new tasks

    def _generation_worker(self, job_id: str, job: Dict[str, Any]):
        """The actual image generation task run in a thread."""
        with self.concurrency_limiter:
            if self.cancellation_event.is_set():
                return
            
            try:
                self.generation_queue.put({'status': 'generating', 'job_id': job_id})
                prompt = job['prompt']
                gen_params = job['gen_params']

                gen_args = {
                    "prompt": prompt,
                    "negative_prompt": gen_params.get("negative_prompt", ""),
                    "seed": gen_params.get("seed"),
                    "model_object": gen_params.get("model"),
                    "loras": gen_params.get("loras", []),
                    "steps": gen_params.get("steps", 30),
                    "cfg_scale": gen_params.get("cfg_scale", 7.5),
                    "scheduler": gen_params.get("scheduler", "dpmpp_2m"),
                    "cfg_rescale_multiplier": gen_params.get("cfg_rescale_multiplier", 0.0),
                    "save_to_gallery": self.save_to_gallery_for_batch,
                    "cancellation_event": self.cancellation_event
                }
                image_bytes = self.processor.generate_image_with_invokeai(**gen_args)
                
                if self.cancellation_event.is_set(): return

                result_data = {'bytes': image_bytes, 'prompt': prompt, 'generation_params': gen_params}
                self.generation_queue.put({'status': 'completed', 'job_id': job_id, 'data': result_data})
            except Exception as e:
                if not self.cancellation_event.is_set():
                    print(f"\n--- ERROR during image generation for job ID {job_id} ---", file=sys.stderr, flush=True)
                    traceback.print_exc(file=sys.stderr)
                    print("-----------------------------------------------------\n", file=sys.stderr, flush=True)
                    self.generation_queue.put({'status': 'error', 'job_id': job_id, 'error': f"Error: {e}"})

    def _check_thumbnail_queue(self):
        """Checks for processed thumbnails and updates the UI."""
        try:
            # Process one item from the queue per call to keep the UI responsive.
            label_widget, result = self.thumbnail_queue.get_nowait()
            if label_widget.winfo_exists(): # Check if widget is still alive
                if isinstance(result, Image.Image):
                    img_ref = ImageTk.PhotoImage(result)
                    label_widget.config(image=img_ref, text="")
                    label_widget.image = img_ref # Keep a reference
                elif isinstance(result, Exception):
                    label_widget.config(text=f"Load Error:\n{result}", image='')
        except queue.Empty:
            pass
        finally:
            if self.winfo_exists():
                self.thumbnail_after_id = self.after(100, self._check_thumbnail_queue)

    def _check_generation_queue(self):
        """Checks for generated images and updates the UI."""
        try:
            # Process one item from the queue per call to keep the UI responsive.
            result = self.generation_queue.get_nowait()
            job_id = result['job_id']
            status = result['status']

            if self.progress_callback:
                self.progress_callback(status)
            
            # Find widget by job_id
            widget_info = next((w for w in self.image_widgets if w['job_data'].get('id') == job_id), None)
            if widget_info and widget_info['frame'].winfo_exists():
                if status == 'generating':
                    widget_info['image_label'].place_forget()
                    widget_info['spinner'].place(relx=0.5, rely=0.5, anchor=tk.CENTER)
                    widget_info['spinner'].start()
                elif status == 'completed':
                    self.completed_jobs += 1
                    widget_info['spinner'].stop()
                    widget_info['spinner'].place_forget()
                    widget_info['image_label'].place(relx=0.5, rely=0.5, anchor=tk.CENTER)
                    self._update_image_in_grid(widget_info, result['data'])
                elif status == 'error':
                    self.completed_jobs += 1
                    widget_info['spinner'].stop()
                    widget_info['spinner'].pack_forget()
                    widget_info['image_label'].pack(expand=True)
                    widget_info['image_label'].config(text=result['error'], image='')
                    widget_info['regen_button'].config(state=tk.NORMAL)
            
            self._update_save_button_state() # Update button state after each processed item
        except queue.Empty:
            pass # No more items to process in this cycle
        finally:
            if self.winfo_exists(): self.generation_after_id = self.after(100, self._check_generation_queue)

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Prompt Display ---
        if self.generation_jobs:
            prompt_text = self.generation_jobs[0].get('prompt', 'No prompt provided.')
            prompt_display_frame = ttk.LabelFrame(main_frame, text="Generating with Prompt", padding=10)
            prompt_display_frame.pack(fill=tk.X, pady=(0, 10))
            
            # Use a Text widget for better display and copy-paste functionality
            prompt_widget = tk.Text(prompt_display_frame, wrap=tk.WORD, height=3, relief=tk.FLAT, exportselection=False)
            prompt_widget.insert("1.0", prompt_text)
            prompt_widget.config(state=tk.DISABLED)
            prompt_widget.pack(fill=tk.X, expand=True)
            TextContextMenu(prompt_widget)

        # Scrollable grid for images
        canvas_frame = ttk.LabelFrame(main_frame, text="Generated Images (Select to Keep)", padding=5)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.container = ttk.Frame(self.canvas)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Scrollbar is packed dynamically later
        self.canvas.pack(side="left", fill="both", expand=True)
        canvas_window = self.canvas.create_window((0, 0), window=self.container, anchor="nw")

        def _update_scrollbar_visibility():
            # This check is important to avoid errors during initialization
            if not self.container.winfo_exists() or not self.canvas.winfo_exists():
                return
            
            self.update_idletasks() # Ensure sizes are current

            content_height = self.container.winfo_reqheight()
            canvas_height = self.canvas.winfo_height()

            if content_height > canvas_height:
                if not self.scrollbar.winfo_ismapped():
                    self.scrollbar.pack(side="right", fill="y")
            else:
                if self.scrollbar.winfo_ismapped():
                    self.scrollbar.pack_forget()

        def on_frame_configure(event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            _update_scrollbar_visibility()

        def on_canvas_configure(event):
            self.canvas.itemconfig(canvas_window, width=event.width)
            self._reflow_grid()
            _update_scrollbar_visibility()

        self.container.bind("<Configure>", on_frame_configure)
        self.canvas.bind("<Configure>", on_canvas_configure)
        # Add mouse wheel scrolling
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.container.bind("<MouseWheel>", self._on_mouse_wheel)

        # Buttons
        self.button_frame = ttk.Frame(main_frame)
        self.button_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.save_button = ttk.Button(self.button_frame, text="Save Kept Images", command=self._on_ok, style="Accent.TButton")
        self.discard_button = ttk.Button(self.button_frame, text="Discard All", command=self._on_cancel)
        
        self.button_frame.bind("<Configure>", self._reflow_buttons)
        self.after(10, self._reflow_buttons)

    def _reflow_buttons(self, event=None):
        if not hasattr(self, 'button_frame') or not self.button_frame.winfo_exists():
            return

        # Ensure all widgets are managed by grid before configuring them
        self.save_button.grid()
        self.discard_button.grid()

        width = self.button_frame.winfo_width()
        req_w = self.save_button.winfo_reqwidth() + self.discard_button.winfo_reqwidth() + 20
        
        if width < req_w:
            # Vertical layout
            self.button_frame.columnconfigure(0, weight=1, minsize=0)
            self.button_frame.columnconfigure(1, weight=0)
            self.button_frame.columnconfigure(2, weight=0)
            self.save_button.grid_configure(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 5), padx=0)
            self.discard_button.grid_configure(row=1, column=0, columnspan=3, sticky='ew', pady=0, padx=0)
        else:
            # Horizontal layout
            self.button_frame.columnconfigure(0, weight=1)
            self.button_frame.columnconfigure(1, weight=0)
            self.button_frame.columnconfigure(2, weight=0)
            # Spacer is column 0
            self.save_button.grid_configure(row=0, column=1, columnspan=1, sticky='e', pady=0, padx=0)
            self.discard_button.grid_configure(row=0, column=2, columnspan=1, sticky='e', pady=0, padx=(5, 0))

    def _on_mouse_wheel(self, event):
        """Handles mouse wheel scrolling for the grid."""
        if not self.canvas: return
        delta = -1 * (event.delta if sys.platform == 'darwin' else event.delta // 120)
        self.canvas.yview_scroll(delta, "units")

    def _reflow_grid(self):
        """Recalculates and applies the grid layout for all image widgets."""
        canvas_width = self.canvas.winfo_width()
        if canvas_width <= 1 or not self.image_widgets: # Not yet rendered or nothing to draw
            return

        # Calculate columns
        cols = max(1, canvas_width // self.item_width)

        # --- NEW: Centering Logic ---
        # Clear any previous column configurations on the container.
        # This is important to handle window resizing correctly.
        for i in range(self.container.grid_size()[0]):
            self.container.columnconfigure(i, weight=0, pad=0)

        # Configure spacer columns with weight to push the content to the center.
        self.container.columnconfigure(0, weight=1)
        self.container.columnconfigure(cols + 1, weight=1)

        # Configure item columns without weight so they don't expand.
        for i in range(cols):
            self.container.columnconfigure(i + 1, weight=0)

        # Re-grid all widgets, offsetting the column by 1 for the left spacer.
        for i, widget_info in enumerate(self.image_widgets):
            widget_info['frame'].grid_forget() # Forget previous placement
            row = i // cols
            col = (i % cols) + 1 # Offset by 1 for the spacer
            widget_info['frame'].grid(row=row, column=col, padx=5, pady=5, sticky='n')

    def _populate_grid(self):
        """Clears and fills the grid with image widgets."""
        for widget_info in self.image_widgets:
            widget_info['frame'].destroy()
        self.image_widgets.clear()

        for job_data in self.generation_jobs:
            self._add_placeholder_to_grid(job_data)
        
        self._update_save_button_state()
        # Defer the reflow to allow the canvas to get its initial size
        self.canvas.after(50, self._reflow_grid)

    def _add_placeholder_to_grid(self, job_data: Dict[str, Any], index: Optional[int] = None):
        """Creates and adds/inserts the widgets for a single image placeholder."""
        item_frame = ttk.Frame(self.container, padding=0)
        item_frame.bind("<MouseWheel>", self._on_mouse_wheel)
        # No pack or grid here. _reflow_grid will handle placement

        # A sub-frame to hold the image and the checkbox, to use .place()
        image_container = ttk.Frame(item_frame, relief="groove", borderwidth=1, width=self.thumbnail_size[0], height=self.thumbnail_size[1])
        image_container.bind("<MouseWheel>", self._on_mouse_wheel)
        image_container.pack(pady=(0,5), fill="both", expand=True)
        image_container.pack_propagate(False) # Prevent the frame from shrinking to fit the text label

        # Image Label
        image_label = ttk.Label(image_container, anchor=tk.CENTER, text="Queued...")
        image_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # Spinner for loading state
        spinner = LoadingAnimation(image_container, size=32)
        # Don't place it yet, it will be shown when generation starts.

        # Checkbox
        keep_var = tk.BooleanVar(value=True)
        keep_check = ttk.Checkbutton(image_container, variable=keep_var, text="", command=self._update_save_button_state)
        keep_check.place(relx=1.0, rely=0.0, x=-5, y=5, anchor='ne')

        # Info and Controls Frame below the image
        controls_frame = ttk.Frame(item_frame, height=45) # Give it a fixed height
        controls_frame.pack_propagate(False) # Prevent it from shrinking/growing
        controls_frame.bind("<MouseWheel>", self._on_mouse_wheel)
        controls_frame.pack(fill=tk.X)

        # Model Name
        parent_app = self.master.parent_app if hasattr(self.master, 'parent_app') else self.master
        model_name = job_data.get('gen_params', {}).get('model', {}).get('name', 'Unknown')
        model_label = ttk.Label(controls_frame, text=model_name, font=parent_app.small_font, wraplength=self.thumbnail_size[0] - 80, justify=tk.LEFT)
        model_label.place(relx=0.0, rely=0.5, anchor='w', x=5)
        model_label.bind("<MouseWheel>", self._on_mouse_wheel)

        # Regen Button
        regen_button = ttk.Button(controls_frame, text="Regen", width=7, state=tk.DISABLED)
        regen_button.place(relx=1.0, rely=0.5, anchor='e', x=-5)
        regen_button.bind("<MouseWheel>", self._on_mouse_wheel)
        # The command will be set after the widget_info is created
        widget_info = {
            'frame': item_frame,
            'job_data': job_data,
            'image_data': None, # Will be filled in later
            'full_pil_image': None, # To store the full-resolution image
            'keep_var': keep_var,
            'image_label': image_label,
            'spinner': spinner,
            'model_label': model_label,
            'regen_button': regen_button
        }
        regen_button.config(command=lambda info=widget_info: self._regenerate_image(info))

        # Bind events for preview now that widget_info exists
        image_label.bind("<Enter>", lambda e, info=widget_info: self._schedule_preview(info))
        image_label.bind("<Leave>", lambda e: self._schedule_hide())

        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        # Bind to multiple widgets within the card for better UX
        for widget in [widget_info['frame'], widget_info['image_label'], widget_info['model_label']]:
            widget.bind(right_click_event, lambda e, info=widget_info: self._show_context_menu(e, info))

        if index is None:
            self.image_widgets.append(widget_info)
        else:
            self.image_widgets.insert(index, widget_info)

    def _update_image_in_grid(self, widget_info: Dict[str, Any], new_image_data: Dict[str, Any]):
        """Updates a single image widget in the grid without rebuilding the whole grid."""
        # Update data sources for final image
        widget_info['job_data']['gen_params'] = new_image_data['generation_params']
        widget_info['image_data'] = new_image_data
        widget_info['image_label'].config(text="Loading Thumb...")

        # Store the full-resolution image in memory
        image_bytes = new_image_data.get('bytes')
        if image_bytes:
            widget_info['full_pil_image'] = Image.open(io.BytesIO(image_bytes))
            # Instead of starting a new thread, put the task on the work queue.
            self.thumbnail_work_queue.put((widget_info['image_label'], image_bytes))

        widget_info['regen_button'].config(state=tk.NORMAL)
        model_name = new_image_data.get('generation_params', {}).get('model', {}).get('name', 'Unknown')
        widget_info['model_label'].config(text=model_name)
        widget_info['keep_var'].set(True)

    def _update_save_button_state(self):
        """Updates the text and state of the main save button."""
        if not hasattr(self, 'save_button') or not self.save_button.winfo_exists():
            return

        num_kept = sum(1 for info in self.image_widgets if info.get('image_data') and info['keep_var'].get())
        
        if self.completed_jobs < len(self.generation_jobs):
            # Generations are in progress
            self.save_button.config(text=f"Save {num_kept} Completed")
        else:
            # All generations are finished
            self.save_button.config(text=f"Save {num_kept} Kept")
        
        # Disable the button if no images are selected to be kept
        self.save_button.config(state=tk.NORMAL if num_kept > 0 else tk.DISABLED)

    def _get_preview_image(self, widget_info: Dict[str, Any]) -> Optional[Image.Image]:
        """Implementation of the abstract method from ImagePreviewMixin."""
        # This dialog already has the full PIL image in memory.
        return widget_info.get('full_pil_image')

    def _regenerate_with_new_seed_from_menu(self):
        """Wrapper to call the standard regeneration from the context menu."""
        if self.context_menu_widget_info:
            self._regenerate_image(self.context_menu_widget_info)

    def _edit_and_regenerate_image(self): # noqa: C901
        """Handles the 'Edit & Regenerate' action, including adding new previews for multiple selected models."""
        if not self.context_menu_widget_info:
            return
        
        widget_info = self.context_menu_widget_info
        image_data = widget_info.get('image_data')
        if not image_data or not image_data.get('generation_params'):
            custom_dialogs.show_error(self, "Error", "No generation parameters found for this image.")
            return

        # --- Collect current models to disable them in the dialog ---
        current_model_names = {
            job['gen_params'].get('model', {}).get('name') 
            for job in self.generation_jobs 
            if job['gen_params'].get('model', {}).get('name')
        }

        # Allow the model from the image being edited to be re-selected.
        model_being_edited = image_data['generation_params'].get('model', {})
        model_name_being_edited = model_being_edited.get('name')
        if model_name_being_edited in current_model_names:
            current_model_names.remove(model_name_being_edited)

        # Prepare params for the dialog
        initial_dialog_params = copy.deepcopy(image_data['generation_params'])
        # Pre-select the original model in the dialog
        if 'model' in initial_dialog_params:
            initial_dialog_params['models'] = [initial_dialog_params.pop('model')]
        
        from .image_generation_dialog import ImageGenerationOptionsDialog
        dialog = ImageGenerationOptionsDialog(
            self,
            self.processor,
            initial_params=initial_dialog_params, 
            is_editing=True,
            disabled_models=list(current_model_names)
        )
        new_options = dialog.result

        if not new_options: return

        new_models = new_options.pop('models', [])
        if not new_models:
            return

        try:
            index_to_replace = self.image_widgets.index(widget_info)
        except ValueError:
            custom_dialogs.show_error(self, "Error", "Could not find the image to replace.")
            return

        # 1. Replace the original job with the first new model
        first_model_info = new_models.pop(0)
        first_new_gen_params = new_options.copy()
        # Correctly unpack the model object and its specific negative prompt
        first_new_gen_params['model'] = first_model_info['model']
        first_new_gen_params['loras'] = first_model_info.get('loras', [])
        first_new_gen_params['negative_prompt'] = first_model_info['negative_prompt']
        self._regenerate_image_with_new_params(widget_info, first_new_gen_params)

        # 2. Insert new jobs for any additional models
        if new_models:
            original_job = self.generation_jobs[index_to_replace]
            for i, model_info in enumerate(new_models):
                insertion_index = index_to_replace + 1 + i
                new_gen_params = new_options.copy()
                # Correctly unpack the model object and its specific negative prompt for each new job
                new_gen_params['model'] = model_info['model']
                new_gen_params['loras'] = model_info.get('loras', [])
                new_gen_params['negative_prompt'] = model_info['negative_prompt']
                # --- NEW: Assign a unique ID ---
                new_job = {'prompt': original_job['prompt'], 'gen_params': new_gen_params, 'id': str(uuid.uuid4())}
                self.generation_jobs.insert(insertion_index, new_job)
                self._add_placeholder_to_grid(new_job, index=insertion_index)
                thread = threading.Thread(target=self._generation_worker, args=(new_job['id'], new_job), daemon=True)
                thread.start()
            self._reflow_grid()

    def _regenerate_image(self, widget_info_to_regen: Dict[str, Any]):
        """Regenerates an image, replacing the old one in the dialog."""
        if self.progress_callback:
            self.progress_callback('regenerating')

        # Use the widget's job_data, which is now the most up-to-date reference
        original_job = widget_info_to_regen['job_data']
        new_gen_params = copy.deepcopy(original_job['gen_params'])
        new_gen_params['seed'] = random.randint(0, 2**32 - 1)
        # A simple regeneration should not be saved to the gallery, regardless of the original setting.
        new_gen_params['save_to_gallery'] = False
        
        self._regenerate_image_with_new_params(widget_info_to_regen, new_gen_params)

    def _show_context_menu(self, event, widget_info: Dict[str, Any]):
        """Shows the context menu for an image card."""
        # Only show if an image has been generated for this slot
        if not widget_info.get('image_data'):
            return
        self.context_menu_widget_info = widget_info
        self.image_context_menu.tk_popup(event.x_root, event.y_root)

    def _regenerate_image_with_new_params(self, widget_info_to_regen: Dict[str, Any], new_gen_params: Dict[str, Any]):
        """Regenerates an image with a full new set of parameters."""
        try:
            # Find the index of the widget and job to replace. This is still safe because
            # we are operating on the current state of the lists.
            index_to_replace = self.image_widgets.index(widget_info_to_regen)
        except ValueError:
            custom_dialogs.show_error(self, "Error", "Could not find the image to replace.")
            return

        widget_info_to_regen['regen_button'].config(state=tk.DISABLED)
        
        original_job = self.generation_jobs[index_to_replace]
        # --- NEW: Create a new job with a new ID ---
        new_job = {'prompt': original_job['prompt'], 'gen_params': new_gen_params, 'id': str(uuid.uuid4())}
        
        # Update the job list so subsequent regens use the new params
        self.generation_jobs[index_to_replace] = new_job
        # Also update the widget's internal job data reference
        widget_info_to_regen['job_data'] = new_job
        # Clear old results
        widget_info_to_regen['image_data'] = None

        # --- NEW: Explicitly reset the UI to a generating state ---
        widget_info_to_regen['image_label'].pack_forget()
        widget_info_to_regen['spinner'].pack(expand=True)
        widget_info_to_regen['spinner'].start()
        new_model_name = new_gen_params.get('model', {}).get('name', '...')
        widget_info_to_regen['model_label'].config(text=new_model_name)

        # Start a new worker thread for this single job with the new ID
        thread = threading.Thread(target=self._generation_worker, args=(new_job['id'], new_job), daemon=True)
        thread.start()

    def _on_ok(self, event=None):
        self.result = [info['image_data'] for info in self.image_widgets if info.get('image_data') and info['keep_var'].get()]
        self.close() # close will handle the callback

    def _on_cancel(self, event=None):
        self.result = []
        self.close() # close will handle the callback