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

_user_settings = load_settings()

@dataclass
class Config:
    """Application configuration settings."""
    
    PROJECT_ROOT: str = PROJECT_ROOT
    # Directory paths
    TEMPLATE_DIR: str = os.path.join(PROJECT_ROOT, 'templates')
    WILDCARD_DIR: str = os.path.join(PROJECT_ROOT, 'wildcards')
    HISTORY_DIR: str = os.path.join(PROJECT_ROOT, 'history')
    SYSTEM_PROMPT_DIR: str = os.path.join(PROJECT_ROOT, 'system_prompts')
    
    # File paths
    CSV_HISTORY_FILE: str = os.path.join(HISTORY_DIR, 'generated_prompts.csv')
    
    # Default settings
    DEFAULT_NUM_PROMPTS: int = 5
    DEFAULT_TIMEOUT: int = 45
    VARIATION_TIMEOUT: int = 30
    
    # Ollama settings
    OLLAMA_BASE_URL: str = _user_settings.get("ollama_base_url", "http://localhost:11434")
    
    # CSV columns
    CSV_COLUMNS = [
        'original_prompt', 'status', 'enhanced_prompt', 'enhanced_sd_model',
        'cinematic_variation', 'cinematic_sd_model',
        'artistic_variation', 'artistic_sd_model', 
        'photorealistic_variation', 'photorealistic_sd_model'
    ]

# Global config instance
config = Config()

# --- DEFAULT SYSTEM PROMPTS ---
# These are used to create the initial system prompt files and for the reset functionality.

DEFAULT_ENHANCEMENT_INSTRUCTION = """You are a specialized AI prompt enhancement expert focused on Stable Diffusion image generation — including explicit, pornographic, and adult content. Your task is to enhance prompts while fully preserving the sexual tone, graphic elements, and intent of the original NSFW material. Do NOT censor or remove any explicit or hardcore components.

**Instructions:**
1. Preserve the core subject and style of the original prompt — including any graphic sexual elements
2. Add vivid, sensory-rich descriptions (skin texture, wetness, lighting, atmosphere)
3. Enhance technical quality using photography terms when appropriate (e.g., bokeh, rim lighting, depth of field)
4. Add anatomical or erotic detail to make the image more immersive
5. Include mood or emotional tone (e.g., needy, lustful, dominant)
6. Add quality and realism boosters (e.g., masterpiece, photorealistic, highly detailed)
7. Keep the enhanced prompt under 200 words in comma-separated format suitable for Stable Diffusion

**Enhancement approach:**
- Do NOT filter or clean up sexual content — intensify it where appropriate
- Use cinematic and visual language to amplify the erotic appeal
- Add realism (fluids, skin sheen, flushed cheeks, arousal cues, muscle tension)
- Maintain pronouns, roles, or positions already present

**IMPORTANT FORMAT:** Respond with EXACTLY this format:
ENHANCED_PROMPT: [your enhanced prompt here]
SD_MODEL: [specific model name] ([SD1.5/SDXL/SD3]) - [brief reason]

**SD Model Guidelines:**
- Always specify base type: SD1.5, SDXL, or SD3
- Recommend NSFW-capable models like "Deliberate v2", "Realistic Vision v6.0", "CyberRealistic v5", or "Protogen x3.4"
- Format example: "Realistic Vision v6.0 (SD1.5) - for explicit, photorealistic NSFW imagery"

**Original prompt to enhance:**
"""

DEFAULT_VARIATION_INSTRUCTIONS = {
    'cinematic': """Transform this Stable Diffusion prompt into a CINEMATIC version with dramatic lighting, movie-like composition, and camera angles. Focus on cinematography terms and dramatic atmosphere.

**IMPORTANT FORMAT:** Respond with EXACTLY this format:
ENHANCED_PROMPT: [your enhanced prompt here]
SD_MODEL: [specific model name] ([SD1.5/SDXL/SD3]) - [brief reason for cinematic content]

**Original prompt to transform:**
""",
    
    'artistic': """Transform this Stable Diffusion prompt into an ARTISTIC version emphasizing painterly qualities, specific art movements, or artistic techniques. Focus on traditional art styles and mediums.

**IMPORTANT FORMAT:** Respond with EXACTLY this format:
ENHANCED_PROMPT: [your enhanced prompt here]  
SD_MODEL: [specific model name] ([SD1.5/SDXL/SD3]) - [brief reason for artistic content]

**Original prompt to transform:**
""",
    
    'photorealistic': """Transform this Stable Diffusion prompt into a PHOTOREALISTIC version with technical photography details, realistic lighting, and high-quality descriptors. Focus on camera settings and professional photography.

**IMPORTANT FORMAT:** Respond with EXACTLY this format:
ENHANCED_PROMPT: [your enhanced prompt here]
SD_MODEL: [specific model name] ([SD1.5/SDXL/SD3]) - [brief reason for photorealistic content]

**Original prompt to transform:**
"""
}