"""History file operations for prompt history."""

import csv
import os
import json
import tempfile
import uuid
import copy
from datetime import datetime
from typing import Set, Optional, Dict, Any, List
from .config import config

class HistoryManager:
    """Handles history file operations using the JSONL format."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
    
    def _migrate_from_csv(self, csv_path: str, jsonl_path: str):
        """Migrates data from the old CSV format to the new JSONL format."""
        if self.verbose:
            print(f"INFO: Migrating history from {csv_path} to {jsonl_path}...")
        history = []
        try:
            with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    variations = {}
                    for var_type in ['cinematic', 'artistic', 'photorealistic']:
                        if row.get(f'{var_type}_variation'):
                            variations[var_type] = {
                                'prompt': row.get(f'{var_type}_variation', ''),
                                'negative_prompt': '', # Old format didn't have this
                                'sd_model': row.get(f'{var_type}_sd_model')
                            }
                    
                    new_entry = {
                        'id': str(uuid.uuid4()),
                        'original_prompt': row.get('original_prompt'),
                        'status': row.get('status'),
                        'enhanced': {
                            'prompt': row.get('enhanced_prompt', ''),
                            'sd_model': row.get('enhanced_sd_model', '')
                        },
                        'favorite': row.get('favorite') == '1',
                        'variations': variations,
                        'template_name': None  # Old format didn't have this
                    }
                    history.append(new_entry)
            
            with open(jsonl_path, 'w', encoding='utf-8') as jsonl_file:
                for entry in history:
                    jsonl_file.write(json.dumps(entry) + '\n')
            
            # Archive the old CSV file
            archive_dir = os.path.join(os.path.dirname(csv_path), 'archive')
            os.makedirs(archive_dir, exist_ok=True)
            os.rename(csv_path, os.path.join(archive_dir, os.path.basename(csv_path)))
            if self.verbose:
                print("INFO: Migration successful. Old CSV history has been archived.")
            return history
        except Exception as e:
            print(f"ERROR: Failed to migrate history file. Error: {e}")
            return []

    def load_full_history(self) -> List[Dict[str, str]]:
        """Load the entire prompt history from the JSONL file, migrating from CSV if needed."""
        jsonl_path = config.get_history_file()
        
        # Check for and run migration if the new file doesn't exist but the old one does
        csv_path = os.path.join(os.path.dirname(jsonl_path), 'generated_prompts.csv')
        if not os.path.exists(jsonl_path) and os.path.exists(csv_path):
            return self._migrate_from_csv(csv_path, jsonl_path)

        history = []
        if not os.path.isfile(jsonl_path):
            return history
        try:
            with open(jsonl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        # --- MIGRATION LOGIC ---
                        if 'enhanced_prompt' in entry and isinstance(entry['enhanced_prompt'], str):
                            # This is the old format. Convert it.
                            entry['enhanced'] = {
                                'prompt': entry.pop('enhanced_prompt'),
                                'sd_model': entry.pop('enhanced_sd_model', '')
                            }
                            # Move top-level image/params into the new enhanced object
                            if 'image_path' in entry: entry['enhanced']['image_path'] = entry.pop('image_path')
                            if 'generation_params' in entry: entry['enhanced']['generation_params'] = entry.pop('generation_params')
                        
                        # New migration for single image paths to lists
                        if entry.get('original_image_path'):
                            entry['original_images'] = [{
                                'image_path': entry.pop('original_image_path'),
                                'generation_params': entry.pop('original_generation_params', {})
                            }]
                        
                        if entry.get('enhanced', {}).get('image_path'):
                            enhanced_data = entry['enhanced']
                            enhanced_data['images'] = [{
                                'image_path': enhanced_data.pop('image_path'),
                                'generation_params': enhanced_data.pop('generation_params', {})
                            }]

                        for var_data in entry.get('variations', {}).values():
                            if var_data.get('image_path'):
                                var_data['images'] = [{'image_path': var_data.pop('image_path'), 'generation_params': var_data.pop('generation_params', {})}]

                        history.append(entry)
        except Exception as e:
            print(f"Error loading full history: {e}")
        return history

    def _get_all_image_paths_from_entry(self, data: Dict[str, Any]) -> Set[str]:
        """Helper to extract all image paths from a single history entry."""
        paths = set()
        # Check original prompt's images
        for img in data.get('original_images', []):
            if img.get('image_path'): paths.add(img['image_path'])
        # Check enhanced prompt's images
        for img in data.get('enhanced', {}).get('images', []):
            if img.get('image_path'): paths.add(img['image_path'])
        # Check variations' images
        for var_data in data.get('variations', {}).values():
            for img in var_data.get('images', []):
                if img.get('image_path'): paths.add(img['image_path'])
        return paths

    def garbage_collect_orphaned_images(self) -> int:
        """
        Scans the images directory and deletes any image files that are not
        referenced in the history file.
        Returns the number of orphaned files deleted.
        """
        history_dir = config.get_history_file_dir()
        image_dir = os.path.join(history_dir, 'images')

        if not os.path.isdir(image_dir):
            return 0

        try:
            disk_images = {os.path.join('images', f) for f in os.listdir(image_dir) if os.path.isfile(os.path.join(image_dir, f))}
        except OSError:
            return 0

        all_entries = self.load_full_history()
        referenced_images = set()
        for entry in all_entries:
            referenced_images.update(self._get_all_image_paths_from_entry(entry))

        orphaned_files = disk_images - referenced_images
        for relative_path in orphaned_files:
            full_path = os.path.join(history_dir, relative_path)
            try:
                os.remove(full_path)
                if self.verbose:
                    print(f"INFO: Deleted orphaned image: {full_path}")
            except OSError as e:
                print(f"WARNING: Could not delete orphaned image file {relative_path}. Error: {e}")
        
        return len(orphaned_files)

    def prune_missing_image_entries(self) -> int:
        """
        Scans the history file, removes references to missing image files,
        and removes 'generated_only' entries that no longer have any images.
        Returns the number of image references that were pruned.
        """
        filepath = config.get_history_file()
        if not os.path.isfile(filepath):
            return 0

        history_dir = config.get_history_file_dir()
        all_entries = self.load_full_history()
        cleaned_entries = []
        pruned_count = 0

        def get_valid_images(images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            nonlocal pruned_count
            valid_images = []
            for img in images:
                if 'image_path' in img and os.path.exists(os.path.join(history_dir, img['image_path'])):
                    valid_images.append(img)
                else:
                    pruned_count += 1
            return valid_images

        for entry in all_entries:
            cleaned_entry = copy.deepcopy(entry)
            
            if 'original_images' in cleaned_entry:
                cleaned_entry['original_images'] = get_valid_images(cleaned_entry['original_images'])
            if 'enhanced' in cleaned_entry and 'images' in cleaned_entry['enhanced']:
                cleaned_entry['enhanced']['images'] = get_valid_images(cleaned_entry['enhanced']['images'])
            if 'variations' in cleaned_entry:
                for var_key in cleaned_entry['variations']:
                    if 'images' in cleaned_entry['variations'][var_key]:
                        cleaned_entry['variations'][var_key]['images'] = get_valid_images(cleaned_entry['variations'][var_key]['images'])
            
            if cleaned_entry.get('status') == 'generated_only' and not cleaned_entry.get('original_images'):
                continue

            cleaned_entries.append(cleaned_entry)

        with open(filepath, 'w', encoding='utf-8') as f:
            for entry in cleaned_entries:
                f.write(json.dumps(entry) + '\n')
        
        return pruned_count

    def get_entry_by_id(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Finds and returns a single history entry by its unique ID."""
        filepath = config.get_history_file()
        if not os.path.isfile(filepath):
            return None
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip() and f'"{entry_id}"' in line: # Quick check to avoid parsing every line
                        entry = json.loads(line)
                        if entry.get('id') == entry_id:
                            return entry
        except (IOError, json.JSONDecodeError) as e:
            print(f"Error reading history file to find entry {entry_id}: {e}")
        return None

    def delete_history_entry(self, row_to_delete: Dict[str, str]) -> bool:
        """Deletes a specific entry from the history file by matching its unique ID."""
        filepath = config.get_history_file()
        if not os.path.isfile(filepath):
            return False

        entry_id_to_delete = row_to_delete.get('id')
        if not entry_id_to_delete: return False

        # --- Image Deletion Logic ---
        image_paths_to_delete = []
        # Check original prompt
        for img in row_to_delete.get('original_images', []):
            if img.get('image_path'):
                image_paths_to_delete.append(img['image_path'])

        # Check enhanced prompt
        enhanced_data = row_to_delete.get('enhanced', {})
        for img in enhanced_data.get('images', []):
            if img.get('image_path'):
                image_paths_to_delete.append(img['image_path'])
        
        # Check variations
        variations_data = row_to_delete.get('variations', {})
        for var_data in variations_data.values():
            for img in var_data.get('images', []):
                if img.get('image_path'):
                    image_paths_to_delete.append(img['image_path'])

        history_dir = config.get_history_file_dir()
        for relative_path in image_paths_to_delete:
            try:
                full_path = os.path.join(history_dir, relative_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
                    if self.verbose:
                        print(f"INFO: Deleted associated image: {full_path}")
            except Exception as e:
                # Log the error but don't stop the history entry deletion
                print(f"WARNING: Could not delete image file {relative_path}. Error: {e}")

        deleted = False
        temp_filepath = ""
        try:
            with tempfile.NamedTemporaryFile(mode='w', newline='', encoding='utf-8', delete=False, dir=os.path.dirname(filepath)) as temp_file:
                temp_filepath = temp_file.name
                with open(filepath, 'r', encoding='utf-8') as f_in:
                    for line in f_in:
                        entry = json.loads(line)
                        if not deleted and entry.get('id') == entry_id_to_delete:
                            deleted = True
                        else:
                            temp_file.write(line)
            
            if deleted:
                os.replace(temp_filepath, filepath)
            else:
                os.remove(temp_filepath) # No changes were made, so remove the temp file
            return deleted
        except Exception as e:
            print(f"Error deleting history entry: {e}")
            if temp_filepath and os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return False

    def update_history_entry(self, original_row: Dict[str, str], updated_row: Dict[str, str]) -> bool:
        """Updates a specific entry in the history file by matching its unique ID."""
        filepath = config.get_history_file()
        if not os.path.isfile(filepath):
            return False

        entry_id_to_update = original_row.get('id')
        if not entry_id_to_update: return False

        # --- NEW: Always update the timestamp on any modification ---
        updated_row['timestamp'] = datetime.now().isoformat()

        # --- NEW: Image Deletion Logic for Replaced Images ---
        original_paths = self._get_all_image_paths_from_entry(original_row)
        updated_paths = self._get_all_image_paths_from_entry(updated_row)
        paths_to_delete = original_paths - updated_paths

        if paths_to_delete:
            history_dir = config.get_history_file_dir()
            for relative_path in paths_to_delete:
                try:
                    full_path = os.path.join(history_dir, relative_path)
                    if os.path.exists(full_path):
                        os.remove(full_path)
                        if self.verbose:
                            print(f"INFO: Deleted replaced image: {full_path}")
                except Exception as e:
                    print(f"WARNING: Could not delete replaced image file {relative_path}. Error: {e}")

        updated = False
        temp_filepath = ""
        try:
            with tempfile.NamedTemporaryFile(mode='w', newline='', encoding='utf-8', delete=False, dir=os.path.dirname(filepath)) as temp_file:
                temp_filepath = temp_file.name
                with open(filepath, 'r', encoding='utf-8') as f_in:
                    for line in f_in:
                        entry = json.loads(line)
                        if not updated and entry.get('id') == entry_id_to_update:
                            temp_file.write(json.dumps(updated_row) + '\n')
                            updated = True
                        else:
                            temp_file.write(line)
            
            if updated:
                os.replace(temp_filepath, filepath)
            else:
                os.remove(temp_filepath)
            return updated
        except Exception as e:
            print(f"Error updating history entry: {e}")
            if temp_filepath and os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return False

    def save_result(self, **result_data: Any) -> Dict[str, Any]:
        """Save a single result to the JSONL history file."""
        filepath = config.get_history_file()
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # Ensure essential keys exist and handle aliases
        result_data.setdefault('id', str(uuid.uuid4()))
        if 'original' in result_data and 'original_prompt' not in result_data:
            result_data['original_prompt'] = result_data.pop('original')
        result_data.setdefault('original_prompt', '')
        
        result_data.setdefault('status', 'enhanced')
        result_data.setdefault('enhanced', {})
        result_data.setdefault('variations', {})
        result_data.setdefault('favorite', False)
        result_data.setdefault('template_name', None)
        result_data.setdefault('timestamp', datetime.now().isoformat())

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(json.dumps(result_data) + '\n')
            return result_data
        except Exception as e:
            print(f"Error saving to history: {e}")
            return {}