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
from . import custom_dialogs
from .review_window import ReviewAndSaveWindow
from .common import BrainstormingContextMenu, TextContextMenu, SmartWindowMixin

if TYPE_CHECKING:
    from .gui_app import GUIApp


class BrainstormingWindow(tk.Toplevel, SmartWindowMixin):
    """An interactive window for brainstorming with an AI model."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor, models: List[str], default_model: str, model_change_callback: Callable, update_callback: Callable):
        super().__init__(parent)
        self.title("AI Brainstorming Session")

        self.parent_app = parent
        self.processor = processor
        self.update_callback = update_callback
        self.models = models
        self.chat_queue = queue.Queue()
        self.model_change_callback = model_change_callback
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

        self.input_text = tk.Text(input_area_frame, height=4, wrap=tk.WORD, font=self.parent_app.default_font)
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
        self.model_change_callback(None, self.active_brainstorm_model)

        self.smart_geometry(min_width=800, min_height=600)

    def close(self):
        """Safely close the window, cancelling any pending after() jobs."""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        if self.suggestion_after_id:
            self.after_cancel(self.suggestion_after_id)
            self.suggestion_after_id = None
        self.destroy()
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
                    template, new_wildcards = self._parse_template_generation_response(response)
                    self._handle_generated_template(template, new_wildcards, metadata)
                elif content_type == 'wildcard':
                    topic = metadata.get('topic', 'new_wildcard')
                    parsed_json_string = self._parse_json_from_ai_response(response, topic)
                    self._handle_generated_wildcard(parsed_json_string, metadata)
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

    def generate_wildcard_with_topic(self, topic: str, filename: Optional[str] = None, existing_window: Optional[ReviewAndSaveWindow] = None):
        """Starts the generation process for a wildcard with a given topic."""
        if not topic:
            return

        # If no filename is provided, derive it from the topic for the 'Generate Wildcard' button.
        # If a filename IS provided (from a missing wildcard link), use that directly.
        final_filename = filename if filename is not None else topic

        # Create or get the results window first with a loading state.
        metadata = {'filename': final_filename, 'topic': topic, 'window': existing_window}
        results_window = self._handle_generated_content("", "wildcard", metadata)
        metadata['window'] = results_window

        # Add workflow context to the prompt
        workflow_context = ""
        if config.workflow == 'nsfw':
            workflow_context = (
                "The user is currently in NSFW (Not Safe For Work) mode. "
                "Generated items may include explicit, adult-oriented, and pornographic elements if the subject naturally calls for it. "
                "Only include sexual or explicit details when they are relevant to the subject or enhance its realism—avoid forcing explicit terms into unrelated or inanimate objects unless it makes natural sense in an erotic context. "
                "If the request involves neutral topics like furniture, backdrops, landscapes, or clothing styles, describe them normally unless there is a clear erotic reason to make them explicit. "
                "Use realistic and coherent descriptions rather than absurd combinations, and prioritize plausible adult themes over randomness."
            )
        else:
            workflow_context = "The user is currently in SFW (Safe For Work) mode. The items should be general-purpose and not contain any explicit content."

        # Sanitize the topic to create a likely wildcard name for the 'no self-reference' rule.
        wildcard_name_from_topic = re.sub(r'\s+', '_', topic.strip()).lower()
        wildcard_name_from_topic = re.sub(r'[^a-z0-9_]', '', wildcard_name_from_topic)

        # Get a sample of other wildcards, making sure not to include the one we are generating.
        all_wildcard_names = self.processor.get_wildcard_names()
        other_wildcard_names = [wc for wc in all_wildcard_names if wc != wildcard_name_from_topic]
        sample_size = min(5, len(other_wildcard_names))
        wildcard_sample_str = ", ".join(random.sample(other_wildcard_names, sample_size)) if other_wildcard_names else "none"

        prompt = (
            f"You are an expert content creator specializing in generating diverse and thematic lists for Stable Diffusion wildcards. Your task is to generate a JSON object containing a list of 20-30 items that are **strictly and creatively** related to the topic: '{topic}'.\n\n"
            f"**CONTEXT:** {workflow_context}\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n"
            f"1.  **Stay Strictly on Theme:** Every single new choice MUST be a specific example of '{topic}'. Do not suggest items that are merely related accessories or concepts. For example, if the topic is 'sex positions', do not suggest 'garter belt'.\n"
            f"2.  **JSON Format:** You MUST return a single JSON object with a `description` and a `choices` array.\n"
            f"3.  **Complex Choices:** The `choices` array should contain a mix of simple strings and complex objects. For objects, you can include `weight`, `tags`, `requires`, and `includes` keys.\n"
            f"4.  **Requirements & Includes:** Use `requires` (e.g., `{{\"wildcard_name\": \"value\"}}`) for dependencies and `includes` (e.g., `[\"another_wildcard\"]`) to add more wildcards.\n"
            f"5.  **No Self-Reference:** The `requires` key MUST NOT refer to the wildcard being generated (`{wildcard_name_from_topic}`). This is a critical rule.\n"
            f"6.  **Use Normal Spaces:** For all `value` fields and simple string choices, use normal spaces, NOT underscores (e.g., 'elven archer', not 'elven_archer'). Underscores are only for wildcard names in `includes`.\n"
            f"7.  **Unique Values:** Ensure all `value` fields within your generated `choices` array are unique. Do not repeat items.\n"
            f"8.  **No Extra Text:** Do not add any commentary outside of the JSON object.\n\n"
            f"**Existing Wildcards sample for 'requires' and 'includes' clauses:** {wildcard_sample_str}\n\n"
            f"**EXAMPLE for topic 'fantasy_character_class':**\n"
            f"{{\n"
            f'  "description": "A list of fantasy character classes.",\n'
            f'  "choices": [\n'
            f'    "peasant",\n'
            f'    {{"value": "elven archer", "weight": 3, "tags": ["ranged", "elf"], "requires": {{"fantasy_race": "elf"}}, "includes": ["elven_bow", "leather_armor"]}},\n'
            f'    {{"value": "dwarven warrior", "weight": 3, "tags": ["melee", "dwarf"], "requires": {{"fantasy_race": "dwarf"}}, "includes": ["dwarven_axe", "plate_armor"]}}\n'
            f'  ]\n'
            f"}}\n\n"
            f"Now, generate the JSON for the topic: '{topic}'."
        )
        self._add_message("AI", f"Generating wildcard ideas for '{topic}'...", "thinking")
        self._run_generation_task(prompt, "wildcard", metadata=metadata)

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

        wildcard_names = self.processor.get_wildcard_names()
        # Suggest a smaller, random sample of wildcards to avoid overwhelming the AI
        sample_size = min(15, len(wildcard_names))
        wildcard_sample_str = ", ".join(random.sample(wildcard_names, sample_size)) if wildcard_names else "none"

        # Add workflow context to the prompt
        workflow_context = ""
        if config.workflow == 'nsfw':
            workflow_context = (
                "The user is currently in NSFW (Not Safe For Work) mode. "
                "The template should be designed for generating explicit, adult-oriented, and pornographic imagery. "
                "It should be descriptive and graphic where appropriate."
            )
        else:
            workflow_context = "The user is currently in SFW (Safe For Work) mode. The template should be suitable for general-purpose, non-explicit imagery."

        prompt = (
            f"You are an AI assistant that creates templates for a Stable Diffusion prompt generator. "
            f"The user wants a template for the concept: '{concept}'.\n\n"
            f"**CONTEXT:** {workflow_context}\n\n"
            f"Your task is to write a descriptive prompt template. You can use existing wildcards from the list below, but you are also **strongly encouraged to invent new, relevant wildcard names** to make the template more versatile.\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n"
            f"1.  All wildcard names, existing or new, MUST be in the exact format `__wildcard_name__`.\n"
            f"2.  The final template should be a single paragraph of comma-separated keywords and phrases.\n"
            f"3.  You MUST return your response in the following format, with nothing before or after:\n"
            f"TEMPLATE: [The full template text you generated]\n"
            f"NEW_WILDCARDS: [A comma-separated list of any new wildcard names you invented. If you invented none, write 'none'.]\n\n"
            f"**EXAMPLE RESPONSE:**\n"
            f"TEMPLATE: a portrait of a __character_class__, __hair_style__ hair, wearing __fantasy_armor__, holding a __weapon_type__, in a __fantasy_forest__, __lighting_style__\n"
            f"NEW_WILDCARDS: fantasy_armor, fantasy_forest\n\n"
            f"Here is a sample of EXISTING wildcards you can use: {wildcard_sample_str}\n\n"
            f"Now, generate the template for the concept: '{concept}'."
        )
        self._add_message("AI", f"Generating a template for '{concept}'...", "thinking")
        self._run_generation_task(prompt, "template", metadata=metadata)

    def _run_generation_task(self, prompt: str, content_type: str, metadata: Optional[Dict] = None):
        """Runs a generation task in a background thread."""
        model = self.model_var.get()
        self.send_button.config(state=tk.DISABLED)

        def task():
            try:
                # Use the new one-shot generation method
                response = self.processor.generate_for_brainstorming(model, prompt)
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

        prompt = (
            f"You are an AI assistant. Your task is to rewrite the following text based on the user's instruction.\n\n"
            f"INSTRUCTION: {instructions}\n\n"
            f"ORIGINAL TEXT:\n---\n{selected_text}\n---\n\n"
            f"Return only the rewritten text, with no extra commentary."
        )
        
        # Replace selected text with a loading message
        self.history_text.config(state=tk.NORMAL)
        self.history_text.delete(start_index, end_index)
        placeholder = f"[Rewriting to '{instructions}'...]"
        self.history_text.insert(start_index, placeholder, ("thinking",))
        new_end_index = self.history_text.index(f"{start_index} + {len(placeholder)}c")
        self.history_text.config(state=tk.DISABLED)
        
        metadata = {'start_index': start_index, 'end_index': new_end_index}
        self._run_generation_task(prompt, "rewrite", metadata=metadata)

    def _parse_json_from_ai_response(self, response: str, topic: str) -> str:
        """Extracts a JSON object from an AI's response, with fallback and cleanup."""
        json_str = None
        # First, try to find a markdown-fenced JSON block (most reliable)
        match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Fallback: find the content between the first '{' and last '}'
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end != -1 and start < end:
                json_str = response[start:end+1]

        parsed_data = None
        if json_str:
            try:
                parsed_data = json.loads(json_str)
            except (json.JSONDecodeError, Exception):
                pass # Fall through to text-based fallback

        if parsed_data and 'choices' in parsed_data:
            # Sanitize the choices list using the shared utility function
            parsed_data['choices'] = sanitize_wildcard_choices(parsed_data.get('choices', []))
            return json.dumps(parsed_data, indent=2)

        # Fallback: If JSON parsing fails, try to parse the response as a plain list.
        # This is more robust than just splitting by lines.
        
        # Regex to find lines that look like list items (markdown or numbered)
        # It captures the content after the list marker.
        list_item_pattern = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)", re.MULTILINE)
        
        choices = list_item_pattern.findall(response)
        
        # If we found list items, clean them up.
        if choices:
            # Further cleanup: remove trailing punctuation that might be part of the list format
            # and replace underscores with spaces.
            cleaned_choices = [re.sub(r'[.,]$', '', choice).strip().replace('_', ' ') for choice in choices]
            # Filter out any empty strings that might result from cleanup
            lines = [c for c in cleaned_choices if c]
        else:
            # If no list items were found, use a less-reliable line-splitting method as a last resort,
            # filtering out common conversational filler.
            ignore_phrases = ["here are", "here's a list", "sure, here", "i've generated", "```", "json"]
            lines = [line.strip().replace('_', ' ') for line in response.split('\n') if line.strip() and not any(phrase in line.lower() for phrase in ignore_phrases)]

        fallback_data = {"description": f"AI-generated list for the topic: {topic} (fallback mode)", "choices": lines}
        return json.dumps(fallback_data, indent=2)

    def _parse_template_generation_response(self, response: str) -> Tuple[str, List[str]]:
        """Parses the AI response for template and new wildcards."""
        template_content = ""
        new_wildcards = []
        
        # Use re.IGNORECASE to handle variations in casing like 'TEMPLATE:' vs 'Template:'
        template_match = re.search(r"TEMPLATE:\s*(.*)", response, re.DOTALL | re.IGNORECASE)
        if template_match:
            # Further split by NEW_WILDCARDS to ensure we only get the template part
            # Use re.split for case-insensitivity to match the search
            template_content = re.split(r"NEW_WILDCARDS:", template_match.group(1), flags=re.IGNORECASE)[0].strip()

        wildcards_match = re.search(r"NEW_WILDCARDS:\s*(.*)", response, re.DOTALL | re.IGNORECASE)
        if wildcards_match:
            wildcards_str = wildcards_match.group(1).strip()
            if wildcards_str.lower() != 'none':
                new_wildcards = [w.strip() for w in wildcards_str.split(',') if w.strip()]

        # If parsing fails (e.g., AI didn't follow format), fall back to treating the whole response as the template
        if not template_content:
            template_content = response
            
        return template_content, new_wildcards

    def _handle_generated_wildcard(self, parsed_json_string: str, metadata: Optional[Dict] = None):
        """Handles the display of a newly generated wildcard and its new 'includes'."""
        try:
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
        used_wildcards = set(re.findall(r'__([a-zA-Z0-9_.-]+)__', template))
        
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

    def _handle_generated_content(self, content: str, content_type: str, metadata: Optional[Dict] = None) -> ReviewAndSaveWindow:
        """
        Opens or updates the review window for newly generated content.
        If content is empty, it creates the window in a loading state.
        Returns the window instance.
        """
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
            window = ReviewAndSaveWindow(self, self.processor, content_type, content or "", self.update_callback, filename=filename, regenerate_callback=regenerate_callback, is_loading=not bool(content))
            return window

    def _on_model_var_change(self, *args):
        """Handles when the user selects a new model in the dropdown."""
        new_model = self.model_var.get()
        old_model = self.active_brainstorm_model
        if new_model and new_model != old_model:
            self.model_change_callback(old_model, new_model)
            self.active_brainstorm_model = new_model