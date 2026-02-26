using Avalonia.Controls;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class BrainstormingWindow : Window
{
    public BrainstormingWindow()
    {
        InitializeComponent();
    }

    public BrainstormingWindow(BrainstormingViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
    }
}
