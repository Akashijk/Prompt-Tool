"""Main prompt processing and coordination logic."""

import json
import copy
import os
import random
import re
import time
import uuid
import threading
import queue
from typing import List, Dict, Any, Optional, Callable, Tuple, Set
from .thumbnail_manager import ThumbnailManager
from .config import config
from .default_content import (DEFAULT_SFW_ENHANCEMENT_INSTRUCTION, DEFAULT_SFW_VARIATIONS, DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION, DEFAULT_NSFW_VARIATIONS, DEFAULT_SFW_NEGATIVE_PROMPTS, DEFAULT_NSFW_NEGATIVE_PROMPTS, DEFAULT_AI_TASK_PROMPTS,
                              DEFAULT_PLANNER_SELECT_WILDCARDS_PROMPT, DEFAULT_AI_CHECK_COMPATIBILITY_PROMPT,
                              DEFAULT_AI_FIX_GRAMMAR_PROMPT, DEFAULT_AI_FIX_WILDCARD_ERROR_PROMPT, DEFAULT_AI_REWRITE_TEXT_PROMPT,
                              DEFAULT_AI_FIX_JSON_SYNTAX_PROMPT, DEFAULT_AI_AUTO_TAG_PROMPT)
from .ollama_client import OllamaClient
from .invokeai_client import InvokeAIClient
from .utils import sanitize_wildcard_choices
from datetime import datetime
from .template_engine import TemplateEngine, PromptSegment
from .history_manager import HistoryManager

class PromptProcessor:
    """Coordinates prompt generation and enhancement workflow."""
    
    def __init__(self, verbose: bool = False):
        self.template_engine = TemplateEngine()
        self.thumbnail_manager = ThumbnailManager()
        # Lazily import OllamaClient to avoid issues if it's not needed (e.g., in GUI)
        self.ollama_client = OllamaClient(base_url=config.OLLAMA_BASE_URL)
        self.invokeai_client = InvokeAIClient(base_url=config.INVOKEAI_BASE_URL, verbose=verbose)
        self.history_manager: 'HistoryManager' = HistoryManager()
        self.model_prefixes: Dict[str, Dict[str, str]] = {}
        self.lora_prefixes: Dict[str, Dict[str, str]] = {}
        self.all_wildcards_cache: Optional[Dict[str, Dict]] = None
        self.verbose = verbose
        self.rng = random.Random()
        self._avg_gen_times_cache: Optional[Dict[str, float]] = None
        self._default_negative_prompt_cache: Optional[str] = None
        self._used_wildcards_cache: Optional[Set[str]] = None
        self.available_variations_map: Dict[str, str] = {}
        
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
        self.model_prefixes = self.load_model_prefixes()
        self.lora_prefixes = self.load_lora_prefixes()
        
        self.available_variations_map = {v['key']: v['name'] for v in self.get_available_variations()}
        
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

        # Always run the AI task file creation, as it's idempotent and may have been
        # added in a newer version of the app. This ensures existing users get new prompts.
        self._create_default_ai_task_files()

        # Check for a flag file to see if we need to create defaults.
        # This avoids disk I/O on every startup after the first one.
        flag_file_path = os.path.join(config.SYSTEM_PROMPT_BASE_DIR, '.defaults_created')
        if os.path.exists(flag_file_path):
            return

        # If no flag file, create the SFW/NSFW-specific defaults and then the flag file.
        self._create_default_files('sfw')
        self._create_default_files('nsfw')

        # Create the flag file to prevent this check on next startup.
        try:
            with open(flag_file_path, 'w') as f:
                f.write(f"Defaults created on {datetime.now().isoformat()}")
        except IOError as e:
            print(f"Warning: Could not create defaults flag file: {e}")

    def _create_default_ai_task_files(self):
        """Creates default AI task prompt files if they don't exist."""
        ai_task_dir = os.path.join(config.SYSTEM_PROMPT_BASE_DIR, 'ai_tasks')
        os.makedirs(ai_task_dir, exist_ok=True)

        for key, data in DEFAULT_AI_TASK_PROMPTS.items():
            filepath = os.path.join(ai_task_dir, data['filename'])
            if not os.path.exists(filepath):
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(data['content'])

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

        # 3. Create default negative prompt .json files.
        neg_prompts_dir = os.path.join(system_prompt_dir, 'negative_prompts')
        os.makedirs(neg_prompts_dir, exist_ok=True)
        try:
            has_txt_files_neg = any(f.endswith('.txt') for f in os.listdir(neg_prompts_dir))
        except FileNotFoundError:
            has_txt_files_neg = False

        if not has_txt_files_neg:
            default_neg_prompts = DEFAULT_SFW_NEGATIVE_PROMPTS if workflow == 'sfw' else DEFAULT_NSFW_NEGATIVE_PROMPTS
            for key, content in default_neg_prompts.items():
                filepath = os.path.join(neg_prompts_dir, f"{key}.txt")
                with open(filepath, 'w', encoding='utf-8') as f:
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
        # --- FIX: Also reload templates to reflect the new workflow ---
        self._update_status("Reloading templates...")
        self.template_engine.list_templates(config.get_template_dir())
        # --- End of fix ---
        self._used_wildcards_cache = None
        self._template_usage_map_cache = None
        self._load_all_wildcards_into_cache()
        self.available_variations_map = {v['key']: v['name'] for v in self.get_available_variations()}
        self._update_status("Ready")

    def clear_wildcard_cache_and_reload(self) -> bool:
        """Clears the wildcard cache file and reloads all wildcards from disk."""
        if self.template_engine.clear_wildcard_cache_file():
            self.reload_wildcards() # This will re-read from disk and create a new cache.
            return True
        return False

    def get_ollama_models(self) -> List[Dict[str, Any]]:
        """Get list of available Ollama models with their details."""
        return self.ollama_client.list_models()

    def get_invokeai_models(self, base_model: Optional[str] = None, model_type: str = 'main') -> List[Dict[str, Any]]:
        """Gets a list of main models from InvokeAI."""
        self.invokeai_client.check_server_compatibility()
        return self.invokeai_client.get_models(model_type=model_type, base_model=base_model)

    def get_invokeai_loras(self, base_model: Optional[str] = None, model_type: str = 'lora') -> List[Dict[str, Any]]:
        """Gets a list of LoRA models from InvokeAI."""
        self.invokeai_client.check_server_compatibility()
        return self.invokeai_client.get_models(model_type=model_type, base_model=base_model)

    def get_model_recommendations(self, models: List[str]) -> List[tuple]:
        """Get recommended models with reasons."""
        return self.ollama_client.get_model_recommendations(models)
    def delete_history_entry(self, row_to_delete: Dict[str, str]) -> bool:
        """Pass-through to delete a history entry."""
        return self.history_manager.delete_history_entry(row_to_delete)

    def update_history_entry(self, original_row: Dict[str, str], updated_row: Dict[str, str]) -> bool:
        """Pass-through to update a history entry, ensuring timestamp is preserved."""
        # Explicitly preserve the original timestamp to prevent it from being updated.
        if 'timestamp' in original_row:
            updated_row['timestamp'] = original_row['timestamp']
        return self.history_manager.update_history_entry(original_row, updated_row)

    def get_full_history(self) -> List[Dict[str, str]]:
        """Pass-through to get the full history data from all workflows, sorted newest first."""
        return self.get_all_history_across_workflows()

    def clear_invokeai_cache(self):
        """Clears the InvokeAI model cache synchronously."""
        if not self.is_invokeai_connected():
            return
        if not self.invokeai_client.empty_model_cache():
            print("ERROR: Failed to clear InvokeAI model cache.")

    def clear_invokeai_data_cache(self):
        """Clears the cached InvokeAI models, LoRAs, and schedulers."""
        if self.is_invokeai_connected():
            self.invokeai_client.clear_cache()

    def prune_missing_image_entries(self) -> int:
        """Pass-through to prune missing image entries from the history."""
        return self.history_manager.prune_missing_image_entries()

    def garbage_collect_orphaned_images(self) -> int:
        """Pass-through to garbage collect orphaned images."""
        return self.history_manager.garbage_collect_orphaned_images()
    def load_model_prefixes(self) -> Dict[str, Dict[str, str]]:
        """Loads model-specific prompt prefixes."""
        return self._load_prefixes(config.MODEL_PREFIXES_FILE)

    def save_model_prefixes(self, prefixes: Dict[str, Dict[str, Any]]):
        """Saves the model prefixes."""
        self._save_prefixes(config.MODEL_PREFIXES_FILE, prefixes)
        self.model_prefixes = prefixes

    def load_lora_prefixes(self) -> Dict[str, Dict[str, str]]:
        """Loads LoRA-specific prompt prefixes."""
        return self._load_prefixes(config.LORA_PREFIXES_FILE)

    def save_lora_prefixes(self, prefixes: Dict[str, Dict[str, str]]):
        """Saves the LoRA prefixes."""
        self._save_prefixes(config.LORA_PREFIXES_FILE, prefixes)
        self.lora_prefixes = prefixes

    def _load_prefixes(self, file_path: str) -> Dict[str, Dict[str, Any]]:
        """Generic method to load prefixes from a JSON file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_prefixes(self, file_path: str, prefixes: Dict[str, Dict[str, Any]]):
        """Generic method to save prefixes to a JSON file."""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(prefixes, f, indent=2)
        except IOError as e:
            raise Exception(f"Could not write to prefixes file at {file_path}: {e}")
    
    def is_ollama_connected(self) -> bool:
        """Checks if the Ollama client is configured and can connect to the server."""
        # A robust check is to see if a successful API call has been made,
        # indicated by the `has_successfully_connected` flag.
        return self.ollama_client is not None and self.ollama_client.has_successfully_connected
    
    def is_invokeai_connected(self) -> bool:
        """Checks if the InvokeAI client is configured and likely connected."""
        # A robust check is to see if the models_endpoint has been successfully determined
        # by the check_server_compatibility method. This confirms a successful handshake
        # with a compatible server.
        return self.invokeai_client is not None and self.invokeai_client.models_endpoint is not None

    def get_model_stats(self) -> Dict[str, Dict[str, float]]:
        """Calculates usage and performance stats per model from history."""
        all_history = self.get_all_history_across_workflows()
        # {model_name: {'count': int, 'duration_count': int, 'total_duration': float, 'min_duration': float, 'max_duration': float}}
        model_stats: Dict[str, Dict[str, Any]] = {}

        def process_images(images: List[Dict[str, Any]]):
            if not images: return
            for img in images:
                params = img.get('generation_params', {})
                if not params: continue

                duration = params.get('duration')
                model_name = params.get('model', {}).get('name')

                if model_name:
                    if model_name not in model_stats:
                        model_stats[model_name] = {
                            'count': 0,
                            'duration_count': 0,
                            'total_duration': 0.0,
                            'min_duration': float('inf'),
                            'max_duration': 0.0
                        }

                    model_stats[model_name]['count'] += 1

                    # Only include images with a valid, positive duration in time-based calculations.
                    if duration is not None and duration > 0:
                        model_stats[model_name]['duration_count'] += 1
                        model_stats[model_name]['total_duration'] += duration
                        model_stats[model_name]['min_duration'] = min(model_stats[model_name]['min_duration'], duration)
                        model_stats[model_name]['max_duration'] = max(model_stats[model_name]['max_duration'], duration)

        for entry in all_history:
            for image_list_key in ['original_images', 'enhanced.images'] + [f'variations.{k}.images' for k in entry.get('variations', {})]:
                parts = image_list_key.split('.')
                data = entry
                for part in parts: data = data.get(part, {})
                process_images(data if isinstance(data, list) else [])

        final_stats: Dict[str, Dict[str, float]] = {}
        for model_name, stats in model_stats.items():
            count = stats['count']
            duration_count = stats['duration_count']
            avg_duration = (stats['total_duration'] / duration_count) if duration_count > 0 else 0.0
            final_stats[model_name] = {
                'count': count, 
                'avg_duration': avg_duration, 
                'total_duration': stats['total_duration'],
                'min_duration': stats['min_duration'] if stats['min_duration'] != float('inf') else 0.0, 
                'max_duration': stats['max_duration']
            }
        return final_stats

    def clear_avg_gen_times_cache(self):
        """Clears the cached average generation times. Should be called when history is updated with new images."""
        self._avg_gen_times_cache = None

    def get_lora_stats(self) -> Dict[str, int]:
        """Calculates usage counts per LoRA from history."""
        all_history = self.get_all_history_across_workflows()
        lora_counts: Dict[str, int] = {}

        def process_images(images: List[Dict[str, Any]]):
            if not images: return
            for img in images:
                params = img.get('generation_params', {})
                if not params: continue

                loras = params.get('loras', [])
                if not loras: continue

                for lora_info in loras:
                    lora_name = lora_info.get('lora_object', {}).get('name')
                    if lora_name:
                        lora_counts[lora_name] = lora_counts.get(lora_name, 0) + 1

        for entry in all_history:
            for image_list_key in ['original_images', 'enhanced.images'] + [f'variations.{k}.images' for k in entry.get('variations', {})]:
                parts = image_list_key.split('.')
                data = entry
                for part in parts: data = data.get(part, {})
                process_images(data if isinstance(data, list) else [])

        return lora_counts

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
        """Get a sorted list of available templates from the cache."""
        # This is designed to be called *after* initialize() or list_templates()
        # has populated the cache.
        return sorted(list(self.template_engine.templates.keys()), key=str.lower)

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

    def get_template_usage_map(self) -> Dict[str, List[str]]:
        """
        Builds a map where each key is a wildcard name and the value is a list
        of template files that use that wildcard, either directly or indirectly.
        Uses a cache to avoid re-computation on subsequent calls.
        """
        if hasattr(self, '_template_usage_map_cache') and self._template_usage_map_cache is not None:
            return self._template_usage_map_cache

        from collections import defaultdict
        dependency_graph = self.get_wildcard_dependency_graph()
        template_usage_map = defaultdict(list)

        # 1. Find direct template usages (root wildcards for each template)
        template_to_roots = defaultdict(set)
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
                        # Use the engine's loader to ensure consistency
                        content = self.template_engine.load_template(template_file, template_dir)
                        found = re.findall(r'__([a-zA-Z0-9_.\\s-]+?)__', content)
                        for wc in found:
                            if wc in dependency_graph: # Only consider known wildcards
                                template_to_roots[template_file].add(wc)
                    except Exception as e:
                        print(f"Warning: Could not scan template {os.path.join(template_dir, template_file)}: {e}")

        # 2. For each template, traverse the dependency graph downwards from its roots
        for template, roots in template_to_roots.items():
            queue = list(roots)
            visited_for_template = set()
            while queue:
                wildcard = queue.pop(0)
                if wildcard in visited_for_template:
                    continue
                visited_for_template.add(wildcard)

                # This wildcard is used by the template
                if template not in template_usage_map[wildcard]:
                    template_usage_map[wildcard].append(template)

                # Get children and add them to the queue to be processed
                children = dependency_graph.get(wildcard, {}).get('dependencies', [])
                for child in children:
                    if child not in visited_for_template:
                        queue.append(child)
        
        # Convert defaultdict to dict and sort lists for consistency
        final_map = {k: sorted(v) for k, v in template_usage_map.items()}
        self._template_usage_map_cache = final_map
        return final_map

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
                        if self.verbose:
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
        self._template_usage_map_cache = None

    def archive_template(self, template_file: str) -> None:
        """Archives a template file."""
        self.template_engine.archive_template(template_file, config.get_template_dir())
        self._used_wildcards_cache = None
        self._template_usage_map_cache = None

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
        try:
            self.template_engine.rename_wildcard(old_filename, new_filename, search_order)
            # --- FIX: Force a full reload after renaming to ensure all caches are updated ---
            self.reload_wildcards()
        except Exception as e:
            # Reload even on failure to ensure UI consistency with the file system state.
            self.reload_wildcards()
            raise e

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

    def get_wildcard_data_for_editing(self, filename: str) -> Tuple[Optional[Any], bool]:
        """
        Loads and parses wildcard data for an editor, designed to be called by the GUI.
        This method encapsulates the logic of checking the cache, loading from disk,
        and parsing .txt or .json files, including handling broken JSON.

        Returns a tuple of (data, is_broken).
        - `data`: The parsed dictionary if successful, or the raw string content if broken.
        - `is_broken`: True if the file is a .json file that failed to parse.
        
        Raises FileNotFoundError or other IOErrors on file read issues, which the caller must handle.
        """
        if not filename:
            return None, False

        basename, ext = os.path.splitext(filename)
        
        # Priority 1: Get from the fast, pre-parsed cache.
        cached_data = self.template_engine.wildcards.get(basename)
        if cached_data:
            return cached_data, False

        # Priority 2: Not in cache, load from disk.
        raw_content = self.load_wildcard_content(filename)

        if ext == '.txt':
            lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
            parsed_data = {
                "description": f"Legacy wildcard from {filename}. Saving will convert to .json.",
                "choices": lines
            }
            return parsed_data, False
        else: # .json
            if not raw_content.strip():
                # Treat empty JSON file as an empty object, not an error.
                return {}, False
            try:
                parsed_data = json.loads(raw_content)
                return parsed_data, False
            except json.JSONDecodeError:
                # It's a broken JSON file. Return the raw content for the GUI to display.
                return raw_content, True

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
                if self._save_refactored_wildcard(wc_name, modified_data):
                    modified_files_count += 1
        
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
                if self._save_refactored_wildcard(wc_name, modified_data):
                    modified_files_count += 1

        return modified_files_count
    
    def _save_refactored_wildcard(self, wc_name: str, modified_data: Dict[str, Any]) -> bool:
        """
        Helper to find the correct path for a wildcard and save its modified data.
        Returns True on success, False on failure.
        """
        try:
            filename_to_save = f"{wc_name}.json"
            save_dir = None
            # --- FIX: Use the correct search order to find the file's true location ---
            all_possible_dirs = self._get_wildcard_search_order()
            for directory in all_possible_dirs:
                if os.path.exists(os.path.join(directory, filename_to_save)):
                    save_dir = directory
                    break
            
            if save_dir:
                self.template_engine.save_wildcard_content(filename_to_save, json.dumps(modified_data, indent=2), save_dir)
                # Update the cache with the modified data
                if self.all_wildcards_cache:
                    self.all_wildcards_cache[wc_name] = modified_data
                return True
            else:
                print(f"Warning: Could not find original path for wildcard '{wc_name}' during refactor. Skipping save.")
                return False
        except Exception as e:
            print(f"Error saving refactored wildcard '{wc_name}': {e}")
            return False

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

    def get_system_prompt_files(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Get a structured dictionary of available system prompt files, categorized.
        Returns a dictionary where keys are categories and values are lists of file info dicts.
        """
        files_by_category = {
            "Enhancement & Variations": [],
            "AI Tasks": [],
            "Negative Prompts": []
        }
        
        # --- Enhancement & Variations ---
        system_prompt_dir = config.get_system_prompt_dir()
        variations_dir = config.get_variations_dir()

        # Add the main enhancement file
        enhancement_file = 'enhancement.txt'
        if os.path.exists(os.path.join(system_prompt_dir, enhancement_file)):
            files_by_category["Enhancement & Variations"].append({
                'display_name': 'Enhancement',
                'relative_path': enhancement_file
            })

        # Add variation files, prefixing them to distinguish from top-level files
        if os.path.exists(variations_dir):
            for filename in sorted(os.listdir(variations_dir)):
                if filename.endswith('.json'):
                    try:
                        full_path = os.path.join(variations_dir, filename)
                        with open(full_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            name = data.get('name', os.path.splitext(filename)[0])
                            display_name = f"{name} (Variation)"
                            files_by_category["Enhancement & Variations"].append({
                                'display_name': display_name,
                                'relative_path': os.path.join('variations', filename)
                            })
                    except Exception:
                        display_name = f"{os.path.splitext(filename)[0]} (Variation)"
                        files_by_category["Enhancement & Variations"].append({
                            'display_name': display_name,
                            'relative_path': os.path.join('variations', filename)
                        })
        
        # --- AI Tasks ---
        ai_task_dir = os.path.join(config.SYSTEM_PROMPT_BASE_DIR, 'ai_tasks')
        if os.path.exists(ai_task_dir):
            for filename in sorted(os.listdir(ai_task_dir)):
                if filename.endswith('.txt'):
                    # Create a more user-friendly display name
                    display_name = filename.replace('.txt', '').replace('_', ' ').title()
                    files_by_category["AI Tasks"].append({
                        'display_name': display_name,
                        'relative_path': os.path.join('ai_tasks', filename)
                    })

        # --- Negative Prompts ---
        neg_prompts_dir = os.path.join(config.get_system_prompt_dir(), 'negative_prompts')
        if os.path.exists(neg_prompts_dir):
            for filename in sorted(os.listdir(neg_prompts_dir)):
                if filename.endswith('.txt'):
                    key = os.path.splitext(filename)[0]
                    display_name = key.replace('_', ' ').title()
                    
                    # --- NEW: Add default indicator ---
                    if key == config.DEFAULT_NEGATIVE_PROMPT_KEY:
                        display_name += " (Default)"

                    files_by_category["Negative Prompts"].append({
                        'display_name': display_name,
                        'relative_path': os.path.join('negative_prompts', filename)
                    })

        return files_by_category

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

    def get_available_negative_prompts(self) -> List[Dict[str, str]]:
        """Scans for and loads all available negative prompt JSON files."""
        neg_prompts_dir = os.path.join(config.get_system_prompt_dir(), 'negative_prompts')
        if not os.path.exists(neg_prompts_dir):
            return []

        prompts = []
        for filename in sorted(os.listdir(neg_prompts_dir)):
            if filename.endswith('.txt'):
                try:
                    filepath = os.path.join(neg_prompts_dir, filename)
                    with open(filepath, 'r', encoding='utf-8') as f:
                        key = os.path.splitext(filename)[0]
                        prompts.append({
                            'key': key,
                            'name': key.replace('_', ' ').title(),
                            'prompt': f.read().strip()
                        })
                except IOError as e:
                    print(f"Warning: Could not load or parse negative prompt file {filename}: {e}")
        return prompts

    def clear_default_negative_prompt_cache(self):
        """Clears the cached default negative prompt text."""
        self._default_negative_prompt_cache = None

    def get_default_negative_prompt_text(self) -> str:
        """Gets the prompt text from the user-defined default negative prompt preset, with caching."""
        if self._default_negative_prompt_cache is not None:
            return self._default_negative_prompt_cache

        available_prompts = self.get_available_negative_prompts()
        if not available_prompts:
            self._default_negative_prompt_cache = ""
            return ""

        default_key = config.DEFAULT_NEGATIVE_PROMPT_KEY
        
        for p in available_prompts:
            if p.get('key') == default_key:
                self._default_negative_prompt_cache = p.get('prompt', '')
                return self._default_negative_prompt_cache
        
        self._default_negative_prompt_cache = available_prompts[0].get('prompt', '')
        return self._default_negative_prompt_cache

    def load_system_prompt_content(self, filename: str) -> str:
        """Load the content of a system prompt file."""
        # The filename can be 'enhancement.txt', 'variations/cinematic.json', or 'ai_tasks/some_task.txt'
        base_dir = config.SYSTEM_PROMPT_BASE_DIR
        if filename.startswith('ai_tasks/'):
            filepath = os.path.join(base_dir, filename)
        else: # Enhancement or variation, which are workflow-dependent
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
        base_dir = config.SYSTEM_PROMPT_BASE_DIR
        if filename.startswith('ai_tasks/'):
            filepath = os.path.join(base_dir, filename)
        else: # Enhancement or variation, which are workflow-dependent
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
        if filename.startswith('ai_tasks/'):
            basename = os.path.basename(filename)
            for key, data in DEFAULT_AI_TASK_PROMPTS.items():
                if data['filename'] == basename:
                    return data['content']
        elif filename.endswith('.txt'):
            key = filename.replace('.txt', '')
            if key == 'enhancement':
                return DEFAULT_SFW_ENHANCEMENT_INSTRUCTION if config.workflow == 'sfw' else DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION
        elif filename.startswith('variations/'):
            # Filename is like 'variations/cinematic.json'
            key = os.path.basename(filename).replace('.json', '')
            defaults = DEFAULT_SFW_VARIATIONS if config.workflow == 'sfw' else DEFAULT_NSFW_VARIATIONS
            return defaults.get(key, {}).get('prompt', '')
        elif filename.startswith('negative_prompts/'):
            key = os.path.basename(filename).replace('.txt', '')
            defaults = DEFAULT_SFW_NEGATIVE_PROMPTS if config.workflow == 'sfw' else DEFAULT_NSFW_NEGATIVE_PROMPTS
            return defaults.get(key, '')
        
        return ""

    def archive_system_prompt(self, filename: str) -> None:
        """Archives a system prompt file."""
        base_dir = config.SYSTEM_PROMPT_BASE_DIR
        if filename.startswith('ai_tasks/'):
            source_path = os.path.join(base_dir, filename)
        else:
            source_path = os.path.join(config.get_system_prompt_dir(), filename)
        
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"System prompt file not found: {source_path}")

        # The archive directory should be inside the file's own directory.
        # e.g., .../sfw/archive/enhancement.txt or .../sfw/variations/archive/cinematic.json
        source_dir = os.path.dirname(source_path)
        archive_dir = os.path.join(source_dir, 'archive')
        dest_path = os.path.join(archive_dir, os.path.basename(filename))

        try:
            os.makedirs(archive_dir, exist_ok=True)
            os.rename(source_path, dest_path)
        except OSError as e:
            raise Exception(f"Error archiving system prompt {filename}: {e}")

    def rename_system_prompt(self, old_filename: str, new_filename: str) -> None:
        """Renames a system prompt file."""
        base_dir = config.SYSTEM_PROMPT_BASE_DIR
        if old_filename.startswith('ai_tasks/'):
            old_path = os.path.join(base_dir, old_filename)
        else:
            old_path = os.path.join(config.get_system_prompt_dir(), old_filename)

        
        if not os.path.exists(old_path):
            raise FileNotFoundError(f"System prompt file not found: {old_path}")

        # New path is in the same directory as the old one.
        source_dir = os.path.dirname(old_path)
        new_path = os.path.join(source_dir, new_filename)

        if os.path.exists(new_path):
            raise FileExistsError(f"A file named '{new_filename}' already exists.")

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            raise Exception(f"Error renaming system prompt from '{old_filename}' to '{new_filename}': {e}")

    def create_system_prompt(self, filename: str, prompt_type: str, content_data: Optional[Dict[str, Any]] = None) -> None:
        """
        Creates a new system prompt file with default or provided content.
        `prompt_type` can be 'enhancement', 'variation', or 'negative_prompt'.
        `content_data` is a dictionary to be written as JSON content.
        """
        if prompt_type == 'ai_task':
            save_dir = os.path.join(config.SYSTEM_PROMPT_BASE_DIR, 'ai_tasks')
            if not filename.endswith('.txt'): filename += '.txt'
            content_str = "This is a new AI task prompt. Edit its content here."
        elif prompt_type == 'negative_prompt':
            base_dir = config.get_system_prompt_dir()
            save_dir = os.path.join(base_dir, 'negative_prompts')
            if not filename.endswith('.txt'): filename += '.txt'
            if content_data and 'prompt' in content_data:
                content_str = content_data['prompt']
            else:
                content_str = "new negative prompt keywords"
        else: # enhancement or variation
            base_dir = config.get_system_prompt_dir()
            if prompt_type == 'variation':
                save_dir = os.path.join(base_dir, 'variations')
                if not filename.endswith('.json'): filename += '.json'
                basename, _ = os.path.splitext(filename)
                content = {"name": basename.replace('_', ' ').title(), "description": f"A new custom variation: {basename}", "prompt": "You are a helpful AI assistant. The user's prompt is below.\n\n"}
                content_str = json.dumps(content, indent=2)
            elif prompt_type == 'enhancement':
                save_dir = base_dir
                if not filename.endswith('.txt'): filename += '.txt'
                content_str = "You are a helpful AI assistant. Enhance the user's prompt."
            else: raise ValueError(f"Invalid prompt_type: {prompt_type}")

        filepath = os.path.join(save_dir, filename)
        if os.path.exists(filepath): raise FileExistsError(f"A system prompt named '{os.path.basename(filename)}' already exists.")
        try:
            os.makedirs(save_dir, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f: f.write(content_str)
        except OSError as e: raise Exception(f"Error creating system prompt file {filename}: {e}")

    def load_ai_task_prompt(self, key: str) -> str:
        """Loads a specific AI task prompt from its file."""
        if key not in DEFAULT_AI_TASK_PROMPTS:
            raise ValueError(f"Unknown AI task prompt key: {key}")

        filename = DEFAULT_AI_TASK_PROMPTS[key]['filename']
        filepath = os.path.join(config.SYSTEM_PROMPT_BASE_DIR, 'ai_tasks', filename)

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except (FileNotFoundError, IOError):
            print(f"Warning: AI task prompt file not found: {filepath}. Using default content.")
            return DEFAULT_AI_TASK_PROMPTS[key]['content']

    def chat_with_model(self, model: str, messages: List[Dict[str, str]], timeout: Optional[int] = None, temperature: Optional[float] = None, top_p: Optional[float] = None) -> str:
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
            raw_response = self.ollama_client.chat(model, messages, timeout=timeout, temperature=temperature, top_p=top_p)
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

        prompt_template = self.load_ai_task_prompt('brainstorm_template')
        prompt = prompt_template.format(
            concept=concept,
            workflow_context=workflow_context,
            wildcard_sample_str=wildcard_sample_str
        )
        # Use chat_with_model for better instruction following on complex prompts
        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages, timeout=config.BRAINSTORM_TIMEOUT)
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
        selected_wildcards_str = self.chat_with_model(model, planner_messages, timeout=config.BRAINSTORM_TIMEOUT)
        
        # Parse the comma-separated list of wildcard names
        selected_wildcard_names = [w.strip().replace('__', '') for w in selected_wildcards_str.split(',') if w.strip()]
        
        if not selected_wildcard_names:
            raise Exception("The AI planner did not select any wildcards. Please try a different theme.")

        # --- Step 2: Use the selected wildcards to generate the final template ---
        self._update_status("brainstorm_template_step", step=2, total_steps=2, message="Generating template...")
        
        workflow_context = self._get_workflow_context()
        
        # Build a rich sample string using ONLY the selected wildcards
        rich_wildcard_sample_str = self._get_rich_wildcard_sample_str(wildcard_names=selected_wildcard_names)

        generator_prompt_template = self.load_ai_task_prompt('generate_template_from_wildcards')
        generator_prompt = generator_prompt_template.format(
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
        prompt = DEFAULT_AI_REWRITE_TEXT_PROMPT.format(
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
                linked_wildcard_addition_template = self.load_ai_task_prompt('brainstorm_linked_wildcard_addition')
                linked_wildcard_instruction = linked_wildcard_addition_template.format(
                    topic=topic,
                    supporting_basename=supporting_basename
                )

            workflow_context = self._get_workflow_context()
            wildcard_name_from_topic = topic.replace(' ', '_')
            wildcard_sample_str = self._get_rich_wildcard_sample_str(count=10)

            # --- Build the final prompt ---
            prompt_template = self.load_ai_task_prompt('brainstorm_wildcard')
            prompt = prompt_template.format(
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
            raw_response = self.chat_with_model(model, messages, timeout=config.BRAINSTORM_TIMEOUT)
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

    def ai_generate_linked_wildcards(self, primary_topic: str, supporting_topic: str, model: str) -> Dict[str, str]:
        """Generates content for two linked wildcards."""
        # Step 1: Generate the supporting wildcard. It has no special context.
        self._update_status("brainstorm_template_step", step=1, total_steps=2, message=f"Generating supporting wildcard: {supporting_topic}...")
        supporting_content_str = self.generate_wildcard_for_brainstorming(model, supporting_topic)

        # Step 2: Generate the primary wildcard, telling it to include the supporting one.
        self._update_status("brainstorm_template_step", step=2, total_steps=2, message=f"Generating primary wildcard: {primary_topic}...")
        supporting_filename = f"{supporting_topic.replace(' ', '_')}.json"
        primary_metadata = {'supporting_wildcard_to_include': supporting_filename}
        primary_content_str = self.generate_wildcard_for_brainstorming(model, primary_topic, metadata=primary_metadata)

        return {
            'primary_topic': primary_topic,
            'supporting_topic': supporting_topic,
            'primary_content': primary_content_str,
            'supporting_content': supporting_content_str
        }

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
        prompt = DEFAULT_AI_FIX_GRAMMAR_PROMPT.format(wildcard_content=wildcard_content)
        
        # Use chat for better instruction following
        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages, timeout=config.BRAINSTORM_TIMEOUT)
        
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
        raw_response = self.chat_with_model(model, messages, timeout=config.BRAINSTORM_TIMEOUT)
        
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
            ai_data = json.loads(json_str)

            # --- NEW: Robustly handle cases where the AI only returns one file ---
            # If the AI returns a file, use its content. If not, use the original.
            final_primary_content = ai_data.get(primary_filename)
            if final_primary_content is None:
                final_primary_content = json.loads(primary_content) # Use original if AI omitted it

            final_supporting_content = ai_data.get(supporting_filename)
            if final_supporting_content is None:
                final_supporting_content = json.loads(supporting_content) # Use original if AI omitted it

            return {
                primary_filename: final_primary_content,
                supporting_filename: final_supporting_content
            }
        except (json.JSONDecodeError) as e:
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
        raw_response = self.chat_with_model(model, messages, timeout=config.BRAINSTORM_TIMEOUT)
        # This prompt should return a single JSON object for the primary file.
        return self.ollama_client.parse_json_object_from_response(raw_response, primary_filename)

    def ai_check_wildcard_compatibility(self, file1_filename: str, file1_content: str, file2_filename: str, file2_content: str, model: str) -> Dict[str, str]:
        """Uses a single-step AI process to refactor and make two wildcard files grammatically compatible by modifying both."""
        self._update_status("compatibility_check_step", step=1, total_steps=1, message="Refactoring and fixing grammar...")

        try:
            file1_data = json.loads(file1_content)
            file2_data = json.loads(file2_content)
        except json.JSONDecodeError as e:
            raise Exception(f"Could not parse one of the wildcard files as JSON: {e}")

        file1_description = file1_data.get('description', 'No description provided.')
        file2_description = file2_data.get('description', 'No description provided.')

        prompt = DEFAULT_AI_CHECK_COMPATIBILITY_PROMPT.format(
            file1_filename=file1_filename,
            file1_content=file1_content,
            file1_description=file1_description,
            file2_filename=file2_filename,
            file2_content=file2_content,
            file2_description=file2_description
        )

        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages, timeout=config.BRAINSTORM_TIMEOUT)
        
        # --- Custom Parsing Logic for this specific task ---
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
            ai_data = json.loads(json_str)
            # Use the robust parsing from the previous fix to handle cases where the AI omits a file.
            final_file1_content = ai_data.get(file1_filename, json.loads(file1_content))
            final_file2_content = ai_data.get(file2_filename, json.loads(file2_content))

            def process_file_data(content: Any) -> str:
                if 'choices' in content and isinstance(content.get('choices'), list):
                    content['choices'] = sanitize_wildcard_choices(content['choices'])
                return json.dumps(content, indent=2)

            return {
                file1_filename: process_file_data(final_file1_content),
                file2_filename: process_file_data(final_file2_content)
            }
        except (json.JSONDecodeError, Exception) as e:
            raise Exception(f"AI failed to return valid refactored JSON for both files. Error: {e}\nResponse: {json_str[:500]}")

    def process_enhancement_batch(self, 
                                prompts: List[str], 
                                model: str,
                                selected_variations: Optional[List[str]] = None,
                                cancellation_event: Optional[threading.Event] = None, 
                                template_name: Optional[str] = None,
                                result_callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """Process a batch of prompts for enhancement."""
        results = []
        total_prompts = len(prompts)
        
        # --- FIX: Prioritize the passed callback, then fall back to the instance's callback ---
        final_result_callback = result_callback if result_callback is not None else self.result_callback
        
        enhancement_instruction = self.load_system_prompt_content('enhancement.txt')
        
        # Create a new list of valid, selected variations to avoid modifying the original argument
        available_variations = {v['key']: v for v in self.get_available_variations()}
        valid_selected_variations = [v for v in (selected_variations or []) if v in available_variations]
        
        for i, prompt in enumerate(prompts):
            if cancellation_event and cancellation_event.is_set():
                self._update_status("batch_cancelled")
                break

            # Enhance the prompt
            self._update_status('enhancement_start', prompt_num=i+1, total_prompts=total_prompts)
            enhanced = self.ollama_client.enhance_prompt(enhancement_instruction + prompt, model)

            # Send back the main enhancement result immediately
            if final_result_callback:
                final_result_callback('enhanced', {'prompt': enhanced, 'ollama_model': model})

            result = {
                'original': prompt,
                'enhanced': {'prompt': enhanced, 'ollama_model': model},
                'variations': {},
                'status': 'enhanced',
                'template_name': template_name,
            }
            
            # Create variations if requested
            if valid_selected_variations:
                for var_type in valid_selected_variations:
                    if cancellation_event and cancellation_event.is_set():
                        break # break inner loop
                    variation_instruction = available_variations[var_type]['prompt']
                    self._update_status('variation_start', var_type=var_type, prompt_num=i+1, total_prompts=total_prompts)
                    var_prompt = self.ollama_client.create_single_variation(
                        instruction=variation_instruction,
                        base_prompt=enhanced,
                        model=model,
                        variation_type=var_type,
                        original_prompt_context=prompt # Pass the original prompt for better AI context.
                    )
                    variation_result = {'prompt': var_prompt, 'ollama_model': model}
                    if final_result_callback:
                        final_result_callback(var_type, variation_result)
                    result['variations'][var_type] = variation_result

            results.append(result)
        
        if not (cancellation_event and cancellation_event.is_set()):
            self._update_status("batch_complete")
        
        return results

    def regenerate_enhancement(self, original_prompt: str, model: str) -> str:
        """Regenerates just the main enhancement for a given prompt."""
        instruction = self.load_system_prompt_content('enhancement.txt')
        full_prompt = instruction + original_prompt
        enhanced = self.ollama_client.enhance_prompt(full_prompt, model)
        return enhanced

    def mutate_prompt(self, base_prompt: str, model: str, temperature: Optional[float] = None, top_p: Optional[float] = None) -> str:
        """Uses AI to generate a single, slightly mutated version of a given prompt."""
        instruction = self.load_ai_task_prompt('mutate_prompt')
        full_prompt = instruction.format(original_prompt=base_prompt)

        messages = [
            {'role': 'user', 'content': full_prompt}
        ]
        raw_response = self.chat_with_model(model, messages, timeout=config.VARIATION_TIMEOUT, temperature=temperature, top_p=top_p)
        return raw_response.strip() # The prompt expects only the mutated prompt back

    def _prepare_suggestion_context(self, wildcard_data: Dict[str, Any], current_wildcard_filename: Optional[str]) -> Tuple[str, str, str, str, Optional[str]]:
        """Prepares context variables for the AI suggestion prompt."""
        description = wildcard_data.get('description', 'No description.')
        
        # Get a sample of existing choices to give the AI context
        existing_choices = wildcard_data.get('choices', [])
        sample_size = min(25, len(existing_choices))
        sample_choices_full = self.rng.sample(existing_choices, sample_size) if existing_choices else []
        
        # Extract just the values for a more concise prompt.
        sample_choice_values = [c.get('value') if isinstance(c, dict) else c for c in sample_choices_full]
        sample_choices_str = "\n".join([f"- {val}" for val in sample_choice_values]) if sample_choices_full else "none"
        
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

    def regenerate_variation(self, base_prompt: str, model: str, variation_type: str, original_prompt_context: Optional[str] = None) -> Dict[str, str]:
        """Regenerates a single variation."""
        available_variations = {v['key']: v for v in self.get_available_variations()}
        variation_data = available_variations.get(variation_type)
        if not variation_data:
            raise ValueError(f"Variation '{variation_type}' not found or is invalid.")
        instruction = variation_data['prompt']
        var_prompt = self.ollama_client.create_single_variation(instruction, base_prompt, model, variation_type, original_prompt_context=original_prompt_context)
        return {'prompt': var_prompt}

    def cleanup_prompt_string(self, prompt: str) -> str:
        """Cleans up a generated prompt string to fix common grammatical issues and apply post-processing rules."""
        if not prompt:
            return ""

        # --- Rule 1: Deduplication ---
        # Use a regex to find and replace repeated words (case-insensitive)
        # e.g., "blue blue car" -> "blue car"
        # \b matches a word boundary, (\w+) captures a word, \s+ matches space, \1 is a backreference to the captured word.
        prompt = re.sub(r'\b(\w+)\b(?:\s+\1\b)+', r'\1', prompt, flags=re.IGNORECASE)

        # --- Rule 2: Blacklist conflicting combos ---
        from .default_content import CONFLICTING_KEYWORDS
        
        # Split prompt into a list of parts for easier manipulation
        parts = [part.strip() for part in prompt.split(',') if part.strip()]
        
        for conflict_set in CONFLICTING_KEYWORDS:
            # Find which keywords from the current conflict set are in the prompt
            present_keywords = []
            for part in parts:
                # Check words within each part
                words_in_part = set(re.findall(r'\b\w+\b', part.lower()))
                for keyword in conflict_set:
                    if keyword in words_in_part:
                        present_keywords.append(keyword)
            
            # If more than one keyword from a conflict set is found...
            if len(set(present_keywords)) > 1:
                # Keep the first one found, and create a set of others to remove
                first_found = present_keywords[0]
                keywords_to_remove = set(present_keywords) - {first_found}
                
                # Create a regex pattern to remove the other conflicting keywords
                # e.g., r'\b(anime|cartoon)\b'
                pattern_to_remove = r'\b(' + '|'.join(re.escape(k) for k in keywords_to_remove) + r')\b'
                
                # Filter parts by removing the conflicting keywords
                new_parts = []
                for part in parts:
                    # Remove the keyword, then clean up any resulting empty parts or extra commas
                    cleaned_part = re.sub(pattern_to_remove, '', part, flags=re.IGNORECASE).strip()
                    cleaned_part = re.sub(r'\s*,\s*', ', ', cleaned_part).strip(' ,')
                    if cleaned_part:
                        new_parts.append(cleaned_part)
                parts = new_parts

        # --- Final Cleanup ---
        # Join the potentially modified parts back together.
        return ", ".join(parts)

    def _get_rich_wildcard_sample_str(self, wildcard_names: Optional[List[str]] = None, count: int = 15, samples_per_wildcard: int = 3) -> str:
        """
        Gets a formatted string of wildcard names with example values for AI context.
        If `wildcard_names` is provided, it uses that list. Otherwise, it takes a random sample.
        """
        if self.all_wildcards_cache is None:
            self._load_all_wildcards_into_cache()
        
        if not self.all_wildcards_cache:
            return "none"

        if wildcard_names:
            source_wildcards = {name: self.all_wildcards_cache[name] for name in wildcard_names if name in self.all_wildcards_cache}
        else:
            sample_size = min(count, len(self.all_wildcards_cache))
            sampled_keys = self.rng.sample(list(self.all_wildcards_cache.keys()), sample_size)
            source_wildcards = {key: self.all_wildcards_cache[key] for key in sampled_keys}

        parts = []
        for wc_name, wc_data in sorted(source_wildcards.items()):
            choices = [str(c.get('value') if isinstance(c, dict) else c) for c in wc_data.get('choices', [])]
            sample_choices = self.rng.sample(choices, min(samples_per_wildcard, len(choices))) if choices else []
            parts.append(f"- __{wc_name}__: (e.g., \"{', '.join(sample_choices)}\")")
        return "\n".join(parts) if parts else "none"

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
        prompt_template = self.load_ai_task_prompt('suggest_wildcard_choices')
        return prompt_template.format(
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

    def ai_enhance_template(self, prompt_text: str, model: str) -> str:
        """Uses AI to enhance a template by adding more detail and wildcards."""
        wildcard_list_str = self._get_rich_wildcard_sample_str()
        prompt = self.load_ai_task_prompt('enhance_template').format(
            prompt_text=prompt_text,
            wildcard_list_str=wildcard_list_str
        )
        # Use the one-shot generation method for this task.
        # We expect a single string back (the enhanced template).
        return self.generate_for_brainstorming(model, prompt)

    def ai_enrich_wildcard_choices(self, wildcard_data: Dict[str, Any], model: str, improve_descriptions: bool, add_metadata: bool, current_wildcard_filename: Optional[str] = None) -> List[Any]:
        """Uses AI to enrich choices by improving descriptions and/or adding metadata."""
        if not improve_descriptions and not add_metadata:
            raise ValueError("No enrichment options selected.")

        description = wildcard_data.get('description', 'No description provided.')
        choices = wildcard_data.get('choices', [])
        if not choices:
            raise ValueError("No choices found in the wildcard file to enrich.")

        topic, current_wildcard_name, available_wildcards = self._prepare_refinement_context(current_wildcard_filename)
        available_wildcards_str = ", ".join(available_wildcards) if available_wildcards else "none"
        choices_json = json.dumps(choices, indent=2)

        # Dynamically build the instructions for the AI
        enrichment_instructions = []
        if improve_descriptions:
            enrichment_instructions.append(
                "**Improve Descriptions:** Rewrite the `value` of each choice to be more descriptive and evocative. Add vivid adjectives, sensory details, and specific elements. (e.g., \"a sword\" -> \"a gleaming longsword with a ruby pommel\")."
            )
            enrichment_instructions.append(
                "**ABSOLUTELY NO QUALITY TAGS:** You are forbidden from adding general quality tags like `masterpiece` or `best quality` to the `value`. Your purpose is to enhance the subject, not create a mini-prompt."
            )
        else:
            enrichment_instructions.append(
                "**Do NOT Change Values:** You MUST NOT change the `value` of any choice. The text of each choice must remain exactly the same."
            )

        if add_metadata:
            enrichment_instructions.append(
                "**Add/Update Metadata:** For each choice, add or update `weight`, `tags`, `requires`, and `includes` where they make sense. Not every item needs every property."
            )
            enrichment_instructions.append(
                "**Strict Wildcard Usage:** For `requires` keys and `includes` values, you MUST ONLY use wildcards from the 'Available Wildcards' list. Do NOT invent wildcards for these properties."
            )
            if current_wildcard_name:
                enrichment_instructions.append(f"**No Self-Reference:** The `requires` key MUST NOT refer to the wildcard being edited (`{current_wildcard_name}`).")

        prompt_template = self.load_ai_task_prompt('enrich_wildcard_choices')
        prompt = prompt_template.format(
            description=description,
            topic=topic,
            choices_json=choices_json,
            enrichment_instructions="\n".join(enrichment_instructions),
            available_wildcards_str=available_wildcards_str
        )

        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages, timeout=config.BRAINSTORM_TIMEOUT)
        return self.ollama_client.parse_json_array_from_response(raw_response)

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
        raw_response = self.chat_with_model(model, messages, timeout=config.BRAINSTORM_TIMEOUT)

        # The response should be a JSON array.
        return self.ollama_client.parse_json_array_from_response(raw_response)

    def generate_image_with_invokeai(self, gen_params: Dict[str, Any], prompt: str, save_to_gallery: bool, cancellation_event: Optional[threading.Event] = None) -> Dict[str, Any]:
        """
        A centralized method to generate an image with InvokeAI. It handles all logic
        for applying prefixes, building the graph, and waiting for the result.
        """
        if self.verbose:
            print("\n--- VERBOSE: PromptProcessor.generate_image_with_invokeai ---")
            print(f"Received gen_params:\n{json.dumps(gen_params, indent=2, default=lambda o: '<object>')}")
            print(f"Received prompt: {prompt}")

        # --- Extract parameters from gen_params ---
        negative_prompt = gen_params.get('negative_prompt', '')
        scheduler = gen_params.get('scheduler', 'dpmpp_2m')
        model_object = gen_params.get('model')
        loras = gen_params.get('loras', [])
        
        # --- Apply model-specific prefixes ---
        model_name = model_object.get('name') if model_object else None
        if model_name and model_name in self.model_prefixes:
            prefixes = self.model_prefixes[model_name]
            if self.verbose:
                print(f"Applying model prefixes for '{model_name}': {prefixes}")
            pos_prefix = prefixes.get('positive_prefix', '').strip()
            if pos_prefix:
                prompt = f"{pos_prefix}, {prompt}"
            neg_prefix = prefixes.get('negative_prefix', '').strip()
            if neg_prefix:
                negative_prompt = f"{neg_prefix}, {negative_prompt}" if negative_prompt else neg_prefix
            model_scheduler = prefixes.get('scheduler')
            if model_scheduler:
                if self.verbose:
                    print(f"INFO: Overriding scheduler with model-specific setting for '{model_name}': '{model_scheduler}'")
                scheduler = model_scheduler

        # --- Apply LoRA-specific prefixes ---
        all_pos_lora_prefixes = set()
        all_neg_lora_prefixes = set()
        for lora_info in loras:
            lora_name = lora_info.get('lora_object', {}).get('name')
            if lora_name and lora_name in self.lora_prefixes:
                lora_prefixes = self.lora_prefixes[lora_name]
                if self.verbose:
                    print(f"Applying LoRA prefixes for '{lora_name}': {lora_prefixes}")
                pos_prefix = lora_prefixes.get('positive_prefix', '').strip()
                if pos_prefix:
                    all_pos_lora_prefixes.update([p.strip() for p in pos_prefix.split(',') if p.strip()])
                neg_prefix = lora_prefixes.get('negative_prefix', '').strip()
                if neg_prefix:
                    all_neg_lora_prefixes.update([p.strip() for p in neg_prefix.split(',') if p.strip()])
        
        # Combine and prepend the unique prefixes
        if all_pos_lora_prefixes:
            prompt = f"{', '.join(sorted(list(all_pos_lora_prefixes)))}, {prompt}"

        if all_neg_lora_prefixes:
            combined_neg_prefix = ", ".join(sorted(list(all_neg_lora_prefixes)))
            negative_prompt = f"{combined_neg_prefix}, {negative_prompt}" if negative_prompt else combined_neg_prefix
        # --- FIX: The model object should not be modified here. ---
        # The width and height are passed directly to the enqueue method.

        if self.verbose:
            print(f"Final positive prompt for API: {prompt}")
            print(f"Final negative prompt for API: {negative_prompt}")
            print(f"Final scheduler for API: {scheduler}")

        # --- Enqueue the job ---
        enqueue_args = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "seed": gen_params.get("seed"),
            "model_object": model_object,
            "loras": loras,
            "steps": gen_params.get("steps", 30),
            "cfg_scale": gen_params.get("cfg_scale", 7.5),
            "width": gen_params.get("width", 1024),
            "height": gen_params.get("height", 1024),
            "scheduler": scheduler,
            "cfg_rescale_multiplier": gen_params.get("cfg_rescale_multiplier", 0.0),
            "save_to_gallery": save_to_gallery, "verbose": self.verbose,
            "cancellation_event": cancellation_event
        }
        enqueue_data = self.invokeai_client.enqueue_image_generation(**enqueue_args)
        item_id = enqueue_data.get('item_id') if isinstance(enqueue_data, dict) else None
        if not item_id:
            raise Exception("Failed to get a valid job ID from InvokeAI after enqueueing.")

        # --- FIX: Add the item_id to the gen_params so it can be accessed for cancellation ---
        gen_params['item_id'] = item_id

        # --- Wait for the result ---
        result_data = self.invokeai_client.wait_for_image_generation_result(item_id, save_to_gallery, cancellation_event)

        # --- Construct the final return dictionary ---
        final_gen_params = gen_params.copy()
        # Merge in params that were determined by the client (e.g., VAE)
        final_gen_params.update(enqueue_data.get('generation_params', {}))
        final_gen_params['duration'] = result_data.get('duration')
        result_data['generation_params'] = final_gen_params
        return result_data

    def run_image_generation_jobs(
        self,
        generation_jobs: List[Dict[str, Any]],
        progress_callback: Callable,
        completion_callback: Callable,
        cancellation_event: threading.Event,
        save_to_gallery: bool,
        new_job_queue: Optional[queue.Queue] = None
    ):
        """
        A centralized method to run a list of image generation jobs sequentially,
        grouped by model, and clearing the VRAM cache between model batches.
        This method is designed to be called from a background thread in the GUI.
        """
        if not generation_jobs:
            completion_callback()
            return

        # Group jobs by model name
        jobs_by_model: Dict[str, List[Dict[str, Any]]] = {}
        for job in generation_jobs:
            model_name = job.get('gen_params', {}).get('model', {}).get('name', 'Unknown Model')
            if model_name not in jobs_by_model:
                jobs_by_model[model_name] = []
            jobs_by_model[model_name].append(job)

        model_queue = sorted(list(jobs_by_model.keys()))
        total_models = len(model_queue)

        for i, model_name in enumerate(model_queue):
            if cancellation_event.is_set():
                break

            # Clear VRAM cache before loading the next model, but not for the very first one.
            if i > 0:
                if self.verbose:
                    print(f"INFO: Model batch for '{model_queue[i-1]}' complete. Clearing VRAM cache before loading '{model_name}'.")
                if hasattr(self, 'clear_invokeai_cache_async'):
                    self.clear_invokeai_cache_async()
                    time.sleep(1.5) # Give the server a moment to process the cache clear.
        
            jobs_for_this_model = jobs_by_model[model_name]
            
            # --- FIX: Process jobs from a dynamic list to handle regenerations ---
            job_queue_for_model = list(jobs_for_this_model)
            while job_queue_for_model:
                if cancellation_event.is_set():
                    break
                
                # Check for high-priority jobs (regenerations)
                if new_job_queue and not new_job_queue.empty():
                    try:
                        new_job = new_job_queue.get_nowait()
                        if new_job.get('gen_params', {}).get('model', {}).get('name') == model_name:
                            job_queue_for_model.insert(0, new_job) # Add to the front
                    except queue.Empty: pass
                job = job_queue_for_model.pop(0)
                
                try:
                    result_data = self.generate_image_with_invokeai(
                        gen_params=job['gen_params'],
                        prompt=job['prompt'],
                        save_to_gallery=save_to_gallery,
                        cancellation_event=cancellation_event
                    )
                    progress_callback({'success': True, 'job_id': job['id'], 'result': result_data})
                except Exception as e:
                    progress_callback({'success': False, 'job_id': job['id'], 'error': str(e)})
        completion_callback()

    def save_generated_image(self, image_bytes: bytes, entry_id: str) -> str:
        """Saves image bytes to a dedicated folder for the history entry and returns the relative path."""
        # Create a dedicated directory for this history entry's images
        entry_image_dir_name = entry_id
        # The full path to the specific entry's image folder
        full_entry_image_dir = os.path.join(config.get_history_file_dir(), 'images', entry_image_dir_name)
        os.makedirs(full_entry_image_dir, exist_ok=True)

        image_filename = f"{uuid.uuid4()}.png"
        image_path = os.path.join(full_entry_image_dir, image_filename)

        with open(image_path, 'wb') as f:
            f.write(image_bytes)
            
        # The path stored in history should be relative to the workflow's history directory
        # e.g., 'images/entry_id_uuid/image_uuid.png'
        return os.path.join('images', entry_image_dir_name, image_filename)

    def ai_interrogate_image(self, base64_image: str, model: str, prompt: str) -> str:
        """Pass-through to the Ollama client to generate a prompt from an image."""
        return self.ollama_client.interrogate_image(model, base64_image, prompt)

    def clear_invokeai_cache_async(self):
        """Clears the InvokeAI model cache in a background thread to avoid UI lag."""
        if not self.is_invokeai_connected():
            return

        def task():
            # The empty_model_cache method already handles its own exceptions and printing.
            self.invokeai_client.empty_model_cache()

        thread = threading.Thread(target=task, daemon=True)
        thread.start()

    def ai_breed_prompts(self, parent_prompts: List[str], num_children: int, model: str, temperature: Optional[float] = None, top_p: Optional[float] = None) -> List[str]:
        """Uses AI to 'breed' new prompts from a list of parent prompts."""
        if len(parent_prompts) < 2:
            raise ValueError("Breeding requires at least two parent prompts.")

        parent_prompts_str = ""
        for i, p in enumerate(parent_prompts):
            parent_prompts_str += f"Parent {i+1}: {p}\n"

        prompt_template = self.load_ai_task_prompt('breed_prompts')
        prompt = prompt_template.format(
            parent_prompts_str=parent_prompts_str.strip(),
            num_children=num_children
        )

        # Use chat for better instruction following on complex tasks.
        messages = [{'role': 'user', 'content': prompt}]
        raw_response = self.chat_with_model(model, messages, timeout=config.BRAINSTORM_TIMEOUT, temperature=temperature, top_p=top_p)

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

    def get_all_favorite_images(self) -> List[Dict[str, Any]]:
        """
        Scans the entire history and returns a list of all images marked as favorite.
        """
        all_history = self.get_all_history_across_workflows()
        favorite_images = []

        for entry in all_history:
            history_id = entry.get('id')
            workflow_source = entry.get('workflow_source')

            def process_image_list(images: List[Dict[str, Any]], prompt_type: str, prompt: str):
                if not images:
                    return
                for img_data in images:
                    if img_data.get('is_favorite'):
                        fav_item = {
                            'history_id': history_id,
                            'prompt_type': prompt_type,
                            'prompt': prompt,
                            'image_path': img_data.get('image_path'),
                            'generation_params': img_data.get('generation_params', {}),
                            'workflow_source': workflow_source
                        }
                        favorite_images.append(fav_item)

            # Check original images
            process_image_list(
                entry.get('original_images', []),
                'original',
                entry.get('original_prompt', '')
            )

            # Check enhanced images
            enhanced_data = entry.get('enhanced', {})
            if enhanced_data:
                process_image_list(
                    enhanced_data.get('images', []),
                    'enhanced',
                    enhanced_data.get('prompt', '')
                )

            # Check variation images
            variations_data = entry.get('variations', {})
            if variations_data:
                for var_key, var_data in variations_data.items():
                    # Use the friendly name for the prompt type if available
                    friendly_name = self.available_variations_map.get(var_key, var_key)
                    process_image_list(
                        var_data.get('images', []),
                        friendly_name,
                        var_data.get('prompt', '')
                    )
        
        return favorite_images
