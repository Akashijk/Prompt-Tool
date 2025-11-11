"""A pop-up window to display enhancement results."""

import tkinter as tk
from tkinter import ttk
import threading
import queue
import uuid
from typing import List, Optional, Dict, Callable, TYPE_CHECKING, Any

from . import custom_dialogs
from core.prompt_processor import PromptProcessor
from .common import LoadingAnimation, TextContextMenu, SmartWindowMixin, ScrollableFrame

if TYPE_CHECKING:
    from .gui_app import GUIApp

class EnhancementResultWindow(tk.Toplevel, SmartWindowMixin):
    """A pop-up window to display enhancement results."""
    def __init__(self, parent: 'GUIApp', result_data: dict, processor: PromptProcessor, model: str, models: List[Dict[str, Any]], selected_variations: List[str], cancel_callback: Callable, api_call_finish_callback: Callable, existing_entry_id: Optional[str] = None):
        super().__init__(parent)
        self.title("Enhancement Result")
        self.transient(parent)
        self.grab_set()
        self.api_call_finish_callback = api_call_finish_callback
        self.cancel_callback = cancel_callback
        self.parent_app = parent

        self.processor = processor
        self.model = model
        self.models = models
        self.result_data = result_data
        self.is_favorite = tk.BooleanVar(value=False)
        self.existing_entry_id = existing_entry_id
        self.selected_variations = selected_variations
        self.model_usage_manager = self.parent_app.model_usage_manager
        self.model_usage_manager.register_usage(self.model)

        # UI element storage
        self.text_widgets: Dict[str, tk.Text] = {}
        self.sd_model_labels: Dict[str, ttk.Label] = {}
        self.loading_animations: Dict[str, LoadingAnimation] = {}
        self.image_gen_spinners: Dict[str, LoadingAnimation] = {}
        self.edit_buttons: Dict[str, ttk.Button] = {}
        self.save_edit_buttons: Dict[str, ttk.Button] = {}
        self.cancel_edit_buttons: Dict[str, ttk.Button] = {}
        self.original_edit_content: Dict[str, str] = {}
        self.image_gen_buttons: Dict[str, ttk.Button] = {}
        self.copy_buttons: Dict[str, ttk.Button] = {}
        self.regen_buttons: Dict[str, ttk.Button] = {}
        self.save_button: Optional[ttk.Button] = None
        self.result_queue: queue.Queue = queue.Queue()
        self.result_queue_after_id: Optional[str] = None
        self.regen_queue_after_id: Optional[str] = None
        self.image_gen_after_id: Optional[str] = None

        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- NEW: Use grid layout for robustness ---
        main_frame.rowconfigure(1, weight=1) # The scrollable area gets all the extra space
        main_frame.columnconfigure(0, weight=1)

        # --- NEW: Add model selector to top of window ---
        top_controls_frame = ttk.Frame(main_frame)
        top_controls_frame.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        ttk.Label(top_controls_frame, text="AI Model:").pack(side=tk.LEFT, padx=(0, 5))
        self.model_var = tk.StringVar(value=self.model)

        # Extract just the names for the OptionMenu, which expects strings.
        model_names = [m['name'] for m in self.models]
        model_menu = ttk.OptionMenu(top_controls_frame, self.model_var, self.model, *model_names, command=self._on_model_change)
        model_menu.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # --- Action Buttons ---
        self.button_frame = ttk.Frame(main_frame) # Padding is handled by grid's pady
        self.button_frame.grid(row=2, column=0, sticky='ew', pady=(10, 0))

        # --- Button Layout (using pack for simplicity and robustness) ---
        self.save_button = ttk.Button(self.button_frame, text="Save to History", command=self._save, state=tk.DISABLED)
        self.regen_all_button = ttk.Button(self.button_frame, text="Regenerate All", command=self._regenerate_all, state=tk.DISABLED)
        self.favorite_button = ttk.Checkbutton(self.button_frame, text="Favorite ⭐", variable=self.is_favorite, style='Switch.TCheckbutton')
        self.close_button = ttk.Button(self.button_frame, text="Close", command=self.close)

        self.close_button.pack(side=tk.RIGHT, padx=(5, 0))
        self.favorite_button.pack(side=tk.RIGHT)
        self.save_button.pack(side=tk.LEFT, padx=(0, 5))
        self.regen_all_button.pack(side=tk.LEFT)

        # --- Scrollable container for prompts (this is the main expanding area) ---
        scrollable_prompts_container = ScrollableFrame(main_frame)
        scrollable_prompts_container.grid(row=1, column=0, sticky='nsew')
        prompts_parent_frame = scrollable_prompts_container.scrollable_frame

        # Create all text areas with placeholder content for dynamic fields, inside the scrollable frame
        self._create_text_area(prompts_parent_frame, 'original', "Original Prompt", self.result_data['original'], height=3, has_regen=False, is_loading=False)
        self._create_text_area(prompts_parent_frame, 'enhanced', "Enhanced Prompt", "Generating...", height=6, is_loading=True)

        if self.selected_variations:
            variations_frame = ttk.LabelFrame(prompts_parent_frame, text="Variations", padding="10")
            variations_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            for var_type in self.selected_variations:
                self._create_text_area(variations_frame, var_type, var_type.capitalize(), "Generating...", height=4, is_loading=True)

        self.result_queue_after_id = self.after(100, self._check_result_queue)
        self.protocol("WM_DELETE_WINDOW", self.close)

        # Call smart geometry after creating widgets
        self.smart_geometry(min_width=700, min_height=750)

    def close(self):
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
        self.model_usage_manager.unregister_usage(self.model)
        self.parent_app.report_enhancement_window_closed(self)
        self.destroy()
    
    def _on_model_change(self, new_model: str):
        """Handles when the user selects a new model in the dropdown."""
        old_model = self.model
        if new_model != old_model:
            self.model_usage_manager.unregister_usage(old_model)
            self.model_usage_manager.register_usage(new_model)
            self.model = new_model
            self.regen_all_button.config(state=tk.NORMAL)
    
    def _create_text_area(self, parent, prompt_key: str, title: str, content: str, height: int, is_loading: bool = False, has_regen: bool = True):
        frame = ttk.LabelFrame(parent, text=title, padding="5")
        frame.pack(fill=tk.X, pady=5)
        
        # Frame to hold text and buttons
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.X, expand=True)

        # Use grid layout for robustness
        text_frame.columnconfigure(0, weight=1) # Text area gets all the space
        text_frame.columnconfigure(1, weight=0) # Scrollbar is fixed width
        text_frame.columnconfigure(2, weight=0) # Button container is fixed width

        # Text widget and its scrollbar
        text_widget = tk.Text(text_frame, wrap=tk.WORD, height=height, font=self.parent_app.default_font)
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.config(yscrollcommand=scrollbar.set)
        text_widget.grid(row=0, column=0, sticky='nsew')
        scrollbar.grid(row=0, column=1, sticky='ns')

        text_widget.insert("1.0", content)
        text_widget.config(state=tk.DISABLED)
        self.text_widgets[prompt_key] = text_widget
        TextContextMenu(text_widget)
        
        # Button container
        button_container = ttk.Frame(text_frame)
        button_container.grid(row=0, column=2, sticky='n', padx=(5, 0))
        
        copy_button = ttk.Button(button_container, text="Copy", command=lambda key=prompt_key: self._copy_current_prompt(key))
        copy_button.pack(fill=tk.X)
        self.copy_buttons[prompt_key] = copy_button

        # --- NEW: Edit Button ---
        if prompt_key != 'original':
            edit_button = ttk.Button(button_container, text="Edit", command=lambda key=prompt_key: self._enter_edit_mode(key))
            edit_button.pack(fill=tk.X, pady=(5,0))
            self.edit_buttons[prompt_key] = edit_button

            save_edit_button = ttk.Button(button_container, text="Save", style="Accent.TButton", command=lambda key=prompt_key: self._save_edit(key))
            self.save_edit_buttons[prompt_key] = save_edit_button

            cancel_edit_button = ttk.Button(button_container, text="Cancel", command=lambda key=prompt_key: self._cancel_edit(key))
            self.cancel_edit_buttons[prompt_key] = cancel_edit_button

        # Add Generate Image button for prompts that can be generated (not negative)
        if prompt_key != 'negative':
            image_gen_frame = ttk.Frame(button_container)
            image_gen_frame.columnconfigure(1, weight=1) # Let the button expand
            image_gen_frame.pack(fill=tk.X, pady=(5,0))

            image_gen_spinner = LoadingAnimation(image_gen_frame, size=20)
            image_gen_spinner.grid(row=0, column=0, padx=(0, 5))
            image_gen_spinner.grid_remove() # Hide initially
            self.image_gen_spinners[prompt_key] = image_gen_spinner

            # The button should be enabled if the content is already loaded (i.e., not in a loading state).
            button_state = tk.DISABLED if is_loading else tk.NORMAL
            gen_image_button = ttk.Button(image_gen_frame, text="Generate Image", command=lambda key=prompt_key: self._generate_image(key), state=button_state)
            gen_image_button.grid(row=0, column=1, sticky='ew')
            self.image_gen_buttons[prompt_key] = gen_image_button

        if is_loading:
            # Create spinner and regen button, but only show the spinner initially
            loading_animation = LoadingAnimation(button_container)
            is_dark = self.parent_app.theme_manager.current_theme == "dark"
            status_bar_dot_color = "lightgrey" if is_dark else "dimgray"
            status_bar_bg = self.cget('background')
            loading_animation.update_style(bg_color=status_bar_bg, dot_color=status_bar_dot_color, is_dark_theme=is_dark)
            loading_animation.pack(fill=tk.X, pady=(5,0))
            loading_animation.start()
            self.loading_animations[prompt_key] = loading_animation
            if prompt_key in self.image_gen_buttons:
                self.image_gen_buttons[prompt_key].config(state=tk.DISABLED)
            copy_button.config(state=tk.DISABLED)

        if has_regen:
            regen_button = ttk.Button(button_container, text="Regen", command=lambda key=prompt_key: self._start_regeneration(key))
            # Don't pack the regen button yet
            self.regen_buttons[prompt_key] = regen_button

        # Add LLM label
        model_label = ttk.Label(frame, text=f"LLM: {self.model}", font=self.parent_app.small_font, foreground="gray")
        model_label.pack(anchor='w', padx=5, pady=(2, 0))
        self.sd_model_labels[prompt_key] = model_label

    def _save(self):
        """Save the result to the history, either as a new entry or by updating an existing one."""
        # Add favorite status to the data before saving
        self.result_data['favorite'] = self.is_favorite.get()

        if self.existing_entry_id:
            original_entry = self.processor.history_manager.get_entry_by_id(self.existing_entry_id)
            if not original_entry:
                # Fallback to creating a new entry if the old one is gone for some reason.
                self.processor.history_manager.save_result(**self.result_data)
                custom_dialogs.show_warning(self, "Save Warning", "Could not find the original history entry to update. A new entry has been created instead.")
            else:
                # Merge the new data into the old entry.
                updated_entry = original_entry.copy()
                if 'enhanced' in self.result_data:
                    updated_entry['enhanced'] = self.result_data['enhanced']
                if 'variations' not in updated_entry: updated_entry['variations'] = {}
                updated_entry['variations'].update(self.result_data.get('variations', {}))
                updated_entry['favorite'] = self.is_favorite.get()
                updated_entry['status'] = 'enhanced'
                self.processor.update_history_entry(original_entry, updated_entry)
        else:
            # It's a new entry. Ensure it has an ID before saving.
            if 'id' not in self.result_data:
                self.result_data['id'] = str(uuid.uuid4())
            self.processor.history_manager.save_result(**self.result_data)

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
            content_to_copy = self.result_data.get('enhanced', {}).get('prompt', '')
        elif prompt_key in self.result_data.get('variations', {}):
            content_to_copy = self.result_data['variations'][prompt_key]['prompt']
        
        if content_to_copy:
            self._copy_to_clipboard(content_to_copy)

    def _generate_image(self, prompt_key: str):
        """Opens the options dialog and then starts the image generation process."""
        prompt = ""
        if prompt_key == 'enhanced':
            prompt = self.result_data.get('enhanced', {}).get('prompt', '')
        elif prompt_key in self.result_data.get('variations', {}):
            prompt = self.result_data['variations'][prompt_key].get('prompt', '')
        elif prompt_key == 'original':
            prompt = self.result_data.get('original', '')
        negative_prompt = self.processor.get_default_negative_prompt_text()
        
        if not prompt:
            custom_dialogs.show_error(self, "Error", "No prompt available to generate an image.")
            return

        def on_success(images_to_save: List[Dict[str, Any]]):
            """Callback to handle saving image data to the result_data object."""
            # --- NEW: Determine the entry ID ---
            # If we are updating an existing entry, use its ID. Otherwise, ensure one exists for a new entry.
            if self.existing_entry_id:
                entry_id = self.existing_entry_id
            else:
                # If it's a new entry, it might not have an ID yet.
                if 'id' not in self.result_data:
                    self.result_data['id'] = str(uuid.uuid4())
                entry_id = self.result_data['id']

            saved_images_data = [{'image_path': self.processor.save_generated_image(img['bytes'], entry_id), 'generation_params': img.get('generation_params')} for img in images_to_save]
            
            if prompt_key == 'original':
                self.result_data['original_images'] = saved_images_data
            elif prompt_key == 'enhanced':
                if 'enhanced' not in self.result_data: self.result_data['enhanced'] = {}
                self.result_data['enhanced']['images'] = saved_images_data
            elif prompt_key in self.result_data.get('variations', {}):
                self.result_data['variations'][prompt_key]['images'] = saved_images_data
            
            self.processor.clear_avg_gen_times_cache()
            custom_dialogs.show_info(self, "Image Saved", f"{len(saved_images_data)} image(s) saved for '{prompt_key}' prompt.\n\nPath(s) will be stored when you save to history.")
            button = self.image_gen_buttons.get(prompt_key)
            if button: button.config(text=f"Regen Image(s) ({len(saved_images_data)})")

        button = self.image_gen_buttons.get(prompt_key)
        self.parent_app._start_image_generation_workflow(
            parent_window=self,
            prompt=prompt,
            initial_dialog_params={'negative_prompt': negative_prompt},
            button_to_manage=button,
            spinner_to_manage=self.image_gen_spinners.get(prompt_key),
            on_success_callback=on_success
        )

    def _regenerate_all(self):
        """Starts the regeneration process for all prompts in the window."""
        keys_to_regen = ['enhanced'] + self.selected_variations
        
        if not keys_to_regen:
            return
            
        # Disable the button to prevent spamming
        self.regen_all_button.config(state=tk.DISABLED)
            
        for key in keys_to_regen:
            # Check if the regen button for this key is visible (i.e., not already regenerating)
            if key in self.regen_buttons and self.regen_buttons[key].winfo_ismapped():
                self._start_regeneration(key)

    def _start_regeneration(self, prompt_key: str):
        """Starts the regeneration process for a specific prompt in a background thread."""
        # Notify the parent app to update its counters and status
        self.parent_app.register_regeneration_call(prompt_key)

        # Hide regen button and show spinner
        self.regen_buttons[prompt_key].pack_forget()
        self.loading_animations[prompt_key].pack(fill=tk.X, pady=(5,0))
        self.regen_queue = queue.Queue()
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
                new_prompt = self.processor.regenerate_enhancement(
                    self.result_data['original'], self.model
                )
                result = {'key': prompt_key, 'prompt': new_prompt, 'ollama_model': self.model}
            else: # It's a variation
                # Use the ENHANCED prompt as the base for regenerating a variation for better context.
                base_prompt_for_variation = self.result_data.get('enhanced', {}).get('prompt')
                # Fallback to original prompt if enhanced isn't available yet.
                if not base_prompt_for_variation:
                    base_prompt_for_variation = self.result_data.get('original', '')
                original_prompt_for_context = self.result_data.get('original', '')
                if not base_prompt_for_variation: raise ValueError("Base prompt not found to generate variation from.")
                variation_result = self.processor.regenerate_variation(base_prompt_for_variation, self.model, prompt_key, original_prompt_context=original_prompt_for_context)
                result = {'key': prompt_key, 'prompt': variation_result['prompt'], 'ollama_model': self.model}
            self.regen_queue.put(result)
        except Exception as e:
            self.regen_queue.put({'key': prompt_key, 'error': str(e)})

    def _check_regen_queue(self):
        """Checks for regeneration results and updates the UI."""
        if not self.winfo_exists():
            return

        try:
            result = self.regen_queue.get_nowait()
            key = result.get('key')
            if not key: return # Cannot proceed without a key

            # --- Safely update UI ---
            spinner = self.loading_animations.get(key)
            regen_button = self.regen_buttons.get(key)
            if spinner:
                spinner.stop()
                spinner.pack_forget()
            if regen_button:
                regen_button.pack(fill=tk.X, pady=(5,0))
            
            if 'error' in result:
                custom_dialogs.show_error(self, "Regeneration Error", result['error'])
                self.parent_app.report_regeneration_finished(success=False)
            else:
                new_prompt = result.get('prompt')
                if new_prompt is None: return

                new_ollama_model = result.get('ollama_model', self.model)
                
                # Update UI
                text_widget = self.text_widgets.get(key)
                if text_widget:
                    text_widget.config(state=tk.NORMAL)
                    text_widget.delete("1.0", tk.END)
                    text_widget.insert("1.0", new_prompt)
                    text_widget.config(state=tk.DISABLED)
                
                model_label = self.sd_model_labels.get(key)
                if model_label:
                    model_label.config(text=f"LLM: {new_ollama_model}")
                
                # Update internal data for saving
                if key == 'enhanced':
                    self.result_data['enhanced'] = {'prompt': new_prompt, 'ollama_model': new_ollama_model}
                else:
                    self.result_data['variations'][key] = {'prompt': new_prompt, 'ollama_model': new_ollama_model}
                
                self.parent_app.report_regeneration_finished(success=True)
            
            self._check_and_enable_regen_all_button()
            
        except queue.Empty:
            pass
        except Exception as e:
            # Add a general exception handler to prevent the loop from dying silently.
            print(f"ERROR: Unhandled exception in _check_regen_queue: {e}")
            traceback.print_exc()
        finally:
            if self.winfo_exists():
                self.regen_queue_after_id = self.after(100, self._check_regen_queue)

    def _check_result_queue(self):
        """Checks for incoming results from the main processing thread and updates the UI."""
        if not self.winfo_exists():
            return

        try:
            key, data = self.result_queue.get_nowait()
            
            # --- Handle the result for the specific key (enhanced or a variation) ---
            self.text_widgets[key].config(state=tk.NORMAL)
            self.text_widgets[key].delete("1.0", tk.END)
            self.text_widgets[key].insert("1.0", data['prompt'])
            self.text_widgets[key].config(state=tk.DISABLED)
            
            if key in self.sd_model_labels:
                ollama_model_text = data.get('ollama_model', self.model)
                self.sd_model_labels[key].config(text=f"LLM: {ollama_model_text}")
            
            # Stop the spinner and show the regen button if it exists
            if key in self.loading_animations:
                self.loading_animations[key].stop()
                self.loading_animations[key].pack_forget()
            if key in self.regen_buttons:
                self.regen_buttons[key].pack(fill=tk.X, pady=(5,0))
            if key in self.copy_buttons:
                self.copy_buttons[key].config(state=tk.NORMAL)
            # Enable the Generate Image button if it exists for this key
            if key in self.image_gen_buttons:
                self.image_gen_buttons[key].config(state=tk.NORMAL)


            # --- Special handling when the main enhancement result arrives ---
            if key == 'enhanced':
                # Store the entire data object for the enhanced prompt
                self.result_data['enhanced'] = data

                if self.save_button:
                    self.save_button.config(state=tk.NORMAL)
                if hasattr(self, 'regen_all_button'):
                    self.regen_all_button.config(state=tk.NORMAL)
            else:
                self.result_data['variations'][key] = data

            # Notify parent that an API call has finished
            self.api_call_finish_callback()

        except queue.Empty:
            pass # No new results yet
        except tk.TclError:
            # This can happen if the window is destroyed while the queue is being processed.
            # We can safely ignore it and stop the loop.
            return
        finally:
            if self.winfo_exists():
                self.result_queue_after_id = self.after(100, self._check_result_queue)

    def _check_and_enable_regen_all_button(self):
        """Checks if all individual regeneration spinners are gone and re-enables the main button."""
        if not hasattr(self, 'regen_all_button'):
            return

        # Check if any loading animation is still visible
        is_any_loading = any(spinner.winfo_ismapped() for spinner in self.loading_animations.values())
        
        if not is_any_loading:
            self.regen_all_button.config(state=tk.NORMAL)

    def _enter_edit_mode(self, prompt_key: str):
        """Enables editing for a specific prompt text widget."""
        text_widget = self.text_widgets.get(prompt_key)
        if not text_widget: return

        # Store original content for cancellation
        self.original_edit_content[prompt_key] = text_widget.get("1.0", "end-1c")
        
        text_widget.config(state=tk.NORMAL)
        text_widget.focus_set()

        # Swap buttons
        self.edit_buttons[prompt_key].pack_forget()
        self.save_edit_buttons[prompt_key].pack(fill=tk.X, pady=(5,0))
        self.cancel_edit_buttons[prompt_key].pack(fill=tk.X, pady=(2,0))

    def _save_edit(self, prompt_key: str):
        """Saves the edited prompt to the internal data structure."""
        text_widget = self.text_widgets.get(prompt_key)
        if not text_widget: return

        new_text = text_widget.get("1.0", "end-1c").strip()
        
        # Update internal data
        if prompt_key == 'enhanced':
            if 'enhanced' not in self.result_data: self.result_data['enhanced'] = {}
            self.result_data['enhanced']['prompt'] = new_text
        elif prompt_key in self.result_data.get('variations', {}):
            self.result_data['variations'][prompt_key]['prompt'] = new_text
        
        # Exit edit mode
        self._exit_edit_mode(prompt_key)

    def _cancel_edit(self, prompt_key: str):
        """Cancels editing and reverts the text."""
        text_widget = self.text_widgets.get(prompt_key)
        original_text = self.original_edit_content.get(prompt_key)
        if not text_widget or original_text is None: return

        text_widget.config(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        text_widget.insert("1.0", original_text)
        
        # Exit edit mode
        self._exit_edit_mode(prompt_key)

    def _exit_edit_mode(self, prompt_key: str):
        """Helper to revert UI state after editing is done."""
        text_widget = self.text_widgets.get(prompt_key)
        if not text_widget: return

        text_widget.config(state=tk.DISABLED)

        # Swap buttons back
        self.save_edit_buttons[prompt_key].pack_forget()
        self.cancel_edit_buttons[prompt_key].pack_forget()
        self.edit_buttons[prompt_key].pack(fill=tk.X, pady=(5,0))

        # Clean up stored original content
        if prompt_key in self.original_edit_content:
            del self.original_edit_content[prompt_key]