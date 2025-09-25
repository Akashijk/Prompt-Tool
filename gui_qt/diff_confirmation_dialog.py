"""A Qt dialog to display a text diff and get user confirmation."""

import difflib
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox
)
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont

class DiffHighlighter(QSyntaxHighlighter):
    """A simple syntax highlighter for unified diff format."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        # Rule for additions
        addition_format = QTextCharFormat()
        addition_format.setForeground(QColor("#2E7D32")) # Green
        self.highlighting_rules.append((r'^\+.*', addition_format))

        # Rule for deletions
        deletion_format = QTextCharFormat()
        deletion_format.setForeground(QColor("#C62828")) # Red
        self.highlighting_rules.append((r'^\-.*', deletion_format))

    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            for match in __import__('re').finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), format)

class DiffConfirmationDialog(QDialog):
    """A dialog to show a diff and ask for confirmation."""
    def __init__(self, parent, title: str, original_text: str, new_text: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(700, 500)
        
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

        layout = QVBoxLayout(self)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Courier", 10))
        layout.addWidget(self.text_edit)
        self.highlighter = DiffHighlighter(self.text_edit.document())
        diff_text = "".join(difflib.unified_diff(original_text.splitlines(keepends=True), new_text.splitlines(keepends=True), fromfile='Original', tofile='Enhanced'))
        self.text_edit.setPlainText(diff_text if diff_text else "No changes proposed by the AI.")
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Apply Changes")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)