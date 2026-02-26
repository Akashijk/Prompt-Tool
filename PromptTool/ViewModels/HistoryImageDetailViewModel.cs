using System;
using System.Threading.Tasks;
using Avalonia.Input.Platform;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;

namespace PromptTool.ViewModels;

public partial class HistoryImageDetailViewModel : ObservableObject
{
    public HistoryEntry Entry { get; }
    public HistoryImage Image { get; }
    public Func<HistoryEntry, HistoryImage, Task>? UpscaleRequested { get; set; }

    [ObservableProperty] private Bitmap? _bitmap;
    [ObservableProperty] private string _detailsText;
    [ObservableProperty] private string? _processedPrompt;
    [ObservableProperty] private string? _originalPrompt;
    [ObservableProperty] private bool _hasProcessedPrompt;

    public IClipboard? Clipboard { get; set; }

    public HistoryImageDetailViewModel(HistoryEntry entry, HistoryImage image, Bitmap bitmap, string detailsText, string? processedPrompt, string? originalPrompt)
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
}
