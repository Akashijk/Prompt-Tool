using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Linq;
using CommunityToolkit.Mvvm.ComponentModel;
using Avalonia;
using Avalonia.Collections;
using PromptTool.Core.Models;
using PromptTool.Core.Services;

namespace PromptTool.ViewModels;

public partial class KpiDashboardViewModel : ObservableObject
{
    private readonly HistoryManagerService _history;
    private readonly KpiStatsService? _statsService;
    private readonly string? _workflow;

    public ObservableCollection<string> TimeRanges { get; } = new()
    {
        "All time",
        "Last 30 days",
        "Last 7 days",
        "Today"
    };

    [ObservableProperty] private string _workflowLabel = "";
    [ObservableProperty] private string _selectedTimeRange = "All time";
    [ObservableProperty] private bool _scoredOnly;
    [ObservableProperty] private bool _hideFailed;

    public ObservableCollection<KpiMetric> Metrics { get; } = new();
    public ObservableCollection<KpiBarChart> Charts { get; } = new();
    public ObservableCollection<KpiBarChart> Histograms { get; } = new();
    public ObservableCollection<KpiTrendChart> TrendCharts { get; } = new();
    public ObservableCollection<KpiScatterChart> ScatterCharts { get; } = new();
    public ObservableCollection<KpiLeaderboard> Leaderboards { get; } = new();

    public KpiDashboardViewModel(HistoryManagerService history, string? workflow, KpiStatsService? statsService = null)
    {
        _history = history;
        _workflow = string.IsNullOrWhiteSpace(workflow) ? null : workflow.Trim();
        _statsService = statsService;
        WorkflowLabel = string.IsNullOrWhiteSpace(_workflow) ? "Workflow: All" : $"Workflow: {_workflow}";
        Refresh();
    }

    partial void OnSelectedTimeRangeChanged(string value) => Refresh();
    partial void OnScoredOnlyChanged(bool value) => Refresh();
    partial void OnHideFailedChanged(bool value) => Refresh();

    private void Refresh()
    {
        Metrics.Clear();
        Charts.Clear();
        Histograms.Clear();
        TrendCharts.Clear();
        ScatterCharts.Clear();
        Leaderboards.Clear();

        var entries = _history.GetAllEntries();
        var images = entries
            .SelectMany(entry => entry.Images.Select(image => (entry, image)))
            .Where(pair => WorkflowMatches(pair.entry, pair.image, _workflow))
            .Where(pair => MatchesTimeRange(pair.entry, SelectedTimeRange))
            .ToList();

        if (ScoredOnly)
        {
            images = images.Where(pair => pair.image.AestheticScore.HasValue).ToList();
        }

        if (HideFailed)
        {
            images = images.Where(pair => !IsFailed(pair.image)).ToList();
        }

        var useStats = SelectedTimeRange == "All time" && !ScoredOnly && !HideFailed;
        var stats = useStats ? _statsService?.GetSnapshot() : null;
        var statsModels = stats?.Models.Values
            .Where(m => WorkflowMatches(m.Workflow, _workflow))
            .ToList() ?? new List<ModelKpiStats>();
        var statsLoras = stats?.Loras.Values
            .Where(l => WorkflowMatches(l.Workflow, _workflow))
            .ToList() ?? new List<LoraKpiStats>();
        var statsLoraBuckets = stats?.LoraCountBuckets.Values
            .Where(b => WorkflowMatches(b.Workflow, _workflow))
            .ToList() ?? new List<LoraCountKpiStats>();

        var totalImages = images.Count;
        var totalEntries = entries.Count(entry => entry.Images.Any(image => WorkflowMatches(entry, image, _workflow)));

        var modelGroups = new Dictionary<string, List<HistoryImage>>(StringComparer.OrdinalIgnoreCase);
        var modelAesthetic = new Dictionary<string, List<double>>(StringComparer.OrdinalIgnoreCase);
        var modelComposite = new Dictionary<string, List<double>>(StringComparer.OrdinalIgnoreCase);
        var modelDurations = new Dictionary<string, List<int>>(StringComparer.OrdinalIgnoreCase);
        var modelTokens = new Dictionary<string, List<int>>(StringComparer.OrdinalIgnoreCase);
        var modelFailures = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var modelFavorites = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var schedulerStats = new Dictionary<string, List<HistoryImage>>(StringComparer.OrdinalIgnoreCase);
        var stepStats = new Dictionary<int, List<HistoryImage>>();
        var loraCountStats = new Dictionary<int, List<HistoryImage>>();
        var loraUsage = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var aestheticScores = new List<double>();
        var heuristicScores = new List<double>();
        var sharpnessScores = new List<double>();
        var compositeScores = new List<double>();
        var promptMatchScores = new List<double>();
        var durationAll = new List<int>();
        var failuresAll = 0;
        var favoritesAll = 0;

        foreach (var (entry, image) in images)
        {
            var modelName = ResolveModelName(entry, image);
            if (!string.IsNullOrWhiteSpace(modelName))
            {
                if (!modelGroups.TryGetValue(modelName, out var list))
                {
                    list = new List<HistoryImage>();
                    modelGroups[modelName] = list;
                }
                list.Add(image);
            }

            if (image.AestheticScore.HasValue)
            {
                aestheticScores.Add(image.AestheticScore.Value);
                if (!string.IsNullOrWhiteSpace(modelName))
                {
                    if (!modelAesthetic.TryGetValue(modelName, out var scores))
                    {
                        scores = new List<double>();
                        modelAesthetic[modelName] = scores;
                    }
                    scores.Add(image.AestheticScore.Value);
                }
            }

            if (image.HeuristicScore.HasValue)
            {
                heuristicScores.Add(image.HeuristicScore.Value);
            }

            if (image.SharpnessScore.HasValue)
            {
                sharpnessScores.Add(image.SharpnessScore.Value);
            }

            if (image.PromptMatchScore.HasValue)
            {
                promptMatchScores.Add(image.PromptMatchScore.Value);
            }

            if (image.CompositeScore.HasValue)
            {
                compositeScores.Add(image.CompositeScore.Value);
                if (!string.IsNullOrWhiteSpace(modelName))
                {
                    if (!modelComposite.TryGetValue(modelName, out var scores))
                    {
                        scores = new List<double>();
                        modelComposite[modelName] = scores;
                    }
                    scores.Add(image.CompositeScore.Value);
                }
            }

            var duration = ResolveDurationMs(image);
            if (duration.HasValue)
            {
                durationAll.Add(duration.Value);
                if (!string.IsNullOrWhiteSpace(modelName))
                {
                    if (!modelDurations.TryGetValue(modelName, out var durations))
                    {
                        durations = new List<int>();
                        modelDurations[modelName] = durations;
                    }
                    durations.Add(duration.Value);
                }
            }

            var tokens = EstimateTokenCount(entry, image);
            if (tokens > 0 && !string.IsNullOrWhiteSpace(modelName))
            {
                if (!modelTokens.TryGetValue(modelName, out var tokenList))
                {
                    tokenList = new List<int>();
                    modelTokens[modelName] = tokenList;
                }
                tokenList.Add(tokens);
            }

            if (IsFailed(image))
            {
                failuresAll++;
                if (!string.IsNullOrWhiteSpace(modelName))
                {
                    if (!modelFailures.TryGetValue(modelName, out var count))
                    {
                        count = 0;
                    }
                    modelFailures[modelName] = count + 1;
                }
            }

            if (image.IsFavorite || entry.IsFavorite)
            {
                favoritesAll++;
                if (!string.IsNullOrWhiteSpace(modelName))
                {
                    if (!modelFavorites.TryGetValue(modelName, out var count))
                    {
                        count = 0;
                    }
                    modelFavorites[modelName] = count + 1;
                }
            }

            var gen = HistoryViewerViewModel.GetOrParseGenParams(image) ?? entry.ImageParameters;
            if (!string.IsNullOrWhiteSpace(gen?.Scheduler))
            {
                if (!schedulerStats.TryGetValue(gen.Scheduler, out var schedulerList))
                {
                    schedulerList = new List<HistoryImage>();
                    schedulerStats[gen.Scheduler] = schedulerList;
                }
                schedulerList.Add(image);
            }

            if (gen?.Steps is > 0)
            {
                if (!stepStats.TryGetValue(gen.Steps, out var stepList))
                {
                    stepList = new List<HistoryImage>();
                    stepStats[gen.Steps] = stepList;
                }
                stepList.Add(image);
            }

            var loraCount = gen?.Loras?.Count ?? 0;
            if (!loraCountStats.TryGetValue(loraCount, out var loraList))
            {
                loraList = new List<HistoryImage>();
                loraCountStats[loraCount] = loraList;
            }
            loraList.Add(image);

            foreach (var lora in ResolveLoraNames(entry, image))
            {
                if (!loraUsage.TryGetValue(lora, out var count))
                {
                    count = 0;
                }
                loraUsage[lora] = count + 1;
            }
        }

        var uniqueModels = modelGroups.Keys.Count;
        var avgAesthetic = aestheticScores.Count > 0 ? aestheticScores.Average() : (double?)null;
        var avgHeuristic = heuristicScores.Count > 0 ? heuristicScores.Average() : (double?)null;
        var avgSharpness = sharpnessScores.Count > 0 ? sharpnessScores.Average() : (double?)null;
        var avgPromptMatch = promptMatchScores.Count > 0 ? promptMatchScores.Average() : (double?)null;
        var avgComposite = compositeScores.Count > 0 ? compositeScores.Average() : (double?)null;
        var medianDuration = durationAll.Count > 0 ? Median(durationAll.Select(d => (double)d)) : (double?)null;
        double? avgMsPerToken = null;
        if (statsModels.Count > 0)
        {
            var totalTokens = statsModels.Sum(m => m.TotalTokens);
            var totalDuration = statsModels.Sum(m => m.TotalDurationMs);
            if (totalTokens > 0 && totalDuration > 0)
            {
                avgMsPerToken = (double)totalDuration / totalTokens;
            }
        }

        var failureRate = totalImages > 0 ? (double)failuresAll / totalImages : (double?)null;
        var favoriteRate = totalImages > 0 ? (double)favoritesAll / totalImages : (double?)null;

        var mostUsedModel = modelGroups
            .OrderByDescending(kvp => kvp.Value.Count)
            .Select(kvp => new { Key = kvp.Key, Count = (long)kvp.Value.Count })
            .FirstOrDefault();

        var bestAestheticModel = modelAesthetic
            .Where(kvp => kvp.Value.Count >= 3)
            .Select(kvp => new { kvp.Key, Avg = kvp.Value.Average(), Count = kvp.Value.Count })
            .OrderByDescending(kvp => kvp.Avg)
            .FirstOrDefault();

        var fastestModel = statsModels.Count > 0
            ? statsModels
                .Where(m => m.TotalDurationMs > 0 && m.TotalTokens > 0)
                .Select(m => new { Key = m.ModelName, MsPerToken = (double)m.TotalDurationMs / m.TotalTokens })
                .OrderBy(m => m.MsPerToken)
                .FirstOrDefault()
            : modelDurations
                .Where(kvp => kvp.Value.Count >= 2)
                .Select(kvp => new { Key = kvp.Key, MsPerToken = Median(kvp.Value.Select(v => (double)v)) })
                .OrderBy(kvp => kvp.MsPerToken)
                .FirstOrDefault();

        Metrics.Add(new KpiMetric("Images", totalImages.ToString("N0", CultureInfo.InvariantCulture)));
        Metrics.Add(new KpiMetric("Entries", totalEntries.ToString("N0", CultureInfo.InvariantCulture)));
        Metrics.Add(new KpiMetric("Models", uniqueModels.ToString("N0", CultureInfo.InvariantCulture)));
        Metrics.Add(new KpiMetric("Avg Aesthetic", avgAesthetic.HasValue ? $"{avgAesthetic:0.00}" : "N/A",
            aestheticScores.Count > 0 ? $"{aestheticScores.Count:N0} scored" : "No scores"));
        Metrics.Add(new KpiMetric("Avg Composite", avgComposite.HasValue ? $"{avgComposite:0.0}" : "N/A",
            compositeScores.Count > 0 ? $"{compositeScores.Count:N0} scored" : "No composite scores"));
        Metrics.Add(new KpiMetric("Avg Sharpness", avgSharpness.HasValue ? $"{avgSharpness:0.0}" : "N/A",
            sharpnessScores.Count > 0 ? $"{sharpnessScores.Count:N0} scored" : "No sharpness scores"));
        Metrics.Add(new KpiMetric("Avg Heuristic", avgHeuristic.HasValue ? $"{avgHeuristic:0.0}" : "N/A",
            heuristicScores.Count > 0 ? $"{heuristicScores.Count:N0} scored" : "No heuristic scores"));
        Metrics.Add(new KpiMetric("Avg Prompt Match", avgPromptMatch.HasValue ? $"{avgPromptMatch:0.0}" : "N/A",
            avgPromptMatch.HasValue ? "CLIP prompt match" : "Prompt match not available"));
        Metrics.Add(new KpiMetric("Most Used Model", mostUsedModel?.Key ?? "N/A",
            mostUsedModel != null ? $"{mostUsedModel.Count:N0} images" : "No model data"));
        Metrics.Add(new KpiMetric("Fastest Model", fastestModel?.Key ?? "N/A",
            fastestModel != null ? $"{fastestModel.MsPerToken:0.0} ms/token" : "No timing data"));
        Metrics.Add(new KpiMetric("Avg ms/token", avgMsPerToken.HasValue ? $"{avgMsPerToken:0.0}" : "N/A",
            avgMsPerToken.HasValue ? "All generations" : "No token data"));
        Metrics.Add(new KpiMetric("Median Gen Time", medianDuration.HasValue ? $"{medianDuration:0} ms" : "N/A",
            durationAll.Count > 0 ? $"{durationAll.Count:N0} timed (history)" : "No timing data"));
        Metrics.Add(new KpiMetric("Failure Rate", failureRate.HasValue ? $"{failureRate:P1}" : "N/A",
            totalImages > 0 ? $"{failuresAll:N0} failed" : "No data"));
        Metrics.Add(new KpiMetric("Favorite Rate", favoriteRate.HasValue ? $"{favoriteRate:P1}" : "N/A",
            totalImages > 0 ? $"{favoritesAll:N0} favorites" : "No favorites"));

        Charts.Add(BuildQualitySpeedChart(modelAesthetic, modelDurations));
        Charts.Add(BuildStabilityChart(modelAesthetic));
        Charts.Add(BuildSchedulerChart(schedulerStats));
        Charts.Add(BuildStepChart(stepStats));
        Charts.Add(BuildLoraCountChart(statsLoraBuckets, loraCountStats));
        Charts.Add(BuildComponentChart(avgComposite, avgAesthetic, avgHeuristic, avgSharpness, avgPromptMatch));
        Charts.Add(BuildFavoriteRateChart(modelFavorites, modelGroups, favoriteRate));

        var scoreValues = compositeScores.Count > 0 ? compositeScores : aestheticScores;
        Histograms.Add(BuildScoreHistogramChart(scoreValues, compositeScores.Count > 0 ? "Composite" : "Aesthetic"));
        TrendCharts.Add(BuildScoreTrendChart(images, compositeScores.Count > 0 ? "Composite" : "Aesthetic"));
        ScatterCharts.Add(BuildPromptLengthScatterChart(images, compositeScores.Count > 0 ? "Composite" : "Aesthetic"));

        Leaderboards.Add(BuildLeaderboard(
            "Top Models (Usage)",
            modelGroups
                .OrderByDescending(kvp => kvp.Value.Count)
                .Select((kvp, index) => new KpiLeaderboardItem(index + 1, kvp.Key, kvp.Value.Count.ToString("N0", CultureInfo.InvariantCulture)))));

        Leaderboards.Add(BuildLeaderboard(
            "Reliability (Consistency)",
            BuildReliabilityItems(modelComposite, modelAesthetic)));

        Leaderboards.Add(BuildLeaderboard(
            "Top Models (Aesthetic Avg)",
            modelAesthetic
                .Where(kvp => kvp.Value.Count >= 3)
                .Select(kvp => new { kvp.Key, Avg = kvp.Value.Average(), Count = kvp.Value.Count })
                .OrderByDescending(kvp => kvp.Avg)
                .Select((kvp, index) => new KpiLeaderboardItem(index + 1, kvp.Key, $"{kvp.Avg:0.00}", $"{kvp.Count:N0} scored"))));

        Leaderboards.Add(BuildLeaderboard(
            "Fastest Models (ms/token)",
            statsModels.Count > 0
                ? statsModels
                    .Where(m => m.TotalDurationMs > 0 && m.TotalTokens > 0)
                    .Select(m => new { Name = m.ModelName, MsPerToken = (double)m.TotalDurationMs / m.TotalTokens })
                    .OrderBy(m => m.MsPerToken)
                    .Select((m, index) => new KpiLeaderboardItem(index + 1, m.Name, $"{m.MsPerToken:0.0}"))
                : modelDurations
                    .Where(kvp => kvp.Value.Count >= 2)
                    .Select(kvp => new { Name = kvp.Key, MsPerToken = Median(kvp.Value.Select(v => (double)v)) })
                    .OrderBy(kvp => kvp.MsPerToken)
                    .Select((m, index) => new KpiLeaderboardItem(index + 1, m.Name, $"{m.MsPerToken:0.0}"))));

        Leaderboards.Add(BuildLeaderboard(
            "Top LoRAs (Usage)",
            loraUsage
                .OrderByDescending(kvp => kvp.Value)
                .Select((kvp, index) => new KpiLeaderboardItem(index + 1, kvp.Key, kvp.Value.ToString("N0", CultureInfo.InvariantCulture)))));

        Leaderboards.Add(BuildLeaderboard(
            "LoRA Count Speed (ms/token)",
            BuildLoraBucketItems(statsLoraBuckets)));

        if (avgMsPerToken.HasValue)
        {
            Leaderboards.Add(BuildLeaderboard(
                "Heaviest LoRAs (ms/token delta)",
                statsLoras
                    .Where(l => l.TotalTokens > 0 && l.TotalCount >= 10)
                    .Select(l => new
                    {
                        l.LoraName,
                        MsPerToken = (double)l.TotalDurationMs / l.TotalTokens,
                        l.TotalCount
                    })
                    .Select(l => new
                    {
                        l.LoraName,
                        Delta = l.MsPerToken - avgMsPerToken.Value,
                        l.TotalCount
                    })
                    .OrderByDescending(l => l.Delta)
                    .Select((l, index) => new KpiLeaderboardItem(
                        index + 1,
                        l.LoraName,
                        $"{l.Delta:0.0}",
                        $"{l.TotalCount:N0} runs"))));
        }
    }

    private static bool WorkflowMatches(HistoryEntry entry, HistoryImage image, string? workflow)
    {
        if (string.IsNullOrWhiteSpace(workflow)) return true;
        if (!string.IsNullOrWhiteSpace(image.Workflow) &&
            string.Equals(image.Workflow, workflow, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }
        return !string.IsNullOrWhiteSpace(entry.Workflow) &&
               string.Equals(entry.Workflow, workflow, StringComparison.OrdinalIgnoreCase);
    }

    private static bool WorkflowMatches(string modelWorkflow, string? workflow)
    {
        if (string.IsNullOrWhiteSpace(workflow)) return true;
        return string.Equals(modelWorkflow ?? "", workflow, StringComparison.OrdinalIgnoreCase);
    }

    private static bool MatchesTimeRange(HistoryEntry entry, string? range)
    {
        if (string.IsNullOrWhiteSpace(range) || range == "All time") return true;
        var now = DateTime.Now;
        var timestamp = entry.Timestamp;
        if (range == "Today") return timestamp.Date == now.Date;
        if (range == "Last 7 days") return timestamp >= now.AddDays(-7);
        if (range == "Last 30 days") return timestamp >= now.AddDays(-30);
        return true;
    }

    private static bool IsFailed(HistoryImage image)
    {
        if (!string.IsNullOrWhiteSpace(image.ErrorMessage) || !string.IsNullOrWhiteSpace(image.ErrorType))
        {
            return true;
        }
        if (!string.IsNullOrWhiteSpace(image.GenerationStatus) &&
            image.GenerationStatus.Equals("failed", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }
        return false;
    }

    private static string ResolveModelName(HistoryEntry entry, HistoryImage image)
    {
        var gen = HistoryViewerViewModel.GetOrParseGenParams(image) ?? entry.ImageParameters;
        return gen?.Model?.Name
               ?? entry.InvokeAIModel
               ?? "(unknown)";
    }

    private static IEnumerable<string> ResolveLoraNames(HistoryEntry entry, HistoryImage image)
    {
        var gen = HistoryViewerViewModel.GetOrParseGenParams(image) ?? entry.ImageParameters;
        if (gen?.Loras == null) return Array.Empty<string>();
        return gen.Loras
            .Where(l => l?.Lora != null && !string.IsNullOrWhiteSpace(l.Lora.Name))
            .Select(l => l.Lora.Name!)
            .Distinct(StringComparer.OrdinalIgnoreCase);
    }

    private static int? ResolveDurationMs(HistoryImage image)
    {
        if (image.GenerationDurationMs.HasValue) return image.GenerationDurationMs.Value;
        if (image.TotalDurationMs.HasValue) return image.TotalDurationMs.Value;
        return null;
    }

    private static int EstimateTokenCount(HistoryEntry entry, HistoryImage image)
    {
        var gen = HistoryViewerViewModel.GetOrParseGenParams(image) ?? entry.ImageParameters;
        var parts = new[]
        {
            gen?.Prompt,
            gen?.PositiveStylePrompt,
            gen?.NegativePrompt,
            gen?.NegativeStylePrompt,
            image.Prompt
        };
        var text = string.Join(" ", parts.Where(p => !string.IsNullOrWhiteSpace(p))).Trim();
        if (string.IsNullOrWhiteSpace(text)) return 0;
        return text.Split((char[])null!, StringSplitOptions.RemoveEmptyEntries).Length;
    }

    private static double Median(IEnumerable<double> values)
    {
        var list = values.OrderBy(v => v).ToList();
        if (list.Count == 0) return 0;
        var mid = list.Count / 2;
        return list.Count % 2 == 0 ? (list[mid - 1] + list[mid]) / 2.0 : list[mid];
    }

    private static IEnumerable<KpiLeaderboardItem> BuildLoraBucketItems(List<LoraCountKpiStats> buckets)
    {
        if (buckets.Count == 0) return Array.Empty<KpiLeaderboardItem>();

        var order = new[] { "0", "1", "2", "3+" };
        var items = buckets
            .Where(b => b.TotalTokens > 0)
            .GroupBy(b => b.Bucket)
            .Select(g => new
            {
                Bucket = g.Key,
                Tokens = g.Sum(x => x.TotalTokens),
                Duration = g.Sum(x => x.TotalDurationMs),
                Count = g.Sum(x => x.TotalCount)
            })
            .Where(g => g.Tokens > 0 && g.Duration > 0)
            .Select(g => new
            {
                g.Bucket,
                MsPerToken = (double)g.Duration / g.Tokens,
                g.Count
            })
            .OrderBy(g => Array.IndexOf(order, g.Bucket))
            .ToList();

        return items.Select((g, index) => new KpiLeaderboardItem(
            index + 1,
            g.Bucket,
            $"{g.MsPerToken:0.0}",
            $"{g.Count:N0} runs"));
    }

    private static KpiLeaderboard BuildLeaderboard(string title, IEnumerable<KpiLeaderboardItem> items)
    {
        var list = new ObservableCollection<KpiLeaderboardItem>(items);
        return new KpiLeaderboard(title, list);
    }

    private static KpiBarChart BuildQualitySpeedChart(
        Dictionary<string, List<double>> modelAesthetic,
        Dictionary<string, List<int>> modelDurations)
    {
        var items = modelAesthetic
            .Where(kvp => kvp.Value.Count >= 3 && modelDurations.ContainsKey(kvp.Key))
            .Select(kvp =>
            {
                var avgScore = kvp.Value.Average();
                var durationMs = Median(modelDurations[kvp.Key].Select(v => (double)v));
                var seconds = durationMs > 0 ? durationMs / 1000.0 : 0;
                var qualitySpeed = seconds > 0 ? avgScore / seconds : 0;
                return new { kvp.Key, AvgScore = avgScore, QualitySpeed = qualitySpeed };
            })
            .Where(x => x.QualitySpeed > 0)
            .OrderByDescending(x => x.QualitySpeed)
            .Take(10)
            .ToList();

        return BuildBarChart(
            "Quality/Speed (Models)",
            items.Select(x => new KpiBarItem(x.Key, $"{x.QualitySpeed:0.0}", $"{x.AvgScore:0.00} avg score", x.QualitySpeed)));
    }

    private static KpiBarChart BuildStabilityChart(Dictionary<string, List<double>> modelAesthetic)
    {
        var items = modelAesthetic
            .Where(kvp => kvp.Value.Count >= 5)
            .Select(kvp => new
            {
                kvp.Key,
                StdDev = StdDev(kvp.Value)
            })
            .Where(x => x.StdDev > 0)
            .OrderBy(x => x.StdDev)
            .Take(10)
            .ToList();

        if (items.Count == 0)
        {
            return new KpiBarChart("Aesthetic Stability (Lower is better)", new ObservableCollection<KpiBarItem>())
            {
                EmptyMessage = "Need at least 5 scored images per model."
            };
        }

        var max = items.Max(x => x.StdDev);
        return BuildBarChart(
            "Aesthetic Stability (Lower is better)",
            items.Select(x =>
            {
                var inverted = max > 0 ? max - x.StdDev : 0;
                return new KpiBarItem(x.Key, $"{x.StdDev:0.00}", "std dev", inverted);
            }));
    }

    private static KpiBarChart BuildSchedulerChart(Dictionary<string, List<HistoryImage>> schedulerStats)
    {
        var items = schedulerStats
            .Select(kvp => new
            {
                kvp.Key,
                Scores = kvp.Value.Where(v => v.AestheticScore.HasValue).Select(v => v.AestheticScore!.Value).ToList(),
                Count = kvp.Value.Count
            })
            .Where(x => x.Scores.Count >= 3)
            .Select(x => new { x.Key, Avg = x.Scores.Average(), x.Count })
            .OrderByDescending(x => x.Avg)
            .Take(10)
            .ToList();

        return BuildBarChart(
            "Schedulers (Avg Aesthetic)",
            items.Select(x => new KpiBarItem(x.Key, $"{x.Avg:0.00}", $"{x.Count:N0} images", x.Avg)));
    }

    private static KpiBarChart BuildStepChart(Dictionary<int, List<HistoryImage>> stepStats)
    {
        var items = stepStats
            .Select(kvp => new
            {
                Steps = kvp.Key,
                Scores = kvp.Value.Where(v => v.AestheticScore.HasValue).Select(v => v.AestheticScore!.Value).ToList(),
                Count = kvp.Value.Count
            })
            .Where(x => x.Scores.Count >= 3)
            .Select(x => new { x.Steps, Avg = x.Scores.Average(), x.Count })
            .OrderByDescending(x => x.Avg)
            .Take(10)
            .ToList();

        return BuildBarChart(
            "Steps (Avg Aesthetic)",
            items.Select(x => new KpiBarItem($"{x.Steps} steps", $"{x.Avg:0.00}", $"{x.Count:N0} images", x.Avg)));
    }

    private static KpiBarChart BuildLoraCountChart(List<LoraCountKpiStats> statsBuckets, Dictionary<int, List<HistoryImage>> loraCountStats)
    {
        if (statsBuckets.Count > 0)
        {
            var order = new[] { "0", "1", "2", "3+" };
            var items = statsBuckets
                .Where(b => b.TotalTokens > 0 && b.TotalDurationMs > 0)
                .GroupBy(b => b.Bucket)
                .Select(g => new
                {
                    Bucket = g.Key,
                    MsPerToken = (double)g.Sum(x => x.TotalDurationMs) / g.Sum(x => x.TotalTokens),
                    Count = g.Sum(x => x.TotalCount)
                })
                .OrderBy(g => Array.IndexOf(order, g.Bucket))
                .ToList();

            return BuildBarChart(
                "LoRA Tax (ms/token by count)",
                items.Select(x => new KpiBarItem($"{x.Bucket} LoRA", $"{x.MsPerToken:0.0}", $"{x.Count:N0} runs", x.MsPerToken)));
        }

        var fallback = loraCountStats
            .Select(kvp => new
            {
                Count = kvp.Key,
                Durations = kvp.Value.Select(ResolveDurationMs).Where(v => v.HasValue).Select(v => v!.Value).ToList(),
                Tokens = kvp.Value.Select(v => EstimateTokenCount(new HistoryEntry(), v)).Where(t => t > 0).ToList()
            })
            .Where(x => x.Durations.Count >= 3 && x.Tokens.Count > 0)
            .Select(x => new
            {
                x.Count,
                MsPerToken = (double)x.Durations.Sum() / x.Tokens.Sum(),
                Images = x.Durations.Count
            })
            .OrderBy(x => x.Count)
            .ToList();

        return BuildBarChart(
            "LoRA Tax (ms/token by count)",
            fallback.Select(x => new KpiBarItem($"{x.Count} LoRA", $"{x.MsPerToken:0.0}", $"{x.Images:N0} images", x.MsPerToken)));
    }

    private static KpiBarChart BuildBarChart(string title, IEnumerable<KpiBarItem> items)
    {
        var list = items.ToList();
        var max = list.Count > 0 ? list.Max(i => i.BarValue) : 0;
        foreach (var item in list)
        {
            item.BarWidth = max > 0 ? (item.BarValue / max) * KpiBarItem.MaxBarWidth : 0;
        }
        return new KpiBarChart(title, new ObservableCollection<KpiBarItem>(list));
    }

    private static double StdDev(IEnumerable<double> values)
    {
        var list = values.ToList();
        if (list.Count == 0) return 0;
        var mean = list.Average();
        var variance = list.Sum(v => Math.Pow(v - mean, 2)) / list.Count;
        return Math.Sqrt(variance);
    }

    private static KpiBarChart BuildComponentChart(double? composite, double? aesthetic, double? heuristic, double? sharpness, double? promptMatch)
    {
        var items = new List<KpiBarItem>();
        if (composite.HasValue) items.Add(new KpiBarItem("Composite", $"{composite:0.0}", "avg", composite.Value));
        if (aesthetic.HasValue) items.Add(new KpiBarItem("Aesthetic", $"{aesthetic:0.0}", "avg", aesthetic.Value));
        if (heuristic.HasValue) items.Add(new KpiBarItem("Heuristic", $"{heuristic:0.0}", "avg", heuristic.Value));
        if (sharpness.HasValue) items.Add(new KpiBarItem("Sharpness", $"{sharpness:0.0}", "avg", sharpness.Value));
        if (promptMatch.HasValue) items.Add(new KpiBarItem("Prompt Match", $"{promptMatch:0.0}", "avg", promptMatch.Value));
        var chart = BuildBarChart("Score Components (Avg)", items);
        if (items.Count == 0)
        {
            chart.EmptyMessage = "No scores yet.";
        }
        return chart;
    }

    private static KpiBarChart BuildFavoriteRateChart(
        Dictionary<string, int> modelFavorites,
        Dictionary<string, List<HistoryImage>> modelGroups,
        double? baselineRate)
    {
        if (baselineRate is null || baselineRate <= 0)
        {
            return new KpiBarChart("Favorite Rate (Model vs baseline)", new ObservableCollection<KpiBarItem>())
            {
                EmptyMessage = "No favorites yet."
            };
        }

        var items = modelGroups
            .Where(kvp => kvp.Value.Count >= 5)
            .Select(kvp =>
            {
                var favs = modelFavorites.TryGetValue(kvp.Key, out var count) ? count : 0;
                var rate = kvp.Value.Count > 0 ? (double)favs / kvp.Value.Count : 0;
                var lift = baselineRate > 0 ? rate / baselineRate.Value : 0;
                return new { kvp.Key, Rate = rate, Lift = lift, Count = kvp.Value.Count };
            })
            .OrderByDescending(x => x.Lift)
            .Take(10)
            .ToList();

        return BuildBarChart(
            "Favorite Rate (Model vs baseline)",
            items.Select(x => new KpiBarItem(x.Key, $"{x.Rate:P0}", $"{x.Lift:0.0}x baseline", x.Lift)));
    }

    private static IEnumerable<KpiLeaderboardItem> BuildReliabilityItems(
        Dictionary<string, List<double>> modelComposite,
        Dictionary<string, List<double>> modelAesthetic)
    {
        var source = modelComposite.Count > 0 ? modelComposite : modelAesthetic;
        return source
            .Where(kvp => kvp.Value.Count >= 5)
            .Select(kvp =>
            {
                var std = StdDev(kvp.Value);
                var label = std <= 0.6 ? "High" : std <= 1.2 ? "Medium" : "Low";
                return new { kvp.Key, Label = label, Std = std, Count = kvp.Value.Count };
            })
            .OrderBy(x => x.Std)
            .Select((x, index) => new KpiLeaderboardItem(
                index + 1,
                x.Key,
                x.Label,
                $"{x.Std:0.00} std · {x.Count:N0} scored"));
    }

    private static KpiBarChart BuildScoreHistogramChart(List<double> values, string label)
    {
        if (values.Count < 5)
        {
            return new KpiBarChart($"{label} Score Distribution", new ObservableCollection<KpiBarItem>())
            {
                EmptyMessage = "Need at least 5 scored images."
            };
        }

        var min = values.Min();
        var max = values.Max();
        if (Math.Abs(max - min) < 0.001)
        {
            max = min + 1;
        }

        var bins = 10;
        var counts = new int[bins];
        foreach (var value in values)
        {
            var normalized = (value - min) / (max - min);
            var idx = Math.Min(bins - 1, (int)Math.Floor(normalized * bins));
            counts[idx]++;
        }

        var items = new List<KpiBarItem>();
        for (var i = 0; i < bins; i++)
        {
            var start = min + (max - min) * i / bins;
            var end = min + (max - min) * (i + 1) / bins;
            items.Add(new KpiBarItem($"{start:0.0}-{end:0.0}", counts[i].ToString("N0", CultureInfo.InvariantCulture), null, counts[i]));
        }

        return BuildBarChart($"{label} Score Distribution", items);
    }

    private static KpiTrendChart BuildScoreTrendChart(List<(HistoryEntry entry, HistoryImage image)> images, string label)
    {
        var series = images
            .Select(pair =>
            {
                var score = pair.image.CompositeScore ?? pair.image.AestheticScore ?? pair.image.HeuristicScore;
                return new { pair.entry.Timestamp.Date, Score = score };
            })
            .Where(x => x.Score.HasValue)
            .GroupBy(x => x.Date)
            .Select(g => new { Date = g.Key, Avg = g.Average(x => x.Score!.Value), Count = g.Count() })
            .OrderBy(x => x.Date)
            .ToList();

        var chart = new KpiTrendChart($"{label} Trend (Daily Avg)");
        if (series.Count < 3)
        {
            chart.EmptyMessage = "Need at least 3 days of scored data.";
            return chart;
        }

        var maxPoints = 30;
        if (series.Count > maxPoints)
        {
            series = series.Skip(series.Count - maxPoints).ToList();
        }

        var min = series.Min(x => x.Avg);
        var max = series.Max(x => x.Avg);
        if (Math.Abs(max - min) < 0.001)
        {
            max = min + 1;
        }

        var width = KpiTrendChart.PlotWidth;
        var height = KpiTrendChart.PlotHeight;
        var step = series.Count > 1 ? width / (series.Count - 1) : width;

        var points = new AvaloniaList<Point>();
        for (var i = 0; i < series.Count; i++)
        {
            var value = series[i].Avg;
            var x = i * step;
            var y = height - ((value - min) / (max - min)) * height;
            points.Add(new Point(x, y));
            chart.Points.Add(new KpiTrendPoint(series[i].Date.ToString("MM/dd"), value, new Point(x, y), series[i].Count));
        }

        chart.LinePoints = points;
        chart.MinValue = min;
        chart.MaxValue = max;
        return chart;
    }

    private static KpiScatterChart BuildPromptLengthScatterChart(List<(HistoryEntry entry, HistoryImage image)> images, string label)
    {
        var points = images
            .Select(pair =>
            {
                var score = pair.image.CompositeScore ?? pair.image.AestheticScore ?? pair.image.HeuristicScore;
                if (!score.HasValue) return null;
                var tokens = EstimateTokenCount(pair.entry, pair.image);
                return new { Tokens = tokens, Score = score.Value };
            })
            .Where(x => x != null && x.Tokens > 0)
            .Select(x => new KpiScatterPoint(x!.Tokens, x.Score))
            .ToList();

        var chart = new KpiScatterChart($"Prompt Length vs {label}");
        if (points.Count < 10)
        {
            chart.EmptyMessage = "Need at least 10 scored images.";
            return chart;
        }

        var maxPoints = 200;
        if (points.Count > maxPoints)
        {
            points = points.OrderByDescending(p => p.Score).Take(maxPoints).ToList();
        }

        var minX = points.Min(p => p.X);
        var maxX = points.Max(p => p.X);
        var minY = points.Min(p => p.Score);
        var maxY = points.Max(p => p.Score);
        if (minX == maxX) maxX = minX + 1;
        if (Math.Abs(maxY - minY) < 0.001) maxY = minY + 1;

        foreach (var point in points)
        {
            var x = (point.X - minX) / (maxX - minX) * KpiScatterChart.PlotWidth;
            var y = KpiScatterChart.PlotHeight - ((point.Score - minY) / (maxY - minY) * KpiScatterChart.PlotHeight);
            point.Plot = new Point(x, y);
            point.Tooltip = $"{point.X} tokens · {point.Score:0.0}";
        }

        chart.Points = new ObservableCollection<KpiScatterPoint>(points);
        chart.MinX = minX;
        chart.MaxX = maxX;
        chart.MinY = minY;
        chart.MaxY = maxY;
        return chart;
    }
}

public class KpiMetric
{
    public string Title { get; }
    public string Value { get; }
    public string? Detail { get; }
    public bool HasDetail => !string.IsNullOrWhiteSpace(Detail);

    public KpiMetric(string title, string value, string? detail = null)
    {
        Title = title;
        Value = value;
        Detail = detail;
    }
}

public class KpiLeaderboard
{
    public string Title { get; }
    public ObservableCollection<KpiLeaderboardItem> Items { get; }
    public bool ShowEmptyMessage { get; }

    public KpiLeaderboard(string title, ObservableCollection<KpiLeaderboardItem> items)
    {
        Title = title;
        Items = items;
        ShowEmptyMessage = Items.Count == 0;
    }
}

public class KpiBarChart
{
    public string Title { get; }
    public ObservableCollection<KpiBarItem> Items { get; }
    public string EmptyMessage { get; set; } = "No data yet.";
    public bool ShowEmptyMessage => Items.Count == 0;

    public KpiBarChart(string title, ObservableCollection<KpiBarItem> items)
    {
        Title = title;
        Items = items;
    }
}

public class KpiBarItem
{
    public const double MaxBarWidth = 180;
    public string Label { get; }
    public string Value { get; }
    public string? Detail { get; }
    public double BarValue { get; }
    public double BarWidth { get; set; }
    public bool HasDetail => !string.IsNullOrWhiteSpace(Detail);

    public KpiBarItem(string label, string value, string? detail, double barValue)
    {
        Label = label;
        Value = value;
        Detail = detail;
        BarValue = barValue;
    }
}

public class KpiLeaderboardItem
{
    public int Rank { get; }
    public string Label { get; }
    public string Value { get; }
    public string? Detail { get; }
    public string FlyoutText { get; }
    public bool HasDetail => !string.IsNullOrWhiteSpace(Detail);

    public KpiLeaderboardItem(int rank, string label, string value, string? detail = null)
    {
        Rank = rank;
        Label = label;
        Value = value;
        Detail = detail;
        FlyoutText = string.IsNullOrWhiteSpace(detail)
            ? $"{label}: {value}"
            : $"{label}\n{value}\n{detail}";
    }
}

public class KpiTrendChart
{
    public const double PlotWidth = 260;
    public const double PlotHeight = 120;
    public string Title { get; }
    public AvaloniaList<Point> LinePoints { get; set; } = new();
    public ObservableCollection<KpiTrendPoint> Points { get; } = new();
    public string EmptyMessage { get; set; } = "No data yet.";
    public bool ShowEmptyMessage => Points.Count == 0;
    public double MinValue { get; set; }
    public double MaxValue { get; set; }

    public KpiTrendChart(string title)
    {
        Title = title;
    }
}

public class KpiTrendPoint
{
    public string Label { get; }
    public double Value { get; }
    public Point Plot { get; }
    public int Count { get; }

    public KpiTrendPoint(string label, double value, Point plot, int count)
    {
        Label = label;
        Value = value;
        Plot = plot;
        Count = count;
    }
}

public class KpiScatterChart
{
    public const double PlotWidth = 260;
    public const double PlotHeight = 140;
    public string Title { get; }
    public ObservableCollection<KpiScatterPoint> Points { get; set; } = new();
    public string EmptyMessage { get; set; } = "No data yet.";
    public bool ShowEmptyMessage => Points.Count == 0;
    public double MinX { get; set; }
    public double MaxX { get; set; }
    public double MinY { get; set; }
    public double MaxY { get; set; }

    public KpiScatterChart(string title)
    {
        Title = title;
    }
}

public class KpiScatterPoint
{
    public int X { get; }
    public double Score { get; }
    public Point Plot { get; set; }
    public string Tooltip { get; set; } = "";

    public KpiScatterPoint(int x, double score)
    {
        X = x;
        Score = score;
    }
}
