"""Client for interacting with the InvokeAI REST API."""

import requests
import os
import json
import time
import threading
import base64
import copy
from typing import Dict, Any, Optional, List, Tuple, Callable
from .config import config
from packaging.version import Version, parse as parse_version

class IncompatibleVersionError(Exception):
    """Custom exception for incompatible InvokeAI server versions."""
    pass

class InvokeAIClient:
    """Handles all InvokeAI model interactions."""
    def __init__(self, base_url: str, verbose: bool = False):
        self.base_url = base_url.rstrip('/')
        self.verbose = verbose
        self.models_endpoint: Optional[str] = None
        self.base_model_param_name: str = "base_models"
        self.server_version: Optional[Version] = None
        # --- NEW: Caching attributes ---
        self.models_cache: Dict[str, List[Dict[str, Any]]] = {} # Key: f"{model_type}_{base_model}"
        self.schedulers_cache: Optional[List[str]] = None
        self.available_vaes: Optional[List[Dict[str, Any]]] = None
        self._init_lock = threading.Lock()

    def clear_cache(self):
        """Clears the cached models, LoRAs, VAEs, and schedulers."""
        if self.verbose: print("INFO: Clearing InvokeAI data cache.")
        self.models_cache.clear()
        self.schedulers_cache = None
        self.available_vaes = None

    def is_server_running(self) -> bool:
        """Checks if the InvokeAI server is running and responsive. Does not check version."""
        try:
            response = requests.get(f"{self.base_url}/", timeout=3)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def check_server_compatibility(self):
        """Checks for connection, compatible version, and a working models endpoint by probing."""
        # Use a lock to ensure this initialization logic is thread-safe.
        with self._init_lock:
            # If we've already successfully configured, don't re-check.
            # This check is now inside the lock to prevent race conditions.
            if self.models_endpoint and self.server_version:
                return

            try:
                # Check version first
                version_str = self.get_version()
                self.server_version = parse_version(version_str)
                if self.server_version.major < 3:
                    raise IncompatibleVersionError(f"Incompatible InvokeAI version. Found {version_str}, but this tool requires version 3.0.0 or higher.")

                # Now, find a working models endpoint by probing known paths and parameter names
                endpoints_to_try = [
                    "/api/v2/models/", # Newer versions
                    "/api/v1/models/", # Older v3 versions
                ]
                param_names_to_try = ["base_models", "base_model"]

                for endpoint in endpoints_to_try:
                    for param_name in param_names_to_try:
                        try:
                            # We test with a dummy parameter to ensure the endpoint handles filtering.
                            params = {param_name: ["sdxl"]}
                            response = requests.get(f"{self.base_url}{endpoint}", params=params, timeout=10)
                            if response.status_code == 200:
                                # Success! We found a working combination.
                                self.models_endpoint = endpoint
                                self.base_model_param_name = param_name
                                
                                # Now that we have a working endpoint, cache the VAEs.
                                # This call is safe because get_models has its own caching logic.
                                try:
                                    self.available_vaes = self.get_models(model_type='vae')
                                except Exception as e:
                                    print(f"Warning: Could not fetch VAE models: {e}")
                                    self.available_vaes = []
                                if self.verbose:
                                    print(f"INFO: InvokeAI client configured to use endpoint '{self.models_endpoint}' with param '{self.base_model_param_name}'")
                                return
                        except requests.RequestException:
                            continue # Try next combination

                # If we get here, no endpoint worked
                raise ConnectionError("Could not find a working models endpoint on the InvokeAI server. The server is running, but the API structure may have changed.")
            except requests.RequestException as e:
                # Re-raise as a more standard ConnectionError for the caller to handle.
                raise ConnectionError(f"Could not connect to InvokeAI server. Is it running and is the URL correct? Error: {e}")

    def get_version(self) -> str:
        """Gets the InvokeAI server version."""
        response = requests.get(f"{self.base_url}/api/v1/app/version", timeout=10)
        response.raise_for_status()
        return response.json().get('version', '0.0.0')

    def get_models(self, base_model: Optional[str] = None, model_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Gets a list of models from the InvokeAI server, with optional filtering."""
        # --- NEW: Caching logic ---
        cache_key = f"{model_type or 'any'}_{base_model or 'any'}"
        if cache_key in self.models_cache:
            if self.verbose:
                print(f"INFO: Returning cached models for key '{cache_key}'.")
            return self.models_cache[cache_key]
        # --- End of new logic ---

        if not self.models_endpoint:
            # This should be called by the settings window, but as a fallback...
            self.check_server_compatibility()
            if not self.models_endpoint:
                 raise Exception("Could not find working models endpoint. Please test the connection in Settings.")
        
        params = {}
        if base_model:
            # Map the internal 'sd-1.5' convention to the 'sd-1' that the InvokeAI API expects.
            api_base_model = base_model
            if base_model == 'sd-1.5':
                api_base_model = 'sd-1'
            
            params[self.base_model_param_name] = [api_base_model]
        if model_type:
            params['model_type'] = model_type
        
        response = requests.get(f"{self.base_url}{self.models_endpoint}", params=params)
        response.raise_for_status()
        data = response.json()
        
        # The response structure can be {"models": [...]} or just [...]
        models = data.get('models', data if isinstance(data, list) else [])
        
        # Ensure all models have a 'key' for API calls.
        # Some versions might return a different identifier.
        for model in models:
            if 'key' not in model and 'model_name' in model:
                model['key'] = model['model_name']
        
        # --- NEW: Store in cache ---
        if self.verbose:
            print(f"INFO: Caching {len(models)} models for key '{cache_key}'.")
        self.models_cache[cache_key] = models
        # --- End of new logic ---
        
        return models

    def get_schedulers(self) -> List[str]:
        """Gets a list of available schedulers from the InvokeAI server."""
        if self.schedulers_cache is not None:
            if self.verbose:
                print("INFO: Returning schedulers from cache.")
            return self.schedulers_cache

        # Method 1: Try the modern schema endpoint (preferred for InvokeAI 3.1+)
        if self.verbose: print("INFO: Attempting to fetch schedulers from schema endpoint...")
        try:
            response = requests.get(f"{self.base_url}/api/v1/schemas/scheduler", timeout=10)
            if response.status_code == 200:
                schema_data = response.json()
                schedulers = schema_data.get('enum', [])
                if schedulers:
                    self.schedulers_cache = sorted(schedulers)
                    if self.verbose: print(f"INFO: SUCCESS: Fetched {len(schedulers)} schedulers from schema endpoint.")
                    return self.schedulers_cache
        except requests.RequestException as e:
            if self.verbose: print(f"INFO: Could not fetch schedulers from schema endpoint, trying next method. Error: {e}")

        # Method 2: Try the denoise_latents node schema (very reliable)
        if self.verbose: print("INFO: Attempting to fetch schedulers from denoise_latents node schema...")
        try:
            response = requests.get(f"{self.base_url}/api/v1/nodes/denoise_latents", timeout=10)
            if response.status_code == 200:
                node_data = response.json()
                schedulers = node_data.get('inputs', {}).get('scheduler', {}).get('enum', [])
                if schedulers:
                    self.schedulers_cache = sorted(schedulers)
                    if self.verbose: print(f"INFO: SUCCESS: Fetched {len(schedulers)} schedulers from denoise_latents node schema.")
                    return self.schedulers_cache
        except requests.RequestException as e:
            if self.verbose: print(f"INFO: Could not fetch schedulers from denoise_latents node schema, trying next method. Error: {e}")

        # Method 3: Try the older config endpoint
        if self.verbose: print("INFO: Attempting to fetch schedulers from config endpoint...")
        try:
            response = requests.get(f"{self.base_url}/api/v1/app/config", timeout=10)
            if response.status_code == 200:
                config_data = response.json()
                schedulers = config_data.get('scheduler_ids', [])
                if schedulers:
                    self.schedulers_cache = sorted(schedulers)
                    if self.verbose: print(f"INFO: SUCCESS: Fetched {len(schedulers)} schedulers from config endpoint.")
                    return self.schedulers_cache
        except requests.RequestException as e:
            if self.verbose: print(f"INFO: Could not fetch schedulers from config endpoint. Error: {e}")

        # Method 4: Fallback to hardcoded list if all API calls fail
        if self.verbose: print("INFO: FALLBACK: Using hardcoded list for schedulers.")
        fallback_schedulers = sorted([
            "ddim", "ddpm", "deis", "dpmpp_2m", "dpmpp_2m_karras", "dpmpp_2s_a", "dpmpp_2s_a_karras",
            "dpmpp_sde", "dpmpp_sde_karras", "dpmpp_3m_sde", "dpmpp_3m_sde_karras", "euler", "euler_a",
            "heun", "lms", "pndm", "lcm"
        ])
        # Cache the fallback so we don't keep trying the API on subsequent calls in the same session.
        self.schedulers_cache = fallback_schedulers
        return self.schedulers_cache

    def _get_vae_override(self, model_object: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Determines if a VAE override is needed and returns the VAE model object if so.
        This is a robust workaround for models that produce black or distorted images.
        """
        # --- NEW: Fetch VAEs if not already cached ---
        if self.available_vaes is None:
            try:
                # This will use the new caching mechanism in get_models
                self.available_vaes = self.get_models(model_type='vae')
            except Exception as e:
                print(f"Warning: Could not fetch VAE models for override check: {e}")
                self.available_vaes = [] # Set to empty list to prevent re-fetching on every call
        if not self.available_vaes: # Check again after attempting to fetch
            return None

        main_model_base = model_object.get('base')

        if main_model_base == 'sdxl':
            # For SDXL, prioritize the fp16-fix VAE, then any other non-fp16 SDXL VAE.
            sdxl_vaes = [v for v in self.available_vaes if v.get('base') == 'sdxl']
            
            # Priority 1: Look for the well-known 'fp16-fix' VAE.
            for vae in sdxl_vaes:
                if 'sdxl-vae-fp16-fix' in vae.get('name', '').lower():
                    if self.verbose: print(f"INFO: Found high-priority 'sdxl-vae-fp16-fix'. Overriding model's default VAE.")
                    return vae
            
            # Priority 2: Look for any other non-fp16 SDXL VAE.
            for vae in sdxl_vaes:
                if 'fp16' not in vae.get('name', '').lower():
                    if self.verbose: print(f"INFO: Found compatible non-fp16 SDXL VAE '{vae.get('name')}'. Overriding model's default VAE.")
                    return vae
            
            # If we reach here, no suitable override was found for SDXL.
            print("\n" + "="*80 + "\nWARNING: No compatible FP32 VAE was found for your SDXL model.\nThis can cause black or distorted images with certain models.\nSOLUTION: Download 'sdxl-vae.safetensors' and place it in your InvokeAI 'models/sdxl/vae' directory.\n" + "="*80 + "\n")
        
        elif main_model_base in ['sd-1', 'sd-1.5']:
            # For SD-1.5, find a suitable VAE override.
            sd15_vaes = [v for v in self.available_vaes if v.get('base') in ['sd-1', None]]
            
            # If no compatible VAEs are found at all, warn the user and return.
            if not sd15_vaes:
                print("\n" + "="*80 + "\nWARNING: No standard 'sd-vae-ft-mse' VAE was found for your SD-1.5 model.\nThis can cause distorted images with certain models.\nSOLUTION: Ensure 'sd-vae-ft-mse.safetensors' is in your InvokeAI 'models/sd-1/vae' directory.\n" + "="*80 + "\n")
                return None

            # Priority 1: Look for the well-known 'ft-mse' VAE.
            for vae in sd15_vaes:
                if 'sd-vae-ft-mse' in vae.get('name', '').lower():
                    if self.verbose: print(f"INFO: Found standard 'sd-vae-ft-mse'. Applying VAE override for SD-1.5 model.")
                    return vae
            
            # Priority 2: If the standard one isn't found, use the first available compatible VAE as a fallback.
            first_available_vae = sd15_vaes[0]
            if self.verbose: print(f"INFO: Standard 'sd-vae-ft-mse' not found. Using first available compatible VAE as fallback: '{first_available_vae.get('name')}'")
            return first_available_vae

        return None

    def _build_sd15_t2i_graph(self, prompt: str, negative_prompt: str, seed: int, model_object: Dict[str, Any], loras: List[Dict[str, Any]], steps: int, cfg_scale: float, scheduler: str, save_to_gallery: bool) -> Dict[str, Any]:
        """
        Builds the complete node graph for a standard SD-1.5 text-to-image generation.
        """
        vae_source_node_id = "main_model_loader"
        compatible_vae = self._get_vae_override(model_object)

        nodes = {
            "main_model_loader": {
                "type": "main_model_loader",
                "id": "main_model_loader",
                "model": model_object,
            },
            "positive_prompt": {
                "type": "string",
                "id": "positive_prompt",
                "value": prompt
            },
            "negative_prompt": {
                "type": "string",
                "id": "negative_prompt",
                "value": negative_prompt
            },
            "positive_conditioning": {
                "type": "compel",
                "id": "positive_conditioning",
            },
            "negative_conditioning": {
                "type": "compel",
                "id": "negative_conditioning",
            },
            "noise": {
                "type": "noise",
                "id": "noise",
                "seed": seed,
                "width": model_object.get("default_settings", {}).get("width", 512),
                "height": model_object.get("default_settings", {}).get("height", 512),
            },
            "denoise_latents": {
                "type": "denoise_latents",
                "id": "denoise_latents",
                "steps": steps,
                "cfg_scale": cfg_scale,
                "scheduler": scheduler,
                "denoising_start": 0.0,
                "denoising_end": 1.0,
            },
            "l2i": {
                "type": "l2i",
                "id": "l2i",
                "is_intermediate": False,
                "use_cache": False,
                "save_to_gallery": save_to_gallery,
                "image_category": "general",
            },
        }

        if compatible_vae:
            nodes['sd15_fp32_vae_loader'] = {
                "type": "vae_loader",
                "id": "sd15_fp32_vae_loader",
                "vae_model": compatible_vae
            }
            vae_source_node_id = "sd15_fp32_vae_loader"

        last_unet_source_node = "main_model_loader"
        last_clip_source_node = "main_model_loader"

        lora_edges = []
        for i, lora_info in enumerate(loras):
            lora_node_id = f"lora_loader_{i}"
            lora_object = lora_info['lora_object']
            nodes[lora_node_id] = {"id": lora_node_id, "type": "lora_loader", "lora": lora_object, "weight": lora_info['weight']}
            
            submodels = lora_object.get('submodels')
            if submodels is None:
                submodel_types = {'unet', 'text_encoder'}
            else:
                submodel_types = {sub.get('type') for sub in submodels}

            if 'unet' in submodel_types:
                lora_edges.append({"source": {"node_id": last_unet_source_node, "field": "unet"}, "destination": {"node_id": lora_node_id, "field": "unet"}})
                last_unet_source_node = lora_node_id
            
            if 'text_encoder' in submodel_types:
                lora_edges.append({"source": {"node_id": last_clip_source_node, "field": "clip"}, "destination": {"node_id": lora_node_id, "field": "clip"}})
                last_clip_source_node = lora_node_id

        edges = [
            {"source": {"node_id": "positive_prompt", "field": "value"}, "destination": {"node_id": "positive_conditioning", "field": "prompt"}},
            {"source": {"node_id": "negative_prompt", "field": "value"}, "destination": {"node_id": "negative_conditioning", "field": "prompt"}},
            {"source": {"node_id": last_clip_source_node, "field": "clip"}, "destination": {"node_id": "positive_conditioning", "field": "clip"}},
            {"source": {"node_id": last_clip_source_node, "field": "clip"}, "destination": {"node_id": "negative_conditioning", "field": "clip"}},
            {"source": {"node_id": last_unet_source_node, "field": "unet"}, "destination": {"node_id": "denoise_latents", "field": "unet"}},
            {"source": {"node_id": "positive_conditioning", "field": "conditioning"}, "destination": {"node_id": "denoise_latents", "field": "positive_conditioning"}},
            {"source": {"node_id": "negative_conditioning", "field": "conditioning"}, "destination": {"node_id": "denoise_latents", "field": "negative_conditioning"}},
            {"source": {"node_id": vae_source_node_id, "field": "vae"}, "destination": {"node_id": "l2i", "field": "vae"}},
            {"source": {"node_id": "denoise_latents", "field": "latents"}, "destination": {"node_id": "l2i", "field": "latents"}},
            {"source": {"node_id": "noise", "field": "noise"}, "destination": {"node_id": "denoise_latents", "field": "latents"}}
        ]

        edges.extend(lora_edges)

        return {"nodes": nodes, "edges": edges}

    def _build_sdxl_t2i_graph(self, prompt: str, negative_prompt: str, seed: int, model_object: Dict[str, Any], loras: List[Dict[str, Any]], steps: int, cfg_scale: float, scheduler: str, cfg_rescale_multiplier: float, save_to_gallery: bool) -> Dict[str, Any]:
        """
        Builds the complete node graph for a standard SDXL text-to-image generation,
        including LoRA chaining.
        Returns the complete graph dictionary.
        """
        # --- Automatic Negative Prompt Splitting ---
        # To improve generation quality, we separate style-related negatives from content-related ones.
        content_neg_parts = []
        style_neg_parts = []
        # A set of common, style-related negative keywords. This is not exhaustive but covers the majority of presets.
        STYLE_KEYWORDS = {
            'ugly', 'deformed', 'disfigured', 'bad anatomy', 'blurry', 'low resolution',
            'duplicate', 'bad quality', 'worst quality', 'low quality', 'normal quality',
            'jpeg artifacts', 'signature', 'watermark', 'username', 'artist name', 'logo',
            'text', 'error', 'missing fingers', 'extra digit', 'fewer digits', 'cropped',
            '3d', 'cgi', 'render', 'cartoon', 'anime', 'manga', 'child', 'loli', 'shota', 'cub'
        }
        
        for part in negative_prompt.split(','):
            part = part.strip()
            if not part:
                continue
            # Use a simple heuristic: if the exact phrase is a known style keyword, send it to the style prompt.
            if part.lower() in STYLE_KEYWORDS:
                style_neg_parts.append(part)
            else:
                content_neg_parts.append(part)
        
        content_negative_prompt = ", ".join(content_neg_parts)
        style_negative_prompt = ", ".join(style_neg_parts)

        # By default, the VAE comes from the main model loader.
        vae_source_node_id = "sdxl_model_loader"
        compatible_vae = self._get_vae_override(model_object)

        # --- Force VAE Precision ---
        # To robustly prevent black images, we ensure the VAE precision is set to fp32.
        # We do this in two ways:
        # 1. Modify the model object itself to default to fp32 VAE precision.
        # 2. Explicitly set the vae_precision on the model loader node.
        # This provides maximum compatibility across different InvokeAI versions.
        model_object_copy = copy.deepcopy(model_object)
        if 'default_settings' not in model_object_copy:
            model_object_copy['default_settings'] = {}
        model_object_copy['default_settings']['vae_precision'] = 'fp32'

        denoise_node = {
            "type": "denoise_latents",
            "id": "sdxl_denoise_latents",
            "steps": steps,
            "cfg_scale": cfg_scale,
            "scheduler": scheduler,
            "denoising_start": 0.0,
            "denoising_end": 1.0,
        }

        # --- Stability Heuristics ---
        # For diffusers models, which are known to be unstable with fp16 VAEs, we apply a
        # CFG rescale multiplier as a fallback, even if the user sets it to 0. This often
        # mirrors hidden behavior in web UIs that stabilizes these specific models.
        final_rescale_multiplier = cfg_rescale_multiplier
        if model_object.get('format') == 'diffusers' and final_rescale_multiplier == 0.0:
            if self.verbose:
                print("INFO: Applying CFG rescale multiplier for diffusers model stability.")
            final_rescale_multiplier = 0.7

        if final_rescale_multiplier > 0.0:
            denoise_node["cfg_rescale_multiplier"] = final_rescale_multiplier

        nodes = {
            "sdxl_model_loader": {
                "type": "sdxl_model_loader",
                "id": "sdxl_model_loader",
                "model": model_object_copy,
                "vae_precision": "fp32"
            },
            "positive_prompt": {
                "type": "string", 
                "id": "positive_prompt", 
                "value": prompt
            },
            "content_negative_prompt": {
                "type": "string", 
                "id": "content_negative_prompt", 
                "value": content_negative_prompt
            },
            "style_negative_prompt": {
                "type": "string",
                "id": "style_negative_prompt",
                "value": style_negative_prompt
            },
            "positive_conditioning": {
                "type": "sdxl_compel_prompt",
                "id": "positive_conditioning",
            },
            "negative_conditioning": {
                "type": "sdxl_compel_prompt",
                "id": "negative_conditioning",
            },
            "noise": {
                "type": "noise",
                "id": "noise",
                "seed": seed,
                "width": model_object.get("default_settings", {}).get("width", 1024),
                "height": model_object.get("default_settings", {}).get("height", 1024),
            },
            "sdxl_denoise_latents": denoise_node,
            "l2i": {
                "type": "l2i",
                "id": "l2i",
                "is_intermediate": False,
                "use_cache": False,
                "save_to_gallery": save_to_gallery,
                "image_category": "general",
            },
        }

        # If we found a suitable fp32 VAE, we add a vae_loader node and update the source.
        if compatible_vae:
            nodes['sdxl_fp32_vae_loader'] = {
                "type": "vae_loader",
                "id": "sdxl_fp32_vae_loader",
                "vae_model": compatible_vae
            }
            vae_source_node_id = "sdxl_fp32_vae_loader"

        # --- LoRA Chaining & Edge Definition ---
        # This logic determines the source for the main model pipes (UNet, CLIP),
        # correctly chaining LoRAs if they exist.
        last_unet_source_node = "sdxl_model_loader"
        last_clip_source_node = "sdxl_model_loader"
        last_clip2_source_node = "sdxl_model_loader"

        lora_edges = []
        for i, lora_info in enumerate(loras):
            lora_node_id = f"lora_loader_{i}"
            lora_object = lora_info['lora_object']
            nodes[lora_node_id] = {"id": lora_node_id, "type": "lora_loader", "lora": lora_object, "weight": lora_info['weight']}
            
            # Check which submodels this LoRA affects.
            # If 'submodels' is null, we must make a safe assumption. The error indicates that
            # assuming 'clip2' exists can fail. A safer default is to assume only the most
            # common submodels ('unet', 'text_encoder') are affected for such LoRAs.
            submodels = lora_object.get('submodels')
            if submodels is None:
                # Fallback for LoRAs that don't report their submodels, to avoid the 'clip2' error.
                submodel_types = {'unet', 'text_encoder'}
            else:
                # If submodels is an empty list or a list of dicts, process it normally.
                submodel_types = {sub.get('type') for sub in submodels}

            # Now, build the chain conditionally based on the determined submodel_types.
            # This ensures we only try to connect fields that actually exist on the lora_loader node.
            
            if 'unet' in submodel_types:
                lora_edges.append({"source": {"node_id": last_unet_source_node, "field": "unet"}, "destination": {"node_id": lora_node_id, "field": "unet"}})
                last_unet_source_node = lora_node_id
            
            if 'text_encoder' in submodel_types:
                lora_edges.append({"source": {"node_id": last_clip_source_node, "field": "clip"}, "destination": {"node_id": lora_node_id, "field": "clip"}})
                last_clip_source_node = lora_node_id
            
            if 'text_encoder_2' in submodel_types:
                lora_edges.append({"source": {"node_id": last_clip2_source_node, "field": "clip2"}, "destination": {"node_id": lora_node_id, "field": "clip2"}})
                last_clip2_source_node = lora_node_id

        # Define all edges in one place, using the final source nodes from the LoRA chain (or the model loader if no LoRAs).
        edges = [
            # Prompts -> Conditioning
            {"source": {"node_id": "positive_prompt", "field": "value"}, "destination": {"node_id": "positive_conditioning", "field": "prompt"}},
            {"source": {"node_id": "positive_prompt", "field": "value"}, "destination": {"node_id": "positive_conditioning", "field": "style"}},
            {"source": {"node_id": "content_negative_prompt", "field": "value"}, "destination": {"node_id": "negative_conditioning", "field": "prompt"}},
            {"source": {"node_id": "style_negative_prompt", "field": "value"}, "destination": {"node_id": "negative_conditioning", "field": "style"}},

            # Model/LoRA Chain -> Conditioning
            {"source": {"node_id": last_clip_source_node, "field": "clip"}, "destination": {"node_id": "positive_conditioning", "field": "clip"}},
            {"source": {"node_id": last_clip2_source_node, "field": "clip2"}, "destination": {"node_id": "positive_conditioning", "field": "clip2"}},
            {"source": {"node_id": last_clip_source_node, "field": "clip"}, "destination": {"node_id": "negative_conditioning", "field": "clip"}},
            {"source": {"node_id": last_clip2_source_node, "field": "clip2"}, "destination": {"node_id": "negative_conditioning", "field": "clip2"}},

            # Model/LoRA Chain -> Denoise
            {"source": {"node_id": last_unet_source_node, "field": "unet"}, "destination": {"node_id": "sdxl_denoise_latents", "field": "unet"}},

            # Conditioning -> Denoise
            {"source": {"node_id": "positive_conditioning", "field": "conditioning"}, "destination": {"node_id": "sdxl_denoise_latents", "field": "positive_conditioning"}},
            {"source": {"node_id": "negative_conditioning", "field": "conditioning"}, "destination": {"node_id": "sdxl_denoise_latents", "field": "negative_conditioning"}},

            # VAE (now dynamically sourced) & Noise
            {"source": {"node_id": vae_source_node_id, "field": "vae"}, "destination": {"node_id": "l2i", "field": "vae"}},
            {"source": {"node_id": "sdxl_denoise_latents", "field": "latents"}, "destination": {"node_id": "l2i", "field": "latents"}},
            {"source": {"node_id": "noise", "field": "noise"}, "destination": {"node_id": "sdxl_denoise_latents", "field": "latents"}},
        ]

        edges.extend(lora_edges)

        return {"nodes": nodes, "edges": edges}

    def empty_model_cache(self) -> bool:
        """
        Sends a request to the InvokeAI server to empty the model cache, freeing VRAM.
        Returns True on success, False on failure.
        """
        if not self.models_endpoint:
            # If we haven't determined the endpoint, we can't clear the cache.
            # This is a safe fallback, though check_server_compatibility should have run.
            print("WARNING: Cannot empty model cache, InvokeAI client not fully configured.")
            return False
            
        # The endpoint path should be constructed dynamically based on the discovered models endpoint.
        # e.g., /api/v1/models/ or /api/v2/models/
        cache_clear_url = f"{self.base_url}{self.models_endpoint}empty_model_cache"

        try:
            response = requests.post(cache_clear_url, timeout=30)
            response.raise_for_status()
            if self.verbose:
                print("INFO: Successfully requested model cache to be emptied.")
            return True
        except requests.RequestException as e:
            print(f"ERROR: Failed to send request to empty model cache: {e}")
            return False

    def delete_images(self, image_names: List[str]):
        """
        Best-effort deletion of images and their thumbnails from InvokeAI's disk,
        with verification and retries. This runs in a background thread.
        """
        if not image_names:
            return

        def task():
            for image_name in image_names:
                # --- FIX: Use the correct DELETE endpoint for direct file deletion ---
                delete_url = f"{self.base_url}/api/v1/images/i/{image_name}"
                image_verify_url = f"{self.base_url}/api/v1/images/i/{image_name}/full"
                
                max_retries = 3
                retry_delay = 5  # seconds

                for attempt in range(max_retries):
                    # 1. Attempt deletion using requests.delete
                    try:
                        response = requests.delete(delete_url, timeout=10)
                        if self.verbose:
                            print(f"INFO (Attempt {attempt + 1}): Delete request for {image_name} sent. Status: {response.status_code}")
                        if response.status_code in [200, 204, 404]:
                            break # Success or already deleted
                    except requests.RequestException as e:
                        if self.verbose:
                            print(f"WARNING (Attempt {attempt + 1}): Delete request for {image_name} failed: {e}")
                        time.sleep(retry_delay)
                        continue

                    # 2. Verify deletion by trying to fetch the image
                    time.sleep(1.5)  # Give server a moment to process deletion
                    try:
                        verify_response = requests.get(image_verify_url, timeout=5)
                        if verify_response.status_code == 404:
                            if self.verbose: print(f"INFO: Deletion of {image_name} confirmed.")
                            break  # Success, move to the next image name
                        else:
                            if self.verbose: print(f"WARNING (Attempt {attempt + 1}): Verification failed. Image {image_name} still exists (Status: {verify_response.status_code}). Retrying...")
                    except requests.RequestException as e:
                        if self.verbose: print(f"WARNING: Verification request for {image_name} failed: {e}. Assuming deletion was successful.")
                        break # Assume success and move on

                    time.sleep(retry_delay)
                else: # This 'else' belongs to the for loop
                    print(f"ERROR: Failed to verify deletion of image {image_name} after {max_retries} attempts.")

        thread = threading.Thread(target=task, daemon=True)
        thread.start()

    def cancel_queue_item(self, item_id: int):
        """Cancels a specific queue item by its ID."""
        try:
            requests.put(f"{self.base_url}/api/v1/queue/default/i/{item_id}/cancel", timeout=5)
        except requests.RequestException as e:
            if self.verbose:
                print(f"WARNING: Failed to send cancellation for item {item_id}: {e}")

    def cancel_and_cleanup_item(self, item_id: int, save_to_gallery: bool) -> Optional[threading.Thread]:
        """
        Cancels a queue item and, if save_to_gallery is False, polls for its
        final state to delete any generated images. This runs in a background thread.
        Returns the thread object so the caller can wait for it to complete if needed.
        """
        def task():
            # Poll for the final status of the queue item to get the session data.
            timeout = 30  # seconds to wait for the item to terminate
            start_time = time.time()
            final_status_data = None

            while time.time() - start_time < timeout:
                try:
                    response = requests.get(f"{self.base_url}/api/v1/queue/default/i/{item_id}", timeout=5)
                    if response.status_code == 404:
                        if self.verbose: print(f"INFO: Queue item {item_id} not found during cleanup, assuming it was processed.")
                        break
                    response.raise_for_status()
                    status_data = response.json()
                    if status_data.get("status") not in ["in_progress", "pending"]:
                        final_status_data = status_data
                        break
                except requests.RequestException as e:
                    if self.verbose: print(f"WARNING: Could not poll status for queue item {item_id} during cleanup: {e}")
                    break
                time.sleep(1)
            
            if final_status_data:
                image_names = self._extract_image_names_from_session(final_status_data)
                if image_names:
                    if self.verbose: print(f"INFO: Cleaning up {len(image_names)} image(s) from cancelled/closed job {item_id}.")
                    self.delete_images(image_names)

        # Always send the cancellation request immediately.
        self.cancel_queue_item(item_id)

        # If not saving to gallery, we need to start a cleanup thread.
        if not save_to_gallery:
            # Make the thread daemonic so it doesn't block app exit if the caller
            # doesn't explicitly wait for it (e.g., when called from generate_image).
            # The main app's shutdown sequence will still wait for it via is_alive() checks.
            thread = threading.Thread(target=task, daemon=True)
            thread.start()
            return thread
        
        # If saving to gallery, no cleanup thread is needed, so we return None.
        return None

    def _extract_image_names_from_session(self, status_json: dict) -> list[str]:
        """
        Walk the execution result payload and collect any produced image names.
        Structure varies by version; we defensively search.
        """
        names = []
        try:
            sess = status_json.get("session", {})
            results = sess.get("results", {}) or {}
            for node_out in results.values():
                # common shapes: {"images": [{"image_name": "...", ...}, ...]} or {"image": {"image_name": "..."}}
                imgs = node_out.get("images") or node_out.get("image") or []
                if isinstance(imgs, dict):
                    imgs = [imgs]
                for im in imgs:
                    name = (im.get("image_name") or im.get("name") or "").strip()
                    if name:
                        names.append(name)
        except Exception:
            pass # Defensive: if anything goes wrong, we just return what we have.
        return names

    def enqueue_image_generation(self, prompt: str, negative_prompt: str, seed: int, model_object: Dict[str, Any], loras: List[Dict[str, Any]], steps: int, cfg_scale: float, scheduler: str, cfg_rescale_multiplier: float, save_to_gallery: bool, verbose: bool = False, cancellation_event: Optional[threading.Event] = None) -> Dict[str, Any]:
        """Generates an image using the queue API and returns the raw image bytes."""
        model_base = model_object.get('base')
        if model_base == 'sdxl':
            graph = self._build_sdxl_t2i_graph(prompt, negative_prompt, seed, model_object, loras, steps, cfg_scale, scheduler, cfg_rescale_multiplier, save_to_gallery)
        elif model_base in ['sd-1.5', 'sd-1']:
            # Note: cfg_rescale_multiplier is not used for SD-1.5
            graph = self._build_sd15_t2i_graph(prompt, negative_prompt, seed, model_object, loras, steps, cfg_scale, scheduler, save_to_gallery)
        else:
            raise ValueError(f"Unsupported model base type: '{model_base}'. This tool currently supports 'sdxl' and 'sd-1.5'.")
        
        if verbose:
            print(f"\n--- VERBOSE: InvokeAI Generation Graph (Base: {model_base}) ---", flush=True)
            print(json.dumps(graph, indent=2), flush=True)
            print("----------------------------------------\n", flush=True)

        batch = {"batch": {"graph": graph, "runs": 1}}

        try:
            response = requests.post(f"{self.base_url}/api/v1/queue/default/enqueue_batch", json=batch, timeout=120)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_details = "No details available in response body."
            try:
                error_details = e.response.json()
            except json.JSONDecodeError:
                error_details = e.response.text
            raise Exception(f"Failed to enqueue batch. Server returned {e.response.status_code} Unprocessable Entity.\nThis means the generation graph is invalid. Server details:\n{json.dumps(error_details, indent=2)}") from e

        queue_item = response.json()
        try:
            item_id = queue_item['item_ids'][0]
        except (KeyError, IndexError) as e:
            raise Exception(f"Could not parse queue item ID from InvokeAI response. Response was: {json.dumps(queue_item, indent=2)}") from e

        # --- FIX: Return the item_id and the actual scheduler used ---
        final_params = {'scheduler': scheduler}
        return {'item_id': item_id, 'generation_params': final_params}

    def wait_for_image_generation_result(self, item_id: int, save_to_gallery: bool, cancellation_event: Optional[threading.Event] = None) -> Dict[str, Any]:
        """Polls the InvokeAI server for the result of a specific queue item."""
        timeout = config.INVOKEAI_TIMEOUT
        start_time = time.time()
        while time.time() - start_time < timeout:
            if cancellation_event and cancellation_event.is_set():
                # We have an item_id, so we can cancel it on the server.
                # The cleanup part will run in a background thread.
                self.cancel_and_cleanup_item(item_id, save_to_gallery)
                raise Exception("Image generation cancelled by user.")
            response = requests.get(f"{self.base_url}/api/v1/queue/default/i/{item_id}")
            response.raise_for_status()
            status_data = response.json()

            duration = time.time() - start_time
            if status_data.get("status") == "completed":
                output_data = status_data
                
                # --- NEW: Use the robust extraction method ---
                image_names = self._extract_image_names_from_session(output_data)
                if not image_names:
                    raise Exception(f"Could not parse final image name from InvokeAI response.\nResponse was: {json.dumps(output_data, indent=2)}")
                
                # For text-to-image, we expect only one image.
                image_name = image_names[0]

                response = requests.get(f"{self.base_url}/api/v1/images/i/{image_name}/full")
                response.raise_for_status()
                image_bytes = response.content

                # --- NEW: Auto-delete intermediate images ---
                # If the image was not meant to be saved to the main gallery, delete it from disk.
                if not save_to_gallery:
                    self.delete_images(image_names)

                # The generation_params are now constructed at a higher level in the UI.
                # We just return the core results here.
                return {'bytes': image_bytes, 'image_name': image_name, 'duration': duration, 'item_id': item_id}
            elif status_data.get("status") in ["failed", "canceled"]:
                error_msg = "Unknown error"
                try:
                    session_data = status_data.get("session", {})
                    results = session_data.get("results", {})
                    for node_output in results.values():
                        if node_output.get("type") == "execution_error":
                            error_msg = node_output.get("error", error_msg)
                            break
                except Exception:
                    error_msg = status_data.get("error", "Unknown error")
                # Also attempt cleanup on failure/cancellation from server, as files might have been created.
                self.cancel_and_cleanup_item(item_id, save_to_gallery)
                raise Exception(f"Image generation failed with status: {status_data['status']}. Error: {error_msg}")

            time.sleep(1)

        # If we exit the loop, it's a timeout. Cancel the job on the server.
        self.cancel_and_cleanup_item(item_id, save_to_gallery)
        raise Exception("Image generation timed out.")