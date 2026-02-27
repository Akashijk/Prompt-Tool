using Avalonia.Controls;
using PromptTool.ViewModels;
using System;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Interactivity;
using System.Threading.Tasks;
using PromptTool.Core.Services;

namespace PromptTool.Views;

public partial class ImageGenerationDialog : Window
{
    private bool _stateRestored;

    public ImageGenerationDialog()
    {
        InitializeComponent();
        Closing += (_, __) => SaveWindowState();
        RestoreWindowState();
    }

    public ImageGenerationDialog(ImageGenerationOptionsViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        viewModel.RequestClose += (sender, e) => Close();
        Closed += OnClosedUnloadModels;
        Closing += (_, __) => SaveWindowState();
        RestoreWindowState();
    }

    private async void OnClosedUnloadModels(object? sender, EventArgs e)
    {
        if (Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime lifetime &&
            lifetime.MainWindow?.DataContext is MainWindowViewModel vm)
        {
            await vm.UnloadModelsAsync();
        }
    }

    private SettingsService? GetSettingsService()
    {
        return (Application.Current as App)?.SettingsService;
    }

    private void RestoreWindowState()
    {
        if (_stateRestored)
        {
            return;
        }
        _stateRestored = true;

        var settings = GetSettingsService()?.Settings;
        if (settings == null)
        {
            return;
        }

        if (Enum.TryParse<WindowState>(settings.ImageGenerationDialogState, out var state) && state != WindowState.Normal)
        {
            WindowState = state;
            return;
        }

        if (settings.ImageGenerationDialogWidth > 0 && settings.ImageGenerationDialogHeight > 0)
        {
            Width = settings.ImageGenerationDialogWidth;
            Height = settings.ImageGenerationDialogHeight;
        }

        if (settings.ImageGenerationDialogX != 0 || settings.ImageGenerationDialogY != 0)
        {
            Position = new PixelPoint((int)settings.ImageGenerationDialogX, (int)settings.ImageGenerationDialogY);
        }

        WindowState = WindowState.Normal;
    }

    private void SaveWindowState()
    {
        var settingsService = GetSettingsService();
        if (settingsService == null)
        {
            return;
        }
        var settings = settingsService.Settings;

        settings.ImageGenerationDialogState = WindowState.ToString();
        if (WindowState == WindowState.Normal)
        {
            var bounds = Bounds;
            if (bounds.Width > 0 && bounds.Height > 0)
            {
                settings.ImageGenerationDialogWidth = bounds.Width;
                settings.ImageGenerationDialogHeight = bounds.Height;
                settings.ImageGenerationDialogX = bounds.X;
                settings.ImageGenerationDialogY = bounds.Y;
            }
        }

        _ = settingsService.SaveSettingsAsync(settings);
    }

    private async void OnGenerateClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not ImageGenerationOptionsViewModel viewModel)
        {
            return;
        }

        if (viewModel.HasUnsavedNegativePromptChanges)
        {
            var choice = await NegativePromptSaveDialog.ShowAsync(this, viewModel.SelectedNegativePreset?.Key ?? "");
            var proceed = await HandleNegativePromptChoiceAsync(viewModel, choice);
            if (!proceed)
            {
                return;
            }
        }

        if (viewModel.GenerateCommand.CanExecute(null))
        {
            viewModel.GenerateCommand.Execute(null);
        }
    }

    private async Task<bool> HandleNegativePromptChoiceAsync(ImageGenerationOptionsViewModel viewModel, NegativePromptSaveChoice choice)
    {
        switch (choice)
        {
            case NegativePromptSaveChoice.Overwrite:
                if (viewModel.SelectedNegativePreset == null)
                {
                    return await SaveAsNewAsync(viewModel);
                }
                return await viewModel.SaveNegativePromptPresetAsync(viewModel.SelectedNegativePreset.Key, overwriteExisting: true);
            case NegativePromptSaveChoice.SaveAsNew:
                return await SaveAsNewAsync(viewModel);
            case NegativePromptSaveChoice.Skip:
                return true;
            default:
                return false;
        }
    }

    private async Task<bool> SaveAsNewAsync(ImageGenerationOptionsViewModel viewModel)
    {
        var suggested = viewModel.GetSuggestedPresetName();
        var name = await TextInputDialog.ShowAsync("Save Negative Prompt", "Preset name:", suggested, this);
        if (string.IsNullOrWhiteSpace(name))
        {
            return false;
        }

        if (!await viewModel.SaveNegativePromptPresetAsync(name, overwriteExisting: false))
        {
            var overwrite = await ConfirmDialog.Show(this, "Preset exists", "A preset with that name already exists. Overwrite it?");
            if (!overwrite)
            {
                return false;
            }
            return await viewModel.SaveNegativePromptPresetAsync(name, overwriteExisting: true);
        }

        return true;
    }
}
