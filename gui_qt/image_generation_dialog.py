"""A Qt dialog for setting image generation options."""

import random
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QDialog,
    QCheckBox,
    QDialogButtonBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QInputDialog,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Slot, Qt, QThread, QObject, Signal

from core.config import config
from core.prompt_processor import PromptProcessor
from .per_model_override_dialogs import PerModelNegativePromptDialog, PerModelLoraDialog
from .custom_widgets import SmoothTextEdit

class AssetFetchWorker(QObject):
    """Worker to fetch InvokeAI assets in the background."""
    finished = Signal(dict)

    def __init__(self, base_model: str, verbose: bool = False):
        super().__init__()
        self.base_model = base_model
        self.verbose = verbose

    @Slot()
    def run(self):
        """Create a thread-local PromptProcessor and fetch assets."""
        try:
            # Create a new processor instance for this thread
            # to ensure thread safety with network clients.
            processor = PromptProcessor(verbose=self.verbose)
            main_models = processor.get_invokeai_models(base_model=self.base_model, model_type='main')
            lora_models = processor.get_invokeai_loras(base_model=self.base_model, model_type='lora')
            self.finished.emit({'success': True, 'main': main_models, 'lora': lora_models})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit({'success': False, 'error': str(e)})


class ImageGenerationOptionsDialog(QDialog):
    """A dialog for setting image generation options."""

    def __init__(self, parent, processor: PromptProcessor, prompt: str, initial_params: Optional[Dict] = None, is_editing: bool = False, force_random_seed: bool = False):
        if processor.verbose:
            print("\n--- VERBOSE: ImageGenerationOptionsDialog.__init__ ENTERED ---")
        super().__init__(parent)
        self.setWindowTitle("Image Generation Options")
        self.processor = processor
        self.prompt = prompt
        self.initial_params = initial_params or {}
        self.fetch_thread: Optional[QThread] = None
        self.is_editing = is_editing
        self.force_random_seed = force_random_seed
        # --- FIX: Make worker an instance variable to prevent garbage collection ---
        self.fetch_worker: Optional[AssetFetchWorker] = None

        # Data stores
        self.models_data: Dict[str, List[Dict]] = {}
        self.loras_data: Dict[str, List[Dict]] = {}
        self.schedulers = self.processor.invokeai_client.get_schedulers() if self.processor.is_invokeai_connected() else ["(InvokeAI not available)"]
        self.negative_prompts = self.processor.get_available_negative_prompts()

        # --- NEW: Storage for per-model overrides ---
        self.neg_prompt_overrides: Dict[str, str] = {}
        self.lora_overrides: Dict[str, List[Dict]] = {}

        # UI stores
        self.model_tree: Optional[QTreeWidget] = None
        self.lora_tree: Optional[QTreeWidget] = None

        self.has_been_resized = False

        self._create_widgets()
        self._connect_signals()
        self._set_initial_state()

    def showEvent(self, event):
        """Handles the show event to safely resize the dialog on first display."""
        super().showEvent(event)
        if not self.has_been_resized:
            screen = self.screen()
            if screen:
                screen_geometry = screen.availableGeometry()
                self.resize(int(screen_geometry.width() * 0.85), int(screen_geometry.height() * 0.9))
            else:
                # Fallback to a default size if the screen isn't available
                self.resize(1024, 768)
            
            try:
                self.move(screen.availableGeometry().center() - self.rect().center())
            except Exception:
                pass

            self.has_been_resized = True


    def _create_widgets(self):
        main_layout = QVBoxLayout(self)
        
        main_splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(main_splitter)

        # --- Top Pane: Models & LoRAs ---
        assets_pane = QWidget()
        assets_layout = QVBoxLayout(assets_pane)
        assets_layout.setContentsMargins(0, 0, 0, 0)
        
        base_model_group = QGroupBox("Base Model Type")
        base_model_layout = QHBoxLayout(base_model_group)
        self.sdxl_radio = QRadioButton("SDXL")
        self.sd15_radio = QRadioButton("SD-1.5")
        base_model_layout.addWidget(self.sdxl_radio)
        base_model_layout.addWidget(self.sd15_radio)
        assets_layout.addWidget(base_model_group)

        assets_splitter = QSplitter(Qt.Horizontal)
        
        models_group = QGroupBox("Models (Multi-select)")
        models_layout = QVBoxLayout(models_group)
        model_controls_layout = QHBoxLayout()
        self.model_search_edit = QLineEdit()
        self.model_search_edit.setPlaceholderText("Search models...")
        model_controls_layout.addWidget(self.model_search_edit)
        toggle_all_models_button = QPushButton("Toggle All")
        toggle_all_models_button.clicked.connect(self._toggle_all_models)
        model_controls_layout.addWidget(toggle_all_models_button)
        clear_models_button = QPushButton("Clear")
        clear_models_button.clicked.connect(self._clear_model_selection)
        model_controls_layout.addWidget(clear_models_button)
        models_layout.addLayout(model_controls_layout)

        self.model_tree = QTreeWidget()
        self.model_tree.setHeaderHidden(True)
        models_layout.addWidget(self.model_tree)
        assets_splitter.addWidget(models_group)

        loras_group = QGroupBox("LoRAs (Multi-select)")
        loras_layout = QVBoxLayout(loras_group)
        lora_controls_layout = QHBoxLayout()
        self.lora_search_edit = QLineEdit()
        self.lora_search_edit.setPlaceholderText("Search LoRAs...")
        lora_controls_layout.addWidget(self.lora_search_edit)
        clear_loras_button = QPushButton("Clear")
        clear_loras_button.clicked.connect(self._clear_lora_selection)
        lora_controls_layout.addWidget(clear_loras_button)
        loras_layout.addLayout(lora_controls_layout)
        self.lora_tree = QTreeWidget()
        self.lora_tree.setHeaderLabels(["LoRA", "Wt."])
        self.lora_tree.header().setStretchLastSection(False)
        self.lora_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.lora_tree.setColumnWidth(1, 80)
        loras_layout.addWidget(self.lora_tree)
        assets_splitter.addWidget(loras_group)

        assets_splitter.setSizes([300, 300])
        assets_layout.addWidget(assets_splitter, 1)
        main_splitter.addWidget(assets_pane)

        # --- Bottom Pane: Generation Settings (in Tabs) ---
        settings_tabs = QTabWidget()
        main_splitter.addWidget(settings_tabs)

        # -- Tab 1: Main Settings --
        main_settings_widget = QWidget()
        main_settings_layout = QGridLayout(main_settings_widget)
        main_settings_layout.setColumnStretch(1, 1)
        main_settings_layout.setColumnStretch(3, 1)

        # Row 0: Images & Steps
        main_settings_layout.addWidget(QLabel("Images per model:"), 0, 0)
        self.num_images_spin = QSpinBox()
        self.num_images_spin.setRange(1, 100)
        self.num_images_spin.setValue(self.initial_params.get("num_images", 1))
        main_settings_layout.addWidget(self.num_images_spin, 0, 1)

        main_settings_layout.addWidget(QLabel("Steps:"), 0, 2)
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 200)
        self.steps_spin.setValue(self.initial_params.get("steps", 30))
        main_settings_layout.addWidget(self.steps_spin, 0, 3)

        # Row 1: CFG Scale & Rescale
        main_settings_layout.addWidget(QLabel("CFG Scale:"), 1, 0)
        self.cfg_spin = QDoubleSpinBox()
        self.cfg_spin.setRange(1.0, 30.0)
        self.cfg_spin.setSingleStep(0.5)
        self.cfg_spin.setValue(self.initial_params.get("cfg_scale", 7.5))
        main_settings_layout.addWidget(self.cfg_spin, 1, 1)

        main_settings_layout.addWidget(QLabel("CFG Rescale:"), 1, 2)
        self.cfg_rescale_spin = QDoubleSpinBox()
        self.cfg_rescale_spin.setRange(0.0, 1.0)
        self.cfg_rescale_spin.setSingleStep(0.05)
        self.cfg_rescale_spin.setDecimals(2)
        self.cfg_rescale_spin.setValue(self.initial_params.get("cfg_rescale_multiplier", 0.0))
        main_settings_layout.addWidget(self.cfg_rescale_spin, 1, 3)

        # Row 2: Size & Aspect Ratio
        main_settings_layout.addWidget(QLabel("Size (W x H):"), 2, 0)
        size_layout = QHBoxLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(64, 4096)
        self.width_spin.setSingleStep(64)
        self.width_spin.setValue(self.initial_params.get("width", 1024))
        size_layout.addWidget(self.width_spin)
        size_layout.addWidget(QLabel("x"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(64, 4096)
        self.height_spin.setSingleStep(64)
        self.height_spin.setValue(self.initial_params.get("height", 1024))
        size_layout.addWidget(self.height_spin)
        main_settings_layout.addLayout(size_layout, 2, 1)

        aspect_button_layout = QGridLayout()
        aspect_ratios = {"1:1": (1,1), "4:3": (4,3), "16:9": (16,9), "3:4": (3,4), "9:16": (9,16)}
        row = 0
        col = 0
        for text, ratio in aspect_ratios.items():
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, r=ratio: self._set_aspect_ratio(r[0], r[1]))
            aspect_button_layout.addWidget(button, row, col)
            col += 1
            if col > 2:
                col = 0
                row += 1
        main_settings_layout.addLayout(aspect_button_layout, 2, 2, 1, 2)

        # Row 3: Scheduler and Seed
        main_settings_layout.addWidget(QLabel("Scheduler:"), 3, 0)
        self.scheduler_combo = QComboBox()
        self.scheduler_combo.addItems(self.schedulers)
        
        # --- FIX: Validate the initial scheduler and fall back to a default if it's not in the list ---
        initial_scheduler = self.initial_params.get("scheduler")
        if initial_scheduler not in self.schedulers:
            # If the saved scheduler isn't valid, try a sensible default
            if "dpmpp_2m" in self.schedulers:
                initial_scheduler = "dpmpp_2m"
            # If that's not available either, just pick the first one
            elif self.schedulers:
                initial_scheduler = self.schedulers[0]
            else:
                initial_scheduler = "" # Should not happen if connected

        if initial_scheduler:
             self.scheduler_combo.setCurrentText(initial_scheduler)

        main_settings_layout.addWidget(self.scheduler_combo, 3, 1) # Only spans 1 column now

        main_settings_layout.addWidget(QLabel("Seed:"), 3, 2)
        seed_layout = QHBoxLayout()
        self.seed_edit = QLineEdit()
        self.random_seed_checkbox = QCheckBox("Random") # Instantiated here
        self.randomize_seed_button = QPushButton("🎲") # Instantiated here
        self.randomize_seed_button.setFixedWidth(40)

        # Now, set properties based on conditions
        if self.force_random_seed:
            initial_seed = random.randint(0, 2**32 - 1)
            self.random_seed_checkbox.setChecked(True)
            self.seed_edit.setEnabled(False)
            self.randomize_seed_button.setEnabled(False)
        elif self.is_editing and "seed" in self.initial_params:
            initial_seed = self.initial_params["seed"]
            self.random_seed_checkbox.setChecked(False)
            self.random_seed_checkbox.setEnabled(False)
            self.seed_edit.setEnabled(True)
            self.randomize_seed_button.setEnabled(False)
        else:
            initial_seed = self.initial_params.get("seed", random.randint(0, 2**32 - 1))
            self.random_seed_checkbox.setChecked(self.initial_params.get("seed") is None)
            self.seed_edit.setEnabled(not self.random_seed_checkbox.isChecked())
            self.randomize_seed_button.setEnabled(not self.random_seed_checkbox.isChecked())
            
        self.seed_edit.setText(str(initial_seed))
        
        seed_layout.addWidget(self.seed_edit, 1)
        seed_layout.addWidget(self.randomize_seed_button)
        seed_layout.addWidget(self.random_seed_checkbox)
        main_settings_layout.addLayout(seed_layout, 3, 3)

        # Row 5: Overrides
        override_buttons_layout = QHBoxLayout()
        self.neg_prompt_override_button = QPushButton("Set Per-Model Negative Prompts...")
        self.neg_prompt_override_button.setEnabled(False)
        self.lora_override_button = QPushButton("Set Per-Model LoRAs...")
        self.lora_override_button.setEnabled(False)
        override_buttons_layout.addWidget(self.neg_prompt_override_button)
        override_buttons_layout.addWidget(self.lora_override_button)
        main_settings_layout.addLayout(override_buttons_layout, 5, 0, 1, 4)

        # Row 6: Save to Gallery
        self.save_to_gallery_check = QCheckBox("Save images to InvokeAI gallery")
        self.save_to_gallery_check.setChecked(self.initial_params.get("save_to_gallery", config.save_to_gallery_by_default))
        main_settings_layout.addWidget(self.save_to_gallery_check, 6, 0, 1, 4)

        settings_tabs.addTab(main_settings_widget, "Main")

        # -- Tab 2: Prompts --
        prompts_widget = QWidget()
        prompts_layout = QVBoxLayout(prompts_widget)
        neg_prompt_group = QGroupBox("Negative Prompt")
        neg_prompt_layout = QVBoxLayout(neg_prompt_group)
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Preset:"))
        self.neg_prompt_combo = QComboBox()
        preset_layout.addWidget(self.neg_prompt_combo, 1)
        self.save_preset_button = QPushButton("Save as Preset...")
        self.save_preset_button.setEnabled(False)
        preset_layout.addWidget(self.save_preset_button)
        neg_prompt_layout.addLayout(preset_layout)
        self.negative_prompt_text = SmoothTextEdit()
        neg_prompt_layout.addWidget(self.negative_prompt_text)
        self._populate_negative_prompt_presets()
        prompts_layout.addWidget(neg_prompt_group)
        settings_tabs.addTab(prompts_widget, "Prompts")

        # Set initial splitter sizes to give more space to the asset lists
        main_splitter.setSizes([600, 400])

        # --- Main Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Generate")
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.randomize_seed_button.clicked.connect(self._randomize_seed)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.sdxl_radio.toggled.connect(self._on_base_model_change)
        self.neg_prompt_combo.currentTextChanged.connect(self._on_negative_prompt_preset_selected)
        self.negative_prompt_text.textChanged.connect(self._on_negative_prompt_text_changed)
        self.save_preset_button.clicked.connect(self._save_negative_prompt_preset)
        self.model_search_edit.textChanged.connect(lambda: self._filter_tree(self.model_tree, self.model_search_edit.text()))
        self.lora_search_edit.textChanged.connect(lambda: self._filter_tree(self.lora_tree, self.lora_search_edit.text()))
        self.neg_prompt_override_button.clicked.connect(self._set_neg_prompt_overrides)
        self.lora_override_button.clicked.connect(self._set_lora_overrides)
        self.model_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.lora_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.model_tree.itemChanged.connect(self._update_generate_button_text) # Connect to update button text
        self.num_images_spin.valueChanged.connect(self._update_generate_button_text) # Connect to update button text
        self.random_seed_checkbox.toggled.connect(self._on_random_seed_toggled)

    @Slot(QTreeWidgetItem)
    def _on_item_double_clicked(self, item: QTreeWidgetItem):
        """Toggles the check state of a model or LoRA item on double-click."""
        current_state = item.checkState(0)
        new_state = Qt.CheckState.Unchecked if current_state == Qt.CheckState.Checked else Qt.CheckState.Checked
        item.setCheckState(0, new_state)

    def _set_initial_state(self):
        """Sets the initial state of the dialog and triggers the first asset fetch."""
        # Determine initial base model from params, defaulting to SDXL
        initial_base = self.initial_params.get('model', {}).get('base', 'sdxl')
        if initial_base in ['sd-1.5', 'sd-1']:
            self.sd15_radio.setChecked(True)
        else:
            self.sdxl_radio.setChecked(True)
        # Manually trigger the fetch since the toggled signal might not fire if it's the default
        self._fetch_and_populate_assets(force_fetch=False)
        self._update_generate_button_text() # Initial update of the button text
    
    def _fetch_and_populate_assets(self, force_fetch: bool = False):
        """Fetches assets in a background thread and populates the UI upon completion."""
        if not self.processor.is_invokeai_connected():
            QMessageBox.warning(self, "Not Connected", "InvokeAI is not configured or connected. Please set the URL in Settings.")
            return

        base_model = 'sdxl' if self.sdxl_radio.isChecked() else 'sd-1.5'

        if not force_fetch and self.models_data.get(base_model):
            self._populate_tree(self.model_tree, self.models_data.get(base_model, []), is_lora=False)
            self._populate_tree(self.lora_tree, self.loras_data.get(base_model, []), is_lora=True)
            return

        self.model_tree.clear()
        self.lora_tree.clear()
        self.model_tree.addTopLevelItem(QTreeWidgetItem(["Loading models..."]))
        self.lora_tree.addTopLevelItem(QTreeWidgetItem(["Loading LoRAs..."]))
        self.set_controls_enabled(False)

        # Stop any existing thread before starting a new one.
        if self.fetch_thread and self.fetch_thread.isRunning():
            self.fetch_thread.quit()
            self.fetch_thread.wait()

        self.fetch_thread = QThread(self)
        # Pass verbose flag to the worker, but not the processor instance
        self.fetch_worker = AssetFetchWorker(base_model, self.processor.verbose)
        self.fetch_worker.moveToThread(self.fetch_thread)

        self.fetch_thread.started.connect(self.fetch_worker.run)
        self.fetch_worker.finished.connect(self._on_assets_fetched)
        self.fetch_worker.finished.connect(self.fetch_thread.quit)
        self.fetch_worker.finished.connect(self.fetch_worker.deleteLater)
        self.fetch_thread.finished.connect(self.fetch_thread.deleteLater)
        self.fetch_thread.finished.connect(self._on_thread_finished)

        self.fetch_thread.start()

    @Slot()
    def _on_thread_finished(self):
        """Slot to nullify the thread reference once it has finished."""
        self.fetch_thread = None

    def _populate_negative_prompt_presets(self):
        """Populates the negative prompt combobox and sets the initial state."""
        self.neg_prompt_combo.blockSignals(True)
        self.neg_prompt_combo.clear()
        self.neg_prompt_combo.addItem("Custom")
        for p in self.negative_prompts:
            self.neg_prompt_combo.addItem(p['name'], p['prompt'])
        self.neg_prompt_combo.blockSignals(False)
        initial_text = self.initial_params.get("negative_prompt", self.processor.get_default_negative_prompt_text())
        self._set_initial_negative_prompt_preset(initial_text)

    @Slot()
    def _on_base_model_change(self):
        """Handles the base model radio button change by fetching new assets and updating the default resolution."""
        if self.sd15_radio.isChecked():
            self.width_spin.setValue(512)
            self.height_spin.setValue(512)
        else:
            self.width_spin.setValue(1024)
            self.height_spin.setValue(1024)
        self._fetch_and_populate_assets(force_fetch=False)

    def set_controls_enabled(self, enabled: bool):
        """Enables or disables all major controls in the dialog."""
        self.model_tree.setEnabled(enabled)
        self.lora_tree.setEnabled(enabled)
        self.button_box.setEnabled(enabled)
        self.sdxl_radio.setEnabled(enabled)
        self.sd15_radio.setEnabled(enabled)
        self.model_search_edit.setEnabled(enabled)
        self.lora_search_edit.setEnabled(enabled)
        self.neg_prompt_override_button.setEnabled(enabled and len(self._get_selected_models()) >= 1)
        self.lora_override_button.setEnabled(enabled and len(self._get_selected_models()) >= 1)

    @Slot(dict)
    def _on_assets_fetched(self, result: dict):
        """Handles the result from the AssetFetchWorker."""
        self.set_controls_enabled(True)
        base_model = 'sdxl' if self.sdxl_radio.isChecked() else 'sd-1.5'

        if result['success']:
            self.models_data[base_model] = result['main']
            self.loras_data[base_model] = result['lora']
            self._populate_tree(self.model_tree, self.models_data.get(base_model, []), is_lora=False)
            self._populate_tree(self.lora_tree, self.loras_data.get(base_model, []), is_lora=True)
            self._update_generate_button_text() # Update button text after models are populated
        else:
            QMessageBox.critical(self, "Fetch Error", f"Could not fetch assets from InvokeAI:\n{result['error']}")
            self.model_tree.clear()
            self.lora_tree.clear()
            self.model_tree.addTopLevelItem(QTreeWidgetItem(["Failed to load"]))
            self.lora_tree.addTopLevelItem(QTreeWidgetItem(["Failed to load"]))

    def _populate_tree(self, tree: QTreeWidget, items: List[Dict], is_lora: bool):
        tree.clear()
        initial_model_name = self.initial_params.get('model', {}).get('name') if self.is_editing and not is_lora else None

        # Sort the items case-insensitively by name before populating the tree
        sorted_items = sorted(items, key=lambda x: x.get('name', '').lower())

        for item_data in sorted_items:
            tree_item = QTreeWidgetItem(tree, [item_data['name']])
            tree_item.setFlags(tree_item.flags() | Qt.ItemIsUserCheckable)
            tree_item.setData(0, Qt.ItemDataRole.UserRole, item_data)

            # --- NEW: Pre-check the model if we are in editing mode ---
            is_checked = False
            if initial_model_name and item_data['name'] == initial_model_name:
                is_checked = True
            
            tree_item.setCheckState(0, Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)

            if is_lora:
                spin_box = QDoubleSpinBox()
                spin_box.setRange(-1.0, 2.0)
                spin_box.setSingleStep(0.1)
                spin_box.setDecimals(2)
                spin_box.setValue(0.75)
                
                # Check if this lora was in the initial params
                initial_lora = next((lora for lora in self.initial_params.get('loras', []) if lora.get('lora_object', {}).get('name') == item_data['name']), None)
                if initial_lora:
                    tree_item.setCheckState(0, Qt.CheckState.Checked)
                    spin_box.setValue(initial_lora.get('weight', 0.75))
                
                tree.setItemWidget(tree_item, 1, spin_box)

    @Slot()
    def _randomize_seed(self):
        self.seed_edit.setText(str(random.randint(0, 2**32 - 1)))

    @Slot(bool)
    def _on_random_seed_toggled(self, checked: bool):
        self.seed_edit.setEnabled(not checked)
        self.randomize_seed_button.setEnabled(not checked)
        if checked:
            self._randomize_seed() # Generate a new random seed when toggled to random

    @Slot(str)
    def _on_negative_prompt_preset_selected(self, preset_name: str):
        if preset_name == "Custom":
            return

        index = self.neg_prompt_combo.findText(preset_name)
        if index != -1:
            prompt_text = self.neg_prompt_combo.itemData(index)
            self.negative_prompt_text.setText(prompt_text)

    @Slot()
    def _on_negative_prompt_text_changed(self):
        current_text = self.negative_prompt_text.toPlainText().strip()
        
        # Find if the current text matches any preset
        matching_preset_name = None
        for i in range(self.neg_prompt_combo.count()):
            prompt_data = self.neg_prompt_combo.itemData(i)
            if prompt_data and prompt_data.strip() == current_text:
                matching_preset_name = self.neg_prompt_combo.itemText(i)
                break

        self.neg_prompt_combo.blockSignals(True)
        if matching_preset_name:
            self.neg_prompt_combo.setCurrentText(matching_preset_name)
            self.save_preset_button.setEnabled(False)
        else:
            self.neg_prompt_combo.setCurrentText("Custom")
            self.save_preset_button.setEnabled(bool(current_text))
        self.neg_prompt_combo.blockSignals(False)

    def _set_initial_negative_prompt_preset(self, initial_text: str):
        """Sets the initial state of the negative prompt widgets."""
        self.negative_prompt_text.setText(initial_text)
        self._on_negative_prompt_text_changed() # This will sync the combobox

    @Slot()
    def _save_negative_prompt_preset(self):
        prompt_text = self.negative_prompt_text.toPlainText().strip()
        if not prompt_text:
            return

        preset_name, ok = QInputDialog.getText(self, "Save Negative Prompt Preset", "Enter a name for the new preset:")
        if not ok or not preset_name:
            return

        # Check for existing name
        if any(p['name'].lower() == preset_name.lower() for p in self.negative_prompts):
            QMessageBox.warning(self, "Preset Exists", f"A preset named '{preset_name}' already exists.")
            return

        try:
            filename = preset_name.replace(' ', '_').lower()
            content_data = {"name": preset_name, "prompt": prompt_text}
            self.processor.create_system_prompt(filename, 'negative_prompt', content_data=content_data)
            
            # Refresh the list
            self.negative_prompts = self.processor.get_available_negative_prompts()
            self._populate_negative_prompt_presets()
            self.neg_prompt_combo.setCurrentText(preset_name)

            QMessageBox.information(self, "Success", f"Saved new preset '{preset_name}'.")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save preset:\n{e}")

    @Slot(QTreeWidgetItem, int)
    def _on_model_item_changed(self, item: QTreeWidgetItem, column: int):
        """When a model is checked, update the resolution to its default."""
        if column != 0 or item.checkState(0) != Qt.CheckState.Checked:
            return

        # --- NEW: Update override button states on selection change ---
        selected_count = len([i for i in range(self.model_tree.topLevelItemCount()) if self.model_tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked])
        can_override = selected_count > 1
        self.neg_prompt_override_button.setEnabled(can_override)
        self.lora_override_button.setEnabled(can_override)

        model_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not model_data:
            return

        # The default resolution is stored in the 'default_settings' dictionary.
        default_settings = model_data.get('default_settings', {})
        width = default_settings.get('width')
        height = default_settings.get('height')

        if width and height:
            self.width_spin.setValue(width)
            self.height_spin.setValue(height)

    @Slot(int, int)
    def _set_aspect_ratio(self, aspect_w: int, aspect_h: int):
        """Sets the width and height spins based on a selected aspect ratio."""
        is_sdxl = self.sdxl_radio.isChecked()
        
        # Define base resolutions for SDXL and SD1.5
        # Using common generation sizes that are multiples of 64
        if is_sdxl:
            resolutions = {
                (1, 1): (1024, 1024),
                (4, 3): (1152, 864),
                (3, 4): (864, 1152),
                (16, 9): (1344, 768),
                (9, 16): (768, 1344),
            }
        else: # SD-1.5
            resolutions = {
                (1, 1): (512, 512),
                (4, 3): (512, 384),
                (3, 4): (384, 512),
                (16, 9): (512, 288),
                (9, 16): (288, 512),
            }
        
        width, height = resolutions.get((aspect_w, aspect_h), (1024, 1024))
        self.width_spin.setValue(width)
        self.height_spin.setValue(height)

    def _toggle_all_models(self):
        """Toggles the check state of all currently visible models in the tree."""
        if not self.model_tree:
            return

        visible_items = []
        iterator = QTreeWidgetItemIterator(self.model_tree)
        while iterator.value():
            item = iterator.value()
            if not item.isHidden():
                visible_items.append(item)
            iterator += 1
        
        if not visible_items:
            return

        # If any visible item is unchecked, the new state is to check all. Otherwise, uncheck all.
        new_state = any(item.checkState(0) == Qt.CheckState.Unchecked for item in visible_items)
        check_state_to_set = Qt.CheckState.Checked if new_state else Qt.CheckState.Unchecked

        for item in visible_items:
            item.setCheckState(0, check_state_to_set)

    def _clear_model_selection(self):
        """Clears the selection in the model tree."""
        if not self.model_tree:
            return
        for i in range(self.model_tree.topLevelItemCount()):
            item = self.model_tree.topLevelItem(i)
            item.setCheckState(0, Qt.CheckState.Unchecked)

    def _clear_lora_selection(self):
        """Clears the selection in the LoRA tree."""
        if not self.lora_tree:
            return
        for i in range(self.lora_tree.topLevelItemCount()):
            item = self.lora_tree.topLevelItem(i)
            item.setCheckState(0, Qt.CheckState.Unchecked)

    @Slot()
    @Slot()
    def _update_override_button_states(self):
        """Updates the enabled state of the per-model override buttons."""
        self.set_controls_enabled(True)
        self._update_generate_button_text() # Also update button text when models change

    def _set_neg_prompt_overrides(self):
        """Opens the dialog to set per-model negative prompt overrides."""
        selected_model_names = [self.model_tree.topLevelItem(i).text(0) for i in range(self.model_tree.topLevelItemCount()) if self.model_tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
        if len(selected_model_names) < 2:
            return
        
        default_prompt = self.negative_prompt_text.toPlainText().strip()
        dialog = PerModelNegativePromptDialog(self, self.processor, selected_model_names, self.neg_prompt_overrides, default_prompt)
        if dialog.exec() == QDialog.Accepted and dialog.result is not None:
            self.neg_prompt_overrides = dialog.result
            QMessageBox.information(self, "Overrides Set", "Per-model negative prompts have been set for this session.")

    @Slot()
    def _set_lora_overrides(self):
        """Opens the dialog to set per-model LoRA overrides."""
        selected_model_names = [self.model_tree.topLevelItem(i).text(0) for i in range(self.model_tree.topLevelItemCount()) if self.model_tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
        if len(selected_model_names) < 2:
            return

        # Get all available LoRAs for the current base model type
        base_model_type = 'sdxl' if self.sdxl_radio.isChecked() else 'sd-1.5'
        all_loras_for_base = self.loras_data.get(base_model_type, [])

        # Get the current global LoRA selection as a default
        global_loras = self._get_selected_loras()

        dialog = PerModelLoraDialog(self, self.processor, selected_model_names, all_loras_for_base, global_loras, self.lora_overrides)
        if dialog.exec() == QDialog.Accepted and dialog.result is not None:
            self.lora_overrides = dialog.result
            QMessageBox.information(self, "Overrides Set", "Per-model LoRA stacks have been set for this session.")

    @Slot(str)
    def _filter_tree(self, tree: QTreeWidget, search_text: str):
        """Filters the items in the given tree widget based on the search text."""
        search_term = search_text.lower()

        # Iterate through all top-level items in the flat list
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            is_visible = search_term in item.text(0).lower()
            item.setHidden(not is_visible)

    def _get_selected_models(self) -> List[Dict[str, Any]]:
        """Helper to get the currently selected models from the main tree."""
        selected_models = []
        if not self.model_tree:
            return selected_models
        iterator = QTreeWidgetItemIterator(self.model_tree)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                model_data = item.data(0, Qt.ItemDataRole.UserRole)
                if model_data:
                    selected_models.append(model_data)
            iterator += 1
        return selected_models

    def _get_selected_loras(self) -> List[Dict[str, Any]]:
        """Helper to get the currently selected LoRAs from the main tree."""
        selected_loras = []
        iterator = QTreeWidgetItemIterator(self.lora_tree)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                lora_data = item.data(0, Qt.ItemDataRole.UserRole)
                weight_widget = self.lora_tree.itemWidget(item, 1)
                weight = weight_widget.value() if weight_widget else 0.75
                selected_loras.append({'lora_object': lora_data, 'weight': weight})
            iterator += 1
        return selected_loras

    def _update_generate_button_text(self):
        """Updates the text of the Generate button to show the total number of images."""
        num_images_per_model = self.num_images_spin.value()
        selected_models_count = len(self._get_selected_models())
        total_images = num_images_per_model * selected_models_count
        
        generate_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if generate_button:
            if total_images > 0:
                generate_button.setText(f"Generate ({total_images})")
            else:
                generate_button.setText("Generate")

    def get_options(self) -> Dict[str, Any]:
        """Returns the selected generation options, structured for batch processing."""
        # This creates a list of dictionaries, where each dictionary contains the model,
        # its specific LoRAs, and its specific negative prompt. This matches the
        # structure now expected by the generation workflow.
        final_model_list = []
        iterator = QTreeWidgetItemIterator(self.model_tree)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                model_obj = item.data(0, Qt.ItemDataRole.UserRole)
                model_name = model_obj['name']
                final_model_list.append({
                    'model': model_obj,
                    'loras': self.lora_overrides.get(model_name, self._get_selected_loras()),
                    'negative_prompt': self.neg_prompt_overrides.get(model_name, self.negative_prompt_text.toPlainText().strip())
                })
            iterator += 1

        return {
            'models': final_model_list, # The corrected, structured list
            'negative_prompt': self.negative_prompt_text.toPlainText().strip(), # Keep global for other uses
            'num_images': self.num_images_spin.value(),
            'steps': self.steps_spin.value(),
            'cfg_scale': self.cfg_spin.value(),
            'scheduler': self.scheduler_combo.currentText(),
            'seed': int(self.seed_edit.text()),
            'width': self.width_spin.value(),
            'height': self.height_spin.value(),
            'cfg_rescale_multiplier': self.cfg_rescale_spin.value(),
            'save_to_gallery': self.save_to_gallery_check.isChecked(),
        }

    def accept(self):
        """Overrides the default accept to validate model selection."""
        selected_models = self._get_selected_models()
        if not selected_models:
            QMessageBox.warning(self, "No Models Selected", "You must select at least one model to generate images.")
            return # Keep the dialog open

        # --- FIX: Validate that the seed is a valid integer before accepting ---
        try:
            int(self.seed_edit.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Seed", "The seed must be a valid integer.")
            return # Keep the dialog open

        super().accept()