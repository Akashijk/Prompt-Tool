using System;
using System.Collections.Generic;
using Avalonia.Controls;
using Avalonia.Input;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class ExperimentRunnerWindow : Window
{
    private ExperimentRunnerViewModel? _attachedVm;

    public ExperimentRunnerWindow()
    {
        InitializeComponent();
        HookViewModel(DataContext as ExperimentRunnerViewModel);
        DataContextChanged += (_, _) => HookViewModel(DataContext as ExperimentRunnerViewModel);
        Closed += (_, _) => HookViewModel(null);
    }

    public ExperimentRunnerWindow(ExperimentRunnerViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        HookViewModel(viewModel);
        Closed += (_, _) => HookViewModel(null);
    }

    private void HookViewModel(ExperimentRunnerViewModel? viewModel)
    {
        if (_attachedVm != null)
        {
            _attachedVm.RequestClose -= OnRequestClose;
        }

        _attachedVm = viewModel;
        if (_attachedVm == null)
        {
            return;
        }

        _attachedVm.RequestClose += OnRequestClose;
    }

    private void OnRequestClose(object? sender, System.EventArgs e)
    {
        Close(_attachedVm?.DialogResult);
    }

    private void BaselineSegmentPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        _ = ShowBaselineSegmentChoicesAsync(sender, e);
    }

    private async System.Threading.Tasks.Task ShowBaselineSegmentChoicesAsync(object? sender, PointerPressedEventArgs e)
    {
        if (sender is not Control control)
        {
            return;
        }

        if (control.DataContext is not PromptSegmentViewModel segment || !segment.IsWildcard)
        {
            return;
        }

        var point = e.GetCurrentPoint(control);
        if (!point.Properties.IsLeftButtonPressed && !point.Properties.IsRightButtonPressed)
        {
            return;
        }

        if (DataContext is not ExperimentRunnerViewModel vm)
        {
            return;
        }

        var choices = vm.GetChoicesForBaselineSegment(segment);
        if (choices.Count == 0)
        {
            return;
        }

        var menuItems = new List<MenuItem>
        {
            new() { Header = $"Wildcard: {segment.WildcardName}", IsEnabled = false }
        };

        var menu = new ContextMenu { ItemsSource = menuItems };
        foreach (var choice in choices)
        {
            var menuItem = new MenuItem
            {
                Header = choice,
                IsChecked = string.Equals(choice, segment.Text, StringComparison.OrdinalIgnoreCase)
            };
            menuItem.Click += (_, _) =>
            {
                vm.ApplyBaselineChoice(segment, choice);
                menu.Close();
            };
            menuItems.Add(menuItem);
        }

        menu.Open(control);
        await System.Threading.Tasks.Task.CompletedTask;
    }
}
