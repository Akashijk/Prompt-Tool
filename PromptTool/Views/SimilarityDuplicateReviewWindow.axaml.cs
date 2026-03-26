using Avalonia.Controls;
using Avalonia.Interactivity;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class SimilarityDuplicateReviewWindow : Window
{
    public SimilarityDuplicateReviewWindow()
    {
        InitializeComponent();
    }

    private void OpenSourceDetails_Click(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not SimilarityDuplicateReviewViewModel vm ||
            (sender as Control)?.DataContext is not SimilarityDuplicateReviewItemViewModel item)
        {
            return;
        }

        vm.ViewSourceDetailsCommand.Execute(item);
        e.Handled = true;
    }

    private void OpenMatchDetails_Click(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not SimilarityDuplicateReviewViewModel vm ||
            (sender as Control)?.DataContext is not SimilarityDuplicateReviewItemViewModel item)
        {
            return;
        }

        vm.ViewMatchDetailsCommand.Execute(item);
        e.Handled = true;
    }

    private void ComparePair_Click(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not SimilarityDuplicateReviewViewModel vm ||
            (sender as Control)?.DataContext is not SimilarityDuplicateReviewItemViewModel item)
        {
            return;
        }

        vm.ComparePairCommand.Execute(item);
        e.Handled = true;
    }
}
