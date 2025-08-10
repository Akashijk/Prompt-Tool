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
        enhanced_prompt_match = re.search(r"ENHANCED_PROMPT:\s*(.*)", response, re.DOTALL | re.IGNORECASE)
        sd_model_match = re.search(r"SD_MODEL:\s*(.*)", response, re.DOTALL | re.IGNORECASE)

        enhanced_prompt = enhanced_prompt_match.group(1).strip() if enhanced_prompt_match else response.strip()
        sd_model = sd_model_match.group(1).strip() if sd_model_match else "Stable Diffusion XL (SDXL) - general purpose"

        # If the prompt still contains the model line, strip it out.
        if sd_model_match:
            enhanced_prompt = re.split(r"SD_MODEL:", enhanced_prompt, flags=re.IGNORECASE)[0].strip()

        return enhanced_prompt, sd_model
    
    def _post_request(self, endpoint: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """Centralized method for making POST requests to the Ollama API."""
        api_url = f"{self.base_url}{endpoint}"
        model_name = payload.get("model", "N/A")
        try:
            res = requests.post(api_url, json=payload, timeout=timeout)
            res.raise_for_status()
            return res.json()
        except requests.Timeout:
            raise Exception(f"Request to Ollama timed out after {timeout} seconds.")
        except requests.RequestException as e:
            if hasattr(e, 'response') and e.response and e.response.status_code == 404:
                raise Exception(f"Model '{model_name}' not found. It may not be pulled or is misspelled.")
            raise Exception(f"Error communicating with Ollama API: {e}")

    def _generate(self, model: str, full_prompt: str, timeout: Optional[int]) -> str:
        """Generic generation method to call the Ollama API."""
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
        response_data = self._post_request("/api/generate", payload, timeout)
        return response_data.get('response', '')

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
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        response_data = self._post_request("/api/chat", payload, config.DEFAULT_TIMEOUT)
        return response_data.get('message', {}).get('content', '')

    def parse_json_array_from_response(self, response: str) -> List[Any]:
        """Extracts a JSON array from an AI's response, with fallback and cleanup."""
        json_str = None
        
        # First, try to find a markdown-fenced JSON block (most reliable)
        match = re.search(r'```json\s*(\[.*?\])\s*```', response, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Fallback: find the content between the first '[' and last ']'
            start = response.find('[')
            end = response.rfind(']')
            if start != -1 and end != -1 and start < end:
                json_str = response[start:end+1]

        if json_str:
            try:
                parsed_array = json.loads(json_str)
                # Post-process to replace underscores with spaces in values
                cleaned_choices = []
                for choice in parsed_array:
                    if isinstance(choice, str):
                        cleaned_choices.append(choice.replace('_', ' '))
                    elif isinstance(choice, dict) and 'value' in choice and isinstance(choice.get('value'), str):
                        choice['value'] = choice['value'].replace('_', ' ')
                        cleaned_choices.append(choice)
                    else:
                        cleaned_choices.append(choice) # Keep malformed items as-is
                return cleaned_choices
            except (json.JSONDecodeError, Exception) as e:
                print(f"Warning: Could not parse JSON array, falling back to text parsing. Error: {e}")
                # Fall through to text-based parsing below

        # Fallback: If no JSON string was found or it failed to parse, treat the response as a plain list.
        print("INFO: Falling back to plain text list parsing for AI response.")
        
        # Regex to find lines that look like list items (markdown or numbered)
        list_item_pattern = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)", re.MULTILINE)
        choices = list_item_pattern.findall(response)
        
        if choices:
            # Further cleanup: remove trailing punctuation and replace underscores.
            cleaned_choices = [re.sub(r'[.,]$', '', choice).strip().replace('_', ' ') for choice in choices]
            return [c for c in cleaned_choices if c] # Filter out empty strings

        # Last resort: split by lines and filter out conversational filler.
        ignore_phrases = ["here are", "here's a list", "sure, here", "i've generated", "```", "json", "[", "]"]
        lines = [line.strip().replace('_', ' ') for line in response.split('\n') if line.strip() and not any(phrase in line.lower() for phrase in ignore_phrases)]
        return [l for l in lines if len(l) > 1]

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
        payload = {
            "model": model,
            "prompt": "", # An empty prompt is required
            "keep_alive": 0
        }
        try:
            self._post_request("/api/generate", payload, 10)
            print(f"INFO: Successfully unloaded model '{model}'.")
        except Exception as e:
            # Catch exceptions here since this is a non-critical cleanup task
            print(f"WARNING: Could not unload model '{model}'. Error: {e}")