"""Main entry point for the GUI application."""

import argparse
from gui.gui_app import GUIApp

def main():
    """Initializes and runs the GUI application."""
    parser = argparse.ArgumentParser(description="A tool for Stable Diffusion prompt engineering.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose logging of raw AI responses to the console for brainstorming tasks.")
    args = parser.parse_args()

    app = GUIApp(verbose=args.verbose)
    app.lift()
    app.focus_force()
    app.mainloop()

if __name__ == "__main__":
    main()
