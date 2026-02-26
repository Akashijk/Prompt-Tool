using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System;
using PromptTool.Core.Config;

namespace PromptTool.ViewModels;

public partial class GenerationDefaultsViewModel : ObservableObject
{
    private readonly Dictionary<string, GenerationDefaultsSettings> _defaultsMap = new(StringComparer.OrdinalIgnoreCase);
    private Dictionary<string, GenerationDefaultsSettings> _originalDefaults = new(StringComparer.OrdinalIgnoreCase);
    private string _currentBase = "sdxl";

    [ObservableProperty] private string _defaultScheduler = "dpmpp_2m_k";
    [ObservableProperty] private int _defaultSteps = 30;
    [ObservableProperty] private double _defaultCfgScale = 7.5;
    [ObservableProperty] private double _defaultCfgRescaleMultiplier = 0.0;
    [ObservableProperty] private int _defaultWidth = 1024;
    [ObservableProperty] private int _defaultHeight = 1024;
    [ObservableProperty] private bool _defaultSaveToGallery;
    [ObservableProperty] private string _defaultBaseModelType = "sdxl";

    [ObservableProperty] private ObservableCollection<string> _schedulers = new();
    [ObservableProperty] private ObservableCollection<string> _baseModelTypes = new() { "sdxl", "sd-1.5" };

    [ObservableProperty] private bool? _dialogResult;

    public GenerationDefaultsViewModel()
    {
    }

    public string CurrentBaseModelType => _currentBase;

    public void SetDefaults(Dictionary<string, GenerationDefaultsSettings> defaults, string initialBase)
    {
        _defaultsMap.Clear();
        foreach (var kvp in defaults ?? new Dictionary<string, GenerationDefaultsSettings>(StringComparer.OrdinalIgnoreCase))
        {
            if (kvp.Value == null) continue;
            _defaultsMap[kvp.Key] = Clone(kvp.Value);
        }

        _currentBase = string.IsNullOrWhiteSpace(initialBase) ? "sdxl" : initialBase;
        LoadCurrentDefaults();
        _originalDefaults = GetDefaultsSnapshot();
    }

    public Dictionary<string, GenerationDefaultsSettings> GetDefaultsSnapshot()
    {
        var clone = new Dictionary<string, GenerationDefaultsSettings>(StringComparer.OrdinalIgnoreCase);
        foreach (var kvp in _defaultsMap)
        {
            if (kvp.Value == null) continue;
            clone[kvp.Key] = Clone(kvp.Value);
        }
        return clone;
    }

    public void SetSchedulers(IEnumerable<string> schedulers, string current)
    {
        var list = schedulers?.Distinct().ToList() ?? new List<string>();
        if (!list.Any())
        {
            list.Add(current);
        }
        Schedulers = new ObservableCollection<string>(list);
        DefaultScheduler = list.FirstOrDefault(s => string.Equals(s, current, StringComparison.OrdinalIgnoreCase)) ?? list.First();
    }

    [RelayCommand]
    private void Save()
    {
        StoreCurrentDefaults();
        NormalizeValues();
        DialogResult = true;
    }

    [RelayCommand]
    private void Cancel()
    {
        DialogResult = false;
    }

    public bool HasPendingChanges()
    {
        StoreCurrentDefaults();
        return !DefaultsEqual(_defaultsMap, _originalDefaults);
    }

    private void NormalizeValues()
    {
        DefaultScheduler = string.IsNullOrWhiteSpace(DefaultScheduler) ? "dpmpp_2m_k" : DefaultScheduler.Trim();
        if (DefaultSteps <= 0) DefaultSteps = 30;
        if (DefaultCfgScale <= 0) DefaultCfgScale = 7.5;
        if (DefaultCfgRescaleMultiplier < 0) DefaultCfgRescaleMultiplier = 0;
        if (DefaultWidth <= 0) DefaultWidth = 1024;
        if (DefaultHeight <= 0) DefaultHeight = 1024;
        DefaultBaseModelType = string.IsNullOrWhiteSpace(DefaultBaseModelType) ? "sdxl" : DefaultBaseModelType;
    }

    partial void OnDefaultBaseModelTypeChanged(string value)
    {
        StoreCurrentDefaults();
        var newType = string.IsNullOrWhiteSpace(value) ? "sdxl" : value.ToLowerInvariant();
        _currentBase = newType;
        LoadCurrentDefaults();
    }

    private void LoadCurrentDefaults()
    {
        if (!_defaultsMap.TryGetValue(_currentBase, out var d))
        {
            d = new GenerationDefaultsSettings
            {
                Scheduler = "dpmpp_2m_k",
                Steps = 30,
                CfgScale = 7.5,
                CfgRescaleMultiplier = 0,
                Width = _currentBase == "sd-1.5" ? 512 : 1024,
                Height = _currentBase == "sd-1.5" ? 512 : 1024,
                SaveToGallery = false
            };
            _defaultsMap[_currentBase] = d;
        }

        DefaultScheduler = d.Scheduler;
        DefaultSteps = d.Steps;
        DefaultCfgScale = d.CfgScale;
        DefaultCfgRescaleMultiplier = d.CfgRescaleMultiplier;
        DefaultWidth = d.Width;
        DefaultHeight = d.Height;
        DefaultSaveToGallery = d.SaveToGallery;
        DefaultBaseModelType = _currentBase;
    }

    private void StoreCurrentDefaults()
    {
        NormalizeValues();
        _defaultsMap[_currentBase] = new GenerationDefaultsSettings
        {
            Scheduler = DefaultScheduler,
            Steps = DefaultSteps,
            CfgScale = DefaultCfgScale,
            CfgRescaleMultiplier = DefaultCfgRescaleMultiplier,
            Width = DefaultWidth,
            Height = DefaultHeight,
            SaveToGallery = DefaultSaveToGallery
        };
    }

    private static GenerationDefaultsSettings Clone(GenerationDefaultsSettings src) =>
        new()
        {
            Scheduler = src.Scheduler,
            Steps = src.Steps,
            CfgScale = src.CfgScale,
            CfgRescaleMultiplier = src.CfgRescaleMultiplier,
            Width = src.Width,
            Height = src.Height,
            SaveToGallery = src.SaveToGallery
        };

    private static bool DefaultsEqual(Dictionary<string, GenerationDefaultsSettings> a, Dictionary<string, GenerationDefaultsSettings> b)
    {
        if (a.Count != b.Count) return false;
        foreach (var kvp in a)
        {
            if (!b.TryGetValue(kvp.Key, out var other)) return false;
            if (!string.Equals(kvp.Value.Scheduler, other.Scheduler, StringComparison.OrdinalIgnoreCase)) return false;
            if (kvp.Value.Steps != other.Steps) return false;
            if (Math.Abs(kvp.Value.CfgScale - other.CfgScale) > 0.0001) return false;
            if (Math.Abs(kvp.Value.CfgRescaleMultiplier - other.CfgRescaleMultiplier) > 0.0001) return false;
            if (kvp.Value.Width != other.Width || kvp.Value.Height != other.Height) return false;
            if (kvp.Value.SaveToGallery != other.SaveToGallery) return false;
        }
        return true;
    }
}
