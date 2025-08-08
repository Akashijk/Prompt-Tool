"""Main entry point for the GUI application."""

from gui.gui_app import GUIApp

def main():
    """Initializes and runs the GUI application."""
    app = GUIApp()
    app.lift()
    app.focus_force()
    app.mainloop()

if __name__ == "__main__":
    main()