using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using PromptTool.Core.Clients;
using PromptTool.Core.Services;
using PromptTool.Core.Models; // Added for HistoryEntry
using PromptTool.ViewModels;
using System;
using System.IO;

namespace PromptTool.Services;

// This class provides a fake implementation of the OllamaClient for design time.
public class DesignTimeOllamaClient : OllamaClient
{
    // A real HttpClient is not needed for design time, so we pass in a dummy one.
    public DesignTimeOllamaClient() : base(new HttpClient(), null!) { }

    public override Task<IReadOnlyList<string>> GetModelNamesAsync(CancellationToken ct = default)
    {
        var models = new List<string>
        {
            "llama3:latest",
            "mistral:latest",
            "codellama:latest"
        };
        return Task.FromResult<IReadOnlyList<string>>(models);
    }

    public override Task<string> GenerateAsync(string model, string prompt, CancellationToken ct = default, double? temperature = null, double? topP = null)
    {
        return Task.FromResult($"This is a design-time response for the model '{model}' with the prompt: '{prompt}'");
    }
}

// This class provides a mock implementation of IWindowManager for design time.
public class DesignTimeWindowManager : IWindowManager
{
    public Task<(bool, List<InvokeAIGenerationParams>?)> ShowImageGenerationOptionsDialog(string initialPrompt, object? owner)
    {
        return Task.FromResult((false, null as List<InvokeAIGenerationParams>));
    }

    public void ShowImagePreview(IReadOnlyList<byte[]> imageData)
    {
        // Do nothing in design time
    }

    public Task<HistoryEntry?> ShowHistoryViewer(object? owner)
    {
        return Task.FromResult(null as HistoryEntry);
    }

    public void ShowWildcardManager(object? owner)
    {
        // Do nothing in design time
    }

    public void ShowBrainstormingWindow(object? owner)
    {
        // Do nothing in design time
    }

    public void ShowImageInterrogatorWindow(object? owner)
    {
        // Do nothing in design time
    }

    public Task<bool> ShowSettingsWindow(object? owner)
    {
        return Task.FromResult(false); // Do nothing in design time
    }

    public void ShowInvokeAIModelDefaultsWindow(object? owner)
    {
        // Do nothing in design time
    }

    public void ShowPromptEvolverWindow(object? owner)
    {
        // Do nothing in design time
    }

    public void ShowSystemPromptEditorWindow(object? owner)
    {
        // Do nothing in design time
    }

    public void ShowFavoritesViewer(object? owner)
    {
        // Do nothing in design time
    }
}


// This class provides a design-time instance of the MainWindowViewModel.
public class DesignTimeMainWindowViewModel : MainWindowViewModel
{
    public DesignTimeMainWindowViewModel() 
        : base(
            null!, // promptProcessorService
            null!, // wildcardService
            null!, // settingsService
            null!, // systemPromptService
            null!, // ollamaClient
            null!, // invokeAIClient
            null!, // historyManager
            null!, // templateService
            new ModelUsageTracker()
        )
    {
        // Pre-populate properties for the designer.
        PromptText = "A prompt for a story about a brave knight.";
        OutputText = "Once upon a time, in a land filled with dragons and magic, there lived a brave knight named Sir Arthur...";
        StatusText = "Loaded 3 models (Design Time)";
        SelectedModel = "llama3:latest";
        Wildcards = new System.Collections.ObjectModel.ObservableCollection<string> { "mythical_creature", "protagonist_role" };
    }
}
