using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Threading;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class SchedulerTunerWindow : Window
{
    public SchedulerTunerWindow()
    {
        InitializeComponent();
        HookDataContext();
        Closed += OnWindowClosed;
    }

    private void HookDataContext()
    {
        DataContextChanged += (_, _) => WireContext();
        WireContext();
    }

    private void WireContext()
    {
        if (DataContext is not SchedulerTunerViewModel vm) return;
        if (vm.ConfirmDownloadAsync == null)
        {
            vm.ConfirmDownloadAsync = ShowConfirmAsync;
        }
        vm.ScoreStatus = msg => Dispatcher.UIThread.Post(() => vm.StatusText = msg);
        vm.SeedSweepRequested -= OnSeedSweepRequested;
        vm.SeedSweepRequested += OnSeedSweepRequested;
        vm.StepsSweepRequested -= OnStepsSweepRequested;
        vm.StepsSweepRequested += OnStepsSweepRequested;
    }

    private void OnWindowClosed(object? sender, EventArgs e)
    {
        if (DataContext is SchedulerTunerViewModel vm)
        {
            vm.CancelGenerationCommand.Execute(null);
        }
    }

    private void Results_SelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (DataContext is not SchedulerTunerViewModel vm) return;
        vm.CanCompare = GetSelectedResults().Count == 2;
    }

    private void Result_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (sender is not Control control) return;
        if (control.DataContext is not SchedulerResultItem item) return;
        if (ResultsList.SelectedItems == null) return;

        if (ResultsList.SelectedItems.Contains(item))
        {
            ResultsList.SelectedItems.Remove(item);
        }
        else
        {
            ResultsList.SelectedItems.Add(item);
        }

        if (DataContext is SchedulerTunerViewModel vm)
        {
            vm.CanCompare = GetSelectedResults().Count == 2;
        }

        e.Handled = true;
    }

    private void Result_DoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (sender is not Control control) return;
        if (control.DataContext is not SchedulerResultItem item) return;
        var bitmap = item.Slot.Image;
        if (bitmap == null) return;

        var vm = new SchedulerTunerImagePreviewViewModel(bitmap, item.Scheduler);
        var win = new SchedulerTunerImagePreviewWindow { DataContext = vm };
        win.Show(this);
    }

    private void CompareSelected_Click(object? sender, RoutedEventArgs e)
    {
        var selected = GetSelectedResults();
        if (selected.Count != 2) return;

        var left = selected[0];
        var right = selected[1];
        if (left.Slot.Image == null || right.Slot.Image == null) return;

        var vm = new SchedulerTunerImageCompareViewModel(left.Slot.Image, left.Scheduler, right.Slot.Image, right.Scheduler);
        var win = new SchedulerTunerImageCompareWindow { DataContext = vm };
        win.Show(this);
    }

    private void OnSeedSweepRequested(SchedulerSeedSweepRequest request)
    {
        _ = ShowSeedSweepAsync(request);
    }

    private void OnStepsSweepRequested(SchedulerStepsSweepRequest request)
    {
        _ = ShowStepsSweepAsync(request);
    }

    private async Task ShowSeedSweepAsync(SchedulerSeedSweepRequest request)
    {
        if (DataContext is not SchedulerTunerViewModel vm) return;

        var seedVm = new SchedulerSeedSweepViewModel(
            vm.GetInvokeAIClient(),
            vm.GetAestheticScoringService(),
            vm.ConfirmDownloadAsync ?? (_ => Task.FromResult(false)));

        var win = new SchedulerTunerSeedSweepWindow { DataContext = seedVm };
        win.Show(this);

        await seedVm.StartAsync(
            request.Scheduler,
            request.Parameters,
            10,
            request.EnableAestheticScoring,
            request.EnableArtifactHeuristics,
            msg => Dispatcher.UIThread.Post(() => seedVm.StatusText = msg));
    }

    private async Task ShowStepsSweepAsync(SchedulerStepsSweepRequest request)
    {
        if (DataContext is not SchedulerTunerViewModel vm) return;

        var stepsVm = new SchedulerStepsSweepViewModel(
            vm.GetInvokeAIClient(),
            vm.GetAestheticScoringService(),
            vm.ConfirmDownloadAsync ?? (_ => Task.FromResult(false)));

        var win = new SchedulerTunerStepsSweepWindow { DataContext = stepsVm };
        win.Show(this);

        var stepsList = BuildStepsSweep(request.Parameters.Steps, request.Interval, request.CountPerSide, request.MinSteps, request.MaxSteps);

        await stepsVm.StartAsync(
            request.Scheduler,
            request.Parameters,
            stepsList,
            request.EnableAestheticScoring,
            request.EnableArtifactHeuristics,
            msg => Dispatcher.UIThread.Post(() => stepsVm.StatusText = msg));
    }

    private static IReadOnlyList<int> BuildStepsSweep(int baseSteps, int interval, int countPerSide, int minSteps, int maxSteps)
    {
        var steps = new HashSet<int>();
        var clampedInterval = Math.Max(1, interval);
        var clampedMin = Math.Max(1, minSteps);
        var clampedMax = Math.Max(clampedMin, maxSteps);
        var baseValue = Math.Clamp(baseSteps, clampedMin, clampedMax);

        for (var i = -countPerSide; i <= countPerSide; i++)
        {
            var value = baseValue + (i * clampedInterval);
            value = Math.Clamp(value, clampedMin, clampedMax);
            steps.Add(value);
        }

        return steps.OrderBy(v => v).ToList();
    }

    private async Task<bool> ShowConfirmAsync(string message)
    {
        var tcs = new TaskCompletionSource<bool>();
        var dialog = new Window
        {
            Width = 420,
            Height = 200,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Confirm",
            Content = new StackPanel
            {
                Margin = new Avalonia.Thickness(12),
                Spacing = 12,
                Children =
                {
                    new TextBlock { Text = message, TextWrapping = Avalonia.Media.TextWrapping.Wrap },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Right,
                        Spacing = 8,
                        Children =
                        {
                            new Button { Content = "Cancel" }
                        }
                    }
                }
            }
        };

        var buttons = dialog.Content as StackPanel;
        var actionBar = buttons?.Children[1] as StackPanel;
        var cancelButton = actionBar?.Children[0] as Button;
        if (cancelButton != null)
        {
            cancelButton.Click += (_, __) =>
            {
                tcs.TrySetResult(false);
                dialog.Close();
            };
        }
        var ok = new Button { Content = "OK" };
        ok.Click += (_, __) =>
        {
            tcs.TrySetResult(true);
            dialog.Close();
        };
        actionBar?.Children.Add(ok);

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(false);
            }
        };

        await dialog.ShowDialog(this);
        return await tcs.Task;
    }

    private List<SchedulerResultItem> GetSelectedResults()
    {
        if (ResultsList.SelectedItems == null) return new List<SchedulerResultItem>();
        return ResultsList.SelectedItems.OfType<SchedulerResultItem>().ToList();
    }
}
