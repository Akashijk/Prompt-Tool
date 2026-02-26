using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using CommunityToolkit.Mvvm.ComponentModel;
using PromptTool.Core.Clients.InvokeAI;

namespace PromptTool.ViewModels;

public partial class UpscaleImageOptionsViewModel : ObservableObject
{
    [ObservableProperty] private ObservableCollection<UpscaleModelOption> _modelOptions = new();
    [ObservableProperty] private ObservableCollection<UpscaleScaleOption> _scaleOptions = new();
    [ObservableProperty] private ObservableCollection<int> _tileSizeOptions = new();
    [ObservableProperty] private int _selectedTileSize = 512;
    [ObservableProperty] private bool _fitToMultipleOf8;
    [ObservableProperty] private bool _runInParallel;
    [ObservableProperty] private bool _hasModels;
    [ObservableProperty] private string _statusText = "";

    public UpscaleImageOptionsViewModel()
    {
        ScaleOptions = new ObservableCollection<UpscaleScaleOption>
        {
            new(1.5, false),
            new(2.0, true),
            new(3.0, false),
            new(4.0, false)
        };
        TileSizeOptions = new ObservableCollection<int> { 0, 256, 512, 1024 };
        SelectedTileSize = 512;
        FitToMultipleOf8 = true;
    }

    public void SetModels(IReadOnlyList<InvokeAIModel> models)
    {
        ModelOptions = new ObservableCollection<UpscaleModelOption>(
            models.Select((m, idx) => new UpscaleModelOption(m, idx == 0)));
        HasModels = ModelOptions.Count > 0;
        StatusText = HasModels ? "" : "No upscaler models found on InvokeAI.";
    }

    public IReadOnlyList<InvokeAIModel> GetSelectedModels()
    {
        return ModelOptions.Where(m => m.IsSelected).Select(m => m.Model).ToList();
    }

    public IReadOnlyList<double> GetSelectedScales()
    {
        return ScaleOptions.Where(s => s.IsSelected).Select(s => s.Scale).ToList();
    }
}

public partial class UpscaleModelOption : ObservableObject
{
    public InvokeAIModel Model { get; }
    public string Name => Model.Name;
    [ObservableProperty] private bool _isSelected;

    public UpscaleModelOption(InvokeAIModel model, bool isSelected)
    {
        Model = model;
        _isSelected = isSelected;
    }
}

public partial class UpscaleScaleOption : ObservableObject
{
    public double Scale { get; }
    [ObservableProperty] private bool _isSelected;

    public UpscaleScaleOption(double scale, bool isSelected)
    {
        Scale = scale;
        _isSelected = isSelected;
    }
}
