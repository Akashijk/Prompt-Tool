"""Main prompt processing and coordination logic."""

import json
import os
import random
import re
import threading
from typing import List, Dict, Any, Optional, Callable, Tuple, Set
from .template_engine import TemplateEngine, PromptSegment
from .csv_manager import HistoryManager
from .config import config
from .default_content import (DEFAULT_SFW_ENHANCEMENT_INSTRUCTION, DEFAULT_SFW_VARIATIONS,
                              DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION, DEFAULT_NSFW_VARIATIONS,
                              DEFAULT_BRAINSTORM_TEMPLATE_PROMPT, DEFAULT_BRAINSTORM_WILDCARD_PROMPT,
                              DEFAULT_BRAINSTORM_LINKED_WILDCARD_PROMPT_ADDITION,
                              DEFAULT_BRAINSTORM_SUGGEST_WILDCARD_CHOICES_PROMPT,
                              DEFAULT_BRAINSTORM_REWRITE_PROMPT)
from .ollama_client import OllamaClient
from datetime import datetime

class PromptProcessor:
    """Coordinates prompt generation and enhancement workflow."""
    
    def __init__(self):
        self.template_engine = TemplateEngine()
        # Lazily import OllamaClient to avoid issues if it's not needed (e.g., in GUI)
        self.ollama_client = OllamaClient(base_url=config.OLLAMA_BASE_URL) 
        self.history_manager = HistoryManager()
        self.all_wildcards_cache: Optional[Dict[str, Dict]] = None
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
        self._load_all_wildcards_into_cache()
        
        self._update_status("Initializing directories...")
        self._initialize_directories()

        self._update_status("Loading templates...")
        self.template_engine.list_templates(config.get_template_dir())
        
        self._update_status("Ready")
    
    def _load_all_wildcards_into_cache(self):
        """Loads all wildcards from all directories into an internal, mode-agnostic cache."""
        all_dirs = [config.WILDCARD_DIR, config.WILDCARD_NSFW_DIR]
        self.all_wildcards_cache = self.template_engine.get_all_wildcards_data_from_dirs(all_dirs)
    
    def _initialize_directories(self):
        """Ensures all necessary directories for templates and system prompts exist."""
        # Always ensure base directories exist.
        os.makedirs(os.path.join(config.TEMPLATE_BASE_DIR, 'sfw'), exist_ok=True)
        os.makedirs(os.path.join(config.TEMPLATE_BASE_DIR, 'nsfw'), exist_ok=True)
        os.makedirs(config.WILDCARD_DIR, exist_ok=True)
        os.makedirs(config.WILDCARD_NSFW_DIR, exist_ok=True)
        os.makedirs(os.path.join(config.HISTORY_DIR, 'sfw'), exist_ok=True)
        os.makedirs(os.path.join(config.HISTORY_DIR, 'nsfw'), exist_ok=True)
        os.makedirs(config.SYSTEM_PROMPT_BASE_DIR, exist_ok=True)

        # Check for a flag file to see if we need to create defaults.
        # This avoids disk I/O on every startup after the first one.
        flag_file_path = os.path.join(config.SYSTEM_PROMPT_BASE_DIR, '.defaults_created')
        if os.path.exists(flag_file_path):
            return

        # If no flag file, create the defaults and then the flag file.
        self._create_default_files('sfw')
        self._create_default_files('nsfw')

        # Create the flag file to prevent this check on next startup.
        try:
            with open(flag_file_path, 'w') as f:
                f.write(f"Defaults created on {datetime.now().isoformat()}")
        except IOError as e:
            print(f"Warning: Could not create defaults flag file: {e}")

    def _create_default_files(self, workflow: str):
        """
        Creates default enhancement and variation files for a given workflow if they don't exist.
        This is designed to not overwrite user customizations.
        """
        system_prompt_dir = os.path.join(config.SYSTEM_PROMPT_BASE_DIR, workflow)
        variations_dir = os.path.join(system_prompt_dir, 'variations')
        os.makedirs(variations_dir, exist_ok=True)

        # 1. Create enhancement.txt if it doesn't exist.
        enhancement_path = os.path.join(system_prompt_dir, 'enhancement.txt')
        if not os.path.exists(enhancement_path):
            content = DEFAULT_SFW_ENHANCEMENT_INSTRUCTION if workflow == 'sfw' else DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION
            with open(enhancement_path, 'w', encoding='utf-8') as f:
                f.write(content)

        # 2. Create default variation .json files only if the variations directory is empty of .json files.
        # This prevents recreating defaults if the user has customized their setup.
        try:
            has_json_files = any(f.endswith('.json') for f in os.listdir(variations_dir))
        except FileNotFoundError:
            has_json_files = False

        if not has_json_files:
            default_variations = DEFAULT_SFW_VARIATIONS if workflow == 'sfw' else DEFAULT_NSFW_VARIATIONS
            for key, data in default_variations.items():
                filepath = os.path.join(variations_dir, f"{key}.json")
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)

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
        self._load_all_wildcards_into_cache()
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
                        found = re.findall(r'__([a-zA-Z0-9_.\s-]+?)__', content)
                        used_wildcards.update(found)

                    except Exception as e:
                        print(f"Warning: Could not scan template {os.path.join(template_dir, template_file)} for used wildcards: {e}")

        # 2. Scan all wildcards from all directories for 'includes' clauses
        if self.all_wildcards_cache is None:
            # Fallback in case cache is not loaded, though it should be.
            print("Warning: all_wildcards_cache not populated. Performing slow scan.")
            all_wildcard_dirs = [config.WILDCARD_DIR, config.WILDCARD_NSFW_DIR]
            all_wildcards_data = self.template_engine.get_all_wildcards_data_from_dirs(all_wildcard_dirs)
        else:
            # Use the fast, in-memory cache
            all_wildcards_data = self.all_wildcards_cache
        
        for wildcard_data in all_wildcards_data.values():
            # Check global includes
            global_includes = wildcard_data.get('includes')
            if isinstance(global_includes, list):
                used_wildcards.update(global_includes)
            elif isinstance(global_includes, str):
                used_wildcards.update(re.findall(r'__([a-zA-Z0-9_.\s-]+?)__', global_includes))

            # Check choice-specific includes and requires
            if 'choices' in wildcard_data and isinstance(wildcard_data.get('choices'), list):
                for choice in wildcard_data['choices']:
                    if isinstance(choice, dict):
                        # Handle choice-specific includes
                        choice_includes = choice.get('includes')
                        if isinstance(choice_includes, list):
                            used_wildcards.update(choice_includes)
                        elif isinstance(choice_includes, str):
                            used_wildcards.update(re.findall(r'__([a-zA-Z0-9_.\s-]+?)__', choice_includes))
                        
                        # Handle requires
                        requires_data = choice.get('requires')
                        if isinstance(requires_data, dict):
                            # Recursively find all keys which are wildcard names
                            def find_keys(d):
                                for k, v in d.items():
                                    if k not in ['tags', 'and', 'or', 'not']:
                                        used_wildcards.add(k)
                                    if isinstance(v, dict):
                                        find_keys(v)
                                    elif isinstance(v, list):
                                        for item in v:
                                            if isinstance(item, dict):
                                                find_keys(item)
                            find_keys(requires_data)

        return used_wildcards

    def get_wildcard_dependency_graph(self) -> Dict[str, Dict[str, List[str]]]:
        """
        Builds a dependency graph for all wildcards.
        Returns a dictionary where each key is a wildcard name, and the value is a
        dict containing 'dependencies' (what it uses) and 'dependents' (what uses it).
        """
        if self.all_wildcards_cache is None:
            self._load_all_wildcards_into_cache()
        
        if self.all_wildcards_cache is None: return {}

        graph = {wc_name: {'dependencies': set(), 'dependents': set()} for wc_name in self.all_wildcards_cache.keys()}

        for wc_name, wc_data in self.all_wildcards_cache.items():
            # Use the existing robust logic to find all wildcards this file uses
            used_wildcards = self.get_all_used_wildcards_for_single_file(wc_data)
            
            for dep in used_wildcards:
                if dep in graph: # Ensure the dependency is a known wildcard
                    graph[wc_name]['dependencies'].add(dep)
                    graph[dep]['dependents'].add(wc_name)

        # Convert sets to sorted lists for consistent output
        final_graph = {}
        for wc_name in sorted(graph.keys()):
            final_graph[wc_name] = {
                'dependencies': sorted(list(graph[wc_name]['dependencies'])),
                'dependents': sorted(list(graph[wc_name]['dependents']))
            }
            
        return final_graph

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

        # Update the mode-agnostic cache
        basename, _ = os.path.splitext(new_filename)
        if self.all_wildcards_cache is not None:
            try:
                self.all_wildcards_cache[basename] = json.loads(content)
            except json.JSONDecodeError:
                print(f"Warning: Could not update all_wildcards_cache for {basename} due to invalid JSON.")

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
        # Update the mode-agnostic cache
        basename, _ = os.path.splitext(wildcard_file)
        if self.all_wildcards_cache is not None:
            self.all_wildcards_cache.pop(basename, None)

    def rename_wildcard(self, old_filename: str, new_filename: str) -> None:
        """Renames a wildcard file on disk and updates internal caches."""
        search_order = self._get_wildcard_search_order()
        
        # Perform the file system operation
        self.template_engine.rename_wildcard(old_filename, new_filename, search_order)
        
        # Update caches
        old_basename, _ = os.path.splitext(old_filename)
        new_basename, _ = os.path.splitext(new_filename)

        # Update template engine's main wildcard cache
        if old_basename in self.template_engine.wildcards:
            self.template_engine.wildcards[new_basename] = self.template_engine.wildcards.pop(old_basename)

        # Update the mode-agnostic cache
        if self.all_wildcards_cache is not None and old_basename in self.all_wildcards_cache:
            self.all_wildcards_cache[new_basename] = self.all_wildcards_cache.pop(old_basename)

    def generate_single_structured_prompt(self, template_content: str, existing_segments: Optional[List[PromptSegment]] = None, force_reroll: Optional[List[str]] = None, seed: Optional[int] = None) -> List[PromptSegment]:
        """Generates a single structured prompt for GUI use, optionally reusing existing wildcard choices."""
        return self.template_engine.generate_structured_prompt(
            template_content, 
            existing_segments=existing_segments, 
            force_reroll=force_reroll,
            seed=seed
        )

    def validate_all_wildcards(self) -> List[Dict[str, Any]]:
        """
        Scans all wildcards and validates 'requires' clauses to ensure that
        required values exist in the referenced wildcards.
        """
        errors: List[Dict[str, Any]] = []
        all_wildcards_data = self.all_wildcards_cache
        if not all_wildcards_data:
            self._load_all_wildcards_into_cache()
            all_wildcards_data = self.all_wildcards_cache

        # 1. Create a lookup table of all possible values for each wildcard for fast access.
        wildcard_values_lookup: Dict[str, Set[str]] = {}
        for wc_name, wc_data in all_wildcards_data.items():
            all_values = set()
            for choice in wc_data.get('choices', []):
                value = choice if isinstance(choice, str) else choice.get('value')
                if value is not None:
                    all_values.add(str(value))
            wildcard_values_lookup[wc_name] = all_values

        # 2. Iterate through all choices in all wildcards and validate their 'requires' clauses.
        for wc_name, wc_data in all_wildcards_data.items():
            for i, choice in enumerate(wc_data.get('choices', [])):
                if not isinstance(choice, dict) or 'requires' not in choice:
                    continue

                choice_value = str(choice.get('value', f'#{i+1}'))
                rules = choice.get('requires')
                if not isinstance(rules, dict):
                    errors.append({
                        'source_file': f"{wc_name}.json",
                        'choice_value': choice_value,
                        'message': "Malformed 'requires' clause (must be a dictionary)."
                    })
                    continue

                # Recursive helper to walk through nested 'and'/'or'/'not' rules.
                def check_rules_recursive(current_rules: Dict):
                    logical_ops = ['and', 'or', 'not']
                    for op in logical_ops:
                        if op in current_rules:
                            sub_rules = current_rules[op]
                            if isinstance(sub_rules, list):
                                for sub_rule in sub_rules:
                                    if isinstance(sub_rule, dict): check_rules_recursive(sub_rule)
                            elif isinstance(sub_rules, dict):
                                check_rules_recursive(sub_rules)
                            return

                    for key, condition in current_rules.items():
                        if key == 'tags': continue # Skip tag validation

                        if key not in wildcard_values_lookup:
                            errors.append({
                                'source_file': f"{wc_name}.json",
                                'choice_value': choice_value,
                                'message': f"References a non-existent wildcard: '{key}'."
                            })
                            continue
                        
                        valid_choices_for_key = wildcard_values_lookup[key]
                        values_to_check = []
                        if isinstance(condition, str): values_to_check.append(str(condition))
                        elif isinstance(condition, list): values_to_check.extend([str(v) for v in condition])
                        elif isinstance(condition, dict):
                            if 'any' in condition and isinstance(condition.get('any'), list): values_to_check.extend([str(v) for v in condition['any']])
                            if 'not' in condition:
                                not_val = condition['not']
                                if isinstance(not_val, str): values_to_check.append(str(not_val))
                                elif isinstance(not_val, list): values_to_check.extend([str(v) for v in not_val])
                        
                        for value in values_to_check:
                            if str(value) not in valid_choices_for_key:
                                errors.append({
                                    'source_file': f"{wc_name}.json",
                                    'choice_value': choice_value,
                                    'message': f"References non-existent value '{value}' in wildcard '{key}'.",
                                    'details': {
                                        'type': 'missing_value',
                                        'missing_value': str(value),
                                        'target_wildcard': f"{key}.json"
                                    }
                                })

                check_rules_recursive(rules)

        return errors

    def get_wildcard_options(self, wildcard_name: str) -> List[str]:
        """Pass-through to get wildcard options."""
        return self.template_engine.get_wildcard_options(wildcard_name)
    
    def find_wildcard_choice_object(self, wildcard_name: str, value: str) -> Optional[Any]:
        """Pass-through to find a choice object by its value."""
        return self.template_engine.find_choice_object_by_value(wildcard_name, value)

    def get_system_prompt_files(self) -> List[str]:
        """Get a list of available system prompt files."""
        files = []
        system_prompt_dir = config.get_system_prompt_dir()
        variations_dir = config.get_variations_dir()

        # Add the main enhancement file
        enhancement_file = 'enhancement.txt'
        if os.path.exists(os.path.join(config.get_system_prompt_dir(), enhancement_file)):
            files.append(enhancement_file)

        # Add variation files, prefixing them to distinguish from top-level files
        if os.path.exists(variations_dir):
            for filename in sorted(os.listdir(variations_dir)):
                if filename.endswith('.json'):
                    files.append(os.path.join('variations', filename))
        
        return files

    def get_available_variations(self) -> List[Dict[str, str]]:
        """Scans for and loads all available variation JSON files."""
        variations_dir = config.get_variations_dir()
        if not os.path.exists(variations_dir):
            return []

        variations = []
        for filename in sorted(os.listdir(variations_dir)):
            if filename.endswith('.json'):
                try:
                    filepath = os.path.join(variations_dir, filename)
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        # Validate required keys
                        if 'name' in data and 'prompt' in data:
                            variations.append({
                                'key': os.path.splitext(filename)[0],
                                'name': data['name'],
                                'description': data.get('description', ''),
                                'prompt': data['prompt']
                            })
                except (json.JSONDecodeError, IOError) as e:
                    print(f"Warning: Could not load or parse variation file {filename}: {e}")
        return variations

    def load_system_prompt_content(self, filename: str) -> str:
        """Load the content of a system prompt file."""
        # The filename can be 'enhancement.txt' or 'variations/cinematic.json'
        filepath = os.path.join(config.get_system_prompt_dir(), filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                if filename.endswith('.json'):
                    data = json.load(f)
                    return data.get('prompt', '') # Return only the prompt string
                else:
                    return f.read() # Return raw content for .txt files
        except Exception as e:
            raise Exception(f"Error loading system prompt {filename}: {e}")

    def save_system_prompt_content(self, filename: str, content: str):
        """Save content to a system prompt file."""
        filepath = os.path.join(config.get_system_prompt_dir(), filename)
        try:
            if filename.endswith('.json'):
                # Read existing data, update prompt, and write back to preserve other keys
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data['prompt'] = content
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            else: # .txt file
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
        except Exception as e:
            raise Exception(f"Error saving system prompt {filename}: {e}")

    def get_default_system_prompt(self, filename: str) -> str:
        """Gets the default content for a given system prompt."""
        if filename.endswith('.txt'):
            key = filename.replace('.txt', '')
            if key == 'enhancement':
                return DEFAULT_SFW_ENHANCEMENT_INSTRUCTION if config.workflow == 'sfw' else DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION
        elif filename.endswith('.json'):
            # Filename is like 'variations/cinematic.json'
            key = os.path.basename(filename).replace('.json', '')
            defaults = DEFAULT_SFW_VARIATIONS if config.workflow == 'sfw' else DEFAULT_NSFW_VARIATIONS
            return defaults.get(key, {}).get('prompt', '')
        
        return ""

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

    def generate_wildcard_for_brainstorming(self, model: str, topic: str, metadata: Optional[Dict] = None) -> str:
        """
        Handles one-shot wildcard generation and robust parsing for the brainstorming window.
        This method now constructs the prompt internally.
        """
        if metadata is None:
            metadata = {}

        # --- Prompt Construction ---
        workflow_context = self._get_workflow_context()
        wildcard_name_from_topic = re.sub(r'\s+', '_', topic.strip()).lower()
        wildcard_name_from_topic = re.sub(r'[^a-z0-9_]', '', wildcard_name_from_topic)

        all_wildcard_names = self.get_wildcard_names()
        other_wildcard_names = [wc for wc in all_wildcard_names if wc != wildcard_name_from_topic]
        sample_size = min(5, len(other_wildcard_names))
        wildcard_sample_str = ", ".join(random.sample(other_wildcard_names, sample_size)) if other_wildcard_names else "none"

        linked_wildcard_instruction = ""
        supporting_wildcard_to_include = metadata.get('supporting_wildcard_to_include')
        if supporting_wildcard_to_include:
            supporting_basename, _ = os.path.splitext(supporting_wildcard_to_include)
            linked_wildcard_instruction = DEFAULT_BRAINSTORM_LINKED_WILDCARD_PROMPT_ADDITION.format(
                topic=topic,
                supporting_basename=supporting_basename
            )

        prompt = DEFAULT_BRAINSTORM_WILDCARD_PROMPT.format(
            topic=topic,
            linked_wildcard_instruction=linked_wildcard_instruction,
            workflow_context=workflow_context,
            wildcard_name_from_topic=wildcard_name_from_topic,
            wildcard_sample_str=wildcard_sample_str
        )
        # --- End Prompt Construction ---

        raw_response = self.generate_for_brainstorming(model, prompt)
        return self.ollama_client.parse_json_object_from_response(raw_response, topic)

    def _get_workflow_context(self) -> str:
        """Returns a string describing the current SFW/NSFW workflow context for an AI prompt."""
        if config.workflow == 'nsfw':
            return (
                "The user is currently in NSFW (Not Safe For Work) mode. "
                "The template should be designed for generating explicit, adult-oriented, and pornographic imagery. "
                "It should be descriptive and graphic where appropriate."
            )
        else:
            return "The user is currently in SFW (Safe For Work) mode. The template should be suitable for general-purpose, non-explicit imagery."

    def generate_template_for_brainstorming(self, model: str, concept: str) -> Tuple[str, List[str]]:
        """
        Handles one-shot template generation and robust parsing for the brainstorming window.
        This method now constructs the prompt internally.
        """
        # --- Prompt Construction ---
        workflow_context = self._get_workflow_context()
        wildcard_names = self.get_wildcard_names()
        sample_size = min(15, len(wildcard_names))
        wildcard_sample_str = ", ".join(random.sample(wildcard_names, sample_size)) if wildcard_names else "none"

        prompt = DEFAULT_BRAINSTORM_TEMPLATE_PROMPT.format(
            concept=concept,
            workflow_context=workflow_context,
            wildcard_sample_str=wildcard_sample_str
        )
        #
        raw_response = self.generate_for_brainstorming(model, prompt)
        return self.ollama_client.parse_template_from_response(raw_response)

    def rewrite_text(self, selected_text: str, instructions: str, model: str) -> str:
        """
        Uses an AI model to rewrite a piece of text based on instructions.
        """
        prompt = DEFAULT_BRAINSTORM_REWRITE_PROMPT.format(
            selected_text=selected_text,
            instructions=instructions
        )
        # Use the one-shot generation method for this task.
        return self.generate_for_brainstorming(model, prompt)

    def fix_wildcard_error_with_ai(self, file_content: str, error_details: Dict[str, Any], model: str) -> str:
        """Uses AI to attempt to fix a validation error in a wildcard file."""
        all_wildcard_names = self.get_wildcard_names()
        available_wildcards_str = ", ".join(all_wildcard_names) if all_wildcard_names else "none"

        prompt = DEFAULT_AI_FIX_WILDCARD_ERROR_PROMPT.format(
            file_content=file_content,
            source_file=error_details.get('source_file', 'N/A'),
            choice_value=error_details.get('choice_value', 'N/A'),
            message=error_details.get('message', 'N/A'),
            available_wildcards_str=available_wildcards_str
        )

        # Use a one-shot generation call.
        # We expect a JSON object back, so we can try to parse it.
        raw_response = self.generate_for_brainstorming(model, prompt)
        
        # The AI should return a full JSON blob. We can use the existing parser.
        # The fallback topic isn't super relevant here, but we need to provide something.
        fallback_topic = os.path.splitext(error_details.get('source_file', 'unknown'))[0]
        # This will attempt to parse the JSON and return it as a string, which is what we want.
        # The parser itself returns a string representation of the JSON.
        return self.ollama_client.parse_json_object_from_response(raw_response, fallback_topic)


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
                                cancellation_event: Optional[threading.Event] = None,
                                template_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Process a batch of prompts for enhancement."""
        results = []
        total_prompts = len(prompts)
        
        # Load all available variations once for the batch
        enhancement_instruction = self.load_system_prompt_content('enhancement.txt')
        available_variations = {v['key']: v for v in self.get_available_variations()}
        if selected_variations:
            selected_variations = [v for v in selected_variations if v in available_variations]
        
        for i, prompt in enumerate(prompts):
            if cancellation_event and cancellation_event.is_set():
                self._update_status("batch_cancelled")
                break

            # Enhance the prompt
            self._update_status('enhancement_start', prompt_num=i+1, total_prompts=total_prompts)
            enhanced, enhanced_sd_model = self.ollama_client.enhance_prompt(enhancement_instruction + prompt, model)
            
            result = {
                'original': prompt,
                'enhanced': enhanced,
                'enhanced_sd_model': enhanced_sd_model,
                'variations': {},
                'status': 'enhanced',
                'template_name': template_name
            }
            
            # Send back the main enhancement result immediately
            if self.result_callback:
                self.result_callback('enhanced', {'prompt': enhanced, 'sd_model': enhanced_sd_model})
            
            # Create variations if requested
            if selected_variations:
                for var_type in selected_variations:
                    if cancellation_event and cancellation_event.is_set():
                        break # break inner loop

                    variation_instruction = available_variations[var_type]['prompt']
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
        available_variations = {v['key']: v for v in self.get_available_variations()}
        variation_data = available_variations.get(variation_type)
        if not variation_data:
            raise ValueError(f"Variation '{variation_type}' not found or is invalid.")
        instruction = variation_data['prompt']
        return self.ollama_client.create_single_variation(instruction, base_prompt, base_sd_model, model, variation_type)

    def cleanup_prompt_string(self, prompt: str) -> str:
        """Pass-through to the template engine's cleanup method."""
        return self.template_engine.cleanup_prompt_string(prompt)

    def _get_rich_wildcard_sample_str(self, count: int = 15) -> str:
        """Gets a string of sample wildcards with example values for AI context."""
        wildcard_names = self.get_wildcard_names()
        if not wildcard_names:
            return "none"

        sample_size = min(count, len(wildcard_names))
        wildcard_sample_names = self.rng.sample(wildcard_names, sample_size)
        
        rich_sample_parts = []
        for wc_name in wildcard_sample_names:
            options = self.get_wildcard_options(wc_name)
            if options:
                option_sample = self.rng.sample(options, min(3, len(options)))
                # Truncate long options for the prompt
                truncated_options = [(opt[:30] + '...' if len(opt) > 30 else opt) for opt in option_sample]
                rich_sample_parts.append(f"- {wc_name}: (e.g., \"{', '.join(truncated_options)}\")")
            else:
                rich_sample_parts.append(f"- {wc_name} (empty)")
        
        return "\n".join(rich_sample_parts) if rich_sample_parts else "none"

    def suggest_template_additions(self, prompt: str, model: str) -> str:
        """Uses AI to suggest additions to an existing prompt template."""
        rich_wildcard_sample = self._get_rich_wildcard_sample_str()

        instruction = (
            f"You are a world-class visual artist and prompt engineer with a deep understanding of Stable Diffusion. Your task is to analyze the user's prompt template and suggest 3-5 highly creative and context-aware additions to elevate it from good to exceptional.\n\n"
            f"**EXISTING TEMPLATE:**\n---\n{prompt}\n---\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n"
            f"1.  **Analyze Intent:** Deeply analyze the user's template to understand its core subject, style, and intent.\n"
            f"2.  **Be Creative & Complementary:** Suggest genuinely new and complementary details. Think about lighting, atmosphere, composition, artistic style, camera angles, or specific subject details. Don't just add generic quality tags.\n"
            f"3.  **Use Existing Wildcards:** When relevant, use wildcards from the 'Existing Wildcards' list below. This is preferred over inventing a new one if a good match exists.\n"
            f"4.  **Invent New Wildcards:** If no existing wildcard fits your creative suggestion, invent a new, logically named `__wildcard__`.\n"
            f"5.  **Format:** Return ONLY a comma-separated list of your suggested additions. Do not repeat any part of the original template. Do not include any extra commentary, explanations, or labels like 'SUGGESTIONS:'.\n"
            f"6.  **Be Concise:** Keep the suggestions brief and impactful.\n\n"
            f"**EXISTING WILDCARDS (SAMPLE):**\n{rich_wildcard_sample}\n\n"
            f"**EXAMPLE:**\n"
            f"If the existing template is 'a portrait of a __character_class__, wearing __fantasy_armor__', and 'lighting_style' and 'fantasy_forest' are existing wildcards, a good response would be: '__lighting_style__, in a __fantasy_forest__, intricate details, masterpiece, from behind'\n\n"
            f"Now, provide the suggested additions for the user's template."
        )
        
        # Use the one-shot generation method for this simple task.
        return self.generate_for_brainstorming(model, instruction)

    def _prepare_suggestion_context(self, wildcard_data: Dict[str, Any], current_wildcard_filename: Optional[str]) -> Tuple[str, str, str, str, Optional[str]]:
        """Prepares context variables for the AI suggestion prompt."""
        description = wildcard_data.get('description', 'No description.')
        
        # Get a sample of existing choices to give the AI context
        existing_choices = wildcard_data.get('choices', [])
        sample_size = min(25, len(existing_choices))
        sample_choices_full = self.rng.sample(existing_choices, sample_size) if existing_choices else []
        
        # Extract just the values for a more concise prompt.
        sample_choice_values = [c.get('value') if isinstance(c, dict) else c for c in sample_choices_full]
        sample_choices_str = "\n".join([f"- {val}" for val in sample_choice_values]) if sample_choice_values else "none"
        
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

        return topic, description, sample_choices_str, other_wildcard_sample, current_wildcard_name

    def _build_suggestion_instructions(self, topic: str, current_wildcard_name: Optional[str]) -> str:
        """Builds the list of critical instructions for the AI suggestion prompt."""
        instructions = [
            f"**Stay Strictly on Theme:** Every single new choice MUST be a specific example of '{topic}'. Do not suggest items that are merely related accessories or concepts. For example, if the topic is 'sex positions', do not suggest 'garter belt'.",
            "**JSON Format:** You MUST return a JSON array of the new choices. Do NOT return a full object with 'description', just the array of choices.",
            "**Complex Choices:** The new choices should be a mix of simple strings and complex objects with `weight`, `tags`, `requires`, and `includes` keys where appropriate. The `includes` key can be a list of wildcard names or a template string (e.g., \"wearing a __hat__\").",
            "**Contextual Suggestions:** Use the 'Existing Wildcards' list below to create relevant `requires` and `includes` clauses. The `requires` key must be an object (e.g., `{{\"key\": \"value\"}}`).",
            "**Use Normal Spaces:** For all `value` fields and simple string choices, use normal spaces, NOT underscores (e.g., 'elven archer', not 'elven_archer'). Underscores are only for wildcard names in `includes`.",
        ]
        if current_wildcard_name:
            instructions.append(f"**No Self-Reference:** The `requires` key MUST NOT refer to the wildcard being edited (`{current_wildcard_name}`). This is a critical rule.")
        
        instructions.extend([
            "**CRITICAL - AVOID DUPLICATES:** The list below is a sample of choices that ALREADY EXIST. Do NOT suggest any items from this list. Do NOT suggest minor variations of these items. Your suggestions must be genuinely new and diverse.",
            "**No Extra Text:** Return ONLY the JSON array of new choices."
        ])

        # Format instructions with numbers
        return "\n".join([f"{i+1}.  {inst}" for i, inst in enumerate(instructions)])

    def _format_suggestion_prompt(self, topic: str, description: str, sample_choices_str: str, instructions: str, other_wildcard_sample: str) -> str:
        """Formats the final prompt string for the AI suggestion task."""
        return DEFAULT_BRAINSTORM_SUGGEST_WILDCARD_CHOICES_PROMPT.format(
            topic=topic,
            description=description,
            sample_choices_str=sample_choices_str,
            instructions=instructions,
            other_wildcard_sample=other_wildcard_sample
        )

    def suggest_wildcard_choices(self, wildcard_data: Dict[str, Any], model: str, current_wildcard_filename: Optional[str] = None) -> List[Any]:
        """Uses AI to suggest new choices for an existing wildcard file."""
        # 1. Prepare context
        topic, description, sample_choices_str, other_wildcard_sample, current_wildcard_name = self._prepare_suggestion_context(wildcard_data, current_wildcard_filename)

        # 2. Build instructions
        formatted_instructions = self._build_suggestion_instructions(topic, current_wildcard_name)

        # 3. Format the final prompt
        prompt = self._format_suggestion_prompt(
            topic=topic,
            description=description,
            sample_choices_str=sample_choices_str,
            instructions=formatted_instructions,
            other_wildcard_sample=other_wildcard_sample
        )
            
        # 4. Call the AI and parse the response
        response = self.generate_for_brainstorming(model, prompt)
        return self.ollama_client.parse_json_array_from_response(response)

    def _prepare_refinement_context(self, current_wildcard_filename: Optional[str]) -> Tuple[str, Optional[str], List[str]]:
        """Prepares context for the AI refinement prompt."""
        current_wildcard_name = None
        if current_wildcard_filename:
            current_wildcard_name, _ = os.path.splitext(current_wildcard_filename)

        topic = current_wildcard_name.replace('_', ' ') if current_wildcard_name else "the given topic"

        all_other_wildcards = self.get_wildcard_names()
        if current_wildcard_name:
            all_other_wildcards = [wc for wc in all_other_wildcards if wc != current_wildcard_name]
        
        return topic, current_wildcard_name, sorted(all_other_wildcards)

    def _build_refinement_instructions(self, current_wildcard_name: Optional[str]) -> str:
        """Builds the list of critical instructions for the AI refinement prompt."""
        instructions = [
            "**Analyze and Enrich:** For each choice, add `weight`, `tags`, `requires`, and `includes` where they make sense. Not every item needs every property.",
            "**Do NOT Change Values:** You MUST NOT change the `value` of any choice or the text of any simple string choice. The list of items must remain the same.",
            "**Do NOT Add or Remove Choices:** The returned JSON array MUST contain the exact same number of items as the input `choices` array.",
            "**JSON Format:** You MUST return a JSON array of the refined choices. The structure of each item should be preserved (string or object).",
            "**Strict Wildcard Usage:** For `requires` keys and `includes` values (both list and template string format), you MUST ONLY use wildcards from the 'Available Wildcards' list. Do NOT invent wildcards for these properties. If a suitable wildcard doesn't exist, omit the property.",
            "**Use Normal Spaces:** For all `value` fields, use normal spaces, NOT underscores. Underscores are only for wildcard names in `includes`."
        ]
        if current_wildcard_name:
            instructions.append(f"**No Self-Reference:** The `requires` key MUST NOT refer to the wildcard being edited (`{current_wildcard_name}`).")
        
        instructions.append("**No Extra Text:** Return ONLY the JSON array of refined choices.")

        return "\n".join([f"{i+1}.  {inst}" for i, inst in enumerate(instructions)])

    def _format_refinement_prompt(self, topic: str, description: str, choices_json: str, instructions: str, available_wildcards_str: str) -> str:
        """Formats the final prompt string for the AI refinement task."""
        return (
            f"You are an expert content creator for Stable Diffusion wildcards. Your task is to analyze an existing list of choices for a wildcard on the topic of '{topic}' and enrich them by adding metadata like weights, tags, requirements, and includes.\n\n"
            f"**EXISTING WILDCARD DESCRIPTION:** {description}\n\n"
            f"**CHOICES TO REFINE:**\n{choices_json}\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n{instructions}\n\n"
            f"**AVAILABLE WILDCARDS (for 'requires' and 'includes'):**\n{available_wildcards_str}\n\n"
            f"**EXAMPLES of refined choice objects:**\n"
            f'{{"value": "elven archer", "weight": 3, "tags": ["ranged", "elf"], "requires": {{"fantasy_race": "elf"}}, "includes": ["elven_bow", "leather_armor"]}}\n'
            f'{{"value": "orc shaman", "tags": ["magic", "orc"], "includes": "chanting a __tribal_spell__"}}\n\n'
            f"Now, generate the JSON array of refined choices."
        )

    def refine_wildcard_choices(self, wildcard_data: Dict[str, Any], model: str, current_wildcard_filename: Optional[str] = None) -> List[Any]:
        """Uses AI to refine existing choices by adding weights, tags, requires, and includes."""
        description = wildcard_data.get('description', 'No description.')
        existing_choices = wildcard_data.get('choices', [])
        if not existing_choices:
            raise ValueError("No choices available to refine.")

        # 1. Prepare context
        topic, current_wildcard_name, available_wildcards = self._prepare_refinement_context(current_wildcard_filename)

        # 2. Build instructions
        formatted_instructions = self._build_refinement_instructions(current_wildcard_name)

        # 3. Format the final prompt
        available_wildcards_str = ", ".join(available_wildcards) if available_wildcards else "none"
        prompt = self._format_refinement_prompt(
            topic=topic,
            description=description,
            choices_json=json.dumps(existing_choices, indent=2),
            instructions=formatted_instructions,
            available_wildcards_str=available_wildcards_str
        )
            
        # 4. Call the AI and parse the response
        response = self.generate_for_brainstorming(model, prompt)
        return self.ollama_client.parse_json_array_from_response(response)

    def suggest_chat_reply(self, messages: List[Dict[str, str]], model: str) -> str:
        """Suggests a reply for the user in a brainstorming chat."""
        system_prompt = (
            "You are a creative partner. Based on the following conversation history with an AI assistant for Stable Diffusion, "
            "suggest a concise, relevant, and creative reply for the 'user' to send next. "
            "Your goal is to help the user continue the brainstorming session effectively. "
            "Return ONLY the suggested reply text, without any labels or quotation marks."
        )
        
        # Create a string representation of the history for the one-shot prompt, ignoring the initial system prompt.
        history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in messages if msg.get('role') != 'system'])
        
        prompt = (
            f"{system_prompt}\n\n"
            f"CONVERSATION HISTORY:\n---\n{history_str}\n---\n\n"
            f"SUGGESTED USER REPLY:"
        )
        
        return self.generate_for_brainstorming(model, prompt)

    def save_results(self, results: List[Dict[str, Any]]) -> None:
        """Save results to CSV."""
        self.history_manager.save_batch_results(results)
    
    def save_skipped_prompt(self, prompt: str) -> None:
        """Save a skipped prompt to prevent regeneration."""
        self.history_manager.save_result(prompt, "", "", status="skipped")
    
    def cleanup_model(self, model: str) -> None:
        """Unload model to free resources."""
        self.ollama_client.unload_model(model)