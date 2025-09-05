"""Main prompt processing and coordination logic."""

import json
import copy
import os
import random
import re
import uuid
import threading
from typing import List, Dict, Any, Optional, Callable, Tuple, Set
from .template_engine import TemplateEngine, PromptSegment
from .history_manager import HistoryManager
from .config import config
from .default_content import (DEFAULT_SFW_ENHANCEMENT_INSTRUCTION, DEFAULT_SFW_VARIATIONS, DEFAULT_PLANNER_SELECT_WILDCARDS_PROMPT, DEFAULT_AI_BREED_PROMPTS_PROMPT,
                              DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION, DEFAULT_NSFW_VARIATIONS, DEFAULT_AI_AUTO_TAG_PROMPT,
                              DEFAULT_BRAINSTORM_TEMPLATE_PROMPT, DEFAULT_BRAINSTORM_WILDCARD_PROMPT, DEFAULT_AI_REFACTOR_CHOICES_PROMPT,
                              DEFAULT_BRAINSTORM_LINKED_WILDCARD_PROMPT_ADDITION,
                              DEFAULT_GENERATE_TEMPLATE_FROM_WILDCARDS_PROMPT,
                              DEFAULT_BRAINSTORM_SUGGEST_WILDCARD_CHOICES_PROMPT,
                              DEFAULT_BRAINSTORM_REWRITE_PROMPT, DEFAULT_AI_FIX_GRAMMAR_PROMPT, DEFAULT_AI_ADD_BRIDGE_PHRASES_PROMPT, DEFAULT_AI_CLEANUP_PROMPT,
                              DEFAULT_AI_FIX_WILDCARD_ERROR_PROMPT,
                              DEFAULT_AI_FIX_JSON_SYNTAX_PROMPT)
from .ollama_client import OllamaClient
from .invokeai_client import InvokeAIClient
from .utils import sanitize_wildcard_choices
from datetime import datetime

class PromptProcessor:
    """Coordinates prompt generation and enhancement workflow."""
    
    def __init__(self, verbose: bool = False):
        self.template_engine = TemplateEngine()
        # Lazily import OllamaClient to avoid issues if it's not needed (e.g., in GUI)
        self.ollama_client = OllamaClient(base_url=config.OLLAMA_BASE_URL)
        self.invokeai_client = InvokeAIClient(base_url=config.INVOKEAI_BASE_URL)
        self.history_manager = HistoryManager()
        self.all_wildcards_cache: Optional[Dict[str, Dict]] = None
        self.verbose = verbose
        self.rng = random.Random()
        self._used_wildcards_cache: Optional[Set[str]] = None
        
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
        os.makedirs(os.path.join(config.HISTORY_DIR, 'sfw', 'images'), exist_ok=True)
        os.makedirs(os.path.join(config.HISTORY_DIR, 'nsfw', 'images'), exist_ok=True)
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
        self._used_wildcards_cache = None
        self._load_all_wildcards_into_cache()
        self._update_status("Ready")

    def clear_wildcard_cache_and_reload(self) -> bool:
        """Clears the wildcard cache file and reloads all wildcards from disk."""
        if self.template_engine.clear_wildcard_cache_file():
            self.reload_wildcards() # This will re-read from disk and create a new cache.
            return True
        return False

    def get_available_models(self) -> List[str]:
        """Get list of available Ollama models."""
        return self.ollama_client.list_models()
    
    def is_invokeai_connected(self) -> bool:
        """Checks if the InvokeAI client is configured and likely connected."""
        # The client is initialized in the GUI. If the URL in the config is empty,
        # the client exists but won't be able to connect.
        return self.invokeai_client is not None and config.INVOKEAI_BASE_URL != ""
    
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

    def prune_missing_image_entries(self) -> int:
        """Pass-through to prune missing image entries from the history."""
        return self.history_manager.prune_missing_image_entries()

    def garbage_collect_orphaned_images(self) -> int:
        """Pass-through to garbage collect orphaned images."""
        return self.history_manager.garbage_collect_orphaned_images()

    def get_all_history_across_workflows(self) -> List[Dict[str, str]]:
        """Loads and returns history data from all workflows (SFW and NSFW), sorted by timestamp."""
        
        def load_from_path(path: str, workflow_tag: str) -> List[Dict[str, str]]:
            history = []
            if not os.path.exists(path):
                return history
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                            entry['workflow_source'] = workflow_tag
                            history.append(entry)
                        except json.JSONDecodeError:
                            continue # Skip corrupted lines
            except IOError as e:
                print(f"Warning: Could not read history file {path}: {e}")
            return history

        all_history = load_from_path(os.path.join(config.HISTORY_DIR, 'sfw', 'history.jsonl'), 'SFW') + load_from_path(os.path.join(config.HISTORY_DIR, 'nsfw', 'history.jsonl'), 'NSFW')
        all_history.sort(key=lambda x: x.get('timestamp', '0'), reverse=True)
        return all_history
    
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

    def get_all_used_wildcards_for_single_file(self, wildcard_data: Dict) -> Set[str]:
        """Scans a single wildcard's data to find which other wildcards it uses."""
        used_wildcards = set()
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

    def get_all_used_wildcards(self) -> set[str]:
        """
        Scans all templates and wildcards to find which wildcards are actively used.
        This method uses an in-memory cache to avoid re-computation.
        """
        if self._used_wildcards_cache is not None:
            return self._used_wildcards_cache

        # --- Build Dependency Graph (Wildcard -> Wildcards it uses) ---
        dependency_graph: Dict[str, Set[str]] = {}
        if self.all_wildcards_cache:
            for wc_name, wc_data in self.all_wildcards_cache.items():
                dependency_graph[wc_name] = self.get_all_used_wildcards_for_single_file(wc_data)

        # --- Find Root Wildcards (directly used by templates) ---
        root_wildcards = set()
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
                        content = self.template_engine.load_template(template_file, template_dir)
                        found = re.findall(r'__([a-zA-Z0-9_.\s-]+?)__', content)
                        root_wildcards.update(found)
                    except Exception as e:
                        print(f"Warning: Could not scan template {os.path.join(template_dir, template_file)} for used wildcards: {e}")

        # --- Transitive Closure: Find all dependencies starting from the roots ---
        all_used = set()
        queue = list(root_wildcards)
        
        while queue:
            current_wc = queue.pop(0)
            if current_wc not in all_used:
                all_used.add(current_wc)
                # Add its dependencies to the queue to be processed
                if current_wc in dependency_graph:
                    for dependency in dependency_graph[current_wc]:
                        if dependency not in all_used:
                            queue.append(dependency)
        
        self._used_wildcards_cache = all_used
        return self._used_wildcards_cache

    def check_for_circular_dependencies(self, start_node: str, temp_node_data: Optional[Dict] = None) -> Optional[List[str]]:
        """
        Checks for circular dependencies in wildcards starting from a given node.
        Uses Depth First Search (DFS) to detect cycles.
        Returns the path of the cycle if found, otherwise None.
        """
        if self.all_wildcards_cache is None:
            self._load_all_wildcards_into_cache()
        
        if self.all_wildcards_cache is None: return None

        # Temporarily update the cache with the live data from the editor for an accurate check
        original_node_data = self.all_wildcards_cache.get(start_node)
        if temp_node_data is not None:
            self.all_wildcards_cache[start_node] = temp_node_data

        try:
            path = set()
            visited = set()

            def dfs(node: str) -> Optional[List[str]]:
                path.add(node)
                visited.add(node)

                node_data = self.all_wildcards_cache.get(node, {})
                dependencies = self.get_all_used_wildcards_for_single_file(node_data)

                for dependency in dependencies:
                    if dependency not in self.all_wildcards_cache: continue
                    if dependency in path:
                        cycle_path = list(path) + [dependency]
                        return cycle_path[cycle_path.index(dependency):]
                    if dependency not in visited:
                        result = dfs(dependency)
                        if result: return result
                path.remove(node)
                return None
            return dfs(start_node)
        finally:
            # Restore the cache to its original state
            if original_node_data is not None: self.all_wildcards_cache[start_node] = original_node_data
            elif temp_node_data is not None and start_node in self.all_wildcards_cache: del self.all_wildcards_cache[start_node]

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

        # After saving, force a full reload to ensure all caches and lists are perfectly in sync.
        self.reload_wildcards()

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
        self._used_wildcards_cache = None

    def archive_template(self, template_file: str) -> None:
        """Archives a template file."""
        self.template_engine.archive_template(template_file, config.get_template_dir())
        self._used_wildcards_cache = None

    def archive_wildcard(self, wildcard_file: str) -> None:
        """Archives a wildcard file."""
        self.template_engine.archive_wildcard(wildcard_file, self._get_wildcard_search_order())
        # Update the mode-agnostic cache
        basename, _ = os.path.splitext(wildcard_file)
        self._used_wildcards_cache = None
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
        self._used_wildcards_cache = None
        self.template_engine.wildcard_files_cache = None # Invalidate file list cache

    def refactor_template_references(self, old_basename: str, new_basename: str) -> int:
        """
        Scans all template files and replaces references to old_basename with new_basename.
        Returns the number of templates modified.
        """
        modified_files_count = 0
        all_template_dirs = [
            os.path.join(config.TEMPLATE_BASE_DIR, 'sfw'),
            os.path.join(config.TEMPLATE_BASE_DIR, 'nsfw')
        ]

        for template_dir in all_template_dirs:
            if not os.path.exists(template_dir):
                continue
            
            for template_file in os.listdir(template_dir):
                if not template_file.endswith('.txt'):
                    continue
                
                filepath = os.path.join(template_dir, template_file)
                made_change = False
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    new_content, count = re.subn(rf'__({re.escape(old_basename)})__', f'__{new_basename}__', content)
                    
                    if count > 0:
                        made_change = True
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        
                        if template_file in self.template_engine.templates:
                            self.template_engine.templates[template_file] = new_content

                except Exception as e:
                    print(f"Error refactoring template '{filepath}': {e}")
                
                if made_change:
                    modified_files_count += 1
        
        return modified_files_count

    def refactor_all_references(self, old_basename: str, new_basename: str) -> Tuple[int, int]:
        """
        Orchestrates refactoring across both wildcards and templates.
        Returns a tuple of (wildcards_modified_count, templates_modified_count).
        """
        wildcards_modified = self.refactor_wildcard_references(old_basename, new_basename)
        templates_modified = self.refactor_template_references(old_basename, new_basename)
        return wildcards_modified, templates_modified

    def generate_single_structured_prompt(self, template_content: str, existing_context: Optional[Dict[str, Any]] = None, force_reroll: Optional[List[str]] = None, force_swap: Optional[Dict[str, str]] = None, seed: Optional[int] = None) -> Tuple[List[PromptSegment], Dict[str, Any]]:
        """Generates a single structured prompt for GUI use, optionally reusing existing wildcard choices."""
        return self.template_engine.generate_structured_prompt(
            template_content, 
            existing_context=existing_context, 
            force_reroll=force_reroll,
            force_swap=force_swap,
            seed=seed
        )

    def validate_template_order(self, template_content: str) -> Dict[str, str]:
        """
        Validates that any wildcard with a 'requires' clause does not depend on a
        wildcard that appears later in the template.
        Returns a dictionary mapping problematic wildcard names to error messages.
        """
        errors = {}
        # Use the full regex to find all wildcards, but only extract the name (group 2)
        wildcard_pattern = re.compile(r'__(!)?([a-zA-Z0-9_.\s-]+?)(?::\d+(?:-\d+)?)?__')
        wildcards_in_order = [match.group(2) for match in wildcard_pattern.finditer(template_content)]
        
        # Create a map of wildcard name to its first appearance index
        wildcard_indices = {}
        for i, wc_name in enumerate(wildcards_in_order):
            if wc_name not in wildcard_indices:
                wildcard_indices[wc_name] = i

        # Now check each wildcard's requirements
        for wc_name, appearance_index in wildcard_indices.items():
            wildcard_data = self.template_engine.wildcards.get(wc_name)
            if not wildcard_data or 'choices' not in wildcard_data:
                continue

            for choice in wildcard_data.get('choices', []):
                if not isinstance(choice, dict) or 'requires' not in choice:
                    continue
                
                rules = choice.get('requires')
                if not isinstance(rules, dict):
                    continue

                # Recursive helper to find all required wildcard keys
                required_keys = set()
                def find_required_keys(d):
                    for k, v in d.items():
                        if k not in ['tags', 'and', 'or', 'not']:
                            required_keys.add(k)
                        if isinstance(v, dict): find_required_keys(v)
                        elif isinstance(v, list):
                            for item in v:
                                if isinstance(item, dict): find_required_keys(item)
                find_required_keys(rules)

                for req_key in required_keys:
                    req_key_index = wildcard_indices.get(req_key)
                    if req_key_index is None or req_key_index >= appearance_index:
                        errors[wc_name] = f"Requires '{req_key}', which is not present before it in the template."
                        break 
                if wc_name in errors:
                    break

        return errors

    def refactor_wildcard_references(self, old_basename: str, new_basename: str) -> int:
        """
        Scans all wildcard files and replaces references to old_basename with new_basename
        in 'requires' and 'includes' clauses.
        Returns the number of files modified.
        """
        if self.all_wildcards_cache is None:
            self._load_all_wildcards_into_cache()
        
        if self.all_wildcards_cache is None: return 0

        modified_files_count = 0
        
        # We need to iterate over a copy of the items because we might modify the cache
        for wc_name, wc_data in list(self.all_wildcards_cache.items()):
            # Don't refactor the file that was just renamed
            if wc_name == new_basename:
                continue

            modified_data = copy.deepcopy(wc_data)
            made_change = False

            # 1. Refactor global 'includes'
            if 'includes' in modified_data:
                includes = modified_data['includes']
                if isinstance(includes, list) and old_basename in includes:
                    modified_data['includes'] = [new_basename if item == old_basename else item for item in includes]
                    made_change = True
                elif isinstance(includes, str):
                    # Handle template string includes
                    new_includes_str, count = re.subn(rf'__({re.escape(old_basename)})__', f'__{new_basename}__', includes)
                    if count > 0:
                        modified_data['includes'] = new_includes_str
                        made_change = True

            # 2. Refactor 'choices'
            if 'choices' in modified_data and isinstance(modified_data.get('choices'), list):
                for choice in modified_data['choices']:
                    if not isinstance(choice, dict):
                        continue
                    
                    # Refactor choice-level 'includes'
                    if 'includes' in choice:
                        choice_includes = choice['includes']
                        if isinstance(choice_includes, list) and old_basename in choice_includes:
                            choice['includes'] = [new_basename if item == old_basename else item for item in choice_includes]
                            made_change = True
                        elif isinstance(choice_includes, str):
                            new_choice_includes_str, count = re.subn(rf'__({re.escape(old_basename)})__', f'__{new_basename}__', choice_includes)
                            if count > 0:
                                choice['includes'] = new_choice_includes_str
                                made_change = True
                    
                    # Refactor 'requires'
                    if 'requires' in choice and isinstance(choice.get('requires'), dict):
                        def refactor_requires_recursive(d):
                            nonlocal made_change
                            # Use list(d.keys()) to avoid issues with changing dict size during iteration
                            for key in list(d.keys()):
                                if key == old_basename:
                                    d[new_basename] = d.pop(old_basename)
                                    made_change = True
                                    # Continue checking the rest of the dict with the new key
                                    if isinstance(d[new_basename], dict):
                                        refactor_requires_recursive(d[new_basename])
                                    elif isinstance(d[new_basename], list):
                                        for item in d[new_basename]:
                                            if isinstance(item, dict):
                                                refactor_requires_recursive(item)
                                elif isinstance(d[key], dict):
                                    refactor_requires_recursive(d[key])
                                elif isinstance(d[key], list):
                                    for item in d[key]:
                                        if isinstance(item, dict):
                                            refactor_requires_recursive(item)
                        
                        refactor_requires_recursive(choice['requires'])

            if made_change:
                # Save the modified file
                try:
                    # Find the correct directory to save to
                    filename_to_save = f"{wc_name}.json"
                    save_dir = None
                    # This needs to check all possible directories to find where the file lives.
                    # The mode-agnostic cache doesn't store the file's original workflow.
                    all_possible_dirs = [config.WILDCARD_NSFW_DIR, config.WILDCARD_DIR]
                    for directory in all_possible_dirs:
                        if os.path.exists(os.path.join(directory, filename_to_save)):
                            save_dir = directory
                            break
                    
                    if save_dir:
                        self.template_engine.save_wildcard_content(filename_to_save, json.dumps(modified_data, indent=2), save_dir)
                        modified_files_count += 1
                        # Update the cache with the modified data
                        if self.all_wildcards_cache:
                            self.all_wildcards_cache[wc_name] = modified_data
                    else:
                        print(f"Warning: Could not find original path for wildcard '{wc_name}' during refactor. Skipping save.")

                except Exception as e:
                    print(f"Error saving refactored wildcard '{wc_name}': {e}")
        
        return modified_files_count

    def refactor_wildcard_value_references(self, wildcard_name: str, old_value: str, new_value: str) -> int:
        """
        Scans all wildcard files and replaces references to an old value with a new value
        in 'requires' clauses.
        Returns the number of files modified.
        """
        if self.all_wildcards_cache is None:
            self._load_all_wildcards_into_cache()
        
        if self.all_wildcards_cache is None: return 0

        modified_files_count = 0

        for wc_name, wc_data in list(self.all_wildcards_cache.items()):
            modified_data = copy.deepcopy(wc_data)
            made_change = False

            if 'choices' in modified_data and isinstance(modified_data.get('choices'), list):
                for choice in modified_data['choices']:
                    if not isinstance(choice, dict) or 'requires' not in choice:
                        continue
                    
                    if 'requires' in choice and isinstance(choice.get('requires'), dict):
                        def refactor_value_recursive(d):
                            nonlocal made_change
                            for key, value in d.items():
                                if key == wildcard_name:
                                    if isinstance(value, str) and value == old_value:
                                        d[key] = new_value
                                        made_change = True
                                    elif isinstance(value, list) and old_value in value:
                                        d[key] = [new_value if v == old_value else v for v in value]
                                        made_change = True
                                    elif isinstance(value, dict):
                                        # Handle complex conditions like {"any": [...]} or {"not": ...}
                                        if 'any' in value and isinstance(value.get('any'), list) and old_value in value['any']:
                                            value['any'] = [new_value if v == old_value else v for v in value['any']]
                                            made_change = True
                                        if 'not' in value:
                                            not_val = value['not']
                                            if isinstance(not_val, str) and not_val == old_value:
                                                value['not'] = new_value
                                                made_change = True
                                            elif isinstance(not_val, list) and old_value in not_val:
                                                value['not'] = [new_value if v == old_value else v for v in not_val]
                                                made_change = True
                                elif isinstance(value, dict):
                                    refactor_value_recursive(value)
                                elif isinstance(value, list):
                                    for item in value:
                                        if isinstance(item, dict):
                                            refactor_value_recursive(item)
                        
                        refactor_value_recursive(choice['requires'])

            if made_change:
                try:
                    filename_to_save = f"{wc_name}.json"
                    save_dir = None
                    all_possible_dirs = [config.WILDCARD_NSFW_DIR, config.WILDCARD_DIR]
                    for directory in all_possible_dirs:
                        if os.path.exists(os.path.join(directory, filename_to_save)):
                            save_dir = directory
                            break
                    
                    if save_dir:
                        self.template_engine.save_wildcard_content(filename_to_save, json.dumps(modified_data, indent=2), save_dir)
                        modified_files_count += 1
                        if self.all_wildcards_cache:
                            self.all_wildcards_cache[wc_name] = modified_data
                    else:
                        print(f"Warning: Could not find original path for wildcard '{wc_name}' during value refactor. Skipping save.")
                except Exception as e:
                    print(f"Error saving refactored wildcard '{wc_name}': {e}")

        return modified_files_count
    
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
        
        if self.verbose:
            print("\n--- VERBOSE: AI Chat Request ---", flush=True)
            print(f"Model: {model}", flush=True)
            try:
                # Pretty-print the JSON for readability
                print(json.dumps(messages, indent=2), flush=True)
            except (TypeError, json.JSONDecodeError):
                # Fallback for non-serializable content
                print(messages, flush=True)
            print("--------------------------------\n", flush=True)

        try:
            raw_response = self.ollama_client.chat(model, messages)
            if self.verbose:
                print("\n--- VERBOSE: AI Raw Chat Response ---", flush=True)
                print(raw_response, flush=True)
                print("-------------------------------------\n", flush=True)
            return raw_response
        except Exception as e:
            if self.verbose:
                print("\n--- VERBOSE: AI CHAT FAILED ---", flush=True)
                print(f"Error: {e}", flush=True)
                print("-------------------------------\n", flush=True)
            raise # Re-raise so the GUI can handle it and show an error message

    def generate_for_brainstorming(self, model: str, prompt: str) -> str:
        """Handles a one-shot generation task for brainstorming wildcards/templates."""
        if self.verbose:
            print("\n--- VERBOSE: AI Generation Request ---", flush=True)
            print(f"Model: {model}", flush=True)
            print(f"Prompt:\n{prompt}", flush=True)
            print("------------------------------------\n", flush=True)
        
        try:
            # This uses the /api/generate endpoint for single, non-conversational tasks.
            # Use a longer timeout for these complex, creative tasks.
            raw_response = self.ollama_client._generate(model, prompt, config.BRAINSTORM_TIMEOUT).strip()
            if self.verbose:
                print("\n--- VERBOSE: AI Raw Generation Response ---", flush=True)
                print(raw_response, flush=True)
                print("-------------------------------------------\n", flush=True)
            return raw_response
        except Exception as e:
            if self.verbose:
                print("\n--- VERBOSE: AI GENERATION FAILED ---", flush=True)
                print(f"Error: {e}", flush=True)
                print("-------------------------------------\n", flush=True)
            raise # Re-raise so the GUI can handle it and show an error message

    
    def _get_workflow_context(self) -> str:
        """Returns a string describing the current workflow for AI context."""
        return f"The current workflow is '{config.workflow.upper()}', so generate content appropriate for that context."

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
        # Use chat_with_model for better instruction following on complex prompts
        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages)
        return self.ollama_client.parse_template_from_response(raw_response)

    def generate_template_from_all_wildcards(self, model: str, theme: str) -> str:
        """Generates a new template using a smart, AI-driven selection of wildcards based on a theme."""
        # --- Step 1: Use a "planner" AI to select the most relevant wildcards ---
        self._update_status("brainstorm_template_step", step=1, total_steps=2, message="Planning wildcard selection...")
        
        wildcard_list_with_desc_str = self._get_wildcards_with_descriptions_str()
        if wildcard_list_with_desc_str == "none":
            raise ValueError("No wildcards available to generate a template.")

        planner_prompt = DEFAULT_PLANNER_SELECT_WILDCARDS_PROMPT.format(
            theme=theme,
            wildcard_list_with_desc_str=wildcard_list_with_desc_str
        )
        
        # Use a chat call for better instruction following
        planner_messages = [{'role': 'user', 'content': planner_prompt}]
        selected_wildcards_str = self.chat_with_model(model, planner_messages)
        
        # Parse the comma-separated list of wildcard names
        selected_wildcard_names = [w.strip().replace('__', '') for w in selected_wildcards_str.split(',') if w.strip()]
        
        if not selected_wildcard_names:
            raise Exception("The AI planner did not select any wildcards. Please try a different theme.")

        # --- Step 2: Use the selected wildcards to generate the final template ---
        self._update_status("brainstorm_template_step", step=2, total_steps=2, message="Generating template...")
        
        workflow_context = self._get_workflow_context()
        
        # Build a rich sample string using ONLY the selected wildcards
        rich_wildcard_sample_str = self._get_rich_wildcard_sample_str(wildcard_names=selected_wildcard_names)

        generator_prompt = DEFAULT_GENERATE_TEMPLATE_FROM_WILDCARDS_PROMPT.format(
            theme=theme,
            workflow_context=workflow_context,
            wildcard_list_str=rich_wildcard_sample_str
        )

        # Use the one-shot generation method for this task. The AI should return only the template.
        return self.generate_for_brainstorming(model, generator_prompt)

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

    def generate_wildcard_for_brainstorming(self, model: str, topic: str, metadata: Optional[Dict] = None) -> str:
        """Generates wildcard content based on a topic using a structured prompt."""
        try:
            # --- Prepare prompt context ---
            metadata = metadata or {}
            template_context = metadata.get('template_context')
            supporting_wildcard = metadata.get('supporting_wildcard_to_include')
            
            template_context_section = f"\n\n**TEMPLATE CONTEXT:** This wildcard will be used in the following template:\n{template_context}\n" if template_context else ""
            
            linked_wildcard_instruction = ""
            if supporting_wildcard:
                supporting_basename, _ = os.path.splitext(supporting_wildcard)
                linked_wildcard_instruction = DEFAULT_BRAINSTORM_LINKED_WILDCARD_PROMPT_ADDITION.format(
                    topic=topic,
                    supporting_basename=supporting_basename
                )

            workflow_context = self._get_workflow_context()
            wildcard_name_from_topic = topic.replace(' ', '_')
            wildcard_sample_str = self._get_rich_wildcard_sample_str(count=10)

            # --- Build the final prompt ---
            prompt = DEFAULT_BRAINSTORM_WILDCARD_PROMPT.format(
                topic=topic,
                template_context_section=template_context_section,
                linked_wildcard_instruction=linked_wildcard_instruction,
                workflow_context=workflow_context,
                wildcard_name_from_topic=wildcard_name_from_topic,
                wildcard_sample_str=wildcard_sample_str
            )

            # --- Generate and Parse ---
            # Use chat_with_model with the correct message format for better instruction following.
            messages = [{'role': 'user', 'content': prompt}]
            raw_response = self.chat_with_model(model, messages)
            return self.ollama_client.parse_json_object_from_response(raw_response, topic)
        except Exception as e:
            raise Exception(f"Failed to generate wildcard for topic '{topic}': {str(e)}")

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

    def fix_json_syntax_with_ai(self, broken_json: str, model: str) -> str:
        """Uses AI to attempt to fix broken JSON syntax."""
        prompt = DEFAULT_AI_FIX_JSON_SYNTAX_PROMPT.format(broken_json=broken_json)
        
        # Use a one-shot generation call.
        raw_response = self.generate_for_brainstorming(model, prompt)
        
        # The AI should return a JSON blob. We can try to parse it to validate.
        # If it's valid, we return the raw string. If not, we raise an error.
        try:
            # We don't need the parsed data, just to know it's valid.
            json.loads(raw_response)
            return raw_response
        except json.JSONDecodeError as e:
            # The AI failed to produce valid JSON. We can't use its response.
            raise Exception(f"The AI failed to produce valid JSON. Please try again or fix it manually. Parser error: {e}")

    def ai_fix_wildcard_grammar(self, wildcard_content: str, model: str) -> str:
        """Uses AI to fix grammatical issues in a wildcard file's choices and includes."""
        
        prompt = DEFAULT_AI_FIX_GRAMMAR_PROMPT.replace('{wildcard_content}', wildcard_content)
        
        # Use chat for better instruction following
        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages)
        
        json_str = None
        match = re.search(r'```json\s*(\{.*?\})\s*```', raw_response, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            start = raw_response.find('{')
            end = raw_response.rfind('}')
            if start != -1 and end != -1 and start < end:
                json_str = raw_response[start:end+1]
        if not json_str:
            raise Exception(f"The AI did not return a recognizable JSON object. Response:\n{raw_response}")

        try:
            parsed_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise Exception(f"The AI returned malformed JSON. Parser error: {e}\n\nRaw response snippet:\n{json_str[:500]}")
        # --- Structural Validation ---
        if not isinstance(parsed_data, dict):
            raise Exception(f"The AI returned a valid JSON, but it was not the expected object structure (e.g., it might be a list). Response:\n{json_str[:500]}")

        if 'choices' not in parsed_data:
            error_guess = parsed_data.get('error', parsed_data.get('message', 'The "choices" key was missing from the response.'))
            raise Exception(f"The AI's response was missing the required 'choices' field. AI message: {error_guess}")

        if not isinstance(parsed_data['choices'], list):
            raise Exception(f"The 'choices' field in the AI's response was not a list. Type was: {type(parsed_data['choices']).__name__}")

        # --- Sanitization and Return ---
        parsed_data['choices'] = sanitize_wildcard_choices(parsed_data.get('choices', []))
        return json.dumps(parsed_data, indent=2)

    def _ai_refactor_choices(self, primary_filename: str, primary_content: str, supporting_filename: str, supporting_content: str, model: str) -> Dict[str, Any]:
        """Step 1 of compatibility check: Refactor choices between files using AI."""
        prompt = DEFAULT_AI_REFACTOR_CHOICES_PROMPT.format(
            primary_filename=primary_filename,
            primary_content=primary_content,
            supporting_filename=supporting_filename,
            supporting_content=supporting_content
        )
        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages)
        
        # --- Custom Parsing Logic for this specific task ---
        # This bypasses the standard parser's fallback which is not suitable here.
        json_str = None
        match = re.search(r'```json\s*(\{.*?\})\s*```', raw_response, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            start = raw_response.find('{')
            end = raw_response.rfind('}')
            if start != -1 and end != -1 and start < end:
                json_str = raw_response[start:end+1]

        if not json_str:
            raise Exception(f"AI response did not contain a recognizable JSON object. Raw response:\n{raw_response[:500]}")
        
        try:
            # The response should be a single JSON object with filenames as keys.
            data = json.loads(json_str)
            if primary_filename not in data or supporting_filename not in data:
                raise KeyError("AI response missing one or both filenames as keys.")
            return data
        except (json.JSONDecodeError, KeyError) as e:
            raise Exception(f"AI failed to return valid refactored JSON for both files. Error: {e}\nResponse: {json_str[:500]}")

    def _ai_add_bridge_phrases(self, primary_filename: str, primary_content: str, supporting_filename: str, supporting_content: str, model: str) -> str:
        """Step 2 of compatibility check: Add bridge phrases to the primary file."""
        prompt = DEFAULT_AI_ADD_BRIDGE_PHRASES_PROMPT.format(
            primary_filename=primary_filename,
            primary_content=primary_content,
            supporting_filename=supporting_filename,
            supporting_content=supporting_content
        )
        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages)
        # This prompt should return a single JSON object for the primary file.
        return self.ollama_client.parse_json_object_from_response(raw_response, primary_filename)

    def ai_check_wildcard_compatibility(self, primary_filename: str, primary_content: str, supporting_filename: str, supporting_content: str, model: str) -> Dict[str, str]:
        """Uses a multi-step AI process to refactor and make two wildcard files grammatically compatible."""
        # --- Step 1: Refactor choices between files ---
        self._update_status("compatibility_check_step", step=1, total_steps=2, message="Refactoring misplaced choices...")
        refactored_data = self._ai_refactor_choices(primary_filename, primary_content, supporting_filename, supporting_content, model)

        refactored_primary_data = refactored_data[primary_filename]
        refactored_supporting_data = refactored_data[supporting_filename]

        # --- Step 2: Add bridge phrases to the now-refactored primary file ---
        self._update_status("compatibility_check_step", step=2, total_steps=2, message="Fixing grammar...")
        final_primary_content_str = self._ai_add_bridge_phrases(
            primary_filename, json.dumps(refactored_primary_data, indent=2),
            supporting_filename, json.dumps(refactored_supporting_data, indent=2),
            model
        )

        # --- Step 3: Sanitize and return the final state of both files ---
        def process_file_data(filename: str, content: Any) -> str:
            file_data = content
            if isinstance(file_data, str):
                try:
                    file_data = json.loads(file_data)
                except json.JSONDecodeError:
                    raise Exception(f"AI returned a string for {filename} that is not valid JSON.")
            if not isinstance(file_data, dict):
                raise Exception(f"The content for {filename} returned by the AI was not a JSON object.")
            if 'choices' in file_data and isinstance(file_data.get('choices'), list):
                file_data['choices'] = sanitize_wildcard_choices(file_data['choices'])
            return json.dumps(file_data, indent=2)

        return {
            primary_filename: process_file_data(primary_filename, final_primary_content_str),
            supporting_filename: process_file_data(supporting_filename, refactored_supporting_data)
        }

    def ai_cleanup_prompt(self, prompt_to_clean: str, model: str) -> str:
        """Pass-through to the Ollama client to clean up a prompt with AI."""
        return self.ollama_client.cleanup_prompt_with_ai(prompt_to_clean, model)


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

            # Send back the main enhancement result immediately
            if self.result_callback:
                self.result_callback('enhanced', {'prompt': enhanced, 'sd_model': enhanced_sd_model})

            result = {
                'original': prompt,
                'enhanced': {'prompt': enhanced, 'sd_model': enhanced_sd_model},
                'variations': {},
                'status': 'enhanced',
                'template_name': template_name,
            }
            
            # Create variations if requested
            if selected_variations:
                for var_type in selected_variations:
                    if cancellation_event and cancellation_event.is_set():
                        break # break inner loop

                    variation_instruction = available_variations[var_type]['prompt']
                    self._update_status('variation_start', var_type=var_type, prompt_num=i+1, total_prompts=total_prompts)
                    var_prompt, var_sd_model = self.ollama_client.create_single_variation(variation_instruction, enhanced, enhanced_sd_model, model, var_type)
                    variation_result = {'prompt': var_prompt, 'sd_model': var_sd_model}
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
        enhanced, enhanced_sd_model = self.ollama_client.enhance_prompt(full_prompt, model)
        return enhanced, enhanced_sd_model

    def regenerate_variation(self, base_prompt: str, base_sd_model: str, model: str, variation_type: str) -> Dict[str, str]:
        """Regenerates a single variation."""
        available_variations = {v['key']: v for v in self.get_available_variations()}
        variation_data = available_variations.get(variation_type)
        if not variation_data:
            raise ValueError(f"Variation '{variation_type}' not found or is invalid.")
        instruction = variation_data['prompt']
        var_prompt, var_sd_model = self.ollama_client.create_single_variation(instruction, base_prompt, base_sd_model, model, variation_type)
        return {'prompt': var_prompt, 'sd_model': var_sd_model}

    def cleanup_prompt_string(self, prompt: str) -> str:
        """Pass-through to the template engine's cleanup method."""
        return self.template_engine.cleanup_prompt_string(prompt)

    def _get_wildcards_with_descriptions_str(self) -> str:
        """Gets a formatted string of all wildcards and their descriptions for AI context."""
        if not self.all_wildcards_cache:
            self._load_all_wildcards_into_cache()
        
        if not self.all_wildcards_cache:
            return "none"

        parts = []
        for wc_name, wc_data in sorted(self.all_wildcards_cache.items()):
            description = wc_data.get('description', 'No description available.')
            parts.append(f"- __{wc_name}__: {description}")
        
        return "\n".join(parts)

    def _get_rich_wildcard_sample_str(self, count: int = 15, wildcard_names: Optional[List[str]] = None) -> str:
        """Gets a string of sample wildcards with example values for AI context."""
        all_wildcard_names = self.get_wildcard_names()
        if not all_wildcard_names:
            return "none"

        if wildcard_names:
            # Use the provided list of names, ensuring they exist
            wildcard_sample_names = [name for name in wildcard_names if name in all_wildcard_names]
        else:
            # Fallback to random sampling if no list is provided
            sample_size = min(count, len(all_wildcard_names))
            wildcard_sample_names = self.rng.sample(all_wildcard_names, sample_size)
        
        rich_sample_parts = []
        for wc_name in wildcard_sample_names:
            options = self.get_wildcard_options(wc_name)
            if options:
                option_sample = self.rng.sample(options, min(3, len(options)))
                # Truncate long options for the prompt
                truncated_options = [(opt[:30] + '...' if len(opt) > 30 else opt) for opt in option_sample]
                rich_sample_parts.append(f"- __{wc_name}__: (e.g., \"{', '.join(truncated_options)}\")")
            else:
                rich_sample_parts.append(f"- __{wc_name}__ (empty)")
        
        return "\n".join(rich_sample_parts) if rich_sample_parts else "none"

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

    def _format_suggestion_prompt(self, topic: str, description: str, sample_choices_str: str, instructions: str, other_wildcard_sample: str, workflow_context: str) -> str:
        """Formats the final prompt string for the AI suggestion task."""
        return DEFAULT_BRAINSTORM_SUGGEST_WILDCARD_CHOICES_PROMPT.format(
            topic=topic,
            description=description,
            sample_choices_str=sample_choices_str,
            instructions=instructions,
            other_wildcard_sample=other_wildcard_sample,
            workflow_context=workflow_context
        )

    def suggest_wildcard_choices(self, wildcard_data: Dict[str, Any], model: str, current_wildcard_filename: Optional[str] = None) -> List[Any]:
        """Uses AI to suggest new choices for an existing wildcard file."""
        # 1. Prepare context
        topic, description, sample_choices_str, other_wildcard_sample, current_wildcard_name = self._prepare_suggestion_context(wildcard_data, current_wildcard_filename)
        workflow_context = self._get_workflow_context()

        # 2. Build instructions
        formatted_instructions = self._build_suggestion_instructions(topic, current_wildcard_name)

        # 3. Format the final prompt
        prompt = self._format_suggestion_prompt(
            topic=topic,
            description=description,
            sample_choices_str=sample_choices_str,
            instructions=formatted_instructions,
            other_wildcard_sample=other_wildcard_sample,
            workflow_context=workflow_context
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

    def ai_auto_tag_choices(self, wildcard_data: Dict[str, Any], model: str, current_wildcard_filename: Optional[str] = None) -> List[Any]:
        """Uses AI to automatically add tags to a list of wildcard choices."""

        description = wildcard_data.get('description', 'No description provided.')
        choices = wildcard_data.get('choices', [])
        if not choices:
            raise ValueError("No choices found in the wildcard file to tag.")

        topic = "the given theme"
        if current_wildcard_filename:
            topic = os.path.splitext(current_wildcard_filename)[0].replace('_', ' ')

        choices_json = json.dumps(choices, indent=2)

        prompt = DEFAULT_AI_AUTO_TAG_PROMPT.format(
            description=description,
            topic=topic,
            choices_json=choices_json
        )

        # Use chat for better instruction following
        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages)

        # The response should be a JSON array.
        return self.ollama_client.parse_json_array_from_response(raw_response)

    def generate_image_with_invokeai(self, prompt: str, negative_prompt: str, seed: int, model_object: Dict[str, Any], loras: List[Dict[str, Any]], steps: int, cfg_scale: float, scheduler: str, cfg_rescale_multiplier: float) -> bytes:
        """Generates an image with InvokeAI and returns the raw image bytes."""
        self.invokeai_client.check_server_compatibility() # This will raise a specific error if there's a problem.

        return self.invokeai_client.generate_image(
            prompt=prompt, 
            negative_prompt=negative_prompt, 
            seed=seed, 
            model_object=model_object,
            loras=loras,
            steps=steps,
            cfg_scale=cfg_scale,
            scheduler=scheduler,
            cfg_rescale_multiplier=cfg_rescale_multiplier,
            verbose=self.verbose
        )

    def save_generated_image(self, image_bytes: bytes) -> str:
        """Saves image bytes to the history folder and returns the relative path."""
        # Save the image to the correct history subfolder
        image_dir = os.path.join(config.get_history_file_dir(), 'images')
        image_filename = f"{uuid.uuid4()}.png"
        image_path = os.path.join(image_dir, image_filename)

        with open(image_path, 'wb') as f:
            f.write(image_bytes)
            
        return os.path.join('images', image_filename)

    def ai_interrogate_image(self, base64_image: str, model: str, prompt: str) -> str:
        """Pass-through to the Ollama client to generate a prompt from an image."""
        return self.ollama_client.interrogate_image(model, base64_image, prompt)

    def ai_breed_prompts(self, parent_prompts: List[str], num_children: int, model: str) -> List[str]:
        """Uses AI to 'breed' new prompts from a list of parent prompts."""
        if len(parent_prompts) < 2:
            raise ValueError("Breeding requires at least two parent prompts.")

        parent_prompts_str = ""
        for i, p in enumerate(parent_prompts):
            parent_prompts_str += f"Parent {i+1}: {p}\n"

        prompt = DEFAULT_AI_BREED_PROMPTS_PROMPT.format(
            parent_prompts_str=parent_prompts_str.strip(),
            num_children=num_children
        )

        # Use chat for better instruction following on complex tasks.
        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages)

        # Parse the numbered list response
        child_prompts = []
        for line in raw_response.splitlines():
            # Remove numbered list prefix, then strip whitespace and any surrounding backticks.
            cleaned_line = re.sub(r"^\d+\.\s*", "", line).strip().strip('`')
            if cleaned_line:
                child_prompts.append(cleaned_line)
        
        return child_prompts

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
    
    def save_skipped_prompt(self, prompt: str) -> None:
        """Save a skipped prompt to prevent regeneration."""
        self.history_manager.save_result(original_prompt=prompt, status="skipped")
    
    def cleanup_model(self, model: str) -> None:
        """Unload model to free resources."""
        self.ollama_client.unload_model(model)