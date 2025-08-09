"""A pop-up window to display enhancement results."""

import tkinter as tk
from tkinter import ttk
import threading
import queue
from typing import List, Optional, Dict, Callable, TYPE_CHECKING

from . import custom_dialogs
from core.prompt_processor import PromptProcessor
from .common import LoadingAnimation, TextContextMenu

if TYPE_CHECKING:
    from .gui_app import GUIApp

class EnhancementResultWindow(tk.Toplevel):
    """A pop-up window to display enhancement results."""
    def __init__(self, parent: 'GUIApp', result_data: dict, processor: PromptProcessor, model: str, selected_variations: List[str], cancel_callback: Callable, api_call_finish_callback: Callable):
        super().__init__(parent)
        self.title("Enhancement Result")
        self.geometry("700x750")
        self.transient(parent)
        self.grab_set()
        self.api_call_finish_callback = api_call_finish_callback
        self.cancel_callback = cancel_callback
        self.parent_app = parent

        self.processor = processor
        self.model = model
        self.result_data = result_data
        self.selected_variations = selected_variations

        # UI element storage
        self.text_widgets: Dict[str, tk.Text] = {}
        self.sd_model_labels: Dict[str, ttk.Label] = {}
        self.loading_animations: Dict[str, LoadingAnimation] = {}
        self.copy_buttons: Dict[str, ttk.Button] = {}
        self.regen_buttons: Dict[str, ttk.Button] = {}
        self.regen_queue: queue.Queue = queue.Queue()
        self.result_queue: queue.Queue = queue.Queue()
        self.result_queue_after_id: Optional[str] = None
        self.regen_queue_after_id: Optional[str] = None

        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Create all text areas with placeholder content for dynamic fields
        self._create_text_area(main_frame, 'original', "Original Prompt", self.result_data['original'], height=3)
        self._create_text_area(main_frame, 'enhanced', "Enhanced Prompt", "Generating...", sd_model="Generating...", height=6)

        if self.selected_variations:
            variations_frame = ttk.LabelFrame(main_frame, text="Variations", padding="10")
            variations_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            for var_type in self.selected_variations:
                self._create_text_area(variations_frame, var_type, var_type.capitalize(), "Generating...", sd_model="Generating...", height=4)

        # --- Action Buttons ---
        button_frame = ttk.Frame(main_frame, padding=(0, 10, 0, 0))
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="Save to History", command=self._save).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Close", command=self._on_close).pack(side=tk.RIGHT)

        self.result_queue_after_id = self.after(100, self._check_result_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        # Cancel pending after jobs to prevent memory leaks
        if self.result_queue_after_id:
            self.after_cancel(self.result_queue_after_id)
            self.result_queue_after_id = None
        if self.regen_queue_after_id:
            self.after_cancel(self.regen_queue_after_id)
            self.regen_queue_after_id = None

        # Only trigger the cancellation logic if there are still active API calls.
        if self.parent_app.active_api_calls > 0:
            self.cancel_callback()
        self.destroy()
    
    def _create_text_area(self, parent, prompt_key: str, title: str, content: str, height: int, sd_model: Optional[str] = None):
        frame = ttk.LabelFrame(parent, text=title, padding="5")
        frame.pack(fill=tk.X, pady=5)
        
        # Frame to hold text and copy button
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.X, expand=True)

        # Scrollbar and Text widget
        scroll_text_frame = ttk.Frame(text_frame)
        scroll_text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(scroll_text_frame, orient=tk.VERTICAL)
        text_widget = tk.Text(scroll_text_frame, wrap=tk.WORD, height=height, font=self.parent_app.default_font, yscrollcommand=scrollbar.set)
        scrollbar.config(command=text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_widget.insert("1.0", content)
        text_widget.config(state=tk.DISABLED)
        self.text_widgets[prompt_key] = text_widget
        TextContextMenu(text_widget)
        
        # Button container
        button_container = ttk.Frame(text_frame)
        button_container.pack(side=tk.LEFT, padx=(5, 0), anchor='n')
        
        copy_button = ttk.Button(button_container, text="Copy", command=lambda key=prompt_key: self._copy_current_prompt(key))
        copy_button.pack(fill=tk.X)
        self.copy_buttons[prompt_key] = copy_button

        if prompt_key != 'original':
            # Create spinner and regen button, but only show the spinner initially
            loading_animation = LoadingAnimation(button_container)
            is_dark = self.parent_app.theme_manager.current_theme == "dark"
            status_bar_dot_color = "lightgrey" if is_dark else "dimgray"
            status_bar_bg = self.cget('background')
            loading_animation.update_style(bg_color=status_bar_bg, dot_color=status_bar_dot_color, is_dark_theme=is_dark)
            loading_animation.pack(fill=tk.X, pady=(5,0))
            loading_animation.start()
            self.loading_animations[prompt_key] = loading_animation

            regen_button = ttk.Button(button_container, text="Regen", command=lambda key=prompt_key: self._start_regeneration(key))
            # Don't pack the regen button yet
            self.regen_buttons[prompt_key] = regen_button
            copy_button.config(state=tk.DISABLED)

        # Add SD model label if provided
        if sd_model:
            model_label = ttk.Label(frame, text=f"Recommended Model: {sd_model}", font=self.parent_app.small_font, foreground="gray")
            model_label.pack(anchor='w', padx=5, pady=(2, 0))
            self.sd_model_labels[prompt_key] = model_label

    def _save(self):
        """Save the result to the CSV history."""
        self.processor.save_results([self.result_data])
        custom_dialogs.show_info(self, "Saved", "Result saved to history.")
        self.destroy()

    def _copy_to_clipboard(self, content: str):
        """Copies the given content to the clipboard."""
        self.clipboard_clear()
        self.clipboard_append(content)

    def _copy_current_prompt(self, prompt_key: str):
        """Copies the current prompt text from the internal data structure."""
        content_to_copy = ""
        if prompt_key == 'original':
            content_to_copy = self.result_data['original']
        elif prompt_key == 'enhanced':
            content_to_copy = self.result_data['enhanced']
        elif prompt_key in self.result_data.get('variations', {}):
            content_to_copy = self.result_data['variations'][prompt_key]['prompt']
        
        if content_to_copy:
            self._copy_to_clipboard(content_to_copy)

    def _start_regeneration(self, prompt_key: str):
        """Starts the regeneration process for a specific prompt in a background thread."""
        # Notify the parent app to update its counters and status
        self.parent_app.register_regeneration_call(prompt_key)

        # Hide regen button and show spinner
        self.regen_buttons[prompt_key].pack_forget()
        self.loading_animations[prompt_key].pack(fill=tk.X, pady=(5,0))
        self.loading_animations[prompt_key].start()
        
        text_widget = self.text_widgets[prompt_key]
        text_widget.config(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        text_widget.insert("1.0", "Regenerating...")
        text_widget.config(state=tk.DISABLED)

        thread = threading.Thread(target=self._regenerate_thread, args=(prompt_key,), daemon=True)
        thread.start()
        self.regen_queue_after_id = self.after(100, self._check_regen_queue)

    def _regenerate_thread(self, prompt_key: str):
        """The background task that calls the AI model for regeneration."""
        try:
            if prompt_key == 'enhanced':
                # BUG FIX: Load the system prompt for enhancement
                instruction = self.processor.load_system_prompt_content('enhancement.txt')
                full_prompt = instruction + self.result_data['original']
                new_prompt, new_sd_model = self.processor.ollama_client.enhance_prompt(full_prompt, self.model)
                result = {'key': prompt_key, 'prompt': new_prompt, 'sd_model': new_sd_model}
            else: # It's a variation
                # BUG FIX: Load the system prompt for the specific variation
                instruction = self.processor.load_system_prompt_content(f'{prompt_key}.txt')
                base_prompt = self.result_data['enhanced']
                variation_result = self.processor.ollama_client.create_single_variation(instruction, base_prompt, self.model, prompt_key)
                result = {'key': prompt_key, 'prompt': variation_result['prompt'], 'sd_model': variation_result['sd_model']}
            self.regen_queue.put(result)
        except Exception as e:
            self.regen_queue.put({'key': prompt_key, 'error': str(e)})

    def _check_regen_queue(self):
        """Checks for regeneration results and updates the UI."""
        try:
            result = self.regen_queue.get_nowait()
            key = result['key']

            # Hide spinner and show regen button
            self.loading_animations[key].stop()
            self.loading_animations[key].pack_forget()
            self.regen_buttons[key].pack(fill=tk.X, pady=(5,0))
            
            if 'error' in result:
                custom_dialogs.show_error(self, "Regeneration Error", result['error'])
                # Notify parent that the call failed
                self.parent_app.report_regeneration_finished(success=False)
                return

            new_prompt, new_sd_model = result['prompt'], result['sd_model']
            
            # Update UI
            self.text_widgets[key].config(state=tk.NORMAL)
            self.text_widgets[key].delete("1.0", tk.END)
            self.text_widgets[key].insert("1.0", new_prompt)
            self.text_widgets[key].config(state=tk.DISABLED)
            if key in self.sd_model_labels:
                self.sd_model_labels[key].config(text=f"Recommended Model: {new_sd_model}")
            
            # Update internal data for saving
            if key == 'enhanced':
                self.result_data['enhanced'] = new_prompt
                self.result_data['enhanced_sd_model'] = new_sd_model
            else:
                self.result_data['variations'][key]['prompt'] = new_prompt
                self.result_data['variations'][key]['sd_model'] = new_sd_model
            
            # Notify parent that the call is complete
            self.parent_app.report_regeneration_finished(success=True)
            
        except queue.Empty:
            self.regen_queue_after_id = self.after(100, self._check_regen_queue)

    def _check_result_queue(self):
        """Checks for incoming results from the main processing thread and updates the UI."""
        try:
            key, data = self.result_queue.get_nowait()
            
            # Update internal data for saving
            if key == 'enhanced':
                self.result_data['enhanced'] = data['prompt']
                self.result_data['enhanced_sd_model'] = data['sd_model']
            else:
                self.result_data['variations'][key] = data

            self.text_widgets[key].config(state=tk.NORMAL)
            self.text_widgets[key].delete("1.0", tk.END)
            self.text_widgets[key].insert("1.0", data['prompt'])
            self.text_widgets[key].config(state=tk.DISABLED)

            self.sd_model_labels[key].config(text=f"Recommended Model: {data['sd_model']}")
            # Hide spinner and show regen button
            self.loading_animations[key].stop()
            self.loading_animations[key].pack_forget()
            self.regen_buttons[key].pack(fill=tk.X, pady=(5,0))
            self.copy_buttons[key].config(state=tk.NORMAL)

            # Notify parent that an API call has finished
            self.api_call_finish_callback()
        except queue.Empty:
            pass # No new results yet
        finally:
            self.result_queue_after_id = self.after(100, self._check_result_queue)