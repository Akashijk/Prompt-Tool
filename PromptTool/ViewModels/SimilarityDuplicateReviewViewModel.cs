using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class SimilarityDuplicateReviewViewModel : ObservableObject
{
    [ObservableProperty] private string _summaryText = string.Empty;
    [ObservableProperty] private ObservableCollection<SimilarityDuplicateReviewItemViewModel> _items = new();
    [ObservableProperty] private SimilarityDuplicateReviewItemViewModel? _selectedItem;

    public Func<HistoryEntry, HistoryImage, Bitmap, Task>? ViewDetailsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Bitmap, HistoryEntry, HistoryImage, Bitmap, Task>? CompareRequested { get; set; }

    public SimilarityDuplicateReviewViewModel(
        IReadOnlyList<SimilarityDuplicateReviewItem> items,
        string historyDir,
        ImageCacheService imageCacheService)
    {
        var vms = items
            .Select(i => new SimilarityDuplicateReviewItemViewModel(i, historyDir, imageCacheService))
            .ToList();
        Items = new ObservableCollection<SimilarityDuplicateReviewItemViewModel>(vms);
        if (vms.Count > 0)
        {
            SelectedItem = vms[0];
        }

        var exact = vms.Count(v => v.Distance == 0);
        var nearest = vms.Count > 0 ? vms.Min(v => v.Distance) : 0;
        SummaryText = vms.Count == 0
            ? "No near-duplicate matches found."
            : $"Found {vms.Count} near-duplicate pair(s). Exact matches: {exact}. Nearest distance: {nearest}.";
    }

    [RelayCommand]
    private async Task ViewSourceDetails(SimilarityDuplicateReviewItemViewModel? item)
    {
        if (item?.SourceBitmap == null || ViewDetailsRequested == null)
        {
            return;
        }

        await ViewDetailsRequested(item.SourceEntry, item.SourceImage, item.SourceBitmap);
    }

    [RelayCommand]
    private async Task ViewMatchDetails(SimilarityDuplicateReviewItemViewModel? item)
    {
        if (item?.MatchBitmap == null || ViewDetailsRequested == null)
        {
            return;
        }

        await ViewDetailsRequested(item.MatchEntry, item.MatchImage, item.MatchBitmap);
    }

    [RelayCommand]
    private async Task ComparePair(SimilarityDuplicateReviewItemViewModel? item)
    {
        if (item?.SourceBitmap == null || item.MatchBitmap == null || CompareRequested == null)
        {
            return;
        }

        await CompareRequested(
            item.SourceEntry, item.SourceImage, item.SourceBitmap,
            item.MatchEntry, item.MatchImage, item.MatchBitmap);
    }
}

public sealed class SimilarityDuplicateReviewItemViewModel
{
    public SimilarityDuplicateReviewItemViewModel(
        SimilarityDuplicateReviewItem item,
        string historyDir,
        ImageCacheService imageCacheService)
    {
        SourceEntry = item.SourceEntry;
        SourceImage = item.SourceImage;
        MatchEntry = item.MatchEntry;
        MatchImage = item.MatchImage;
        Distance = item.Distance;
        DistanceText = $"Distance: {item.Distance}";
        SourceModel = item.SourceImage.GenerationParams?.Model?.Name ?? item.SourceEntry.InvokeAIModel ?? "(unknown)";
        MatchModel = item.MatchImage.GenerationParams?.Model?.Name ?? item.MatchEntry.InvokeAIModel ?? "(unknown)";
        SourceSeedText = BuildSeedText(item.SourceImage);
        MatchSeedText = BuildSeedText(item.MatchImage);
        SourceBitmap = LoadBitmap(item.SourceImage, historyDir, imageCacheService, 300);
        MatchBitmap = LoadBitmap(item.MatchImage, historyDir, imageCacheService, 300);
    }

    public HistoryEntry SourceEntry { get; }
    public HistoryImage SourceImage { get; }
    public HistoryEntry MatchEntry { get; }
    public HistoryImage MatchImage { get; }
    public int Distance { get; }
    public string DistanceText { get; }
    public string SourceModel { get; }
    public string MatchModel { get; }
    public string SourceSeedText { get; }
    public string MatchSeedText { get; }
    public Bitmap? SourceBitmap { get; }
    public Bitmap? MatchBitmap { get; }

    private static string BuildSeedText(HistoryImage image)
    {
        var seed = image.GenerationParams?.Seed ?? 0;
        return seed > 0 ? $"Seed {seed}" : string.Empty;
    }

    private static Bitmap? LoadBitmap(HistoryImage image, string historyDir, ImageCacheService imageCacheService, int uiSize)
    {
        if (!string.IsNullOrWhiteSpace(image.ImagePath))
        {
            var bitmap = imageCacheService.GetOrLoadForUi(image.ImagePath, uiSize, historyDir);
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
}

public sealed record SimilarityDuplicateReviewItem(
    HistoryEntry SourceEntry,
    HistoryImage SourceImage,
    HistoryEntry MatchEntry,
    HistoryImage MatchImage,
    int Distance);
