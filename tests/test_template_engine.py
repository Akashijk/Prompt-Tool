import unittest
from unittest.mock import MagicMock, patch, PropertyMock
import os
import json
import random

from core.template_engine import TemplateEngine, PromptSegment
from core.config import Config # Import Config class to mock its properties

class TestTemplateEngine(unittest.TestCase):
    def setUp(self):
        self.engine = TemplateEngine()
        self.engine.wildcards = {
            'color': {'choices': ['red', 'blue', 'green']},
            'animal': {'choices': ['cat', 'dog', 'bird']},
            'mood': {'choices': ['happy', 'sad']},
            'size': {'choices': ['small', 'large']},
            'style_of_sword': {'choices': ['longsword', 'shortsword']},
            'weapon': {
                'choices': [
                    {'value': 'sword', 'includes': ['__style_of_sword__']},
                    {'value': 'staff', 'requires': {'character': 'mage'}}
                ]
            },
            'character': {'choices': ['mage', 'warrior']},
        }
        
        # Mock the global config object
        self.mock_config = patch('core.config.config', autospec=True).start()
        self.mock_config.WILDCARD_DIR = 'mock_wildcards'
        self.mock_config.WILDCARD_NSFW_DIR = 'mock_wildcards_nsfw'
        self.mock_config.TEMPLATE_BASE_DIR = 'mock_templates_base'
        self.mock_config.HISTORY_DIR = 'mock_history'
        self.mock_config.SYSTEM_PROMPT_BASE_DIR = 'mock_system_prompts'
        self.mock_config.get_template_dir.return_value = 'mock_templates'
        self.mock_config.get_system_prompt_dir.return_value = 'mock_system_prompts_sfw'
        self.mock_config.get_variations_dir.return_value = 'mock_variations'
        self.mock_config.get_history_file_dir.return_value = 'mock_history_sfw'
        self.mock_config.get_history_file.return_value = 'mock_history_sfw/history.jsonl'
        self.mock_config.workflow = 'sfw' # Set workflow for testing

        self.mock_os_path_exists = patch('os.path.exists', return_value=True).start()
        self.mock_os_listdir = patch('os.listdir', return_value=[]).start()
        self.mock_open = patch('builtins.open', new_callable=unittest.mock.mock_open).start()
        
        # Mock random.Random to control random choices
        self.mock_random_random = patch('random.Random', autospec=True).start()
        self.mock_rng_instance = self.mock_random_random.return_value
        self.mock_rng_instance.seed.return_value = None # Prevent seed from interfering with mock behavior
        
        # For _get_wildcard_choice_object, make uniform always select the first choice
        self.mock_rng_instance.uniform.return_value = 0.01 
        
        # For _get_multiple_wildcard_choices, make sample return specific values
        self.mock_rng_instance.sample.side_effect = [
            ['red'], # For test_multiple_wildcard_choices (color) - num_to_select = 1
            ['blue', 'green'], # For test_multiple_wildcard_choices (animal) - num_to_select = 2
        ]
        # For multiple_wildcard_choices, randint is called twice: once for color, once for animal.
        self.mock_rng_instance.randint.side_effect = [1, 2]

        self.addCleanup(patch.stopall)

    def test_seed_reproducibility(self):
        """Test that the same seed produces the same result."""
        template = "A __color__ __animal__."

        # First run
        segments1, _ = self.engine.generate_structured_prompt(template, seed=42)
        result1 = "".join(s.text for s in segments1)
        seed1 = self.engine.current_seed

        # Second run with the same seed
        segments2, _ = self.engine.generate_structured_prompt(template, seed=42)
        result2 = "".join(s.text for s in segments2)
        seed2 = self.engine.current_seed

        self.assertEqual(result1, result2)
        self.assertEqual(seed1, seed2)
        self.assertEqual(seed1, 42)

    def test_random_seed_generation(self):
        """Test that different calls without a seed produce different results."""
        template = "A __color__ __animal__."

        segments1, _ = self.engine.generate_structured_prompt(template)
        result1 = "".join(s.text for s in segments1)
        seed1 = self.engine.current_seed

        segments2, _ = self.engine.generate_structured_prompt(template)
        result2 = "".join(s.text for s in segments2)
        seed2 = self.engine.current_seed

        self.assertNotEqual(result1, result2)
        self.assertNotEqual(seed1, seed2)
        self.assertIsNotNone(seed1)
        self.assertIsNotNone(seed2)

    def test_seed_locking(self):
        """Test that locked seeds remain constant."""
        template = "A __color__ __animal__."

        # Simulate locking by always passing the same seed
        segments1, _ = self.engine.generate_structured_prompt(template, seed=100)
        result1 = "".join(s.text for s in segments1)
        seed1 = self.engine.current_seed

        segments2, _ = self.engine.generate_structured_prompt(template, seed=100)
        result2 = "".join(s.text for s in segments2)
        seed2 = self.engine.current_seed

        self.assertEqual(result1, result2)
        self.assertEqual(seed1, seed2)
        self.assertEqual(seed1, 100)

    def test_seed_unlocking(self):
        """Test that unlocking allows new seeds."""
        template = "A __color__ __animal__."

        # First, generate with a specific seed
        segments1, _ = self.engine.generate_structured_prompt(template, seed=50)
        result1 = "".join(s.text for s in segments1)
        seed1 = self.engine.current_seed

        # Then, generate without a seed (simulating unlock)
        segments2, _ = self.engine.generate_structured_prompt(template)
        result2 = "".join(s.text for s in segments2)
        seed2 = self.engine.current_seed

        self.assertNotEqual(result1, result2)
        self.assertNotEqual(seed1, seed2)
        self.assertEqual(seed1, 50)
        self.assertIsNotNone(seed2)

    def test_structured_prompt_generation(self):
        """Test that structured prompt generation returns correct segments."""
        template = "A __color__ __animal__."
        segments, resolved_context = self.engine.generate_structured_prompt(template, seed=42)

        self.assertIsInstance(segments, list)
        self.assertGreater(len(segments), 0)
        self.assertIsInstance(segments[0], PromptSegment)

        # Check if wildcards were resolved and context populated
        self.assertIn('color', resolved_context)
        self.assertIn('animal', resolved_context)
        self.assertIsNotNone(resolved_context['color']['value'])
        self.assertIsNotNone(resolved_context['animal']['value'])

        # Check the combined text
        full_text = "".join(s.text for s in segments)
        self.assertTrue(full_text.startswith("A "))
        self.assertTrue(resolved_context['color']['value'] in full_text)
        self.assertTrue(resolved_context['animal']['value'] in full_text)

    def test_structured_prompt_with_includes(self):
        """Test structured prompt generation with includes."""
        template = "A __weapon__."
        segments, resolved_context = self.engine.generate_structured_prompt(template, seed=42)
        
        full_text = "".join(s.text for s in segments)
        self.assertIn('weapon', resolved_context)
        self.assertIn('sword', full_text) # Assuming 'sword' is chosen for weapon with seed 42
        self.assertIn('style_of_sword', resolved_context) # Should resolve the included wildcard
        self.assertTrue(resolved_context['style_of_sword']['value'] in full_text)

    def test_structured_prompt_with_requires(self):
        """Test structured prompt generation with requires."""
        template = "A __character__ with a __weapon__."
        # With seed 42, 'mage' is chosen for character, which allows 'staff' for weapon
        segments, resolved_context = self.engine.generate_structured_prompt(template, seed=42)
        
        full_text = "".join(s.text for s in segments)
        self.assertIn('character', resolved_context)
        self.assertIn('weapon', resolved_context)
        self.assertEqual(resolved_context['character']['value'], 'mage')
        self.assertEqual(resolved_context['weapon']['value'], 'staff')
        self.assertIn('mage', full_text)
        self.assertIn('staff', full_text)

    def test_structured_prompt_with_force_reroll(self):
        """Test that force_reroll correctly re-generates a specific wildcard."""
        template = "A __color__ __animal__."
        
        # First generation
        segments1, resolved_context1 = self.engine.generate_structured_prompt(template, seed=1)
        color1 = resolved_context1['color']['value']
        animal1 = resolved_context1['animal']['value']

        # Reroll 'color'
        segments2, resolved_context2 = self.engine.generate_structured_prompt(template, existing_context=resolved_context1, force_reroll=['color'], seed=2)
        color2 = resolved_context2['color']['value']
        animal2 = resolved_context2['animal']['value']

        self.assertNotEqual(color1, color2) # Color should have changed
        self.assertEqual(animal1, animal2) # Animal should remain the same

    def test_structured_prompt_with_force_swap(self):
        """Test that force_swap correctly overrides a specific wildcard."""
        template = "A __color__ __animal__."
        
        # First generation (seed doesn't matter much here as we're swapping)
        segments1, resolved_context1 = self.engine.generate_structured_prompt(template, seed=1)
        original_color = resolved_context1['color']['value']

        # Force swap 'color' to 'purple'
        segments2, resolved_context2 = self.engine.generate_structured_prompt(template, existing_context=resolved_context1, force_swap={'color': 'purple'}, seed=1)
        swapped_color = resolved_context2['color']['value']
        
        self.assertEqual(swapped_color, 'purple')
        self.assertNotEqual(original_color, 'purple') # Ensure it actually changed from original

    def test_cleanup_prompt_string(self):
        """Test the prompt cleanup function."""
        self.assertEqual(self.engine.cleanup_prompt_string("  hello  ,  world  ,  "), "hello, world")
        self.assertEqual(self.engine.cleanup_prompt_string(""), "")
        self.assertEqual(self.engine.cleanup_prompt_string("one, ,two"), "one, two")
        self.assertEqual(self.engine.cleanup_prompt_string("  test  "), "test")
        self.assertEqual(self.engine.cleanup_prompt_string("a,b,c"), "a, b, c")
        self.assertEqual(self.engine.cleanup_prompt_string("a,,b,,c"), "a, b, c") # This is a change in behavior, previous was "a,b,c"

    def test_get_wildcard_options(self):
        """Test retrieving sorted wildcard options."""
        options = self.engine.get_wildcard_options('color')
        self.assertEqual(options, ['blue', 'green', 'red'])

        options = self.engine.get_wildcard_options('non_existent')
        self.assertEqual(options, [])

    def test_find_choice_object_by_value(self):
        """Test finding a choice object by its value."""
        choice = self.engine.find_choice_object_by_value('color', 'red')
        self.assertEqual(choice, 'red')

        choice = self.engine.find_choice_object_by_value('weapon', 'sword')
        self.assertIsInstance(choice, dict)
        self.assertEqual(choice['value'], 'sword')

        choice = self.engine.find_choice_object_by_value('color', 'purple')
        self.assertIsNone(choice)

    def test_multiple_wildcard_choices(self):
        """Test generation of multiple wildcard choices."""
        template = "A __color:1-2__ __animal__."
        segments, resolved_context = self.engine.generate_structured_prompt(template) # Removed seed=42
        
        self.assertIsInstance(segments, list)
        self.assertGreater(len(segments), 0)
        
        # Check that 'color' segment contains 'red, blue'
        color_segment = next((s for s in segments if s.wildcard_name == 'color'), None)
        self.assertIsNotNone(color_segment)
        self.assertEqual(color_segment.text, 'red, blue')

        # Check that 'animal' segment contains 'cat'
        animal_segment = next((s for s in segments if s.wildcard_name == 'animal'), None)
        self.assertIsNotNone(animal_segment)
        self.assertEqual(animal_segment.text, 'cat')

        self.assertFalse('color' in resolved_context) # Multi-selects don't update context
        self.assertFalse('animal' in resolved_context) # Multi-selects don't update context

    def test_force_unique_wildcard(self):
        """Test that !wildcard forces a new choice even if in context."""
        template = "A __color__ and then a __!color__."
        
        # First, generate a color
        segments1, resolved_context1 = self.engine.generate_structured_prompt(template, seed=1)
        first_color = resolved_context1['color']['value']

        # Then, generate again, forcing a unique color for the second instance
        segments2, resolved_context2 = self.engine.generate_structured_prompt(template, existing_context=resolved_context1, seed=2)
        
        # Extract the two color choices from the segments
        colors_in_segments = [s.text for s in segments2 if s.wildcard_name == 'color']
        
        self.assertEqual(len(colors_in_segments), 2)
        self.assertNotEqual(colors_in_segments[0], colors_in_segments[1])