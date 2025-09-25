"""A Qt-based pop-up window to display enhancement results."""

import random
import sys
from typing import Optional, List, Dict, Any, Callable, TYPE_CHECKING
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QGroupBox, QScrollArea, QMessageBox
)
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt

from core.prompt_processor import PromptProcessor
if TYPE_CHECKING:
    from .multi_image_preview_dialog import MultiImagePreviewDialog
    from .gui_app import GUIApp
    from .image_generation_dialog import ImageGenerationOptionsDialog


class EnhancementWorker(QObject):
    """Worker to run the enhancement batch process in the background."""
    # Signal signature: key (e.g., 'enhanced'), data (the prompt dict)
    result_ready = Signal(str, dict)
    batch_finished = Signal()

    def __init__(self, parent, processor: PromptProcessor, prompt: str, model: str, variations: List[str]):
        super().__init__()
        self.processor = processor
        self.prompt = prompt
        self.model = model
        self.variations = variations

    @Slot()
    def run(self):
        """The main work method."""
        try:
            # The processor's batch method needs a list of prompts.
            # We pass this worker's signal emitter as the callback.
            self.processor.process_enhancement_batch(
                prompts=[self.prompt],
                model=self.model,
                selected_variations=self.variations,
                result_callback=self.result_ready.emit
            )
        except Exception as e:
            # Emit an error signal if something goes wrong
            error_data = {'prompt': f"Error during enhancement: {e}"}
            self.result_ready.emit('error', error_data)
        finally:
            self.batch_finished.emit()

class SingleEnhancementWorker(QObject):
    """Worker to regenerate a single prompt part."""
    result_ready = Signal(str, dict)
    finished = Signal()

    def __init__(self, parent, processor: PromptProcessor, original_prompt: str, enhanced_prompt: str, model: str, key_to_regenerate: str):
        super().__init__()
        self.processor = processor
        self.original_prompt = original_prompt
        self.enhanced_prompt = enhanced_prompt
        self.model = model
        self.key = key_to_regenerate

    @Slot()
    def run(self):
        """The main work method."""
        try:
            if self.key == 'enhanced':
                # Regenerating the main enhancement is based on the original prompt
                result_data = self.processor.enhance_prompt(self.original_prompt, self.model)
            else:
                # Regenerating a variation is based on the current enhanced prompt
                result_data = self.processor.process_single_variation(self.enhanced_prompt, self.key, self.model)
            
            self.result_ready.emit(self.key, result_data)
        except Exception as e:
            self.result_ready.emit(self.key, {'prompt': f"Error: {e}"})
        finally:
            self.finished.emit()


class EnhancementResultWindow(QDialog):
    """A pop-up window to display enhancement results, rewritten in Qt."""
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor, original_prompt: str, model: str, variations: List[str]):
        super().__init__(parent)
        self.setWindowTitle("Enhancement Result")
        self.setMinimumSize(700, 750)

        self.parent_app = parent
        self.processor = processor
        self.original_prompt = original_prompt
        self.model = model
        self.variations = variations
        self.result_data: Dict[str, Any] = {'original': original_prompt, 'variations': {}}
        self.active_threads: List[QThread] = []

        # --- UI element storage ---
        self.text_widgets: Dict[str, QTextEdit] = {}
        self.loading_labels: Dict[str, QLabel] = {}
        self.regen_buttons: Dict[str, QPushButton] = {}

        self._create_widgets()
        self._start_enhancement()
        
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception: pass

    def _create_widgets(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        # Scrollable area for the prompt sections
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        self.prompts_layout = QVBoxLayout(scroll_widget)
        self.prompts_layout.setSpacing(10)
        scroll_area.setWidget(scroll_widget)
        self.main_layout.addWidget(scroll_area)

        # Create the text areas
        self._create_text_area('original', "Original Prompt", self.original_prompt, is_loading=False)
        self._create_text_area('enhanced', "Enhanced Prompt", "Generating...", is_loading=True)
        
        if self.variations:
            variations_group = QGroupBox("Variations")
            variations_layout = QVBoxLayout(variations_group)
            for var_key in self.variations:
                var_name = self.processor.available_variations_map.get(var_key, var_key.capitalize())
                self._create_text_area(var_key, var_name, "Generating...", is_loading=True, parent_layout=variations_layout)
            variations_group.setLayout(variations_layout)
            self.prompts_layout.addWidget(variations_group)

        self.prompts_layout.addStretch()

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        self.save_button = QPushButton("Save to History")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)

        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.close_button)
        self.main_layout.addLayout(button_layout)

    def _create_text_area(self, key: str, title: str, content: str, is_loading: bool, parent_layout: Optional[QVBoxLayout] = None, has_regen: bool = True):
        """Helper to create a group box with a text area and buttons."""
        group_box = QGroupBox(title)
        group_layout = QHBoxLayout(group_box)
        
        text_widget = QTextEdit(content)
        text_widget.setReadOnly(is_loading)
        group_layout.addWidget(text_widget)
        self.text_widgets[key] = text_widget

        # --- Side Button Panel ---
        button_panel = QWidget()
        button_panel_layout = QVBoxLayout(button_panel)
        button_panel_layout.setContentsMargins(0,0,0,0)
        button_panel_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(lambda: self._copy_prompt(key))
        button_panel_layout.addWidget(copy_button)

        gen_image_button = QPushButton("Generate Image")
        gen_image_button.clicked.connect(lambda: self._generate_image(key))
        button_panel_layout.addWidget(gen_image_button)

        if has_regen:
            regen_button = QPushButton("Regenerate")
            regen_button.clicked.connect(lambda: self._regenerate_prompt(key))
            button_panel_layout.addWidget(regen_button)
            self.regen_buttons[key] = regen_button

        if is_loading:
            loading_label = QLabel("Generating...")
            loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.loading_labels[key] = loading_label
            button_panel_layout.addWidget(loading_label)
            copy_button.setEnabled(False)
            gen_image_button.setEnabled(False)
            if has_regen: regen_button.setEnabled(False)

        group_layout.addWidget(button_panel)
        group_layout.setStretchFactor(text_widget, 1)

        if parent_layout is not None:
            parent_layout.addWidget(group_box)
        else:
            self.prompts_layout.addWidget(group_box)

    def _start_enhancement(self):
        """Starts the background worker to run the enhancement process."""
        self.thread = QThread() # No parent
        self.worker = EnhancementWorker(None, self.processor, self.original_prompt, self.model, self.variations)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.result_ready.connect(self._on_result_ready)
        self.worker.batch_finished.connect(self._on_batch_finished)
        
        self.worker.batch_finished.connect(self.thread.quit)
        self.worker.batch_finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()
        self.parent_app._start_loading_animation(f"Enhancing prompt with {self.model}...")

    @Slot(str, dict)
    def _on_result_ready(self, key: str, data: dict):
        """Slot to receive a generated prompt part and update the UI."""
        if key in self.text_widgets:
            prompt_text = data.get('prompt', 'Error: No prompt received.')
            self.text_widgets[key].setReadOnly(False)
            self.text_widgets[key].setPlainText(prompt_text)
            
            if key == 'enhanced':
                self.result_data['enhanced'] = data
            else:
                self.result_data['variations'][key] = data

            if key in self.loading_labels:
                self.loading_labels[key].hide()
            
            # Enable buttons for this section
            for btn_dict in [self.text_widgets[key].parent().findChildren(QPushButton)]:
                for btn in btn_dict:
                    btn.setEnabled(True)

    @Slot()
    def _on_batch_finished(self):
        """Slot called when the entire batch is complete."""
        self.save_button.setEnabled(True)
        self.parent_app._stop_loading_animation("Enhancement complete.")

    @Slot()
    def _save(self):
        """Saves the result to the history file."""
        # Update prompts from text widgets before saving
        if 'enhanced' in self.result_data:
            self.result_data['enhanced']['prompt'] = self.text_widgets['enhanced'].toPlainText()
        for key, var_data in self.result_data.get('variations', {}).items():
            var_data['prompt'] = self.text_widgets[key].toPlainText()

        self.processor.history_manager.save_result(**self.result_data)
        self.parent_app.status_bar.showMessage("Result saved to history.", 5000)
        self.close()

    def _copy_prompt(self, key: str):
        """Copies the text from a specific prompt area to the clipboard."""
        if key in self.text_widgets:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.text_widgets[key].toPlainText())
            self.parent_app.status_bar.showMessage(f"Copied '{key}' prompt.", 3000)

    def _generate_image(self, key: str):
        """Placeholder for generating an image from a specific prompt."""
        if key not in self.text_widgets:
            return
        
        prompt_text = self.text_widgets[key].toPlainText().strip()
        if not prompt_text:
            QMessageBox.warning(self, "Empty Prompt", "There is no prompt text to generate an image from.")
            return

        # Use the main app's ImageGenerationOptionsDialog
        from .image_generation_dialog import ImageGenerationOptionsDialog
        dialog = ImageGenerationOptionsDialog(self, self.processor, prompt_text, initial_params={})
        if dialog.exec() == QDialog.Accepted:
            options = dialog.get_options()
            selected_models = options.pop('models', [])
            if not selected_models:
                QMessageBox.warning(self, "No Models Selected", "You must select at least one model to generate images.")
                return

            generation_jobs = []
            num_images_per_model = options.pop('num_images', 1)
            base_seed = options.get('seed', random.randint(0, 2**32 - 1))

            for model_obj in selected_models:
                for i in range(num_images_per_model):
                    job_params = options.copy()
                    job_params['model'] = model_obj
                    job_params['seed'] = base_seed + i
                    generation_jobs.append({
                        'prompt': prompt_text,
                        'gen_params': job_params
                    })
            
            # The on_success callback is empty because the MultiImagePreviewDialog handles saving
            # to history itself. The main app's history viewer will show the new entry on its next refresh.
            def on_success(images_to_save):
                self.parent_app.status_bar.showMessage(f"{len(images_to_save)} image(s) saved to history.", 5000)

            from .multi_image_preview_dialog import MultiImagePreviewDialog
            preview_dialog = MultiImagePreviewDialog(self, self.processor, generation_jobs, on_success_callback=on_success)
            preview_dialog.exec()

    def _regenerate_prompt(self, key: str):
        """Regenerates a specific prompt using a background worker."""
        # Disable UI for this section
        self.text_widgets[key].setReadOnly(True)
        self.text_widgets[key].setPlainText("Generating...")
        if key in self.loading_labels:
            self.loading_labels[key].show()
        
        for btn in self.text_widgets[key].parent().findChildren(QPushButton):
            btn.setEnabled(False)

        enhanced_prompt = self.text_widgets.get('enhanced', QTextEdit()).toPlainText()

        regen_thread = QThread() # No parent
        regen_worker = SingleEnhancementWorker(None, self.processor, self.original_prompt, enhanced_prompt, self.model, key)
        regen_worker.moveToThread(regen_thread)

        regen_thread.started.connect(regen_worker.run)
        regen_worker.result_ready.connect(self._on_result_ready)
        regen_worker.finished.connect(regen_thread.quit)
        regen_worker.finished.connect(regen_worker.deleteLater)
        regen_thread.finished.connect(regen_thread.deleteLater)

        regen_thread.start()

    def closeEvent(self, event: QCloseEvent):
        """Ensures the parent app knows this window is closed."""
        if self in self.parent_app.enhancement_windows:
            self.parent_app.enhancement_windows.remove(self)
        super().closeEvent(event)