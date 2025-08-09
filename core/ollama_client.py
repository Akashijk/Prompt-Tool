"""Ollama API client for model interactions."""

import json
import re
import requests
from typing import List, Tuple, Optional, Dict, Any
from .config import config

class OllamaClient:
    """Handles all Ollama model interactions."""
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url

    def _is_ollama_running(self) -> bool:
        """Check if the Ollama server is running."""
        try:
            requests.get(self.base_url, timeout=2)
            return True
        except requests.ConnectionError:
            return False

    def list_models(self) -> List[str]:
        """Get list of installed Ollama models."""
        if not self._is_ollama_running():
            raise Exception("Ollama server is not running. Please start it to continue.")

        try:
            res = requests.get(f"{self.base_url}/api/tags")
            res.raise_for_status()
            models_data = res.json().get('models', [])
            return [model['name'] for model in models_data]
        except requests.RequestException as e:
            raise Exception(f"Error getting Ollama models from API: {e}")
    
    def get_model_recommendations(self, models: List[str]) -> List[Tuple[int, str, str]]:
        """Get recommended models with reasons."""
        recommendations = []
        
        for i, model in enumerate(models):
            model_lower = model.lower()
            if 'qwen' in model_lower and '7b' in model_lower:
                recommendations.append((i + 1, model, "Best overall for creative tasks"))
            elif 'qwen' in model_lower and '14b' in model_lower:
                recommendations.append((i + 1, model, "Excellent quality, needs more VRAM"))
            elif 'llama3' in model_lower and '8b' in model_lower:
                recommendations.append((i + 1, model, "Reliable and well-tested"))
        
        return recommendations
    
    def parse_enhanced_response(self, response: str) -> Tuple[str, str]:
        """Parse the enhanced response to extract prompt and SD model recommendation."""
        lines = response.strip().split('\n')
        enhanced_prompt = ""
        sd_model = ""
        
        for line in lines:
            if line.startswith('ENHANCED_PROMPT:'):
                enhanced_prompt = line.replace('ENHANCED_PROMPT:', '').strip()
            elif line.startswith('SD_MODEL:'):
                sd_model = line.replace('SD_MODEL:', '').strip()
        
        # Fallback if format isn't followed exactly
        if not enhanced_prompt:
            enhanced_prompt = response.strip()
        if not sd_model:
            sd_model = "Stable Diffusion XL (SDXL) - general purpose"
        
        return enhanced_prompt, sd_model
    
    def _generate(self, model: str, full_prompt: str, timeout: Optional[int]) -> str:
        """Generic generation method to call the Ollama API."""
        api_url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
        try:
            res = requests.post(api_url, json=payload, timeout=timeout)
            res.raise_for_status()
            return res.json().get('response', '')
        except requests.Timeout:
            raise Exception(f"Request to Ollama timed out after {timeout} seconds.")
        except requests.RequestException as e:
            if hasattr(e, 'response') and e.response and e.response.status_code == 404:
                raise Exception(f"Model '{model}' not found. It may not be pulled or is misspelled.")
            raise Exception(f"Error communicating with Ollama API: {e}")

    def enhance_prompt(self, full_instruction_prompt: str, model: str) -> Tuple[str, str]:
        """Enhance a single prompt using the specified model."""
        try:
            raw_response = self._generate(model, full_instruction_prompt, config.DEFAULT_TIMEOUT)
            
            enhanced, sd_model = self.parse_enhanced_response(raw_response)
            
            # Clean up formatting
            enhanced = enhanced.replace('\n', ' ').replace('  ', ' ')
            return enhanced, sd_model
                
        except Exception:
            # Re-raise to be caught by the GUI and displayed to the user.
            raise

    def chat(self, model: str, messages: List[Dict[str, str]]) -> str:
        """Generic chat with a model for brainstorming, using a message history."""
        api_url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        try:
            res = requests.post(api_url, json=payload, timeout=config.DEFAULT_TIMEOUT)
            res.raise_for_status()
            return res.json().get('message', {}).get('content', '')
        except requests.Timeout:
            raise Exception(f"Request to Ollama timed out after {config.DEFAULT_TIMEOUT} seconds.")
        except requests.RequestException as e:
            if hasattr(e, 'response') and e.response and e.response.status_code == 404:
                raise Exception(f"Model '{model}' not found. It may not be pulled or is misspelled.")
            raise Exception(f"Error communicating with Ollama API: {e}")

    def parse_json_array_from_response(self, response: str) -> List[Any]:
        """Extracts a JSON array from an AI's response, with fallback."""
        try:
            # Look for a JSON block within markdown code fences
            match = re.search(r'```json\s*(\[.*?\])\s*```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
                return json.loads(json_str)

            # Look for the first '[' and last ']'
            start = response.find('[')
            end = response.rfind(']')
            if start != -1 and end != -1 and start < end:
                json_str = response[start:end+1]
                return json.loads(json_str)
        except (json.JSONDecodeError, Exception) as e:
            print(f"Warning: Could not parse JSON array, falling back. Error: {e}")

        return []

    def create_single_variation(self, instruction: str, base_prompt: str, model: str, variation_type: str) -> Dict[str, str]:
        """Create a single variation of a given type."""
        try:
            full_instruction_prompt = instruction + base_prompt
            raw_response = self._generate(model, full_instruction_prompt, config.VARIATION_TIMEOUT)
            var_prompt, var_sd_model = self.parse_enhanced_response(raw_response)
            return {'prompt': var_prompt.replace('\n', ' ').replace('  ', ' '), 'sd_model': var_sd_model}
        except Exception as e:
            print(f"Exception during variation creation for '{variation_type}': {e}")
            # Fallback to the original enhanced prompt if variation fails
            return {'prompt': base_prompt, 'sd_model': f"Stable Diffusion XL (SDXL) - {variation_type} fallback"}

    def unload_model(self, model: str) -> None:
        """Unload a model from memory to free VRAM using the keep_alive=0 method."""
        api_url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": "", # An empty prompt is required
            "keep_alive": 0
        }
        try:
            res = requests.post(api_url, json=payload, timeout=10)
            res.raise_for_status()
            print(f"INFO: Successfully unloaded model '{model}'.")
        except requests.RequestException as e:
            print(f"WARNING: Could not unload model '{model}'. Error: {e}")