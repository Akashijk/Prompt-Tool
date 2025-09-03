"""
Core utility functions shared across the application's backend logic.
"""

from typing import List, Dict, Any, Optional

def _clean_string(s: Any, replace_underscores: bool = True) -> str:
    """Helper to clean a string value by stripping whitespace and optionally replacing underscores."""
    if not isinstance(s, str):
        return ""
    if replace_underscores:
        s = s.replace('_', ' ')
    return s.strip()

def _sanitize_requires_dict(requires: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Cleans a 'requires' dictionary, removing empty values and cleaning string content."""
    if not isinstance(requires, dict):
        return None
    
    new_requires = {}
    for req_key, req_value in requires.items():
        if req_value is None:
            continue
        
        if isinstance(req_value, str):
            cleaned_val = _clean_string(req_value)
            if cleaned_val:
                new_requires[req_key] = cleaned_val
        elif isinstance(req_value, list):
            # Clean each string in the list and filter out empty ones
            cleaned_list = [_clean_string(v) for v in req_value if isinstance(v, str)]
            cleaned_list = [v for v in cleaned_list if v]
            if cleaned_list:
                new_requires[req_key] = cleaned_list
    
    return new_requires if new_requires else None

def _sanitize_choice_object(choice_obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Sanitizes a single complex choice object, returning None if it's invalid."""
    if not isinstance(choice_obj, dict):
        return None

    # A choice object must have a non-null, non-empty 'value'.
    value = _clean_string(choice_obj.get('value'))
    if not value:
        return None
    choice_obj['value'] = value

    # Remove any keys with null values
    keys_to_delete = [key for key, val in choice_obj.items() if val is None]
    for key in keys_to_delete:
        del choice_obj[key]

    # Clean 'requires' dictionary
    if 'requires' in choice_obj:
        cleaned_requires = _sanitize_requires_dict(choice_obj.get('requires'))
        if cleaned_requires:
            choice_obj['requires'] = cleaned_requires
        else:
            del choice_obj['requires']

    # Clean list-based fields like 'tags' and 'includes'
    for list_key in ['tags', 'includes']:
        if list_key in choice_obj:
            original_list = choice_obj.get(list_key)
            if not isinstance(original_list, list):
                del choice_obj[list_key]
                continue
            
            # For 'includes', we don't replace underscores in the wildcard names.
            # For 'tags', the original logic also just stripped them, so we maintain that.
            cleaned_list = [_clean_string(v, replace_underscores=False) for v in original_list if isinstance(v, str)]
            cleaned_list = [v for v in cleaned_list if v]  # Filter out empty strings
            
            if cleaned_list:
                choice_obj[list_key] = cleaned_list
            else:
                del choice_obj[list_key]

    return choice_obj

def sanitize_wildcard_choices(choices: List[Any]) -> List[Any]:
    """
    Recursively sanitizes and flattens a list of wildcard choices from AI generation.
    - Flattens any nested lists of choices.
    - Replaces underscores with spaces in string values.
    - Handles simple strings and complex choice objects.
    """
    if not isinstance(choices, list):
        return choices  # Return as-is for malformed AI output

    cleaned_choices = []
    for choice in choices:
        if choice is None:
            continue

        # --- NEW: Handle choices that are strings but contain JSON objects ---
        if isinstance(choice, str):
            stripped_choice = choice.strip()
            if stripped_choice.startswith('{') and stripped_choice.endswith('}'):
                try:
                    # It looks like a JSON object, try to parse it.
                    parsed_choice = json.loads(stripped_choice)
                    if isinstance(parsed_choice, dict):
                        choice = parsed_choice # Overwrite the string with the parsed dict
                except json.JSONDecodeError:
                    pass # It wasn't valid JSON, so we'll treat it as a normal string.

        if isinstance(choice, str):
            cleaned_str = _clean_string(choice)
            if cleaned_str:
                cleaned_choices.append(cleaned_str)
        elif isinstance(choice, dict):
            cleaned_obj = _sanitize_choice_object(choice)
            if cleaned_obj:
                cleaned_choices.append(cleaned_obj)
        elif isinstance(choice, list):
            # If the choice is a list, recursively sanitize and extend the main list
            cleaned_choices.extend(sanitize_wildcard_choices(choice))
        else:
            # Keep other malformed items (e.g., numbers) as-is
            cleaned_choices.append(choice)
            
    return cleaned_choices