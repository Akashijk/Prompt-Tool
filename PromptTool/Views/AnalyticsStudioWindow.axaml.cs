using System;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia;
using PromptTool.Core.Services;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class AnalyticsStudioWindow : Window
{
    public AnalyticsStudioWindow()
    {
        InitializeComponent();
        ResultsScrollViewer.ScrollChanged += (_, __) => UpdateThumbnailPriority();
        Opened += (_, __) => UpdateThumbnailPriority();
        SizeChanged += (_, __) => UpdateThumbnailPriority();
        Opened += (_, __) => RestoreWindowState();
        Closing += (_, __) => SaveWindowState();
    }

    private void UpdateThumbnailPriority()
    {
        if (DataContext is not AnalyticsStudioViewModel vm) return;
        var viewport = ResultsScrollViewer.Viewport;
        var offset = ResultsScrollViewer.Offset;
        vm.UpdateThumbnailPriority(offset.Y, viewport.Height, viewport.Width);
    }

    private void OnImageDoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (sender is not Control control) return;
        if (control.DataContext is not AnalyticsImageItem item)
        {
            if (e.Source is Control source && source.DataContext is AnalyticsImageItem sourceItem)
            {
                item = sourceItem;
            }
            else
            {
                return;
            }
        }

        if (DataContext is AnalyticsStudioViewModel vm)
        {
            vm.ViewDetailsCommand.Execute(item);
        }
        e.Handled = true;
    }

    private SettingsService? GetSettingsService()
    {
        return (Application.Current as App)?.SettingsService;
    }

    private void RestoreWindowState()
    {
        var settings = GetSettingsService()?.Settings;
        if (settings == null)
        {
            return;
        }

        if (settings.AnalyticsWindowWidth > 0 && settings.AnalyticsWindowHeight > 0)
        {
            Width = settings.AnalyticsWindowWidth;
            Height = settings.AnalyticsWindowHeight;
        }

        if (settings.AnalyticsWindowX != 0 || settings.AnalyticsWindowY != 0)
        {
            Position = new PixelPoint((int)settings.AnalyticsWindowX, (int)settings.AnalyticsWindowY);
        }

        if (Enum.TryParse<WindowState>(settings.AnalyticsWindowState, out var state))
        {
            WindowState = state;
        }
    }

    private void SaveWindowState()
    {
        var settingsService = GetSettingsService();
        if (settingsService == null)
        {
            return;
        }
        var settings = settingsService.Settings;

        settings.AnalyticsWindowState = WindowState.ToString();
        if (WindowState == WindowState.Normal)
        {
            var bounds = Bounds;
            if (bounds.Width > 0 && bounds.Height > 0)
            {
                settings.AnalyticsWindowWidth = bounds.Width;
                settings.AnalyticsWindowHeight = bounds.Height;
                settings.AnalyticsWindowX = bounds.X;
                settings.AnalyticsWindowY = bounds.Y;
            }
        }

        _ = settingsService.SaveSettingsAsync(settings);
    }

}
