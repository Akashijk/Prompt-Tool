using System;
using Avalonia;
using Avalonia.Controls;
using PromptTool.Core.Services;

namespace PromptTool.Views;

public partial class FavoritesViewerWindow : Window
{
    public FavoritesViewerWindow()
    {
        InitializeComponent();
        Opened += (_, __) => RestoreWindowState();
        Closing += (_, __) => SaveWindowState();
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

        if (settings.FavoritesViewerWindowWidth > 0 && settings.FavoritesViewerWindowHeight > 0)
        {
            Width = settings.FavoritesViewerWindowWidth;
            Height = settings.FavoritesViewerWindowHeight;
        }

        if (settings.FavoritesViewerWindowX != 0 || settings.FavoritesViewerWindowY != 0)
        {
            Position = new PixelPoint((int)settings.FavoritesViewerWindowX, (int)settings.FavoritesViewerWindowY);
        }

        if (Enum.TryParse<WindowState>(settings.FavoritesViewerWindowState, out var state))
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

        settings.FavoritesViewerWindowState = WindowState.ToString();
        if (WindowState == WindowState.Normal)
        {
            var bounds = Bounds;
            if (bounds.Width > 0 && bounds.Height > 0)
            {
                settings.FavoritesViewerWindowWidth = bounds.Width;
                settings.FavoritesViewerWindowHeight = bounds.Height;
                settings.FavoritesViewerWindowX = bounds.X;
                settings.FavoritesViewerWindowY = bounds.Y;
            }
        }

        _ = settingsService.SaveSettingsAsync(settings);
    }
}
