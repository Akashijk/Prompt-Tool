using Avalonia.Controls;
using Avalonia.Platform.Storage;
using System;
using System.Collections.Generic;
using System.Linq;
using System.ComponentModel;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Layout;
using PromptTool.ViewModels;
using PromptTool.Helpers;

namespace PromptTool.Views;

public partial class InvokeAILoraDefaultsWindow : Window
{
    private bool _closePromptActive;

    public InvokeAILoraDefaultsWindow()
    {
        InitializeComponent();
        WireHandlers();
        HookDialogCloseFromDataContext();
        Closing += OnClosing;
    }

    public InvokeAILoraDefaultsWindow(InvokeAILoraDefaultsViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        WireHandlers();
        HookDialogClose(viewModel);
        Closing += OnClosing;
    }

    private void HookDialogCloseFromDataContext()
    {
        DataContextChanged += (_, _) =>
        {
            if (DataContext is InvokeAILoraDefaultsViewModel vm)
            {
                HookDialogClose(vm);
            }
        };
    }

    private void HookDialogClose(InvokeAILoraDefaultsViewModel viewModel)
    {
        viewModel.PropertyChanged += OnViewModelPropertyChanged;
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(InvokeAILoraDefaultsViewModel.DialogResult) &&
            sender is InvokeAILoraDefaultsViewModel vm &&
            vm.DialogResult.HasValue)
        {
            Close(vm.DialogResult.Value);
        }
    }

    private async void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        if (_closePromptActive) return;
        if (DataContext is not InvokeAILoraDefaultsViewModel vm) return;
        if (vm.DialogResult.HasValue) return;
        if (!vm.IsDeferred || !vm.IsDirty) return;

        e.Cancel = true;
        _closePromptActive = true;
        var choice = await ShowUnsavedChangesPromptAsync(
            "Unsaved LoRA defaults",
            "You have unsaved changes. Apply them before closing?",
            applyLabel: "Apply");
        _closePromptActive = false;

        switch (choice)
        {
            case CloseChoice.Save:
                vm.ConfirmCommand.Execute(null);
                break;
            case CloseChoice.Discard:
                Close(false);
                break;
            case CloseChoice.Cancel:
                break;
        }
    }

    private enum CloseChoice
    {
        Save,
        Discard,
        Cancel
    }

    private async Task<CloseChoice> ShowUnsavedChangesPromptAsync(string title, string message, string applyLabel)
    {
        var dialog = new Window
        {
            Title = title,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            SizeToContent = SizeToContent.WidthAndHeight,
            CanResize = false
        };

        var text = new TextBlock
        {
            Text = message,
            TextWrapping = Avalonia.Media.TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 12)
        };

        var saveButton = new Button { Content = applyLabel, MinWidth = 80 };
        var discardButton = new Button { Content = "Discard", MinWidth = 80 };
        var cancelButton = new Button { Content = "Cancel", MinWidth = 80, IsCancel = true };

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Spacing = 8,
            Children = { saveButton, discardButton, cancelButton }
        };

        var panel = new StackPanel
        {
            Margin = new Thickness(12),
            Children = { text, buttons }
        };

        dialog.Content = panel;

        saveButton.Click += (_, _) => dialog.Close(CloseChoice.Save);
        discardButton.Click += (_, _) => dialog.Close(CloseChoice.Discard);
        cancelButton.Click += (_, _) => dialog.Close(CloseChoice.Cancel);

        return await dialog.ShowDialog<CloseChoice>(this);
    }

    private void WireHandlers()
    {
        this.FindControl<Button>("ExportButton")?.AddHandler(Button.ClickEvent, async (_, __) =>
        {
            if (DataContext is not InvokeAILoraDefaultsViewModel vm) return;
            var provider = StorageProvider;
            if (provider == null) return;

            var options = new FilePickerSaveOptions
            {
                Title = "Export LoRA Defaults",
                SuggestedFileName = $"invokeai_lora_defaults_{DateTime.Now:yyyyMMdd_HHmmss}.json",
                FileTypeChoices = new List<FilePickerFileType>
                {
                    new FilePickerFileType("JSON") { Patterns = new[] { "*.json" } }
                }
            };
            var path = await FilePickerHelper.PickSaveFileAsync(provider, options);
            if (string.IsNullOrWhiteSpace(path)) return;
            vm.ExportTo(path);
        });

        this.FindControl<Button>("ImportButton")?.AddHandler(Button.ClickEvent, async (_, __) =>
        {
            if (DataContext is not InvokeAILoraDefaultsViewModel vm) return;
            var provider = StorageProvider;
            if (provider == null) return;

            var options = new FilePickerOpenOptions
            {
                Title = "Import LoRA Defaults",
                AllowMultiple = false,
                FileTypeFilter = new List<FilePickerFileType>
                {
                    new FilePickerFileType("JSON") { Patterns = new[] { "*.json" } }
                }
            };
            var path = await FilePickerHelper.PickOpenFileAsync(provider, options);
            if (string.IsNullOrWhiteSpace(path)) return;
            vm.ImportFrom(path);
        });
    }
}
