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
using PromptTool.Core.Models;

namespace PromptTool.ViewModels;

public partial class MultiImagePreviewViewModel : ObservableObject
{
    [ObservableProperty]
    private ObservableCollection<ImageSlotViewModel> _slots = new();

    [ObservableProperty]
    private bool? _dialogResult;

    [ObservableProperty]
    private string _statusText = "Generating images...";

    [ObservableProperty]
    private string _progressText = "";

    [ObservableProperty]
    private string _headerContextText = "";

    [ObservableProperty]
    private int _generatedCount;

    [ObservableProperty]
    private int _totalCount;

    [ObservableProperty]
    private bool _showGenerationActions = true;

    public IReadOnlyList<HistoryEntry> SavedEntries { get; private set; } = Array.Empty<HistoryEntry>();

    public CancellationTokenSource? GenerationToken { get; set; }
    private readonly object _pendingVariationJobsLock = new();
    private readonly List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> _pendingVariationJobs = new();

    private Func<ImageSlotViewModel, Task>? _onSaveSlot;
    private Func<Task>? _onSaveCompleted;
    private Func<ImageSlotViewModel, Task>? _onGenerateSeedVariations;
    private Func<ImageSlotViewModel, Task>? _onGenerateModelVariations;
    private Func<ImageSlotViewModel, Task>? _onGenerateLoraVariations;
    private Func<ImageSlotViewModel, Task>? _onEditAndRegenerate;
    private Func<ImageSlotViewModel, Task>? _onPromoteToBase;
    private Func<ImageSlotViewModel, Task>? _onEnhanceFromThis;
    private Action<ImageSlotViewModel>? _onShowFullSize;

    public Func<ImageSlotViewModel, Task>? OnSaveSlot
    {
        get => _onSaveSlot;
        set => _onSaveSlot = value;
    }

    public Func<Task>? OnSaveCompleted
    {
        get => _onSaveCompleted;
        set => _onSaveCompleted = value;
    }

    public Func<ImageSlotViewModel, Task>? OnGenerateSeedVariations
    {
        get => _onGenerateSeedVariations;
        set
        {
            _onGenerateSeedVariations = value;
            SyncSlotActions();
        }
    }

    public Func<ImageSlotViewModel, Task>? OnGenerateModelVariations
    {
        get => _onGenerateModelVariations;
        set
        {
            _onGenerateModelVariations = value;
            SyncSlotActions();
        }
    }

    public Func<ImageSlotViewModel, Task>? OnGenerateLoraVariations
    {
        get => _onGenerateLoraVariations;
        set
        {
            _onGenerateLoraVariations = value;
            SyncSlotActions();
        }
    }

    public Func<ImageSlotViewModel, Task>? OnEditAndRegenerate
    {
        get => _onEditAndRegenerate;
        set
        {
            _onEditAndRegenerate = value;
            SyncSlotActions();
        }
    }

    public Func<ImageSlotViewModel, Task>? OnPromoteToBase
    {
        get => _onPromoteToBase;
        set
        {
            _onPromoteToBase = value;
            SyncSlotActions();
        }
    }

    public Func<ImageSlotViewModel, Task>? OnEnhanceFromThis
    {
        get => _onEnhanceFromThis;
        set
        {
            _onEnhanceFromThis = value;
            SyncSlotActions();
        }
    }

    public Action<ImageSlotViewModel>? OnShowFullSize
    {
        get => _onShowFullSize;
        set
        {
            _onShowFullSize = value;
            SyncSlotActions();
        }
    }

    private void SyncSlotActions()
    {
        foreach (var slot in Slots)
        {
            slot.OnGenerateSeedVariations = _onGenerateSeedVariations;
            slot.OnGenerateModelVariations = _onGenerateModelVariations;
            slot.OnGenerateLoraVariations = _onGenerateLoraVariations;
            slot.OnEditAndRegenerate = _onEditAndRegenerate;
            slot.OnPromoteToBase = _onPromoteToBase;
            slot.OnEnhanceFromThis = _onEnhanceFromThis;
            slot.OnShowFullSize = _onShowFullSize;
            slot.ShowGenerationActions = ShowGenerationActions;
        }
    }

    public void InitializePlaceholders(int count)
    {
        Slots.Clear();
        for (int i = 0; i < count; i++)
        {
            var slot = CreatePlaceholderSlot($"Image {i + 1}");
            Slots.Add(slot);
        }
        SyncProgressFromSlots();
    }

    public ImageSlotViewModel CreatePlaceholderSlot(string label)
    {
        var slot = new ImageSlotViewModel { Label = label, IsLoading = true, IsSelected = true };
        slot.OnGenerateSeedVariations = _onGenerateSeedVariations;
        slot.OnGenerateModelVariations = _onGenerateModelVariations;
        slot.OnGenerateLoraVariations = _onGenerateLoraVariations;
        slot.OnEditAndRegenerate = _onEditAndRegenerate;
        slot.OnPromoteToBase = _onPromoteToBase;
        slot.OnEnhanceFromThis = _onEnhanceFromThis;
        slot.OnShowFullSize = _onShowFullSize;
        slot.ShowGenerationActions = ShowGenerationActions;
        return slot;
    }

    public void SetImage(int index, byte[] data)
    {
        if (index < 0 || index >= Slots.Count) return;

        using var ms = new MemoryStream(data);
        var bmp = new Bitmap(ms);
        var slot = Slots[index];
        var old = slot.Image;
        slot.Image = bmp;
        slot.ImageBytes = data;
        slot.IsLoading = false;
        old?.Dispose();
    }

    public void UpdateSlotImage(ImageSlotViewModel slot, byte[] data)
    {
        var index = Slots.IndexOf(slot);
        if (index >= 0)
        {
            SetImage(index, data);
        }
        else
        {
            using var ms = new MemoryStream(data);
            var old = slot.Image;
            slot.Image = new Bitmap(ms);
            slot.ImageBytes = data;
            slot.IsLoading = false;
            slot.OnGenerateSeedVariations = _onGenerateSeedVariations;
            slot.OnGenerateModelVariations = _onGenerateModelVariations;
            slot.OnGenerateLoraVariations = _onGenerateLoraVariations;
            slot.OnEditAndRegenerate = _onEditAndRegenerate;
            slot.OnPromoteToBase = _onPromoteToBase;
            slot.OnEnhanceFromThis = _onEnhanceFromThis;
            slot.OnShowFullSize = _onShowFullSize;
            slot.ShowGenerationActions = ShowGenerationActions;
            old?.Dispose();
        }
    }

    public void SyncProgressFromSlots()
    {
        TotalCount = Slots.Count;
        GeneratedCount = Slots.Count(s => s.ImageBytes != null);
        UpdateProgressText();
    }

    public void EnqueuePendingVariationJobs(IEnumerable<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> jobs)
    {
        lock (_pendingVariationJobsLock)
        {
            _pendingVariationJobs.AddRange(jobs);
        }
    }

    public List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> TakePendingVariationJobsForModel(string? modelName)
    {
        var key = modelName ?? string.Empty;
        lock (_pendingVariationJobsLock)
        {
            var matches = _pendingVariationJobs
                .Where(job => string.Equals(job.param.Model?.Name ?? string.Empty, key, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (matches.Count == 0)
            {
                return matches;
            }

            foreach (var match in matches)
            {
                _pendingVariationJobs.Remove(match);
            }

            return matches;
        }
    }

    public List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> TakePendingVariationJobs()
    {
        lock (_pendingVariationJobsLock)
        {
            if (_pendingVariationJobs.Count == 0)
            {
                return new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
            }

            var pending = _pendingVariationJobs.ToList();
            _pendingVariationJobs.Clear();
            return pending;
        }
    }

    public void IncrementGenerated()
    {
        GeneratedCount = Math.Min(GeneratedCount + 1, TotalCount);
        UpdateProgressText();
    }

    private void UpdateProgressText()
    {
        ProgressText = TotalCount > 0 ? $"{GeneratedCount}/{TotalCount}" : "";
    }

    public IReadOnlyList<ImageSlotViewModel> GetSelectedSlots()
    {
        var list = new List<ImageSlotViewModel>();
        foreach (var slot in Slots)
        {
            if (slot.IsSelected && slot.ImageBytes != null)
            {
                list.Add(slot);
            }
        }
        return list;
    }

    [RelayCommand]
    private async Task SaveSelected()
    {
        if (OnSaveSlot != null)
        {
            foreach (var slot in GetSelectedSlots())
            {
                await OnSaveSlot(slot);
            }
        }
        if (OnSaveCompleted != null)
        {
            await OnSaveCompleted();
        }
        DialogResult = true;
    }

    [RelayCommand]
    private void Cancel()
    {
        GenerationToken?.Cancel();
        DialogResult = false;
    }

    [RelayCommand]
    private async Task GenerateSeedVariations(ImageSlotViewModel? slot)
    {
        if (slot == null || OnGenerateSeedVariations == null) return;
        await OnGenerateSeedVariations(slot);
    }

    [RelayCommand]
    private async Task GenerateModelVariations(ImageSlotViewModel? slot)
    {
        if (slot == null || OnGenerateModelVariations == null) return;
        await OnGenerateModelVariations(slot);
    }

    [RelayCommand]
    private async Task GenerateLoraVariations(ImageSlotViewModel? slot)
    {
        if (slot == null || OnGenerateLoraVariations == null) return;
        await OnGenerateLoraVariations(slot);
    }

    [RelayCommand]
    private async Task EditAndRegenerate(ImageSlotViewModel? slot)
    {
        if (slot == null || OnEditAndRegenerate == null) return;
        await OnEditAndRegenerate(slot);
    }

    [RelayCommand]
    private async Task PromoteToBase(ImageSlotViewModel? slot)
    {
        if (slot == null || OnPromoteToBase == null) return;
        await OnPromoteToBase(slot);
    }

    [RelayCommand]
    private async Task EnhanceFromThis(ImageSlotViewModel? slot)
    {
        if (slot == null || OnEnhanceFromThis == null) return;
        await OnEnhanceFromThis(slot);
    }

    [RelayCommand]
    private void ShowFullSize(ImageSlotViewModel? slot)
    {
        if (slot == null || OnShowFullSize == null) return;
        OnShowFullSize(slot);
    }
}

public partial class ImageSlotViewModel : ObservableObject
{
    [ObservableProperty] private string _label = "";
    [ObservableProperty] private Bitmap? _image;
    [ObservableProperty] private byte[]? _imageBytes;
    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private bool _isSelected = true;
    [ObservableProperty] private bool _isFavorite;
    [ObservableProperty] private string _modelUsed = "";
    [ObservableProperty] private string _seed = "";
    [ObservableProperty] private string _rootSeedLabel = "";
    [ObservableProperty] private bool _isRootSeed;
    [ObservableProperty] private string _size = "";
    [ObservableProperty] private string _loraLabel = "";
    [ObservableProperty] private string _promptToolTip = "";
    [ObservableProperty] private bool _showGenerationActions = true;
    [ObservableProperty] private int? _generationDurationMs;
    [ObservableProperty] private int? _queueWaitMs;
    [ObservableProperty] private int? _totalDurationMs;
    [ObservableProperty] private string? _generationStatus;
    [ObservableProperty] private string? _errorType;
    [ObservableProperty] private string? _errorMessage;
    [ObservableProperty] private string? _errorTraceback;
    public InvokeAIGenerationParams? GenerationParams { get; set; }
    public string? GenerationGraphJson { get; set; }

    public Func<ImageSlotViewModel, Task>? OnGenerateSeedVariations { get; set; }
    public Func<ImageSlotViewModel, Task>? OnGenerateModelVariations { get; set; }
    public Func<ImageSlotViewModel, Task>? OnGenerateLoraVariations { get; set; }
    public Func<ImageSlotViewModel, Task>? OnEditAndRegenerate { get; set; }
    public Func<ImageSlotViewModel, Task>? OnPromoteToBase { get; set; }
    public Func<ImageSlotViewModel, Task>? OnEnhanceFromThis { get; set; }
    public Action<ImageSlotViewModel>? OnShowFullSize { get; set; }

    [RelayCommand]
    private Task GenerateSeedVariations()
    {
        return OnGenerateSeedVariations?.Invoke(this) ?? Task.CompletedTask;
    }

    [RelayCommand]
    private Task GenerateModelVariations()
    {
        return OnGenerateModelVariations?.Invoke(this) ?? Task.CompletedTask;
    }

    [RelayCommand]
    private Task GenerateLoraVariations()
    {
        return OnGenerateLoraVariations?.Invoke(this) ?? Task.CompletedTask;
    }

    [RelayCommand]
    private Task EditAndRegenerate()
    {
        return OnEditAndRegenerate?.Invoke(this) ?? Task.CompletedTask;
    }

    [RelayCommand]
    private Task PromoteToBase()
    {
        return OnPromoteToBase?.Invoke(this) ?? Task.CompletedTask;
    }

    [RelayCommand]
    private Task EnhanceFromThis()
    {
        return OnEnhanceFromThis?.Invoke(this) ?? Task.CompletedTask;
    }

    [RelayCommand]
    private void ShowFullSize()
    {
        OnShowFullSize?.Invoke(this);
    }
}
