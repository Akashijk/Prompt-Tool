using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using PromptTool.Core.Models;

namespace PromptTool.ViewModels;

public partial class WildcardChoiceViewModel : ObservableObject
{
    private readonly WildcardChoice _choice;
    private readonly Action _onDirty;

    [ObservableProperty] private int _index;
    [ObservableProperty] private string _warning = "";
    [ObservableProperty] private string _includesDisplay = "";
    [ObservableProperty] private int _includesCount;
    [ObservableProperty] private int _requiresCount;
    [ObservableProperty] private string _includesTooltip = "";
    [ObservableProperty] private string _requiresTooltip = "";
    public WildcardChoiceViewModel(WildcardChoice choice, int index, Action onDirty)
    {
        _choice = choice;
        _onDirty = onDirty;
        _index = index;
        _value = choice.Value;
        _weight = choice.Weight;
        _tags = string.Join(", ", choice.Tags ?? new());
        _requiresDisplay = FormatRequiresDisplay(_requires);
        _includesDisplay = FormatIncludesDisplay(_includes);
        UpdateIncludesDisplay();
        UpdateRequiresDisplay();
    }

    [ObservableProperty] private string _value = string.Empty;
    [ObservableProperty] private double _weight = 1.0;
    [ObservableProperty] private string _tags = "";
    [ObservableProperty] private string _includes = "";
    [ObservableProperty] private string _requires = "";
    [ObservableProperty] private string _requiresDisplay = "";

    partial void OnValueChanged(string value) => _onDirty();
    partial void OnWeightChanged(double value) => _onDirty();
    partial void OnTagsChanged(string value) => _onDirty();
    partial void OnIncludesChanged(string value)
    {
        UpdateIncludesDisplay();
        _onDirty();
    }
    partial void OnRequiresChanged(string value)
    {
        UpdateRequiresDisplay();
        _onDirty();
    }

    public WildcardChoice ToModel()
    {
        return new WildcardChoice
        {
            Value = Value,
            Weight = Weight,
            Tags = (Tags ?? string.Empty)
                .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                .ToList(),
            Includes = ParseIncludes(Includes),
            RequiresJson = string.IsNullOrWhiteSpace(Requires) ? null : Requires
        };
    }

    private void UpdateRequiresDisplay()
    {
        RequiresDisplay = FormatRequiresDisplay(Requires);
        var (count, tooltip) = BuildRequiresTooltip(Requires);
        RequiresCount = count;
        RequiresTooltip = tooltip;
    }

    private void UpdateIncludesDisplay()
    {
        IncludesDisplay = FormatIncludesDisplay(Includes);
        var items = ParseIncludesList(Includes);
        IncludesCount = items.Count;
        IncludesTooltip = items.Count == 0 ? "None" : string.Join(Environment.NewLine, items);
    }

    private static string FormatRequiresDisplay(string? requires)
    {
        if (string.IsNullOrWhiteSpace(requires)) return string.Empty;
        try
        {
            using var doc = JsonDocument.Parse(requires);
            if (doc.RootElement.ValueKind != JsonValueKind.Object) return "custom";
            var props = doc.RootElement.EnumerateObject().ToList();
            if (props.Count != 1) return "custom";
            var prop = props[0];
            if (prop.Value.ValueKind == JsonValueKind.String)
            {
                return $"{prop.Name} = {prop.Value.GetString()}";
            }
            if (prop.Value.ValueKind == JsonValueKind.Array)
            {
                var values = prop.Value.EnumerateArray()
                    .Where(e => e.ValueKind == JsonValueKind.String)
                    .Select(e => e.GetString())
                    .Where(s => !string.IsNullOrWhiteSpace(s))
                    .ToList();
                if (values.Count > 0)
                {
                    return $"{prop.Name} in [{string.Join(", ", values)}]";
                }
            }
            return "custom";
        }
        catch
        {
            return "custom";
        }
    }

    private static string FormatIncludesDisplay(string? includes)
    {
        if (string.IsNullOrWhiteSpace(includes)) return string.Empty;
        var parts = includes.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length == 0) return string.Empty;
        return string.Join(", ", parts);
    }

    private static List<string> ParseIncludesList(string? includes)
    {
        if (string.IsNullOrWhiteSpace(includes)) return new List<string>();
        return includes.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(s => !string.IsNullOrWhiteSpace(s))
            .ToList();
    }

    private static (int Count, string Tooltip) BuildRequiresTooltip(string? requires)
    {
        if (string.IsNullOrWhiteSpace(requires)) return (0, "None");
        try
        {
            using var doc = JsonDocument.Parse(requires);
            var root = doc.RootElement;
            var rules = new List<string>();
            if (root.ValueKind == JsonValueKind.Object && root.TryGetProperty("and", out var andNode) && andNode.ValueKind == JsonValueKind.Array)
            {
                foreach (var child in andNode.EnumerateArray())
                {
                    if (TryFormatRule(child, out var line))
                    {
                        rules.Add(line);
                    }
                }
            }
            else if (TryFormatRule(root, out var single))
            {
                rules.Add(single);
            }

            if (rules.Count == 0)
            {
                return (1, "Custom rules");
            }
            return (rules.Count, string.Join(Environment.NewLine, rules));
        }
        catch
        {
            return (1, "Custom rules");
        }
    }

    private static bool TryFormatRule(JsonElement element, out string line)
    {
        line = string.Empty;
        if (element.ValueKind != JsonValueKind.Object) return false;
        var props = element.EnumerateObject().ToList();
        if (props.Count != 1) return false;
        var prop = props[0];
        if (prop.Value.ValueKind == JsonValueKind.String)
        {
            line = $"{prop.Name} = {prop.Value.GetString()}";
            return true;
        }
        if (prop.Value.ValueKind == JsonValueKind.Array)
        {
            var values = prop.Value.EnumerateArray()
                .Where(e => e.ValueKind == JsonValueKind.String)
                .Select(e => e.GetString())
                .Where(s => !string.IsNullOrWhiteSpace(s))
                .ToList();
            if (values.Count > 0)
            {
                line = $"{prop.Name} in [{string.Join(", ", values)}]";
                return true;
            }
        }
        return false;
    }

    private static object? ParseIncludes(string includes)
    {
        if (string.IsNullOrWhiteSpace(includes)) return null;
        var parts = includes.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length == 1) return parts[0];
        return parts.ToList();
    }
}
