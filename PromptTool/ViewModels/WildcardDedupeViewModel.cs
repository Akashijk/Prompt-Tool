using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;
using PromptTool.Core.Services;

namespace PromptTool.ViewModels;

public partial class WildcardDedupeViewModel : ObservableObject
{
    private readonly WildcardService _wildcardService;
    private readonly TemplateService _templateService;

    [ObservableProperty] private ObservableCollection<WildcardDuplicatePairItem> _candidatePairs = new();
    [ObservableProperty] private WildcardDuplicatePairItem? _selectedPair;
    [ObservableProperty] private string _statusText = "Scan the wildcard library for likely duplicates.";
    [ObservableProperty] private string _mergeTargetName = string.Empty;
    [ObservableProperty] private string _leftDetailText = string.Empty;
    [ObservableProperty] private string _rightDetailText = string.Empty;
    [ObservableProperty] private string _sharedDetailText = string.Empty;
    [ObservableProperty] private string _leftJson = string.Empty;
    [ObservableProperty] private string _rightJson = string.Empty;
    [ObservableProperty] private bool _isBusy;
    [ObservableProperty] private string? _lastMergedName;

    public WildcardDedupeViewModel(WildcardService wildcardService, TemplateService templateService)
    {
        _wildcardService = wildcardService;
        _templateService = templateService;
    }

    partial void OnSelectedPairChanged(WildcardDuplicatePairItem? value)
    {
        if (value == null)
        {
            MergeTargetName = string.Empty;
            LeftDetailText = string.Empty;
            RightDetailText = string.Empty;
            SharedDetailText = string.Empty;
            LeftJson = string.Empty;
            RightJson = string.Empty;
            return;
        }

        MergeTargetName = value.SuggestedName;
        LeftDetailText = BuildSideDetailText(value.LeftName, value.LeftOnlyChoices, value.LeftOnlyTags);
        RightDetailText = BuildSideDetailText(value.RightName, value.RightOnlyChoices, value.RightOnlyTags);
        SharedDetailText = BuildSharedDetailText(value.SharedChoices, value.SharedTags, value.SharedTemplates);
        LeftJson = value.LeftJson;
        RightJson = value.RightJson;
    }

    [RelayCommand]
    private async Task ScanAsync()
    {
        if (IsBusy)
        {
            return;
        }

        IsBusy = true;
        try
        {
            await RunScanAsync();
        }
        finally
        {
            IsBusy = false;
        }
    }

    public void UseLeftName()
    {
        if (SelectedPair != null)
        {
            MergeTargetName = SelectedPair.LeftName;
        }
    }

    public void UseRightName()
    {
        if (SelectedPair != null)
        {
            MergeTargetName = SelectedPair.RightName;
        }
    }

    public async Task MergeSelectedAsync()
    {
        if (IsBusy || SelectedPair == null)
        {
            return;
        }

        var targetName = MergeTargetName?.Trim();
        if (string.IsNullOrWhiteSpace(targetName))
        {
            StatusText = "Enter a target wildcard name for the merge.";
            return;
        }

        IsBusy = true;
        try
        {
            var entries = (await _wildcardService.GetWildcardFileEntries(includeArchived: true))
                .ToDictionary(e => e.Name, StringComparer.OrdinalIgnoreCase);
            if (!entries.TryGetValue(SelectedPair.LeftName, out var leftEntry) ||
                !entries.TryGetValue(SelectedPair.RightName, out var rightEntry))
            {
                StatusText = "The selected wildcard files are no longer available.";
                return;
            }

            var structured = _wildcardService.GetStructuredWildcards();
            if (!structured.TryGetValue(SelectedPair.LeftName, out var leftStructured) ||
                !structured.TryGetValue(SelectedPair.RightName, out var rightStructured))
            {
                StatusText = "The selected wildcard data is no longer available.";
                return;
            }

            StructuredWildcard merged;
            var addedChoices = 0;
            var dedupedChoices = 0;

            if (structured.TryGetValue(targetName, out var existingTarget) &&
                !string.Equals(targetName, SelectedPair.LeftName, StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(targetName, SelectedPair.RightName, StringComparison.OrdinalIgnoreCase))
            {
                var firstPass = MergeStructuredWildcards(targetName, existingTarget, leftStructured);
                var secondPass = MergeStructuredWildcards(targetName, firstPass.Structured, rightStructured);
                merged = secondPass.Structured;
                addedChoices = firstPass.AddedChoices + secondPass.AddedChoices;
                dedupedChoices = firstPass.DedupedChoices + secondPass.DedupedChoices;
            }
            else
            {
                var first = string.Equals(targetName, SelectedPair.RightName, StringComparison.OrdinalIgnoreCase)
                    ? rightStructured
                    : leftStructured;
                var second = string.Equals(targetName, SelectedPair.RightName, StringComparison.OrdinalIgnoreCase)
                    ? leftStructured
                    : rightStructured;
                var result = MergeStructuredWildcards(targetName, first, second);
                merged = result.Structured;
                addedChoices = result.AddedChoices;
                dedupedChoices = result.DedupedChoices;
            }

            await _wildcardService.SaveWildcardFileContent(targetName, SerializeStructuredWildcard(merged));
            var updatedTemplates = await ReplaceWildcardReferencesInTemplatesAsync(
                SelectedPair.LeftName,
                SelectedPair.RightName,
                targetName);

            if (!string.Equals(targetName, SelectedPair.LeftName, StringComparison.OrdinalIgnoreCase))
            {
                await _wildcardService.DeleteWildcardFileByPath(leftEntry.FilePath);
            }
            if (!string.Equals(targetName, SelectedPair.RightName, StringComparison.OrdinalIgnoreCase))
            {
                await _wildcardService.DeleteWildcardFileByPath(rightEntry.FilePath);
            }

            LastMergedName = targetName;
            var summary = $"Merged '{SelectedPair.LeftName}' and '{SelectedPair.RightName}' into '{targetName}'. Added {addedChoices} new choice(s), folded {dedupedChoices} duplicate choice(s), updated {updatedTemplates} template(s).";
            await RunScanAsync();
            StatusText = summary;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RunScanAsync()
    {
        StatusText = "Scanning wildcard library for likely duplicates...";
        var templateUsage = await BuildTemplateUsageMapAsync();
        var structured = _wildcardService.GetStructuredWildcards()
            .OrderBy(kvp => kvp.Key, StringComparer.OrdinalIgnoreCase)
            .ToList();

        var pairs = new List<WildcardDuplicatePairItem>();
        for (var i = 0; i < structured.Count; i++)
        {
            for (var j = i + 1; j < structured.Count; j++)
            {
                var pair = BuildPair(structured[i].Key, structured[i].Value, structured[j].Key, structured[j].Value, templateUsage);
                if (pair != null)
                {
                    pairs.Add(pair);
                }
            }
        }

        var ordered = pairs
            .OrderByDescending(p => p.Score)
            .ThenBy(p => p.LeftName, StringComparer.OrdinalIgnoreCase)
            .ThenBy(p => p.RightName, StringComparer.OrdinalIgnoreCase)
            .Take(60)
            .ToList();

        CandidatePairs = new ObservableCollection<WildcardDuplicatePairItem>(ordered);
        SelectedPair = ordered.FirstOrDefault();
        StatusText = ordered.Count == 0
            ? "No strong duplicate candidates found."
            : $"Found {ordered.Count} likely duplicate pair(s).";
    }

    private async Task<Dictionary<string, HashSet<string>>> BuildTemplateUsageMapAsync()
    {
        var result = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
        foreach (var templateName in await _templateService.GetTemplateNamesAsync())
        {
            var content = await _templateService.LoadTemplateAsync(templateName);
            if (string.IsNullOrWhiteSpace(content))
            {
                continue;
            }

            foreach (Match match in Regex.Matches(content, @"__([^_]+(?:_[^_]+)*)__"))
            {
                if (!match.Success || match.Groups.Count < 2)
                {
                    continue;
                }

                var wildcardName = match.Groups[1].Value;
                if (!result.TryGetValue(wildcardName, out var templates))
                {
                    templates = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    result[wildcardName] = templates;
                }

                templates.Add(templateName);
            }
        }

        return result;
    }

    private WildcardDuplicatePairItem? BuildPair(
        string leftName,
        StructuredWildcard left,
        string rightName,
        StructuredWildcard right,
        IReadOnlyDictionary<string, HashSet<string>> templateUsage)
    {
        var leftValues = BuildNormalizedValueMap(left);
        var rightValues = BuildNormalizedValueMap(right);
        var sharedValueKeys = leftValues.Keys.Intersect(rightValues.Keys, StringComparer.OrdinalIgnoreCase).ToList();
        var leftOnlyKeys = leftValues.Keys.Except(rightValues.Keys, StringComparer.OrdinalIgnoreCase).ToList();
        var rightOnlyKeys = rightValues.Keys.Except(leftValues.Keys, StringComparer.OrdinalIgnoreCase).ToList();

        var leftTags = BuildNormalizedTagSet(left);
        var rightTags = BuildNormalizedTagSet(right);
        var sharedTags = leftTags.Intersect(rightTags, StringComparer.OrdinalIgnoreCase).ToList();
        var leftOnlyTags = leftTags.Except(rightTags, StringComparer.OrdinalIgnoreCase).ToList();
        var rightOnlyTags = rightTags.Except(leftTags, StringComparer.OrdinalIgnoreCase).ToList();

        var leftTemplates = templateUsage.TryGetValue(leftName, out var leftUsed)
            ? leftUsed
            : new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var rightTemplates = templateUsage.TryGetValue(rightName, out var rightUsed)
            ? rightUsed
            : new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var sharedTemplates = leftTemplates.Intersect(rightTemplates, StringComparer.OrdinalIgnoreCase).ToList();

        var leftNameTokens = TokenizeForSimilarity(leftName);
        var rightNameTokens = TokenizeForSimilarity(rightName);
        var sharedNameTokens = leftNameTokens.Intersect(rightNameTokens, StringComparer.OrdinalIgnoreCase).ToList();
        var leftDescTokens = TokenizeForSimilarity(left.Description);
        var rightDescTokens = TokenizeForSimilarity(right.Description);
        var sharedDescTokens = leftDescTokens.Intersect(rightDescTokens, StringComparer.OrdinalIgnoreCase).ToList();

        var valueRatio = ComputeOverlapRatio(leftValues.Count, rightValues.Count, sharedValueKeys.Count);
        var tagRatio = ComputeOverlapRatio(leftTags.Count, rightTags.Count, sharedTags.Count);
        var templateRatio = ComputeOverlapRatio(leftTemplates.Count, rightTemplates.Count, sharedTemplates.Count);
        var nameRatio = ComputeOverlapRatio(leftNameTokens.Count, rightNameTokens.Count, sharedNameTokens.Count);
        var descriptionRatio = ComputeOverlapRatio(leftDescTokens.Count, rightDescTokens.Count, sharedDescTokens.Count);

        var score = (int)Math.Round(
            (valueRatio * 60.0) +
            (tagRatio * 15.0) +
            (templateRatio * 10.0) +
            (nameRatio * 10.0) +
            (descriptionRatio * 5.0));

        if (score < 22 && sharedValueKeys.Count < 2 && sharedTags.Count == 0 && sharedTemplates.Count == 0)
        {
            return null;
        }

        var summaryParts = new List<string>();
        if (sharedValueKeys.Count > 0)
        {
            summaryParts.Add($"{sharedValueKeys.Count} shared choice(s)");
        }
        if (sharedTags.Count > 0)
        {
            summaryParts.Add($"{sharedTags.Count} shared tag(s)");
        }
        if (sharedTemplates.Count > 0)
        {
            summaryParts.Add($"{sharedTemplates.Count} shared template(s)");
        }
        if (summaryParts.Count == 0)
        {
            summaryParts.Add($"Name overlap: {string.Join(", ", sharedNameTokens.Take(3))}");
        }

        return new WildcardDuplicatePairItem
        {
            LeftName = leftName,
            RightName = rightName,
            Score = score,
            ScoreText = $"{Math.Clamp(score, 0, 99)}% match",
            Summary = string.Join(" | ", summaryParts),
            SuggestedName = ChooseSuggestedName(leftName, left, leftTemplates.Count, rightName, right, rightTemplates.Count),
            SharedChoices = sharedValueKeys.Select(key => leftValues[key]).OrderBy(v => v, StringComparer.OrdinalIgnoreCase).ToList(),
            LeftOnlyChoices = leftOnlyKeys.Select(key => leftValues[key]).OrderBy(v => v, StringComparer.OrdinalIgnoreCase).ToList(),
            RightOnlyChoices = rightOnlyKeys.Select(key => rightValues[key]).OrderBy(v => v, StringComparer.OrdinalIgnoreCase).ToList(),
            SharedTags = sharedTags.OrderBy(v => v, StringComparer.OrdinalIgnoreCase).ToList(),
            LeftOnlyTags = leftOnlyTags.OrderBy(v => v, StringComparer.OrdinalIgnoreCase).ToList(),
            RightOnlyTags = rightOnlyTags.OrderBy(v => v, StringComparer.OrdinalIgnoreCase).ToList(),
            SharedTemplates = sharedTemplates.OrderBy(v => v, StringComparer.OrdinalIgnoreCase).ToList(),
            LeftJson = SerializeStructuredWildcard(left),
            RightJson = SerializeStructuredWildcard(right)
        };
    }

    private static string ChooseSuggestedName(
        string leftName,
        StructuredWildcard left,
        int leftTemplateCount,
        string rightName,
        StructuredWildcard right,
        int rightTemplateCount)
    {
        if (leftTemplateCount != rightTemplateCount)
        {
            return leftTemplateCount > rightTemplateCount ? leftName : rightName;
        }

        if (left.Choices.Count != right.Choices.Count)
        {
            return left.Choices.Count >= right.Choices.Count ? leftName : rightName;
        }

        if (leftName.Length != rightName.Length)
        {
            return leftName.Length <= rightName.Length ? leftName : rightName;
        }

        return string.Compare(leftName, rightName, StringComparison.OrdinalIgnoreCase) <= 0 ? leftName : rightName;
    }

    private async Task<int> ReplaceWildcardReferencesInTemplatesAsync(string leftName, string rightName, string targetName)
    {
        var updated = 0;
        var leftToken = $"__{leftName}__";
        var rightToken = $"__{rightName}__";
        var targetToken = $"__{targetName}__";

        foreach (var templateName in await _templateService.GetTemplateNamesAsync())
        {
            var content = await _templateService.LoadTemplateAsync(templateName);
            if (string.IsNullOrWhiteSpace(content))
            {
                continue;
            }

            var replaced = content;
            replaced = ReplaceIgnoreCase(replaced, leftToken, targetToken);
            replaced = ReplaceIgnoreCase(replaced, rightToken, targetToken);

            if (string.Equals(replaced, content, StringComparison.Ordinal))
            {
                continue;
            }

            await _templateService.SaveTemplateAsync(templateName, replaced);
            updated++;
        }

        return updated;
    }

    private static MergeResult MergeStructuredWildcards(string targetName, StructuredWildcard primary, StructuredWildcard secondary)
    {
        var merged = new StructuredWildcard
        {
            Name = targetName,
            Description = !string.IsNullOrWhiteSpace(primary.Description) ? primary.Description : secondary.Description,
            Includes = primary.Includes ?? secondary.Includes
        };

        var choices = new List<WildcardChoice>();
        var choiceMap = new Dictionary<string, WildcardChoice>(StringComparer.OrdinalIgnoreCase);
        var added = 0;
        var deduped = 0;

        foreach (var choice in primary.Choices)
        {
            var clone = CloneChoice(choice);
            choices.Add(clone);
            var key = NormalizeWhitespace(clone.Value);
            if (!string.IsNullOrWhiteSpace(key))
            {
                choiceMap[key] = clone;
            }
        }

        foreach (var choice in secondary.Choices)
        {
            var key = NormalizeWhitespace(choice.Value);
            if (string.IsNullOrWhiteSpace(key))
            {
                continue;
            }

            if (choiceMap.TryGetValue(key, out var existing))
            {
                MergeChoiceMetadata(existing, choice);
                deduped++;
                continue;
            }

            var clone = CloneChoice(choice);
            choices.Add(clone);
            choiceMap[key] = clone;
            added++;
        }

        merged.Choices = choices;
        return new MergeResult(merged, added, deduped);
    }

    private static Dictionary<string, string> BuildNormalizedValueMap(StructuredWildcard wildcard)
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var choice in wildcard.Choices)
        {
            var key = NormalizeWhitespace(choice.Value).ToLowerInvariant();
            if (string.IsNullOrWhiteSpace(key) || map.ContainsKey(key))
            {
                continue;
            }

            map[key] = choice.Value.Trim();
        }

        return map;
    }

    private static HashSet<string> BuildNormalizedTagSet(StructuredWildcard wildcard)
    {
        return wildcard.Choices
            .SelectMany(choice => choice.Tags ?? new List<string>())
            .Select(tag => NormalizeWhitespace(tag).ToLowerInvariant())
            .Where(tag => !string.IsNullOrWhiteSpace(tag))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    private static double ComputeOverlapRatio(int leftCount, int rightCount, int sharedCount)
    {
        var union = leftCount + rightCount - sharedCount;
        if (union <= 0)
        {
            return 0;
        }

        return sharedCount / (double)union;
    }

    private static HashSet<string> TokenizeForSimilarity(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        }

        return text
            .Split(new[] { ' ', '_', '-', ',', '.', ';', ':', '\n', '\r', '\t', '/', '\\', '(', ')', '[', ']' }, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(token => token.Length >= 3)
            .Select(token => token.ToLowerInvariant())
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    private static string BuildSideDetailText(string name, IReadOnlyList<string> choices, IReadOnlyList<string> tags)
    {
        var lines = new List<string>
        {
            $"{name}",
            $"Unique choices: {choices.Count}"
        };

        if (choices.Count > 0)
        {
            lines.Add(string.Empty);
            lines.AddRange(choices.Take(20).Select(choice => $"- {choice}"));
            if (choices.Count > 20)
            {
                lines.Add($"... and {choices.Count - 20} more");
            }
        }

        if (tags.Count > 0)
        {
            lines.Add(string.Empty);
            lines.Add($"Unique tags: {string.Join(", ", tags.Take(10))}");
        }

        return string.Join(Environment.NewLine, lines);
    }

    private static string BuildSharedDetailText(
        IReadOnlyList<string> sharedChoices,
        IReadOnlyList<string> sharedTags,
        IReadOnlyList<string> sharedTemplates)
    {
        var lines = new List<string>
        {
            $"Shared choices: {sharedChoices.Count}"
        };

        if (sharedChoices.Count > 0)
        {
            lines.Add(string.Empty);
            lines.AddRange(sharedChoices.Take(24).Select(choice => $"- {choice}"));
            if (sharedChoices.Count > 24)
            {
                lines.Add($"... and {sharedChoices.Count - 24} more");
            }
        }

        if (sharedTags.Count > 0)
        {
            lines.Add(string.Empty);
            lines.Add($"Shared tags: {string.Join(", ", sharedTags.Take(10))}");
        }

        if (sharedTemplates.Count > 0)
        {
            lines.Add(string.Empty);
            lines.Add($"Shared templates: {string.Join(", ", sharedTemplates.Take(8))}");
        }

        return string.Join(Environment.NewLine, lines);
    }

    private static string SerializeStructuredWildcard(StructuredWildcard structured)
    {
        var payload = new
        {
            description = string.IsNullOrWhiteSpace(structured.Description) ? null : structured.Description,
            includes = structured.Includes,
            choices = structured.Choices.Select(choice => new
            {
                value = choice.Value,
                weight = choice.Weight,
                tags = choice.Tags?.Where(tag => !string.IsNullOrWhiteSpace(tag)).Distinct(StringComparer.OrdinalIgnoreCase).ToList(),
                includes = choice.Includes,
                requires = ParseRequires(choice.RequiresJson)
            }).ToList()
        };

        return JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
    }

    private static WildcardChoice CloneChoice(WildcardChoice choice)
    {
        return new WildcardChoice
        {
            Value = choice.Value,
            Weight = choice.Weight,
            Tags = choice.Tags?.Where(tag => !string.IsNullOrWhiteSpace(tag)).Distinct(StringComparer.OrdinalIgnoreCase).ToList() ?? new List<string>(),
            Includes = CloneIncludes(choice.Includes),
            RequiresJson = choice.RequiresJson
        };
    }

    private static object? CloneIncludes(object? includes)
    {
        return includes switch
        {
            null => null,
            string text => text,
            IEnumerable<string> values => values.Where(value => !string.IsNullOrWhiteSpace(value)).Distinct(StringComparer.OrdinalIgnoreCase).ToList(),
            _ => includes
        };
    }

    private static void MergeChoiceMetadata(WildcardChoice target, WildcardChoice source)
    {
        target.Weight = Math.Max(target.Weight, source.Weight);
        target.Tags = target.Tags
            .Concat(source.Tags ?? new List<string>())
            .Where(tag => !string.IsNullOrWhiteSpace(tag))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        target.Includes = MergeIncludes(target.Includes, source.Includes);
        if (string.IsNullOrWhiteSpace(target.RequiresJson) && !string.IsNullOrWhiteSpace(source.RequiresJson))
        {
            target.RequiresJson = source.RequiresJson;
        }
    }

    private static object? MergeIncludes(object? left, object? right)
    {
        var values = new List<string>();

        void Add(object? includes)
        {
            switch (includes)
            {
                case null:
                    return;
                case string text when !string.IsNullOrWhiteSpace(text):
                    values.Add(text.Trim());
                    break;
                case IEnumerable<string> list:
                    values.AddRange(list.Where(item => !string.IsNullOrWhiteSpace(item)).Select(item => item.Trim()));
                    break;
            }
        }

        Add(left);
        Add(right);

        var distinct = values
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        return distinct.Count switch
        {
            0 => null,
            1 => distinct[0],
            _ => distinct
        };
    }

    private static object? ParseRequires(string? requires)
    {
        if (string.IsNullOrWhiteSpace(requires))
        {
            return null;
        }

        try
        {
            return JsonSerializer.Deserialize<JsonElement>(requires);
        }
        catch
        {
            return requires;
        }
    }

    private static string ReplaceIgnoreCase(string input, string search, string replacement)
    {
        if (string.IsNullOrEmpty(input) || string.IsNullOrEmpty(search))
        {
            return input;
        }

        return Regex.Replace(input, Regex.Escape(search), replacement ?? string.Empty, RegexOptions.IgnoreCase);
    }

    private static string NormalizeWhitespace(string input)
    {
        if (string.IsNullOrWhiteSpace(input))
        {
            return string.Empty;
        }

        return Regex.Replace(input.Trim(), @"\s+", " ");
    }
}

public sealed class WildcardDuplicatePairItem
{
    public string LeftName { get; init; } = string.Empty;
    public string RightName { get; init; } = string.Empty;
    public int Score { get; init; }
    public string ScoreText { get; init; } = string.Empty;
    public string Summary { get; init; } = string.Empty;
    public string SuggestedName { get; init; } = string.Empty;
    public IReadOnlyList<string> SharedChoices { get; init; } = Array.Empty<string>();
    public IReadOnlyList<string> LeftOnlyChoices { get; init; } = Array.Empty<string>();
    public IReadOnlyList<string> RightOnlyChoices { get; init; } = Array.Empty<string>();
    public IReadOnlyList<string> SharedTags { get; init; } = Array.Empty<string>();
    public IReadOnlyList<string> LeftOnlyTags { get; init; } = Array.Empty<string>();
    public IReadOnlyList<string> RightOnlyTags { get; init; } = Array.Empty<string>();
    public IReadOnlyList<string> SharedTemplates { get; init; } = Array.Empty<string>();
    public string LeftJson { get; init; } = string.Empty;
    public string RightJson { get; init; } = string.Empty;
}

public sealed record MergeResult(StructuredWildcard Structured, int AddedChoices, int DedupedChoices);
