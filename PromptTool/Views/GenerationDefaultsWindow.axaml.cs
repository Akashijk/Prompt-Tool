using Avalonia.Controls;
using PromptTool.ViewModels;
using System.ComponentModel;
using System.Threading.Tasks;
using Avalonia.Layout;
using Avalonia;

namespace PromptTool.Views;

public partial class GenerationDefaultsWindow : Window
{
    private bool _closePromptActive;

    public GenerationDefaultsWindow()
    {
        InitializeComponent();
        HookDialogCloseFromDataContext();
        Closing += OnClosing;
    }

    public GenerationDefaultsWindow(GenerationDefaultsViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        HookDialogClose(viewModel);
        Closing += OnClosing;
    }

    private void HookDialogCloseFromDataContext()
    {
        this.DataContextChanged += (_, _) =>
        {
            if (DataContext is GenerationDefaultsViewModel vm)
            {
                HookDialogClose(vm);
            }
        };
    }

    private void HookDialogClose(GenerationDefaultsViewModel viewModel)
    {
        viewModel.PropertyChanged += OnViewModelPropertyChanged;
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(GenerationDefaultsViewModel.DialogResult) && sender is GenerationDefaultsViewModel vm && vm.DialogResult.HasValue)
        {
            Close(vm.DialogResult.Value);
        }
    }

    private async void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        if (_closePromptActive) return;
        if (DataContext is not GenerationDefaultsViewModel vm) return;
        if (vm.DialogResult.HasValue) return;
        if (!vm.HasPendingChanges()) return;

        e.Cancel = true;
        _closePromptActive = true;
        var choice = await ShowUnsavedChangesPromptAsync(
            "Unsaved defaults",
            "You have unsaved changes. Save them before closing?");
        _closePromptActive = false;

        switch (choice)
        {
            case CloseChoice.Save:
                vm.SaveCommand.Execute(null);
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

    private async Task<CloseChoice> ShowUnsavedChangesPromptAsync(string title, string message)
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

        var saveButton = new Button { Content = "Save", MinWidth = 80 };
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
}
