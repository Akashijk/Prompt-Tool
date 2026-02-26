using System;
using Avalonia.Controls;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class LoraPermutationDialog : Window
{
    public LoraPermutationDialog()
    {
        InitializeComponent();
    }

    public LoraPermutationDialog(LoraPermutationDialogViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        viewModel.RequestClose += (_, _) => Close();
    }
}
