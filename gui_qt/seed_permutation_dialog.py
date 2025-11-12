from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QSpinBox,
    QDialogButtonBox, QFormLayout, QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt, Slot
from typing import Dict, Any, Optional

class SeedPermutationDialog(QDialog):
    def __init__(self, parent: Optional[QDialog] = None, initial_seed: Optional[int] = None):
        super().__init__(parent)
        self.setWindowTitle("Generate Seed Permutations")
        self.result: Optional[Dict[str, Any]] = None
        self.original_initial_seed = initial_seed # Store the original initial_seed
        self.is_seed_too_large_for_spinbox = (initial_seed is not None and initial_seed + 1 > (2**31 - 1))

        self._create_widgets(initial_seed)
        self._connect_signals()

    def _create_widgets(self, initial_seed: Optional[int]):
        main_layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        self.start_seed_input = QSpinBox()
        max_spinbox_value = 2**31 - 1
        self.start_seed_input.setRange(0, max_spinbox_value)
        if self.is_seed_too_large_for_spinbox:
            self.start_seed_input.setValue(max_spinbox_value) # Display max value
        elif initial_seed is not None:
            # Cap the initial_seed + 1 to prevent overflow
            self.start_seed_input.setValue(min(initial_seed + 1, max_spinbox_value))
        else:
            self.start_seed_input.setValue(0) # Default to 0 or a random seed

        self.num_permutations_input = QSpinBox()
        self.num_permutations_input.setRange(1, 1000) # Limit to a reasonable number
        self.num_permutations_input.setValue(5) # Default to 5

        self.end_seed_input = QSpinBox()
        self.end_seed_input.setRange(0, max_spinbox_value)
        if self.is_seed_too_large_for_spinbox:
            self.end_seed_input.setValue(max_spinbox_value) # Display max value
        elif initial_seed is not None:
            # Cap the initial_seed + num_permutations to prevent overflow
            self.end_seed_input.setValue(min(initial_seed + self.num_permutations_input.value(), max_spinbox_value))
        else:
            self.end_seed_input.setValue(10)

        self.random_seed_checkbox = QCheckBox("Generate Random Seeds")
        self.random_seed_checkbox.setChecked(False) # Default to unchecked

        form_layout.addRow("Start Seed:", self.start_seed_input)
        form_layout.addRow("End Seed:", self.end_seed_input)
        form_layout.addRow("Number of Permutations:", self.num_permutations_input)
        form_layout.addRow(self.random_seed_checkbox)

        if self.is_seed_too_large_for_spinbox:
            form_layout.addRow(QLabel("Seed too large for manual adjustment. Using original seed + 1."))

        main_layout.addLayout(form_layout)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        main_layout.addWidget(self.button_box)

        # --- NEW: Trigger initial update for end_seed_input ---
        self._on_num_permutations_changed(self.num_permutations_input.value())

    def _connect_signals(self):
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.num_permutations_input.valueChanged.connect(self._on_num_permutations_changed)
        self.start_seed_input.valueChanged.connect(self._on_start_seed_changed)
        self.random_seed_checkbox.stateChanged.connect(self._on_random_seed_checkbox_changed)

    @Slot(int)
    def _on_num_permutations_changed(self, value: int):
        current_start_seed = self.start_seed_input.value()
        required_end_seed = current_start_seed + value - 1
        max_spinbox_value = 2**31 - 1 # Define max_spinbox_value here as well
        
        # Always set the value to the required_end_seed, capped at max_spinbox_value
        # This will both increase and decrease as needed.
        self.end_seed_input.setValue(min(required_end_seed, max_spinbox_value))

    @Slot(int)
    def _on_start_seed_changed(self, value: int):
        current_num_permutations = self.num_permutations_input.value()
        required_end_seed = value + current_num_permutations - 1
        max_spinbox_value = 2**31 - 1 # Define max_spinbox_value here as well
        
        # Always set the value to the required_end_seed, capped at max_spinbox_value
        # This will both increase and decrease as needed.
        self.end_seed_input.setValue(min(required_end_seed, max_spinbox_value))

    @Slot(int)
    def _on_random_seed_checkbox_changed(self, state: int):
        is_checked = (state == Qt.CheckState.Checked.value)
        # Only enable/disable if seed is not too large for spinbox
        self.start_seed_input.setEnabled(not is_checked)
        self.end_seed_input.setEnabled(not is_checked)

    def accept(self):
        num_permutations = self.num_permutations_input.value()
        if self.random_seed_checkbox.isChecked():
            # Generate random seeds
            import random
            seeds = [random.randint(0, 2**31 - 1) for _ in range(num_permutations)]
            self.result = {
                "random_seeds": True,
                "seeds": seeds,
                "num_permutations": num_permutations
            }
        else:
            if self.is_seed_too_large_for_spinbox:
                # Use original_initial_seed for calculation
                true_start_seed = self.original_initial_seed + 1
                true_end_seed = true_start_seed + num_permutations - 1
                
                # --- NEW: Apply roll-over logic ---
                max_generation_seed = 2**32 - 1
                if true_start_seed > max_generation_seed:
                    true_start_seed = (true_start_seed % (max_generation_seed + 1)) # Roll over
                    if true_start_seed == 0:
                        true_start_seed = 1 # Ensure not 0
                if true_end_seed > max_generation_seed:
                    true_end_seed = (true_end_seed % (max_generation_seed + 1)) # Roll over
                    if true_end_seed == 0:
                        true_end_seed = 1 # Ensure not 0
                
                self.result = {
                    "random_seeds": False,
                    "start_seed": true_start_seed,
                    "end_seed": true_end_seed,
                    "num_permutations": num_permutations
                }
            else:
                start_seed = self.start_seed_input.value()
                end_seed = self.end_seed_input.value()

                if start_seed > end_seed:
                    QMessageBox.warning(self, "Invalid Input", "Start Seed cannot be greater than End Seed.")
                    return

                # --- NEW: Apply roll-over logic for manually entered seeds ---
                max_generation_seed = 2**32 - 1
                if start_seed > max_generation_seed:
                    start_seed = (start_seed % (max_generation_seed + 1))
                    if start_seed == 0:
                        start_seed = 1
                if end_seed > max_generation_seed:
                    end_seed = (end_seed % (max_generation_seed + 1))
                    if end_seed == 0:
                        end_seed = 1

                self.result = {
                    "random_seeds": False,
                    "start_seed": start_seed,
                    "end_seed": end_seed,
                    "num_permutations": num_permutations
                }
        super().accept()

    def get_options(self) -> Optional[Dict[str, Any]]:
        return self.result
