using System;
using System.Collections.Generic;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Threading;

namespace PromptTool.Services;

/// <summary>
/// Lightweight toast manager that does not rely on external packages.
/// Creates small, top-right floating windows that auto-dismiss.
/// </summary>
public class NotificationService
{
    private readonly List<ToastWindow> _openToasts = new();
    private Window? _anchor;

    public void Attach(Window window)
    {
        _anchor = window;
    }

    public void ShowInfo(string message, string? title = null) => Show(title ?? "Info", message, ToastType.Info);
    public void ShowWarning(string message, string? title = null) => Show(title ?? "Warning", message, ToastType.Warning);
    public void ShowError(string message, string? title = null) => Show(title ?? "Error", message, ToastType.Error);

    private void Show(string title, string message, ToastType type)
    {
        if (_anchor == null) return;

        void ShowOnUi()
        {
            var toast = new ToastWindow(title, message, type);
            toast.Closed += (_, __) => _openToasts.Remove(toast);
            _openToasts.Add(toast);

            PositionToast(toast);
            toast.Show(_anchor);
        }

        if (Dispatcher.UIThread.CheckAccess())
        {
            ShowOnUi();
        }
        else
        {
            Dispatcher.UIThread.Post(ShowOnUi);
        }
    }

    private void PositionToast(ToastWindow toast)
    {
        if (_anchor == null) return;

        // Stack from top-right, offset by existing toasts.
        const double margin = 12;
        const double spacing = 8;
        double width = 320;
        double height = 96;

        toast.Width = width;
        toast.Height = height;

        // If anchor is not shown yet, default to screen (0,0).
        var anchorPos = _anchor.Position;
        var anchorSize = _anchor.Bounds;

        var topOffset = margin;
        foreach (var t in _openToasts)
        {
            topOffset += t.Height + spacing;
        }

        toast.Position = new PixelPoint(
            (int)(anchorPos.X + anchorSize.Width - width - margin),
            (int)(anchorPos.Y + topOffset));
    }

    private enum ToastType { Info, Warning, Error }

    private sealed class ToastWindow : Window
    {
        private readonly DispatcherTimer _timer;

        public ToastWindow(string title, string message, ToastType type)
        {
            SystemDecorations = SystemDecorations.None;
            CanResize = false;
            ShowInTaskbar = false;
            Topmost = true;
            WindowStartupLocation = WindowStartupLocation.Manual;
            TransparencyLevelHint = new[] { WindowTransparencyLevel.Transparent };
            Background = Brushes.Transparent;
            Opacity = 0.97;

            var (bg, fg) = type switch
            {
                ToastType.Info => (Color.Parse("#1F6FEB"), Colors.White),
                ToastType.Warning => (Color.Parse("#D97706"), Colors.White),
                ToastType.Error => (Color.Parse("#B91C1C"), Colors.White),
                _ => (Color.Parse("#1F6FEB"), Colors.White)
            };

            Content = new Border
            {
                Background = new SolidColorBrush(bg),
                CornerRadius = new CornerRadius(8),
                Padding = new Thickness(12),
                Child = new StackPanel
                {
                    Spacing = 4,
                    Children =
                    {
                        new TextBlock { Text = title, FontWeight = FontWeight.Bold, Foreground = new SolidColorBrush(fg) },
                        new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap, Foreground = new SolidColorBrush(fg) }
                    }
                }
            };

            _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(4) };
            _timer.Tick += (_, __) =>
            {
                _timer.Stop();
                Close();
            };
            _timer.Start();
        }
    }
}
