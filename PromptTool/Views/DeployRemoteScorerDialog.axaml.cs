using Avalonia.Controls;
using Avalonia.Threading;
using PromptTool.ViewModels;
using System;
using System.ComponentModel;
using System.Threading.Tasks;

namespace PromptTool.Views;

public partial class DeployRemoteScorerDialog : Window
{
    private DeployRemoteScorerDialogViewModel? _vm;
    private EventHandler<bool?>? _requestCloseHandler;

    public DeployRemoteScorerDialog()
    {
        InitializeComponent();
        HookDataContext();
        DataContextChanged += (_, _) => HookDataContext();
        Closed += OnClosed;
    }

    public DeployRemoteScorerDialog(DeployRemoteScorerDialogViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        HookDataContext();
        _requestCloseHandler = (_, result) => Close(result);
        viewModel.RequestClose += _requestCloseHandler;
        Closed += OnClosed;
    }

    private void HookDataContext()
    {
        if (DataContext is not DeployRemoteScorerDialogViewModel vm)
        {
            return;
        }

        if (_vm != null)
        {
            _vm.PropertyChanged -= OnVmPropertyChanged;
        }
        _vm = vm;
        _vm.PropertyChanged += OnVmPropertyChanged;

        vm.CopyToClipboardAsync = async text =>
        {
            if (Clipboard == null) return;
            await Clipboard.SetTextAsync(text);
        };
    }

    private void OnVmPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName != nameof(DeployRemoteScorerDialogViewModel.OutputLog))
        {
            return;
        }

        Dispatcher.UIThread.Post(() =>
        {
            if (OutputLogBox == null)
            {
                return;
            }

            var length = OutputLogBox.Text?.Length ?? 0;
            OutputLogBox.CaretIndex = length;
            OutputLogBox.SelectionStart = length;
            OutputLogBox.SelectionEnd = length;
            OutputLogBox.BringIntoView();
            OutputLogScroll?.ScrollToEnd();
        });
    }

    private void OnClosed(object? sender, System.EventArgs e)
    {
        if (_vm != null)
        {
            _vm.PropertyChanged -= OnVmPropertyChanged;
            if (_requestCloseHandler != null)
            {
                _vm.RequestClose -= _requestCloseHandler;
            }
            _vm = null;
        }

        _requestCloseHandler = null;
    }
}
