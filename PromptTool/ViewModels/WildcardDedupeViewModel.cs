using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;
using PromptTool.Core.Services;

namespace PromptTool.ViewModels;

public partial class WildcardDedupeViewModel : ObservableObject
{
    private readonly WildcardService _wildcardService;
    private readonly TemplateService _templateService;
    private const int DefaultMinimumScore = 35;

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
    [ObservableProperty] private int _minimumScore = DefaultMinimumScore;
    [ObservableProperty] private double _scanProgressPercent;
    [ObservableProperty] private string _scanProgressText = string.Empty;

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
        SharedDetailText = BuildSharedDetailText(value.SharedChoices, value.NearDuplicateChoicePairs, value.SharedTags, value.SharedTemplates);
        LeftJson = value.LeftJson;
        RightJson = value.RightJson;
    }

    partial void OnMinimumScoreChanged(int value)
    {
        if (value < 0)
        {
            MinimumScore = 0;
            return;
        }

        if (value > 100)
        {
            MinimumScore = 100;
            return;
        }
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

        var mergedPair = SelectedPair;
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
            if (!entries.TryGetValue(mergedPair.LeftName, out var leftEntry) ||
                !entries.TryGetValue(mergedPair.RightName, out var rightEntry))
            {
                StatusText = "The selected wildcard files are no longer available.";
                return;
            }

            var structured = _wildcardService.GetStructuredWildcards();
            if (!structured.TryGetValue(mergedPair.LeftName, out var leftStructured) ||
                !structured.TryGetValue(mergedPair.RightName, out var rightStructured))
            {
                StatusText = "The selected wildcard data is no longer available.";
                return;
            }

            StructuredWildcard merged;
            var addedChoices = 0;
            var dedupedChoices = 0;

            if (structured.TryGetValue(targetName, out var existingTarget) &&
                !string.Equals(targetName, mergedPair.LeftName, StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(targetName, mergedPair.RightName, StringComparison.OrdinalIgnoreCase))
            {
                var firstPass = MergeStructuredWildcards(targetName, existingTarget, leftStructured);
                var secondPass = MergeStructuredWildcards(targetName, firstPass.Structured, rightStructured);
                merged = secondPass.Structured;
                addedChoices = firstPass.AddedChoices + secondPass.AddedChoices;
                dedupedChoices = firstPass.DedupedChoices + secondPass.DedupedChoices;
            }
            else
            {
                var first = string.Equals(targetName, mergedPair.RightName, StringComparison.OrdinalIgnoreCase)
                    ? rightStructured
                    : leftStructured;
                var second = string.Equals(targetName, mergedPair.RightName, StringComparison.OrdinalIgnoreCase)
                    ? leftStructured
                    : rightStructured;
                var result = MergeStructuredWildcards(targetName, first, second);
                merged = result.Structured;
                addedChoices = result.AddedChoices;
                dedupedChoices = result.DedupedChoices;
            }

            await _wildcardService.SaveWildcardFileContent(targetName, SerializeStructuredWildcard(merged));
            var updatedTemplates = await ReplaceWildcardReferencesInTemplatesAsync(
                mergedPair.LeftName,
                mergedPair.RightName,
                targetName);

            if (!string.Equals(targetName, mergedPair.LeftName, StringComparison.OrdinalIgnoreCase))
            {
                await _wildcardService.DeleteWildcardFileByPath(leftEntry.FilePath);
            }
            if (!string.Equals(targetName, mergedPair.RightName, StringComparison.OrdinalIgnoreCase))
            {
                await _wildcardService.DeleteWildcardFileByPath(rightEntry.FilePath);
            }

            LastMergedName = targetName;
            var summary = $"Merged '{mergedPair.LeftName}' and '{mergedPair.RightName}' into '{targetName}'. Added {addedChoices} new choice(s), folded {dedupedChoices} duplicate choice(s), updated {updatedTemplates} template(s).";
            RemoveMergedCandidates(mergedPair, targetName);
            StatusText = summary;
            ScanProgressPercent = 100;
            ScanProgressText = CandidatePairs.Count == 0
                ? "Merge complete. No remaining candidate pairs in the current results list."
                : $"Merge complete. {CandidatePairs.Count} candidate pair(s) remain in the current results list.";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void RemoveMergedCandidates(WildcardDuplicatePairItem mergedPair, string targetName)
    {
        var remaining = CandidatePairs
            .Where(pair =>
                !PairReferencesName(pair, mergedPair.LeftName) &&
                !PairReferencesName(pair, mergedPair.RightName) &&
                !PairReferencesName(pair, targetName))
            .ToList();

        CandidatePairs = new ObservableCollection<WildcardDuplicatePairItem>(remaining);
        SelectedPair = remaining.FirstOrDefault();
    }

    private static bool PairReferencesName(WildcardDuplicatePairItem pair, string name)
    {
        return string.Equals(pair.LeftName, name, StringComparison.OrdinalIgnoreCase) ||
               string.Equals(pair.RightName, name, StringComparison.OrdinalIgnoreCase);
    }

    private async Task RunScanAsync()
    {
        StatusText = $"Scanning wildcard library for likely duplicates at {MinimumScore}%+...";
        ScanProgressPercent = 0;
        ScanProgressText = "Preparing scan...";
        var templateUsage = await BuildTemplateUsageMapAsync();
        var structured = _wildcardService.GetStructuredWildcards()
            .OrderBy(kvp => kvp.Key, StringComparer.OrdinalIgnoreCase)
            .ToList();

        var ordered = await Task.Run(() => BuildCandidatePairs(structured, templateUsage));

        CandidatePairs = new ObservableCollection<WildcardDuplicatePairItem>(ordered);
        SelectedPair = ordered.FirstOrDefault();
        StatusText = ordered.Count == 0
            ? $"No strong duplicate candidates found at {MinimumScore}%+."
            : $"Found {ordered.Count} likely duplicate pair(s) at {MinimumScore}%+.";
        ScanProgressPercent = 100;
        ScanProgressText = ordered.Count == 0
            ? "Scan finished. No candidates met the current threshold."
            : $"Scan finished. Showing {ordered.Count} strongest candidate pairs.";
    }

    private List<WildcardDuplicatePairItem> BuildCandidatePairs(
        IReadOnlyList<KeyValuePair<string, StructuredWildcard>> structured,
        IReadOnlyDictionary<string, HashSet<string>> templateUsage)
    {
        var pairs = new List<WildcardDuplicatePairItem>();
        var totalWildcards = structured.Count;
        var totalPairs = totalWildcards <= 1 ? 0 : (totalWildcards * (totalWildcards - 1)) / 2;
        var processedPairs = 0;

        void ReportProgress()
        {
            var percent = totalPairs == 0 ? 100 : (processedPairs / (double)totalPairs) * 100.0;
            Dispatcher.UIThread.Post(() =>
            {
                ScanProgressPercent = percent;
                ScanProgressText = $"Compared {processedPairs:N0} of {totalPairs:N0} wildcard pairs. Found {pairs.Count:N0} candidate(s) so far.";
            });
        }

        ReportProgress();
        for (var i = 0; i < structured.Count; i++)
        {
            for (var j = i + 1; j < structured.Count; j++)
            {
                var pair = BuildPair(structured[i].Key, structured[i].Value, structured[j].Key, structured[j].Value, templateUsage);
                if (pair != null)
                {
                    pairs.Add(pair);
                }

                processedPairs++;
                if (processedPairs == totalPairs || processedPairs % 200 == 0)
                {
                    ReportProgress();
                }
            }
        }

        return pairs
            .OrderByDescending(p => p.Score)
            .ThenByDescending(p => p.SharedChoices.Count + p.NearDuplicateChoicePairs.Count)
            .ThenBy(p => p.LeftName, StringComparer.OrdinalIgnoreCase)
            .ThenBy(p => p.RightName, StringComparer.OrdinalIgnoreCase)
            .Take(60)
            .ToList();
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
        var nearDuplicatePairs = BuildNearDuplicateChoicePairs(leftValues, rightValues, sharedValueKeys);

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
        var nameCoverage = ComputeTokenCoverage(leftNameTokens, rightNameTokens);
        var descriptionCoverage = ComputeTokenCoverage(leftDescTokens, rightDescTokens);
        var combinedKeywordCoverage = ComputeTokenCoverage(
            leftNameTokens.Union(leftDescTokens, StringComparer.OrdinalIgnoreCase).ToHashSet(StringComparer.OrdinalIgnoreCase),
            rightNameTokens.Union(rightDescTokens, StringComparer.OrdinalIgnoreCase).ToHashSet(StringComparer.OrdinalIgnoreCase));

        var exactValueRatio = ComputeOverlapRatio(leftValues.Count, rightValues.Count, sharedValueKeys.Count);
        var matchedValueCount = sharedValueKeys.Count + (nearDuplicatePairs.Count * 0.75);
        var valueCoverage = ComputeCoverageRatio(leftValues.Count, rightValues.Count, matchedValueCount);
        var tagRatio = ComputeOverlapRatio(leftTags.Count, rightTags.Count, sharedTags.Count);
        var templateRatio = ComputeOverlapRatio(leftTemplates.Count, rightTemplates.Count, sharedTemplates.Count);
        var nameRatio = Math.Max(ComputeOverlapRatio(leftNameTokens.Count, rightNameTokens.Count, sharedNameTokens.Count), nameCoverage);
        var descriptionRatio = Math.Max(ComputeOverlapRatio(leftDescTokens.Count, rightDescTokens.Count, sharedDescTokens.Count), descriptionCoverage);
        var semanticChoiceCoverage = ComputeNearDuplicateChoiceCoverage(leftValues, rightValues);

        var score = (int)Math.Round(
            (valueCoverage * 38.0) +
            (exactValueRatio * 20.0) +
            (semanticChoiceCoverage * 16.0) +
            (tagRatio * 8.0) +
            (templateRatio * 5.0) +
            (nameRatio * 5.0) +
            (descriptionRatio * 4.0) +
            (combinedKeywordCoverage * 4.0));

        var hasStrongContentOverlap =
            sharedValueKeys.Count >= 2 ||
            nearDuplicatePairs.Count >= 2 ||
            (sharedValueKeys.Count >= 1 && nearDuplicatePairs.Count >= 1);
        var hasSupportingSignals =
            sharedTags.Count > 0 ||
            sharedTemplates.Count > 0 ||
            sharedNameTokens.Count >= 2 ||
            sharedDescTokens.Count >= 2 ||
            nameCoverage >= 0.5 ||
            descriptionCoverage >= 0.45 ||
            combinedKeywordCoverage >= 0.45;
        var hasSemanticContentOverlap = semanticChoiceCoverage >= 0.5 || (semanticChoiceCoverage >= 0.35 && combinedKeywordCoverage >= 0.45);
        var hasStrongMetadataOverlap = combinedKeywordCoverage >= 0.6 && (nameCoverage >= 0.45 || descriptionCoverage >= 0.45);

        if ((!hasStrongContentOverlap && !hasSupportingSignals && !hasSemanticContentOverlap && !hasStrongMetadataOverlap) || score < MinimumScore)
        {
            return null;
        }

        var summaryParts = new List<string>();
        if (sharedValueKeys.Count > 0)
        {
            summaryParts.Add($"{sharedValueKeys.Count} shared choice(s)");
        }
        if (nearDuplicatePairs.Count > 0)
        {
            summaryParts.Add($"{nearDuplicatePairs.Count} near-duplicate choice pair(s)");
        }
        if (sharedTags.Count > 0)
        {
            summaryParts.Add($"{sharedTags.Count} shared tag(s)");
        }
        if (sharedTemplates.Count > 0)
        {
            summaryParts.Add($"{sharedTemplates.Count} shared template(s)");
        }
        if (descriptionCoverage >= 0.45 && sharedDescTokens.Count > 0)
        {
            summaryParts.Add($"similar summaries: {string.Join(", ", sharedDescTokens.Take(3))}");
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
            NearDuplicateChoicePairs = nearDuplicatePairs,
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

    private static double ComputeCoverageRatio(int leftCount, int rightCount, double matchedCount)
    {
        var smaller = Math.Min(leftCount, rightCount);
        if (smaller <= 0)
        {
            return 0;
        }

        return Math.Min(1, matchedCount / smaller);
    }

    private static double ComputeTokenCoverage(IReadOnlyCollection<string> leftTokens, IReadOnlyCollection<string> rightTokens)
    {
        if (leftTokens.Count == 0 || rightTokens.Count == 0)
        {
            return 0;
        }

        var shared = leftTokens.Intersect(rightTokens, StringComparer.OrdinalIgnoreCase).Count();
        var smaller = Math.Min(leftTokens.Count, rightTokens.Count);
        return smaller == 0 ? 0 : shared / (double)smaller;
    }

    private static List<string> BuildNearDuplicateChoicePairs(
        IReadOnlyDictionary<string, string> leftValues,
        IReadOnlyDictionary<string, string> rightValues,
        IReadOnlyCollection<string> exactSharedKeys)
    {
        var pairs = new List<string>();
        var usedRight = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var left in leftValues)
        {
            if (exactSharedKeys.Contains(left.Key))
            {
                continue;
            }

            foreach (var right in rightValues)
            {
                if (exactSharedKeys.Contains(right.Key) || usedRight.Contains(right.Key))
                {
                    continue;
                }

                if (!AreNearDuplicateChoices(left.Value, right.Value))
                {
                    continue;
                }

                pairs.Add($"{left.Value} <-> {right.Value}");
                usedRight.Add(right.Key);
                break;
            }
        }

        return pairs.OrderBy(pair => pair, StringComparer.OrdinalIgnoreCase).ToList();
    }

    private static double ComputeNearDuplicateChoiceCoverage(
        IReadOnlyDictionary<string, string> leftValues,
        IReadOnlyDictionary<string, string> rightValues)
    {
        if (leftValues.Count == 0 || rightValues.Count == 0)
        {
            return 0;
        }

        var matched = 0;
        var usedRight = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var left in leftValues)
        {
            var bestRight = rightValues
                .Where(right => !usedRight.Contains(right.Key))
                .Select(right => new { right.Key, Score = ComputeChoiceSimilarity(left.Value, right.Value) })
                .OrderByDescending(item => item.Score)
                .FirstOrDefault();

            if (bestRight == null || bestRight.Score < 0.74)
            {
                continue;
            }

            usedRight.Add(bestRight.Key);
            matched++;
        }

        return matched / (double)Math.Min(leftValues.Count, rightValues.Count);
    }

    private static bool AreNearDuplicateChoices(string left, string right)
    {
        var similarity = ComputeChoiceSimilarity(left, right);
        if (similarity >= 0.8)
        {
            return true;
        }

        var leftKey = BuildCanonicalChoiceKey(left);
        var rightKey = BuildCanonicalChoiceKey(right);
        if (string.IsNullOrWhiteSpace(leftKey) || string.IsNullOrWhiteSpace(rightKey))
        {
            return false;
        }

        if (string.Equals(leftKey, rightKey, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        var leftTokens = leftKey.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var rightTokens = rightKey.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (leftTokens.Length < 2 || rightTokens.Length < 2)
        {
            return false;
        }

        var shorter = leftTokens.Length <= rightTokens.Length ? leftTokens : rightTokens;
        var longer = leftTokens.Length <= rightTokens.Length ? rightTokens : leftTokens;
        var shorterSet = shorter.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var longerSet = longer.ToHashSet(StringComparer.OrdinalIgnoreCase);

        return shorterSet.IsSubsetOf(longerSet) && longerSet.Count - shorterSet.Count <= 2;
    }

    private static double ComputeChoiceSimilarity(string left, string right)
    {
        var leftKey = BuildCanonicalChoiceKey(left);
        var rightKey = BuildCanonicalChoiceKey(right);
        if (string.IsNullOrWhiteSpace(leftKey) || string.IsNullOrWhiteSpace(rightKey))
        {
            return 0;
        }

        if (string.Equals(leftKey, rightKey, StringComparison.OrdinalIgnoreCase))
        {
            return 1;
        }

        var leftTokens = leftKey.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var rightTokens = rightKey.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var leftSet = leftTokens.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var rightSet = rightTokens.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var tokenCoverage = ComputeTokenCoverage(leftSet, rightSet);

        var leftChars = BuildCharacterTrigrams(leftKey);
        var rightChars = BuildCharacterTrigrams(rightKey);
        var trigramOverlap = ComputeTokenCoverage(leftChars, rightChars);

        return Math.Max(tokenCoverage, trigramOverlap);
    }

    private static HashSet<string> BuildCharacterTrigrams(string text)
    {
        var normalized = $"  {text.Trim().ToLowerInvariant()}  ";
        var grams = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (normalized.Length < 3)
        {
            grams.Add(normalized);
            return grams;
        }

        for (var i = 0; i <= normalized.Length - 3; i++)
        {
            grams.Add(normalized.Substring(i, 3));
        }

        return grams;
    }

    private static string BuildCanonicalChoiceKey(string input)
    {
        var normalized = NormalizeWhitespace(input).ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(normalized))
        {
            return string.Empty;
        }

        normalized = Regex.Replace(normalized, @"^(a|an|the)\s+", string.Empty, RegexOptions.IgnoreCase);
        normalized = Regex.Replace(normalized, @"[^a-z0-9\s]", " ");
        normalized = Regex.Replace(normalized, @"\s+", " ").Trim();
        return normalized;
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
        IReadOnlyList<string> nearDuplicateChoicePairs,
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

        if (nearDuplicateChoicePairs.Count > 0)
        {
            lines.Add(string.Empty);
            lines.Add($"Near-duplicate choices: {nearDuplicateChoicePairs.Count}");
            lines.AddRange(nearDuplicateChoicePairs.Take(18).Select(pair => $"- {pair}"));
            if (nearDuplicateChoicePairs.Count > 18)
            {
                lines.Add($"... and {nearDuplicateChoicePairs.Count - 18} more");
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
    public IReadOnlyList<string> NearDuplicateChoicePairs { get; init; } = Array.Empty<string>();
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
