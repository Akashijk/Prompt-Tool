using Avalonia.Controls;
using Avalonia.Platform.Storage;
using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using PromptTool.ViewModels;
using PromptTool.Helpers;

namespace PromptTool.Views;

public partial class InvokeAIModelDefaultsWindow : PropertyChangedDialogWindow<InvokeAIModelDefaultsViewModel, bool>
{
    private bool _closePromptActive;

    public InvokeAIModelDefaultsWindow()
    {
        InitializeComponent();
        WireHandlers();
        Closing += OnClosing;
    }

    public InvokeAIModelDefaultsWindow(InvokeAIModelDefaultsViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        WireHandlers();
        Closing += OnClosing;
    }

    protected override string DialogResultPropertyName => nameof(InvokeAIModelDefaultsViewModel.DialogResult);

    protected override bool TryGetDialogResult(InvokeAIModelDefaultsViewModel viewModel, out bool result)
    {
        if (viewModel.DialogResult.HasValue)
        {
            result = viewModel.DialogResult.Value;
            return true;
        }

        result = default;
        return false;
    }

    private async void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        if (_closePromptActive) return;
        if (DataContext is not InvokeAIModelDefaultsViewModel vm) return;
        if (vm.DialogResult.HasValue) return;
        if (!vm.IsDeferred || !vm.IsDirty) return;

        e.Cancel = true;
        _closePromptActive = true;
        var choice = await WindowClosePrompt.ShowAsync(
            this,
            "Unsaved model defaults",
            "You have unsaved changes. Apply them before closing?",
            applyLabel: "Apply");
        _closePromptActive = false;

        switch (choice)
        {
            case WindowCloseChoice.Save:
                vm.ConfirmCommand.Execute(null);
                break;
            case WindowCloseChoice.Discard:
                Close(false);
                break;
            case WindowCloseChoice.Cancel:
                break;
        }
    }

    private void WireHandlers()
    {
        this.FindControl<Button>("ExportButton")?.AddHandler(Button.ClickEvent, async (_, __) =>
        {
            if (DataContext is not InvokeAIModelDefaultsViewModel vm) return;
            var provider = StorageProvider;
            if (provider == null) return;

            var options = new FilePickerSaveOptions
            {
                Title = "Export Model Defaults",
                SuggestedFileName = $"invokeai_model_defaults_{DateTime.Now:yyyyMMdd_HHmmss}.json",
                FileTypeChoices = new List<FilePickerFileType>
                {
                    new FilePickerFileType("JSON") { Patterns = new[] { "*.json" } }
                }
            };
            var path = await FilePickerHelper.PickSaveFileAsync(provider, options);
            if (string.IsNullOrWhiteSpace(path)) return;
            vm.ExportAll(path);
        });

        this.FindControl<Button>("ImportButton")?.AddHandler(Button.ClickEvent, async (_, __) =>
        {
            if (DataContext is not InvokeAIModelDefaultsViewModel vm) return;
            var provider = StorageProvider;
            if (provider == null) return;

            var options = new FilePickerOpenOptions
            {
                Title = "Import Model Defaults",
                AllowMultiple = false,
                FileTypeFilter = new List<FilePickerFileType>
                {
                    new FilePickerFileType("JSON") { Patterns = new[] { "*.json" } }
                }
            };
            var path = await FilePickerHelper.PickOpenFileAsync(provider, options);
            if (string.IsNullOrWhiteSpace(path)) return;
            vm.ImportAll(path);
        });
    }

}
