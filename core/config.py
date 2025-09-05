"""Configuration settings and constants for the prompt generator."""

import os
import json
from dataclasses import dataclass
from typing import Optional

# Determine the project root directory (the 'v2' folder)
# __file__ is the path to this config.py file
# The project root is the parent directory of the 'core' directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- User Settings Management ---
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".prompt_tool_v2")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
WILDCARD_CACHE_FILE = os.path.join(CONFIG_DIR, "wildcards.cache.json")

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
        # Convert to uppercase for dataclass attribute name
        config_attr = key.upper()
        if hasattr(config, config_attr):
            setattr(config, config_attr, value)
    save_settings(settings)

_user_settings = load_settings()

@dataclass
class Config:
    """Application configuration settings."""
    
    PROJECT_ROOT: str = PROJECT_ROOT
    # Base Directory paths
    TEMPLATE_BASE_DIR: str = _user_settings.get("template_base_dir", os.path.join(PROJECT_ROOT, 'templates'))
    WILDCARD_DIR: str = _user_settings.get("wildcard_dir", os.path.join(PROJECT_ROOT, 'wildcards'))
    HISTORY_DIR: str = _user_settings.get("history_dir", os.path.join(PROJECT_ROOT, 'history'))
    SYSTEM_PROMPT_BASE_DIR: str = _user_settings.get("system_prompt_base_dir", os.path.join(PROJECT_ROOT, 'system_prompts'))
    
    # Default settings
    DEFAULT_NUM_PROMPTS: int = 5
    DEFAULT_FONT_SIZE: int = 11
    DEFAULT_TIMEOUT: int = 45
    BRAINSTORM_TIMEOUT: int = 90
    VARIATION_TIMEOUT: int = 30
    
    # Ollama settings
    OLLAMA_BASE_URL: str = _user_settings.get("ollama_base_url", "http://localhost:11434")

    # InvokeAI settings
    INVOKEAI_BASE_URL: str = _user_settings.get("invokeai_base_url", "http://127.0.0.1:9090")
    DEFAULT_NEGATIVE_PROMPT: str = _user_settings.get("default_negative_prompt", "ugly, deformed, bad quality, cartoon, 3d, disfigured, bad anatomy")
    
    # Workflow setting
    workflow: str = _user_settings.get("workflow", "sfw")

    # UI settings
    font_size: int = _user_settings.get("font_size", DEFAULT_FONT_SIZE)

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