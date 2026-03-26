using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class GalleryImageItem : ObservableObject, IDisposable
{
    public HistoryEntry Entry { get; }
    public HistoryImage Image { get; }

    [ObservableProperty] private Bitmap? _bitmap;
    [ObservableProperty] private bool _isSelected;

    public GalleryImageItem(HistoryEntry entry, HistoryImage image, Bitmap? bitmap)
    {
        Entry = entry;
        Image = image;
        _bitmap = bitmap;
    }

    partial void OnBitmapChanged(Bitmap? oldValue, Bitmap? newValue)
    {
        if (!ReferenceEquals(oldValue, newValue))
        {
            oldValue?.Dispose();
        }
    }

    public string Label
    {
        get
        {
            var baseLabel = string.IsNullOrWhiteSpace(Image.PromptType) ? "Image" : Image.PromptType;
            return string.IsNullOrWhiteSpace(Image.PromptTypeSuffix)
                ? baseLabel
                : $"{baseLabel} · {Image.PromptTypeSuffix}";
        }
    }

    public string ModelLabel
    {
        get
        {
            var gen = HistoryViewerViewModel.GetOrParseGenParams(Image);
            var model = gen?.Model?.Name;
            if (string.IsNullOrWhiteSpace(model)) model = string.Empty;
            if (string.IsNullOrWhiteSpace(Image.UpscaleModel)) return model;
            return string.IsNullOrWhiteSpace(model)
                ? $"Upscale: {Image.UpscaleModel}"
                : $"{model} · Upscale: {Image.UpscaleModel}";
        }
    }

    public string SeedLabel
    {
        get
        {
            var gen = HistoryViewerViewModel.GetOrParseGenParams(Image);
            return gen != null ? $"Seed {gen.Seed}" : string.Empty;
        }
    }

    public string LoraLabel
    {
        get
        {
            var gen = HistoryViewerViewModel.GetOrParseGenParams(Image);
            if (gen?.Loras == null || gen.Loras.Count == 0) return string.Empty;
            var names = gen.Loras
                .Select(l => l.Lora?.Name)
                .Where(n => !string.IsNullOrWhiteSpace(n))
                .Take(2)
                .ToList();
            if (names.Count == 0) return string.Empty;
            return gen.Loras.Count > 2
                ? $"LoRAs {string.Join(", ", names)} +{gen.Loras.Count - 2}"
                : $"LoRAs {string.Join(", ", names)}";
        }
    }

    public void Dispose()
    {
        Bitmap = null;
    }
}

public partial class TemplateImageGroup : ObservableObject
{
    public string Name { get; }
    public bool IsNoTemplate { get; }
    public ObservableCollection<GalleryImageItem> Images { get; }
    [ObservableProperty] private bool _isExpanded = true;

    public TemplateImageGroup(string name, bool isNoTemplate, IEnumerable<GalleryImageItem> images)
    {
        Name = name;
        IsNoTemplate = isNoTemplate;
        Images = new ObservableCollection<GalleryImageItem>(images);
    }

    public int Count => Images.Count;
}

public partial class AllImagesViewerViewModel : ObservableObject, IDisposable
{
    private readonly HistoryManagerService _historyManager;
    private readonly TemplateService _templateService;
    private readonly ImageCacheService _imageCache;
    private readonly HistoryIndexService _historyIndexService;
    private readonly string _historyDir;
    private CancellationTokenSource? _loadCts;
    private readonly string _workflowFilter;
    private readonly List<GalleryImageItem> _selected = new();
    private bool _expandAll = true;

    [ObservableProperty] private ObservableCollection<TemplateImageGroup> _groups = new();
    [ObservableProperty] private string _statusText = string.Empty;
    [ObservableProperty] private bool _canCompare;
    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private string _expandAllLabel = "Collapse All";
    [ObservableProperty] private bool _showFavoritesOnly;

    public Func<IReadOnlyList<GalleryImageItem>, Task>? CompareRequested { get; set; }
    public Action<GalleryImageItem>? ViewLargeRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? UpscaleRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? GenerateMoreRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? SeedVariationsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? LoraVariationsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? ModelVariationsRequested { get; set; }
    public HistoryManagerService HistoryManager => _historyManager;
    public HistoryIndexService HistoryIndexService => _historyIndexService;
    public ImageCacheService ImageCacheService => _imageCache;

    public AllImagesViewerViewModel(HistoryManagerService historyManager, TemplateService templateService, ImageCacheService imageCache, HistoryIndexService historyIndexService, string workflowFilter)
    {
        _historyManager = historyManager;
        _templateService = templateService;
        _imageCache = imageCache;
        _historyIndexService = historyIndexService;
        _historyDir = historyManager.GetHistoryDir();
        _workflowFilter = workflowFilter;
        _ = LoadImagesAsync();
    }

    public Task RefreshAsync()
    {
        return LoadImagesAsync();
    }

    partial void OnShowFavoritesOnlyChanged(bool value)
    {
        _ = LoadImagesAsync();
    }

    [RelayCommand]
    private void ToggleSelect(GalleryImageItem? item)
    {
        if (item == null) return;

        if (item.IsSelected)
        {
            item.IsSelected = false;
            _selected.Remove(item);
        }
        else
        {
            if (_selected.Count >= 2)
            {
                var toClear = _selected[0];
                toClear.IsSelected = false;
                _selected.RemoveAt(0);
            }
            item.IsSelected = true;
            _selected.Add(item);
        }

        CanCompare = _selected.Count == 2;
        StatusText = CanCompare ? "Ready to compare." : "Select two images to compare.";
    }

    [RelayCommand]
    private async Task CompareSelected()
    {
        if (_selected.Count != 2)
        {
            StatusText = "Select exactly two images to compare.";
            return;
        }
        if (CompareRequested != null)
        {
            await CompareRequested(_selected.ToList());
        }
    }

    [RelayCommand]
    private void ToggleExpandAll()
    {
        _expandAll = !_expandAll;
        foreach (var group in Groups)
        {
            group.IsExpanded = _expandAll;
        }
        ExpandAllLabel = _expandAll ? "Collapse All" : "Expand All";
    }

    private async Task LoadImagesAsync()
    {
        _loadCts?.Cancel();
        _loadCts?.Dispose();
        _loadCts = new CancellationTokenSource();
        var token = _loadCts.Token;

        using var perf = PerfLogger.Time("AllImages.Load");
        PerfLogger.ResetTimings("AllImages.Decode");
        IsLoading = true;
        StatusText = "Loading images...";

        var validTemplates = await LoadValidTemplateNamesAsync();
        var result = await Task.Run(() =>
        {
            token.ThrowIfCancellationRequested();
            var entries = _historyManager.GetAllEntries()
                .Where(e => _workflowFilter == "All"
                            || string.IsNullOrWhiteSpace(e.Workflow)
                            || string.Equals(e.Workflow, _workflowFilter, StringComparison.OrdinalIgnoreCase))
                .ToList();

            var grouped = new Dictionary<string, List<GalleryImageItem>>(StringComparer.OrdinalIgnoreCase);
            foreach (var entry in entries)
            {
                var normalized = NormalizeTemplateName(entry.TemplateName);
                var groupKey = normalized != null && validTemplates.Contains(normalized)
                    ? normalized
                    : "(No Template)";

                foreach (var img in entry.Images)
                {
                    if (ShowFavoritesOnly && !img.IsFavorite && !entry.IsFavorite)
                    {
                        continue;
                    }

                    if (!grouped.TryGetValue(groupKey, out var list))
                    {
                        list = new List<GalleryImageItem>();
                        grouped[groupKey] = list;
                    }
                    list.Add(new GalleryImageItem(entry, img, null));
                }
            }

            return grouped
                .Select(kvp =>
                {
                    var group = new TemplateImageGroup(
                        kvp.Key,
                        string.Equals(kvp.Key, "(No Template)", StringComparison.OrdinalIgnoreCase),
                        kvp.Value);
                    group.IsExpanded = _expandAll;
                    return group;
                })
                .OrderBy(g => g.IsNoTemplate)
                .ThenBy(g => g.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();
        });

        if (token.IsCancellationRequested)
        {
            DisposeGroups(result);
            return;
        }

        var oldGroups = Groups;
        Groups = new ObservableCollection<TemplateImageGroup>(result);
        DisposeGroups(oldGroups);
        var total = result.Sum(g => g.Count);
        StatusText = $"Loaded {total} images. Loading thumbnails...";
        ClearSelectionState();
        CanCompare = false;
        PerfLogger.Log($"AllImages.Load groups={result.Count} images={total}");

        _ = Task.Run(() =>
        {
            var loaded = 0;
            foreach (var group in result)
            {
                if (token.IsCancellationRequested) return;
                foreach (var item in group.Images)
                {
                    if (token.IsCancellationRequested) return;
                    var bmp = LoadBitmap(item.Image.ImagePath, 320);
                    if (bmp != null)
                    {
                        Dispatcher.UIThread.Post(() =>
                        {
                            if (token.IsCancellationRequested)
                            {
                                bmp.Dispose();
                                return;
                            }

                            item.Bitmap = bmp;
                        });
                    }
                    loaded++;
                    if (loaded % 25 == 0 || loaded == total)
                    {
                        var progress = loaded;
                        Dispatcher.UIThread.Post(() =>
                        {
                            StatusText = progress == total
                                ? $"Loaded {total} images."
                                : $"Loading thumbnails... {progress}/{total}";
                        });
                    }
                }
            }
            Dispatcher.UIThread.Post(() =>
            {
                IsLoading = false;
                PerfLogger.LogSummary("AllImages.Thumbnails", "AllImages.Decode");
            });
        });
    }

    private async Task<HashSet<string>> LoadValidTemplateNamesAsync()
    {
        if (string.Equals(_workflowFilter, "SFW", StringComparison.OrdinalIgnoreCase))
        {
            var names = await _templateService.GetTemplateNamesAsync("sfw");
            return new HashSet<string>(NormalizeTemplateNames(names), StringComparer.OrdinalIgnoreCase);
        }

        if (string.Equals(_workflowFilter, "NSFW", StringComparison.OrdinalIgnoreCase))
        {
            var names = await _templateService.GetTemplateNamesAsync("nsfw");
            return new HashSet<string>(NormalizeTemplateNames(names), StringComparer.OrdinalIgnoreCase);
        }

        var result = await Task.WhenAll(
            _templateService.GetTemplateNamesAsync("sfw"),
            _templateService.GetTemplateNamesAsync("nsfw"));
        return new HashSet<string>(NormalizeTemplateNames(result.SelectMany(n => n)), StringComparer.OrdinalIgnoreCase);
    }

    private static IEnumerable<string> NormalizeTemplateNames(IEnumerable<string> names)
    {
        foreach (var name in names)
        {
            var normalized = NormalizeTemplateName(name);
            if (!string.IsNullOrWhiteSpace(normalized))
            {
                yield return normalized;
            }
        }
    }

    private static string? NormalizeTemplateName(string? name)
    {
        if (string.IsNullOrWhiteSpace(name)) return null;
        var trimmed = name.Trim();
        var fileName = Path.GetFileNameWithoutExtension(trimmed);
        return string.IsNullOrWhiteSpace(fileName) ? null : fileName;
    }

    private Bitmap? LoadBitmap(string? path, int decodeWidth)
    {
        if (string.IsNullOrWhiteSpace(path)) return null;
        using var _ = PerfLogger.Measure("AllImages.Decode");
        return _imageCache.GetOrLoadForUi(path, decodeWidth, _historyDir);
    }

    private void ClearSelectionState()
    {
        foreach (var item in _selected)
        {
            item.IsSelected = false;
        }

        _selected.Clear();
    }

    private static void DisposeGroups(IEnumerable<TemplateImageGroup>? groups)
    {
        if (groups == null) return;

        foreach (var group in groups)
        {
            foreach (var item in group.Images)
            {
                item.Dispose();
            }
        }
    }

    public void Dispose()
    {
        _loadCts?.Cancel();
        _loadCts?.Dispose();
        _loadCts = null;
        ClearSelectionState();
        DisposeGroups(Groups);
        Groups = new ObservableCollection<TemplateImageGroup>();
    }
}
