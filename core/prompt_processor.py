"""Main prompt processing and coordination logic."""

import json
import os
import random
import re
import threading
from typing import List, Dict, Any, Optional, Callable, Tuple, Set
from .template_engine import TemplateEngine, PromptSegment
from .csv_manager import HistoryManager
from .config import config, DEFAULT_SFW_ENHANCEMENT_INSTRUCTION, DEFAULT_SFW_VARIATION_INSTRUCTIONS, \
                    DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION, DEFAULT_NSFW_VARIATION_INSTRUCTIONS
from .ollama_client import OllamaClient
from datetime import datetime

class PromptProcessor:
    """Coordinates prompt generation and enhancement workflow."""
    
    def __init__(self):
        self.template_engine = TemplateEngine()
        # Lazily import OllamaClient to avoid issues if it's not needed (e.g., in GUI)
        self.ollama_client = OllamaClient(base_url=config.OLLAMA_BASE_URL) 
        self.history_manager = HistoryManager()
        self.rng = random.Random()
        
        # Callback functions for UI updates (optional)
        self.status_callback: Optional[Callable] = None
        self.result_callback: Optional[Callable] = None
    
    def set_callbacks(self, status_callback: Optional[Callable] = None, result_callback: Optional[Callable] = None) -> None:
        """Set callback functions for UI updates."""
        self.status_callback = status_callback
        self.result_callback = result_callback
    
    def _update_status(self, event_type: str, **kwargs) -> None:
        """Update status if callback is set."""
        if self.status_callback:
            self.status_callback(event_type, **kwargs)
    
    def initialize(self) -> None:
        """Initialize all components."""
        self._update_status("Loading wildcards...")
        self.template_engine.load_wildcards(self._get_wildcard_load_order())
        
        self._update_status("Initializing directories...")
        self._initialize_directories()

        self._update_status("Loading templates...")
        self.template_engine.list_templates(config.get_template_dir())
        
        self._update_status("Ready")
    
    def _initialize_directories(self):
        """Ensures all necessary directories for templates and system prompts exist."""
        os.makedirs(os.path.join(config.TEMPLATE_BASE_DIR, 'sfw'), exist_ok=True)
        os.makedirs(os.path.join(config.TEMPLATE_BASE_DIR, 'nsfw'), exist_ok=True)

        os.makedirs(config.WILDCARD_DIR, exist_ok=True)
        os.makedirs(config.WILDCARD_NSFW_DIR, exist_ok=True)

        os.makedirs(os.path.join(config.HISTORY_DIR, 'sfw'), exist_ok=True)
        os.makedirs(os.path.join(config.HISTORY_DIR, 'nsfw'), exist_ok=True)

        os.makedirs(os.path.join(config.SYSTEM_PROMPT_BASE_DIR, 'sfw'), exist_ok=True)
        os.makedirs(os.path.join(config.SYSTEM_PROMPT_BASE_DIR, 'nsfw'), exist_ok=True)

    def _get_wildcard_load_order(self) -> List[str]:
        """Returns dirs for loading all wildcards. Specific (NSFW) overrides shared (root)."""
        dirs = [config.WILDCARD_DIR]
        if config.workflow == 'nsfw':
            dirs.append(config.WILDCARD_NSFW_DIR)
        return dirs

    def _get_wildcard_search_order(self) -> List[str]:
        """Returns dirs for finding a single file. Specific (NSFW) is checked first."""
        # This order is important for finding the most specific version of a file first.
        if config.workflow == 'nsfw':
            return [config.WILDCARD_NSFW_DIR, config.WILDCARD_DIR]
        else:
            return [config.WILDCARD_DIR]

    def reload_wildcards(self) -> None:
        """Reloads wildcards based on the current workflow."""
        self._update_status("Reloading wildcards...")
        self.template_engine.load_wildcards(self._get_wildcard_load_order())
        self._update_status("Ready")

    def get_available_models(self) -> List[str]:
        """Get list of available Ollama models."""
        return self.ollama_client.list_models()
    
    def get_model_recommendations(self, models: List[str]) -> List[tuple]:
        """Get recommended models with reasons."""
        return self.ollama_client.get_model_recommendations(models)
    
    def delete_history_entry(self, row_to_delete: Dict[str, str]) -> bool:
        """Pass-through to delete a history entry."""
        return self.history_manager.delete_history_entry(row_to_delete)

    def update_history_entry(self, original_row: Dict[str, str], updated_row: Dict[str, str]) -> bool:
        """Pass-through to update a history entry."""
        return self.history_manager.update_history_entry(original_row, updated_row)
    
    def get_full_history(self) -> List[Dict[str, str]]:
        """Pass-through to get the full history data."""
        return self.history_manager.load_full_history()
    
    def get_available_templates(self) -> List[str]:
        """Get a fresh, sorted list of available templates."""
        return self.template_engine.list_templates(config.get_template_dir())

    def get_wildcard_names(self) -> List[str]:
        """Get the names (keys) of all loaded wildcards."""
        return list(self.template_engine.wildcards.keys())

    def get_wildcard_files(self) -> List[str]:
        """Get list of available wildcard files."""
        return self.template_engine.list_wildcard_files(self._get_wildcard_load_order())

    def get_all_wildcard_files_mode_agnostic(self) -> List[str]:
        """Gets a list of all wildcard files from all possible directories, regardless of mode."""
        all_dirs = [config.WILDCARD_DIR, config.WILDCARD_NSFW_DIR]
        return self.template_engine.list_wildcard_files(all_dirs)

    def get_all_used_wildcards(self) -> set[str]:
        """Scans all templates and wildcards across all workflows to find which wildcards are actively used."""
        used_wildcards = set()
        
        # 1. Scan all templates from ALL workflows to be mode-agnostic
        all_template_dirs = [
            os.path.join(config.TEMPLATE_BASE_DIR, 'sfw'),
            os.path.join(config.TEMPLATE_BASE_DIR, 'nsfw')
        ]

        for template_dir in all_template_dirs:
            if not os.path.exists(template_dir):
                continue
            
            for template_file in os.listdir(template_dir):
                if template_file.endswith('.txt'):
                    try:
                        # Use the template engine directly to specify the directory,
                        # bypassing the mode-specific self.load_template_content().
                        content = self.template_engine.load_template(template_file, template_dir)
                        found = re.findall(r'__([a-zA-Z0-9_.-]+)__', content)
                        used_wildcards.update(found)
                    except Exception as e:
                        print(f"Warning: Could not scan template {os.path.join(template_dir, template_file)} for used wildcards: {e}")

        # 2. Scan all wildcards from all directories for 'includes' clauses
        all_wildcard_dirs = [config.WILDCARD_DIR, config.WILDCARD_NSFW_DIR]
        all_wildcards_data = self.template_engine.get_all_wildcards_data_from_dirs(all_wildcard_dirs)
        
        for wildcard_data in all_wildcards_data.values():
            if 'includes' in wildcard_data and isinstance(wildcard_data.get('includes'), list):
                used_wildcards.update(wildcard_data['includes'])
            if 'choices' in wildcard_data and isinstance(wildcard_data.get('choices'), list):
                for choice in wildcard_data['choices']:
                    if isinstance(choice, dict) and 'includes' in choice and isinstance(choice.get('includes'), list):
                        used_wildcards.update(choice['includes'])
                    if isinstance(choice, dict) and 'requires' in choice and isinstance(choice.get('requires'), dict):
                        used_wildcards.update(choice['requires'].keys())
        return used_wildcards

    def load_wildcard_content(self, wildcard_file: str) -> str:
        """Load content of a single wildcard file."""
        return self.template_engine.load_wildcard_content(wildcard_file, self._get_wildcard_search_order())
    
    def save_wildcard_content(self, wildcard_file: str, content: str, is_nsfw_only: bool = False) -> None:
        """
        Saves content to a wildcard file.
        If the file exists, it's saved in its current location (NSFW takes precedence).
        If it's a new file, it's saved to the NSFW or shared directory based on the flag.
        """
        basename, old_ext = os.path.splitext(wildcard_file)
        new_filename = f"{basename}.json"

        # Determine save directory.
        save_dir = config.WILDCARD_DIR  # Default to shared/root.
        search_order = self._get_wildcard_search_order()
        found_dir = None
        for directory in search_order:
            # Check for either .json or .txt to find where the family of files lives.
            if os.path.exists(os.path.join(directory, new_filename)) or os.path.exists(os.path.join(directory, wildcard_file)):
                found_dir = directory
                break
        
        if found_dir:
            save_dir = found_dir
        elif is_nsfw_only: # It's a new file and flagged as NSFW-only.
            save_dir = config.WILDCARD_NSFW_DIR
            
        # Save the new .json file.
        self.template_engine.save_wildcard_content(new_filename, content, save_dir)

        # If we migrated from .txt, delete the old file.
        if old_ext == '.txt':
            old_file_path = None
            for directory in search_order:
                path_to_check = os.path.join(directory, wildcard_file)
                if os.path.exists(path_to_check):
                    try:
                        os.remove(path_to_check)
                        print(f"INFO: Migrated and removed old wildcard file: {path_to_check}")
                    except OSError as e:
                        print(f"WARNING: Could not remove old .txt wildcard file during migration: {e}")
                    break
    
    def load_template_content(self, template_file: str) -> str:
        """Load template content."""
        return self.template_engine.load_template(template_file, config.get_template_dir())

    def save_template_content(self, template_file: str, content: str) -> None:
        """Saves modified template content back to its file."""
        self.template_engine.save_template(template_file, content, config.get_template_dir())

    def archive_template(self, template_file: str) -> None:
        """Archives a template file."""
        self.template_engine.archive_template(template_file, config.get_template_dir())

    def archive_wildcard(self, wildcard_file: str) -> None:
        """Archives a wildcard file."""
        self.template_engine.archive_wildcard(wildcard_file, self._get_wildcard_search_order())
    def generate_single_structured_prompt(self, template_content: str, existing_segments: Optional[List[PromptSegment]] = None, force_reroll: Optional[List[str]] = None, seed: Optional[int] = None) -> List[PromptSegment]:
        """Generates a single structured prompt for GUI use, optionally reusing existing wildcard choices."""
        return self.template_engine.generate_structured_prompt(
            template_content, 
            existing_segments=existing_segments, 
            force_reroll=force_reroll,
            seed=seed
        )

    def get_wildcard_options(self, wildcard_name: str) -> List[str]:
        """Pass-through to get wildcard options."""
        return self.template_engine.get_wildcard_options(wildcard_name)
    
    def find_wildcard_choice_object(self, wildcard_name: str, value: str) -> Optional[Any]:
        """Pass-through to find a choice object by its value."""
        return self.template_engine.find_choice_object_by_value(wildcard_name, value)

    def get_system_prompt_files(self) -> List[str]:
        """Get a list of available system prompt files."""
        return sorted([f for f in os.listdir(config.get_system_prompt_dir()) if f.endswith('.txt')])

    def load_system_prompt_content(self, filename: str) -> str:
        """Load the content of a system prompt file."""
        filepath = os.path.join(config.get_system_prompt_dir(), filename)
        
        # Lazy initialization: If the file doesn't exist, create it with default content.
        if not os.path.exists(filepath):
            default_content = self.get_default_system_prompt(filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(default_content)
            return default_content
            
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise Exception(f"Error loading system prompt {filename}: {e}")

    def save_system_prompt_content(self, filename: str, content: str):
        """Save content to a system prompt file."""
        filepath = os.path.join(config.get_system_prompt_dir(), filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            raise Exception(f"Error saving system prompt {filename}: {e}")

    def get_default_system_prompt(self, filename: str) -> str:
        """Gets the default content for a given system prompt."""

        key = filename.replace('.txt', '')
        if config.workflow == 'sfw':
            if key == 'enhancement':
                return DEFAULT_SFW_ENHANCEMENT_INSTRUCTION
            return DEFAULT_SFW_VARIATION_INSTRUCTIONS.get(key, '')
        else: # nsfw
            if key == 'enhancement':
                return DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION
            return DEFAULT_NSFW_VARIATION_INSTRUCTIONS.get(key, '')

    def chat_with_model(self, model: str, messages: List[Dict[str, str]]) -> str:
        """Handles a chat interaction with the specified Ollama model."""
        return self.ollama_client.chat(model, messages)

    def generate_for_brainstorming(self, model: str, prompt: str) -> str:
        """Handles a one-shot generation task for brainstorming wildcards/templates."""
        # This uses the /api/generate endpoint for single, non-conversational tasks.
        try:
            # Use a longer timeout for these complex, creative tasks.
            return self.ollama_client._generate(model, prompt, config.BRAINSTORM_TIMEOUT).strip()
        except Exception:
            # Re-raise to be caught by the GUI
            raise

    def generate_wildcard_for_brainstorming(self, model: str, prompt: str, topic: str) -> str:
        """
        Handles one-shot wildcard generation and robust parsing for the brainstorming window.
        """
        raw_response = self.generate_for_brainstorming(model, prompt)
        return self.ollama_client.parse_json_object_from_response(raw_response, topic)

    def generate_template_for_brainstorming(self, model: str, prompt: str) -> Tuple[str, List[str]]:
        """
        Handles one-shot template generation and robust parsing for the brainstorming window.
        """
        raw_response = self.generate_for_brainstorming(model, prompt)
        return self.ollama_client.parse_template_from_response(raw_response)


    def generate_raw_prompts(self, 
                           template_content: str, 
                           count: int) -> List[str]:
        """Generate raw prompts from template."""
        prompts = []
        for _ in range(count):
            prompt = self.template_engine.generate_prompt(template_content)
            prompts.append(prompt)
        return prompts
    
    def process_enhancement_batch(self, 
                                prompts: List[str], 
                                model: str,
                                selected_variations: Optional[List[str]] = None,
                                cancellation_event: Optional[threading.Event] = None) -> List[Dict[str, Any]]:
        """Process a batch of prompts for enhancement."""
        results = []
        total_prompts = len(prompts)
        
        for i, prompt in enumerate(prompts):
            if cancellation_event and cancellation_event.is_set():
                self._update_status("batch_cancelled")
                break
            
            # Enhance the prompt
            enhancement_instruction = self.load_system_prompt_content('enhancement.txt')
            self._update_status('enhancement_start', prompt_num=i+1, total_prompts=total_prompts)
            enhanced, enhanced_sd_model = self.ollama_client.enhance_prompt(enhancement_instruction + prompt, model)
            
            result = {
                'original': prompt,
                'enhanced': enhanced,
                'enhanced_sd_model': enhanced_sd_model,
                'variations': {},
                'status': 'enhanced'
            }
            
            # Send back the main enhancement result immediately
            if self.result_callback:
                self.result_callback('enhanced', {'prompt': enhanced, 'sd_model': enhanced_sd_model})
            
            # Create variations if requested
            if selected_variations:
                for var_type in selected_variations:
                    if cancellation_event and cancellation_event.is_set():
                        break # break inner loop

                    variation_instruction = self.load_system_prompt_content(f'{var_type}.txt')
                    self._update_status('variation_start', var_type=var_type, prompt_num=i+1, total_prompts=total_prompts)
                    variation_result = self.ollama_client.create_single_variation(variation_instruction, enhanced, enhanced_sd_model, model, var_type)
                    # Send back variation result immediately
                    if self.result_callback:
                        self.result_callback(var_type, variation_result)
                    result['variations'][var_type] = variation_result
            
            if cancellation_event and cancellation_event.is_set():
                break # break outer loop

            results.append(result)
        
        if not (cancellation_event and cancellation_event.is_set()):
            self._update_status("batch_complete")
        
        return results

    def regenerate_enhancement(self, original_prompt: str, model: str) -> Tuple[str, str]:
        """Regenerates just the main enhancement for a given prompt."""
        instruction = self.load_system_prompt_content('enhancement.txt')
        full_prompt = instruction + original_prompt
        return self.ollama_client.enhance_prompt(full_prompt, model)

    def regenerate_variation(self, base_prompt: str, base_sd_model: str, model: str, variation_type: str) -> Dict[str, str]:
        """Regenerates a single variation."""
        instruction = self.load_system_prompt_content(f'{variation_type}.txt')
        return self.ollama_client.create_single_variation(instruction, base_prompt, base_sd_model, model, variation_type)

    def cleanup_prompt_string(self, prompt: str) -> str:
        """Pass-through to the template engine's cleanup method."""
        return self.template_engine.cleanup_prompt_string(prompt)

    def suggest_template_additions(self, prompt: str, model: str) -> str:
        """Uses AI to suggest additions to an existing prompt template."""
        # Get a sample of existing wildcards to give the AI context.
        wildcard_names = self.get_wildcard_names()
        sample_size = min(15, len(wildcard_names))
        wildcard_sample_str = ", ".join(random.sample(wildcard_names, sample_size)) if wildcard_names else "none"

        instruction = (
            f"You are a prompt engineering expert for Stable Diffusion. Your task is to analyze the following prompt template and suggest 3-5 creative and context-aware additions. These can be descriptive phrases or new `__wildcard__` tags.\n\n"
            f"**EXISTING TEMPLATE:**\n---\n{prompt}\n---\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n"
            f"1.  **Analyze Intent:** Deeply analyze the user's template to understand its core subject, style, and intent.\n"
            f"2.  **Be Creative & Complementary:** Suggest genuinely new and complementary details. Think about lighting, atmosphere, composition, artistic style, camera angles, or specific subject details. Don't just add generic quality tags.\n"
            f"3.  **Use Existing Wildcards:** When relevant, use wildcards from the 'Existing Wildcards' list below. This is preferred over inventing a new one if a good match exists.\n"
            f"4.  **Invent New Wildcards:** If no existing wildcard fits your creative suggestion, invent a new, logically named `__wildcard__`.\n"
            f"5.  **Format:** Return ONLY a comma-separated list of your suggested additions. Do not repeat any part of the original template. Do not include any extra commentary, explanations, or labels like 'SUGGESTIONS:'.\n\n"
            f"**EXISTING WILDCARDS (SAMPLE):** {wildcard_sample_str}\n\n"
            f"**EXAMPLE:**\n"
            f"If the existing template is 'a portrait of a __character_class__, wearing __fantasy_armor__', and 'lighting_style' and 'fantasy_forest' are existing wildcards, a good response would be: '__lighting_style__, in a __fantasy_forest__, intricate details, masterpiece, from behind'\n\n"
            f"Now, provide the suggested additions for the user's template."
        )
        
        # Use the one-shot generation method for this simple task.
        return self.generate_for_brainstorming(model, instruction)

    def suggest_wildcard_choices(self, wildcard_data: Dict[str, Any], model: str, current_wildcard_filename: Optional[str] = None) -> List[Any]:
        """Uses AI to suggest new choices for an existing wildcard file."""
        description = wildcard_data.get('description', 'No description.')
        # Get a sample of existing choices to give the AI context
        existing_choices = wildcard_data.get('choices', [])
        sample_size = min(10, len(existing_choices))
        sample_choices = self.rng.sample(existing_choices, sample_size) if existing_choices else []
        
        current_wildcard_name = None
        if current_wildcard_filename:
            current_wildcard_name, _ = os.path.splitext(current_wildcard_filename)

        topic = current_wildcard_name.replace('_', ' ') if current_wildcard_name else "the given theme"

        # Get a sample of other wildcards for 'requires' and 'includes'
        other_wildcards = self.get_wildcard_names()
        # Filter out the current wildcard from the list of possibilities for 'requires'
        if current_wildcard_name:
            other_wildcards = [wc for wc in other_wildcards if wc != current_wildcard_name]

        other_sample_size = min(5, len(other_wildcards))
        other_wildcard_sample = ", ".join(self.rng.sample(other_wildcards, other_sample_size)) if other_wildcards else "none"

        # Build instructions dynamically
        instructions = [
            f"**Stay Strictly on Theme:** Every single new choice MUST be a specific example of '{topic}'. Do not suggest items that are merely related accessories or concepts. For example, if the topic is 'sex positions', do not suggest 'garter belt'.",
            "**JSON Format:** You MUST return a JSON array of the new choices. Do NOT return a full object with 'description', just the array of choices.",
            "**Complex Choices:** The new choices should be a mix of simple strings and complex objects with `weight`, `tags`, `requires`, and `includes` keys where appropriate.",
            "**Contextual Suggestions:** Use the 'Existing Wildcards' list below to create relevant `requires` and `includes` clauses. The `requires` key must be an object (e.g., `{{\"key\": \"value\"}}`), and `includes` must be an array of strings.",
            "**Use Normal Spaces:** For all `value` fields and simple string choices, use normal spaces, NOT underscores (e.g., 'elven archer', not 'elven_archer'). Underscores are only for wildcard names in `includes`.",
        ]
        if current_wildcard_name:
            instructions.append(f"**No Self-Reference:** The `requires` key MUST NOT refer to the wildcard being edited (`{current_wildcard_name}`). This is a critical rule.")
        
        instructions.extend([
            "**Avoid Duplicates:** The list above is only a small sample of existing choices. Do not suggest items that are already in the sample. Prioritize suggesting choices that are genuinely new and different from the existing theme.",
            "**No Extra Text:** Return ONLY the JSON array of new choices."
        ])

        # Format instructions with numbers
        formatted_instructions = "\n".join([f"{i+1}.  {inst}" for i, inst in enumerate(instructions)])

        prompt = (
            f"You are an expert content creator for Stable Diffusion wildcards. Your task is to analyze an existing wildcard file on the topic of '{topic}' and suggest 5-10 new, creative, and relevant choices that expand upon it.\n\n"
            f"**EXISTING WILDCARD DESCRIPTION:** {description}\n\n"
            f"**SAMPLE OF EXISTING CHOICES:**\n{json.dumps(sample_choices, indent=2)}\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n{formatted_instructions}\n\n"
            f"**Existing Wildcards sample for context:** {other_wildcard_sample}\n\n"
            f"**EXAMPLE RESPONSE for a 'fantasy_race' wildcard:**\n"
            f'[\n'
            f'  "gnome",\n'
            f'  {{"value": "tiefling", "weight": 2, "tags": ["fiendish"], "requires": {{"body_type": "curvy"}} }},\n'
            f'  {{"value": "aasimar", "weight": 2, "tags": ["celestial"], "includes": ["halo"]}}\n'
            f']\n\n'
            f"Now, generate the JSON array of new choices."
        )
            
        response = self.generate_for_brainstorming(model, prompt)
        
        return self.ollama_client.parse_json_array_from_response(response)

    def save_results(self, results: List[Dict[str, Any]]) -> None:
        """Save results to CSV."""
        self.history_manager.save_batch_results(results)
    
    def save_skipped_prompt(self, prompt: str) -> None:
        """Save a skipped prompt to prevent regeneration."""
        self.history_manager.save_result(prompt, "", "", status="skipped")
    
    def cleanup_model(self, model: str) -> None:
        """Unload model to free resources."""
        self.ollama_client.unload_model(model)