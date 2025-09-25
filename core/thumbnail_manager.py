"""
Manages the creation, storage, and retrieval of image thumbnails for the UI.
"""

import os
import hashlib
import threading
from typing import Optional
from PIL import Image
from .config import config

class ThumbnailManager:
    """Handles the thumbnail cache to improve UI performance."""
    def __init__(self):
        # Base size for standard DPI screens
        base_size = 256
        
        # Check for high DPI displays (like on macOS) and adjust size.
        try:
            from PySide6.QtGui import QGuiApplication
            pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()
            self.thumbnail_size = (int(base_size * pixel_ratio), int(base_size * pixel_ratio))
        except (ImportError, Exception):
            # Fallback if Qt is not available or fails
            self.thumbnail_size = (base_size, base_size)

    def _get_cache_dir(self, workflow: str) -> str:
        """Gets the path to the cache directory for a specific workflow, creating it if needed."""
        base_cache_dir = os.path.join(config.CACHE_DIR, 'thumbnails', workflow.lower())
        os.makedirs(base_cache_dir, exist_ok=True)
        return base_cache_dir

    def _get_history_dir(self, workflow: str) -> str:
        """Gets the path to the history directory for a specific workflow."""
        original_workflow = config.workflow
        config.workflow = workflow.lower()
        history_dir = config.get_history_file_dir()
        config.workflow = original_workflow # Restore immediately
        return history_dir

    def _get_cache_path(self, original_relative_path: str, workflow: str) -> str:
        """Generates a unique, safe cache path for a given image path."""
        cache_dir = self._get_cache_dir(workflow)
        # Use a hash of the relative path to create a unique and filesystem-safe filename.
        filename = hashlib.sha1(original_relative_path.encode()).hexdigest() + ".webp"
        return os.path.join(cache_dir, filename)

    def get_thumbnail(self, original_relative_path: str, workflow: str) -> Optional[Image.Image]:
        """
        Gets a thumbnail for an image. Returns a cached version if available,
        otherwise creates, caches, and returns a new one.
        """
        cache_path = self._get_cache_path(original_relative_path, workflow)
        if os.path.exists(cache_path):
            try:
                return Image.open(cache_path)
            except Exception:
                # The cached file might be corrupted, so we'll try to regenerate it.
                pass

        # If not in cache or corrupted, generate it.
        history_dir = self._get_history_dir(workflow)
        original_full_path = os.path.join(history_dir, original_relative_path)
        if not os.path.exists(original_full_path):
            return None

        try:
            with Image.open(original_full_path) as img:
                img_copy = img.copy()
                img_copy.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)
                # Save as WEBP for good quality and small file size.
                img_copy.save(cache_path, "WEBP", quality=85)
                return img_copy
        except Exception as e:
            print(f"Error creating thumbnail for {original_relative_path}: {e}")
            return None