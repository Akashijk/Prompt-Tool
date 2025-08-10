import unittest
from core.template_engine import TemplateEngine

class TestTemplateEngine(unittest.TestCase):
    def setUp(self):
        self.engine = TemplateEngine()
        # Updated to new format and set directly on the engine
        self.engine.wildcards = {
            "color": {"choices": ["red", "blue", "green"]},
            "animal": {"choices": ["cat", "dog", "bird"]}
        }
        
    def test_seed_reproducibility(self):
        """Test that the same seed produces the same result."""
        template = "A __color__ __animal__."
        
        # First run
        seed1 = self.engine.set_seed(42)
        result1 = self.engine.generate_prompt(template)
        
        # Second run with the same seed
        seed2 = self.engine.set_seed(42)
        result2 = self.engine.generate_prompt(template)
        
        self.assertEqual(result1, result2, "The same seed should produce the same prompt.")
        self.assertEqual(seed1, seed2, "The seed value should be consistent.")
        self.assertEqual(result1, "A green bird.")
        
    def test_seed_locking(self):
        """Test that locked seeds remain constant."""
        self.engine.set_seed(42, lock=True)
        seed1 = self.engine.current_seed
        
        # Try to set a new seed while locked (should be ignored)
        self.engine.set_seed(100)
        seed2 = self.engine.current_seed
        
        self.assertEqual(seed1, seed2, "Locked seed should not change.")
        
    def test_seed_unlocking(self):
        """Test that unlocking allows new seeds."""
        self.engine.set_seed(42, lock=True)
        seed1 = self.engine.current_seed
        
        self.engine.unlock_seed()
        self.engine.set_seed(100) # This should now work
        seed2 = self.engine.current_seed
        
        self.assertNotEqual(seed1, seed2, "Unlocked seed should be updatable.")
        self.assertEqual(seed2, 100)

    def test_random_seed_generation(self):
        """Test that different calls without a seed produce different results."""
        template = "A __color__ __animal__."
        
        self.engine.unlock_seed() # Ensure seed is not locked
        seed1 = self.engine.set_seed()
        result1 = self.engine.generate_prompt(template)
        
        seed2 = self.engine.set_seed()
        result2 = self.engine.generate_prompt(template)
        
        self.assertNotEqual(result1, result2, "Different random seeds should produce different prompts.")
        self.assertNotEqual(seed1, seed2, "set_seed() should generate a new random seed each time.")

    def test_structured_prompt_generation(self):
        """Test that structured prompt generation returns correct segments."""
        template = "A __color__ __animal__."
        self.engine.set_seed(42)
        segments = self.engine.generate_structured_prompt(template)
        
        self.assertEqual(len(segments), 5, "Should produce 5 segments")
        
        reconstructed = "".join(s.text for s in segments)
        self.assertEqual(reconstructed, "A green bird.")
        
        self.assertEqual(segments[1].wildcard_name, "color")
        self.assertEqual(segments[3].wildcard_name, "animal")
        self.assertIsNone(segments[0].wildcard_name)