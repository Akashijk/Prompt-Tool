"""An interactive window for brainstorming with an AI model."""

import tkinter.font as tkfont
import tkinter as tk
from tkinter import ttk
import queue
import threading
import json
import re
import random
from typing import Optional, List, Dict, Callable, Tuple, TYPE_CHECKING

from core.prompt_processor import PromptProcessor
from core.config import config
from core.ollama_client import sanitize_wildcard_choices
from . import custom_dialogs, wildcard_editor_widget
from .review_window import ReviewAndSaveWindow
from .common import BrainstormingContextMenu, TextContextMenu, SmartWindowMixin

if TYPE_CHECKING:
    from .gui_app import GUIApp
    from .model_usage_manager import ModelUsageManager

class _AskLinkedWildcardTopicsDialog(custom_dialogs._CustomDialog):
    """A dialog to get topics for linked wildcard generation."""
    def __init__(self, parent):
        super().__init__(parent, "Generate Linked Wildcards")

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="This will generate two linked wildcard files. The primary file will be prompted to 'include' choices from the supporting file.", wraplength=350).pack(pady=(0, 15), anchor='w')

        ttk.Label(main_frame, text="Primary Topic (e.g., 'character poses'):").pack(anchor='w')
        self.primary_entry = ttk.Entry(main_frame, width=50)
        self.primary_entry.pack(pady=(0, 10), fill=tk.X, expand=True)
        self.primary_entry.focus_set()

        ttk.Label(main_frame, text="Supporting Topic (e.g., 'handheld weapons'):").pack(anchor='w')
        self.supporting_entry = ttk.Entry(main_frame, width=50)
        self.supporting_entry.pack(pady=(0, 20), fill=tk.X, expand=True)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        ok_button = ttk.Button(button_frame, text="Generate", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5, 0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self._center_window()
        self.wait_window(self)

    def _on_ok(self, event=None):
        primary = self.primary_entry.get().strip()
        supporting = self.supporting_entry.get().strip()
        if primary and supporting:
            self.result = (primary, supporting)
        self.destroy()

class BrainstormingWindow(tk.Toplevel, SmartWindowMixin):
    """An interactive window for brainstorming with an AI model."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor, models: List[str], default_model: str, model_usage_manager: 'ModelUsageManager', update_callback: Callable):
        super().__init__(parent)
        self.title("AI Brainstorming Session")

        self.parent_app = parent
        self.processor = processor
        self.update_callback = update_callback
        self.models = models
        self.chat_queue = queue.Queue()
        self.model_usage_manager = model_usage_manager
        self.active_brainstorm_model: Optional[str] = None
        self.conversation_history: List[Dict[str, str]] = []
        self.after_id: Optional[str] = None
        self.suggestion_queue = queue.Queue()
        self.suggestion_after_id: Optional[str] = None

        # --- Widgets ---
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill=tk.X)
        ttk.Label(top_frame, text="Model:").pack(side=tk.LEFT)
        self.model_var = tk.StringVar(value=default_model)
        model_menu = ttk.OptionMenu(top_frame, self.model_var, default_model, *models, style="Toolbutton")
        self.model_var.trace_add("write", self._on_model_var_change)
        model_menu.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(top_frame, text="Generate Wildcard File...", command=self._generate_wildcard_file).pack(side=tk.LEFT)
        ttk.Button(top_frame, text="Generate Template File...", command=self._generate_template_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="Generate Linked Wildcards...", command=self._generate_linked_wildcard_files).pack(side=tk.LEFT)

        main_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # --- Conversation History ---
        history_frame = ttk.LabelFrame(main_pane, text="Conversation History", padding=5)
        main_pane.add(history_frame, weight=4)

        history_scroll_frame = ttk.Frame(history_frame)
        history_scroll_frame.pack(fill=tk.BOTH, expand=True)
        history_scrollbar = ttk.Scrollbar(history_scroll_frame, orient=tk.VERTICAL)
        self.history_text = tk.Text(history_scroll_frame, wrap=tk.WORD, state=tk.DISABLED, font=self.parent_app.default_font, yscrollcommand=history_scrollbar.set)
        history_scrollbar.config(command=self.history_text.yview)
        history_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.history_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        BrainstormingContextMenu(self.history_text, self._rewrite_selection)

        self.history_text.tag_configure("user", foreground="blue", font=tkfont.Font(family="Helvetica", size=config.font_size, weight="bold"))
        self.history_text.tag_configure("ai", foreground="#006400")
        self.history_text.tag_configure("error", foreground="red", font=tkfont.Font(family="Helvetica", size=config.font_size, weight="bold"))
        self.history_text.tag_configure("thinking", foreground="gray", font=tkfont.Font(family="Helvetica", size=config.font_size, slant="italic"))
        self.history_text.tag_configure("new_wildcard_link", foreground="#FFB000", underline=True)
        self.history_text.tag_bind("new_wildcard_link", "<Enter>", lambda e: self.history_text.config(cursor="hand2"))
        self.history_text.tag_bind("new_wildcard_link", "<Leave>", lambda e: self.history_text.config(cursor=""))

        # --- Input Area ---
        input_area_frame = ttk.LabelFrame(main_pane, text="Your Message (Enter to send, Shift+Enter for new line)", padding=5)
        main_pane.add(input_area_frame, weight=1)

        self.input_text = tk.Text(input_area_frame, height=4, wrap=tk.WORD, font=self.parent_app.default_font, exportselection=False)
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.input_text.bind("<Return>", self._on_send_message_event)
        TextContextMenu(self.input_text)
        
        button_container = ttk.Frame(input_area_frame)
        button_container.pack(side=tk.LEFT, padx=(10, 0), fill=tk.Y)

        self.send_button = ttk.Button(button_container, text="Send", command=self._send_message)
        self.send_button.pack(fill=tk.X)
        self.suggest_button = ttk.Button(button_container, text="Suggest Reply", command=self._suggest_reply)
        self.suggest_button.pack(fill=tk.X, pady=(5,0))
        
        self._add_message("AI", "Hello! How can I help you brainstorm today? You can ask me to improve a list of wildcards, create a new template, or anything else you can think of.", "ai")

        # Register initial model usage
        self.active_brainstorm_model = default_model
        self.model_usage_manager.register_usage(self.active_brainstorm_model)

        self.smart_geometry(min_width=800, min_height=600)

    def _configure_tags(self):
        """Configures the text tags for the conversation history."""
        is_dark = self.parent_app.theme_manager.current_theme == "dark"

        user_fg = "#87CEFA" if is_dark else "blue" # Light blue / Blue
        ai_fg = "#90EE90" if is_dark else "#006400" # Light green / Dark green
        error_fg = "#F08080" if is_dark else "red" # Light coral / Red
        thinking_fg = "#A9A9A9" if is_dark else "gray" # Dark gray / Gray
        link_fg = "#FFD700" if is_dark else "#FFB000" # Gold / Darker Gold

        bold_font = tkfont.Font(family="Helvetica", size=config.font_size, weight="bold")
        italic_font = tkfont.Font(family="Helvetica", size=config.font_size, slant="italic")

        self.history_text.tag_configure("user", foreground=user_fg, font=bold_font)
        self.history_text.tag_configure("ai", foreground=ai_fg)
        self.history_text.tag_configure("error", foreground=error_fg, font=bold_font)
        self.history_text.tag_configure("thinking", foreground=thinking_fg, font=italic_font)
        self.history_text.tag_configure("new_wildcard_link", foreground=link_fg, underline=True)
        self.history_text.tag_bind("new_wildcard_link", "<Enter>", lambda e: self.history_text.config(cursor="hand2"))
        self.history_text.tag_bind("new_wildcard_link", "<Leave>", lambda e: self.history_text.config(cursor=""))

    def close(self):
        """Safely close the window, cancelling any pending after() jobs."""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        if self.suggestion_after_id:
            self.after_cancel(self.suggestion_after_id)
            self.suggestion_after_id = None
        
        # Unregister the model used by this window before destroying it
        self.model_usage_manager.unregister_usage(self.active_brainstorm_model)
        
        self.destroy()

    def update_theme(self):
        """Updates the tag colors to match the current theme."""
        self._configure_tags()
    def _handle_wildcard_link_click(self, wildcard_name: str, tag_name: str):
        """Handles a click on a new wildcard link, disabling it and starting generation."""
        # Disable the link to prevent multiple clicks
        self.history_text.tag_config(tag_name, foreground="gray", underline=False)
        self.history_text.tag_unbind(tag_name, "<Button-1>")
        
        self.generate_wildcard_with_topic(wildcard_name)

    def _on_send_message_event(self, event):
        # If shift is pressed, allow default newline behavior. Otherwise, send message.
        if event.state & 1:
            return
        else:
            self._send_message()
            return "break"

    def _send_message(self):
        user_prompt = self.input_text.get("1.0", "end-1c").strip()
        if not user_prompt: return

        model = self.model_var.get()

        # Add to conversation history BEFORE making the call
        self.conversation_history.append({'role': 'user', 'content': user_prompt})

        self._add_message("User", user_prompt, "user")
        self.input_text.delete("1.0", tk.END)
        self.send_button.config(state=tk.DISABLED)
        self._add_message("AI", "Thinking...", "thinking")
        self.suggest_button.config(state=tk.DISABLED)

        thread = threading.Thread(target=self._get_ai_response, args=(model,), daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_chat_queue)

    def _get_ai_response(self, model: str):
        try:
            response = self.processor.chat_with_model(model, self.conversation_history)
            self.chat_queue.put({'response': response, 'tag': 'ai'})
        except Exception as e:
            self.chat_queue.put({'response': f"An error occurred: {e}", 'tag': 'error'})

    def _get_initial_ai_response(self, model: str):
        """Gets the first AI response after a system prompt is loaded."""
        try:
            # The history already contains the system prompt.
            response = self.processor.chat_with_model(model, self.conversation_history)
            self.chat_queue.put({'response': response, 'tag': 'ai'})
        except Exception as e:
            self.chat_queue.put({'response': f"An error occurred: {e}", 'tag': 'error'})

    def _check_chat_queue(self):
        try:
            result = self.chat_queue.get_nowait()
            
            # The 'rewrite' action manages its own placeholder text and does not append a "Thinking..." message.
            # All other actions do, so we remove it before processing the result for those cases.
            is_rewrite_action = result.get('tag') == 'ai_generated' and result.get('content_type') == 'rewrite'

            if not is_rewrite_action:
                self.history_text.config(state=tk.NORMAL)
                self.history_text.delete("end-2l", "end-1c") # Remove the "Thinking..." line
                self.history_text.config(state=tk.DISABLED)

            # Handle errors first, especially for generation tasks
            if result.get('tag') == 'error':
                metadata = result.get('metadata')
                # If the error came from a task that opened a window, close it.
                if metadata and metadata.get('window'):
                    window = metadata.get('window')
                    if window and window.winfo_exists():
                        window.destroy()
                
                # Display the error in the chat window
                self._add_message("System", f"Error during generation: {result.get('response')}", "error")

            elif is_rewrite_action or result.get('tag') == 'ai_generated':
                content_type = result.get('content_type')
                response = result.get('response', '')
                metadata = result.get('metadata')
                if content_type == 'template':
                    template, new_wildcards = response # The response is now a tuple
                    self._handle_generated_template(template, new_wildcards, metadata)
                elif content_type == 'wildcard': # The response is now pre-parsed JSON
                    self._handle_generated_wildcard(response, metadata)
                elif content_type == 'rewrite':
                    if metadata:
                        self._handle_rewritten_text(response, metadata['start_index'], metadata['end_index'])
            else:
                # Handle regular chat or errors
                response_text = result['response']
                tag = result['tag']
                # Add AI response to history if it's not an error
                if tag == 'ai':
                    self.conversation_history.append({'role': 'assistant', 'content': response_text})
                self._add_message("AI", response_text, tag)
            
            self.suggest_button.config(state=tk.NORMAL)
            self.send_button.config(state=tk.NORMAL)
        except queue.Empty:
            self.after_id = self.after(100, self._check_chat_queue)

    def _suggest_reply(self):
        """Starts the AI suggestion process for a chat reply."""
        self.suggest_button.config(state=tk.DISABLED, text="Suggesting...")
        
        def task():
            try:
                model = self.model_var.get()
                if not model or "model" in model.lower():
                    raise Exception("Please select a valid Ollama model.")
                
                suggestion = self.processor.suggest_chat_reply(self.conversation_history, model)
                self.suggestion_queue.put({'success': True, 'suggestion': suggestion})
            except Exception as e:
                self.suggestion_queue.put({'success': False, 'error': str(e)})
        
        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.suggestion_after_id = self.after(100, self._check_suggestion_queue)

    def _check_suggestion_queue(self):
        """Checks for AI reply suggestions and updates the input box."""
        try:
            result = self.suggestion_queue.get_nowait()
            self.suggest_button.config(state=tk.NORMAL, text="Suggest Reply")
            
            if result['success']:
                self.input_text.delete("1.0", tk.END)
                self.input_text.insert("1.0", result.get('suggestion', ''))
            else:
                custom_dialogs.show_error(self, "Suggestion Error", f"An error occurred while generating a suggestion:\n{result['error']}")
        except queue.Empty:
            self.suggestion_after_id = self.after(100, self._check_suggestion_queue)

    def _add_message(self, sender, message, tag):
        self.history_text.config(state=tk.NORMAL)
        if self.history_text.get("1.0", "end-1c"):
            self.history_text.insert(tk.END, "\n\n")
        
        self.history_text.insert(tk.END, f"{sender}:\n", (tag,))
        self.history_text.insert(tk.END, message)
        self.history_text.see(tk.END)
        self.history_text.config(state=tk.DISABLED)

    def load_content_for_brainstorming(self, content_type: str, filename: str, content: str):
        """Loads existing content into the chat window for refinement."""
        # Clear previous session
        self.history_text.config(state=tk.NORMAL)
        self.history_text.delete("1.0", tk.END)
        self.history_text.config(state=tk.DISABLED)
        self.conversation_history.clear()

        system_prompt = (
            f"You are an AI assistant helping a user brainstorm content for a Stable Diffusion prompt generator. "
            f"The user has loaded the following {content_type} named '{filename}'. Your task is to act as an expert collaborator. "
            f"Analyze the content and start the conversation by asking a helpful, targeted question about how the user wants to improve or expand upon it. "
            f"Be proactive and suggest a potential first step.\n\n"
            f"LOADED CONTENT:\n"
            f"----------------\n"
            f"{content}\n"
            f"----------------"
        )
        self.conversation_history.append({'role': 'system', 'content': system_prompt})

        # Display a simplified message to the user
        user_facing_message = f"Loaded {content_type} '{filename}' for brainstorming. The AI is reviewing it and will start the conversation."
        self._add_message("System", user_facing_message, "thinking")
        
        # Start the AI's response
        model = self.model_var.get()
        self.send_button.config(state=tk.DISABLED)
        self._add_message("AI", "Thinking...", "thinking")
        
        thread = threading.Thread(target=self._get_initial_ai_response, args=(model,), daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_chat_queue)

    def _generate_wildcard_file(self):
        """Guides the user to generate a new wildcard file."""
        topic = custom_dialogs.ask_string(self, "Generate Wildcard", "What is the topic for the new wildcard file?\n(e.g., 'sci-fi helmet designs', 'fantasy potion names')")
        self.generate_wildcard_with_topic(topic)

    def _generate_linked_wildcard_files(self):
        """Orchestrates the two-step generation of linked wildcard files."""
        dialog = _AskLinkedWildcardTopicsDialog(self)
        if not dialog.result:
            return

        primary_topic, supporting_topic = dialog.result

        # Define the second step of the process
        def generate_primary_wildcard(supporting_filename: str):
            # Force a reload of wildcards so the newly created one is available.
            self.processor.reload_wildcards()
            # The main app's UI also needs to be refreshed.
            self.update_callback('wildcard')

            custom_dialogs.show_info(
                self, 
                "Step 2: Primary Wildcard", 
                f"Now we will generate the primary wildcard '{primary_topic}', which will be encouraged to use the supporting wildcard you just saved."
            )
            self.generate_wildcard_with_topic(primary_topic, supporting_wildcard_to_include=supporting_filename)

        # Start the first step
        custom_dialogs.show_info(
            self, 
            "Step 1: Supporting Wildcard", 
            f"First, we will generate the supporting wildcard: '{supporting_topic}'.\n\nPlease review and save it. The primary wildcard generation will begin automatically after you save."
        )
        self.generate_wildcard_with_topic(supporting_topic, next_step_callback=generate_primary_wildcard)

    def generate_wildcard_with_topic(self, topic: str, filename: Optional[str] = None, existing_window: Optional[ReviewAndSaveWindow] = None, next_step_callback: Optional[Callable] = None, supporting_wildcard_to_include: Optional[str] = None):
        """Starts the generation process for a wildcard with a given topic."""
        if not topic:
            return

        final_filename = filename if filename is not None else topic

        # Create or get the results window first with a loading state.
        metadata = {'filename': final_filename, 'topic': topic, 'window': existing_window, 'next_step_callback': next_step_callback, 'supporting_wildcard_to_include': supporting_wildcard_to_include}
        results_window = self._handle_generated_content("", "wildcard", metadata)
        metadata['window'] = results_window

        self._add_message("AI", f"Generating wildcard ideas for '{topic}'...", "thinking")
        # The task now just needs the topic, not the full prompt.
        # The processor will build the full prompt internally.
        self._run_generation_task(topic, "wildcard", metadata=metadata)

    def _generate_template_file(self):
        """Guides the user to generate a new template file."""
        concept = custom_dialogs.ask_string(self, "Generate Template", "What is the high-level concept for the new template?\n(e.g., 'a character portrait in a dark forest', 'a futuristic city street scene')")
        self.generate_template_with_concept(concept)

    def generate_template_with_concept(self, concept: str, existing_window: Optional[ReviewAndSaveWindow] = None):
        """Starts the generation process for a template with a given concept."""
        if not concept:
            return

        # Create or get the results window first with a loading state.
        metadata = {'concept': concept, 'window': existing_window}
        results_window = self._handle_generated_content("", "template", metadata)
        metadata['window'] = results_window
        self._add_message("AI", f"Generating a template for '{concept}'...", "thinking")
        # The task now just needs the concept, not the full prompt.
        # The processor will build the full prompt internally.
        self._run_generation_task(concept, "template", metadata=metadata)

    def _run_generation_task(self, prompt_or_topic: str, content_type: str, metadata: Optional[Dict] = None):
        """Runs a generation task in a background thread."""
        model = self.model_var.get()
        self.send_button.config(state=tk.DISABLED)

        def task():
            try:
                # Use the one-shot generation method which builds the prompt internally
                if content_type == 'wildcard':
                    # The processor method now takes the topic and metadata directly
                    response = self.processor.generate_wildcard_for_brainstorming(model, prompt_or_topic, metadata)
                    self.chat_queue.put({'response': response, 'tag': 'ai_generated', 'content_type': content_type, 'metadata': metadata})
                elif content_type == 'template':
                    # The processor method now takes the concept directly
                    template, new_wildcards = self.processor.generate_template_for_brainstorming(model, prompt_or_topic)
                    self.chat_queue.put({'response': (template, new_wildcards), 'tag': 'ai_generated', 'content_type': content_type, 'metadata': metadata})
                elif content_type == 'rewrite':
                    if not metadata: return
                    selected_text = metadata.get('selected_text', '')
                    instructions = metadata.get('instructions', '')
                    response = self.processor.rewrite_text(selected_text, instructions, model)
                    self.chat_queue.put({'response': response, 'tag': 'ai_generated', 'content_type': content_type, 'metadata': metadata})
            except Exception as e:
                # Pass metadata along with the error so we can handle the UI correctly
                self.chat_queue.put({'response': f"An error occurred: {e}", 'tag': 'error', 'metadata': metadata})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_chat_queue)

    def _rewrite_selection(self):
        """Handles the AI-powered rewriting of selected text in the history."""
        try:
            start_index = self.history_text.index("sel.first")
            end_index = self.history_text.index("sel.last")
            selected_text = self.history_text.get(start_index, end_index)
        except tk.TclError:
            return # No selection

        instructions = custom_dialogs.ask_string(
            self,
            "Rewrite with AI",
            "How should I rewrite the selected text?\n(e.g., 'make it more poetic', 'add more technical terms')"
        )
        if not instructions: return

        # Replace selected text with a loading message
        self.history_text.config(state=tk.NORMAL)
        self.history_text.delete(start_index, end_index)
        placeholder = f"[Rewriting to '{instructions}'...]"
        self.history_text.insert(start_index, placeholder, ("thinking",))
        new_end_index = self.history_text.index(f"{start_index} + {len(placeholder)}c")
        self.history_text.config(state=tk.DISABLED)
        
        # Pass the raw components to the generation task
        metadata = {
            'start_index': start_index, 
            'end_index': new_end_index,
            'selected_text': selected_text,
            'instructions': instructions
        }
        self._run_generation_task("", "rewrite", metadata=metadata)

    def _handle_generated_wildcard(self, parsed_json_string: str, metadata: Optional[Dict] = None):
        """Handles the display of a newly generated wildcard and its new 'includes'."""
        try:
            # --- Programmatic Linking ---
            # If this generation was for a linked wildcard, inject the 'includes' key.
            if metadata and metadata.get('supporting_wildcard_to_include'):
                wildcard_data = json.loads(parsed_json_string)
                supporting_filename = metadata['supporting_wildcard_to_include']
                supporting_basename, _ = os.path.splitext(supporting_filename)
                
                # Add it to the global includes.
                if 'includes' not in wildcard_data or not isinstance(wildcard_data.get('includes'), list):
                    wildcard_data['includes'] = []
                
                if supporting_basename not in wildcard_data['includes']:
                    wildcard_data['includes'].append(supporting_basename)
                
                parsed_json_string = json.dumps(wildcard_data, indent=2)

            wildcard_data = json.loads(parsed_json_string)
            included_wildcards = set()
            for choice in wildcard_data.get('choices', []):
                if isinstance(choice, dict) and 'includes' in choice:
                    for included_wc in choice['includes']:
                        included_wildcards.add(included_wc)
            
            existing_wildcards = set(self.processor.get_wildcard_names())
            genuinely_new_wildcards = sorted(list(included_wildcards - existing_wildcards))
            
            # Build the message
            message = "Generated a new wildcard. See the new window to review and save."
            if genuinely_new_wildcards:
                message += "\n\nThis wildcard includes other wildcards that don't exist yet. Click any link to generate them:"
                self._add_message("AI", message, "ai")
                
                # Add the links
                self.history_text.config(state=tk.NORMAL)
                self.history_text.insert(tk.END, "\n")
                for i, wc in enumerate(genuinely_new_wildcards):
                    tag_name = f"new_wc_{wc}_{i}" # Unique tag
                    self.history_text.insert(tk.END, wc, ("new_wildcard_link", tag_name))
                    self.history_text.tag_bind(tag_name, "<Button-1>", lambda e, w=wc, t=tag_name: self._handle_wildcard_link_click(w, t))
                    if i < len(genuinely_new_wildcards) - 1:
                        self.history_text.insert(tk.END, ", ")
                self.history_text.config(state=tk.DISABLED)
            else:
                self._add_message("AI", message, "ai")

        except json.JSONDecodeError:
            # If JSON is invalid, just show the basic message
            self._add_message("AI", f"Generated a new wildcard. See the new window to review and save.", "ai")

        self._handle_generated_content(parsed_json_string, 'wildcard', metadata)

    def _handle_generated_template(self, template: str, new_wildcards: List[str], metadata: Optional[Dict] = None):
        """Handles the display of a newly generated template and its new wildcards."""
        # Get the ground truth of all currently loaded wildcards.
        existing_wildcards = set(self.processor.get_wildcard_names())
        
        # Find all wildcards used in the template to be safe
        used_wildcards = set(re.findall(r'__([a-zA-Z0-9_.\s-]+?)__', template))
        
        # Combine the AI's list with the parsed list, and then find what's genuinely new.
        all_potential_new = set(new_wildcards) | used_wildcards
        genuinely_new_wildcards = sorted(list(all_potential_new - existing_wildcards))

        self.history_text.config(state=tk.NORMAL)
        
        # Add the main message and the generated template
        self.history_text.insert(tk.END, "AI:\n", ("ai",))
        self.history_text.insert(tk.END, "Generated a new template. See below to review and save. ")
        
        if genuinely_new_wildcards:
            self.history_text.insert(tk.END, "Click any new wildcard links to generate content for them.\n\n")
            self.history_text.insert(tk.END, "New Wildcards to Generate:\n")
            for i, wc in enumerate(genuinely_new_wildcards):
                tag_name = f"new_wc_{wc}_{i}" # Unique tag
                self.history_text.insert(tk.END, wc, ("new_wildcard_link", tag_name))
                # Use a default argument in lambda to capture the current value of wc
                self.history_text.tag_bind(tag_name, "<Button-1>", lambda e, w=wc, t=tag_name: self._handle_wildcard_link_click(w, t))
                if i < len(genuinely_new_wildcards) - 1:
                    self.history_text.insert(tk.END, ", ")
            self.history_text.insert(tk.END, "\n\n")

        self.history_text.insert(tk.END, "Template:\n")
        self.history_text.insert(tk.END, template)
        
        self.history_text.see(tk.END)
        self.history_text.config(state=tk.DISABLED)

        # Open the review window for the template itself
        self._handle_generated_content(template, 'template', metadata)

    def _handle_rewritten_text(self, rewritten_text: str, start_index: str, end_index: str):
        """Replaces the selected text with the AI's rewritten version."""
        self.history_text.config(state=tk.NORMAL)
        self.history_text.delete(start_index, end_index)
        self.history_text.insert(start_index, rewritten_text)
        self.history_text.config(state=tk.DISABLED)
    def _handle_generated_content(self, content: str, content_type: str, metadata: Optional[Dict] = None, next_step_callback: Optional[Callable] = None) -> ReviewAndSaveWindow:
        """
        Opens or updates the review window for newly generated content.
        If content is empty, it creates the window in a loading state.
        Returns the window instance.
        """
        # Prioritize callback from metadata if it exists (for linked generation)
        final_next_step_callback = metadata.get('next_step_callback') if metadata else next_step_callback
        existing_window = metadata.get('window') if metadata else None

        if existing_window and existing_window.winfo_exists():
            if content:  # Only update if we have new content to show
                existing_window.update_content(content)
            existing_window.lift()
            return existing_window
        else:
            filename = metadata.get('filename') if metadata else None
            regenerate_callback = None
            if metadata:
                if content_type == 'wildcard' and 'topic' in metadata:
                    original_filename = metadata.get('filename')
                    regenerate_callback = lambda win: self.generate_wildcard_with_topic(metadata['topic'], filename=original_filename, existing_window=win)
                elif content_type == 'template' and 'concept' in metadata:
                    regenerate_callback = lambda win: self.generate_template_with_concept(metadata['concept'], win)

            # If content is empty, is_loading will be True.
            window = ReviewAndSaveWindow(self, self.processor, content_type, content or "", self.update_callback, filename=filename, regenerate_callback=regenerate_callback, is_loading=not bool(content), next_step_callback=final_next_step_callback)
            return window

    def _on_model_var_change(self, *args):
        """Handles when the user selects a new model in the dropdown."""
        new_model = self.model_var.get()
        old_model = self.active_brainstorm_model
        if new_model and new_model != old_model:
            self.model_usage_manager.unregister_usage(old_model)
            self.model_usage_manager.register_usage(new_model)
            self.active_brainstorm_model = new_model