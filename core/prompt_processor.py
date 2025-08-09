"""Main prompt processing and coordination logic."""

import json
import os
import random
import threading
from typing import List, Dict, Any, Optional, Callable, Tuple
from .template_engine import TemplateEngine, PromptSegment
from .csv_manager import CSVManager
from .config import config, DEFAULT_SFW_ENHANCEMENT_INSTRUCTION, DEFAULT_SFW_VARIATION_INSTRUCTIONS, \
                    DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION, DEFAULT_NSFW_VARIATION_INSTRUCTIONS
from .ollama_client import OllamaClient

class PromptProcessor:
    """Coordinates prompt generation and enhancement workflow."""
    
    def __init__(self):
        self.template_engine = TemplateEngine()
        # Lazily import OllamaClient to avoid issues if it's not needed (e.g., in GUI)
        self.ollama_client = OllamaClient(base_url=config.OLLAMA_BASE_URL) 
        self.csv_manager = CSVManager()
        
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
        # Create template directories
        os.makedirs(os.path.join(config.TEMPLATE_BASE_DIR, 'sfw'), exist_ok=True)
        os.makedirs(os.path.join(config.TEMPLATE_BASE_DIR, 'nsfw'), exist_ok=True)

        # Create wildcard directories
        os.makedirs(config.WILDCARD_DIR, exist_ok=True)
        os.makedirs(config.WILDCARD_NSFW_DIR, exist_ok=True)

        # Create history directories
        os.makedirs(os.path.join(config.HISTORY_DIR, 'sfw'), exist_ok=True)
        os.makedirs(os.path.join(config.HISTORY_DIR, 'nsfw'), exist_ok=True)

        # Create system prompt directories and default files
        workflows: List[Tuple[str, str, Dict[str, str]]] = [
            ('sfw', DEFAULT_SFW_ENHANCEMENT_INSTRUCTION, DEFAULT_SFW_VARIATION_INSTRUCTIONS),
            ('nsfw', DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION, DEFAULT_NSFW_VARIATION_INSTRUCTIONS)
        ]

        for wf_name, enhancement_prompt, variation_prompts in workflows:
            prompt_dir = os.path.join(config.SYSTEM_PROMPT_BASE_DIR, wf_name)
            os.makedirs(prompt_dir, exist_ok=True)

            # Enhancement prompt
            enhancement_path = os.path.join(prompt_dir, 'enhancement.txt')
            if not os.path.exists(enhancement_path):
                with open(enhancement_path, 'w', encoding='utf-8') as f:
                    f.write(enhancement_prompt)

            # Variation prompts
            for key, content in variation_prompts.items():
                var_path = os.path.join(prompt_dir, f'{key}.txt')
                if not os.path.exists(var_path):
                    with open(var_path, 'w', encoding='utf-8') as f:
                        f.write(content)

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
        return self.csv_manager.delete_history_entry(row_to_delete)
    
    def get_full_history(self) -> List[Dict[str, str]]:
        """Pass-through to get the full history data."""
        return self.csv_manager.load_full_history()
    
    def get_available_templates(self) -> List[str]:
        """Get a fresh, sorted list of available templates."""
        return self.template_engine.list_templates(config.get_template_dir())

    def get_wildcard_names(self) -> List[str]:
        """Get the names (keys) of all loaded wildcards."""
        return list(self.template_engine.wildcards.keys())

    def get_wildcard_files(self) -> List[str]:
        """Get list of available wildcard files."""
        return self.template_engine.list_wildcard_files(self._get_wildcard_load_order())

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

    def generate_single_structured_prompt(self, template_content: str, existing_segments: Optional[List[PromptSegment]] = None, force_reroll: Optional[List[str]] = None) -> List[PromptSegment]:
        """Generates a single structured prompt for GUI use, optionally reusing existing wildcard choices."""
        return self.template_engine.generate_structured_prompt(template_content, existing_segments=existing_segments, force_reroll=force_reroll)

    def get_wildcard_options(self, wildcard_name: str) -> List[str]:
        """Pass-through to get wildcard options."""
        return self.template_engine.get_wildcard_options(wildcard_name)
    
    def get_system_prompt_files(self) -> List[str]:
        """Get a list of available system prompt files."""
        return sorted([f for f in os.listdir(config.get_system_prompt_dir()) if f.endswith('.txt')])

    def load_system_prompt_content(self, filename: str) -> str:
        """Load the content of a system prompt file."""
        filepath = os.path.join(config.get_system_prompt_dir(), filename)
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

    def generate_raw_prompts(self, 
                           template_content: str, 
                           count: int) -> List[str]:
        """Generate raw prompts from template."""
        prompts = []
        for _ in range(count):
            prompt = self.template_engine.generate_prompt(template_content)
            prompts.append(prompt)
        return prompts
    
    def save_results(self, results: List[Dict[str, Any]]) -> None:
        """Save results to CSV."""
        self.csv_manager.save_batch_results(results)
    
    def save_skipped_prompt(self, prompt: str) -> None:
        """Save a skipped prompt to prevent regeneration."""
        self.csv_manager.save_result(prompt, "", "", status="skipped")
    
    def cleanup_model(self, model: str) -> None:
        """Unload model to free resources."""
        self.ollama_client.unload_model(model)