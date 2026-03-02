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

public enum LoraMatchMode
{
    Any,
    All
}

public enum AnalyticsSortMode
{
    None,
    Favorites,
    HeuristicScoreDesc,
    HeuristicScoreAsc,
    AestheticScoreDesc,
    AestheticScoreAsc,
    DateDesc,
    DateAsc
}

public partial class FilterOption : ObservableObject
{
    [ObservableProperty] private string _name = "";
    [ObservableProperty] private int _count;
    [ObservableProperty] private bool _isSelected;
    [ObservableProperty] private bool _isVisible = true;
    [ObservableProperty] private string _displayName = "";

    public FilterOption(string name)
    {
        _name = name;
        _displayName = name;
    }

    partial void OnCountChanged(int value)
    {
        DisplayName = $"{Name} ({value})";
    }

    partial void OnNameChanged(string value)
    {
        DisplayName = $"{value} ({Count})";
    }
}

public partial class AnalyticsImageItem : ObservableObject
{
    public HistoryEntry Entry { get; }
    public HistoryImage Image { get; }
    private InvokeAIGenerationParams? _genCache;
    private bool _genParsed;
    private string? _modelName;
    private List<string>? _loraNames;
    [ObservableProperty] private Bitmap? _bitmap;
    [ObservableProperty] private bool _isSelected;
    [ObservableProperty] private double? _score;
    [ObservableProperty] private double? _aestheticScore;
    [ObservableProperty] private int? _aestheticScoreMs;
    [ObservableProperty] private double? _sharpnessScore;
    [ObservableProperty] private double? _promptMatchScore;
    [ObservableProperty] private double? _compositeScore;
    [ObservableProperty] private bool _hasScore;

    public AnalyticsImageItem(HistoryEntry entry, HistoryImage image, Bitmap? bitmap)
    {
        Entry = entry;
        Image = image;
        _bitmap = bitmap;
        // Use the property setter to ensure OnAestheticScoreChanged is triggered
        AestheticScore = image.AestheticScore;
        AestheticScoreMs = image.AestheticScoreMs;
        SharpnessScore = image.SharpnessScore;
        PromptMatchScore = image.PromptMatchScore;
        CompositeScore = image.CompositeScore;
        UpdateScoreFlags(); // Ensure initial flags are set correctly
    }

    partial void OnScoreChanged(double? value)
    {
        UpdateScoreFlags();
        OnPropertyChanged(nameof(DisplayScore));
        OnPropertyChanged(nameof(HeuristicScoreLabel));
        OnPropertyChanged(nameof(HasHeuristicScore));
    }

    partial void OnAestheticScoreChanged(double? value)
    {
        UpdateScoreFlags();
        OnPropertyChanged(nameof(DisplayScore));
        OnPropertyChanged(nameof(AestheticScoreLabel));
        OnPropertyChanged(nameof(HasAestheticScore));
    }

    partial void OnSharpnessScoreChanged(double? value)
    {
        UpdateScoreFlags();
    }

    partial void OnCompositeScoreChanged(double? value)
    {
        UpdateScoreFlags();
    }

    partial void OnAestheticScoreMsChanged(int? value)
    {
        OnPropertyChanged(nameof(AestheticScoreLabel));
    }

    public string Prompt
    {
        get
        {
            return HistoryViewerViewModel.ResolveGeneratedPromptForImage(Entry, Image);
        }
    }

    public string ModelLabel
    {
        get
        {
            return GetModelName();
        }
    }

    public string SeedLabel
    {
        get
        {
            var gen = GetGen();
            return gen != null ? $"Seed {gen.Seed}" : string.Empty;
        }
    }

    public string LoraLabel
    {
        get
        {
            var loras = GetLoraNames();
            if (loras.Count == 0) return string.Empty;
            var gen = GetGen();
            if (gen?.Loras == null || gen.Loras.Count == 0) return string.Empty;
            return string.Join(", ", gen.Loras
                .Where(l => l.Lora != null && !string.IsNullOrWhiteSpace(l.Lora.Name))
                .Select(l => $"{l.Lora!.Name} ({l.Weight:0.##})"));
        }
    }

    private InvokeAIGenerationParams? GetGen()
    {
        if (_genParsed) return _genCache;
        _genParsed = true;
        _genCache = HistoryViewerViewModel.GetOrParseGenParams(Image);
        return _genCache;
    }

    public string GetModelName()
    {
        if (!string.IsNullOrWhiteSpace(_modelName)) return _modelName!;
        var gen = GetGen();
        _modelName = gen?.Model?.Name ?? Entry.InvokeAIModel ?? string.Empty;
        return _modelName;
    }

    public IReadOnlyList<string> GetLoraNames()
    {
        if (_loraNames != null) return _loraNames;
        var gen = GetGen();
        _loraNames = gen?.Loras?
            .Select(l => l.Lora?.Name)
            .Where(n => !string.IsNullOrWhiteSpace(n))
            .Select(n => n!)
            .ToList() ?? new List<string>();
        return _loraNames;
    }

    public bool IsFavorite => Image.IsFavorite || Entry.IsFavorite;

    public string TemplateLabel => Entry.TemplateName ?? "(No Template)";
    public string PromptTypeLabel => Image.PromptType ?? "Image";
    public string PromptTypeDisplay => string.IsNullOrWhiteSpace(Image.PromptTypeSuffix)
        ? PromptTypeLabel
        : $"{PromptTypeLabel} · {Image.PromptTypeSuffix}";
    public bool HasAestheticScore => AestheticScore.HasValue;
    public bool HasHeuristicScore => Score.HasValue;
    public double? DisplayScore => AestheticScore ?? Score;
    public string AestheticScoreLabel => AestheticScore.HasValue ? $"Aesthetic {AestheticScore:0.0}" : string.Empty;
    public string HeuristicScoreLabel => Score.HasValue ? $"Heuristic {Score:0.0}" : string.Empty;

    private void UpdateScoreFlags()
    {
        HasScore = AestheticScore.HasValue || Score.HasValue || SharpnessScore.HasValue || CompositeScore.HasValue || PromptMatchScore.HasValue;
    }

    public void NotifyFavoriteChanged()
    {
        OnPropertyChanged(nameof(IsFavorite));
    }
}

public sealed record ScoreByModelConfirmRequest(
    string ModelName,
    int UnscoredCount,
    int TotalCount,
    double AverageSeconds);

public sealed record ScoreByModelConfirmResult(
    bool Confirmed,
    bool IncludeAlreadyScored);

public partial class AnalyticsStudioViewModel : ObservableObject
{
    private readonly HistoryManagerService _historyManager;
    private readonly TemplateService _templateService;
    private readonly AestheticScoringService _aestheticScoringService;
    private readonly PromptMatchScoringService _promptMatchScoringService;
    private readonly SettingsService _settingsService;
    private readonly ImageCacheService _imageCache;
    private readonly HistoryIndexService _historyIndexService;
    private readonly string _historyDir;
    private readonly string _workflowFilter;
    private readonly SemaphoreSlim _refreshGate = new(1, 1);
    private CancellationTokenSource? _refreshCts;
    private CancellationTokenSource? _scoreCts;
    private CancellationTokenSource? _thumbLoadCts;
    private volatile int _thumbPriorityStart;
    private volatile int _thumbPriorityEnd;
    private int _thumbPriorityDirty;
    private bool _enableScoringInitialized;
    private readonly Dictionary<HistoryImage, AnalyticsImageItem> _itemCache = new();

    [ObservableProperty] private ObservableCollection<FilterOption> _models = new();
    [ObservableProperty] private ObservableCollection<FilterOption> _loras = new();
    [ObservableProperty] private bool _showLoraMatchMode;
    [ObservableProperty] private ObservableCollection<LoraMatchMode> _loraMatchModes = new();
    [ObservableProperty] private ObservableCollection<string> _templates = new();
    [ObservableProperty] private ObservableCollection<string> _promptTypes = new();
    [ObservableProperty] private ObservableCollection<AnalyticsImageItem> _results = new();
    [ObservableProperty] private string _statusText = "";
    [ObservableProperty] private string _modelSearchText = "";
    [ObservableProperty] private string _loraSearchText = "";
    [ObservableProperty] private string _selectedTemplate = "(Any)";
    [ObservableProperty] private string _selectedPromptType = "(Any)";
    [ObservableProperty] private DateTime? _fromDate;
    [ObservableProperty] private DateTime? _toDate;
    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private bool _enableScoring;
    [ObservableProperty] private LoraMatchMode _loraMatchMode = LoraMatchMode.Any;
    [ObservableProperty] private bool _canCompare;
    [ObservableProperty] private bool _showFavoritesOnly;
    [ObservableProperty] private bool _favoritesFirst;
    [ObservableProperty] private AnalyticsSortMode _selectedSortMode = AnalyticsSortMode.None;
    [ObservableProperty] private bool _isSortNone = true;
    [ObservableProperty] private bool _isSortFavorites;
    [ObservableProperty] private bool _isSortHeuristicScoreDesc;
    [ObservableProperty] private bool _isSortHeuristicScoreAsc;
    [ObservableProperty] private bool _isSortAestheticScoreDesc;
    [ObservableProperty] private bool _isSortAestheticScoreAsc;
    [ObservableProperty] private bool _isSortDateDesc;
    [ObservableProperty] private bool _isSortDateAsc;
    [ObservableProperty] private bool _canScoreSelected;
    [ObservableProperty] private bool _canDeleteSelected;
    [ObservableProperty] private bool _isDownloadActive;
    [ObservableProperty] private double _downloadProgress;
    [ObservableProperty] private string _downloadStatus = "";
    [ObservableProperty] private bool _isScoreRunActive;
    [ObservableProperty] private double _scoreRunProgress;
    [ObservableProperty] private string _scoreRunStatus = "";
    [ObservableProperty] private bool _canCancelScoreRun;
    [ObservableProperty] private string _scoreByModelMenuLabel = "Score by Model (Aesthetic)";
    [ObservableProperty] private bool _canScoreByModel;
    [ObservableProperty] private string _scoreByModelHint = "Select exactly one model to enable this action.";
    [ObservableProperty] private bool _showScoreByModelHint = true;
    [ObservableProperty] private bool _canFavoriteSelected;

    private readonly List<AnalyticsImageItem> _selected = new();
    private bool _suppressFilterChangePrompt;

    public Func<IReadOnlyList<AnalyticsImageItem>, Task>? CompareRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Bitmap, IReadOnlyList<ImageDetailNavigationItem>, Task>? ViewDetailsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage?, Task>? GenerateMoreRequested { get; set; }
    public Func<HistoryEntry, HistoryImage?, Task>? GenerateSeedVariationsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage?, Task>? GenerateLoraVariationsRequested { get; set; }
    public Func<string, Task>? ShowPngMetadataRequested { get; set; }
    public Func<string, Task<bool>>? ConfirmAsync { get; set; }
    public Func<ScoreByModelConfirmRequest, Task<ScoreByModelConfirmResult>>? ScoreByModelConfirmAsync { get; set; }

    public AnalyticsStudioViewModel(
        HistoryManagerService historyManager,
        TemplateService templateService,
        string workflowFilter,
        AestheticScoringService aestheticScoringService,
        PromptMatchScoringService promptMatchScoringService,
        SettingsService settingsService,
        ImageCacheService imageCache,
        HistoryIndexService historyIndexService)
    {
        _historyManager = historyManager;
        _templateService = templateService;
        _aestheticScoringService = aestheticScoringService;
        _promptMatchScoringService = promptMatchScoringService;
        _settingsService = settingsService;
        _imageCache = imageCache;
        _historyIndexService = historyIndexService;
        _historyDir = historyManager.GetHistoryDir();
        _workflowFilter = workflowFilter;
        LoraMatchModes = new ObservableCollection<LoraMatchMode>(new[] { LoraMatchMode.Any, LoraMatchMode.All });

        _enableScoring = _settingsService.Settings.EnableHeuristicScoring;
        _enableScoringInitialized = true;
        _ = RecomputeScoresAsync(_enableScoring);
        _ = LoadFiltersAsync();
        _ = RefreshAsync();
        UpdateSortFlags();
        UpdateScoreByModelStatus();
        UpdateModelCountsGlobal();
    }

    partial void OnModelsChanged(ObservableCollection<FilterOption>? oldValue, ObservableCollection<FilterOption> newValue)
    {
        if (oldValue != null)
        {
            oldValue.CollectionChanged -= OnFilterCollectionChanged;
            foreach (var item in oldValue)
            {
                item.PropertyChanged -= OnFilterOptionPropertyChanged;
            }
        }

        if (newValue != null)
        {
            newValue.CollectionChanged += OnFilterCollectionChanged;
            foreach (var item in newValue)
            {
                item.PropertyChanged += OnFilterOptionPropertyChanged;
            }
        }
    }

    partial void OnLorasChanged(ObservableCollection<FilterOption>? oldValue, ObservableCollection<FilterOption> newValue)
    {
        if (oldValue != null)
        {
            oldValue.CollectionChanged -= OnFilterCollectionChanged;
            foreach (var item in oldValue)
            {
                item.PropertyChanged -= OnFilterOptionPropertyChanged;
            }
        }

        if (newValue != null)
        {
            newValue.CollectionChanged += OnFilterCollectionChanged;
            foreach (var item in newValue)
            {
                item.PropertyChanged += OnFilterOptionPropertyChanged;
            }
        }
        UpdateLoraMatchModeVisibility();
    }

    partial void OnModelSearchTextChanged(string value) => ApplyFilterVisibility(Models, value);
    partial void OnLoraSearchTextChanged(string value) => ApplyFilterVisibility(Loras, value);
    partial void OnEnableScoringChanged(bool value)
    {
        if (_enableScoringInitialized)
        {
            _settingsService.Settings.EnableHeuristicScoring = value;
            _ = _settingsService.SaveSettingsAsync(_settingsService.Settings);
        }
        _ = RecomputeScoresAsync(value);
    }
    partial void OnSelectedTemplateChanged(string? oldValue, string newValue) => _ = HandleFilterChangeAsync(() => SelectedTemplate = oldValue ?? "(Any)");
    partial void OnSelectedPromptTypeChanged(string? oldValue, string newValue) => _ = HandleFilterChangeAsync(() => SelectedPromptType = oldValue ?? "(Any)");
    partial void OnFromDateChanged(DateTime? oldValue, DateTime? newValue) => _ = HandleFilterChangeAsync(() => FromDate = oldValue);
    partial void OnToDateChanged(DateTime? oldValue, DateTime? newValue) => _ = HandleFilterChangeAsync(() => ToDate = oldValue);
    partial void OnShowFavoritesOnlyChanged(bool oldValue, bool newValue) => _ = HandleFilterChangeAsync(() => ShowFavoritesOnly = oldValue);

    [RelayCommand]
    private async Task ViewDetails(AnalyticsImageItem? item)
    {
        if (item?.Bitmap == null || ViewDetailsRequested == null) return;
        var navigationItems = Results
            .Select(result => new ImageDetailNavigationItem(result.Entry, result.Image))
            .ToList();
        await ViewDetailsRequested(item.Entry, item.Image, item.Bitmap, navigationItems);
    }

    [RelayCommand]
    private async Task GenerateMore(AnalyticsImageItem? item)
    {
        var target = ResolveSingleTarget(item);
        if (target == null) return;
        if (GenerateMoreRequested != null)
        {
            await GenerateMoreRequested(target.Entry, target.Image);
            await RefreshAsync();
            return;
        }
        StatusText = "Generate flow not configured.";
    }

    [RelayCommand]
    private async Task GenerateSeedVariations(AnalyticsImageItem? item)
    {
        var target = ResolveSingleTarget(item);
        if (target == null) return;
        if (GenerateSeedVariationsRequested != null)
        {
            await GenerateSeedVariationsRequested(target.Entry, target.Image);
            await RefreshAsync();
            return;
        }
        StatusText = "Seed variation flow not configured.";
    }

    [RelayCommand]
    private async Task GenerateLoraVariations(AnalyticsImageItem? item)
    {
        var target = ResolveSingleTarget(item);
        if (target == null) return;
        if (GenerateLoraVariationsRequested != null)
        {
            await GenerateLoraVariationsRequested(target.Entry, target.Image);
            await RefreshAsync();
            return;
        }
        StatusText = "LoRA variation flow not configured.";
    }

    [RelayCommand]
    private async Task ShowPngMetadata(AnalyticsImageItem? item)
    {
        if (item == null)
        {
            StatusText = "No image selected.";
            return;
        }
        var path = item.Image.ImagePath;
        if (string.IsNullOrWhiteSpace(path))
        {
            StatusText = "Image file missing.";
            return;
        }
        var full = Path.IsPathRooted(path) ? path : Path.Combine(_historyDir, path);
        if (!File.Exists(full))
        {
            StatusText = "Image file not found.";
            return;
        }
        if (ShowPngMetadataRequested != null)
        {
            await ShowPngMetadataRequested(full);
            return;
        }
        StatusText = "PNG metadata viewer not configured.";
    }
    partial void OnLoraMatchModeChanged(LoraMatchMode oldValue, LoraMatchMode newValue) => _ = HandleFilterChangeAsync(() => LoraMatchMode = oldValue);
    partial void OnFavoritesFirstChanged(bool value) => ScheduleRefresh();
    partial void OnSelectedSortModeChanged(AnalyticsSortMode value)
    {
        if (value != AnalyticsSortMode.Favorites)
        {
            FavoritesFirst = false;
        }
        UpdateSortFlags();
        ScheduleRefresh();
    }

    partial void OnResultsChanged(ObservableCollection<AnalyticsImageItem>? oldValue, ObservableCollection<AnalyticsImageItem> newValue)
    {
        if (oldValue != null)
        {
            foreach (var item in oldValue)
            {
                item.PropertyChanged -= OnItemPropertyChanged;
            }
        }

        _selected.Clear();
        CanCompare = false;
        CanScoreSelected = false;
        CanDeleteSelected = false;
        CanFavoriteSelected = false;

        if (newValue != null)
        {
            foreach (var item in newValue)
            {
                item.PropertyChanged += OnItemPropertyChanged;
                if (item.IsSelected)
                {
                    _selected.Add(item);
                }
            }
            CanCompare = _selected.Count == 2;
            CanScoreSelected = _selected.Count > 0;
            CanDeleteSelected = _selected.Count > 0;
            CanFavoriteSelected = _selected.Count > 0;
        }

        UpdateScoreByModelStatus();
    }

    private static void ApplyFilterVisibility(IEnumerable<FilterOption> options, string term)
    {
        var hasTerm = !string.IsNullOrWhiteSpace(term);
        foreach (var option in options)
        {
            option.IsVisible = !hasTerm || option.Name.Contains(term, StringComparison.OrdinalIgnoreCase);
        }
    }

    private void OnFilterCollectionChanged(object? sender, System.Collections.Specialized.NotifyCollectionChangedEventArgs e)
    {
        if (e.OldItems != null)
        {
            foreach (var item in e.OldItems.OfType<FilterOption>())
            {
                item.PropertyChanged -= OnFilterOptionPropertyChanged;
            }
        }
        if (e.NewItems != null)
        {
            foreach (var item in e.NewItems.OfType<FilterOption>())
            {
                item.PropertyChanged += OnFilterOptionPropertyChanged;
            }
        }
    }

    private void OnFilterOptionPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(FilterOption.IsSelected))
        {
            if (sender is FilterOption option && Models.Contains(option))
            {
                UpdateScoreByModelStatus();
            }
            if (sender is FilterOption lora && Loras.Contains(lora))
            {
                UpdateLoraMatchModeVisibility();
            }
            if (_suppressFilterChangePrompt)
            {
                return;
            }

            if (sender is FilterOption changedOption)
            {
                _ = HandleFilterOptionSelectionChangedAsync(changedOption);
            }
        }
    }

    private void UpdateLoraMatchModeVisibility()
    {
        var selectedCount = Loras?.Count(l => l.IsSelected) ?? 0;
        ShowLoraMatchMode = selectedCount > 1;
        if (!ShowLoraMatchMode && LoraMatchMode != LoraMatchMode.Any)
        {
            LoraMatchMode = LoraMatchMode.Any;
        }
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
                await Task.Delay(200, token);
                if (!token.IsCancellationRequested)
                {
                    Dispatcher.UIThread.Post(async () => await RefreshAsync());
                }
            }
            catch (OperationCanceledException)
            {
                // ignore
            }
        }, token);
    }

    private async Task HandleFilterOptionSelectionChangedAsync(FilterOption option)
    {
        var shouldProceed = await ConfirmSelectionClearedAsync();
        if (!shouldProceed)
        {
            _suppressFilterChangePrompt = true;
            option.IsSelected = !option.IsSelected;
            _suppressFilterChangePrompt = false;

            if (Models.Contains(option))
            {
                UpdateScoreByModelStatus();
            }
            if (Loras.Contains(option))
            {
                UpdateLoraMatchModeVisibility();
            }
            return;
        }

        ClearSelection();
        ScheduleRefresh();
    }

    private async Task HandleFilterChangeAsync(Action revert)
    {
        if (_suppressFilterChangePrompt)
        {
            return;
        }

        var shouldProceed = await ConfirmSelectionClearedAsync();
        if (!shouldProceed)
        {
            _suppressFilterChangePrompt = true;
            revert();
            _suppressFilterChangePrompt = false;
            return;
        }

        ClearSelection();
        ScheduleRefresh();
    }

    private async Task<bool> ConfirmSelectionClearedAsync()
    {
        if (_selected.Count == 0)
        {
            return true;
        }

        if (ConfirmAsync == null)
        {
            return true;
        }

        var noun = _selected.Count == 1 ? "selected image" : "selected images";
        return await ConfirmAsync(
            $"This filter change will clear the current selection of {_selected.Count} {noun}. Continue?");
    }

    private void OnItemPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (sender is not AnalyticsImageItem item)
        {
            return;
        }

        if (e.PropertyName == nameof(AnalyticsImageItem.Bitmap))
        {
            if (!EnableScoring) return;
            if (item.Score.HasValue && item.SharpnessScore.HasValue) return;
            var bmp = item.Bitmap;
            if (bmp == null) return;

            _ = Task.Run(() =>
            {
                var heuristic = ScoringHelper.CalculateScore(bmp);
                var sharpness = ScoringHelper.CalculateSharpnessScore(bmp);
                Dispatcher.UIThread.Post(() =>
                {
                    item.Score = heuristic;
                    item.SharpnessScore = sharpness;
                    item.Image.HeuristicScore = heuristic;
                    item.Image.SharpnessScore = sharpness;
                    TryUpdateCompositeScore(item);
                    _historyManager.UpdateImage(item.Entry.Id, item.Image, save: false);
                });
            });
            return;
        }

        if (e.PropertyName != nameof(AnalyticsImageItem.IsSelected))
        {
            return;
        }

        if (item.IsSelected)
        {
            if (!_selected.Contains(item))
            {
                _selected.Add(item);
            }
        }
        else
        {
            _selected.Remove(item);
        }

        CanCompare = _selected.Count == 2;
        CanScoreSelected = _selected.Count > 0;
        CanDeleteSelected = _selected.Count > 0;
        CanFavoriteSelected = _selected.Count > 0;
    }

    private AnalyticsImageItem? ResolveSingleTarget(AnalyticsImageItem? item)
    {
        if (item != null) return item;
        if (_selected.Count == 1) return _selected[0];
        StatusText = _selected.Count > 1 ? "Select a single image." : "Select an image first.";
        return null;
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
    private void ClearSelection()
    {
        foreach (var item in _selected.ToList())
        {
            item.IsSelected = false;
        }
    }

    [RelayCommand]
    private async Task AddToFavorites(AnalyticsImageItem? item)
    {
        var target = ResolveSingleTarget(item);
        if (target == null)
        {
            return;
        }

        await AddItemsToFavoritesAsync(new[] { target });
    }

    [RelayCommand]
    private async Task AddSelectedToFavorites()
    {
        if (_selected.Count == 0)
        {
            StatusText = "Select one or more images to favorite.";
            return;
        }

        await AddItemsToFavoritesAsync(_selected.ToList());
    }

    [RelayCommand]
    private async Task DeleteSelected()
    {
        if (_selected.Count == 0)
        {
            StatusText = "Select one or more images to delete.";
            return;
        }

        if (ConfirmAsync == null)
        {
            StatusText = "Delete confirmation dialog unavailable.";
            return;
        }

        var confirm = await ConfirmAsync($"Delete {_selected.Count} selected image(s)? This cannot be undone.");
        if (!confirm)
        {
            StatusText = "Delete canceled.";
            return;
        }

        var toDelete = _selected.ToList();
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

            if (_historyManager.DeleteImage(item.Entry.Id, path))
            {
                deleted++;
            }
            else
            {
                failed++;
            }
        }

        ClearSelection();
        await RefreshAsync();

        StatusText = failed > 0
            ? $"Deleted {deleted} images. {failed} failed."
            : $"Deleted {deleted} images.";
    }

    private async Task AddItemsToFavoritesAsync(IReadOnlyList<AnalyticsImageItem> items)
    {
        var changed = 0;
        foreach (var item in items.Distinct())
        {
            if (item.Image.IsFavorite)
            {
                item.NotifyFavoriteChanged();
                continue;
            }

            item.Image.IsFavorite = true;
            item.Entry.IsFavorite = true;
            _historyManager.UpdateImage(item.Entry.Id, item.Image, save: false);
            item.NotifyFavoriteChanged();
            changed++;
        }

        if (changed == 0)
        {
            StatusText = items.Count == 1
                ? "Image is already a favorite."
                : "Selected images are already favorites.";
            return;
        }

        _historyManager.SaveChanges();

        if (FavoritesFirst || SelectedSortMode == AnalyticsSortMode.Favorites)
        {
            ApplySortToResults();
        }

        StatusText = changed == 1
            ? "Added image to favorites."
            : $"Added {changed} images to favorites.";
        await Task.CompletedTask;
    }

    [RelayCommand]
    private void SetSort(AnalyticsSortMode mode)
    {
        SelectedSortMode = mode;
        if (mode == AnalyticsSortMode.Favorites)
        {
            FavoritesFirst = true;
        }
    }

    [RelayCommand]
    private void ClearFilters()
    {
        _suppressFilterChangePrompt = true;
        foreach (var model in Models)
        {
            model.IsSelected = false;
        }
        foreach (var lora in Loras)
        {
            lora.IsSelected = false;
        }

        ModelSearchText = string.Empty;
        LoraSearchText = string.Empty;
        SelectedTemplate = Templates.FirstOrDefault() ?? "(Any)";
        SelectedPromptType = PromptTypes.FirstOrDefault() ?? "(Any)";
        FromDate = null;
        ToDate = null;
        LoraMatchMode = LoraMatchMode.Any;
        SelectedSortMode = AnalyticsSortMode.None;
        FavoritesFirst = false;
        ShowFavoritesOnly = false;
        _suppressFilterChangePrompt = false;
        ScheduleRefresh();
    }

    [RelayCommand]
    private void ToggleScoring()
    {
        EnableScoring = !EnableScoring;
    }

    [RelayCommand]
    private async Task ScoreSelected()
    {
        if (_selected.Count == 0)
        {
            StatusText = "Select one or more images to score.";
            return;
        }

        if (ConfirmAsync == null)
        {
            StatusText = "Scoring confirmation dialog unavailable.";
            return;
        }

        await ScoreItemsAsync(_selected.ToList(), $"Scoring {_selected.Count} images...");
    }

    [RelayCommand]
    private async Task ScoreByModel()
    {
        var selectedModels = Models.Where(m => m.IsSelected).Select(m => m.Name).ToList();
        if (selectedModels.Count < 1)
        {
            StatusText = "Select one or more models in the Models filter to score by model.";
            return;
        }

        var modelLabel = selectedModels.Count == 1
            ? selectedModels[0]
            : $"{selectedModels.Count} selected models";
        var selectedSet = selectedModels.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var candidates = Results.Where(r => selectedSet.Contains(r.ModelLabel)).ToList();
        if (candidates.Count == 0)
        {
            StatusText = $"No images found for {modelLabel} in the current filters.";
            return;
        }

        var avgMs = Results.Where(r => r.AestheticScoreMs.HasValue && r.AestheticScoreMs.Value > 0)
            .Select(r => r.AestheticScoreMs!.Value)
            .DefaultIfEmpty(3000)
            .Average();
        var unscoredCount = candidates.Count(c => !c.AestheticScore.HasValue);
        var includeAlreadyScored = false;
        if (ScoreByModelConfirmAsync != null)
        {
            var result = await ScoreByModelConfirmAsync(new ScoreByModelConfirmRequest(
                modelLabel,
                unscoredCount,
                candidates.Count,
                avgMs / 1000));
            if (!result.Confirmed)
            {
                StatusText = "Scoring canceled.";
                return;
            }
            includeAlreadyScored = result.IncludeAlreadyScored;
        }
        else if (ConfirmAsync != null)
        {
            var estimate = TimeSpan.FromMilliseconds(avgMs * unscoredCount);
            var estimateLabel = FormatDuration(estimate);
            var confirmMessage = $"Score {unscoredCount} unscored images for {modelLabel} within the current filters?\n\n" +
                                 $"Estimated time: {estimateLabel} (avg {avgMs / 1000:0.0}s per image).";
            if (!await ConfirmAsync(confirmMessage))
            {
                StatusText = "Scoring canceled.";
                return;
            }
        }

        var toScore = includeAlreadyScored ? candidates : candidates.Where(c => !c.AestheticScore.HasValue).ToList();
        if (toScore.Count == 0)
        {
            StatusText = includeAlreadyScored
                ? $"No images found for {modelLabel} in the current filters."
                : $"All images for {modelLabel} are already scored.";
            return;
        }

        await ScoreItemsAsync(toScore, $"Scoring {toScore.Count} images for {modelLabel}...");
    }

    [RelayCommand]
    private async Task ScoreAllImages()
    {
        if (ConfirmAsync == null && ScoreByModelConfirmAsync == null)
        {
            StatusText = "Scoring confirmation dialog unavailable.";
            return;
        }

        var entries = _historyManager.GetAllEntries();
        var items = new List<AnalyticsImageItem>();
        foreach (var entry in entries)
        {
            foreach (var img in entry.Images)
            {
                items.Add(new AnalyticsImageItem(entry, img, null));
            }
        }

        if (items.Count == 0)
        {
            StatusText = "No images found in history.";
            return;
        }

        var unscoredCount = items.Count(i => !i.AestheticScore.HasValue);
        var avgMs = Results.Where(r => r.AestheticScoreMs.HasValue && r.AestheticScoreMs.Value > 0)
            .Select(r => r.AestheticScoreMs!.Value)
            .DefaultIfEmpty(3000)
            .Average();

        var includeAlreadyScored = false;
        if (ScoreByModelConfirmAsync != null)
        {
            var result = await ScoreByModelConfirmAsync(new ScoreByModelConfirmRequest(
                "All Images",
                unscoredCount,
                items.Count,
                avgMs / 1000));
            if (!result.Confirmed)
            {
                StatusText = "Scoring canceled.";
                return;
            }
            includeAlreadyScored = result.IncludeAlreadyScored;
        }
        else if (ConfirmAsync != null)
        {
            var estimate = TimeSpan.FromMilliseconds(avgMs * Math.Max(1, unscoredCount));
            var estimateLabel = FormatDuration(estimate);
            var confirmMessage = $"Score {unscoredCount} unscored images in the entire history?\n\n" +
                                 $"Estimated time: {estimateLabel} (avg {avgMs / 1000:0.0}s per image).";
            if (!await ConfirmAsync(confirmMessage))
            {
                StatusText = "Scoring canceled.";
                return;
            }
        }

        var toScore = includeAlreadyScored ? items : items.Where(i => !i.AestheticScore.HasValue).ToList();
        if (toScore.Count == 0)
        {
            StatusText = includeAlreadyScored ? "No images found in history." : "All images are already scored.";
            return;
        }

        await ScoreItemsAsync(toScore, $"Scoring {toScore.Count} images (entire history)...");
    }

    [RelayCommand]
    private async Task ScoreAllUnscored()
    {
        if (ConfirmAsync == null && ScoreByModelConfirmAsync == null)
        {
            StatusText = "Scoring confirmation dialog unavailable.";
            return;
        }

        var entries = _historyManager.GetAllEntries();
        var items = new List<AnalyticsImageItem>();
        foreach (var entry in entries)
        {
            foreach (var img in entry.Images)
            {
                if (img.AestheticScore.HasValue) continue;
                items.Add(new AnalyticsImageItem(entry, img, null));
            }
        }

        if (items.Count == 0)
        {
            StatusText = "All images are already scored.";
            return;
        }

        var avgMs = Results.Where(r => r.AestheticScoreMs.HasValue && r.AestheticScoreMs.Value > 0)
            .Select(r => r.AestheticScoreMs!.Value)
            .DefaultIfEmpty(3000)
            .Average();

        if (ScoreByModelConfirmAsync != null)
        {
            var result = await ScoreByModelConfirmAsync(new ScoreByModelConfirmRequest(
                "All Unscored Images",
                items.Count,
                items.Count,
                avgMs / 1000));
            if (!result.Confirmed)
            {
                StatusText = "Scoring canceled.";
                return;
            }
        }
        else if (ConfirmAsync != null)
        {
            var estimate = TimeSpan.FromMilliseconds(avgMs * Math.Max(1, items.Count));
            var estimateLabel = FormatDuration(estimate);
            var confirmMessage = $"Score {items.Count} unscored images in the entire history?\n\n" +
                                 $"Estimated time: {estimateLabel} (avg {avgMs / 1000:0.0}s per image).";
            if (!await ConfirmAsync(confirmMessage))
            {
                StatusText = "Scoring canceled.";
                return;
            }
        }

        await ScoreItemsAsync(items, $"Scoring {items.Count} unscored images...");
    }

    private async Task ScoreItemsAsync(IReadOnlyList<AnalyticsImageItem> items, string startStatus)
    {
        if (items.Count == 0)
        {
            StatusText = "No images to score.";
            return;
        }

        if (ConfirmAsync == null)
        {
            StatusText = "Scoring confirmation dialog unavailable.";
            return;
        }

        _scoreCts?.Cancel();
        _scoreCts?.Dispose();
        _scoreCts = new CancellationTokenSource();
        var token = _scoreCts.Token;

        IsLoading = true;
        IsScoreRunActive = true;
        CanCancelScoreRun = true;
        ScoreRunProgress = 0;
        ScoreRunStatus = startStatus;
        StatusText = startStatus;
        var updated = false;

        try
        {
            var backend = _settingsService.Settings.AestheticScoringBackend?.Trim().ToLowerInvariant() ?? "local";
            if (backend == "remote")
            {
                var validItems = new List<(AnalyticsImageItem Item, string Path)>();
                foreach (var item in items)
                {
                    var path = item.Image.ImagePath;
                    if (string.IsNullOrWhiteSpace(path)) continue;
                    var full = Path.IsPathRooted(path) ? path : Path.Combine(_historyDir, path);
                    if (!File.Exists(full)) continue;
                    validItems.Add((item, full));
                }

                var total = validItems.Count;
                var completed = 0;
                var batchSize = _settingsService.Settings.AestheticScoringRemoteBatchSize;
                if (batchSize <= 0) batchSize = 8;

                for (int i = 0; i < total; i += batchSize)
                {
                    if (token.IsCancellationRequested)
                    {
                        StatusText = "Scoring canceled.";
                        break;
                    }

                    var chunk = validItems.Skip(i).Take(batchSize).ToList();
                    var paths = chunk.Select(x => x.Path).ToList();

                    var results = await _aestheticScoringService.ScoreRemoteBatchAsync(
                        paths,
                        msg => Dispatcher.UIThread.Post(() => StatusText = msg),
                        null,
                        token);

                    if (results != null && results.Count == chunk.Count)
                    {
                        for (int j = 0; j < chunk.Count; j++)
                        {
                            var tuple = chunk[j];
                            var item = tuple.Item;
                            var result = results[j];

                            item.AestheticScore = result.Score;
                            item.AestheticScoreMs = result.ElapsedMs;
                            item.Image.AestheticScore = result.Score;
                            item.Image.AestheticScoreMs = result.ElapsedMs;
                            item.Image.AestheticScoreModel = result.ModelName;
                            item.Image.AestheticScoreTimestamp = DateTime.Now;
                            await TryApplyLocalScoresAsync(item, tuple.Path, token);
                            _historyManager.UpdateImage(item.Entry.Id, item.Image, save: false);
                            SyncLiveScore(item.Entry, item.Image, result.Score, result.ElapsedMs);
                            updated = true;
                        }
                    }

                    completed += chunk.Count;
                    UpdateScoreRunProgress(completed, total);
                }
            }
            else
            {
                var total = items.Count;
                var completed = 0;
                foreach (var item in items)
                {
                    if (token.IsCancellationRequested)
                    {
                        StatusText = "Scoring canceled.";
                        break;
                    }

                    var path = item.Image.ImagePath;
                    if (string.IsNullOrWhiteSpace(path)) continue;
                    var full = Path.IsPathRooted(path) ? path : Path.Combine(_historyDir, path);
                    if (!File.Exists(full)) continue;

                    var progress = new Progress<DownloadProgressInfo>(info =>
                    {
                        IsDownloadActive = true;
                        DownloadStatus = info.TotalBytes.HasValue
                            ? $"Downloading {info.Label} model... {info.BytesDownloaded / 1024 / 1024}MB / {info.TotalBytes.Value / 1024 / 1024}MB"
                            : $"Downloading {info.Label} model... {info.BytesDownloaded / 1024 / 1024}MB";
                        DownloadProgress = info.Ratio ?? 0;
                    });

                    var result = await _aestheticScoringService.ScoreImageAsync(
                        full,
                        ConfirmAsync,
                        msg => Dispatcher.UIThread.Post(() => StatusText = msg),
                        progress,
                        token);

                    if (result == null)
                    {
                        completed++;
                        UpdateScoreRunProgress(completed, total);
                        continue;
                    }

                    item.AestheticScore = result.Score;
                    item.AestheticScoreMs = result.ElapsedMs;
                    item.Image.AestheticScore = result.Score;
                    item.Image.AestheticScoreMs = result.ElapsedMs;
                    item.Image.AestheticScoreModel = result.ModelName;
                    item.Image.AestheticScoreTimestamp = DateTime.Now;
                    await TryApplyLocalScoresAsync(item, full, token);
                    _historyManager.UpdateImage(item.Entry.Id, item.Image, save: false);
                    SyncLiveScore(item.Entry, item.Image, result.Score, result.ElapsedMs);
                    updated = true;
                    completed++;
                    UpdateScoreRunProgress(completed, total);
                }
            }
        }
        finally
        {
            IsDownloadActive = false;
            DownloadStatus = string.Empty;
            DownloadProgress = 0;
            IsScoreRunActive = false;
            CanCancelScoreRun = false;
            ScoreRunProgress = 0;
            ScoreRunStatus = string.Empty;
            if (updated)
            {
                _historyManager.SaveChanges();
                if (SelectedSortMode is AnalyticsSortMode.HeuristicScoreAsc or AnalyticsSortMode.HeuristicScoreDesc
                    or AnalyticsSortMode.AestheticScoreAsc or AnalyticsSortMode.AestheticScoreDesc)
                {
                    ApplySortToResults();
                }
            }
            IsLoading = false;
            StatusText = updated ? "Aesthetic scoring complete." : "No images scored.";
            UpdateScoreByModelStatus();
        }
    }

    private void SyncLiveScore(HistoryEntry entry, HistoryImage image, double score, int? elapsedMs)
    {
        Dispatcher.UIThread.Post(() =>
        {
            foreach (var result in Results)
            {
                if (ReferenceEquals(result.Entry, entry) && ReferenceEquals(result.Image, image))
                {
                    result.AestheticScore = score;
                    result.AestheticScoreMs = elapsedMs;
                    continue;
                }

                var leftPath = result.Image.ImagePath;
                var rightPath = image.ImagePath;
                if (!string.IsNullOrWhiteSpace(leftPath) &&
                    !string.IsNullOrWhiteSpace(rightPath) &&
                    string.Equals(leftPath, rightPath, StringComparison.OrdinalIgnoreCase))
                {
                    result.AestheticScore = score;
                    result.AestheticScoreMs = elapsedMs;
                }
            }
        });
    }

    private async Task TryApplyLocalScoresAsync(AnalyticsImageItem item, string fullPath, CancellationToken token)
    {
        var remoteBackend = string.Equals(
            _settingsService.Settings.AestheticScoringBackend?.Trim(),
            "remote",
            StringComparison.OrdinalIgnoreCase);
        var hasLocalScores = item.Score.HasValue
                             && item.SharpnessScore.HasValue
                             && (remoteBackend || item.PromptMatchScore.HasValue);
        if (hasLocalScores || !File.Exists(fullPath))
        {
            TryUpdateCompositeScore(item);
            return;
        }

        try
        {
            using var bmp = new Bitmap(fullPath);
            var heuristic = ScoringHelper.CalculateScore(bmp);
            var sharpness = ScoringHelper.CalculateSharpnessScore(bmp);
            var prompt = item.Prompt;
            double? promptMatch = null;
            if (!remoteBackend && !string.IsNullOrWhiteSpace(prompt))
            {
                promptMatch = await _promptMatchScoringService.ScorePromptMatchAsync(
                    bmp,
                    prompt,
                    ConfirmAsync,
                    msg => Dispatcher.UIThread.Post(() => StatusText = msg),
                    null,
                    token);
            }

            Dispatcher.UIThread.Post(() =>
            {
                item.Score = heuristic;
                item.SharpnessScore = sharpness;
                item.Image.HeuristicScore = heuristic;
                item.Image.SharpnessScore = sharpness;
                if (promptMatch.HasValue)
                {
                    item.PromptMatchScore = promptMatch;
                    item.Image.PromptMatchScore = promptMatch;
                }
                TryUpdateCompositeScore(item);
                _historyManager.UpdateImage(item.Entry.Id, item.Image, save: false);
            });
        }
        catch (OperationCanceledException)
        {
            // ignore
        }
        catch
        {
            // ignore local score failures
        }
    }

    private static void TryUpdateCompositeScore(AnalyticsImageItem item)
    {
        if (!item.Image.AestheticScore.HasValue ||
            !item.Image.HeuristicScore.HasValue ||
            !item.Image.SharpnessScore.HasValue)
        {
            return;
        }

        var composite = ComputeCompositeScore(
            item.Image.AestheticScore.Value,
            item.Image.HeuristicScore.Value,
            item.Image.SharpnessScore.Value);
        item.Image.CompositeScore = composite;
        item.CompositeScore = composite;
    }

    private static double ComputeCompositeScore(double aestheticScore, double heuristicScore, double sharpnessScore)
    {
        var aestheticScaled = Math.Clamp(aestheticScore, 0, 10) * 10;
        var composite = (aestheticScaled * 0.5) + (heuristicScore * 0.3) + (sharpnessScore * 0.2);
        return Math.Round(composite, 1);
    }

    private void UpdateScoreRunProgress(int completed, int total)
    {
        if (total <= 0) return;
        ScoreRunProgress = completed / (double)total;
        ScoreRunStatus = $"Scoring images... {completed}/{total}";
    }

    [RelayCommand]
    private void CancelScoreRun()
    {
        if (_scoreCts == null || !_scoreCts.Token.CanBeCanceled) return;
        _scoreCts.Cancel();
    }

    private void UpdateScoreByModelStatus()
    {
        var selectedModels = Models.Where(m => m.IsSelected).Select(m => m.Name).ToList();
        if (selectedModels.Count < 1)
        {
            ScoreByModelMenuLabel = "Score by Model (Aesthetic)";
            CanScoreByModel = false;
            ShowScoreByModelHint = true;
            ScoreByModelHint = "Select one or more models to enable this action.";
            return;
        }

        var selectedSet = selectedModels.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var candidates = Results.Where(r => selectedSet.Contains(r.ModelLabel)).ToList();
        if (candidates.Count == 0)
        {
            ScoreByModelMenuLabel = "Score by Model (Aesthetic)";
            CanScoreByModel = false;
            ShowScoreByModelHint = true;
            ScoreByModelHint = "No images for the selected models in current filters.";
            return;
        }

        var label = selectedModels.Count == 1
            ? selectedModels[0]
            : $"{selectedModels.Count} models";
        var unscoredCount = candidates.Count(c => !c.AestheticScore.HasValue);
        var avgMs = Results.Where(r => r.AestheticScoreMs.HasValue && r.AestheticScoreMs.Value > 0)
            .Select(r => r.AestheticScoreMs!.Value)
            .DefaultIfEmpty(3000)
            .Average();
        var estimate = TimeSpan.FromMilliseconds(avgMs * Math.Max(1, unscoredCount));
        var estimateLabel = FormatDuration(estimate);

        ScoreByModelMenuLabel = unscoredCount > 0
            ? $"Score by Model (Aesthetic) — {label}: {unscoredCount} (~{estimateLabel})"
            : "Score by Model (Aesthetic) — all scored";
        CanScoreByModel = true;
        ShowScoreByModelHint = false;
    }

    private static string FormatDuration(TimeSpan duration)
    {
        if (duration.TotalSeconds < 60)
        {
            return $"{duration.TotalSeconds:0}s";
        }
        if (duration.TotalMinutes < 60)
        {
            return $"{(int)duration.TotalMinutes}m {duration.Seconds}s";
        }
        return $"{(int)duration.TotalHours}h {duration.Minutes}m";
    }

    [RelayCommand]
    private async Task RefreshAsync()
    {
        await _refreshGate.WaitAsync();
        try
        {
        using var perf = PerfLogger.Time("AnalyticsStudio.Refresh");
        PerfLogger.ResetCounters("ImageCache.Hit", "ImageCache.Miss", "ImageCache.Evict", "ImageCache.DiskHit", "ImageCache.DiskEvict", "HistoryIndex.Hit", "HistoryIndex.Miss");
        PerfLogger.ResetCounters(
            "AnalyticsStudio.SkipDate",
            "AnalyticsStudio.SkipTemplate",
            "AnalyticsStudio.SkipPromptType",
            "AnalyticsStudio.SkipModel",
            "AnalyticsStudio.SkipLora");
        PerfLogger.ResetTimings("AnalyticsStudio.Decode");
        PerfLogger.ResetTimings(
            "AnalyticsStudio.GetEntries",
            "AnalyticsStudio.FilterLoop",
            "AnalyticsStudio.GenParams",
            "AnalyticsStudio.Sort",
            "AnalyticsStudio.Assign");
        IsLoading = true;
        StatusText = "Loading analytics...";

        var selectedModels = Models.Where(m => m.IsSelected).Select(m => m.Name).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var selectedLoras = Loras.Where(l => l.IsSelected).Select(l => l.Name).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var templateFilter = SelectedTemplate;
        var promptTypeFilter = SelectedPromptType;
        var from = FromDate?.Date;
        var to = ToDate?.Date;
        var favoritesOnly = ShowFavoritesOnly;

        var result = await Task.Run(() =>
        {
            List<HistoryEntry> entries;
            using (PerfLogger.Measure("AnalyticsStudio.GetEntries"))
            {
                entries = _historyManager.GetAllEntries()
                    .Where(e => string.Equals(e.Workflow, _workflowFilter, StringComparison.OrdinalIgnoreCase))
                    .ToList();
            }

            var items = new List<AnalyticsImageItem>();
            var pending = new Dictionary<AnalyticsImageItem, string>();
            var needsGen = selectedModels.Count > 0 || selectedLoras.Count > 0;
            using (PerfLogger.Measure("AnalyticsStudio.FilterLoop"))
            {
                foreach (var entry in entries)
                {
                    if (from != null && entry.Timestamp.Date < from.Value)
                    {
                        PerfLogger.Count("AnalyticsStudio.SkipDate");
                        continue;
                    }
                    if (to != null && entry.Timestamp.Date > to.Value)
                    {
                        PerfLogger.Count("AnalyticsStudio.SkipDate");
                        continue;
                    }

                        var templateOk = MatchesTemplate(entry, templateFilter);
                        foreach (var img in entry.Images)
                        {
                            if (!templateOk)
                            {
                                PerfLogger.Count("AnalyticsStudio.SkipTemplate");
                                continue;
                            }

                            if (favoritesOnly && !img.IsFavorite && !entry.IsFavorite)
                            {
                                continue;
                            }

                            var index = _historyIndexService.GetIndex(entry, img);
                            if (!MatchesPromptType(index.PromptType, promptTypeFilter))
                            {
                                PerfLogger.Count("AnalyticsStudio.SkipPromptType");
                                continue;
                            }

                            var item = GetOrCreateItem(entry, img);
                            var modelName = needsGen ? index.ModelName : entry.InvokeAIModel ?? string.Empty;
                            if (selectedModels.Count > 0 && !selectedModels.Contains(modelName))
                            {
                                PerfLogger.Count("AnalyticsStudio.SkipModel");
                                continue;
                            }

                            if (selectedLoras.Count > 0)
                            {
                                var loraNames = index.LoraNames;
                                var hasAny = loraNames.Any(n => selectedLoras.Contains(n));
                                var hasAll = selectedLoras.All(n => loraNames.Contains(n, StringComparer.OrdinalIgnoreCase));
                                if (LoraMatchMode == LoraMatchMode.Any && !hasAny)
                                {
                                    PerfLogger.Count("AnalyticsStudio.SkipLora");
                                    continue;
                                }
                                if (LoraMatchMode == LoraMatchMode.All && !hasAll)
                                {
                                    PerfLogger.Count("AnalyticsStudio.SkipLora");
                                    continue;
                                }
                            }

                        var path = img.ImagePath;
                        if (!string.IsNullOrWhiteSpace(path))
                        {
                            var full = Path.IsPathRooted(path) ? path : Path.Combine(_historyDir, path);
                            if (!string.IsNullOrWhiteSpace(full))
                            {
                                if (_imageCache.TryGetCached(full, 220, null, out var cached) && cached != null)
                                {
                                    PerfLogger.Count("ImageCache.Hit");
                                    item.Bitmap = cached;
                                    if (EnableScoring && !item.Score.HasValue)
                                    {
                                        item.Score = ScoringHelper.CalculateScore(cached);
                                        item.SharpnessScore = ScoringHelper.CalculateSharpnessScore(cached);
                                        item.Image.HeuristicScore = item.Score;
                                        item.Image.SharpnessScore = item.SharpnessScore;
                                        TryUpdateCompositeScore(item);
                                        _historyManager.UpdateImage(item.Entry.Id, item.Image, save: false);
                                    }
                                }
                                else
                                {
                                    PerfLogger.Count("ImageCache.Miss");
                                    pending[item] = full;
                                }
                            }
                        }

                        items.Add(item);
                    }
                }
            }

            using (PerfLogger.Measure("AnalyticsStudio.Sort"))
            {
                items = ApplySort(items);
            }

            var toLoad = new List<(AnalyticsImageItem Item, string FullPath, int Index)>();
            for (var i = 0; i < items.Count; i++)
            {
                if (pending.TryGetValue(items[i], out var full))
                {
                    toLoad.Add((items[i], full, i));
                }
            }

            return (items, toLoad);
        });

        using (PerfLogger.Measure("AnalyticsStudio.Assign"))
        {
            UpdateResultsCollection(result.items);
        }
        UpdateFilterCounts(result.items);
        StatusText = result.toLoad.Count == 0
            ? $"Loaded {result.items.Count} images."
            : $"Loaded {result.items.Count} images. Loading thumbnails...";
        PerfLogger.Log($"AnalyticsStudio.Refresh items={result.items.Count} toLoad={result.toLoad.Count} cacheHit={PerfLogger.GetCount("ImageCache.Hit")} cacheMiss={PerfLogger.GetCount("ImageCache.Miss")} diskHit={PerfLogger.GetCount("ImageCache.DiskHit")} evict={PerfLogger.GetCount("ImageCache.Evict")} diskEvict={PerfLogger.GetCount("ImageCache.DiskEvict")} indexHit={PerfLogger.GetCount("HistoryIndex.Hit")} indexMiss={PerfLogger.GetCount("HistoryIndex.Miss")}");
        PerfLogger.Log($"AnalyticsStudio.Filter skips date={PerfLogger.GetCount("AnalyticsStudio.SkipDate")} template={PerfLogger.GetCount("AnalyticsStudio.SkipTemplate")} promptType={PerfLogger.GetCount("AnalyticsStudio.SkipPromptType")} model={PerfLogger.GetCount("AnalyticsStudio.SkipModel")} lora={PerfLogger.GetCount("AnalyticsStudio.SkipLora")}");
        PerfLogger.LogSummary("AnalyticsStudio.Refresh", "AnalyticsStudio.GetEntries", "AnalyticsStudio.FilterLoop", "AnalyticsStudio.GenParams", "AnalyticsStudio.Sort", "AnalyticsStudio.Assign", "AnalyticsStudio.Decode");

        _thumbLoadCts?.Cancel();
        _thumbLoadCts?.Dispose();
        _thumbLoadCts = new CancellationTokenSource();
        var thumbToken = _thumbLoadCts.Token;

        if (result.toLoad.Count > 0)
        {
            _ = Task.Run(() =>
            {
                var loaded = 0;
                var queue = result.toLoad.ToList();
                ReorderThumbnailQueue(queue, _thumbPriorityStart, _thumbPriorityEnd);

                while (queue.Count > 0 && !thumbToken.IsCancellationRequested)
                {
                    if (Interlocked.Exchange(ref _thumbPriorityDirty, 0) == 1)
                    {
                        ReorderThumbnailQueue(queue, _thumbPriorityStart, _thumbPriorityEnd);
                    }

                    var next = queue[0];
                    queue.RemoveAt(0);
                    var bmp = LoadBitmap(next.FullPath, 220);
                    if (bmp != null)
                    {
                        Dispatcher.UIThread.Post(() =>
                        {
                            next.Item.Bitmap = bmp;
                            if (EnableScoring && !next.Item.Score.HasValue)
                            {
                                next.Item.Score = ScoringHelper.CalculateScore(bmp);
                                next.Item.SharpnessScore = ScoringHelper.CalculateSharpnessScore(bmp);
                                next.Item.Image.HeuristicScore = next.Item.Score;
                                next.Item.Image.SharpnessScore = next.Item.SharpnessScore;
                                TryUpdateCompositeScore(next.Item);
                                _historyManager.UpdateImage(next.Item.Entry.Id, next.Item.Image, save: false);
                            }
                        });
                    }
                    loaded++;
                    if (loaded % 25 == 0 || loaded == result.toLoad.Count)
                    {
                        var progress = loaded;
                        Dispatcher.UIThread.Post(() =>
                        {
                            StatusText = progress == result.toLoad.Count
                                ? $"Loaded {result.items.Count} images."
                                : $"Loading thumbnails... {progress}/{result.toLoad.Count}";
                        });
                    }
                }
                Dispatcher.UIThread.Post(() =>
                {
                    if (SelectedSortMode is AnalyticsSortMode.HeuristicScoreAsc or AnalyticsSortMode.HeuristicScoreDesc
                        or AnalyticsSortMode.AestheticScoreAsc or AnalyticsSortMode.AestheticScoreDesc)
                    {
                        ApplySortToResults();
                    }
                    IsLoading = false;
                    PerfLogger.LogSummary("AnalyticsStudio.Thumbnails", "AnalyticsStudio.Decode");
                });
            });
        }
        else
        {
            if (SelectedSortMode is AnalyticsSortMode.HeuristicScoreAsc or AnalyticsSortMode.HeuristicScoreDesc
                or AnalyticsSortMode.AestheticScoreAsc or AnalyticsSortMode.AestheticScoreDesc)
            {
                ApplySortToResults();
            }
            IsLoading = false;
            PerfLogger.LogSummary("AnalyticsStudio.Thumbnails", "AnalyticsStudio.Decode");
        }
        }
        finally
        {
            _refreshGate.Release();
        }
    }

    private void UpdateResultsCollection(IReadOnlyList<AnalyticsImageItem> items)
    {
        if (Results == null)
        {
            Results = new ObservableCollection<AnalyticsImageItem>(items);
            return;
        }

        var existing = Results;
        var newSet = new HashSet<AnalyticsImageItem>(items);
        for (var i = existing.Count - 1; i >= 0; i--)
        {
            var item = existing[i];
            if (!newSet.Contains(item))
            {
                if (item.IsSelected)
                {
                    item.IsSelected = false;
                }
                item.PropertyChanged -= OnItemPropertyChanged;
                existing.RemoveAt(i);
            }
        }

        for (var i = 0; i < items.Count; i++)
        {
            var item = items[i];
            if (i < existing.Count && ReferenceEquals(existing[i], item))
            {
                continue;
            }

            var currentIndex = existing.IndexOf(item);
            if (currentIndex >= 0)
            {
                existing.Move(currentIndex, i);
            }
            else
            {
                item.PropertyChanged += OnItemPropertyChanged;
                existing.Insert(i, item);
            }
        }

        _selected.Clear();
        foreach (var item in existing)
        {
            if (item.IsSelected)
            {
                _selected.Add(item);
            }
        }
        CanCompare = _selected.Count == 2;
        CanScoreSelected = _selected.Count > 0;
        CanDeleteSelected = _selected.Count > 0;
        CanFavoriteSelected = _selected.Count > 0;
        UpdateScoreByModelStatus();
    }

    private Task RecomputeScoresAsync(bool enable)
    {
        return Task.Run(() =>
        {
            foreach (var item in Results)
            {
                if (!enable)
                {
                    Dispatcher.UIThread.Post(() => item.Score = null);
                    continue;
                }

                var bmp = item.Bitmap;
                if (bmp == null) continue;
                var score = ScoringHelper.CalculateScore(bmp);
                var sharpness = ScoringHelper.CalculateSharpnessScore(bmp);
                Dispatcher.UIThread.Post(() =>
                {
                    item.Score = score;
                    item.SharpnessScore = sharpness;
                    item.Image.HeuristicScore = score;
                    item.Image.SharpnessScore = sharpness;
                    TryUpdateCompositeScore(item);
                    _historyManager.UpdateImage(item.Entry.Id, item.Image, save: false);
                });
            }
            if (enable && SelectedSortMode is AnalyticsSortMode.HeuristicScoreAsc or AnalyticsSortMode.HeuristicScoreDesc
                or AnalyticsSortMode.AestheticScoreAsc or AnalyticsSortMode.AestheticScoreDesc)
            {
                Dispatcher.UIThread.Post(ApplySortToResults);
            }
        });
    }

    private static bool IsFavorite(AnalyticsImageItem item)
    {
        return item.Image.IsFavorite || item.Entry.IsFavorite;
    }

    internal void UpdateThumbnailPriority(double verticalOffset, double viewportHeight, double viewportWidth)
    {
        if (viewportHeight <= 0 || viewportWidth <= 0) return;
        const double tileWidth = 272; // 260 width + 12 margin
        const double tileHeight = 332; // approx height + margin
        var columns = Math.Max(1, (int)Math.Floor(viewportWidth / tileWidth));
        var startRow = (int)Math.Floor(Math.Max(0, verticalOffset) / tileHeight);
        var visibleRows = (int)Math.Ceiling(viewportHeight / tileHeight) + 1;
        _thumbPriorityStart = startRow * columns;
        _thumbPriorityEnd = _thumbPriorityStart + (visibleRows * columns);
        Interlocked.Exchange(ref _thumbPriorityDirty, 1);
    }

    private static void ReorderThumbnailQueue(List<(AnalyticsImageItem Item, string FullPath, int Index)> queue, int start, int end)
    {
        if (queue.Count == 0) return;
        if (end <= start) return;
        queue.Sort((a, b) =>
        {
            var da = DistanceToRange(a.Index, start, end);
            var db = DistanceToRange(b.Index, start, end);
            var cmp = da.CompareTo(db);
            if (cmp != 0) return cmp;
            return a.Index.CompareTo(b.Index);
        });
    }

    private static int DistanceToRange(int index, int start, int end)
    {
        if (index < start) return start - index;
        if (index > end) return index - end;
        return 0;
    }

    private List<AnalyticsImageItem> ApplySort(IEnumerable<AnalyticsImageItem> items)
    {
        var list = items.ToList();
        var sortFavorites = FavoritesFirst || SelectedSortMode == AnalyticsSortMode.Favorites;

        IOrderedEnumerable<AnalyticsImageItem>? ordered = null;
        if (sortFavorites)
        {
            ordered = list.OrderByDescending(IsFavorite);
        }

        switch (SelectedSortMode)
        {
            case AnalyticsSortMode.HeuristicScoreDesc:
                ordered = (ordered ?? list.OrderBy(_ => 0))
                    .ThenByDescending(i => i.Score ?? double.MinValue)
                    .ThenByDescending(i => i.Entry.Timestamp);
                break;
            case AnalyticsSortMode.HeuristicScoreAsc:
                ordered = (ordered ?? list.OrderBy(_ => 0))
                    .ThenBy(i => i.Score ?? double.MaxValue)
                    .ThenByDescending(i => i.Entry.Timestamp);
                break;
            case AnalyticsSortMode.AestheticScoreDesc:
                ordered = (ordered ?? list.OrderBy(_ => 0))
                    .ThenByDescending(i => i.AestheticScore ?? double.MinValue)
                    .ThenByDescending(i => i.Entry.Timestamp);
                break;
            case AnalyticsSortMode.AestheticScoreAsc:
                ordered = (ordered ?? list.OrderBy(_ => 0))
                    .ThenBy(i => i.AestheticScore ?? double.MaxValue)
                    .ThenByDescending(i => i.Entry.Timestamp);
                break;
            case AnalyticsSortMode.DateAsc:
                ordered = (ordered ?? list.OrderBy(_ => 0))
                    .ThenBy(i => i.Entry.Timestamp);
                break;
            case AnalyticsSortMode.DateDesc:
                ordered = (ordered ?? list.OrderBy(_ => 0))
                    .ThenByDescending(i => i.Entry.Timestamp);
                break;
            default:
                if (ordered == null)
                {
                    ordered = list.OrderByDescending(i => i.Entry.Timestamp);
                }
                break;
        }

        return ordered.ToList();
    }

    private void ApplySortToResults()
    {
        Results = new ObservableCollection<AnalyticsImageItem>(ApplySort(Results));
    }

    private void UpdateSortFlags()
    {
        IsSortNone = SelectedSortMode == AnalyticsSortMode.None;
        IsSortFavorites = SelectedSortMode == AnalyticsSortMode.Favorites;
        IsSortHeuristicScoreDesc = SelectedSortMode == AnalyticsSortMode.HeuristicScoreDesc;
        IsSortHeuristicScoreAsc = SelectedSortMode == AnalyticsSortMode.HeuristicScoreAsc;
        IsSortAestheticScoreDesc = SelectedSortMode == AnalyticsSortMode.AestheticScoreDesc;
        IsSortAestheticScoreAsc = SelectedSortMode == AnalyticsSortMode.AestheticScoreAsc;
        IsSortDateDesc = SelectedSortMode == AnalyticsSortMode.DateDesc;
        IsSortDateAsc = SelectedSortMode == AnalyticsSortMode.DateAsc;
    }

    private Task LoadFiltersAsync()
    {
        var entries = _historyManager.GetAllEntries()
            .Where(e => string.Equals(e.Workflow, _workflowFilter, StringComparison.OrdinalIgnoreCase))
            .ToList();

        var models = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var loras = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var templates = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var promptTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var entry in entries)
        {
            if (!string.IsNullOrWhiteSpace(entry.TemplateName))
            {
                templates.Add(NormalizeTemplateName(entry.TemplateName));
            }
            foreach (var img in entry.Images)
            {
                if (!string.IsNullOrWhiteSpace(img.PromptType))
                {
                    promptTypes.Add(img.PromptType);
                }
                var gen = HistoryViewerViewModel.GetOrParseGenParams(img);
                var modelName = gen?.Model?.Name ?? entry.InvokeAIModel;
                if (!string.IsNullOrWhiteSpace(modelName)) models.Add(modelName);
                if (gen?.Loras != null)
                {
                    foreach (var l in gen.Loras)
                    {
                        var name = l.Lora?.Name;
                        if (!string.IsNullOrWhiteSpace(name)) loras.Add(name);
                    }
                }
            }
        }

        Models = new ObservableCollection<FilterOption>(models.OrderBy(m => m, StringComparer.OrdinalIgnoreCase).Select(m => new FilterOption(m)));
        Loras = new ObservableCollection<FilterOption>(loras.OrderBy(l => l, StringComparer.OrdinalIgnoreCase).Select(l => new FilterOption(l)));

        Templates = new ObservableCollection<string>(new[] { "(Any)" }.Concat(
            templates.Where(t => !string.IsNullOrWhiteSpace(t)).OrderBy(t => t, StringComparer.OrdinalIgnoreCase)));
        PromptTypes = new ObservableCollection<string>(new[] { "(Any)" }.Concat(
            promptTypes.OrderBy(p => p, StringComparer.OrdinalIgnoreCase)));

        SelectedTemplate = Templates.FirstOrDefault() ?? "(Any)";
        SelectedPromptType = PromptTypes.FirstOrDefault() ?? "(Any)";

        UpdateModelCountsGlobal();
        return Task.CompletedTask;
    }

    private bool MatchesTemplate(HistoryEntry entry, string? filter)
    {
        if (string.IsNullOrWhiteSpace(filter) || filter == "(Any)") return true;
        var normalized = NormalizeTemplateName(entry.TemplateName);
        return string.Equals(normalized, filter, StringComparison.OrdinalIgnoreCase);
    }

    private bool MatchesPromptType(string? promptType, string? filter)
    {
        if (string.IsNullOrWhiteSpace(filter) || filter == "(Any)") return true;
        return string.Equals(promptType, filter, StringComparison.OrdinalIgnoreCase);
    }

    private static string NormalizeTemplateName(string? name)
    {
        if (string.IsNullOrWhiteSpace(name)) return string.Empty;
        var trimmed = name.Trim();
        return Path.GetFileNameWithoutExtension(trimmed);
    }

    private AnalyticsImageItem GetOrCreateItem(HistoryEntry entry, HistoryImage image)
    {
        if (_itemCache.TryGetValue(image, out var existing))
        {
            return existing;
        }

        var item = new AnalyticsImageItem(entry, image, null);
        _itemCache[image] = item;
        return item;
    }

    private Bitmap? LoadBitmap(string? path, int decodeWidth)
    {
        if (string.IsNullOrWhiteSpace(path)) return null;
        using var _ = PerfLogger.Measure("AnalyticsStudio.Decode");
        return _imageCache.GetOrLoadForUi(path, decodeWidth, _historyDir);
    }

    private void UpdateFilterCounts(IReadOnlyList<AnalyticsImageItem> items)
    {
        var modelCounts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var loraCounts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        foreach (var item in items)
        {
            var model = item.ModelLabel ?? string.Empty;
            if (!string.IsNullOrWhiteSpace(model))
            {
                modelCounts[model] = modelCounts.TryGetValue(model, out var count) ? count + 1 : 1;
            }

            foreach (var lora in item.GetLoraNames())
            {
                if (string.IsNullOrWhiteSpace(lora)) continue;
                loraCounts[lora] = loraCounts.TryGetValue(lora, out var count) ? count + 1 : 1;
            }
        }

        foreach (var option in Models)
        {
            // Model counts are global and updated separately.
        }

        foreach (var option in Loras)
        {
            option.Count = loraCounts.TryGetValue(option.Name, out var count) ? count : 0;
        }
    }

    private void UpdateModelCountsGlobal()
    {
        var modelCounts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var entries = _historyManager.GetAllEntries()
            .Where(e => string.Equals(e.Workflow, _workflowFilter, StringComparison.OrdinalIgnoreCase))
            .ToList();

        foreach (var entry in entries)
        {
            foreach (var img in entry.Images)
            {
                var gen = HistoryViewerViewModel.GetOrParseGenParams(img);
                var modelName = gen?.Model?.Name ?? entry.InvokeAIModel;
                if (!string.IsNullOrWhiteSpace(modelName))
                {
                    modelCounts[modelName] = modelCounts.TryGetValue(modelName, out var count) ? count + 1 : 1;
                }
            }
        }

        foreach (var option in Models)
        {
            option.Count = modelCounts.TryGetValue(option.Name, out var count) ? count : 0;
        }
    }
}
