using Avalonia.Controls;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class EnhancementResultWindow : Window
{
    private bool _autoStarted;

    public EnhancementResultWindow()
    {
        InitializeComponent();
    }

    public EnhancementResultWindow(EnhancementResultViewModel vm)
    {
        InitializeComponent();
        DataContext = vm;
        Opened += (_, __) =>
        {
            if (_autoStarted) return;
            _autoStarted = true;
            if (!vm.IsBusy && !string.IsNullOrWhiteSpace(vm.SelectedModel))
            {
                vm.RegenerateCommand.Execute(null);
            }
        };
        vm.RequestClose += () => Close(vm.Result);
        vm.RequestCopy += text =>
        {
            if (!string.IsNullOrEmpty(text))
            {
                Clipboard?.SetTextAsync(text);
            }
        };
    }
}
