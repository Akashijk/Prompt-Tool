using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Media.Imaging;
using PromptTool.Core.Models;
using PromptTool.Core.Services;

namespace PromptTool.Services;

public sealed class ModelComparisonService
{
    private const double WinnerEpsilon = 0.05;

    public async Task<ModelComparisonResult> CompareEntryAsync(
        HistoryEntry entry,
        string historyDir,
        ImageCacheService imageCache,
        int threshold,
        CancellationToken ct,
        IProgress<(double pct, string status)>? progress = null,
        IReadOnlyDictionary<string, SimilarityFingerprint>? cachedFingerprints = null)
    {
        return await CompareEntriesAsync(
            new[] { entry },
            historyDir,
            imageCache,
            threshold,
            ct,
            progress,
            cachedFingerprints);
    }

    public async Task<ModelComparisonResult> CompareEntriesAsync(
        IReadOnlyList<HistoryEntry> entries,
        string historyDir,
        ImageCacheService imageCache,
        int threshold,
        CancellationToken ct,
        IProgress<(double pct, string status)>? progress = null,
        IReadOnlyDictionary<string, SimilarityFingerprint>? cachedFingerprints = null)
    {
        return await Task.Run(() =>
        {
            var candidateList = entries ?? Array.Empty<HistoryEntry>();
            var totalImages = candidateList.Sum(e => e.Images?.Count ?? 0);
            progress?.Report((0, "Loading comparable images..."));

            var comparable = new List<ComparableHistoryImage>();
            var processedImages = 0;
            foreach (var entry in candidateList)
            {
                var images = entry.Images ?? new List<HistoryImage>();
                for (var i = 0; i < images.Count; i++)
                {
                    ct.ThrowIfCancellationRequested();
                    processedImages++;
                    var current = images[i];
                    if (!TryBuildComparableImage(entry, current, historyDir, imageCache, cachedFingerprints, out var item))
                    {
                        continue;
                    }

                    comparable.Add(item!);
                    progress?.Report((Math.Min(45, processedImages * 45d / Math.Max(1, totalImages)), $"Hashing image {processedImages} of {Math.Max(1, totalImages)}..."));
                }
            }

            var modelCount = comparable
                .Select(c => c.ModelName)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Count();
            if (comparable.Count < 2 || modelCount < 2)
            {
                return new ModelComparisonResult
                {
                    ComparedEntries = candidateList.Count,
                    TotalImages = comparable.Count,
                    DistinctModels = modelCount,
                    SummaryText = "Not enough cross-model images in the selected scope to compare."
                };
            }

            var matches = new List<ModelSimilarityMatch>();
            var stats = new Dictionary<string, ModelPairStats>(StringComparer.OrdinalIgnoreCase);
            var seenPairs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            var grouped = comparable
                .GroupBy(c => c.ComparisonKey, StringComparer.Ordinal)
                .Where(g => g.Select(x => x.ModelName).Distinct(StringComparer.OrdinalIgnoreCase).Count() > 1)
                .ToList();

            var processedGroups = 0;
            foreach (var group in grouped)
            {
                ct.ThrowIfCancellationRequested();

                var byModel = group
                    .GroupBy(item => item.ModelName, StringComparer.OrdinalIgnoreCase)
                    .ToList();

                for (var leftIndex = 0; leftIndex < byModel.Count; leftIndex++)
                {
                    for (var rightIndex = leftIndex + 1; rightIndex < byModel.Count; rightIndex++)
                    {
                        ct.ThrowIfCancellationRequested();
                        var leftGroup = byModel[leftIndex].ToList();
                        var rightGroup = byModel[rightIndex].ToList();

                        foreach (var left in leftGroup)
                        {
                            ComparableHistoryImage? best = null;
                            var bestDistance = int.MaxValue;

                            foreach (var right in rightGroup)
                            {
                                var dedupeKey = BuildImagePairKey(left.Image, right.Image);
                                if (seenPairs.Contains(dedupeKey))
                                {
                                    continue;
                                }

                                var distance = HammingDistance(left.Hash, right.Hash);
                                if (distance < bestDistance)
                                {
                                    bestDistance = distance;
                                    best = right;
                                    if (distance == 0)
                                    {
                                        break;
                                    }
                                }
                            }

                            if (best == null || bestDistance > threshold)
                            {
                                continue;
                            }

                            var pairKey = BuildOrderedModelPairKey(left.ModelName, best.ModelName);
                            if (!stats.TryGetValue(pairKey, out var pairStats))
                            {
                                pairStats = new ModelPairStats(left.ModelName, best.ModelName);
                                stats[pairKey] = pairStats;
                            }

                            var winner = DetermineWinner(left, best);
                            pairStats.MatchCount++;
                            switch (winner)
                            {
                                case ModelSimilarityWinner.Left:
                                    pairStats.WinLeft++;
                                    break;
                                case ModelSimilarityWinner.Right:
                                    pairStats.WinRight++;
                                    break;
                                default:
                                    pairStats.Ties++;
                                    break;
                            }

                            seenPairs.Add(BuildImagePairKey(left.Image, best.Image));
                            matches.Add(new ModelSimilarityMatch(
                                left.Entry,
                                best.Entry,
                                left.Image,
                                best.Image,
                                left.ModelName,
                                best.ModelName,
                                left.ComparisonKey,
                                bestDistance,
                                winner,
                                left.AestheticScore,
                                best.AestheticScore));
                        }
                    }
                }

                processedGroups++;
                progress?.Report((45 + (processedGroups * 50d / Math.Max(1, grouped.Count)), $"Comparing group {processedGroups} of {grouped.Count}..."));
            }

            var orderedMatches = matches
                .OrderBy(m => m.Distance)
                .ThenBy(m => m.LeftModel, StringComparer.OrdinalIgnoreCase)
                .ThenBy(m => m.RightModel, StringComparer.OrdinalIgnoreCase)
                .ToList();

            progress?.Report((100, "Comparison complete."));
            return new ModelComparisonResult
            {
                ComparedEntries = candidateList.Count,
                TotalImages = comparable.Count,
                DistinctModels = modelCount,
                ComparedGroups = grouped.Count,
                MatchCount = orderedMatches.Count,
                PairStats = stats.Values
                    .OrderByDescending(s => s.MatchCount)
                    .ThenBy(s => s.LeftModel, StringComparer.OrdinalIgnoreCase)
                    .ThenBy(s => s.RightModel, StringComparer.OrdinalIgnoreCase)
                    .ToList(),
                Matches = orderedMatches,
                SummaryText = BuildSummaryText(candidateList.Count, comparable.Count, modelCount, grouped.Count, orderedMatches.Count, stats.Values.ToList())
            };
        }, ct);
    }

    private static bool TryBuildComparableImage(
        HistoryEntry entry,
        HistoryImage current,
        string historyDir,
        ImageCacheService imageCache,
        IReadOnlyDictionary<string, SimilarityFingerprint>? cachedFingerprints,
        out ComparableHistoryImage? item)
    {
        item = null;
        var modelName = current.GenerationParams?.Model?.Name
                        ?? entry.InvokeAIModel
                        ?? string.Empty;
        if (string.IsNullOrWhiteSpace(modelName))
        {
            return false;
        }

        var key = SimilarityFingerprintCacheService.TryBuildImageKey(current, historyDir);
        ulong hash;
        double sharpness;
        if (!string.IsNullOrWhiteSpace(key) &&
            cachedFingerprints != null &&
            cachedFingerprints.TryGetValue(key, out var cached))
        {
            hash = cached.PHash;
            sharpness = current.SharpnessScore ?? cached.Sharpness;
        }
        else
        {
            var bitmap = TryLoadBitmap(current, historyDir, imageCache);
            if (bitmap == null)
            {
                return false;
            }

            hash = ComputePHash(bitmap);
            sharpness = current.SharpnessScore ?? ScoringHelper.CalculateSharpnessScore(bitmap);
        }

        item = new ComparableHistoryImage(
            entry,
            current,
            modelName.Trim(),
            BuildComparableKeyForImage(entry, current),
            hash,
            current.AestheticScore,
            sharpness);
        return true;
    }

    private static string BuildSummaryText(
        int entriesScanned,
        int totalImages,
        int modelCount,
        int groupCount,
        int matchCount,
        IReadOnlyList<ModelPairStats> pairStats)
    {
        var lines = new List<string>
        {
            $"Entries scanned: {entriesScanned}",
            $"Images analyzed: {totalImages}",
            $"Models involved: {modelCount}",
            $"Comparable groups: {groupCount}",
            $"Near-duplicate matches: {matchCount}"
        };

        if (pairStats.Count == 0)
        {
            lines.Add("No cross-model near-duplicate output detected within the selected threshold.");
            return string.Join(Environment.NewLine, lines);
        }

        lines.Add(string.Empty);
        lines.Add("Top similar model pairs:");
        foreach (var stat in pairStats.Take(8))
        {
            lines.Add($"{stat.LeftModel} <-> {stat.RightModel}: {stat.MatchCount} match(es) | {stat.LeftModel} wins {stat.WinLeft}, {stat.RightModel} wins {stat.WinRight}, ties {stat.Ties}");
        }

        var clusters = BuildModelClusters(pairStats);
        if (clusters.Count > 0)
        {
            lines.Add(string.Empty);
            lines.Add("Model clusters:");
            foreach (var cluster in clusters)
            {
                lines.Add(string.Join(", ", cluster));
            }
        }

        return string.Join(Environment.NewLine, lines);
    }

    private static List<List<string>> BuildModelClusters(IReadOnlyList<ModelPairStats> pairStats)
    {
        var graph = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
        foreach (var stat in pairStats)
        {
            if (!graph.TryGetValue(stat.LeftModel, out var leftNeighbors))
            {
                leftNeighbors = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                graph[stat.LeftModel] = leftNeighbors;
            }
            if (!graph.TryGetValue(stat.RightModel, out var rightNeighbors))
            {
                rightNeighbors = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                graph[stat.RightModel] = rightNeighbors;
            }

            leftNeighbors.Add(stat.RightModel);
            rightNeighbors.Add(stat.LeftModel);
        }

        var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var clusters = new List<List<string>>();
        foreach (var node in graph.Keys.OrderBy(x => x, StringComparer.OrdinalIgnoreCase))
        {
            if (!visited.Add(node))
            {
                continue;
            }

            var cluster = new List<string>();
            var queue = new Queue<string>();
            queue.Enqueue(node);
            while (queue.Count > 0)
            {
                var current = queue.Dequeue();
                cluster.Add(current);
                foreach (var neighbor in graph[current])
                {
                    if (visited.Add(neighbor))
                    {
                        queue.Enqueue(neighbor);
                    }
                }
            }

            if (cluster.Count > 1)
            {
                cluster.Sort(StringComparer.OrdinalIgnoreCase);
                clusters.Add(cluster);
            }
        }

        return clusters;
    }

    private static Bitmap? TryLoadBitmap(HistoryImage image, string historyDir, ImageCacheService imageCache)
    {
        if (!string.IsNullOrWhiteSpace(image.ImagePath))
        {
            var bitmap = imageCache.GetOrLoad(image.ImagePath, null, historyDir);
            if (bitmap != null)
            {
                return bitmap;
            }
        }

        if (image.ImageBytes == null || image.ImageBytes.Length == 0)
        {
            return null;
        }

        try
        {
            using var ms = new MemoryStream(image.ImageBytes);
            return new Bitmap(ms);
        }
        catch
        {
            return null;
        }
    }

    public static string BuildComparableKeyForImage(HistoryEntry entry, HistoryImage image)
    {
        var p = image.GenerationParams ?? entry.ImageParameters;
        var prompt = (image.Prompt ?? entry.ProcessedPrompt ?? entry.OriginalPrompt ?? string.Empty).Trim();
        var width = p?.Width ?? 0;
        var height = p?.Height ?? 0;
        var steps = p?.Steps ?? 0;
        var cfg = Math.Round(p?.CfgScale ?? 0, 2);
        var scheduler = NormalizeScheduler(p?.Scheduler);
        var baseSeed = p?.BaseSeed != 0 ? p?.BaseSeed ?? 0 : p?.Seed ?? 0;
        var loras = p?.Loras == null || p.Loras.Count == 0
            ? string.Empty
            : string.Join("|", p.Loras
                .Where(l => l?.Lora != null && !string.IsNullOrWhiteSpace(l.Lora.Name))
                .OrderBy(l => l.Lora.Name, StringComparer.OrdinalIgnoreCase)
                .Select(l => $"{l.Lora.Name}:{Math.Round(l.Weight, 2):0.##}"));

        return $"{prompt}||{width}x{height}||{steps}||{cfg:0.##}||{scheduler}||{baseSeed}||{loras}";
    }

    private static string NormalizeScheduler(string? scheduler)
    {
        var value = scheduler?.Trim() ?? string.Empty;
        return value.Replace('-', '_').ToLowerInvariant();
    }

    private static string BuildOrderedModelPairKey(string left, string right)
    {
        return string.Compare(left, right, StringComparison.OrdinalIgnoreCase) <= 0
            ? $"{left}||{right}"
            : $"{right}||{left}";
    }

    private static string BuildImagePairKey(HistoryImage left, HistoryImage right)
    {
        var leftKey = left.ImagePath ?? $"mem:{RuntimeHelpers.GetHashCode(left)}";
        var rightKey = right.ImagePath ?? $"mem:{RuntimeHelpers.GetHashCode(right)}";
        return string.Compare(leftKey, rightKey, StringComparison.OrdinalIgnoreCase) <= 0
            ? $"{leftKey}||{rightKey}"
            : $"{rightKey}||{leftKey}";
    }

    private static ModelSimilarityWinner DetermineWinner(ComparableHistoryImage left, ComparableHistoryImage right)
    {
        if (left.AestheticScore.HasValue && right.AestheticScore.HasValue)
        {
            var delta = left.AestheticScore.Value - right.AestheticScore.Value;
            if (Math.Abs(delta) <= WinnerEpsilon)
            {
                return ModelSimilarityWinner.Tie;
            }

            return delta > 0 ? ModelSimilarityWinner.Left : ModelSimilarityWinner.Right;
        }

        var sharpDelta = left.SharpnessScore - right.SharpnessScore;
        if (Math.Abs(sharpDelta) <= WinnerEpsilon)
        {
            return ModelSimilarityWinner.Tie;
        }

        return sharpDelta > 0 ? ModelSimilarityWinner.Left : ModelSimilarityWinner.Right;
    }

    public static ulong ComputePHash(Bitmap bitmap)
    {
        const int sampleSize = 32;
        const int dctSize = 8;
        var luminance = ExtractLuminance(bitmap, sampleSize, sampleSize);
        if (luminance == null)
        {
            return 0;
        }

        var dct = new double[dctSize * dctSize];
        for (var u = 0; u < dctSize; u++)
        {
            for (var v = 0; v < dctSize; v++)
            {
                double sum = 0;
                for (var x = 0; x < sampleSize; x++)
                {
                    for (var y = 0; y < sampleSize; y++)
                    {
                        var value = luminance[(y * sampleSize) + x];
                        sum += value
                               * Math.Cos(((2 * x) + 1) * u * Math.PI / (2 * sampleSize))
                               * Math.Cos(((2 * y) + 1) * v * Math.PI / (2 * sampleSize));
                    }
                }

                var cu = u == 0 ? Math.Sqrt(1d / sampleSize) : Math.Sqrt(2d / sampleSize);
                var cv = v == 0 ? Math.Sqrt(1d / sampleSize) : Math.Sqrt(2d / sampleSize);
                dct[(u * dctSize) + v] = cu * cv * sum;
            }
        }

        var thresholdValues = dct.Skip(1).ToArray();
        Array.Sort(thresholdValues);
        var median = thresholdValues.Length == 0 ? 0 : thresholdValues[thresholdValues.Length / 2];

        ulong hash = 0;
        for (var i = 0; i < dct.Length; i++)
        {
            if (dct[i] >= median)
            {
                hash |= 1UL << i;
            }
        }

        return hash;
    }

    public static int HammingDistance(ulong left, ulong right)
    {
        return BitOperations.PopCount(left ^ right);
    }

    private static double[]? ExtractLuminance(Bitmap bitmap, int targetWidth, int targetHeight)
    {
        try
        {
            var width = bitmap.PixelSize.Width;
            var height = bitmap.PixelSize.Height;
            if (width <= 0 || height <= 0)
            {
                return null;
            }

            var stride = width * 4;
            var data = new byte[stride * height];
            var handle = GCHandle.Alloc(data, GCHandleType.Pinned);
            try
            {
                bitmap.CopyPixels(new PixelRect(0, 0, width, height), handle.AddrOfPinnedObject(), data.Length, stride);
            }
            finally
            {
                handle.Free();
            }

            var output = new double[targetWidth * targetHeight];
            for (var y = 0; y < targetHeight; y++)
            {
                var sourceY = Math.Min(height - 1, (y * height) / targetHeight);
                var row = sourceY * stride;
                for (var x = 0; x < targetWidth; x++)
                {
                    var sourceX = Math.Min(width - 1, (x * width) / targetWidth);
                    var idx = row + (sourceX * 4);
                    var b = data[idx];
                    var g = data[idx + 1];
                    var r = data[idx + 2];
                    output[(y * targetWidth) + x] = (0.2126 * r) + (0.7152 * g) + (0.0722 * b);
                }
            }

            return output;
        }
        catch
        {
            return null;
        }
    }

    private sealed record ComparableHistoryImage(
        HistoryEntry Entry,
        HistoryImage Image,
        string ModelName,
        string ComparisonKey,
        ulong Hash,
        double? AestheticScore,
        double SharpnessScore);
}

public sealed class ModelComparisonResult
{
    public int ComparedEntries { get; init; }
    public int TotalImages { get; init; }
    public int DistinctModels { get; init; }
    public int ComparedGroups { get; init; }
    public int MatchCount { get; init; }
    public string SummaryText { get; init; } = string.Empty;
    public IReadOnlyList<ModelPairStats> PairStats { get; init; } = Array.Empty<ModelPairStats>();
    public IReadOnlyList<ModelSimilarityMatch> Matches { get; init; } = Array.Empty<ModelSimilarityMatch>();
}

public sealed class ModelPairStats
{
    public ModelPairStats(string leftModel, string rightModel)
    {
        LeftModel = leftModel;
        RightModel = rightModel;
    }

    public string LeftModel { get; }
    public string RightModel { get; }
    public int MatchCount { get; set; }
    public int WinLeft { get; set; }
    public int WinRight { get; set; }
    public int Ties { get; set; }
}

public sealed class ModelSimilarityMatch
{
    public ModelSimilarityMatch(
        HistoryEntry leftEntry,
        HistoryEntry rightEntry,
        HistoryImage leftImage,
        HistoryImage rightImage,
        string leftModel,
        string rightModel,
        string comparisonKey,
        int distance,
        ModelSimilarityWinner winner,
        double? leftAestheticScore,
        double? rightAestheticScore)
    {
        LeftEntry = leftEntry;
        RightEntry = rightEntry;
        LeftImage = leftImage;
        RightImage = rightImage;
        LeftModel = leftModel;
        RightModel = rightModel;
        ComparisonKey = comparisonKey;
        Distance = distance;
        Winner = winner;
        LeftAestheticScore = leftAestheticScore;
        RightAestheticScore = rightAestheticScore;
    }

    public HistoryEntry LeftEntry { get; }
    public HistoryEntry RightEntry { get; }
    public HistoryImage LeftImage { get; }
    public HistoryImage RightImage { get; }
    public string LeftModel { get; }
    public string RightModel { get; }
    public string ComparisonKey { get; }
    public int Distance { get; }
    public ModelSimilarityWinner Winner { get; }
    public double? LeftAestheticScore { get; }
    public double? RightAestheticScore { get; }
}

public enum ModelSimilarityWinner
{
    Tie,
    Left,
    Right
}
