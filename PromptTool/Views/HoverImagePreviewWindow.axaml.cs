using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media.Imaging;

namespace PromptTool.Views;

public partial class HoverImagePreviewWindow : Window
{
    private bool _isPanning;
    private Point _panStart;
    private Vector _offsetStart;

    public HoverImagePreviewWindow()
    {
        InitializeComponent();
    }

    public HoverImagePreviewWindow(Bitmap image, double maxWidth, double maxHeight)
    {
        InitializeComponent();
        DataContext = image;

        var width = Math.Min(image.PixelSize.Width, maxWidth);
        var height = Math.Min(image.PixelSize.Height, maxHeight);
        Width = Math.Max(240, width);
        Height = Math.Max(180, height);
    }

    private void PreviewImage_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (!e.GetCurrentPoint(this).Properties.IsLeftButtonPressed) return;
        _isPanning = true;
        _panStart = e.GetPosition(ImageScroll);
        _offsetStart = ImageScroll.Offset;
        PreviewImage.Cursor = new Cursor(StandardCursorType.Hand);
        e.Pointer.Capture(PreviewImage);
    }

    private void PreviewImage_PointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        _isPanning = false;
        PreviewImage.Cursor = new Cursor(StandardCursorType.Arrow);
        e.Pointer.Capture(null);
    }

    private void PreviewImage_PointerMoved(object? sender, PointerEventArgs e)
    {
        if (!_isPanning) return;
        var current = e.GetPosition(ImageScroll);
        var delta = current - _panStart;

        var newOffset = _offsetStart - delta;
        var maxX = Math.Max(0, ImageScroll.Extent.Width - ImageScroll.Viewport.Width);
        var maxY = Math.Max(0, ImageScroll.Extent.Height - ImageScroll.Viewport.Height);
        var clamped = new Vector(
            Math.Clamp(newOffset.X, 0, maxX),
            Math.Clamp(newOffset.Y, 0, maxY));
        ImageScroll.Offset = clamped;
    }

    private void Window_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            Close();
            e.Handled = true;
        }
    }

    private void CloseButton_Click(object? sender, RoutedEventArgs e)
    {
        Close();
    }
}
