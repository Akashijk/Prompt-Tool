using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;

namespace PromptTool.Views;

public partial class SchedulerTunerImagePreviewWindow : Window
{
    private bool _isPanning;
    private Point _panStart;
    private Vector _panOffsetStart;

    public SchedulerTunerImagePreviewWindow()
    {
        InitializeComponent();
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            Close();
            e.Handled = true;
            return;
        }

        base.OnKeyDown(e);
    }

    private void ScrollViewer_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (sender is not ScrollViewer viewer) return;
        if (!e.GetCurrentPoint(viewer).Properties.IsLeftButtonPressed) return;

        _isPanning = true;
        _panStart = e.GetPosition(viewer);
        _panOffsetStart = viewer.Offset;
        e.Pointer.Capture(viewer);
        e.Handled = true;
    }

    private void ScrollViewer_PointerMoved(object? sender, PointerEventArgs e)
    {
        if (!_isPanning || sender is not ScrollViewer viewer) return;
        var current = e.GetPosition(viewer);
        var delta = current - _panStart;
        viewer.Offset = _panOffsetStart - delta;
    }

    private void ScrollViewer_PointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (sender is not ScrollViewer viewer) return;
        if (!_isPanning) return;
        _isPanning = false;
        e.Pointer.Capture(null);
        e.Handled = true;
    }
}
