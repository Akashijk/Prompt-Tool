using Avalonia.Controls;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class PromptEvolverWindow : Window
{
    public PromptEvolverWindow()
    {
        InitializeComponent();
    }

    public PromptEvolverWindow(PromptEvolverViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
    }
}
