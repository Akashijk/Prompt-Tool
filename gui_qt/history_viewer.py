"""The Qt-based History Viewer window."""

import os
import json
import random
import copy
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QCheckBox,
    QLineEdit, QPushButton, QGroupBox, QTextEdit, QSplitter, QLabel, QMenu, QApplication,
    QAbstractItemView, QHeaderView, QMessageBox, QWidget, QListWidget, QListWidgetItem,
    QStyleOptionViewItem, QStyledItemDelegate
)
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QSize, QItemSelectionModel, QPoint, QModelIndex, QTimer
from PySide6.QtGui import QPixmap, QIcon, QImage, QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QCloseEvent, QAction, QPainter
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING

from core.prompt_processor import PromptProcessor
from core.config import config
from .image_preview_dialog import ImagePreviewDialog
from .multi_image_preview_dialog import MultiImagePreviewDialog
from PIL.ImageQt import ImageQt
if TYPE_CHECKING:
    from .gui_app import GUIApp
from .image_generation_dialog import ImageGenerationOptionsDialog


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

    def __init__(self, processor: PromptProcessor, image_data: List[Dict[str, Any]]):
        super().__init__()
        self.processor = processor
        self.image_data = image_data

    @Slot()
    def run(self):
        """Loads thumbnails and emits them one by one."""
        for data in self.image_data:
            if QThread.currentThread().isInterruptionRequested():
                break
            
            relative_path = data.get('image_path')
            workflow = data.get('workflow_source', 'sfw')
            # --- FIX: Pass through the item widget (QTableWidgetItem or QListWidgetItem) ---
            item_widget = data.get('item')

            if relative_path:
                # Construct the full path using the correct workflow context
                original_workflow = config.workflow
                config.workflow = workflow.lower()
                full_path = os.path.join(config.get_history_file_dir(), relative_path)
                config.workflow = original_workflow # Restore immediately
                if os.path.exists(full_path):
                    thumb_image = self.processor.thumbnail_manager.get_thumbnail(relative_path, workflow.lower())
                    if thumb_image:
                        # Emit a dictionary that contains all the original data plus the loaded image
                        result = {**data, 'item': item_widget, 'thumb_path': thumb_image, 'full_path': full_path}
                        self.thumbnail_ready.emit(result)
        self.finished.emit()

class ThumbnailDelegate(QStyledItemDelegate):
    """A delegate to draw pixmaps in table cells."""
    PixmapRole = Qt.ItemDataRole.UserRole + 2

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        pixmap = index.data(self.PixmapRole)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            # Scale the high-resolution pixmap smoothly to fit the cell's rectangle
            scaled_pixmap = pixmap.scaled(option.rect.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            if not scaled_pixmap.isNull():
                # Calculate the position to center the pixmap in the cell
                x = option.rect.x() + (option.rect.width() - scaled_pixmap.width()) / 2
                y = option.rect.y() + (option.rect.height() - scaled_pixmap.height()) / 2
                painter.drawPixmap(int(x), int(y), scaled_pixmap)
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
        self.thread: Optional[QThread] = None # For the main history loader
        self.history_thumb_loader_thread: Optional[QThread] = None
        self.thumbnail_queue = []
        self.thumbnail_worker_thread: Optional[QThread] = None
        self.thumbnail_worker: Optional[ThumbnailLoaderWorker] = None

        self._create_widgets()
        self._connect_signals()
        self._start_loading_history()
        self._update_action_buttons() # Set initial state
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning
        self.resize(1400, 800)

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
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels(["Favorite", "Thumbnail", "Timestamp", "Prompt", "Status", "Template"])
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setShowGrid(False)
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
        details_group = QGroupBox("Entry Details (JSON)")
        details_layout = QVBoxLayout(details_group)
        self.details_text = QTextEdit() # Keep a reference if needed, but use the new one
        self.details_text.setReadOnly(True)
        self.json_highlighter = JsonHighlighter(self.details_text.document())
        details_layout.addWidget(self.details_text) # Add the editor to the layout
        right_pane.addWidget(details_group)

        # Bottom-right: Image Gallery
        images_group = QGroupBox("Associated Images (Double-click to view)")
        images_layout = QVBoxLayout(images_group)
        self.image_gallery = QListWidget()
        self.image_gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.image_gallery.setIconSize(QSize(128, 128))
        self.image_gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.image_gallery.setWordWrap(True)
        self.image_gallery.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
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
        self.history_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.enhance_button.clicked.connect(self._on_enhance_clicked)
        self.history_table.verticalScrollBar().valueChanged.connect(self._lazy_load_visible_thumbnails)
        self.generate_image_button.clicked.connect(self._on_generate_image_clicked)
        self.generate_image_button.clicked.connect(self._on_generate_image_clicked)
        self.delete_button.clicked.connect(self._delete_selected)
        self.load_prompt_button.clicked.connect(self._on_load_prompt_clicked)
        self.image_gallery.itemDoubleClicked.connect(self._on_image_double_clicked)
        self.image_gallery.customContextMenuRequested.connect(self._show_image_context_menu)

    def _start_loading_history(self):
        self.history_table.clearContents()
        self.history_table.setRowCount(1)
        self.history_table.setItem(0, 2, QTableWidgetItem("Loading history..."))

        self.thread = QThread(self)
        self.worker = HistoryLoaderWorker(self.processor)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_history_loaded)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

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
        if not original_row_index_item: return
        original_row_index = original_row_index_item.data(Qt.ItemDataRole.UserRole)
        entry = self.row_to_entry_map.get(original_row_index)
        if entry:
            cover_image_path, workflow = self._get_cover_image_path_for_row(entry)
            if cover_image_path and workflow:
                self._load_table_thumbnail(thumb_item, cover_image_path, workflow)

    def _load_table_thumbnail(self, item: QTableWidgetItem, image_path: str, workflow: str):
        """Loads a thumbnail for a table cell in the background."""
        # Add a request to the queue
        self.thumbnail_queue.append({'item': item, 'image_path': image_path, 'workflow_source': workflow})
        self._start_thumbnail_worker()

    def _start_thumbnail_worker(self):
        """Starts the single thumbnail worker thread if it's not already running."""
        if self.thumbnail_worker_thread and self.thumbnail_worker_thread.isRunning():
            return # Worker is already active

        if not self.thumbnail_queue:
            return # Nothing to process

        self.thumbnail_worker_thread = QThread(self)
        # The worker will process the entire queue
        # --- FIX: Pass a copy of the queue to the worker ---
        jobs_to_process = list(self.thumbnail_queue)
        self.thumbnail_worker = ThumbnailLoaderWorker(self.processor, jobs_to_process)
        self.thumbnail_worker.moveToThread(self.thumbnail_worker_thread)

        # Clear the queue as the worker now has the jobs
        self.thumbnail_queue = []

        self.thumbnail_worker.thumbnail_ready.connect(self._on_table_thumbnail_ready)
        self.thumbnail_worker_thread.started.connect(self.thumbnail_worker.run)
        self.thumbnail_worker.finished.connect(self.thumbnail_worker_thread.quit)
        self.thumbnail_worker.finished.connect(self.thumbnail_worker.deleteLater)
        self.thumbnail_worker_thread.finished.connect(self.thumbnail_worker_thread.deleteLater)
        self.thumbnail_worker_thread.start()

    @Slot(dict)
    def _on_table_thumbnail_ready(self, result: dict):
        """Slot to receive a loaded thumbnail and apply it to the correct table cell."""
        item = result.get('item')
        thumb_image = result.get('thumb_path')
        if item and thumb_image:
            pixmap = QPixmap.fromImage(ImageQt(thumb_image))
            item.setData(ThumbnailDelegate.PixmapRole, pixmap)

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

    @Slot()
    def _on_selection_changed(self):
        selected_rows = self.history_table.selectionModel().selectedRows()
        if not selected_rows:
            self.details_text.clear()
            self.image_gallery.clear()
            self._update_action_buttons()
            return

        selected_row_index = selected_rows[0].row()
        # Retrieve the original data index we stored in the first column's item.
        item = self.history_table.item(selected_row_index, 0)
        if not item:
            return

        original_row_index = item.data(Qt.UserRole)
        entry = self.row_to_entry_map.get(original_row_index)

        if entry:
            # Pretty-print the JSON for display
            self.details_text.setPlainText(json.dumps(entry, indent=2))
            self._load_images_for_entry(entry)
        else:
            self.image_gallery.clear()

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
        if not item: return

        original_row_index = item.data(Qt.UserRole)
        entry = self.row_to_entry_map.get(original_row_index)
        if not entry: return

        prompt_text = entry.get('enhanced', {}).get('prompt') or entry.get('original_prompt', '')
        if not prompt_text:
            QMessageBox.warning(self, "No Prompt", "The selected history entry has no prompt text to enhance.")
            return

        # Call the main app's workflow to open the enhancement window
        parent_app = self.parent()
        from .gui_app import GUIApp
        if isinstance(parent_app, GUIApp):
            parent_app.start_enhancement_workflow(prompt_text)

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

        prompt_text = entry.get('enhanced', {}).get('prompt') or entry.get('original_prompt', '')
        if not prompt_text:
            QMessageBox.warning(self, "No Prompt", "The selected history entry has no prompt text to generate an image from.")
            return

        # Use the context from the history entry to pre-fill the dialog
        initial_params = entry.get('context', {})
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

            for model_obj in selected_models:
                for i in range(num_images_per_model):
                    job_params = options.copy()
                    job_params['model'] = model_obj
                    job_params['seed'] = base_seed + i
                    generation_jobs.append({
                        'prompt': prompt_text,
                        'gen_params': job_params
                    })
            
            # The on_success callback is now empty because the MultiImagePreviewDialog handles saving
            # to history itself. We just need to trigger a refresh of the history viewer.
            preview_dialog = MultiImagePreviewDialog(self, self.processor, generation_jobs, on_success_callback=lambda: self._start_loading_history())
            preview_dialog.exec()

    def _load_images_for_entry(self, entry: Dict[str, Any]):
        """Starts a background worker to load thumbnails for the selected entry."""
        if self.thumbnail_loader_thread and self.thumbnail_loader_thread.isRunning():
            self.thumbnail_loader_thread.requestInterruption()
            self.thumbnail_loader_thread.quit()
            self.thumbnail_loader_thread.wait()

        self.image_gallery.clear()
        
        # Collect all image data from the entry
        workflow_source = entry.get('workflow_source', 'sfw')
        all_image_data = []
        def collect(images: List[Dict], prompt_type: str):
            for img in images:
                img['prompt_type'] = prompt_type
                img['workflow_source'] = workflow_source
                all_image_data.append(img)

        # The HistoryManager now handles all legacy format migrations.
        # We only need to read the modern, consistent format here.
        collect(entry.get('original_images', []), 'Original')
        if 'enhanced' in entry:
            collect(entry['enhanced'].get('images', []), 'Enhanced')
        for var_key, var_data in entry.get('variations', {}).items():
            collect(var_data.get('images', []), var_key.capitalize())

        if not all_image_data:
            self.image_gallery.addItem("No images found for this entry.")
            return

        self.image_gallery.addItem("Loading images...")

        self.thumbnail_loader_thread = QThread(self)
        self.thumbnail_worker = ThumbnailLoaderWorker(self.processor, all_image_data)
        self.thumbnail_worker.moveToThread(self.thumbnail_loader_thread)

        self.thumbnail_loader_thread.started.connect(self.thumbnail_worker.run)
        self.thumbnail_worker.thumbnail_ready.connect(self._on_thumbnail_loaded)
        self.thumbnail_worker.finished.connect(self.thumbnail_loader_thread.quit)
        self.thumbnail_worker.finished.connect(self.thumbnail_worker.deleteLater)
        self.thumbnail_loader_thread.finished.connect(self.thumbnail_loader_thread.deleteLater)
        self.thumbnail_loader_thread.finished.connect(self._on_thumbnail_thread_finished)
        self.thumbnail_loader_thread.start()

    @Slot(dict)
    def _on_thumbnail_loaded(self, result: dict):
        """Adds a loaded thumbnail to the image gallery."""
        if self.image_gallery.item(0) and self.image_gallery.item(0).text() == "Loading images...":
            self.image_gallery.clear()

        pil_image = result.get('thumb_path')
        if pil_image:
            # Convert the PIL.Image object to a QImage, then to a QPixmap.
            qimage = ImageQt(pil_image)
            pixmap = QPixmap.fromImage(qimage) # Base pixmap

            is_favorite = result.get('params', {}).get('favorite', False)
            item_text = f"{result['prompt_type']}{' ★' if is_favorite else ''}"

            icon = QIcon(pixmap)
            item = QListWidgetItem(icon, item_text)
            item.setData(Qt.ItemDataRole.UserRole, result) # Store all data
            self.image_gallery.addItem(item)
            if is_favorite:
                item.setForeground(self.favorite_star_color)

    @Slot(QListWidgetItem)
    def _on_image_double_clicked(self, item: QListWidgetItem):
        """Opens the full-size image preview dialog."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            preview_dialog = ImagePreviewDialog(self, data['full_path'], data['params'])
            preview_dialog.exec()

    @Slot()
    def _on_thumbnail_thread_finished(self):
        """Slot to clean up the reference to the thumbnail loader thread."""
        self.thumbnail_loader_thread = None

    @Slot(QPoint)
    def _show_image_context_menu(self, pos: QPoint):
        """Shows a context menu for the selected image."""
        item = self.image_gallery.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        toggle_fav_action = menu.addAction("Toggle Favorite")
        set_cover_action = menu.addAction("Set as Entry Cover")

        action = menu.exec(self.image_gallery.mapToGlobal(pos))

        if action == toggle_fav_action:
            self._toggle_selected_image_favorite(item)
        elif action == set_cover_action:
            self._set_selected_image_as_cover(item)

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
        if 'enhanced' in updated_entry: image_lists.append(updated_entry['enhanced'].get('images', []))
        for var_data in updated_entry.get('variations', {}).values():
            image_lists.append(var_data.get('images', []))

        for img_list in image_lists:
            for img_dict in img_list:
                if os.path.basename(img_dict.get('image_path', '')) == os.path.basename(image_path_to_find):
                    found_image_dict = img_dict
                    break
            if found_image_dict: break

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

    def closeEvent(self, event: QCloseEvent):
        """Handle window close event to stop any running threads."""
        # Use a try-except block to gracefully handle threads that might already be deleted.
        try:
            if self.thread and self.thread.isRunning():
                self.thread.requestInterruption()
                self.thread.quit()
        except RuntimeError: pass # Object already deleted

        try:
            if self.thumbnail_loader_thread and self.thumbnail_loader_thread.isRunning():
                self.thumbnail_loader_thread.requestInterruption()
                self.thumbnail_loader_thread.quit()
        except RuntimeError: pass # Object already deleted

        try:
            if self.thumbnail_worker_thread and self.thumbnail_worker_thread.isRunning():
                self.thumbnail_worker_thread.requestInterruption()
                self.thumbnail_worker_thread.quit()
        except RuntimeError: pass # Object already deleted

        super().closeEvent(event)