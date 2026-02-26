using Avalonia.Controls;
using PromptTool.ViewModels;
using System.ComponentModel;

namespace PromptTool.Views;

public partial class SystemPromptEditorWindow : Window
{
    public SystemPromptEditorWindow()
    {
        InitializeComponent();
    }

    public SystemPromptEditorWindow(SystemPromptEditorViewModel vm)
    {
        InitializeComponent();
        DataContext = vm;
        vm.PropertyChanged += OnVmPropertyChanged;
    }

    private void OnVmPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (sender is SystemPromptEditorViewModel vm && e.PropertyName == nameof(SystemPromptEditorViewModel.DialogResult) && vm.DialogResult.HasValue)
        {
            Close(vm.DialogResult.Value);
        }
    }
}
