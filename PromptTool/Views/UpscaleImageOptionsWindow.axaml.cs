using System.Linq;
using Avalonia.Controls;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class UpscaleImageOptionsWindow : Window
{
    public UpscaleImageOptionsWindow()
    {
        InitializeComponent();
    }

    public UpscaleImageOptionsWindow(UpscaleImageOptionsViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
    }

    private void Cancel_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        Close(false);
    }

    private void Start_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is UpscaleImageOptionsViewModel vm)
        {
            if (!vm.GetSelectedModels().Any())
            {
                vm.StatusText = "Select at least one upscaler model.";
                return;
            }
            if (!vm.GetSelectedScales().Any())
            {
                vm.StatusText = "Select at least one scale.";
                return;
            }
        }
        Close(true);
    }
}
