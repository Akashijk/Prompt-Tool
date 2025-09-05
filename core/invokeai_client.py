"""Client for interacting with the InvokeAI REST API."""

import requests
import json
import time
import base64
from typing import Dict, Any, Optional, List, Tuple
from packaging.version import parse as parse_version

class IncompatibleVersionError(Exception):
    """Custom exception for incompatible InvokeAI server versions."""
    pass

class InvokeAIClient:
    """Handles all InvokeAI model interactions."""
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.models_endpoint: Optional[str] = None
        self.base_model_param_name: str = "base_models"

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
            version = parse_version(version_str)
            if version.major < 3:
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
            params[self.base_model_param_name] = [base_model]
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

    def _build_sdxl_t2i_graph(self, prompt: str, negative_prompt: str, seed: int, model_object: Dict[str, Any], loras: List[Dict[str, Any]], steps: int, cfg_scale: float, scheduler: str) -> Dict[str, Any]:
        """
        Builds the complete node graph for a standard SDXL text-to-image generation,
        including LoRA chaining.
        Returns the complete graph dictionary.
        """
        nodes = {
            "sdxl_model_loader": {
                "type": "sdxl_model_loader",
                "id": "sdxl_model_loader",
                "model": model_object
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
            "sdxl_denoise_latents": {
                "type": "denoise_latents",
                "id": "sdxl_denoise_latents",
                "steps": steps,
                "cfg_scale": cfg_scale,
                "scheduler": scheduler,
                "denoising_start": 0.0,
                "denoising_end": 1.0,
            },
            "l2i": {
                "type": "l2i",
                "id": "l2i",
            },
        }

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
            
            # Check which submodels this LoRA affects. Some LoRAs (especially LyCORIS) might not affect all parts.
            # The submodels list tells us which output fields the lora_loader node will have.
            submodels = lora_object.get('submodels') or [] # Handles the case where 'submodels' is None
            submodel_types = {sub.get('type') for sub in submodels}

            # Only create an edge if the LoRA actually affects the corresponding part.
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
            {"source": {"node_id": "negative_prompt", "field": "value"}, "destination": {"node_id": "negative_conditioning", "field": "prompt"}},
            {"source": {"node_id": "negative_prompt", "field": "value"}, "destination": {"node_id": "negative_conditioning", "field": "style"}},

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

            # Noise & VAE
            {"source": {"node_id": "sdxl_model_loader", "field": "vae"}, "destination": {"node_id": "l2i", "field": "vae"}},
            {"source": {"node_id": "sdxl_denoise_latents", "field": "latents"}, "destination": {"node_id": "l2i", "field": "latents"}},
            {"source": {"node_id": "noise", "field": "noise"}, "destination": {"node_id": "sdxl_denoise_latents", "field": "latents"}},
        ]

        edges.extend(lora_edges)

        return {"nodes": nodes, "edges": edges}

    def generate_image(self, prompt: str, negative_prompt: str, seed: int, model_object: Dict[str, Any], loras: List[Dict[str, Any]], steps: int, cfg_scale: float, scheduler: str) -> bytes:
        """Generates an image using the queue API and returns the raw image bytes."""
        
        graph = self._build_sdxl_t2i_graph(prompt, negative_prompt, seed, model_object, loras, steps, cfg_scale, scheduler)
        
        # Prepare the batch
        batch = {"batch": {"graph": graph, "runs": 1}}

        # Enqueue the batch
        try:
            # The enqueue endpoint appears to be on /api/v1/ even if other endpoints are on v2.
            response = requests.post(f"{self.base_url}/api/v1/queue/default/enqueue_batch", json=batch)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            # This is the key change. We are now extracting the detailed error message.
            error_details = "No details available in response body."
            try:
                # The server's validation error is usually in the JSON body of the 422 response
                error_details = e.response.json()
            except json.JSONDecodeError:
                error_details = e.response.text
            
            # Re-raise a much more informative exception
            raise Exception(f"Failed to enqueue batch. Server returned {e.response.status_code} Unprocessable Entity.\nThis means the generation graph is invalid. Server details:\n{json.dumps(error_details, indent=2)}") from e

        queue_item = response.json()
        # The response contains a list of item_ids for the batch. Since we run with "runs": 1, we take the first one.
        try:
            item_id = queue_item['item_ids'][0]
        except (KeyError, IndexError) as e:
            raise Exception(f"Could not parse queue item ID from InvokeAI response. Response was: {json.dumps(queue_item, indent=2)}") from e

        # Poll for completion
        timeout = 300  # Increased timeout for slower GPUs or complex generations
        start_time = time.time()
        while time.time() - start_time < timeout:
            # The models endpoint is on v2, so the queue polling is likely on v2 as well.
            # The enqueue endpoint is on v1, so the polling should be on v1 as well, using the /i/ path.
            response = requests.get(f"{self.base_url}/api/v1/queue/default/i/{item_id}")
            response.raise_for_status()
            status_data = response.json()

            if status_data.get("status") == "completed":
                # The result is in the status data itself, no need for another request.
                output_data = status_data
                # Robustly parse the output to find the image name
                try:
                    # The session object contains the execution results and mappings
                    session_data = output_data.get("session")
                    if not session_data:
                        raise KeyError("'session' object not found in completed status response")

                    # The final image is the output of the 'l2i' node. We need to find its execution ID.
                    # The mapping from our original graph node ID to the execution graph node ID
                    l2i_node_id = session_data['source_prepared_mapping']['l2i'][0]
                    # The actual results from the execution
                    results = session_data.get("results")
                    if not results: raise KeyError("'results' key missing from session data")
                    # The output of the l2i node
                    output_node = results.get(l2i_node_id)
                    if not output_node: raise KeyError(f"l2i node output (id: {l2i_node_id}) not found in results")
                except (KeyError, IndexError) as e:
                    # Re-raise with a more informative message and the full response for debugging.
                    raise Exception(f"Could not parse final image from InvokeAI response. Error: {e}\nResponse was: {json.dumps(output_data, indent=2)}") from e

                image_output = output_node.get("image")
                if not image_output: raise Exception(f"Generation completed, but no 'image' key found in the output node: {json.dumps(output_node, indent=2)}")

                image_name = image_output.get("image_name")
                if not image_name: raise Exception(f"Generation completed, but no 'image_name' found in the image output: {json.dumps(image_output, indent=2)}")

                response = requests.get(f"{self.base_url}/api/v1/images/i/{image_name}/full")
                response.raise_for_status()
                return response.content
            elif status_data.get("status") in ["failed", "canceled"]:
                error_msg = status_data.get("error", "Unknown error")
                print(f"Full status data: {json.dumps(status_data, indent=2)}")
                raise Exception(f"Image generation failed with status: {status_data['status']}. Error: {error_msg}")

            time.sleep(1)

        raise Exception("Image generation timed out.")