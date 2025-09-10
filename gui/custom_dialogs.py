"""
Custom, theme-aware dialog boxes for the application, replacing tkinter's
standard simpledialog and messagebox to ensure consistent styling.
"""

import tkinter as tk
from tkinter import ttk
import sys
import re
import json
import copy
import difflib
import re
import os
from typing import TYPE_CHECKING, Callable, Tuple, Any, Optional, List, Dict
from .common import Tooltip, TextContextMenu

if TYPE_CHECKING:
    from core.prompt_processor import PromptProcessor
    from .gui_app import GUIApp

def is_valid_filename_component(name: str) -> Tuple[bool, str]:
    """
    Validates a string to ensure it's a safe component for a filename.
    Returns (is_valid, error_message).
    """
    if not name:
        return False, "Filename cannot be empty."
    if name in {".", ".."}:
        return False, "Filename cannot be '.' or '..'."
    
    # Disallow characters that are invalid in Windows/Linux/macOS filenames
    invalid_chars = r'[\\/:*?"<>|]'
    if re.search(invalid_chars, name):
        return False, f"Filename cannot contain any of the following characters: \\ / : * ? \" < > |"
    
    return True, ""

class _CustomDialog(tk.Toplevel):
    """Base class for custom dialogs, handling window positioning and setup."""
    def __init__(self, parent, title: str, modal: bool = True):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.result = None
        if modal:
            self.grab_set()

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

class _EnrichChoicesDialog(_CustomDialog):
    """A dialog to select options for AI-powered choice enrichment."""
    def __init__(self, parent):
        super().__init__(parent, "Enrich Choices with AI")

        self.improve_descriptions_var = tk.BooleanVar(value=True)
        self.add_metadata_var = tk.BooleanVar(value=True)

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Select how you want the AI to enrich your choices:", wraplength=350).pack(pady=(0, 15), anchor='w')

        options_frame = ttk.Frame(main_frame)
        options_frame.pack(fill=tk.X)

        cb1 = ttk.Checkbutton(options_frame, text="Improve Descriptions", variable=self.improve_descriptions_var, onvalue=True, offvalue=False)
        cb1.pack(anchor='w', pady=2)
        Tooltip(cb1, "Rewrite choice values to be more descriptive and evocative for image generation.")

        cb2 = ttk.Checkbutton(options_frame, text="Add/Update Metadata", variable=self.add_metadata_var, onvalue=True, offvalue=False)
        cb2.pack(anchor='w', pady=2)
        Tooltip(cb2, "Add or update metadata like tags, weights, requirements, and includes.")

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        ok_button = ttk.Button(button_frame, text="Enrich", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5, 0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self._center_window()
        self.wait_window(self)

    def _on_ok(self, event=None):
        self.result = (self.improve_descriptions_var.get(), self.add_metadata_var.get())
        self.destroy()

class _AskStringDialog(_CustomDialog):
    """A custom dialog to get a string input from the user."""
    def __init__(self, parent, title: str, prompt: str, initialvalue: str = "", validator: Optional[Callable[[str], Tuple[bool, str]]] = None):
        super().__init__(parent, title)
        self.validator = validator

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
        value = self.entry.get().strip()
        if self.validator:
            is_valid, error_message = self.validator(value)
            if not is_valid:
                show_warning(self, "Invalid Input", error_message)
                return
        self.result = value
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

class _YesNoCancelBox(_CustomDialog):
    """A custom, theme-aware message box that returns True, False, or None."""
    def __init__(self, parent, title: str, message: str):
        super().__init__(parent, title)
        self.result = None # Default for cancel/close

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text=message, wraplength=350).pack(pady=(0, 20), anchor='w')

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        yes_button = ttk.Button(button_frame, text="Yes", command=self._on_yes, style="Accent.TButton")
        yes_button.pack(side=tk.RIGHT, padx=(5, 0))
        no_button = ttk.Button(button_frame, text="No", command=self._on_no)
        no_button.pack(side=tk.RIGHT, padx=(5,0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self._center_window()
        self.wait_window(self)

    def _on_yes(self): self.result = True; self.destroy()
    def _on_no(self): self.result = False; self.destroy()

class _CopyableErrorDialog(_CustomDialog):
    """A message box with selectable text for copying."""
    def __init__(self, parent, title: str, message: str):
        super().__init__(parent, title)

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Use a read-only Text widget to allow selection
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(pady=(0, 20), fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        text_widget = tk.Text(text_frame, wrap=tk.WORD, height=10, exportselection=False, yscrollcommand=scrollbar.set)
        scrollbar.config(command=text_widget.yview)
        
        text_widget.insert("1.0", message)
        text_widget.config(state=tk.DISABLED) # This still allows selection
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT)
        self.bind("<Return>", self._on_ok)

        self.geometry("600x300") # Give it a decent default size
        self._center_window()
        self.wait_window(self)

def ask_string(parent, title, prompt, **kwargs) -> str | None:
    dialog = _AskStringDialog(parent, title, prompt, **kwargs)
    return dialog.result

def ask_yes_no(parent, title, message) -> bool:
    dialog = _MessageBox(parent, title, message, yes_no=True)
    return dialog.result

def ask_yes_no_cancel(parent, title, message) -> Optional[bool]:
    dialog = _YesNoCancelBox(parent, title, message)
    return dialog.result

def show_info(parent, title, message):
    _MessageBox(parent, title, message)

def show_warning(parent, title, message):
    # In a real app, you might add a warning icon here
    _MessageBox(parent, title, message)

def show_error(parent, title, message):
    # In a real app, you might add an error icon here
    _CopyableErrorDialog(parent, title, message)

class _CreateSystemPromptDialog(_CustomDialog):
    """A dialog to get the type and name for a new system prompt."""
    def __init__(self, parent):
        super().__init__(parent, "Create New System Prompt")
        self.prompt_type_var = tk.StringVar(value="variation")
        self.filename_var = tk.StringVar()

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Select the type of prompt to create:").pack(anchor='w', pady=(0, 10))
        
        type_frame = ttk.Frame(main_frame)
        type_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Radiobutton(type_frame, text="Variation (.json)", variable=self.prompt_type_var, value="variation").pack(anchor='w')
        ttk.Radiobutton(type_frame, text="Enhancement (.txt)", variable=self.prompt_type_var, value="enhancement").pack(anchor='w')
        ttk.Radiobutton(type_frame, text="Negative Prompt (.txt)", variable=self.prompt_type_var, value="negative_prompt").pack(anchor='w')

        ttk.Label(main_frame, text="Enter filename (without extension):").pack(anchor='w')
        self.entry = ttk.Entry(main_frame, textvariable=self.filename_var, width=40)
        self.entry.pack(fill=tk.X, pady=(0, 20))
        self.entry.focus_set()

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        ok_button = ttk.Button(button_frame, text="Create", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5, 0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self._center_window()
        self.wait_window(self)

    def _on_ok(self, event=None):
        filename = self.filename_var.get().strip()
        is_valid, error_message = is_valid_filename_component(filename)
        if not is_valid:
            show_warning(self, "Invalid Input", error_message)
            return
            
        self.result = {
            "type": self.prompt_type_var.get(),
            "filename": filename
        }
        self.destroy()

class _PerModelNegativePromptDialog(_CustomDialog):
    """A dialog to set negative prompt overrides for selected models."""
    def __init__(self, parent, processor: 'PromptProcessor', selected_models: List[str], overrides: Dict[str, str]):
        super().__init__(parent, "Per-Model Negative Prompt Overrides")
        self.processor = processor
        self.entries: Dict[str, tk.StringVar] = {}
        self.combo_vars: Dict[str, tk.StringVar] = {}
        self.text_widgets: Dict[str, tk.Entry] = {}

        # Get presets once
        self.negative_prompts = self.processor.get_available_negative_prompts()
        self.neg_prompt_names = ["(Use Default)"] + [p['name'] for p in self.negative_prompts]

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Select a preset or enter a custom negative prompt for specific models. Leave blank to use the main negative prompt.", wraplength=480).pack(pady=(0, 10))

        from .common import ScrollableFrame # Local import
        scroll_frame = ScrollableFrame(main_frame)
        scroll_frame.pack(fill=tk.BOTH, expand=True)
        container = scroll_frame.scrollable_frame

        for model_name in selected_models:
            row_frame = ttk.LabelFrame(container, text=model_name, padding=5)
            row_frame.pack(fill=tk.X, pady=3, padx=3)
            row_frame.columnconfigure(0, weight=1)

            # Preset Combobox
            combo_var = tk.StringVar()
            combo = ttk.Combobox(row_frame, textvariable=combo_var, values=self.neg_prompt_names, state="readonly")
            combo.pack(fill=tk.X, pady=(0, 5))
            combo.bind("<<ComboboxSelected>>", lambda event, m=model_name: self._on_preset_select(event, m))
            self.combo_vars[model_name] = combo_var
            
            # Text Entry
            string_var = tk.StringVar(value=overrides.get(model_name, ""))
            entry = ttk.Entry(row_frame, textvariable=string_var)
            entry.pack(fill=tk.X)
            entry.bind("<KeyRelease>", lambda event, m=model_name: self._on_text_change(event, m))
            self.entries[model_name] = string_var
            self.text_widgets[model_name] = entry

            # Set initial state
            self._set_initial_preset(model_name, overrides.get(model_name, ""))

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5, 0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self.geometry("500x400")
        self._center_window()
        self.wait_window(self)

    def _on_preset_select(self, event, model_name: str):
        combo_var = self.combo_vars[model_name]
        entry_var = self.entries[model_name]
        selected_name = combo_var.get()

        if selected_name == "(Use Default)":
            entry_var.set("")
            return

        selected_prompt_obj = next((p for p in self.negative_prompts if p['name'] == selected_name), None)
        if selected_prompt_obj:
            entry_var.set(selected_prompt_obj['prompt'])

    def _on_text_change(self, event, model_name: str):
        combo_var = self.combo_vars[model_name]
        entry_var = self.entries[model_name]
        current_text = entry_var.get().strip()

        if not current_text:
            combo_var.set("(Use Default)")
            return

        matching_preset = next((p['name'] for p in self.negative_prompts if p['prompt'].strip() == current_text), None)
        
        if matching_preset:
            if combo_var.get() != matching_preset:
                combo_var.set(matching_preset)
        else:
            # It's a custom value, so clear the combobox selection
            combo_var.set("")

    def _set_initial_preset(self, model_name: str, initial_text: str):
        combo_var = self.combo_vars[model_name]
        stripped_initial = initial_text.strip()
        if not stripped_initial:
            combo_var.set("(Use Default)")
            return

        matching_preset = next((p['name'] for p in self.negative_prompts if p['prompt'].strip() == stripped_initial), None)
        if matching_preset:
            combo_var.set(matching_preset)
        else:
            combo_var.set("")

    def _on_ok(self, event=None):
        self.result = {name: var.get().strip() for name, var in self.entries.items() if var.get().strip()}
        self.destroy()

class _DiffConfirmationDialog(_CustomDialog):
    """A dialog to show a side-by-side diff of text changes and ask for confirmation."""
    def __init__(self, parent, title: str, original_text: str, new_text: str):
        super().__init__(parent, title)
        self.result = False # Default to not applying changes

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="The AI has proposed the following changes. Review the diff and click 'Apply' to accept.", wraplength=780).pack(anchor='w', pady=(0, 10))

        # --- Diff View Pane ---
        diff_frame = ttk.LabelFrame(main_frame, text="Proposed Enhancement (Additions Highlighted in Green)", padding=5)
        diff_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        font_to_use = parent.fixed_font if hasattr(parent, 'fixed_font') else parent.parent_app.fixed_font
        diff_text_widget = tk.Text(diff_frame, wrap=tk.WORD, font=font_to_use, state=tk.DISABLED)
        diff_text_widget.pack(fill=tk.BOTH, expand=True)

        # --- Buttons ---
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        apply_button = ttk.Button(button_frame, text="Apply Changes", command=self._on_ok, style="Accent.TButton")
        apply_button.pack(side=tk.RIGHT, padx=(5, 0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        # --- Calculate and display diff ---
        diff_text_widget.config(state=tk.NORMAL)
        diff_text_widget.tag_configure("addition", foreground="green", font=(font_to_use.cget("family"), font_to_use.cget("size"), "bold"))
        
        # Tokenize by splitting on commas and whitespace, but keeping them for reconstruction.
        # This provides a much more granular and accurate diff than a character-by-character comparison.
        original_tokens = re.split(r'([,\s]+)', original_text)
        new_tokens = re.split(r'([,\s]+)', new_text)

        sm = difflib.SequenceMatcher(None, original_tokens, new_tokens, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            # Join the tokens for the current segment to insert them.
            segment_text = "".join(new_tokens[j1:j2])
            if tag == 'equal':
                diff_text_widget.insert(tk.END, segment_text)
            elif tag == 'insert' or tag == 'replace':
                diff_text_widget.insert(tk.END, segment_text, ("addition",))
        
        diff_text_widget.config(state=tk.DISABLED)

        self.geometry("900x600")
        self._center_window()
        self.wait_window(self)

    def _on_ok(self, event=None):
        self.result = True
        self.destroy()

class MassEditContextMenu(TextContextMenu):
    """A context menu for the mass edit dialog with a 'send to' function."""
    def __init__(self, widget, send_callback: Callable, insert_wildcard_callback: Callable):
        super().__init__(widget, insert_wildcard_callback=insert_wildcard_callback)
        self.send_callback = send_callback
        self.menu.add_separator()
        self.menu.add_command(label="Send to Wildcard...", command=self.send_callback, state=tk.DISABLED)

    def _configure_menu_items(self, event):
        super()._configure_menu_items(event)
        try:
            self.widget.selection_get()
            self.menu.entryconfig("Send to Wildcard...", state=tk.NORMAL)
        except tk.TclError:
            self.menu.entryconfig("Send to Wildcard...", state=tk.DISABLED)

class MassEditDialog(_CustomDialog):
    """A dialog for mass editing choice values in a simple text box."""
    def __init__(self, parent, initial_text: str, processor: 'PromptProcessor'):
        super().__init__(parent, "Mass Edit Choices")
        self.processor = processor
        self.parent_app = parent.parent_app

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Edit choice values below (one per line). Metadata will be preserved for modified lines.", wraplength=500).pack(pady=(0, 10), anchor='w')

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        self.text_widget = tk.Text(text_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, undo=True)
        scrollbar.config(command=self.text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text_widget.insert("1.0", initial_text)
        self.text_widget.focus_set()

        # Add the context menu
        MassEditContextMenu(
            self.text_widget, 
            send_callback=self._send_to_wildcard,
            insert_wildcard_callback=self._insert_wildcard_into_text
        )

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(button_frame, text="OK", command=self._on_ok, style="Accent.TButton").pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)
        self._center_window()
        self.wait_window(self)

    def _on_ok(self, event=None):
        self.result = self.text_widget.get("1.0", "end-1c")
        self.destroy()

    def _insert_wildcard_into_text(self):
        """Callback to insert a wildcard into the text widget."""
        selector_dialog = WildcardSelectorDialog(self, self.processor)
        if selector_dialog.result:
            wildcard_name = selector_dialog.result[0] # Use the first selected
            self.text_widget.insert(tk.INSERT, f"__{wildcard_name}__")
            self.text_widget.focus_set()

    def _send_to_wildcard(self):
        """Sends the selected text to another wildcard file."""
        try:
            selected_text = self.text_widget.get("sel.first", "sel.last").strip()
        except tk.TclError:
            return # No selection

        if not selected_text:
            return

        # Open wildcard selector
        selector_dialog = WildcardSelectorDialog(self, self.processor)
        if not selector_dialog.result:
            return

        target_wildcard_name = selector_dialog.result[0] # Just use the first one if multiple are selected
        target_filename = f"{target_wildcard_name}.json"

        try:
            # Load the target file's content, preferring the cache but falling back to disk.
            wildcard_data = self.processor.template_engine.wildcards.get(target_wildcard_name)
            if not wildcard_data:
                raw_content = self.processor.load_wildcard_content(target_filename)
                wildcard_data = json.loads(raw_content)
            else:
                wildcard_data = copy.deepcopy(wildcard_data) # Work on a copy

            if 'choices' not in wildcard_data:
                wildcard_data['choices'] = []
            
            existing_values = {str(c.get('value') if isinstance(c, dict) else c) for c in wildcard_data['choices']}
            if selected_text not in existing_values:
                wildcard_data['choices'].append(selected_text)
            else:
                show_info(self, "Duplicate", f"The value '{selected_text}' already exists in '{target_filename}'.")
                return

            new_content = json.dumps(wildcard_data, indent=2)
            self.processor.save_wildcard_content(target_filename, new_content)

            if ask_yes_no(self, "Move Text?", f"Successfully added '{selected_text}' to '{target_filename}'.\n\nDo you want to remove the selected text from this editor?"):
                self.text_widget.delete("sel.first", "sel.last")
            
            show_info(self, "Success", f"Sent '{selected_text}' to '{target_filename}'.")

        except Exception as e:
            show_error(self, "Error", f"Failed to send text to wildcard:\n{e}")

class AddRequirementDialog(_CustomDialog):
    """A dialog to help build a 'requires' clause."""
    def __init__(self, parent, processor: 'PromptProcessor'):
        super().__init__(parent, "Add Requirement")
        self.processor = processor

        # --- Main Frames ---
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Type Selection ---
        type_frame = ttk.LabelFrame(main_frame, text="Requirement Type", padding=10)
        type_frame.pack(fill=tk.X, pady=(0, 10))
        self.req_type_var = tk.StringVar(value="value")
        ttk.Radiobutton(type_frame, text="Wildcard Value", variable=self.req_type_var, value="value", command=self._update_ui).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(type_frame, text="Tag Presence", variable=self.req_type_var, value="tag", command=self._update_ui).pack(side=tk.LEFT, padx=5)

        # --- Dynamic Frames ---
        self.value_frame = ttk.LabelFrame(main_frame, text="Value Requirement", padding=10)
        self.tag_frame = ttk.LabelFrame(main_frame, text="Tag Requirement", padding=10)

        # --- Widgets for Value Frame ---
        self.wildcard_var = tk.StringVar()
        ttk.Label(self.value_frame, text="Wildcard Name:").grid(row=0, column=0, sticky='w', pady=2)
        self.wildcard_combo = ttk.Combobox(self.value_frame, textvariable=self.wildcard_var, state="readonly", width=30)
        self.wildcard_combo['values'] = sorted(self.processor.get_wildcard_names())
        self.wildcard_combo.grid(row=0, column=1, sticky='ew', pady=2)
        self.wildcard_combo.bind("<<ComboboxSelected>>", self._on_wildcard_select)

        ttk.Label(self.value_frame, text="Required Value(s):").grid(row=1, column=0, sticky='nw', pady=2)
        self.value_listbox = tk.Listbox(self.value_frame, selectmode=tk.EXTENDED, height=6)
        self.value_listbox.grid(row=1, column=1, sticky='nsew')
        self.value_frame.rowconfigure(1, weight=1)
        self.value_frame.columnconfigure(1, weight=1)

        # --- Widgets for Tag Frame ---
        self.tag_frame.columnconfigure(0, weight=1) # Let columns share space
        self.tag_frame.columnconfigure(1, weight=1)

        self.tag_match_type_var = tk.StringVar(value="any")
        ttk.Label(self.tag_frame, text="Match Type:").grid(row=0, column=0, columnspan=2, sticky='w')
        ttk.Radiobutton(self.tag_frame, text="Any of these tags", variable=self.tag_match_type_var, value="any").grid(row=1, column=0, sticky='w', padx=10)
        ttk.Radiobutton(self.tag_frame, text="All of these tags", variable=self.tag_match_type_var, value="all").grid(row=1, column=1, sticky='w', padx=10)
        
        ttk.Label(self.tag_frame, text="Required Tags (comma-separated):").grid(row=2, column=0, columnspan=2, sticky='w', pady=(10, 2))
        self.tags_entry = ttk.Entry(self.tag_frame)
        self.tags_entry.grid(row=3, column=0, columnspan=2, sticky='ew')

        # --- OK/Cancel Buttons ---
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10,0))
        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5,0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self._update_ui() # Set initial visibility
        self._center_window()
        self.wait_window(self)

    def _update_ui(self):
        """Shows the relevant frame based on the selected requirement type."""
        req_type = self.req_type_var.get()
        if req_type == "value":
            self.tag_frame.pack_forget()
            self.value_frame.pack(fill=tk.BOTH, expand=True)
        else: # tag
            self.value_frame.pack_forget()
            self.tag_frame.pack(fill=tk.BOTH, expand=True)

    def _on_wildcard_select(self, event=None):
        wildcard_name = self.wildcard_var.get()
        if wildcard_name:
            self.value_listbox.delete(0, tk.END)
            options = self.processor.get_wildcard_options(wildcard_name)
            for option in options:
                self.value_listbox.insert(tk.END, option)
    
    def _on_ok(self, event=None):
        req_type = self.req_type_var.get()
        if req_type == "value":
            wildcard_name = self.wildcard_var.get()
            selected_indices = self.value_listbox.curselection()
            selected_values = [self.value_listbox.get(i) for i in selected_indices]
            if not wildcard_name or not selected_values:
                self.destroy()
                return
            
            # If only one value is selected, it's a simple key:value match.
            # If multiple, it's a key:[val1, val2] "any of" match.
            if len(selected_values) == 1:
                self.result = {wildcard_name: selected_values[0]}
            else:
                self.result = {wildcard_name: selected_values}
        else: # tag
            match_type = self.tag_match_type_var.get()
            tags = [t.strip() for t in self.tags_entry.get().split(',') if t.strip()]
            if not tags:
                self.destroy()
                return
            self.result = {"tags": {match_type: tags}}

        self.destroy()

class EditChoiceDialog(_CustomDialog):
    """A dialog for editing a single choice from a wildcard file."""
    def __init__(self, parent, title: str, initial_values: Tuple[str, str, str, str, str], processor: 'PromptProcessor'):
        super().__init__(parent, title)
        self.parent_app = parent.parent_app

        self.value_var = tk.StringVar(value=initial_values[0])
        self.weight_var = tk.StringVar(value=initial_values[1])
        self.tags_var = tk.StringVar(value=initial_values[2])
        self.requires_var = tk.StringVar(value=initial_values[3])
        self.includes_var = tk.StringVar(value=initial_values[4])
        self.processor = processor

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Value:").grid(row=0, column=0, sticky='w', pady=2)
        value_entry = ttk.Entry(main_frame, textvariable=self.value_var, width=50)
        value_entry.grid(row=0, column=1, sticky='ew', pady=2)
        
        ttk.Label(main_frame, text="Weight:").grid(row=1, column=0, sticky='w', pady=2)
        weight_entry = ttk.Entry(main_frame, textvariable=self.weight_var)
        weight_entry.grid(row=1, column=1, sticky='ew', pady=2)

        ttk.Label(main_frame, text="Tags (comma-separated):").grid(row=2, column=0, sticky='w', pady=2)
        ttk.Entry(main_frame, textvariable=self.tags_var).grid(row=2, column=1, sticky='ew', pady=2)

        ttk.Label(main_frame, text="Requires (key:val, ...):").grid(row=3, column=0, sticky='w', pady=2)
        
        requires_frame = ttk.Frame(main_frame)
        requires_frame.grid(row=3, column=1, sticky='ew', pady=2)
        requires_frame.columnconfigure(0, weight=1)
        requires_entry = ttk.Entry(requires_frame, textvariable=self.requires_var)
        requires_entry.grid(row=0, column=0, sticky='ew')
        ttk.Button(requires_frame, text="Add...", command=self._add_requirement).grid(row=0, column=1, padx=(5, 0))

        ttk.Label(main_frame, text="Includes (list or template string):").grid(row=4, column=0, sticky='w', pady=2)
        
        includes_frame = ttk.Frame(main_frame)
        includes_frame.grid(row=4, column=1, sticky='ew', pady=2)
        includes_frame.columnconfigure(0, weight=1)
        includes_entry = ttk.Entry(includes_frame, textvariable=self.includes_var)
        includes_entry.grid(row=0, column=0, sticky='ew')
        ttk.Button(includes_frame, text="Add...", command=self._add_include).grid(row=0, column=1, padx=(5, 0))
        
        main_frame.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=2, pady=(10,0), sticky='e')
        
        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side=tk.RIGHT, padx=(5,0))
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self._center_window()

        # Add context menus with the insert wildcard functionality
        TextContextMenu(value_entry, insert_wildcard_callback=lambda: self._insert_wildcard_into_entry(value_entry))
        TextContextMenu(includes_entry, insert_wildcard_callback=lambda: self._insert_wildcard_into_entry(includes_entry))
        self.wait_window(self)

    def _on_ok(self, event=None):
        self.result = (
            self.value_var.get(),
            self.weight_var.get(),
            self.tags_var.get(),
            self.requires_var.get(),
            self.includes_var.get()
        )
        self.destroy()

    def _insert_wildcard_into_entry(self, entry_widget: ttk.Entry):
        """Callback to insert a wildcard into a specific Entry widget."""
        selector_dialog = WildcardSelectorDialog(self, self.processor)
        if selector_dialog.result:
            wildcard_name = selector_dialog.result[0] # Use the first selected
            entry_widget.insert(tk.INSERT, f"__{wildcard_name}__")
            entry_widget.focus_set()
    
    def _add_requirement(self):
        dialog = AddRequirementDialog(self, self.processor)
        if not dialog.result:
            return

        try:
            current_req_str = self.requires_var.get()
            current_reqs = json.loads(current_req_str) if current_req_str else {}
            if not isinstance(current_reqs, dict): current_reqs = {}
        except json.JSONDecodeError:
            current_reqs = {}

        new_key, new_value = list(dialog.result.items())[0]

        if new_key == 'tags':
            if 'tags' not in current_reqs or not isinstance(current_reqs.get('tags'), dict):
                current_reqs['tags'] = new_value
            else:
                existing_tags_rule = current_reqs['tags']
                new_tags_rule = new_value
                for condition, tags_to_add in new_tags_rule.items():
                    if condition not in existing_tags_rule:
                        existing_tags_rule[condition] = tags_to_add
                    else:
                        combined = set(existing_tags_rule[condition]) | set(tags_to_add)
                        existing_tags_rule[condition] = sorted(list(combined))
        else:
            if new_key not in current_reqs:
                current_reqs[new_key] = new_value
            else:
                existing_value = current_reqs[new_key]
                all_values = set()
                if isinstance(existing_value, list): all_values.update(existing_value)
                else: all_values.add(existing_value)
                if isinstance(new_value, list): all_values.update(new_value)
                else: all_values.add(new_value)
                merged_list = sorted(list(all_values))
                current_reqs[new_key] = merged_list[0] if len(merged_list) == 1 else merged_list

        new_req_str = json.dumps(current_reqs, separators=(',', ':')) if current_reqs else ""
        self.requires_var.set(new_req_str)

    def _add_include(self):
        """Opens a dialog to add wildcards to the includes field."""
        dialog = WildcardSelectorDialog(self, self.processor)
        if not dialog.result:
            return

        current_text = self.includes_var.get().strip()
        to_append = " ".join([f"[{w}]" for w in dialog.result])
        new_text = f"{current_text} {to_append}".strip()
        self.includes_var.set(new_text)

class WildcardSelectorDialog(_CustomDialog):
    """A dialog for selecting wildcards to include."""
    def __init__(self, parent, processor: 'PromptProcessor'):
        super().__init__(parent, "Select Wildcards to Include")
        
        # Get the main app instance for callbacks.
        # This relies on the parent widget having a 'parent_app' attribute,
        # which is a convention used throughout the dialogs in this app.
        self.parent_app: 'GUIApp' = parent.parent_app
        self.processor = processor
        
        # Create main frame
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add search box
        search_frame = ttk.Frame(main_frame)
        search_frame.pack(fill=tk.X, pady=(0, 5))
        search_frame.columnconfigure(1, weight=1)

        ttk.Label(search_frame, text="Search:").grid(row=0, column=0, sticky='w')
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._filter_wildcards)
        ttk.Entry(search_frame, textvariable=self.search_var).grid(row=0, column=1, sticky='ew', padx=(5, 0))
        
        # Create listbox with scrollbar inside a container frame
        list_container = ttk.Frame(main_frame)
        list_container.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_container, selectmode=tk.MULTIPLE, height=15)
        scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL, 
                                command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Populate with wildcards
        self.all_wildcards = sorted(processor.get_wildcard_names())
        for wildcard in self.all_wildcards:
            self.listbox.insert(tk.END, wildcard)
        
        # --- Tooltip for preview ---
        self.tooltip = Tooltip(self.listbox)
        self.tooltip_after_id = None
        self.last_hovered_index = -1
        self.listbox.bind("<Motion>", self._schedule_tooltip)
        self.listbox.bind("<Leave>", self._hide_tooltip)

        # --- Context Menu for full review ---
        self.context_menu = tk.Menu(self.listbox, tearoff=0)
        self.context_menu.add_command(label="Open in Wildcard Manager", command=self._open_in_manager)
        right_click_event = "<Button-3>" if sys.platform != "darwin" else "<Button-2>"
        self.listbox.bind(right_click_event, self._show_context_menu)

        # Add buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(button_frame, text="OK", 
                  command=self._on_ok, 
                  style="Accent.TButton").pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Cancel",
                  command=self._on_cancel).pack(side=tk.RIGHT)
        
        # Center the dialog
        self.geometry("300x400")
        self._center_window()

        # Make dialog modal
        self.wait_window(self)
    
    def _filter_wildcards(self, *args):
        """Filter the wildcard list based on search text."""
        search_text = self.search_var.get().lower()
        self.listbox.delete(0, tk.END)
        
        for wildcard in self.all_wildcards:
            if search_text in wildcard.lower():
                self.listbox.insert(tk.END, wildcard)
    
    def _on_ok(self):
        """Handle OK button click."""
        selection = self.listbox.curselection()
        if selection:
            self.result = [self.listbox.get(i) for i in selection]
        self.destroy()

    def _schedule_tooltip(self, event):
        """Schedules a tooltip to appear after a short delay."""
        if self.tooltip_after_id:
            self.after_cancel(self.tooltip_after_id)

        index = self.listbox.nearest(event.y)
        if index != self.last_hovered_index:
            self.tooltip.hide() # Hide immediately if moving to a new item
        self.last_hovered_index = index
        self.tooltip_after_id = self.after(500, lambda: self._display_tooltip(index, event))

    def _display_tooltip(self, index, event):
        """Fetches content and displays the tooltip. This is called after a delay."""
        try:
            wildcard_name = self.listbox.get(index)
            options = self.processor.get_wildcard_options(wildcard_name)

            if not options:
                self.tooltip.text = f"{wildcard_name} (empty)"
            else:
                preview_count = 10
                preview_options = options[:preview_count]
                
                tooltip_text = f"'{wildcard_name}' choices:\n" + "\n".join([f"- {opt}" for opt in preview_options])
                if len(options) > preview_count:
                    tooltip_text += f"\n...and {len(options) - preview_count} more"
                
                self.tooltip.text = tooltip_text
            
            self.tooltip.show(event)
        except tk.TclError:
            # This can happen if the mouse is over an empty part of the listbox
            self.tooltip.hide()

    def _hide_tooltip(self, event=None):
        """Hides the wildcard preview tooltip."""
        self.last_hovered_index = -1
        if self.tooltip_after_id:
            self.after_cancel(self.tooltip_after_id)
            self.tooltip_after_id = None
        self.tooltip.hide()

    def _show_context_menu(self, event):
        """Shows the context menu for the listbox."""
        index = self.listbox.nearest(event.y)
        if index != -1:
            if not self.listbox.selection_includes(index):
                self.listbox.selection_clear(0, tk.END)
                self.listbox.selection_set(index)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _open_in_manager(self):
        """Opens the selected wildcard in the Wildcard Manager."""
        selection = self.listbox.curselection()
        if not selection:
            return
        
        wildcard_name = self.listbox.get(selection[0])
        self.parent_app._open_wildcard_manager(initial_file=f"{wildcard_name}.json")