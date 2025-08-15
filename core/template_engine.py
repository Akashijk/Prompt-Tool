"""Template and wildcard handling functionality."""

import os
import json
import re
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple, Callable
from .config import config

@dataclass
class PromptSegment:
    """Represents a piece of a generated prompt."""
    text: str
    wildcard_name: Optional[str] = None
    includes: Optional[Any] = None
    is_from_include: bool = False

class TemplateEngine:
    """Handles template loading and wildcard substitution."""
    
    def __init__(self):
        self.wildcards: Dict[str, Dict] = {} # Will now store the full parsed JSON object
        self.templates: Dict[str, str] = {}
        self.wildcard_files_cache: Optional[List[str]] = None
        self.wildcard_dirs_for_cache: Optional[List[str]] = None
        self.current_seed: Optional[int] = None
        self.rng = random.Random()

    def _load_wildcard_cache(self) -> Dict[str, Any]:
        """Loads the wildcard cache from disk."""
        from .config import WILDCARD_CACHE_FILE
        if not os.path.exists(WILDCARD_CACHE_FILE):
            return {}
        try:
            with open(WILDCARD_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            # If cache is corrupted or unreadable, start fresh.
            return {}

    def _save_wildcard_cache(self, cache_data: Dict[str, Any]):
        """Saves the wildcard cache to disk."""
        from .config import WILDCARD_CACHE_FILE
        try:
            os.makedirs(os.path.dirname(WILDCARD_CACHE_FILE), exist_ok=True)
            with open(WILDCARD_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f) # No indent for smaller file size
        except IOError as e:
            print(f"Warning: Could not save wildcard cache: {e}")

    def clear_wildcard_cache_file(self) -> bool:
        """Deletes the wildcard cache file from disk."""
        from .config import WILDCARD_CACHE_FILE
        if os.path.exists(WILDCARD_CACHE_FILE):
            try:
                os.remove(WILDCARD_CACHE_FILE)
                print("INFO: Wildcard cache file deleted.")
                return True
            except OSError as e:
                print(f"Warning: Could not delete wildcard cache file: {e}")
                return False
        return True # It's already clear if it doesn't exist

    def load_wildcards(self, wildcard_dirs: List[str]) -> Dict[str, Dict]:
        """Load all wildcard files from a list of directories, with later directories overriding earlier ones."""
        self.wildcards = self.get_all_wildcards_data_from_dirs(wildcard_dirs)
        # Invalidate the file list cache whenever we reload wildcards.
        self.wildcard_files_cache = None
        self.wildcard_dirs_for_cache = None
        return self.wildcards
    
    def get_all_wildcards_data_from_dirs(self, wildcard_dirs: List[str]) -> Dict[str, Dict]:
        """
        Loads and returns all wildcard data from a list of directories,
        using a file-based cache to speed up subsequent loads.
        """
        disk_cache = self._load_wildcard_cache()
        wildcards: Dict[str, Dict] = {}
        
        # {basename: {ext: '.json', path: '/path/to/file.json', mtime: 12345.67}}
        found_files: Dict[str, Dict[str, Any]] = {}
        
        # 1. Scan all files on disk to get their paths and modification times.
        for wildcard_dir in wildcard_dirs:
            if not os.path.exists(wildcard_dir):
                continue
            
            for filename in os.listdir(wildcard_dir):
                basename, ext = os.path.splitext(filename)
                if ext in ['.txt', '.json']:
                    path = os.path.join(wildcard_dir, filename)
                    try:
                        mtime = os.path.getmtime(path)
                        
                        # Prioritize .json over .txt. Later dirs override earlier ones.
                        if basename not in found_files or \
                           (ext == '.json' and found_files[basename]['ext'] == '.txt') or \
                           (ext == found_files[basename]['ext']):
                            found_files[basename] = {'ext': ext, 'path': path, 'mtime': mtime}
                    except FileNotFoundError:
                        continue # File might have been deleted during the scan

        # 2. Process files, using cache where possible.
        current_cache = {}
        for basename, file_info in found_files.items():
            path = file_info['path']
            mtime = file_info['mtime']
            
            # Check if a valid, up-to-date entry exists in the cache.
            if path in disk_cache and disk_cache[path].get('mtime') == mtime:
                wildcards[basename] = disk_cache[path]['data']
                current_cache[path] = disk_cache[path] # Keep the valid entry
                continue

            # If not in cache or outdated, load from disk.
            try:
                if file_info['ext'] == '.json':
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                else: # .txt
                    with open(path, 'r', encoding='utf-8') as f:
                        lines = [line.strip() for line in f if line.strip()]
                        data = {"description": f"Legacy wildcard from {os.path.basename(path)}.", "choices": lines}
                
                wildcards[basename] = data
                current_cache[path] = {'mtime': mtime, 'data': data} # Update cache
            except Exception as e:
                print(f"Error loading or parsing wildcard file {path}: {e}")

        # 3. Save the updated cache back to disk.
        self._save_wildcard_cache(current_cache)
        
        return wildcards
    
    def list_templates(self, template_dir: str) -> List[str]:
        """Get a sorted list of available template files and cache their content."""
        if not os.path.exists(template_dir):
            self.templates.clear()
            return []
            
        template_files = sorted([f for f in os.listdir(template_dir) if f.endswith('.txt')], key=str.lower)
        
        # Clear old cache and load new content
        self.templates.clear()
        for filename in template_files:
            try:
                filepath = os.path.join(template_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    self.templates[filename] = f.read()
            except Exception as e:
                print(f"Warning: Could not load and cache template {filename}: {e}")
        
        return template_files
    
    def load_template(self, template_file: str, template_dir: str) -> str:
        """Load template content from file, preferring the cache."""
        if template_file in self.templates:
            return self.templates[template_file]
        
        print(f"INFO: Template '{template_file}' not in cache, loading from disk.")
        filepath = os.path.join(template_dir, template_file)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                self.templates[template_file] = content # Add to cache
                return content
        except Exception as e:
            raise Exception(f"Error loading template {template_file}: {e}")
    
    def list_wildcard_files(self, wildcard_dirs: List[str]) -> List[str]:
        """Get a sorted, unique list of available wildcard files from multiple directories."""
        # Check cache first. If the directories being requested are the same as last time, return the cached list.
        if self.wildcard_files_cache is not None and self.wildcard_dirs_for_cache == wildcard_dirs:
            return self.wildcard_files_cache

        # {basename: {'ext': '.json', 'filename': 'file.json'}}
        canonical_files: Dict[str, Dict[str, str]] = {}

        for wildcard_dir in wildcard_dirs:
            if not os.path.exists(wildcard_dir):
                continue
            for filename in os.listdir(wildcard_dir):
                basename, ext = os.path.splitext(filename)
                if ext not in ['.txt', '.json']:
                    continue

                # If we haven't seen this basename, or if the new file is a .json and the old was a .txt,
                # or if it's the same extension (from a later dir), then update.
                if basename not in canonical_files or (ext == '.json' and canonical_files[basename]['ext'] == '.txt'):
                    canonical_files[basename] = {'ext': ext, 'filename': filename}
                elif ext == canonical_files[basename]['ext']:
                    canonical_files[basename]['filename'] = filename # Same extension, later dir takes precedence
        
        file_list = sorted([data['filename'] for data in canonical_files.values()], key=str.lower)
        
        # Update cache
        self.wildcard_files_cache = file_list
        self.wildcard_dirs_for_cache = wildcard_dirs
        return file_list

    def load_wildcard_content(self, wildcard_file: str, wildcard_dirs: List[str]) -> str:
        """Load raw content of a wildcard file, checking directories in order."""
        for wildcard_dir in wildcard_dirs:
            filepath = os.path.join(wildcard_dir, wildcard_file)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception as e:
                    raise Exception(f"Error loading wildcard file {wildcard_file}: {e}")
        raise FileNotFoundError(f"Wildcard file '{wildcard_file}' not found in any provided directory.")

    def save_wildcard_content(self, wildcard_file: str, content: str, wildcard_dir: str) -> None:
        """Save content to a wildcard file and update the in-memory cache."""
        filepath = os.path.join(wildcard_dir, wildcard_file)
        if not wildcard_file.endswith('.json'):
            raise ValueError("Wildcard file must be a .json file.")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(json.loads(content), f, indent=2) # Prettify the JSON
            self.wildcards[wildcard_file[:-5]] = json.loads(content)
            # Invalidate file list cache on save
            self.wildcard_files_cache = None
        except Exception as e:
            raise Exception(f"Error saving wildcard file {wildcard_file}: {e}")

    def save_template(self, template_file: str, content: str, template_dir: str) -> None:
        """Save template content to a file and update the in-memory cache."""
        filepath = os.path.join(template_dir, template_file)
        try:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            # Update cache
            self.templates[template_file] = content
        except Exception as e:
            raise Exception(f"Error saving template {template_file}: {e}")

    def _archive_file(self, filename: str, search_dirs: List[str], file_type_name: str, post_archive_callback: Optional[Callable] = None) -> None:
        """Generic method to move a file to an 'archive' subdirectory within its source directory."""
        source_path = None
        source_dir = None
        for directory in search_dirs:
            path_to_check = os.path.join(directory, filename)
            if os.path.exists(path_to_check):
                source_path = path_to_check
                source_dir = directory
                break
        
        if not source_path or not source_dir:
            raise FileNotFoundError(f"{file_type_name.capitalize()} file not found in any provided directory: {filename}")

        archive_dir = os.path.join(source_dir, 'archive')
        dest_path = os.path.join(archive_dir, filename)

        try:
            os.makedirs(archive_dir, exist_ok=True)
            os.rename(source_path, dest_path)
            if post_archive_callback:
                post_archive_callback()
        except OSError as e:
            raise Exception(f"Error archiving {file_type_name} {filename}: {e}")

    def archive_template(self, template_file: str, template_dir: str) -> None:
        """Move a template file to an 'archive' subdirectory."""
        def on_success():
            self.templates.pop(template_file, None)

        self._archive_file(template_file, [template_dir], "template", post_archive_callback=on_success)

    def archive_wildcard(self, wildcard_file: str, wildcard_dirs: List[str]) -> None:
        """Move a wildcard file to an 'archive' subdirectory, checking directories in order."""
        def on_success():
            key, _ = os.path.splitext(wildcard_file)
            self.wildcards.pop(key, None)
            # Invalidate file list cache on archive
            self.wildcard_files_cache = None
        
        self._archive_file(wildcard_file, wildcard_dirs, "wildcard", post_archive_callback=on_success)

    def rename_wildcard(self, old_filename: str, new_filename: str, search_dirs: List[str]) -> None:
        """Renames a wildcard file on disk."""
        old_path = None
        source_dir = None
        for directory in search_dirs:
            path_to_check = os.path.join(directory, old_filename)
            if os.path.exists(path_to_check):
                old_path = path_to_check
                source_dir = directory
                break
        
        if not old_path or not source_dir:
            raise FileNotFoundError(f"Wildcard file not found in any provided directory: {old_filename}")

        new_path = os.path.join(source_dir, new_filename)

        if os.path.exists(new_path):
            raise FileExistsError(f"A file named '{new_filename}' already exists in '{source_dir}'.")

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            raise Exception(f"Error renaming file from '{old_path}' to '{new_path}': {e}")

    def get_wildcard_options(self, wildcard_name: str) -> List[str]:
        """Get all sorted options for a given wildcard."""
        wildcard_data = self.wildcards.get(wildcard_name, {})
        choices = wildcard_data.get('choices', [])
        # Extract string value whether the choice is a string or an object
        str_choices = [c['value'] if isinstance(c, dict) else c for c in choices]
        return sorted(str_choices, key=str.lower)

    def find_choice_object_by_value(self, wildcard_name: str, value: str) -> Optional[Any]:
        """Finds a choice object (string or dict) by its value within a wildcard."""
        wildcard_data = self.wildcards.get(wildcard_name)
        if not wildcard_data or 'choices' not in wildcard_data:
            return None

        for choice in wildcard_data['choices']:
            if isinstance(choice, str) and choice == value:
                return choice
            elif isinstance(choice, dict) and choice.get('value') == value:
                return choice
        return None

    def _process_includes(self, choice_obj: Any, wildcard_data: Optional[Dict]) -> str:
        """
        Processes includes and returns formatted string with proper spacing.
        Handles both list-based includes and template strings.
        """
        final_includes = None
        if isinstance(choice_obj, dict) and 'includes' in choice_obj:
            final_includes = choice_obj.get('includes')
        elif wildcard_data and 'includes' in wildcard_data:
            final_includes = wildcard_data.get('includes')
        
        if not final_includes:
            return ""

        if isinstance(final_includes, list):
            # Process list of wildcards
            wildcards = []
            for name in final_includes:
                # Don't wrap if it's already a wildcard reference
                if re.fullmatch(r'__.*__', str(name)):
                    wildcards.append(str(name))
                else:
                    wildcards.append(f"__{name}__")
            # Join with commas for better prompt structure and add spaces for separation.
            return " " + ", ".join(wildcards) + " "
        elif isinstance(final_includes, str):
            # Process template string
            processed = re.sub(r'\[([a-zA-Z0-9_.\s-]+?)\]', r'__\1__', final_includes)
            # Important: Return with single spaces at start/end
            return " " + processed.strip() + " "
        
        return ""

    def _check_requirements(self, choice: Any, context: Optional[Dict[str, Any]]) -> bool:
        """Checks if a given choice object meets the requirements of the current context."""
        if not isinstance(choice, dict):
            return True  # Simple string choices have no requirements.
        
        rules = choice.get('requires')
        if not rules:
            return True  # No 'requires' key means no requirements.
        
        # Pass the context to the rule checker. An empty context is valid.
        return self._check_rules(rules, context or {})

    def generate_prompt(self, template: str, wildcards: Optional[Dict[str, Dict]] = None, seed: Optional[int] = None) -> str:
        """
        Generate a prompt by substituting wildcards in template, respecting context.
        This non-structured version is suitable for CLI or backend use.
        """
        if wildcards is None:
            wildcards = self.wildcards
        
        if seed is None:
            seed = random.randint(0, 2**32 - 1)
        self.current_seed = seed
        self.rng.seed(self.current_seed)
        
        output_prompt = ""
        remaining_template = template
        resolved_context: Dict[str, Any] = {} # Can now hold strings or lists of tags

        # This iterative approach ensures that wildcards are resolved in order,
        # allowing context from earlier wildcards to influence later ones.
        while '__' in remaining_template:
            start_pos = remaining_template.find('__')
            end_pos = remaining_template.find('__', start_pos + 2)

            if end_pos == -1:
                break # No closing __, treat rest as static

            # Add the static text before the wildcard
            output_prompt += remaining_template[:start_pos]

            key = remaining_template[start_pos+2:end_pos]

            # If a wildcard is used multiple times, reuse its resolved value.
            if key in resolved_context:
                choice_val = resolved_context[key]['value']
                output_prompt += choice_val
                remaining_template = remaining_template[end_pos+2:]
            else:
                wildcard_data = self.wildcards.get(key)
                choice_obj = self._get_wildcard_choice_object(key, resolved_context)
                if choice_obj:
                    choice = choice_obj['value'] if isinstance(choice_obj, dict) else choice_obj
                    tags = choice_obj.get('tags') if isinstance(choice_obj, dict) else []
                    output_prompt += choice
                    resolved_context[key] = {'value': choice, 'tags': tags}

                    include_text_to_inject = self._process_includes(choice_obj, wildcard_data)
                    remaining_template = include_text_to_inject + remaining_template[end_pos+2:]
                else:
                    output_prompt += f"__{key}__"
                    remaining_template = remaining_template[end_pos+2:]

        output_prompt += remaining_template
        
        return self.cleanup_prompt_string(output_prompt)

    def _get_wildcard_choice_object(self, key: str, context: Dict[str, Any] = None) -> Optional[Any]:
        """Gets a random choice for a wildcard key, considering context."""
        wildcard_data = self.wildcards.get(key)

        if not wildcard_data or 'choices' not in wildcard_data:
            return None

        choices = wildcard_data['choices']
        if not choices:
            return None

        # Filter choices based on requirements
        valid_choices = [c for c in choices if self._check_requirements(c, context)]
        if not valid_choices:
            return None

        # Calculate total weight
        total_weight = 0
        for choice in valid_choices:
            if isinstance(choice, dict):
                total_weight += choice.get('weight', 1)
            else:
                total_weight += 1

        # Generate random number
        r = self.rng.uniform(0, total_weight)

        # Select choice based on weight
        current_weight = 0
        for choice in valid_choices:
            if isinstance(choice, dict):
                current_weight += choice.get('weight', 1)
            else:
                current_weight += 1
            if r <= current_weight:
                return choice

        return valid_choices[-1]  # Fallback

    def _check_rules(self, rules: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Recursively checks if a set of rules is satisfied by the current context.
        Supports logical operators 'and', 'or', 'not' for complex, nested conditions.
        """
        # Base case: empty rules are always true.
        if not rules:
            return True

        # Handle logical operators for nested conditions
        if 'and' in rules:
            # 'and' must be a list of rule dictionaries
            if not isinstance(rules['and'], list): return False
            return all(self._check_rules(rule, context) for rule in rules['and'])
        
        if 'or' in rules:
            # 'or' must be a list of rule dictionaries
            if not isinstance(rules['or'], list): return False
            return any(self._check_rules(rule, context) for rule in rules['or'])

        if 'not' in rules:
            # 'not' must be a single rule dictionary
            if not isinstance(rules['not'], dict): return False
            return not self._check_rules(rules['not'], context)

        # If no logical operators, it's an implicit 'and' of all key-value pairs.
        return self._check_single_rule_set(rules, context)

    def _check_single_rule_set(self, rules: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Checks a simple set of rules (an implicit AND) against the context."""
        for key, condition in rules.items():
            if key == 'tags':
                # Delegate tag checking to its own robust method
                if not self._check_tag_rules(condition, context):
                    return False
            else:
                # It's a wildcard value check
                if not self._check_value_condition(key, condition, context):
                    return False
        return True

    def _check_value_condition(self, wildcard_name: str, condition: Any, context: Dict[str, Any]) -> bool:
        """Checks if a single wildcard's value in the context matches a given condition."""
        context_value = context.get(wildcard_name, {}).get('value')

        if isinstance(condition, dict):
            # Handle complex conditions like {"not": "value"} or {"any": [...]}
            if 'any' in condition:
                if not isinstance(condition.get('any'), list) or context_value not in condition['any']:
                    return False
            if 'not' in condition:
                not_condition = condition['not']
                if isinstance(not_condition, list):
                    if context_value in not_condition:
                        return False
                elif context_value == not_condition:
                    return False
        elif isinstance(condition, list):
            # "wildcard": ["value1", "value2"] means value must be one of them.
            if context_value not in condition:
                return False
        else:
            # "wildcard": "value" means an exact match is required.
            if context_value != condition:
                return False
            
        return True

    def _check_tag_rules(self, tag_rules: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Checks tag-based rules against the context.
        Supports 'any', 'all', and 'not' conditions.
        """
        if not isinstance(tag_rules, dict):
            return False # Malformed tag rules

        # Collect all tags from all previously resolved items in the context
        all_context_tags = set()
        for item in context.values():
            if isinstance(item, dict) and 'tags' in item:
                all_context_tags.update(item['tags'])

        # Check 'any' condition: at least one of the specified tags must be present.
        if 'any' in tag_rules:
            required_tags = tag_rules['any']
            if not isinstance(required_tags, list) or not any(tag in all_context_tags for tag in required_tags):
                return False
            
        # Check 'all' condition: all of the specified tags must be present.
        if 'all' in tag_rules:
            required_tags = tag_rules['all']
            if not isinstance(required_tags, list) or not all(tag in all_context_tags for tag in required_tags):
                return False
            
        # Check 'not' condition: none of the specified tags should be present.
        if 'not' in tag_rules:
            forbidden_tags = tag_rules['not']
            if isinstance(forbidden_tags, list):
                if any(tag in all_context_tags for tag in forbidden_tags):
                    return False
            elif isinstance(forbidden_tags, str): # Support for a single tag string
                 if forbidden_tags in all_context_tags:
                    return False

        return True

    def _find_or_generate_choice(self, key: str, existing_choices_map: Dict[str, str], resolved_context: Dict[str, Any]) -> Tuple[Optional[Any], Optional[str]]:
        """
        Finds an existing choice or generates a new one for a given wildcard key.
        Returns a tuple of (choice_object, choice_text).
        """
        # Priority 1: Check if this wildcard has already been resolved in this generation pass.
        if key in resolved_context:
            choice_text = resolved_context[key]['value']
            # We need to find the original choice object to get its metadata (like includes) again.
            choice_obj = self.find_choice_object_by_value(key, choice_text)
            return choice_obj, choice_text

        # Priority 2: Check if we are preserving a choice from a previous generation.
        if key in existing_choices_map:
            choice_text = existing_choices_map[key]
            choice_obj = self.find_choice_object_by_value(key, choice_text)
            
            # If a choice object was found, we must validate its 'requires' clause
            # against the current context, as dependencies may have changed.
            if choice_obj:
                is_still_valid = True
                if isinstance(choice_obj, dict) and 'requires' in choice_obj:
                    if not self._check_rules(choice_obj['requires'], resolved_context):
                        is_still_valid = False
                
                if is_still_valid:
                    return choice_obj, choice_text
            # If the choice is no longer valid, fall through to generate a new one.
        
        # Priority 3: Generate a new choice.
        choice_obj = self._get_wildcard_choice_object(key, resolved_context)
        if choice_obj:
            choice_text = choice_obj['value'] if isinstance(choice_obj, dict) else choice_obj
            return choice_obj, choice_text

        return None, None

    def _create_segment_and_update_context(self, key: str, choice_obj: Any, choice_text: str, resolved_context: Dict[str, Any]) -> Tuple[PromptSegment, str]:
        """
        Creates a PromptSegment, updates the context, and returns the segment and any text to inject.
        """
        wildcard_data = self.wildcards.get(key)
        text_to_inject = self._process_includes(choice_obj, wildcard_data)
        
        raw_includes = (choice_obj.get('includes') if isinstance(choice_obj, dict) and 'includes' in choice_obj else wildcard_data.get('includes') if wildcard_data else None)
        tags = choice_obj.get('tags', []) if isinstance(choice_obj, dict) else []
        
        new_segment = PromptSegment(text=choice_text, wildcard_name=key, includes=raw_includes)
        resolved_context[key] = {'value': choice_text, 'tags': tags}
        
        return new_segment, text_to_inject

    def generate_structured_prompt(self, template: str, wildcards: Optional[Dict[str, Dict]] = None, 
                             existing_segments: Optional[List[PromptSegment]] = None, 
                             force_reroll: Optional[List[str]] = None,
                             seed: Optional[int] = None) -> List[PromptSegment]:
        """Generate a prompt as a list of segments for rich interaction."""
        if wildcards is None:
            wildcards = self.wildcards

        # --- Seed Management ---
        if seed is None:
            seed = random.randint(0, 2**32 - 1)
            
        self.current_seed = seed
        self.rng.seed(self.current_seed)

        # --- Tag Mode Detection ---
        is_tag_mode = template.lstrip().startswith("#- mode: tags -#")
        if is_tag_mode:
            # Remove the directive from the template so it's not processed as text
            template = re.sub(r'#-\s*mode:\s*tags\s*-#', '', template).lstrip()
        existing_choices_map = {}
        if existing_segments:
            for segment in existing_segments:
                if segment.wildcard_name:
                    if force_reroll and segment.wildcard_name in force_reroll:
                        continue
                    if segment.wildcard_name not in existing_choices_map:
                        existing_choices_map[segment.wildcard_name] = segment.text

        resolved_context: Dict[str, Any] = {}

        # --- Processing Logic ---
        segments: List[PromptSegment] = []
        # Queue of (template_string, is_from_include_flag)
        processing_queue: List[Tuple[str, bool]] = [(template, False)]

        while processing_queue:
            current_template, is_from_include = processing_queue.pop(0)
            
            match = re.search(r'__([a-zA-Z0-9_.\s-]+?)__', current_template)
            
            if not match:
                # No wildcards left in this string, so it's all static text
                if current_template:
                    segments.append(PromptSegment(text=current_template))
                continue # Move to the next item in the queue

            # --- We found a wildcard ---

            # 1. Add any static text that came before it
            static_prefix = current_template[:match.start()]
            if static_prefix:
                segments.append(PromptSegment(text=static_prefix))

            # 2. Process the wildcard
            key = match.group(1)
            choice_obj, choice_text = self._find_or_generate_choice(key, existing_choices_map, resolved_context)
            
            # 3. Get the rest of the template to be processed later
            rest_of_template = current_template[match.end():]

            if choice_obj:
                new_segment, text_to_inject = self._create_segment_and_update_context(key, choice_obj, choice_text, resolved_context)
                new_segment.is_from_include = is_from_include
                segments.append(new_segment)
                
                # 4. Queue up the rest of the work
                # The rest of the original template goes on the queue first.
                if rest_of_template:
                    processing_queue.insert(0, (rest_of_template, is_from_include))
                
                # The included text goes on the front, to be processed next.
                if text_to_inject:
                    processing_queue.insert(0, (text_to_inject, True))
            else:
                # Wildcard not found, treat it as static text and queue the rest
                segments.append(PromptSegment(text=match.group(0), wildcard_name=key, is_from_include=is_from_include))
                if rest_of_template:
                    processing_queue.insert(0, (rest_of_template, is_from_include))

        return segments

    def cleanup_prompt_string(self, prompt: str) -> str:
        """Cleans up a generated prompt string to fix common grammatical issues."""
        if not prompt:
            return ""

        # Split the prompt by commas, strip whitespace from each part,
        # filter out any empty parts, and then join them back together.
        parts = [part.strip() for part in prompt.split(',')]
        cleaned_parts = [part for part in parts if part]
        return ", ".join(cleaned_parts)
