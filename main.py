"""Main entry point for the Stable Diffusion Prompt Generator application."""

from cli.cli_app import CLIApp

def main():
    """Initializes and runs the command-line interface."""
    app = CLIApp()
    app.run()

if __name__ == "__main__":
    main()
