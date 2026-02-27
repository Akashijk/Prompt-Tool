using System;
using System.Threading.Tasks;
using Avalonia.Controls;
using Microsoft.Extensions.DependencyInjection;
using PromptTool.Core.Clients;
using PromptTool.Core.Models; // Added
using PromptTool.Core.Services; // Added
using Avalonia.Controls.ApplicationLifetimes; // Added
using System.Collections.Generic;
using System.Linq;
using PromptTool.Views;
using PromptTool.ViewModels;

namespace PromptTool.Services;

public class WindowManager : IWindowManager
{
    private readonly IServiceProvider _serviceProvider;

    public WindowManager(IServiceProvider serviceProvider)
    {
        _serviceProvider = serviceProvider;
    }

    public async Task<(bool, List<InvokeAIGenerationParams>?)> ShowImageGenerationOptionsDialog(string initialPrompt, object? owner)
    {
        var viewModel = _serviceProvider.GetRequiredService<ImageGenerationOptionsViewModel>();
        viewModel.Prompt = initialPrompt;

        var dialog = new ImageGenerationDialog(viewModel);

        Window ownerWindow = (owner as Window) ??
                              (App.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow ??
                              throw new InvalidOperationException("Cannot show dialog without a valid owner window.");

        await dialog.ShowDialog(ownerWindow);
        
        return viewModel.Result;
    }

    public void ShowImagePreview(IReadOnlyList<byte[]> images)
    {
        var previewWindow = _serviceProvider.GetRequiredService<MultiImagePreviewView>();
        var previewViewModel = _serviceProvider.GetRequiredService<MultiImagePreviewViewModel>();

        previewViewModel.InitializePlaceholders(images.Count);
        for (var i = 0; i < images.Count; i++)
        {
            previewViewModel.SetImage(i, images[i]);
        }
        previewWindow.DataContext = previewViewModel;
        previewWindow.Show(); // Show non-modally
    }

    public async Task<HistoryEntry?> ShowHistoryViewer(object? owner)
    {
        var historyWindow = _serviceProvider.GetRequiredService<HistoryViewerWindow>();
        var historyViewModel = _serviceProvider.GetRequiredService<HistoryViewerViewModel>();
        
        historyWindow.DataContext = historyViewModel;
        
        // Ensure a valid owner window for ShowDialog
        Window ownerWindow = (owner as Window) ??
                              (App.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow ??
                              throw new InvalidOperationException("Cannot show dialog without a valid owner window.");
        var result = await historyWindow.ShowDialog<HistoryEntry?>(ownerWindow);

        return result;
    }

    public void ShowWildcardManager(object? owner)
    {
        var wildcardManagerWindow = _serviceProvider.GetRequiredService<WildcardManagerWindow>();
        var wildcardManagerViewModel = _serviceProvider.GetRequiredService<WildcardManagerViewModel>();
        
        wildcardManagerWindow.DataContext = wildcardManagerViewModel;
        // Ensure a valid owner window before showing
        if (owner is Window ownerWindow)
        {
            wildcardManagerWindow.Show(ownerWindow); // Show non-modally with owner
        }
        else
        {
            wildcardManagerWindow.Show(); // Show non-modally without owner
        }
    }

    public void ShowBrainstormingWindow(object? owner)
    {
        var brainstormingWindow = _serviceProvider.GetRequiredService<BrainstormingWindow>();
        var brainstormingViewModel = _serviceProvider.GetRequiredService<BrainstormingViewModel>();

        brainstormingWindow.DataContext = brainstormingViewModel;
        // Ensure a valid owner window before showing
        if (owner is Window ownerWindow)
        {
            brainstormingWindow.Show(ownerWindow); // Show non-modally with owner
        }
        else
        {
            brainstormingWindow.Show(); // Show non-modally without owner
        }
    }

    public void ShowImageInterrogatorWindow(object? owner)
    {
        var imageInterrogatorWindow = _serviceProvider.GetRequiredService<ImageInterrogatorWindow>();
        var imageInterrogatorViewModel = _serviceProvider.GetRequiredService<ImageInterrogatorViewModel>();

        imageInterrogatorWindow.DataContext = imageInterrogatorViewModel;
        // Ensure a valid owner window before showing
        if (owner is Window ownerWindow)
        {
            imageInterrogatorWindow.Show(ownerWindow); // Show non-modally with owner
        }
        else
        {
            imageInterrogatorWindow.Show(); // Show non-modally without owner
        }
    }

    public async Task<bool> ShowSettingsWindow(object? owner)
    {
        var settingsWindow = _serviceProvider.GetRequiredService<SettingsWindow>();
        var settingsViewModel = _serviceProvider.GetRequiredService<SettingsViewModel>();

        settingsWindow.DataContext = settingsViewModel;
        
        // Ensure a valid owner window for ShowDialog
        Window ownerWindow = (owner as Window) ??
                              (App.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow ??
                              throw new InvalidOperationException("Cannot show dialog without a valid owner window.");
        var result = await settingsWindow.ShowDialog<bool>(ownerWindow);

        return result;
    }

    public void ShowInvokeAIModelDefaultsWindow(object? owner)
    {
        var invokeAIModelDefaultsWindow = _serviceProvider.GetRequiredService<InvokeAIModelDefaultsWindow>();
        var invokeAIModelDefaultsViewModel = _serviceProvider.GetRequiredService<InvokeAIModelDefaultsViewModel>();

        invokeAIModelDefaultsWindow.DataContext = invokeAIModelDefaultsViewModel;
        // Ensure a valid owner window before showing
        if (owner is Window ownerWindow)
        {
            invokeAIModelDefaultsWindow.Show(ownerWindow); // Show non-modally with owner
        }
        else
        {
            invokeAIModelDefaultsWindow.Show(); // Show non-modally without owner
        }
    }

    public void ShowInvokeAILoraDefaultsWindow(object? owner)
    {
        var win = _serviceProvider.GetRequiredService<InvokeAILoraDefaultsWindow>();
        var vm = _serviceProvider.GetRequiredService<InvokeAILoraDefaultsViewModel>();
        win.DataContext = vm;
        if (owner is Window ownerWindow)
        {
            win.Show(ownerWindow);
        }
        else
        {
            win.Show();
        }
    }

    public void ShowPromptEvolverWindow(object? owner)
    {
        var promptEvolverWindow = _serviceProvider.GetRequiredService<PromptEvolverWindow>();
        var promptEvolverViewModel = _serviceProvider.GetRequiredService<PromptEvolverViewModel>();

        promptEvolverWindow.DataContext = promptEvolverViewModel;
        // Ensure a valid owner window before showing
        if (owner is Window ownerWindow)
        {
            promptEvolverWindow.Show(ownerWindow); // Show non-modally with owner
        }
        else
        {
            promptEvolverWindow.Show(); // Show non-modally without owner
        }
    }

    public void ShowSystemPromptEditorWindow(object? owner)
    {
        var window = _serviceProvider.GetRequiredService<SystemPromptEditorWindow>();
        var vm = _serviceProvider.GetRequiredService<SystemPromptEditorViewModel>();
        window.DataContext = vm;
        if (owner is Window ownerWindow)
        {
            window.Show(ownerWindow);
        }
        else
        {
            window.Show();
        }
    }

}
