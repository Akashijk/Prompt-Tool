"""CSV file operations for prompt history."""

import csv
import os
import tempfile
from typing import Set, Optional, Dict, Any, List
from .config import config

class CSVManager:
    """Handles CSV file operations for prompt history."""
    
    def __init__(self):
        pass # No filepath state needed; it will be determined on-the-fly.
    
    def load_history(self) -> Set[str]:
        """Load existing prompt history from CSV."""
        filepath = config.get_csv_history_file()
        history = set()
        if os.path.isfile(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        if 'original_prompt' in row:
                            history.add(row['original_prompt'])
            except Exception as e:
                print(f"Error loading history: {e}")
        return history
    
    def _migrate_history_file(self, filepath: str, data: List[Dict[str, str]]):
        """Overwrites a history file with a header and proper formatting."""
        print(f"INFO: Migrating old history file to new format: {filepath}")
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                # Use extrasaction='ignore' to be safe with potentially malformed old rows
                writer = csv.DictWriter(csvfile, fieldnames=config.CSV_COLUMNS, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(data)
        except Exception as e:
            print(f"ERROR: Failed to migrate history file {filepath}. Error: {e}")

    def load_full_history(self) -> List[Dict[str, str]]:
        """Load the entire prompt history, migrating old formats if necessary."""
        filepath = config.get_csv_history_file()
        history = []
        # Return early if file doesn't exist or is empty
        if not os.path.isfile(filepath) or os.path.getsize(filepath) == 0:
            return history

        is_old_format = False
        try:
            with open(filepath, 'r', newline='', encoding='utf-8') as csvfile:
                # Check for header using the sniffer, which is fine for this detection task
                try:
                    has_header = csv.Sniffer().has_header(csvfile.read(2048))
                    if not has_header:
                        is_old_format = True
                except csv.Error:
                    # Sniffer fails on single-line files or other edge cases, assume old format
                    is_old_format = True
                
                csvfile.seek(0) # Rewind after sniffing

                # Load data based on the detected format
                if not is_old_format:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        history.append(row)
                else:
                    # Load old format (headerless)
                    reader = csv.reader(csvfile)
                    for row_list in reader:
                        if not any(row_list): continue # Skip completely empty lines
                        # Create a dict, being careful about rows with fewer columns than expected
                        row_dict = {k: v for k, v in zip(config.CSV_COLUMNS, row_list)}
                        history.append(row_dict)
            
            # If we detected and loaded an old format, migrate the file on disk
            if is_old_format and history:
                self._migrate_history_file(filepath, history)

        except Exception as e:
            print(f"Error loading full history: {e}")
        return history

    def delete_history_entry(self, row_to_delete: Dict[str, str]) -> bool:
        """Deletes a specific entry from the history CSV file by matching the full row.
        
        This method is memory-efficient and suitable for large files, as it avoids
        loading the entire file into memory.
        """
        filepath = config.get_csv_history_file()
        if not os.path.isfile(filepath):
            return False

        deleted = False
        temp_filepath = ""
        try:
            # Create a temporary file to write the new content to
            with tempfile.NamedTemporaryFile(mode='w', newline='', encoding='utf-8', delete=False, dir=os.path.dirname(filepath)) as temp_file:
                temp_filepath = temp_file.name
                with open(filepath, 'r', newline='', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    # If the file is empty or has no header, there's nothing to delete.
                    if not reader.fieldnames:
                        return False
                    
                    writer = csv.DictWriter(temp_file, fieldnames=reader.fieldnames)
                    writer.writeheader()

                    for row in reader:
                        if not deleted and row == row_to_delete:
                            deleted = True  # Found the row to delete, skip writing it
                        else:
                            writer.writerow(row)
            
            if deleted:
                os.replace(temp_filepath, filepath)
            else:
                os.remove(temp_filepath) # No changes were made, so remove the temp file
            return deleted
        except Exception as e:
            print(f"Error deleting history entry: {e}")
            # Clean up the temp file on error
            if temp_filepath and os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return False

    def save_result(self, 
                   original: str, 
                   enhanced: str, 
                   enhanced_sd_model: str, 
                   variations: Optional[Dict[str, Dict[str, str]]] = None, 
                   status: str = "enhanced") -> None:
        """Save a single result to CSV."""
        filepath = config.get_csv_history_file()
        # Check if file exists AND is not empty. An empty file needs a header.
        file_has_content = os.path.isfile(filepath) and os.path.getsize(filepath) > 0
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        row_data = {
            'original_prompt': original,
            'status': status,
            'enhanced_prompt': enhanced,
            'enhanced_sd_model': enhanced_sd_model,
        }

        if variations:
            for var_type, var_data in variations.items():
                # Ensure the keys match the CSV_COLUMNS in config
                row_data[f'{var_type}_variation'] = var_data.get('prompt', '')
                row_data[f'{var_type}_sd_model'] = var_data.get('sd_model', '')

        try:
            with open(filepath, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=config.CSV_COLUMNS)
                
                if not file_has_content:
                    writer.writeheader()
                
                writer.writerow(row_data)
        except Exception as e:
            print(f"Error saving to CSV: {e}")
    
    def save_batch_results(self, results: List[Dict[str, Any]]) -> None:
        """Save multiple results to CSV."""
        for result in results:
            self.save_result(
                result['original'],
                result['enhanced'],
                result['enhanced_sd_model'],
                result.get('variations'),
                result.get('status', 'enhanced')
            )