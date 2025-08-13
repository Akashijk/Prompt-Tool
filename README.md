# Prompt Tool GUI

A desktop application for generating and enhancing prompts for Stable Diffusion. It leverages local AI models through Ollama to provide a rich, interactive, and creative environment for prompt engineering.

![Main Window Screenshot](assets/screenshot_main.png) <!-- Placeholder: Add a real screenshot here -->

## Key Features

*   **Template-Based Generation:** Create complex prompts using simple templates and `__wildcard__` placeholders.
*   **Interactive Template Editor:**
    *   Get AI-powered suggestions to expand and improve your templates.
    *   Double-click any `__wildcard__` to immediately open it in the Wildcard Manager.
    *   Select any text and right-click to instantly turn it into a new wildcard file.
*   **Live Preview & Interaction:**
    *   Instantly see a generated prompt and click on wildcard-generated text to swap it with other options from the source file.
    *   Automatically detects missing wildcards used in your template and provides clickable links to generate them on the fly.
*   **AI-Powered Enhancement:** Use a local LLM to enhance your base prompts, adding detail, style, and quality keywords.
*   **Automatic Variations:** Generate cinematic, artistic, and photorealistic variations of your enhanced prompt with a single click.
*   **Advanced AI Brainstorming:**
    *   A dedicated chat window to brainstorm ideas. Load existing wildcards or templates into the chat to have the AI help you refine, expand, and improve them.
    *   Generate new wildcard or template files from scratch based on a concept.
    *   The AI automatically detects when a generated template or wildcard requires *new* wildcards, and provides clickable links to generate them.
    *   Select any text in the conversation and have the AI rewrite it based on your instructions.
*   **Full-Featured Wildcard Management:**
    *   A powerful structured editor to easily manage complex choices with weights, tags, requirements, and includes.
    *   Find and automatically remove duplicate choices within a file.
    *   Merge multiple wildcard files into a new one, intelligently combining their content.
    *   Scan your entire project to find unused wildcard files that can be archived or deleted.
    *   Use AI to suggest new choices for a wildcard, or to automatically add weights, tags, and other metadata to your existing choices.
*   **SFW/NSFW Workflows:** Keep your SFW and NSFW content completely separate. The app dynamically switches template, wildcard, and system prompt directories.
*   **Customizable System Prompts:** Edit the underlying instructions given to the AI for enhancement and variations to tailor its output to your needs.
*   **History Viewer:** Browse, search, and reuse all your past enhanced prompts, with the ability to mark favorites.
*   **Seed Management:** Easily switch between a fixed seed for reproducible results and random seeds for variety.
*   **Modern UI:** Features a clean, modern interface with light and dark themes and adjustable font sizes.

## Requirements

*   **Python 3.10+**
*   **Ollama** installed and running on your system.
*   At least one LLM pulled in Ollama (e.g., `qwen:7b`, `llama3:8b`). `qwen` models are highly recommended for their creative capabilities.
*   Python libraries as listed in `requirements.txt`.

## Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Akashijk/Prompt-Tool
    cd Prompt-Tool
    ```

2.  **Install Ollama:**
    Follow the instructions on ollama.com to install and start the Ollama server.

3.  **Pull an AI Model:**
    Pull a model to be used for enhancement and brainstorming.
    ```bash
    ollama run qwen:7b
    ```

4.  **Set up a Python Environment (Recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

5.  **Install Dependencies:**
    Install the required Python packages using the provided `requirements.txt` file.
    ```bash
    pip install -r requirements.txt
    ```

6.  **Directory Structure:**
    The application uses the following directory structure within the project root. You can create these folders and start adding your own `.txt` files.
    ```
    /
    ├── templates/  (.txt files)
    │   ├── sfw/
    │   └── nsfw/
    ├── wildcards/  (.json files)
    │   ├── nsfw/ (for nsfw-only wildcards)
    │   └── ... (shared wildcards go in the root)
    └── system_prompts/ (.txt files)
        ├── sfw/
        └── nsfw/
    ```
    *   **`templates/`**: Contains your prompt templates, organized by workflow.
    *   **`wildcards/`**: Contains your wildcard files in `.json` format. This powerful format supports simple lists, weighted randomization (`"weight": 5`), context-aware choices (`"requires": {"key": "value"}`), dynamic wildcard inclusion (`"includes": ["wildcard_name"]`), and descriptive tags (`"tags": ["tag1"]`) for future filtering and organization. The root folder is for shared wildcards, and the `nsfw` subfolder is for NSFW-specific ones.
    *   **`system_prompts/`**: The application will automatically create default system prompts here. You can edit them via the UI (`Tools -> System Prompt Editor`).

## Usage

1.  **Run the application:**
    ```bash
    python main.py  # Assuming the main script is named main.py
    ```

2.  **Main Window Workflow:**
    *   **Workflow:** Choose `SFW` or `NSFW` from the "Workflow" menu. This changes the content available.
    *   **Model:** Select an active Ollama model from the dropdown.
    *   **Template:** Select a template file. The content will appear in the editor.
    *   **Generate:** Click "Generate Next Preview" to see a prompt with wildcards filled in.
    *   **Interact:** In the preview pane, click on any highlighted text to see a menu of other options from that wildcard file. If your template uses a wildcard that doesn't exist, a link will appear below the preview allowing you to generate it.
    *   **Enhance:** When you're happy with the preview, click "Enhance This Prompt". A new window will appear showing the AI's enhanced version and any selected variations.

3.  **AI Brainstorming (`Tools -> AI Brainstorming`):**
    *   Chat directly with the AI for general ideas.
    *   Load an existing wildcard or template (via the Wildcard Manager or Template Editor context menu) to have a focused, context-aware conversation about improving it.
    *   Use the "Generate Wildcard File..." or "Generate Template File..." buttons to have the AI create new content from scratch.
    *   When the AI generates content that uses a new, non-existent wildcard, it will appear as a clickable link in the chat history, allowing you to generate it instantly.
    *   Right-click on text in the conversation to "Rewrite Selection with AI...".

4.  **Wildcard Manager (`Tools -> Wildcard Manager`):**
    *   View all wildcard files for the current workflow.
    *   Select a file to view and edit its contents.
    *   Use the structured editor to manage complex choices, or switch to the raw text editor for direct JSON editing.
    *   Use the "Suggest Choices (AI)" button to have the AI generate new items for your list.
    *   Use the "Refine Choices (AI)" button to have the AI analyze your existing choices and add metadata like weights, tags, and requirements.
    *   Find duplicates, sort choices, merge files, or find unused wildcards across your project.
    *   Click "Brainstorm with AI" to send the current wildcard list to the chat window for refinement.

## Configuration

*   **Ollama Server:** Change the Ollama server URL via `Tools -> Ollama Server...`. This is useful if you run Ollama on a different machine on your network.
*   **Theme & Font:** Change the UI theme (Light/Dark) and font size under the `View` menu. Your preferences are saved automatically.
*   **System Prompts:** Modify the core instructions given to the AI via `Tools -> System Prompt Editor`. This gives you fine-grained control over how the AI enhances prompts and creates variations.

## How It Works

*   **Frontend:** Built with Python's standard `tkinter` library and themed with `sv-ttk` for a modern look and feel.
*   **Backend:** Interacts with a local Ollama instance via its REST API. All AI processing happens on your machine.
*   **Workflows:** The SFW/NSFW toggle is a core feature that changes the directories from which templates, wildcards, and system prompts are loaded, ensuring strict content separation.
*   **State Management:** The application tracks model usage across all windows and automatically sends requests to Ollama to unload models from VRAM when they are no longer active, helping to manage system resources.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any bugs or feature requests.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.