"""Template and wildcard handling functionality."""

import os
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
        self.wildcards: Dict[str, List[str]] = {}
        self.templates: List[str] = []
        
    def load_wildcards(self, wildcard_dirs: List[str]) -> Dict[str, List[str]]:
        """Load all wildcard files from a list of directories, with later directories overriding earlier ones."""
        self.wildcards = {}
        
        for wildcard_dir in wildcard_dirs:
            if not os.path.exists(wildcard_dir):
                continue
            
            for fname in os.listdir(wildcard_dir):
                if fname.endswith('.txt'):
                    key = fname[:-4]
                    filepath = os.path.join(wildcard_dir, fname)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            # This will automatically override if key already exists from a previous dir
                            self.wildcards[key] = [line.strip() for line in f if line.strip()]
                    except Exception as e:
                        print(f"Error loading wildcard file {fname}: {e}")
                        
        return self.wildcards
    
    def list_templates(self, template_dir: str) -> List[str]:
        """Get a sorted list of available template files."""
        if not os.path.exists(template_dir):
            return []
            
        self.templates = sorted([f for f in os.listdir(template_dir) if f.endswith('.txt')], key=str.lower)
        return self.templates
    
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
        all_files = set()
        for wildcard_dir in wildcard_dirs:
            if not os.path.exists(wildcard_dir):
                continue
            for f in os.listdir(wildcard_dir):
                if f.endswith('.txt'):
                    all_files.add(f)
        # Sort case-insensitively for consistent ordering in UI lists
        return sorted(list(all_files), key=str.lower)

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
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            # Update the in-memory wildcard dictionary for live changes
            key = wildcard_file[:-4]
            self.wildcards[key] = [line.strip() for line in content.split('\n') if line.strip()]
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
            key = wildcard_file[:-4]
            self.wildcards.pop(key, None)
        except OSError as e:
            raise Exception(f"Error archiving wildcard {wildcard_file}: {e}")

    def get_wildcard_options(self, wildcard_name: str) -> List[str]:
        """Get all sorted options for a given wildcard."""
        options = self.wildcards.get(wildcard_name, [])
        return sorted(options, key=str.lower)

    def generate_prompt(self, template: str, wildcards: Dict[str, List[str]] = None) -> str:
        """Generate a prompt by substituting wildcards in template."""
        if wildcards is None:
            wildcards = self.wildcards
            
        prompt = template
        while '__' in prompt:
            start = prompt.find('__')
            end = prompt.find('__', start + 2)
            if end == -1:
                break
                
            key = prompt[start+2:end]
            if key in wildcards and wildcards[key]:
                choice = random.choice(wildcards[key])
                prompt = prompt[:start] + choice + prompt[end+2:]
            else:
                # Remove unknown wildcard placeholder
                prompt = prompt[:start] + prompt[end+2:]
                
        return prompt.strip()

    def generate_structured_prompt(self, template: str, wildcards: Optional[Dict[str, List[str]]] = None, existing_segments: Optional[List[PromptSegment]] = None, force_reroll: Optional[List[str]] = None) -> List[PromptSegment]:
        """Generate a prompt as a list of segments for rich interaction."""
        if wildcards is None:
            wildcards = self.wildcards

        # Build a queue of existing choices for each wildcard name to maintain them across edits
        existing_choices = {}
        if existing_segments:
            for segment in existing_segments:
                if segment.wildcard_name:
                    # If this wildcard should be re-rolled, don't add its existing choice to the queue
                    if force_reroll and segment.wildcard_name in force_reroll:
                        continue
                    if segment.wildcard_name not in existing_choices:
                        existing_choices[segment.wildcard_name] = []
                    existing_choices[segment.wildcard_name].append(segment.text)

        segments: List[PromptSegment] = []
        remaining_template = template

        while '__' in remaining_template:
            start_pos = remaining_template.find('__')
            end_pos = remaining_template.find('__', start_pos + 2)

            if end_pos == -1:
                break  # No closing __, treat rest as static

            if start_pos > 0:
                segments.append(PromptSegment(text=remaining_template[:start_pos]))

            key = remaining_template[start_pos+2:end_pos]
            choice = None
            if key in existing_choices and existing_choices[key]:
                choice = existing_choices[key].pop(0)  # Use existing choice
            elif key in wildcards and wildcards[key]:
                choice = random.choice(wildcards[key])
            
            if choice is not None:
                segments.append(PromptSegment(text=choice, wildcard_name=key))

            remaining_template = remaining_template[end_pos+2:]

        if remaining_template:
            segments.append(PromptSegment(text=remaining_template))

        return segments