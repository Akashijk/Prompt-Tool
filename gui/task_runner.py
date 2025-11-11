"""A mixin for running background tasks with a loading dialog."""

import tkinter as tk
from tkinter import ttk
import threading
import queue
from typing import Callable, Optional

from . import custom_dialogs
from .common import LoadingAnimation

class _LoadingDialog(custom_dialogs._CustomDialog):
    """A simple, non-interactive loading dialog."""
    def __init__(self, parent, title: str, message: str):
        super().__init__(parent, title)
        self.protocol("WM_DELETE_WINDOW", lambda: None) # Prevent closing with 'X'
        self.bind("<Escape>", lambda e: None) # Prevent closing with escape

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.loading_animation = LoadingAnimation(main_frame, size=32)
        self.loading_animation.pack(pady=(0, 15))
        self.loading_animation.start()

        ttk.Label(main_frame, text=message, wraplength=300).pack()

        self._center_window()
        self.lift()

class TaskRunnerMixin:
    """A mixin for running background tasks with a loading dialog."""
    def __init__(self):
        self.task_queue = queue.Queue()
        self.task_after_id: Optional[str] = None
        self.loading_dialog: Optional[_LoadingDialog] = None

    def _get_active_ai_model(self) -> str:
        """
        Abstract method. Subclasses must implement this to return the
        currently selected AI model string for AI-powered tasks.
        """
        raise NotImplementedError("Subclasses must implement _get_active_ai_model")

    def run_task(self, task_callable: Callable, on_success: Callable, on_error: Callable, loading_dialog_title: str, loading_dialog_message: str, is_ai_task: bool = False):
        if self.loading_dialog and self.loading_dialog.winfo_exists():
            return # A task is already running

        self.loading_dialog = _LoadingDialog(self, loading_dialog_title, loading_dialog_message)

        def task_wrapper():
            try:
                if is_ai_task:
                    model = self._get_active_ai_model()
                    if not model or "model" in model.lower():
                        raise ValueError("Please select a valid AI model.")
                    result = task_callable(model)
                else:
                    result = task_callable()
                self.task_queue.put({'success': True, 'result': result})
            except Exception as e:
                self.task_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task_wrapper, daemon=True)
        thread.start()
        self._check_task_queue(on_success, on_error)

    def _check_task_queue(self, on_success: Callable, on_error: Callable):
        """Checks the queue for task results."""
        try:
            result = self.task_queue.get_nowait()
            if self.loading_dialog and self.loading_dialog.winfo_exists():
                self.loading_dialog.destroy()
                self.loading_dialog = None

            if result['success']:
                on_success(result['result'])
            else:
                on_error(result['error'])
        except queue.Empty:
            if self.winfo_exists():
                self.task_after_id = self.after(100, lambda: self._check_task_queue(on_success, on_error))