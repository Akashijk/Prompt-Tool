using System;
using Avalonia.Controls;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class LoraPermutationDialog : Window
{
    private LoraPermutationDialogViewModel? _attachedVm;
    private EventHandler? _requestCloseHandler;

    public LoraPermutationDialog()
    {
        InitializeComponent();
    }

    public LoraPermutationDialog(LoraPermutationDialogViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        _attachedVm = viewModel;
        _requestCloseHandler = (_, _) => Close();
        viewModel.RequestClose += _requestCloseHandler;
        Closed += OnClosed;
    }

    private void OnClosed(object? sender, EventArgs e)
    {
        if (_attachedVm != null && _requestCloseHandler != null)
        {
            _attachedVm.RequestClose -= _requestCloseHandler;
        }

        _attachedVm = null;
        _requestCloseHandler = null;
    }
}
