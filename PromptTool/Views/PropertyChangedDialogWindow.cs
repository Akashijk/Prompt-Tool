using System.ComponentModel;
using Avalonia.Controls;

namespace PromptTool.Views;

public abstract class PropertyChangedDialogWindow<TViewModel, TResult> : Window
    where TViewModel : class, INotifyPropertyChanged
{
    private TViewModel? _attachedViewModel;

    protected PropertyChangedDialogWindow()
    {
        DataContextChanged += OnDataContextChanged;
        Closed += OnWindowClosed;
    }

    protected abstract string DialogResultPropertyName { get; }

    protected abstract bool TryGetDialogResult(TViewModel viewModel, out TResult result);

    protected virtual void HandleViewModelPropertyChanged(TViewModel viewModel, PropertyChangedEventArgs e)
    {
    }

    private void OnDataContextChanged(object? sender, System.EventArgs e)
    {
        AttachViewModel(DataContext as TViewModel);
    }

    private void OnWindowClosed(object? sender, System.EventArgs e)
    {
        AttachViewModel(null);
    }

    private void AttachViewModel(TViewModel? viewModel)
    {
        if (ReferenceEquals(_attachedViewModel, viewModel))
        {
            return;
        }

        if (_attachedViewModel != null)
        {
            _attachedViewModel.PropertyChanged -= OnViewModelPropertyChanged;
        }

        _attachedViewModel = viewModel;

        if (_attachedViewModel != null)
        {
            _attachedViewModel.PropertyChanged += OnViewModelPropertyChanged;
        }
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (sender is not TViewModel viewModel)
        {
            return;
        }

        HandleViewModelPropertyChanged(viewModel, e);

        if (e.PropertyName == DialogResultPropertyName && TryGetDialogResult(viewModel, out var result))
        {
            Close(result);
        }
    }
}
