using System;
using System.Threading.Tasks;
using Avalonia.Input.Platform;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;

namespace PromptTool.ViewModels;

public enum ImageDetailMode
{
    History,
    ActiveGeneration
}

public partial class ImageDetailViewModel : ObservableObject
{
    public HistoryEntry Entry { get; }
    public HistoryImage Image { get; }
    public Func<HistoryEntry, HistoryImage, Task>? UpscaleRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? GenerateMoreRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? GenerateSeedVariationsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? GenerateLoraVariationsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? GenerateModelVariationsRequested { get; set; }

    [ObservableProperty] private Bitmap? _bitmap;
    [ObservableProperty] private string _detailsText;
    [ObservableProperty] private string? _processedPrompt;
    [ObservableProperty] private string? _originalPrompt;
    [ObservableProperty] private bool _hasProcessedPrompt;
    [ObservableProperty] private ImageDetailMode _displayMode = ImageDetailMode.History;
    [ObservableProperty] private bool _showHistoryActions = true;
    [ObservableProperty] private bool _canGenerateMore;
    [ObservableProperty] private bool _canGenerateSeedVariations;
    [ObservableProperty] private bool _canGenerateLoraVariations;
    [ObservableProperty] private bool _canGenerateModelVariations;

    public IClipboard? Clipboard { get; set; }

    public ImageDetailViewModel(HistoryEntry entry, HistoryImage image, Bitmap bitmap, string detailsText, string? processedPrompt, string? originalPrompt)
    {
        Entry = entry;
        Image = image;
        _bitmap = bitmap;
        _detailsText = detailsText;
        if (!string.IsNullOrWhiteSpace(processedPrompt) && !string.Equals(processedPrompt, originalPrompt, StringComparison.Ordinal))
        {
            _processedPrompt = processedPrompt;
            _hasProcessedPrompt = true;
        }
        else
        {
            _processedPrompt = null;
            _hasProcessedPrompt = false;
        }
        _originalPrompt = originalPrompt;
    }

    [RelayCommand]
    private async Task CopyText(string? text)
    {
        if (Clipboard == null || string.IsNullOrWhiteSpace(text)) return;
        await Clipboard.SetTextAsync(text);
    }

    [RelayCommand]
    private async Task Upscale()
    {
        if (UpscaleRequested == null) return;
        await UpscaleRequested(Entry, Image);
    }

    [RelayCommand]
    private async Task GenerateMore()
    {
        if (GenerateMoreRequested == null) return;
        await GenerateMoreRequested(Entry, Image);
    }

    [RelayCommand]
    private async Task GenerateSeedVariations()
    {
        if (GenerateSeedVariationsRequested == null) return;
        await GenerateSeedVariationsRequested(Entry, Image);
    }

    [RelayCommand]
    private async Task GenerateLoraVariations()
    {
        if (GenerateLoraVariationsRequested == null) return;
        await GenerateLoraVariationsRequested(Entry, Image);
    }

    [RelayCommand]
    private async Task GenerateModelVariations()
    {
        if (GenerateModelVariationsRequested == null) return;
        await GenerateModelVariationsRequested(Entry, Image);
    }

    public void UpdateGenerationActions()
    {
        var allowActions = DisplayMode == ImageDetailMode.History;
        ShowHistoryActions = allowActions;
        CanGenerateMore = allowActions && GenerateMoreRequested != null;
        CanGenerateSeedVariations = allowActions && GenerateSeedVariationsRequested != null;
        CanGenerateLoraVariations = allowActions && GenerateLoraVariationsRequested != null;
        CanGenerateModelVariations = allowActions && GenerateModelVariationsRequested != null;
    }

    partial void OnDisplayModeChanged(ImageDetailMode value)
    {
        UpdateGenerationActions();
    }
}
