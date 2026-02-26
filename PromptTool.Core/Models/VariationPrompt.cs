using System;
using System.IO;

namespace PromptTool.Core.Models;

public record VariationPrompt(string Key, string Name, string Description, string Prompt)
{
    public static VariationPrompt FromFileData(string fileName, string? name, string? description, string prompt)
    {
        var key = Path.GetFileNameWithoutExtension(fileName) ?? Guid.NewGuid().ToString("N");
        var displayName = string.IsNullOrWhiteSpace(name) ? key.Replace('_', ' ').Trim() : name;
        var desc = description ?? string.Empty;
        return new VariationPrompt(key, displayName, desc, prompt);
    }
}
