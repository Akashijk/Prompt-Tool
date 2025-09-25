"""A Qt dialog to preview multiple generated images and select which to keep."""

import copy
import time
import queue
import io
import os
import threading
import json
import uuid
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QSize, Qt, Signal, Slot, QThread, QEvent, QTimer, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QAction, QCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QProgressDialog,
    QGroupBox, QHBoxLayout, QLabel, QMenu, QScrollArea, QSizePolicy, QSpacerItem, QPushButton,
    QVBoxLayout, QWidget, QDialog
)
from PIL import Image
from PIL.ImageQt import ImageQt

from core.prompt_processor import PromptProcessor
from core.config import config
from .image_preview_mixin import ImagePreviewMixin
from .image_generation_dialog import ImageGenerationOptionsDialog
from .lora_permutation_dialog import LoraPermutationDialog

import random

class GenerationWorker(QObject):
    """
    A worker that processes jobs from a queue one by one. This is a more robust
    approach than the previous batch-based system, as it can handle jobs
    being added dynamically (e.g., for regenerations).
    """
    progress = Signal(dict)
    finished = Signal()

    def __init__(self, processor: PromptProcessor, job_queue: queue.Queue, save_to_gallery: bool, cancellation_event: threading.Event):
        super().__init__()
        self.processor = processor
        self.job_queue = job_queue
        self.save_to_gallery = save_to_gallery
        self.cancellation_event = cancellation_event
        self.current_model_name: Optional[str] = None

    @Slot()
    def run(self):
        """Processes jobs from the queue, handling model switching and exceptions robustly."""
        while not self.cancellation_event.is_set():
            job = None
            try:
                job = self.job_queue.get(timeout=1)
                if job is None: break

                try:
                    model_name = job.get('gen_params', {}).get('model', {}).get('name', 'Unknown')
                    if model_name != self.current_model_name:
                        if self.current_model_name is not None:
                            if self.processor.verbose:
                                print(f"INFO: Worker is switching from '{self.current_model_name}' to '{model_name}'. Clearing VRAM cache.")
                            self.processor.clear_invokeai_cache()
                            time.sleep(1.5)
                        self.current_model_name = model_name
                    
                    result_data = self.processor.generate_image_with_invokeai(gen_params=job['gen_params'], prompt=job['prompt'], save_to_gallery=self.save_to_gallery, cancellation_event=self.cancellation_event)
                    self.progress.emit({'success': True, 'job_id': job['id'], 'result': result_data})
                
                except Exception as e:
                    if not self.cancellation_event.is_set():
                        self.progress.emit({'success': False, 'job_id': job.get('id'), 'error': str(e)})
                
            except queue.Empty:
                continue
            finally:
                # Ensure task_done is called once per get(), even if processing fails.
                if job is not None:
                    self.job_queue.task_done()

        self.finished.emit()

class LoadingSpinner(QWidget):
    """A simple animated loading spinner widget."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_angle)
        self.setFixedSize(48, 48)

    def start(self):
        self.timer.start(20) # Update every 20ms

    def stop(self):
        self.timer.stop()

    def _update_angle(self):
        self.angle = (self.angle + 10) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#3498db"), 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawArc(rect, self.angle * 16, 120 * 16)

class ImageCard(QFrame, ImagePreviewMixin):
    """A widget to display a single image generation result."""
    def __init__(self, job: Dict[str, Any], parent_dialog: 'MultiImagePreviewDialog'):
        super().__init__()
        ImagePreviewMixin.__init__(self)
        self.job = job
        self.image_data: Optional[Dict[str, Any]] = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(276)

        layout = QVBoxLayout(self)
        
        # Container for image/spinner
        image_container = QFrame()
        image_container.setFixedSize(256, 256)
        image_container.setStyleSheet("border: 1px solid gray;")
        image_container_layout = QVBoxLayout(image_container)
        image_container_layout.setContentsMargins(0,0,0,0)
        image_container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spinner = LoadingSpinner(image_container)
        image_container_layout.addWidget(self.spinner)
        image_container_layout.addWidget(self.image_label)
        self.image_label.hide() # Hide image label initially
        layout.addWidget(image_container)

        model_name = job.get('gen_params', {}).get('model', {}).get('name', 'Unknown')
        self.info_label = QLabel(f"Model: {model_name}")
        self.info_label.setWordWrap(True)
        self.info_label.setMinimumHeight(40) # Reserve space
        layout.addWidget(self.info_label)

        # Bottom controls
        bottom_layout = QHBoxLayout()
        self.keep_checkbox = QCheckBox("Keep")
        self.keep_checkbox.setChecked(False) # Start unchecked, check on success
        bottom_layout.addWidget(self.keep_checkbox)
        bottom_layout.addStretch()
        self.regen_button = QPushButton("Regen")
        self.regen_button.setFixedWidth(60)
        self.regen_button.setEnabled(False)

        def on_regen_clicked():
            self._hide_preview() # Hide the preview first to prevent a lockup
            self.parent_dialog._regenerate_image(self)
        self.regen_button.clicked.connect(on_regen_clicked)

        bottom_layout.addWidget(self.regen_button)
        layout.addLayout(bottom_layout)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.parent_dialog = parent_dialog

    def set_generating(self):
        self.setMouseTracking(False)
        self.spinner.start()
        self.spinner.show()
        self.image_label.hide()
        self.regen_button.setEnabled(False)

    def set_image(self, image_bytes: bytes):
        self.spinner.stop()
        self.spinner.hide()
        pixmap = QPixmap()
        if pixmap.loadFromData(image_bytes):
            self.image_label.setPixmap(pixmap.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.image_label.setText("Failed to load image")
        self.image_label.show()
        self.regen_button.setEnabled(True)
        self.keep_checkbox.setChecked(True)
        self.setMouseTracking(True)
        
        # --- FIX: Update info label with new generation data ---
        gen_params = self.image_data.get('generation_params', {})
        model_name = gen_params.get('model', {}).get('name', 'Unknown')
        duration = gen_params.get('duration')
        duration_text = f" ({duration:.2f}s)" if duration else ""
        loras = gen_params.get('loras', [])
        
        # --- FIX: Display full LoRA details instead of just the count ---
        lora_text = ""
        if loras:
            lora_details = [f"{l.get('lora_object', {}).get('name', 'Unknown')} (w: {l.get('weight', 0.0):.2f})" for l in loras]
            lora_text = " | LoRAs: " + ", ".join(lora_details)
        self.info_label.setText(f"Model: {model_name}{duration_text}{lora_text}")

    def set_error(self, error_msg: str):
        self.spinner.stop()
        self.spinner.hide()
        self.image_label.show()
        self.image_label.setText(f"Error:\n{error_msg}")
        self.image_label.setWordWrap(True)
        self.keep_checkbox.setChecked(False)
        self.keep_checkbox.setEnabled(False)
        self.regen_button.setText("Retry")
        self.regen_button.setEnabled(True)

    def _show_context_menu(self, pos: QPoint):
        """Shows the context menu, delegating to the parent dialog."""
        # --- FIX: Hide the preview immediately when the context menu is requested ---
        self._hide_preview()
        self.parent_dialog.show_card_context_menu(self, self.mapToGlobal(pos))

    def enterEvent(self, event: QEvent):
        """Show preview on hover."""
        if self.image_data and self.image_data.get('full_path'):
            self._schedule_preview(self.image_data['full_path'])
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent):
        """Hide preview when mouse leaves."""
        self._hide_preview()
        super().leaveEvent(event)

class MultiImagePreviewDialog(QDialog):
    """A dialog to preview multiple generated images and select which to keep."""

    def __init__(self, parent, processor: PromptProcessor, generation_jobs: List[Dict[str, Any]], on_success_callback: Callable, save_to_gallery: bool):
        if processor.verbose:
            print(f"--- VERBOSE: MultiImagePreviewDialog.__init__ ENTERED ---")
        super().__init__(parent)
        
        self.setWindowTitle("Review Generated Images")
        self.processor = processor
        self.generation_jobs = generation_jobs
        self.on_success_callback = on_success_callback
        self.save_to_gallery_for_batch = save_to_gallery

        self.image_cards: Dict[str, ImageCard] = {}
        self.active_threads: List[QThread] = []
        self.cancellation_event = threading.Event()
        self.result: List[Dict[str, Any]] = []
        self.completed_job_count = 0

        # --- NEW: Centralized job queue for dynamic job submission ---
        self.job_queue = queue.Queue()
        self.cache_cleared_on_completion = False


        self._create_widgets()
        self._start_generation()

        self.resize(1200, 800)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception: pass

    def _remove_thread(self, thread_to_remove: QThread):
        """Safely removes a thread from the active list when it finishes."""
        try:
            self.active_threads.remove(thread_to_remove)
        except ValueError:
            # This can happen if the thread was already removed, which is fine.
            pass
    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        # Toolbar
        toolbar_layout = QHBoxLayout()
        toggle_all_button = QPushButton("Toggle All")
        toggle_all_button.clicked.connect(self._toggle_all_checkboxes)

        # --- FIX: Add the "Add New Image..." button to the toolbar ---
        add_new_button = QPushButton("Add New Image...")
        add_new_button.clicked.connect(self._add_new_image)
        toolbar_layout.addWidget(add_new_button)

        toolbar_layout.addWidget(toggle_all_button)
        toolbar_layout.addStretch()
        main_layout.addLayout(toolbar_layout)

        # Prompt Display
        if self.generation_jobs:
            prompt_group = QGroupBox("Generating with Prompt")
            prompt_layout = QVBoxLayout(prompt_group)
            first_prompt = self.generation_jobs[0].get('prompt', 'No prompt')
            prompt_label = QLabel(first_prompt)
            prompt_label.setWordWrap(True)
            prompt_layout.addWidget(prompt_label)
            main_layout.addWidget(prompt_group)

        # Scrollable Grid for Images
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll_area.setWidget(self.grid_widget)
        main_layout.addWidget(scroll_area, 1)

        self._populate_grid()

        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Keep Selected")
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("Discard All")
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

    def _populate_grid(self):
        """Populates the grid with image cards."""
        cols = 4
        for i, job in enumerate(self.generation_jobs):
            job_id = str(uuid.uuid4())
            job['id'] = job_id
            card = ImageCard(job, self)
            self.image_cards[job_id] = card
            row, col = divmod(i, cols)
            self.grid_layout.addWidget(card, row, col)

    def _start_generation(self):
        """Starts the generation process by grouping jobs and processing the first batch."""
        # Set the initial state for all cards
        for card in self.image_cards.values():
            card.set_generating()

        # --- NEW: Group jobs by model and add to queue in order ---
        jobs_by_model: Dict[str, List[Dict[str, Any]]] = {}
        for job in self.generation_jobs:
            model_name = job.get('gen_params', {}).get('model', {}).get('name', 'Unknown Model')
            if model_name not in jobs_by_model:
                jobs_by_model[model_name] = []
            jobs_by_model[model_name].append(job)

        for model_name in sorted(jobs_by_model.keys()):
            for job in jobs_by_model[model_name]:
                self.job_queue.put(job)

        # --- NEW: Start a persistent worker thread ---
        self.worker_thread = QThread(self)
        self.generation_worker = GenerationWorker(self.processor, self.job_queue, self.save_to_gallery_for_batch, self.cancellation_event)
        self.generation_worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.generation_worker.run)
        self.generation_worker.progress.connect(self._on_generation_finished)
        self.generation_worker.finished.connect(self._on_batch_complete)
        self.generation_worker.finished.connect(self.worker_thread.quit)

        self.active_threads.append(self.worker_thread)
        self.worker_thread.start()

    @Slot()
    def _on_batch_complete(self):
        """Called when all jobs in the initial batch are finished."""
        self.setWindowTitle("Review Generated Images (Complete)")
        if not self.cache_cleared_on_completion:
            self.processor.clear_invokeai_cache_async()
            self.cache_cleared_on_completion = True
        
        parent = self.parent()
        if hasattr(parent, 'on_image_generation_complete'):
            parent.on_image_generation_complete()

    @Slot(dict)
    def _on_generation_finished(self, result: dict):
        job_id = result.get('job_id')
        
        if job_id not in self.image_cards:
            return

        card = self.image_cards[job_id]
        
        if result['success']:
            image_data = result['result']
            card.image_data = image_data
            
            # --- NEW: Store the full image path for the previewer ---
            # The image bytes are in memory, but to show a preview popup, we need a path.
            # We'll save a temporary file in the cache directory for the popup to use.
            cache_dir = os.path.join(config.CACHE_DIR, 'previews')
            os.makedirs(cache_dir, exist_ok=True)
            
            # Use a unique name for the temporary preview file.
            temp_filename = f"preview_{job_id}.png"
            full_path = os.path.join(cache_dir, temp_filename)
            with open(full_path, 'wb') as f:
                f.write(image_data['bytes'])
            card.image_data['full_path'] = full_path

            if image_data and 'bytes' in image_data:
                card.set_image(image_data['bytes'])
            else:
                card.set_error("No image data received")
            
        else:
            error_msg = result.get('error', 'Unknown error')
            card.set_error(error_msg)


    @Slot()
    def _on_accept(self):
        """Handles the 'Keep Selected' button click."""
        kept_images = []
        for card in self.image_cards.values():
            if card.keep_checkbox.isChecked() and card.image_data:
                kept_images.append(card.image_data)
        self.result = kept_images
        if kept_images:
            self.on_success_callback(kept_images)
        
        self.accept()

    def show_card_context_menu(self, card: ImageCard, global_pos: QPoint):
        """Creates and shows the context menu for a specific image card."""
        menu = QMenu(self)
        has_image = card.image_data is not None

        regen_action = QAction("Regenerate with new seed", self)
        regen_action.setEnabled(has_image)
        regen_action.triggered.connect(lambda: self._regenerate_image(card))
        menu.addAction(regen_action)

        edit_action = QAction("Edit & Regenerate...", self)
        edit_action.setEnabled(has_image)
        edit_action.triggered.connect(lambda: self._edit_and_regenerate_image(card))
        menu.addAction(edit_action)

        perm_action = QAction("Generate LoRA Permutations...", self)
        perm_action.setEnabled(has_image)
        perm_action.triggered.connect(lambda: self._generate_lora_permutations(card))
        menu.addAction(perm_action)

        menu.addSeparator()
        discard_action = QAction("Discard", self)
        discard_action.triggered.connect(lambda: self._discard_image(card))
        menu.addAction(discard_action)

        menu.exec(global_pos)

    def _regenerate_image(self, card_to_regen: ImageCard):
        """Creates a new job to regenerate an image with a new seed."""
        # --- FIX: Create a completely new job for regeneration ---
        # The previous logic modified the existing job, which could lead to race conditions.
        # This new approach creates a new, unique job and replaces the old one.
        old_job = card_to_regen.job
        new_gen_params = copy.deepcopy(old_job['gen_params'])
        new_gen_params['seed'] = random.randint(0, 2**32 - 1)

        new_job = {
            'prompt': old_job['prompt'],
            'gen_params': new_gen_params,
            'id': str(uuid.uuid4()) # A new unique ID for the new job
        }

        # Replace the old job with the new one on the card and start it.
        self._replace_card_job(card_to_regen, new_job)

    def _edit_and_regenerate_image(self, card_to_edit: ImageCard):
        """Opens the options dialog to edit and regenerate an image."""
        image_data = card_to_edit.image_data
        if not image_data:
            QMessageBox.warning(self, "Error", "Cannot regenerate, image data is missing.")
            return

        prompt = card_to_edit.job['prompt']
        initial_params = image_data.get('generation_params', {})
        dialog = ImageGenerationOptionsDialog(self, self.processor, prompt, initial_params=initial_params, is_editing=True)
        if dialog.exec() != QDialog.Accepted:
            return

        options = dialog.get_options()
        new_models_info = options.pop('models', [])
        if not new_models_info:
            return

        try:
            # Find the index of the card in the grid layout for insertion
            idx = self.grid_layout.indexOf(card_to_edit)
            if idx == -1: raise ValueError("Card not in layout")
            row, col, _, _ = self.grid_layout.getItemPosition(idx)
            index_to_replace = row * self.grid_layout.columnCount() + col
        except ValueError:
            QMessageBox.critical(self, "Error", "Could not find the image card to replace.")
            return

        # 1. Handle the first selected model: it replaces the original card.
        first_model_info = new_models_info.pop(0)
        first_new_gen_params = options.copy()
        first_new_gen_params['model'] = first_model_info['model']
        first_new_gen_params['loras'] = first_model_info.get('loras', [])
        # --- FIX: Ensure the negative prompt from the override is used ---
        # The previous code was missing this, causing the global negative prompt
        first_new_gen_params['negative_prompt'] = first_model_info.get('negative_prompt', '')
        self._replace_card_job(card_to_edit, {'prompt': prompt, 'gen_params': first_new_gen_params, 'id': str(uuid.uuid4())})

        # 2. Handle additional models: insert them as new cards.
        if new_models_info:
            jobs_to_add = []
            for model_info in new_models_info:
                new_gen_params = options.copy()
                new_gen_params['model'] = model_info['model']
                new_gen_params['loras'] = model_info.get('loras', [])
                new_gen_params['negative_prompt'] = model_info['negative_prompt']
                new_job = {'prompt': prompt, 'gen_params': new_gen_params, 'id': str(uuid.uuid4())}
                jobs_to_add.append(new_job)

            for new_job in jobs_to_add:
                self.generation_jobs.append(new_job)
                self._add_job_to_grid(new_job)
                self.job_queue.put(new_job)
            self._reflow_grid_layout() # Reflow after adding all new jobs

    def _generate_lora_permutations(self, card: ImageCard):
        """Opens a dialog to generate permutations of an image with different LoRAs."""
        image_data = card.image_data
        if not image_data or not image_data.get('generation_params'):
            QMessageBox.warning(self, "Error", "No generation parameters found for this image.")
            return

        dialog = LoraPermutationDialog(self, self.processor, image_data['generation_params'])
        if dialog.exec() != QDialog.Accepted or not dialog.result:
            return

        lora_permutations = dialog.result
        original_prompt = card.job['prompt']
        base_gen_params = image_data['generation_params']

        jobs_to_add = []
        for perm_loras in lora_permutations:
            new_gen_params = copy.deepcopy(base_gen_params)
            new_gen_params['loras'] = perm_loras
            new_job = {
                'prompt': original_prompt,
                'gen_params': new_gen_params,
                'id': str(uuid.uuid4())
            }
            jobs_to_add.append(new_job)

        # --- FIX: Insert new permutation jobs next to the source image ---
        try:
            index_to_insert_after = self.generation_jobs.index(card.job)
        except ValueError:
            index_to_insert_after = len(self.generation_jobs) - 1

        for i, new_job in enumerate(jobs_to_add):
            insertion_index = index_to_insert_after + 1 + i
            self.generation_jobs.insert(insertion_index, new_job)
            self._add_job_to_grid(new_job)
            self.job_queue.put(new_job)
        self._reflow_grid_layout()


    def _add_new_image(self):
        """Opens the options dialog to add a new image to the batch."""
        if not self.generation_jobs:
            QMessageBox.warning(self, "Error", "No existing job to base new image on.")
            return

        # Use the first job's parameters as a starting point
        base_job = self.generation_jobs[0]
        prompt = base_job['prompt']
        initial_params = base_job['gen_params']

        dialog = ImageGenerationOptionsDialog(self, self.processor, prompt, initial_params=initial_params, is_editing=False)
        if dialog.exec() != QDialog.Accepted:
            return

        options = dialog.get_options()
        new_models_info = options.pop('models', [])
        if not new_models_info:
            return

        num_images_per_model = options.pop('num_images', 1)
        base_seed = options.get('seed', random.randint(0, 2**32 - 1))

        for model_info in new_models_info:
            for i in range(num_images_per_model):
                new_gen_params = options.copy()
                new_gen_params['model'] = model_info['model']
                new_gen_params['loras'] = model_info.get('loras', [])
                new_gen_params['negative_prompt'] = model_info['negative_prompt']
                new_gen_params['seed'] = base_seed + i
                new_job = {'prompt': prompt, 'gen_params': new_gen_params, 'id': str(uuid.uuid4())}
                self.generation_jobs.append(new_job)
                self._add_job_to_grid(new_job)
                self.job_queue.put(new_job)
        self._reflow_grid_layout()

    def _discard_image(self, card_to_discard: ImageCard, reflow: bool = True):
        """Removes an image card from the view and cancels its job if running."""
        job_id = card_to_discard.job['id']
        self.grid_layout.removeWidget(card_to_discard)
        card_to_discard.deleteLater()
        if job_id in self.image_cards:
            del self.image_cards[job_id] # type: ignore

        # Also remove from the master job list
        job_to_discard = next((j for j in self.generation_jobs if j.get('id') == job_id), None)
        if job_to_discard:
            job_to_discard['discarded'] = True # Mark as discarded for any running workers
            self.generation_jobs.remove(job_to_discard)

        if reflow:
            self._reflow_grid_layout()

    def _add_job_to_grid(self, job: Dict[str, Any]):
        """Adds a new placeholder card for a job and starts its generation."""
        card = ImageCard(job, self)
        self.image_cards[job['id']] = card
        card.set_generating()
        self._start_single_job(card)

    def _start_single_job(self, card: ImageCard):
        """Starts a background worker for a single new job."""
        card.set_generating()
        # The queue.Queue methods are already thread-safe. Do not access mutex directly.
        # If high_priority is needed, a PriorityQueue should be used, or a custom queue.
        # For now, just put the job in the queue.
        self.job_queue.put(card.job)

    def _replace_card_job(self, card: ImageCard, new_job: Dict[str, Any]):
        """Replaces the job on an existing card and starts generation."""
        old_job_id = card.job['id']
        new_job_id = new_job['id']

        # Update the master job list
        try:
            idx = next(i for i, j in enumerate(self.generation_jobs) if j['id'] == old_job_id)
            self.generation_jobs[idx] = new_job
        except ValueError:
            self.generation_jobs.append(new_job)

        # Update the card and the dictionary mapping
        card.job = new_job
        card.set_generating()
        self.image_cards[new_job_id] = self.image_cards.pop(old_job_id)
        self.job_queue.put(new_job)



    def _reflow_grid_layout(self):
        """Clears and re-populates the grid layout based on the current image_cards."""
        
        # Clear the layout without deleting the widgets
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child and child.widget():
                child.widget().setParent(None)

        cols = max(1, self.grid_widget.width() // 280) if self.grid_widget.width() > 0 else 4
        for i, job in enumerate(self.generation_jobs):
            card = self.image_cards.get(job['id'])
            if not card: continue
            row, col = divmod(i, cols)
            self.grid_layout.addWidget(card, row, col)

        # Add spacers to keep cards aligned to the left
        self.grid_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum), 0, cols)
        self.grid_layout.setRowStretch(self.grid_layout.rowCount(), 1)

    def resizeEvent(self, event: QEvent):
        """Handle window resize to reflow the grid."""
        super().resizeEvent(event)
        self._reflow_grid_layout()

    @Slot()
    def _toggle_all_checkboxes(self):
        """Toggles the 'keep' checkbox for all successfully generated images."""
        valid_cards = [card for card in self.image_cards.values() if card.image_data]
        if not valid_cards: 
            return

        # If any are unchecked, the new state is checked. Otherwise, uncheck all.
        new_state = any(not card.keep_checkbox.isChecked() for card in valid_cards)
        for card in valid_cards:
            card.keep_checkbox.setChecked(new_state)

    def resizeEvent(self, event: QEvent):
        """Handle window resize to reflow the grid."""
        super().resizeEvent(event)
        self._reflow_grid_layout()

    def closeEvent(self, event):
        """Handle window close event to stop threads."""
        
        # Signal cancellation
        if not self.cancellation_event.is_set():
            self.cancellation_event.set()
            # Unblock the worker thread if it's waiting on the queue
            self.job_queue.put(None)

        for thread in self.active_threads:
            if thread.isRunning():
                thread.quit()
                thread.wait(3000) # Wait up to 3 seconds

        # Clean up the worker object
        if hasattr(self, 'generation_worker'):
            self.generation_worker.deleteLater()
        active_jobs = [job['gen_params'].get('item_id') for job in self.generation_jobs if job.get('gen_params', {}).get('item_id')]
        if active_jobs:
            print(f"INFO: Cancelling {len(active_jobs)} active/queued InvokeAI jobs.")
            for item_id in active_jobs:
                self.processor.invokeai_client.cancel_and_cleanup_item(item_id, self.save_to_gallery_for_batch)

        # Clean up temporary preview images on close
        cache_dir = os.path.join(config.CACHE_DIR, 'previews')
        if os.path.exists(cache_dir):
            for card in self.image_cards.values():
                temp_filename = f"preview_{card.job['id']}.png"
                temp_path = os.path.join(cache_dir, temp_filename)
                if os.path.exists(temp_path):
                    try: os.remove(temp_path)
                    except OSError: pass

        # --- NEW: Clear InvokeAI VRAM cache on close ---
        if hasattr(self.processor, 'is_invokeai_connected') and self.processor.is_invokeai_connected():
            if hasattr(self.processor, 'clear_invokeai_cache_async'):
                self.processor.clear_invokeai_cache_async()

        parent = self.parent()
        if hasattr(parent, 'image_preview_dialogs') and self in parent.image_preview_dialogs:
            parent.image_preview_dialogs.remove(self)

        super().closeEvent(event)

    def _start_generation(self):
        """Starts the generation process by grouping jobs and processing the first batch."""
        # Set the initial state for all cards
        for card in self.image_cards.values():
            card.set_generating()

        # --- NEW: Group jobs by model and add to queue in order ---
        jobs_by_model: Dict[str, List[Dict[str, Any]]] = {}
        for job in self.generation_jobs:
            model_name = job.get('gen_params', {}).get('model', {}).get('name', 'Unknown Model')
            if model_name not in jobs_by_model:
                jobs_by_model[model_name] = []
            jobs_by_model[model_name].append(job)

        for model_name in sorted(jobs_by_model.keys()):
            for job in jobs_by_model[model_name]:
                self.job_queue.put(job)

        # --- NEW: Start a persistent worker thread ---
        self.worker_thread = QThread(self)
        self.generation_worker = GenerationWorker(self.processor, self.job_queue, self.save_to_gallery_for_batch, self.cancellation_event)
        self.generation_worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.generation_worker.run)
        self.generation_worker.progress.connect(self._on_generation_finished)
        self.generation_worker.finished.connect(self._on_batch_complete)
        self.generation_worker.finished.connect(self.worker_thread.quit)

        self.active_threads.append(self.worker_thread)
        self.worker_thread.start()

    @Slot()
    def _on_batch_complete(self):
        """Called when all jobs in the initial batch are finished."""
        self.setWindowTitle("Review Generated Images (Complete)")
        if not self.cache_cleared_on_completion:
            self.processor.clear_invokeai_cache_async()
            self.cache_cleared_on_completion = True

    @Slot(dict)
    def _on_generation_finished(self, result: dict):
        job_id = result.get('job_id')
        
        if job_id not in self.image_cards:
            return

        card = self.image_cards[job_id]
        
        if result['success']:
            image_data = result['result']
            card.image_data = image_data
            
            # --- NEW: Store the full image path for the previewer ---
            # The image bytes are in memory, but to show a preview popup, we need a path.
            # We'll save a temporary file in the cache directory for the popup to use.
            cache_dir = os.path.join(config.CACHE_DIR, 'previews')
            os.makedirs(cache_dir, exist_ok=True)
            
            # Use a unique name for the temporary preview file.
            temp_filename = f"preview_{job_id}.png"
            full_path = os.path.join(cache_dir, temp_filename)
            with open(full_path, 'wb') as f:
                f.write(image_data['bytes'])
            card.image_data['full_path'] = full_path

            if image_data and 'bytes' in image_data:
                card.set_image(image_data['bytes'])
            else:
                card.set_error("No image data received")
            
        else:
            error_msg = result.get('error', 'Unknown error')
            card.set_error(error_msg)


    @Slot()
    def _on_accept(self):
        """Handles the 'Keep Selected' button click."""
        kept_images = []
        for card in self.image_cards.values():
            if card.keep_checkbox.isChecked() and card.image_data:
                kept_images.append(card.image_data)
        self.result = kept_images
        if kept_images:
            self.on_success_callback(kept_images)
        
        self.accept()

    def show_card_context_menu(self, card: ImageCard, global_pos: QPoint):
        """Creates and shows the context menu for a specific image card."""
        menu = QMenu(self)
        has_image = card.image_data is not None

        regen_action = QAction("Regenerate with new seed", self)
        regen_action.setEnabled(has_image)
        regen_action.triggered.connect(lambda: self._regenerate_image(card))
        menu.addAction(regen_action)

        edit_action = QAction("Edit & Regenerate...", self)
        edit_action.setEnabled(has_image)
        edit_action.triggered.connect(lambda: self._edit_and_regenerate_image(card))
        menu.addAction(edit_action)

        perm_action = QAction("Generate LoRA Permutations...", self)
        perm_action.setEnabled(has_image)
        perm_action.triggered.connect(lambda: self._generate_lora_permutations(card))
        menu.addAction(perm_action)

        menu.addSeparator()
        discard_action = QAction("Discard", self)
        discard_action.triggered.connect(lambda: self._discard_image(card))
        menu.addAction(discard_action)

        menu.exec(global_pos)

    def _regenerate_image(self, card_to_regen: ImageCard):
        """Creates a new job to regenerate an image with a new seed."""
        # --- FIX: Create a completely new job for regeneration ---
        # The previous logic modified the existing job, which could lead to race conditions.
        # This new approach creates a new, unique job and replaces the old one.
        old_job = card_to_regen.job
        new_gen_params = copy.deepcopy(old_job['gen_params'])
        new_gen_params['seed'] = random.randint(0, 2**32 - 1)

        new_job = {
            'prompt': old_job['prompt'],
            'gen_params': new_gen_params,
            'id': str(uuid.uuid4()) # A new unique ID for the new job
        }

        # Replace the old job with the new one on the card and start it.
        self._replace_card_job(card_to_regen, new_job)

    def _edit_and_regenerate_image(self, card_to_edit: ImageCard):
        """Opens the options dialog to edit and regenerate an image."""
        image_data = card_to_edit.image_data
        if not image_data:
            QMessageBox.warning(self, "Error", "Cannot regenerate, image data is missing.")
            return

        prompt = card_to_edit.job['prompt']
        initial_params = image_data.get('generation_params', {})
        dialog = ImageGenerationOptionsDialog(self, self.processor, prompt, initial_params=initial_params, is_editing=True)
        if dialog.exec() != QDialog.Accepted:
            return

        options = dialog.get_options()
        new_models_info = options.pop('models', [])
        if not new_models_info:
            return

        try:
            # Find the index of the card in the grid layout for insertion
            idx = self.grid_layout.indexOf(card_to_edit)
            if idx == -1: raise ValueError("Card not in layout")
            row, col, _, _ = self.grid_layout.getItemPosition(idx)
            index_to_replace = row * self.grid_layout.columnCount() + col
        except ValueError:
            QMessageBox.critical(self, "Error", "Could not find the image card to replace.")
            return

        # 1. Handle the first selected model: it replaces the original card.
        first_model_info = new_models_info.pop(0)
        first_new_gen_params = options.copy()
        first_new_gen_params['model'] = first_model_info['model']
        first_new_gen_params['loras'] = first_model_info.get('loras', [])
        # --- FIX: Ensure the negative prompt from the override is used ---
        # The previous code was missing this, causing the global negative prompt
        first_new_gen_params['negative_prompt'] = first_model_info.get('negative_prompt', '')
        self._replace_card_job(card_to_edit, {'prompt': prompt, 'gen_params': first_new_gen_params, 'id': str(uuid.uuid4())})

        # 2. Handle additional models: insert them as new cards.
        if new_models_info:
            jobs_to_add = []
            for model_info in new_models_info:
                new_gen_params = options.copy()
                new_gen_params['model'] = model_info['model']
                new_gen_params['loras'] = model_info.get('loras', [])
                new_gen_params['negative_prompt'] = model_info['negative_prompt']
                new_job = {'prompt': prompt, 'gen_params': new_gen_params, 'id': str(uuid.uuid4())}
                jobs_to_add.append(new_job)

            for new_job in jobs_to_add:
                self.generation_jobs.append(new_job)
                self._add_job_to_grid(new_job)
                self.job_queue.put(new_job)
            self._reflow_grid_layout() # Reflow after adding all new jobs

    def _generate_lora_permutations(self, card: ImageCard):
        """Opens a dialog to generate permutations of an image with different LoRAs."""
        image_data = card.image_data
        if not image_data or not image_data.get('generation_params'):
            QMessageBox.warning(self, "Error", "No generation parameters found for this image.")
            return

        dialog = LoraPermutationDialog(self, self.processor, image_data['generation_params'])
        if dialog.exec() != QDialog.Accepted or not dialog.result:
            return

        lora_permutations = dialog.result
        original_prompt = card.job['prompt']
        base_gen_params = image_data['generation_params']

        jobs_to_add = []
        for perm_loras in lora_permutations:
            new_gen_params = copy.deepcopy(base_gen_params)
            new_gen_params['loras'] = perm_loras
            new_job = {
                'prompt': original_prompt,
                'gen_params': new_gen_params,
                'id': str(uuid.uuid4())
            }
            jobs_to_add.append(new_job)

        # --- FIX: Insert new permutation jobs next to the source image ---
        try:
            index_to_insert_after = self.generation_jobs.index(card.job)
        except ValueError:
            index_to_insert_after = len(self.generation_jobs) - 1

        for i, new_job in enumerate(jobs_to_add):
            insertion_index = index_to_insert_after + 1 + i
            self.generation_jobs.insert(insertion_index, new_job)
            self._add_job_to_grid(new_job)
            self.job_queue.put(new_job)
        self._reflow_grid_layout()


    def _add_new_image(self):
        """Opens the options dialog to add a new image to the batch."""
        if not self.generation_jobs:
            QMessageBox.warning(self, "Error", "No existing job to base new image on.")
            return

        # Use the first job's parameters as a starting point
        base_job = self.generation_jobs[0]
        prompt = base_job['prompt']
        initial_params = base_job['gen_params']

        dialog = ImageGenerationOptionsDialog(self, self.processor, prompt, initial_params=initial_params, is_editing=False)
        if dialog.exec() != QDialog.Accepted:
            return

        options = dialog.get_options()
        new_models_info = options.pop('models', [])
        if not new_models_info:
            return

        num_images_per_model = options.pop('num_images', 1)
        base_seed = options.get('seed', random.randint(0, 2**32 - 1))

        for model_info in new_models_info:
            for i in range(num_images_per_model):
                new_gen_params = options.copy()
                new_gen_params['model'] = model_info['model']
                new_gen_params['loras'] = model_info.get('loras', [])
                new_gen_params['negative_prompt'] = model_info['negative_prompt']
                new_gen_params['seed'] = base_seed + i
                new_job = {'prompt': prompt, 'gen_params': new_gen_params, 'id': str(uuid.uuid4())}
                self.generation_jobs.append(new_job)
                self._add_job_to_grid(new_job)
                self.job_queue.put(new_job)
        self._reflow_grid_layout()

    def _discard_image(self, card_to_discard: ImageCard, reflow: bool = True):
        """Removes an image card from the view and cancels its job if running."""
        job_id = card_to_discard.job['id']
        self.grid_layout.removeWidget(card_to_discard)
        card_to_discard.deleteLater()
        if job_id in self.image_cards:
            del self.image_cards[job_id] # type: ignore

        # Also remove from the master job list
        job_to_discard = next((j for j in self.generation_jobs if j.get('id') == job_id), None)
        if job_to_discard:
            job_to_discard['discarded'] = True # Mark as discarded for any running workers
            self.generation_jobs.remove(job_to_discard)

        if reflow:
            self._reflow_grid_layout()

    def _add_job_to_grid(self, job: Dict[str, Any]):
        """Adds a new placeholder card for a job and starts its generation."""
        card = ImageCard(job, self)
        self.image_cards[job['id']] = card
        card.set_generating()



    def _replace_card_job(self, card: ImageCard, new_job: Dict[str, Any]):
        """Replaces the job on an existing card and starts generation."""
        old_job_id = card.job['id']
        new_job_id = new_job['id']

        # Update the master job list
        try:
            idx = next(i for i, j in enumerate(self.generation_jobs) if j['id'] == old_job_id)
            self.generation_jobs[idx] = new_job
        except ValueError:
            self.generation_jobs.append(new_job)

        # Update the card and the dictionary mapping
        card.job = new_job
        card.set_generating()
        self.image_cards[new_job_id] = self.image_cards.pop(old_job_id)
        self.job_queue.put(new_job)



    def _set_initial_size_and_position(self):
        """Sets the initial size and position of the dialog."""
        num_jobs = len(self.generation_jobs)
        if num_jobs == 0:
            self.resize(300, 200)
            return

        cols = min(num_jobs, 4)
        rows = (num_jobs + cols - 1) // cols
        card_width = 276 + self.grid_layout.horizontalSpacing()
        card_height = 400 + self.grid_layout.verticalSpacing()

        new_width = cols * card_width + self.layout().contentsMargins().left() + self.layout().contentsMargins().right() + 70
        new_height = rows * card_height + self.layout().contentsMargins().top() + self.layout().contentsMargins().bottom() + 250

        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            max_width = screen_geometry.width() * 0.95
            max_height = screen_geometry.height() * 0.9
            new_width = min(new_width, int(max_width))
            new_height = min(new_height, int(max_height))
        except Exception:
            pass

        self.resize(new_width, new_height)

        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass

    def _reflow_grid_layout(self):
        """Clears and re-populates the grid layout based on the current image_cards."""
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child and child.widget():
                child.widget().setParent(None)

        cols = max(1, self.grid_widget.width() // 280) if self.grid_widget.width() > 0 else min(len(self.generation_jobs), 4)
        for i, job in enumerate(self.generation_jobs):
            card = self.image_cards.get(job['id'])
            if not card: continue
            row, col = divmod(i, cols)
            self.grid_layout.addWidget(card, row, col)

        self.grid_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum), 0, cols)
        self.grid_layout.setRowStretch(self.grid_layout.rowCount(), 1)

    @Slot()
    def _toggle_all_checkboxes(self):
        """Toggles the 'keep' checkbox for all successfully generated images."""
        valid_cards = [card for card in self.image_cards.values() if card.image_data]
        if not valid_cards: 
            return

        # If any are unchecked, the new state is checked. Otherwise, uncheck all.
        new_state = any(not card.keep_checkbox.isChecked() for card in valid_cards)
        for card in valid_cards:
            card.keep_checkbox.setChecked(new_state)

    def resizeEvent(self, event: QEvent):
        """Handle window resize to reflow the grid."""
        super().resizeEvent(event)
        self._reflow_grid_layout()

    def closeEvent(self, event):
        """Handle window close event to stop threads."""
        
        # Signal cancellation
        if not self.cancellation_event.is_set():
            self.cancellation_event.set()
            # Unblock the worker thread if it's waiting on the queue
            self.job_queue.put(None)

        for thread in self.active_threads:
            if thread.isRunning():
                thread.quit()
                thread.wait(3000) # Wait up to 3 seconds

        # Clean up the worker object
        if hasattr(self, 'generation_worker'):
            self.generation_worker.deleteLater()
        active_jobs = [job['gen_params'].get('item_id') for job in self.generation_jobs if job.get('gen_params', {}).get('item_id')]
        if active_jobs:
            print(f"INFO: Cancelling {len(active_jobs)} active/queued InvokeAI jobs.")
            for item_id in active_jobs:
                self.processor.invokeai_client.cancel_and_cleanup_item(item_id, self.save_to_gallery_for_batch)

        # Clean up temporary preview images on close
        cache_dir = os.path.join(config.CACHE_DIR, 'previews')
        if os.path.exists(cache_dir):
            for card in self.image_cards.values():
                temp_filename = f"preview_{card.job['id']}.png"
                temp_path = os.path.join(cache_dir, temp_filename)
                if os.path.exists(temp_path):
                    try: os.remove(temp_path)
                    except OSError: pass

        # --- NEW: Clear InvokeAI VRAM cache on close ---
        if hasattr(self.processor, 'is_invokeai_connected') and self.processor.is_invokeai_connected():
            if hasattr(self.processor, 'clear_invokeai_cache_async'):
                self.processor.clear_invokeai_cache_async()

        super().closeEvent(event)