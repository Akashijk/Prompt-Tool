using System;
using Avalonia.Controls;
using Avalonia.Markup.Xaml;
using Avalonia.Interactivity;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class WildcardDedupeWindow : Window
{
    public WildcardDedupeWindow()
    {
        InitializeComponent();
    }

    public WildcardDedupeWindow(WildcardDedupeViewModel viewModel) : this()
    {
        DataContext = viewModel;
        Opened += OnOpened;
    }

    private void InitializeComponent()
    {
        AvaloniaXamlLoader.Load(this);
    }

    private async void OnOpened(object? sender, EventArgs e)
    {
        Opened -= OnOpened;
        if (DataContext is WildcardDedupeViewModel vm)
        {
            await vm.ScanCommand.ExecuteAsync(null);
        }
    }

    private async void RefreshScan_Click(object? sender, RoutedEventArgs e)
    {
        if (DataContext is WildcardDedupeViewModel vm)
        {
            await vm.ScanCommand.ExecuteAsync(null);
        }
    }

    private void UseLeftName_Click(object? sender, RoutedEventArgs e)
    {
        if (DataContext is WildcardDedupeViewModel vm)
        {
            vm.UseLeftName();
        }
    }

    private void UseRightName_Click(object? sender, RoutedEventArgs e)
    {
        if (DataContext is WildcardDedupeViewModel vm)
        {
            vm.UseRightName();
        }
    }

    private async void Merge_Click(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardDedupeViewModel vm || vm.SelectedPair == null)
        {
            return;
        }

        var finalName = string.IsNullOrWhiteSpace(vm.MergeTargetName) ? "(blank)" : vm.MergeTargetName.Trim();
        var confirmed = await ConfirmDialog.Show(
            this,
            "Merge wildcard duplicates?",
            $"Merge '{vm.SelectedPair.LeftName}' and '{vm.SelectedPair.RightName}' into '{finalName}'?\n\nThis updates template references and deletes superseded wildcard files.",
            "Yes",
            "No");

        if (!confirmed)
        {
            return;
        }

        await vm.MergeSelectedAsync();
    }

    private void ViewJsonDiff_Click(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardDedupeViewModel vm || vm.SelectedPair == null)
        {
            return;
        }

        var diffVm = new JsonDiffViewModel(
            $"Wildcard Diff: {vm.SelectedPair.LeftName} vs {vm.SelectedPair.RightName}",
            vm.LeftJson,
            vm.RightJson)
        {
            LeftTitle = vm.SelectedPair.LeftName,
            RightTitle = vm.SelectedPair.RightName
        };

        var win = new JsonDiffWindow(diffVm);
        win.Show(this);
    }

    private void Close_Click(object? sender, RoutedEventArgs e)
    {
        Close();
    }
}
