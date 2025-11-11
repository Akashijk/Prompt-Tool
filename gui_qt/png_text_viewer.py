"""A Qt-based window for viewing PNG text chunks."""

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton, QLabel, QFrame, QMenu,
    QMessageBox, QFileDialog,
    QTreeWidget, QTreeWidgetItem, QLineEdit
)
from PySide6.QtCore import Slot, Qt, QPoint
from PySide6.QtGui import QFont, QColor
from typing import Dict, Any, TYPE_CHECKING

from PIL import Image
import os
import json
from datetime import datetime
import csv

from .custom_widgets import SmoothTextEdit

if TYPE_CHECKING:
    from .gui_app import GUIApp

class PNGTextViewerWindow(QDialog):
    """A window for viewing the text chunks of a PNG file."""

    def __init__(self, parent: 'GUIApp'):
        super().__init__(parent)
        self.setWindowTitle("PNG Text Chunk Viewer")
        self.parent_app = parent
        self.current_chunks: Dict[str, str] = {}

        self.key_font = QFont()
        self.key_font.setBold(True)
        self.key_color = QColor("#8e44ad")
        self.string_color = QColor("#27ae60")
        self.number_color = QColor("#f39c12")

        self._create_widgets()
        self._connect_signals()
        self.resize(900, 700)

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        # Drop zone
        self.drop_frame = QFrame(self)
        self.drop_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.drop_frame.setAcceptDrops(True)
        drop_layout = QVBoxLayout(self.drop_frame)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label = QLabel("📁 Drop PNG file here or click to browse")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(self.drop_label)
        main_layout.addWidget(self.drop_frame)

        # File info and controls
        controls_frame = QHBoxLayout()
        self.file_label = QLabel("No file loaded")
        controls_frame.addWidget(self.file_label, 1)
        self.expand_all_button = QPushButton("Expand All")
        controls_frame.addWidget(self.expand_all_button)
        self.collapse_all_button = QPushButton("Collapse All")
        controls_frame.addWidget(self.collapse_all_button)
        self.copy_button = QPushButton("Copy")
        controls_frame.addWidget(self.copy_button)
        self.export_button = QPushButton("Export")
        controls_frame.addWidget(self.export_button)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search...")
        controls_frame.addWidget(self.search_edit)
        self.search_button = QPushButton("Search")
        controls_frame.addWidget(self.search_button)
        main_layout.addLayout(controls_frame)

        # Splitter for file info and tree
        splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(splitter)

        # File info display
        self.file_info_display = SmoothTextEdit()
        self.file_info_display.setReadOnly(True)
        self.file_info_display.setFixedHeight(150)
        splitter.addWidget(self.file_info_display)

        # Tree display
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Key", "Value"])
        self.tree_widget.setColumnWidth(0, 200)
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        splitter.addWidget(self.tree_widget)

    def format_chunk_key(self, key):
        """Format chunk keys to be more human readable"""
        key_mappings = {
            'Title': '📄 Title',
            'Author': '👤 Author', 
            'Description': '📝 Description',
            'Copyright': '©️ Copyright',
            'Creation Time': '📅 Creation Time',
            'Software': '💻 Software',
            'Comment': '💭 Comment',
            'Source': '🔗 Source',
            'Disclaimer': '⚠️ Disclaimer',
            'Warning': '⚠️ Warning',
            'parameters': '🔧 AI Parameters',
            'prompt': '💡 AI Prompt',
            'workflow': '⚙️ Workflow',
            'model': '🤖 Model Info',
            'negative_prompt': '🚫 Negative Prompt',
            'steps': '🔢 Steps',
            'cfg_scale': '⚖️ CFG Scale',
            'seed': '🌱 Seed',
            'sampler': '🎲 Sampler',
            'upscaler': '🔍 Upscaler'
        }
        
        # Check for exact matches first
        if key in key_mappings:
            return key_mappings[key]
        
        # Check for partial matches (case insensitive)
        key_lower = key.lower()
        for original, formatted in key_mappings.items():
            if original.lower() in key_lower or key_lower in original.lower():
                return formatted
        
        # Auto-detect URLs and make them special
        if 'url' in key_lower or 'link' in key_lower or 'http' in str(key_lower):
            return f"🔗 {key.replace('_', ' ').title()}"
        
        # Auto-detect technical terms
        if any(term in key_lower for term in ['cfg', 'scale', 'step', 'seed', 'sample']):
            return f"🔧 {key.replace('_', ' ').title()}"
        
        # Default formatting
        return f"🏷️ {key.replace('_', ' ').title()}"

    def sort_chunks_by_importance(self, chunks):
        """Sort chunks by importance/relevance"""
        importance_order = [
            'Title', 'prompt', 'Description', 'Comment',
            'Author', 'Software', 'model', 'parameters', 
            'workflow', 'negative_prompt', 'steps', 'cfg_scale',
            'seed', 'sampler', 'upscaler', 'Copyright', 
            'Creation Time', 'Source'
        ]
        
        sorted_items = []
        remaining_items = dict(chunks)
        
        # Add items in order of importance
        for important_key in importance_order:
            for key in list(remaining_items.keys()):
                if important_key.lower() in key.lower():
                    sorted_items.append((key, remaining_items.pop(key)))
                    break
        
        # Add remaining items
        for key, value in remaining_items.items():
            sorted_items.append((key, value))
        
        return sorted_items

    def _format_json_to_tree(self, parent_item: QTreeWidgetItem, data: Any):
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    child_item = QTreeWidgetItem(parent_item, [str(key)])
                    child_item.setFont(0, self.key_font)
                    child_item.setForeground(0, self.key_color)
                    self._format_json_to_tree(child_item, value)
                else:
                    child_item = QTreeWidgetItem(parent_item, [str(key), str(value)])
                    child_item.setFont(0, self.key_font)
                    child_item.setForeground(0, self.key_color)
                    if isinstance(value, str):
                        child_item.setForeground(1, self.string_color)
                    elif isinstance(value, (int, float)):
                        child_item.setForeground(1, self.number_color)
                    if len(str(value)) > 50:
                        child_item.setToolTip(1, str(value))
        elif isinstance(data, list):
            for i, value in enumerate(data):
                if isinstance(value, (dict, list)):
                    child_item = QTreeWidgetItem(parent_item, [f"[{i}]"])
                    child_item.setFont(0, self.key_font)
                    child_item.setForeground(0, self.key_color)
                    self._format_json_to_tree(child_item, value)
                else:
                    child_item = QTreeWidgetItem(parent_item, [f"[{i}]", str(value)])
                    child_item.setFont(0, self.key_font)
                    child_item.setForeground(0, self.key_color)
                    if isinstance(value, str):
                        child_item.setForeground(1, self.string_color)
                    elif isinstance(value, (int, float)):
                        child_item.setForeground(1, self.number_color)
                    if len(str(value)) > 50:
                        child_item.setToolTip(1, str(value))

    def _connect_signals(self):
        self.drop_frame.dragEnterEvent = self.dragEnterEvent
        self.drop_frame.dragLeaveEvent = self.dragLeaveEvent
        self.drop_frame.dropEvent = self.dropEvent
        self.drop_label.mousePressEvent = self.browse_file
        self.expand_all_button.clicked.connect(self.tree_widget.expandAll)
        self.collapse_all_button.clicked.connect(self.tree_widget.collapseAll)
        self.export_button.clicked.connect(self._export_data)
        self.copy_button.clicked.connect(self._copy_to_clipboard)
        self.search_button.clicked.connect(self._search_text)
        self.search_edit.returnPressed.connect(self._search_text)
        self.tree_widget.customContextMenuRequested.connect(self._show_tree_context_menu)

    @Slot(QPoint)
    def _show_tree_context_menu(self, pos: QPoint):
        item = self.tree_widget.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        copy_action = menu.addAction("Copy Value")
        
        action = menu.exec(self.tree_widget.mapToGlobal(pos))

        if action == copy_action:
            value = item.text(1)
            QApplication.clipboard().setText(value)

    def _search_text(self):
        search_term = self.search_edit.text()
        if not search_term:
            # Clear selection
            self.tree_widget.clearSelection()
            # un-hide all items
            for i in range(self.tree_widget.topLevelItemCount()):
                item = self.tree_widget.topLevelItem(i)
                item.setHidden(False)
                for j in range(item.childCount()):
                    child = item.child(j)
                    child.setHidden(False)
            return

        self.tree_widget.clearSelection()
        self.tree_widget.collapseAll()

        for i in range(self.tree_widget.topLevelItemCount()):
            item = self.tree_widget.topLevelItem(i)
            match = False
            if search_term.lower() in item.text(0).lower():
                match = True
            
            for j in range(item.childCount()):
                child = item.child(j)
                if search_term.lower() in child.text(0).lower() or search_term.lower() in child.text(1).lower():
                    match = True
                    child.setHidden(False)
                else:
                    child.setHidden(True)
            
            if match:
                item.setHidden(False)
                item.setExpanded(True)
            else:
                item.setHidden(True)

    def _copy_to_clipboard(self):
        if not self.current_chunks:
            QMessageBox.warning(self, "No Data", "No chunks to copy.")
            return

        text = ""
        for key, value in self.current_chunks.items():
            text += f"{key}: {value}\n\n"
        
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", "Text chunks copied to clipboard.")

    def _export_data(self):
        if not self.current_chunks:
            QMessageBox.warning(self, "No Data", "No chunks to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Export PNG Metadata", 
            "", 
            "JSON files (*.json);;Text files (*.txt);;CSV files (*.csv)"
        )

        if file_path:
            try:
                if file_path.endswith('.json'):
                    with open(file_path, 'w', encoding='utf-8') as f:
                        export_data = {
                            'file_info': {
                                'filename': os.path.basename(self.file_label.text()),
                                'path': self.file_label.text(),
                                'exported_at': datetime.now().isoformat()
                            },
                            'chunks': self.current_chunks
                        }
                        json.dump(export_data, f, indent=2, ensure_ascii=False)
                elif file_path.endswith('.csv'):
                    with open(file_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(['Key', 'Value', 'Length'])
                        for key, value in self.current_chunks.items():
                            writer.writerow([key, str(value), len(str(value))])
                else:  # .txt
                    with open(file_path, 'w', encoding='utf-8') as f:
                        for key, value in self.current_chunks.items():
                            f.write(f"{key}: {value}\n\n")
                
                QMessageBox.information(self, "Exported", f"Data exported to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export: {str(e)}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        pass

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith('.png'):
                self.process_file(file_path)
                break

    def browse_file(self, event=None):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select PNG File", "", "PNG Files (*.png)")
        if file_path:
            self.process_file(file_path)

    def process_file(self, file_path):
        self.file_label.setText(os.path.basename(file_path))
        self.tree_widget.clear()
        self.file_info_display.clear()
        try:
            with Image.open(file_path) as img:
                # Display file info
                file_size = os.path.getsize(file_path)
                file_size_mb = file_size / (1024 * 1024)
                modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                self.file_info_display.append(f"<b>File:</b> {os.path.basename(file_path)}")
                self.file_info_display.append(f"<b>Path:</b> {file_path}")
                self.file_info_display.append(f"<b>Dimensions:</b> {img.size[0]} x {img.size[1]} pixels")
                self.file_info_display.append(f"<b>Color Mode:</b> {img.mode}")
                self.file_info_display.append(f"<b>File Size:</b> {file_size_mb:.2f} MB ({file_size:,} bytes)")
                self.file_info_display.append(f"<b>Modified:</b> {modified_time.strftime('%Y-%m-%d %H:%M:%S')}")

                text_chunks = {}
                if hasattr(img, 'text') and img.text:
                    text_chunks.update(img.text)
                
                if hasattr(img, 'info'):
                    for key, value in img.info.items():
                        if isinstance(value, str):
                            text_chunks[key] = value
                
                self.current_chunks = text_chunks
                
                if text_chunks:
                    sorted_chunks = self.sort_chunks_by_importance(text_chunks)
                    for key, value in sorted_chunks:
                        formatted_key = self.format_chunk_key(key)
                        item = QTreeWidgetItem(self.tree_widget, [formatted_key])
                        try:
                            # Try to parse as JSON
                            data = json.loads(value)
                            self._format_json_to_tree(item, data)
                        except json.JSONDecodeError:
                            item.setText(1, value)
                    self.tree_widget.expandAll()
                else:
                    item = QTreeWidgetItem(self.tree_widget, ["Info"])
                    item.setText(1, "No text chunks found in this PNG file.")

        except Exception as e:
            item = QTreeWidgetItem(self.tree_widget, ["Error"])
            item.setText(1, f"Error processing file: {e}")
