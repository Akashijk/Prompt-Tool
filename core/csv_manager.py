"""CSV file operations for prompt history."""

import csv
import os
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
    
    def load_full_history(self) -> List[Dict[str, str]]:
        """Load the entire prompt history as a list of dictionaries."""
        filepath = config.get_csv_history_file()
        history = []
        if os.path.isfile(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        history.append(row)
            except Exception as e:
                print(f"Error loading full history: {e}")
        return history

    def delete_history_entry(self, original_prompt_to_delete: str) -> bool:
        """Deletes a specific entry from the history CSV file."""
        filepath = config.get_csv_history_file()
        if not os.path.isfile(filepath):
            return False

        rows_to_keep = []
        deleted = False
        try:
            with open(filepath, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row.get('original_prompt') == original_prompt_to_delete:
                        deleted = True
                    else:
                        rows_to_keep.append(row)
            
            if deleted:
                with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=config.CSV_COLUMNS)
                    writer.writeheader()
                    writer.writerows(rows_to_keep)
            
            return deleted
        except Exception as e:
            print(f"Error deleting history entry: {e}")
            return False

    def save_result(self, 
                   original: str, 
                   enhanced: str, 
                   enhanced_sd_model: str, 
                   variations: Optional[Dict[str, Dict[str, str]]] = None, 
                   status: str = "enhanced") -> None:
        """Save a single result to CSV."""
        filepath = config.get_csv_history_file()
        file_exists = os.path.isfile(filepath)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        try:
            with open(filepath, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                
                if not file_exists:
                    writer.writerow(config.CSV_COLUMNS)
                
                # Handle variations
                if variations:
                    cinematic = variations.get('cinematic', {})
                    artistic = variations.get('artistic', {})
                    photorealistic = variations.get('photorealistic', {})
                    
                    cinematic_prompt = cinematic.get('prompt', '')
                    cinematic_sd = cinematic.get('sd_model', '')
                    artistic_prompt = artistic.get('prompt', '')
                    artistic_sd = artistic.get('sd_model', '')
                    photo_prompt = photorealistic.get('prompt', '')
                    photo_sd = photorealistic.get('sd_model', '')
                else:
                    cinematic_prompt = artistic_prompt = photo_prompt = ''
                    cinematic_sd = artistic_sd = photo_sd = ''
                
                writer.writerow([
                    original, status, enhanced, enhanced_sd_model,
                    cinematic_prompt, cinematic_sd,
                    artistic_prompt, artistic_sd,
                    photo_prompt, photo_sd
                ])
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