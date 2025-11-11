"""The Qt-based History Viewer window."""

import os
import random
import copy
import queue # NEW
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QCheckBox,
    QLineEdit, QPushButton, QGroupBox, QSplitter, QLabel, QMenu, QApplication,
    QAbstractItemView, QHeaderView, QMessageBox, QWidget, QListWidget, QListWidgetItem,
    QStyleOptionViewItem, QComboBox, QStyledItemDelegate
)
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QSize, QPoint, QModelIndex, QTimer, QEvent
from PySide6.QtGui import QPixmap, QIcon, QImage, QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QCloseEvent, QPainter, QDesktopServices, QCursor
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING

from core.prompt_processor import PromptProcessor
from core.config import config
from .image_preview_dialog import ImagePreviewDialog
from .multi_image_preview_dialog import MultiImagePreviewDialog
from PIL.ImageQt import ImageQt
if TYPE_CHECKING:
    from .gui_app import GUIApp
from .custom_widgets import SmoothTableWidget, SmoothListWidget, SmoothTextEdit, ImageGalleryItemWidget
from .image_generation_dialog import ImageGenerationOptionsDialog
from .image_preview_popup import ImagePreviewPopup


class JsonHighlighter(QSyntaxHighlighter):
    """A syntax highlighter for JSON text."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        # Rule for keys (text in quotes followed by a colon)
        key_format = QTextCharFormat()
        key_format.setForeground(QColor("#9CDCFE")) # Light blue
        self.highlighting_rules.append((r'"[^"]*"\s*:', key_format))

        # Rule for string values
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#CE9178")) # Orange/brown
        self.highlighting_rules.append((r'"[^"]*"', string_format))

        # Rule for numbers
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#B5CEA8")) # Light green
        self.highlighting_rules.append((r'\b[0-9]+\.?[0-9]*\b', number_format))

    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            for match in __import__('re').finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), format)

class HistoryLoaderWorker(QObject):
    """Worker to load history in the background."""
    finished = Signal(list)

    def __init__(self, processor: PromptProcessor):
        super().__init__()
        self.processor = processor

    @Slot()
    def run(self):
        """Loads the full history and emits it."""
        history = self.processor.get_all_history_across_workflows()
        self.finished.emit(history)

class ThumbnailLoaderWorker(QObject):
    """Worker to load image thumbnails in the background."""
    thumbnail_ready = Signal(dict)
    finished = Signal()
    # job_added = Signal() # No longer needed

    def __init__(self, processor: PromptProcessor, target_size: Tuple[int, int], job_queue: queue.Queue): # Accept shared job_queue
        super().__init__()
        self.processor = processor
        self.target_size = target_size
        self.job_queue = job_queue # Use shared queue
        # self._is_running = False # No longer needed for individual worker

    def add_job(self, job: Dict[str, Any]):
        """Adds a job to the shared queue."""
        self.job_queue.put(job) # Put job into shared queue
        # No need to emit job_added here, workers will pull from the queue

    @Slot()
    def run(self):
        """Loads thumbnails from the shared queue and emits them one by one."""
        while not QThread.currentThread().isInterruptionRequested():
            data = None # Initialize data to None
            try:
                data = self.job_queue.get(timeout=1) # Get job from shared queue with timeout
                if data is None: # Sentinel for graceful shutdown
                    self.job_queue.task_done()
                    break

                relative_path = data.get('image_path') # This is the key for the path
                workflow = data.get('workflow_source', 'sfw')
                item_widget = data.get('item')

                if relative_path:
                    original_workflow = config.workflow
                    config.workflow = workflow.lower()
                    full_path = os.path.join(config.get_history_file_dir(), relative_path)
                    config.workflow = original_workflow # Restore immediately
                    if os.path.exists(full_path):
                        thumb_image = self.processor.thumbnail_manager.get_thumbnail(relative_path, workflow.lower(), self.target_size)
                        if thumb_image and (not QThread.currentThread().isInterruptionRequested()):
                            qimage = ImageQt(thumb_image).copy()
                            qimage = qimage.convertToFormat(QImage.Format.Format_ARGB32)
                            result = {**data, 'item': item_widget, 'thumb_image': qimage, 'full_path': full_path}
                            self.thumbnail_ready.emit(result)
            except queue.Empty:
                continue # Loop again to check for interruption
            except Exception as e:
                print(f"ERROR in ThumbnailLoaderWorker: {e}")
            finally:
                if data is not None: # Ensure task_done is called for actual jobs
                    self.job_queue.task_done()

        self.finished.emit()

class ThumbnailDelegate(QStyledItemDelegate):
    """A delegate to draw pixmaps in table cells."""
    PixmapRole = Qt.ItemDataRole.UserRole + 2

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        pixmap = index.data(self.PixmapRole)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            # Calculate the position to center the pixmap in the cell
            x = option.rect.x() + (option.rect.width() - pixmap.width()) / 2
            y = option.rect.y() + (option.rect.height() - pixmap.height()) / 2
            painter.drawPixmap(int(x), int(y), pixmap)
            return
        super().paint(painter, option, index)

class HistoryViewerWindow(QDialog):
    """A Qt-based window for viewing and managing prompt history."""
    # Signal to emit the full history entry when a prompt is to be loaded
    prompt_to_load = Signal(dict)

    def __init__(self, parent: 'GUIApp', processor: PromptProcessor):
        super().__init__(parent)
        self.setWindowTitle("History Viewer (Qt)")
        self.processor = processor
        self.all_history_data: List[Dict[str, Any]] = []
        self.row_to_entry_map: Dict[int, Dict[str, Any]] = {}
        self.favorite_star_color = QColor("#FFD700") # Gold color for the star
        self.thumbnail_loader_thread: Optional[QThread] = None
        self.history_loader_thread: Optional[QThread] = None # For the main history loader
        self._current_history_entry: Optional[Dict[str, Any]] = None # Store the currently selected history entry
        
        # --- NEW: Persistent worker for all thumbnails ---
        self.persistent_thumb_worker: Optional[ThumbnailLoaderWorker] = None
        self.persistent_thumb_thread: Optional[QThread] = None
        self.shared_thumb_job_queue = queue.Queue() # NEW: Shared queue for thumbnail jobs
        self.image_preview_popup = ImagePreviewPopup(self) # Initialize the popup
        self.image_preview_timer = QTimer(self) # Timer for delayed image preview
        self.image_preview_timer.setSingleShot(True)
        self.image_preview_timer.setInterval(1500) # 1500ms delay
        self._current_hover_image_path: Optional[str] = None # Store path for timer

        self._create_widgets()
        self._connect_signals()
        self._setup_persistent_thumbnail_worker()
        self._start_loading_history()
        self._update_action_buttons() # Set initial state
        self.resize(1400, 800)

        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            # Calculate top-left point for centering
            x = screen_geometry.x() + (screen_geometry.width() - self.width()) // 2
            y = screen_geometry.y() + (screen_geometry.height() - self.height()) // 2
            self.move(x, y)
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        # Top: Search bar
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter by prompt, status, or template...")
        search_layout.addWidget(self.search_edit)
        search_layout.addStretch(1)
        self.favorites_only_checkbox = QCheckBox("Show Favorites Only")
        search_layout.addWidget(self.favorites_only_checkbox)
        main_layout.addLayout(search_layout)

        # Middle: Splitter for table and details
        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter, 1)

        # Left side: Table and actions
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        self.history_table = SmoothTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels(["Favorite", "Thumbnail", "Timestamp", "Prompt", "Status", "Template"])
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setShowGrid(False)
        self.history_table.setMouseTracking(True) # Enable mouse tracking for hover events
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu) # NEW LINE
        self.history_table.setIconSize(QSize(200, 200)) # Set the display size for icons
        self.history_table.verticalHeader().setDefaultSectionSize(200) # Row height for thumbnails
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch) # Prompt column
        self.history_table.setColumnWidth(0, 60)
        self.history_table.setItemDelegateForColumn(1, ThumbnailDelegate(self))
        self.history_table.setColumnWidth(1, 200) # Thumbnail
        self.history_table.setColumnWidth(2, 160)
        self.history_table.setColumnWidth(4, 100)
        self.history_table.setColumnWidth(5, 150)
        left_layout.addWidget(self.history_table)

        # Action buttons below the table
        action_layout = QHBoxLayout()
        self.load_prompt_button = QPushButton("Load Prompt")
        self.enhance_button = QPushButton("Enhance")
        self.generate_image_button = QPushButton("Generate Image")
        self.delete_button = QPushButton("Delete Entry")
        self.delete_button.setStyleSheet("color: red;")
        action_layout.addWidget(self.load_prompt_button)
        action_layout.addWidget(self.enhance_button)
        action_layout.addWidget(self.generate_image_button)
        action_layout.addStretch()
        action_layout.addWidget(self.delete_button)
        left_layout.addLayout(action_layout)
        main_splitter.addWidget(left_pane)

        # Right side: Details
        right_pane = QSplitter(Qt.Vertical)
        
        # Top-right: Details
        details_group = QGroupBox("Entry Details")
        details_layout = QVBoxLayout(details_group)

        prompt_selection_layout = QHBoxLayout()
        prompt_selection_layout.addWidget(QLabel("View Prompt:"))
        self.prompt_selector_combo = QComboBox()
        prompt_selection_layout.addWidget(self.prompt_selector_combo)
        details_layout.addLayout(prompt_selection_layout)

        self.details_text = SmoothTextEdit() # Keep a reference if needed, but use the new one
        self.details_text.setReadOnly(True)
        self.json_highlighter = JsonHighlighter(self.details_text.document())
        details_layout.addWidget(self.details_text) # Add the editor to the layout
        right_pane.addWidget(details_group)

        # Bottom-right: Image Gallery
        images_group = QGroupBox("Associated Images (Double-click to view)")
        images_layout = QVBoxLayout(images_group)
        self.image_gallery = SmoothListWidget()
        self.image_gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.image_gallery.setIconSize(QSize(128, 128))
        self.image_gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.image_gallery.setWordWrap(True)
        self.image_gallery.setMouseTracking(True) # Enable mouse tracking for hover events
        self.image_gallery.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.image_gallery.viewport().installEventFilter(self) # Install event filter on the viewport
        images_layout.addWidget(self.image_gallery)
        images_group.setLayout(images_layout)
        right_pane.addWidget(images_group)

        right_pane.setSizes([200, 300])
        main_splitter.addWidget(right_pane)
        main_splitter.setSizes([900, 500])

    def _connect_signals(self):
        self.search_edit.textChanged.connect(self._filter_history)
        self.favorites_only_checkbox.stateChanged.connect(self._filter_history)
        self.history_table.cellClicked.connect(self._on_cell_clicked)
        self.history_table.customContextMenuRequested.connect(self._show_history_context_menu)
        self.history_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.enhance_button.clicked.connect(self._on_enhance_clicked)
        self.history_table.verticalScrollBar().valueChanged.connect(self._lazy_load_visible_thumbnails)
        self.history_table.cellEntered.connect(self._on_table_cell_entered)
        self.generate_image_button.clicked.connect(self._on_generate_image_clicked)
        self.generate_image_button.clicked.connect(self._on_generate_image_clicked)
        self.delete_button.clicked.connect(self._delete_selected)
        self.load_prompt_button.clicked.connect(self._on_load_prompt_clicked)
        self.image_gallery.itemDoubleClicked.connect(self._on_image_double_clicked)
        self.image_gallery.customContextMenuRequested.connect(self._show_image_context_menu)
        self.image_gallery.itemEntered.connect(self._on_image_gallery_item_entered)
        self.image_preview_timer.timeout.connect(self._show_image_preview_popup)
        self.prompt_selector_combo.currentTextChanged.connect(self._on_prompt_selection_changed)

    def _setup_persistent_thumbnail_worker(self):
        """Creates and starts a pool of long-lived worker threads for thumbnail loading."""
        self.persistent_thumb_threads: List[QThread] = []
        self.persistent_thumb_workers: List[ThumbnailLoaderWorker] = []
        num_workers = 4 # Number of concurrent thumbnail loaders

        for i in range(num_workers):
            thread = QThread(self)
            worker = ThumbnailLoaderWorker(self.processor, (200, 200), self.shared_thumb_job_queue) # Pass shared queue
            worker.moveToThread(thread)

            worker.thumbnail_ready.connect(self._on_any_thumbnail_ready)
            thread.started.connect(worker.run)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)

            self.persistent_thumb_threads.append(thread)
            self.persistent_thumb_workers.append(worker)
            thread.start()

    def _start_loading_history(self):
        self.history_table.clearContents()
        self.history_table.setRowCount(1)
        self.history_table.setItem(0, 2, QTableWidgetItem("Loading history..."))

        self.history_loader_thread = QThread(self)
        self.worker = HistoryLoaderWorker(self.processor)
        self.worker.moveToThread(self.history_loader_thread)

        self.history_loader_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_history_loaded)
        self.worker.finished.connect(self.history_loader_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.history_loader_thread.finished.connect(self.history_loader_thread.deleteLater)

        self.history_loader_thread.start()

    def _get_cover_image_path_for_row(self, row: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """Finds the cover image path and its workflow for a given history row data."""
        image_lists_to_check = []
        if row.get('original_images'): image_lists_to_check.append(row['original_images'])
        if row.get('enhanced', {}).get('images'): image_lists_to_check.append(row['enhanced']['images'])
        for var_data in row.get('variations', {}).values():
            if var_data.get('images'): image_lists_to_check.append(var_data['images'])

        workflow_source = row.get('workflow_source', 'sfw')

        for img_list in image_lists_to_check:
            for img_data in img_list:
                if img_data.get('is_cover_image') and img_data.get('image_path'):
                    return img_data['image_path'], workflow_source

        # If no explicit cover image, find the first available image
        for img_list in image_lists_to_check:
            if img_list:
                first_image_path = img_list[0].get('image_path')
                if first_image_path:
                    return first_image_path, workflow_source

        return None, None

    @Slot(list)
    def _on_history_loaded(self, history: List[Dict[str, Any]]):
        self.all_history_data = sorted(history, key=lambda x: x.get('timestamp', ''), reverse=True)
        self.history_table.clearContents()
        self.history_table.setRowCount(len(self.all_history_data))
        self.row_to_entry_map.clear()

        for row, entry in enumerate(self.all_history_data):
            self.row_to_entry_map[row] = entry
            fav_char = "★" if entry.get('favorite') else ""

            # More robustly find a prompt to display
            prompt = (entry.get('enhanced', {}).get('prompt') or
                      entry.get('prompt') or # Check for legacy top-level prompt
                      entry.get('original_prompt') or
                      next((v.get('prompt') for v in entry.get('variations', {}).values() if v.get('prompt')), 'No prompt found'))

            # Create an item for the first column and store the original row index in it.
            # This makes selection robust even after sorting.
            item_fav = QTableWidgetItem(fav_char)
            item_fav.setData(Qt.UserRole, row)
            item_fav.setTextAlignment(Qt.AlignCenter)
            if entry.get('favorite'):
                item_fav.setForeground(self.favorite_star_color)
                item_fav.setFont(QFont("Arial", 14, QFont.Bold))
            thumb_item = QTableWidgetItem() # Placeholder for the thumbnail

            self.history_table.setItem(row, 0, item_fav)
            self.history_table.setItem(row, 1, thumb_item)
            self.history_table.setItem(row, 2, QTableWidgetItem(entry.get('timestamp', '')))
            self.history_table.setItem(row, 3, QTableWidgetItem(prompt))
            self.history_table.setItem(row, 4, QTableWidgetItem(entry.get('status', '')))
            self.history_table.setItem(row, 5, QTableWidgetItem(entry.get('template_name', '')))
        
        # Enable sorting after the table is populated
        self.history_table.setSortingEnabled(True)
        self.history_table.sortByColumn(2, Qt.SortOrder.DescendingOrder) # Sort by timestamp by default
        
        # Trigger an initial load of visible thumbnails
        self.history_table.resizeEvent = lambda event: self._on_table_resize(event) # type: ignore
        QTimer.singleShot(100, self._lazy_load_visible_thumbnails)

        # Select the first row and trigger selection changed to load details
        if self.history_table.rowCount() > 0:
            self.history_table.selectRow(0)
            # Explicitly call the slot to ensure details are loaded
            self._on_selection_changed()

    def _on_table_resize(self, event):
        """Handle table resize to load thumbnails for newly visible items."""
        QTableWidget.resizeEvent(self.history_table, event)
        self._lazy_load_visible_thumbnails()

    def _lazy_load_visible_thumbnails(self):
        """Identifies visible rows and queues their thumbnails for loading."""
        first_visible_row = self.history_table.rowAt(0)
        if first_visible_row == -1: first_visible_row = 0 # Handle empty table case
        last_visible_row = self.history_table.rowAt(self.history_table.viewport().height())
        if last_visible_row == -1: last_visible_row = self.history_table.rowCount() - 1
        for row in range(first_visible_row, last_visible_row + 1):
            self._request_thumbnail_for_row(row)

    def _request_thumbnail_for_row(self, row: int):
        """Checks if a row needs its thumbnail loaded and queues it."""
        thumb_item = self.history_table.item(row, 1)
        if not thumb_item or thumb_item.data(ThumbnailDelegate.PixmapRole): return
        original_row_index_item = self.history_table.item(row, 0)
        if not original_row_index_item: return # Row might not be fully populated yet
        original_row_index = original_row_index_item.data(Qt.UserRole)
        entry = self.row_to_entry_map.get(original_row_index)
        if entry:
            cover_image_path, workflow = self._get_cover_image_path_for_row(entry)
            if cover_image_path and workflow:
                # --- NEW: Add job to the persistent worker ---
                job = {'item': thumb_item, 'image_path': cover_image_path, 'workflow_source': workflow}
                self.shared_thumb_job_queue.put(job) # Add job to shared queue

    @Slot(dict)
    def _on_any_thumbnail_ready(self, result: dict):
        """Unified slot to handle thumbnails for both the table and the gallery."""
        item_widget = result.get('item')
        qimage: Optional[QImage] = result.get('thumb_image')
        
        if not item_widget or not qimage:
            return

        if isinstance(item_widget, QTableWidgetItem):
            # Handle table thumbnail
            if item_widget.tableWidget() is None: return # Item is no longer in the table
            pixmap = QPixmap.fromImage(qimage)
            item_widget.setData(ThumbnailDelegate.PixmapRole, pixmap)
        elif isinstance(item_widget, ImageGalleryItemWidget): # Check for our custom widget
            # Handle gallery thumbnail
            pixmap = QPixmap.fromImage(qimage)
            item_widget.set_image(pixmap)
            # No need to updateGeometries() here, as the custom widget manages its own layout
            
            # --- NEW: Update the stored data with full_path ---
            # The item_widget here is the custom widget, not the QListWidgetItem.
            # We need to find the corresponding QListWidgetItem to update its data.
            # This is a bit indirect, but necessary if we want to keep data in QListWidgetItem.
            # A more direct approach would be to store full_path directly in the custom widget.
            # For now, let's assume the full_path is not strictly needed in the QListWidgetItem's data
            # after the thumbnail is loaded, as it's primarily for the preview popup.
            # The preview popup will get the full_path from the original job data.


    @Slot(int, int)
    def _on_table_cell_entered(self, row: int, column: int):
        """Shows a preview popup when the mouse enters a cell in the history table, if it's the thumbnail column."""
        self.image_preview_timer.stop() # Stop any previous timer
        self.image_preview_popup.hide() # Hide any active popup
        if column == 1: # Thumbnail column
            thumb_item = self.history_table.item(row, 1)
            if thumb_item and thumb_item.data(ThumbnailDelegate.PixmapRole):
                # Get the full path from the original entry data
                original_row_index_item = self.history_table.item(row, 0)
                if not original_row_index_item: return
                original_row_index = original_row_index_item.data(Qt.UserRole)
                entry = self.row_to_entry_map.get(original_row_index)
                if entry:
                    cover_image_path, _ = self._get_cover_image_path_for_row(entry)
                    if cover_image_path:
                        # Construct the full path using the correct workflow context
                        workflow = entry.get('workflow_source', 'sfw')
                        original_workflow = config.workflow
                        config.workflow = workflow.lower()
                        full_path = os.path.join(config.get_history_file_dir(), cover_image_path)
                        config.workflow = original_workflow # Restore immediately
                        self._current_hover_image_path = full_path
                        self.image_preview_timer.start() # Start the timer
        else:
            self.image_preview_popup.hide() # Hide if not hovering over a thumbnail

    @Slot(int, int)
    def _on_cell_clicked(self, row: int, column: int):
        """Handle clicks on table cells, specifically for favoriting."""
        if column != 0: # Only handle clicks on the 'Favorite' column
            return

        item = self.history_table.item(row, 0)
        if not item: return

        original_row_index = item.data(Qt.UserRole)
        original_entry = self.row_to_entry_map.get(original_row_index)
        if not original_entry: return

        # Create a deep copy to modify
        updated_entry = copy.deepcopy(original_entry)
        is_currently_favorite = updated_entry.get('favorite', False)
        updated_entry['favorite'] = not is_currently_favorite

        # Update the backend
        if self.processor.history_manager.update_history_entry(original_entry, updated_entry):
            # Update the in-memory store
            self.row_to_entry_map[original_row_index] = updated_entry
            self.all_history_data[original_row_index] = updated_entry

            # Update the UI
            item.setText("★" if updated_entry['favorite'] else "")
            item.setForeground(self.favorite_star_color if updated_entry['favorite'] else QColor(Qt.GlobalColor.black)) # Adjust for theme later
            font = QFont("Arial", 14, QFont.Bold) if updated_entry['favorite'] else QFont()
            item.setFont(font)

    @Slot(QPoint)
    def _show_history_context_menu(self, pos: QPoint):
        """Shows a context menu for the selected history item."""
        menu = QMenu(self)

        # Actions from the buttons below the table
        load_action = menu.addAction("Load Prompt")
        enhance_action = menu.addAction("Enhance")
        generate_image_action = menu.addAction("Generate Image")
        menu.addSeparator()
        delete_action = menu.addAction("Delete Entry")

        # Connect actions to existing slots
        load_action.triggered.connect(self._on_load_prompt_clicked)
        enhance_action.triggered.connect(self._on_enhance_clicked)
        generate_image_action.triggered.connect(self._on_generate_image_clicked)
        delete_action.triggered.connect(self._delete_selected)

        # Enable/disable actions based on selection, similar to buttons
        has_selection = len(self.history_table.selectionModel().selectedRows()) > 0
        load_action.setEnabled(has_selection)
        enhance_action.setEnabled(has_selection)
        generate_image_action.setEnabled(has_selection and self.processor.is_invokeai_connected())
        delete_action.setEnabled(has_selection)

        menu.exec(self.history_table.mapToGlobal(pos))

    def _get_available_prompts_for_entry(self, entry: Dict[str, Any]) -> List[Tuple[str, str]]:
        """Returns a list of (label, prompt_text) for all available prompts in an entry."""
        prompts = []

        # Original Prompt
        original_prompt = entry.get('original_prompt', '')
        if original_prompt:
            prompts.append(("Original Prompt", original_prompt))

        # Enhanced Prompt
        enhanced_prompt = entry.get('enhanced', {}).get('prompt', '')
        if enhanced_prompt:
            prompts.append(("Enhanced Prompt", enhanced_prompt))

        # Variation Prompts
        for var_key, var_data in entry.get('variations', {}).items():
            var_prompt = var_data.get('prompt', '')
            if var_prompt:
                prompts.append((f"Variation: {var_key.capitalize()}", var_prompt))
        
        if not prompts:
            prompts.append(("No Prompt Found", "No prompt text available for this entry."))

        return prompts

    def _format_prompt_details(self, entry: Dict[str, Any], prompt_text: str) -> str:
        """Formats a history entry into a human-readable string for display, with a specific prompt."""
        details = []

        # Basic Info
        details.append(f"Timestamp: {entry.get('timestamp', 'N/A')}")
        details.append(f"Status: {entry.get('status', 'N/A')}")
        details.append(f"Template: {entry.get('template_name', 'N/A')}")
        details.append(f"Workflow: {entry.get('workflow_source', 'N/A').upper()}")
        details.append(f"Favorite: {'Yes' if entry.get('favorite') else 'No'}")

        # Prompt
        details.append(f"Prompt:\n{prompt_text}\n")


        
        return "\n".join(details)

    @Slot(str)
    def _on_prompt_selection_changed(self, selected_label: str):
        """Updates the details_text with the prompt corresponding to the selected label."""
        # Get the currently selected row
        # This slot is called even when selection is cleared, so we need to check if there's an actual selection
        if not self._current_history_entry: # Use the stored entry
            self.details_group.setVisible(False)
            return

        entry = self._current_history_entry # Use the stored entry

        available_prompts = self._get_available_prompts_for_entry(entry)
        for label, prompt_text in available_prompts:
            if label == selected_label:
                self.details_text.setPlainText(self._format_prompt_details(entry, prompt_text))
                return

    @Slot()
    def _on_selection_changed(self):
        selected_rows = self.history_table.selectionModel().selectedRows()
        if not selected_rows:
            self.details_text.clear()
            self.image_gallery.clear()
            self._update_action_buttons()
            # Clear prompt selector
            self.prompt_selector_combo.clear()
            self._current_history_entry = None # Clear the stored entry
            return

        selected_row_index = selected_rows[0].row()
        # Retrieve the original data index we stored in the first column's item.
        item = self.history_table.item(selected_row_index, 0)
        if not item:
            return

        original_row_index = item.data(Qt.UserRole)
        entry = self.row_to_entry_map.get(original_row_index)
        self._current_history_entry = entry # Store the current entry

        if entry:
            # Populate the prompt selector combo box
            self.prompt_selector_combo.blockSignals(True) # Block signals to prevent re-triggering
            self.prompt_selector_combo.clear()
            available_prompts = self._get_available_prompts_for_entry(entry)
            for label, _ in available_prompts:
                self.prompt_selector_combo.addItem(label)
            self.prompt_selector_combo.blockSignals(False)

            # Set initial display to the first available prompt (or original/enhanced if preferred)
            if available_prompts:
                # Try to default to Enhanced, then Original, then first available
                default_prompt_label = available_prompts[0][0]
                for label, _ in available_prompts:
                    if label == "Enhanced Prompt":
                        default_prompt_label = label
                        break
                    elif label == "Original Prompt":
                        default_prompt_label = label
                self.prompt_selector_combo.setCurrentText(default_prompt_label)
            else:
                self.details_text.setPlainText("No prompt details available.")

            self._load_images_for_entry(entry)
        else:
            self.image_gallery.clear()
            self.prompt_selector_combo.clear()
            self._current_history_entry = None # Clear the stored entry

        self._update_action_buttons()

    def _update_action_buttons(self):
        """Enables or disables action buttons based on selection."""
        has_selection = len(self.history_table.selectionModel().selectedRows()) > 0
        self.load_prompt_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        self.enhance_button.setEnabled(has_selection)
        self.generate_image_button.setEnabled(has_selection and self.processor.is_invokeai_connected())

    @Slot()
    def _filter_history(self):
        """Filters the history table based on search text and favorite status."""
        search_term = self.search_edit.text().lower()
        favorites_only = self.favorites_only_checkbox.isChecked()

        for row in range(self.history_table.rowCount()):
            item_fav = self.history_table.item(row, 0)
            prompt_item = self.history_table.item(row, 2)
            status_item = self.history_table.item(row, 3)
            template_item = self.history_table.item(row, 4)

            if not item_fav: continue

            # Check favorite status
            original_row_index = item_fav.data(Qt.UserRole)
            entry = self.row_to_entry_map.get(original_row_index)
            is_favorite = entry.get('favorite', False) if entry else False
            favorite_match = not favorites_only or is_favorite

            # Check search term match
            search_match = (
                not search_term or
                (prompt_item and search_term in prompt_item.text().lower()) or
                (status_item and search_term in status_item.text().lower()) or
                (template_item and search_term in template_item.text().lower())
            )
            
            self.history_table.setRowHidden(row, not (favorite_match and search_match))

    @Slot()
    def _delete_selected(self):
        selected_rows = self.history_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select an entry to delete.")
            return

        selected_row_index = selected_rows[0].row()
        item = self.history_table.item(selected_row_index, 0)
        if not item:
            return

        original_row_index = item.data(Qt.UserRole)
        entry = self.row_to_entry_map.get(original_row_index)
        if not entry:
            return

        reply = QMessageBox.question(self, "Confirm Delete", "Are you sure you want to delete this history entry and its associated images?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self.processor.history_manager.delete_history_entry(entry):
                self._start_loading_history() # Reload the list
                QMessageBox.information(self, "Success", "History entry deleted.")
            else:
                QMessageBox.critical(self, "Error", "Failed to delete the history entry.")

    @Slot()
    def _on_load_prompt_clicked(self):
        """Handles the 'Load Prompt' button click."""
        selected_rows = self.history_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        selected_row_index = selected_rows[0].row()
        item = self.history_table.item(selected_row_index, 0)
        if not item:
            return

        original_row_index = item.data(Qt.UserRole)
        entry = self.row_to_entry_map.get(original_row_index)
        if entry:
            self.prompt_to_load.emit(entry)
            self.accept() # Close the dialog with an OK result

    @Slot()
    def _on_enhance_clicked(self):
        """Handles the 'Enhance' button click."""
        selected_rows = self.history_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        item = self.history_table.item(selected_rows[0].row(), 0)
        if not item:
            return

        original_row_index = item.data(Qt.UserRole)
        entry = self.row_to_entry_map.get(original_row_index)
        if not entry:
            return

        prompt_text = entry.get('enhanced', {}).get('prompt') or entry.get('original_prompt', '')
        if not prompt_text:
            QMessageBox.warning(self, "No Prompt", "The selected history entry has no prompt text to enhance.")
            return

        # Call the main app's workflow to open the enhancement window
        parent_app = self.parent()
        from .gui_app import GUIApp
        if isinstance(parent_app, GUIApp):
            parent_app.start_enhancement_workflow(prompt_text)

    def _get_params_for_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Finds the generation parameters for an entry, prioritizing the cover image,
        then the first available image. Falls back to the entry's context.
        """
        image_lists_to_check = []
        if entry.get('original_images'):
            image_lists_to_check.append(entry['original_images'])
        if entry.get('enhanced', {}).get('images'): image_lists_to_check.append(entry['enhanced']['images'])
        for var_data in entry.get('variations', {}).values():
            if var_data.get('images'): image_lists_to_check.append(var_data['images'])

        # Find cover image
        for img_list in image_lists_to_check:
            for img_data in img_list:
                if img_data.get('is_cover_image') and img_data.get('generation_params'):
                    return img_data['generation_params']

        # Find first image with params
        for img_list in image_lists_to_check:
            if img_list and img_list[0].get('generation_params'):
                return img_list[0]['generation_params']

        # Fallback to entry context
        return entry.get('context', {})

    @Slot()
    def _on_generate_image_clicked(self):
        """Handles the 'Generate Image' button click."""
        selected_rows = self.history_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        item = self.history_table.item(selected_rows[0].row(), 0)
        if not item: return

        original_row_index = item.data(Qt.UserRole)
        entry = self.row_to_entry_map.get(original_row_index)
        if not entry: return

        # --- NEW: Use the currently selected prompt from the dropdown ---
        selected_prompt_label = self.prompt_selector_combo.currentText()
        available_prompts = self._get_available_prompts_for_entry(entry)
        prompt_text = ""
        for label, text in available_prompts:
            if label == selected_prompt_label:
                prompt_text = text
                break
        
        # Fallback to old behavior if the selected prompt can't be found for some reason
        if not prompt_text:
            prompt_text = entry.get('enhanced', {}).get('prompt') or entry.get('original_prompt', '')

        if not prompt_text:
            QMessageBox.warning(self, "No Prompt", "The selected history entry has no prompt text to generate an image from.")
            return

        # --- NEW: Use the new helper to get the correct parameters ---
        initial_params = self._get_params_for_entry(entry)
        dialog = ImageGenerationOptionsDialog(self, self.processor, prompt_text, initial_params=initial_params)
        if dialog.exec() == QDialog.Accepted:
            options = dialog.get_options()
            selected_models = options.pop('models', [])
            if not selected_models:
                QMessageBox.warning(self, "No Models Selected", "You must select at least one model to generate images.")
                return

            generation_jobs = []
            num_images_per_model = options.pop('num_images', 1)
            base_seed = options.get('seed', random.randint(0, 2**32 - 1))

            for model_info in selected_models:
                for i in range(num_images_per_model):
                    job_params = options.copy()
                    job_params['model'] = model_info.get('model')
                    job_params['loras'] = model_info.get('loras', [])
                    job_params['negative_prompt'] = model_info.get('negative_prompt', '')
                    job_params['seed'] = base_seed + i
                    generation_jobs.append({
                        'prompt': prompt_text,
                        'gen_params': job_params
                    })
            
            # The on_success callback is now responsible for saving the kept images to history
            # and then refreshing the history viewer.
            def on_success(kept_images: List[Dict[str, Any]]):
                """Callback to save new images to history and refresh the history viewer."""
                if kept_images:
                    # Create a deep copy of the original entry to modify
                    updated_entry = copy.deepcopy(entry)
                    
                    # Ensure 'original_images' list exists
                    if 'original_images' not in updated_entry:
                        updated_entry['original_images'] = []

                    history_file_dir = config.get_history_file_dir() # Get the base history directory

                    for image_data in kept_images:
                        # The image_name from InvokeAI is the relative path within the history directory
                        image_path_relative = image_data.get('image_name')
                        image_bytes = image_data.get('bytes')
                        gen_params = image_data.get('generation_params', {})

                        if image_path_relative and image_bytes:
                            # Construct the full path where the image should be saved
                            # The image_path_relative is already in the format 'images/entry_id/filename.png'
                            # due to the normalization in history_manager.save_result
                            full_image_path = os.path.join(history_file_dir, image_path_relative)
                            
                            # Ensure the directory exists
                            os.makedirs(os.path.dirname(full_image_path), exist_ok=True)

                            # Write the image bytes to the file
                            try:
                                with open(full_image_path, 'wb') as f:
                                    f.write(image_bytes)
                                if self.processor.verbose:
                                    print(f"INFO: Saved generated image to {full_image_path}")
                            except IOError as e:
                                print(f"ERROR: Could not save image to {full_image_path}. Error: {e}")
                                continue # Skip to the next image if saving fails

                            new_image_info = {
                                'image_path': image_path_relative,
                                'generation_params': gen_params,
                                'is_cover_image': False # New images are not cover by default
                            }
                            updated_entry['original_images'].append(new_image_info)
                    
                    # Update the history entry in the backend
                    self.processor.history_manager.update_history_entry(entry, updated_entry)
                
                self._start_loading_history()

            preview_dialog = MultiImagePreviewDialog(self, self.processor, generation_jobs, on_success_callback=on_success, save_to_gallery=config.save_to_gallery_by_default)
            preview_dialog.exec()

    def _load_images_for_entry(self, entry: Dict[str, Any]):
        """Starts a background worker to load thumbnails for the selected entry."""
        self.image_gallery.clear()
        
        # --- NEW: Disable updates for faster population ---
        self.image_gallery.setUpdatesEnabled(False)

        workflow_source = entry.get('workflow_source', 'sfw')
        all_image_data = []
        def collect(images: List[Dict], prompt_type: str):
            for img in images:
                # Create a new dict to avoid modifying the original entry data
                job_data = {**img, 'prompt_type': prompt_type, 'workflow_source': workflow_source}
                # --- NEW: Add 'params' if it exists in img ---
                if 'params' in img:
                    job_data['params'] = img['params']
                elif 'generation_params' in img: # Fallback if 'params' is not directly available
                    job_data['params'] = img['generation_params']
                elif 'context' in entry: # Fallback to entry's context if image-specific params are missing
                    job_data['params'] = entry['context']
                all_image_data.append(job_data)

        collect(entry.get('original_images', []), 'Original')
        if 'enhanced' in entry:
            collect(entry['enhanced'].get('images', []), 'Enhanced')
        for var_key, var_data in entry.get('variations', {}).items():
            collect(var_data.get('images', []), var_key.capitalize())

        # --- NEW: Use the persistent worker ---
        # First, populate the gallery with placeholder items
        for data in all_image_data:
            # Get favorite status for the individual image
            image_is_favorite = data.get('favorite', False)
            item_text = f"{data['prompt_type']}{' ★' if image_is_favorite else ''}"
            
            custom_widget = ImageGalleryItemWidget(self.image_gallery)
            custom_widget.set_text(item_text)
            custom_widget.set_is_cover_image(data.get('is_cover_image', False))

            list_item = QListWidgetItem(self.image_gallery)
            list_item.setSizeHint(custom_widget.sizeHint())
            list_item.setData(Qt.ItemDataRole.UserRole, data) # Store original data in QListWidgetItem
            self.image_gallery.setItemWidget(list_item, custom_widget)
            
            # Now, create a job for this item
            job = {**data, 'item': custom_widget} # Pass the custom_widget to the worker
            self.shared_thumb_job_queue.put(job) # Add job to shared queue

        # --- NEW: Re-enable updates and force repaint ---
        self.image_gallery.setUpdatesEnabled(True)
        self.image_gallery.viewport().update()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Event filter to hide the image preview popup when the mouse leaves the image gallery viewport."""
        if (obj == self.image_gallery.viewport() or obj == self.history_table.viewport()) and event.type() == QEvent.Type.Leave:
            self.image_preview_timer.stop()
            self.image_preview_popup.hide()
            return True
        return super().eventFilter(obj, event)

    @Slot(QListWidgetItem)
    def _on_image_double_clicked(self, item: QListWidgetItem):
        """Opens the full-size image preview dialog."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            preview_dialog = ImagePreviewDialog(self, data['full_path'], data['params'])
            preview_dialog.exec()

    @Slot()
    def _show_image_preview_popup(self):
        """Shows the image preview popup using the stored image path."""
        if self._current_hover_image_path:
            try:
                from PIL import Image
                pil_image = Image.open(self._current_hover_image_path)
                self.image_preview_popup.show_image(pil_image, QCursor.pos())
            except Exception as e:
                print(f"Error showing image preview: {e}")

    @Slot(QListWidgetItem)
    def _on_image_gallery_item_entered(self, item: QListWidgetItem):
        """Starts a timer to show a preview popup when the mouse enters an image gallery item."""
        self.image_preview_timer.stop() # Stop any previous timer
        self.image_preview_popup.hide() # Hide any active popup
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and data.get('full_path'):
            self._current_hover_image_path = data['full_path']
            self.image_preview_timer.start() # Start the timer

    @Slot(QPoint)
    def _show_image_context_menu(self, pos: QPoint):
        """Shows a context menu for the selected image."""
        item = self.image_gallery.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        toggle_fav_action = menu.addAction("Toggle Favorite")
        set_cover_action = menu.addAction("Set as Entry Cover")
        menu.addSeparator()
        copy_path_action = menu.addAction("Copy Image Path")
        copy_image_action = menu.addAction("Copy Image")
        open_location_action = menu.addAction("Open Image Location")
        menu.addSeparator()
        delete_image_action = menu.addAction("Delete Image")

        action = menu.exec(self.image_gallery.mapToGlobal(pos))

        if action == toggle_fav_action:
            self._toggle_selected_image_favorite(item)
        elif action == set_cover_action:
            self._set_selected_image_as_cover(item)
        elif action == copy_path_action:
            self._copy_image_path(item)
        elif action == copy_image_action:
            self._copy_image(item)
        elif action == open_location_action:
            self._open_image_location(item)
        elif action == delete_image_action:
            self._delete_image(item)

    def _toggle_selected_image_favorite(self, item: QListWidgetItem):
        """Toggles the favorite status of an individual image."""
        image_data = item.data(Qt.ItemDataRole.UserRole)
        if not image_data: return

        # Find the main history entry
        selected_rows = self.history_table.selectionModel().selectedRows()
        if not selected_rows: return
        original_row_index = self.history_table.item(selected_rows[0].row(), 0).data(Qt.UserRole)
        original_entry = self.row_to_entry_map.get(original_row_index)
        if not original_entry: return

        updated_entry = copy.deepcopy(original_entry)
        image_path_to_find = image_data['full_path']

        # Find the specific image dict within the entry
        found_image_dict = None
        image_lists = [updated_entry.get('original_images', [])]
        if 'enhanced' in updated_entry:
            all_image_lists.append(updated_entry['enhanced'].get('images', []))
        for var_data in updated_entry.get('variations', {}).values():
            image_lists.append(var_data.get('images', []))

        for img_list in image_lists:
            for img_dict in img_list:
                if os.path.basename(img_dict.get('image_path', '')) == os.path.basename(image_path_to_find):
                    found_image_dict = img_dict
                    break
            if found_image_dict:
                break

        if found_image_dict:
            is_currently_favorite = found_image_dict.get('favorite', False)
            found_image_dict['favorite'] = not is_currently_favorite
            if self.processor.history_manager.update_history_entry(original_entry, updated_entry):
                self.row_to_entry_map[original_row_index] = updated_entry
                self.all_history_data[original_row_index] = updated_entry
                self._load_images_for_entry(updated_entry) # Reload to update UI

    def _set_selected_image_as_cover(self, item: QListWidgetItem):
        """Sets the selected image as the cover image for the history entry."""
        image_data = item.data(Qt.ItemDataRole.UserRole)
        if not image_data:
            return

        # Find the main history entry
        selected_rows = self.history_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        original_row_index = self.history_table.item(selected_rows[0].row(), 0).data(Qt.UserRole)
        original_entry = self.row_to_entry_map.get(original_row_index)
        if not original_entry:
            return

        updated_entry = copy.deepcopy(original_entry)
        image_path_to_find = image_data['full_path']

        # 1. Clear all existing cover image flags within the entry
        all_image_lists = [updated_entry.get('original_images', [])]
        if 'enhanced' in updated_entry:
            all_image_lists.append(updated_entry['enhanced'].get('images', []))
        for var_data in updated_entry.get('variations', {}).values():
            all_image_lists.append(var_data.get('images', []))

        for img_list in all_image_lists:
            for img_dict in img_list:
                if 'is_cover_image' in img_dict:
                    img_dict['is_cover_image'] = False

        # 2. Find the selected image and set it as the new cover
        found_and_set = False
        for img_list in all_image_lists:
            for img_dict in img_list:
                if os.path.basename(img_dict.get('image_path', '')) == os.path.basename(image_path_to_find):
                    img_dict['is_cover_image'] = True
                    found_and_set = True
                    break
            if found_and_set:
                break
        """Sets the selected image as the cover image for the history entry."""
        image_data = item.data(Qt.ItemDataRole.UserRole)
        if not image_data: return

        # Find the main history entry
        selected_rows = self.history_table.selectionModel().selectedRows()
        if not selected_rows: return
        original_row_index = self.history_table.item(selected_rows[0].row(), 0).data(Qt.UserRole)
        original_entry = self.row_to_entry_map.get(original_row_index)
        if not original_entry: return

        updated_entry = copy.deepcopy(original_entry)
        image_path_to_find = image_data['full_path']

        # 1. Clear all existing cover image flags within the entry
        all_image_lists = [updated_entry.get('original_images', [])]
        if 'enhanced' in updated_entry: all_image_lists.append(updated_entry['enhanced'].get('images', []))
        for var_data in updated_entry.get('variations', {}).values():
            all_image_lists.append(var_data.get('images', []))

        for img_list in all_image_lists:
            for img_dict in img_list:
                if 'is_cover_image' in img_dict:
                    img_dict['is_cover_image'] = False

        # 2. Find the selected image and set it as the new cover
        found_and_set = False
        for img_list in all_image_lists:
            for img_dict in img_list:
                if os.path.basename(img_dict.get('image_path', '')) == os.path.basename(image_path_to_find):
                    img_dict['is_cover_image'] = True
                    found_and_set = True
                    break
            if found_and_set: break # type: ignore

        if found_and_set and self.processor.history_manager.update_history_entry(original_entry, updated_entry):
            QMessageBox.information(self, "Success", "Cover image has been set. The list will now refresh.")
            self._start_loading_history() # Easiest way to reflect the change in the main table's thumbnail

    def _copy_image_path(self, item: QListWidgetItem):
        """Copies the full path of the selected image to the clipboard."""
        image_data = item.data(Qt.ItemDataRole.UserRole)
        if image_data and image_data.get('full_path'):
            clipboard = QApplication.clipboard()
            clipboard.setText(image_data['full_path'])
            QMessageBox.information(self, "Copied", "Image path copied to clipboard.")

    def _copy_image(self, item: QListWidgetItem):
        """Copies the selected image to the clipboard."""
        image_data = item.data(Qt.ItemDataRole.UserRole)
        if image_data and image_data.get('full_path'):
            pixmap = QPixmap(image_data['full_path'])
            if not pixmap.isNull():
                clipboard = QApplication.clipboard()
                clipboard.setPixmap(pixmap)
                QMessageBox.information(self, "Copied", "Image copied to clipboard.")
            else:
                QMessageBox.warning(self, "Error", "Could not load image to copy.")

    def _open_image_location(self, item: QListWidgetItem):
        """Opens the folder containing the selected image."""
        image_data = item.data(Qt.ItemDataRole.UserRole)
        if image_data and image_data.get('full_path'):
            folder_path = os.path.dirname(image_data['full_path'])
            if os.path.exists(folder_path):
                QDesktopServices.openUrl(folder_path)
            else:
                QMessageBox.warning(self, "Error", "Image folder not found.")

    def _delete_image(self, item: QListWidgetItem):
        """Deletes the selected image from the history entry and filesystem."""
        image_data = item.data(Qt.ItemDataRole.UserRole)
        if not image_data:
            return

        reply = QMessageBox.question(self, "Confirm Delete Image", "Are you sure you want to delete this image? This cannot be undone.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        # Find the main history entry
        selected_rows = self.history_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        original_row_index = self.history_table.item(selected_rows[0].row(), 0).data(Qt.UserRole)
        original_entry = self.row_to_entry_map.get(original_row_index)
        if not original_entry: return

        updated_entry = copy.deepcopy(original_entry)
        
        # Construct the full path from the relative image_path
        relative_image_path = image_data.get('image_path')
        if not relative_image_path:
            QMessageBox.warning(self, "Error", "Could not determine image path for deletion.")
            return
        
        workflow = image_data.get('workflow_source', 'sfw')
        original_workflow = config.workflow
        config.workflow = workflow.lower() # Set workflow context for path resolution
        history_file_dir = config.get_history_file_dir()
        image_path_to_delete = os.path.join(history_file_dir, relative_image_path)
        config.workflow = original_workflow # Restore workflow context

        # Remove the image from the entry's image lists
        found_and_removed = False
        all_image_lists = [updated_entry.get('original_images', [])]
        if 'enhanced' in updated_entry: all_image_lists.append(updated_entry['enhanced'].get('images', []))
        for var_data in updated_entry.get('variations', {}).values():
            all_image_lists.append(var_data.get('images', []))

        for img_list in all_image_lists:
            for img_dict in img_list:
                if os.path.basename(img_dict.get('image_path', '')) == os.path.basename(image_path_to_delete):
                    img_list.remove(img_dict)
                    found_and_removed = True
                    break
            if found_and_removed: break

        if found_and_removed:
            # Update the history entry in the backend
            if self.processor.history_manager.update_history_entry(original_entry, updated_entry):
                # Delete the actual image file
                try:
                    os.remove(image_path_to_delete)
                    QMessageBox.information(self, "Success", "Image deleted and history updated.")
                    self._load_images_for_entry(updated_entry) # Reload gallery
                    self._start_loading_history() # Reload main table to update cover image if needed
                except OSError as e:
                    QMessageBox.critical(self, "Error", f"Could not delete image file: {e}")
            else:
                QMessageBox.critical(self, "Error", "Failed to update history entry after image removal.")

    def closeEvent(self, event: QCloseEvent):
        """Handle window close event to stop any running threads."""
        try:
            if self.history_loader_thread and self.history_loader_thread.isRunning():
                self.history_loader_thread.quit()
                self.history_loader_thread.wait(1000)
            # Signal all persistent thumbnail workers to stop
            for thread in self.persistent_thumb_threads:
                if thread.isRunning():
                    thread.requestInterruption()
                    self.shared_thumb_job_queue.put(None) # Send sentinel to unblock worker
                    thread.quit()
                    thread.wait(1000)
        except RuntimeError: pass # Object already deleted

        super().closeEvent(event)