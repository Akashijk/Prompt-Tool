from PySide6.QtWidgets import QStyledItemDelegate, QLineEdit, QSpinBox, QWidget
from PySide6.QtCore import Qt, QModelIndex

class ChoiceItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)

    def createEditor(self, parent: QWidget, option: 'QStyleOptionViewItem', index: QModelIndex) -> QWidget:
        if index.column() == 0: # Value column
            editor = QLineEdit(parent)
            return editor
        elif index.column() == 1: # Weight column
            editor = QSpinBox(parent)
            editor.setRange(0, 1000)
            return editor
        # For other columns, use default editor or a custom dialog
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor: QWidget, index: QModelIndex):
        value = index.model().data(index, Qt.EditRole)
        if index.column() == 0: # Value
            editor.setText(str(value))
        elif index.column() == 1: # Weight
            editor.setValue(int(value) if value else 1)
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor: QWidget, model: 'QAbstractItemModel', index: QModelIndex):
        if index.column() == 0: # Value
            model.setData(index, editor.text(), Qt.EditRole)
        elif index.column() == 1: # Weight
            model.setData(index, editor.value(), Qt.EditRole)
        else:
            super().setModelData(editor, model, index)

    def updateEditorGeometry(self, editor: QWidget, option: 'QStyleOptionViewItem', index: QModelIndex):
        editor.setGeometry(option.rect)
