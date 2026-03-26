using System;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia;
using PromptTool.Core.Services;
using PromptTool.ViewModels;
using Avalonia.Controls.ApplicationLifetimes;

namespace PromptTool.Views;

public partial class AnalyticsStudioWindow : Window
{
    private bool _stateRestored;
    private AnalyticsStudioViewModel? _attachedVm;

    public AnalyticsStudioWindow()
    {
        InitializeComponent();
        ResultsScrollViewer.ScrollChanged += (_, __) => UpdateThumbnailPriority();
        Opened += (_, __) => UpdateThumbnailPriority();
        SizeChanged += (_, __) => UpdateThumbnailPriority();
        Closing += (_, __) => SaveWindowState();
        DataContextChanged += (_, __) => WireContext();
        Closed += OnClosed;
        RestoreWindowState();
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
        if (_stateRestored)
        {
            return;
        }
        _stateRestored = true;

        var settings = GetSettingsService()?.Settings;
        if (settings == null)
        {
            return;
        }

        if (Enum.TryParse<WindowState>(settings.AnalyticsWindowState, out var state) && state != WindowState.Normal)
        {
            WindowState = state;
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

        WindowState = WindowState.Normal;
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

    private void WireContext()
    {
        if (_attachedVm != null)
        {
            _attachedVm.ShowPngMetadataRequested = null;
        }

        if (DataContext is AnalyticsStudioViewModel vm)
        {
            _attachedVm = vm;
            vm.ShowPngMetadataRequested = ShowPngMetadataAsync;
        }
    }

    private void OnClosed(object? sender, EventArgs e)
    {
        if (_attachedVm != null)
        {
            _attachedVm.ShowPngMetadataRequested = null;
            _attachedVm.Dispose();
            _attachedVm = null;
        }
    }

    private async Task ShowPngMetadataAsync(string filePath)
    {
        var historyManager = (Application.Current as App)?.HistoryManagerService;
        var vm = new PngMetadataViewerViewModel(historyManager);
        var mainVm = (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow?.DataContext as MainWindowViewModel;
        if (mainVm != null)
        {
            vm.GenerateMergedRequested = mainVm.GenerateFromMergedPngAsync;
            vm.GenerateGraphReplayRequested = mainVm.GenerateFromPngGraphAsync;
            vm.BuildGenerationGraphJsonAsync = mainVm.BuildGenerationGraphJsonAsync;
            vm.ShowJsonDiffRequested = mainVm.ShowJsonDiffAsync;
        }
        var win = new PngMetadataViewerWindow(vm);
        win.Show(this);
        await vm.LoadFileAsync(filePath);
    }
}
