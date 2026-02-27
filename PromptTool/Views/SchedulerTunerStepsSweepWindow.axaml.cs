using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class SchedulerTunerStepsSweepWindow : Window
{
    public SchedulerTunerStepsSweepWindow()
    {
        InitializeComponent();
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            Close();
            e.Handled = true;
            return;
        }

        base.OnKeyDown(e);
    }

    private void Result_DoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (sender is not Control control) return;
        if (control.DataContext is not SchedulerStepsResultItem item) return;
        if (item.Image == null) return;

        var title = item.Label;
        if (DataContext is SchedulerStepsSweepViewModel vm && !string.IsNullOrWhiteSpace(vm.SchedulerName))
        {
            title = $"{vm.SchedulerName} - {item.Label}";
        }

        var previewVm = new SchedulerTunerImagePreviewViewModel(item.Image, title);
        var win = new SchedulerTunerImagePreviewWindow { DataContext = previewVm };
        win.Show(this);
    }

    private void Close_Click(object? sender, RoutedEventArgs e)
    {
        Close();
    }
}
