"""Client for interacting with the InvokeAI REST API."""

import requests
import json
import time
import threading
import base64
import copy
from typing import Dict, Any, Optional, List, Tuple, Callable
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
        self.available_vaes: Optional[List[Dict[str, Any]]] = None

    def is_server_running(self) -> bool:
        """Checks if the InvokeAI server is running and responsive. Does not check version."""
        try:
            response = requests.get(f"{self.base_url}/", timeout=3)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def check_server_compatibility(self):
        """Checks for connection, compatible version, and a working models endpoint by probing."""
        try:
            # Check version first
            version_str = self.get_version()
            self.server_version = parse_version(version_str)
            if self.server_version.major < 3:
                raise IncompatibleVersionError(f"Incompatible InvokeAI version. Found {version_str}, but this tool requires version 3.0.0 or higher.")

            # Now, find a working models endpoint by probing known paths and parameter names
            # The user's test script confirms /api/v2/models/ is a valid endpoint for some versions.
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
                        response = requests.get(f"{self.base_url}{endpoint}", params=params, timeout=3)
                        if response.status_code == 200:
                            # Success! We found a working combination.
                            self.models_endpoint = endpoint
                            self.base_model_param_name = param_name
                            # Now that we have a working endpoint, cache the VAEs
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
        response = requests.get(f"{self.base_url}/api/v1/app/version", timeout=3)
        response.raise_for_status()
        return response.json().get('version', '0.0.0')

    def get_models(self, base_model: Optional[str] = None, model_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Gets a list of models from the InvokeAI server, with optional filtering."""
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
        
        return models

    def _get_vae_override(self, model_object: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Determines if a VAE override is needed and returns the VAE model object if so.
        This is a robust workaround for models that produce black or distorted images.
        """
        if not self.available_vaes:
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
            # For SD-1.5, look for the standard 'sd-vae-ft-mse' VAE.
            sd15_vaes = [v for v in self.available_vaes if v.get('base') in ['sd-1', None]]
            for vae in sd15_vaes:
                if 'sd-vae-ft-mse' in vae.get('name', '').lower():
                    if self.verbose: print(f"INFO: Found standard 'sd-vae-ft-mse'. Applying VAE override for SD-1.5 model.")
                    return vae
            
            print("\n" + "="*80 + "\nWARNING: No standard 'sd-vae-ft-mse' VAE was found for your SD-1.5 model.\nThis can cause distorted images with certain models.\nSOLUTION: Ensure 'sd-vae-ft-mse.safetensors' is in your InvokeAI 'models/sd-1/vae' directory.\n" + "="*80 + "\n")

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
                "is_intermediate": True,
            },
            "save_image": {
                "id": "save_image",
                "type": "save_image",
                "is_intermediate": not save_to_gallery,
                "use_cache": False,
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
            {"source": {"node_id": "noise", "field": "noise"}, "destination": {"node_id": "denoise_latents", "field": "latents"}},
            {"source": {"node_id": "l2i", "field": "image"}, "destination": {"node_id": "save_image", "field": "image"}},
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
                "is_intermediate": True,
            },
            "save_image": {
                "id": "save_image",
                "type": "save_image",
                "is_intermediate": not save_to_gallery,
                "use_cache": False,
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
            {"source": {"node_id": "l2i", "field": "image"}, "destination": {"node_id": "save_image", "field": "image"}},
        ]

        edges.extend(lora_edges)

        return {"nodes": nodes, "edges": edges}

    def empty_model_cache(self) -> bool:
        """
        Sends a request to the InvokeAI server to empty the model cache, freeing VRAM.
        Returns True on success, False on failure.
        """
        try:
            response = requests.post(f"{self.base_url}/api/v2/models/empty_model_cache", timeout=30)
            response.raise_for_status()
            if self.verbose:
                print("INFO: Successfully requested model cache to be emptied.")
            return True
        except requests.RequestException as e:
            print(f"ERROR: Failed to send request to empty model cache: {e}") # type: ignore
            return False

    def generate_image(self, prompt: str, negative_prompt: str, seed: int, model_object: Dict[str, Any], loras: List[Dict[str, Any]], steps: int, cfg_scale: float, scheduler: str, cfg_rescale_multiplier: float, save_to_gallery: bool, verbose: bool = False, cancellation_event: Optional[threading.Event] = None) -> bytes:
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

        timeout = 300  # Increased timeout for slower GPUs or complex generations
        start_time = time.time()
        while time.time() - start_time < timeout:
            if cancellation_event and cancellation_event.is_set():
                print(f"INFO: Cancellation requested for InvokeAI job ID: {item_id}")
                try:
                    # Attempt to tell the server to cancel the job.
                    cancel_response = requests.put(f"{self.base_url}/api/v1/queue/default/i/{item_id}/cancel")
                    cancel_response.raise_for_status()
                    if self.verbose:
                        print(f"INFO: Successfully sent cancellation request for job {item_id}.")
                except requests.RequestException as cancel_err:
                    print(f"WARNING: Failed to send cancellation request for job {item_id}. It may continue running on the server. Error: {cancel_err}")
                raise Exception("Image generation cancelled by user.")
            response = requests.get(f"{self.base_url}/api/v1/queue/default/i/{item_id}")
            response.raise_for_status()
            status_data = response.json()

            if status_data.get("status") == "completed":
                output_data = status_data
                try:
                    session_data = output_data.get("session")
                    if not session_data: raise KeyError("'session' object not found")
                    target_node_id = session_data['source_prepared_mapping']['save_image'][0]
                    results = session_data.get("results")
                    if not results: raise KeyError("'results' key missing from session data")
                    output_node = results.get(target_node_id)
                    if not output_node: raise KeyError(f"Node output for 'save_image' (id: {target_node_id}) not found in results")
                except (KeyError, IndexError) as e:
                    raise Exception(f"Could not parse final image from InvokeAI response. Error: {e}\nResponse was: {json.dumps(output_data, indent=2)}") from e
                
                image_output = output_node.get("image")
                if not image_output: raise Exception(f"Generation completed, but no 'image' key found in the output node: {json.dumps(output_node, indent=2)}")

                image_name = image_output.get("image_name")
                if not image_name: raise Exception(f"Generation completed, but no 'image_name' found in the image output: {json.dumps(image_output, indent=2)}")

                response = requests.get(f"{self.base_url}/api/v1/images/i/{image_name}/full")
                response.raise_for_status()
                return response.content
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
                raise Exception(f"Image generation failed with status: {status_data['status']}. Error: {error_msg}")

            time.sleep(1)

        raise Exception("Image generation timed out.")