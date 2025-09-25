"""A Qt-based window for the Prompt Evolver tool."""

import random
from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QGroupBox,
    QPushButton, QScrollArea, QLabel, QFrame, QCheckBox, QMenu,
    QInputDialog, QMessageBox
)
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QPoint
from PySide6.QtGui import QAction
from typing import List, Dict, Any, Optional, Callable, TYPE_CHECKING

from core.prompt_processor import PromptProcessor
from .prompt_selection_dialog import PromptSelectionDialog
from .multi_image_preview_dialog import MultiImagePreviewDialog
from .image_generation_dialog import ImageGenerationOptionsDialog
if TYPE_CHECKING:
    from .gui_app import GUIApp

class BreedingWorker(QObject):
    """Worker to 'breed' new prompts from parents in the background."""
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor, parent_prompts: List[str], num_children: int, model: str):
        super().__init__()
        self.processor = processor
        self.parent_prompts = parent_prompts
        self.num_children = num_children
        self.model = model

    @Slot()
    def run(self):
        try:
            child_prompts = self.processor.breed_prompts(self.parent_prompts, self.num_children, self.model)
            self.finished.emit({'success': True, 'children': child_prompts})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

class PromptCard(QFrame):
    """A custom widget to display a prompt in a selectable card."""
    def __init__(self, prompt: str, parent_window: 'PromptEvolverWindow'):
        super().__init__()
        self.prompt = prompt
        self.parent_window = parent_window
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)

        layout = QHBoxLayout(self)
        self.checkbox = QCheckBox()
        layout.addWidget(self.checkbox)

        self.label = QLabel(prompt)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        copy_action = menu.addAction("Copy Prompt")
        enhance_action = menu.addAction("Enhance This Prompt")
        generate_action = menu.addAction("Generate Image")
        
        action = menu.exec(self.mapToGlobal(pos))

        if action == copy_action:
            QApplication.clipboard().setText(self.prompt)
        elif action == enhance_action:
            self.parent_window.parent_app.start_enhancement_workflow(self.prompt)
        elif action == generate_action:
            self.parent_window._generate_image_from_card(self.prompt)

class PromptEvolverWindow(QDialog):
    """A window for 'breeding' new prompts from parent prompts."""

    def __init__(self, parent: 'GUIApp', processor: PromptProcessor, load_prompt_callback: Callable):
        super().__init__(parent)
        self.setWindowTitle("Prompt Evolver")
        self.parent_app = parent
        self.processor = processor
        self.load_prompt_callback = load_prompt_callback
        self.breeding_thread: Optional[QThread] = None

        self._create_widgets()
        self._connect_signals()
        self.resize(1000, 700)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, 1)

        # --- Parents Pane ---
        parents_group = QGroupBox("Parents (Select 2+ to breed)")
        parents_main_layout = QVBoxLayout(parents_group)
        self.select_parents_button = QPushButton("Select Parents from History...")
        parents_main_layout.addWidget(self.select_parents_button)
        
        parents_scroll = QScrollArea()
        parents_scroll.setWidgetResizable(True)
        self.parents_widget = QWidget()
        self.parents_layout = QVBoxLayout(self.parents_widget)
        self.parents_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        parents_scroll.setWidget(self.parents_widget)
        parents_main_layout.addWidget(parents_scroll)
        splitter.addWidget(parents_group)

        # --- Children Pane ---
        children_group = QGroupBox("Children (Right-click for actions)")
        children_main_layout = QVBoxLayout(children_group)
        
        children_scroll = QScrollArea()
        children_scroll.setWidgetResizable(True)
        self.children_widget = QWidget()
        self.children_layout = QVBoxLayout(self.children_widget)
        self.children_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        children_scroll.setWidget(self.children_widget)
        children_main_layout.addWidget(children_scroll)
        splitter.addWidget(children_group)

        # --- Bottom Action Bar ---
        action_layout = QHBoxLayout()
        self.breed_button = QPushButton("Breed Prompts")
        self.breed_button.setEnabled(False)
        action_layout.addWidget(self.breed_button)
        action_layout.addStretch()
        self.close_button = QPushButton("Close")
        action_layout.addWidget(self.close_button)
        main_layout.addLayout(action_layout)

    def _connect_signals(self):
        self.select_parents_button.clicked.connect(self._on_select_parents)
        self.breed_button.clicked.connect(self._on_breed)
        self.close_button.clicked.connect(self.close)

    @Slot()
    def _on_select_parents(self):
        dialog = PromptSelectionDialog(self, self.processor)
        if dialog.exec() == QDialog.Accepted:
            self.add_prompts_to_pane(self.parents_layout, dialog.selected_prompts)

    def add_prompts_to_pane(self, layout: QVBoxLayout, prompts: List[str]):
        for prompt in prompts:
            card = PromptCard(prompt, self)
            card.checkbox.stateChanged.connect(self._update_breed_button_state)
            layout.addWidget(card)
        self._update_breed_button_state()

    @Slot()
    def _update_breed_button_state(self):
        selected_count = len(self._get_selected_parent_prompts())
        self.breed_button.setEnabled(selected_count >= 2)

    def _get_selected_parent_prompts(self) -> List[str]:
        prompts = []
        for i in range(self.parents_layout.count()):
            card = self.parents_layout.itemAt(i).widget()
            if isinstance(card, PromptCard) and card.checkbox.isChecked():
                prompts.append(card.prompt)
        return prompts

    @Slot()
    def _on_breed(self):
        parent_prompts = self._get_selected_parent_prompts()
        if len(parent_prompts) < 2:
            QMessageBox.warning(self, "Not Enough Parents", "Please select at least two parent prompts to breed.")
            return

        num_children, ok = QInputDialog.getInt(self, "Breed Prompts", "Number of children to generate:", 5, 1, 20)
        if not ok:
            return

        model = self.parent_app.model_combo.currentText()
        if not model or "model" in model.lower():
            QMessageBox.warning(self, "No Model", "Please select a valid model in the main window.")
            return

        self.breed_button.setEnabled(False)
        self.parent_app._start_loading_animation(f"Breeding {num_children} prompts with {model}...")

        self.breeding_thread = QThread(self)
        worker = BreedingWorker(self.processor, parent_prompts, num_children, model)
        worker.moveToThread(self.breeding_thread)

        self.breeding_thread.started.connect(worker.run)
        worker.finished.connect(self._on_breeding_finished)
        worker.finished.connect(self.breeding_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self.breeding_thread.finished.connect(self.breeding_thread.deleteLater)
        self.breeding_thread.start()

    @Slot(dict)
    def _on_breeding_finished(self, result: dict):
        self.breed_button.setEnabled(True)
        self.parent_app._stop_loading_animation("Breeding complete.")

        if result['success']:
            # Clear previous children
            while self.children_layout.count():
                child = self.children_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            
            children = result.get('children', [])
            self.add_prompts_to_pane(self.children_layout, children)
        else:
            QMessageBox.critical(self, "Breeding Error", f"An error occurred while breeding prompts:\n{result['error']}")

    def _generate_image_from_card(self, prompt_text: str):
        """Handles the 'Generate Image' action from a prompt card's context menu."""
        if not self.processor.is_invokeai_connected():
            QMessageBox.warning(self, "Not Connected", "InvokeAI is not configured or connected.")
            return

        dialog = ImageGenerationOptionsDialog(self, self.processor, prompt_text, initial_params={})
        if dialog.exec() == QDialog.Accepted:
            options = dialog.get_options()
            selected_models = options.pop('models', [])
            save_to_gallery = options.get('save_to_gallery', config.save_to_gallery_by_default)
            if not selected_models:
                QMessageBox.warning(self, "No Models Selected", "You must select at least one model to generate images.")
                return

            generation_jobs = []
            num_images_per_model = options.pop('num_images', 1)
            base_seed = options.get('seed', random.randint(0, 2**32 - 1))

            for model_info in selected_models:
                for i in range(num_images_per_model):
                    job_params = options.copy()
                    job_params['model'] = model_info['model']
                    job_params['loras'] = model_info.get('loras', [])
                    job_params['negative_prompt'] = model_info['negative_prompt']
                    job_params['seed'] = base_seed + i
                    generation_jobs.append({
                        'prompt': prompt_text,
                        'gen_params': job_params
                    })
            
            def on_success(images_to_save):
                self.parent_app.status_bar.showMessage(f"{len(images_to_save)} image(s) saved to history.", 5000)

            preview_dialog = MultiImagePreviewDialog(self, self.processor, generation_jobs, on_success_callback=on_success, save_to_gallery=save_to_gallery)
            preview_dialog.exec()