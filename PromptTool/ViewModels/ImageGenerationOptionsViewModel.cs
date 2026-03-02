using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Windows.Input;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Clients;
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.Core.Config;
using PromptTool.Services;
using System.Threading.Tasks;

namespace PromptTool.ViewModels;

public partial class ImageGenerationOptionsViewModel : ObservableObject
{
    private const int PromptTokenLimitEstimate = 77;
    private readonly InvokeAIClient _invokeAiClient;
    private readonly SettingsService _settingsService;
    private readonly string _defaultNegativePrompt;
    private readonly NotificationService? _notifications;
    private readonly Random _rng = new();
    private GenerationDefaultsSettings _activeDefaults;
    private string? _pendingSchedulerValue;
    private bool _suppressSchedulerTracking;
    private bool _schedulerManuallySet;

    [ObservableProperty] private string _prompt = "";
    [ObservableProperty] private string _negativePrompt = "";
    [ObservableProperty] private int _seed;
    [ObservableProperty] private bool _useRandomSeed = true;
    [ObservableProperty] private int _steps = 30;
    [ObservableProperty] private double _cfgScale = 7.5;
    [ObservableProperty] private double _cfgRescaleMultiplier = 0;
    [ObservableProperty] private int _numImages = 1;
    [ObservableProperty] private bool _saveToGallery;
    [ObservableProperty] private int _width = 1024;
    [ObservableProperty] private int _height = 1024;

    [ObservableProperty] private ObservableCollection<SelectableModelViewModel> _models = new();
    private List<SelectableModelViewModel> _allModels = new();
    [ObservableProperty] private string _modelSearchText = string.Empty;
    
    [ObservableProperty] private ObservableCollection<SchedulerOption> _schedulers = new();
    [ObservableProperty] private SchedulerOption? _selectedSchedulerOption;
    [ObservableProperty] private bool _useModelDefaultsForScheduler = true;
    [ObservableProperty] private bool _hasModelSchedulerDefault;
    [ObservableProperty] private string _modelSchedulerDefaultLabel = string.Empty;
    [ObservableProperty] private string _modelSchedulerDefaultToolTip = string.Empty;

    [ObservableProperty] private ObservableCollection<SelectableLoraViewModel> _loras = new();
    private List<SelectableLoraViewModel> _allLoras = new();
    [ObservableProperty] private string _loraSearchText = string.Empty;

    [ObservableProperty] private string _negativeStyleText = string.Empty;
    [ObservableProperty] private string _positiveStyleText = string.Empty;
    [ObservableProperty] private bool _showStylePrompts = true;

    [ObservableProperty] private string _baseModelType = "sdxl"; // Default to SDXL
    public ObservableCollection<string> BaseModelTypes { get; } = new() { "sdxl", "sd-1.5" };
    [ObservableProperty] private string _statusMessage = "";
    [ObservableProperty] private string _modeBannerText = "";
    [ObservableProperty] private bool _showModeBanner;
    [ObservableProperty] private string _totalImagesLabel = "Total images: 0";
    [ObservableProperty] private ObservableCollection<NegativePresetItem> _negativePresets = new();
    [ObservableProperty] private NegativePresetItem? _selectedNegativePreset;
    [ObservableProperty] private bool _isNegativePromptDirty;
    private bool _suppressNegativePresetSync;

    public ICommand GenerateCommand { get; }
    public ICommand CancelCommand { get; }
    public ICommand RandomizeSeedCommand { get; }
    public ICommand ToggleAllModelsCommand { get; }
    public ICommand ClearModelsCommand { get; }
    public IAsyncRelayCommand RefreshDataCommand { get; }
    public ICommand ClearLorasCommand { get; }
    public ICommand SetAspectRatioCommand { get; }

    public (bool, List<InvokeAIGenerationParams>?) Result { get; private set; }
    public bool SkipDefaultPrefixes { get; set; }
    public bool AllowLongPromptWarningOnly { get; set; }
    public bool DisableAutoDefaults { get; set; }
    public bool UsePromptAsStyleWhenEmpty { get; set; } = true;
    public bool? UseCpuNoise { get; set; }
    public bool? L2iFp32 { get; set; }
    public string? VaePrecision { get; set; }
    public bool? UseAutoCfgRescale { get; set; }
    private string? _pendingModelSelection;
    private List<(string name, double weight)> _pendingLoraSelection = new();
    private string? _disabledModelSelection;

    public ImageGenerationOptionsViewModel(InvokeAIClient invokeAiClient, SettingsService settingsService, NotificationService? notifications = null)
    {
        _invokeAiClient = invokeAiClient;
        _settingsService = settingsService;
        _notifications = notifications;
        _defaultNegativePrompt = settingsService.Settings.DefaultNegativePrompt;
        _baseModelType = string.IsNullOrWhiteSpace(settingsService.Settings.DefaultBaseModelType)
            ? "sdxl"
            : settingsService.Settings.DefaultBaseModelType;
        if (!BaseModelTypes.Contains(_baseModelType))
        {
            BaseModelTypes.Add(_baseModelType);
        }
        _activeDefaults = ResolveDefaultsForBase(_baseModelType);
        Steps = _activeDefaults.Steps;
        CfgScale = _activeDefaults.CfgScale;
        CfgRescaleMultiplier = _activeDefaults.CfgRescaleMultiplier;
        Width = _activeDefaults.Width;
        Height = _activeDefaults.Height;
        SaveToGallery = _activeDefaults.SaveToGallery;
        ShowStylePrompts = string.Equals(_baseModelType, "sdxl", StringComparison.OrdinalIgnoreCase);

        GenerateCommand = new RelayCommand(Generate);
        CancelCommand = new RelayCommand(Cancel);
        RandomizeSeedCommand = new RelayCommand(RandomizeSeed);
        ToggleAllModelsCommand = new RelayCommand(ToggleAllModels);
        ClearModelsCommand = new RelayCommand(ClearModels);
        ClearLorasCommand = new RelayCommand(ClearLoras);
        SetAspectRatioCommand = new RelayCommand<string>(SetAspectRatio);
        RefreshDataCommand = new AsyncRelayCommand(LoadDataAsync);
        
        RandomizeSeed();
        UseRandomSeed = true;
        _ = LoadDataAsync();
        NegativePrompt = _defaultNegativePrompt;
        InitializeNegativePresets();
    }

    private async Task LoadDataAsync()
    {
        StatusMessage = "";
        try
        {
            var reachable = await _invokeAiClient.IsReachableAsync();
            if (!reachable)
            {
                EnsureSchedulerSelection();
                StatusMessage = "InvokeAI is offline; using cached/default selections.";
                UpdateTotalImagesLabel();
                ApplyDefaultsForSelection();
                return;
            }

            var models = await _invokeAiClient.GetModelsAsync(baseModel: BaseModelType, modelType: "main");
            _allModels = models
                .OrderBy(m => m.Name, StringComparer.OrdinalIgnoreCase)
                .Select(CreateModelVm)
                .ToList();
            Models = new ObservableCollection<SelectableModelViewModel>(_allModels);
            ApplyPendingModelSelection();

            if (_allModels.Count == 0)
            {
                StatusMessage = "InvokeAI is unreachable; select saved defaults or retry after starting the server.";
            }

            var schedulers = await _invokeAiClient.GetSchedulersAsync();
            var schedulerOptions = schedulers
                .OrderBy(s => s, StringComparer.OrdinalIgnoreCase)
                .Select(s => new SchedulerOption(s, NormalizeSchedulerDisplay(s))).ToList();
            EnsureSchedulerSelection(schedulerOptions);
            
            var loras = await _invokeAiClient.GetModelsAsync(baseModel: BaseModelType, modelType: "lora");
            _allLoras = loras
                .OrderBy(l => l.Name, StringComparer.OrdinalIgnoreCase)
                .Select(CreateLoraVm)
                .ToList();
            Loras = new ObservableCollection<SelectableLoraViewModel>(_allLoras);
            ApplyPendingLoraSelection();

            if (_allLoras.Count == 0 && string.IsNullOrWhiteSpace(StatusMessage))
            {
                StatusMessage = "No LoRAs loaded; InvokeAI may be offline.";
            }
        }
        catch (Exception ex)
        {
            StatusMessage = $"Failed to load InvokeAI data: {ex.Message}";
            _notifications?.ShowWarning("InvokeAI not reachable; generation options limited to saved defaults.", "Offline");
            _allModels = new List<SelectableModelViewModel>();
            Models = new ObservableCollection<SelectableModelViewModel>();
            _allLoras = new List<SelectableLoraViewModel>();
            Loras = new ObservableCollection<SelectableLoraViewModel>();
            EnsureSchedulerSelection();
        }

        UpdateTotalImagesLabel();
        ApplyDefaultsForSelection();
    }

    public void SetInitialModel(string? modelName)
    {
        _pendingModelSelection = modelName;
        ApplyPendingModelSelection();
    }

    public void DisableModelSelection(string? modelName)
    {
        _disabledModelSelection = string.IsNullOrWhiteSpace(modelName) ? null : modelName.Trim();
        ApplyDisabledModelSelection();
    }

    public void SetInitialLoras(IEnumerable<LoraParameter> loras)
    {
        _pendingLoraSelection = loras.Select(l => (l.Lora.Name, l.Weight)).ToList();
        ApplyPendingLoraSelection();
    }

    public void ApplyGenerationParams(InvokeAIGenerationParams p)
    {
        if (!string.IsNullOrWhiteSpace(p.Model?.Base) && BaseModelTypes.Contains(p.Model.Base))
        {
            BaseModelType = p.Model.Base;
        }
        else if (!string.IsNullOrWhiteSpace(p.BaseModelType) && BaseModelTypes.Contains(p.BaseModelType))
        {
            BaseModelType = p.BaseModelType;
        }
        Prompt = string.IsNullOrWhiteSpace(p.Prompt) ? Prompt : p.Prompt;
        _suppressNegativePresetSync = true;
        NegativePrompt = string.IsNullOrWhiteSpace(p.NegativePrompt) ? NegativePrompt : p.NegativePrompt;
        IsNegativePromptDirty = false;
        _suppressNegativePresetSync = false;
        NegativeStyleText = string.IsNullOrWhiteSpace(p.NegativeStylePrompt) ? NegativeStyleText : p.NegativeStylePrompt;
        PositiveStyleText = string.IsNullOrWhiteSpace(p.PositiveStylePrompt) ? PositiveStyleText : p.PositiveStylePrompt;
        Steps = p.Steps;
        CfgScale = p.CfgScale;
        CfgRescaleMultiplier = p.CfgRescaleMultiplier;
        Width = p.Width;
        Height = p.Height;
        Seed = p.Seed;
        UseRandomSeed = false;
        SaveToGallery = p.SaveToGallery;
        _pendingSchedulerValue = p.Scheduler;
        SetInitialModel(p.Model?.Name);
        SetInitialLoras(p.Loras ?? Enumerable.Empty<LoraParameter>());
        UsePromptAsStyleWhenEmpty = p.UsePromptAsStyleWhenEmpty;
        UseCpuNoise = p.UseCpuNoise;
        L2iFp32 = p.L2iFp32;
        VaePrecision = p.VaePrecision;
        UseAutoCfgRescale = p.UseAutoCfgRescale;
    }

    public bool HasUnsavedNegativePromptChanges => IsNegativePromptDirty;

    public async Task<bool> SaveNegativePromptPresetAsync(string presetName, bool overwriteExisting)
    {
        if (string.IsNullOrWhiteSpace(presetName))
        {
            return false;
        }

        var settings = _settingsService.Settings;
        var normalizedName = presetName.Trim();
        var existingKey = settings.NegativePromptPresets.Keys
            .FirstOrDefault(k => string.Equals(k, normalizedName, StringComparison.OrdinalIgnoreCase));
        var exists = existingKey != null;
        if (exists && !overwriteExisting)
        {
            return false;
        }

        var targetKey = existingKey ?? normalizedName;
        settings.NegativePromptPresets[targetKey] = NegativePrompt?.Trim() ?? string.Empty;
        var saved = await _settingsService.SaveSettingsAsync(settings);
        if (!saved)
        {
            return false;
        }

        var existing = NegativePresets.FirstOrDefault(p => string.Equals(p.Key, targetKey, StringComparison.OrdinalIgnoreCase));
        if (existing == null)
        {
            existing = new NegativePresetItem(targetKey, settings.NegativePromptPresets[targetKey]);
            NegativePresets.Add(existing);
        }
        else
        {
            existing.Value = settings.NegativePromptPresets[targetKey];
        }

        _suppressNegativePresetSync = true;
        SelectedNegativePreset = existing;
        NegativePrompt = existing.Value;
        IsNegativePromptDirty = false;
        _suppressNegativePresetSync = false;
        return true;
    }

    partial void OnBaseModelTypeChanged(string value)
    {
        _activeDefaults = ResolveDefaultsForBase(value);
        _schedulerManuallySet = false;
        if (!DisableAutoDefaults)
        {
            Steps = _activeDefaults.Steps;
            CfgScale = _activeDefaults.CfgScale;
            CfgRescaleMultiplier = _activeDefaults.CfgRescaleMultiplier;
            Width = _activeDefaults.Width;
            Height = _activeDefaults.Height;
            SaveToGallery = _activeDefaults.SaveToGallery;
        }
        EnsureSchedulerSelection();
        ShowStylePrompts = string.Equals(value, "sdxl", StringComparison.OrdinalIgnoreCase);
        _ = LoadDataAsync(); // Reload models and LoRAs when base model type changes
    }

    partial void OnNegativePromptChanged(string value)
    {
        if (_suppressNegativePresetSync)
        {
            return;
        }

        if (SelectedNegativePreset == null)
        {
            IsNegativePromptDirty = !string.IsNullOrWhiteSpace(value);
            return;
        }

        IsNegativePromptDirty = !string.Equals(value, SelectedNegativePreset.Value, StringComparison.Ordinal);
    }

    partial void OnSelectedNegativePresetChanged(NegativePresetItem? value)
    {
        if (_suppressNegativePresetSync || value == null)
        {
            return;
        }

        _suppressNegativePresetSync = true;
        NegativePrompt = value.Value;
        IsNegativePromptDirty = false;
        _suppressNegativePresetSync = false;
    }

    partial void OnSelectedSchedulerOptionChanged(SchedulerOption? value)
    {
        if (_suppressSchedulerTracking)
        {
            return;
        }

        _schedulerManuallySet = true;
        UpdateModelSchedulerDefaultInfo();
    }

    partial void OnUseModelDefaultsForSchedulerChanged(bool value)
    {
        UpdateModelSchedulerDefaultInfo();
        if (value && !_schedulerManuallySet)
        {
            ApplyDefaultsForSelection();
        }
    }

    private void InitializeNegativePresets()
    {
        NegativePresets.Clear();
        var settings = _settingsService.Settings;
        foreach (var kvp in settings.NegativePromptPresets)
        {
            NegativePresets.Add(new NegativePresetItem(kvp.Key, kvp.Value));
        }

        if (NegativePresets.Count == 0)
        {
            var key = string.IsNullOrWhiteSpace(settings.DefaultNegativePromptKey) ? "standard" : settings.DefaultNegativePromptKey;
            NegativePresets.Add(new NegativePresetItem(key, settings.DefaultNegativePrompt));
        }

        var defaultKey = settings.DefaultNegativePromptKey;
        var selected = NegativePresets.FirstOrDefault(p => string.Equals(p.Key, defaultKey, StringComparison.OrdinalIgnoreCase))
                       ?? NegativePresets.FirstOrDefault();
        if (selected != null)
        {
            _suppressNegativePresetSync = true;
            SelectedNegativePreset = selected;
            NegativePrompt = selected.Value;
            IsNegativePromptDirty = false;
            _suppressNegativePresetSync = false;
        }
    }

    public string GetSuggestedPresetName()
    {
        var baseName = SelectedNegativePreset?.Key;
        if (string.IsNullOrWhiteSpace(baseName))
        {
            baseName = "Preset";
        }

        var candidate = $"{baseName} copy";
        if (!NegativePresets.Any(p => string.Equals(p.Key, candidate, StringComparison.OrdinalIgnoreCase)))
        {
            return candidate;
        }

        var index = 1;
        while (true)
        {
            var name = $"{baseName} copy {index}";
            if (!NegativePresets.Any(p => string.Equals(p.Key, name, StringComparison.OrdinalIgnoreCase)))
            {
                return name;
            }
            index++;
        }
    }

    public sealed partial class NegativePresetItem : ObservableObject
    {
        public NegativePresetItem(string key, string value)
        {
            _key = key;
            _value = value;
        }

        [ObservableProperty] private string _key;
        [ObservableProperty] private string _value;
    }

    public event EventHandler? RequestClose;

    private void Generate()
    {
        StatusMessage = "";
        ApplyLoraDefaults();
        var selectedLoras = Loras.Where(l => l.IsSelected).ToList();
        var loraParams = selectedLoras.Select(l => new LoraParameter { Lora = l.Lora, Weight = l.Weight }).ToList();

        var selectedModels = Models.Where(m => m.IsSelected).ToList();
        if (!selectedModels.Any())
        {
            StatusMessage = "Select at least one model.";
            return;
        }

        var styleNegative = ShowStylePrompts ? (NegativeStyleText ?? string.Empty) : string.Empty;
        var stylePositive = ShowStylePrompts ? (PositiveStyleText ?? string.Empty).Trim() : string.Empty;

        var imagesPerModel = Math.Max(1, NumImages);
        var results = new List<InvokeAIGenerationParams>();
        var baseSeed = UseRandomSeed ? _rng.Next() : Seed;

        foreach (var model in selectedModels)
        {
            var invokeModel = model.Model;
            if (string.IsNullOrEmpty(invokeModel.Type))
            {
                invokeModel = invokeModel with { Type = "main" };
            }

            var promptForModel = Prompt ?? string.Empty;
            var negativeForModel = NegativePrompt ?? string.Empty;
            var schedulerForModel = SelectedSchedulerOption?.Value ?? string.Empty;
            if (!SkipDefaultPrefixes)
            {
                (promptForModel, negativeForModel, schedulerForModel) = ApplyDefaultPrefixes(
                    promptForModel,
                    negativeForModel,
                    schedulerForModel,
                    invokeModel,
                    selectedLoras,
                    allowSchedulerOverride: UseModelDefaultsForScheduler && !_schedulerManuallySet);
            }
            else
            {
                schedulerForModel = ApplyModelSchedulerDefault(
                    schedulerForModel,
                    invokeModel,
                    allowSchedulerOverride: UseModelDefaultsForScheduler && !_schedulerManuallySet);
            }

            var finalNegativeForModel = string.IsNullOrWhiteSpace(styleNegative)
                ? negativeForModel
                : $"{negativeForModel}\n{styleNegative}".Trim();

            if (!ValidatePromptLengths(promptForModel, finalNegativeForModel, stylePositive, styleNegative, invokeModel.Name))
            {
                return;
            }

            for (int i = 0; i < imagesPerModel; i++)
            {
                results.Add(new InvokeAIGenerationParams
                {
                    Prompt = promptForModel,
                    PositiveStylePrompt = string.IsNullOrWhiteSpace(stylePositive) ? null : stylePositive,
                    NegativeStylePrompt = string.IsNullOrWhiteSpace(styleNegative) ? null : styleNegative,
                    NegativePrompt = finalNegativeForModel,
                    UsePromptAsStyleWhenEmpty = UsePromptAsStyleWhenEmpty,
                    Model = invokeModel,
                    Steps = Steps,
                    CfgScale = CfgScale,
                    Width = Width,
                    Height = Height,
                    Seed = baseSeed + i,
                    Scheduler = schedulerForModel,
                    CfgRescaleMultiplier = CfgRescaleMultiplier,
                    Loras = loraParams,
                    SaveToGallery = SaveToGallery,
                    UsedRandomSeed = UseRandomSeed,
                    BaseSeed = baseSeed,
                    BaseModelType = BaseModelType,
                    AutoClearedModelCacheBetweenModels = _settingsService.Settings.AutoClearInvokeCacheBetweenModels,
                    UseCpuNoise = UseCpuNoise,
                    L2iFp32 = L2iFp32,
                    VaePrecision = VaePrecision,
                    UseAutoCfgRescale = UseAutoCfgRescale
                });
            }
        }

        Result = (true, results);
        RequestClose?.Invoke(this, EventArgs.Empty);
    }

    private bool ValidatePromptLengths(
        string prompt,
        string? negativePrompt,
        string? positiveStyle,
        string? negativeStyle,
        string? modelName)
    {
        return true;
    }

    private void ToggleAllModels()
    {
        if (!_allModels.Any()) return;
        var enabled = _allModels.Where(m => m.IsEnabled).ToList();
        if (enabled.Count == 0) return;
        var anyUnchecked = enabled.Any(m => !m.IsSelected);
        foreach (var model in _allModels)
        {
            if (!model.IsEnabled) continue;
            model.IsSelected = anyUnchecked;
        }
        UpdateTotalImagesLabel();
        UpdateModelSchedulerDefaultInfo();
    }

    private void Cancel()
    {
        Result = (false, null);
        RequestClose?.Invoke(this, EventArgs.Empty);
    }

    private void LoadNegativeStyles(Dictionary<string, string> presets, string defaultKey)
    {
        // No-op: negative styles now free-form text.
    }

    private void RandomizeSeed()
    {
        Seed = _rng.Next();
    }

    private void UpdateTotalImagesLabel()
    {
        var selectedCount = (_allModels.Count > 0 ? _allModels.AsEnumerable() : Models).Count(m => m.IsSelected);
        var total = selectedCount * Math.Max(1, NumImages);
        TotalImagesLabel = $"Total images: {total}";
    }

    partial void OnNumImagesChanged(int value)
    {
        UpdateTotalImagesLabel();
    }

    private (string prompt, string negativePrompt, string scheduler) ApplyDefaultPrefixes(
        string prompt,
        string negativePrompt,
        string scheduler,
        InvokeAIModel model,
        IReadOnlyList<SelectableLoraViewModel> selectedLoras,
        bool allowSchedulerOverride)
    {
        var promptOut = prompt?.Trim() ?? string.Empty;
        var negativeOut = negativePrompt?.Trim() ?? string.Empty;
        var schedulerOut = scheduler ?? string.Empty;

        var modelDefaults = _settingsService.InvokeAIModelDefaults.FirstOrDefault(d =>
            string.Equals(d.ModelName, model.Name, StringComparison.OrdinalIgnoreCase));
        if (modelDefaults != null)
        {
            if (!string.IsNullOrWhiteSpace(modelDefaults.PositivePromptPrefix))
            {
                var prefix = modelDefaults.PositivePromptPrefix.Trim();
                promptOut = string.IsNullOrWhiteSpace(promptOut) ? prefix : $"{prefix}, {promptOut}";
            }
            if (!string.IsNullOrWhiteSpace(modelDefaults.NegativePromptPrefix))
            {
                var prefix = modelDefaults.NegativePromptPrefix.Trim();
                negativeOut = string.IsNullOrWhiteSpace(negativeOut) ? prefix : $"{prefix}, {negativeOut}";
            }
            if (allowSchedulerOverride &&
                !string.IsNullOrWhiteSpace(modelDefaults.Sampler) &&
                modelDefaults.Sampler != "(None)")
            {
                schedulerOut = modelDefaults.Sampler;
            }
        }

        if (_settingsService.InvokeAILoraDefaults.Any() && selectedLoras.Count > 0)
        {
            var posSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var negSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var lora in selectedLoras)
            {
                var defaults = _settingsService.InvokeAILoraDefaults.FirstOrDefault(d =>
                    string.Equals(d.ModelName, lora.Lora.Name, StringComparison.OrdinalIgnoreCase));
                if (defaults == null) continue;

                AddPrefixes(posSet, defaults.PositivePromptPrefix);
                AddPrefixes(negSet, defaults.NegativePromptPrefix);
            }

            if (posSet.Count > 0)
            {
                var combined = string.Join(", ", posSet.OrderBy(p => p, StringComparer.OrdinalIgnoreCase));
                promptOut = string.IsNullOrWhiteSpace(promptOut) ? combined : $"{combined}, {promptOut}";
            }
            if (negSet.Count > 0)
            {
                var combined = string.Join(", ", negSet.OrderBy(p => p, StringComparer.OrdinalIgnoreCase));
                negativeOut = string.IsNullOrWhiteSpace(negativeOut) ? combined : $"{combined}, {negativeOut}";
            }
        }

        return (promptOut, negativeOut, schedulerOut);
    }

    private string ApplyModelSchedulerDefault(string scheduler, InvokeAIModel model, bool allowSchedulerOverride)
    {
        if (!allowSchedulerOverride)
        {
            return scheduler;
        }

        var modelDefaults = _settingsService.InvokeAIModelDefaults.FirstOrDefault(d =>
            string.Equals(d.ModelName, model.Name, StringComparison.OrdinalIgnoreCase));
        if (modelDefaults == null)
        {
            return scheduler;
        }

        if (!string.IsNullOrWhiteSpace(modelDefaults.Sampler) && modelDefaults.Sampler != "(None)")
        {
            return modelDefaults.Sampler;
        }

        return scheduler;
    }

    private static void AddPrefixes(HashSet<string> target, string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return;
        var parts = raw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        foreach (var part in parts)
        {
            if (!string.IsNullOrWhiteSpace(part))
            {
                target.Add(part.Trim());
            }
        }
    }

    private void ClearModels()
    {
        foreach (var m in _allModels)
        {
            if (!m.IsEnabled) continue;
            m.IsSelected = false;
        }
        UpdateTotalImagesLabel();
        UpdateModelSchedulerDefaultInfo();
    }

    private void ClearLoras()
    {
        foreach (var l in _allLoras)
        {
            l.IsSelected = false;
            l.Weight = 0.75;
        }
    }

    partial void OnModelSearchTextChanged(string value)
    {
        ApplyModelFilter();
    }

    partial void OnLoraSearchTextChanged(string value)
    {
        ApplyLoraFilter();
    }

    private void ApplyModelFilter()
    {
        if (_allModels.Count == 0) return;
        var term = ModelSearchText?.Trim();
        var filtered = string.IsNullOrWhiteSpace(term)
            ? _allModels
            : _allModels.Where(vm => vm.Model.Name.Contains(term, StringComparison.OrdinalIgnoreCase)).ToList();
        Models = new ObservableCollection<SelectableModelViewModel>(filtered);
    }

    private void ApplyLoraFilter()
    {
        if (_allLoras.Count == 0) return;
        var term = LoraSearchText?.Trim();
        var filtered = string.IsNullOrWhiteSpace(term)
            ? _allLoras
            : _allLoras.Where(vm => vm.Lora.Name.Contains(term, StringComparison.OrdinalIgnoreCase)).ToList();
        Loras = new ObservableCollection<SelectableLoraViewModel>(filtered);
    }

    private SelectableModelViewModel CreateModelVm(InvokeAIModel m)
    {
        var vm = new SelectableModelViewModel { Model = m };
        vm.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(SelectableModelViewModel.IsSelected))
            {
                UpdateTotalImagesLabel();
                ApplyDefaultsForSelection();
            }
        };
        if (!string.IsNullOrWhiteSpace(_disabledModelSelection) &&
            string.Equals(m.Name, _disabledModelSelection, StringComparison.OrdinalIgnoreCase))
        {
            vm.IsEnabled = false;
            vm.IsSelected = false;
            vm.IsSourceModel = true;
        }
        return vm;
    }

    private SelectableLoraViewModel CreateLoraVm(InvokeAIModel l)
    {
        var defaults = _settingsService.InvokeAILoraDefaults.FirstOrDefault(d =>
            string.Equals(d.ModelName, l.Name, StringComparison.OrdinalIgnoreCase));
        var weight = defaults?.LoraWeight ?? 0.75;
        return new SelectableLoraViewModel { Lora = l, Weight = weight };
    }

    public static string NormalizeSchedulerDisplay(string value)
    {
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
    private void SetAspectRatio(string? ratio)
    {
        if (string.IsNullOrWhiteSpace(ratio) || !ratio.Contains(':')) return;
        var parts = ratio.Split(':', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length != 2) return;
        if (!int.TryParse(parts[0], out var wPart) || !int.TryParse(parts[1], out var hPart) || wPart == 0 || hPart == 0) return;

        var targetLong = Math.Max(Width, Height);
        if (targetLong < 512) targetLong = 1024;

        var aspect = (double)wPart / hPart;
        int newWidth, newHeight;
        if (aspect >= 1)
        {
            newWidth = RoundTo64(targetLong);
            newHeight = RoundTo64((int)(targetLong / aspect));
        }
        else
        {
            newHeight = RoundTo64(targetLong);
            newWidth = RoundTo64((int)(targetLong * aspect));
        }
        Width = newWidth;
        Height = newHeight;
    }

    private static int RoundTo64(int value)
    {
        const int step = 64;
        if (value < step) return step;
        return ((value + step / 2) / step) * step;
    }

    private void ApplyDefaultsForSelection()
    {
        if (DisableAutoDefaults) return;
        var selected = (_allModels.Count > 0 ? _allModels.AsEnumerable() : Models).Where(m => m.IsSelected).Select(m => m.Model).FirstOrDefault();
        if (selected == null)
        {
            UpdateModelSchedulerDefaultInfo();
            return;
        }

        var defaults = _settingsService.InvokeAIModelDefaults.FirstOrDefault(d => d.ModelName == selected.Name);
        if (defaults == null)
        {
            UpdateModelSchedulerDefaultInfo();
            return;
        }

        // Only override if values are still at their initial defaults to avoid clobbering user edits.
        if ((Steps == 30 || Steps == 0) && defaults.Steps > 0) Steps = defaults.Steps;
        if ((Math.Abs(CfgScale - 7.5) < 0.001 || CfgScale == 0) && defaults.CfgScale > 0) CfgScale = defaults.CfgScale;
        if (Math.Abs(CfgRescaleMultiplier) < 0.0001 && defaults.CfgRescaleMultiplier > 0) CfgRescaleMultiplier = defaults.CfgRescaleMultiplier;
        if ((Width == 1024 || Width == 0) && defaults.Width > 0) Width = defaults.Width;
        if ((Height == 1024 || Height == 0) && defaults.Height > 0) Height = defaults.Height;

        if (!string.IsNullOrWhiteSpace(defaults.PositivePromptPrefix) && string.IsNullOrWhiteSpace(Prompt))
        {
            Prompt = defaults.PositivePromptPrefix.Trim();
        }

        if (!string.IsNullOrWhiteSpace(defaults.NegativePromptPrefix) &&
            (string.IsNullOrWhiteSpace(NegativePrompt) || NegativePrompt == _defaultNegativePrompt))
        {
            NegativePrompt = $"{defaults.NegativePromptPrefix.Trim()} {NegativePrompt}".Trim();
        }

        UpdateModelSchedulerDefaultInfo();
    }

    private void ApplyPendingModelSelection()
    {
        if (string.IsNullOrWhiteSpace(_pendingModelSelection) || !_allModels.Any()) return;
        var match = _allModels.FirstOrDefault(m => string.Equals(m.Model.Name, _pendingModelSelection, StringComparison.OrdinalIgnoreCase));
        if (match != null && match.IsEnabled)
        {
            match.IsSelected = true;
            _pendingModelSelection = null;
            UpdateTotalImagesLabel();
            UpdateModelSchedulerDefaultInfo();
        }
    }

    private void ApplyDisabledModelSelection()
    {
        if (string.IsNullOrWhiteSpace(_disabledModelSelection) || !_allModels.Any()) return;
        foreach (var model in _allModels)
        {
            var isDisabled = string.Equals(model.Model.Name, _disabledModelSelection, StringComparison.OrdinalIgnoreCase);
            model.IsEnabled = !isDisabled;
            if (isDisabled)
            {
                model.IsSelected = false;
                model.IsSourceModel = true;
            }
            else if (model.IsSourceModel)
            {
                model.IsSourceModel = false;
            }
        }
        if (string.Equals(_pendingModelSelection, _disabledModelSelection, StringComparison.OrdinalIgnoreCase))
        {
            _pendingModelSelection = null;
        }
        UpdateTotalImagesLabel();
        UpdateModelSchedulerDefaultInfo();
    }

    private void ApplyPendingLoraSelection()
    {
        if (_pendingLoraSelection.Count == 0 || !_allLoras.Any()) return;
        foreach (var lora in _allLoras)
        {
            var pending = _pendingLoraSelection.FirstOrDefault(p => string.Equals(p.name, lora.Lora.Name, StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrWhiteSpace(pending.name))
            {
                lora.IsSelected = true;
                lora.Weight = pending.weight;
            }
        }
        _pendingLoraSelection.Clear();
        ApplyLoraDefaults();
    }

    private void ApplyLoraDefaults()
    {
        if (DisableAutoDefaults) return;
        if (!_settingsService.InvokeAILoraDefaults.Any()) return;
        var selectedVm = _allLoras.FirstOrDefault(l => l.IsSelected);
        var selectedLora = selectedVm?.Lora;
        if (selectedLora == null) return;

        var defaults = _settingsService.InvokeAILoraDefaults.FirstOrDefault(d => string.Equals(d.ModelName, selectedLora.Name, StringComparison.OrdinalIgnoreCase));
        if (defaults == null) return;

        if (defaults.LoraWeight.HasValue && selectedVm != null && Math.Abs(selectedVm.Weight - 0.75) < 0.0001)
        {
            selectedVm.Weight = defaults.LoraWeight.Value;
        }

        if ((Steps == 30 || Steps == 0) && defaults.Steps > 0) Steps = defaults.Steps;
        if ((Math.Abs(CfgScale - 7.5) < 0.001 || CfgScale == 0) && defaults.CfgScale > 0) CfgScale = defaults.CfgScale;
        if (Math.Abs(CfgRescaleMultiplier) < 0.0001 && defaults.CfgRescaleMultiplier > 0) CfgRescaleMultiplier = defaults.CfgRescaleMultiplier;
        if ((Width == 1024 || Width == 0) && defaults.Width > 0) Width = defaults.Width;
        if ((Height == 1024 || Height == 0) && defaults.Height > 0) Height = defaults.Height;

        if (!string.IsNullOrWhiteSpace(defaults.PositivePromptPrefix) && string.IsNullOrWhiteSpace(Prompt))
        {
            Prompt = defaults.PositivePromptPrefix.Trim();
        }

        if (!string.IsNullOrWhiteSpace(defaults.NegativePromptPrefix) &&
            (string.IsNullOrWhiteSpace(NegativePrompt) || NegativePrompt == _defaultNegativePrompt))
        {
            NegativePrompt = $"{defaults.NegativePromptPrefix.Trim()} {NegativePrompt}".Trim();
        }

        UpdateModelSchedulerDefaultInfo();
    }

    private void UpdateModelSchedulerDefaultInfo()
    {
        var selected = (_allModels.Count > 0 ? _allModels.AsEnumerable() : Models)
            .Where(m => m.IsSelected)
            .Select(m => m.Model)
            .ToList();

        if (selected.Count == 0)
        {
            HasModelSchedulerDefault = false;
            ModelSchedulerDefaultLabel = string.Empty;
            ModelSchedulerDefaultToolTip = string.Empty;
            return;
        }

        var defaults = selected
            .Select(m => new
            {
                Model = m.Name,
                Scheduler = _settingsService.InvokeAIModelDefaults
                    .FirstOrDefault(d => string.Equals(d.ModelName, m.Name, StringComparison.OrdinalIgnoreCase))
                    ?.Sampler
            })
            .Where(x => !string.IsNullOrWhiteSpace(x.Scheduler) && x.Scheduler != "(None)")
            .Select(x => new { x.Model, Scheduler = x.Scheduler! })
            .ToList();

        if (defaults.Count == 0)
        {
            HasModelSchedulerDefault = false;
            ModelSchedulerDefaultLabel = string.Empty;
            ModelSchedulerDefaultToolTip = string.Empty;
            return;
        }

        var uniqueSchedulers = defaults
            .Select(d => d.Scheduler)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        HasModelSchedulerDefault = true;
        var suffix = !UseModelDefaultsForScheduler
            ? " (disabled)"
            : _schedulerManuallySet ? " (overridden)" : string.Empty;

        if (uniqueSchedulers.Count == 1)
        {
            var display = NormalizeSchedulerDisplay(uniqueSchedulers[0]);
            ModelSchedulerDefaultLabel = $"Model default: {display}{suffix}";
        }
        else
        {
            ModelSchedulerDefaultLabel = $"Model defaults: Mixed ({uniqueSchedulers.Count}){suffix}";
        }

        ModelSchedulerDefaultToolTip = string.Join(
            "\n",
            defaults
                .OrderBy(d => d.Model, StringComparer.OrdinalIgnoreCase)
                .Select(d => $"{d.Model}: {NormalizeSchedulerDisplay(d.Scheduler)}"));
    }

    private GenerationDefaultsSettings ResolveDefaultsForBase(string baseModelType)
    {
        var key = string.IsNullOrWhiteSpace(baseModelType) ? "sdxl" : baseModelType;
        var map = _settingsService.Settings.GenerationDefaults ?? new Dictionary<string, GenerationDefaultsSettings>();
        if (map.TryGetValue(key, out var found))
        {
            found.Scheduler = NormalizeConfiguredScheduler(found.Scheduler);
            return found;
        }

        return new GenerationDefaultsSettings
        {
            Scheduler = NormalizeConfiguredScheduler(_settingsService.Settings.DefaultScheduler),
            Steps = _settingsService.Settings.DefaultSteps,
            CfgScale = _settingsService.Settings.DefaultCfgScale,
            CfgRescaleMultiplier = _settingsService.Settings.DefaultCfgRescaleMultiplier,
            Width = key == "sd-1.5" ? 512 : _settingsService.Settings.DefaultWidth,
            Height = key == "sd-1.5" ? 512 : _settingsService.Settings.DefaultHeight,
            SaveToGallery = _settingsService.Settings.DefaultSaveToGallery
        };
    }

    private void EnsureSchedulerSelection(IEnumerable<SchedulerOption>? availableOptions = null)
    {
        var options = availableOptions?.ToList();
        if (options == null || options.Count == 0)
        {
            var fallback = ResolveConfiguredScheduler();
            options = new List<SchedulerOption> { new(fallback, NormalizeSchedulerDisplay(fallback)) };
        }

        Schedulers = new ObservableCollection<SchedulerOption>(options);

        var configured = ResolveConfiguredScheduler();
        _suppressSchedulerTracking = true;
        SelectedSchedulerOption = options.FirstOrDefault(s => string.Equals(s.Value, configured, StringComparison.OrdinalIgnoreCase))
                                 ?? options.FirstOrDefault(s => string.Equals(NormalizeConfiguredScheduler(s.Value), configured, StringComparison.OrdinalIgnoreCase))
                                 ?? options.FirstOrDefault(s => string.Equals(s.Value, "dpmpp_2m_k", StringComparison.OrdinalIgnoreCase))
                                 ?? options.FirstOrDefault();
        _suppressSchedulerTracking = false;
        _schedulerManuallySet = !string.IsNullOrWhiteSpace(_pendingSchedulerValue);
        _pendingSchedulerValue = null;
    }

    private string ResolveConfiguredScheduler()
    {
        if (!string.IsNullOrWhiteSpace(_pendingSchedulerValue))
        {
            return NormalizeConfiguredScheduler(_pendingSchedulerValue);
        }

        if (!string.IsNullOrWhiteSpace(_activeDefaults.Scheduler))
        {
            return NormalizeConfiguredScheduler(_activeDefaults.Scheduler);
        }

        return NormalizeConfiguredScheduler(_settingsService.Settings.DefaultScheduler);
    }

    private static string NormalizeConfiguredScheduler(string? scheduler)
    {
        var resolved = string.IsNullOrWhiteSpace(scheduler) ? "dpmpp_2m_k" : scheduler.Trim();
        return GraphBuilder.NormalizeScheduler(resolved);
    }
}

public partial class SelectableModelViewModel : ObservableObject
{
    [ObservableProperty] private bool _isSelected;
    [ObservableProperty] private bool _isVisible = true;
    [ObservableProperty] private bool _isEnabled = true;
    [ObservableProperty] private bool _isSourceModel;
    public required InvokeAIModel Model { get; init; }

    public string DisplayName => Model.Name;
    public string Metadata
    {
        get
        {
            var parts = new List<string>();
            if (!string.IsNullOrWhiteSpace(Model.Base)) parts.Add(Model.Base);
            if (!string.IsNullOrWhiteSpace(Model.Format)) parts.Add(Model.Format);
            if (!string.IsNullOrWhiteSpace(Model.Type)) parts.Add(Model.Type);
            return parts.Count > 0 ? string.Join(" · ", parts) : string.Empty;
        }
    }
    public string Hash => Model.Hash;
    public bool HasHash => !string.IsNullOrWhiteSpace(Model.Hash);
}

public partial class SelectableLoraViewModel : ObservableObject
{
    [ObservableProperty] private bool _isSelected;
    [ObservableProperty] private bool _isVisible = true;
    [ObservableProperty] private double _weight = 0.75;
    public required InvokeAIModel Lora { get; init; }
}

public record SchedulerOption(string Value, string Display);
