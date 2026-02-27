using System;
using System.Collections.Generic;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia;
using PromptTool.ViewModels;
using ReactiveUI;
using PromptTool.Core.Config;

namespace PromptTool.Views;

public partial class PromptWindow : Window
{
    public PromptWindow()
        : this(null)
    {
    }

    public PromptWindow(AppSettings? settings)
    {
        if (settings != null)
        {
            ApplyInitialWindowState(settings);
        }
        InitializeComponent();
        Closing += OnClosing;
    }

    private async void SegmentPointerPressed(object? sender, PointerPressedEventArgs e)
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

        if (DataContext is not MainWindowViewModel vm)
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(segment.WildcardName))
        {
            return;
        }

        var choices = await vm.GetChoicesForWildcardAsync(segment.WildcardName);
        if (choices.Count == 0)
        {
            return;
        }

        var menuItems = new List<MenuItem>
        {
            new MenuItem { Header = $"Wildcard: {segment.WildcardName}", IsEnabled = false }
        };

        var menu = new ContextMenu { ItemsSource = menuItems }; // Declared here

        foreach (var choice in choices)
        {
            var menuItem = new MenuItem
            {
                Header = choice,
                IsChecked = string.Equals(choice, segment.Text, StringComparison.OrdinalIgnoreCase),
            };
            menuItem.Click += async (s, args) =>
            {
                if (vm != null && segment != null && choice != null)
                {
                    await vm.ApplyWildcardChoiceAsync(segment, choice);
                }
                menu.Close(); // Now menu is in scope
            };
            menuItems.Add(menuItem);
        }
        
        if (control == null) // This check is mostly for paranoia, as sender is already cast to Control
        {
            if (vm.SettingsService.Settings.Verbose) Console.WriteLine("SegmentPointerPressed: Control is null right before opening ContextMenu.");
            return;
        }
        menu.Open(control);
        if (vm.SettingsService.Settings.Verbose) Console.WriteLine("SegmentPointerPressed: ContextMenu opened.");
    }

    private void InsertWildcard_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is not Button button || button.Tag is not string wildcardName)
        {
            return;
        }

        if (DataContext is not MainWindowViewModel vm)
        {
            return;
        }

        var input = this.FindControl<TextBox>("PromptInputBox");
        var caret = input?.CaretIndex ?? vm.PromptText?.Length ?? 0;
        var selectionStart = input?.SelectionStart ?? caret;
        var selectionEnd = input?.SelectionEnd ?? caret;

        var (_, newCaret) = vm.InsertWildcardAtSelection(wildcardName, caret, selectionStart, selectionEnd);
        
        if (input != null)
        {
            input.CaretIndex = newCaret;
            input.SelectionStart = newCaret;
            input.SelectionEnd = newCaret;
            input.Focus();
        }
    }

    private void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        if (DataContext is not MainWindowViewModel vm)
        {
            return;
        }

        var settings = vm.SettingsService.Settings;
        settings.MainWindowState = WindowState.ToString();
        settings.LastPromptText = vm.PromptText ?? string.Empty;
        settings.LastTemplateName = vm.SelectedTemplate?.Name;
        settings.LastOllamaModel = vm.SelectedModel;

        if (WindowState == WindowState.Normal)
        {
            var bounds = Bounds;
            if (bounds.Width > 0 && bounds.Height > 0)
            {
                settings.MainWindowWidth = bounds.Width;
                settings.MainWindowHeight = bounds.Height;
                settings.MainWindowX = bounds.X;
                settings.MainWindowY = bounds.Y;
            }
        }

        _ = vm.SettingsService.SaveSettingsAsync(settings);
    }

    private void ApplyInitialWindowState(AppSettings settings)
    {
        if (Enum.TryParse<WindowState>(settings.MainWindowState, out var state) && state != WindowState.Normal)
        {
            WindowState = state;
            return;
        }

        if (settings.MainWindowWidth > 0 && settings.MainWindowHeight > 0)
        {
            Width = settings.MainWindowWidth;
            Height = settings.MainWindowHeight;
        }

        if (settings.MainWindowX != 0 || settings.MainWindowY != 0)
        {
            Position = new PixelPoint((int)settings.MainWindowX, (int)settings.MainWindowY);
        }
    }

}
