using Avalonia.Controls;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class ImageInterrogatorWindow : Window
{
    public ImageInterrogatorWindow()
    {
        InitializeComponent();
    }

    public ImageInterrogatorWindow(ImageInterrogatorViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
    }
}
