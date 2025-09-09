"""Ollama API client for model interactions."""

import json
import re
import requests
import time
from typing import List, Tuple, Optional, Dict, Any, Callable
from .config import config
from .default_content import MODEL_RECOMMENDATIONS
from .utils import sanitize_wildcard_choices

class OllamaClient:
    """Handles all Ollama model interactions."""
    
    def __init__(self, base_url: str = "http://localhost:11434", verbose: bool = False):
        self.base_url = base_url
        self.verbose = verbose
        self._is_running_cache: Optional[bool] = None
        self._last_check_time: float = 0
        self._cache_duration: int = 5  # Cache for 5 seconds

    def _is_ollama_running(self) -> bool:
        """Check if the Ollama server is running, with caching."""
        current_time = time.time()
        # Return cached result if it's recent
        if self._is_running_cache is not None and (current_time - self._last_check_time) < self._cache_duration:
            return self._is_running_cache

        try:
            requests.get(self.base_url, timeout=2)
            self._is_running_cache = True
        except requests.ConnectionError:
            self._is_running_cache = False
        
        self._last_check_time = current_time
        return self._is_running_cache

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
        """Get recommended models with reasons, based on data from config."""
        found_recs = []

        for i, model in enumerate(models):
            model_lower = model.lower()
            for rule in MODEL_RECOMMENDATIONS:
                if all(keyword in model_lower for keyword in rule['keywords']):
                    found_recs.append({
                        'idx': i + 1,
                        'model': model,
                        'reason': rule['reason'],
                        'priority': rule.get('priority', 999) # Default to low priority
                    })
                    break # Move to the next model once a rule is matched
        
        # Sort recommendations by priority (lower is better)
        sorted_recs = sorted(found_recs, key=lambda x: x['priority'])
        
        # Format for the final output tuple
        return [(rec['idx'], rec['model'], rec['reason']) for rec in sorted_recs]
    
    def parse_enhanced_response(self, response: str) -> Tuple[str, str]:
        """
        Parse the enhanced response to extract prompt and SD model recommendation.
        This method is designed to be robust against variations in AI output, such as missing sections or
        sections appearing out of order.
        """
        # Find the starting positions of each key, case-insensitively
        enhanced_match = re.search(r"ENHANCED_PROMPT:", response, re.IGNORECASE)
        sd_model_match = re.search(r"SD_MODEL:", response, re.IGNORECASE)

        # If ENHANCED_PROMPT is missing, assume the whole response is the prompt
        if not enhanced_match:
            enhanced_prompt = response.strip()
            sd_model = "Stable Diffusion XL (SDXL) - general purpose"
            return enhanced_prompt, sd_model

        # Create a list of found sections with their start positions
        sections = []
        if enhanced_match: sections.append({'key': 'enhanced', 'pos': enhanced_match.start(), 'match': enhanced_match})
        if sd_model_match: sections.append({'key': 'sd_model', 'pos': sd_model_match.start(), 'match': sd_model_match})

        # Sort sections by their position in the string
        sections.sort(key=lambda x: x['pos'])

        # Extract content for each section
        results = {'enhanced': '', 'sd_model': ''}
        for i, section in enumerate(sections):
            key = section['key']
            start_pos = section['match'].end() # Start extracting content *after* the key
            
            # Determine the end position for this section's content
            if i + 1 < len(sections):
                # The end is the start of the next section
                end_pos = sections[i+1]['pos']
            else:
                # This is the last section, so it goes to the end of the string
                end_pos = len(response)
            
            content = response[start_pos:end_pos].strip()
            results[key] = content

        enhanced_prompt = results.get('enhanced', response.strip())
        sd_model = results.get('sd_model', "Stable Diffusion XL (SDXL) - general purpose")

        return enhanced_prompt, sd_model

    def _post_request(self, endpoint: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """Centralized method for making POST requests to the Ollama API with a retry mechanism."""
        api_url = f"{self.base_url}{endpoint}"
        model_name = payload.get("model", "N/A")
        
        max_retries = 3
        backoff_factor = 0.5  # seconds
        last_exception = None

        for attempt in range(max_retries):
            try:
                res = requests.post(api_url, json=payload, timeout=timeout)
                res.raise_for_status()  # Raises HTTPError for bad responses (4xx or 5xx)
                return res.json()
            except (requests.Timeout, requests.ConnectionError) as e:
                last_exception = e
                if attempt < max_retries - 1:
                    sleep_time = backoff_factor * (2 ** attempt)
                    print(f"WARNING: Connection error ({type(e).__name__}) on attempt {attempt + 1}/{max_retries}. Retrying in {sleep_time:.2f}s...")
                    time.sleep(sleep_time)
            except requests.HTTPError as e:
                last_exception = e
                status_code = e.response.status_code
                # Retry on server-side errors (5xx) which might be transient
                if 500 <= status_code <= 599 and attempt < max_retries - 1:
                    sleep_time = backoff_factor * (2 ** attempt)
                    print(f"WARNING: Ollama server error (Status {status_code}) on attempt {attempt + 1}/{max_retries}. Retrying in {sleep_time:.2f}s...")
                    time.sleep(sleep_time)
                    continue
                
                # For non-retryable HTTP errors (like 404), fail immediately.
                error_message = f"Ollama API returned an error (Status {status_code}):"
                try:
                    error_body = e.response.json()
                    specific_error = error_body.get('error', str(e))
                    if status_code == 404:
                        error_message = f"Model '{model_name}' not found on the Ollama server. It may not be pulled or is misspelled. (Details: {specific_error})"
                    else:
                        error_message = f"{error_message} {specific_error}"
                except json.JSONDecodeError:
                    error_message = f"{error_message} {e.response.text}"
                raise Exception(error_message) # Fail fast
            except requests.RequestException as e:
                raise Exception(f"An unexpected network error occurred when communicating with Ollama: {e}")

        # If the loop completes, all retries have failed. Raise an informative exception.
        if isinstance(last_exception, requests.Timeout):
            raise Exception(f"Request to Ollama timed out after {max_retries} attempts ({timeout}s each). The server might be busy or the model is taking too long to load.")
        elif isinstance(last_exception, requests.ConnectionError):
            raise Exception(f"Could not connect to Ollama at {self.base_url} after {max_retries} attempts. Please ensure the Ollama server is running and the URL is correct.")
        elif isinstance(last_exception, requests.HTTPError):
             raise Exception(f"Ollama server returned a persistent error (Status {last_exception.response.status_code}) after {max_retries} attempts.")
        else:
            raise Exception(f"Request to Ollama failed after multiple retries. Last error: {last_exception}")

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

    def chat(self, model: str, messages: List[Dict[str, str]], timeout: Optional[int] = None) -> str:
        """Generic chat with a model for brainstorming, using a message history."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        final_timeout = timeout if timeout is not None else config.DEFAULT_TIMEOUT
        response_data = self._post_request("/api/chat", payload, final_timeout)
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
                return sanitize_wildcard_choices(parsed_array)
            except (json.JSONDecodeError, Exception) as e:
                if self.verbose:
                    print(f"Warning: Could not parse JSON array, falling back to text parsing. Error: {e}")
                # Fall through to text-based parsing below

        # Fallback: If JSON parsing fails, use a more robust text-based parsing.
        if self.verbose: print("INFO: Falling back to plain text list parsing for AI response.")
        
        # Define conversational filler prefixes to ignore. Checking for prefixes is safer than 'in'.
        ignore_prefixes = [
            "here are", "here's a list", "sure, here", "of course", "certainly", 
            "i've generated", "the new choices are:", "as requested", "below are"
        ]
        
        # Define characters to strip from the beginning and end of each line.
        # This handles lines that look like '  "my choice",'
        strip_chars = " \t\n\r,.'\""

        cleaned_lines = []
        for line in response.split('\n'):
            line = line.strip()
            
            # Skip empty lines or lines that are just code fences/brackets
            if not line or line.lower() in ['```json', '```', '[', ']', '{', '}']:
                continue
            
            # Skip conversational filler lines
            if any(line.lower().startswith(prefix) for prefix in ignore_prefixes):
                continue
            
            # Clean the line content:
            # 1. Remove list markers like ' - ' or '1. '
            cleaned_line = re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", line)
            # 2. Strip surrounding junk characters (quotes, commas, etc.)
            cleaned_line = cleaned_line.strip(strip_chars)
            
            if cleaned_line:
                cleaned_lines.append(cleaned_line)

        # The sanitize function will handle replacing underscores and filtering empty strings.
        return sanitize_wildcard_choices(cleaned_lines)

    def parse_json_object_from_response(self, response: str, fallback_topic: str) -> str:
        """Extracts a JSON object from an AI's response, with fallback and cleanup."""
        json_str = None
        # First, try to find a markdown-fenced JSON block (most reliable)
        match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Fallback: find the content between the first '{' and last '}'
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end != -1 and start < end:
                json_str = response[start:end+1]

        if json_str:
            try:
                parsed_data = json.loads(json_str)
                # This check is now more flexible. It handles both single wildcard objects
                # and other valid JSON objects like the refactor response.
                if isinstance(parsed_data, dict):
                    if 'choices' in parsed_data:
                        # It's a standard wildcard object, sanitize it.
                        parsed_data['choices'] = sanitize_wildcard_choices(parsed_data.get('choices', []))
                        return json.dumps(parsed_data, indent=2)
                    else:
                        # It's a different but valid JSON object (e.g., from refactor).
                        # Return it as a string for the caller to validate its structure.
                        return json_str
            except (json.JSONDecodeError, Exception):
                # The extracted string was not valid JSON, fall through to text parsing.
                pass

        # Fallback: If JSON parsing fails or it's not a dict, treat as a plain list.
        # This reuses the robust list parsing logic from the array parser.
        if self.verbose:
            print("INFO: Falling back to plain text list parsing for wildcard object.")
        choices = self.parse_json_array_from_response(response)

        fallback_data = {
            "description": f"AI-generated list for the topic: {fallback_topic} (fallback mode)", 
            "choices": choices
        }
        return json.dumps(fallback_data, indent=2)

    def parse_template_from_response(self, response: str) -> Tuple[str, List[str]]:
        """Parses the AI response for template and new wildcards."""
        template_content = ""
        new_wildcards = []
        
        # Use re.IGNORECASE to handle variations in casing like 'TEMPLATE:' vs 'Template:'
        template_match = re.search(r"TEMPLATE:\s*(.*)", response, re.DOTALL | re.IGNORECASE)
        if template_match:
            # Further split by NEW_WILDCARDS to ensure we only get the template part
            # Use re.split for case-insensitivity to match the search
            template_content = re.split(r"NEW_WILDCARDS:", template_match.group(1), flags=re.IGNORECASE)[0].strip()

        wildcards_match = re.search(r"NEW_WILDCARDS:\s*(.*)", response, re.DOTALL | re.IGNORECASE)
        if wildcards_match:
            wildcards_str = wildcards_match.group(1).strip()
            if wildcards_str.lower() != 'none':
                new_wildcards = [w.strip() for w in wildcards_str.split(',') if w.strip()]

        # If parsing fails (e.g., AI didn't follow format), fall back to treating the whole response as the template
        if not template_content:
            template_content = response
            
        return template_content, new_wildcards

    def create_single_variation(self, instruction: str, base_prompt: str, base_sd_model: str, model: str, variation_type: str, original_prompt_context: Optional[str] = None) -> Tuple[str, str]:
        """Create a single variation of a given type."""
        try:
            # If we have both original and enhanced (base) prompts, provide both to the AI for better context.
            if original_prompt_context and original_prompt_context != base_prompt:
                prompt_to_transform = (f"ORIGINAL PROMPT: {original_prompt_context}\n\n"
                                       f"ENHANCED PROMPT TO TRANSFORM: {base_prompt}")
            else:
                prompt_to_transform = base_prompt
            full_instruction_prompt = instruction + prompt_to_transform
            raw_response = self._generate(model, full_instruction_prompt, config.VARIATION_TIMEOUT)
            var_prompt, var_sd_model = self.parse_enhanced_response(raw_response)
            return var_prompt.replace('\n', ' ').replace('  ', ' '), var_sd_model
        except Exception as e:
            print(f"Exception during variation creation for '{variation_type}': {e}")
            # Fallback to the original enhanced prompt and its model if variation fails
            return base_prompt, base_sd_model

    def unload_model(self, model: str) -> None:
        """Unload a model from memory to free VRAM using the keep_alive=0 method."""
        payload = {
            "model": model,
            "prompt": "", # An empty prompt is required
            "keep_alive": 0
        }
        try:
            self._post_request("/api/generate", payload, 10)
            if self.verbose:
                print(f"INFO: Successfully unloaded model '{model}'.")
        except Exception as e:
            # Catch exceptions here since this is a non-critical cleanup task
            print(f"WARNING: Could not unload model '{model}'. Error: {e}")

    def interrogate_image(self, model: str, base64_image: str, prompt: str) -> str:
        """Generates a prompt from an image using a multimodal model."""
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [base64_image],
            "stream": False
        }
        # Use a longer timeout for vision models as they can be slower
        response_data = self._post_request("/api/generate", payload, config.BRAINSTORM_TIMEOUT)
        # The response is a simple string
        return response_data.get('response', '').strip()