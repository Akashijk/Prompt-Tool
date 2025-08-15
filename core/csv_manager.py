"""CSV file operations for prompt history."""

import csv
import os
import json
import tempfile
import uuid
from typing import Set, Optional, Dict, Any, List
from .config import config

class HistoryManager:
    """Handles history file operations using the JSONL format."""
    
    def __init__(self):
        pass # No filepath state needed; it will be determined on-the-fly.
    
    def _migrate_from_csv(self, csv_path: str, jsonl_path: str):
        """Migrates data from the old CSV format to the new JSONL format."""
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
                        'enhanced_prompt': row.get('enhanced_prompt'),
                        'negative_prompt': '', # Old format didn't have this
                        'enhanced_sd_model': row.get('enhanced_sd_model'),
                        'favorite': row.get('favorite') == '1',
                        'variations': variations,
                        'template_name': None # Old format didn't have this
                    }
                    history.append(new_entry)
            
            with open(jsonl_path, 'w', encoding='utf-8') as jsonl_file:
                for entry in history:
                    jsonl_file.write(json.dumps(entry) + '\n')
            
            # Archive the old CSV file
            archive_dir = os.path.join(os.path.dirname(csv_path), 'archive')
            os.makedirs(archive_dir, exist_ok=True)
            os.rename(csv_path, os.path.join(archive_dir, os.path.basename(csv_path)))
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
                        history.append(json.loads(line))
        except Exception as e:
            print(f"Error loading full history: {e}")
        return history

    def delete_history_entry(self, row_to_delete: Dict[str, str]) -> bool:
        """Deletes a specific entry from the history file by matching its unique ID."""
        filepath = config.get_history_file()
        if not os.path.isfile(filepath):
            return False

        entry_id_to_delete = row_to_delete.get('id')
        if not entry_id_to_delete: return False

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

    def save_result(self, 
                   original: str, 
                   enhanced: str, 
                   enhanced_sd_model: str, 
                   negative_prompt: Optional[str] = None,
                   variations: Optional[Dict[str, Dict[str, str]]] = None, 
                   status: str = "enhanced",
                   favorite: bool = False,
                   template_name: Optional[str] = None) -> None:
        """Save a single result to the JSONL history file."""
        filepath = config.get_history_file()
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        row_data = {
            'id': str(uuid.uuid4()),
            'original_prompt': original,
            'status': status,
            'enhanced_prompt': enhanced,
            'negative_prompt': negative_prompt or '',
            'enhanced_sd_model': enhanced_sd_model,
            'favorite': favorite,
            'variations': variations or {},
            'template_name': template_name
        }

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(json.dumps(row_data) + '\n')
        except Exception as e:
            print(f"Error saving to CSV: {e}")
    
    def save_batch_results(self, results: List[Dict[str, Any]]) -> None:
        """Save multiple results to the history file."""
        for result in results:
            self.save_result(
                result['original'],
                result['enhanced'],
                result['enhanced_sd_model'],
                result.get('negative_prompt'),
                result.get('variations'),
                result.get('status', 'enhanced'),
                result.get('favorite', False),
                result.get('template_name')
            )
