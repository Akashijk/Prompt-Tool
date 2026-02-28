using System;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using System.Windows.Input; // Added for ICommand
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Clients; // For OllamaClient
using Avalonia.Platform.Storage; // For IStorageProvider and StorageFile
using Avalonia.Controls; // For TopLevel
using PromptTool.Helpers;

namespace PromptTool.ViewModels;

public partial class ImageInterrogatorViewModel : ObservableObject
{
    private readonly OllamaClient _ollamaClient;

    [ObservableProperty]
    private string _imagePath = "";

    [ObservableProperty]
    private string _interrogationResult = "";

    [ObservableProperty]
    private ObservableCollection<string> _ollamaModels = new();

    [ObservableProperty]
    private string? _selectedOllamaModel;

    [ObservableProperty]
    private bool _isBusy = false; // To indicate loading state

    public ICommand SelectImageAsyncCommand { get; } // Manually defined command
    public AsyncRelayCommand InterrogateImageAsyncCommand { get; } // Manually defined command

    public ImageInterrogatorViewModel(OllamaClient ollamaClient)
    {
        _ollamaClient = ollamaClient;
        LoadOllamaModelsCommand.Execute(null); // Load models on creation

        SelectImageAsyncCommand = new AsyncRelayCommand<Window?>(SelectImageAsync); // Initialize command, owner is nullable
        InterrogateImageAsyncCommand = new AsyncRelayCommand(InterrogateImageAsync, CanInterrogate); // Initialize command
    }

    [RelayCommand]
    private async Task LoadOllamaModelsAsync()
    {
        IsBusy = true;
        try
        {
            var models = await _ollamaClient.GetModelNamesAsync();
            OllamaModels = new ObservableCollection<string>(models);
            if (OllamaModels.Count > 0)
            {
                SelectedOllamaModel = OllamaModels[0];
            }
        }
        catch (Exception ex)
        {
            InterrogationResult = $"Error loading models: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    // Removed [RelayCommand] attribute, method is now directly referenced by the manual command
    private async Task SelectImageAsync(Window? owner) // Changed to nullable Window?
    {
        if (owner == null) return;

        var storageProvider = owner.StorageProvider;
        if (storageProvider == null) return;

        var path = await FilePickerHelper.PickOpenFileAsync(storageProvider, new FilePickerOpenOptions
        {
            Title = "Select Image File",
            AllowMultiple = false,
            FileTypeFilter = new[]
            {
                new FilePickerFileType("Image Files")
                {
                    Patterns = new[] {"*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif"}
                }
            }
        });

        if (!string.IsNullOrWhiteSpace(path))
        {
            ImagePath = path;
        }
    }


    // Removed [RelayCommand] attribute, method is now directly referenced by the manual command
    private Task InterrogateImageAsync()
    {
        if (string.IsNullOrWhiteSpace(ImagePath) || string.IsNullOrWhiteSpace(SelectedOllamaModel))
        {
            InterrogationResult = "Please select an image and an Ollama model.";
            return Task.CompletedTask;
        }

        IsBusy = true;
        try
        {
            InterrogationResult = "Image interrogation is not available yet. Ollama multimodal support needs to be added.";
        }
        catch (Exception ex)
        {
            InterrogationResult = $"Error interrogating image: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }

        return Task.CompletedTask;
    }

    private bool CanInterrogate()
    {
        return !IsBusy && !string.IsNullOrWhiteSpace(ImagePath) && !string.IsNullOrWhiteSpace(SelectedOllamaModel);
    }

    partial void OnImagePathChanged(string? oldValue, string newValue)
    {
        InterrogateImageAsyncCommand.NotifyCanExecuteChanged();
    }

    partial void OnSelectedOllamaModelChanged(string? oldValue, string? newValue)
    {
        InterrogateImageAsyncCommand.NotifyCanExecuteChanged();
    }
}
