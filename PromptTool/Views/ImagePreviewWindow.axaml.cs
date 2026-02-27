using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media.Imaging;

namespace PromptTool.Views;

public partial class ImagePreviewWindow : Window
{
    private bool _isPanning;
    private Point _panStart;
    private Vector _offsetStart;

    public ImagePreviewWindow()
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

    public ImagePreviewWindow(Bitmap bitmap) : this()
    {
        SetImage(bitmap);
    }

    public void SetImage(Bitmap bitmap)
    {
        PreviewImage.Source = bitmap;
    }

    private void Image_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (e.GetCurrentPoint(this).Properties.IsLeftButtonPressed)
        {
            _isPanning = true;
            _panStart = e.GetPosition(PreviewScrollViewer);
            _offsetStart = PreviewScrollViewer.Offset;
            PreviewImage.Cursor = new Cursor(StandardCursorType.Hand);
            e.Pointer.Capture(PreviewImage);
        }
    }

    private void Image_PointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        _isPanning = false;
        PreviewImage.Cursor = new Cursor(StandardCursorType.Arrow);
        e.Pointer.Capture(null);
    }

    private void Image_PointerMoved(object? sender, PointerEventArgs e)
    {
        if (!_isPanning || !e.GetCurrentPoint(this).Properties.IsLeftButtonPressed)
        {
            return;
        }

        var current = e.GetPosition(PreviewScrollViewer);
        var delta = current - _panStart;
        var newOffset = new Vector(
            Math.Max(0, _offsetStart.X - delta.X),
            Math.Max(0, _offsetStart.Y - delta.Y));
        PreviewScrollViewer.Offset = newOffset;
    }

    private void Close_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        Close();
    }
}
