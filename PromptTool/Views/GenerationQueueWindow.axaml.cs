using Avalonia.Controls;

namespace PromptTool.Views;

public partial class GenerationQueueWindow : Window
{
    public GenerationQueueWindow()
    {
        InitializeComponent();
    }

    private void OnSelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (DataContext is not ViewModels.GenerationQueueViewModel vm)
        {
            return;
        }

        if (sender is DataGrid grid)
        {
            vm.SelectedJobs = grid.SelectedItems;
        }
    }
}
