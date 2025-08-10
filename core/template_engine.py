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
    includes: Optional[List[str]] = None

class TemplateEngine:
    """Handles template loading and wildcard substitution."""
    
    def __init__(self):
        self.wildcards: Dict[str, Dict] = {} # Will now store the full parsed JSON object
        self.current_seed: Optional[int] = None
        self.seed_locked: bool = False
        self.rng = random.Random()

    def load_wildcards(self, wildcard_dirs: List[str]) -> Dict[str, Dict]:
        """Load all wildcard files from a list of directories, with later directories overriding earlier ones."""
        self.wildcards = {}
        found_files: Dict[str, Dict[str, str]] = {} # {basename: {'.txt': path, '.json': path}}
        
        for wildcard_dir in wildcard_dirs:
            if not os.path.exists(wildcard_dir):
                continue
            
            for filename in os.listdir(wildcard_dir):
                basename, ext = os.path.splitext(filename)
                if ext in ['.txt', '.json']:
                    if basename not in found_files:
                        found_files[basename] = {}
                    # Later dirs override earlier ones for the same extension
                    found_files[basename][ext] = os.path.join(wildcard_dir, filename)

        for basename, paths in found_files.items():
            try:
                if '.json' in paths: # Prefer .json if it exists
                    with open(paths['.json'], 'r', encoding='utf-8') as f:
                        self.wildcards[basename] = json.load(f)
                elif '.txt' in paths: # Fallback to .txt
                    with open(paths['.txt'], 'r', encoding='utf-8') as f:
                        lines = [line.strip() for line in f if line.strip()]
                        # Convert to the standard JSON structure in memory
                        self.wildcards[basename] = {
                            "description": f"Legacy wildcard from {os.path.basename(paths['.txt'])}.",
                            "choices": lines
                        }
            except Exception as e:
                print(f"Error loading or parsing wildcard file for {basename}: {e}")
                        
        return self.wildcards
    
    def list_templates(self, template_dir: str) -> List[str]:
        """Get a sorted list of available template files."""
        if not os.path.exists(template_dir):
            return []
            
        return sorted([f for f in os.listdir(template_dir) if f.endswith('.txt')], key=str.lower)
    
    def load_template(self, template_file: str, template_dir: str) -> str:
        """Load template content from file."""
        filepath = os.path.join(template_dir, template_file)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise Exception(f"Error loading template {template_file}: {e}")
    
    def list_wildcard_files(self, wildcard_dirs: List[str]) -> List[str]:
        """Get a sorted, unique list of available wildcard files from multiple directories."""
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
        return sorted([data['filename'] for data in canonical_files.values()], key=str.lower)

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
        except Exception as e:
            raise Exception(f"Error saving wildcard file {wildcard_file}: {e}")

    def save_template(self, template_file: str, content: str, template_dir: str) -> None:
        """Save template content to a file."""
        filepath = os.path.join(template_dir, template_file)
        try:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
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
        self._archive_file(template_file, [template_dir], "template")

    def archive_wildcard(self, wildcard_file: str, wildcard_dirs: List[str]) -> None:
        """Move a wildcard file to an 'archive' subdirectory, checking directories in order."""
        def on_success():
            key, _ = os.path.splitext(wildcard_file)
            self.wildcards.pop(key, None)
        
        self._archive_file(wildcard_file, wildcard_dirs, "wildcard", post_archive_callback=on_success)

    def get_wildcard_options(self, wildcard_name: str) -> List[str]:
        """Get all sorted options for a given wildcard."""
        wildcard_data = self.wildcards.get(wildcard_name, {})
        choices = wildcard_data.get('choices', [])
        # Extract string value whether the choice is a string or an object
        str_choices = [c['value'] if isinstance(c, dict) else c for c in choices]
        return sorted(str_choices, key=str.lower)

    def generate_prompt(self, template: str, wildcards: Optional[Dict[str, Dict]] = None) -> str:
        """
        Generate a prompt by substituting wildcards in template, respecting context.
        This non-structured version is suitable for CLI or backend use.
        """
        if wildcards is None:
            wildcards = self.wildcards

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
                # The context for a key might be a dict {'value': '...', 'tags': []}
                choice_val = resolved_context[key]['value'] if isinstance(resolved_context[key], dict) else resolved_context[key]
                output_prompt += choice_val
                remaining_template = remaining_template[end_pos+2:]
            else:
                choice_obj = self._get_wildcard_choice_object(key, resolved_context)
                if choice_obj:
                    choice = choice_obj['value'] if isinstance(choice_obj, dict) else choice_obj
                    tags = choice_obj.get('tags') if isinstance(choice_obj, dict) else []
                    output_prompt += choice
                    # Store the value and tags for context matching
                    resolved_context[key] = {'value': choice, 'tags': tags}

                    if isinstance(choice_obj, dict) and 'includes' in choice_obj:
                        include_text = " " + " ".join([f"__{inc}__" for inc in choice_obj['includes']])
                        remaining_template = include_text + remaining_template[end_pos+2:]
                    else:
                        remaining_template = remaining_template[end_pos+2:]
                else:
                    # If no choice is found, keep the placeholder
                    output_prompt += f"__{key}__"
                    remaining_template = remaining_template[end_pos+2:]

        # Add any remaining static text
        output_prompt += remaining_template
        
        return output_prompt.strip()

    def _get_wildcard_choice_object(self, key: str, context: Dict[str, Any]) -> Optional[Any]:
        """
        Gets a choice object (string or dict) from a wildcard, respecting weights and context rules.
        """
        wildcard_data = self.wildcards.get(key)
        if not wildcard_data or 'choices' not in wildcard_data:
            return None

        # 1. Filter choices based on context
        valid_choices = []
        for choice in wildcard_data['choices']:
            if isinstance(choice, dict) and 'requires' in choice:
                if self._check_rules(choice['requires'], context):
                    valid_choices.append(choice)
            else: # It's a simple string or a dict without rules
                valid_choices.append(choice)

        if not valid_choices:
            return None

        # 2. Perform weighted random selection
        weights = [c.get('weight', 1) if isinstance(c, dict) else 1 for c in valid_choices]
        chosen_item = self.rng.choices(valid_choices, weights=weights, k=1)[0]

        return chosen_item

    def _check_rules(self, rules: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Recursively checks if a set of rules is satisfied by the current context."""
        for key, condition in rules.items():
            if key == 'tags':
                # Handle tag-based requirements
                if not self._check_tag_rules(condition, context):
                    return False
            elif isinstance(condition, dict):
                # Composite rule (e.g., {"any": [...]})
                if "any" in condition:
                    if not any(context.get(key, {}).get('value') == val for val in condition["any"]):
                        return False
                if "all" in condition:
                    if not all(context.get(key, {}).get('value') == val for val in condition["all"]):
                        return False
            else:
                # Simple key-value or key-[value] match
                context_value = context.get(key, {}).get('value')
                if isinstance(condition, list):
                    if context_value not in condition:
                        return False
                elif context_value != condition:
                    return False
        return True

    def _check_tag_rules(self, tag_rules: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Checks tag-based rules against the context."""
        # Collect all tags from all previously resolved items in the context
        all_context_tags = set()
        for item in context.values():
            if isinstance(item, dict) and 'tags' in item:
                all_context_tags.update(item['tags'])

        if "any" in tag_rules:
            if not any(tag in all_context_tags for tag in tag_rules["any"]):
                return False
        if "all" in tag_rules:
            if not all(tag in all_context_tags for tag in tag_rules["all"]):
                return False
        return True

    def generate_structured_prompt(self, template: str, wildcards: Optional[Dict[str, Dict]] = None, existing_segments: Optional[List[PromptSegment]] = None, force_reroll: Optional[List[str]] = None) -> List[PromptSegment]:
        """Generate a prompt as a list of segments for rich interaction."""
        if wildcards is None:
            wildcards = self.wildcards

        # If this is a full new generation (not a live update) and the seed is not locked,
        # generate a new random seed to ensure the "Generate" button always produces a new result.
        if not existing_segments and not self.seed_locked:
            self.set_seed()

        # Build a map of existing choices to maintain them across edits
        existing_choices_map = {}
        if existing_segments:
            for segment in existing_segments:
                if segment.wildcard_name:
                    if force_reroll and segment.wildcard_name in force_reroll:
                        continue
                    if segment.wildcard_name not in existing_choices_map:
                        existing_choices_map[segment.wildcard_name] = segment.text

        segments: List[PromptSegment] = []
        remaining_template = template
        resolved_context: Dict[str, Any] = {} # Can now hold strings or lists of tags

        while '__' in remaining_template:
            start_pos = remaining_template.find('__')
            end_pos = remaining_template.find('__', start_pos + 2)

            if end_pos == -1:
                break

            if start_pos > 0:
                segments.append(PromptSegment(text=remaining_template[:start_pos]))

            key = remaining_template[start_pos+2:end_pos]
            if key in existing_choices_map:
                choice_text = existing_choices_map[key]
                # We don't know the tags of a pre-existing choice, so context is limited here.
                segments.append(PromptSegment(text=choice_text, wildcard_name=key))
                resolved_context[key] = {'value': choice_text, 'tags': []}
                remaining_template = remaining_template[end_pos+2:]
            else:
                choice_obj = self._get_wildcard_choice_object(key, resolved_context)
                if choice_obj:
                    choice_text = choice_obj['value'] if isinstance(choice_obj, dict) else choice_obj
                    includes_list = choice_obj.get('includes') if isinstance(choice_obj, dict) else None
                    tags = choice_obj.get('tags') if isinstance(choice_obj, dict) else []
                    segments.append(PromptSegment(text=choice_text, wildcard_name=key, includes=includes_list))
                    resolved_context[key] = {'value': choice_text, 'tags': tags}

                    if isinstance(choice_obj, dict) and 'includes' in choice_obj:
                        include_text = " " + " ".join([f"__{inc}__" for inc in choice_obj['includes']])
                        remaining_template = include_text + remaining_template[end_pos+2:]
                    else:
                        remaining_template = remaining_template[end_pos+2:]
                else:
                    # If no choice is found, keep the placeholder
                    segments.append(PromptSegment(text=f"__{key}__", wildcard_name=key))
                    remaining_template = remaining_template[end_pos+2:]

        if remaining_template:
            segments.append(PromptSegment(text=remaining_template))

        return segments

    def set_seed(self, seed: Optional[int] = None, lock: bool = False) -> int:
        """Set and/or lock the random seed.
        
        Args:
            seed: Specific seed to use. If None, generates random seed.
            lock: Whether to lock this seed for future generations.
        
        Returns:
            The seed being used.
        """
        if seed is not None:
            self.current_seed = seed
        elif not self.seed_locked:
            self.current_seed = self.rng.randint(0, 2**32 - 1)
            
        self.seed_locked = lock
        self.rng.seed(self.current_seed)
        return self.current_seed
    
    def unlock_seed(self):
        """Unlock the seed to allow new random seeds."""
        self.seed_locked = False
        
    def process_template(self, template: str, wildcards: Dict[str, List[str]]) -> Tuple[str, int]:
        """Process template and return result with seed used."""
        if not self.seed_locked:
            self.set_seed()
            
        # ...existing processing code...
        
        return result, self.current_seed