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
    private readonly TemplateService _templateService;
    private readonly ModelUsageTracker _modelUsageTracker;
    private readonly NotificationService? _notifications;
    private readonly ScoringCacheService _scoringCacheService;
    private readonly AestheticScoringService _aestheticScoringService;
    private readonly ImageCacheService _imageCacheService;
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

    public bool IsSfwWorkflow => string.Equals(Workflow, "sfw", StringComparison.OrdinalIgnoreCase);
    public bool IsNsfwWorkflow => string.Equals(Workflow, "nsfw", StringComparison.OrdinalIgnoreCase);

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
    public IAsyncRelayCommand<Window?> ViewFavoriteImagesCommand { get; }
    public IAsyncRelayCommand<Window?> ShowBrainstormingCommand { get; }
    public IAsyncRelayCommand<Window?> ShowImageInterrogatorCommand { get; }
    public IAsyncRelayCommand<Window?> ShowModelStatsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowWildcardManagerCommand { get; }
    public IAsyncRelayCommand<string?> OpenWildcardInManagerCommand { get; }
    public IAsyncRelayCommand<Window?> ShowAllImagesCommand { get; }
    public IRelayCommand<string?> CreateMissingWildcardCommand { get; }
    public IRelayCommand<string?> InsertWildcardCommand { get; }
    public IAsyncRelayCommand<Window?> ShowPromptEvolverCommand { get; }
    public IAsyncRelayCommand<Window?> ShowInvokeAIModelDefaultsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowInvokeAILoraDefaultsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowSystemPromptsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowPngMetadataViewerCommand { get; }
    public IAsyncRelayCommand<Window?> ShowSettingsSystemPromptsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowSettingsInvokeAIModelDefaultsCommand { get; }
    public IAsyncRelayCommand<Window?> ShowSettingsInvokeAILoraDefaultsCommand { get; }
    public IAsyncRelayCommand ClearInvokeCacheCommand { get; }
    public IAsyncRelayCommand<Window?> ShowAnalyticsStudioCommand { get; }
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
        _templateService = templateService;
        _modelUsageTracker = modelUsageTracker;
        _notifications = notifications;
        _scoringCacheService = new ScoringCacheService();
        _aestheticScoringService = new AestheticScoringService(_scoringCacheService, _settingsService);
        _imageCacheService = new ImageCacheService();
        _imageCacheService.DiskCacheDir = Path.Combine(_settingsService.GetHistoryDir(), ".thumbs");
        _historyIndexService = new HistoryIndexService();
        _workflow = _settingsService.Settings.Workflow;

        GenerateCommand = new AsyncRelayCommand(ProcessPromptAsync);
        EnhancePromptCommand = new AsyncRelayCommand(EnhancePromptAsync);
        GenerateImageCommand = new AsyncRelayCommand<Window?>(GenerateImageAsync);
        SetWorkflowCommand = new AsyncRelayCommand<string?>(SetWorkflowAsync);
        ShowSettingsCommand = new AsyncRelayCommand<Window?>(ShowSettingsAsync);
        ViewHistoryCommand = new AsyncRelayCommand<Window?>(ShowHistoryAsync);
        ViewFavoriteImagesCommand = new AsyncRelayCommand<Window?>(ShowFavoritesAsync);
        ShowBrainstormingCommand = new AsyncRelayCommand<Window?>(ShowBrainstormingAsync);
        ShowImageInterrogatorCommand = new AsyncRelayCommand<Window?>(ShowImageInterrogatorAsync);
        ShowModelStatsCommand = new AsyncRelayCommand<Window?>(ShowModelStatsAsync);
        ShowWildcardManagerCommand = new AsyncRelayCommand<Window?>(ShowWildcardManagerAsync);
        OpenWildcardInManagerCommand = new AsyncRelayCommand<string?>(OpenWildcardInManagerAsync);
        ShowAllImagesCommand = new AsyncRelayCommand<Window?>(ShowAllImagesAsync);
        CreateMissingWildcardCommand = new RelayCommand<string?>(CreateMissingWildcard);
        InsertWildcardCommand = new RelayCommand<string?>(InsertWildcard);
        ShowPromptEvolverCommand = new AsyncRelayCommand<Window?>(ShowPromptEvolverAsync);
        ShowPngMetadataViewerCommand = new AsyncRelayCommand<Window?>(ShowPngMetadataViewerAsync);
        ShowInvokeAIModelDefaultsCommand = new AsyncRelayCommand<Window?>(ShowInvokeAIModelDefaultsAsync);
        ShowInvokeAILoraDefaultsCommand = new AsyncRelayCommand<Window?>(ShowInvokeAILoraDefaultsAsync);
        ShowSystemPromptsCommand = new AsyncRelayCommand<Window?>(ShowSystemPromptsAsync);
        ShowSettingsSystemPromptsCommand = new AsyncRelayCommand<Window?>(owner => ShowSettingsAsync(owner, "SystemPrompts"));
        ShowSettingsInvokeAIModelDefaultsCommand = new AsyncRelayCommand<Window?>(owner => ShowSettingsAsync(owner, "InvokeAIModelDefaults"));
        ShowSettingsInvokeAILoraDefaultsCommand = new AsyncRelayCommand<Window?>(owner => ShowSettingsAsync(owner, "InvokeAILoraDefaults"));
        ClearInvokeCacheCommand = new AsyncRelayCommand(ClearInvokeCacheAsync);
        ShowAnalyticsStudioCommand = new AsyncRelayCommand<Window?>(ShowAnalyticsStudioAsync);
        RerollPromptCommand = new RelayCommand(RerollPrompt, () => _lastGeneration != null);
        ExitCommand = new RelayCommand(Exit);
    }

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
        _ = StartInvokeMonitorAsync();
        StatusText = "Ready.";
    }

    private void LoadWildcards()
    {
        var names = _wildcardService.GetWildcardNames()
            .OrderBy(n => n, StringComparer.OrdinalIgnoreCase);
        Wildcards = new ObservableCollection<string>(names);
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
            if (!ok && showToastOnFailure)
            {
                _notifications?.ShowError("InvokeAI is offline. Start it, then click Generate again.", "InvokeAI");
                StatusText = "InvokeAI offline.";
            }
            return ok;
        }
        catch
        {
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

    private async Task EnhancePromptAsync()
    {
        var textToEnhance = string.IsNullOrWhiteSpace(OutputText) ? PromptText : OutputText;
        if (string.IsNullOrWhiteSpace(textToEnhance))
        {
            StatusText = "Generate a prompt first.";
            return;
        }

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
                OriginalPrompt = PromptText,
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

        if (_generationInProgress)
        {
            StatusText = "Generation already in progress.";
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

        try
        {
            _generationInProgress = true;
            var result = await RunGenerationPreviewAsync(parametersList, prompt, "Generated", Workflow, owner, "Generating images...", allowLongPrompts: false);
            if (result.Saved == true)
            {
                var entry = BuildHistoryEntryForGeneration(
                    PromptText ?? string.Empty,
                    prompt,
                    SelectedTemplate?.Name,
                    SelectedModel ?? "",
                    SelectedModel,
                    Workflow,
                    result.Images);
                _historyManager.AddEntry(entry);
            }
            ApplyGenerationResultStatus(result, "Selected images saved to history.", StatusImagesDiscarded);
        }
        catch (Exception ex)
        {
            StatusText = $"Image generation failed: {ex.Message}";
        }
        finally
        {
            _generationInProgress = false;
        }
    }

    private async Task ShowSettingsAsync(Window? owner)
    {
        await ShowSettingsAsync(owner, null);
    }

    private async Task ShowSettingsAsync(Window? owner, string? sectionKey)
    {
        var vm = new SettingsViewModel(_settingsService, _ollamaClient, _notifications, _imageCacheService);
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
        var win = new Views.AllImagesWindow(vm);
        win.Show(resolved);
        return Task.CompletedTask;
    }

    private Task ShowAnalyticsStudioAsync(Window? owner)
    {
        var resolved = GetOwnerWindow(owner) ?? new Window();
        var vm = new AnalyticsStudioViewModel(_historyManager, _templateService, Workflow, _aestheticScoringService, _settingsService, _imageCacheService, _historyIndexService);
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
        vm.ViewDetailsRequested = async (entry, image, bitmap) =>
        {
            ShowHistoryImageDetailsWindow(entry, image, bitmap, window);
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

    private void ShowHistoryImageDetailsWindow(HistoryEntry entry, HistoryImage image, Bitmap bitmap, Window owner)
    {
        HistoryImageDetailPresenter.Show(
            entry,
            image,
            bitmap,
            owner,
            _historyManager,
            _historyIndexService,
            _imageCacheService,
            (e, img) => UpscaleImageFromHistoryAsync(e, img, owner));
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

    private async Task ShowFavoritesAsync(Window? owner)
    {
        var vm = new FavoritesViewerViewModel(_historyManager, _imageCacheService);
        var win = new Views.FavoritesViewerWindow { DataContext = vm };
        win.Show(GetOwnerWindow(owner) ?? new Window());
        StatusText = "Favorite images viewer closed.";
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

    private async Task ShowSystemPromptsAsync(Window? arg)
    {
        var vm = new SystemPromptEditorViewModel(_settingsService);
        var win = new Views.SystemPromptEditorWindow { DataContext = vm };
        var resolved = GetOwnerWindow(arg) ?? new Window();
        win.Closed += (_, __) =>
        {
            StatusText = vm.DialogResult == true ? "System prompts saved." : "System prompt editor closed.";
        };
        win.Show(resolved);
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
        var vm = new PngMetadataViewerViewModel(historyManager);
        vm.GenerateMergedRequested = GenerateFromMergedPngAsync;
        vm.GenerateGraphReplayRequested = GenerateFromPngGraphAsync;
        vm.BuildGenerationGraphJsonAsync = BuildGenerationGraphJsonAsync;
        vm.ShowJsonDiffRequested = ShowJsonDiffAsync;
        var win = new Views.PngMetadataViewerWindow(vm);
        var resolved = GetOwnerWindow(owner) ?? new Window();
        win.Show(resolved);
        await Task.CompletedTask;
    }

    public async Task GenerateFromMergedPngAsync(PngMergedGenerationRequest request, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        if (_generationInProgress)
        {
            StatusText = "Generation already in progress.";
            return;
        }

        _generationInProgress = true;
        try
        {
            var prompt = string.IsNullOrWhiteSpace(request.Prompt) ? request.Parameters.Prompt : request.Prompt;
            await ResolveInvokeModelsAsync(request.Parameters);
            var parametersList = new List<InvokeAIGenerationParams> { request.Parameters };
            var workflow = !string.IsNullOrWhiteSpace(request.Workflow) ? request.Workflow : Workflow;

            var result = await RunGenerationPreviewAsync(
                parametersList,
                prompt,
                request.PromptType,
                workflow,
                owner,
                "Generating images...",
                allowLongPrompts: true);

            if (request.SaveToHistory && result.Saved == true)
            {
                if (request.TargetEntry != null && !request.CreateNewEntryOnSave)
                {
                    AppendImagesToEntry(request.TargetEntry.Id, result.Images);
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
                        result.Images);
                    _historyManager.AddEntry(entry);
                    StatusText = "Saved merged images to new history entry.";
                }
            }
            else if (!request.SaveToHistory)
            {
                StatusText = "Merged generation complete (not saved).";
            }
            else
            {
                StatusText = "Merged generation discarded.";
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Merged generation failed: {ex.Message}";
        }
        finally
        {
            _generationInProgress = false;
        }
    }

    public async Task GenerateFromPngGraphAsync(PngGraphReplayRequest request, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        if (_generationInProgress)
        {
            StatusText = "Generation already in progress.";
            return;
        }

        _generationInProgress = true;
        try
        {
            var workflow = !string.IsNullOrWhiteSpace(request.Workflow) ? request.Workflow : Workflow;
            var prompt = string.IsNullOrWhiteSpace(request.Prompt) ? request.Parameters?.Prompt ?? string.Empty : request.Prompt;
            var result = await RunGraphReplayPreviewAsync(
                request.Graph,
                request.Parameters,
                prompt,
                request.PromptType,
                workflow,
                owner,
                "Replaying PNG graph...");

            var shouldPersist = result.Saved == true && (request.SaveToHistory || request.TargetEntry != null || request.CreateNewEntryOnSave);
            if (shouldPersist)
            {
                if (request.TargetEntry != null && !request.CreateNewEntryOnSave)
                {
                    AppendImagesToEntry(request.TargetEntry.Id, result.Images);
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
                        result.Images);
                    _historyManager.AddEntry(entry);
                    StatusText = "Saved replayed image to new history entry.";
                }
            }
            else if (!request.SaveToHistory)
            {
                StatusText = "Replay complete (not saved).";
            }
            else
            {
                StatusText = "Replay discarded.";
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Replay failed: {ex.Message}";
        }
        finally
        {
            _generationInProgress = false;
        }
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
        string statusText)
    {
        var savedImages = new List<HistoryImage>();
        var previewVm = new MultiImagePreviewViewModel();
        previewVm.InitializePlaceholders(1);
        previewVm.StatusText = statusText;
        previewVm.OnSaveSlot = async slot =>
        {
            savedImages.Add(new HistoryImage
            {
                ImageBytes = slot.ImageBytes,
                GenerationParams = parameters,
                GenerationParamsJson = parameters != null ? JsonSerializer.Serialize(parameters) : null,
                GenerationGraphJson = slot.GenerationGraphJson,
                Prompt = prompt,
                PromptType = promptType,
                Workflow = workflow,
                IsFavorite = slot.IsFavorite
            });
        };
        ConfigurePreviewCommands(previewVm);
        var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);
        _activeGenerationCts = cts;
        previewVm.OnEditAndRegenerate = async slot => await EditAndRegenerateSlotAsync(slot, preview);
        StatusText = statusText;

        try
        {
            var slot = previewVm.Slots.First();
            slot.GenerationParams = parameters;
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

            if (!cts.IsCancellationRequested)
            {
                previewVm.SetImage(0, result.ImageBytes);
                slot.IsLoading = false;
            }
        }
        catch (OperationCanceledException)
        {
            previewVm.StatusText = StatusGenerationCancelled;
            cts.Cancel();
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
        var saveResult = await saveTask;
        return new GenerationPreviewResult(saveResult, savedImages);
    }

    private void ApplyReplaySlotMetadata(ImageSlotViewModel slot, InvokeAIGenerationParams? parameters, JsonObject graph)
    {
        if (parameters != null)
        {
            slot.ModelUsed = parameters.Model?.Name ?? "";
            slot.Seed = FormatSeedLabel(parameters);
            slot.Size = $"{parameters.Width}x{parameters.Height}";
            slot.LoraLabel = FormatLoraLabel(parameters);
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
        if (NormalizeBool(a.L2iFp32, true) != NormalizeBool(b.L2iFp32, true)) return false;
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
        return string.IsNullOrWhiteSpace(value) ? "fp32" : value.Trim();
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

    private async Task ShowModelStatsAsync(Window? owner)
    {
        var vm = new ModelStatsViewModel(_historyManager);
        var win = new Views.ModelStatsWindow { DataContext = vm };
        var resolved = GetOwnerWindow(owner) ?? new Window();
        win.Show(resolved);
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
        var vm = new WildcardManagerViewModel(_wildcardService);
        var win = new Views.WildcardManagerWindow(vm);
        if (!string.IsNullOrWhiteSpace(wildcardName))
        {
            win.SelectWildcardOnOpen(wildcardName);
        }
        var resolved = GetOwnerWindow(owner) ?? new Window();
        win.Show(resolved);
        await Task.CompletedTask;
    }

    private async Task RegenerateFromHistoryAsync(HistoryEntry entry, HistoryImage? image, string? promptOverride, string? promptTypeOverride, Window? owner)
    {
        if (_generationInProgress)
        {
            StatusText = "Generation already in progress.";
            return;
        }

        await GenerateFromHistoryAsync(entry, image, promptOverride, promptTypeOverride, owner, applyModelFromSource: true, configureVm: null);
    }

    private async Task GenerateNewFromHistoryAsync(HistoryEntry entry, HistoryImage? image, string? promptOverride, string? promptTypeOverride, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        if (_generationInProgress)
        {
            StatusText = "Generation already in progress.";
            return;
        }

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
            var result = await RunGenerationPreviewAsync(parametersList, prompt, resolvedPromptType, workflow, owner, "Generating images...", allowLongPrompts: true);
            if (result.Saved == true)
            {
                if (appendToExisting)
                {
                    AppendImagesToEntry(entry.Id, result.Images);
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
                        result.Images);
                    _historyManager.AddEntry(newEntry);
                }
            }
            ApplyGenerationResultStatus(result, appendToExisting ? "Selected images saved to history entry." : "Selected images saved to history.", StatusImagesDiscarded);
        }
        catch (Exception ex)
        {
            StatusText = $"Image generation failed: {ex.Message}";
        }
        finally
        {
            _generationInProgress = false;
        }
    }

    private async Task GenerateSeedVariationsFromHistoryAsync(HistoryEntry entry, HistoryImage? image, Window? owner)
    {
        await GenerateFromHistoryAsync(entry, image, null, image?.PromptType, owner, applyModelFromSource: true, configureVm: vm =>
        {
            vm.UseRandomSeed = true;
            vm.NumImages = Math.Max(vm.NumImages, 4);
        });
    }

    private async Task GenerateLoraVariationsFromHistoryAsync(HistoryEntry entry, HistoryImage? image, Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        if (_generationInProgress)
        {
            StatusText = "Generation already in progress.";
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

            var savedImages = new List<HistoryImage>();
            var workflow = entry.Workflow ?? Workflow;
            var result = await RunGenerationPreviewAsync(parametersList, prompt, "LoRA Permutation", workflow, owner, "Generating LoRA permutations...", allowLongPrompts: true);
            if (result.Saved == true)
            {
                var newEntry = BuildHistoryEntryForGeneration(
                    entry.OriginalPrompt ?? string.Empty,
                    prompt,
                    entry.TemplateName,
                    entry.OllamaModel ?? "",
                    entry.InvokeAIModel,
                    workflow,
                    result.Images);
                _historyManager.AddEntry(newEntry);
            }
            ApplyGenerationResultStatus(result, "Selected images saved to history.", StatusImagesDiscarded);
        }
        catch (Exception ex)
        {
            StatusText = $"LoRA permutations failed: {ex.Message}";
        }
        finally
        {
            _generationInProgress = false;
        }
    }

    private async Task GenerateVariationsFromSlotAsync(ImageSlotViewModel slot, bool seedVariations)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        if (_generationInProgress)
        {
            StatusText = "Generation already in progress.";
            return;
        }

        var baseParams = slot.GenerationParams;
        if (baseParams == null)
        {
            StatusText = "No generation parameters available for variations.";
            return;
        }

        _generationInProgress = true;
        try
        {
            var prompt = ResolvePromptForSlot(baseParams, PromptText);
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
            if (seedVariations)
            {
                dialogVm.NumImages = Math.Max(dialogVm.NumImages, 4);
            }
            else
            {
                dialogVm.NumImages = Math.Max(dialogVm.NumImages, 3);
            }

            var (ok, parametersList) = await ShowImageGenerationDialogAsync(dialogVm, GetOwnerWindow(null));
            if (!ok || parametersList == null || parametersList.Count == 0)
            {
                StatusText = "Image generation cancelled.";
                return;
            }

            var result = await RunGenerationPreviewAsync(parametersList, prompt, "Generated", Workflow, null, "Generating images...", allowLongPrompts: true);
            if (result.Saved == true)
            {
                var entry = BuildHistoryEntryForGeneration(
                    PromptText ?? string.Empty,
                    prompt,
                    SelectedTemplate?.Name,
                    SelectedModel ?? "",
                    SelectedModel,
                    Workflow,
                    result.Images);
                _historyManager.AddEntry(entry);
            }
            ApplyGenerationResultStatus(result, "Selected images saved to history.", StatusImagesDiscarded);
        }
        catch (Exception ex)
        {
            StatusText = $"Image generation failed: {ex.Message}";
        }
        finally
        {
            _generationInProgress = false;
        }
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
            previewVm.Slots.Insert(insertIndex, newSlot);
            insertIndex++;
            counter++;

            jobs.Add((p, newSlot));
        }

        previewVm.StatusText = "Generating LoRA permutations...";
        if (previewVm.GenerationToken == null)
        {
            previewVm.GenerationToken = new CancellationTokenSource();
        }
            await GenerateImagesForSlotsAsync(jobs, previewVm, previewVm.GenerationToken, allowLongPrompts: true);
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

        if (_generationInProgress)
        {
            StatusText = "Generation already in progress.";
            return;
        }

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
            GenerationPreviewResult result;
            if (!string.IsNullOrWhiteSpace(graphJson) &&
                graphParams != null &&
                parametersList.Count == 1 &&
                AreParamsEquivalent(parametersList[0], graphParams))
            {
                var graphObj = JsonNode.Parse(graphJson) as JsonObject;
                if (graphObj == null)
                {
                    result = await RunGenerationPreviewAsync(parametersList, prompt, promptType, workflow, owner, "Generating images...", allowLongPrompts: baseParams != null);
                }
                else
                {
                    result = await RunGraphReplayPreviewAsync(
                        graphObj,
                        parametersList[0],
                        prompt,
                        promptType,
                        workflow,
                        owner,
                        "Replaying exact graph...");
                }
            }
            else
            {
                result = await RunGenerationPreviewAsync(parametersList, prompt, promptType, workflow, owner, "Generating images...", allowLongPrompts: baseParams != null);
            }
            if (result.Saved == true)
            {
                AppendImagesToEntry(entry.Id, result.Images);
            }
            ApplyGenerationResultStatus(result, "Selected images saved to history entry.", StatusImagesDiscarded);
        }
            catch (Exception ex)
            {
                StatusText = $"Image generation failed: {ex.Message}";
            }
        finally
        {
            _generationInProgress = false;
        }
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
        var win = new Views.EnhancementResultWindow(vm);
        var resolvedOwner = GetOwnerWindow(owner) ?? new Window();
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
        if (_generationInProgress)
        {
            StatusText = "Generation already in progress.";
            return;
        }
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
            previewVm.OnSaveSlot = async slot =>
            {
                var index = previewVm.Slots.IndexOf(slot);
                if (index < 0 || index >= paramList.Count) return;
                var (p, key) = paramList[index];
                _historyManager.AppendImages(entry.Id, new[]
                {
                    new HistoryImage
                    {
                        ImageBytes = slot.ImageBytes,
                        GenerationParams = p,
                        GenerationParamsJson = p != null ? JsonSerializer.Serialize(p) : null,
                        Prompt = p?.Prompt ?? string.Empty,
                        PromptType = $"Variation:{key}",
                        Workflow = entry.Workflow,
                        IsFavorite = slot.IsFavorite
                    }
                });
            };
            ConfigurePreviewCommands(previewVm);

            var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);
            previewVm.OnEditAndRegenerate = async slot => await EditAndRegenerateSlotAsync(slot, preview);
            await GenerateImagesAsync(paramList.Select(p => p.param).ToList(), previewVm, cts, allowLongPrompts: false);

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

        previewVm.OnSaveSlot = async slot =>
        {
            if (slot.ImageBytes == null) return;
            var slotIndex = previewVm.Slots.IndexOf(slot);
            if (slotIndex < 0 || slotIndex >= jobs.Count) return;
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
                UpscaleSourceImagePath = image.ImagePath
            };

            _historyManager.AppendImages(entry.Id, new[] { newImage });
            await Task.CompletedTask;
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
        var dialog = new Views.ImageGenerationDialog(dialogVm);
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
    }

    private sealed record GenerationPreviewResult(bool? Saved, List<HistoryImage> Images);

    private async Task<GenerationPreviewResult> RunGenerationPreviewAsync(
        IReadOnlyList<InvokeAIGenerationParams> parametersList,
        string prompt,
        string promptType,
        string workflow,
        Window? owner,
        string statusText,
        bool allowLongPrompts)
    {
        var savedImages = new List<HistoryImage>();
        var previewVm = new MultiImagePreviewViewModel();
        previewVm.InitializePlaceholders(parametersList.Count);
        previewVm.StatusText = statusText;
        previewVm.OnSaveSlot = async slot =>
        {
            savedImages.Add(new HistoryImage
            {
                ImageBytes = slot.ImageBytes,
                GenerationParams = slot.GenerationParams,
                GenerationParamsJson = slot.GenerationParams != null ? JsonSerializer.Serialize(slot.GenerationParams) : null,
                Prompt = prompt,
                PromptType = promptType,
                Workflow = workflow,
                IsFavorite = slot.IsFavorite
            });
        };
        ConfigurePreviewCommands(previewVm);
        var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);
        _activeGenerationCts = cts;
        previewVm.OnEditAndRegenerate = async slot => await EditAndRegenerateSlotAsync(slot, preview);
        StatusText = statusText;

        try
        {
            await GenerateImagesAsync(parametersList, previewVm, cts, allowLongPrompts);
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
        previewVm.OnGenerateSeedVariations = async slot => await GenerateVariationsFromSlotAsync(slot, true);
        previewVm.OnGenerateLoraVariations = async slot => await GenerateLoraPermutationsFromSlotAsync(slot, previewVm);
    }

    private async Task<List<List<LoraParameter>>?> ShowLoraPermutationDialogAsync(InvokeAIGenerationParams baseParams, Window? owner)
    {
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

    private async Task GenerateImagesAsync(IReadOnlyList<InvokeAIGenerationParams> parametersList, MultiImagePreviewViewModel previewVm, CancellationTokenSource cts, bool allowLongPrompts)
    {
        if (!ValidateGenerationParams(parametersList, allowLongPrompts, out var invalidMessage, out var isWarning))
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
        // Pre-populate slot metadata so users can see model/seed/size while images are generating.
        for (int i = 0; i < parametersList.Count && i < previewVm.Slots.Count; i++)
        {
            var param = parametersList[i];
            var slot = previewVm.Slots[i];
            slot.GenerationParams = param;
            slot.ModelUsed = param.Model?.Name ?? "";
            slot.Seed = FormatSeedLabel(param);
            slot.Size = $"{param.Width}x{param.Height}";
            slot.LoraLabel = FormatLoraLabel(param);
        }

        // Group by model to avoid loading multiple models at once; clear cache between groups if enabled.
        var order = new List<string>();
        var grouped = new Dictionary<string, List<(InvokeAIGenerationParams param, int index)>>(StringComparer.OrdinalIgnoreCase);
        for (int i = 0; i < parametersList.Count; i++)
        {
            var param = parametersList[i];
            var key = param.Model?.Name ?? $"__model_{i}";
            if (!grouped.TryGetValue(key, out var list))
            {
                list = new List<(InvokeAIGenerationParams, int)>();
                grouped[key] = list;
                order.Add(key);
            }
            list.Add((param, i));
        }

        foreach (var key in order)
        {
            if (cts.IsCancellationRequested) break;
            foreach (var (param, index) in grouped[key])
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
                    if (result.GenerationParams?.Vae?.Name is { Length: > 0 } vaeName)
                    {
                        param.VaeUsedName = vaeName;
                    }
                    if (cts.IsCancellationRequested) break;
                    previewVm.SetImage(index, result.ImageBytes);
                    var slot = previewVm.Slots[index];
                    slot.GenerationParams = param;
                    slot.ModelUsed = param.Model?.Name ?? "";
                    slot.Seed = FormatSeedLabel(param);
                    slot.Size = $"{param.Width}x{param.Height}";
                    slot.LoraLabel = FormatLoraLabel(param);
                }
                catch (OperationCanceledException)
                {
                    StatusText = "Image generation cancelled.";
                    cts.Cancel();
                    break;
                }
            }

            if (cts.IsCancellationRequested) break;

            if (_settingsService.Settings.AutoClearInvokeCacheBetweenModels)
            {
                await _invokeAIClient.EmptyModelCacheAsync(cts.Token);
            }
        }
    }

    private async Task GenerateImagesForSlotsAsync(
        IReadOnlyList<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> jobs,
        MultiImagePreviewViewModel previewVm,
        CancellationTokenSource cts,
        bool allowLongPrompts)
    {
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
            slot.GenerationParams = param;
            slot.ModelUsed = param.Model?.Name ?? "";
            slot.Seed = FormatSeedLabel(param);
            slot.Size = $"{param.Width}x{param.Height}";
            slot.LoraLabel = FormatLoraLabel(param);
            slot.IsLoading = true;
        }

        var order = new List<string>();
        var grouped = new Dictionary<string, List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>>(StringComparer.OrdinalIgnoreCase);
        foreach (var job in jobs)
        {
            var key = job.param.Model?.Name ?? $"__model_{order.Count}";
            if (!grouped.TryGetValue(key, out var list))
            {
                list = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
                grouped[key] = list;
                order.Add(key);
            }
            list.Add(job);
        }

        var done = 0;
        foreach (var key in order)
        {
            if (cts.IsCancellationRequested) break;
            foreach (var (param, slot) in grouped[key])
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

                    if (result.GenerationParams?.Vae?.Name is { Length: > 0 } vaeName)
                    {
                        param.VaeUsedName = vaeName;
                    }

                    previewVm.UpdateSlotImage(slot, result.ImageBytes);
                }
                catch (OperationCanceledException)
                {
                    StatusText = "Image generation cancelled.";
                    cts.Cancel();
                    return;
                }
                catch (Exception ex)
                {
                    slot.IsLoading = false;
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Generation failed: {ex.Message}");
                }
                finally
                {
                    done++;
                    previewVm.StatusText = $"Generating {done}/{jobs.Count}...";
                }
            }

            if (cts.IsCancellationRequested) break;

            if (_settingsService.Settings.AutoClearInvokeCacheBetweenModels)
            {
                await _invokeAIClient.EmptyModelCacheAsync(cts.Token);
            }
        }
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
        var baseSeed = p.BaseSeed != 0 ? p.BaseSeed : p.Seed;
        return baseSeed != p.Seed ? $"{p.Seed} (base {baseSeed})" : p.Seed.ToString();
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



    private void CreateMissingWildcard(string? wildcardName)
    {
        if (wildcardName == null) return;
        // In a real scenario, this would pre-fill the WildcardManager window
        // with the wildcardName and a template for new JSON content.
        // For now, we'll just open the manager.
        StatusText = $"Attempted to create missing wildcard: {wildcardName}";
        ShowWildcardManagerCommand.Execute(GetOwnerWindow(null));
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
                vm.Tooltip = _wildcardService.GetWildcardFileContent(segment.OriginalWildcardName);
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
