"""A Qt-based window for AI brainstorming and content generation."""

import re
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QInputDialog,
    QPushButton, QComboBox, QGroupBox, QSplitter, QWidget, QMessageBox, QApplication
)
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtGui import QTextCursor
from typing import List, Dict, Optional

from core.prompt_processor import PromptProcessor
from .review_and_save_dialog import ReviewAndSaveDialog
from core.config import config
from .custom_widgets import SmoothTextEdit, SmoothTextBrowser

class ChatWorker(QObject):
    """Worker to handle streaming chat with an AI model."""
    chunk_ready = Signal(str)
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor, model: str, messages: List[Dict[str, str]]):
        super().__init__()
        self.processor = processor
        self.model = model
        self.messages = messages

    @Slot()
    def run(self):
        full_response = ""
        try:
            for chunk in self.processor.ollama_client.stream_chat(self.model, self.messages):
                if QThread.currentThread().isInterruptionRequested():
                    break
                content = chunk.get('message', {}).get('content', '')
                if content:
                    full_response += content
                    self.chunk_ready.emit(content)
            self.finished.emit({'success': True, 'response': full_response})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

class ContentGenWorker(QObject):
    """Worker to generate content like templates or wildcards."""
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor, model: str, gen_type: str, topic: str):
        super().__init__()
        self.processor = processor
        self.model = model
        self.gen_type = gen_type
        self.topic = topic

    @Slot()
    def run(self):
        try:
            if self.gen_type == 'template':
                template, new_wildcards = self.processor.generate_template_for_brainstorming(self.model, self.topic)
                result = {'success': True, 'content': template, 'new_wildcards': new_wildcards}
            elif self.gen_type == 'wildcard':
                wildcard_json = self.processor.generate_wildcard_for_brainstorming(self.model, self.topic)
                result = {'success': True, 'content': wildcard_json}
            else:
                result = {'success': False, 'error': f"Unknown generation type: {self.gen_type}"}
            
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

    def _suggest_filename(self) -> str:
        """Suggests a filename based on the topic."""
        # Sanitize the topic to create a valid filename
        sanitized = re.sub(r'\s+', '_', self.topic.strip()).lower()
        sanitized = re.sub(r'[^a-z0-9_]', '', sanitized)
        
        if self.gen_type == 'template':
            return f"{sanitized}.txt"
        elif self.gen_type == 'wildcard':
            return f"{sanitized}.json"
        return "new_file"

class BrainstormingWindow(QDialog):
    """A window for AI brainstorming and content generation."""

    def __init__(self, parent, processor: PromptProcessor):
        super().__init__(parent)
        self.setWindowTitle("AI Brainstorming")
        self.processor = processor
        self.parent_app = parent
        self.chat_history: List[Dict[str, str]] = []
        self.current_worker_thread: Optional[QThread] = None
        self.content_gen_thread: Optional[QThread] = None

        self.models = [m['name'] for m in self.processor.get_ollama_models()]
        self.current_model: Optional[str] = None

        self._create_widgets()
        self._connect_signals()

        # Set the default model after widgets are created
        if config.DEFAULT_OLLAMA_MODEL and config.DEFAULT_OLLAMA_MODEL in self.models:
            self.model_combo.setCurrentText(config.DEFAULT_OLLAMA_MODEL)
        else:
            main_app_model = self.parent_app.model_combo.currentText()
            if main_app_model and main_app_model in self.models:
                self.model_combo.setCurrentText(main_app_model)
            elif self.models:
                self.model_combo.setCurrentIndex(0)
        
        self.current_model = self.model_combo.currentText()

        self.resize(800, 600)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        main_layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # --- Left Pane: Chat ---
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        
        self.chat_display = SmoothTextBrowser()
        self.chat_display.setOpenExternalLinks(True)
        chat_layout.addWidget(self.chat_display)

        input_layout = QHBoxLayout()
        self.user_input = SmoothTextEdit()
        self.user_input.setFixedHeight(80)
        input_layout.addWidget(self.user_input)
        
        self.send_button = QPushButton("Send")
        self.send_button.setFixedWidth(80)
        input_layout.addWidget(self.send_button)
        chat_layout.addLayout(input_layout)
        splitter.addWidget(chat_widget)

        # --- Right Pane: Actions ---
        actions_widget = QWidget()
        actions_layout = QVBoxLayout(actions_widget)
        actions_widget.setFixedWidth(250)

        model_group = QGroupBox("Model")
        model_layout = QVBoxLayout(model_group)
        self.model_combo = QComboBox()
        self.model_combo.addItems(self.models)
        model_layout.addWidget(self.model_combo)
        actions_layout.addWidget(model_group)

        gen_group = QGroupBox("Generate Content")
        gen_layout = QVBoxLayout(gen_group)
        self.gen_template_button = QPushButton("Template from Concept")
        self.gen_wildcard_button = QPushButton("Wildcard from Topic")
        gen_layout.addWidget(self.gen_template_button)
        gen_layout.addWidget(self.gen_wildcard_button)
        actions_layout.addWidget(gen_group)

        actions_layout.addStretch()
        splitter.addWidget(actions_widget)
        splitter.setSizes([550, 250])

    def _connect_signals(self):
        self.send_button.clicked.connect(self._on_send_clicked)
        self.gen_template_button.clicked.connect(self._on_gen_template)
        self.gen_wildcard_button.clicked.connect(self._on_gen_wildcard)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)

    @Slot(str)
    def _on_model_changed(self, new_model: str):
        self.current_model = new_model
        self.parent_app.report_model_change(new_model)

    @Slot(str)
    def set_model(self, model_name: str):
        """Slot to programmatically set the model from the parent app."""
        self.model_combo.blockSignals(True)
        self.model_combo.setCurrentText(model_name)
        self.model_combo.blockSignals(False)
        self.current_model = model_name

    @Slot()
    def _on_send_clicked(self):
        user_text = self.user_input.toPlainText().strip()
        if not user_text: return

        self._append_message("user", user_text)
        self.user_input.clear()
        self.chat_history.append({"role": "user", "content": user_text})
        self._start_chat_worker()

    def _start_chat_worker(self):
        model = self.model_combo.currentText()
        if not model:
            self._append_message("assistant", "Error: No model selected.")
            return

        self.send_button.setEnabled(False)
        self._append_message("assistant", "")

        self.current_worker_thread = QThread(self)
        worker = ChatWorker(self.processor, model, self.chat_history)
        worker.moveToThread(self.current_worker_thread)

        self.current_worker_thread.started.connect(worker.run)
        worker.chunk_ready.connect(self._on_chunk_ready)
        worker.finished.connect(self._on_chat_finished)
        worker.finished.connect(self.current_worker_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self.current_worker_thread.finished.connect(self.current_worker_thread.deleteLater)
        self.current_worker_thread.start()

    def _append_message(self, role: str, text: str):
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        formatted_text = text.replace('\n', '<br>')
        html = f"<p><b>{'You' if role == 'user' else 'AI'}:</b><br>{formatted_text}</p>"
        cursor.insertHtml(html)
        if role == "user": cursor.insertHtml("<hr>")
        self.chat_display.ensureCursorVisible()

    @Slot(str)
    def _on_chunk_ready(self, chunk: str):
        self.chat_display.moveCursor(QTextCursor.MoveOperation.End)
        self.chat_display.insertPlainText(chunk)
        self.chat_display.ensureCursorVisible()

    @Slot(dict)
    def _on_chat_finished(self, result: dict):
        self.send_button.setEnabled(True)
        if result['success']:
            full_response = result.get('response', '')
            self.chat_history.append({"role": "assistant", "content": full_response})
            self.chat_display.moveCursor(QTextCursor.MoveOperation.End)
            self.chat_display.insertHtml("<hr>")
        else:
            error_msg = result.get('error', 'Unknown error')
            self._append_message("error", f"<b>Error:</b> {error_msg}")

    @Slot()
    def _on_gen_template(self):
        """Handles the 'Generate Template from Concept' button click."""
        concept, ok = QInputDialog.getText(self, "Generate Template", "Enter a concept for the new template:")
        if ok and concept:
            self._start_content_gen_worker('template', concept)

    @Slot()
    def _on_gen_wildcard(self):
        """Handles the 'Generate Wildcard from Topic' button click."""
        topic, ok = QInputDialog.getText(self, "Generate Wildcard", "Enter a topic for the new wildcard:")
        if ok and topic:
            self._start_content_gen_worker('wildcard', topic)

    def _start_content_gen_worker(self, gen_type: str, topic: str):
        model = self.model_combo.currentText()
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model first.")
            return

        self.parent_app._start_loading_animation(f"Generating {gen_type} for '{topic}'...")

        self.content_gen_thread = QThread(self)
        worker = ContentGenWorker(self.processor, model, gen_type, topic)
        worker.moveToThread(self.content_gen_thread)

        self.content_gen_thread.started.connect(worker.run)
        worker.finished.connect(lambda result, w=worker: self._on_content_gen_finished(result, w))
        worker.finished.connect(self.content_gen_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self.content_gen_thread.finished.connect(self.content_gen_thread.deleteLater)
        self.content_gen_thread.start()

    @Slot(dict, ContentGenWorker)
    def _on_content_gen_finished(self, result: dict, worker: ContentGenWorker):
        self.parent_app._stop_loading_animation("Ready")
        if result['success']:
            content = result.get('content', '')
            suggested_filename = worker._suggest_filename()
            
            dialog = ReviewAndSaveDialog(self, self.processor, worker.gen_type, content, self._handle_ai_content_update, filename=suggested_filename)
            dialog.exec()
        else:
            error_msg = result.get('error', 'Unknown error')
            QMessageBox.critical(self, "Generation Error", f"Could not generate content:\n{error_msg}")

    def _handle_ai_content_update(self, content_type: str):
        """Callback for when the review dialog saves a new file."""
        # Pass the notification up to the main app to refresh its lists
        self.parent_app._handle_ai_content_update(content_type)