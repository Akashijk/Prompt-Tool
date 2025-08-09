"""Template and wildcard handling functionality."""

import os
import json
import re
import random
from dataclasses import dataclass
from typing import Dict, List, Optional
from .config import config

@dataclass
class PromptSegment:
    """Represents a piece of a generated prompt."""
    text: str
    wildcard_name: Optional[str] = None

class TemplateEngine:
    """Handles template loading and wildcard substitution."""
    
    def __init__(self):
        self.wildcards: Dict[str, Dict] = {} # Will now store the full parsed JSON object

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

    def archive_template(self, template_file: str, template_dir: str) -> None:
        """Move a template file to an 'archive' subdirectory."""
        try:
            archive_dir = os.path.join(template_dir, 'archive')
            os.makedirs(archive_dir, exist_ok=True)
            dest_path = os.path.join(archive_dir, template_file)
            source_path = os.path.join(template_dir, template_file)

            if not os.path.exists(source_path):
                raise FileNotFoundError(f"Template file not found: {source_path}")
            os.rename(source_path, dest_path)
        except OSError as e:
            raise Exception(f"Error archiving template {template_file}: {e}")

    def archive_wildcard(self, wildcard_file: str, wildcard_dirs: List[str]) -> None:
        """Move a wildcard file to an 'archive' subdirectory, checking directories in order."""
        source_path = None
        source_dir = None
        for wildcard_dir in wildcard_dirs:
            path_to_check = os.path.join(wildcard_dir, wildcard_file)
            if os.path.exists(path_to_check):
                source_path = path_to_check
                source_dir = wildcard_dir
                break
        
        if not source_path or not source_dir:
            raise FileNotFoundError(f"Wildcard file not found in any provided directory: {wildcard_file}")

        archive_dir = os.path.join(source_dir, 'archive')
        dest_path = os.path.join(archive_dir, wildcard_file)

        try:
            os.makedirs(archive_dir, exist_ok=True)
            os.rename(source_path, dest_path)
            # Remove from in-memory cache if it exists
            key, _ = os.path.splitext(wildcard_file)
            self.wildcards.pop(key, None)
        except OSError as e:
            raise Exception(f"Error archiving wildcard {wildcard_file}: {e}")

    def get_wildcard_options(self, wildcard_name: str) -> List[str]:
        """Get all sorted options for a given wildcard."""
        wildcard_data = self.wildcards.get(wildcard_name, {})
        choices = wildcard_data.get('choices', [])
        # Extract string value whether the choice is a string or an object
        str_choices = [c['value'] if isinstance(c, dict) else c for c in choices]
        return sorted(str_choices, key=str.lower)

    def generate_prompt(self, template: str, wildcards: Dict[str, Dict] = None) -> str:
        """Generate a prompt by substituting wildcards in template."""
        if wildcards is None:
            wildcards = self.wildcards
            
        prompt = template
        resolved_context: Dict[str, str] = {}

        # Find all unique wildcards in the template
        wildcard_keys = re.findall(r'__([a-zA-Z0-9_.-]+)__', prompt)
        
        # Create a dictionary to hold the resolved values
        resolved_wildcards = {}
        for key in wildcard_keys:
            if key not in resolved_wildcards: # Resolve each unique key only once
                choice = self._get_wildcard_choice(key, resolved_context)
                if choice:
                    resolved_wildcards[key] = choice
                    resolved_context[key] = choice # Add to context for next choices
        
        for key, value in resolved_wildcards.items():
            prompt = prompt.replace(f"__{key}__", value)
                
        return prompt.strip()

    def _get_wildcard_choice(self, key: str, context: Dict[str, str]) -> Optional[str]:
        """
        Gets a choice from a wildcard, respecting weights and context rules.
        """
        wildcard_data = self.wildcards.get(key)
        if not wildcard_data or 'choices' not in wildcard_data:
            return None

        # 1. Filter choices based on context
        valid_choices = []
        for choice in wildcard_data['choices']:
            if isinstance(choice, dict) and 'requires' in choice:
                rules = choice['requires']
                if all(context.get(req_key) == req_val for req_key, req_val in rules.items()):
                    valid_choices.append(choice)
            else: # It's a simple string or a dict without rules
                valid_choices.append(choice)

        if not valid_choices:
            return f"__NO_VALID_CHOICE_FOR_{key}__"

        # 2. Perform weighted random selection
        weights = [c.get('weight', 1) if isinstance(c, dict) else 1 for c in valid_choices]
        chosen_item = random.choices(valid_choices, weights=weights, k=1)[0]

        # 3. Return the string value
        return chosen_item['value'] if isinstance(chosen_item, dict) else chosen_item

    def generate_structured_prompt(self, template: str, wildcards: Optional[Dict[str, Dict]] = None, existing_segments: Optional[List[PromptSegment]] = None, force_reroll: Optional[List[str]] = None) -> List[PromptSegment]:
        """Generate a prompt as a list of segments for rich interaction."""
        if wildcards is None:
            wildcards = self.wildcards

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
        resolved_context: Dict[str, str] = {}

        while '__' in remaining_template:
            start_pos = remaining_template.find('__')
            end_pos = remaining_template.find('__', start_pos + 2)

            if end_pos == -1:
                break

            if start_pos > 0:
                segments.append(PromptSegment(text=remaining_template[:start_pos]))

            key = remaining_template[start_pos+2:end_pos]
            choice = None
            if key in existing_choices_map:
                choice = existing_choices_map[key]
            else:
                choice = self._get_wildcard_choice(key, resolved_context)
            
            if choice is not None:
                segments.append(PromptSegment(text=choice, wildcard_name=key))
                resolved_context[key] = choice # Add to context for subsequent choices

            remaining_template = remaining_template[end_pos+2:]

        if remaining_template:
            segments.append(PromptSegment(text=remaining_template))

        return segments