using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Controls.Templates;
using Avalonia.Layout;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using System.Windows.Input;
using Avalonia.Media.Imaging;
using PromptTool.Core.Clients;
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class MainWindowViewModel : ObservableObject
{
    private const string StatusGenerationCancelled = "Generation cancelled.";
    private const string StatusImagesDiscarded = "Images discarded.";
    private const string StatusImagesReady = "Images ready. Add notes, select, and save.";
    private const string StatusImagesReadyMain = "Images ready. Choose which to save or discard.";
    private const string StatusImagesReadySaveDiscard = "Images ready. Save or discard.";
    private const int PromptTokenLimitEstimate = 77;
    private readonly PromptProcessorService _promptProcessorService;
    private readonly WildcardService _wildcardService;
    private readonly SettingsService _settingsService;
    private readonly SystemPromptService _systemPromptService;
    private readonly OllamaClient _ollamaClient;
    private readonly InvokeAIClient _invokeAIClient;
    private readonly HistoryManagerService _historyManager;
    private readonly KpiStatsService? _kpiStats;
    private readonly TemplateService _templateService;
    private readonly ModelUsageTracker _modelUsageTracker;
    private readonly NotificationService? _notifications;
    private readonly ScoringCacheService _scoringCacheService;
    private readonly AestheticScoringService _aestheticScoringService;
    private readonly PromptMatchScoringService _promptMatchScoringService;
    private readonly ImageCacheService _imageCacheService;
    private readonly GenerationQueueService _generationQueue;
    private readonly HistoryIndexService _historyIndexService;
    private CancellationTokenSource? _invokeMonitorCts;
    private bool? _invokeOnline;
    private readonly SemaphoreSlim _invokeGenerationGate = new(1, 1);
    private CancellationTokenSource? _activeGenerationCts;
    private readonly SemaphoreSlim _unloadLock = new(1, 1);
    private static readonly Regex WildcardRegex = new(@"__(?<name>.+?)__|\{(?<name>[^{}]+)\}", RegexOptions.Compiled);
    private bool _initialized;
    private bool _generationInProgress;
    private int _invokeOfflineFailures;
    private const int InvokeOfflineFailureThreshold = 2;
    private const int InvokeOfflineFailureThresholdBusy = 3;

    public SettingsService SettingsService => _settingsService;

    [ObservableProperty] private string _promptText = "";
    [ObservableProperty] private ObservableCollection<PromptSegmentViewModel> _processedPromptSegments = new();
    [ObservableProperty] private string _outputText = "";
    [ObservableProperty] private ObservableCollection<string> _missingWildcards = new();
    [ObservableProperty] private ObservableCollection<string> _wildcards = new();
    [ObservableProperty] private ObservableCollection<TemplateOption> _templates = new();
    [ObservableProperty] private TemplateOption? _selectedTemplate;
    [ObservableProperty] private ObservableCollection<string> _models = new();
    [ObservableProperty] private string? _selectedModel;
    [ObservableProperty] private string _workflow;
    [ObservableProperty] private ObservableCollection<VariationOption> _variationOptions = new();
    [ObservableProperty] private string _statusText = "Ready.";
    [ObservableProperty] private bool _isInvokeOnline = true;
    [ObservableProperty] private string _wildcardSearchText = string.Empty;
    [ObservableProperty] private ObservableCollection<WildcardBrowserItem> _filteredWildcards = new();
    [ObservableProperty] private ObservableCollection<WildcardBrowserItem> _allWildcardBrowserItems = new();
    [ObservableProperty] private WildcardBrowserItem? _selectedWildcardBrowserItem;
    [ObservableProperty] private ObservableCollection<WildcardBrowserItem> _promptSuggestedWildcards = new();
    [ObservableProperty] private string _wildcardPreviewText = "Select a wildcard to preview its values, tags, and usage hints.";
    [ObservableProperty] private string _wildcardBrowserStatus = "Browse your wildcard library.";
    [ObservableProperty] private bool _isWildcardBrowserDetailed;
    [ObservableProperty] private ObservableCollection<WildcardAutocompleteItem> _wildcardAutocompleteItems = new();
    [ObservableProperty] private bool _isWildcardAutocompleteOpen;
    [ObservableProperty] private WildcardAutocompleteItem? _selectedWildcardAutocompleteItem;

    private int _wildcardAutocompleteReplaceStart = -1;
    private int _wildcardAutocompleteReplaceLength;

    public bool IsSfwWorkflow => string.Equals(Workflow, "sfw", StringComparison.OrdinalIgnoreCase);
    public bool IsNsfwWorkflow => string.Equals(Workflow, "nsfw", StringComparison.OrdinalIgnoreCase);

    partial void OnPromptTextChanged(string value)
    {
        UpdateMissingWildcardsPreview(value);
        RefreshWildcardBrowser();
    }

    partial void OnWildcardSearchTextChanged(string value)
    {
        RefreshWildcardBrowser();
    }

    partial void OnSelectedWildcardAutocompleteItemChanged(WildcardAutocompleteItem? value)
    {
        if (value == null && WildcardAutocompleteItems.Count > 0)
        {
            SelectedWildcardAutocompleteItem = WildcardAutocompleteItems[0];
        }
    }

    partial void OnSelectedModelChanged(string? value)
    {
        if (!_initialized || string.IsNullOrWhiteSpace(value))
        {
            return;
        }

        if (string.Equals(_settingsService.Settings.DefaultOllamaModel, value, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        _settingsService.Settings.DefaultOllamaModel = value;
        _ = _settingsService.SaveSettingsAsync(_settingsService.Settings);
    }

    public IAsyncRelayCommand GenerateCommand { get; }
    public IAsyncRelayCommand EnhancePromptCommand { get; }
    public IAsyncRelayCommand<Window?> GenerateImageCommand { get; }
    public IAsyncRelayCommand<string?> SetWorkflowCommand { get; }
    public IAsyncRelayCommand<Window?> ShowSettingsCommand { get; }
    public IAsyncRelayCommand<Window?> ViewHistoryCommand { get; }
    public IAsyncRelayCommand<Window?> ShowBrainstormingCommand { get; }
    public IAsyncRelayCommand<Window?> ShowImageInterrogatorCommand { get; }
    public IAsyncRelayCommand<Window?> ShowModelStatsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowWildcardManagerCommand { get; }
    public IAsyncRelayCommand<string?> OpenWildcardInManagerCommand { get; }
    public IAsyncRelayCommand<Window?> ShowAllImagesCommand { get; }
    public IAsyncRelayCommand<Window?> SaveTemplateCommand { get; }
    public IAsyncRelayCommand<Window?> CreateTemplateCommand { get; }
    public IAsyncRelayCommand<Window?> SaveTemplateAsCommand { get; }
    public IAsyncRelayCommand<Window?> GenerateTemplateFromThemeCommand { get; }
    public IAsyncRelayCommand<string?> CreateMissingWildcardCommand { get; }
    public IRelayCommand<string?> InsertWildcardCommand { get; }
    public IAsyncRelayCommand<string?> ShowExperimentRunnerCommand { get; }
    public IAsyncRelayCommand<Window?> ShowPromptEvolverCommand { get; }
    public IAsyncRelayCommand<Window?> ShowInvokeAIModelDefaultsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowInvokeAILoraDefaultsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowSystemPromptsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowPngMetadataViewerCommand { get; }
    public IAsyncRelayCommand<Window?> ShowHistoryIntegrityCommand { get; }
    public IAsyncRelayCommand<Window?> ShowSettingsSystemPromptsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowSettingsInvokeAIModelDefaultsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowSettingsInvokeAILoraDefaultsCommand { get; }
    public IAsyncRelayCommand ClearInvokeCacheCommand { get; }
    public IAsyncRelayCommand<Window?> ShowAnalyticsStudioCommand { get; }
    public IAsyncRelayCommand<Window?> ShowKpiDashboardCommand { get; }
    public IAsyncRelayCommand<Window?> ShowSchedulerTunerCommand { get; }
    public IRelayCommand RerollPromptCommand { get; }
    public ICommand ExitCommand { get; }

    private TemplateGenerationResult? _lastGeneration;

    public MainWindowViewModel(
        PromptProcessorService promptProcessorService,
        WildcardService wildcardService,
        SettingsService settingsService,
        SystemPromptService systemPromptService,
        OllamaClient ollamaClient,
        InvokeAIClient invokeAIClient,
        HistoryManagerService historyManager,
        KpiStatsService? kpiStats,
        TemplateService templateService,
        ModelUsageTracker modelUsageTracker,
        NotificationService? notifications = null)
    {
        _promptProcessorService = promptProcessorService;
        _wildcardService = wildcardService;
        _settingsService = settingsService;
        _systemPromptService = systemPromptService;
        _ollamaClient = ollamaClient;
        _invokeAIClient = invokeAIClient;
        _historyManager = historyManager;
        _kpiStats = kpiStats;
        _templateService = templateService;
        _modelUsageTracker = modelUsageTracker;
        _notifications = notifications;
        _scoringCacheService = new ScoringCacheService();
        _aestheticScoringService = new AestheticScoringService(_scoringCacheService, _settingsService);
        _promptMatchScoringService = new PromptMatchScoringService(_scoringCacheService, _settingsService);
        _imageCacheService = new ImageCacheService();
        _generationQueue = new GenerationQueueService();
        _imageCacheService.DiskCacheDir = Path.Combine(_settingsService.GetHistoryDir(), ".thumbs");
        _historyIndexService = new HistoryIndexService();
        _workflow = _settingsService.Settings.Workflow;

        GenerateCommand = new AsyncRelayCommand(ProcessPromptAsync);
        EnhancePromptCommand = new AsyncRelayCommand(EnhancePromptAsync);
        GenerateImageCommand = new AsyncRelayCommand<Window?>(GenerateImageAsync);
        ShowGenerationQueueCommand = new AsyncRelayCommand<Window?>(ShowGenerationQueueAsync);
        SetWorkflowCommand = new AsyncRelayCommand<string?>(SetWorkflowAsync);
        ShowSettingsCommand = new AsyncRelayCommand<Window?>(ShowSettingsAsync);
        ViewHistoryCommand = new AsyncRelayCommand<Window?>(ShowHistoryAsync);
        ShowBrainstormingCommand = new AsyncRelayCommand<Window?>(ShowBrainstormingAsync);
        ShowImageInterrogatorCommand = new AsyncRelayCommand<Window?>(ShowImageInterrogatorAsync);
        ShowModelStatsCommand = new AsyncRelayCommand<Window?>(ShowModelStatsAsync);
        ShowWildcardManagerCommand = new AsyncRelayCommand<Window?>(ShowWildcardManagerAsync);
        OpenWildcardInManagerCommand = new AsyncRelayCommand<string?>(OpenWildcardInManagerAsync);
        ShowAllImagesCommand = new AsyncRelayCommand<Window?>(ShowAllImagesAsync);
        SaveTemplateCommand = new AsyncRelayCommand<Window?>(SaveTemplateAsync);
        CreateTemplateCommand = new AsyncRelayCommand<Window?>(CreateTemplateAsync);
        SaveTemplateAsCommand = new AsyncRelayCommand<Window?>(SaveTemplateAsAsync);
        GenerateTemplateFromThemeCommand = new AsyncRelayCommand<Window?>(GenerateTemplateFromThemeAsync);
        CreateMissingWildcardCommand = new AsyncRelayCommand<string?>(CreateMissingWildcardAsync);
        InsertWildcardCommand = new RelayCommand<string?>(InsertWildcard);
        ShowExperimentRunnerCommand = new AsyncRelayCommand<string?>(ShowExperimentRunnerAsync);
        ShowPromptEvolverCommand = new AsyncRelayCommand<Window?>(ShowPromptEvolverAsync);
        ShowPngMetadataViewerCommand = new AsyncRelayCommand<Window?>(ShowPngMetadataViewerAsync);
        ShowHistoryIntegrityCommand = new AsyncRelayCommand<Window?>(ShowHistoryIntegrityAsync);
        ShowInvokeAIModelDefaultsCommand = new AsyncRelayCommand<Window?>(ShowInvokeAIModelDefaultsAsync);
        ShowInvokeAILoraDefaultsCommand = new AsyncRelayCommand<Window?>(ShowInvokeAILoraDefaultsAsync);
        ShowSystemPromptsCommand = new AsyncRelayCommand<Window?>(ShowSystemPromptsAsync);
        ShowSettingsSystemPromptsCommand = new AsyncRelayCommand<Window?>(owner => ShowSettingsAsync(owner, "SystemPrompts"));
        ShowSettingsInvokeAIModelDefaultsCommand = new AsyncRelayCommand<Window?>(owner => ShowSettingsAsync(owner, "InvokeAIModelDefaults"));
        ShowSettingsInvokeAILoraDefaultsCommand = new AsyncRelayCommand<Window?>(owner => ShowSettingsAsync(owner, "InvokeAILoraDefaults"));
        ClearInvokeCacheCommand = new AsyncRelayCommand(ClearInvokeCacheAsync);
        ShowAnalyticsStudioCommand = new AsyncRelayCommand<Window?>(ShowAnalyticsStudioAsync);
        ShowKpiDashboardCommand = new AsyncRelayCommand<Window?>(ShowKpiDashboardAsync);
        ShowSchedulerTunerCommand = new AsyncRelayCommand<Window?>(ShowSchedulerTunerAsync);
        RerollPromptCommand = new RelayCommand(RerollPrompt, () => _lastGeneration != null);
        ExitCommand = new RelayCommand(Exit);
    }

    public AsyncRelayCommand<Window?> ShowGenerationQueueCommand { get; }

    public async Task InitializeAsync()
    {
        if (_initialized) return;
        _initialized = true;
        
        _invokeAIClient.ClearCache();
        StatusText = "Loading data...";
        await LoadTemplatesAsync();
        await LoadModelsAsync();
        await Task.Run(LoadWildcards);
        await LoadVariationsAsync();
        ApplySavedUiState();
        _ = StartInvokeMonitorAsync();
        StatusText = "Ready.";
    }

    private void ApplySavedUiState()
    {
        var settings = _settingsService.Settings;
        if (!string.IsNullOrWhiteSpace(settings.LastPromptText))
        {
            PromptText = settings.LastPromptText;
        }

        if (!string.IsNullOrWhiteSpace(settings.LastTemplateName))
        {
            var match = Templates.FirstOrDefault(t => string.Equals(t.Name, settings.LastTemplateName, StringComparison.OrdinalIgnoreCase));
            if (match != null)
            {
                SelectedTemplate = match;
            }
        }

        if (!string.IsNullOrWhiteSpace(settings.LastOllamaModel))
        {
            var modelMatch = Models.FirstOrDefault(m => string.Equals(m, settings.LastOllamaModel, StringComparison.OrdinalIgnoreCase));
            if (modelMatch != null)
            {
                SelectedModel = modelMatch;
            }
        }
    }

    private void LoadWildcards()
    {
        var names = _wildcardService.GetWildcardNames()
            .OrderBy(n => n, StringComparer.OrdinalIgnoreCase);
        Wildcards = new ObservableCollection<string>(names);
        RefreshWildcardBrowser();
    }

    private void RefreshWildcardBrowser()
    {
        var structured = _wildcardService.GetStructuredWildcards();
        var selectedName = SelectedWildcardBrowserItem?.Name;
        if (structured.Count == 0)
        {
            FilteredWildcards = new ObservableCollection<WildcardBrowserItem>();
            AllWildcardBrowserItems = new ObservableCollection<WildcardBrowserItem>();
            PromptSuggestedWildcards = new ObservableCollection<WildcardBrowserItem>();
            SelectedWildcardBrowserItem = null;
            WildcardBrowserStatus = "No wildcards loaded.";
            WildcardPreviewText = "Create or load some wildcards to browse them here.";
            return;
        }

        var promptTerms = ExtractSearchTerms(PromptText);
        var existingPromptWildcards = ExtractReferencedWildcardNames(PromptText);
        var searchTerms = ExtractSearchTerms(WildcardSearchText);

        var suggested = structured.Keys
            .Where(name => !existingPromptWildcards.Contains(name))
            .Select(name => BuildWildcardBrowserItem(name, structured[name], Array.Empty<string>(), promptTerms))
            .Where(item => item != null && item.Score > 0)
            .Select(item => item!)
            .OrderByDescending(item => item.Score)
            .ThenBy(item => item.Name, StringComparer.OrdinalIgnoreCase)
            .Take(8)
            .ToList();
        PromptSuggestedWildcards = new ObservableCollection<WildcardBrowserItem>(suggested);

        var allItems = structured.Keys
            .Select(name => BuildWildcardBrowserItem(name, structured[name], Array.Empty<string>(), Array.Empty<string>()))
            .Where(item => item != null)
            .Select(item => item!)
            .OrderBy(item => item.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
        AllWildcardBrowserItems = new ObservableCollection<WildcardBrowserItem>(allItems);

        var items = structured.Keys
            .Select(name => BuildWildcardBrowserItem(name, structured[name], searchTerms, promptTerms))
            .Where(item => item != null)
            .Select(item => item!)
            .OrderByDescending(item => item.Score)
            .ThenBy(item => item.Name, StringComparer.OrdinalIgnoreCase)
            .Take(80)
            .ToList();

        FilteredWildcards = new ObservableCollection<WildcardBrowserItem>(items);
        if (items.Count == 0)
        {
            SelectedWildcardBrowserItem = null;
            WildcardBrowserStatus = "No wildcards matched this search.";
            WildcardPreviewText = "Try a broader search term, or pick one of the prompt-relevant suggestions.";
            return;
        }

        WildcardBrowserStatus = searchTerms.Count == 0
            ? $"Showing {items.Count} wildcards. Top matches are ranked by relevance to the current prompt."
            : $"Showing {items.Count} wildcard matches for '{WildcardSearchText.Trim()}'.";

        SelectedWildcardBrowserItem = items.FirstOrDefault(i => string.Equals(i.Name, selectedName, StringComparison.OrdinalIgnoreCase))
                                     ?? items.FirstOrDefault();
    }

    private WildcardBrowserItem? BuildWildcardBrowserItem(
        string wildcardName,
        StructuredWildcard structured,
        IReadOnlyList<string> searchTerms,
        IReadOnlyList<string> promptTerms)
    {
        var choices = structured.Choices?.Select(c => c.Value).Where(v => !string.IsNullOrWhiteSpace(v)).ToList() ?? new List<string>();
        var tags = structured.Choices?
            .SelectMany(c => c.Tags ?? Enumerable.Empty<string>())
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList() ?? new List<string>();

        var searchBlob = BuildWildcardSearchBlob(wildcardName, structured, choices, tags);
        var score = 0;
        if (searchTerms.Count > 0)
        {
            foreach (var term in searchTerms)
            {
                if (!searchBlob.Contains(term, StringComparison.OrdinalIgnoreCase))
                {
                    return null;
                }

                score += wildcardName.Contains(term, StringComparison.OrdinalIgnoreCase) ? 10 : 3;
                score += choices.Any(c => c.Contains(term, StringComparison.OrdinalIgnoreCase)) ? 4 : 0;
                score += tags.Any(t => t.Contains(term, StringComparison.OrdinalIgnoreCase)) ? 5 : 0;
            }
        }
        else
        {
            score = ScoreWildcardForPrompt(wildcardName, promptTerms, structured);
        }

        var previewParts = new List<string>();
        if (!string.IsNullOrWhiteSpace(structured.Description))
        {
            previewParts.Add(structured.Description!.Trim());
        }

        if (choices.Count > 0)
        {
            previewParts.Add($"Examples: {string.Join(", ", choices.Take(3))}");
        }

        if (tags.Count > 0)
        {
            previewParts.Add($"Tags: {string.Join(", ", tags.Take(4))}");
        }

        var sampleText = choices.Count == 0
            ? "No sample values"
            : string.Join(", ", choices.Take(2));

        var tooltipParts = new List<string> { $"__{wildcardName}__" };
        if (!string.IsNullOrWhiteSpace(structured.Description))
        {
            tooltipParts.Add(structured.Description!.Trim());
        }
        if (choices.Count > 0)
        {
            tooltipParts.Add($"Examples: {string.Join(", ", choices.Take(10))}");
        }
        if (tags.Count > 0)
        {
            tooltipParts.Add($"Tags: {string.Join(", ", tags.Take(8))}");
        }

        return new WildcardBrowserItem
        {
            Name = wildcardName,
            SampleText = sampleText,
            Summary = string.Join(" | ", previewParts.Where(p => !string.IsNullOrWhiteSpace(p))),
            Tooltip = string.Join(Environment.NewLine + Environment.NewLine, tooltipParts.Where(p => !string.IsNullOrWhiteSpace(p))),
            ChoiceCount = choices.Count,
            Score = score
        };
    }

    private string BuildWildcardSearchBlob(string wildcardName, StructuredWildcard structured, IReadOnlyList<string> choices, IReadOnlyList<string> tags)
    {
        var parts = new List<string> { wildcardName };
        if (!string.IsNullOrWhiteSpace(structured.Description))
        {
            parts.Add(structured.Description!);
        }

        if (choices.Count > 0)
        {
            parts.AddRange(choices.Take(40));
        }

        if (tags.Count > 0)
        {
            parts.AddRange(tags);
        }

        if (structured.Includes != null)
        {
            parts.Add(structured.Includes.ToString() ?? string.Empty);
        }

        return string.Join(" ", parts);
    }

    private int ScoreWildcardForPrompt(string wildcardName, IReadOnlyList<string> promptTerms, StructuredWildcard structured)
    {
        if (promptTerms.Count == 0)
        {
            return 1;
        }

        var score = 0;
        var description = structured.Description ?? string.Empty;
        var values = structured.Choices?.Select(c => c.Value).Where(v => !string.IsNullOrWhiteSpace(v)).ToList() ?? new List<string>();
        var tags = structured.Choices?.SelectMany(c => c.Tags ?? Enumerable.Empty<string>()).ToList() ?? new List<string>();

        foreach (var term in promptTerms)
        {
            if (wildcardName.Contains(term, StringComparison.OrdinalIgnoreCase))
            {
                score += 8;
            }
            if (description.Contains(term, StringComparison.OrdinalIgnoreCase))
            {
                score += 4;
            }
            if (values.Any(v => v.Contains(term, StringComparison.OrdinalIgnoreCase)))
            {
                score += 2;
            }
            if (tags.Any(t => t.Contains(term, StringComparison.OrdinalIgnoreCase)))
            {
                score += 5;
            }
        }

        return score;
    }

    private string BuildWildcardBrowserPreview(string wildcardName)
    {
        if (!_wildcardService.GetStructuredWildcards().TryGetValue(wildcardName, out var structured))
        {
            return _wildcardService.GetWildcardFileContent(wildcardName);
        }

        var lines = new List<string>
        {
            $"__{wildcardName}__",
            $"Choices: {structured.Choices.Count}"
        };

        if (!string.IsNullOrWhiteSpace(structured.Description))
        {
            lines.Add(string.Empty);
            lines.Add(structured.Description!.Trim());
        }

        var tags = structured.Choices
            .SelectMany(c => c.Tags ?? Enumerable.Empty<string>())
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(t => t, StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (tags.Count > 0)
        {
            lines.Add(string.Empty);
            lines.Add($"Tags: {string.Join(", ", tags.Take(12))}");
        }

        var includesText = structured.Includes?.ToString();
        if (!string.IsNullOrWhiteSpace(includesText))
        {
            lines.Add(string.Empty);
            lines.Add($"Includes: {includesText}");
        }

        var examples = structured.Choices
            .Select(c => c.Value)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .Take(12)
            .ToList();
        if (examples.Count > 0)
        {
            lines.Add(string.Empty);
            lines.Add("Examples:");
            lines.AddRange(examples.Select(v => $"- {v}"));
        }

        return string.Join(Environment.NewLine, lines);
    }

    public void UpdateWildcardAutocomplete(string? text, int caretIndex)
    {
        var currentText = text ?? string.Empty;
        var context = FindWildcardAutocompleteContext(currentText, caretIndex);
        if (context == null)
        {
            CloseWildcardAutocomplete();
            return;
        }

        var structured = _wildcardService.GetStructuredWildcards();
        if (structured.Count == 0)
        {
            CloseWildcardAutocomplete();
            return;
        }

        var selectedName = SelectedWildcardAutocompleteItem?.Name;
        var query = context.Value.query.Trim();
        var queryTerms = ExtractSearchTerms(query);
        var promptTerms = ExtractSearchTerms(PromptText);

        var items = structured.Keys
            .Select(name => BuildWildcardAutocompleteItem(name, structured[name], query, queryTerms, promptTerms))
            .Where(item => item != null)
            .Select(item => item!)
            .OrderByDescending(item => item.Score)
            .ThenBy(item => item.Name, StringComparer.OrdinalIgnoreCase)
            .Take(10)
            .ToList();

        if (items.Count == 0)
        {
            CloseWildcardAutocomplete();
            return;
        }

        _wildcardAutocompleteReplaceStart = context.Value.replaceStart;
        _wildcardAutocompleteReplaceLength = context.Value.replaceLength;
        WildcardAutocompleteItems = new ObservableCollection<WildcardAutocompleteItem>(items);
        IsWildcardAutocompleteOpen = true;
        SelectedWildcardAutocompleteItem = items.FirstOrDefault(i => string.Equals(i.Name, selectedName, StringComparison.OrdinalIgnoreCase))
                                          ?? items[0];
    }

    public void MoveWildcardAutocompleteSelection(int delta)
    {
        if (WildcardAutocompleteItems.Count == 0)
        {
            return;
        }

        var currentIndex = SelectedWildcardAutocompleteItem == null
            ? -1
            : WildcardAutocompleteItems.IndexOf(SelectedWildcardAutocompleteItem);

        var nextIndex = currentIndex < 0
            ? 0
            : Math.Clamp(currentIndex + delta, 0, WildcardAutocompleteItems.Count - 1);

        SelectedWildcardAutocompleteItem = WildcardAutocompleteItems[nextIndex];
    }

    public (string newText, int caret)? CommitWildcardAutocomplete(int caretIndex)
    {
        if (!IsWildcardAutocompleteOpen || SelectedWildcardAutocompleteItem == null || _wildcardAutocompleteReplaceStart < 0)
        {
            return null;
        }

        var current = PromptText ?? string.Empty;
        var token = $"__{SelectedWildcardAutocompleteItem.Name}__";
        var updated = ReplaceRange(current, _wildcardAutocompleteReplaceStart, _wildcardAutocompleteReplaceLength, token);
        var newCaret = _wildcardAutocompleteReplaceStart + token.Length;

        PromptText = updated;
        StatusText = $"Inserted wildcard {SelectedWildcardAutocompleteItem.Name}.";
        CloseWildcardAutocomplete();
        return (updated, newCaret);
    }

    public void CloseWildcardAutocomplete()
    {
        _wildcardAutocompleteReplaceStart = -1;
        _wildcardAutocompleteReplaceLength = 0;
        IsWildcardAutocompleteOpen = false;
        WildcardAutocompleteItems = new ObservableCollection<WildcardAutocompleteItem>();
        SelectedWildcardAutocompleteItem = null;
    }

    private WildcardAutocompleteItem? BuildWildcardAutocompleteItem(
        string wildcardName,
        StructuredWildcard structured,
        string rawQuery,
        IReadOnlyList<string> queryTerms,
        IReadOnlyList<string> promptTerms)
    {
        var values = structured.Choices?
            .Select(c => c.Value)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .ToList() ?? new List<string>();
        var tags = structured.Choices?
            .SelectMany(c => c.Tags ?? Enumerable.Empty<string>())
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList() ?? new List<string>();

        var searchBlob = BuildWildcardSearchBlob(wildcardName, structured, values, tags);
        var score = 0;

        if (!string.IsNullOrWhiteSpace(rawQuery))
        {
            if (wildcardName.StartsWith(rawQuery, StringComparison.OrdinalIgnoreCase))
            {
                score += 140;
            }
            else if (wildcardName.Contains(rawQuery, StringComparison.OrdinalIgnoreCase))
            {
                score += 90;
            }

            if (tags.Any(t => t.Contains(rawQuery, StringComparison.OrdinalIgnoreCase)))
            {
                score += 55;
            }

            if (values.Any(v => v.Contains(rawQuery, StringComparison.OrdinalIgnoreCase)))
            {
                score += 40;
            }

            if (score == 0 && queryTerms.Count == 0)
            {
                return null;
            }

            foreach (var term in queryTerms)
            {
                if (!searchBlob.Contains(term, StringComparison.OrdinalIgnoreCase))
                {
                    return null;
                }

                score += wildcardName.Contains(term, StringComparison.OrdinalIgnoreCase) ? 20 : 4;
                score += tags.Any(t => t.Contains(term, StringComparison.OrdinalIgnoreCase)) ? 10 : 0;
                score += values.Any(v => v.Contains(term, StringComparison.OrdinalIgnoreCase)) ? 6 : 0;
            }
        }
        else
        {
            score = ScoreWildcardForPrompt(wildcardName, promptTerms, structured);
        }

        var previewParts = new List<string>();
        if (!string.IsNullOrWhiteSpace(structured.Description))
        {
            previewParts.Add(structured.Description!.Trim());
        }

        previewParts.AddRange(values.Take(2));

        return new WildcardAutocompleteItem
        {
            Name = wildcardName,
            Preview = string.Join(" | ", previewParts.Where(p => !string.IsNullOrWhiteSpace(p))),
            ChoiceCount = values.Count,
            Score = Math.Max(score, 1)
        };
    }

    private static IReadOnlyList<string> ExtractSearchTerms(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return Array.Empty<string>();
        }

        return text
            .Split(new[] { ' ', ',', '\n', '\r', '\t', '.', ';', ':', '!', '?', '(', ')', '[', ']', '{', '}', '"', '\'' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(t => t.Trim())
            .Where(t => t.Length >= 3)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static HashSet<string> ExtractReferencedWildcardNames(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        }

        return WildcardRegex.Matches(text)
            .Select(match => match.Groups["name"].Value.Trim())
            .Where(name => !string.IsNullOrWhiteSpace(name))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    private async Task LoadTemplatesAsync()
    {
        try
        {
            var items = (await _templateService.GetTemplateNamesAsync())
                .Select(name => new TemplateOption(name, Path.Combine(_settingsService.GetTemplateDir(), $"{name}.txt")))
                .OrderBy(t => t.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();
            
            Templates = new ObservableCollection<TemplateOption>(items);
            if (SelectedTemplate == null && Templates.Count > 0)
            {
                SelectedTemplate = Templates[0];
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Error loading templates: {ex.Message}";
        }
    }

    private async Task<bool> EnsureInvokeOnlineAsync(bool showToastOnFailure)
    {
        try
        {
            var ok = await _invokeAIClient.IsReachableAsync();
            IsInvokeOnline = ok;
            if (!ok && showToastOnFailure)
            {
                _notifications?.ShowError("InvokeAI is offline. Start it, then click Generate again.", "InvokeAI");
                StatusText = "InvokeAI offline.";
            }
            return ok;
        }
        catch
        {
            IsInvokeOnline = false;
            if (showToastOnFailure)
            {
                _notifications?.ShowError("InvokeAI is offline. Start it, then click Generate again.", "InvokeAI");
                StatusText = "InvokeAI offline.";
            }
            return false;
        }
    }

    private async Task StartInvokeMonitorAsync()
    {
        _invokeMonitorCts?.Cancel();
        _invokeMonitorCts = new CancellationTokenSource();
        var token = _invokeMonitorCts.Token;

        await CheckInvokeStatusAsync(showToast: false, token);

        _ = Task.Run(async () =>
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(30), token);
                    await CheckInvokeStatusAsync(showToast: true, token);
                }
                catch (TaskCanceledException)
                {
                    break;
                }
            }
        }, token);
    }

    private async Task CheckInvokeStatusAsync(bool showToast, CancellationToken token)
    {
        var reachable = await _invokeAIClient.IsReachableAsync(token);
        IsInvokeOnline = reachable;
        if (reachable)
        {
            _invokeOfflineFailures = 0;
            if (_invokeOnline == null)
            {
                _invokeOnline = true;
                return;
            }

            if (_invokeOnline == false)
            {
                _invokeOnline = true;
                if (showToast)
                {
                    _notifications?.ShowInfo("InvokeAI is online.", "InvokeAI");
                }
            }
            return;
        }

        _invokeOfflineFailures++;
        var threshold = _generationInProgress ? InvokeOfflineFailureThresholdBusy : InvokeOfflineFailureThreshold;
        if (_invokeOnline == null)
        {
            if (_invokeOfflineFailures >= threshold)
            {
                _invokeOnline = false;
                if (showToast)
                {
                    _notifications?.ShowWarning("InvokeAI went offline. Start it to generate images.", "InvokeAI");
                }
            }
            return;
        }

        if (_invokeOnline == true && _invokeOfflineFailures >= threshold)
        {
            _invokeOnline = false;
            if (showToast)
            {
                _notifications?.ShowWarning("InvokeAI went offline. Start it to generate images.", "InvokeAI");
            }
        }
    }

    private async Task LoadTemplateContentAsync(TemplateOption? template)
    {
        if (template == null) return;
        try
        {
            PromptText = await _templateService.LoadTemplateAsync(template.Name);
            StatusText = $"Loaded template: {template.Name}";
        }
        catch (Exception ex)
        {
            StatusText = $"Failed to load template: {ex.Message}";
        }
    }

    private async Task SaveTemplateAsync(Window? owner)
    {
        if (SelectedTemplate == null)
        {
            await SaveTemplateAsAsync(owner);
            return;
        }

        try
        {
            await _templateService.SaveTemplateAsync(SelectedTemplate.Name, PromptText ?? string.Empty, Workflow);
            StatusText = $"Saved template: {SelectedTemplate.Name}";
        }
        catch (Exception ex)
        {
            StatusText = $"Failed to save template: {ex.Message}";
        }
    }

    private async Task CreateTemplateAsync(Window? owner)
    {
        var resolved = GetOwnerWindow(owner) ?? new Window();
        var name = await Views.TextInputDialog.ShowAsync("New Template", "Template name:", "new_template", resolved);
        if (string.IsNullOrWhiteSpace(name))
        {
            StatusText = "Template creation canceled.";
            return;
        }

        var trimmedName = name.Trim();
        if (trimmedName.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
        {
            StatusText = "Template name contains invalid filename characters.";
            return;
        }

        try
        {
            await _templateService.SaveTemplateAsync(trimmedName, string.Empty, Workflow);
            await LoadTemplatesAsync();

            var match = Templates.FirstOrDefault(t => string.Equals(t.Name, trimmedName, StringComparison.OrdinalIgnoreCase));
            if (match != null)
            {
                SelectedTemplate = match;
            }

            PromptText = string.Empty;
            StatusText = $"Created template: {trimmedName}";
        }
        catch (Exception ex)
        {
            StatusText = $"Failed to create template: {ex.Message}";
        }
    }

    private async Task SaveTemplateAsAsync(Window? owner)
    {
        var resolved = GetOwnerWindow(owner) ?? new Window();
        var suggestedName = SelectedTemplate?.Name ?? "new_template";
        var name = await Views.TextInputDialog.ShowAsync("Save Template As", "Template name:", suggestedName, resolved);
        if (string.IsNullOrWhiteSpace(name))
        {
            StatusText = "Template save canceled.";
            return;
        }

        var trimmedName = name.Trim();
        if (trimmedName.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
        {
            StatusText = "Template name contains invalid filename characters.";
            return;
        }

        try
        {
            await _templateService.SaveTemplateAsync(trimmedName, PromptText ?? string.Empty, Workflow);
            await LoadTemplatesAsync();
            var match = Templates.FirstOrDefault(t => string.Equals(t.Name, trimmedName, StringComparison.OrdinalIgnoreCase));
            if (match != null)
            {
                SelectedTemplate = match;
            }
            StatusText = $"Saved template: {trimmedName}";
        }
        catch (Exception ex)
        {
            StatusText = $"Failed to save template: {ex.Message}";
        }
    }

    private async Task GenerateTemplateFromThemeAsync(Window? owner)
    {
        var resolved = GetOwnerWindow(owner) ?? new Window();

        if (string.IsNullOrWhiteSpace(SelectedModel))
        {
            StatusText = "Select an Ollama model before using AI template generation.";
            await ShowInfoAsync(resolved, "No Model Selected", "Select an Ollama model first. Template generation needs a model.");
            return;
        }

        if (Wildcards.Count == 0)
        {
            StatusText = "No wildcards are available for template generation.";
            await ShowInfoAsync(resolved, "No Wildcards", "Load or create some wildcards first. The template builder relies on your wildcard library.");
            return;
        }

        var theme = await Views.TextInputDialog.ShowAsync(
            "Generate Template",
            "Describe the theme or concept for the template:",
            string.Empty,
            resolved);

        if (string.IsNullOrWhiteSpace(theme))
        {
            StatusText = "AI template generation canceled.";
            return;
        }

        var options = await ShowTemplateBuilderOptionsDialogAsync(resolved);
        if (options == null)
        {
            StatusText = "AI template generation canceled.";
            return;
        }

        var trimmedTheme = theme.Trim();

        try
        {
            StatusText = "Planning template wildcard shortlist...";
            var immediatePlan = BuildImmediateTemplatePlan(trimmedTheme, options);
            var plannerTask = PlanTemplateWildcardsAsync(trimmedTheme, options);

            var approvedWildcards = await ShowTemplateWildcardReviewDialogAsync(resolved, trimmedTheme, immediatePlan, options, plannerTask);
            if (approvedWildcards == null || approvedWildcards.Count == 0)
            {
                StatusText = "AI template generation canceled.";
                return;
            }

            StatusText = "Generating template candidates...";
            var candidates = await GenerateTemplateCandidatesAsync(trimmedTheme, options, approvedWildcards);
            var selected = await ShowTemplateCandidatePickerAsync(resolved, trimmedTheme, options, candidates);
            if (selected == null)
            {
                StatusText = "AI template generation canceled.";
                return;
            }

            PromptText = selected.Template;
            StatusText = $"Applied AI template '{selected.Name}'.";

            var saveNow = await ShowConfirmAsync(
                resolved,
                $"Applied '{selected.Name}'.\n\nWould you like to save this as a template now?");

            if (!saveNow)
            {
                return;
            }

            var templateName = await Views.TextInputDialog.ShowAsync(
                "Save AI Template",
                "Template name:",
                SuggestTemplateName(trimmedTheme),
                resolved);

            if (string.IsNullOrWhiteSpace(templateName))
            {
                StatusText = "Template applied but not saved.";
                return;
            }

            var trimmedName = templateName.Trim();
            if (trimmedName.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
            {
                StatusText = "Template name contains invalid filename characters.";
                return;
            }

            await _templateService.SaveTemplateAsync(trimmedName, PromptText ?? string.Empty, Workflow);
            await LoadTemplatesAsync();
            var match = Templates.FirstOrDefault(t => string.Equals(t.Name, trimmedName, StringComparison.OrdinalIgnoreCase));
            if (match != null)
            {
                SelectedTemplate = match;
            }

            StatusText = $"Saved AI template: {trimmedName}";
        }
        catch (Exception ex)
        {
            StatusText = $"AI template generation failed: {ex.Message}";
            await ShowInfoAsync(resolved, "Template Generation Failed", ex.Message);
        }
    }

    private void UpdateMissingWildcardsPreview(string? rawPrompt)
    {
        if (string.IsNullOrWhiteSpace(rawPrompt))
        {
            MissingWildcards = new ObservableCollection<string>();
            return;
        }

        var result = _promptProcessorService.ProcessPrompt(rawPrompt);
        MissingWildcards = new ObservableCollection<string>(
            result.MissingWildcards.OrderBy(s => s, StringComparer.OrdinalIgnoreCase));
    }

    private async Task LoadVariationsAsync()
    {
        try
        {
            var variations = await _systemPromptService.LoadVariationPromptsAsync();
            var previouslySelected = VariationOptions.Where(v => v.IsSelected).Select(v => v.Key).ToHashSet(StringComparer.OrdinalIgnoreCase);
            var options = variations
                .OrderBy(v => v.Name ?? v.Key, StringComparer.OrdinalIgnoreCase)
                .Select(v =>
            {
                var option = new VariationOption(v);
                option.IsSelected = previouslySelected.Count == 0 || previouslySelected.Contains(v.Key);
                return option;
            }).ToList();
            VariationOptions = new ObservableCollection<VariationOption>(options);
        }
        catch (Exception ex)
        {
            StatusText = $"Error loading variations: {ex.Message}";
        }
    }

    partial void OnSelectedTemplateChanged(TemplateOption? value)
    {
        _ = LoadTemplateContentAsync(value);
    }

    private async Task LoadModelsAsync()
    {
        try
        {
            var endpoints = BuildOllamaEndpointList();
            var attemptLogs = new List<string>();
            IReadOnlyList<string> models = Array.Empty<string>();
            Uri? usedEndpoint = null;

            foreach (var endpoint in endpoints)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Ollama: trying {endpoint} for /api/tags...");
                try
                {
                    using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
                    models = await _ollamaClient.GetModelNamesAsync(endpoint, cts.Token);
                    usedEndpoint = endpoint;
                    attemptLogs.Add($"✓ {endpoint} returned {models.Count} models.");
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Ollama: success from {endpoint}, models: {models.Count}.");
                    _ollamaClient.UpdateBaseAddress(endpoint);
                    break;
                }
                catch (Exception ex)
                {
                    attemptLogs.Add($"✗ {endpoint}: {ex.Message}");
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Ollama: failed {endpoint}: {ex.Message}");
                }
            }

            Models = new ObservableCollection<string>(models.OrderBy(m => m, StringComparer.OrdinalIgnoreCase));
            SelectedModel = Models.FirstOrDefault(m => string.Equals(m, _settingsService.Settings.DefaultOllamaModel, StringComparison.OrdinalIgnoreCase))
                            ?? Models.FirstOrDefault();

            StatusText = Models.Count > 0
                ? $"Loaded {Models.Count} models from {usedEndpoint}."
                : $"Failed to load models. Attempts: {string.Join(" | ", attemptLogs)}";
            if (Models.Count == 0)
            {
                _notifications?.ShowWarning("Ollama not reachable; using saved prompt tools only.", "Offline");
            }
            if (Models.Count == 0)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Ollama: no models loaded. Attempts: {string.Join(" | ", attemptLogs)}");
            }
        }
                    catch (Exception ex)
                    {
                        var target = _ollamaClient.BaseAddress?.ToString() ?? _settingsService.Settings.OllamaBaseUrl ?? "(not set)";
                        StatusText = $"Error loading models from {target}: {ex.Message}";
                        if (_settingsService.Settings.Verbose) Console.WriteLine($"Ollama: error loading models from {target}: {ex}");
                    }    }

    private async Task<(IReadOnlyList<string> Models, Uri? Endpoint, string? Error)> TryLoadOllamaModelsAsync()
    {
        var endpoints = BuildOllamaEndpointList();
        var attemptLogs = new List<string>();

        foreach (var endpoint in endpoints)
        {
            if (_settingsService.Settings.Verbose) Console.WriteLine($"Ollama: trying {endpoint} for /api/tags...");
            try
            {
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
                var models = await _ollamaClient.GetModelNamesAsync(endpoint, cts.Token);
                _ollamaClient.UpdateBaseAddress(endpoint);
                return (models.OrderBy(m => m, StringComparer.OrdinalIgnoreCase).ToList(), endpoint, null);
            }
            catch (Exception ex)
            {
                attemptLogs.Add($"{endpoint}: {ex.Message}");
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Ollama: failed {endpoint}: {ex.Message}");
            }
        }

        var error = attemptLogs.Count > 0 ? string.Join(" | ", attemptLogs) : "No Ollama endpoints configured.";
        return (Array.Empty<string>(), null, error);
    }

    private async Task ProcessPromptAsync()
    {
        ProcessedPromptSegments.Clear();
        _lastGeneration = null;
        (RerollPromptCommand as RelayCommand)?.NotifyCanExecuteChanged();

        if (string.IsNullOrWhiteSpace(PromptText))
        {
            OutputText = string.Empty;
            StatusText = "Enter a prompt.";
            return;
        }

        StatusText = "Generating prompt...";
        var result = _promptProcessorService.ProcessPrompt(PromptText);
        _lastGeneration = result;
        ApplyGenerationResult(result, "Prompt generated.");
        StatusText = "Prompt generated.";
        await Task.CompletedTask;
    }

    public Task<IReadOnlyList<string>> GetChoicesForWildcardAsync(string wildcardName)
    {
        var values = _wildcardService.GetAllValues(wildcardName)
            .OrderBy(v => v, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        return Task.FromResult<IReadOnlyList<string>>(values);
    }

    partial void OnSelectedWildcardBrowserItemChanged(WildcardBrowserItem? value)
    {
        WildcardPreviewText = value == null
            ? "Select a wildcard to preview its values, tags, and usage hints."
            : BuildWildcardBrowserPreview(value.Name);
    }

    public Task ApplyWildcardChoiceAsync(PromptSegmentViewModel segment, string newValue)
    {
        if (segment == null || !segment.IsWildcard)
        {
            return Task.CompletedTask;
        }

        if (_lastGeneration == null || string.IsNullOrWhiteSpace(segment.WildcardName))
        {
            segment.Text = newValue;
            RefreshProcessedOutput();
            StatusText = $"Applied '{newValue}' for {segment.WildcardName}.";
            return Task.CompletedTask;
        }

        var newContext = new Dictionary<string, ContextValue>(_lastGeneration.Context, StringComparer.OrdinalIgnoreCase);
        newContext[segment.WildcardName] = BuildContextValue(segment.WildcardName, newValue);
        var result = _promptProcessorService.ProcessPrompt(PromptText ?? string.Empty, _lastGeneration.Seed, newContext);
        _lastGeneration = result;
        ApplyGenerationResult(result, $"Applied '{newValue}' for {segment.WildcardName}.");
        return Task.CompletedTask;
    }

    public string? GetWildcardFileContent(string? wildcardName)
    {
        if (string.IsNullOrWhiteSpace(wildcardName))
        {
            return null;
        }
        return _wildcardService.GetWildcardFileContent(wildcardName);
    }

    public (string newText, int caret) InsertOrReplaceWildcardAt(string wildcardName, int caretIndex, int selectionStart, int selectionEnd)
    {
        var current = PromptText ?? string.Empty;
        var token = $"__{wildcardName}__";

        selectionStart = Math.Clamp(selectionStart, 0, current.Length);
        selectionEnd = Math.Clamp(selectionEnd, 0, current.Length);
        if (selectionEnd < selectionStart)
        {
            (selectionStart, selectionEnd) = (selectionEnd, selectionStart);
        }

        if (selectionEnd > selectionStart)
        {
            var updated = ReplaceRange(current, selectionStart, selectionEnd - selectionStart, token);
            PromptText = updated;
            return (updated, selectionStart + token.Length);
        }

        var enclosed = FindEnclosingWildcard(current, caretIndex);
        if (enclosed != null)
        {
            var updated = ReplaceRange(current, enclosed.Value.start, enclosed.Value.length, token);
            PromptText = updated;
            return (updated, enclosed.Value.start + token.Length);
        }

        var inserted = ReplaceRange(current, caretIndex, 0, token);
        PromptText = inserted;
        return (inserted, caretIndex + token.Length);
    }

    private void RefreshProcessedOutput()
    {
        var text = string.Join(" ", ProcessedPromptSegments
            .Select(p => p.Text?.Trim() ?? string.Empty)
            .Where(t => !string.IsNullOrWhiteSpace(t)));
        OutputText = _promptProcessorService.CleanupPrompt(text);
    }

    private static string ReplaceRange(string text, int start, int length, string replacement)
    {
        start = Math.Clamp(start, 0, text.Length);
        length = Math.Clamp(length, 0, text.Length - start);
        return text[..start] + replacement + text[(start + length)..];
    }

    private static (int start, int length)? FindEnclosingWildcard(string text, int position)
    {
        foreach (Match match in WildcardRegex.Matches(text))
        {
            if (position >= match.Index && position <= match.Index + match.Length)
            {
                return (match.Index, match.Length);
            }
        }
        return null;
    }

    private static (int replaceStart, int replaceLength, string query)? FindWildcardAutocompleteContext(string text, int caretIndex)
    {
        caretIndex = Math.Clamp(caretIndex, 0, text.Length);
        var delimiterPositions = new List<int>();
        var searchIndex = 0;

        while (searchIndex < caretIndex)
        {
            var found = text.IndexOf("__", searchIndex, StringComparison.Ordinal);
            if (found < 0 || found >= caretIndex)
            {
                break;
            }

            delimiterPositions.Add(found);
            searchIndex = found + 2;
        }

        if (delimiterPositions.Count == 0 || delimiterPositions.Count % 2 == 0)
        {
            return null;
        }

        var start = delimiterPositions[^1];
        var replaceStart = start;
        var queryStart = start + 2;
        if (queryStart > caretIndex)
        {
            return null;
        }

        var query = text[queryStart..caretIndex];
        if (query.Contains('\n') || query.Contains('\r'))
        {
            return null;
        }

        return (replaceStart, caretIndex - replaceStart, query);
    }

    private async Task EnhancePromptAsync()
    {
        var textToEnhance = string.IsNullOrWhiteSpace(OutputText) ? PromptText : OutputText;
        if (string.IsNullOrWhiteSpace(textToEnhance))
        {
            StatusText = "Generate a prompt first.";
            return;
        }

        await EnhancePromptTextAsync(textToEnhance, PromptText ?? string.Empty);
    }

    private async Task EnhancePromptTextAsync(string textToEnhance, string originalPrompt)
    {
        if (string.IsNullOrWhiteSpace(SelectedModel))
        {
            StatusText = "Select an Ollama model.";
            return;
        }

        var enhancementPrompt = await _systemPromptService.LoadEnhancementPromptAsync(_settingsService.Settings.EnhancementSystemPrompt);
        var selectedVariations = VariationOptions.Where(v => v.IsSelected).Select(v => v.Definition).ToList();

        _modelUsageTracker.Register(SelectedModel);
        var vm = new EnhancementResultViewModel(_ollamaClient, SelectedModel, textToEnhance, enhancementPrompt, selectedVariations, Models);
        vm.RequestReleaseModel += m => { _ = ReleaseModelAsync(m); };
        var win = new Views.EnhancementResultWindow(vm);
        var owner = GetOwnerWindow(null) ?? new Window();
        var result = await win.ShowDialog<EnhancementResult?>(owner);
        if (result != null)
        {
            OutputText = result.EnhancedPrompt;
            StatusText = "Enhanced prompt ready.";
            _historyManager.AddEntry(new HistoryEntry
            {
                OriginalPrompt = originalPrompt,
                ProcessedPrompt = OutputText,
                EnhancedPrompt = result.EnhancedPrompt,
                VariationPrompts = result.Variations,
                TemplateName = SelectedTemplate?.Name,
                OllamaModel = SelectedModel ?? "",
                Workflow = Workflow
            });
        }
        await UnloadModelsAsync();
    }

    private async Task GenerateImageAsync(Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var prompt = ResolvePromptForMain(OutputText, PromptText);
        if (string.IsNullOrWhiteSpace(prompt))
        {
            StatusText = "Generate or enter a prompt first.";
            return;
        }

        var dialogVm = new ImageGenerationOptionsViewModel(_invokeAIClient, _settingsService, _notifications)
        {
            Prompt = prompt,
            NegativePrompt = _settingsService.Settings.DefaultNegativePrompt,
            ModeBannerText = "New work: using defaults; model changes may update settings.",
            ShowModeBanner = true
        };
        var (ok, parametersList) = await ShowImageGenerationDialogAsync(dialogVm, owner);
        if (!ok || parametersList == null || parametersList.Count == 0)
        {
            StatusText = "Image generation cancelled.";
            return;
        }

        await EnqueueGenerationJobAsync(
            "Generate Images",
            async (job, token) =>
        {
            try
            {
                _generationInProgress = true;
                await RunGenerationPreviewAsync(
                    parametersList,
                    prompt,
                    "Generated",
                    Workflow,
                    owner,
                    "Generating images...",
                    allowLongPrompts: false,
                    job,
                    token,
                    waitForSaveSelection: false,
                    onSaveCompleted: async images =>
                    {
                        var entry = BuildHistoryEntryForGeneration(
                            PromptText ?? string.Empty,
                            prompt,
                            SelectedTemplate?.Name,
                            SelectedModel ?? "",
                            SelectedModel,
                            Workflow,
                            images);
                        _historyManager.AddEntry(entry);
                        StatusText = "Selected images saved to history.";
                        await Task.CompletedTask;
                    });
            }
            finally
            {
                _generationInProgress = false;
            }
        },
            GetDominantModelName(parametersList),
            GetEstimatedWorkUnits(parametersList));
    }

    private async Task ShowExperimentRunnerAsync(string? initialMode)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(PromptText))
        {
            StatusText = "Enter a prompt before running an experiment.";
            return;
        }

        var promptWildcards = ExtractWildcardNames(PromptText);
        var baselineGeneration = _lastGeneration;
        var experimentVm = new ExperimentRunnerViewModel(
            promptWildcards,
            _wildcardService.GetStructuredWildcards(),
            baselineGeneration?.Context,
            (wildcardName, lockedChoices) => BuildWildcardSweepBaselineResult(PromptText ?? string.Empty, wildcardName, lockedChoices),
            initialMode);
        var owner = GetOwnerWindow(null) ?? new Window();
        var experimentDialog = new Views.ExperimentRunnerWindow(experimentVm);
        var approved = await experimentDialog.ShowDialog<bool?>(owner);
        if (approved != true || experimentVm.Result == null)
        {
            StatusText = "Experiment cancelled.";
            return;
        }

        var imagePrompt = ResolvePromptForMain(OutputText, PromptText);
        if (string.IsNullOrWhiteSpace(imagePrompt))
        {
            StatusText = "Generate or enter a prompt first.";
            return;
        }

        var dialogVm = new ImageGenerationOptionsViewModel(_invokeAIClient, _settingsService, _notifications)
        {
            Prompt = imagePrompt,
            NegativePrompt = _settingsService.Settings.DefaultNegativePrompt,
            ModeBannerText = "Experiments use one fixed image setup. Keep this to one model and one image.",
            ShowModeBanner = true
        };

        var (ok, parametersList) = await ShowImageGenerationDialogAsync(dialogVm, owner);
        if (!ok || parametersList == null || parametersList.Count == 0)
        {
            StatusText = "Experiment cancelled.";
            return;
        }

        if (parametersList.Count != 1)
        {
            StatusText = "Experiments currently support one model and one image at a time.";
            return;
        }

        var request = experimentVm.Result;
        var promptSnapshot = PromptText ?? string.Empty;
        var outputSnapshot = OutputText;
        var generationSnapshot = baselineGeneration;
        var templateNameSnapshot = SelectedTemplate?.Name;
        var ollamaModelSnapshot = SelectedModel;
        await EnqueueGenerationJobAsync(
            $"Experiment: {request.Mode}",
            async (job, token) =>
        {
            _generationInProgress = true;
            try
            {
                var experiment = BuildExperimentJobs(request, parametersList[0], promptSnapshot, outputSnapshot, generationSnapshot);
                if (experiment.Jobs.Count == 0)
                {
                    StatusText = "Nothing to generate for this experiment.";
                    return;
                }

                await RunExperimentPreviewAsync(
                    experiment,
                    request,
                    owner,
                    $"Running {request.Mode.ToLowerInvariant()}...",
                    allowLongPrompts: false,
                    job,
                    token,
                    promptSnapshot,
                    ResolvePromptForMain(outputSnapshot, promptSnapshot),
                    templateNameSnapshot,
                    ollamaModelSnapshot);
            }
            catch (Exception ex)
            {
                StatusText = $"Experiment failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        },
            parametersList[0].Model?.Name,
            GetEstimatedWorkUnits(parametersList));
    }

    private Task ShowSettingsAsync(Window? owner)
    {
        return ShowSettingsAsync(owner, null);
    }

    private Task ShowSettingsAsync(Window? owner, string? sectionKey)
    {
        var vm = new SettingsViewModel(_settingsService, _ollamaClient, _notifications, _imageCacheService, _invokeAIClient);
        var win = new Views.SettingsWindow(vm);
        win.Opened += (_, _) =>
        {
            if (!string.IsNullOrWhiteSpace(sectionKey))
            {
                win.NavigateToGenerationSection(sectionKey);
            }
        };
        win.Closed += async (_, __) =>
        {
            if (vm.DialogResult == true)
            {
                _wildcardService.Reload(_settingsService.GetWildcardDirs());
                await LoadTemplatesAsync();
                await LoadModelsAsync();
                await LoadVariationsAsync();
                StatusText = "Settings saved.";
            }
            else
            {
                StatusText = "Settings closed.";
            }
        };
        win.Show(GetOwnerWindow(owner) ?? new Window());
        return Task.CompletedTask;
    }

    private async Task ShowHistoryAsync(Window? owner)
    {
        var resolved = GetOwnerWindow(owner) ?? new Window();
        var variations = await _systemPromptService.LoadVariationPromptsAsync();
        var vm = new HistoryViewerViewModel(_historyManager, _templateService, _imageCacheService, _historyIndexService, Workflow, variations, _settingsService);
        var win = new Views.HistoryViewerWindow { DataContext = vm };
        vm.RegenerateRequested = (entry, image, prompt, promptType) => RegenerateFromHistoryAsync(entry, image, prompt, promptType, win);
        vm.GenerateNewRequested = (entry, image, prompt, promptType) => GenerateNewFromHistoryAsync(entry, image, prompt, promptType, win);
        vm.EditRegenerateRequested = (entry, image, prompt, promptType) => RegenerateFromHistoryAsync(entry, image, prompt, promptType, win);
        vm.SeedVariationsRequested = (entry, image) => GenerateSeedVariationsFromHistoryAsync(entry, image, win);
        vm.LoraVariationsRequested = (entry, image) => GenerateLoraVariationsFromHistoryAsync(entry, image, win);
        vm.ModelVariationsRequested = (entry, image) => GenerateModelPermutationsFromHistoryAsync(entry, image, win);
        vm.EnhanceRequested = entry => EnhanceFromHistoryAsync(entry, win);
        vm.FillMissingVariationsRequested = (entry, missing) => FillMissingVariationsWithDialogAsync(entry, missing, win);
        vm.UpscaleRequested = (entry, image) => UpscaleImageFromHistoryAsync(entry, image, win);
        vm.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(HistoryViewerViewModel.DialogResult) && vm.DialogResult != null)
            {
                var loaded = vm.LoadPromptOverride
                             ?? vm.DialogResult.ProcessedPrompt
                             ?? vm.DialogResult.OriginalPrompt;
                PromptText = loaded;
                OutputText = loaded;
                SelectedModel = vm.DialogResult.OllamaModel;
                StatusText = "Loaded selected prompt from history.";
            }
        };
        win.Show(resolved);
    }

    private Task ShowAllImagesAsync(Window? owner)
    {
        var resolved = GetOwnerWindow(owner) ?? new Window();
        var vm = new AllImagesViewerViewModel(_historyManager, _templateService, _imageCacheService, _historyIndexService, Workflow);
        vm.UpscaleRequested = (entry, image) => UpscaleImageFromHistoryAsync(entry, image, resolved);
        vm.GenerateMoreRequested = (entry, image) => GenerateFromHistoryAsync(entry, image, null, null, resolved, applyModelFromSource: true, configureVm: null);
        vm.SeedVariationsRequested = (entry, image) => GenerateSeedVariationsFromHistoryAsync(entry, image, resolved);
        vm.LoraVariationsRequested = (entry, image) => GenerateLoraVariationsFromHistoryAsync(entry, image, resolved);
        vm.ModelVariationsRequested = (entry, image) => GenerateModelPermutationsFromHistoryAsync(entry, image, resolved);
        var win = new Views.AllImagesWindow(vm);
        win.Show(resolved);
        return Task.CompletedTask;
    }

    private Task ShowAnalyticsStudioAsync(Window? owner)
    {
        var resolved = GetOwnerWindow(owner) ?? new Window();
        var vm = new AnalyticsStudioViewModel(
            _historyManager,
            _templateService,
            Workflow,
            _aestheticScoringService,
            _promptMatchScoringService,
            _settingsService,
            _imageCacheService,
            _historyIndexService);
        vm.CompareRequested = async items =>
        {
            if (items.Count != 2) return;
            var leftBitmap = items[0].Bitmap;
            var rightBitmap = items[1].Bitmap;
            if (leftBitmap == null || rightBitmap == null) return;
            var compareVm = new CompareImagesViewModel(items[0].Entry, items[0].Image, leftBitmap,
                                                       items[1].Entry, items[1].Image, rightBitmap);
            var win = new Views.CompareImagesWindow { DataContext = compareVm };
            win.Show(resolved);
            await Task.CompletedTask;
        };
        var window = new Views.AnalyticsStudioWindow { DataContext = vm };
        vm.ViewDetailsRequested = async (entry, image, bitmap, navigationItems) =>
        {
            ShowHistoryImageDetailsWindow(entry, image, bitmap, window, navigationItems);
            await Task.CompletedTask;
        };
        vm.GenerateMoreRequested = (entry, image) => GenerateFromHistoryAsync(entry, image, null, null, window, applyModelFromSource: true, configureVm: null);
        vm.GenerateSeedVariationsRequested = (entry, image) => GenerateSeedVariationsFromHistoryAsync(entry, image, window);
        vm.GenerateLoraVariationsRequested = (entry, image) => GenerateLoraVariationsFromHistoryAsync(entry, image, window);
        window.Opened += (_, _) =>
        {
            if (vm.ConfirmAsync == null)
            {
                vm.ConfirmAsync = message => ShowConfirmAsync(window, message);
            }
            if (vm.ScoreByModelConfirmAsync == null)
            {
                vm.ScoreByModelConfirmAsync = request => ShowScoreByModelConfirmAsync(window, request);
            }
        };
        window.Show(resolved);
        return Task.CompletedTask;
    }

    private Task ShowKpiDashboardAsync(Window? owner)
    {
        var resolved = GetOwnerWindow(owner) ?? new Window();
        var vm = new KpiDashboardViewModel(_historyManager, Workflow, _kpiStats);
        var window = new Views.KpiDashboardWindow { DataContext = vm };
        window.Show(resolved);
        return Task.CompletedTask;
    }

    private Task ShowSchedulerTunerAsync(Window? owner)
    {
        var resolved = GetOwnerWindow(owner) ?? new Window();
        var vm = new SchedulerTunerViewModel(_invokeAIClient, _settingsService, _aestheticScoringService, _notifications);
        var window = new Views.SchedulerTunerWindow { DataContext = vm };
        window.Show(resolved);
        return Task.CompletedTask;
    }

    private Task ShowGenerationQueueAsync(Window? owner)
    {
        var resolved = GetOwnerWindow(owner) ?? new Window();
        var vm = new GenerationQueueViewModel(_generationQueue);
        var window = new Views.GenerationQueueWindow { DataContext = vm };
        window.Show(resolved);
        return Task.CompletedTask;
    }

    private void ShowHistoryImageDetailsWindow(
        HistoryEntry entry,
        HistoryImage image,
        Bitmap bitmap,
        Window owner,
        IReadOnlyList<ImageDetailNavigationItem>? navigationItems = null)
    {
        ImageDetailPresenter.Show(
            entry,
            image,
            bitmap,
            owner,
            _historyManager,
            _historyIndexService,
            _imageCacheService,
            (e, img) => UpscaleImageFromHistoryAsync(e, img, owner),
            (e, img) => GenerateFromHistoryAsync(e, img, null, null, owner, applyModelFromSource: true, configureVm: null),
            (e, img) => GenerateSeedVariationsFromHistoryAsync(e, img, owner),
            (e, img) => GenerateLoraVariationsFromHistoryAsync(e, img, owner),
            (e, img) => GenerateModelPermutationsFromHistoryAsync(e, img, owner),
            navigationItems: navigationItems);
    }


    private async Task<ScoreByModelConfirmResult> ShowScoreByModelConfirmAsync(Window owner, ScoreByModelConfirmRequest request)
    {
        var tcs = new TaskCompletionSource<ScoreByModelConfirmResult>();
        var includeScored = false;

        var estimateUnscored = FormatDuration(TimeSpan.FromSeconds(request.AverageSeconds * Math.Max(1, request.UnscoredCount)));
        var estimateAll = FormatDuration(TimeSpan.FromSeconds(request.AverageSeconds * Math.Max(1, request.TotalCount)));

        var message = new TextBlock
        {
            Text = $"Score {request.UnscoredCount} unscored images for model \"{request.ModelName}\" within the current filters?\n\n" +
                   $"Total images for model: {request.TotalCount}\n" +
                   $"Estimated time (unscored): {estimateUnscored} (avg {request.AverageSeconds:0.0}s per image).",
            TextWrapping = Avalonia.Media.TextWrapping.Wrap
        };

        var estimateLabel = new TextBlock
        {
            Text = $"Estimated time (with rescoring): {estimateAll}",
            IsVisible = false
        };
        estimateLabel.Classes.Add("subtle");

        var checkbox = new CheckBox
        {
            Content = "Include already scored images (rescore all)",
            IsChecked = false
        };
        checkbox.IsCheckedChanged += (_, _) =>
        {
            includeScored = checkbox.IsChecked == true;
            estimateLabel.IsVisible = includeScored;
        };

        var okButton = new Button { Content = "Proceed" };
        var cancelButton = new Button { Content = "Cancel" };

        var dialog = new Window
        {
            Width = 560,
            Height = 360,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Confirm",
            Content = new Grid
            {
                RowDefinitions = new RowDefinitions("*,Auto,Auto"),
                Margin = new Thickness(16),
                Children =
                {
                    message,
                    new StackPanel
                    {
                        Spacing = 6,
                        Children =
                        {
                            checkbox,
                            estimateLabel
                        }
                    },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = HorizontalAlignment.Right,
                        Spacing = 8,
                        Children =
                        {
                            cancelButton,
                            okButton
                        }
                    }
                }
            }
        };
        Grid.SetRow(((Grid)dialog.Content!).Children[1], 1);
        Grid.SetRow(((Grid)dialog.Content!).Children[2], 2);

        okButton.Click += (_, _) =>
        {
            tcs.TrySetResult(new ScoreByModelConfirmResult(true, includeScored));
            dialog.Close();
        };
        cancelButton.Click += (_, _) =>
        {
            tcs.TrySetResult(new ScoreByModelConfirmResult(false, false));
            dialog.Close();
        };

        await dialog.ShowDialog(owner);
        return await tcs.Task;
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

    private async Task<bool> ShowConfirmAsync(Window owner, string message)
    {
        var tcs = new TaskCompletionSource<bool>();
        var dialog = new Window
        {
            Width = 560,
            Height = 320,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Confirm",
            Content = new Grid
            {
                Margin = new Thickness(12),
                RowDefinitions = new RowDefinitions("*,Auto"),
                Children =
                {
                    new ScrollViewer
                    {
                        Content = new TextBlock
                        {
                            Text = message,
                            TextWrapping = Avalonia.Media.TextWrapping.Wrap
                        }
                    },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Right,
                        Spacing = 8,
                        Margin = new Thickness(0, 12, 0, 0),
                        Children =
                        {
                            new Button { Content = "Cancel" },
                            new Button { Content = "OK" }
                        }
                    }
                }
            }
        };

        var grid = dialog.Content as Grid;
        var actionBar = grid?.Children[1] as StackPanel;
        var cancelButton = actionBar?.Children[0] as Button;
        var okButton = actionBar?.Children[1] as Button;

        if (cancelButton != null)
        {
            cancelButton.Click += (_, __) =>
            {
                tcs.TrySetResult(false);
                dialog.Close();
            };
        }
        if (okButton != null)
        {
            okButton.Click += (_, __) =>
            {
                tcs.TrySetResult(true);
                dialog.Close();
            };
        }

        dialog.Show(owner);
        return await tcs.Task;
    }

    private async Task<TemplateBuilderOptions?> ShowTemplateBuilderOptionsDialogAsync(Window owner)
    {
        var tcs = new TaskCompletionSource<TemplateBuilderOptions?>();
        var complexityItems = new[] { "Balanced", "Minimal", "Rich" };
        var focusItems = new[] { "Balanced", "Character", "Environment", "Action" };

        var complexityCombo = new ComboBox
        {
            ItemsSource = complexityItems,
            SelectedIndex = 0
        };

        var focusCombo = new ComboBox
        {
            ItemsSource = focusItems,
            SelectedIndex = 0
        };

        var dialog = new Window
        {
            Width = 520,
            Height = 300,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Template Builder",
            Content = new StackPanel
            {
                Margin = new Thickness(12),
                Spacing = 12,
                Children =
                {
                    new TextBlock
                    {
                        Text = "Choose how dense and what kind of composition the AI should favor.",
                        TextWrapping = Avalonia.Media.TextWrapping.Wrap
                    },
                    new StackPanel
                    {
                        Spacing = 6,
                        Children =
                        {
                            new TextBlock { Text = "Complexity", FontWeight = Avalonia.Media.FontWeight.Bold },
                            complexityCombo
                        }
                    },
                    new StackPanel
                    {
                        Spacing = 6,
                        Children =
                        {
                            new TextBlock { Text = "Focus", FontWeight = Avalonia.Media.FontWeight.Bold },
                            focusCombo
                        }
                    },
                    new TextBlock
                    {
                        Text = "Balanced is the default. Minimal keeps the prompt lean. Rich uses more wildcard coverage.",
                        Classes = { "subtle" },
                        TextWrapping = Avalonia.Media.TextWrapping.Wrap
                    },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = HorizontalAlignment.Right,
                        Spacing = 8,
                        Children =
                        {
                            new Button { Content = "Cancel" },
                            new Button { Content = "Continue" }
                        }
                    }
                }
            }
        };

        var buttons = ((dialog.Content as StackPanel)?.Children.LastOrDefault() as StackPanel)?.Children;
        var cancelButton = buttons?[0] as Button;
        var okButton = buttons?[1] as Button;

        if (cancelButton != null)
        {
            cancelButton.Click += (_, __) =>
            {
                tcs.TrySetResult(null);
                dialog.Close();
            };
        }

        if (okButton != null)
        {
            okButton.Click += (_, __) =>
            {
                var complexity = NormalizeTemplateComplexity((complexityCombo.SelectedItem as string) ?? "Balanced");
                var focus = NormalizeTemplateFocus((focusCombo.SelectedItem as string) ?? "Balanced");
                tcs.TrySetResult(new TemplateBuilderOptions(complexity, focus));
                dialog.Close();
            };
        }

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(null);
            }
        };

        await dialog.ShowDialog(owner);
        return await tcs.Task;
    }

    private async Task<IReadOnlyList<string>?> ShowTemplateWildcardReviewDialogAsync(
        Window owner,
        string theme,
        TemplatePlanResult plan,
        TemplateBuilderOptions options,
        Task<TemplatePlanResult>? plannerTask = null)
    {
        var tcs = new TaskCompletionSource<IReadOnlyList<string>?>();
        var approvedWildcards = plan.SelectedWildcards
            .Where(name => !string.IsNullOrWhiteSpace(name) && _wildcardService.WildcardExists(name))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        var chipsPanel = new WrapPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Top
        };
        var emptyApprovedText = new TextBlock
        {
            Text = "No approved wildcards yet. Add from the picker on the right.",
            Classes = { "subtle" },
            TextWrapping = Avalonia.Media.TextWrapping.Wrap
        };
        var approvedSummaryText = new TextBlock
        {
            Classes = { "subtle" }
        };
        var filterBox = new TextBox
        {
            Watermark = "Filter wildcards..."
        };
        var wildcardList = new ListBox
        {
            Height = 260,
            ItemTemplate = new FuncDataTemplate<string>((name, _) =>
            {
                var text = new TextBlock
                {
                    Text = name
                };
                ToolTip.SetTip(text, BuildHumanReadableWildcardPreview(name));
                return text;
            }, true)
        };
        var previewBox = new TextBox
        {
            IsReadOnly = true,
            AcceptsReturn = true,
            TextWrapping = Avalonia.Media.TextWrapping.Wrap,
            MinHeight = 220
        };
        var addButton = new Button
        {
            Content = "Add Selected",
            Width = 120,
            HorizontalAlignment = HorizontalAlignment.Right
        };
        var plannerStatus = new TextBlock
        {
            Text = plannerTask == null
                ? "Review or adjust the fast local shortlist."
                : "AI planner is refining the shortlist...",
            Classes = { "subtle" },
            TextWrapping = Avalonia.Media.TextWrapping.Wrap
        };
        var strategyText = new TextBlock
        {
            Text = string.IsNullOrWhiteSpace(plan.Strategy)
                ? "Fast local shortlist based on your current wildcard library."
                : plan.Strategy,
            TextWrapping = Avalonia.Media.TextWrapping.Wrap
        };
        var missingIdeasText = new TextBlock
        {
            Classes = { "subtle" },
            TextWrapping = Avalonia.Media.TextWrapping.Wrap
        };

        var allWildcardNames = _wildcardService.GetWildcardNames()
            .OrderBy(n => n, StringComparer.OrdinalIgnoreCase)
            .ToList();
        var userEditedApprovedList = false;

        void RefreshApprovedSummary()
        {
            approvedSummaryText.Text = approvedWildcards.Count == 0
                ? "Approved count: 0"
                : $"Approved count: {approvedWildcards.Count}";
        }

        void RenderApprovedChips()
        {
            chipsPanel.Children.Clear();

            if (approvedWildcards.Count == 0)
            {
                emptyApprovedText.IsVisible = true;
                RefreshApprovedSummary();
                return;
            }

            emptyApprovedText.IsVisible = false;

            foreach (var wildcardName in approvedWildcards)
            {
                var removeButton = new Button
                {
                    Content = "x",
                    Width = 26,
                    Height = 26,
                    Padding = new Thickness(0),
                    Margin = new Thickness(6, 0, 0, 0),
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center
                };

                removeButton.Click += (_, __) =>
                {
                    approvedWildcards.RemoveAll(name => string.Equals(name, wildcardName, StringComparison.OrdinalIgnoreCase));
                    userEditedApprovedList = true;
                    RenderApprovedChips();
                };

                chipsPanel.Children.Add(new Border
                {
                    BorderBrush = Avalonia.Media.Brush.Parse("#3D6F99"),
                    BorderThickness = new Thickness(1),
                    Background = Avalonia.Media.Brush.Parse("#14324C"),
                    CornerRadius = new CornerRadius(999),
                    Padding = new Thickness(10, 6),
                    Margin = new Thickness(0, 0, 8, 8),
                    Child = new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        Spacing = 0,
                        Children =
                        {
                            new TextBlock
                            {
                                Text = wildcardName,
                                VerticalAlignment = VerticalAlignment.Center
                            },
                            removeButton
                        }
                    }
                });
            }

            RefreshApprovedSummary();
        }

        void RefreshWildcardPicker()
        {
            var filter = filterBox.Text?.Trim();
            var filtered = string.IsNullOrWhiteSpace(filter)
                ? allWildcardNames
                : allWildcardNames
                    .Where(n => n.Contains(filter, StringComparison.OrdinalIgnoreCase))
                    .ToList();

            wildcardList.ItemsSource = filtered;

            if (filtered.Count > 0)
            {
                var current = wildcardList.SelectedItem as string;
                if (current == null || !filtered.Contains(current, StringComparer.OrdinalIgnoreCase))
                {
                    wildcardList.SelectedItem = filtered[0];
                }
            }
            else
            {
                wildcardList.SelectedItem = null;
            }
        }

        void RefreshWildcardPreview()
        {
            previewBox.Text = wildcardList.SelectedItem is string selectedName
                ? BuildHumanReadableWildcardPreview(selectedName)
                : "Select a wildcard to preview its normalized contents.";
        }
        void ApplyPlanToUi(TemplatePlanResult updatedPlan, bool fromAi)
        {
            strategyText.Text = string.IsNullOrWhiteSpace(updatedPlan.Strategy)
                ? (fromAi ? "AI planner updated the shortlist." : "Fast local shortlist based on your current wildcard library.")
                : updatedPlan.Strategy;

            missingIdeasText.Text = updatedPlan.MissingWildcardIdeas.Count == 0
                ? "Missing wildcard opportunities: None"
                : $"Missing wildcard opportunities: {string.Join(", ", updatedPlan.MissingWildcardIdeas.Take(8))}";

            if (!userEditedApprovedList)
            {
                approvedWildcards.Clear();
                approvedWildcards.AddRange(updatedPlan.SelectedWildcards
                    .Where(name => !string.IsNullOrWhiteSpace(name) && _wildcardService.WildcardExists(name))
                    .Distinct(StringComparer.OrdinalIgnoreCase));
                RenderApprovedChips();
            }
        }

        ApplyPlanToUi(plan, fromAi: false);

        var dialog = new Window
        {
            Width = 1120,
            Height = 760,
            MinWidth = 960,
            MinHeight = 680,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Review Wildcard Plan",
            Content = new Grid
            {
                Margin = new Thickness(12),
                RowDefinitions = new RowDefinitions("Auto,*,Auto"),
                RowSpacing = 10,
                Children =
                {
                    new Border
                    {
                        BorderBrush = Avalonia.Media.Brush.Parse("#33506A"),
                        BorderThickness = new Thickness(1),
                        CornerRadius = new CornerRadius(6),
                        Padding = new Thickness(12),
                        Child = new StackPanel
                        {
                            Spacing = 8,
                            Children =
                            {
                                new TextBlock
                                {
                                    Text = $"Theme: {theme}",
                                    FontWeight = Avalonia.Media.FontWeight.Bold,
                                    FontSize = 16,
                                    TextWrapping = Avalonia.Media.TextWrapping.Wrap
                                },
                                new TextBlock
                                {
                                    Text = $"Mode: {options.DisplayComplexity} | Focus: {options.DisplayFocus}",
                                    Classes = { "subtle" }
                                },
                                plannerStatus,
                                strategyText,
                                missingIdeasText
                            }
                        }
                    },
                    new Grid
                    {
                        ColumnDefinitions = new ColumnDefinitions("1.2*,1*"),
                        ColumnSpacing = 14,
                        Children =
                        {
                            new Border
                            {
                                BorderBrush = Avalonia.Media.Brush.Parse("#33506A"),
                                BorderThickness = new Thickness(1),
                                CornerRadius = new CornerRadius(6),
                                Padding = new Thickness(12),
                                Child = new StackPanel
                                {
                                    Spacing = 8,
                                    Children =
                                    {
                                        new TextBlock
                                        {
                                            Text = "Approved Wildcards",
                                            FontWeight = Avalonia.Media.FontWeight.Bold,
                                            FontSize = 15
                                        },
                                        new TextBlock
                                        {
                                            Text = "Use the picker to add, and remove chips directly here. The generator will only use these approved wildcards.",
                                            Classes = { "subtle" },
                                            TextWrapping = Avalonia.Media.TextWrapping.Wrap
                                        },
                                        approvedSummaryText,
                                        new ScrollViewer
                                        {
                                            MinHeight = 180,
                                            VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto,
                                            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
                                            Content = chipsPanel
                                        },
                                        emptyApprovedText
                                    }
                                }
                            },
                            new Border
                            {
                                BorderBrush = Avalonia.Media.Brush.Parse("#33506A"),
                                BorderThickness = new Thickness(1),
                                CornerRadius = new CornerRadius(4),
                                Padding = new Thickness(10),
                                Child = new StackPanel
                                {
                                    Spacing = 8,
                                    Children =
                                    {
                                        new TextBlock
                                        {
                                            Text = "Wildcard Picker",
                                            FontWeight = Avalonia.Media.FontWeight.Bold,
                                            FontSize = 15
                                        },
                                        new TextBlock
                                        {
                                            Text = "Filter, inspect, and inject wildcards without typing names manually.",
                                            Classes = { "subtle" },
                                            TextWrapping = Avalonia.Media.TextWrapping.Wrap
                                        },
                                        filterBox,
                                        wildcardList,
                                        addButton,
                                        new TextBlock
                                        {
                                            Text = "Preview",
                                            FontWeight = Avalonia.Media.FontWeight.Bold
                                        },
                                        previewBox
                                    }
                                }
                            }
                        }
                    },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = HorizontalAlignment.Right,
                        Spacing = 8,
                        Margin = new Thickness(0, 4, 0, 0),
                        Children =
                        {
                            new Button { Content = "Cancel" },
                            new Button { Content = "Generate Templates" }
                        }
                    }
                }
            }
        };

        var grid = (Grid)dialog.Content!;
        Grid.SetRow(grid.Children[0], 0);
        Grid.SetRow(grid.Children[1], 1);
        Grid.SetRow(grid.Children[2], 2);

        var contentGrid = grid.Children[1] as Grid;
        if (contentGrid != null)
        {
            Grid.SetColumn(contentGrid.Children[0], 0);
            Grid.SetColumn(contentGrid.Children[1], 1);
        }

        filterBox.PropertyChanged += (_, args) =>
        {
            if (args.Property == TextBox.TextProperty)
            {
                RefreshWildcardPicker();
            }
        };
        wildcardList.SelectionChanged += (_, __) => RefreshWildcardPreview();

        addButton.Click += (_, __) =>
        {
            if (wildcardList.SelectedItem is not string selectedName)
            {
                return;
            }

            if (!approvedWildcards.Contains(selectedName, StringComparer.OrdinalIgnoreCase))
            {
                approvedWildcards.Add(selectedName);
                userEditedApprovedList = true;
                RenderApprovedChips();
            }
        };

        RenderApprovedChips();
        RefreshWildcardPicker();
        RefreshWildcardPreview();

        if (plannerTask != null)
        {
            _ = plannerTask.ContinueWith(task =>
            {
                Dispatcher.UIThread.Post(() =>
                {
                    if (task.IsCanceled)
                    {
                        plannerStatus.Text = "AI planner canceled. Using the fast local shortlist.";
                        return;
                    }

                    if (task.IsFaulted)
                    {
                        plannerStatus.Text = "AI planner failed. Using the fast local shortlist.";
                        return;
                    }

                    plannerStatus.Text = "AI planner suggestions loaded.";
                    if (task.Result.SelectedWildcards.Count > 0)
                    {
                        ApplyPlanToUi(task.Result, fromAi: true);
                    }
                });
            }, TaskScheduler.Default);
        }

        var buttons = (grid.Children[2] as StackPanel)?.Children;
        var cancelButton = buttons?[0] as Button;
        var okButton = buttons?[1] as Button;

        if (cancelButton != null)
        {
            cancelButton.Click += (_, __) =>
            {
                tcs.TrySetResult(null);
                dialog.Close();
            };
        }

        if (okButton != null)
        {
            okButton.Click += (_, __) =>
            {
                var approved = approvedWildcards
                    .Where(name => !string.IsNullOrWhiteSpace(name))
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .ToList();
                tcs.TrySetResult(approved.Count == 0 ? null : approved);
                dialog.Close();
            };
        }

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(null);
            }
        };

        await dialog.ShowDialog(owner);
        return await tcs.Task;
    }

    private async Task<TemplateCandidate?> ShowTemplateCandidatePickerAsync(
        Window owner,
        string theme,
        TemplateBuilderOptions options,
        IReadOnlyList<TemplateCandidate> candidates)
    {
        var tcs = new TaskCompletionSource<TemplateCandidate?>();
        var cards = new StackPanel { Spacing = 10 };
        var buttonMap = new Dictionary<Button, TemplateCandidate>();

        foreach (var candidate in candidates)
        {
            var applyButton = new Button
            {
                Content = $"Apply {candidate.Name}",
                HorizontalAlignment = HorizontalAlignment.Right,
                Width = 150
            };
            buttonMap[applyButton] = candidate;

            cards.Children.Add(new Border
            {
                BorderBrush = Avalonia.Media.Brush.Parse("#33506A"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(4),
                Padding = new Thickness(10),
                Child = new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = candidate.Name,
                            FontWeight = Avalonia.Media.FontWeight.Bold
                        },
                        new TextBlock
                        {
                            Text = candidate.Strategy,
                            Classes = { "subtle" },
                            TextWrapping = Avalonia.Media.TextWrapping.Wrap
                        },
                        new TextBox
                        {
                            Text = candidate.Template,
                            IsReadOnly = true,
                            AcceptsReturn = true,
                            TextWrapping = Avalonia.Media.TextWrapping.Wrap,
                            Height = 88
                        },
                        applyButton
                    }
                }
            });
        }

        var dialog = new Window
        {
            Width = 820,
            Height = 720,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Choose Template Candidate",
            Content = new Grid
            {
                Margin = new Thickness(12),
                RowDefinitions = new RowDefinitions("Auto,*,Auto"),
                RowSpacing = 10,
                Children =
                {
                    new StackPanel
                    {
                        Spacing = 4,
                        Children =
                        {
                            new TextBlock
                            {
                                Text = $"Theme: {theme}",
                                FontWeight = Avalonia.Media.FontWeight.Bold,
                                TextWrapping = Avalonia.Media.TextWrapping.Wrap
                            },
                            new TextBlock
                            {
                                Text = $"Mode: {options.DisplayComplexity} | Focus: {options.DisplayFocus}",
                                Classes = { "subtle" }
                            }
                        }
                    },
                    new ScrollViewer
                    {
                        Content = cards
                    },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = HorizontalAlignment.Right,
                        Children =
                        {
                            new Button { Content = "Cancel" }
                        }
                    }
                }
            }
        };

        var grid = (Grid)dialog.Content!;
        Grid.SetRow(grid.Children[0], 0);
        Grid.SetRow(grid.Children[1], 1);
        Grid.SetRow(grid.Children[2], 2);

        foreach (var pair in buttonMap)
        {
            var button = pair.Key;
            var candidate = pair.Value;
            button.Click += (_, __) =>
            {
                tcs.TrySetResult(candidate);
                dialog.Close();
            };
        }

        var cancel = (grid.Children[2] as StackPanel)?.Children[0] as Button;
        if (cancel != null)
        {
            cancel.Click += (_, __) =>
            {
                tcs.TrySetResult(null);
                dialog.Close();
            };
        }

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(null);
            }
        };

        await dialog.ShowDialog(owner);
        return await tcs.Task;
    }

    private Task ShowBrainstormingAsync(Window? arg)
    {
        const string message = "AI Brainstorming is not implemented yet.";
        StatusText = message;
        _notifications?.ShowInfo(message, "Brainstorming");
        return Task.CompletedTask;
    }

    private async Task ShowGenerationDefaultsDialogAsync(Window? owner)
    {
        var defaultsVm = new GenerationDefaultsViewModel();

        var currentScheduler = _settingsService.Settings.DefaultScheduler ?? "dpmpp_2m_k";
        var invokeOnline = await EnsureInvokeOnlineAsync(showToastOnFailure: true);
        try
        {
            if (invokeOnline)
            {
                var schedulers = await _invokeAIClient.GetSchedulersAsync();
                defaultsVm.SetSchedulers(schedulers, currentScheduler);
            }
            else
            {
                defaultsVm.SetSchedulers(new[] { currentScheduler }, currentScheduler);
                StatusText = "InvokeAI offline; using existing scheduler defaults.";
            }
        }
        catch
        {
            defaultsVm.SetSchedulers(new[] { currentScheduler }, currentScheduler);
        }

        defaultsVm.SetDefaults(_settingsService.Settings.GenerationDefaults ?? new(), _settingsService.Settings.DefaultBaseModelType ?? "sdxl");

        var dialog = new Views.GenerationDefaultsWindow { DataContext = defaultsVm };
        var resolved = GetOwnerWindow(owner) ?? new Window();
        dialog.Closed += async (_, __) =>
        {
            if (defaultsVm.DialogResult == true)
            {
                _settingsService.Settings.GenerationDefaults = defaultsVm.GetDefaultsSnapshot();
                _settingsService.Settings.DefaultBaseModelType = defaultsVm.CurrentBaseModelType;
                _settingsService.Settings.DefaultScheduler = defaultsVm.DefaultScheduler;
                var ok = await _settingsService.SaveSettingsAsync(_settingsService.Settings);
                if (ok)
                {
                    _notifications?.ShowInfo("Default generation options saved.", "Success");
                    StatusText = "Default generation options saved.";
                }
                else
                {
                    _notifications?.ShowError("Failed to save generation defaults.", "Error");
                    StatusText = "Failed to save generation defaults.";
                }
            }
            else
            {
                StatusText = "Default generation options unchanged.";
            }
        };
        dialog.Show(resolved);
    }

    private Task ShowSystemPromptsAsync(Window? arg)
    {
        var vm = new SystemPromptEditorViewModel(_settingsService);
        var win = new Views.SystemPromptEditorWindow { DataContext = vm };
        var resolved = GetOwnerWindow(arg) ?? new Window();
        win.Closed += (_, __) =>
        {
            StatusText = vm.DialogResult == true ? "System prompts saved." : "System prompt editor closed.";
        };
        win.Show(resolved);
        return Task.CompletedTask;
    }

    private async Task ShowInvokeAIModelDefaultsAsync(Window? arg)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }
        var vm = new InvokeAIModelDefaultsViewModel(_settingsService, _invokeAIClient, _notifications);
        var win = new Views.InvokeAIModelDefaultsWindow { DataContext = vm };
        var resolved = GetOwnerWindow(arg) ?? new Window();
        win.Show(resolved);
        return;
    }

    private async Task ShowInvokeAILoraDefaultsAsync(Window? arg)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }
        var vm = new InvokeAILoraDefaultsViewModel(_settingsService, _invokeAIClient, _notifications);
        var win = new Views.InvokeAILoraDefaultsWindow { DataContext = vm };
        var resolved = GetOwnerWindow(arg) ?? new Window();
        win.Show(resolved);
        return;
    }

    private Task ShowPromptEvolverAsync(Window? arg)
    {
        const string message = "Prompt Evolver is not implemented yet.";
        StatusText = message;
        _notifications?.ShowInfo(message, "Prompt Evolver");
        return Task.CompletedTask;
    }

    private async Task ShowPngMetadataViewerAsync(Window? owner)
    {
        var historyManager = (Avalonia.Application.Current as App)?.HistoryManagerService;
        var vm = new PngMetadataViewerViewModel(historyManager, _settingsService);
        vm.GenerateMergedRequested = GenerateFromMergedPngAsync;
        vm.GenerateGraphReplayRequested = GenerateFromPngGraphAsync;
        vm.BuildGenerationGraphJsonAsync = BuildGenerationGraphJsonAsync;
        vm.ShowJsonDiffRequested = ShowJsonDiffAsync;
        var win = new Views.PngMetadataViewerWindow(vm);
        var resolved = GetOwnerWindow(owner) ?? new Window();
        win.Show(resolved);
        await Task.CompletedTask;
    }

    private Task ShowHistoryIntegrityAsync(Window? owner)
    {
        var vm = new HistoryIntegrityViewModel(_historyManager, _imageCacheService);
        var win = new Views.HistoryIntegrityWindow { DataContext = vm };
        win.Show(GetOwnerWindow(owner) ?? new Window());
        return Task.CompletedTask;
    }

    public async Task GenerateFromMergedPngAsync(PngMergedGenerationRequest request, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        await EnqueueGenerationJobAsync(
            "Merged PNG Generation",
            async (job, token) =>
        {
            _generationInProgress = true;
            try
            {
                var prompt = string.IsNullOrWhiteSpace(request.Prompt) ? request.Parameters.Prompt : request.Prompt;
                await ResolveInvokeModelsAsync(request.Parameters);
                var parametersList = new List<InvokeAIGenerationParams> { request.Parameters };
                var workflow = !string.IsNullOrWhiteSpace(request.Workflow) ? request.Workflow : Workflow;

                await RunGenerationPreviewAsync(
                    parametersList,
                    prompt,
                    request.PromptType,
                    workflow,
                    owner,
                    "Generating images...",
                    allowLongPrompts: true,
                    job,
                    token,
                    waitForSaveSelection: false,
                    onSaveCompleted: async images =>
                    {
                        if (!request.SaveToHistory)
                        {
                            StatusText = "Merged generation complete (not saved).";
                            return;
                        }

                        if (request.TargetEntry != null && !request.CreateNewEntryOnSave)
                        {
                            AppendImagesToEntry(request.TargetEntry.Id, images);
                            StatusText = "Saved merged images to history entry.";
                        }
                        else
                        {
                            var entry = BuildHistoryEntryForGeneration(
                                request.Metadata.OriginalPrompt ?? prompt,
                                request.Metadata.ProcessedPrompt ?? prompt,
                                request.Metadata.TemplateName,
                                request.Metadata.OllamaModel ?? SelectedModel ?? string.Empty,
                                request.Parameters.Model?.Name,
                                workflow,
                                images);
                            _historyManager.AddEntry(entry);
                            StatusText = "Saved merged images to new history entry.";
                        }

                        await Task.CompletedTask;
                    });
            }
            catch (Exception ex)
            {
                StatusText = $"Merged generation failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        },
            request.Parameters.Model?.Name,
            1);
    }

    public async Task GenerateFromPngGraphAsync(PngGraphReplayRequest request, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        await EnqueueGenerationJobAsync(
            "Replay PNG Graph",
            async (job, token) =>
        {
            _generationInProgress = true;
            try
            {
                var workflow = !string.IsNullOrWhiteSpace(request.Workflow) ? request.Workflow : Workflow;
                var prompt = string.IsNullOrWhiteSpace(request.Prompt) ? request.Parameters?.Prompt ?? string.Empty : request.Prompt;
                await RunGraphReplayPreviewAsync(
                    request.Graph,
                    request.Parameters,
                    prompt,
                    request.PromptType,
                    workflow,
                    owner,
                    "Replaying PNG graph...",
                    job,
                    token,
                    waitForSaveSelection: false,
                    onSaveCompleted: async images =>
                    {
                        var shouldPersist = request.SaveToHistory || request.TargetEntry != null || request.CreateNewEntryOnSave;
                        if (!shouldPersist)
                        {
                            StatusText = "Replay complete (not saved).";
                            return;
                        }

                        if (request.TargetEntry != null && !request.CreateNewEntryOnSave)
                        {
                            AppendImagesToEntry(request.TargetEntry.Id, images);
                            StatusText = "Saved replayed image to history entry.";
                        }
                        else
                        {
                            var entry = BuildHistoryEntryForGeneration(
                                request.Metadata.OriginalPrompt ?? prompt,
                                request.Metadata.ProcessedPrompt ?? prompt,
                                request.Metadata.TemplateName,
                                request.Metadata.OllamaModel ?? SelectedModel ?? string.Empty,
                                request.Parameters?.Model?.Name,
                                workflow,
                                images);
                            _historyManager.AddEntry(entry);
                            StatusText = "Saved replayed image to new history entry.";
                        }

                        await Task.CompletedTask;
                    });
            }
            catch (Exception ex)
            {
                StatusText = $"Replay failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        },
            request.Parameters?.Model?.Name,
            1);
    }

    public async Task<string?> BuildGenerationGraphJsonAsync(InvokeAIGenerationParams parameters)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return null;
        }

        if (parameters.Model == null)
        {
            StatusText = "Cannot build graph JSON without a model.";
            return null;
        }

        try
        {
            await ResolveInvokeModelsAsync(parameters);
            var baseModel = parameters.Model?.Base ?? parameters.BaseModelType ?? string.Empty;
            var vaes = await _invokeAIClient.GetModelsAsync(baseModel, "vae");
            var isSdxl = string.Equals(baseModel, "sdxl", StringComparison.OrdinalIgnoreCase);
            var graph = isSdxl
                ? GraphBuilder.BuildSdxlGraph(parameters, vaes).Graph
                : GraphBuilder.BuildSd15Graph(parameters, vaes).Graph;

            return JsonSerializer.Serialize(graph, new JsonSerializerOptions { WriteIndented = true });
        }
        catch (Exception ex)
        {
            StatusText = $"Failed to build generation graph: {ex.Message}";
            return null;
        }
    }

    public Task ShowJsonDiffAsync(string title, string leftJson, string? rightJson)
    {
        var vm = new JsonDiffViewModel(title, leftJson, rightJson);
        if (string.IsNullOrWhiteSpace(rightJson))
        {
            vm.LeftTitle = title;
        }
        else
        {
            vm.LeftTitle = "PNG Graph JSON";
            vm.RightTitle = "Generation Graph JSON";
        }
        var win = new Views.JsonDiffWindow(vm);
        var resolved = (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow ?? new Window();
        win.Show(resolved);
        return Task.CompletedTask;
    }

    private async Task<GenerationPreviewResult> RunGraphReplayPreviewAsync(
        JsonObject graph,
        InvokeAIGenerationParams? parameters,
        string prompt,
        string promptType,
        string workflow,
        Window? owner,
        string statusText,
        GenerationJob? job = null,
        CancellationToken externalToken = default,
        bool waitForSaveSelection = true,
        Func<List<HistoryImage>, Task>? onSaveCompleted = null)
    {
        var savedImages = new List<HistoryImage>();
        var previewVm = new MultiImagePreviewViewModel();
        previewVm.InitializePlaceholders(1);
        previewVm.StatusText = statusText;
        previewVm.OnSaveSlot = slot =>
        {
            var image = CreateHistoryImageFromSlot(
                slot,
                parameters,
                promptType,
                prompt,
                workflow);
            image.GenerationParamsJson = parameters != null ? JsonSerializer.Serialize(parameters) : null;
            image.GenerationGraphJson = slot.GenerationGraphJson;
            savedImages.Add(image);
            return Task.CompletedTask;
        };
        previewVm.OnSaveCompleted = onSaveCompleted == null
            ? null
            : async () => await onSaveCompleted(savedImages);
        ConfigurePreviewCommands(previewVm);
        var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);
        if (externalToken.CanBeCanceled)
        {
            externalToken.Register(() => cts.Cancel());
        }
        if (job != null)
        {
            job.StatusMessage = statusText;
            job.UpdateProgress(0, 1);
            job.CancelAction = () => cts.Cancel();
        }
        _activeGenerationCts = cts;
        previewVm.OnEditAndRegenerate = async slot => await EditAndRegenerateSlotAsync(slot, preview);
        StatusText = statusText;

        try
        {
            var slot = previewVm.Slots.First();
            if (parameters != null)
            {
                ApplySlotGenerationMetadata(slot, parameters);
            }
            slot.GenerationGraphJson = graph.ToJsonString(new JsonSerializerOptions { WriteIndented = false });
            ApplyReplaySlotMetadata(slot, parameters, graph);
            slot.IsLoading = true;

            await _invokeGenerationGate.WaitAsync(cts.Token);
            InvokeAIGenerationResult result;
            try
            {
                result = await _invokeAIClient.GenerateImageFromGraphJsonAsync(graph, parameters?.SaveToGallery ?? false, cts.Token);
            }
            finally
            {
                _invokeGenerationGate.Release();
            }
            if (parameters != null)
            {
                RecordKpiGeneration(parameters, result.JobInfo, workflow);
            }
            if (_settingsService.Settings.ServerSafetyModeEnabled)
            {
                await _invokeAIClient.EmptyModelCacheAsync(cts.Token);
            }

            if (!cts.IsCancellationRequested)
            {
                previewVm.SetImage(0, result.ImageBytes);
                ApplyJobInfoToSlot(previewVm.Slots[0], result.JobInfo);
                slot.IsLoading = false;
                job?.UpdateProgress(1, 1);
            }
        }
        catch (OperationCanceledException)
        {
            previewVm.StatusText = StatusGenerationCancelled;
            cts.Cancel();
        }
        catch (InvokeAIJobFailedException ex)
        {
            if (parameters != null)
            {
                RecordKpiGeneration(parameters, ex.JobInfo, workflow);
            }
            previewVm.StatusText = $"Replay failed: {ex.Message}";
        }
        finally
        {
            if (ReferenceEquals(_activeGenerationCts, cts))
            {
                _activeGenerationCts = null;
            }
        }

        if (cts.IsCancellationRequested)
        {
            previewVm.StatusText = StatusGenerationCancelled;
            return new GenerationPreviewResult(null, savedImages);
        }

        previewVm.StatusText = StatusImagesReady;
        StatusText = StatusImagesReadyMain;
        if (!waitForSaveSelection)
        {
            _ = saveTask;
            return new GenerationPreviewResult(null, savedImages);
        }

        var saveResult = await saveTask;
        return new GenerationPreviewResult(saveResult, savedImages);
    }

    private void ApplyReplaySlotMetadata(ImageSlotViewModel slot, InvokeAIGenerationParams? parameters, JsonObject graph)
    {
        if (parameters != null)
        {
            ApplySlotGenerationMetadata(slot, parameters);
            return;
        }

        var nodes = graph["nodes"] as JsonObject;
        if (nodes == null)
        {
            return;
        }

        if (nodes["sdxl_model_loader"] is JsonObject modelNode &&
            modelNode["model"] is JsonObject modelObj &&
            modelObj["name"] is JsonValue modelNameVal &&
            modelNameVal.TryGetValue(out string? modelName))
        {
            slot.ModelUsed = modelName ?? "";
        }

        if (nodes["noise"] is JsonObject noise)
        {
            if (noise["seed"] is JsonValue seedVal && seedVal.TryGetValue(out int seed))
            {
                slot.Seed = seed.ToString(CultureInfo.InvariantCulture);
            }
            if (noise["width"] is JsonValue widthVal && widthVal.TryGetValue(out int width) &&
                noise["height"] is JsonValue heightVal && heightVal.TryGetValue(out int height))
            {
                slot.Size = $"{width}x{height}";
            }
        }
    }

    private void ApplySlotGenerationMetadata(ImageSlotViewModel slot, InvokeAIGenerationParams param)
    {
        slot.GenerationParams = param;
        slot.ModelUsed = param.Model?.Name ?? "";
        slot.Seed = FormatSeedLabel(param);
        if (param.BaseSeed != 0)
        {
            slot.IsRootSeed = param.Seed == param.BaseSeed;
            slot.RootSeedLabel = slot.IsRootSeed ? "" : $"Root seed: {param.BaseSeed}";
        }
        else
        {
            slot.RootSeedLabel = "";
            slot.IsRootSeed = false;
        }
        slot.Size = $"{param.Width}x{param.Height}";
        slot.LoraLabel = FormatLoraLabel(param);
        slot.PromptToolTip = param.Prompt ?? string.Empty;
    }

    private static InvokeAIGenerationParams? TryBuildParamsFromGraphJson(string? json)
    {
        if (string.IsNullOrWhiteSpace(json)) return null;
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return null;
            if (!root.TryGetProperty("nodes", out var nodes) || nodes.ValueKind != JsonValueKind.Object) return null;

            JsonElement? GetNode(string id)
            {
                if (nodes.TryGetProperty(id, out var node) && node.ValueKind == JsonValueKind.Object)
                {
                    return node;
                }
                return null;
            }

            string? GetNodeValue(string id)
            {
                var node = GetNode(id);
                if (node.HasValue && node.Value.TryGetProperty("value", out var value) && value.ValueKind == JsonValueKind.String)
                {
                    return value.GetString();
                }
                return null;
            }

            var p = new InvokeAIGenerationParams
            {
                Prompt = GetNodeValue("positive_prompt") ?? string.Empty,
                PositiveStylePrompt = GetNodeValue("positive_style_prompt"),
                NegativePrompt = GetNodeValue("content_negative_prompt"),
                NegativeStylePrompt = GetNodeValue("style_negative_prompt"),
                UseAutoCfgRescale = false
            };

            var modelNode = GetNode("sdxl_model_loader");
            if (modelNode.HasValue &&
                modelNode.Value.TryGetProperty("model", out var modelObj) &&
                modelObj.ValueKind == JsonValueKind.Object)
            {
                var name = modelObj.TryGetProperty("name", out var modelName) && modelName.ValueKind == JsonValueKind.String
                    ? modelName.GetString()
                    : string.Empty;
                var baseModel = modelObj.TryGetProperty("base", out var baseElem) && baseElem.ValueKind == JsonValueKind.String
                    ? baseElem.GetString()
                    : string.Empty;
                var key = modelObj.TryGetProperty("key", out var keyElem) && keyElem.ValueKind == JsonValueKind.String
                    ? keyElem.GetString()
                    : string.Empty;
                var hash = modelObj.TryGetProperty("hash", out var hashElem) && hashElem.ValueKind == JsonValueKind.String
                    ? hashElem.GetString()
                    : string.Empty;
                p.Model = new InvokeAIModel { Name = name ?? "", Base = baseModel ?? "", Key = key ?? "", Hash = hash ?? "" };
                p.BaseModelType = baseModel ?? p.BaseModelType;
            }

            var denoise = GetNode("sdxl_denoise_latents");
            if (denoise.HasValue)
            {
                if (denoise.Value.TryGetProperty("steps", out var steps) && steps.TryGetInt32(out var st)) p.Steps = st;
                if (denoise.Value.TryGetProperty("cfg_scale", out var cfg) && cfg.TryGetDouble(out var cfgVal)) p.CfgScale = cfgVal;
                if (denoise.Value.TryGetProperty("scheduler", out var sched) && sched.ValueKind == JsonValueKind.String)
                {
                    p.Scheduler = sched.GetString() ?? p.Scheduler;
                }
                if (denoise.Value.TryGetProperty("cfg_rescale_multiplier", out var rescale) && rescale.TryGetDouble(out var r)) p.CfgRescaleMultiplier = r;
            }

            var noise = GetNode("noise");
            if (noise.HasValue)
            {
                if (noise.Value.TryGetProperty("width", out var w) && w.TryGetInt32(out var wi)) p.Width = wi;
                if (noise.Value.TryGetProperty("height", out var h) && h.TryGetInt32(out var he)) p.Height = he;
                if (noise.Value.TryGetProperty("seed", out var seed) && seed.TryGetInt32(out var s)) p.Seed = s;
                if (noise.Value.TryGetProperty("use_cpu", out var useCpu) && useCpu.ValueKind is JsonValueKind.True or JsonValueKind.False)
                {
                    p.UseCpuNoise = useCpu.GetBoolean();
                }
            }

            var vaeNode = GetNode("sdxl_fp32_vae_loader");
            if (vaeNode.HasValue &&
                vaeNode.Value.TryGetProperty("vae_model", out var vaeObj) &&
                vaeObj.ValueKind == JsonValueKind.Object &&
                vaeObj.TryGetProperty("name", out var vaeName) &&
                vaeName.ValueKind == JsonValueKind.String)
            {
                p.VaeUsedName = vaeName.GetString();
            }

            if (modelNode.HasValue &&
                modelNode.Value.TryGetProperty("vae_precision", out var vaePrecision) &&
                vaePrecision.ValueKind == JsonValueKind.String)
            {
                p.VaePrecision = vaePrecision.GetString();
            }

            var l2iNode = GetNode("l2i");
            if (l2iNode.HasValue &&
                l2iNode.Value.TryGetProperty("fp32", out var fp32) &&
                fp32.ValueKind is JsonValueKind.True or JsonValueKind.False)
            {
                p.L2iFp32 = fp32.GetBoolean();
            }

            if (root.TryGetProperty("edges", out var edgesElem) && edgesElem.ValueKind == JsonValueKind.Array)
            {
                var hasStyleEdge = false;
                var usesPromptAsStyle = false;
                foreach (var edge in edgesElem.EnumerateArray())
                {
                    if (edge.ValueKind != JsonValueKind.Object) continue;
                    if (!edge.TryGetProperty("destination", out var dest) || dest.ValueKind != JsonValueKind.Object) continue;
                    var destNode = dest.TryGetProperty("node_id", out var destNodeElem) && destNodeElem.ValueKind == JsonValueKind.String
                        ? destNodeElem.GetString()
                        : null;
                    var destField = dest.TryGetProperty("field", out var destFieldElem) && destFieldElem.ValueKind == JsonValueKind.String
                        ? destFieldElem.GetString()
                        : null;
                    if (!string.Equals(destNode, "positive_conditioning", StringComparison.OrdinalIgnoreCase) ||
                        !string.Equals(destField, "style", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    hasStyleEdge = true;
                    if (edge.TryGetProperty("source", out var src) && src.ValueKind == JsonValueKind.Object)
                    {
                        var srcNode = src.TryGetProperty("node_id", out var srcNodeElem) && srcNodeElem.ValueKind == JsonValueKind.String
                            ? srcNodeElem.GetString()
                            : null;
                        if (string.Equals(srcNode, "positive_prompt", StringComparison.OrdinalIgnoreCase))
                        {
                            usesPromptAsStyle = true;
                        }
                    }
                }

                if (hasStyleEdge)
                {
                    p.UsePromptAsStyleWhenEmpty = usesPromptAsStyle;
                }
                else
                {
                    p.UsePromptAsStyleWhenEmpty = false;
                }
            }

            var loras = new List<LoraParameter>();
            foreach (var node in nodes.EnumerateObject())
            {
                if (!node.Name.StartsWith("lora_loader_", StringComparison.OrdinalIgnoreCase)) continue;
                if (node.Value.ValueKind != JsonValueKind.Object) continue;
                if (node.Value.TryGetProperty("lora", out var loraObj) && loraObj.ValueKind == JsonValueKind.Object)
                {
                    var loraName = loraObj.TryGetProperty("name", out var lName) && lName.ValueKind == JsonValueKind.String
                        ? lName.GetString()
                        : null;
                    double? weight = null;
                    if (node.Value.TryGetProperty("weight", out var weightElem) && weightElem.TryGetDouble(out var wVal))
                    {
                        weight = wVal;
                    }
                    if (!string.IsNullOrWhiteSpace(loraName))
                    {
                        loras.Add(new LoraParameter
                        {
                            Lora = new InvokeAIModel { Name = loraName ?? "" },
                            Weight = weight ?? 1.0
                        });
                    }
                }
            }
            if (loras.Count > 0)
            {
                p.Loras = loras;
            }

            return p;
        }
        catch
        {
            return null;
        }
    }

    private static bool AreParamsEquivalent(InvokeAIGenerationParams a, InvokeAIGenerationParams b)
    {
        if (!string.Equals(a.Prompt?.Trim(), b.Prompt?.Trim(), StringComparison.Ordinal)) return false;

        var aNeg = NormalizeNegativePrompts(a.NegativePrompt, a.NegativeStylePrompt);
        var bNeg = NormalizeNegativePrompts(b.NegativePrompt, b.NegativeStylePrompt);
        if (!string.Equals(aNeg.Content, bNeg.Content, StringComparison.Ordinal)) return false;
        if (!string.Equals(aNeg.Style, bNeg.Style, StringComparison.Ordinal)) return false;

        var aPosStyle = NormalizePositiveStylePrompt(a);
        var bPosStyle = NormalizePositiveStylePrompt(b);
        if (!string.Equals(aPosStyle, bPosStyle, StringComparison.Ordinal)) return false;
        if (a.Steps != b.Steps) return false;
        if (!NearlyEqual(a.CfgScale, b.CfgScale)) return false;
        if (a.Width != b.Width) return false;
        if (a.Height != b.Height) return false;
        if (a.Seed != b.Seed) return false;
        if (!string.Equals(NormalizeSchedulerForCompare(a.Scheduler), NormalizeSchedulerForCompare(b.Scheduler), StringComparison.Ordinal)) return false;
        if (!NearlyEqual(a.CfgRescaleMultiplier, b.CfgRescaleMultiplier)) return false;
        if (NormalizeBool(a.UseCpuNoise, false) != NormalizeBool(b.UseCpuNoise, false)) return false;
        if (NormalizeBool(a.L2iFp32, false) != NormalizeBool(b.L2iFp32, false)) return false;
        if (!string.Equals(NormalizeVaePrecision(a.VaePrecision), NormalizeVaePrecision(b.VaePrecision), StringComparison.OrdinalIgnoreCase)) return false;

        if (!string.Equals(a.Model?.Name?.Trim(), b.Model?.Name?.Trim(), StringComparison.OrdinalIgnoreCase)) return false;
        if (!string.Equals(a.Model?.Base?.Trim(), b.Model?.Base?.Trim(), StringComparison.OrdinalIgnoreCase)) return false;
        if (!string.Equals(a.VaeUsedName?.Trim(), b.VaeUsedName?.Trim(), StringComparison.OrdinalIgnoreCase)) return false;

        var aLoras = NormalizeLoras(a.Loras);
        var bLoras = NormalizeLoras(b.Loras);
        return string.Equals(aLoras, bLoras, StringComparison.Ordinal);
    }

    private static string NormalizePositiveStylePrompt(InvokeAIGenerationParams p)
    {
        var style = p.PositiveStylePrompt?.Trim() ?? string.Empty;
        if (!string.IsNullOrWhiteSpace(style)) return style;
        if (p.UsePromptAsStyleWhenEmpty)
        {
            return p.Prompt?.Trim() ?? string.Empty;
        }
        return string.Empty;
    }

    private static (string Content, string Style) NormalizeNegativePrompts(string? negativePrompt, string? negativeStylePrompt)
    {
        var content = negativePrompt?.Trim() ?? string.Empty;
        var style = negativeStylePrompt?.Trim() ?? string.Empty;

        if (!string.IsNullOrWhiteSpace(style) && content.EndsWith(style, StringComparison.Ordinal))
        {
            content = content.Substring(0, content.Length - style.Length).TrimEnd();
        }

        return (content, style);
    }

    private static string NormalizeSchedulerForCompare(string? scheduler)
    {
        var value = scheduler?.Trim() ?? string.Empty;
        if (string.IsNullOrWhiteSpace(value)) return string.Empty;
        if (value.EndsWith("_karras", StringComparison.OrdinalIgnoreCase))
        {
            value = value[..^"_karras".Length];
        }
        if (value.EndsWith("_k", StringComparison.OrdinalIgnoreCase))
        {
            value = value[..^"_k".Length];
        }
        return value;
    }

    private static bool NormalizeBool(bool? value, bool defaultValue)
    {
        return value ?? defaultValue;
    }

    private static string NormalizeVaePrecision(string? value)
    {
        return string.IsNullOrWhiteSpace(value) ? string.Empty : value.Trim();
    }

    private static bool NearlyEqual(double a, double b, double tolerance = 0.0001)
    {
        return Math.Abs(a - b) <= tolerance;
    }

    private static string NormalizeLoras(IReadOnlyList<LoraParameter>? loras)
    {
        if (loras == null || loras.Count == 0) return string.Empty;
        return string.Join("|", loras
            .Where(l => l?.Lora != null && !string.IsNullOrWhiteSpace(l.Lora.Name))
            .Select(l => $"{l!.Lora!.Name}:{l.Weight:0.###}")
            .OrderBy(s => s, StringComparer.OrdinalIgnoreCase));
    }

    private async Task ResolveInvokeModelsAsync(InvokeAIGenerationParams parameters)
    {
        var baseModel = parameters.BaseModelType;
        var modelName = parameters.Model?.Name;
        if (!string.IsNullOrWhiteSpace(modelName))
        {
            var models = await _invokeAIClient.GetModelsAsync(baseModel, "main");
            var resolved = models.FirstOrDefault(m =>
                string.Equals(m.Name, modelName, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(m.Key, modelName, StringComparison.OrdinalIgnoreCase));
            if (resolved != null)
            {
                parameters.Model = resolved;
            }
            else
            {
                parameters.Model = new InvokeAIModel
                {
                    Name = modelName,
                    Base = baseModel ?? string.Empty,
                    Type = "main"
                };
            }
        }

        if (parameters.Loras == null || parameters.Loras.Count == 0) return;
        var loraModels = await _invokeAIClient.GetModelsAsync(baseModel, "lora");
        foreach (var lora in parameters.Loras)
        {
            if (lora?.Lora == null || string.IsNullOrWhiteSpace(lora.Lora.Name)) continue;
            var loraName = lora.Lora.Name;
            var resolved = loraModels.FirstOrDefault(m =>
                string.Equals(m.Name, loraName, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(m.Key, loraName, StringComparison.OrdinalIgnoreCase));
            if (resolved != null)
            {
                lora.Lora = resolved;
            }
        }
    }

    private async Task ShowInfoAsync(Window owner, string title, string message)
    {
        var tcs = new TaskCompletionSource<bool>();
        var dialog = new Window
        {
            Width = 420,
            Height = 180,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = title,
            Content = new StackPanel
            {
                Margin = new Thickness(12),
                Spacing = 12,
                Children =
                {
                    new TextBlock { Text = message, TextWrapping = Avalonia.Media.TextWrapping.Wrap },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = HorizontalAlignment.Right,
                        Spacing = 8,
                        Children =
                        {
                            new Button { Content = "OK" }
                        }
                    }
                }
            }
        };

        var ok = ((dialog.Content as StackPanel)?.Children.LastOrDefault() as StackPanel)?.Children.FirstOrDefault() as Button;
        if (ok != null)
        {
            ok.Click += (_, __) =>
            {
                tcs.TrySetResult(true);
                dialog.Close();
            };
        }

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(true);
            }
        };

        await dialog.ShowDialog(owner);
        await tcs.Task;
    }

    private async Task ShowImageInterrogatorAsync(Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var vm = new ImageInterrogatorViewModel(_ollamaClient);
        var win = new Views.ImageInterrogatorWindow { DataContext = vm };
        var resolved = GetOwnerWindow(owner) ?? new Window();
        win.Closed += (_, __) => StatusText = "Image interrogator closed.";
        win.Show(resolved);
    }

    private Task ShowModelStatsAsync(Window? owner)
    {
        var vm = new ModelStatsViewModel(_historyManager);
        var win = new Views.ModelStatsWindow { DataContext = vm };
        var resolved = GetOwnerWindow(owner) ?? new Window();
        win.Show(resolved);
        return Task.CompletedTask;
    }

    private async Task ShowWildcardManagerAsync(Window? owner)
    {
        await ShowWildcardManagerAsync(owner, null);
    }

    private async Task OpenWildcardInManagerAsync(string? wildcardName)
    {
        await ShowWildcardManagerAsync(GetOwnerWindow(null), wildcardName);
    }

    private async Task ShowWildcardManagerAsync(Window? owner, string? wildcardName)
    {
        OpenWildcardManagerWindow(owner, wildcardName);
        await Task.CompletedTask;
    }

    private Views.WildcardManagerWindow OpenWildcardManagerWindow(Window? owner, string? wildcardName)
    {
        var vm = new WildcardManagerViewModel(_wildcardService, _templateService);
        var win = new Views.WildcardManagerWindow(vm);
        if (!string.IsNullOrWhiteSpace(wildcardName))
        {
            win.SelectWildcardOnOpen(wildcardName);
        }
        var resolved = GetOwnerWindow(owner) ?? new Window();
        win.Show(resolved);
        return win;
    }

    private async Task RegenerateFromHistoryAsync(HistoryEntry entry, HistoryImage? image, string? promptOverride, string? promptTypeOverride, Window? owner)
    {
        await GenerateFromHistoryAsync(entry, image, promptOverride, promptTypeOverride, owner, applyModelFromSource: true, configureVm: null);
    }

    private async Task GenerateNewFromHistoryAsync(HistoryEntry entry, HistoryImage? image, string? promptOverride, string? promptTypeOverride, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        await EnqueueGenerationJobAsync("Generate New Image", async (job, token) =>
        {
            _generationInProgress = true;
            try
            {
                var prompt = ResolvePromptForHistoryGeneration(entry, image, baseParams: null, promptOverride, includeEnhanced: true).prompt;
                if (string.IsNullOrWhiteSpace(prompt))
                {
                    StatusText = "No prompt available to generate.";
                    return;
                }

                var resolvedPromptType = string.IsNullOrWhiteSpace(promptTypeOverride) ? "Generated" : promptTypeOverride!;
                var hasExistingType = !string.IsNullOrWhiteSpace(promptTypeOverride) &&
                                      entry.Images.Any(img => string.Equals(img.PromptType, promptTypeOverride, StringComparison.OrdinalIgnoreCase));
                var appendToExisting = !string.IsNullOrWhiteSpace(promptTypeOverride) && !hasExistingType;

                var dialogVm = new ImageGenerationOptionsViewModel(_invokeAIClient, _settingsService, _notifications)
                {
                    Prompt = prompt,
                    NegativePrompt = _settingsService.Settings.DefaultNegativePrompt,
                    ModeBannerText = appendToExisting
                        ? "Iterative: adding image to this entry for the selected prompt variant."
                        : "New work: using defaults; model changes may update settings.",
                    ShowModeBanner = true
                };

                var (ok, parametersList) = await ShowImageGenerationDialogAsync(dialogVm, owner);
                if (!ok || parametersList == null || parametersList.Count == 0)
                {
                    StatusText = "Image generation cancelled.";
                    return;
                }

                var workflow = entry.Workflow ?? Workflow;
                await RunGenerationPreviewAsync(
                    parametersList,
                    prompt,
                    resolvedPromptType,
                    workflow,
                    owner,
                    "Generating images...",
                    allowLongPrompts: true,
                    job,
                    token,
                    waitForSaveSelection: false,
                    onSaveCompleted: async images =>
                    {
                        if (appendToExisting)
                        {
                            AppendImagesToEntry(entry.Id, images, image);
                            StatusText = "Selected images saved to history entry.";
                        }
                        else
                        {
                            var newEntry = BuildHistoryEntryForGeneration(
                                entry.OriginalPrompt ?? prompt,
                                prompt,
                                entry.TemplateName,
                                entry.OllamaModel ?? "",
                                entry.InvokeAIModel,
                                workflow,
                                images);
                            _historyManager.AddEntry(newEntry);
                            StatusText = "Selected images saved to history.";
                        }
                        await Task.CompletedTask;
                    });
            }
            catch (Exception ex)
            {
                StatusText = $"Image generation failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        });
    }

    private async Task GenerateSeedVariationsFromHistoryAsync(HistoryEntry entry, HistoryImage? image, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var graphJson = image?.GenerationGraphJson;
        var graphParams = TryBuildParamsFromGraphJson(graphJson);
        var baseParams = graphParams ?? image?.GenerationParams;
        baseParams ??= entry.ImageParameters ?? TryParseGenerationParamsJson(image?.GenerationParamsJson);
        if (baseParams == null)
        {
            StatusText = "No generation parameters available for seed variations.";
            return;
        }

        var ownerWindow = GetOwnerWindow(owner) ?? new Window();
        var baseSeed = baseParams.BaseSeed != 0 ? baseParams.BaseSeed : baseParams.Seed;
        var options = await Views.SeedVariationDialog.ShowAsync(ownerWindow, defaultCount: 4, initialSeed: baseSeed);
        if (options == null)
        {
            StatusText = "Seed variations cancelled.";
            return;
        }

        var prompt = ResolvePromptForHistoryGeneration(entry, image, baseParams, promptOverride: null, includeEnhanced: true).prompt;
        var fallbackModel = baseParams.Model?.Name ?? entry.InvokeAIModel;
        if (!await EnsureSeedVariationParamsAsync(baseParams, fallbackModel))
        {
            StatusText = "Seed variations failed: missing model information.";
            return;
        }

        var seeds = BuildSeedVariationSeeds(options);
        if (seeds.Count == 0)
        {
            StatusText = "No seeds selected for variations.";
            return;
        }

        var parametersList = BuildSeedVariationParams(
            baseParams,
            prompt,
            seeds,
            options.RandomSeeds ? null : options.RootSeed);
        var workflow = entry.Workflow ?? Workflow;
        await EnqueueGenerationJobAsync(
            "Seed Variations",
            async (job, token) =>
        {
            try
            {
                _generationInProgress = true;
                var rootBytes = options.MirrorSeeds ? TryLoadHistoryImageBytes(image) : null;
                if (options.MirrorSeeds && rootBytes != null)
                {
                    await RunSeedVariationPreviewAsync(
                        parametersList,
                        prompt,
                        "Seed Variations",
                        workflow,
                        owner,
                        "Generating seed variations...",
                        allowLongPrompts: true,
                        rootSeed: options.RootSeed,
                        rootImageBytes: rootBytes,
                        job,
                        token,
                        waitForSaveSelection: false,
                        onSaveCompleted: async images =>
                        {
                            AppendImagesToEntry(entry.Id, images, image);
                            StatusText = "Selected images saved to history entry.";
                            await Task.CompletedTask;
                        });
                }
                else
                {
                    await RunGenerationPreviewAsync(
                        parametersList,
                        prompt,
                        "Seed Variations",
                        workflow,
                        owner,
                        "Generating seed variations...",
                        allowLongPrompts: true,
                        job,
                        token,
                        waitForSaveSelection: false,
                        onSaveCompleted: async images =>
                        {
                            AppendImagesToEntry(entry.Id, images, image);
                            StatusText = "Selected images saved to history entry.";
                            await Task.CompletedTask;
                        });
                }
            }
            catch (Exception ex)
            {
                StatusText = $"Seed variations failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        },
            GetDominantModelName(parametersList),
            GetEstimatedWorkUnits(parametersList));
    }

    private async Task GenerateLoraVariationsFromHistoryAsync(HistoryEntry entry, HistoryImage? image, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var baseParams = image?.GenerationParams
                         ?? entry.ImageParameters
                         ?? TryParseGenerationParamsJson(image?.GenerationParamsJson);
        if (baseParams == null)
        {
            StatusText = "No generation parameters available for LoRA permutations.";
            return;
        }

        var (prompt, _) = ResolvePromptForHistoryGeneration(entry, image, baseParams, promptOverride: null, includeEnhanced: false);
        var permutations = await ShowLoraPermutationDialogAsync(baseParams, owner);
        if (permutations == null)
        {
            StatusText = "LoRA permutations cancelled.";
            return;
        }

        await EnqueueGenerationJobAsync(
            "LoRA Permutations",
            async (job, token) =>
        {
            _generationInProgress = true;
            try
            {
                var parametersList = new List<InvokeAIGenerationParams>();
                foreach (var perm in permutations)
                {
                    var p = CloneParams(baseParams);
                    p.Prompt = prompt;
                    p.Loras = perm.Select(l => new LoraParameter { Lora = l.Lora, Weight = l.Weight }).ToList();
                    parametersList.Add(p);
                }

                var workflow = entry.Workflow ?? Workflow;
                await RunGenerationPreviewAsync(
                    parametersList,
                    prompt,
                    "LoRA Permutation",
                    workflow,
                    owner,
                    "Generating LoRA permutations...",
                    allowLongPrompts: true,
                    job,
                    token,
                    waitForSaveSelection: false,
                    onSaveCompleted: async images =>
                    {
                        AppendImagesToEntry(entry.Id, images, image);
                        StatusText = "Selected images saved to history entry.";
                        await Task.CompletedTask;
                    });
            }
            catch (Exception ex)
            {
                StatusText = $"LoRA permutations failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        },
            baseParams.Model?.Name ?? entry.InvokeAIModel,
            permutations.Count);
    }

    private async Task GenerateModelPermutationsFromHistoryAsync(HistoryEntry entry, HistoryImage? image, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var baseParams = image?.GenerationParams
                         ?? entry.ImageParameters
                         ?? TryParseGenerationParamsJson(image?.GenerationParamsJson);
        if (baseParams == null)
        {
            StatusText = "No generation parameters available for model permutations.";
            return;
        }

        var (prompt, _) = ResolvePromptForHistoryGeneration(entry, image, baseParams, promptOverride: null, includeEnhanced: false);

        var dialogVm = new ImageGenerationOptionsViewModel(_invokeAIClient, _settingsService, _notifications)
        {
            Prompt = prompt,
            NegativePrompt = _settingsService.Settings.DefaultNegativePrompt
        };
        dialogVm.ApplyGenerationParams(baseParams);
        dialogVm.Prompt = prompt;
        dialogVm.UseRandomSeed = false;
        dialogVm.Seed = baseParams.BaseSeed != 0 ? baseParams.BaseSeed : baseParams.Seed;
        dialogVm.NumImages = 1;
        dialogVm.SkipDefaultPrefixes = true;
        dialogVm.AllowLongPromptWarningOnly = true;
        dialogVm.DisableAutoDefaults = true;
        dialogVm.ModeBannerText = "Iterative: using original image params; defaults are disabled.";
        dialogVm.ShowModeBanner = true;
        dialogVm.DisableModelSelection(baseParams.Model?.Name);

        var (ok, parametersList) = await ShowImageGenerationDialogAsync(dialogVm, owner ?? GetOwnerWindow(null));
        if (!ok || parametersList == null || parametersList.Count == 0)
        {
            StatusText = "Model permutations cancelled.";
            return;
        }

        await EnqueueGenerationJobAsync(
            "Model Permutations",
            async (job, token) =>
        {
            _generationInProgress = true;
            try
            {
                foreach (var param in parametersList)
                {
                    param.Prompt = prompt;
                }

                var workflow = entry.Workflow ?? Workflow;
                await RunGenerationPreviewAsync(
                    parametersList,
                    prompt,
                    "Model Permutation",
                    workflow,
                    owner,
                    "Generating model permutations...",
                    allowLongPrompts: true,
                    job,
                    token,
                    waitForSaveSelection: false,
                    onSaveCompleted: async images =>
                    {
                        AppendImagesToEntry(entry.Id, images, image);
                        StatusText = "Selected images saved to history entry.";
                        await Task.CompletedTask;
                    });
            }
            catch (Exception ex)
            {
                StatusText = $"Model permutations failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        },
            GetDominantModelName(parametersList),
            GetEstimatedWorkUnits(parametersList));
    }

    private async Task GenerateVariationsFromSlotAsync(ImageSlotViewModel slot, bool seedVariations, MultiImagePreviewViewModel? previewVm = null)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var baseParams = slot.GenerationParams;
        if (baseParams == null)
        {
            StatusText = "No generation parameters available for variations.";
            return;
        }

        var prompt = ResolvePromptForSlot(baseParams, PromptText);
        Views.SeedVariationDialog.SeedVariationOptions? seedOptions = null;
        List<InvokeAIGenerationParams>? preparedParams = null;
        List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>? queuedSeedVariationJobs = null;
        var previewHadActiveGeneration = false;
        byte[]? rootBytes = null;

        if (seedVariations)
        {
            var ownerWindow = GetOwnerWindow(null) ?? new Window();
            var baseSeed = baseParams.BaseSeed != 0 ? baseParams.BaseSeed : baseParams.Seed;
            seedOptions = await Views.SeedVariationDialog.ShowAsync(ownerWindow, defaultCount: 4, initialSeed: baseSeed);
            if (seedOptions == null)
            {
                StatusText = "Seed variations cancelled.";
                return;
            }

            var fallbackModel = baseParams.Model?.Name ?? slot.ModelUsed;
            if (!await EnsureSeedVariationParamsAsync(baseParams, fallbackModel))
            {
                StatusText = "Seed variations failed: missing model information.";
                return;
            }

            var seeds = BuildSeedVariationSeeds(seedOptions);
            if (seeds.Count == 0)
            {
                StatusText = "No seeds selected for variations.";
                return;
            }

            preparedParams = BuildSeedVariationParams(
                baseParams,
                prompt,
                seeds,
                seedOptions.RandomSeeds ? null : seedOptions.RootSeed);
            rootBytes = seedOptions.MirrorSeeds ? slot.ImageBytes : null;

            if (previewVm != null)
            {
                previewHadActiveGeneration = previewVm.GenerationToken != null &&
                                             !previewVm.GenerationToken.IsCancellationRequested &&
                                             previewVm.Slots.Any(existing => existing.IsLoading);
                var slotIndex = previewVm.Slots.IndexOf(slot);
                if (slotIndex < 0)
                {
                    slotIndex = previewVm.Slots.Count - 1;
                }

                queuedSeedVariationJobs = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
                var beforeInsertIndex = slotIndex;
                var afterInsertIndex = slotIndex + 1;
                var counter = 1;
                foreach (var param in preparedParams)
                {
                    if (seedOptions.MirrorSeeds && rootBytes != null && param.Seed == seedOptions.RootSeed)
                    {
                        continue;
                    }

                    var label = $"Variation {counter}";
                    var newSlot = previewVm.CreatePlaceholderSlot(label);
                    if (param.BaseSeed != 0)
                    {
                        newSlot.IsRootSeed = param.Seed == param.BaseSeed;
                        newSlot.RootSeedLabel = newSlot.IsRootSeed ? string.Empty : $"Root seed: {param.BaseSeed}";
                    }
                    ApplySlotGenerationMetadata(newSlot, param);

                    if (seedOptions.MirrorSeeds && param.Seed < seedOptions.RootSeed)
                    {
                        previewVm.Slots.Insert(beforeInsertIndex, newSlot);
                        beforeInsertIndex++;
                        afterInsertIndex++;
                    }
                    else
                    {
                        previewVm.Slots.Insert(afterInsertIndex, newSlot);
                        afterInsertIndex++;
                    }

                    counter++;
                    queuedSeedVariationJobs.Add((param, newSlot));
                }

                if (queuedSeedVariationJobs.Count == 0)
                {
                    StatusText = "No seed variations selected.";
                    return;
                }

                previewVm.SyncProgressFromSlots();
                previewVm.StatusText = "Queued seed variations...";
                if (previewVm.GenerationToken == null || previewVm.GenerationToken.IsCancellationRequested)
                {
                    previewVm.GenerationToken = new CancellationTokenSource();
                }
            }
        }
        else
        {
            var seedForVariations = baseParams.BaseSeed != 0 ? baseParams.BaseSeed : baseParams.Seed;
            var dialogVm = new ImageGenerationOptionsViewModel(_invokeAIClient, _settingsService, _notifications)
            {
                Prompt = prompt,
                NegativePrompt = _settingsService.Settings.DefaultNegativePrompt
            };
            dialogVm.ApplyGenerationParams(baseParams);
            dialogVm.Prompt = prompt;
            dialogVm.Seed = seedForVariations;
            dialogVm.UseRandomSeed = false;
            dialogVm.SkipDefaultPrefixes = true;
            dialogVm.AllowLongPromptWarningOnly = true;
            dialogVm.DisableAutoDefaults = true;
            dialogVm.ModeBannerText = "Iterative: using original image params; defaults are disabled.";
            dialogVm.ShowModeBanner = true;
            dialogVm.NumImages = Math.Max(dialogVm.NumImages, 3);

            var (ok, parametersList) = await ShowImageGenerationDialogAsync(dialogVm, GetOwnerWindow(null));
            if (!ok || parametersList == null || parametersList.Count == 0)
            {
                StatusText = "Image generation cancelled.";
                return;
            }
            preparedParams = parametersList;
        }

        if (seedVariations && seedOptions != null && preparedParams != null && previewVm != null)
        {
            try
            {
                _generationInProgress = true;
                var jobs = queuedSeedVariationJobs ?? new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
                if (previewHadActiveGeneration)
                {
                    previewVm.EnqueuePendingVariationJobs(jobs);
                    previewVm.StatusText = "Queued seed variations for current model...";
                    StatusText = "Queued seed variations for current model.";
                    return;
                }

                previewVm.StatusText = "Generating seed variations...";
                StatusText = "Generating seed variations...";

                var generationToken = previewVm.GenerationToken;
                if (generationToken == null || generationToken.IsCancellationRequested)
                {
                    generationToken = new CancellationTokenSource();
                    previewVm.GenerationToken = generationToken;
                }

                if (jobs.Count > 0)
                {
                    await GenerateImagesForSlotsAsync(jobs, previewVm, generationToken, allowLongPrompts: true, job: null);
                }

                previewVm.StatusText = StatusImagesReady;
                StatusText = StatusImagesReadyMain;
            }
            catch (Exception ex)
            {
                StatusText = $"Seed variations failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }

            return;
        }

        await EnqueueGenerationJobAsync(
            seedVariations ? "Seed Variations" : "Variations",
            async (job, token) =>
        {
            _generationInProgress = true;
            try
            {
                if (seedVariations && seedOptions != null && preparedParams != null)
                {
                    if (previewVm != null)
                    {
                        return;
                    }
                    else
                    {
                        if (seedOptions.MirrorSeeds && rootBytes != null)
                        {
                            await RunSeedVariationPreviewAsync(
                                preparedParams,
                                prompt,
                                "Seed Variations",
                                Workflow,
                                null,
                                "Generating seed variations...",
                                allowLongPrompts: true,
                                rootSeed: seedOptions.RootSeed,
                                rootImageBytes: rootBytes,
                                job,
                                token,
                                waitForSaveSelection: false,
                                onSaveCompleted: async images =>
                                {
                                    var entry = BuildHistoryEntryForGeneration(
                                        PromptText ?? string.Empty,
                                        prompt,
                                        SelectedTemplate?.Name,
                                        SelectedModel ?? "",
                                        SelectedModel,
                                        Workflow,
                                        images);
                                    _historyManager.AddEntry(entry);
                                    StatusText = "Selected images saved to history.";
                                    await Task.CompletedTask;
                                });
                        }
                        else
                        {
                            await RunGenerationPreviewAsync(
                                preparedParams,
                                prompt,
                                "Seed Variations",
                                Workflow,
                                null,
                                "Generating seed variations...",
                                allowLongPrompts: true,
                                job,
                                token,
                                waitForSaveSelection: false,
                                onSaveCompleted: async images =>
                                {
                                    var entry = BuildHistoryEntryForGeneration(
                                        PromptText ?? string.Empty,
                                        prompt,
                                        SelectedTemplate?.Name,
                                        SelectedModel ?? "",
                                        SelectedModel,
                                        Workflow,
                                        images);
                                    _historyManager.AddEntry(entry);
                                    StatusText = "Selected images saved to history.";
                                    await Task.CompletedTask;
                                });
                        }
                    }
                    return;
                }

                if (preparedParams == null || preparedParams.Count == 0)
                {
                    StatusText = "Image generation cancelled.";
                    return;
                }

                await RunGenerationPreviewAsync(
                    preparedParams,
                    prompt,
                    "Generated",
                    Workflow,
                    null,
                    "Generating images...",
                    allowLongPrompts: true,
                    job,
                    token,
                    waitForSaveSelection: false,
                    onSaveCompleted: async images =>
                    {
                        var entry = BuildHistoryEntryForGeneration(
                            PromptText ?? string.Empty,
                            prompt,
                            SelectedTemplate?.Name,
                            SelectedModel ?? "",
                            SelectedModel,
                            Workflow,
                            images);
                        _historyManager.AddEntry(entry);
                        StatusText = "Selected images saved to history.";
                        await Task.CompletedTask;
                    });
            }
            catch (Exception ex)
            {
                StatusText = $"Image generation failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        },
            GetDominantModelName(preparedParams),
            GetEstimatedWorkUnits(preparedParams));
    }

    private static List<InvokeAIGenerationParams> BuildSeedVariationParams(InvokeAIGenerationParams baseParams, string prompt, IReadOnlyList<int> seeds, int? rootSeed)
    {
        if (seeds.Count == 0)
        {
            return new List<InvokeAIGenerationParams>();
        }

        var baseSeed = rootSeed.HasValue && rootSeed.Value != 0 ? rootSeed.Value : seeds[0];
        var parametersList = new List<InvokeAIGenerationParams>(seeds.Count);
        foreach (var seed in seeds)
        {
            var clone = CloneParams(baseParams);
            clone.Prompt = prompt;
            clone.Seed = seed;
            clone.BaseSeed = baseSeed;
            clone.UsedRandomSeed = false;
            parametersList.Add(clone);
        }
        return parametersList;
    }

    private static List<int> BuildSeedVariationSeeds(Views.SeedVariationDialog.SeedVariationOptions options)
    {
        var count = Math.Max(1, options.Count);
        var seeds = new List<int>(count);
        if (options.RandomSeeds)
        {
            var rng = new Random();
            for (int i = 0; i < count; i++)
            {
                seeds.Add(rng.Next(0, int.MaxValue));
            }
            return seeds;
        }

        if (options.MirrorSeeds)
        {
            var root = options.RootSeed;
            for (int i = count; i >= 1; i--)
            {
                var before = root - i;
                if (before >= 0)
                {
                    seeds.Add(before);
                }
            }
            seeds.Add(root);
            for (int i = 1; i <= count; i++)
            {
                var after = root + i;
                seeds.Add(after);
            }
            return seeds;
        }

        var minimumSequentialSeed = options.RootSeed == int.MaxValue
            ? int.MaxValue
            : Math.Max(0, options.RootSeed + 1);
        var start = Math.Max(options.StartSeed, minimumSequentialSeed);
        var end = options.EndSeed;
        if (end < start)
        {
            end = start;
        }
        var rangeCount = (int)Math.Min((long)end - start + 1, int.MaxValue);
        count = Math.Min(count, rangeCount);
        for (int i = 0; i < count; i++)
        {
            var next = start + i;
            if (next < 0)
            {
                next = 0;
            }
            seeds.Add(next);
        }
        return seeds;
    }

    private async Task<bool> EnsureSeedVariationParamsAsync(InvokeAIGenerationParams baseParams, string? fallbackModelName)
    {
        if (baseParams.Model == null && !string.IsNullOrWhiteSpace(fallbackModelName))
        {
            baseParams.Model = new InvokeAIModel
            {
                Name = fallbackModelName,
                Base = baseParams.BaseModelType ?? string.Empty,
                Type = "main"
            };
        }
        else if (baseParams.Model != null && string.IsNullOrWhiteSpace(baseParams.Model.Type))
        {
            baseParams.Model = baseParams.Model with { Type = "main" };
        }

        if (string.IsNullOrWhiteSpace(baseParams.BaseModelType) && !string.IsNullOrWhiteSpace(baseParams.Model?.Base))
        {
            baseParams.BaseModelType = baseParams.Model?.Base;
        }
        if (string.IsNullOrWhiteSpace(baseParams.BaseModelType) && !string.IsNullOrWhiteSpace(_settingsService.Settings.DefaultBaseModelType))
        {
            baseParams.BaseModelType = _settingsService.Settings.DefaultBaseModelType;
        }

        if (baseParams.Model == null)
        {
            return false;
        }

        await ResolveInvokeModelsAsync(baseParams);
        return baseParams.Model != null && !string.IsNullOrWhiteSpace(baseParams.Model.Name);
    }

    private async Task GenerateLoraPermutationsFromSlotAsync(ImageSlotViewModel slot, MultiImagePreviewViewModel previewVm)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var baseParams = slot.GenerationParams;
        if (baseParams == null)
        {
            StatusText = "No generation parameters available for LoRA permutations.";
            return;
        }

        var permutations = await ShowLoraPermutationDialogAsync(baseParams, GetOwnerWindow(null));
        if (permutations == null || permutations.Count == 0)
        {
            StatusText = "LoRA permutations cancelled.";
            return;
        }

        var prompt = ResolvePromptForSlot(baseParams, PromptText);
        var previewHadActiveGeneration = previewVm.GenerationToken != null &&
                                         !previewVm.GenerationToken.IsCancellationRequested &&
                                         previewVm.Slots.Any(existing => existing.IsLoading);
        var slotIndex = previewVm.Slots.IndexOf(slot);
        if (slotIndex < 0) slotIndex = previewVm.Slots.Count - 1;

        var jobs = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
        var insertIndex = slotIndex + 1;
        var counter = 1;
        foreach (var perm in permutations)
        {
            var p = CloneParams(baseParams);
            p.Prompt = prompt;
            p.Loras = perm.Select(l => new LoraParameter { Lora = l.Lora, Weight = l.Weight }).ToList();

            var label = $"Permutation {counter}";
            var newSlot = previewVm.CreatePlaceholderSlot(label);
            ApplySlotGenerationMetadata(newSlot, p);
            previewVm.Slots.Insert(insertIndex, newSlot);
            insertIndex++;
            counter++;

            jobs.Add((p, newSlot));
        }
        previewVm.SyncProgressFromSlots();

        if (previewHadActiveGeneration)
        {
            previewVm.EnqueuePendingVariationJobs(jobs);
            previewVm.StatusText = "Queued LoRA permutations for current model...";
            StatusText = "Queued LoRA permutations for current model.";
            return;
        }

        previewVm.StatusText = "Generating LoRA permutations...";
        if (previewVm.GenerationToken == null)
        {
            previewVm.GenerationToken = new CancellationTokenSource();
        }
        await GenerateImagesForSlotsAsync(jobs, previewVm, previewVm.GenerationToken, allowLongPrompts: true, job: null);
        previewVm.StatusText = StatusImagesReady;
    }

    private async Task GenerateModelPermutationsFromSlotAsync(ImageSlotViewModel slot, MultiImagePreviewViewModel previewVm)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var baseParams = slot.GenerationParams ?? TryBuildParamsFromGraphJson(slot.GenerationGraphJson);
        if (baseParams == null)
        {
            StatusText = "No generation parameters available for model permutations.";
            return;
        }

        var prompt = ResolvePromptForSlot(baseParams, PromptText);
        var dialogVm = new ImageGenerationOptionsViewModel(_invokeAIClient, _settingsService, _notifications)
        {
            Prompt = prompt,
            NegativePrompt = _settingsService.Settings.DefaultNegativePrompt
        };
        dialogVm.ApplyGenerationParams(baseParams);
        dialogVm.Prompt = prompt;
        dialogVm.UseRandomSeed = false;
        dialogVm.Seed = baseParams.BaseSeed != 0 ? baseParams.BaseSeed : baseParams.Seed;
        dialogVm.NumImages = 1;
        dialogVm.SkipDefaultPrefixes = true;
        dialogVm.AllowLongPromptWarningOnly = true;
        dialogVm.DisableAutoDefaults = true;
        dialogVm.ModeBannerText = "Iterative: using original image params; defaults are disabled.";
        dialogVm.ShowModeBanner = true;
        dialogVm.DisableModelSelection(baseParams.Model?.Name);

        var (ok, parametersList) = await ShowImageGenerationDialogAsync(dialogVm, GetOwnerWindow(null));
        if (!ok || parametersList == null || parametersList.Count == 0)
        {
            StatusText = "Model permutations cancelled.";
            return;
        }

        var slotIndex = previewVm.Slots.IndexOf(slot);
        if (slotIndex < 0) slotIndex = previewVm.Slots.Count - 1;
        var previewHadActiveGeneration = previewVm.GenerationToken != null &&
                                         !previewVm.GenerationToken.IsCancellationRequested &&
                                         previewVm.Slots.Any(existing => existing.IsLoading);

        var jobs = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
        var insertIndex = slotIndex + 1;
        var counter = 1;
        foreach (var param in parametersList)
        {
            var label = param.Model?.Name ?? $"Model {counter}";
            if (parametersList.Count > 1)
            {
                label = $"{label} {counter}";
            }

            var newSlot = previewVm.CreatePlaceholderSlot(label);
            ApplySlotGenerationMetadata(newSlot, param);
            previewVm.Slots.Insert(insertIndex, newSlot);
            insertIndex++;
            counter++;

            jobs.Add((param, newSlot));
        }
        previewVm.SyncProgressFromSlots();

        if (previewHadActiveGeneration)
        {
            previewVm.EnqueuePendingVariationJobs(jobs);
            previewVm.StatusText = "Queued model permutations for current preview...";
            StatusText = "Queued model permutations for current preview.";
            return;
        }

        previewVm.StatusText = "Generating model permutations...";
        if (previewVm.GenerationToken == null)
        {
            previewVm.GenerationToken = new CancellationTokenSource();
        }
        await GenerateImagesForSlotsAsync(jobs, previewVm, previewVm.GenerationToken, allowLongPrompts: true, job: null);
        previewVm.StatusText = StatusImagesReady;
    }

    private async Task EditAndRegenerateSlotAsync(ImageSlotViewModel slot, Window owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var baseParams = slot.GenerationParams;
        var graphJson = slot.GenerationGraphJson;
        var graphParams = TryBuildParamsFromGraphJson(graphJson);
        if (graphParams != null)
        {
            baseParams = graphParams;
        }
        if (baseParams == null)
        {
            StatusText = "No generation parameters available for edit/regenerate.";
            return;
        }

        var dialogVm = new ImageGenerationOptionsViewModel(_invokeAIClient, _settingsService, _notifications)
        {
            NegativePrompt = _settingsService.Settings.DefaultNegativePrompt
        };
        dialogVm.ApplyGenerationParams(baseParams);
        if (string.IsNullOrWhiteSpace(dialogVm.Prompt))
        {
            dialogVm.Prompt = PromptText ?? baseParams.Prompt ?? string.Empty;
        }
        dialogVm.SkipDefaultPrefixes = true;
        dialogVm.AllowLongPromptWarningOnly = true;
        dialogVm.DisableAutoDefaults = true;
        dialogVm.ModeBannerText = "Iterative: using original image params; defaults are disabled.";
        dialogVm.ShowModeBanner = true;

        var (ok, list) = await ShowImageGenerationDialogAsync(dialogVm, owner);
        if (!ok || list == null || list.Count == 0)
        {
            StatusText = "Edit/regenerate cancelled.";
            return;
        }

        try
        {
            _generationInProgress = true;
            slot.IsLoading = true;
            slot.Image = null;
            var newParam = list.First();
            if (!ValidateGenerationParams(newParam, allowLongPrompts: true, out var invalidParamMessage, out var isWarning))
            {
                StatusText = invalidParamMessage;
                return;
            }
            if (isWarning)
            {
                StatusText = invalidParamMessage;
            }
            await _invokeGenerationGate.WaitAsync();
            InvokeAIGenerationResult result;
            try
            {
                if (!string.IsNullOrWhiteSpace(graphJson) && graphParams != null && AreParamsEquivalent(newParam, graphParams))
                {
                    var graphObj = JsonNode.Parse(graphJson) as JsonObject;
                    if (graphObj == null)
                    {
                        result = await _invokeAIClient.GenerateImageAsync(newParam);
                    }
                    else
                    {
                        result = await _invokeAIClient.GenerateImageFromGraphJsonAsync(graphObj, newParam.SaveToGallery);
                    }
                }
                else
                {
                    result = await _invokeAIClient.GenerateImageAsync(newParam);
                }
            }
            finally
            {
                _invokeGenerationGate.Release();
            }
            if (_settingsService.Settings.ServerSafetyModeEnabled)
            {
                await _invokeAIClient.EmptyModelCacheAsync();
            }
            slot.GenerationParams = newParam;
            slot.GenerationGraphJson = graphJson;
            slot.ModelUsed = newParam.Model?.Name ?? slot.ModelUsed;
            slot.Seed = FormatSeedLabel(newParam);
            slot.Size = $"{newParam.Width}x{newParam.Height}";
            slot.LoraLabel = FormatLoraLabel(newParam);

            if (owner.DataContext is MultiImagePreviewViewModel previewVm)
            {
                previewVm.UpdateSlotImage(slot, result.ImageBytes);
            }
            else
            {
                using var ms = new MemoryStream(result.ImageBytes);
                slot.Image = new Bitmap(ms);
                slot.ImageBytes = result.ImageBytes;
            }
            slot.IsLoading = false;
            StatusText = "Image regenerated.";
        }
        catch (OperationCanceledException)
        {
            StatusText = "Edit/regenerate cancelled.";
        }
        catch (Exception ex)
        {
            StatusText = "Failed to regenerate image.";
            if (_settingsService.Settings.Verbose) Console.WriteLine($"Edit/regenerate error: {ex.Message}");
        }
        finally
        {
            _generationInProgress = false;
        }
    }
    private async Task GenerateFromHistoryAsync(
        HistoryEntry entry,
        HistoryImage? image,
        string? promptOverride,
        string? promptTypeOverride,
        Window? owner,
        bool applyModelFromSource,
        Action<ImageGenerationOptionsViewModel>? configureVm)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        await EnqueueGenerationJobAsync("Regenerate Image", async (job, token) =>
        {
            _generationInProgress = true;
            try
            {
                var graphJson = image?.GenerationGraphJson;
                var graphParams = TryBuildParamsFromGraphJson(graphJson);
                var baseParams = graphParams ?? image?.GenerationParams;
                baseParams ??= entry.ImageParameters ?? TryParseGenerationParamsJson(image?.GenerationParamsJson);
                var (prompt, promptSource) = ResolvePromptForHistoryGeneration(entry, image, baseParams, promptOverride, includeEnhanced: true);
                var promptType = !string.IsNullOrWhiteSpace(promptTypeOverride) ? promptTypeOverride : "Regenerated";
                var dialogVm = new ImageGenerationOptionsViewModel(_invokeAIClient, _settingsService, _notifications)
                {
                    Prompt = prompt
                };

                if (baseParams != null)
                {
                    dialogVm.ApplyGenerationParams(baseParams);
                }
                if (!string.IsNullOrWhiteSpace(prompt))
                {
                    dialogVm.Prompt = prompt;
                }
                var isHistoryRegen = baseParams != null;
                dialogVm.SkipDefaultPrefixes = isHistoryRegen;
                dialogVm.AllowLongPromptWarningOnly = isHistoryRegen;
                dialogVm.DisableAutoDefaults = isHistoryRegen;
                if (isHistoryRegen)
                {
                    dialogVm.ModeBannerText = "Iterative: using original image params; defaults are disabled.";
                    dialogVm.ShowModeBanner = true;
                }

                configureVm?.Invoke(dialogVm);

                var (ok, parametersList) = await ShowImageGenerationDialogAsync(dialogVm, owner);
                if (!ok || parametersList == null || parametersList.Count == 0)
                {
                    StatusText = "Image generation cancelled.";
                    return;
                }

                var workflow = entry.Workflow ?? Workflow;
                Func<List<HistoryImage>, Task> onSaveCompleted = async images =>
                {
                    AppendImagesToEntry(entry.Id, images, image);
                    StatusText = "Selected images saved to history entry.";
                    await Task.CompletedTask;
                };

                if (!string.IsNullOrWhiteSpace(graphJson) &&
                    graphParams != null &&
                    parametersList.Count == 1 &&
                    AreParamsEquivalent(parametersList[0], graphParams))
                {
                    var graphObj = JsonNode.Parse(graphJson) as JsonObject;
                    if (graphObj == null)
                    {
                        await RunGenerationPreviewAsync(
                            parametersList,
                            prompt,
                            promptType,
                            workflow,
                            owner,
                            "Generating images...",
                            allowLongPrompts: baseParams != null,
                            job,
                            token,
                            waitForSaveSelection: false,
                            onSaveCompleted: onSaveCompleted);
                    }
                    else
                    {
                        await RunGraphReplayPreviewAsync(
                            graphObj,
                            parametersList[0],
                            prompt,
                            promptType,
                            workflow,
                            owner,
                            "Replaying exact graph...",
                            job,
                            token,
                            waitForSaveSelection: false,
                            onSaveCompleted: onSaveCompleted);
                    }
                }
                else
                {
                    await RunGenerationPreviewAsync(
                        parametersList,
                        prompt,
                        promptType,
                        workflow,
                        owner,
                        "Generating images...",
                        allowLongPrompts: baseParams != null,
                        job,
                        token,
                        waitForSaveSelection: false,
                        onSaveCompleted: onSaveCompleted);
                }
            }
            catch (Exception ex)
            {
                StatusText = $"Image generation failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        });
    }

    private async Task EnhanceFromHistoryAsync(HistoryEntry entry, Window? owner)
    {
        var prompt = entry.EnhancedPrompt ?? entry.ProcessedPrompt ?? entry.OriginalPrompt;
        if (string.IsNullOrWhiteSpace(prompt))
        {
            StatusText = "No prompt available to enhance.";
            return;
        }

        var model = !string.IsNullOrWhiteSpace(entry.OllamaModel) ? entry.OllamaModel : SelectedModel;
        if (string.IsNullOrWhiteSpace(model))
        {
            StatusText = "Select an Ollama model to enhance prompts.";
            return;
        }

        var enhancementPrompt = await _systemPromptService.LoadEnhancementPromptAsync(_settingsService.Settings.EnhancementSystemPrompt);
        var selectedVariations = VariationOptions.Any()
            ? VariationOptions.Where(v => v.IsSelected).Select(v => v.Definition).ToList()
            : (await _systemPromptService.LoadVariationPromptsAsync()).ToList();

        _modelUsageTracker.Register(model);
        var vm = new EnhancementResultViewModel(_ollamaClient, model, prompt, enhancementPrompt, selectedVariations, Models);
        vm.RequestReleaseModel += m => { _ = ReleaseModelAsync(m); };
        var resolvedOwner = GetOwnerWindow(owner) ?? new Window();
        vm.GenerateSampleRequested = samplePrompt => GenerateSampleFromEnhancementAsync(samplePrompt, entry, resolvedOwner);
        var win = new Views.EnhancementResultWindow(vm);
        var result = await win.ShowDialog<EnhancementResult?>(resolvedOwner);
        if (result != null)
        {
            entry.EnhancedPrompt = result.EnhancedPrompt;
            entry.VariationPrompts = result.Variations;
            entry.OllamaModel = model;
            _historyManager.UpdateEntry(entry);
            StatusText = "Enhanced prompt saved to history.";

            if (result.Variations?.Count > 0 && entry.ImageParameters != null)
            {
                await GenerateVariationImagesForEntryAsync(entry, result.Variations, entry.ImageParameters, owner);
            }
        }
        await UnloadModelsAsync();
    }

    private async Task GenerateSampleFromEnhancementAsync(string prompt, HistoryEntry? entry, Window owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        await EnqueueGenerationJobAsync("Enhancement Sample", async (job, token) =>
        {
            _generationInProgress = true;
            try
            {
                var dialogVm = new ImageGenerationOptionsViewModel(_invokeAIClient, _settingsService, _notifications)
                {
                    Prompt = prompt,
                    NegativePrompt = _settingsService.Settings.DefaultNegativePrompt
                };

                var (ok, parametersList) = await ShowImageGenerationDialogAsync(dialogVm, owner);
                if (!ok || parametersList == null || parametersList.Count == 0)
                {
                    StatusText = "Sample generation cancelled.";
                    return;
                }

                var workflow = entry?.Workflow ?? Workflow;
                await RunGenerationPreviewAsync(
                    parametersList,
                    prompt,
                    "Enhanced Sample",
                    workflow,
                    owner,
                    "Generating sample images...",
                    allowLongPrompts: true,
                    job,
                    token,
                    waitForSaveSelection: false,
                    onSaveCompleted: async images =>
                    {
                        if (entry != null)
                        {
                            AppendImagesToEntry(entry.Id, images);
                        }
                        else
                        {
                            var newEntry = BuildHistoryEntryForGeneration(
                                prompt,
                                prompt,
                                SelectedTemplate?.Name,
                                SelectedModel ?? "",
                                SelectedModel,
                                workflow,
                                images);
                            _historyManager.AddEntry(newEntry);
                        }
                        StatusText = "Sample images saved to history.";
                        await Task.CompletedTask;
                    });
            }
            catch (Exception ex)
            {
                StatusText = $"Sample generation failed: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        });
    }

    private async Task<FillMissingResult> FillMissingVariationsWithDialogAsync(HistoryEntry entry, IReadOnlyList<string> missingKeys, Window? owner)
    {
        try
        {
            // Prefer the generated/processed prompt; fall back to enhanced or original template only if needed.
            var basePrompt = new[] { entry.ProcessedPrompt, entry.EnhancedPrompt, entry.OriginalPrompt }
                .FirstOrDefault(p => !string.IsNullOrWhiteSpace(p));
            if (string.IsNullOrWhiteSpace(basePrompt))
            {
                const string message = "No prompt available to generate missing enhancements.";
                StatusText = message;
                return FillMissingResult.PreconditionFailed(message);
            }

            var modelResult = await TryLoadOllamaModelsAsync();
            var availableModels = modelResult.Models ?? Array.Empty<string>();
            if (availableModels.Count == 0)
            {
                var message = string.IsNullOrWhiteSpace(modelResult.Error)
                    ? "Ollama not reachable; cannot generate enhancements."
                    : $"Ollama not reachable; cannot generate enhancements. {modelResult.Error}";
                StatusText = message;
                return FillMissingResult.PreconditionFailed(message);
            }

            var allVariations = await _systemPromptService.LoadVariationPromptsAsync();
            var missingSet = missingKeys != null && missingKeys.Count > 0
                ? new HashSet<string>(missingKeys, StringComparer.OrdinalIgnoreCase)
                : ComputeMissingVariationKeys(entry, allVariations);

            if (missingSet.Count == 0)
            {
                const string message = "No missing enhancements to generate.";
                StatusText = message;
                return FillMissingResult.NoChanges(message);
            }

            var filtered = allVariations.Where(v => missingSet.Contains(v.Key)).ToList();
            if (filtered.Count == 0)
            {
                const string message = "No enhancement definitions matched the missing keys.";
                StatusText = message;
                return FillMissingResult.PreconditionFailed(message);
            }

            var enhancementPrompt = await _systemPromptService.LoadEnhancementPromptAsync(_settingsService.Settings.EnhancementSystemPrompt);
            var model = entry.OllamaModel;
            if (string.IsNullOrWhiteSpace(model) ||
                !availableModels.Contains(model, StringComparer.OrdinalIgnoreCase))
            {
                model = SelectedModel;
            }
            if (string.IsNullOrWhiteSpace(model) ||
                !availableModels.Contains(model, StringComparer.OrdinalIgnoreCase))
            {
                model = availableModels.FirstOrDefault() ?? "";
            }

            _modelUsageTracker.Register(model);

            var vm = new EnhancementResultViewModel(_ollamaClient, model, basePrompt, enhancementPrompt, filtered, availableModels);
            vm.RequestReleaseModel += m => { _ = ReleaseModelAsync(m); };
            var win = new Views.EnhancementResultWindow(vm);
            var resolvedOwner = GetOwnerWindow(owner) ?? new Window();
            var result = await win.ShowDialog<EnhancementResult?>(resolvedOwner);

            if (result != null)
            {
                var updated = false;
                if (!string.IsNullOrWhiteSpace(result.EnhancedPrompt) &&
                    !string.Equals(result.EnhancedPrompt, entry.EnhancedPrompt, StringComparison.Ordinal))
                {
                    entry.EnhancedPrompt = result.EnhancedPrompt;
                    updated = true;
                }
                if (!string.IsNullOrWhiteSpace(vm.SelectedModel) &&
                    !string.Equals(vm.SelectedModel, entry.OllamaModel, StringComparison.Ordinal))
                {
                    entry.OllamaModel = vm.SelectedModel;
                    updated = true;
                }
                entry.VariationPrompts ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                foreach (var kvp in result.Variations)
                {
                    if (string.IsNullOrWhiteSpace(kvp.Key) || string.IsNullOrWhiteSpace(kvp.Value))
                    {
                        continue;
                    }
                    entry.VariationPrompts[kvp.Key] = kvp.Value;
                    updated = true;
                }
                if (updated)
                {
                    _historyManager.UpdateEntry(entry);
                    StatusText = "Missing enhancements generated.";
                    return FillMissingResult.Updated(StatusText);
                }
                else
                {
                    StatusText = "No new enhancements generated.";
                    return FillMissingResult.NoChanges(StatusText);
                }
            }
            StatusText = "Missing enhancements canceled.";
            return FillMissingResult.Canceled(StatusText);
        }
        catch (Exception ex)
        {
            var message = $"Generate missing enhancements failed: {ex.Message}";
            StatusText = message;
            if (_settingsService.Settings.Verbose) Console.WriteLine($"FillMissingVariationsWithDialogAsync failed: {ex}");
            return FillMissingResult.PreconditionFailed(message);
        }
    }

    private HashSet<string> ComputeMissingVariationKeys(HistoryEntry entry, IReadOnlyList<VariationPrompt> definitions)
    {
        var missing = new HashSet<string>(definitions.Select(d => d.Key), StringComparer.OrdinalIgnoreCase);

        if (entry.VariationPrompts != null)
        {
            foreach (var k in entry.VariationPrompts.Keys)
            {
                missing.Remove(k);
            }
        }

        foreach (var img in entry.Images)
        {
            var pt = img.PromptType ?? string.Empty;
            if (pt.StartsWith("Variation:", StringComparison.OrdinalIgnoreCase))
            {
                var name = pt.Split(':', 2).ElementAtOrDefault(1)?.Trim();
                if (!string.IsNullOrWhiteSpace(name))
                {
                    missing.Remove(name);
                }
            }
        }

        return missing;
    }

    private async Task GenerateVariationImagesForEntryAsync(HistoryEntry entry, Dictionary<string, string> variations, InvokeAIGenerationParams baseParams, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }
        await EnqueueGenerationJobAsync(
            "Generate Variations",
            async (job, token) =>
        {
            _generationInProgress = true;
            try
            {
                var paramList = new List<(InvokeAIGenerationParams param, string key)>();
                int offset = 0;
                var baseSeed = baseParams.BaseSeed != 0 ? baseParams.BaseSeed : baseParams.Seed;

                foreach (var kvp in variations)
                {
                    var clone = CloneParams(baseParams);
                    clone.Prompt = kvp.Value;
                    clone.Seed = baseSeed + offset;
                    clone.BaseSeed = baseSeed;
                    paramList.Add((clone, kvp.Key));
                    offset++;
                }

                var previewVm = new MultiImagePreviewViewModel();
                previewVm.InitializePlaceholders(paramList.Count);
                previewVm.StatusText = "Generating variation images...";
                previewVm.OnSaveSlot = slot =>
                {
                    var index = previewVm.Slots.IndexOf(slot);
                    if (index < 0 || index >= paramList.Count) return Task.CompletedTask;
                    var (p, key) = paramList[index];
                    var image = CreateHistoryImageFromSlot(
                        slot,
                        p,
                        $"Variation:{key}",
                        p?.Prompt ?? string.Empty,
                        entry.Workflow ?? string.Empty);
                    image.GenerationParamsJson = p != null ? JsonSerializer.Serialize(p) : null;
                    _historyManager.AppendImages(entry.Id, new[] { image });
                    return Task.CompletedTask;
                };
                ConfigurePreviewCommands(previewVm);

                var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);
                if (token.CanBeCanceled)
                {
                    token.Register(() => cts.Cancel());
                }
                job.StatusMessage = "Generating variation images...";
                job.UpdateProgress(0, paramList.Count);
                job.CancelAction = () => cts.Cancel();
                previewVm.OnEditAndRegenerate = async slot => await EditAndRegenerateSlotAsync(slot, preview);
                await GenerateImagesAsync(paramList.Select(p => p.param).ToList(), previewVm, cts, allowLongPrompts: false, job);

                previewVm.StatusText = cts.IsCancellationRequested ? StatusGenerationCancelled : StatusImagesReadySaveDiscard;
                var saveResult = await saveTask;
                StatusText = saveResult == true ? "Variation images saved to history entry." :
                             cts.IsCancellationRequested ? StatusGenerationCancelled : StatusImagesDiscarded;
            }
            catch (Exception ex)
            {
                StatusText = $"Failed to generate variation images: {ex.Message}";
            }
            finally
            {
                _generationInProgress = false;
            }
        },
            baseParams.Model?.Name,
            Math.Max(1, variations.Count));
    }

    private async Task UpscaleImageFromHistoryAsync(HistoryEntry entry, HistoryImage image, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(image.ImagePath))
        {
            StatusText = "Upscale failed: image path missing.";
            return;
        }

        var historyDir = _historyManager.GetHistoryDir();
        var fullPath = Path.IsPathRooted(image.ImagePath)
            ? image.ImagePath
            : Path.Combine(historyDir, image.ImagePath);

        if (!File.Exists(fullPath))
        {
            StatusText = "Upscale failed: image file not found.";
            return;
        }

        var models = (await _invokeAIClient.GetModelsAsync(modelType: "spandrel_image_to_image")).ToList();
        var optionsVm = new UpscaleImageOptionsViewModel();
        optionsVm.SetModels(models);

        if (!optionsVm.HasModels)
        {
            StatusText = "No upscaler models found on InvokeAI.";
            return;
        }

        var optionsWin = new Views.UpscaleImageOptionsWindow(optionsVm);
        var ok = await optionsWin.ShowDialog<bool?>(GetOwnerWindow(owner) ?? new Window());
        var selectedModels = optionsVm.GetSelectedModels();
        var selectedScales = optionsVm.GetSelectedScales();
        if (ok != true || selectedModels.Count == 0 || selectedScales.Count == 0)
        {
            StatusText = "Upscale cancelled.";
            return;
        }

        var jobs = selectedModels
            .SelectMany(m => selectedScales.Select(s => (model: m, scale: s)))
            .ToList();

        var previewVm = new MultiImagePreviewViewModel();
        previewVm.InitializePlaceholders(jobs.Count);
        previewVm.StatusText = "Upscaling...";
        previewVm.ShowGenerationActions = false;

        for (var i = 0; i < jobs.Count; i++)
        {
            var label = $"{jobs[i].scale:0.#}x · {jobs[i].model.Name}";
            previewVm.Slots[i].Label = label;
        }

        var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);

        previewVm.OnSaveSlot = slot =>
        {
            if (slot.ImageBytes == null) return Task.CompletedTask;
            var slotIndex = previewVm.Slots.IndexOf(slot);
            if (slotIndex < 0 || slotIndex >= jobs.Count) return Task.CompletedTask;
            var job = jobs[slotIndex];
            var prompt = HistoryViewerViewModel.ResolveGeneratedPromptForImage(entry, image);
            var width = slot.Image?.PixelSize.Width ?? 0;
            var height = slot.Image?.PixelSize.Height ?? 0;
            var modelLabel = job.model.Name;

            var payload = new Dictionary<string, object?>
            {
                ["prompt"] = prompt,
                ["width"] = width > 0 ? width : null,
                ["height"] = height > 0 ? height : null,
                ["model"] = new { name = modelLabel, @base = job.model.Base, format = job.model.Format },
                ["upscale_model"] = modelLabel,
                ["scale"] = job.scale,
                ["tile_size"] = optionsVm.SelectedTileSize,
                ["fit_to_multiple_of_8"] = optionsVm.FitToMultipleOf8,
                ["save_to_gallery"] = _settingsService.Settings.DefaultSaveToGallery
            };

            var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
            var promptTypeSuffix = $"Upscale {job.scale:0.#}x";

            var newImage = new HistoryImage
            {
                ImageBytes = slot.ImageBytes,
                PromptType = image.PromptType,
                PromptTypeSuffix = promptTypeSuffix,
                Prompt = prompt,
                GenerationParams = image.GenerationParams ?? HistoryViewerViewModel.GetOrParseGenParams(image),
                GenerationParamsJson = image.GenerationParamsJson,
                Workflow = image.Workflow ?? entry.Workflow,
                IsFavorite = image.IsFavorite,
                UpscaleModel = modelLabel,
                UpscaleScale = job.scale,
                UpscaleTileSize = optionsVm.SelectedTileSize,
                UpscaleFitToMultipleOf8 = optionsVm.FitToMultipleOf8,
                UpscaleSourceImagePath = image.ImagePath,
                DerivedFromImagePath = image.ImagePath
            };
            ApplyJobInfoToHistoryImage(newImage, slot);

            _historyManager.AppendImages(entry.Id, new[] { newImage });
            return Task.CompletedTask;
        };
        try
        {
            var bytes = await File.ReadAllBytesAsync(fullPath, cts.Token);
            var maxParallel = optionsVm.RunInParallel ? 2 : 1;
            var gate = new SemaphoreSlim(maxParallel);
            var tasks = new List<Task>();
            var completed = 0;

            for (var i = 0; i < jobs.Count; i++)
            {
                var index = i;
                tasks.Add(Task.Run(async () =>
                {
                    await gate.WaitAsync(cts.Token);
                    try
                    {
                        var job = jobs[index];
                        var result = await _invokeAIClient.UpscaleImageAsync(
                            bytes,
                            Path.GetFileName(fullPath),
                            job.model,
                            job.scale,
                            optionsVm.SelectedTileSize,
                            optionsVm.FitToMultipleOf8,
                            saveToGallery: _settingsService.Settings.DefaultSaveToGallery,
                            ct: cts.Token);

                        previewVm.SetImage(index, result.ImageBytes);
                        var slot = previewVm.Slots[index];
                        ApplyJobInfoToSlot(slot, result.JobInfo);
                        slot.ModelUsed = job.model.Name;
                        if (slot.Image != null)
                        {
                            slot.Size = $"{slot.Image.PixelSize.Width}x{slot.Image.PixelSize.Height}";
                        }
                    }
                    finally
                    {
                        var done = Interlocked.Increment(ref completed);
                        previewVm.StatusText = $"Upscaling... {done}/{jobs.Count}";
                        gate.Release();
                    }
                }, cts.Token));
            }

            await Task.WhenAll(tasks);
            previewVm.StatusText = "Upscale complete. Save or discard.";
        }
        catch (OperationCanceledException)
        {
            previewVm.StatusText = "Upscale cancelled.";
        }
        catch (Exception ex)
        {
            previewVm.StatusText = $"Upscale failed: {ex.Message}";
        }

        var saveResult = await saveTask;
        if (saveResult == true)
        {
            _historyManager.Reload();
            if (owner is Views.HistoryViewerWindow hv && hv.DataContext is HistoryViewerViewModel hvm)
            {
                hvm.RefreshCommand.Execute(null);
            }
            else if (owner is Views.AllImagesWindow aw && aw.DataContext is AllImagesViewerViewModel avm)
            {
                _ = avm.RefreshAsync();
            }
            StatusText = "Upscale saved to history.";
        }
        else
        {
            StatusText = "Upscale discarded.";
        }
    }

    private (Views.MultiImagePreviewView preview, Task<bool?> resultTask, CancellationTokenSource cts)
        ShowPreviewWindow(MultiImagePreviewViewModel previewVm, Window? owner)
    {
        if (!Dispatcher.UIThread.CheckAccess())
        {
            return Dispatcher.UIThread.InvokeAsync(() => ShowPreviewWindowInternal(previewVm, owner)).GetAwaiter().GetResult();
        }
        return ShowPreviewWindowInternal(previewVm, owner);
    }

    private (Views.MultiImagePreviewView preview, Task<bool?> resultTask, CancellationTokenSource cts)
        ShowPreviewWindowInternal(MultiImagePreviewViewModel previewVm, Window? owner)
    {
        var preview = new Views.MultiImagePreviewView { DataContext = previewVm };
        var tcs = new TaskCompletionSource<bool?>();
        var cts = new CancellationTokenSource();
        previewVm.GenerationToken = cts;
        preview.Closed += (_, __) =>
        {
            cts.Cancel();
            tcs.TrySetResult(previewVm.DialogResult);
        };
        preview.Show(GetOwnerWindow(owner) ?? new Window());
        return (preview, tcs.Task, cts);
    }

    private Task<(bool ok, List<InvokeAIGenerationParams>? parameters)> ShowImageGenerationDialogAsync(
        ImageGenerationOptionsViewModel dialogVm,
        Window? owner)
    {
        if (!Dispatcher.UIThread.CheckAccess())
        {
            return Dispatcher.UIThread.InvokeAsync(() => ShowImageGenerationDialogAsync(dialogVm, owner));
        }

        var dialog = new Views.ImageGenerationDialog(dialogVm);
        dialog.Topmost = true;
        dialog.Opened += (_, __) => dialog.Activate();
        var tcs = new TaskCompletionSource<(bool, List<InvokeAIGenerationParams>?)>();
        dialog.Closed += (_, __) => tcs.TrySetResult(dialogVm.Result);
        dialog.Show(GetOwnerWindow(owner) ?? new Window());
        return tcs.Task;
    }

    private HistoryEntry BuildHistoryEntryForGeneration(
        string originalPrompt,
        string processedPrompt,
        string? templateName,
        string ollamaModel,
        string? invokeModelFallback,
        string workflow,
        List<HistoryImage> images)
    {
        var firstParams = images.FirstOrDefault()?.GenerationParams;
        return new HistoryEntry
        {
            OriginalPrompt = originalPrompt,
            ProcessedPrompt = processedPrompt,
            TemplateName = templateName,
            OllamaModel = ollamaModel,
            InvokeAIModel = firstParams?.Model?.Name ?? invokeModelFallback,
            ImageParameters = firstParams,
            Images = images,
            Workflow = workflow
        };
    }

    private void AppendImagesToEntry(string entryId, List<HistoryImage> images)
    {
        _historyManager.AppendImages(entryId, images);
        RefreshOpenHistoryViews();
    }

    private void AppendImagesToEntry(string entryId, List<HistoryImage> images, HistoryImage? sourceImage)
    {
        if (sourceImage != null && !string.IsNullOrWhiteSpace(sourceImage.ImagePath))
        {
            foreach (var image in images)
            {
                image.DerivedFromImagePath ??= sourceImage.ImagePath;
            }
        }

        _historyManager.AppendImages(entryId, images);
        RefreshOpenHistoryViews();
    }

    private void RefreshOpenHistoryViews()
    {
        void RefreshCore()
        {
            if (Application.Current?.ApplicationLifetime is not IClassicDesktopStyleApplicationLifetime desktop)
            {
                return;
            }

            foreach (var window in desktop.Windows)
            {
                switch (window)
                {
                    case Views.HistoryViewerWindow { DataContext: HistoryViewerViewModel historyVm }:
                        historyVm.RefreshCommand.Execute(null);
                        break;
                    case Views.AllImagesWindow { DataContext: AllImagesViewerViewModel allImagesVm }:
                        _ = allImagesVm.RefreshAsync();
                        break;
                    case Views.AnalyticsStudioWindow { DataContext: AnalyticsStudioViewModel analyticsVm }:
                        analyticsVm.RefreshCommand.Execute(null);
                        break;
                }
            }
        }

        if (Dispatcher.UIThread.CheckAccess())
        {
            RefreshCore();
        }
        else
        {
            Dispatcher.UIThread.Post(RefreshCore);
        }
    }

    private sealed record GenerationPreviewResult(bool? Saved, List<HistoryImage> Images);
    private sealed record ExperimentPreviewJob(InvokeAIGenerationParams Parameters, string Label);
    private sealed record ExperimentBatchDefinition(IReadOnlyList<ExperimentPreviewJob> Jobs, string? HeaderContextText);

    private static string BuildExperimentVariableLabel(ExperimentRunRequest request)
    {
        return request.Mode switch
        {
            ExperimentRunnerViewModel.WildcardChoiceSweepMode when !string.IsNullOrWhiteSpace(request.WildcardName) => $"__{request.WildcardName}__",
            ExperimentRunnerViewModel.SeedSweepMode => "Seed",
            _ => "Template Roll"
        };
    }

    private static string BuildExperimentNotes(ExperimentRunRequest request)
    {
        return request.Mode switch
        {
            ExperimentRunnerViewModel.WildcardChoiceSweepMode => "Locked wildcard values were fixed before the sweep; only the selected wildcard changed per image.",
            ExperimentRunnerViewModel.SeedSweepMode => "One resolved prompt was reused; only the seed changed per image.",
            _ => "The current template was re-resolved for each roll using one fixed image setup."
        };
    }

    private static string BuildExperimentVariantValue(ExperimentRunRequest request, ImageSlotViewModel slot, InvokeAIGenerationParams? parameters)
    {
        return request.Mode switch
        {
            ExperimentRunnerViewModel.SeedSweepMode when parameters != null => parameters.Seed.ToString(CultureInfo.InvariantCulture),
            ExperimentRunnerViewModel.WildcardChoiceSweepMode => slot.Label,
            _ => slot.Label
        };
    }

    private HistoryEntry BuildExperimentHistoryEntry(
        ExperimentRunRequest request,
        string originalPrompt,
        string processedPrompt,
        string? templateName,
        string ollamaModel,
        string? invokeModelFallback,
        List<HistoryImage> images,
        string? headerPrompt)
    {
        var entry = BuildHistoryEntryForGeneration(
            originalPrompt,
            processedPrompt,
            templateName,
            ollamaModel,
            invokeModelFallback,
            Workflow,
            images);

        entry.IsExperimentRun = true;
        entry.ExperimentType = request.Mode;
        entry.ExperimentVariable = BuildExperimentVariableLabel(request);
        entry.ExperimentHeaderPrompt = headerPrompt;
        entry.ExperimentLockedChoices = request.LockedChoices.Count == 0
            ? null
            : new Dictionary<string, string>(request.LockedChoices, StringComparer.OrdinalIgnoreCase);
        entry.ExperimentPlannedCount = request.RunCount;
        entry.ExperimentNotes = BuildExperimentNotes(request);
        entry.Status = "experiment";
        entry.ProcessedPrompt = request.Mode switch
        {
            ExperimentRunnerViewModel.NTemplateRollsMode => string.Empty,
            _ when !string.IsNullOrWhiteSpace(headerPrompt) => headerPrompt!,
            _ => processedPrompt
        };
        return entry;
    }

    private ExperimentBatchDefinition BuildExperimentJobs(
        ExperimentRunRequest request,
        InvokeAIGenerationParams baseParams,
        string promptText,
        string? outputText,
        TemplateGenerationResult? generationSnapshot)
    {
        return request.Mode switch
        {
            ExperimentRunnerViewModel.WildcardChoiceSweepMode => BuildWildcardSweepExperimentJobs(baseParams, promptText, request.WildcardName, request.SelectedChoices, request.LockedChoices, generationSnapshot),
            ExperimentRunnerViewModel.SeedSweepMode => BuildSeedSweepExperimentJobs(baseParams, promptText, outputText, request.RunCount, generationSnapshot),
            _ => BuildTemplateRollExperimentJobs(baseParams, promptText, outputText, request.RunCount)
        };
    }

    private ExperimentBatchDefinition BuildTemplateRollExperimentJobs(
        InvokeAIGenerationParams baseParams,
        string promptText,
        string? outputText,
        int runCount)
    {
        var jobs = new List<ExperimentPreviewJob>();
        for (var i = 0; i < runCount; i++)
        {
            var result = _promptProcessorService.ProcessPrompt(promptText);
            var prompt = BuildResolvedPromptText(result);
            if (string.IsNullOrWhiteSpace(prompt))
            {
                prompt = ResolvePromptForMain(outputText, promptText);
            }

            var clone = CloneParams(baseParams);
            clone.Prompt = prompt;
            jobs.Add(new ExperimentPreviewJob(clone, $"Roll {i + 1}"));
        }

        return new ExperimentBatchDefinition(jobs, null);
    }

    private ExperimentBatchDefinition BuildWildcardSweepExperimentJobs(
        InvokeAIGenerationParams baseParams,
        string promptText,
        string? wildcardName,
        IReadOnlyList<string> selectedChoices,
        IReadOnlyDictionary<string, string> lockedChoices,
        TemplateGenerationResult? generationSnapshot)
    {
        var jobs = new List<ExperimentPreviewJob>();
        if (string.IsNullOrWhiteSpace(wildcardName) || selectedChoices.Count == 0)
        {
            return new ExperimentBatchDefinition(jobs, null);
        }

        var lockedContext = BuildExperimentContext(lockedChoices);
        var headerText = BuildResolvedPromptText(BuildWildcardSweepBaselineResult(promptText, wildcardName, lockedChoices));

        foreach (var choice in selectedChoices)
        {
            var context = new Dictionary<string, ContextValue>(lockedContext, StringComparer.OrdinalIgnoreCase)
            {
                [wildcardName] = BuildContextValue(wildcardName, choice)
            };

            var result = _promptProcessorService.ProcessPrompt(promptText, existingContext: context);
            var clone = CloneParams(baseParams);
            clone.Prompt = BuildResolvedPromptText(result);
            jobs.Add(new ExperimentPreviewJob(clone, choice));
        }

        return new ExperimentBatchDefinition(jobs, headerText);
    }

    private TemplateGenerationResult BuildWildcardSweepBaselineResult(
        string promptText,
        string? wildcardName,
        IReadOnlyDictionary<string, string> lockedChoices)
    {
        if (string.IsNullOrWhiteSpace(promptText) || string.IsNullOrWhiteSpace(wildcardName))
        {
            return new TemplateGenerationResult(new List<PromptSegment>(), new HashSet<string>(), 0, new Dictionary<string, ContextValue>(StringComparer.OrdinalIgnoreCase));
        }

        var headerContext = BuildExperimentContext(lockedChoices);
        headerContext[wildcardName] = new ContextValue($"__{wildcardName}__", new List<string>());
        return _promptProcessorService.ProcessPrompt(promptText, existingContext: headerContext);
    }

    private ExperimentBatchDefinition BuildSeedSweepExperimentJobs(
        InvokeAIGenerationParams baseParams,
        string promptText,
        string? outputText,
        int runCount,
        TemplateGenerationResult? generationSnapshot)
    {
        var jobs = new List<ExperimentPreviewJob>();
        var resolvedPrompt = !string.IsNullOrWhiteSpace(outputText)
            ? outputText
            : BuildResolvedPromptText(generationSnapshot ?? _promptProcessorService.ProcessPrompt(promptText));
        var rootSeed = baseParams.Seed;

        for (var i = 0; i < runCount; i++)
        {
            var clone = CloneParams(baseParams);
            clone.Prompt = resolvedPrompt;
            clone.Seed = rootSeed + i;
            clone.BaseSeed = rootSeed;
            jobs.Add(new ExperimentPreviewJob(clone, $"Seed {clone.Seed}"));
        }

        return new ExperimentBatchDefinition(jobs, resolvedPrompt);
    }

    private async Task RunExperimentPreviewAsync(
        ExperimentBatchDefinition experiment,
        ExperimentRunRequest request,
        Window? owner,
        string statusText,
        bool allowLongPrompts,
        GenerationJob? job = null,
        CancellationToken externalToken = default,
        string? originalPrompt = null,
        string? processedPrompt = null,
        string? templateName = null,
        string? ollamaModel = null)
    {
        var savedImages = new List<HistoryImage>();
        var previewVm = new MultiImagePreviewViewModel();
        previewVm.InitializePlaceholders(experiment.Jobs.Count);
        previewVm.StatusText = statusText;
        previewVm.HeaderContextText = experiment.HeaderContextText ?? string.Empty;

        for (var i = 0; i < experiment.Jobs.Count && i < previewVm.Slots.Count; i++)
        {
            previewVm.Slots[i].Label = experiment.Jobs[i].Label;
        }

        if (request.SaveSelectionsToHistory)
        {
            previewVm.OnSaveSlot = slot =>
            {
                var slotIndex = previewVm.Slots.IndexOf(slot);
                var parameters = slot.GenerationParams;
                var imagePrompt = parameters?.Prompt ?? string.Empty;
                var image = CreateHistoryImageFromSlot(
                    slot,
                    parameters,
                    $"Experiment:{request.Mode}",
                    imagePrompt,
                    Workflow);
                image.GenerationParamsJson = parameters != null ? JsonSerializer.Serialize(parameters) : null;
                image.ExperimentVariantIndex = slotIndex >= 0 ? slotIndex : null;
                image.ExperimentVariantLabel = slot.Label;
                image.ExperimentVariantValue = BuildExperimentVariantValue(request, slot, parameters);
                image.PromptTypeSuffix = slot.Label;
                savedImages.Add(image);
                return Task.CompletedTask;
            };
            previewVm.OnSaveCompleted = () =>
            {
                if (savedImages.Count > 0)
                {
                    var entry = BuildExperimentHistoryEntry(
                        request,
                        originalPrompt ?? string.Empty,
                        processedPrompt ?? string.Empty,
                        templateName,
                        ollamaModel ?? string.Empty,
                        savedImages[0].GenerationParams?.Model?.Name,
                        savedImages,
                        experiment.HeaderContextText);
                    _historyManager.AddEntry(entry);
                    StatusText = "Experiment images saved to history.";
                }
                return Task.CompletedTask;
            };
        }
        else
        {
            previewVm.OnSaveSlot = _ => Task.CompletedTask;
            previewVm.OnSaveCompleted = () =>
            {
                StatusText = "Experiment preview closed without saving to history.";
                return Task.CompletedTask;
            };
        }

        ConfigurePreviewCommands(previewVm);
        var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);
        _ = saveTask;
        if (externalToken.CanBeCanceled)
        {
            externalToken.Register(() => cts.Cancel());
        }
        if (job != null)
        {
            job.StatusMessage = statusText;
            job.UpdateProgress(0, experiment.Jobs.Count);
            job.CancelAction = () => cts.Cancel();
        }

        _activeGenerationCts = cts;
        previewVm.OnEditAndRegenerate = async slot => await EditAndRegenerateSlotAsync(slot, preview);
        StatusText = statusText;

        try
        {
            var jobs = experiment.Jobs
                .Zip(previewVm.Slots, (experimentJob, slot) => (experimentJob.Parameters, slot))
                .ToList();
            await GenerateImagesForSlotsAsync(jobs, previewVm, cts, allowLongPrompts, job);
        }
        finally
        {
            if (ReferenceEquals(_activeGenerationCts, cts))
            {
                _activeGenerationCts = null;
            }
        }

        if (cts.IsCancellationRequested)
        {
            previewVm.StatusText = StatusGenerationCancelled;
            StatusText = StatusGenerationCancelled;
            return;
        }

        previewVm.StatusText = request.SaveSelectionsToHistory
            ? StatusImagesReady
            : "Experiment ready. Save closes the preview without writing history.";
        StatusText = request.SaveSelectionsToHistory
            ? StatusImagesReadyMain
            : "Experiment ready. Review the results and close when done.";
    }

    private async Task<GenerationPreviewResult> RunGenerationPreviewAsync(
        IReadOnlyList<InvokeAIGenerationParams> parametersList,
        string prompt,
        string promptType,
        string workflow,
        Window? owner,
        string statusText,
        bool allowLongPrompts,
        GenerationJob? job = null,
        CancellationToken externalToken = default,
        bool waitForSaveSelection = true,
        Func<List<HistoryImage>, Task>? onSaveCompleted = null)
    {
        var savedImages = new List<HistoryImage>();
        var previewVm = new MultiImagePreviewViewModel();
        previewVm.InitializePlaceholders(parametersList.Count);
        previewVm.StatusText = statusText;
        previewVm.OnSaveSlot = slot =>
        {
            var image = CreateHistoryImageFromSlot(
                slot,
                slot.GenerationParams,
                promptType,
                prompt,
                workflow);
            image.GenerationParamsJson = slot.GenerationParams != null ? JsonSerializer.Serialize(slot.GenerationParams) : null;
            savedImages.Add(image);
            return Task.CompletedTask;
        };
        previewVm.OnSaveCompleted = onSaveCompleted == null
            ? null
            : async () => await onSaveCompleted(savedImages);
        ConfigurePreviewCommands(previewVm);
        var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);
        if (externalToken.CanBeCanceled)
        {
            externalToken.Register(() => cts.Cancel());
        }
        if (job != null)
        {
            job.StatusMessage = statusText;
            job.UpdateProgress(0, parametersList.Count);
            job.CancelAction = () => cts.Cancel();
        }
        _activeGenerationCts = cts;
        previewVm.OnEditAndRegenerate = async slot => await EditAndRegenerateSlotAsync(slot, preview);
        StatusText = statusText;

        try
        {
            await GenerateImagesAsync(parametersList, previewVm, cts, allowLongPrompts, job);
        }
        finally
        {
            if (ReferenceEquals(_activeGenerationCts, cts))
            {
                _activeGenerationCts = null;
            }
        }
        if (cts.IsCancellationRequested)
        {
            previewVm.StatusText = StatusGenerationCancelled;
            return new GenerationPreviewResult(null, savedImages);
        }

        previewVm.StatusText = StatusImagesReady;
        StatusText = StatusImagesReadyMain;

        if (!waitForSaveSelection)
        {
            _ = saveTask;
            return new GenerationPreviewResult(null, savedImages);
        }

        var saveResult = await saveTask;
        return new GenerationPreviewResult(saveResult, savedImages);
    }

    private async Task<GenerationPreviewResult> RunSeedVariationPreviewAsync(
        IReadOnlyList<InvokeAIGenerationParams> parametersList,
        string prompt,
        string promptType,
        string workflow,
        Window? owner,
        string statusText,
        bool allowLongPrompts,
        int rootSeed,
        byte[] rootImageBytes,
        GenerationJob? job = null,
        CancellationToken externalToken = default,
        bool waitForSaveSelection = true,
        Func<List<HistoryImage>, Task>? onSaveCompleted = null)
    {
        var savedImages = new List<HistoryImage>();
        var previewVm = new MultiImagePreviewViewModel();
        previewVm.InitializePlaceholders(parametersList.Count);
        previewVm.StatusText = statusText;
        previewVm.OnSaveSlot = slot =>
        {
            var image = CreateHistoryImageFromSlot(
                slot,
                slot.GenerationParams,
                promptType,
                prompt,
                workflow);
            image.GenerationParamsJson = slot.GenerationParams != null ? JsonSerializer.Serialize(slot.GenerationParams) : null;
            savedImages.Add(image);
            return Task.CompletedTask;
        };
        previewVm.OnSaveCompleted = onSaveCompleted == null
            ? null
            : async () => await onSaveCompleted(savedImages);
        ConfigurePreviewCommands(previewVm);
        var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);
        if (externalToken.CanBeCanceled)
        {
            externalToken.Register(() => cts.Cancel());
        }
        if (job != null)
        {
            job.StatusMessage = statusText;
            job.UpdateProgress(0, parametersList.Count);
            job.CancelAction = () => cts.Cancel();
        }
        _activeGenerationCts = cts;
        previewVm.OnEditAndRegenerate = async slot => await EditAndRegenerateSlotAsync(slot, preview);
        StatusText = statusText;

        try
        {
            var jobs = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
            for (int i = 0; i < parametersList.Count && i < previewVm.Slots.Count; i++)
            {
                var param = parametersList[i];
                var slot = previewVm.Slots[i];
                ApplySlotGenerationMetadata(slot, param);

                if (param.Seed == rootSeed)
                {
                    slot.IsSelected = false;
                    previewVm.SetImage(i, rootImageBytes);
                }
                else
                {
                    slot.IsLoading = true;
                    jobs.Add((param, slot));
                }
            }
            previewVm.SyncProgressFromSlots();

            if (jobs.Count > 0)
            {
                await GenerateImagesForSlotsAsync(jobs, previewVm, cts, allowLongPrompts, job);
            }
        }
        finally
        {
            if (ReferenceEquals(_activeGenerationCts, cts))
            {
                _activeGenerationCts = null;
            }
        }

        if (cts.IsCancellationRequested)
        {
            previewVm.StatusText = StatusGenerationCancelled;
            return new GenerationPreviewResult(null, savedImages);
        }

        previewVm.StatusText = StatusImagesReady;
        StatusText = StatusImagesReadyMain;

        if (!waitForSaveSelection)
        {
            _ = saveTask;
            return new GenerationPreviewResult(null, savedImages);
        }

        var saveResult = await saveTask;
        return new GenerationPreviewResult(saveResult, savedImages);
    }

    private void ApplyGenerationResultStatus(GenerationPreviewResult result, string savedMessage, string discardedMessage)
    {
        if (result.Saved == true)
        {
            StatusText = savedMessage;
        }
        else if (result.Saved == null)
        {
            StatusText = StatusGenerationCancelled;
        }
        else
        {
            StatusText = discardedMessage;
        }
    }

    private static string? GetDominantModelName(IEnumerable<InvokeAIGenerationParams>? parameters)
    {
        return parameters?
            .Where(param => !string.IsNullOrWhiteSpace(param.Model?.Name))
            .GroupBy(param => param.Model!.Name, StringComparer.OrdinalIgnoreCase)
            .OrderByDescending(group => group.Count())
            .ThenBy(group => group.Key, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.Key)
            .FirstOrDefault();
    }

    private static int GetEstimatedWorkUnits(IEnumerable<InvokeAIGenerationParams>? parameters)
    {
        return Math.Max(1, parameters?.Count() ?? 0);
    }

    private Task EnqueueGenerationJobAsync(string name, Func<GenerationJob, CancellationToken, Task> work, string? preferredModel = null, int estimatedWorkUnits = 1)
    {
        var job = new GenerationJob(name, work, preferredModel, estimatedWorkUnits);
        _generationQueue.Enqueue(job);
        StatusText = $"Queued: {name}";
        _notifications?.ShowInfo($"Queued: {name}", "Generation Queue");
        return Task.CompletedTask;
    }

    private void ApplyGenerationParamsToDialog(
        ImageGenerationOptionsViewModel dialogVm,
        InvokeAIGenerationParams baseParams,
        bool applyModelFromSource,
        int? seedOverride = null)
    {
        dialogVm.Seed = seedOverride ?? baseParams.Seed;
        dialogVm.UseRandomSeed = false;
        dialogVm.CfgScale = baseParams.CfgScale;
        dialogVm.NegativePrompt = baseParams.NegativePrompt ?? dialogVm.NegativePrompt;
        dialogVm.Steps = baseParams.Steps;
        dialogVm.Width = baseParams.Width;
        dialogVm.Height = baseParams.Height;
        dialogVm.CfgRescaleMultiplier = baseParams.CfgRescaleMultiplier;
        dialogVm.SaveToGallery = baseParams.SaveToGallery;
        if (baseParams.Loras?.Any() == true)
        {
            dialogVm.SetInitialLoras(baseParams.Loras);
        }
        if (applyModelFromSource)
        {
            if (baseParams.Model?.Base is { Length: > 0 } baseModel)
            {
                dialogVm.BaseModelType = baseModel;
            }
            if (!string.IsNullOrWhiteSpace(baseParams.Model?.Name))
            {
                dialogVm.SetInitialModel(baseParams.Model.Name);
            }
        }
        var schedVal = baseParams.Scheduler;
        if (!string.IsNullOrWhiteSpace(schedVal))
        {
            Dispatcher.UIThread.Post(() =>
            {
                var match = dialogVm.Schedulers.FirstOrDefault(s => string.Equals(s.Value, schedVal, StringComparison.OrdinalIgnoreCase));
                if (match != null) dialogVm.SelectedSchedulerOption = match;
            });
        }
    }

    private static string ResolvePromptForMain(string? outputText, string? promptText)
    {
        return string.IsNullOrWhiteSpace(outputText) ? promptText ?? string.Empty : outputText;
    }

    private string BuildResolvedPromptText(TemplateGenerationResult result)
    {
        var text = string.Join(" ", result.Segments
            .Select(segment => segment.Text?.Trim() ?? string.Empty)
            .Where(segment => !string.IsNullOrWhiteSpace(segment)));
        return _promptProcessorService.CleanupPrompt(text);
    }

    private static List<string> ExtractWildcardNames(string? promptText)
    {
        if (string.IsNullOrWhiteSpace(promptText))
        {
            return new List<string>();
        }

        return WildcardRegex.Matches(promptText)
            .Select(match => match.Groups["name"].Value.Trim())
            .Where(name => !string.IsNullOrWhiteSpace(name))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private byte[]? TryLoadHistoryImageBytes(HistoryImage? image)
    {
        if (image?.ImageBytes != null && image.ImageBytes.Length > 0)
        {
            return image.ImageBytes;
        }

        if (string.IsNullOrWhiteSpace(image?.ImagePath))
        {
            return null;
        }

        var historyDir = _historyManager.GetHistoryDir();
        var fullPath = Path.IsPathRooted(image.ImagePath)
            ? image.ImagePath
            : Path.Combine(historyDir, image.ImagePath);

        if (!File.Exists(fullPath))
        {
            return null;
        }

        try
        {
            return File.ReadAllBytes(fullPath);
        }
        catch
        {
            return null;
        }
    }

    private static string ResolvePromptForSlot(InvokeAIGenerationParams baseParams, string? fallback)
    {
        return string.IsNullOrWhiteSpace(baseParams.Prompt) ? fallback ?? string.Empty : baseParams.Prompt;
    }

    private enum PromptSource
    {
        Override,
        GeneratedPrompt,
        EnhancedPrompt,
        ProcessedPrompt,
        OriginalPrompt,
        None
    }

    private static (string prompt, PromptSource source) ResolvePromptForHistoryGeneration(
        HistoryEntry entry,
        HistoryImage? image,
        InvokeAIGenerationParams? baseParams,
        string? promptOverride,
        bool includeEnhanced)
    {
        if (!string.IsNullOrWhiteSpace(promptOverride)) return (promptOverride, PromptSource.Override);

        var resolved = HistoryViewerViewModel.ResolveGeneratedPromptForImage(entry, image);
        if (!string.IsNullOrWhiteSpace(resolved)) return (resolved, PromptSource.GeneratedPrompt);

        if (!string.IsNullOrWhiteSpace(image?.Prompt)) return (image!.Prompt!, PromptSource.GeneratedPrompt);
        if (!string.IsNullOrWhiteSpace(baseParams?.Prompt)) return (baseParams!.Prompt, PromptSource.GeneratedPrompt);

        if (includeEnhanced && !string.IsNullOrWhiteSpace(entry.EnhancedPrompt))
        {
            return (entry.EnhancedPrompt!, PromptSource.EnhancedPrompt);
        }

        if (!string.IsNullOrWhiteSpace(entry.ProcessedPrompt)) return (entry.ProcessedPrompt, PromptSource.ProcessedPrompt);
        if (!string.IsNullOrWhiteSpace(entry.OriginalPrompt)) return (entry.OriginalPrompt, PromptSource.OriginalPrompt);
        return (string.Empty, PromptSource.None);
    }

    private void ConfigurePreviewCommands(MultiImagePreviewViewModel previewVm)
    {
        previewVm.OnGenerateSeedVariations = async slot => await GenerateVariationsFromSlotAsync(slot, true, previewVm);
        previewVm.OnGenerateModelVariations = async slot => await GenerateModelPermutationsFromSlotAsync(slot, previewVm);
        previewVm.OnGenerateLoraVariations = async slot => await GenerateLoraPermutationsFromSlotAsync(slot, previewVm);
        previewVm.OnPromoteToBase = async slot => await PromotePreviewSlotToBaseAsync(slot);
        previewVm.OnEnhanceFromThis = async slot => await EnhancePromptFromPreviewSlotAsync(slot);
    }

    private Task PromotePreviewSlotToBaseAsync(ImageSlotViewModel slot)
    {
        var prompt = slot.GenerationParams?.Prompt;
        if (string.IsNullOrWhiteSpace(prompt))
        {
            StatusText = "This image does not have a prompt to promote.";
            return Task.CompletedTask;
        }

        PromptText = prompt;
        OutputText = prompt;
        _lastGeneration = null;
        ProcessedPromptSegments.Clear();
        MissingWildcards.Clear();
        var segmentVm = new PromptSegmentViewModel(new PromptSegment(prompt), 0)
        {
            Tooltip = "Promoted from image preview."
        };
        segmentVm.PropertyChanged += (_, _) => RefreshProcessedOutput();
        ProcessedPromptSegments.Add(segmentVm);
        RefreshProcessedOutput();
        StatusText = "Promoted image prompt to the base prompt.";
        return Task.CompletedTask;
    }

    private async Task EnhancePromptFromPreviewSlotAsync(ImageSlotViewModel slot)
    {
        var prompt = slot.GenerationParams?.Prompt;
        if (string.IsNullOrWhiteSpace(prompt))
        {
            StatusText = "This image does not have a prompt to enhance.";
            return;
        }

        await EnhancePromptTextAsync(prompt, prompt);
    }

    private async Task<List<List<LoraParameter>>?> ShowLoraPermutationDialogAsync(InvokeAIGenerationParams baseParams, Window? owner)
    {
        if (!Dispatcher.UIThread.CheckAccess())
        {
            return await Dispatcher.UIThread.InvokeAsync(() => ShowLoraPermutationDialogAsync(baseParams, owner));
        }

        var baseModel = baseParams.Model?.Base ?? baseParams.BaseModelType;
        var loras = await _invokeAIClient.GetModelsAsync(baseModel, "lora");
        var dialogVm = new LoraPermutationDialogViewModel(loras, baseParams.Loras);
        var dialog = new Views.LoraPermutationDialog(dialogVm);
        var tcs = new TaskCompletionSource<List<List<LoraParameter>>?>();
        dialogVm.RequestClose += (_, _) => dialog.Close();
        dialog.Closed += (_, _) => tcs.TrySetResult(dialogVm.Result);
        dialog.Show(GetOwnerWindow(owner) ?? new Window());
        return await tcs.Task;
    }

    private static InvokeAIGenerationParams CloneParams(InvokeAIGenerationParams src)
    {
        var model = src.Model;
        if (model != null && string.IsNullOrEmpty(model.Type))
        {
            model = model with { Type = "main" };
        }
        return new InvokeAIGenerationParams
        {
            Prompt = src.Prompt,
            PositiveStylePrompt = src.PositiveStylePrompt,
            NegativeStylePrompt = src.NegativeStylePrompt,
            NegativePrompt = src.NegativePrompt,
            BaseModelType = src.BaseModelType,
            UsedRandomSeed = src.UsedRandomSeed,
            BaseSeed = src.BaseSeed,
            AutoClearedModelCacheBetweenModels = src.AutoClearedModelCacheBetweenModels,
            VaeUsedName = src.VaeUsedName,
            VaePrecision = src.VaePrecision,
            UseCpuNoise = src.UseCpuNoise,
            L2iFp32 = src.L2iFp32,
            UseAutoCfgRescale = src.UseAutoCfgRescale,
            Model = model,
            Steps = src.Steps,
            CfgScale = src.CfgScale,
            Width = src.Width,
            Height = src.Height,
            Seed = src.Seed,
            Scheduler = src.Scheduler,
            CfgRescaleMultiplier = src.CfgRescaleMultiplier,
            Loras = src.Loras?.Select(l => new LoraParameter { Lora = l.Lora, Weight = l.Weight }).ToList() ?? new List<LoraParameter>(),
            SaveToGallery = src.SaveToGallery,
            UsePromptAsStyleWhenEmpty = src.UsePromptAsStyleWhenEmpty
        };
    }

    private async Task GenerateImagesAsync(IReadOnlyList<InvokeAIGenerationParams> parametersList, MultiImagePreviewViewModel previewVm, CancellationTokenSource cts, bool allowLongPrompts, GenerationJob? job = null)
    {
        var slotAssignments = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
        for (int i = 0; i < parametersList.Count && i < previewVm.Slots.Count; i++)
        {
            slotAssignments.Add((parametersList[i], previewVm.Slots[i]));
        }

        await GenerateImagesForSlotsAsync(slotAssignments, previewVm, cts, allowLongPrompts, job);
    }

    private async Task GenerateImagesForSlotsAsync(
        IReadOnlyList<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> jobs,
        MultiImagePreviewViewModel previewVm,
        CancellationTokenSource cts,
        bool allowLongPrompts,
        GenerationJob? job = null)
    {
        var completedAny = false;
        previewVm.StatusText = "Generating images...";
        if (!ValidateGenerationParams(jobs.Select(j => j.param).ToList(), allowLongPrompts, out var invalidMessage, out var isWarning))
        {
            StatusText = invalidMessage;
            previewVm.StatusText = invalidMessage;
            cts.Cancel();
            return;
        }
        if (isWarning)
        {
            StatusText = invalidMessage;
            previewVm.StatusText = invalidMessage;
        }
        foreach (var (param, slot) in jobs)
        {
            ApplySlotGenerationMetadata(slot, param);
            slot.IsLoading = true;
        }
        previewVm.SyncProgressFromSlots();
        job?.UpdateProgress(previewVm.GeneratedCount, previewVm.TotalCount);

        var pendingJobs = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>(jobs);
        string? currentModelKey = null;

        void AttachPendingPreviewJobs()
        {
            var attached = previewVm.TakePendingVariationJobs();
            if (attached.Count == 0)
            {
                return;
            }

            foreach (var (param, slot) in attached)
            {
                ApplySlotGenerationMetadata(slot, param);
                slot.IsLoading = true;
            }

            pendingJobs.AddRange(attached);
            previewVm.SyncProgressFromSlots();
            job?.UpdateProgress(previewVm.GeneratedCount, previewVm.TotalCount);
        }

        static string GetModelKey(InvokeAIGenerationParams param)
            => param.Model?.Name ?? string.Empty;

        static List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> TakeJobsForModel(
            List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> source,
            string modelKey)
        {
            var matches = source
                .Where(item => string.Equals(GetModelKey(item.param), modelKey, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (matches.Count == 0)
            {
                return matches;
            }

            foreach (var match in matches)
            {
                source.Remove(match);
            }

            return matches;
        }

        static List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> TakeLargestModelBatch(
            List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> source,
            out string modelKey)
        {
            var selected = source
                .Select((item, index) => new { item, index })
                .GroupBy(x => GetModelKey(x.item.param), StringComparer.OrdinalIgnoreCase)
                .Select(group => new
                {
                    ModelKey = group.Key,
                    Count = group.Count(),
                    FirstIndex = group.Min(x => x.index)
                })
                .OrderByDescending(group => group.Count)
                .ThenBy(group => group.FirstIndex)
                .First();

            modelKey = selected.ModelKey;
            return TakeJobsForModel(source, modelKey);
        }

        while (!cts.IsCancellationRequested)
        {
            AttachPendingPreviewJobs();
            if (pendingJobs.Count == 0)
            {
                break;
            }

            List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> activeBatch;
            if (!string.IsNullOrWhiteSpace(currentModelKey))
            {
                activeBatch = TakeJobsForModel(pendingJobs, currentModelKey);
            }
            else
            {
                activeBatch = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
            }

            if (activeBatch.Count == 0)
            {
                activeBatch = TakeLargestModelBatch(pendingJobs, out var selectedModelKey);
                currentModelKey = selectedModelKey;
            }

            foreach (var (param, slot) in activeBatch)
            {
                if (cts.IsCancellationRequested) break;
                try
                {
                    if (!ValidateGenerationParams(param, allowLongPrompts, out var invalidParamMessage, out var paramWarning))
                    {
                        StatusText = invalidParamMessage;
                        previewVm.StatusText = invalidParamMessage;
                        cts.Cancel();
                        break;
                    }
                    if (paramWarning)
                    {
                        StatusText = invalidParamMessage;
                        previewVm.StatusText = invalidParamMessage;
                    }
                    await _invokeGenerationGate.WaitAsync(cts.Token);
                    InvokeAIGenerationResult result;
                    try
                    {
                        result = await _invokeAIClient.GenerateImageAsync(param, ct: cts.Token);
                    }
                    finally
                    {
                        _invokeGenerationGate.Release();
                    }

                    RecordKpiGeneration(param, result.JobInfo, Workflow);
                    if (result.GenerationParams?.Vae?.Name is { Length: > 0 } vaeName)
                    {
                        param.VaeUsedName = vaeName;
                    }

                    previewVm.UpdateSlotImage(slot, result.ImageBytes);
                    ApplyJobInfoToSlot(slot, result.JobInfo);
                    previewVm.IncrementGenerated();
                    completedAny = true;
                    job?.UpdateProgress(previewVm.GeneratedCount, previewVm.TotalCount);
                }
                catch (OperationCanceledException)
                {
                    StatusText = "Image generation cancelled.";
                    cts.Cancel();
                    return;
                }
                catch (InvokeAIJobFailedException ex)
                {
                    RecordKpiGeneration(param, ex.JobInfo, Workflow);
                    slot.IsLoading = false;
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Generation failed: {ex.Message}");
                }
                catch (Exception ex)
                {
                    slot.IsLoading = false;
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Generation failed: {ex.Message}");
                }
            }

            if (cts.IsCancellationRequested) break;

            AttachPendingPreviewJobs();
            if (pendingJobs.Any(item => string.Equals(GetModelKey(item.param), currentModelKey ?? string.Empty, StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

            if (_settingsService.Settings.AutoClearInvokeCacheBetweenModels)
            {
                await TryEmptyModelCacheAsync(cts.Token);
            }

            currentModelKey = null;
        }

        if (_settingsService.Settings.ServerSafetyModeEnabled && !cts.IsCancellationRequested)
        {
            await TryEmptyModelCacheAsync(cts.Token);
        }

        if (completedAny && !cts.IsCancellationRequested && ShouldNotifyGenerationCompletion(job))
        {
            previewVm.StatusText = StatusImagesReadySaveDiscard;
            TryPlayGenerationCompleteSound();
        }
    }

    private static HistoryImage CreateHistoryImageFromSlot(
        ImageSlotViewModel slot,
        InvokeAIGenerationParams? parameters,
        string promptType,
        string prompt,
        string workflow)
    {
        var image = new HistoryImage
        {
            ImageBytes = slot.ImageBytes,
            GenerationParams = parameters,
            PromptType = promptType,
            Prompt = prompt,
            Workflow = workflow,
            IsFavorite = slot.IsFavorite
        };
        ApplyJobInfoToHistoryImage(image, slot);
        return image;
    }

    private static void ApplyJobInfoToSlot(ImageSlotViewModel slot, GenerationJobInfo? jobInfo)
    {
        if (jobInfo == null) return;
        slot.GenerationDurationMs = jobInfo.GenerationDurationMs;
        slot.QueueWaitMs = jobInfo.QueueWaitMs;
        slot.TotalDurationMs = jobInfo.TotalDurationMs;
        slot.GenerationStatus = jobInfo.Status;
        slot.ErrorType = jobInfo.ErrorType;
        slot.ErrorMessage = jobInfo.ErrorMessage;
        slot.ErrorTraceback = jobInfo.ErrorTraceback;
    }

    private static void ApplyJobInfoToHistoryImage(HistoryImage image, ImageSlotViewModel slot)
    {
        image.GenerationDurationMs = slot.GenerationDurationMs;
        image.QueueWaitMs = slot.QueueWaitMs;
        image.TotalDurationMs = slot.TotalDurationMs;
        image.GenerationStatus = slot.GenerationStatus;
        image.ErrorType = slot.ErrorType;
        image.ErrorMessage = slot.ErrorMessage;
        image.ErrorTraceback = slot.ErrorTraceback;
    }

    private void RecordKpiGeneration(InvokeAIGenerationParams parameters, GenerationJobInfo? jobInfo, string? workflow)
    {
        _kpiStats?.RecordGeneration(parameters, jobInfo, workflow ?? Workflow);
    }

    private static bool ValidateGenerationParams(
        IReadOnlyList<InvokeAIGenerationParams> parametersList,
        bool allowLongPrompts,
        out string message,
        out bool isWarning)
    {
        message = string.Empty;
        isWarning = false;
        return true;
    }

    private static bool ValidateGenerationParams(
        InvokeAIGenerationParams param,
        bool allowLongPrompts,
        out string message,
        out bool isWarning)
    {
        message = string.Empty;
        isWarning = false;
        return true;
    }

    private static string FormatSeedLabel(InvokeAIGenerationParams p)
    {
        if (p.BaseSeed != 0 && p.Seed != p.BaseSeed)
        {
            return $"{p.Seed} (root {p.BaseSeed})";
        }
        return p.Seed.ToString();
    }

    private static string FormatLoraLabel(InvokeAIGenerationParams? p)
    {
        if (p?.Loras == null || p.Loras.Count == 0) return "";
        var parts = p.Loras
            .Where(l => l?.Lora != null && !string.IsNullOrWhiteSpace(l.Lora.Name))
            .Select(l => $"{l.Lora.Name} ({l.Weight:0.##})");
        return string.Join(", ", parts);
    }

    private async Task ClearInvokeCacheAsync()
    {
        try
        {
            StatusText = "Clearing InvokeAI cache...";
            await CleanupInvokeAiAsync();
            StatusText = "InvokeAI cache cleared.";
        }
        catch (Exception ex)
        {
            StatusText = $"Cache clear failed: {ex.Message}";
        }
    }

    private InvokeAIGenerationParams? TryParseGenerationParamsJson(string? json)
    {
        if (string.IsNullOrWhiteSpace(json)) return null;
        try
        {
            using var doc = System.Text.Json.JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.ValueKind != System.Text.Json.JsonValueKind.Object) return null;

            var map = new Dictionary<string, System.Text.Json.JsonElement>(StringComparer.OrdinalIgnoreCase);
            foreach (var prop in root.EnumerateObject())
            {
                map[Normalize(prop.Name)] = prop.Value;
            }

            bool TryGet(string key, out System.Text.Json.JsonElement value) => map.TryGetValue(Normalize(key), out value);
            static string Normalize(string name) => name.Replace("_", string.Empty).ToLowerInvariant();

            var p = new InvokeAIGenerationParams();
            if (TryGet("prompt", out var prompt) && prompt.ValueKind == System.Text.Json.JsonValueKind.String) p.Prompt = prompt.GetString() ?? p.Prompt;
            if (TryGet("positivestyleprompt", out var ps) && ps.ValueKind == System.Text.Json.JsonValueKind.String) p.PositiveStylePrompt = ps.GetString();
            if (TryGet("negativestyleprompt", out var ns) && ns.ValueKind == System.Text.Json.JsonValueKind.String) p.NegativeStylePrompt = ns.GetString();
            if (TryGet("negativeprompt", out var neg) && neg.ValueKind == System.Text.Json.JsonValueKind.String) p.NegativePrompt = neg.GetString();
            if (TryGet("basemodeltype", out var bmt) && bmt.ValueKind == System.Text.Json.JsonValueKind.String) p.BaseModelType = bmt.GetString();
            if (TryGet("usedrandomseed", out var urs) && urs.ValueKind is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False) p.UsedRandomSeed = urs.GetBoolean();
            if (TryGet("baseseed", out var bs) && bs.TryGetInt32(out var bsVal)) p.BaseSeed = bsVal;
            if (TryGet("autoclearedmodelcachebetweenmodels", out var ac) && ac.ValueKind is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False) p.AutoClearedModelCacheBetweenModels = ac.GetBoolean();
            if (TryGet("vaeusedname", out var vaeUsed) && vaeUsed.ValueKind == System.Text.Json.JsonValueKind.String) p.VaeUsedName = vaeUsed.GetString();
            if (TryGet("usepromptasstylewhenempty", out var styleFallback) && styleFallback.ValueKind is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False)
            {
                p.UsePromptAsStyleWhenEmpty = styleFallback.GetBoolean();
            }

            if (TryGet("steps", out var steps) && steps.TryGetInt32(out var st)) p.Steps = st;
            if (TryGet("cfgscale", out var cfg) && cfg.TryGetDouble(out var c)) p.CfgScale = c;
            if (TryGet("width", out var w) && w.TryGetInt32(out var wi)) p.Width = wi;
            if (TryGet("height", out var h) && h.TryGetInt32(out var he)) p.Height = he;
            if (TryGet("seed", out var seed) && seed.TryGetInt32(out var s)) p.Seed = s;
            if (TryGet("scheduler", out var sch) && sch.ValueKind == System.Text.Json.JsonValueKind.String) p.Scheduler = sch.GetString() ?? p.Scheduler;
            if (TryGet("cfgrescalemultiplier", out var rescale) && rescale.TryGetDouble(out var r)) p.CfgRescaleMultiplier = r;
            if (TryGet("savetogallery", out var save) && save.ValueKind is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False) p.SaveToGallery = save.GetBoolean();
            if (TryGet("vae", out var vaeElem))
            {
                if (vaeElem.ValueKind == System.Text.Json.JsonValueKind.Object)
                {
                    var name = vaeElem.TryGetProperty("name", out var vn) ? vn.GetString() : null;
                    var key = vaeElem.TryGetProperty("key", out var vk) ? vk.GetString() : null;
                    var hash = vaeElem.TryGetProperty("hash", out var vh) ? vh.GetString() : null;
                    p.VaeUsedName = name ?? key ?? hash ?? p.VaeUsedName;
                }
                else if (vaeElem.ValueKind == System.Text.Json.JsonValueKind.String)
                {
                    p.VaeUsedName = vaeElem.GetString();
                }
            }

            if (TryGet("model", out var modelElem) || TryGet("modelname", out modelElem))
            {
                if (modelElem.ValueKind == System.Text.Json.JsonValueKind.Object)
                {
                    var name = modelElem.TryGetProperty("name", out var mn) ? mn.GetString() : null;
                    var @base = modelElem.TryGetProperty("base", out var mb) ? mb.GetString() : null;
                    var format = modelElem.TryGetProperty("format", out var mf) ? mf.GetString() : null;
                    var key = modelElem.TryGetProperty("key", out var mk) ? mk.GetString() : null;
                    var hash = modelElem.TryGetProperty("hash", out var mh) ? mh.GetString() : null;
                    p.Model = new InvokeAIModel { Name = name ?? "", Base = @base ?? "", Format = format ?? "", Key = key ?? "", Hash = hash ?? "" };
                }
                else if (modelElem.ValueKind == System.Text.Json.JsonValueKind.String)
                {
                    p.Model = new InvokeAIModel { Name = modelElem.GetString() ?? "" };
                }
            }

            if (TryGet("loras", out var lorasElem) && lorasElem.ValueKind == System.Text.Json.JsonValueKind.Array)
            {
                foreach (var l in lorasElem.EnumerateArray())
                {
                    InvokeAIModel? loraModel = null;
                    var weight = 0.75;

                    if (l.ValueKind == System.Text.Json.JsonValueKind.String)
                    {
                        loraModel = new InvokeAIModel { Name = l.GetString() ?? "" };
                    }
                    else if (l.ValueKind == System.Text.Json.JsonValueKind.Object)
                    {
                        var lProps = new Dictionary<string, System.Text.Json.JsonElement>(StringComparer.OrdinalIgnoreCase);
                        foreach (var prop in l.EnumerateObject())
                        {
                            lProps[prop.Name] = prop.Value;
                        }
                        bool TryGetL(string key, out System.Text.Json.JsonElement value) => lProps.TryGetValue(key, out value);

                        if (TryGetL("weight", out var wt) && wt.TryGetDouble(out var wgt))
                        {
                            weight = wgt;
                        }

                        if (TryGetL("lora", out var loraObj) || TryGetL("lora_object", out loraObj))
                        {
                            if (loraObj.ValueKind == System.Text.Json.JsonValueKind.Object)
                            {
                                var loraProps = new Dictionary<string, System.Text.Json.JsonElement>(StringComparer.OrdinalIgnoreCase);
                                foreach (var prop in loraObj.EnumerateObject())
                                {
                                    loraProps[prop.Name] = prop.Value;
                                }
                                loraProps.TryGetValue("name", out var ln);
                                loraProps.TryGetValue("base", out var lb);
                                loraProps.TryGetValue("key", out var lk);
                                loraProps.TryGetValue("hash", out var lh);
                                var name = ln.ValueKind == System.Text.Json.JsonValueKind.String ? ln.GetString() : null;
                                var baseVal = lb.ValueKind == System.Text.Json.JsonValueKind.String ? lb.GetString() : null;
                                var key = lk.ValueKind == System.Text.Json.JsonValueKind.String ? lk.GetString() : null;
                                var hash = lh.ValueKind == System.Text.Json.JsonValueKind.String ? lh.GetString() : null;
                                loraModel = new InvokeAIModel { Name = name ?? "", Base = baseVal ?? "", Key = key ?? "", Hash = hash ?? "" };
                            }
                            else if (loraObj.ValueKind == System.Text.Json.JsonValueKind.String)
                            {
                                loraModel = new InvokeAIModel { Name = loraObj.GetString() ?? "" };
                            }
                        }

                        if (loraModel == null)
                        {
                            var name = TryGetL("name", out var ln) && ln.ValueKind == System.Text.Json.JsonValueKind.String ? ln.GetString() : null;
                            if (string.IsNullOrWhiteSpace(name) && TryGetL("lora_name", out var ln2) && ln2.ValueKind == System.Text.Json.JsonValueKind.String)
                            {
                                name = ln2.GetString();
                            }
                            var baseVal = TryGetL("base", out var lb) && lb.ValueKind == System.Text.Json.JsonValueKind.String ? lb.GetString() : null;
                            var key = TryGetL("key", out var lk) && lk.ValueKind == System.Text.Json.JsonValueKind.String ? lk.GetString() : null;
                            var hash = TryGetL("hash", out var lh) && lh.ValueKind == System.Text.Json.JsonValueKind.String ? lh.GetString() : null;
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
            return p;
        }
        catch
        {
            return null;
        }
    }
    private TemplatePlanResult BuildImmediateTemplatePlan(string theme, TemplateBuilderOptions options)
    {
        var selected = _wildcardService.GetWildcardNames()
            .OrderBy(n => ScoreWildcardForTheme(n, theme))
            .ThenBy(n => n, StringComparer.OrdinalIgnoreCase)
            .Take(options.TargetWildcardCount)
            .ToList();

        return new TemplatePlanResult(
            selected,
            Array.Empty<string>(),
            "Fast local shortlist based on wildcard names, descriptions, and sample values.");
    }

    private async Task<TemplatePlanResult> PlanTemplateWildcardsAsync(string theme, TemplateBuilderOptions options)
    {
        var wildcardNames = _wildcardService.GetWildcardNames()
            .OrderBy(n => ScoreWildcardForTheme(n, theme))
            .ThenBy(n => n, StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (wildcardNames.Count == 0)
        {
            throw new InvalidOperationException("No wildcards are available.");
        }

        var candidateCatalog = wildcardNames
            .Take(Math.Min(72, wildcardNames.Count))
            .Select(BuildWildcardCatalogEntry)
            .ToList();

        var targetRange = options.Complexity switch
        {
            "minimal" => "4-6",
            "rich" => "8-12",
            _ => "6-9"
        };

        var prompt =
            "You are an expert Stable Diffusion template planner.\n\n" +
            $"Theme: {theme}\n" +
            $"Workflow context: {BuildTemplateWorkflowContext()}\n" +
            $"Requested complexity: {options.DisplayComplexity}\n" +
            $"Requested focus: {options.DisplayFocus}\n\n" +
            "Choose the strongest wildcard set from the provided library. Your job is to pick a clean, non-redundant shortlist that fits the theme and focus.\n\n" +
            "Return exactly one JSON object with this shape:\n" +
            "{\n" +
            "  \"strategy\": \"one short sentence\",\n" +
            "  \"selectedWildcards\": [\"wildcard_name\"],\n" +
            "  \"missingWildcardIdeas\": [\"optional wildcard idea\"]\n" +
            "}\n\n" +
            "Rules:\n" +
            $"- Select {targetRange} wildcards.\n" +
            "- Use only wildcard names from the provided library.\n" +
            "- Avoid redundant wildcards that do the same job.\n" +
            "- Prefer wildcards that add variety, not generic filler.\n" +
            "- In SFW mode, keep the plan safe.\n" +
            "- In NSFW mode, adult content is allowed only when the user's theme is explicitly sexual. Do not force explicit content into non-sexual themes.\n" +
            "- 'missingWildcardIdeas' should list missing gaps only when they would materially improve the result.\n" +
            "- Do not include commentary outside the JSON object.\n\n" +
            "Available wildcard library:\n" +
            string.Join("\n", candidateCatalog);

        var raw = await _ollamaClient.GenerateAsync(SelectedModel!, prompt, temperature: 0.2, topP: 0.75);
        var parsed = ParseTemplatePlanResponse(raw);
        if (parsed.SelectedWildcards.Count > 0)
        {
            return parsed;
        }

        return new TemplatePlanResult(
            wildcardNames.Take(options.TargetWildcardCount).ToList(),
            new List<string>(),
            "Using the strongest local wildcard matches because the planner did not return a usable shortlist.");
    }

    private async Task<IReadOnlyList<TemplateCandidate>> GenerateTemplateCandidatesAsync(
        string theme,
        TemplateBuilderOptions options,
        IReadOnlyList<string> approvedWildcards)
    {
        var wildcardDetails = approvedWildcards
            .Select(BuildWildcardDetailEntry)
            .ToList();

        var prompt =
            "You are an expert Stable Diffusion template composer.\n\n" +
            $"Theme: {theme}\n" +
            $"Workflow context: {BuildTemplateWorkflowContext()}\n" +
            $"Requested complexity: {options.DisplayComplexity}\n" +
            $"Requested focus: {options.DisplayFocus}\n\n" +
            "Generate exactly three template candidates using only the approved wildcard list.\n" +
            "Return exactly one JSON object with this shape:\n" +
            "{\n" +
            "  \"candidates\": [\n" +
            "    {\"name\": \"Balanced Core\", \"strategy\": \"short rationale\", \"template\": \"comma-separated prompt template\"}\n" +
            "  ]\n" +
            "}\n\n" +
            "Rules:\n" +
            "- Use ONLY approved wildcards from the provided list.\n" +
            "- Never invent a wildcard.\n" +
            "- Keep templates comma-separated, not full sentences.\n" +
            "- Avoid generic camera-angle, lens, shot-type, or quality-tag fluff unless the theme explicitly asks for it.\n" +
            "- Each candidate should feel distinct: one clean and reliable, one more atmospheric, one more adventurous.\n" +
            "- Do not repeat the same wildcard more than once in a single template.\n" +
            "- In SFW mode, keep content safe.\n" +
            "- In NSFW mode, adult content is allowed only when the theme is explicitly sexual. Do not force erotic phrasing into non-sexual themes.\n" +
            "- Do not include commentary outside the JSON object.\n\n" +
            "Approved wildcards with samples:\n" +
            string.Join("\n", wildcardDetails);

        var raw = await _ollamaClient.GenerateAsync(SelectedModel!, prompt, temperature: 0.3, topP: 0.8);
        var candidates = ParseTemplateCandidatesResponse(raw, approvedWildcards, theme);

        if (candidates.Count >= 3)
        {
            return candidates;
        }

        var fallback = BuildFallbackTemplateCandidates(theme, options, approvedWildcards);
        var merged = candidates.Concat(fallback)
            .GroupBy(c => c.Name, StringComparer.OrdinalIgnoreCase)
            .Select(g => g.First())
            .Take(3)
            .ToList();

        return merged;
    }

    private TemplatePlanResult ParseTemplatePlanResponse(string rawResponse)
    {
        var json = ExtractJsonObject(rawResponse);
        if (json == null)
        {
            return new TemplatePlanResult(new List<string>(), new List<string>(), string.Empty);
        }

        var selected = new List<string>();
        var missing = new List<string>();
        var strategy = string.Empty;

        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
        {
            return new TemplatePlanResult(selected, missing, strategy);
        }

        if (root.TryGetProperty("strategy", out var strategyProp) && strategyProp.ValueKind == JsonValueKind.String)
        {
            strategy = strategyProp.GetString() ?? string.Empty;
        }

        if (root.TryGetProperty("selectedWildcards", out var selectedProp) && selectedProp.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in selectedProp.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.String)
                {
                    continue;
                }

                var normalized = NormalizeWildcardReference(item.GetString());
                if (!string.IsNullOrWhiteSpace(normalized) &&
                    _wildcardService.WildcardExists(normalized) &&
                    !selected.Contains(normalized, StringComparer.OrdinalIgnoreCase))
                {
                    selected.Add(normalized);
                }
            }
        }

        if (root.TryGetProperty("missingWildcardIdeas", out var missingProp) && missingProp.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in missingProp.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.String)
                {
                    continue;
                }

                var value = item.GetString()?.Trim();
                if (!string.IsNullOrWhiteSpace(value) &&
                    !missing.Contains(value, StringComparer.OrdinalIgnoreCase))
                {
                    missing.Add(value);
                }
            }
        }

        return new TemplatePlanResult(selected, missing, strategy);
    }

    private List<TemplateCandidate> ParseTemplateCandidatesResponse(
        string rawResponse,
        IReadOnlyList<string> approvedWildcards,
        string theme)
    {
        var results = new List<TemplateCandidate>();
        var json = ExtractJsonObject(rawResponse);
        if (json == null)
        {
            return results;
        }

        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (root.ValueKind != JsonValueKind.Object ||
            !root.TryGetProperty("candidates", out var candidatesProp) ||
            candidatesProp.ValueKind != JsonValueKind.Array)
        {
            return results;
        }

        foreach (var item in candidatesProp.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            var name = item.TryGetProperty("name", out var nameProp) && nameProp.ValueKind == JsonValueKind.String
                ? (nameProp.GetString() ?? "Candidate")
                : "Candidate";
            var strategy = item.TryGetProperty("strategy", out var strategyProp) && strategyProp.ValueKind == JsonValueKind.String
                ? (strategyProp.GetString() ?? string.Empty)
                : string.Empty;
            var template = item.TryGetProperty("template", out var templateProp) && templateProp.ValueKind == JsonValueKind.String
                ? (templateProp.GetString() ?? string.Empty)
                : string.Empty;

            var normalizedTemplate = NormalizeGeneratedTemplate(template, approvedWildcards, theme);
            if (string.IsNullOrWhiteSpace(normalizedTemplate))
            {
                continue;
            }

            results.Add(new TemplateCandidate(name.Trim(), normalizedTemplate, strategy.Trim()));
        }

        return results;
    }

    private IReadOnlyList<TemplateCandidate> BuildFallbackTemplateCandidates(
        string theme,
        TemplateBuilderOptions options,
        IReadOnlyList<string> approvedWildcards)
    {
        var baseSegments = approvedWildcards
            .Take(options.TargetWildcardCount)
            .Select(name => $"__{name}__")
            .ToList();

        var themeSegment = theme.Trim();
        var candidates = new List<TemplateCandidate>();

        var lean = string.Join(", ", new[] { themeSegment }
            .Concat(baseSegments.Take(Math.Min(4, baseSegments.Count))));
        candidates.Add(new TemplateCandidate(
            "Reliable Core",
            lean,
            "Lean structure centered on the theme with the strongest wildcard anchors."));

        var atmosphericSegments = baseSegments.Skip(1).Take(Math.Min(5, Math.Max(0, baseSegments.Count - 1))).ToList();
        var atmosphericLead = options.Focus switch
        {
            "environment" => "layered environment detail",
            "character" => "subject-forward detail",
            "action" => "motion-driven scene detail",
            _ => "balanced scene detail"
        };
        var atmospheric = string.Join(", ", new[] { themeSegment, atmosphericLead }
            .Concat(atmosphericSegments));
        candidates.Add(new TemplateCandidate(
            "Atmospheric Build",
            atmospheric,
            "Adds more scene texture while keeping the wildcard set controlled."));

        var adventurous = string.Join(", ", new[] { themeSegment, options.Focus == "action" ? "dynamic action emphasis" : "creative layered composition" }
            .Concat(baseSegments.Take(Math.Min(8, baseSegments.Count))));
        candidates.Add(new TemplateCandidate(
            "Creative Push",
            adventurous,
            "Uses a denser wildcard mix for a richer, more varied template."));

        return candidates
            .Select(c => new TemplateCandidate(c.Name, NormalizeGeneratedTemplate(c.Template, approvedWildcards, theme), c.Strategy))
            .Where(c => !string.IsNullOrWhiteSpace(c.Template))
            .ToList();
    }

    private string NormalizeGeneratedTemplate(string template, IReadOnlyList<string> approvedWildcards, string theme)
    {
        if (string.IsNullOrWhiteSpace(template))
        {
            return string.Empty;
        }

        var approved = approvedWildcards.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var cleaned = template
            .Replace("```", string.Empty, StringComparison.Ordinal)
            .Replace("TEMPLATE:", string.Empty, StringComparison.OrdinalIgnoreCase)
            .Trim();

        var segments = cleaned.Split(',')
            .Select(segment => segment.Trim())
            .Where(segment => !string.IsNullOrWhiteSpace(segment))
            .ToList();

        var finalSegments = new List<string>();
        var usedWildcards = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var segment in segments)
        {
            var matches = WildcardRegex.Matches(segment);
            var unknownWildcard = false;
            var duplicateWildcard = false;

            foreach (Match match in matches)
            {
                var wildcardName = match.Groups["name"].Value;
                if (!approved.Contains(wildcardName))
                {
                    unknownWildcard = true;
                    break;
                }

                if (!usedWildcards.Add(wildcardName))
                {
                    duplicateWildcard = true;
                    break;
                }
            }

            if (unknownWildcard || duplicateWildcard)
            {
                continue;
            }

            if (!finalSegments.Contains(segment, StringComparer.OrdinalIgnoreCase))
            {
                finalSegments.Add(segment);
            }
        }

        if (!finalSegments.Any(s => WildcardRegex.IsMatch(s)))
        {
            finalSegments.Insert(0, theme.Trim());
            if (approvedWildcards.Count > 0)
            {
                finalSegments.Add($"__{approvedWildcards[0]}__");
            }
        }

        return string.Join(", ", finalSegments.Where(s => !string.IsNullOrWhiteSpace(s)));
    }

    private IReadOnlyList<string> ParseApprovedWildcardNames(string? rawText)
    {
        if (string.IsNullOrWhiteSpace(rawText))
        {
            return Array.Empty<string>();
        }

        var approved = new List<string>();
        foreach (var item in rawText.Split(new[] { ',', '\n', '\r', '\t' }, StringSplitOptions.RemoveEmptyEntries))
        {
            var normalized = NormalizeWildcardReference(item);
            if (string.IsNullOrWhiteSpace(normalized) || !_wildcardService.WildcardExists(normalized))
            {
                continue;
            }

            if (!approved.Contains(normalized, StringComparer.OrdinalIgnoreCase))
            {
                approved.Add(normalized);
            }
        }

        return approved;
    }

    private string BuildWildcardCatalogEntry(string wildcardName)
    {
        var description = _wildcardService.GetStructuredWildcards().TryGetValue(wildcardName, out var structured) &&
                          !string.IsNullOrWhiteSpace(structured.Description)
            ? structured.Description!.Trim()
            : "No description";
        var samples = _wildcardService.GetAllValues(wildcardName)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .Take(3)
            .Select(TrimTemplateSample)
            .ToList();
        var sampleText = samples.Count == 0 ? "no sample values" : string.Join(" | ", samples);
        return $"- __{wildcardName}__: {description}. Samples: {sampleText}";
    }

    private string BuildWildcardDetailEntry(string wildcardName)
    {
        var samples = _wildcardService.GetAllValues(wildcardName)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .Take(4)
            .Select(TrimTemplateSample)
            .ToList();
        var sampleText = samples.Count == 0 ? "no sample values" : string.Join(" | ", samples);
        return $"- __{wildcardName}__: {sampleText}";
    }

    private string BuildHumanReadableWildcardPreview(string wildcardName)
    {
        var lines = new List<string> { $"__{wildcardName}__" };

        if (_wildcardService.GetStructuredWildcards().TryGetValue(wildcardName, out var structured))
        {
            if (!string.IsNullOrWhiteSpace(structured.Description))
            {
                lines.Add(string.Empty);
                lines.Add(structured.Description.Trim());
            }

            if (structured.Choices.Count > 0)
            {
                lines.Add(string.Empty);
                lines.Add("Sample Entries:");
                foreach (var choice in structured.Choices.Take(8))
                {
                    var summary = choice.Value?.Trim();
                    if (string.IsNullOrWhiteSpace(summary))
                    {
                        continue;
                    }

                    var suffix = new List<string>();
                    if (Math.Abs(choice.Weight - 1d) > 0.001d)
                    {
                        suffix.Add($"weight {choice.Weight:0.##}");
                    }

                    if (choice.Tags != null && choice.Tags.Count > 0)
                    {
                        suffix.Add($"tags: {string.Join(", ", choice.Tags.Take(4))}");
                    }

                    lines.Add(suffix.Count == 0
                        ? $"- {TrimTemplateSample(summary)}"
                        : $"- {TrimTemplateSample(summary)} ({string.Join("; ", suffix)})");
                }
            }
        }
        else
        {
            var values = _wildcardService.GetAllValues(wildcardName)
                .Where(v => !string.IsNullOrWhiteSpace(v))
                .Take(8)
                .Select(TrimTemplateSample)
                .ToList();

            lines.Add(string.Empty);
            lines.Add(values.Count == 0
                ? "No preview available."
                : $"Sample Entries:\n- {string.Join("\n- ", values)}");
        }

        return string.Join("\n", lines);
    }

    private int ScoreWildcardForTheme(string wildcardName, string theme)
    {
        var tokens = ExtractThemeTokens(theme).ToList();
        if (tokens.Count == 0)
        {
            return 0;
        }

        var nameText = wildcardName.Replace('_', ' ');
        var descriptionText = _wildcardService.GetStructuredWildcards().TryGetValue(wildcardName, out var structured)
            ? structured.Description ?? string.Empty
            : string.Empty;
        var sampleText = string.Join(" ", _wildcardService.GetAllValues(wildcardName).Take(8));

        var score = 0;
        foreach (var token in tokens)
        {
            if (ContainsToken(nameText, token))
            {
                score -= 6;
            }

            if (ContainsToken(descriptionText, token))
            {
                score -= 3;
            }

            if (ContainsToken(sampleText, token))
            {
                score -= 2;
            }
        }

        var themeText = string.Join(" ", tokens);
        if (ContainsPhrase(nameText, themeText))
        {
            score -= 4;
        }

        if (ContainsPhrase(descriptionText, themeText))
        {
            score -= 2;
        }

        var isNsfwWorkflow = string.Equals(Workflow, "nsfw", StringComparison.OrdinalIgnoreCase);
        var themeIsAdult = tokens.Any(t =>
            t.Contains("nsfw", StringComparison.OrdinalIgnoreCase) ||
            t.Contains("adult", StringComparison.OrdinalIgnoreCase) ||
            t.Contains("sex", StringComparison.OrdinalIgnoreCase) ||
            t.Contains("nude", StringComparison.OrdinalIgnoreCase) ||
            t.Contains("erotic", StringComparison.OrdinalIgnoreCase) ||
            t.Contains("porn", StringComparison.OrdinalIgnoreCase));
        var wildcardLooksAdult =
            ContainsToken(nameText, "nsfw") ||
            ContainsToken(nameText, "adult") ||
            ContainsToken(nameText, "sex") ||
            ContainsToken(nameText, "nude") ||
            ContainsToken(descriptionText, "adult") ||
            ContainsToken(descriptionText, "erotic");

        if (isNsfwWorkflow && themeIsAdult && wildcardLooksAdult)
        {
            score -= 3;
        }

        if (!themeIsAdult && wildcardLooksAdult && !isNsfwWorkflow)
        {
            score += 3;
        }

        return score;
    }

    private IEnumerable<string> ExtractThemeTokens(string theme)
    {
        return Regex.Matches(theme.ToLowerInvariant(), "[a-z0-9]+")
            .Select(m => m.Value)
            .Where(v => v.Length >= 3)
            .Distinct(StringComparer.OrdinalIgnoreCase);
    }

    private static bool ContainsToken(string source, string token)
    {
        if (string.IsNullOrWhiteSpace(source) || string.IsNullOrWhiteSpace(token))
        {
            return false;
        }

        return source.Contains(token, StringComparison.OrdinalIgnoreCase);
    }

    private static bool ContainsPhrase(string source, string phrase)
    {
        if (string.IsNullOrWhiteSpace(source) || string.IsNullOrWhiteSpace(phrase))
        {
            return false;
        }

        return source.Contains(phrase, StringComparison.OrdinalIgnoreCase);
    }

    private string BuildTemplateWorkflowContext()
    {
        return string.Equals(Workflow, "nsfw", StringComparison.OrdinalIgnoreCase)
            ? "NSFW workflow is active. Adult themes are allowed when the user explicitly asks for them. Do not force explicit content into non-sexual concepts."
            : "SFW workflow is active. Keep concepts safe and non-explicit.";
    }

    private static string? ExtractJsonObject(string rawResponse)
    {
        if (string.IsNullOrWhiteSpace(rawResponse))
        {
            return null;
        }

        var start = rawResponse.IndexOf('{');
        var end = rawResponse.LastIndexOf('}');
        if (start < 0 || end <= start)
        {
            return null;
        }

        return rawResponse[start..(end + 1)];
    }

    private static string NormalizeTemplateComplexity(string value)
    {
        return value.Trim().ToLowerInvariant() switch
        {
            "minimal" => "minimal",
            "rich" => "rich",
            _ => "balanced"
        };
    }

    private static string NormalizeTemplateFocus(string value)
    {
        return value.Trim().ToLowerInvariant() switch
        {
            "character" => "character",
            "environment" => "environment",
            "action" => "action",
            _ => "balanced"
        };
    }

    private static string NormalizeWildcardReference(string? rawValue)
    {
        if (string.IsNullOrWhiteSpace(rawValue))
        {
            return string.Empty;
        }

        var trimmed = rawValue.Trim();
        if (trimmed.StartsWith("__", StringComparison.Ordinal) && trimmed.EndsWith("__", StringComparison.Ordinal) && trimmed.Length > 4)
        {
            trimmed = trimmed[2..^2];
        }

        if (trimmed.StartsWith("{", StringComparison.Ordinal) && trimmed.EndsWith("}", StringComparison.Ordinal) && trimmed.Length > 2)
        {
            trimmed = trimmed[1..^1];
        }

        return trimmed.Trim();
    }

    private static string TrimTemplateSample(string value)
    {
        var normalized = Regex.Replace(value.Trim(), "\\s+", " ");
        return normalized.Length <= 60 ? normalized : $"{normalized[..57]}...";
    }

    private static string SuggestTemplateName(string theme)
    {
        var lower = theme.Trim().ToLowerInvariant();
        var slug = Regex.Replace(lower, "[^a-z0-9]+", "_");
        slug = Regex.Replace(slug, "_{2,}", "_").Trim('_');
        return string.IsNullOrWhiteSpace(slug) ? "ai_template" : slug;
    }

    private sealed record TemplateBuilderOptions(string Complexity, string Focus)
    {
        public string DisplayComplexity => Complexity switch
        {
            "minimal" => "Minimal",
            "rich" => "Rich",
            _ => "Balanced"
        };

        public string DisplayFocus => Focus switch
        {
            "character" => "Character",
            "environment" => "Environment",
            "action" => "Action",
            _ => "Balanced"
        };

        public int TargetWildcardCount => Complexity switch
        {
            "minimal" => 5,
            "rich" => 10,
            _ => 7
        };
    }

    private sealed record TemplatePlanResult(
        IReadOnlyList<string> SelectedWildcards,
        IReadOnlyList<string> MissingWildcardIdeas,
        string Strategy);

    private sealed record TemplateCandidate(
        string Name,
        string Template,
        string Strategy);

    public async Task CreateWildcardWithOptionalAiAsync(string? wildcardName, Window? owner = null, WildcardManagerViewModel? managerVm = null)
    {
        if (string.IsNullOrWhiteSpace(wildcardName))
        {
            return;
        }

        var normalizedName = wildcardName.Trim();
        var resolvedOwner = GetOwnerWindow(owner) ?? new Window();

        try
        {
            await _wildcardService.SaveWildcardFileContent(normalizedName, BuildEmptyWildcardContent(normalizedName));
            _wildcardService.Reload(_settingsService.GetWildcardDirs());
            LoadWildcards();
            UpdateMissingWildcardsPreview(PromptText);
        }
        catch (Exception ex)
        {
            StatusText = $"Failed to create wildcard: {ex.Message}";
            return;
        }

        Window dialogOwner;
        if (managerVm != null && owner != null)
        {
            await managerVm.SelectWildcardAfterLoadAsync(normalizedName);
            dialogOwner = owner;
        }
        else
        {
            dialogOwner = OpenWildcardManagerWindow(resolvedOwner, normalizedName);
            await Task.Yield();
        }

        var useAi = await ShowConfirmAsync(
            dialogOwner,
            $"The wildcard '{normalizedName}' has been created.\n\n" +
            "Would you like to prepopulate it with AI suggestions?");

        if (useAi)
        {
            if (string.IsNullOrWhiteSpace(SelectedModel))
            {
                StatusText = "Wildcard created, but no Ollama model is selected for AI suggestions.";
                await ShowInfoAsync(dialogOwner, "No Model Selected", "Select an Ollama model first. The wildcard was created with the default scaffold.");
            }
            else
            {
                var description = await Views.TextInputDialog.ShowAsync(
                    "Describe Wildcard",
                    $"What should '{normalizedName}' be comprised of?",
                    $"A curated set of {normalizedName.Replace('_', ' ')} options",
                    dialogOwner);

                if (!string.IsNullOrWhiteSpace(description))
                {
                    try
                    {
                        StatusText = $"Generating AI suggestions for '{normalizedName}'...";
                        managerVm?.SetStatusMessage("AI is generating suggestions...");
                        if (dialogOwner.DataContext is WildcardManagerViewModel activeManagerVm)
                        {
                            activeManagerVm.SetStatusMessage("AI is generating suggestions...");
                        }
                        await Task.Yield();

                        var generatedContent = await GenerateWildcardSuggestionsAsync(normalizedName, description.Trim());
                        await _wildcardService.SaveWildcardFileContent(normalizedName, generatedContent);
                        _wildcardService.Reload(_settingsService.GetWildcardDirs());
                        LoadWildcards();
                        UpdateMissingWildcardsPreview(PromptText);
                        if (managerVm != null)
                        {
                            await managerVm.SelectWildcardAfterLoadAsync(normalizedName);
                            managerVm.CurrentWildcardName = normalizedName;
                            managerVm.CurrentWildcardContent = generatedContent;
                            managerVm.ReloadStructuredFromRawCommand.Execute(null);
                            managerVm.SetStatusMessage($"Created wildcard '{normalizedName}' with AI suggestions.");
                        }
                        else if (dialogOwner.DataContext is WildcardManagerViewModel openedManagerVm)
                        {
                            await openedManagerVm.SelectWildcardAfterLoadAsync(normalizedName);
                            openedManagerVm.CurrentWildcardName = normalizedName;
                            openedManagerVm.CurrentWildcardContent = generatedContent;
                            openedManagerVm.ReloadStructuredFromRawCommand.Execute(null);
                            openedManagerVm.SetStatusMessage($"Created wildcard '{normalizedName}' with AI suggestions.");
                        }
                        StatusText = $"Created wildcard '{normalizedName}' with AI suggestions.";
                    }
                    catch (Exception ex)
                    {
                        managerVm?.SetStatusMessage($"AI suggestions failed: {ex.Message}");
                        if (dialogOwner.DataContext is WildcardManagerViewModel failedManagerVm)
                        {
                            failedManagerVm.SetStatusMessage($"AI suggestions failed: {ex.Message}");
                        }
                        StatusText = $"Wildcard created, but AI suggestions failed: {ex.Message}";
                        await ShowInfoAsync(dialogOwner, "AI Suggestions Failed", $"The wildcard was created, but suggestions failed.\n\n{ex.Message}");
                    }
                }
                else
                {
                    StatusText = $"Created wildcard '{normalizedName}' with default scaffold.";
                }
            }
        }
        else
        {
            StatusText = $"Created wildcard '{normalizedName}' with default scaffold.";
        }
    }

    private async Task CreateMissingWildcardAsync(string? wildcardName)
    {
        await CreateWildcardWithOptionalAiAsync(wildcardName, null, null);
    }

    private string BuildEmptyWildcardContent(string wildcardName)
    {
        var payload = new
        {
            description = $"Wildcard file for {wildcardName.Replace('_', ' ')}",
            choices = new[] { "example entry" }
        };

        return JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
    }

    private async Task<string> GenerateWildcardSuggestionsAsync(string wildcardName, string description)
    {
        var workflowContext = string.Equals(Workflow, "nsfw", StringComparison.OrdinalIgnoreCase)
            ? "NSFW workflow is active. Only produce adult content if the requested topic is inherently adult."
            : "SFW workflow is active. Keep suggestions safe unless the topic explicitly requires otherwise.";

        var availableWildcards = _wildcardService.GetWildcardNames()
            .Where(n => !string.Equals(n, wildcardName, StringComparison.OrdinalIgnoreCase))
            .OrderBy(n => n, StringComparer.OrdinalIgnoreCase)
            .Take(24)
            .ToList();
        var availableWildcardsText = availableWildcards.Count == 0
            ? "None"
            : string.Join(", ", availableWildcards);

        var prompt =
            "You are an expert Stable Diffusion wildcard generator with strong prompt-engineering discipline.\n\n" +
            $"Create a JSON wildcard file for the wildcard name '{wildcardName}'.\n" +
            $"User description: {description}\n" +
            $"Workflow context: {workflowContext}\n" +
            $"Available related wildcards: {availableWildcardsText}\n\n" +
            "Return exactly one valid JSON object with this structure:\n" +
            "{\n" +
            "  \"description\": \"short description\",\n" +
            "  \"choices\": [\n" +
            "    \"simple choice\",\n" +
            "    {\"value\": \"rich choice\", \"weight\": 2, \"tags\": [\"tag\"]}\n" +
            "  ]\n" +
            "}\n\n" +
            "Rules:\n" +
            "- Generate 20-30 distinct, highly relevant choices.\n" +
            "- Keep the choices tightly aligned with the topic.\n" +
            "- Treat the topic as the only subject. Do not broaden into adjacent prompt-engineering categories.\n" +
            "- Do not generate camera angles, shot types, lens terms, composition phrases, render-quality terms, art styles, lighting setups, or other cinematic modifiers unless the topic explicitly asks for those.\n" +
            "- For subject or scene wildcards, generate actual subjects, factions, props, terrain details, weather conditions, battlefield elements, creature types, roles, or thematic objects that belong inside the scene.\n" +
            "- Bad example for a 'fantasy battlefield' wildcard: 'wide shot', 'dramatic angle', 'cinematic lighting'.\n" +
            "- Good example for a 'fantasy battlefield' wildcard: 'broken siege towers', 'muddy trench lines', 'burning barricades', 'fallen banners', 'orc war drums'.\n" +
            "- Do not use underscores inside 'value' strings.\n" +
            "- Do not include commentary outside the JSON.\n" +
            $"- Do not self-reference '{wildcardName}' in requires/includes.\n" +
            "- You may use value, weight, tags, requires, and includes when useful.\n" +
            "- Ensure the JSON is valid and the choices array is not empty.\n";

        var raw = await _ollamaClient.GenerateAsync(SelectedModel!, prompt, temperature: 0.35, topP: 0.8);
        return NormalizeWildcardJsonResponse(raw, wildcardName, description);
    }

    public async Task<string> GenerateWildcardSuggestionsForEditorAsync(string wildcardName, string description)
    {
        if (string.IsNullOrWhiteSpace(SelectedModel))
        {
            throw new InvalidOperationException("Select an Ollama model first.");
        }

        return await GenerateWildcardSuggestionsAsync(wildcardName, description);
    }

    private static string NormalizeWildcardJsonResponse(string rawResponse, string wildcardName, string description)
    {
        if (string.IsNullOrWhiteSpace(rawResponse))
        {
            throw new InvalidOperationException("The model returned an empty response.");
        }

        var start = rawResponse.IndexOf('{');
        var end = rawResponse.LastIndexOf('}');
        if (start < 0 || end <= start)
        {
            throw new InvalidOperationException("The model did not return a JSON object.");
        }

        var jsonSlice = rawResponse[start..(end + 1)];
        using var doc = JsonDocument.Parse(jsonSlice);
        if (doc.RootElement.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidOperationException("The model response was not a JSON object.");
        }

        if (!doc.RootElement.TryGetProperty("choices", out var choices) || choices.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidOperationException("The model response did not include a valid 'choices' array.");
        }

        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();

            if (doc.RootElement.TryGetProperty("description", out var descProp) && descProp.ValueKind == JsonValueKind.String)
            {
                writer.WriteString("description", descProp.GetString());
            }
            else
            {
                writer.WriteString("description", $"Wildcard file for {wildcardName.Replace('_', ' ')}: {description}");
            }

            writer.WritePropertyName("choices");
            writer.WriteStartArray();
            foreach (var choice in choices.EnumerateArray())
            {
                WriteNormalizedWildcardChoice(writer, choice);
            }
            writer.WriteEndArray();
            writer.WriteEndObject();
        }

        return System.Text.Encoding.UTF8.GetString(stream.ToArray());
    }

    private static void WriteNormalizedWildcardChoice(Utf8JsonWriter writer, JsonElement choice)
    {
        switch (choice.ValueKind)
        {
            case JsonValueKind.String:
                writer.WriteStringValue(NormalizeWildcardChoiceText(choice.GetString()));
                return;

            case JsonValueKind.Object:
                writer.WriteStartObject();
                foreach (var prop in choice.EnumerateObject())
                {
                    var isChoiceValue = (prop.NameEquals("value") || prop.NameEquals("choice")) &&
                                        prop.Value.ValueKind == JsonValueKind.String;
                    if (isChoiceValue)
                    {
                        writer.WriteString(prop.Name, NormalizeWildcardChoiceText(prop.Value.GetString()));
                    }
                    else
                    {
                        prop.WriteTo(writer);
                    }
                }
                writer.WriteEndObject();
                return;

            default:
                choice.WriteTo(writer);
                return;
        }
    }

    private static string NormalizeWildcardChoiceText(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return string.Empty;
        }

        var normalized = text.Replace('_', ' ').Trim();
        while (normalized.Contains("  ", StringComparison.Ordinal))
        {
            normalized = normalized.Replace("  ", " ", StringComparison.Ordinal);
        }

        return normalized;
    }

    private void TryPlayGenerationCompleteSound()
    {
        try
        {
            if (OperatingSystem.IsWindows())
            {
                Console.Beep(880, 180);
            }
            else
            {
                Console.Write("\a");
                _notifications?.ShowInfo("Image generation complete.", "Generation Complete");
            }
        }
        catch
        {
            try
            {
                Console.Write("\a");
                if (!OperatingSystem.IsWindows())
                {
                    _notifications?.ShowInfo("Image generation complete.", "Generation Complete");
                }
            }
            catch
            {
                // Ignore best-effort notification failures.
            }
        }
    }

    private bool ShouldNotifyGenerationCompletion(GenerationJob? currentJob)
    {
        return !_generationQueue.Jobs.Any(job =>
            !ReferenceEquals(job, currentJob) &&
            job.Status is GenerationJobStatus.Queued or GenerationJobStatus.Running);
    }

    private async Task TryEmptyModelCacheAsync(CancellationToken cancellationToken)
    {
        try
        {
            await _invokeAIClient.EmptyModelCacheAsync(cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Respect cancellation without surfacing a secondary failure.
        }
        catch (Exception ex)
        {
            if (_settingsService.Settings.Verbose)
            {
                Console.WriteLine($"InvokeAI: failed to clear model cache: {ex.Message}");
            }
        }
    }

    public (string newText, int caret) InsertWildcardAtSelection(string? wildcardName, int caretIndex, int selectionStart, int selectionEnd)
    {
        if (string.IsNullOrWhiteSpace(wildcardName))
        {
            return (PromptText ?? string.Empty, caretIndex);
        }

        var (updated, caret) = InsertOrReplaceWildcardAt(wildcardName, caretIndex, selectionStart, selectionEnd);
        StatusText = $"Inserted wildcard {wildcardName}.";
        return (updated, caret);
    }

    private void InsertWildcard(string? wildcardName)
    {
        if (string.IsNullOrWhiteSpace(wildcardName))
        {
            return;
        }

        var caret = PromptText?.Length ?? 0;
        InsertWildcardAtSelection(wildcardName, caret, caret, caret);
    }

    private async Task SetWorkflowAsync(string? workflow)
    {
        if (string.IsNullOrWhiteSpace(workflow) || string.Equals(workflow, Workflow, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        Workflow = workflow.ToLowerInvariant();
        _settingsService.Settings.Workflow = Workflow;
        var ok = await _settingsService.SaveSettingsAsync(_settingsService.Settings);
        if (!ok)
        {
            _notifications?.ShowError("Failed to save workflow change.", "Error");
            StatusText = "Failed to switch workflow.";
            return;
        }

        _wildcardService.Reload(_settingsService.GetWildcardDirs());
        LoadWildcards();
        await LoadTemplatesAsync();
        await LoadVariationsAsync();
        StatusText = $"Switched to {Workflow.ToUpperInvariant()} workflow.";
    }

    private void RerollPrompt()
    {
        if (_lastGeneration == null)
        {
            StatusText = "Nothing to reroll.";
            return;
        }

        _ = ProcessPromptAsyncWithSeed(_lastGeneration.Seed, _lastGeneration.Context);
    }

    private async Task ProcessPromptAsyncWithSeed(int seed, Dictionary<string, ContextValue>? context)
    {
        ProcessedPromptSegments.Clear();
        StatusText = "Regenerating prompt...";

        var result = _promptProcessorService.ProcessPrompt(PromptText, seed, context);
        _lastGeneration = result;
        ApplyGenerationResult(result, "Prompt regenerated.");
        await Task.CompletedTask;
    }

    private void ApplyGenerationResult(TemplateGenerationResult result, string status)
    {
        ProcessedPromptSegments.Clear();
        (RerollPromptCommand as RelayCommand)?.NotifyCanExecuteChanged();
        var index = 0;
        foreach (var segment in result.Segments)
        {
            var vm = new PromptSegmentViewModel(segment, index++);
            if (segment.IsWildcard && !string.IsNullOrWhiteSpace(segment.OriginalWildcardName))
            {
                vm.Tooltip = BuildWildcardBrowserPreview(segment.OriginalWildcardName);
            }
            vm.PropertyChanged += (_, _) => RefreshProcessedOutput();
            ProcessedPromptSegments.Add(vm);
        }

        RefreshProcessedOutput();
        MissingWildcards = new ObservableCollection<string>(result.MissingWildcards.OrderBy(s => s, StringComparer.OrdinalIgnoreCase));
        StatusText = status;
    }

    private ContextValue BuildContextValue(string wildcardName, string value)
    {
        var structured = _wildcardService.GetStructuredWildcards();
        if (structured.TryGetValue(wildcardName, out var wildcard))
        {
            var match = wildcard.Choices.FirstOrDefault(c => string.Equals(c.Value, value, StringComparison.OrdinalIgnoreCase));
            if (match != null)
            {
                return new ContextValue(match.Value, match.Tags.ToList());
            }
        }
        return new ContextValue(value, new List<string>());
    }

    private Dictionary<string, ContextValue> BuildExperimentContext(IReadOnlyDictionary<string, string> lockedChoices)
    {
        var context = new Dictionary<string, ContextValue>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in lockedChoices)
        {
            if (string.IsNullOrWhiteSpace(entry.Key) || string.IsNullOrWhiteSpace(entry.Value))
            {
                continue;
            }

            context[entry.Key] = BuildContextValue(entry.Key, entry.Value);
        }

        return context;
    }

    public async Task UnloadModelsAsync()
    {
        if (!await _unloadLock.WaitAsync(0))
        {
            return;
        }
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            await _ollamaClient.UnloadAllModelsAsync(cts.Token);
        }
        catch (Exception ex)
        {
            if (_settingsService.Settings.Verbose) Console.WriteLine($"UnloadModelsAsync: {ex.Message}");
        }
        finally
        {
            _unloadLock.Release();
        }
    }

    private IEnumerable<Uri> BuildOllamaEndpointList()
    {
        var endpoints = new List<Uri>();
        if (_ollamaClient.BaseAddress != null) endpoints.Add(_ollamaClient.BaseAddress);
        else if (Uri.TryCreate(_settingsService.Settings.OllamaBaseUrl, UriKind.Absolute, out var configured))
            endpoints.Add(configured);

        if (!endpoints.Any(u => string.Equals(u.Host, "127.0.0.1") || string.Equals(u.Host, "localhost")))
        {
            endpoints.Add(new Uri("http://127.0.0.1:11434"));
        }

        return endpoints;
    }

    private static Window? GetOwnerWindow(Window? owner)
    {
        if (owner != null) return owner;
        var lifetime = Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime;
        return lifetime?.MainWindow;
    }

    private void Exit()
    {
        if (Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime lifetime)
        {
            _ = UnloadModelsAsync();
            _ = CleanupInvokeAiAsync();
            DisposeCaches();
            lifetime.Shutdown();
        }
    }

    public void DisposeCaches()
    {
        CancelActiveGeneration();
        _imageCacheService.Dispose();
        _historyIndexService.Clear();
    }

    public void CancelActiveGeneration()
    {
        _activeGenerationCts?.Cancel();
    }

    private async Task CleanupInvokeAiAsync()
    {
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            var ok = await _invokeAIClient.EmptyModelCacheAsync(cts.Token);
            if (!ok) if (_settingsService.Settings.Verbose) Console.WriteLine("InvokeAI: empty_model_cache call did not succeed.");
        }
        catch (Exception ex)
        {
            if (_settingsService.Settings.Verbose) Console.WriteLine($"InvokeAI: failed to empty model cache: {ex.Message}");
        }
    }

    private async Task ReleaseModelAsync(string? model)
    {
        foreach (var name in _modelUsageTracker.Release(model))
        {
            try
            {
                await _ollamaClient.UnloadModelAsync(name);
            }
            catch (Exception ex)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Unload model {name} failed: {ex.Message}");
            }
        }
    }
}

public record TemplateOption(string Name, string Path);

public sealed class WildcardBrowserItem
{
    public string Name { get; init; } = string.Empty;
    public string SampleText { get; init; } = string.Empty;
    public string Summary { get; init; } = string.Empty;
    public string Tooltip { get; init; } = string.Empty;
    public int ChoiceCount { get; init; }
    public int Score { get; init; }
}

public sealed class WildcardAutocompleteItem
{
    public string Name { get; init; } = string.Empty;
    public string Preview { get; init; } = string.Empty;
    public int ChoiceCount { get; init; }
    public int Score { get; init; }
}
