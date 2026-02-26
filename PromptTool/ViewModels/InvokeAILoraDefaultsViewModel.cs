using System;
using System.Collections.ObjectModel;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Clients;
using PromptTool.Core.Models;
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Services;
using System.IO;
using System.Text.Json;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class InvokeAILoraDefaultsViewModel : ObservableObject
{
    private readonly SettingsService _settingsService;
    private readonly InvokeAIClient _invokeAIClient;
    private readonly NotificationService? _notifications;
    private readonly bool _deferPersist;
    private readonly List<ModelDefaults> _defaults;
    private bool _suppressLoraSelectionSync;
    private bool _suppressDirty;
    private List<InvokeAIModel> _allAssets = new();
    private string? _lastSelectedAssetName;
    private bool _suppressSelectionRestore;

    [ObservableProperty]
    private ObservableCollection<ModelDefaults> _loraDefaults = new();

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
    private string _windowTitle = "InvokeAI LoRA Defaults";

    [ObservableProperty]
    private bool _isDeferred;

    [ObservableProperty]
    private bool? _dialogResult;

    [ObservableProperty]
    private string _saveButtonLabel = "Save Current";

    [ObservableProperty]
    private ModelDefaults? _selectedLoraDefault;

    [ObservableProperty]
    private string _currentLoraName = "";

    [ObservableProperty]
    private string _currentSampler = "";

    [ObservableProperty]
    private int _currentSteps = 30;

    [ObservableProperty]
    private double _currentCfgScale = 7.0;

    [ObservableProperty]
    private double _currentCfgRescaleMultiplier = 0.0;

    [ObservableProperty]
    private int _currentWidth = 512;

    [ObservableProperty]
    private int _currentHeight = 512;

    [ObservableProperty]
    private string _currentPositivePromptPrefix = "";

    [ObservableProperty]
    private string _currentNegativePromptPrefix = "";

    [ObservableProperty]
    private bool _useWeightOverride;

    [ObservableProperty]
    private double _currentLoraWeight = 0.75;

    [ObservableProperty]
    private string _statusMessage = "";

    public ObservableCollection<string> AvailableLoras { get; } = new();

    public InvokeAILoraDefaultsViewModel(
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
        _defaults = initialDefaults != null ? CloneModelDefaults(initialDefaults) : _settingsService.InvokeAILoraDefaults;
        IsDeferred = _deferPersist;
        SaveButtonLabel = _deferPersist ? "Apply" : "Save Current";
        LoadLoraDefaultsCommand.Execute(null);
        LoadAvailableLorasCommand.Execute(null);
    }

    [RelayCommand]
    private async Task LoadLoraDefaultsAsync()
    {
        LoraDefaults = new ObservableCollection<ModelDefaults>(CloneModelDefaults(_defaults));
        RebuildAssetGroups();
    }

    [RelayCommand]
    private async Task LoadAvailableLorasAsync()
    {
        StatusMessage = "";
        AvailableLoras.Clear();
        try
        {
            var loras = new List<InvokeAIModel>();
            foreach (var baseModel in new[] { "sdxl", "sd-1.5" })
            {
                var batch = await _invokeAIClient.GetModelsAsync(baseModel: baseModel, modelType: "lora");
                loras.AddRange(batch);
            }
            _allAssets = loras
                .GroupBy(l => l.Key ?? l.Name, StringComparer.OrdinalIgnoreCase)
                .Select(g => g.First())
                .ToList();
            UpdateBaseModelTypes();
            foreach (var lora in _allAssets)
            {
                AvailableLoras.Add(lora.Name);
            }
            if (AvailableLoras.Count == 0)
            {
                StatusMessage = "InvokeAI is unreachable; showing saved LoRA defaults only.";
            }
        }
        catch (Exception ex)
        {
            StatusMessage = $"Failed to load LoRAs from InvokeAI: {ex.Message}";
            _notifications?.ShowWarning("InvokeAI not reachable; showing saved LoRA defaults only.", "Offline");
            _allAssets = new List<InvokeAIModel>();
            UpdateBaseModelTypes();
        }
        _lastSelectedAssetName ??= _defaults.FirstOrDefault()?.ModelName;
        RebuildAssetGroups();
    }

    partial void OnSelectedLoraDefaultChanged(ModelDefaults? value)
    {
        if (_suppressLoraSelectionSync)
        {
            return;
        }

        _suppressLoraSelectionSync = true;
        if (value != null)
        {
            CurrentLoraName = value.ModelName;
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
        _suppressLoraSelectionSync = false;
    }

    partial void OnCurrentLoraNameChanged(string value)
    {
        if (_suppressLoraSelectionSync)
        {
            return;
        }

        var match = LoraDefaults.FirstOrDefault(d => string.Equals(d.ModelName, value, StringComparison.OrdinalIgnoreCase));
        if (match == null)
        {
            return;
        }

        _suppressLoraSelectionSync = true;
        SelectedLoraDefault = match;
        _suppressLoraSelectionSync = false;
    }

    [RelayCommand]
    private void NewLoraDefault()
    {
        _suppressLoraSelectionSync = true;
        ClearCurrentEditFields();
        SelectedLoraDefault = null;
        if (AvailableLoras.Any() && string.IsNullOrWhiteSpace(CurrentLoraName))
        {
            CurrentLoraName = AvailableLoras.First();
        }
        _suppressLoraSelectionSync = false;
    }

    [RelayCommand]
    private async Task SaveLoraDefaultAsync()
    {
        var name = SelectedAsset?.Name ?? CurrentLoraName;
        if (string.IsNullOrWhiteSpace(name)) return;

        UpsertDefault(name);
        if (!_deferPersist)
        {
            var ok = _settingsService.SaveInvokeAILoraDefaults();
            if (ok)
            {
                _notifications?.ShowInfo("LoRA defaults saved.", "Success");
            }
            else
            {
                _notifications?.ShowError("Failed to save LoRA defaults.", "Error");
            }
        }

        await LoadLoraDefaultsAsync();
        SelectedLoraDefault = LoraDefaults.FirstOrDefault(d => string.Equals(d.ModelName, name, StringComparison.OrdinalIgnoreCase));
        SetDirty(false);
    }

    [RelayCommand]
    private async Task DeleteLoraDefaultAsync()
    {
        if (SelectedLoraDefault == null) return;
        RemoveDefault(SelectedLoraDefault.ModelName);
        if (!_deferPersist)
        {
            var ok = _settingsService.SaveInvokeAILoraDefaults();
            if (ok)
            {
                _notifications?.ShowInfo("LoRA default deleted.", "Success");
            }
            else
            {
                _notifications?.ShowError("Failed to save after deletion.", "Error");
            }
        }
        await LoadLoraDefaultsAsync();
        SelectedLoraDefault = null;
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
        WindowTitle = value ? "InvokeAI LoRA Defaults *" : "InvokeAI LoRA Defaults";
        OnPropertyChanged(nameof(CanSave));
    }

    private void ClearCurrentEditFields()
    {
        CurrentLoraName = "";
        CurrentSampler = "";
        CurrentSteps = 0;
        CurrentCfgScale = 0.0;
        CurrentCfgRescaleMultiplier = 0.0;
        CurrentWidth = 0;
        CurrentHeight = 0;
        CurrentPositivePromptPrefix = "";
        CurrentNegativePromptPrefix = "";
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
        CurrentLoraName = assetName;
        if (defaults == null)
        {
            CurrentPositivePromptPrefix = "";
            CurrentNegativePromptPrefix = "";
            UseWeightOverride = false;
            CurrentLoraWeight = 0.75;
        }
        else
        {
            CurrentPositivePromptPrefix = defaults.PositivePromptPrefix;
            CurrentNegativePromptPrefix = defaults.NegativePromptPrefix;
            UseWeightOverride = defaults.LoraWeight.HasValue;
            CurrentLoraWeight = defaults.LoraWeight ?? 0.75;
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
        var pos = CurrentPositivePromptPrefix?.Trim() ?? string.Empty;
        var neg = CurrentNegativePromptPrefix?.Trim() ?? string.Empty;
        var weight = UseWeightOverride ? CurrentLoraWeight : (double?)null;
        if (string.IsNullOrWhiteSpace(pos) && string.IsNullOrWhiteSpace(neg) && !weight.HasValue)
        {
            return null;
        }

        return new ModelDefaults
        {
            ModelName = assetName,
            PositivePromptPrefix = pos,
            NegativePromptPrefix = neg,
            Sampler = string.Empty,
            Steps = 0,
            CfgScale = 0,
            CfgRescaleMultiplier = 0,
            Width = 0,
            Height = 0,
            LoraWeight = weight
        };
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

    partial void OnCurrentLoraWeightChanged(double value)
    {
        if (UseWeightOverride)
        {
            MarkDirty();
        }
    }

    partial void OnUseWeightOverrideChanged(bool value)
    {
        MarkDirty();
    }

    private void SetDirty(bool value)
    {
        IsDirty = value;
        OnPropertyChanged(nameof(CanSave));
    }

    public bool ExportTo(string path)
    {
        try
        {
            var options = new JsonSerializerOptions { WriteIndented = true };
            var json = JsonSerializer.Serialize(_defaults, options);
            File.WriteAllText(path, json);
            return true;
        }
        catch
        {
            return false;
        }
    }

    public bool ImportFrom(string path)
    {
        try
        {
            var json = File.ReadAllText(path);
            var list = JsonSerializer.Deserialize<ObservableCollection<ModelDefaults>>(json) ?? new ObservableCollection<ModelDefaults>();
            _defaults.Clear();
            _defaults.AddRange(list);
            if (!_deferPersist)
            {
                _settingsService.SaveInvokeAILoraDefaults();
            }
            LoadLoraDefaultsCommand.Execute(null);
            return true;
        }
        catch
        {
            return false;
        }
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
            _settingsService.SaveInvokeAILoraDefaults();
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
        var target = _settingsService.InvokeAILoraDefaults;
        target.Clear();
        target.AddRange(CloneModelDefaults(_defaults));
    }

    private void CommitCurrentEdits()
    {
        var name = SelectedAsset?.Name ?? CurrentLoraName;
        if (string.IsNullOrWhiteSpace(name)) return;
        UpsertDefault(name);
        SetDirty(false);
        RebuildAssetGroups();
    }

    private void UpsertDefault(string name)
    {
        var cleaned = BuildDefaultsForSave(name);
        var existing = _defaults.FirstOrDefault(d => string.Equals(d.ModelName, name, StringComparison.OrdinalIgnoreCase));
        if (cleaned == null)
        {
            if (existing != null)
            {
                _defaults.Remove(existing);
            }
        }
        else if (existing != null)
        {
            existing.Sampler = cleaned.Sampler;
            existing.Steps = cleaned.Steps;
            existing.CfgScale = cleaned.CfgScale;
            existing.CfgRescaleMultiplier = cleaned.CfgRescaleMultiplier;
            existing.Width = cleaned.Width;
            existing.Height = cleaned.Height;
            existing.PositivePromptPrefix = cleaned.PositivePromptPrefix;
            existing.NegativePromptPrefix = cleaned.NegativePromptPrefix;
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
