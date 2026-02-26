using System.Collections.Generic;
using System.Text.Json;

namespace PromptTool.Core.Models;

public class WildcardChoice
{
    public string Value { get; set; } = string.Empty;
    public double Weight { get; set; } = 1;
    public List<string> Tags { get; set; } = new();
    public object? Includes { get; set; }
    public string? RequiresJson { get; set; }
}

public class StructuredWildcard
{
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public object? Includes { get; set; }
    public List<WildcardChoice> Choices { get; set; } = new();
}
