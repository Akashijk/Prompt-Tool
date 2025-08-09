# Prompt Tool GUI

A desktop application for generating and enhancing prompts for Stable Diffusion. It leverages local AI models through Ollama to provide a rich, interactive, and creative environment for prompt engineering.

![Main Window Screenshot](assets/screenshot_main.png) <!-- Placeholder: Add a real screenshot here -->

## Key Features

*   **Template-Based Generation:** Create complex prompts using simple templates and `__wildcard__` placeholders.
*   **Live Preview & Interaction:** Instantly see a generated prompt and click on wildcard-generated text to swap it with other options from the source file.
*   **AI-Powered Enhancement:** Use a local LLM to enhance your base prompts, adding detail, style, and quality keywords.
*   **Automatic Variations:** Generate cinematic, artistic, and photorealistic variations of your enhanced prompt with a single click.
*   **Context-Aware AI Brainstorming:** A dedicated chat window to brainstorm ideas. Load existing wildcards or templates into the chat to have the AI help you refine, expand, and improve them in a stateful conversation. You can also generate new content from scratch.
*   **AI Rewriting:** Select any text in the brainstorming chat and have the AI rewrite it based on your instructions.
*   **Wildcard Management:** A full-featured manager to create, edit, sort, and archive your wildcard files, now with a one-click option to send a file's content to the AI Brainstorming window for refinement.
*   **SFW/NSFW Workflows:** Keep your SFW and NSFW content completely separate. The app dynamically switches template, wildcard, and system prompt directories.
*   **Customizable System Prompts:** Edit the underlying instructions given to the AI for enhancement and variations to tailor its output to your needs.
*   **History Viewer:** Browse, search, and reuse all your past enhanced prompts.
*   **Modern UI:** Features a clean, modern interface with light and dark themes.

## Requirements

*   **Python 3.10+**
*   **Ollama** installed and running on your system.
*   At least one LLM pulled in Ollama (e.g., `qwen:7b`, `llama3:8b`). `qwen` models are highly recommended for their creative capabilities.
*   Python libraries as listed in `requirements.txt`.

## Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Akashijk/Prompt-Tool
    cd Prompt_Toolv3
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
    *   **`wildcards/`**: Contains your wildcard files in `.json` format. This powerful format supports simple lists, weighted randomization (`"weight": 5`), context-aware choices (`"requires": {"key": "value"}`), and descriptive tags (`"tags": ["tag1"]`). The root folder is for shared wildcards, and the `nsfw` subfolder is for NSFW-specific ones.
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
    *   **Interact:** In the preview pane, click on any highlighted text to see a menu of other options from that wildcard file.
    *   **Enhance:** When you're happy with the preview, click "Enhance This Prompt". A new window will appear showing the AI's enhanced version and any selected variations.

3.  **AI Brainstorming (`Tools -> AI Brainstorming`):**
    *   Chat directly with the AI for general ideas.
    *   Load an existing wildcard or template (via the Wildcard Manager or Template Editor context menu) to have a focused, context-aware conversation about improving it.
    *   Use the "Generate Wildcard File..." or "Generate Template File..." buttons to have the AI create new content from scratch.
    *   Right-click on text in the conversation to "Rewrite Selection with AI...".

4.  **Wildcard Manager (`Tools -> Wildcard Manager`):**
    *   View all wildcard files for the current workflow.
    *   Select a file to view, edit, and sort its contents.
    *   Click "Brainstorm with AI" to send the current wildcard list to the chat window for refinement.
    *   Save changes, create new files, or archive old ones.

## Configuration

*   **Ollama Server:** Change the Ollama server URL via `Tools -> Ollama Server...`. This is useful if you run Ollama on a different machine on your network.
*   **Theme & Font:** Change the UI theme (Light/Dark) and font size under the `View` menu. Your preferences are saved automatically.
*   **System Prompts:** Modify the core instructions given to the AI via `Tools -> System Prompt Editor`. This gives you fine-grained control over how the AI enhances prompts and creates variations.

## How It Works

*   **Frontend:** Built with Python's standard `tkinter` library and themed with `sv-ttk` for a modern look and feel.
*   **Backend:** Interacts with a local Ollama instance via its REST API. All AI processing happens on your machine.
*   **Workflows:** The SFW/NSFW toggle is a core feature that changes the directories from which templates, wildcards, and system prompts are loaded, ensuring strict content separation.
*   **State Management:** The application tracks model usage and automatically sends requests to Ollama to unload models from VRAM when they are no longer active in any window, helping to manage system resources.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any bugs or feature requests.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.