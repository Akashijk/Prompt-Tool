"""A Qt-based window for viewing and managing all favorited images from the history."""

import queue # Ensure queue is imported
import os
import copy
import random
import uuid
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QScrollArea, QWidget, QFrame, QMessageBox, QApplication
)
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QEvent
from PySide6.QtGui import QPixmap
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING

from core.prompt_processor import PromptProcessor
from core.config import config
from .image_preview_mixin import ImagePreviewMixin
from .image_generation_dialog import ImageGenerationOptionsDialog
from .multi_image_preview_dialog import MultiImagePreviewDialog
from .custom_widgets import SmoothTextEdit
from PIL.ImageQt import ImageQt
from PIL import Image

from .history_viewer import ThumbnailThread, ThumbnailLoaderWorker # NEW: Import ThumbnailThread and ThumbnailLoaderWorker

class FavoriteLoaderWorker(QObject):
    """Worker to fetch all favorite images in the background."""
    finished = Signal(dict)
    def __init__(self, processor: PromptProcessor):
        super().__init__()
        self.processor = processor
    @Slot()
    def run(self):
        try:
            # --- FIX: Explicitly reload history from disk to get the latest favorite statuses ---
            # This prevents the viewer from showing stale data.
            self.processor.history_manager.load_full_history()
            favorites = self.processor.history_manager.get_all_favorite_images()
            self.finished.emit({'success': True, 'data': favorites})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

class FavoriteItemWidget(QFrame, ImagePreviewMixin):
    """A custom widget for a single item in the favorites viewer."""
    def __init__(self, fav_data: Dict[str, Any], parent_viewer: 'FavoriteImagesViewer'):
        super().__init__()
        ImagePreviewMixin.__init__(self)
        self._init_image_preview_mixin(self)
        self.fav_data = fav_data
        self.parent_viewer = parent_viewer
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.full_image_path: Optional[str] = None
        self.img_label: Optional[QLabel] = None

        # Calculate full path
        relative_path = self.fav_data.get('image_path')
        workflow = self.fav_data.get('workflow_source', 'sfw')
        if relative_path and workflow:
            original_config_workflow = config.workflow
            config.workflow = workflow.lower()
            history_dir = config.get_history_file_dir()
            config.workflow = original_config_workflow # Restore immediately
            self.full_image_path = os.path.join(history_dir, relative_path)

    def set_image_label(self, label: QLabel):
        """Sets the image label and installs an event filter to watch for hovers."""
        self.img_label = label
        if self.img_label:
            self.img_label.setMouseTracking(True)
            self.img_label.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Filters events to show/hide preview only when hovering over the image label."""
        if obj == self.img_label:
            if event.type() == QEvent.Type.Enter:
                self._schedule_preview(self.fav_data)
                return True
            elif event.type() == QEvent.Type.Leave:
                self._schedule_hide()
                return True
        return super().eventFilter(obj, event)

    def _get_preview_image(self, item_data: Dict[str, Any]) -> Optional['Image.Image']:
        if self.full_image_path and os.path.exists(self.full_image_path):
            try:
        
                return Image.open(self.full_image_path)
            except Exception as e:
                print(f"Error loading preview image: {e}")

        return None

class FavoriteImagesViewer(QDialog, ImagePreviewMixin):
    """A dialog to view and manage all favorited images."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor):
        super().__init__(parent)
        ImagePreviewMixin.__init__(self)
        self.setWindowTitle("Favorite Images")
        self.parent_app = parent
        self.processor = processor
        self.favorite_widgets: List[FavoriteItemWidget] = []
        
        # --- NEW: Persistent worker for all thumbnails ---
        self.persistent_thumb_threads: List[QThread] = []
        self.persistent_thumb_workers: List[ThumbnailLoaderWorker] = []
        self.shared_thumb_job_queue = queue.Queue() # Shared queue for thumbnail jobs
        self._setup_persistent_thumbnail_worker() # Setup the workers
        
        self._create_widgets()
        self._start_loading_favorites()
        self.resize(1000, 800)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)
        self.loading_label = QLabel("Loading favorite images...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.loading_label)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.hide()
        main_layout.addWidget(self.scroll_area)
        container = QWidget()
        self.favorites_layout = QVBoxLayout(container)
        self.favorites_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(container)

    def _setup_persistent_thumbnail_worker(self):
        """Creates and starts a pool of long-lived worker threads for thumbnail loading."""
        num_workers = 2 # Number of concurrent thumbnail loaders, can be adjusted

        for i in range(num_workers):
            thread = ThumbnailThread() # Use our custom QThread subclass
            worker = ThumbnailLoaderWorker(self.processor, (200, 200), self.shared_thumb_job_queue) # Pass shared queue
            worker.moveToThread(thread)

            worker.thumbnail_ready.connect(self._on_thumbnail_ready)
            thread.started.connect(worker._timer.start) # Start the worker's timer when the thread starts
            worker.finished.connect(thread.quit)
            # Let the closeEvent handle deletion

            self.persistent_thumb_threads.append(thread)
            self.persistent_thumb_workers.append(worker)
            thread.start()

    def refresh_viewer(self):
        """Clears the current display and reloads all favorite images."""
        # Clear existing widgets
        for i in reversed(range(self.favorites_layout.count())):
            widget = self.favorites_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self.favorite_widgets.clear()
        self.thumbnail_queue.clear()
        
        # Show loading message and restart loading process
        self.loading_label.setText("Loading favorite images...")
        self.loading_label.show()
        self.scroll_area.hide()
        self._start_loading_favorites()

    def _start_loading_favorites(self):
        self.load_thread = QThread(self)
        self.load_worker = FavoriteLoaderWorker(self.processor)
        self.load_worker.moveToThread(self.load_thread)
        self.load_thread.started.connect(self.load_worker.run)
        self.load_worker.finished.connect(self._on_favorites_loaded)
        self.load_worker.finished.connect(self.load_thread.quit)
        # self.load_worker.finished.connect(self.load_worker.deleteLater) # Managed explicitly in closeEvent
        # self.load_thread.finished.connect(self.load_thread.deleteLater) # Managed explicitly in closeEvent
        self.load_thread.start()

    @Slot(dict)
    def _on_favorites_loaded(self, result: dict):
        self.loading_label.hide()
        if result['success']:
            self._populate_viewer(result['data'])
            self.scroll_area.show()
        else:
            QMessageBox.critical(self, "Error", f"Could not load favorites: {result['error']}")

    def _populate_viewer(self, favorites_data: List[Dict[str, Any]]):
        if not favorites_data:
            self.loading_label.setText("No favorite images found.")
            self.loading_label.show()
            return

        for fav_data in favorites_data:
            item_widget = FavoriteItemWidget(fav_data, self)
            item_frame = item_widget # Use the custom widget as the main frame
            item_layout = QHBoxLayout(item_frame)

            img_label = QLabel()
            img_label.setFixedSize(200, 200)
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_label.setStyleSheet("border: 1px solid gray;")
            item_widget.set_image_label(img_label) # Set the label for event filtering
            item_layout.addWidget(img_label)
            self._queue_thumbnail_load(img_label, fav_data.get('image_path'), fav_data.get('workflow_source'))

            info_frame = QWidget()
            info_layout = QVBoxLayout(info_frame)
            prompt_type = fav_data.get('prompt_type', 'N/A')
            prompt_label = QLabel(f"<b>Prompt ({prompt_type}):</b>")
            info_layout.addWidget(prompt_label)
            prompt_text = SmoothTextEdit(fav_data.get('prompt', ''))
            prompt_text.setReadOnly(True)
            prompt_text.setFixedHeight(100)
            info_layout.addWidget(prompt_text)
            gen_params = fav_data.get('generation_params', {})
            model_name = gen_params.get('model', {}).get('name', 'N/A')
            seed = gen_params.get('seed', 'N/A')
            params_label = QLabel(f"<b>Model:</b> {model_name} | <b>Seed:</b> {seed}")
            info_layout.addWidget(params_label)
            
            button_layout = QHBoxLayout()
            unfav_button = QPushButton("Unfavorite")
            unfav_button.clicked.connect(lambda checked=False, d=fav_data, w=item_widget: self._unfavorite_image(d, w))
            button_layout.addWidget(unfav_button)
            perm_button = QPushButton("Generate Permutations...")
            perm_button.clicked.connect(lambda checked=False, d=fav_data: self._generate_permutations(d))
            button_layout.addWidget(perm_button)
            button_layout.addStretch()
            info_layout.addLayout(button_layout)
            
            item_layout.addWidget(info_frame)
            self.favorites_layout.addWidget(item_frame)
            self.favorite_widgets.append(item_widget)

    def _queue_thumbnail_load(self, label: QLabel, image_path: Optional[str], workflow: Optional[str]):
        if label and image_path and workflow:
            # The ThumbnailLoaderWorker expects 'item' and 'workflow_source'
            job = {'item': label, 'image_path': image_path, 'workflow_source': workflow}
            self.shared_thumb_job_queue.put(job)




    @Slot(dict)
    def _on_thumbnail_ready(self, result: dict):
        label = result.get('item') # ThumbnailLoaderWorker passes the QLabel as 'item'
        qimage = result.get('thumb_image') # Corrected: ThumbnailLoaderWorker passes the QImage as 'thumb_image'
        if label and qimage:

            if not label.parent():
                print(f"WARNING: Label {label} has no parent, likely deleted. Skipping thumbnail update.")
                return
            pixmap = QPixmap.fromImage(qimage)
            label.setPixmap(pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _unfavorite_image(self, fav_data: Dict[str, Any], item_widget: FavoriteItemWidget):
        history_id = fav_data.get('history_id')
        image_path = fav_data.get('image_path')
        if not history_id or not image_path:
            QMessageBox.warning(self, "Error", "Missing data to unfavorite image.")
            return

        original_entry = self.processor.history_manager.get_entry_by_id(history_id)
        if not original_entry:
            QMessageBox.critical(self, "Error", "Could not find the original history entry. It may have been deleted.")
            item_widget.hide()
            item_widget.deleteLater()
            return

        updated_entry = copy.deepcopy(original_entry)
        image_found_and_updated = False

        image_lists_to_check = [updated_entry.get('original_images', [])]
        if 'enhanced' in updated_entry: image_lists_to_check.append(updated_entry['enhanced'].get('images', []))
        for var_data in updated_entry.get('variations', {}).values():
            image_lists_to_check.append(var_data.get('images', []))

        for img_list in image_lists_to_check:
            for img_data in img_list:
                if img_data.get('image_path') == image_path:
                    img_data['is_favorite'] = False
                    image_found_and_updated = True
                    break
            if image_found_and_updated: break

        if not image_found_and_updated:
            QMessageBox.critical(self, "Error", "Could not find the image within the original history entry.")
            return

        if self.processor.update_history_entry(original_entry, updated_entry):
            QMessageBox.information(self, "Success", "Image has been unfavorited.")
            item_widget.hide()
            item_widget.deleteLater()
            if self.parent_app.history_viewer_window and self.parent_app.history_viewer_window.isVisible():
                self.parent_app.history_viewer_window._start_loading_history()
        else:
            QMessageBox.critical(self, "Error", "Failed to update the history file.")

    def _generate_permutations(self, fav_data: Dict[str, Any]):
        prompt = fav_data.get('prompt')
        gen_params = fav_data.get('generation_params')
        if not prompt or not gen_params:
            QMessageBox.warning(self, "Error", "Missing prompt or generation data.")
            return
        
        dialog = ImageGenerationOptionsDialog(self, self.processor, prompt, initial_params=gen_params)
        if dialog.exec() != QDialog.Accepted: return

        options = dialog.get_options()
        selected_models_info = options.pop('models', [])
        if not selected_models_info:
            QMessageBox.warning(self, "No Models Selected", "You must select at least one model to generate images.")
            return

        generation_jobs = []
        num_images_per_model = options.pop('num_images', 1)
        base_seed = options.get('seed', random.randint(0, 2**32 - 1))
        save_to_gallery = options.get('save_to_gallery', config.save_to_gallery_by_default)

        for model_info in selected_models_info:
            for i in range(num_images_per_model):
                job_params = options.copy()
                job_params['model'] = model_info['model']
                job_params['loras'] = model_info.get('loras', [])
                job_params['negative_prompt'] = model_info['negative_prompt']
                job_params['seed'] = base_seed + i
                generation_jobs.append({'prompt': prompt, 'gen_params': job_params})

        def on_success(images_to_save: List[Dict[str, Any]]):
            if not images_to_save: return
            entry_id = str(uuid.uuid4())
            saved_images_data = [{'image_path': self.processor.save_generated_image(img['bytes'], entry_id), 'generation_params': img.get('generation_params')} for img in images_to_save]
            prompt_type = fav_data.get('prompt_type', 'favorite')
            original_prompt_text = fav_data.get('prompt', '')
            prompt_preview = (original_prompt_text[:30] + '...') if len(original_prompt_text) > 30 else original_prompt_text
            template_name = f"Permutation of '{prompt_type}' prompt: \"{prompt_preview}\""
            entry = {'id': entry_id, 'original_prompt': images_to_save[0]['prompt'], 'status': 'generated_only', 'original_images': saved_images_data, 'template_name': template_name}
            self.processor.history_manager.save_result(**entry)
            self.parent_app.status_bar.showMessage(f"{len(saved_images_data)} image(s) saved to history.", 5000)

        preview_dialog = MultiImagePreviewDialog(self, self.processor, generation_jobs, on_success, save_to_gallery=save_to_gallery)
        preview_dialog.exec()

    def closeEvent(self, event: QCloseEvent):
        """Ensures the parent app knows this window is closed and gracefully stops worker threads."""
        if self.processor.verbose: print("INFO: FavoriteImagesViewer closeEvent triggered.")

        # Gracefully shut down the persistent thumbnail workers
        num_workers = len(self.persistent_thumb_threads)
        if num_workers > 0:
            if self.processor.verbose: print(f"INFO: Shutting down {num_workers} thumbnail worker threads.")
            
            # Disconnect signals for persistent thumbnail workers and threads
            for i, worker in enumerate(self.persistent_thumb_workers):
                thread = self.persistent_thumb_threads[i]
                if worker and thread:
                    try:
                        worker.thumbnail_ready.disconnect(self._on_thumbnail_ready)
                        thread.started.disconnect(worker._timer.start)
                        worker.finished.disconnect(thread.quit)
                    except RuntimeError:
                        pass # Already disconnected or object gone
            
            # Signal workers to stop their timers
            for worker in self.persistent_thumb_workers:
                if worker:
                    worker.stop_timer_signal.emit()
            
            # Clear the queue to prevent workers from starting new jobs
            if self.processor.verbose: print("INFO: Clearing thumbnail job queue for FavoriteImagesViewer...")
            while not self.shared_thumb_job_queue.empty():
                try:
                    self.shared_thumb_job_queue.get_nowait()
                except queue.Empty:
                    break
                self.shared_thumb_job_queue.task_done()

            # Unblock all workers waiting on the queue by sending sentinel values
            if self.processor.verbose: print("INFO: Unblocking thumbnail worker threads for FavoriteImagesViewer...")
            for _ in range(num_workers):
                self.shared_thumb_job_queue.put(None)

            # Call worker.stop() to quit the event loop and emit finished
            for worker in self.persistent_thumb_workers:
                if worker:
                    worker.stop()

            # Wait for all threads to finish
            if self.processor.verbose: print("INFO: Waiting for thumbnail worker threads to terminate...")
            for thread in self.persistent_thumb_threads:
                if thread and thread.isRunning():
                    if not thread.wait(5000): # Wait 5s
                        print(f"WARNING: Thumbnail thread {thread} did not terminate gracefully. Terminating.")
                        thread.terminate() # Last resort
            if self.processor.verbose: print("INFO: All thumbnail worker threads have been processed.")

        # Schedule all thread and worker objects for deletion
        if self.processor.verbose: print("INFO: Scheduling threads and workers for deletion.")
        if self.load_thread:
            self.load_thread.deleteLater()
        if self.load_worker:
            self.load_worker.deleteLater()

        for worker in self.persistent_thumb_workers:
            if worker:
                worker.deleteLater()
        for thread in self.persistent_thumb_threads:
            if thread:
                thread.deleteLater()

        if self.parent_app and hasattr(self.parent_app, 'favorite_images_viewer_window'):
            self.parent_app.favorite_images_viewer_window = None
        
        if self.processor.verbose: print("INFO: FavoriteImagesViewer closeEvent finished.")
        super().closeEvent(event)