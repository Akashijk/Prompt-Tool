"""A dialog for creating LoRA permutations for an image generation."""

import tkinter as tk
import uuid
from tkinter import ttk
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from .common import SmartWindowMixin, VerticalSpinbox
from . import custom_dialogs
from .common import ScrollableFrame

if TYPE_CHECKING:
    from core.prompt_processor import PromptProcessor

class LoraPermutationDialog(custom_dialogs._CustomDialog, SmartWindowMixin):
    """A dialog for creating LoRA permutations for an image generation."""
    def __init__(self, parent, processor: 'PromptProcessor', base_params: Dict[str, Any]):
        super().__init__(parent, "Generate LoRA Permutations")
        self.processor = processor
        self.base_params = base_params
        self.all_loras: Dict[str, Any] = {}
        
        # NEW DATA STRUCTURE: A list of permutation objects.
        # Each object contains its UI widgets and data.
        self.permutations: List[Dict[str, Any]] = []
        self.current_permutation_index = -1

        self._create_widgets()
        self._load_loras()

        # Add initial permutation based on the original image's LoRAs
        initial_loras = self.base_params.get('loras', [])
        self._add_permutation(initial_loras)

        # If there's at least one permutation, select the first one.
        if self.permutations:
            self.perm_listbox.selection_set(0)
            self._on_permutation_select()

        self.smart_geometry(min_width=800, min_height=500)
        self.wait_window(self)

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Info ---
        model_name = self.base_params.get('model', {}).get('name', 'Unknown')
        seed = self.base_params.get('seed', 'Unknown')
        info_text = f"Generating permutations for Model: {model_name} | Seed: {seed}"
        ttk.Label(main_frame, text=info_text, wraplength=480).pack(anchor='w', pady=(0, 10))

        # --- Main Paned Window ---
        pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)

        # --- Left Pane: Permutation List ---
        left_pane = ttk.LabelFrame(pane, text="Permutations", padding=10)
        pane.add(left_pane, weight=1)

        self.perm_listbox = tk.Listbox(left_pane, exportselection=False)
        self.perm_listbox.pack(fill=tk.BOTH, expand=True)
        self.perm_listbox.bind("<<ListboxSelect>>", self._on_permutation_select)

        perm_actions = ttk.Frame(left_pane)
        perm_actions.pack(fill=tk.X, pady=(5,0))
        ttk.Button(perm_actions, text="Add", command=lambda: self._add_permutation()).pack(side=tk.LEFT)
        ttk.Button(perm_actions, text="Duplicate", command=self._duplicate_permutation).pack(side=tk.LEFT, padx=5)
        ttk.Button(perm_actions, text="Remove", command=self._remove_permutation).pack(side=tk.LEFT)

        # --- Right Pane: LoRA Configuration for selected permutation ---
        right_pane = ttk.LabelFrame(pane, text="LoRAs for Selected Permutation", padding=10)
        pane.add(right_pane, weight=2)

        # Header for LoRA list
        header_frame = ttk.Frame(right_pane)
        header_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(header_frame, text="LoRA", font="-weight bold").pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Label(header_frame, text="Weight", font="-weight bold").pack(side=tk.LEFT, padx=10)
        
        # Scrollable container for LoRA rows
        scroll_container = ScrollableFrame(right_pane)
        scroll_container.pack(fill=tk.BOTH, expand=True)
        self.lora_rows_container = scroll_container.scrollable_frame

        # Action button for adding a LoRA to the current permutation
        ttk.Button(right_pane, text="Add LoRA to Permutation", command=self._add_lora_row_to_current_perm).pack(fill=tk.X, pady=(5,0))

        # --- Bottom Buttons ---
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(10, 0))
        self.generate_button = ttk.Button(bottom_frame, text="Generate", command=self._on_ok, style="Accent.TButton")
        self.generate_button.pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(bottom_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)

    def _on_permutation_select(self, event=None):
        """Handles selection of a permutation in the listbox."""
        selection = self.perm_listbox.curselection()
        if not selection:
            return

        new_index = selection[0]
        if new_index == self.current_permutation_index:
            return

        # Save current state before switching
        self._save_current_permutation_state()

        # Hide all LoRA rows
        for perm in self.permutations:
            for row in perm['lora_rows']:
                row['frame'].pack_forget()

        # Show LoRA rows for the newly selected permutation
        self.current_permutation_index = new_index
        current_perm = self.permutations[self.current_permutation_index]
        for row in current_perm['lora_rows']:
            row['frame'].pack(fill=tk.X, pady=2)

    def _save_current_permutation_state(self):
        """Saves the state of the currently active permutation's LoRA rows."""
        if self.current_permutation_index == -1 or not self.permutations:
            return
        
        current_perm = self.permutations[self.current_permutation_index]
        
        # The lora_rows list already holds the tk variables, so the state is live.
        # We just need to update the display name in the listbox.
        lora_names = []
        for row in current_perm['lora_rows']:
            lora_name = row['lora_var'].get()
            if lora_name and lora_name != "(None)":
                lora_names.append(lora_name)
        
        display_name = f"Permutation {self.current_permutation_index + 1}"
        if lora_names:
            display_name += f" ({' + '.join(lora_names)})"
        
        self.perm_listbox.delete(self.current_permutation_index)
        self.perm_listbox.insert(self.current_permutation_index, display_name)
        current_perm['name'] = display_name

    def _load_loras(self):
        """Loads available LoRAs for the base model."""
        try:
            base_model_obj = self.base_params.get('model', {})
            base_model_type = base_model_obj.get('base')
            lora_models = self.processor.get_invokeai_loras(base_model=base_model_type)
            self.all_loras = {m['name']: m for m in lora_models}

        except Exception as e:
            custom_dialogs.show_error(self, "Error", f"Could not load LoRAs: {e}")
            self.destroy()

    def _add_lora_row(self, lora_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Creates a new LoRA selection row widget set, but does not pack it."""
        row_frame = ttk.Frame(self.lora_rows_container)
        # The frame is packed by the selection logic.

        lora_names = ["(None)"] + sorted(list(self.all_loras.keys()), key=str.lower)
        lora_var = tk.StringVar()
        lora_combo = ttk.Combobox(row_frame, textvariable=lora_var, values=lora_names, state="readonly", width=30)
        lora_combo.pack(side=tk.LEFT, expand=True, fill=tk.X)

        weight_var = tk.StringVar(value="0.75")
        weight_spinbox = VerticalSpinbox(row_frame, from_=-1.0, to=2.0, increment=0.05, textvariable=weight_var, width=4)
        weight_spinbox.pack(side=tk.LEFT, padx=10)

        delete_button = ttk.Button(row_frame, text="Delete", width=6, command=lambda rf=row_frame: self._delete_lora_row(rf))
        delete_button.pack(side=tk.LEFT, padx=5)

        # Set initial values if provided
        if lora_info:
            lora_name = lora_info.get('lora_object', {}).get('name')
            if lora_name in lora_names:
                lora_var.set(lora_name)
            weight_var.set(str(lora_info.get('weight', 0.75)))

        return {"frame": row_frame, "lora_var": lora_var, "weight_var": weight_var}
    
    def _add_lora_row_to_current_perm(self):
        """Adds a new, empty LoRA row to the currently selected permutation."""
        if self.current_permutation_index == -1: return
        
        new_row_widgets = self._add_lora_row()
        self.permutations[self.current_permutation_index]['lora_rows'].append(new_row_widgets)
        # Pack it to make it visible
        new_row_widgets['frame'].pack(fill=tk.X, pady=2)

    def _delete_lora_row(self, row_frame: ttk.Frame):
        """Deletes a specific LoRA row from the current permutation."""
        if self.current_permutation_index == -1: return

        current_perm = self.permutations[self.current_permutation_index]
        row_to_remove = next((row for row in current_perm['lora_rows'] if row['frame'] == row_frame), None)

        if row_to_remove:
            current_perm['lora_rows'].remove(row_to_remove)
            row_frame.destroy()
            self._save_current_permutation_state() # Update listbox name

    def _add_permutation(self, initial_loras: Optional[List[Dict[str, Any]]] = None):
        """Adds a new permutation to the list."""
        perm_id = str(uuid.uuid4())
        lora_rows = []
        lora_names = []

        if initial_loras:
            for lora_info in initial_loras:
                lora_rows.append(self._add_lora_row(lora_info))
                lora_name = lora_info.get('lora_object', {}).get('name')
                if lora_name: lora_names.append(lora_name)
        else:
            # Add one empty row to a new permutation
            lora_rows.append(self._add_lora_row())

        display_name = f"Permutation {len(self.permutations) + 1}"
        if lora_names:
            display_name += f" ({' + '.join(lora_names)})"

        self.permutations.append({
            'id': perm_id,
            'name': display_name,
            'lora_rows': lora_rows
        })
        self.perm_listbox.insert(tk.END, display_name)

    def _duplicate_permutation(self):
        """Duplicates the currently selected permutation."""
        if self.current_permutation_index == -1: return

        self._save_current_permutation_state()
        perm_to_copy = self.permutations[self.current_permutation_index]
        
        new_loras = []
        for row in perm_to_copy['lora_rows']:
            lora_name = row['lora_var'].get()
            weight = row['weight_var'].get()
            lora_obj = self.all_loras.get(lora_name)
            if lora_obj:
                try:
                    weight_val = float(weight)
                except (ValueError, TypeError):
                    weight_val = 0.75
                new_loras.append({'lora_object': lora_obj, 'weight': weight_val})
        self._add_permutation(new_loras)

    def _remove_permutation(self):
        """Removes the currently selected permutation."""
        selection = self.perm_listbox.curselection()
        if not selection: return

        index_to_remove = selection[0]
        perm_to_remove = self.permutations.pop(index_to_remove)

        # Destroy all associated widgets
        for row in perm_to_remove['lora_rows']:
            row['frame'].destroy()

        self.perm_listbox.delete(index_to_remove)

        # Adjust current index and re-select if possible
        if self.current_permutation_index >= index_to_remove:
            self.current_permutation_index -= 1
        
        if self.permutations:
            new_selection_index = min(index_to_remove, len(self.permutations) - 1)
            if new_selection_index >= 0:
                self.perm_listbox.selection_set(new_selection_index)
                self._on_permutation_select()
            else: # List is now empty
                self.current_permutation_index = -1
        else: # List is now empty
            self.current_permutation_index = -1

    def _on_ok(self, event=None):
        """Collects the permutation data and closes the dialog."""
        self._save_current_permutation_state()
        self.result = []
        
        for perm in self.permutations:
            loras_for_this_perm = []
            for row_data in perm['lora_rows']:
                lora_name = row_data["lora_var"].get()
                if not lora_name or lora_name == "(None)":
                    continue

                lora_object = self.all_loras.get(lora_name)
                if not lora_object:
                    custom_dialogs.show_warning(self, "Invalid LoRA", f"LoRA '{lora_name}' not found. Skipping this LoRA.")
                    continue

                try:
                    weight = float(row_data["weight_var"].get())
                except (ValueError, TypeError):
                    weight = 0.75

                loras_for_this_perm.append({'lora_object': lora_object, 'weight': weight})
            
            # Add the list of LoRAs for this permutation to the final result.
            # An empty list is a valid permutation (no LoRAs).
            self.result.append(loras_for_this_perm)

        if not self.result:
            # This can happen if the user removes all permutations.
            # We can add a default permutation with no LoRAs.
            self.result.append([])

        self.destroy()