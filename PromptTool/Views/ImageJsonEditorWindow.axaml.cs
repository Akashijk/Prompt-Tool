using Avalonia.Controls;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class ImageJsonEditorWindow : Window
{
    public ImageJsonEditorWindow()
    {
        InitializeComponent();
    }

    public ImageJsonEditorWindow(ImageJsonEditorViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
    }

    private void Cancel_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        Close();
    }

    private void Save_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not ImageJsonEditorViewModel vm) return;
        if (!vm.ApplyChanges(out var error))
        {
            vm.StatusText = error;
            return;
        }
        Close();
    }
}
