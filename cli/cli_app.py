"""Command-line interface for the prompt generator."""

from typing import List, Optional, Dict, Any
from core.prompt_processor import PromptProcessor
from core.config import config, DEFAULT_SFW_VARIATION_INSTRUCTIONS, DEFAULT_NSFW_VARIATION_INSTRUCTIONS

class CLIApp:
    """Command-line interface for prompt generation."""
    
    def __init__(self):
        self.processor = PromptProcessor()
        self.chosen_model: Optional[str] = None
        
    def run(self) -> None:
        """Main CLI application loop."""
        print("🎨 Stable Diffusion Prompt Generator")
        print("="*50)
        
        try:
            # Initialize
            print("Initializing...")
            self.processor.initialize()

            # Select workflow
            self._select_workflow()
            
            # Select model
            self.chosen_model = self._select_model()
            if not self.chosen_model:
                return
                
            # Select template
            template_file = self._select_template()
            if not template_file:
                return
                
            template_content = self.processor.load_template_content(template_file)
            
            # Get generation settings
            num_prompts = self._get_prompt_count()
            
            # Phase 1: Queue prompts
            enhancement_queue = self._queue_prompts(template_content, num_prompts)
            
            if not enhancement_queue:
                print("No prompts queued. Exiting.")
                return
            
            # Phase 2: Choose enhancement type and process
            create_variations = self._get_enhancement_choice()
            
            # Phase 3: Process batch
            results = self._process_batch(enhancement_queue, create_variations)
            
            # Display results and save
            self._display_results(results, create_variations)
            self._save_results(results)

            print("\n✅ Complete!")
            
        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user.")
        except Exception as e:
            print(f"\nError: {e}")
        finally:
            if self.chosen_model:
                print("\nCleaning up and unloading model...")
                self.processor.cleanup_model(self.chosen_model)
            print("\nApplication finished.")

    def _select_workflow(self):
        """Let user select the operational workflow."""
        print("\n" + "="*50)
        print("SELECT WORKFLOW")
        print("1. SFW (Safe For Work)")
        print("2. NSFW (Not Safe For Work)")
        
        while True:
            choice = input("\nChoose a workflow (default 1): ").strip()
            if choice == '' or choice == '1':
                config.workflow = 'sfw'
                print("SFW workflow selected.")
                break
            elif choice == '2':
                config.workflow = 'nsfw'
                print("NSFW workflow selected.")
                break
            else:
                print("Invalid choice. Please enter 1 or 2.")
    
    def _select_model(self) -> Optional[str]:
        """Let user select an Ollama model."""
        try:
            models = self.processor.get_available_models()
        except Exception as e:
            print(f"Error getting models: {e}")
            return None
            
        if not models:
            print("No Ollama models found. Please install a model first.")
            return None
        
        # Get recommendations
        recommendations = self.processor.get_model_recommendations(models)
        default_model = None
        default_index = None
        
        # Find default
        for idx, model, _ in recommendations:
            if 'qwen' in model.lower() and '7b' in model.lower():
                default_model = model
                default_index = idx
                break
        
        if not default_model and recommendations:
            default_index, default_model, _ = recommendations[0]
        elif not default_model:
            default_model = models[0]
            default_index = 1
        
        # Display recommendations
        if recommendations:
            print("\n🌟 RECOMMENDED MODELS FOR PROMPT ENHANCEMENT:")
            for idx, model, reason in recommendations:
                marker = " (DEFAULT)" if model == default_model else ""
                print(f"   {idx}. {model}{marker} - {reason}")

        print("\n" + "-"*50)
        print(f"All Available Ollama Models:")
        for i, model in enumerate(models, 1):
            marker = " ← DEFAULT" if model == default_model else ""
            print(f"{i}. {model}{marker}")
        
        while True:
            try:
                user_input = input(f"\nChoose a model number (or press Enter for default #{default_index}): ").strip()
                if not user_input:
                    return default_model
                
                choice = int(user_input)
                if 1 <= choice <= len(models):
                    return models[choice - 1]
                else:
                    print("Invalid number, try again.")
            except ValueError:
                print("Please enter a valid number.")
    
    def _select_template(self) -> Optional[str]:
        """Let user select a template."""
        templates = self.processor.get_available_templates()
        
        if not templates:
            print("No template files found in templates/ directory.")
            return None
        
        print("\nAvailable Templates:")
        for i, template in enumerate(templates, 1):
            print(f"{i}. {template}")
        
        while True:
            try:
                choice = int(input("\nChoose a template number: "))
                if 1 <= choice <= len(templates):
                    return templates[choice - 1]
                else:
                    print("Invalid number, try again.")
            except ValueError:
                print("Please enter a valid number.")
    
    def _get_prompt_count(self) -> int:
        """Get number of prompts to generate."""
        while True:
            try:
                user_input = input(f"\nHow many prompts to generate? (default {config.DEFAULT_NUM_PROMPTS}): ").strip()
                if not user_input:
                    return config.DEFAULT_NUM_PROMPTS
                return int(user_input)
            except ValueError:
                print("Please enter a valid number.")
    
    def _queue_prompts(self, template_content: str, num_prompts: int) -> List[str]:
        """Phase 1: Queue prompts for enhancement."""
        print(f"\n" + "="*60)
        print("PHASE 1: QUEUING PROMPTS FOR ENHANCEMENT")
        print("="*60)
        print("Tip: Queue as many prompts as you want, then batch process them all!")
        
        enhancement_queue = []
        skipped_count = 0
        
        while len(enhancement_queue) < num_prompts:
            # Generate a new prompt
            raw_prompts = self.processor.generate_raw_prompts(template_content, 1)
            if not raw_prompts:
                print("Could not generate more unique prompts.")
                break
                
            prompt = raw_prompts[0]
            
            print(f"\n{'='*80}")
            print(f"[Preview #{len(enhancement_queue) + skipped_count + 1}] (Queue: {len(enhancement_queue)}/{num_prompts}):")
            print(f"{prompt}")
            
            choice = self._get_queue_choice()
            
            if choice == 'done':
                if len(enhancement_queue) == 0:
                    print("No prompts queued! Please queue at least one prompt.")
                    continue
                else:
                    break
            elif choice == 'skip':
                self.processor.save_skipped_prompt(prompt)
                skipped_count += 1
                print("Prompt skipped and logged.\n")
            elif choice == 'queue':
                enhancement_queue.append(prompt)
                print(f"✓ Queued! ({len(enhancement_queue)}/{num_prompts} slots filled)\n")
        
        return enhancement_queue
    
    def _get_enhancement_choice(self) -> bool:
        """Ask user if they want to generate variations for the queued prompts."""
        print("\n" + "="*60)
        print("PHASE 2: CHOOSE ENHANCEMENT OPTIONS")
        print("="*60)
        return input("\nGenerate cinematic/artistic/photorealistic variations for each prompt? (y/N): ").lower().startswith('y')

    def _process_batch(self, prompts: List[str], create_variations: bool) -> List[Dict[str, Any]]:
        """Phase 3: Process the batch of prompts."""
        print("\n" + "="*60)
        print("PHASE 3: PROCESSING BATCH")
        print("="*60)
        
        if not self.chosen_model:
            print("Error: No model selected.")
            return []
            
        # Set up a structured callback for progress display
        def cli_status_callback(event_type: str, **kwargs):
            message = ""
            if event_type == 'enhancement_start':
                p_num = kwargs.get('prompt_num', 0)
                t_prompts = kwargs.get('total_prompts', 0)
                message = f"Enhancing main prompt {p_num}/{t_prompts}..."
            elif event_type == 'variation_start':
                var_type = kwargs.get('var_type', 'unknown')
                p_num = kwargs.get('prompt_num', 0)
                t_prompts = kwargs.get('total_prompts', 0)
                message = f"Creating '{var_type}' variation for prompt {p_num}/{t_prompts}..."
            elif event_type == 'batch_complete':
                message = "Batch processing complete."
            elif event_type == 'batch_cancelled':
                message = "Processing cancelled."
            
            if message:
                print(f"-> {message}")
            
        self.processor.set_callbacks(status_callback=cli_status_callback)
        
        variation_instructions = DEFAULT_SFW_VARIATION_INSTRUCTIONS if config.workflow == 'sfw' else DEFAULT_NSFW_VARIATION_INSTRUCTIONS
        selected_variations = list(variation_instructions.keys()) if create_variations else None
        
        results = self.processor.process_enhancement_batch(
            prompts,
            self.chosen_model,
            selected_variations,
            cancellation_event=None # CLI does not support cancellation
        )
        
        return results

    def _display_results(self, results: List[Dict[str, Any]], with_variations: bool):
        """Display the final generated prompts."""
        print("\n" + "="*60)
        print("🌟 FINAL RESULTS 🌟")
        print("="*60)
        
        for i, result in enumerate(results, 1):
            print(f"\n--- Prompt #{i} ---")
            print(f"Original: {result['original']}")
            print(f"Enhanced: {result['enhanced']}")
            print(f"Recommended SD Model: {result['enhanced_sd_model']}")
            
            if with_variations and result.get('variations'):
                print("\n  Variations:")
                for var_type, var_data in result['variations'].items():
                    print(f"    - {var_type.capitalize()}: {var_data['prompt']}")
                    print(f"      (Model: {var_data['sd_model']})")
            print()  # Add a blank line for spacing
        print("="*60)

    def _save_results(self, results: List[Dict[str, Any]]):
        """Save the results to the CSV history file."""
        if not results:
            return
            
        print("\n💾 Saving results to history file...")
        self.processor.save_results(results)
        print(f"Saved {len(results)} results to {config.get_csv_history_file()}\n")

    def _get_queue_choice(self) -> str:
        """Get user choice for queuing."""
        while True:
            print("\nOptions:")
            print("1. Queue for enhancement (default)")
            print("2. Skip and generate new prompt")
            print("3. Done queuing, start processing")
            
            choice = input("\nChoose an option (1/2/3) or press Enter for 1: ").strip().lower()
            
            if choice == '' or choice == '1' or choice == 'queue' or choice == 'q':
                return 'queue'
            elif choice == '2' or choice == 'skip' or choice == 's':
                return 'skip'
            elif choice == '3' or choice == 'done' or choice == 'd':
                return 'done'
            else:
                print("Invalid choice, please try again.")