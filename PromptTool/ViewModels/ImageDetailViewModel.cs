using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Avalonia.Input.Platform;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public enum ImageDetailMode
{
    History,
    ActiveGeneration
}

public partial class ImageDetailViewModel : ObservableObject
{
    [ObservableProperty] private HistoryEntry _entry;
    public Func<HistoryEntry, HistoryImage, Task>? UpscaleRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? GenerateMoreRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? GenerateSeedVariationsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? GenerateLoraVariationsRequested { get; set; }
    public Func<HistoryEntry, HistoryImage, Task>? GenerateModelVariationsRequested { get; set; }

    [ObservableProperty] private HistoryImage _image;
    [ObservableProperty] private Bitmap? _bitmap;
    [ObservableProperty] private string _detailsText = string.Empty;
    [ObservableProperty] private string? _processedPrompt;
    [ObservableProperty] private string? _originalPrompt;
    [ObservableProperty] private bool _hasProcessedPrompt;
    [ObservableProperty] private string _currentImagePositionText = string.Empty;
    [ObservableProperty] private bool _canNavigatePrevious;
    [ObservableProperty] private bool _canNavigateNext;
    [ObservableProperty] private ImageDetailMode _displayMode = ImageDetailMode.History;
    [ObservableProperty] private bool _showHistoryActions = true;
    [ObservableProperty] private bool _canGenerateMore;
    [ObservableProperty] private bool _canGenerateSeedVariations;
    [ObservableProperty] private bool _canGenerateLoraVariations;
    [ObservableProperty] private bool _canGenerateModelVariations;
    [ObservableProperty] private bool _isFavorite;
    [ObservableProperty] private string _favoriteButtonText = "Add to Favorites";

    public IClipboard? Clipboard { get; set; }
    public IReadOnlyList<ImageDetailNavigationItem>? NavigationItems { get; private set; }

    public ImageDetailViewModel(HistoryEntry entry, HistoryImage image, Bitmap bitmap, string detailsText, string? processedPrompt, string? originalPrompt)
    {
        _entry = entry;
        _image = image;
        SetDisplayedImage(entry, image, bitmap, detailsText, processedPrompt, originalPrompt);
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
        UpdateCurrentImagePositionText();
    }

    public void SetNavigationItems(IReadOnlyList<ImageDetailNavigationItem>? navigationItems)
    {
        NavigationItems = navigationItems is { Count: > 1 } ? navigationItems : null;
        UpdateCurrentImagePositionText();
    }

    public void SetDisplayedImage(
        HistoryEntry entry,
        HistoryImage image,
        Bitmap bitmap,
        string detailsText,
        string? processedPrompt,
        string? originalPrompt)
    {
        Entry = entry;
        Image = image;
        Bitmap = bitmap;
        DetailsText = detailsText;
        if (!string.IsNullOrWhiteSpace(processedPrompt) && !string.Equals(processedPrompt, originalPrompt, StringComparison.Ordinal))
        {
            ProcessedPrompt = processedPrompt;
            HasProcessedPrompt = true;
        }
        else
        {
            ProcessedPrompt = null;
            HasProcessedPrompt = false;
        }

        OriginalPrompt = originalPrompt;
        UpdateFavoriteState();
        UpdateCurrentImagePositionText();
    }

    public void UpdateFavoriteState()
    {
        IsFavorite = Image.IsFavorite || Entry.IsFavorite;
        FavoriteButtonText = IsFavorite ? "Remove Favorite" : "Add to Favorites";
    }

    private void UpdateCurrentImagePositionText()
    {
        if (DisplayMode != ImageDetailMode.History)
        {
            CurrentImagePositionText = string.Empty;
            CanNavigatePrevious = false;
            CanNavigateNext = false;
            return;
        }

        if (NavigationItems is { Count: > 1 })
        {
            var index = FindNavigationIndex();
            if (index >= 0)
            {
                CurrentImagePositionText = $"Image {index + 1} of {NavigationItems.Count}";
                CanNavigatePrevious = index > 0;
                CanNavigateNext = index < NavigationItems.Count - 1;
                return;
            }
        }

        if (Entry.Images.Count > 1)
        {
            var index = Entry.Images.IndexOf(Image);
            if (index >= 0)
            {
                CurrentImagePositionText = $"Image {index + 1} of {Entry.Images.Count}";
                CanNavigatePrevious = index > 0;
                CanNavigateNext = index < Entry.Images.Count - 1;
                return;
            }
        }

        CurrentImagePositionText = string.Empty;
        CanNavigatePrevious = false;
        CanNavigateNext = false;
    }

    public int FindNavigationIndex()
    {
        if (NavigationItems == null)
        {
            return -1;
        }

        for (var i = 0; i < NavigationItems.Count; i++)
        {
            var item = NavigationItems[i];
            if (ReferenceEquals(item.Entry, Entry) && ReferenceEquals(item.Image, Image))
            {
                return i;
            }
        }

        return -1;
    }
}
