using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Diagnostics;
using Avalonia;
using Avalonia.Input.Platform;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.Services;
using System.Text.Json;
using PromptTool.Core.Clients.InvokeAI;

namespace PromptTool.ViewModels;

public partial class HistoryViewerViewModel : ObservableObject
{
    private readonly HistoryManagerService _historyManager;
    private readonly TemplateService _templateService;
    private readonly ImageCacheService _imageCache;
    private readonly HistoryIndexService _historyIndexService;
    private readonly string _historyDir;
    private CancellationTokenSource? _imageLoadCts;
    private IReadOnlyList<VariationPrompt> _variationDefinitions;
    private List<string> _missingVariationKeys = new();
    private bool _fillInProgress;
    private const int CoverPrefetchCount = 30;
    private readonly SemaphoreSlim _refreshGate = new(1, 1);
    private CancellationTokenSource? _refreshCts;
    private readonly SettingsService _settingsService;

    public IClipboard? Clipboard { get; set; }
    public Func<string, Task<bool>>? ConfirmAsync { get; set; }
    public Func<ImageJsonEditRequest, Task<ImageJsonEditResult?>>? EditJsonAsync { get; set; }
    public Func<HistoryEntry, HistoryImage?, string?, string?, Task>? RegenerateRequested { get; set; }
    public Func<HistoryEntry, HistoryImage?, string?, string?, Task>? GenerateNewRequested { get; set; }
    public Func<HistoryEntry, HistoryImage?, string?, string?, Task>? EditRegenerateRequested { get; set; }
    public Func<HistoryEntry, HistoryImage?, Task>? SeedVariationsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage?, Task>? LoraVariationsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage?, Task>? ModelVariationsRequested { get; set; }
    public Func<HistoryEntry, Task>? EnhanceRequested { get; set; }
    public Func<HistoryEntry, IReadOnlyList<string>, Task<FillMissingResult>>? FillMissingVariationsRequested { get; set; }
    public Func<Task>? ShowAllImagesRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? UpscaleRequested { get; set; }
    public Func<string, Task>? ShowPngMetadataRequested { get; set; }

    public HistoryManagerService HistoryManager => _historyManager;
    public TemplateService TemplateService => _templateService;
    public ImageCacheService ImageCacheService => _imageCache;
    public HistoryIndexService HistoryIndexService => _historyIndexService;

    [ObservableProperty] private ObservableCollection<HistoryEntryItem> _historyEntries = new();
    [ObservableProperty] private ObservableCollection<HistoryEntryItem> _selectedHistoryEntries = new();
    [ObservableProperty] private ObservableCollection<HistoryImageItem> _selectedImages = new();
    [ObservableProperty] private HistoryEntryItem? _selectedHistoryEntry;
    [ObservableProperty] private HistoryImageItem? _selectedImageItem;
    [ObservableProperty] private Bitmap? _selectedImage;
    [ObservableProperty] private ObservableCollection<PromptVariant> _promptVariants = new();
    [ObservableProperty] private PromptVariant? _selectedPromptVariant;
    [ObservableProperty] private string _selectedPromptBanner = string.Empty;
    [ObservableProperty] private bool _showSelectedPromptBanner;
    [ObservableProperty] private string _detailsText = string.Empty;
    [ObservableProperty] private string _fullDetailsText = string.Empty;
    [ObservableProperty] private string _statusNote = string.Empty;
    [ObservableProperty] private bool _showFavoritesOnly;
    [ObservableProperty] private string _searchText = string.Empty;
    [ObservableProperty] private string _workflowFilter = "All"; // All, SFW, NSFW
    [ObservableProperty] private bool _canEnhanceSelected;
    [ObservableProperty] private bool _isEnhancing;
    [ObservableProperty] private bool _canFillMissingVariations;
    [ObservableProperty] private bool _canDeleteSelectedImages;
    [ObservableProperty] private bool _canMergeEntries;
    // Result set when dialog closes.
    [ObservableProperty] private HistoryEntry? _dialogResult;
    [ObservableProperty] private string? _loadPromptOverride;

    private readonly List<HistoryImageItem> _selectedForDelete = new();

    // Parameterless constructor for design-time support
    public HistoryViewerViewModel()
    {
        _historyManager = null!;
        _templateService = null!;
        _imageCache = new ImageCacheService();
        _historyIndexService = new HistoryIndexService();
        _historyDir = string.Empty;
        _variationDefinitions = Array.Empty<VariationPrompt>();
        _settingsService = null!;
    }

    public HistoryViewerViewModel(HistoryManagerService historyManager, TemplateService templateService, ImageCacheService imageCache, HistoryIndexService historyIndexService, string? currentWorkflow = null, IReadOnlyList<VariationPrompt>? defaultVariations = null, SettingsService? settingsService = null)
    {
        _historyManager = historyManager;
        _templateService = templateService;
        _imageCache = imageCache;
        _historyIndexService = historyIndexService;
        _historyDir = historyManager.GetHistoryDir();
        _variationDefinitions = defaultVariations ?? Array.Empty<VariationPrompt>();
        _settingsService = settingsService ?? throw new ArgumentNullException(nameof(settingsService));
        if (!string.IsNullOrWhiteSpace(currentWorkflow))
        {
            WorkflowFilter = currentWorkflow.Equals("sfw", StringComparison.OrdinalIgnoreCase) ? "SFW" :
                             currentWorkflow.Equals("nsfw", StringComparison.OrdinalIgnoreCase) ? "NSFW" : "All";
        }
        LoadHistoryEntries();
    }

    public void SetSelectedEntries(IEnumerable<HistoryEntryItem> entries)
    {
        var list = entries.Where(e => e != null).Distinct().ToList();
        SelectedHistoryEntries = new ObservableCollection<HistoryEntryItem>(list);
        CanMergeEntries = SelectedHistoryEntries.Count > 1;
    }

    [RelayCommand]
    private void LoadHistoryEntries()
    {
        _ = LoadHistoryEntriesAsync();
    }

    partial void OnSearchTextChanged(string value) => ScheduleRefresh();
    partial void OnShowFavoritesOnlyChanged(bool value) => ScheduleRefresh();
    partial void OnWorkflowFilterChanged(string value) => ScheduleRefresh();

    [RelayCommand]
    private void Refresh() => _ = LoadHistoryEntriesAsync();

    [RelayCommand]
    private async Task RecoverOrphanImages()
    {
        if (!await ConfirmAsyncSafe("Recover orphan images from disk? This will create new entries for any image folders not present in the history file."))
        {
            StatusNote = "Recovery canceled.";
            return;
        }

        var (entriesCreated, imagesAdded) = _historyManager.RecoverOrphanedImages();
        StatusNote = $"Recovered {imagesAdded} images across {entriesCreated} entries.";
        _ = LoadHistoryEntriesAsync();
    }

    private void ScheduleRefresh()
    {
        _refreshCts?.Cancel();
        _refreshCts?.Dispose();
        _refreshCts = new CancellationTokenSource();
        var token = _refreshCts.Token;
        _ = Task.Run(async () =>
        {
            try
            {
                await Task.Delay(150, token);
                if (!token.IsCancellationRequested)
                {
                    Dispatcher.UIThread.Post(async () => await LoadHistoryEntriesAsync(token));
                }
            }
            catch (OperationCanceledException)
            {
                // ignore
            }
        }, token);
    }

    private async Task LoadHistoryEntriesAsync(CancellationToken cancellationToken = default)
    {
        await _refreshGate.WaitAsync(cancellationToken);
        try
        {
            using var perf = PerfLogger.Time("HistoryViewer.LoadEntries");
            PerfLogger.ResetCounters("HistoryViewer.CoverCacheHit", "HistoryViewer.CoverCacheMiss");
            PerfLogger.ResetTimings("HistoryViewer.Decode");
            var currentEntryId = SelectedHistoryEntry?.Entry.Id;
            var currentImagePath = SelectedImageItem?.Image.ImagePath;

            var search = (SearchText ?? string.Empty).Trim().ToLowerInvariant();
            var entries = await Task.Run(() =>
            {
                cancellationToken.ThrowIfCancellationRequested();
                return _historyManager.GetAllEntries()
                    .Where(e => !ShowFavoritesOnly || e.IsFavorite || e.Images.Any(i => i.IsFavorite))
                    .Where(e => WorkflowFilter == "All" ||
                                string.IsNullOrWhiteSpace(e.Workflow) ||
                                string.Equals(e.Workflow, WorkflowFilter, StringComparison.OrdinalIgnoreCase))
                    .Where(e => string.IsNullOrWhiteSpace(search) ||
                                e.OriginalPrompt.ToLowerInvariant().Contains(search) ||
                                e.ProcessedPrompt.ToLowerInvariant().Contains(search) ||
                                (e.TemplateName ?? string.Empty).ToLowerInvariant().Contains(search) ||
                                (e.Status ?? string.Empty).ToLowerInvariant().Contains(search))
                    .OrderByDescending(e => e.Timestamp)
                    .Select(e => new HistoryEntryItem(e, ResolveCoverPath(e), _imageCache, _historyDir))
                    .ToList();
            }, cancellationToken);

            if (cancellationToken.IsCancellationRequested) return;

            HistoryEntries = new ObservableCollection<HistoryEntryItem>(entries);
            SelectedHistoryEntry = HistoryEntries.FirstOrDefault(h => h.Entry.Id == currentEntryId) ?? HistoryEntries.FirstOrDefault();
            PerfLogger.Log($"HistoryViewer.LoadEntries entries={entries.Count}");
            PerfLogger.LogSummary("HistoryViewer.LoadEntries", "HistoryViewer.Decode");
            _ = PrefetchCoversAsync(entries.Take(CoverPrefetchCount).ToList(), cancellationToken);

            if (SelectedHistoryEntry != null && currentImagePath != null)
            {
                SelectedImageItem = SelectedImages.FirstOrDefault(i =>
                    string.Equals(i.Image.ImagePath, currentImagePath, StringComparison.OrdinalIgnoreCase));
            }
        }
        finally
        {
            _refreshGate.Release();
        }
    }

    partial void OnSelectedHistoryEntryChanged(HistoryEntryItem? value)
    {
        using var perf = PerfLogger.Time("HistoryViewer.LoadEntryImages");
        _imageLoadCts?.Cancel();
        _imageLoadCts?.Dispose();
        _imageLoadCts = new CancellationTokenSource();
        var loadToken = _imageLoadCts.Token;

        if (SelectedImages.Count > 0)
        {
            ClearSelectionTracking(SelectedImages.ToList());
        }

        SelectedImage = null;
        SelectedImages.Clear();
        _selectedForDelete.Clear();
        CanDeleteSelectedImages = false;
        PromptVariants.Clear();
        DetailsText = string.Empty;
        SelectedImageItem = null;
        if (value == null) return;

        foreach (var img in value.Entry.Images)
        {
            var item = new HistoryImageItem(img, null);
            item.PropertyChanged += OnSelectedImagePropertyChanged;
            SelectedImages.Add(item);
        }

        // Fallback to single ImageFilePath or cover for legacy entries
        if (!value.Entry.Images.Any())
        {
            var altPath = value.Entry.ImageFilePath ?? value.Entry.CoverImagePath;
            if (!string.IsNullOrWhiteSpace(altPath))
            {
                var item = new HistoryImageItem(new HistoryImage { ImagePath = altPath }, null);
                item.PropertyChanged += OnSelectedImagePropertyChanged;
                SelectedImages.Add(item);
            }
        }

        SelectedImageItem = SelectedImages.FirstOrDefault();
        if (value.Entry.ImageParameters == null)
        {
            var firstWithParams = value.Entry.Images.FirstOrDefault(i => i.GenerationParams != null);
            if (firstWithParams?.GenerationParams != null)
            {
                value.Entry.ImageParameters = firstWithParams.GenerationParams;
            }
        }
        if (value.Entry.ImageParameters == null)
        {
            var parsedParams = SelectedImages.Select(si => si.Image.GenerationParams).FirstOrDefault(p => p != null);
            if (parsedParams != null)
            {
                value.Entry.ImageParameters = parsedParams;
            }
        }
        PopulatePromptVariants(value.Entry);
        SyncSelectedVariantToImage(SelectedImageItem?.Image);
        UpdatePromptBanner();
        DetailsText = BuildSummaryText(value.Entry, SelectedImageItem?.Image);
        FullDetailsText = BuildDetailsText(value.Entry, SelectedImageItem?.Image);
        CanEnhanceSelected = value.Entry != null &&
                             (value.Entry.VariationPrompts == null || value.Entry.VariationPrompts.Count == 0) &&
                             string.IsNullOrWhiteSpace(value.Entry.EnhancedPrompt);
        UpdateMissingVariationState(value.Entry!);
        PerfLogger.Log($"HistoryViewer.LoadEntryImages images={SelectedImages.Count}");
        PerfLogger.LogSummary("HistoryViewer.LoadEntryImages", "HistoryViewer.Decode");

        _ = LoadSelectedImagesAsync(SelectedImages.ToList(), loadToken);
    }

    private Task LoadSelectedImagesAsync(IReadOnlyList<HistoryImageItem> items, CancellationToken token)
    {
        if (items.Count == 0)
        {
            return Task.CompletedTask;
        }

        return Task.Run(async () =>
        {
            foreach (var item in items)
            {
                if (token.IsCancellationRequested) break;
                if (item.Bitmap != null) continue;
                var bmp = LoadBitmap(item.Image.ImagePath, 320);
                if (bmp == null) continue;
                await Dispatcher.UIThread.InvokeAsync(() =>
                {
                    if (!token.IsCancellationRequested)
                    {
                        item.Bitmap = bmp;
                        if (ReferenceEquals(SelectedImageItem, item))
                        {
                            SelectedImage = bmp;
                        }
                    }
                }, DispatcherPriority.Background);
            }
        }, token);
    }

    partial void OnSelectedImageItemChanged(HistoryImageItem? value)
    {
        SelectedImage = value?.Bitmap;

        if (SelectedHistoryEntry != null)
        {
            DetailsText = BuildSummaryText(SelectedHistoryEntry.Entry, value?.Image);
            FullDetailsText = BuildDetailsText(SelectedHistoryEntry.Entry, value?.Image);
            SyncSelectedVariantToImage(value?.Image);
            UpdatePromptBanner();
        }
    }

    private void OnSelectedImagePropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName != nameof(HistoryImageItem.IsSelected))
        {
            return;
        }

        if (sender is not HistoryImageItem item)
        {
            return;
        }

        if (item.IsSelected)
        {
            if (!_selectedForDelete.Contains(item))
            {
                _selectedForDelete.Add(item);
            }
        }
        else
        {
            _selectedForDelete.Remove(item);
        }

        CanDeleteSelectedImages = _selectedForDelete.Count > 0;
    }

    private void ClearSelectionTracking(IReadOnlyList<HistoryImageItem> items)
    {
        foreach (var item in items)
        {
            item.PropertyChanged -= OnSelectedImagePropertyChanged;
        }
    }

    private static string? ResolveCoverPath(HistoryEntry entry)
    {
        return entry.CoverImagePath
                   ?? entry.Images.FirstOrDefault()?.ImagePath
                   ?? entry.ImageFilePath;
    }

    private async Task PrefetchCoversAsync(IReadOnlyList<HistoryEntryItem> items, CancellationToken cancellationToken)
    {
        foreach (var item in items)
        {
            if (cancellationToken.IsCancellationRequested) break;
            await item.WarmCoverAsync();
        }
    }

    private Bitmap? LoadBitmap(string? path, int? decodeWidth = null)
    {
        if (string.IsNullOrWhiteSpace(path)) return null;
        using var _ = PerfLogger.Measure("HistoryViewer.Decode");
        return _imageCache.GetOrLoadForUi(path, decodeWidth, _historyDir);
    }

    internal static Bitmap? CloneBitmapForUi(Bitmap? bitmap)
    {
        return UiBitmapHelper.CloneForUi(bitmap);
    }

    private string BuildDetailsText(HistoryEntry entry, HistoryImage? image)
    {
        var genParams = GetOrParseGenParams(image)
                        ?? entry.ImageParameters
                        ?? entry.Images.FirstOrDefault(i => i.GenerationParams != null)?.GenerationParams;
        var prompt = FirstNonEmpty(SelectedPromptVariant?.Prompt, genParams?.Prompt, image?.Prompt, entry.ProcessedPrompt, entry.EnhancedPrompt, entry.OriginalPrompt);
        var model = ResolveModelName(entry, image);
        var lines = new[]
        {
            $"Timestamp: {entry.Timestamp:g}",
            $"Template: {WithPlaceholder(entry.TemplateName, "(none)")}",
            $"Status: {WithPlaceholder(entry.Status, "(unknown)")}",
            $"Workflow: {WithPlaceholder(entry.Workflow, "(default)")}",
            $"Model: {WithPlaceholder(model)}",
            $"Prompt: {WithPlaceholder(prompt)}",
            $"Negative Prompt: {WithPlaceholder(genParams?.NegativePrompt)}",
            $"Ollama: {WithPlaceholder(entry.OllamaModel, "(none)")}",
            //$"InvokeAI: {WithPlaceholder(entry.InvokeAIModel, "(none)")}",
            image != null ? $"Image Prompt Type: {WithPlaceholder(image.PromptType, "(unknown)")}" : null,
            FormatGenParams(image, entry)
        }.Where(l => !string.IsNullOrWhiteSpace(l));

        return string.Join(Environment.NewLine + Environment.NewLine, lines);
    }

    public static string BuildDetailsTextForImage(HistoryEntry entry, HistoryImage? image)
    {
        var genParams = GetOrParseGenParams(image)
                        ?? entry.ImageParameters
                        ?? entry.Images.FirstOrDefault(i => i.GenerationParams != null)?.GenerationParams;
        var prompt = ResolvePromptForImage(entry, image);
        var model = ResolveModelName(entry, image);
        var lines = new[]
        {
            $"Timestamp: {entry.Timestamp:g}",
            $"Template: {WithPlaceholder(entry.TemplateName, "(none)")}",
            $"Status: {WithPlaceholder(entry.Status, "(unknown)")}",
            $"Workflow: {WithPlaceholder(entry.Workflow, "(default)")}",
            $"Model: {WithPlaceholder(model)}",
            $"Prompt: {WithPlaceholder(prompt)}",
            $"Negative Prompt: {WithPlaceholder(genParams?.NegativePrompt)}",
            $"Ollama: {WithPlaceholder(entry.OllamaModel, "(none)")}",
            image != null ? $"Image Prompt Type: {WithPlaceholder(image.PromptType, "(unknown)")}" : null,
            FormatGenParams(image, entry)
        }.Where(l => !string.IsNullOrWhiteSpace(l));

        return string.Join(Environment.NewLine + Environment.NewLine, lines);
    }

    internal static string ResolvePromptForImage(HistoryEntry entry, HistoryImage? image)
    {
        var gen = GetOrParseGenParams(image);
        var prompt = FirstNonEmpty(image?.Prompt, gen?.Prompt);
        if (!string.IsNullOrWhiteSpace(prompt))
        {
            return prompt;
        }

        var promptType = image?.PromptType ?? string.Empty;
        if (promptType.StartsWith("Variation:", StringComparison.OrdinalIgnoreCase))
        {
            static string NormalizeVariationName(string value)
                => string.Join(' ', value.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries));

            var name = promptType.Split(':', 2).ElementAtOrDefault(1)?.Trim() ?? string.Empty;
            if (!string.IsNullOrWhiteSpace(name) && entry.VariationPrompts != null &&
                entry.VariationPrompts.TryGetValue(name, out var stored))
            {
                return stored ?? string.Empty;
            }

            var match = entry.Images.FirstOrDefault(i =>
                i.PromptType != null &&
                i.PromptType.StartsWith("Variation:", StringComparison.OrdinalIgnoreCase) &&
                string.Equals(NormalizeVariationName(i.PromptType.Split(':', 2).ElementAtOrDefault(1)?.Trim() ?? string.Empty),
                              NormalizeVariationName(name),
                              StringComparison.OrdinalIgnoreCase));
            if (match != null)
            {
                return FirstNonEmpty(match.Prompt, match.GenerationParams?.Prompt) ?? string.Empty;
            }
        }

        return FirstNonEmpty(entry.ProcessedPrompt, entry.EnhancedPrompt, entry.OriginalPrompt) ?? string.Empty;
    }

    internal static string ResolveGeneratedPromptForImage(HistoryEntry entry, HistoryImage? image)
    {
        var gen = GetOrParseGenParams(image);
        var prompt = FirstNonEmpty(gen?.Prompt, image?.Prompt);
        if (!string.IsNullOrWhiteSpace(prompt))
        {
            return prompt;
        }

        var promptType = image?.PromptType ?? string.Empty;
        if (promptType.StartsWith("Variation:", StringComparison.OrdinalIgnoreCase))
        {
            static string NormalizeVariationName(string value)
                => string.Join(' ', value.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries));

            var name = promptType.Split(':', 2).ElementAtOrDefault(1)?.Trim() ?? string.Empty;
            if (!string.IsNullOrWhiteSpace(name) && entry.VariationPrompts != null &&
                entry.VariationPrompts.TryGetValue(name, out var stored))
            {
                return stored ?? string.Empty;
            }

            var match = entry.Images.FirstOrDefault(i =>
                i.PromptType != null &&
                i.PromptType.StartsWith("Variation:", StringComparison.OrdinalIgnoreCase) &&
                string.Equals(NormalizeVariationName(i.PromptType.Split(':', 2).ElementAtOrDefault(1)?.Trim() ?? string.Empty),
                              NormalizeVariationName(name),
                              StringComparison.OrdinalIgnoreCase));
            if (match != null)
            {
                return FirstNonEmpty(match.Prompt, match.GenerationParams?.Prompt) ?? string.Empty;
            }
        }

        return string.Empty;
    }

    private string BuildSummaryText(HistoryEntry entry, HistoryImage? image)
    {
        return BuildDetailsText(entry, image, SelectedPromptVariant?.Prompt);
    }

    internal static string BuildDetailsText(HistoryEntry entry, HistoryImage? image, string? promptOverride = null)
    {
        var gen = GetOrParseGenParams(image)
                  ?? entry.ImageParameters
                  ?? entry.Images.FirstOrDefault(i => i.GenerationParams != null)?.GenerationParams;
        var resolvedPrompt = ResolveGeneratedPromptForImage(entry, image);
        var prompt = FirstNonEmpty(promptOverride, resolvedPrompt, gen?.Prompt, image?.Prompt, entry.ProcessedPrompt, entry.EnhancedPrompt, entry.OriginalPrompt);
        var lines = new List<string?>
        {
            $"Timestamp: {entry.Timestamp:g}",
            $"Template: {WithPlaceholder(entry.TemplateName, "(none)")}",
            $"Model: {WithPlaceholder(ResolveModelName(entry, image), "(unknown)")}",
            !string.IsNullOrWhiteSpace(image?.PromptType) ? $"Type: {image?.PromptType}" : null,
            !string.IsNullOrWhiteSpace(prompt) ? $"Prompt: {prompt}" : "Prompt: (not saved)",
            gen != null && !string.IsNullOrWhiteSpace(gen.NegativePrompt) ? $"Negative: {gen.NegativePrompt}" : "Negative: (not saved)",
            gen != null && gen.Loras.Any()
                ? $"LoRAs: {string.Join(", ", gen.Loras.Select(l => $"{l.Lora.Name} ({l.Weight:0.##})"))}"
                : "LoRAs: (none)",
            gen != null
                ? $"Seed: {gen.Seed}, CFG: {gen.CfgScale}, Steps: {gen.Steps}, Size: {gen.Width}x{gen.Height}, Scheduler: {(!string.IsNullOrWhiteSpace(gen.Scheduler) ? NormalizeSchedulerDisplay(gen.Scheduler) : gen.Scheduler)}, Rescale: {gen.CfgRescaleMultiplier}, SaveToGallery: {gen.SaveToGallery}"
                : "(no generation parameters saved)",
            image?.AestheticScore.HasValue == true ? $"Aesthetic Score: {image.AestheticScore:0.00}" : null,
            image?.HeuristicScore.HasValue == true ? $"Heuristic Score: {image.HeuristicScore:0.0}" : null,
            image?.SharpnessScore.HasValue == true ? $"Sharpness Score: {image.SharpnessScore:0.0}" : null,
            image?.PromptMatchScore.HasValue == true ? $"Prompt Match: {image.PromptMatchScore:0.0}" : null,
            image?.CompositeScore.HasValue == true ? $"Composite Score: {image.CompositeScore:0.0}" : null
        };

        return string.Join(Environment.NewLine + Environment.NewLine, lines.Where(l => !string.IsNullOrWhiteSpace(l)));
    }

    public static string ResolveModelName(HistoryEntry entry, HistoryImage? image)
    {
        // Parse JSON once so downstream consumers (including this method) see populated GenerationParams
        _ = GetOrParseGenParams(image);

        // Prefer image-specific model if available
        if (image?.GenerationParams?.Model?.Name is { } model && !string.IsNullOrWhiteSpace(model))
        {
            return model;
        }
        if (entry.ImageParameters?.Model?.Name is { } entryModel && !string.IsNullOrWhiteSpace(entryModel))
        {
            return entryModel;
        }

        if (!string.IsNullOrWhiteSpace(entry.InvokeAIModel)) return entry.InvokeAIModel;
        if (!string.IsNullOrWhiteSpace(entry.OllamaModel)) return entry.OllamaModel;
        return string.Empty;
    }

    private static string FormatGenParams(HistoryImage? image, HistoryEntry entry)
    {
        var parsed = GetOrParseGenParams(image) ?? entry.ImageParameters;
        var baseText = parsed != null ? FormatFromParams(parsed) : string.Empty;
        var upscale = FormatUpscaleMeta(image);
        if (string.IsNullOrWhiteSpace(upscale)) return baseText;
        if (string.IsNullOrWhiteSpace(baseText)) return upscale;
        return $"{baseText}, {upscale}";
    }

    private static string FormatFromParams(InvokeAIGenerationParams p)
    {
        var sched = string.IsNullOrWhiteSpace(p.Scheduler) ? null : NormalizeSchedulerDisplay(p.Scheduler);
        var parts = new[]
        {
            $"Seed: {p.Seed}",
            p.UsedRandomSeed ? "Seed Source: random" : "Seed Source: manual",
            p.BaseSeed != 0 ? $"Base Seed: {p.BaseSeed}" : null,
            $"CFG: {p.CfgScale}",
            $"Steps: {p.Steps}",
            $"Size: {p.Width}x{p.Height}",
            !string.IsNullOrWhiteSpace(sched ?? p.Scheduler) ? $"Scheduler: {sched ?? p.Scheduler}" : null,
            $"Rescale: {p.CfgRescaleMultiplier}",
            $"SaveToGallery: {p.SaveToGallery}",
            !string.IsNullOrWhiteSpace(p.NegativePrompt) ? $"Negative: {p.NegativePrompt}" : null,
            !string.IsNullOrWhiteSpace(p.NegativeStylePrompt) ? $"Negative Style: {p.NegativeStylePrompt}" : null,
            !string.IsNullOrWhiteSpace(p.PositiveStylePrompt) ? $"Positive Style: {p.PositiveStylePrompt}" : null,
            p.Loras.Any() ? $"LoRAs: {string.Join(", ", p.Loras.Select(l => $"{l.Lora.Name} ({l.Weight:0.##})"))}" : "LoRAs: (none)",
            !string.IsNullOrWhiteSpace(p.BaseModelType) ? $"Base: {p.BaseModelType}" : null,
            p.Model != null && (!string.IsNullOrWhiteSpace(p.Model.Base) || !string.IsNullOrWhiteSpace(p.Model.Format))
                ? $"Model Base/Format: {p.Model.Base} / {p.Model.Format}"
                : null,
            !string.IsNullOrWhiteSpace(p.VaeUsedName) ? $"VAE: {p.VaeUsedName}" : null,
            p.AutoClearedModelCacheBetweenModels ? "Auto-cleared model cache between models: true" : null
        }.Where(x => !string.IsNullOrWhiteSpace(x));
        return string.Join(", ", parts);
    }

    private static string FormatUpscaleMeta(HistoryImage? image)
    {
        if (image == null) return string.Empty;
        if (image.UpscaleModel == null && image.UpscaleScale == null && image.UpscaleTileSize == null && image.UpscaleFitToMultipleOf8 == null)
        {
            return string.Empty;
        }

        var parts = new List<string> { "Upscale" };
        if (image.UpscaleScale.HasValue)
        {
            parts.Add($"{image.UpscaleScale:0.#}x");
        }
        if (!string.IsNullOrWhiteSpace(image.UpscaleModel))
        {
            parts.Add($"Model: {image.UpscaleModel}");
        }
        if (image.UpscaleTileSize.HasValue)
        {
            parts.Add($"Tile: {image.UpscaleTileSize}");
        }
        if (image.UpscaleFitToMultipleOf8.HasValue)
        {
            parts.Add($"FitTo8: {image.UpscaleFitToMultipleOf8.Value}");
        }

        return string.Join(" ", parts);
    }

    internal static InvokeAIGenerationParams? GetOrParseGenParams(HistoryImage? image)
    {
        if (image == null) return null;
        if (image.GenerationParams != null) return image.GenerationParams;

        if (string.IsNullOrWhiteSpace(image.GenerationParamsJson)) return null;

        try
        {
            using var doc = JsonDocument.Parse(image.GenerationParamsJson);
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return null;

            var map = new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);
            foreach (var prop in root.EnumerateObject())
            {
                map[Normalize(prop.Name)] = prop.Value;
            }

            bool TryGet(string key, out JsonElement value) => map.TryGetValue(Normalize(key), out value);
            string Normalize(string name) => name.Replace("_", string.Empty).ToLowerInvariant();

            var p = new InvokeAIGenerationParams();

            if (TryGet("prompt", out var prompt) && prompt.ValueKind == JsonValueKind.String) p.Prompt = prompt.GetString() ?? p.Prompt;
            if (string.IsNullOrWhiteSpace(image.Prompt) && !string.IsNullOrWhiteSpace(p.Prompt)) image.Prompt = p.Prompt;
            if (TryGet("positivestyleprompt", out var ps) && ps.ValueKind == JsonValueKind.String) p.PositiveStylePrompt = ps.GetString();
            if (TryGet("negativestyleprompt", out var ns) && ns.ValueKind == JsonValueKind.String) p.NegativeStylePrompt = ns.GetString();
            if (TryGet("negativeprompt", out var neg) && neg.ValueKind == JsonValueKind.String) p.NegativePrompt = neg.GetString();
            if (TryGet("basemodeltype", out var bmt) && bmt.ValueKind == JsonValueKind.String) p.BaseModelType = bmt.GetString();
            if (TryGet("usedrandomseed", out var urs) && urs.ValueKind is JsonValueKind.True or JsonValueKind.False) p.UsedRandomSeed = urs.GetBoolean();
            if (TryGet("baseseed", out var bs) && bs.TryGetInt32(out var bsVal)) p.BaseSeed = bsVal;
            if (TryGet("autoclearedmodelcachebetweenmodels", out var ac) && ac.ValueKind is JsonValueKind.True or JsonValueKind.False) p.AutoClearedModelCacheBetweenModels = ac.GetBoolean();
            if (TryGet("vaeusedname", out var vaeUsed) && vaeUsed.ValueKind == JsonValueKind.String) p.VaeUsedName = vaeUsed.GetString();
            if (TryGet("usepromptasstylewhenempty", out var styleFallback) && styleFallback.ValueKind is JsonValueKind.True or JsonValueKind.False)
            {
                p.UsePromptAsStyleWhenEmpty = styleFallback.GetBoolean();
            }

            if (TryGet("steps", out var steps) && steps.TryGetInt32(out var st)) p.Steps = st;
            if (TryGet("cfgscale", out var cfg) && cfg.TryGetDouble(out var c)) p.CfgScale = c;
            if (TryGet("width", out var w) && w.TryGetInt32(out var wi)) p.Width = wi;
            if (TryGet("height", out var h) && h.TryGetInt32(out var he)) p.Height = he;
            if (TryGet("seed", out var seed) && seed.TryGetInt32(out var s)) p.Seed = s;
            if (TryGet("scheduler", out var sch) && sch.ValueKind == JsonValueKind.String) p.Scheduler = sch.GetString() ?? p.Scheduler;
            if (TryGet("cfgrescalemultiplier", out var rescale) && rescale.TryGetDouble(out var r)) p.CfgRescaleMultiplier = r;
            if (TryGet("savetogallery", out var save) && save.ValueKind is JsonValueKind.True or JsonValueKind.False) p.SaveToGallery = save.GetBoolean();
            if (TryGet("vae", out var vaeElem))
            {
                if (vaeElem.ValueKind == JsonValueKind.Object)
                {
                    var name = vaeElem.TryGetProperty("name", out var vn) ? vn.GetString() : null;
                    var key = vaeElem.TryGetProperty("key", out var vk) ? vk.GetString() : null;
                    var hash = vaeElem.TryGetProperty("hash", out var vh) ? vh.GetString() : null;
                    p.VaeUsedName = name ?? key ?? hash ?? p.VaeUsedName;
                }
                else if (vaeElem.ValueKind == JsonValueKind.String)
                {
                    p.VaeUsedName = vaeElem.GetString();
                }
            }

            if (TryGet("model", out var modelElem) || TryGet("modelname", out modelElem))
            {
                if (modelElem.ValueKind == JsonValueKind.Object)
                {
                    var name = modelElem.TryGetProperty("name", out var mn) ? mn.GetString() : null;
                    var @base = modelElem.TryGetProperty("base", out var mb) ? mb.GetString() : null;
                    var format = modelElem.TryGetProperty("format", out var mf) ? mf.GetString() : null;
                    var key = modelElem.TryGetProperty("key", out var mk) ? mk.GetString() : null;
                    var hash = modelElem.TryGetProperty("hash", out var mh) ? mh.GetString() : null;
                    p.Model = new InvokeAIModel { Name = name ?? "", Base = @base ?? "", Format = format ?? "", Key = key ?? "", Hash = hash ?? "" };
                }
                else if (modelElem.ValueKind == JsonValueKind.String)
                {
                    p.Model = new InvokeAIModel { Name = modelElem.GetString() ?? "" };
                }
            }

            if (TryGet("loras", out var lorasElem) && lorasElem.ValueKind == JsonValueKind.Array)
            {
                foreach (var l in lorasElem.EnumerateArray())
                {
                    InvokeAIModel? loraModel = null;
                    var weight = 0.75;

                    if (l.ValueKind == JsonValueKind.String)
                    {
                        loraModel = new InvokeAIModel { Name = l.GetString() ?? "" };
                    }
                    else if (l.ValueKind == JsonValueKind.Object)
                    {
                        var lProps = new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);
                        foreach (var prop in l.EnumerateObject())
                        {
                            lProps[prop.Name] = prop.Value;
                        }
                        bool TryGetL(string key, out JsonElement value) => lProps.TryGetValue(key, out value);

                        if (TryGetL("weight", out var wt) && wt.TryGetDouble(out var wgt))
                        {
                            weight = wgt;
                        }

                        if (TryGetL("lora", out var loraObj) || TryGetL("lora_object", out loraObj))
                        {
                            if (loraObj.ValueKind == JsonValueKind.Object)
                            {
                                var loraProps = new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);
                                foreach (var prop in loraObj.EnumerateObject())
                                {
                                    loraProps[prop.Name] = prop.Value;
                                }
                                loraProps.TryGetValue("name", out var ln);
                                loraProps.TryGetValue("base", out var lb);
                                loraProps.TryGetValue("key", out var lk);
                                loraProps.TryGetValue("hash", out var lh);
                                var name = ln.ValueKind == JsonValueKind.String ? ln.GetString() : null;
                                var baseVal = lb.ValueKind == JsonValueKind.String ? lb.GetString() : null;
                                var key = lk.ValueKind == JsonValueKind.String ? lk.GetString() : null;
                                var hash = lh.ValueKind == JsonValueKind.String ? lh.GetString() : null;
                                loraModel = new InvokeAIModel { Name = name ?? "", Base = baseVal ?? "", Key = key ?? "", Hash = hash ?? "" };
                            }
                            else if (loraObj.ValueKind == JsonValueKind.String)
                            {
                                loraModel = new InvokeAIModel { Name = loraObj.GetString() ?? "" };
                            }
                        }

                        if (loraModel == null)
                        {
                            var name = TryGetL("name", out var ln) && ln.ValueKind == JsonValueKind.String ? ln.GetString() : null;
                            if (string.IsNullOrWhiteSpace(name) && TryGetL("lora_name", out var ln2) && ln2.ValueKind == JsonValueKind.String)
                            {
                                name = ln2.GetString();
                            }
                            var baseVal = TryGetL("base", out var lb) && lb.ValueKind == JsonValueKind.String ? lb.GetString() : null;
                            var key = TryGetL("key", out var lk) && lk.ValueKind == JsonValueKind.String ? lk.GetString() : null;
                            var hash = TryGetL("hash", out var lh) && lh.ValueKind == JsonValueKind.String ? lh.GetString() : null;
                            if (!string.IsNullOrWhiteSpace(name))
                            {
                                loraModel = new InvokeAIModel { Name = name ?? "", Base = baseVal ?? "", Key = key ?? "", Hash = hash ?? "" };
                            }
                        }
                    }

                    if (loraModel != null)
                    {
                        p.Loras.Add(new LoraParameter { Lora = loraModel, Weight = weight });
                    }
                }
            }

            image.GenerationParams = p;
            return p;
        }
        catch
        {
            return null;
        }
    }

    private static string NormalizeSchedulerDisplay(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return value;
        var tokens = value.Split('_', StringSplitOptions.RemoveEmptyEntries);
        if (tokens.Length == 0) return value;

        string MapToken(string token, bool isFirst)
        {
            if (isFirst)
            {
                return token.ToLowerInvariant() switch
                {
                    "dpmpp" => "DPM++",
                    "dpm" => "DPM",
                    "kdpm" => "DPM",
                    "ddpm" => "DDPM",
                    "ddim" => "DDIM",
                    "deis" => "DEIS",
                    "euler" => "Euler",
                    "heun" => "Heun",
                    "pndm" => "PNDM",
                    "lms" => "LMS",
                    "unipc" => "UniPC",
                    "tcd" => "TCD",
                    _ => token.ToUpperInvariant()
                };
            }

            return token.ToLowerInvariant() switch
            {
                "k" => "Karras",
                "sde" => "SDE",
                "a" => "Ancestral",
                "2m" => "2M",
                "3m" => "3M",
                "2s" => "2S",
                _ => token.ToUpperInvariant()
            };
        }

        var parts = tokens.Select((t, idx) => MapToken(t, idx == 0));
        return string.Join(' ', parts);
    }

    private static string WithPlaceholder(string? value, string placeholder = "(not saved)")
    {
        return string.IsNullOrWhiteSpace(value) ? placeholder : value;
    }

    internal static string? FirstNonEmpty(params string?[] values)
    {
        foreach (var value in values)
        {
            if (!string.IsNullOrWhiteSpace(value))
            {
                return value;
            }
        }
        return null;
    }

    private void PopulatePromptVariants(HistoryEntry entry)
    {
        var variants = new List<PromptVariant>();
        var labels = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        void AddVariant(string label, string? prompt, string source)
        {
            if (!labels.Add(label)) return;
            var p = FirstNonEmpty(prompt, "(not saved)");
            variants.Add(new PromptVariant(label, p ?? "(not saved)", source));
        }

        static string NormalizeVariationName(string name)
            => string.Join(' ', name.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries));

        // Only keep processed/enhanced; hide original from dropdown
        if (!string.IsNullOrWhiteSpace(entry.ProcessedPrompt)) AddVariant("Processed", entry.ProcessedPrompt, "processed");
        if (!string.IsNullOrWhiteSpace(entry.EnhancedPrompt)) AddVariant("Enhanced", entry.EnhancedPrompt, "enhanced");

        var variationNames = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (entry.VariationPrompts != null)
        {
            foreach (var kvp in entry.VariationPrompts)
            {
                var normalized = NormalizeVariationName(kvp.Key);
                if (!variationNames.ContainsKey(normalized))
                {
                    variationNames[normalized] = kvp.Key.Trim();
                }
            }
        }

        foreach (var img in entry.Images.Where(i => !string.IsNullOrWhiteSpace(i.PromptType) &&
                                                    i.PromptType.StartsWith("Variation:", StringComparison.OrdinalIgnoreCase)))
        {
            var name = img.PromptType!.Split(':', 2).ElementAtOrDefault(1)?.Trim();
            if (!string.IsNullOrWhiteSpace(name))
            {
                var normalized = NormalizeVariationName(name);
                if (!variationNames.ContainsKey(normalized))
                {
                    variationNames[normalized] = name;
                }
            }
        }

        foreach (var kvp in variationNames)
        {
            var name = kvp.Value;
            var prompt = entry.VariationPrompts != null && entry.VariationPrompts.TryGetValue(name, out var stored)
                ? stored
                : null;

            if (string.IsNullOrWhiteSpace(prompt))
            {
                var imagePrompt = entry.Images
                    .Where(i => i.PromptType != null && i.PromptType.StartsWith("Variation:", StringComparison.OrdinalIgnoreCase))
                    .FirstOrDefault(i =>
                        string.Equals(NormalizeVariationName(i.PromptType!.Split(':', 2).ElementAtOrDefault(1)?.Trim() ?? string.Empty),
                                      NormalizeVariationName(name),
                                      StringComparison.OrdinalIgnoreCase));

                prompt = FirstNonEmpty(imagePrompt?.Prompt, imagePrompt?.GenerationParams?.Prompt);
            }

            AddVariant($"Variation: {name}", prompt, $"variation:{name}");
        }

        // Fallback: include any unique prompts found on images, but skip obvious originals
        for (int idx = 0; idx < entry.Images.Count; idx++)
        {
            var img = entry.Images[idx];
            var pt = img.PromptType ?? string.Empty;
            if (pt.StartsWith("Original", StringComparison.OrdinalIgnoreCase) ||
                pt.StartsWith("Generated", StringComparison.OrdinalIgnoreCase) ||
                pt.StartsWith("Variation:", StringComparison.OrdinalIgnoreCase) ||
                pt.StartsWith("Upscale:", StringComparison.OrdinalIgnoreCase) ||
                pt.Equals("Image", StringComparison.OrdinalIgnoreCase))
            {
                continue; // avoid flooding with originals
            }

            var label = !string.IsNullOrWhiteSpace(pt) ? pt : $"Image {idx + 1}";
            var prompt = FirstNonEmpty(img.Prompt, img.GenerationParams?.Prompt);
            AddVariant(label, prompt, $"image:{idx}");
        }

        // Deduplicate by source/label to avoid duplicates
        variants = variants
            .GroupBy(v => v.Source ?? v.Label, StringComparer.OrdinalIgnoreCase)
            .Select(g => g.First())
            .ToList();

        PromptVariants = new ObservableCollection<PromptVariant>(variants);
        SelectedPromptVariant = PromptVariants.FirstOrDefault();

        if (SelectedHistoryEntry != null && SelectedHistoryEntries.Count == 0)
        {
            SelectedHistoryEntries.Add(SelectedHistoryEntry);
            CanMergeEntries = SelectedHistoryEntries.Count > 1;
        }
    }

    [RelayCommand]
    private async Task MergeSelectedEntries()
    {
        if (SelectedHistoryEntries.Count < 2)
        {
            StatusNote = "Select at least two entries to merge.";
            return;
        }

        var target = SelectedHistoryEntry ?? SelectedHistoryEntries.FirstOrDefault();
        if (target == null)
        {
            StatusNote = "Select a target history entry.";
            return;
        }

        var sourceEntries = SelectedHistoryEntries.Where(e => e.Entry.Id != target.Entry.Id).ToList();
        if (sourceEntries.Count == 0)
        {
            StatusNote = "Select at least two distinct entries to merge.";
            return;
        }

        if (ConfirmAsync != null)
        {
            var ok = await ConfirmAsync($"Merge {sourceEntries.Count + 1} entries into \"{target.Template}\"?\n\nThis will move all images into the target entry and delete the other entries.");
            if (!ok) return;
        }

        var appended = 0;
        foreach (var entry in sourceEntries)
        {
            if (entry.Entry.Images.Count > 0)
            {
                _historyManager.AppendImages(target.Entry.Id, entry.Entry.Images);
                appended += entry.Entry.Images.Count;
            }
        }

        foreach (var entry in sourceEntries)
        {
            _historyManager.DeleteEntry(entry.Entry.Id);
        }

        StatusNote = $"Merged {sourceEntries.Count} entries into \"{target.Template}\" ({appended} images).";
        _ = LoadHistoryEntriesAsync();
    }

    private void UpdateMissingVariationState(HistoryEntry entry)
    {
        var defaults = _variationDefinitions.Select(v => v.Key).ToHashSet(StringComparer.OrdinalIgnoreCase);
        // Variations already present
        if (entry.VariationPrompts != null)
        {
            foreach (var key in entry.VariationPrompts.Keys)
            {
                defaults.Remove(key);
            }
        }
        // Variations present via images
        foreach (var img in entry.Images.Where(i => !string.IsNullOrWhiteSpace(i.PromptType) &&
                                                    i.PromptType.StartsWith("Variation:", StringComparison.OrdinalIgnoreCase)))
        {
            var name = img.PromptType!.Split(':', 2).ElementAtOrDefault(1)?.Trim();
            if (!string.IsNullOrWhiteSpace(name))
            {
                defaults.Remove(name);
            }
        }

        _missingVariationKeys = defaults.ToList();
        var hasBasePrompt = !string.IsNullOrWhiteSpace(entry.OriginalPrompt) ||
                            !string.IsNullOrWhiteSpace(entry.ProcessedPrompt) ||
                            !string.IsNullOrWhiteSpace(entry.EnhancedPrompt);
        CanFillMissingVariations = hasBasePrompt && _missingVariationKeys.Count > 0;
    }

    private void SyncSelectedVariantToImage(HistoryImage? image)
    {
        if (image == null || PromptVariants.Count == 0) return;

        // Match by prompt type (e.g., Variation:Name) or by prompt text
        var byType = !string.IsNullOrWhiteSpace(image.PromptType)
            ? PromptVariants.FirstOrDefault(v => v.Label.Equals(image.PromptType, StringComparison.OrdinalIgnoreCase))
            : null;

        if (byType != null)
        {
            SelectedPromptVariant = byType;
            return;
        }

        var byPrompt = !string.IsNullOrWhiteSpace(image.Prompt)
            ? PromptVariants.FirstOrDefault(v => string.Equals(v.Prompt, image.Prompt, StringComparison.Ordinal))
            : null;

        if (byPrompt != null)
        {
            SelectedPromptVariant = byPrompt;
        }
    }


    [RelayCommand]
    private void LoadPromptFromHistory()
    {
        if (SelectedHistoryEntry == null) return;
        var fallback = SelectedHistoryEntry.Entry.ProcessedPrompt ?? SelectedHistoryEntry.Entry.OriginalPrompt;
        LoadPromptOverride = FirstNonEmpty(SelectedPromptVariant?.Prompt, fallback);
        DialogResult = SelectedHistoryEntry.Entry;
    }

    [RelayCommand]
    private void ToggleFavorite()
    {
        if (SelectedHistoryEntry == null) return;

        if (SelectedImageItem?.Image != null)
        {
            SelectedImageItem.Image.IsFavorite = !SelectedImageItem.Image.IsFavorite;
        }
        else
        {
            SelectedHistoryEntry.Entry.IsFavorite = !SelectedHistoryEntry.Entry.IsFavorite;
        }

        if (SelectedHistoryEntry.Entry.Images.Any(i => i.IsFavorite))
        {
            SelectedHistoryEntry.Entry.IsFavorite = true;
        }

        if (SelectedImageItem?.Image != null)
        {
            _historyManager.UpdateImage(SelectedHistoryEntry.Entry.Id, SelectedImageItem.Image);
        }
        else
        {
            _historyManager.UpdateEntry(SelectedHistoryEntry.Entry);
        }
        LoadHistoryEntries();
    }

    [RelayCommand]
    private void ToggleEntryFavorite(HistoryEntryItem? item)
    {
        if (item == null) return;
        item.Entry.IsFavorite = !item.Entry.IsFavorite;
        if (item.Entry.Images.Any(i => i.IsFavorite))
        {
            item.Entry.IsFavorite = true;
        }
        _historyManager.UpdateEntry(item.Entry);
        LoadHistoryEntries();
    }

    [RelayCommand]
    private void ToggleImageFavorite(HistoryImageItem? item)
    {
        if (item == null || SelectedHistoryEntry == null) return;
        item.Image.IsFavorite = !item.Image.IsFavorite;
        if (SelectedHistoryEntry.Entry.Images.Any(i => i.IsFavorite))
        {
            SelectedHistoryEntry.Entry.IsFavorite = true;
        }
        _historyManager.UpdateImage(SelectedHistoryEntry.Entry.Id, item.Image);
        LoadHistoryEntries();
    }

    [RelayCommand]
    private void SetEntryFavorite()
    {
        if (SelectedHistoryEntry == null) return;
        SelectedHistoryEntry.Entry.IsFavorite = true;
        _historyManager.UpdateEntry(SelectedHistoryEntry.Entry);
        LoadHistoryEntries();
    }

    [RelayCommand]
    private void SetCoverImage(HistoryImageItem? item)
    {
        if (item == null || SelectedHistoryEntry == null) return;
        var path = item.Image.ImagePath;
        if (string.IsNullOrWhiteSpace(path)) return;
        SelectedHistoryEntry.Entry.CoverImagePath = path;
        _historyManager.UpdateEntry(SelectedHistoryEntry.Entry);
        LoadHistoryEntries();
    }

    [RelayCommand]
    private async Task DeleteImage(HistoryImageItem? item)
    {
        if (item == null || SelectedHistoryEntry == null) return;
        if (!await ConfirmAsyncSafe("Delete this image?")) return;
        if (_historyManager.DeleteImage(SelectedHistoryEntry.Entry.Id, item.Image.ImagePath))
        {
            LoadHistoryEntries();
            StatusNote = "Image deleted.";
        }
        else
        {
            StatusNote = "Failed to delete image.";
        }
    }

    [RelayCommand]
    private async Task DeleteSelectedImages()
    {
        if (_selectedForDelete.Count == 0)
        {
            StatusNote = "Select one or more images to delete.";
            return;
        }

        if (!await ConfirmAsyncSafe($"Delete {_selectedForDelete.Count} selected image(s)? This cannot be undone."))
        {
            StatusNote = "Delete canceled.";
            return;
        }

        if (SelectedHistoryEntry == null)
        {
            StatusNote = "No history entry selected.";
            return;
        }

        var toDelete = _selectedForDelete.ToList();
        if (SelectedHistoryEntry.Entry.Images.Count <= toDelete.Count)
        {
            if (!await ConfirmAsyncSafe("This will remove all images from the entry. The entry will remain (empty). Continue?"))
            {
                StatusNote = "Delete canceled.";
                return;
            }
        }
        var deleted = 0;
        var failed = 0;

        foreach (var item in toDelete)
        {
            var path = item.Image.ImagePath;
            if (string.IsNullOrWhiteSpace(path))
            {
                failed++;
                continue;
            }

            if (_historyManager.DeleteImage(SelectedHistoryEntry.Entry.Id, path))
            {
                deleted++;
            }
            else
            {
                failed++;
            }
        }

        _selectedForDelete.Clear();
        CanDeleteSelectedImages = false;
        LoadHistoryEntries();

        StatusNote = failed > 0
            ? $"Deleted {deleted} images. {failed} failed."
            : $"Deleted {deleted} images.";
    }

    [RelayCommand]
    private async Task DeleteEntry()
    {
        if (SelectedHistoryEntry == null) return;
        if (!await ConfirmAsyncSafe("Delete this history entry and its images?")) return;
        if (_historyManager.DeleteEntry(SelectedHistoryEntry.Entry.Id))
        {
            SelectedHistoryEntry = null;
            LoadHistoryEntries();
            StatusNote = "Entry deleted.";
        }
        else
        {
            StatusNote = "Failed to delete entry.";
        }
    }

    [RelayCommand]
    private async Task CopyPrompt()
    {
        var text = FirstNonEmpty(
            SelectedPromptVariant?.Prompt,
            SelectedImageItem?.Image.Prompt,
            SelectedHistoryEntry?.Entry.ProcessedPrompt,
            SelectedHistoryEntry?.Entry.EnhancedPrompt,
            SelectedHistoryEntry?.Entry.OriginalPrompt);
        if (string.IsNullOrWhiteSpace(text)) return;
        if (Clipboard != null)
        {
            await Clipboard.SetTextAsync(text);
        }
    }

    [RelayCommand]
    private async Task CopyGenerationJson(HistoryImageItem? item)
    {
        var image = item?.Image ?? SelectedImageItem?.Image;
        string? json = null;

        if (image != null)
        {
            json = !string.IsNullOrWhiteSpace(image.GenerationParamsJson)
                ? image.GenerationParamsJson
                : image.GenerationParams != null
                    ? JsonSerializer.Serialize(image.GenerationParams, new JsonSerializerOptions { WriteIndented = true })
                    : null;
        }

        if (json == null && SelectedHistoryEntry?.Entry != null)
        {
            var e = SelectedHistoryEntry.Entry;
            json = e.ImageParameters != null
                ? JsonSerializer.Serialize(e.ImageParameters, new JsonSerializerOptions { WriteIndented = true })
                : null;
        }

        if (string.IsNullOrWhiteSpace(json))
        {
            StatusNote = "No generation parameters to copy.";
            return;
        }

        if (Clipboard != null)
        {
            await Clipboard.SetTextAsync(json);
            StatusNote = "Generation JSON copied to clipboard.";
        }
        else
        {
            StatusNote = "Clipboard unavailable; could not copy JSON.";
        }
    }

    [RelayCommand]
    private async Task UpscaleImage(HistoryImageItem? item)
    {
        if (UpscaleRequested == null || SelectedHistoryEntry == null || item?.Image == null) return;
        await UpscaleRequested(SelectedHistoryEntry.Entry, item.Image);
    }

    [RelayCommand]
    private async Task EditGenerationJson(HistoryImageItem? item)
    {
        if (EditJsonAsync == null)
        {
            StatusNote = "JSON editor not available.";
            return;
        }
        if (SelectedHistoryEntry == null)
        {
            StatusNote = "Select an entry first.";
            return;
        }

        var image = item?.Image ?? SelectedImageItem?.Image;
        if (image == null)
        {
            StatusNote = "Select an image to edit.";
            return;
        }

        var json = !string.IsNullOrWhiteSpace(image.GenerationParamsJson)
            ? image.GenerationParamsJson
            : image.GenerationParams != null
                ? JsonSerializer.Serialize(image.GenerationParams, new JsonSerializerOptions { WriteIndented = true })
                : "{}";

        var request = new ImageJsonEditRequest(image.PromptType ?? "", image.Prompt ?? "", json);
        var edited = await EditJsonAsync(request);
        if (edited == null)
        {
            StatusNote = "Edit canceled.";
            return;
        }

        var normalizedJson = string.IsNullOrWhiteSpace(edited.Value.GenerationParamsJson)
            ? "{}"
            : edited.Value.GenerationParamsJson;

        try
        {
            using var doc = JsonDocument.Parse(normalizedJson);
            if (doc.RootElement.ValueKind != JsonValueKind.Object)
            {
                StatusNote = "JSON must be an object.";
                return;
            }
            normalizedJson = JsonSerializer.Serialize(doc.RootElement, new JsonSerializerOptions { WriteIndented = true });
        }
        catch (Exception ex)
        {
            StatusNote = $"Invalid JSON: {ex.Message}";
            return;
        }

        image.PromptType = string.IsNullOrWhiteSpace(edited.Value.PromptType) ? null : edited.Value.PromptType.Trim();
        image.Prompt = string.IsNullOrWhiteSpace(edited.Value.Prompt) ? null : edited.Value.Prompt.Trim();
        image.GenerationParamsJson = normalizedJson;
        image.GenerationParams = null;
        _ = GetOrParseGenParams(image);
        _historyManager.UpdateImage(SelectedHistoryEntry.Entry.Id, image);
        LoadHistoryEntries();
        StatusNote = "Generation JSON updated.";
    }

    [RelayCommand]
    private async Task GenerateMore()
    {
        if (SelectedHistoryEntry == null) return;
        if (RegenerateRequested != null)
        {
            await RegenerateRequested(SelectedHistoryEntry.Entry, SelectedImageItem?.Image, SelectedPromptVariant?.Prompt, SelectedPromptVariant?.Label);
            LoadHistoryEntries();
            return;
        }
        StatusNote = "Regenerate flow not configured.";
    }

    [RelayCommand]
    private async Task GenerateNew()
    {
        if (SelectedHistoryEntry == null) return;
        if (GenerateNewRequested != null)
        {
            await GenerateNewRequested(SelectedHistoryEntry.Entry, SelectedImageItem?.Image, SelectedPromptVariant?.Prompt, SelectedPromptVariant?.Label);
            LoadHistoryEntries();
            return;
        }
        StatusNote = "Generate new flow not configured.";
    }

    [RelayCommand]
    private async Task Enhance()
    {
        if (SelectedHistoryEntry == null) return;
        if (IsEnhancing) return;
        if (EnhanceRequested != null)
        {
            IsEnhancing = true;
            StatusNote = "Enhancing prompt...";
            try
            {
                await EnhanceRequested(SelectedHistoryEntry.Entry);
            }
            finally
            {
                IsEnhancing = false;
            }
            return;
        }
        StatusNote = "Enhance flow not configured.";
    }

    [RelayCommand]
    private async Task EditAndRegenerate()
    {
        if (SelectedHistoryEntry == null) return;
        if (EditRegenerateRequested != null)
        {
            await EditRegenerateRequested(SelectedHistoryEntry.Entry, SelectedImageItem?.Image, SelectedPromptVariant?.Prompt, SelectedPromptVariant?.Label);
            LoadHistoryEntries();
            return;
        }
        StatusNote = "Edit/regenerate flow not configured.";
    }

    [RelayCommand]
    private async Task GenerateSeedVariations(HistoryImageItem? imageItem)
    {
        if (SelectedHistoryEntry == null) return;
        var image = imageItem?.Image ?? SelectedImageItem?.Image;
        if (SeedVariationsRequested != null)
        {
            await SeedVariationsRequested(SelectedHistoryEntry.Entry, image);
            LoadHistoryEntries();
            return;
        }
        StatusNote = "Seed variation flow not configured.";
    }

    [RelayCommand]
    private async Task GenerateLoraVariations(HistoryImageItem? imageItem)
    {
        if (SelectedHistoryEntry == null) return;
        var image = imageItem?.Image ?? SelectedImageItem?.Image;
        if (LoraVariationsRequested != null)
        {
            await LoraVariationsRequested(SelectedHistoryEntry.Entry, image);
            LoadHistoryEntries();
            return;
        }
        StatusNote = "LoRA variation flow not configured.";
    }

    [RelayCommand]
    private async Task ShowAllImages()
    {
        if (ShowAllImagesRequested != null)
        {
            await ShowAllImagesRequested();
            return;
        }
        StatusNote = "All images view not configured.";
    }

    [RelayCommand]
    private async Task FillMissingVariations()
    {
        if (_fillInProgress) return;
        if (SelectedHistoryEntry == null)
        {
            StatusNote = "Select an entry first.";
            return;
        }
        if (_missingVariationKeys.Count == 0)
        {
            StatusNote = "No missing variations detected.";
            return;
        }
        if (FillMissingVariationsRequested != null)
        {
            try
            {
                _fillInProgress = true;
                StatusNote = "Generating missing enhancements...";
                var result = await FillMissingVariationsRequested(SelectedHistoryEntry.Entry, _missingVariationKeys.AsReadOnly());
                if (result.Outcome == FillMissingOutcome.Updated)
                {
                    StatusNote = result.Message;
                    LoadHistoryEntries();
                }
                else if (result.Outcome == FillMissingOutcome.NoChanges)
                {
                    StatusNote = result.Message;
                }
                else
                {
                    StatusNote = result.Message;
                }
            }
            catch (Exception ex)
            {
                StatusNote = $"Generate missing enhancements failed: {ex.Message}";
            }
            finally
            {
                _fillInProgress = false;
            }
        }
        else
        {
            StatusNote = "Fill-missing flow not configured.";
        }
    }

    [RelayCommand]
    private void PruneMissingImages()
    {
        var pruned = _historyManager.PruneMissingImageEntries();
        LoadHistoryEntries();
        StatusNote = $"Pruned {pruned} missing images.";
    }

    [RelayCommand]
    private void GarbageCollectOrphans()
    {
        var count = _historyManager.GarbageCollectOrphanedImages();
        LoadHistoryEntries();
        StatusNote = $"Deleted {count} orphaned files.";
    }

    [RelayCommand]
    private void ViewLarge(HistoryImageItem? item)
    {
        if (item == null || item.Bitmap == null || SelectedHistoryEntry == null) return;
        var details = BuildDetailsText(SelectedHistoryEntry.Entry, item.Image);
        OnLargeImageRequested?.Invoke(new HistoryImagePreviewContext(item, SelectedHistoryEntry.Entry, details));
    }

    public event Action<HistoryImagePreviewContext?>? OnLargeImageRequested;

    private async Task<bool> ConfirmAsyncSafe(string message)
    {
        if (ConfirmAsync == null) return true;
        try
        {
            return await ConfirmAsync(message);
        }
        catch
        {
            return false;
        }
    }

    [RelayCommand]
    private void OpenImage(HistoryImageItem? item)
    {
        var path = item?.Image.ImagePath;
        if (string.IsNullOrWhiteSpace(path)) return;
        var full = Path.IsPathRooted(path) ? path : Path.Combine(_historyDir, path);
        if (!File.Exists(full)) return;
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = full,
                UseShellExecute = true
            });
        }
        catch (Exception ex)
        {
            if (_settingsService.Settings.Verbose) Console.Error.WriteLine($"Error opening image: {ex.Message}");
        }
    }

    [RelayCommand]
    private async Task ShowPngMetadata(HistoryImageItem? item)
    {
        var path = item?.Image.ImagePath ?? SelectedImageItem?.Image.ImagePath;
        if (string.IsNullOrWhiteSpace(path))
        {
            StatusNote = "No image selected.";
            return;
        }
        var full = Path.IsPathRooted(path) ? path : Path.Combine(_historyDir, path);
        if (!File.Exists(full))
        {
            StatusNote = "Image file not found.";
            return;
        }
        if (ShowPngMetadataRequested != null)
        {
            await ShowPngMetadataRequested(full);
            return;
        }
        StatusNote = "PNG metadata viewer not configured.";
    }

    [RelayCommand]
    private void OpenContainingFolder(HistoryImageItem? item)
    {
        var path = item?.Image.ImagePath;
        if (string.IsNullOrWhiteSpace(path)) return;
        var full = Path.IsPathRooted(path) ? path : Path.Combine(_historyDir, path);
        if (!File.Exists(full)) return;
        var dir = Path.GetDirectoryName(full);
        if (string.IsNullOrWhiteSpace(dir)) return;
        try
        {
            if (OperatingSystem.IsMacOS())
            {
                Process.Start("open", dir);
            }
            else if (OperatingSystem.IsWindows())
            {
                Process.Start("explorer.exe", dir);
            }
            else
            {
                Process.Start("xdg-open", dir);
            }
        }
        catch (Exception ex)
        {
            if (_settingsService.Settings.Verbose) Console.Error.WriteLine($"Error opening folder: {ex.Message}");
        }
    }

    [RelayCommand]
    private void Cancel()
    {
        // Ensure the dialog closes even if DialogResult is already null.
        DialogResult = null;
        OnPropertyChanged(nameof(DialogResult));
    }

    partial void OnSelectedPromptVariantChanged(PromptVariant? value)
    {
        if (SelectedHistoryEntry != null)
        {
            UpdatePromptBanner();
            DetailsText = BuildSummaryText(SelectedHistoryEntry.Entry, SelectedImageItem?.Image);
            FullDetailsText = BuildDetailsText(SelectedHistoryEntry.Entry, SelectedImageItem?.Image);
        }
    }

    private void UpdatePromptBanner()
    {
        if (SelectedPromptVariant == null)
        {
            SelectedPromptBanner = string.Empty;
            ShowSelectedPromptBanner = false;
            return;
        }

        SelectedPromptBanner = $"Viewing prompt: {SelectedPromptVariant.Label}";
        ShowSelectedPromptBanner = true;
    }
}

public partial class HistoryEntryItem : ObservableObject
{
    public HistoryEntry Entry { get; }

    private Bitmap? _cover;
    private bool _coverRequested;
    private bool _coverLoading;
    private readonly string? _coverPath;
    private readonly ImageCacheService _imageCache;
    private readonly string _historyDir;

    public HistoryEntryItem(HistoryEntry entry, string? coverPath, ImageCacheService imageCache, string historyDir)
    {
        Entry = entry;
        _coverPath = coverPath;
        _imageCache = imageCache;
        _historyDir = historyDir;
    }

    public Bitmap? Cover
    {
        get
        {
            if (!_coverRequested)
            {
                _coverRequested = true;
                _ = LoadCoverAsync();
            }
            return _cover;
        }
    }

    public string Prompt => string.IsNullOrWhiteSpace(Entry.ProcessedPrompt) ? Entry.OriginalPrompt : Entry.ProcessedPrompt;
    public string Status => Entry.Status ?? "generated";
    public string Template => Entry.TemplateName ?? "";
    public DateTime Timestamp => Entry.Timestamp;
    public bool IsFavorite => Entry.IsFavorite || Entry.Images.Any(i => i.IsFavorite);
    public string Model => HistoryViewerViewModel.ResolveModelName(Entry, Entry.Images.FirstOrDefault()) switch
    {
        { Length: > 0 } m => m,
        _ => "(unknown)"
    };

    public Task WarmCoverAsync()
    {
        return LoadCoverAsync();
    }

    private Task LoadCoverAsync()
    {
        if (_coverLoading || _cover != null || string.IsNullOrWhiteSpace(_coverPath)) return Task.CompletedTask;
        _coverLoading = true;
        return Task.Run(() =>
        {
            try
            {
                var bmp = _imageCache.GetOrLoadForUi(_coverPath, 128, _historyDir);
                if (bmp != null)
                {
                    Dispatcher.UIThread.Post(() =>
                    {
                        _cover = bmp;
                        OnPropertyChanged(nameof(Cover));
                    });
                }
            }
            finally
            {
                _coverLoading = false;
            }
        });
    }
}

public partial class HistoryImageItem : ObservableObject
{
    public HistoryImage Image { get; }
    [ObservableProperty] private Bitmap? _bitmap;
    [ObservableProperty] private bool _isSelected;

    public HistoryImageItem(HistoryImage image, Bitmap? bitmap)
    {
        Image = image;
        _bitmap = bitmap;
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
}

public record HistoryImagePreviewContext(HistoryImageItem Item, HistoryEntry Entry, string DetailsText);

public record PromptVariant(string Label, string Prompt, string Source);

public readonly record struct ImageJsonEditRequest(string PromptType, string Prompt, string GenerationParamsJson);
public readonly record struct ImageJsonEditResult(string PromptType, string Prompt, string GenerationParamsJson);
