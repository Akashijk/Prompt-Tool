"""The new Qt-based main application window."""

import re
import random
import json
import os
import uuid
from typing import Optional, List, Dict, Any
from PySide6.QtGui import QAction, QKeySequence, QActionGroup, QSyntaxHighlighter, QTextCharFormat, QColor, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QMenuBar, QMenu,
    QLabel, QComboBox, QPushButton, QTextEdit, QSplitter, QGroupBox, QLineEdit, QInputDialog, QMessageBox, QCheckBox, QFileDialog, QStatusBar,
    QDialog, QGridLayout
)
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer, QUrl

# The magic! We import the existing core logic directly. No changes needed there.
from core.prompt_processor import PromptProcessor
from core.config import config, load_settings, save_settings
from .enhancement_window import EnhancementResultWindow
from .history_viewer import HistoryViewerWindow
from .wildcard_manager import WildcardManagerWindow
from .image_generation_dialog import ImageGenerationOptionsDialog
from .multi_image_preview_dialog import MultiImagePreviewDialog
from .brainstorming_window import BrainstormingWindow
from .image_interrogator import ImageInterrogatorWindow
from .prompt_evolver import PromptEvolverWindow
from .model_stats_window import ModelStatsWindow
from .diff_confirmation_dialog import DiffConfirmationDialog
from .settings_window import SettingsWindow
from .asset_prefix_editor import AssetPrefixEditorWindow
from .custom_widgets import LinkOnlyTextBrowser, SmoothTextEdit
from .system_prompt_editor import SystemPromptEditorWindow
from .favorite_images_viewer import FavoriteImagesViewer
from .theme_manager import ThemeManager
from .text_preview_mixin import TextPreviewMixin
from .model_usage_manager import ModelUsageManager
from .wildcard_inserter import WildcardInserter
from .dependency_graph_window import DependencyGraphWindow
from .png_text_viewer import PNGTextViewerWindow


import threading

class NetworkWorker(QObject):
    """
    A worker object that runs network-dependent tasks in a separate thread.
    """
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor, cancellation_event: threading.Event):
        super().__init__()
        self.processor = processor
        self.cancellation_event = cancellation_event

    @Slot()
    def run(self):
        """The main work method. This runs in the background thread."""
        try:
            if self.cancellation_event.is_set():
                self.finished.emit({'success': False, 'error': 'Cancelled'})
                return
            
            try:
                self.processor.invokeai_client.check_server_compatibility()
            except Exception as e:
                pass # Ignore connection errors for now, will be handled later


            if self.cancellation_event.is_set():
                self.finished.emit({'success': False, 'error': 'Cancelled'})
                return
            models = self.processor.get_ollama_models()

            self.finished.emit({'success': True, 'models': models})
        except Exception as e:
            if not self.cancellation_event.is_set():
                self.finished.emit({'success': False, 'error': str(e)})


class Worker(QObject):
    """
    A worker object that runs tasks in a separate thread.
    This is the standard Qt way to handle background tasks without freezing the UI.
    """
    # Define a signal that will be emitted when the task is finished.
    # It will carry a dictionary as its payload.
    finished = Signal(dict)

    def __init__(self, verbose: bool):
        super().__init__()
        self.verbose = verbose

    @Slot()
    def run(self):
        """The main work method. This runs in the background thread."""
        try:
            processor = PromptProcessor(verbose=self.verbose)
            processor.initialize()
            # These are local file operations and should be fast
            templates = processor.get_available_templates()
            wildcard_files = processor.get_wildcard_files()
            
            # Emit the 'finished' signal with the results.
            self.finished.emit({'success': True, 'processor': processor, 'templates': templates, 'wildcard_files': wildcard_files})
        except Exception as e:
            # This is a catch-all for any other unexpected errors
            self.finished.emit({'success': False, 'error': str(e)})

class PromptGenerationWorker(QObject):
    """A worker to generate a prompt in the background."""
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor, template_content: str, seed: int, existing_context: Optional[Dict] = None, force_reroll: Optional[List[str]] = None):
        super().__init__()
        self.processor = processor
        self.template_content = template_content
        self.seed = seed
        self.existing_context = existing_context
        self.force_reroll = force_reroll

    @Slot()
    def run(self):
        """The main work method. This runs in the background thread."""
        try:
            segments, context = self.processor.generate_single_structured_prompt(
                self.template_content,
                seed=self.seed,
                existing_context=self.existing_context,
                force_reroll=self.force_reroll
            )
            self.finished.emit({'success': True, 'segments': segments, 'context': context})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

class TemplateEnhancementWorker(QObject):
    """Worker to enhance a template in the background."""
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor, template_content: str, model: str):
        super().__init__()
        self.processor = processor
        self.template_content = template_content
        self.model = model

    @Slot()
    def run(self):
        try:
            enhanced_content = self.processor.ai_enhance_template(self.template_content, self.model)
            self.finished.emit({'success': True, 'original': self.template_content, 'enhanced': enhanced_content})
        except Exception as e:
            print(f"ERROR in TemplateEnhancementWorker: {e}")
            self.finished.emit({'success': False, 'error': str(e)})


class WildcardHighlighter(QSyntaxHighlighter):
    """A syntax highlighter for wildcards in the template editor."""
    def __init__(self, document, parent_app):
        super().__init__(document)
        self.parent_app = parent_app
        self.highlighting_rules = []

        self.light_theme_format = QTextCharFormat()
        self.light_theme_format.setForeground(QColor("#00008B")) # Dark Blue
        self.light_theme_format.setFontWeight(700) # Bold

        self.dark_theme_format = QTextCharFormat()
        self.dark_theme_format.setForeground(QColor("#FFFF00")) # Bright Yellow
        self.dark_theme_format.setFontWeight(700) # Bold

    def highlightBlock(self, text):
        current_theme = config.theme
        wildcard_format = self.dark_theme_format if current_theme == "dark" else self.light_theme_format

        pattern = re.compile(r"__([a-zA-Z0-9_.\\s-]+?)__")
        for match in pattern.finditer(text):
            start, end = match.span()
            self.setFormat(start, end - start, wildcard_format)


class GUIApp(QMainWindow, TextPreviewMixin):
    """The main application window, rewritten using PyQt/PySide."""
    ollama_model_changed = Signal(str)

    def __init__(self, verbose: bool = False):
        super().__init__()
        TextPreviewMixin.__init__(self)
        self.setWindowTitle("Prompt Tool GUI (Qt Version)")

        try:
            # Smartly set window size and position
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.setGeometry(
                screen_geometry.x(),
                screen_geometry.y(),
                int(screen_geometry.width() * 0.9),
                int(screen_geometry.height() * 0.9)
            )
            # Center the window on the screen
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            self.setGeometry(100, 100, 1280, 800)

        settings = load_settings()
        config.theme = settings.get('theme', 'light')
        config.save_to_gallery_by_default = settings.get('save_to_gallery_by_default', False)

        self.processor: Optional[PromptProcessor] = None
        self.verbose = verbose

        self.theme_manager = ThemeManager()
        self.model_usage_manager: Optional[ModelUsageManager] = None
        self.wildcard_inserter: Optional[WildcardInserter] = None

        self.last_generation_result: Dict = {}
        self.current_structured_prompt: List = []
        self.enhancement_windows: List[EnhancementResultWindow] = []
        self.brainstorming_window: Optional[BrainstormingWindow] = None
        self.image_preview_dialogs: List[MultiImagePreviewDialog] = []
        self.model_stats_window: Optional[ModelStatsWindow] = None
        self.prompt_evolver_window: Optional[PromptEvolverWindow] = None
        self.image_interrogator_window: Optional[ImageInterrogatorWindow] = None
        self.history_viewer_window: Optional[HistoryViewerWindow] = None
        self.settings_window: Optional[SettingsWindow] = None
        self.wildcard_manager_window: Optional[WildcardManagerWindow] = None
        self.favorite_images_viewer_window: Optional[FavoriteImagesViewer] = None
        self.asset_prefix_editor_window: Optional[AssetPrefixEditorWindow] = None
        self.system_prompt_editor_window: Optional[SystemPromptEditorWindow] = None
        self.png_text_viewer_window: Optional[PNGTextViewerWindow] = None
        self.loading_animation_timer: Optional[QTimer] = None
        self.loading_animation_chars = ["/", "-", "\\", "|"]
        self.loading_animation_index = 0
        self.current_ollama_model: Optional[str] = None
        self.current_history_entry_id: Optional[str] = None
        
        self.live_update_timer = QTimer(self)
        self.live_update_timer.setSingleShot(True)
        self.live_update_timer.setInterval(500)
        
        self.template_editor_text: Optional[QTextEdit] = None
        self.missing_wildcards_container: Optional[QWidget] = None

        # Thread attributes must be initialized to None
        self.thread: Optional[QThread] = None
        self.network_thread: Optional[QThread] = None
        self.gen_thread: Optional[QThread] = None
        self.enhance_thread: Optional[QThread] = None

        self.cancellation_event = threading.Event()

        self._create_widgets()
        self.theme_manager.apply_theme(config.theme)
        self._create_menu_bar()
        self._create_status_bar()
        self._connect_signals()
        self._start_initial_load()



    def closeEvent(self, event):
        """Ensures all child windows are closed before the main application exits."""
        all_windows = []
        if self.wildcard_manager_window: all_windows.append(self.wildcard_manager_window)
        if self.history_viewer_window: all_windows.append(self.history_viewer_window)
        if self.brainstorming_window: all_windows.append(self.brainstorming_window)
        if self.prompt_evolver_window: all_windows.append(self.prompt_evolver_window)
        if self.image_interrogator_window: all_windows.append(self.image_interrogator_window)
        if self.model_stats_window: all_windows.append(self.model_stats_window)
        if self.asset_prefix_editor_window: all_windows.append(self.asset_prefix_editor_window)
        if self.system_prompt_editor_window: all_windows.append(self.system_prompt_editor_window)
        if self.settings_window: all_windows.append(self.settings_window)
        if self.favorite_images_viewer_window: all_windows.append(self.favorite_images_viewer_window)
        if self.png_text_viewer_window: all_windows.append(self.png_text_viewer_window)
        
        all_windows.extend(self.enhancement_windows)
        all_windows.extend(self.image_preview_dialogs)

        for window in all_windows:
            if window and window.isVisible():
                window.close()
        
        super().closeEvent(event)

    @Slot()
    def _on_any_thread_finished(self):
        """Finds which thread just finished and sets its attribute to None."""
        finished_thread = self.sender()
        if not isinstance(finished_thread, QThread):
            return

        thread_attrs = ['thread', 'network_thread', 'gen_thread', 'enhance_thread']
        for attr in thread_attrs:
            if hasattr(self, attr) and getattr(self, attr) is finished_thread:
                setattr(self, attr, None)
                break

    def _create_widgets(self):
        """Create the main widgets and layout for the window."""
        # A central widget is required for a QMainWindow.
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # --- NEW: Main layout is now a horizontal splitter ---
        self.main_layout = QHBoxLayout(central_widget)
        main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter = main_splitter # Store a reference to it

        # --- Left Pane (Editor, Preview, Actions) ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # --- Top Controls ---
        top_controls_layout = QHBoxLayout()
        
        self.template_label = QLabel("Template:")
        self.template_combo = QComboBox()
        self.template_combo.setEnabled(False)
        self.template_combo.setPlaceholderText("Loading templates...")

        self.model_label = QLabel("Model:")
        self.model_combo = QComboBox()
        self.model_combo.setEnabled(False)
        self.model_combo.setPlaceholderText("Loading models...")

        top_controls_layout.addWidget(self.template_label)
        top_controls_layout.addWidget(self.template_combo, 1) # Stretch factor of 1
        top_controls_layout.addWidget(self.model_label)
        top_controls_layout.addWidget(self.model_combo, 1) # Stretch factor of 1
        
        left_layout.addLayout(top_controls_layout)

        # --- Main Paned View (Editor and Preview) ---
        self.splitter = QSplitter(Qt.Vertical)
        
        # Template Editor
        self.template_editor_group = QGroupBox("Template Content")
        template_editor_layout = QVBoxLayout()
        self.template_editor_text = SmoothTextEdit()
        self.template_editor_text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.highlighter = WildcardHighlighter(self.template_editor_text.document(), self)
        template_editor_layout.addWidget(self.template_editor_text)
        self.template_editor_group.setLayout(template_editor_layout)
        
        # Prompt Preview
        # --- CHANGE: Use QTextBrowser for clickable links ---
        self.prompt_preview_group = QGroupBox("Generated Prompt")
        prompt_preview_layout = QVBoxLayout()
        self.prompt_preview_text = LinkOnlyTextBrowser()
        self.prompt_preview_text.setOpenExternalLinks(False) # We handle links internally
        self.prompt_preview_text.setReadOnly(True)
        prompt_preview_layout.addWidget(self.prompt_preview_text)
        self.prompt_preview_group.setLayout(prompt_preview_layout)

        self.splitter.addWidget(self.template_editor_group)
        self.splitter.addWidget(self.prompt_preview_group)
        self.splitter.setSizes([300, 400]) # Initial size ratio

        # --- NEW: Missing Wildcards Display ---
        self.missing_wildcards_frame = QGroupBox("Missing Wildcards (Click to generate)")
        self.missing_wildcards_layout = QHBoxLayout(self.missing_wildcards_frame)
        self.missing_wildcards_container = QWidget() # A container to hold the labels
        self.missing_wildcards_container_layout = QHBoxLayout(self.missing_wildcards_container)
        self.missing_wildcards_layout.addWidget(self.missing_wildcards_container)
        self.missing_wildcards_frame.setVisible(False) # Hide by default

        left_layout.addWidget(self.splitter)

        # --- Action Bar ---
        # A container to hold the action groups side-by-side
        action_bar_container = QWidget()
        action_bar_main_layout = QHBoxLayout(action_bar_container)
        action_bar_main_layout.setContentsMargins(0, 0, 0, 0)

        # Left side: Generate and Output actions
        left_actions_layout = QVBoxLayout()

        # Generate Actions Group
        generate_actions_group = QGroupBox("Generate Actions")
        generate_actions_layout = QHBoxLayout()
        self.enhance_template_button = QPushButton("Enhance Template (AI)")
        self.generate_preview_button = QPushButton("Generate Next Preview")
        self.enhance_prompt_button = QPushButton("Enhance This Prompt")
        generate_actions_layout.addWidget(self.enhance_template_button)
        generate_actions_layout.addWidget(self.generate_preview_button)
        generate_actions_layout.addWidget(self.enhance_prompt_button)
        generate_actions_group.setLayout(generate_actions_layout)
        left_actions_layout.addWidget(generate_actions_group)

        # Output Actions Group
        output_actions_group = QGroupBox("Output Actions")
        output_actions_layout = QHBoxLayout()
        self.copy_prompt_button = QPushButton("Copy Prompt")
        self.save_as_template_button = QPushButton("Save as Template")
        self.generate_image_button = QPushButton("Generate Image")
        output_actions_layout.addWidget(self.copy_prompt_button)
        output_actions_layout.addWidget(self.save_as_template_button)
        output_actions_layout.addStretch()
        output_actions_layout.addWidget(self.generate_image_button)
        output_actions_group.setLayout(output_actions_layout)
        left_actions_layout.addWidget(output_actions_group)

        action_bar_main_layout.addLayout(left_actions_layout)

        # --- Variations Group ---
        self.variations_group = QGroupBox("Variations")
        self.variations_layout = QGridLayout(self.variations_group) # Changed to QGridLayout
        self.variation_checkboxes: Dict[str, QCheckBox] = {}
        action_bar_main_layout.addWidget(self.variations_group)
        action_bar_main_layout.addStretch(1)

        # Seed Controls
        seed_controls_group = QGroupBox("Seed Controls")
        seed_controls_layout = QHBoxLayout()
        seed_controls_layout.setAlignment(Qt.AlignVCenter) # Align items vertically in the center
        seed_label = QLabel("Seed:")
        seed_label.setFixedHeight(24) # Set a reasonable fixed height
        seed_controls_layout.addWidget(seed_label)
        self.seed_edit = QLineEdit()
        self.seed_edit.setFixedWidth(120)
        seed_controls_layout.addWidget(self.seed_edit)
        self.randomize_seed_button = QPushButton("🎲")
        self.randomize_seed_button.setFixedWidth(30)
        seed_controls_layout.addWidget(self.randomize_seed_button)
        self.random_seed_checkbox = QCheckBox("Random")
        self.random_seed_checkbox.setChecked(True)
        seed_controls_layout.addWidget(self.random_seed_checkbox)
        seed_controls_group.setLayout(seed_controls_layout)
        action_bar_main_layout.addWidget(seed_controls_group)

        left_layout.addWidget(action_bar_container)
        left_layout.addWidget(self.missing_wildcards_frame) # Add missing wildcards frame at the bottom
        main_splitter.addWidget(left_widget)

        # --- Right Pane (Wildcard Inserter) ---
        self.wildcard_group = QGroupBox("Insert Wildcard")
        wildcard_layout = QVBoxLayout(self.wildcard_group)
        self.wildcard_placeholder = QLabel("Loading wildcards...")
        self.wildcard_placeholder.setAlignment(Qt.AlignCenter)
        wildcard_layout.addWidget(self.wildcard_placeholder)
        main_splitter.addWidget(self.wildcard_group)

        self.main_layout.addWidget(main_splitter)

    @Slot(str)
    def _insert_wildcard_into_editor(self, wildcard_name: str):
        """Inserts a wildcard tag into the template editor, replacing an existing one if the cursor is inside it."""
        cursor = self.template_editor_text.textCursor()
        current_pos = cursor.position()
        text = self.template_editor_text.toPlainText()
        
        # Define the wildcard pattern (consistent with WildcardHighlighter)
        wildcard_pattern = r"__([a-zA-Z0-9_.\\s-]+?)__"
        
        found_existing_wildcard = False
        
        # Strategy:
        # 1. Check if cursor is strictly inside a wildcard.
        # 2. Check if cursor is exactly at the end of a wildcard.
        # 3. Check if cursor is exactly at the start of a wildcard.
        
        # Search a reasonable window around the cursor
        window_start = max(0, current_pos - 50) # Increased window size
        window_end = min(len(text), current_pos + 50)
        search_substring = text[window_start:window_end]

        for match in re.finditer(wildcard_pattern, search_substring):
            match_start_abs = window_start + match.start()
            match_end_abs = window_start + match.end()
            
            # Case 1: Cursor is strictly inside the wildcard
            if match_start_abs < current_pos < match_end_abs:
                cursor.setPosition(match_start_abs)
                cursor.setPosition(match_end_abs, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                found_existing_wildcard = True
                break
            # Case 2: Cursor is exactly at the end of a wildcard (e.g., __wildcard1__|)
            elif current_pos == match_end_abs:
                cursor.setPosition(match_start_abs)
                cursor.setPosition(match_end_abs, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                found_existing_wildcard = True
                break
            # Case 3: Cursor is exactly at the start of a wildcard (e.g., |__wildcard2__)
            elif current_pos == match_start_abs:
                cursor.setPosition(match_start_abs)
                cursor.setPosition(match_end_abs, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                found_existing_wildcard = True
                break
        
        # Insert the new wildcard tag
        cursor.insertText(f"__{wildcard_name}__")
        self.template_editor_text.setTextCursor(cursor) # Ensure cursor is updated
        self.live_update_timer.start() # Trigger a live update after insertion

    def _connect_signals(self):
        """Connect widget signals to corresponding slots."""
        self.template_combo.currentTextChanged.connect(self._on_template_select)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.generate_preview_button.clicked.connect(self._on_generate_preview_clicked)
        self.randomize_seed_button.clicked.connect(self._randomize_seed)
        self.template_editor_text.textChanged.connect(self.live_update_timer.start)
        self.live_update_timer.timeout.connect(self._perform_live_update)
        self.copy_prompt_button.clicked.connect(self._on_copy_prompt_clicked)
        self.save_as_template_button.clicked.connect(self._on_save_as_template_clicked)
        self.enhance_template_button.clicked.connect(self._on_enhance_template_clicked)
        self.prompt_preview_text.anchorClicked.connect(self._on_wildcard_link_clicked)
        self.template_editor_text.customContextMenuRequested.connect(self._show_template_editor_context_menu)
        self.generate_image_button.clicked.connect(self._on_generate_image_clicked)
        self.enhance_prompt_button.clicked.connect(self._on_enhance_prompt_clicked)

    def _start_initial_load(self):
        """Starts the background thread to load initial data."""
        # --- Local Worker ---
        self.thread = QThread(self)
        self.worker = Worker(self.verbose)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_load_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._on_any_thread_finished)
        self.thread.start()

        self._start_loading_animation("Initializing...")

    @Slot(dict)
    def _on_network_load_finished(self, result: Dict):
        if result['success']:
            models = result.get('models', [])
            model_names = [m['name'] for m in models]
            self.model_combo.clear()
            self.model_combo.addItems(model_names)

            if config.DEFAULT_OLLAMA_MODEL and config.DEFAULT_OLLAMA_MODEL in model_names:
                self.model_combo.setCurrentText(config.DEFAULT_OLLAMA_MODEL)
            elif model_names:
                self.model_combo.setCurrentIndex(0)

            if model_names:
                self.current_ollama_model = self.model_combo.currentText()
            self.model_combo.setEnabled(True)
            self.model_combo.setPlaceholderText("Select a model")
        else:
            self.model_combo.setPlaceholderText("Failed to load models")
            print(f"Error during network load: {result['error']}")

    @Slot(dict)
    def _on_load_finished(self, result: Dict):
        """This method is the 'slot' that receives the result from the local worker."""
        if result['success']:
            self.processor = result['processor']
            self.model_usage_manager = ModelUsageManager(self.processor)

            # Create and set the wildcard inserter
            self.wildcard_inserter = WildcardInserter(self, self.processor, self._insert_wildcard_into_editor, self._open_wildcard_manager)
            if self.wildcard_placeholder:
                self.wildcard_group.layout().removeWidget(self.wildcard_placeholder)
                self.wildcard_placeholder.deleteLater()
                self.wildcard_placeholder = None
            self.wildcard_group.layout().addWidget(self.wildcard_inserter)

            # Populate templates
            templates = result.get('templates', [])
            self.template_combo.clear()
            self.template_combo.addItems(templates)
            self.template_combo.setEnabled(True)
            self.template_combo.setPlaceholderText("Select a template")

            # Populate wildcards
            wildcard_files = result.get('wildcard_files', [])
            self.wildcard_inserter.populate(wildcard_files)

            # Set an initial random seed
            self._randomize_seed()
            
            # Set initial button states
            self._update_action_button_states()
            self._update_action_bar_variations()
            self._stop_loading_animation("Ready")

            # Now that the UI is populated, set the splitter sizes.
            self.main_splitter.setSizes([self.width() * 0.7, self.width() * 0.3])

            # Start the network worker now that the processor is available
            self.network_thread = QThread(self)
            self.network_worker = NetworkWorker(self.processor, self.cancellation_event)
            self.network_worker.moveToThread(self.network_thread)
            self.network_thread.started.connect(self.network_worker.run)
            self.network_worker.finished.connect(self._on_network_load_finished)
            self.network_worker.finished.connect(self.network_thread.quit)
            self.network_worker.finished.connect(self.network_worker.deleteLater)
            self.network_thread.finished.connect(self.network_thread.deleteLater)
            self.network_thread.finished.connect(self._on_any_thread_finished)
            self.network_thread.start()

        else:
            # Here you would show an error dialog.
            error_message = result.get('error', 'An unknown error occurred.')
            print(f"Error during initial load: {error_message}")
            self.template_combo.setPlaceholderText("Failed to load templates")
            self._stop_loading_animation(f"Error: {error_message}")

    def _on_generate_preview_clicked(self):
        """Handles the 'Generate Next Preview' button click."""
        self._perform_live_update(use_existing_context=False)

    def _perform_live_update(self, use_existing_context: bool = True, force_reroll: Optional[List[str]] = None):
        """Generates a prompt preview, optionally reusing existing wildcard choices."""
        template_content = self.template_editor_text.toPlainText()
        if not template_content.strip():
            return

        seed = 0
        if self.random_seed_checkbox.isChecked() and not use_existing_context:
            seed = random.randint(0, 2**32 - 1)
            self.seed_edit.setText(str(seed))
        else:
            try:
                seed = int(self.seed_edit.text())
            except (ValueError, TypeError):
                self._randomize_seed()
                seed = int(self.seed_edit.text())

        existing_context = self.last_generation_result.get('context') if use_existing_context else None

        # --- Run generation in a background thread ---
        self.gen_thread = QThread(self)
        self.gen_worker = PromptGenerationWorker(self.processor, template_content, seed, existing_context, force_reroll)
        self.gen_worker.moveToThread(self.gen_thread)

        self.gen_thread.started.connect(self.gen_worker.run)
        self.gen_worker.finished.connect(self._on_preview_generated)
        self.gen_worker.finished.connect(self.gen_thread.quit)
        self.gen_worker.finished.connect(self.gen_worker.deleteLater)
        self.gen_thread.finished.connect(self.gen_thread.deleteLater)
        self.gen_thread.finished.connect(self._on_any_thread_finished)

        self.gen_thread.start()
        self.generate_preview_button.setEnabled(False)
        self._start_loading_animation("Generating preview...")

    @Slot(dict)
    def _on_preview_generated(self, result: Dict):
        """Slot to receive and display the generated prompt."""
        self.generate_preview_button.setEnabled(True)
        self.generate_preview_button.setText("Generate Next Preview")
        self._stop_loading_animation("Ready")

        if result['success']:
            self.last_generation_result = result
            self.current_structured_prompt = result.get('segments', [])
            self._display_structured_prompt()
            self._update_action_button_states()
        else:
            self.prompt_preview_text.setPlainText(f"Error generating prompt: {result['error']}")

    def _display_structured_prompt(self):
        """Renders the structured prompt with highlighting in the preview pane."""
        html_content = ""
        for i, segment in enumerate(self.current_structured_prompt):
            if segment.wildcard_name:
                # Create a clickable link for wildcard segments
                # The URL contains the index of the segment in the list
                bg_color = "#e0e0e0" # Default for normal wildcard
                if segment.is_from_include:
                    bg_color = "#d8f3e9" # Greenish for included
                if segment.text == f"__{segment.wildcard_name}__":
                    bg_color = "#ffcccc" # Reddish for missing
                
                link = f'<a href="swap:{i}" style="background-color:{bg_color}; text-decoration:none; color:black;">{segment.text}</a>'
                html_content += link
            else:
                html_content += segment.text
        
        self.prompt_preview_text.setHtml(html_content.replace("\n", "<br>"))
        self._check_and_display_missing_includes()

    @Slot(str)
    def _on_template_select(self, template_name: str):
        """Loads the content of the selected template into the editor."""
        self.current_history_entry_id = None # Reset history context
        if not template_name or template_name == "Select a template":
            self.template_editor_text.clear()
            self._update_action_button_states()
            return

        try:
            content = self.processor.load_template_content(template_name)
            self.template_editor_text.setPlainText(content)
            self._update_action_button_states()
        except Exception as e:
            print(f"Error loading template '{template_name}': {e}")
            self.template_editor_text.setPlainText(f"Error loading template: {e}")


    @Slot(str)
    def _on_model_changed(self, new_model: str):
        """When the model is changed in the dropdown, unload the previous one."""
        if self.current_ollama_model and self.current_ollama_model != new_model:
            # This is a non-critical task, so we can run it and forget.
            # A background thread would be better, but this is simpler for now.
            try:
                self.processor.ollama_client.unload_model(self.current_ollama_model)
            except Exception as e:
                print(f"Warning: Could not unload model {self.current_ollama_model}: {e}")
        self.current_ollama_model = new_model
        self.ollama_model_changed.emit(new_model)

    def report_model_change(self, new_model: str):
        """Allows child windows to report a model change back to the main app."""
        # Set our own combo box. This will trigger our _on_model_changed signal,
        # which in turn unloads the old model and emits the signal to all other windows.
        self.model_combo.setCurrentText(new_model)


    def _check_and_display_missing_includes(self):
        """Checks for missing wildcards and displays clickable links to generate them."""
        # This logic is now part of the main app, similar to the Tkinter version.
        all_includes = {seg.wildcard_name for seg in self.current_structured_prompt if seg.wildcard_name and seg.text == f"__{seg.wildcard_name}__"}
        
        # Clear previous links
        while self.missing_wildcards_container_layout.count():
            child = self.missing_wildcards_container_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.missing_wildcards_frame.setVisible(bool(all_includes))
        for wc_name in sorted(list(all_includes)):
            link_label = QLabel(f'<a href="create:{wc_name}" style="color: orange;">{wc_name}</a>')
            link_label.linkActivated.connect(self._on_wildcard_link_clicked)
            self.missing_wildcards_container_layout.addWidget(link_label)

    def _create_menu_bar(self):
        """Creates the main menu bar and its actions."""
        # On macOS, it's crucial to create a new menu bar and set it,
        # rather than trying to modify the existing one in-place.
        menu_bar = QMenuBar(self)

        # --- File Menu ---
        file_menu = menu_bar.addMenu("&File")
        new_template_action = QAction("New Template...", self)
        new_template_action.triggered.connect(self._create_new_template_file)
        file_menu.addAction(new_template_action)
        self.save_template_action = QAction("Save Template", self)
        self.save_template_action.triggered.connect(self._save_template)
        file_menu.addAction(self.save_template_action)
        self.archive_template_action = QAction("Archive Template...", self)
        self.archive_template_action.triggered.connect(self._archive_current_template)
        file_menu.addAction(self.archive_template_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # --- View Menu ---
        view_menu = menu_bar.addMenu("&View")
        theme_menu = view_menu.addMenu("Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)

        light_theme_action = QAction("Light", self, checkable=True)
        light_theme_action.triggered.connect(lambda: self._set_theme("light"))
        theme_menu.addAction(light_theme_action)
        theme_group.addAction(light_theme_action)

        dark_theme_action = QAction("Dark", self, checkable=True)
        dark_theme_action.triggered.connect(lambda: self._set_theme("dark"))
        theme_menu.addAction(dark_theme_action)
        theme_group.addAction(dark_theme_action)

        # Set initial theme state
        if config.theme == 'dark':
            dark_theme_action.setChecked(True)
        else:
            light_theme_action.setChecked(True)

        # Note: Font size changing in Qt is complex and requires a restart
        # or significant UI reconstruction. We will add a placeholder for now.
        view_menu.addSeparator()

        # --- Workflow Menu ---
        workflow_menu = menu_bar.addMenu("&Workflow")
        workflow_group = QActionGroup(self)
        workflow_group.setExclusive(True)

        self.sfw_action = QAction("SFW", self, checkable=True)
        self.sfw_action.triggered.connect(lambda: self._switch_workflow("sfw"))
        workflow_menu.addAction(self.sfw_action)
        workflow_group.addAction(self.sfw_action)

        self.nsfw_action = QAction("NSFW", self, checkable=True)
        self.nsfw_action.triggered.connect(lambda: self._switch_workflow("nsfw"))
        workflow_menu.addAction(self.nsfw_action)
        workflow_group.addAction(self.nsfw_action)

        self.sfw_action.setChecked(config.workflow == 'sfw')
        self.nsfw_action.setChecked(config.workflow == 'nsfw')

        # --- Tools Menu ---
        tools_menu = menu_bar.addMenu("&Tools")

        brainstorm_action = QAction("AI Brainstorming...", self)
        brainstorm_action.triggered.connect(self._open_brainstorming_window)
        tools_menu.addAction(brainstorm_action)

        wildcard_manager_action = QAction("Wildcard Manager...", self)
        wildcard_manager_action.triggered.connect(self._open_wildcard_manager)
        tools_menu.addAction(wildcard_manager_action)
        
        dependency_graph_action = QAction("Wildcard Dependency Graph...", self)
        dependency_graph_action.triggered.connect(self._open_dependency_graph_window)
        tools_menu.addAction(dependency_graph_action)

        history_action = QAction("History Viewer...", self)
        history_action.triggered.connect(self._open_history_viewer)
        history_action.setShortcut(QKeySequence("Ctrl+H"))
        tools_menu.addAction(history_action)

        fav_images_action = QAction("Favorite Images Viewer...", self)
        fav_images_action.triggered.connect(self._open_favorite_images_viewer)
        tools_menu.addAction(fav_images_action)

        tools_menu.addSeparator()

        interrogator_action = QAction("Image Interrogator...", self)
        interrogator_action.triggered.connect(self._open_image_interrogator)
        tools_menu.addAction(interrogator_action)

        evolver_action = QAction("Prompt Evolver...", self)
        evolver_action.triggered.connect(self._open_prompt_evolver)
        tools_menu.addAction(evolver_action)

        stats_action = QAction("Model Usage Statistics...", self)
        stats_action.triggered.connect(self._open_model_stats_window)
        tools_menu.addAction(stats_action)

        png_viewer_action = QAction("PNG Text Viewer...", self)
        png_viewer_action.triggered.connect(self._open_png_text_viewer)
        tools_menu.addAction(png_viewer_action)

        tools_menu.addSeparator()

        asset_prefix_action = QAction("InvokeAI Asset Prefixes...", self)
        asset_prefix_action.triggered.connect(self._open_asset_prefix_editor)
        tools_menu.addAction(asset_prefix_action)

        system_prompt_action = QAction("System Prompt Editor...", self)
        system_prompt_action.triggered.connect(self._open_system_prompt_editor)
        tools_menu.addAction(system_prompt_action)

        settings_action = QAction("Settings...", self)
        settings_action.setMenuRole(QAction.NoRole)  # Prevent macOS from moving it
        settings_action.triggered.connect(self._open_settings_window)

        # --- Window Menu (for switching between open tool windows) ---
        self.window_menu = menu_bar.addMenu("&Window")
        
        # Add standard macOS window actions
        minimize_action = QAction("Minimize", self)
        minimize_action.setShortcut(QKeySequence("Ctrl+M"))
        minimize_action.triggered.connect(self.showMinimized)
        self.window_menu.addAction(minimize_action)

        zoom_action = QAction("Zoom", self)
        zoom_action.setShortcut(QKeySequence("Ctrl++")) # Common shortcut for zoom/maximize
        zoom_action.triggered.connect(self.showMaximized) # Or showFullScreen() depending on desired behavior
        self.window_menu.addAction(zoom_action)

        bring_all_to_front_action = QAction("Bring All to Front", self)
        bring_all_to_front_action.triggered.connect(self.activateWindow) # This brings the main window to front
        self.window_menu.addAction(bring_all_to_front_action)
        
        self.window_menu.addSeparator() # Separate standard actions from custom list

        self.window_menu.aboutToShow.connect(self._update_window_menu)

        tools_menu.addAction(settings_action)

        # Set initial state for actions after all menus are created
        is_template_loaded = self.template_combo.currentIndex() != -1
        self.save_template_action.setEnabled(is_template_loaded)
        self.archive_template_action.setEnabled(is_template_loaded)

        # Finally, set the constructed menu bar on the main window.
        self.setMenuBar(menu_bar)

    def _update_window_menu(self):
        # Remove all dynamically added custom window actions (those after the separator).
        # Find the index of the separator.
        separator_index = -1
        for i, action in enumerate(self.window_menu.actions()):
            if action.isSeparator():
                separator_index = i
                break

        # Remove all actions after the separator.
        if separator_index != -1:
            for i in range(len(self.window_menu.actions()) - 1, separator_index, -1):
                action = self.window_menu.actions()[i]
                self.window_menu.removeAction(action)

        # --- NEW: Centralized list of all managed windows ---
        all_windows = []
        # ... (rest of the method remains the same, adding custom windows)
        if self.wildcard_manager_window and self.wildcard_manager_window.isVisible():
            all_windows.append(self.wildcard_manager_window)
        if self.history_viewer_window and self.history_viewer_window.isVisible():
            all_windows.append(self.history_viewer_window)
        if self.brainstorming_window and self.brainstorming_window.isVisible():
            all_windows.append(self.brainstorming_window)
        if self.prompt_evolver_window and self.prompt_evolver_window.isVisible():
            all_windows.append(self.prompt_evolver_window)
        if self.image_interrogator_window and self.image_interrogator_window.isVisible():
            all_windows.append(self.image_interrogator_window)
        if self.model_stats_window and self.model_stats_window.isVisible():
            all_windows.append(self.model_stats_window)
        if self.asset_prefix_editor_window and self.asset_prefix_editor_window.isVisible():
            all_windows.append(self.asset_prefix_editor_window)
        if self.system_prompt_editor_window and self.system_prompt_editor_window.isVisible():
            all_windows.append(self.system_prompt_editor_window)
        
        # Add windows from lists
        all_windows.extend([win for win in self.enhancement_windows if win.isVisible()])
        all_windows.extend([win for win in self.image_preview_dialogs if win.isVisible()])

        if not all_windows:
            no_windows_action = QAction("No Other Windows Open", self)
            no_windows_action.setEnabled(False)
            self.window_menu.addAction(no_windows_action)
            return

        for window in all_windows:
            action = QAction(window.windowTitle(), self)
            action.triggered.connect(lambda checked=False, w=window: self._bring_window_to_front(w))
            self.window_menu.addAction(action)

    def _bring_window_to_front(self, window: QWidget):
        """Brings the specified window to the front and activates it."""
        window.show()
        window.raise_()
        window.activateWindow()

    def _create_status_bar(self):
        """Creates the status bar at the bottom of the window."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Ready")
        self.loading_label = QLabel("")
        self.status_bar.addWidget(self.loading_label, 0) # Permanent widget on the left
        self.status_bar.addWidget(self.status_label, 1) # Stretchable widget

    def _handle_ai_content_update(self, content_type: str):
        """Callback for when AI generates a new file, to refresh UI lists."""
        if content_type == 'template':
            self._refresh_template_list()
        # Always refresh wildcards, as a new template might create new ones
        self._refresh_wildcard_list()
        self.status_bar.showMessage(f"New AI-generated {content_type} saved.", 5000)

    def _set_theme(self, theme_name: str):
        """Sets the application theme and saves the setting."""
        self.theme_manager.apply_theme(theme_name)
        settings = load_settings()
        settings['theme'] = theme_name
        save_settings(settings)
        self.status_bar.showMessage(f"Theme changed to {theme_name}.", 3000)
        # Re-apply highlighting for the template editor
        if self.highlighter:
            self.highlighter.rehighlight()

    def _start_loading_animation(self, message: str):
        """Starts the status bar loading animation."""
        self.status_label.setText(message)
        if self.loading_animation_timer is None:
            self.loading_animation_timer = QTimer(self)
            self.loading_animation_timer.setInterval(100) # Update every 100ms
            self.loading_animation_timer.timeout.connect(self._update_loading_animation)
        self.loading_animation_timer.start()

    def _update_loading_animation(self):
        """Updates the character for the loading animation."""
        char = self.loading_animation_chars[self.loading_animation_index]
        self.loading_label.setText(f"[{char}]")
        self.loading_animation_index = (self.loading_animation_index + 1) % len(self.loading_animation_chars)

    def _stop_loading_animation(self, final_message: str):
        """Stops the loading animation and sets a final message."""
        if self.loading_animation_timer and self.loading_animation_timer.isActive():
            self.loading_animation_timer.stop()
        self.loading_label.setText("")
        self.status_label.setText(final_message)

    def _open_history_viewer(self):
        """Opens the History Viewer window, ensuring only one instance exists."""
        if self.history_viewer_window is None or not self.history_viewer_window.isVisible():
            self.history_viewer_window = HistoryViewerWindow(self, self.processor)
            # Connect the signal from the history window to a slot in this main window
            self.history_viewer_window.finished.connect(self._update_window_menu)
            self.history_viewer_window.prompt_to_load.connect(self._load_prompt_from_history)
            self.history_viewer_window.show()
        self.history_viewer_window.activateWindow()
        self.history_viewer_window.raise_()

    def _open_favorite_images_viewer(self):
        """Opens the Favorite Images Viewer window, ensuring only one instance exists."""
        if self.favorite_images_viewer_window is None or not self.favorite_images_viewer_window.isVisible():
            self.favorite_images_viewer_window = FavoriteImagesViewer(self, self.processor)
            self.favorite_images_viewer_window.finished.connect(self._update_window_menu)
            self.favorite_images_viewer_window.show()
        self.favorite_images_viewer_window.activateWindow()
        self.favorite_images_viewer_window.raise_()

    def _open_brainstorming_window(self):
        """Opens the AI Brainstorming window, ensuring only one instance exists."""
        if self.brainstorming_window is None or not self.brainstorming_window.isVisible():
            self.brainstorming_window = BrainstormingWindow(self, self.processor)
            self.brainstorming_window.finished.connect(self._update_window_menu)
            self.ollama_model_changed.connect(self.brainstorming_window.set_model)
            self.brainstorming_window.show()
        self.brainstorming_window.activateWindow()
        self.brainstorming_window.raise_()

    def _open_image_interrogator(self):
        """Opens the Image Interrogator window, ensuring only one instance exists."""
        if self.image_interrogator_window is None or not self.image_interrogator_window.isVisible():
            self.image_interrogator_window = ImageInterrogatorWindow(self, self.processor)
            self.image_interrogator_window.finished.connect(self._update_window_menu)
            self.ollama_model_changed.connect(self.image_interrogator_window.set_model)
            self.image_interrogator_window.show()
        self.image_interrogator_window.activateWindow()
        self.image_interrogator_window.raise_()

    def _open_model_stats_window(self):
        """Opens the Model Usage Statistics window, ensuring only one instance exists."""
        if self.model_stats_window is None or not self.model_stats_window.isVisible():
            self.model_stats_window = ModelStatsWindow(self, self.processor)
            self.model_stats_window.finished.connect(self._update_window_menu)
            self.model_stats_window.show()
        self.model_stats_window.activateWindow()
        self.model_stats_window.raise_()

    def _open_prompt_evolver(self):
        """Opens the Prompt Evolver window, ensuring only one instance exists."""
        if self.prompt_evolver_window is None or not self.prompt_evolver_window.isVisible():
            self.prompt_evolver_window = PromptEvolverWindow(self, self.processor, self._load_prompt_from_history)
            self.prompt_evolver_window.finished.connect(self._update_window_menu)
            self.prompt_evolver_window.show()
        self.prompt_evolver_window.activateWindow()
        self.prompt_evolver_window.raise_()

    def _open_png_text_viewer(self):
        """Opens the PNG Text Viewer window, ensuring only one instance exists."""
        if self.png_text_viewer_window is None or not self.png_text_viewer_window.isVisible():
            self.png_text_viewer_window = PNGTextViewerWindow(self)
            self.png_text_viewer_window.finished.connect(self._update_window_menu)
            self.png_text_viewer_window.show()
        self.png_text_viewer_window.activateWindow()
        self.png_text_viewer_window.raise_()

    def _open_settings_window(self):
        """Opens the application settings window."""
        if self.settings_window is None or not self.settings_window.isVisible():
            self.settings_window = SettingsWindow(self, on_save_callback=self._on_settings_saved)
            self.settings_window.finished.connect(self._update_window_menu)
            self.settings_window.show()
        self.settings_window.activateWindow()
        self.settings_window.raise_()

    def _open_asset_prefix_editor(self):
        """Opens the InvokeAI Asset Prefix Editor window."""
        if self.asset_prefix_editor_window is None or not self.asset_prefix_editor_window.isVisible():
            self.asset_prefix_editor_window = AssetPrefixEditorWindow(self, self.processor)
            self.asset_prefix_editor_window.finished.connect(self._update_window_menu)
            self.asset_prefix_editor_window.show()
        self.asset_prefix_editor_window.activateWindow()
        self.asset_prefix_editor_window.raise_()

    def _open_system_prompt_editor(self):
        """Opens the System Prompt Editor window."""
        if self.system_prompt_editor_window is None or not self.system_prompt_editor_window.isVisible():
            self.system_prompt_editor_window = SystemPromptEditorWindow(self, self.processor)
            self.system_prompt_editor_window.finished.connect(self._update_window_menu)
            self.system_prompt_editor_window.show()
        self.system_prompt_editor_window.activateWindow()
        self.system_prompt_editor_window.raise_()

    def _on_settings_saved(self):
        """Callback for when settings are saved, to reload necessary resources."""
        self.status_bar.showMessage("Settings saved. Re-initializing application...", 5000)
        # Re-initialize the processor's clients with the new URLs from the global config
        self.processor.ollama_client = self.processor.ollama_client.__class__(base_url=config.OLLAMA_BASE_URL)
        self.processor.invokeai_client = self.processor.invokeai_client.__class__(base_url=config.INVOKEAI_BASE_URL)
        
        # --- NEW: Re-initialize HistoryManager to pick up potential changes to HISTORY_DIR ---
        self.processor.history_manager = self.processor.history_manager.__class__()
        
        # --- NEW: Explicitly re-check server compatibility after settings change ---
        try:
            # After re-initializing the client, we must re-check compatibility.
            if config.INVOKEAI_BASE_URL:
                self.processor.invokeai_client.check_server_compatibility()
                self.status_bar.showMessage("InvokeAI connection verified.", 3000)
        except Exception as e:
            QMessageBox.warning(self, "InvokeAI Connection Warning", f"Could not verify connection to new InvokeAI URL. Please check the server.\n\nError: {e}")

        # Re-run the initial load process to refresh everything
        self._start_initial_load()

    def _switch_workflow(self, new_workflow: str):
        """Handles the logic for switching between SFW and NSFW modes."""
        if new_workflow == config.workflow:
            return

        config.workflow = new_workflow
        settings = load_settings()
        settings['workflow'] = new_workflow
        save_settings(settings)

        # Reload core data and UI components
        self.processor.reload_wildcards()
        self._refresh_template_list()
        self._update_action_bar_variations()
        self._refresh_wildcard_list()

        self.status_bar.showMessage(f"Switched to {new_workflow.upper()} workflow. Select a template.", 5000)

    @Slot(dict)
    def _load_prompt_from_history(self, entry: dict):
        """Loads a prompt from a history entry into the main UI for re-enhancement."""
        # Determine which prompt to load: the enhanced one if it exists, otherwise the original.
        prompt_text = entry.get('enhanced', {}).get('prompt') or entry.get('original_prompt', '')
        if not prompt_text:
            self.status_bar.showMessage("Warning: Selected history entry has no prompt text to load.", 5000)
            return

        # Store the ID of the history entry being loaded
        self.current_history_entry_id = entry.get('id')

        # Block signals to prevent the combo box from triggering a template load while we clear it
        self.template_combo.blockSignals(True)
        self.template_combo.setCurrentIndex(-1) # Clear selection
        self.template_combo.setPlaceholderText("Select a template")
        self.template_combo.blockSignals(False)

        # Clear preview and update state
        self.prompt_preview_text.clear()
        self.current_structured_prompt = []
        self.last_generation_result = {}

        # Load the historical prompt into the editable text area
        self.template_editor_group.setTitle("Editable Prompt (from History)")
        self.template_editor_text.setPlainText(prompt_text)

        # Update UI states
        self._update_action_button_states()
        self.status_bar.showMessage("Loaded prompt from history. Ready to enhance or generate.", 5000)

    def _get_current_prompt_string(self) -> str:
        """Constructs the full prompt string from the current structured prompt."""
        if not self.current_structured_prompt:
            return self.prompt_preview_text.toPlainText().strip()
        
        raw_prompt = "".join(seg.text for seg in self.current_structured_prompt)
        return self.processor.cleanup_prompt_string(raw_prompt)

    def _update_action_button_states(self):
        """Updates the enabled/disabled state of all action buttons."""
        is_prompt_available = bool(self.template_editor_text.toPlainText().strip()) or bool(self.prompt_preview_text.toPlainText().strip())
        is_template_loaded = bool(self.template_combo.currentIndex() != -1)
        is_invokeai_ready = self.processor and self.processor.is_invokeai_connected()

        if hasattr(self, 'save_template_action'):
            self.save_template_action.setEnabled(is_template_loaded)
            self.archive_template_action.setEnabled(is_template_loaded)

        self.generate_preview_button.setEnabled(is_template_loaded)
        self.enhance_prompt_button.setEnabled(is_prompt_available)
        self.copy_prompt_button.setEnabled(is_prompt_available)
        self.save_as_template_button.setEnabled(is_prompt_available)
        self.generate_image_button.setEnabled(is_prompt_available and is_invokeai_ready)
        self.enhance_template_button.setEnabled(is_template_loaded)

    @Slot()
    def _on_copy_prompt_clicked(self):
        """Copies the generated prompt text to the clipboard."""
        prompt_text = self._get_current_prompt_string()
        if prompt_text:
            clipboard = QApplication.clipboard()
            clipboard.setText(prompt_text)
            self.status_bar.showMessage("Prompt copied to clipboard.", 3000)

    @Slot()
    def _on_save_as_template_clicked(self):
        """Saves the content of the preview pane as a new template file."""
        content_to_save = self.template_editor_text.toPlainText()
        if not content_to_save.strip():
            QMessageBox.warning(self, "Empty Content", "There is no content in the editor to save as a template.")
            return

        filename, _ = QFileDialog.getSaveFileName(self, "Save as New Template", config.get_template_dir(), "Text Files (*.txt)")

        if filename:
            try:
                # The processor handles adding .txt if missing
                template_basename = os.path.basename(filename)
                saved_filename = self.processor.save_template_content(template_basename, content_to_save)
                
                # Refresh the template list and select the new one
                self._refresh_template_list()
                self.template_combo.setCurrentText(saved_filename)
                
                self.status_bar.showMessage(f"Saved new template to {saved_filename}", 5000)
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Could not save template:\n{e}")

    @Slot()
    def _on_enhance_prompt_clicked(self):
        """Handles the 'Enhance This Prompt' button click from the main window."""
        prompt_text = self._get_current_prompt_string()
        self.start_enhancement_workflow(prompt_text, original_entry_id=self.current_history_entry_id)

    def start_enhancement_workflow(self, prompt_text: str, original_entry_id: Optional[str] = None, prompt_type_key: Optional[str] = None, model_override: Optional[str] = None, is_reenhancement_mode: bool = False, history_entry: Optional[Dict[str, Any]] = None):
        """
        Starts the enhancement process for a given prompt string.
        This can be called from the main UI or from other windows like the History Viewer.
        """
        if not prompt_text.strip():
            QMessageBox.warning(self, "No Prompt", "There is no prompt to enhance.")
            return

        model = model_override if model_override else self.model_combo.currentText()
        if not model or "model" in model.lower():
            QMessageBox.warning(self, "No Model Selected", "Please select a valid Ollama model to use for enhancement.")
            return

        selected_variations = self._get_selected_variations()

        # Create and show the enhancement window, which is non-modal.
        enhancement_window = EnhancementResultWindow(
            self, self.processor, prompt_text, model, selected_variations,
            original_entry_id=original_entry_id,
            prompt_type_key=prompt_type_key, # Pass the key
            is_reenhancement_mode=is_reenhancement_mode,
            history_entry=history_entry
        )
        enhancement_window.finished.connect(self._update_window_menu)
        self.ollama_model_changed.connect(enhancement_window.set_model)
        self.enhancement_windows.append(enhancement_window)
        enhancement_window.show()

    def _get_selected_variations(self) -> List[str]:
        """Gets a list of keys for the checked variation checkboxes."""
        return [key for key, checkbox in self.variation_checkboxes.items() if checkbox.isChecked()]

    @Slot()
    def _on_enhance_template_clicked(self):
        """Handles the 'Enhance Template (AI)' button click."""
        template_content = self.template_editor_text.toPlainText().strip()
        if not template_content:
            QMessageBox.warning(self, "Empty Template", "There is no template content to enhance.")
            return

        model = self.model_combo.currentText()
        if not model or "model" in model.lower():
            QMessageBox.warning(self, "No Model Selected", "Please select a valid Ollama model to use for enhancement.")
            return

        # Start the background worker
        self.model_usage_manager.register_usage(model)
        self.enhance_thread = QThread(self)
        self.enhance_worker = TemplateEnhancementWorker(self.processor, template_content, model)
        self.enhance_worker.moveToThread(self.enhance_thread)

        self.enhance_thread.started.connect(self.enhance_worker.run)
        self.enhance_worker.finished.connect(self._on_template_enhanced)
        self.enhance_worker.finished.connect(self.enhance_thread.quit)
        self.enhance_worker.finished.connect(self.enhance_worker.deleteLater)
        self.enhance_thread.finished.connect(self.enhance_thread.deleteLater)
        self.enhance_thread.finished.connect(self._on_any_thread_finished)

        self.enhance_thread.start()
        self._start_loading_animation(f"Enhancing template with {model}...")
        self.enhance_template_button.setEnabled(False)

    @Slot(dict)
    def _on_template_enhanced(self, result: dict):
        """Slot to handle the result of the template enhancement."""
        self.enhance_template_button.setEnabled(True)
        self._stop_loading_animation("Ready")

        model = self.enhance_worker.model
        self.model_usage_manager.unregister_usage(model)

        if not result['success']:
            error_message = result.get('error', 'An unknown error occurred.')
            QMessageBox.critical(self, "Enhancement Error", str(error_message))
            return

        original = result.get('original', '')
        enhanced = result.get('enhanced', '').strip()

        if not enhanced or enhanced == original:
            self.status_bar.showMessage("AI enhancement resulted in no changes.", 5000)
            return

        dialog = DiffConfirmationDialog(self, "Confirm AI Enhancement", original, enhanced)
        if dialog.exec() == QDialog.Accepted:
            self.template_editor_text.setPlainText(enhanced)
            self.status_bar.showMessage("AI enhancement applied to the template.", 5000)
        else:
            self.status_bar.showMessage("AI enhancement discarded.", 5000)

    @Slot()
    def _on_generate_image_clicked(self):
        """Opens the image generation options dialog and starts the generation."""
        prompt_text = self._get_current_prompt_string()
        if not prompt_text:
            QMessageBox.warning(self, "No Prompt", "There is no prompt to generate an image from.")
            return

        # --- NEW: Unload all Ollama models before image generation ---
        if self.processor and self.processor.ollama_client:
            self.processor.ollama_client.unload_all_models()

        dialog = ImageGenerationOptionsDialog(self, self.processor, prompt_text, initial_params=self.last_generation_result.get('context', {}), force_random_seed=True)
        if dialog.exec() == QDialog.Accepted:
            options = dialog.get_options()
            
            selected_models_info = options.pop('models', [])
            if not selected_models_info:
                QMessageBox.warning(self, "No Models Selected", "You must select at least one model to generate images.")
                return

            save_to_gallery = options.get('save_to_gallery', False)

            generation_jobs = []
            num_images_per_model = options.pop('num_images', 1)
            base_seed = options.get('seed', random.randint(0, 2**32 - 1)) # REVERTED TO THIS LINE

            for model_info in selected_models_info:
                self.model_usage_manager.register_usage(model_info.get('model', {}).get('name'))
                for i in range(num_images_per_model):
                    job_params = options.copy()
                    job_params['model'] = model_info.get('model')
                    job_params['loras'] = model_info.get('loras', [])
                    job_params['negative_prompt'] = model_info['negative_prompt']
                    job_params['seed'] = base_seed + i # Use base_seed + i
                    generation_jobs.append({
                        'prompt': prompt_text,
                        'gen_params': job_params
                    })
            
            def on_success(images_to_save: List[Dict[str, Any]]):
                if not images_to_save: return
                entry_id = str(uuid.uuid4())
                saved_images_data = [{'image_path': self.processor.save_generated_image(img['bytes'], entry_id), 'generation_params': img.get('generation_params')} for img in images_to_save]
                entry = {'id': entry_id, 'original_prompt': prompt_text, 'status': 'generated_only', 'original_images': saved_images_data,
                         'template_name': self.template_combo.currentText() if self.template_combo.currentIndex() != -1 else None,
                         'context': self.last_generation_result.get('context')}
                self.processor.history_manager.save_result(**entry)
                self.status_bar.showMessage(f"{len(saved_images_data)} image(s) saved to history.", 5000)

                for model_info in selected_models_info:
                    self.model_usage_manager.unregister_usage(model_info.get('model', {}).get('name'))

            preview_dialog = MultiImagePreviewDialog(self, self.processor, generation_jobs, on_success, save_to_gallery=save_to_gallery)
            self.image_preview_dialogs.append(preview_dialog)
            preview_dialog.show()

    def on_image_generation_complete(self):
        """Flashes the window to notify the user that image generation is complete."""
        QApplication.alert(self)

    def _start_image_generation_workflow(self, parent_window: QWidget, prompt: str, initial_params: Dict[str, Any], is_regeneration: bool = False, save_to_gallery_for_batch: Optional[bool] = None):
        """
        A centralized method to handle the entire image generation process, from
        opening the options dialog to launching the preview window.
        This is now the single entry point for all image generation tasks.
        """
        if is_regeneration:
            # For a simple regeneration, we skip the options dialog and use the provided params.
            # The 'model' is already in initial_params, so we wrap it in the expected structure.
            options = initial_params
            selected_models_info = [{'model': initial_params.get('model'), 'loras': initial_params.get('loras', []), 'negative_prompt': initial_params.get('negative_prompt', '')}]
            save_to_gallery = save_to_gallery_for_batch if save_to_gallery_for_batch is not None else False
        else:
            # For a new generation, show the full options dialog.
            dialog = ImageGenerationOptionsDialog(parent_window, self.processor, prompt, initial_params=initial_params)
            if dialog.exec() != QDialog.Accepted:
                return
            options = dialog.get_options()
            selected_models_info = options.pop('models', [])
            save_to_gallery = options.get('save_to_gallery', False)

        if not selected_models_info:
            QMessageBox.warning(self, "No Models Selected", "You must select at least one model to generate images.")
            return

        generation_jobs = []
        num_images_per_model = options.pop('num_images', 1)
        base_seed = options.get('seed', random.randint(0, 2**32 - 1))

        for model_info in selected_models_info:
            for i in range(num_images_per_model):
                job_params = options.copy()
                job_params['model'] = model_info['model']
                job_params['loras'] = model_info.get('loras', [])
                job_params['negative_prompt'] = model_info['negative_prompt']
                job_params['seed'] = base_seed + i
                generation_jobs.append({'prompt': prompt, 'gen_params': job_params})

        def on_success(images_to_save: List[Dict[str, Any]]):
            """This callback is now generic and just shows a status message."""
            if images_to_save:
                self.status_bar.showMessage(f"{len(images_to_save)} image(s) saved to history.", 5000)

        preview_dialog = MultiImagePreviewDialog(parent_window, self.processor, generation_jobs, on_success, save_to_gallery=save_to_gallery)
        preview_dialog.exec()

    def _open_wildcard_manager(self):
        """Opens the Wildcard Manager window, ensuring only one instance exists."""
        if self.wildcard_manager_window is None or not self.wildcard_manager_window.isVisible():
            # We need to pass a callback to refresh the main UI when a wildcard is saved
            self.wildcard_manager_window = WildcardManagerWindow(self, self.processor, self._on_wildcard_update)
            self.wildcard_manager_window.finished.connect(self._update_window_menu)
            self.wildcard_manager_window.show()
        self.wildcard_manager_window.activateWindow()
        self.wildcard_manager_window.raise_()

    def open_wildcard_manager_and_select_file(self, filename: str):
        """Opens the wildcard manager and tells it to load a specific file."""
        self._open_wildcard_manager() # This will show and raise the window
        if self.wildcard_manager_window:
            self.wildcard_manager_window.select_and_load_file(filename)
        
    def _open_dependency_graph_window(self) -> None:
        """Opens the Wildcard Dependency Graph window."""
        # This window is modal, so we don't need to worry about multiple instances.
        dialog = DependencyGraphWindow(self, self.processor)
        dialog.exec()

    def _refresh_template_list(self):
        """Reloads the list of templates from the processor and updates the UI."""
        try:
            templates = self.processor.get_available_templates()
            self.template_combo.clear()
            self.template_combo.addItems(templates)
        except Exception as e:
            print(f"Error refreshing template list: {e}")
            self.template_combo.clear()
            self.template_combo.addItem("Error loading templates.")

    def _refresh_wildcard_list(self):
        """Reloads the list of wildcards from the processor and updates the UI."""
        try:
            wildcard_files = self.processor.get_wildcard_files()
            self.wildcard_inserter.populate(wildcard_files)
        except Exception as e:
            print(f"Error refreshing wildcard list: {e}")
            self.wildcard_inserter.populate([])

    def _update_action_bar_variations(self):
        """Populates the variations group box with checkboxes."""
        # Clear existing checkboxes and layout items
        while self.variations_layout.count():
            item = self.variations_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.variation_checkboxes.clear()
        
        variations = self.processor.available_variations_map
        num_variations = len(variations)
        if num_variations == 0:
            self.variations_group.setVisible(False)
            return
        else:
            self.variations_group.setVisible(True)

        # Determine grid dimensions (e.g., 2 rows, dynamic columns)
        num_rows = 2
        num_cols = (num_variations + num_rows - 1) // num_rows # Ceiling division
        
        row, col = 0, 0
        for key, name in variations.items():
            checkbox = QCheckBox(name)
            checkbox.setChecked(True)  # Set to checked by default
            self.variation_checkboxes[key] = checkbox
            self.variations_layout.addWidget(checkbox, row, col)
            
            col += 1
            if col >= num_cols:
                col = 0
                row += 1

    @Slot(QUrl)
    def _on_wildcard_link_clicked(self, url: QUrl):
        """Handles clicks on links in the prompt preview or missing wildcard list."""
        scheme = url.scheme()
        path = url.path()

        if scheme == "swap":
            try:
                segment_index = int(path)
                self._show_swap_menu(segment_index)
            except (ValueError, IndexError):
                print(f"Warning: Could not parse swap link: {url.toString()}")
        elif scheme == "create":
            wildcard_name = path
            self._handle_missing_wildcard_click(wildcard_name)

    def _show_swap_menu(self, segment_index: int):
        """Displays a context menu to swap the wildcard value."""
        if not (0 <= segment_index < len(self.current_structured_prompt)):
            return

        segment = self.current_structured_prompt[segment_index]
        wildcard_name = segment.wildcard_name
        if not wildcard_name:
            return

        options = self.processor.get_wildcard_options(wildcard_name)
        if not options:
            return

        menu = QMenu(self)
        for option in options:
            display_option = (option[:75] + '...') if len(option) > 75 else option
            action = QAction(display_option, self)
            action.triggered.connect(lambda checked=False, opt=option: self._swap_wildcard(segment_index, opt))
            menu.addAction(action)
        
        menu.exec(self.cursor().pos())

    def _swap_wildcard(self, segment_index: int, new_value: str):
        """Swaps the text of a wildcard segment and redisplays the prompt."""
        if not (0 <= segment_index < len(self.current_structured_prompt)):
            return

        segment_to_swap = self.current_structured_prompt[segment_index]
        wildcard_name = segment_to_swap.wildcard_name
        if not wildcard_name:
            return

        context = self.last_generation_result.get('context', {})
        context[wildcard_name] = {'value': new_value, 'tags': []} # Assume no tags for a simple swap
        self._perform_live_update(use_existing_context=True)

    def _handle_missing_wildcard_click(self, wildcard_name: str):
        """Handles click on a missing wildcard link."""
        reply = QMessageBox.question(self, "Generate Wildcard", f"Would you like to generate content for the missing wildcard '{wildcard_name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            # Generate with AI
            self._open_brainstorming_window()
            if self.brainstorming_window:
                self.brainstorming_window.generate_wildcard_with_topic(wildcard_name.replace('_', ' '), filename=wildcard_name, template_context=self.template_editor_text.toPlainText())
        elif reply == QMessageBox.StandardButton.No:
            # Create manually
            self._create_empty_wildcard(wildcard_name)

    def _create_empty_wildcard(self, wildcard_name: str):
        """Creates an empty wildcard file with basic structure."""
        initial_data = {"description": f"Wildcard file for {wildcard_name}", "choices": ["Sample choice 1", "Sample choice 2"]}
        initial_content = json.dumps(initial_data, indent=2)
        self._open_wildcard_manager(initial_file=f"{wildcard_name}.json", initial_content=initial_content)

    def _show_template_editor_context_menu(self, position):
        """Shows the context menu for the template editor."""
        menu = QMenu()
        cursor = self.template_editor_text.textCursor()
        selected_text = cursor.selectedText()

        create_wildcard_action = QAction("Create Wildcard from Selection...", self)
        create_wildcard_action.setEnabled(bool(selected_text))
        create_wildcard_action.triggered.connect(lambda: self._create_wildcard_from_selection(selected_text))
        menu.addAction(create_wildcard_action)

        brainstorm_action = QAction("Brainstorm with AI...", self)
        brainstorm_action.triggered.connect(self._brainstorm_with_template)
        menu.addAction(brainstorm_action)

        menu.exec(self.template_editor_text.mapToGlobal(position))

    def _create_wildcard_from_selection(self, selected_text: str):
        """Creates a new wildcard file from the selected text."""
        suggested_name = re.sub(r'\s+', '_', selected_text.strip()).lower()
        suggested_name = re.sub(r'[^a-z0-9_]', '', suggested_name)[:50]
        
        wildcard_name, ok = QInputDialog.getText(self, "Create New Wildcard", "Enter a name for the new wildcard (without .json):", text=suggested_name)
        if not ok or not wildcard_name:
            return

        initial_data = {"description": f"Wildcard created from template selection: '{selected_text}'", "choices": [selected_text]}
        initial_content_str = json.dumps(initial_data, indent=2)

        cursor = self.template_editor_text.textCursor()
        cursor.insertText(f"__{wildcard_name}__")
        self._open_wildcard_manager(initial_file=f"{wildcard_name}.json", initial_content=initial_content_str)

    def _brainstorm_with_template(self):
        """Sends the current template content to the brainstorming window."""
        content = self.template_editor_text.toPlainText()
        filename = self.template_combo.currentText() or "Unsaved Template"
        self._open_brainstorming_window()
        if self.brainstorming_window:
            self.brainstorming_window.load_content_for_brainstorming("template", filename, content)

    def _on_wildcard_update(self, modified_file: Optional[str] = None):
        """Callback for when the Wildcard Manager saves a file."""
        self._refresh_wildcard_list()

        if modified_file and self.current_structured_prompt:
            modified_basename = os.path.splitext(modified_file)[0]
            if any(seg.wildcard_name == modified_basename for seg in self.current_structured_prompt):
                self.status_label.setText(f"Wildcard '{modified_basename}' updated. Refreshing preview...")
                self._perform_live_update(use_existing_context=True, force_reroll=[modified_basename])

    def _create_new_template_file(self):
        """Prompts for a new template filename and creates it."""
        filename, ok = QInputDialog.getText(self, "New Template", "Enter new template filename (without .txt):")
        if ok and filename:
            if not filename.endswith('.txt'):
                filename += '.txt'
            try:
                self.processor.save_template_content(filename, "")
                self._refresh_template_list()
                self.template_combo.setCurrentText(filename)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not create template file:\n{e}")

    def _save_template(self):
        """Saves the currently loaded template."""
        current_file = self.template_combo.currentText()
        if not current_file or "template" in current_file.lower():
            self.status_bar.showMessage("No template selected to save.", 3000)
            return
        content = self.template_editor_text.toPlainText()
        try:
            self.processor.save_template_content(current_file, content)
            self.status_bar.showMessage(f"Template '{current_file}' saved.", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save template:\n{e}")

    def _archive_current_template(self):
        """Archives the currently loaded template."""
        current_file = self.template_combo.currentText()
        if not current_file or "template" in current_file.lower():
            return
        if QMessageBox.question(self, "Confirm Archive", f"Are you sure you want to archive '{current_file}'?") == QMessageBox.StandardButton.Yes:
            self.processor.archive_template(current_file)
            self._refresh_template_list()
            self.template_editor_text.clear()
            self.prompt_preview_text.clear()
            self.status_bar.showMessage(f"Archived template: {current_file}", 3000)

    @Slot()
    def _randomize_seed(self):
        """Generates and sets a new random seed."""
        self.seed_edit.setText(str(random.randint(0, 2**32 - 1)))