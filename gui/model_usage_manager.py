"""
Manages the lifecycle of active AI models to optimize resource usage.
"""

import threading
from typing import Dict, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from core.prompt_processor import PromptProcessor

class ModelUsageManager:
    """Tracks model usage and unloads them from VRAM when no longer needed."""
    def __init__(self, processor: 'PromptProcessor'):
        self.processor = processor
        self.active_models: Dict[str, int] = {}

    def register_usage(self, model_name: Optional[str]):
        """Increments the usage count for a model."""
        if not model_name or "model" in model_name.lower():
            return
        self.active_models[model_name] = self.active_models.get(model_name, 0) + 1

    def unregister_usage(self, model_name: Optional[str]):
        """Decrements the usage count for a model and unloads it if no longer used."""
        if not model_name or "model" in model_name.lower():
            return
        
        if model_name in self.active_models:
            self.active_models[model_name] -= 1
            if self.active_models[model_name] <= 0:
                # We don't need to join this thread; it can clean up on its own.
                # This prevents the UI from hanging if the unload takes time.
                thread = threading.Thread(target=self.processor.cleanup_model, args=(model_name,), daemon=True)
                thread.start()
                del self.active_models[model_name]

    def get_active_models(self) -> List[str]:
        """Returns a list of all currently active models."""
        return list(self.active_models.keys())