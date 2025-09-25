"""A Qt-based window for managing automatic prompt prefixes for specific InvokeAI assets."""

import json
from datetime import datetime
from typing import TYPE_CHECKING, List, Dict, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QSplitter, QGroupBox, QTreeWidget, QTreeWidgetItem, QLineEdit, QTextEdit, QLabel,
    QComboBox, QPushButton, QMessageBox, QFileDialog
)
from PySide6.QtGui import QCloseEvent

if TYPE_CHECKING:
    from .gui_app import GUIApp
    from core.prompt_processor import PromptProcessor

class AssetFetchWorker(QObject):
    """Worker to fetch InvokeAI assets in the background."""
    finished = Signal(dict)

    def __init__(self, processor: 'PromptProcessor'):
        super().__init__()
        self.processor = processor

    @Slot()
    def run(self):
        print("DEBUG: AssetFetchWorker.run started.")
        try:
            assets = {
                'model': {
                    'sdxl': self.processor.get_invokeai_models(base_model='sdxl'),
                    'sd-1.5': self.processor.get_invokeai_models(base_model='sd-1.5')
                },
                'lora': {
                    'sdxl': self.processor.get_invokeai_loras(base_model='sdxl'),
                    'sd-1.5': self.processor.get_invokeai_loras(base_model='sd-1.5')
                }
            }
            schedulers = self.processor.invokeai_client.get_schedulers()
            print(f"DEBUG: AssetFetchWorker fetched {len(assets['model']['sdxl'])} SDXL models, {len(assets['model']['sd-1.5'])} SD1.5 models.")
            print(f"DEBUG: AssetFetchWorker fetched {len(assets['lora']['sdxl'])} SDXL LoRAs, {len(assets['lora']['sd-1.5'])} SD1.5 LoRAs.")
            self.finished.emit({'success': True, 'assets': assets, 'schedulers': schedulers})
            print("DEBUG: AssetFetchWorker finished successfully.")
        except Exception as e:
            print(f"DEBUG: AssetFetchWorker FAILED with error: {e}")
            self.finished.emit({'success': False, 'error': str(e)})

class AssetPrefixEditorWindow(QDialog):
    """A window for managing automatic prompt prefixes for InvokeAI models and LoRAs."""

    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor'):
        super().__init__(parent)
        self.setWindowTitle("InvokeAI Asset Prefixes")
        print("DEBUG: AssetPrefixEditorWindow.__init__ called")
        self.processor = processor
        self.parent_app = parent
        self.model_prefixes = self.processor.load_model_prefixes()
        self.lora_prefixes = self.processor.load_lora_prefixes()
        self.fetch_thread: Optional[QThread] = None
        self.fetch_worker: Optional[AssetFetchWorker] = None
        self.is_dirty = False

        # Data Storage
        self.schedulers: List[str] = []
        self.model_asset_data: Dict[str, List[str]] = {'sdxl': [], 'sd-1.5': []}
        self.lora_asset_data: Dict[str, List[str]] = {'sdxl': [], 'sd-1.5': []}

        # UI Widget Storage
        self.notebook: Optional[QTabWidget] = None
        self.trees: Dict[str, QTreeWidget] = {}
        self.search_edits: Dict[str, QLineEdit] = {}
        self.positive_editors: Dict[str, QTextEdit] = {}
        self.negative_editors: Dict[str, QTextEdit] = {}
        self.scheduler_combos: Dict[str, QComboBox] = {}
        self.save_button: Optional[QPushButton] = None

        self._create_widgets()
        self._connect_signals()
        self.resize(1000, 700)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning
        self._fetch_assets()

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        top_controls = QHBoxLayout()
        top_controls.addStretch()
        refresh_button = QPushButton("Refresh Assets from Server")
        refresh_button.clicked.connect(self._refresh_assets)
        top_controls.addWidget(refresh_button)
        main_layout.addLayout(top_controls)

        self.notebook = QTabWidget()
        main_layout.addWidget(self.notebook)

        # Models Tab
        models_tab = QWidget()
        self._create_asset_tab(models_tab, 'model')
        self.notebook.addTab(models_tab, "Main Models")

        # LoRAs Tab
        loras_tab = QWidget()
        self._create_asset_tab(loras_tab, 'lora')
        self.notebook.addTab(loras_tab, "LoRAs")

        # Bottom Buttons
        button_layout = QHBoxLayout()
        import_button = QPushButton("Import All...")
        import_button.clicked.connect(self._import_all_prefixes)
        button_layout.addWidget(import_button)
        export_button = QPushButton("Export All...")
        export_button.clicked.connect(self._export_all_prefixes)
        button_layout.addWidget(export_button)
        button_layout.addStretch()
        self.save_button = QPushButton("Save Current Asset")
        self.save_button.setEnabled(False)
        button_layout.addWidget(self.save_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        button_layout.addWidget(close_button)
        main_layout.addLayout(button_layout)

    def _create_asset_tab(self, parent_widget: QWidget, asset_type: str):
        tab_layout = QVBoxLayout(parent_widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        tab_layout.addWidget(splitter)

        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        search_edit = QLineEdit()
        search_layout.addWidget(search_edit)
        left_layout.addLayout(search_layout)
        self.search_edits[asset_type] = search_edit

        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        left_layout.addWidget(tree)
        self.trees[asset_type] = tree
        splitter.addWidget(left_pane)

        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)

        pos_group = QGroupBox("Positive Prompt Prefix")
        pos_layout = QVBoxLayout(pos_group)
        positive_editor = QTextEdit()
        pos_layout.addWidget(positive_editor)
        right_layout.addWidget(pos_group)
        self.positive_editors[asset_type] = positive_editor

        neg_group = QGroupBox("Negative Prompt Prefix")
        neg_layout = QVBoxLayout(neg_group)
        negative_editor = QTextEdit()
        neg_layout.addWidget(negative_editor)
        right_layout.addWidget(neg_group)
        self.negative_editors[asset_type] = negative_editor

        if asset_type == 'model':
            scheduler_group = QGroupBox("Default Scheduler")
            scheduler_layout = QVBoxLayout(scheduler_group)
            scheduler_combo = QComboBox()
            scheduler_layout.addWidget(scheduler_combo)
            right_layout.addWidget(scheduler_group)
            self.scheduler_combos[asset_type] = scheduler_combo
        
        right_layout.addStretch()
        splitter.addWidget(right_pane)
        splitter.setSizes([300, 700])

    def _connect_signals(self):
        self.trees['model'].itemSelectionChanged.connect(lambda: self._on_asset_select('model'))
        self.trees['lora'].itemSelectionChanged.connect(lambda: self._on_asset_select('lora'))
        self.search_edits['model'].textChanged.connect(lambda: self._repopulate_tree('model'))
        self.search_edits['lora'].textChanged.connect(lambda: self._repopulate_tree('lora'))
        self.save_button.clicked.connect(self._save_prefixes)

        self.positive_editors['model'].textChanged.connect(self._mark_dirty)
        self.negative_editors['model'].textChanged.connect(self._mark_dirty)
        self.scheduler_combos['model'].currentTextChanged.connect(self._mark_dirty)
        self.positive_editors['lora'].textChanged.connect(self._mark_dirty)
        self.negative_editors['lora'].textChanged.connect(self._mark_dirty)

    def _fetch_assets(self):
        if not self.processor.is_invokeai_connected():
            QMessageBox.critical(self, "Not Connected", "InvokeAI is not configured or connected. Please set the URL in Settings.")
            return

        for tree in self.trees.values():
            tree.clear()
            tree.addTopLevelItem(QTreeWidgetItem(["Loading assets..."]))
            tree.setEnabled(False)

        print("DEBUG: _fetch_assets called. Starting worker thread.")
        self.fetch_thread = QThread(self)
        self.fetch_worker = AssetFetchWorker(self.processor)
        self.fetch_worker.moveToThread(self.fetch_thread)

        self.fetch_thread.started.connect(self.fetch_worker.run)
        self.fetch_worker.finished.connect(self._on_assets_fetched)
        self.fetch_worker.finished.connect(self.fetch_thread.quit)
        self.fetch_worker.finished.connect(self.fetch_worker.deleteLater)
        self.fetch_thread.finished.connect(self.fetch_thread.deleteLater)
        self.fetch_thread.start()

    @Slot(dict)
    def _on_assets_fetched(self, result: dict):
        for tree in self.trees.values():
            tree.clear()
            tree.setEnabled(True)

        if not result['success']:
            print(f"DEBUG: _on_assets_fetched received error: {result['error']}")
            QMessageBox.critical(self, "Fetch Error", f"Could not fetch assets from InvokeAI:\n{result['error']}")
            return

        print("DEBUG: _on_assets_fetched received success signal.")
        self.schedulers = ["(None)"] + result.get('schedulers', [])
        if 'model' in self.scheduler_combos:
            self.scheduler_combos['model'].clear()
            self.scheduler_combos['model'].addItems(self.schedulers)

        assets = result.get('assets', {})
        self.model_asset_data['sdxl'] = sorted([m['name'] for m in assets.get('model', {}).get('sdxl', [])], key=str.lower)
        self.model_asset_data['sd-1.5'] = sorted([m['name'] for m in assets.get('model', {}).get('sd-1.5', [])], key=str.lower)
        self.lora_asset_data['sdxl'] = sorted([m['name'] for m in assets.get('lora', {}).get('sdxl', [])], key=str.lower)
        self.lora_asset_data['sd-1.5'] = sorted([m['name'] for m in assets.get('lora', {}).get('sd-1.5', [])], key=str.lower)

        print(f"DEBUG: Stored {len(self.model_asset_data['sdxl'])} SDXL models and {len(self.model_asset_data['sd-1.5'])} SD1.5 models.")
        print(f"DEBUG: Stored {len(self.lora_asset_data['sdxl'])} SDXL LoRAs and {len(self.lora_asset_data['sd-1.5'])} SD1.5 LoRAs.")

        print("DEBUG: Calling _repopulate_tree for 'model' and 'lora'.")
        self._repopulate_tree('model')
        self._repopulate_tree('lora')

    def _repopulate_tree(self, asset_type: str):
        tree = self.trees.get(asset_type)
        if not tree: return

        asset_data = self.model_asset_data if asset_type == 'model' else self.lora_asset_data
        search_term = self.search_edits[asset_type].text().lower()
        print(f"DEBUG: _repopulate_tree for '{asset_type}'. Search term: '{search_term}'")
        
        tree.clear()
        tree.setUpdatesEnabled(False)

        total_added = 0
        for base_model, assets in asset_data.items():
            filtered_assets = [name for name in assets if search_term in name.lower()]
            if filtered_assets:
                category_item = QTreeWidgetItem(tree, [f"{base_model.upper()} {asset_type.capitalize()}s"])
                category_item.setExpanded(True)
                for name in filtered_assets:
                    total_added += 1
                    QTreeWidgetItem(category_item, [name])
        
        print(f"DEBUG: Added {total_added} items to the '{asset_type}' tree.")
        tree.setUpdatesEnabled(True)

    @Slot()
    def _on_asset_select(self, asset_type: str):
        tree = self.trees[asset_type]
        selected_items = tree.selectedItems()
        if not selected_items:
            self._clear_editors(asset_type)
            return

        item = selected_items[0]
        if not item.parent():
            self._clear_editors(asset_type)
            return

        asset_name = item.text(0)
        print(f"DEBUG: _on_asset_select for '{asset_type}'. Selected asset: '{asset_name}'")
        prefix_map = self.model_prefixes if asset_type == 'model' else self.lora_prefixes
        prefixes = prefix_map.get(asset_name, {})

        self.positive_editors[asset_type].setPlainText(prefixes.get("positive_prefix", ""))
        self.negative_editors[asset_type].setPlainText(prefixes.get("negative_prefix", ""))

        if asset_type == 'model':
            scheduler = prefixes.get("scheduler", "(None)")
            self.scheduler_combos[asset_type].setCurrentText(scheduler)
        
        self._clear_dirty()

    def _clear_editors(self, asset_type: str):
        self.positive_editors[asset_type].clear()
        self.negative_editors[asset_type].clear()
        if asset_type == 'model':
            self.scheduler_combos[asset_type].setCurrentIndex(0)
        self._clear_dirty()

    @Slot()
    def _save_prefixes(self):
        current_tab_index = self.notebook.currentIndex()
        asset_type = 'model' if current_tab_index == 0 else 'lora'

        tree = self.trees[asset_type]
        selected_items = tree.selectedItems()
        if not selected_items or not selected_items[0].parent():
            QMessageBox.warning(self, "No Asset Selected", f"Please select a {asset_type} to save prefixes for.")
            return

        asset_name = selected_items[0].text(0)
        positive_prefix = self.positive_editors[asset_type].toPlainText().strip()
        negative_prefix = self.negative_editors[asset_type].toPlainText().strip()
        
        scheduler_value = None
        if asset_type == 'model':
            scheduler_value = self.scheduler_combos[asset_type].currentText()
            if scheduler_value == "(None)":
                scheduler_value = None

        prefix_map = self.model_prefixes if asset_type == 'model' else self.lora_prefixes
        save_func = self.processor.save_model_prefixes if asset_type == 'model' else self.processor.save_lora_prefixes

        if not positive_prefix and not negative_prefix and not scheduler_value:
            if asset_name in prefix_map:
                del prefix_map[asset_name]
        else:
            prefix_map[asset_name] = {"positive_prefix": positive_prefix, "negative_prefix": negative_prefix}
            if scheduler_value:
                prefix_map[asset_name]["scheduler"] = scheduler_value

        try:
            save_func(prefix_map)
            self._clear_dirty()
            self.parent_app.status_bar.showMessage(f"Prefixes for '{asset_name}' saved.", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save {asset_type} prefixes:\n{e}")

    @Slot()
    def _refresh_assets(self):
        if QMessageBox.question(self, "Confirm Refresh", "This will re-fetch all models and LoRAs from the InvokeAI server. Continue?") == QMessageBox.StandardButton.Yes:
            self.processor.clear_invokeai_data_cache()
            self._fetch_assets()

    @Slot()
    def _export_all_prefixes(self):
        model_prefixes = self.processor.load_model_prefixes()
        lora_prefixes = self.processor.load_lora_prefixes()

        if not model_prefixes and not lora_prefixes:
            QMessageBox.information(self, "Nothing to Export", "There are no saved prefixes to export.")
            return

        combined_data = {"models": model_prefixes, "loras": lora_prefixes}
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"invokeai_asset_prefixes_backup_{timestamp}.json"

        filepath, _ = QFileDialog.getSaveFileName(self, "Export All Prefixes", filename, "JSON Files (*.json)")
        if not filepath: return

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(combined_data, f, indent=2)
            QMessageBox.information(self, "Export Successful", f"All prefixes exported to:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Could not export prefixes:\n{e}")

    @Slot()
    def _import_all_prefixes(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Import Prefixes", "", "JSON Files (*.json)")
        if not filepath: return

        if QMessageBox.question(self, "Confirm Import", "This will overwrite all existing prefixes. This action cannot be undone. Continue?") == QMessageBox.StandardButton.No:
            return

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            imported_models = data.get("models", {})
            imported_loras = data.get("loras", {})

            self.processor.save_model_prefixes(imported_models)
            self.processor.save_lora_prefixes(imported_loras)

            self.model_prefixes = imported_models
            self.lora_prefixes = imported_loras
            self._on_asset_select('model')
            self._on_asset_select('lora')

            QMessageBox.information(self, "Import Successful", "Successfully imported and saved all prefixes.")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Could not import prefixes:\n{e}")

    @Slot()
    def _mark_dirty(self):
        if not self.is_dirty:
            self.is_dirty = True
            self.save_button.setEnabled(True)
            self.setWindowTitle(self.windowTitle() + "*")

    def _clear_dirty(self):
        self.is_dirty = False
        self.save_button.setEnabled(False)
        self.setWindowTitle("InvokeAI Asset Prefixes")

    def closeEvent(self, event: QCloseEvent):
        if self.is_dirty:
            reply = QMessageBox.question(self, "Unsaved Changes", "You have unsaved changes. Do you want to save them before closing?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save:
                self._save_prefixes()
                if self.is_dirty:
                    event.ignore()
                else:
                    event.accept()
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
            else:
                event.accept()
        else:
            event.accept()