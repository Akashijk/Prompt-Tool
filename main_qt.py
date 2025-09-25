import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from gui_qt.gui_app import GUIApp
from core.config import config

if __name__ == "__main__":
    # Create the QApplication instance
    app = QApplication(sys.argv)

    # --- FIX: Set the application-wide icon here ---
    # This ensures the icon is correctly displayed in the taskbar/dock.
    icon_path = os.path.join(config.PROJECT_ROOT, 'assets', 'icon.png')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Check for the --verbose command-line argument
    verbose_mode = "--verbose" in sys.argv

    # Initialize the GUIApp, passing the verbose flag
    window = GUIApp(verbose=verbose_mode)
    window.show()
    sys.exit(app.exec())