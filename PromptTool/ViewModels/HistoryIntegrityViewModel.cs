using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class HistoryIntegrityViewModel : ObservableObject
{
    private readonly HistoryManagerService _historyManager;
    private readonly ImageCacheService _imageCache;
    private readonly string _historyDir;

    [ObservableProperty] private string _reportText = "Run a scan to see history issues.";
    [ObservableProperty] private int _missingImageCount;
    [ObservableProperty] private int _thumbnailFailureCount;
    [ObservableProperty] private int _orphanRecoveredEntries;
    [ObservableProperty] private int _orphanRecoveredImages;

    public HistoryIntegrityViewModel(HistoryManagerService historyManager, ImageCacheService imageCache)
    {
        _historyManager = historyManager;
        _imageCache = imageCache;
        _historyDir = historyManager.GetHistoryDir();
    }

    [RelayCommand]
    private void ScanMissing()
    {
        var missing = FindMissingImages();
        MissingImageCount = missing.Count;
        ReportText = missing.Count == 0
            ? "No missing images detected."
            : $"Missing images: {missing.Count}{Environment.NewLine}{string.Join(Environment.NewLine, missing.Take(20))}";
    }

    [RelayCommand]
    private void PruneMissing()
    {
        var removed = _historyManager.PruneMissingImageEntries();
        MissingImageCount = 0;
        ReportText = removed == 0
            ? "No missing images to remove."
            : $"Removed {removed} missing image references.";
    }

    [RelayCommand]
    private void RecoverOrphans()
    {
        var result = _historyManager.RecoverOrphanedImages();
        OrphanRecoveredEntries = result.EntriesCreated;
        OrphanRecoveredImages = result.ImagesAdded;
        ReportText = result.ImagesAdded == 0
            ? "No orphaned images were found."
            : $"Recovered {result.ImagesAdded} images across {result.EntriesCreated} entries.";
    }

    [RelayCommand]
    private void VerifyThumbnails()
    {
        var failures = 0;
        foreach (var entry in _historyManager.GetAllEntries())
        {
            foreach (var image in entry.Images)
            {
                if (string.IsNullOrWhiteSpace(image.ImagePath))
                {
                    failures++;
                    continue;
                }
                var bmp = _imageCache.GetOrLoad(image.ImagePath, decodeWidth: 320, baseDir: _historyDir);
                if (bmp == null)
                {
                    failures++;
                }
            }
        }

        ThumbnailFailureCount = failures;
        ReportText = failures == 0
            ? "All thumbnails decoded successfully."
            : $"Thumbnail decode failures: {failures}.";
    }

    private List<string> FindMissingImages()
    {
        var missing = new List<string>();
        foreach (var entry in _historyManager.GetAllEntries())
        {
            foreach (var image in entry.Images)
            {
                if (string.IsNullOrWhiteSpace(image.ImagePath))
                {
                    missing.Add($"{entry.Id}: (missing path)");
                    continue;
                }
                var full = Path.IsPathRooted(image.ImagePath)
                    ? image.ImagePath
                    : Path.Combine(_historyDir, image.ImagePath);
                if (!File.Exists(full))
                {
                    missing.Add($"{entry.Id}: {image.ImagePath}");
                }
            }
        }
        return missing;
    }
}
