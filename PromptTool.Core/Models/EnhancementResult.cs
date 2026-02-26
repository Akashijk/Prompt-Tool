using System.Collections.Generic;

namespace PromptTool.Core.Models;

public record EnhancementResult(string EnhancedPrompt, Dictionary<string, string> Variations);
