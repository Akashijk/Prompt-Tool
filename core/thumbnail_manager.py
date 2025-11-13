"""
Manages the creation, storage, and retrieval of image thumbnails for the UI.
"""

import os
import hashlib
from typing import Optional, Tuple
from PIL import Image
from .config import config

class ThumbnailManager:
    """Handles the thumbnail cache to improve UI performance."""
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
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

    def clear_cache(self):
        """Clears the entire thumbnail cache directory."""
        cache_dir = self._get_cache_dir()
        if os.path.exists(cache_dir):
            try:
                import shutil
                shutil.rmtree(cache_dir)
                if self.verbose: print(f"INFO: Removed old thumbnail cache at {cache_dir}")
            except Exception as e:
                print(f"ERROR: Could not remove old thumbnail cache: {e}")
        
        # Ensure the cache directory exists after clearing
        os.makedirs(cache_dir, exist_ok=True)
        if self.verbose: print(f"INFO: Ensured thumbnail cache directory exists at {cache_dir}")

    def _get_cache_dir(self) -> str:
        """Gets the path to the cache directory, creating it if needed."""
        base_cache_dir = os.path.join(config.CACHE_DIR, 'thumbnails')
        os.makedirs(base_cache_dir, exist_ok=True)
        return base_cache_dir

    def _get_history_dir(self, workflow: str) -> str:
        """Gets the path to the history directory for a specific workflow."""
        original_workflow = config.workflow
        config.workflow = workflow.lower()
        history_dir = config.get_history_file_dir()
        config.workflow = original_workflow # Restore immediately
        return history_dir

    def _get_cache_path(self, original_full_path: str) -> str:
        """Generates a unique, safe cache path for a given image's full path."""
        cache_dir = self._get_cache_dir()
        # Use a hash of the full path to create a unique and filesystem-safe filename.
        filename = hashlib.sha1(original_full_path.encode()).hexdigest() + ".webp" # Use webp for cache
        return os.path.join(cache_dir, filename)

    def get_thumbnail(self, original_full_path: str, target_size: Tuple[int, int]) -> Optional[Image.Image]:
        """
        Gets a thumbnail for an image. Returns a cached version if available,
        otherwise creates, caches, and returns a new one.
        """
        cache_path = self._get_cache_path(original_full_path)

        # Check if cached thumbnail exists and is valid
        if os.path.exists(cache_path):
            try:
                with Image.open(cache_path) as img:
                    # Ensure the cached image is converted to RGB if it's not already
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Resize to target_size, scaling up or down as needed
                    # This is the display size, not the cached size
                    img = img.resize(target_size, Image.Resampling.LANCZOS)
                    return img
            except Exception as e:
                print(f"WARNING: Cached thumbnail for {original_full_path} corrupted or unreadable: {e}. Regenerating.")
                # The cached file might be corrupted, so we'll try to regenerate it.
                pass

        # If not in cache or corrupted, generate it from the original image.
        if not os.path.exists(original_full_path):
            return None

        try:
            with Image.open(original_full_path) as img:
                # Ensure the original image is converted to RGB if it's not already
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # Resize to the DPI-aware thumbnail_size for caching
                cached_img = img.resize(self.thumbnail_size, Image.Resampling.LANCZOS)
                
                # Save this thumbnail to the cache
                cached_img.save(cache_path, "WEBP", quality=80)
                
                # Now, resize the cached_img to the requested target_size for returning
                return cached_img.resize(target_size, Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"ERROR: Error creating thumbnail for {original_full_path}: {e}")
            return None