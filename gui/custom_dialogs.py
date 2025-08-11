"""
Custom, theme-aware dialog boxes for the application, replacing tkinter's
standard simpledialog and messagebox to ensure consistent styling.
"""

import tkinter as tk
from tkinter import ttk

class _CustomDialog(tk.Toplevel):
    """Base class for custom dialogs, handling window positioning and setup."""
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.result = None

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", self._on_cancel)

    def _center_window(self):
        """Centers the dialog over its parent window."""
        self.withdraw()
        self.update_idletasks()
        parent_x = self.master.winfo_x()
        parent_y = self.master.winfo_y()
        parent_w = self.master.winfo_width()
        parent_h = self.master.winfo_height()
        dialog_w = self.winfo_width()
        dialog_h = self.winfo_height()
        self.geometry(f"+{parent_x + (parent_w // 2) - (dialog_w // 2)}+{parent_y + (parent_h // 2) - (dialog_h // 2)}")
        self.deiconify()

    def _on_ok(self, event=None):
        # To be implemented by subclasses
        self.destroy()

    def _on_cancel(self, event=None):
        self.result = None
        self.destroy()

class _AskStringDialog(_CustomDialog):
    """A custom dialog to get a string input from the user."""
    def __init__(self, parent, title: str, prompt: str, initialvalue: str = ""):
        super().__init__(parent, title)

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text=prompt, wraplength=350).pack(pady=(0, 10), anchor='w')

        self.entry = ttk.Entry(main_frame, width=50)
        self.entry.pack(pady=(0, 20), fill=tk.X, expand=True)
        if initialvalue:
            self.entry.insert(0, initialvalue)
        self.entry.focus_set()
        self.entry.selection_range(0, tk.END)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5, 0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self._center_window()
        self.wait_window(self)

    def _on_ok(self, event=None):
        self.result = self.entry.get()
        self.destroy()

class _MessageBox(_CustomDialog):
    """A custom, theme-aware message box."""
    def __init__(self, parent, title: str, message: str, yes_no: bool = False):
        super().__init__(parent, title)
        self.result = False # Default for askyesno

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text=message, wraplength=350).pack(pady=(0, 20), anchor='w')

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        if yes_no:
            yes_button = ttk.Button(button_frame, text="Yes", command=self._on_ok, style="Accent.TButton")
            yes_button.pack(side=tk.RIGHT, padx=(5, 0))
            no_button = ttk.Button(button_frame, text="No", command=self._on_cancel)
            no_button.pack(side=tk.RIGHT)
            self.bind("<Return>", self._on_ok)
        else:
            ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok, style="Accent.TButton")
            ok_button.pack(side=tk.RIGHT)
            self.bind("<Return>", self._on_ok)

        self._center_window()
        self.wait_window(self)

    def _on_ok(self, event=None):
        self.result = True
        self.destroy()

    def _on_cancel(self, event=None):
        self.result = False
        self.destroy()

def ask_string(parent, title, prompt, **kwargs) -> str | None:
    dialog = _AskStringDialog(parent, title, prompt, **kwargs)
    return dialog.result

def ask_yes_no(parent, title, message) -> bool:
    dialog = _MessageBox(parent, title, message, yes_no=True)
    return dialog.result

def show_info(parent, title, message):
    _MessageBox(parent, title, message)

def show_warning(parent, title, message):
    # In a real app, you might add a warning icon here
    _MessageBox(parent, title, message)

def show_error(parent, title, message):
    # In a real app, you might add an error icon here
    _MessageBox(parent, title, message)