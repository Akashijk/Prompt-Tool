using System;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using System.Windows.Input; // Added for ICommand
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Clients; // For OllamaClient

namespace PromptTool.ViewModels;

public partial class BrainstormingViewModel : ObservableObject
{
    private readonly OllamaClient _ollamaClient;

    [ObservableProperty]
    private string _brainstormingPrompt = "";

    [ObservableProperty]
    private string _brainstormingResult = "";

    [ObservableProperty]
    private ObservableCollection<string> _ollamaModels = new();

    [ObservableProperty]
    private string? _selectedOllamaModel;

    [ObservableProperty]
    private bool _isBusy = false; // To indicate loading state

    public ICommand BrainstormAsyncCommand { get; } // Manually defined command

    public BrainstormingViewModel(OllamaClient ollamaClient)
    {
        _ollamaClient = ollamaClient;
        LoadOllamaModelsCommand.Execute(null); // Load models on creation

        BrainstormAsyncCommand = new AsyncRelayCommand(BrainstormAsync, CanBrainstorm); // Initialize command
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
            BrainstormingResult = $"Error loading models: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    // Removed [RelayCommand] attribute, method is now directly referenced by the manual command
    private async Task BrainstormAsync()
    {
        if (string.IsNullOrWhiteSpace(BrainstormingPrompt) || string.IsNullOrWhiteSpace(SelectedOllamaModel))
        {
            BrainstormingResult = "Please enter a prompt and select a model.";
            return;
        }

        IsBusy = true;
        try
        {
            BrainstormingResult = await _ollamaClient.GenerateAsync(SelectedOllamaModel, BrainstormingPrompt);
        }
        catch (Exception ex)
        {
            BrainstormingResult = $"Error brainstorming: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private bool CanBrainstorm()
    {
        return !IsBusy && !string.IsNullOrWhiteSpace(BrainstormingPrompt) && !string.IsNullOrWhiteSpace(SelectedOllamaModel);
    }
}
