using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;

namespace PromptTool.ViewModels;

public partial class JsonDiffViewModel : ObservableObject
{
    [ObservableProperty] private string _windowTitle = "JSON Diff";
    [ObservableProperty] private string _leftTitle = "Left JSON";
    [ObservableProperty] private string _rightTitle = "Right JSON";
    [ObservableProperty] private string _leftJson = string.Empty;
    [ObservableProperty] private string? _rightJson;
    [ObservableProperty] private string _summary = string.Empty;
    [ObservableProperty] private ObservableCollection<JsonDiffItem> _diffs = new();
    [ObservableProperty] private bool _hasDiffs;
    [ObservableProperty] private bool _hasRightJson;

    public JsonDiffViewModel(string windowTitle, string leftJson, string? rightJson)
    {
        WindowTitle = windowTitle;
        LeftJson = leftJson;
        RightJson = rightJson;
        HasRightJson = !string.IsNullOrWhiteSpace(rightJson);
        BuildDiffs();
    }

    private void BuildDiffs()
    {
        Diffs.Clear();
        HasDiffs = false;

        if (!HasRightJson)
        {
            Summary = "Showing generated JSON output.";
            return;
        }

        string? rightError = null;
        if (!TryParseJson(LeftJson, out var leftRoot, out var leftError) ||
            !TryParseJson(RightJson!, out var rightRoot, out rightError))
        {
            Summary = $"Unable to parse JSON. Left: {leftError} | Right: {rightError}";
            Diffs.Add(new JsonDiffItem("$", "ParseError", leftError, rightError));
            HasDiffs = true;
            return;
        }

        var leftMap = new Dictionary<string, string?>(StringComparer.Ordinal);
        var rightMap = new Dictionary<string, string?>(StringComparer.Ordinal);
        FlattenJson(leftRoot, "$", leftMap);
        FlattenJson(rightRoot, "$", rightMap);

        var allKeys = new SortedSet<string>(leftMap.Keys, StringComparer.Ordinal);
        allKeys.UnionWith(rightMap.Keys);

        foreach (var key in allKeys)
        {
            leftMap.TryGetValue(key, out var leftValue);
            rightMap.TryGetValue(key, out var rightValue);

            if (leftValue == null && rightValue == null) continue;
            if (leftValue == null)
            {
                Diffs.Add(new JsonDiffItem(key, "OnlyInRight", "<missing>", rightValue));
                continue;
            }
            if (rightValue == null)
            {
                Diffs.Add(new JsonDiffItem(key, "OnlyInLeft", leftValue, "<missing>"));
                continue;
            }
            if (!string.Equals(leftValue, rightValue, StringComparison.Ordinal))
            {
                Diffs.Add(new JsonDiffItem(key, "Different", leftValue, rightValue));
            }
        }

        HasDiffs = Diffs.Count > 0;
        Summary = HasDiffs ? $"{Diffs.Count} differences found." : "No differences found.";
    }

    private static bool TryParseJson(string json, out JsonElement root, out string? error)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            root = doc.RootElement.Clone();
            error = null;
            return true;
        }
        catch (Exception ex)
        {
            root = default;
            error = ex.Message;
            return false;
        }
    }

    private static void FlattenJson(JsonElement element, string path, Dictionary<string, string?> map)
    {
        switch (element.ValueKind)
        {
            case JsonValueKind.Object:
                map[path] = "{object}";
                foreach (var prop in element.EnumerateObject())
                {
                    FlattenJson(prop.Value, $"{path}.{prop.Name}", map);
                }
                break;
            case JsonValueKind.Array:
                map[path] = $"[array:{element.GetArrayLength()}]";
                var index = 0;
                foreach (var item in element.EnumerateArray())
                {
                    FlattenJson(item, $"{path}[{index}]", map);
                    index++;
                }
                break;
            case JsonValueKind.String:
                map[path] = $"\"{element.GetString()}\"";
                break;
            case JsonValueKind.Number:
            case JsonValueKind.True:
            case JsonValueKind.False:
            case JsonValueKind.Null:
                map[path] = element.GetRawText();
                break;
            default:
                map[path] = element.ToString();
                break;
        }
    }
}

public sealed record JsonDiffItem(string Path, string Status, string? LeftValue, string? RightValue);
