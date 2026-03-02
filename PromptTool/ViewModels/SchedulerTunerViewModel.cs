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
using PromptTool.Core.Clients;
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Config;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class SchedulerTunerViewModel : ObservableObject
{
    private const string DefaultSfwPromptText =
        "hyper-detailed product photograph of a chrome mechanical wristwatch " +
        "on a textured wooden table, studio lighting, " +
        "fine engraved lettering visible, micro scratches on metal, " +
        "sharp reflections, realistic shadows, " +
        "high clarity, macro photography";
    private const string DefaultNsfwPromptText =
        "tasteful boudoir portrait of a confident adult woman, " +
        "silk robe draped over the shoulders, subtle skin highlights, " +
        "elegant pose by a window with soft moonlight, " +
        "delicate lace details, cinematic lighting, " +
        "shallow depth of field, natural skin texture, " +
        "high detail, soft bokeh, intimate atmosphere";
    private const string DefaultNegativePromptText =
        "blurry, low contrast, oversharpened, flat lighting, " +
        "extra limbs, distorted hands, noisy shadows, washed out colors";

    private readonly InvokeAIClient _invokeAIClient;
    private readonly SettingsService _settingsService;
    private readonly NotificationService? _notifications;
    private readonly AestheticScoringService _aestheticScoringService;
    private readonly ObservableCollection<SchedulerChoice> _allSchedulers = new();
    private readonly ObservableCollection<InvokeAIModel> _allModels = new();
    private readonly Random _rng = new();
    private CancellationTokenSource? _generationCts;
    private readonly List<SchedulerResultItem> _allResults = new();

    [ObservableProperty] private ObservableCollection<string> _modelCategories = new();
    [ObservableProperty] private string _selectedModelCategory = "All";
    [ObservableProperty] private string _modelFilterText = "";
    [ObservableProperty] private ObservableCollection<InvokeAIModel> _models = new();
    [ObservableProperty] private InvokeAIModel? _selectedModel;
    [ObservableProperty] private double _modelDropdownWidth = 260;
    [ObservableProperty] private string _prompt = DefaultSfwPromptText;
    [ObservableProperty] private string _negativePromptText = DefaultNegativePromptText;
    [ObservableProperty] private int _steps;
    [ObservableProperty] private ObservableCollection<int> _stepSweepIntervals = new();
    [ObservableProperty] private int _stepSweepInterval = 5;
    [ObservableProperty] private int _stepSweepCount = 3;
    [ObservableProperty] private int _stepSweepMin = 5;
    [ObservableProperty] private int _stepSweepMax = 80;
    [ObservableProperty] private string _schedulerFilterText = "";
    [ObservableProperty] private ObservableCollection<SchedulerChoice> _schedulers = new();
    [ObservableProperty] private string _schedulerCountText = "Schedulers (0)";
    [ObservableProperty] private ObservableCollection<SchedulerResultItem> _results = new();
    [ObservableProperty] private SchedulerResultItem? _selectedResult;
    [ObservableProperty] private string _statusText = "";
    [ObservableProperty] private bool _isGenerating;
    [ObservableProperty] private bool _canCompare;
    [ObservableProperty] private bool _enableAestheticScoring;
    [ObservableProperty] private bool _rankByScore;
    [ObservableProperty] private bool _enableArtifactHeuristics = true;
    [ObservableProperty] private bool _hideBandingRisk;
    [ObservableProperty] private bool _hideOverSmoothRisk;
    [ObservableProperty] private bool _hideWarpRisk;
    [ObservableProperty] private string _preferredSchedulerLabel = "";
    [ObservableProperty] private bool _hasPreferredScheduler;
    [ObservableProperty] private string _preferredSchedulerTooltip = "";

    public IAsyncRelayCommand GenerateAllCommand { get; }
    public IAsyncRelayCommand GenerateSelectedCommand { get; }
    public IRelayCommand ClearResultsCommand { get; }
    public IRelayCommand CancelGenerationCommand { get; }
    public IRelayCommand<SchedulerResultItem> ApplyResultSchedulerCommand { get; }
    public IRelayCommand<SchedulerResultItem> SeedSweepCommand { get; }
    public IRelayCommand<SchedulerResultItem> StepsSweepCommand { get; }
    public IRelayCommand SelectAllSchedulersCommand { get; }
    public IRelayCommand SelectNoneSchedulersCommand { get; }
    public IRelayCommand InvertSchedulersCommand { get; }

    public Func<string, Task<bool>>? ConfirmDownloadAsync { get; set; }
    public Action<string>? ScoreStatus { get; set; }
    public event Action<SchedulerSeedSweepRequest>? SeedSweepRequested;
    public event Action<SchedulerStepsSweepRequest>? StepsSweepRequested;

    public SchedulerTunerViewModel(
        InvokeAIClient invokeAIClient,
        SettingsService settingsService,
        AestheticScoringService aestheticScoringService,
        NotificationService? notifications = null)
    {
        _invokeAIClient = invokeAIClient;
        _settingsService = settingsService;
        _notifications = notifications;
        _aestheticScoringService = aestheticScoringService;

        GenerateAllCommand = new AsyncRelayCommand(() => GenerateAsync(selectedOnly: false), () => !IsGenerating);
        GenerateSelectedCommand = new AsyncRelayCommand(() => GenerateAsync(selectedOnly: true), () => !IsGenerating);
        ClearResultsCommand = new RelayCommand(ClearResults);
        CancelGenerationCommand = new RelayCommand(CancelGeneration, () => IsGenerating);
        ApplyResultSchedulerCommand = new RelayCommand<SchedulerResultItem>(ApplyResultScheduler);
        SeedSweepCommand = new RelayCommand<SchedulerResultItem>(RequestSeedSweep);
        StepsSweepCommand = new RelayCommand<SchedulerResultItem>(RequestStepsSweep);
        SelectAllSchedulersCommand = new RelayCommand(SelectAllSchedulers);
        SelectNoneSchedulersCommand = new RelayCommand(SelectNoneSchedulers);
        InvertSchedulersCommand = new RelayCommand(InvertSchedulers);

        StepSweepIntervals = new ObservableCollection<int>(new[] { 5, 10 });
        ApplyWorkflowDefaults();
        _ = LoadAsync();
    }

    partial void OnIsGeneratingChanged(bool value)
    {
        GenerateAllCommand.NotifyCanExecuteChanged();
        GenerateSelectedCommand.NotifyCanExecuteChanged();
        CancelGenerationCommand.NotifyCanExecuteChanged();
    }

    partial void OnSchedulerFilterTextChanged(string value)
    {
        ApplySchedulerFilter();
    }

    partial void OnModelFilterTextChanged(string value)
    {
        ApplyModelFilter();
    }

    partial void OnSelectedModelCategoryChanged(string value)
    {
        ApplyModelFilter();
    }

    partial void OnEnableAestheticScoringChanged(bool value)
    {
        _ = ScorePendingResultsAsync();
    }

    partial void OnRankByScoreChanged(bool value)
    {
        ApplyResultOrdering();
    }

    partial void OnEnableArtifactHeuristicsChanged(bool value)
    {
        if (value)
        {
            ComputeArtifactFlagsForResults();
        }
        ApplyResultFilters();
    }

    partial void OnHideBandingRiskChanged(bool value)
    {
        ApplyResultFilters();
    }

    partial void OnHideOverSmoothRiskChanged(bool value)
    {
        ApplyResultFilters();
    }

    partial void OnHideWarpRiskChanged(bool value)
    {
        ApplyResultFilters();
    }

    partial void OnSelectedModelChanged(InvokeAIModel? value)
    {
        UpdateDefaultsFromModel(value);
        UpdatePreferredSchedulerInfo(value);
    }

    private async Task LoadAsync()
    {
        StatusText = "Loading models...";
        if (!await _invokeAIClient.IsReachableAsync())
        {
            StatusText = "InvokeAI is offline.";
            return;
        }

        var baseModelTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "sdxl",
            "sd-1.5"
        };
        if (!string.IsNullOrWhiteSpace(_settingsService.Settings.DefaultBaseModelType))
        {
            baseModelTypes.Add(_settingsService.Settings.DefaultBaseModelType);
        }
        foreach (var key in _settingsService.Settings.GenerationDefaults.Keys)
        {
            if (!string.IsNullOrWhiteSpace(key))
            {
                baseModelTypes.Add(key);
            }
        }

        var modelLookup = new Dictionary<string, InvokeAIModel>(StringComparer.OrdinalIgnoreCase);
        foreach (var baseModel in baseModelTypes)
        {
            var batch = await _invokeAIClient.GetModelsAsync(baseModel: baseModel, modelType: "main");
            foreach (var model in batch)
            {
                var key = string.IsNullOrWhiteSpace(model.Key) ? model.Name : model.Key;
                if (string.IsNullOrWhiteSpace(key))
                {
                    continue;
                }
                modelLookup[key] = model;
            }
        }

        if (modelLookup.Count == 0)
        {
            var models = await _invokeAIClient.GetModelsAsync(modelType: "main");
            foreach (var model in models)
            {
                var key = string.IsNullOrWhiteSpace(model.Key) ? model.Name : model.Key;
                if (string.IsNullOrWhiteSpace(key))
                {
                    continue;
                }
                modelLookup[key] = model;
            }
        }

        _allModels.Clear();
        foreach (var model in modelLookup.Values.OrderBy(m => m.Name, StringComparer.OrdinalIgnoreCase))
        {
            _allModels.Add(model);
        }
        ModelDropdownWidth = CalculateDropdownWidth(_allModels.Select(m => m.Name), 260, 420);
        BuildModelCategories();
        ApplyModelFilter();

        StatusText = "Loading schedulers...";
        var schedulers = await _invokeAIClient.GetSchedulersAsync();
        _allSchedulers.Clear();
        foreach (var sched in schedulers)
        {
            _allSchedulers.Add(new SchedulerChoice(sched));
        }
        ApplySchedulerFilter();
        StatusText = "";
    }

    private void ApplyWorkflowDefaults()
    {
        var workflow = _settingsService.Settings.Workflow ?? "sfw";
        Prompt = string.Equals(workflow, "nsfw", StringComparison.OrdinalIgnoreCase)
            ? DefaultNsfwPromptText
            : DefaultSfwPromptText;
    }

    private void BuildModelCategories()
    {
        ModelCategories.Clear();
        ModelCategories.Add("All");

        foreach (var baseModel in _allModels
                     .Select(m => m.Base)
                     .Where(b => !string.IsNullOrWhiteSpace(b))
                     .Distinct(StringComparer.OrdinalIgnoreCase)
                     .OrderBy(b => b, StringComparer.OrdinalIgnoreCase))
        {
            ModelCategories.Add(baseModel!);
        }

        var preferred = _settingsService.Settings.DefaultBaseModelType;
        if (!string.IsNullOrWhiteSpace(preferred) &&
            ModelCategories.Contains(preferred) &&
            !string.Equals(SelectedModelCategory, preferred, StringComparison.OrdinalIgnoreCase))
        {
            SelectedModelCategory = preferred;
        }
        else if (!ModelCategories.Contains(SelectedModelCategory))
        {
            SelectedModelCategory = "All";
        }
    }

    private void ApplyModelFilter()
    {
        var category = SelectedModelCategory;
        var filter = (ModelFilterText ?? string.Empty).Trim();
        IEnumerable<InvokeAIModel> filtered = _allModels;
        if (!string.IsNullOrWhiteSpace(category) &&
            !string.Equals(category, "All", StringComparison.OrdinalIgnoreCase))
        {
            filtered = filtered.Where(m => string.Equals(m.Base, category, StringComparison.OrdinalIgnoreCase));
        }

        if (!string.IsNullOrWhiteSpace(filter))
        {
            filtered = filtered.Where(m => m.Name.Contains(filter, StringComparison.OrdinalIgnoreCase));
        }

        var list = filtered.OrderBy(m => m.Name, StringComparer.OrdinalIgnoreCase).ToList();
        Models = new ObservableCollection<InvokeAIModel>(list);

        if (SelectedModel != null &&
            list.Any(m => string.Equals(m.Key, SelectedModel.Key, StringComparison.OrdinalIgnoreCase)))
        {
            return;
        }

        SelectedModel = Models.FirstOrDefault();
    }

    private void ApplySchedulerFilter()
    {
        var filter = (SchedulerFilterText ?? string.Empty).Trim();
        var list = string.IsNullOrWhiteSpace(filter)
            ? _allSchedulers.ToList()
            : _allSchedulers
                .Where(s => s.Name.Contains(filter, StringComparison.OrdinalIgnoreCase))
                .ToList();

        Schedulers = new ObservableCollection<SchedulerChoice>(list);
        SchedulerCountText = $"Schedulers ({Schedulers.Count})";
    }

    private void UpdateDefaultsFromModel(InvokeAIModel? model)
    {
        if (model == null) return;

        var baseModel = model.Base ?? _settingsService.Settings.DefaultBaseModelType ?? "sdxl";
        var generationDefaults = _settingsService.Settings.GenerationDefaults.TryGetValue(baseModel, out var d) ? d : null;
        var modelDefaults = _settingsService.InvokeAIModelDefaults
            .FirstOrDefault(m => string.Equals(m.ModelName, model.Name, StringComparison.OrdinalIgnoreCase));

        var resolvedSteps = modelDefaults?.Steps > 0
            ? modelDefaults.Steps
            : generationDefaults?.Steps ?? _settingsService.Settings.DefaultSteps;

        Steps = resolvedSteps;
    }

    private void UpdatePreferredSchedulerInfo(InvokeAIModel? model)
    {
        if (model == null)
        {
            HasPreferredScheduler = false;
            PreferredSchedulerLabel = string.Empty;
            PreferredSchedulerTooltip = string.Empty;
            UpdatePreferredSchedulerFlags();
            return;
        }

        var modelDefaults = _settingsService.InvokeAIModelDefaults
            .FirstOrDefault(m => string.Equals(m.ModelName, model.Name, StringComparison.OrdinalIgnoreCase));
        var scheduler = modelDefaults?.Sampler;
        if (string.IsNullOrWhiteSpace(scheduler) || scheduler == "(None)")
        {
            HasPreferredScheduler = false;
            PreferredSchedulerLabel = string.Empty;
            PreferredSchedulerTooltip = string.Empty;
            UpdatePreferredSchedulerFlags();
            return;
        }

        var steps = modelDefaults?.Steps > 0 ? modelDefaults.Steps : (int?)null;
        var displayScheduler = ImageGenerationOptionsViewModel.NormalizeSchedulerDisplay(scheduler);
        HasPreferredScheduler = true;
        PreferredSchedulerLabel = steps.HasValue
            ? $"Preferred scheduler: {displayScheduler} ({steps} steps)"
            : $"Preferred scheduler: {displayScheduler}";
        PreferredSchedulerTooltip = steps.HasValue
            ? $"Model default scheduler: {displayScheduler}, steps {steps}"
            : $"Model default scheduler: {displayScheduler}";

        UpdatePreferredSchedulerFlags();
    }

    private async Task GenerateAsync(bool selectedOnly)
    {
        if (SelectedModel == null)
        {
            StatusText = "Select a model first.";
            return;
        }

        var choices = selectedOnly
            ? _allSchedulers.Where(s => s.IsSelected).ToList()
            : _allSchedulers.ToList();

        if (choices.Count == 0)
        {
            StatusText = "Select at least one scheduler.";
            return;
        }

        Results.Clear();
        _allResults.Clear();
        _generationCts?.Cancel();
        _generationCts?.Dispose();
        _generationCts = new CancellationTokenSource();
        var token = _generationCts.Token;

        var baseParams = BuildBaseParams(SelectedModel);
        var seed = _rng.Next(1, int.MaxValue);
        baseParams.Seed = seed;
        baseParams.UsedRandomSeed = false;
        baseParams.BaseSeed = seed;

        foreach (var choice in choices)
        {
            var p = CloneParams(baseParams);
            p.Scheduler = choice.Name;
            var slot = new ImageSlotViewModel
            {
                Label = choice.Name,
                IsLoading = true,
                IsSelected = false,
                ModelUsed = SelectedModel.Name,
                Seed = seed.ToString(),
                Size = $"{p.Width}x{p.Height}",
                LoraLabel = ""
            };
            var resultItem = new SchedulerResultItem(choice.Name, p, slot);
            _allResults.Add(resultItem);
            Results.Add(resultItem);
        }
        UpdatePreferredSchedulerFlags();

        IsGenerating = true;
        StatusText = "Generating scheduler samples...";
        try
        {
            var resultsSnapshot = _allResults.ToList();
            foreach (var result in resultsSnapshot)
            {
                if (token.IsCancellationRequested)
                {
                    break;
                }
                var p = result.Parameters;
                if (p == null) continue;
                try
                {
                    var genResult = await _invokeAIClient.GenerateImageAsync(p, token);
                    result.Slot.IsLoading = false;
                    result.Slot.ImageBytes = genResult.ImageBytes;
                    using var ms = new System.IO.MemoryStream(genResult.ImageBytes);
                    result.Slot.Image = new Bitmap(ms);
                    result.DurationLabel = FormatDurationLabel(genResult.JobInfo);
                    result.HeuristicScore = ScoringHelper.CalculateScore(result.Slot.Image);
                    if (EnableArtifactHeuristics && result.Slot.Image != null)
                    {
                        var flags = ArtifactHeuristics.Evaluate(result.Slot.Image);
                        result.BandingRisk = flags.BandingRisk;
                        result.OverSmoothRisk = flags.OverSmoothRisk;
                        result.WarpRisk = flags.WarpRisk;
                        result.ArtifactChecked = true;
                    }

                    if (EnableAestheticScoring && result.Slot.ImageBytes != null)
                    {
                        result.AestheticScore = await ScoreAestheticAsync(result.Slot.ImageBytes, token);
                    }
                    UpdateSchedulerStats(result.Scheduler);
                    ApplyResultOrdering();
                    ApplyResultFilters();
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    result.Slot.IsLoading = false;
                    result.Error = ex.Message;
                }
            }
        }
        finally
        {
            IsGenerating = false;
            StatusText = token.IsCancellationRequested ? "Generation cancelled." : "Scheduler samples ready.";
            GenerateAllCommand.NotifyCanExecuteChanged();
            GenerateSelectedCommand.NotifyCanExecuteChanged();
            _generationCts?.Dispose();
            _generationCts = null;
        }
    }

    private void ClearResults()
    {
        _generationCts?.Cancel();
        Results.Clear();
        _allResults.Clear();
        SelectedResult = null;
        StatusText = "Results cleared.";
    }

    private void CancelGeneration()
    {
        if (!IsGenerating) return;
        StatusText = "Cancelling generation...";
        _generationCts?.Cancel();
    }

    private void ApplyResultScheduler(SchedulerResultItem? result)
    {
        if (SelectedModel == null)
        {
            StatusText = "Select a model first.";
            return;
        }
        if (result == null)
        {
            StatusText = "Select a scheduler result to save.";
            return;
        }

        var scheduler = GraphBuilder.NormalizeScheduler(result.Scheduler);
        var defaults = _settingsService.InvokeAIModelDefaults;
        var existing = defaults.FirstOrDefault(d => string.Equals(d.ModelName, SelectedModel.Name, StringComparison.OrdinalIgnoreCase));
        if (existing == null)
        {
            existing = new ModelDefaults
            {
                ModelName = SelectedModel.Name,
                Sampler = scheduler,
                Steps = Steps > 0 ? Steps : 0,
                CfgScale = 0,
                CfgRescaleMultiplier = -1,
                Width = 0,
                Height = 0,
                PositivePromptPrefix = string.Empty,
                NegativePromptPrefix = string.Empty,
                LoraWeight = null
            };
            defaults.Add(existing);
        }
        else
        {
            existing.Sampler = scheduler;
            if (Steps > 0)
            {
                existing.Steps = Steps;
            }
        }
        if (_settingsService.SaveInvokeAIModelDefaults())
        {
            var displayScheduler = ImageGenerationOptionsViewModel.NormalizeSchedulerDisplay(scheduler);
            StatusText = $"Saved scheduler '{displayScheduler}' and steps {Steps} for {SelectedModel.Name}.";
            _notifications?.ShowInfo(
                $"{SelectedModel.Name} default scheduler set to {displayScheduler} with {Steps} steps.",
                "Scheduler Default Saved");
            UpdatePreferredSchedulerInfo(SelectedModel);
        }
        else
        {
            StatusText = "Failed to save scheduler default.";
        }
    }

    private void SelectAllSchedulers()
    {
        foreach (var scheduler in _allSchedulers)
        {
            scheduler.IsSelected = true;
        }
    }

    private void SelectNoneSchedulers()
    {
        foreach (var scheduler in _allSchedulers)
        {
            scheduler.IsSelected = false;
        }
    }

    private void InvertSchedulers()
    {
        foreach (var scheduler in _allSchedulers)
        {
            scheduler.IsSelected = !scheduler.IsSelected;
        }
    }

    private void ApplyResultOrdering()
    {
        if (!_allResults.Any())
        {
            Results = new ObservableCollection<SchedulerResultItem>();
            return;
        }

        IEnumerable<SchedulerResultItem> ordered = _allResults;
        if (RankByScore)
        {
            ordered = ordered
                .OrderByDescending(r => r.AestheticScore ?? r.HeuristicScore ?? double.MinValue)
                .ThenBy(r => r.Scheduler, StringComparer.OrdinalIgnoreCase);
        }

        Results = new ObservableCollection<SchedulerResultItem>(ordered);
        UpdatePreferredSchedulerFlags();
    }

    private void ApplyResultFilters()
    {
        if (!_allResults.Any()) return;

        IEnumerable<SchedulerResultItem> filtered = _allResults;
        if (EnableArtifactHeuristics)
        {
            if (HideBandingRisk)
            {
                filtered = filtered.Where(r => !r.BandingRisk);
            }
            if (HideOverSmoothRisk)
            {
                filtered = filtered.Where(r => !r.OverSmoothRisk);
            }
            if (HideWarpRisk)
            {
                filtered = filtered.Where(r => !r.WarpRisk);
            }
        }

        if (RankByScore)
        {
            filtered = filtered
                .OrderByDescending(r => r.AestheticScore ?? r.HeuristicScore ?? double.MinValue)
                .ThenBy(r => r.Scheduler, StringComparer.OrdinalIgnoreCase);
        }

        Results = new ObservableCollection<SchedulerResultItem>(filtered);
        UpdatePreferredSchedulerFlags();
    }

    private void UpdatePreferredSchedulerFlags()
    {
        if (!_allResults.Any())
        {
            return;
        }

        var preferredRaw = ResolvePreferredSchedulerValue();
        var preferredNorm = !string.IsNullOrWhiteSpace(preferredRaw)
            ? GraphBuilder.NormalizeScheduler(preferredRaw)
            : null;
        foreach (var item in _allResults)
        {
            if (string.IsNullOrWhiteSpace(preferredRaw))
            {
                item.IsPreferred = false;
                continue;
            }

            var itemNorm = GraphBuilder.NormalizeScheduler(item.Scheduler);
            item.IsPreferred = string.Equals(item.Scheduler, preferredRaw, StringComparison.OrdinalIgnoreCase)
                               || (preferredNorm != null && string.Equals(itemNorm, preferredNorm, StringComparison.OrdinalIgnoreCase));
        }
    }

    private string? ResolvePreferredSchedulerValue()
    {
        if (SelectedModel == null) return null;
        var modelDefaults = _settingsService.InvokeAIModelDefaults
            .FirstOrDefault(m => string.Equals(m.ModelName, SelectedModel.Name, StringComparison.OrdinalIgnoreCase));
        var scheduler = modelDefaults?.Sampler;
        if (string.IsNullOrWhiteSpace(scheduler) || scheduler == "(None)") return null;
        return GraphBuilder.NormalizeScheduler(scheduler);
    }

    private void ComputeArtifactFlagsForResults()
    {
        foreach (var result in _allResults)
        {
            if (result.ArtifactChecked) continue;
            if (result.Slot.Image == null) continue;
            var flags = ArtifactHeuristics.Evaluate(result.Slot.Image);
            result.BandingRisk = flags.BandingRisk;
            result.OverSmoothRisk = flags.OverSmoothRisk;
            result.WarpRisk = flags.WarpRisk;
            result.ArtifactChecked = true;
        }
    }

    private async Task ScorePendingResultsAsync()
    {
        if (!EnableAestheticScoring) return;
        if (_generationCts?.IsCancellationRequested == true) return;
        var token = _generationCts?.Token ?? CancellationToken.None;

        foreach (var result in _allResults)
        {
            if (token.IsCancellationRequested) break;
            if (result.AestheticScore.HasValue) continue;
            if (result.Slot.ImageBytes == null) continue;
            result.AestheticScore = await ScoreAestheticAsync(result.Slot.ImageBytes, token);
            UpdateSchedulerStats(result.Scheduler);
        }

        ApplyResultOrdering();
        ApplyResultFilters();
    }

    private async Task<double?> ScoreAestheticAsync(byte[] imageBytes, CancellationToken token)
    {
        var confirm = ConfirmDownloadAsync ?? (_ => Task.FromResult(false));
        var path = Path.Combine(Path.GetTempPath(), $"scheduler_tuner_{Guid.NewGuid():N}.png");
        try
        {
            await File.WriteAllBytesAsync(path, imageBytes, token);
            var result = await _aestheticScoringService.ScoreImageAsync(
                path,
                confirm,
                ScoreStatus,
                null,
                token);
            return result?.Score;
        }
        finally
        {
            try
            {
                if (File.Exists(path)) File.Delete(path);
            }
            catch
            {
                // ignore cleanup failures
            }
        }
    }

    private void UpdateSchedulerStats(string scheduler)
    {
        var scores = _allResults
            .Where(r => string.Equals(r.Scheduler, scheduler, StringComparison.OrdinalIgnoreCase))
            .Select(r => r.AestheticScore ?? r.HeuristicScore)
            .Where(s => s.HasValue)
            .Select(s => s!.Value)
            .ToList();

        if (scores.Count <= 1)
        {
            foreach (var item in _allResults.Where(r => string.Equals(r.Scheduler, scheduler, StringComparison.OrdinalIgnoreCase)))
            {
                item.SchedulerScoreMean = null;
                item.SchedulerScoreStdDev = null;
            }
            return;
        }

        var mean = scores.Average();
        var variance = scores.Sum(s => Math.Pow(s - mean, 2)) / scores.Count;
        var stdDev = Math.Sqrt(variance);

        foreach (var item in _allResults.Where(r => string.Equals(r.Scheduler, scheduler, StringComparison.OrdinalIgnoreCase)))
        {
            item.SchedulerScoreMean = mean;
            item.SchedulerScoreStdDev = stdDev;
        }
    }

    private void RequestSeedSweep(SchedulerResultItem? result)
    {
        if (result?.Parameters == null) return;
        SeedSweepRequested?.Invoke(new SchedulerSeedSweepRequest(
            result.Scheduler,
            result.Parameters,
            EnableAestheticScoring,
            EnableArtifactHeuristics));
    }

    private void RequestStepsSweep(SchedulerResultItem? result)
    {
        if (result?.Parameters == null) return;

        var interval = Math.Max(1, StepSweepInterval);
        var count = Math.Clamp(StepSweepCount, 1, 6);
        var min = Math.Max(1, StepSweepMin);
        var max = Math.Max(min, StepSweepMax);

        StepsSweepRequested?.Invoke(new SchedulerStepsSweepRequest(
            result.Scheduler,
            result.Parameters,
            interval,
            count,
            min,
            max,
            EnableAestheticScoring,
            EnableArtifactHeuristics));
    }

    public InvokeAIClient GetInvokeAIClient() => _invokeAIClient;

    public AestheticScoringService GetAestheticScoringService() => _aestheticScoringService;

    private static string? FormatDurationLabel(GenerationJobInfo? jobInfo)
    {
        if (jobInfo == null) return null;

        var gen = jobInfo.GenerationDurationMs;
        var total = jobInfo.TotalDurationMs;
        if (gen == null && total == null) return null;

        var parts = new List<string>();
        if (gen is > 0)
        {
            parts.Add($"Gen {FormatMs(gen.Value)}");
        }
        if (total is > 0)
        {
            parts.Add($"Total {FormatMs(total.Value)}");
        }
        return parts.Count == 0 ? null : string.Join(" | ", parts);
    }

    private static string FormatMs(int ms)
    {
        if (ms < 1000)
        {
            return $"{ms} ms";
        }
        var seconds = ms / 1000d;
        return $"{seconds:F2}s";
    }

    private static double CalculateDropdownWidth(IEnumerable<string?> items, double minWidth, double maxWidth)
    {
        var maxLen = items.Select(i => i?.Length ?? 0).DefaultIfEmpty(0).Max();
        var width = maxLen * 7.5 + 48;
        return Math.Min(maxWidth, Math.Max(minWidth, width));
    }

    private InvokeAIGenerationParams BuildBaseParams(InvokeAIModel model)
    {
        var baseModel = model.Base ?? _settingsService.Settings.DefaultBaseModelType ?? "sdxl";
        var generationDefaults = _settingsService.Settings.GenerationDefaults.TryGetValue(baseModel, out var d) ? d : null;
        var modelDefaults = _settingsService.InvokeAIModelDefaults
            .FirstOrDefault(m => string.Equals(m.ModelName, model.Name, StringComparison.OrdinalIgnoreCase));

        var promptPrefix = modelDefaults?.PositivePromptPrefix ?? string.Empty;
        var negativePrefix = modelDefaults?.NegativePromptPrefix ?? string.Empty;

        return new InvokeAIGenerationParams
        {
            Prompt = string.Join(" ", new[] { promptPrefix, Prompt }.Where(s => !string.IsNullOrWhiteSpace(s))).Trim(),
            NegativePrompt = string.Join(" ", new[] { negativePrefix, NegativePromptText }.Where(s => !string.IsNullOrWhiteSpace(s))).Trim(),
            BaseModelType = baseModel,
            Steps = Steps > 0 ? Steps : modelDefaults?.Steps > 0 ? modelDefaults.Steps : generationDefaults?.Steps ?? _settingsService.Settings.DefaultSteps,
            CfgScale = modelDefaults?.CfgScale > 0 ? modelDefaults.CfgScale : generationDefaults?.CfgScale ?? _settingsService.Settings.DefaultCfgScale,
            CfgRescaleMultiplier = modelDefaults?.CfgRescaleMultiplier >= 0
                ? modelDefaults.CfgRescaleMultiplier
                : generationDefaults?.CfgRescaleMultiplier ?? _settingsService.Settings.DefaultCfgRescaleMultiplier,
            Width = modelDefaults?.Width > 0 ? modelDefaults.Width : generationDefaults?.Width ?? _settingsService.Settings.DefaultWidth,
            Height = modelDefaults?.Height > 0 ? modelDefaults.Height : generationDefaults?.Height ?? _settingsService.Settings.DefaultHeight,
            SaveToGallery = false,
            Model = model
        };
    }

    private static InvokeAIGenerationParams CloneParams(InvokeAIGenerationParams src)
    {
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
            Model = src.Model,
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
}

public partial class SchedulerChoice : ObservableObject
{
    public string Name { get; }
    public string DisplayName => ImageGenerationOptionsViewModel.NormalizeSchedulerDisplay(Name);

    [ObservableProperty] private bool _isSelected;

    public SchedulerChoice(string name)
    {
        Name = name;
    }
}

public partial class SchedulerResultItem : ObservableObject
{
    public string Scheduler { get; }
    public string DisplayScheduler => ImageGenerationOptionsViewModel.NormalizeSchedulerDisplay(Scheduler);
    public InvokeAIGenerationParams? Parameters { get; }
    public ImageSlotViewModel Slot { get; }

    [ObservableProperty] private string? _error;
    [ObservableProperty] private string? _durationLabel;
    [ObservableProperty] private double? _aestheticScore;
    [ObservableProperty] private double? _heuristicScore;
    [ObservableProperty] private bool _bandingRisk;
    [ObservableProperty] private bool _overSmoothRisk;
    [ObservableProperty] private bool _warpRisk;
    [ObservableProperty] private bool _artifactChecked;
    [ObservableProperty] private bool _isPreferred;
    [ObservableProperty] private double? _schedulerScoreMean;
    [ObservableProperty] private double? _schedulerScoreStdDev;

    public bool HasAestheticScore => AestheticScore.HasValue;
    public bool HasHeuristicScore => HeuristicScore.HasValue;
    public bool HasSchedulerStats => SchedulerScoreMean.HasValue && SchedulerScoreStdDev.HasValue;

    public string AestheticScoreLabel => AestheticScore.HasValue ? $"Aesthetic {AestheticScore:0.00}" : string.Empty;
    public string HeuristicScoreLabel => HeuristicScore.HasValue ? $"Heuristic {HeuristicScore:0.0}" : string.Empty;
    public string SchedulerStatsLabel => HasSchedulerStats ? $"Avg {SchedulerScoreMean:0.00} | Std Dev {SchedulerScoreStdDev:0.00}" : string.Empty;

    public SchedulerResultItem(string scheduler, InvokeAIGenerationParams? parameters, ImageSlotViewModel slot)
    {
        Scheduler = scheduler;
        Parameters = parameters;
        Slot = slot;
    }

    partial void OnAestheticScoreChanged(double? value)
    {
        OnPropertyChanged(nameof(HasAestheticScore));
        OnPropertyChanged(nameof(AestheticScoreLabel));
    }

    partial void OnHeuristicScoreChanged(double? value)
    {
        OnPropertyChanged(nameof(HasHeuristicScore));
        OnPropertyChanged(nameof(HeuristicScoreLabel));
    }

    partial void OnSchedulerScoreMeanChanged(double? value)
    {
        OnPropertyChanged(nameof(HasSchedulerStats));
        OnPropertyChanged(nameof(SchedulerStatsLabel));
    }

    partial void OnSchedulerScoreStdDevChanged(double? value)
    {
        OnPropertyChanged(nameof(HasSchedulerStats));
        OnPropertyChanged(nameof(SchedulerStatsLabel));
    }
}

public sealed record SchedulerSeedSweepRequest(
    string Scheduler,
    InvokeAIGenerationParams Parameters,
    bool EnableAestheticScoring,
    bool EnableArtifactHeuristics);

public sealed record SchedulerStepsSweepRequest(
    string Scheduler,
    InvokeAIGenerationParams Parameters,
    int Interval,
    int CountPerSide,
    int MinSteps,
    int MaxSteps,
    bool EnableAestheticScoring,
    bool EnableArtifactHeuristics);
