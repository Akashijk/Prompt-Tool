"""An interactive window for brainstorming with an AI model."""

import tkinter as tk
from tkinter import ttk, simpledialog
import queue
import threading
import re
import random
from typing import Optional, List, Dict, Callable, Tuple

from core.prompt_processor import PromptProcessor
from core.config import config
from .review_window import ReviewAndSaveWindow
from .common import BrainstormingContextMenu, TextContextMenu


class BrainstormingWindow(tk.Toplevel):
    """An interactive window for brainstorming with an AI model."""
    def __init__(self, parent, processor: PromptProcessor, models: List[str], default_model: str, model_change_callback: Callable, update_callback: Callable):
        super().__init__(parent)
        self.title("AI Brainstorming Session")
        self.geometry("800x600")

        self.processor = processor
        self.update_callback = update_callback
        self.models = models
        self.chat_queue = queue.Queue()
        self.model_change_callback = model_change_callback
        self.active_brainstorm_model: Optional[str] = None

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
        self.history_text = tk.Text(history_scroll_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Helvetica", 11), yscrollcommand=history_scrollbar.set)
        history_scrollbar.config(command=self.history_text.yview)
        history_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.history_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        BrainstormingContextMenu(self.history_text, self._rewrite_selection)

        self.history_text.tag_configure("user", foreground="blue", font=("Helvetica", 11, "bold"))
        self.history_text.tag_configure("ai", foreground="#006400")
        self.history_text.tag_configure("error", foreground="red", font=("Helvetica", 11, "bold"))
        self.history_text.tag_configure("thinking", foreground="gray", font=("Helvetica", 11, "italic"))
        self.history_text.tag_configure("new_wildcard_link", foreground="#FFB000", underline=True)
        self.history_text.tag_bind("new_wildcard_link", "<Enter>", lambda e: self.history_text.config(cursor="hand2"))
        self.history_text.tag_bind("new_wildcard_link", "<Leave>", lambda e: self.history_text.config(cursor=""))

        # --- Input Area ---
        input_area_frame = ttk.LabelFrame(main_pane, text="Your Message (Enter to send, Shift+Enter for new line)", padding=5)
        main_pane.add(input_area_frame, weight=1)

        self.input_text = tk.Text(input_area_frame, height=4, wrap=tk.WORD, font=("Helvetica", 11))
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.input_text.bind("<Return>", self._on_send_message_event)
        TextContextMenu(self.input_text)
        
        self.send_button = ttk.Button(input_area_frame, text="Send", command=self._send_message)
        self.send_button.pack(side=tk.LEFT, padx=(10, 0), fill=tk.Y)
        
        self._add_message("AI", "Hello! How can I help you brainstorm today? You can ask me to improve a list of wildcards, create a new template, or anything else you can think of.", "ai")

        # Register initial model usage
        self.active_brainstorm_model = default_model
        self.model_change_callback(None, self.active_brainstorm_model)

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

        self._add_message("User", user_prompt, "user")
        self.input_text.delete("1.0", tk.END)
        self.send_button.config(state=tk.DISABLED)
        self._add_message("AI", "Thinking...", "thinking")

        thread = threading.Thread(target=self._get_ai_response, args=(model, user_prompt), daemon=True)
        thread.start()
        self.after(100, self._check_chat_queue)

    def _get_ai_response(self, model, prompt):
        try:
            response = self.processor.chat_with_model(model, prompt)
            self.chat_queue.put({'response': response, 'tag': 'ai'})
        except Exception as e:
            self.chat_queue.put({'response': f"An error occurred: {e}", 'tag': 'error'})

    def _check_chat_queue(self):
        try:
            result = self.chat_queue.get_nowait()
            self.history_text.config(state=tk.NORMAL)
            self.history_text.delete("end-2l", "end-1c")
            self.history_text.config(state=tk.DISABLED)

            if result.get('tag') == 'ai_generated':
                content_type = result.get('content_type')
                response = result.get('response', '')
                metadata = result.get('metadata')
                if content_type == 'template':
                    template, new_wildcards = self._parse_template_generation_response(response)
                    self._handle_generated_template(template, new_wildcards, metadata)
                elif content_type == 'wildcard':
                    self._add_message("AI", f"Generated a new wildcard. See the new window to review and save.", "ai")
                    self._handle_generated_content(response, 'wildcard', metadata)
                elif content_type == 'rewrite':
                    if metadata:
                        self._handle_rewritten_text(response, metadata['start_index'], metadata['end_index'])
            else:
                # Handle regular chat or errors
                self._add_message("AI", result['response'], result['tag'])
            
            self.send_button.config(state=tk.NORMAL)
        except queue.Empty:
            self.after(100, self._check_chat_queue)

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
        message = (
            f"Loaded {content_type} '{filename}' for brainstorming.\n\n"
            f"You can now ask me to refine it. For example: 'make this list more diverse', 'rewrite this template to be more cinematic', or 'add more technical terms'.\n\n"
            f"CONTENT:\n"
            f"----------------\n"
            f"{content}"
        )
        self._add_message("System", message, "thinking")

    def _generate_wildcard_file(self):
        """Guides the user to generate a new wildcard file."""
        topic = simpledialog.askstring("Generate Wildcard", "What is the topic for the new wildcard file?\n(e.g., 'sci-fi helmet designs', 'fantasy potion names')", parent=self)
        self.generate_wildcard_with_topic(topic)

    def generate_wildcard_with_topic(self, topic: str, existing_window: Optional[ReviewAndSaveWindow] = None):
        """Starts the generation process for a wildcard with a given topic."""
        if not topic: return
        
        # Add workflow context to the prompt
        workflow_context = ""
        if config.workflow == 'nsfw':
            workflow_context = (
                "The user is currently in NSFW (Not Safe For Work) mode. "
                "The generated items should be explicit, adult-oriented, and suitable for generating pornographic imagery if it appears to require it. "
                "Do not censor the content, but if you are asked to generate content for furniture or backdrops you don't need to necessarily make it explicit."
                "Use your best judgement, but default to NSFW themes if you aren't sure."
            )
        else:
            workflow_context = "The user is currently in SFW (Safe For Work) mode. The items should be general-purpose and not contain any explicit content."

        prompt = (
            f"You are an expert content creator specializing in generating diverse and thematic lists for Stable Diffusion wildcards.\n\n"
            f"The user needs a list for a wildcard file named '{topic}'. Your task is to generate a list of 20-30 items that are **strictly and creatively** related to this topic.\n\n"
            f"**CONTEXT:** {workflow_context}\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n"
            f"1.  **Stay on Theme:** Every single item must be a specific example of '{topic}'. Do not stray from the topic.\n"
            f"2.  **Be Creative and Diverse:** The items should be varied and interesting, not just simple variations of the same idea.\n"
            f"3.  **Use English:** The entire list must be in English.\n"
            f"4.  **Formatting:**\n"
            f"    - Each item must be on a new line.\n"
            f"    - Use normal spaces for multi-word items (e.g., 'ancient stone temple', NOT 'ancient_stone_temple').\n"
            f"    - Do NOT add numbers, bullets, or any other formatting.\n"
            f"    - Do NOT repeat the topic '{topic}' as a prefix for each item.\n\n"
            f"**EXAMPLE for topic 'fantasy_potions':**\n"
            f"Elixir of Sun's Vigor\n"
            f"Draught of Shadowy Concealment\n"
            f"Philter of Gilded Luck\n\n"
            f"Now, generate the list for the topic: '{topic}'."
        )
        self._add_message("AI", f"Generating wildcard ideas for '{topic}'...", "thinking")
        # The 'topic' is the base name for the wildcard file.
        self._run_generation_task(prompt, "wildcard", metadata={'filename': topic, 'topic': topic, 'window': existing_window})

    def _generate_template_file(self):
        """Guides the user to generate a new template file."""
        concept = simpledialog.askstring("Generate Template", "What is the high-level concept for the new template?\n(e.g., 'a character portrait in a dark forest', 'a futuristic city street scene')", parent=self)
        self.generate_template_with_concept(concept)

    def generate_template_with_concept(self, concept: str, existing_window: Optional[ReviewAndSaveWindow] = None):
        """Starts the generation process for a template with a given concept."""
        if not concept: return

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
        self._run_generation_task(prompt, "template", metadata={'concept': concept, 'window': existing_window})

    def _run_generation_task(self, prompt: str, content_type: str, metadata: Optional[Dict] = None):
        """Runs a generation task in a background thread."""
        model = self.model_var.get()
        self.send_button.config(state=tk.DISABLED)

        def task():
            try:
                response = self.processor.chat_with_model(model, prompt)
                self.chat_queue.put({'response': response, 'tag': 'ai_generated', 'content_type': content_type, 'metadata': metadata})
            except Exception as e:
                self.chat_queue.put({'response': f"An error occurred: {e}", 'tag': 'error'})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after(100, self._check_chat_queue)

    def _rewrite_selection(self):
        """Handles the AI-powered rewriting of selected text in the history."""
        try:
            start_index = self.history_text.index("sel.first")
            end_index = self.history_text.index("sel.last")
            selected_text = self.history_text.get(start_index, end_index)
        except tk.TclError:
            return # No selection

        instructions = simpledialog.askstring(
            "Rewrite with AI",
            "How should I rewrite the selected text?\n(e.g., 'make it more poetic', 'add more technical terms')",
            parent=self
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

    def _parse_template_generation_response(self, response: str) -> Tuple[str, List[str]]:
        """Parses the AI response for template and new wildcards."""
        template_content = ""
        new_wildcards = []
        
        # Use re.IGNORECASE to handle variations in casing like 'TEMPLATE:' vs 'Template:'
        template_match = re.search(r"TEMPLATE:\s*(.*)", response, re.DOTALL | re.IGNORECASE)
        if template_match:
            # Further split by NEW_WILDCARDS to ensure we only get the template part
            template_content = template_match.group(1).split("NEW_WILDCARDS:")[0].strip()

        wildcards_match = re.search(r"NEW_WILDCARDS:\s*(.*)", response, re.DOTALL | re.IGNORECASE)
        if wildcards_match:
            wildcards_str = wildcards_match.group(1).strip()
            if wildcards_str.lower() != 'none':
                new_wildcards = [w.strip() for w in wildcards_str.split(',') if w.strip()]

        # If parsing fails (e.g., AI didn't follow format), fall back to treating the whole response as the template
        if not template_content:
            template_content = response
            
        return template_content, new_wildcards

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

    def _handle_generated_content(self, content: str, content_type: str, metadata: Optional[Dict] = None):
        """Opens the review window for newly generated content."""
        existing_window = metadata.get('window') if metadata else None

        if existing_window and existing_window.winfo_exists():
            existing_window.update_content(content)
            existing_window.lift()
        else:
            filename = metadata.get('filename') if metadata else None
            regenerate_callback = None
            if metadata:
                if content_type == 'wildcard' and 'topic' in metadata:
                    regenerate_callback = lambda window: self.generate_wildcard_with_topic(metadata['topic'], window)
                elif content_type == 'template' and 'concept' in metadata:
                    regenerate_callback = lambda window: self.generate_template_with_concept(metadata['concept'], window)

            ReviewAndSaveWindow(self, self.processor, content_type, content, self.update_callback, filename=filename, regenerate_callback=regenerate_callback)

    def _on_model_var_change(self, *args):
        """Handles when the user selects a new model in the dropdown."""
        new_model = self.model_var.get()
        old_model = self.active_brainstorm_model
        if new_model and new_model != old_model:
            self.model_change_callback(old_model, new_model)
            self.active_brainstorm_model = new_model