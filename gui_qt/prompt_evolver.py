"A Qt-based window for the Prompt Evolver tool."

import queue
from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QGroupBox,
    QPushButton, QLabel, QMenu,
    QMessageBox, QComboBox, QListWidget, QListWidgetItem,
    QSpinBox, QDoubleSpinBox
)
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QPoint, QEvent, QMimeData
from PySide6.QtGui import QPixmap, QMouseEvent, QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent
from PIL.ImageQt import ImageQt
from PIL import Image
from PySide6.QtWidgets import QSizePolicy
from typing import List, Dict, Any, Optional, Callable, TYPE_CHECKING
import os
from core.config import config

from core.prompt_processor import PromptProcessor
from .image_preview_mixin import ImagePreviewMixin
from .custom_widgets import LoadingSpinner, SmoothListWidget

if TYPE_CHECKING:
    from .gui_app import GUIApp

class PromptListItem(QWidget):
    mouse_entered = Signal(dict)
    mouse_left = Signal()

    def __init__(self, prompt_data: Dict[str, Any], processor: PromptProcessor):
        super().__init__()
        self.prompt_data = prompt_data
        self.processor = processor

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(64, 64)
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setStyleSheet("border: 1px solid #555;")
        layout.addWidget(self.thumbnail_label)

        workflow_tag = prompt_data.get('workflow_source', 'N/A')
        workflow_label = QLabel(f"[{workflow_tag}]")
        if workflow_tag == 'SFW':
            workflow_label.setStyleSheet("color: gray;")
        else: # NSFW
            workflow_label.setStyleSheet("color: red;")
        layout.addWidget(workflow_label)

        prompt_text = prompt_data.get('enhanced', {}).get('prompt') or prompt_data.get('original_prompt', '')
        self.prompt_label = QLabel(prompt_text)
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.prompt_label, 1)

        if prompt_data.get('favorite', False):
            favorite_label = QLabel("⭐")
            favorite_label.setStyleSheet("font-weight: bold; color: gold;")
            layout.addWidget(favorite_label)
        
        self.setLayout(layout)
        self.thumbnail_label.installEventFilter(self)

    def set_thumbnail(self, pixmap: QPixmap):
        if not pixmap.isNull():
            self.thumbnail_label.setPixmap(pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumbnail_label.setText("No\nImage")

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() != Qt.LeftButton:
            return
        mime_data = QMimeData()
        prompt_text = self.prompt_data.get('enhanced', {}).get('prompt') or self.prompt_data.get('original_prompt', '')
        mime_data.setText(prompt_text)
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.MoveAction)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj == self.thumbnail_label:
            if event.type() == QEvent.Type.Enter:
                if not self.thumbnail_label.pixmap().isNull():
                    self.mouse_entered.emit(self.prompt_data)
                return True
            elif event.type() == QEvent.Type.Leave:
                self.mouse_left.emit()
                return True
        return super().eventFilter(obj, event)

class ThumbnailLoader(QObject):
    thumbnail_ready = Signal(dict)

    def __init__(self, processor: PromptProcessor, job_queue: queue.Queue):
        super().__init__()
        self.processor = processor
        self.job_queue = job_queue

    @Slot()
    def run(self):
        while not QThread.currentThread().isInterruptionRequested():
            try:
                job = self.job_queue.get(timeout=1)
                if job is None: break
                item_widget, prompt_data = job.get('item_widget'), job.get('prompt_data')
                all_image_data_lists = []
                if isinstance(prompt_data.get('original_images'), list):
                    all_image_data_lists.append(prompt_data['original_images'])
                if isinstance(prompt_data.get('enhanced'), dict) and isinstance(prompt_data['enhanced'].get('images'), list):
                    all_image_data_lists.append(prompt_data['enhanced']['images'])
                if isinstance(prompt_data.get('variations'), dict):
                    for var_data in prompt_data['variations'].values():
                        if isinstance(var_data, dict) and isinstance(var_data.get('images'), list):
                            all_image_data_lists.append(var_data['images'])
                cover_image_path, first_image_path = None, None
                for img_list in all_image_data_lists:
                    if not first_image_path and img_list and isinstance(img_list[0], dict):
                        first_image_path = img_list[0].get('image_path')
                    for img_data in img_list:
                        if isinstance(img_data, dict) and img_data.get('is_cover_image'):
                            cover_image_path = img_data.get('image_path')
                            break
                    if cover_image_path:
                        break
                image_to_load = cover_image_path or first_image_path
                pixmap = QPixmap()
                if image_to_load:
                    try:
                        workflow = prompt_data.get('workflow_source', 'sfw').lower()
                        original_workflow = config.workflow
                        config.workflow = workflow
                        full_path = os.path.join(config.get_history_file_dir(), image_to_load)
                        config.workflow = original_workflow
                        if os.path.exists(full_path):
                            pil_image = self.processor.thumbnail_manager.get_thumbnail(image_to_load, workflow, (64, 64))
                            if pil_image:
                                qimage = ImageQt(pil_image)
                                pixmap = QPixmap.fromImage(qimage)
                    except Exception as e:
                        print(f"Error loading thumbnail for {image_to_load}: {e}")
                self.thumbnail_ready.emit({'item_widget': item_widget, 'pixmap': pixmap})
            except queue.Empty:
                continue

class ModelLoadingWorker(QObject):
    finished = Signal(dict)
    def __init__(self, processor: PromptProcessor):
        super().__init__()
        self.processor = processor
    @Slot()
    def run(self):
        try:
            self.finished.emit({'success': True, 'models': self.processor.get_ollama_models()})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})
class BreedingWorker(QObject):
    finished = Signal(dict)
    def __init__(self, processor: PromptProcessor, parents: List[str], num_children: int, model: str, temperature: float, top_p: float):
        super().__init__()
        self.processor = processor
        self.parents = parents
        self.num_children = num_children
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
    @Slot()
    def run(self):
        try:
            self.finished.emit({'success': True, 'children': self.processor.ai_breed_prompts(self.parents, self.num_children, self.model, self.temperature, self.top_p)})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

class PromptEvolverWindow(QDialog, ImagePreviewMixin):
    def __init__(self, parent: 'GUIApp', processor: PromptProcessor, load_prompt_callback: Callable):
        super().__init__(parent)
        ImagePreviewMixin.__init__(self)
        self.setWindowTitle("Prompt Evolver")
        self.parent_app, self.processor, self.load_prompt_callback = parent, processor, load_prompt_callback
        self.breeding_thread, self.mutation_thread, self.model_loading_thread = None, None, None
        self.models, self.current_model, self.all_prompts_data = [], None, []
        self.shared_thumb_job_queue = queue.Queue()
        self._setup_persistent_thumbnail_worker()
        self._create_widgets()
        self._init_image_preview_mixin(self)
        self._connect_signals()
        self._load_models()
        self._load_prompt_history()
        self.resize(1600, 900)
        try:
            self.move(QApplication.primaryScreen().availableGeometry().center() - self.rect().center())
        except Exception:
            pass

    def _get_preview_image(self, item_data: Dict[str, Any]) -> Optional[Image.Image]:
        all_image_data_lists = []
        if isinstance(item_data.get('original_images'), list): all_image_data_lists.append(item_data['original_images'])
        if isinstance(item_data.get('enhanced'), dict) and isinstance(item_data['enhanced'].get('images'), list): all_image_data_lists.append(item_data['enhanced']['images'])
        if isinstance(item_data.get('variations'), dict):
            for var_data in item_data['variations'].values():
                if isinstance(var_data, dict) and isinstance(var_data.get('images'), list): all_image_data_lists.append(var_data['images'])
        cover_image_path, first_image_path = None, None
        for img_list in all_image_data_lists:
            if not first_image_path and img_list and isinstance(img_list[0], dict): first_image_path = img_list[0].get('image_path')
            for img_data in img_list:
                if isinstance(img_data, dict) and img_data.get('is_cover_image'):
                    cover_image_path = img_data.get('image_path')
                    break
                if cover_image_path:
                    break
                image_to_load = cover_image_path or first_image_path
        if not relative_image_path:
            return None
        try:
            workflow = item_data.get('workflow_source', 'sfw').lower()
            original_workflow = config.workflow
            config.workflow = workflow
            full_path = os.path.join(config.get_history_file_dir(), relative_image_path)
            config.workflow = original_workflow
            if not os.path.exists(full_path):
                return None
            return Image.open(full_path)
        except Exception as e:
            print(f"Error loading full image for preview: {e}")
            return None

    def _setup_persistent_thumbnail_worker(self):
        self.persistent_thumb_thread = QThread()
        self.persistent_thumb_worker = ThumbnailLoader(self.processor, self.shared_thumb_job_queue)
        self.persistent_thumb_worker.moveToThread(self.persistent_thumb_thread)
        self.persistent_thumb_worker.thumbnail_ready.connect(self._on_any_thumbnail_ready)
        self.persistent_thumb_thread.started.connect(self.persistent_thumb_worker.run)
        self.persistent_thumb_thread.start()

    @Slot(dict)
    def _on_any_thumbnail_ready(self, result: dict):
        item_widget, pixmap = result.get('item_widget'), result.get('pixmap')
        if item_widget and not pixmap.isNull():
            item_widget.set_thumbnail(pixmap)

    def _create_widgets(self):
        self.main_layout = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.splitter)
        history_group = QGroupBox("Prompt History")
        history_layout = QVBoxLayout(history_group)
        self.history_list = SmoothListWidget()
        self.history_list.setDragEnabled(True)
        history_layout.addWidget(self.history_list)
        self.splitter.addWidget(history_group)
        middle_panel = QWidget()
        middle_layout = QVBoxLayout(middle_panel)
        parents_group = QGroupBox("Parents")
        parents_layout = QVBoxLayout(parents_group)
        self.parents_list = SmoothListWidget()
        self.parents_list.setAcceptDrops(True)
        parents_layout.addWidget(self.parents_list)
        middle_layout.addWidget(parents_group)
        controls_group = QGroupBox("Breeding Controls")
        controls_layout = QVBoxLayout(controls_group)
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_combo.setToolTip("The AI model used to generate the new prompts.")
        model_layout.addWidget(self.model_combo)
        controls_layout.addLayout(model_layout)
        num_children_layout = QHBoxLayout()
        num_children_layout.addWidget(QLabel("Number of Children:"))
        self.num_children_spinbox = QSpinBox()
        self.num_children_spinbox.setRange(1, 20)
        self.num_children_spinbox.setValue(5)
        self.num_children_spinbox.setToolTip("How many new prompts to generate from the parents.")
        num_children_layout.addWidget(self.num_children_spinbox)
        controls_layout.addLayout(num_children_layout)
        temperature_layout = QHBoxLayout()
        temperature_layout.addWidget(QLabel("Temperature:"))
        self.temperature_spinbox = QDoubleSpinBox()
        self.temperature_spinbox.setRange(0.0, 2.0)
        self.temperature_spinbox.setSingleStep(0.1)
        self.temperature_spinbox.setValue(0.7)
        self.temperature_spinbox.setToolTip("Controls the creativity/randomness of the AI. Higher values (e.g., 1.2) are more creative. Lower values (e.g., 0.5) are more focused.")
        temperature_layout.addWidget(self.temperature_spinbox)
        controls_layout.addLayout(temperature_layout)
        top_p_layout = QHBoxLayout()
        top_p_layout.addWidget(QLabel("Top P:"))
        self.top_p_spinbox = QDoubleSpinBox()
        self.top_p_spinbox.setRange(0.0, 1.0)
        self.top_p_spinbox.setSingleStep(0.1)
        self.top_p_spinbox.setValue(0.9)
        self.top_p_spinbox.setToolTip("An alternative to Temperature for controlling randomness. It's generally recommended to alter either Temperature or Top P, but not both.")
        top_p_layout.addWidget(self.top_p_spinbox)
        controls_layout.addLayout(top_p_layout)
        self.breed_button = QPushButton("Breed Prompts")
        self.breed_spinner = LoadingSpinner(self)
        self.breed_spinner.setVisible(False)
        breed_layout = QHBoxLayout()
        breed_layout.addWidget(self.breed_button)
        breed_layout.addWidget(self.breed_spinner)
        controls_layout.addLayout(breed_layout)
        middle_layout.addWidget(controls_group)
        self.splitter.addWidget(middle_panel)
        children_group = QGroupBox("Children")
        children_layout = QVBoxLayout(children_group)
        self.children_list = SmoothListWidget()
        children_layout.addWidget(self.children_list)
        self.use_as_parents_button = QPushButton("Use Selected as Parents")
        self.send_to_editor_button = QPushButton("Send to Editor")
        children_button_layout = QHBoxLayout()
        children_button_layout.addWidget(self.use_as_parents_button)
        children_button_layout.addWidget(self.send_to_editor_button)
        children_layout.addLayout(children_button_layout)
        self.splitter.addWidget(children_group)
        self.close_button = QPushButton("Close")
        self.main_layout.addWidget(self.close_button, 0, Qt.AlignRight)

    def _connect_signals(self):
        self.breed_button.clicked.connect(self._breed_prompts)
        self.close_button.clicked.connect(self.close)
        self.use_as_parents_button.clicked.connect(self._use_children_as_parents)
        self.send_to_editor_button.clicked.connect(self._handle_send_to_editor_button_click)
        self.history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self._show_history_context_menu)
        self.parents_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.parents_list.customContextMenuRequested.connect(self._show_parents_context_menu)
        self.children_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.children_list.customContextMenuRequested.connect(self._show_children_context_menu)
        self.history_list.itemDoubleClicked.connect(self._handle_history_double_click)
        self.parents_list.itemSelectionChanged.connect(self._handle_parents_selection_changed)
        self.children_list.itemSelectionChanged.connect(self._handle_children_selection_changed)
        self.parents_list.keyPressEvent = self._handle_parents_key_press
        self.model_combo.currentIndexChanged.connect(self._on_model_combo_index_changed)

    def _load_models(self):
        self.model_loading_thread = QThread()
        self.model_loading_worker = ModelLoadingWorker(self.processor)
        self.model_loading_worker.moveToThread(self.model_loading_thread)
        self.model_loading_worker.finished.connect(self._on_models_loaded)
        self.model_loading_thread.started.connect(self.model_loading_worker.run)
        self.model_loading_thread.start()

    @Slot(dict)
    def _on_models_loaded(self, result: dict):
        if result['success']:
            self.models = [m['name'] for m in result['models']]
            self.model_combo.clear()
            self.model_combo.addItems(self.models)
            if config.DEFAULT_OLLAMA_MODEL and config.DEFAULT_OLLAMA_MODEL in self.models:
                self.model_combo.setCurrentText(config.DEFAULT_OLLAMA_MODEL)
            else:
                main_app_model = self.parent_app.model_combo.currentText()
                if main_app_model and main_app_model in self.models:
                    self.model_combo.setCurrentText(main_app_model)
                elif self.models:
                    self.model_combo.setCurrentIndex(0)
            if not self.models:
                self.model_combo.setEnabled(False)
            self.breed_button.setEnabled(bool(self.models))
        else:
            QMessageBox.critical(self, "Model Loading Error", f"Failed to load Ollama models: {result['error']}")
        self.model_loading_thread.quit()
        self.model_loading_thread.wait()

    def _load_prompt_history(self):
        self.history_list.clear()
        self.all_prompts_data = self.processor.get_full_history()
        for item_data in self.all_prompts_data:
            prompt_text = item_data.get('enhanced', {}).get('prompt') or item_data.get('original_prompt', '')
            if prompt_text:
                list_item = QListWidgetItem(self.history_list)
                custom_widget = PromptListItem(item_data, self.processor)
                list_item.setSizeHint(custom_widget.sizeHint())
                self.history_list.setItemWidget(list_item, custom_widget)
                self.shared_thumb_job_queue.put({'item_widget': custom_widget, 'prompt_data': item_data})
                custom_widget.mouse_entered.connect(self._schedule_preview)
                custom_widget.mouse_left.connect(self._schedule_hide)

    def _add_wrapping_list_item(self, list_widget: QListWidget, text: str):
        item = QListWidgetItem()
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMargin(2)
        list_widget.addItem(item)
        list_widget.setItemWidget(item, label)
        item.setData(Qt.UserRole, text)
        item.setSizeHint(label.sizeHint())

    @Slot()
    def _breed_prompts(self):
        parents = [self.parents_list.item(i).data(Qt.UserRole) for i in range(self.parents_list.count())]
        if len(parents) < 2:
            QMessageBox.warning(self, "Not Enough Parents", "Please drag at least two parent prompts to the Parents list.")
            return
        model = self.model_combo.currentText()
        if not model:
            QMessageBox.critical(self, "Model Error", "Please select a valid Ollama model.")
            return
        self.breed_button.setEnabled(False)
        self.breed_spinner.start()
        self.children_list.clear()
        self._add_wrapping_list_item(self.children_list, "Generating with AI...")
        self.breeding_thread = QThread()
        self.breeding_worker = BreedingWorker(self.processor, parents, self.num_children_spinbox.value(), model, self.temperature_spinbox.value(), self.top_p_spinbox.value())
        self.breeding_worker.moveToThread(self.breeding_thread)
        self.breeding_worker.finished.connect(self._on_breeding_finished)
        self.breeding_worker.finished.connect(self.breeding_worker.deleteLater)
        self.breeding_thread.started.connect(self.breeding_worker.run)
        self.breeding_thread.start()

    @Slot(dict)
    def _on_breeding_finished(self, result: dict):
        self.breed_button.setEnabled(True)
        self.breed_spinner.stop()
        self.children_list.clear()
        if result['success']:
            for prompt in result.get('children', []):
                self._add_wrapping_list_item(self.children_list, prompt)
            if not result.get('children'):
                self._add_wrapping_list_item(self.children_list, "No child prompts generated.")
        else:
            error_msg = f"The AI failed to generate child prompts:\n{result['error']}"
            QMessageBox.critical(self, "Breeding Error", error_msg)
            self._add_wrapping_list_item(self.children_list, f"Error: {result['error']}")
        self.breeding_thread.quit()
        self.breeding_thread.wait()

    @Slot()
    def _use_children_as_parents(self):
        selected_children = [item.data(Qt.UserRole) for item in self.children_list.selectedItems()]
        if not selected_children:
            QMessageBox.warning(self, "No Selection", "Please select one or more child prompts to use as parents.")
            return
        self.parents_list.clear()
        for prompt in selected_children:
            self._add_wrapping_list_item(self.parents_list, prompt)
        self.children_list.clear()

    @Slot()
    def _handle_send_to_editor_button_click(self):
        selected = self.children_list.selectedItems()
        if len(selected) != 1:
            QMessageBox.warning(self, "Selection Error", "Please select exactly one child prompt.")
            return
        self._send_prompt_to_editor(selected[0].data(Qt.UserRole))

    def _send_prompt_to_editor(self, prompt: str):
        if not prompt:
            return
        self.load_prompt_callback({'original_prompt': prompt})
        self.close()

    def _add_history_item_to_parents(self, item_data: Dict[str, Any]):
        prompt_text = item_data.get('enhanced', {}).get('prompt') or item_data.get('original_prompt', '')
        if prompt_text and prompt_text not in [self.parents_list.item(i).data(Qt.UserRole) for i in range(self.parents_list.count())]:
            self._add_wrapping_list_item(self.parents_list, prompt_text)

    def _show_history_context_menu(self, position: QPoint):
        menu = QMenu()
        copy_action = menu.addAction("Copy Prompt")
        add_parent_action = menu.addAction("Add as Parent")
        action = menu.exec(self.history_list.mapToGlobal(position))
        selected = self.history_list.selectedItems()
        if not selected:
            return
        widget = self.history_list.itemWidget(selected[0])
        if not isinstance(widget, PromptListItem):
            return
        prompt_text = widget.prompt_data.get('enhanced', {}).get('prompt') or widget.prompt_data.get('original_prompt', '')
        if action == copy_action:
            QApplication.clipboard().setText(prompt_text)
        elif action == add_parent_action:
            self._add_history_item_to_parents(widget.prompt_data)

    def _show_parents_context_menu(self, position: QPoint):
        menu = QMenu()
        copy_action = menu.addAction("Copy Prompt")
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.parents_list.mapToGlobal(position))
        selected = self.parents_list.selectedItems()
        if not selected:
            return
        prompt_text = selected[0].data(Qt.UserRole)
        if action == copy_action:
            QApplication.clipboard().setText(prompt_text)
        elif action == remove_action:
            for item in selected:
                self.parents_list.takeItem(self.parents_list.row(item))

    def _show_children_context_menu(self, position: QPoint):
        menu = QMenu()
        copy_action = menu.addAction("Copy Prompt")
        add_parent_action = menu.addAction("Add as Parent")
        menu.addSeparator()
        generate_image_action = menu.addAction("Generate Image...")
        enhance_save_action = menu.addAction("Enhance and Save...")
        send_to_editor_action = menu.addAction("Send to Main Editor")
        action = menu.exec(self.children_list.mapToGlobal(position))
        selected = self.children_list.selectedItems()
        if not selected:
            return
        prompt_text = selected[0].data(Qt.UserRole)
        if action == copy_action:
            QApplication.clipboard().setText(prompt_text)
        elif action == add_parent_action:
            for item in selected:
                self._add_wrapping_list_item(self.parents_list, item.data(Qt.UserRole))
        elif action == generate_image_action:
            self._generate_image_for_child(prompt_text)
        elif action == enhance_save_action:
            self._enhance_child_prompt(prompt_text)
        elif action == send_to_editor_action:
            self._send_prompt_to_editor(prompt_text)

    def _generate_image_for_child(self, prompt: str):
        self.parent_app._start_image_generation_workflow(self, prompt, initial_params={})
    def _enhance_child_prompt(self, prompt: str):
        self.parent_app.start_enhancement_workflow(prompt)

    def _handle_history_double_click(self, item: QListWidgetItem):
        widget = self.history_list.itemWidget(item)
        if isinstance(widget, PromptListItem):
            self._add_history_item_to_parents(widget.prompt_data)

    def _handle_parents_key_press(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            for item in self.parents_list.selectedItems():
                self.parents_list.takeItem(self.parents_list.row(item))

    def _handle_parents_selection_changed(self):
        self.breed_button.setEnabled(self.parents_list.count() >= 2)
    def _handle_children_selection_changed(self):
        has_selection = bool(self.children_list.selectedItems())
        self.use_as_parents_button.setEnabled(has_selection)
        self.send_to_editor_button.setEnabled(len(self.children_list.selectedItems()) == 1)

    @Slot(int)
    def _on_model_combo_index_changed(self, index: int):
        pass

    def dragEnterEvent(self, event: QDragEnterEvent):
            if event.mimeData().hasText():
                event.acceptProposedAction()
    def dragMoveEvent(self, event: QDragMoveEvent): 
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasText():
            prompt_text = event.mimeData().text()
            item_data = next((data for data in self.all_prompts_data if (data.get('enhanced', {}).get('prompt') or data.get('original_prompt', '')) == prompt_text), None)
            if item_data:
                self._add_history_item_to_parents(item_data)
            event.acceptProposedAction()

    def closeEvent(self, event):
        for thread in [self.breeding_thread, self.mutation_thread, self.model_loading_thread]:
            if thread and thread.isRunning():
                thread.quit()
                thread.wait()
        if self.persistent_thumb_thread and self.persistent_thumb_thread.isRunning():
            self.persistent_thumb_thread.requestInterruption()
            self.shared_thumb_job_queue.put(None)
            self.persistent_thumb_thread.quit()
            self.persistent_thumb_thread.wait()
        super().closeEvent(event)