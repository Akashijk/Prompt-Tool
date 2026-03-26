using Avalonia.Controls;
using PromptTool.ViewModels;
using System.Threading.Tasks;

namespace PromptTool.Views;

public partial class GenerationDefaultsWindow : PropertyChangedDialogWindow<GenerationDefaultsViewModel, bool>
{
    private bool _closePromptActive;

    public GenerationDefaultsWindow()
    {
        InitializeComponent();
        Closing += OnClosing;
    }

    public GenerationDefaultsWindow(GenerationDefaultsViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        Closing += OnClosing;
    }

    protected override string DialogResultPropertyName => nameof(GenerationDefaultsViewModel.DialogResult);

    protected override bool TryGetDialogResult(GenerationDefaultsViewModel viewModel, out bool result)
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
        if (DataContext is not GenerationDefaultsViewModel vm) return;
        if (vm.DialogResult.HasValue) return;
        if (!vm.HasPendingChanges()) return;

        e.Cancel = true;
        _closePromptActive = true;
        var choice = await WindowClosePrompt.ShowAsync(
            this,
            "Unsaved defaults",
            "You have unsaved changes. Save them before closing?");
        _closePromptActive = false;

        switch (choice)
        {
            case WindowCloseChoice.Save:
                vm.SaveCommand.Execute(null);
                break;
            case WindowCloseChoice.Discard:
                Close(false);
                break;
            case WindowCloseChoice.Cancel:
                break;
        }
    }
}
