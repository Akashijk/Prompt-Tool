using System;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using System.Windows.Input; // Added for ICommand
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Clients; // For OllamaClient

namespace PromptTool.ViewModels;

public partial class PromptEvolverViewModel : ObservableObject
{
    private readonly OllamaClient _ollamaClient;

    [ObservableProperty]
    private string _originalPrompt = "";

    [ObservableProperty]
    private string _evolvedPrompt = "";

    [ObservableProperty]
    private ObservableCollection<string> _ollamaModels = new();

    [ObservableProperty]
    private string? _selectedOllamaModel;

    [ObservableProperty]
    private bool _isBusy = false; // To indicate loading state

    public ICommand EvolveAsyncCommand { get; } // Manually defined command

    public PromptEvolverViewModel(OllamaClient ollamaClient)
    {
        _ollamaClient = ollamaClient;
        LoadOllamaModelsCommand.Execute(null); // Load models on creation

        EvolveAsyncCommand = new AsyncRelayCommand(EvolveAsync, CanEvolve); // Initialize command
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
            EvolvedPrompt = $"Error loading models: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    // Removed [RelayCommand] attribute, method is now directly referenced by the manual command
    private async Task EvolveAsync()
    {
        if (string.IsNullOrWhiteSpace(OriginalPrompt) || string.IsNullOrWhiteSpace(SelectedOllamaModel))
        {
            EvolvedPrompt = "Please enter an original prompt and select an Ollama model.";
            return;
        }

        IsBusy = true;
        try
        {
            // For now, this is a placeholder for prompt evolution logic
            // In a real scenario, this would involve sending the OriginalPrompt to Ollama
            // with specific instructions for evolving it.
            EvolvedPrompt = await _ollamaClient.GenerateAsync(SelectedOllamaModel, $"Evolve the following prompt: {OriginalPrompt}");
        }
        catch (Exception ex)
        {
            EvolvedPrompt = $"Error evolving prompt: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private bool CanEvolve()
    {
        return !IsBusy && !string.IsNullOrWhiteSpace(OriginalPrompt) && !string.IsNullOrWhiteSpace(SelectedOllamaModel);
    }
}
