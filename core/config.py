"""Configuration settings and constants for the prompt generator."""

import os
import json
from dataclasses import dataclass
from typing import Optional

# --- User Settings Management ---
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".prompt_tool_v2")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
MODEL_PREFIXES_FILE = os.path.join(CONFIG_DIR, "model_prefixes.json")
LORA_PREFIXES_FILE = os.path.join(CONFIG_DIR, "lora_prefixes.json")
WILDCARD_CACHE_FILE = os.path.join(CONFIG_DIR, "wildcards.cache.json")
CACHE_DIR = os.path.join(CONFIG_DIR, "cache")

def load_settings() -> dict:
    """Loads user settings from the config file."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}

def save_settings(settings: dict):
    """Saves user settings to the config file."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

def update_and_save_settings(settings_dict: dict):
    """Updates settings in the global config object and saves them to file."""
    global config
    settings = load_settings()
    for key, value in settings_dict.items():
        settings[key] = value
        config_attr = key.upper()
        if hasattr(config, config_attr) and not isinstance(getattr(type(config), config_attr, None), property):
            setattr(config, config_attr, value)
    save_settings(settings)
    # --- NEW: Reload _user_settings after saving to ensure properties reflect latest values ---
    global _user_settings
    _user_settings = load_settings()

_user_settings = load_settings()

@dataclass
class Config:
    """Application configuration settings."""

    # The root directory of the application.
    PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Default settings
    DEFAULT_FONT_SIZE: int = 11
    DEFAULT_TIMEOUT: int = 45
    BRAINSTORM_TIMEOUT: int = 90
    VARIATION_TIMEOUT: int = 30
    DEFAULT_NEGATIVE_PROMPT_KEY: str = _user_settings.get("default_negative_prompt_key", "standard")
    DEFAULT_INVOKEAI_TIMEOUT: int = 300
    
    # Ollama settings
    OLLAMA_BASE_URL: str = _user_settings.get("ollama_base_url", "http://localhost:11434")

    # InvokeAI settings
    INVOKEAI_BASE_URL: str = _user_settings.get("invokeai_base_url", "http://127.0.0.1:9090")
    DEFAULT_NEGATIVE_PROMPT: str = _user_settings.get("default_negative_prompt", "ugly, deformed, bad quality, cartoon, 3d, disfigured, bad anatomy")
    INVOKEAI_TIMEOUT: int = _user_settings.get("invokeai_timeout", DEFAULT_INVOKEAI_TIMEOUT)
    
    # Workflow setting
    workflow: str = _user_settings.get("workflow", "sfw")

    # UI settings
    theme: str = _user_settings.get("theme", "light")
    font_size: int = _user_settings.get("font_size", DEFAULT_FONT_SIZE)
    DEFAULT_OLLAMA_MODEL: Optional[str] = _user_settings.get("default_ollama_model")



    @property
    def TEMPLATE_BASE_DIR(self) -> str:
        return _user_settings.get("template_base_dir", os.path.join(self.PROJECT_ROOT, 'templates'))

    @property
    def WILDCARD_DIR(self) -> str:
        return _user_settings.get("wildcard_dir", os.path.join(self.PROJECT_ROOT, 'wildcards'))

    @property
    def HISTORY_DIR(self) -> str:
        return _user_settings.get("history_dir", os.path.join(self.PROJECT_ROOT, 'history'))
    
    @property
    def SYSTEM_PROMPT_BASE_DIR(self) -> str:
        return _user_settings.get("system_prompt_base_dir", os.path.join(self.PROJECT_ROOT, 'system_prompts'))

    @property
    def CACHE_DIR(self) -> str:
        return CACHE_DIR # This is a global constant, so it's fine

    @property
    def MODEL_PREFIXES_FILE(self) -> str:
        return MODEL_PREFIXES_FILE # Global constant

    @property
    def LORA_PREFIXES_FILE(self) -> str:
        return LORA_PREFIXES_FILE # Global constant

    @property
    def WILDCARD_NSFW_DIR(self) -> str:
        """Returns the path to the NSFW wildcard directory, derived from the base."""
        return os.path.join(self.WILDCARD_DIR, 'nsfw')

    def get_template_dir(self) -> str:
        """Returns the path to the template directory for the current workflow."""
        return os.path.join(self.TEMPLATE_BASE_DIR, self.workflow)

    def get_system_prompt_dir(self) -> str:
        """Returns the path to the system prompt directory for the current workflow."""
        return os.path.join(self.SYSTEM_PROMPT_BASE_DIR, self.workflow)

    def get_variations_dir(self) -> str:
        """Returns the path to the variations directory for the current workflow."""
        return os.path.join(self.get_system_prompt_dir(), 'variations')

    def get_history_file_dir(self) -> str:
        """Returns the path to the history directory for the current workflow."""
        return os.path.join(self.HISTORY_DIR, self.workflow)

    def get_history_file(self) -> str:
        """Returns the path to the history file for the current workflow."""
        workflow_history_dir = self.get_history_file_dir()
        return os.path.join(workflow_history_dir, 'history.jsonl')



# Global config instance
config = Config()