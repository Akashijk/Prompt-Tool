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
    # Base Directory paths
    TEMPLATE_BASE_DIR: str = os.path.join(PROJECT_ROOT, 'templates')
    WILDCARD_DIR: str = os.path.join(PROJECT_ROOT, 'wildcards')
    WILDCARD_NSFW_DIR: str = os.path.join(WILDCARD_DIR, 'nsfw')
    HISTORY_DIR: str = os.path.join(PROJECT_ROOT, 'history')
    SYSTEM_PROMPT_BASE_DIR: str = os.path.join(PROJECT_ROOT, 'system_prompts')
    
    # Default settings
    DEFAULT_NUM_PROMPTS: int = 5
    DEFAULT_FONT_SIZE: int = 11
    DEFAULT_TIMEOUT: int = 45
    VARIATION_TIMEOUT: int = 30
    
    # Ollama settings
    OLLAMA_BASE_URL: str = _user_settings.get("ollama_base_url", "http://localhost:11434")
    
    # Workflow setting
    workflow: str = _user_settings.get("workflow", "sfw")

    # UI settings
    font_size: int = _user_settings.get("font_size", DEFAULT_FONT_SIZE)

    def get_template_dir(self) -> str:
        """Returns the path to the template directory for the current workflow."""
        return os.path.join(self.TEMPLATE_BASE_DIR, self.workflow)

    def get_system_prompt_dir(self) -> str:
        """Returns the path to the system prompt directory for the current workflow."""
        return os.path.join(self.SYSTEM_PROMPT_BASE_DIR, self.workflow)
    
    def get_csv_history_file(self) -> str:
        """Returns the path to the CSV history file for the current workflow."""
        workflow_history_dir = os.path.join(self.HISTORY_DIR, self.workflow)
        return os.path.join(workflow_history_dir, 'generated_prompts.csv')
    
    # CSV columns
    CSV_COLUMNS = [
        'original_prompt', 'status', 'enhanced_prompt', 'enhanced_sd_model',
        'cinematic_variation', 'cinematic_sd_model',
        'artistic_variation', 'artistic_sd_model', 
        'photorealistic_variation', 'photorealistic_sd_model'
    ]

# Global config instance
config = Config()

# --- DEFAULT SFW SYSTEM PROMPTS ---
DEFAULT_SFW_ENHANCEMENT_INSTRUCTION = """You are a specialized AI prompt enhancement expert for Stable Diffusion. Your task is to take a user's prompt and enhance it to create a more detailed and visually appealing image.

**Instructions:**
1.  Preserve the core subject and style of the original prompt.
2.  Add vivid, sensory-rich descriptions (e.g., lighting, atmosphere, textures).
3.  Enhance technical quality using photography or art terms (e.g., bokeh, rim lighting, impasto, watercolor).
4.  Add details to make the image more immersive and interesting.
5.  Include mood or emotional tone (e.g., serene, chaotic, joyful).
6.  Add quality and realism boosters (e.g., masterpiece, photorealistic, highly detailed, 8k).
7.  Keep the enhanced prompt under 200 words in a comma-separated format suitable for Stable Diffusion.

**IMPORTANT FORMAT:** Respond with EXACTLY this format:
ENHANCED_PROMPT: [your enhanced prompt here]
SD_MODEL: [specific model name] ([SD1.5/SDXL/SD3]) - [brief reason]

**SD Model Guidelines:**
-   Always specify base type: SD1.5, SDXL, or SD3.
-   Recommend common, high-quality models like "DreamShaper", "Realistic Vision", or "Juggernaut XL".
-   Format example: "DreamShaper v8 (SDXL) - for high-quality general purpose and fantasy imagery"

**Original prompt to enhance:**
"""

DEFAULT_SFW_VARIATION_INSTRUCTIONS = {
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

# --- DEFAULT NSFW SYSTEM PROMPTS ---
DEFAULT_NSFW_ENHANCEMENT_INSTRUCTION = """You are a specialized AI prompt enhancement expert focused on Stable Diffusion image generation — including explicit, pornographic, and adult content. Your task is to enhance prompts while fully preserving the sexual tone, graphic elements, and intent of the original NSFW material. Do NOT censor or remove any explicit or hardcore components.

**Instructions:**
1. Preserve the core subject and style of the original prompt — including any graphic sexual elements
2. Add vivid, sensory-rich descriptions (skin texture, wetness, lighting, atmosphere)
3. Enhance technical quality using photography terms when appropriate (e.g., bokeh, rim lighting, depth of field)
4.  Add anatomical or erotic detail to make the image more immersive
5.  Include mood or emotional tone (e.g., needy, lustful, dominant)
6.  Add quality and realism boosters (e.g., masterpiece, photorealistic, highly detailed)
7.  Keep the enhanced prompt under 200 words in comma-separated format suitable for Stable Diffusion

**Enhancement approach:**
-   Do NOT filter or clean up sexual content — intensify it where appropriate
-   Use cinematic and visual language to amplify the erotic appeal
-   Add realism (fluids, skin sheen, flushed cheeks, arousal cues, muscle tension)
-   Maintain pronouns, roles, or positions already present

**IMPORTANT FORMAT:** Respond with EXACTLY this format:
ENHANCED_PROMPT: [your enhanced prompt here]
SD_MODEL: [specific model name] ([SD1.5/SDXL/SD3]) - [brief reason]

**SD Model Guidelines:**
-   Always specify base type: SD1.5, SDXL, or SD3
-   Recommend NSFW-capable models like "Deliberate v2", "Realistic Vision v6.0", "CyberRealistic v5", or "Protogen x3.4"
-   Format example: "Realistic Vision v6.0 (SD1.5) - for explicit, photorealistic NSFW imagery"

**Original prompt to enhance:**
"""

DEFAULT_NSFW_VARIATION_INSTRUCTIONS = {
    'cinematic': """Transform this NSFW Stable Diffusion prompt into a CINEMATIC version with dramatic, moody lighting, intimate camera angles, and a film-like quality. Focus on cinematography terms that enhance the erotic and atmospheric tone.

**IMPORTANT FORMAT:** Respond with EXACTLY this format:
ENHANCED_PROMPT: [your enhanced prompt here]
SD_MODEL: [specific model name] ([SD1.5/SDXL/SD3]) - [brief reason for cinematic NSFW content]

**Original prompt to transform:**
""",
    'artistic': """Transform this NSFW Stable Diffusion prompt into an ARTISTIC version, emphasizing painterly qualities, erotic art movements (like Shunga or Rococo), or sensual artistic techniques. Focus on styles that complement the adult theme.

**IMPORTANT FORMAT:** Respond with EXACTLY this format:
ENHANCED_PROMPT: [your enhanced prompt here]
SD_MODEL: [specific model name] ([SD1.5/SDXL/SD3]) - [brief reason for artistic NSFW content]

**Original prompt to transform:**
""",
    'photorealistic': """Transform this NSFW Stable Diffusion prompt into a hyper-realistic PHOTOREALISTIC version. Focus on technical photography details like skin pores, sweat, bodily fluids, and realistic lighting to create a raw, intimate, and high-quality image.

**IMPORTANT FORMAT:** Respond with EXACTLY this format:
ENHANCED_PROMPT: [your enhanced prompt here]
SD_MODEL: [specific model name] ([SD1.5/SDXL/SD3]) - [brief reason for photorealistic NSFW content]

**Original prompt to transform:**
"""
}