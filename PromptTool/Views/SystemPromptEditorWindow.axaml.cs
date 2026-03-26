using Avalonia.Controls;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class SystemPromptEditorWindow : PropertyChangedDialogWindow<SystemPromptEditorViewModel, bool>
{
    public SystemPromptEditorWindow()
    {
        InitializeComponent();
    }

    public SystemPromptEditorWindow(SystemPromptEditorViewModel vm)
    {
        InitializeComponent();
        DataContext = vm;
    }

    protected override string DialogResultPropertyName => nameof(SystemPromptEditorViewModel.DialogResult);

    protected override bool TryGetDialogResult(SystemPromptEditorViewModel viewModel, out bool result)
    {
        if (viewModel.DialogResult.HasValue)
        {
            result = viewModel.DialogResult.Value;
            return true;
        }

        result = default;
        return false;
    }
}
