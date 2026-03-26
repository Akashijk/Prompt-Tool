using Avalonia.Controls;
using Avalonia.Interactivity;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class ModelSimilarityWindow : Window
{
    public ModelSimilarityWindow()
    {
        InitializeComponent();
        Opened += (_, _) =>
        {
            if (DataContext is ModelSimilarityViewModel vm)
            {
                vm.RunCommand.Execute(null);
            }
        };
    }

    private void LeftImage_DoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not ModelSimilarityViewModel vm)
        {
            return;
        }

        if ((sender as Control)?.DataContext is ModelSimilarityPairMatchViewModel pair)
        {
            vm.ViewLeftDetailsCommand.Execute(pair);
            e.Handled = true;
        }
    }

    private void RightImage_DoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not ModelSimilarityViewModel vm)
        {
            return;
        }

        if ((sender as Control)?.DataContext is ModelSimilarityPairMatchViewModel pair)
        {
            vm.ViewRightDetailsCommand.Execute(pair);
            e.Handled = true;
        }
    }

    private void SiblingImage_DoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not ModelSimilarityViewModel vm)
        {
            return;
        }

        if ((sender as Control)?.DataContext is ModelSimilaritySiblingImageViewModel sibling)
        {
            vm.ViewSiblingDetailsCommand.Execute(sibling);
            e.Handled = true;
        }
    }
}
