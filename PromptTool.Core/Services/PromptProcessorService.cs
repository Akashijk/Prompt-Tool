using System.Collections.Generic;
using System.Linq;
using PromptTool.Core.Models;

namespace PromptTool.Core.Services
{
    public class PromptProcessorService
    {
        private readonly TemplateEngine _templateEngine;
        private readonly WildcardService _wildcardService;
        private readonly SettingsService _settingsService;

        public PromptProcessorService(WildcardService wildcardService, SettingsService settingsService)
        {
            _wildcardService = wildcardService;
            _settingsService = settingsService;
            if (_settingsService.Settings.Verbose) Console.WriteLine("PromptProcessorService: Constructor started.");
            _templateEngine = new TemplateEngine(wildcardService);
            if (_settingsService.Settings.Verbose) Console.WriteLine("PromptProcessorService: Constructor finished.");
        }

        public TemplateGenerationResult ProcessPrompt(string rawPrompt, int? seed = null, Dictionary<string, ContextValue>? existingContext = null)
        {
            return _templateEngine.Generate(rawPrompt, seed, existingContext);
        }

        public string ProcessPromptToString(string rawPrompt)
        {
            var result = ProcessPrompt(rawPrompt);
            var text = string.Join("", result.Segments.Select(s => s.Text));
            return _templateEngine.CleanupPrompt(text);
        }

        public string CleanupPrompt(string prompt) => _templateEngine.CleanupPrompt(prompt);
    }
}
