using System;
using System.Collections.ObjectModel;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using System.IO;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Clients; // For InvokeAIClient
using PromptTool.Core.Models; // For ModelDefaults
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Services; // For SettingsService
using PromptTool.Services;
using PromptTool.Views;

namespace PromptTool.ViewModels;

public partial class InvokeAIModelDefaultsViewModel : ObservableObject
{
    private readonly SettingsService _settingsService;
    private readonly InvokeAIClient _invokeAIClient;
    private readonly NotificationService? _notifications;
    private readonly bool _deferPersist;
    private readonly List<ModelDefaults> _defaults;
    private bool _suppressModelSelectionSync;
    private bool _suppressDirty;
    private List<InvokeAIModel> _allAssets = new();
    private string? _lastSelectedAssetName;
    private bool _suppressSelectionRestore;

    [ObservableProperty]
    private ObservableCollection<ModelDefaults> _modelDefaults = new();

    public ObservableCollection<AssetGroupViewModel> AssetGroups { get; } = new();
    public ObservableCollection<AssetItemViewModel> AssetItems { get; } = new();

    [ObservableProperty]
    private object? _selectedTreeItem;

    [ObservableProperty]
    private AssetItemViewModel? _selectedAsset;

    [ObservableProperty]
    private string _searchText = "";

    public ObservableCollection<string> BaseModelTypes { get; } = new();

    [ObservableProperty]
    private string _selectedBaseModelType = "All";

    [ObservableProperty]
    private bool _isDirty;

    public bool CanSave => SelectedAsset != null && IsDirty;

    [ObservableProperty]
    private string _windowTitle = "InvokeAI Model Defaults";

    [ObservableProperty]
    private bool _isDeferred;

    [ObservableProperty]
    private bool? _dialogResult;

    [ObservableProperty]
    private string _saveButtonLabel = "Save Current";

    [ObservableProperty]
    private ModelDefaults? _selectedModelDefault;

    [ObservableProperty]
    private string _currentModelName = "";

    [ObservableProperty]
    private string _currentSampler = "";

    [ObservableProperty]
    private int? _currentSteps;

    [ObservableProperty]
    private double? _currentCfgScale;

    [ObservableProperty]
    private double? _currentCfgRescaleMultiplier;

    [ObservableProperty]
    private int? _currentWidth;

    [ObservableProperty]
    private int? _currentHeight;

    [ObservableProperty]
    private string _currentPositivePromptPrefix = "";

    [ObservableProperty]
    private string _currentNegativePromptPrefix = "";

    [ObservableProperty]
    private string _statusMessage = "";

    public ObservableCollection<string> AvailableInvokeAIModels { get; } = new();
    public ObservableCollection<string> SchedulerOptions { get; } = new();


    public InvokeAIModelDefaultsViewModel(
        SettingsService settingsService,
        InvokeAIClient invokeAIClient,
        NotificationService? notifications = null,
        IEnumerable<ModelDefaults>? initialDefaults = null,
        bool deferPersist = false)
    {
        _settingsService = settingsService;
        _invokeAIClient = invokeAIClient;
        _notifications = notifications;
        _deferPersist = deferPersist;
        _defaults = initialDefaults != null ? CloneModelDefaults(initialDefaults) : _settingsService.InvokeAIModelDefaults;
        IsDeferred = _deferPersist;
        SaveButtonLabel = _deferPersist ? "Apply" : "Save Current";
        LoadModelDefaultsCommand.Execute(null);
        LoadAvailableInvokeAIModelsCommand.Execute(null);
    }

    [RelayCommand]
    private async Task LoadModelDefaultsAsync()
    {
        ModelDefaults = new ObservableCollection<ModelDefaults>(CloneModelDefaults(_defaults));
        RebuildAssetGroups();
    }

    [RelayCommand]
    private async Task LoadAvailableInvokeAIModelsAsync()
    {
        StatusMessage = "";
        AvailableInvokeAIModels.Clear();
        try
        {
            var models = new List<InvokeAIModel>();
            foreach (var baseModel in new[] { "sdxl", "sd-1.5" })
            {
                var batch = await _invokeAIClient.GetModelsAsync(baseModel: baseModel, modelType: "main");
                models.AddRange(batch);
            }
            _allAssets = models
                .GroupBy(m => m.Key ?? m.Name, StringComparer.OrdinalIgnoreCase)
                .Select(g => g.First())
                .ToList();
            UpdateBaseModelTypes();
            SchedulerOptions.Clear();
            SchedulerOptions.Add("(None)");
            var schedulers = await _invokeAIClient.GetSchedulersAsync();
            foreach (var scheduler in schedulers.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                SchedulerOptions.Add(scheduler);
            }
            foreach (var model in _allAssets)
            {
                AvailableInvokeAIModels.Add(model.Name);
            }
            if (AvailableInvokeAIModels.Count == 0)
            {
                StatusMessage = "InvokeAI is unreachable; using saved defaults only.";
            }
        }
        catch (Exception ex)
        {
            StatusMessage = $"Failed to load InvokeAI models: {ex.Message}";
            _notifications?.ShowWarning("InvokeAI not reachable; showing saved model defaults only.", "Offline");
            _allAssets = new List<InvokeAIModel>();
            UpdateBaseModelTypes();
            if (!SchedulerOptions.Contains("(None)"))
            {
                SchedulerOptions.Clear();
                SchedulerOptions.Add("(None)");
            }
        }
        _lastSelectedAssetName ??= _defaults.FirstOrDefault()?.ModelName;
        RebuildAssetGroups();
    }

    partial void OnSelectedModelDefaultChanged(ModelDefaults? value)
    {
        if (_suppressModelSelectionSync)
        {
            return;
        }

        _suppressModelSelectionSync = true;
        if (value != null)
        {
            CurrentModelName = value.ModelName;
            CurrentSampler = value.Sampler;
            CurrentSteps = value.Steps;
            CurrentCfgScale = value.CfgScale;
            CurrentCfgRescaleMultiplier = value.CfgRescaleMultiplier;
            CurrentWidth = value.Width;
            CurrentHeight = value.Height;
            CurrentPositivePromptPrefix = value.PositivePromptPrefix;
            CurrentNegativePromptPrefix = value.NegativePromptPrefix;
        }
        else
        {
            ClearCurrentEditFields();
        }
        _suppressModelSelectionSync = false;
    }

    partial void OnCurrentModelNameChanged(string value)
    {
        if (_suppressModelSelectionSync)
        {
            return;
        }

        var match = ModelDefaults.FirstOrDefault(d => string.Equals(d.ModelName, value, StringComparison.OrdinalIgnoreCase));
        if (match == null)
        {
            return;
        }

        _suppressModelSelectionSync = true;
        SelectedModelDefault = match;
        _suppressModelSelectionSync = false;
    }

    [RelayCommand]
    private void NewModelDefault()
    {
        _suppressModelSelectionSync = true;
        ClearCurrentEditFields();
        SelectedModelDefault = null;
        // Optionally pre-select the first available InvokeAI model if not already selected
        if (AvailableInvokeAIModels.Any() && string.IsNullOrWhiteSpace(CurrentModelName))
        {
            CurrentModelName = AvailableInvokeAIModels.First();
        }
        _suppressModelSelectionSync = false;
    }

    [RelayCommand]
    private async Task SaveModelDefaultAsync()
    {
        var name = SelectedAsset?.Name ?? CurrentModelName;
        if (string.IsNullOrWhiteSpace(name))
        {
            _notifications?.ShowWarning("Please select a model before saving.", "Missing model");
            return;
        }

        UpsertDefault(name);
        if (!_deferPersist)
        {
            var ok = _settingsService.SaveInvokeAIModelDefaults();
            if (ok)
            {
                _notifications?.ShowInfo("Model defaults saved.", "Success");
            }
            else
            {
                _notifications?.ShowError("Failed to save model defaults.", "Error");
            }
        }

        await LoadModelDefaultsAsync();
        SelectedModelDefault = ModelDefaults.FirstOrDefault(d => string.Equals(d.ModelName, name, StringComparison.OrdinalIgnoreCase));
        SetDirty(false);
    }

    [RelayCommand]
    private async Task DeleteModelDefaultAsync()
    {
        if (SelectedModelDefault == null) return;

        var owner = GetOwnerWindow();
        if (owner == null)
        {
            _notifications?.ShowWarning("Unable to confirm deletion without an owner window.", "Delete model default");
            return;
        }

        var confirm = await ConfirmDialog.Show(owner, "Delete model default?",
            $"Delete defaults for '{SelectedModelDefault.ModelName}'?");
        if (!confirm) return;

        RemoveDefault(SelectedModelDefault.ModelName);
        if (!_deferPersist)
        {
            var ok = _settingsService.SaveInvokeAIModelDefaults();
            if (ok)
            {
                _notifications?.ShowInfo("Model default deleted.", "Success");
            }
            else
            {
                _notifications?.ShowError("Failed to save after deletion.", "Error");
            }
        }

        await LoadModelDefaultsAsync();
        SelectedModelDefault = null; // Clear selection
        ClearCurrentEditFields();
    }

    partial void OnSelectedTreeItemChanged(object? value)
    {
        if (value is AssetItemViewModel asset)
        {
            SelectedAsset = asset;
        }
        else
        {
            SelectedAsset = null;
        }
    }

    partial void OnSelectedAssetChanged(AssetItemViewModel? value)
    {
        if (value == null)
        {
            SetDirty(false);
            return;
        }
        if (_deferPersist && IsDirty)
        {
            CommitCurrentEdits();
        }
        _lastSelectedAssetName = value.Name;
        LoadDefaultsForAsset(value.Name);
    }

    partial void OnSearchTextChanged(string value)
    {
        RebuildAssetGroups();
    }

    partial void OnSelectedBaseModelTypeChanged(string value)
    {
        RebuildAssetGroups();
    }

    partial void OnCurrentSamplerChanged(string value)
    {
        MarkDirty();
    }

    partial void OnCurrentStepsChanged(int? value)
    {
        MarkDirty();
    }

    partial void OnCurrentCfgScaleChanged(double? value)
    {
        MarkDirty();
    }

    partial void OnCurrentCfgRescaleMultiplierChanged(double? value)
    {
        MarkDirty();
    }

    partial void OnCurrentWidthChanged(int? value)
    {
        MarkDirty();
    }

    partial void OnCurrentHeightChanged(int? value)
    {
        MarkDirty();
    }

    partial void OnCurrentPositivePromptPrefixChanged(string value)
    {
        MarkDirty();
    }

    partial void OnCurrentNegativePromptPrefixChanged(string value)
    {
        MarkDirty();
    }

    partial void OnIsDirtyChanged(bool value)
    {
        WindowTitle = value ? "InvokeAI Model Defaults *" : "InvokeAI Model Defaults";
        OnPropertyChanged(nameof(CanSave));
    }

    private static Window? GetOwnerWindow()
    {
        return (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow;
    }

    public bool ExportAll(string path)
    {
        try
        {
            if (_deferPersist)
            {
                var options = new JsonSerializerOptions { WriteIndented = true };
                var json = JsonSerializer.Serialize(_defaults, options);
                File.WriteAllText(path, json);
            }
            else
            {
                _settingsService.ExportInvokeAIDefaults(path);
            }
            return true;
        }
        catch
        {
            return false;
        }
    }

    public bool ImportAll(string path)
    {
        try
        {
            if (_deferPersist)
            {
                var json = File.ReadAllText(path);
                var list = JsonSerializer.Deserialize<List<ModelDefaults>>(json) ?? new List<ModelDefaults>();
                _defaults.Clear();
                _defaults.AddRange(list);
                LoadModelDefaultsCommand.Execute(null);
                return true;
            }

            var ok = _settingsService.ImportInvokeAIDefaults(path);
            LoadModelDefaultsCommand.Execute(null);
            return ok;
        }
        catch
        {
            return false;
        }
    }

    private void RebuildAssetGroups()
    {
        AssetGroups.Clear();
        AssetItems.Clear();
        var term = SearchText?.Trim() ?? string.Empty;
        var groups = new Dictionary<string, List<AssetItemViewModel>>(StringComparer.OrdinalIgnoreCase);

        var assetNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var asset in _allAssets)
        {
            if (!string.Equals(SelectedBaseModelType, "All", StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(asset.Base, SelectedBaseModelType, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            assetNames.Add(asset.Name);
            if (!string.IsNullOrWhiteSpace(term) &&
                !asset.Name.Contains(term, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            var baseName = string.IsNullOrWhiteSpace(asset.Base) ? "Other" : asset.Base;
            if (!groups.TryGetValue(baseName, out var list))
            {
                list = new List<AssetItemViewModel>();
                groups[baseName] = list;
            }
            list.Add(new AssetItemViewModel(asset.Name, HasDefaults(asset.Name), baseName));
        }

        foreach (var group in groups.OrderBy(g => g.Key, StringComparer.OrdinalIgnoreCase))
        {
            var items = new ObservableCollection<AssetItemViewModel>(group.Value.OrderBy(i => i.Name, StringComparer.OrdinalIgnoreCase));
            AssetGroups.Add(new AssetGroupViewModel(group.Key, items));
            foreach (var item in items)
            {
                AssetItems.Add(item);
            }
        }

        RestoreSelection();
    }

    private void UpdateBaseModelTypes()
    {
        BaseModelTypes.Clear();
        BaseModelTypes.Add("All");
        foreach (var type in _allAssets.Select(a => a.Base).Where(b => !string.IsNullOrWhiteSpace(b)).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            BaseModelTypes.Add(type);
        }
        if (!BaseModelTypes.Contains(SelectedBaseModelType))
        {
            SelectedBaseModelType = "All";
        }
    }

    private void LoadDefaultsForAsset(string assetName)
    {
        _suppressDirty = true;
        var defaults = _defaults.FirstOrDefault(d =>
            string.Equals(d.ModelName, assetName, StringComparison.OrdinalIgnoreCase));
        CurrentModelName = assetName;
        if (defaults == null)
        {
            CurrentSampler = "(None)";
            CurrentSteps = null;
            CurrentCfgScale = null;
            CurrentCfgRescaleMultiplier = null;
            CurrentWidth = null;
            CurrentHeight = null;
            CurrentPositivePromptPrefix = "";
            CurrentNegativePromptPrefix = "";
        }
        else
        {
            CurrentSampler = string.IsNullOrWhiteSpace(defaults.Sampler) ? "(None)" : defaults.Sampler;
            CurrentSteps = defaults.Steps > 0 ? defaults.Steps : null;
            CurrentCfgScale = defaults.CfgScale > 0 ? defaults.CfgScale : null;
            CurrentCfgRescaleMultiplier = defaults.CfgRescaleMultiplier > 0 ? defaults.CfgRescaleMultiplier : null;
            CurrentWidth = defaults.Width > 0 ? defaults.Width : null;
            CurrentHeight = defaults.Height > 0 ? defaults.Height : null;
            CurrentPositivePromptPrefix = defaults.PositivePromptPrefix;
            CurrentNegativePromptPrefix = defaults.NegativePromptPrefix;
        }
        SetDirty(false);
        _suppressDirty = false;
    }

    private void RestoreSelection()
    {
        if (_suppressSelectionRestore) return;
        if (string.IsNullOrWhiteSpace(_lastSelectedAssetName)) return;
        var match = AssetItems.FirstOrDefault(i => string.Equals(i.Name, _lastSelectedAssetName, StringComparison.OrdinalIgnoreCase));
        if (match != null)
        {
            _suppressSelectionRestore = true;
            SelectedAsset = match;
            _suppressSelectionRestore = false;
        }
    }

    private ModelDefaults? BuildDefaultsForSave(string assetName)
    {
        var hasAny = false;
        var result = new ModelDefaults { ModelName = assetName };

        var sampler = string.IsNullOrWhiteSpace(CurrentSampler) || CurrentSampler == "(None)"
            ? string.Empty
            : CurrentSampler.Trim();
        if (!string.IsNullOrWhiteSpace(sampler))
        {
            result.Sampler = sampler;
            hasAny = true;
        }
        else
        {
            result.Sampler = string.Empty;
        }

        if (CurrentSteps.HasValue && CurrentSteps.Value > 0) { result.Steps = CurrentSteps.Value; hasAny = true; } else { result.Steps = 0; }
        if (CurrentCfgScale.HasValue && CurrentCfgScale.Value > 0) { result.CfgScale = CurrentCfgScale.Value; hasAny = true; } else { result.CfgScale = 0; }
        if (CurrentCfgRescaleMultiplier.HasValue && CurrentCfgRescaleMultiplier.Value > 0) { result.CfgRescaleMultiplier = CurrentCfgRescaleMultiplier.Value; hasAny = true; } else { result.CfgRescaleMultiplier = 0; }
        if (CurrentWidth.HasValue && CurrentWidth.Value > 0) { result.Width = CurrentWidth.Value; hasAny = true; } else { result.Width = 0; }
        if (CurrentHeight.HasValue && CurrentHeight.Value > 0) { result.Height = CurrentHeight.Value; hasAny = true; } else { result.Height = 0; }

        var pos = CurrentPositivePromptPrefix?.Trim() ?? string.Empty;
        if (!string.IsNullOrWhiteSpace(pos)) { result.PositivePromptPrefix = pos; hasAny = true; } else { result.PositivePromptPrefix = string.Empty; }

        var neg = CurrentNegativePromptPrefix?.Trim() ?? string.Empty;
        if (!string.IsNullOrWhiteSpace(neg)) { result.NegativePromptPrefix = neg; hasAny = true; } else { result.NegativePromptPrefix = string.Empty; }

        return hasAny ? result : null;
    }

    private bool HasDefaults(string assetName)
    {
        return _defaults.Any(d =>
            string.Equals(d.ModelName, assetName, StringComparison.OrdinalIgnoreCase));
    }

    private void MarkDirty()
    {
        if (_suppressDirty) return;
        SetDirty(true);
    }

    private void SetDirty(bool value)
    {
        IsDirty = value;
        OnPropertyChanged(nameof(CanSave));
    }

    private void ClearCurrentEditFields()
    {
        CurrentModelName = "";
        CurrentSampler = "(None)";
        CurrentSteps = null;
        CurrentCfgScale = null;
        CurrentCfgRescaleMultiplier = null;
        CurrentWidth = null;
        CurrentHeight = null;
        CurrentPositivePromptPrefix = "";
        CurrentNegativePromptPrefix = "";
    }

    [RelayCommand]
    private void Confirm()
    {
        if (_deferPersist && IsDirty)
        {
            CommitCurrentEdits();
        }
        if (_deferPersist)
        {
            ApplyDefaultsToService();
            _settingsService.SaveInvokeAIModelDefaults();
        }
        DialogResult = true;
    }

    [RelayCommand]
    private void Cancel()
    {
        DialogResult = false;
    }

    public List<ModelDefaults> GetDefaultsSnapshot() => CloneModelDefaults(_defaults);

    private void ApplyDefaultsToService()
    {
        var target = _settingsService.InvokeAIModelDefaults;
        target.Clear();
        target.AddRange(CloneModelDefaults(_defaults));
    }

    private void CommitCurrentEdits()
    {
        var name = SelectedAsset?.Name ?? CurrentModelName;
        if (string.IsNullOrWhiteSpace(name)) return;
        UpsertDefault(name);
        SetDirty(false);
        RebuildAssetGroups();
    }

    private void UpsertDefault(string name)
    {
        var cleaned = BuildDefaultsForSave(name);
        var existingDefault = _defaults.FirstOrDefault(d => string.Equals(d.ModelName, name, StringComparison.OrdinalIgnoreCase));
        if (cleaned == null)
        {
            if (existingDefault != null)
            {
                _defaults.Remove(existingDefault);
            }
        }
        else if (existingDefault != null)
        {
            existingDefault.Sampler = cleaned.Sampler;
            existingDefault.Steps = cleaned.Steps;
            existingDefault.CfgScale = cleaned.CfgScale;
            existingDefault.CfgRescaleMultiplier = cleaned.CfgRescaleMultiplier;
            existingDefault.Width = cleaned.Width;
            existingDefault.Height = cleaned.Height;
            existingDefault.PositivePromptPrefix = cleaned.PositivePromptPrefix;
            existingDefault.NegativePromptPrefix = cleaned.NegativePromptPrefix;
        }
        else
        {
            _defaults.Add(cleaned);
        }
    }

    private void RemoveDefault(string name)
    {
        var existing = _defaults.FirstOrDefault(d => string.Equals(d.ModelName, name, StringComparison.OrdinalIgnoreCase));
        if (existing != null)
        {
            _defaults.Remove(existing);
        }
    }

    private static List<ModelDefaults> CloneModelDefaults(IEnumerable<ModelDefaults> source)
    {
        var list = new List<ModelDefaults>();
        foreach (var item in source)
        {
            list.Add(new ModelDefaults
            {
                ModelName = item.ModelName,
                Sampler = item.Sampler,
                Steps = item.Steps,
                CfgScale = item.CfgScale,
                CfgRescaleMultiplier = item.CfgRescaleMultiplier,
                Width = item.Width,
                Height = item.Height,
                PositivePromptPrefix = item.PositivePromptPrefix,
                NegativePromptPrefix = item.NegativePromptPrefix
            });
        }
        return list;
    }

}
