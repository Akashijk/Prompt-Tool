using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using System.Text.Json;
using PromptTool.Core.Models;

namespace PromptTool.Core.Services;

public class TemplateEngine
{
    private readonly WildcardService _wildcardService;
    private Random _random = new();

    // Supports __name__, __!name__, __name:2-4__, and {name}
    private static readonly Regex WildcardRegex =
        new(@"__(?<bang>!)?(?<name>[a-zA-Z0-9_.\s-]+?)(?::(?<min>\d+)(?:-(?<max>\d+))?)?__|\{(?<brace>[^{}]+)\}",
            RegexOptions.Compiled);

    public TemplateEngine(WildcardService wildcardService)
    {
        _wildcardService = wildcardService;
    }

    public TemplateGenerationResult Generate(string template, int? seed = null, Dictionary<string, ContextValue>? existingContext = null)
    {
        var seedToUse = seed ?? Random.Shared.Next();
        _random = new Random(seedToUse);
        var context = existingContext != null
            ? new Dictionary<string, ContextValue>(existingContext, StringComparer.OrdinalIgnoreCase)
            : new Dictionary<string, ContextValue>(StringComparer.OrdinalIgnoreCase);
        var missing = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var segments = RecursiveGenerate(template ?? string.Empty, parentWildcard: null, isFromInclude: false, context, missing);
        return new TemplateGenerationResult(segments, missing, seedToUse, context);
    }

    public string CleanupPrompt(string prompt)
    {
        if (string.IsNullOrWhiteSpace(prompt)) return string.Empty;
        var parts = prompt.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
        return string.Join(", ", parts);
    }

    private List<PromptSegment> RecursiveGenerate(string template, string? parentWildcard, bool isFromInclude, Dictionary<string, ContextValue> context, HashSet<string> missing)
    {
        var segments = new List<PromptSegment>();
        var remaining = template;
        var wildcards = _wildcardService.GetStructuredWildcards();

        while (true)
        {
            var match = WildcardRegex.Match(remaining);
            if (!match.Success) break;

            if (match.Index > 0)
            {
                var prefix = remaining[..match.Index];
                AddSegmentIfAny(prefix, parentWildcard, isFromInclude, false, segments);
            }

            var wildcardName = match.Groups["brace"].Success
                ? match.Groups["brace"].Value.Trim()
                : match.Groups["name"].Value.Trim();

            var hasRange = int.TryParse(match.Groups["min"].Value, out var min);
            int? max = int.TryParse(match.Groups["max"].Value, out var maxParsed) ? maxParsed : null;
            var forceUnique = match.Groups["bang"].Success;

            if (hasRange)
            {
                var text = GetMultipleChoicesText(wildcardName, min, max, wildcards);
                if (string.IsNullOrWhiteSpace(text))
                {
                    missing.Add(wildcardName);
                    segments.Add(new PromptSegment($"__{wildcardName}__", true, wildcardName, isFromInclude, isMissing: true));
                }
                else
                {
                    AddSegmentIfAny(text, wildcardName, true, false, segments);
                }
            }
            else
            {
                var choice = GetChoice(wildcardName, wildcards, context, forceUnique, missing);
                if (choice == null)
                {
                    missing.Add(wildcardName);
                    segments.Add(new PromptSegment(match.Value, true, wildcardName, isFromInclude, isMissing: true));
                }
                else
                {
                    context[wildcardName] = new ContextValue(choice.Value, choice.Tags);
                    segments.AddRange(RecursiveGenerate(choice.Value, wildcardName, true, context, missing));
                    var includeText = BuildIncludes(choice, wildcards.TryGetValue(wildcardName, out var wc) ? wc : null, missing);
                    if (!string.IsNullOrWhiteSpace(includeText))
                    {
                        segments.AddRange(RecursiveGenerate(includeText, wildcardName, true, context, missing));
                    }
                }
            }

            remaining = remaining[(match.Index + match.Length)..];
        }

        AddSegmentIfAny(remaining, parentWildcard, isFromInclude, false, segments);

        return segments;
    }

    private void AddSegmentIfAny(string text, string? wildcardName, bool isFromInclude, bool isMissing, List<PromptSegment> segments)
    {
        if (string.IsNullOrWhiteSpace(text) && string.IsNullOrWhiteSpace(wildcardName))
        {
            return;
        }
        var isWildcard = !string.IsNullOrWhiteSpace(wildcardName);
        if (isWildcard && string.IsNullOrWhiteSpace(text))
        {
            return;
        }
        segments.Add(new PromptSegment(text, isWildcard, wildcardName, isFromInclude, isMissing));
    }

    private WildcardChoice? GetChoice(string wildcardName, IReadOnlyDictionary<string, StructuredWildcard> wildcards, Dictionary<string, ContextValue> context, bool forceUnique, HashSet<string> missing)
    {
        if (!wildcards.TryGetValue(wildcardName, out var data) || data.Choices.Count == 0)
        {
            missing.Add(wildcardName);
            return null;
        }

        if (context.TryGetValue(wildcardName, out var locked) && !string.IsNullOrWhiteSpace(locked.Value))
        {
            var match = data.Choices.FirstOrDefault(c => string.Equals(c.Value, locked.Value, StringComparison.OrdinalIgnoreCase));
            if (match != null)
            {
                return match;
            }
        }

        // Filter choices based on simple "requires" rules (tags/values), if present.
        var pool = data.Choices.Where(c => CheckRequirements(c.RequiresJson, context)).ToList();
        if (forceUnique && context.TryGetValue(wildcardName, out var previous))
        {
            pool = pool.Where(c => !string.Equals(c.Value, previous.Value, StringComparison.OrdinalIgnoreCase)).ToList();
        }
        if (pool.Count == 0) return null;

        var total = pool.Sum(c => c.Weight <= 0 ? 1 : c.Weight);
        return WeightedPick(pool, total);
    }

    private string GetMultipleChoicesText(string wildcardName, int min, int? max, IReadOnlyDictionary<string, StructuredWildcard> wildcards)
    {
        if (!wildcards.TryGetValue(wildcardName, out var data) || data.Choices.Count == 0)
        {
            return string.Empty;
        }

        var upper = max ?? min;
        upper = Math.Max(min, upper);
        var count = _random.Next(min, upper + 1);

        var pool = data.Choices.Where(c => !string.IsNullOrWhiteSpace(c.Value)).ToList();
        if (pool.Count == 0) return string.Empty;

        count = Math.Min(count, pool.Count);
        var selected = new List<string>();
        var available = new List<WildcardChoice>(pool);
        while (selected.Count < count && available.Count > 0)
        {
            var total = available.Sum(c => c.Weight <= 0 ? 1 : c.Weight);
            var choice = WeightedPick(available, total);
            if (choice == null) break;
            selected.Add(choice.Value);
            available.Remove(choice);
        }

        return string.Join(", ", selected);
    }

    private string BuildIncludes(WildcardChoice choice, StructuredWildcard? wildcardData, HashSet<string> missing)
    {
        var includes = choice.Includes ?? wildcardData?.Includes;
        if (includes == null) return string.Empty;

        switch (includes)
        {
            case string s when !string.IsNullOrWhiteSpace(s):
                TrackMissingFromTemplateString(s, missing);
                return " " + ReplaceBracketWildcards(s.Trim()) + " ";
            case IEnumerable<string> list:
                var tokens = new List<string>();
                foreach (var n in list.Where(n => !string.IsNullOrWhiteSpace(n)))
                {
                    var trimmed = n.Trim();
                    var nameOnly = trimmed.Trim('_');
                    if (!_wildcardService.GetStructuredWildcards().ContainsKey(nameOnly))
                    {
                        missing.Add(nameOnly);
                    }
                    tokens.Add(trimmed.StartsWith("__") && trimmed.EndsWith("__") ? trimmed : $"__{trimmed}__");
                }
                return " " + string.Join(", ", tokens) + " ";
            default:
                return string.Empty;
        }
    }

    private void TrackMissingFromTemplateString(string input, HashSet<string> missing)
    {
        foreach (Match m in Regex.Matches(input, @"\[(?<name>[a-zA-Z0-9_.\s-]+?)\]|__(?<name2>[a-zA-Z0-9_.\s-]+?)__"))
        {
            var name = m.Groups["name"].Success ? m.Groups["name"].Value : m.Groups["name2"].Value;
            if (!_wildcardService.GetStructuredWildcards().ContainsKey(name))
            {
                missing.Add(name);
            }
        }
    }

    private static string ReplaceBracketWildcards(string input)
    {
        return Regex.Replace(input, @"\[(?<name>[a-zA-Z0-9_.\s-]+?)\]", m => $"__{m.Groups["name"].Value}__");
    }

    private bool CheckRequirements(string? requiresJson, Dictionary<string, ContextValue> context)
    {
        if (string.IsNullOrWhiteSpace(requiresJson)) return true;
        try
        {
            using var doc = JsonDocument.Parse(requiresJson);
            if (doc.RootElement.ValueKind != JsonValueKind.Object) return true;

            return CheckRules(doc.RootElement, context);
        }
        catch
        {
            // If parsing fails, ignore the requirement
        }
        return true;
    }

    private bool CheckRules(JsonElement rules, Dictionary<string, ContextValue> context)
    {
        if (rules.ValueKind != JsonValueKind.Object) return true;

        if (rules.TryGetProperty("and", out var andNode) && andNode.ValueKind == JsonValueKind.Array)
        {
            return andNode.EnumerateArray().All(child => CheckRules(child, context));
        }
        if (rules.TryGetProperty("or", out var orNode) && orNode.ValueKind == JsonValueKind.Array)
        {
            return orNode.EnumerateArray().Any(child => CheckRules(child, context));
        }
        if (rules.TryGetProperty("not", out var notNode))
        {
            return !CheckRules(notNode, context);
        }

        foreach (var prop in rules.EnumerateObject())
        {
            if (prop.NameEquals("and") || prop.NameEquals("or") || prop.NameEquals("not")) continue;

            // Tag checks
            if (prop.NameEquals("tags") && prop.Value.ValueKind == JsonValueKind.Object)
            {
                if (!CheckTags(prop.Value, context)) return false;
                continue;
            }

            var expected = prop.Value;
            if (context.TryGetValue(prop.Name, out var existing))
            {
                if (expected.ValueKind == JsonValueKind.String &&
                    !string.Equals(existing.Value, expected.GetString(), StringComparison.OrdinalIgnoreCase))
                {
                    return false;
                }
                if (expected.ValueKind == JsonValueKind.Array)
                {
                    var matches = expected.EnumerateArray()
                        .Any(e => e.ValueKind == JsonValueKind.String &&
                                  string.Equals(existing.Value, e.GetString(), StringComparison.OrdinalIgnoreCase));
                    if (!matches) return false;
                }
            }
        }

        return true;
    }

    private bool CheckTags(JsonElement rule, Dictionary<string, ContextValue> context)
    {
        // rule schema: { "any": ["tag"], "all": ["tag2"] }
        List<string> any = new();
        List<string> all = new();
        if (rule.TryGetProperty("any", out var anyNode) && anyNode.ValueKind == JsonValueKind.Array)
        {
            any = anyNode.EnumerateArray().Where(e => e.ValueKind == JsonValueKind.String).Select(e => e.GetString() ?? "").Where(s => !string.IsNullOrWhiteSpace(s)).ToList();
        }
        if (rule.TryGetProperty("all", out var allNode) && allNode.ValueKind == JsonValueKind.Array)
        {
            all = allNode.EnumerateArray().Where(e => e.ValueKind == JsonValueKind.String).Select(e => e.GetString() ?? "").Where(s => !string.IsNullOrWhiteSpace(s)).ToList();
        }

        var tags = context.Values.SelectMany(v => v.Tags).ToList();
        if (all.Count > 0 && all.Any(a => !tags.Contains(a, StringComparer.OrdinalIgnoreCase))) return false;
        if (any.Count > 0 && !any.Any(a => tags.Contains(a, StringComparer.OrdinalIgnoreCase))) return false;
        return true;
    }

    private WildcardChoice? WeightedPick(List<WildcardChoice> pool, double totalWeight)
    {
        var roll = _random.NextDouble() * totalWeight;
        var cumulative = 0.0;
        foreach (var choice in pool)
        {
            cumulative += choice.Weight <= 0 ? 1 : choice.Weight;
            if (roll <= cumulative)
            {
                return choice;
            }
        }
        return pool.LastOrDefault();
    }
}
