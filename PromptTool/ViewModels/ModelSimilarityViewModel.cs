using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class ModelSimilarityViewModel : ObservableObject
{
    private readonly HistoryEntry _entry;
    private readonly IReadOnlyList<HistoryEntry> _allEntries;
    private readonly string _historyDir;
    private readonly ImageCacheService _imageCacheService;
    private readonly ModelComparisonService _comparisonService;
    private readonly SimilarityFingerprintCacheService _similarityCacheService;
    private CancellationTokenSource? _runCts;

    [ObservableProperty] private int _threshold = 6;
    [ObservableProperty] private bool _isRunning;
    [ObservableProperty] private double _progressValue;
    [ObservableProperty] private string _status = "Ready.";
    [ObservableProperty] private string _summaryText = string.Empty;
    [ObservableProperty] private ObservableCollection<ModelSimilarityPairMatchViewModel> _matches = new();
    [ObservableProperty] private ModelSimilarityPairMatchViewModel? _selectedMatch;
    [ObservableProperty] private ObservableCollection<ModelSimilaritySiblingImageViewModel> _similarContextImages = new();
    [ObservableProperty] private string _similarContextHeader = "No match selected.";
    [ObservableProperty] private ObservableCollection<string> _scopeOptions = new(new[] { "Selected Entry", "Full History (cached)" });
    [ObservableProperty] private string _selectedScope = "Selected Entry";

    public Func<HistoryEntry, HistoryImage, Bitmap, Task>? ViewDetailsRequested { get; set; }
    public Func<ModelSimilarityVerificationRequest, Task>? RunVerificationRequested { get; set; }

    public bool CanRunVerification =>
        SelectedMatch != null &&
        !IsRunning &&
        string.Equals(SelectedScope, "Selected Entry", StringComparison.OrdinalIgnoreCase) &&
        string.Equals(SelectedMatch.LeftEntry.Id, SelectedMatch.RightEntry.Id, StringComparison.OrdinalIgnoreCase);

    public ModelSimilarityViewModel(
        HistoryEntry entry,
        IReadOnlyList<HistoryEntry> allEntries,
        string historyDir,
        ImageCacheService imageCacheService,
        ModelComparisonService comparisonService,
        SimilarityFingerprintCacheService similarityCacheService)
    {
        _entry = entry;
        _allEntries = allEntries ?? new List<HistoryEntry> { entry };
        _historyDir = historyDir;
        _imageCacheService = imageCacheService;
        _comparisonService = comparisonService;
        _similarityCacheService = similarityCacheService;
    }

    partial void OnSelectedMatchChanged(ModelSimilarityPairMatchViewModel? value)
    {
        RefreshSimilarContextImages(value);
        RunVerificationCommand.NotifyCanExecuteChanged();
    }

    partial void OnIsRunningChanged(bool value)
    {
        RunVerificationCommand.NotifyCanExecuteChanged();
    }

    partial void OnSelectedScopeChanged(string value)
    {
        RunVerificationCommand.NotifyCanExecuteChanged();
    }

    [RelayCommand]
    private async Task Run()
    {
        _runCts?.Cancel();
        _runCts?.Dispose();
        _runCts = new CancellationTokenSource();

        IsRunning = true;
        ProgressValue = 0;
        Status = "Starting comparison...";
        SummaryText = string.Empty;
        Matches.Clear();
        SimilarContextImages.Clear();
        SimilarContextHeader = "No match selected.";
        SelectedMatch = null;

        try
        {
            var progress = new Progress<(double pct, string status)>(update =>
            {
                ProgressValue = Math.Clamp(update.pct, 0, 100);
                Status = update.status;
            });

            var scopedEntries = string.Equals(SelectedScope, "Full History (cached)", StringComparison.OrdinalIgnoreCase)
                ? _allEntries
                : new List<HistoryEntry> { _entry };
            var cachedFingerprints = await _similarityCacheService.GetFingerprintsAsync(_historyDir, _runCts.Token);
            var result = await _comparisonService.CompareEntriesAsync(
                scopedEntries,
                _historyDir,
                _imageCacheService,
                Math.Max(0, Threshold),
                _runCts.Token,
                progress,
                cachedFingerprints);

            SummaryText = result.SummaryText;
            var averageDistanceByPair = result.Matches
                .GroupBy(m => BuildOrderedPairKey(m.LeftModel, m.RightModel), StringComparer.OrdinalIgnoreCase)
                .ToDictionary(
                    g => g.Key,
                    g => g.Average(m => m.Distance),
                    StringComparer.OrdinalIgnoreCase);

            var pairStatsByPair = result.PairStats
                .ToDictionary(
                    s => BuildOrderedPairKey(s.LeftModel, s.RightModel),
                    s => s,
                    StringComparer.OrdinalIgnoreCase);

            foreach (var match in result.Matches)
            {
                if (Matches.Count >= 200)
                {
                    break;
                }

                var pairKey = BuildOrderedPairKey(match.LeftModel, match.RightModel);
                pairStatsByPair.TryGetValue(pairKey, out var pairStats);
                averageDistanceByPair.TryGetValue(pairKey, out var avgDistance);
                Matches.Add(new ModelSimilarityPairMatchViewModel(match, _historyDir, _imageCacheService, pairStats, avgDistance));
            }

            if (Matches.Count > 0)
            {
                SelectedMatch = Matches[0];
            }

            Status = _runCts.IsCancellationRequested
                ? "Comparison cancelled."
                : $"Comparison complete. Showing {Matches.Count} match(es).";
            ProgressValue = _runCts.IsCancellationRequested ? ProgressValue : 100;
        }
        catch (OperationCanceledException)
        {
            Status = "Comparison cancelled.";
        }
        catch (Exception ex)
        {
            Status = $"Comparison failed: {ex.Message}";
        }
        finally
        {
            IsRunning = false;
        }
    }

    [RelayCommand]
    private void Cancel()
    {
        _runCts?.Cancel();
    }

    [RelayCommand]
    private async Task ViewLeftDetails(ModelSimilarityPairMatchViewModel? pair)
    {
        if (pair == null || ViewDetailsRequested == null || pair.LeftBitmap == null)
        {
            return;
        }

        await ViewDetailsRequested(pair.LeftEntry, pair.LeftImage, pair.LeftBitmap);
    }

    [RelayCommand]
    private async Task ViewRightDetails(ModelSimilarityPairMatchViewModel? pair)
    {
        if (pair == null || ViewDetailsRequested == null || pair.RightBitmap == null)
        {
            return;
        }

        await ViewDetailsRequested(pair.RightEntry, pair.RightImage, pair.RightBitmap);
    }

    [RelayCommand]
    private async Task ViewSiblingDetails(ModelSimilaritySiblingImageViewModel? sibling)
    {
        if (sibling == null || ViewDetailsRequested == null || sibling.Bitmap == null)
        {
            return;
        }

        await ViewDetailsRequested(sibling.Entry, sibling.Image, sibling.Bitmap);
    }

    [RelayCommand(CanExecute = nameof(CanRunVerification))]
    private async Task RunVerification()
    {
        if (SelectedMatch == null || RunVerificationRequested == null)
        {
            return;
        }

        if (!string.Equals(SelectedMatch.LeftEntry.Id, SelectedMatch.RightEntry.Id, StringComparison.OrdinalIgnoreCase))
        {
            Status = "Verification requires a match from the same history entry.";
            return;
        }

        await RunVerificationRequested(new ModelSimilarityVerificationRequest(
            SelectedMatch.LeftEntry,
            SelectedMatch.LeftImage,
            SelectedMatch.RightImage,
            SelectedMatch.LeftModel,
            SelectedMatch.RightModel,
            SelectedMatch.ComparisonKey));
    }

    private void RefreshSimilarContextImages(ModelSimilarityPairMatchViewModel? pair)
    {
        SimilarContextImages.Clear();
        if (pair == null)
        {
            SimilarContextHeader = "No match selected.";
            return;
        }

        if (!string.Equals(pair.LeftEntry.Id, pair.RightEntry.Id, StringComparison.OrdinalIgnoreCase))
        {
            SimilarContextHeader = "Additional context is only available for matches inside the same history entry.";
            return;
        }

        SimilarContextHeader = $"Other images with same prompt/settings for {pair.LeftModel} and {pair.RightModel}";
        var leftPath = pair.LeftImage.ImagePath ?? string.Empty;
        var rightPath = pair.RightImage.ImagePath ?? string.Empty;
        var sourceEntry = pair.LeftEntry;

        var siblings = (sourceEntry.Images ?? new List<HistoryImage>())
            .Where(img =>
            {
                var modelName = img.GenerationParams?.Model?.Name ?? sourceEntry.InvokeAIModel ?? string.Empty;
                if (!string.Equals(ModelComparisonService.BuildComparableKeyForImage(sourceEntry, img), pair.ComparisonKey, StringComparison.Ordinal))
                {
                    return false;
                }

                return string.Equals(modelName, pair.LeftModel, StringComparison.OrdinalIgnoreCase) ||
                       string.Equals(modelName, pair.RightModel, StringComparison.OrdinalIgnoreCase);
            })
            .Where(img =>
            {
                var imagePath = img.ImagePath ?? string.Empty;
                return !string.Equals(imagePath, leftPath, StringComparison.OrdinalIgnoreCase) &&
                       !string.Equals(imagePath, rightPath, StringComparison.OrdinalIgnoreCase);
            })
            .OrderBy(img => GetSiblingSeedSortKey(img))
            .ThenBy(img =>
            {
                var modelName = img.GenerationParams?.Model?.Name ?? sourceEntry.InvokeAIModel ?? string.Empty;
                if (string.Equals(modelName, pair.LeftModel, StringComparison.OrdinalIgnoreCase))
                {
                    return 0;
                }

                if (string.Equals(modelName, pair.RightModel, StringComparison.OrdinalIgnoreCase))
                {
                    return 1;
                }

                return 2;
            })
            .ThenBy(img => img.ImagePath ?? string.Empty, StringComparer.OrdinalIgnoreCase)
            .Take(24)
            .ToList();

        foreach (var image in siblings)
        {
            SimilarContextImages.Add(new ModelSimilaritySiblingImageViewModel(image, sourceEntry, _historyDir, _imageCacheService));
        }

        if (SimilarContextImages.Count == 0)
        {
            SimilarContextHeader += " (no additional siblings found)";
        }
    }

    private static string BuildOrderedPairKey(string left, string right)
    {
        return string.Compare(left, right, StringComparison.OrdinalIgnoreCase) <= 0
            ? $"{left}||{right}"
            : $"{right}||{left}";
    }

    private static int GetSiblingSeedSortKey(HistoryImage image)
    {
        var p = image.GenerationParams;
        if (p == null)
        {
            return int.MaxValue;
        }

        if (p.Seed != 0)
        {
            return p.Seed;
        }

        if (p.BaseSeed != 0)
        {
            return p.BaseSeed;
        }

        return int.MaxValue - 1;
    }
}

public sealed class ModelSimilarityPairMatchViewModel
{
    public ModelSimilarityPairMatchViewModel(
        ModelSimilarityMatch match,
        string historyDir,
        ImageCacheService imageCacheService,
        ModelPairStats? pairStats,
        double averageDistance)
    {
        LeftEntry = match.LeftEntry;
        RightEntry = match.RightEntry;
        LeftImage = match.LeftImage;
        RightImage = match.RightImage;
        LeftBitmap = LoadBitmapForUi(match.LeftImage, historyDir, imageCacheService);
        RightBitmap = LoadBitmapForUi(match.RightImage, historyDir, imageCacheService);
        LeftModel = match.LeftModel;
        RightModel = match.RightModel;
        ComparisonKey = match.ComparisonKey;
        DistanceText = $"Distance: {match.Distance}";
        WinnerText = match.Winner switch
        {
            ModelSimilarityWinner.Left => $"Winner: {match.LeftModel}",
            ModelSimilarityWinner.Right => $"Winner: {match.RightModel}",
            _ => "Winner: Tie"
        };
        LeftAestheticText = match.LeftAestheticScore.HasValue
            ? $"Aesthetic: {match.LeftAestheticScore.Value:0.##}"
            : string.Empty;
        RightAestheticText = match.RightAestheticScore.HasValue
            ? $"Aesthetic: {match.RightAestheticScore.Value:0.##}"
            : string.Empty;

        if (pairStats != null)
        {
            PairSummaryText = $"{pairStats.MatchCount} match(es) | wins {pairStats.LeftModel}:{pairStats.WinLeft}, {pairStats.RightModel}:{pairStats.WinRight}, ties:{pairStats.Ties} | avg distance {averageDistance:0.##}";
            PairLabelText = BuildPairLabel(pairStats.MatchCount, averageDistance);
        }
        else
        {
            PairSummaryText = $"avg distance {averageDistance:0.##}";
            PairLabelText = BuildPairLabel(1, averageDistance);
        }
    }

    public HistoryEntry LeftEntry { get; }
    public HistoryEntry RightEntry { get; }
    public HistoryImage LeftImage { get; }
    public HistoryImage RightImage { get; }
    public Bitmap? LeftBitmap { get; }
    public Bitmap? RightBitmap { get; }
    public string LeftModel { get; }
    public string RightModel { get; }
    public string ComparisonKey { get; }
    public string DistanceText { get; }
    public string WinnerText { get; }
    public string LeftAestheticText { get; }
    public string RightAestheticText { get; }
    public string PairSummaryText { get; }
    public string PairLabelText { get; }

    private static string BuildPairLabel(int pairMatchCount, double avgDistance)
    {
        if (pairMatchCount >= 4 && avgDistance <= 3)
        {
            return "Likely Equivalent";
        }
        if (pairMatchCount >= 2 && avgDistance <= 4.5)
        {
            return "Very Similar";
        }
        if (avgDistance <= 6)
        {
            return "Similar";
        }

        return "Possibly Similar";
    }

    private static Bitmap? LoadBitmapForUi(HistoryImage image, string historyDir, ImageCacheService imageCacheService)
    {
        if (!string.IsNullOrWhiteSpace(image.ImagePath))
        {
            var loaded = imageCacheService.GetOrLoadForUi(image.ImagePath, 320, historyDir);
            if (loaded != null)
            {
                return loaded;
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
}

public sealed class ModelSimilaritySiblingImageViewModel
{
    public ModelSimilaritySiblingImageViewModel(HistoryImage image, HistoryEntry entry, string historyDir, ImageCacheService imageCacheService)
    {
        Entry = entry;
        Image = image;
        ModelName = image.GenerationParams?.Model?.Name ?? entry.InvokeAIModel ?? "(unknown)";
        SeedText = image.GenerationParams != null
            ? $"Seed {image.GenerationParams.Seed}"
            : string.Empty;
        Bitmap = LoadBitmapForUi(image, historyDir, imageCacheService);
    }

    public HistoryEntry Entry { get; }
    public HistoryImage Image { get; }
    public string ModelName { get; }
    public string SeedText { get; }
    public Bitmap? Bitmap { get; }

    private static Bitmap? LoadBitmapForUi(HistoryImage image, string historyDir, ImageCacheService imageCacheService)
    {
        if (!string.IsNullOrWhiteSpace(image.ImagePath))
        {
            var loaded = imageCacheService.GetOrLoadForUi(image.ImagePath, 220, historyDir);
            if (loaded != null)
            {
                return loaded;
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
}

public sealed record ModelSimilarityVerificationRequest(
    HistoryEntry Entry,
    HistoryImage LeftImage,
    HistoryImage RightImage,
    string LeftModel,
    string RightModel,
    string ComparisonKey);
