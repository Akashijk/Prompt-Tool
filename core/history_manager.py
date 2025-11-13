"""History file operations for prompt history."""

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
    
    def load_full_history(self) -> List[Dict[str, str]]:
        """Load the entire prompt history from the JSONL file, migrating from CSV if needed."""
        jsonl_path = config.get_history_file()
        history_dir = config.get_history_file_dir() # Get the base dir for the current workflow

        history = []
        needs_rewrite = False # Flag to check if we need to rewrite the history file after migration
        if not os.path.isfile(jsonl_path):
            return history
        try:
            with open(jsonl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)

                        # --- MIGRATION: Ensure entry has a UUID ---
                        if 'id' not in entry:
                            entry['id'] = str(uuid.uuid4())
                            needs_rewrite = True

                        # --- MIGRATION: Old flat image path format to new subfolder format ---
                        def migrate_image_list(images: List[Dict[str, Any]], entry_id: str) -> bool:
                            """Moves images from flat structure to subfolder and updates paths."""
                            list_updated = False
                            if not images: return False
                            for img in images:
                                relative_path = img.get('image_path')
                                # An old-style path is 'uuid.png' (1 part) or 'images/uuid.png' (2 parts).
                                # A new one is 'images/entry_id/uuid.png' (3 parts).
                                path_parts = os.path.normpath(relative_path).split(os.sep)
                                if relative_path and (len(path_parts) == 1 or len(path_parts) == 2):
                                    # Determine the old full path correctly based on the number of parts
                                    if len(path_parts) == 1: # e.g., "uuid.png"
                                        old_full_path = os.path.join(history_dir, relative_path)
                                    else: # len(path_parts) == 2, e.g., "images/uuid.png"
                                        old_full_path = os.path.join(history_dir, relative_path)
                                    
                                    if os.path.exists(old_full_path):
                                        new_relative_dir = os.path.join('images', entry_id)
                                        new_full_dir = os.path.join(history_dir, new_relative_dir)
                                        os.makedirs(new_full_dir, exist_ok=True)
                                        
                                        image_filename = os.path.basename(relative_path)
                                        new_relative_path = os.path.join(new_relative_dir, image_filename)
                                        new_full_path = os.path.join(history_dir, new_relative_path)
                                        
                                        try:
                                            os.rename(old_full_path, new_full_path)
                                            img['image_path'] = new_relative_path
                                            list_updated = True
                                            if self.verbose: print(f"INFO: Migrated image '{old_full_path}' to '{new_full_path}'")
                                        except OSError as e:
                                            print(f"WARNING: Could not migrate image file {relative_path}. Error: {e}")
                            return list_updated

                        if migrate_image_list(entry.get('original_images', []), entry['id']): needs_rewrite = True
                        if 'enhanced' in entry and migrate_image_list(entry.get('enhanced', {}).get('images', []), entry['id']): needs_rewrite = True
                        if 'variations' in entry:
                            for var_data in entry.get('variations', {}).values():
                                if migrate_image_list(var_data.get('images', []), entry['id']): needs_rewrite = True

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
                            needs_rewrite = True
                        
                        # New migration for single image paths to lists
                        if entry.get('original_image_path'):
                            entry['original_images'] = [{
                                'image_path': entry.pop('original_image_path'),
                                'generation_params': entry.pop('original_generation_params', {})
                            }]
                            needs_rewrite = True
                        
                        if entry.get('enhanced', {}).get('image_path'):
                            enhanced_data = entry['enhanced']
                            enhanced_data['images'] = [{
                                'image_path': enhanced_data.pop('image_path'),
                                'generation_params': enhanced_data.pop('generation_params', {})
                            }]
                            needs_rewrite = True

                        for var_data in entry.get('variations', {}).values():
                            if var_data.get('image_path'):
                                var_data['images'] = [{'image_path': var_data.pop('image_path'), 'generation_params': var_data.pop('generation_params', {})}]
                                needs_rewrite = True

                        # --- NEW: Normalize all image paths within the entry to the new format ---
                        def normalize_image_path(img_data: Dict[str, Any], entry_id: str) -> bool:
                            path_updated = False
                            relative_path = img_data.get('image_path')
                            if relative_path:
                                path_parts = os.path.normpath(relative_path).split(os.sep)
                                if len(path_parts) < 3 or path_parts[0] != 'images' or path_parts[1] != entry_id:
                                    # Path is not in the expected 'images/entry_id/filename.png' format
                                    image_filename = os.path.basename(relative_path)
                                    new_relative_path = os.path.join('images', entry_id, image_filename)
                                    img_data['image_path'] = new_relative_path
                                    path_updated = True
                            return path_updated

                        if 'original_images' in entry:
                            for img_data in entry['original_images']:
                                if normalize_image_path(img_data, entry['id']): needs_rewrite = True
                        if 'enhanced' in entry and 'images' in entry['enhanced']:
                            for img_data in entry['enhanced']['images']:
                                if normalize_image_path(img_data, entry['id']): needs_rewrite = True
                        if 'variations' in entry:
                            for var_data in entry['variations'].values():
                                if 'images' in var_data:
                                    for img_data in var_data['images']:
                                        if normalize_image_path(img_data, entry['id']): needs_rewrite = True
                        # --- END NEW ---

                        # --- NEW: Set entry's overall 'favorite' status based on contained images ---
                        entry.setdefault('favorite', False) # Ensure the key exists
                        if self._is_any_image_favorited_in_entry(entry):
                            entry['favorite'] = True

                        history.append(entry)
        except Exception as e:
            print(f"Error loading full history: {e}")
        
        # If any migrations occurred, rewrite the entire history file with the updated data.
        if needs_rewrite:
            if self.verbose: print("INFO: Migrating history file to new format...")
            try:
                with open(jsonl_path, 'w', encoding='utf-8') as f:
                    for entry in history:
                        f.write(json.dumps(entry) + '\n')
            except IOError as e:
                print(f"ERROR: Could not rewrite history file after migration: {e}")
        return history

    def _is_any_image_favorited_in_entry(self, entry: Dict[str, Any]) -> bool:
        """Checks if any image within the given entry is marked as favorite."""
        # Check original images
        for img_data in entry.get('original_images', []):
            if img_data.get('is_favorite'):
                return True
        # Check enhanced images
        for img_data in entry.get('enhanced', {}).get('images', []):
            if img_data.get('is_favorite'):
                return True
        # Check variation images
        for var_data in entry.get('variations', {}).values():
            for img_data in var_data.get('images', []):
                if img_data.get('is_favorite'):
                    return True
        return False

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
                    if self.verbose: print(f"INFO: Deleted orphaned image: {full_path}")
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
            # Attempt to find and delete the image file in various possible locations
            possible_paths = []
            # 1. Current expected format: images/entry_id/filename.png
            possible_paths.append(os.path.join(history_dir, 'images', entry_id_to_delete, os.path.basename(relative_path)))
            # 2. Old format: images/filename.png (if it was moved but not to entry_id subfolder)
            possible_paths.append(os.path.join(history_dir, 'images', os.path.basename(relative_path)))
            # 3. Oldest format: filename.png (directly in history_dir)
            possible_paths.append(os.path.join(history_dir, os.path.basename(relative_path)))
            # 4. The path as it is stored in the entry (might already be correct)
            possible_paths.append(os.path.join(history_dir, relative_path))

            deleted_file = False
            for full_path in possible_paths:
                try:
                    # Only attempt to remove if the file actually exists
                    if os.path.exists(full_path):
                        os.remove(full_path)
                        if self.verbose:
                            if self.verbose: print(f"INFO: Deleted associated image: {full_path}")
                        deleted_file = True
                        break # Stop after first successful deletion
                    # If the file doesn't exist, it's already "deleted" from our perspective
                    elif self.verbose:
                        if self.verbose: print(f"INFO: Image file {full_path} not found, skipping deletion.")
                        deleted_file = True # Consider it deleted if it wasn't there
                        break # Stop trying other paths for this image
                except FileNotFoundError:
                    # This specific error means the file was already gone, which is fine.
                    if self.verbose:
                        if self.verbose: print(f"INFO: Image file {full_path} not found during deletion attempt, already gone.")
                    deleted_file = True # Consider it deleted
                    break # Stop trying other paths for this image
                except Exception as e:
                    # Log other types of errors
                    print(f"WARNING: Could not delete image file {full_path}. Error: {e}")
            
            if not deleted_file:
                print(f"WARNING: Image file for {relative_path} not found or could not be deleted from any known location.")

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
                            if self.verbose: print(f"INFO: Deleted replaced image: {full_path}")
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

    def update_enhanced_prompt_entry(self, entry_id: str, enhanced_data: Dict[str, Any]) -> bool:
        """
        Updates the 'enhanced' and 'variations' fields of an existing history entry.
        This is used when a prompt from history is re-enhanced.
        """
        existing_entry = self.get_entry_by_id(entry_id)
        if not existing_entry:
            print(f"WARNING: Attempted to update non-existent history entry with ID: {entry_id}")
            return False

        # Update the 'enhanced' and 'variations' parts of the existing entry
        # Ensure 'original_prompt' is preserved from the existing entry
        updated_entry = copy.deepcopy(existing_entry)
        updated_entry['enhanced'] = enhanced_data.get('enhanced', {})
        updated_entry['variations'] = enhanced_data.get('variations', {})
        updated_entry['status'] = 're-enhanced' # Mark as re-enhanced
        updated_entry['timestamp'] = datetime.now().isoformat() # Update timestamp

        # The enhanced_data might contain 'original' which is the original prompt text.
        # We should ensure the 'original_prompt' field of the history entry remains consistent.
        if 'original' in enhanced_data and 'original_prompt' not in updated_entry:
            updated_entry['original_prompt'] = enhanced_data['original']
        
        # Call the generic update method
        return self.update_history_entry(existing_entry, updated_entry)

    def get_all_favorite_images(self) -> List[Dict[str, Any]]:
        """
        Loads all history entries from all workflows and extracts information about all favorited images.
        Returns a list of dictionaries, each representing a favorited image.
        """
        favorite_images = []
        original_config_workflow = config.workflow # Store current workflow

        for workflow_name in ['sfw', 'nsfw']: # Iterate through all possible workflows
            config.workflow = workflow_name # Temporarily set workflow
            all_history = self.load_full_history() # Load history for this workflow

            for entry in all_history:
                history_id = entry.get('id')
                if not history_id:
                    continue
                
                # Ensure workflow_source is explicitly set for this entry
                entry['workflow_source'] = workflow_name 

                # Helper to process image lists
                def process_image_list(images: List[Dict[str, Any]], prompt_type: str):
                    for img_data in images:
                        if img_data.get('is_favorite'):
                            # Extract relevant data for the favorite image
                            fav_image_info = {
                                'history_id': history_id,
                                'image_path': img_data.get('image_path'),
                                'prompt': entry.get('original_prompt'), # Default to original prompt
                                'generation_params': img_data.get('generation_params'),
                                'workflow_source': entry.get('workflow_source'), # Use the explicitly set workflow_name
                                'prompt_type': prompt_type, # e.g., 'Original', 'Enhanced', 'Variation'
                                'timestamp': entry.get('timestamp')
                            }
                            # Override prompt if it's from enhanced or variation
                            if prompt_type == 'Enhanced' and entry.get('enhanced', {}).get('prompt'):
                                fav_image_info['prompt'] = entry['enhanced']['prompt']
                            elif prompt_type.startswith('Variation') and entry.get('variations', {}).get(prompt_type.split(': ')[1].lower(), {}).get('prompt'):
                                fav_image_info['prompt'] = entry['variations'][prompt_type.split(': ')[1].lower()]['prompt']
                            
                            favorite_images.append(fav_image_info)

                # Check original images
                process_image_list(entry.get('original_images', []), 'Original')

                # Check enhanced images
                if 'enhanced' in entry:
                    process_image_list(entry['enhanced'].get('images', []), 'Enhanced')

                # Check variation images
                for var_key, var_data in entry.get('variations', {}).items():
                    process_image_list(var_data.get('images', []), f'Variation: {var_key.capitalize()}')
        
        config.workflow = original_config_workflow # Restore original workflow
        return favorite_images

    def update_specific_prompt_part_entry(self, entry_id: str, prompt_part_key: str, new_data: Dict[str, Any]) -> bool:
        """
        Updates a specific part (e.g., 'enhanced', 'variations.some_key') of an existing history entry.
        """
        existing_entry = self.get_entry_by_id(entry_id)
        if not existing_entry:
            print(f"WARNING: Attempted to update non-existent history entry with ID: {entry_id}")
            return False

        updated_entry = copy.deepcopy(existing_entry)
        
        if prompt_part_key == "enhanced":
            updated_entry['enhanced'] = new_data
        elif prompt_part_key.startswith("variations."):
            parts = prompt_part_key.split('.')
            if len(parts) == 2:
                variation_key = parts[1]
                if 'variations' not in updated_entry:
                    updated_entry['variations'] = {}
                updated_entry['variations'][variation_key] = new_data
            else:
                print(f"WARNING: Invalid prompt_part_key format for variations: {prompt_part_key}")
                return False
        elif prompt_part_key == "original_prompt":
            updated_entry['original_prompt'] = new_data.get('prompt', '') # Assuming new_data contains 'prompt'
        else:
            print(f"WARNING: Unknown prompt_part_key for update: {prompt_part_key}")
            return False

        updated_entry['status'] = 're-enhanced' # Mark as re-enhanced
        updated_entry['timestamp'] = datetime.now().isoformat() # Update timestamp

        return self.update_history_entry(existing_entry, updated_entry)