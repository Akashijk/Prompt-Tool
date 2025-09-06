"""A dialog to preview multiple generated images and select which to keep."""

import tkinter as tk
from tkinter import ttk
import sys
import queue
import threading
import copy
import random
from PIL import Image, ImageTk
import io
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Callable

from .common import SmartWindowMixin, LoadingAnimation, TextContextMenu
from . import custom_dialogs

if TYPE_CHECKING:
    from core.prompt_processor import PromptProcessor

class MultiImagePreviewDialog(custom_dialogs._CustomDialog, SmartWindowMixin):
    """A dialog to preview multiple generated images and select which to keep."""
    def __init__(self, parent, generation_jobs: List[Dict[str, Any]], processor: 'PromptProcessor', progress_callback: Callable, completion_callback: Callable):
        super().__init__(parent, "Review Generated Images")
        self.processor = processor
        self.generation_jobs = generation_jobs
        self.image_results = [None] * len(self.generation_jobs) # Placeholders for results
        self.image_widgets: List[Dict[str, Any]] = []
        self.progress_callback = progress_callback
        self.image_context_menu = tk.Menu(self, tearoff=0)
        self.context_menu_widget_info: Optional[Dict[str, Any]] = None
        self.completion_callback = completion_callback
        
        # Queues for async operations
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
        
        if self.completion_callback:
            # If result is still None, it means the window was closed via 'X' or Escape.
            self.completion_callback(self.result)
            self.completion_callback = None # Prevent double calls

        self.destroy()

    def _start_generation_threads(self):
        """Starts worker threads to generate images."""
        for index, job in enumerate(self.generation_jobs):
            if self.cancellation_event.is_set():
                break
            thread = threading.Thread(target=self._generation_worker, args=(index, job), daemon=True)
            thread.start()

    def _generation_worker(self, index: int, job: Dict[str, Any]):
        """The actual image generation task run in a thread."""
        with self.concurrency_limiter:
            if self.cancellation_event.is_set():
                return
            
            try:
                self.generation_queue.put({'status': 'generating', 'index': index})
                prompt = job['prompt']
                gen_params = job['gen_params']
                gen_args = {
                    "prompt": prompt, "negative_prompt": gen_params.get("negative_prompt", ""), "seed": gen_params.get("seed"),
                    "model_object": gen_params.get("model"), "loras": gen_params.get("loras", []), "steps": gen_params.get("steps"),
                    "cfg_scale": gen_params.get("cfg_scale"), "scheduler": gen_params.get("scheduler"),
                    "cfg_rescale_multiplier": gen_params.get("cfg_rescale_multiplier"), "save_to_gallery": gen_params.get("save_to_gallery", False),
                }
                image_bytes = self.processor.generate_image_with_invokeai(**gen_args)
                
                if self.cancellation_event.is_set(): return

                result_data = {'bytes': image_bytes, 'prompt': prompt, 'generation_params': gen_params}
                self.generation_queue.put({'status': 'completed', 'index': index, 'data': result_data})
            except Exception as e:
                if not self.cancellation_event.is_set():
                    self.generation_queue.put({'status': 'error', 'index': index, 'error': f"Error: {e}"})

    def _check_thumbnail_queue(self):
        """Checks for processed thumbnails and updates the UI."""
        try:
            while not self.thumbnail_queue.empty():
                label_widget, result = self.thumbnail_queue.get_nowait()
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
            while not self.generation_queue.empty():
                result = self.generation_queue.get_nowait()
                index = result['index']
                status = result['status']

                if self.progress_callback:
                    self.progress_callback(status)
                
                if index >= len(self.image_widgets): continue
                widget_info = self.image_widgets[index]

                if status == 'generating':
                    widget_info['image_label'].pack_forget()
                    widget_info['spinner'].pack(expand=True)
                    widget_info['spinner'].start()
                elif status == 'completed':
                    widget_info['spinner'].stop()
                    widget_info['spinner'].pack_forget()
                    widget_info['image_label'].pack(expand=True)
                    self._update_image_in_grid(index, result['data'])
                elif status == 'error':
                    widget_info['spinner'].stop()
                    widget_info['spinner'].pack_forget()
                    widget_info['image_label'].pack(expand=True)
                    widget_info['image_label'].config(text=result['error'], image='')
                    widget_info['regen_button'].config(state=tk.NORMAL)
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

        # Forget all widgets to regrid them
        self.save_button.grid_forget()
        self.discard_button.grid_forget()

        width = self.button_frame.winfo_width()
        req_w = self.save_button.winfo_reqwidth() + self.discard_button.winfo_reqwidth() + 20
        
        if width < req_w:
            # Vertical layout
            self.button_frame.columnconfigure(0, weight=1, minsize=0)
            self.button_frame.columnconfigure(1, weight=0)
            self.button_frame.columnconfigure(2, weight=0)
            self.save_button.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 5))
            self.discard_button.grid(row=1, column=0, columnspan=3, sticky='ew')
        else:
            # Horizontal layout
            self.button_frame.columnconfigure(0, weight=1)
            self.button_frame.columnconfigure(1, weight=0)
            self.button_frame.columnconfigure(2, weight=0)
            self.save_button.grid(row=0, column=1, sticky='e')
            self.discard_button.grid(row=0, column=2, sticky='e', padx=(5, 0))

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

        # Forget all previous grid placements to allow recalculation
        for widget_info in self.image_widgets:
            widget_info['frame'].grid_forget()

        # Calculate columns
        cols = max(1, canvas_width // self.item_width)

        # Re-grid all widgets
        for i, widget_info in enumerate(self.image_widgets):
            row = i // cols
            col = i % cols
            widget_info['frame'].grid(row=row, column=col, padx=5, pady=5, sticky='nw')

    def _populate_grid(self):
        """Clears and fills the grid with image widgets."""
        for widget_info in self.image_widgets:
            widget_info['frame'].destroy()
        self.image_widgets.clear()

        for job_data in self.generation_jobs:
            self._add_placeholder_to_grid(job_data)
        
        # Defer the reflow to allow the canvas to get its initial size
        self.canvas.after(50, self._reflow_grid)

    def _add_placeholder_to_grid(self, job_data: Dict[str, Any]):
        """Creates the widgets for a single image, but does not place them in the grid."""
        item_frame = ttk.Frame(self.container, padding=0)
        item_frame.bind("<MouseWheel>", self._on_mouse_wheel)
        # No pack or grid here. _reflow_grid will handle placement.

        # A sub-frame to hold the image and the checkbox, to use .place()
        image_container = ttk.Frame(item_frame, relief="groove", borderwidth=1, width=self.thumbnail_size[0], height=self.thumbnail_size[1])
        image_container.bind("<MouseWheel>", self._on_mouse_wheel)
        image_container.pack(pady=(0,5), fill="both", expand=True)
        image_container.pack_propagate(False) # Prevent the frame from shrinking to fit the text label

        # Image Label
        image_label = ttk.Label(image_container, anchor=tk.CENTER, text="Queued...")
        image_label.pack(expand=True) # Center the label within the fixed-size container
        
        # Spinner for loading state
        spinner = LoadingAnimation(image_container, size=32)
        # Don't pack it yet, it will be shown when generation starts.

        # Checkbox
        keep_var = tk.BooleanVar(value=True)
        keep_check = ttk.Checkbutton(image_container, variable=keep_var, text="")
        keep_check.place(relx=1.0, rely=0.0, x=-5, y=5, anchor='ne')

        # Info and Controls Frame below the image
        controls_frame = ttk.Frame(item_frame)
        controls_frame.bind("<MouseWheel>", self._on_mouse_wheel)
        controls_frame.pack(fill=tk.X)

        # Model Name
        parent_app = self.master.parent_app if hasattr(self.master, 'parent_app') else self.master
        model_name = job_data.get('gen_params', {}).get('model', {}).get('name', 'Unknown')
        model_label = ttk.Label(controls_frame, text=model_name, font=parent_app.small_font, wraplength=self.thumbnail_size[0] - 60)
        model_label.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        model_label.bind("<MouseWheel>", self._on_mouse_wheel)

        # Regen Button
        regen_button = ttk.Button(controls_frame, text="Regen", width=7, state=tk.DISABLED)
        regen_button.pack(side=tk.RIGHT)
        regen_button.bind("<MouseWheel>", self._on_mouse_wheel)
        # The command will be set after the widget_info is created
        widget_info = {
            'frame': item_frame,
            'job_data': job_data,
            'image_data': None, # Will be filled in later
            'keep_var': keep_var,
            'image_label': image_label,
            'spinner': spinner,
            'model_label': model_label,
            'regen_button': regen_button
        }
        regen_button.config(command=lambda info=widget_info: self._regenerate_image(info))

        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        # Bind to multiple widgets within the card for better UX
        for widget in [widget_info['frame'], widget_info['image_label'], widget_info['model_label']]:
            widget.bind(right_click_event, lambda e, info=widget_info: self._show_context_menu(e, info))

        self.image_widgets.append(widget_info)

    def _update_image_in_grid(self, index: int, new_image_data: Dict[str, Any]):
        """Updates a single image widget in the grid without rebuilding the whole grid."""
        if index >= len(self.image_widgets):
            return

        widget_info = self.image_widgets[index]
        
        # Update data sources
        widget_info['job_data']['gen_params'] = new_image_data['generation_params']
        widget_info['image_data'] = new_image_data
        self.image_results[index] = new_image_data

        # Update UI elements
        widget_info['image_label'].config(text="Loading Thumb...")
        def task():
            image_bytes = new_image_data.get('bytes')
            if image_bytes:
                try:
                    img_data = io.BytesIO(image_bytes)
                    img = Image.open(img_data)
                    img.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)
                    self.thumbnail_queue.put((widget_info['image_label'], img))
                except Exception as e:
                    self.thumbnail_queue.put((widget_info['image_label'], e))
        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        model_name = new_image_data.get('generation_params', {}).get('model', {}).get('name', 'Unknown')
        widget_info['model_label'].config(text=model_name)
        widget_info['keep_var'].set(True)
        widget_info['regen_button'].config(state=tk.NORMAL)

    def _regenerate_with_new_seed_from_menu(self):
        """Wrapper to call the standard regeneration from the context menu."""
        if self.context_menu_widget_info:
            self._regenerate_image(self.context_menu_widget_info)

    def _edit_and_regenerate_image(self):
        """Opens the generation options dialog to edit and then regenerate an image."""
        if not self.context_menu_widget_info:
            return
        
        widget_info = self.context_menu_widget_info
        image_data = widget_info.get('image_data')
        if not image_data: return

        gen_params = image_data.get('generation_params')
        if not gen_params:
            custom_dialogs.show_error(self, "Error", "No generation parameters found for this image.")
            return

        # Prepare params for the dialog
        initial_dialog_params = copy.deepcopy(gen_params)
        if 'model' in initial_dialog_params:
            initial_dialog_params['models'] = [initial_dialog_params.pop('model')]
        
        from .image_generation_dialog import ImageGenerationOptionsDialog
        dialog = ImageGenerationOptionsDialog(self, self.processor.invokeai_client, initial_params=initial_dialog_params, is_editing=True)
        new_options = dialog.result

        if not new_options: return # User cancelled

        new_options['model'] = new_options.pop('models')[0]
        if 'num_images' in new_options: del new_options['num_images']

        self._regenerate_image_with_new_params(widget_info, new_options)

    def _regenerate_image(self, widget_info_to_regen: Dict[str, Any]):
        """Regenerates an image, replacing the old one in the dialog."""
        if self.progress_callback:
            self.progress_callback('regenerating')

        # Get original job and create new params
        original_job = self.generation_jobs[self.image_widgets.index(widget_info_to_regen)]
        new_gen_params = copy.deepcopy(original_job['gen_params'])
        new_gen_params['seed'] = random.randint(0, 2**32 - 1)
        
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
            index_to_replace = self.image_widgets.index(widget_info_to_regen)
        except ValueError:
            custom_dialogs.show_error(self, "Error", "Could not find the image to replace.")
            return

        widget_info_to_regen['regen_button'].config(state=tk.DISABLED)
        
        original_job = self.generation_jobs[index_to_replace]
        new_job = {'prompt': original_job['prompt'], 'gen_params': new_gen_params}
        # Update the job list so subsequent regens use the new params
        self.generation_jobs[index_to_replace] = new_job

        # Start a new worker thread for this single job
        thread = threading.Thread(target=self._generation_worker, args=(index_to_replace, new_job), daemon=True)
        thread.start()

    def _on_ok(self, event=None):
        self.result = [info['image_data'] for info in self.image_widgets if info.get('image_data') and info['keep_var'].get()]
        self.close() # close will handle the callback

    def _on_cancel(self, event=None):
        self.result = []
        self.close() # close will handle the callback