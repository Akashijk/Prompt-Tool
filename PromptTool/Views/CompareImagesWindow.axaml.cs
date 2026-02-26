using System;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class CompareImagesWindow : Window
{
    private readonly ZoomPane _leftPane;
    private readonly ZoomPane _rightPane;

    public CompareImagesWindow()
    {
        InitializeComponent();
        SetInterpolation();
        _leftPane = new ZoomPane(LeftScrollViewer, LeftCanvas, LeftImage, LeftZoomSlider);
        _rightPane = new ZoomPane(RightScrollViewer, RightCanvas, RightImage, RightZoomSlider);
        HookZoom();
    }

    public CompareImagesWindow(CompareImagesViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        SetInterpolation();
        _leftPane = new ZoomPane(LeftScrollViewer, LeftCanvas, LeftImage, LeftZoomSlider);
        _rightPane = new ZoomPane(RightScrollViewer, RightCanvas, RightImage, RightZoomSlider);
        HookZoom();
    }

    private void HookZoom()
    {
        _leftPane.Hook();
        _rightPane.Hook();
    }

    private void SetInterpolation()
    {
        RenderOptions.SetBitmapInterpolationMode(LeftImage, BitmapInterpolationMode.None);
        RenderOptions.SetBitmapInterpolationMode(RightImage, BitmapInterpolationMode.None);
    }

    private sealed class ZoomPane
    {
        private readonly ScrollViewer _scrollViewer;
        private readonly Canvas _canvas;
        private readonly Image _image;
        private readonly Slider _slider;
        private bool _isPanning;
        private Point _panStart;
        private Vector _offsetStart;
        private double _imageWidth;
        private double _imageHeight;
        private TranslateTransform? _translate;
        private ScaleTransform? _scale;

        public ZoomPane(ScrollViewer scrollViewer, Canvas canvas, Image image, Slider slider)
        {
            _scrollViewer = scrollViewer;
            _canvas = canvas;
            _image = image;
            _slider = slider;
            InitializeTransforms();
        }

        public void Hook()
        {
            _image.PropertyChanged += ImageOnPropertyChanged;
            _slider.PropertyChanged += SliderOnPropertyChanged;
            _scrollViewer.SizeChanged += ScrollViewerOnSizeChanged;
            _canvas.PointerPressed += CanvasOnPointerPressed;
            _canvas.PointerReleased += CanvasOnPointerReleased;
            _canvas.PointerMoved += CanvasOnPointerMoved;
            _canvas.PointerWheelChanged += CanvasOnPointerWheelChanged;
            _slider.PointerWheelChanged += SliderOnPointerWheelChanged;
        }

        private void InitializeTransforms()
        {
            if (_image.RenderTransform is TransformGroup group)
            {
                _scale = group.Children.OfType<ScaleTransform>().FirstOrDefault();
                _translate = group.Children.OfType<TranslateTransform>().FirstOrDefault();
            }
        }

        private void CanvasOnPointerPressed(object? sender, PointerPressedEventArgs e)
        {
            if (!e.GetCurrentPoint(_canvas).Properties.IsLeftButtonPressed || !IsPannable()) return;
            _isPanning = true;
            _panStart = e.GetPosition(_scrollViewer);
            _offsetStart = new Vector(_translate?.X ?? 0, _translate?.Y ?? 0);
            _image.Cursor = new Cursor(StandardCursorType.Hand);
            e.Pointer.Capture(_canvas);
        }

        private void CanvasOnPointerReleased(object? sender, PointerReleasedEventArgs e)
        {
            _isPanning = false;
            _image.Cursor = new Cursor(StandardCursorType.Arrow);
            e.Pointer.Capture(null);
        }

        private void CanvasOnPointerMoved(object? sender, PointerEventArgs e)
        {
            if (!_isPanning || !e.GetCurrentPoint(_canvas).Properties.IsLeftButtonPressed)
            {
                return;
            }

            var current = e.GetPosition(_scrollViewer);
            var delta = current - _panStart;
            var scale = _slider.Value;
            var scaledWidth = _imageWidth * scale;
            var scaledHeight = _imageHeight * scale;

            var minX = Math.Min(0, _scrollViewer.Viewport.Width - scaledWidth);
            var minY = Math.Min(0, _scrollViewer.Viewport.Height - scaledHeight);

            var newX = Math.Clamp(_offsetStart.X + delta.X, minX, 0);
            var newY = Math.Clamp(_offsetStart.Y + delta.Y, minY, 0);

            if (_translate != null)
            {
                _translate.X = newX;
                _translate.Y = newY;
            }
        }

        private void CanvasOnPointerWheelChanged(object? sender, PointerWheelEventArgs e)
        {
            var delta = e.Delta.Y;
            if (Math.Abs(delta) < double.Epsilon) return;
            AdjustZoom(delta, e.GetPosition(_scrollViewer));
            e.Handled = true;
        }

        private void SliderOnPointerWheelChanged(object? sender, PointerWheelEventArgs e)
        {
            var delta = e.Delta.Y;
            if (Math.Abs(delta) < double.Epsilon) return;
            AdjustZoom(delta, new Point(_scrollViewer.Viewport.Width / 2, _scrollViewer.Viewport.Height / 2));
            e.Handled = true;
        }

        private void AdjustZoom(double delta, Point zoomCenter)
        {
            var currentScale = _slider.Value;
            var step = delta > 0 ? 1 : -1;
            var targetScale = Math.Clamp(Math.Round(currentScale) + step, _slider.Minimum, _slider.Maximum);
            if (Math.Abs(targetScale - currentScale) < 0.0001) return;

            var offsetBefore = new Vector(_translate?.X ?? 0, _translate?.Y ?? 0);
            var contentX = (zoomCenter.X - offsetBefore.X) / currentScale;
            var contentY = (zoomCenter.Y - offsetBefore.Y) / currentScale;

            _slider.Value = targetScale;

            var newOffsetX = zoomCenter.X - contentX * targetScale;
            var newOffsetY = zoomCenter.Y - contentY * targetScale;

            ApplyPan(newOffsetX, newOffsetY, targetScale);
        }

        private void ApplyPan(double newX, double newY, double scale)
        {
            var scaledWidth = _imageWidth * scale;
            var scaledHeight = _imageHeight * scale;

            if (scaledWidth <= _scrollViewer.Viewport.Width)
            {
                newX = (_scrollViewer.Viewport.Width - scaledWidth) / 2;
            }
            else
            {
                var minX = _scrollViewer.Viewport.Width - scaledWidth;
                newX = Math.Clamp(newX, minX, 0);
            }

            if (scaledHeight <= _scrollViewer.Viewport.Height)
            {
                newY = (_scrollViewer.Viewport.Height - scaledHeight) / 2;
            }
            else
            {
                var minY = _scrollViewer.Viewport.Height - scaledHeight;
                newY = Math.Clamp(newY, minY, 0);
            }

            if (_translate != null)
            {
                _translate.X = newX;
                _translate.Y = newY;
            }
        }

        private void ImageOnPropertyChanged(object? sender, AvaloniaPropertyChangedEventArgs e)
        {
            if (e.Property == Image.SourceProperty && _image.Source != null)
            {
                _imageWidth = _image.Source.Size.Width;
                _imageHeight = _image.Source.Size.Height;
                var initial = Math.Clamp(1.0, _slider.Minimum, _slider.Maximum);
                _slider.Value = initial;
                if (_scale != null)
                {
                    _scale.ScaleX = initial;
                    _scale.ScaleY = initial;
                }
                CenterImage();
            }
        }

        private void SliderOnPropertyChanged(object? sender, AvaloniaPropertyChangedEventArgs e)
        {
            if (e.Property == RangeBase.ValueProperty)
            {
                var scale = _slider.Value;
                var x = _translate?.X ?? 0;
                var y = _translate?.Y ?? 0;
                ApplyPan(x, y, scale);
                if (_scale != null)
                {
                    _scale.ScaleX = scale;
                    _scale.ScaleY = scale;
                }
            }
        }

        private void ScrollViewerOnSizeChanged(object? sender, SizeChangedEventArgs e)
        {
            CenterImage();
        }

        private void CenterImage()
        {
            var scale = _slider.Value;
            var scaledWidth = _imageWidth * scale;
            var scaledHeight = _imageHeight * scale;

            double x;
            double y;
            if (scaledWidth <= _scrollViewer.Viewport.Width)
            {
                x = (_scrollViewer.Viewport.Width - scaledWidth) / 2;
            }
            else
            {
                x = Math.Min(0, (_scrollViewer.Viewport.Width - scaledWidth) / 2);
            }

            if (scaledHeight <= _scrollViewer.Viewport.Height)
            {
                y = (_scrollViewer.Viewport.Height - scaledHeight) / 2;
            }
            else
            {
                y = Math.Min(0, (_scrollViewer.Viewport.Height - scaledHeight) / 2);
            }

            if (_translate != null)
            {
                _translate.X = x;
                _translate.Y = y;
            }
        }

        private bool IsPannable()
        {
            var scale = _slider.Value;
            return _imageWidth * scale > _scrollViewer.Viewport.Width || _imageHeight * scale > _scrollViewer.Viewport.Height;
        }
    }
}
