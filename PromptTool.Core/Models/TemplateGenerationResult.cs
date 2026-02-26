using System.Collections.Generic;

namespace PromptTool.Core.Models;

public record TemplateGenerationResult(
    List<PromptSegment> Segments,
    HashSet<string> MissingWildcards,
    int Seed,
    Dictionary<string, ContextValue> Context);

public record ContextValue(string Value, List<string> Tags);
