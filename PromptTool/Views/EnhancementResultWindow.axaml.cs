using Avalonia.Controls;
using PromptTool.ViewModels;
using System;

namespace PromptTool.Views;

public partial class EnhancementResultWindow : Window
{
    private bool _autoStarted;
    private EnhancementResultViewModel? _attachedVm;
    private Action? _requestCloseHandler;
    private Action<string>? _requestCopyHandler;

    public EnhancementResultWindow()
    {
        InitializeComponent();
    }

    public EnhancementResultWindow(EnhancementResultViewModel vm)
    {
        InitializeComponent();
        DataContext = vm;
        _attachedVm = vm;
        Opened += (_, __) =>
        {
            if (_autoStarted) return;
            _autoStarted = true;
            if (!vm.IsBusy && !string.IsNullOrWhiteSpace(vm.SelectedModel))
            {
                vm.RegenerateCommand.Execute(null);
            }
        };
        _requestCloseHandler = () => Close(vm.Result);
        vm.RequestClose += _requestCloseHandler;
        _requestCopyHandler = text =>
        {
            if (!string.IsNullOrEmpty(text))
            {
                Clipboard?.SetTextAsync(text);
            }
        };
        vm.RequestCopy += _requestCopyHandler;
        Closed += OnClosed;
    }

    private void OnClosed(object? sender, System.EventArgs e)
    {
        if (_attachedVm != null)
        {
            if (_requestCloseHandler != null)
            {
                _attachedVm.RequestClose -= _requestCloseHandler;
            }

            if (_requestCopyHandler != null)
            {
                _attachedVm.RequestCopy -= _requestCopyHandler;
            }

            _attachedVm = null;
        }

        _requestCloseHandler = null;
        _requestCopyHandler = null;
    }
}
